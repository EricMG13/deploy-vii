"""Derived flows and balances: calculated quarters, missing components, KPIs
and the rolling LTM frames."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.model._cells import (
    UNSPANNED,
)
from deploy_vii.model.frame import Cell, SourceRef
from deploy_vii.model.history import (
    account_frame,
    historical_columns,
    ltm_frames,
)
from tests.product.model.credit_model_fixture import example_registers
from tests.product.model.history_cases import _Figures, _regs
from tests.product.model.history_frames import _frame, _kpi, _value


def test_a_ytd_with_components_is_their_sum_and_keeps_cp1_stated() -> None:
    frame = _frame(example_registers())

    ytd = frame["YTD:H1_2026"]["acct:revenue"]
    assert (ytd.value, ytd.basis, ytd.stated, ytd.note) == (
        Decimal(5885),
        "CALCULATED",
        Decimal(5885),
        None,
    )
    assert [ref.cell_text for ref in ytd.sources] == ["2877", "3008"]
    assert frame["YTD:H1_2026"]["bu:las_vegas"].value == Decimal(2175)


def test_a_reported_quarter_is_never_replaced_by_a_calculated_one() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}, "Q2_2025": {"revenue": 120}},
        ytd={"H1_2025": {"revenue": 230}},
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    quarters = [column.column_id for column in columns if column.kind == "QUARTER"]
    assert quarters == ["Q:Q1_2025", "Q:Q2_2025"]
    assert frame["Q:Q2_2025"]["acct:revenue"] == Cell(
        Decimal(120),
        basis="REPORTED",
        sources=(SourceRef("S1", "Q2_2025", "120"),),
    )
    assert frame["Q:Q1_2025"]["acct:revenue"].value == Decimal(100)


def test_q2_and_q3_are_calculated_from_the_ytd_periods() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}},
        ytd={"H1_2025": {"revenue": 230}, "9M_2025": {"revenue": "365.5"}},
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    by_id = {column.column_id: column for column in columns}
    q2, q3 = by_id["Q:H1_2025-Q1_2025"], by_id["Q:9M_2025-H1_2025"]
    assert [column.column_id for column in columns][:3] == [
        "Q:Q1_2025",
        "Q:H1_2025-Q1_2025",
        "Q:9M_2025-H1_2025",
    ]
    assert (q2.label, q2.period_id, q2.end_date, q2.days) == (
        "Q2 25",
        None,
        "2025-06-30",
        91,
    )
    assert (q3.label, q3.end_date, q3.days) == ("Q3 25", "2025-09-30", 92)
    assert frame[q2.column_id]["acct:revenue"].value == Decimal(130)
    assert frame[q3.column_id]["acct:revenue"].value == Decimal("135.5")
    assert frame[q3.column_id]["acct:revenue"].basis == "CALCULATED"


def test_q4_is_calculated_from_fy_minus_9m_only_without_a_reported_q4() -> None:
    quarters = {f"Q{n}_2025": {"revenue": 100 + n} for n in (1, 2, 3)}
    fy = {"FY2025": {"revenue": 420}}
    ytd = {"9M_2025": {"revenue": 306}}
    regs = _regs(quarters=quarters, fy=fy, ytd=ytd)

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    q4 = next(column for column in columns if column.label == "Q4 25")
    assert q4.column_id == "Q:FY2025-9M_2025"
    assert (q4.kind, q4.period_id, q4.end_date, q4.days) == (
        "QUARTER",
        None,
        "2025-12-31",
        92,
    )
    cell = frame[q4.column_id]["acct:revenue"]
    assert (cell.value, cell.basis, cell.stated, cell.note) == (
        Decimal(114),
        "CALCULATED",
        None,
        None,
    )
    assert [ref.source_locator for ref in cell.sources] == ["FY2025", "9M_2025"]

    reported = _regs(quarters={**quarters, "Q4_2025": {"revenue": 90}}, fy=fy, ytd=ytd)
    columns = historical_columns(reported)
    assert [column.label for column in columns if column.kind == "QUARTER"] == [
        "Q1 25",
        "Q2 25",
        "Q3 25",
        "Q4 25",
    ]
    q4_cell = account_frame(reported, columns)["Q:Q4_2025"]["acct:revenue"]
    assert (q4_cell.value, q4_cell.basis) == (Decimal(90), "REPORTED")


def test_a_derived_column_with_a_missing_component_is_component_missing() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400, "cogs": -100}},
        ytd={
            "H1_2025": {"revenue": None, "cogs": -40},
            "H1_2026": {"revenue": 210, "cogs": -50},
        },
        ltm={"LTM_Q2_2026": {"revenue": 420}},
    )

    frame = _frame(regs)

    ltm = frame["LTM:LTM_Q2_2026"]
    assert ltm["acct:revenue"] == Cell(None, "COMPONENT_MISSING", stated=Decimal(420))
    assert ltm["acct:cogs"].value == Decimal(-110)
    # H1 2025's revenue row has no figure: not stated, not absent.
    assert frame["PYTD:H1_2025"]["acct:revenue"] == Cell(None, "NOT_STATED")

    no_pytd = _regs(fy={"FY2025": {"revenue": 400}}, ytd={"H1_2026": {"revenue": 1}})
    columns = historical_columns(no_pytd)
    assert [column.kind for column in columns] == ["YTD", "FY", "LTM"]
    assert account_frame(no_pytd, columns)["LTM:H1_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING"
    )

    halves = _regs(
        quarters={"Q1_2026": {"revenue": 100}},
        ytd={"H1_2026": {"revenue": 210}, "H1_2025": {"revenue": 200}},
        components={"H1_2026": ("Q1_2026", "Q2_2026")},
    )
    ytd_cell = _frame(halves)["YTD:H1_2026"]["acct:revenue"]
    assert ytd_cell == Cell(None, "COMPONENT_MISSING", stated=Decimal(210), note=UNSPANNED)


def test_a_calculated_quarter_with_a_missing_component_is_component_missing() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}},
        fy={"FY2025": {"revenue": 420}},
        ytd={"9M_2025": {"revenue": None}},
    )

    frame = _frame(regs)

    assert frame["Q:FY2025-9M_2025"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")


def test_a_stated_ltm_that_differs_beyond_rounding_is_noted() -> None:
    fy: _Figures = {"FY2025": {"revenue": 400, "ebitda": "100.4", "ebit": "80.5", "cogs": -1}}
    ytd = {
        "H1_2025": {"revenue": 190, "ebitda": 0, "ebit": 0, "cogs": 0},
        "H1_2026": {"revenue": 210, "ebitda": 0, "ebit": 0, "cogs": 0},
    }
    stated: dict[str, Decimal | int | str | None] = {
        "revenue": "420.6",
        "ebitda": 100,
        "ebit": 80,
        "cogs": "-1.0",
    }
    regs = _regs(fy=fy, ytd=ytd, ltm={"LTM_Q2_2026": stated})

    ltm = _frame(regs)["LTM:LTM_Q2_2026"]

    noted = "differs from CP-1 stated"
    # One decimal place stated: 0.6 is beyond 0.05.
    assert (ltm["acct:revenue"].value, ltm["acct:revenue"].stated) == (
        Decimal(420),
        Decimal("420.6"),
    )
    assert ltm["acct:revenue"].note == noted
    # A whole number stated: 0.4 and 0.5 are rounding, not a difference.
    assert ltm["acct:ebitda"].note is None
    assert ltm["acct:ebit"].note is None
    assert ltm["acct:ebit"].stated == Decimal(80)
    # Equal at the stated precision.
    assert ltm["acct:cogs"].note is None

    beyond = _regs(fy=fy, ytd=ytd, ltm={"LTM_Q2_2026": {"ebitda": 99, "cogs": "-1.1"}})
    frame = _frame(beyond)["LTM:LTM_Q2_2026"]
    assert frame["acct:ebitda"].note == noted
    assert frame["acct:cogs"].note == noted


def test_balances_take_the_column_end_period() -> None:
    frame = _frame(example_registers())

    def value(column_id: str, key: str) -> Decimal | None:
        return frame[column_id][key].value

    assert value("PYTD:H1_2025", "acct:total_debt") == Decimal(13870)
    assert value("YTD:H1_2026", "acct:total_debt") == Decimal(13846)
    assert value("LTM:LTM_Q2_2026", "acct:cash_and_equivalents") == Decimal(1000)
    assert value("FY:FY2023", "acct:total_debt") == Decimal(13906)
    assert value("Q:Q3_2025", "acct:cash_and_equivalents") == Decimal(920)
    # No facility row on H1 or the LTM: the quarter that ends with them.
    tlb = frame["YTD:H1_2026"]["fac:tlb"]
    assert (tlb.value, tlb.basis) == (Decimal(2316), "REPORTED")
    assert tlb.sources[0].source_id == "S11"
    assert value("LTM:LTM_Q2_2026", "fac:tlb") == Decimal(2316)
    assert value("PYTD:H1_2025", "fac:tlb") == Decimal(2340)
    assert value("FY:FY2024", "fac:tlb") == Decimal(2352)
    assert value("FY:FY2024", "fac:finl") == Decimal(260)
    # A period-end KPI is a balance too.
    assert value("YTD:H1_2026", "kpi:rewards_members") == Decimal("67.3")
    assert value("PYTD:H1_2025", "kpi:rewards_members") == Decimal("65.1")
    assert value("LTM:LTM_Q2_2026", "kpi:rewards_members") == Decimal("67.3")


def test_a_balance_on_a_calculated_quarter_is_its_end_period() -> None:
    regs = _regs(
        quarters={"Q3_2025": {"cash_and_equivalents": 50}},
        fy={"FY2025": {"revenue": 420, "cash_and_equivalents": 70}},
        ytd={"9M_2025": {"revenue": 306, "cash_and_equivalents": None}},
    )

    frame = _frame(regs)

    cash = frame["Q:FY2025-9M_2025"]["acct:cash_and_equivalents"]
    assert (cash.value, cash.basis) == (Decimal(70), "REPORTED")
    assert frame["Q:Q3_2025"]["acct:cash_and_equivalents"].value == Decimal(50)
    assert frame["Q:Q3_2025"]["acct:revenue"] == Cell(None, "NOT_SOURCED")
    assert frame["FY:FY2025"]["acct:cash_and_equivalents"].value == Decimal(70)


def test_a_rate_kpi_is_not_sourced_on_a_derived_column() -> None:
    frame = _frame(example_registers())

    occupancy = "kpi:lv_occupancy"
    assert frame["Q:Q2_2026"][occupancy].value == Decimal("94.3")
    assert frame["FY:FY2025"][occupancy].value == Decimal("92.6")
    for column_id in ("PYTD:H1_2025", "YTD:H1_2026", "LTM:LTM_Q2_2026"):
        assert frame[column_id][occupancy] == Cell(None, "NOT_SOURCED"), column_id

    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}},
        fy={"FY2025": {"revenue": 420}},
        ytd={"9M_2025": {"revenue": 306}},
    )
    rates = (
        _kpi("occupancy", "RATE", "FY2025", "91.0"),
        _kpi("occupancy", "RATE", "9M_2025", "92.0"),
        _kpi("nights", "PERIOD_FLOW", "FY2025", "40"),
        _kpi("nights", "PERIOD_FLOW", "9M_2025", "31"),
    )
    frame = _frame(replace(regs, kpis=rates))
    assert frame["Q:FY2025-9M_2025"]["kpi:occupancy"] == Cell(None, "NOT_SOURCED")
    assert frame["Q:FY2025-9M_2025"]["kpi:nights"].value == Decimal(9)
    assert frame["FY:FY2025"]["kpi:occupancy"].value == Decimal("91.0")


def test_period_flow_kpis_segments_and_addbacks_follow_the_flow_rules() -> None:
    frame = _frame(example_registers())

    nights = frame["YTD:H1_2026"]["kpi:lv_room_nights"]
    assert (nights.value, nights.basis, nights.stated) == (
        Decimal(5111),
        "CALCULATED",
        None,
    )
    assert frame["LTM:LTM_Q2_2026"]["kpi:lv_room_nights"].value == Decimal(10001)
    assert frame["FY:FY2024"]["bu:corporate_eliminations"].value == Decimal(-60)
    savings = frame["Q:Q3_2025"]["addback:run_rate_cost_savings"]
    assert (savings.value, savings.basis) == (Decimal(10), "REPORTED")
    assert frame["LTM:LTM_Q2_2026"]["bu:digital"].value == Decimal(1339)


def test_an_account_outside_both_lists_is_shown_only_for_its_own_period() -> None:
    regs = _regs(
        quarters={"Q2_2026": {"effective_tax_rate": "0.3"}},
        fy={"FY2025": {"revenue": 400, "effective_tax_rate": "0.21"}},
        ytd={
            "H1_2025": {"revenue": 190, "effective_tax_rate": "0.2"},
            "H1_2026": {"revenue": 210},
        },
    )

    frame = _frame(regs)

    assert frame["FY:FY2025"]["acct:effective_tax_rate"].value == Decimal("0.21")
    assert frame["PYTD:H1_2025"]["acct:effective_tax_rate"].value == Decimal("0.2")
    assert frame["YTD:H1_2026"]["acct:effective_tax_rate"] == Cell(None, "NOT_SOURCED")
    assert frame["LTM:H1_2026"]["acct:effective_tax_rate"] == Cell(None, "NOT_SOURCED")


def test_ltm_frames_sum_the_four_quarters_ending_each_quarter() -> None:
    regs = example_registers()
    columns = historical_columns(regs)

    frames = ltm_frames(regs, columns)

    assert list(frames) == [c.column_id for c in columns if c.kind == "QUARTER"]
    assert frames["Q:Q2_2026"]["acct:revenue"].value == Decimal(11654)
    assert frames["Q:Q2_2026"]["acct:revenue"].basis == "CALCULATED"
    assert len(frames["Q:Q2_2026"]["acct:revenue"].sources) == 4
    assert frames["Q:Q4_2024"]["acct:revenue"].value == Decimal(11165)
    assert frames["Q:Q4_2025"]["acct:adjusted_ebitda"].value == Decimal(4019)
    assert frames["Q:Q4_2025"]["kpi:lv_room_nights"].value == Decimal(9900)
    assert frames["Q:Q3_2024"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")
    # Balances and period-end KPIs are the quarter's own; rates are not summed.
    assert frames["Q:Q3_2025"]["acct:total_debt"].value == Decimal(13864)
    assert frames["Q:Q3_2025"]["fac:tlb"].value == Decimal(2334)
    assert frames["Q:Q3_2025"]["kpi:rewards_members"].value == Decimal("65.6")
    assert frames["Q:Q3_2025"]["kpi:lv_occupancy"] == Cell(None, "NOT_SOURCED")
    # Whatever the order the columns come in.
    assert set(ltm_frames(regs, tuple(reversed(columns)))) == set(frames)


def test_ltm_frames_include_calculated_quarters_and_refuse_a_gap() -> None:
    quarters = {
        "Q4_2024": {"revenue": 10},
        "Q1_2025": {"revenue": 1},
        "Q2_2025": {"revenue": 2},
        "Q3_2025": {"revenue": 3},
    }
    regs = _regs(
        quarters=quarters,
        fy={"FY2025": {"revenue": 10}},
        ytd={"9M_2025": {"revenue": 6}},
    )
    columns = historical_columns(regs)

    frames = ltm_frames(regs, columns)

    assert frames["Q:FY2025-9M_2025"]["acct:revenue"].value == Decimal(10)
    assert frames["Q:Q3_2025"]["acct:revenue"].value == Decimal(16)

    gap = _regs(quarters={k: v for k, v in quarters.items() if k != "Q2_2025"})
    gap_frames = ltm_frames(gap, historical_columns(gap))
    assert gap_frames["Q:Q3_2025"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")
    assert set(ltm_frames(gap, ())) == set()


_CENTS = st.integers(min_value=-(10**12), max_value=10**12).map(
    lambda cents: Decimal(cents).scaleb(-2)
)


@settings(deadline=None, max_examples=200)
@given(st.lists(_CENTS, min_size=6, max_size=6), st.lists(_CENTS, min_size=6, max_size=6))
def test_derived_flows_reconcile_for_any_quarter_values(
    revenue: list[Decimal], interest: list[Decimal]
) -> None:
    ids = ["Q1_2025", "Q2_2025", "Q3_2025", "Q4_2025", "Q1_2026", "Q2_2026"]
    quarters = {
        period_id: {"revenue": rev, "cash_interest_paid": paid}
        for period_id, rev, paid in zip(ids, revenue, interest, strict=True)
    }
    regs = _regs(
        quarters=quarters,
        fy={"FY2025": {}},
        ytd={"H1_2025": {}, "H1_2026": {}},
        components={
            "FY2025": tuple(ids[:4]),
            "H1_2025": tuple(ids[:2]),
            "H1_2026": tuple(ids[4:]),
        },
    )

    frame = _frame(regs)

    # An outflow reads as minus its absolute value, whatever sign CP-1 wrote.
    for key, values in (
        ("acct:revenue", revenue),
        ("acct:cash_interest_paid", [-abs(paid) for paid in interest]),
    ):
        fy = _value(frame["FY:FY2025"][key])
        ytd = _value(frame["YTD:H1_2026"][key])
        pytd = _value(frame["PYTD:H1_2025"][key])
        assert fy == sum(values[:4], Decimal(0))
        assert ytd == values[4] + values[5]
        assert pytd == values[0] + values[1]
        assert frame["LTM:H1_2026"][key].value == fy + ytd - pytd
        assert frame["LTM:H1_2026"][key].value == sum(values[2:], Decimal(0))
