# mypy: ignore-missing-imports, allow-subclassing-any
"""Hybrid CP-1 measurement: the four CP-1 steps with read-only pack tools across Sol, Opus and
Sonnet (experiment only: evidence, not adoption; decision 0005 names Sol at high).

Each cell (model, provider, effort) runs `source_context` -> `financials` -> `narrative` ->
`readiness` (`CP1_STEPS`, the runner's order) on its own copy of one frozen, accepted CP-0
journal (hybrid-cp0-1 hybrid-2); CP-0 is never re-run. A step's prompt is the runner's
(`prompts.build` with no SOURCE inputs and the bounded `step:` projections M7's
`_upstream(store, attempt, step_id)` offers), with rule 5 replaced as in hybrid CP-0; its tools
are `search_pack`, `read_pages` and `submit_<step_id>`, whose input schema is the step's sent
schema (`strict_schema`: M7 leaves out every hash binding Python pre-fills). Every submit is
judged on the runner's path (`submit_model_payload`, which pre-fills the bindings, then
`journal_outcome`) in a fresh copy of the step's starting journal, so each submit is judged as a
first try (M7 would keep a rejected one as the step's repair within the attempt); an accepted
copy is the journal the next step starts from. A step that does not end accepted stops its cell.

Providers: OpenRouter through the product `ChatClient` (as hybrid CP-0), and Anthropic's
Messages API over the same stdlib `urllib_transport`. Anthropic reports no cost: it is computed
from usage at list prices and recorded as `computed-from-list-prices`. Anthropic replies are
parsed with Decimal numbers and bodies re-serialised with `schema.exact_json`, so tool inputs
and the assistant content sent back keep their exact digits.

Money: one ledger per provider. Every call commits a reservation first: OpenRouter as hybrid
CP-0; Anthropic as the prompt-token bound at the higher of the input and 5-minute cache-write
prices (automatic caching may write the whole prompt) plus MAX_TOKENS at the output price. A
call settles with the reported (OpenRouter) or computed (Anthropic) cost; an HTTP 4xx other than
408 settles at zero (the runner's `_cost` rule); otherwise the whole reservation is held. A
refused reservation, exhausted credit or a refused key stops every remaining cell of that
provider, and the other provider's cells go on.

Keys: `credential.py`'s loader matches only `sk-or-` tokens, so the Anthropic key is found here
with the same textutil conversion: the one token starting `sk-ant-` among the file's distinct
`sk-` tokens. Only its index and the token count are printed or recorded. Both keys are held in
memory for the batch (as hybrid CP-0) and never written; replies are scrubbed of the exact key
and of `sk-or-`/`sk-ant-` shapes.
"""

import argparse
import json
import math
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol

from deploy_vii.cp1_workflow import CP1_STEPS  # type: ignore[import-untyped]
from deploy_vii.execution import Execution  # type: ignore[import-untyped]
from deploy_vii.live.catalog import Catalog, CatalogError, ModelSelection, PinnedCandidate  # type: ignore[import-untyped]
from deploy_vii.live.client import (  # type: ignore[import-untyped]
    DEFAULT_TIMEOUT_SECONDS,
    PROVIDER_DETAIL_CHARS,
    ChatClient,
    ChatRequest,
    ChatResult,
    Request,
    Transport,
    TransportError,
    _count,
    urllib_transport,
)
from deploy_vii.live.credential import (  # type: ignore[import-untyped]
    REDACTED,
    CredentialError,
    LoadedKey,
    load_key_with_note,
    redact,
    scrub_key,
)
from deploy_vii.live.ledger import CapExceeded, Ledger, LedgerError, Settlement  # type: ignore[import-untyped]
from deploy_vii.live.prompts import PromptError, UpstreamInput, build  # type: ignore[import-untyped]
from deploy_vii.live.runner import (  # type: ignore[import-untyped]
    TOKEN_OVERHEAD,
    _cost,
    _upstream,
    expected_step,
    journal_outcome,
    prompt_token_bound,
    reservation_usd,
    schema_shaped,
)
from deploy_vii.live.schema import exact_json, strict_schema  # type: ignore[import-untyped]
from deploy_vii.live.settings import DEFAULT_SETTINGS, load_settings  # type: ignore[import-untyped]
from deploy_vii.live.submission import STEPS, submit_model_payload  # type: ignore[import-untyped]
from deploy_vii.preparation import PreparedPack  # type: ignore[import-untyped]
from devtools import hybrid_cp0 as cp0

BATCH_ID = "hybrid-cp1-1"
CP0_JOURNAL = cp0.ARTIFACT_ROOT / "hybrid-cp0-1" / "hybrid-2" / "journal-submit-1"
MAX_TOKENS = cp0.MAX_TOKENS
MAX_CALLS = 30
DEADLINE_S = 1200.0
MAX_SUBMITS = cp0.MAX_SUBMITS
CAPS = {"openrouter": Decimal(8), "anthropic": Decimal(17)}
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MILLION = Decimal(1_000_000)
# Opus 5.5 and Sonnet 5.5 context window (claude-api reference, models.md). A prompt whose bound
# plus MAX_TOKENS exceeds it is not sent, as `PinnedCandidate.misfit` does for OpenRouter.
CONTEXT_TOKENS = 1_000_000
USAGE = ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens")
EVIDENCE = ("citations", "limitations", "claims", "objects")
CLAIM_LISTS = frozenset({"analysis", "claims", "events", "findings", "gaps", "stories"})
CITATION_LISTS = frozenset({"citations", "evidence", "evidence_ids"})
_ANY_KEY = re.compile(r"(?<![\w-])sk-[A-Za-z0-9_\-]{6,}+(?![\w-])")
_ANT_SHAPE = re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_\-]{6,}")
_SCHEMA_ERROR = re.compile(r"input_schema|invalid[ _](json[ _])?schema|json schema", re.IGNORECASE)


@dataclass(frozen=True)
class Cell:
    cell_id: str
    model: str
    provider: str  # openrouter or anthropic
    effort: str


CELLS = (
    Cell("sol-medium", cp0.MODEL, "openrouter", "medium"),
    Cell("sol-high", cp0.MODEL, "openrouter", "high"),
    Cell("opus-medium", "claude-opus-5-5", "anthropic", "medium"),
    Cell("opus-high", "claude-opus-5-5", "anthropic", "high"),
    Cell("sonnet-xhigh", "claude-sonnet-5-5", "anthropic", "xhigh"),
    Cell("sonnet-max", "claude-sonnet-5-5", "anthropic", "max"),
)


@dataclass(frozen=True)
class Prices:
    """Anthropic list prices, USD per million tokens."""

    input: Decimal
    write_5m: Decimal
    write_1h: Decimal
    read: Decimal
    output: Decimal


PRICES = {
    "claude-opus-5-5": Prices(
        Decimal("4.00"), Decimal("5.00"), Decimal("8.00"), Decimal("0.20"), Decimal("20.00")
    ),
    # Cache reads at 0.10: Anthropic release note of 7 October 2026, which lowered them from
    # 0.20 (coordinator, fetched 23 Oct 2026 via Context7; the bundled claude-api reference
    # still lists 0.20).
    "claude-sonnet-5-5": Prices(
        Decimal("2.00"), Decimal("2.50"), Decimal("4.00"), Decimal("0.10"), Decimal("10.00")
    ),
}


class ProviderStop(Exception):
    """A provider cannot go on (cap reached, credit exhausted, key refused)."""


# --- prompt and tools ------------------------------------------------------------------------


def submit_name(step_id: str) -> str:
    return f"submit_{step_id}"


def hybrid_prompt(
    step_id: str, pack: PreparedPack, upstream: Sequence[UpstreamInput]
) -> tuple[str, str]:
    """(system, user): the runner's prompt without pack SOURCE blocks. The CONTEXT and `step:`
    upstream blocks are `build`'s own text; only rule 5 is replaced."""
    system, user = build(step_id, pack, (), STEPS[step_id].schema, upstream=upstream)
    if system.content.count(cp0.NO_TOOLS_RULE) != 1:
        raise PromptError("the runner's system prompt no longer holds the no-tools rule once")
    rule = cp0.tools_rule(submit_name(step_id))
    return system.content.replace(cp0.NO_TOOLS_RULE, rule), user.content


Tool = tuple[str, str, dict[str, Any]]  # name, description, JSON Schema


def step_tools(step_id: str) -> tuple[Tool, ...]:
    """hybrid CP-0's search_pack and read_pages, and this step's submit tool."""
    pack_tools = tuple(
        (spec["function"]["name"], spec["function"]["description"], spec["function"]["parameters"])
        for spec in cp0.tool_specs()
        if spec["function"]["name"] in ("search_pack", "read_pages")
    )
    submit = (
        submit_name(step_id),
        f"Submit the {step_id} JSON object. Answers `accepted` or the validator's issues.",
        strict_schema(STEPS[step_id].schema),
    )
    return (*pack_tools, submit)


# --- provider replies ------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # JSON text: OpenRouter's own string; Anthropic's input with exact digits
    problem: str | None = None


@dataclass(frozen=True)
class Reply:
    """One provider reply, normalised. Unknown usage is None with a reason, never zero."""

    classification: str
    http_status: int | None
    raw: bytes | None  # key-scrubbed
    latency_s: float
    cost: Decimal | None
    cost_basis: str
    cost_reason: str
    error_detail: str | None = None
    finish_reason: str | None = None
    served_model: str | None = None
    request_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    turn: tuple[dict[str, Any], ...] = ()  # what the conversation appends, unmodified
    usage: Mapping[str, int | None] = field(default_factory=dict)
    usage_missing: Mapping[str, str] = field(default_factory=dict)
    schema_rejected: bool = False
    tool_choice_rejected: bool = False
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Prepared:
    payload: bytes  # the exact request body sent; retained as call-NN-request.json
    bound: int
    reserve: Decimal
    misfit: str | None
    tool_choice: str
    timeout_s: float
    request: ChatRequest | None = None  # OpenRouter only


class Provider(Protocol):
    name: str

    def prepare(
        self,
        cell: Cell,
        system: str,
        conversation: Sequence[Mapping[str, Any]],
        tools: Sequence[Tool],
        timeout_s: float,
    ) -> Prepared: ...

    def send(self, cell: Cell, prepared: Prepared, key: str) -> Reply: ...

    def tool_results(self, results: Sequence[tuple[str, str]]) -> list[dict[str, Any]]: ...


@dataclass
class OpenRouter:
    client: ChatClient
    candidate: PinnedCandidate
    bytes_per_token: Decimal
    name: str = "openrouter"

    def prepare(
        self,
        cell: Cell,
        system: str,
        conversation: Sequence[Mapping[str, Any]],
        tools: Sequence[Tool],
        timeout_s: float,
    ) -> Prepared:
        request = cp0.ToolChatRequest(
            model=self.candidate.slug,
            messages=(),
            max_tokens=MAX_TOKENS,
            response_format={},
            reasoning_effort=cell.effort,
            accepted_model_ids=(self.candidate.slug, self.candidate.canonical_slug),
            timeout_s=timeout_s,
            conversation=({"role": "system", "content": system}, *conversation),
            tools=tuple(
                {"type": "function", "function": {"name": n, "description": d, "parameters": s}}
                for n, d, s in tools
            ),
        )
        body = request.body()
        bound = prompt_token_bound(body, self.bytes_per_token)
        return Prepared(
            payload=json.dumps(body, sort_keys=True).encode(),  # what ChatClient sends
            bound=bound,
            reserve=reservation_usd(self.candidate, bound, MAX_TOKENS),
            misfit=self.candidate.misfit(bound, MAX_TOKENS),
            tool_choice=request.tool_choice,
            timeout_s=timeout_s,
            request=request,
        )

    def send(self, cell: Cell, prepared: Prepared, key: str) -> Reply:
        assert prepared.request is not None
        return openrouter_reply(self.candidate, self.client.complete(prepared.request, key=key))

    def tool_results(self, results: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
        return [{"role": "tool", "tool_call_id": ident, "content": text} for ident, text in results]


def openrouter_reply(candidate: PinnedCandidate, result: ChatResult) -> Reply:
    """The client's classified result; cost by the runner's own `_cost` rule."""
    cost = _cost(candidate, result)
    calls: list[ToolCall] = []
    turn: tuple[dict[str, Any], ...] = ()
    if result.classification == "ok":
        message = cp0._message(result)
        listed = message.get("tool_calls")
        if isinstance(listed, list) and listed:
            for item in listed:
                try:
                    calls.append(ToolCall(*cp0._call_parts(item)))
                except cp0.ToolError as error:
                    calls.append(ToolCall("", "", json.dumps(item), str(error)))
            turn = (message,)  # unmodified, with any reasoning_details
    usage = result.usage
    return Reply(
        classification=result.classification,
        http_status=result.http_status,
        raw=result.raw,
        latency_s=result.latency_s,
        cost=cost.amount,
        cost_basis=cost.basis,
        cost_reason=cost.reason,
        error_detail=result.error_detail,
        finish_reason=result.finish_reason,
        served_model=result.served_model,
        request_id=result.provider_request_id,
        tool_calls=tuple(calls),
        turn=turn,
        usage={name: getattr(usage, name) for name in USAGE},
        usage_missing={name: why for name, why in usage.missing.items() if name in USAGE},
        schema_rejected=schema_shaped(result),
        extras={
            "served_provider": result.served_provider,
            "identity_verified": result.identity_verified,
            "provider_error_code": result.provider_error_code,
            "retry_after": result.retry_after,
        },
    )


def scrub(text: str, key: str) -> str:
    """`scrub_key` (the exact key, `sk-or-` shapes) and `sk-ant-` shapes."""
    return _ANT_SHAPE.sub(REDACTED, scrub_key(text, key))


def token_bound(size: int, bytes_per_token: Decimal) -> int:
    """`prompt_token_bound` over a body's exact byte count (Anthropic bodies hold Decimals)."""
    if not bytes_per_token.is_finite() or bytes_per_token <= 0:
        raise ValueError("bytes_per_token must be a positive finite amount")
    return math.ceil(Fraction(size) / Fraction(bytes_per_token)) + int(TOKEN_OVERHEAD)


def anthropic_reservation(prices: Prices, bound: int) -> Decimal:
    return (bound * max(prices.input, prices.write_5m) + MAX_TOKENS * prices.output) / MILLION


@dataclass
class Anthropic:
    transport: Transport
    bytes_per_token: Decimal
    clock: Callable[[], float] = time.monotonic
    tool_choice: str = "any"  # "auto" after a 400 naming tool_choice, for every later call
    fallback: dict[str, Any] | None = None
    name: str = "anthropic"

    def body(
        self,
        cell: Cell,
        system: str,
        conversation: Sequence[Mapping[str, Any]],
        tools: Sequence[Tool],
    ) -> dict[str, Any]:
        return {
            "model": cell.model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": list(conversation),
            "tools": [{"name": n, "description": d, "input_schema": s} for n, d, s in tools],
            "tool_choice": {"type": self.tool_choice},
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": cell.effort},
            "cache_control": {"type": "ephemeral"},
        }

    def prepare(
        self,
        cell: Cell,
        system: str,
        conversation: Sequence[Mapping[str, Any]],
        tools: Sequence[Tool],
        timeout_s: float,
    ) -> Prepared:
        payload = exact_json(self.body(cell, system, conversation, tools)).encode()
        bound = token_bound(len(payload), self.bytes_per_token)
        needed = bound + MAX_TOKENS
        return Prepared(
            payload=payload,
            bound=bound,
            reserve=anthropic_reservation(PRICES[cell.model], bound),
            misfit=None
            if needed <= CONTEXT_TOKENS
            else f"context {CONTEXT_TOKENS} < bound {needed}",
            tool_choice=self.tool_choice,
            timeout_s=timeout_s,
        )

    def send(self, cell: Cell, prepared: Prepared, key: str) -> Reply:
        http = Request(
            url=ANTHROPIC_URL,
            method="POST",
            headers={
                "x-api-key": key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            body=prepared.payload,
            timeout_s=prepared.timeout_s,
        )
        started = self.clock()
        try:
            response = self.transport(http)
        except TimeoutError:
            return Reply(
                classification="timeout",
                http_status=None,
                raw=None,
                latency_s=self.clock() - started,
                cost=None,
                cost_basis="unknown",
                cost_reason="no response received; reservation held",
                error_detail="request timed out",
            )
        except (TransportError, OSError) as error:  # re-raised with the key scrubbed
            raise TransportError(
                scrub(redact(f"{type(error).__name__}: {error}", key), key)
            ) from None
        return anthropic_reply(
            cell.model, response.status, response.body, key, self.clock() - started
        )

    def tool_results(self, results: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
        blocks = [
            {"type": "tool_result", "tool_use_id": ident, "content": text}
            for ident, text in results
        ]
        return [{"role": "user", "content": blocks}] if blocks else []


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def anthropic_reply(model: str, status: int, body: bytes, key: str, latency: float) -> Reply:
    """Classify a Messages API reply: ok, truncated (max_tokens), refusal, fallback (another
    model served), http_error or insufficient_credit."""
    text = scrub(body.decode("utf-8", errors="replace"), key)
    raw = text.encode()
    try:
        parsed = json.loads(text, parse_float=Decimal)
    except ValueError:
        parsed = None
    document: dict[str, Any] = parsed if isinstance(parsed, dict) else {}
    request_id = _text(document.get("id"))
    if not 200 <= status < 300 or not document or document.get("type") == "error":
        error = document.get("error")
        error = error if isinstance(error, dict) else {}
        message = scrub(redact(str(error.get("message", "")), key), key)[:PROVIDER_DETAIL_CHARS]
        kind = _text(error.get("type")) or "error"
        zero = 400 <= status < 500 and status != 408
        return Reply(
            classification="insufficient_credit"
            if status == 402 or "credit balance" in message.lower()
            else "http_error",
            http_status=status,
            raw=raw,
            latency_s=latency,
            cost=Decimal(0) if zero else None,
            cost_basis="known-zero" if zero else "unknown",
            cost_reason=f"HTTP {status} refused before inference"
            if zero
            else "no usage in the reply; reservation held",
            error_detail=f"HTTP {status} {kind}: {message}" if message else f"HTTP {status}",
            request_id=request_id,
            schema_rejected=status == 400 and bool(_SCHEMA_ERROR.search(message)),
            tool_choice_rejected=status == 400 and "tool_choice" in message,
        )
    content = document.get("content")
    blocks = content if isinstance(content, list) else []
    calls = tuple(
        _tool_use(item)
        for item in blocks
        if isinstance(item, dict) and item.get("type") == "tool_use"
    )
    stop = _text(document.get("stop_reason"))
    served = _text(document.get("model"))
    # The requested id or a dated snapshot of it (`<model>-<date>`) is the drawn model.
    classification = (
        "fallback"
        if served is not None and served != model and not served.startswith(f"{model}-")
        else "truncated"
        if stop == "max_tokens"
        else "refusal"
        if stop == "refusal"
        else "ok"
    )
    usage, missing, cost, reason = anthropic_usage(document.get("usage"), PRICES[model])
    return Reply(
        classification=classification,
        http_status=status,
        raw=raw,
        latency_s=latency,
        cost=cost,
        cost_basis="computed-from-list-prices" if cost is not None else "unknown",
        cost_reason=reason,
        finish_reason=stop,
        served_model=served,
        request_id=request_id,
        tool_calls=calls,
        turn=({"role": "assistant", "content": content},) if calls else (),
        usage=usage,
        usage_missing=missing,
        extras={k: document[k] for k in ("stop_details", "diagnostics", "usage") if k in document},
    )


def _tool_use(item: Mapping[str, Any]) -> ToolCall:
    ident, name, value = item.get("id"), item.get("name"), item.get("input")
    if not isinstance(ident, str) or not isinstance(name, str) or not isinstance(value, dict):
        return ToolCall(
            "", "", exact_json(dict(item)), "malformed tool_use block (id, name or input)"
        )
    return ToolCall(ident, name, exact_json(value))


def anthropic_usage(
    raw: object, prices: Prices
) -> tuple[dict[str, int | None], dict[str, str], Decimal | None, str]:
    """(usage, reasons for missing values, computed cost or None, cost reason).

    Prompt tokens are uncached input plus cache writes plus cache reads; completion tokens are
    `output_tokens`, which include thinking (billed as output)."""
    usage = raw if isinstance(raw, dict) else {}
    uncached = _count(usage.get("input_tokens"))
    written = _count(usage.get("cache_creation_input_tokens"))
    cached = _count(usage.get("cache_read_input_tokens"))
    output = _count(usage.get("output_tokens"))
    details = usage.get("output_tokens_details")
    thinking = _count(details.get("thinking_tokens")) if isinstance(details, dict) else None
    counts: dict[str, int | None] = {
        "prompt_tokens": None
        if uncached is None or written is None or cached is None
        else uncached + written + cached,
        "completion_tokens": output,
        "reasoning_tokens": thinking,
        "cached_tokens": cached,
    }
    reasons = {
        "prompt_tokens": "input_tokens, cache_creation_input_tokens or cache_read_input_tokens "
        "absent",
        "completion_tokens": "output_tokens absent",
        "reasoning_tokens": "output_tokens_details.thinking_tokens absent",
        "cached_tokens": "cache_read_input_tokens absent",
    }
    missing = {name: reasons[name] for name, value in counts.items() if value is None}
    if uncached is None or written is None or cached is None or output is None:
        return counts, missing, None, "usage incomplete; reservation held"
    breakdown = usage.get("cache_creation")
    five = (
        _count(breakdown.get("ephemeral_5m_input_tokens")) if isinstance(breakdown, dict) else None
    )
    if five is None:  # no breakdown: every cache write at the 1-hour price (the higher)
        five, basis = 0, "cache writes without a 5-minute breakdown priced at the 1-hour rate"
    else:
        basis = "cache writes split by usage.cache_creation; the rest at the 1-hour rate"
    if five > written:
        return counts, missing, None, "5-minute cache writes exceed all cache writes; held"
    cost = (
        uncached * prices.input
        + five * prices.write_5m
        + (written - five) * prices.write_1h
        + cached * prices.read
        + output * prices.output
    ) / MILLION
    return counts, missing, cost, f"computed-from-list-prices; {basis}"


# --- the Anthropic key ------------------------------------------------------------------------


def anthropic_token(text: str) -> LoadedKey:
    """The one `sk-ant-` token among the distinct standalone `sk-` tokens of `text`, with its
    1-based position and the token count. Messages hold counts only, never token text."""
    tokens = list(dict.fromkeys(match.group() for match in _ANY_KEY.finditer(text)))
    found = [n for n, token in enumerate(tokens, start=1) if token.startswith("sk-ant-")]
    if len(found) != 1:
        raise CredentialError(
            f"{len(found)} sk-ant- tokens among {len(tokens)} key-shaped tokens; need exactly one"
        )
    return LoadedKey(tokens[found[0] - 1], len(tokens), found[0])


def load_anthropic_key(path: Path) -> LoadedKey:
    """`credential.load_key_with_note`'s textutil conversion, then `anthropic_token`."""
    source = path.expanduser()
    textutil = shutil.which("textutil")
    if not source.is_file() or textutil is None:
        raise CredentialError("credential file or textutil unavailable; loading fails closed")
    try:
        done = subprocess.run(
            [textutil, "-convert", "txt", "-stdout", str(source)],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise CredentialError("textutil could not convert the credential file") from None
    if done.returncode != 0:
        raise CredentialError(f"textutil exited with status {done.returncode}")
    try:
        text = done.stdout.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CredentialError("credential file is not UTF-8 text") from None
    return anthropic_token(text)


# --- evidence counts -------------------------------------------------------------------------


def evidence_counts(payload: str) -> dict[str, int] | None:
    """What a CP-1 payload holds, for evidence density and shrink-to-pass (None: not an object).

    citations: items of `citations`, `*_citations`, `evidence` and `evidence_ids` lists;
    limitations: items of `limitations` lists plus non-empty `limitation`/`*_limitation` text;
    claims: items of analysis, claims, events, findings, gaps and stories lists; objects: every
    JSON object."""
    try:
        document = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(document, dict):
        return None
    counts = dict.fromkeys(EVIDENCE, 0)

    def walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        counts["objects"] += 1
        for name, value in node.items():
            if isinstance(value, list):
                if name in CITATION_LISTS or name.endswith("_citations"):
                    counts["citations"] += len(value)
                elif name == "limitations":
                    counts["limitations"] += len(value)
                elif name in CLAIM_LISTS:
                    counts["claims"] += len(value)
            elif (
                isinstance(value, str)
                and value
                and (name == "limitation" or name.endswith("_limitation"))
            ):
                counts["limitations"] += 1
            walk(value)

    walk(document)
    return counts


# --- one step --------------------------------------------------------------------------------


@dataclass
class Call:
    number: int
    reserved_usd: Decimal
    prompt_tokens_upper_bound: int
    request_bytes: int
    tool_choice: str
    reply: Reply | None = None
    transport_error: str | None = None
    settlement: Settlement | None = None
    tool_calls_requested: int = 0

    def to_record(self) -> dict[str, Any]:
        reply, settled = self.reply, self.settlement
        record: dict[str, Any] = {
            "call": self.number,
            "reserved_usd": self.reserved_usd,
            "prompt_tokens_upper_bound": self.prompt_tokens_upper_bound,
            "request_bytes": self.request_bytes,
            "tool_choice": self.tool_choice,
            "transport_error": self.transport_error,
            "charged_usd": settled.charged if settled else None,
            "cost_held": settled.unreconciled if settled else None,
            "overrun": settled.overrun if settled else None,
            "tool_calls_requested": self.tool_calls_requested,
        }
        if reply is None:
            why = self.transport_error or "no response received"
            return record | {"classification": None, "classification_reason": why}
        record |= {
            "classification": reply.classification,
            "http_status": reply.http_status,
            "latency_s": reply.latency_s,
            "finish_reason": reply.finish_reason,
            "served_model": reply.served_model,
            "request_id": reply.request_id,
            "error_detail": reply.error_detail,
            "cost_usd": reply.cost,
            "cost_basis": reply.cost_basis,
            "cost_reason": reply.cost_reason,
            "schema_rejected": reply.schema_rejected,
            "extras": dict(reply.extras),
        }
        for name in USAGE:
            reason = reply.usage_missing.get(name, "not reported")
            record |= cp0._nullable(name, reply.usage.get(name), reason)
        return record


@dataclass
class StepRun:
    step_id: str
    directory: Path
    calls: list[Call] = field(default_factory=list)
    verdict: str = "not run"
    verdict_reason: str | None = None
    wall_clock_s: float | None = None
    tool_time_s: float = 0.0
    submits: list[dict[str, Any]] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    final_payload: str | None = None
    accepted_journal: Path | None = None
    tools: cp0.PackTools | None = None


@dataclass
class CellRun:
    cell: Cell
    order: int
    directory: Path
    steps: list[StepRun] = field(default_factory=list)
    verdict: str = "not run"
    stopped_at: str | None = None
    wall_clock_s: float | None = None


@dataclass
class Harness:
    cp0_journal: Path
    providers: Mapping[str, Provider]
    ledgers: Mapping[str, Ledger]
    keys: Mapping[str, str] = field(repr=False)
    batch_directory: Path
    clock: Callable[[], float] = time.monotonic


def send(harness: Harness, cell: Cell, step: StepRun, prepared: Prepared) -> Call | None:
    """Retain the request, reserve, send, settle, retain the scrubbed reply. None: not sent
    (the step's verdict says why). A refused reservation raises ProviderStop."""
    number = len(step.calls) + 1
    attempt = f"{cell.cell_id}-{step.step_id}-call-{number:02d}"
    if prepared.misfit is not None:
        step.verdict, step.verdict_reason = "not sent: misfit", prepared.misfit
        return None
    with (step.directory / f"call-{number:02d}-request.json").open("xb") as stream:
        stream.write(prepared.payload)  # the body only: no header is retained
    ledger = harness.ledgers[cell.provider]
    try:
        ledger.reserve(attempt, prepared.reserve)
    except CapExceeded as error:
        raise ProviderStop(f"{attempt} not sent: {error}") from None
    call = Call(
        number, prepared.reserve, prepared.bound, len(prepared.payload), prepared.tool_choice
    )
    step.calls.append(call)
    try:
        provider = harness.providers[cell.provider]
        call.reply = provider.send(cell, prepared, harness.keys[cell.provider])
    except TransportError as error:  # the key is already scrubbed from the message
        call.transport_error = str(error)
    finally:
        reply = call.reply
        cost = reply.cost if reply else None
        reason = (
            f"{reply.cost_basis}: {reply.cost_reason}"
            if reply
            else "no response received; reservation held"
        )
        call.settlement = ledger.settle(attempt, cost, reason)
    response = step.directory / f"call-{number:02d}-response.json"
    if call.reply is not None and call.reply.raw is not None:
        with response.open("xb") as stream:
            stream.write(call.reply.raw)
    else:
        detail = call.transport_error or (call.reply.error_detail if call.reply else None)
        cp0._write(response, {"no_body": detail})
    return call


def run_step(harness: Harness, cell: Cell, step: StepRun, base: Path, ticket: str) -> None:
    """One step's hybrid conversation, bounded by MAX_CALLS calls and DEADLINE_S seconds."""
    step.directory.mkdir(parents=True)
    store = Execution(base)
    snapshot = store.read()
    attempt = next(item for item in snapshot.attempts if item.ticket_id == ticket)
    if expected_step(attempt, "CP-1") != step.step_id:
        raise ValueError(f"{step.step_id} is not the journal's next CP-1 step")
    pack = store.pack(snapshot)
    system, user = hybrid_prompt(step.step_id, pack, _upstream(store, attempt, step.step_id))
    step.tools = cp0.PackTools(pack)
    tools = step_tools(step.step_id)
    conversation: list[dict[str, Any]] = [{"role": "user", "content": user}]
    started = harness.clock()
    try:
        while step.verdict == "not run":
            elapsed = harness.clock() - started
            if len(step.calls) >= MAX_CALLS or elapsed >= DEADLINE_S:
                step.verdict = "rejected: limit"
                step.verdict_reason = f"{len(step.calls)} calls, {elapsed:.1f} s"
                break
            timeout = min(DEFAULT_TIMEOUT_SECONDS, DEADLINE_S - elapsed)
            provider = harness.providers[cell.provider]
            prepared = provider.prepare(cell, system, conversation, tools, timeout)
            call = send(harness, cell, step, prepared)
            if call is None:
                break
            _turn(harness, cell, step, call, conversation, (base, ticket))
            if step.verdict == "no-response: timeout" and harness.clock() - started >= DEADLINE_S:
                step.verdict = "rejected: limit"  # the call's bound was the step's deadline
                step.verdict_reason = (
                    f"deadline of {DEADLINE_S} s reached during call {call.number}"
                )
    finally:
        step.wall_clock_s = harness.clock() - started


def _turn(
    harness: Harness,
    cell: Cell,
    step: StepRun,
    call: Call,
    conversation: list[dict[str, Any]],
    journal: tuple[Path, str],
) -> None:
    reply = call.reply
    provider = harness.providers[cell.provider]
    if reply is None or reply.classification != "ok":
        detail = call.transport_error or (reply.error_detail if reply else None)
        if reply and reply.tool_choice_rejected and isinstance(provider, Anthropic):
            if provider.tool_choice == "any":  # the next call resends with auto
                provider.tool_choice = "auto"
                provider.fallback = {
                    "cell": cell.cell_id,
                    "step": step.step_id,
                    "call": call.number,
                    "detail": detail,
                }
                return
        if reply and reply.schema_rejected:
            step.verdict, step.verdict_reason = "provider-schema-error", detail
            return
        cls = reply.classification if reply else "transport_error"
        step.verdict = "withheld-fallback" if cls == "fallback" else f"no-response: {cls}"
        step.verdict_reason = detail
        if cls == "insufficient_credit" or (reply and reply.http_status in (401, 403)):
            raise ProviderStop(f"{cell.provider} {step.verdict}: {detail}")
        return
    if not reply.tool_calls:
        step.verdict = "rejected: no-submit"
        step.verdict_reason = f"stop reason {reply.finish_reason}; no tool call"
        return
    call.tool_calls_requested = len(reply.tool_calls)
    conversation.extend(reply.turn)
    log = step.directory / "tool-calls.jsonl"
    results: list[tuple[str, str]] = []
    for index, tool_call in enumerate(reply.tool_calls, 1):
        entry = {"call": call.number, "index": index} | asdict(tool_call)
        if tool_call.problem is not None:
            step.verdict, step.verdict_reason = "rejected: malformed tool call", tool_call.problem
            cp0._append(log, entry | {"status": "error"})
            return
        if step.verdict != "not run":
            cp0._append(log, entry | {"status": "not executed: the step has a final verdict"})
            continue
        started = harness.clock()
        status, text = _execute(step, tool_call, journal)
        duration = harness.clock() - started
        step.tool_time_s += duration
        if status != "error":
            step.counts[tool_call.name] += 1
        cp0._append(log, entry | {"status": status, "result": text, "duration_s": duration})
        results.append((tool_call.call_id, text))
        if status == "accepted" or (status == "rejected" and len(step.submits) >= MAX_SUBMITS):
            step.verdict = status
    conversation.extend(provider.tool_results(results))


def _execute(step: StepRun, tool_call: ToolCall, journal: tuple[Path, str]) -> tuple[str, str]:
    """(status, result text) of one tool call; refusals are results, never raised. A submit is
    judged in a fresh copy of the step's starting journal."""
    assert step.tools is not None
    name, arguments = tool_call.name, tool_call.arguments
    try:
        raw = json.loads(arguments)
        if not isinstance(raw, dict):
            raise cp0.ToolError("bad arguments: not a JSON object")
        if name == "search_pack":
            return "ok", step.tools.search_pack(raw)
        if name == "read_pages":
            return "ok", step.tools.read_pages(raw)
        if name != submit_name(step.step_id):
            raise cp0.ToolError(f"unknown tool {name!r}")
    except json.JSONDecodeError:
        step.counts["invalid"] += 1
        return "error", "error: bad arguments: invalid JSON"
    except (cp0.ToolError, PromptError) as error:
        step.counts["invalid"] += 1
        return "error", f"error: {error}"
    number = len(step.submits) + 1
    base, ticket = journal
    directory = step.directory / f"journal-submit-{number}"
    shutil.copytree(base, directory)
    store = Execution(directory)
    submitted = submit_model_payload(store, ticket, step.step_id, arguments)
    outcome, issues = journal_outcome(store, step.step_id, submitted.journal)
    step.final_payload = arguments
    step.submits.append(
        {
            "submit": number,
            "outcome": outcome,
            "issues": list(issues),
            "issue_classes": dict(Counter(map(cp0.issue_class, issues))),
            "counts": evidence_counts(arguments),
        }
    )
    if outcome == "accepted":
        step.accepted_journal = directory
        return "accepted", "accepted"
    listed = "\n".join(f"- {issue}" for issue in issues)
    return "rejected", f"rejected ({MAX_SUBMITS - number} submits left):\n{listed}"


# --- cells and the batch ---------------------------------------------------------------------


def run_cell(harness: Harness, run: CellRun) -> None:
    """CP-1 on a copy of the frozen CP-0 journal; stops at the first step not accepted."""
    run.directory.mkdir(parents=True)
    base = run.directory / "journal-start"
    shutil.copytree(harness.cp0_journal, base)
    ticket = Execution(base).begin("CP-1").ticket_id
    started = harness.clock()
    try:
        for step_id in CP1_STEPS:
            step = StepRun(step_id, run.directory / step_id)
            run.steps.append(step)
            run_step(harness, run.cell, step, base, ticket)
            if step.verdict != "accepted" or step.accepted_journal is None:
                run.verdict, run.stopped_at = f"stopped at {step_id}: {step.verdict}", step_id
                return
            base = step.accepted_journal
        run.verdict = "accepted"
    finally:
        run.wall_clock_s = harness.clock() - started


def _summed(calls: Sequence[Call], name: str) -> dict[str, object]:
    """A step's total of one usage count over calls that reached inference (known-zero
    refusals add nothing); null with a reason when such a call lacks it."""
    counted = [c for c in calls if not (c.reply and c.reply.cost_basis == "known-zero")]
    if not counted:
        return {name: None, f"{name}_reason": "no call reached inference"}
    values = [c.reply.usage.get(name) if c.reply else None for c in counted]
    missing = [c.number for c, value in zip(counted, values, strict=True) if value is None]
    if missing:
        return {name: None, f"{name}_reason": f"not reported on calls {missing}"}
    return {name: sum(value for value in values if value is not None)}


def _money(calls: Sequence[Call]) -> dict[str, Decimal]:
    settled = [c.settlement for c in calls if c.settlement]
    return {
        "cost_settled_usd": sum((s.charged for s in settled if not s.unreconciled), Decimal(0)),
        "cost_held_usd": sum((s.charged for s in settled if s.unreconciled), Decimal(0)),
    }


def step_metrics(step: StepRun) -> dict[str, Any]:
    final = step.final_payload
    cited = cp0.cited_locators(final) if final else set()
    metrics: dict[str, Any] = {
        "step_id": step.step_id,
        "verdict": step.verdict,
        "verdict_reason": step.verdict_reason,
        "wall_clock_s": step.wall_clock_s,
        "tool_time_s": step.tool_time_s,
        "calls": len(step.calls),
        "latency_s": [c.reply.latency_s if c.reply else None for c in step.calls],
        "per_call": [c.to_record() for c in step.calls],
        **_money(step.calls),
        "cost_bases": sorted({c.reply.cost_basis for c in step.calls if c.reply}),
        "submits": step.submits,
        "first_submit_accepted": step.submits[0]["outcome"] == "accepted" if step.submits else None,
        "submit_shrinkage": cp0.shrinkage(step.submits, EVIDENCE),
        "issue_classes": dict(
            sum((Counter(item["issue_classes"]) for item in step.submits), Counter())
        ),
        "tool_calls": {
            name: step.counts[name]
            for name in ("search_pack", "read_pages", submit_name(step.step_id), "invalid")
        },
        "final_payload_evidence": evidence_counts(final) if final else None,
    }
    for name in USAGE:
        metrics |= _summed(step.calls, name)
    tools = step.tools
    if tools is None:
        return metrics | {"coverage": None, "coverage_reason": "the step did not start"}
    metrics["coverage"] = {
        "pages_read": len(tools.read),
        "located_pages": tools.located_pages,
        "spans_surfaced_by_search": len(tools.surfaced),
        "final_payload_cited_locators": len(cited),
        "cited_not_read": sorted(cited - tools.read),
    }
    return metrics


def cell_metrics(run: CellRun) -> dict[str, Any]:
    calls = [call for step in run.steps for call in step.calls]
    return {
        **asdict(run.cell),
        "order": run.order,
        "verdict": run.verdict,
        "stopped_at": run.stopped_at,
        "wall_clock_s": run.wall_clock_s,
        **_money(calls),
        "steps": [step_metrics(step) for step in run.steps],
    }


def run_batch(
    harness: Harness, runs: Sequence[CellRun], *, seed: int, prior: cp0.PriorSpend | None = None
) -> dict[str, Any]:
    """Run the cells in order. A ProviderStop skips that provider's remaining cells and is
    recorded, never raised; the other provider's cells go on."""
    stopped: dict[str, str] = {}
    for run in runs:
        provider = run.cell.provider
        if provider in stopped:
            run.verdict = f"not run: {provider} stopped"
            continue
        try:
            run_cell(harness, run)
        except ProviderStop as stop:
            stopped[provider] = str(stop)
            step = run.steps[-1] if run.steps else None
            if step is not None and step.verdict == "not run":
                step.verdict, step.verdict_reason = "stopped", str(stop)
            run.stopped_at = step.step_id if step else None
            run.verdict = f"stopped at {run.stopped_at}: {stop}"
        finally:  # also when an unexpected error propagates: the evidence is kept
            if run.directory.exists():
                cp0._write(run.directory / "metrics.json", cell_metrics(run))
    anthropic = harness.providers.get("anthropic")
    summary = {
        "seed": seed,
        "order": [run.cell.cell_id for run in runs],
        "stopped_providers": stopped,
        "tool_choice_fallback": anthropic.fallback if isinstance(anthropic, Anthropic) else None,
        "prior_committed": None
        if prior is None
        else {"total_usd": prior.total, "worst_case_adjusts": list(prior.worst_case_adjusts)},
        "ledgers": {
            name: {
                "path": ledger.path,
                "cap": (state := ledger.state()).cap,
                "reserved_open": state.reserved,
                "spent": state.spent,
                "overrun": state.overrun,
                "attempts": len(state.attempts),
            }
            for name, ledger in harness.ledgers.items()
        },
        "cells": [
            {key: value for key, value in cell_metrics(run).items() if key != "steps"}
            | {
                "steps": [
                    {
                        key: step_metrics(step)[key]
                        for key in (
                            "step_id",
                            "verdict",
                            "wall_clock_s",
                            "calls",
                            "cost_settled_usd",
                            "cost_held_usd",
                            "first_submit_accepted",
                        )
                    }
                    for step in run.steps
                ]
            }
            for run in runs
        ],
    }
    cp0._write(harness.batch_directory / "batch-summary.json", summary)
    return summary


# --- command line ----------------------------------------------------------------------------


def cp1_start(journal: Path) -> tuple[PreparedPack, str, str]:
    """The pack and the `source_context` prompt of a CP-1 ticket begun on a scratch copy of the
    frozen CP-0 journal (the journal itself is never written). Raises when CP-1 cannot start."""
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "journal"
        shutil.copytree(journal, copy)
        store = Execution(copy)
        attempt = store.begin("CP-1")
        step = expected_step(attempt, "CP-1")
        if step != CP1_STEPS[0]:
            raise ValueError(f"a fresh CP-1 ticket expects {step}, not {CP1_STEPS[0]}")
        pack = store.pack()
        system, user = hybrid_prompt(step, pack, _upstream(store, attempt, step))
    return pack, system, user


def step_prompts(
    journal: Path,
    payload_for: Callable[[str], str],
    providers: Mapping[str, Provider],
    cells: Sequence[Cell],
) -> list[dict[str, Any]]:
    """Each step's first-call prompt size and reservation per cell, on a scratch copy of the
    frozen CP-0 journal into which `payload_for(step)` (representative retained payloads) is
    entered on the runner's path after each step is measured. Stops at the first payload the
    journal does not accept. Nothing is sent."""
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "journal"
        shutil.copytree(journal, copy)
        store = Execution(copy)
        ticket = store.begin("CP-1").ticket_id
        for step_id in CP1_STEPS:
            attempt = next(item for item in store.read().attempts if item.ticket_id == ticket)
            upstream = _upstream(store, attempt, step_id)
            system, user = hybrid_prompt(step_id, store.pack(), upstream)
            conversation = [{"role": "user", "content": user}]
            tools = step_tools(step_id)
            per_cell = {}
            for cell in cells:
                prepared = providers[cell.provider].prepare(
                    cell, system, conversation, tools, DEFAULT_TIMEOUT_SECONDS
                )
                per_cell[cell.cell_id] = {
                    "request_bytes": len(prepared.payload),
                    "prompt_tokens_upper_bound": prepared.bound,
                    "reserved_usd": prepared.reserve,
                    "misfit": prepared.misfit,
                }
            payload = payload_for(step_id)
            submitted = submit_model_payload(store, ticket, step_id, payload)
            outcome, issues = journal_outcome(store, step_id, submitted.journal)
            rows.append(
                {
                    "step_id": step_id,
                    "system_chars": len(system),
                    "user_chars": len(user),
                    "upstream": [
                        {"input_id": u.input_id, "projection": u.projection, "chars": len(u.text)}
                        for u in upstream
                    ],
                    "first_call_per_cell": per_cell,
                    "representative_payload": {
                        "chars": len(payload),
                        "outcome": outcome,
                        "issues": list(issues),
                    },
                }
            )
            if outcome != "accepted":
                break
    return rows


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        prog="python -m devtools.hybrid_cp1", description="Hybrid CP-1 across Sol, Opus, Sonnet"
    )
    command.add_argument("--dry-run", action="store_true", help="plan only: no model call")
    command.add_argument("--batch-id", default=BATCH_ID)
    command.add_argument("--cap-openrouter", type=cp0._money, default=CAPS["openrouter"])
    command.add_argument("--cap-anthropic", type=cp0._money, default=CAPS["anthropic"])
    command.add_argument("--seed", type=int, help="cell order seed; else drawn and recorded")
    command.add_argument("--cp0-journal", type=Path, default=CP0_JOURNAL)
    command.add_argument("--artifact-root", type=Path, default=cp0.ARTIFACT_ROOT)
    command.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    command.add_argument("--catalog", type=Path, help="saved models JSON; else fetched (public)")
    command.add_argument(
        "--upstream-from",
        help="measure every step's prompt with retained payloads: PREFIX-<step>-1/output.md",
    )
    return command


def _refuse(reason: str) -> int:
    print(f"refused: {reason}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None, *, transport: Transport = urllib_transport) -> int:
    args = parser().parse_args(argv)
    settings = load_settings(args.settings)
    caps = {"openrouter": args.cap_openrouter, "anthropic": args.cap_anthropic}
    ledgers = args.artifact_root / ".ledgers"
    paths = {name: ledgers / f"{args.batch_id}-{name}.jsonl" for name in caps}
    batch_directory = args.artifact_root / args.batch_id
    try:
        spend = cp0.prior_committed(ledgers)
    except LedgerError as error:  # an unreadable prior ledger leaves the ceiling unknown
        return _refuse(f"prior ledgers cannot be counted: {error}")
    for item in spend.worst_case_adjusts:
        print(
            f"worst case: {item['ledger']} seq {item['seq']} attempt {item['attempt_id']} "
            f"source {item['source']} counted at previous_charged_usd "
            f"{item['previous_charged_usd']}",
            file=sys.stderr,
        )
    ceiling = settings.caps.cumulative_ceiling
    total_cap = sum(caps.values(), Decimal(0))
    if spend.total + total_cap > ceiling:
        return _refuse(f"prior ledgers hold {spend.total} USD; with caps {total_cap} > {ceiling}")
    if any(path.exists() for path in paths.values()) or batch_directory.exists():
        return _refuse(f"{args.batch_id} already has a ledger or directory; use a new --batch-id")
    try:
        pack, system, user = cp1_start(args.cp0_journal)
    except (OSError, ValueError, PromptError) as error:
        return _refuse(f"the frozen CP-0 journal cannot start CP-1: {error}")
    try:
        catalog = Catalog.from_file(args.catalog) if args.catalog else Catalog.fetch(transport)
        pool = catalog.pin_selected(args.batch_id, (ModelSelection(cp0.MODEL, None),))
        candidate = pool.candidate(cp0.MODEL)
    except CatalogError as error:
        return _refuse(str(error))
    lacking = [p for p in ("tools", "tool_choice") if p not in candidate.supported_parameters]
    if not candidate.eligible or lacking:
        return _refuse(f"{cp0.MODEL} ineligible: {candidate.exclusion_reason or lacking}")
    efforts = {}
    for cell in CELLS:
        if cell.provider == "openrouter":
            decision = candidate.effort_for(cell.effort)
            if decision.sent != cell.effort:  # never measure an effort other than the one asked
                return _refuse(
                    f"{cell.cell_id}: effort {cell.effort} would be sent as {decision.sent}"
                )
            efforts[cell.cell_id] = decision.to_record()
    try:
        openrouter_key = load_key_with_note(
            settings.credential_file, settings.credential_token_index
        )
        anthropic_key = load_anthropic_key(settings.credential_file)
    except CredentialError as error:  # messages hold counts only
        return _refuse(f"credential: {error}")
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**32)
    order = list(CELLS)
    random.Random(seed).shuffle(order)
    bpt = settings.prompt_bytes_per_token_lower_bound
    providers: dict[str, Provider] = {
        "openrouter": OpenRouter(ChatClient(transport), candidate, bpt),
        "anthropic": Anthropic(transport, bpt),
    }
    first = [{"role": "user", "content": user}]
    tools = step_tools(CP1_STEPS[0])
    first_calls = {}
    for cell in order:
        prepared = providers[cell.provider].prepare(
            cell, system, first, tools, DEFAULT_TIMEOUT_SECONDS
        )
        first_calls[cell.cell_id] = {
            "request_bytes": len(prepared.payload),
            "prompt_tokens_upper_bound": prepared.bound,
            "reserved_usd": prepared.reserve,
            "tool_choice": prepared.tool_choice,
            "misfit": prepared.misfit,
        }
    plan = {
        "batch_id": args.batch_id,
        "seed": seed,
        "order": [{"order": n} | asdict(cell) for n, cell in enumerate(order, start=1)],
        "steps": list(CP1_STEPS),
        "cp0_journal": {"path": args.cp0_journal, "pack_sha256": pack.content_hash()},
        "located_pages": cp0.PackTools(pack).located_pages,
        "openrouter": {
            "pinned_candidate": candidate.to_record(),
            "catalog": {"source": catalog.source, "sha256": catalog.sha256},
            "efforts": efforts,
        },
        "anthropic": {
            "url": ANTHROPIC_URL,
            "version": ANTHROPIC_VERSION,
            "prices_usd_per_million": {model: asdict(p) for model, p in PRICES.items()},
            "cost_basis": "computed-from-list-prices",
            "tool_choice": "any first; auto after a 400 naming tool_choice",
            "thinking": {"type": "adaptive"},
        },
        "credential": {
            "recorded": False,
            "openrouter": openrouter_key.note(),
            "anthropic": anthropic_key.note()
            | {"rule": "the one sk-ant- token among the file's distinct sk- tokens"},
        },
        "limits": {
            "max_tokens_per_call": MAX_TOKENS,
            "calls_per_step": MAX_CALLS,
            "wall_clock_s_per_step": DEADLINE_S,
            "submits_per_step": MAX_SUBMITS,
        },
        "money": {
            "caps_usd": caps,
            "prior_committed_usd": spend.total,
            "prior_worst_case_adjusts": list(spend.worst_case_adjusts),
            "cumulative_ceiling_usd": ceiling,
            "ledgers": paths,
            "first_call_per_cell": first_calls,
            "later_calls": "reserved at send time from each call's own (growing) request body",
        },
        "retention": batch_directory,
    }
    if args.upstream_from:
        prefix = args.upstream_from

        def retained(step_id: str) -> str:
            return Path(f"{prefix}-{step_id}-1", "output.md").read_text(encoding="utf-8")

        plan["step_prompts"] = {
            "upstream_from": prefix,
            "steps": step_prompts(args.cp0_journal, retained, providers, order),
        }
    print(cp0._json(plan), end="")
    if args.dry_run:
        return 0
    batch_directory.mkdir(parents=True)
    cp0._write(batch_directory / "plan.json", plan)
    harness = Harness(
        cp0_journal=args.cp0_journal,
        providers=providers,
        ledgers={name: Ledger(path, caps[name]) for name, path in paths.items()},
        keys={"openrouter": openrouter_key.key, "anthropic": anthropic_key.key},
        batch_directory=batch_directory,
    )
    runs = [
        CellRun(cell, n, batch_directory / cell.cell_id) for n, cell in enumerate(order, start=1)
    ]
    print(cp0._json(run_batch(harness, runs, seed=seed, prior=spend)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
