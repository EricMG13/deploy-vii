"""Statements: absent rows, sparse items, foreign facilities and PF adjustments."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from deploy_vii.model.frame import Cell
from deploy_vii.model.history import (
    PARTLY_STATED,
)
from deploy_vii.model.registers import Cp1Registers
from deploy_vii.model.statements import (
    UNREALISED,
    excluded_addbacks,
    pro_forma_column,
)
from tests.product.model.credit_model_fixture import example_registers, with_figures
from tests.product.model.statements_cases import _cells, _columns, _equal, _frame, _values, _without


def _without_addback(regs: Cp1Registers, addback_id: str, *period_ids: str) -> Cp1Registers:
    return replace(
        regs,
        addbacks=tuple(
            b for b in regs.addbacks if b.addback_id != addback_id or b.period_id not in period_ids
        ),
    )


def test_an_addback_without_a_row_contributes_zero_and_a_null_one_is_missing() -> None:
    regs = _without_addback(example_registers(), "transaction_costs", "Q2_2026")
    frame = _frame(regs)
    by_label = _columns(regs)
    q2 = frame[by_label["Q2 26"].column_id]
    assert q2["addback:transaction_costs"] == Cell(None, "NOT_SOURCED")
    assert q2["adjusted_ebitda"].value == 1053 - 3
    assert _values(q2, "other_operating", "ffo") == (-20 + 3, 773)
    assert q2["adjusted_ebitdar"].value == 1050 + 28
    # CP-1's H1 2026 row (6) stands for the YTD and the LTM built on it.
    ytd = frame[by_label["YTD H1 26"].column_id]
    assert ytd["addback:transaction_costs"].value == 6
    assert ytd["adjusted_ebitda"].value == 2062
    assert frame[by_label["LTM Q2 26"].column_id]["adjusted_ebitda"].value == 4089
    nulled = replace(
        regs,
        addbacks=tuple(
            replace(b, value=None)
            if (b.addback_id, b.period_id) == ("restructuring", "Q1_2026")
            else b
            for b in regs.addbacks
            # without H1's own row, the YTD is built from the null Q1 row
            if (b.addback_id, b.period_id) != ("restructuring", "H1_2026")
        ),
    )
    ytd_null = _cells(nulled, "YTD H1 26")
    assert ytd_null["addback:restructuring"].reason == "COMPONENT_MISSING"
    assert ytd_null["adjusted_ebitda"].reason == "COMPONENT_MISSING"


def test_financing_lease_and_interest_without_rows_count_zero_in_cfo_adjusted() -> None:
    regs = example_registers()
    one = _cells(_without(regs, "interest_paid_in_financing", "Q2_2026"), "Q2 26")
    assert one["cfo_adjusted"] == replace(
        one["cfo_adjusted"], value=Decimal(787), note="not stated, treated as zero"
    )
    assert one["ffo"].value == 773
    both = _cells(
        _without(
            _without(regs, "interest_paid_in_financing", "Q2_2026"),
            "lease_payments_in_financing",
            "Q2_2026",
        ),
        "Q2 26",
    )
    assert both["lease_cash_not_in_ebitda"] == Cell(None, "NOT_SOURCED")
    assert both["cfo_adjusted"].value == 791
    assert both["cfo_adjusted"].note == "not stated, treated as zero"
    assert both["ffo"].value == 791 - 14
    _equal(both, ("ffo", "working_capital_change"), ("cfo_adjusted",))
    assert _cells(regs, "Q2 26")["cfo_adjusted"].note is None
    nulled = replace(
        regs,
        accounts=tuple(
            replace(a, value=None)
            if (a.metric_id, a.period_id) == ("lease_payments_in_financing", "Q2_2026")
            else a
            for a in regs.accounts
        ),
    )
    missing = _cells(nulled, "Q2 26")
    assert missing["lease_cash_not_in_ebitda"] == Cell(None, "NOT_STATED")
    assert missing["cfo_adjusted"] == Cell(None, "COMPONENT_MISSING")


def test_a_pro_forma_ebitda_adjustment_adds_to_ebitda_and_adjusted_ebitda() -> None:
    regs = example_registers()
    first = regs.pro_forma[0]
    regs = replace(
        regs,
        pro_forma=(replace(first, adjustment_id="synergy", metric_id="ebitda"),),
    )
    ltm = _columns(regs)["LTM Q2 26"]
    made = pro_forma_column(regs, ltm, _frame(regs))
    assert made is not None
    pf = made[1]["PF:LTM_Q2_2026"]
    assert _values(pf, "ebitda", "adjusted_ebitda", "adjusted_ebitdar") == (
        3904 + 45,
        4089 + 45,
        4089 + 45 + 112,
    )


def test_exclude_unrealised_compares_stated_where_nothing_was_excluded() -> None:
    regs = with_figures(example_registers(), "Q1_2024", {"adjusted_ebitda": Decimal(900)})
    q1 = _cells(regs, "Q1 24", exclude=True)
    assert q1["addback:run_rate_cost_savings"].value == 0
    assert q1["adjusted_ebitda"].value == 946
    assert q1["adjusted_ebitda"].note == "differs from CP-1 stated"


def test_a_sparse_addback_and_financing_line_resolve_bottom_up() -> None:
    regs = example_registers()
    kept = [b for b in regs.addbacks if b.addback_id != "transaction_costs"]
    model = next(b for b in regs.addbacks if b.addback_id == "transaction_costs")
    probe = replace(
        regs,
        addbacks=(
            *kept,
            replace(model, period_id="Q1_2025", value=Decimal(3)),
            replace(model, period_id="H1_2025", value=Decimal(3)),
        ),
    )
    ltm = _cells(probe, "LTM Q2 26")
    # A PYTD row beside no YTD row: the add-back's LTM is not built, and the
    # adjusted EBITDA that adds it is missing too.
    assert ltm["addback:transaction_costs"] == Cell(None, "COMPONENT_MISSING", note=PARTLY_STATED)
    assert ltm["adjusted_ebitda"].value is None
    assert ltm["ebitda"].value == 3904
    lease = _without(regs, "lease_payments_in_financing", "Q2_2026", "H1_2026")
    ytd = _cells(lease, "YTD H1 26")
    assert ytd["cfo_adjusted"].value == 1504 - 4
    assert ytd["cfo_adjusted"].note is None


def test_an_all_absent_financing_line_with_a_stated_figure_counts_zero() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            replace(a, value=Decimal(-5)) if a.metric_id == "interest_paid_in_financing" else a
            for a in regs.accounts
            if a.metric_id != "interest_paid_in_financing" or a.period_id == "LTM_Q2_2026"
        ),
    )
    ltm = _cells(regs, "LTM Q2 26")
    assert ltm["acct:interest_paid_in_financing"] == Cell(None, "NOT_SOURCED", stated=Decimal(-5))
    assert ltm["cfo_adjusted"].value == 3029 - 16
    assert ltm["cfo_adjusted"].note == "not stated, treated as zero"


def test_an_excluded_addback_absent_on_a_column_leaves_nothing_out() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        addbacks=tuple(
            b
            for b in regs.addbacks
            if b.addback_id != "run_rate_cost_savings" or b.period_id == "LTM_Q2_2026"
        ),
    )
    regs = with_figures(regs, "LTM_Q2_2026", {"adjusted_ebitda": Decimal(4000)})
    ltm = _cells(regs, "LTM Q2 26", exclude=True)
    # Deploy VI A14: stated only for the LTM, it counts there (it is excluded
    # from adjusted EBITDA, so that is unchanged).
    assert ltm["addback:run_rate_cost_savings"].value == 40
    assert ltm["addback:run_rate_cost_savings"].reason is None
    assert ltm["adjusted_ebitda"].value == 3904 + 32 + 92 + 21
    # The stated figure (4000) includes the 40 it left out, so it is not compared.
    assert ltm["adjusted_ebitda"].note is None
    assert ltm["adjusted_ebitda"].stated == 4000


_EXCLUDES_FOREIGN = "excludes facility in another currency"


def _pf(regs: Cp1Registers) -> dict[str, Cell]:
    ltm = _columns(regs)["LTM Q2 26"]
    made = pro_forma_column(regs, ltm, _frame(regs))
    assert made is not None
    return made[1]["PF:LTM_Q2_2026"]


def test_a_foreign_facility_is_noted_on_every_debt_balance_it_leaves() -> None:
    regs = example_registers()
    eur = replace(
        regs,
        facilities=tuple(
            replace(f, currency="EUR") if f.facility_id == "sun29" else f for f in regs.facilities
        ),
    )
    ltm = _cells(eur, "LTM Q2 26")
    for key in ("net_debt", "lease_adjusted_debt", "lease_adjusted_net_debt"):
        assert ltm[key].note == _EXCLUDES_FOREIGN, key
    assert ltm["liquidity"].note is None
    pf = _pf(eur)
    for key in ("total_debt", "net_debt", "lease_adjusted_debt"):
        assert pf[key].note == _EXCLUDES_FOREIGN, key
    clean = _cells(regs, "LTM Q2 26")
    for key in ("net_debt", "lease_adjusted_debt", "lease_adjusted_net_debt"):
        assert clean[key].note is None, key


def _pf_interest(regs: Cp1Registers, value: Decimal) -> Cp1Registers:
    """`regs` with the PF cash-interest adjustment set to `value`."""
    return replace(
        regs,
        pro_forma=tuple(
            replace(a, value=value) if a.metric_id == "cash_interest_paid" else a
            for a in regs.pro_forma
        ),
    )


def test_a_pf_adjustment_is_a_change_and_keeps_cp1s_sign() -> None:
    # A refinancing that cuts interest by 30 adds +30 to the (negative) line.
    pf = _pf(_pf_interest(example_registers(), Decimal(30)))

    assert pf["pf:silverlake_interest"].value == 30
    assert pf["pf:silverlake_interest"].note is None
    assert pf["cash_interest"].value == -862 + 30
    assert pf["cash_interest"].note is None
    unchanged = _pf(example_registers())
    assert unchanged["pf:silverlake_interest"].value == -42
    assert unchanged["cash_interest"].value == -862 - 42
    # Cash keeps its sign too.
    assert unchanged["pf:silverlake_cash"].value == -50
    # Read exactly, beyond the context's 38 digits.
    long = Decimal("-42.123456789012345678901234567890123456789")
    exact = _pf(_pf_interest(example_registers(), long))
    assert exact["pf:silverlake_interest"].value == long


def test_a_pf_facility_with_no_ltm_row_starts_from_zero() -> None:
    regs = example_registers()
    ltm = _columns(regs)["LTM Q2 26"]
    frame = _frame(regs)
    frame[ltm.column_id]["fac:ssn33"] = Cell(None, "NOT_SOURCED")
    first = regs.pro_forma[0]
    regs = replace(
        regs,
        pro_forma=(
            *regs.pro_forma,
            replace(first, adjustment_id="ssn33", metric_id="facility:ssn33"),
        ),
    )
    made = pro_forma_column(regs, ltm, frame)
    assert made is not None
    pf = made[1]["PF:LTM_Q2_2026"]

    assert pf["fac:ssn33"] == Cell(Decimal(45), basis="PRO_FORMA", sources=pf["pf:ssn33"].sources)
    assert pf["total_debt"].value == 14706 + 45
    # A line other than a facility's without an LTM figure stays without one.
    frame[ltm.column_id]["revenue"] = Cell(None, "NOT_SOURCED")
    revenue = replace(first, adjustment_id="rev", metric_id="revenue")
    made = pro_forma_column(replace(regs, pro_forma=(revenue,)), ltm, frame)
    assert made is not None
    assert made[1]["PF:LTM_Q2_2026"]["revenue"] == Cell(None, "COMPONENT_MISSING")


def test_the_pf_debt_roll_forward_opens_at_the_ltm_and_closes_with_the_pf() -> None:
    regs = example_registers()
    ltm = _cells(regs, "LTM Q2 26")
    pf = _pf(regs)

    assert pf["debt_opening"] == ltm["debt_opening"]
    assert pf["debt_non_cash"] == ltm["debt_non_cash"]
    assert pf["debt_closing"].value == pf["total_debt"].value == 14706


def test_an_outflow_of_zero_is_no_negative_zero() -> None:
    regs = with_figures(example_registers(), "FY2025", {"dividends_paid": Decimal(0)})
    value = _cells(regs, "FY25")["dividends"].value

    assert value == 0
    assert value is not None and not value.is_signed()


def test_excluded_addbacks_are_those_with_any_row_unrealised_or_not_stated() -> None:
    regs = example_registers()
    assert excluded_addbacks(regs, exclude_unrealised=False) == frozenset()
    statuses: dict[str, set[str]] = {b.addback_id: set() for b in regs.addbacks}
    for b in regs.addbacks:
        statuses[b.addback_id].add(b.realization_status)
    expected = {a for a, seen in statuses.items() if seen & UNREALISED}
    assert expected
    assert excluded_addbacks(regs, exclude_unrealised=True) == expected
    first = regs.addbacks[0]
    one_row = replace(
        regs,
        addbacks=tuple(
            replace(b, realization_status="NOT_STATED") if b is first else b for b in regs.addbacks
        ),
    )
    assert first.addback_id in excluded_addbacks(one_row, exclude_unrealised=True)
    assert UNREALISED == {"UNREALIZED", "NOT_STATED"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal(0), Decimal(0)),
        (Decimal("-0"), Decimal(0)),
        (Decimal("0.5"), Decimal("0.5")),
        (Decimal(-1), Decimal(-1)),
    ],
)
def test_a_pf_adjustment_is_never_flipped_and_never_a_negative_zero(
    value: Decimal, expected: Decimal
) -> None:
    pf = _pf(_pf_interest(example_registers(), value))
    cell = pf["pf:silverlake_interest"]

    assert cell.value is not None
    assert (cell.value, cell.value.is_signed(), cell.note) == (
        expected,
        expected < 0,
        None,
    )
    total = pf["cash_interest"].value
    assert total is not None and str(total) != "-0"
