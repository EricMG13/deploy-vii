"""OpenRouter chat client behind an injectable transport. No tools, no network in tests.

Classification is closed: ok, fallback, truncated, http_error, insufficient_credit, timeout.
Unknown usage fields are None with a reason, never zero. Response text that could carry
the key (provider error bodies) is scrubbed before it leaves this module.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from email.message import Message
from pathlib import Path
from typing import IO, Any, Literal, Protocol

from deploy_vii.live.credential import CredentialError, load_key_with_note, redact, scrub_key

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
KEY_URL = "https://openrouter.ai/api/v1/key"
GENERATION_URL = "https://openrouter.ai/api/v1/generation"
GENERATION_ID = re.compile(r"gen-[A-Za-z0-9_-]{1,200}")
KEY_TIMEOUT_SECONDS = 30.0
DEFAULT_TIMEOUT_SECONDS = 600.0
READ_CHUNK_BYTES = 64 * 1024
PROVIDER_DETAIL_CHARS = 500  # the upstream message kept in `error_detail` (task 2.11)
USAGE_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "reasoning_tokens",
    "cached_tokens",
    "cost",
)
Classification = Literal[
    "ok", "fallback", "truncated", "http_error", "insufficient_credit", "timeout"
]


class TransportError(Exception):
    """The request could not complete (connection level). The message never holds the key."""


@dataclass(frozen=True)
class Request:
    url: str
    method: str
    headers: Mapping[str, str] = field(repr=False)
    body: bytes | None = field(default=None, repr=False)
    timeout_s: float = 60.0


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


Transport = Callable[[Request], Response]


@dataclass(frozen=True)
class ChatRequest:
    """The non-secret request: exactly what request.json retains."""

    model: str
    messages: Sequence[Mapping[str, str]]
    max_tokens: int
    response_format: Mapping[str, Any]
    reasoning_effort: str | None  # None: reasoning is switched on without an effort value
    accepted_model_ids: Sequence[str] = ()
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS
    # False: no `reasoning` parameter at all, the provider default applies (`live schema-check`).
    reasoning: bool = True

    def __post_init__(self) -> None:
        if not self.reasoning and self.reasoning_effort is not None:
            raise ValueError("reasoning_effort needs reasoning: a request without it sends none")

    def body(self) -> dict[str, Any]:
        # Routing is pinned to the drawn model: no `models` list, no provider fallbacks,
        # and providers that would ignore a requested parameter are never chosen.
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in self.messages],
            "max_tokens": self.max_tokens,
            "response_format": dict(self.response_format),
            "reasoning": {"enabled": True}
            if self.reasoning_effort is None
            else {"effort": self.reasoning_effort},
            "provider": {"allow_fallbacks": False, "require_parameters": True},
        }
        if not self.reasoning:
            del body["reasoning"]
        return body


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    reasoning_tokens: int | None
    cached_tokens: int | None
    cost: Decimal | None
    missing: Mapping[str, str]


@dataclass(frozen=True)
class ChatResult:
    classification: Classification
    http_status: int | None
    raw: bytes | None
    redacted: bool
    content: str | None
    refusal: str | None
    finish_reason: str | None
    served_model: str | None
    served_provider: str | None
    identity_verified: bool
    provider_request_id: str | None
    usage: Usage
    latency_s: float
    error_detail: str | None
    # OpenRouter's `error.metadata.provider_error_code` of a non-2xx reply, when it is text
    # (probe-5b OpenAI: "invalid_json_schema"); None otherwise.
    provider_error_code: str | None = None


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _nested(usage: Mapping[str, Any], group: str, name: str) -> object:
    inner = usage.get(group)
    return inner.get(name) if isinstance(inner, Mapping) else None


def parse_usage(usage: object) -> Usage:
    """Read provider usage; every unknown value is None with a reason in `missing`."""
    if not isinstance(usage, Mapping):
        reason = "usage object absent from the response"
        return Usage(None, None, None, None, None, None, {name: reason for name in USAGE_FIELDS})
    raw: dict[str, object] = {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "reasoning_tokens": _nested(usage, "completion_tokens_details", "reasoning_tokens"),
        "cached_tokens": _nested(usage, "prompt_tokens_details", "cached_tokens"),
    }
    missing: dict[str, str] = {}
    counts: dict[str, int | None] = {}
    for name, value in raw.items():
        counts[name] = _count(value)
        if counts[name] is None:
            missing[name] = (
                "field absent from usage"
                if value is None
                else f"{name} is not a non-negative integer"
            )
    cost: Decimal | None = None
    value = usage.get("cost")
    if isinstance(value, int | Decimal) and not isinstance(value, bool) and value >= 0:
        cost = Decimal(value)
    else:
        missing["cost"] = (
            "field absent from usage" if value is None else "cost is not a non-negative number"
        )
    return Usage(
        prompt_tokens=counts["prompt_tokens"],
        completion_tokens=counts["completion_tokens"],
        total_tokens=counts["total_tokens"],
        reasoning_tokens=counts["reasoning_tokens"],
        cached_tokens=counts["cached_tokens"],
        cost=cost,
        missing=missing,
    )


def _no_response(
    classification: Classification, detail: str, latency: float, status: int | None = None
) -> ChatResult:
    return ChatResult(
        classification=classification,
        http_status=status,
        raw=None,
        redacted=False,
        content=None,
        refusal=None,
        finish_reason=None,
        served_model=None,
        served_provider=None,
        identity_verified=False,
        provider_request_id=None,
        usage=parse_usage(None),
        latency_s=latency,
        error_detail=detail,
    )


@dataclass(frozen=True)
class KeyStatus:
    """A `GET /api/v1/key` reply and the key note of the call that fetched it (counts only)."""

    response: Response
    key_note: dict[str, int]


class ChatClient:
    def __init__(
        self,
        transport: Transport | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        key_path: Path | None = None,
        key_index: int | None = None,
    ) -> None:
        if key_path is not None and key_index is None:
            # No default token: `[model_tests].credential_token_index` is always passed.
            raise ValueError("a client with key_path needs key_index (credential_token_index)")
        self._transport = transport or urllib_transport
        self._clock = clock
        # Only the DC-7 file path is kept; the key itself is read per call and never stored.
        self._key_path = key_path
        self._key_index = key_index  # `[model_tests].credential_token_index`; no fallback

    def fetch_key_status(self) -> KeyStatus:
        """`GET /api/v1/key` with the key read from the client's credential file for this call.

        The body is returned with the key scrubbed, with this call's key note (counts only, set
        when the file held several tokens). A connection failure raises TransportError (key
        scrubbed); an HTTP error status is returned for the caller to interpret."""
        return KeyStatus(*self._get(KEY_URL, "key status"))

    def fetch_generation(self, generation_id: str) -> Response:
        """`GET /api/v1/generation?id=<gen>`: the provider's record (and cost) of one generation.

        Same key handling as `fetch_key_status`: read from the credential file for this call
        only. The id must look like a generation id; anything else is refused unsent."""
        if not GENERATION_ID.fullmatch(generation_id):
            raise ValueError("not a generation id (expected gen-<letters, digits, '-', '_'>)")
        url = f"{GENERATION_URL}?{urllib.parse.urlencode({'id': generation_id})}"
        return self._get(url, "generation lookup")[0]

    def _get(self, url: str, what: str) -> tuple[Response, dict[str, int]]:
        if self._key_path is None or self._key_index is None:
            raise CredentialError("this client has no credential file; build it with key_path")
        loaded = load_key_with_note(self._key_path, self._key_index)
        key = loaded.key
        note = loaded.note() if loaded.tokens_found > 1 else {}
        http = Request(
            url=url,
            method="GET",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout_s=KEY_TIMEOUT_SECONDS,
        )
        try:
            response = self._transport(http)
        except TimeoutError:
            raise TransportError(f"{what} request timed out") from None
        except Exception as error:  # noqa: BLE001 - converted to TransportError, never swallowed
            raise TransportError(redact(f"{type(error).__name__}: {error}", key)) from None
        text = response.body.decode("utf-8", errors="replace")
        return Response(response.status, scrub_key(text, key).encode()), note

    def complete(self, request: ChatRequest, *, key: str) -> ChatResult:
        """One chat completion. The key is used for the header and for scrubbing only."""
        http = Request(
            url=CHAT_URL,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body=json.dumps(request.body(), sort_keys=True).encode(),
            timeout_s=request.timeout_s,
        )
        started = self._clock()
        try:
            response = self._transport(http)
        except TimeoutError:
            return _no_response("timeout", "request timed out", self._clock() - started)
        except Exception as error:  # noqa: BLE001 - converted to TransportError, never swallowed
            # An injected transport may embed request headers in its message, so every failure
            # leaves this method as a TransportError with the key scrubbed.
            message = redact(f"{type(error).__name__}: {error}", key)
            raise TransportError(message) from None
        return _classify(request, response, key, self._clock() - started)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _body_error_class(error: Mapping[str, Any]) -> Classification:
    """The class of an `error` object that arrived inside a 2xx body (OpenRouter mid-call)."""
    code = error.get("code")
    error_type = _text(_as_dict(error.get("metadata")).get("error_type")) or ""
    if code in (504, 408) or "timeout" in error_type.lower():
        return "timeout"
    return "insufficient_credit" if code == 402 else "http_error"


def _classify(request: ChatRequest, response: Response, key: str, latency: float) -> ChatResult:
    """Scrub the body, then classify it; an error body never becomes an `ok` result.

    OpenRouter commits a 200 before inference and pads a non-streaming call with whitespace, so
    a failure mid-call arrives as a 200 whose body holds an `error` object (probe-2: DeepSeek
    `{"id": "gen-...", "error": {"code": 504, ...}}` after ~1.1 KB of whitespace). Such a body is
    classified by its code; no retry happens here (a retry is a new, separately reserved
    attempt). The body `id` is kept as `provider_request_id` in every branch."""
    text = response.body.decode("utf-8", errors="replace")
    # Only the key itself is removed: the body is evidence and the model's answer, kept verbatim.
    scrubbed = scrub_key(text, key)
    redacted = scrubbed != text
    raw = scrubbed.encode() if redacted else response.body
    try:
        document, readable = _as_dict(json.loads(scrubbed.strip(), parse_float=Decimal)), True
    except ValueError:
        document, readable = {}, False
    failure = replace(
        _no_response("http_error", f"HTTP {response.status}", latency, response.status),
        raw=raw,
        redacted=redacted,
        provider_request_id=_text(document.get("id")),
    )
    error = _as_dict(document.get("error"))
    message = redact(str(error.get("message", "")), key)
    success = 200 <= response.status < 300
    if success and not readable:
        return _failed(failure, "empty or non-JSON 200 body")
    if success and error:
        code = error.get("code")
        detail = f"HTTP {response.status} body error {'unknown' if code is None else code}"
        return replace(
            failure,
            classification=_body_error_class(error),
            error_detail=f"{detail}: {message}" if message else detail,
        )
    if response.status == 402 or error.get("code") == 402:
        return _failed(failure, message or None, "insufficient_credit")
    if not success:
        provider = _provider_detail(error, key)
        explained = "; ".join(part for part in (message, provider) if part) or None
        return replace(
            _failed(failure, explained),
            provider_error_code=_text(_as_dict(error.get("metadata")).get("provider_error_code")),
        )
    choices = document.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    if not isinstance(choice, dict):
        return _failed(failure, "no choices in the response")
    answer = _answer(request, response.status, document, choice, raw, redacted, latency)
    choice_error = choice.get("error")
    if choice_error is not None or answer.finish_reason == "error":
        # Probe-4 (DeepSeek 9d68b734): the provider's failure inside `choices[0]` of a 200, with
        # `finish_reason` "error" and null content. Never `ok`; an error object is classed like
        # the same object at the top level (402 reaches DC-8, 504/408/timeout is `timeout`), any
        # other value is `http_error`. The usage stays as reported, so a `usage.cost` settles the
        # attempt (the runner holds the reservation when there is none).
        return replace(
            answer,
            classification=_body_error_class(choice_error)
            if isinstance(choice_error, dict) and choice_error
            else "http_error",
            content=None,
            error_detail=_choice_error_detail(choice_error, response.status, key),
        )
    return answer


def _provider_detail(error: Mapping[str, Any], key: str) -> str | None:
    """The upstream provider's own message from an OpenRouter error's `metadata.raw` (key
    scrubbed), prefixed with `provider_name` and `provider_error_code` where they are text.

    OpenRouter's `message` is generic ("Provider returned error"); the reason (probe-5b: "Invalid
    schema for response_format 'source_context' ...") is only inside `raw`. A raw JSON text gives
    its `error.message` (or `message`); any other raw text is kept as it is, up to
    `PROVIDER_DETAIL_CHARS` characters (an HTML error page must not flood reports)."""
    metadata = _as_dict(error.get("metadata"))
    raw = _text(metadata.get("raw"))
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    try:
        document = _as_dict(json.loads(text))
    except ValueError:
        document = {}
    inner = _as_dict(document.get("error")) or document
    text = _text(inner.get("message")) or text
    if len(text) > PROVIDER_DETAIL_CHARS:
        text = f"{text[:PROVIDER_DETAIL_CHARS]} [truncated from {len(text)} chars]"
    label = " ".join(
        name
        for name in (
            _text(metadata.get("provider_name")),
            _text(metadata.get("provider_error_code")),
        )
        if name
    )
    return redact(f"{label}: {text}" if label else text, key)


def _choice_error_detail(error: object, status: int, key: str) -> str:
    """`HTTP <code>: <message>` from a `choices[0].error` object (key scrubbed). Any other
    present `error` value still fails the result closed, with a fixed detail."""
    if error is None:
        return f"HTTP {status}: choices[0] finish_reason error without an error object"
    if not isinstance(error, dict) or not error:
        return f"HTTP {status}: choices[0] error that is not an error object"
    code = error.get("code")
    message = redact(str(error.get("message", "")), key)
    detail = f"HTTP {'unknown' if code is None else code}"
    return f"{detail}: {message}" if message else detail


def _answer(
    request: ChatRequest,
    status: int,
    document: dict[str, Any],
    choice: dict[str, Any],
    raw: bytes,
    redacted: bool,
    latency: float,
) -> ChatResult:
    message = _as_dict(choice.get("message"))
    served_model = _text(document.get("model"))
    provider = document.get("provider")
    served_provider = _text(provider) or _text(_as_dict(provider).get("name"))
    accepted = {request.model, *request.accepted_model_ids}
    # Only the served model decides `fallback`. The provider is never pinned in the request
    # (allow_fallbacks is false), so it is recorded for every attempt but not compared.
    mismatch = served_model is not None and served_model not in accepted
    finish = _text(choice.get("finish_reason"))
    classification: Classification = (
        "fallback" if mismatch else "truncated" if finish == "length" else "ok"
    )
    return ChatResult(
        classification=classification,
        http_status=status,
        raw=raw,
        redacted=redacted,
        content=_text(message.get("content")),
        refusal=_text(message.get("refusal")),
        finish_reason=finish,
        served_model=served_model,
        served_provider=served_provider,
        identity_verified=served_model in accepted,
        provider_request_id=_text(document.get("id")),
        usage=parse_usage(document.get("usage")),
        latency_s=latency,
        error_detail=None,
    )


def _failed(
    base: ChatResult, detail: str | None, classification: Classification | None = None
) -> ChatResult:
    """Return a copy of the failure shell with an explanation and optionally a new class."""
    return replace(
        base,
        classification=classification or base.classification,
        error_detail=f"{base.error_detail}: {detail}" if detail else base.error_detail,
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would resend the Authorization header to the target."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        return None


class _Reply(Protocol):
    def read1(self, size: int = -1, /) -> bytes: ...


def _read_within(reply: _Reply, deadline: float, timeout_s: float) -> bytes:
    """The whole body, or TimeoutError at the first read that returns after `deadline`.

    `read1` returns whatever has arrived (at most one socket read), so OpenRouter's whitespace
    keep-alive cannot hold one read open; a socket that sends nothing still ends at the
    per-read timeout. A body whose last bytes arrive after the deadline is a timeout too."""
    chunks: list[bytes] = []
    while chunk := reply.read1(READ_CHUNK_BYTES):
        chunks.append(chunk)
        if time.monotonic() > deadline:
            raise TimeoutError(f"wall-clock deadline of {timeout_s} s exceeded reading the body")
    return b"".join(chunks)


def urllib_transport(request: Request) -> Response:
    """Default transport: https only, no redirects; HTTP error statuses are returned, not raised.

    `timeout_s` bounds the whole call by the wall clock (task 2.10): the deadline is fixed
    before the connection opens and checked after every body read, because urllib's timeout
    applies to each socket operation and keep-alive padding resets it (probe-4: 1,029 s against
    600). Each socket operation is still bounded by `timeout_s`, so a silent connection ends
    there; the overrun past the deadline is at most one such operation. An expiry raises
    TimeoutError, which the client classifies `timeout`."""
    if not request.url.startswith("https://"):
        raise TransportError("only https endpoints are permitted")
    http = urllib.request.Request(
        request.url, data=request.body, headers=dict(request.headers), method=request.method
    )
    opener = urllib.request.build_opener(_NoRedirect())
    deadline = time.monotonic() + request.timeout_s
    try:
        with opener.open(http, timeout=request.timeout_s) as reply:
            return Response(
                status=reply.status, body=_read_within(reply, deadline, request.timeout_s)
            )
    except urllib.error.HTTPError as error:
        with error:
            return Response(status=error.code, body=error.read())
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise TimeoutError("request timed out") from None
        raise TransportError(f"network error: {type(error.reason).__name__}") from None
