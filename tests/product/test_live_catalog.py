"""The user-selected model pool (`live --models`): parsing, eligibility, effort, context fit."""

import pytest

from deploy_vii.live.catalog import (
    NO_EFFORT_BASIS,
    USER_SELECTED,
    CatalogError,
    ModelSelection,
    parse_selection,
)
from tests.product.live_support import catalog_of, catalog_row, fixture_pool

NO_EFFORT = ("max_tokens", "reasoning", "response_format", "structured_outputs")


def test_selection_keeps_the_given_order_and_each_models_own_effort() -> None:
    assert parse_selection("b/one @ max, a/two ,c/three@xhigh") == (
        ModelSelection("b/one", "max"),
        ModelSelection("a/two", None),
        ModelSelection("c/three", "xhigh"),
    )


@pytest.mark.parametrize(
    "text", ["", "a/one,", "@high", "a/one@", "a/one@turbo", "a/one@high@low", "a/one,a/one@low"]
)
def test_selection_refuses_malformed_unknown_effort_and_repeated_ids(text: str) -> None:
    with pytest.raises(ValueError, match="--models"):
        parse_selection(text)


def test_an_id_absent_from_the_catalog_fails_closed_naming_it() -> None:
    catalog = catalog_of(catalog_row("a/one"))
    with pytest.raises(CatalogError, match="a/missing"):
        catalog.pin_selected("b", parse_selection("a/one,a/missing"))


def test_the_pool_is_pinned_in_the_given_order_and_labelled() -> None:
    catalog = catalog_of(catalog_row("a/one"), catalog_row("a/two"))
    pool = catalog.pin_selected("b", parse_selection("a/two@high,a/one"))
    assert [c.slug for c in pool.candidates] == ["a/two", "a/one"]
    assert pool.pool_label == USER_SELECTED and pool.to_record()["pool_label"] == USER_SELECTED
    assert fixture_pool().pool_label == "catalog-rule"
    assert [c.requested_effort for c in pool.candidates] == ["high", None]


@pytest.mark.parametrize("missing", ["response_format", "structured_outputs", "max_tokens"])
def test_a_model_without_a_parameter_the_request_carries_is_recorded_ineligible(
    missing: str,
) -> None:
    parameters = tuple(name for name in NO_EFFORT if name != missing)
    pool = catalog_of(catalog_row("a/one", parameters=parameters)).pin_selected(
        "b", parse_selection("a/one")
    )
    (candidate,) = pool.candidates
    assert not candidate.eligible and missing in (candidate.exclusion_reason or "")
    assert pool.eligible == ()


def test_reasoning_effort_is_not_required_and_a_missing_context_length_is() -> None:
    row = catalog_row("a/one", parameters=NO_EFFORT, efforts=None)
    (candidate,) = catalog_of(row).pin_selected("b", parse_selection("a/one")).candidates
    assert candidate.eligible
    bare = {key: value for key, value in row.items() if key != "context_length"}
    bare["top_provider"] = {}
    (item,) = catalog_of(bare).pin_selected("b", parse_selection("a/one")).candidates
    assert not item.eligible and item.exclusion_reason == "catalog lists no context_length"


def test_the_smaller_listed_context_length_governs() -> None:
    row = catalog_row("a/one", context=1_050_000)
    row["top_provider"] = {"context_length": 1_048_576, "max_completion_tokens": 131_072}
    (candidate,) = catalog_of(row).pin_selected("b", parse_selection("a/one")).candidates
    assert (candidate.context_length, candidate.max_completion_tokens) == (1_048_576, 131_072)


def test_each_models_effort_is_sent_where_listed_and_mapped_where_not() -> None:
    catalog = catalog_of(
        catalog_row("d/deep", efforts=("max", "high", "low")),
        catalog_row("x/grok", efforts=("xhigh", "high", "medium", "low")),
        catalog_row("o/gpt", efforts=("max", "xhigh", "high", "medium", "low")),
    )
    pool = catalog.pin_selected("b", parse_selection("d/deep@max,x/grok@max,o/gpt@high"))
    sent = [c.effort_for("high") for c in pool.candidates]
    assert [(d.requested, d.sent, d.mapped) for d in sent] == [
        ("max", "max", False),
        ("max", "xhigh", True),  # nearest lower level the catalog lists
        ("high", "high", False),
    ]
    assert all(not d.reasoning_enabled for d in sent)


def test_without_an_own_effort_the_batch_default_is_used() -> None:
    (candidate,) = (
        catalog_of(catalog_row("a/one")).pin_selected("b", parse_selection("a/one")).candidates
    )
    assert candidate.effort_for("high").sent == "high"
    assert candidate.effort_for("low").sent == "low"


def test_a_model_listing_no_reasoning_effort_gets_reasoning_switched_on_without_a_value() -> None:
    row = catalog_row("x/mimo", parameters=NO_EFFORT, efforts=None)
    (candidate,) = catalog_of(row).pin_selected("b", parse_selection("x/mimo@xhigh")).candidates
    decision = candidate.effort_for("high")
    assert decision.sent is None and decision.reasoning_enabled
    assert decision.requested == "xhigh" and decision.basis == NO_EFFORT_BASIS
    record = decision.to_record()
    assert record["sent"] is None and record["reasoning_enabled"] is True


def test_context_fit_has_both_branches() -> None:
    row = catalog_row("a/one", context=500_000, completion_limit=450_000)
    (candidate,) = catalog_of(row).pin_selected("b", parse_selection("a/one")).candidates
    assert candidate.misfit(289_224, 16_000) is None  # the current bound fits
    assert candidate.misfit(484_000, 16_000) is None  # exactly the context
    assert candidate.misfit(484_001, 16_000) == "context 500000 < bound 500001"
    assert candidate.misfit(1_000, 450_001) == "max completion 450000 < max_tokens 450001"
