"""Source-first CP-1 submissions in the execution journal; no model calls.

Validated stage outputs are internal handoffs. Completing the four stages never accepts
CP-1 or CP-MODEL implicitly; only `promote_cp1` (a QA review plus a verified canonical
handoff, task 6.4) settles CP-1.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from deploy_vii.canonical_audit import DefinitionReview, validate_definition_review
from deploy_vii.canonical_tables import REGISTER_NOTE, CanonicalTables, canonical_tables
from deploy_vii.context_binding import FinancialContextBinding, validate_financial_context
from deploy_vii.contracts import Contract, Hash, Identifier, Module, Text
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.downstream_readiness import (
    DownstreamInputs,
    DownstreamReview,
    canonical_downstream_readiness,
    downstream_inputs,
    validate_downstream_review,
)
from deploy_vii.envelope import (
    Envelope,
    EnvelopeError,
    envelope_issues,
    read_envelope,
    write_envelope,
)
from deploy_vii.execution import (
    Attempt,
    Execution,
    ExecutionSnapshot,
    Qualification,
    StepValidation,
    current_inputs,
    text_sha256,
)
from deploy_vii.financial_contracts import PREFILLED_MARKER, FinancialReview
from deploy_vii.financial_model import ModelReport, model_report
from deploy_vii.interface_view import write_interface_preview
from deploy_vii.narrative import (
    NarrativeInputs,
    NarrativeReview,
    narrative_inputs,
    validate_narrative_review,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.quality import QualityReport, QualityReview, assess_quality, validate_quality_review
from deploy_vii.readiness import shape_issues
from deploy_vii.registry import plan
from deploy_vii.source_context import SourceContextReview, source_context, validate_source_context
from deploy_vii.statement_view import write_statement_preview

CP1_STEPS = ("source_context", "financials", "narrative", "readiness")
# Promotion retains the QA review as one more step of the same attempt and repair budget.
CP1_PROMOTION = (*CP1_STEPS, "quality")


class FinancialSubmission(Contract):
    schema_version: Literal["cp1-financial-submission/1"] = "cp1-financial-submission/1"
    # Task 7.0i: Python fills it from the retained source step (`live.submission`); never sent.
    context_step_sha256: Hash = Field(json_schema_extra={PREFILLED_MARKER: True})
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


def _validate_stage(store: Execution, pack: PreparedPack, attempt: Attempt) -> StepValidation:
    step = attempt.steps[-1]

    def text(index: int, *, output: bool = False) -> str:
        retained = attempt.steps[index]
        if output:
            if retained.output_sha256 is None:
                raise ValueError(f"Step {retained.step_id} retains no output")
            return store.step_output(retained.output_sha256)
        return store.payload(retained.payload_sha256)

    try:
        if step.step_id == "source_context":
            context = SourceContextReview.model_validate_json(text(-1))
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
        context = SourceContextReview.model_validate_json(text(0))
        financial = FinancialSubmission.model_validate_json(text(1))
    except ValidationError as error:
        return StepValidation(issues=shape_issues(error))
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
    stage_inputs = FinancialStage.model_validate_json(text(1, output=True)).narrative_inputs
    try:
        narrative = NarrativeReview.model_validate_json(text(2))
        readiness = (
            DownstreamReview.model_validate_json(text(-1)) if step.step_id == "readiness" else None
        )
    except ValidationError as error:
        return StepValidation(issues=shape_issues(error))
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
    prior = DownstreamInputs.model_validate_json(text(2, output=True))
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
    return store.submit_step(
        ticket_id,
        "CP-1",
        CP1_STEPS,
        step_id,
        payload,
        lambda pack, attempt: _validate_stage(store, pack, attempt),
    )


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
    pack = store.pack(snapshot)
    verified = _validate_stage(store, pack, attempt.model_copy(update={"steps": prefix}))
    if verified.issues or not verified.retained_as(prefix[-1]):
        raise ValueError("Financial stage differs from trusted recomputation")
    submission = FinancialSubmission.model_validate_json(store.payload(prefix[-1].payload_sha256))
    binding = {
        "snapshot_sha256": snapshot.content_hash(),
        "ticket_id": ticket_id,
        "financial_step_sha256": prefix[-1].content_hash(),
    }
    if include_interface:
        return write_interface_preview(
            pack,
            submission.financial,
            submission.definition.book_id,
            destination,
            quarter_ids=submission.quarter_ids,
            execution_binding=binding,
        )
    return write_statement_preview(
        pack,
        submission.financial,
        submission.definition.book_id,
        destination,
        execution_binding=binding,
    )


def _stage_registers(store: Execution, pack: PreparedPack, attempt: Attempt) -> CanonicalTables:
    """Recompute every retained stage prefix, then the canonical registers from the raw reviews.

    A retained output that differs from its trusted recomputation fails closed (raises).
    """
    stages = attempt.steps[: len(CP1_STEPS)]
    if tuple(s.step_id for s in stages) != CP1_STEPS or any(s.status != "valid" for s in stages):
        raise ValueError("All CP-1 source, financial, narrative and readiness stages must be valid")
    for index, step in enumerate(stages, 1):
        verified = _validate_stage(
            store, pack, attempt.model_copy(update={"steps": stages[:index]})
        )
        if verified.issues or not verified.retained_as(step):
            raise ValueError(f"{step.step_id} stage differs from trusted recomputation")
        del verified
    payloads = [store.payload(step.payload_sha256) for step in stages]
    financial = FinancialSubmission.model_validate_json(payloads[1])
    return canonical_tables(
        pack,
        SourceContextReview.model_validate_json(payloads[0]),
        financial.financial,
        financial.definition,
        financial.binding,
        NarrativeReview.model_validate_json(payloads[2]),
        consumer_entries(pack),
        DownstreamReview.model_validate_json(payloads[3]),
        quarter_ids=financial.quarter_ids,
    )


def _current_attempt(store: Execution, ticket_id: str) -> tuple[ExecutionSnapshot, Attempt]:
    snapshot = store.read()
    attempt = next((a for a in snapshot.attempts if a.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != "CP-1":
        raise ValueError("CP-1 attempt is not available")
    if current_inputs(snapshot, "CP-1") != attempt.inputs:
        raise ValueError("CP-1 attempt inputs are stale")
    return snapshot, attempt


def cp1_registers(store: Execution, ticket_id: str) -> CanonicalTables:
    """The trusted canonical registers of one CP-1 attempt (every stage recomputed first).

    An analyst prepares the QA review from `cp1_quality_inputs` of these registers.
    """
    snapshot, attempt = _current_attempt(store, ticket_id)
    return _stage_registers(store, store.pack(snapshot), attempt)


def cp1_register_preview(store: Execution, ticket_id: str, destination: Path) -> Path:
    """Recompute every retained stage before projecting a complete register candidate."""
    from deploy_vii.register_view import write_register_preview

    snapshot, attempt = _current_attempt(store, ticket_id)
    pack = store.pack(snapshot)
    report = _stage_registers(store, pack, attempt)
    return write_register_preview(
        pack,
        report,
        destination,
        execution_binding={
            "snapshot_sha256": snapshot.content_hash(),
            "ticket_id": ticket_id,
            "readiness_step_sha256": attempt.steps[len(CP1_STEPS) - 1].content_hash(),
        },
    )


# --- Promotion (task 6.4): QA review, verified canonical handoff, M4 settlement --------------


class CP1Handoff(Contract):
    """The retained output of the `quality` step: what the verified handoff bound."""

    schema_version: Literal["cp1-handoff/1"] = "cp1-handoff/1"
    registers_sha256: Hash
    quality: QualityReport
    gap_limitations: tuple[Text, ...]
    candidate_sha256: Hash
    envelope_sha256: Hash
    sidecar_sha256: Hash


# The four statuses a promotion records on the CP-1 head (plan: "four statuses per module").
PROMOTED = Qualification(implementation="implemented")


def _candidate(registers: CanonicalTables, attempt: Attempt, quality: QualityReport) -> Module:
    """The promoted CP-1 candidate: the registers' module bound to the journal attempt.

    Own limitations drop the register note and, unless QA passed, gain a QA line, so the M4
    rule (own findings restrict) settles the status. Promotion itself is not a finding: the
    head's four statuses record that qualification is unrun, so `accepted` stays reachable.
    """
    module = registers.module
    if REGISTER_NOTE not in module.limitations:
        raise ValueError("Canonical registers do not carry their register note")
    confidence = quality.confidence
    qa = (
        ()
        if confidence.qa_status == "Passed"
        else (
            f"CP-1 QA {confidence.qa_status}: confidence {confidence.confidence_score} "
            f"({confidence.confidence_band})",
        )
    )
    rest = tuple(text for text in module.limitations if text != REGISTER_NOTE)
    return Module.model_validate_json(
        module.model_copy(
            update={
                "inputs": (*attempt.inputs, *module.inputs),
                "attempt": attempt.number,
                "status": "candidate",
                "limitations": (*qa, *rest),
            }
        ).model_dump_json()
    )


def _quality_stage(
    store: Execution, pack: PreparedPack, attempt: Attempt
) -> tuple[StepValidation, Module | None]:
    """Validate the QA review and the promoted handoff; issues refuse promotion by status.

    Promotion needs every condition: the four stages recompute, the review binds the current
    QA inputs and keeps every lineage within its ceiling, QA is not Blocked, the registers'
    envelope verified (the `canonical-handoff` slot), and the promoted envelope, with QA and
    the journal binding, round-trips. CP-0's `Run CP-1` is checked by the journal itself.
    """
    registers = _stage_registers(store, pack, attempt)
    try:
        review = QualityReview.model_validate_json(
            store.payload(attempt.steps[len(CP1_STEPS)].payload_sha256)
        )
    except ValidationError as error:
        return StepValidation(issues=shape_issues(error)), None
    inputs = cp1_quality_inputs(registers)
    issues = list(validate_quality_review(inputs, review))
    slot = next(f for f in inputs.coverage if f.field_id == "canonical-handoff")
    if not slot.present:
        issues.append(f"Canonical handoff does not verify: {slot.rationale}")
    if issues:
        return StepValidation(issues=tuple(issues)), None
    quality = assess_quality(inputs, review)
    confidence = quality.confidence
    if confidence.qa_status == "Blocked":
        blocked = (
            f"CP-1 QA Blocked: confidence {confidence.confidence_score} "
            f"({confidence.confidence_band}); a Blocked handoff is not promoted"
        )
        return StepValidation(issues=(blocked,)), None
    candidate = _candidate(registers, attempt, quality)
    ledger = registers.downstream.inputs.narrative.inputs.ledger
    envelope = Envelope(
        run=pack.run,
        module=candidate,
        registers_sha256=registers.content_hash(),
        gap_limitations=ledger.limitations,
        quality=quality,
        journal=attempt.inputs,
    )
    try:
        markdown, sidecar = write_envelope(envelope)
    except ValueError as error:
        return StepValidation(issues=(f"Canonical envelope cannot be written: {error}",)), None
    if found := envelope_issues(markdown, sidecar):
        failed = tuple(f"Canonical handoff verification failed: {issue}" for issue in found)
        return StepValidation(issues=failed), None
    handoff = CP1Handoff(
        registers_sha256=envelope.registers_sha256,
        quality=quality,
        gap_limitations=envelope.gap_limitations,
        candidate_sha256=candidate.content_hash(),
        envelope_sha256=text_sha256(markdown),
        sidecar_sha256=text_sha256(sidecar),
    )
    return StepValidation(output=handoff.model_dump_json()), candidate


def promote_cp1(store: Execution, ticket_id: str, payload: str) -> Attempt:
    """Retain a QA review as the `quality` step, then settle only its verified candidate.

    Mirrors `submit_cp0_review`: a crash between the step and the settlement resumes from the
    retained valid step. An invalid review or a handoff that does not verify finishes the
    attempt (rejected, or blocked on the repair) and never promotes. Settlement follows the M4
    status rules; a promoted head records the four statuses.
    """
    attempt = next((a for a in store.read().attempts if a.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != "CP-1" or attempt.status != "pending":
        raise ValueError("Ticket is absent, finished or belongs to another module")
    quality = len(CP1_STEPS)
    retained = attempt.steps[quality] if len(attempt.steps) > quality else None
    if retained is not None and retained.payload_sha256 != text_sha256(payload):
        raise ValueError("Ticket already retains a different QA review; resume or interrupt")
    validated: list[tuple[StepValidation, Module | None]] = []

    def validate(pack: PreparedPack, current: Attempt) -> StepValidation:
        validated.append(_quality_stage(store, pack, current))
        return validated[-1][0]

    if retained is None or retained.status == "pending":
        attempt = store.submit_step(ticket_id, "CP-1", CP1_PROMOTION, "quality", payload, validate)
    if attempt.status == "finished":
        return attempt
    # A resumed step is recomputed rather than trusting its retained output; a step validated
    # in this call already is that recomputation. Either way the retained output must match.
    outcome, candidate = (
        validated[-1] if validated else _quality_stage(store, store.pack(), attempt)
    )
    if outcome.issues or candidate is None or not outcome.retained_as(attempt.steps[quality]):
        raise ValueError("Retained CP-1 handoff differs from trusted validation")
    return store.finish(
        ticket_id,
        candidate.model_dump_json(),
        lambda supplied: (
            () if supplied == candidate else ("CP-1 candidate differs from its verified handoff",)
        ),
        qualification=PROMOTED,
    )


def write_cp1_envelope(store: Execution, destination: Path) -> Path:
    """Write the promoted CP-1 head's canonical envelope, verified before any file is written.

    Files: `envelope.md`, `envelope.json` (the typed sidecar) and a last-written receipt
    `complete.json` (`cp1-envelope/1`). An existing directory is refused.
    """
    snapshot = store.read()
    head = next((h for h in snapshot.heads if h.module_id == "CP-1"), None)
    if head is None or head.status not in ("accepted", "restricted"):
        raise ValueError("CP-1 has no accepted or restricted head")
    attempt = next((a for a in snapshot.attempts if a.result_sha256 == head.result_sha256), None)
    quality = len(CP1_STEPS)
    step = attempt.steps[quality] if attempt and len(attempt.steps) > quality else None
    if attempt is None or step is None or step.step_id != "quality" or step.output_sha256 is None:
        raise ValueError("CP-1 head was not promoted through a verified handoff")
    handoff = CP1Handoff.model_validate_json(store.step_output(step.output_sha256))
    envelope = Envelope(
        run=snapshot.run,
        module=store.head_module(head),
        registers_sha256=handoff.registers_sha256,
        gap_limitations=handoff.gap_limitations,
        quality=handoff.quality,
        journal=attempt.inputs,
    )
    markdown, sidecar = write_envelope(envelope)
    if issues := envelope_issues(markdown, sidecar):
        raise EnvelopeError(issues)
    payloads = {"envelope.md": markdown, "envelope.json": sidecar}
    receipt = {
        "schema_version": "cp1-envelope/1",
        "module_sha256": head.result_sha256,
        "snapshot_sha256": snapshot.content_hash(),
        "ticket_id": attempt.ticket_id,
        "pack_sha256": snapshot.pack_sha256,
        "registers_sha256": handoff.registers_sha256,
        "quality_report_sha256": handoff.quality.content_hash(),
        "status": head.status,
        "qualification": None
        if head.qualification is None
        else head.qualification.model_dump(mode="json"),
        "files": {name: text_sha256(raw) for name, raw in payloads.items()},
    }
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        (destination / name).write_text(raw, encoding="utf-8")
    (destination / "complete.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return destination / "envelope.md"


# --- Reading an exported envelope back (task 6.5): the first downstream consumer ------------


class EnvelopeRefused(ValueError):
    """An exported CP-1 envelope that does not verify against the journal; ``issues`` says why."""

    def __init__(self, issues: tuple[str, ...]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


_EXPORTED_FILES = ("envelope.md", "envelope.json")


def cp1_binding_issues(
    envelope: Envelope, receipt: dict[str, object], snapshot: ExecutionSnapshot
) -> tuple[str, ...]:
    """What ties a verified envelope to the journal that promoted it.

    `read_envelope` checks the Markdown only against its own sidecar, so a consistently
    rewritten pair passes it. The pair is genuine only when its module is the CP-1 head's
    settled blob, built on the journal's run and prepared pack, with the head's status, and
    when the receipt records the same hashes, QA report and statuses.
    """
    head = next((h for h in snapshot.heads if h.module_id == "CP-1"), None)
    if head is None or head.status not in ("accepted", "restricted"):
        return ("CP-1 has no accepted or restricted head in the journal",)
    issues: list[str] = []
    if envelope.run != snapshot.run:
        issues.append("Envelope run differs from the journal's run")
    if envelope.pack_sha256 != snapshot.pack_sha256:
        issues.append("Envelope pack differs from the journal's prepared pack")
    if envelope.module.content_hash() != head.result_sha256:
        issues.append("Envelope module is not the CP-1 head's settled module")
    if envelope.module.status != head.status:
        issues.append("Envelope status differs from the CP-1 head")
    qualification = (
        None if head.qualification is None else head.qualification.model_dump(mode="json")
    )
    quality = None if envelope.quality is None else envelope.quality.content_hash()
    expected: dict[str, object] = {
        "schema_version": "cp1-envelope/1",
        "module_sha256": head.result_sha256,
        "pack_sha256": snapshot.pack_sha256,
        "registers_sha256": envelope.registers_sha256,
        "quality_report_sha256": quality,
        "status": head.status,
        "qualification": qualification,
    }
    issues.extend(
        f"Receipt {key} does not match the journal"
        for key, value in expected.items()
        if receipt.get(key) != value
    )
    return tuple(issues)


def read_cp1_envelope(store: Execution, directory: Path) -> Envelope:
    """The CP-1 envelope exported to `directory`, verified against the journal; else refused.

    Reads `complete.json`, `envelope.md` and `envelope.json` once, checks the files against the
    receipt's SHA-256 hashes, the Markdown against the sidecar (`read_envelope`) and the pair
    against the journal (`cp1_binding_issues`). Any failure raises `EnvelopeRefused` carrying
    every issue found; nothing partial is returned. The contract comes from the sidecar; the
    Markdown is verified against it, not decoded.
    """
    try:
        receipt = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
        raw = {name: (directory / name).read_text(encoding="utf-8") for name in _EXPORTED_FILES}
    except (OSError, ValueError) as error:  # missing, unreadable or not JSON: nothing to verify
        raise EnvelopeRefused((f"Envelope export cannot be read: {error}",)) from error
    if not isinstance(receipt, dict) or not isinstance(receipt.get("files"), dict):
        raise EnvelopeRefused(("Envelope receipt is not a cp1-envelope receipt",))
    issues = [
        f"{name} differs from the receipt's hash"
        for name, text in raw.items()
        if receipt["files"].get(name) != text_sha256(text)
    ]
    if issues:
        raise EnvelopeRefused(tuple(issues))
    try:
        envelope = read_envelope(raw["envelope.md"], raw["envelope.json"])
    except EnvelopeError as error:
        raise EnvelopeRefused(error.issues) from error
    if issues := list(cp1_binding_issues(envelope, receipt, store.read())):
        raise EnvelopeRefused(tuple(issues))
    return envelope
