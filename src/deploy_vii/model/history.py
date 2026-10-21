"""CP-1's figures over the historical columns (spec M2); the columns
themselves are `periods`.

The LTM's FY must end the day before its YTD starts, and its PYTD start
with that FY; otherwise its flows are `COMPONENT_MISSING`, noted
`UNSPANNED`. A sparse item's interim without a row counts as nothing in that
LTM only when the other interim has none either (the LTM is then the FY's);
with some of its FY, YTD and PYTD stated and another without a row, its LTM
is `COMPONENT_MISSING`, noted `PARTLY_STATED`, never a sum over 18 or 6
months. (An FY without a row beside a stated PYTD inside it already resolves
`COMPONENT_MISSING`, noted `UNSPANNED`, by its cover.)

Every row of an outflow account in `OUTFLOW_METRICS` is read as minus its
absolute value before anything is summed, so CP-1 writing a quarter positive
and a year negative reads one way; a cell whose figure came from a row
written positive is noted `SIGN_NORMALISED`, and so is every sum of it.

A flow on a reported column is CP-1's figure. A derived column (a calculated
quarter, a YTD or PYTD built from quarters, the LTM, and a YTD or FY period
that names its component periods) adds and subtracts its components; CP-1's
own figure for that column is kept as `stated` and noted when it differs
beyond its rounding. A period's named components must be distinct periods,
each starting the day after the one before ends, from its start date to its
end date (a period without a start date starts its day count before its
end); otherwise its derived cells are `COMPONENT_MISSING`, noted
`UNSPANNED`. A period with no row is `NOT_SOURCED`, and one whose row
has no figure `NOT_STATED`. A sum with a component that has no figure, or
that is not a period, is `COMPONENT_MISSING`; with no row for any component
it is `NOT_SOURCED`; with rows for only some, `COMPONENT_MISSING`.

A sparse item (an add-back; a lease or interest payment classed in
financing) has rows only for the periods it occurred in, so it resolves
bottom-up: a period's figure is its own row (noted "differs from components"
where its parts disagree beyond its rounding: often an add-back is disclosed
only for a half or a year, so that row is the only figure), else the sum of
its components, or else of its cover: from its start date, the longest other
period starting then and ending within it that has a figure (a half or 9M
before its quarters), else the shortest such period without a row, which is
nothing, repeated from the day after the part taken ends; a part with the
period's own dates gives only its own row. A cover counts only where its
parts tile the period to its end date: a day on which no part starts is a
gap. Over a gap the period's own row stands un-noted, and a period without
a row is `COMPONENT_MISSING`, noted `UNSPANNED` (`NOT_SOURCED` where no part
has a row): a partial sum is never the period's figure. Every part without
a row is `NOT_SOURCED`, and a part with a null figure `COMPONENT_MISSING`.
Each period is resolved once per item, so the work is polynomial in the
periods. Columns then add and subtract these resolved figures (the LTM is
FY + YTD - PYTD of them).

For any other flow, a component that is itself a YTD or FY with components
is their recursively validated sum, at most four period levels deep.
A balance is the observation at the column's
end date: the column's own period first, then any period ending that day, in
register order. A RATE KPI, and an account in neither metric list, is shown
only on its own period.

`model_inputs.cp1_registers` refuses a register id written twice for one
period, two periods for one fiscal quarter, YTD or year, a fiscal year
without a four-digit year, a date that is not `YYYY-MM-DD`, more than 200
periods and components nested past four deep or in a cycle, so every key and
period here has one row and every fiscal period one period. Registers built
otherwise never raise here: a date that is not one is no date. Fiscal years
compare as that four-digit year (`FY2025` is `2025`, `FY2024/25` is
`2025`).

Pure: Decimal only, no I/O or display quantization. Arithmetic uses
the 38-significant-digit, half-even context defined in `_cells`.
"""

from __future__ import annotations

import operator
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from deploy_vii.model._cells import (
    ABSENT,
    CONTEXT,
    DIFFERS,
    SIGN_NORMALISED,
    UNSPANNED,
    beyond_rounding,
    calc,
    join_notes,
    no_negative_zero,
    refs,
)
from deploy_vii.model.frame import Arithmetic, Cell, Column, Frame, SourceRef
from deploy_vii.model.periods import (
    _ADDITIVE,
    LTM_DAYS,
    _dated,
    _first_day,
    _plan,
    _quarter_index,
    _Spec,
    _start,
)
from deploy_vii.model.periods import (
    historical_columns as historical_columns,
)
from deploy_vii.model.registers import AccountRow, Cp1Registers, PeriodRow, iso_date

FLOW_METRICS = frozenset(
    {
        "revenue",
        "cogs",
        "gross_profit",
        "opex_including_da",
        "ebit",
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
        "pretax_income",
        "net_income",
        "income_tax_expense",
        "operating_lease_cost",
        "lease_payments_in_financing",
        "interest_paid_in_financing",
    }
)
# The expense and outflow accounts, sign-agnostic in CP-1's register: each
# row is read as minus its absolute value (`statements.OUTFLOW_METRICS`).
OUTFLOW_METRICS = frozenset(
    {
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
)
BALANCE_METRICS = frozenset(
    {
        "cash_and_equivalents",
        "rcf_commitment",
        "rcf_drawn",
        "senior_secured_debt",
        "unsecured_debt",
        "total_debt",
        "net_accounts_receivable",
        "inventory",
        "accounts_payable",
    }
)


# "sparse" is a flow CP-1 writes only for the periods it occurred in (an
# add-back, a lease or interest payment classed in financing): a period
# without a row is its parts' sum, and a quarter without one is nothing.
# "flow" needs a row for every period it sums.
_Kind = Literal["flow", "sparse", "balance", "exact"]


@dataclass(frozen=True, slots=True)
class _Series:
    kind: _Kind
    # Each row's cell, keyed by period id; None, no period, is never a key.
    rows: dict[str | None, Cell]
    # A sparse item's resolved cell per period, each worked out once; and
    # the periods whose working out has started: one met again before it is
    # resolved is in a cycle (`cp1_registers` refuses them), which stops at
    # that period's own row.
    resolved: dict[str | None, Cell] = field(default_factory=dict)
    started: set[str | None] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _Register:
    periods: dict[str | None, PeriodRow]  # None is never a key
    ending: dict[str | None, tuple[str, ...]]  # end date -> ids, register order
    # Start date -> the dated flow periods starting then, register order:
    # what a sparse item's cover of a period is chosen from.
    starting: dict[str, tuple[PeriodRow, ...]]


_KPI_KINDS: dict[str, _Kind] = {"PERIOD_FLOW": "flow", "PERIOD_END": "balance"}
_Entry = tuple[str, _Kind, str, Cell]


_SPARSE_ACCOUNTS = frozenset({"lease_payments_in_financing", "interest_paid_in_financing"})


def _account_kind(metric_id: str) -> _Kind:
    if metric_id in _SPARSE_ACCOUNTS:
        return "sparse"
    if metric_id in FLOW_METRICS:
        return "flow"
    return "balance" if metric_id in BALANCE_METRICS else "exact"


def _row(value: Decimal | None, source: SourceRef | None, outflow: bool = False) -> Cell:
    """A register row's cell: `NOT_STATED` without a figure; a negative zero
    is zero; an outflow written positive is read negative (exactly: no
    context rounds it) and noted."""
    if value is None:
        return replace(_UNSTATED, input_sources=refs([source]))
    value = no_negative_zero(value)
    cell = Cell(value, basis="REPORTED", sources=refs([source]))
    if outflow and value > 0:
        return replace(cell, value=value.copy_negate(), note=SIGN_NORMALISED)
    return cell


def _no_cost_of_revenue(row: AccountRow) -> bool:
    """CP-1's marker for an issuer reporting expenses by nature: a `cogs` row
    with no figure and `NOT AVAILABLE`. It reads as no row, as `_income` expects."""
    return (
        row.metric_id == "cogs" and row.value is None and row.calculation_status == "NOT AVAILABLE"
    )


def _entries(regs: Cp1Registers) -> Iterator[_Entry]:
    """(key, kind, period id, cell) for every register row."""
    for a in regs.accounts:
        kind = _account_kind(a.metric_id)
        cell = _row(a.value, a.source, a.metric_id in OUTFLOW_METRICS)
        if _no_cost_of_revenue(a):
            cell = ABSENT
        yield f"acct:{a.metric_id}", kind, a.period_id, cell
    for s in regs.segments:
        yield f"bu:{s.segment_id}", "flow", s.period_id, _row(s.revenue, s.source)
    for b in regs.addbacks:
        yield f"addback:{b.addback_id}", "sparse", b.period_id, _row(b.value, b.source)
    for k in regs.kpis:
        kind = _KPI_KINDS.get(k.value_type, "exact")
        yield f"kpi:{k.kpi_id}", kind, k.period_id, _row(k.value, k.source)
    for f in regs.facilities:
        cell = _row(f.carrying_value, f.source)
        yield f"fac:{f.facility_id}", "balance", f.period_id, cell


def _series(regs: Cp1Registers) -> dict[str, _Series]:
    """Every frame key's rows by period (one each: `cp1_registers` refuses a
    second), read by the kind of the key's first row."""
    series: dict[str, _Series] = {}
    for key, kind, period_id, cell in _entries(regs):
        series.setdefault(key, _Series(kind, {})).rows[period_id] = cell
    return series


def _register(regs: Cp1Registers) -> _Register:
    periods: dict[str | None, PeriodRow] = {}
    ending: dict[str | None, tuple[str, ...]] = {}
    starting: dict[str, tuple[PeriodRow, ...]] = {}
    for period in regs.periods:
        first = _first_day(period)
        if period.period_type in _COVERING and first and period.end_date:
            starting[first.isoformat()] = (
                *starting.get(first.isoformat(), ()),
                period,
            )
        periods[period.period_id] = period
        if period.end_date is not None:
            ending[period.end_date] = (
                *ending.get(period.end_date, ()),
                period.period_id,
            )
    return _Register(periods, ending, starting)


_MISSING = Cell(None, "COMPONENT_MISSING")  # a part not stated, or no period
_FROM_PARTS = "differs from components"
# An LTM whose FY, YTD and PYTD are stated on some but not all: a sum of them
# would span more or fewer than twelve months.
PARTLY_STATED = "FY, YTD and PYTD not all stated"
# The periods a sparse item's cover is chosen from.
_COVERING = frozenset({"QUARTER", "YTD", "FY", "LTM"})
_UNSTATED = Cell(None, "NOT_STATED")  # a row without a figure


def _reported(series: _Series, period_id: str | None) -> Cell:
    """The period's row: `NOT_SOURCED` when there is none, `NOT_STATED`
    when it has no figure."""
    return series.rows.get(period_id, ABSENT)


def _sum(series: _Series, parts: Iterable[tuple[Cell, int]]) -> Cell:
    """The parts added (+1) or subtracted (-1), noted `SIGN_NORMALISED`
    where one is. A part not stated, or missing, is `COMPONENT_MISSING` (with
    that part's note); every part absent is `NOT_SOURCED`; some absent is
    `COMPONENT_MISSING`, except in a sparse series, where an absent part is
    nothing."""
    cells = list(parts)
    arithmetic = Arithmetic("sum", tuple(cells))
    if not cells:
        return ABSENT
    missing = [cell for cell, _ in cells if cell.value is None]
    unstated = next((c for c in missing if c.reason != "NOT_SOURCED"), None)
    if unstated is not None:
        return Cell(None, "COMPONENT_MISSING", note=unstated.note, arithmetic=arithmetic)
    if missing and (len(missing) == len(cells) or series.kind != "sparse"):
        return replace(ABSENT if len(missing) == len(cells) else _MISSING, arithmetic=arithmetic)
    return calc((cell, sign) for cell, sign in cells if cell.value is not None)


def _spans(register: _Register, period: PeriodRow) -> bool:
    """Whether the period's components are distinct periods, each starting
    the day after the one before ends, from its start date to its end
    date."""
    ids = period.component_period_ids
    whole = _dated(period)
    parts = [_dated(register.periods.get(part)) for part in ids]
    if whole is None or None in parts or len(set(ids)) != len(ids):
        return False
    following = whole[0]
    for start, end in sorted(part for part in parts if part is not None):
        if start != following:
            return False
        following = end + 1
    return following == whole[1] + 1


_UNSPANNED_PARTS = Cell(None, "COMPONENT_MISSING", note=UNSPANNED)


def _component(series: _Series, register: _Register, period_id: str | None) -> Cell:
    """Resolve all declared flow components; a reported subtotal is not a plug."""
    if period_id not in register.periods:
        return _MISSING
    if series.kind == "sparse":
        return _resolved(series, register, period_id)

    def resolve(identity: str | None, ancestors: tuple[str, ...]) -> Cell:
        period = register.periods.get(identity)
        if period is None:
            return _MISSING
        if period.period_id in ancestors or len(ancestors) >= 4:
            return _UNSPANNED_PARTS
        if period.period_type not in _ADDITIVE or not period.component_period_ids:
            return _sum(series, ((_reported(series, period.period_id), 1),))
        if not _spans(register, period):
            return _UNSPANNED_PARTS
        child_path = (*ancestors, period.period_id)
        parts = ((resolve(part, child_path), 1) for part in period.component_period_ids)
        return _sum(series, parts)

    return resolve(period_id, ())


def _resolved(series: _Series, register: _Register, period_id: str | None) -> Cell:
    """A sparse item's cell for a period: its own row, noted where parts that
    tile it differ beyond its rounding; else its parts' where they tile it
    (`NOT_SOURCED` when none has a row), and `COMPONENT_MISSING`, noted
    `UNSPANNED`, where they leave a gap but one has a figure. Worked out once
    per period."""
    known = series.resolved.get(period_id)
    if known is not None:
        return known
    own = _reported(series, period_id)
    period = register.periods.get(period_id)
    if period is None or period_id in series.started:
        return own
    series.started.add(period_id)
    parts, tiled = _parts(series, register, period)
    if own.value is not None:
        differs = tiled and parts.value is not None and beyond_rounding(own.value, parts.value)
        cell = replace(own, note=join_notes(own.note, _FROM_PARTS if differs else None))
    elif own.reason != "NOT_SOURCED":
        cell = own
    elif tiled or parts.value is None:
        cell = parts
    else:
        cell = _UNSPANNED_PARTS  # a partial sum is never the period's figure
    series.resolved[period_id] = cell
    return cell


def _parts(series: _Series, register: _Register, period: PeriodRow) -> tuple[Cell, bool]:
    """A sparse item's figure for a period from its parts, and whether they
    tile it: its components where it names them (`COMPONENT_MISSING`, noted,
    where they do not span it), else its cover."""
    if period.component_period_ids:
        if not _spans(register, period):
            return _UNSPANNED_PARTS, False
        cells = [_resolved(series, register, part) for part in period.component_period_ids]
        tiled = True
    else:
        cells, tiled = _cover(series, register, period)
    return _sum(series, ((cell, 1) for cell in cells)), tiled


def _cover(series: _Series, register: _Register, period: PeriodRow) -> tuple[list[Cell], bool]:
    """The period's parts from its start date, one `_step` at a time from the
    day after the last part ends, and whether they tile it to its end date:
    a day on which no part starts is a gap, and the cover goes on from the
    next day a period starts (so a part with a figure past a gap is still
    seen)."""
    whole = _dated(period)
    if whole is None:
        return [], False
    cells: list[Cell] = []
    tiled = True
    day = whole[0]
    while day <= whole[1]:
        step = _step(series, register, (period, (day, whole[1])))
        if step is None:
            tiled = False
            day = _next_start(register, day, whole[1] + 1)
            continue
        last, cell = step
        if cell is not None:
            cells.append(cell)
        day = last + 1
    return cells, tiled


def _next_start(register: _Register, day: int, beyond: int) -> int:
    """The first day after `day` (ordinals) on which a period starts; else
    `beyond`."""
    after = date.fromordinal(day).isoformat()
    later = (start for start in sorted(register.starting) if start > after)
    following = next(later, None)
    return beyond if following is None else date.fromisoformat(following).toordinal()


def _part(series: _Series, register: _Register, period: PeriodRow, part: PeriodRow) -> Cell:
    """A cover part's cell: resolved, except a part with the period's own
    dates, which gives its own row only (so neither resolves the other)."""
    if _dated(part) == _dated(period):
        return _reported(series, part.period_id)
    return _resolved(series, register, part.period_id)


def _step(
    series: _Series, register: _Register, at: tuple[PeriodRow, tuple[int, int]]
) -> tuple[int, Cell | None] | None:
    """The cover part starting on `at`'s day (ordinal), as its last day and
    its cell: the longest other period starting then and ending by `at`'s
    last day that has a figure; else the shortest without a row, which is
    nothing (None); else one whose components do not span it, which leaves
    its days without a figure; None where no period starts then (a gap). A
    part with the period's own dates and no row is never nothing."""
    period, (day, end) = at
    fitting = sorted(
        (
            (span[1], part)
            for part in register.starting.get(date.fromordinal(day).isoformat(), ())
            if part.period_id != period.period_id
            and (span := _dated(part)) is not None
            and span[1] <= end
        ),
        key=lambda found: found[0],
        reverse=True,
    )
    nothing: tuple[int, Cell | None] | None = None
    unspanned: tuple[int, Cell | None] | None = None
    for last, part in fitting:
        cell = _part(series, register, period, part)
        if cell == _UNSPANNED_PARTS:
            unspanned = unspanned or (last, cell)
        elif cell.reason != "NOT_SOURCED":
            return last, cell
        elif _dated(part) != _dated(period):
            nothing = (last, None)
    return nothing or unspanned


def _term(series: _Series, register: _Register, ref: str | _Spec | None) -> Cell:
    """A term's cell: a column's, or a register period's."""
    if isinstance(ref, _Spec):
        return _flow(series, register, ref)
    return _component(series, register, ref)


def _partly_stated(spec: _Spec, cells: list[tuple[Cell, int]]) -> bool:
    """Whether an LTM built as FY + YTD - PYTD has some of the three stated
    and another without a row (`NOT_SOURCED`), except both interims without
    one (the LTM is then the FY's). A part missing otherwise is `_sum`'s."""
    if spec.column.kind != "LTM" or len(cells) != 3:
        return False
    found = [cell.value is not None for cell, _ in cells]
    absent = [cell.reason == "NOT_SOURCED" for cell, _ in cells]
    if not any(found) or not all(map(operator.or_, found, absent)):
        return False
    return any(absent) and not (absent[1] and absent[2])


def _flow(series: _Series, register: _Register, spec: _Spec) -> Cell:
    if spec.terms is None:
        if series.kind == "sparse":
            return _resolved(series, register, spec.own)
        return _reported(series, spec.own)
    stated = _reported(series, spec.stated).value
    if spec.unbuilt is not None:
        return Cell(None, "COMPONENT_MISSING", stated=stated, note=spec.unbuilt)
    terms = [(_term(series, register, ref), sign) for ref, sign in spec.terms]
    if series.kind == "sparse" and _partly_stated(spec, terms):
        return Cell(None, "COMPONENT_MISSING", stated=stated, note=PARTLY_STATED)
    total = _sum(series, terms)
    if total.value is None:
        return replace(total, stated=stated)
    differs = stated is not None and beyond_rounding(stated, total.value)
    note = join_notes(total.note, DIFFERS if differs else None)
    return replace(total, stated=stated, note=note)


def _balance(series: _Series, register: _Register, spec: _Spec) -> Cell:
    """The first observation at the column's end date: its own period's, then
    any period's ending that day, in register order."""
    ending = register.ending.get(spec.column.end_date, ())
    cells = [_reported(series, period_id) for period_id in (spec.own, *ending)]
    found = next((cell for cell in cells if cell.value is not None), None)
    if found is not None:
        return found
    return _UNSTATED if _UNSTATED in cells else ABSENT


def _exact(series: _Series, register: _Register, spec: _Spec) -> Cell:
    """A rate: only a row for exactly the column's own period."""
    return _reported(series, spec.own)


_READERS = {"flow": _flow, "sparse": _flow, "balance": _balance, "exact": _exact}


def _read(key: str, series: _Series, register: _Register, spec: _Spec) -> Cell:
    """The series' cell on the column. Deploy VI A14: an add-back none of whose
    parts has a row, but whose LTM period has one (stated only for the LTM),
    reads that row, so it counts in Structuring EBITDA instead of reading
    `NOT_SOURCED`; every other series keeps caos's rule (the stated figure is
    only kept beside the reason)."""
    found = _READERS[series.kind](series, register, spec)
    ltm_only = key.startswith("addback:") and spec.column.kind == "LTM"
    if ltm_only and found.reason == "NOT_SOURCED" and found.stated is not None:
        return _reported(series, spec.stated)
    return found


def account_frame(regs: Cp1Registers, columns: tuple[Column, ...]) -> Frame:
    """CP-1's figures over `columns` (from `historical_columns`): each column
    to `acct:<metric_id>`, `bu:<segment_id>`, `addback:<addback_id>`,
    `kpi:<kpi_id>` and `fac:<facility_id>` cells."""
    with localcontext(CONTEXT):
        specs = {spec.column.column_id: spec for spec in _plan(regs)}
        series = _series(regs)
        register = _register(regs)
        return {
            column.column_id: {
                key: _read(key, one, register, specs[column.column_id])
                for key, one in series.items()
            }
            for column in columns
        }


def _earlier(spec: _Spec, quarters: dict[tuple[int, int], _Spec]) -> list[_Spec | None]:
    """The three quarters before `spec`'s; None where one is not a column."""
    if spec.quarter is None:
        return [None, None, None]
    year, number = spec.quarter
    earlier: list[_Spec | None] = []
    for back in (1, 2, 3):
        prior_year, prior = divmod(year * 4 + number - 1 - back, 4)
        earlier.append(quarters.get((prior_year, prior + 1)))
    return earlier


def _rolling_days(spec: _Spec, earlier: list[_Spec | None], register: _Register) -> int | None:
    """Return the span of four usable, contiguous quarters, else None."""
    quarters = (*reversed(earlier), spec)
    if len(quarters) != 4:
        return None
    first_start: int | None = None
    next_start: int | None = None
    for quarter in quarters:
        if quarter is None or quarter.unbuilt is not None:
            return None
        start = _start(quarter, register.periods)
        end = iso_date(quarter.column.end_date)
        if start is None or end is None:
            return None
        end_day = end.toordinal()
        if not 1 <= start <= end_day:
            return None
        if next_start is not None and start != next_start:
            return None
        if first_start is None:
            first_start = start
        next_start = end_day + 1
    assert first_start is not None and next_start is not None
    days = next_start - first_start
    return days if LTM_DAYS[0] <= days <= LTM_DAYS[1] else None


def ltm_columns(regs: Cp1Registers, columns: tuple[Column, ...]) -> tuple[Column, ...]:
    """Metadata for `ltm_frames`, keyed by quarter but dated over all four quarters.

    Keep these in a separate frame: the keys deliberately match the associated
    quarter so `metric_frame` can select its twelve-month basis.
    """
    plan = {spec.column.column_id: spec for spec in _plan(regs)}
    quarters = _quarter_index(plan.values())
    register = _register(regs)
    return tuple(
        replace(
            column,
            kind="LTM",
            label=f"LTM {column.label}",
            days=_rolling_days(
                plan[column.column_id], _earlier(plan[column.column_id], quarters), register
            ),
        )
        for column in columns
        if column.kind == "QUARTER"
    )


def _ltm_cell(
    series: _Series, register: _Register, spec: _Spec, earlier: list[_Spec | None]
) -> Cell:
    """A flow over the quarter and the three before it is their sum; a
    balance is the quarter's; a rate has no observation for twelve months."""
    if series.kind == "balance":
        return _balance(series, register, spec)
    if series.kind == "exact":
        return Cell(None, "NOT_SOURCED")
    if (
        all(quarter is not None for quarter in earlier)
        and _rolling_days(spec, earlier, register) is None
    ):
        return _UNSPANNED_PARTS
    quarters = (
        (_MISSING if quarter is None else _flow(series, register, quarter), 1)
        for quarter in (spec, *earlier)
    )
    return _sum(series, quarters)


def ltm_frames(regs: Cp1Registers, columns: tuple[Column, ...]) -> dict[str, dict[str, Cell]]:
    """For each quarter column in `columns`, the cells of the twelve months
    ending with it: flows summed over it and the three quarters before it,
    `COMPONENT_MISSING` without all four (an add-back's absent quarter adds
    nothing)."""
    with localcontext(CONTEXT):
        plan = {spec.column.column_id: spec for spec in _plan(regs)}
        quarters = _quarter_index(plan.values())
        series = _series(regs)
        register = _register(regs)
        frames: dict[str, dict[str, Cell]] = {}
        for spec in (plan[c.column_id] for c in columns if c.kind == "QUARTER"):
            earlier = _earlier(spec, quarters)
            frames[spec.column.column_id] = {
                key: _ltm_cell(one, register, spec, earlier) for key, one in series.items()
            }
        return frames
