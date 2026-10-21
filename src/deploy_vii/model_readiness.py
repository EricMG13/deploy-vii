"""Scoped historical CP-MODEL readiness; calculation success alone is insufficient."""

from datetime import date
from typing import Literal

from deploy_vii.contracts import Contract, Hash, Identifier, Text
from deploy_vii.financial_contracts import FinancialBook, FinancialReview, Observation
from deploy_vii.financial_reconciliation import ReconciliationReport, reconcile_financials
from deploy_vii.financial_validation import records, validate_financial_review
from deploy_vii.model.dates import fiscal_year_number
from deploy_vii.model.history import BALANCE_METRICS
from deploy_vii.model.periods import LTM_DAYS
from deploy_vii.period_reconciliation import (
    PeriodReconciliationReport,
    _source_periods,
    reconcile_periods,
)
from deploy_vii.preparation import PreparedPack

# r14's Model interface flow coverage, with the two financing cash classifications
# needed by the reviewed kernel's adjusted CFO. Unknown is never an inferred zero.
REQUIRED_FLOWS = frozenset(
    {
        "revenue",
        "cogs",
        "opex_including_da",
        "depreciation_amortization",
        "ebitda",
        "adjusted_ebitda",
        "cash_interest_paid",
        "cash_lease_payments",
        "cash_taxes_paid",
        "cfo_ncfo",
        "working_capital_change",
        "capex_and_intangible_investment",
        "acquisitions_disposals",
        "net_debt_issue_repay",
        "net_equity_issue_repay",
        "dividends_paid",
        "other_investing_financing",
        "net_cash_change",
        "lease_payments_in_financing",
        "interest_paid_in_financing",
    }
)
_MANDATORY_CHECKS = frozenset(
    {
        "SEGMENT_REVENUE",
        "EBITDA_BRIDGE",
        "ADJUSTED_EBITDA_BRIDGE",
        "CFO_IDENTITY",
        "DEBT_TOTAL_EX_LEASES",
        "NCF_CASH_MOVEMENT",
    }
)


class ReadinessFinding(Contract):
    code: Identifier
    severity: Literal["BLOCK", "WARN"]
    construction_id: Identifier | None = None
    references: tuple[Text, ...] = ()
    explanation: Text


class ModelReadinessRow(Contract):
    downstream_module: Literal["CP-MODEL"] = "CP-MODEL"
    scope: Literal["selected_historical_quarters"] = "selected_historical_quarters"
    status: Literal["ready", "blocked"]
    selected_quarters: tuple[Identifier, ...]
    missing_metric_ids: tuple[Text, ...]
    conflict_refs: tuple[Identifier, ...]
    mandatory_check_ids: tuple[Identifier, ...]
    findings: tuple[ReadinessFinding, ...]
    explanation: Text


class ModelReadinessReport(Contract):
    schema_version: Literal["model-readiness/1"] = "model-readiness/1"
    run_id: Identifier
    issuer_id: Identifier
    as_of: date
    method_version: Literal["deploy-v-r14"] = "deploy-v-r14"
    pack_sha256: Hash
    review_sha256: Hash
    book_id: Identifier
    requested_quarters: tuple[Text, ...] | None
    readiness: ModelReadinessRow
    period_reconciliation: PeriodReconciliationReport | None
    source_reconciliation: ReconciliationReport
    limitations: tuple[Text, ...]


def _evaluate(
    book: FinancialBook,
    periods: PeriodReconciliationReport,
    source: ReconciliationReport,
    requested: tuple[str, ...] | None,
) -> ModelReadinessRow:
    historical = periods.historical
    available = {n.construction_id: n for n in historical.constructions if n.kind == "QUARTER"}
    selected = tuple(available) if requested is None else requested
    findings: list[ReadinessFinding] = []
    missing: set[str] = set()

    def issue(
        code: str,
        text: str,
        node: str | None = None,
        refs: tuple[str, ...] = (),
        *,
        warning: bool = False,
    ) -> None:
        findings.append(
            ReadinessFinding(
                code=code,
                severity="WARN" if warning else "BLOCK",
                construction_id=node,
                references=refs,
                explanation=text,
            )
        )

    if len(selected) != len(set(selected)) or any(key not in available for key in selected):
        issue(
            "quarter_selection", "Selection contains duplicate or unknown quarter construction IDs"
        )
    quarters = sorted(
        (available[key] for key in dict.fromkeys(selected) if key in available),
        key=lambda n: (n.end_date or date.min, n.construction_id),
    )
    if len(quarters) < 4:
        issue("quarter_count", "At least four discrete complete quarters are required")
    quarter_years: list[int | None] = []
    for index, quarter in enumerate(quarters):
        previous_end = quarters[index - 1].end_date if index else None
        if (
            quarter.start_date is None
            or quarter.end_date is None
            or quarter.days is None
            or quarter.limitation
        ):
            issue(
                "quarter_span",
                "Quarter span is unavailable or not comparable",
                quarter.construction_id,
            )
        if index and (
            previous_end is None
            or quarter.start_date is None
            or previous_end.toordinal() + 1 != quarter.start_date.toordinal()
        ):
            issue(
                "quarter_continuity",
                "Selected quarters must be contiguous and non-overlapping",
                quarter.construction_id,
            )
        year = fiscal_year_number(quarter.fiscal_year)
        previous = quarters[index - 1] if index else None
        previous_year = quarter_years[index - 1] if index else None
        quarter_years.append(year)
        if (
            year is None
            or quarter.fiscal_quarter is None
            or (
                previous is not None
                and (
                    previous_year is None
                    or previous.fiscal_quarter is None
                    or 4 * year + quarter.fiscal_quarter
                    != 4 * previous_year + previous.fiscal_quarter + 1
                )
            )
        ):
            issue(
                "fiscal_sequence",
                "Selected fiscal quarter slots are not consecutive",
                quarter.construction_id,
            )
        if index >= 3:
            start = quarters[index - 3].start_date
            end = quarter.end_date
            if (
                start is None
                or end is None
                or not LTM_DAYS[0] <= (end - start).days + 1 <= LTM_DAYS[1]
            ):
                issue(
                    "annual_span",
                    "Each four-quarter window must span 364-371 days",
                    quarter.construction_id,
                )
    rows = {(v.construction_id, v.series_key): v for v in historical.values}
    by_period = {p.period_id: p for p in book.periods}
    used_periods: set[str] = set()
    required_by_year: dict[int | None, set[str]] = {}
    facilities = tuple(dict.fromkeys(r.facility_id for r in book.facilities))
    segments = tuple(dict.fromkeys(r.segment_id for r in book.segments))
    addbacks = tuple(dict.fromkeys(r.addback_id for r in book.addbacks))
    if not facilities:
        issue("facility_schedule", "A complete carrying-value facility schedule is required")
    input_keys: dict[bool, tuple[str, ...]] = {}
    schedule_keys = (
        *("fac:" + fid for fid in facilities),
        *("bu:" + sid for sid in segments),
        *("addback:" + aid for aid in addbacks),
    )
    for quarter, year in zip(quarters, quarter_years, strict=True):
        cid = quarter.construction_id
        leaves = _source_periods(historical, quarter)
        used_periods.update(pid for pid, _ in leaves if pid is not None)
        nature = bool(leaves) and all(
            pid is not None and by_period[pid].expense_presentation == "by_nature"
            for pid, _ in leaves
        )
        flow_metrics = REQUIRED_FLOWS - ({"cogs"} if nature else set())
        required_by_year.setdefault(year, set()).update(flow_metrics)
        if nature not in input_keys:
            input_keys[nature] = (
                *("acct:" + metric for metric in sorted(flow_metrics | BALANCE_METRICS)),
                *schedule_keys,
            )
        keys = input_keys[nature]
        for key in keys:
            row = rows.get((cid, key))
            if row is None or row.value.amount is None:
                missing.add(key)
                issue("missing_input", "Required historical input is unknown", cid, (key,))
            elif not row.value.citations:
                issue(
                    "source_locator",
                    "Required historical input has no located evidence",
                    cid,
                    (key,),
                )
        tax = rows.get((cid, "acct:effective_tax_rate"))
        components = [
            rows.get((cid, "acct:" + key)) for key in ("pretax_income", "income_tax_expense")
        ]
        if (tax is None or tax.value.amount is None) and any(
            v is None or v.value.amount is None for v in components
        ):
            missing.add("effective_tax_rate_or_pretax_and_tax")
            issue(
                "tax_inputs",
                "Tax rate requires a source rate or both pretax income and tax expense",
                cid,
            )
    # Every selected quarter must carry the six mandatory comparisons, including
    # a WARN/null segment comparison for genuine non-disclosure.
    mandatory = []
    selected_ids = {q.construction_id for q in quarters}
    selected_years = set(quarter_years)
    nodes = {n.construction_id: n for n in historical.constructions}
    check_kinds: dict[str, set[str]] = {}
    for check in periods.checks:
        check_kinds.setdefault(check.construction_id, set()).add(check.check_type)
        selected_check = (
            check.construction_id in selected_ids and check.check_type in _MANDATORY_CHECKS
        )
        year_check = (
            check.check_type in {"FY_QUARTERS", "REPORTED_DERIVED_PERIOD"}
            and fiscal_year_number(nodes[check.construction_id].fiscal_year) in selected_years
            and (
                (
                    check.check_type == "FY_QUARTERS"
                    and check.metric_id
                    in required_by_year.get(
                        fiscal_year_number(nodes[check.construction_id].fiscal_year), set()
                    )
                )
                or check.reported.amount is not None
            )
        )
        if selected_check or year_check:
            mandatory.append(check.check_id)
            if check.status != "PASS":
                issue(
                    "reconciliation",
                    check.explanation,
                    check.construction_id,
                    (check.check_id,),
                    warning=check.status == "WARN",
                )
    for quarter in quarters:
        cid = quarter.construction_id
        kinds = check_kinds.get(cid, set())
        if not _MANDATORY_CHECKS <= kinds:
            issue("missing_checks", "Mandatory reconciliation types are absent", cid)
    # A source error must not disappear through period subtraction. Derived FY
    # checks replace the direct-only quarterly comparison, which lacks computed Q4.
    for source_check in source.checks:
        if (
            source_check.period_id in used_periods
            and source_check.check_type != "FY_QUARTERS"
            and (
                source_check.check_type == "SOURCE_STATEMENT_IDENTITY"
                or source_check.difference is not None
            )
        ):
            mandatory.append(source_check.check_id)
            if source_check.status != "PASS":
                issue(
                    "source_reconciliation",
                    source_check.explanation,
                    refs=(source_check.check_id,),
                    warning=source_check.status == "WARN",
                )
    conflicts = tuple(
        o.observation_id for o in records(book, Observation) if o.status == "conflicting"
    )
    if conflicts:
        issue(
            "source_conflicts",
            "Unresolved source conflicts require explicit resolution",
            refs=conflicts,
        )
    for facility in book.facilities:
        if facility.period_id in used_periods and (
            facility.rate_type == "NOT_STATED"
            or facility.annual_amortisation.amount is None
            or facility.maturity_date is None
        ):
            issue(
                "facility_terms",
                "Historical carrying value does not establish forecast rate, "
                "amortisation or maturity terms",
                refs=(facility.facility_id, facility.period_id),
                warning=True,
            )
    ready = not any(f.severity == "BLOCK" for f in findings)
    return ModelReadinessRow(
        status="ready" if ready else "blocked",
        selected_quarters=tuple(q.construction_id for q in quarters),
        missing_metric_ids=tuple(sorted(missing)),
        conflict_refs=conflicts,
        mandatory_check_ids=tuple(dict.fromkeys(mandatory)),
        findings=tuple(findings),
        explanation="Selected historical quarters satisfy deterministic Model input requirements"
        if ready
        else "Selected historical quarters do not satisfy Model input requirements",
    )


def assess_model_readiness(
    pack: PreparedPack,
    review: FinancialReview,
    book_id: str,
    *,
    quarter_ids: tuple[str, ...] | None = None,
) -> ModelReadinessReport:
    issues = validate_financial_review(pack, review)
    if issues:
        raise ValueError("; ".join(issues))
    review = FinancialReview.model_validate_json(review.model_dump_json())
    book = next((b for b in review.books if b.book_id == book_id), None)
    if book is None:
        raise ValueError(f"Unknown financial book: {book_id}")
    source = reconcile_financials(pack, review, book_id)
    periods: PeriodReconciliationReport | None = None
    try:
        periods = reconcile_periods(pack, review, book_id)
    except ValueError as error:
        row = ModelReadinessRow(
            status="blocked",
            selected_quarters=(),
            missing_metric_ids=(),
            conflict_refs=tuple(
                o.observation_id for o in records(book, Observation) if o.status == "conflicting"
            ),
            mandatory_check_ids=(),
            findings=(
                ReadinessFinding(code="input_conversion", severity="BLOCK", explanation=str(error)),
            ),
            explanation="Source review cannot enter historical Model calculation",
        )
    else:
        row = _evaluate(book, periods, source, quarter_ids)
    return ModelReadinessReport(
        run_id=review.run_id,
        issuer_id=review.issuer_id,
        as_of=review.as_of,
        pack_sha256=review.pack_sha256,
        review_sha256=review.content_hash(),
        book_id=book_id,
        requested_quarters=quarter_ids,
        readiness=row,
        period_reconciliation=periods,
        source_reconciliation=source,
        limitations=(
            "Readiness applies only to the explicitly retained historical quarter scope",
            "A ready row does not qualify pro forma, projections, "
            "analytical interpretation or report delivery",
            "No downstream consumer other than CP-MODEL is assessed here",
            "Source-backed exceptions and full CP-1 acceptance remain separate",
        ),
    )


def validate_model_readiness(
    pack: PreparedPack, review: FinancialReview, report: ModelReadinessReport
) -> tuple[str, ...]:
    try:
        report = ModelReadinessReport.model_validate_json(report.model_dump_json())
        expected = assess_model_readiness(
            pack, review, report.book_id, quarter_ids=report.requested_quarters
        )
    except ValueError as error:
        return (f"Invalid Model readiness inputs: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Model readiness differs from deterministic recomputation",)
    )
