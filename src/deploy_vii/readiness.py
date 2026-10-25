"""CP-0: bind evidence-grounded readiness judgments to one frozen preparation pack."""

import re
from collections.abc import Iterable
from typing import Literal, Self

from pydantic import ValidationError, model_validator
from pydantic_core import ErrorDetails

from deploy_vii.contracts import (
    Citation,
    Claim,
    Contract,
    Fact,
    Hash,
    Identifier,
    Input,
    Module,
    Source,
    Text,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.quotes import explain, prefix, quoted
from deploy_vii.registry import canonical, plan

Readiness = Literal["READY", "READY_WITH_LIMITATIONS", "CONDITIONAL", "BLOCKED"]
Authority = Literal[
    "filed", "executed", "issuer", "management", "sponsor", "third_party", "unknown"
]
Fidelity = Literal["verified", "degraded", "blocked"]
GapKind = Literal["source", "parse", "identity", "period", "conflict", "authority", "scope"]
GapSeverity = Literal["critical", "material", "minor"]
# Modules CP-0 does not assess: itself and the modules outside the live consumer set.
NOT_CONSUMERS = frozenset({"CP-0", "CP-MODEL", "CP-MEMO", "CP-OS"})


class SourceAssessment(Contract):
    source_id: Identifier
    document_family: Text
    authority: Authority
    entity: str | None
    period: str | None
    version_relationship: Text
    fidelity: Fidelity
    citations: tuple[Citation, ...]
    limitations: tuple[str, ...] = ()


class ConsumerReadiness(Contract):
    module_id: Identifier
    readiness: Readiness
    evidence_demand: Text
    source_ids: tuple[Identifier, ...]
    rationale: Text
    citations: tuple[Citation, ...]
    missing_source: str | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def limited(self) -> Self:
        if self.readiness != "READY" and not self.limitations:
            raise ValueError("non-ready consumer requires limitations")
        if self.readiness == "CONDITIONAL" and not self.missing_source:
            raise ValueError("conditional readiness requires a named missing source")
        return self


class ReadinessGap(Contract):
    gap_id: Identifier
    kind: GapKind
    severity: GapSeverity
    description: Text
    affected_modules: tuple[Identifier, ...]
    remediation: Text
    citations: tuple[Citation, ...] = ()


class ReadinessReview(Contract):
    schema_version: Literal["readiness-review/1"] = "readiness-review/1"
    pack_sha256: Hash
    objective: Text
    reporting_period: Text
    issuer_confirmed: bool
    sources: tuple[SourceAssessment, ...]
    consumers: tuple[ConsumerReadiness, ...]
    gaps: tuple[ReadinessGap, ...]
    analysis: tuple[Claim, ...]


class ReadinessAddendumContext(Contract):
    schema_version: Literal["readiness-addendum-context/1"] = "readiness-addendum-context/1"
    pack_sha256: Hash
    cp0_result_sha256: Hash
    base_requested_modules: tuple[Identifier, ...]
    target_requested_modules: tuple[Identifier, ...]
    added_modules: tuple[Identifier, ...]
    original_review: ReadinessReview
    previous_addenda: tuple[Hash, ...] = ()
    prior_consumers: tuple[ConsumerReadiness, ...] = ()
    prior_gaps: tuple[ReadinessGap, ...] = ()
    prior_analysis: tuple[Claim, ...] = ()


class ReadinessAddendum(Contract):
    schema_version: Literal["readiness-addendum/1"] = "readiness-addendum/1"
    context: ReadinessAddendumContext
    payload_sha256: Hash
    consumers: tuple[ConsumerReadiness, ...]
    gaps: tuple[ReadinessGap, ...]
    analysis: tuple[Claim, ...]
    implementation: Literal["implemented"] = "implemented"
    analytical_qualification: Literal["unrun"] = "unrun"
    rendering_acceptance: Literal["unrun"] = "unrun"
    native_host_qualification: Literal["unrun"] = "unrun"


class ReadinessAddendumSubmissionInput(Contract):
    payload: str
    context_sha256: str  # checked after the extension's established refusal/no-op guards


def shape_issues(error: ValidationError) -> tuple[str, ...]:
    """One issue per Pydantic error, short form `<field.path>: <message>`.

    No library URL and no `input_value` repr: the text is stable across library upgrades (replay
    compares it exactly) and small enough for a repair prompt. A whole-payload error (invalid
    JSON) has the path `(root)`."""
    errors = error.errors(include_url=False, include_input=False, include_context=False)
    return tuple(
        f"{'.'.join(str(part) for part in item['loc']) or '(root)'}: {item['msg']}"
        for item in errors
        if not _echoes_item_error(item, errors)
    )


def _echoes_item_error(item: ErrorDetails, errors: list[ErrorDetails]) -> bool:
    """A container min-length error beside an error inside that container (the items failed)."""
    return (
        item["type"] == "too_short"
        and item["msg"].startswith(("Tuple should have at least", "List should have at least"))
        and any(
            len(other["loc"]) > len(item["loc"]) and other["loc"][: len(item["loc"])] == item["loc"]
            for other in errors
        )
    )


def citation_issues(
    citations: tuple[Citation, ...], sources: tuple[Source, ...]
) -> tuple[str, ...]:
    """One issue per citation whose source, locator or quote does not hold in the pack.

    The locator is matched exactly; the quote with `deploy_vii.quotes` (layout normalisation,
    still a contiguous substring of that one span). The issue names the quote's prefix and,
    where `quotes.explain` finds one (task 7.0), why it failed; it never accepts a quote."""
    index = {source.source_id: source for source in sources}
    issues: list[str] = []
    for citation in citations:
        source = index.get(citation.source_id)
        if source is None or source.status != "ready" or source.sha256 != citation.source_sha256:
            issues.append(f"Unavailable or changed source: {citation.source_id}")
            continue
        position = next(
            (i for i, item in enumerate(source.spans) if item.locator == citation.locator), None
        )
        if position is None:
            issues.append(
                f"Quote/locator mismatch: no locator {citation.locator} in "
                f'{citation.source_id}: "{prefix(citation.quote)}"'
            )
            continue
        span = source.spans[position]
        if quoted(citation.quote, span.text):
            continue
        spans = source.spans
        following = (
            (spans[position + 1].locator, spans[position + 1].text)
            if position + 1 < len(spans)
            else None
        )
        preceding = (spans[position - 1].locator, spans[position - 1].text) if position else None
        why = explain(citation.quote, span.text, following, preceding)
        issues.append(
            f"Quote/locator mismatch: quote not found under {citation.source_id} "
            f'{citation.locator} ({why.label}): "{prefix(citation.quote)}"{why.hint}'
        )
    return tuple(issues)


def live_consumers(pack: PreparedPack) -> tuple[str, ...]:
    """The consumers a readiness review assesses, in plan order (CP-0 and non-consumers out)."""
    return tuple(item for item in plan(pack.run.requested_modules) if item not in NOT_CONSUMERS)


_PAGE = re.compile(r"page:([0-9]+)")


def page_numbers(source: Source) -> tuple[int, ...]:
    """The `page:N` numbers among the source's located spans, in span order."""
    return tuple(int(m.group(1)) for span in source.spans if (m := _PAGE.fullmatch(span.locator)))


def _runs(numbers: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for number in numbers:
        if runs and number == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], number)
        else:
            runs.append((number, number))
    return runs


def extraction_coverage(source: Source) -> dict[str, object]:
    """What the pack holds for one source, stated as facts for the prompt's CONTEXT block.

    Counts, the first and last locator, coverage records that are not `retained`, and (for a
    source located by `page:N` only) the page numbers missing between its first and last page."""
    locators = [span.locator for span in source.spans]
    record: dict[str, object] = {
        "located_spans": len(locators),
        "first_locator": locators[0] if locators else None,
        "last_locator": locators[-1] if locators else None,
        "coverage_not_retained": [
            f"{item.locator}: {item.status}"
            for item in source.coverage
            if item.status != "retained"
        ],
    }
    pages = page_numbers(source)
    if pages and len(pages) == len(locators):
        present = set(pages)
        missing = [n for n in range(min(pages), max(pages) + 1) if n not in present]
        record["pages_missing_between_first_and_last"] = [
            f"page:{a}" if a == b else f"page:{a} to page:{b}" for a, b in _runs(missing)
        ]
    return record


# A claim that pages are absent: a page range and an absence word in the same clause.
_PAGE_RANGE = re.compile(
    r"\bpages?\s*:?\s*([0-9]+)\s*(?:-|\u2013|\u2014|to|through)\s*(?:\[?pages?\s*:?\s*)?([0-9]+)",
    re.IGNORECASE,
)
_ABSENT = re.compile(
    r"\b(?:absent|missing|omitted|omits|omitting|unextracted|not (?:present|included|supplied|"
    r"delivered|extracted|contained))\b",
    re.IGNORECASE,
)
_CLAUSE = re.compile(r";|(?<=\.)\s+(?=[A-Z])")
# Statements that pages are NOT absent (probe-3: "no pages missing between the first and last
# locator", rule f followed): a negator, at most four words from a closed list, then the absence
# word; or the CONTEXT coverage field restated as empty. The closed list keeps a positive claim
# positive: "not complete with missing pages 53-96" and "pages 33-52 not present and also
# missing" still claim absence; so does "none of pages 53-96 are missing" (a range in between).
_FILLER = (
    r"(?:pages?|locators?|spans?|located|content|text|material|other|further|additional|more|"
    r"of|the|these|those|them|any|are|is|were|was|be|been|being|appear|appears|actually)"
)
_NEGATED = re.compile(
    rf"\b(?:no|none|not|nothing|without|zero)\s+(?:{_FILLER}\s+){{0,4}}"
    r"(?:missing|absent|omitted|unextracted)\b"
    r"|\bpages?\s+missing\s+between\s+(?:the\s+)?first\s+and\s+last(?:\s+(?:locators?|pages?))?"
    r"\s*[:=]\s*(?:none\b|nil\b|\[\s*\]|0\b)",
    re.IGNORECASE,
)
# "missing from pages 40-60": the range says where content was looked for, on pages the claim
# itself treats as present; that is a judgment about content, not an absence claim.
_LOCATIVE = re.compile(r"\b(?:from|in|on|within)\s+(?:\S+\s+){0,2}$", re.IGNORECASE)


def absent_page_ranges(text: str) -> tuple[tuple[int, int], ...]:
    """Page ranges `text` says are absent (`pages 33-52 not present`, `pages 12 to 180 ... are
    absent`; en and em dashes too). A range with no absence word in its clause is not one, nor
    is a range introduced by a locative preposition (`missing from pages 40-60`). A negated
    absence (`no pages missing`, `none missing`, `not missing`) or the coverage field restated
    as empty is not an absence word."""
    found: list[tuple[int, int]] = []
    for clause in _CLAUSE.split(text):
        clause = _NEGATED.sub(" ", clause)
        if _ABSENT.search(clause):
            found += [
                (int(m.group(1)), int(m.group(2)))
                for m in _PAGE_RANGE.finditer(clause)
                if int(m.group(1)) <= int(m.group(2)) and not _LOCATIVE.search(clause[: m.start()])
            ]
    return tuple(found)


def absence_issues(
    pack: PreparedPack, texts: Iterable[tuple[str, tuple[str, ...]]]
) -> tuple[str, ...]:
    """Texts that call a page range absent although the pack retains every page in it.

    Each text comes with the sources it is about (empty: every ready paged source). It is a
    contradiction only when every such source retains the whole range, so a claim that may
    concern another source, or a source without page locators, is never flagged."""
    paged = {
        source.source_id: set(page_numbers(source))
        for source in pack.sources
        if source.status == "ready" and page_numbers(source)
    }
    issues: list[str] = []
    for text, scope in texts:
        targets = list(dict.fromkeys(scope)) if scope else list(paged)
        if not targets or any(item not in paged for item in targets):
            continue  # about a source without page locators: nothing to compare against
        for first, last in absent_page_ranges(text):
            pages = set(range(first, last + 1))
            if all(pages <= paged[item] for item in targets):
                issues.append(
                    f"Absence claim contradicts extraction coverage: page:{first} to "
                    f"page:{last} retained in {', '.join(targets)}"
                )
    return tuple(issues)


def coverage_issues(pack: PreparedPack, review: ReadinessReview) -> tuple[str, ...]:
    """Limitations that call a page range absent although the pack retains every page in it.

    Each text is checked against the sources it is about: a source assessment's own source;
    otherwise the sources an item attaches or cites; otherwise every ready paged source."""
    texts: list[tuple[str, tuple[str, ...]]] = []
    for assessment in review.sources:
        texts += [(text, (assessment.source_id,)) for text in assessment.limitations]
    for consumer in review.consumers:
        scope = consumer.source_ids or tuple(item.source_id for item in consumer.citations)
        texts += [(text, scope) for text in consumer.limitations]
        texts += [(consumer.missing_source, scope)] if consumer.missing_source else []
    for gap in review.gaps:
        texts.append((gap.description, tuple(item.source_id for item in gap.citations)))
    for claim in review.analysis:
        scope = tuple(item.source_id for item in claim.citations)
        texts += [(claim.limitation, scope)] if claim.limitation else []
    return absence_issues(pack, texts)


def validate_review(pack: PreparedPack, review: ReadinessReview) -> tuple[str, ...]:
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        review = ReadinessReview.model_validate_json(review.model_dump_json())
    except ValidationError as error:
        return shape_issues(error)
    return _review_issues(pack, review, live_consumers(pack))


def _validate_review_for(
    pack: PreparedPack, review: ReadinessReview, expected: tuple[str, ...]
) -> tuple[str, ...]:
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        review = ReadinessReview.model_validate_json(review.model_dump_json())
    except ValidationError as error:
        return shape_issues(error)
    return _review_issues(pack, review, expected)


def _review_issues(
    pack: PreparedPack, review: ReadinessReview, expected: tuple[str, ...]
) -> tuple[str, ...]:
    issues: list[str] = []
    if review.pack_sha256 != pack.content_hash():
        issues.append("Review does not bind the current prepared pack")
    sources_by_id = {source.source_id: source for source in pack.sources}
    if len(review.sources) != len(sources_by_id) or {
        item.source_id for item in review.sources
    } != set(sources_by_id):
        issues.append("Assess every prepared source exactly once")
    selected = set(expected)
    if (
        len(review.consumers) != len(selected)
        or {item.module_id for item in review.consumers} != selected
    ):
        issues.append("Assess each selected canonical live consumer exactly once")
    if len({item.gap_id for item in review.gaps}) != len(review.gaps):
        issues.append("Duplicate gap identity")
    if not review.analysis:
        issues.append("Source readiness requires an evidence-grounded analytical read-through")

    for source_review in review.sources:
        source = sources_by_id.get(source_review.source_id)
        if source is None:
            continue
        if source.status != "ready" and source_review.fidelity != "blocked":
            issues.append(f"Unavailable source cannot pass fidelity: {source.source_id}")
        if source.status == "ready" and not source_review.citations:
            issues.append(f"Source classification must cite content: {source.source_id}")
        if source_review.fidelity != "verified" and not source_review.limitations:
            issues.append(f"Limited fidelity requires explanation: {source.source_id}")
        if (
            source_review.authority == "unknown"
            or not source_review.entity
            or not source_review.period
        ) and not source_review.limitations:
            issues.append(
                f"Unresolved source classification requires limitation: {source.source_id}"
            )
        if any(citation.source_id != source.source_id for citation in source_review.citations):
            issues.append(f"Classification cites a different source: {source.source_id}")
        issues.extend(citation_issues(source_review.citations, pack.sources))

    assessments_by_id = {item.source_id: item for item in review.sources}
    for consumer in review.consumers:
        try:
            owner = canonical(consumer.module_id)
        except ValueError:
            issues.append(f"Unknown consumer: {consumer.module_id}")
            continue
        if owner != consumer.module_id:
            issues.append(f"Alias is not a separate consumer: {consumer.module_id}")
        if len(set(consumer.source_ids)) != len(consumer.source_ids):
            issues.append(f"Duplicate consumer source: {consumer.module_id}")
        runnable = consumer.readiness in {"READY", "READY_WITH_LIMITATIONS"}
        for source_id in consumer.source_ids:
            source = sources_by_id.get(source_id)
            assessment = assessments_by_id.get(source_id)
            if (
                source is None
                or source.status != "ready"
                or assessment is None
                or assessment.fidelity == "blocked"
            ):
                issues.append(
                    f"Consumer attaches unusable source: {consumer.module_id} {source_id}"
                )
            elif consumer.readiness == "READY" and (
                source.limitation or assessment.limitations or assessment.fidelity != "verified"
            ):
                issues.append(
                    f"Consumer must carry source limitations: {consumer.module_id} {source_id}"
                )
        if runnable and (not consumer.source_ids or not consumer.citations):
            issues.append(f"Runnable consumer needs located evidence: {consumer.module_id}")
        if any(citation.source_id not in consumer.source_ids for citation in consumer.citations):
            issues.append(f"Consumer citation not in its attachment set: {consumer.module_id}")
        if not review.issuer_confirmed and runnable:
            issues.append(f"Issuer unconfirmed: {consumer.module_id}")
        issues.extend(citation_issues(consumer.citations, pack.sources))

    for gap in review.gaps:
        issues.extend(citation_issues(gap.citations, pack.sources))
        if not set(gap.affected_modules) <= selected | {"CP-0"}:
            issues.append(f"Gap names unselected consumers: {gap.gap_id}")
        for consumer in review.consumers:
            if consumer.module_id in gap.affected_modules and consumer.readiness == "READY":
                issues.append(f"Consumer omits relevant gap: {consumer.module_id} {gap.gap_id}")

    for claim in review.analysis:
        if not claim.citations and not claim.limitation:
            issues.append(f"Unsupported readiness claim: {claim.claim_id}")
        issues.extend(citation_issues(claim.citations, pack.sources))

    issues.extend(coverage_issues(pack, review))
    return tuple(dict.fromkeys(issues))


def build_readiness(pack: PreparedPack, review: ReadinessReview, *, attempt: int = 0) -> Module:
    """Produce a candidate only; a later acceptance receipt controls promotion."""
    issues = validate_review(pack, review)
    if issues:
        raise ValueError("; ".join(issues))
    pack = PreparedPack.model_validate_json(pack.model_dump_json())
    review = ReadinessReview.model_validate_json(review.model_dump_json())
    facts: list[Fact] = []

    def field(
        table: str, row: str, key: str, value: str, citations: tuple[Citation, ...] = ()
    ) -> None:
        facts.append(
            Fact(
                fact_id=f"{table}.{row}.{key}",
                label=key.replace("_", " "),
                table_id=table,
                row_id=row,
                field=key,
                text=value,
                citations=citations,
            )
        )

    field("T1", "run", "objective", review.objective)
    field("T1", "run", "issuer", pack.run.issuer_name)
    field("T1", "run", "reporting_period", review.reporting_period)
    field("T1", "run", "identity_gate", "confirmed" if review.issuer_confirmed else "blocked")
    by_source = {item.source_id: item for item in review.sources}
    for source in pack.sources:
        assessment = by_source[source.source_id]
        for key, value in (
            ("family", assessment.document_family),
            ("entity", assessment.entity or "Unconfirmed"),
            ("period", assessment.period or "Unconfirmed"),
            ("version_relationship", assessment.version_relationship),
        ):
            field("P3", source.source_id, key, value, assessment.citations)
        field(
            "P5",
            source.source_id,
            "preparation",
            f"{source.extraction_status}; fidelity {assessment.fidelity}; "
            f"{source.limitation or 'No mechanical limitation'}",
        )
        field(
            "T2",
            source.source_id,
            "source",
            f"{source.name}; {source.status}; SHA-256 {source.sha256 or 'Unavailable'}",
        )
        field("T3", source.source_id, "authority", assessment.authority, assessment.citations)
        for index, citation in enumerate(assessment.citations):
            field("T6", source.source_id, f"evidence_{index}", citation.quote, (citation,))
    order = plan(pack.run.requested_modules)
    for consumer in sorted(review.consumers, key=lambda item: order.index(item.module_id)):
        field("T4", consumer.module_id, "demand", consumer.evidence_demand, consumer.citations)
        field("T4", consumer.module_id, "readiness", consumer.readiness)
        field("T4", consumer.module_id, "rationale", consumer.rationale, consumer.citations)
        field("T8", consumer.module_id, "candidate_command", "Run " + consumer.module_id)
        command = (
            "Run " + consumer.module_id
            if consumer.readiness in {"READY", "READY_WITH_LIMITATIONS"}
            else "DO NOT RUN"
        )
        field("T8", consumer.module_id, "exact_command", command)
        field("T8", consumer.module_id, "sources", ", ".join(consumer.source_ids) or "None")
        consumer_limits = list(consumer.limitations)
        for source in pack.sources:
            if source.source_id in consumer.source_ids:
                if source.limitation:
                    consumer_limits.append(source.limitation)
                consumer_limits.extend(by_source[source.source_id].limitations)
        consumer_limits.extend(
            gap.description for gap in review.gaps if consumer.module_id in gap.affected_modules
        )
        field(
            "T8",
            consumer.module_id,
            "limits",
            "; ".join(dict.fromkeys(consumer_limits)) or "None identified",
        )
        field(
            "T8",
            consumer.module_id,
            "upstream",
            "CP-0 " + pack.run.run_id + "; analytical dependencies checked separately",
        )
    for gap in review.gaps:
        field(
            "T5",
            gap.gap_id,
            "gap",
            f"{gap.kind}/{gap.severity}: {gap.description}; "
            f"affects {', '.join(gap.affected_modules)}; {gap.remediation}",
            gap.citations,
        )
    if not review.gaps:
        field("T5", "review", "gaps", "No gaps identified by this supplied review")
    field("T7", "run", "preparation", pack.content_hash())
    field("T7", "run", "method", pack.run.method_version)
    field(
        "T7",
        "run",
        "assertion_scope",
        "SOURCE_SUFFICIENCY_ONLY; CP_MODEL_INPUT_CONTRACT_NOT_EVALUATED",
    )
    for table in ("P3", "P5", "T2", "T3", "T4", "T6", "T8"):
        if not any(fact.table_id == table for fact in facts):
            field(table, "unavailable", "status", "No records available; no readiness assertion")
    limitations = tuple(
        dict.fromkeys(
            [source.limitation for source in pack.sources if source.limitation]
            + [text for item in review.sources for text in item.limitations]
            + [text for item in review.consumers for text in item.limitations]
            + [item.description for item in review.gaps]
            + (["Issuer identity is unconfirmed"] if not review.issuer_confirmed else [])
            + (
                ["Synthetic case; not real issuer qualification"]
                if pack.run.case_kind == "synthetic"
                else []
            )
        )
    )
    return Module(
        run_id=pack.run.run_id,
        issuer_id=pack.run.issuer_id,
        as_of=pack.run.as_of,
        module_id="CP-0",
        facts=tuple(facts),
        claims=review.analysis,
        inputs=(
            Input(input_id="prepared-pack", sha256=pack.content_hash()),
            Input(input_id="readiness-review", sha256=review.content_hash()),
        ),
        limitations=limitations,
        attempt=attempt,
    )
