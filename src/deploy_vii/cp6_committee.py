"""CP-6 committee challenge (task 8.5): one live step, `committee_challenge`.

Decision 0008 MC-1, as for CP-2 and CP-3: the model returns a `CommitteeSubmission`, judgments
only. It challenges CP-2's thesis points (the strongest counter-case per point and what would
change the view) and states an action bias with its confidence, the only final recommendation
in the run (docs/frontend-direction-c.md). Python owns every figure, id, hash, status,
limitation and the call-band mapping (`call_scale`).

Evidence (coordinator rulings 1 and 6): CP-6 reads the bound heads of its graph edges, CP-0,
CP-1, CP-2, CP-3 and CP-5 required and CP-1A optional (read only when the run selects it). CP-4
is no CP-6 edge: its evidence reaches CP-6 only through CP-5's findings and limitations. A
row's basis cites rows by id, never restated: `cp2_refs` and `cp3_refs` name `<table_id>.<row_id>`
rows of the bound CP-2 and CP-3 registers, `cp5_refs` rows of CP-5's findings, module status,
report-level limitations and verdict tables or a `CP-5-FINDING-NNN` id; its CP-1 basis is the
`{ref|unit}` references in its text. No pack quote. `validate_committee` holds the submission,
in Python only, to:

- reference existence: every ref resolves, a challenge names a CP-2 thesis, strength, weakness
  or key-finding row once, and every row cites at least one ref (`prose.issues`: no bare
  figure, no chip);
- provenance and staleness against `execution.current_inputs`, as CP-3; a required upstream
  that is not accepted or restricted refuses the step (decision 0007: CP-5's handoff is Passed
  or Restricted);
- gap propagation (decision 0007): a blocked ancestor, a restricted CP-5 or CP-5's unsupported
  claims and contradictions cap the confidence below High (so no High Overweight or
  Underweight); a recommendation that rests only on claims CP-5 flags is refused; CP-3 without
  observed or indicative market evidence, or with an Insufficient Information preference, makes
  the action bias Insufficient Information; a recovery view without CP-4 evidence carried by a
  CP-5 finding or limitation is Insufficient Information;
- the prohibited conclusions (ruling 3): CP-6 may state an instrument recommendation and a
  recovery conclusion; peer ranking, buy, sell and switch phrases and trade terms (a price or a
  size) stay prohibited.

`committee_challenge` then composes, in Python, the final bias under CP-6's own `T6` id (r14's
Step 8 has no table) and minimal tables under the r14 CP-6 ids they denote, `T6A.4`, `T6A.6`,
`T6A.7` and `T6A.11` (`methods/cp6.md` records the verified mapping and the decision 0005
adaptation; the `T6E.*` ids are CP-6A Portfolio Debate tables, which CP-6 never writes), the
FP 01 `committee-challenge` table, the CP-6 side of `strengths-weaknesses` keyed by CP-2 row
id, the referenced CP-1 facts, claims and own limitations. The call band reads the settled
final-bias action bias and confidence (`settled_call`, `ACTION_BIAS_FACT`, `CONFIDENCE_FACT`);
final integrity at report assembly is out of scope (ruling 4).
`submit_cp6_step` settles CP-6 as `submit_cp3_step` does and needs no registry entry.
"""

import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from types import MappingProxyType
from typing import Literal, get_args

from pydantic import BaseModel, Field, ValidationError

from deploy_vii import prose
from deploy_vii.business_context import (
    ACTIONS,
    CP1_REFERENCES,
    NONE_STATED,
    Cell,
    Confidence,
    Gap,
    Register,
    Severity,
    prohibited_issues,
    referencable,
    spelled,
)
from deploy_vii.contracts import (
    Claim,
    Contract,
    Fact,
    Hash,
    Input,
    Module,
    ReportTable,
    Run,
    TableColumn,
    TableRow,
    Text,
)
from deploy_vii.cp2_synthesis import CatalogueRow, cp1a_catalogue
from deploy_vii.cp3_relative_value import KIND_LABEL as CP3_KIND_LABEL
from deploy_vii.cp3_relative_value import REQUIRED_TABLES as CP3_REGISTERS
from deploy_vii.cp3_relative_value import cp2_catalogue
from deploy_vii.cp5_integrity import KIND_LABEL as CP5_KIND_LABEL
from deploy_vii.cp5_integrity import SUPPORT_WORD
from deploy_vii.execution import (
    Attempt,
    Execution,
    Qualification,
    StepValidation,
    blocked_ancestors,
    current_inputs,
    inherited_limitations,
    text_sha256,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import shape_issues
from deploy_vii.report_view import figure_unit

MODULE_ID = "CP-6"
STEP_ID = "committee_challenge"
CP6_STEPS = (STEP_ID,)
SCHEMA_VERSION = "committee-challenge/1"
PROMOTED = Qualification(implementation="implemented")
SUBMISSION_INPUT = "committee-submission"
CP0, CP1, CP2, CP3, CP5 = "CP-0", "CP-1", "CP-2", "CP-3", "CP-5"
REQUIRED = (CP0, CP1, CP2, CP3, CP5)
SETTLED = frozenset({"accepted", "restricted"})
# Ruling 1: the optional upstream CP-6 reads in M8 (status and limitations only). CP-2A, CP-2E,
# CP-2D, CP-3C and CP-3D are never read, whatever the run binds.
READ_OPTIONAL: Mapping[str, str] = MappingProxyType({"CP-1A": "business and transaction context"})
NOT_IN_RUN = "not in this run"
INSUFFICIENT = "Insufficient Information"
# The CP-2 rows a challenge may name (T2.7 thesis, strengths, weaknesses; T2.10 key findings).
CHALLENGEABLE = ("T2.7", "T2.10")
# The CP-5 tables a `cp5_refs` id may name: findings, module status, report-level limitations
# and the verdict. A finding may also be named by its `CP-5-FINDING-NNN` id (the T5.9 label).
FINDINGS = "T5.9"
CP5_CITABLE = (FINDINGS, "T5B.6", "T5B.7", "T5B.8")
# CP-5's own words in its verdict-consistency table for a claim no Python finding touches
# (`cp5_integrity._verdict_tables`); any other text there is a Python mark on the claim.
NO_PYTHON_FINDING = "None"
_FINDING_ID = re.compile(r"CP-5-FINDING-[0-9]{3}")
CP4 = "CP-4"
# What CP-5 writes (`cp5_integrity.integrity_review` and `_status_tables`) that CP-6 reads to
# tell CP-4 content from a mere mention: findings that say a module was outside the review,
# the origin of a T5B.7 row restating one of CP-5's own findings, and the T5B.6 result of a
# module CP-5 did not evaluate.
NO_CONTENT_KINDS = frozenset(
    {CP5_KIND_LABEL["blocked_upstream"], CP5_KIND_LABEL["empty_evaluated_set"]}
)
FINDING_ORIGIN = "CP-5 finding"
NOT_EVALUATED_RESULT = "Blocked upstream: not evaluated"
# The CP-2 T2.7 side cell names the Front Page column a challenge sits beside.
THESIS_CHALLENGE = "cp6.thesis_challenge"
STRENGTH_CHALLENGES = "cp6.strength_challenges"
WEAKNESS_CHALLENGES = "cp6.weakness_challenges"
SIDE_TABLE: Mapping[str, str] = MappingProxyType(
    {"Thesis": THESIS_CHALLENGE, "Strength": STRENGTH_CHALLENGES, "Weakness": WEAKNESS_CHALLENGES}
)

# --- the call band (ruling 2) ----------------------------------------------------------------
# Ruling 3: neither docs/frontend-direction-c.md nor report_view.py spells an action bias, so
# the proposed vocabulary stands.

ActionBias = Literal["Overweight", "Neutral", "Underweight", "Insufficient Information"]
ACTION_BIASES: tuple[ActionBias, ...] = get_args(ActionBias)
# Confidence from least to most; the call band's meter runs from 1 to 5 (`CallItem`).
CONFIDENCES: tuple[Confidence, ...] = ("Insufficient Information", "Low", "Medium", "High")
# The final bias (r14 CP-6 Step 8, which has no table): CP-6's own `T6` id, outside r14's A and
# E phase ids, one `final_bias` row. The call band reads these two facts and nothing else.
FINAL_BIAS_TABLE = "T6"
FINAL_BIAS_ROW = "final_bias"
ACTION_BIAS_FACT = f"{FINAL_BIAS_TABLE}.{FINAL_BIAS_ROW}.action_bias"
CONFIDENCE_FACT = f"{FINAL_BIAS_TABLE}.{FINAL_BIAS_ROW}.confidence"


def call_scale(confidence: Confidence) -> int:
    """The call band's meter for a confidence: its rank from 1 (Insufficient Information), with
    High filling the five-step meter (four levels on five steps, so step 4 is unused)."""
    if confidence not in CONFIDENCES:
        raise ValueError(f"Unknown confidence: {confidence}")
    return 5 if confidence == "High" else CONFIDENCES.index(confidence) + 1


CALL_SCALE: Mapping[str, int] = MappingProxyType({c: call_scale(c) for c in CONFIDENCES})


@dataclass(frozen=True)
class CallValues:
    """What the call band reads from a settled CP-6 head."""

    action_bias: ActionBias
    confidence: Confidence

    @property
    def scale(self) -> int:
        return call_scale(self.confidence)


def settled_call(module: Module) -> CallValues:
    """The action bias and confidence of a CP-6 head (its final-bias cells); raises ValueError
    when the head is not CP-6's or carries no settled pair."""
    if module.module_id != MODULE_ID:
        raise ValueError(f"{module.module_id} is not a CP-6 head")
    facts = {fact.fact_id: fact for fact in module.facts}
    bias, confidence = facts.get(ACTION_BIAS_FACT), facts.get(CONFIDENCE_FACT)
    if (
        bias is None
        or confidence is None
        or bias.text not in ACTION_BIASES
        or confidence.text not in CONFIDENCES
    ):
        raise ValueError("The CP-6 head carries no settled action bias and confidence")
    return CallValues(bias.text, confidence.text)


# --- prohibited conclusions (ruling 3) -------------------------------------------------------

CP6_PROHIBITED_KINDS = ("peer ranking",)
# CP-3's action phrases less the lifted vocabulary: overweight and underweight are the action
# bias itself, and recommend* is the instrument recommendation CP-6 states.
LIFTED_ACTIONS = frozenset({"overweight", "underweight"}) | {
    phrase for phrase in ACTIONS["instrument action"] if phrase.startswith("recommend")
}
CP6_ACTIONS = tuple(p for p in ACTIONS["instrument action"] if p not in LIFTED_ACTIONS)
# The model never names a buy or sell price or a size (figures are rejected as bare figures;
# these are the words).
TRADE_TERMS = (
    "target price",
    "price target",
    "entry price",
    "exit price",
    "entry level",
    "exit level",
    "position size",
    "position sizing",
    "sized at",
    "size the position",
)
_CP6_PHRASES = tuple(
    (kind, phrase, re.compile(rf"(?<![A-Za-z]){re.escape(phrase)}(?![A-Za-z])", re.IGNORECASE))
    for kind, phrases in (("instrument action", CP6_ACTIONS), ("trade terms", TRADE_TERMS))
    for phrase in phrases
)


def cp6_prohibited_issues(path: str, text: str) -> tuple[str, ...]:
    """A text that states a conclusion CP-6 may not: a peer ranking
    (`business_context.prohibited_issues`), a buy, sell or switch phrase or a trade term. A
    guard over phrases, not a semantic review."""
    return (
        *prohibited_issues(path, text, kinds=CP6_PROHIBITED_KINDS),
        *(
            f'{path}: prohibited conclusion ({kind}): "{phrase}"'
            for kind, phrase, pattern in _CP6_PHRASES
            if pattern.search(text)
        ),
    )


# --- the model-facing contract ---------------------------------------------------------------
# Plain `str` fields and `Literal` enums, as CP-2 and CP-3: the validator, not the sent schema,
# holds the references and the text.


class Basis(Contract):
    """A row's basis: CP-2, CP-3 and CP-5 rows by id; its CP-1 basis is the figure references
    in its text."""

    cp2_refs: tuple[str, ...]
    cp3_refs: tuple[str, ...]
    cp5_refs: tuple[str, ...]


class Recommendation(Contract):
    action_bias: ActionBias
    rationale: str
    conditions: str
    confidence: Confidence
    limitation: str | None
    basis: Basis


class ThesisChallenge(Contract):
    thesis_ref: str  # a CP-2 T2.7 or T2.10 row id, `<table_id>.<row_id>`
    counter_case: str
    evidence_for: str
    evidence_against: str
    would_change_view: str
    basis: Basis


class RecoveryView(Contract):
    subject: str
    view: str
    confidence: Confidence
    limitation: str | None
    basis: Basis


class Risk(Contract):
    risk: str
    mechanic: str
    implication: str
    severity: Severity
    basis: Basis


class CommitteeSubmission(Contract):
    """What the model returns for `committee_challenge`; every field is required."""

    recommendation: Recommendation
    # `minItems: 1` in the sent schema only, as CP-2's `key_findings`; empty composes as a gap.
    thesis_challenges: tuple[ThesisChallenge, ...] = Field(json_schema_extra={"minItems": 1})
    recovery_view: tuple[RecoveryView, ...]
    risks: tuple[Risk, ...]
    gaps: tuple[Gap, ...]


class CommitteeReport(Contract):
    schema_version: Literal["committee-challenge/1"] = "committee-challenge/1"
    run: Run
    pack_sha256: Hash
    submission_sha256: Hash
    tables: tuple[ReportTable, ...]
    facts: tuple[Fact, ...]
    claims: tuple[Claim, ...]
    limitations: tuple[Text, ...]


# --- the upstream heads a step binds ---------------------------------------------------------


def _catalogue(head: Module, tables: Sequence[str]) -> dict[str, CatalogueRow]:
    """The citable rows of `head`'s `tables`, by the CP-1A catalogue rule (`cp1a_catalogue`)."""
    table_of = {f"{t.table_id}.{r.row_id}": t.table_id for t in head.tables for r in t.rows}
    return {ref: row for ref, row in cp1a_catalogue(head).items() if table_of[ref] in tables}


def cp3_catalogue(cp3: Module) -> dict[str, CatalogueRow]:
    """The CP-3 rows a `cp3_refs` id may name: its T3.1, T3.3, T3.4, T3.9 and T3.10 rows that
    settle a cell. The Front Page copy and `cp1_references` are not citable."""
    return _catalogue(cp3, CP3_REGISTERS)


def cp5_catalogue(cp5: Module) -> dict[str, CatalogueRow]:
    """The CP-5 rows a `cp5_refs` id may name (`CP5_CITABLE`)."""
    return _catalogue(cp5, CP5_CITABLE)


@dataclass(frozen=True)
class Cp5Finding:
    finding_id: str  # CP-5-FINDING-NNN, the T5.9 row label
    ref: str  # T5.9.<row_id>
    kind: str
    where: str
    detail: str


@dataclass(frozen=True)
class Cp5Review:
    """What CP-6 reads from a CP-5 head, from its Python-written registers only.

    `flagged` holds each (module, claim id) CP-5 does not hold supported: a verdict other than
    Supported or a Python mark (T5B.4), or a party to a contradiction (T5B.3). `cp4_rows` are
    the rows that carry CP-4 content (`cp4_rows`). `unreadable` lists claim names that do not
    read as `<module> <claim id>`."""

    findings: tuple[Cp5Finding, ...]
    flagged: frozenset[tuple[str, str]]
    unsupported: int
    contradictions: int
    cp4_rows: frozenset[str]
    verdict: Mapping[str, str]
    unreadable: tuple[str, ...]


def _register_rows(head: Module, table_id: str) -> list[tuple[TableRow, dict[str, Fact]]]:
    """The rows of one register that settle a cell, each with its cells by column field."""
    facts = {fact.fact_id: fact for fact in head.facts}
    table = next((t for t in head.tables if t.table_id == table_id), None)
    if table is None:
        return []
    found: list[tuple[TableRow, dict[str, Fact]]] = []
    for row in table.rows:
        cells = {c.field: facts[i] for c, i in zip(table.columns, row.fact_ids, strict=True)}
        if any(cell.status == "known" for cell in cells.values()):
            found.append((row, cells))
    return found


def _said(cells: Mapping[str, Fact], field: str) -> str:
    cell = cells.get(field)
    return cell.text or "" if cell is not None else ""


def _where_modules(where: str) -> tuple[str, ...]:
    """The modules a T5.9 Where cell names (`cp5_integrity.Finding.where`): `<module> claim|fact
    <id>`, `<subject> (<module>, ...)` for a figure mismatch, `<module> <claim>; ...` for a
    contradiction."""
    if where.endswith(")") and " (" in where:
        return tuple(where[where.rindex(" (") + 2 : -1].split(", "))
    return tuple(part.split(" ")[0] for part in where.split("; "))


def cp4_rows(
    cp5: Module, findings: Sequence[Cp5Finding], verdict: Mapping[str, str]
) -> frozenset[str]:
    """The CP-5 rows that carry CP-4 content (fix round 1, ruling 6): a finding about CP-4's own
    claims, facts or figures, and the T5B.7 row restating such a finding. None unless CP-5
    evaluated CP-4 (its T5B.8 evaluated set, not its not-evaluated list, and no T5B.6 Blocked
    upstream result); a Blocked upstream finding, an inherited limitation and a gap row never
    carry CP-4 content."""
    evaluated = verdict.get("evaluated", "").split(", ")
    outside = verdict.get("not_evaluated", "").split(", ")
    results = {row.label: _said(cells, "result") for row, cells in _register_rows(cp5, "T5B.6")}
    if CP4 not in evaluated or CP4 in outside or results.get(CP4) == NOT_EVALUATED_RESULT:
        return frozenset()
    carrying = {
        f.finding_id: f.ref
        for f in findings
        if f.kind not in NO_CONTENT_KINDS and CP4 in _where_modules(f.where)
    }
    restated = {
        f"T5B.7.{row.row_id}"
        for row, cells in _register_rows(cp5, "T5B.7")
        if _said(cells, "origin") == FINDING_ORIGIN
        and _said(cells, "limitation").partition(" ")[0] in carrying
    }
    return frozenset({*carrying.values(), *restated})


def cp5_review(cp5: Module) -> Cp5Review:
    """Read a CP-5 head's findings, flagged claims, CP-4 rows and verdict."""
    findings = tuple(
        Cp5Finding(
            finding_id=row.label,
            ref=f"{FINDINGS}.{row.row_id}",
            kind=_said(cells, "kind"),
            where=_said(cells, "where"),
            detail=_said(cells, "detail"),
        )
        for row, cells in _register_rows(cp5, FINDINGS)
        if _FINDING_ID.fullmatch(row.label)
    )
    names = [
        row.label
        for row, cells in _register_rows(cp5, "T5B.4")
        if _said(cells, "support") != SUPPORT_WORD["supported"]
        or _said(cells, "python_findings") != NO_PYTHON_FINDING
    ]
    contradictions = _register_rows(cp5, "T5B.3")
    names += [part for _, cells in contradictions for part in _said(cells, "claims").split("; ")]
    flagged: set[tuple[str, str]] = set()
    unreadable: list[str] = []
    for name in names:
        module_id, _, claim_id = name.partition(" ")
        if not module_id or not claim_id or " " in claim_id:
            unreadable.append(name)
        else:
            flagged.add((module_id, claim_id))
    verdict = {row.row_id: _said(cells, "value") for row, cells in _register_rows(cp5, "T5B.8")}
    return Cp5Review(
        findings=findings,
        flagged=frozenset(flagged),
        unsupported=len(_register_rows(cp5, "T5B.2")),
        contradictions=len(contradictions),
        cp4_rows=cp4_rows(cp5, findings, verdict),
        verdict=MappingProxyType(verdict),
        unreadable=tuple(dict.fromkeys(unreadable)),
    )


@dataclass(frozen=True)
class Upstream:
    """What one CP-6 attempt binds, read once from the journal (`cp6_upstream`).

    `bound` is the attempt's input set; `current` is `execution.current_inputs` now, or its
    refusal text; `cp0` to `cp5` are the bound required heads; `optional` holds the bound head
    of `READ_OPTIONAL` (a blocked one is its limitations only); `blocked` is
    `execution.blocked_ancestors` over the bound inputs; `inherited` is what settlement will
    carry from them (`execution.inherited_limitations`)."""

    bound: tuple[Input, ...]
    current: tuple[Input, ...] | str
    cp0: Module
    cp1: Module
    cp2: Module
    cp3: Module
    cp5: Module
    optional: Mapping[str, Module]
    blocked: frozenset[str]
    inherited: tuple[str, ...]

    def status(self, module_id: str) -> str | None:
        return next((item.status for item in self.bound if item.input_id == module_id), None)

    def optional_status(self, module_id: str) -> str:
        """A read optional upstream's bound status, or `NOT_IN_RUN`."""
        return self.status(module_id) or NOT_IN_RUN

    @cached_property
    def cp2_rows(self) -> dict[str, CatalogueRow]:
        return cp2_catalogue(self.cp2)

    @cached_property
    def cp3_rows(self) -> dict[str, CatalogueRow]:
        return cp3_catalogue(self.cp3)

    @cached_property
    def cp5_rows(self) -> dict[str, CatalogueRow]:
        return cp5_catalogue(self.cp5)

    @cached_property
    def review(self) -> Cp5Review:
        return cp5_review(self.cp5)

    @cached_property
    def challengeable(self) -> frozenset[str]:
        rows = {
            f"{t.table_id}.{r.row_id}"
            for t in self.cp2.tables
            if t.table_id in CHALLENGEABLE
            for r in t.rows
        }
        return frozenset(rows & self.cp2_rows.keys())

    def cp5_ref(self, ref: str) -> str | None:
        """The CP-5 catalogue row a `cp5_refs` id names (a finding id names its T5.9 row)."""
        if ref in self.cp5_rows:
            return ref
        found = next((f.ref for f in self.review.findings if f.finding_id == ref), None)
        return found if found in self.cp5_rows else None

    @cached_property
    def claim_rows(self) -> frozenset[tuple[str, str]]:
        """The CP-2 and CP-3 rows that bear a claim (T2.1.assessment, T2.10.kfNN, T3.4.preference,
        T3.1.iNN with a market observation): the only rows CP-5 reviews, so the only rows that
        can support a call (fix round 1, ruling 3). Gap and limitation rows never do."""
        return frozenset(
            (head.module_id, claim.claim_id)
            for head, rows in ((self.cp2, self.cp2_rows), (self.cp3, self.cp3_rows))
            for claim in head.claims
            if claim.claim_id in rows
        )

    @property
    def cp4_evidence(self) -> frozenset[str]:
        """The CP-5 rows carrying CP-4 content (`Cp5Review.cp4_rows`); none while CP-4 is
        blocked up CP-6's own input chain."""
        return frozenset() if CP4 in self.blocked_upstream else self.review.cp4_rows

    @property
    def blocked_upstream(self) -> tuple[str, ...]:
        """Every blocked module up the bound input chain, bound ones included."""
        bound = {item.input_id for item in self.bound if item.status == "blocked"}
        return tuple(sorted(self.blocked | bound))

    @property
    def caps(self) -> tuple[str, ...]:
        """Why the confidence is below High whatever the evidence (decision 0007, ruling 1): a
        blocked ancestor, a CP-5 handoff that is not accepted, and CP-5's unsupported claims
        and contradictions. An optional upstream the run does not select is silent."""
        reasons = [f"{module_id} is blocked upstream" for module_id in self.blocked_upstream]
        return (*reasons, *self.cp5_caps)

    @property
    def cp5_caps(self) -> tuple[str, ...]:
        """The CP-5 reasons among `caps`; each comes with an own limitation (`limits`)."""
        reasons: list[str] = []
        if self.status(CP5) != "accepted":
            reasons.append(f"CP-5 is {self.status(CP5) or 'absent'}")
        if self.review.unsupported:
            reasons.append(
                f"CP-5 marks {self.review.unsupported} claims unsupported or partly supported"
            )
        if self.review.contradictions:
            reasons.append(f"CP-5 records {self.review.contradictions} contradictions")
        return tuple(reasons)

    @property
    def insufficient(self) -> tuple[str, ...]:
        """Why the action bias is Insufficient Information whatever the judgment: CP-3 records
        no observed or indicative market evidence, or its preference is not assessed."""
        evidence = {CP3_KIND_LABEL["observed"], CP3_KIND_LABEL["indicative_talk"]}
        facts = {fact.fact_id: fact for fact in self.cp3.facts}
        kinds = {
            fact.text
            for fact in self.cp3.facts
            if fact.table_id == "T3.3" and fact.field == "kind" and fact.status == "known"
        }
        reasons: list[str] = []
        if not kinds & evidence:
            reasons.append("CP-3 records no observed or indicative market evidence")
        preference = facts.get("T3.4.preference.confidence")
        if preference is None or preference.status != "known":
            reasons.append("CP-3 records no preference")
        elif preference.text == INSUFFICIENT:
            reasons.append("CP-3's preference is Insufficient Information")
        return tuple(reasons)

    @property
    def limits(self) -> tuple[str, ...]:
        """CP-6's own limitations from its upstream: each blocked ancestor (a blocked read
        optional one in the decision 0007 wording) and every CP-5 cap. An optional
        upstream the run does not select records none: `current_inputs` refuses a selected one
        that is unrun or stale, so blocked is the only missing state a bound attempt shows."""
        texts = [
            f"Optional upstream {m} blocked: CP-6 reads no {READ_OPTIONAL[m]}"
            if m in READ_OPTIONAL
            else f"Blocked upstream {m}: its outputs are outside CP-6's evidence"
            for m in self.blocked_upstream
        ]
        if self.cp5_caps:
            ids = [finding.finding_id for finding in self.review.findings]
            found = f"; findings {', '.join(ids)}" if ids else ""
            texts.append(
                f"CP-5 handoff caps the confidence below High: {'; '.join(self.cp5_caps)}{found}"
            )
        return tuple(texts)


def _bound_module(store: Execution, attempt: Attempt, module_id: str) -> Module:
    item = next((i for i in attempt.inputs if i.input_id == module_id), None)
    if item is None:
        raise ValueError(f"The CP-6 attempt binds no {module_id} input")
    return store.result(item.sha256)


def cp6_upstream(store: Execution, attempt: Attempt) -> Upstream:
    """The bound required heads of `attempt`, its bound CP-1A head (when the run selects it),
    the current input set, the blocked ancestors and the inherited limitations. A refusal of
    `current_inputs` is kept as text: the validator reports it as a staleness issue."""
    snapshot = store.read()
    current: tuple[Input, ...] | str
    try:
        current = current_inputs(snapshot, MODULE_ID)
    except ValueError as error:  # NotAuthorized included: reported, never passed as current
        current = str(error)
    bound = {item.input_id for item in attempt.inputs}
    return Upstream(
        bound=attempt.inputs,
        current=current,
        cp0=_bound_module(store, attempt, CP0),
        cp1=_bound_module(store, attempt, CP1),
        cp2=_bound_module(store, attempt, CP2),
        cp3=_bound_module(store, attempt, CP3),
        cp5=_bound_module(store, attempt, CP5),
        optional={
            module_id: _bound_module(store, attempt, module_id)
            for module_id in READ_OPTIONAL
            if module_id in bound
        },
        blocked=blocked_ancestors(snapshot, attempt.inputs),
        inherited=inherited_limitations(snapshot, attempt, (), store.head_module),
    )


# --- validation ------------------------------------------------------------------------------

_TEXT = (str, str | None)
_NOT_PROSE = frozenset({"thesis_ref"})
SubmissionRow = Recommendation | ThesisChallenge | RecoveryView | Risk | Gap


def _rows(submission: CommitteeSubmission) -> Iterator[tuple[str, SubmissionRow]]:
    yield "recommendation", submission.recommendation
    for name in ("thesis_challenges", "recovery_view", "risks", "gaps"):
        for index, row in enumerate(getattr(submission, name)):
            yield f"{name}[{index}]", row


def _texts(row: BaseModel) -> Iterator[tuple[str, str]]:
    """(field, value) of each prose field of one row; ids, enums and the basis excluded."""
    for name, info in type(row).model_fields.items():
        value = getattr(row, name)
        if name not in _NOT_PROSE and info.annotation in _TEXT and value is not None:
            yield name, value


def _figures(row: BaseModel, bound: Mapping[str, Fact]) -> list[Fact]:
    """The CP-1 facts the row's text names by figure reference, in reading order. A malformed
    text names none here; `prose.issues` reports it."""
    found: list[Fact] = []
    for _, text in _texts(row):
        try:
            runs = prose.tokenize(text)
        except ValueError:
            continue
        found += [bound[r.text] for r in runs if r.kind == "ref" and r.figure and r.text in bound]
    return list({fact.fact_id: fact for fact in found}.values())


def _stale_issues(upstream: Upstream) -> list[str]:
    if isinstance(upstream.current, str):
        return [f"Stale inputs: {upstream.current}"]
    bound = {item.input_id: item for item in upstream.bound}
    current = {item.input_id: item for item in upstream.current}

    def state(item: Input | None) -> str:
        return "absent" if item is None else f"{item.status} {item.sha256[:12]}"

    return [
        f"Stale input {key}: bound {state(bound.get(key))}, current {state(current.get(key))}"
        for key in dict.fromkeys((*bound, *current))
        if bound.get(key) != current.get(key)
    ]


def _provenance_issues(upstream: Upstream) -> list[str]:
    """The supplied modules are the bound heads (same module, same canonical hash); a bound
    read optional upstream is supplied and none is supplied unbound; every required upstream is
    accepted or restricted (decision 0007)."""
    supplied: dict[str, Module | None] = {
        CP0: upstream.cp0,
        CP1: upstream.cp1,
        CP2: upstream.cp2,
        CP3: upstream.cp3,
        CP5: upstream.cp5,
    }
    bound = {item.input_id: item for item in upstream.bound}
    for module_id in READ_OPTIONAL:
        if module_id in bound or module_id in upstream.optional:
            supplied[module_id] = upstream.optional.get(module_id)
    issues: list[str] = []
    for module_id, module in supplied.items():
        item = bound.get(module_id)
        if (
            item is None
            or module is None
            or module.module_id != module_id
            or module.content_hash() != item.sha256
        ):
            issues.append(f"Upstream {module_id}: the supplied module is not the bound input")
    for item in upstream.bound:
        if item.input_id in REQUIRED and item.status not in SETTLED:
            handoff = (
                ": its handoff is neither Passed nor Restricted" if item.input_id == CP5 else ""
            )
            issues.append(f"Required upstream {item.input_id} is {item.status}{handoff}")
    issues.extend(f"CP-5 head: unreadable claim name {name}" for name in upstream.review.unreadable)
    return issues


def _basis_issues(path: str, basis: Basis, upstream: Upstream) -> list[str]:
    issues = [
        f"{path}.basis.cp2_refs: unknown CP-2 row {ref}"
        for ref in basis.cp2_refs
        if ref not in upstream.cp2_rows
    ]
    issues += [
        f"{path}.basis.cp3_refs: unknown CP-3 row {ref}"
        for ref in basis.cp3_refs
        if ref not in upstream.cp3_rows
    ]
    issues += [
        f"{path}.basis.cp5_refs: unknown CP-5 row or finding {ref}"
        for ref in basis.cp5_refs
        if upstream.cp5_ref(ref) is None
    ]
    return issues


def _cites(
    row: Recommendation | ThesisChallenge | RecoveryView | Risk, bound: Mapping[str, Fact]
) -> bool:
    b = row.basis
    return bool(b.cp2_refs or b.cp3_refs or b.cp5_refs or _figures(row, bound))


def _reference_issues(
    submission: CommitteeSubmission, upstream: Upstream, bound: Mapping[str, Fact]
) -> list[str]:
    """Reference existence, the challenge targets and the one-ref rule on every row (an
    Insufficient Information recovery view records a gap and needs none)."""
    issues: list[str] = []
    counts = Counter(row.thesis_ref for row in submission.thesis_challenges)
    issues += [
        f"thesis_challenges: {ref} is challenged more than once"
        for ref, count in counts.items()
        if count > 1
    ]
    for index, challenge in enumerate(submission.thesis_challenges):
        if challenge.thesis_ref not in upstream.challengeable:
            issues.append(
                f"thesis_challenges[{index}].thesis_ref: {challenge.thesis_ref} is not a CP-2 "
                "thesis, strength, weakness or key finding row"
            )
    for path, row in _rows(submission):
        if isinstance(row, Gap):
            continue
        issues += _basis_issues(path, row.basis, upstream)
        exempt = isinstance(row, RecoveryView) and row.confidence == INSUFFICIENT
        if not exempt and not _cites(row, bound):
            issues.append(f"{path}: a row cites a CP-2, CP-3 or CP-5 row or a CP-1 figure")
    return issues


def _recommendation_issues(
    submission: CommitteeSubmission, upstream: Upstream, bound: Mapping[str, Fact]
) -> list[str]:
    """The recommendation boundary and gap propagation (decision 0007, rulings 1 and 6)."""
    row = submission.recommendation
    issues: list[str] = []
    insufficient = row.action_bias == INSUFFICIENT
    if insufficient != (row.confidence == INSUFFICIENT):
        issues.append(
            "recommendation: action_bias and confidence are Insufficient Information together"
        )
    if insufficient and not row.limitation:
        issues.append(
            "recommendation: an Insufficient Information action bias states its limitation"
        )
    if (forced := upstream.insufficient) and not insufficient:
        issues.append(
            f"recommendation.action_bias: Insufficient Information because {'; '.join(forced)}"
        )
    if upstream.caps and row.confidence == "High":
        issues.append(
            f"recommendation.confidence: capped below High because {'; '.join(upstream.caps)}"
        )
    if not insufficient:
        cited = [(CP2, r) for r in row.basis.cp2_refs] + [(CP3, r) for r in row.basis.cp3_refs]
        support = [key for key in dict.fromkeys(cited) if key in upstream.claim_rows]
        unflagged = [key for key in support if key not in upstream.review.flagged]
        # A figure supports the call only where the call is argued: its limitation is not.
        argued = row.model_copy(update={"limitation": None})
        if not unflagged and not _figures(argued, bound):
            if support:
                named = ", ".join(f"{m} {r}" for m, r in support)
                issues.append(f"recommendation.basis: rests only on CP-5-flagged claims ({named})")
            else:
                issues.append(
                    "recommendation.basis: cites no CP-2 or CP-3 claim row or CP-1 figure CP-5 "
                    "leaves unflagged"
                )
    for index, view in enumerate(submission.recovery_view):
        path = f"recovery_view[{index}]"
        if view.confidence == INSUFFICIENT:
            if not view.limitation:
                issues.append(
                    f"{path}: an Insufficient Information recovery view states its limitation"
                )
            continue
        if not any(upstream.cp5_ref(r) in upstream.cp4_evidence for r in view.basis.cp5_refs):
            issues.append(
                f"{path}: a recovery view that is not Insufficient Information cites a CP-5 "
                "finding or limitation carrying CP-4 evidence"
            )
        if upstream.caps and view.confidence == "High":
            issues.append(
                f"{path}.confidence: capped below High because {'; '.join(upstream.caps)}"
            )
    return issues


def _text_issues(
    submission: CommitteeSubmission, bound: Mapping[str, Fact], names: tuple[str, ...]
) -> list[str]:
    issues: list[str] = []
    for path, row in _rows(submission):
        for name, text in _texts(row):
            where = f"{path}.{name}"
            if not text.strip():
                issues.append(f"{where}: empty text")
                continue
            issues.extend(f"{where}: {issue}" for issue in prose.issues(text, bound, names=names))
            issues.extend(cp6_prohibited_issues(where, text))
    return issues


def validate_committee(
    pack: PreparedPack, submission: CommitteeSubmission, upstream: Upstream
) -> tuple[str, ...]:
    """Every issue of `submission` over the bound `upstream`, in a stable order; empty when it
    composes."""
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        submission = CommitteeSubmission.model_validate_json(submission.model_dump_json())
    except ValidationError as error:
        return shape_issues(error)
    bound = prose.bind(referencable(upstream.cp1.facts))
    issues = [*_stale_issues(upstream), *_provenance_issues(upstream)]
    issues += _reference_issues(submission, upstream, bound)
    issues += _recommendation_issues(submission, upstream, bound)
    issues += _text_issues(submission, bound, (pack.run.issuer_name,))
    return tuple(dict.fromkeys(issues))


# --- composition -----------------------------------------------------------------------------

NO_BASIS = "No CP-2, CP-3 or CP-5 row or CP-1 figure cited"
FINAL_BIAS = Register(
    FINAL_BIAS_TABLE,
    "Final bias",
    (
        ("action_bias", "Action bias"),
        ("rationale", "Rationale"),
        ("conditions", "Conditions"),
        ("confidence", "Confidence"),
        ("basis", "Basis"),
        ("limitation", "Limitation"),
    ),
)
# Ruling 5 and task CP6-R: minimal tables under the r14 CP-6 ids they denote (verified against
# the pinned r14 source, `methods/cp6.md`), titled by r14's table names; every column is composed
# from the contract rows, not from r14 column definitions (decision 0005).
CROSS_EXAMINATION, EVIDENCE_WEIGHTING, RESOLUTION, GAPS = "T6A.4", "T6A.6", "T6A.7", "T6A.11"
REGISTERS: Mapping[str, Register] = {
    item.table_id: item
    for item in (
        Register(
            CROSS_EXAMINATION,
            "Bear cross-examination",
            (
                ("thesis_ref", "CP-2 row"),
                ("counter_case", "Counter-case"),
                ("evidence_for", "Evidence for"),
                ("evidence_against", "Evidence against"),
                ("would_change_view", "What would change the view"),
                ("basis", "Basis"),
            ),
        ),
        Register(
            EVIDENCE_WEIGHTING,
            "Chair evidence weighting: recovery view",
            (
                ("subject", "Subject"),
                ("view", "View"),
                ("confidence", "Confidence"),
                ("basis", "Basis"),
                ("limitation", "Limitation"),
            ),
        ),
        Register(
            RESOLUTION,
            "Debate resolution matrix: committee risks",
            (
                ("risk", "Risk"),
                ("mechanic", "Risk mechanic"),
                ("implication", "Credit implication"),
                ("severity", "Severity"),
                ("basis", "Basis"),
            ),
        ),
        Register(
            GAPS,
            "Gaps ledger",
            (
                ("gap_id", "Gap ID"),
                ("gap", "Gap"),
                ("why_it_matters", "Why it matters"),
                ("affected_analysis", "Affected analysis"),
                ("severity", "Severity"),
                ("action", "Action"),
            ),
        ),
    )
}
# The r14 CP-6 ids CP-6 composes; the final bias is CP-6's own table, outside r14's ids.
REQUIRED_TABLES = tuple(REGISTERS)
# What each table holds, in the words an empty table's limitation uses: unchanged by the r14 id
# remap, which renamed the titles and not the analysis.
HOLDS: Mapping[str, str] = MappingProxyType(
    {
        FINAL_BIAS_TABLE: "action bias",
        CROSS_EXAMINATION: "committee challenges",
        EVIDENCE_WEIGHTING: "recovery view",
        RESOLUTION: "committee risks",
        GAPS: "gaps ledger",
    }
)
# The FP 01 `committee-challenge` table: one model text per line, the action bias first (the
# collapsed block's summary), then each challenge, its CP-2 row's name leading the text.
COMMITTEE_CHALLENGE = "cp6.committee_challenge"
FRONT_TITLES: Mapping[str, str] = MappingProxyType(
    {
        COMMITTEE_CHALLENGE: "Committee challenge",
        THESIS_CHALLENGE: "Thesis challenge",
        STRENGTH_CHALLENGES: "Strength challenges",
        WEAKNESS_CHALLENGES: "Weakness challenges",
    }
)


@dataclass(frozen=True)
class _Row:
    row_id: str
    label: str
    cells: Sequence[Cell]


class _Composer:
    """Writes the tables: cells from validated rows, figures spelled by Python."""

    def __init__(self, upstream: Upstream) -> None:
        self.upstream = upstream
        self.bound = prose.bind(referencable(upstream.cp1.facts))
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

    def said(self, value: str) -> Cell:
        return Cell(self.text(value), judged=True)

    def limit(self, limitation: str | None) -> Cell:
        return Cell(self.text(limitation) if limitation else NONE_STATED)

    def basis(self, row: Recommendation | ThesisChallenge | RecoveryView | Risk) -> Cell:
        """Python's basis cell: the cited CP-2, CP-3 and CP-5 rows, each in catalogue
        (register) order with its label whatever order the model listed them in (a finding id
        names its T5.9 row), then each CP-1 figure in reading order."""
        up, b = self.upstream, row.basis
        cp5 = {up.cp5_ref(ref) for ref in b.cp5_refs}
        parts = [
            f"{module_id} {ref} ({item.label})"
            for module_id, rows, cited in (
                (CP2, up.cp2_rows, set(b.cp2_refs)),
                (CP3, up.cp3_rows, set(b.cp3_refs)),
                (CP5, up.cp5_rows, cp5),
            )
            for ref, item in rows.items()
            if ref in cited
        ]
        parts += [
            f"CP-1 {fact.label} · {fact.period}" if fact.period else f"CP-1 {fact.label}"
            for fact in _figures(row, self.bound)
        ]
        return Cell("; ".join(parts) or NO_BASIS)

    def _fact(self, table_id: str, row_id: str, field: str, label: str, cell: Cell) -> str:
        fact_id = f"{table_id}.{row_id}.{field}"
        self.facts.append(
            Fact(
                fact_id=fact_id,
                label=label,
                table_id=table_id,
                row_id=row_id,
                field=field,
                text=cell.text,
                status="known" if cell.text is not None else cell.status,
                value_class="analyst_judgment" if cell.judged else None,
                limitation=cell.reason if cell.text is None else None,
            )
        )
        return fact_id

    def _empty(self, holds: str, required: bool) -> Cell:
        if required:
            reason = f"No {holds} rows in the CP-6 submission"
            self.limitations.append(reason)
            return Cell(None, reason=reason, status="missing")
        return Cell(None, reason=f"None in the CP-6 submission ({holds})", status="not_applicable")

    def table(self, register: Register, rows: Sequence[_Row], *, required: bool) -> None:
        if not rows:
            cell = self._empty(HOLDS[register.table_id], required)
            rows = (_Row("none", "None", tuple(cell for _ in register.columns)),)
        self.tables.append(
            ReportTable(
                table_id=register.table_id,
                title=register.title,
                columns=tuple(TableColumn(field=f, label=label) for f, label in register.columns),
                rows=tuple(
                    TableRow(
                        row_id=row.row_id,
                        label=row.label,
                        fact_ids=tuple(
                            self._fact(register.table_id, row.row_id, field, label, cell)
                            for (field, label), cell in zip(
                                register.columns, row.cells, strict=True
                            )
                        ),
                    )
                    for row in rows
                ),
                row_header="Item",
            )
        )

    def front(self, table_id: str, lines: Sequence[tuple[str, str, Cell]]) -> None:
        """A Front Page table: one `value` fact per line, labelled as the block shows it. A
        challenge column with no line is not composed: nothing is invented beside a CP-2 row
        CP-6 does not challenge."""
        if not lines:
            return
        title = FRONT_TITLES[table_id]
        self.tables.append(
            ReportTable(
                table_id=table_id,
                title=title,
                columns=(TableColumn(field="value", label="Value"),),
                rows=tuple(
                    TableRow(
                        row_id=row_id,
                        label=label,
                        fact_ids=(self._fact(table_id, row_id, "value", label, cell),),
                    )
                    for row_id, label, cell in lines
                ),
                row_header=title,
            )
        )


def _name(row: CatalogueRow) -> str:
    """How a CP-2 row is named: a point's own label (T2.7), else its row label."""
    return dict(row.cells).get("label") or row.label


def _recommendation(submission: CommitteeSubmission, out: _Composer) -> Cell:
    """The final bias (`T6`) and the FP 01 action-bias line."""
    row = submission.recommendation
    rationale, conditions = out.text(row.rationale), out.text(row.conditions)
    out.table(
        FINAL_BIAS,
        [
            _Row(
                FINAL_BIAS_ROW,
                "Recommendation",
                (
                    Cell(row.action_bias),
                    Cell(rationale, judged=True),
                    Cell(conditions, judged=True),
                    Cell(row.confidence),
                    out.basis(row),
                    out.limit(row.limitation),
                ),
            )
        ],
        required=True,
    )
    if row.action_bias == INSUFFICIENT:
        why = out.text(row.limitation or "")
        out.limitations.append(f"Action bias is Insufficient Information: {why}")
    return Cell(
        f"Action bias: {row.action_bias} (confidence {row.confidence}). {rationale} "
        f"Conditions: {conditions}",
        judged=True,
    )


def _ordered(submission: CommitteeSubmission, upstream: Upstream) -> list[ThesisChallenge]:
    """The challenges in CP-2 catalogue order (each CP-2 row is challenged once), so the
    composition does not depend on the order the model listed them in."""
    order = {ref: index for index, ref in enumerate(upstream.cp2_rows)}
    return sorted(submission.thesis_challenges, key=lambda c: order[c.thesis_ref])


def _challenges(
    challenges: Sequence[ThesisChallenge], out: _Composer
) -> list[tuple[str, str, Cell]]:
    """T6A.4 and the challenge columns beside CP-2's strengths and weaknesses, keyed by the
    CP-2 row id; returns the FP 01 challenge lines."""
    rows: list[_Row] = []
    lines: list[tuple[str, str, Cell]] = []
    columns: dict[str, list[tuple[str, str, Cell]]] = {table: [] for table in FRONT_TITLES}
    for index, challenge in enumerate(challenges, 1):
        ref = challenge.thesis_ref
        target = out.upstream.cp2_rows[ref]
        row_id, name = f"c{index:02d}", _name(target)
        counter, change = out.text(challenge.counter_case), out.text(challenge.would_change_view)
        rows.append(
            _Row(
                row_id,
                name,
                (
                    Cell(f"CP-2 {ref} ({target.label})"),
                    Cell(counter, judged=True),
                    out.said(challenge.evidence_for),
                    out.said(challenge.evidence_against),
                    Cell(change, judged=True),
                    out.basis(challenge),
                ),
            )
        )
        lines.append(
            (row_id, name, Cell(f"{name}: {counter} Would change the view: {change}", judged=True))
        )
        side = SIDE_TABLE.get(dict(target.cells).get("side", ""))
        if side is not None:
            cp2_row = ref.removeprefix("T2.7.")
            columns[side].append((cp2_row, f"Challenge · {name}", Cell(counter, judged=True)))
    out.table(REGISTERS[CROSS_EXAMINATION], rows, required=True)
    for table_id in (THESIS_CHALLENGE, STRENGTH_CHALLENGES, WEAKNESS_CHALLENGES):
        out.front(table_id, columns[table_id])
    return lines


def _recovery(submission: CommitteeSubmission, out: _Composer) -> None:
    rows: list[_Row] = []
    for index, view in enumerate(submission.recovery_view, 1):
        text = out.text(view.view)
        if view.confidence == INSUFFICIENT:
            why = out.text(view.limitation or "")
            out.limitations.append(f"Recovery view is Insufficient Information: {why}")
        rows.append(
            _Row(
                f"v{index:02d}",
                f"Recovery view {index}",
                (
                    out.said(view.subject),
                    Cell(text, judged=True),
                    Cell(view.confidence),
                    out.basis(view),
                    out.limit(view.limitation),
                ),
            )
        )
    out.table(REGISTERS[EVIDENCE_WEIGHTING], rows, required=True)


def _risks_and_gaps(submission: CommitteeSubmission, out: _Composer) -> None:
    out.table(
        REGISTERS[RESOLUTION],
        [
            _Row(
                f"r{index:02d}",
                f"Risk {index}",
                (
                    out.said(risk.risk),
                    out.said(risk.mechanic),
                    out.said(risk.implication),
                    Cell(risk.severity),
                    out.basis(risk),
                ),
            )
            for index, risk in enumerate(submission.risks, 1)
        ],
        required=True,
    )
    out.table(
        REGISTERS[GAPS],
        [
            _Row(
                f"g{index:02d}",
                f"Gap {index}",
                (
                    Cell(f"CP-6-GAP-{index:03d}"),
                    out.said(gap.gap),
                    out.said(gap.why_it_matters),
                    out.said(gap.affected_analysis),
                    Cell(gap.severity),
                    out.said(gap.action),
                ),
            )
            for index, gap in enumerate(submission.gaps, 1)
        ],
        required=False,
    )


def _references(out: _Composer) -> tuple[list[Fact], ReportTable | None]:
    """The CP-1 facts the text references, carried verbatim under `cp1_references`."""
    referenced = [
        fact.model_copy(
            update={"table_id": CP1_REFERENCES, "row_id": f"ref{index:02d}", "field": "value"}
        )
        for index, fact in enumerate(out.referenced.values(), 1)
    ]
    if not referenced:
        return [], None
    return referenced, ReportTable(
        table_id=CP1_REFERENCES,
        title="CP-1 facts referenced in CP-6 text",
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


def committee_challenge(
    pack: PreparedPack, submission: CommitteeSubmission, upstream: Upstream
) -> CommitteeReport:
    """The composed CP-6 tables of a valid submission; raises ValueError on any issue."""
    issues = validate_committee(pack, submission, upstream)
    if issues:
        raise ValueError("; ".join(issues))
    pack = PreparedPack.model_validate_json(pack.model_dump_json())
    submission = CommitteeSubmission.model_validate_json(submission.model_dump_json())
    out = _Composer(upstream)
    # Own limitations: the gaps rows, the blocked ancestors and a restricted CP-5 handoff, an
    # Insufficient Information action bias or recovery view, and an empty required register.
    # Inherited ones are settlement's (`execution.settle`).
    out.limitations.extend(f"Gap ({g.severity}): {out.text(g.gap)}" for g in submission.gaps)
    out.limitations.extend(upstream.limits)
    action = _recommendation(submission, out)
    challenges = _ordered(submission, upstream)
    lines = _challenges(challenges, out)
    _recovery(submission, out)
    _risks_and_gaps(submission, out)
    out.front(COMMITTEE_CHALLENGE, [("recommendation", "Action bias", action), *lines])
    referenced, table = _references(out)
    tables = [*out.tables, *((table,) if table else ())]
    row = submission.recommendation
    # Claims are the model's run text as written; references resolve against the carried CP-1
    # facts (`execution.candidate_issues`). CP-6 quotes no pack source.
    claims = (
        Claim(
            claim_id=f"{FINAL_BIAS_TABLE}.{FINAL_BIAS_ROW}",
            text=row.rationale,
            citations=(),
            limitation=row.limitation,
        ),
        *(
            Claim(claim_id=f"{CROSS_EXAMINATION}.c{index:02d}", text=c.counter_case, citations=())
            for index, c in enumerate(challenges, 1)
        ),
        *(
            Claim(
                claim_id=f"{EVIDENCE_WEIGHTING}.v{index:02d}",
                text=view.view,
                citations=(),
                limitation=view.limitation,
            )
            for index, view in enumerate(submission.recovery_view, 1)
            if view.confidence != INSUFFICIENT
        ),
    )
    return CommitteeReport(
        run=pack.run,
        pack_sha256=pack.content_hash(),
        submission_sha256=submission.content_hash(),
        tables=tuple(tables),
        facts=(*out.facts, *referenced),
        claims=claims,
        limitations=tuple(dict.fromkeys(out.limitations)),
    )


# --- the module and the journal ---------------------------------------------------------------


def cp6_module(report: CommitteeReport, inputs: Sequence[Input], attempt: int) -> Module:
    """The CP-6 candidate: the report's tables and claims bound to `inputs`."""
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
        submission = CommitteeSubmission.model_validate_json(
            store.payload(attempt.steps[0].payload_sha256)
        )
    except ValidationError as error:
        return StepValidation(issues=shape_issues(error))
    upstream = cp6_upstream(store, attempt)
    issues = validate_committee(pack, submission, upstream)
    if issues:
        return StepValidation(issues=issues)
    return StepValidation(output=committee_challenge(pack, submission, upstream).model_dump_json())


def submit_cp6_step(store: Execution, ticket_id: str, step_id: str, payload: str) -> Attempt:
    """Retain the one `committee_challenge` response, validate it, then settle CP-6 with the
    Python candidate (as `submit_cp3_step`): promotion is an accepted step and no validator
    issue. An invalid step finishes the attempt rejected (or blocked on the repair); there is
    no within-attempt repair. A crash after the step resumes from the retained step."""
    if step_id != STEP_ID:
        raise ValueError(f"CP-6 has one step, {STEP_ID}")
    attempt = next((a for a in store.read().attempts if a.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != MODULE_ID or attempt.status != "pending":
        raise ValueError("Ticket is absent, finished or belongs to another module")
    if attempt.steps and attempt.steps[0].payload_sha256 != text_sha256(payload):
        raise ValueError("Ticket already retains a different response; resume or interrupt")
    if not attempt.steps or attempt.steps[0].status == "pending":
        attempt = store.submit_step(
            ticket_id,
            MODULE_ID,
            CP6_STEPS,
            STEP_ID,
            payload,
            lambda pack, current: _validate_step(store, pack, current),
        )
    if attempt.status == "finished":
        return attempt
    outcome = _validate_step(store, store.pack(), attempt)
    if outcome.issues or not outcome.retained_as(attempt.steps[0]):
        raise ValueError("Retained CP-6 output differs from trusted validation")
    report = CommitteeReport.model_validate_json(outcome.output or "")
    candidate = cp6_module(report, attempt.inputs, attempt.number)
    return store.finish(
        ticket_id,
        candidate.model_dump_json(),
        lambda supplied: () if supplied == candidate else ("CP-6 candidate differs",),
        qualification=PROMOTED,
    )


def _rows_of(rows: Mapping[str, CatalogueRow]) -> list[dict[str, object]]:
    return [
        {"ref": ref, "register": row.register, "row": row.label, "cells": dict(row.cells)}
        for ref, row in rows.items()
    ]


def _head(module: Module, status: str | None) -> dict[str, object]:
    return {
        "module_id": module.module_id,
        "status": status,
        "claims": [
            {
                "claim_id": claim.claim_id,
                "text": claim.text,
                "limitation": claim.limitation,
                "citations": [
                    {"source_id": c.source_id, "locator": c.locator, "quote": c.quote}
                    for c in claim.citations
                ],
            }
            for claim in module.claims
        ],
        "limitations": list(module.limitations),
        "inherited_limitations": list(module.inherited_limitations),
    }


def context_block(pack: PreparedPack, upstream: Upstream) -> dict[str, object]:
    """What the `committee_challenge` CONTEXT block adds to the pack facts, all Python's: the
    upstream statuses and blocked ancestors, per bound analyst head its claims, limitations and
    status, the CP-1 facts a figure reference may name, the CP-2, CP-3 and CP-5 rows a basis may
    cite (CP-2's challengeable ones marked), CP-5's findings, flagged claims and verdict, the
    read optional upstream, the confidence caps, the reasons the action bias is Insufficient
    Information and the limitations settlement will inherit. The pack is named for parity with
    the sibling blocks; CP-6 quotes none of its sources."""
    facts = referencable(upstream.cp1.facts)
    review = upstream.review
    return {
        "issuer": pack.run.issuer_name,
        "upstream": [
            {"module_id": item.input_id, "status": item.status}
            for item in upstream.bound
            if item.input_id.startswith("CP-")
        ],
        "blocked_ancestors": list(upstream.blocked_upstream),
        "heads": [
            _head(module, upstream.status(module.module_id))
            for module in (upstream.cp1, upstream.cp2, upstream.cp3, upstream.cp5)
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
            else "CP-1 offers no referencable figure: write no figure at all (labels only)."
        ),
        "cp2_rows": [
            {
                **entry,
                "challengeable": entry["ref"] in upstream.challengeable,
                "claim": (CP2, entry["ref"]) in upstream.claim_rows,
            }
            for entry in _rows_of(upstream.cp2_rows)
        ],
        "cp3_rows": [
            {**entry, "claim": (CP3, entry["ref"]) in upstream.claim_rows}
            for entry in _rows_of(upstream.cp3_rows)
        ],
        "cp5_rows": _rows_of(upstream.cp5_rows),
        "rows_note": (
            "Cite rows only by listing their refs in cp2_refs, cp3_refs and cp5_refs (a CP-5 "
            "finding may be named by its finding_id); never restate them. A thesis_ref names a "
            "cp2_rows ref whose challengeable is true, each at most once."
        ),
        "cp5_findings": [
            {"finding_id": f.finding_id, "ref": f.ref, "kind": f.kind, "where": f.where}
            for f in review.findings
        ],
        "cp5_flagged_claims": [list(key) for key in sorted(review.flagged)],
        "cp5_cp4_rows": sorted(upstream.cp4_evidence),
        "cp5_verdict": dict(review.verdict),
        "cp5_note": (
            "A recommendation that is not Insufficient Information cites at least one CP-2 or "
            "CP-3 row whose claim is true and that is outside cp5_flagged_claims, or names a "
            "CP-1 figure in its rationale or conditions; gap rows support nothing. A recovery "
            "view that is not Insufficient Information cites a cp5_cp4_rows ref; without one it "
            "is a gap."
        ),
        "optional_upstream": [
            {
                "module_id": module_id,
                "status": upstream.optional_status(module_id),
                "limitations": list(
                    upstream.optional[module_id].limitations
                    if module_id in upstream.optional
                    else ()
                ),
            }
            for module_id in READ_OPTIONAL
        ],
        "confidence_caps": list(upstream.caps),
        "insufficient_information": list(upstream.insufficient),
        "action_biases": list(ACTION_BIASES),
        "inherited_limitations": list(upstream.inherited),
    }
