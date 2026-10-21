"""Historical Model statements and an explicit ratio calculation register.

The reviewed kernel owns calculation. This boundary records the operands used
by its metric definitions, not a model-authored explanation of the numbers.
"""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from deploy_vii.contracts import Contract, Identifier, Text
from deploy_vii.financial_adapter import kernel_registers
from deploy_vii.financial_contracts import FinancialBook, FinancialReview, Observation
from deploy_vii.financial_periods import (
    HistoricalReport,
    PeriodValue,
    _evidence,
    _id,
    _unit,
    _value,
    historical_report,
)
from deploy_vii.financial_validation import records
from deploy_vii.model import history, metrics
from deploy_vii.model._cells import CONTEXT, calc
from deploy_vii.model.frame import Cell, Column, Frame
from deploy_vii.model.periods import _plan, _quarter_index
from deploy_vii.model.registers import Cp1Registers
from deploy_vii.model.statements import statement_frame
from deploy_vii.preparation import PreparedPack


class ModelBasis(Contract):
    basis_id: Identifier
    column_key: Text
    label: Text
    kind: Literal["QUARTER", "PYTD", "YTD", "FY", "LTM"]
    scope: Literal["historical", "trailing_four_quarters"]
    period_id: Identifier | None
    start_date: date | None
    end_date: date | None
    days: int | None
    historical_construction_id: Identifier | None
    quarter_construction_ids: tuple[Identifier | None, ...]
    limitation: Text | None


class ModelValue(Contract):
    value_id: Identifier
    basis_id: Identifier
    key: Text
    unit: Text
    currency: Text | None
    value: PeriodValue
    residual_formula: Text | None


class MetricOperand(Contract):
    value_id: Identifier
    coefficient: Literal[-1, 1]


class MetricLeg(Contract):
    amount: Decimal | None
    operands: tuple[MetricOperand, ...]


class ModelMetric(Contract):
    calculation_id: Identifier
    display_basis_id: Identifier
    key: Text
    unit: Literal["MULTIPLE", "PERCENT"]
    currency: Text
    input_scale: Text
    formula: Text
    numerator: MetricLeg
    denominator: MetricLeg
    offset: Literal[-1, 0]
    value: PeriodValue
    evidence_quality_tier: Text | None = None
    evidence_limitation: Text = "Evidence quality tier has not been analytically assessed"


class ModelReport(Contract):
    schema_version: Literal["financial-model/1"] = "financial-model/1"
    historical: HistoricalReport
    exclude_unrealised: bool
    bases: tuple[ModelBasis, ...]
    values: tuple[ModelValue, ...]
    metrics: tuple[ModelMetric, ...]
    limitations: tuple[Text, ...]


_RESIDUALS = {
    "other_operating": (
        "cfo_adjusted - working_capital_change - adjusted_ebitda - cash_interest "
        "- lease_cash_not_in_ebitda - cash_taxes"
    ),
    "other_investing_financing": (
        "acct:net_cash_change - fcf - acquisitions_net "
        "- debt_raised_net - equity_raised_net - dividends"
    ),
    "fx_and_other_cash": "cash_closing - cash_opening - ncf",
    "debt_non_cash": "total_debt - debt_opening - debt_raised_net",
}


def _basis_id(column: Column, rolling: bool = False) -> str:
    return _id("model-basis", "rolling" if rolling else "historical", column.column_id)


def _bases(
    regs: Cp1Registers,
    columns: tuple[Column, ...],
    rolling: tuple[Column, ...],
    historical: HistoricalReport,
) -> tuple[ModelBasis, ...]:
    nodes = {n.column_key: n for n in historical.constructions}
    plan = {s.column.column_id: s for s in _plan(regs)}
    quarters = _quarter_index(plan.values())
    result: list[ModelBasis] = []
    for is_rolling, group in ((False, columns), (True, rolling)):
        for column in group:
            node = nodes[column.column_id]
            end = date.fromisoformat(column.end_date) if column.end_date else None
            start = (
                date.fromordinal(end.toordinal() - column.days + 1)
                if end and column.days and 0 < column.days <= end.toordinal()
                else None
            )
            components: tuple[Identifier | None, ...] = ()
            if is_rolling:
                spec = plan[column.column_id]
                parts = (*reversed(history._earlier(spec, quarters)), spec)
                components = tuple(
                    None if part is None else _id("period", part.column.column_id) for part in parts
                )
            if column.kind not in {"QUARTER", "PYTD", "YTD", "FY", "LTM"}:
                raise ValueError("Historical Model received a nonhistorical column")
            result.append(
                ModelBasis(
                    basis_id=_basis_id(column, is_rolling),
                    column_key=column.column_id,
                    label=column.label,
                    kind=column.kind,
                    scope="trailing_four_quarters" if is_rolling else "historical",
                    period_id=column.period_id,
                    start_date=start,
                    end_date=end,
                    days=column.days,
                    historical_construction_id=None if is_rolling else node.construction_id,
                    quarter_construction_ids=components,
                    limitation=(
                        "Four complete contiguous quarters spanning 364-371 days are required"
                        if is_rolling and column.days is None
                        else None
                        if is_rolling
                        else node.limitation
                    ),
                )
            )
    return tuple(result)


def _value_unit(book: FinancialBook, key: str) -> tuple[str, str | None]:
    if key in {"days", "dso", "dio", "dpo", "ccc"}:
        return "DAYS", None
    return _unit(book, key)


def _leg(
    basis: str | None,
    cells: Mapping[str, Cell] | None,
    parts: tuple[tuple[str, int], ...],
) -> MetricLeg:
    if cells is None or basis is None:
        return MetricLeg(amount=None, operands=())
    # The kernel's signed sum preserves unknown components and Decimal context.
    total = calc((cells[key], sign) for key, sign in parts)
    return MetricLeg(
        amount=total.value,
        operands=tuple(
            MetricOperand(
                value_id=_id("model-value", basis, key), coefficient=1 if sign == 1 else -1
            )
            for key, sign in parts
        ),
    )


def _metric_rows(
    columns: tuple[Column, ...],
    frame: Frame,
    rolling: Frame,
    result: Frame,
    book: FinancialBook,
    observations: dict[str, Observation],
) -> tuple[ModelMetric, ...]:
    evidence = _evidence(book)
    corporate = frozenset(
        s.segment_id for s in book.segments if s.segment_type == "CORPORATE_ELIMINATION"
    )
    rows: list[ModelMetric] = []
    for column in columns:
        own = frame[column.column_id]
        own_basis_id = _basis_id(column)
        prior = metrics._prior_cells(column, columns, frame, rolling)
        growth_targets = {
            **{f"{key}_growth": key for key in metrics._GROWTH},
            **{f"bu_growth:{key.removeprefix('bu:')}": key for key in own if key.startswith("bu:")},
        }
        for key, cell in result[column.column_id].items():
            if key.startswith("metric:"):
                recipe = metrics._METRICS[key.removeprefix("metric:")]
                cells = metrics._basis(column, own, rolling, recipe.scope)
                uses_rolling = column.kind == "QUARTER" and recipe.scope != "own"
                metric_basis_id = _basis_id(column, uses_rolling)
                numerator = _leg(metric_basis_id, cells, recipe.numerator)
                denominator = _leg(metric_basis_id, cells, recipe.denominator)
                offset: Literal[-1, 0] = 0
            elif key in growth_targets:
                target = growth_targets[key]
                corporate_growth = (
                    target.startswith("bu:") and target.removeprefix("bu:") in corporate
                )
                if prior is None or corporate_growth:
                    numerator = denominator = MetricLeg(amount=None, operands=())
                else:
                    prior_column, prior_cells = prior
                    prior_basis_id = _basis_id(
                        prior_column, column.kind == "LTM" and prior_column.kind == "QUARTER"
                    )
                    numerator = _leg(own_basis_id, own, ((target, 1),))
                    denominator = _leg(prior_basis_id, prior_cells, ((target, 1),))
                offset = -1
            else:
                continue
            rows.append(
                ModelMetric(
                    calculation_id=_id("model-metric", own_basis_id, key),
                    display_basis_id=own_basis_id,
                    key=key,
                    unit=metrics.unit_of(key),
                    currency=book.currency,
                    input_scale=book.unit,
                    formula="sum(numerator signed operands) / sum(denominator signed operands)"
                    + (" - 1" if offset else ""),
                    numerator=numerator,
                    denominator=denominator,
                    offset=offset,
                    value=_value(cell, observations, evidence),
                )
            )
    return tuple(rows)


def model_report(
    pack: PreparedPack,
    review: FinancialReview,
    book_id: str,
    *,
    exclude_unrealised: bool = False,
) -> ModelReport:
    """Calculate historical Model output; the house variant must be selected explicitly."""
    regs = kernel_registers(pack, review, book_id)
    review = FinancialReview.model_validate_json(review.model_dump_json())
    book = next(book for book in review.books if book.book_id == book_id)
    historical = historical_report(pack, review, book_id)
    columns = history.historical_columns(regs)
    rolling_columns = history.ltm_columns(regs, columns)
    frame = statement_frame(history.account_frame(regs, columns), columns, regs, exclude_unrealised)
    rolling = statement_frame(
        history.ltm_frames(regs, columns), rolling_columns, regs, exclude_unrealised
    )
    corporate = frozenset(
        s.segment_id for s in book.segments if s.segment_type == "CORPORATE_ELIMINATION"
    )
    result = metrics.metric_frame(columns, frame, rolling, corporate=corporate)
    observations = {o.observation_id: o for o in records(book, Observation)}
    evidence = _evidence(book)
    values: list[ModelValue] = []
    for is_rolling, group, data in ((False, columns, frame), (True, rolling_columns, rolling)):
        for column in group:
            basis = _basis_id(column, is_rolling)
            for key, cell in data[column.column_id].items():
                unit, currency = _value_unit(book, key)
                values.append(
                    ModelValue(
                        value_id=_id("model-value", basis, key),
                        basis_id=basis,
                        key=key,
                        unit=unit,
                        currency=currency,
                        value=_value(cell, observations, evidence),
                        residual_formula=_RESIDUALS.get(key),
                    )
                )
    with localcontext(CONTEXT):
        ratios = _metric_rows(columns, frame, rolling, result, book, observations)
    return ModelReport(
        historical=historical,
        exclude_unrealised=exclude_unrealised,
        bases=_bases(regs, columns, rolling_columns, historical),
        values=tuple(values),
        metrics=ratios,
        limitations=(
            "Historical Model calculations only; no readiness or analytical acceptance is granted",
            "Model debt includes finance leases; canonical CP-1 debt excludes both lease types",
            "Residuals explain arithmetic differences, not their economic causes "
            "or independent reconciliation",
            "Evidence quality tiers and analytical KPI trends remain unassessed",
            "Full canonical CP-1 KPI coverage, statement formula register, "
            "pro forma and projections remain pending",
            "No CLI, journal or Workbench binding yet",
            *book.limitations,
        ),
    )


def validate_model_report(
    pack: PreparedPack, review: FinancialReview, report: ModelReport
) -> tuple[str, ...]:
    try:
        report = ModelReport.model_validate_json(report.model_dump_json())
        expected = model_report(
            pack, review, report.historical.book_id, exclude_unrealised=report.exclude_unrealised
        )
    except ValueError as error:
        return (f"Invalid Model inputs: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Model artifact differs from deterministic recomputation",)
    )
