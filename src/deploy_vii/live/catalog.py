"""Pin the candidate pool for one batch from the public OpenRouter models catalog.

Prices are decimal USD per token. The pinned price is the maximum of the base price and
every published override (time-of-day or long-prompt tiers), so a reservation made from
it can only over-estimate. Eligibility reasons are recorded before any draw.
"""

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from deploy_vii.live.client import Request, Response
from deploy_vii.live.ledger import utc_stamp
from deploy_vii.live.settings import CandidateSetting

MODELS_URL = "https://openrouter.ai/api/v1/models"
DEEPSEEK_LATEST = "refresh-latest-suitable-deepseek-before-batch"
DEEPSEEK_RULE = (
    "newest `created` among deepseek/* catalog entries that are text-output, reasoning-capable "
    "(`reasoning` and `reasoning_effort` supported), carry no `:` variant suffix (so no "
    ":batch) and are not experimental (no `exp` name segment); ties break on the larger id"
)
REQUIRED_PARAMETERS = ("max_tokens", "reasoning_effort", "response_format", "structured_outputs")
EFFORT_LADDER = ("minimal", "low", "medium", "high", "xhigh", "max")
# A user-selected model (`--models`) need not list `reasoning_effort`: it is then asked to reason
# with the generic switch. Every parameter the request carries must still be listed.
SELECTED_PARAMETERS = ("max_tokens", "reasoning", "response_format", "structured_outputs")
CATALOG_RULE = "catalog-rule"
USER_SELECTED = "user-selected"
NO_EFFORT_BASIS = "catalog lists no reasoning_effort; provider default reasoning depth"
_EXPERIMENTAL = re.compile(r"(^|[-/])exp($|[-:])")


class CatalogError(Exception):
    """The catalog could not be fetched or parsed."""


def _price(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _conservative_price(pricing: Mapping[str, Any], field: str) -> tuple[Decimal, Decimal] | None:
    """(pinned maximum, base) for one price field, or None when any value is unusable."""
    base = _price(pricing.get(field, "0"))
    if base is None:
        return None
    pinned = base
    for override in pricing.get("overrides") or ():
        if field in override:
            value = _price(override[field])
            if value is None:
                return None
            pinned = max(pinned, value)
    return pinned, base


@dataclass(frozen=True)
class EffortDecision:
    requested: str
    sent: str | None  # None: no effort value is sent, reasoning is only switched on
    mapped: bool
    basis: str
    supported_efforts: tuple[str, ...] | None
    reasoning_enabled: bool = False

    def to_record(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "sent": self.sent,
            "reasoning_enabled": self.reasoning_enabled,
            "mapped": self.mapped,
            "basis": self.basis,
            "documented_mapping": "xhigh->high"
            if self.requested == "xhigh" and self.mapped
            else None,
            "catalog_supported_efforts": list(self.supported_efforts)
            if self.supported_efforts is not None
            else None,
            "accepted_by_provider": None,
            "accepted_by_provider_reason": "the provider response does not expose an effective "
            "effort; catalog support does not prove acceptance",
        }


def resolve_effort(requested: str, supported: Sequence[str] | None) -> EffortDecision:
    """Send the requested effort only where the catalog lists it; else the nearest lower level.

    OpenRouter documents mapping an unsupported non-`none` effort to the nearest supported
    level (for example xhigh to high); the runner maps first so the record is explicit.
    """
    if requested not in EFFORT_LADDER:
        raise ValueError(f"unknown reasoning effort {requested!r}")
    if not supported:
        sent = "high" if requested == "xhigh" else requested
        basis = "catalog lists no efforts for this model; xhigh is requested only where supported"
        return EffortDecision(requested, sent, sent != requested, basis, None)
    listed = tuple(sorted(set(supported) & set(EFFORT_LADDER), key=EFFORT_LADDER.index))
    if requested in listed:
        return EffortDecision(requested, requested, False, "listed in catalog efforts", listed)
    position = EFFORT_LADDER.index(requested)
    lower = [level for level in listed if EFFORT_LADDER.index(level) < position]
    higher = [level for level in listed if EFFORT_LADDER.index(level) > position]
    sent = lower[-1] if lower else higher[0]
    return EffortDecision(
        requested, sent, True, "requested effort not listed; nearest supported level used", listed
    )


def reasoning_only_decision(requested: str) -> EffortDecision:
    """The decision for a model whose catalog lists no `reasoning_effort`: no effort is sent."""
    if requested not in EFFORT_LADDER:
        raise ValueError(f"unknown reasoning effort {requested!r}")
    return EffortDecision(requested, None, False, NO_EFFORT_BASIS, None, reasoning_enabled=True)


@dataclass(frozen=True)
class ModelSelection:
    """One `--models` entry: a catalog id and the effort asked of it (None: the batch default)."""

    model_id: str
    effort: str | None


def parse_selection(text: str) -> tuple[ModelSelection, ...]:
    """`ID[@EFFORT],ID[@EFFORT],...` in the given order; unknown efforts and repeats are refused."""
    chosen: list[ModelSelection] = []
    for part in text.split(","):
        model_id, at, effort = (piece.strip() for piece in part.partition("@"))
        if not model_id or "@" in effort or (at and effort not in EFFORT_LADDER):
            raise ValueError(
                f"bad --models entry {part.strip()!r}: expected ID or ID@EFFORT with EFFORT in "
                + ", ".join(EFFORT_LADDER)
            )
        if any(item.model_id == model_id for item in chosen):
            raise ValueError(f"--models names {model_id} twice")
        chosen.append(ModelSelection(model_id, effort if at else None))
    return tuple(chosen)


@dataclass(frozen=True)
class PinnedCandidate:
    key: str
    requested_model_id: str
    resolution: str
    slug: str
    canonical_slug: str
    created: int | None
    prompt_price: Decimal
    completion_price: Decimal
    request_price: Decimal
    base_prompt_price: Decimal
    base_completion_price: Decimal
    price_basis: str
    supported_parameters: tuple[str, ...]
    supported_efforts: tuple[str, ...] | None
    eligible: bool
    exclusion_reason: str | None
    context_length: int | None = None
    max_completion_tokens: int | None = None
    requested_effort: str | None = None

    def effort_for(self, default: str) -> EffortDecision:
        """The effort sent: this model's own request, else `default`; none where unlisted."""
        requested = self.requested_effort or default
        if "reasoning_effort" not in self.supported_parameters:
            return reasoning_only_decision(requested)
        return resolve_effort(requested, self.supported_efforts)

    def misfit(self, prompt_bound: int, max_tokens: int) -> str | None:
        """Why the bounded prompt plus `max_tokens` cannot be served, or None when it fits."""
        needed = prompt_bound + max_tokens
        if self.context_length is not None and needed > self.context_length:
            return f"context {self.context_length} < bound {needed}"
        if self.max_completion_tokens is not None and max_tokens > self.max_completion_tokens:
            return f"max completion {self.max_completion_tokens} < max_tokens {max_tokens}"
        return None

    def to_record(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "requested_model_id": self.requested_model_id,
            "resolution": self.resolution,
            "slug": self.slug,
            "resolved_differs_from_settings": self.slug != self.requested_model_id,
            "canonical_slug": self.canonical_slug,
            "created": self.created,
            "prompt_price": format(self.prompt_price, "f"),
            "completion_price": format(self.completion_price, "f"),
            "request_price": format(self.request_price, "f"),
            "base_prompt_price": format(self.base_prompt_price, "f"),
            "base_completion_price": format(self.base_completion_price, "f"),
            "price_basis": self.price_basis,
            "supported_parameters": list(self.supported_parameters),
            "supported_efforts": list(self.supported_efforts)
            if self.supported_efforts is not None
            else None,
            "eligible": self.eligible,
            "exclusion_reason": self.exclusion_reason,
            "context_length": self.context_length,
            "max_completion_tokens": self.max_completion_tokens,
            "requested_effort": self.requested_effort,
        }


@dataclass(frozen=True)
class PinnedPool:
    batch_id: str
    catalog_source: str
    catalog_sha256: str
    looked_up_at: str
    deepseek_rule: str
    candidates: tuple[PinnedCandidate, ...]
    pool_label: str = CATALOG_RULE

    @property
    def eligible(self) -> tuple[PinnedCandidate, ...]:
        return tuple(item for item in self.candidates if item.eligible)

    def candidate(self, slug: str) -> PinnedCandidate:
        for item in self.candidates:
            if item.slug == slug:
                return item
        raise KeyError(f"{slug} is not in the pinned pool")

    def to_record(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "catalog_source": self.catalog_source,
            "catalog_sha256": self.catalog_sha256,
            "looked_up_at": self.looked_up_at,
            "deepseek_rule": self.deepseek_rule,
            "pool_label": self.pool_label,
            "candidates": [item.to_record() for item in self.candidates],
        }


class Catalog:
    def __init__(
        self, entries: Mapping[str, Mapping[str, Any]], sha256: str, source: str, looked_up_at: str
    ) -> None:
        self._entries = entries
        self.sha256 = sha256
        self.source = source
        self.looked_up_at = looked_up_at

    @classmethod
    def from_bytes(cls, raw: bytes, *, source: str, looked_up_at: str | None = None) -> "Catalog":
        try:
            document = json.loads(raw)
        except ValueError:
            raise CatalogError("catalog body is not JSON") from None
        rows = document.get("data") if isinstance(document, dict) else None
        if not isinstance(rows, list):
            raise CatalogError("catalog body is not a catalog: no `data` list")
        entries = {row["id"]: row for row in rows if isinstance(row, dict) and "id" in row}
        return cls(entries, hashlib.sha256(raw).hexdigest(), source, looked_up_at or utc_stamp())

    @classmethod
    def from_file(cls, path: Path, *, looked_up_at: str | None = None) -> "Catalog":
        return cls.from_bytes(path.read_bytes(), source=str(path), looked_up_at=looked_up_at)

    @classmethod
    def fetch(
        cls, transport: Callable[[Request], Response], *, looked_up_at: str | None = None
    ) -> "Catalog":
        request = Request(url=MODELS_URL, method="GET", headers={"Accept": "application/json"})
        response = transport(request)
        if response.status != 200:
            raise CatalogError(f"catalog fetch failed with HTTP {response.status}")
        return cls.from_bytes(response.body, source=MODELS_URL, looked_up_at=looked_up_at)

    def _suitable_deepseek(self) -> str | None:
        best: tuple[int, str] | None = None
        for slug, entry in self._entries.items():
            if not slug.startswith("deepseek/") or ":" in slug or _EXPERIMENTAL.search(slug):
                continue
            parameters = set(entry.get("supported_parameters") or ())
            if not {"reasoning", "reasoning_effort"} <= parameters or not _produces_text(entry):
                continue
            created = entry.get("created")
            key = (created if isinstance(created, int) else 0, slug)
            best = key if best is None or key > best else best
        return best[1] if best else None

    def _pin_one(
        self,
        setting: CandidateSetting,
        required: Sequence[str] = REQUIRED_PARAMETERS,
        requested_effort: str | None = None,
        require_context: bool = False,
    ) -> PinnedCandidate:
        slug = setting.model_id
        if setting.resolution == DEEPSEEK_LATEST:
            resolved = self._suitable_deepseek()
            if resolved is None:
                return _excluded(setting, "no suitable deepseek model in the catalog")
            slug = resolved
        entry = self._entries.get(slug)
        if entry is None:
            return _excluded(setting, f"{slug} is absent from the catalog")
        pricing = entry.get("pricing") or {}
        prompt = _conservative_price(pricing, "prompt")
        completion = _conservative_price(pricing, "completion")
        request = _conservative_price(pricing, "request")
        parameters = tuple(entry.get("supported_parameters") or ())
        efforts = (entry.get("reasoning") or {}).get("supported_efforts")
        problem: str | None = None
        if prompt is None or completion is None or request is None:
            problem = "price unavailable or not a finite non-negative decimal"
        elif not _produces_text(entry):
            problem = "model does not produce text output"
        elif missing := [name for name in required if name not in parameters]:
            problem = "missing parameters: " + ", ".join(missing)
        context, completion_limit = _limits(entry)
        if problem is None and require_context and context is None:
            problem = "catalog lists no context_length"
        zero = (Decimal(0), Decimal(0))
        prompt, completion, request = prompt or zero, completion or zero, request or zero
        created = entry.get("created")
        return PinnedCandidate(
            key=setting.key,
            requested_model_id=setting.model_id,
            resolution=setting.resolution,
            slug=slug,
            canonical_slug=str(entry.get("canonical_slug") or slug),
            created=created if isinstance(created, int) else None,
            prompt_price=prompt[0],
            completion_price=completion[0],
            request_price=request[0],
            base_prompt_price=prompt[1],
            base_completion_price=completion[1],
            price_basis="max of base price and every published override",
            supported_parameters=parameters,
            supported_efforts=tuple(efforts) if isinstance(efforts, list) else None,
            eligible=problem is None,
            exclusion_reason=problem,
            context_length=context,
            max_completion_tokens=completion_limit,
            requested_effort=requested_effort,
        )

    def pin_selected(self, batch_id: str, selections: Sequence[ModelSelection]) -> PinnedPool:
        """Freeze the user's `--models` pool, in the given order.

        The catalog rule is bypassed, eligibility is not: an id absent from the catalog fails
        closed (naming it) and a model missing a parameter the request carries is recorded
        ineligible before any draw."""
        for item in selections:
            if item.model_id not in self._entries:
                raise CatalogError(f"--models: {item.model_id} is absent from the catalog")
        return PinnedPool(
            batch_id=batch_id,
            catalog_source=self.source,
            catalog_sha256=self.sha256,
            looked_up_at=self.looked_up_at,
            deepseek_rule="not applicable: the pool is user-selected",
            candidates=tuple(
                self._pin_one(
                    CandidateSetting(item.model_id, item.model_id, USER_SELECTED),
                    SELECTED_PARAMETERS,
                    item.effort,
                    require_context=True,
                )
                for item in selections
            ),
            pool_label=USER_SELECTED,
        )

    def pin(self, batch_id: str, candidates: Sequence[CandidateSetting]) -> PinnedPool:
        """Resolve and freeze the ordered pool for one comparison batch."""
        return PinnedPool(
            batch_id=batch_id,
            catalog_source=self.source,
            catalog_sha256=self.sha256,
            looked_up_at=self.looked_up_at,
            deepseek_rule=DEEPSEEK_RULE,
            candidates=tuple(self._pin_one(item) for item in candidates),
        )


def _limits(entry: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """(context length, max completion tokens): the smaller listed context, the provider limit."""
    top = entry.get("top_provider") or {}
    contexts = [
        value
        for value in (entry.get("context_length"), top.get("context_length"))
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    completion = top.get("max_completion_tokens")
    valid = isinstance(completion, int) and not isinstance(completion, bool) and completion > 0
    return (min(contexts) if contexts else None, completion if valid else None)


def _produces_text(entry: Mapping[str, Any]) -> bool:
    outputs = (entry.get("architecture") or {}).get("output_modalities") or ()
    return "text" in outputs


def _excluded(setting: CandidateSetting, reason: str) -> PinnedCandidate:
    zero = Decimal(0)
    return PinnedCandidate(
        key=setting.key,
        requested_model_id=setting.model_id,
        resolution=setting.resolution,
        slug=setting.model_id,
        canonical_slug=setting.model_id,
        created=None,
        prompt_price=zero,
        completion_price=zero,
        request_price=zero,
        base_prompt_price=zero,
        base_completion_price=zero,
        price_basis="unavailable",
        supported_parameters=(),
        supported_efforts=None,
        eligible=False,
        exclusion_reason=reason,
    )
