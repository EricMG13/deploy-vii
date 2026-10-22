"""Catalog pinning, eligibility, effort mapping and the seeded draw (no network)."""

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any

import pytest

from deploy_vii.live.catalog import Catalog, CatalogError, resolve_effort
from deploy_vii.live.client import Request, Response
from deploy_vii.live.draw import NoEligibleModel, draw
from tests.product.live_support import CANDIDATES, FIXTURES, fixture_pool

DEEPSEEK_RULE_WORDS = ("newest", "created", ":batch", "exp", "reasoning")
PINNED_INDEXES = [1, 0, 0, 0, 0, 2, 2, 1]  # random.Random(seed).randrange(3), seeds 0..7


def _catalog_with(mutator: Callable[[list[dict[str, Any]]], None]) -> Catalog:
    document = json.loads((FIXTURES / "models-subset.json").read_text(encoding="utf-8"))
    mutator(document["data"])
    return Catalog.from_bytes(
        json.dumps(document).encode(), source="test", looked_up_at="2026-10-22T00:00:00Z"
    )


def _entry(data: list[dict[str, Any]], slug: str) -> dict[str, Any]:
    return next(item for item in data if item["id"] == slug)


def test_deepseek_latest_resolution_is_pinned_and_recorded() -> None:
    pool = fixture_pool("batch-1")
    deepseek = pool.candidates[2]
    # Newer decoys (experimental, :batch, non-reasoning, image-output) are all skipped.
    assert deepseek.slug == "deepseek/deepseek-v4.1-flash-1017"
    assert deepseek.canonical_slug == "deepseek/deepseek-v4.1-flash-20261017"
    assert deepseek.eligible and deepseek.exclusion_reason is None
    assert deepseek.resolution == "refresh-latest-suitable-deepseek-before-batch"
    assert deepseek.requested_model_id == "deepseek/deepseek-v4.1-flash-1017"
    record = pool.to_record()
    assert record["batch_id"] == "batch-1"
    assert record["looked_up_at"] == "2026-10-21T09:00:00Z"
    assert all(word in record["deepseek_rule"] for word in DEEPSEEK_RULE_WORDS)
    assert len(record["catalog_sha256"]) == 64
    assert record["candidates"][2]["slug"] == deepseek.slug
    assert record["candidates"][2]["resolved_differs_from_settings"] is False
    # Pinned: the pool is immutable and does not follow a later, newer catalog.
    with pytest.raises(FrozenInstanceError):
        pool.candidates[2].__setattr__("slug", "other")

    def newer(data: list[dict[str, Any]]) -> None:
        fresh = dict(_entry(data, "deepseek/deepseek-v4.1-flash-1017"))
        fresh.update(id="deepseek/deepseek-v5", canonical_slug="deepseek/deepseek-v5")
        fresh["created"] = 1792999999
        data.append(fresh)

    later = _catalog_with(newer).pin("batch-2", CANDIDATES)
    assert later.candidates[2].slug == "deepseek/deepseek-v5"
    assert later.to_record()["candidates"][2]["resolved_differs_from_settings"] is True
    assert pool.candidates[2].slug == "deepseek/deepseek-v4.1-flash-1017"
    assert later.catalog_sha256 != pool.catalog_sha256


def test_no_suitable_deepseek_is_recorded_ineligible_before_draw() -> None:
    def strip(data: list[dict[str, Any]]) -> None:
        data[:] = [item for item in data if not item["id"].startswith("deepseek/")]

    pool = _catalog_with(strip).pin("b", CANDIDATES)
    missing = pool.candidates[2]
    assert not missing.eligible and "no suitable deepseek" in str(missing.exclusion_reason)
    assert [item.key for item in pool.eligible] == ["luna", "glm"]
    assert {draw(pool, seed).slug for seed in range(50)} == {
        "openai/gpt-6-luna",
        "z-ai/glm-5.3-flash",
    }


@pytest.mark.parametrize(
    "mutation, reason",
    [
        ("drop-structured", "missing parameters: structured_outputs"),
        ("drop-effort", "missing parameters: reasoning_effort"),
        ("image-output", "does not produce text"),
        ("bad-price", "price unavailable"),
        ("negative-price", "price unavailable"),
        ("bad-override", "price unavailable"),
        ("absent", "absent from the catalog"),
    ],
)
def test_ineligible_members_carry_a_reason(mutation: str, reason: str) -> None:
    def change(data: list[dict[str, Any]]) -> None:
        item = _entry(data, "z-ai/glm-5.3-flash")
        if mutation == "drop-structured":
            item["supported_parameters"].remove("structured_outputs")
        elif mutation == "drop-effort":
            item["supported_parameters"].remove("reasoning_effort")
        elif mutation == "image-output":
            item["architecture"]["output_modalities"] = ["image"]
        elif mutation == "bad-price":
            item["pricing"]["completion"] = "free"
        elif mutation == "negative-price":
            item["pricing"]["prompt"] = "-1"
        elif mutation == "bad-override":
            item["pricing"]["overrides"] = [{"prompt": "NaN"}]
        else:
            data.remove(item)

    pool = _catalog_with(change).pin("b", CANDIDATES)
    glm = pool.candidates[1]
    assert not glm.eligible and reason in str(glm.exclusion_reason)
    chosen = draw(pool, 3)
    assert glm.slug not in chosen.eligible
    assert (glm.slug, glm.exclusion_reason) in chosen.exclusions


def test_pinned_prices_are_the_conservative_maximum_with_base_recorded() -> None:
    pool = fixture_pool()
    luna, glm, deepseek = pool.candidates
    # Luna: a long-prompt override raises both prices; DeepSeek: a weekday peak override.
    assert (luna.prompt_price, luna.completion_price) == (Decimal("2E-7"), Decimal("7.5E-7"))
    assert (luna.base_prompt_price, luna.base_completion_price) == (
        Decimal("1E-7"),
        Decimal("5E-7"),
    )
    assert (deepseek.prompt_price, deepseek.completion_price) == (
        Decimal("3E-7"),
        Decimal("1.2E-6"),
    )
    assert (glm.prompt_price, glm.completion_price) == (Decimal("4.1191E-8"), Decimal("1.2E-7"))
    assert glm.request_price == Decimal(0)
    assert "max" in glm.price_basis


def test_same_seed_reproduces_draw() -> None:
    pool = fixture_pool()
    first, second = draw(pool, 20261021), draw(pool, 20261021)
    assert first == second
    record = first.to_record()
    assert record["algorithm"] == "python-random-MT19937"
    assert record["seed"] == 20261021
    assert record["pool"] == [item.slug for item in pool.candidates]
    assert record["eligible"] == record["pool"] and record["exclusions"] == []
    assert record["slug"] == record["eligible"][record["index"]]
    # A fresh pool object (same catalog) gives the same answer: nothing hidden in state.
    assert draw(fixture_pool(), 20261021) == first
    # Pinned values guard against an unnoticed change of RNG semantics across Python versions.
    assert [draw(pool, seed).index for seed in range(8)] == PINNED_INDEXES
    counts = Counter(draw(pool, seed).slug for seed in range(3000))
    assert set(counts) == {item.slug for item in pool.candidates}
    assert all(850 < count < 1150 for count in counts.values())
    assert draw(pool, 1) != draw(pool, 2) or draw(pool, 1) != draw(pool, 3)
    with pytest.raises(KeyError, match="not in the pinned pool"):
        pool.candidate("unknown/model")


def test_draw_with_no_eligible_model_blocks() -> None:
    def kill(data: list[dict[str, Any]]) -> None:
        data[:] = []

    pool = _catalog_with(kill).pin("b", CANDIDATES)
    with pytest.raises(NoEligibleModel, match="no eligible"):
        draw(pool, 1)


def test_catalog_fetch_uses_public_endpoint_without_credentials() -> None:
    raw = (FIXTURES / "models-subset.json").read_bytes()
    seen: list[Request] = []

    def transport(request: Request) -> Response:
        seen.append(request)
        return Response(status=200, body=raw)

    catalog = Catalog.fetch(transport, looked_up_at="2026-10-21T10:00:00Z")
    assert seen[0].url == "https://openrouter.ai/api/v1/models" and seen[0].method == "GET"
    assert "Authorization" not in {name.title() for name in seen[0].headers}
    assert catalog.pin("b", CANDIDATES).looked_up_at == "2026-10-21T10:00:00Z"
    assert catalog.source == "https://openrouter.ai/api/v1/models"
    with pytest.raises(CatalogError, match="HTTP 503"):
        Catalog.fetch(lambda _: Response(status=503, body=b"down"))
    with pytest.raises(CatalogError, match="not a catalog"):
        Catalog.from_bytes(b"[]", source="x")
    with pytest.raises(CatalogError, match="not JSON"):
        Catalog.from_bytes(b"{", source="x")
    # Without an explicit lookup time the moment of lookup is recorded in UTC.
    assert Catalog.from_bytes(raw, source="x").looked_up_at.endswith("Z")


@pytest.mark.parametrize(
    "requested, supported, sent, mapped",
    [
        ("high", None, "high", False),
        ("xhigh", ("max", "xhigh", "high"), "xhigh", False),
        ("xhigh", ("max", "high", "low"), "high", True),
        ("xhigh", None, "high", True),
        ("high", ("max", "low"), "low", True),
        ("low", ("max", "high"), "high", True),
        ("high", (), "high", False),
    ],
)
def test_effort_resolution_maps_and_explains(
    requested: str, supported: tuple[str, ...] | None, sent: str, mapped: bool
) -> None:
    decision = resolve_effort(requested, supported)
    assert (decision.requested, decision.sent, decision.mapped) == (requested, sent, mapped)
    record = decision.to_record()
    assert record["accepted_by_provider"] is None and record["accepted_by_provider_reason"]
    assert bool(record["basis"])
    if mapped and requested == "xhigh":
        assert record["documented_mapping"] == "xhigh->high"


def test_unknown_effort_is_refused() -> None:
    with pytest.raises(ValueError, match="effort"):
        resolve_effort("ludicrous", None)
