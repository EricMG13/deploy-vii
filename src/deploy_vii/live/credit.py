"""OpenRouter credit state (decision 0006 DC-8): what the account can still pay for.

Two signals feed it: `GET /api/v1/key` (`data.limit_remaining`, `data.usage`) and a 402 on a
chat completion. A key without a spending limit reports `limit_remaining: null`; that says
nothing about account credit, so it is recorded as null with a reason and `exhausted` stays
unknown (None). Only a limit at or below zero or a 402 declares the credit exhausted. Nothing
here sees the key: callers hand in the already-scrubbed response.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from deploy_vii.live.client import Response

Source = Literal["key-endpoint", "dispatch-402"]


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

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "checked_at": self.checked_at,
            "source": self.source,
            "exhausted": self.exhausted,
            "limit_remaining": _text(self.limit_remaining),
            "usage": _text(self.usage),
            "detail": self.detail,
        }
        for name in ("limit_remaining", "usage"):
            if record[name] is None:
                record[f"{name}_reason"] = self.reasons.get(name, "not reported")
        if self.key_note:
            record["key_file"] = dict(self.key_note)
        return record


class CreditExhausted(Exception):
    """OpenRouter credit is exhausted. The runner never substitutes a model or a cohort: moving
    to native Luna or a proxy is an explicit coordinator decision (DC-8)."""

    def __init__(self, state: CreditState, ticket_id: str | None = None) -> None:
        pending = f"; ticket {ticket_id} stays pending" if ticket_id else ""
        super().__init__(
            f"OpenRouter credit is exhausted ({state.source}, checked {state.checked_at}); "
            f"dispatch refused{pending}. Switching to native Luna or a proxy is a coordinator "
            "decision."
        )
        self.state = state
        self.ticket_id = ticket_id


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _number(data: Mapping[str, Any], name: str, why_null: str) -> tuple[Decimal | None, str]:
    value = data.get(name)
    if isinstance(value, Decimal):
        return value, ""
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value), ""
    if value is None:
        return None, why_null if name in data else f"{name} absent from the response"
    return None, f"{name} is not a number"


def from_dispatch_402(checked_at: str, http_status: int | None) -> CreditState:
    return CreditState(
        checked_at=checked_at,
        source="dispatch-402",
        exhausted=True,
        limit_remaining=None,
        usage=None,
        reasons={
            "limit_remaining": "a 402 does not report the remaining limit",
            "usage": "a 402 does not report usage",
        },
        detail=f"HTTP {http_status}" if http_status is not None else "HTTP 402",
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
