"""Source-register reconciliations, never an analytical or Model-readiness verdict.

Checks compare independent reported values where available. In particular, the
Model's residual-defined CFO cannot prove its own source statement reconciles.
"""

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import Literal, Self

from pydantic import model_validator

from deploy_vii.audit_basis import annual_warning
from deploy_vii.contracts import Citation, Contract, Hash, Identifier, Text
from deploy_vii.financial_contracts import (
    AuditBasisExplanation,
    CashMovementBridge,
    FinancialBook,
    FinancialPeriod,
    FinancialReview,
    Observation,
    StatementIdentity,
)
from deploy_vii.financial_validation import validate_financial_review
from deploy_vii.model._cells import CONTEXT
from deploy_vii.model.dates import fiscal_year_number
from deploy_vii.model.history import FLOW_METRICS
from deploy_vii.preparation import PreparedPack
from deploy_vii.statement_validation import account_outflow, effective_accounts

CheckType = Literal[
    "SEGMENT_REVENUE",
    "EBITDA_BRIDGE",
    "ADJUSTED_EBITDA_BRIDGE",
    "CFO_IDENTITY",
    "DEBT_TOTAL_EX_LEASES",
    "NCF_CASH_MOVEMENT",
    "FY_QUARTERS",
    "SOURCE_STATEMENT_IDENTITY",
    "REPORTED_DERIVED_PERIOD",
]


class ReconciliationTerm(Contract):
    label: Text
    observation_id: Identifier | None
    original_amount: Decimal | None
    amount: Decimal | None
    coefficient: Literal[-1, 1] = 1
    reason: Text | None = None
    citations: tuple[Citation, ...]

    @model_validator(mode="after")
    def missing_reason(self) -> Self:
        if self.amount is None and self.reason is None:
            raise ValueError("missing reconciliation term requires a reason")
        if self.amount is not None and self.reason is not None:
            raise ValueError("known reconciliation term cannot carry a missing reason")
        return self


class Reconciliation(Contract):
    check_id: Identifier
    period_id: Identifier
    check_type: CheckType
    metric_id: Identifier
    reported: ReconciliationTerm
    components: tuple[ReconciliationTerm, ...]
    reported_value: Decimal | None
    calculated_value: Decimal | None
    difference: Decimal | None
    tolerance: Decimal | None
    status: Literal["PASS", "WARN", "BLOCK"]
    formula: Text
    explanation: Text
    context_citations: tuple[Citation, ...]
    audit_basis_explanation: AuditBasisExplanation | None = None
    cash_movement_bridges: tuple[CashMovementBridge, ...] = ()


class ReconciliationReport(Contract):
    schema_version: Literal["financial-reconciliation/3"] = "financial-reconciliation/3"
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
    checks: tuple[Reconciliation, ...]
    limitations: tuple[Text, ...]


def _term(
    label: str,
    value: Observation | None,
    *,
    coefficient: Literal[-1, 1] = 1,
    outflow: bool = False,
) -> ReconciliationTerm:
    amount = value.amount if value else None
    citations = (
        ()
        if value is None
        else tuple(
            dict.fromkeys(
                (
                    *value.citations,
                    *(c for a in value.alternatives for c in a.citations),
                )
            )
        )
    )
    return ReconciliationTerm(
        label=label,
        observation_id=value.observation_id if value else None,
        original_amount=amount,
        amount=amount.copy_abs().copy_negate() if outflow and amount is not None else amount,
        coefficient=coefficient,
        reason=None if amount is not None else (value.reason if value else "Not supplied"),
        citations=citations,
    )


def _check(
    period: FinancialPeriod,
    kind: CheckType,
    metric: str,
    reported: ReconciliationTerm,
    components: tuple[ReconciliationTerm, ...],
    formula: str,
    *,
    blocker: str | None = None,
    warning: str | None = None,
    context: tuple[Citation, ...] = (),
) -> Reconciliation:
    """Calculate only complete components; never change a difference to fit tolerance."""
    with localcontext(CONTEXT):
        calculated: Decimal | None = None
        if components and all(term.amount is not None for term in components):
            calculated = sum(
                (term.amount * term.coefficient for term in components if term.amount is not None),
                Decimal(0),
            )
        # A structural blocker makes even a numeric subtotal incomplete.
        if blocker:
            calculated = None
        stated = reported.amount
        tolerance = (
            None if stated is None else Decimal("0.5").scaleb(int(stated.as_tuple().exponent))
        )
        difference = None if stated is None or calculated is None else calculated - stated
        status: Literal["PASS", "WARN", "BLOCK"] = "BLOCK"
        explanation = blocker or "Missing reported value or complete independent components"
        if difference is not None and tolerance is not None:
            if abs(difference) <= tolerance:
                status, explanation = "PASS", "Agrees within half the last reported decimal place"
            else:
                explanation = "Difference exceeds reporting-precision tolerance; unresolved"
        if warning and not blocker:
            status, explanation = "WARN", warning
    identity = json.dumps((period.period_id, kind, metric), separators=(",", ":"))
    return Reconciliation(
        check_id="recon:" + hashlib.sha256(identity.encode()).hexdigest(),
        period_id=period.period_id,
        check_type=kind,
        metric_id=metric,
        reported=reported,
        components=components,
        reported_value=stated,
        calculated_value=calculated,
        difference=difference,
        tolerance=tolerance,
        status=status,
        formula=formula,
        explanation=explanation,
        context_citations=tuple(dict.fromkeys((*period.citations, *context))),
    )


def _account(
    book: FinancialBook, period_id: str, metric: str, *, sign: Literal[-1, 1] = 1
) -> ReconciliationTerm:
    value = next(
        (
            r.value
            for r in effective_accounts(book)
            if r.period_id == period_id and r.metric_id == metric
        ),
        None,
    )
    return _term(metric, value, coefficient=sign, outflow=account_outflow(book, period_id, metric))


def _balance(
    book: FinancialBook, day: date | None, metric: str, *, sign: Literal[-1, 1] = 1
) -> ReconciliationTerm:
    ids = {p.period_id for p in book.periods if day is not None and p.end_date == day}
    rows = [
        r.value for r in effective_accounts(book) if r.period_id in ids and r.metric_id == metric
    ]
    conflict = next((v for v in rows if v.status == "conflicting"), None)
    value = conflict or next((v for v in rows if v.amount is not None), next(iter(rows), None))
    return _term(metric, value, coefficient=sign)


def _segments(book: FinancialBook, period: FinancialPeriod) -> Reconciliation:
    rows = {r.segment_id: r for r in book.segments if r.period_id == period.period_id}
    ids = tuple(dict.fromkeys(r.segment_id for r in book.segments))
    terms = tuple(_term(sid, rows[sid].revenue if sid in rows else None) for sid in ids)
    disclosure = book.segment_disclosure
    undisclosed = not book.segments and disclosure.status in {"not_disclosed", "not_applicable"}
    return _check(
        period,
        "SEGMENT_REVENUE",
        "revenue",
        _account(book, period.period_id, "revenue"),
        terms,
        "sum(operating segment revenue and separate corporate/elimination revenue)",
        blocker="Disclosed segment schedule is incomplete"
        if disclosure.status == "partial"
        else None,
        warning="No segment schedule disclosed; calculated total is unknown, not zero"
        if undisclosed
        else None,
        context=(
            *disclosure.citations,
            *(c for r in rows.values() for c in r.classification_citations),
        ),
    )


def _income(book: FinancialBook, period: FinancialPeriod) -> tuple[Reconciliation, ...]:
    pid = period.period_id
    parts = [
        _account(book, pid, "revenue"),
        _account(book, pid, "opex_including_da"),
        _account(book, pid, "depreciation_amortization", sign=-1),
    ]
    if period.expense_presentation != "by_nature":
        parts.insert(1, _account(book, pid, "cogs"))
    ebitda = _check(
        period,
        "EBITDA_BRIDGE",
        "ebitda",
        _account(book, pid, "ebitda"),
        tuple(parts),
        "revenue + signed COGS (by-function only) + signed opex including D&A - signed D&A",
        blocker="Expense presentation is unknown"
        if period.expense_presentation == "unknown"
        else None,
        context=period.presentation_citations,
    )
    rows = {r.addback_id: r for r in book.addbacks if r.period_id == pid}
    ids = tuple(dict.fromkeys(r.addback_id for r in book.addbacks))
    adjustments = tuple(_term(aid, rows[aid].value if aid in rows else None) for aid in ids)
    disclosure = book.addback_disclosure
    adjusted = _check(
        period,
        "ADJUSTED_EBITDA_BRIDGE",
        "adjusted_ebitda",
        _account(book, pid, "adjusted_ebitda"),
        (_account(book, pid, "ebitda"), *adjustments),
        "reported EBITDA + each separately identified add-back",
        blocker="Add-back bridge is incomplete or undisclosed"
        if disclosure.status in {"partial", "not_disclosed"}
        else None,
        context=(
            *disclosure.citations,
            *(c for r in rows.values() for c in r.classification_citations),
        ),
    )
    return ebitda, adjusted


def _debt(book: FinancialBook, period: FinancialPeriod) -> Reconciliation:
    """Use same-date carrying values, excluding both lease classes; no FX inference."""
    ids = {p.period_id for p in book.periods if period.end_date and p.end_date == period.end_date}
    templates = {r.facility_id: r for r in book.facilities}
    values_by_id: dict[str, list[Observation]] = {}
    citations_by_id: dict[str, list[Citation]] = {}
    for row in book.facilities:
        if row.period_id in ids:
            values_by_id.setdefault(row.facility_id, []).append(row.carrying_value)
            citations_by_id.setdefault(row.facility_id, []).extend(row.terms_citations)
    terms: list[ReconciliationTerm] = []
    context: list[Citation] = []
    blockers: list[str] = []
    for fid, template in templates.items():
        context.extend(citations_by_id.get(fid, ()))
        if template.facility_type != "DEBT ADJUSTMENT" and template.lease_classification in {
            "OPERATING_LEASE",
            "FINANCE_LEASE",
        }:
            continue
        values = values_by_id.get(fid, [])
        value = next((v for v in values if v.status == "conflicting"), None)
        value = value or next((v for v in values if v.amount is not None), next(iter(values), None))
        if template.currency != book.currency:
            blockers.append(f"{fid}: foreign currency has no explicit conversion")
        terms.append(_term(fid, value))
    return _check(
        period,
        "DEBT_TOTAL_EX_LEASES",
        "total_debt",
        _balance(book, period.end_date, "total_debt"),
        tuple(terms),
        "sum(non-lease carrying values, including separately sourced debt adjustments)",
        blocker="; ".join(blockers) or None,
        context=tuple(context),
    )


def _identity_terms(
    book: FinancialBook,
    identity: StatementIdentity,
) -> tuple[tuple[ReconciliationTerm, ...], tuple[Citation, ...]]:
    """Expand validated identities to source leaves; never reuse a reported plug.

    Repeated opposite-signed leaves stay present, so unknown operands cannot
    disappear through algebraic cancellation. Validation bounds expansion/depth.
    """
    lines = {r.line_id: r for r in book.statement_lines if r.period_id == identity.period_id}
    equations = {
        r.target_line_id: r for r in book.statement_identities if r.period_id == identity.period_id
    }
    terms: list[ReconciliationTerm] = []
    context: list[Citation] = []

    def expand(equation: StatementIdentity, inherited_sign: Literal[-1, 1]) -> None:
        context.extend(equation.citations)
        source = lines[equation.target_line_id].value
        context.extend(source.citations)
        context.extend(c for alternative in source.alternatives for c in alternative.citations)
        for component in equation.components:
            # Multiplying two exact integer signs gives +1 when they agree.
            coefficient: Literal[-1, 1] = 1 if component.coefficient == inherited_sign else -1
            if component.line_id in equations:
                expand(equations[component.line_id], coefficient)
            else:
                terms.append(
                    _term(
                        component.line_id, lines[component.line_id].value, coefficient=coefficient
                    )
                )

    expand(identity, 1)
    return tuple(terms), tuple(dict.fromkeys(context))


def _statement_check(
    book: FinancialBook,
    period: FinancialPeriod,
    statement: str,
    item: str,
    kind: CheckType,
) -> Reconciliation:
    lines = {r.line_id: r for r in book.statement_lines if r.period_id == period.period_id}
    target = next(
        (r for r in lines.values() if r.statement == statement and r.item_id == item), None
    )
    identity = next(
        (
            r
            for r in book.statement_identities
            if target is not None
            and r.period_id == period.period_id
            and r.target_line_id == target.line_id
        ),
        None,
    )
    disclosure = next(
        (
            r.disclosure
            for r in book.statement_disclosures
            if r.statement == statement and r.period_id == period.period_id
        ),
        None,
    )
    terms, context = ((), ()) if identity is None else _identity_terms(book, identity)
    reported = _term(item, target.value) if target else _account(book, period.period_id, item)
    complete = identity is not None and disclosure is not None and disclosure.status == "complete"
    return _check(
        period,
        kind,
        f"{statement}:{item}" if kind == "SOURCE_STATEMENT_IDENTITY" else item,
        reported,
        terms,
        " + ".join(f"({term.coefficient}) * {term.label}" for term in terms)
        if identity
        else "independent source statement components",
        blocker=None
        if complete
        else "Full source statement and independent component identity are not assessed complete",
        context=(
            *context,
            *(disclosure.citations if disclosure else ()),
        ),
    )


def _cash_movement(book: FinancialBook, period: FinancialPeriod) -> Reconciliation:
    opening = (
        period.start_date - timedelta(days=1)
        if period.start_date and period.start_date.toordinal() > 1
        else None
    )
    bridge = next((b for b in book.cash_movement_bridges if b.period_id == period.period_id), None)
    lines = {r.line_id: r for r in book.statement_lines if r.period_id == period.period_id}
    adjustments = tuple(
        _term(
            part.line_id,
            lines[part.line_id].value,
            coefficient=-1 if part.coefficient == 1 else 1,
            outflow=lines[part.line_id].sign_convention == "outflow_magnitude",
        )
        for part in (bridge.components if bridge else ())
    )
    ncf = _check(
        period,
        "NCF_CASH_MOVEMENT",
        "net_cash_change",
        _account(book, period.period_id, "net_cash_change"),
        (
            _balance(book, period.end_date, "cash_and_equivalents"),
            _balance(book, opening, "cash_and_equivalents", sign=-1),
            *adjustments,
        ),
        "closing cash - opening cash - signed source adjustments"
        if bridge
        else "closing cash - opening cash; no inferred FX or other cash adjustment",
        context=(
            *bridge.citations,
            *(c for part in bridge.components for c in lines[part.line_id].sign_citations),
        )
        if bridge
        else (),
    )
    return ncf.model_copy(update={"cash_movement_bridges": (bridge,) if bridge else ()})


def _cash(book: FinancialBook, period: FinancialPeriod) -> tuple[Reconciliation, ...]:
    return (
        _statement_check(book, period, "CFS", "cfo_ncfo", "CFO_IDENTITY"),
        _cash_movement(book, period),
    )


def _year(book: FinancialBook, period: FinancialPeriod) -> tuple[Reconciliation, ...]:
    quarters = sorted(
        (
            p
            for p in book.periods
            if p.period_type == "QUARTER"
            and fiscal_year_number(p.fiscal_year) == fiscal_year_number(period.fiscal_year)
        ),
        key=lambda p: p.fiscal_quarter or 0,
    )
    complete = len(quarters) == 4 and all(p.start_date and p.end_date for p in quarters)
    complete = (
        complete
        and quarters[0].start_date == period.start_date
        and quarters[-1].end_date == period.end_date
    )
    complete = complete and all(
        a.end_date and b.start_date and a.end_date + timedelta(days=1) == b.start_date
        for a, b in pairwise(quarters)
    )
    checks: list[Reconciliation] = []
    for metric in sorted(FLOW_METRICS):
        check = _check(
            period,
            "FY_QUARTERS",
            metric,
            _account(book, period.period_id, metric),
            tuple(_account(book, q.period_id, metric) for q in quarters),
            "sum(four discrete quarters); reported FY remains independent",
            blocker=None
            if complete
            else "Four dated discrete quarters do not span the reported FY",
            context=tuple(c for q in quarters for c in q.citations),
        )
        explanation = annual_warning(
            book,
            period.period_id,
            metric,
            tuple(q.period_id for q in quarters),
            check.difference,
            check.tolerance,
        )
        if explanation is not None:
            check = check.model_copy(
                update={
                    "status": "WARN",
                    "explanation": "Audited FY / unaudited quarter basis difference: "
                    + explanation.explanation,
                    "audit_basis_explanation": explanation,
                    "context_citations": tuple(
                        dict.fromkeys((*check.context_citations, *explanation.citations))
                    ),
                }
            )
        checks.append(check)
    return tuple(checks)


def reconcile_financials(
    pack: PreparedPack, review: FinancialReview, book_id: str
) -> ReconciliationReport:
    """Reconcile supplied periods only; no inferred source rows or readiness promotion."""
    issues = validate_financial_review(pack, review)
    if issues:
        raise ValueError("; ".join(issues))
    review = FinancialReview.model_validate_json(review.model_dump_json())
    book = next((b for b in review.books if b.book_id == book_id), None)
    if book is None:
        raise ValueError(f"Unknown financial book: {book_id}")
    checks: list[Reconciliation] = []
    for period in book.periods:
        checks.append(_debt(book, period))
        targets = {
            r.target_line_id for r in book.statement_identities if r.period_id == period.period_id
        }
        checks.extend(
            _statement_check(book, period, row.statement, row.item_id, "SOURCE_STATEMENT_IDENTITY")
            for row in book.statement_lines
            if row.period_id == period.period_id and row.line_id in targets
        )
        if period.period_type != "PERIOD_END":
            checks.extend((_segments(book, period), *_income(book, period), *_cash(book, period)))
        if period.period_type == "FY":
            checks.extend(_year(book, period))
    return ReconciliationReport(
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
        checks=tuple(checks),
        limitations=(
            "Source-register checks only; derived-period calculation and full statement "
            "coverage remain separate",
            "CFO identity requires a complete source statement "
            "and an independent component identity",
            "Only exact-scope sourced audited-FY explanations permit annual WARN; "
            "unexplained differences, missing inputs and cash/FX differences remain BLOCK",
            *book.limitations,
        ),
    )


def validate_reconciliation_report(
    pack: PreparedPack, review: FinancialReview, report: ReconciliationReport
) -> tuple[str, ...]:
    """Recompute before consuming a supplied artifact; schema shape is not evidence."""
    try:
        report = ReconciliationReport.model_validate_json(report.model_dump_json())
        expected = reconcile_financials(pack, review, report.book_id)
    except ValueError as error:
        return (f"Invalid reconciliation inputs: {error}",)
    if report.content_hash() != expected.content_hash():
        return ("Reconciliation artifact differs from deterministic recomputation",)
    return ()
