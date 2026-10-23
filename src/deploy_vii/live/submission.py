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
  narrative step's `DownstreamInputs`.

A value the payload carries is overwritten. A payload already holding every right value is kept
byte for byte and nothing is recorded; otherwise it is rewritten (`live.schema.exact_json`,
numbers keep their digits) and every changed JSON path is recorded in `Submitted.prefilled`. A
binding Python cannot know (an unknown source, facility or observation, or a sub-object that does
not parse) is left as sent, so the existing shape or validator rejection stands; so is a payload
that is not a JSON object or cannot be stored as UTF-8. A missing retained step raises ValueError
before anything is written. The validators' binding checks are unchanged.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from deploy_vii.business_context import BusinessContextSubmission, submit_cp1a_step
from deploy_vii.contracts import Contract
from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.cp1_workflow import FinancialStage, FinancialSubmission, submit_cp1_step
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview
from deploy_vii.execution import Attempt, Execution, StepSubmission, StepValidation
from deploy_vii.financial_contracts import FacilityObservation, FinancialBook, FinancialReview
from deploy_vii.live.schema import Marked, exact_json, json_object, marked_fields, normalise
from deploy_vii.narrative import NarrativeReview
from deploy_vii.preparation import PreparedPack
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
from deploy_vii.source_context import SourceContextReview
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


STEPS: Mapping[str, StepDef] = {
    "source_readiness": StepDef("CP-0", ReadinessSubmission),
    "source_context": StepDef("CP-1", SourceContextReview),
    "financials": StepDef("CP-1", FinancialSubmission),
    "narrative": StepDef("CP-1", NarrativeReview),
    "readiness": StepDef("CP-1", DownstreamReview),
    # Task 7.2: the stored shape is the submission itself; Python composes the registers as the
    # step output (`business_context.submit_cp1a_step`), so no composer is needed here.
    "business_context": StepDef("CP-1A", BusinessContextSubmission),
}
# Task 7.0i: the model supplies no hash. Each hash binding of a CP-1 step contract is marked
# `PREFILLED_MARKER` with its kind (so the sent schema leaves it out), and Python fills it before
# the journal validates. Per step: the kinds it carries, and the retained steps they come from.
PREFILLED: Mapping[str, frozenset[str]] = {
    "source_context": frozenset({"pack", "source"}),
    "financials": frozenset(
        {
            "context-step",
            "pack",
            "source",
            "source-context-review",
            "facility",
            "annual-observation",
            "quarter-observations",
            "financial-review",
        }
    ),
    "narrative": frozenset({"step-inputs"}),
    "readiness": frozenset({"step-inputs"}),
}
BOUND_STEPS: Mapping[str, tuple[str, ...]] = {
    "source_context": (),
    "financials": ("source_context",),
    "narrative": ("source_context", "financials"),
    "readiness": ("source_context", "financials", "narrative"),
}
# Fill order: a phase reads only values that are sent or that earlier phases wrote (a facility
# row and an observation hash cover their citations; the financial review hash covers them all).
PHASES = (
    frozenset({"context-step", "pack", "source", "source-context-review", "step-inputs"}),
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
    the pack's hash, each ready source's hash and the step-level kinds (`STEP_KINDS`)."""

    pack_sha256: str
    sources: Mapping[str, str]
    step: Mapping[str, str]


def _held_output(store: Execution, step: StepSubmission) -> str:
    if step.output_sha256 is None:  # a valid step always retains its output (StepSubmission)
        raise ValueError(f"Step {step.step_id} retains no output")
    return store.step_output(step.output_sha256)


def known_bindings(store: Execution, ticket_id: str, step_id: str) -> Known:
    """What `prefill` writes for `step_id` on this ticket: exactly the values the step's
    validators compare against (`cp1_workflow._validate_stage`, `validate_source_context`,
    `validate_financial_context`, `validate_definition_review`, the narrative and downstream
    validators). Raises ValueError when a step the bindings come from is not retained valid."""
    snapshot = store.read()
    attempt = next((a for a in snapshot.attempts if a.ticket_id == ticket_id), None)
    held = attempt.steps if attempt is not None else ()
    for index, wanted in enumerate(BOUND_STEPS[step_id]):
        if len(held) <= index or held[index].step_id != wanted or held[index].status != "valid":
            raise ValueError(f"Ticket {ticket_id} retains no valid {wanted} step to bind")
    pack = store.pack(snapshot)
    step: dict[str, str] = {}
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
    return Known(
        pack_sha256=pack.content_hash(),
        sources={s.source_id: s.sha256 for s in pack.sources if s.status == "ready" and s.sha256},
        step=step,
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


class _Resolver:
    """The value of one marked binding (None when Python cannot know it from what was sent)."""

    def __init__(self, known: Known, document: dict[str, Any]) -> None:
        self.known = known
        self.document = document
        self.observations: dict[int, dict[tuple[str, str], str] | None] = {}

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
            return self.known.sources.get(source_id) if isinstance(source_id, str) else None
        if kind in self.known.step:
            return self.known.step[kind]
        if kind == "financial-review":
            return self.financial_review
        book = item.enclosing("FinancialBook")
        if book is None:
            return None
        if kind == "facility":
            # `fx_conversion_issues` keys rows by (facility_id, period_id); the last one wins.
            scope = holder.get("facility_id"), holder.get("period_id")
            rows = book.get("facilities")
            matches = [
                row
                for row in (rows if isinstance(rows, list) else ())
                if isinstance(row, dict) and (row.get("facility_id"), row.get("period_id")) == scope
            ]
            return _parsed_hash(FacilityObservation, matches[-1]) if matches else None
        hashes = self._observations(book)
        metric = holder.get("metric_id")
        annual = holder.get("annual_period_id")
        quarters = holder.get("quarter_period_ids")
        if hashes is None or not isinstance(metric, str):
            return None
        if kind == "annual-observation":
            return hashes.get((annual, metric)) if isinstance(annual, str) else None
        if kind != "quarter-observations":
            raise ValueError(f"No pre-fill for the marked binding kind {kind!r}")
        if not (isinstance(quarters, list) and all(isinstance(q, str) for q in quarters)):
            return None
        found = [hashes.get((quarter, metric)) for quarter in quarters]
        return found if all(found) else None

    def _observations(self, book: dict[str, Any]) -> dict[tuple[str, str], str] | None:
        """`audit_explanation_issues`' observation hashes for this book: each effective account
        value by (period, metric), the last one winning. The explanations themselves are not
        parsed (effective accounts read only accounts and statement lines)."""
        if id(book) not in self.observations:
            try:
                parsed = FinancialBook.model_validate_json(
                    exact_json({**book, "audit_basis_explanations": []})
                )
            except ValidationError:
                self.observations[id(book)] = None
            else:
                self.observations[id(book)] = {
                    (row.period_id, row.metric_id): row.value.content_hash()
                    for row in effective_accounts(parsed)
                }
        return self.observations[id(book)]


def prefill(
    model: type[BaseModel], payload: str, known: Known, kinds: frozenset[str]
) -> tuple[str, tuple[str, ...]]:
    """`payload` with every marked binding (`live.schema.marked_fields`) set to the value Python
    knows, in `PHASES` order, and the JSON paths that changed. Unchanged (same string, no paths)
    when every value is already right, when the payload is not a JSON object or cannot be stored
    as UTF-8 (a lone surrogate escape, which Pydantic refuses as invalid JSON); a binding Python
    cannot know (an unknown source or facility, a sub-object that does not parse) is left as
    sent for the validators. A marked kind outside `kinds` raises ValueError (nothing fills
    it)."""
    document = json_object(payload)
    if document is None:
        return payload, ()
    try:
        exact_json(document).encode()
    except UnicodeEncodeError:
        return payload, ()
    marked = marked_fields(model, document)
    unknown = sorted({item.kind for item in marked} - kinds)
    if unknown:
        raise ValueError(f"No pre-fill for the marked binding kinds {unknown}")
    resolve = _Resolver(known, document)
    changed: list[str] = []
    for phase in PHASES:
        for item in marked:
            if item.kind not in phase:
                continue
            value = resolve(item)
            if value is not None and item.holder.get(item.name) != value:
                item.holder[item.name] = value
                changed.append(item.path)
    if not changed:
        return payload, ()
    return exact_json(document), tuple(changed)


@dataclass(frozen=True)
class Submitted:
    journal: Attempt
    payload: str  # what the journal step retains: composed, pre-filled or as received
    nulls_resolved: tuple[str, ...]
    prefilled: tuple[str, ...]  # JSON paths of the bindings Python set (task 7.0i)
    composition: Composition | None  # source_readiness only


def submit_model_payload(
    store: Execution,
    ticket_id: str,
    step_id: str,
    payload: str,
    *,
    on_normalised: Callable[[tuple[str, ...]], None] | None = None,
) -> Submitted:
    """Enter one model payload (pool or proxy cohort) into the journal for `step_id`.

    Nulls standing for omitted defaults are resolved first (`live.schema.normalise`, against the
    model-facing schema). `on_normalised` sees the resolved paths before the journal does, so a
    caller can record them even if validation raises. Then `financials` gets its pre-filled
    binding (`prefill`; see the module docstring)."""
    step = STEPS[step_id]
    normalised, resolved = normalise(step.schema, payload)
    if on_normalised is not None:
        on_normalised(resolved)
    if step.module_id == "CP-1A":
        journal = submit_cp1a_step(store, ticket_id, step_id, normalised)
        return Submitted(journal, normalised, resolved, (), None)
    if step_id != "source_readiness":
        known = known_bindings(store, ticket_id, step_id)
        normalised, filled = prefill(step.schema, normalised, known, PREFILLED[step_id])
        journal = submit_cp1_step(store, ticket_id, step_id, normalised)
        return Submitted(journal, normalised, resolved, filled, None)
    composition = compose_payload(store.pack(), normalised)
    if composition.review is not None and not composition.issues:
        retained = composition.review.model_dump_json()
        return Submitted(
            submit_cp0_review(store, ticket_id, retained), retained, resolved, (), composition
        )
    journal = store.submit_step(
        ticket_id,
        "CP-0",
        ("source_readiness",),
        "source_readiness",
        normalised,
        lambda pack, current: _validate_uncomposable(store, pack, current),
    )
    return Submitted(journal, normalised, resolved, (), composition)
