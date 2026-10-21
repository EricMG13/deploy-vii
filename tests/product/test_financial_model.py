"""Synthetic integration cases for the historical Model calculation artifact."""

from datetime import date
from decimal import Decimal, localcontext

import pytest

from deploy_vii.financial_contracts import AccountObservation, AddbackObservation, FinancialBook
from deploy_vii.financial_model import ModelMetric, ModelReport, model_report, validate_model_report
from deploy_vii.model._cells import CONTEXT
from tests.product.test_financial_periods import frozen
from tests.product.test_financials import _C, book, facility, observed, period


def model_case() -> FinancialBook:
    base = book()
    periods = tuple(
        period(f"Q{i}", start, end, i)
        for i, start, end in (
            (1, "2025-01-01", "2025-03-31"),
            (2, "2025-04-01", "2025-06-30"),
            (3, "2025-07-01", "2025-09-30"),
            (4, "2025-10-01", "2025-12-31"),
        )
    )
    opening = period("OPEN", "2024-12-31", "2024-12-31", 4, "PERIOD_END").model_copy(
        update={"fiscal_year": "2024"}
    )
    fy = period("FY", "2025-01-01", "2025-12-31", 4, "FY")
    values = {
        "revenue": "100",
        "cogs": "-30",
        "opex_including_da": "-20",
        "depreciation_amortization": "-10",
        "cash_interest_paid": "-5",
        "cash_taxes_paid": "-5",
        "cfo_ncfo": "60",
        "working_capital_change": "0",
        "capex_and_intangible_investment": "-10",
        "lease_payments_in_financing": "0",
        "interest_paid_in_financing": "0",
        "operating_lease_cost": "0",
        "net_debt_issue_repay": "0",
        "net_equity_issue_repay": "0",
        "dividends_paid": "-2",
        "acquisitions_disposals": "0",
        "net_cash_change": "3",
        "cash_and_equivalents": "20",
        "rcf_commitment": "50",
        "rcf_drawn": "10",
    }
    balances = {"cash_and_equivalents", "rcf_commitment", "rcf_drawn"}
    accounts = tuple(
        AccountObservation(
            metric_id=key,
            period_id=p.period_id,
            value=observed(
                f"{p.period_id}.{key}",
                str(Decimal(amount) * (4 if p == fy and key not in balances else 1)),
            ),
        )
        for p in (*periods, fy)
        for key, amount in values.items()
    )
    accounts += (
        AccountObservation(
            metric_id="cash_and_equivalents", period_id="OPEN", value=observed("opening.cash", "5")
        ),
    )
    return base.model_copy(
        update={
            "periods": (opening, *periods, fy),
            "accounts": accounts,
            "facilities": tuple(facility(p.period_id) for p in (opening, *periods, fy)),
        }
    )


def metric(report: ModelReport, column: str, key: str) -> ModelMetric:
    basis = next(
        b.basis_id for b in report.bases if b.column_key == column and b.scope == "historical"
    )
    return next(m for m in report.metrics if m.display_basis_id == basis and m.key == key)


def test_ratios_expose_resolvable_signed_legs_and_exact_kernel_values() -> None:
    value = model_case()
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    cells = {v.value_id: v for v in report.values}
    bases = {b.basis_id: b for b in report.bases}
    assert len(cells) == len(report.values)
    for row in report.metrics:
        for leg in (row.numerator, row.denominator):
            assert all(o.value_id in cells for o in leg.operands)
        if row.value.amount is not None:
            assert row.numerator.amount is not None and row.denominator.amount is not None
            with localcontext(CONTEXT):
                assert (
                    row.value.amount == row.numerator.amount / row.denominator.amount + row.offset
                )
                for leg in (row.numerator, row.denominator):
                    assert leg.amount == sum(
                        cells[o.value_id].value.amount * o.coefficient for o in leg.operands
                    )
        assert row.evidence_quality_tier is None
    leverage = metric(report, "Q:Q4", "metric:total_leverage_adjusted")
    assert leverage.numerator.amount == 100 and leverage.denominator.amount == 240
    assert all(
        bases[cells[o.value_id].basis_id].scope == "trailing_four_quarters"
        for o in leverage.denominator.operands
    )
    margin = metric(report, "Q:Q4", "metric:ebitda_margin")
    assert margin.value.amount == Decimal("0.6") and margin.denominator.amount == 100
    assert all(
        bases[cells[o.value_id].basis_id].scope == "historical" for o in margin.denominator.operands
    )
    assert validate_model_report(pack, review, report) == ()


def test_rolling_statement_opening_is_start_of_year_not_start_of_quarter() -> None:
    value = model_case()
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    basis = next(
        b for b in report.bases if b.scope == "trailing_four_quarters" and b.column_key == "Q:Q4"
    )
    assert (basis.start_date, basis.end_date, basis.days) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
        365,
    )
    rows = {v.key: v for v in report.values if v.basis_id == basis.basis_id}
    assert rows["cash_opening"].value.amount == 5
    assert rows["ncf"].value.amount == 12
    assert rows["fx_and_other_cash"].value.amount == 3
    assert rows["fx_and_other_cash"].residual_formula == "cash_closing - cash_opening - ncf"
    assert rows["fx_and_other_cash"].value.note == "residual"
    assert len(basis.quarter_construction_ids) == 4
    assert all(
        c in {n.construction_id for n in report.historical.constructions}
        for c in basis.quarter_construction_ids
    )


@pytest.mark.parametrize("start", [date(2025, 4, 2), date(2025, 3, 31), None])
def test_gap_overlap_or_unknown_quarter_dates_cannot_support_rolling_leverage(
    start: date | None,
) -> None:
    value = model_case()
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(
                    update={
                        "start_date": start,
                        "limitation": "Synthetic uncertain quarter boundary",
                    }
                )
                if p.period_id == "Q2"
                else p
                for p in value.periods
            )
        }
    )
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    row = metric(report, "Q:Q4", "metric:total_leverage_adjusted")
    assert row.numerator.amount == 100  # closing debt remains usable
    assert row.denominator.amount is None and row.value.amount is None
    basis = next(
        b for b in report.bases if b.scope == "trailing_four_quarters" and b.column_key == "Q:Q4"
    )
    assert basis.days is None and basis.start_date is None and basis.limitation
    assert metric(report, "Q:Q4", "metric:ebitda_margin").value.amount == Decimal("0.6")


def test_missing_and_nonpositive_denominators_remain_visible() -> None:
    for revenue in (None, "0", "-100"):
        value = model_case()
        value = value.model_copy(
            update={
                "accounts": tuple(
                    r.model_copy(update={"value": observed(r.value.observation_id, revenue)})
                    if r.metric_id == "revenue" and r.period_id == "Q1"
                    else r
                    for r in value.accounts
                )
            }
        )
        pack, review = frozen(value)
        report = model_report(pack, review, value.book_id)
        row = metric(report, "Q:Q1", "metric:ebitda_margin")
        assert row.value.amount is None
        assert row.denominator.amount == (Decimal(revenue) if revenue is not None else None)
        assert row.denominator.operands
        assert row.value.calculation_status == "Not Calculable"
        if revenue is not None:
            assert row.value.reason == "ZERO_OR_NEGATIVE_DENOMINATOR"


def test_growth_retains_prior_period_and_minus_one() -> None:
    value = model_case()
    prior = period("FY24", "2024-01-01", "2024-12-31", 4, "FY").model_copy(
        update={"fiscal_year": "2024"}
    )
    row = AccountObservation(
        metric_id="revenue", period_id="FY24", value=observed("FY24.revenue", "250")
    )
    value = value.model_copy(
        update={"periods": (prior, *value.periods), "accounts": (*value.accounts, row)}
    )
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    growth = metric(report, "FY:FY", "revenue_growth")
    assert (
        growth.numerator.amount,
        growth.denominator.amount,
        growth.offset,
        growth.value.amount,
    ) == (400, 250, -1, Decimal("0.6"))
    inputs = {v.value_id: v for v in report.values}
    prior_input = inputs[growth.denominator.operands[0].value_id]
    basis = next(b for b in report.bases if b.basis_id == prior_input.basis_id)
    assert basis.column_key == "FY:FY24"
    assert metric(report, "Q:Q1", "revenue_growth").value.amount is None


def test_house_addback_variant_is_explicit_and_keeps_negative_deductions() -> None:
    value = model_case()
    addbacks = tuple(
        AddbackObservation(
            addback_id="synergy",
            addback_label="Synthetic synergy",
            classification="SYNERGY",
            realization_status="UNREALIZED",
            display_priority=1,
            period_id=p.period_id,
            value=observed(f"synergy.{p.period_id}", "-3" if p.period_id == "Q2" else "5"),
            source_definition="Synthetic unrealized synergy",
            classification_citations=(_C,),
        )
        for p in value.periods
    )
    value = value.model_copy(update={"addbacks": addbacks})
    pack, review = frozen(value)
    original = model_report(pack, review, value.book_id)
    house = model_report(pack, review, value.book_id, exclude_unrealised=True)
    assert original.historical.content_hash() == house.historical.content_hash()
    assert original.content_hash() != house.content_hash()
    assert metric(original, "Q:Q1", "metric:adjusted_ebitda_margin").numerator.amount == 65
    assert metric(house, "Q:Q1", "metric:adjusted_ebitda_margin").numerator.amount == 60
    assert metric(house, "Q:Q2", "metric:adjusted_ebitda_margin").numerator.amount == 57
    assert validate_model_report(pack, review, house) == ()


def test_unconverted_foreign_facility_blocks_model_ratio_and_retains_original() -> None:
    value = model_case()
    foreign = tuple(
        facility(p.period_id, "euro").model_copy(update={"currency": "EUR"}) for p in value.periods
    )
    value = value.model_copy(update={"facilities": (*value.facilities, *foreign)})
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    row = metric(report, "Q:Q4", "metric:total_leverage_adjusted")
    assert row.numerator.amount is None and row.value.amount is None
    assert all(v.currency == "USD" for v in report.values if v.key == "fac:euro")
    assert all(
        n.source_currency == "EUR" and n.amount is None
        for n in report.historical.facility_normalizations
    )


def test_model_report_rejects_tampering_and_is_context_independent() -> None:
    value = model_case()
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    with localcontext() as context:
        context.prec = 2
        assert model_report(pack, review, value.book_id) == report
    row = report.metrics[-1]
    forged = row.model_copy(update={"formula": "invented"})
    assert validate_model_report(
        pack, review, report.model_copy(update={"metrics": (*report.metrics[:-1], forged)})
    )
    assert validate_model_report(pack, review, report.model_copy(update={"values": ()}))
    with pytest.warns(UserWarning, match="Pydantic serializer warnings"):
        assert validate_model_report(
            pack, review, report.model_copy(update={"exclude_unrealised": "false"})
        )
    assert validate_model_report(pack, review.model_copy(update={"issuer_id": "stale"}), report)


@pytest.mark.parametrize("end,expected_days", [("2026-01-06", 371), ("2026-01-07", None)])
def test_rolling_span_accepts_53_weeks_but_not_a_longer_year(
    end: str, expected_days: int | None
) -> None:
    value = model_case()
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"end_date": date.fromisoformat(end)})
                if p.period_id == "Q4"
                else p
                for p in value.periods
            )
        }
    )
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    basis = next(
        b for b in report.bases if b.scope == "trailing_four_quarters" and b.column_key == "Q:Q4"
    )
    assert basis.days == expected_days
    assert (metric(report, "Q:Q4", "metric:total_leverage_adjusted").value.amount is not None) == (
        expected_days is not None
    )


def test_missing_quarter_keeps_missing_component_reference_and_unknown_ratios() -> None:
    value = model_case()
    value = value.model_copy(
        update={
            "periods": tuple(p for p in value.periods if p.period_id != "Q2"),
            "accounts": tuple(r for r in value.accounts if r.period_id != "Q2"),
            "facilities": tuple(r for r in value.facilities if r.period_id != "Q2"),
        }
    )
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    basis = next(
        b for b in report.bases if b.scope == "trailing_four_quarters" and b.column_key == "Q:Q4"
    )
    assert basis.quarter_construction_ids[1] is None
    assert basis.days is None
    assert metric(report, "Q:Q4", "metric:total_leverage_adjusted").value.amount is None


def test_interim_leverage_is_not_applicable_but_liquidity_uses_its_own_balance() -> None:
    value = model_case()
    half = period("H1", "2025-01-01", "2025-06-30", 2, "YTD")
    # Make the interim the latest period, keeping no later quarters or FY.
    rows = tuple(p for p in value.periods if p.period_id in {"OPEN", "Q1", "Q2"})
    value = value.model_copy(
        update={
            "periods": (*rows, half),
            "accounts": tuple(r for r in value.accounts if r.period_id in {"OPEN", "Q1", "Q2"})
            + tuple(
                r.model_copy(
                    update={
                        "period_id": "H1",
                        "value": r.value.model_copy(update={"observation_id": "H1." + r.metric_id}),
                    }
                )
                for r in value.accounts
                if r.period_id == "Q2"
            ),
            "facilities": tuple(r for r in value.facilities if r.period_id in {"OPEN", "Q1", "Q2"}),
        }
    )
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    leverage = metric(report, "YTD:H1", "metric:total_leverage_adjusted")
    assert leverage.value.reason == "NOT_APPLICABLE"
    assert leverage.numerator.amount is None and leverage.numerator.operands == ()
    liquidity = metric(report, "YTD:H1", "metric:liquidity_to_debt")
    assert liquidity.numerator.amount == 60 and liquidity.denominator.amount == 100
    inputs = {v.value_id: v for v in report.values}
    assert inputs[liquidity.numerator.operands[0].value_id].basis_id == liquidity.display_basis_id


def test_ltm_growth_fallback_links_to_prior_rolling_quarters() -> None:
    value = model_case()
    quarters = tuple(p for p in value.periods if p.period_type == "QUARTER")
    before = tuple(
        p.model_copy(
            update={
                "period_id": "prior." + p.period_id,
                "fiscal_year": "2024",
                "start_date": p.start_date.replace(year=2024),
                "end_date": p.end_date.replace(year=2024),
            }
        )
        for p in quarters
    )
    ids = {p.period_id for p in quarters}
    rows = tuple(
        r.model_copy(
            update={
                "period_id": "prior." + r.period_id,
                "value": observed(
                    "prior." + r.value.observation_id,
                    "80"
                    if r.metric_id == "revenue"
                    else "5"
                    if r.metric_id == "cash_and_equivalents" and r.period_id == "Q4"
                    else str(r.value.amount),
                ),
            }
        )
        for r in value.accounts
        if r.period_id in ids
    )
    value = value.model_copy(
        update={
            "periods": (*before, *value.periods),
            "accounts": (*rows, *value.accounts),
            "facilities": (*value.facilities, *(facility(p.period_id) for p in before)),
        }
    )
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    row = metric(report, "LTM:FY", "revenue_growth")
    assert row.denominator.amount == 320 and row.value.amount == Decimal("0.25")
    cells = {v.value_id: v for v in report.values}
    denominator = cells[row.denominator.operands[0].value_id]
    basis = next(b for b in report.bases if b.basis_id == denominator.basis_id)
    assert basis.scope == "trailing_four_quarters" and basis.column_key == "Q:prior.Q4"
    assert basis.days == 366


def test_corporate_segment_growth_remains_not_applicable_with_valid_prior() -> None:
    from deploy_vii.financial_contracts import SegmentAllocation, SegmentObservation

    value = model_case()
    prior = period("FY24", "2024-01-01", "2024-12-31", 4, "FY").model_copy(
        update={"fiscal_year": "2024"}
    )
    segments = tuple(
        SegmentObservation(
            segment_id="corp",
            segment_name="Corporate",
            segment_type="CORPORATE_ELIMINATION",
            display_priority=1,
            period_id=pid,
            revenue=observed("corp." + pid, amount),
            classification_citations=(_C,),
        )
        for pid, amount in (("FY24", "1"), ("FY", "2"))
    )
    value = value.model_copy(
        update={
            "periods": (prior, *value.periods),
            "segments": segments,
            "segment_disclosure": value.segment_disclosure.model_copy(
                update={"status": "complete"}
            ),
            "segment_allocation": (
                SegmentAllocation(
                    slot_id="DIVISION_1",
                    slot_label="Corporate",
                    component_segment_ids=("corp",),
                    rationale="Synthetic allocation",
                ),
            ),
        }
    )
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    row = metric(report, "FY:FY", "bu_growth:corp")
    assert row.value.reason == "NOT_APPLICABLE"
    assert row.numerator.operands == () and row.denominator.operands == ()
