"""Strict response schemas for `response_format` and the matching null resolution on parse.

OpenAI strict mode (probe-2: HTTP 400 `invalid_json_schema`, "Missing 'limitation'") requires
every object to list all of its properties in `required` and to set `additionalProperties:
false`. Pydantic leaves defaulted fields out of `required`, so `strict_schema` rewrites a copy
of `model_json_schema()` (`strict_copy`): every property becomes required, a property that had
a default becomes nullable instead (`type` gains "null", `$ref`/union/const nodes are wrapped in
`anyOf` with `{"type": "null"}`), and `default` keywords are removed. The one exception is the
tag of a discriminated union: it stays required and non-null, because a null tag would leave the
branch unresolvable.

The copy that is sent (and printed in the prompt) is then relaxed (`relax`, task 2.11): OpenAI
refused the `source_context` schema (probe-5b 5ae16ef9, HTTP 400 `invalid_json_schema`, no
keyword named) while accepting the readiness schema, and the three constructs only the refused
one carried are rewritten on the way out: a nullable enum lists its values without null and is
nullable through its `type` (OpenAI's documented shape; "nullable-enum"), `const: v` becomes
`enum: [v]` ("const-to-enum"), and `minLength`/`maxLength` are dropped ("drop-length").
Round 3 (bisects schema-2026-10-22-bisect and -bisect2, OpenAI): a nullable array is sent as
`anyOf: [{type: "array", items, ...bounds}, {"type": "null"}]` instead of a `type` union
("nullable-array-anyof"), and `oneOf` + `discriminator` as `anyOf` ("oneof-anyof"); both are
lossless, because every such array defaults to `[]` and the stored contract keeps its tags.
Task 7.0d (E1 batch e1-cp1-3: 131 amounts sent as printed strings such as "3,624"): a `Number`
node, marked `DECIMAL_MARKER` by `financial_contracts`, is Pydantic's Decimal union `anyOf:
[{type: number, ...bounds}, {type: string}]` (null joins it when nullable). The sent copy keeps
the number branch with its bounds and any null branch and drops the string branch
("decimal-number-only"); the marker, not the shape, selects the node, so a genuine number-or-text
union is never rewritten, and a marked node of any other shape raises ValueError. The stored
contract still accepts a string amount (a stored payload replays unchanged).
Fix round 1: an id node marked `PREFIXED_ENUM_MARKER` (`StatementLine.item_id`,
`BalanceMovementBridge.balance_item_id`) is replaced whole by `anyOf` [{type: string, enum},
{type: string, pattern}] from the marker's lists ("prefixed-enum"): a listed r14 statement item
or an `other:` id. The flat list is a superset per statement; Python still enforces the split.
Task 7.0i (E1 batch e1-cp1-5: three `financials` attempts copied a wrong 64-hex
`context_step_sha256`): the model supplies no hash. A property marked `PREFILLED_MARKER` (its
value names the binding kind; every hash binding of the CP-1 step contracts carries one) is left
out of its object's `properties` and `required` ("drop-prefilled"), because Python fills it before
the journal validates (`live.submission.prefill`, which finds the marked properties of a payload
with `marked_fields`). A marker anywhere but on an object's property, or one whose value is not a
kind name, raises ValueError, so it never reaches the provider.
`pattern`, `format`, `minItems`, `maxItems`, `anyOf` and `$ref` are kept. The relaxation only
widens what the provider is asked to enforce: the reply is still validated by the unchanged
Pydantic contract, so every dropped constraint is still enforced on the way in.

The contracts are not changed. Before a payload reaches Pydantic, `normalise` replaces a null
that stands for an omitted defaulted field with that field's default, walking the payload with
the *original* schema (the same field list). A payload with nothing to resolve is returned
byte-for-byte; one that cannot be parsed is returned unchanged for the validator to reject.
`pattern`, `format` and the other keywords the fetched provider documentation does not list as
supported are kept and named by `unverified_keywords` for the attempt manifest, beside the
relaxations applied (`schema_relaxations`).
"""

import copy
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from deploy_vii.contracts import PREFILLED_MARKER as PREFILLED_MARKER
from deploy_vii.financial_contracts import DECIMAL_MARKER as DECIMAL_MARKER
from deploy_vii.financial_contracts import PREFIXED_ENUM_MARKER as PREFIXED_ENUM_MARKER

ANNOTATIONS = ("title", "description")
# Present in the step schemas; acceptance under strict mode is not stated in the fetched docs.
UNVERIFIED = frozenset(
    {
        "pattern",
        "minLength",
        "maxLength",
        "format",
        "const",
        "oneOf",
        "discriminator",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
    }
)
_REF = "#/$defs/"
# Relaxations of the sent copy, in the order the manifest lists them (see the module docstring).
RELAXATIONS = (
    "nullable-enum",
    "const-to-enum",
    "drop-length",
    "nullable-array-anyof",
    "oneof-anyof",
    "decimal-number-only",
    "prefixed-enum",
    "drop-prefilled",
)
_LENGTH = frozenset({"minLength", "maxLength"})
# The keywords a Decimal union's branches may carry (`_kind`); a later Pydantic may add a
# `pattern` to the string branch.
_NUMBER_KEYS = frozenset(
    {"type", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
)
_STRING_KEYS = frozenset({"type", "pattern"})
# Keys whose values are data (names, constants, defaults, marker lists), never schema nodes.
_DATA = frozenset({"enum", "const", "required", "default", "discriminator", PREFIXED_ENUM_MARKER})


def _nodes(node: object) -> Iterator[dict[str, Any]]:
    """Every schema node; property names, enum and const values are not nodes."""
    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if key in {"properties", "$defs"} and isinstance(value, dict):
                for child in value.values():
                    yield from _nodes(child)
            elif key not in _DATA:
                yield from _nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _nodes(item)


def _ref_name(node: dict[str, Any]) -> str | None:
    ref = node.get("$ref")
    return ref[len(_REF) :] if isinstance(ref, str) and ref.startswith(_REF) else None


def _tags(schema: dict[str, Any]) -> set[tuple[str, str]]:
    """(definition, property) pairs that tag a discriminated union branch."""
    tags: set[tuple[str, str]] = set()
    for node in _nodes(schema):
        discriminator = node.get("discriminator")
        if not isinstance(discriminator, dict):
            continue
        name = discriminator.get("propertyName")
        for branch in node.get("oneOf", ()):
            target = _ref_name(branch) if isinstance(branch, dict) else None
            if isinstance(name, str) and target is not None:
                tags.add((target, name))
    return tags


def _admits_null(node: dict[str, Any]) -> bool:
    kind = node.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind):
        return True
    if None in node.get("enum", ()) or ("const" in node and node["const"] is None):
        return True
    return any(isinstance(b, dict) and _admits_null(b) for b in node.get("anyOf", ()))


def _nullable(prop: dict[str, Any]) -> dict[str, Any]:
    """The property with null admitted; `prop` has no `default` keyword any more."""
    if _admits_null(prop):
        return prop
    if "anyOf" in prop:
        return {**prop, "anyOf": [*prop["anyOf"], {"type": "null"}]}
    if not ({"$ref", "oneOf", "allOf", "const"} & set(prop)) and "type" in prop:
        kind = prop["type"]
        # An enum keeps its values only: null is admitted by the type (OpenAI's documented
        # nullable-enum shape); `normalise` and Pydantic read the original schema, not this one.
        return {**prop, "type": [*(kind if isinstance(kind, list) else [kind]), "null"]}
    outer = {key: prop[key] for key in ANNOTATIONS if key in prop}
    inner = {key: value for key, value in prop.items() if key not in ANNOTATIONS}
    return {"anyOf": [inner, {"type": "null"}], **outer}


def _strict_object(node: dict[str, Any], tags: set[str]) -> None:
    properties: dict[str, Any] = node["properties"]
    required = set(node.get("required", ()))
    for name, prop in properties.items():
        if name not in required and isinstance(prop, dict) and name not in tags:
            properties[name] = _nullable(prop)
    node["required"] = list(properties)
    node["additionalProperties"] = False


def _strip_defaults(node: object) -> None:
    if isinstance(node, dict):
        node.pop("default", None)
        for key, value in node.items():
            if key in {"properties", "$defs"} and isinstance(value, dict):
                for child in value.values():
                    _strip_defaults(child)
            elif key not in {"enum", "const", "required", "discriminator"}:
                _strip_defaults(value)
    elif isinstance(node, list):
        for item in node:
            _strip_defaults(item)


def strict_copy(model: type[BaseModel]) -> dict[str, Any]:
    """A strict-mode copy of `model.model_json_schema()`; the model's own schema is untouched."""
    schema = copy.deepcopy(model.model_json_schema())
    tags = _tags(schema)
    _strip_defaults(schema)
    done: set[int] = set()
    for name, definition in schema.get("$defs", {}).items():
        if isinstance(definition, dict) and "properties" in definition:
            _strict_object(definition, {prop for owner, prop in tags if owner == name})
            done.add(id(definition))
    for node in list(_nodes(schema)):  # the root and any inline object
        if "properties" in node and id(node) not in done:
            _strict_object(node, set())
    return schema


def _nullable_enum(node: dict[str, Any]) -> bool:
    kind = node.get("type")
    return "enum" in node and isinstance(kind, list) and "null" in kind


def _relaxed_node(node: dict[str, Any]) -> dict[str, Any]:
    """One node (a fresh copy, children already relaxed) with its own keywords relaxed."""
    if "const" in node:
        if "enum" in node or node["const"] is None:
            raise ValueError(f"schema node cannot be relaxed (const beside enum, or null): {node}")
        node = {("enum" if key == "const" else key): value for key, value in node.items()}
        node["enum"] = [node["enum"]]
    if None in node.get("enum", ()):
        if not _nullable_enum(node):
            raise ValueError(f"schema node cannot be relaxed (null enum, no null type): {node}")
        node["enum"] = [value for value in node["enum"] if value is not None]
    if "oneOf" in node and "anyOf" in node:
        raise ValueError(f"schema node cannot be relaxed (oneOf beside anyOf): {node}")
    # Round 3 (bisects schema-2026-10-22-bisect and -bisect2): OpenAI refuses a nullable array
    # written as a type union and accepts the `anyOf` form; it refuses `oneOf` ("narrative").
    return _drop_prefilled(_prefixed_enum(_number_only(_array_to_any_of(_one_of_to_any_of(node)))))


def prefilled_kind(node: object) -> str | None:
    """The binding kind a schema node's `PREFILLED_MARKER` names (a non-empty string), or None."""
    kind = node.get(PREFILLED_MARKER) if isinstance(node, dict) else None
    return kind if isinstance(kind, str) and kind else None


def _drop_prefilled(node: dict[str, Any]) -> dict[str, Any]:
    """An object node without its `PREFILLED_MARKER` properties and their `required` entries
    ("drop-prefilled"); any other node is returned as it is. Children are relaxed first, so a
    marked property still carries its marker here; one left anywhere else is refused by
    `relax`."""
    properties = node.get("properties")
    if not isinstance(properties, dict):
        return node
    kept = {name: child for name, child in properties.items() if prefilled_kind(child) is None}
    if len(kept) == len(properties):
        return node
    out = {**node, "properties": kept}
    if isinstance(node.get("required"), list):
        out["required"] = [name for name in node["required"] if name in kept]
    return out


def _prefixed_enum(node: dict[str, Any]) -> dict[str, Any]:
    """A `PREFIXED_ENUM_MARKER` node replaced whole by `anyOf` [{string, enum}, {string,
    pattern}] from the marker's lists ("prefixed-enum"); annotations stay outside. Any other node
    is returned as it is; a marked node that is not a plain string (its own `pattern` aside, which
    the marker's two branches replace) or whose marker is not {enum: [str, ...], pattern: str}
    raises ValueError."""
    if PREFIXED_ENUM_MARKER not in node:
        return node
    marker = node[PREFIXED_ENUM_MARKER]
    own = {key for key in node if key not in {*ANNOTATIONS, PREFIXED_ENUM_MARKER}}
    if not (
        node.get("type") == "string"
        and own <= {"type", "pattern"}
        and isinstance(marker, dict)
        and set(marker) == {"enum", "pattern"}
        and isinstance(marker["enum"], list)
        and marker["enum"]
        and all(isinstance(value, str) for value in marker["enum"])
        and isinstance(marker["pattern"], str)
    ):
        raise ValueError(f"schema node cannot be relaxed (prefixed-enum marker): {node}")
    outer = {key: node[key] for key in ANNOTATIONS if key in node}
    listed = {"type": "string", "enum": list(marker["enum"])}
    return {**outer, "anyOf": [listed, {"type": "string", "pattern": marker["pattern"]}]}


def _kind(branch: object) -> str:
    """The kind of one Decimal union branch: number or string (keys within `_NUMBER_KEYS`,
    `_STRING_KEYS`), null, or other."""
    if branch == _NULL:
        return "null"
    for kind, keys in (("number", _NUMBER_KEYS), ("string", _STRING_KEYS)):
        if isinstance(branch, dict) and branch.get("type") == kind and set(branch) <= keys:
            return kind
    return "other"


def _number_only(node: dict[str, Any]) -> dict[str, Any]:
    """A `DECIMAL_MARKER` node without its string branch and marker ("decimal-number-only"): the
    number branch alone, or `anyOf` [number, null] where the node admits null. Any other node is
    returned as it is; a marked node whose `anyOf` is not one number and one string branch
    (and at most one null branch) raises ValueError."""
    if DECIMAL_MARKER not in node:
        return node
    branches: list[Any] = node["anyOf"] if isinstance(node.get("anyOf"), list) else []
    kinds = [_kind(branch) for branch in branches]
    if sorted(kinds) not in (["number", "string"], ["null", "number", "string"]):
        raise ValueError(f"schema node cannot be relaxed (decimal marker on another shape): {node}")
    outer = {key: value for key, value in node.items() if key not in {"anyOf", DECIMAL_MARKER}}
    kept = [branch for branch, kind in zip(branches, kinds, strict=True) if kind != "string"]
    return {**outer, "anyOf": kept} if len(kept) > 1 else {**kept[0], **outer}


Rule = Callable[[dict[str, Any]], dict[str, Any]]


def _map(node: object, rule: Rule) -> object:
    """A copy of `node` with `rule` applied to every schema node, children first; property
    names and data values (`_DATA`) are copied, never treated as nodes."""
    if isinstance(node, list):
        return [_map(item, rule) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in {"properties", "$defs"} and isinstance(value, dict):
            out[key] = {name: _map(child, rule) for name, child in value.items()}
        else:
            out[key] = copy.deepcopy(value) if key in _DATA else _map(value, rule)
    return rule(out)


def _map_schema(schema: dict[str, Any], rule: Rule) -> dict[str, Any]:
    mapped = _map(schema, rule)
    assert isinstance(mapped, dict)  # a dict maps to a dict
    return mapped


def _without(keys: frozenset[str]) -> Rule:
    return lambda node: {key: value for key, value in node.items() if key not in keys}


def relax(schema: dict[str, Any]) -> dict[str, Any]:
    """The sent copy of a strict schema (see the module docstring); pure and idempotent.

    A shape the relaxation cannot express (a null `const`, a null enum member whose type does
    not admit null, `const` beside `enum`) raises ValueError, so nothing is sent for it."""
    drop = _without(_LENGTH)
    sent = _map_schema(schema, lambda node: _relaxed_node(drop(node)))
    left = [node for node in _nodes(sent) if PREFILLED_MARKER in node]
    if left:
        raise ValueError(f"schema node cannot be relaxed (prefilled marker off a property): {left}")
    return sent


def relaxations(schema: dict[str, Any]) -> list[str]:
    """The relaxations the sent copy of `schema` (a strict copy) carries, in `RELAXATIONS` order.

    "nullable-enum" is reported by shape, not by a rewrite: it is named wherever the result
    relies on the documented nullable-enum reading (an enum under a type that admits null),
    whether `_nullable` built it or `relax` removed a null member. Manifests carry this note as
    `schema_relaxations_basis` (`RELAXATIONS_BASIS`)."""
    found = set()
    for node in _nodes(schema):
        if _nullable_enum(node):
            found.add("nullable-enum")
        if "const" in node:
            found.add("const-to-enum")
        if _LENGTH & set(node):
            found.add("drop-length")
        if _nullable_array(node):
            found.add("nullable-array-anyof")
        if "oneOf" in node:
            found.add("oneof-anyof")
        if DECIMAL_MARKER in node:
            found.add("decimal-number-only")
        if PREFIXED_ENUM_MARKER in node:
            found.add("prefixed-enum")
        if prefilled_kind(node) is not None:
            found.add("drop-prefilled")
    return [name for name in RELAXATIONS if name in found]


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The schema that is sent and printed in the prompt: the relaxed strict copy."""
    return relax(strict_copy(model))


def schema_relaxations(model: type[BaseModel]) -> list[str]:
    """The relaxations `strict_schema(model)` carries, for the attempt manifest."""
    return relaxations(strict_copy(model))


# --- bisect variants (`live schema-check --bisect`, task 2.11 fix round 1) ---------------------
#
# Each variant removes or rewrites ONE suspect class of the sent schema, so a provider's verdict
# on it says whether that class is what it refuses. They are only ever sent by the bisect and
# never reach a real run (whose schema is always `strict_schema`).

BISECT_VARIANTS = (
    "one-of-to-any-of",
    "drop-format",
    "drop-pattern",
    "drop-items-bounds",
    "open-object",
    "any-of-null-to-type-union",
    "split-mixed-types",
    # Fix round 2: the classes the first live bisect (2026-10-22) left open.
    "nullable-array-to-anyof",
    "nullable-array-required",
    "anyof-enum-null-to-type-union",
    "strip-titles",
    "inline-refs",
    "all",
)
OPEN_OBJECT = "open-object"  # detected and reported only: closing it would change the contract
# Never part of "all": a reply could no longer say null where the contract allows it.
NULLABLE_ARRAY_REQUIRED = "nullable-array-required"
_ARRAY_BOUNDS = ("items", "minItems", "maxItems")


class VariantRefused(ValueError):
    """A variant that cannot be built for this schema (a cyclic or unresolved `$ref`)."""


_NULL = {"type": "null"}
_JSON_TYPES: dict[type, str] = {
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
    type(None): "null",
}


def open_objects(schema: dict[str, Any]) -> int:
    """Nodes whose `additionalProperties` is present and not false (dict-valued fields)."""
    return sum(
        1
        for node in _nodes(schema)
        if "additionalProperties" in node and node["additionalProperties"] is not False
    )


def _one_of_to_any_of(node: dict[str, Any]) -> dict[str, Any]:
    if "oneOf" not in node or "anyOf" in node:
        return node
    return {("anyOf" if k == "oneOf" else k): v for k, v in node.items() if k != "discriminator"}


def _null_union(definitions: dict[str, Any]) -> Rule:
    """`anyOf: [X, {"type": "null"}]` -> X with `type: [T, "null"]` where X has one string type;
    a bare `$ref` X is inlined (one level: the inlined body keeps its own nodes as they are)."""

    def rule(node: dict[str, Any]) -> dict[str, Any]:
        branches = node.get("anyOf")
        if not isinstance(branches, list) or len(branches) != 2 or _NULL not in branches:
            return node
        others = [branch for branch in branches if branch != _NULL]
        other = others[0] if len(others) == 1 and isinstance(others[0], dict) else None
        if other is None:
            return node
        name = _ref_name(other)
        base = copy.deepcopy(definitions.get(name)) if name and set(other) == {"$ref"} else other
        if (
            not isinstance(base, dict)
            or not isinstance(base.get("type"), str)
            or {"anyOf", "oneOf", "allOf", "$ref"} & set(base)
        ):
            return node
        outer = {key: value for key, value in node.items() if key != "anyOf"}
        return {**base, **outer, "type": [base["type"], "null"]}

    return rule


def _split_types(node: dict[str, Any]) -> dict[str, Any]:
    """A mixed-type enum or a `type` array of more than two types -> `anyOf` of one branch per
    type; the node's other keywords stay on the outer node."""
    if "anyOf" in node:
        return node
    rest = {key: value for key, value in node.items() if key not in {"enum", "type"}}
    enum, kind = node.get("enum"), node.get("type")
    if isinstance(enum, list) and all(type(value) in _JSON_TYPES for value in enum):
        groups: dict[str, list[object]] = {}
        for value in enum:
            groups.setdefault(_JSON_TYPES[type(value)], []).append(value)
        if len(groups) > 1:
            branches = [
                _NULL if name == "null" else {"type": name, "enum": values}
                for name, values in groups.items()
            ]
            return {**rest, "anyOf": branches}
    if isinstance(kind, list) and len(kind) > 2 and "enum" not in node:
        return {**rest, "anyOf": [{"type": name} for name in kind]}
    return node


def _nullable_array(node: dict[str, Any]) -> str | None:
    """The array type of a `type: [X, "null"]` node with `items`; None for any other node."""
    kind = node.get("type")
    if not (isinstance(kind, list) and len(kind) == 2 and "null" in kind and "items" in node):
        return None
    (other,) = [name for name in kind if name != "null"]
    return str(other)


def _array_to_any_of(node: dict[str, Any]) -> dict[str, Any]:
    kind = _nullable_array(node)
    if kind is None:
        return node
    inner = {"type": kind, **{key: node[key] for key in _ARRAY_BOUNDS if key in node}}
    outer = {key: value for key, value in node.items() if key not in {"type", *_ARRAY_BOUNDS}}
    return {**outer, "anyOf": [inner, _NULL]}


def _array_required(node: dict[str, Any]) -> dict[str, Any]:
    kind = _nullable_array(node)
    return node if kind is None else {**node, "type": kind}


def _enum_null_union(node: dict[str, Any]) -> dict[str, Any]:
    """`anyOf: [{enum, type: T}, {"type": "null"}]` -> `type: [T, "null"]` with the enum; the
    enum branch carries nothing else (`any-of-null-to-type-union` without its other cases)."""
    branches = node.get("anyOf")
    if not isinstance(branches, list) or len(branches) != 2 or _NULL not in branches:
        return node
    others = [branch for branch in branches if branch != _NULL]
    other = others[0] if len(others) == 1 else None
    if not (
        isinstance(other, dict)
        and set(other) == {"enum", "type"}
        and isinstance(other["type"], str)
    ):
        return node
    outer = {key: value for key, value in node.items() if key != "anyOf"}
    return {**outer, "type": [other["type"], "null"], "enum": copy.deepcopy(other["enum"])}


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """`schema` with every `#/$defs/` reference replaced by its definition and `$defs` removed
    (a reference's own keywords override the definition's). A cycle or an unresolved reference
    raises VariantRefused: such a schema cannot be written without references."""
    definitions: dict[str, Any] = schema.get("$defs", {})

    def resolve(node: object, trail: tuple[str, ...]) -> object:
        if isinstance(node, list):
            return [resolve(item, trail) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = _ref_name(node)
            if name is None or name not in definitions:
                raise VariantRefused(f"unresolved $ref {node['$ref']!r}")
            if name in trail:
                raise VariantRefused(f"cyclic $ref: {' -> '.join((*trail, name))}")
            body = resolve(definitions[name], (*trail, name))
            rest = resolve({k: v for k, v in node.items() if k != "$ref"}, trail)
            assert isinstance(body, dict) and isinstance(rest, dict)  # a dict resolves to a dict
            return {**body, **rest}
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "$defs":
                continue
            if key == "properties" and isinstance(value, dict):
                out[key] = {name: resolve(child, trail) for name, child in value.items()}
            else:
                out[key] = copy.deepcopy(value) if key in _DATA else resolve(value, trail)
        return out

    resolved = resolve(schema, ())
    assert isinstance(resolved, dict)
    return resolved


def bisect_variant(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """`schema` with the one suspect class `name` removed or rewritten (pure). "all" applies
    every rewrite in order except `nullable-array-required`; "open-object" returns the schema
    unchanged (it is reported, not sent). An unknown name raises ValueError; "inline-refs" (and
    so "all") raises VariantRefused for a cyclic or unresolved `$ref`."""
    if name == "all":
        for each in BISECT_VARIANTS:
            if each not in {OPEN_OBJECT, NULLABLE_ARRAY_REQUIRED, "all"}:
                schema = bisect_variant(each, schema)
        return schema
    if name == "inline-refs":
        return _inline_refs(schema)
    rules: dict[str, Rule] = {
        "one-of-to-any-of": _one_of_to_any_of,
        "drop-format": _without(frozenset({"format"})),
        "drop-pattern": _without(frozenset({"pattern"})),
        "drop-items-bounds": _without(frozenset({"minItems", "maxItems"})),
        OPEN_OBJECT: lambda node: node,
        "any-of-null-to-type-union": _null_union(schema.get("$defs", {})),
        "split-mixed-types": _split_types,
        "nullable-array-to-anyof": _array_to_any_of,
        NULLABLE_ARRAY_REQUIRED: _array_required,
        "anyof-enum-null-to-type-union": _enum_null_union,
        "strip-titles": _without(frozenset({"title"})),
    }
    if name not in rules:
        raise ValueError(f"unknown bisect variant {name!r}; known: {', '.join(BISECT_VARIANTS)}")
    return _map_schema(schema, rules[name])


def _named_nodes(node: object, path: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """(owner.property path, node) for every schema node; `$defs` entries name their owner."""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            if key in {"properties", "$defs"} and isinstance(value, dict):
                for name, child in value.items():
                    yield from _named_nodes(
                        child, f"{path}.{name}" if key == "properties" else name
                    )
            elif key not in _DATA:
                yield from _named_nodes(value, path)
    elif isinstance(node, list):
        for item in node:
            yield from _named_nodes(item, path)


def nullable_array_fields(schema: dict[str, Any]) -> list[str]:
    """The `Owner.field` paths whose node is a nullable array (what `nullable-array-required`
    changes), in schema order; the root object is "(root)"."""
    return [path for path, node in _named_nodes(schema, "(root)") if _nullable_array(node)]


def schema_shape(schema: dict[str, Any]) -> str:
    """The text "depth D (O objects), P properties": D is the longest chain of schema nodes from
    the root with every `$ref` resolved, O the object nodes (with `properties`) on the deepest
    chain of objects, P the properties written in the root and every definition, each counted
    once. A cyclic or unresolved `$ref` gives "depth cyclic"."""
    properties = sum(len(node.get("properties", {})) for node in _nodes(schema))
    try:
        resolved = _inline_refs(schema)
    except VariantRefused:
        return f"depth cyclic, {properties} properties"

    def depth(node: object, objects: bool) -> int:
        if isinstance(node, list):
            return max((depth(item, objects) for item in node), default=0)
        if not isinstance(node, dict):
            return 0
        children = [
            depth(value, objects)
            for key, value in node.items()
            if key not in _DATA and key != "properties"
        ] + [depth(child, objects) for child in node.get("properties", {}).values()]
        own = 1 if not objects or "properties" in node else 0
        return own + max(children, default=0)

    return (
        f"depth {depth(resolved, False)} ({depth(resolved, True)} objects), {properties} properties"
    )


RELAXATIONS_BASIS = (
    "nullable-enum is named by shape: wherever the sent schema has an enum under a type that "
    "admits null (strict_copy already builds that shape); const-to-enum, drop-length, "
    "nullable-array-anyof and oneof-anyof are named where the strict copy had const, "
    "minLength or maxLength, a type: [array, null] node with items, or oneOf; "
    f"decimal-number-only where it had a {DECIMAL_MARKER} node (a Decimal amount, sent as a "
    f"JSON number only); prefixed-enum where it had a {PREFIXED_ENUM_MARKER} node (an id sent as "
    "a listed value or a prefixed id, e.g. a statement item or other:<id>); drop-prefilled where "
    f"it had a {PREFILLED_MARKER} property (a field Python fills before validation, so the "
    "model is not asked for it)"
)


def schema_keywords(schema: dict[str, Any]) -> list[str]:
    """Every JSON-Schema keyword the schema's nodes use, sorted; annotations left out."""
    return sorted({key for node in _nodes(schema) for key in node} - set(ANNOTATIONS))


def unverified_keywords(schema: dict[str, Any]) -> list[str]:
    """Keywords used by `schema` whose strict-mode acceptance is not documented (sorted)."""
    return sorted({key for node in _nodes(schema) for key in node} & UNVERIFIED)


# --- null resolution ---------------------------------------------------------------------


class _Unparseable(ValueError):
    pass


def _refuse_constant(name: str) -> object:
    raise _Unparseable(name)


class _Walker:
    def __init__(self, schema: dict[str, Any]) -> None:
        self.definitions: dict[str, Any] = schema.get("$defs", {})
        self.paths: list[str] = []

    def resolve(self, node: object) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        name = _ref_name(node)
        return self.resolve(self.definitions.get(name)) if name is not None else node

    def branch(self, node: dict[str, Any], value: object) -> dict[str, Any] | None:
        """The one union branch `value` can belong to; None when it is not determined."""
        discriminator = node.get("discriminator")
        if isinstance(discriminator, dict) and isinstance(value, dict):
            target = discriminator.get("mapping", {}).get(value.get(discriminator["propertyName"]))
            return self.resolve({"$ref": target}) if isinstance(target, str) else None
        options = [self.resolve(b) for b in (*node.get("anyOf", ()), *node.get("oneOf", ()))]
        key = "properties" if isinstance(value, dict) else "items"
        matches = [option for option in options if key in option]
        return matches[0] if len(matches) == 1 else None

    def fill(self, node: object, value: object, path: str) -> None:
        schema = self.resolve(node)
        if isinstance(value, dict) and "properties" in schema:
            required = set(schema.get("required", ()))
            for name, prop in schema["properties"].items():
                if name not in value:
                    continue
                spec = self.resolve(prop) if "$ref" in prop else prop
                if (
                    value[name] is None
                    and name not in required
                    and "default" in prop
                    and not _admits_null(spec)
                ):
                    value[name] = copy.deepcopy(prop["default"])
                    self.paths.append(f"{path}{name}")
                else:
                    self.fill(prop, value[name], f"{path}{name}.")
        elif isinstance(value, list) and "items" in schema:
            for index, item in enumerate(value):
                self.fill(schema["items"], item, f"{path}{index}.")
        elif "anyOf" in schema or "oneOf" in schema:
            chosen = self.branch(schema, value)
            if chosen is not None:
                self.fill(chosen, value, path)


@dataclass(frozen=True)
class Marked:
    """One `PREFILLED_MARKER` property of a payload object, present or not: its JSON path, the
    object that holds it, the binding kind and the enclosing objects by their `$defs` name
    (outermost first)."""

    path: str
    holder: dict[str, Any]
    name: str
    kind: str
    within: tuple[tuple[str, dict[str, Any]], ...]

    def enclosing(self, definition: str) -> dict[str, Any] | None:
        """The innermost enclosing object of `definition`, or None."""
        return next((obj for name, obj in reversed(self.within) if name == definition), None)


def marked_fields(model: type[BaseModel], document: dict[str, Any]) -> tuple[Marked, ...]:
    """Every marked property of `document`, walked with `model`'s own schema as `normalise`
    walks it (a union branch only where it is determined), in document order."""
    schema = model.model_json_schema()
    walker = _Walker(schema)
    found: list[Marked] = []

    def visit(node: object, value: object, path: str, within: tuple[Any, ...]) -> None:
        name = _ref_name(node) if isinstance(node, dict) else None
        if name is not None and isinstance(value, dict):
            within = (*within, (name, value))
        spec = walker.resolve(node)
        if isinstance(value, dict) and "properties" in spec:
            for key, prop in spec["properties"].items():
                kind = prefilled_kind(prop)
                if kind is not None:
                    found.append(Marked(f"{path}{key}", value, key, kind, within))
                elif key in value:
                    visit(prop, value[key], f"{path}{key}.", within)
        elif isinstance(value, list) and "items" in spec:
            for index, item in enumerate(value):
                visit(spec["items"], item, f"{path}{index}.", within)
        elif "anyOf" in spec or "oneOf" in spec:
            chosen = walker.branch(spec, value)
            if chosen is not None:
                visit(chosen, value, path, within)

    visit(schema, document, "", ())
    return tuple(found)


def json_object(payload: str) -> dict[str, Any] | None:
    """`payload` parsed as a JSON object, floats as Decimal (`exact_json` keeps their digits);
    None for anything else: invalid or truncated JSON, NaN or Infinity, or a non-object."""
    try:
        document = json.loads(payload, parse_float=Decimal, parse_constant=_refuse_constant)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def exact_json(value: object) -> str:
    """JSON text that keeps every parsed number's exact digits (floats were parsed as Decimal)."""
    if isinstance(value, dict):
        return "{" + ",".join(f"{json.dumps(k)}:{exact_json(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(exact_json(item) for item in value) + "]"
    if isinstance(value, Decimal):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def normalise(model: type[BaseModel], payload: str) -> tuple[str, tuple[str, ...]]:
    """Resolve nulls that stand for omitted defaulted fields; return the payload and the paths.

    Unchanged (same string, no paths) when nothing needed resolving or the text is not a JSON
    object; Pydantic then reports whatever is wrong with it."""
    document = json_object(payload)
    if document is None:
        return payload, ()
    walker = _Walker(model.model_json_schema())
    walker.fill(model.model_json_schema(), document, "")
    if not walker.paths:
        return payload, ()
    return exact_json(document), tuple(walker.paths)
