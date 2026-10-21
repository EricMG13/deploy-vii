"""Source and constructed statements; not a completed CP-1 handoff or acceptance."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Literal

from deploy_vii.contracts import Fact, ModuleView, ReportTable, TableColumn, TableRow, View
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.financial_periods import _id
from deploy_vii.preparation import PreparedPack
from deploy_vii.render import empty_view, render
from deploy_vii.statement_history import (
    StatementHistoricalValue,
    StatementHistoryReport,
    statement_history,
)
from deploy_vii.statement_output import StatementCell

_PREVIEW_LIMIT = (
    "Statement preview only. Source and derived periods are included; the remaining CP-1 "
    "registers, canonical Markdown and final module validation are not delivered here. "
    "This preview does not accept CP-1 or qualify analytical judgments."
)


def statement_view(pack: PreparedPack, financial: FinancialReview, book_id: str) -> View:
    history = statement_history(pack, financial, book_id)
    report = history.source
    scale = {"UNITS": Decimal(1), "THOUSANDS": Decimal(1000), "MILLIONS": Decimal(1000000)}[
        report.unit
    ]
    facts: list[Fact] = []
    tables: list[ReportTable] = []
    for table_id, statement, title in (
        ("T4.4", "IS", "Income statement"),
        ("T4.5", "CFS", "Cash flow statement"),
        ("T4.6", "BS", "Balance sheet"),
    ):
        periods = tuple(
            p for p in history.periods if statement == "BS" or p.period_type != "PERIOD_END"
        )
        if not periods:
            # A genuinely empty source register still has an explicit value column.
            # It is never populated with a manufactured period or financial row.
            tables.append(
                ReportTable(
                    table_id=table_id,
                    title=title,
                    columns=(TableColumn(field="unavailable", label="No source periods"),),
                    rows=(),
                    row_header="Line Item",
                    limitation="No applicable source periods supplied",
                )
            )
            continue
        cells = {(c.item_id, c.period_id): c for c in report.cells if c.table_id == table_id}
        # Source line order/labels take precedence over generated required-gap labels.
        templates: dict[str, StatementCell] = {}
        for source_cell in sorted(
            cells.values(), key=lambda c: (c.line_id is None, c.display_priority)
        ):
            templates.setdefault(source_cell.item_id, source_cell)
        rows: list[TableRow] = []
        for item_id, template in templates.items():
            ids: list[str] = []
            for period in periods:
                cell = cells.get((item_id, period.period_id))
                amount = cell.normalized_amount if cell else None
                identity = _id("statement-fact", book_id, table_id, item_id, period.period_id)
                limitation = (
                    cell.limitation
                    if cell
                    else "This source period supplies no row for the disclosed statement item"
                )
                facts.append(
                    Fact(
                        fact_id=identity,
                        label=(cell.label if cell else template.label) + " · " + period.period_id,
                        table_id=table_id,
                        row_id=item_id,
                        field=period.period_id,
                        amount=amount,
                        status=cell.status if cell else "missing",
                        unit="currency",
                        currency=report.currency,
                        scale=scale,
                        period=(
                            f"{period.period_id} · {period.start_date or 'start not supplied'}"
                            f" to {period.end_date or 'end not supplied'}"
                        ),
                        basis=f"{report.accounting_basis} · {report.entity_perimeter}",
                        citations=cell.citations if cell else (),
                        calculation_id=cell.normalization_id if cell else None,
                        value_class=cell.value_class if cell else None,
                        source_amount=cell.source_amount if cell else None,
                        formula=cell.normalization if cell and cell.normalization_id else None,
                        limitation=limitation
                        or ("Statement value unavailable" if amount is None else None),
                    )
                )
                ids.append(identity)
            rows.append(TableRow(row_id=item_id, label=template.label, fact_ids=tuple(ids)))
        tables.append(
            ReportTable(
                table_id=table_id,
                title=title,
                row_header="Line Item",
                columns=tuple(
                    TableColumn(
                        field=p.period_id,
                        label=f"{p.period_id} · {p.end_date or 'date unavailable'}",
                    )
                    for p in periods
                ),
                rows=tuple(rows),
                limitation=(
                    f"{report.currency} · {report.unit} · {report.entity_perimeter} · "
                    f"{report.accounting_basis}. Source periods only. Inspect each cell "
                    "for source label, dates, status and limitations."
                ),
            )
        )
    module = ModuleView(
        module_id="CP-1",
        title="Financial foundation",
        aliases=(),
        status="candidate",
        artifact_sha256=report.content_hash(),
        facts=tuple(facts),
        tables=tuple(tables),
        limitations=(_PREVIEW_LIMIT, *("Source artifact: " + note for note in report.limitations)),
    )
    return _with_derived(
        View(
            run=pack.run,
            mode="candidate",
            sources=pack.sources,
            modules=tuple(
                module if m.module_id == "CP-1" else m for m in empty_view(pack.run).modules
            ),
        ),
        history,
    )


def _with_derived(view: View, history: StatementHistoryReport) -> View:
    module = next(m for m in view.modules if m.module_id == "CP-1")
    constructions = {n.construction_id: n for n in history.constructions}
    periods = {p.period_id: p for p in history.periods}
    computations = {n.computation_id: n for n in history.computations}
    observations = {c.observation_id: c for c in history.source.cells if c.observation_id}
    values: dict[tuple[str, str, str], StatementHistoricalValue] = {
        (v.table_id, v.item_id, v.construction_id): v for v in history.values
    }
    scale = {"UNITS": Decimal(1), "THOUSANDS": Decimal(1000), "MILLIONS": Decimal(1000000)}[
        history.source.unit
    ]
    facts = list(module.facts)
    tables = []
    for table in module.tables:
        # No synthetic flow periods for a point-in-time-only source book.
        if not table.rows:
            tables.append(table)
            continue
        columns = list(table.columns)
        rows = []
        for identity in history.columns:
            node = constructions[identity]
            field = _id("statement-column", identity)
            if any(c.field == field for c in columns):
                raise ValueError("Constructed statement column collides with source identity")
            columns.append(
                TableColumn(
                    field=field,
                    label=f"{node.label} · constructed · {node.end_date or 'date unavailable'}",
                )
            )
        for row in table.rows:
            ids = list(row.fact_ids)
            for identity in history.columns:
                node = constructions[identity]
                result = values[table.table_id, row.row_id, identity]
                value = result.value
                own = (
                    observations.get(value.observation_ids[0])
                    if len(value.observation_ids) == 1
                    else None
                )
                formula_parts = []
                for operand in result.operands:
                    ref = operand.reference
                    name = (
                        constructions[ref.reference].label
                        if ref.kind == "construction" and ref.reference in constructions
                        else ref.reference or "unavailable component"
                    )
                    if (
                        ref.kind == "period"
                        and ref.reference in periods
                        and periods[ref.reference].component_period_ids
                    ):
                        name += " (declared components)"
                    amount = computations[operand.computation_id].value.amount
                    formula_parts.append(
                        f"({ref.coefficient:+d} * {name}: "
                        f"{amount if amount is not None else 'null'})"
                    )
                formula = (
                    " + ".join(formula_parts) + "; all components required"
                    if formula_parts
                    else "Closing observation at period end; no flow subtraction"
                )
                source = history.source
                period_text = (
                    f"{node.label} · {node.start_date or 'start not supplied'} "
                    f"to {node.end_date or 'end not supplied'}"
                )
                if table.table_id == "T4.6":
                    period_text = f"Closing balance · {node.end_date or 'date unavailable'}"
                status: Literal["known", "missing", "conflicting", "not_applicable"] = (
                    "known"
                    if value.amount is not None
                    else "conflicting"
                    if value.calculation_status == "Conflicted"
                    else "not_applicable"
                    if value.reason == "NOT_APPLICABLE"
                    else "missing"
                )
                fact = Fact(
                    fact_id=result.value_id,
                    label=f"{row.label} · {node.label}",
                    table_id=table.table_id,
                    row_id=row.row_id,
                    field=_id("statement-column", identity),
                    amount=value.amount,
                    status=status,
                    unit="currency",
                    currency=source.currency,
                    scale=scale,
                    period=period_text,
                    basis=f"{source.accounting_basis} · {source.entity_perimeter}",
                    citations=value.citations,
                    calculation_id=result.computation_id,
                    value_class=value.value_class,
                    source_amount=own.source_amount
                    if own and value.value_class != "calculated"
                    else None,
                    stated_amount=value.stated_amount,
                    calculation_status=value.calculation_status,
                    formula=formula,
                    limitation="; ".join(
                        x for x in (value.reason, value.note, node.limitation) if x
                    )
                    or None,
                )
                facts.append(fact)
                ids.append(fact.fact_id)
            rows.append(row.model_copy(update={"fact_ids": tuple(ids)}))
        tables.append(
            table.model_copy(
                update={
                    "columns": tuple(columns),
                    "rows": tuple(rows),
                    "limitation": (
                        f"{history.source.currency} · {history.source.unit} · "
                        f"{history.source.entity_perimeter} · {history.source.accounting_basis}. "
                        + (
                            "Reported periods followed by constructed periods. "
                            if history.columns
                            else "Reported periods only. "
                        )
                        + "Balance sheets use "
                        "closing observations. Inspect cells for formulas, stated comparisons "
                        "and evidence."
                    ),
                }
            )
        )
    updated = module.model_copy(
        update={
            "facts": tuple(facts),
            "tables": tuple(tables),
            "artifact_sha256": history.content_hash(),
        }
    )
    return View.model_validate_json(
        view.model_copy(
            update={"modules": tuple(updated if m.module_id == "CP-1" else m for m in view.modules)}
        ).model_dump_json()
    )


def write_statement_preview(
    pack: PreparedPack,
    financial: FinancialReview,
    book_id: str,
    destination: Path,
    *,
    execution_binding: dict[str, str] | None = None,
) -> Path:
    view = statement_view(pack, financial, book_id)
    history = statement_history(pack, financial, book_id)
    report = history.source
    payloads = {
        "statement-report.json": report.model_dump_json(),
        "statement-history.json": history.model_dump_json(),
        "view.json": view.model_dump_json(),
        "candidate.html": render(view),
    }
    receipt = {
        "schema_version": "statement-preview/2",
        "pack_sha256": pack.content_hash(),
        "review_sha256": financial.content_hash(),
        "statement_sha256": report.content_hash(),
        "history_sha256": history.content_hash(),
        "analytical_qualification": "unrun",
        "module_acceptance": "unrun",
        "browser_acceptance": "unrun",
        "execution_binding": execution_binding,
        "files": {name: hashlib.sha256(raw.encode()).hexdigest() for name, raw in payloads.items()},
    }
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        (destination / name).write_text(raw, encoding="utf-8")
    (destination / "complete.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return destination / "candidate.html"
