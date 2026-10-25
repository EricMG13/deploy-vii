"""Trusted source-readiness submission into the resumable execution journal."""

from collections.abc import Sequence

from pydantic import ValidationError

from deploy_vii.contracts import Module
from deploy_vii.execution import (
    Attempt,
    Execution,
    ExecutionSnapshot,
    ExtendReport,
    StepValidation,
    current_inputs,
    settle,
    text_sha256,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import (
    NOT_CONSUMERS,
    ReadinessAddendum,
    ReadinessAddendumContext,
    ReadinessAddendumSubmissionInput,
    ReadinessReview,
    _validate_review_for,
    build_readiness,
    shape_issues,
    validate_review,
)
from deploy_vii.registry import canonical, dependencies, plan


class InvalidReadinessAddendum(ValueError):
    def __init__(self, issues: tuple[str, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(issues))


def _original_review(store: Execution, snapshot: ExecutionSnapshot) -> ReadinessReview:
    head = next((h for h in snapshot.heads if h.module_id == "CP-0"), None)
    if head is None or head.status not in {"accepted", "restricted"}:
        raise ValueError("Source-readiness addendum requires a current settled CP-0")
    attempts = [
        a
        for a in snapshot.attempts
        if a.result_sha256 == head.result_sha256
        and a.module_id == "CP-0"
        and a.status == "finished"
        and not a.issues
    ]
    if len(attempts) != 1:
        raise ValueError("Source-readiness addendum requires the retained producing CP-0 attempt")
    attempt = attempts[0]
    if (
        len(attempt.steps) != 1
        or attempt.steps[0].step_id != "source_readiness"
        or attempt.steps[0].status != "valid"
        or attempt.steps[0].inputs != attempt.inputs
        or attempt.inputs != current_inputs(snapshot, "CP-0")
    ):
        raise ValueError("Source-readiness addendum requires a completed retained CP-0 review")
    pack = store.pack(snapshot)
    outcome = _validate_review(store, pack, attempt)
    if outcome.issues or not outcome.retained_as(attempt.steps[0]) or outcome.output is None:
        raise ValueError("Retained CP-0 output differs from trusted validation")
    if attempt.payload_sha256 is None or store.payload(attempt.payload_sha256) != outcome.output:
        raise ValueError("Retained CP-0 settlement differs from trusted validation")
    candidate = Module.model_validate_json(outcome.output)
    _, recomputed = settle(
        snapshot,
        attempt,
        outcome.output,
        lambda supplied: () if supplied == candidate else ("CP-0 candidate differs",),
        pack=pack,
        load=store.head_module,
    )
    if recomputed != store.head_module(head):
        raise ValueError("Current CP-0 head differs from trusted settlement")
    return ReadinessReview.model_validate_json(store.payload(attempt.steps[0].payload_sha256))


def _addendum_context(
    store: Execution, snapshot: ExecutionSnapshot, extended: tuple[str, ...], added: tuple[str, ...]
) -> ReadinessAddendumContext:
    original = _original_review(store, snapshot)
    head = next(h for h in snapshot.heads if h.module_id == "CP-0")
    active = [
        store.readiness_addendum(ref)
        for ref in snapshot.readiness_addenda
        if ref.pack_sha256 == snapshot.pack_sha256 and ref.cp0_result_sha256 == head.result_sha256
    ]
    return ReadinessAddendumContext(
        pack_sha256=snapshot.pack_sha256,
        cp0_result_sha256=head.result_sha256,
        base_requested_modules=snapshot.run.requested_modules,
        target_requested_modules=extended,
        added_modules=added,
        original_review=original,
        previous_addenda=tuple(a.content_hash() for a in active),
        prior_consumers=tuple(c for a in active for c in a.consumers),
        prior_gaps=tuple(g for a in active for g in a.gaps),
        prior_analysis=tuple(c for a in active for c in a.analysis),
    )


def cp0_addendum_context(store: Execution, requested: Sequence[str]) -> ReadinessAddendumContext:
    """Derive the assessment binding under the journal lock; submission rechecks it there."""
    with store._locked():
        snapshot = store.read()
        if any(a.status == "pending" for a in snapshot.attempts):
            raise ValueError("Cannot change scope while an attempt is pending")
        wanted = tuple(dict.fromkeys(canonical(m) for m in requested))
        old = snapshot.run.requested_modules
        held = {canonical(m) for m in old}
        if not held <= set(wanted):
            raise ValueError("Scope only extends; create a new execution to remove modules")
        if set(wanted) == held:
            raise ValueError("Source-readiness addendum requires an extended scope")
        extended = (*old, *(m for m in wanted if m not in held))
        added = tuple(m for m in plan(extended) if m not in dependencies(old))
        return _addendum_context(store, snapshot, extended, added)


def _check_addendum(
    pack: PreparedPack, context: ReadinessAddendumContext, payload: str
) -> ReadinessAddendum:
    from deploy_vii.live.submission import compose_addendum

    composed = compose_addendum(pack, context, payload)
    if composed.review is None:
        raise InvalidReadinessAddendum(composed.issues)
    review = composed.review
    original = context.original_review
    consumers = review.consumers[len(original.consumers) + len(context.prior_consumers) :]
    gaps = review.gaps[len(original.gaps) + len(context.prior_gaps) :]
    analysis = review.analysis[len(original.analysis) + len(context.prior_analysis) :]
    expected = tuple(m for m in plan(context.target_requested_modules) if m not in NOT_CONSUMERS)
    added = tuple(m for m in context.added_modules if m not in NOT_CONSUMERS)
    issues = [*composed.issues, *_validate_review_for(pack, review, expected)]
    if len(consumers) != len(added) or {c.module_id for c in consumers} != set(added):
        issues.append("Assess every added canonical live consumer exactly once")
    if any(not set(g.affected_modules) <= set(added) for g in gaps):
        issues.append("Addendum gaps may affect only newly added consumers")
    if issues:
        raise InvalidReadinessAddendum(tuple(dict.fromkeys(issues)))
    return ReadinessAddendum(
        context=context,
        payload_sha256=text_sha256(payload),
        consumers=consumers,
        gaps=gaps,
        analysis=analysis,
    )


def submit_cp0_addendum(
    store: Execution, requested: Sequence[str], payload: str, *, context_sha256: str
) -> ExtendReport:
    """Administrative import and extension in one locked transition; never a CP-0 attempt."""
    return store.extend_scope(
        requested,
        readiness_addendum=ReadinessAddendumSubmissionInput(
            payload=payload,
            context_sha256=context_sha256,
        ),
    )


def _validate_review(store: Execution, pack: PreparedPack, attempt: Attempt) -> StepValidation:
    try:
        review = ReadinessReview.model_validate_json(store.payload(attempt.steps[0].payload_sha256))
    except ValidationError as error:
        return StepValidation(issues=shape_issues(error))
    issues = validate_review(pack, review)
    if issues:
        return StepValidation(issues=issues)
    candidate = build_readiness(pack, review, attempt=attempt.number)
    usable = any(
        source.status == "ready" and assessment.fidelity != "blocked"
        for source in pack.sources
        for assessment in review.sources
        if source.source_id == assessment.source_id
    )
    return StepValidation(
        output=candidate.model_dump_json(),
        issues=("No usable identity-confirmed evidence for the requested work",)
        if not usable or not review.issuer_confirmed
        else (),
    )


def submit_cp0_review(store: Execution, ticket_id: str, payload: str) -> Attempt:
    """Validate raw review, then promote only its exact Python-built candidate.

    A crash between the two journal writes resumes from the retained valid step.
    Structural acceptance is not analytical or browser qualification.
    """
    attempt = next((a for a in store.read().attempts if a.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != "CP-0" or attempt.status != "pending":
        raise ValueError("Ticket is absent, finished or belongs to another module")
    if attempt.steps and attempt.steps[0].payload_sha256 != text_sha256(payload):
        raise ValueError("Ticket already retains a different response; resume or interrupt")
    if not attempt.steps or attempt.steps[0].status == "pending":
        attempt = store.submit_step(
            ticket_id,
            "CP-0",
            ("source_readiness",),
            "source_readiness",
            payload,
            lambda pack, current: _validate_review(store, pack, current),
        )
    if attempt.status == "finished":
        return attempt
    if len(attempt.steps) != 1 or attempt.steps[0].step_id != "source_readiness":
        raise ValueError("Retained steps do not match CP-0")
    # Recompute rather than treating stored or caller-supplied output as authority.
    outcome = _validate_review(store, store.pack(), attempt)
    if outcome.issues or not outcome.retained_as(attempt.steps[0]):
        raise ValueError("Retained CP-0 output differs from trusted validation")
    candidate = Module.model_validate_json(outcome.output or "")
    return store.finish(
        ticket_id,
        candidate.model_dump_json(),
        lambda supplied: () if supplied == candidate else ("CP-0 candidate differs",),
    )
