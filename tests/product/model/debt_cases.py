"""Debt frames shared by the debt tests (split from caos
`tests/test_credit_model_debt.py`)."""

from __future__ import annotations

from dataclasses import replace

from deploy_vii.model.debt import (
    debt_frame,
)
from deploy_vii.model.frame import Column, Frame
from deploy_vii.model.history import account_frame, historical_columns
from deploy_vii.model.registers import Cp1Registers, FacilityRow


def _row(regs: Cp1Registers, facility_id: str) -> FacilityRow:
    return next(f for f in regs.facilities if f.facility_id == facility_id)


def _columns(regs: Cp1Registers) -> dict[str, Column]:
    return {column.label: column for column in historical_columns(regs)}


def _debt(regs: Cp1Registers, columns: tuple[Column, ...]) -> Frame:
    return debt_frame(regs, columns, account_frame(regs, columns))


def _with_facilities(regs: Cp1Registers, *rows: FacilityRow) -> Cp1Registers:
    return replace(regs, facilities=(*regs.facilities, *rows))
