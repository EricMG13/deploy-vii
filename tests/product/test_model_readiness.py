"""Historical Model readiness is a scoped input decision, not analytical qualification."""

from datetime import date
from decimal import Decimal

import pytest

from deploy_vii.financial_contracts import (
    ACCOUNT_IDS,
    AccountObservation,
    BalanceMovementBridge,
    FinancialBook,
    StatementDisclosure,
)
from deploy_vii.model.history import BALANCE_METRICS
from deploy_vii.model_readiness import (
    ModelReadinessReport,
    assess_model_readiness,
    validate_model_readiness,
)
from tests.product.test_financial_model import model_case
from tests.product.test_financial_periods import frozen
from tests.product.test_financials import observed
from tests.product.test_reconciliation import accounts
from tests.product.test_statements import identity, line


def ready_case() -> FinancialBook:
    value = model_case()
    # Explicitly synthetic values, including sourced zeroes; no production inference.
    amounts = dict.fromkeys(ACCOUNT_IDS, "0.00")
    amounts.update(
        revenue="100.00",
        cogs="-30.00",
        opex_including_da="-20.00",
        depreciation_amortization="-10.00",
        ebitda="60.00",
        adjusted_ebitda="60.00",
        cash_interest_paid="-5.00",
        cash_taxes_paid="-5.00",
        cfo_ncfo="60.00",
        capex_and_intangible_investment="-10.00",
        dividends_paid="-2.00",
        other_investing_financing="-28.00",
        net_cash_change="20.00",
        rcf_commitment="50.00",
        rcf_drawn="10.00",
        senior_secured_debt="100.00",
        total_debt="100.00",
        net_accounts_receivable="20.00",
        accounts_payable="10.00",
        effective_tax_rate="0.25",
        pretax_income="20.00",
        income_tax_expense="-5.00",
        net_income="40.00",
    )
    rows = []
    lines = []
    identities = []
    disclosures = []
    bridges = []
    for period in value.periods:
        scale = 4 if period.period_type == "FY" else 1
        for key, amount in amounts.items():
            if period.period_type == "PERIOD_END" and key not in BALANCE_METRICS:
                continue
            number = Decimal(amount) * (
                1 if key in BALANCE_METRICS or key == "effective_tax_rate" else scale
            )
            if key == "cash_and_equivalents":
                number = Decimal(
                    0
                    if period.period_id == "OPEN"
                    else 80
                    if period.period_type == "FY"
                    else 20 * period.fiscal_quarter
                )
            rows.append(
                AccountObservation(
                    metric_id=key,
                    period_id=period.period_id,
                    value=observed(period.period_id + "." + key, str(number)),
                )
            )
        quarter = (
            0
            if period.period_id == "OPEN"
            else 4
            if period.period_type == "FY"
            else period.fiscal_quarter
        )
        lines.append(
            line(
                "equity",
                "total_equity",
                str(100 + 40 * quarter),
                1,
                statement="BS",
                kind="total",
                pid=period.period_id,
            )
        )
        if period.period_type != "PERIOD_END":
            lines.append(
                line(
                    "income",
                    "net_income",
                    str(40 * scale),
                    1,
                    statement="IS",
                    kind="total",
                    pid=period.period_id,
                )
            )
            bridges.append(
                BalanceMovementBridge(
                    bridge_id="equity." + period.period_id,
                    period_id=period.period_id,
                    balance_item_id="total_equity",
                    movement_ids=(),
                    disclosure=value.addback_disclosure,
                )
            )
            lines.extend(
                (
                    line("cfo", "cfo_ncfo", str(60 * scale), 1, kind="total", pid=period.period_id),
                    line("profit", "net_income", str(40 * scale), 2, pid=period.period_id),
                    line("noncash", "other:noncash", str(20 * scale), 3, pid=period.period_id),
                    line(
                        "cfi",
                        "investing_cash_flow",
                        str(-10 * scale),
                        10,
                        kind="subtotal",
                        pid=period.period_id,
                    ),
                    line(
                        "cff",
                        "financing_cash_flow",
                        str(-30 * scale),
                        11,
                        kind="subtotal",
                        pid=period.period_id,
                    ),
                    line(
                        "ncf",
                        "net_cash_change",
                        str(20 * scale),
                        12,
                        kind="total",
                        pid=period.period_id,
                    ),
                )
            )
            identities.append(identity("cfo", ("profit", 1), ("noncash", 1), pid=period.period_id))
            identities.append(
                identity("ncf", ("cfo", 1), ("cfi", 1), ("cff", 1), pid=period.period_id)
            )
            disclosures.append(
                StatementDisclosure(
                    statement="CFS", period_id=period.period_id, disclosure=value.addback_disclosure
                )
            )
    return value.model_copy(
        update={
            "accounts": tuple(rows),
            "statement_lines": tuple(lines),
            "statement_identities": tuple(identities),
            "statement_disclosures": tuple(disclosures),
            "balance_movement_bridges": tuple(bridges),
        }
    )


def assess(value: FinancialBook) -> ModelReadinessReport:
    pack, review = frozen(value)
    return assess_model_readiness(pack, review, value.book_id)


def test_complete_four_quarters_are_ready_with_disclosure_and_forecast_limits() -> None:
    report = assess(ready_case())
    row = report.readiness
    assert row.downstream_module == "CP-MODEL" and row.status == "ready", row.findings
    assert len(row.selected_quarters) == 4
    assert row.missing_metric_ids == row.conflict_refs == ()
    assert all(f.severity == "WARN" for f in row.findings)
    assert any(f.code == "facility_terms" for f in row.findings)
    assert report.period_reconciliation
    checks = {
        c.check_id
        for c in (*report.period_reconciliation.checks, *report.source_reconciliation.checks)
    }
    assert set(row.mandatory_check_ids) <= checks
    assert report.limitations


@pytest.mark.parametrize("change", ["metric", "facility", "identity", "cash", "gap"])
def test_each_material_gap_blocks_readiness(change: str) -> None:
    value = ready_case()
    if change == "metric":
        value = accounts(value, "Q2", cash_taxes_paid=None)
    elif change == "facility":
        value = value.model_copy(
            update={"facilities": tuple(r for r in value.facilities if r.period_id != "Q2")}
        )
    elif change == "identity":
        value = value.model_copy(
            update={
                "statement_identities": tuple(
                    r for r in value.statement_identities if r.period_id != "Q2"
                )
            }
        )
    elif change == "cash":
        value = accounts(value, "Q2", cash_and_equivalents="41.00")
    else:
        value = value.model_copy(
            update={
                "periods": tuple(
                    p.model_copy(update={"start_date": date(2025, 4, 2)})
                    if p.period_id == "Q2"
                    else p
                    for p in value.periods
                )
            }
        )
    report = assess(value)
    assert report.readiness.status == "blocked"
    assert any(f.severity == "BLOCK" for f in report.readiness.findings)


def test_scope_is_explicit_and_duplicate_or_unknown_selection_refuses() -> None:
    value = ready_case()
    pack, review = frozen(value)
    full = assess_model_readiness(pack, review, value.book_id)
    selected = full.readiness.selected_quarters
    for scope in ((), selected[:3], (selected[0],) * 4, (*selected, "unknown")):
        report = assess_model_readiness(pack, review, value.book_id, quarter_ids=scope)
        assert report.readiness.status == "blocked"
        assert report.requested_quarters == scope
    explicit = assess_model_readiness(
        pack, review, value.book_id, quarter_ids=tuple(reversed(selected))
    )
    assert explicit.readiness.status == "ready"
    assert explicit.readiness.selected_quarters == selected


def test_partial_addback_review_is_retained_as_blocked_without_fake_calculations() -> None:
    value = ready_case()
    value = value.model_copy(
        update={
            "addback_disclosure": value.addback_disclosure.model_copy(update={"status": "partial"})
        }
    )
    report = assess(value)
    assert report.readiness.status == "blocked" and report.period_reconciliation is None
    assert report.readiness.findings[0].code == "input_conversion"
    assert report.source_reconciliation.checks


def test_by_nature_disclosure_does_not_require_an_invented_cogs() -> None:
    value = ready_case()
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"expense_presentation": "by_nature"}) for p in value.periods
            ),
            "accounts": tuple(r for r in value.accounts if r.metric_id != "cogs"),
        }
    )
    for period in value.periods:
        if period.period_type != "PERIOD_END":
            value = accounts(
                value,
                period.period_id,
                opex_including_da="-200.00" if period.period_type == "FY" else "-50.00",
            )
    row = assess(value).readiness
    assert row.status == "ready", row.findings
    assert "acct:cogs" not in row.missing_metric_ids


def test_tampering_and_invalid_source_identity_cannot_authorize_model() -> None:
    value = ready_case()
    pack, review = frozen(value)
    report = assess_model_readiness(pack, review, value.book_id)
    assert validate_model_readiness(pack, review, report) == ()
    assert validate_model_readiness(
        pack,
        review,
        report.model_copy(
            update={"readiness": report.readiness.model_copy(update={"mandatory_check_ids": ()})}
        ),
    )
    assert validate_model_readiness(pack, review, report.model_copy(update={"book_id": "unknown"}))
    with pytest.raises(ValueError, match="identity mismatch"):
        assess_model_readiness(
            pack, review.model_copy(update={"issuer_id": "other"}), value.book_id
        )


def test_short_fiscal_year_cannot_masquerade_as_four_complete_quarters() -> None:
    value = ready_case()
    periods = []
    for period in value.periods:
        if period.period_type == "QUARTER":
            period = period.model_copy(
                update={
                    "start_date": date(2025, 1, period.fiscal_quarter),
                    "end_date": date(2025, 1, period.fiscal_quarter),
                }
            )
        elif period.period_type == "FY":
            period = period.model_copy(update={"end_date": date(2025, 1, 4)})
        periods.append(period)
    row = assess(value.model_copy(update={"periods": tuple(periods)})).readiness
    assert row.status == "blocked"
    assert any(f.code == "annual_span" for f in row.findings)


def test_dates_cannot_override_nonconsecutive_fiscal_quarter_labels() -> None:
    value = ready_case()
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"fiscal_quarter": 5 - p.fiscal_quarter})
                if p.period_type == "QUARTER"
                else p
                for p in value.periods
            )
        }
    )
    row = assess(value).readiness
    assert row.status == "blocked"
    assert any(f.code == "fiscal_sequence" for f in row.findings)


def test_derived_quarters_qualify_without_requiring_direct_source_quarters() -> None:
    value = ready_case()
    updates = {}
    for key in (
        "periods",
        "accounts",
        "facilities",
        "statement_lines",
        "statement_identities",
        "statement_disclosures",
        "balance_movement_bridges",
    ):
        rows = []
        for row in getattr(value, key):
            if row.period_id == "Q4":
                continue
            if row.period_id in {"Q2", "Q3"}:
                scale = int(row.period_id[-1])
                if key == "periods":
                    row = row.model_copy(
                        update={"period_type": "YTD", "start_date": date(2025, 1, 1)}
                    )
                elif key == "accounts" and row.metric_id not in BALANCE_METRICS | {
                    "effective_tax_rate"
                }:
                    row = row.model_copy(
                        update={
                            "value": observed(
                                row.value.observation_id, str(row.value.amount * scale)
                            )
                        }
                    )
                elif key == "statement_lines" and row.statement != "BS":
                    row = row.model_copy(
                        update={
                            "value": observed(
                                row.value.observation_id, str(row.value.amount * scale)
                            )
                        }
                    )
            rows.append(row)
        updates[key] = tuple(rows)
    report = assess(value.model_copy(update=updates))
    assert report.readiness.status == "ready", report.readiness.findings
    assert report.period_reconciliation
    selected = set(report.readiness.selected_quarters)
    nodes = [
        n
        for n in report.period_reconciliation.historical.constructions
        if n.construction_id in selected
    ]
    assert sum(n.own_period_id is None for n in nodes) == 3


@pytest.mark.parametrize("change", ["complete", "partial", "missing", "null"])
def test_disclosed_segment_schedule_must_be_complete_for_every_quarter(change: str) -> None:
    from deploy_vii.financial_contracts import SegmentAllocation, SegmentObservation
    from tests.product.test_financials import _C

    value = ready_case()
    segments = tuple(
        SegmentObservation(
            segment_id="all",
            segment_name="All operations",
            segment_type="OPERATING_SEGMENT",
            display_priority=1,
            period_id=p.period_id,
            revenue=observed(
                "segment." + p.period_id,
                None
                if change == "null" and p.period_id == "Q2"
                else "400.00"
                if p.period_type == "FY"
                else "100.00",
            ),
            classification_citations=(_C,),
        )
        for p in value.periods
        if p.period_type != "PERIOD_END" and not (change == "missing" and p.period_id == "Q2")
    )
    value = value.model_copy(
        update={
            "segments": segments,
            "segment_allocation": (
                SegmentAllocation(
                    slot_id="DIVISION_1",
                    slot_label="All operations",
                    component_segment_ids=("all",),
                    rationale="Synthetic complete segment",
                ),
            ),
            "segment_disclosure": value.segment_disclosure.model_copy(
                update={"status": "partial" if change == "partial" else "complete"}
            ),
        }
    )
    row = assess(value).readiness
    assert row.status == ("ready" if change == "complete" else "blocked"), row.findings


def test_conflict_remains_explicit_and_cannot_be_selected_away() -> None:
    from deploy_vii.financial_contracts import Alternative
    from tests.product.test_financials import _C

    value = ready_case()
    target = next(r for r in value.accounts if r.period_id == "Q1" and r.metric_id == "revenue")
    conflict = target.value.model_copy(
        update={
            "amount": None,
            "status": "conflicting",
            "reason": "Unresolved synthetic sources",
            "alternatives": tuple(
                Alternative(amount=Decimal(n), citations=(_C,), explanation=n)
                for n in ("100", "101")
            ),
        }
    )
    value = value.model_copy(
        update={
            "accounts": tuple(
                r.model_copy(update={"value": conflict}) if r == target else r
                for r in value.accounts
            )
        }
    )
    row = assess(value).readiness
    assert row.status == "blocked" and row.conflict_refs == (target.value.observation_id,)
    assert any(f.code == "source_conflicts" for f in row.findings)


@pytest.mark.parametrize("tax_case", ["rate_only", "components", "missing"])
def test_tax_inputs_require_one_evidenced_route(tax_case: str) -> None:
    value = ready_case()
    missing = (
        {"pretax_income", "income_tax_expense"}
        if tax_case == "rate_only"
        else {"effective_tax_rate"}
    )
    if tax_case == "missing":
        missing.add("income_tax_expense")
    value = value.model_copy(
        update={"accounts": tuple(r for r in value.accounts if r.metric_id not in missing)}
    )
    row = assess(value).readiness
    assert row.status == ("blocked" if tax_case == "missing" else "ready"), row.findings
    assert ("effective_tax_rate_or_pretax_and_tax" in row.missing_metric_ids) == (
        tax_case == "missing"
    )


def test_missing_facility_schedule_is_not_interpreted_as_debt_free() -> None:
    row = assess(ready_case().model_copy(update={"facilities": ()})).readiness
    assert row.status == "blocked"
    assert any(f.code == "facility_schedule" for f in row.findings)


def test_fiscal_year_spellings_do_not_bypass_annual_reconciliation() -> None:
    value = accounts(ready_case(), "FY", cash_taxes_paid="-99.00")
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"fiscal_year": "FY2024/25"}) if p.period_id == "FY" else p
                for p in value.periods
            )
        }
    )
    report = assess(value)
    assert report.readiness.status == "blocked"
    assert report.period_reconciliation
    failures = [
        c
        for c in report.period_reconciliation.checks
        if c.check_id in report.readiness.mandatory_check_ids
        and c.check_type == "FY_QUARTERS"
        and c.metric_id == "cash_taxes_paid"
    ]
    assert len(failures) == 1 and failures[0].status == "BLOCK"


def test_tax_amount_without_located_evidence_is_refused_at_public_boundary() -> None:
    pack, review = frozen(ready_case())
    value = review.books[0]
    value = value.model_copy(
        update={
            "accounts": tuple(
                r.model_copy(update={"value": r.value.model_copy(update={"citations": ()})})
                if r.metric_id == "effective_tax_rate"
                else r
                for r in value.accounts
            )
        }
    )
    review = review.model_copy(update={"books": (value,)})
    with pytest.raises(ValueError, match="known observation requires amount and citations"):
        assess_model_readiness(pack, review, value.book_id)
