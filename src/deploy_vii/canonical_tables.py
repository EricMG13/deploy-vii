"""Canonical CP-1 register projection from recomputed analytical artifacts.

Projection only: arithmetic and sufficiency judgments remain in their validated
upstream contracts. This is not the final Markdown envelope or Module acceptance.
"""

from collections.abc import Iterable
from dataclasses import replace
from typing import Literal

from deploy_vii.calculation_trace import Computation
from deploy_vii.canonical_audit import DefinitionReview
from deploy_vii.context_binding import FinancialContextBinding
from deploy_vii.contracts import Citation, Contract, Input, Module, TableColumn
from deploy_vii.downstream_readiness import (
    DownstreamReport,
    DownstreamReview,
    canonical_downstream_readiness,
)
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.financial_periods import PeriodValue, _id
from deploy_vii.model_interface import (
    SCHEMAS,
    ModelInterface,
    Scalar,
    TableSchemas,
    _Cell,
    _Tables,
    model_interface,
)
from deploy_vii.narrative import NarrativeReview
from deploy_vii.narrative_projection import project_narrative
from deploy_vii.preparation import PreparedPack
from deploy_vii.source_context import SourceContextReview
from deploy_vii.statement_history import StatementHistoryReport, statement_history
from deploy_vii.statement_view import statement_view

# Machine keys and human headings are separate. Only Model interface tables use
# machine-readable table-id comments and their exact controlled key headings.
COLUMNS = {
    "T4.1": (
        "Source Register",
        "Source File Name|Document Type|Period Coverage|Currency|Unit|Perimeter|"
        "Accounting Basis|Evidence Quality Tier|Analytical Use|Limitations",
    ),
    "T4.2": (
        "Entity Period Key",
        "Entity Name|Entity Role|Fiscal Year End|Reporting Currency|Reporting Unit|"
        "Consolidation Perimeter|Accounting Basis|Available Periods",
    ),
    "T4.3": ("Normalization Register", "Description|Source|Type|Before|After|Rationale|Periods"),
    "T4.8": (
        "Constructed Period Register",
        "Metric Name|Derived Period Type|Full-Year Component|Current Stub|Prior-Year Stub|"
        "Derived Value|Calculation Status|Source Files|Limitations|Components",
    ),
    "T4.9": (
        "Calculation Register",
        "Metric Name|Formula|Numerator Value|Numerator Source|Denominator Value|"
        "Denominator Source|Period|Currency|Unit|Calculated Value|Calculation Status|"
        "Evidence Quality Tier|Limitations|Operand References",
    ),
    "T4.10": ("KPI Dashboard", "KPI Category|Metric Name|Trend Direction|Analyst Note"),
    "T4.11": (
        "Definition Conflict Register",
        "Metric Name|Canonical Definition|Issuer-Reported Definition|Source of Conflict|"
        "Periods Affected|Materiality|Downstream Modules Affected|"
        "Resolution / Recommendation|Source Positions",
    ),
    "T4.12": (
        "Gaps & Warnings",
        "Gap Description|Affected Line Item or Metric|Affected Period(s)|Downstream Impact|"
        "Severity|Recommended Action",
    ),
    "T4.13": (
        "Downstream Readiness",
        "Downstream Module|Readiness Status|Gaps or Limitations|Recommended Actions",
    ),
}


# The register candidate's own first limitation; CP-1 promotion (cp1_workflow) replaces it.
REGISTER_NOTE = (
    "Canonical register and narrative candidate; final envelope, QA "
    "and Module promotion are pending."
)


class CanonicalTables(Contract):
    schema_version: Literal["canonical-tables/2"] = "canonical-tables/2"
    downstream: DownstreamReport
    statements: StatementHistoryReport
    interface: ModelInterface
    module: Module


def _join(values: Iterable[str | None]) -> str | None:
    return "; ".join(dict.fromkeys(v for v in values if v)) or None


def _optional(value: str | None) -> _Cell:
    return _Cell(
        value,
        status="known" if value else "not_applicable",
        reason="No additional reference or limitation recorded",
    )


def _refs(citations: tuple[Citation, ...]) -> str | None:
    return _join(tuple(f"{c.source_id}: {c.locator}" for c in citations))


def _value(
    value: PeriodValue, unit: str, currency: str | None, identity: str, formula: str
) -> _Cell:
    return _Cell(
        value.amount,
        value.citations,
        status="known"
        if value.amount is not None
        else "conflicting"
        if value.calculation_status == "Conflicted"
        else "not_applicable"
        if value.reason == "NOT_APPLICABLE"
        else "missing",
        reason=_join((value.reason, value.note)) or "Calculation unavailable",
        unit=unit,
        currency=currency,
        value_class=value.value_class,
        formula=formula,
        calculation_id=identity,
        calculation_status=value.calculation_status,
        stated_amount=value.stated_amount,
        note=_join((value.reason, value.note)),
    )


def _keys(table: str) -> tuple[str, ...]:
    return tuple(f"field_{i}" for i, _ in enumerate(COLUMNS[table][1].split("|")))


def _row(
    tables: _Tables,
    table: str,
    identity: str,
    period: str,
    cells: tuple[Scalar | _Cell, ...],
    citations: tuple[Citation, ...] = (),
) -> None:
    fields = dict(zip(tables.schemas[table][2], cells, strict=True))
    tables.row(
        table,
        (identity,),
        period,
        fields,
        citations,
        frozenset(
            k for k, v in fields.items() if isinstance(v, _Cell) and v.status == "not_applicable"
        ),
    )


def _context(tables: _Tables, report: DownstreamReport) -> None:
    context = report.inputs.narrative.inputs.ledger.context
    for source in context.sources:
        assessment = source.assessment
        # One row per source/scope avoids pairing currencies with another scope's period.
        for scope in assessment.scopes or (None,):
            citations = tuple(
                dict.fromkeys((*assessment.citations, *(scope.citations if scope else ())))
            )
            period = (
                f"{scope.period_label}: {scope.start_date or 'null'} to {scope.end_date or 'null'}"
                if scope
                else "Unspecified source coverage"
            )
            _row(
                tables,
                "T4.1",
                _id("source-scope", source.source_id, scope.scope_id if scope else "unscoped"),
                period,
                (
                    source.filename,
                    assessment.document_type,
                    period if scope else None,
                    scope.currency if scope else None,
                    scope.unit if scope else None,
                    scope.entity_perimeter if scope else None,
                    scope.accounting_basis if scope else None,
                    source.evidence_tier,
                    assessment.analytical_use,
                    _optional(
                        _join(
                            (
                                *source.extraction_limitations,
                                *assessment.limitations,
                                *(scope.limitations if scope else ()),
                            )
                        )
                    ),
                ),
                citations,
            )
    scopes = {s.scope_id: s for source in context.sources for s in source.assessment.scopes}
    for row in context.entities:
        for scope_id in row.scope_ids or (None,):
            scope = scopes[scope_id] if scope_id else None
            _row(
                tables,
                "T4.2",
                _id("entity-scope", row.entity.entity_id, scope_id or "unscoped"),
                scope.period_label if scope else "Unspecified entity coverage",
                (
                    row.entity.name,
                    _join(row.entity.roles),
                    row.entity.fiscal_year_end,
                    scope.currency if scope else None,
                    scope.unit if scope else None,
                    scope.entity_perimeter if scope else None,
                    scope.accounting_basis if scope else None,
                    (
                        f"{scope.period_label}: {scope.start_date or 'null'} "
                        f"to {scope.end_date or 'null'}"
                    )
                    if scope
                    else None,
                ),
                tuple(dict.fromkeys((*row.entity.citations, *(scope.citations if scope else ())))),
            )


def _normalizations(tables: _Tables, report: DownstreamReport) -> None:
    audit = report.inputs.narrative.inputs.ledger.audit
    positions = {p.observation.observation_id: p for p in audit.source_positions}
    for row in audit.normalizations:
        original = positions[row.observation_id]
        before = _Cell(row.before, row.citations, unit=original.unit, currency=original.currency)
        after = replace(
            before,
            value=row.after,
            source_amount=row.before,
            value_class="normalized",
            formula=row.operation,
            calculation_id=row.normalization_id,
        )
        _row(
            tables,
            "T4.3",
            row.normalization_id,
            row.period_id,
            (
                row.observation_id,
                _refs(row.citations),
                row.operation,
                before,
                after,
                row.rationale,
                row.period_id,
            ),
            row.citations,
        )
    for fx in audit.facility_normalizations:
        before = _Cell(
            fx.original_amount,
            fx.citations,
            unit=fx.unit,
            currency=fx.source_currency,
            reason=fx.reason,
        )
        after = replace(
            before,
            value=fx.amount,
            currency=fx.target_currency,
            source_amount=fx.original_amount,
            value_class="normalized",
            formula=fx.formula,
            calculation_id=fx.normalization_id,
        )
        _row(
            tables,
            "T4.3",
            fx.normalization_id,
            fx.period_id,
            (
                f"{fx.facility_id} / {fx.field}",
                _refs(fx.citations),
                f"FX {fx.source_currency} to {fx.target_currency}",
                before,
                after,
                _join((fx.formula, fx.reason, str(fx.rate_date) if fx.rate_date else None)),
                fx.period_id,
            ),
            fx.citations,
        )


def _constructed(tables: _Tables, history: StatementHistoryReport) -> None:
    constructions = {c.construction_id: c for c in history.constructions}
    periods = {p.period_id: p for p in history.periods}
    graph = {c.computation_id: c for c in history.computations}
    for row in history.values:
        construction = constructions[row.construction_id]
        parts: list[list[str]] = [[], [], []]
        for operand in row.operands:
            ref = operand.reference
            node = constructions.get(ref.reference or "")
            period = periods.get(ref.reference or "")
            kind = node.kind if node else period.period_type if period else None
            value = graph[operand.computation_id].value.amount
            text = (
                f"{ref.coefficient:+d} * {ref.reference or 'missing'}: "
                f"{value if value is not None else 'null'}; {operand.computation_id}"
            )
            parts[2 if ref.coefficient < 0 else 0 if kind == "FY" else 1].append(text)
        formula = (
            "Closing observation at period end; no flow subtraction"
            if row.table_id == "T4.6"
            else construction.formula
        )
        period_text = (
            f"{construction.label}: {construction.start_date or 'null'} "
            f"to {construction.end_date or 'null'}"
        )
        amount = _value(
            row.value, history.source.unit, history.source.currency, row.computation_id, formula
        )
        _row(
            tables,
            "T4.8",
            row.value_id,
            period_text,
            (
                f"{row.table_id} / {row.item_id}",
                construction.kind,
                *(
                    _Cell(
                        _join(p),
                        status="known" if p else "not_applicable",
                        reason="Not an operand of this construction",
                    )
                    for p in parts
                ),
                amount,
                row.value.calculation_status,
                _refs(row.value.citations),
                _optional(_join((row.value.reason, row.value.note, construction.limitation))),
                _join(tuple(x for part in parts for x in part))
                or "Closing observation; inspect its calculation",
            ),
            row.value.citations,
        )


def _calculations(
    tables: _Tables, report: DownstreamReport, history: StatementHistoryReport
) -> None:
    """Project each graph in each dimensional use; never infer units from graph IDs."""
    ledger = report.inputs.narrative.inputs.ledger
    # A graph node can serve several periods/units. Its ID alone is not a display scope.
    scopes: list[tuple[str, str, str, str, str | None, str, tuple[Computation, ...]]] = []
    constructions = {c.construction_id: c for c in history.constructions}
    for row in history.values:
        c = constructions[row.construction_id]
        scopes.append(
            (
                row.value_id,
                row.computation_id,
                c.label + f" ({c.start_date} to {c.end_date})",
                history.source.unit,
                history.source.currency,
                f"{row.table_id}/{row.item_id}",
                history.computations,
            )
        )
    kpis = ledger.kpis
    if kpis:
        bases = {b.basis_id: b for b in kpis.bases}
        for item in kpis.values:
            basis = bases[item.basis_id]
            scopes.append(
                (
                    item.value_id,
                    item.computation_id,
                    basis.label + f" ({basis.start_date} to {basis.end_date})",
                    item.unit,
                    item.currency,
                    item.key,
                    kpis.computations,
                )
            )
    # Sums preserve their input dimensions. Unknown operation dimensions stay
    # explicit rather than being silently inferred from a root result.
    seen: set[tuple[str, str]] = set()
    for use_id, root, period, unit, currency, metric, raw_graph in scopes:
        graph = {c.computation_id: c for c in raw_graph}
        pending = [(root, True, unit, currency)]
        while pending:
            identity, is_root, child_unit, child_currency = pending.pop()
            key = (use_id, identity)
            if key in seen:
                continue
            seen.add(key)
            node = graph[identity]
            value = _value(node.value, child_unit, child_currency, identity, node.formula)
            refs = _join(tuple(f"{o.coefficient:+d} * {o.computation_id}" for o in node.operands))
            note = _join(
                (
                    node.value.reason,
                    node.value.note,
                    None
                    if child_unit != "untyped_operand"
                    else "Intermediate unit unavailable; inspect root formula and sources",
                )
            )
            _row(
                tables,
                "T4.9",
                _id("graph-scope", *key),
                period,
                (
                    metric if is_root else identity,
                    node.formula,
                    _Cell(
                        None, status="not_applicable", reason="Graph operands are listed separately"
                    ),
                    _Cell(
                        None, status="not_applicable", reason="Graph operands are listed separately"
                    ),
                    _Cell(
                        None, status="not_applicable", reason="Graph operands are listed separately"
                    ),
                    _Cell(
                        None, status="not_applicable", reason="Graph operands are listed separately"
                    ),
                    period,
                    child_currency or "Not monetary or not independently typed",
                    child_unit,
                    value,
                    node.value.calculation_status,
                    None,
                    _optional(note),
                    refs or node.operation,
                ),
                node.value.citations,
            )
            pending.extend(
                (
                    o.computation_id,
                    False,
                    child_unit if node.operation == "sum" else "untyped_operand",
                    child_currency if node.operation == "sum" else None,
                )
                for o in reversed(node.operands)
            )
    if not kpis:
        return
    values = {v.value_id: v for v in kpis.values}
    bases = {b.basis_id: b for b in kpis.bases}
    for metric_row in kpis.kpis:
        basis = bases[metric_row.display_basis_id]
        period = basis.label + f" ({basis.start_date} to {basis.end_date})"
        legs: list[_Cell] = []
        operand_refs: list[str] = []
        for leg in (metric_row.numerator, metric_row.denominator):
            if leg is None:
                legs.extend(
                    (_Cell(None, status="not_applicable", reason="No denominator for this metric"),)
                    * 2
                )
                continue
            citations = tuple(
                dict.fromkeys(c for o in leg.operands for c in values[o.value_id].value.citations)
            )
            legs.extend(
                (
                    _Cell(
                        leg.amount,
                        citations,
                        unit=metric_row.input_scale,
                        currency=metric_row.currency,
                        value_class="calculated",
                        reason="Metric operands unavailable",
                    ),
                    _Cell(
                        _refs(citations), citations, reason="No source citation for metric operands"
                    ),
                )
            )
            operand_refs.extend(
                f"{o.coefficient:+d} * {o.value_id} -> {values[o.value_id].computation_id}"
                for o in leg.operands
            )
        _row(
            tables,
            "T4.9",
            metric_row.calculation_id,
            period,
            (
                metric_row.key,
                metric_row.formula,
                *legs,
                period,
                metric_row.currency,
                metric_row.unit,
                _value(
                    metric_row.value,
                    metric_row.unit,
                    metric_row.currency
                    if metric_row.unit in {"UNITS", "THOUSANDS", "MILLIONS"}
                    else None,
                    metric_row.calculation_id,
                    metric_row.formula,
                ),
                metric_row.value.calculation_status,
                metric_row.evidence_quality_tier,
                _join(
                    (metric_row.evidence_limitation, metric_row.value.reason, metric_row.value.note)
                ),
                _join(tuple(operand_refs)),
            ),
            metric_row.value.citations,
        )


def _category(key: str) -> str:
    if key.endswith("_growth"):
        return "Growth"
    if "margin" in key:
        return "Margin"
    if "leverage" in key:
        return "Leverage"
    if "coverage" in key or key == "ffo_to_debt":
        return "Coverage"
    if "liquidity" in key or key in {"cash_closing", "undrawn_rcf"}:
        return "Liquidity"
    if key.startswith(("fcf", "dcf", "cfo")) or key in {
        "ffo",
        "capex",
        "working_capital_change",
        "cash_interest",
        "cash_taxes",
        "capex_to_revenue",
    }:
        return "Cash Flow"
    return "Financial inputs"


def _dashboard(tables: _Tables, report: DownstreamReport) -> None:
    kpis = report.inputs.narrative.inputs.ledger.kpis
    if not kpis:
        return
    bases = tuple(b for b in kpis.bases if b.basis_id in {k.display_basis_id for k in kpis.kpis})
    tables.schemas["T4.10"] = (
        "KPI Dashboard",
        None,
        (*_keys("T4.10")[:2], *(b.basis_id for b in bases), *_keys("T4.10")[2:]),
    )
    for key in dict.fromkeys(k.key for k in kpis.kpis):
        rows = {k.display_basis_id: k for k in kpis.kpis if k.key == key}
        cells = []
        for basis in bases:
            metric = rows[basis.basis_id]
            cells.append(
                replace(
                    _value(
                        metric.value,
                        metric.unit,
                        metric.currency
                        if metric.unit in {"UNITS", "THOUSANDS", "MILLIONS"}
                        else None,
                        metric.calculation_id,
                        metric.formula,
                    ),
                    period=f"{basis.label}: {basis.start_date} to {basis.end_date}",
                )
            )
        _row(
            tables,
            "T4.10",
            key,
            "Exact period stated by each column",
            (
                _category(key),
                key,
                *cells,
                _Cell(None, reason="Analytical trend has not been assessed"),
                _Cell(None, reason="Metric-specific analyst note has not been supplied"),
            ),
        )


def _decisions(tables: _Tables, report: DownstreamReport) -> None:
    narrative = report.inputs.narrative
    audit = narrative.inputs.ledger.audit
    positions = {p.observation.observation_id: p for p in audit.source_positions}
    for row in audit.definitions:
        source_positions = []
        for index, oid in enumerate(row.observation_ids):
            position = positions[oid]
            observation = position.observation
            role = row.roles[index] if index < len(row.roles) else position.field
            alternatives = _join(
                tuple(f"{a.amount} ({_refs(a.citations)})" for a in observation.alternatives)
            )
            source_positions.append(
                f"{role}: {oid} = "
                f"{observation.amount if observation.amount is not None else 'null'} "
                f"{position.currency or ''} {position.unit}; {position.period_id}; "
                f"{observation.status}; {_refs(observation.citations) or 'no primary locator'}"
                + (f"; alternatives: {alternatives}" if alternatives else "")
            )
        _row(
            tables,
            "T4.11",
            row.row_id,
            _join(row.period_ids) or "Unspecified period",
            (
                row.metric,
                row.canonical_definition,
                row.issuer_definition,
                f"{row.kind}: {row.explanation}; observations: {_join(row.observation_ids)}",
                _join(row.period_ids),
                row.materiality,
                row.downstream_impact,
                row.recommendation,
                _join(source_positions),
            ),
            row.citations,
        )
    for gap in narrative.gaps:
        _row(
            tables,
            "T4.12",
            gap.gap_id,
            _join(tuple(p.label for p in gap.periods)) or "Unspecified gap scope",
            (
                f"{gap.gap_id}: {gap.description}",
                gap.metric or gap.reference,
                _join(
                    tuple(
                        f"{p.label} ({p.start_date or 'null'} to {p.end_date or 'null'})"
                        for p in gap.periods
                    )
                ),
                gap.downstream_impact,
                gap.severity,
                gap.recommended_action,
            ),
            gap.citations,
        )
    for consumer in report.consumers:
        _row(
            tables,
            "T4.13",
            consumer.entry,
            "Consumer-specific scope",
            (
                consumer.entry,
                consumer.status,
                _join(
                    (
                        *consumer.blocking_gap_ids,
                        *consumer.relevant_gap_ids,
                        *consumer.unassessed_gap_ids,
                        *consumer.unassessed_requirements,
                    )
                ),
                _optional(_join(consumer.actions)),
            ),
        )
    model = report.model
    _row(
        tables,
        "T4.13",
        "CP-MODEL",
        model.scope,
        (
            model.entry,
            model.status,
            _optional(
                _join((*model.blocking_gap_ids, *model.missing_metric_ids, *model.conflict_refs))
            ),
            _optional(_join(model.actions)),
        ),
    )


def canonical_tables(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
    narrative: NarrativeReview,
    requested_consumers: tuple[str, ...],
    review: DownstreamReview,
    *,
    quarter_ids: tuple[str, ...] | None = None,
) -> CanonicalTables:
    pack = PreparedPack.model_validate_json(pack.model_dump_json())
    financial = FinancialReview.model_validate_json(financial.model_dump_json())
    downstream = canonical_downstream_readiness(
        pack,
        context,
        financial,
        definition,
        binding,
        narrative,
        requested_consumers,
        review,
        quarter_ids=quarter_ids,
    )
    book = downstream.inputs.financial_book
    history = statement_history(pack, financial, book.book_id)
    interface = model_interface(pack, financial, book.book_id, quarter_ids=quarter_ids)
    schemas: TableSchemas = {key: (title, None, _keys(key)) for key, (title, _) in COLUMNS.items()}
    schemas["model-readiness"] = SCHEMAS["model-readiness"]
    tables = _Tables(book, schemas=schemas)
    _context(tables, downstream)
    _normalizations(tables, downstream)
    _constructed(tables, history)
    _calculations(tables, downstream, history)
    _dashboard(tables, downstream)
    _decisions(tables, downstream)
    model = downstream.model
    tables.row(
        "model-readiness",
        ("CP-MODEL",),
        model.scope,
        {
            "downstream_module": model.entry,
            "status": model.status,
            "missing_metric_ids": _join(model.missing_metric_ids),
            "conflict_refs": _join(model.conflict_refs),
            "explanation": _join((*model.actions, *model.blocking_gap_ids))
            or "Selected historical quarters pass their input gate; workbook delivery is separate",
        },
        references=frozenset({"missing_metric_ids", "conflict_refs"}),
    )
    statements = next(
        m for m in statement_view(pack, financial, book.book_id).modules if m.module_id == "CP-1"
    )
    # Add value-null coordinates from the two other projections to the cumulative ledger.
    from deploy_vii.model_interface import InterfaceGap

    tables.gaps.extend(interface.gaps)
    tables.gaps.extend(
        InterfaceGap(
            table_id=f.table_id,
            row_id=f.row_id,
            field=f.field,
            reason=f.limitation or "Statement value unavailable",
        )
        for f in statements.facts
        if f.status != "known"
    )
    # Projection gaps are additional to the immutable upstream ledger. Append once,
    # without recursively turning absent metadata in the gap table into more gaps.
    for gap in tuple(tables.gaps):
        _row(
            tables,
            "T4.12",
            _id("projection-gap", gap.table_id, gap.row_id, gap.field),
            "See referenced row",
            (
                f"{gap.table_id}/{gap.row_id}/{gap.field}: {gap.reason}",
                gap.field,
                "See referenced row",
                "Review source/analysis completeness",
                "WARN",
                "Resolve or retain the explicit limitation",
            ),
        )
    layouts = []
    for layout in tables.layouts():
        if layout.table_id == "model-readiness":
            layouts.append(layout)
            continue
        labels = dict(
            zip(_keys(layout.table_id), COLUMNS[layout.table_id][1].split("|"), strict=True)
        )
        if layout.table_id == "T4.10" and downstream.inputs.narrative.inputs.ledger.kpis:
            labels.update(
                {
                    b.basis_id: f"{b.label} ({b.start_date} to {b.end_date})"
                    for b in downstream.inputs.narrative.inputs.ledger.kpis.bases
                }
            )
        layouts.append(
            layout.model_copy(
                update={
                    "columns": tuple(
                        TableColumn(field=c.field, label=labels[c.field]) for c in layout.columns
                    ),
                    "limitation": (
                        "Candidate register. Inspect values for exact source, units, "
                        "calculation identity and missing reason."
                    ),
                }
            )
        )
    column_labels = {(t.table_id, c.field): c.label for t in layouts for c in t.columns}
    row_labels = {
        (f.table_id, f.row_id): f.text
        for f in tables.facts
        if f.field == ("field_1" if f.table_id == "T4.10" else "field_0")
    }
    projected_facts = tuple(
        f.model_copy(
            update={
                "label": column_labels[f.table_id, f.field]
                + " · "
                + ((row_labels.get((f.table_id, f.row_id)) or f.table_id)[:160]),
            }
        )
        for f in tables.facts
    )
    interface_facts = tuple(f for f in interface.module.facts if f.table_id != "model-readiness")
    interface_tables = tuple(t for t in interface.module.tables if t.table_id != "model-readiness")
    analysis = project_narrative(book, downstream.inputs.narrative, pack.run.issuer_name)
    module = Module(
        run_id=financial.run_id,
        issuer_id=financial.issuer_id,
        as_of=financial.as_of,
        module_id="CP-1",
        inputs=(
            *interface.module.inputs,
            Input(input_id="downstream-report", sha256=downstream.content_hash()),
            Input(input_id="statement-history", sha256=history.content_hash()),
        ),
        facts=(*projected_facts, *statements.facts, *interface_facts, *analysis.facts),
        claims=analysis.claims,
        tables=tuple(
            sorted(
                (*layouts, *statements.tables, *interface_tables, *analysis.tables),
                key=lambda t: (
                    (0, int(t.table_id[3:])) if t.table_id.startswith("T4.") else (1, t.table_id)
                ),
            )
        ),
        limitations=(
            REGISTER_NOTE,
            *("Statement subartifact: " + note for note in statements.limitations),
            *("Model interface subartifact: " + note for note in interface.module.limitations),
            *("Narrative: " + note for note in downstream.inputs.narrative.limitations),
            *downstream.limitations,
        ),
    )
    return CanonicalTables(
        downstream=downstream, statements=history, interface=interface, module=module
    )


def validate_canonical_tables(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
    narrative: NarrativeReview,
    requested_consumers: tuple[str, ...],
    review: DownstreamReview,
    report: CanonicalTables,
    *,
    quarter_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Authenticate a candidate against external inputs, including precision and metadata."""
    try:
        report = CanonicalTables.model_validate_json(report.model_dump_json())
        expected = canonical_tables(
            pack,
            context,
            financial,
            definition,
            binding,
            narrative,
            requested_consumers,
            review,
            quarter_ids=quarter_ids,
        )
    except ValueError as error:
        return (f"Invalid canonical register report: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Canonical registers differ from trusted external recomputation",)
    )
