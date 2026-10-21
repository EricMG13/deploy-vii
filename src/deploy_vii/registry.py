"""r14 ownership and sequential dependency planning; aliases never create new work."""

import json
from functools import lru_cache
from importlib.resources import files

from deploy_vii.contracts import Contract, Identifier, Text


class Responsibility(Contract):
    module_id: Identifier
    title: Text
    aliases: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...]
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
        remaining["CP-5"] |= selected - {"CP-5", "CP-6", "CP-8", "CP-MEMO", "CP-MODEL", "CP-OS"}

    return remaining


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
