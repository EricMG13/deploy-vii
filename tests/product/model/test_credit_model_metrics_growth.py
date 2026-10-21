"""Credit metrics: growth, PF-LTM variants, leases and what a metric leaves out."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext

from deploy_vii.model._cells import CONTEXT, refs
from deploy_vii.model.frame import Cell, Column
from deploy_vii.model.metrics import metric_frame
from tests.product.model.credit_model_fixture import example_registers
from tests.product.model.metrics_cases import _cells, _div, _fy, _metrics, _model, _v


def _rise(current: Decimal, prior: Decimal) -> Decimal:
    with localcontext(CONTEXT):
        return current / prior - 1


def test_growth_compares_like_periods() -> None:
    result, frame, _ = _metrics()

    def growth(column_id: str, prior_id: str, key: str) -> Decimal:
        return _rise(_v(frame[column_id], key), _v(frame[prior_id], key))

    assert result["Q:Q2_2026"]["revenue_growth"] == Cell(
        _rise(Decimal(3008), Decimal(2940)),
        basis="CALCULATED",
        sources=refs(
            [
                *frame["Q:Q2_2026"]["revenue"].sources,
                *frame["Q:Q2_2025"]["revenue"].sources,
            ]
        ),
    )
    assert result["YTD:H1_2026"]["revenue_growth"].value == growth(
        "YTD:H1_2026", "PYTD:H1_2025", "revenue"
    )
    assert result["FY:FY2025"]["adjusted_ebitda_growth"].value == growth(
        "FY:FY2025", "FY:FY2024", "adjusted_ebitda"
    )
    assert result["FY:FY2025"]["bu_growth:regional"].value == growth(
        "FY:FY2025", "FY:FY2024", "bu:regional"
    )
    # A projection against the last FY, then its own case's prior year.
    assert result["BASE:2026"]["bu_growth:las_vegas"].value == Decimal("0.02")
    assert result["DOWNSIDE:2026"]["bu_growth:las_vegas"].value == Decimal("-0.05")
    regional = result["BASE:2027"]["bu_growth:regional"].value
    assert regional == _rise(Decimal("1.05"), Decimal("1.02"))
    assert result["BASE:2027"]["revenue_growth"].value == growth(
        "BASE:2027", "BASE:2026", "revenue"
    )
    assert result["DOWNSIDE:2027"]["adjusted_ebitda_growth"].value == growth(
        "DOWNSIDE:2027", "DOWNSIDE:2026", "adjusted_ebitda"
    )
    # No prior, or no like period: not applicable.
    na = Cell(None, "NOT_APPLICABLE")
    for column_id in (
        "Q:Q1_2024",
        "FY:FY2023",
        "PYTD:H1_2025",
        "PF:LTM_Q2_2026",
    ):
        assert result[column_id]["revenue_growth"] == na, column_id
        assert result[column_id]["adjusted_ebitda_growth"] == na, column_id
    assert result["FY:FY2025"]["bu_growth:corporate_eliminations"] == na
    assert result["BASE:2026"]["bu_growth:corporate_eliminations"] == na
    # The LTM against the LTM ending a year earlier, at Q2 2025: revenue
    # 2,807 + 2,783 + 2,810 + 2,940, adjusted EBITDA 973 + 965 + 975 + 1,017
    # and Las Vegas 1,000 + 1,020 + 1,040 + 1,092.
    ltm = result["LTM:LTM_Q2_2026"]
    assert ltm["revenue_growth"].value == _rise(Decimal(11654), Decimal(11340))
    assert ltm["adjusted_ebitda_growth"].value == _rise(Decimal(4089), Decimal(3930))
    assert ltm["bu_growth:las_vegas"].value == _rise(Decimal(4256), Decimal(4152))
    assert ltm["bu_growth:corporate_eliminations"] == na


def test_growth_takes_a_like_period_within_a_week_of_a_year_earlier() -> None:
    now = _fy("FY:B", "2025-12-31", "FY2025")
    cells = {"FY:B": _cells(revenue="110", adjusted_ebitda="0")}
    for end, found in (
        ("2024-12-24", True),  # 372 days
        ("2024-12-23", False),  # 373
        ("2025-01-07", True),  # 358
        ("2025-01-08", False),  # 357
    ):
        prior = _fy("FY:A", end, "FY2024")
        frame = {**cells, "FY:A": _cells(revenue="100", adjusted_ebitda="-1")}
        out = metric_frame((now, prior), frame, {})["FY:B"]
        if found:
            assert out["revenue_growth"].value == Decimal("0.1"), end
            assert out["adjusted_ebitda_growth"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
        else:
            assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE"), end
    # Another kind is never the like period; a missing figure carries.
    quarter = replace(_fy("Q:A", "2024-12-31", "FY2024"), kind="QUARTER")
    frame = {**cells, "Q:A": _cells(revenue="100")}
    out = metric_frame((now, quarter), frame, {"Q:A": {}})["FY:B"]
    assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE")
    prior = _fy("FY:A", "2024-12-31", "FY2024")
    frame = {**cells, "FY:A": {"revenue": Cell(None, "NOT_STATED")}}
    out = metric_frame((now, prior), frame, {})["FY:B"]
    assert out["revenue_growth"] == Cell(None, "NOT_STATED")
    assert out["adjusted_ebitda_growth"] == Cell(None, "NOT_SOURCED")
    # Without an end date there is no like period.
    undated = replace(now, end_date=None)
    out = metric_frame((undated, prior), frame, {})["FY:B"]
    assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE")


def test_projected_growth_needs_a_four_digit_year() -> None:
    projected = Column("BASE:X", "PROJECTED", "X", "X", "FYX", None, 365, "BASE")
    fiscal = _fy("FY:A", "2024-12-31", "FY2024")
    frame = {"BASE:X": _cells(revenue="110"), "FY:A": _cells(revenue="100")}
    out = metric_frame((projected, fiscal), frame, {})["BASE:X"]
    assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE")
    # The other case's prior year is never the prior.
    later = replace(projected, column_id="BASE:2026", fiscal_year="2026")
    other = replace(projected, column_id="DOWNSIDE:2025", fiscal_year="2025")
    other = replace(other, case="DOWNSIDE")
    frame = {"BASE:2026": _cells(revenue="110"), "DOWNSIDE:2025": _cells(revenue="1")}
    out = metric_frame((later, other), frame, {})["BASE:2026"]
    assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE")


def test_pf_leverage_uses_pf_debt_and_pf_ebitda() -> None:
    result, frame, _ = _metrics()
    pf = frame["PF:LTM_Q2_2026"]
    # The $600m add-on notes and Silverlake's 45 of adjusted EBITDA.
    assert _v(pf, "total_debt") == 14106 + 600
    assert _v(pf, "adjusted_ebitda") == 4089 + 45
    cells = result["PF:LTM_Q2_2026"]
    assert cells["metric:total_leverage_adjusted"].value == _div(Decimal(14706), Decimal(4134))
    assert cells["metric:senior_secured_leverage"].value == _div(
        _v(pf, "secured_debt"), Decimal(4134)
    )
    assert cells["metric:interest_coverage_adjusted"].value == _div(
        Decimal(4134), -_v(pf, "cash_interest")
    )
    assert cells["metric:total_leverage_adjusted"].value != (
        result["LTM:LTM_Q2_2026"]["metric:total_leverage_adjusted"].value
    )
    # The waterfall below cash interest has no pro forma meaning.
    assert cells["metric:ffo_to_debt"] == Cell(None, "NOT_APPLICABLE")
    assert cells["metric:capex_adjusted_coverage"] == Cell(None, "NOT_APPLICABLE")


def test_pf_reported_ebitda_variants_are_not_applicable() -> None:
    result, frame, _ = _metrics()
    cells = result["PF:LTM_Q2_2026"]
    assert frame["PF:LTM_Q2_2026"]["ebitda"].value is not None
    for name in (
        "total_leverage_reported",
        "net_leverage_reported",
        "interest_coverage_reported",
    ):
        assert cells[f"metric:{name}"] == Cell(None, "NOT_APPLICABLE"), name
        assert result["LTM:LTM_Q2_2026"][f"metric:{name}"].value is not None
    # Acquired EBITDA over unadjusted revenue is no margin; gross margin is.
    pf = frame["PF:LTM_Q2_2026"]
    assert cells["metric:ebitda_margin"] == Cell(None, "NOT_APPLICABLE")
    assert cells["metric:adjusted_ebitda_margin"] == Cell(None, "NOT_APPLICABLE")
    assert cells["metric:gross_margin"].value == _div(_v(pf, "gross_profit"), _v(pf, "revenue"))


def test_pf_margins_with_a_revenue_adjustment() -> None:
    regs = example_registers()
    revenue = replace(
        regs.pro_forma[0],
        adjustment_id="silverlake_revenue",
        metric_id="revenue",
        value=Decimal(300),
    )
    regs = replace(regs, pro_forma=(*regs.pro_forma, revenue))
    columns, frame, ltm_ending = _model(regs)
    cells = metric_frame(columns, frame, ltm_ending)["PF:LTM_Q2_2026"]
    pf = frame["PF:LTM_Q2_2026"]
    assert _v(pf, "revenue") == 11654 + 300
    assert cells["metric:adjusted_ebitda_margin"].value == _div(Decimal(4134), Decimal(11954))
    assert cells["metric:ebitda_margin"].value == _div(_v(pf, "ebitda"), Decimal(11954))
    # The reported-EBITDA variants stay not applicable.
    assert cells["metric:total_leverage_reported"] == Cell(None, "NOT_APPLICABLE")


def test_lease_adjusted_metrics_read_the_lease_balances() -> None:
    column = _fy("FY:A", "2025-12-31")
    cells = _cells(
        total_debt="500",
        lease_adjusted_debt="600",
        lease_adjusted_net_debt="500",
        cash_closing="100",
        ffo="60",
        adjusted_ebitda="100",
        adjusted_ebitdar="150",
    )
    out = metric_frame((column,), {"FY:A": cells}, {})["FY:A"]
    assert out["metric:ffo_to_debt"].value == Decimal("0.12")
    assert out["metric:ffo_to_lease_adjusted_debt"].value == Decimal("0.1")
    assert out["metric:total_leverage_adjusted"].value == 5
    assert out["metric:lease_adjusted_leverage"].value == 4
    assert out["metric:lease_adjusted_net_leverage"].value == _div(Decimal(500), Decimal(150))


def test_corporate_names_only_segments() -> None:
    column = _fy("FY:B", "2025-12-31", "FY2025")
    prior = _fy("FY:A", "2024-12-31", "FY2024")
    frame = {
        "FY:B": _cells(revenue="110", adjusted_ebitda="22", **{"bu:revenue": "55"}),
        "FY:A": _cells(revenue="100", adjusted_ebitda="20", **{"bu:revenue": "50"}),
    }
    corporate = frozenset({"revenue", "adjusted_ebitda"})
    out = metric_frame((column, prior), frame, {}, corporate=corporate)["FY:B"]
    assert out["revenue_growth"].value == Decimal("0.1")
    assert out["adjusted_ebitda_growth"].value == Decimal("0.1")
    assert out["bu_growth:revenue"] == Cell(None, "NOT_APPLICABLE")


def test_ltm_growth_reads_the_ltm_ending_a_year_earlier() -> None:
    ltm = replace(_fy("LTM:B", "2025-12-31", "FY2025"), kind="LTM")
    frame = {"LTM:B": _cells(revenue="120", adjusted_ebitda="30")}
    # No quarter ending a year earlier: not applicable.
    out = metric_frame((ltm,), frame, {})["LTM:B"]
    assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE")
    # The quarter's own cells are not the twelve months; its LTM frame is.
    quarter = replace(_fy("Q:A", "2024-12-31", "FY2024"), kind="QUARTER")
    frame = {**frame, "Q:A": _cells(revenue="30", adjusted_ebitda="8")}
    ending = {"Q:A": _cells(revenue="100", adjusted_ebitda="25")}
    out = metric_frame((ltm, quarter), frame, ending)["LTM:B"]
    assert out["revenue_growth"].value == Decimal("0.2")
    assert out["adjusted_ebitda_growth"].value == Decimal("0.2")


_EXCLUDES_FOREIGN = "excludes facility in another currency"


_EXCLUDES_UNALLOCATED = "excludes unallocated CP-CF movements"


def _noted(cell: Cell, note: str) -> Cell:
    return replace(cell, note=note)


def test_a_metric_carries_what_its_debt_or_interest_leaves_out() -> None:
    column = _fy("FY:A", "2025-12-31")
    base = _cells(
        total_debt="500",
        cash_closing="100",
        secured_debt="300",
        ebitda="50",
        adjusted_ebitda="60",
        adjusted_ebitdar="70",
        cash_interest="-10",
        operating_lease_cost="-5",
        revenue="400",
        capex="-5",
        ffo="40",
        fcf="20",
        liquidity="150",
        lease_adjusted_debt="550",
        lease_adjusted_net_debt="450",
    )
    noted = {
        **base,
        "total_debt": _noted(base["total_debt"], f"differs from CP-1 stated; {_EXCLUDES_FOREIGN}"),
        "secured_debt": _noted(base["secured_debt"], _EXCLUDES_UNALLOCATED),
        "lease_adjusted_debt": _noted(base["lease_adjusted_debt"], _EXCLUDES_FOREIGN),
        "lease_adjusted_net_debt": _noted(base["lease_adjusted_net_debt"], _EXCLUDES_FOREIGN),
        "cash_interest": _noted(base["cash_interest"], _EXCLUDES_FOREIGN),
    }
    cells = metric_frame((column,), {"FY:A": noted}, {})["FY:A"]

    for name in (
        "total_leverage_reported",
        "net_leverage_adjusted",
        "lease_adjusted_leverage",
        "lease_adjusted_net_leverage",
        "interest_coverage_adjusted",
        "ebitdar_coverage",
        "ffo_to_debt",
        "ffo_to_lease_adjusted_debt",
        "fcf_to_debt",
        "liquidity_to_debt",
    ):
        assert cells[f"metric:{name}"].note == _EXCLUDES_FOREIGN, name
    for name in ("senior_secured_leverage", "senior_secured_net_leverage"):
        assert cells[f"metric:{name}"].note == _EXCLUDES_UNALLOCATED, name
    for name in ("fcf_to_adjusted_ebitda", "capex_to_revenue", "ebitda_margin"):
        assert cells[f"metric:{name}"].note is None, name
    both = {
        **noted,
        "secured_debt": _noted(
            base["secured_debt"], f"{_EXCLUDES_UNALLOCATED}; {_EXCLUDES_FOREIGN}"
        ),
    }
    cells = metric_frame((column,), {"FY:A": both}, {})["FY:A"]
    assert cells["metric:senior_secured_net_leverage"].note == (
        f"{_EXCLUDES_FOREIGN}; {_EXCLUDES_UNALLOCATED}"
    )
    # A metric without a figure says why, not what it would leave out.
    missing = {**noted, "ebitda": Cell(None, "NOT_STATED")}
    cells = metric_frame((column,), {"FY:A": missing}, {})["FY:A"]
    assert cells["metric:total_leverage_reported"] == Cell(None, "NOT_STATED")
    clean = metric_frame((column,), {"FY:A": base}, {})["FY:A"]
    assert all(cell.note is None for key, cell in clean.items() if key.startswith("metric:"))
