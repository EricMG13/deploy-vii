"""Metric frames and expected ratios shared by the metric tests (split from caos
`tests/test_credit_model_metrics.py`)."""

from __future__ import annotations

from decimal import Decimal, localcontext

from deploy_vii.model._cells import CONTEXT
from deploy_vii.model.frame import Case, Cell, Column, Frame, SourceRef
from deploy_vii.model.history import (
    account_frame,
    historical_columns,
    ltm_frames,
)
from deploy_vii.model.metrics import metric_frame
from deploy_vii.model.registers import Cp1Registers
from deploy_vii.model.statements import (
    pro_forma_column,
    statement_frame,
)
from tests.product.model.credit_model_fixture import example_registers

_CORPORATE = frozenset({"corporate_eliminations"})


# Projected columns stand in for caos `projection` (Plan 13 ports it): each
# carries only the keys a projection writes, from FY2025 with revenue,
# adjusted EBITDA and the business units grown by its factor.
_PROJECTED: tuple[tuple[Case, int, str], ...] = (
    ("BASE", 2026, "1.02"),
    ("BASE", 2027, "1.05"),
    ("DOWNSIDE", 2026, "0.95"),
    ("DOWNSIDE", 2027, "0.97"),
)


_PROJECTED_KEYS = ("total_debt", "secured_debt", "cash_closing", "capex", "cash_interest")


_GROWN_KEYS = ("revenue", "adjusted_ebitda")


def _projections(frame: Frame) -> tuple[tuple[Column, ...], Frame]:
    fy = frame["FY:FY2025"]
    columns: list[Column] = []
    projected: Frame = {}
    for case, year, factor in _PROJECTED:
        column_id = f"{case}:{year}"
        columns.append(
            Column(column_id, "PROJECTED", f"FY{year % 100}E", None, str(year), None, 365, case)
        )
        cells = {key: fy[key] for key in _PROJECTED_KEYS}
        for key in (*_GROWN_KEYS, *(k for k in fy if k.startswith("bu:"))):
            value = fy[key].value
            assert value is not None, key
            cells[key] = Cell(value * Decimal(factor), basis="PROJECTED")
        projected[column_id] = cells
    return tuple(columns), projected


def _model(
    regs: Cp1Registers | None = None,
) -> tuple[tuple[Column, ...], Frame, Frame]:
    """Every column of the example: history, the PF-LTM and stand-in
    projections; their frame; and the statements of the LTM ending each
    quarter."""
    regs = regs or example_registers()
    columns = historical_columns(regs)
    frame = statement_frame(account_frame(regs, columns), columns, regs)
    quarters = tuple(c for c in columns if c.kind == "QUARTER")
    ltm_ending = statement_frame(ltm_frames(regs, columns), quarters, regs)
    ltm = next(c for c in columns if c.kind == "LTM")
    pro_forma = pro_forma_column(regs, ltm, frame)
    assert pro_forma is not None
    pf_column, pf_frame = pro_forma
    projected, projected_frame = _projections(frame)
    every = (*columns, pf_column, *projected)
    return every, {**frame, **pf_frame, **projected_frame}, ltm_ending


def _metrics() -> tuple[Frame, Frame, Frame]:
    columns, frame, ltm_ending = _model()
    result = metric_frame(columns, frame, ltm_ending, corporate=_CORPORATE)
    return result, frame, ltm_ending


def _div(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext(CONTEXT):
        return numerator / denominator


def _v(cells: dict[str, Cell], key: str) -> Decimal:
    value = cells[key].value
    assert value is not None, key
    return value


def _fy(column_id: str, end: str, fiscal_year: str = "FY2025") -> Column:
    return Column(column_id, "FY", column_id, column_id, fiscal_year, end, 365, None)


_SOURCE_A = SourceRef("S1", "10-K", "100")


def _cells(**values: str) -> dict[str, Cell]:
    return {
        key: Cell(Decimal(value), basis="REPORTED", sources=(_SOURCE_A,))
        for key, value in values.items()
    }
