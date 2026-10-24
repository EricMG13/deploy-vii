"""Model-facing step shapes and how a model payload enters the journal (decision 0008, MC-1).

For `source_readiness` the model returns a `ReadinessSubmission`: judgments and verbatim quotes
only, with no hash, no pack binding and no derived set. Python composes the stored
`ReadinessReview` (contract and hash unchanged) from it and the frozen pack:

- `pack_sha256` and every citation's `source_sha256` come from the pack. A citation that names a
  source the pack does not hold as ready cannot be bound; it is left out of the composed review and
  reported ("Unavailable or changed source: <id>", the validator's own wording), which rejects
  the submission.
- A consumer's `source_ids` (its attachment set) are the distinct sources its citations name, in
  citation order.
- Every pack source and every live consumer is assessed exactly once structurally: one the
  submission omits is added as an explicit placeholder (fidelity `blocked` / readiness `BLOCKED`,
  limitation "Not assessed in the model submission") plus a critical gap naming it, never as
  ready. Duplicates and extras are kept, so the validator's "exactly once" checks still see them.
- Locators are passed through exactly; `validate_review` matches them against the pack's span
  locators and checks the quote substring.

The composed review then meets `submit_cp0_review`, the same trusted path as any other review.
A payload that cannot be composed (not a submission, the pre-0008 `ReadinessReview` shape, or an
unbindable citation) is retained in the journal as received and rejected there with the
composition issues plus whatever the validator finds in the part that could be composed, so the
input set's repair is consumed exactly as for any other invalid response.

The CP-1 steps keep their stored contract as the model-facing shape for now (their MC-1 skeletons
are M6 work); `STEPS` is the hook: a step whose schema differs from its stored contract gets its
own composer here.

Task 7.0i (E1 batch e1-cp1-5): the model supplies no hash. Every hash binding of the CP-1 step
contracts is marked with its kind (`contracts.PREFILLED_MARKER`), so the sent schemas leave it out
(`live.schema`, "drop-prefilled"), and after null resolution Python fills it with the value the
step's validator compares it against (`PREFILLED`, `known_bindings`, `prefill`):

- `context-step`: the content hash of the ticket's valid retained `source_context` step;
- `pack`: the prepared pack's hash; `source`: a citation's ready source's hash by its source_id;
- `source-context-review`: the hash of the retained `SourceContextReview`;
- `facility`: the hash of the book's facility row the conversion names (last match);
- `annual-observation`, `quarter-observations`: the hashes of the book's effective account values
  for the explanation's periods and metric;
- `financial-review`: the hash of the submitted `financial` object parsed as `FinancialReview`;
- `step-inputs`: for `narrative` the financial stage's `NarrativeInputs`, for `readiness` the
  narrative step's `DownstreamInputs`;
- `quality-inputs` (task 7.4): `cp1_quality_inputs` of the ticket's recomputed registers, the
  scope `validate_quality_review` binds the review to. Registers that do not stage raise
  ValueError with the staging issue before anything is written.
- `scope-dimension` (task 7.13, user-approved, decision 0005): a book's and each period's
  `currency`, `unit`, `accounting_basis` and `entity_perimeter`, copied from the retained
  source-context scopes the model's own choices select (the book's `binding.books[].entity_id`,
  each period's `period_type`, `start_date` and `end_date`, by `context_binding`'s date and kind
  rule over the financial sources' scopes). A book takes the one tuple its bound periods share;
  where they share none (or more than one) the book is left unfilled and one issue names the
  periods and fields; a period no scope matches is left unfilled and rejected in
  `context_binding`'s wording per cited source; a scope's null dimension is never written, so
  the stored contract's "Field required" names it. The validators' exact-match rules are
  unchanged: they pass because the strings are the scope's.

Task 7.4: `quality` is the fifth CP-1 step. Its model-facing shape is the stored `QualityReview`
(materiality, lineage within each ceiling, findings; never a score, band or status). After null
resolution and the pre-fill it enters the journal only through `cp1_workflow.promote_cp1`: an
accepted review is the promotion, a rejected one finishes the attempt (no within-attempt
repair: the step settles the module), so the module-wide repair re-runs the chain.

A value the payload carries is overwritten. A payload already holding every right value is kept
byte for byte and nothing is recorded; otherwise it is rewritten (`live.schema.exact_json`,
numbers keep their digits) and every changed JSON path is recorded in `Submitted.prefilled`. A
reference Python cannot resolve (an unknown or not-ready source, an unknown facility or period,
an audit explanation whose period or observation the book lacks) is rejected with the validator's
own wording first (`_validate_prefilled`, mirroring CP-0's uncomposable path); a binding whose
sub-object does not parse is left as sent, so the shape rejection names the cause, without
(task 7.16) the "Field required" of the binding the model was never offered; a payload that
is not a JSON object or cannot be stored as UTF-8 is handed on as received. A missing retained
step raises ValueError before anything is written. The validators' binding checks are unchanged.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cached_property, partial
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from deploy_vii.business_context import BusinessContextSubmission, submit_cp1a_step
from deploy_vii.contracts import Contract
from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_workflow import (
    CP1_STEPS,
    FinancialStage,
    FinancialSubmission,
    cp1_registers,
    promote_cp1,
    submit_cp1_step,
    validate_cp1_stage,
)
from deploy_vii.cp2_synthesis import CreditSynthesisSubmission, submit_cp2_step
from deploy_vii.cp3_relative_value import RelativeValueSubmission, submit_cp3_step
from deploy_vii.cp4_legal import CovenantInterpretationSubmission, submit_cp4_step
from deploy_vii.cp5_integrity import IntegritySubmission, submit_cp5_step
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview
from deploy_vii.execution import Attempt, Execution, StepSubmission, StepValidation
from deploy_vii.financial_contracts import FacilityObservation, FinancialBook, FinancialReview
from deploy_vii.live.schema import Marked, exact_json, json_object, marked_fields, normalise
from deploy_vii.narrative import NarrativeReview
from deploy_vii.preparation import PreparedPack
from deploy_vii.quality import QualityInputs, QualityReview
from deploy_vii.readiness import (
    Authority,
    Fidelity,
    GapKind,
    GapSeverity,
    Readiness,
    ReadinessReview,
    live_consumers,
    shape_issues,
    validate_review,
)
from deploy_vii.registry import bound_steps, prefilled_kinds, step_modules
from deploy_vii.source_context import (
    DIMENSIONS,
    ReportingScope,
    SourceContextReview,
    scope_matches_period,
)
from deploy_vii.statement_validation import effective_accounts

SUPERSEDED_SHAPE = "schema: pre-0008 submission shape"
NOT_ASSESSED = "Not assessed in the model submission"


# Plain `str` fields: no pattern or length keywords in the response schema (their strict-mode
# acceptance is undocumented). The composed `ReadinessReview` enforces identifiers and text.
class SubmittedCitation(Contract):
    source_id: str
    locator: str
    quote: str


class SourceJudgment(Contract):
    source_id: str
    document_family: str
    authority: Authority
    entity: str | None
    period: str | None
    version_relationship: str
    fidelity: Fidelity
    citations: tuple[SubmittedCitation, ...]
    limitations: tuple[str, ...]


class ConsumerJudgment(Contract):
    module_id: str
    readiness: Readiness
    evidence_demand: str
    rationale: str
    citations: tuple[SubmittedCitation, ...]
    missing_source: str | None
    limitations: tuple[str, ...]


class GapJudgment(Contract):
    gap_id: str
    kind: GapKind
    severity: GapSeverity
    description: str
    affected_modules: tuple[str, ...]
    remediation: str
    citations: tuple[SubmittedCitation, ...]


class ClaimJudgment(Contract):
    claim_id: str
    text: str
    citations: tuple[SubmittedCitation, ...]
    limitation: str | None


class ReadinessSubmission(Contract):
    """What the model returns for `source_readiness`; every field is required (no defaults)."""

    objective: str
    reporting_period: str
    issuer_confirmed: bool
    sources: tuple[SourceJudgment, ...]
    consumers: tuple[ConsumerJudgment, ...]
    gaps: tuple[GapJudgment, ...]
    # `minItems: 1` in the sent schema only (task 2.10): the trusted validator stays the one that
    # rejects an empty read-through, in its own words, beside the submission's other issues.
    analysis: tuple[ClaimJudgment, ...] = Field(json_schema_extra={"minItems": 1})


type Judgment = SourceJudgment | ConsumerJudgment | GapJudgment | ClaimJudgment


@dataclass(frozen=True)
class StepDef:
    module_id: str
    schema: type[BaseModel]  # the model-facing shape: prompt schema, response_format, parse


def step_definitions(schemas: Mapping[str, type[BaseModel]]) -> dict[str, StepDef]:
    """Every registry step (`registry.step_modules`, its order and module) with its schema from
    `schemas`; a registry step without a schema, or a schema for no registry step, raises
    ValueError (task 8.0a)."""
    modules = step_modules()
    if extra := sorted(set(schemas) - set(modules)):
        raise ValueError(f"a schema for {', '.join(extra)}, which is no live step")
    if missing := [step_id for step_id in modules if step_id not in schemas]:
        raise ValueError(f"no model-facing schema for {', '.join(missing)}")
    return {step_id: StepDef(module_id, schemas[step_id]) for step_id, module_id in modules.items()}


STEPS: Mapping[str, StepDef] = step_definitions(
    {
        "source_readiness": ReadinessSubmission,
        "source_context": SourceContextReview,
        "financials": FinancialSubmission,
        "narrative": NarrativeReview,
        "readiness": DownstreamReview,
        # Task 7.4: the analyst's QA review over the retained registers; its accepted submission
        # is the CP-1 promotion (`cp1_workflow.promote_cp1`).
        "quality": QualityReview,
        # Task 7.2: the stored shape is the submission itself; Python composes the registers as
        # the step output (`business_context.submit_cp1a_step`), so no composer is needed here.
        "business_context": BusinessContextSubmission,
        # Task 8.6: each module's thin submission is its stored shape too; its step entry
        # validates it and settles the module with the Python candidate (`MODULE_STEP_ENTRIES`).
        "credit_synthesis": CreditSynthesisSubmission,
        "legal_covenants": CovenantInterpretationSubmission,
        "relative_value": RelativeValueSubmission,
        "integrity_review": IntegritySubmission,
    }
)
# The one-step modules whose own entry retains, validates and settles the step (task 7.2 for
# CP-1A, task 8.6 for the rest); the payload reaches it after null resolution only.
MODULE_STEP_ENTRIES: Mapping[str, Callable[[Execution, str, str, str], Attempt]] = {
    "CP-1A": submit_cp1a_step,
    "CP-2": submit_cp2_step,
    "CP-4": submit_cp4_step,
    "CP-3": submit_cp3_step,
    "CP-5": submit_cp5_step,
}
# Task 7.0i: the model supplies no hash. Each hash binding of a CP-1 step contract is marked
# `PREFILLED_MARKER` with its kind (so the sent schema leaves it out), and Python fills it before
# the journal validates. Per step: the kinds it carries, and the retained steps they come from
# (every earlier step of its chain). Both are the registry's (task 8.0a).
PREFILLED: Mapping[str, frozenset[str]] = prefilled_kinds()
BOUND_STEPS: Mapping[str, tuple[str, ...]] = bound_steps()
# Fill order: a phase reads only values that are sent or that earlier phases wrote (a facility
# row and an observation hash cover their citations; the financial review hash covers them all).
# The dimension strings (task 7.13) read only sent fields, and the observation hashes parse the
# book, which needs them.
PHASES = (
    frozenset(
        {"context-step", "pack", "source", "source-context-review", "step-inputs", "quality-inputs"}
    ),
    frozenset({"scope-dimension"}),
    frozenset({"facility"}),
    frozenset({"annual-observation", "quarter-observations"}),
    frozenset({"financial-review"}),
)


@dataclass(frozen=True)
class Composition:
    """A composed review (None when the payload could not be composed at all), the issues that
    make the submission unusable as received, and the placeholders Python added."""

    review: ReadinessReview | None
    issues: tuple[str, ...]
    placeholders: tuple[str, ...] = ()


def _placeholder_source(source_id: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "document_family": NOT_ASSESSED,
        "authority": "unknown",
        "entity": None,
        "period": None,
        "version_relationship": NOT_ASSESSED,
        "fidelity": "blocked",
        "citations": [],
        "limitations": [NOT_ASSESSED],
    }


def _placeholder_consumer(module_id: str) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "readiness": "BLOCKED",
        "evidence_demand": NOT_ASSESSED,
        "source_ids": [],
        "rationale": f"{NOT_ASSESSED}; Python recorded the omission and blocks the consumer",
        "citations": [],
        "missing_source": None,
        "limitations": [NOT_ASSESSED],
    }


def _placeholder_gap(gap_id: str, kind: str, what: str, affected: list[str]) -> dict[str, Any]:
    return {
        "gap_id": gap_id,
        "kind": kind,
        "severity": "critical",
        "description": f"{what}: {NOT_ASSESSED.lower()}",
        "affected_modules": affected,
        "remediation": "Repair the source_readiness step so that it assesses this item",
        "citations": [],
    }


def compose(pack: PreparedPack, submission: ReadinessSubmission) -> Composition:
    """The stored `ReadinessReview` for `submission` over `pack` (see the module docstring)."""
    bindable = {s.source_id: s.sha256 for s in pack.sources if s.status == "ready" and s.sha256}
    issues: list[str] = []

    def cite(items: tuple[SubmittedCitation, ...]) -> list[dict[str, str]]:
        bound = []
        for item in items:
            digest = bindable.get(item.source_id)
            if digest is None:
                issues.append(f"Unavailable or changed source: {item.source_id}")
                continue
            bound.append(
                {
                    "source_id": item.source_id,
                    "source_sha256": digest,
                    "locator": item.locator,
                    "quote": item.quote,
                }
            )
        return bound

    def with_citations(item: Judgment) -> dict[str, Any]:
        return {**item.model_dump(mode="json"), "citations": cite(item.citations)}

    sources = [with_citations(item) for item in submission.sources]
    consumers = [with_citations(item) for item in submission.consumers]
    for consumer in consumers:  # the attachment set: the distinct cited sources, in order
        consumer["source_ids"] = list(dict.fromkeys(c["source_id"] for c in consumer["citations"]))
    gaps = [with_citations(item) for item in submission.gaps]
    analysis = [with_citations(item) for item in submission.analysis]
    expected = live_consumers(pack)
    assessed = {item.source_id for item in submission.sources}
    judged = {item.module_id for item in submission.consumers}
    placeholders: list[str] = []
    for source in pack.sources:
        if source.source_id not in assessed:
            placeholders.append(f"source:{source.source_id}")
            sources.append(_placeholder_source(source.source_id))
            gaps.append(
                _placeholder_gap(
                    f"not-assessed.{source.source_id}",
                    "source",
                    f"Source {source.source_id}",
                    list(expected),
                )
            )
    for module_id in expected:
        if module_id not in judged:
            placeholders.append(f"consumer:{module_id}")
            consumers.append(_placeholder_consumer(module_id))
            gaps.append(
                _placeholder_gap(
                    f"not-assessed.{module_id}", "scope", f"Consumer {module_id}", [module_id]
                )
            )
    document = {
        "pack_sha256": pack.content_hash(),
        "objective": submission.objective,
        "reporting_period": submission.reporting_period,
        "issuer_confirmed": submission.issuer_confirmed,
        "sources": sources,
        "consumers": consumers,
        "gaps": gaps,
        "analysis": analysis,
    }
    bound = tuple(dict.fromkeys(issues))
    try:
        review = ReadinessReview.model_validate_json(json.dumps(document))
    except ValidationError as error:
        return Composition(None, (*bound, *shape_issues(error)), tuple(placeholders))
    return Composition(review, bound, tuple(placeholders))


def compose_payload(pack: PreparedPack, payload: str) -> Composition:
    """Parse a (null-resolved) model payload as a `ReadinessSubmission` and compose it."""
    try:
        document = json.loads(payload)
    except ValueError:
        document = None
    if isinstance(document, dict) and "pack_sha256" in document:
        # The model returned the stored contract (it binds the pack itself): pre-0008 shape.
        return Composition(None, (SUPERSEDED_SHAPE,))
    try:
        submission = ReadinessSubmission.model_validate_json(payload)
    except ValidationError as error:
        return Composition(None, shape_issues(error))
    return compose(pack, submission)


def rejection_issues(pack: PreparedPack, payload: str) -> tuple[str, ...]:
    """Every issue of a payload that cannot be composed cleanly (empty when it can)."""
    composition = compose_payload(pack, payload)
    if not composition.issues:
        return ()
    found = validate_review(pack, composition.review) if composition.review else ()
    return tuple(dict.fromkeys((*composition.issues, *found)))


def _validate_uncomposable(
    store: Execution, pack: PreparedPack, attempt: Attempt
) -> StepValidation:
    issues = rejection_issues(pack, store.payload(attempt.steps[0].payload_sha256))
    if not issues:
        # The same payload composes cleanly now: it belongs on the trusted review path instead.
        raise ValueError("Retained submission composes cleanly; resubmit it as a review")
    return StepValidation(issues=issues)


@dataclass(frozen=True)
class Known:
    """The values Python binds a step's payload to, read from the journal before any write:
    the pack's hash, each ready source's hash, the step-level kinds (`STEP_KINDS`) and, for
    `financials`, the retained source-context review whose scopes the dimension strings come
    from (task 7.13; None elsewhere, so nothing fills them)."""

    pack_sha256: str
    sources: Mapping[str, str]
    step: Mapping[str, str]
    context: SourceContextReview | None = None


def _held_output(store: Execution, step: StepSubmission) -> str:
    if step.output_sha256 is None:  # a valid step always retains its output (StepSubmission)
        raise ValueError(f"Step {step.step_id} retains no output")
    return store.step_output(step.output_sha256)


def quality_inputs(store: Execution, ticket_id: str) -> QualityInputs:
    """The QA scope the `quality` step's review must bind: `cp1_quality_inputs` of the ticket's
    trusted registers (every stage recomputed). Registers that do not stage raise ValueError
    with the staging issue, before anything is written."""
    try:
        registers = cp1_registers(store, ticket_id)
    except ValueError as error:
        raise ValueError(f"Ticket {ticket_id} QA inputs cannot be computed: {error}") from error
    return cp1_quality_inputs(registers)


def known_bindings(store: Execution, ticket_id: str, step_id: str) -> Known:
    """What `prefill` writes for `step_id` on this ticket: exactly the values the step's
    validators compare against (`cp1_workflow._validate_stage`, `validate_source_context`,
    `validate_financial_context`, `validate_definition_review`, the narrative and downstream
    validators, `validate_quality_review`). Raises ValueError when a step the bindings come from
    is not retained valid, or when the QA inputs cannot be computed (`quality_inputs`)."""
    snapshot = store.read()
    attempt = next((a for a in snapshot.attempts if a.ticket_id == ticket_id), None)
    held = attempt.steps if attempt is not None else ()
    for index, wanted in enumerate(BOUND_STEPS[step_id]):
        if len(held) <= index or held[index].step_id != wanted or held[index].status != "valid":
            raise ValueError(f"Ticket {ticket_id} retains no valid {wanted} step to bind")
    pack = store.pack(snapshot)
    step: dict[str, str] = {}
    context: SourceContextReview | None = None
    if step_id == "financials":
        step["context-step"] = held[0].content_hash()
        context = SourceContextReview.model_validate_json(store.payload(held[0].payload_sha256))
        step["source-context-review"] = context.content_hash()
    elif step_id == "narrative":
        stage = FinancialStage.model_validate_json(_held_output(store, held[1]))
        step["step-inputs"] = stage.narrative_inputs.content_hash()
    elif step_id == "readiness":
        step["step-inputs"] = DownstreamInputs.model_validate_json(
            _held_output(store, held[2])
        ).content_hash()
    elif step_id == "quality":
        step["quality-inputs"] = quality_inputs(store, ticket_id).content_hash()
    return Known(
        pack_sha256=pack.content_hash(),
        sources={s.source_id: s.sha256 for s in pack.sources if s.status == "ready" and s.sha256},
        step=step,
        context=context,
    )


def _parsed_hash(model: type[Contract], value: object) -> str | None:
    """The content hash of `value` parsed as `model`; None when it does not parse (the existing
    shape rejection then stands)."""
    if not isinstance(value, dict):
        return None
    try:
        return model.model_validate_json(exact_json(value)).content_hash()
    except ValidationError:
        return None


@dataclass(frozen=True)
class _Book:
    """What `audit_explanation_issues` reads of one book: its period ids and each effective
    account value's hash by (period, metric), the last one winning."""

    periods: frozenset[str]
    observations: Mapping[tuple[str, str], str]


# Task 7.13: the four strings `context_binding` and `book_issues` compare exactly, in
# `source_context.DIMENSIONS` order (task 8.0b).
type Dimensions = tuple[str | None, ...]
# Parsed as the stored contract parses a period's dates (`Contract`: strict, from JSON).
_DAY: TypeAdapter[date | None] = TypeAdapter(date | None, config=ConfigDict(strict=True))


def _book_path(item: Marked) -> str:
    """The JSON path of the book that holds a marked dimension field: the field's own path
    less its name, less `periods.<n>` too for a period's."""
    head = item.path[: -len(item.name)].rstrip(".")
    return (
        head if item.holder is item.enclosing("FinancialBook") else head.rsplit(".periods.", 1)[0]
    )


def _scope_strings(scope: ReportingScope) -> Dimensions:
    return tuple(getattr(scope, name) for name in DIMENSIONS)


def _period_scopes(
    period: dict[str, Any], scopes: Sequence[ReportingScope]
) -> frozenset[Dimensions] | None:
    """The distinct strings of the scopes a period binds to, by the date and kind rule
    `context_binding` binds by (`source_context.scope_matches_period`). None when the period's
    type or dates (or its id) do not parse as the contract parses them: the shape rejection
    names them."""
    kind = period.get("period_type")
    if (
        not isinstance(kind, str)
        or not isinstance(period.get("period_id"), str)
        or not {"start_date", "end_date"} <= period.keys()
    ):
        return None
    try:
        start = _DAY.validate_json(exact_json(period["start_date"]))
        end = _DAY.validate_json(exact_json(period["end_date"]))
    except ValidationError:
        return None
    return frozenset(
        _scope_strings(scope) for scope in scopes if scope_matches_period(scope, kind, start, end)
    )


class _Resolver:
    """The value of one marked binding, or None when Python cannot know it from what was sent.
    A reference Python cannot resolve (an unknown or not-ready source, an unknown facility, an
    audit explanation period or observation the book lacks) is recorded in `unbound` with the
    validator's own wording, so the step is rejected as the validator would reject it."""

    def __init__(self, known: Known, document: dict[str, Any]) -> None:
        self.known = known
        self.document = document
        self.books: dict[int, _Book | None] = {}
        self.dimensions: dict[int, Mapping[int, Dimensions]] = {}
        self.unbound: list[tuple[str, str]] = []

    @cached_property
    def financial_review(self) -> str | None:
        """Read first in the last phase, when `financial` holds every value it will hold."""
        return _parsed_hash(FinancialReview, self.document.get("financial"))

    def __call__(self, item: Marked) -> object | None:
        holder, kind = item.holder, item.kind
        if kind == "pack":
            return self.known.pack_sha256
        if kind == "source":
            source_id = holder.get("source_id")
            if not isinstance(source_id, str):
                return None  # not an id: the shape rejection names it
            digest = self.known.sources.get(source_id)
            if digest is None:  # `readiness.citation_issues`' wording
                self.unbound.append((item.path, f"Unavailable or changed source: {source_id}"))
            return digest
        if kind in self.known.step:
            return self.known.step[kind]
        if kind == "financial-review":
            return self.financial_review
        book = item.enclosing("FinancialBook")
        if book is None:
            return None
        if kind == "scope-dimension":
            if id(book) not in self.dimensions:
                self.dimensions[id(book)] = self._dimensions(item, book)
            strings = self.dimensions[id(book)].get(id(item.holder))
            value = None if strings is None else strings[DIMENSIONS.index(item.name)]
            if strings is not None and value is None:
                # The bound scope states no such dimension: the contract's own message, kept
                # visible (`_validate_prefilled` drops "Field required" of other unset fields).
                self.unbound.append((item.path, f"{item.path}: Field required"))
            return value
        if kind == "facility":
            return self._facility(item, book)
        if kind in {"annual-observation", "quarter-observations"}:
            return self._observation(item, book)
        raise ValueError(f"No pre-fill for the marked binding kind {kind!r}")

    def _dimensions(self, item: Marked, book: dict[str, Any]) -> Mapping[int, Dimensions]:
        """Task 7.13: the four strings of the book and of each period, keyed by the object's
        id; an object left out is not filled.

        A period takes the strings of the scopes it binds to (`_period_scopes`, over the
        financial sources' scopes of the book's bound entity). The book takes the one tuple
        every period that binds to a scope shares, and each such period takes it too. Where
        there is no single shared tuple, nothing is filled for the book (no majority, no first
        wins), each period with one tuple keeps its own, and one issue names the periods and
        the fields. A period that binds to no scope is left unfilled and rejected with
        `context_binding`'s wording for each source it cites; a binding that names no single
        known entity, with the wording of that validator's binding checks."""
        context, book_id, periods = self.known.context, book.get("book_id"), book.get("periods")
        if context is None or not isinstance(book_id, str) or not isinstance(periods, list):
            return {}
        where = _book_path(item)
        entity = self._bound_entity(where, book_id, context)
        if entity is None:
            return {}
        classes = {source.source_id: source.classification for source in context.sources}
        scopes = [
            scope
            for source in context.sources
            if source.classification == "financial"
            for scope in source.scopes
            if scope.entity_id == entity
        ]
        filled: dict[int, Dimensions] = {}
        bound: list[tuple[str, frozenset[Dimensions], dict[str, Any]]] = []
        for index, period in enumerate(periods):
            found = _period_scopes(period, scopes) if isinstance(period, dict) else None
            if found is None:
                continue  # the shape rejection names what does not parse
            period_id = period["period_id"]
            if not found:
                self._no_scope(f"{where}.periods.{index}", book_id, period_id, period, classes)
                continue
            bound.append((period_id, found, period))
            if len(found) == 1:
                (filled[id(period)],) = found
        if not bound:
            return filled
        shared = frozenset.intersection(*(found for _, found, _ in bound))
        if len(shared) == 1:
            (strings,) = shared
            return {**{id(period): strings for _, _, period in bound}, id(book): strings}
        differing = [
            name
            for index, name in enumerate(DIMENSIONS)
            if len({strings[index] for _, found, _ in bound for strings in found}) > 1
        ]
        issue = (
            f"Bound source scopes disagree on {', '.join(differing)}: "
            f"{book_id} {', '.join(period_id for period_id, _, _ in bound)}"
        )
        self.unbound.append((where, issue))
        return filled

    def _bound_entity(self, where: str, book_id: str, context: SourceContextReview) -> str | None:
        """The one entity `binding.books` binds `book_id` to, or None. A count other than one
        and an entity the source context lacks are recorded in `validate_financial_context`'s
        wording; a binding that does not parse is left to the shape rejection."""
        binding = self.document.get("binding")
        rows = binding.get("books") if isinstance(binding, dict) else None
        if not isinstance(rows, list):
            return None
        named = [
            r.get("entity_id") for r in rows if isinstance(r, dict) and r.get("book_id") == book_id
        ]
        if len(named) != 1:
            self.unbound.append((where, "Bind every financial book exactly once"))
            return None
        (entity,) = named
        if not isinstance(entity, str):
            return None
        if entity not in {known.entity_id for known in context.entities}:
            self.unbound.append((where, f"Unknown bound entity: {book_id} {entity}"))
            return None
        return entity

    def _no_scope(
        self,
        where: str,
        book_id: str,
        period_id: str,
        period: dict[str, Any],
        classes: Mapping[str, str],
    ) -> None:
        """`validate_financial_context`'s issue for each source the unbound period cites: no
        matching scope in a financial source, or a source not classified financial. A source
        the context lacks is skipped (its citation's own binding names it)."""
        citations = period.get("citations")
        cited = sorted(
            {
                c["source_id"]
                for c in (citations if isinstance(citations, list) else ())
                if isinstance(c, dict) and isinstance(c.get("source_id"), str)
            }
        )
        for source_id in cited:
            if source_id not in classes:
                continue
            if classes[source_id] == "financial":
                issue = (
                    f"No matching entity/date/basis source scope: {book_id} {period_id} {source_id}"
                )
            else:
                issue = f"Financial evidence source not classified financial: {book_id} {source_id}"
            self.unbound.append((where, issue))

    def _facility(self, item: Marked, book: dict[str, Any]) -> str | None:
        # `fx_conversion_issues` keys rows by (facility_id, period_id); the last one wins.
        scope = item.holder.get("facility_id"), item.holder.get("period_id")
        rows = book.get("facilities")
        matches = [
            row
            for row in (rows if isinstance(rows, list) else ())
            if isinstance(row, dict) and (row.get("facility_id"), row.get("period_id")) == scope
        ]
        if matches:
            return _parsed_hash(FacilityObservation, matches[-1])
        conversion = item.holder.get("conversion_id")
        if isinstance(conversion, str):  # `fx_conversion_issues`' wording
            self.unbound.append((item.path, f"FX conversion {conversion}: unknown facility/period"))
        return None

    def _observation(self, item: Marked, book: dict[str, Any]) -> object | None:
        holder = item.holder
        explanation, metric = holder.get("explanation_id"), holder.get("metric_id")
        annual, quarters = holder.get("annual_period_id"), holder.get("quarter_period_ids")
        parsed = self._book(book)
        if (
            parsed is None
            or not isinstance(explanation, str)
            or not isinstance(metric, str)
            or not isinstance(annual, str)
            or not (isinstance(quarters, list) and all(isinstance(q, str) for q in quarters))
        ):
            return None  # the shape rejection names what does not parse
        # `audit_explanation_issues`' wording, in its order.
        if annual not in parsed.periods or any(q not in parsed.periods for q in quarters):
            self.unbound.append((item.path, f"Unknown audit explanation period: {explanation}"))
            return None
        wanted = [annual] if item.kind == "annual-observation" else quarters
        found = [parsed.observations.get((period, metric)) for period in wanted]
        for period, digest in zip(wanted, found, strict=True):
            if digest is None:
                issue = f"Stale audit explanation observation: {explanation} {period}"
                self.unbound.append((item.path, issue))
        if not all(found):
            return None
        return found[0] if item.kind == "annual-observation" else found

    def _book(self, book: dict[str, Any]) -> _Book | None:
        """The book parsed without its explanations (effective accounts read only accounts and
        statement lines); None when it does not parse."""
        if id(book) not in self.books:
            try:
                parsed = FinancialBook.model_validate_json(
                    exact_json({**book, "audit_basis_explanations": []})
                )
            except ValidationError:
                self.books[id(book)] = None
            else:
                self.books[id(book)] = _Book(
                    periods=frozenset(p.period_id for p in parsed.periods),
                    observations={
                        (row.period_id, row.metric_id): row.value.content_hash()
                        for row in effective_accounts(parsed)
                    },
                )
        return self.books[id(book)]


@dataclass(frozen=True)
class Prefill:
    """`prefill`'s result: the payload to retain, the JSON paths Python set with each one's kind,
    the (path, validator-worded issue) of each reference Python could not resolve, and the marked
    paths still unset: every marked path absent after the pre-fill, such as an unbound
    reference's field and the bindings that depend on it, and also a hash whose sub-object did
    not parse."""

    payload: str
    paths: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    unbound: tuple[tuple[str, str], ...] = ()
    unset: tuple[str, ...] = ()


def prefill(model: type[BaseModel], payload: str, known: Known, kinds: frozenset[str]) -> Prefill:
    """`payload` with every marked binding (`live.schema.marked_fields`) set to the value Python
    knows, in `PHASES` order. The payload is unchanged (same string, no paths) when every value is
    already right, or when it is not a JSON object or cannot be stored as UTF-8 (a lone surrogate
    escape, which Pydantic refuses as invalid JSON). A binding Python cannot know is left as sent;
    an unresolvable reference among them is also returned in `unbound`. A marked kind outside
    `kinds` raises ValueError (nothing fills it)."""
    document = json_object(payload)
    if document is None:
        return Prefill(payload)
    try:
        exact_json(document).encode()
    except UnicodeEncodeError:
        return Prefill(payload)
    marked = marked_fields(model, document)
    unknown = sorted({item.kind for item in marked} - kinds)
    if unknown:
        raise ValueError(f"No pre-fill for the marked binding kinds {unknown}")
    resolve = _Resolver(known, document)
    changed: list[Marked] = []
    for phase in PHASES:
        for item in marked:
            if item.kind not in phase:
                continue
            value = resolve(item)
            if value is not None and item.holder.get(item.name) != value:
                item.holder[item.name] = value
                changed.append(item)
    return Prefill(
        exact_json(document) if changed else payload,
        tuple(item.path for item in changed),
        tuple(item.kind for item in changed),
        tuple(dict.fromkeys(resolve.unbound)),
        tuple(item.path for item in marked if item.name not in item.holder),
    )


def _validate_prefilled(
    store: Execution, known: Known, step_id: str, pack: PreparedPack, attempt: Attempt
) -> StepValidation:
    """The validation of a step whose pre-fill left a marked field unset, recomputed from the
    retained payload and the bindings read before the write: the stage's own issues without the
    "Field required" of each unset field (the sent schema never offers it: an unbound
    reference's own field, or a hash that covers what did not parse, such as the financial
    review's when the financial object fails its own shape; task 7.16).

    With an unresolvable reference (as `_validate_uncomposable` is CP-0's) the validator-worded
    unbound issues come first and the step is rejected. Otherwise the stage's outcome stands
    with only those lines removed; when they are its only issues, the unset dimension strings'
    lines stay (task H1: a period bound to no scope that cites nothing itself; never a hash's,
    which covers what did not parse), and only a stage whose issues are all hash lines keeps
    them, so stripping never turns a rejection into an acceptance. Acceptance is unchanged:
    such a payload never validated."""
    retained = store.payload(attempt.steps[-1].payload_sha256)
    result = prefill(STEPS[step_id].schema, retained, known, PREFILLED[step_id])
    if not (result.unbound or result.unset):
        raise ValueError("Retained payload binds cleanly; resubmit it through submit_cp1_step")
    unset = {f"{path}: Field required" for path in result.unset}
    stage = validate_cp1_stage(store, pack, attempt)
    kept = tuple(issue for issue in stage.issues if issue not in unset)
    if result.unbound:
        issues = (*(issue for _, issue in result.unbound), *kept)
        return StepValidation(issues=tuple(dict.fromkeys(issues)))
    if not kept:
        hashes = {
            f"{path}: Field required"
            for path in result.unset
            if path.rsplit(".", 1)[-1] not in SCOPE_DIMENSIONS
        }
        named = tuple(issue for issue in stage.issues if issue not in hashes)
        return StepValidation(output=stage.output, issues=named) if named else stage
    return StepValidation(output=stage.output, issues=kept)


@dataclass(frozen=True)
class Submitted:
    journal: Attempt
    payload: str  # what the journal step retains: composed, pre-filled or as received
    nulls_resolved: tuple[str, ...]
    prefilled: tuple[str, ...]  # JSON paths of the bindings Python set (task 7.0i)
    prefilled_kinds: tuple[str, ...]  # each path's binding kind
    composition: Composition | None  # source_readiness only


def _with_rules(
    validate: Callable[[PreparedPack, Attempt], StepValidation],
    rules: Callable[[str], tuple[str, ...]],
    payload: str,
) -> Callable[[PreparedPack, Attempt], StepValidation]:
    """`validate`, then the tool-loop rule issues of the retained payload appended (task 8.0d).
    They only add issues: a payload the stage rejects stays rejected, one it accepts is rejected
    when a rule fails, and the stage's output is kept as `_validate_prefilled` keeps it."""

    def run(pack: PreparedPack, attempt: Attempt) -> StepValidation:
        outcome = validate(pack, attempt)
        found = rules(payload)
        if not found:
            return outcome
        issues = tuple(dict.fromkeys((*outcome.issues, *found)))
        return StepValidation(output=outcome.output, issues=issues)

    return run


def submit_model_payload(
    store: Execution,
    ticket_id: str,
    step_id: str,
    payload: str,
    *,
    on_normalised: Callable[[tuple[str, ...]], None] | None = None,
    rules: Callable[[str], tuple[str, ...]] | None = None,
) -> Submitted:
    """Enter one model payload (pool or proxy cohort) into the journal for `step_id`.

    Nulls standing for omitted defaults are resolved first (`live.schema.normalise`, against the
    model-facing schema). `on_normalised` sees the resolved paths before the journal does, so a
    caller can record them even if validation raises. Then every CP-1 step's hash bindings are
    pre-filled (`prefill`; see the module docstring); a payload the pre-fill leaves a marked field
    unset in is validated by `_validate_prefilled` (an unresolvable reference rejected with the
    validator's wording first; the "Field required" of a field the sent schema omits is dropped,
    unless, with no unbound reference, those lines are the stage's only issues).

    `rules` (task 8.0d, a tool-loop step's evidence rules, `live.tools.ToolRules`) receives the
    retained payload and returns issues the journal adds to the step's own (`_with_rules`). It
    applies to the four CP-1 stages only; for any other step it is refused."""
    step = STEPS[step_id]
    if rules is not None and (step.module_id != "CP-1" or step_id == "quality"):
        raise ValueError(f"tool-loop rules apply to the CP-1 stages, not to {step_id}")
    normalised, resolved = normalise(step.schema, payload)
    if on_normalised is not None:
        on_normalised(resolved)
    entry = MODULE_STEP_ENTRIES.get(step.module_id)
    if entry is not None:
        journal = entry(store, ticket_id, step_id, normalised)
        return Submitted(journal, normalised, resolved, (), (), None)
    if step_id == "quality":
        # Task 7.4: the review enters the journal only through the promotion, so an accepted
        # step is the promotion and a rejected one finishes the attempt (`promote_cp1`). Its one
        # binding always resolves (`quality_inputs` raises before any write when it cannot).
        known = known_bindings(store, ticket_id, step_id)
        filled = prefill(step.schema, normalised, known, PREFILLED[step_id])
        journal = promote_cp1(store, ticket_id, filled.payload)
        return Submitted(journal, filled.payload, resolved, filled.paths, filled.kinds, None)
    if step_id != "source_readiness":
        known = known_bindings(store, ticket_id, step_id)
        filled = prefill(step.schema, normalised, known, PREFILLED[step_id])
        if not (filled.unbound or filled.unset or rules):
            journal = submit_cp1_step(store, ticket_id, step_id, filled.payload)
            return Submitted(journal, filled.payload, resolved, filled.paths, filled.kinds, None)
        validate: Callable[[PreparedPack, Attempt], StepValidation] = (
            partial(_validate_prefilled, store, known, step_id)
            if filled.unbound or filled.unset
            else partial(validate_cp1_stage, store)
        )
        if rules is not None:
            validate = _with_rules(validate, rules, filled.payload)
        journal = store.submit_step(ticket_id, "CP-1", CP1_STEPS, step_id, filled.payload, validate)
        return Submitted(journal, filled.payload, resolved, filled.paths, filled.kinds, None)
    composition = compose_payload(store.pack(), normalised)
    if composition.review is not None and not composition.issues:
        retained = composition.review.model_dump_json()
        return Submitted(
            submit_cp0_review(store, ticket_id, retained), retained, resolved, (), (), composition
        )
    journal = store.submit_step(
        ticket_id,
        "CP-0",
        ("source_readiness",),
        "source_readiness",
        normalised,
        lambda pack, current: _validate_uncomposable(store, pack, current),
    )
    return Submitted(journal, normalised, resolved, (), (), composition)
