"""Decision 0006 DC-8: the no-credit backup cohort.

When OpenRouter has no credit the coordinator may run the same frozen step through a native
Luna agent or a Claude proxy. This module never makes that switch: `dispatch` raises
CreditExhausted and stops. A payload the coordinator supplies afterwards enters the journal
through `accept_proxy_payload`, the same validators as a live attempt, and is retained as the
cohort `proxy:<agent_label>`. A proxy attempt is never poolable, never counts toward a pool
model's results, never qualifies Luna, GLM 5.3 Flash or DeepSeek, and costs the cap nothing: its
ledger line is a zero reservation settled with `actual_usd: null` and reason `proxy`. The
cohort is also carried by the attempt id (`proxy-<label>-...`), because the ledger line
format has no cohort field and is unchanged.
"""

import hashlib
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from deploy_vii.execution import Attempt, Execution
from deploy_vii.live.catalog import utc_stamp
from deploy_vii.live.client import ChatClient
from deploy_vii.live.context import PACK_SOURCE_STEPS
from deploy_vii.live.credential import redact
from deploy_vii.live.credit import CreditExhausted, CreditState, from_key_response
from deploy_vii.live.ledger import Ledger, Settlement
from deploy_vii.live.retention import AttemptLocator, AttemptWriter
from deploy_vii.live.runner import (
    StepSpec,
    code_sha256,
    composed_event,
    expected_step,
    journal_outcome,
    next_attempt_id,
    step_repair_of,
    step_try,
)
from deploy_vii.live.submission import submit_model_payload

__all__ = [
    "CreditExhausted",
    "CreditState",
    "NativeLunaCheck",
    "ProxyResult",
    "accept_proxy_payload",
    "credit_state",
    "native_luna_available",
    "native_luna_check",
]

PROXY_PREFIX = "proxy:"
AGENT_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}")
NATIVE_LUNA_EXECUTABLE = "codex"
PROXY_REASON = "proxy"
NO_USAGE = "proxy agent usage is not exposed to the runner"


def credit_state(client: ChatClient, *, clock: Callable[[], str] = utc_stamp) -> CreditState:
    """Ask `GET /api/v1/key` what is left. The client holds the credential path and reads the
    key itself for this one call; no key value passes through here, only its token counts."""
    fetched = client.fetch_key_status()
    state = from_key_response(fetched.response, clock())
    return replace(state, key_note=dict(fetched.key_note)) if fetched.key_note else state


@dataclass(frozen=True)
class NativeLunaCheck:
    """Whether a `codex` executable is on PATH. Installed is not entitled: this never assumes."""

    available: bool | None
    path: str | None
    reason: str
    checked_at: str

    def to_record(self) -> dict[str, Any]:
        return {
            "executable": NATIVE_LUNA_EXECUTABLE,
            "available": self.available,
            "path": self.path,
            "reason": self.reason,
            "checked_at": self.checked_at,
        }


def native_luna_check(
    *,
    which: Callable[[str], str | None] = shutil.which,
    clock: Callable[[], str] = utc_stamp,
) -> NativeLunaCheck:
    """True with the path, False with the reason, None only if the check itself could not run."""
    at = clock()
    try:
        found = which(NATIVE_LUNA_EXECUTABLE)
    except OSError as error:
        return NativeLunaCheck(None, None, f"the PATH lookup could not run: {error}", at)
    if found is None:
        reason = f"no {NATIVE_LUNA_EXECUTABLE} executable found: not on PATH"
        return NativeLunaCheck(False, None, reason, at)
    return NativeLunaCheck(
        True,
        found,
        f"{NATIVE_LUNA_EXECUTABLE} is on PATH; this does not establish entitlement to Luna",
        at,
    )


def native_luna_available(*, which: Callable[[str], str | None] = shutil.which) -> bool | None:
    return native_luna_check(which=which).available


@dataclass(frozen=True)
class ProxyResult:
    attempt_id: str
    cohort: str
    status: str
    directory: Path
    journal: Attempt | None
    settlement: Settlement | None
    issues: tuple[str, ...]


def accept_proxy_payload(
    step: StepSpec,
    payload: str,
    agent_label: str,
    *,
    store: Execution,
    ticket_id: str,
    ledger: Ledger,
    writer: AttemptWriter,
    batch_id: str,
    clock: Callable[[], str] = utc_stamp,
    native_luna: NativeLunaCheck | None = None,
    credit: CreditState | None = None,
) -> ProxyResult:
    """Feed a coordinator-supplied payload through the journal validators as cohort proxy:<label>.

    Raises ValueError for a bad label, pack sources declared for a step whose validator checks no
    span (task 7.5, R6), unknown ticket or a step that is not next on the ticket, before anything
    is written. A payload the journal rejects is retained and settles `rejected`.
    """
    if not AGENT_LABEL.fullmatch(agent_label):
        raise ValueError("agent label may hold letters, digits, '.', '_' and '-' (max 40)")
    if step.declared_sources and step.step_id not in PACK_SOURCE_STEPS:  # task 7.5, R6
        raise ValueError(
            f"step {step.step_id} checks no span against the pack; it declares no pack sources "
            "(declare them through live.context.step_sources)"
        )
    snapshot = store.read()
    attempt = next((item for item in snapshot.attempts if item.ticket_id == ticket_id), None)
    if attempt is None:
        raise ValueError("unknown ticket")
    if expected_step(attempt, step.module_id) != step.step_id:
        raise ValueError(f"{step.step_id} is not the next step for this ticket")
    luna = native_luna or native_luna_check(clock=clock)
    cohort = PROXY_PREFIX + agent_label
    first_try = f"proxy-{agent_label}-{ticket_id}-{step.step_id}"
    # A step the journal kept pending after its first rejection: this payload is its repair try
    # (task 7.0g), with its own ids, so it is never labelled a retry of the rejected try.
    current = step_try(attempt, step.step_id)
    prefix = first_try if current == 1 else f"{first_try}-repair"
    base = AttemptLocator(batch_id, step.case_id, cohort, prefix)
    attempt_id, retry_of = next_attempt_id(ledger, writer, base, prefix)
    known = [item.attempt_id for item in ledger.state().attempts]
    links = {
        "retry_of_attempt_id": retry_of,
        "step_repair_of_attempt_id": (
            step_repair_of(known, ticket_id, step.step_id) if current == 2 else None
        ),
    }
    locator = AttemptLocator(batch_id, step.case_id, cohort, attempt_id)
    started = clock()
    events: list[dict[str, Any]] = []

    def event(name: str, **fields: object) -> None:
        events.append({"seq": len(events) + 1, "at": clock(), "event": name, **fields})

    writer.begin(
        locator,
        {
            "endpoint": None,
            "method": None,
            "endpoint_reason": "no HTTP request: the coordinator supplied the payload",
            "cohort": cohort,
            "step_id": step.step_id,
            "declared_inputs": list(step.declared_sources),
            "note": "same frozen case, prompt, schema and validators as a live attempt (DC-8)",
        },
    )
    event("proxy_payload_received", cohort=cohort, native_luna=luna.to_record())
    # After begin, so a failed begin leaves no dangling reservation. A proxy attempt costs the
    # cap nothing, but the zero reservation is still the cap's gate: once the ledger is over its
    # cap (an overrun) it refuses, and that refusal is left to stand. The attempt directory then
    # holds only request.json and no manifest, i.e. an incomplete attempt.
    ledger.reserve(attempt_id, Decimal(0))
    status, error = "interrupted", None
    issues: tuple[str, ...] = ()
    journal: Attempt | None = None
    settlement: Settlement | None = None
    writer.record_response(
        locator,
        {
            "http_status": None,
            "source": "coordinator-supplied proxy payload",
            "body_text": payload,
            "body_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        },
        payload,
    )
    try:
        # The same null resolution and composition as a pool attempt, so replay treats both
        # cohorts alike.
        def resolved(paths: tuple[str, ...]) -> None:
            if paths:
                event("payload_nulls_resolved", paths=list(paths))

        submitted = submit_model_payload(
            store, attempt.ticket_id, step.step_id, payload, on_normalised=resolved
        )
        composed_event(event, submitted)
        journal = submitted.journal
        status, issues = journal_outcome(store, step.step_id, journal)
        event("journal_result", outcome=status, issues=list(issues))
    except BaseException as failure:
        error = redact(f"{type(failure).__name__}: {failure}", "")
        event("interrupted", error=error)
        raise
    finally:
        try:
            settlement = ledger.settle(attempt_id, None, PROXY_REASON)
            event("ledger_settled", charged=settlement.charged, reason=PROXY_REASON)
        finally:
            directory = writer.seal(
                locator,
                _manifest(
                    step,
                    attempt,
                    snapshot.content_hash(),
                    locator,
                    cohort,
                    luna,
                    status,
                    issues,
                    error,
                    links,
                    current,
                    started,
                    clock(),
                    payload,
                    credit,
                ),
                events,
                _metrics(status, issues),
                {"validator": {"outcome": status, "issues": list(issues)}},
            )
    return ProxyResult(attempt_id, cohort, status, directory, journal, settlement, issues)


def _metrics(status: str, issues: tuple[str, ...]) -> dict[str, Any]:
    provider: dict[str, Any] = {}
    for name in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "reasoning_tokens",
        "cached_tokens",
        "cost_usd",
    ):
        provider.update({name: None, f"{name}_reason": NO_USAGE})
    return {
        "provider": provider,
        "local": {"latency_s": None, "latency_s_reason": "not measured for a proxy payload"},
        "ledger": {
            "attempt_cost_usd": None,
            "cost_basis": PROXY_REASON,
            "cost_reason": "proxy attempts are not billed to the cap",
            "charged_usd": Decimal(0),
        },
        "validation": {"outcome": status, "issue_count": len(issues)},
    }


def _manifest(
    step: StepSpec,
    attempt: Attempt,
    snapshot_sha256: str,
    locator: AttemptLocator,
    cohort: str,
    luna: NativeLunaCheck,
    status: str,
    issues: tuple[str, ...],
    error: str | None,
    links: dict[str, str | None],
    current: int,
    started: str,
    finished: str,
    payload: str,
    credit: CreditState | None,
) -> dict[str, Any]:
    return {
        "schema": "model-test-attempt/1",
        "experiment_id": locator.experiment,
        "case_id": locator.case,
        "attempt_id": locator.attempt,
        "model": cohort,
        "ticket_id": attempt.ticket_id,
        "module_id": step.module_id,
        "step_id": step.step_id,
        "started_at": started,
        "finished_at": finished,
        "cohort": cohort,
        "status": status,
        "classification": None,
        "classification_reason": "no provider response: the payload came from a proxy agent",
        "poolable": False,
        "qualification": False,
        "error": error,
        "code": {"live_package_sha256": code_sha256()},
        "hashes": {
            "snapshot_sha256": snapshot_sha256,
            "journal_inputs": {item.input_id: item.sha256 for item in attempt.inputs},
            "declared_inputs": list(step.declared_sources),
            "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        },
        "draw": None,
        "draw_reason": "no draw: a proxy agent is chosen by the coordinator, not drawn",
        "effort": None,
        "effort_reason": "the proxy agent's effort is not controlled or reported by the runner",
        "served": {"model": None, "provider": None, "identity_verified": False},
        "served_reason": "a proxy agent is not an OpenRouter model",
        "backup": {
            "decision": "0006 DC-8",
            "caller_supplied_payload": True,
            "native_luna": luna.to_record(),
        },
        "links": links,
        "retries": {"step_try": current},
        "validator": {"outcome": status, "issues": list(issues)},
        "credential": {"recorded": False, "response_scrubbed": False},
        "credit": credit.to_record() if credit else None,
    }
