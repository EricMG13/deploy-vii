"""Complete r14 statement coverage with source/normalized data kept distinct."""

import hashlib
from datetime import date
from decimal import Decimal
from typing import Literal

from deploy_vii.contracts import Citation, Contract, Hash, Identifier, Text
from deploy_vii.financial_contracts import FinancialBook, FinancialReview, StatementLine
from deploy_vii.financial_validation import validate_financial_review
from deploy_vii.model.history import OUTFLOW_METRICS
from deploy_vii.preparation import PreparedPack
from deploy_vii.statement_validation import ACCOUNT_LINKS, REQUIRED_ITEMS


class StatementCell(Contract):
    statement: Literal["IS", "CFS", "BS"]
    table_id: Literal["T4.4", "T4.5", "T4.6"]
    period_id: Identifier
    item_id: Identifier
    line_id: Identifier | None
    label: Text
    display_priority: int
    line_kind: Literal["detail", "subtotal", "total"]
    observation_id: Identifier | None
    status: Literal["known", "missing", "conflicting", "not_applicable"]
    source_amount: Decimal | None
    normalized_amount: Decimal | None
    value_class: Literal["source", "normalized"]
    normalization: Literal["identity", "negative absolute source amount"]
    normalization_id: Identifier | None
    citations: tuple[Citation, ...]
    limitation: Text | None


class StatementReport(Contract):
    schema_version: Literal["financial-statements/1"] = "financial-statements/1"
    run_id: Identifier
    issuer_id: Identifier
    as_of: date
    method_version: Literal["deploy-v-r14"] = "deploy-v-r14"
    pack_sha256: Hash
    review_sha256: Hash
    book_id: Identifier
    currency: Text
    unit: Text
    entity_perimeter: Text
    accounting_basis: Text
    cells: tuple[StatementCell, ...]
    limitations: tuple[Text, ...]


def _cell(
    statement: Literal["IS", "CFS", "BS"],
    pid: str,
    item: str,
    row: StatementLine | None,
    priority: int,
) -> StatementCell:
    value = row.value if row else None
    raw = value.amount if value else None
    outflow = (row is not None and row.sign_convention == "outflow_magnitude") or ACCOUNT_LINKS.get(
        (statement, item)
    ) in OUTFLOW_METRICS
    changed = outflow and raw is not None and raw > 0
    amount = raw.copy_abs().copy_negate() if raw is not None and outflow else raw
    table: Literal["T4.4", "T4.5", "T4.6"] = (
        "T4.4" if statement == "IS" else "T4.5" if statement == "CFS" else "T4.6"
    )
    return StatementCell(
        statement=statement,
        table_id=table,
        period_id=pid,
        item_id=item,
        line_id=row.line_id if row else None,
        label=row.label if row else item.replace("_", " ").capitalize(),
        display_priority=row.display_priority if row else priority,
        line_kind=row.line_kind if row else "detail",
        observation_id=value.observation_id if value else None,
        status=value.status if value else "missing",
        source_amount=raw,
        normalized_amount=amount,
        value_class="normalized" if changed else "source",
        normalization="negative absolute source amount" if changed else "identity",
        normalization_id=("norm:" + hashlib.sha256(value.observation_id.encode()).hexdigest())
        if changed and value
        else None,
        citations=()
        if value is None
        else tuple(
            dict.fromkeys(
                (
                    *value.citations,
                    *(row.sign_citations if row else ()),
                    *(c for a in value.alternatives for c in a.citations),
                )
            )
        ),
        limitation=value.reason if value else "Required statement item not supplied",
    )


def _cells(book: FinancialBook) -> tuple[StatementCell, ...]:
    cells: list[StatementCell] = []
    for statement in ("IS", "CFS", "BS"):
        for period in book.periods:
            if statement != "BS" and period.period_type == "PERIOD_END":
                continue
            rows = sorted(
                (
                    r
                    for r in book.statement_lines
                    if r.statement == statement and r.period_id == period.period_id
                ),
                key=lambda r: r.display_priority,
            )
            # Source order remains intact. Missing required rows follow it rather
            # than pushing issuer-specific disclosures out of a fixed template.
            for row in rows:
                cells.append(
                    _cell(row.statement, period.period_id, row.item_id, row, row.display_priority)
                )
            supplied = {r.item_id for r in rows}
            priority = max((r.display_priority for r in rows), default=0)
            for item in REQUIRED_ITEMS[statement]:
                if item not in supplied:
                    priority += 1
                    cells.append(_cell(statement, period.period_id, item, None, priority))
    return tuple(cells)


def statement_report(pack: PreparedPack, review: FinancialReview, book_id: str) -> StatementReport:
    issues = validate_financial_review(pack, review)
    if issues:
        raise ValueError("; ".join(issues))
    review = FinancialReview.model_validate_json(review.model_dump_json())
    book = next((b for b in review.books if b.book_id == book_id), None)
    if book is None:
        raise ValueError(f"Unknown financial book: {book_id}")
    return StatementReport(
        run_id=review.run_id,
        issuer_id=review.issuer_id,
        as_of=review.as_of,
        pack_sha256=review.pack_sha256,
        review_sha256=review.content_hash(),
        book_id=book_id,
        currency=book.currency,
        unit=book.unit,
        entity_perimeter=book.entity_perimeter,
        accounting_basis=book.accounting_basis,
        cells=_cells(book),
        limitations=(
            "Source and sign-normalized statements only; no calculated or analyst-judgment "
            "figures are presented as source values",
            *book.limitations,
        ),
    )


def validate_statement_report(
    pack: PreparedPack, review: FinancialReview, report: StatementReport
) -> tuple[str, ...]:
    try:
        report = StatementReport.model_validate_json(report.model_dump_json())
        expected = statement_report(pack, review, report.book_id)
    except ValueError as error:
        return (f"Invalid statement inputs: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Statement artifact differs from deterministic recomputation",)
    )
