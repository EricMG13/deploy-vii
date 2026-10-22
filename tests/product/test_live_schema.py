"""Strict response schemas: every property required, defaults nullable, nulls resolved back."""

import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

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
    assert root["schema_version"] == {
        "anyOf": [{"const": "readiness-review/1", "type": "string"}, {"type": "null"}],
        "title": "Schema Version",
    }
    assert root["pack_sha256"]["type"] == "string"  # required: not made nullable
    consumer = transformed["$defs"]["ConsumerReadiness"]["properties"]
    assert consumer["limitations"]["type"] == ["array", "null"]
    assert consumer["missing_source"]["anyOf"].count({"type": "null"}) == 1
    claim = transformed["$defs"]["Claim"]["properties"]
    assert {"type": "null"} in claim["limitation"]["anyOf"]
    # Enums carry null too.
    context = strict.strict_schema(SCHEMAS["source_context"])
    scan = context["$defs"]["SourceContext"]["properties"]["event_scan"]
    assert scan["type"] == ["string", "null"] and None in scan["enum"]


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
        assert "anyOf" not in tag and tag.get("type") == "string" and "const" in tag


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
    assert {"pattern", "minLength"} <= set(found) and found == sorted(found)
    context = strict.unverified_keywords(strict.strict_schema(SCHEMAS["source_context"]))
    assert "format" in context
    transformed = json.dumps(strict.strict_schema(ReadinessReview))
    assert '"pattern"' in transformed and '"minLength"' in transformed


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
