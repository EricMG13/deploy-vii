"""Period registers of every shape: irregular periods, fiscal labels and the
register's own LTM."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from deploy_vii.model.frame import Cell
from deploy_vii.model.history import (
    account_frame,
    historical_columns,
    ltm_frames,
)
from deploy_vii.model.registers import (
    AccountRow,
)
from tests.product.model.credit_model_fixture import example_registers
from tests.product.model.history_cases import _regs
from tests.product.model.history_frames import _frame, _kpi


def test_an_irregular_period_is_kept_without_a_guess() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}, "Q4_2025": {"revenue": 1}},
        ytd={"H1_2025": {"revenue": 230}},
    )
    q1, q4, h1 = regs.periods
    stub = replace(q4, period_id="STUB", fiscal_quarter=None, end_date=None)
    regs = replace(
        regs,
        periods=(replace(q1, day_count=None), stub, h1),
        accounts=(
            *regs.accounts,
            AccountRow("revenue", "STUB", Decimal(5), "VERIFIED", None),
            AccountRow("total_debt", "STUB", Decimal(7), "VERIFIED", None),
        ),
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)
    frames = ltm_frames(regs, columns)

    assert [(c.column_id, c.label) for c in columns if c.kind == "QUARTER"] == [
        ("Q:STUB", "STUB"),
        ("Q:Q1_2025", "Q1 25"),
        ("Q:H1_2025-Q1_2025", "Q2 25"),
    ]
    assert columns[2].days is None
    assert frame["Q:STUB"]["acct:revenue"].value == Decimal(5)
    assert frame["Q:Q1_2025"]["acct:total_debt"] == Cell(None, "NOT_SOURCED")
    assert frames["Q:STUB"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")
    assert frames["Q:STUB"]["acct:total_debt"].value == Decimal(7)


def test_fiscal_quarters_read_with_or_without_a_q() -> None:
    regs = _regs(quarters={"Q1_2025": {"revenue": 1}, "Q2_2025": {"revenue": 2}})
    q1, q2 = regs.periods
    regs = replace(
        regs,
        periods=(replace(q1, fiscal_quarter="q1"), replace(q2, fiscal_quarter="Q2")),
    )

    columns = historical_columns(regs)

    # Both quarters to date are columns, so they are the YTD.
    assert [column.label for column in columns] == [
        "Q1 25",
        "Q2 25",
        "YTD H1 25",
        "LTM Q2 25",
    ]
    assert ltm_frames(regs, columns)["Q:Q2_2025"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")


def test_a_fiscal_year_without_four_digits_is_labelled_by_its_last_two() -> None:
    regs = _regs(
        quarters={f"Q{n}_2025": {"revenue": n} for n in (1, 2, 3, 4)},
        ytd={"H1_2025": {"revenue": 3}, "H1_2026": {"revenue": 5}},
    )
    regs = replace(
        regs,
        periods=tuple(replace(p, fiscal_year=f"Y{p.fiscal_year[2:]}") for p in regs.periods),
    )

    columns = historical_columns(regs)

    assert [column.label for column in columns] == [
        "Q1 25",
        "Q2 25",
        "Q3 25",
        "Q4 25",
        "PYTD H1 25",
        "YTD H1 26",
        "LTM Q2 26",
    ]
    # No year to count back from: no LTM year and no trailing quarters; the
    # PYTD is still found by its dates, twelve months before the YTD.
    ltm = account_frame(regs, columns)["LTM:H1_2026"]["acct:revenue"]
    assert ltm == Cell(None, "COMPONENT_MISSING")
    frames = ltm_frames(regs, columns)
    assert frames["Q:Q4_2025"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")


def test_undated_periods_are_never_the_latest() -> None:
    dated = _regs(
        fy={"FY2024": {"revenue": 1}, "FY2025": {"revenue": 2}},
        ytd={"H1_2026": {"revenue": 3}},
    )
    fy24, fy25, h1 = dated.periods
    no_fy_end = replace(dated, periods=(replace(fy24, end_date=None), fy25, h1))
    assert [c.column_id for c in historical_columns(no_fy_end)] == [
        "YTD:H1_2026",
        "FY:FY2024",
        "FY:FY2025",
        "LTM:H1_2026",
    ]
    assert _frame(no_fy_end)["LTM:H1_2026"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")

    no_ytd_end = replace(dated, periods=(fy24, fy25, replace(h1, end_date=None)))
    assert [c.kind for c in historical_columns(no_ytd_end)] == ["FY", "FY", "LTM"]

    only_undated = replace(dated, periods=(replace(fy25, end_date=None), h1))
    assert [c.kind for c in historical_columns(only_undated)] == ["YTD", "FY", "LTM"]

    latest_undated = replace(dated, periods=(fy24, replace(fy25, end_date=None), h1))
    columns = historical_columns(latest_undated)
    assert [c.column_id for c in columns] == [
        "YTD:H1_2026",
        "FY:FY2025",
        "FY:FY2024",
        "LTM:H1_2026",
    ]


def test_a_register_ltm_ending_elsewhere_is_not_the_columns() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ytd={"H1_2025": {"revenue": 190}, "H1_2026": {"revenue": 210}},
        ltm={"LTM_Q1_2026": {"revenue": 999}},
    )

    columns = historical_columns(regs)
    ltm = account_frame(regs, columns)["LTM:H1_2026"]["acct:revenue"]

    assert columns[-1].column_id == "LTM:H1_2026"
    assert (ltm.value, ltm.stated, ltm.note) == (Decimal(420), None, None)


def test_constructed_ltm_supplies_its_days_but_retains_source_period_rates() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ytd={"H1_2025": {"revenue": 190}, "H1_2026": {"revenue": 210}},
        ltm={"LTM_Q2_2026": {"revenue": 420}},
    )
    fy, pytd, ytd, ltm = regs.periods
    regs = replace(
        regs,
        periods=(fy, pytd, ytd, replace(ltm, day_count=364)),
        kpis=(_kpi("occupancy", "RATE", "LTM_Q2_2026", "90.5"),),
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    # Deploy VII: source metadata cannot relabel a 365-day construction.
    assert columns[-1].days == 365
    assert frame["LTM:LTM_Q2_2026"]["kpi:occupancy"].value == Decimal("90.5")

    undated = replace(regs, periods=(fy, pytd, ytd, replace(ltm, day_count=None)))
    assert historical_columns(undated)[-1].days == 365


def test_derived_sums_are_exact_past_the_default_precision() -> None:
    big = Decimal("1234567890123456789012345678.91")
    regs = _regs(
        quarters={f"Q{n}_2025": {"revenue": big} for n in (1, 2, 3, 4)},
        fy={"FY2025": {}},
        components={"FY2025": tuple(f"Q{n}_2025" for n in (1, 2, 3, 4))},
    )

    columns = historical_columns(regs)

    # 30 significant digits: the default context's 28 would round them.
    exact = Decimal("4938271560493827156049382715.64")
    assert account_frame(regs, columns)["FY:FY2025"]["acct:revenue"].value == exact
    assert ltm_frames(regs, columns)["Q:Q4_2025"]["acct:revenue"].value == exact


def test_the_ltm_needs_the_fiscal_year_before_the_ytd() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        periods=tuple(p for p in regs.periods if p.period_id != "FY2025"),
        accounts=tuple(a for a in regs.accounts if a.period_id != "FY2025"),
    )

    frame = _frame(regs)

    # FY2024 + H1 2026 - H1 2025 would be eighteen months.
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(11654)
    )


def test_a_q1_only_year_builds_its_ytd_and_pytd_from_quarters() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}, "Q1_2026": {"revenue": 110}},
        fy={"FY2025": {"revenue": 420}},
        ltm={"LTM_Q1_2026": {"revenue": 430}},
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [(c.column_id, c.label, c.period_id, c.days) for c in columns] == [
        ("Q:Q1_2025", "Q1 25", "Q1_2025", 90),
        ("Q:Q1_2026", "Q1 26", "Q1_2026", 90),
        ("PYTD:Q1_2025", "PYTD Q1 25", None, 90),
        ("YTD:Q1_2026", "YTD Q1 26", None, 90),
        ("FY:FY2025", "FY25", "FY2025", 365),
        ("LTM:LTM_Q1_2026", "LTM Q1 26", "LTM_Q1_2026", 365),
    ]
    pytd_column, ytd_column = columns[2], columns[3]
    assert (ytd_column.kind, ytd_column.fiscal_year, ytd_column.end_date) == (
        "YTD",
        "2026",
        "2026-03-31",
    )
    assert (pytd_column.kind, pytd_column.fiscal_year, pytd_column.end_date) == (
        "PYTD",
        "2025",
        "2025-03-31",
    )
    ytd = frame["YTD:Q1_2026"]["acct:revenue"]
    assert (ytd.value, ytd.basis, ytd.stated) == (Decimal(110), "CALCULATED", None)
    assert frame["PYTD:Q1_2025"]["acct:revenue"].value == Decimal(100)
    ltm = frame["LTM:LTM_Q1_2026"]["acct:revenue"]
    assert (ltm.value, ltm.stated, ltm.note) == (Decimal(430), Decimal(430), None)


def test_a_ytd_from_quarters_needs_every_quarter_to_date() -> None:
    regs = _regs(
        quarters={"Q2_2026": {"revenue": 110}},
        fy={"FY2025": {"revenue": 420}},
    )

    columns = historical_columns(regs)

    assert [c.column_id for c in columns] == ["Q:Q2_2026", "FY:FY2025", "LTM:Q2_2026"]
    assert columns[-1].label == "LTM Q2 26"
    assert account_frame(regs, columns)["LTM:Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING"
    )


def test_a_register_ltm_later_than_the_host_can_build_is_kept_unadopted() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ytd={"H1_2025": {"revenue": 190}, "H1_2026": {"revenue": 210}},
        ltm={"LTM_Q3_2026": {"revenue": 500}},
    )
    regs = replace(regs, kpis=(_kpi("occupancy", "RATE", "LTM_Q3_2026", "90.5"),))

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [c.column_id for c in columns][-2:] == ["LTM:H1_2026", "LTM:LTM_Q3_2026"]
    later = columns[-1]
    assert (later.label, later.period_id, later.end_date) == (
        "LTM Q3 26",
        "LTM_Q3_2026",
        "2026-09-30",
    )
    assert (later.kind, later.fiscal_year, later.days) == ("LTM", "2026", 365)
    assert frame["LTM:LTM_Q3_2026"]["kpi:occupancy"].value == Decimal("90.5")
    assert frame["LTM:H1_2026"]["acct:revenue"].value == Decimal(420)
    assert frame["LTM:LTM_Q3_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(500)
    )


def test_a_stated_figure_in_hundreds_is_rounding_within_fifty() -> None:
    zero = {"revenue": 0, "cogs": 0}
    regs = _regs(
        fy={"FY2025": {"revenue": 1240, "cogs": -1260}},
        ytd={"H1_2025": zero, "H1_2026": zero},
        ltm={"LTM_Q2_2026": {"revenue": "1.2E+3", "cogs": "-1.2E+3"}},
    )

    ltm = _frame(regs)["LTM:LTM_Q2_2026"]

    assert ltm["acct:revenue"].note is None
    assert ltm["acct:cogs"].note == "differs from CP-1 stated"


def test_a_register_with_only_an_ltm_row_keeps_it_unadopted() -> None:
    regs = _regs(ltm={"LTM_Q2_2026": {"revenue": 5}})

    columns = historical_columns(regs)

    assert [c.column_id for c in columns] == ["LTM:LTM_Q2_2026"]
    assert account_frame(regs, columns)["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(5)
    )


def test_quarters_to_date_make_the_ytd_and_pytd_without_ytd_rows() -> None:
    values = {"Q1": 10, "Q2": 20, "Q3": 30, "Q4": 40}
    quarters = {f"{q}_2025": {"revenue": v} for q, v in values.items()}
    quarters |= {"Q1_2026": {"revenue": 11}, "Q2_2026": {"revenue": 21}}
    regs = _regs(quarters=quarters, fy={"FY2025": {"revenue": 100}})
    regs = replace(
        regs,
        periods=tuple(
            replace(p, day_count=None) if p.period_id == "Q1_2026" else p for p in regs.periods
        ),
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    by_id = {c.column_id: c for c in columns}
    assert (by_id["YTD:Q2_2026"].label, by_id["YTD:Q2_2026"].days) == (
        "YTD H1 26",
        None,
    )
    assert (by_id["PYTD:Q2_2025"].label, by_id["PYTD:Q2_2025"].days) == (
        "PYTD H1 25",
        181,
    )
    assert frame["YTD:Q2_2026"]["acct:revenue"].value == Decimal(32)
    assert frame["PYTD:Q2_2025"]["acct:revenue"].value == Decimal(30)
    assert frame["LTM:Q2_2026"]["acct:revenue"].value == Decimal(102)
    # Deploy VII: complete source dates establish days despite a missing count.
    assert by_id["LTM:Q2_2026"].days == 365


def test_an_undated_register_ltm_is_kept_unadopted() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ltm={"LTM_Q2_2026": {"revenue": 420}},
    )
    fy, ltm = regs.periods
    regs = replace(regs, periods=(fy, replace(ltm, end_date=None)))

    columns = historical_columns(regs)

    assert [c.column_id for c in columns] == [
        "FY:FY2025",
        "LTM:FY2025",
        "LTM:LTM_Q2_2026",
    ]
    assert account_frame(regs, columns)["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(420)
    )


def test_a_fiscal_year_reads_as_its_four_digit_year_however_written() -> None:
    regs = _regs(
        quarters={f"Q{n}_2025": {"revenue": n} for n in (1, 2, 3, 4)},
        fy={"FY2025": {"revenue": 10}},
        ytd={"H1_2025": {"revenue": 3}, "H1_2026": {"revenue": 5}},
    )
    written = {"FY2025": "FY2025", "H1_2025": "FY2025", "Q4_2025": "FY 2024/25"}
    regs = replace(
        regs,
        periods=tuple(
            replace(p, fiscal_year=written.get(p.period_id, p.fiscal_year)) for p in regs.periods
        ),
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [column.label for column in columns] == [
        "Q1 25",
        "Q2 25",
        "Q3 25",
        "Q4 25",
        "PYTD H1 25",
        "YTD H1 26",
        "FY25",
        "LTM Q2 26",
    ]
    assert frame["LTM:H1_2026"]["acct:revenue"].value == Decimal(12)
    assert ltm_frames(regs, columns)["Q:Q4_2025"]["acct:revenue"].value == Decimal(10)
