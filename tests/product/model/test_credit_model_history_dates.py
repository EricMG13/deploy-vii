"""Signs, dates and day counts: outflows written positive, malformed dates and
components that do not span their period."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from deploy_vii.model._cells import (
    SIGN_NORMALISED,
    UNSPANNED,
)
from deploy_vii.model.frame import Cell
from deploy_vii.model.history import (
    FLOW_METRICS,
    OUTFLOW_METRICS,
    account_frame,
    historical_columns,
    ltm_frames,
)
from deploy_vii.model.registers import (
    AccountRow,
    AddbackRow,
    PeriodRow,
)
from tests.product.model.credit_model_fixture import example_registers
from tests.product.model.history_cases import _regs, _relabelled
from tests.product.model.history_frames import (
    _costs,
    _extra_period,
    _frame,
    _periods_changed,
    _sparse_rows,
    _without_ltm_rows,
    _written_positive,
)


def test_outflow_metrics_are_cp1s_sign_agnostic_outflows() -> None:
    assert OUTFLOW_METRICS == {
        "cogs",
        "opex_including_da",
        "depreciation_amortization",
        "cash_interest_paid",
        "cash_lease_payments",
        "cash_taxes_paid",
        "capex_and_intangible_investment",
        "operating_lease_cost",
        "lease_payments_in_financing",
        "interest_paid_in_financing",
        "dividends_paid",
    }
    assert OUTFLOW_METRICS <= FLOW_METRICS
    assert SIGN_NORMALISED == "sign normalised"


def test_an_outflow_row_written_positive_is_negative_before_any_sum() -> None:
    regs = _without_ltm_rows(example_registers())
    flows = {
        "capex_and_intangible_investment",
        "cash_interest_paid",
        "lease_payments_in_financing",
    }
    hostile = _written_positive(regs, {"Q1_2026", "Q2_2026"}, flows)
    # Without CP-1's own H1 figure, the sparse lease line sums the quarters.
    hostile = replace(
        hostile,
        accounts=tuple(
            a
            for a in hostile.accounts
            if (a.metric_id, a.period_id) != ("lease_payments_in_financing", "H1_2026")
        ),
    )
    columns = historical_columns(hostile)
    frame = account_frame(hostile, columns)
    base = account_frame(regs, historical_columns(regs))
    for metric in flows:
        key = f"acct:{metric}"
        for column_id in ("Q:Q2_2026", "YTD:H1_2026", "LTM:LTM_Q2_2026"):
            cell = frame[column_id][key]
            assert cell.value == base[column_id][key].value, (metric, column_id)
            assert cell.note == SIGN_NORMALISED, (metric, column_id)
        assert frame["FY:FY2025"][key] == base["FY:FY2025"][key]
        assert frame["FY:FY2025"][key].note is None
    assert frame["LTM:LTM_Q2_2026"]["acct:cash_interest_paid"].value == -862
    assert frame["Q:Q2_2026"]["acct:cash_interest_paid"].basis == "REPORTED"
    # A non-outflow and a zero outflow are never flipped.
    assert frame["Q:Q2_2026"]["acct:revenue"].note is None
    assert frame["Q:Q2_2026"]["acct:dividends_paid"] == Cell(
        Decimal(0),
        basis="REPORTED",
        sources=frame["Q:Q2_2026"]["acct:dividends_paid"].sources,
    )
    twelve = ltm_frames(hostile, columns)["Q:Q2_2026"]["acct:cash_interest_paid"]
    assert (twelve.value, twelve.note) == (Decimal(-862), SIGN_NORMALISED)


def test_sixteen_nested_ltm_periods_resolve_a_sparse_item_in_under_a_second() -> None:
    # The audit's H1 probe: n LTM periods starting together, each a day
    # longer, and an add-back with no FY2025 row, took 2^n before memoising.
    regs = example_registers()
    extra = tuple(
        PeriodRow(
            period_id=f"X{i}",
            fiscal_year="2025",
            fiscal_quarter=None,
            period_type="LTM",
            start_date="2025-01-01",
            end_date=(date(2025, 1, 1) + timedelta(days=30 + i)).isoformat(),
            day_count=31 + i,
            currency="USD",
            unit="MILLIONS",
            component_period_ids=(),
        )
        for i in range(16)
    )
    regs = replace(
        regs,
        periods=regs.periods + extra,
        addbacks=tuple(
            b for b in regs.addbacks if (b.addback_id, b.period_id) != ("restructuring", "FY2025")
        ),
    )
    columns = historical_columns(regs)
    started = time.perf_counter()
    frame = account_frame(regs, columns)
    assert time.perf_counter() - started < 1
    assert frame["FY:FY2025"]["addback:restructuring"].value == 32


def _written(period: PeriodRow, field: str, written: str | int) -> PeriodRow:
    """`period` with a day count, or a start or end date, as written."""
    if isinstance(written, int):
        return replace(period, day_count=written)
    if field == "start_date":
        return replace(period, start_date=written)
    return replace(period, end_date=written)


@pytest.mark.parametrize(
    ("period_id", "field", "written"),
    [
        ("FY2025", "end_date", "31/12/2025"),
        ("FY2025", "end_date", "2025-12-31T00:00:00"),
        ("Q1_2026", "end_date", "20260331"),
        ("FY2025", "end_date", "9999-12-31"),
        ("FY2025", "start_date", "0001-01-01"),
        ("H1_2026", "start_date", "2026-02-30"),
        ("Q2_2026", "day_count", 800000),
        ("Q2_2026", "day_count", -90),
        ("Q2_2026", "day_count", 0),
        ("LTM_Q2_2026", "end_date", "30 June 2026"),
    ],
)
def test_a_date_or_day_count_that_is_not_one_never_raises(
    period_id: str, field: str, written: str | int
) -> None:
    # The audit's H2 probes, built directly (the parser refuses them).
    regs = example_registers()
    regs = replace(
        regs,
        periods=tuple(
            _written(p, field, written) if p.period_id == period_id else p for p in regs.periods
        ),
    )
    columns = historical_columns(regs)
    frame = account_frame(regs, columns)
    assert set(frame) == {column.column_id for column in columns}
    assert set(ltm_frames(regs, columns)) <= set(frame)
    # An end date that is not `YYYY-MM-DD` is no date: never the latest.
    if written != "9999-12-31":
        assert any(c.kind == "LTM" and c.end_date == "2026-06-30" for c in columns)


_SPLIT_H1 = "components do not span the period"


@pytest.mark.parametrize(
    "components",
    [
        ("Q1_2026", "Q1_2026", "Q2_2026"),
        ("Q2_2025", "Q2_2026"),
        ("FY2025",),
        ("Q2_2026", "Q1_2026", "GHOST"),
        ("Q2_2026",),
        (),
    ],
)
def test_a_derived_period_whose_components_do_not_span_it_is_missing(
    components: tuple[str, ...],
) -> None:
    # The audit's H3 probes: duplicate, foreign-year and 12-month components
    # once summed into the YTD and the LTM silently.
    regs = _without_ltm_rows(example_registers())
    regs = replace(regs, accounts=tuple(a for a in regs.accounts if a.period_id != "H1_2026"))
    changed = replace(
        regs,
        periods=tuple(
            replace(p, component_period_ids=components) if p.period_id == "H1_2026" else p
            for p in regs.periods
        ),
    )
    frame = account_frame(changed, historical_columns(changed))
    if not components:  # no components: CP-1's own row, here none
        assert frame["YTD:H1_2026"]["acct:revenue"] == Cell(None, "NOT_SOURCED")
        return
    for column_id in ("YTD:H1_2026", "LTM:LTM_Q2_2026"):
        assert frame[column_id]["acct:revenue"] == Cell(
            None, "COMPONENT_MISSING", note=UNSPANNED
        ), column_id
    assert UNSPANNED == _SPLIT_H1
    # Balances are read at the end date, not summed.
    assert frame["LTM:LTM_Q2_2026"]["acct:total_debt"].value == 13846


def test_components_in_any_order_that_span_the_period_are_summed() -> None:
    regs = _without_ltm_rows(example_registers())
    swapped = replace(
        regs,
        periods=tuple(
            replace(p, component_period_ids=("Q2_2026", "Q1_2026"))
            if p.period_id == "H1_2026"
            else p
            for p in regs.periods
        ),
    )
    frame = account_frame(swapped, historical_columns(swapped))
    assert frame["YTD:H1_2026"]["acct:revenue"].value == 5885
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"].value == 11654


def test_two_year_fiscal_spellings_read_as_the_end_year_throughout() -> None:
    # The audit's H3 probe: quarters "FY2025/26" and years "FY2025/2026"
    # once read as 2025 and 2026, so the LTM took the wrong fiscal year.
    regs = _without_ltm_rows(example_registers())
    spelt = {"2024": "FY2023/24", "2025": "FY2024/25", "2026": "FY2025/26"}
    years = {
        p.period_id: spelt[p.fiscal_year]
        for p in regs.periods
        if p.period_type != "FY" and p.fiscal_year in spelt
    }
    years |= {"FY2023": "FY2022/2023", "FY2024": "FY2023/2024", "FY2025": "FY2024/2025"}
    changed = _relabelled(regs, years)
    columns = historical_columns(changed)
    frame = account_frame(changed, columns)
    base = account_frame(regs, historical_columns(regs))
    assert [c.label for c in columns] == [c.label for c in historical_columns(regs)]
    for key in ("acct:revenue", "acct:cash_interest_paid", "acct:adjusted_ebitda"):
        assert frame["LTM:LTM_Q2_2026"][key].value == (base["LTM:LTM_Q2_2026"][key].value)


def test_an_ltm_whose_fiscal_year_does_not_meet_its_ytd_is_missing() -> None:
    regs = _without_ltm_rows(example_registers())
    # FY2024 labelled 2025 and FY2025 labelled 2024: the LTM's "prior" year
    # ends a year before the YTD starts.
    swapped = _relabelled(regs, {"FY2024": "2025", "FY2025": "2024"})
    frame = account_frame(swapped, historical_columns(swapped))
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )
    assert frame["LTM:LTM_Q2_2026"]["acct:total_debt"].value == 13846
    # A PYTD that does not start with the fiscal year.
    late = replace(
        regs,
        periods=tuple(
            replace(
                p,
                start_date="2025-01-02",
                day_count=180,
                component_period_ids=(),
            )
            if p.period_id == "H1_2025"
            else p
            for p in regs.periods
        ),
    )
    late_frame = account_frame(late, historical_columns(late))
    assert late_frame["PYTD:H1_2025"]["acct:revenue"].value == 5750
    assert late_frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )
    # An undated fiscal year cannot be shown to meet it either.
    undated = replace(
        regs,
        periods=tuple(
            replace(p, start_date=None, day_count=None) if p.period_id == "FY2025" else p
            for p in regs.periods
        ),
    )
    undated_frame = account_frame(undated, historical_columns(undated))
    assert undated_frame["LTM:LTM_Q2_2026"]["acct:revenue"].reason == ("COMPONENT_MISSING")
    # Nor does an undated PYTD start "with" an undated year.
    both = replace(
        undated,
        periods=tuple(
            replace(p, start_date=None, day_count=None, component_period_ids=())
            if p.period_id == "H1_2025"
            else p
            for p in undated.periods
        ),
    )
    both_frame = account_frame(both, historical_columns(both))
    assert both_frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )


def test_a_sparse_period_takes_an_equal_twins_own_row_and_nothing_more() -> None:
    regs = example_registers()
    twin = PeriodRow(
        period_id="LTM_Q4_2025",
        fiscal_year="2025",
        fiscal_quarter="4",
        period_type="LTM",
        start_date="2025-01-01",
        end_date="2025-12-31",
        day_count=365,
        currency="USD",
        unit="MILLIONS",
        component_period_ids=(),
    )
    model = next(b for b in regs.addbacks if b.addback_id == "transaction_costs")
    regs = replace(
        regs,
        periods=(*regs.periods, twin),
        addbacks=(
            *(b for b in regs.addbacks if b.addback_id != "transaction_costs"),
            replace(model, period_id="LTM_Q4_2025", value=Decimal(40)),
            AddbackRow(
                "transaction_costs",
                model.label,
                model.classification,
                model.realization_status,
                model.display_priority,
                "Q1_2025",
                Decimal(3),
                None,
            ),
        ),
    )
    costs = _costs(regs)
    # FY2025 has no row: its twin's own row covers it, not the twin's parts.
    assert costs["FY:FY2025"].value == 40
    frame = account_frame(regs, historical_columns(regs))
    assert frame["FY:FY2025"]["addback:transaction_costs"].value == 40


def test_every_register_row_keeps_its_source() -> None:
    regs = example_registers()
    cells = account_frame(regs, historical_columns(regs))["Q:Q2_2026"]
    rows = {
        "bu:las_vegas": next(
            s for s in regs.segments if (s.segment_id, s.period_id) == ("las_vegas", "Q2_2026")
        ).source,
        "addback:restructuring": next(
            b for b in regs.addbacks if (b.addback_id, b.period_id) == ("restructuring", "Q2_2026")
        ).source,
        "kpi:lv_room_nights": next(
            k for k in regs.kpis if (k.kpi_id, k.period_id) == ("lv_room_nights", "Q2_2026")
        ).source,
    }
    for key, source in rows.items():
        assert source is not None
        assert cells[key].sources == (source,), key


def test_a_sparse_own_row_written_positive_keeps_its_note() -> None:
    regs = _written_positive(example_registers(), {"H1_2026"}, {"lease_payments_in_financing"})
    cell = account_frame(regs, historical_columns(regs))["YTD:H1_2026"][
        "acct:lease_payments_in_financing"
    ]
    assert (cell.value, cell.note) == (Decimal(-8), SIGN_NORMALISED)


def test_a_one_day_component_spans_its_day() -> None:
    regs = _regs(fy={"FY2025": {"revenue": 10}})
    regs = replace(
        regs,
        periods=(
            *(replace(p, component_period_ids=("A", "B")) for p in regs.periods),
            _extra_period("A", "2025-01-01", "2025-12-30"),
            _extra_period("B", "2025-12-31", "2025-12-31"),
        ),
        accounts=(
            *regs.accounts,
            AccountRow("revenue", "A", Decimal(7), "VERIFIED", None),
            AccountRow("revenue", "B", Decimal(3), "VERIFIED", None),
        ),
    )
    cell = _frame(regs)["FY:FY2025"]["acct:revenue"]
    assert (cell.value, cell.stated, cell.note) == (Decimal(10), Decimal(10), None)


def test_a_cover_part_resolves_through_its_components_but_a_twin_does_not() -> None:
    regs = _sparse_rows(example_registers(), {"Q1_2025": 3, "M2": 4, "H2X": 9})
    periods = {p.period_id: p for p in regs.periods}
    # H1 2025 names Q1 and M2, a period no cover is chosen from: resolving
    # H1 reaches M2's figure; taking only H1's own row (none) would not.
    halves = _periods_changed(
        regs, replace(periods["H1_2025"], component_period_ids=("Q1_2025", "M2"))
    )
    halves = replace(
        halves,
        periods=(*halves.periods, _extra_period("M2", "2025-04-01", "2025-06-30")),
    )
    assert _costs(halves)["FY:FY2025"].value == 7
    # FY2025's twin, with the same dates and no row of its own, gives
    # nothing: its components (H1 and H2X) are not read through it.
    twin = replace(
        _extra_period("TWIN", "2025-01-01", "2025-12-31", ("H1_2025", "H2X")),
        period_type="LTM",
    )
    twinned = replace(
        halves,
        periods=(
            *halves.periods,
            twin,
            _extra_period("H2X", "2025-07-01", "2025-12-31"),
        ),
    )
    assert _costs(twinned)["FY:FY2025"].value == 7
    # A longer part whose parts have no row (none of them a quarter's dates)
    # gives way to a shorter one.
    hollow = _periods_changed(
        _sparse_rows(example_registers(), {"Q1_2025": 3}),
        replace(periods["H1_2025"], component_period_ids=("A1", "A2")),
    )
    hollow = replace(
        hollow,
        periods=(
            *hollow.periods,
            _extra_period("A1", "2025-01-01", "2025-02-28"),
            _extra_period("A2", "2025-03-01", "2025-06-30"),
        ),
    )
    assert _costs(hollow)["PYTD:H1_2025"] == Cell(None, "NOT_SOURCED")
    assert _costs(hollow)["FY:FY2025"].value == 3


def test_an_unbuilt_ltm_keeps_cp1s_figure_as_stated() -> None:
    regs = _relabelled(example_registers(), {"FY2024": "2025", "FY2025": "2024"})
    frame = account_frame(regs, historical_columns(regs))
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(11654), note=UNSPANNED
    )


def test_quarters_to_date_meet_the_year_by_their_days_without_a_start() -> None:
    values = {"Q1": 10, "Q2": 20, "Q3": 30, "Q4": 40}
    quarters = {f"{q}_2025": {"revenue": v} for q, v in values.items()}
    quarters |= {"Q1_2026": {"revenue": 11}, "Q2_2026": {"revenue": 21}}
    regs = _regs(quarters=quarters, fy={"FY2025": {"revenue": 100}})
    regs = replace(
        regs,
        periods=tuple(
            replace(p, start_date=None) if p.period_id == "Q1_2026" else p for p in regs.periods
        ),
    )
    frame = _frame(regs)
    assert frame["LTM:Q2_2026"]["acct:revenue"].value == 100 + 32 - 30


def test_a_period_without_a_start_date_starts_its_day_count_before_its_end() -> None:
    regs = example_registers()
    columns = historical_columns(regs)
    whole = account_frame(regs, columns)
    undated = replace(
        regs,
        periods=tuple(
            replace(p, start_date=None) if p.period_id in {"Q2_2026", "H1_2026", "FY2025"} else p
            for p in regs.periods
        ),
    )
    frame = account_frame(undated, historical_columns(undated))

    for column in ("YTD:H1_2026", "LTM:LTM_Q2_2026", "FY:FY2025"):
        assert frame[column]["acct:revenue"] == whole[column]["acct:revenue"]
    assert frame["YTD:H1_2026"]["acct:revenue"].reason is None
    # Sparse items cover a period from its derived start too.
    sparse = _sparse_rows(undated, {"Q1_2025": 3, "Q3_2025": 12, "Q4_2025": 5})
    assert _costs(sparse)["FY:FY2025"].value == 20


def test_a_ytd_built_from_quarters_with_a_gap_does_not_meet_the_year() -> None:
    regs = example_registers()
    built = replace(regs, periods=tuple(p for p in regs.periods if p.period_id != "H1_2026"))
    whole = account_frame(built, historical_columns(built))
    assert whole["LTM:LTM_Q2_2026"]["acct:revenue"].value is not None
    gap = replace(
        built,
        periods=tuple(
            replace(p, start_date="2026-04-02", day_count=90) if p.period_id == "Q2_2026" else p
            for p in built.periods
        ),
    )
    frame = account_frame(gap, historical_columns(gap))
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(11654), note=UNSPANNED
    )
