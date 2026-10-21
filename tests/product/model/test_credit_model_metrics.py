"""Credit metrics: leverage, coverage and ratios per column, with reasons."""

from __future__ import annotations

from decimal import Decimal

import pytest

from deploy_vii.model.frame import Cell, SourceRef
from deploy_vii.model.metrics import metric_frame, unit_of
from tests.product.model.metrics_cases import _SOURCE_A, _cells, _div, _fy, _metrics, _model, _v

_LEVERAGE = (
    "total_leverage_reported",
    "total_leverage_adjusted",
    "net_leverage_reported",
    "net_leverage_adjusted",
    "senior_secured_leverage",
    "senior_secured_net_leverage",
    "lease_adjusted_leverage",
    "lease_adjusted_net_leverage",
)


_COVERAGE = (
    "interest_coverage_reported",
    "interest_coverage_adjusted",
    "capex_adjusted_coverage",
    "ebitdar_coverage",
)


_PERCENT = (
    "ffo_to_debt",
    "ffo_to_lease_adjusted_debt",
    "fcf_to_debt",
    "fcf_to_adjusted_ebitda",
    "capex_to_revenue",
    "liquidity_to_debt",
    "gross_margin",
    "ebitda_margin",
    "adjusted_ebitda_margin",
)


_SOURCE_B = SourceRef("S2", "10-Q", "200")


def test_quarter_leverage_uses_the_ltm_ending_that_quarter() -> None:
    result, frame, ltm_ending = _metrics()
    quarter = result["Q:Q2_2026"]
    ltm = ltm_ending["Q:Q2_2026"]
    # LTM to Q2 2026: adjusted EBITDA 4,089 (the quarter alone is 1,053) and
    # the host's total debt at 30 June 2026, 14,106.
    assert _v(ltm, "adjusted_ebitda") == 4089
    assert _v(frame["Q:Q2_2026"], "adjusted_ebitda") == 1053
    expected = _div(Decimal(14106), Decimal(4089))
    assert quarter["metric:total_leverage_adjusted"] == Cell(
        expected,
        basis="CALCULATED",
        sources=quarter["metric:total_leverage_adjusted"].sources,
    )
    assert result["LTM:LTM_Q2_2026"]["metric:total_leverage_adjusted"].value == (expected)
    coverage = quarter["metric:interest_coverage_adjusted"].value
    assert coverage == _div(Decimal(4089), -_v(ltm, "cash_interest"))
    # Margins stay on the quarter's own period.
    own = frame["Q:Q2_2026"]
    assert quarter["metric:adjusted_ebitda_margin"].value == _div(Decimal(1053), _v(own, "revenue"))
    # Same-period flow ratios are on the quarter's own period too; a ratio
    # against a balance is on its twelve months.
    assert quarter["metric:capex_to_revenue"].value == _div(-_v(own, "capex"), _v(own, "revenue"))
    assert quarter["metric:fcf_to_adjusted_ebitda"].value == _div(_v(own, "fcf"), Decimal(1053))
    assert quarter["metric:fcf_to_debt"].value == _div(_v(ltm, "fcf"), _v(ltm, "total_debt"))
    assert quarter["metric:liquidity_to_debt"].value == _div(
        _v(ltm, "liquidity"), _v(ltm, "total_debt")
    )
    # The first quarters have no four to sum: the LTM's reason carries.
    first = result["Q:Q1_2024"]["metric:total_leverage_adjusted"]
    assert first == Cell(None, "COMPONENT_MISSING")


def test_ytd_leverage_is_not_applicable() -> None:
    result, frame, _ = _metrics()
    for column_id in ("YTD:H1_2026", "PYTD:H1_2025"):
        cells = result[column_id]
        for name in (*_LEVERAGE, *_COVERAGE, "ffo_to_debt", "fcf_to_debt"):
            assert cells[f"metric:{name}"] == Cell(None, "NOT_APPLICABLE"), name
        assert cells["metric:ffo_to_lease_adjusted_debt"].reason == "NOT_APPLICABLE"
        own = frame[column_id]
        assert cells["metric:gross_margin"].value == _div(
            _v(own, "gross_profit"), _v(own, "revenue")
        )
        assert cells["metric:fcf_to_adjusted_ebitda"].value == _div(
            _v(own, "fcf"), _v(own, "adjusted_ebitda")
        )
        assert cells["metric:liquidity_to_debt"].value == _div(
            _v(own, "liquidity"), _v(own, "total_debt")
        )


def test_each_metric_has_reported_and_adjusted_variants_where_named() -> None:
    result, frame, _ = _metrics()
    ltm = frame["LTM:LTM_Q2_2026"]
    cells = result["LTM:LTM_Q2_2026"]
    debt, cash = _v(ltm, "total_debt"), _v(ltm, "cash_closing")
    ebitda, adjusted = _v(ltm, "ebitda"), _v(ltm, "adjusted_ebitda")
    ebitdar, secured = _v(ltm, "adjusted_ebitdar"), _v(ltm, "secured_debt")
    interest, capex = -_v(ltm, "cash_interest"), _v(ltm, "capex")
    lease_cost, revenue = _v(ltm, "operating_lease_cost"), _v(ltm, "revenue")
    leased = _v(ltm, "lease_adjusted_debt")
    expected = {
        "total_leverage_reported": _div(debt, ebitda),
        "total_leverage_adjusted": _div(debt, adjusted),
        "net_leverage_reported": _div(debt - cash, ebitda),
        "net_leverage_adjusted": _div(debt - cash, adjusted),
        "senior_secured_leverage": _div(secured, adjusted),
        "senior_secured_net_leverage": _div(secured - cash, adjusted),
        "lease_adjusted_leverage": _div(leased, ebitdar),
        "lease_adjusted_net_leverage": _div(_v(ltm, "lease_adjusted_net_debt"), ebitdar),
        "interest_coverage_reported": _div(ebitda, interest),
        "interest_coverage_adjusted": _div(adjusted, interest),
        "capex_adjusted_coverage": _div(adjusted + capex, interest),
        "ebitdar_coverage": _div(ebitdar + capex, interest - lease_cost),
        "ffo_to_debt": _div(_v(ltm, "ffo"), debt),
        "ffo_to_lease_adjusted_debt": _div(_v(ltm, "ffo"), leased),
        "fcf_to_debt": _div(_v(ltm, "fcf"), debt),
        "fcf_to_adjusted_ebitda": _div(_v(ltm, "fcf"), adjusted),
        "capex_to_revenue": _div(-capex, revenue),
        "liquidity_to_debt": _div(_v(ltm, "liquidity"), debt),
        "gross_margin": _div(_v(ltm, "gross_profit"), revenue),
        "ebitda_margin": _div(ebitda, revenue),
        "adjusted_ebitda_margin": _div(adjusted, revenue),
    }
    assert {key: cells[f"metric:{key}"].value for key in expected} == expected
    assert all(cells[f"metric:{key}"].basis == "CALCULATED" for key in expected)
    assert cells["metric:total_leverage_reported"].value != (
        cells["metric:total_leverage_adjusted"].value
    )
    # Reported EBITDA and lease balances are not projected; adjusted is.
    base = result["BASE:2026"]
    for name in (
        "total_leverage_reported",
        "net_leverage_reported",
        "interest_coverage_reported",
        "lease_adjusted_leverage",
        "lease_adjusted_net_leverage",
        "ebitdar_coverage",
        "ffo_to_debt",
        "ffo_to_lease_adjusted_debt",
        "gross_margin",
        "ebitda_margin",
    ):
        assert base[f"metric:{name}"] == Cell(None, "NOT_PROJECTED"), name
    projected = frame["BASE:2026"]
    assert base["metric:total_leverage_adjusted"].value == _div(
        _v(projected, "total_debt"), _v(projected, "adjusted_ebitda")
    )
    assert base["metric:senior_secured_net_leverage"].value == _div(
        _v(projected, "secured_debt") - _v(projected, "cash_closing"),
        _v(projected, "adjusted_ebitda"),
    )
    assert base["metric:capex_adjusted_coverage"].value == _div(
        _v(projected, "adjusted_ebitda") + _v(projected, "capex"),
        -_v(projected, "cash_interest"),
    )


def test_units_are_multiples_for_leverage_and_coverage() -> None:
    for name in (*_LEVERAGE, *_COVERAGE):
        assert unit_of(f"metric:{name}") == "MULTIPLE"
    for name in _PERCENT:
        assert unit_of(f"metric:{name}") == "PERCENT"
    for key in ("revenue_growth", "adjusted_ebitda_growth", "bu_growth:digital"):
        assert unit_of(key) == "PERCENT"
    with pytest.raises(KeyError):
        unit_of("metric:unknown")
    with pytest.raises(KeyError, match="revenue"):
        unit_of("revenue")


def test_every_column_carries_every_metric_and_keeps_its_cells() -> None:
    columns, frame, ltm_ending = _model()
    result = metric_frame(columns, frame, ltm_ending)
    assert set(result) == {c.column_id for c in columns}
    names = {f"metric:{n}" for n in (*_LEVERAGE, *_COVERAGE, *_PERCENT)}
    for column in columns:
        cells = result[column.column_id]
        assert names <= set(cells)
        assert {k: cells[k] for k in frame[column.column_id]} == (frame[column.column_id])
    # Without `corporate`, every segment is compared: eliminations are
    # negative, so the denominator refuses.
    eliminations = result["FY:FY2025"]["bu_growth:corporate_eliminations"]
    assert eliminations == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")


def test_a_non_positive_denominator_is_zero_or_negative() -> None:
    column = _fy("FY:A", "2025-12-31")
    base = _cells(
        total_debt="500",
        cash_closing="100",
        secured_debt="300",
        ebitda="0",
        adjusted_ebitda="-10",
        cash_interest="0",
        operating_lease_cost="0",
        revenue="0",
        capex="-5",
    )
    cells = metric_frame((column,), {"FY:A": base}, {})["FY:A"]
    for name in (
        "total_leverage_reported",
        "total_leverage_adjusted",
        "senior_secured_leverage",
        "interest_coverage_reported",
        "capex_adjusted_coverage",
        "capex_to_revenue",
        "adjusted_ebitda_margin",
    ):
        assert cells[f"metric:{name}"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    # A missing input carries its own reason, the first in formula order.
    assert cells["metric:lease_adjusted_leverage"] == Cell(None, "NOT_SOURCED")
    assert cells["metric:ebitdar_coverage"] == Cell(None, "NOT_SOURCED")
    # A positive denominator is a ratio, sourced once per source.
    positive = {
        **base,
        "ebitda": Cell(Decimal("0.5"), sources=(_SOURCE_B, _SOURCE_A)),
        "cash_interest": Cell(Decimal("-0.25")),
    }
    cells = metric_frame((column,), {"FY:A": positive}, {})["FY:A"]
    assert cells["metric:total_leverage_reported"] == Cell(
        Decimal(1000), basis="CALCULATED", sources=(_SOURCE_A, _SOURCE_B)
    )
    assert cells["metric:interest_coverage_reported"].value == 2
    assert cells["metric:net_leverage_reported"].value == 800


def test_a_missing_input_gives_its_reason_first_in_formula_order() -> None:
    column = _fy("FY:A", "2025-12-31")
    cells = {
        **_cells(total_debt="500", cash_closing="100", revenue="10"),
        "ebitda": Cell(None, "NOT_STATED"),
        "secured_debt": Cell(None, "COMPONENT_MISSING"),
        "adjusted_ebitda": Cell(None, "NOT_APPLICABLE"),
        "cash_interest": Cell(Decimal(-5)),
    }
    out = metric_frame((column,), {"FY:A": cells}, {})["FY:A"]
    assert out["metric:total_leverage_reported"] == Cell(None, "NOT_STATED")
    assert out["metric:senior_secured_leverage"] == Cell(None, "COMPONENT_MISSING")
    assert out["metric:senior_secured_net_leverage"] == Cell(None, "COMPONENT_MISSING")
    assert out["metric:total_leverage_adjusted"] == Cell(None, "NOT_APPLICABLE")
    # The numerator's reason before the denominator's.
    assert out["metric:interest_coverage_reported"] == Cell(None, "NOT_STATED")
    assert out["metric:fcf_to_debt"] == Cell(None, "NOT_SOURCED")
