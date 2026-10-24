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
Messages API streamed (`"stream": true`) over stdlib urllib with the same https-only,
no-redirect rules (`urllib_stream`): server-sent events are read line by line with an idle limit
of IDLE_S between bytes and the step's remaining wall-clock time for the whole stream; the
assistant content is rebuilt by block index (`assemble`) and the raw stream is retained. A
stream cut before `message_stop` is `stream-incomplete`: its reservation is held and its cell
stops. Every call allows MAX_TOKENS (128,000, as the e1-cp1 batches) and may use the rest of
its step's wall-clock limit. Anthropic reports no cost: it is computed
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
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
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
    _NoRedirect,
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
from deploy_vii.live.reconcile import open_ledger  # type: ignore[import-untyped]
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
MAX_TOKENS = 128_000  # as the e1-cp1 batches (user decision, 23 Oct 2026)
MAX_CALLS = 30
DEADLINE_S = 1200.0
MAX_SUBMITS = cp0.MAX_SUBMITS
CAPS = {"openrouter": Decimal(15), "anthropic": Decimal(25)}
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
IDLE_S = 120.0  # longest silence allowed between stream bytes
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
# Run only when named with --cells (user decision, 23 Oct 2026: Luna at xhigh, after
# hybrid-cp1-1, on that batch's OpenRouter ledger). Decision 0005's amendment superseded Luna.
EXTRA_CELLS = (Cell("luna-xhigh", "openai/gpt-6-luna", "openrouter", "xhigh"),)
SKIPPED_BY_USER = "skipped by user"  # user decision, 24 Oct 2026: "skip opus high"
# Top-level Anthropic `cache_control` (default 5-minute TTL) goes on every step: narrative and
# readiness were multi-call in most hybrid-cp1-1/-2 cells. Each within-step cache miss there
# followed a call longer than 300 s; a top-level `ttl` of "1h" is documented but unmeasured.
CACHE_CONTROL = {
    "sent": "top-level {'type': 'ephemeral'} on every step (default 5-minute TTL)",
    "observed": "hybrid-cp1-1: every within-step cache miss (3) followed a call longer than "
    "300 s (633.4, 557.3, 329.0 s), the 5-minute TTL; no read followed such a call",
    "unmeasured_option": "top-level ttl '1h' (documented values '5m', '1h'); not measured",
}
# From this many calls left, each turn's tool results end with one line saying so.
NUDGE_FROM_CALLS_LEFT = 3


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
    raw_kind: str = "json"  # "sse": the key-scrubbed event stream as received


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
    candidates: Mapping[str, PinnedCandidate]  # by the cell's model id
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
        candidate = self.candidates[cell.model]
        request = cp0.ToolChatRequest(
            model=candidate.slug,
            messages=(),
            max_tokens=MAX_TOKENS,
            response_format={},
            reasoning_effort=cell.effort,
            accepted_model_ids=(candidate.slug, candidate.canonical_slug),
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
            reserve=reservation_usd(candidate, bound, MAX_TOKENS),
            misfit=candidate.misfit(bound, MAX_TOKENS),
            tool_choice=request.tool_choice,
            timeout_s=timeout_s,
            request=request,
        )

    def send(self, cell: Cell, prepared: Prepared, key: str) -> Reply:
        assert prepared.request is not None
        result = self.client.complete(prepared.request, key=key)
        return openrouter_reply(self.candidates[cell.model], result)

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


@dataclass(frozen=True)
class Stream:
    """An HTTP reply read line by line: the event stream of a 2xx, the error body otherwise.
    Iterating raises TimeoutError when no byte arrives within the transport's idle limit."""

    status: int
    lines: Iterator[bytes]


StreamTransport = Callable[[Request, float], Stream]  # (request, idle seconds)


def urllib_stream(request: Request, idle_s: float) -> Stream:
    """`urllib_transport` for a streamed reply: https only, no redirects, HTTP errors returned.
    Each socket operation waits at most `idle_s`, so a silent stream ends there; the caller
    enforces the overall wall-clock deadline between lines."""
    if not request.url.startswith("https://"):
        raise TransportError("only https endpoints are permitted")
    http = urllib.request.Request(
        request.url, data=request.body, headers=dict(request.headers), method=request.method
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        reply = opener.open(http, timeout=idle_s)
    except urllib.error.HTTPError as error:
        with error:
            return Stream(error.code, iter(error.read().splitlines(keepends=True)))
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise TimeoutError("request timed out") from None
        raise TransportError(f"network error: {type(error.reason).__name__}") from None

    def lines() -> Iterator[bytes]:
        with reply:
            while line := reply.readline():
                yield line

    return Stream(reply.status, lines())


@dataclass
class Events:
    events: list[dict[str, Any]]
    raw: list[str]
    cut: str | None  # why reading ended before `message_stop` or an `error` event


def read_events(
    lines: Iterator[bytes], deadline: float, clock: Callable[[], float], idle_s: float
) -> Events:
    """Server-sent events (`event:`/`data:` lines, a blank line ends one) parsed with Decimal
    numbers, up to `message_stop` or an `error` event. Every line read is kept."""
    events: list[dict[str, Any]] = []
    raw: list[str] = []
    data: list[str] = []
    try:
        for line in lines:
            text = line.decode("utf-8", errors="replace")
            raw.append(text)
            if clock() > deadline:
                return Events(events, raw, "the step's wall-clock deadline passed mid-stream")
            stripped = text.rstrip("\r\n")
            if stripped:
                field_name, _, value = stripped.partition(":")
                if field_name == "data":
                    data.append(value[1:] if value.startswith(" ") else value)
                continue  # `event:` names repeat the data's `type`; comments are ignored
            if not data:
                continue
            try:
                event = json.loads("\n".join(data), parse_float=Decimal)
            except ValueError:
                return Events(events, raw, "an event's data is not JSON")
            data = []
            if not isinstance(event, dict):
                return Events(events, raw, "an event's data is not a JSON object")
            events.append(event)
            if event.get("type") in ("message_stop", "error"):
                return Events(events, raw, None)
    except TimeoutError:
        return Events(events, raw, f"no byte for {idle_s} s (idle timeout)")
    except OSError as error:
        return Events(events, raw, f"connection lost: {type(error).__name__}")
    return Events(events, raw, "the stream ended before message_stop")


_DELTA_FIELDS = {
    "text_delta": ("text", "text"),
    "thinking_delta": ("thinking", "thinking"),
    "signature_delta": ("signature", "signature"),
}


def assemble(events: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], str | None]:
    """The Message the events describe, content rebuilt by index (thinking blocks with their
    signatures; each tool_use input parsed once from its joined `partial_json`, exact digits),
    usage merged (`message_start`, then every field of the last `message_delta`); or a problem
    when the events cannot be rebuilt exactly."""
    message: dict[str, Any] = {}
    blocks: dict[int, dict[str, Any]] = {}
    partial: dict[int, list[str]] = {}
    usage: dict[str, Any] = {}
    for event in events:
        kind = event.get("type")
        index = event.get("index")
        if kind == "message_start" and isinstance(event.get("message"), dict):
            message = dict(event["message"])
            usage.update(message.get("usage") or {})
        elif kind == "content_block_start" and isinstance(index, int):
            block = event.get("content_block")
            if not isinstance(block, dict) or index in blocks:
                return message, f"content block {index} starts twice or without a block"
            blocks[index] = dict(block)
            if block.get("type") == "tool_use":
                partial[index] = []
        elif kind == "content_block_delta" and isinstance(index, int):
            delta = event.get("delta")
            if index not in blocks or not isinstance(delta, dict):
                return message, f"delta for content block {index}, which has not started"
            if delta.get("type") == "input_json_delta" and index in partial:
                partial[index].append(str(delta.get("partial_json", "")))
            elif delta.get("type") in _DELTA_FIELDS:
                source, target = _DELTA_FIELDS[str(delta["type"])]
                blocks[index][target] = str(blocks[index].get(target) or "") + str(
                    delta.get(source, "")
                )
            else:
                return message, f"unknown delta type {delta.get('type')!r}"
        elif kind == "content_block_stop" and isinstance(index, int):
            if index not in blocks:
                return message, f"stop for content block {index}, which has not started"
            if index in partial:
                text = "".join(partial.pop(index)) or "{}"
                try:
                    blocks[index]["input"] = json.loads(text, parse_float=Decimal)
                except ValueError:
                    blocks[index]["input"] = text  # read as a malformed tool call
        elif kind == "message_delta":
            delta = event.get("delta")
            message.update(delta if isinstance(delta, dict) else {})
            usage.update(event.get("usage") or {})
        elif kind not in ("ping", "message_stop"):
            return message, f"unexpected event {kind!r}"
    if not message:
        return message, "no message_start event"
    if partial:
        return message, f"content blocks {sorted(partial)} never stopped"
    message["content"] = [blocks[index] for index in sorted(blocks)]
    message["usage"] = usage
    return message, None


@dataclass
class Anthropic:
    stream_transport: StreamTransport
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
            "cache_control": {"type": "ephemeral"},  # every step: see CACHE_CONTROL
            "stream": True,
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
        """One streamed call: an idle limit between bytes (IDLE_S) and the step's remaining
        wall-clock time (`prepared.timeout_s`) for the whole stream."""
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
        idle = min(IDLE_S, prepared.timeout_s)
        started = self.clock()
        try:
            stream = self.stream_transport(http, idle)
        except TimeoutError:
            return Reply(
                classification="timeout",
                http_status=None,
                raw=None,
                latency_s=self.clock() - started,
                cost=None,
                cost_basis="unknown",
                cost_reason="no response received; reservation held",
                error_detail="request timed out before the reply began",
            )
        except (TransportError, OSError) as error:  # re-raised with the key scrubbed
            raise TransportError(
                scrub(redact(f"{type(error).__name__}: {error}", key), key)
            ) from None
        if not 200 <= stream.status < 300:  # an error body, not a stream
            try:
                body = b"".join(stream.lines)
            except (TimeoutError, OSError):  # documented: the status alone classifies it
                body = b""
            return anthropic_reply(cell.model, stream.status, body, key, self.clock() - started)
        events = read_events(stream.lines, started + prepared.timeout_s, self.clock, idle)
        return stream_reply(cell.model, stream.status, events, key, self.clock() - started)

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
    if not 200 <= status < 300 or not document or document.get("type") == "error":
        return _error_reply(status, document, raw, latency, key)
    return _message_reply(model, status, document, raw, latency)


def _error_reply(
    status: int, document: Mapping[str, Any], raw: bytes, latency: float, key: str
) -> Reply:
    """An HTTP error reply: settled at zero for a 4xx other than 408, else held."""
    request_id = _text(document.get("id"))
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


def _message_reply(
    model: str,
    status: int,
    document: Mapping[str, Any],
    raw: bytes,
    latency: float,
    raw_kind: str = "json",
) -> Reply:
    """A Message: ok, truncated (max_tokens), refusal or fallback (another model served)."""
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
        request_id=_text(document.get("id")),
        tool_calls=calls,
        turn=({"role": "assistant", "content": content},) if calls else (),
        usage=usage,
        usage_missing=missing,
        extras={k: document[k] for k in ("stop_details", "diagnostics", "usage") if k in document},
        raw_kind=raw_kind,
    )


def stream_reply(model: str, status: int, events: Events, key: str, latency: float) -> Reply:
    """A streamed reply: an `error` event is the provider's failure; a stream cut before
    `message_stop` (or one that cannot be rebuilt exactly) is `stream-incomplete`. Both hold
    the reservation (tokens may have been generated). The raw stream is retained either way."""
    raw = scrub("".join(events.raw), key).encode()
    held = Reply(
        classification="stream-incomplete",
        http_status=status,
        raw=raw,
        latency_s=latency,
        cost=None,
        cost_basis="unknown",
        cost_reason="stream incomplete; reservation held",
        raw_kind="sse",
    )
    error = next((e for e in events.events if e.get("type") == "error"), None)
    if error is not None:
        found = error.get("error")
        detail: dict[str, Any] = found if isinstance(found, dict) else {}
        message = scrub(redact(str(detail.get("message", "")), key), key)[:PROVIDER_DETAIL_CHARS]
        return replace(
            held,
            classification="insufficient_credit"
            if "credit balance" in message.lower()
            else "http_error",
            cost_reason="error event mid-stream; reservation held",
            error_detail=f"stream error {detail.get('type', 'error')}: {message}",
        )
    document, problem = assemble(events.events)
    if events.cut is not None or problem is not None:
        return replace(
            held,
            error_detail=events.cut or problem,
            served_model=_text(document.get("model")),
            request_id=_text(document.get("id")),
        )
    return _message_reply(model, status, document, raw, latency, raw_kind="sse")


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


COMPLETENESS_COUNTED = ("statement_lines", "balance_movements")


def _objects(node: object, key: str) -> list[dict[str, Any]]:
    """The JSON objects in `node[key]` when that is a list (none otherwise)."""
    value = node.get(key) if isinstance(node, dict) else None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def completeness(payload: str) -> dict[str, Any] | None:
    """What a financials payload covers, summed over its books (None: not an object).

    Statement lines by `statement` and by the fiscal year of their period (`unknown` when the
    book lists no such period); accounts, balance movements and their bridges, statement
    identities; definition assessments and the distinct observation ids they name. Only string
    or integer ids are matched: anything else counts as unknown, with the reason recorded (a
    paid call's payload is measured, never raised on)."""
    try:
        document = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(document, dict):
        return None
    by_statement: Counter[str] = Counter()
    by_year: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    reasons: list[str] = []

    def note(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    for book in _objects(document.get("financial"), "books"):
        years: dict[str | int, str] = {}
        for period in _objects(book, "periods"):
            ident = _scalar_id(period.get("period_id"))
            if ident is None:
                note("a period's period_id is not a string or integer; its lines count as unknown")
            else:
                years[ident] = str(period.get("fiscal_year"))
        for line in _objects(book, "statement_lines"):
            by_statement[str(line.get("statement"))] += 1
            ident = _scalar_id(line.get("period_id"))
            if ident is None:
                note("a statement line's period_id is not a string or integer; counted as unknown")
            by_year["unknown" if ident is None else years.get(ident, "unknown")] += 1
        for key in (
            "accounts",
            "balance_movements",
            "balance_movement_bridges",
            "statement_identities",
        ):
            sizes[key] += len(_objects(book, key))
    assessments = _objects(document.get("definition"), "assessments")
    observed = {
        ident
        for item in assessments
        if isinstance(item.get("observation_ids"), list)
        for ident in item["observation_ids"]
        if isinstance(ident, str)
    }
    return {
        "statement_lines": sum(by_statement.values()),
        "statement_lines_by_statement": dict(sorted(by_statement.items())),
        "statement_lines_by_fiscal_year": dict(sorted(by_year.items())),
        "accounts": sizes["accounts"],
        "balance_movements": sizes["balance_movements"],
        "balance_movement_bridges": sizes["balance_movement_bridges"],
        "statement_identities": sizes["statement_identities"],
        "definition_assessments": len(assessments),
        "definition_observation_ids": len(observed),
        "reasons": reasons,
    }


def _scalar_id(value: object) -> str | int | None:
    """A usable id: a string or an integer (not a bool); None for anything else."""
    return value if isinstance(value, str | int) and not isinstance(value, bool) else None


def completeness_drop(submits: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Later financials submits with fewer statement lines or balance movements than the most
    any earlier submit held (so 5 -> 200 -> 50 is a drop at the third). It sits beside
    `submit_shrinkage`, which counts citations, limitations, claims and objects."""
    basis = "each later submit vs the most any earlier submit held"
    if len(submits) < 2:
        return {"flag": False, "dropped": [], "basis": "fewer than two submits"}
    most: dict[str, int] = {}
    dropped: list[dict[str, Any]] = []
    for index, item in enumerate(submits):
        counts = item["completeness"]
        if counts is None:
            if index:  # a later submit that is not an object holds nothing the earlier ones did
                dropped.append({"submit": item["submit"], "not_a_json_object": True})
            continue
        fewer = {
            k: [most[k], counts[k]] for k in COMPLETENESS_COUNTED if counts[k] < most.get(k, 0)
        }
        if fewer:
            dropped.append({"submit": item["submit"], "most_before_then_now": fewer})
        most = {k: max(most.get(k, 0), counts[k]) for k in COMPLETENESS_COUNTED}
    return {"flag": bool(dropped), "dropped": dropped, "basis": basis}


def completeness_from_log(path: Path) -> list[dict[str, Any]]:
    """Each judged `submit_financials` in a retained tool-calls.jsonl, in order, with its
    completeness: a back-fill for batches run before submits recorded it. Reads only."""
    rows: list[dict[str, Any]] = []
    for text in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(text)
        if entry.get("name") == "submit_financials" and entry.get("status") in (
            "accepted",
            "rejected",
        ):
            rows.append(
                {
                    "submit": len(rows) + 1,
                    "call": entry["call"],
                    "status": entry["status"],
                    "completeness": completeness(entry["arguments"]),
                }
            )
    return rows


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
    deadline_s: float = DEADLINE_S  # the step's wall-clock limit


def send(harness: Harness, cell: Cell, step: StepRun, prepared: Prepared) -> Call | None:
    """Retain the request, reserve, send, settle, retain the scrubbed reply. None: not sent
    (the step's verdict says why). A refused reservation, or any ledger error, raises
    ProviderStop. Attempt ids are `<batch>:<cell>-<step>-call-NN`, so batches sharing a ledger
    cannot collide (hybrid-cp1-1 and -2 wrote the earlier `<cell>-<step>-call-NN`)."""
    number = len(step.calls) + 1
    attempt = attempt_id(harness.batch_directory.name, cell.cell_id, step.step_id, number)
    if prepared.misfit is not None:
        step.verdict, step.verdict_reason = "not sent: misfit", prepared.misfit
        return None
    with (step.directory / f"call-{number:02d}-request.json").open("xb") as stream:
        stream.write(prepared.payload)  # the body only: no header is retained
    ledger = harness.ledgers[cell.provider]
    try:
        ledger.reserve(attempt, prepared.reserve)
    except (CapExceeded, LedgerError) as error:
        raise ProviderStop(f"{attempt} not sent: {error}") from None
    call = Call(
        number, prepared.reserve, prepared.bound, len(prepared.payload), prepared.tool_choice
    )
    step.calls.append(call)
    unsettled = None
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
        try:
            call.settlement = ledger.settle(attempt, cost, reason)
        except LedgerError as error:  # the reservation stays held; the reply is still retained
            unsettled = f"{attempt} not settled, reservation held: {error}"
    kind = call.reply.raw_kind if call.reply is not None else "json"
    response = step.directory / f"call-{number:02d}-response.{kind}"
    if call.reply is not None and call.reply.raw is not None:
        with response.open("xb") as stream:
            stream.write(call.reply.raw)
    else:
        detail = call.transport_error or (call.reply.error_detail if call.reply else None)
        cp0._write(response, {"no_body": detail})
    if unsettled is not None:
        raise ProviderStop(unsettled)
    return call


def attempt_id(batch_id: str, cell_id: str, step_id: str, number: int) -> str:
    return f"{batch_id}:{cell_id}-{step_id}-call-{number:02d}"


def attempt_owner(attempt: str) -> tuple[str | None, str]:
    """(batch, cell) of a CP-1 attempt id; batch None for the earlier unprefixed ids."""
    batch, _, rest = attempt.rpartition(":")
    head = rest.rsplit("-call-", 1)[0]
    for step_id in CP1_STEPS:
        if head.endswith(f"-{step_id}"):
            return batch or None, head[: -len(step_id) - 1]
    return batch or None, head


def run_step(harness: Harness, cell: Cell, step: StepRun, base: Path, ticket: str) -> None:
    """One step's hybrid conversation, bounded by MAX_CALLS calls and the harness's step
    wall-clock limit; each call may use the rest of that limit (no per-call cap)."""
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
            if len(step.calls) >= MAX_CALLS or elapsed >= harness.deadline_s:
                step.verdict = "rejected: limit"
                step.verdict_reason = f"{len(step.calls)} calls, {elapsed:.1f} s"
                break
            timeout = harness.deadline_s - elapsed
            provider = harness.providers[cell.provider]
            prepared = provider.prepare(cell, system, conversation, tools, timeout)
            call = send(harness, cell, step, prepared)
            if call is None:
                break
            _turn(harness, cell, step, call, conversation, (base, ticket))
            timed_out = step.verdict in ("no-response: timeout", "no-response: stream-incomplete")
            if timed_out and harness.clock() - started >= harness.deadline_s:
                step.verdict = "rejected: limit"  # the call's bound was the step's deadline
                step.verdict_reason = (
                    f"deadline of {harness.deadline_s} s reached during call {call.number}"
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
    left = MAX_CALLS - call.number
    if results and 0 < left <= NUDGE_FROM_CALLS_LEFT:  # one line, on the turn's last result
        ident, text = results[-1]
        nudge = call_nudge(left, step.step_id)
        results[-1] = (ident, f"{text}\n{nudge}")
        cp0._append(log, {"call": call.number, "nudge": nudge, "appended_to": ident})
    conversation.extend(provider.tool_results(results))


def call_nudge(left: int, step_id: str) -> str:
    return (
        f"Harness: {left} of {MAX_CALLS} calls remain in this step; "
        f"the step must end with {submit_name(step_id)}."
    )


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
        | ({"completeness": completeness(arguments)} if step.step_id == "financials" else {})
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
    financials = step.step_id == "financials"
    metrics["completeness_drop"] = completeness_drop(step.submits) if financials else None
    metrics["final_payload_completeness"] = completeness(final) if financials and final else None
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
    harness: Harness,
    runs: Sequence[CellRun],
    *,
    seed: int,
    prior: cp0.PriorSpend | None = None,
    summary_name: str = "batch-summary.json",
) -> dict[str, Any]:
    """Run the cells in order. A ProviderStop skips that provider's remaining cells and is
    recorded, never raised; the other provider's cells go on. A cell whose verdict is already
    SKIPPED_BY_USER is listed in the summary and never started."""
    stopped: dict[str, str] = {}
    for run in runs:
        provider = run.cell.provider
        if run.verdict == SKIPPED_BY_USER:
            continue
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
    cp0._write(harness.batch_directory / summary_name, summary)
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
    # Default: CAPS for a new ledger; an existing ledger's opening cap (a given cap must match).
    command.add_argument("--cap-openrouter", type=cp0._money)
    command.add_argument("--cap-anthropic", type=cp0._money)
    command.add_argument("--seed", type=int, help="cell order seed; else drawn and recorded")
    command.add_argument("--cp0-journal", type=Path, default=CP0_JOURNAL)
    command.add_argument("--artifact-root", type=Path, default=cp0.ARTIFACT_ROOT)
    command.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    command.add_argument("--catalog", type=Path, help="saved models JSON; else fetched (public)")
    command.add_argument(
        "--cells",
        type=_cells,
        default=CELLS,
        help="comma-separated cell ids (default: the six of hybrid-cp1-1)",
    )
    command.add_argument(
        "--openrouter-ledger",
        type=Path,
        help="spend OpenRouter cells against this existing ledger (its own cap)",
    )
    command.add_argument(
        "--resume",
        action="store_true",
        help="run --cells of the batch's plan.json not yet started, on its existing ledgers",
    )
    command.add_argument(
        "--skipped-by-user",
        type=_cells,
        default=(),
        help="comma-separated cell ids the user skipped; listed in the summary, never started",
    )
    command.add_argument(
        "--step-seconds",
        type=float,
        default=DEADLINE_S,
        help="each step's wall-clock limit (the brief's 1,200 s by default)",
    )
    command.add_argument(
        "--upstream-from",
        help="measure every step's prompt with retained payloads: PREFIX-<step>-1/output.md",
    )
    return command


def _refuse(reason: str) -> int:
    print(f"refused: {reason}", file=sys.stderr)
    return 2


def _cells(text: str) -> tuple[Cell, ...]:
    known = {cell.cell_id: cell for cell in (*CELLS, *EXTRA_CELLS)}
    chosen = [name.strip() for name in text.split(",") if name.strip()]
    unknown = [name for name in chosen if name not in known]
    if unknown or not chosen or len(set(chosen)) != len(chosen):
        raise argparse.ArgumentTypeError(f"cells must be distinct ids of {sorted(known)}")
    return tuple(known[name] for name in chosen)


@dataclass(frozen=True)
class LedgerPlan:
    path: Path
    cap: Decimal
    headroom: Decimal  # what this batch can still commit against the ceiling
    shared: bool


def _ledger_plans(
    args: argparse.Namespace, providers: Sequence[str], directory: Path
) -> dict[str, LedgerPlan]:
    """A new `<batch>-<provider>.jsonl` per provider (it must not exist), or an existing ledger
    with the cap its first line records: --openrouter-ledger's for OpenRouter, the batch's own
    under --resume. An existing ledger must be one the cumulative ceiling counts: a match of
    `directory.glob("*.jsonl")`, as `cp0.prior_committed` sums them. A --cap-* given for an
    existing ledger must equal that cap. Raises ValueError to refuse."""
    plans = {}
    for name in providers:
        path = _ledger_path(args, name, directory)
        given_cap = args.cap_openrouter if name == "openrouter" else args.cap_anthropic
        if args.resume or (name == "openrouter" and args.openrouter_ledger is not None):
            if not path.is_file():
                raise ValueError(f"ledger {path.name} does not exist")
            if path.resolve() not in {p.resolve() for p in directory.glob("*.jsonl")}:
                raise ValueError(
                    f"ledger {path} is not in {directory}, the ledgers the ceiling counts"
                )
            state = open_ledger(path).state()
            if given_cap is not None and given_cap != state.cap:
                raise ValueError(
                    f"{name} cap {given_cap} differs from {path.name}'s opening cap {state.cap}"
                )
            plans[name] = LedgerPlan(path, state.cap, state.remaining, True)
            continue
        if path.exists():
            raise ValueError(f"{path.name} already exists; use a new --batch-id")
        cap = CAPS[name] if given_cap is None else given_cap
        plans[name] = LedgerPlan(path, cap, cap, False)
    return plans


def _ledger_path(args: argparse.Namespace, provider: str, directory: Path) -> Path:
    given: Path | None = args.openrouter_ledger if provider == "openrouter" else None
    return given or directory / f"{args.batch_id}-{provider}.jsonl"


def _refuse_traces(args: argparse.Namespace, directory: Path, batch_directory: Path) -> None:
    """Raises ValueError when a ledger already holds attempts for this batch and a cell it is
    to run, or a cell to be recorded as skipped left any trace: a step call, or a ledger
    attempt of this batch or an unprefixed one of that cell. (An unprefixed attempt of a cell
    to run belongs to whichever batch has that cell's directory; `_cell_numbers` refuses
    started cells.)"""
    cells: tuple[Cell, ...] = (*args.cells, *args.skipped_by_user)
    owners: dict[str, set[tuple[str | None, str]]] = {}
    for provider in {cell.provider for cell in cells}:
        path = _ledger_path(args, provider, directory)
        attempts = open_ledger(path).state().attempts if path.is_file() else ()
        owners[provider] = {attempt_owner(a.attempt_id) for a in attempts}
    for cell in args.cells:
        if (args.batch_id, cell.cell_id) in owners[cell.provider]:
            name = _ledger_path(args, cell.provider, directory).name
            raise ValueError(f"{name} already holds attempts for {args.batch_id} {cell.cell_id}")
    for cell in args.skipped_by_user:
        held = owners[cell.provider] & {(args.batch_id, cell.cell_id), (None, cell.cell_id)}
        calls = sorted((batch_directory / cell.cell_id).glob("*/call-*-request.json"))
        if held or calls:
            raise ValueError(
                f"{cell.cell_id} cannot be recorded as skipped: {len(calls)} step call(s) "
                f"retained, ledger attempts {'held' if held else 'none'}"
            )


def _cell_numbers(args: argparse.Namespace, batch_directory: Path) -> dict[str, int]:
    """Under --resume, each cell's place in the batch's own plan.json order; for a new batch,
    none (the seeded shuffle numbers it). Raises ValueError to refuse."""
    running = [cell.cell_id for cell in args.cells]
    skipped = [cell.cell_id for cell in args.skipped_by_user]
    if both := sorted(set(running) & set(skipped)):
        raise ValueError(f"both run and skipped: {both}")
    if not args.resume:
        if batch_directory.exists():
            raise ValueError("already has a directory; use a new --batch-id or --resume")
        return {}
    plan = json.loads((batch_directory / "plan.json").read_text(encoding="utf-8"))
    numbers = {str(row["cell_id"]): int(row["order"]) for row in plan["order"]}
    if absent := [name for name in [*running, *skipped] if name not in numbers]:
        raise ValueError(f"not in {args.batch_id}'s plan: {absent}")
    if started := [name for name in running if (batch_directory / name).exists()]:
        raise ValueError(f"already started: {started}; a started cell is never re-run")
    return numbers


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: Transport = urllib_transport,
    stream_transport: StreamTransport = urllib_stream,
) -> int:
    args = parser().parse_args(argv)
    # Attempt ids take the batch directory's name and the batch's ledgers sit beside the others
    # only for a single component (`_refuse_traces` checks the id itself).
    if args.batch_id in ("", ".", "..") or Path(args.batch_id).name != args.batch_id:
        return _refuse(f"--batch-id {args.batch_id!r} must be one path component")
    settings = load_settings(args.settings)
    cells: tuple[Cell, ...] = args.cells
    used = sorted({cell.provider for cell in cells})
    ledgers = args.artifact_root / ".ledgers"
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
    try:
        plans = _ledger_plans(args, used, ledgers)
    except (ValueError, LedgerError) as error:
        return _refuse(str(error))
    ceiling = settings.caps.cumulative_ceiling
    headroom = sum((plan.headroom for plan in plans.values()), Decimal(0))
    if spend.total + headroom > ceiling:
        return _refuse(f"prior ledgers hold {spend.total} USD; with {headroom} more > {ceiling}")
    try:
        numbers = _cell_numbers(args, batch_directory)
        _refuse_traces(args, ledgers, batch_directory)
    except (OSError, ValueError, KeyError, TypeError, LedgerError) as error:
        return _refuse(f"{args.batch_id}: {error}")
    try:
        pack, system, user = cp1_start(args.cp0_journal)
    except (OSError, ValueError, PromptError) as error:
        return _refuse(f"the frozen CP-0 journal cannot start CP-1: {error}")
    models = list(dict.fromkeys(c.model for c in cells if c.provider == "openrouter"))
    candidates: dict[str, PinnedCandidate] = {}
    catalog = None
    if models:
        try:
            catalog = Catalog.from_file(args.catalog) if args.catalog else Catalog.fetch(transport)
            selection = tuple(ModelSelection(model, None) for model in models)
            pool = catalog.pin_selected(args.batch_id, selection)
            candidates = {model: pool.candidate(model) for model in models}
        except CatalogError as error:
            return _refuse(str(error))
    for model, candidate in candidates.items():
        lacking = [p for p in ("tools", "tool_choice") if p not in candidate.supported_parameters]
        if not candidate.eligible or lacking:
            return _refuse(f"{model} ineligible: {candidate.exclusion_reason or lacking}")
    efforts = {}
    for cell in cells:
        if cell.provider == "openrouter":
            decision = candidates[cell.model].effort_for(cell.effort)
            if decision.sent != cell.effort or decision.mapped:  # only the effort asked for
                return _refuse(
                    f"{cell.cell_id}: effort {cell.effort} would be sent as {decision.sent}"
                )
            efforts[cell.cell_id] = decision.to_record()
    keys: dict[str, LoadedKey] = {}
    try:
        if "openrouter" in used:
            keys["openrouter"] = load_key_with_note(
                settings.credential_file, settings.credential_token_index
            )
        if "anthropic" in used:
            keys["anthropic"] = load_anthropic_key(settings.credential_file)
    except CredentialError as error:  # messages hold counts only
        return _refuse(f"credential: {error}")
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**32)
    order = list(cells)
    random.Random(seed).shuffle(order)
    skipped: tuple[Cell, ...] = args.skipped_by_user
    listed = [*order, *skipped]
    numbers = numbers or {cell.cell_id: n for n, cell in enumerate(listed, start=1)}
    listed.sort(key=lambda cell: numbers[cell.cell_id])
    bpt = settings.prompt_bytes_per_token_lower_bound
    providers: dict[str, Provider] = {
        "openrouter": OpenRouter(ChatClient(transport), candidates, bpt),
        "anthropic": Anthropic(stream_transport, bpt),
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
    notes: dict[str, dict[str, object]] = {name: dict(key.note()) for name, key in keys.items()}
    if "anthropic" in notes:
        notes["anthropic"]["rule"] = "the one sk-ant- token among the file's distinct sk- tokens"
    plan = {
        "batch_id": args.batch_id,
        "seed": seed,
        "order": [{"order": numbers[cell.cell_id]} | asdict(cell) for cell in order],
        "skipped_by_user": [cell.cell_id for cell in skipped],
        "resume": {"of": "plan.json"} if args.resume else None,
        "steps": list(CP1_STEPS),
        "cp0_journal": {"path": args.cp0_journal, "pack_sha256": pack.content_hash()},
        "located_pages": cp0.PackTools(pack).located_pages,
        "openrouter": {
            "pinned_candidates": {m: c.to_record() for m, c in candidates.items()},
            "catalog": None
            if catalog is None
            else {"source": catalog.source, "sha256": catalog.sha256},
            "efforts": efforts,
        },
        "anthropic": {
            "url": ANTHROPIC_URL,
            "version": ANTHROPIC_VERSION,
            "prices_usd_per_million": {model: asdict(p) for model, p in PRICES.items()},
            "cost_basis": "computed-from-list-prices",
            "tool_choice": "any first; auto after a 400 naming tool_choice",
            "thinking": {"type": "adaptive"},
            "cache_control": CACHE_CONTROL,
        },
        "harness_rules": {
            "call_limit_nudge": {
                "from_calls_left": NUDGE_FROM_CALLS_LEFT,
                "where": "one line appended to the last tool result of each turn after which "
                "1 to 3 calls remain (first sent with the step's third-last call)",
                "text": call_nudge(NUDGE_FROM_CALLS_LEFT, "<step>"),
            }
        },
        "credential": {"recorded": False, **notes},
        "limits": {
            "max_tokens_per_call": MAX_TOKENS,
            "calls_per_step": MAX_CALLS,
            "wall_clock_s_per_step": args.step_seconds,
            "idle_s_between_stream_bytes": IDLE_S,
            "submits_per_step": MAX_SUBMITS,
        },
        "money": {
            "caps_usd": {name: plan.cap for name, plan in plans.items()},
            "ledgers": {name: asdict(plan) for name, plan in plans.items()},
            "prior_committed_usd": spend.total,
            "prior_worst_case_adjusts": list(spend.worst_case_adjusts),
            "cumulative_ceiling_usd": ceiling,
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
    # A resume writes beside the batch's plan.json, never over it.
    suffix = "-resume-" + "-".join(cell.cell_id for cell in order) if args.resume else ""
    batch_directory.mkdir(parents=True, exist_ok=args.resume)
    cp0._write(batch_directory / f"plan{suffix}.json", plan)
    harness = Harness(
        cp0_journal=args.cp0_journal,
        providers=providers,
        ledgers={name: Ledger(plan.path, plan.cap) for name, plan in plans.items()},
        keys={name: key.key for name, key in keys.items()},
        batch_directory=batch_directory,
        deadline_s=args.step_seconds,
    )
    runs = [
        CellRun(
            cell,
            numbers[cell.cell_id],
            batch_directory / cell.cell_id,
            verdict="not run" if cell in order else SKIPPED_BY_USER,
        )
        for cell in listed
    ]
    summary = run_batch(
        harness, runs, seed=seed, prior=spend, summary_name=f"batch-summary{suffix}.json"
    )
    print(cp0._json(summary), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
