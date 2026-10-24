"""`live schema-check`: one strict `response_format` call per (model, step schema).

Moved out of `live.runner` (task 8.0c) unchanged: the check reuses the runner's cost, ledger
and attempt-id helpers but nothing reaches an execution journal, and `dispatch` reads only the
`schema_rejections` mapping this module builds from the retained records.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from deploy_vii.live.catalog import PinnedCandidate
from deploy_vii.live.client import (
    CHAT_URL,
    SCHEMA_WORDS,
    ChatClient,
    ChatRequest,
    ChatResult,
)
from deploy_vii.live.credential import load_key_with_note, redact
from deploy_vii.live.credit import CreditExhausted, from_dispatch_402
from deploy_vii.live.ledger import CapExceeded, Ledger, Settlement, utc_stamp
from deploy_vii.live.prompts import response_format, schema_text
from deploy_vii.live.retention import AttemptLocator, AttemptWriter, response_envelope
from deploy_vii.live.runner import (
    _NOT_RECEIVED,
    _UNSENT,
    COHORT,
    SUBMITTED,
    _Cost,
    _cost,
    _ledger_block,
    _nullable,
    _provider_usage,
    code_sha256,
    next_attempt_id,
    prompt_token_bound,
    reservation_usd,
)
from deploy_vii.live.schema import (
    RELAXATIONS_BASIS,
    schema_keywords,
    schema_relaxations,
    schema_shape,
    unverified_keywords,
)
from deploy_vii.live.submission import STEPS

__all__ = [
    "SchemaCheck",
    "check_schema",
    "schema_rejections",
]

# --- `live schema-check` (task 2.11) ------------------------------------------------------------
#
# One strict `response_format` call per (model, step schema) with the smallest legal prompt, so a
# provider's verdict on a schema costs cents, not a CP-0 call. Reserved, retained and settled like
# any attempt (same client, key path and classification); nothing reaches an execution journal.

SCHEMA_CHECK_CASE = "schema-check"
SCHEMA_CHECK_RECORD = "schema-check-attempt/1"
# `schema-check --bisect` variants: evidence apart from the plain checks, so a variant's verdict
# can never block or lift a real run (`schema_rejections` reads `schema-check` only).
SCHEMA_BISECT_CASE = "schema-bisect"
SCHEMA_BISECT_RECORD = "schema-bisect-attempt/1"
SCHEMA_CHECK_MAX_TOKENS = 16  # the brief's floor; a provider minimum above it answers a 400
SCHEMA_CHECK_TIMEOUT_SECONDS = 120.0
SCHEMA_CHECK_PROMPT = "Reply with one JSON object that conforms to the response format."


def schema_shaped(result: ChatResult) -> bool:
    """True for an HTTP 400 whose provider code is `invalid_json_schema` or whose detail says
    "invalid schema" or names `response_format` (`client.SCHEMA_WORDS`). Google's "Request
    contains an invalid argument" does not. A detail withheld for its account id keeps the
    verdict it had: the client read the words before withholding it (`detail_names_schema`,
    task 7.15 fix round 1)."""
    if result.classification != "http_error" or result.http_status != 400:
        return False
    if result.provider_error_code == "invalid_json_schema":
        return True
    return result.detail_names_schema or bool(SCHEMA_WORDS.search(result.error_detail or ""))


@dataclass(frozen=True)
class SchemaCheck:
    """One (model, step) result. `outcome`: accepted (ok or truncated: the provider took the
    schema), http_error (with the provider's `detail`), other (timeout, fallback, credit),
    ineligible or refused (nothing sent)."""

    model: str
    step_id: str
    outcome: str
    classification: str
    http_status: int | None
    detail: str | None
    schema_sha256: str
    relaxations: tuple[str, ...]
    attempt_id: str
    charged_usd: Decimal | None
    held: bool
    schema_rejection: bool = False  # a schema-shaped 400: blocks later runs (`schema_shaped`)
    keywords: tuple[str, ...] = ()  # JSON-Schema keywords of the schema sent (`schema_keywords`)
    variant: str | None = None  # the bisect variant sent; None for the plain check


@dataclass
class _Check:
    candidate: PinnedCandidate
    step_id: str
    batch_id: str
    chat: ChatRequest
    locator: AttemptLocator
    reserve_usd: Decimal
    prompt_tokens: int
    cap_usd: Decimal
    clock: Callable[[], str]
    started_at: str
    variant: str | None = None
    status: str = "interrupted"
    result: ChatResult | None = None
    error: str | None = None
    settlement: Settlement | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    key_note: dict[str, int] = field(default_factory=dict)

    @property
    def schema(self) -> type[BaseModel]:
        return STEPS[self.step_id].schema

    @property
    def sent(self) -> dict[str, Any]:
        sent: dict[str, Any] = self.chat.response_format["json_schema"]["schema"]
        return sent

    @property
    def sent_sha256(self) -> str:
        """The hash `schema_text` gives the plain sent schema (same serialisation)."""
        text = json.dumps(self.sent, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()

    def event(self, name: str, **fields: object) -> None:
        self.events.append(
            {"seq": len(self.events) + 1, "at": self.clock(), "event": name, **fields}
        )


def schema_check_request(
    candidate: PinnedCandidate, step_id: str, schema: dict[str, Any] | None = None
) -> ChatRequest:
    """The minimal strict request: one short user message, 16 tokens, no reasoning parameter.

    `schema` replaces the step's sent schema (a bisect variant); the format is otherwise the
    one a probe sends (`name` = step id, `strict: true`)."""
    fmt = response_format(step_id, STEPS[step_id].schema)
    if schema is not None:
        fmt = {**fmt, "json_schema": {**fmt["json_schema"], "schema": schema}}
    return ChatRequest(
        model=candidate.slug,
        messages=({"role": "user", "content": SCHEMA_CHECK_PROMPT},),
        max_tokens=SCHEMA_CHECK_MAX_TOKENS,
        response_format=fmt,
        reasoning_effort=None,
        accepted_model_ids=(candidate.slug, candidate.canonical_slug),
        timeout_s=SCHEMA_CHECK_TIMEOUT_SECONDS,
        reasoning=False,
    )


def _check_manifest(check: _Check, cost: _Cost) -> dict[str, Any]:
    result, sent = check.result, check.sent
    return {
        "schema": SCHEMA_CHECK_RECORD if check.variant is None else SCHEMA_BISECT_RECORD,
        "experiment_id": check.batch_id,
        "case_id": check.locator.case,
        "variant": check.variant,
        "attempt_id": check.locator.attempt,
        "model": check.candidate.slug,
        "module_id": STEPS[check.step_id].module_id,
        "step_id": check.step_id,
        "started_at": check.started_at,
        "finished_at": check.clock(),
        "cohort": COHORT,
        "status": check.status,
        "classification": result.classification if result else None,
        "http_status": result.http_status if result else None,
        "error": check.error,
        "error_detail": result.error_detail if result else None,
        "provider_error_code": result.provider_error_code if result else None,
        # Only a schema-shaped 400 blocks later runs (`schema_rejections`).
        "schema_rejection": bool(result and schema_shaped(result)),
        "journal": "none: schema-check submits nothing",
        "code": {"live_package_sha256": code_sha256()},
        "hashes": {
            "schema_sha256": check.sent_sha256,
            "request_sha256": hashlib.sha256(
                json.dumps(check.chat.body(), sort_keys=True).encode()
            ).hexdigest(),
        },
        "schema_keywords": schema_keywords(sent),
        "schema_shape": schema_shape(sent),
        "schema_keywords_unverified": unverified_keywords(sent),
        # A variant is derived from the step's sent schema; its relaxations are that schema's.
        "variant_base_schema_sha256": (
            None
            if check.variant is None
            else hashlib.sha256(schema_text(check.schema).encode()).hexdigest()
        ),
        "schema_relaxations": schema_relaxations(check.schema),
        "schema_relaxations_of": (
            "hashes.schema_sha256" if check.variant is None else "variant_base_schema_sha256"
        ),
        "schema_relaxations_basis": RELAXATIONS_BASIS,
        "endpoint": CHAT_URL,
        "routing": {"allow_fallbacks": False, "require_parameters": True, "models": None},
        "reasoning": "not sent: the provider default applies",
        "served": {
            "model": result.served_model if result else None,
            "provider": result.served_provider if result else None,
            "provider_request_id": result.provider_request_id if result else None,
            "identity_verified": bool(result and result.identity_verified),
        },
        "budgets": {
            "cap_usd": check.cap_usd,
            "max_tokens": check.chat.max_tokens,
            "reserved_usd": check.reserve_usd if check.status not in _UNSENT else None,
            "timeout_s": check.chat.timeout_s,
        },
        "pinned_candidate": check.candidate.to_record(),
        "credential": {
            "recorded": False,
            "response_scrubbed": bool(result and result.redacted),
            **check.key_note,
        },
        "cost": {"basis": cost.basis, "reason": cost.reason},
    }


def _seal_check(check: _Check, writer: AttemptWriter, cost: _Cost) -> None:
    result = check.result
    checks: dict[str, Any] = {"verdict": {"outcome": check.status, "error": check.error}}
    if result is not None:
        checks["classification"] = {
            "classification": result.classification,
            "finish_reason": result.finish_reason,
            "identity_verified": result.identity_verified,
            "error_detail": result.error_detail,
        }
    metrics = {
        "provider": _provider_usage(result),
        "local": _nullable("latency_s", result.latency_s if result else None, _NOT_RECEIVED),
        "estimate": {"prompt_tokens_upper_bound": check.prompt_tokens},
        "ledger": _ledger_block(cost, check.settlement),
    }
    upstream = ["response.json", "output.md"] if result and result.redacted else []
    writer.seal(
        check.locator,
        _check_manifest(check, cost),
        check.events,
        metrics,
        checks,
        scrubbed_upstream=upstream,
    )


def _unsent_check(check: _Check, writer: AttemptWriter, status: str, reason: str) -> None:
    check.status, check.error = status, reason
    check.event(status, reason=reason)
    writer.record_response(check.locator, response_envelope(None, reason), None)
    _seal_check(check, writer, _Cost(None, "not-dispatched", f"{status}; nothing was sent"))


def _result(check: _Check) -> SchemaCheck:
    result = check.result
    unsent = check.status in _UNSENT
    return SchemaCheck(
        model=check.candidate.slug,
        step_id=check.step_id,
        outcome=check.status,
        classification="not sent" if unsent or result is None else result.classification,
        http_status=result.http_status if result else None,
        detail=check.error if unsent or result is None else result.error_detail,
        schema_sha256=check.sent_sha256,
        relaxations=tuple(schema_relaxations(check.schema)),
        attempt_id=check.locator.attempt,
        charged_usd=check.settlement.charged if check.settlement else None,
        held=bool(check.settlement and check.settlement.unreconciled),
        schema_rejection=bool(result and schema_shaped(result)),
        keywords=tuple(schema_keywords(check.sent)),
        variant=check.variant,
    )


def check_schema(
    candidate: PinnedCandidate,
    step_id: str,
    *,
    batch_id: str,
    ledger: Ledger,
    client: ChatClient,
    writer: AttemptWriter,
    key_path: Path,
    key_index: int,
    bytes_per_token: Decimal,
    clock: Callable[[], str] = utc_stamp,
    variant: tuple[str, dict[str, Any]] | None = None,
) -> SchemaCheck:
    """Send `step_id`'s sent schema to `candidate` once and record the provider's verdict.

    Evidence goes to `<root>/<batch_id>/schema-check/<model>/<attempt>/`; with `variant` (a
    bisect variant's name and schema, which is sent instead) to `.../schema-bisect/...`, which
    no real run reads. A reservation the cap refuses is sealed and returned as outcome
    `refused` (nothing sent; the caller stops); a connection failure propagates after the
    reservation is settled as held; a 402 raises CreditExhausted after the attempt is sealed
    (DC-8), with the reason its body states. A check is not retried, so an in-flight 402 stops
    it too (task 7.8; only `dispatch` waits and re-sends)."""
    name, schema = variant if variant is not None else (None, None)
    chat = schema_check_request(candidate, step_id, schema)
    tokens = prompt_token_bound(chat.body(), bytes_per_token)
    # As in `dispatch`: a key that cannot be read stops the check before anything is written
    # or reserved, so no reservation is left open.
    loaded = load_key_with_note(key_path, key_index)
    prefix = f"{candidate.slug.replace('/', '__')}-{step_id}" + (f"-{name}" if name else "")
    case = SCHEMA_CHECK_CASE if name is None else SCHEMA_BISECT_CASE
    base = AttemptLocator(batch_id, case, candidate.slug, prefix)
    attempt_id, _ = next_attempt_id(ledger, writer, base, prefix)
    check = _Check(
        candidate=candidate,
        step_id=step_id,
        batch_id=batch_id,
        chat=chat,
        locator=replace(base, attempt=attempt_id),
        reserve_usd=reservation_usd(candidate, tokens, chat.max_tokens),
        prompt_tokens=tokens,
        cap_usd=ledger.cap,
        clock=clock,
        started_at=clock(),
        variant=name,
    )
    writer.begin(
        check.locator,
        {
            "endpoint": CHAT_URL,
            "method": "POST",
            "body": chat.body(),
            "non_secret_parameters": {
                "timeout_s": chat.timeout_s,
                "accepted_model_ids": list(chat.accepted_model_ids),
                "prompt_tokens_upper_bound": tokens,
            },
            "authentication": "Authorization header omitted; the credential is never recorded",
        },
    )
    misfit = candidate.misfit(tokens, chat.max_tokens)
    if misfit is not None:
        _unsent_check(check, writer, "ineligible", f"ineligible: {misfit}")
        return _result(check)
    try:
        ledger.reserve(attempt_id, check.reserve_usd)
    except CapExceeded as error:
        _unsent_check(check, writer, "refused", str(error))
        return _result(check)  # the caller stops the batch: nothing further fits the cap
    check.event("reserved", usd=check.reserve_usd, prompt_tokens_upper_bound=tokens)
    if loaded.tokens_found > 1:
        check.key_note = loaded.note()
    try:
        check.event("request_sent", model=candidate.slug)
        answer = check.result = client.complete(chat, key=loaded.key)
        check.status = (
            "accepted"
            if answer.classification in SUBMITTED
            else "http_error"
            if answer.classification == "http_error"
            else "other"
        )
        check.event(
            "response_received",
            classification=answer.classification,
            http_status=answer.http_status,
        )
    except BaseException as failure:
        check.error = redact(f"{type(failure).__name__}: {failure}", loaded.key)
        check.event("interrupted", error=check.error)
        raise
    finally:
        result = check.result
        writer.record_response(
            check.locator,
            response_envelope(result, check.error or "no response received"),
            result.content if result else None,
        )
        cost = _cost(candidate, result)
        try:
            check.settlement = ledger.settle(
                attempt_id, cost.amount, f"{cost.reason}; schema-check status={check.status}"
            )
            check.event("ledger_settled", charged=check.settlement.charged, basis=cost.basis)
        finally:
            _seal_check(check, writer, cost)
    if answer.classification == "insufficient_credit":
        state = from_dispatch_402(clock(), answer.http_status, answer.raw, answer.retry_after)
        if state.exhausted is not True:
            detail = f"{state.detail} in flight; schema-check does not retry: treated as exhaustion"
            state = replace(state, exhausted=True, detail=detail)
        raise CreditExhausted(state)
    return _result(check)


def _check_record(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:  # a JSONDecodeError or undecodable bytes: the record is corrupt
        raise ValueError(f"{path} is not a schema-check record (not JSON)") from None
    fields = {"experiment_id", "model", "step_id", "status", "finished_at", "hashes"}
    if (
        not isinstance(record, dict)
        or record.get("schema") != SCHEMA_CHECK_RECORD
        or not fields <= set(record)
        or not isinstance(record["hashes"], dict)
        or "schema_sha256" not in record["hashes"]
    ):
        raise ValueError(f"{path} is not a {SCHEMA_CHECK_RECORD} schema-check record")
    return record


def schema_rejections(artifact_root: Path) -> dict[tuple[str, str, str], str]:
    """(model, step, sent schema sha256) -> the batch whose schema-check saw it refused.

    Only verdicts on the schema count: an accepted call, or an HTTP 400 the record marks
    `schema_rejection: true` (`schema_shaped`). Other errors, refusals, interruptions, a 400
    that does not name the schema and a record written before that field existed say nothing
    about the schema and neither block nor lift. The latest verdict per key wins (finished_at,
    then batch id), so a later accepted check lifts an earlier rejection, and a changed schema
    has a new hash and is never blocked by a verdict on the old one. An unreadable record fails
    closed (ValueError) before anything is spent."""
    latest: dict[tuple[str, str, str], tuple[str, str, bool]] = {}
    for path in sorted(artifact_root.glob(f"*/{SCHEMA_CHECK_CASE}/*/*/manifest.json")):
        record = _check_record(path)
        rejected = (
            record["status"] == "http_error"
            and record.get("http_status") == 400
            and record.get("schema_rejection") is True
        )
        if record["status"] != "accepted" and not rejected:
            continue
        key = (str(record["model"]), str(record["step_id"]), str(record["hashes"]["schema_sha256"]))
        verdict = (str(record["finished_at"]), str(record["experiment_id"]), rejected)
        if key not in latest or verdict[:2] > latest[key][:2]:
            latest[key] = verdict
    return {key: batch for key, (_, batch, rejected) in latest.items() if rejected}
