"""Binding maps: module + table/row/fact coordinates -> report block and cell slot.

Maps are data (``cp0.py``, ``cp1.py``). A ``None`` table, row or fact id in a coordinate is
a wildcard, so a map names a table once instead of listing thousands of facts. Each
binding owns a distinct ``(block_id, cell_slot)``; no catch-all binding exists, so a fact
from a table the map does not name is reported, never silently placed.
"""

from collections import Counter
from collections.abc import Iterable
from typing import Self

from pydantic import model_validator

from deploy_vii.contracts import Contract, Fact, Identifier, Text, View
from deploy_vii.display import UnitClass
from deploy_vii.report_view import FactCoord, Section, pathways

# Modules whose facts reach the Front Page or module pages; the other statuses show none.
SHOWN_STATUSES = frozenset({"accepted", "restricted", "candidate"})
# Binding targets that are rail destinations, not Front Page blocks: the Evidence and
# Limitations pages and the issuer header. A map may name these without any Pathway block.
RAIL_DESTINATIONS = frozenset({"evidence", "limitations", "header"})


class Binding(Contract):
    fact_coord: FactCoord
    block_id: Identifier
    cell_slot: Identifier
    unit_class: UnitClass
    # Tab or section label when the block shows several registers; defaults to the slot words.
    label: Text | None = None
    # Prose column of a strengths-and-weaknesses block: the thesis, a strength or a weakness.
    section: Section | None = None

    @model_validator(mode="after")
    def names_more_than_a_module(self) -> Self:
        coord = self.fact_coord
        if coord.table_id is None and coord.row_id is None and coord.fact_id is None:
            raise ValueError(
                "An all-wildcard coordinate would bind every fact of the module: "
                "name a table, row or fact"
            )
        return self

    @property
    def title(self) -> str:
        return self.label or self.cell_slot.replace("-", " ").capitalize()

    @property
    def slot(self) -> tuple[str, str]:
        return (self.block_id, self.cell_slot)

    def matches(self, module_id: str, fact: Fact) -> bool:
        coord = self.fact_coord
        return (
            coord.module_id == module_id
            and coord.table_id in {None, fact.table_id}
            and coord.row_id in {None, fact.row_id}
            and coord.fact_id in {None, fact.fact_id}
        )


class BindingMap(Contract):
    module_id: Identifier
    entries: tuple[Binding, ...]

    @model_validator(mode="after")
    def stays_in_module(self) -> Self:
        if any(entry.fact_coord.module_id != self.module_id for entry in self.entries):
            raise ValueError("A binding map holds bindings for its own module only")
        return self


def _name(module_id: str, fact: Fact) -> str:
    return f"{module_id}/{fact.table_id}/{fact.row_id}/{fact.fact_id!r}"


def validate_bindings(view: View, maps: Iterable[BindingMap]) -> tuple[str, ...]:
    """One message per unbound or doubly bound fact, per shared slot and per repeated map.

    A fact in an accepted, restricted or candidate module must match exactly one binding in the
    run's Pathway. A register may be placed in several blocks when no Pathway composes more than
    one of them (T4.17 feeds FP 01's capital structure and FP 02's EBITDA adjustments), so a
    fact is doubly bound when two of its bindings name one block, or name two blocks the run's
    Pathway composes (a rail destination is composed everywhere). Empty when valid.
    """
    maps = tuple(maps)
    composed = RAIL_DESTINATIONS | set(
        next(item for item in pathways() if item.id == view.run.pathway).blocks
    )
    issues: list[str] = []
    for module_id, count in Counter(m.module_id for m in maps).items():
        if count > 1:
            issues.append(f"{module_id} has more than one binding map")
    entries = [entry for m in maps for entry in m.entries]
    for (block_id, cell_slot), count in Counter(e.slot for e in entries).items():
        if count > 1:
            issues.append(f"slot {block_id}/{cell_slot} is bound {count} times")
    by_module: dict[str, list[Binding]] = {}
    for entry in entries:
        by_module.setdefault(entry.fact_coord.module_id, []).append(entry)
    for module in view.modules:
        if module.status not in SHOWN_STATUSES:
            continue
        candidates = by_module.get(module.module_id, [])
        for fact in module.facts:
            hits = [e for e in candidates if e.matches(module.module_id, fact)]
            blocks = Counter(e.block_id for e in hits)
            placed = {block for block in blocks if block in composed}
            if not hits:
                issues.append(f"unbound fact {_name(module.module_id, fact)}")
            elif max(blocks.values()) > 1 or len(placed) > 1:
                slots = ", ".join(f"{e.block_id}/{e.cell_slot}" for e in hits)
                issues.append(f"doubly bound fact {_name(module.module_id, fact)}: {slots}")
    return tuple(issues)
