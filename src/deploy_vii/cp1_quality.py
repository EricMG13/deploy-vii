"""Producer-owned CP-1 QA scope, before final canonical handoff and acceptance."""

from typing import Literal

from deploy_vii.calculation_trace import Computation
from deploy_vii.canonical_audit import DefinitionReview, SourcePosition
from deploy_vii.canonical_kpis import CanonicalKpi
from deploy_vii.canonical_tables import CanonicalTables, canonical_tables
from deploy_vii.context_binding import FinancialContextBinding
from deploy_vii.contracts import Contract
from deploy_vii.downstream_readiness import DownstreamReview
from deploy_vii.envelope import handoff_issues, register_envelope
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.financial_model import ModelValue
from deploy_vii.financial_periods import HistoricalValue, _id
from deploy_vii.narrative import (
    _DIMENSIONS,
    EvidencePart,
    EvidenceRecord,
    NarrativeReport,
    NarrativeReview,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.quality import (
    ClaimCandidate,
    CoverageField,
    EvidenceCeiling,
    LineageBasis,
    ModuleStatus,
    QualityInputs,
    QualityReport,
    QualityReview,
    SourceGate,
    assess_quality,
)
from deploy_vii.source_context import SourceContextReview, SourceRegisterRow
from deploy_vii.statement_output import StatementCell

REQUIRED_TABLES = tuple(f"T4.{i}" for i in range(1, 20) if i != 7)
# MC-5 register table over the narrative catalogue kinds (narrative._catalogue).
_CITED = frozenset(
    {"source", "entity", "subsequent_event", "source_period", "definition", "multi_figure_event"}
)
_LOCATED = frozenset({"observation", "statement_IS", "statement_CFS", "statement_BS"})
_CALCULATED = frozenset({"normalization", "source_check", "period_check", "construction", "basis"})
_VALUED: dict[str, type[HistoricalValue | ModelValue | CanonicalKpi | Computation]] = {
    "historical_value": HistoricalValue,
    "canonical_value": ModelValue,
    "kpi": CanonicalKpi,
    "computation": Computation,
}
_SETTLED = frozenset({"known", "not_applicable"})
# An estimated or proxied figure is assumption-based by definition (coordinator ruling, 6.3).
_ESTIMATED = frozenset({"Estimated", "Proxy"})


class CP1QualityReport(Contract):
    schema_version: Literal["cp1-quality/1"] = "cp1-quality/1"
    scope: Literal["pre_handoff"] = "pre_handoff"
    registers: CanonicalTables
    inputs: QualityInputs
    quality: QualityReport


def _module_status(narrative: NarrativeReport) -> ModuleStatus:
    """Own findings only (decision 0007): limitations inherited from inputs never restrict."""
    if narrative.status == "blocked":
        return "blocked"
    return "restricted" if narrative.limitations or narrative.status != "candidate" else "complete"


def _lineage_basis(record: EvidenceRecord) -> LineageBasis:
    """The producing register's ceiling basis; an unlisted kind fails closed.

    Citation registers cap at Directly Sourced only while they carry a citation and, for
    located values, a settled status; an unavailable source, a missing or conflicting value
    (even one citing where it was sought) or an absent calculated amount is missing evidence,
    and an Estimated or Proxy calculated amount caps at Assumption-Based.
    """
    kind, row = record.kind, record.record_json
    if kind == "gap":
        return "gap"
    if kind == "source" and SourceRegisterRow.model_validate_json(row).availability != "ready":
        return "missing"
    if kind in _CITED:
        return "citation" if record.citations else "missing"
    if kind in _LOCATED:
        status = (
            SourcePosition.model_validate_json(row).observation.status
            if kind == "observation"
            else StatementCell.model_validate_json(row).status
        )
        return "citation" if record.citations and status in _SETTLED else "missing"
    if kind in _CALCULATED:
        return "calculation"
    if kind in _VALUED:
        value = _VALUED[kind].model_validate_json(row).value
        if value.amount is None:
            return "missing"
        return "estimate" if value.calculation_status in _ESTIMATED else "calculation"
    raise ValueError(f"No QA lineage ceiling for register kind: {kind}")


def _ceilings(
    narrative: NarrativeReport, coverage: list[CoverageField]
) -> tuple[EvidenceCeiling, ...]:
    """One ceiling per distinct reference, in first-appearance order."""
    bases: dict[str, LineageBasis] = {}

    def add(evidence_id: str, basis: LineageBasis) -> None:
        if bases.setdefault(evidence_id, basis) != basis:
            raise ValueError(f"QA reference has conflicting lineage registers: {evidence_id}")

    for record in narrative.inputs.catalogue:
        add(record.evidence_id, _lineage_basis(record))
    for field in coverage:
        add(field.field_id, "coverage")
    for gap in narrative.gaps:
        add(gap.gap_id, "gap")
    return tuple(EvidenceCeiling.of(i, b) for i, b in bases.items())


def _handoff_slot(registers: CanonicalTables) -> CoverageField:
    """Present when these registers' canonical envelope round-trips cleanly (writer, reader,
    every section, cell, marker, prose run and footer hash); absent with the reason otherwise.

    The register envelope carries no QA section, because QA is computed from this slot; the
    promoted envelope, which adds QA and the journal binding, is verified again at promotion.
    """
    issues = handoff_issues(register_envelope(registers))
    return CoverageField(
        field_id="canonical-handoff",
        present=not issues,
        rationale=(
            "Canonical envelope of these registers round-trips: r14 sections, cells, evidence "
            "markers, prose runs and footer hashes verified against its sidecar"
            if not issues
            else "Canonical envelope does not verify: "
            + "; ".join(issue[:300] for issue in issues[:3])
        ),
    )


def cp1_quality_inputs(registers: CanonicalTables) -> QualityInputs:
    """Project scope from trusted registers; authenticate with canonical_quality.

    Shape validation alone is not authentication. Review producers may use this
    projection to prepare judgments; final consumers must recompute externally.
    """
    registers = CanonicalTables.model_validate_json(registers.model_dump_json())
    narrative = registers.downstream.inputs.narrative
    context = narrative.inputs.ledger.context
    tables = {t.table_id: t for t in registers.module.tables}
    coverage = [
        CoverageField(
            field_id=f"table:{table_id}",
            present=table_id in tables,
            rationale="Required r14 register exists; empty permitted registers remain explicit",
        )
        for table_id in REQUIRED_TABLES
    ]
    coverage.extend(
        CoverageField(
            field_id=_id("qa-cell", fact.fact_id),
            present=fact.status in {"known", "not_applicable"},
            rationale=f"{fact.table_id}/{fact.row_id}/{fact.field}: {fact.status}"
            + (f"; {fact.limitation}" if fact.limitation else ""),
        )
        for fact in registers.module.facts
        if fact.table_id in REQUIRED_TABLES
    )
    # Empty mandatory data registers must not improve coverage by losing their cells.
    for table_id in ("T4.1", "T4.2", "T4.4", "T4.5", "T4.6", "T4.10"):
        coverage.append(
            CoverageField(
                field_id=f"populated:{table_id}",
                present=bool(tables.get(table_id) and tables[table_id].rows),
                rationale="Source/entity/statements/KPI register requires populated rows",
            )
        )
    dimensions = {c.dimension: c for c in narrative.review.coverage}
    coverage.extend(
        CoverageField(
            field_id=f"dimension:{dimension}",
            present=dimension in dimensions and dimensions[dimension].status != "unassessed",
            rationale="Explicit addressed or justified not-applicable dimensional assessment",
        )
        for dimension in _DIMENSIONS
    )
    stories = {s.evidence_id for s in narrative.review.stories}
    coverage.extend(
        CoverageField(
            field_id=_id("qa-story", evidence_id),
            present=evidence_id in stories,
            rationale="Required event/funding story is linked to a validated finding",
        )
        for evidence_id in narrative.required_story_ids
    )
    coverage.extend(
        (
            CoverageField(
                field_id="source-gate",
                present=context.status == "candidate",
                rationale=f"Source context status: {context.status}",
            ),
            CoverageField(
                field_id="funding-assessment",
                present=narrative.review.funding.status != "unassessed",
                rationale="Located balance-sheet funding classification has been assessed",
            ),
            CoverageField(
                field_id="analytical-findings",
                present=bool(narrative.review.findings),
                rationale="At least one evidence-risk-credit chain is supplied",
            ),
            _handoff_slot(registers),
        )
    )
    claims = tuple(
        ClaimCandidate(
            claim_id=f.finding_id,
            evidence_ids=tuple(
                dict.fromkeys(
                    part.evidence_id
                    for passage in (f.evidence, f.risk_mechanic, f.credit_implication)
                    for part in passage
                    if isinstance(part, EvidencePart)
                )
            ),
        )
        for f in narrative.review.findings
    )
    gate: SourceGate = (
        "pass"
        if context.status == "candidate"
        else "partial"
        if context.status == "restricted"
        else "fail"
    )
    ceilings = _ceilings(narrative, coverage)
    return QualityInputs(
        artifact_sha256=registers.content_hash(),
        coverage_policy="cp1-registers-pre-handoff/1",
        claims=claims,
        coverage=tuple(coverage),
        source_gate=gate,
        module_status=_module_status(narrative),
        references=tuple(c.evidence_id for c in ceilings),
        ceilings=ceilings,
    )


def canonical_quality(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
    narrative: NarrativeReview,
    requested_consumers: tuple[str, ...],
    downstream: DownstreamReview,
    review: QualityReview,
    *,
    quarter_ids: tuple[str, ...] | None = None,
) -> CP1QualityReport:
    """Recompute CP-1 registers and QA scope from external, validated inputs."""
    registers = canonical_tables(
        pack,
        context,
        financial,
        definition,
        binding,
        narrative,
        requested_consumers,
        downstream,
        quarter_ids=quarter_ids,
    )
    inputs = cp1_quality_inputs(registers)
    return CP1QualityReport(
        registers=registers, inputs=inputs, quality=assess_quality(inputs, review)
    )


def validate_canonical_quality(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
    narrative: NarrativeReview,
    requested_consumers: tuple[str, ...],
    downstream: DownstreamReview,
    review: QualityReview,
    report: CP1QualityReport,
    *,
    quarter_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    try:
        report = CP1QualityReport.model_validate_json(report.model_dump_json())
        expected = canonical_quality(
            pack,
            context,
            financial,
            definition,
            binding,
            narrative,
            requested_consumers,
            downstream,
            review,
            quarter_ids=quarter_ids,
        )
    except ValueError as error:
        return (f"Invalid CP-1 QA report: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("CP-1 QA report differs from trusted external recomputation",)
    )
