"""OpenRouter credit state (decision 0006 DC-8): what the account can still pay for.

Two signals feed it: `GET /api/v1/key` (`data.limit_remaining`, `data.usage`) and a 402 on a
chat completion. A key without a spending limit reports `limit_remaining: null`; that says
nothing about account credit, so it is recorded as null with a reason and `exhausted` stays
unknown (None). Only a limit at or below zero or a 402 declares the credit exhausted. Nothing
here sees the key: callers hand in the already-scrubbed response.

A dispatch 402 is read for its reason first (task 7.8). OpenRouter's in-flight refusal
(`error.metadata.reason` `in_flight_budget_exhausted` or `limit_source`
`openrouter_in_flight_budget`: earlier calls have not settled yet) is transient: `transient`
is true and `exhausted` unknown. Every other 402, a body that cannot be read included, stays
exhaustion. Only named fields are copied out of the body: its `user_id` (the account id) and
its message text are never recorded.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from deploy_vii.live.client import Response

Source = Literal["key-endpoint", "dispatch-402"]
IN_FLIGHT_REASON = "in_flight_budget_exhausted"
IN_FLIGHT_LIMIT_SOURCE = "openrouter_in_flight_budget"
_REFUSAL_FIELDS = ("reason", "retry_after_s", "requested_max_tokens", "affordable_max_tokens")
# At most 12 digits: a longer run is not read (and `int()` refuses over 4,300 digits).
_DIGITS = re.compile(r"[0-9]{1,12}")
_REQUESTED = re.compile(r"requested up to ([0-9]{1,12}) tokens")
_AFFORDABLE = re.compile(r"can only afford ([0-9]{1,12})(?![0-9])")


@dataclass(frozen=True)
class CreditState:
    checked_at: str
    source: Source
    exhausted: bool | None
    limit_remaining: Decimal | None
    usage: Decimal | None
    reasons: Mapping[str, str] = field(default_factory=dict)
    detail: str | None = None
    # `credential.LoadedKey.note()` when the key file held several tokens; counts only.
    key_note: Mapping[str, int] = field(default_factory=dict)
    # Read from a dispatch 402 only (task 7.8); each null has its reason in `reasons`.
    transient: bool = False
    reason: str | None = None  # `error.metadata.reason`, else `error.metadata.limit_source`
    retry_after_s: int | None = None
    requested_max_tokens: int | None = None  # "You requested up to N tokens"
    affordable_max_tokens: int | None = None  # "but can only afford N"

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "checked_at": self.checked_at,
            "source": self.source,
            "exhausted": self.exhausted,
            "limit_remaining": _text(self.limit_remaining),
            "usage": _text(self.usage),
            "detail": self.detail,
        }
        names = ["limit_remaining", "usage"]
        if self.source == "dispatch-402":
            record["transient"] = self.transient
            record.update({name: getattr(self, name) for name in _REFUSAL_FIELDS})
            names += _REFUSAL_FIELDS
        for name in names:
            if record[name] is None:
                record[f"{name}_reason"] = self.reasons.get(name, "not reported")
        if self.key_note:
            record["key_file"] = dict(self.key_note)
        return record

    def summary(self) -> str:
        """The refusal in one line: its reason, the token budget and Retry-After where the body
        states them, then the detail (`reason openrouter_credits; requested max_tokens 128000,
        affordable 91075; HTTP 402`)."""
        parts = [f"reason {self.reason or 'not stated'}"]
        if self.requested_max_tokens is not None or self.affordable_max_tokens is not None:
            parts.append(
                f"requested max_tokens {_count(self.requested_max_tokens)}, "
                f"affordable {_count(self.affordable_max_tokens)}"
            )
        if self.retry_after_s is not None:
            parts.append(f"Retry-After {self.retry_after_s} s")
        if self.detail:
            parts.append(self.detail)
        return "; ".join(parts)


class CreditExhausted(Exception):
    """OpenRouter credit is exhausted. The runner never substitutes a model or a cohort: moving
    to native Luna or a proxy is an explicit coordinator decision (DC-8)."""

    def __init__(self, state: CreditState, ticket_id: str | None = None) -> None:
        pending = f"; ticket {ticket_id} stays pending" if ticket_id else ""
        said = f": {state.summary()}" if state.source == "dispatch-402" else ""
        super().__init__(
            f"OpenRouter credit is exhausted ({state.source}, checked {state.checked_at}){said}; "
            f"dispatch refused{pending}. Switching to native Luna or a proxy is a coordinator "
            "decision."
        )
        self.state = state
        self.ticket_id = ticket_id


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _count(value: int | None) -> str:
    return "not stated" if value is None else str(value)


def _number(data: Mapping[str, Any], name: str, why_null: str) -> tuple[Decimal | None, str]:
    value = data.get(name)
    if isinstance(value, Decimal):
        return value, ""
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value), ""
    if value is None:
        return None, why_null if name in data else f"{name} absent from the response"
    return None, f"{name} is not a number"


def _error_object(body: bytes | None) -> tuple[Mapping[str, Any], str]:
    """The 402's `error` object (top level, else `choices[0].error`, a 402 inside a 200), or
    an empty one and why there is none."""
    try:
        document = json.loads((body or b"").decode("utf-8", errors="replace").strip())
    except ValueError:
        return {}, "the 402 body is not JSON"
    if not isinstance(document, dict):
        return {}, "the 402 body is not JSON"
    error = document.get("error")
    choices = document.get("choices")
    if not isinstance(error, dict) and isinstance(choices, list) and choices:
        error = choices[0].get("error") if isinstance(choices[0], dict) else None
    if not isinstance(error, dict):
        return {}, "the 402 body has no error object"
    return error, ""


def _seconds(value: object) -> int | None:
    """Retry-After as delta-seconds; an HTTP-date or anything else is not read."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and _DIGITS.fullmatch(value.strip()):
        return int(value.strip())
    return None


def _retry_after(headers: Mapping[str, Any]) -> object:
    """The `Retry-After` entry of the body's `metadata.headers` (header names ignore case)."""
    return next((v for k, v in headers.items() if str(k).lower() == "retry-after"), None)


def _stated(pattern: re.Pattern[str], message: str) -> int | None:
    found = pattern.search(message)
    return int(found.group(1)) if found else None


def _as_dict(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def from_dispatch_402(
    checked_at: str,
    http_status: int | None,
    body: bytes | None,
    header_retry_after: str | None = None,
) -> CreditState:
    """Read a (scrubbed) dispatch 402 body for its reason, Retry-After and token budget.

    `header_retry_after` is the reply's HTTP `Retry-After`; the body's
    `error.metadata.headers.Retry-After` wins over it. Only the in-flight markers make the
    refusal transient; anything else, an unreadable body included, is exhaustion."""
    error, unread = _error_object(body)
    metadata = _as_dict(error.get("metadata"))
    named, limit_source = metadata.get("reason"), metadata.get("limit_source")
    transient = named == IN_FLIGHT_REASON or limit_source == IN_FLIGHT_LIMIT_SOURCE
    reason = next((v for v in (named, limit_source) if isinstance(v, str) and v), None)
    stated = _retry_after(_as_dict(metadata.get("headers")))
    raw_wait = header_retry_after if stated is None else stated
    retry_after = _seconds(raw_wait)
    message = error.get("message")
    message = message if isinstance(message, str) else ""
    requested, affordable = _stated(_REQUESTED, message), _stated(_AFFORDABLE, message)
    reasons = {
        "limit_remaining": "a 402 does not report the remaining limit",
        "usage": "a 402 does not report usage",
    }
    if reason is None:
        reasons["reason"] = unread or "the 402 names no reason"
    if retry_after is None:
        reasons["retry_after_s"] = (
            "Retry-After is not a number of seconds"
            if raw_wait is not None
            else "no Retry-After in the 402 body or HTTP header"
        )
    if requested is None:
        reasons["requested_max_tokens"] = unread or "the 402 message states no requested tokens"
    if affordable is None:
        reasons["affordable_max_tokens"] = (
            unread or 'the 402 message states no "can only afford" token count'
        )
    return CreditState(
        checked_at=checked_at,
        source="dispatch-402",
        exhausted=None if transient else True,
        limit_remaining=None,
        usage=None,
        reasons=reasons,
        detail=f"HTTP {http_status}" if http_status is not None else "HTTP 402",
        transient=transient,
        reason=reason,
        retry_after_s=retry_after,
        requested_max_tokens=requested,
        affordable_max_tokens=affordable,
    )


def from_key_response(response: Response, checked_at: str) -> CreditState:
    """Interpret a (scrubbed) `GET /api/v1/key` reply; every unknown value is null + reason."""
    unknown = {"limit_remaining": "key endpoint gave no answer", "usage": "no answer"}

    def state(exhausted: bool | None, detail: str) -> CreditState:
        return CreditState(checked_at, "key-endpoint", exhausted, None, None, unknown, detail)

    if response.status == 402:
        return state(True, "HTTP 402")
    if not 200 <= response.status < 300:
        return state(None, f"HTTP {response.status}")
    try:
        document = json.loads(response.body.decode("utf-8", errors="replace"), parse_float=Decimal)
    except ValueError:
        return state(None, "key endpoint reply is not JSON")
    data = document.get("data") if isinstance(document, dict) else None
    if not isinstance(data, dict):
        return state(None, "key endpoint reply has no data object")
    remaining, remaining_why = _number(
        data,
        "limit_remaining",
        "limit_remaining is null: the key has no spending limit, so account credit is not "
        "visible here; a 402 on dispatch is the authoritative signal",
    )
    usage, usage_why = _number(data, "usage", "usage is null")
    reasons = {
        name: why for name, why in (("limit_remaining", remaining_why), ("usage", usage_why)) if why
    }
    return CreditState(
        checked_at,
        "key-endpoint",
        None if remaining is None else remaining <= 0,
        remaining,
        usage,
        reasons,
    )
