"""Debt totals and roll-forward against the statement frame (needs
`deploy_vii.model.statements`)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from deploy_vii.model.frame import Cell
from deploy_vii.model.history import account_frame, historical_columns
from deploy_vii.model.statements import statement_frame
from tests.product.model.credit_model_fixture import example_registers, with_figures
from tests.product.model.debt_cases import _columns, _debt, _row, _with_facilities


def test_total_debt_excludes_operating_leases_and_includes_finance_leases() -> None:
    regs = example_registers()
    finl = _row(regs, "finl")
    leases = replace(
        finl,
        facility_id="opl",
        facility_name="Operating lease liabilities",
        facility_type="OPERATING_LEASE",
        lease_classification="OPERATING_LEASE",
        period_id="Q2_2026",
        carrying_value=Decimal(500),
        source=None,
    )
    euro = replace(
        _row(regs, "sun29"),
        facility_id="eur",
        facility_name="EUR notes",
        currency="EUR",
        period_id="Q2_2026",
        carrying_value=Decimal(300),
        source=None,
    )
    regs = _with_facilities(regs, leases, euro)
    columns = historical_columns(regs)
    q2_id = _columns(regs)["Q2 26"].column_id
    q2 = _debt(regs, columns)[q2_id]
    assert q2["total_debt"].value == 14106
    assert q2["total_debt"].stated == 13846
    # The EUR notes are left out of it, said so (H6).
    assert q2["total_debt"].note == "excludes facility in another currency"
    assert q2["total_debt"].basis == "CALCULATED"
    assert q2["lease_liabilities"].value == 500
    assert q2["secured_debt"].value == 5316
    assert q2["fac:eur"] == Cell(
        Decimal(300), basis="REPORTED", note="different currency, not converted"
    )
    assert q2["fac:opl"].value == 500
    assert q2["fac:tlb"].note is None
    assert q2["undrawn_rcf"].value == 2200
    accounts = account_frame(regs, columns)
    statement = statement_frame(accounts, columns, regs)[q2_id]
    assert statement["lease_adjusted_debt"].value == 14606
    assert statement["net_debt"].value == 14106 - 1000
    assert statement["lease_adjusted_net_debt"].value == 14606 - 1000
    assert statement["fac:eur"].note == "different currency, not converted"
    stated = with_figures(regs, "Q2_2026", {"total_debt": Decimal(13800)})
    differs = _debt(stated, columns)[q2_id]["total_debt"]
    assert differs.note == ("differs from CP-1 stated; excludes facility in another currency")
    assert differs.stated == 13800


def test_debt_roll_forward_closes_to_the_stack() -> None:
    regs = example_registers()
    columns = historical_columns(regs)
    frame = _debt(regs, columns)
    by_label = _columns(regs)
    q2 = frame[by_label["Q2 26"].column_id]
    assert q2["debt_opening"].value == 14112
    assert q2["debt_non_cash"].value == 0
    assert q2["debt_closing"].value == 14106
    assert q2["debt_non_cash"].note == "residual"
    ltm = frame[by_label["LTM Q2 26"].column_id]
    assert ltm["debt_opening"].value == 14130
    assert ltm["debt_closing"].value == 14106
    assert ltm["debt_non_cash"].value == 0
    fy23 = frame[by_label["FY23"].column_id]
    assert fy23["debt_opening"] == Cell(None, "NOT_SOURCED")
    assert fy23["debt_non_cash"].reason == "COMPONENT_MISSING"
    accounts = account_frame(regs, columns)
    statement = statement_frame(accounts, columns, regs)
    closed = 0
    for cells in statement.values():
        opening, raised, other, closing = (
            cells[key].value
            for key in (
                "debt_opening",
                "debt_raised_net",
                "debt_non_cash",
                "debt_closing",
            )
        )
        if opening is None or raised is None or other is None:
            continue
        assert opening + raised + other == closing == cells["total_debt"].value
        closed += 1
    assert closed >= 10
    grown = replace(
        regs,
        facilities=tuple(
            replace(f, carrying_value=Decimal(280))
            if (f.facility_id, f.period_id) == ("finl", "Q2_2026")
            else f
            for f in regs.facilities
        ),
    )
    moved = _debt(grown, historical_columns(grown))
    assert moved[by_label["Q2 26"].column_id]["debt_non_cash"].value == 20
