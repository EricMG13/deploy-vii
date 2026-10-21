"""CP-1 KPI calculations on canonical carrying debt, separate from Model debt."""

from collections.abc import Mapping
from dataclasses import replace
from decimal import localcontext
from typing import Literal

from deploy_vii.calculation_trace import Computation, trace_cells
from deploy_vii.contracts import Contract, Identifier, Text
from deploy_vii.facility_fx import normalize_facilities
from deploy_vii.financial_adapter import kernel_registers
from deploy_vii.financial_contracts import FinancialBook, FinancialReview, Observation
from deploy_vii.financial_model import (
    MetricLeg,
    MetricOperand,
    ModelBasis,
    ModelValue,
    _bases,
    _basis_id,
    _value_unit,
)
from deploy_vii.financial_periods import (
    HistoricalReport,
    PeriodValue,
    _evidence,
    _id,
    _value,
    historical_report,
)
from deploy_vii.financial_validation import records
from deploy_vii.model import history, metrics
from deploy_vii.model._cells import ABSENT, CONTEXT, calc, join_notes
from deploy_vii.model.frame import Cell, Column, Frame
from deploy_vii.model.statements import statement_frame
from deploy_vii.preparation import PreparedPack


class CanonicalKpi(Contract):
    calculation_id: Identifier
    display_basis_id: Identifier
    key: Text
    operation: Literal["value", "ratio", "growth", "unavailable"]
    unit: Text
    currency: Text
    input_scale: Text
    formula: Text
    numerator: MetricLeg
    denominator: MetricLeg | None
    value: PeriodValue
    evidence_quality_tier: Text | None = None
    evidence_limitation: Text = "Evidence quality and analytical trend have not been assessed"


class CanonicalKpiReport(Contract):
    schema_version: Literal["canonical-kpis/2"] = "canonical-kpis/2"
    historical: HistoricalReport
    debt_basis: Literal["carrying_value_excluding_both_lease_types"] = (
        "carrying_value_excluding_both_lease_types"
    )
    bases: tuple[ModelBasis, ...]
    values: tuple[ModelValue, ...]
    kpis: tuple[CanonicalKpi, ...]
    computations: tuple[Computation, ...]
    limitations: tuple[Text, ...]


# Explicit variants: never silently select adjusted EBITDA over reported EBITDA.
_RECIPES = {
    key: recipe
    for key, recipe in metrics._METRICS.items()
    if key
    in {
        "total_leverage_reported",
        "total_leverage_adjusted",
        "net_leverage_reported",
        "net_leverage_adjusted",
        "senior_secured_leverage",
        "interest_coverage_reported",
        "interest_coverage_adjusted",
        "capex_adjusted_coverage",
        "ffo_to_debt",
        "fcf_to_debt",
        "fcf_to_adjusted_ebitda",
        "capex_to_revenue",
        "liquidity_to_debt",
        "gross_margin",
        "ebit_margin",
        "net_income_margin",
        "ebitda_margin",
        "adjusted_ebitda_margin",
    }
}
_RECIPES.update(
    {
        "senior_secured_leverage_reported": metrics._Metric(
            "MULTIPLE", "twelve", (("secured_debt", 1),), (("ebitda", 1),)
        ),
        "capex_adjusted_coverage_reported": metrics._Metric(
            "MULTIPLE", "twelve", (("ebitda", 1), ("capex", 1)), (("cash_interest", -1),)
        ),
        "cfo_to_debt": metrics._Metric(
            "PERCENT", "twelve", (("cfo_adjusted", 1),), (("total_debt", 1),)
        ),
        "fcf_to_reported_ebitda": metrics._Metric(
            "PERCENT", "own", (("fcf", 1),), (("ebitda", 1),)
        ),
        "dcf_to_debt": metrics._Metric("PERCENT", "twelve", (("dcf", 1),), (("total_debt", 1),)),
        "ffo_interest_coverage": metrics._Metric(
            "MULTIPLE", "twelve", (("ffo", 1), ("cash_interest", -1)), (("cash_interest", -1),)
        ),
    }
)
_SCALARS = (
    "revenue",
    "gross_profit",
    "ebitda",
    "adjusted_ebitda",
    "ebit",
    "net_income",
    "da",
    "cash_interest",
    "cash_taxes",
    "capex",
    "working_capital_change",
    "cfo_reported",
    "cfo_adjusted",
    "ffo",
    "fcf",
    "dcf",
    "cash_closing",
    "total_debt",
    "secured_debt",
    "net_debt",
    "undrawn_rcf",
    "liquidity",
)


def _source_states(value: Cell, observations: dict[str, Observation]) -> frozenset[str]:
    """Inspect original leaves, including null operands retained in a failed sum."""
    pending = [value]
    seen: set[int] = set()
    states: set[str] = set()
    while pending:
        cell = pending.pop()
        if id(cell) in seen:
            continue
        seen.add(id(cell))
        states.update(
            observations[ref.source_id].status
            for ref in (*cell.sources, *cell.input_sources)
            if ref.source_locator == "financial-observation"
        )
        if cell.arithmetic:
            pending.extend(part for part, _ in cell.arithmetic.operands)
    return frozenset(states)


def _preferred(reported: Cell, derived: Cell, observations: dict[str, Observation]) -> Cell:
    """Use reported evidence first; a conflict cannot fall through to arithmetic."""
    if (
        reported.value is not None
        or _source_states(reported, observations) & {"conflicting", "not_applicable"}
        or reported.arithmetic is not None
    ):
        return reported
    return replace(
        derived,
        note=join_notes(derived.note, "Reported value unavailable; derived from components"),
    )


def _canonical_frame(
    accounts: Frame, statements: Frame, observations: dict[str, Observation]
) -> Frame:
    """Select source income and carrying debt, then derive dependent scalars."""
    result: Frame = {}
    with localcontext(CONTEXT):
        for column_id, statement in statements.items():
            source = accounts[column_id]
            cells = {key: statement.get(key, ABSENT) for key in _SCALARS}

            cells["gross_profit"] = _preferred(
                source.get("acct:gross_profit", ABSENT), cells["gross_profit"], observations
            )
            operating_income_base = (
                cells["revenue"]
                if statement["cogs"].reason == "NOT_SOURCED"
                else cells["gross_profit"]
            )
            cells["ebit"] = _preferred(
                source.get("acct:ebit", ABSENT),
                calc(((operating_income_base, 1), (statement["opex_total"], 1))),
                observations,
            )
            cells["ebitda"] = _preferred(
                source.get("acct:ebitda", ABSENT),
                calc(((cells["ebit"], 1), (cells["da"], -1))),
                observations,
            )
            adjustments = tuple(
                (value, 1) for key, value in source.items() if key.startswith("addback:")
            )
            cells["adjusted_ebitda"] = _preferred(
                source.get("acct:adjusted_ebitda", ABSENT),
                calc(((cells["ebitda"], 1), *adjustments)),
                observations,
            )

            cells["ffo"] = calc(((cells["cfo_adjusted"], 1), (cells["working_capital_change"], -1)))
            cells["dcf"] = calc(((cells["fcf"], 1), (statement.get("dividends", ABSENT), 1)))
            cells["total_debt"] = source.get("acct:total_debt", ABSENT)
            cells["secured_debt"] = source.get("acct:senior_secured_debt", ABSENT)
            cells["net_debt"] = calc(((cells["total_debt"], 1), (cells["cash_closing"], -1)))
            result[column_id] = cells
    return result


_BALANCES = frozenset(
    {"cash_closing", "total_debt", "secured_debt", "net_debt", "undrawn_rcf", "liquidity"}
)


def _rolling_frame(
    frame: Frame, rolling: Frame, bases: tuple[ModelBasis, ...], historical: HistoricalReport
) -> Frame:
    """Sum canonical flow cells for trailing quarters, retaining every operand."""
    column_by_construction = {
        node.construction_id: node.column_key for node in historical.constructions
    }
    result = {key: dict(cells) for key, cells in rolling.items()}
    with localcontext(CONTEXT):
        for basis in bases:
            if basis.scope != "trailing_four_quarters":
                continue
            for key in _SCALARS:
                if key in _BALANCES:
                    continue
                parts = tuple(
                    (ABSENT if part is None else frame[column_by_construction[part]][key], 1)
                    for part in basis.quarter_construction_ids
                )
                value = calc(parts)
                if basis.days is None:
                    value = replace(
                        value,
                        value=None,
                        reason="COMPONENT_MISSING",
                        note=join_notes(value.note, basis.limitation),
                    )
                result[basis.column_key][key] = value
    return result


def _value_id(basis: str, key: str) -> str:
    return _id("canonical-value", basis, key)


def _kpi_rows(
    columns: tuple[Column, ...],
    frame: Frame,
    rolling: Frame,
    book: FinancialBook,
    observations: dict[str, Observation],
) -> tuple[CanonicalKpi, ...]:
    normalizations = {n.normalization_id: n for n in normalize_facilities(book)}
    evidence = _evidence(book, normalizations)
    rows: list[CanonicalKpi] = []
    operands = {
        _value_id(_basis_id(c, rolling_basis), key): cell
        for rolling_basis, data in ((False, frame), (True, rolling))
        for c in columns
        if c.column_id in data
        for key, cell in data[c.column_id].items()
    }

    def leg(
        basis: str, cells: Mapping[str, Cell] | None, parts: tuple[tuple[str, int], ...]
    ) -> MetricLeg:
        if cells is None:
            return MetricLeg(amount=None, operands=())
        return MetricLeg(
            amount=calc((cells[key], sign) for key, sign in parts).value,
            operands=tuple(
                MetricOperand(value_id=_value_id(basis, key), coefficient=1 if sign == 1 else -1)
                for key, sign in parts
            ),
        )

    def add(
        column: Column,
        key: str,
        operation: Literal["value", "ratio", "growth"],
        unit: str,
        formula: str,
        top: MetricLeg,
        bottom: MetricLeg | None,
        cell: Cell,
    ) -> None:
        basis = _basis_id(column)
        value = _value(cell, observations, evidence, normalizations)
        if value.amount is None and any(
            "conflicting" in _source_states(operands[part.value_id], observations)
            for side in (top, bottom)
            if side is not None
            for part in side.operands
        ):
            value = value.model_copy(update={"calculation_status": "Conflicted"})
        rows.append(
            CanonicalKpi(
                calculation_id=_id("canonical-kpi", basis, key),
                display_basis_id=basis,
                key=key,
                operation=operation,
                unit=unit,
                currency=book.currency,
                input_scale=book.unit,
                formula=formula,
                numerator=top,
                denominator=bottom,
                value=value,
            )
        )

    with localcontext(CONTEXT):
        for column in columns:
            own = frame[column.column_id]
            basis = _basis_id(column)
            for key in _SCALARS:
                add(
                    column,
                    key,
                    "value",
                    book.unit,
                    key,
                    leg(basis, own, ((key, 1),)),
                    None,
                    own[key],
                )
            for key, recipe in _RECIPES.items():
                selected = metrics._basis(column, own, rolling, recipe.scope)
                selected_basis = _basis_id(
                    column, column.kind == "QUARTER" and recipe.scope != "own"
                )
                cells = selected
                top, bottom = (
                    leg(selected_basis, cells, recipe.numerator),
                    leg(selected_basis, cells, recipe.denominator),
                )
                cell = (
                    Cell(None, "NOT_APPLICABLE")
                    if cells is None
                    else metrics._ratio(
                        [(cells[k], sign) for k, sign in recipe.numerator],
                        [(cells[k], sign) for k, sign in recipe.denominator],
                    )
                )
                formula = (
                    "("
                    + " + ".join(f"{s} * {k}" for k, s in recipe.numerator)
                    + ") / ("
                    + " + ".join(f"{s} * {k}" for k, s in recipe.denominator)
                    + ")"
                )
                add(column, key, "ratio", recipe.unit, formula, top, bottom, cell)
            prior = metrics._prior_cells(column, columns, frame, rolling)
            growth = metrics._growth(column, own, prior, frozenset())
            for target in metrics._GROWTH:
                key = target + "_growth"
                if prior is None:
                    top = bottom = MetricLeg(amount=None, operands=())
                else:
                    previous, previous_cells = prior
                    prior_basis = _basis_id(
                        previous, column.kind == "LTM" and previous.kind == "QUARTER"
                    )
                    top = leg(basis, own, ((target, 1),))
                    bottom = leg(prior_basis, previous_cells, ((target, 1),))
                add(
                    column,
                    key,
                    "growth",
                    "PERCENT",
                    "current / prior comparable period - 1",
                    top,
                    bottom,
                    growth[key],
                )
    return tuple(rows)


def canonical_kpis(pack: PreparedPack, review: FinancialReview, book_id: str) -> CanonicalKpiReport:
    regs = kernel_registers(pack, review, book_id)
    review = FinancialReview.model_validate_json(review.model_dump_json())
    book = next(b for b in review.books if b.book_id == book_id)
    observations = {o.observation_id: o for o in records(book, Observation)}
    historical = historical_report(pack, review, book_id)
    columns = history.historical_columns(regs)
    rolling_columns = history.ltm_columns(regs, columns)
    accounts = history.account_frame(regs, columns)
    rolling_accounts = history.ltm_frames(regs, columns)
    frame = _canonical_frame(
        accounts, statement_frame(accounts, columns, regs, False), observations
    )
    rolling = _canonical_frame(
        rolling_accounts,
        statement_frame(rolling_accounts, rolling_columns, regs, False),
        observations,
    )
    bases = _bases(regs, columns, rolling_columns, historical)
    rolling = _rolling_frame(frame, rolling, bases, historical)
    value_cells = {
        _value_id(_basis_id(c, is_rolling), key): cell
        for is_rolling, group, data in ((False, columns, frame), (True, rolling_columns, rolling))
        for c in group
        for key, cell in data[c.column_id].items()
    }
    computations, roots = trace_cells(value_cells, book)
    normalizations = {n.normalization_id: n for n in normalize_facilities(book)}
    evidence = _evidence(book, normalizations)
    values = []
    for is_rolling, group, data in ((False, columns, frame), (True, rolling_columns, rolling)):
        for column in group:
            basis = _basis_id(column, is_rolling)
            for key, cell in data[column.column_id].items():
                unit, currency = _value_unit(book, key)
                value_id = _value_id(basis, key)
                values.append(
                    ModelValue(
                        value_id=value_id,
                        basis_id=basis,
                        key=key,
                        unit=unit,
                        currency=currency,
                        value=_value(cell, observations, evidence, normalizations),
                        residual_formula=None,
                        computation_id=roots[value_id],
                    )
                )
    return CanonicalKpiReport(
        historical=historical,
        bases=bases,
        values=tuple(values),
        kpis=_kpi_rows(columns, frame, rolling, book, observations),
        computations=computations,
        limitations=(
            "Canonical debt uses CP-1 carrying values excluding both lease types; Model "
            "debt is separate",
            "Reported income values take precedence; missing values may be derived, "
            "conflicts never are",
            "CFO retains the reviewed financing classifications; "
            "FFO = adjusted CFO - working capital change",
            "Cash conversion is FCF / adjusted EBITDA; both EBITDA variants are "
            "explicitly retained",
            "DCF = FCF - dividends paid; share repurchases are not deducted",
            "Calculations do not establish source reconciliation, readiness, analytical "
            "trends or report acceptance",
            *book.limitations,
        ),
    )


def validate_canonical_kpis(
    pack: PreparedPack, review: FinancialReview, report: CanonicalKpiReport
) -> tuple[str, ...]:
    try:
        report = CanonicalKpiReport.model_validate_json(report.model_dump_json())
        expected = canonical_kpis(pack, review, report.historical.book_id)
    except ValueError as error:
        return (f"Invalid canonical KPI inputs: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Canonical KPIs differ from deterministic recomputation",)
    )
