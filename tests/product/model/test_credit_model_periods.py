"""The Model's columns: which periods become quarters, PYTD, YTD, FY and LTM
columns, and their labels and days."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from deploy_vii.model import periods
from deploy_vii.model.periods import historical_columns
from tests.product.model.credit_model_fixture import example_registers
from tests.product.model.history_cases import _regs, _relabelled


def test_columns_are_ordered_quarters_pytd_ytd_fy_ltm() -> None:
    columns = historical_columns(example_registers())

    assert [column.column_id for column in columns] == [
        *(f"Q:Q{n}_{year}" for year in (2024, 2025) for n in (1, 2, 3, 4)),
        "Q:Q1_2026",
        "Q:Q2_2026",
        "PYTD:H1_2025",
        "YTD:H1_2026",
        "FY:FY2023",
        "FY:FY2024",
        "FY:FY2025",
        "LTM:LTM_Q2_2026",
    ]
    assert [column.label for column in columns][-8:] == [
        "Q1 26",
        "Q2 26",
        "PYTD H1 25",
        "YTD H1 26",
        "FY23",
        "FY24",
        "FY25",
        "LTM Q2 26",
    ]
    assert [column.kind for column in columns][-8:] == [
        "QUARTER",
        "QUARTER",
        "PYTD",
        "YTD",
        "FY",
        "FY",
        "FY",
        "LTM",
    ]
    by_id = {column.column_id: column for column in columns}
    q3 = by_id["Q:Q3_2024"]
    assert (q3.period_id, q3.fiscal_year, q3.end_date, q3.days, q3.case) == (
        "Q3_2024",
        "2024",
        "2024-09-30",
        92,
        None,
    )
    ltm = by_id["LTM:LTM_Q2_2026"]
    assert (ltm.period_id, ltm.fiscal_year, ltm.end_date, ltm.days) == (
        "LTM_Q2_2026",
        "2026",
        "2026-06-30",
        365,
    )
    assert by_id["PYTD:H1_2025"].end_date == "2025-06-30"
    for column_id in ("PYTD:H1_2025", "YTD:H1_2026", "FY:FY2024"):
        column = by_id[column_id]
        assert column.column_id == f"{column.kind}:{column.period_id}"
        assert column.fiscal_year == column.column_id[-4:]
    assert by_id["FY:FY2024"].days == 366


def test_a_ytd_ending_on_the_fy_end_is_left_out() -> None:
    regs = _regs(fy={"FY2025": {"revenue": 12}}, ytd={"9M_2025": {"revenue": 9}})
    fy, nine = regs.periods
    twelve = replace(nine, period_id="12M_2025", fiscal_quarter="4", end_date=fy.end_date)
    regs = replace(regs, periods=(fy, twelve))

    assert [c.kind for c in historical_columns(regs)] == ["FY", "LTM"]


def test_a_ytd_without_a_fiscal_quarter_is_labelled_by_its_id() -> None:
    regs = _regs(fy={"FY2025": {"revenue": 12}}, ytd={"H1_2026": {"revenue": 6}})
    fy, h1 = regs.periods
    regs = replace(regs, periods=(fy, replace(h1, fiscal_quarter=None)))

    columns = historical_columns(regs)

    assert [c.label for c in columns] == ["YTD H1_2026", "FY25", "LTM H1_2026"]


def test_the_fixture_half_years_are_derived_periods() -> None:
    regs = example_registers()
    halves = {"H1_2025", "H1_2026"}

    assert all(p.component_period_ids for p in regs.periods if p.period_id in halves)
    rows = [a for a in regs.accounts if a.period_id in halves]
    assert rows
    assert {(a.source, a.calculation_status) for a in rows} == {(None, "CALCULATED")}


def test_an_anchor_quarter_without_a_fiscal_quarter_has_no_ytd() -> None:
    regs = _regs(quarters={"Q1_2026": {"revenue": 1}})
    regs = replace(regs, periods=(replace(regs.periods[0], fiscal_quarter=None),))

    columns = historical_columns(regs)

    assert [(c.column_id, c.label) for c in columns] == [
        ("Q:Q1_2026", "Q1_2026"),
        ("LTM:Q1_2026", "LTM Q1_2026"),
    ]


def test_a_label_takes_the_four_digit_year_however_the_text_ends() -> None:
    regs = _relabelled(example_registers(), {"FY2025": "FY2025 (restated)"})
    labels = {c.column_id: c.label for c in historical_columns(regs)}
    assert labels["FY:FY2025"] == "FY25"


def test_a_derived_start_is_a_calendar_day_no_later_than_the_end() -> None:
    q2 = next(p for p in example_registers().periods if p.period_id == "Q2_2026")
    end = date(2026, 6, 30)
    undated = replace(q2, start_date=None)

    def first(days: int | None, end_date: str | None = "2026-06-30") -> date | None:
        return periods._first_day(replace(undated, day_count=days, end_date=end_date))

    assert first(91) == date(2026, 4, 1)
    assert first(1) == end
    assert first(end.toordinal()) == date(1, 1, 1)
    assert first(end.toordinal() + 1) is None
    assert first(0) is None
    assert first(None) is None
    assert first(91, None) is None
    assert periods._first_day(q2) == date(2026, 4, 1)
