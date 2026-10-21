"""Independent account and source-equation checks over constructed historical periods.

Model residuals never enter these comparisons. Shared source observations are
identified explicitly so a construction cannot certify itself as independent.
"""

from datetime import timedelta
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import Literal

from deploy_vii.audit_basis import annual_warning
from deploy_vii.contracts import Citation, Contract, Identifier, Text
from deploy_vii.financial_contracts import AuditBasisExplanation, FinancialBook, FinancialReview
from deploy_vii.financial_periods import (
    HistoricalReport,
    HistoricalValue,
    PeriodConstruction,
    _id,
    historical_report,
)
from deploy_vii.financial_reconciliation import (
    CheckType,
    ReconciliationTerm,
    _account,
    _balance,
    _statement_check,
)
from deploy_vii.model._cells import CONTEXT
from deploy_vii.model.dates import fiscal_year_number
from deploy_vii.model.history import FLOW_METRICS
from deploy_vii.preparation import PreparedPack


class PeriodTerm(Contract):
    label: Text
    value_id: Identifier | None
    amount: Decimal | None
    coefficient: Literal[-1, 1] = 1
    observation_ids: tuple[Identifier, ...]
    citations: tuple[Citation, ...]
    reason: Text | None


class PeriodCheck(Contract):
    check_id: Identifier
    construction_id: Identifier
    check_type: CheckType
    metric_id: Identifier
    reported: PeriodTerm
    components: tuple[PeriodTerm, ...]
    calculated_value: Decimal | None
    difference: Decimal | None
    tolerance: Decimal | None
    independent: bool
    shared_observation_ids: tuple[Identifier, ...]
    status: Literal["PASS", "WARN", "BLOCK"]
    formula: Text
    explanation: Text
    context_citations: tuple[Citation, ...]
    audit_basis_explanation: AuditBasisExplanation | None = None


class PeriodReconciliationReport(Contract):
    schema_version: Literal["period-reconciliation/2"] = "period-reconciliation/2"
    historical: HistoricalReport
    checks: tuple[PeriodCheck, ...]
    limitations: tuple[Text, ...]


def _source(term: ReconciliationTerm, sign: int = 1) -> PeriodTerm:
    return PeriodTerm(
        label=term.label,
        value_id=None,
        amount=term.amount,
        coefficient=1 if term.coefficient == sign else -1,
        observation_ids=(term.observation_id,) if term.observation_id else (),
        citations=term.citations,
        reason=term.reason,
    )


def _cell(row: HistoricalValue | None, label: str, sign: Literal[-1, 1] = 1) -> PeriodTerm:
    return PeriodTerm(
        label=label,
        value_id=row.value_id if row else None,
        amount=row.value.amount if row else None,
        coefficient=sign,
        observation_ids=row.value.observation_ids if row else (),
        citations=row.value.citations if row else (),
        reason=row.value.reason if row else "No historical input value",
    )


def _compare(
    node: PeriodConstruction,
    kind: CheckType,
    metric: str,
    reported: PeriodTerm,
    parts: tuple[PeriodTerm, ...],
    formula: str,
    *,
    blocker: str | None = None,
    warning: str | None = None,
    context: tuple[Citation, ...] = (),
) -> PeriodCheck:
    origins = {oid for part in parts for oid in part.observation_ids}
    shared = tuple(oid for oid in reported.observation_ids if oid in origins)
    with localcontext(CONTEXT):
        calculated = (
            sum((p.amount * p.coefficient for p in parts if p.amount is not None), Decimal(0))
            if parts and all(p.amount is not None for p in parts) and not blocker
            else None
        )
        tolerance = (
            Decimal("0.5").scaleb(int(reported.amount.as_tuple().exponent))
            if reported.amount is not None
            else None
        )
        difference = (
            calculated - reported.amount
            if calculated is not None and reported.amount is not None
            else None
        )
        status: Literal["PASS", "WARN", "BLOCK"] = "BLOCK"
        explanation = blocker or "Reported value or independent components are unavailable"
        if difference is not None and tolerance is not None:
            if abs(difference) > tolerance:
                explanation = "Difference exceeds reporting-precision tolerance; unresolved"
            elif shared:
                status, explanation = (
                    "WARN",
                    "Shared source observations: construction agreement only",
                )
            else:
                status, explanation = "PASS", "Independent agreement within reporting precision"
        if warning and not blocker and difference is None:
            status, explanation = "WARN", warning
    return PeriodCheck(
        check_id=_id("period-check", node.construction_id, kind, metric),
        construction_id=node.construction_id,
        check_type=kind,
        metric_id=metric,
        reported=reported,
        components=parts,
        calculated_value=calculated,
        difference=difference,
        tolerance=tolerance,
        independent=not shared and difference is not None,
        shared_observation_ids=shared,
        status=status,
        formula=formula,
        explanation=explanation,
        context_citations=tuple(dict.fromkeys(context)),
    )


def _source_periods(
    report: HistoricalReport, node: PeriodConstruction
) -> tuple[tuple[str | None, int], ...]:
    """Follow the flow plan to source periods; retain opposite signed terms."""
    nodes = {n.construction_id: n for n in report.constructions}
    periods = {p.period_id: p for p in report.periods}
    result: list[tuple[str | None, int]] = []

    def visit(current: PeriodConstruction, sign: int) -> None:
        if not current.terms:
            result.append((current.own_period_id, sign))
            return
        for term in current.terms:
            coefficient = sign * term.coefficient
            if term.kind == "construction" and term.reference is not None:
                visit(nodes[term.reference], coefficient)
            elif term.kind == "period" and term.reference is not None:
                period = periods[term.reference]
                # The kernel's flow component reads immediate reported children.
                ids = (
                    period.component_period_ids
                    if period.period_type in {"YTD", "FY"} and period.component_period_ids
                    else (period.period_id,)
                )
                result.extend((pid, coefficient) for pid in ids)
            else:
                result.append((None, coefficient))

    visit(node, 1)
    return tuple(result)


def _cfo(
    book: FinancialBook, report: HistoricalReport, node: PeriodConstruction, reported: PeriodTerm
) -> PeriodCheck:
    periods = {p.period_id: p for p in book.periods}
    terms: list[PeriodTerm] = []
    contexts: list[Citation] = []
    blockers: list[str] = []
    for pid, sign in _source_periods(report, node):
        if pid is None:
            terms.append(_cell(None, "Missing period component", 1 if sign == 1 else -1))
            blockers.append("Missing period component")
            continue
        source = _statement_check(book, periods[pid], "CFS", "cfo_ncfo", "CFO_IDENTITY")
        terms.extend(_source(term, sign) for term in source.components)
        contexts.extend(source.context_citations)
        if source.calculated_value is None or (
            source.difference is not None and source.status == "BLOCK"
        ):
            blockers.append(f"{pid}: {source.explanation}")
    return _compare(
        node,
        "CFO_IDENTITY",
        "cfo_ncfo",
        reported,
        tuple(terms),
        "signed period combination of independent source CFO equation leaves",
        blocker=node.limitation or "; ".join(blockers) or None,
        context=tuple(contexts),
    )


def _bridges(
    book: FinancialBook,
    report: HistoricalReport,
    node: PeriodConstruction,
    rows: dict[tuple[str, str], HistoricalValue],
) -> tuple[PeriodCheck, ...]:
    def account(key: str, sign: Literal[-1, 1] = 1) -> PeriodTerm:
        return _cell(rows.get((node.construction_id, "acct:" + key)), key, sign)

    def series(prefix: str, ids: tuple[str, ...]) -> tuple[PeriodTerm, ...]:
        return tuple(_cell(rows.get((node.construction_id, prefix + key)), key) for key in ids)

    periods = {p.period_id: p for p in book.periods}
    source_periods = _source_periods(report, node)
    presentations = {
        periods[pid].expense_presentation if pid else "unknown" for pid, _ in source_periods
    }
    presentation_issue = (
        None
        if presentations in ({"by_function"}, {"by_nature"})
        else ("Mixed or unknown expense presentation requires an explicit comparable bridge")
    )
    income: tuple[PeriodTerm, ...] = (
        account("revenue"),
        account("opex_including_da"),
        account("depreciation_amortization", -1),
    )
    if presentations != {"by_nature"}:
        income = (income[0], account("cogs"), *income[1:])
    segments = tuple(dict.fromkeys(r.segment_id for r in book.segments))
    addbacks = tuple(dict.fromkeys(r.addback_id for r in book.addbacks))
    facilities = {r.facility_id: r for r in book.facilities}
    debt = tuple(
        fid
        for fid, row in facilities.items()
        if row.facility_type == "DEBT ADJUSTMENT"
        or row.lease_classification not in {"FINANCE_LEASE", "OPERATING_LEASE"}
    )
    foreign = any(facilities[fid].currency != book.currency for fid in debt)
    opening = (
        node.start_date - timedelta(days=1)
        if node.start_date and node.start_date.toordinal() > 1
        else None
    )
    undisclosed = not segments and book.segment_disclosure.status in {
        "not_disclosed",
        "not_applicable",
    }
    return (
        _compare(
            node,
            "SEGMENT_REVENUE",
            "revenue",
            account("revenue"),
            series("bu:", segments),
            "sum(segment revenue including corporate/eliminations)",
            blocker=node.limitation
            or (
                "Disclosed segment schedule is partial"
                if book.segment_disclosure.status == "partial"
                else None
            ),
            warning="Segment schedule is not disclosed; total stays unknown"
            if undisclosed
            else None,
            context=book.segment_disclosure.citations,
        ),
        _compare(
            node,
            "EBITDA_BRIDGE",
            "ebitda",
            account("ebitda"),
            income,
            "revenue + signed COGS (by-function only) + signed opex - signed D&A",
            blocker=node.limitation or presentation_issue,
            context=tuple(
                c for pid, _ in source_periods if pid for c in periods[pid].presentation_citations
            ),
        ),
        _compare(
            node,
            "ADJUSTED_EBITDA_BRIDGE",
            "adjusted_ebitda",
            account("adjusted_ebitda"),
            (account("ebitda"), *series("addback:", addbacks)),
            "reported EBITDA + each stable add-back separately",
            blocker=node.limitation,
            context=book.addback_disclosure.citations,
        ),
        _compare(
            node,
            "DEBT_TOTAL_EX_LEASES",
            "total_debt",
            account("total_debt"),
            series("fac:", debt),
            "closing non-lease facility carrying values including debt adjustments",
            blocker="Foreign carrying value requires explicit conversion" if foreign else None,
            context=tuple(c for row in book.facilities for c in row.terms_citations),
        ),
        _cfo(book, report, node, account("cfo_ncfo")),
        _compare(
            node,
            "NCF_CASH_MOVEMENT",
            "net_cash_change",
            account("net_cash_change"),
            (
                account("cash_and_equivalents"),
                _source(_balance(book, opening, "cash_and_equivalents", sign=-1)),
            ),
            "closing cash - opening cash; no inferred FX plug",
            blocker=node.limitation,
        ),
    )


def _years(
    book: FinancialBook, report: HistoricalReport, rows: dict[tuple[str, str], HistoricalValue]
) -> tuple[PeriodCheck, ...]:
    checks: list[PeriodCheck] = []
    for node in report.constructions:
        if node.kind != "FY" or node.own_period_id is None:
            continue
        quarters = sorted(
            (
                n
                for n in report.constructions
                if n.kind == "QUARTER"
                and fiscal_year_number(n.fiscal_year) == fiscal_year_number(node.fiscal_year)
            ),
            key=lambda n: n.fiscal_quarter or 0,
        )
        complete = len(quarters) == 4 and {q.fiscal_quarter for q in quarters} == {1, 2, 3, 4}
        complete = (
            complete
            and node.start_date is not None
            and node.end_date is not None
            and quarters[0].start_date == node.start_date
            and quarters[-1].end_date == node.end_date
        )
        complete = complete and all(
            a.end_date is not None
            and b.start_date is not None
            and a.end_date.toordinal() + 1 == b.start_date.toordinal()
            for a, b in pairwise(quarters)
        )
        for metric in sorted(FLOW_METRICS):
            check = _compare(
                node,
                "FY_QUARTERS",
                metric,
                _source(_account(book, node.own_period_id, metric)),
                tuple(
                    _cell(rows.get((q.construction_id, "acct:" + metric)), q.column_key)
                    for q in quarters
                ),
                "reported FY compared with four discrete constructed quarters",
                blocker=None if complete else "Four dated quarters do not span the reported FY",
            )
            explanation = annual_warning(
                book,
                node.own_period_id,
                metric,
                tuple(q.own_period_id if not q.terms else None for q in quarters),
                check.difference if check.independent else None,
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


def _stated(
    book: FinancialBook, report: HistoricalReport, rows: dict[tuple[str, str], HistoricalValue]
) -> tuple[PeriodCheck, ...]:
    return tuple(
        _compare(
            node,
            "REPORTED_DERIVED_PERIOD",
            metric,
            _source(_account(book, node.stated_period_id, metric)),
            (_cell(rows.get((node.construction_id, "acct:" + metric)), metric),),
            "separately reported value compared with constructed-period input",
            blocker=node.limitation,
        )
        for node in report.constructions
        if node.terms and node.stated_period_id is not None
        for metric in sorted(FLOW_METRICS)
    )


def reconcile_periods(
    pack: PreparedPack, review: FinancialReview, book_id: str
) -> PeriodReconciliationReport:
    historical = historical_report(pack, review, book_id)
    review = FinancialReview.model_validate_json(review.model_dump_json())
    book = next(b for b in review.books if b.book_id == book_id)
    rows = {(v.construction_id, v.series_key): v for v in historical.values}
    checks = tuple(
        check
        for node in historical.constructions
        if node.construction_id in historical.columns
        for check in _bridges(book, historical, node, rows)
    )
    return PeriodReconciliationReport(
        historical=historical,
        checks=(*checks, *_years(book, historical, rows), *_stated(book, historical, rows)),
        limitations=(
            "Historical account/source-equation comparisons only; "
            "no Model readiness or analytical acceptance",
            "Shared observations imply construction agreement, never independent verification",
            "Only exact-scope sourced audited-FY explanations permit annual WARN; "
            "no inferred FX or residual-defined proof",
            "Mixed expense presentations require an explicitly comparable source bridge",
        ),
    )


def validate_period_reconciliation(
    pack: PreparedPack, review: FinancialReview, report: PeriodReconciliationReport
) -> tuple[str, ...]:
    try:
        report = PeriodReconciliationReport.model_validate_json(report.model_dump_json())
        expected = reconcile_periods(pack, review, report.historical.book_id)
    except ValueError as error:
        return (f"Invalid period reconciliation inputs: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Period reconciliation differs from deterministic recomputation",)
    )
