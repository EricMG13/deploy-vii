"""Trusted source-readiness submission into the resumable execution journal."""

from pydantic import ValidationError

from deploy_vii.contracts import Module
from deploy_vii.execution import Attempt, Execution, StepValidation
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import ReadinessReview, build_readiness, validate_review


def _validate_review(pack: PreparedPack, attempt: Attempt) -> StepValidation:
    try:
        review = ReadinessReview.model_validate_json(attempt.steps[0].payload)
    except ValidationError as error:
        return StepValidation(issues=(f"Invalid CP-0 review: {error}",))
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
    if attempt.steps and attempt.steps[0].payload != payload:
        raise ValueError("Ticket already retains a different response; resume or interrupt")
    if not attempt.steps or attempt.steps[0].status == "pending":
        attempt = store.submit_step(
            ticket_id, "CP-0", ("source_readiness",), "source_readiness", payload, _validate_review
        )
    if attempt.status == "finished":
        return attempt
    if len(attempt.steps) != 1 or attempt.steps[0].step_id != "source_readiness":
        raise ValueError("Retained steps do not match CP-0")
    # Recompute rather than treating stored or caller-supplied output as authority.
    outcome = _validate_review(store.read().pack, attempt)
    if outcome.issues or outcome.output != attempt.steps[0].output:
        raise ValueError("Retained CP-0 output differs from trusted validation")
    candidate = Module.model_validate_json(outcome.output or "")
    return store.finish(
        ticket_id,
        candidate.model_dump_json(),
        lambda supplied: () if supplied == candidate else ("CP-0 candidate differs",),
    )
