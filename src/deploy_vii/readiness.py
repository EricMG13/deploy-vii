"""CP-0: bind evidence-grounded readiness judgments to one frozen preparation pack."""

from typing import Literal, Self

from pydantic import ValidationError, model_validator

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
from deploy_vii.registry import canonical, plan

Readiness = Literal["READY", "READY_WITH_LIMITATIONS", "CONDITIONAL", "BLOCKED"]


class SourceAssessment(Contract):
    source_id: Identifier
    document_family: Text
    authority: Literal[
        "filed", "executed", "issuer", "management", "sponsor", "third_party", "unknown"
    ]
    entity: str | None
    period: str | None
    version_relationship: Text
    fidelity: Literal["verified", "degraded", "blocked"]
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
    kind: Literal["source", "parse", "identity", "period", "conflict", "authority", "scope"]
    severity: Literal["critical", "material", "minor"]
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


def citation_issues(
    citations: tuple[Citation, ...], sources: tuple[Source, ...]
) -> tuple[str, ...]:
    index = {source.source_id: source for source in sources}
    issues: list[str] = []
    for citation in citations:
        source = index.get(citation.source_id)
        if source is None or source.status != "ready" or source.sha256 != citation.source_sha256:
            issues.append(f"Unavailable or changed source: {citation.source_id}")
            continue
        span = next((item for item in source.spans if item.locator == citation.locator), None)
        if span is None or citation.quote not in span.text:
            issues.append(f"Quote/locator mismatch: {citation.source_id} {citation.locator}")
    return tuple(issues)


def validate_review(pack: PreparedPack, review: ReadinessReview) -> tuple[str, ...]:
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        review = ReadinessReview.model_validate_json(review.model_dump_json())
    except ValidationError as error:
        return (f"Invalid readiness contract: {error}",)

    issues: list[str] = []
    if review.pack_sha256 != pack.content_hash():
        issues.append("Review does not bind the current prepared pack")
    sources_by_id = {source.source_id: source for source in pack.sources}
    if len(review.sources) != len(sources_by_id) or {
        item.source_id for item in review.sources
    } != set(sources_by_id):
        issues.append("Assess every prepared source exactly once")
    selected = set(plan(pack.run.requested_modules)) - {"CP-0", "CP-MODEL", "CP-MEMO", "CP-OS"}
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
