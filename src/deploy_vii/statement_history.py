"""Full statement-line period construction using the reviewed historical kernel.

No Model readiness gate: incomplete add-back disclosure does not stop statement
arithmetic. Reported figures remain in the source artifact and never plug a
missing derived component. Every calculation retains its actual operand graph.
"""

from decimal import localcontext
from typing import Literal

from deploy_vii.calculation_trace import Computation, trace_cells
from deploy_vii.contracts import Contract, Identifier
from deploy_vii.financial_adapter import _periods
from deploy_vii.financial_contracts import FinancialPeriod, FinancialReview
from deploy_vii.financial_periods import (
    PeriodConstruction,
    PeriodReference,
    PeriodValue,
    _constructions,
    _id,
    _reference,
)
from deploy_vii.model import history
from deploy_vii.model._cells import CONTEXT, SIGN_NORMALISED
from deploy_vii.model.frame import Cell, SourceRef
from deploy_vii.model.periods import _period_spec, _plan, _Spec
from deploy_vii.model.registers import Cp1Registers
from deploy_vii.preparation import PreparedPack
from deploy_vii.statement_output import StatementCell, StatementReport, statement_report


class StatementPeriodOperand(Contract):
    reference: PeriodReference
    computation_id: Identifier


class StatementHistoricalValue(Contract):
    value_id: Identifier
    construction_id: Identifier
    table_id: Literal["T4.4", "T4.5", "T4.6"]
    item_id: Identifier
    value: PeriodValue
    computation_id: Identifier
    operands: tuple[StatementPeriodOperand, ...]
    stated_computation_id: Identifier | None


class StatementHistoryReport(Contract):
    schema_version: Literal["statement-history/1"] = "statement-history/1"
    source: StatementReport
    periods: tuple[FinancialPeriod, ...]
    columns: tuple[Identifier, ...]
    constructions: tuple[PeriodConstruction, ...]
    values: tuple[StatementHistoricalValue, ...]
    computations: tuple[Computation, ...]


def _input(cell: StatementCell) -> Cell:
    source = (
        (SourceRef(cell.observation_id, "financial-observation", str(cell.source_amount)),)
        if cell.observation_id
        else ()
    )
    if cell.normalized_amount is None:
        return Cell(
            None,
            "NOT_APPLICABLE" if cell.status == "not_applicable" else "NOT_STATED",
            input_sources=source,
            note=cell.limitation,
        )
    return Cell(
        cell.normalized_amount,
        basis="REPORTED",
        sources=source,
        note=SIGN_NORMALISED if cell.value_class == "normalized" else None,
    )


def _closing(
    cells: dict[str, StatementCell], periods: tuple[FinancialPeriod, ...], spec: _Spec
) -> Cell:
    """Closing observations only; an unresolved same-date conflict blocks selection."""
    end = spec.column.end_date
    if end is None:
        return Cell(None, "NOT_SOURCED", note="Closing date is unavailable")
    matching = tuple(p.period_id for p in periods if p.end_date and p.end_date.isoformat() == end)
    ordered = tuple(dict.fromkeys((spec.own, *matching)))
    available = [cells[pid] for pid in ordered if pid in matching and pid in cells]
    if any(cell.status == "conflicting" for cell in available):
        return Cell(
            None,
            "COMPONENT_MISSING",
            note="Unresolved conflicting statement observations at the closing date",
            input_sources=tuple(
                ref
                for cell in available
                for ref in (_input(cell).sources or _input(cell).input_sources)
            ),
        )
    selected = next((cell for cell in available if cell.normalized_amount is not None), None)
    if selected is None:
        selected = next((cell for cell in available if cell.observation_id), None)
    return _input(selected) if selected else Cell(None, "NOT_SOURCED")


def _derived_specs(regs: Cp1Registers) -> tuple[_Spec, ...]:
    planned = list(_plan(regs))
    seen: set[str] = set()
    derived: list[_Spec] = []

    def visit(spec: _Spec) -> None:
        if spec.column.column_id in seen:
            return
        seen.add(spec.column.column_id)
        if spec.terms is not None:
            derived.append(spec)
        for ref, _ in spec.terms or ():
            if isinstance(ref, _Spec):
                visit(ref)

    # Check ambiguous kernel identities before deduplicating the traversal.
    _constructions(tuple(planned))
    for spec in planned:
        visit(spec)
    for period in regs.periods:
        if (
            period.period_type in {"YTD", "FY"}
            and period.component_period_ids
            and not any(spec.own == period.period_id for spec in derived)
        ):
            visit(_period_spec(period, "FY" if period.period_type == "FY" else "YTD"))
    return tuple(derived)


def _lineage(computations: tuple[Computation, ...]) -> dict[str, PeriodValue]:
    """Include missing operands' evidence, which a null arithmetic root cannot carry."""
    result: dict[str, PeriodValue] = {}
    for node in computations:  # trace_cells emits children before their parent.
        values = (node.value, *(result[o.computation_id] for o in node.operands))
        result[node.computation_id] = node.value.model_copy(
            update={
                "observation_ids": tuple(
                    dict.fromkeys(i for v in values for i in v.observation_ids)
                ),
                "citations": tuple(dict.fromkeys(c for v in values for c in v.citations)),
            }
        )
    return result


def statement_history(
    pack: PreparedPack, review: FinancialReview, book_id: str
) -> StatementHistoryReport:
    source = statement_report(pack, review, book_id)
    review = FinancialReview.model_validate_json(review.model_dump_json())
    book = next(b for b in review.books if b.book_id == book_id)
    regs = Cp1Registers(_periods(book), (), (), (), (), (), (), book.currency, book.unit)
    specs = _derived_specs(regs)
    constructions = _constructions(specs)
    register = history._register(regs)
    items = tuple(dict.fromkeys((c.table_id, c.item_id) for c in source.cells))
    raw: dict[str, Cell] = {}
    operands: dict[str, tuple[tuple[PeriodReference, str], ...]] = {}
    comparisons: dict[str, str | None] = {}
    identities: list[tuple[str, str, Literal["T4.4", "T4.5", "T4.6"], str]] = []
    with localcontext(CONTEXT):
        for table, item in items:
            cells = {
                c.period_id: c for c in source.cells if (c.table_id, c.item_id) == (table, item)
            }
            series = history._Series("flow", {pid: _input(c) for pid, c in cells.items()})
            for spec in specs:
                identity = _id("statement-history", table, item, spec.column.column_id)
                construction = _id("period", spec.column.column_id)
                identities.append((identity, construction, table, item))
                raw[identity] = (
                    _closing(cells, book.periods, spec)
                    if table == "T4.6"
                    else history._flow(series, register, spec)
                )
                terms = []
                if table != "T4.6":
                    for i, (ref, sign) in enumerate(spec.terms or ()):
                        key = identity + f":term:{i}"
                        raw[key] = history._term(series, register, ref)
                        terms.append((_reference(ref, sign), key))
                operands[identity] = tuple(terms)
                stated = cells.get(spec.stated or "")
                comparison_key = identity + ":stated" if stated is not None else None
                if comparison_key and stated is not None:
                    raw[comparison_key] = _input(stated)
                comparisons[identity] = comparison_key
    computations, roots = trace_cells(raw, book)
    lineage = _lineage(computations)
    conflicts = {c.observation_id for c in source.cells if c.status == "conflicting"}
    values = []
    for identity, construction, table, item in identities:
        value = lineage[roots[identity]]
        # An unspanned period still retains its attempted component evidence.
        evidence = (value, *(lineage[roots[key]] for _, key in operands[identity]))
        ids = tuple(dict.fromkeys(i for v in evidence for i in v.observation_ids))
        if value.amount is None and conflicts.intersection(ids):
            value = value.model_copy(update={"calculation_status": "Conflicted"})
        value = value.model_copy(
            update={
                "observation_ids": ids,
                "citations": tuple(dict.fromkeys(c for v in evidence for c in v.citations)),
            }
        )
        comparison = comparisons[identity]
        values.append(
            StatementHistoricalValue(
                value_id=identity,
                construction_id=construction,
                table_id=table,
                item_id=item,
                value=value,
                computation_id=roots[identity],
                operands=tuple(
                    StatementPeriodOperand(reference=ref, computation_id=roots[key])
                    for ref, key in operands[identity]
                ),
                stated_computation_id=roots[comparison] if comparison else None,
            )
        )
    return StatementHistoryReport(
        source=source,
        periods=book.periods,
        columns=tuple(_id("period", spec.column.column_id) for spec in specs),
        constructions=constructions,
        values=tuple(values),
        computations=computations,
    )


def validate_statement_history(
    pack: PreparedPack, review: FinancialReview, report: StatementHistoryReport
) -> tuple[str, ...]:
    try:
        report = StatementHistoryReport.model_validate_json(report.model_dump_json())
        expected = statement_history(pack, review, report.source.book_id)
    except ValueError as error:
        return (f"Invalid statement history: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Statement history differs from trusted recomputation",)
    )
