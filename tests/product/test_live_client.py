"""Chat client: request shape, classification, usage parsing, redaction, default transport."""

import hashlib
import io
import json
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from decimal import Decimal
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from deploy_vii.live.client import (
    CHAT_URL,
    GENERATION_URL,
    ChatClient,
    ChatRequest,
    ChatResult,
    Request,
    Response,
    TransportError,
    _NoRedirect,
    parse_usage,
    urllib_transport,
)
from tests.product.live_support import FAKE_KEY, FakeTransport, chat_body, make_rtf_key, ok

MESSAGES = ({"role": "system", "content": "contract"}, {"role": "user", "content": "data"})
FORMAT = {"type": "json_schema", "json_schema": {"name": "s", "strict": True, "schema": {}}}


def make_request(**changes: object) -> ChatRequest:
    values: dict[str, Any] = {
        "model": "openai/gpt-6-luna",
        "messages": MESSAGES,
        "max_tokens": 2000,
        "response_format": FORMAT,
        "reasoning_effort": "high",
        "accepted_model_ids": ("openai/gpt-6-luna", "openai/gpt-6-luna-20260922"),
    }
    values.update(changes)
    return ChatRequest(**values)


def test_no_effort_switches_reasoning_on_without_an_effort_value() -> None:
    body = make_request(reasoning_effort=None).body()
    assert body["reasoning"] == {"enabled": True}


def test_a_request_without_reasoning_sends_no_reasoning_parameter() -> None:
    """`live schema-check` (task 2.11): the provider default applies, nothing is asked for."""
    body = make_request(reasoning_effort=None, reasoning=False).body()
    assert "reasoning" not in body
    assert body["provider"] == {"allow_fallbacks": False, "require_parameters": True}
    with pytest.raises(ValueError, match="reasoning_effort needs reasoning"):
        make_request(reasoning_effort="high", reasoning=False)


def test_request_pins_routing_and_grants_no_tools() -> None:
    body = make_request().body()
    assert body["provider"] == {"allow_fallbacks": False, "require_parameters": True}
    assert body["reasoning"] == {"effort": "high"}
    assert body["max_tokens"] == 2000 and body["response_format"] == FORMAT
    assert body["messages"] == list(MESSAGES) and body["model"] == "openai/gpt-6-luna"
    assert not {"tools", "tool_choice", "models", "temperature", "stream"} & set(body)
    assert FAKE_KEY not in json.dumps(body)


def test_key_travels_only_in_the_authorization_header() -> None:
    transport = FakeTransport(ok("{}"))
    ChatClient(transport).complete(make_request(), key=FAKE_KEY)
    sent = transport.requests[0]
    assert sent.url == CHAT_URL and sent.method == "POST"
    assert sent.headers["Authorization"] == "Bearer " + FAKE_KEY
    assert FAKE_KEY not in (sent.body or b"").decode()
    assert FAKE_KEY not in repr(sent) and "Authorization" not in repr(sent)
    assert sent.timeout_s == 600.0


def test_ok_result_carries_content_usage_identity_and_latency() -> None:
    ticks = iter([10.0, 12.5])
    client = ChatClient(FakeTransport(ok('{"a":1}')), clock=lambda: next(ticks))
    result = client.complete(make_request(), key=FAKE_KEY)
    assert result.classification == "ok" and result.http_status == 200
    assert result.content == '{"a":1}' and result.finish_reason == "stop"
    assert result.served_model == "openai/gpt-6-luna" and result.served_provider == "OpenAI"
    assert result.identity_verified and result.provider_request_id == "gen-test-0001"
    assert result.latency_s == 2.5
    usage = result.usage
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (1000, 400, 1400)
    assert (usage.reasoning_tokens, usage.cached_tokens) == (250, 0)
    assert usage.cost == Decimal("0.00033") and usage.missing == {}
    assert json.loads(result.raw)["model"] == "openai/gpt-6-luna"


def test_fallback_model_is_classified_not_hidden() -> None:
    other = chat_body('{"x":1}', model="anthropic/some-other-model", provider="Elsewhere")
    result = ChatClient(FakeTransport(Response(200, other))).complete(make_request(), key=FAKE_KEY)
    assert result.classification == "fallback"
    assert result.served_model == "anthropic/some-other-model"
    assert result.served_provider == "Elsewhere"
    assert result.content == '{"x":1}'  # retained, never discarded
    # The catalog's canonical slug is the same model, not a fallback.
    canonical = chat_body("{}", model="openai/gpt-6-luna-20260922")
    same = ChatClient(FakeTransport(Response(200, canonical))).complete(
        make_request(), key=FAKE_KEY
    )
    assert same.classification == "ok"
    # The provider is recorded but never compared: a different provider name for the same
    # model is `ok` (allow_fallbacks is false, so drift is reported, not classified).
    moved = ChatClient(FakeTransport(ok("{}", provider="Other"))).complete(
        make_request(), key=FAKE_KEY
    )
    assert moved.classification == "ok" and moved.served_provider == "Other"
    assert not hasattr(make_request(), "expected_provider")
    # An absent model is flagged unverified.
    nameless = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})
    unverified = ChatClient(FakeTransport(Response(200, nameless.encode())))
    result = unverified.complete(make_request(), key=FAKE_KEY)
    assert result.classification == "ok" and not result.identity_verified
    assert result.served_model is None


def test_truncated_and_refusal_results() -> None:
    cut = ChatClient(FakeTransport(ok('{"partial": [1, 2', finish_reason="length")))
    result = cut.complete(make_request(), key=FAKE_KEY)
    assert result.classification == "truncated" and result.content == '{"partial": [1, 2'
    refusal = {
        "model": "openai/gpt-6-luna",
        "choices": [{"finish_reason": "stop", "message": {"content": None, "refusal": "no"}}],
    }
    refused = ChatClient(FakeTransport(Response(200, json.dumps(refusal).encode())))
    result = refused.complete(make_request(), key=FAKE_KEY)
    assert result.classification == "ok" and result.content is None and result.refusal == "no"


@pytest.mark.parametrize(
    "status, body, classification, detail",
    [
        (
            402,
            b'{"error":{"message":"Insufficient credits","code":402}}',
            "insufficient_credit",
            "",
        ),
        (429, b'{"error":{"message":"slow down"}}', "http_error", "slow down"),
        (503, b"<html>down</html>", "http_error", "HTTP 503"),
        (402, b"Payment Required (plain text)", "insufficient_credit", ""),
        (402, b'{"detail":"no body error key"}', "insufficient_credit", ""),
        (301, b'{"moved":true}', "http_error", "HTTP 301"),
        (200, b"not json at all", "http_error", "empty or non-JSON 200 body"),
        (200, b'{"error":{"message":"upstream blew up","code":502}}', "http_error", "upstream"),
        (200, b'{"error":{"message":"credits","code":402}}', "insufficient_credit", ""),
        (200, b'{"no_choices":true}', "http_error", "no choices"),
        (200, b'{"model":"openai/gpt-6-luna","choices":[]}', "http_error", "no choices"),
    ],
)
def test_error_classes(status: int, body: bytes, classification: str, detail: str) -> None:
    result = ChatClient(FakeTransport(Response(status, body))).complete(
        make_request(), key=FAKE_KEY
    )
    assert result.classification == classification
    assert detail in (result.error_detail or "")
    assert result.content is None


def test_timeout_is_a_classified_result_without_response() -> None:
    result = ChatClient(FakeTransport(TimeoutError("deadline"))).complete(
        make_request(), key=FAKE_KEY
    )
    assert result.classification == "timeout" and result.raw is None
    assert result.http_status is None and result.error_detail == "request timed out"
    assert result.usage.cost is None and "cost" in result.usage.missing


def test_missing_usage_is_null_with_reason() -> None:
    absent = ChatClient(FakeTransport(ok("{}", usage=False))).complete(make_request(), key=FAKE_KEY)
    usage = absent.usage
    assert usage.cost is None and usage.prompt_tokens is None and usage.reasoning_tokens is None
    assert usage.missing["cost"] == "usage object absent from the response"
    assert set(usage.missing) == {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "reasoning_tokens",
        "cached_tokens",
        "cost",
    }
    partial = parse_usage({"prompt_tokens": 7, "cost": "oops", "completion_tokens": True})
    assert partial.prompt_tokens == 7 and partial.cost is None
    assert partial.missing["cost"] == "cost is not a non-negative number"
    assert partial.missing["completion_tokens"] == "completion_tokens is not a non-negative integer"
    assert partial.missing["total_tokens"] == "field absent from usage"
    assert parse_usage({"cost": 0}).cost == Decimal(0)
    assert parse_usage({"cost": -1}).cost is None
    assert parse_usage("not a mapping").missing["cost"] == "usage object absent from the response"


def test_transport_error_text_is_scrubbed_of_the_key() -> None:
    boom = TransportError(f"connection reset while sending Authorization: Bearer {FAKE_KEY}")
    client = ChatClient(FakeTransport(boom))
    with pytest.raises(TransportError) as raised:
        client.complete(make_request(), key=FAKE_KEY)
    text = "".join(traceback.format_exception(raised.value)) + str(raised.value)
    assert "TESTONLY" not in text and "[REDACTED]" in text
    # Foreign exception types are converted too (their text may embed request headers).
    foreign = RuntimeError(f"headers were {{'Authorization': 'Bearer {FAKE_KEY}'}}")
    with pytest.raises(TransportError) as converted:
        ChatClient(FakeTransport(foreign)).complete(make_request(), key=FAKE_KEY)
    text = "".join(traceback.format_exception(converted.value)) + repr(converted.value)
    assert "TESTONLY" not in text and "RuntimeError" in text


def test_error_bodies_are_scrubbed_before_retention() -> None:
    body = json.dumps({"error": {"message": f"bad key {FAKE_KEY}"}}).encode()
    result = ChatClient(FakeTransport(Response(401, body))).complete(make_request(), key=FAKE_KEY)
    assert result.raw is not None and b"TESTONLY" not in result.raw
    assert "TESTONLY" not in (result.error_detail or "") and result.redacted


def test_model_output_that_looks_like_a_header_is_kept_verbatim() -> None:
    prose = "Authorization: the board approved the notes"
    result = ChatClient(FakeTransport(ok(prose))).complete(make_request(), key=FAKE_KEY)
    assert result.content == prose and not result.redacted
    assert prose.encode() in (result.raw or b"")
    # The same reply carrying the key is scrubbed and flagged.
    leaked = ChatClient(FakeTransport(ok(f"{prose} {FAKE_KEY}"))).complete(
        make_request(), key=FAKE_KEY
    )
    assert leaked.content == f"{prose} [REDACTED]" and leaked.redacted


def test_words_containing_the_key_prefix_survive_in_model_output_but_a_real_key_does_not() -> None:
    prose = "risk-or-reward, task-or-derived and disk-or-network"
    result = ChatClient(FakeTransport(ok(prose))).complete(make_request(), key=FAKE_KEY)
    assert result.content == prose and not result.redacted
    leaked = ChatClient(FakeTransport(ok(f"{prose} {FAKE_KEY}"))).complete(
        make_request(), key=FAKE_KEY
    )
    assert leaked.content == f"{prose} [REDACTED]" and leaked.redacted


class FakeReply(io.BytesIO):
    status = 200

    def __enter__(self) -> "FakeReply":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def install(monkeypatch: pytest.MonkeyPatch, opener_open: Callable[..., Any]) -> None:
    """Route urllib_transport through a fake opener; record the handlers it was built with."""

    class FakeOpener:
        def open(self, http: urllib.request.Request, timeout: float) -> io.BytesIO:
            reply: io.BytesIO = opener_open(http, timeout)
            return reply

    def build_opener(*handlers: object) -> FakeOpener:
        assert len(handlers) == 1 and isinstance(handlers[0], _NoRedirect)
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)


def test_default_transport_never_follows_redirects() -> None:
    redirect = _NoRedirect()
    http = urllib.request.Request(CHAT_URL, headers={"Authorization": "Bearer x"})
    result = redirect.redirect_request(
        http, io.BytesIO(), 307, "Temporary Redirect", Message(), "https://elsewhere.test/"
    )
    assert result is None  # urllib then raises HTTPError(307), which becomes http_error


def test_default_transport_maps_urllib_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[urllib.request.Request] = []

    def urlopen(http: urllib.request.Request, timeout: float) -> FakeReply:
        seen.append(http)
        assert timeout == 7.0
        return FakeReply(b'{"ok":true}')

    install(monkeypatch, urlopen)
    request = Request(
        url=CHAT_URL,
        method="POST",
        headers={"Authorization": "Bearer x"},
        body=b"{}",
        timeout_s=7.0,
    )
    assert urllib_transport(request) == Response(200, b'{"ok":true}')
    assert seen[0].get_header("Authorization") == "Bearer x" and seen[0].data == b"{}"

    def http_error(http: object, timeout: float) -> None:
        raise urllib.error.HTTPError(
            CHAT_URL, 402, "Payment Required", Message(), io.BytesIO(b"credit")
        )

    install(monkeypatch, http_error)
    assert urllib_transport(request) == Response(402, b"credit")

    def timed_out(http: object, timeout: float) -> None:
        raise urllib.error.URLError(TimeoutError("slow"))

    install(monkeypatch, timed_out)
    with pytest.raises(TimeoutError):
        urllib_transport(request)

    def refused(http: object, timeout: float) -> None:
        raise urllib.error.URLError(ConnectionRefusedError(f"refused {FAKE_KEY}"))

    install(monkeypatch, refused)
    with pytest.raises(TransportError) as raised:
        urllib_transport(request)
    assert "TESTONLY" not in str(raised.value) and "ConnectionRefusedError" in str(raised.value)

    with pytest.raises(TransportError, match="https"):
        urllib_transport(Request(url="http://example.test/", method="GET", headers={}))
    with pytest.raises(TransportError, match="https"):
        urllib_transport(Request(url="file:///etc/passwd", method="GET", headers={}))


# --- 2.7a: errors reported inside a 200 body (probe-2 fixtures) ----------------------------

PROBE_FIXTURES = Path(__file__).parent / "fixtures" / "live"
DEEPSEEK_BODIES = sorted(PROBE_FIXTURES.glob("deepseek-504-in-200-*.json"))


def fixture_response(path: Path) -> tuple[Response, dict[str, Any]]:
    fixture: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return Response(fixture["http_status"], fixture["body_text"].encode("utf-8")), fixture


def classify(response: Response) -> ChatResult:
    return ChatClient(FakeTransport(response)).complete(make_request(), key=FAKE_KEY)


@pytest.mark.parametrize("path", DEEPSEEK_BODIES, ids=lambda p: p.stem)
def test_probe2_upstream_timeout_inside_a_200_is_a_timeout_with_its_generation_id(
    path: Path,
) -> None:
    response, fixture = fixture_response(path)
    assert hashlib.sha256(response.body).hexdigest() == fixture["body_sha256"]
    assert response.body[:1].isspace() and len(response.body) <= 2048  # keep-alive padding
    generation = json.loads(response.body)["id"]
    result = classify(response)
    assert result.classification == "timeout" and result.http_status == 200
    assert result.error_detail == "HTTP 200 body error 504: A Timeout Occurred"
    assert result.provider_request_id == generation and generation.startswith("gen-")
    assert result.content is None and result.raw == response.body  # evidence kept verbatim
    assert result.usage.cost is None and "cost" in result.usage.missing


def test_probe2_luna_schema_refusal_stays_an_http_error() -> None:
    response, _ = fixture_response(PROBE_FIXTURES / "luna-400-invalid-json-schema.json")
    result = classify(response)
    assert result.classification == "http_error" and result.http_status == 400
    assert result.error_detail == (
        "HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for "
        "response_format 'source_readiness': In context=(), 'required' is required to be "
        "supplied and to be an array including every key in properties. Missing 'limitation'."
    )
    assert result.provider_request_id is None  # the body carries no generation id
    assert b"invalid_json_schema" in (result.raw or b"")


def test_probe5b_sol_source_context_refusal_names_the_providers_own_message() -> None:
    """Task 2.11: the provider's raw message (inside `metadata.raw`) reaches `error_detail`,
    which is what `live schema-check` reports per (model, step)."""
    path = PROBE_FIXTURES / "sol-400-invalid-json-schema-source-context.json"
    response, fixture = fixture_response(path)
    assert fixture["http_status"] == 400 and "user_REDACTED" in fixture["body_text"]
    result = classify(response)
    assert result.classification == "http_error" and result.http_status == 400
    assert result.error_detail == (
        "HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for "
        "response_format 'source_context'. Please ensure it is a valid JSON Schema."
    )
    assert result.provider_error_code == "invalid_json_schema"


def test_a_long_provider_message_is_capped_and_says_so() -> None:
    raw = "x" * 2000
    body = json.dumps({"error": {"code": 400, "message": "m", "metadata": {"raw": raw}}})
    result = classify(Response(400, body.encode()))
    assert result.error_detail == "HTTP 400: m; " + "x" * 500 + " [truncated from 2000 chars]"
    assert result.provider_error_code is None


@pytest.mark.parametrize(
    "metadata, detail",
    [
        ({"raw": "upstream said no"}, "HTTP 400: refused; upstream said no"),
        ({"raw": '{"message": "flat"}'}, "HTTP 400: refused; flat"),
        ({"raw": '{"error": {"message": 3}}'}, 'HTTP 400: refused; {"error": {"message": 3}}'),
        ({"provider_name": "P", "raw": "  "}, "HTTP 400: refused"),
        ({"provider_name": "P"}, "HTTP 400: refused"),
        ({"raw": f"leak {FAKE_KEY}"}, "HTTP 400: refused; leak [REDACTED]"),
        ("not an object", "HTTP 400: refused"),
    ],
    ids=["text", "flat-json", "non-text-message", "blank", "no-raw", "key", "bad-metadata"],
)
def test_the_provider_detail_is_taken_only_from_a_raw_text_and_scrubbed(
    metadata: object, detail: str
) -> None:
    body = json.dumps({"error": {"code": 400, "message": "refused", "metadata": metadata}})
    result = classify(Response(400, body.encode()))
    assert result.classification == "http_error" and result.error_detail == detail


@pytest.mark.parametrize(
    "error, classification, detail",
    [
        ({"code": 408, "message": "slow"}, "timeout", "HTTP 200 body error 408: slow"),
        (
            {"code": 502, "message": "x", "metadata": {"error_type": "provider_timeout"}},
            "timeout",
            "HTTP 200 body error 502: x",
        ),
        ({"code": 402, "message": "credits"}, "insufficient_credit", "HTTP 200 body error 402"),
        ({"code": 502, "message": "gone"}, "http_error", "HTTP 200 body error 502: gone"),
        ({"code": 429, "message": "busy"}, "http_error", "HTTP 200 body error 429: busy"),
        ({"message": "no code"}, "http_error", "HTTP 200 body error unknown: no code"),
        ({"code": 500, "message": f"leak {FAKE_KEY}"}, "http_error", "[REDACTED]"),
    ],
)
def test_errors_inside_a_200_body_are_classified_by_their_code(
    error: dict[str, object], classification: str, detail: str
) -> None:
    body = json.dumps({"id": "gen-body-1", "error": error}).encode()
    result = classify(Response(200, body))
    assert result.classification == classification
    assert detail in (result.error_detail or "") and "TESTONLY" not in (result.error_detail or "")
    assert result.provider_request_id == "gen-body-1" and result.content is None


def test_an_error_beside_choice_content_still_fails_closed() -> None:
    body = json.loads(chat_body('{"a":1}'))
    body["error"] = {"code": 504, "message": "late", "metadata": {"error_type": "timeout"}}
    result = classify(Response(200, json.dumps(body).encode()))
    assert result.classification == "timeout" and result.content is None
    assert result.provider_request_id == "gen-test-0001"


@pytest.mark.parametrize("body", [b"", b"   \n  \n", b"\n\n<html>gateway</html>"])
def test_an_empty_or_non_json_200_body_is_an_http_error_never_ok(body: bytes) -> None:
    result = classify(Response(200, body))
    assert result.classification == "http_error" and result.content is None
    assert result.error_detail == "HTTP 200: empty or non-JSON 200 body"
    assert result.raw == body and result.provider_request_id is None


def test_padded_success_body_is_still_ok_and_carries_its_id() -> None:
    result = classify(Response(200, b"\n \n" + chat_body("{}") + b"\n"))
    assert result.classification == "ok" and result.provider_request_id == "gen-test-0001"


def test_generation_lookup_reads_the_key_for_the_call_and_refuses_odd_ids(
    tmp_path: Path,
) -> None:
    key_path = make_rtf_key(tmp_path)
    reply = Response(200, json.dumps({"data": {"cost": 1, "note": FAKE_KEY}}).encode())
    transport = FakeTransport(reply)
    client = ChatClient(transport, key_path=key_path, key_index=1)
    response = client.fetch_generation("gen-1792615216-IeCvDX2rmXpw9DDxWqjP")
    (sent,) = transport.requests
    assert sent.method == "GET" and sent.body is None
    assert sent.url == f"{GENERATION_URL}?id=gen-1792615216-IeCvDX2rmXpw9DDxWqjP"
    assert sent.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert b"TESTONLY" not in response.body  # scrubbed like the key-status body
    for odd in ("gen-../x", "abc", "gen-1&id=gen-2", "gen-"):
        with pytest.raises(ValueError, match="generation id"):
            client.fetch_generation(odd)
    assert len(transport.requests) == 1
    with pytest.raises(TransportError, match="generation lookup request timed out"):
        timing_out = ChatClient(FakeTransport(TimeoutError()), key_path=key_path, key_index=1)
        timing_out.fetch_generation("gen-1")


def test_a_4xx_body_id_is_kept_as_the_provider_request_id() -> None:
    body = json.dumps({"id": "gen-4xx", "error": {"code": 429, "message": "busy"}}).encode()
    result = classify(Response(429, body))
    assert result.classification == "http_error" and result.provider_request_id == "gen-4xx"


def test_a_client_with_a_key_file_needs_the_token_index_and_keeps_no_key_note(
    tmp_path: Path,
) -> None:
    """No default token (settings pass `credential_token_index`), and the key note travels
    with the call that read the key instead of living on the client."""
    key_path = make_rtf_key(tmp_path)
    with pytest.raises(ValueError, match="needs key_index"):
        ChatClient(FakeTransport(), key_path=key_path)
    client = ChatClient(FakeTransport(Response(200, b"{}")), key_path=key_path, key_index=1)
    assert not hasattr(client, "key_note")
    fetched = client.fetch_key_status()
    assert fetched.response.status == 200 and fetched.key_note == {}


# --- 2.10: a provider error inside choices[0] (probe-4, DeepSeek 9d68b734) -----------------


def choice_error_body(
    *, error: dict[str, object] | None = None, finish_reason: str = "error", cost: object = 0
) -> bytes:
    """Synthesised from the shape of probe-4 DeepSeek 9d68b734 (HTTP 200): the provider's 502
    sits in `choices[0].error`, `content` is null and the body is mostly reasoning text. Short
    reasoning; the token counts and the zero `usage.cost` are the recorded ones."""
    choice: dict[str, object] = {
        "index": 0,
        "finish_reason": finish_reason,
        "native_finish_reason": None,
        "message": {
            "role": "assistant",
            "content": None,
            "refusal": None,
            "reasoning": "We need to produce JSON only. Need assess source readiness.",
        },
    }
    if error is not None:
        choice["error"] = error
    usage: dict[str, object] = {
        "prompt_tokens": 214966,
        "completion_tokens": 16000,
        "total_tokens": 230966,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 35064},
        "cost_details": {"upstream_inference_cost": 0.02304762},
    }
    if cost is not None:
        usage["cost"] = cost
    return json.dumps(
        {
            "id": "gen-1792631442-9B519OmgY7sVrcB9XDdI",
            "object": "chat.completion",
            "model": "deepseek/deepseek-v4.1-flash-1017",
            "provider": "OpenInference",
            "choices": [choice],
            "usage": usage,
        }
    ).encode()


UPSTREAM_502 = {
    "code": 502,
    "message": "Upstream error from OpenInference: Internal server error",
    "metadata": {"error_type": "provider_unavailable"},
}


def deepseek_request() -> ChatRequest:
    model = "deepseek/deepseek-v4.1-flash-1017"
    return make_request(model=model, accepted_model_ids=(model,))


def test_a_provider_error_inside_choices_is_an_http_error_never_ok() -> None:
    body = choice_error_body(error=UPSTREAM_502)
    result = ChatClient(FakeTransport(Response(200, body))).complete(
        deepseek_request(), key=FAKE_KEY
    )
    assert result.classification == "http_error" and result.http_status == 200
    assert (
        result.error_detail == "HTTP 502: Upstream error from OpenInference: Internal server error"
    )
    assert result.finish_reason == "error" and result.content is None
    assert result.provider_request_id == "gen-1792631442-9B519OmgY7sVrcB9XDdI"
    assert result.usage.cost == Decimal(0) and result.usage.completion_tokens == 16000
    assert result.raw == body  # the body is evidence, kept verbatim


def test_finish_reason_error_without_an_error_object_is_an_http_error_too() -> None:
    body = choice_error_body()
    result = ChatClient(FakeTransport(Response(200, body))).complete(
        deepseek_request(), key=FAKE_KEY
    )
    assert result.classification == "http_error" and result.content is None
    assert result.error_detail == "HTTP 200: choices[0] finish_reason error without an error object"


@pytest.mark.parametrize(
    ("error", "classification", "detail"),
    [
        ({"code": 402, "message": "credits"}, "insufficient_credit", "HTTP 402: credits"),
        ({"code": 504, "message": "A Timeout Occurred"}, "timeout", "HTTP 504: A Timeout Occurred"),
        ({"code": 408, "message": "slow"}, "timeout", "HTTP 408: slow"),
        (
            {"code": 502, "message": "x", "metadata": {"error_type": "provider_timeout"}},
            "timeout",
            "HTTP 502: x",
        ),
        (UPSTREAM_502, "http_error", f"HTTP 502: {UPSTREAM_502['message']}"),
    ],
)
def test_a_choice_error_object_is_classified_like_a_body_error(
    error: dict[str, object], classification: str, detail: str
) -> None:
    """Whole-lane review: a 402 inside choices[0] must reach DC-8 and a 504/408/timeout must be
    `timeout`, exactly as the same error object at the top level of a 200 body."""
    body = choice_error_body(error=error)
    result = ChatClient(FakeTransport(Response(200, body))).complete(
        deepseek_request(), key=FAKE_KEY
    )
    assert result.classification == classification and result.content is None
    assert result.error_detail == detail


@pytest.mark.parametrize("error", ["boom", ["boom"], {}, 502])
def test_any_present_choice_error_fails_closed_whatever_its_shape(error: object) -> None:
    document = json.loads(choice_error_body(finish_reason="stop"))
    document["choices"][0]["error"] = error
    document["choices"][0]["message"]["content"] = '{"a":1}'
    result = ChatClient(FakeTransport(Response(200, json.dumps(document).encode()))).complete(
        deepseek_request(), key=FAKE_KEY
    )
    assert result.classification == "http_error" and result.content is None
    assert result.error_detail == "HTTP 200: choices[0] error that is not an error object"


def test_a_choice_error_beside_content_still_fails_closed_and_is_scrubbed() -> None:
    document = json.loads(choice_error_body(error={"message": f"leak {FAKE_KEY}"}))
    document["choices"][0]["finish_reason"] = "stop"
    document["choices"][0]["message"]["content"] = '{"a":1}'
    result = ChatClient(FakeTransport(Response(200, json.dumps(document).encode()))).complete(
        deepseek_request(), key=FAKE_KEY
    )
    assert result.classification == "http_error"
    assert result.error_detail == "HTTP unknown: leak [REDACTED]"
    assert "TESTONLY" not in (result.error_detail or "")


# --- 2.10: timeout_s bounds the whole call (probe-4: 1,029 s against timeout_s 600) --------


class TricklingReply:
    """A 200 that sends one keep-alive space every `pause` seconds, `spaces` times, then a
    complete body: each read is far inside any per-read timeout, but the whole body arrives
    long after the call's deadline (as probe-4 DeepSeek ran 1,029 s against timeout_s 600)."""

    status = 200

    def __init__(self, pause: float, spaces: int = 25) -> None:
        self.pause = pause
        self.spaces = spaces
        self.reads = 0
        self.tail = chat_body('{"a":1}')

    def read1(self, size: int = -1) -> bytes:
        self.reads += 1
        if self.reads <= self.spaces:
            time.sleep(self.pause)
            return b" "
        tail, self.tail = self.tail, b""
        return tail

    def read(self, size: int = -1) -> bytes:
        chunks = []
        while chunk := self.read1(size):
            chunks.append(chunk)
        return b"".join(chunks)

    def __enter__(self) -> "TricklingReply":
        return self

    def __exit__(self, *args: object) -> None:
        return None


DEADLINE_S = 0.05


def chat_http(timeout_s: float = DEADLINE_S) -> Request:
    return Request(url=CHAT_URL, method="POST", headers={}, body=b"{}", timeout_s=timeout_s)


def test_the_default_transport_bounds_the_whole_call_not_each_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = TricklingReply(0.02)
    install(monkeypatch, lambda http, timeout: reply)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match=f"wall-clock deadline of {DEADLINE_S} s"):
        urllib_transport(chat_http())
    elapsed = time.monotonic() - started
    assert DEADLINE_S <= elapsed < DEADLINE_S + 0.5  # ends at the first read past the deadline
    assert 2 <= reply.reads <= 10


def test_a_body_that_completes_within_the_deadline_is_read_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b" " * 300_000 + chat_body('{"a":1}')  # padding first, as OpenRouter sends it
    install(monkeypatch, lambda http, timeout: FakeReply(body))
    assert urllib_transport(chat_http(timeout_s=30.0)) == Response(200, body)


def test_a_deadline_expiry_is_a_timeout_result_like_a_504_in_a_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch, lambda http, timeout: TricklingReply(0.02))
    result = ChatClient(urllib_transport).complete(make_request(timeout_s=DEADLINE_S), key=FAKE_KEY)
    assert result.classification == "timeout" and result.raw is None
    assert result.usage.cost is None and "cost" in result.usage.missing
