"""Statements: income to adjusted EBITDA, the cash-flow waterfall and add-backs."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext

from deploy_vii.model.frame import Cell
from deploy_vii.model.history import (
    OUTFLOW_METRICS,
)
from tests.product.model.credit_model_fixture import example_registers, with_figures
from tests.product.model.statements_cases import _cells, _columns, _equal, _frame, _values

_OUTFLOWS = (
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
)


def test_the_waterfall_reconciles_ffo_plus_wc_to_cfo_adjusted() -> None:
    regs = example_registers()
    q2 = _cells(regs, "Q2 26")
    assert _values(q2, "revenue", "cogs", "gross_profit", "da", "opex_ex_da") == (
        3008,
        -1263,
        1745,
        -310,
        -737,
    )
    assert _values(q2, "opex_total", "ebit", "ebitda", "adjusted_ebitda") == (
        -1047,
        698,
        1008,
        1053,
    )
    assert _values(q2, "operating_lease_cost", "adjusted_ebitdar") == (-28, 1081)
    assert _values(q2, "cash_interest", "lease_cash_not_in_ebitda", "cash_taxes") == (
        -214,
        -4,
        -42,
    )
    assert _values(q2, "other_operating", "ffo", "working_capital_change", "cfo_adjusted") == (
        -20,
        773,
        14,
        787,
    )
    assert _values(q2, "cfo_reported", "capex", "fcf") == (791, -380, 407)
    assert q2["other_operating"].basis == "CALCULATED"
    assert q2["other_operating"].note == "residual"
    assert q2["ebit"] == replace(q2["ebit"], stated=Decimal(698), note=None)
    assert q2["adjusted_ebitda"].stated == 1053
    assert q2["gross_profit"].stated is None
    ltm = _cells(regs, "LTM Q2 26")
    assert _values(ltm, "adjusted_ebitda", "other_operating", "ffo") == (
        4089,
        -80,
        2971,
    )
    assert _values(ltm, "cfo_adjusted", "fcf") == (3013, 1533)
    reconciled = 0
    for cells in _frame(regs).values():
        if cells["ffo"].value is not None:
            _equal(cells, ("ffo", "working_capital_change"), ("cfo_adjusted",))
            reconciled += 1
    assert reconciled == len(_columns(regs))


def test_ebitda_stated_differs_note() -> None:
    regs = with_figures(example_registers(), "Q2_2026", {"ebitda": Decimal(1000)})
    q2 = _cells(regs, "Q2 26")
    assert q2["ebitda"].value == 1008
    assert q2["ebitda"].stated == 1000
    assert q2["ebitda"].note == "differs from CP-1 stated"


def test_expense_metrics_written_positive_read_the_same() -> None:
    assert frozenset(_OUTFLOWS) == OUTFLOW_METRICS
    regs = example_registers()
    positive = replace(
        regs,
        accounts=tuple(
            replace(a, value=abs(a.value))
            if a.metric_id in _OUTFLOWS and a.value is not None
            else a
            for a in regs.accounts
        ),
    )
    # Every figure, CP-1's `acct:` cells included, reads one way.
    assert {
        column_id: {key: cell.value for key, cell in cells.items()}
        for column_id, cells in _frame(positive).items()
    } == {
        column_id: {key: cell.value for key, cell in cells.items()}
        for column_id, cells in _frame(regs).items()
    }


def test_cfo_adjusted_removes_lease_and_interest_classified_in_financing() -> None:
    for written in (Decimal(-10), Decimal(10)):
        regs = with_figures(
            example_registers(),
            "Q2_2026",
            {
                "interest_paid_in_financing": written,
                "lease_payments_in_financing": Decimal(-4),
            },
        )
        q2 = _cells(regs, "Q2 26")
        assert _values(q2, "cfo_reported", "lease_cash_not_in_ebitda") == (791, -4)
        assert q2["cfo_adjusted"].value == 791 - 4 - 10
        assert q2["cfo_reported"].basis == "REPORTED"


def test_ncf_equals_reported_net_cash_change() -> None:
    regs = example_registers()
    frame = _frame(regs)
    checked = 0
    for cells in frame.values():
        reported = cells["acct:net_cash_change"].value
        if reported is not None and cells["ncf"].value is not None:
            assert cells["ncf"].value == reported
            checked += 1
    assert checked >= 10
    q2 = _cells(regs, "Q2 26")
    assert _values(q2, "acquisitions_net", "debt_raised_net", "equity_raised_net", "dividends") == (
        0,
        -6,
        -343,
        0,
    )
    assert q2["other_investing_financing"].value == -8
    assert q2["other_investing_financing"].note == "residual"
    assert q2["other_investing_financing"].basis == "CALCULATED"
    assert _values(q2, "cash_opening", "ncf", "fx_and_other_cash", "cash_closing") == (
        950,
        50,
        0,
        1000,
    )
    assert q2["fx_and_other_cash"].note == "residual"
    bought = with_figures(
        regs,
        "Q2_2026",
        {"acquisitions_disposals": Decimal(-100), "dividends_paid": Decimal(10)},
    )
    acquired = _cells(bought, "Q2 26")
    assert _values(acquired, "acquisitions_net", "dividends", "other_investing_financing") == (
        -100,
        -10,
        102,
    )
    assert acquired["ncf"].value == 50
    assert _values(q2, "undrawn_rcf", "liquidity") == (2200, 3200)
    fy23 = _cells(regs, "FY23")
    assert fy23["cash_opening"] == Cell(None, "NOT_SOURCED")
    assert fy23["fx_and_other_cash"].reason == "COMPONENT_MISSING"
    ytd = _cells(regs, "YTD H1 26")
    assert _values(ytd, "cash_opening", "ncf", "cash_closing") == (980, 20, 1000)


def test_dio_and_dpo_are_null_when_cogs_is_not_negative() -> None:
    """Normalisation is sign-agnostic (cogs is read as -abs), so cogs written
    positive is negative too: cogs = 0 is the only null-denominator case."""
    regs = example_registers()
    q2 = _cells(regs, "Q2 26")
    assert q2["days"].value == 91
    with localcontext(prec=38):
        dso = Decimal(297) / Decimal(3008) * 91
        dio = Decimal(48) / Decimal(1263) * 91
        dpo = Decimal(443) / Decimal(1263) * 91
        ccc = dso + dio - dpo
    assert _values(q2, "dso", "dio", "dpo", "ccc") == (dso, dio, dpo, ccc)
    assert _values(q2, "accounts_receivable", "inventory", "accounts_payable") == (
        297,
        48,
        443,
    )
    zero = _cells(with_figures(regs, "Q2_2026", {"cogs": Decimal(0)}), "Q2 26")
    assert zero["dio"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    assert zero["dpo"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    assert zero["ccc"].reason == "COMPONENT_MISSING"
    assert zero["dso"].value == q2["dso"].value
    no_revenue = _cells(with_figures(regs, "Q2_2026", {"revenue": Decimal(0)}), "Q2 26")
    assert no_revenue["dso"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")


def test_exclude_unrealised_leaves_unrealised_and_not_stated_addbacks_out() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        addbacks=tuple(
            replace(b, realization_status="NOT_STATED")
            if b.addback_id == "transaction_costs"
            else b
            for b in regs.addbacks
        ),
    )
    kept = _cells(regs, "Q2 26")
    assert kept["adjusted_ebitda"].value == 1053
    assert kept["addback:run_rate_cost_savings"].note is None
    q2 = _cells(regs, "Q2 26", exclude=True)
    assert q2["adjusted_ebitda"].value == 1008 + 8 + 24
    assert q2["adjusted_ebitda"].stated == 1053
    assert q2["adjusted_ebitda"].note is None
    assert q2["addback:run_rate_cost_savings"].value == 10
    assert q2["addback:run_rate_cost_savings"].note == "excluded"
    assert q2["addback:transaction_costs"].note == "excluded"
    assert q2["addback:restructuring"].note is None
    assert q2["adjusted_ebitdar"].value == 1008 + 8 + 24 + 28
    ltm = _cells(regs, "LTM Q2 26", exclude=True)
    assert ltm["adjusted_ebitda"].value == 3904 + 32 + 92
