"""Validated source observations to the internal Model, without omission-as-zero.

The FinancialReview remains the canonical, hash-bound source artifact. Kernel
SourceRefs point to its observation IDs, never masquerade as original documents.
"""

from decimal import Decimal

from deploy_vii.contracts import Citation
from deploy_vii.financial_contracts import (
    ACCOUNT_IDS,
    FacilityObservation,
    FinancialBook,
    FinancialReview,
    Observation,
)
from deploy_vii.financial_validation import records, validate_financial_review
from deploy_vii.model.frame import SourceRef
from deploy_vii.model.history import BALANCE_METRICS
from deploy_vii.model.registers import (
    AccountRow,
    AddbackRow,
    Cp1Registers,
    FacilityRow,
    KpiRow,
    PeriodRow,
    PfAdjustmentRow,
    SegmentRow,
)
from deploy_vii.preparation import PreparedPack


def _ref(value: Observation | None) -> SourceRef | None:
    return (
        None
        if value is None
        else SourceRef(value.observation_id, "financial-observation", str(value.amount))
    )


def _accounts(book: FinancialBook) -> tuple[AccountRow, ...]:
    supplied = {(row.metric_id, row.period_id): row.value for row in book.accounts}
    periods = {period.period_id: period for period in book.periods}
    conflicted = {
        (row.metric_id, periods[row.period_id].end_date)
        for row in book.accounts
        if row.metric_id in BALANCE_METRICS and row.value.status == "conflicting"
    }
    result: list[AccountRow] = []
    for period in book.periods:
        for metric in sorted(ACCOUNT_IDS):
            observation = supplied.get((metric, period.period_id))
            if (
                observation is None
                and period.component_period_ids
                and metric in {"lease_payments_in_financing", "interest_paid_in_financing"}
            ):
                # Explicit components may compute an unreported aggregate. Leaf
                # omissions still become null, so partial components cannot sum.
                continue
            value = observation.amount if observation else None
            if (metric, period.end_date) in conflicted:
                value = None
            status = "VERIFIED" if value is not None else "PARTIAL"
            if metric == "cogs" and period.expense_presentation == "by_nature":
                status = "NOT AVAILABLE"
            result.append(AccountRow(metric, period.period_id, value, status, _ref(observation)))
    return tuple(result)


def _facilities(book: FinancialBook) -> tuple[FacilityRow, ...]:
    supplied = {(row.facility_id, row.period_id): row for row in book.facilities}
    templates = {row.facility_id: row for row in book.facilities}
    # Prefer the last dated row, retaining each facility's first insertion position.
    templates.update({row.facility_id: row for row in book.facilities if row.issued_on})
    periods = {period.period_id: period for period in book.periods}
    conflicted = {
        (row.facility_id, periods[row.period_id].end_date)
        for row in book.facilities
        if row.carrying_value.status == "conflicting"
    }
    result: list[FacilityRow] = []
    for period in book.periods:
        for facility_id, template in templates.items():
            supplied_row = supplied.get((facility_id, period.period_id))
            row = supplied_row or template
            carrying = row.carrying_value.amount if supplied_row else None
            source = _ref(row.carrying_value) if supplied_row else None
            if (facility_id, period.end_date) in conflicted:
                carrying = None
            elif (
                supplied_row is None
                and row.issued_on
                and period.end_date
                and row.issued_on > period.end_date
            ):
                carrying = Decimal(0)
                source = SourceRef(facility_id, f"facility-issuance:{book.book_id}", "0")
            result.append(
                _facility(row, period.period_id, supplied_row is not None, carrying, source)
            )
    return tuple(result)


def _facility(
    row: FacilityObservation,
    period_id: str,
    supplied: bool,
    carrying: Decimal | None,
    source: SourceRef | None,
) -> FacilityRow:
    return FacilityRow(
        facility_id=row.facility_id,
        facility_name=row.facility_name,
        period_id=period_id,
        facility_type=row.facility_type,
        currency=row.currency,
        carrying_value=carrying,
        commitment=row.commitment.amount if supplied else None,
        drawn_amount=row.drawn_amount.amount if supplied else None,
        secured_status=row.secured_status,
        seniority=row.seniority,
        lease_classification=row.lease_classification,
        maturity_date=row.maturity_date.isoformat() if supplied and row.maturity_date else None,
        margin_or_coupon=row.margin_or_coupon if supplied else "Not stated",
        rate_type=row.rate_type if supplied else "NOT_STATED",
        reference_rate=row.reference_rate if supplied else "NOT_STATED",
        spread_bps=row.spread_bps.amount if supplied else None,
        floor_bps=row.floor_bps.amount if supplied else None,
        fixed_rate=row.fixed_rate.amount if supplied else None,
        annual_amortisation=row.annual_amortisation.amount if supplied else None,
        source=source,
        terms_out_of_range=row.fixed_rate.amount is not None
        and not Decimal("0.5") <= row.fixed_rate.amount <= Decimal(30),
    )


def _periods(book: FinancialBook) -> tuple[PeriodRow, ...]:
    result: list[PeriodRow] = []
    for period in book.periods:
        days = period.day_count
        if days is None and period.start_date and period.end_date:
            days = (period.end_date - period.start_date).days + 1
        result.append(
            PeriodRow(
                period.period_id,
                period.fiscal_year,
                str(period.fiscal_quarter) if period.fiscal_quarter is not None else None,
                period.period_type,
                period.start_date.isoformat() if period.start_date else None,
                period.end_date.isoformat() if period.end_date else None,
                days,
                period.currency,
                period.unit,
                period.component_period_ids,
            )
        )
    return tuple(result)


def _addbacks(book: FinancialBook) -> tuple[AddbackRow, ...]:
    if book.addback_disclosure.status in {"partial", "not_disclosed"}:
        raise ValueError("Model requires an assessed complete add-back bridge; missing is not zero")
    supplied = {(row.addback_id, row.period_id): row for row in book.addbacks}
    templates = {row.addback_id: row for row in book.addbacks}
    return tuple(
        AddbackRow(
            template.addback_id,
            template.addback_label,
            template.classification,
            row.realization_status if row else "NOT_STATED",
            template.display_priority,
            period.period_id,
            row.value.amount if row else None,
            _ref(row.value) if row else None,
        )
        for period in book.periods
        for addback_id, template in templates.items()
        for row in (supplied.get((addback_id, period.period_id)),)
        if row is not None or not period.component_period_ids
    )


def _segments(book: FinancialBook) -> tuple[SegmentRow, ...]:
    supplied = {(row.segment_id, row.period_id): row for row in book.segments}
    templates = {row.segment_id: row for row in book.segments}
    return tuple(
        SegmentRow(
            template.segment_id,
            template.segment_name,
            template.segment_type,
            template.display_priority,
            period.period_id,
            row.revenue.amount if row else None,
            _ref(row.revenue) if row else None,
        )
        for period in book.periods
        for segment_id, template in templates.items()
        for row in (supplied.get((segment_id, period.period_id)),)
    )


def _kpis(book: FinancialBook) -> tuple[KpiRow, ...]:
    supplied = {(row.kpi_id, row.period_id): row for row in book.kpis}
    templates = {row.kpi_id: row for row in book.kpis}
    return tuple(
        KpiRow(
            template.kpi_id,
            template.kpi_label,
            template.display_priority,
            period.period_id,
            row.value.amount if row else None,
            template.unit,
            template.value_type,
            _ref(row.value) if row else None,
        )
        for period in book.periods
        for kpi_id, template in templates.items()
        for row in (supplied.get((kpi_id, period.period_id)),)
    )


def kernel_registers(pack: PreparedPack, review: FinancialReview, book_id: str) -> Cp1Registers:
    """Build one validated book. Unknown rows are explicit nulls, never inferred zeros."""
    issues = validate_financial_review(pack, review)
    if issues:
        raise ValueError("; ".join(issues))
    # Round-trip again to retain validation even if a caller used model_copy/model_construct.
    review = FinancialReview.model_validate_json(review.model_dump_json())
    book = next((item for item in review.books if item.book_id == book_id), None)
    if book is None:
        raise ValueError(f"Unknown financial book: {book_id}")
    adjustments = tuple(
        PfAdjustmentRow(
            row.adjustment_id,
            row.label,
            row.period_id,
            row.classification,
            row.metric_id,
            row.value.amount,
            _ref(row.value),
        )
        for row in book.pro_forma
        if row.value.amount is not None
    )
    return Cp1Registers(
        _periods(book),
        _accounts(book),
        _addbacks(book),
        _segments(book),
        _kpis(book),
        _facilities(book),
        adjustments,
        book.currency,
        book.unit,
    )


def source_citations(review: FinancialReview, refs: tuple[SourceRef, ...]) -> tuple[Citation, ...]:
    """Resolve kernel provenance back to every quote in the canonical observation.

    Call with the validated review bound to the calculation's input hash. An
    unknown reference raises; it cannot silently become an uncited output.
    """
    index = {value.observation_id: value for value in records(review, Observation)}
    citations: list[Citation] = []
    for ref in refs:
        if ref.source_locator == "financial-observation":
            value = index[ref.source_id]
            citations.extend(value.citations)
            citations.extend(
                citation for alternative in value.alternatives for citation in alternative.citations
            )
        elif ref.source_locator.startswith("facility-issuance:"):
            book_id = ref.source_locator.removeprefix("facility-issuance:")
            book = next(book for book in review.books if book.book_id == book_id)
            matching = [
                row for row in book.facilities if row.facility_id == ref.source_id and row.issued_on
            ]
            if not matching:
                raise ValueError(f"Unknown facility issuance provenance: {ref.source_id}")
            citations.extend(citation for row in matching for citation in row.issuance_citations)
        else:
            raise ValueError(f"Unknown kernel provenance: {ref.source_locator}")
    return tuple(dict.fromkeys(citations))
