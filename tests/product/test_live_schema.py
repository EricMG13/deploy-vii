"""Strict response schemas: every property required, defaults nullable, nulls resolved back."""

import json
import re
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from deploy_vii.contracts import Identifier
from deploy_vii.financial_contracts import Alternative, Observation
from deploy_vii.live import schema as strict
from deploy_vii.live.prompts import response_format, schema_text
from deploy_vii.live.runner import STEPS
from deploy_vii.readiness import ReadinessReview
from deploy_vii.statement_validation import OPTIONAL_ITEMS, REQUIRED_ITEMS
from tests.product import replay_support
from tests.product.test_readiness import readiness_fixture

# OpenAI Structured Outputs, strict mode: keywords listed as unsupported (task 2.7a inputs).
UNSUPPORTED = {
    "unevaluatedProperties",
    "propertyNames",
    "minProperties",
    "maxProperties",
    "unevaluatedItems",
    "contains",
    "minContains",
    "maxContains",
    "uniqueItems",
}
SCHEMAS = {step: definition.schema for step, definition in STEPS.items()}


def nodes(node: object) -> Iterator[dict[str, Any]]:
    """Every schema object node, including those under `$defs`, `properties` and `items`."""
    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                for child in value.values():
                    yield from nodes(child)
            elif key not in {"enum", "const", "required"}:
                yield from nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from nodes(item)


@pytest.mark.parametrize("step", sorted(SCHEMAS))
def test_every_object_requires_all_properties_and_forbids_extras(step: str) -> None:
    transformed = strict.strict_schema(SCHEMAS[step])
    assert "$defs" in transformed  # definitions stay inside the schema object
    objects = [n for n in nodes(transformed) if "properties" in n]
    assert objects
    for node in objects:
        assert node["required"] == list(node["properties"]), node.get("title")
        assert node["additionalProperties"] is False, node.get("title")
    # No free-form object is left for strict mode to refuse.
    free = [n for n in nodes(transformed) if n.get("type") == "object" and "properties" not in n]
    assert not free


@pytest.mark.parametrize("step", sorted(SCHEMAS))
def test_transformed_schema_has_no_unsupported_keyword_and_no_default(step: str) -> None:
    transformed = strict.strict_schema(SCHEMAS[step])
    used = {key for node in nodes(transformed) for key in node}
    assert not used & UNSUPPORTED
    assert "default" not in used


def test_defaulted_fields_become_nullable_and_required_fields_do_not() -> None:
    transformed = strict.strict_schema(ReadinessReview)
    root = transformed["properties"]
    assert root["schema_version"] == {  # the sent copy: `const` is sent as a one-value enum
        "anyOf": [{"enum": ["readiness-review/1"], "type": "string"}, {"type": "null"}],
        "title": "Schema Version",
    }
    assert root["pack_sha256"]["type"] == "string"  # required: not made nullable
    consumer = transformed["$defs"]["ConsumerReadiness"]["properties"]
    # The strict copy makes a defaulted array nullable through its type; the sent copy says the
    # same as an `anyOf` (task 2.11 round 3, OpenAI's accepted form).
    copied = strict.strict_copy(ReadinessReview)["$defs"]["ConsumerReadiness"]["properties"]
    assert copied["limitations"]["type"] == ["array", "null"]
    assert consumer["limitations"]["anyOf"][1] == {"type": "null"}
    assert consumer["limitations"]["anyOf"][0]["type"] == "array"
    assert consumer["missing_source"]["anyOf"].count({"type": "null"}) == 1
    claim = transformed["$defs"]["Claim"]["properties"]
    assert {"type": "null"} in claim["limitation"]["anyOf"]
    # A defaulted enum is nullable through its type only (OpenAI's documented shape): null is
    # never a member of the enum (task 2.11).
    context = strict.strict_schema(SCHEMAS["source_context"])
    scan = context["$defs"]["SourceContext"]["properties"]["event_scan"]
    assert scan == {
        "enum": ["events_identified", "no_events_identified", "unassessed"],
        "title": "Event Scan",
        "type": ["string", "null"],
    }


def test_transform_is_pure() -> None:
    before = ReadinessReview.model_json_schema()
    strict.strict_schema(ReadinessReview)
    assert ReadinessReview.model_json_schema() == before


def test_union_discriminators_stay_required_and_non_null() -> None:
    transformed = strict.strict_schema(SCHEMAS["narrative"])
    tags = [
        node["properties"]["kind"]
        for node in nodes(transformed)
        if "properties" in node and "kind" in node["properties"]
    ]
    assert tags
    for tag in tags:
        assert "anyOf" not in tag and tag.get("type") == "string" and "const" not in tag
        assert len(tag["enum"]) == 1  # the tag's constant, sent as a one-value enum


@pytest.mark.parametrize("step_id", sorted(SCHEMAS))
def test_prompt_schema_text_is_the_strict_response_schema(step_id: str) -> None:
    """One source of truth (decision 0008): the system prompt prints exactly the schema that
    `response_format` sends, not Pydantic's untransformed one."""
    model = SCHEMAS[step_id]
    fmt = response_format(step_id, model)
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == strict.strict_schema(model)
    assert json.loads(schema_text(model)) == fmt["json_schema"]["schema"]
    assert schema_text(model) == json.dumps(
        fmt["json_schema"]["schema"], sort_keys=True, separators=(",", ":")
    )
    untransformed = json.dumps(model.model_json_schema(), sort_keys=True, separators=(",", ":"))
    # The 0008 submissions (CP-0's and, task 7.2, CP-1A's) have no defaults, so they are already
    # strict as Pydantic writes them; the stored contracts the CP-1 steps still send are not.
    assert (schema_text(model) == untransformed) is (
        step_id in {"source_readiness", "business_context"}
    )


def test_unverified_keywords_are_listed_not_stripped() -> None:
    found = strict.unverified_keywords(strict.strict_schema(ReadinessReview))
    assert "pattern" in found and found == sorted(found)
    context = strict.unverified_keywords(strict.strict_schema(SCHEMAS["source_context"]))
    assert "format" in context
    transformed = json.dumps(strict.strict_schema(ReadinessReview))
    assert '"pattern"' in transformed


# --- sent-schema relaxation (task 2.11, probe-5b source_context HTTP 400) -----------------


def sent_keys(schema: dict[str, Any]) -> set[str]:
    return {key for node in nodes(schema) for key in node}


@pytest.mark.parametrize("step", sorted(SCHEMAS))
def test_sent_schema_has_no_const_no_length_and_no_null_enum_member(step: str) -> None:
    sent = strict.strict_schema(SCHEMAS[step])
    assert not sent_keys(sent) & {"const", "minLength", "maxLength"}
    assert not [n for n in nodes(sent) if None in n.get("enum", ())]
    # The rewritten and dropped keywords are not named as unverified either.
    assert not {"const", "minLength", "maxLength"} & set(strict.unverified_keywords(sent))


def test_source_context_sent_schema_keeps_every_other_constraint() -> None:
    strict_copy = strict.strict_copy(SCHEMAS["source_context"])
    sent = strict.strict_schema(SCHEMAS["source_context"])
    assert {"const", "minLength", "maxLength"} <= sent_keys(strict_copy)  # what 5ae16ef9 sent
    kept = {"pattern", "format", "maxItems", "anyOf", "$ref", "enum", "additionalProperties"}
    assert kept <= sent_keys(sent)
    assert sent_keys(sent) == sent_keys(strict_copy) - {"const", "minLength", "maxLength"}
    patterns = sorted({n["pattern"] for n in nodes(sent) if "pattern" in n})
    assert patterns == sorted({n["pattern"] for n in nodes(strict_copy) if "pattern" in n})
    assert strict.schema_relaxations(SCHEMAS["source_context"]) == [
        "nullable-enum",
        "const-to-enum",
        "drop-length",
        "nullable-array-anyof",
    ]


def test_the_readiness_submission_keeps_min_items_and_needs_no_relaxation() -> None:
    model = SCHEMAS["source_readiness"]
    sent = strict.strict_schema(model)
    assert sent == strict.strict_copy(model)  # cf6bf65b's accepted schema, unchanged
    assert strict.schema_relaxations(model) == []
    assert '"minItems":1' in json.dumps(sent, separators=(",", ":"))


@pytest.mark.parametrize("step", sorted(SCHEMAS))
def test_relaxation_is_idempotent_and_pure(step: str) -> None:
    model = SCHEMAS[step]
    before = model.model_json_schema()
    strict_copy = strict.strict_copy(model)
    snapshot = json.dumps(strict_copy, sort_keys=True)
    once = strict.relax(strict_copy)
    assert json.dumps(strict_copy, sort_keys=True) == snapshot  # the input is not mutated
    assert strict.relax(once) == once == strict.strict_schema(model)
    assert model.model_json_schema() == before


# --- round 3: the forms the bisects showed OpenAI accepts (schema-2026-10-22-bisect, -bisect2)


@pytest.mark.parametrize("step", sorted(SCHEMAS))
def test_sent_schemas_have_no_nullable_array_type_union_and_no_one_of(step: str) -> None:
    sent = strict.strict_schema(SCHEMAS[step])
    assert not [n for n in nodes(sent) if isinstance(n.get("type"), list) and "array" in n["type"]]
    assert not {"oneOf", "discriminator"} & sent_keys(sent)
    assert strict.relax(sent) == sent


def test_relaxations_name_the_nullable_array_and_one_of_rewrites() -> None:
    assert strict.RELAXATIONS == (
        "nullable-enum",
        "const-to-enum",
        "drop-length",
        "nullable-array-anyof",
        "oneof-anyof",
        "decimal-number-only",
        "prefixed-enum",
        "drop-prefilled",
    )
    assert strict.schema_relaxations(SCHEMAS["narrative"]) == [
        "const-to-enum",
        "drop-length",
        "nullable-array-anyof",
        "oneof-anyof",
    ]
    assert "nullable-array-anyof" in strict.schema_relaxations(SCHEMAS["readiness"])
    assert "nullable-array-anyof" in strict.schema_relaxations(SCHEMAS["financials"])


def test_a_nullable_array_is_sent_as_an_any_of_and_one_of_without_discriminator() -> None:
    node = {"type": ["array", "null"], "items": {"type": "string"}, "maxItems": 3, "title": "A"}
    assert strict.relax(node) == {
        "title": "A",
        "anyOf": [{"type": "array", "items": {"type": "string"}, "maxItems": 3}, {"type": "null"}],
    }
    assert strict.relaxations(node) == ["nullable-array-anyof"]
    union = {
        "oneOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}],
        "discriminator": {"propertyName": "kind", "mapping": {"a": "#/$defs/A"}},
        "title": "U",
    }
    assert strict.relax(union) == {
        "anyOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}],
        "title": "U",
    }
    assert strict.relaxations(union) == ["oneof-anyof"]


def test_a_nullable_enum_that_still_lists_null_loses_it_and_the_rest_is_kept() -> None:
    node = {"type": ["string", "null"], "enum": ["a", None, "b"], "title": "T"}
    assert strict.relax(node) == {"type": ["string", "null"], "enum": ["a", "b"], "title": "T"}
    assert strict.relaxations(node) == ["nullable-enum"]
    nested = {"properties": {"minLength": {"type": "string", "minLength": 1, "maxLength": 3}}}
    # A property that happens to be called minLength is a name, not a keyword: it stays.
    assert strict.relax(nested) == {"properties": {"minLength": {"type": "string"}}}
    assert strict.relaxations(nested) == ["drop-length"]


@pytest.mark.parametrize(
    "node",
    [
        {"const": None},
        {"enum": ["a", None], "type": "string"},
        {"enum": ["a", None]},
        {"const": "a", "enum": ["a", "b"]},
    ],
    ids=["const-null", "null-enum-non-null-type", "null-enum-untyped", "const-beside-enum"],
)
def test_shapes_the_relaxation_cannot_express_fail_closed(node: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="cannot be relaxed"):
        strict.relax({"properties": {"x": node}})


# --- bisect variants (task 2.11 fix round 1): report-only, never sent by a real run ------------


def test_bisect_variants_run_in_the_coordinators_order() -> None:
    assert strict.BISECT_VARIANTS == (
        "one-of-to-any-of",
        "drop-format",
        "drop-pattern",
        "drop-items-bounds",
        "open-object",
        "any-of-null-to-type-union",
        "split-mixed-types",
        "nullable-array-to-anyof",
        "nullable-array-required",
        "anyof-enum-null-to-type-union",
        "strip-titles",
        "inline-refs",
        "all",
    )


def test_the_one_of_variant_sends_the_narrative_unions_as_any_of_without_discriminator() -> None:
    sent = strict.strict_copy(SCHEMAS["narrative"])  # what was sent before round 3
    snapshot = json.dumps(sent, sort_keys=True)
    variant = strict.bisect_variant("one-of-to-any-of", sent)
    keywords = set(strict.schema_keywords(sent))
    assert {"oneOf", "discriminator"} <= keywords
    assert set(strict.schema_keywords(variant)) == keywords - {"oneOf", "discriminator"}
    assert json.dumps(sent, sort_keys=True) == snapshot  # pure


@pytest.mark.parametrize(
    "name, gone",
    [
        ("drop-format", {"format"}),
        ("drop-pattern", {"pattern"}),
        ("drop-items-bounds", {"minItems", "maxItems"}),
    ],
)
def test_a_drop_variant_removes_only_its_keywords(name: str, gone: set[str]) -> None:
    sent = strict.strict_schema(SCHEMAS["source_context"])
    assert gone <= sent_keys(sent)
    assert sent_keys(strict.bisect_variant(name, sent)) == sent_keys(sent) - gone


def test_the_null_union_variant_merges_two_branch_null_unions_and_inlines_a_ref() -> None:
    definition = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    schema: dict[str, Any] = {
        "$defs": {"D": definition},
        "type": "object",
        "properties": {
            "r": {"anyOf": [{"$ref": "#/$defs/D"}, {"type": "null"}], "title": "R"},
            "d": {"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}]},
            "e": {"anyOf": [{"enum": ["a"], "type": "string"}, {"type": "null"}]},
            "three": {"anyOf": [{"type": "number"}, {"type": "string"}, {"type": "null"}]},
            "union": {"anyOf": [{"$ref": "#/$defs/D"}, {"type": "string"}]},
            "typed": {"anyOf": [{"type": ["string", "number"]}, {"type": "null"}]},
        },
    }
    merged = strict.bisect_variant("any-of-null-to-type-union", schema)["properties"]
    assert merged["r"] == {**definition, "type": ["object", "null"], "title": "R"}
    assert merged["d"] == {"format": "date", "type": ["string", "null"]}
    assert merged["e"] == {"enum": ["a"], "type": ["string", "null"]}
    for name in ("three", "union", "typed"):  # not a two-branch union with one simple type
        assert merged[name] == schema["properties"][name]
    sent = strict.bisect_variant(
        "any-of-null-to-type-union", strict.strict_schema(SCHEMAS["source_context"])
    )
    assert not [
        n for n in nodes(sent) if len(n.get("anyOf", ())) == 2 and {"type": "null"} in n["anyOf"]
    ]


def test_the_split_variant_rewrites_mixed_enums_and_long_type_arrays() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "m": {"enum": ["a", 1, None], "title": "M"},
            "t": {"type": ["string", "number", "null"], "title": "T"},
            "ok": {"type": ["string", "null"], "enum": ["x"]},
            "odd": {"enum": ["a", [1]]},
        }
    }
    split = strict.bisect_variant("split-mixed-types", schema)["properties"]
    assert split["m"] == {
        "title": "M",
        "anyOf": [
            {"type": "string", "enum": ["a"]},
            {"type": "integer", "enum": [1]},
            {"type": "null"},
        ],
    }
    assert split["t"] == {
        "title": "T",
        "anyOf": [{"type": "string"}, {"type": "number"}, {"type": "null"}],
    }
    assert split["ok"] == schema["properties"]["ok"]
    assert split["odd"] == schema["properties"]["odd"]  # a non-scalar value: left as it is


def test_open_objects_are_counted_never_rewritten_and_absent_from_the_step_schemas() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "free": {"type": "object", "additionalProperties": {"type": "number"}},
            "closed": {"type": "object", "properties": {}, "additionalProperties": False},
        }
    }
    assert strict.open_objects(schema) == 1
    assert strict.bisect_variant("open-object", schema) == schema
    assert all(strict.open_objects(strict.strict_schema(model)) == 0 for model in SCHEMAS.values())


@pytest.mark.parametrize("step", sorted(SCHEMAS))
def test_the_all_variant_is_every_rewrite_at_once(step: str) -> None:
    sent = strict.strict_schema(SCHEMAS[step])
    composed = sent
    for name in strict.BISECT_VARIANTS:
        if name not in {"open-object", "nullable-array-required", "all"}:
            composed = strict.bisect_variant(name, composed)
    every = strict.bisect_variant("all", sent)
    assert every == composed
    gone = {"oneOf", "discriminator", "format", "pattern", "minItems", "maxItems", "title", "$ref"}
    assert not (gone | {"$defs"}) & set(every) and not gone & sent_keys(every)
    # "all" never drops null from an array (that variant changes what a reply may say): every
    # nullable array is an `anyOf` with a null branch instead.
    assert not [n for n in nodes(every) if isinstance(n.get("type"), list) and "array" in n["type"]]
    nullable = [
        n
        for n in nodes(every)
        if {"type": "null"} in n.get("anyOf", ())
        and any(b.get("type") == "array" for b in n["anyOf"])
    ]
    assert len(nullable) >= len(strict.nullable_array_fields(sent))


# --- fix round 2: the classes the first live bisect left open --------------------------------


def nullable_arrays() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "a": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "maxItems": 3,
                "title": "A",
            },
            "s": {"type": ["string", "null"], "title": "S"},
            "b": {"type": "array", "items": {"type": "string"}},
        },
    }


def test_the_nullable_array_variant_sends_an_any_of_with_the_array_bounds_inside() -> None:
    out = strict.bisect_variant("nullable-array-to-anyof", nullable_arrays())["properties"]
    assert out["a"] == {
        "title": "A",
        "anyOf": [{"type": "array", "items": {"type": "string"}, "maxItems": 3}, {"type": "null"}],
    }
    assert out["s"] == nullable_arrays()["properties"]["s"]  # not an array
    assert out["b"] == nullable_arrays()["properties"]["b"]  # not nullable
    sent = strict.bisect_variant(
        "nullable-array-to-anyof", strict.strict_copy(SCHEMAS["source_context"])
    )
    assert not [n for n in nodes(sent) if isinstance(n.get("type"), list) and "array" in n["type"]]


def test_the_required_array_variant_drops_null_and_names_the_fields_it_touches() -> None:
    out = strict.bisect_variant("nullable-array-required", nullable_arrays())["properties"]
    assert out["a"] == {"type": "array", "items": {"type": "string"}, "maxItems": 3, "title": "A"}
    assert out["s"] == nullable_arrays()["properties"]["s"]
    assert strict.nullable_array_fields(nullable_arrays()) == ["(root).a"]
    readiness = strict.strict_copy(SCHEMAS["readiness"])  # what was sent before round 3
    assert strict.nullable_array_fields(strict.strict_schema(SCHEMAS["readiness"])) == []
    assert set(strict.nullable_array_fields(readiness)) == {
        "(root).consumers",
        "ConsumerAssessment.requirements",
        "ConsumerAssessment.gaps",
        "RequirementAssessment.actions",
    }
    assert (
        strict.nullable_array_fields(strict.bisect_variant("nullable-array-required", readiness))
        == []
    )


def test_the_enum_null_variant_merges_only_enum_branches() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "e": {"anyOf": [{"enum": ["a"], "type": "string"}, {"type": "null"}], "title": "E"},
            "d": {"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}]},
            "r": {"anyOf": [{"$ref": "#/$defs/D"}, {"type": "null"}]},
            "two": {"anyOf": [{"enum": ["a"], "type": "string"}, {"type": "integer"}]},
        }
    }
    out = strict.bisect_variant("anyof-enum-null-to-type-union", schema)["properties"]
    assert out["e"] == {"title": "E", "type": ["string", "null"], "enum": ["a"]}
    for name in ("d", "r", "two"):
        assert out[name] == schema["properties"][name]


def test_strip_titles_keeps_a_property_named_title() -> None:
    schema = {"title": "Root", "properties": {"title": {"type": "string", "title": "Title"}}}
    assert strict.bisect_variant("strip-titles", schema) == {
        "properties": {"title": {"type": "string"}}
    }
    sent = strict.strict_schema(SCHEMAS["financials"])
    assert "title" in sent_keys(sent)
    assert "title" not in sent_keys(strict.bisect_variant("strip-titles", sent))


def test_inline_refs_resolves_definition_chains_and_refuses_a_cycle() -> None:
    schema: dict[str, Any] = {
        "$defs": {
            "A": {"type": "object", "properties": {"b": {"$ref": "#/$defs/B"}}},
            "B": {"type": "string", "title": "B"},
        },
        "type": "object",
        "properties": {"x": {"$ref": "#/$defs/A", "description": "d"}},
    }
    assert strict.bisect_variant("inline-refs", schema) == {
        "type": "object",
        "properties": {
            "x": {
                "type": "object",
                "properties": {"b": {"type": "string", "title": "B"}},
                "description": "d",
            }
        },
    }
    cyclic = {
        "$defs": {
            "A": {"properties": {"b": {"$ref": "#/$defs/B"}}},
            "B": {"properties": {"a": {"$ref": "#/$defs/A"}}},
        },
        "properties": {"x": {"$ref": "#/$defs/A"}},
    }
    with pytest.raises(strict.VariantRefused, match=r"cyclic \$ref: A -> B -> A"):
        strict.bisect_variant("inline-refs", cyclic)
    with pytest.raises(strict.VariantRefused, match="unresolved"):
        strict.bisect_variant("inline-refs", {"properties": {"x": {"$ref": "#/$defs/Z"}}})
    for model in SCHEMAS.values():
        inlined = strict.bisect_variant("inline-refs", strict.strict_schema(model))
        assert "$defs" not in inlined and "$ref" not in sent_keys(inlined)


def test_the_schema_shape_counts_resolved_depth_objects_and_properties() -> None:
    schema: dict[str, Any] = {
        "$defs": {
            "D": {
                "type": "object",
                "properties": {"c": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
            }
        },
        "type": "object",
        "properties": {"a": {"type": "array", "items": {"$ref": "#/$defs/D"}}, "b": {}},
    }
    # root > a > items (D) > c > anyOf branch: five nodes deep, two of them objects.
    assert strict.schema_shape(schema) == "depth 5 (2 objects), 3 properties"
    cyclic = {"$defs": {"A": {"properties": {"a": {"$ref": "#/$defs/A"}}}}, "$ref": "#/$defs/A"}
    assert strict.schema_shape(cyclic) == "depth cyclic, 1 properties"


def test_an_unknown_variant_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown bisect variant"):
        strict.bisect_variant("drop-everything", {})


def _source_context_document(tmp_path: Path) -> dict[str, Any]:
    payload = replay_support.cp1_seed_payloads(tmp_path)["source_context"]
    document: dict[str, Any] = json.loads(payload)
    return document


def test_the_stored_contract_still_resolves_a_null_event_scan_to_its_default(
    tmp_path: Path,
) -> None:
    """The relaxation is on the way out only: Pydantic validates the reply as before."""
    model = SCHEMAS["source_context"]
    document = _source_context_document(tmp_path)
    for source in document["sources"]:
        source["event_scan"] = None
        source["event_ids"] = []
        source["event_scan_citations"] = []
    normalised, paths = strict.normalise(model, json.dumps(document))
    assert paths and all(path.endswith(".event_scan") for path in paths)
    review = model.model_validate_json(normalised)
    assert {source.event_scan for source in review.sources} == {"unassessed"}  # the default


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: d["sources"][0]["scopes"][0].update(period_label=""), "at least 1 character"),
        (lambda d: d["sources"][0]["scopes"][0].update(scope_id="x" * 161), "at most 160"),
        (lambda d: d["sources"][0].update(event_scan="maybe"), "Input should be"),
        (lambda d: d.update(schema_version="source-context-review/2"), "Input should be"),
    ],
    ids=["empty-period", "long-identifier", "unknown-enum-value", "wrong-constant"],
)
def test_the_stored_contract_still_rejects_what_the_sent_schema_no_longer_says(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    model = SCHEMAS["source_context"]
    document = _source_context_document(tmp_path)
    change(document)
    normalised, _ = strict.normalise(model, json.dumps(document))
    with pytest.raises(ValidationError, match=message):
        model.model_validate_json(normalised)


# --- null resolution on parse -------------------------------------------------------------


def null_defaults(model: BaseModel) -> dict[str, Any]:
    """The model as JSON with an explicit null for every field left at its default (exactly the
    fields `exclude_defaults` omits). Independent of the code under test: it walks Pydantic
    fields, not the JSON schema."""

    def walk(value: object) -> object:
        if isinstance(value, BaseModel):
            out: dict[str, object] = {}
            for name, info in type(value).model_fields.items():
                field = getattr(value, name)
                at_default = not info.is_required() and field == info.get_default()
                out[name] = None if at_default else walk(field)
            return out
        if isinstance(value, tuple):
            return [walk(item) for item in value]
        return json.loads(json.dumps(value, default=str)) if not isinstance(value, str) else value

    result = walk(model)
    assert isinstance(result, dict)
    return result


def omit_defaults(model: BaseModel) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(model.model_dump_json(exclude_defaults=True))
    return document


def test_explicit_nulls_parse_to_the_same_object_as_omitted_defaults() -> None:
    _, review = readiness_fixture()
    with_nulls = json.dumps(null_defaults(review))
    normalised, paths = strict.normalise(ReadinessReview, with_nulls)
    assert paths  # something was resolved, and every path is named
    assert "schema_version" in paths
    # Fields whose default is None were already nullable: their null is a value, not resolved.
    assert not [p for p in paths if p.endswith((".missing_source", ".limitation"))]
    omitted = ReadinessReview.model_validate_json(json.dumps(omit_defaults(review)))
    assert ReadinessReview.model_validate_json(normalised) == omitted == review


def test_cp1_payload_nulls_resolve_for_every_defaulted_field(tmp_path: Path) -> None:
    payloads = replay_support.cp1_seed_payloads(tmp_path)
    for step in ("source_context", "financials"):
        model = SCHEMAS[step].model_validate_json(payloads[step])
        normalised, paths = strict.normalise(SCHEMAS[step], json.dumps(null_defaults(model)))
        assert paths, step
        omitted = SCHEMAS[step].model_validate_json(json.dumps(omit_defaults(model)))
        assert SCHEMAS[step].model_validate_json(normalised) == omitted == model, step


def test_payload_without_nulls_is_returned_byte_for_byte() -> None:
    _, review = readiness_fixture()
    raw = review.model_dump_json()
    assert strict.normalise(ReadinessReview, raw) == (raw, ())
    spaced = "  " + json.dumps(json.loads(raw), indent=3) + "\n"
    assert strict.normalise(ReadinessReview, spaced) == (spaced, ())


@pytest.mark.parametrize("text", ["not json", "", "[1, 2]", '{"a": NaN}', "{" * 5])
def test_unparseable_payloads_pass_through_for_the_validator_to_reject(text: str) -> None:
    assert strict.normalise(ReadinessReview, text) == (text, ())


def test_nulls_on_required_or_already_nullable_fields_are_left_alone() -> None:
    _, review = readiness_fixture()
    document = json.loads(review.model_dump_json())
    document["pack_sha256"] = None  # required: the validator must still refuse it
    document["sources"][0]["entity"] = None  # required and nullable: null is a real value
    document["analysis"][0]["limitation"] = None  # default None: nothing to resolve
    text = json.dumps(document)
    assert strict.normalise(ReadinessReview, text) == (text, ())


def test_numbers_keep_their_exact_text_when_a_payload_is_rewritten() -> None:
    class Amounts(BaseModel):
        value: Decimal
        notes: tuple[str, ...] = ()

    text = '{"value": 1234567890.123456789012, "notes": null}'
    normalised, paths = strict.normalise(Amounts, text)
    assert paths == ("notes",)
    assert "1234567890.123456789012" in normalised
    assert json.loads(normalised, parse_float=Decimal) == {
        "value": Decimal("1234567890.123456789012"),
        "notes": [],
    }


# --- task 7.0d: Decimal amounts are sent as JSON numbers only (E1 batch e1-cp1-3) -------------


def number_or_string(node: dict[str, Any]) -> bool:
    kinds = [b.get("type") for b in node.get("anyOf", ()) if isinstance(b, dict)]
    return "number" in kinds and "string" in kinds


def test_observation_and_alternative_amounts_are_sent_without_a_string_branch() -> None:
    bounds = {"exclusiveMaximum": 1e18, "exclusiveMinimum": -1e18, "type": "number"}
    assert strict.strict_schema(Observation)["properties"]["amount"] == {
        "anyOf": [bounds, {"type": "null"}],
        "title": "Amount",
    }
    alternative = strict.strict_schema(Alternative)["properties"]["amount"]
    assert alternative == {**bounds, "title": "Amount"}
    sent = strict.strict_schema(SCHEMAS["financials"])
    assert not [n for n in nodes(sent) if number_or_string(n)]
    # The stored contract's own schema still has the string branch (normalise reads it).
    assert [n for n in nodes(SCHEMAS["financials"].model_json_schema()) if number_or_string(n)]
    # The marker is consumed on the way out: no step's sent schema carries it.
    for model in SCHEMAS.values():
        assert strict.DECIMAL_MARKER not in sent_keys(strict.strict_schema(model))


Lookalike = Annotated[float, Field(gt=-1e18, lt=1e18)]


class NumberOrText(BaseModel):
    plain: float | str
    bounded: Lookalike | str
    optional: Lookalike | str | None


def test_a_genuine_number_or_string_union_is_not_rewritten() -> None:
    """The rule fires on the `Number` marker only, never on a shape that merely looks alike (a
    float with the Decimal bounds beside a string is a real union)."""
    copied = strict.strict_copy(NumberOrText)
    sent = strict.strict_schema(NumberOrText)
    for name in ("plain", "bounded", "optional"):
        assert number_or_string(sent["properties"][name]), name
        assert sent["properties"][name] == copied["properties"][name], name
    assert "decimal-number-only" not in strict.relaxations(copied)


def test_relaxations_name_decimal_number_only_where_it_applied() -> None:
    assert "decimal-number-only" in strict.RELAXATIONS
    assert "decimal-number-only" in strict.schema_relaxations(SCHEMAS["financials"])
    for step in sorted(set(SCHEMAS) - {"financials"}):
        assert "decimal-number-only" not in strict.schema_relaxations(SCHEMAS[step]), step
    assert "decimal-number-only" in strict.RELAXATIONS_BASIS
    # Reported on the strict copy only: the sent copy no longer carries the marker.
    assert "decimal-number-only" not in strict.relaxations(strict.strict_schema(Observation))


@pytest.mark.parametrize(
    "node",
    [
        {"anyOf": [{"type": "number"}, {"type": "integer"}]},
        {"anyOf": [{"type": "number"}, {"type": "string", "format": "date"}]},
        {"anyOf": [{"type": "number", "enum": [1]}, {"type": "string"}]},
        {"anyOf": [{"type": "number"}, {"type": "string"}, {"type": "string"}]},
        {"anyOf": [{"type": "string"}, {"type": "null"}]},
        {"type": "number"},
    ],
    ids=["no-string", "string-format", "number-enum", "two-strings", "no-number", "no-any-of"],
)
def test_a_marked_node_of_another_shape_fails_closed(node: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="cannot be relaxed"):
        strict.relax({"properties": {"x": {**node, strict.DECIMAL_MARKER: True}}})


def test_a_defaulted_marked_number_keeps_its_null_branch() -> None:
    """`_nullable` appends null inside a marked node; only the string branch is dropped."""
    marked = {
        "anyOf": [{"type": "number", "minimum": 0}, {"type": "string"}, {"type": "null"}],
        "title": "N",
        strict.DECIMAL_MARKER: True,
    }
    assert strict.relax({"properties": {"n": marked}}) == {
        "properties": {
            "n": {"anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}], "title": "N"}
        }
    }


def test_a_stored_string_amount_still_validates_and_a_printed_one_is_still_refused() -> None:
    """The sent copy only: the stored contract and its parse are unchanged (I2)."""
    citation = {"source_id": "filing", "source_sha256": "0" * 64, "locator": "page:1", "quote": "q"}
    stored = {"amount": "3624", "citations": [citation], "explanation": "A"}
    assert Alternative.model_validate_json(json.dumps(stored)).amount == Decimal("3624")
    number = json.dumps({**stored, "amount": 0}).replace('"amount": 0', '"amount": 3624.10')
    assert Alternative.model_validate_json(number).amount == Decimal("3624.10")
    for printed in ("3,624", "(211)"):
        with pytest.raises(ValidationError, match="Input should be a valid decimal"):
            Alternative.model_validate_json(json.dumps({**stored, "amount": printed}))


# --- task 7.0d fix 1: statement item ids as a closed list or an `other:` id ("prefixed-enum") --

IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"  # deploy_vii.contracts.Identifier, read there
OTHER = r"^other:[A-Za-z0-9_.:-]*$"


def items(*kinds: str) -> list[str]:
    return sorted(
        {item for kind in kinds for item in (*REQUIRED_ITEMS[kind], *OPTIONAL_ITEMS[kind])}
    )


def prefixed(enum: list[str], title: str) -> dict[str, Any]:
    return {
        "anyOf": [{"type": "string", "enum": enum}, {"type": "string", "pattern": OTHER}],
        "title": title,
    }


def test_statement_and_balance_item_ids_are_sent_as_a_list_or_an_other_id() -> None:
    sent = strict.strict_schema(SCHEMAS["financials"])["$defs"]
    assert sent["StatementLine"]["properties"]["item_id"] == prefixed(
        items("IS", "CFS", "BS"), "Item Id"
    )
    assert sent["BalanceMovementBridge"]["properties"]["balance_item_id"] == prefixed(
        items("BS"), "Balance Item Id"
    )
    assert (len(items("IS", "CFS", "BS")), len(items("BS"))) == (78, 32)
    # Deferred (6 ids plus `facility:<facility_id>`, a derived prefix): still a free Identifier.
    assert "anyOf" not in sent["ProFormaObservation"]["properties"]["metric_id"]
    assert strict.PREFIXED_ENUM_MARKER not in json.dumps(
        strict.strict_schema(SCHEMAS["financials"])
    )
    assert strict.PREFIXED_ENUM_MARKER in json.dumps(SCHEMAS["financials"].model_json_schema())


def test_every_listed_item_is_an_identifier_and_none_is_an_other_id() -> None:
    for item in items("IS", "CFS", "BS"):
        assert re.fullmatch(IDENTIFIER, item) and not re.fullmatch(OTHER, item), item
    assert TypeAdapter(Identifier).json_schema()["pattern"] == IDENTIFIER  # the pattern read above


@given(
    st.one_of(
        st.text(alphabet="other:Az9_.-/ é\n", max_size=12),
        st.text(alphabet="Az9_.:-/ é\n", max_size=8).map(lambda tail: "other:" + tail),
    )
)
def test_the_other_pattern_accepts_exactly_what_identifier_and_the_prefix_rule_accept(
    text: str,
) -> None:
    """`statement_validation` and `balance_movement` accept a non-listed id when it is an
    Identifier and `startswith("other:")`; the sent pattern is that intersection (lengths aside:
    `maxLength` is dropped from every sent Identifier)."""
    expected = bool(re.fullmatch(IDENTIFIER, text)) and text.startswith("other:")
    assert bool(re.fullmatch(OTHER, text)) is expected


def test_prefixed_enum_is_named_where_it_applied_and_marked_nodes_of_another_shape_fail() -> None:
    assert strict.RELAXATIONS[-2] == "prefixed-enum"  # task 7.0i appended drop-prefilled
    assert "prefixed-enum" in strict.schema_relaxations(SCHEMAS["financials"])
    for step in sorted(set(SCHEMAS) - {"financials"}):
        assert "prefixed-enum" not in strict.schema_relaxations(SCHEMAS[step]), step
    assert "prefixed-enum" in strict.RELAXATIONS_BASIS
    marker = {strict.PREFIXED_ENUM_MARKER: {"enum": ["a"], "pattern": "^other:"}}
    for node in (
        {"type": ["string", "null"], **marker},  # nullable: not expressible as this anyOf
        {"type": "string", "enum": ["b"], **marker},
        {"anyOf": [{"type": "string"}], **marker},
        {"type": "string", strict.PREFIXED_ENUM_MARKER: {"enum": [], "pattern": "^x"}},
        {"type": "string", strict.PREFIXED_ENUM_MARKER: {"enum": ["a"]}},
        {"type": "string", strict.PREFIXED_ENUM_MARKER: ["a"]},
    ):
        with pytest.raises(ValueError, match="cannot be relaxed"):
            strict.relax({"properties": {"x": node}})


# --- task 7.0i: a field Python fills is left out of the sent schema ("drop-prefilled") --------


def test_the_financials_sent_schema_leaves_out_the_context_step_binding() -> None:
    """E1 batch 5: the model copied the wrong 64-hex value three times; it is no longer asked."""
    model = SCHEMAS["financials"]
    sent = strict.strict_schema(model)
    assert "context_step_sha256" not in sent["properties"]
    assert "context_step_sha256" not in sent["required"]
    assert sent["required"] == list(sent["properties"])  # still strict-valid
    assert sent["additionalProperties"] is False
    assert strict.PREFILLED_MARKER not in json.dumps(sent)  # the marker is consumed
    # The stored contract is unchanged: the field is still a required, marked Hash.
    stored = model.model_json_schema()
    assert "context_step_sha256" in stored["required"]
    assert stored["properties"]["context_step_sha256"][strict.PREFILLED_MARKER] is True
    assert stored["properties"]["context_step_sha256"]["pattern"] == "^[0-9a-f]{64}$"


def test_drop_prefilled_is_named_for_financials_only_and_other_steps_carry_no_marker() -> None:
    assert strict.RELAXATIONS[-2:] == ("prefixed-enum", "drop-prefilled")
    assert "drop-prefilled" in strict.schema_relaxations(SCHEMAS["financials"])
    assert "drop-prefilled" in strict.RELAXATIONS_BASIS
    assert strict.PREFILLED_MARKER in strict.RELAXATIONS_BASIS
    for step in sorted(set(SCHEMAS) - {"financials"}):
        assert "drop-prefilled" not in strict.schema_relaxations(SCHEMAS[step]), step
        # The rule rewrites marked nodes only, so with no marker these sent schemas are unchanged.
        assert strict.PREFILLED_MARKER not in json.dumps(SCHEMAS[step].model_json_schema()), step
    # Reported on the strict copy only: the sent copy no longer carries the marker.
    sent = strict.strict_schema(SCHEMAS["financials"])
    assert "drop-prefilled" not in strict.relaxations(sent)


def test_a_marked_property_is_dropped_with_its_required_entry_and_nothing_else() -> None:
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "h": {"type": "string", "pattern": "^x$", strict.PREFILLED_MARKER: True},
            "b": {"type": "integer"},
        },
        "required": ["a", "h", "b"],
        "additionalProperties": False,
    }
    expected = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
        "additionalProperties": False,
    }
    assert strict.relax(schema) == expected
    assert strict.relax(expected) == expected  # idempotent
    assert strict.relaxations(schema) == ["drop-prefilled"]


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", strict.PREFILLED_MARKER: True},
        {"type": "array", "items": {"type": "string", strict.PREFILLED_MARKER: True}},
        {"anyOf": [{"type": "string", strict.PREFILLED_MARKER: True}, {"type": "null"}]},
        {"$defs": {"H": {"type": "string", strict.PREFILLED_MARKER: True}}},
        {"properties": {"h": {"type": "string", strict.PREFILLED_MARKER: False}}},
    ],
    ids=["root", "array-item", "union-branch", "definition", "marker-not-true"],
)
def test_a_marker_that_is_not_on_an_object_property_fails_closed(schema: dict[str, Any]) -> None:
    """Only a property can be left out (its object drops it); a marker anywhere else would reach
    the provider, so nothing is sent for it."""
    with pytest.raises(ValueError, match="cannot be relaxed"):
        strict.relax(schema)
