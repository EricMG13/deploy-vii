"""CP-4 legal covenant interpreter (task 8.2): one live step, `legal_covenants`.

Decision 0008 MC-1, as for CP-1A: the model returns a `CovenantInterpretationSubmission`,
judgments and verbatim quotes only. It reads the executed and filed sources of the pack (CP-0's
authority classes, coordinator ruling 1) and judges what each clause permits and prohibits; it
supplies no hash, no id Python can assign, no computed amount and no compliance verdict.
`validate_covenant_interpretation` holds it to the CP-0 citation rules (restricted to executed or
filed sources), the run-text rule (figures only as `{ref|unit}` references to the CP-1 figures
offered in CONTEXT), the bound T4.18 facility ids, the prohibited conclusions and the rule that
each stated threshold value is the number Python parses out of its own quote (ruling 2).

Python then owns every number: headroom is `headroom(threshold, comparison, metric)` over the
parsed threshold and the CP-1 metric the row names, only when CP-1 is bound unblocked, the
threshold is a ratio or percentage, the metric's unit matches and the model judged the covenant
definition the same as CP-1's; otherwise the cell is "not calculable" with its reason, never
zero (`docs/frontend-direction-c.md`). Basket capacity amounts are not computed in M8 and are
shown as unsettled. A blocked CP-1 (decision 0007: the `CP-1 -> CP-4` edge is `restricted`)
reaches CP-4 as an input with status `blocked`: the step still runs, every headroom is not
calculable and the journal settles CP-4 `restricted` with the inherited limitation.

The 31 r14 table ids are composed minimally from the rows (ruling 4). The r14 CP-4 SKILL.md and
its column definitions are not in this repository, so each id's title and columns are Deploy
VII's placement, recorded in `methods/cp4.md`, not r14's layout.
"""

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ValidationError

from deploy_vii import prose
from deploy_vii.business_context import (
    _PROHIBITED,
    NO_EVIDENCE,
    NONE_STATED,
    Cell,
    Gap,
    Quote,
    Register,
    Severity,
    _Bound,
    _register,
    _trace,
    referencable,
    spelled,
)
from deploy_vii.contracts import (
    Citation,
    Claim,
    Contract,
    Fact,
    Hash,
    Input,
    InputStatus,
    Module,
    ReportTable,
    Run,
    TableColumn,
    TableRow,
    Text,
)
from deploy_vii.execution import Attempt, Execution, Qualification, StepValidation, text_sha256
from deploy_vii.preparation import PreparedPack
from deploy_vii.quotes import normalise, quoted
from deploy_vii.readiness import (
    absence_issues,
    citation_issues,
    extraction_coverage,
    shape_issues,
)
from deploy_vii.report_view import figure_unit

__all__ = ["Gap", "Quote"]  # re-exported: the CP-4 contract reuses CP-1A's rows

MODULE_ID = "CP-4"
STEP_ID = "legal_covenants"
CP4_STEPS = (STEP_ID,)
SCHEMA_VERSION = "covenant-interpretation/1"
PROMOTED = Qualification(implementation="implemented")
CP0 = "CP-0"
CP1 = "CP-1"
PACK_INPUT = "prepared-pack"
SUBMISSION_INPUT = "covenant-interpretation-submission"
# Ruling 1: the step cites only the sources CP-0 classes as executed or filed.
LEGAL_AUTHORITIES = frozenset({"executed", "filed"})
# The CP-1 registers whose figures the step may reference: the KPI dashboard and the EBITDA bridge.
FIGURE_TABLES = ("T4.10", "T4.17")
FACILITY_TABLE = "T4.18"
NOT_CALCULABLE = "Not calculable"
_SETTLED: Mapping[str, InputStatus] = {
    "accepted": "accepted",
    "restricted": "restricted",
    "blocked": "blocked",
}

# --- the model-facing contract ---------------------------------------------------------------
# Plain `str` fields and `Literal` enums, as in CP-1A; every field is required (no defaults).

CovenantKind = Literal["maintenance", "incurrence", "negative", "other"]
# How the CP-1 metric must stand against the threshold for the test to hold.
Comparison = Literal["<=", "<", ">=", ">", "none"]
ThresholdUnit = Literal["multiple", "percent", "other", "not stated"]
DefinitionBasis = Literal["Same definition", "Different definition", "Not determinable"]
Rating = Literal["Strong", "Adequate", "Weak", "Insufficient Information"]
NOT_STATED = "not stated"


class LegalDocument(Contract):
    """One governing document, by its pack source (the CP-0 authority is Python's)."""

    source_id: str
    document_family: str
    governing_entity: str
    date_or_amendment: str
    citations: tuple[Quote, ...]
    limitation: str | None


class Covenant(Contract):
    name: str
    kind: CovenantKind
    document_id: str  # the governing document: a `documents` row's source_id
    clause: str
    definition_text: str
    test_formula: str
    # A verbatim part of one of the row's quotes, or "not stated" (with unit "not stated").
    threshold_text: str
    threshold_unit: ThresholdUnit
    # The number as the quote writes it (12.5 for 12.5%, 5.00 for 5.00 to 1.00); Python parses
    # the quote and rejects a value that differs. Null unless the unit is multiple or percent.
    threshold_value: str | None
    comparison: Comparison
    metric_ref: str | None  # a CP-1 figure offered in CONTEXT that the test compares
    metric_basis: DefinitionBasis  # whether the covenant definition is CP-1's for that figure
    facility_ids: tuple[str, ...]
    period_scope: str
    citations: tuple[Quote, ...]
    limitation: str | None


class Basket(Contract):
    basket: str
    permits: str
    conditions: str
    citations: tuple[Quote, ...]
    limitation: str | None


class RedFlag(Contract):
    flag: str
    mechanic: str
    implication: str
    severity: Severity
    citations: tuple[Quote, ...]


class ProtectionScore(Contract):
    rating: Rating
    rationale: str
    basis: str
    citations: tuple[Quote, ...]
    limitation: str | None


class CovenantInterpretationSubmission(Contract):
    """What the model returns for `legal_covenants`; every field is required (no defaults)."""

    documents: tuple[LegalDocument, ...]
    covenants: tuple[Covenant, ...]
    capacity: tuple[Basket, ...]
    red_flags: tuple[RedFlag, ...]
    protection_score: ProtectionScore
    gaps: tuple[Gap, ...]


class CovenantInterpretationReport(Contract):
    schema_version: Literal["covenant-interpretation/1"] = "covenant-interpretation/1"
    run: Run
    pack_sha256: Hash
    submission_sha256: Hash
    tables: tuple[ReportTable, ...]
    facts: tuple[Fact, ...]
    claims: tuple[Claim, ...]
    limitations: tuple[Text, ...]


# --- what the bound inputs supply (Python-built, never the model's) -----------------------------


@dataclass(frozen=True)
class Upstream:
    """What CP-4 reads from its bound CP-0 and CP-1 heads."""

    cp0_sha256: str
    cp1_sha256: str
    cp1_status: InputStatus
    authority: Mapping[str, str]  # pack source id -> CP-0 authority class
    legal_sources: tuple[str, ...]  # ready pack sources CP-0 classes executed or filed
    facilities: Mapping[str, str | None]  # T4.18 facility id -> facility name
    facts: tuple[Fact, ...]  # the referencable CP-1 figures offered (none when CP-1 is blocked)
    rows: Mapping[tuple[str, str], str]  # (table, row) -> the CP-1 row label of an offered fact
    cp1_gaps: tuple[str, ...]  # what CP-1 carries forward (its own and inherited limitations)

    @property
    def blocked(self) -> bool:
        return self.cp1_status == "blocked"


def cp4_upstream(pack: PreparedPack, cp0: Module, cp1: Module) -> Upstream:
    """The CP-4 view of the CP-0 and CP-1 modules an attempt binds. A blocked CP-1 offers no
    figure and no facility; its limitations are carried with the decision 0007 wording."""
    if cp0.module_id != CP0 or cp1.module_id != CP1:
        raise ValueError("CP-4 reads the CP-0 and CP-1 modules")
    status = _SETTLED.get(cp1.status)
    if status is None:
        raise ValueError(f"CP-1 is {cp1.status}; CP-4 binds a settled CP-1 only")
    authority = {
        fact.row_id: fact.text
        for fact in cp0.facts
        if fact.table_id == "T3" and fact.field == "authority" and fact.text is not None
    }
    ready = {s.source_id for s in pack.sources if s.status == "ready"}
    legal = tuple(
        s.source_id
        for s in pack.sources
        if s.source_id in ready and authority.get(s.source_id) in LEGAL_AUTHORITIES
    )
    blocked = status == "blocked"
    names: dict[str, str | None] = {}
    if not blocked:
        by_row = {(f.row_id, f.field): f.text for f in cp1.facts if f.table_id == FACILITY_TABLE}
        for (row_id, field), text in by_row.items():
            if field == "facility_id" and text is not None:
                names.setdefault(text, by_row.get((row_id, "facility_name")))
    facts = () if blocked else referencable(f for f in cp1.facts if f.table_id in FIGURE_TABLES)
    labels = {(t.table_id, r.row_id): r.label for t in cp1.tables for r in t.rows}
    gaps = (
        tuple(f"Upstream {CP1} blocked: {text}" for text in cp1.limitations)
        if blocked
        else (*cp1.limitations, *cp1.inherited_limitations)
    )
    return Upstream(
        cp0_sha256=cp0.content_hash(),
        cp1_sha256=cp1.content_hash(),
        cp1_status=status,
        authority=authority,
        legal_sources=legal,
        facilities=names,
        facts=facts,
        rows={(f.table_id, f.row_id): labels.get((f.table_id, f.row_id), f.row_id) for f in facts},
        cp1_gaps=tuple(dict.fromkeys(gaps)),
    )


def upstream_of(store: Execution, attempt: Attempt) -> Upstream:
    """The `Upstream` of the CP-0 and CP-1 heads `attempt` binds (the registry requires both)."""
    bound = {item.input_id: item for item in attempt.inputs}
    if attempt.module_id != MODULE_ID or CP0 not in bound or CP1 not in bound:
        raise ValueError("The attempt is not a CP-4 attempt binding CP-0 and CP-1")
    return cp4_upstream(
        store.pack(), store.result(bound[CP0].sha256), store.result(bound[CP1].sha256)
    )


# --- thresholds and headroom (Python arithmetic) ---------------------------------------------

_NUMBER = r"([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
# A number starts after no letter, digit or digit-separator pair ("1,000" is one number) and the
# ratio's denominator ends before no further digit ("1.00," ends at the comma).
_BEFORE = r"(?<![0-9A-Za-z])(?<![0-9][.,])"
_AFTER = r"(?![0-9A-Za-z])"
_END = r"(?![0-9]|[.,][0-9])"
# "N to D" with any denominator; "N:1" only to one (confidence review: "12:00" is a clock time).
_RATIO = re.compile(
    rf"{_BEFORE}{_NUMBER}\s*(?:to\s*{_NUMBER}|:\s*(1(?:\.0+)?)){_END}", re.IGNORECASE
)
_TIMES = re.compile(rf"{_BEFORE}{_NUMBER}\s*(?:x|\u00d7|times){_AFTER}", re.IGNORECASE)
_PERCENT = re.compile(rf"{_BEFORE}{_NUMBER}\s*(?:%|percent|per cent){_AFTER}", re.IGNORECASE)


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def parse_threshold(text: str, unit: str) -> tuple[Decimal | None, str | None]:
    """The one threshold a quoted text states, as written (a ratio N to one is N, a multiple
    N x is N, a percentage is its number: 12.5 for 12.5%), or None with the reason it cannot be
    read. A ratio to anything but one is not read: Python would have to divide a number the
    model never wrote. Only the multiple and percent forms are read."""
    plain = normalise(text)
    values: list[Decimal] = []
    issue: str | None = None
    if unit == "multiple":
        for match in _RATIO.finditer(plain):
            numerator, denominator = _decimal(match[1]), _decimal(match[2] or match[3])
            if denominator == 0:
                issue = "the ratio has a zero denominator"
            elif denominator != 1:
                issue = "a ratio to other than one is not read; set threshold_unit to other"
            else:  # "5.00 to 1.00" keeps its written 5.00
                values.append(numerator)
        # A ratio's own numbers are read once: the "N times" form is searched outside them.
        values += [_decimal(m[1]) for m in _TIMES.finditer(_RATIO.sub(" ", plain))]
    elif unit == "percent":
        values = [_decimal(m[1]) for m in _PERCENT.finditer(plain)]
    else:
        return None, f"a {unit} threshold is not parsed"
    if issue is not None:
        return None, issue
    if not values:
        return None, f"no {unit} threshold is written in it"
    if len(values) > 1:
        return None, "it states more than one threshold; quote the one tested"
    return values[0], None


@dataclass(frozen=True)
class Headroom:
    """Room between the metric and the threshold on the permitted side, in the metric's unit
    (negative outside the threshold); its share of the threshold's size; whether the test holds."""

    amount: Decimal
    share: Decimal | None
    share_reason: str | None
    within: bool


def headroom(threshold: Decimal, comparison: Comparison, metric: Decimal) -> Headroom:
    """A maximum test (`<=`, `<`) has threshold minus metric of room, a minimum test (`>=`, `>`)
    metric minus threshold; a strict test does not hold at the threshold itself. The share
    divides the room by the threshold's absolute value; a zero threshold has no share."""
    if comparison in ("<=", "<"):
        room = threshold - metric
        within = room > 0 or (room == 0 and comparison == "<=")
    elif comparison in (">=", ">"):
        room = metric - threshold
        within = room > 0 or (room == 0 and comparison == ">=")
    else:
        raise ValueError("A test without a comparison has no headroom")
    if threshold == 0:
        return Headroom(room, None, "The threshold is zero: no share of it is calculable", within)
    return Headroom(room, room / abs(threshold), None, within)


# --- validation ------------------------------------------------------------------------------

_NOT_PROSE = frozenset({"source_id", "document_id", "metric_ref", "threshold_text"})
_NOT_PROSE |= {"threshold_value"}
_TEXT = (str, str | None)
_UNIT_OF: Mapping[str, frozenset[str]] = {
    "multiple": frozenset({"MULTIPLE"}),
    "percent": frozenset({"PERCENT", "decimal_fraction"}),
}
# Python owns compliance and headroom: run text states neither (a guard over phrases, not a
# semantic review, as `prohibited_issues`). Naming the test a clause sets ("must comply with
# the leverage test") or the analysis a gap affects ("covenant tests and headroom") is not a
# status, and is allowed; an amount or a status of headroom ("ample headroom", "headroom is",
# "a cushion of") and a compliance status ("is in compliance", "has breached") are refused.
# Finite verbs only (confidence review): "must remain in compliance" and "subject to the issuer
# being in compliance" are obligations and conditions a clause sets, not a status.
_STATUS = r"(?:is|was|are|were|remains|remained|stays|stayed|been)"
_ROOM = r"(?:headroom|cushion)"
_SIZE = (
    r"(?:ample|sufficient|insufficient|limited|tight|comfortable|significant|substantial|"
    r"adequate|enough|considerable|meaningful|modest|thin|narrow|wide|large|small|healthy|"
    r"good|minimal|little|no|some|plenty of|more|less)"
)
# CP-1A's prohibited conclusions (`business_context.PROHIBITED`, `NEAR_INSTRUMENT`), less the
# phrases that are contract mechanics in a legal reading (confidence review): "the notes must be
# repaid in full upon a change of control" is a repayment term, not a recovery outcome.
_LEGAL_MECHANICS = frozenset({"repaid in full"})
_PROHIBITED_HERE = tuple(item for item in _PROHIBITED if item[1] not in _LEGAL_MECHANICS)
_PYTHON_OWNED = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        rf"(?<![A-Za-z]){_SIZE} (?:covenant )?{_ROOM}(?![A-Za-z])",
        rf"(?<![A-Za-z]){_ROOM} (?:of|{_STATUS})(?![A-Za-z])",
        rf"(?<![A-Za-z]){_STATUS} (?:in compliance|compliant|in breach|non-?compliant)(?![A-Za-z])",
        r"(?<![A-Za-z])(?:has|have|had) (?:complied|breached)(?![A-Za-z])",
    )
)


def _rows(submission: CovenantInterpretationSubmission) -> Iterator[tuple[str, BaseModel]]:
    for name in type(submission).model_fields:
        value = getattr(submission, name)
        if isinstance(value, BaseModel):
            yield name, value
            continue
        for index, row in enumerate(value):
            yield f"{name}[{index}]", row


def _quotes(row: BaseModel) -> tuple[Quote, ...]:
    citations = getattr(row, "citations", ())
    assert isinstance(citations, tuple)
    return citations


def _texts(row: BaseModel) -> Iterator[tuple[str, str]]:
    """(field, value) of each prose field of one row; identifiers, enums and quotes excluded."""
    for name, info in type(row).model_fields.items():
        value = getattr(row, name)
        if name not in _NOT_PROSE and info.annotation in _TEXT and value is not None:
            yield name, value


def _bind(pack: PreparedPack, submission: CovenantInterpretationSubmission) -> _Bound:
    """Each quote as a `Citation` with the pack's source hash; an unbindable one is reported
    ("Unavailable or changed source", the CP-0 validator's wording) and left out."""
    digests = {s.source_id: s.sha256 for s in pack.sources if s.status == "ready" and s.sha256}
    bound: dict[int, tuple[Citation, ...]] = {}
    issues: list[str] = []
    for path, row in _rows(submission):
        cited: list[Citation] = []
        for quote in _quotes(row):
            digest = digests.get(quote.source_id)
            if digest is None:
                issues.append(f"Unavailable or changed source: {quote.source_id}")
                continue
            try:
                cited.append(
                    Citation(
                        source_id=quote.source_id,
                        source_sha256=digest,
                        locator=quote.locator,
                        quote=quote.quote,
                    )
                )
            except ValidationError:
                issues.append(f"{path}: malformed citation (empty locator or quote)")
        bound[id(row)] = tuple(cited)
    return _Bound(bound, tuple(dict.fromkeys(issues)))


def stale_issues(
    pack: PreparedPack, upstream: Upstream, inputs: Sequence[Input]
) -> tuple[str, ...]:
    """The bound inputs differ from what CP-4 read: the pack, CP-0 or CP-1 (hash and status)."""
    bound = {item.input_id: item for item in inputs}
    expected = (
        (PACK_INPUT, pack.content_hash(), None),
        (CP0, upstream.cp0_sha256, None),
        (CP1, upstream.cp1_sha256, upstream.cp1_status),
    )
    issues: list[str] = []
    for input_id, sha256, status in expected:
        item = bound.get(input_id)
        if item is None:
            issues.append(f"Stale input: {input_id} is not bound")
        elif item.sha256 != sha256 or (status is not None and item.status != status):
            issues.append(
                f"Stale input: {input_id} is bound at {item.sha256[:12]} ({item.status}) but "
                f"CP-4 read {sha256[:12]}; rerun required"
            )
    return tuple(issues)


def _row_issues(path: str, row: BaseModel, upstream: Upstream) -> list[str]:
    """Evidence rules of one row: what each kind of row quotes, from which sources."""
    issues: list[str] = []
    legal = set(upstream.legal_sources)
    for source_id in dict.fromkeys(quote.source_id for quote in _quotes(row)):
        if source_id in upstream.authority and source_id not in legal:
            issues.append(
                f"{path}: {source_id} is not an executed or filed source (CP-0 authority "
                f"{upstream.authority[source_id]}, or the source is not ready)"
            )
    quotes = _quotes(row)
    if isinstance(row, LegalDocument):
        if row.source_id not in legal:
            issues.append(f"{path}: {row.source_id} is not an executed or filed source")
        if not quotes:
            issues.append(f"{path}: a document row quotes its own source")
        if any(quote.source_id != row.source_id for quote in quotes):
            issues.append(f"{path}: a document row quotes its own source only")
    if isinstance(row, Basket) and not quotes:
        issues.append(f"{path}: a capacity row quotes its basket")
    if isinstance(row, RedFlag) and not quotes:
        issues.append(f"{path}: a red flag quotes its mechanic")
    if isinstance(row, ProtectionScore):
        if row.rating == "Insufficient Information" and not row.limitation:
            issues.append(f"{path}: an Insufficient Information rating states its limitation")
        if row.rating != "Insufficient Information" and not quotes:
            issues.append(f"{path}: a rating above Insufficient Information cites its basis")
    return issues


def _threshold_issues(path: str, row: Covenant) -> list[str]:
    """Ruling 2: the stated value is the number Python reads from the quoted threshold."""
    unit = row.threshold_unit
    if unit == NOT_STATED:
        if row.threshold_text != NOT_STATED or row.threshold_value is not None:
            return [f'{path}: an unstated threshold is "not stated" with a null threshold_value']
        return (
            [] if row.comparison == "none" else [f"{path}: an unstated threshold has no comparison"]
        )
    issues: list[str] = []
    if not any(quoted(row.threshold_text, quote.quote) for quote in row.citations):
        issues.append(f"{path}: threshold_text is not part of the row's quotes")
    if unit == "other":
        if row.threshold_value is not None:
            issues.append(f"{path}: an other threshold is not parsed, so threshold_value is null")
        return issues
    if row.comparison == "none":
        issues.append(f"{path}: a {unit} threshold states its comparison")
    if row.threshold_value is None:
        return [*issues, f"{path}: a {unit} threshold states the threshold_value"]
    try:
        stated = Decimal(row.threshold_value)
    except InvalidOperation:
        return [*issues, f"{path}: threshold_value {row.threshold_value} is not a number"]
    parsed, reason = parse_threshold(row.threshold_text, unit)
    if parsed is None:
        issues.append(f"{path}: threshold_text cannot be read: {reason}")
    elif not stated.is_finite() or stated != parsed:
        issues.append(f"{path}: threshold_value {row.threshold_value} differs from {parsed}")
    return issues


def _covenant_issues(
    path: str, row: Covenant, upstream: Upstream, documents: frozenset[str]
) -> list[str]:
    issues = _threshold_issues(path, row)
    if row.document_id not in documents:
        issues.append(f"{path}: no documents row for {row.document_id}, its governing document")
    if not any(quote.source_id == row.document_id for quote in row.citations):
        issues.append(f"{path}: a covenant quotes its governing document")
    seen: list[str] = []
    for facility_id in row.facility_ids:
        if facility_id not in upstream.facilities:
            issues.append(
                f"{path}: unknown facility_id {facility_id} (not in the bound CP-1 T4.18)"
            )
        elif facility_id in seen:
            issues.append(f"{path}: facility_id {facility_id} is listed more than once")
        seen.append(facility_id)
    offered = {fact.fact_id: fact for fact in upstream.facts}
    if row.metric_ref is None:
        if row.metric_basis != "Not determinable":
            issues.append(f"{path}: metric_basis is Not determinable when no metric_ref is named")
        return issues
    fact = offered.get(row.metric_ref)
    if fact is None:
        offer = "no CP-1 figure is offered" if upstream.blocked else "see cp1_facts"
        issues.append(f"{path}: metric_ref {row.metric_ref} is not a CP-1 figure offered ({offer})")
    elif row.threshold_unit in _UNIT_OF and fact.unit not in _UNIT_OF[row.threshold_unit]:
        issues.append(
            f"{path}: metric_ref {row.metric_ref} is a {fact.unit} figure; the threshold is a "
            f"{row.threshold_unit}"
        )
    return issues


def _shape_issues(submission: CovenantInterpretationSubmission) -> list[str]:
    seen = [row.source_id for row in submission.documents]
    return [
        f"documents: {source_id} is registered more than once"
        for source_id in sorted({s for s in seen if seen.count(s) > 1})
    ]


def prohibited_issues_cp4(path: str, text: str) -> tuple[str, ...]:
    """A text that states a prohibited conclusion (instrument recommendation, recovery outcome,
    peer ranking), worded as `business_context.prohibited_issues`; CP-4 rows quote no
    labelled management language, so no quoting exemption applies."""
    return tuple(
        f'{path}: prohibited conclusion ({kind}): "{phrase}"'
        for kind, phrase, pattern in _PROHIBITED_HERE
        if pattern.search(text)
    )


def python_owned_issues(path: str, text: str) -> tuple[str, ...]:
    """A text that states compliance or headroom, which only Python's cells state."""
    return tuple(
        f'{path}: prohibited conclusion (compliance or headroom): "{match[0]}"'
        for pattern in _PYTHON_OWNED
        if (match := pattern.search(text))
    )


def validate_covenant_interpretation(
    pack: PreparedPack,
    submission: CovenantInterpretationSubmission,
    upstream: Upstream,
    inputs: Sequence[Input],
) -> tuple[str, ...]:
    """Every issue of `submission` over `pack` and the bound `inputs`, in a stable order; empty
    when it composes. `upstream` is what CP-4 read from those inputs (`cp4_upstream`)."""
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        submission = CovenantInterpretationSubmission.model_validate_json(
            submission.model_dump_json()
        )
    except ValidationError as error:
        return shape_issues(error)
    bound = prose.bind(upstream.facts)
    names = (pack.run.issuer_name,)
    binding = _bind(pack, submission)
    documents = frozenset(row.source_id for row in submission.documents)
    issues: list[str] = [*stale_issues(pack, upstream, inputs), *binding.issues]
    texts: list[tuple[str, tuple[str, ...]]] = []
    for path, row in _rows(submission):
        issues.extend(f"{path}: {i}" for i in citation_issues(binding.of(row), pack.sources))
        issues.extend(_row_issues(path, row, upstream))
        if isinstance(row, Covenant):
            issues.extend(_covenant_issues(path, row, upstream, documents))
        scope = tuple(dict.fromkeys(quote.source_id for quote in _quotes(row)))
        for name, text in _texts(row):
            where = f"{path}.{name}"
            if not text.strip():
                issues.append(f"{where}: empty text")
                continue
            issues.extend(f"{where}: {issue}" for issue in prose.issues(text, bound, names=names))
            issues.extend(prohibited_issues_cp4(where, text))
            issues.extend(python_owned_issues(where, text))
            texts.append((text, scope))
    issues.extend(_shape_issues(submission))
    issues.extend(absence_issues(pack, texts))
    return tuple(dict.fromkeys(issues))


# --- the tables (minimal, from the rows; ids from r14, placement Deploy VII's) ----------------

REGISTERS: Mapping[str, Register] = {
    item.table_id: item
    for item in (
        _register(
            "T4.2",
            "Document register",
            "Source ID|Document family|Authority|Governing entity|Date / amendment|"
            "Source trace|Limitation",
        ),
        _register(
            "T4.3",
            "Covenant register",
            "Covenant|Kind|Clause|Governing document|Period scope|Facilities|Source trace|"
            "Limitation",
        ),
        _register(
            "T4.9",
            "Covenant tests and headroom",
            "Covenant|Test formula|Threshold|Comparison|CP-1 metric|Current|Headroom|"
            "Headroom share|Test on CP-1 metric",
        ),
        _register(
            "T4.10",
            "Capacity and baskets",
            "Basket|Permits|Conditions|Capacity amount|Source trace|Limitation",
        ),
        _register("T4.11", "Red flags", "Flag|Severity|Mechanic|Implication|Source trace"),
        _register("T4.12", "CP-4 gaps ledger", "Gap ID|Gap|Why it matters|Severity|Action"),
        _register(
            "T4.13", "Lender protection score", "Rating|Rationale|Basis|Source trace|Limitation"
        ),
        _register(
            "T4C.2",
            "Maintenance covenants",
            "Covenant|Test formula|Threshold|Period scope|Facilities",
        ),
        _register(
            "T4C.3",
            "Incurrence covenants",
            "Covenant|Test formula|Threshold|Period scope|Facilities",
        ),
        _register("T4C.4", "Negative covenants", "Covenant|Clause|Facilities|Source trace"),
        _register("T4C.5", "Other covenants", "Covenant|Clause|Facilities|Source trace"),
        _register("T4C.6", "Covenant definitions", "Covenant|Definition|Source trace"),
        _register(
            "T4C.7",
            "Threshold check",
            "Covenant|Threshold text|Unit|Stated value|Parsed value|Comparison",
        ),
        _register(
            "T4C.8",
            "CP-1 metric binding",
            "Covenant|CP-1 metric|Metric period|Definition basis|Unit",
        ),
        _register("T4C.9", "Headroom calculability", "Covenant|Calculable|Reason"),
        _register("T4C.11", "Covenant-to-facility map", "Covenant|Facility ID|Facility"),
        _register("T4C.12", "Facility coverage", "Facility ID|Facility|Covenants|Status"),
        _register(
            "T4D.1",
            "Pack legal source eligibility",
            "Source ID|CP-0 authority|Eligible for CP-4 citation|Cited by CP-4|Limitation",
        ),
        _register("T4D.2", "Governing entities", "Source ID|Governing entity|Source trace"),
        _register("T4D.3", "Dates and amendments", "Source ID|Date / amendment|Source trace"),
        _register("T4D.4", "Document quotations", "Quotation|Source|Locator|Quote"),
        _register("T4D.5", "Document limitations", "Source ID|Limitation"),
        _register("T4D.6", "Capacity conditions", "Basket|Conditions|Source trace"),
        _register("T4D.7", "Red flag implications", "Flag|Implication|Severity"),
        _register("T4D.8", "Covenants by governing document", "Source ID|Covenants"),
        _register("T4F.1", "CP-4 input status", "Input|Status|SHA-256|Note"),
        _register("T4F.2", "CP-1 figures referenced", "Value"),
        _register(
            "T4F.3",
            "Headroom calculation trace",
            "Covenant|Formula|Threshold operand|Metric operand|Result",
        ),
        _register("T4F.4", "Protection score basis", "Rating|Basis|Source trace"),
        _register("T4F.5", "Inherited CP-1 gaps", "Gap ID|Gap"),
        _register("T4F.6", "CP-4 source trace", "Row|Source|Locator|Quote"),
    )
}
REQUIRED_TABLES = tuple(REGISTERS)
# Registers a legal interpretation always fills: empty, each is a `missing` gap and a limitation.
NONEMPTY = frozenset({"T4.2", "T4.3"})
# The first column is the row header except here: the single rating row shows its rating as a
# cell, and the referenced figures are labelled by their CP-1 row.
UNKEYED = frozenset({"T4.13", "T4F.2"})
_COMPARISON_TEXT: Mapping[str, str] = {
    "<=": "Not more than",
    "<": "Less than",
    ">=": "Not less than",
    ">": "More than",
    "none": "Not stated",
}
WITHIN = "Within threshold on the CP-1 metric"
OUTSIDE = "Outside threshold on the CP-1 metric"
CP1_BLOCKED = (
    "CP-1 is blocked: covenant formulas are extracted, headroom and capacity are not calculable "
    "(decision 0007)"
)
CAPACITY_NOT_CALCULATED = (
    "Basket capacity amounts are not calculated: CP-4 quotes and interprets baskets in M8"
)
_RATIO_KINDS = frozenset({"maintenance", "incurrence"})

CellLike = Cell | Fact


class _Composer:
    """Writes the tables: cells from validated rows (text, or a numeric `Fact` Python computed or
    copied), table facts and own limitations."""

    def __init__(self, pack: PreparedPack, binding: _Bound, bound: Mapping[str, Fact]) -> None:
        self.pack = pack
        self.binding = binding
        self.bound = bound
        self.tables: list[ReportTable] = []
        self.facts: list[Fact] = []
        self.limitations: list[str] = []
        self.referenced: dict[str, Fact] = {}

    def text(self, value: str) -> str:
        """Validated run text with each figure reference spelled by Python (`spelled`)."""
        out: list[str] = []
        for run in prose.tokenize(value):
            if run.kind == "text":
                out.append(run.text)
                continue
            fact = self.bound[run.text]
            self.referenced.setdefault(fact.fact_id, fact)
            out.append(spelled(fact))
        return "".join(out)

    def said(self, value: str, row: BaseModel | None = None) -> Cell:
        return Cell(self.text(value), self.binding.of(row) if row is not None else (), judged=True)

    def limit(self, row: BaseModel) -> Cell:
        limitation = getattr(row, "limitation", None)
        return Cell(self.text(limitation) if limitation else NONE_STATED)

    def trace(self, row: BaseModel) -> Cell:
        cited = self.binding.of(row)
        return Cell(_trace(cited) or NO_EVIDENCE, cited)

    def _fact(
        self, cell: CellLike, register: Register, row_id: str, field: str, label: str
    ) -> Fact:
        fact_id = f"{register.table_id}.{row_id}.{field}"
        if isinstance(cell, Fact):
            where = {"table_id": register.table_id, "row_id": row_id, "field": field}
            return cell.model_copy(update={"fact_id": fact_id, **where})
        return Fact(
            fact_id=fact_id,
            table_id=register.table_id,
            row_id=row_id,
            field=field,
            label=label,
            text=cell.text,
            status="known" if cell.text is not None else cell.status,
            citations=cell.citations,
            value_class="analyst_judgment" if cell.judged else None,
            limitation=cell.reason if cell.text is None else None,
        )

    def table(
        self,
        register: Register,
        rows: Sequence[tuple[str, Sequence[CellLike]]],
        empty: str | None = None,
    ) -> None:
        keyed = register.table_id not in UNKEYED
        columns = register.columns[1:] if keyed else register.columns
        if not rows:
            title = register.title.lower()
            if register.table_id in NONEMPTY:
                cell = Cell(
                    None, reason=f"No {title} rows in the CP-4 submission", status="missing"
                )
                self.limitations.append(str(cell.reason))
            else:
                reason = empty or f"None in the CP-4 submission ({title})"
                cell = Cell(None, reason=reason, status="not_applicable")
            header = (Cell("None"),) if keyed else ()
            rows = (("none", (*header, *(cell for _ in columns))),)
        table_rows: list[TableRow] = []
        for position, (row_id, all_cells) in enumerate(rows, 1):
            body = all_cells[1:] if keyed else all_cells
            ids: list[str] = []
            for (field, label), item in zip(columns, body, strict=True):
                fact = self._fact(item, register, row_id, field, label)
                self.facts.append(fact)
                ids.append(fact.fact_id)
            head = all_cells[0]
            label = (head.text if keyed and isinstance(head, Cell) else None) or (
                f"{register.title} {position}"
            )
            table_rows.append(TableRow(row_id=row_id, label=label, fact_ids=tuple(ids)))
        self.tables.append(
            ReportTable(
                table_id=register.table_id,
                title=register.title,
                columns=tuple(TableColumn(field=f, label=label) for f, label in columns),
                rows=tuple(table_rows),
                row_header=register.columns[0][1] if keyed else None,
            )
        )


def _numbered(cells: Iterable[Sequence[CellLike]]) -> list[tuple[str, Sequence[CellLike]]]:
    return [(f"r{index:02d}", row) for index, row in enumerate(cells, 1)]


def _gap(reason: str) -> Cell:
    return Cell(None, reason=reason, status="missing")


def _absent(reason: str) -> Cell:
    return Cell(None, reason=reason, status="not_applicable")


@dataclass(frozen=True)
class _Test:
    """One covenant's Python test: the parsed threshold, the CP-1 metric and the headroom, or
    why it is not calculable (`reason`) or not applicable (`inapplicable`)."""

    row: Covenant
    parsed: Decimal | None
    metric: Fact | None
    result: Headroom | None
    reason: str | None
    inapplicable: bool

    @property
    def operand(self) -> Decimal | None:
        """The threshold in the metric's unit: a percentage as a decimal fraction (CP-1 holds a
        percent figure as one, `display` spells it)."""
        if self.parsed is None:
            return None
        return self.parsed / 100 if self.row.threshold_unit == "percent" else self.parsed


def _test(row: Covenant, upstream: Upstream) -> _Test:
    offered = {fact.fact_id: fact for fact in upstream.facts}
    metric = offered.get(row.metric_ref) if row.metric_ref else None
    parsed = (
        parse_threshold(row.threshold_text, row.threshold_unit)[0]
        if row.threshold_unit in _UNIT_OF
        else None
    )
    if row.kind not in _RATIO_KINDS:
        why = f"A {row.kind} covenant has no ratio test"
        return _Test(row, parsed, metric, None, why, inapplicable=True)
    reason: str | None = None
    if upstream.blocked:
        reason = CP1_BLOCKED
    elif row.threshold_unit == NOT_STATED:
        reason = "The documents state no threshold"
    elif row.threshold_unit == "other":
        reason = "The threshold is not a ratio or percentage Python parses"
    elif metric is None:
        reason = "No CP-1 metric is matched to this test"
    elif row.metric_basis == "Different definition":
        reason = "The covenant definition differs from the CP-1 metric"
    elif row.metric_basis == "Not determinable":
        reason = "Whether the covenant definition is the CP-1 metric's is not determinable"
    test = _Test(row, parsed, metric, None, reason, inapplicable=False)
    if reason is not None:
        return test
    assert test.operand is not None and metric is not None and metric.amount is not None
    result = headroom(test.operand, row.comparison, metric.amount)
    return _Test(row, parsed, metric, result, None, inapplicable=False)


def _computed(
    test: _Test, cited: tuple[Citation, ...], label: str, amount: Decimal, unit: str, formula: str
) -> Fact:
    """A Python-computed figure in the metric's period, citing the threshold quote and the
    metric's own evidence."""
    metric = test.metric
    assert metric is not None
    return Fact(
        fact_id="pending",
        label=label,
        amount=amount,
        unit=unit,
        period=metric.period,
        basis=metric.basis,
        citations=tuple(dict.fromkeys((*cited, *metric.citations))),
        value_class="calculated",
        formula=formula,
    )


def _test_cells(test: _Test, out: _Composer) -> tuple[CellLike, CellLike, CellLike]:
    """Headroom, its share and the test result: computed, not calculable or not applicable."""
    if test.result is None:
        reason = f"{NOT_CALCULABLE}: {test.reason}"
        if test.inapplicable:
            return _absent(str(test.reason)), _absent(str(test.reason)), Cell("Not applicable")
        return _gap(reason), _gap(reason), Cell(NOT_CALCULABLE)
    metric = test.metric
    assert metric is not None and metric.unit is not None and test.operand is not None
    ref, operand = metric.fact_id, test.operand
    upper = test.row.comparison in ("<=", "<")
    formula = f"{operand} (threshold) - {ref}" if upper else f"{ref} - {operand} (threshold)"
    cited = out.binding.of(test.row)
    room = _computed(test, cited, "Headroom", test.result.amount, metric.unit, formula)
    share: CellLike = (
        _computed(
            test, cited, "Headroom share", test.result.share, "PERCENT", "headroom / |threshold|"
        )
        if test.result.share is not None
        else _gap(f"{NOT_CALCULABLE}: {test.result.share_reason}")
    )
    return room, share, Cell(WITHIN if test.result.within else OUTSIDE)


def _metric_cell(test: _Test, upstream: Upstream) -> CellLike:
    if test.metric is not None:
        return test.metric
    if upstream.blocked:
        return _gap(f"{NOT_CALCULABLE}: {CP1_BLOCKED}")
    return _absent("No CP-1 metric is named for this covenant")


def _facilities(row: Covenant, upstream: Upstream) -> Cell:
    names = [f"{i} ({upstream.facilities.get(i) or 'name not stated'})" for i in row.facility_ids]
    return Cell("; ".join(names) or "None named")


def _threshold_cell(row: Covenant, out: _Composer) -> Cell:
    """The quoted threshold, cited by the row's quotes (it is a part of one of them)."""
    if row.threshold_unit == NOT_STATED:
        return Cell("Not stated")
    return Cell(row.threshold_text, out.binding.of(row))


def _covenant_tables(
    submission: CovenantInterpretationSubmission, upstream: Upstream, out: _Composer
) -> None:
    covenants = submission.covenants
    tests = [_test(row, upstream) for row in covenants]
    out.table(
        REGISTERS["T4.3"],
        _numbered(
            (
                out.said(c.name, c),
                Cell(c.kind),
                out.said(c.clause, c),
                Cell(c.document_id),
                out.said(c.period_scope, c),
                _facilities(c, upstream),
                out.trace(c),
                out.limit(c),
            )
            for c in covenants
        ),
    )
    rows: list[tuple[str, Sequence[CellLike]]] = []
    for index, test in enumerate(tests, 1):
        c = test.row
        headroom_cell, share_cell, verdict = _test_cells(test, out)
        metric = test.metric
        rows.append(
            (
                f"r{index:02d}",
                (
                    out.said(c.name, c),
                    out.said(c.test_formula, c),
                    _threshold_cell(c, out),
                    Cell(_COMPARISON_TEXT[c.comparison]),
                    Cell(
                        upstream.rows[(metric.table_id, metric.row_id)] if metric else "None named"
                    ),
                    _metric_cell(test, upstream),
                    headroom_cell,
                    share_cell,
                    verdict,
                ),
            )
        )
        if test.reason is not None and not test.inapplicable:
            out.limitations.append(
                CP1_BLOCKED
                if test.reason == CP1_BLOCKED
                else f"Headroom not calculable for {out.text(c.name)}: {test.reason}"
            )
    out.table(REGISTERS["T4.9"], rows)
    for table_id, kind in (("T4C.2", "maintenance"), ("T4C.3", "incurrence")):
        out.table(
            REGISTERS[table_id],
            [
                (
                    f"r{index:02d}",
                    (
                        out.said(c.name, c),
                        out.said(c.test_formula, c),
                        _threshold_cell(c, out),
                        out.said(c.period_scope, c),
                        _facilities(c, upstream),
                    ),
                )
                for index, c in enumerate(covenants, 1)
                if c.kind == kind
            ],
        )
    for table_id, kind in (("T4C.4", "negative"), ("T4C.5", "other")):
        out.table(
            REGISTERS[table_id],
            [
                (
                    f"r{index:02d}",
                    (
                        out.said(c.name, c),
                        out.said(c.clause, c),
                        _facilities(c, upstream),
                        out.trace(c),
                    ),
                )
                for index, c in enumerate(covenants, 1)
                if c.kind == kind
            ],
        )
    out.table(
        REGISTERS["T4C.6"],
        _numbered(
            (out.said(c.name, c), out.said(c.definition_text, c), out.trace(c)) for c in covenants
        ),
    )
    _check_tables(tests, upstream, out)


def _check_tables(tests: Sequence[_Test], upstream: Upstream, out: _Composer) -> None:
    """T4C.7 to T4C.12 and T4F.3: Python's provenance for every threshold, metric and headroom."""
    out.table(
        REGISTERS["T4C.7"],
        _numbered(
            (
                out.said(t.row.name, t.row),
                _threshold_cell(t.row, out),
                Cell(t.row.threshold_unit),
                Cell(t.row.threshold_value or "None stated"),
                Cell(str(t.parsed)) if t.parsed is not None else _absent("Nothing to parse"),
                Cell(_COMPARISON_TEXT[t.row.comparison]),
            )
            for t in tests
        ),
    )
    out.table(
        REGISTERS["T4C.8"],
        _numbered(
            (
                out.said(t.row.name, t.row),
                Cell(t.metric.fact_id if t.metric else "None named"),
                Cell(t.metric.period or NONE_STATED) if t.metric else _absent("No metric"),
                Cell(t.row.metric_basis),
                Cell(t.metric.unit or NONE_STATED) if t.metric else _absent("No metric"),
            )
            for t in tests
        ),
    )
    out.table(
        REGISTERS["T4C.9"],
        _numbered(
            (
                out.said(t.row.name, t.row),
                Cell("Yes" if t.result else "Not applicable" if t.inapplicable else "No"),
                Cell(t.reason or "Threshold, metric and definition basis are all present"),
            )
            for t in tests
        ),
    )
    pairs = [(t.row, i) for t in tests for i in t.row.facility_ids]
    out.table(
        REGISTERS["T4C.11"],
        _numbered(
            (
                out.said(c.name, c),
                Cell(i),
                Cell(upstream.facilities.get(i) or NONE_STATED),
            )
            for c, i in pairs
        ),
    )
    naming = {i: [out.text(c.name) for c, j in pairs if j == i] for i in upstream.facilities}
    out.table(
        REGISTERS["T4C.12"],
        _numbered(
            (
                Cell(i),
                Cell(name or NONE_STATED),
                Cell("; ".join(naming[i]) or "None"),
                Cell("Named by a covenant" if naming[i] else "No covenant names this facility"),
            )
            for i, name in upstream.facilities.items()
        ),
        empty=f"{CP1_BLOCKED}: no facility register is bound"
        if upstream.blocked
        else "The bound CP-1 T4.18 lists no facility",
    )
    out.table(
        REGISTERS["T4F.3"],
        _numbered(
            (
                out.said(t.row.name, t.row),
                Cell(
                    "threshold minus metric"
                    if t.row.comparison in ("<=", "<")
                    else "metric minus threshold"
                    if t.row.comparison in (">=", ">")
                    else "No comparison"
                ),
                Cell(str(t.operand)) if t.operand is not None else _absent("No parsed threshold"),
                Cell(t.metric.fact_id) if t.metric else _absent("No CP-1 metric"),
                Cell(
                    str(t.result.amount)
                    if t.result
                    else f"{NOT_CALCULABLE}: {t.reason}"
                    if not t.inapplicable
                    else "Not applicable"
                ),
            )
            for t in tests
        ),
    )


def _document_tables(
    submission: CovenantInterpretationSubmission, upstream: Upstream, out: _Composer
) -> None:
    documents = submission.documents
    out.table(
        REGISTERS["T4.2"],
        _numbered(
            (
                Cell(d.source_id),
                out.said(d.document_family, d),
                Cell(upstream.authority.get(d.source_id, "unknown")),
                out.said(d.governing_entity, d),
                out.said(d.date_or_amendment, d),
                out.trace(d),
                out.limit(d),
            )
            for d in documents
        ),
    )
    cited = {c.source_id for _, row in _rows(submission) for c in out.binding.of(row)}
    out.table(
        REGISTERS["T4D.1"],
        _numbered(
            (
                Cell(s.source_id),
                Cell(upstream.authority.get(s.source_id, "not assessed by CP-0")),
                Cell("Yes" if s.source_id in upstream.legal_sources else "No"),
                Cell("Yes" if s.source_id in cited else "No"),
                Cell(s.limitation or NONE_STATED),
            )
            for s in out.pack.sources
        ),
    )
    out.table(
        REGISTERS["T4D.2"],
        _numbered(
            (Cell(d.source_id), out.said(d.governing_entity, d), out.trace(d)) for d in documents
        ),
    )
    out.table(
        REGISTERS["T4D.3"],
        _numbered(
            (Cell(d.source_id), out.said(d.date_or_amendment, d), out.trace(d)) for d in documents
        ),
    )
    quotations = [(c, d) for d in documents for c in out.binding.of(d)]
    out.table(
        REGISTERS["T4D.4"],
        _numbered(
            (Cell(f"Quotation {i}"), Cell(c.source_id), Cell(c.locator), Cell(c.quote, (c,)))
            for i, (c, _) in enumerate(quotations, 1)
        ),
    )
    out.table(REGISTERS["T4D.5"], _numbered((Cell(d.source_id), out.limit(d)) for d in documents))
    out.table(
        REGISTERS["T4D.8"],
        _numbered(
            (
                Cell(d.source_id),
                Cell(
                    "; ".join(
                        out.text(c.name)
                        for c in submission.covenants
                        if c.document_id == d.source_id
                    )
                    or "None"
                ),
            )
            for d in documents
        ),
    )


def _judgment_tables(submission: CovenantInterpretationSubmission, out: _Composer) -> None:
    capacity, flags, score = submission.capacity, submission.red_flags, submission.protection_score
    amount = _gap(f"{CAPACITY_NOT_CALCULATED}; unknown capacity is not zero")
    out.table(
        REGISTERS["T4.10"],
        _numbered(
            (
                out.said(b.basket, b),
                out.said(b.permits, b),
                out.said(b.conditions, b),
                amount,
                out.trace(b),
                out.limit(b),
            )
            for b in capacity
        ),
    )
    if capacity:
        out.limitations.append(CAPACITY_NOT_CALCULATED)
    out.table(
        REGISTERS["T4D.6"],
        _numbered(
            (out.said(b.basket, b), out.said(b.conditions, b), out.trace(b)) for b in capacity
        ),
    )
    out.table(
        REGISTERS["T4.11"],
        _numbered(
            (
                out.said(f.flag, f),
                Cell(f.severity),
                out.said(f.mechanic, f),
                out.said(f.implication, f),
                out.trace(f),
            )
            for f in flags
        ),
    )
    out.table(
        REGISTERS["T4D.7"],
        _numbered(
            (out.said(f.flag, f), out.said(f.implication, f), Cell(f.severity)) for f in flags
        ),
    )
    out.table(
        REGISTERS["T4.13"],
        [
            (
                "rating",
                (
                    Cell(score.rating),
                    out.said(score.rationale, score),
                    out.said(score.basis, score),
                    out.trace(score),
                    out.limit(score),
                ),
            )
        ],
    )
    out.table(
        REGISTERS["T4F.4"],
        [("rating", (Cell(score.rating), out.said(score.basis, score), out.trace(score)))],
    )
    out.table(
        REGISTERS["T4.12"],
        _numbered(
            (
                Cell(f"CP-4-GAP-{index:03d}"),
                out.said(g.gap),
                out.said(g.why_it_matters),
                Cell(g.severity),
                out.said(g.action),
            )
            for index, g in enumerate(submission.gaps, 1)
        ),
    )


def _input_tables(
    submission: CovenantInterpretationSubmission,
    upstream: Upstream,
    inputs: Sequence[Input],
    out: _Composer,
) -> None:
    notes = {
        PACK_INPUT: "The prepared pack",
        CP0: "Source authority classes (T3)",
        CP1: CP1_BLOCKED if upstream.blocked else "Facility register and figure catalogue",
    }
    out.table(
        REGISTERS["T4F.1"],
        [
            (
                item.input_id.lower(),
                (
                    Cell(item.input_id),
                    Cell(item.status),
                    Cell(item.sha256),
                    Cell(notes[item.input_id]),
                ),
            )
            for item in inputs
            if item.input_id in notes
        ],
    )
    out.table(
        REGISTERS["T4F.5"],
        _numbered(
            (Cell(f"CP-1-GAP-{i:03d}"), Cell(text)) for i, text in enumerate(upstream.cp1_gaps, 1)
        ),
        empty="CP-1 carries no limitation",
    )
    traced = [(path, c) for path, row in _rows(submission) for c in out.binding.of(row)]
    out.table(
        REGISTERS["T4F.6"],
        _numbered(
            (Cell(path), Cell(c.source_id), Cell(c.locator), Cell(c.quote, (c,)))
            for path, c in traced
        ),
    )


def _referenced_table(tests: Sequence[_Test], upstream: Upstream, out: _Composer) -> list[Fact]:
    """T4F.2: each CP-1 figure the text or a test names, copied value for value (its own id, so
    a `{ref|unit}` in a claim resolves)."""
    for test in tests:
        if test.metric is not None:
            out.referenced.setdefault(test.metric.fact_id, test.metric)
    register = REGISTERS["T4F.2"]
    copies = [
        fact.model_copy(
            update={"table_id": register.table_id, "row_id": f"ref{index:02d}", "field": "value"}
        )
        for index, fact in enumerate(out.referenced.values(), 1)
    ]
    rows = tuple(
        TableRow(
            row_id=fact.row_id,
            label=upstream.rows.get((original.table_id, original.row_id), original.row_id)
            + (f" · {fact.period}" if fact.period else ""),
            fact_ids=(fact.fact_id,),
        )
        for fact, original in zip(copies, out.referenced.values(), strict=True)
    )
    if not rows:
        empty = Cell(None, reason="No CP-1 figure is referenced", status="not_applicable")
        out.table(register, [("none", (empty,))])
        return []
    out.tables.append(
        ReportTable(
            table_id=register.table_id,
            title=register.title,
            columns=(TableColumn(field="value", label="Value"),),
            rows=rows,
            row_header="CP-1 figure",
        )
    )
    return copies


def covenant_interpretation(
    pack: PreparedPack,
    submission: CovenantInterpretationSubmission,
    upstream: Upstream,
    inputs: Sequence[Input],
) -> CovenantInterpretationReport:
    """The composed CP-4 tables of a valid submission; raises ValueError on any issue."""
    issues = validate_covenant_interpretation(pack, submission, upstream, inputs)
    if issues:
        raise ValueError("; ".join(issues))
    pack = PreparedPack.model_validate_json(pack.model_dump_json())
    submission = CovenantInterpretationSubmission.model_validate_json(submission.model_dump_json())
    out = _Composer(pack, _bind(pack, submission), prose.bind(upstream.facts))
    out.limitations.extend(f"Gap ({g.severity}): {out.text(g.gap)}" for g in submission.gaps)
    if upstream.blocked:
        out.limitations.append(CP1_BLOCKED)
    _document_tables(submission, upstream, out)
    _covenant_tables(submission, upstream, out)
    _judgment_tables(submission, out)
    _input_tables(submission, upstream, inputs, out)
    copies = _referenced_table([_test(c, upstream) for c in submission.covenants], upstream, out)
    order = {table_id: index for index, table_id in enumerate(REQUIRED_TABLES)}
    tables = sorted(out.tables, key=lambda table: order[table.table_id])
    claims = (
        *(
            Claim(
                claim_id=f"red_flags.r{index:02d}",
                text=f"{f.flag}. Mechanic: {f.mechanic} Implication: {f.implication}",
                citations=out.binding.of(f),
            )
            for index, f in enumerate(submission.red_flags, 1)
        ),
        Claim(
            claim_id="protection_score",
            text=f"Lender protection {submission.protection_score.rating}: "
            f"{submission.protection_score.rationale}",
            citations=out.binding.of(submission.protection_score),
            limitation=submission.protection_score.limitation,
        ),
    )
    return CovenantInterpretationReport(
        run=pack.run,
        pack_sha256=pack.content_hash(),
        submission_sha256=submission.content_hash(),
        tables=tuple(tables),
        facts=(*out.facts, *copies),
        claims=claims,
        limitations=tuple(dict.fromkeys(out.limitations)),
    )


# --- the module and the journal ---------------------------------------------------------------


def cp4_module(
    report: CovenantInterpretationReport, inputs: Sequence[Input], attempt: int
) -> Module:
    """The CP-4 candidate: the report's tables and claims bound to `inputs`."""
    run = report.run
    return Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id=MODULE_ID,
        inputs=(*inputs, Input(input_id=SUBMISSION_INPUT, sha256=report.submission_sha256)),
        facts=report.facts,
        tables=report.tables,
        claims=report.claims,
        limitations=report.limitations,
        attempt=attempt,
    )


def _validate_step(store: Execution, pack: PreparedPack, attempt: Attempt) -> StepValidation:
    try:
        submission = CovenantInterpretationSubmission.model_validate_json(
            store.payload(attempt.steps[0].payload_sha256)
        )
    except ValidationError as error:
        return StepValidation(issues=shape_issues(error))
    upstream = upstream_of(store, attempt)
    issues = validate_covenant_interpretation(pack, submission, upstream, attempt.inputs)
    if issues:
        return StepValidation(issues=issues)
    report = covenant_interpretation(pack, submission, upstream, attempt.inputs)
    return StepValidation(output=report.model_dump_json())


def submit_cp4_step(store: Execution, ticket_id: str, step_id: str, payload: str) -> Attempt:
    """Retain the one `legal_covenants` response, validate it, then settle CP-4 with the Python
    candidate (as `submit_cp1a_step`): an invalid step finishes the attempt rejected (or blocked
    on the repair); a crash after the step resumes from the retained valid step."""
    if step_id != STEP_ID:
        raise ValueError(f"CP-4 has one step, {STEP_ID}")
    attempt = next((a for a in store.read().attempts if a.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != MODULE_ID or attempt.status != "pending":
        raise ValueError("Ticket is absent, finished or belongs to another module")
    if attempt.steps and attempt.steps[0].payload_sha256 != text_sha256(payload):
        raise ValueError("Ticket already retains a different response; resume or interrupt")
    if not attempt.steps or attempt.steps[0].status == "pending":
        attempt = store.submit_step(
            ticket_id,
            MODULE_ID,
            CP4_STEPS,
            STEP_ID,
            payload,
            lambda pack, current: _validate_step(store, pack, current),
        )
    if attempt.status == "finished":
        return attempt
    outcome = _validate_step(store, store.pack(), attempt)
    if outcome.issues or not outcome.retained_as(attempt.steps[0]):
        raise ValueError("Retained CP-4 output differs from trusted validation")
    report = CovenantInterpretationReport.model_validate_json(outcome.output or "")
    candidate = cp4_module(report, attempt.inputs, attempt.number)
    return store.finish(
        ticket_id,
        candidate.model_dump_json(),
        lambda supplied: () if supplied == candidate else ("CP-4 candidate differs",),
        qualification=PROMOTED,
    )


def context_block(pack: PreparedPack, upstream: Upstream) -> dict[str, object]:
    """What the `legal_covenants` CONTEXT block adds to the pack facts: the citable (executed or
    filed) sources, the CP-1 status and the gaps it carries, the T4.18 facility list and the CP-1
    figures a reference or a test may name, or the statement that none is offered."""
    names = {source.source_id: source for source in pack.sources}
    return {
        "legal_sources": [
            {
                "source_id": source_id,
                "name": names[source_id].name,
                "authority": upstream.authority[source_id],
                "extraction_coverage": extraction_coverage(names[source_id]),
            }
            for source_id in upstream.legal_sources
        ],
        "other_sources": [
            {"source_id": s.source_id, "authority": upstream.authority.get(s.source_id, "unknown")}
            for s in pack.sources
            if s.source_id not in upstream.legal_sources
        ],
        "cp1_status": upstream.cp1_status,
        "inherited_gaps": list(upstream.cp1_gaps),
        "facilities": [
            {"facility_id": facility_id, "facility_name": name}
            for facility_id, name in upstream.facilities.items()
        ],
        "cp1_facts": [
            {
                "ref": fact.fact_id,
                "row": upstream.rows[(fact.table_id, fact.row_id)],
                "label": fact.label,
                "period": fact.period,
                "unit": figure_unit(fact) or fact.unit,
                "shown": spelled(fact),
                "basis": fact.basis,
            }
            for fact in upstream.facts
        ],
        "cp1_facts_note": (
            "Reference a figure only as {ref|unit} with a ref and unit listed in cp1_facts; a "
            "test's metric_ref names one of these refs."
            if upstream.facts
            else "No CP-1 figure is offered: write no figure, name no metric_ref and no facility."
        ),
        "headroom_note": (
            "Python computes every headroom from the quoted threshold and the CP-1 metric; "
            "where an operand is missing it writes not calculable, never zero. State no "
            "compliance and no headroom in any text."
        ),
    }
