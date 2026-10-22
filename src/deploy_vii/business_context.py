"""CP-1A business and transaction context (task 7.2): one live step, `business_context`.

Decision 0008 MC-1, as for `source_readiness`: the model returns a `BusinessContextSubmission`,
judgments and verbatim quotes only (no hash, no id Python can assign, no amount, no score).
`validate_business_context` holds it to the CP-0 citation rules, the run-text rule of task 6.2
(figures only as `{ref|unit}` references to accepted CP-1 facts supplied in CONTEXT), the closed
enums, the r14 semantic rules `cp1a.*`, the prohibited conclusions and the CONTEXT consumer list.
`business_context` then composes every r14 register (`REGISTERS`, the 22 required ids plus the
conditional `cp1a.cp_model_snapshot_fields`) as `ReportTable`s over text facts, in Python:

- Model text reaches a cell only after validation, with each figure reference spelled by
  Python (`report_view.fact_spelling` and `figure_unit`); the referenced CP-1 facts are carried
  verbatim (values, units, citations) in the `cp1_references` table so claims resolve.
- Identifiers, source names, as-of dates, sequential gap and flag ids, handoff tags and the
  governance score (T2D.8, `governance_sponsor_score`) and risk-level drivers (T2D.9) are
  Python's. The score is a documented count-and-severity rule over the categorised governance
  rows; the model sets no weight and no score.
- A register the submission leaves empty is one explicit row of unsettled cells with a reason,
  never an invented value: `missing` (a gap and a module limitation) or, for the conflict log
  and the gap ledgers, `not_applicable` ("none logged").

The journal path (`submit_cp1a_step`) validates the one step and settles CP-1A with the Python
candidate in the same call, as `submit_cp0_review` does for CP-0, recording the four statuses.
"""

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, get_args

from pydantic import BaseModel, Field, ValidationError

from deploy_vii import prose
from deploy_vii.contracts import (
    Citation,
    Claim,
    Contract,
    Fact,
    Hash,
    Input,
    Module,
    ReportTable,
    Run,
    Source,
    TableColumn,
    TableRow,
    Text,
)
from deploy_vii.execution import Attempt, Execution, Qualification, StepValidation, text_sha256
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import (
    Authority,
    Readiness,
    absence_issues,
    citation_issues,
    shape_issues,
)
from deploy_vii.registry import dependencies, modules
from deploy_vii.report_view import fact_spelling, figure_unit

MODULE_ID = "CP-1A"
STEP_ID = "business_context"
CP1A_STEPS = (STEP_ID,)
SCHEMA_VERSION = "business-context/1"
# The four statuses a settled CP-1A head records (plan: "four statuses per module").
PROMOTED = Qualification(implementation="implemented")
# The producer whose accepted facts CP-1A's run text may reference (bound by the journal).
CP1 = "CP-1"
CP_MODEL = "CP-MODEL"

# --- the model-facing contract ---------------------------------------------------------------
# Plain `str` fields, as in `ReadinessSubmission`: the validator, not the sent schema, holds
# identifiers and text. Every enum is a `Literal`, so the sent schema carries it.

Category = Literal[
    "Documentary Fact", "Management Language", "Analyst Interpretation", "Insufficient Information"
]
EvidenceQuality = Literal["High", "Medium", "Low", "Insufficient"]
Confidence = Literal["High", "Medium", "Low", "Insufficient Information"]
Severity = Literal["Critical", "Material", "Minor"]
Aspect = Literal["business_description", "country", "sector"]
TransactionStatus = Literal[
    "Completed", "Pending", "Announced", "Proposed", "Terminated", "Insufficient Information"
]
DriverStatus = Literal["Disclosed", "Partially disclosed", "Not disclosed"]
EventStatus = Literal["Completed", "Announced", "Pending", "Subsequent event"]
GovernanceKind = Literal["governance_topic", "behaviour_flag"]
# r14 CP-2C taxonomy A-E as T2D.4 spells it; a governance topic (T2D.3) never uses
# Extraction-Oriented, which is a behaviour category only.
Direction = Literal[
    "Supportive",
    "Neutral",
    "Mixed",
    "Extraction-Oriented",
    "Creditor-Adverse",
    "Insufficient Information",
]
BehaviourType = Literal[
    "dividend recap",
    "distribution",
    "support",
    "LME",
    "amendment",
    "acquisition",
    "disposal",
    "reporting",
    "other",
]
Dimension = Literal[
    "Leverage tolerance",
    "Shareholder extraction risk",
    "Acquisition appetite",
    "Support behavior",
    "Disclosure transparency",
    "Creditor treatment / amendment behavior",
    "Legal-capacity linkage",
    "Reporting quality",
    "Related-party leakage risk",
]
DIMENSIONS: tuple[Dimension, ...] = get_args(Dimension)
CapitalDirection = Literal["Supportive", "Neutral", "Mixed", "Adverse", "Insufficient Information"]
Available = Literal["Yes", "No", "Partial", "Insufficient Information"]
Theme = Literal[
    "Revenue Durability",
    "Margin/CF Risk",
    "Concentration Risk",
    "Sponsor Alignment",
    "Key Uncertainties",
]


class Quote(Contract):
    source_id: str
    locator: str
    quote: str


class SourceUse(Contract):
    source_id: str
    source_class: Authority
    quality: EvidenceQuality
    period: str | None
    entity_covered: str
    data_supplied: str
    use: str
    citations: tuple[Quote, ...]
    limitation: str | None


class CompanyFact(Contract):
    aspect: Aspect
    text: str
    category: Category
    citations: tuple[Quote, ...]
    limitation: str | None


class BusinessLine(Contract):
    name: str
    revenue_mix: str
    period: str
    category: Category
    citations: tuple[Quote, ...]
    limitation: str | None


class Owner(Contract):
    owner: str
    control: str
    economic_interest: str
    credit_relevance: str
    evidence_quality: EvidenceQuality
    credit_mechanic: str
    credit_implication: str
    category: Category
    citations: tuple[Quote, ...]
    limitation: str | None


class OperatingDriver(Contract):
    driver: str
    measure: str | None  # null where the source leaves the metric undisclosed (r14 null rule)
    period: str
    status: DriverStatus
    credit_relevance: str
    category: Category
    citations: tuple[Quote, ...]
    limitation: str | None


class Transaction(Contract):
    transaction: str
    status: TransactionStatus
    credit_relevance: str
    category: Category
    citations: tuple[Quote, ...]
    limitation: str | None


class Event(Contract):
    date_window: str
    event: str
    credit_relevance: str
    status: EventStatus
    category: Category
    citations: tuple[Quote, ...]
    limitation: str | None


class GovernanceItem(Contract):
    """One row of T2D.3 (a governance topic) or T2D.4 (a behaviour flag)."""

    kind: GovernanceKind
    topic: str
    documented_fact: str
    direction: Direction
    behaviour_type: BehaviourType | None  # a behaviour flag's type; null for a topic
    amount_funding_source: str | None  # a behaviour flag's amount or funding source
    legal_capacity_link: str | None  # a behaviour flag's legal-capacity link
    dimension: Dimension | None  # the T2D.8 scoring dimension the row informs, if any
    risk_mechanic: str
    credit_implication: str
    evidence_quality: EvidenceQuality
    category: Category
    citations: tuple[Quote, ...]
    limitation: str | None


class CapitalAllocation(Contract):
    item: str
    fact: str
    direction: CapitalDirection
    risk_mechanic: str
    credit_implication: str
    evidence_quality: EvidenceQuality
    category: Category
    citations: tuple[Quote, ...]
    limitation: str | None


class Acquisition(Contract):
    acquisition_period: str
    fact: str
    funding_mix: str
    pro_forma_basis: str
    integration_evidence: str
    leverage_liquidity_effect: str
    risk_mechanic: str
    credit_implication: str
    category: Category
    citations: tuple[Quote, ...]
    limitation: str | None


class DisclosureItem(Contract):
    item: str
    available: Available
    detail: str
    credit_relevance: str
    severity: Severity
    follow_up: str
    citations: tuple[Quote, ...]


class CreditTranslation(Contract):
    theme: Theme
    evidence: str
    risk_mechanic: str
    credit_implication: str
    confidence: Confidence
    countervailing_conflict_ids: tuple[str, ...]
    citations: tuple[Quote, ...]
    limitation: str | None


class Conflict(Contract):
    conflict_id: str
    conflict: str
    materiality: Severity
    downstream_impact: str
    citations: tuple[Quote, ...]


class Gap(Contract):
    gap: str
    why_it_matters: str
    affected_analysis: str
    severity: Severity
    action: str


class Consumer(Contract):
    module_id: str
    status: Readiness
    handoff_item: str
    why_it_matters: str
    gap: str
    required_action: str


class BusinessContextSubmission(Contract):
    """What the model returns for `business_context`; every field is required (no defaults)."""

    sources: tuple[SourceUse, ...]
    # `minItems: 1` in the sent schema only, as `analysis` in `ReadinessSubmission`.
    company: tuple[CompanyFact, ...] = Field(json_schema_extra={"minItems": 1})
    business_lines: tuple[BusinessLine, ...]
    owners: tuple[Owner, ...]
    operating_drivers: tuple[OperatingDriver, ...]
    transactions: tuple[Transaction, ...]
    events: tuple[Event, ...]
    governance_and_sponsor: tuple[GovernanceItem, ...]
    capital_allocation: tuple[CapitalAllocation, ...]
    acquisitions: tuple[Acquisition, ...]
    disclosure_items: tuple[DisclosureItem, ...]
    credit_translations: tuple[CreditTranslation, ...]
    conflicts: tuple[Conflict, ...]
    gaps: tuple[Gap, ...]
    consumers: tuple[Consumer, ...] = Field(json_schema_extra={"minItems": 1})


# --- the composed report ---------------------------------------------------------------------


class BusinessContextReport(Contract):
    schema_version: Literal["business-context/1"] = "business-context/1"
    run: Run
    pack_sha256: Hash
    submission_sha256: Hash
    tables: tuple[ReportTable, ...]
    facts: tuple[Fact, ...]
    claims: tuple[Claim, ...]
    limitations: tuple[Text, ...]


# --- what the step may reference and who consumes it -----------------------------------------


def cp1a_consumers(pack: PreparedPack) -> tuple[str, ...]:
    """The modules `consumers` must judge, exactly: CP-MODEL always (r14: the readiness row always
    names CP-MODEL) and every module of the run's plan that consumes CP-1A, in registry order."""
    selected = set(dependencies(pack.run.requested_modules))
    return tuple(
        item.module_id
        for item in modules()
        if item.module_id == CP_MODEL
        or (item.module_id in selected and MODULE_ID in (*item.required, *item.optional))
    )


def referencable(facts: Iterable[Fact]) -> tuple[Fact, ...]:
    """The CP-1 facts a figure reference can name: known amounts with a citation or a
    calculation (the facts `prose` resolves as figures)."""
    return tuple(
        fact
        for fact in facts
        if fact.status == "known"
        and fact.amount is not None
        and (fact.citations or fact.calculation_id is not None)
    )


def cp1_context_facts(store: Execution, attempt: Attempt) -> tuple[Fact, ...]:
    """The referencable facts of the CP-1 head this attempt binds; none when it binds none
    (CP-1 not accepted or restricted when the attempt began)."""
    bound = next((item for item in attempt.inputs if item.input_id == CP1), None)
    if bound is None:
        return ()
    return referencable(store.result(bound.sha256).facts)


def spelled(fact: Fact) -> str:
    """How Python writes a referenced figure in a register cell: the cell spelling, plus the
    unit prose shows after an amount (``report_view.resolve`` applies the same rule)."""
    unit_class, _, shown = fact_spelling(fact, None)
    unit = figure_unit(fact) if unit_class == "amount" else None
    return f"{shown} {unit}" if unit else shown


# --- validation ------------------------------------------------------------------------------

# Free text that is an identifier, not prose: never run text.
_NOT_PROSE = frozenset({"source_id", "module_id", "conflict_id"})
_TEXT = (str, str | None)
# r14 critical_cell_values_casefold: a placeholder does not populate a credit-translation cell.
_PLACEHOLDERS = frozenset(
    {"", "[insufficient information]", "n/a", "tbd", "not calculable from provided materials"}
    | {"unavailable"}
)
# The r14 prohibited conclusions of CP-1A ("No peer ranking, instrument recommendation, or
# recovery conclusion"), as a closed phrase list matched on word boundaries, case-insensitively.
# A mention of recovery prospects as a credit mechanic is permitted; a recovery outcome is not.
PROHIBITED: Mapping[str, tuple[str, ...]] = {
    "peer ranking": (
        "peer ranking",
        "ranks above",
        "ranks below",
        "ranked first",
        "ranked last",
        "best-in-class",
        "best in class",
        "outperforms peers",
        "underperforms peers",
        "versus peers",
        "relative to peers",
        "compared with peers",
        "against its peers",
    ),
    "instrument recommendation": (
        "we recommend",
        "recommend buying",
        "recommend selling",
        "buy recommendation",
        "sell recommendation",
        "should buy",
        "should sell",
        "overweight",
        "underweight",
        "preferred instrument",
        "prefer the",
        "instrument recommendation",
    ),
    "recovery conclusion": (
        "recovery conclusion",
        "expected recovery",
        "recovery rate",
        "recovery estimate",
        "recovery value of",
        "full recovery",
        "recover par",
        "would recover",
        "will recover",
    ),
}
_PROHIBITED = tuple(
    (kind, phrase, re.compile(rf"(?<![A-Za-z]){re.escape(phrase)}(?![A-Za-z])", re.IGNORECASE))
    for kind, phrases in PROHIBITED.items()
    for phrase in phrases
)


def _rows(submission: BusinessContextSubmission) -> Iterator[tuple[str, BaseModel]]:
    for name in type(submission).model_fields:
        for index, row in enumerate(getattr(submission, name)):
            yield f"{name}[{index}]", row


def _texts(row: BaseModel) -> Iterator[tuple[str, str]]:
    """(field, value) of each prose field of one row; identifiers, enums and quotes excluded."""
    for name, info in type(row).model_fields.items():
        value = getattr(row, name)
        if name not in _NOT_PROSE and info.annotation in _TEXT and value is not None:
            yield name, value


def _quotes(row: BaseModel) -> tuple[Quote, ...]:
    citations = getattr(row, "citations", ())
    assert isinstance(citations, tuple)
    return citations


@dataclass(frozen=True)
class _Bound:
    """A submission's citations bound to the pack: each row's `Citation`s, and the issues of the
    ones that could not be bound."""

    citations: Mapping[int, tuple[Citation, ...]]
    issues: tuple[str, ...]

    def of(self, row: BaseModel) -> tuple[Citation, ...]:
        return self.citations.get(id(row), ())


def _bind(pack: PreparedPack, submission: BusinessContextSubmission) -> _Bound:
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


def _blank(value: str) -> bool:
    return not value.strip()


def _populated(value: str) -> bool:
    return value.strip().casefold() not in _PLACEHOLDERS


def prohibited_issues(path: str, text: str) -> tuple[str, ...]:
    """A text that states a prohibited CP-1A conclusion (`PROHIBITED`), one issue per phrase."""
    return tuple(
        f'{path}: prohibited conclusion ({kind}): "{phrase}"'
        for kind, phrase, pattern in _PROHIBITED
        if pattern.search(text)
    )


def _row_issues(path: str, row: BaseModel) -> list[str]:
    """Evidence and category rules of one row (the Five Categories and the citation rules)."""
    issues: list[str] = []
    category = getattr(row, "category", None)
    limitation = getattr(row, "limitation", None)
    if category is not None:
        if category == "Insufficient Information" and not limitation:
            issues.append(f"{path}: an Insufficient Information row states its limitation")
        if category != "Insufficient Information" and not _quotes(row):
            issues.append(f"{path}: a {category} row cites located evidence")
    if isinstance(row, CreditTranslation):
        if row.confidence != "Insufficient Information" and not row.citations:
            issues.append(f"{path}: a credit translation cites its evidence (source and locator)")
        if row.confidence == "Insufficient Information" and not row.limitation:
            issues.append(f"{path}: an Insufficient Information translation states its limitation")
    if isinstance(row, Conflict) and len(row.citations) < 2:
        issues.append(f"{path}: a conflict cites each conflicting span (at least two citations)")
    if (
        isinstance(row, DisclosureItem)
        and row.available in {"Yes", "Partial"}
        and not row.citations
    ):
        issues.append(f"{path}: an available disclosure item cites where it is disclosed")
    if isinstance(row, SourceUse) and row.quality != "Insufficient" and not row.citations:
        issues.append(f"{path}: a source assessed above Insufficient cites its content")
    if isinstance(row, OperatingDriver) and (row.status == "Not disclosed") != (
        row.measure is None
    ):
        issues.append(f"{path}: measure is null exactly when the driver is Not disclosed")
    if isinstance(row, GovernanceItem):
        issues.extend(_governance_issues(path, row))
    return issues


def _governance_issues(path: str, row: GovernanceItem) -> list[str]:
    flag_fields = ("behaviour_type", "amount_funding_source", "legal_capacity_link")
    issues: list[str] = []
    if row.kind == "behaviour_flag":
        missing = [name for name in flag_fields if getattr(row, name) is None]
        if missing:
            issues.append(f"{path}: a behaviour flag states {', '.join(missing)}")
    else:
        present = [name for name in flag_fields if getattr(row, name) is not None]
        if present:
            issues.append(f"{path}: a governance topic leaves {', '.join(present)} null")
        if row.direction == "Extraction-Oriented":
            issues.append(f"{path}: Extraction-Oriented is a behaviour category, not a direction")
    return issues


def _source_issues(pack: PreparedPack, submission: BusinessContextSubmission) -> list[str]:
    issues: list[str] = []
    seen = [item.source_id for item in submission.sources]
    for source_id in sorted({s for s in seen if seen.count(s) > 1}):
        issues.append(f"cp1a.source_ids_unique: {source_id} is assessed more than once")
    if set(seen) != {s.source_id for s in pack.sources} or len(seen) != len(pack.sources):
        issues.append("Assess every prepared source exactly once")
    available = {s.source_id for s in pack.sources if s.status == "ready"}
    for index, item in enumerate(submission.sources):
        if item.source_id not in available and item.quality != "Insufficient":
            issues.append(f"sources[{index}]: an unavailable source has Insufficient quality")
        if any(quote.source_id != item.source_id for quote in item.citations):
            issues.append(f"sources[{index}]: a source assessment cites another source")
    return issues


def _consumer_issues(pack: PreparedPack, submission: BusinessContextSubmission) -> list[str]:
    issues: list[str] = []
    judged = [item.module_id for item in submission.consumers]
    for module_id in sorted({m for m in judged if judged.count(m) > 1}):
        issues.append(f"cp1a.downstream_modules_unique: {module_id} is judged more than once")
    expected = cp1a_consumers(pack)
    if set(judged) != set(expected):
        issues.append(
            "Judge exactly the consumers listed in the CONTEXT block: " + ", ".join(expected)
        )
    return issues


def _shape_issues(submission: BusinessContextSubmission) -> list[str]:
    """Rules across rows: the company aspects, conflict ids and their references, and the
    evidenced credit-translation row (cp1a.credit_translation_has_evidenced_row)."""
    issues: list[str] = []
    aspects = [item.aspect for item in submission.company]
    for aspect in get_args(Aspect):
        if aspects.count(aspect) != 1:
            issues.append(f"company: state {aspect} exactly once")
    ids = [item.conflict_id for item in submission.conflicts]
    for conflict_id in sorted({c for c in ids if ids.count(c) > 1}):
        issues.append(f"conflicts: duplicate conflict_id {conflict_id}")
    for index, conflict_id in enumerate(ids):
        if not re.fullmatch(r"[A-Za-z][A-Za-z_.:-]{0,63}", conflict_id):
            issues.append(f"conflicts[{index}]: conflict_id is letters, '_', '.', ':' or '-'")
    for index, row in enumerate(submission.credit_translations):
        for unknown in sorted(set(row.countervailing_conflict_ids) - set(ids)):
            issues.append(f"credit_translations[{index}]: unknown conflict_id {unknown}")
    if not any(
        all(_populated(text) for text in (row.evidence, row.risk_mechanic, row.credit_implication))
        for row in submission.credit_translations
    ):
        issues.append(
            "cp1a.credit_translation_has_evidenced_row: at least one credit translation populates "
            "evidence, risk mechanic, credit implication and confidence"
        )
    return issues


def validate_business_context(
    pack: PreparedPack, submission: BusinessContextSubmission, cp1_facts: Sequence[Fact] = ()
) -> tuple[str, ...]:
    """Every issue of `submission` over `pack`, in a stable order; empty when it composes.

    `cp1_facts` are the CP-1 facts the CONTEXT block offered (`referencable`); a figure reference
    to anything else, a bare figure, a malformed reference or a chip is a run-text issue."""
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        submission = BusinessContextSubmission.model_validate_json(submission.model_dump_json())
    except ValidationError as error:
        return shape_issues(error)
    bound = prose.bind(referencable(cp1_facts))
    names = (pack.run.issuer_name,)
    binding = _bind(pack, submission)
    issues: list[str] = [*_source_issues(pack, submission), *_consumer_issues(pack, submission)]
    issues.extend(binding.issues)
    texts: list[tuple[str, tuple[str, ...]]] = []
    for path, row in _rows(submission):
        issues.extend(f"{path}: {i}" for i in citation_issues(binding.of(row), pack.sources))
        issues.extend(_row_issues(path, row))
        scope = tuple(dict.fromkeys(quote.source_id for quote in _quotes(row)))
        for name, text in _texts(row):
            where = f"{path}.{name}"
            if _blank(text):
                issues.append(f"{where}: empty text")
                continue
            issues.extend(f"{where}: {issue}" for issue in prose.issues(text, bound, names=names))
            issues.extend(prohibited_issues(where, text))
            texts.append((text, scope))
    issues.extend(_shape_issues(submission))
    issues.extend(absence_issues(pack, texts))
    return tuple(dict.fromkeys(issues))


# --- the T2D.8 governance score and the T2D.9 drivers (Python, documented rule) ---------------

_ADVERSE = frozenset({"Extraction-Oriented", "Creditor-Adverse"})
_QUALITY_ORDER: tuple[EvidenceQuality, ...] = ("High", "Medium", "Low")
NOT_SCORABLE = "Not Scorable"
MIN_SCORED_DIMENSIONS = 4  # r14 CP-2C: no composite unless at least four dimensions are scored
# r14 rubric scores and their words; "1" < "3" < "5" also as text, so `max` is the most adverse.
ASSESSMENT: Mapping[str, str] = {
    "1": "Creditor-favorable",
    "3": "Mixed",
    "5": "Adverse",
    NOT_SCORABLE: NOT_SCORABLE,
}
RISK_LEVEL: Mapping[str, str] = {"1": "Low", "3": "Medium", "5": "High"}
INSUFFICIENT_LEVEL = "Insufficient Information"


@dataclass(frozen=True)
class DimensionScore:
    dimension: Dimension
    score: str  # "1", "3", "5" or NOT_SCORABLE
    deciding: tuple[GovernanceItem, ...]  # the rows that set the score (none when not scored)

    @property
    def assessment(self) -> str:
        return ASSESSMENT[self.score]

    @property
    def evidence_quality(self) -> str:
        """The strongest evidence quality among the deciding rows ("Insufficient" for none)."""
        found = {row.evidence_quality for row in self.deciding}
        return next((q for q in _QUALITY_ORDER if q in found), "Insufficient")


@dataclass(frozen=True)
class GovernanceScore:
    dimensions: tuple[DimensionScore, ...]
    composite: str  # the most adverse dimension score, or NOT_SCORABLE
    risk_level: str  # Low, Medium, High or Insufficient Information
    high_risk_action: bool  # an adverse row on High-quality evidence (r14's override)

    @property
    def scored(self) -> int:
        return sum(item.score != NOT_SCORABLE for item in self.dimensions)


def scorable(row: GovernanceItem) -> bool:
    """A row informs its dimension's score when it names one and is evidenced: its direction,
    category and evidence quality are none of the Insufficient values."""
    return (
        row.dimension is not None
        and row.direction != "Insufficient Information"
        and row.category != "Insufficient Information"
        and row.evidence_quality != "Insufficient"
    )


def dimension_score(dimension: Dimension, rows: Sequence[GovernanceItem]) -> DimensionScore:
    """r14 rubric 1 / 3 / 5 over one dimension's scorable rows: every row Supportive is 1
    (creditor-favorable); any Extraction-Oriented or Creditor-Adverse row and no Supportive row
    is 5 (adverse), decided by the adverse rows; anything else (Neutral, Mixed, or support beside
    extraction, r14's "support and extraction coexist") is 3. No row: Not Scorable."""
    directions = {row.direction for row in rows}
    if not rows:
        return DimensionScore(dimension, NOT_SCORABLE, ())
    if directions == {"Supportive"}:
        return DimensionScore(dimension, "1", tuple(rows))
    if directions & _ADVERSE and "Supportive" not in directions:
        return DimensionScore(dimension, "5", tuple(r for r in rows if r.direction in _ADVERSE))
    return DimensionScore(dimension, "3", tuple(rows))


def governance_sponsor_score(rows: Sequence[GovernanceItem]) -> GovernanceScore:
    """T2D.8 and the Sponsor / Governance Risk Level, from the categorised governance rows only.

    Each dimension is scored by `dimension_score` over its `scorable` rows. With at least
    `MIN_SCORED_DIMENSIONS` dimensions scored, the composite is the most adverse dimension score
    and the risk level follows it (1 Low, 3 Medium, 5 High). With fewer, the composite is Not
    Scorable and the level Insufficient Information, unless one Extraction-Oriented or
    Creditor-Adverse row rests on High-quality evidence (r14: "unless one clearly High-risk
    documented action"), which sets High. Counts and severities only: no weight, no average."""
    evidenced = [row for row in rows if scorable(row)]
    dimensions = tuple(
        dimension_score(dimension, [row for row in evidenced if row.dimension == dimension])
        for dimension in DIMENSIONS
    )
    scores = [item.score for item in dimensions if item.score != NOT_SCORABLE]
    high_action = any(r.direction in _ADVERSE and r.evidence_quality == "High" for r in evidenced)
    if len(scores) < MIN_SCORED_DIMENSIONS:
        level = RISK_LEVEL["5"] if high_action else INSUFFICIENT_LEVEL
        return GovernanceScore(dimensions, NOT_SCORABLE, level, high_action)
    composite = max(scores)
    return GovernanceScore(dimensions, composite, RISK_LEVEL[composite], high_action)


# --- composition -----------------------------------------------------------------------------

LABEL: Mapping[str, str] = {
    "Management Language": " [Management Language]",
    "Analyst Interpretation": " [Analyst Interpretation]",
    "Insufficient Information": " [Insufficient Information]",
}
NONE_STATED = "None stated"
NO_EVIDENCE = "No located evidence"
_STATUS_OF_CATEGORY: Mapping[str, str] = {
    "Documentary Fact": "Documented",
    "Management Language": "Management Language",
    "Analyst Interpretation": "Analyst Interpretation",
    "Insufficient Information": "Insufficient Information",
}
_CONSEQUENCE: Mapping[str, str] = {"Critical": "High", "Material": "Medium", "Minor": "Low"}
# T2D.9 Evidence Quality from the translation's confidence, level for level (r14 uses the same
# four grades for both; "Insufficient Information" is the label "Insufficient").
_QUALITY_OF_CONFIDENCE: Mapping[str, str] = {
    "High": "High",
    "Medium": "Medium",
    "Low": "Low",
    "Insufficient Information": "Insufficient",
}


@dataclass(frozen=True)
class Register:
    table_id: str
    title: str
    columns: tuple[tuple[str, str], ...]  # (field, r14 column label)
    # An empty register is one row of unsettled cells: `missing` (a gap, and a module
    # limitation) or `not_applicable` ("none logged": the conflict log and the gap ledgers).
    empty: Literal["missing", "not_applicable"] = "missing"


def _register(
    table_id: str, title: str, columns: str, empty: Literal["missing", "not_applicable"] = "missing"
) -> Register:
    """A register from its r14 column labels, `|`-separated; each field is the label in
    snake case."""
    labels = columns.split("|")
    fields = [re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_") for label in labels]
    return Register(table_id, title, tuple(zip(fields, labels, strict=True)), empty)


REGISTERS: Mapping[str, Register] = {
    item.table_id: item
    for item in (
        _register(
            "source_classification",
            "Source classification",
            "Source ID|Source class|Quality|Use|Limitation",
        ),
        _register(
            "transaction_summary",
            "Transaction summary",
            "Transaction|Status|Credit relevance|Source",
        ),
        _register(
            "company_description",
            "Company description",
            "Issuer|Business description|Country|Sector",
        ),
        _register(
            "revenue_business_mix",
            "Revenue and business mix",
            "Business line|Revenue mix|Period|Status|Limitation",
        ),
        _register(
            "ownership_register",
            "Ownership register",
            "Owner / class|Control|Economic interest|Credit relevance|Source",
        ),
        _register(
            "operating_model",
            "Operating model",
            "Operating driver|Measure|Period|Status|Credit relevance",
        ),
        _register(
            "events_timeline",
            "Events timeline",
            "Date / window|Event|Credit relevance|Status|Source",
        ),
        _register(
            "credit_translation",
            "Credit translation",
            "Evidence|Risk mechanic|Credit implication|Confidence|Limitation",
        ),
        _register(
            "gaps_ledger",
            "Gaps ledger",
            "Gap|Affected analysis|Severity|Action|Status",
            "not_applicable",
        ),
        _register(
            "conflict_log",
            "Conflict log",
            "Conflict|Sources|Materiality|Resolution|Downstream impact",
            "not_applicable",
        ),
        _register(
            "downstream_readiness",
            "Downstream readiness",
            "Module|Status|Gap|Required action",
        ),
        _register(
            "T2D.1",
            "Source register",
            "source_document_id|source_document_name|source_quality|period|entity_covered|"
            "data_supplied|limitation|downstream_use",
        ),
        _register(
            "T2D.2",
            "Ownership and control register",
            "Item|Source-Supported Fact|Evidence Quality|Source Trace|Credit Mechanic|"
            "Credit Implication|Limitation",
        ),
        _register(
            "T2D.3",
            "Governance register",
            "Governance Topic|Source-Supported Fact|Risk Direction|Risk Mechanic|"
            "Credit Implication|Evidence Quality|Source Trace|Limitation",
        ),
        _register(
            "T2D.4",
            "Behaviour flag register",
            "Flag ID|Behavior Type|Documented Action|Behavior Category|Amount / Funding Source|"
            "Legal-Capacity Link|Risk Mechanic|Credit Implication|Evidence Quality|Source Trace|"
            "Limitation",
        ),
        _register(
            "T2D.5",
            "Capital allocation risk table",
            "Capital Allocation Item|Source-Supported Fact|Direction|Risk Mechanic|"
            "Credit Implication|Evidence Quality|Source Trace|Limitation",
        ),
        _register(
            "T2D.6",
            "Acquisition appetite and integration",
            "Acquisition / Period|Source-Supported Fact|Funding Mix|EBITDA / Pro Forma Basis|"
            "Integration Evidence|Leverage / Liquidity Effect|Risk Mechanic|Credit Implication|"
            "Source Trace|Limitation",
        ),
        _register(
            "T2D.7",
            "Disclosure quality log",
            "Disclosure Item|Available?|Source-Supported Detail|Credit Relevance|Severity|"
            "Source Trace|Required Follow-Up",
        ),
        _register(
            "T2D.8",
            "Governance and sponsor score",
            "Dimension|Assessment|Evidence|Risk Mechanic|Credit Implication|Score|"
            "Evidence Quality|Source Trace|Limitation",
        ),
        _register(
            "T2D.9",
            "Sponsor risk-level drivers",
            "Risk-Level Driver|Evidence|Risk Mechanic|Credit Implication|Evidence Quality|"
            "Source Trace|Countervailing Evidence|Limitation",
        ),
        _register(
            "T2D.10",
            "Cross-module handoff register",
            "Downstream Module|Handoff Tag|Handoff Item|Why It Matters|"
            "Required Consumer Action|Source / Flag Link|Limitation",
        ),
        _register(
            "T2D.11",
            "Governance gaps ledger",
            "Gap ID|Missing Data|Why It Matters|Affected Section / Flag / Export Record|"
            "Consequence for Confidence|Required Follow-Up Source",
            "not_applicable",
        ),
        _register(
            "cp1a.cp_model_snapshot_fields",
            "CP-MODEL snapshot fields",
            "field_id|value|status|source_id|source_locator|as_of",
        ),
    )
}
# The r14 required registers (the conditional CP-MODEL snapshot table is emitted on every run).
REQUIRED_REGISTERS = tuple(key for key in REGISTERS if key != "cp1a.cp_model_snapshot_fields")
CP1_REFERENCES = "cp1_references"
COMPANY_ROW = "company"
# Front Page and rail destinations of CP-1A's registers (bindings/cp1a.py), for T2D.10.
DESTINATIONS = (
    "company-operating-model; company-profile; transaction-summary; evidence; limitations"
)


@dataclass(frozen=True)
class Cell:
    """A composed cell: its text (None when unsettled), citations and how it was written."""

    text: str | None
    citations: tuple[Citation, ...] = ()
    judged: bool = False  # model-written analysis rather than a Python value
    reason: str | None = None  # why an unsettled cell is unsettled
    status: Literal["known", "missing", "not_applicable"] = "known"


def _trace(citations: tuple[Citation, ...]) -> str:
    """A Python source trace: each distinct `source_id locator`, in citation order."""
    return "; ".join(dict.fromkeys(f"{c.source_id} {c.locator}" for c in citations))


class _Composer:
    """Writes the registers: cells from validated rows, tables, facts and own limitations."""

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
        """Model text, cited by its row."""
        cited = self.binding.of(row) if row is not None else ()
        return Cell(self.text(value), cited, judged=True)

    def tagged(self, value: str, row: BaseModel) -> Cell:
        """A fact row's main text with its r14 category label ([Management Language] ...)."""
        category = str(getattr(row, "category", "Documentary Fact"))
        return Cell(self.text(value) + LABEL.get(category, ""), self.binding.of(row), judged=True)

    def limit(self, row: BaseModel) -> Cell:
        limitation = getattr(row, "limitation", None)
        return Cell(self.text(limitation) if limitation else NONE_STATED)

    def trace(self, row: BaseModel) -> Cell:
        cited = self.binding.of(row)
        return Cell(_trace(cited) or NO_EVIDENCE, cited)

    def joined(self, values: Iterable[str]) -> str:
        return "; ".join(dict.fromkeys(self.text(value) for value in values))

    def table(self, register: Register, rows: Sequence[tuple[str, Sequence[Cell]]]) -> None:
        if not rows:
            title = register.title.lower()
            if register.empty == "missing":
                reason = f"No {title} rows in the CP-1A submission"
                self.limitations.append(reason)
            else:
                reason = f"None logged in the CP-1A submission ({title})"
            cell = Cell(None, reason=reason, status=register.empty)
            rows = (("none", tuple(cell for _ in register.columns)),)
        table_rows: list[TableRow] = []
        for row_id, cells in rows:
            ids: list[str] = []
            for (field, label), cell in zip(register.columns, cells, strict=True):
                fact_id = f"{register.table_id}.{row_id}.{field}"
                self.facts.append(
                    Fact(
                        fact_id=fact_id,
                        label=label,
                        table_id=register.table_id,
                        row_id=row_id,
                        field=field,
                        text=cell.text,
                        status="known" if cell.text is not None else cell.status,
                        citations=cell.citations,
                        value_class="analyst_judgment" if cell.judged else None,
                        limitation=cell.reason if cell.text is None else None,
                    )
                )
                ids.append(fact_id)
            label = cells[0].text or register.columns[0][1]
            table_rows.append(TableRow(row_id=row_id, label=label, fact_ids=tuple(ids)))
        self.tables.append(
            ReportTable(
                table_id=register.table_id,
                title=register.title,
                columns=tuple(TableColumn(field=f, label=label) for f, label in register.columns),
                rows=tuple(table_rows),
                row_header=register.columns[0][1],
            )
        )


def _numbered(cells: Iterable[Sequence[Cell]]) -> list[tuple[str, Sequence[Cell]]]:
    return [(f"r{index:02d}", row) for index, row in enumerate(cells, 1)]


def _source_registers(submission: BusinessContextSubmission, out: _Composer) -> None:
    """source_classification and T2D.1: one row per pack source, its assessment beside the
    pack's own name and limitation; a source no CP-1A row cites says so."""
    uses = {item.source_id: item for item in submission.sources}
    cited = {c.source_id for _, row in _rows(submission) for c in out.binding.of(row)}
    pairs = [(s, uses[s.source_id]) for s in out.pack.sources]

    def limit(source: Source, use: SourceUse) -> Cell:
        parts = [out.text(use.limitation)] if use.limitation else []
        parts += [source.limitation] if source.limitation else []
        parts += [] if source.source_id in cited else ["Not cited by any CP-1A row"]
        return Cell("; ".join(parts) or NONE_STATED)

    out.table(
        REGISTERS["source_classification"],
        _numbered(
            (
                Cell(s.source_id),
                Cell(u.source_class),
                Cell(u.quality),
                out.said(u.use, u),
                limit(s, u),
            )
            for s, u in pairs
        ),
    )
    out.table(
        REGISTERS["T2D.1"],
        _numbered(
            (
                Cell(s.source_id),
                Cell(s.name),
                Cell(u.quality),
                out.said(u.period, u) if u.period else Cell(NONE_STATED),
                out.said(u.entity_covered, u),
                out.said(u.data_supplied, u),
                limit(s, u),
                out.said(u.use, u),
            )
            for s, u in pairs
        ),
    )


def _fact_registers(submission: BusinessContextSubmission, out: _Composer) -> None:
    """The business and transaction fact pack (r14 steps 3 to 7)."""
    company = {item.aspect: item for item in submission.company}
    out.table(
        REGISTERS["company_description"],
        [
            (
                COMPANY_ROW,
                (
                    Cell(out.pack.run.issuer_name),
                    *(out.tagged(company[a].text, company[a]) for a in get_args(Aspect)),
                ),
            )
        ],
    )
    out.table(
        REGISTERS["transaction_summary"],
        _numbered(
            (
                out.tagged(t.transaction, t),
                Cell(t.status),
                out.said(t.credit_relevance, t),
                out.trace(t),
            )
            for t in submission.transactions
        ),
    )
    out.table(
        REGISTERS["revenue_business_mix"],
        _numbered(
            (
                out.said(b.name, b),
                out.tagged(b.revenue_mix, b),
                out.said(b.period, b),
                Cell(_STATUS_OF_CATEGORY[b.category]),
                out.limit(b),
            )
            for b in submission.business_lines
        ),
    )
    out.table(
        REGISTERS["ownership_register"],
        _numbered(
            (
                out.tagged(o.owner, o),
                out.said(o.control, o),
                out.said(o.economic_interest, o),
                out.said(o.credit_relevance, o),
                out.trace(o),
            )
            for o in submission.owners
        ),
    )
    undisclosed = _gap("Not disclosed by the source (r14: null, never 0)")
    out.table(
        REGISTERS["operating_model"],
        _numbered(
            (
                out.said(d.driver, d),
                out.tagged(d.measure, d) if d.measure is not None else undisclosed,
                out.said(d.period, d),
                Cell(d.status),
                out.said(d.credit_relevance, d),
            )
            for d in submission.operating_drivers
        ),
    )
    out.table(
        REGISTERS["events_timeline"],
        _numbered(
            (
                out.said(e.date_window, e),
                out.tagged(e.event, e),
                out.said(e.credit_relevance, e),
                Cell(e.status),
                out.trace(e),
            )
            for e in submission.events
        ),
    )


def _gap(reason: str) -> Cell:
    """An unsettled cell (`missing`): shown as a gap with its reason, never as a value."""
    return Cell(None, reason=reason, status="missing")


def _ledger_registers(submission: BusinessContextSubmission, out: _Composer) -> None:
    """credit_translation, gaps_ledger and conflict_log (r14 steps 8 and 9)."""
    out.table(
        REGISTERS["credit_translation"],
        _numbered(
            (
                out.said(c.evidence, c),
                out.said(c.risk_mechanic, c),
                out.said(c.credit_implication, c),
                Cell(c.confidence),
                out.limit(c),
            )
            for c in submission.credit_translations
        ),
    )
    out.table(
        REGISTERS["gaps_ledger"],
        _numbered(
            (
                out.said(g.gap),
                out.said(g.affected_analysis),
                Cell(g.severity),
                out.said(g.action),
                Cell("Open"),
            )
            for g in submission.gaps
        ),
    )
    out.table(
        REGISTERS["conflict_log"],
        _numbered(
            (
                out.said(c.conflict, c),
                Cell(
                    ", ".join(dict.fromkeys(x.source_id for x in out.binding.of(c))),
                    out.binding.of(c),
                ),
                Cell(c.materiality),
                Cell("Logged, not reconciled"),
                out.said(c.downstream_impact, c),
            )
            for c in submission.conflicts
        ),
    )


def _governance_registers(submission: BusinessContextSubmission, out: _Composer) -> None:
    """T2D.2 to T2D.7, the absorbed CP-2C registers the model supplies."""
    out.table(
        REGISTERS["T2D.2"],
        _numbered(
            (
                out.said(o.owner, o),
                out.tagged(f"Control: {o.control}; economic interest: {o.economic_interest}", o),
                Cell(o.evidence_quality),
                out.trace(o),
                out.said(o.credit_mechanic, o),
                out.said(o.credit_implication, o),
                out.limit(o),
            )
            for o in submission.owners
        ),
    )
    rows = submission.governance_and_sponsor
    out.table(
        REGISTERS["T2D.3"],
        _numbered(
            (
                out.said(g.topic, g),
                out.tagged(g.documented_fact, g),
                Cell(g.direction),
                out.said(g.risk_mechanic, g),
                out.said(g.credit_implication, g),
                Cell(g.evidence_quality),
                out.trace(g),
                out.limit(g),
            )
            for g in rows
            if g.kind == "governance_topic"
        ),
    )
    flags = [g for g in rows if g.kind == "behaviour_flag"]
    out.table(
        REGISTERS["T2D.4"],
        _numbered(
            (
                Cell(f"CP-2C-FLAG-{index:03d}"),
                Cell(str(g.behaviour_type)),
                out.tagged(g.documented_fact, g),
                Cell(g.direction),
                out.said(str(g.amount_funding_source), g),
                out.said(str(g.legal_capacity_link), g),
                out.said(g.risk_mechanic, g),
                out.said(g.credit_implication, g),
                Cell(g.evidence_quality),
                out.trace(g),
                out.limit(g),
            )
            for index, g in enumerate(flags, 1)
        ),
    )
    out.table(
        REGISTERS["T2D.5"],
        _numbered(
            (
                out.said(c.item, c),
                out.tagged(c.fact, c),
                Cell(c.direction),
                out.said(c.risk_mechanic, c),
                out.said(c.credit_implication, c),
                Cell(c.evidence_quality),
                out.trace(c),
                out.limit(c),
            )
            for c in submission.capital_allocation
        ),
    )
    out.table(
        REGISTERS["T2D.6"],
        _numbered(
            (
                out.said(a.acquisition_period, a),
                out.tagged(a.fact, a),
                out.said(a.funding_mix, a),
                out.said(a.pro_forma_basis, a),
                out.said(a.integration_evidence, a),
                out.said(a.leverage_liquidity_effect, a),
                out.said(a.risk_mechanic, a),
                out.said(a.credit_implication, a),
                out.trace(a),
                out.limit(a),
            )
            for a in submission.acquisitions
        ),
    )
    out.table(
        REGISTERS["T2D.7"],
        _numbered(
            (
                out.said(d.item, d),
                Cell(d.available),
                out.said(d.detail, d),
                out.said(d.credit_relevance, d),
                Cell(d.severity),
                out.trace(d),
                out.said(d.follow_up, d),
            )
            for d in submission.disclosure_items
        ),
    )


def _score_registers(submission: BusinessContextSubmission, out: _Composer) -> None:
    """T2D.8 (`governance_sponsor_score`) and T2D.9 (the credit translations as risk-level
    drivers, with countervailing evidence from the conflicts they name)."""
    score = governance_sponsor_score(submission.governance_and_sponsor)
    unscored = "No evidenced governance or sponsor row informs this dimension"
    rows: list[tuple[str, Sequence[Cell]]] = []
    for index, item in enumerate(score.dimensions, 1):
        deciding = item.deciding
        cited = tuple(dict.fromkeys(c for row in deciding for c in out.binding.of(row)))

        def chain(texts: Iterable[str], cited: tuple[Citation, ...] = cited) -> Cell:
            joined = out.joined(texts)
            return Cell(joined, cited, judged=True) if joined else _gap(unscored)

        limits = [row.limitation for row in deciding if row.limitation]
        rows.append(
            (
                f"d{index:02d}",
                (
                    Cell(item.dimension),
                    Cell(item.assessment),
                    chain(r.documented_fact for r in deciding),
                    chain(r.risk_mechanic for r in deciding),
                    chain(r.credit_implication for r in deciding),
                    Cell(item.score),
                    Cell(item.evidence_quality),
                    Cell(_trace(cited) or NO_EVIDENCE, cited),
                    Cell(out.joined(limits) or NONE_STATED),
                ),
            )
        )
    supported = f"{score.scored} of {len(DIMENSIONS)} scoring dimensions supported"
    if score.composite != NOT_SCORABLE:
        rule = "The most adverse dimension score; at least four dimensions are scored"
    elif score.high_risk_action:
        rule = (
            "Fewer than four dimensions are scored; one Extraction-Oriented or Creditor-Adverse "
            "row on High-quality evidence sets the level High"
        )
    else:
        rule = "Fewer than four dimensions are scored, so no composite is calculated"
        out.limitations.append(f"Sponsor / Governance Risk Level Insufficient Information: {rule}")
    rows.append(
        (
            "composite",
            (
                Cell("Composite"),
                Cell(f"Sponsor / Governance Risk Level: {score.risk_level}"),
                Cell(supported),
                Cell(rule),
                Cell(f"Sponsor / Governance Risk Level: {score.risk_level}"),
                Cell(score.composite),
                Cell("Derived from the dimension rows"),
                Cell("The dimension rows above"),
                Cell(NONE_STATED),
            ),
        )
    )
    out.table(REGISTERS["T2D.8"], rows)
    conflicts = {item.conflict_id: item for item in submission.conflicts}
    countered = "Insufficient Information: no logged conflict counters this driver"
    out.table(
        REGISTERS["T2D.9"],
        _numbered(
            (
                Cell(c.theme),
                out.said(c.evidence, c),
                out.said(c.risk_mechanic, c),
                out.said(c.credit_implication, c),
                Cell(_QUALITY_OF_CONFIDENCE[c.confidence]),
                out.trace(c),
                Cell(
                    out.joined(conflicts[x].conflict for x in c.countervailing_conflict_ids)
                    or countered
                ),
                out.limit(c),
            )
            for c in submission.credit_translations
        ),
    )


def _handoff_registers(submission: BusinessContextSubmission, out: _Composer) -> None:
    """downstream_readiness, T2D.10, T2D.11 and the CP-MODEL snapshot fields (r14 step 10)."""
    order = cp1a_consumers(out.pack)
    consumers = sorted(submission.consumers, key=lambda c: order.index(c.module_id))
    out.table(
        REGISTERS["downstream_readiness"],
        _numbered(
            (Cell(c.module_id), Cell(c.status), out.said(c.gap), out.said(c.required_action))
            for c in consumers
        ),
    )
    out.table(
        REGISTERS["T2D.10"],
        _numbered(
            (
                Cell(c.module_id),
                Cell(f"CP-2C-HANDOFF-{c.module_id}"),
                out.said(c.handoff_item),
                out.said(c.why_it_matters),
                out.said(c.required_action),
                Cell(DESTINATIONS),
                out.said(c.gap),
            )
            for c in consumers
        ),
    )
    out.table(
        REGISTERS["T2D.11"],
        [
            (
                f"r{index:02d}",
                (
                    Cell(f"CP-1A-GAP-{index:03d}"),
                    out.said(g.gap),
                    out.said(g.why_it_matters),
                    out.said(g.affected_analysis),
                    Cell(_CONSEQUENCE[g.severity]),
                    out.said(g.action),
                ),
            )
            for index, g in enumerate(submission.gaps, 1)
        ],
    )
    out.table(REGISTERS["cp1a.cp_model_snapshot_fields"], _snapshot_rows(submission, out))


def _snapshot_rows(
    submission: BusinessContextSubmission, out: _Composer
) -> list[tuple[str, Sequence[Cell]]]:
    """The six r14 CP-MODEL snapshot fields. Each is READY only where located CP-1A rows supply
    it (the issuer name: the run identity); otherwise a GAP row whose value and source cells are
    unsettled. Several rows (owners, transactions) are joined in order, with every source."""
    as_of = out.pack.run.as_of.isoformat()
    company = {item.aspect: item for item in submission.company}

    supplied: dict[str, tuple[tuple[str, ...], tuple[BaseModel, ...]]] = {
        "sector": ((company["sector"].text,), (company["sector"],)),
        "country": ((company["country"].text,), (company["country"],)),
        "shareholders": (tuple(o.owner for o in submission.owners), submission.owners),
        "transaction_summary": (
            tuple(t.transaction for t in submission.transactions),
            submission.transactions,
        ),
        "business_description": (
            (company["business_description"].text,),
            (company["business_description"],),
        ),
    }
    rows: list[tuple[str, Sequence[Cell]]] = [
        (
            "issuer_name",
            (
                Cell("issuer_name"),
                Cell(out.pack.run.issuer_name),
                Cell("READY"),
                Cell("prepared-pack"),
                Cell("run.issuer_name"),
                Cell(as_of),
            ),
        )
    ]
    for field, (texts, sources) in supplied.items():
        cited = tuple(dict.fromkeys(c for row in sources for c in out.binding.of(row)))
        if not texts or not cited:
            gap = _gap(f"CP-1A has no located {field.replace('_', ' ')}")
            rows.append((field, (Cell(field), gap, Cell("GAP"), gap, gap, Cell(as_of))))
            continue
        rows.append(
            (
                field,
                (
                    Cell(field),
                    Cell(out.joined(texts), cited, judged=True),
                    Cell("READY"),
                    Cell(", ".join(dict.fromkeys(c.source_id for c in cited))),
                    Cell("; ".join(dict.fromkeys(c.locator for c in cited))),
                    Cell(as_of),
                ),
            )
        )
    return rows


def business_context(
    pack: PreparedPack, submission: BusinessContextSubmission, cp1_facts: Sequence[Fact] = ()
) -> BusinessContextReport:
    """The composed CP-1A registers of a valid submission; raises ValueError on any issue."""
    issues = validate_business_context(pack, submission, cp1_facts)
    if issues:
        raise ValueError("; ".join(issues))
    pack = PreparedPack.model_validate_json(pack.model_dump_json())
    submission = BusinessContextSubmission.model_validate_json(submission.model_dump_json())
    out = _Composer(pack, _bind(pack, submission), prose.bind(referencable(cp1_facts)))
    for _, row in _rows(submission):
        if getattr(row, "category", None) == "Insufficient Information":
            out.limitations.append(out.text(str(getattr(row, "limitation", ""))))
    out.limitations.extend(f"Gap ({g.severity}): {out.text(g.gap)}" for g in submission.gaps)
    for compose in (
        _source_registers,
        _fact_registers,
        _ledger_registers,
        _governance_registers,
        _score_registers,
        _handoff_registers,
    ):
        compose(submission, out)
    referenced = [
        fact.model_copy(
            update={"table_id": CP1_REFERENCES, "row_id": f"ref{index:02d}", "field": "value"}
        )
        for index, fact in enumerate(out.referenced.values(), 1)
    ]
    tables = list(out.tables)
    if referenced:
        tables.append(
            ReportTable(
                table_id=CP1_REFERENCES,
                title="CP-1 facts referenced in CP-1A text",
                columns=(TableColumn(field="value", label="Value"),),
                rows=tuple(
                    TableRow(
                        row_id=fact.row_id,
                        label=f"{fact.label} · {fact.period}" if fact.period else fact.label,
                        fact_ids=(fact.fact_id,),
                    )
                    for fact in referenced
                ),
                row_header="CP-1 fact",
            )
        )
    claims = tuple(
        Claim(
            claim_id=f"credit_translation.r{index:02d}",
            text=f"{row.evidence} Risk mechanic: {row.risk_mechanic} "
            f"Credit implication: {row.credit_implication}",
            citations=out.binding.of(row),
            limitation=row.limitation,
        )
        for index, row in enumerate(submission.credit_translations, 1)
    )
    report = BusinessContextReport(
        run=pack.run,
        pack_sha256=pack.content_hash(),
        submission_sha256=submission.content_hash(),
        tables=tuple(tables),
        facts=(*out.facts, *referenced),
        claims=claims,
        limitations=tuple(dict.fromkeys(out.limitations)),
    )
    if found := register_rule_issues(report):
        raise ValueError("; ".join(found))
    return report


# --- the r14 semantic rules over the composed registers ---------------------------------------

CONFIDENCE_VALUES = frozenset(get_args(Confidence))


def register_rule_issues(report: BusinessContextReport) -> tuple[str, ...]:
    """The four r14 `cp1a.*` semantic rules, checked on the composed registers themselves
    (r14's completeness check reads the handoff, not the submission)."""
    facts = {fact.fact_id: fact for fact in report.facts}
    tables = {table.table_id: table for table in report.tables}

    def column(table_id: str, field: str) -> list[str | None]:
        table = tables[table_id]
        position = [c.field for c in table.columns].index(field)
        return [facts[row.fact_ids[position]].text for row in table.rows]

    issues: list[str] = []
    for rule, table_id, field in (
        ("cp1a.source_ids_unique", "source_classification", "source_id"),
        ("cp1a.downstream_modules_unique", "downstream_readiness", "module"),
    ):
        values = [value for value in column(table_id, field) if value is not None]
        if len(values) != len(set(values)):
            issues.append(f"{rule}: {table_id} repeats a {field} value")
    confidence = column("credit_translation", "confidence")
    if any(value is not None and value not in CONFIDENCE_VALUES for value in confidence):
        issues.append(
            "cp1a.credit_translation_confidence_enum: confidence is High, Medium, Low or "
            "Insufficient Information"
        )
    rows = zip(
        *(
            column("credit_translation", field)
            for field in ("evidence", "risk_mechanic", "credit_implication", "confidence")
        ),
        strict=True,
    )
    if not any(all(cell is not None and _populated(cell) for cell in row) for row in rows):
        issues.append(
            "cp1a.credit_translation_has_evidenced_row: no credit translation row populates "
            "evidence, risk mechanic, credit implication and confidence"
        )
    return tuple(issues)


# --- the module and the journal ---------------------------------------------------------------


def cp1a_module(report: BusinessContextReport, inputs: Sequence[Input], attempt: int) -> Module:
    """The CP-1A candidate: the report's registers and claims bound to `inputs`."""
    run = report.run
    return Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id=MODULE_ID,
        inputs=(
            *inputs,
            Input(input_id="business-context-submission", sha256=report.submission_sha256),
        ),
        facts=report.facts,
        tables=report.tables,
        claims=report.claims,
        limitations=report.limitations,
        attempt=attempt,
    )


def _validate_step(store: Execution, pack: PreparedPack, attempt: Attempt) -> StepValidation:
    try:
        submission = BusinessContextSubmission.model_validate_json(
            store.payload(attempt.steps[0].payload_sha256)
        )
    except ValidationError as error:
        return StepValidation(issues=shape_issues(error))
    facts = cp1_context_facts(store, attempt)
    issues = validate_business_context(pack, submission, facts)
    if issues:
        return StepValidation(issues=issues)
    return StepValidation(output=business_context(pack, submission, facts).model_dump_json())


def submit_cp1a_step(store: Execution, ticket_id: str, step_id: str, payload: str) -> Attempt:
    """Retain the one `business_context` response, validate it, then settle CP-1A with the
    Python candidate (as `submit_cp0_review`): promotion is an accepted step, run text that
    resolves and no validator issue. An invalid step finishes the attempt rejected (or blocked on
    the repair). A crash after the step resumes from the retained valid step."""
    if step_id != STEP_ID:
        raise ValueError(f"CP-1A has one step, {STEP_ID}")
    attempt = next((a for a in store.read().attempts if a.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != MODULE_ID or attempt.status != "pending":
        raise ValueError("Ticket is absent, finished or belongs to another module")
    if attempt.steps and attempt.steps[0].payload_sha256 != text_sha256(payload):
        raise ValueError("Ticket already retains a different response; resume or interrupt")
    if not attempt.steps or attempt.steps[0].status == "pending":
        attempt = store.submit_step(
            ticket_id,
            MODULE_ID,
            CP1A_STEPS,
            STEP_ID,
            payload,
            lambda pack, current: _validate_step(store, pack, current),
        )
    if attempt.status == "finished":
        return attempt
    outcome = _validate_step(store, store.pack(), attempt)
    if outcome.issues or not outcome.retained_as(attempt.steps[0]):
        raise ValueError("Retained CP-1A output differs from trusted validation")
    report = BusinessContextReport.model_validate_json(outcome.output or "")
    candidate = cp1a_module(report, attempt.inputs, attempt.number)
    return store.finish(
        ticket_id,
        candidate.model_dump_json(),
        lambda supplied: () if supplied == candidate else ("CP-1A candidate differs",),
        qualification=PROMOTED,
    )


def context_block(pack: PreparedPack, cp1_facts: Sequence[Fact]) -> dict[str, object]:
    """What the `business_context` CONTEXT block adds to the pack facts: the consumers to judge
    (registry title and purpose) and the CP-1 facts a figure reference may name (id, label,
    period, unit and Python's spelling), or the statement that none may be referenced."""
    registry = {item.module_id: item for item in modules()}
    facts = referencable(cp1_facts)
    return {
        "consumers": [
            {
                "module_id": module_id,
                "title": registry[module_id].title,
                "purpose": registry[module_id].purpose,
            }
            for module_id in cp1a_consumers(pack)
        ],
        "cp1_facts": [
            {
                "ref": fact.fact_id,
                "label": fact.label,
                "period": fact.period,
                "unit": figure_unit(fact) or fact.unit,
                "shown": spelled(fact),
            }
            for fact in facts
        ],
        "cp1_facts_note": (
            "Reference a figure only as {ref|unit} with a ref and unit listed in cp1_facts."
            if facts
            else "CP-1 is not accepted in this journal: no figure may be referenced, so write "
            "no figure at all (labels only)."
        ),
    }
