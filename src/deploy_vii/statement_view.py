"""Source-period statement preview; not a completed CP-1 handoff or acceptance."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from deploy_vii.contracts import Fact, ModuleView, ReportTable, TableColumn, TableRow, View
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.financial_periods import _id
from deploy_vii.preparation import PreparedPack
from deploy_vii.render import empty_view, render
from deploy_vii.statement_output import StatementCell, statement_report

_PREVIEW_LIMIT = (
    "Source-period statement preview only. Derived-period statements, the remaining CP-1 "
    "registers, canonical Markdown and final module validation are not delivered here. "
    "This preview does not accept CP-1 or qualify analytical judgments."
)


def statement_view(pack: PreparedPack, financial: FinancialReview, book_id: str) -> View:
    report = statement_report(pack, financial, book_id)
    book = next(book for book in financial.books if book.book_id == book_id)
    scale = {"UNITS": Decimal(1), "THOUSANDS": Decimal(1000), "MILLIONS": Decimal(1000000)}[
        book.unit
    ]
    facts: list[Fact] = []
    tables: list[ReportTable] = []
    for table_id, statement, title in (
        ("T4.4", "IS", "Income statement"),
        ("T4.5", "CFS", "Cash flow statement"),
        ("T4.6", "BS", "Balance sheet"),
    ):
        periods = tuple(
            p for p in book.periods if statement == "BS" or p.period_type != "PERIOD_END"
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
        limitations=(_PREVIEW_LIMIT, *report.limitations),
    )
    return View(
        run=pack.run,
        mode="candidate",
        sources=pack.sources,
        modules=tuple(module if m.module_id == "CP-1" else m for m in empty_view(pack.run).modules),
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
    report = statement_report(pack, financial, book_id)
    payloads = {
        "statement-report.json": report.model_dump_json(),
        "view.json": view.model_dump_json(),
        "candidate.html": render(view),
    }
    receipt = {
        "schema_version": "statement-preview/1",
        "pack_sha256": pack.content_hash(),
        "review_sha256": financial.content_hash(),
        "statement_sha256": report.content_hash(),
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
