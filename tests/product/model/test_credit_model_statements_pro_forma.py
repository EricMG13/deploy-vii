"""Statements: pro forma columns, any consistent accounts reconciling, sources and
stated figures."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.model.frame import Cell, Column, SourceRef
from deploy_vii.model.history import (
    account_frame,
    historical_columns,
)
from deploy_vii.model.statements import (
    pro_forma_column,
    statement_frame,
)
from tests.product.model.credit_model_fixture import example_registers, with_figures
from tests.product.model.statements_cases import _cells, _columns, _equal, _frame, _values, _without

_WATERFALL = (
    "ffo",
    "working_capital_change",
    "cfo_adjusted",
    "cfo_reported",
    "capex",
    "fcf",
    "acquisitions_net",
    "debt_raised_net",
    "equity_raised_net",
    "dividends",
    "other_investing_financing",
    "ncf",
)


def test_adjusted_ebitda_needs_every_addback() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        addbacks=tuple(
            replace(b, value=None)
            if (b.addback_id, b.period_id) == ("restructuring", "Q2_2026")
            else b
            for b in regs.addbacks
        ),
    )
    q2 = _cells(regs, "Q2 26")
    assert q2["adjusted_ebitda"] == Cell(None, "COMPONENT_MISSING", stated=Decimal(1053))
    assert q2["ffo"].reason == "COMPONENT_MISSING"


def test_a_missing_account_is_not_sourced_and_its_lines_component_missing() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if (a.metric_id, a.period_id) != ("capex_and_intangible_investment", "Q2_2026")
        ),
    )
    q2 = _cells(regs, "Q2 26")
    assert q2["capex"] == Cell(None, "NOT_SOURCED")
    assert q2["fcf"].reason == "COMPONENT_MISSING"
    assert q2["other_investing_financing"].reason == "COMPONENT_MISSING"
    assert q2["ffo"].value == 773


def test_pro_forma_adds_each_adjustment_once_and_blanks_the_waterfall() -> None:
    regs = example_registers()
    columns = _columns(regs)
    ltm = columns["LTM Q2 26"]
    frame = _frame(regs)
    made = pro_forma_column(regs, ltm, frame)
    assert made is not None
    column, pf_frame = made
    assert column == Column(
        column_id="PF:LTM_Q2_2026",
        kind="PF_LTM",
        label="PF-LTM",
        period_id="LTM_Q2_2026",
        fiscal_year=ltm.fiscal_year,
        end_date=ltm.end_date,
        days=ltm.days,
        case=None,
    )
    assert set(pf_frame) == {column.column_id}
    pf = pf_frame[column.column_id]
    base = frame[ltm.column_id]
    assert set(pf) == set(base) | {
        "pf:silverlake_ebitda",
        "pf:silverlake_interest",
        "pf:silverlake_cash",
        "pf:silverlake_notes",
    }
    assert pf["pf:silverlake_notes"].value == 600
    assert pf["pf:silverlake_notes"].basis == "PRO_FORMA"
    assert pf["pf:silverlake_notes"].sources[0].source_id == "S12"
    assert _values(pf, "adjusted_ebitda", "cash_interest", "cash_closing") == (
        4134,
        -904,
        950,
    )
    assert pf["adjusted_ebitda"].basis == "PRO_FORMA"
    assert pf["adjusted_ebitda"].stated is None
    assert pf["adjusted_ebitda"].sources[-1].source_id == "S12"
    assert _values(pf, "total_debt", "fac:ssn31", "secured_debt") == (
        14706,
        1600,
        5916,
    )
    assert _values(pf, "net_debt", "liquidity", "lease_adjusted_debt") == (
        14706 - 950,
        950 + 2200,
        14706,
    )
    assert pf["lease_adjusted_net_debt"].value == 14706 - 950
    assert pf["adjusted_ebitdar"].value == 4134 + 112
    assert pf["revenue"] == base["revenue"]
    assert pf["ebitda"] == base["ebitda"]
    for key in (
        *_WATERFALL,
        "other_operating",
        "cash_opening",
        "fx_and_other_cash",
        "accounts_receivable",
        "inventory",
        "accounts_payable",
        "days",
        "dso",
        "dio",
        "dpo",
        "ccc",
        *(key for key in base if key.startswith("kpi:")),
    ):
        assert pf[key] == Cell(None, "NOT_APPLICABLE"), key
    assert "kpi:lv_room_nights" in base
    for key in ("lease_cash_not_in_ebitda", "cash_taxes", "bu:digital"):
        assert pf[key] == base[key], key


def test_pro_forma_revenue_and_total_debt_adjustments() -> None:
    regs = example_registers()
    extra = replace(regs.pro_forma[0], adjustment_id="silverlake_revenue", metric_id="revenue")
    debt = replace(regs.pro_forma[0], adjustment_id="other_debt", metric_id="total_debt")
    regs = replace(regs, pro_forma=(*regs.pro_forma, extra, debt))
    ltm = _columns(regs)["LTM Q2 26"]
    made = pro_forma_column(regs, ltm, _frame(regs))
    assert made is not None
    pf = made[1]["PF:LTM_Q2_2026"]
    assert pf["revenue"].value == 11654 + 45
    assert pf["total_debt"].value == 14706 + 45
    assert pf["secured_debt"].value == 5916


def test_pro_forma_is_none_without_adjustments_for_the_ltm() -> None:
    regs = example_registers()
    ltm = _columns(regs)["LTM Q2 26"]
    assert pro_forma_column(replace(regs, pro_forma=()), ltm, _frame(regs)) is None
    other = replace(
        regs,
        pro_forma=tuple(replace(a, period_id="LTM_Q4_2025") for a in regs.pro_forma),
    )
    assert pro_forma_column(other, ltm, _frame(regs)) is None


_FIGURE = st.decimals(
    min_value=-(10**6), max_value=10**6, places=2, allow_nan=False, allow_infinity=False
)


_ACCOUNTS = (
    "revenue",
    "cogs",
    "opex_including_da",
    "depreciation_amortization",
    "operating_lease_cost",
    "cash_interest_paid",
    "cash_taxes_paid",
    "working_capital_change",
    "cfo_ncfo",
    "lease_payments_in_financing",
    "interest_paid_in_financing",
    "capex_and_intangible_investment",
    "acquisitions_disposals",
    "net_debt_issue_repay",
    "net_equity_issue_repay",
    "dividends_paid",
    "net_cash_change",
    "cash_and_equivalents",
    "rcf_commitment",
    "rcf_drawn",
)


_BASE = example_registers()


@settings(max_examples=40, deadline=None)
@given(st.fixed_dictionaries({metric: _FIGURE for metric in _ACCOUNTS}))
def test_every_bridge_reconciles_for_any_consistent_accounts(
    figures: dict[str, Decimal],
) -> None:
    regs = with_figures(_BASE, "Q2_2026", figures)
    frame = _frame(regs)
    for label in ("Q2 26", "LTM Q2 26", "YTD H1 26"):
        cells = frame[_columns(regs)[label].column_id]
        _equal(cells, ("gross_profit",), ("revenue", "cogs"))
        _equal(cells, ("ebit",), ("gross_profit", "opex_total"))
        _equal(cells, ("ebitda", "da"), ("ebit",))
        _equal(cells, ("opex_ex_da", "da"), ("opex_total",))
        _equal(cells, ("ffo", "working_capital_change"), ("cfo_adjusted",))
        _equal(cells, ("fcf",), ("cfo_adjusted", "capex"))
        _equal(
            cells,
            ("ncf",),
            (
                "fcf",
                "acquisitions_net",
                "debt_raised_net",
                "equity_raised_net",
                "dividends",
                "other_investing_financing",
            ),
        )
        _equal(cells, ("ncf",), ("acct:net_cash_change",))
        _equal(cells, ("cash_opening", "ncf", "fx_and_other_cash"), ("cash_closing",))
        _equal(
            cells,
            ("debt_opening", "debt_raised_net", "debt_non_cash"),
            ("debt_closing",),
        )
        _equal(cells, ("debt_closing",), ("total_debt",))
        _equal(cells, ("net_debt", "cash_closing"), ("total_debt",))
        _equal(cells, ("liquidity",), ("cash_closing", "undrawn_rcf"))
        _equal(cells, ("adjusted_ebitdar", "operating_lease_cost"), ("adjusted_ebitda",))
        raw = cells["acct:interest_paid_in_financing"].value
        assert raw is not None
        lease = cells["lease_cash_not_in_ebitda"].value
        assert lease is not None and lease == -abs(lease)
        reported, adjusted = cells["cfo_reported"].value, cells["cfo_adjusted"].value
        assert reported is not None
        assert adjusted == reported + lease - abs(raw)
        addbacks = tuple(key for key in cells if key.startswith("addback:"))
        _equal(cells, ("adjusted_ebitda",), ("ebitda", *addbacks))
        _equal(cells, ("undrawn_rcf", "acct:rcf_drawn"), ("acct:rcf_commitment",))
        for key in ("cogs", "da", "cash_interest", "cash_taxes", "capex"):
            value = cells[key].value
            assert value is not None and value <= 0, key


def test_pro_forma_new_facility_unknown_metric_and_a_missing_line() -> None:
    regs = example_registers()
    first = regs.pro_forma[0]
    regs = replace(
        regs,
        pro_forma=(
            *regs.pro_forma,
            replace(first, adjustment_id="newco", metric_id="facility:newco"),
            replace(first, adjustment_id="capex", metric_id="capex", source=None),
        ),
    )
    ltm = _columns(regs)["LTM Q2 26"]
    frame = _frame(regs)
    frame[ltm.column_id]["cash_closing"] = Cell(None, "NOT_SOURCED")
    made = pro_forma_column(regs, ltm, frame)
    assert made is not None
    pf = made[1]["PF:LTM_Q2_2026"]
    assert pf["fac:newco"].value == 45
    assert pf["fac:newco"].basis == "PRO_FORMA"
    assert pf["total_debt"].value == 14706 + 45
    assert pf["secured_debt"].value == 5916
    assert pf["pf:capex"] == Cell(Decimal(45), basis="PRO_FORMA")
    assert pf["capex"] == Cell(None, "NOT_APPLICABLE")
    assert pf["cash_closing"] == Cell(None, "COMPONENT_MISSING")
    assert pf["net_debt"] == Cell(None, "COMPONENT_MISSING")
    assert pf["liquidity"] == Cell(None, "COMPONENT_MISSING")
    assert set(pf) == set(frame[ltm.column_id]) | {
        "fac:newco",
        "pf:newco",
        "pf:capex",
        *(f"pf:{a.adjustment_id}" for a in example_registers().pro_forma),
    }


def test_a_column_without_days_has_no_opening_balances_or_days_ratios() -> None:
    regs = example_registers()
    columns = tuple(
        replace(column, days=None) if column.label == "Q2 26" else column
        for column in historical_columns(regs)
    )
    q2_id = _columns(regs)["Q2 26"].column_id
    frame = statement_frame(account_frame(regs, columns), columns, regs)
    q2 = frame[q2_id]
    assert q2["days"] == Cell(None, "NOT_SOURCED")
    assert q2["cash_opening"] == Cell(None, "NOT_SOURCED")
    assert q2["debt_opening"] == Cell(None, "NOT_SOURCED")
    for key in ("dso", "dio", "dpo", "ccc", "fx_and_other_cash", "debt_non_cash"):
        assert q2[key].reason == "COMPONENT_MISSING", key


def test_lines_keep_their_sources_and_cp1_stated_figures() -> None:
    regs = example_registers()
    q2 = _cells(regs, "Q2 26")
    assert q2["gross_profit"].sources == (
        *q2["revenue"].sources,
        *q2["cogs"].sources,
    )
    assert q2["cash_opening"] == Cell(
        Decimal(950),
        basis="REPORTED",
        sources=(SourceRef("S10", "10-Q Q1 2026, Item 1", "950"),),
    )
    assert q2["days"] == Cell(Decimal(91), basis="CALCULATED")
    assert q2["dso"] == Cell(
        q2["dso"].value,
        basis="CALCULATED",
        sources=(*q2["accounts_receivable"].sources, *q2["revenue"].sources),
    )
    # CP-1's H1 figure written positive is a negative `stated`.
    positive = with_figures(regs, "H1_2026", {"cogs": Decimal(2471)})
    assert _cells(positive, "YTD H1 26")["cogs"].stated == -2471
    # CP-1's EBITDA component missing: the host's EBITDA keeps CP-1's H1.
    gap = _without(regs, "ebitda", "Q1_2026")
    ytd = _cells(gap, "YTD H1 26")
    assert ytd["ebitda"].value == 1972
    assert ytd["ebitda"].stated == 1972
    absent = _cells(_without(regs, "operating_lease_cost"), "Q2 26")
    assert absent["operating_lease_cost"] == Cell(None, "NOT_SOURCED")
    assert absent["adjusted_ebitdar"].reason == "COMPONENT_MISSING"


def test_adjusted_ebitda_differs_note_unless_unrealised_are_excluded() -> None:
    regs = with_figures(example_registers(), "Q2_2026", {"adjusted_ebitda": Decimal(1000)})
    columns = historical_columns(regs)
    accounts = account_frame(regs, columns)
    q2_id = _columns(regs)["Q2 26"].column_id
    default = statement_frame(accounts, columns, regs)[q2_id]
    assert default["adjusted_ebitda"].value == 1053
    assert default["adjusted_ebitda"].note == "differs from CP-1 stated"
    assert default["addback:run_rate_cost_savings"].note is None
    excluded = statement_frame(accounts, columns, regs, True)[q2_id]
    assert excluded["adjusted_ebitda"].stated == 1000
    assert excluded["adjusted_ebitda"].note is None


def test_days_ratios_divide_by_any_positive_flow_and_need_the_balance() -> None:
    regs = example_registers()
    half = _cells(with_figures(regs, "Q2_2026", {"revenue": Decimal("0.5")}), "Q2 26")
    assert half["dso"].value == Decimal(297) / Decimal("0.5") * 91
    ending = ("Q2_2026", "H1_2026", "LTM_Q2_2026")
    bare = _cells(_without(regs, "inventory", *ending), "Q2 26")
    assert bare["inventory"] == Cell(None, "NOT_SOURCED")
    assert bare["dio"] == Cell(None, "COMPONENT_MISSING")
    assert bare["dpo"].value is not None


def test_pro_forma_keeps_a_foreign_note_drops_a_differs_note_and_is_exact() -> None:
    regs = example_registers()
    rows = [replace(f, currency="EUR") if f.facility_id == "sun32" else f for f in regs.facilities]
    first = regs.pro_forma[0]
    regs = replace(
        regs,
        facilities=tuple(rows),
        pro_forma=(
            replace(first, value=Decimal("0.1234567890123456789012345678901")),
            replace(first, adjustment_id="eur", metric_id="facility:sun32"),
        ),
    )
    regs = with_figures(regs, "LTM_Q2_2026", {"adjusted_ebitda": Decimal(4000)})
    ltm = _columns(regs)["LTM Q2 26"]
    frame = _frame(regs)
    assert frame[ltm.column_id]["adjusted_ebitda"].note == "differs from CP-1 stated"
    made = pro_forma_column(regs, ltm, frame)
    assert made is not None
    pf = made[1]["PF:LTM_Q2_2026"]
    assert pf["adjusted_ebitda"].value == Decimal("4089.1234567890123456789012345678901")
    assert pf["adjusted_ebitda"].note is None
    assert pf["adjusted_ebitdar"].basis == "PRO_FORMA"
    assert pf["fac:sun32"].value == 3500 + 45
    assert pf["fac:sun32"].note == "different currency, not converted"
    assert pf["total_debt"] == frame[ltm.column_id]["total_debt"]
    assert pf["net_debt"].basis == "PRO_FORMA"
    assert pf["net_debt"].value == frame[ltm.column_id]["net_debt"].value


def _revolver_pf(drawn: Decimal, movement: Decimal) -> tuple[dict[str, Cell], dict[str, Cell]]:
    """The LTM and PF-LTM cells for a revolver drawn `drawn` with `movement`
    pro forma drawings (negative repays)."""
    regs = with_figures(example_registers(), "LTM_Q2_2026", {"rcf_drawn": drawn})
    row = replace(regs.pro_forma[0], adjustment_id="rcf_move", metric_id="facility:rcf")
    regs = replace(regs, pro_forma=(replace(row, value=movement),))
    ltm = _columns(regs)["LTM Q2 26"]
    frame = _frame(regs)
    made = pro_forma_column(regs, ltm, frame)
    assert made is not None
    return frame[ltm.column_id], made[1]["PF:LTM_Q2_2026"]


def test_pf_revolver_repayment_restores_undrawn_and_liquidity() -> None:
    base, pf = _revolver_pf(Decimal(120), Decimal(-120))
    assert _values(base, "undrawn_rcf") == (2080,)
    assert _values(pf, "undrawn_rcf") == (2200,)
    assert pf["undrawn_rcf"].basis == "PRO_FORMA"
    for cells, undrawn in ((pf, 2200), (base, 2080)):
        cash = cells["cash_closing"].value
        assert cash is not None
        assert cells["liquidity"].value == cash + undrawn


def test_pf_non_revolver_facility_leaves_undrawn() -> None:
    regs = example_registers()
    ltm = _columns(regs)["LTM Q2 26"]
    frame = _frame(regs)
    made = pro_forma_column(regs, ltm, frame)
    assert made is not None
    assert made[1]["PF:LTM_Q2_2026"]["undrawn_rcf"] == frame[ltm.column_id]["undrawn_rcf"]


@settings(max_examples=60, deadline=None)
@given(drawn=st.decimals(0, 2200, places=2), movement=st.decimals(-2200, 2200, places=2))
def test_pf_undrawn_is_commitment_less_pro_forma_drawn(drawn: Decimal, movement: Decimal) -> None:
    _, pf = _revolver_pf(drawn, movement)
    assert pf["undrawn_rcf"].value == Decimal(2200) - (drawn + movement)


def test_pf_revolver_type_spellings_and_drawings_lower_undrawn() -> None:
    regs = with_figures(example_registers(), "LTM_Q2_2026", {"rcf_drawn": Decimal(0)})
    for spelling in ("Revolver", "rcf", "REVOLVING CREDIT FACILITY"):
        typed = replace(
            regs,
            facilities=tuple(replace(f, facility_type=spelling) for f in regs.facilities),
            pro_forma=(replace(regs.pro_forma[0], metric_id="facility:rcf", value=Decimal(50)),),
        )
        ltm = _columns(typed)["LTM Q2 26"]
        made = pro_forma_column(typed, ltm, _frame(typed))
        assert made is not None
        assert made[1]["PF:LTM_Q2_2026"]["undrawn_rcf"].value == 2150
