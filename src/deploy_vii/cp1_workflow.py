"""Source-first CP-1 submissions in the execution journal; no model calls.

Validated stage outputs are internal handoffs. Module projection and promotion
are separate: completing these stages never accepts CP-1 or CP-MODEL implicitly.
"""

from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from deploy_vii.canonical_audit import DefinitionReview, validate_definition_review
from deploy_vii.context_binding import FinancialContextBinding, validate_financial_context
from deploy_vii.contracts import Contract, Hash, Identifier, Text
from deploy_vii.downstream_readiness import (
    DownstreamInputs,
    DownstreamReview,
    canonical_downstream_readiness,
    downstream_inputs,
    validate_downstream_review,
)
from deploy_vii.execution import Attempt, Execution, StepValidation, current_inputs
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.financial_model import ModelReport, model_report
from deploy_vii.interface_view import write_interface_preview
from deploy_vii.narrative import (
    NarrativeInputs,
    NarrativeReview,
    narrative_inputs,
    validate_narrative_review,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.registry import plan
from deploy_vii.source_context import SourceContextReview, source_context, validate_source_context
from deploy_vii.statement_view import write_statement_preview

CP1_STEPS = ("source_context", "financials", "narrative", "readiness")


class FinancialSubmission(Contract):
    schema_version: Literal["cp1-financial-submission/1"] = "cp1-financial-submission/1"
    context_step_sha256: Hash
    financial: FinancialReview
    definition: DefinitionReview
    binding: FinancialContextBinding
    quarter_ids: tuple[Identifier, ...] | None = None


class FinancialStage(Contract):
    schema_version: Literal["cp1-financial-stage/1"] = "cp1-financial-stage/1"
    narrative_inputs: NarrativeInputs
    model: ModelReport | None
    model_issues: tuple[Text, ...]
    analytical_qualification: Literal["unrun"] = "unrun"


def consumer_entries(pack: PreparedPack) -> tuple[str, ...]:
    """Include selected prerequisites and retain explicitly requested alias rows."""
    selected = plan(pack.run.requested_modules)
    return tuple(
        dict.fromkeys(
            entry
            for entry in (*selected, *pack.run.requested_modules)
            if entry not in {"CP-0", "CP-PARSE", "CP-1"}
        )
    )


def _validate_stage(pack: PreparedPack, attempt: Attempt) -> StepValidation:
    step = attempt.steps[-1]
    try:
        if step.step_id == "source_context":
            context = SourceContextReview.model_validate_json(step.payload)
            issues = validate_source_context(pack, context)
            if issues:
                return StepValidation(issues=issues)
            report = source_context(pack, context)
            return StepValidation(
                output=report.model_dump_json(),
                issues=("CP-1 source gate blocked: no usable assessed financial source",)
                if report.status == "blocked"
                else (),
            )
        context = SourceContextReview.model_validate_json(attempt.steps[0].payload)
        financial = FinancialSubmission.model_validate_json(attempt.steps[1].payload)
    except ValidationError as error:
        return StepValidation(issues=(f"Invalid CP-1 {step.step_id} submission: {error}",))
    if step.step_id == "financials":
        if financial.context_step_sha256 != attempt.steps[0].content_hash():
            return StepValidation(
                issues=("Financial extraction does not bind the retained source step",)
            )
        issues = (
            *validate_financial_context(pack, context, financial.financial, financial.binding),
            *validate_definition_review(pack, financial.financial, financial.definition),
        )
        if issues:
            return StepValidation(issues=tuple(dict.fromkeys(issues)))
        inputs = narrative_inputs(
            pack, context, financial.financial, financial.definition, financial.binding
        )
        output = FinancialStage(
            narrative_inputs=inputs,
            model=model_report(pack, financial.financial, financial.definition.book_id)
            if inputs.ledger.kpis is not None
            else None,
            model_issues=inputs.ledger.calculation_issues,
        )
        return StepValidation(output=output.model_dump_json())
    # These outputs came from trusted Python validation of the already retained
    # responses. Recompute the final artifacts from original contracts below.
    stage_inputs = FinancialStage.model_validate_json(
        attempt.steps[1].output or ""
    ).narrative_inputs
    try:
        narrative = NarrativeReview.model_validate_json(attempt.steps[2].payload)
        readiness = (
            DownstreamReview.model_validate_json(step.payload)
            if step.step_id == "readiness"
            else None
        )
    except ValidationError as error:
        return StepValidation(issues=(f"Invalid CP-1 {step.step_id} submission: {error}",))
    if step.step_id == "narrative":
        issues = validate_narrative_review(stage_inputs, narrative)
        if issues:
            return StepValidation(issues=issues)
        downstream = downstream_inputs(
            pack,
            context,
            financial.financial,
            financial.definition,
            financial.binding,
            narrative,
            consumer_entries(pack),
            quarter_ids=financial.quarter_ids,
        )
        return StepValidation(output=downstream.model_dump_json())
    assert step.step_id == "readiness" and readiness is not None
    prior = DownstreamInputs.model_validate_json(attempt.steps[2].output or "")
    issues = validate_downstream_review(prior, readiness)
    if issues:
        return StepValidation(issues=issues)
    result = canonical_downstream_readiness(
        pack,
        context,
        financial.financial,
        financial.definition,
        financial.binding,
        narrative,
        consumer_entries(pack),
        readiness,
        quarter_ids=financial.quarter_ids,
    )
    return StepValidation(output=result.model_dump_json())


def submit_cp1_step(store: Execution, ticket_id: str, step_id: str, payload: str) -> Attempt:
    """Submit one step or resume its exact retained response after a runtime failure."""
    return store.submit_step(ticket_id, "CP-1", CP1_STEPS, step_id, payload, _validate_stage)


def cp1_statement_preview(
    store: Execution, ticket_id: str, destination: Path, *, include_interface: bool = False
) -> Path:
    """Render only a current, source-gated financial stage; never settle its ticket."""
    snapshot = store.read()
    attempt = next((a for a in snapshot.attempts if a.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != "CP-1" or len(attempt.steps) < 2:
        raise ValueError("CP-1 financial stage is not available")
    prefix = attempt.steps[:2]
    if tuple(s.step_id for s in prefix) != CP1_STEPS[:2] or any(
        s.status != "valid" for s in prefix
    ):
        raise ValueError("CP-1 source and financial stages must be valid")
    if current_inputs(snapshot, "CP-1") != attempt.inputs:
        raise ValueError("CP-1 statement preview inputs are stale")
    verified = _validate_stage(snapshot.pack, attempt.model_copy(update={"steps": prefix}))
    if verified.issues or verified.output != prefix[-1].output:
        raise ValueError("Financial stage differs from trusted recomputation")
    submission = FinancialSubmission.model_validate_json(prefix[-1].payload)
    binding = {
        "snapshot_sha256": snapshot.content_hash(),
        "ticket_id": ticket_id,
        "financial_step_sha256": prefix[-1].content_hash(),
    }
    if include_interface:
        return write_interface_preview(
            snapshot.pack,
            submission.financial,
            submission.definition.book_id,
            destination,
            quarter_ids=submission.quarter_ids,
            execution_binding=binding,
        )
    return write_statement_preview(
        snapshot.pack,
        submission.financial,
        submission.definition.book_id,
        destination,
        execution_binding=binding,
    )
