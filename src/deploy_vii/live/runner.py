"""Dispatch one module step to one drawn model: reserve, call, retain, validate, settle.

Order: the draw, effort and prompt are fixed before anything is spent; the cap is enforced by
reserving first; the raw response is retained before the journal sees it; the payload reaches
the journal only through `live.submission.submit_model_payload`: submit_cp0_review /
submit_cp1_step (the same validators as any other input), or `store.submit_step` with the
validator that rejects an uncomposable CP-0 submission or a CP-1 payload holding a reference
Python cannot bind (task 7.0i), or `promote_cp1` for CP-1's fifth step, `quality` (task 7.4),
or a one-step module's own entry (`MODULE_STEP_ENTRIES`: CP-1A, CP-2/CP-4/CP-3/CP-5 since
task 8.6 and CP-6 since task 8.7, each sent its module context and only its bound sources).
For source_readiness Python composes the stored review from the model's submission; for every
CP-1 step it pre-fills the hash bindings. The ledger is settled
and the manifest sealed even if validation raises. A response from a model other than the
drawn one (provider fallback) is retained and classified but never submitted, so a substitute
can never be counted as the drawn model. The key is loaded here, used for the header and for
scrubbing, and appears in no record.
"""

import hashlib
import json
import math
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from fractions import Fraction
from functools import cache, partial
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from deploy_vii.business_context import cp1_context_facts
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_workflow import cp1_registers
from deploy_vii.execution import Attempt, Execution, ExecutionSnapshot
from deploy_vii.live.catalog import PinnedCandidate, PinnedPool
from deploy_vii.live.client import (
    CHAT_URL,
    DEFAULT_TIMEOUT_SECONDS,
    ChatClient,
    ChatRequest,
    ChatResult,
    TransportError,
)
from deploy_vii.live.context import (
    INTEGRITY,
    OMITTED,
    SOURCE_SCOPES,
    declared_sources,
    integrity_scope,
    module_context,
    projection_name,
    upstream_text,
)
from deploy_vii.live.credential import load_key_with_note, redact
from deploy_vii.live.credit import CreditExhausted, CreditState, from_dispatch_402
from deploy_vii.live.draw import Draw, draw
from deploy_vii.live.ledger import AttemptRecord, CapExceeded, Ledger, Settlement, utc_stamp
from deploy_vii.live.prompts import (
    QUALITY,
    UpstreamInput,
    build,
    quality_scope,
    response_format,
    schema_text,
)
from deploy_vii.live.retention import AttemptLocator, AttemptWriter, response_envelope
from deploy_vii.live.schema import (
    RELAXATIONS_BASIS,
    schema_relaxations,
    unverified_keywords,
)
from deploy_vii.live.submission import STEPS, StepDef, Submitted, submit_model_payload
from deploy_vii.registry import settling_steps, step_chain

COHORT = "openrouter-pool"
DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_TOKENS = 16000  # the completion budget; `live ... --max-tokens N` overrides it
TOKEN_OVERHEAD = 64
# Task 7.8: the wait before the one retry of an in-flight 402 (`in_flight_wait_s`).
IN_FLIGHT_DEFAULT_WAIT_S = 120  # when the refusal states no Retry-After
IN_FLIGHT_MAX_WAIT_S = 300
# Ends the ledger settle reason of an in-flight 402 (`in_flight_refused`).
IN_FLIGHT_SETTLE_MARK = "; in-flight 402: not a model try"
# Ends it for the second in-flight 402 of one try, which is exhaustion (task 8.0a); it is no
# model try either (`in_flight_refused`).
IN_FLIGHT_EXHAUSTED_MARK = "; in-flight 402 again: treated as exhaustion"
SUBMITTED = frozenset({"ok", "truncated"})
# Each module's last step, whose acceptance is the module's (`journal_outcome`, task 8.0a).
SETTLING_STEPS = settling_steps()
POOLABLE_STATUSES = frozenset({"accepted", "rejected"})


__all__ = [
    "STEPS",
    "DispatchResult",
    "StepDef",
    "StepSpec",
    "dispatch",
]


@dataclass(frozen=True)
class StepSpec:
    """One case to dispatch: a module step, its declared source inputs and its token budget."""

    step_id: str
    case_id: str
    declared_sources: tuple[str, ...]
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.step_id not in STEPS:
            raise ValueError(f"unknown step {self.step_id!r}")
        if self.max_tokens <= 0 or self.timeout_s <= 0:
            raise ValueError("max_tokens and timeout_s must be positive")

    @property
    def module_id(self) -> str:
        return STEPS[self.step_id].module_id

    @property
    def schema(self) -> type[BaseModel]:
        return STEPS[self.step_id].schema


@dataclass(frozen=True)
class DispatchResult:
    """The outcome of one attempt.

    `status` is one of accepted, rejected (journal verdict on a submitted payload),
    no-response (HTTP error, 402 or timeout), withheld-fallback (served model differs from the
    drawn one; never submitted). The last two leave the journal ticket pending, and the caller
    may dispatch again on the same ticket: a retry is a new attempt id linked by
    `retry_of_attempt_id`, on the same drawn model (same seed), up to `max_retries` retries.
    On the attempt that exhausts them (attempt `max_retries + 1`, also for a connection
    failure that raises TransportError) the runner interrupts the ticket through
    `Execution.interrupt`. That consumes the input set's one repair: the next `begin` is the
    repair attempt, or, if this was already the repair, the module is blocked for these inputs.
    The manifest `retries` block records this. `ticket_interrupted` mirrors it.

    A CP-1 step the journal rejects for the first time in its attempt leaves the attempt
    pending (`attempt_pending`, task 7.0g): the same step is expected again, and its next
    dispatch is the step's one repair within the attempt (`step_try` 2), with its own attempt
    ids (`<ticket>-<step>-repair-<n>`) and its own retry budget.

    An in-flight 402 (task 7.8, `credit.from_dispatch_402`) is waited out and re-sent once by
    `dispatch` itself: the result is the re-sent attempt's, and `retried` holds the refused
    one (`no-response`, `insufficient_credit`, its credit state in `in_flight`).
    """

    attempt_id: str
    status: str
    classification: str | None
    draw: Draw
    effort: Mapping[str, Any]
    directory: Path
    journal: Attempt | None
    settlement: Settlement | None
    cost_usd: Decimal | None
    issues: tuple[str, ...]
    ticket_interrupted: bool = False
    prompt_tokens_upper_bound: int | None = None  # the reservation's prompt bound (MC-10)
    attempt_pending: bool = False  # the journal ticket is still pending after this dispatch
    step_try: int = 1  # 2 for the step's repair within its attempt (task 7.0g)
    in_flight: CreditState | None = None  # an in-flight 402 that `dispatch` retries (7.8)
    retried: "DispatchResult | None" = None  # the in-flight refused attempt this one re-sent

    @property
    def held(self) -> bool:
        """Whether the charge is the held reservation, not a measured cost."""
        return bool(self.settlement and self.settlement.unreconciled)


@cache
def code_sha256() -> str:
    """Hash of the live package sources, so a manifest names the code that produced it."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def request_bytes(body: Mapping[str, Any]) -> int:
    """UTF-8 bytes of the request body as serialised for `request_sha256` (sorted keys)."""
    return len(json.dumps(body, sort_keys=True).encode("utf-8"))


def prompt_token_bound(body: Mapping[str, Any], bytes_per_token: Decimal) -> int:
    """Upper bound on prompt tokens (MC-10, decision 0008): ceil(request bytes / the measured
    lower bound on bytes per token), plus the fixed overhead for chat-template tokens.

    `bytes_per_token` is `[model_tests].prompt_bytes_per_token_lower_bound`. Exact rational
    arithmetic: no float rounding can move the ceiling."""
    if not bytes_per_token.is_finite() or bytes_per_token <= 0:
        raise ValueError("bytes_per_token must be a positive finite amount")
    return math.ceil(Fraction(request_bytes(body)) / Fraction(bytes_per_token)) + TOKEN_OVERHEAD


def reservation_usd(candidate: PinnedCandidate, prompt_tokens: int, max_tokens: int) -> Decimal:
    """Worst case at the pinned price: prompt bound, full max_tokens (reasoning bills as output)."""
    return (
        prompt_tokens * candidate.prompt_price
        + max_tokens * candidate.completion_price
        + candidate.request_price
    )


@dataclass(frozen=True)
class RepairPrompt:
    """What a repair ticket's step prompt carries (MC-7, decision 0008)."""

    issues: tuple[str, ...]
    scope: str  # "failing-step", "none" (another step failed) or "module" (no step failed)
    failing_step: str | None

    def to_record(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "failing_step": self.failing_step,
            "issue_count": len(self.issues),
        }


def repair_prompt(snapshot: ExecutionSnapshot, attempt: Attempt, step_id: str) -> RepairPrompt:
    """The failing step's validator issues, on that step's prompt only.

    Within an attempt first (task 7.0g): a step whose first try this attempt rejected gets that
    try's issues (`Attempt.step_repairs`), and nothing from the previous attempt. Otherwise, on
    a repair ticket, the previous attempt's last invalid step is the failing step: its own
    issues go into the REPAIR block of the same step, and the other steps get none. When no step
    failed validation (an interruption, or a module-level refusal after valid steps) there is
    no step to scope to, so the module issues are carried on every step as before."""
    own = next((item for item in attempt.step_repairs if item.step_id == step_id), None)
    if own is not None:
        return RepairPrompt(own.issues, "failing-step", step_id)
    if attempt.repair_of is None:
        return RepairPrompt((), "none", None)
    previous = next(item for item in snapshot.attempts if item.ticket_id == attempt.repair_of)
    failed = next((item for item in reversed(previous.steps) if item.status == "invalid"), None)
    if failed is None:
        return RepairPrompt(attempt.repair_issues, "module", None)
    if failed.step_id != step_id:
        return RepairPrompt((), "none", failed.step_id)
    return RepairPrompt(failed.issues, "failing-step", failed.step_id)


@dataclass
class _Plan:
    step: StepSpec
    attempt: Attempt
    snapshot_sha256: str
    drawn: Draw
    candidate: PinnedCandidate
    effort: Mapping[str, Any]
    chat: ChatRequest
    prompt_tokens: int
    bytes_per_token: Decimal
    reserve_usd: Decimal
    attempt_id: str
    locator: AttemptLocator
    links: dict[str, str | None]
    clock: Callable[[], str]
    started_at: str
    ledger_cap: Decimal
    hashes: dict[str, Any]
    attempt_number: int
    max_retries: int
    repair: RepairPrompt
    step_try: int
    pool_label: str
    misfit: str | None
    events: list[dict[str, Any]] = field(default_factory=list)
    # Counts only, and only when the key file held several tokens (see credential.LoadedKey).
    key_note: dict[str, int] = field(default_factory=dict)
    # The wait before this re-send of an in-flight 402 (task 7.8; links name the refused try).
    in_flight_waited_s: int | None = None

    @property
    def exhausted(self) -> bool:
        """True on the attempt after which no further retry is allowed."""
        return self.attempt_number >= self.max_retries + 1

    def event(self, name: str, **fields: object) -> None:
        self.events.append(
            {"seq": len(self.events) + 1, "at": self.clock(), "event": name, **fields}
        )


@dataclass
class _Run:
    status: str = "interrupted"
    result: ChatResult | None = None
    journal: Attempt | None = None
    settlement: Settlement | None = None
    directory: Path | None = None
    response_staged: bool = False
    issues: tuple[str, ...] = ()
    failure: BaseException | None = None
    error: str | None = None
    ticket_interrupted: bool = False
    credit: CreditState | None = None


@dataclass(frozen=True)
class _Cost:
    amount: Decimal | None
    basis: str
    reason: str


def expected_step(attempt: Attempt, module_id: str) -> str:
    if attempt.module_id != module_id:
        raise ValueError(f"ticket belongs to {attempt.module_id}, not {module_id}")
    if attempt.status != "pending" or attempt.payload_sha256 is not None:
        raise ValueError("ticket is finished or already retains a module response")
    if any(item.status == "pending" for item in attempt.steps):
        raise ValueError("a step response is pending; resume it before dispatching another")
    # Task 8.0a: the module's registry chain (CP-1: the four stages, then the `quality` review
    # whose acceptance is the promotion). On a pending ticket the journal keeps valid steps
    # only, so `done` is its position: every module (CP-0's `submit_cp0_review` and CP-1A's
    # `submit_cp1a_step` included) retains steps through `Execution.submit_step`, which settles
    # an invalid response that is not repaired within the attempt in the write that retains it
    # (`_save_finished`), and keeps a repaired first try in `step_repairs`, not `steps`.
    steps = step_chain(module_id).steps
    done = sum(1 for item in attempt.steps if item.status == "valid")
    if done < len(steps):
        return steps[done]
    if len(steps) == 1:
        raise ValueError(f"{module_id} already retains its one step; resume it through the journal")
    raise ValueError(f"every {module_id} step is already retained")


def _upstream(store: Execution, attempt: Attempt, step_id: str) -> tuple[UpstreamInput, ...]:
    """The retained valid steps `step_id` is sent, each as its `live.context` projection under
    its content hash (task 7.5); an omitted step sends nothing, an unlisted pair raises."""
    blocks = []
    for item in attempt.steps:
        if item.status != "valid" or item.output_sha256 is None:
            continue
        projection = projection_name(step_id, item.step_id)
        if projection == OMITTED:
            continue
        output = store.step_output(item.output_sha256)
        text = upstream_text(step_id, item.step_id, output)
        blocks.append(UpstreamInput("step:" + item.step_id, item.content_hash(), text, projection))
    return tuple(blocks)


def step_try(attempt: Attempt, step_id: str) -> int:
    """2 when the journal kept this step's rejected first try for its repair within the attempt."""
    return 2 if any(item.step_id == step_id for item in attempt.step_repairs) else 1


def _tries(names: list[str], prefix: str) -> list[str]:
    """The attempt ids `<prefix>-<n>` among `names`, in order (`<prefix>-repair-<n>` excluded)."""
    pattern = re.compile(re.escape(prefix) + r"-[0-9]+")
    return [name for name in names if pattern.fullmatch(name)]


def step_repair_of(names: list[str], ticket_id: str, step_id: str) -> str:
    """The last first try of this ticket step among the ledger ids `names`, from either cohort
    (`<ticket>-<step>-<n>` or `proxy-<label>-<ticket>-<step>-<n>`): the try the journal rejected
    and kept for the step's repair within the attempt (task 7.0g). A repair without that try would
    carry false provenance, so its absence raises before anything is written (task 7.0h)."""
    first = re.escape(f"{ticket_id}-{step_id}") + r"-[0-9]+"
    pattern = re.compile(r"(?:proxy-[A-Za-z0-9_.-]+-)?" + first)
    found = next((name for name in reversed(names) if pattern.fullmatch(name)), None)
    if found is None:
        raise ValueError(
            f"no prior try of {ticket_id}/{step_id} in the ledger: "
            "a step repair needs the rejected try"
        )
    return found


def in_flight_refused(record: AttemptRecord) -> bool:
    """Whether the ledger settled this attempt as an in-flight 402 (task 7.8, fix round 1):
    credit is not a model failure, so such an attempt uses up no `max_retries` try. The mark is
    the end of the settle reason `_close` writes; the charge is known zero, so no `adjust`
    (held charges only) can replace it. Task 8.0a: the second in-flight refusal, exhaustion, ends
    with `IN_FLIGHT_EXHAUSTED_MARK` instead and counts the same; ledgers written before 8.0a
    carry `IN_FLIGHT_SETTLE_MARK` on both refusals."""
    basis = record.basis or ""
    return record.status == "settled" and basis.endswith(
        (IN_FLIGHT_SETTLE_MARK, IN_FLIGHT_EXHAUSTED_MARK)
    )


def next_attempt_id(
    ledger: Ledger, writer: AttemptWriter, base: AttemptLocator, prefix: str
) -> tuple[str, str | None]:
    """First unused id for this ticket and step, and the id of the previous try (a retry link)."""
    used = {item.attempt_id for item in ledger.state().attempts}
    number, previous = 1, None
    while True:
        name = f"{prefix}-{number}"
        if name not in used and not writer.path_for(replace(base, attempt=name)).exists():
            return name, previous
        previous, number = name, number + 1


def _plan(
    step: StepSpec,
    store: Execution,
    ticket_id: str,
    ledger: Ledger,
    pool: PinnedPool,
    seed: int,
    writer: AttemptWriter,
    effort: str,
    clock: Callable[[], str],
    max_retries: int,
    bytes_per_token: Decimal,
) -> _Plan:
    if max_retries < 0:
        raise ValueError("max_retries cannot be negative")
    snapshot = store.read()
    attempt = next((item for item in snapshot.attempts if item.ticket_id == ticket_id), None)
    if attempt is None:
        raise ValueError("unknown ticket")
    if expected_step(attempt, step.module_id) != step.step_id:
        raise ValueError(f"{step.step_id} is not the next step for this ticket")
    drawn = draw(pool, seed)
    candidate = pool.candidate(drawn.slug)
    decision = candidate.effort_for(effort)
    repair = repair_prompt(snapshot, attempt, step.step_id)
    # Task 7.4: the QA review reads the QA scope of the recomputed registers (registers that do
    # not stage raise here, before anything is spent), not the four retained stage outputs
    # (task 7.5: `live.context` omits them for `quality`).
    quality = step.step_id == QUALITY
    registers = cp1_registers(store, ticket_id) if quality else None
    inputs = cp1_quality_inputs(registers) if registers is not None else None
    # Task 8.6: CP-4 and CP-3 are sent only the sources their bound upstream names (CP-0's
    # legal, or third-party, sources); any other declared source is refused before spending.
    if step.step_id in SOURCE_SCOPES:
        allowed = declared_sources(
            store, attempt, step.step_id, [s.source_id for s in store.pack(snapshot).sources]
        )
        if extra := [s for s in step.declared_sources if s not in allowed]:
            raise ValueError(
                f"{step.step_id} is sent {', '.join(extra)}, which is not one of the sources its "
                f"bound upstream names ({', '.join(allowed) or 'none'})"
            )
    scope = (
        quality_scope(registers, inputs)
        if registers is not None
        else integrity_scope(store, attempt)
        if step.step_id == INTEGRITY
        else None
    )
    messages = build(
        step.step_id,
        store.pack(snapshot),
        step.declared_sources,
        step.schema,
        upstream=_upstream(store, attempt, step.step_id),
        repair_issues=repair.issues,
        # Task 7.2: the CP-1 facts the attempt binds (none unless CP-1 was settled at begin).
        cp1_facts=cp1_context_facts(store, attempt) if step.module_id == "CP-1A" else (),
        # Task 8.6: CP-2, CP-4 and CP-3 (task 8.7: and CP-6) read their bound upstream through
        # Python's view of it.
        module_context=module_context(store, attempt, step.step_id),
        scope=scope,
    )
    chat = ChatRequest(
        model=candidate.slug,
        messages=tuple(item.as_dict() for item in messages),
        max_tokens=step.max_tokens,
        response_format=response_format(step.step_id, step.schema),
        reasoning_effort=decision.sent,
        accepted_model_ids=(candidate.slug, candidate.canonical_slug),
        timeout_s=step.timeout_s,
    )
    body = chat.body()
    tokens = prompt_token_bound(body, bytes_per_token)
    first_try = f"{ticket_id}-{step.step_id}"
    current = step_try(attempt, step.step_id)
    # The step's repair within the attempt has its own ids, so its retries are its own.
    prefix = first_try if current == 1 else f"{first_try}-repair"
    base = AttemptLocator(pool.batch_id, step.case_id, candidate.slug, prefix)
    attempt_id, retry_of = next_attempt_id(ledger, writer, base, prefix)
    records = ledger.state().attempts
    known = [item.attempt_id for item in records]
    # Neither cap refusals (never reserved) nor in-flight 402s (task 7.8) are model tries.
    in_flight = {item.attempt_id for item in records if in_flight_refused(item)}
    tries = sum(name not in in_flight for name in _tries(known, prefix))
    if tries >= max_retries + 1:
        raise ValueError(
            f"{tries} attempts already used on this ticket step (max_retries={max_retries}); "
            "call Execution.interrupt on the ticket instead of dispatching again"
        )
    repair_of = attempt.repair_of
    return _Plan(
        step=step,
        attempt=attempt,
        snapshot_sha256=snapshot.content_hash(),
        drawn=drawn,
        candidate=candidate,
        effort=decision.to_record(),
        chat=chat,
        prompt_tokens=tokens,
        bytes_per_token=bytes_per_token,
        reserve_usd=reservation_usd(candidate, tokens, step.max_tokens),
        attempt_id=attempt_id,
        locator=AttemptLocator(pool.batch_id, step.case_id, candidate.slug, attempt_id),
        links={
            "repair_of_ticket_id": repair_of,
            "repair_of_attempt_id": next(
                (
                    name
                    for name in reversed(known)
                    if repair_of and name.startswith(repair_of + "-")
                ),
                None,
            ),
            "retry_of_attempt_id": retry_of,
            # The dispatched try the journal rejected; its issues are this try's REPAIR block.
            "step_repair_of_attempt_id": (
                step_repair_of(known, ticket_id, step.step_id) if current == 2 else None
            ),
            # The in-flight 402 this try re-sends (task 7.8); set by `dispatch`.
            "in_flight_retry_of_attempt_id": None,
        },
        clock=clock,
        started_at=clock(),
        ledger_cap=ledger.cap,
        attempt_number=tries + 1,
        max_retries=max_retries,
        repair=repair,
        step_try=current,
        pool_label=pool.pool_label,
        misfit=candidate.misfit(tokens, step.max_tokens),
        hashes={
            "prompt_sha256": hashlib.sha256(
                json.dumps(body["messages"], sort_keys=True).encode()
            ).hexdigest(),
            "schema_sha256": hashlib.sha256(schema_text(step.schema).encode()).hexdigest(),
            "request_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
            "declared_inputs": list(step.declared_sources),
            # Task 7.4 fix round 1: the QA inputs the scope shows and the review must bind.
            **({} if inputs is None else {"quality_inputs_sha256": inputs.content_hash()}),
        },
    )


def _request_record(plan: _Plan) -> dict[str, Any]:
    return {
        "endpoint": CHAT_URL,
        "method": "POST",
        "body": plan.chat.body(),
        "non_secret_parameters": {
            "timeout_s": plan.chat.timeout_s,
            "accepted_model_ids": list(plan.chat.accepted_model_ids),
            "prompt_tokens_upper_bound": plan.prompt_tokens,
            "prompt_bytes_per_token_lower_bound": format(plan.bytes_per_token, "f"),
        },
        "selection": {"draw": plan.drawn.to_record(), "effort": plan.effort},
        "authentication": "Authorization header omitted; the credential is never recorded",
    }


def _record_response(plan: _Plan, writer: AttemptWriter, run: _Run) -> None:
    reason = run.error or "no response received"
    content = run.result.content if run.result else None
    writer.record_response(plan.locator, response_envelope(run.result, reason), content)
    run.response_staged = True


def journal_outcome(
    store: Execution, step_id: str, journal: Attempt
) -> tuple[str, tuple[str, ...]]:
    # A step that settles its module (CP-0's review, CP-1A's one step, CP-1's `quality`
    # promotion) is accepted only when the settled module is: a valid step whose candidate
    # fails the journal's check is rejected.
    if step_id in SETTLING_STEPS:
        accepted = journal.result_sha256 is not None and store.result(
            journal.result_sha256
        ).status in {"accepted", "restricted"}
        return ("accepted" if accepted else "rejected"), journal.issues
    # A first rejection repaired within the attempt is kept apart from `steps` (task 7.0g).
    submitted = next(
        (item for item in reversed(journal.steps) if item.step_id == step_id),
        next((item for item in journal.step_repairs if item.step_id == step_id), None),
    )
    if submitted is None:
        raise ValueError(f"the journal retains no {step_id} submission on this ticket")
    return ("accepted" if submitted.status == "valid" else "rejected"), submitted.issues


def _pending(store: Execution, ticket_id: str) -> bool:
    """Whether the journal ticket is still pending, read from the journal after the dispatch."""
    attempt = next(item for item in store.read().attempts if item.ticket_id == ticket_id)
    return attempt.status == "pending"


def _interrupt_if_exhausted(plan: _Plan, store: Execution, run: _Run, why: str) -> None:
    """After the last allowed try, interrupt the ticket: that consumes the input set's repair."""
    if not plan.exhausted:
        return
    reason = (
        f"Retries exhausted after {plan.attempt_number} attempts on {plan.candidate.slug} "
        f"({why}); this consumes the input set's repair"
    )
    store.interrupt(plan.attempt.ticket_id, reason)
    run.ticket_interrupted = True
    plan.event("ticket_interrupted", reason=reason)


def _re_sent(run: _Run) -> bool:
    """Whether `dispatch` re-sends this attempt: an in-flight 402 not yet treated as exhaustion
    (task 7.8). The second in-flight refusal still reads transient but is exhaustion
    (`_refusal`): it is not re-sent, and its settle reason says so (`IN_FLIGHT_EXHAUSTED_MARK`,
    task 8.0a) while it still counts as no model try."""
    return run.credit is not None and run.credit.transient and run.credit.exhausted is None


def _retries_record(plan: _Plan, run: _Run) -> dict[str, Any]:
    consequence = None
    if run.ticket_interrupted:
        consequence = (
            "ticket interrupted: the input set's one repair is consumed; the next begin() "
            "is the repair attempt"
            if plan.attempt.number == 0
            else "ticket interrupted during the repair: no repair remains and the module is "
            "blocked for these inputs"
        )
    # An in-flight 402 `dispatch` re-sends (task 7.8) is no model try: on the last allowed try
    # the re-send follows, so the refused attempt exhausts nothing (task 7.10 item 7).
    resent = _re_sent(run)
    return {
        "attempt_number": plan.attempt_number,
        "step_try": plan.step_try,
        "max_retries": plan.max_retries,
        "exhausted": plan.exhausted and not resent,
        "ticket_interrupted": run.ticket_interrupted,
        "journal_consequence": consequence,
    }


def _refusal(plan: _Plan, result: ChatResult) -> CreditState:
    """The 402 as its body reads (task 7.8). An in-flight refusal is re-sent once (also on the
    last try: it used up none), so on the re-send itself it is exhaustion (DC-8)."""
    state = from_dispatch_402(plan.clock(), result.http_status, result.raw, result.retry_after)
    retried = plan.links["in_flight_retry_of_attempt_id"]
    if not state.transient or retried is None:
        return state
    why = f"in flight again after one retry of {retried} ({plan.in_flight_waited_s} s wait)"
    detail = f"{state.detail} on {plan.attempt_id}, {why}: treated as exhaustion"
    return replace(state, exhausted=True, detail=detail)


def in_flight_wait_s(state: CreditState) -> int:
    """Seconds to wait before re-sending an in-flight 402: its Retry-After, at most 300; 120
    when the refusal states none (task 7.8)."""
    stated = state.retry_after_s
    return min(IN_FLIGHT_DEFAULT_WAIT_S if stated is None else stated, IN_FLIGHT_MAX_WAIT_S)


def _submit(plan: _Plan, store: Execution, run: _Run) -> None:
    result = run.result
    assert result is not None
    if result.classification == "fallback":
        run.status = "withheld-fallback"
        plan.event("journal_skipped", reason="served model differs from the drawn model")
        _interrupt_if_exhausted(plan, store, run, "served model differed from the drawn model")
        return
    if result.classification not in SUBMITTED:
        run.status = "no-response"
        plan.event("journal_skipped", reason="no model payload to submit")
        if result.classification == "insufficient_credit":
            # Credit is not a model failure: the ticket stays open for the coordinator's
            # explicit choice (native Luna or a proxy) and the input set's repair is kept. An
            # in-flight refusal is not a model failure either: `dispatch` re-sends it once.
            run.credit = _refusal(plan, result)
            name = "credit_exhausted" if run.credit.exhausted else "credit_in_flight_refusal"
            plan.event(name, **run.credit.to_record())
            return
        _interrupt_if_exhausted(plan, store, run, result.classification)
        return

    # output.md keeps the raw content; the journal sees nulls for omitted defaults resolved,
    # for source_readiness the review Python composed from the submission and for every CP-1
    # step the hash bindings Python pre-filled (task 7.0i).
    def resolved(paths: tuple[str, ...]) -> None:
        if paths:
            plan.event("payload_nulls_resolved", paths=list(paths))

    submitted = submit_model_payload(
        store,
        plan.attempt.ticket_id,
        plan.step.step_id,
        result.content or "",
        on_normalised=resolved,
    )
    composed_event(plan.event, submitted)
    run.journal = submitted.journal
    run.status, run.issues = journal_outcome(store, plan.step.step_id, run.journal)
    plan.event("journal_result", outcome=run.status, issues=list(run.issues))


def composed_event(event: Callable[..., None], submitted: Submitted) -> None:
    """Record what Python composed from a submission: the retained review's hash, the items it
    added as explicit gaps and the issues that kept the payload from composing; for pre-filled
    bindings (task 7.0i), the paths Python set, their count and count per kind, and the retained
    payload's hash."""
    if submitted.prefilled:
        event(
            "payload_prefilled",
            paths=list(submitted.prefilled),
            count=len(submitted.prefilled),
            by_kind=dict(Counter(submitted.prefilled_kinds)),
            retained_payload_sha256=hashlib.sha256(submitted.payload.encode()).hexdigest(),
        )
    composition = submitted.composition
    if composition is None:
        return
    event(
        "submission_composed",
        composed=composition.review is not None and not composition.issues,
        retained_payload_sha256=hashlib.sha256(submitted.payload.encode()).hexdigest(),
        placeholders=list(composition.placeholders),
        composition_issues=list(composition.issues),
    )


def _cost(candidate: PinnedCandidate, result: ChatResult | None) -> _Cost:
    if result is None:
        return _Cost(None, "unknown", "no response received; reservation held as worst case")
    if result.usage.cost is not None:
        return _Cost(result.usage.cost, "provider-reported", "usage.cost")
    status = result.http_status
    if result.classification == "insufficient_credit" or (
        status is not None and 400 <= status < 500 and status != 408
    ):
        return _Cost(Decimal(0), "known-zero", f"HTTP {status} refused before inference")
    usage = result.usage
    if usage.prompt_tokens is not None and usage.completion_tokens is not None:
        failed = result.classification in {"http_error", "timeout"}
        if failed and status is not None and 200 <= status < 300:
            # A provider error inside a 200 (choices[0]) with tokens but no usage.cost: a failed
            # generation's charge is not its token price (probe-4 charged 0), so hold it.
            return _Cost(None, "unknown", "error inside a 200 without usage.cost; reservation held")
        estimate = (
            usage.prompt_tokens * candidate.prompt_price
            + usage.completion_tokens * candidate.completion_price
            + candidate.request_price
        )
        return _Cost(estimate, "estimate-from-tokens", "usage.cost absent; tokens x pinned price")
    return _Cost(None, "unknown", "usage and cost absent; reservation held as worst case")


def _nullable(name: str, value: object, reason: str) -> dict[str, object]:
    return {name: value} if value is not None else {name: None, f"{name}_reason": reason}


# Seals of attempts that never reached the provider: nothing was reserved in the ledger.
_UNSENT = frozenset({"ineligible", "refused"})


def _reserved(plan: _Plan, run: _Run) -> dict[str, object]:
    unsent = run.status in _UNSENT
    reason = f"nothing reserved: {run.status}, nothing was sent"
    return _nullable("reserved_usd", None if unsent else plan.reserve_usd, reason)


_NOT_RECEIVED = "not dispatched or no response received"


def _provider_usage(result: ChatResult | None) -> dict[str, object]:
    """The provider-reported usage; every unknown value is null with its reason."""
    usage = result.usage if result else None
    missing = usage.missing if usage else {}
    provider: dict[str, object] = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens"):
        value = getattr(usage, name, None)
        provider.update(_nullable(name, value, missing.get(name, _NOT_RECEIVED)))
    provider.update(
        _nullable(
            "cached_tokens",
            getattr(usage, "cached_tokens", None),
            missing.get("cached_tokens", _NOT_RECEIVED),
        )
    )
    provider.update(
        _nullable("cost_usd", usage.cost if usage else None, missing.get("cost", _NOT_RECEIVED))
    )
    return provider


def _ledger_block(cost: _Cost, settlement: Settlement | None) -> dict[str, Any]:
    return {
        "attempt_cost_usd": cost.amount,
        "cost_basis": cost.basis,
        "cost_reason": cost.reason,
        "charged_usd": settlement.charged if settlement else None,
        "unreconciled": settlement.unreconciled if settlement else None,
        "overrun": settlement.overrun if settlement else None,
    }


def _metrics(plan: _Plan, run: _Run, cost: _Cost) -> dict[str, Any]:
    result = run.result
    why = _NOT_RECEIVED
    return {
        "provider": _provider_usage(result),
        "local": {
            **_nullable("latency_s", result.latency_s if result else None, why),
            **_nullable("time_to_first_token_s", None, "request is not streamed"),
            **_nullable("tool_time_s", None, "no tools are offered"),
        },
        "estimate": {
            "prompt_tokens_upper_bound": plan.prompt_tokens,
            **_reserved(plan, run),
            "request_bytes": request_bytes(plan.chat.body()),
            "prompt_bytes_per_token_lower_bound": format(plan.bytes_per_token, "f"),
            "basis": (
                "ceil(request body UTF-8 bytes / prompt_bytes_per_token_lower_bound) plus "
                f"{TOKEN_OVERHEAD} fixed overhead tokens (decision 0008)"
            ),
        },
        "ledger": _ledger_block(cost, run.settlement),
        "validation": {"outcome": run.status, "issue_count": len(run.issues)},
        "repair_count": plan.attempt.number,
        "retries_on_this_ticket_step": plan.links["retry_of_attempt_id"] is not None,
    }


def _manifest(plan: _Plan, run: _Run) -> dict[str, Any]:
    result = run.result
    classification = result.classification if result else None
    verified = bool(result and result.identity_verified)
    return {
        "schema": "model-test-attempt/1",
        "experiment_id": plan.locator.experiment,
        "case_id": plan.locator.case,
        "attempt_id": plan.attempt_id,
        "model": plan.candidate.slug,
        "ticket_id": plan.attempt.ticket_id,
        "module_id": plan.step.module_id,
        "step_id": plan.step.step_id,
        "started_at": plan.started_at,
        "finished_at": plan.clock(),
        "cohort": COHORT,
        "pool_label": plan.pool_label,
        "status": run.status,
        "classification": classification,
        "poolable": classification in SUBMITTED and verified and run.status in POOLABLE_STATUSES,
        "error": run.error,
        "code": {"live_package_sha256": code_sha256()},
        "hashes": {
            **plan.hashes,
            "snapshot_sha256": plan.snapshot_sha256,
            "journal_inputs": {item.input_id: item.sha256 for item in plan.attempt.inputs},
        },
        "draw": plan.drawn.to_record(),
        "effort": plan.effort,
        "endpoint": CHAT_URL,
        "routing": {"allow_fallbacks": False, "require_parameters": True, "models": None},
        "tools": {"offered": False, "tool_choice": None},
        # Kept in the sent schema; strict-mode acceptance is not documented (live.schema).
        "schema_keywords_unverified": unverified_keywords(
            plan.chat.response_format["json_schema"]["schema"]
        ),
        # How the sent schema departs from the strict copy (task 2.11; Pydantic still validates).
        "schema_relaxations": schema_relaxations(plan.step.schema),
        "schema_relaxations_basis": RELAXATIONS_BASIS,
        "served": {
            "model": result.served_model if result else None,
            "provider": result.served_provider if result else None,
            "provider_request_id": result.provider_request_id if result else None,
            "identity_verified": verified,
        },
        "budgets": {
            "cap_usd": plan.ledger_cap,
            "max_tokens": plan.step.max_tokens,
            **_reserved(plan, run),
            "timeout_s": plan.step.timeout_s,  # each socket operation
            "deadline_s": plan.step.timeout_s,  # the whole call, wall clock (task 2.10)
        },
        "pinned_candidate": plan.candidate.to_record(),
        "links": plan.links,
        "validator": {"outcome": run.status, "issues": list(run.issues)},
        "retries": _retries_record(plan, run),
        "credential": {
            "recorded": False,
            "response_scrubbed": bool(result and result.redacted),
            **plan.key_note,
        },
        "credit": run.credit.to_record() if run.credit else None,
    }


def _seal(plan: _Plan, writer: AttemptWriter, run: _Run, cost: _Cost) -> Path:
    checks: dict[str, Any] = {"validator": {"outcome": run.status, "issues": list(run.issues)}}
    if run.result is not None:
        checks["classification"] = {
            "classification": run.result.classification,
            "finish_reason": run.result.finish_reason,
            "identity_verified": run.result.identity_verified,
            "error_detail": run.result.error_detail,
        }
    # The client scrubs the provider body (and so the content) before the writer sees it.
    upstream = ["response.json", "output.md"] if run.result and run.result.redacted else []
    return writer.seal(
        plan.locator,
        _manifest(plan, run),
        plan.events,
        _metrics(plan, run, cost),
        checks,
        scrubbed_upstream=upstream,
    )


def _close(plan: _Plan, ledger: Ledger, writer: AttemptWriter, run: _Run, key: str) -> None:
    if run.failure is not None:
        run.status = "interrupted"
        run.error = redact(f"{type(run.failure).__name__}: {run.failure}", key)
        plan.event("interrupted", error=run.error)
    if not run.response_staged:
        _record_response(plan, writer, run)
    cost = _cost(plan.candidate, run.result)
    try:
        reason = f"{cost.reason}; status={run.status}"
        # `_plan` counts no try for either (`in_flight_refused`); only the wording differs.
        if _re_sent(run):
            reason += IN_FLIGHT_SETTLE_MARK
        elif run.credit is not None and run.credit.transient:
            reason += IN_FLIGHT_EXHAUSTED_MARK
        run.settlement = ledger.settle(plan.attempt_id, cost.amount, reason)
        plan.event("ledger_settled", charged=run.settlement.charged, basis=cost.basis)
    finally:
        run.directory = _seal(plan, writer, run, cost)


def _retain_unsent(plan: _Plan, writer: AttemptWriter, status: str, reason: str) -> Path:
    """Seal an attempt that never reached the provider (refused or ineligible)."""
    run = _Run(status=status, error=reason)
    plan.event(status, reason=reason)
    _record_response(plan, writer, run)
    cost = _Cost(None, "not-dispatched", f"{status}; nothing was sent")
    return _seal(plan, writer, run, cost)


def dispatch(
    step: StepSpec,
    *,
    store: Execution,
    ticket_id: str,
    ledger: Ledger,
    pool: PinnedPool,
    seed: int,
    client: ChatClient,
    writer: AttemptWriter,
    key_path: Path,
    key_index: int,
    bytes_per_token: Decimal,
    effort: str,
    clock: Callable[[], str] = utc_stamp,
    max_retries: int = DEFAULT_MAX_RETRIES,
    credit: CreditState | None = None,
    schema_rejections: Mapping[tuple[str, str, str], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_in_flight: Callable[[DispatchResult], None] | None = None,
) -> DispatchResult:
    """Run one attempt of `step` on the model drawn from `pool` with `seed`.

    Retries on a pending ticket are bounded by `max_retries`; see `DispatchResult`.
    `schema_rejections` (from `schema_rejections(artifact_root)`) holds the (model, step, sent
    schema sha256) cells a `live schema-check` saw refused; such a step is sealed ineligible
    before anything is reserved or sent (task 2.11).
    Credit exhaustion (a 402, or a `credit` state already known to be exhausted) raises
    CreditExhausted; the runner never switches model or cohort on its own (DC-8).
    An in-flight 402 (task 7.8) is the one exception: once that attempt is sealed and settled
    (at zero), `sleep(in_flight_wait_s(...))` and the step is re-sent once on the same drawn
    model, reserved anew under the same cap. The refused attempt uses up no `max_retries` try
    (`in_flight_refused`), so the re-send is the same model try, also on the last one. Its
    manifest names the refused try (`links.in_flight_retry_of_attempt_id`). A second in-flight
    402 is exhaustion. `on_in_flight` receives the sealed refused attempt before the wait, so a
    caller can report it whatever the re-send then does (raises included).
    `key_index` is `[model_tests].credential_token_index`; a refused key (401) is never retried
    with another token from the file. `bytes_per_token` is
    `[model_tests].prompt_bytes_per_token_lower_bound` (the reservation's prompt bound). Both are
    required: the settings are the one source of truth, so there is no default here.
    """
    if credit is not None and credit.exhausted is True:
        raise CreditExhausted(credit, ticket_id)
    send = partial(
        _dispatch_once,
        step,
        store=store,
        ticket_id=ticket_id,
        ledger=ledger,
        pool=pool,
        seed=seed,
        client=client,
        writer=writer,
        key_path=key_path,
        key_index=key_index,
        bytes_per_token=bytes_per_token,
        effort=effort,
        clock=clock,
        max_retries=max_retries,
        schema_rejections=schema_rejections,
    )
    first = send(None)
    if first.in_flight is None:
        return first
    if on_in_flight is not None:
        on_in_flight(first)
    waited = in_flight_wait_s(first.in_flight)
    sleep(waited)
    # The re-send raises CreditExhausted on any further in-flight 402 (`_refusal`).
    return replace(send((first.attempt_id, waited)), retried=first)


def _dispatch_once(
    step: StepSpec,
    in_flight_of: tuple[str, int] | None,
    *,
    store: Execution,
    ticket_id: str,
    ledger: Ledger,
    pool: PinnedPool,
    seed: int,
    client: ChatClient,
    writer: AttemptWriter,
    key_path: Path,
    key_index: int,
    bytes_per_token: Decimal,
    effort: str,
    clock: Callable[[], str],
    max_retries: int,
    schema_rejections: Mapping[tuple[str, str, str], str] | None,
) -> DispatchResult:
    """One attempt of `dispatch`; `in_flight_of` is (the refused try, the wait) on a re-send."""
    plan = _plan(
        step,
        store,
        ticket_id,
        ledger,
        pool,
        seed,
        writer,
        effort,
        clock,
        max_retries,
        bytes_per_token,
    )
    rejected = (schema_rejections or {}).get(
        (plan.candidate.slug, step.step_id, plan.hashes["schema_sha256"])
    )
    if plan.misfit is None and rejected is not None:
        plan.misfit = f"schema rejected by provider ({rejected})"
    loaded = load_key_with_note(key_path, key_index)
    key = loaded.key
    if loaded.tokens_found > 1:
        plan.key_note = loaded.note()
    writer.begin(
        plan.locator, _request_record(plan)
    )  # the exact request is retained before sending
    plan.event("drawn", draw=plan.drawn.to_record(), effort=plan.effort)
    if in_flight_of is not None:
        retry_of, waited = in_flight_of
        plan.links["in_flight_retry_of_attempt_id"] = retry_of
        plan.in_flight_waited_s = waited
        plan.event("in_flight_retry", retry_of=retry_of, waited_s=waited)
    if plan.attempt.repair_of is not None or plan.step_try == 2:
        plan.event("repair_prompt", **plan.repair.to_record())
    if plan.misfit is not None:
        reason = f"ineligible: {plan.misfit}"
        return DispatchResult(
            attempt_id=plan.attempt_id,
            status="ineligible",
            classification=reason,
            draw=plan.drawn,
            effort=plan.effort,
            directory=_retain_unsent(plan, writer, "ineligible", reason),
            journal=None,
            settlement=None,
            cost_usd=Decimal(0),
            issues=(),
            prompt_tokens_upper_bound=plan.prompt_tokens,
            attempt_pending=True,  # nothing was sent, so the journal was not touched
            step_try=plan.step_try,
        )
    try:
        ledger.reserve(plan.attempt_id, plan.reserve_usd)
    except CapExceeded as error:
        _retain_unsent(plan, writer, "refused", str(error))
        raise
    plan.event("reserved", usd=plan.reserve_usd, prompt_tokens_upper_bound=plan.prompt_tokens)
    run = _Run()
    try:
        plan.event("request_sent", model=plan.candidate.slug)
        run.result = client.complete(plan.chat, key=key)
        plan.event(
            "response_received",
            classification=run.result.classification,
            http_status=run.result.http_status,
            latency_s=run.result.latency_s,
        )
        _record_response(plan, writer, run)
        _submit(plan, store, run)
    except BaseException as error:
        run.failure = error
        if isinstance(error, TransportError):
            _interrupt_if_exhausted(plan, store, run, "connection failure")
        raise
    finally:
        _close(plan, ledger, writer, run, key)
    assert run.directory is not None
    # Only a retryable in-flight refusal (exhausted unknown) returns; every other 402 raises.
    if run.credit is not None and run.credit.exhausted is not None:
        raise CreditExhausted(run.credit, ticket_id)
    return DispatchResult(
        attempt_id=plan.attempt_id,
        status=run.status,
        classification=run.result.classification if run.result else None,
        draw=plan.drawn,
        effort=plan.effort,
        directory=run.directory,
        journal=run.journal,
        settlement=run.settlement,
        cost_usd=run.settlement.charged if run.settlement else None,
        issues=run.issues,
        ticket_interrupted=run.ticket_interrupted,
        prompt_tokens_upper_bound=plan.prompt_tokens,
        attempt_pending=_pending(store, ticket_id),
        step_try=plan.step_try,
        in_flight=run.credit,
    )
