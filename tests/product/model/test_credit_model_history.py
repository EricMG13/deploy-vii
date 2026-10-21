"""Historical columns and derived periods: quarters, PYTD, YTD, FY and LTM."""

from __future__ import annotations

from decimal import Decimal

from deploy_vii.model.frame import Cell, SourceRef
from deploy_vii.model.history import (
    BALANCE_METRICS,
    FLOW_METRICS,
    account_frame,
    historical_columns,
)
from tests.product.model.credit_model_fixture import example_registers
from tests.product.model.history_cases import _regs
from tests.product.model.history_frames import _frame, _value


def test_flow_and_balance_metrics_are_cp1_controlled_ids() -> None:
    assert len(FLOW_METRICS) == 25
    assert len(BALANCE_METRICS) == 9
    assert not FLOW_METRICS & BALANCE_METRICS
    assert {"revenue", "gross_profit", "cash_lease_payments", "pretax_income"} <= (FLOW_METRICS)
    assert {"cash_and_equivalents", "senior_secured_debt", "unsecured_debt"} <= (BALANCE_METRICS)
    assert "effective_tax_rate" not in FLOW_METRICS | BALANCE_METRICS


def test_ytd_and_pytd_are_omitted_when_the_latest_period_is_a_fy_end() -> None:
    regs = _regs(
        quarters={"Q3_2025": {"revenue": 30}, "Q4_2025": {"revenue": 40}},
        fy={"FY2025": {"revenue": 140}},
        ytd={"H1_2025": {"revenue": 70}, "H1_2024": {"revenue": 60}},
    )

    columns = historical_columns(regs)

    assert [column.column_id for column in columns] == [
        "Q:Q3_2025",
        "Q:Q4_2025",
        "FY:FY2025",
        "LTM:FY2025",
    ]
    ltm = columns[-1]
    assert (ltm.label, ltm.period_id, ltm.end_date, ltm.days) == (
        "LTM Q4 25",
        None,
        "2025-12-31",
        365,
    )
    cell = account_frame(regs, columns)["LTM:FY2025"]["acct:revenue"]
    assert (cell.value, cell.basis, cell.stated) == (Decimal(140), "CALCULATED", None)


def test_a_derived_ltm_without_a_register_row_is_named_by_its_ytd() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ytd={"H1_2025": {"revenue": 190}, "H1_2026": {"revenue": 210}},
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [column.column_id for column in columns] == [
        "PYTD:H1_2025",
        "YTD:H1_2026",
        "FY:FY2025",
        "LTM:H1_2026",
    ]
    assert (columns[-1].label, columns[-1].days) == ("LTM Q2 26", 365)
    assert frame["LTM:H1_2026"]["acct:revenue"].value == Decimal(420)
    assert frame["YTD:H1_2026"]["acct:revenue"] == Cell(
        Decimal(210),
        basis="REPORTED",
        sources=(SourceRef("S1", "H1_2026", "210"),),
    )


def test_ltm_equals_fy_plus_ytd_minus_pytd_for_every_flow() -> None:
    frame = _frame(example_registers())
    ltm, fy = frame["LTM:LTM_Q2_2026"], frame["FY:FY2025"]
    ytd, pytd = frame["YTD:H1_2026"], frame["PYTD:H1_2025"]
    flows = [
        key for key in ltm if key.removeprefix("acct:") in FLOW_METRICS or key.startswith("bu:")
    ]

    assert len(flows) == 26
    for key in flows:
        expected = _value(fy[key]) + _value(ytd[key]) - _value(pytd[key])
        cell = ltm[key]
        assert cell.value == expected, key
        assert (cell.basis, cell.stated, cell.note) == ("CALCULATED", expected, None)
    assert ltm["acct:revenue"].value == Decimal(11654)
    assert ltm["acct:adjusted_ebitda"].value == Decimal(4089)
    assert ltm["addback:run_rate_cost_savings"].value == Decimal(40)
    assert ltm["acct:revenue"].sources[0] == SourceRef(
        "S3", "10-K FY2025, Item 8 and quarterly data", "11519"
    )
