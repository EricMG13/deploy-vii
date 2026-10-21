"""Statement frames shared by the statement tests (split from caos
`tests/test_credit_model_statements.py`)."""

from __future__ import annotations

from dataclasses import replace

from deploy_vii.model.frame import Cell, Column, Frame
from deploy_vii.model.history import (
    account_frame,
    historical_columns,
)
from deploy_vii.model.registers import Cp1Registers
from deploy_vii.model.statements import (
    statement_frame,
)


def _columns(regs: Cp1Registers) -> dict[str, Column]:
    return {column.label: column for column in historical_columns(regs)}


def _frame(regs: Cp1Registers, exclude_unrealised: bool = False) -> Frame:
    columns = historical_columns(regs)
    accounts = account_frame(regs, columns)
    return statement_frame(accounts, columns, regs, exclude_unrealised)


def _cells(regs: Cp1Registers, label: str, exclude: bool = False) -> dict[str, Cell]:
    return _frame(regs, exclude)[_columns(regs)[label].column_id]


def _values(cells: dict[str, Cell], *keys: str) -> tuple[object, ...]:
    return tuple(cells[key].value for key in keys)


def _equal(cells: dict[str, Cell], left: tuple[str, ...], right: tuple[str, ...]) -> None:
    """The sum of the `left` keys equals the sum of the `right` keys."""
    lhs = [cells[key].value for key in left]
    rhs = [cells[key].value for key in right]
    assert None not in lhs and None not in rhs
    assert sum(v for v in lhs if v is not None) == sum(v for v in rhs if v is not None)


def _without(regs: Cp1Registers, metric_id: str, *period_ids: str) -> Cp1Registers:
    """`regs` without the metric's rows for `period_ids` (all when none)."""
    return replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if a.metric_id != metric_id or (period_ids and a.period_id not in period_ids)
        ),
    )
