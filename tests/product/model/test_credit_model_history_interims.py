"""Prior-year YTDs found by dates, and LTMs never built from a one-sided interim."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.model import history, periods
from deploy_vii.model._cells import (
    UNSPANNED,
)
from deploy_vii.model.frame import Cell
from deploy_vii.model.history import (
    account_frame,
    historical_columns,
)
from deploy_vii.model.registers import (
    AccountRow,
    Cp1Registers,
    PeriodRow,
)
from tests.product.model.history_cases import _regs


def _unlabelled(regs: Cp1Registers) -> Cp1Registers:
    """The registers with every YTD period's fiscal quarter left out."""
    return replace(
        regs,
        periods=tuple(
            replace(p, fiscal_quarter=None) if p.period_type == "YTD" else p for p in regs.periods
        ),
    )


def _halves() -> Cp1Registers:
    """Run 9b9e2b72's shape: Q2 25 and Q2 26, FY24 and FY25, H1 25 and H1 26."""
    return _regs(
        quarters={
            "Q2_2025": {"revenue": "101.5", "cogs": -40},
            "Q2_2026": {"revenue": "111.25", "cogs": -44},
        },
        fy={
            "FY2024": {"revenue": 380, "cogs": -150},
            "FY2025": {"revenue": "400.5", "cogs": -160},
        },
        ytd={
            "H1_2025": {"revenue": "200.25", "cogs": -79},
            "H1_2026": {"revenue": "210.5", "cogs": -83},
        },
    )


def test_an_unlabelled_ytd_finds_its_prior_year_ytd_by_its_dates() -> None:
    regs = _unlabelled(_halves())

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [c.column_id for c in columns] == [
        "Q:Q2_2025",
        "Q:Q2_2026",
        "PYTD:H1_2025",
        "YTD:H1_2026",
        "FY:FY2024",
        "FY:FY2025",
        "LTM:H1_2026",
    ]
    assert columns[2].label == "PYTD H1_2025"
    ltm = frame["LTM:H1_2026"]
    revenue = Decimal("400.5") + Decimal("210.5") - Decimal("200.25")
    assert ltm["acct:revenue"] == Cell(
        revenue, basis="CALCULATED", sources=ltm["acct:revenue"].sources
    )
    assert revenue == Decimal("410.75")
    assert ltm["acct:cogs"].value == Decimal(-164)
    assert frame["PYTD:H1_2025"]["acct:revenue"].value == Decimal("200.25")


def test_a_labelled_register_still_finds_its_prior_year_ytd_by_label() -> None:
    labelled = _halves()
    columns = historical_columns(labelled)
    assert [c.label for c in columns][2:4] == ["PYTD H1 25", "YTD H1 26"]
    unlabelled = _unlabelled(labelled)
    ltm = account_frame(labelled, columns)["LTM:H1_2026"]["acct:revenue"]
    dated = account_frame(unlabelled, historical_columns(unlabelled))
    assert ltm == dated["LTM:H1_2026"]["acct:revenue"]

    # A same-dated YTD without a label is a second candidate by dates only:
    # the label decides, so it is no ambiguity.
    h1 = next(p for p in labelled.periods if p.period_id == "H1_2025")
    twin = replace(h1, period_id="H1_2025_R", fiscal_quarter=None)
    restated = AccountRow("revenue", "H1_2025_R", Decimal(1), "VERIFIED", None)
    both = replace(
        labelled,
        periods=(*labelled.periods, twin),
        accounts=(*labelled.accounts, restated),
    )
    assert historical_columns(both)[2].column_id == "PYTD:H1_2025"
    assert account_frame(both, historical_columns(both))["LTM:H1_2026"]["acct:revenue"] == ltm


def _priors(regs: Cp1Registers, *priors: PeriodRow, keep: bool) -> Cp1Registers:
    """The registers with `priors` added, each with H1 2025's account rows;
    H1 2025 itself kept only with `keep`."""
    h1 = [a for a in regs.accounts if a.period_id == "H1_2025"]
    copied = tuple(replace(a, period_id=p.period_id) for p in priors for a in h1)
    return replace(
        regs,
        periods=(
            *(p for p in regs.periods if keep or p.period_id != "H1_2025"),
            *priors,
        ),
        accounts=(
            *(a for a in regs.accounts if keep or a.period_id != "H1_2025"),
            *copied,
        ),
    )


def _ambiguous_cases() -> dict[str, Cp1Registers]:
    regs = _unlabelled(_halves())
    h1 = next(p for p in regs.periods if p.period_id == "H1_2025")
    twin = replace(h1, period_id="H1_2025_R")
    q1 = replace(h1, period_id="Q1YTD_2025", end_date="2025-03-31", day_count=90)
    nine = replace(h1, period_id="9M_2025", end_date="2025-09-30", day_count=273)
    late = replace(h1, period_id="H1_2025_L", start_date="2025-01-02", day_count=180)
    short = replace(h1, period_id="H1_2025_S", end_date="2025-06-29", day_count=180)
    undated = replace(h1, period_id="H1_2025_U", start_date=None, end_date=None, day_count=None)
    return {
        "two candidates": _priors(regs, twin, keep=True),
        "spans differ (Q1)": _priors(regs, q1, keep=False),
        "spans differ (9M)": _priors(regs, nine, keep=False),
        "starts on another day": _priors(regs, late, keep=False),
        "ends on another day": _priors(regs, short, keep=False),
        "no dates": _priors(regs, undated, keep=False),
        "no dates beside a match": _priors(regs, undated, keep=True),
        "the YTD without a start": replace(
            regs,
            periods=tuple(
                replace(p, start_date=None, day_count=None) if p.period_id == "H1_2026" else p
                for p in regs.periods
            ),
        ),
    }


@pytest.mark.parametrize("case", list(_ambiguous_cases()))
def test_a_prior_year_ytd_the_dates_leave_ambiguous_is_no_pytd(case: str) -> None:
    regs = _ambiguous_cases()[case]

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [c.kind for c in columns] == [
        "QUARTER",
        "QUARTER",
        "YTD",
        "FY",
        "FY",
        "LTM",
    ]
    for key in ("acct:revenue", "acct:cogs"):
        assert frame["LTM:H1_2026"][key] == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    # The YTD itself is untouched.
    assert frame["YTD:H1_2026"]["acct:revenue"].value == Decimal("210.5")


def test_without_a_prior_year_ytd_the_ltm_is_missing_un_noted() -> None:
    regs = _priors(_unlabelled(_halves()), keep=False)
    # A YTD of the same year is no candidate for the prior year's.
    h1 = next(p for p in regs.periods if p.period_id == "H1_2026")
    q1 = replace(h1, period_id="Q1YTD_2026", end_date="2026-03-31", day_count=90)
    # Nor is one ending on the YTD's first day: it is not before the YTD.
    overlap = replace(
        h1,
        period_id="DEC_JAN",
        start_date="2025-12-01",
        end_date="2026-01-01",
        day_count=32,
    )
    for extra in ((), (q1,), (overlap,)):
        case = replace(regs, periods=(*regs.periods, *extra))
        frame = account_frame(case, historical_columns(case))
        assert frame["LTM:H1_2026"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")


def _fiscal(period_id: str, kind: str, year: int, first: date, last: date) -> PeriodRow:
    return PeriodRow(
        period_id=period_id,
        fiscal_year=str(year),
        fiscal_quarter=None,
        period_type=kind,
        start_date=first.isoformat(),
        end_date=last.isoformat(),
        day_count=(last - first).days + 1,
        currency="USD",
        unit="MILLIONS",
        component_period_ids=(),
    )


def _month(year: int, month: int) -> date:
    """The first day of the month, `month` counted on past December."""
    return date(year + (month - 1) // 12, (month - 1) % 12 + 1, 1)


@settings(deadline=None, max_examples=150)
@given(
    start=st.integers(min_value=1, max_value=12),
    months=st.sampled_from((3, 6, 9)),
    decoy=st.sampled_from((3, 6, 9)),
    year=st.integers(min_value=1990, max_value=2190),
    figures=st.tuples(*(st.integers(-(10**6), 10**6) for _ in range(4))),
)
def test_the_prior_year_ytd_by_dates_is_the_one_of_the_same_months(
    start: int,
    months: int,
    decoy: int,
    year: int,
    figures: tuple[int, int, int, int],
) -> None:
    """Any fiscal-year start month (a February month end included) and YTD
    length: the PYTD found is the YTD of the same months a year before, never
    the decoy of another length, and the LTM is FY + YTD - PYTD exactly."""
    fy_first = _month(year, start)
    ytd_first = _month(year, start + 12)
    day = timedelta(days=1)
    periods: tuple[PeriodRow, ...] = (
        _fiscal("FY", "FY", year, fy_first, ytd_first - day),
        _fiscal("PRIOR", "YTD", year, fy_first, _month(year, start + months) - day),
        _fiscal("YTD", "YTD", year + 1, ytd_first, _month(year, start + 12 + months) - day),
    )
    if decoy != months:
        decoy_last = _month(year, start + decoy) - day
        periods = (*periods, _fiscal("DECOY", "YTD", year, fy_first, decoy_last))
    tenths = [Decimal(f) / 10 for f in figures]
    accounts = tuple(
        AccountRow("revenue", period.period_id, value, "VERIFIED", None)
        for period, value in zip(periods, tenths, strict=False)
    )
    regs = Cp1Registers(
        periods=periods,
        accounts=accounts,
        addbacks=(),
        segments=(),
        kpis=(),
        facilities=(),
        pro_forma=(),
        currency="USD",
        unit="MILLIONS",
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [c.column_id for c in columns if c.kind == "PYTD"] == ["PYTD:PRIOR"]
    fy, prior, ytd, _ = tenths
    assert frame["LTM:YTD"]["acct:revenue"].value == fy + ytd - prior


def test_a_labelled_ytd_falls_back_to_quarters_past_a_ytd_of_other_months() -> None:
    """A labelled H1 with no labelled prior H1 and a prior 9M of other months:
    the prior year's quarters still build the PYTD, and the LTM is un-noted."""
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 3}, "Q2_2025": {"revenue": 4}},
        fy={"FY2025": {"revenue": 20}},
        ytd={"9M_2025": {"revenue": 12}, "H1_2026": {"revenue": 9}},
    )

    columns = historical_columns(regs)
    ltm = account_frame(regs, columns)["LTM:H1_2026"]["acct:revenue"]

    assert [c.column_id for c in columns if c.kind == "PYTD"] == ["PYTD:Q2_2025"]
    assert (ltm.value, ltm.note) == (Decimal(22), None)


def test_whole_months_reads_a_span_from_a_first_day_to_a_last_day() -> None:
    whole = periods._whole_months
    jan, feb = date(2024, 1, 1).toordinal(), date(2024, 2, 29).toordinal()
    assert whole((jan, feb)) == (2024 * 12 + 1, 2)
    assert whole((jan, date(2024, 12, 31).toordinal())) == (2024 * 12 + 1, 12)
    assert whole((date(2023, 9, 1).toordinal(), feb)) == (2023 * 12 + 9, 6)
    assert whole((1, 31)) == (12 + 1, 1)  # 1 January of year 1
    assert whole((jan, feb - 1)) is None  # not a month's last day
    assert whole((jan + 1, feb)) is None  # not a month's first day
    assert whole((feb, jan)) is None  # ends before it starts
    assert whole((0, 31)) is None  # no such day
    assert whole((-30, 31)) is None
    december = date(9999, 12, 1).toordinal()
    assert whole((december, date.max.toordinal())) is None  # no following day
    assert whole(None) is None


def _interest(regs: Cp1Registers, figures: Mapping[str, int]) -> Cp1Registers:
    """The registers with interest paid in financing (a sparse account) on
    the given periods only."""
    rows = tuple(
        AccountRow("interest_paid_in_financing", pid, Decimal(v), "VERIFIED", None)
        for pid, v in figures.items()
    )
    kept = tuple(a for a in regs.accounts if a.metric_id != "interest_paid_in_financing")
    return replace(regs, accounts=(*kept, *rows))


@pytest.mark.parametrize("labelled", [True, False])
def test_an_ltm_is_never_built_from_a_one_sided_interim(labelled: bool) -> None:
    regs = _halves() if labelled else _unlabelled(_halves())
    key = "acct:interest_paid_in_financing"

    def ltm(figures: Mapping[str, int]) -> Cell:
        case = _interest(regs, figures)
        return account_frame(case, historical_columns(case))["LTM:H1_2026"][key]

    one_sided = Cell(None, "COMPONENT_MISSING", note=history.PARTLY_STATED)
    assert ltm({"FY2025": -20, "H1_2026": -9}) == one_sided
    assert ltm({"FY2025": -20, "H1_2025": -8}) == one_sided
    # Neither interim stated: the item did not occur in them, so the LTM is
    # the year's.
    assert ltm({"FY2025": -20}).value == Decimal(-20)
    assert ltm({"FY2025": -20, "H1_2026": -9, "H1_2025": -8}).value == Decimal(-21)
    # A stated zero is a statement: both sides stated.
    assert ltm({"FY2025": -20, "H1_2026": 0, "H1_2025": -8}).value == Decimal(-12)

    # CP-1's own LTM figure is kept as `stated`, never adopted.
    stated = _interest(
        _regs(
            fy={"FY2025": {"revenue": 1}},
            ytd={"H1_2026": {"revenue": 1}, "H1_2025": {"revenue": 1}},
            ltm={"LTM_Q2_2026": {"revenue": 1}},
        ),
        {"FY2025": -20, "H1_2026": -9, "LTM_Q2_2026": -29},
    )
    frame = account_frame(stated, historical_columns(stated))
    assert frame["LTM:LTM_Q2_2026"][key] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(-29), note=history.PARTLY_STATED
    )


@pytest.mark.parametrize("labelled", [True, False])
def test_a_sparse_ltm_needs_its_fy_when_an_interim_is_stated(labelled: bool) -> None:
    regs = _halves() if labelled else _unlabelled(_halves())
    key = "acct:interest_paid_in_financing"

    def ltm(figures: Mapping[str, int]) -> Cell:
        case = _interest(regs, figures)
        return account_frame(case, historical_columns(case))["LTM:H1_2026"][key]

    partly = Cell(None, "COMPONENT_MISSING", note=history.PARTLY_STATED)
    # The interims are parts of the FY: without its row, never YTD - PYTD. A
    # stated PYTD inside an FY without a row leaves the FY's cover a gap.
    unspanned = Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    assert ltm({"H1_2026": -9, "H1_2025": -8}) == unspanned
    assert ltm({"H1_2025": -8}) == unspanned
    assert ltm({"H1_2026": -9}) == partly
    # Nothing stated over the twelve months: no row, not a missing component.
    assert ltm({"FY2024": -5}) == Cell(None, "NOT_SOURCED")
    assert ltm({"FY2025": -20}).value == Decimal(-20)
    assert ltm({"FY2025": -20, "H1_2026": -9, "H1_2025": -8}).value == Decimal(-21)


def test_partly_stated_reads_the_three_terms_of_a_rolled_ltm() -> None:
    """Every pattern of stated (S), no row (A) and missing otherwise (M) over
    FY, YTD and PYTD: only all stated, or the FY beside two interims without
    a row, is summed; a part missing otherwise is left to the sum."""
    regs = _halves()
    spec = next(s for s in periods._plan(regs) if s.column.kind == "LTM")
    year = next(s for s in periods._plan(regs) if s.column.kind == "FY")
    cells = {
        "S": Cell(Decimal(1)),
        "A": Cell(None, "NOT_SOURCED"),
        "M": Cell(None, "COMPONENT_MISSING"),
    }
    partly = {"ASS", "SAS", "SSA", "AAS", "ASA"}
    for pattern in (a + b + c for a in "SAM" for b in "SAM" for c in "SAM"):
        terms = [(cells[p], sign) for p, sign in zip(pattern, (1, 1, -1), strict=True)]
        expected = pattern in partly
        assert history._partly_stated(spec, terms) == expected, pattern
        assert not history._partly_stated(year, terms), pattern
    assert not history._partly_stated(spec, [(cells["S"], 1), (cells["A"], 1)])
