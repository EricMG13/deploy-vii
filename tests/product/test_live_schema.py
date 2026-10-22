"""Strict response schemas: every property required, defaults nullable, nulls resolved back."""

import json
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from deploy_vii.live import schema as strict
from deploy_vii.live.prompts import response_format, schema_text
from deploy_vii.live.runner import STEPS
from deploy_vii.readiness import ReadinessReview
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
    assert consumer["limitations"]["type"] == ["array", "null"]
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
    # The 0008 submission has no defaults, so it is already strict as Pydantic writes it; the
    # stored contracts the CP-1 steps still send are not.
    assert (schema_text(model) == untransformed) is (step_id == "source_readiness")


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
        "all",
    )


def test_the_one_of_variant_sends_the_narrative_unions_as_any_of_without_discriminator() -> None:
    sent = strict.strict_schema(SCHEMAS["narrative"])
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
        if name not in {"open-object", "all"}:
            composed = strict.bisect_variant(name, composed)
    every = strict.bisect_variant("all", sent)
    assert every == composed
    assert not {"oneOf", "discriminator", "format", "pattern", "minItems", "maxItems"} & sent_keys(
        every
    )


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
