"""History frames and register edits shared by the history tests (split from
caos `tests/test_credit_model_history.py`)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from deploy_vii.model.frame import Cell, SourceRef
from deploy_vii.model.history import (
    account_frame,
    historical_columns,
)
from deploy_vii.model.registers import (
    Cp1Registers,
    KpiRow,
    PeriodRow,
)


def _frame(regs: Cp1Registers) -> dict[str, dict[str, Cell]]:
    return account_frame(regs, historical_columns(regs))


def _value(cell: Cell) -> Decimal:
    assert cell.value is not None, cell
    return cell.value


def _kpi(kpi_id: str, value_type: str, period_id: str, value: str) -> KpiRow:
    source = SourceRef("S1", period_id, value)
    return KpiRow(kpi_id, kpi_id, 1, period_id, Decimal(value), "UNITS", value_type, source)


def _sparse_rows(regs: Cp1Registers, rows: dict[str, int]) -> Cp1Registers:
    """`regs` with transaction costs only in `rows` (period id: figure)."""
    kept = [b for b in regs.addbacks if b.addback_id != "transaction_costs"]
    model = next(b for b in regs.addbacks if b.addback_id == "transaction_costs")
    added = [
        replace(model, period_id=period_id, value=Decimal(value))
        for period_id, value in rows.items()
    ]
    return replace(regs, addbacks=(*kept, *added))


def _costs(regs: Cp1Registers) -> dict[str, Cell]:
    frame = account_frame(regs, historical_columns(regs))
    return {column_id: cells["addback:transaction_costs"] for column_id, cells in frame.items()}


def _periods_changed(regs: Cp1Registers, *changed: PeriodRow) -> Cp1Registers:
    by_id = {p.period_id: p for p in changed}
    return replace(regs, periods=tuple(by_id.get(p.period_id, p) for p in regs.periods))


def _without_ltm_rows(regs: Cp1Registers) -> Cp1Registers:
    """`regs` without CP-1's LTM figures or pro forma: nothing stated to
    compare the host's LTM with."""
    accounts = tuple(a for a in regs.accounts if a.period_id != "LTM_Q2_2026")
    return replace(regs, accounts=accounts, pro_forma=())


def _written_positive(
    regs: Cp1Registers, period_ids: set[str], metric_ids: set[str]
) -> Cp1Registers:
    """`regs` with those accounts' figures written as their absolute value."""
    return replace(
        regs,
        accounts=tuple(
            replace(a, value=abs(a.value))
            if a.period_id in period_ids and a.metric_id in metric_ids and a.value is not None
            else a
            for a in regs.accounts
        ),
    )


def _extra_period(
    period_id: str, start: str, end: str, components: tuple[str, ...] = ()
) -> PeriodRow:
    return PeriodRow(
        period_id=period_id,
        fiscal_year="2025",
        fiscal_quarter=None,
        period_type="PERIOD_END",
        start_date=start,
        end_date=end,
        day_count=None,
        currency="USD",
        unit="MILLIONS",
        component_period_ids=components,
    )
