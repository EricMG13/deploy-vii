"""Mechanical CP-1 evidence, reference and dimensional checks; not analytical qualification."""

from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import date

from pydantic import BaseModel, ValidationError

from deploy_vii.contracts import Citation
from deploy_vii.financial_contracts import (
    AccountObservation,
    AddbackObservation,
    FacilityObservation,
    FinancialBook,
    FinancialPeriod,
    FinancialReview,
    KpiObservation,
    Observation,
    ProFormaObservation,
    SegmentObservation,
)
from deploy_vii.model.dates import fiscal_year_number
from deploy_vii.model.history import BALANCE_METRICS
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import citation_issues

type PeriodRecord = (
    AccountObservation
    | AddbackObservation
    | FacilityObservation
    | KpiObservation
    | ProFormaObservation
    | SegmentObservation
)


def records[T: BaseModel](value: BaseModel, kind: type[T]) -> Iterator[T]:
    """Traverse typed contracts, including every nested observation/alternative citation."""
    if isinstance(value, kind):
        yield value
    for name in type(value).model_fields:
        child = getattr(value, name)
        if isinstance(child, BaseModel):
            yield from records(child, kind)
        elif isinstance(child, tuple):
            for item in child:
                if isinstance(item, BaseModel):
                    yield from records(item, kind)


def period_issues(periods: tuple[FinancialPeriod, ...]) -> tuple[str, ...]:
    """Validate a bounded, unique, acyclic component graph and fiscal slots."""
    index = {period.period_id: period for period in periods}
    if len(index) != len(periods):
        return ("Duplicate period identity",)
    issues: list[str] = []
    slots: set[tuple[str, int | None, int | None]] = set()
    for period in periods:
        components = set(period.component_period_ids)
        if len(components) != len(period.component_period_ids) or not components <= index.keys():
            issues.append(f"Duplicate or unknown period component: {period.period_id}")
        if period.period_type in {"QUARTER", "YTD", "FY"}:
            slot = (
                period.period_type,
                fiscal_year_number(period.fiscal_year),
                None if period.period_type == "FY" else period.fiscal_quarter,
            )
            if slot in slots:
                issues.append(f"Duplicate fiscal slot: {period.period_id}")
            slots.add(slot)
    if issues:
        return tuple(issues)
    active: set[str] = set()
    depths: dict[str, int] = {}

    def depth(period_id: str) -> int:
        if period_id in active:
            raise ValueError(f"Cyclic period components: {period_id}")
        if period_id in depths:
            return depths[period_id]
        active.add(period_id)
        depths[period_id] = 1 + max(
            (depth(part) for part in index[period_id].component_period_ids), default=0
        )
        active.remove(period_id)
        return depths[period_id]

    try:
        if max(depth(period_id) for period_id in index) > 4:
            return ("Period component nesting exceeds four levels",)
    except ValueError as error:
        return (str(error),)
    return ()


def _series_issues(
    rows: Sequence[PeriodRecord], identity: str, stable: tuple[str, ...], periods: set[str]
) -> list[str]:
    issues: list[str] = []
    seen: set[tuple[str, str]] = set()
    metadata: dict[str, tuple[object, ...]] = {}
    for row in rows:
        row_id, period_id = getattr(row, identity), row.period_id
        key = row_id, period_id
        if key in seen or period_id not in periods:
            issues.append(f"Duplicate row or unknown period: {identity} {row_id} {period_id}")
        seen.add(key)
        values = tuple(getattr(row, field) for field in stable)
        if row_id in metadata and metadata[row_id] != values:
            issues.append(f"Changed definition requires a distinct identity: {identity} {row_id}")
        metadata[row_id] = values
    if len(metadata) * len(periods) > 20000:
        issues.append(f"Expanded register exceeds 20000 rows: {identity}")
    if "display_priority" in stable:
        priority_index = stable.index("display_priority")
        priorities = [
            values[priority_index]
            for values in metadata.values()
            if "segment_type" not in stable
            or values[stable.index("segment_type")] == "OPERATING_SEGMENT"
        ]
        if len(set(priorities)) != len(priorities):
            issues.append(f"Duplicate display priority: {identity}")
    return issues


def book_issues(book: FinancialBook) -> tuple[str, ...]:
    issues = list(period_issues(book.periods))
    periods = {period.period_id: period for period in book.periods}
    dimensions = book.currency, book.unit, book.accounting_basis, book.entity_perimeter
    for declared_period in book.periods:
        if (
            declared_period.currency,
            declared_period.unit,
            declared_period.accounting_basis,
            declared_period.entity_perimeter,
        ) != dimensions:
            issues.append(
                f"Mixed units, currency, accounting basis or perimeter: {declared_period.period_id}"
            )
    for rows, identity, stable in (
        (book.accounts, "metric_id", ()),
        (book.addbacks, "addback_id", ("addback_label", "classification", "display_priority")),
        (book.segments, "segment_id", ("segment_name", "segment_type", "display_priority")),
        (
            book.kpis,
            "kpi_id",
            ("kpi_label", "business_unit", "definition", "unit", "value_type", "display_priority"),
        ),
        (
            book.facilities,
            "facility_id",
            (
                "currency",
                "facility_type",
                "secured_status",
                "seniority",
                "lease_classification",
            ),
        ),
        (book.pro_forma, "adjustment_id", ()),
    ):
        issues.extend(_series_issues(rows, identity, stable, set(periods)))
    balance_values: dict[tuple[str, object], set[object]] = defaultdict(set)
    for account in book.accounts:
        period = periods.get(account.period_id)
        if period is None:
            continue
        if (
            account.metric_id in BALANCE_METRICS
            and period.end_date
            and account.value.amount is not None
        ):
            balance_values[account.metric_id, period.end_date].add(account.value.amount)
        if (
            account.metric_id == "cogs"
            and period.expense_presentation == "by_nature"
            and (account.value.amount is not None or account.value.status == "conflicting")
        ):
            issues.append(
                f"COGS conflicts with expenses-by-nature classification: {account.period_id}"
            )
        if (
            account.metric_id in {"rcf_drawn", "rcf_commitment"}
            and account.value.amount is not None
            and account.value.amount < 0
        ):
            issues.append(f"Negative revolver balance: {account.metric_id} {account.period_id}")
    for (metric, day), values in balance_values.items():
        if len(values) > 1:
            issues.append(f"Unresolved same-date account balances: {metric} {day}")
    facility_values: dict[tuple[str, object, str], set[object]] = defaultdict(set)
    issuance: dict[str, set[date]] = defaultdict(set)
    for facility_row in book.facilities:
        if facility_row.issued_on is not None:
            issuance[facility_row.facility_id].add(facility_row.issued_on)
        period = periods.get(facility_row.period_id)
        if period is None:
            continue
        for field in ("carrying_value", "principal", "drawn_amount", "commitment"):
            value = getattr(facility_row, field).amount
            if value is not None and period.end_date:
                facility_values[facility_row.facility_id, period.end_date, field].add(value)
    for facility_id, dates in issuance.items():
        if len(dates) > 1:
            issues.append(f"Conflicting facility issuance dates: {facility_id}")
    for facility_row in book.facilities:
        period = periods.get(facility_row.period_id)
        if (
            period is not None
            and period.end_date is not None
            and facility_row.carrying_value.amount not in {None, 0}
            and any(issued > period.end_date for issued in issuance[facility_row.facility_id])
        ):
            issues.append(
                f"Facility balance precedes issuance: {facility_row.facility_id} "
                f"{facility_row.period_id}"
            )
    for (facility, day, field), values in facility_values.items():
        if len(values) > 1:
            issues.append(f"Unresolved same-date facility balances: {facility} {day} {field}")
    segments = {row.segment_id for row in book.segments}
    allocated = [
        segment for slot in book.segment_allocation for segment in slot.component_segment_ids
    ]
    if len({slot.slot_id for slot in book.segment_allocation}) != len(book.segment_allocation):
        issues.append("Duplicate segment allocation slot")
    if set(allocated) != segments or len(allocated) != len(segments):
        issues.append("Allocate every segment exactly once, retaining its own presentation row")
    for name, rows, disclosure in (
        ("segment", book.segments, book.segment_disclosure),
        ("addback", book.addbacks, book.addback_disclosure),
    ):
        if rows and disclosure.status in {"not_disclosed", "not_applicable"}:
            issues.append(f"{name} disclosure contradicts populated schedule")
    corporate: dict[str, int] = defaultdict(int)
    for segment in book.segments:
        if segment.segment_type == "CORPORATE_ELIMINATION":
            corporate[segment.period_id] += 1
    if any(count > 1 for count in corporate.values()):
        issues.append("At most one corporate/elimination segment per period")
    events: dict[tuple[str, str], list[str]] = defaultdict(list)
    facilities = {row.facility_id for row in book.facilities}
    for adjustment in book.pro_forma:
        period = periods.get(adjustment.period_id)
        if period is None or period.period_type != "LTM":
            issues.append(f"Pro forma requires an LTM period: {adjustment.adjustment_id}")
        elif period.end_date and adjustment.effective_date <= period.end_date:
            issues.append(f"Pro forma event is inside reported period: {adjustment.adjustment_id}")
        allowed = {
            "revenue",
            "ebitda",
            "adjusted_ebitda",
            "cash_interest_paid",
            "cash_and_equivalents",
            "total_debt",
        }
        if adjustment.metric_id not in allowed and adjustment.metric_id not in {
            f"facility:{fid}" for fid in facilities
        }:
            issues.append(f"Unsupported pro forma target: {adjustment.adjustment_id}")
        if adjustment.value.status != "known":
            issues.append(f"Unsettled pro forma adjustment: {adjustment.adjustment_id}")
        events[adjustment.event_id, adjustment.period_id].append(adjustment.metric_id)
    for (event, period_id), metrics in events.items():
        if (
            len(metrics) != len(set(metrics))
            or {"ebitda", "adjusted_ebitda"} <= set(metrics)
            or (
                "total_debt" in metrics
                and any(metric.startswith("facility:") for metric in metrics)
            )
        ):
            issues.append(f"Double-counted pro forma event: {event} {period_id}")
    return tuple(issues)


def validate_financial_review(pack: PreparedPack, review: FinancialReview) -> tuple[str, ...]:
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        review = FinancialReview.model_validate_json(review.model_dump_json())
    except ValidationError as error:
        return (f"Invalid financial contract: {error}",)
    issues: list[str] = []
    if review.pack_sha256 != pack.content_hash():
        issues.append("Financial review does not bind current prepared pack")
    if (review.run_id, review.issuer_id, review.as_of, review.method_version) != (
        pack.run.run_id,
        pack.run.issuer_id,
        pack.run.as_of,
        pack.run.method_version,
    ):
        issues.append("Financial review run/issuer/date/method identity mismatch")
    if len({book.book_id for book in review.books}) != len(review.books):
        issues.append("Duplicate book identity")
    observations = list(records(review, Observation))
    if len({value.observation_id for value in observations}) != len(observations):
        issues.append("Duplicate observation identity")
    issues.extend(citation_issues(tuple(records(review, Citation)), pack.sources))
    for book in review.books:
        issues.extend(f"{book.book_id}: {issue}" for issue in book_issues(book))
        for period in book.periods:
            if period.end_date and period.end_date > review.as_of:
                issues.append(f"Historical period ends after as-of date: {period.period_id}")
        for facility in book.facilities:
            if facility.issued_on and facility.issued_on > review.as_of:
                issues.append(f"Issuance date is after as-of date: {facility.facility_id}")
        for row in book.pro_forma:
            if row.announced_on > review.as_of or (
                row.event_status == "completed" and row.effective_date > review.as_of
            ):
                issues.append(f"Pro forma event is not known at as-of date: {row.adjustment_id}")
    return tuple(issues)
