"""r14 ownership and sequential dependency planning; aliases never create new work."""

import json
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from pydantic import Field

from deploy_vii.contracts import Contract, Identifier, Run, Status, Text

EdgeRule = Literal["block", "restricted"]

# CP-5 follows every selected analyst, CP-MODEL included (DC-5); challenge, exports and OS do not.
_NOT_CP5_FAN_IN = frozenset({"CP-5", "CP-6", "CP-8", "CP-MEMO", "CP-OS"})


class Responsibility(Contract):
    module_id: Identifier
    title: Text
    aliases: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...]
    edge_rules: dict[str, EdgeRule] = Field(default_factory=dict)
    purpose: Text
    table_ids: tuple[str, ...]


@lru_cache(maxsize=1)
def modules() -> tuple[Responsibility, ...]:
    raw = json.loads(files("deploy_vii").joinpath("methodology.json").read_text())
    return tuple(Responsibility.model_validate_json(json.dumps(row)) for row in raw)


def canonical(entry: str) -> str:
    for module in modules():
        if entry == module.module_id or entry in module.aliases:
            return module.module_id
    raise ValueError(f"Unknown r14 entry: {entry}")


def dependencies(requested: tuple[str, ...]) -> dict[str, set[str]]:
    catalog = {module.module_id: module for module in modules()}
    selected = {canonical(entry) for entry in requested}
    pending = list(selected)
    while pending:
        for dependency in catalog[pending.pop()].required:
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)

    # Optional dependencies constrain execution only when selected.
    remaining = {
        module_id: set(catalog[module_id].required) | (set(catalog[module_id].optional) & selected)
        for module_id in selected
    }
    if "CP-5" in selected:
        # QA follows every selected analyst; challenge and exports follow QA.
        remaining["CP-5"] |= selected - _NOT_CP5_FAN_IN

    return remaining


def edge_rule(consumer: str, producer: str) -> EdgeRule:
    """Degradation rule of one dependency edge (decision 0007).

    An explicit `edge_rules` entry wins. Otherwise a required producer blocks its
    consumer and an optional one, or CP-5's fan-in over analysts, restricts it.
    """
    entry = next((module for module in modules() if module.module_id == consumer), None)
    if entry is not None:
        if producer in entry.edge_rules:
            return entry.edge_rules[producer]
        if producer in entry.required:
            return "block"
        if producer in entry.optional or (
            consumer == "CP-5"
            and producer not in _NOT_CP5_FAN_IN
            and any(module.module_id == producer for module in modules())
        ):
            return "restricted"
    raise ValueError(f"No dependency edge from {producer} to {consumer}")


def idle_statuses(run: Run) -> dict[str, Status]:
    """Status of every registry module before it runs: ``unrun`` in scope, else ``not_in_pathway``.

    Scope is the run's requested modules plus their required producers (decision 0009); an
    unknown module id raises rather than silently widening or narrowing the scope. Every view
    builder takes its not-yet-run statuses from here.
    """
    in_scope = set(dependencies(run.requested_modules))
    return {
        m.module_id: "unrun" if m.module_id in in_scope else "not_in_pathway" for m in modules()
    }


def plan(requested: tuple[str, ...]) -> tuple[str, ...]:
    remaining = dependencies(requested)
    ordered: list[str] = []
    while remaining:
        ready = [
            module.module_id
            for module in modules()
            if module.module_id in remaining and not remaining[module.module_id]
        ]
        if not ready:
            raise ValueError("cyclic selected module dependencies")
        for module_id in ready:
            ordered.append(module_id)
            del remaining[module_id]
            for required in remaining.values():
                required.discard(module_id)
    return tuple(ordered)
