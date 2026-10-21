"""Cumulative CP-1 gaps with their source artifacts and actual period bases.

This register does not grant consumer readiness or analytical acceptance.
"""

from datetime import date
from typing import Literal

from deploy_vii.canonical_audit import CanonicalAuditReport, DefinitionReview, canonical_audit
from deploy_vii.canonical_kpis import CanonicalKpiReport, canonical_kpis
from deploy_vii.context_binding import FinancialContextBinding, validate_financial_context
from deploy_vii.contracts import Citation, Contract, Hash, Identifier, Text
from deploy_vii.financial_adapter import kernel_registers
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.financial_periods import PeriodValue, _id
from deploy_vii.financial_validation import records
from deploy_vii.period_reconciliation import PeriodReconciliationReport, reconcile_periods
from deploy_vii.preparation import PreparedPack
from deploy_vii.source_context import SourceContextReport, SourceContextReview, source_context


class GapPeriod(Contract):
    kind: Literal["source", "construction", "basis", "context"]
    reference: Identifier
    label: Text
    start_date: date | None
    end_date: date | None


class GapDetail(Contract):
    origin: Text
    artifact_sha256: Hash
    reference: Text
    metric: Text | None
    periods: tuple[GapPeriod, ...]
    description: Text
    severity: Literal["WARN", "BLOCK"]
    downstream_impact: Text
    recommended_action: Text
    citations: tuple[Citation, ...]


class LedgerGap(GapDetail):
    gap_id: Identifier


class CanonicalGapReport(Contract):
    schema_version: Literal["canonical-gaps/1"] = "canonical-gaps/1"
    context: SourceContextReport
    binding: FinancialContextBinding
    binding_issues: tuple[Text, ...]
    audit: CanonicalAuditReport
    calculation_status: Literal["generated", "blocked"]
    calculation_issues: tuple[Text, ...]
    kpis: CanonicalKpiReport | None
    period_reconciliation: PeriodReconciliationReport | None
    gaps: tuple[LedgerGap, ...]
    limitations: tuple[Text, ...]


def _calculation_gaps(
    kpis: CanonicalKpiReport, reconciliation: PeriodReconciliationReport
) -> tuple[GapDetail, ...]:
    """Keep calculation failures, caveats and original basis identities together."""
    historical = kpis.historical
    historical_hash, kpi_hash, check_hash = (
        historical.content_hash(),
        kpis.content_hash(),
        reconciliation.content_hash(),
    )
    constructions = {
        row.construction_id: GapPeriod(
            kind="construction",
            reference=row.construction_id,
            label=row.label,
            start_date=row.start_date,
            end_date=row.end_date,
        )
        for row in historical.constructions
    }
    bases = {
        row.basis_id: GapPeriod(
            kind="basis",
            reference=row.basis_id,
            label=row.label,
            start_date=row.start_date,
            end_date=row.end_date,
        )
        for row in kpis.bases
    }
    source_periods = {
        p.period_id: GapPeriod(
            kind="source",
            reference=p.period_id,
            label=p.period_id,
            start_date=p.start_date,
            end_date=p.end_date,
        )
        for p in historical.periods
    }
    result: list[GapDetail] = []

    def append(
        origin: str,
        artifact: str,
        reference: str,
        metric: str | None,
        periods: tuple[GapPeriod, ...],
        description: str,
        severity: Literal["WARN", "BLOCK"] = "WARN",
        citations: tuple[Citation, ...] = (),
    ) -> None:
        result.append(
            GapDetail(
                origin=origin,
                artifact_sha256=artifact,
                reference=reference,
                metric=metric,
                periods=periods,
                description=description,
                severity=severity,
                citations=citations,
                downstream_impact="Affected period and metric remain limited for downstream use",
                recommended_action=(
                    "Resolve the cited input or retain the limitation; rerun affected calculations"
                ),
            )
        )

    def value_gap(
        origin: str,
        artifact: str,
        reference: str,
        metric: str,
        periods: tuple[GapPeriod, ...],
        value: PeriodValue,
    ) -> None:
        if (
            value.amount is None
            or value.reason
            or value.note
            or value.calculation_status not in {"Verified", "Calculated"}
        ):
            append(
                origin,
                artifact,
                reference,
                metric,
                periods,
                "; ".join(
                    dict.fromkeys(
                        part
                        for part in (
                            f"{metric}: {value.calculation_status}",
                            value.reason,
                            value.note,
                            "Value unavailable" if value.amount is None else None,
                        )
                        if part
                    )
                ),
                "BLOCK" if value.calculation_status == "Conflicted" else "WARN",
                value.citations,
            )

    if not historical.columns:
        append(
            "construction",
            historical_hash,
            "display-periods",
            None,
            (),
            "No historical display periods could be constructed",
            "BLOCK",
        )
    observations = {o.observation_id: o for o in historical.observations}
    normalizations = {n.normalization_id: n for n in historical.facility_normalizations}
    for i, input_row in enumerate(historical.input_rows):
        if input_row.adapter_amount is None:
            normalization = normalizations.get(input_row.normalization_id or "")
            observation = (
                observations.get(input_row.observation_id) if input_row.observation_id else None
            )
            append(
                "historical_input",
                historical_hash,
                f"input:{i}",
                input_row.series_key,
                (source_periods[input_row.period_id],),
                normalization.reason
                if normalization and normalization.reason
                else observation.reason
                if observation and observation.reason
                else "Adapter input unavailable",
                "BLOCK"
                if normalization or (observation and observation.status == "conflicting")
                else "WARN",
                normalization.citations
                if normalization
                else tuple(records(observation, Citation))
                if observation
                else (),
            )
    for node in historical.constructions:
        period = constructions[node.construction_id]
        for text in (
            node.limitation,
            "Constructed period dates are incomplete"
            if period.start_date is None or period.end_date is None
            else None,
            "Construction has unavailable period operands"
            if any(t.kind == "missing" for t in node.terms)
            else None,
        ):
            if text:
                append("construction", historical_hash, node.construction_id, None, (period,), text)
    for row in historical.values:
        period = constructions[row.construction_id]
        value_gap(
            "historical_value", historical_hash, row.value_id, row.series_key, (period,), row.value
        )
        for i, operand in enumerate(row.operands):
            ref = operand.reference
            operand_period = (
                source_periods[ref.reference]
                if ref.kind == "period" and ref.reference
                else constructions[ref.reference]
                if ref.kind == "construction" and ref.reference
                else None
            )
            value_gap(
                "historical_operand",
                historical_hash,
                f"{row.value_id}:{i}",
                row.series_key,
                tuple(dict.fromkeys((period, operand_period))) if operand_period else (period,),
                operand.value,
            )
    for check in reconciliation.checks:
        if check.status != "PASS":
            append(
                "period_reconciliation",
                check_hash,
                check.check_id,
                check.metric_id,
                (constructions[check.construction_id],),
                check.explanation,
                check.status,
                tuple(dict.fromkeys(records(check, Citation))),
            )
    for basis in kpis.bases:
        for text in (
            basis.limitation,
            "Calculation basis dates are incomplete"
            if basis.start_date is None or basis.end_date is None
            else None,
        ):
            if text:
                append("basis", kpi_hash, basis.basis_id, None, (bases[basis.basis_id],), text)
    for value in kpis.values:
        value_gap(
            "canonical_value",
            kpi_hash,
            value.value_id,
            value.key,
            (bases[value.basis_id],),
            value.value,
        )
    values = {v.value_id: v for v in kpis.values}
    for kpi in kpis.kpis:
        period = bases[kpi.display_basis_id]
        affected = tuple(
            dict.fromkeys(
                (
                    period,
                    *(
                        bases[values[operand.value_id].basis_id]
                        for leg in (kpi.numerator, kpi.denominator)
                        if leg
                        for operand in leg.operands
                    ),
                )
            )
        )
        value_gap("kpi", kpi_hash, kpi.calculation_id, kpi.key, affected, kpi.value)
        if kpi.evidence_quality_tier is None:
            append(
                "kpi_evidence",
                kpi_hash,
                kpi.calculation_id,
                kpi.key,
                (period,),
                kpi.evidence_limitation,
                citations=kpi.value.citations,
            )
    for origin, report, report_hash in (
        ("historical", historical, historical_hash),
        ("canonical_kpis", kpis, kpi_hash),
        ("period_reconciliation", reconciliation, check_hash),
    ):
        for limitation in report.limitations:
            append("report_limitation", report_hash, origin, None, (), limitation)
    return tuple(result)


def canonical_gaps(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
) -> CanonicalGapReport:
    # Reconstruct before traversal, including nested model_copy/model_construct inputs.
    pack = PreparedPack.model_validate_json(pack.model_dump_json())
    context = SourceContextReview.model_validate_json(context.model_dump_json())
    financial = FinancialReview.model_validate_json(financial.model_dump_json())
    definition = DefinitionReview.model_validate_json(definition.model_dump_json())
    binding = FinancialContextBinding.model_validate_json(binding.model_dump_json())
    context_report = source_context(pack, context)
    audit = canonical_audit(pack, financial, definition)
    binding_issues = validate_financial_context(pack, context, financial, binding)
    book = next(b for b in financial.books if b.book_id == definition.book_id)
    source_periods = {
        p.period_id: GapPeriod(
            kind="source",
            reference=p.period_id,
            label=p.period_id,
            start_date=p.start_date,
            end_date=p.end_date,
        )
        for p in book.periods
    }
    scopes = {
        s.scope_id: GapPeriod(
            kind="context",
            reference=s.scope_id,
            label=s.period_label,
            start_date=s.start_date,
            end_date=s.end_date,
        )
        for source in context.sources
        for s in source.scopes
    }
    context_hash, audit_hash = context_report.content_hash(), audit.content_hash()
    details: list[GapDetail] = []
    for gap in context_report.gaps:
        details.append(
            GapDetail(
                origin="context",
                artifact_sha256=context_hash,
                reference=gap.gap_id,
                metric=None,
                periods=tuple(scopes[scope_id] for scope_id in gap.scope_ids),
                description=gap.description,
                severity="BLOCK"
                if gap.reference == "file-gate" and gap.category == "source"
                else "WARN",
                downstream_impact=(
                    "Source authority, entity scope or event treatment requires review"
                ),
                recommended_action=(
                    "Resolve the located source-context gap or retain its limitation"
                ),
                citations=gap.citations,
            )
        )
    for audit_gap in audit.gaps:
        details.append(
            GapDetail(
                origin="source_audit",
                artifact_sha256=audit_hash,
                reference=audit_gap.gap_id,
                metric=audit_gap.reference,
                periods=tuple(source_periods[p] for p in audit_gap.period_ids),
                description=audit_gap.description,
                severity=audit_gap.severity,
                downstream_impact=audit_gap.downstream_impact,
                recommended_action=audit_gap.recommended_action,
                citations=audit_gap.citations,
            )
        )
    binding_hash = binding.content_hash() if binding_issues else ""
    for issue in binding_issues:
        details.append(
            GapDetail(
                origin="context_binding",
                artifact_sha256=binding_hash,
                reference=book.book_id,
                metric=None,
                periods=(),
                description=issue,
                severity="BLOCK",
                downstream_impact=(
                    "Financial evidence is not bound to the declared source/entity context"
                ),
                recommended_action=(
                    "Correct the explicit binding and source scopes; do not infer compatibility"
                ),
                citations=(),
            )
        )
    # Retain a source-stage ledger when the Model adapter cannot accept the inputs.
    calculation_issues: tuple[str, ...] = ()
    try:
        kernel_registers(pack, financial, book.book_id)
    except ValueError as error:
        calculation_issues = (str(error),)
    kpis = None
    reconciliation = None
    if calculation_issues:
        for issue in calculation_issues:
            details.append(
                GapDetail(
                    origin="calculation_gate",
                    artifact_sha256=financial.content_hash(),
                    reference=book.book_id,
                    metric=None,
                    periods=(),
                    description=issue,
                    severity="BLOCK",
                    downstream_impact="Constructed-period and KPI registers cannot be generated",
                    recommended_action=(
                        "Complete the source assessments required by the calculation adapter"
                    ),
                    citations=book.addback_disclosure.citations,
                )
            )
    else:
        kpis = canonical_kpis(pack, financial, book.book_id)
        reconciliation = reconcile_periods(pack, financial, book.book_id)
        details.extend(_calculation_gaps(kpis, reconciliation))
    for origin, report, report_hash in (
        ("context", context_report, context_hash),
        ("source_audit", audit, audit_hash),
    ):
        for limitation in report.limitations:
            details.append(
                GapDetail(
                    origin="report_limitation",
                    artifact_sha256=report_hash,
                    reference=origin,
                    metric=None,
                    periods=(),
                    description=limitation,
                    severity="WARN",
                    downstream_impact="The originating artifact's scope remains limited",
                    recommended_action=(
                        "Retain the limitation when presenting or using this artifact"
                    ),
                    citations=(),
                )
            )
    gaps = tuple(
        LedgerGap(gap_id=_id("cp1-gap", book.book_id, detail.content_hash()), **dict(detail))
        for detail in dict.fromkeys(details)
    )
    return CanonicalGapReport(
        context=context_report,
        binding=binding,
        binding_issues=binding_issues,
        audit=audit,
        calculation_status="blocked" if calculation_issues else "generated",
        calculation_issues=calculation_issues,
        kpis=kpis,
        period_reconciliation=reconciliation,
        gaps=gaps,
        limitations=(
            "Cumulative implemented-register gaps only; narrative "
            "and full consumer readiness remain separate",
            "Generated calculations and absence of a gap do not "
            "establish analytical or Module acceptance",
        ),
    )


def validate_canonical_gaps(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
    report: CanonicalGapReport,
) -> tuple[str, ...]:
    try:
        report = CanonicalGapReport.model_validate_json(report.model_dump_json())
        expected = canonical_gaps(pack, context, financial, definition, binding)
    except ValueError as error:
        return (f"Invalid canonical gap ledger: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Canonical gap ledger differs from recomputed input registers",)
    )
