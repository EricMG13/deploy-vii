"""Serialize the kernel's actual immutable arithmetic graph without recalculating it."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Literal

from deploy_vii.contracts import Contract, Identifier, Text
from deploy_vii.financial_contracts import FinancialBook, Observation
from deploy_vii.financial_periods import PeriodValue, _evidence, _id, _value
from deploy_vii.financial_validation import records
from deploy_vii.model.frame import Cell


class ComputationOperand(Contract):
    computation_id: Identifier
    coefficient: int


class Computation(Contract):
    computation_id: Identifier
    operation: Literal["sum", "ratio_times", "input", "constant", "unavailable"]
    operands: tuple[ComputationOperand, ...]
    value: PeriodValue
    formula: Text
    arithmetic_context: Literal["decimal-38-half-even"] = "decimal-38-half-even"


_FORMULAS = {
    "sum": "sum(coefficient * operand value) in operand order; unknown component yields null",
    "ratio_times": "operand[0] / operand[1] * operand[2]; denominator must be positive",
    "input": "located input, retaining any recorded sign normalization",
    "constant": "kernel constant; not a sourced observation",
    "unavailable": "no calculable value; retain the missing reason and limitation",
}


def trace_cells(
    cells: Mapping[str, Cell], book: FinancialBook
) -> tuple[tuple[Computation, ...], dict[str, str]]:
    """Return a content-addressed DAG and each output ID's computation root.

    Shared subexpressions are visited once by object identity and identical
    nodes are deduplicated by complete content. No Python object IDs escape.
    """
    observations = {o.observation_id: o for o in records(book, Observation)}
    evidence = _evidence(book)
    nodes: dict[str, Computation] = {}
    visited: dict[int, str] = {}
    active: set[int] = set()

    def visit(cell: Cell) -> str:
        identity = id(cell)
        if identity in visited:
            return visited[identity]
        if identity in active:
            raise ValueError("Cyclic kernel arithmetic")
        active.add(identity)
        arithmetic = cell.arithmetic
        operands = (
            tuple(
                ComputationOperand(computation_id=visit(part), coefficient=sign)
                for part, sign in arithmetic.operands
            )
            if arithmetic is not None
            else ()
        )
        located = (
            replace(cell, sources=cell.input_sources, basis="REPORTED")
            if cell.input_sources
            else cell
        )
        value = _value(located, observations, evidence)
        operation: Literal["sum", "ratio_times", "input", "constant", "unavailable"]
        if arithmetic is not None:
            operation = arithmetic.operation
        elif located.sources:
            operation = "input"
        else:
            operation = "unavailable" if cell.value is None else "constant"
        node_id = _id(
            "computation",
            operation,
            value.content_hash(),
            *(f"{o.computation_id}:{o.coefficient}" for o in operands),
        )
        node = Computation(
            computation_id=node_id,
            operation=operation,
            operands=operands,
            value=value,
            formula=_FORMULAS[operation],
        )
        existing = nodes.get(node_id)
        if existing is not None and existing != node:
            raise ValueError("Conflicting computation identity")
        nodes[node_id] = node
        visited[identity] = node_id
        active.remove(identity)
        return node_id

    roots = {key: visit(cell) for key, cell in cells.items()}
    return tuple(nodes.values()), roots
