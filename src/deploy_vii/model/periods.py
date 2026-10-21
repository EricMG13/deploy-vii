"""The historical columns (spec M2), split from caos `history.py`: which
columns a register gives and how each is built from register periods;
`history` reads CP-1's figures over them.

Columns run quarters, PYTD, YTD, FY, then LTM. Every reported quarter is a
column; where CP-1's period register has no quarter, one is calculated as
H1 - Q1, 9M - H1 or FY - 9M when both periods exist.

The anchor is the latest end date of a quarter, YTD or FY period. At a
fiscal-year end there is no YTD and the LTM is that FY. Otherwise the YTD is
the YTD period ending at the anchor, else the anchor year's quarters to date
when every one is a column; the PYTD is the prior year's YTD period of the
same fiscal quarter, else (by its dates, its fiscal quarter not required) the
one YTD period of the same whole months starting twelve months earlier, else
the prior year's same quarters; and the LTM is FY + YTD - PYTD with the FY of
the prior year, the PYTD's. Deploy VI: an LTM spanning other than `LTM_DAYS`
(a stub year, a mislabelled interim) is unbuilt, noted `UNSPANNED`. The dates
leave the PYTD ambiguous where a YTD period ends before the YTD starts, or
has no dates, but not exactly one dated period is that one (or the YTD is
not whole months); without the prior year's quarters either, the LTM's flows
are then `COMPONENT_MISSING`, noted `UNSPANNED`.
CP-1's LTM row ending at the anchor names the LTM column and supplies the
stated figures; one ending later than the anchor keeps its own column,
its flows `COMPONENT_MISSING` with CP-1's figure as `stated` (spec M4: the
host recomputes, it never adopts CP-1's arithmetic).

Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from deploy_vii.model._cells import UNSPANNED
from deploy_vii.model.frame import Column
from deploy_vii.model.registers import Cp1Registers, PeriodRow, fiscal_year_number, iso_date

_YTD_LABELS = {1: "Q1", 2: "H1", 3: "9M", 4: "12M"}
LTM_DAYS = (364, 371)  # Deploy VI: twelve months, a 52- or 53-week year included
_QUARTERS = {f"{prefix}{n}": n for n in range(1, 5) for prefix in ("", "Q")}
_ADDITIVE = frozenset({"YTD", "FY"})
_RANK = {"FY": 0, "YTD": 1, "QUARTER": 2}  # which period at the anchor date


@dataclass(frozen=True, slots=True)
class _Spec:
    """A column and how its cells are read."""

    column: Column
    own: str | None  # the register period the column is, if any
    terms: tuple[_Term, ...] | None  # None: the own period as reported
    stated: str | None = None  # where CP-1 stated a derived column's figure
    # (read only when `terms` is set)
    quarter: tuple[int, int] | None = None  # (fiscal year, quarter) of a quarter
    unbuilt: str | None = None  # why the terms cannot be summed, if they cannot


# A term adds (+1) or subtracts (-1) a register period's figure, a column's
# cell, or nothing: None is a component that does not exist.
_Term = tuple["str | _Spec | None", int]
_UNBUILT: tuple[_Term, ...] = ((None, 1),)  # no component the host can build


def _quarter_number(period: PeriodRow) -> int | None:
    """The register's fiscal quarter, `2` or `Q2`, as 1 to 4; else None."""
    if period.fiscal_quarter is None:
        return None
    return _QUARTERS.get(period.fiscal_quarter.upper())


def _year(period: PeriodRow) -> int | None:
    return fiscal_year_number(period.fiscal_year)


def _yy(fiscal_year: str) -> str:
    """The year's last two digits: of its four-digit year where it has one."""
    year = fiscal_year_number(fiscal_year)
    return fiscal_year[-2:] if year is None else f"{year % 100:02d}"


def _by_end(periods: Iterable[PeriodRow]) -> list[PeriodRow]:
    return sorted(periods, key=lambda period: period.end_date or "")


def _of_type(regs: Cp1Registers, period_type: str) -> list[PeriodRow]:
    return [p for p in regs.periods if p.period_type == period_type]


def _by_quarter(
    periods: Iterable[PeriodRow],
) -> dict[tuple[int | None, int], PeriodRow]:
    """Each (fiscal year, quarter) to its period: one each, `cp1_registers`
    refuses a second."""
    index: dict[tuple[int | None, int], PeriodRow] = {}
    for period in periods:
        number = _quarter_number(period)
        if number is not None:
            index[_year(period), number] = period
    return index


def _days(minuend: PeriodRow, subtrahend: PeriodRow) -> int | None:
    if minuend.day_count is None or subtrahend.day_count is None:
        return None
    return minuend.day_count - subtrahend.day_count


def _quarter_spec(
    period: PeriodRow,
    number: int | None,
    own: str | None,
    terms: tuple[_Term, ...] | None,
) -> _Spec:
    """A quarter's column, labelled `Q{n} {yy}`; by its period id when the
    register's fiscal quarter is not 1 to 4."""
    year = _year(period)
    label = period.period_id if number is None else f"Q{number} {_yy(period.fiscal_year)}"
    return _Spec(
        column=Column(
            column_id=f"Q:{own}" if own is not None else f"Q:{_term_ids(terms)}",
            kind="QUARTER",
            label=label,
            period_id=own,
            fiscal_year=period.fiscal_year,
            end_date=period.end_date,
            days=period.day_count,
            case=None,
        ),
        own=own,
        terms=terms,
        quarter=None if year is None or number is None else (year, number),
    )


def _term_ids(terms: tuple[_Term, ...] | None) -> str:
    return "-".join(str(period_id) for period_id, _ in terms or ())


def _calculated_quarters(regs: Cp1Registers) -> list[_Spec]:
    """Q2 = H1 - Q1, Q3 = 9M - H1 and Q4 = FY - 9M, where the register has
    no such quarter and both periods exist."""
    reported = _by_quarter(_of_type(regs, "QUARTER"))
    ytd = _by_quarter(_of_type(regs, "YTD"))
    fiscal = {_year(p): p for p in _of_type(regs, "FY")}
    specs = []
    for year in dict.fromkeys(_year(p) for p in regs.periods):
        candidates = (
            (2, ytd.get((year, 2)), reported.get((year, 1))),
            (3, ytd.get((year, 3)), ytd.get((year, 2))),
            (4, fiscal.get(year), ytd.get((year, 3))),
        )
        for number, whole_period, prefix_period in candidates:
            if (year, number) in reported or whole_period is None or prefix_period is None:
                continue
            terms = ((whole_period.period_id, 1), (prefix_period.period_id, -1))
            spec = _quarter_spec(whole_period, number, None, terms)
            whole, prefix = _dated(whole_period), _dated(prefix_period)
            comparable = (
                whole is not None
                and prefix is not None
                and whole[0] == prefix[0]
                and prefix[1] < whole[1]
            )
            days = _days(whole_period, prefix_period) if comparable else None
            specs.append(
                replace(
                    spec,
                    column=replace(spec.column, days=days),
                    unbuilt=None if comparable else UNSPANNED,
                )
            )
    return specs


def _quarters(regs: Cp1Registers) -> list[_Spec]:
    specs = _calculated_quarters(regs)
    for period in _of_type(regs, "QUARTER"):
        number = _quarter_number(period)
        specs.append(_quarter_spec(period, number, period.period_id, None))
    return sorted(specs, key=lambda spec: spec.column.end_date or "")


def _period_spec(period: PeriodRow, kind: Literal["PYTD", "YTD", "FY"]) -> _Spec:
    """A register period's column; derived when it names its components."""
    number = _quarter_number(period)
    if kind == "FY":
        label = f"FY{_yy(period.fiscal_year)}"
    elif number is None:
        label = f"{kind} {period.period_id}"
    else:
        label = f"{kind} {_YTD_LABELS[number]} {_yy(period.fiscal_year)}"
    derived = bool(period.component_period_ids)
    return _Spec(
        column=Column(
            column_id=f"{kind}:{period.period_id}",
            kind=kind,
            label=label,
            period_id=period.period_id,
            fiscal_year=period.fiscal_year,
            end_date=period.end_date,
            days=period.day_count,
            case=None,
        ),
        own=period.period_id,
        terms=((period.period_id, 1),) if derived else None,
        stated=period.period_id,
    )


def _anchor(regs: Cp1Registers) -> PeriodRow | None:
    """The period at the latest end date of a quarter, YTD or FY: an FY
    ending then, else a YTD, else a quarter, first in register order. An end
    that is not a `YYYY-MM-DD` date is none (its text would sort anywhere)."""
    candidates = [p for p in regs.periods if p.period_type in _RANK]
    ends = [day.isoformat() for p in candidates if (day := iso_date(p.end_date))]
    if not ends:
        return None
    return min(
        (p for p in candidates if p.end_date == max(ends)),
        key=lambda p: _RANK[p.period_type],
    )


def _quarter_index(specs: Iterable[_Spec]) -> dict[tuple[int, int], _Spec]:
    """Each (fiscal year, quarter) to its quarter column: one each, as
    `cp1_registers` refuses a second period for one fiscal quarter."""
    return {spec.quarter: spec for spec in specs if spec.quarter is not None}


def _summed(
    kind: Literal["PYTD", "YTD"],
    quarters: dict[tuple[int, int], _Spec],
    year: int,
    number: int,
) -> _Spec | None:
    """The year's quarters 1 to `number` as one column; None unless every
    one is a column."""
    specs = []
    for n in range(1, number + 1):
        spec = quarters.get((year, n))
        if spec is None:
            return None
        specs.append(spec)
    last = specs[-1].column
    terms: tuple[_Term, ...] = tuple((spec, 1) for spec in specs)
    return _Spec(
        column=Column(
            column_id=f"{kind}:{last.column_id.removeprefix('Q:')}",
            kind=kind,
            label=f"{kind} {_YTD_LABELS[number]} {_yy(last.fiscal_year)}",
            period_id=None,
            fiscal_year=last.fiscal_year,
            end_date=last.end_date,
            days=_term_days(terms),
            case=None,
        ),
        own=None,
        terms=terms,
    )


def _whole_months(dated: tuple[int, int] | None) -> tuple[int, int] | None:
    """A span (ordinals) from a month's first day to a month's last day as
    its first month (year x 12 + month) and its number of months; None for
    any other span, or none."""
    if dated is None or not 1 <= dated[0] <= dated[1] < date.max.toordinal():
        return None
    first, following = date.fromordinal(dated[0]), date.fromordinal(dated[1] + 1)
    if first.day != 1 or following.day != 1:
        return None
    month = first.year * 12 + first.month
    return month, following.year * 12 + following.month - month


def _dated_prior(regs: Cp1Registers, ytd: _Spec | None) -> tuple[_Spec | None, bool]:
    """The PYTD of `ytd` by dates: the one other YTD period of the same whole
    months starting twelve months before it. Else None, and whether the dates
    leave it ambiguous: a YTD period ends before `ytd` starts, or has no
    dates, while none or several are that one."""
    if ytd is None:
        return None, False
    periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
    first, end = _start(ytd, periods), iso_date(ytd.column.end_date)
    span = None if first is None or end is None else (first, end.toordinal())
    months = _whole_months(span)
    before = [
        p
        for p in _of_type(regs, "YTD")
        if p.period_id != ytd.own
        and ((dated := _dated(p)) is None or first is None or dated[1] < first)
    ]
    found = [
        p
        for p in before
        if months is not None and _whole_months(_dated(p)) == (months[0] - 12, months[1])
    ]
    if len(found) == 1 and None not in map(_dated, before):
        return _period_spec(found[0], "PYTD"), False
    return None, bool(before)


def _to_date(
    regs: Cp1Registers,
    quarters: dict[tuple[int, int], _Spec],
    anchor: PeriodRow | None,
) -> tuple[_Spec | None, _Spec | None, bool]:
    """(PYTD, YTD) to the anchor, neither at a fiscal-year end; and whether
    no PYTD was found because the dates leave it ambiguous."""
    if anchor is None or anchor.period_type == "FY":
        return None, None, False
    row = next((p for p in _of_type(regs, "YTD") if p.end_date == anchor.end_date), None)
    year, number = _year(anchor), _quarter_number(row or anchor)
    known = None if year is None or number is None else (year, number)
    if row is not None:
        ytd: _Spec | None = _period_spec(row, "YTD")
    else:
        ytd = None if known is None else _summed("YTD", quarters, *known)
    pytd, ambiguous = _prior_to_date(regs, quarters, ytd, known)
    return pytd, ytd, ambiguous


def _prior_to_date(
    regs: Cp1Registers,
    quarters: dict[tuple[int, int], _Spec],
    ytd: _Spec | None,
    known: tuple[int, int] | None,
) -> tuple[_Spec | None, bool]:
    """The PYTD of `ytd`, the anchor's fiscal year and quarter `known`: the
    prior year's YTD period of that quarter; else the one by its dates
    (`_dated_prior`); else the prior year's quarters to that one. And whether
    none was found because the dates leave it ambiguous."""
    if known is not None:
        year, number = known
        labelled = next(
            (
                p
                for p in _of_type(regs, "YTD")
                if _year(p) == year - 1 and _quarter_number(p) == number
            ),
            None,
        )
        if labelled is not None:
            return _period_spec(labelled, "PYTD"), False
    dated, ambiguous = _dated_prior(regs, ytd)
    if dated is not None or known is None:
        return dated, ambiguous
    summed = _summed("PYTD", quarters, known[0] - 1, known[1])
    return summed, ambiguous and summed is None


def _ltm_label(period: PeriodRow, number: int | None) -> str:
    if number is None:
        return f"LTM {period.period_id}"
    return f"LTM Q{number} {_yy(period.fiscal_year)}"


def _term_days(terms: tuple[_Term, ...]) -> int | None:
    """The terms' columns' day counts added and subtracted; None when one is
    unknown."""
    days = 0
    for spec, sign in terms:
        count = spec.column.days if isinstance(spec, _Spec) else None
        if count is None:
            return None
        days += sign * count
    return days


def _first_day(period: PeriodRow) -> date | None:
    """The period's start date; without one, its end less its day count
    (end - days + 1); None where neither is known or the day count is not
    positive."""
    start = iso_date(period.start_date)
    end = iso_date(period.end_date)
    if start is not None or end is None or period.day_count is None:
        return start
    first = end.toordinal() - period.day_count + 1
    return date.fromordinal(first) if 1 <= first <= end.toordinal() else None


def _dated(period: PeriodRow | None) -> tuple[int, int] | None:
    """The period's first and last day as ordinals (the first derived from
    the day count where no start is stated); None without both or with the
    end before the start."""
    if period is None:
        return None
    start, end = _first_day(period), iso_date(period.end_date)
    if start is None or end is None or end < start:
        return None
    return start.toordinal(), end.toordinal()


def _start(spec: _Spec, periods: Mapping[str | None, PeriodRow]) -> int | None:
    """A column's first day as an ordinal: its own period's start; else its
    end date less its days; else, for quarters to date, the first quarter's
    start; None when none is known. (The FY, YTD and PYTD are never a
    calculated quarter.)"""
    own = _dated(periods.get(spec.own))
    if own is not None:
        return own[0]
    end = iso_date(spec.column.end_date)
    if end is not None and spec.column.days is not None:
        return end.toordinal() - spec.column.days + 1
    first = (spec.terms or _UNBUILT)[0][0]
    return _start(first, periods) if isinstance(first, _Spec) else None


def _meets(regs: Cp1Registers, fy: _Spec, ytd: _Spec, pytd: _Spec) -> bool:
    """Whether the FY ends the day before the YTD starts and the PYTD starts
    with the FY: FY + YTD - PYTD is then the twelve months to the YTD's end."""
    periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
    starts = [_start(s, periods) for s in (fy, ytd, pytd)]
    year_end = iso_date(fy.column.end_date)
    if year_end is None or None in starts:
        return False
    year, current, prior = starts
    return year_end.toordinal() + 1 == current and prior == year


def _rolled(
    regs: Cp1Registers,
    anchor: PeriodRow,
    fiscal: list[_Spec],
    to_date: tuple[_Spec | None, _Spec | None],
) -> tuple[tuple[_Term, ...], str | None]:
    """FY + YTD - PYTD with the FY of the year before the anchor's, and
    `UNSPANNED` where the three do not meet (else None)."""
    pytd, ytd = to_date
    year = _year(anchor)
    prior = None if year is None else year - 1
    fy = next(
        (s for s in fiscal if fiscal_year_number(s.column.fiscal_year) == prior),
        None,
    )
    met = not (fy and ytd and pytd) or _meets(regs, fy, ytd, pytd)
    return ((fy, 1), (ytd, 1), (pytd, -1)), None if met else UNSPANNED


def _host_ltm(
    regs: Cp1Registers,
    anchor: PeriodRow,
    fiscal: list[_Spec],
    to_date: tuple[_Spec | None, _Spec | None],
) -> _Spec:
    """Build the LTM as the anchor FY or FY + YTD - PYTD.

    A stated LTM row supplies its identity and comparison figure. Its dates
    must agree with the computed span; its day count never replaces that span.
    """
    unbuilt = None
    if anchor.period_type == "FY":
        own_fy = next(spec for spec in fiscal if spec.own == anchor.period_id)
        terms: tuple[_Term, ...] = ((own_fy, 1),)
        number: int | None = 4
    else:
        terms, unbuilt = _rolled(regs, anchor, fiscal, to_date)
        number = _quarter_number(anchor)
    span = anchor.day_count if anchor.period_type == "FY" else _term_days(terms)
    complete = all(isinstance(ref, _Spec) for ref, _ in terms)
    if span is None and complete:
        # Only complete, dated components can establish a missing day count.
        periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
        dated_days = 0
        for ref, sign in terms:
            if isinstance(ref, _Spec):
                start, end = _start(ref, periods), iso_date(ref.column.end_date)
                if start is None or end is None or start > end.toordinal():
                    break
                dated_days += sign * (end.toordinal() - start + 1)
        else:
            span = dated_days
    invalid_span = (span is None and complete) or (
        span is not None and not LTM_DAYS[0] <= span <= LTM_DAYS[1]
    )
    if invalid_span:
        unbuilt = UNSPANNED  # Deploy VI: a stub year or a mislabelled interim
    stated = next((p for p in _of_type(regs, "LTM") if p.end_date == anchor.end_date), None)
    own = stated.period_id if stated is not None else None
    stated_span = _dated(stated)
    if (
        stated is not None
        and span is not None
        and (stated_span is None or stated_span[1] - stated_span[0] + 1 != span)
    ):
        unbuilt = UNSPANNED
    return _Spec(
        column=Column(
            column_id=f"LTM:{own or anchor.period_id}",
            kind="LTM",
            label=_ltm_label(anchor, number),
            period_id=own,
            fiscal_year=anchor.fiscal_year,
            end_date=anchor.end_date,
            days=span,
            case=None,
        ),
        own=own,
        terms=terms,
        stated=own,
        unbuilt=unbuilt,
    )


def _unadopted_ltm(period: PeriodRow) -> _Spec:
    """CP-1's LTM ending after anything the host can build: its column, with
    no components, so CP-1's figure is only ever `stated`."""
    return _Spec(
        column=Column(
            column_id=f"LTM:{period.period_id}",
            kind="LTM",
            label=_ltm_label(period, _quarter_number(period)),
            period_id=period.period_id,
            fiscal_year=period.fiscal_year,
            end_date=period.end_date,
            days=period.day_count,
            case=None,
        ),
        own=period.period_id,
        terms=_UNBUILT,
        stated=period.period_id,
    )


def _plan(regs: Cp1Registers) -> tuple[_Spec, ...]:
    quarters = _quarters(regs)
    anchor = _anchor(regs)
    pytd, ytd, ambiguous = _to_date(regs, _quarter_index(quarters), anchor)
    fiscal = [_period_spec(p, "FY") for p in _by_end(_of_type(regs, "FY"))]
    specs = [*quarters, *(s for s in (pytd, ytd) if s is not None), *fiscal]
    if anchor is not None:
        ltm = _host_ltm(regs, anchor, fiscal, (pytd, ytd))
        specs.append(replace(ltm, unbuilt=UNSPANNED) if ambiguous else ltm)
    end = anchor.end_date if anchor is not None else None
    specs.extend(
        _unadopted_ltm(p)
        for p in _by_end(_of_type(regs, "LTM"))
        if end is None or p.end_date is None or p.end_date > end
    )
    return tuple(specs)


def historical_columns(regs: Cp1Registers) -> tuple[Column, ...]:
    """The historical columns in the spec's order: quarters by end date, PYTD,
    YTD, the fiscal years by end date, LTM."""
    return tuple(spec.column for spec in _plan(regs))
