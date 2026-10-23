"""Task 7.8: a dispatch 402 is read for its reason before it is called exhaustion.

The two bodies are the E1 refusals of 23 October 2026 (batches e1-cp1-8 and e1-cp1-9), built
from the text the task brief quotes; the account id is a fixture value, never the real one.
"""

import json
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from deploy_vii.live.client import Response
from deploy_vii.live.credit import (
    CreditExhausted,
    CreditState,
    from_dispatch_402,
    from_key_response,
)

NOW = "2026-10-23T06:31:49Z"
ACCOUNT = "user_TESTONLY-account-id"  # stands in for the body's `user_id`


def refusal(message: str, metadata: dict[str, Any]) -> bytes:
    """An OpenRouter 402 body: `error.{message, code, metadata}` and the account's `user_id`."""
    error = {"message": message, "code": 402, "metadata": metadata}
    return json.dumps({"error": error, "user_id": ACCOUNT}).encode()


# Batch e1-cp1-8: `source_context` refused 105 s after CP-0 was accepted (US$0.484).
IN_FLIGHT_402 = refusal(
    "This request would exceed your available credits given your current in-flight requests. "
    "Retry after in-flight requests settle",
    {
        "reason": "in_flight_budget_exhausted",
        "limit_source": "openrouter_in_flight_budget",
        "headers": {"Retry-After": "120"},
        "provider_name": None,
    },
)
# Batch e1-cp1-9: the first call (CP-0) refused for the balance.
CREDIT_402 = refusal(
    "This request requires more credits, or fewer max_tokens. "
    "You requested up to 128000 tokens, but can only afford 91075.",
    {"limit_source": "openrouter_credits", "provider_name": None},
)


def test_the_in_flight_refusal_is_transient_with_its_retry_after() -> None:
    state = from_dispatch_402(NOW, 402, IN_FLIGHT_402)
    assert state.transient is True and state.exhausted is None
    assert state.reason == "in_flight_budget_exhausted" and state.retry_after_s == 120
    assert state.requested_max_tokens is None and state.affordable_max_tokens is None
    record = state.to_record()
    assert record["source"] == "dispatch-402" and record["transient"] is True
    assert record["reason"] == "in_flight_budget_exhausted" and record["retry_after_s"] == 120
    assert record["affordable_max_tokens"] is None
    assert "can only afford" in record["affordable_max_tokens_reason"]
    assert "user_id" not in json.dumps(record) and ACCOUNT not in json.dumps(record)
    assert ACCOUNT not in repr(state)


def test_the_credit_refusal_is_exhaustion_and_carries_the_affordable_budget() -> None:
    state = from_dispatch_402(NOW, 402, CREDIT_402)
    assert state.transient is False and state.exhausted is True
    assert state.reason == "openrouter_credits"
    assert state.requested_max_tokens == 128000 and state.affordable_max_tokens == 91075
    assert state.retry_after_s is None
    record = state.to_record()
    assert record["requested_max_tokens"] == 128000 and record["affordable_max_tokens"] == 91075
    assert record["retry_after_s_reason"] == "no Retry-After in the 402 body or HTTP header"
    assert "user_id" not in json.dumps(record) and ACCOUNT not in json.dumps(record)
    assert state.summary() == (
        "reason openrouter_credits; requested max_tokens 128000, affordable 91075; HTTP 402"
    )
    message = str(CreditExhausted(state, "t-1"))
    assert "credit is exhausted" in message and "ticket t-1 stays pending" in message
    assert "reason openrouter_credits; requested max_tokens 128000, affordable 91075" in message


def test_the_limit_source_alone_marks_the_in_flight_refusal() -> None:
    body = refusal("busy", {"limit_source": "openrouter_in_flight_budget"})
    state = from_dispatch_402(NOW, 402, body)
    assert state.transient is True and state.exhausted is None
    assert state.reason == "openrouter_in_flight_budget"
    # No Retry-After anywhere: null, explained (the runner then waits its default).
    assert state.retry_after_s is None
    assert state.to_record()["retry_after_s_reason"] == (
        "no Retry-After in the 402 body or HTTP header"
    )


@pytest.mark.parametrize(
    ("body", "why"),
    [
        (b"Payment Required (plain text)", "the 402 body is not JSON"),
        (None, "the 402 body is not JSON"),
        (b'{"detail":"no body error key"}', "the 402 body has no error object"),
        (b'{"error":{"message":"Insufficient credits","code":402}}', "the 402 names no reason"),
        (b'{"error":{"code":402,"metadata":{"reason":7}}}', "the 402 names no reason"),
    ],
)
def test_an_unreadable_402_stays_exhaustion_with_every_null_explained(
    body: bytes | None, why: str
) -> None:
    state = from_dispatch_402(NOW, 402, body)
    assert state.exhausted is True and state.transient is False
    record = state.to_record()
    assert record["reason"] is None and record["reason_reason"] == why
    for name in ("retry_after_s", "requested_max_tokens", "affordable_max_tokens"):
        assert record[name] is None and record[f"{name}_reason"]
    assert record["detail"] == "HTTP 402"
    assert state.summary() == "reason not stated; HTTP 402"


def test_the_http_retry_after_header_is_read_when_the_body_has_none() -> None:
    body = refusal("busy", {"reason": "in_flight_budget_exhausted"})
    assert from_dispatch_402(NOW, 402, body, header_retry_after="45").retry_after_s == 45
    # The body's own value wins over the header.
    assert from_dispatch_402(NOW, 402, IN_FLIGHT_402, header_retry_after="45").retry_after_s == 120
    dated = from_dispatch_402(NOW, 402, body, header_retry_after="Wed, 21 Oct 2026 07:28:00 GMT")
    assert dated.retry_after_s is None
    assert dated.to_record()["retry_after_s_reason"] == "Retry-After is not a number of seconds"
    numeric = refusal(
        "busy", {"reason": "in_flight_budget_exhausted", "headers": {"Retry-After": 9}}
    )
    assert from_dispatch_402(NOW, 402, numeric).retry_after_s == 9


def test_oversized_numbers_are_not_read_and_never_raise() -> None:
    """Confidence review: `int()` refuses digit strings over 4,300 digits, so a provider body
    with one must leave the value null (the default wait applies), not fail the dispatch."""
    huge = "9" * 5000
    body = refusal(
        f"You requested up to {huge} tokens, but can only afford {huge}",
        {"reason": "in_flight_budget_exhausted", "headers": {"Retry-After": huge}},
    )
    state = from_dispatch_402(NOW, 402, body)
    assert state.transient is True
    assert (state.retry_after_s, state.requested_max_tokens, state.affordable_max_tokens) == (
        None,
        None,
        None,
    )
    assert state.to_record()["retry_after_s_reason"] == "Retry-After is not a number of seconds"


def test_the_body_retry_after_key_is_read_in_any_case() -> None:
    body = refusal(
        "busy", {"reason": "in_flight_budget_exhausted", "headers": {"retry-after": "7"}}
    )
    assert from_dispatch_402(NOW, 402, body).retry_after_s == 7


def test_a_402_inside_choices_is_read_from_that_error_object() -> None:
    error = {
        "code": 402,
        "message": "You requested up to 4000 tokens, but can only afford 12.",
        "metadata": {"limit_source": "openrouter_credits"},
    }
    body = json.dumps({"id": "gen-1", "choices": [{"error": error}], "user_id": ACCOUNT})
    state = from_dispatch_402(NOW, 200, body.encode())
    assert state.exhausted is True and state.reason == "openrouter_credits"
    assert (state.requested_max_tokens, state.affordable_max_tokens) == (4000, 12)
    assert state.detail == "HTTP 200"


def test_the_key_endpoint_record_is_unchanged() -> None:
    state = from_key_response(Response(200, b'{"data":{"limit_remaining":null,"usage":2.5}}'), NOW)
    assert set(state.to_record()) == {
        "checked_at",
        "source",
        "exhausted",
        "limit_remaining",
        "usage",
        "detail",
        "limit_remaining_reason",
    }
    assert state.usage == Decimal("2.5")
    paid = CreditState(NOW, "key-endpoint", True, Decimal(0), Decimal(5), {}, None)
    assert str(CreditExhausted(paid, "t-1")) == (
        f"OpenRouter credit is exhausted (key-endpoint, checked {NOW}); dispatch refused; "
        "ticket t-1 stays pending. Switching to native Luna or a proxy is a coordinator decision."
    )


MARKERS = {"in_flight_budget_exhausted", "openrouter_in_flight_budget"}
TEXT = st.text(max_size=30).filter(lambda value: value not in MARKERS)


@given(
    metadata=st.dictionaries(
        st.sampled_from(["reason", "limit_source", "headers", "provider_name"]),
        st.one_of(TEXT, st.none(), st.integers()),
    ),
    message=st.text(max_size=80),
)
def test_without_the_in_flight_markers_every_402_is_exhaustion(
    metadata: dict[str, object], message: str
) -> None:
    state = from_dispatch_402(NOW, 402, refusal(message, dict(metadata)))
    assert state.exhausted is True and state.transient is False
    assert ACCOUNT not in json.dumps(state.to_record())
