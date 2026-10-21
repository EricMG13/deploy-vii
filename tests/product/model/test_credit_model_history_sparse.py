"""Sparse items: a figure resolved from the periods that tile it, bottom up."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal, localcontext

from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.model import history
from deploy_vii.model._cells import (
    CONTEXT,
    UNSPANNED,
)
from deploy_vii.model.frame import Cell
from deploy_vii.model.history import (
    account_frame,
    historical_columns,
    ltm_frames,
)
from deploy_vii.model.registers import (
    Cp1Registers,
    PeriodRow,
)
from tests.product.model.credit_model_fixture import example_registers
from tests.product.model.history_cases import _period
from tests.product.model.history_frames import _costs, _extra_period, _periods_changed, _sparse_rows


def _rows_changed(
    regs: Cp1Registers, metric_id: str, period_ids: set[str], *, drop: bool
) -> Cp1Registers:
    """`regs` with the metric's rows for `period_ids` dropped, or nulled."""
    kept = []
    for a in regs.accounts:
        if a.metric_id != metric_id or a.period_id not in period_ids:
            kept.append(a)
        elif not drop:
            kept.append(replace(a, value=None))
    return replace(regs, accounts=tuple(kept))


def test_an_absent_row_is_not_sourced_and_a_null_row_not_stated_or_missing() -> None:
    regs = example_registers()
    columns = historical_columns(regs)

    def cell(changed: Cp1Registers, column_id: str, key: str) -> Cell:
        return account_frame(changed, columns)[column_id][key]

    q2 = {"Q2_2026"}
    dropped = _rows_changed(regs, "revenue", q2, drop=True)
    nulled = _rows_changed(regs, "revenue", q2, drop=False)
    assert cell(dropped, "Q:Q2_2026", "acct:revenue") == Cell(None, "NOT_SOURCED")
    assert cell(nulled, "Q:Q2_2026", "acct:revenue") == Cell(None, "NOT_STATED")
    # A flow with some components absent cannot be summed; with all absent it
    # is not sourced, CP-1's own figure kept.
    assert cell(dropped, "YTD:H1_2026", "acct:revenue").reason == "COMPONENT_MISSING"
    halves = _rows_changed(regs, "revenue", {"Q1_2026", "Q2_2026"}, drop=True)
    assert cell(halves, "YTD:H1_2026", "acct:revenue") == Cell(
        None, "NOT_SOURCED", stated=Decimal(5885)
    )
    assert cell(nulled, "YTD:H1_2026", "acct:revenue") == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(5885)
    )
    # A balance: the first figure at the date; a null row there is missing.
    ending = {"Q2_2026", "H1_2026", "LTM_Q2_2026"}
    cash = "acct:cash_and_equivalents"
    one_null = _rows_changed(regs, "cash_and_equivalents", q2, drop=False)
    assert cell(one_null, "Q:Q2_2026", cash).value == 1000
    all_null = _rows_changed(regs, "cash_and_equivalents", ending, drop=False)
    assert cell(all_null, "Q:Q2_2026", cash) == Cell(None, "NOT_STATED")
    all_gone = _rows_changed(regs, "cash_and_equivalents", ending, drop=True)
    assert cell(all_gone, "Q:Q2_2026", cash) == Cell(None, "NOT_SOURCED")


def test_an_addback_without_a_row_for_a_period_counts_zero_in_a_sum() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        addbacks=tuple(
            b
            for b in regs.addbacks
            if (b.addback_id, b.period_id) != ("transaction_costs", "Q2_2026")
        ),
    )
    columns = historical_columns(regs)
    frame = account_frame(regs, columns)
    key = "addback:transaction_costs"
    assert frame["Q:Q2_2026"][key] == Cell(None, "NOT_SOURCED")
    # H1 2026's own row (6) stands; the LTM is built from it.
    assert frame["YTD:H1_2026"][key].value == 6
    assert frame["LTM:LTM_Q2_2026"][key].value == 21
    halves = replace(
        regs,
        addbacks=tuple(
            b
            for b in regs.addbacks
            if (b.addback_id, b.period_id) != ("transaction_costs", "H1_2026")
        ),
    )
    resolved = account_frame(halves, historical_columns(halves))
    assert resolved["YTD:H1_2026"][key].value == 3
    assert resolved["LTM:LTM_Q2_2026"][key].value == 21 - 3
    assert ltm_frames(regs, columns)["Q:Q2_2026"][key].value == 12 + 3 + 3
    assert ltm_frames(regs, columns)["Q:Q2_2026"]["acct:revenue"].value == 11654


def test_a_sparse_item_resolves_each_period_bottom_up() -> None:
    regs = example_registers()
    # (a) rows only for Q1 2025 and H1 2025: FY2025 is its quarters (3); the
    # PYTD is stated and the YTD has no row, so the LTM is never 3 + 0 - 3.
    probe = _costs(_sparse_rows(regs, {"Q1_2025": 3, "H1_2025": 3}))
    assert probe["FY:FY2025"] == Cell(
        Decimal(3), basis="CALCULATED", sources=probe["Q:Q1_2025"].sources
    )
    assert probe["LTM:LTM_Q2_2026"] == Cell(None, "COMPONENT_MISSING", note=history.PARTLY_STATED)
    assert probe["YTD:H1_2026"] == Cell(None, "NOT_SOURCED")
    assert probe["Q:Q2_2025"] == Cell(None, "NOT_SOURCED")
    # (b) only Q3 2025 and FY2025: the LTM keeps the 12, the YTD has none.
    third = _costs(_sparse_rows(regs, {"Q3_2025": 12, "FY2025": 12}))
    assert third["LTM:LTM_Q2_2026"].value == 12
    assert third["YTD:H1_2026"] == Cell(None, "NOT_SOURCED")
    assert third["PYTD:H1_2025"] == Cell(None, "NOT_SOURCED")
    # (c) only at the fiscal year: the FY's own figure, then the LTM from it.
    annual = _costs(_sparse_rows(regs, {"FY2025": 21}))
    assert annual["FY:FY2025"].value == 21
    assert annual["FY:FY2025"].basis == "REPORTED"
    assert annual["LTM:LTM_Q2_2026"].value == 21
    assert annual["FY:FY2024"] == Cell(None, "NOT_SOURCED")
    quarters = _costs(_sparse_rows(regs, {"Q1_2025": 3, "Q3_2025": 12, "Q4_2025": 5}))
    assert quarters["FY:FY2025"].value == 20
    assert quarters["Q:Q2_2025"] == Cell(None, "NOT_SOURCED")


def test_a_sparse_item_with_a_null_row_it_uses_is_component_missing() -> None:
    regs = _sparse_rows(example_registers(), {"Q1_2025": 3, "Q3_2025": 12})
    regs = replace(
        regs,
        addbacks=tuple(
            replace(b, value=None)
            if (b.addback_id, b.period_id) == ("transaction_costs", "Q3_2025")
            else b
            for b in regs.addbacks
        ),
    )
    costs = _costs(regs)
    assert costs["Q:Q3_2025"] == Cell(None, "NOT_STATED")
    assert costs["FY:FY2025"].reason == "COMPONENT_MISSING"
    assert costs["LTM:LTM_Q2_2026"].reason == "COMPONENT_MISSING"
    assert costs["PYTD:H1_2025"].value == 3


def test_financing_lines_are_sparse() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if a.metric_id != "lease_payments_in_financing"
            or a.period_id not in {"Q2_2026", "H1_2026"}
        ),
    )
    frame = account_frame(regs, historical_columns(regs))
    assert frame["YTD:H1_2026"]["acct:lease_payments_in_financing"].value == -4
    assert frame["Q:Q2_2026"]["acct:lease_payments_in_financing"] == Cell(None, "NOT_SOURCED")


def test_a_sparse_period_resolves_only_through_dated_existing_parts() -> None:
    regs = _sparse_rows(example_registers(), {"Q1_2025": 3, "Q3_2025": 12, "Q4_2025": 5})
    periods = {p.period_id: p for p in regs.periods}
    # A quarter without a start date (nor a day count to derive one) is not
    # within the year: its days are a gap, so Q1 + Q4 is not the year.
    undated = _periods_changed(regs, replace(periods["Q3_2025"], start_date=None, day_count=None))
    assert _costs(undated)["FY:FY2025"] == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    # A year without dates has no quarters; a quarter is never its own part.
    no_end = _periods_changed(regs, replace(periods["FY2025"], end_date=None))
    assert _costs(no_end)["FY:FY2025"] == Cell(None, "NOT_SOURCED")
    no_start = _periods_changed(regs, replace(periods["FY2025"], start_date=None, day_count=None))
    assert _costs(no_start)["FY:FY2025"] == Cell(None, "NOT_SOURCED")
    assert _costs(regs)["Q:Q1_2025"].value == 3
    # Components that are not all periods do not span it; one naming itself
    # ends.
    ghost = _periods_changed(
        _sparse_rows(regs, {"Q1_2025": 3, "Q2_2025": 4}),
        replace(periods["H1_2025"], component_period_ids=("Q1_2025", "Q2_2025", "GHOST")),
    )
    assert _costs(ghost)["PYTD:H1_2025"] == Cell(
        None, "COMPONENT_MISSING", note="components do not span the period"
    )
    cycle = _periods_changed(regs, replace(periods["H1_2025"], component_period_ids=("H1_2025",)))
    assert _costs(cycle)["PYTD:H1_2025"] == Cell(None, "NOT_SOURCED")


def test_a_flow_that_is_not_sparse_never_resolves_from_its_parts() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            a for a in regs.accounts if (a.metric_id, a.period_id) != ("revenue", "FY2025")
        ),
    )
    frame = account_frame(regs, historical_columns(regs))
    assert frame["FY:FY2025"]["acct:revenue"] == Cell(None, "NOT_SOURCED")


def test_a_sparse_period_is_covered_greedily_by_its_longest_parts() -> None:
    regs = example_registers()
    # (a) H1 2025 and Q3 2025 only: FY2025 is H1 + Q3 + nothing for Q4; the
    # YTD has no row beside a stated PYTD, so the LTM is not built.
    probe = _costs(_sparse_rows(regs, {"H1_2025": 6, "Q3_2025": 12}))
    assert probe["FY:FY2025"].value == 18
    assert probe["PYTD:H1_2025"].value == 6
    assert probe["LTM:LTM_Q2_2026"].note == history.PARTLY_STATED
    # (b) a 9M row and Q4: FY = 9M + Q4.
    h1 = next(p for p in regs.periods if p.period_id == "H1_2025")
    nine = replace(
        h1,
        period_id="9M_2025",
        fiscal_quarter="3",
        end_date="2025-09-30",
        day_count=273,
        component_period_ids=(),
    )
    with_nine = replace(regs, periods=(*regs.periods, nine))
    nine_q4 = _costs(_sparse_rows(with_nine, {"9M_2025": 20, "Q4_2025": 5}))
    assert nine_q4["FY:FY2025"].value == 25
    # The longest part with a figure comes first: H1 (6) rather than Q1 (3).
    longest = _costs(_sparse_rows(regs, {"Q1_2025": 3, "H1_2025": 6}))
    assert longest["FY:FY2025"].value == 6
    # A longer period without a figure gives way to a shorter one that has one.
    ghost = replace(h1, component_period_ids=("GHOST",))
    hollow = _periods_changed(_sparse_rows(regs, {"Q1_2025": 3}), ghost)
    assert _costs(hollow)["PYTD:H1_2025"] == Cell(
        None, "COMPONENT_MISSING", note="components do not span the period"
    )
    assert _costs(hollow)["FY:FY2025"].value == 3
    # A period starting on the day the last part taken ends overlaps it.
    overlap = replace(
        h1,
        period_id="STUB_2025",
        fiscal_quarter=None,
        start_date="2025-06-30",
        day_count=1,
        component_period_ids=(),
    )
    stub = replace(regs, periods=(*regs.periods, overlap))
    covered = _costs(_sparse_rows(stub, {"H1_2025": 6, "STUB_2025": 100}))
    assert covered["FY:FY2025"].value == 6
    # (c) round 2's probe: rows for Q1 2025 and H1 2025 only; a stated PYTD
    # beside no YTD row, so the LTM is not built.
    first = _costs(_sparse_rows(regs, {"Q1_2025": 3, "H1_2025": 3}))
    assert first["FY:FY2025"].value == 3
    assert first["LTM:LTM_Q2_2026"].note == history.PARTLY_STATED


def test_a_sparse_own_row_wins_and_is_noted_where_its_parts_differ() -> None:
    regs = example_registers()
    agreed = _costs(regs)
    assert agreed["FY:FY2025"] == replace(agreed["FY:FY2025"], note=None)
    assert agreed["FY:FY2025"].value == 21
    restated = replace(
        regs,
        addbacks=tuple(
            replace(b, value=Decimal(30))
            if (b.addback_id, b.period_id) == ("transaction_costs", "FY2025")
            else b
            for b in regs.addbacks
        ),
    )
    costs = _costs(restated)
    assert costs["FY:FY2025"].value == 30
    assert costs["FY:FY2025"].basis == "REPORTED"
    assert costs["FY:FY2025"].note == "differs from components"
    assert costs["Q:Q4_2025"].note is None
    only_fy = _costs(_sparse_rows(regs, {"FY2025": 21}))
    assert only_fy["FY:FY2025"].note is None


def _without_periods(regs: Cp1Registers, *period_ids: str) -> Cp1Registers:
    """`regs` without those periods in its period register."""
    return replace(regs, periods=tuple(p for p in regs.periods if p.period_id not in period_ids))


def _h1_2026_alone(rows: dict[str, int]) -> Cp1Registers:
    """Run 9b9e2b72's shape: H1 2026 names no components and no Q1 2026
    period exists, so no period covers January to March 2026."""
    regs = _sparse_rows(example_registers(), rows)
    h1 = next(p for p in regs.periods if p.period_id == "H1_2026")
    regs = _periods_changed(regs, replace(h1, component_period_ids=()))
    return _without_periods(regs, "Q1_2026")


def test_a_sparse_own_row_over_a_gap_is_never_compared_with_a_partial_cover() -> None:
    # Live run 9b9e2b72: stock comp H1 2026 YTD 47, Q2 2026 23, no Q1 2026
    # period. Q2 alone does not cover H1, so 47 is not "differs from" 23.
    h1 = _costs(_h1_2026_alone({"H1_2026": 47, "Q2_2026": 23}))["YTD:H1_2026"]
    assert (h1.value, h1.basis, h1.note) == (Decimal(47), "REPORTED", None)
    # A registered Q1 without a row is nothing, not a gap: Q1 + Q2 tile H1,
    # so the same rows disagree.
    tiled = _sparse_rows(example_registers(), {"H1_2026": 47, "Q2_2026": 23})
    h1_2026 = next(p for p in tiled.periods if p.period_id == "H1_2026")
    tiled = _periods_changed(tiled, replace(h1_2026, component_period_ids=()))
    noted = _costs(tiled)["YTD:H1_2026"]
    assert (noted.value, noted.note) == (Decimal(47), "differs from components")


def test_a_sparse_year_with_its_own_row_and_only_h1_below_keeps_its_row() -> None:
    # Live run 9b9e2b72: stock comp FY2025 95, H1 2025 50, no Q3 or Q4 2025.
    regs = _sparse_rows(example_registers(), {"FY2025": 95, "H1_2025": 50})
    fy = _costs(_without_periods(regs, "Q3_2025", "Q4_2025"))["FY:FY2025"]
    assert (fy.value, fy.basis, fy.note) == (Decimal(95), "REPORTED", None)


def test_a_sparse_period_without_a_row_over_a_gap_is_component_missing() -> None:
    regs = _sparse_rows(example_registers(), {"H1_2025": 50})
    gap = _without_periods(regs, "Q3_2025", "Q4_2025")
    # H1's 50 is not FY2025's figure: July to December has no period.
    assert _costs(gap)["FY:FY2025"] == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    # Nor is Q2 2026's 23 H1 2026's.
    assert _costs(_h1_2026_alone({"Q2_2026": 23}))["YTD:H1_2026"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )
    # A gap with no row on either side: nothing was sourced.
    empty = _without_periods(_sparse_rows(example_registers(), {"FY2024": 9}), "Q3_2025", "Q4_2025")
    assert _costs(empty)["FY:FY2025"] == Cell(None, "NOT_SOURCED")


def test_a_complete_tiling_still_resolves_from_parts_and_notes_a_disagreement() -> None:
    regs = example_registers()
    quarters = {"Q1_2025": 3, "Q2_2025": 4, "Q3_2025": 12, "Q4_2025": 5}
    by_quarters = _costs(_sparse_rows(regs, quarters))["FY:FY2025"]
    assert (by_quarters.value, by_quarters.basis) == (Decimal(24), "CALCULATED")
    halves = {"H1_2025": 7, "Q3_2025": 12, "Q4_2025": 5}
    by_halves = _costs(_sparse_rows(regs, halves))["FY:FY2025"]
    assert (by_halves.value, by_halves.basis) == (Decimal(24), "CALCULATED")
    stated = _costs(_sparse_rows(regs, {**halves, "FY2025": 30}))["FY:FY2025"]
    assert (stated.value, stated.note) == (Decimal(30), "differs from components")
    agreed = _costs(_sparse_rows(regs, {**halves, "FY2025": 24}))["FY:FY2025"]
    assert (agreed.value, agreed.note) == (Decimal(24), None)


# One fiscal year's periods and the quarters (1 to 4) each runs over.
_SPANS = {
    "Q1_2025": (1, 1),
    "Q2_2025": (2, 2),
    "Q3_2025": (3, 3),
    "Q4_2025": (4, 4),
    "H1_2025": (1, 2),
    "9M_2025": (1, 3),
    "FY2025": (1, 4),
}


def _tiled(period_id: str, registered: set[str]) -> bool:
    """Whether other registered periods lie end to end over the period."""
    first, last = _SPANS[period_id]
    reached = {first}
    for quarter in range(first, last + 1):
        if quarter in reached:
            reached |= {
                _SPANS[other][1] + 1
                for other in registered - {period_id}
                if _SPANS[other][0] == quarter and _SPANS[other][1] <= last
            }
    return last + 1 in reached


@settings(deadline=None, max_examples=300)
@given(
    st.sets(st.sampled_from(sorted(_SPANS)), min_size=1),
    st.lists(st.integers(min_value=-40, max_value=40), min_size=4, max_size=4),
    st.sets(st.sampled_from(sorted(_SPANS))),
    st.sets(st.sampled_from(sorted(_SPANS))),
)
def test_a_sparse_figure_from_parts_comes_only_from_parts_that_tile_it(
    registered: set[str], amounts: list[int], zero_rows: set[str], dropped: set[str]
) -> None:
    # The item's true amount per quarter; every registered period with a
    # nonzero amount has its row (so a registered period without one is
    # truly nothing), except a period inside no other, whose row may be
    # dropped so that it resolves from its parts.
    truth = {
        pid: sum(amounts[q - 1] for q in range(_SPANS[pid][0], _SPANS[pid][1] + 1))
        for pid in registered
    }

    def outermost(pid: str) -> bool:
        lo, hi = _SPANS[pid]
        return not any(_SPANS[o][0] <= lo and hi <= _SPANS[o][1] for o in registered - {pid})

    rows = {
        pid: value
        for pid, value in truth.items()
        if (value != 0 or pid in zero_rows) and not (pid in dropped and outermost(pid))
    }
    regs = _sparse_rows(example_registers(), rows)
    regs = replace(regs, periods=tuple(_period(pid, ()) for pid in sorted(registered)))
    resolved = _resolver(regs)
    for pid in sorted(registered):
        cell = resolved(pid)
        assert "differs from components" not in (cell.note or ""), (pid, cell)
        if pid in rows:
            assert cell.value == truth[pid], (pid, cell)
        elif cell.value is not None:
            assert _tiled(pid, registered), (pid, cell)
            assert cell.value == truth[pid], (pid, cell)


def _resolver(regs: Cp1Registers) -> Callable[[str], Cell]:
    """Transaction costs' resolved cell for a register period of `regs`."""
    empty = history._Series("sparse", {})
    series = history._series(regs).get("addback:transaction_costs", empty)
    register = history._register(regs)

    def resolved(period_id: str) -> Cell:
        with localcontext(CONTEXT):
            return history._resolved(series, register, period_id)

    return resolved


def _cover_case(rows: dict[str, int], *periods: PeriodRow) -> Callable[[str], Cell]:
    """Transaction costs in `rows` over FY2025 and `periods` only."""
    regs = _sparse_rows(example_registers(), rows)
    return _resolver(replace(regs, periods=(_period("FY2025", ()), *periods)))


def _covering(period_id: str, start: str, end: str, kind: str = "YTD") -> PeriodRow:
    return replace(_extra_period(period_id, start, end), period_type=kind)


def test_a_cover_reaches_the_last_day_of_the_period() -> None:
    most = _covering("MOST", "2025-01-01", "2025-12-30")
    last = _covering("LAST", "2025-12-31", "2025-12-31", "QUARTER")
    tiled = _cover_case({"MOST": 20, "LAST": 1}, most, last)("FY2025")
    assert (tiled.value, tiled.basis) == (Decimal(21), "CALCULATED")
    # Without a period for December 31 that day is a gap.
    assert _cover_case({"MOST": 20}, most)("FY2025") == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )


def test_parts_with_the_same_dates_are_taken_in_register_order() -> None:
    h1 = _period("H1_2025", ())
    copy = replace(h1, period_id="H1X")
    rows = {"H1_2025": 6, "H1X": 7, "Q3_2025": 1}
    third, fourth = _period("Q3_2025", ()), _period("Q4_2025", ())
    assert _cover_case(rows, copy, h1, third, fourth)("FY2025").value == 8
    assert _cover_case(rows, h1, copy, third, fourth)("FY2025").value == 7


def test_a_part_whose_components_do_not_span_it_leaves_its_days_unknown() -> None:
    broken = _period("H1_2025", ("GHOST",))
    rest = (_period("Q3_2025", ()), _period("Q4_2025", ()))
    alone = _cover_case({"FY2024": 1}, broken, *rest)("FY2025")
    assert alone == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    # A registered Q1 and Q2 without rows are nothing, and they tile H1's days.
    quarters = (_period("Q1_2025", ()), _period("Q2_2025", ()))
    tiled = _cover_case({"FY2024": 1}, broken, *quarters, *rest)("FY2025")
    assert tiled == Cell(None, "NOT_SOURCED")


def test_a_twin_without_a_row_is_never_nothing_over_the_period() -> None:
    twin = _covering("TWIN", "2025-01-01", "2025-12-31", "LTM")
    resolved = _cover_case({"Q2_2025": 5}, twin, _period("Q2_2025", ()))
    assert resolved("FY2025") == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
