"""One step as a tool loop (task 8.0d): the hybrid harness ported into the live runner.

User decision, 24 Oct 2026: E1 runs the CP-1 stages the way `devtools/hybrid_cp1.py` did. A
tool-loop step (`registry.tool_loop_steps`) is one conversation with the drawn model on the
OpenRouter path (`ChatClient`, `tools` with `tool_choice: required`, no `response_format`). Its
prompt is the runner's (`prompts.build`: the step's upstream projections and any REPAIR block)
with rule 5 naming the tools, and no pack SOURCE block. The tools are `search_pack`,
`read_pages` (`live.tools.PackTools`, read-only over the prepared pack) and `submit_<step>`.

Task 8.9 (user decision, 24 Oct 2026: every live step of every module is a tool loop): the
registry's tool set decides the tools (`registry.tool_sets`). A `pack` step gets the two pack
tools, bounded to its declared sources where it has a source scope (CP-4's legal, CP-3's market
sources: `live.context.readable_sources`), so the whole legal source is read on demand rather
than pre-sent. A `submit-only` step (CP-1 `quality`, CP-2, CP-5, CP-6) gets its submit alone;
a call to any other tool is refused as a tool result and never run. Every step's prompt is
built from the one-shot dispatch's inputs (`runner.prompt_inputs`: the upstream projections,
CP-1A's facts, the `MODULE_CONTEXTS` CONTEXT, the QA or review scope) less its pack SOURCE
blocks, with rule 5 naming the step's tools.

Order within a call: the request is retained, the call reserved (`reservation_usd` of the call's
own growing body at `ToolLimits.max_tokens`), sent, the tools run, the reply retained, then the
call is settled (`runner._cost`: `usage.cost`, else known zero for a refusal before inference,
else the whole reservation held) and sealed. Every call is its own attempt directory and ledger
attempt (`<ticket>-<step>-<n>`; in the step's repair `<ticket>-<step>-repair-<n>`), the shape the
reconcile paths of tasks 7.11, 7.13 and 7.14 read, so an interrupted call is reconciled as any
interrupted attempt. Each sent call also keeps its tool transcript (`tool-calls.jsonl`). A step
whose first call is already reserved or retained is never run again (`_started`).

Limits per step (`ToolLimits`, the harness's): 30 calls, 3 submits, 3,600 s of wall clock and
128,000 output tokens per call; a call may use the rest of the step's wall clock. From three
calls left, each turn's tool results are followed by a Python-owned user message saying so
(harness review C6: never inside tool or pack text). A transport, timeout or stream failure
(`transient`) is retried once: the failed call is recorded and settled, the retry is a new call
within the same budgets and is never a submit; a second failure in a row ends the step. An
in-flight 402 is waited out and re-sent once per step, as `runner.dispatch` does (task 7.8); any
other 402 raises CreditExhausted once the call is sealed.

Judging: every submit is judged as the step's current try on the runner's trusted path
(`submission.submit_model_payload`, then `runner.journal_outcome`) in a scratch copy of the
step's starting journal, with the step's evidence rules (`live.tools.ToolRules`) evaluated on
what the model had been shown when it submitted. When the step ends, the live journal receives
its last judged submit (the accepted one, or the last rejected one) through the same function
and rules; its verdict must equal the scratch verdict, else the loop raises. The journal's own
budget (one within-attempt repair per step, MC-7) is therefore unchanged: the CLI runs a
rejected step's repair as a second tool loop with the REPAIR block. Each submit stays in the
call that made it: `output.md` holds its payload, `checks/validator.json` its verdict.

Effort: the step's row of the settings table (`LiveSettings.step_effort`), or the model's own
`--models ID@EFFORT`. After two rejected submits or a completeness-floor rejection, later calls
of the step are sent one level higher, never above the row's ceiling (`StepEffort.escalated`).
The effort sent is recorded on every call.
"""

import hashlib
import json
import re
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

from deploy_vii.execution import Attempt, Execution
from deploy_vii.live.catalog import EffortDecision, PinnedCandidate, PinnedPool
from deploy_vii.live.client import CHAT_URL, ChatClient, ChatRequest, ChatResult, TransportError
from deploy_vii.live.context import SOURCE_SCOPES, readable_sources
from deploy_vii.live.credential import load_key_with_note, redact
from deploy_vii.live.credit import CreditExhausted, CreditState, from_dispatch_402
from deploy_vii.live.draw import Draw, draw
from deploy_vii.live.ledger import CapExceeded, Ledger, Settlement, utc_stamp
from deploy_vii.live.prompts import TOOL_LOOP_SUBMITS, PromptError, build, schema_text
from deploy_vii.live.retention import (
    TOOL_TRANSCRIPT,
    AttemptLocator,
    AttemptWriter,
    response_envelope,
)
from deploy_vii.live.runner import (
    COHORT,
    IN_FLIGHT_EXHAUSTED_MARK,
    IN_FLIGHT_SETTLE_MARK,
    POOLABLE_STATUSES,
    SUBMITTED,
    TOKEN_OVERHEAD,
    StepSpec,
    _Cost,
    _cost,
    _ledger_block,
    _nullable,
    _pending,
    _provider_usage,
    code_sha256,
    composed_event,
    expected_step,
    in_flight_wait_s,
    journal_outcome,
    prompt_inputs,
    prompt_token_bound,
    repair_prompt,
    request_bytes,
    reservation_usd,
    step_repair_of,
    step_try,
)
from deploy_vii.live.schema_check import schema_shaped
from deploy_vii.live.settings import EFFORT_LADDER, StepEffort
from deploy_vii.live.submission import submit_model_payload
from deploy_vii.live.tools import (
    INCOMPLETE,
    READ,
    SEARCH,
    TOOL_CHOICE,
    PackTools,
    Seen,
    ToolError,
    ToolRules,
    cited_locators,
    completeness,
    completeness_drop,
    evidence_counts,
    shrinkage,
    submit_name,
    tool_specs,
)
from deploy_vii.registry import PACK_TOOLS, ToolSet, tool_loop_steps, tool_set
from deploy_vii.source_context import SourceContextReview

TOOL_STEPS = tool_loop_steps()
NOT_RUN = "not run"
NO_SUBMIT = "no-submit"  # a step status: the step ended without a judged submit
LIMIT = "rejected: limit"
_NUMBER = re.compile(r"\b[0-9]+\b")
# Verdicts whose call may have used the step's whole deadline (the harness's `timed_out`).
_TIMED_OUT = frozenset({"no-response: timeout"})


@dataclass(frozen=True)
class ToolLimits:
    """A tool-loop step's limits (the hybrid harness's, `devtools/hybrid_cp1.py`)."""

    max_calls: int = 30
    max_submits: int = TOOL_LOOP_SUBMITS
    deadline_s: float = 3600.0
    max_tokens: int = 128_000  # each request's `max_tokens`
    nudge_from_calls_left: int = 3

    def __post_init__(self) -> None:
        if min(self.max_calls, self.max_submits, self.max_tokens) < 1 or self.deadline_s <= 0:
            raise ValueError("tool-loop limits must be positive")
        if self.nudge_from_calls_left < 0:
            raise ValueError("the nudge threshold cannot be negative")


LIMITS = ToolLimits()


def call_nudge(left: int, step_id: str, max_calls: int) -> str:
    """The note the loop sends as its own user message when few calls remain (the harness's
    words; the harness appended them to the last tool result, which review C6 refused)."""
    return (
        f"Harness: {left} of {max_calls} calls remain in this step; "
        f"the step must end with {submit_name(step_id)}."
    )


def issue_class(issue: str) -> str:
    """The issue's kind: the text before its first colon, with list indices as N."""
    return _NUMBER.sub("N", issue.split(":", 1)[0])


def transient(result: ChatResult | None) -> bool:
    """A failure the loop retries once (task 8.0d item 10): no reply at all (a connection
    failure), a timeout, or an HTTP error that is not a refusal before inference: a 5xx (batch
    hybrid-cp1-4's "HTTP 502: Stream ended before a terminal response event"), a 408, or an error
    inside a 200."""
    if result is None or result.classification == "timeout":
        return True
    if result.classification != "http_error":
        return False
    status = result.http_status
    return status is None or status >= 500 or status == 408 or 200 <= status < 300


@dataclass(frozen=True)
class Submit:
    """One judged submit: where it was made, what the model had been shown, its verdict."""

    number: int
    call: int
    attempt_id: str
    payload: str
    seen: Seen
    outcome: str
    issues: tuple[str, ...]
    effort_sent: str | None

    def record(self, step_id: str) -> dict[str, Any]:
        return {
            "submit": self.number,
            "call": self.call,
            "attempt_id": self.attempt_id,
            "outcome": self.outcome,
            "issues": list(self.issues),
            "issue_classes": dict(Counter(map(issue_class, self.issues))),
            "completeness_floor_failed": any(i.startswith(INCOMPLETE) for i in self.issues),
            "counts": evidence_counts(self.payload),
            "payload_sha256": hashlib.sha256(self.payload.encode()).hexdigest(),
            "effort_sent": self.effort_sent,
            **({"completeness": completeness(self.payload)} if step_id == "financials" else {}),
        }


@dataclass
class Call:
    """One call of the loop and what it left."""

    number: int
    attempt_id: str
    locator: AttemptLocator
    chat: ChatRequest
    bound: int
    reserve: Decimal
    effort: EffortDecision
    level: str
    started_at: str
    retry_of: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    result: ChatResult | None = None
    error: str | None = None
    failure: BaseException | None = None
    settlement: Settlement | None = None
    cost: _Cost | None = None
    status: str = "interrupted"
    output: str | None = None
    issues: tuple[str, ...] = ()
    credit: CreditState | None = None
    responded: bool = False
    nudged: bool = False
    tool_time_s: float = 0.0
    sent: bool = False
    not_re_sent: bool = False  # an in-flight 402 no call could follow (review A item 6)
    transcript_sha256: str | None = None  # of tool-calls.jsonl as written
    clock: Callable[[], str] = utc_stamp

    def event(self, name: str, **fields: object) -> None:
        self.events.append(
            {"seq": len(self.events) + 1, "at": self.clock(), "event": name, **fields}
        )


@dataclass(frozen=True)
class ToolStepResult:
    """A tool-loop step's outcome, in the terms `cli` reads from `runner.DispatchResult`.

    `status`: accepted or rejected (the live journal's verdict on the step's last judged
    submit), no-submit (no submit was judged), no-response (no usable reply, a provider schema
    error included), withheld-fallback, or ineligible (nothing sent). `verdict` is the harness's
    wording of how the step ended. `attempt_id` is the call that made the last judged submit
    (else the last call); `cost_usd` sums every call's settled charge, `held_usd` is the part
    of it held at a reservation, and `held` says whether any call held its reservation."""

    step_id: str
    attempt_id: str
    attempt_ids: tuple[str, ...]
    status: str
    verdict: str
    verdict_reason: str | None
    classification: str | None
    draw: Draw
    effort: Mapping[str, Any]
    directory: Path
    journal: Attempt | None
    cost_usd: Decimal
    held_usd: Decimal
    held: bool
    issues: tuple[str, ...]
    attempt_pending: bool
    step_try: int
    prompt_tokens_upper_bound: int
    submits: tuple[Mapping[str, Any], ...]


@dataclass
class _Context:
    """What the loop needs besides the step: where it writes, spends and sends."""

    ledger: Ledger
    writer: AttemptWriter
    client: ChatClient
    key: str = field(repr=False)
    bytes_per_token: Decimal
    clock: Callable[[], str]
    monotonic: Callable[[], float]


@dataclass
class _Step:
    spec: StepSpec
    store: Execution
    attempt: Attempt
    snapshot_sha256: str
    batch_id: str
    pool_label: str
    drawn: Draw
    candidate: PinnedCandidate
    plan: StepEffort
    rules: ToolRules
    limits: ToolLimits
    kind: ToolSet
    tools: PackTools | None  # None: a submit-only step reads nothing (task 8.9)
    specs: tuple[dict[str, Any], ...]
    context: SourceContextReview | None
    quality_inputs_sha256: str | None
    conversation: list[dict[str, Any]]
    prefix: str
    current_try: int
    links: dict[str, str | None]
    prompt_sha256: str
    repair: dict[str, Any]
    lacking: tuple[str, ...]
    key_note: dict[str, int] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)
    submits: list[Submit] = field(default_factory=list)
    verdict: str = NOT_RUN
    verdict_reason: str | None = None
    escalated: str | None = None  # why later calls go one level higher
    retry_pending: bool = False  # the last call failed transiently; the next call retries it
    in_flight_used: bool = False
    wait_s: int | None = None  # the wait before an in-flight re-send
    counts: Counter[str] = field(default_factory=Counter)
    journal: Attempt | None = None  # the live journal after the step's last judged submit
    started: float = 0.0

    @property
    def step_id(self) -> str:
        return self.spec.step_id

    def level(self) -> str:
        return self.plan.escalated() if self.escalated else self.plan.effort


def _rank(effort: str) -> int:
    if effort not in EFFORT_LADDER:
        raise ValueError(f"effort {effort!r} is not one of {', '.join(EFFORT_LADDER)}")
    return EFFORT_LADDER.index(effort)


def _started(ledger: Ledger, writer: AttemptWriter, base: AttemptLocator) -> bool:
    """Whether this ticket step's loop already reserved or retained a call."""
    first = f"{base.attempt}-1"
    used = {item.attempt_id for item in ledger.state().attempts}
    return first in used or writer.path_for(replace(base, attempt=first)).exists()


def _prepare(
    spec: StepSpec,
    store: Execution,
    ticket_id: str,
    ledger: Ledger,
    pool: PinnedPool,
    seed: int,
    writer: AttemptWriter,
    effort: StepEffort,
    rules: ToolRules,
    limits: ToolLimits,
) -> _Step:
    """Everything fixed before anything is spent: the draw, effort plan, prompt and tools."""
    if spec.step_id not in TOOL_STEPS:
        raise ValueError(f"{spec.step_id} is not a tool-loop step")
    if spec.declared_sources:
        raise ValueError("a tool-loop step declares no pack SOURCE inputs; it reads by tool")
    snapshot = store.read()
    attempt = next((item for item in snapshot.attempts if item.ticket_id == ticket_id), None)
    if attempt is None:
        raise ValueError("unknown ticket")
    if expected_step(attempt, spec.module_id) != spec.step_id:
        raise ValueError(f"{spec.step_id} is not the next step for this ticket")
    drawn = draw(pool, seed)
    candidate = pool.candidate(drawn.slug)
    start = candidate.requested_effort or effort.effort
    plan = StepEffort.of(start, max(effort.ceiling, start, key=_rank))
    current = step_try(attempt, spec.step_id)
    first_try = f"{ticket_id}-{spec.step_id}"
    prefix = first_try if current == 1 else f"{first_try}-repair"
    if _started(ledger, writer, AttemptLocator(pool.batch_id, spec.case_id, drawn.slug, prefix)):
        raise ValueError(f"{prefix} already started; a started tool-loop step is never re-run")
    repair = repair_prompt(snapshot, attempt, spec.step_id)
    pack = store.pack(snapshot)
    # Task 8.9: the same prompt inputs as the one-shot dispatch (`runner.prompt_inputs`: the
    # upstream projections, CP-1A's facts, the module CONTEXT, the QA or review scope), the
    # step's tool set, and for a pack-tool step with a source scope (CP-4, CP-3) its readable
    # sources, which bound the pack tools too.
    kind = tool_set(spec.step_id)
    inputs = prompt_inputs(store, attempt, spec.step_id)
    scoped = kind == PACK_TOOLS and spec.step_id in SOURCE_SCOPES
    readable = readable_sources(store, attempt, spec.step_id) if scoped else None
    messages = [
        item.as_dict()
        for item in build(
            spec.step_id,
            pack,
            (),
            spec.schema,
            upstream=inputs.upstream,
            repair_issues=repair.issues,
            cp1_facts=inputs.cp1_facts,
            module_context=inputs.module_context,
            scope=inputs.scope,
            submit_tool=submit_name(spec.step_id),
            submits=limits.max_submits,  # the prompt states the loop's own limit
            tool_set=kind,
            readable=readable,
        )
    ]
    context = None
    if spec.step_id == "financials":  # the floor's expected cells (`tools.expected_cells`)
        context = SourceContextReview.model_validate_json(
            store.payload(attempt.steps[0].payload_sha256)
        )
    known = [item.attempt_id for item in ledger.state().attempts]
    repair_of = attempt.repair_of
    return _Step(
        spec=spec,
        store=store,
        attempt=attempt,
        snapshot_sha256=snapshot.content_hash(),
        batch_id=pool.batch_id,
        pool_label=pool.pool_label,
        drawn=drawn,
        candidate=candidate,
        plan=plan,
        rules=rules,
        limits=limits,
        kind=kind,
        tools=PackTools(pack, readable) if kind == PACK_TOOLS else None,
        specs=tool_specs(spec.step_id, kind),
        context=context,
        quality_inputs_sha256=inputs.quality_inputs_sha256,
        conversation=messages,
        prefix=prefix,
        current_try=current,
        links={
            "repair_of_ticket_id": repair_of,
            "repair_of_attempt_id": next(
                (n for n in reversed(known) if repair_of and n.startswith(repair_of + "-")),
                None,
            ),
            # The rejected first try's last call; its issues are this loop's REPAIR block.
            "step_repair_of_attempt_id": (
                step_repair_of(known, ticket_id, spec.step_id) if current == 2 else None
            ),
        },
        prompt_sha256=hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest(),
        repair=repair.to_record(),
        lacking=tuple(
            p for p in ("tools", "tool_choice") if p not in candidate.supported_parameters
        ),
    )


def _decision(candidate: PinnedCandidate, level: str) -> EffortDecision:
    """The catalog's verdict on sending `level` (the step's plan decides the level)."""
    return replace(candidate, requested_effort=None).effort_for(level)


def _new_call(step: _Step, ctx: _Context, elapsed: float) -> Call:
    """The next call, timed out at the rest of the step's wall clock as the loop head measured
    it (`elapsed` < the deadline there; review A item 4: no second clock read)."""
    number = len(step.calls) + 1
    attempt_id = f"{step.prefix}-{number}"
    level = step.level()
    decision = _decision(step.candidate, level)
    chat = ChatRequest(
        model=step.candidate.slug,
        messages=tuple(step.conversation),
        max_tokens=step.limits.max_tokens,
        response_format={},
        reasoning_effort=decision.sent,
        accepted_model_ids=(step.candidate.slug, step.candidate.canonical_slug),
        timeout_s=step.limits.deadline_s - elapsed,  # the rest of the step's wall clock
        tools=step.specs,
        tool_choice=TOOL_CHOICE,
    )
    bound = prompt_token_bound(chat.body(), ctx.bytes_per_token)
    previous = step.calls[-1].attempt_id if step.calls else None
    return Call(
        number=number,
        attempt_id=attempt_id,
        locator=AttemptLocator(step.batch_id, step.spec.case_id, step.candidate.slug, attempt_id),
        chat=chat,
        bound=bound,
        reserve=reservation_usd(step.candidate, bound, step.limits.max_tokens),
        effort=decision,
        level=level,
        started_at=ctx.clock(),
        retry_of=previous if step.retry_pending else None,
        clock=ctx.clock,
    )


def _request_record(step: _Step, call: Call, ctx: _Context) -> dict[str, Any]:
    return {
        "endpoint": CHAT_URL,
        "method": "POST",
        "body": call.chat.body(),
        "non_secret_parameters": {
            "timeout_s": call.chat.timeout_s,
            "accepted_model_ids": list(call.chat.accepted_model_ids),
            "prompt_tokens_upper_bound": call.bound,
            "prompt_bytes_per_token_lower_bound": format(ctx.bytes_per_token, "f"),
        },
        "selection": {"draw": step.drawn.to_record(), "effort": call.effort.to_record()},
        "authentication": "Authorization header omitted; the credential is never recorded",
        "tool_loop": {
            "call": call.number,
            "first_call_attempt_id": f"{step.prefix}-1",
            "retry_of_attempt_id": call.retry_of,
            "effort_level": call.level,
            "effort_plan": {"effort": step.plan.effort, "ceiling": step.plan.ceiling},
            "limits": asdict(step.limits),
        },
    }


def run_tool_step(
    spec: StepSpec,
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
    effort: StepEffort,
    rules: ToolRules,
    limits: ToolLimits = LIMITS,
    clock: Callable[[], str] = utc_stamp,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_stop: Callable[[ToolStepResult], None] | None = None,
) -> ToolStepResult:
    """Run `spec` as a tool loop on the model drawn from `pool` with `seed` (see the module
    docstring). A cap refusal raises CapExceeded and an exhausted credit CreditExhausted, each
    after the call is sealed; nothing else is raised for a provider's answer. When anything is
    raised after a call was sealed, `on_stop` first receives the step's result so far (so a
    caller's report keeps the calls already spent). On exhausted credit the step has ended, so
    its last judged submit, if any, is already in the live journal; on a cap refusal or any
    other raise mid-step the live journal is untouched (the submits were judged in scratch only)
    and the ticket stays pending, with this try started and never re-run (`_started`)."""
    step = _prepare(spec, store, ticket_id, ledger, pool, seed, writer, effort, rules, limits)
    loaded = load_key_with_note(key_path, key_index)
    if loaded.tokens_found > 1:
        step.key_note = loaded.note()
    ctx = _Context(ledger, writer, client, loaded.key, bytes_per_token, clock, monotonic)
    step.started = monotonic()
    try:
        while step.verdict == NOT_RUN:
            elapsed = monotonic() - step.started
            if len(step.calls) >= limits.max_calls or elapsed >= limits.deadline_s:
                step.verdict = LIMIT
                step.verdict_reason = f"{len(step.calls)} calls, {elapsed:.1f} s"
                break
            _call(step, ctx, elapsed)
            if step.wait_s is not None:
                sleep(step.wait_s)
                step.wait_s = None
    except BaseException:
        if on_stop is not None and step.calls:
            on_stop(_result(step, ctx))
        raise
    return _result(step, ctx)


def _call(step: _Step, ctx: _Context, elapsed: float) -> None:
    call = _new_call(step, ctx, elapsed)
    ctx.writer.begin(call.locator, _request_record(step, call, ctx))
    call.event("drawn", draw=step.drawn.to_record(), effort=call.effort.to_record())
    if call.retry_of is not None:
        call.event("transient_retry", retry_of=call.retry_of)
    if call.number == 1 and (step.attempt.repair_of is not None or step.current_try == 2):
        call.event("repair_prompt", **step.repair)
    step.calls.append(call)
    misfit = (
        f"the route lacks {', '.join(step.lacking)}"
        if step.lacking
        else step.candidate.misfit(call.bound, step.limits.max_tokens)
    )
    if misfit is not None:
        step.verdict, step.verdict_reason = "not sent: misfit", misfit
        _seal_unsent(step, call, ctx, "ineligible", f"ineligible: {misfit}")
        return
    try:
        ctx.ledger.reserve(call.attempt_id, call.reserve)
    except CapExceeded as error:
        step.verdict, step.verdict_reason = "stopped: cap", str(error)
        _seal_unsent(step, call, ctx, "refused", str(error))
        raise
    call.event("reserved", usd=call.reserve, prompt_tokens_upper_bound=call.bound)
    call.sent = True
    try:
        call.event("request_sent", model=step.candidate.slug, effort_sent=call.effort.sent)
        try:
            call.result = ctx.client.complete(call.chat, key=ctx.key)
        except TransportError as error:  # the client scrubbed the key from the message
            call.error = str(error)
            call.event("transport_error", error=call.error)
        else:
            result = call.result
            call.event(
                "response_received",
                classification=result.classification,
                http_status=result.http_status,
                latency_s=result.latency_s,
                tool_calls=len(result.tool_calls),
            )
        _reply(step, call, ctx)
        _record_response(call, ctx)
        _after(step, call, ctx)
    except BaseException as error:
        call.failure = error
        try:
            _close(step, call, ctx)
        except BaseException as closing:  # review A item 1: never hide the original failure
            raise closing from error
        raise
    _close(step, call, ctx)
    if call.credit is not None and call.credit.exhausted is not None:
        raise CreditExhausted(call.credit, step.attempt.ticket_id)


def _reply(step: _Step, call: Call, ctx: _Context) -> None:
    result = call.result
    if result is None or result.classification != "ok":
        _failure(step, call, ctx)
        return
    step.retry_pending = False
    if not result.tool_calls:
        step.verdict = "rejected: no-submit"
        step.verdict_reason = f"stop reason {result.finish_reason}; no tool call"
        call.status, call.output = NO_SUBMIT, result.content
        return
    call.status = "tools"
    _turn(step, call, ctx)


def _failure(step: _Step, call: Call, ctx: _Context) -> None:
    """A call without a usable reply: retried once when transient, else the step ends."""
    result = call.result
    detail = call.error or (result.error_detail if result else None)
    cls = result.classification if result else "transport_error"
    call.status = "withheld-fallback" if cls == "fallback" else "no-response"
    call.output = result.content if result else None
    if result is not None and schema_shaped(result):
        step.verdict, step.verdict_reason = "provider-schema-error", detail
        return
    if result is not None and cls == "insufficient_credit":
        _refused(step, call, result, ctx)
        return
    if transient(result) and call.retry_of is None:
        step.retry_pending = True
        call.event("transient_failure", classification=cls, detail=detail, retried=True)
        return
    step.retry_pending = False
    step.verdict = "withheld-fallback" if cls == "fallback" else f"no-response: {cls}"
    step.verdict_reason = detail


def _refused(step: _Step, call: Call, result: ChatResult, ctx: _Context) -> None:
    """A 402 as its body reads (task 7.8): one in-flight refusal per step is waited out and
    re-sent; a second, or any other 402, is exhaustion (raised once the call is sealed)."""
    state = from_dispatch_402(ctx.clock(), result.http_status, result.raw, result.retry_after)
    if state.transient and step.in_flight_used:
        state = replace(
            state,
            exhausted=True,
            detail=f"{state.detail} on {call.attempt_id}, in flight again after one re-send in "
            "this step: treated as exhaustion",
        )
    call.credit = state
    if state.transient and state.exhausted is None:
        step.in_flight_used = True
        step.wait_s = in_flight_wait_s(state)
        call.event("credit_in_flight_refusal", **state.to_record(), wait_s=step.wait_s)
        return
    step.verdict, step.verdict_reason = "no-response: insufficient_credit", state.detail
    call.event("credit_exhausted", **state.to_record())


def _turn(step: _Step, call: Call, ctx: _Context) -> None:
    """The model's tool calls, in order: the assistant turn joins the conversation unmodified,
    each tool runs (none after the step's verdict is final), each result follows as a `tool`
    message, then the nudge as a user message when few calls remain."""
    result = call.result
    assert result is not None and result.message is not None
    step.conversation.append(dict(result.message))
    results: list[tuple[str, str]] = []
    for index, tool_call in enumerate(result.tool_calls, 1):
        entry: dict[str, Any] = {"call": call.number, "index": index, **asdict(tool_call)}
        # A final verdict (an accepted or the last allowed submit) stands: any later call of the
        # turn, a malformed one included, is only noted (review A item 5).
        if step.verdict != NOT_RUN:
            call.transcript.append(entry | {"status": "not executed: the step has a final verdict"})
            continue
        if tool_call.problem is not None:
            step.verdict, step.verdict_reason = "rejected: malformed tool call", tool_call.problem
            call.transcript.append(entry | {"status": "error"})
            return
        started = ctx.monotonic()
        status, text, verdict = _execute(step, call, tool_call.name, tool_call.arguments)
        duration = ctx.monotonic() - started
        call.tool_time_s += duration
        if status != "error":
            step.counts[tool_call.name] += 1
            call.counts[tool_call.name] += 1
        call.transcript.append(entry | {"status": status, "result": text, "duration_s": duration})
        if verdict is not None:
            call.transcript[-1] |= verdict
        call.event("tool_executed", index=index, tool=tool_call.name, status=status)
        results.append((tool_call.call_id, text))
        submitted = len(step.submits) >= step.limits.max_submits
        if status == "accepted" or (status == "rejected" and submitted):
            step.verdict = status
    step.conversation.extend(
        {"role": "tool", "tool_call_id": ident, "content": text} for ident, text in results
    )
    left = step.limits.max_calls - call.number
    if results and step.verdict == NOT_RUN and 0 < left <= step.limits.nudge_from_calls_left:
        nudge = call_nudge(left, step.step_id, step.limits.max_calls)
        step.conversation.append({"role": "user", "content": nudge})
        call.transcript.append({"call": call.number, "nudge": nudge, "sent_as": "user message"})
        call.nudged = True


def _execute(
    step: _Step, call: Call, name: str, arguments: str
) -> tuple[str, str, dict[str, Any] | None]:
    """(status, result text, submit verdict) of one tool call; refusals are results."""
    try:
        raw = json.loads(arguments)
        if not isinstance(raw, dict):
            raise ToolError("bad arguments: not a JSON object")
        if step.tools is None and name != submit_name(step.step_id):
            # Task 8.9: a submit-only step is offered no pack tool and never runs one.
            raise ToolError(
                f"unknown tool {name!r}: this step's only tool is {submit_name(step.step_id)}"
            )
        if name == SEARCH and step.tools is not None:
            return "ok", step.tools.search_pack(raw), None
        if name == READ and step.tools is not None:
            return "ok", step.tools.read_pages(raw), None
        if name != submit_name(step.step_id):
            raise ToolError(f"unknown tool {name!r}")
    except json.JSONDecodeError:
        step.counts["invalid"] += 1
        call.counts["invalid"] += 1
        return "error", "error: bad arguments: invalid JSON", None
    except (ToolError, PromptError) as error:
        step.counts["invalid"] += 1
        call.counts["invalid"] += 1
        return "error", f"error: {error}", None
    submit = _judge(step, call, arguments)
    verdict = {"submit": submit.number, "outcome": submit.outcome, "issues": list(submit.issues)}
    if submit.outcome == "accepted":
        return "accepted", "accepted", verdict
    listed = "\n".join(f"- {issue}" for issue in submit.issues)
    left = step.limits.max_submits - submit.number
    return "rejected", f"rejected ({left} submits left):\n{listed}", verdict


def _rules(step: _Step, seen: Seen) -> Callable[[str], tuple[str, ...]] | None:
    if not step.rules.active(step.step_id):
        return None
    return partial(step.rules.issues, step.step_id, seen=seen, context=step.context)


def _judge(step: _Step, call: Call, payload: str) -> Submit:
    """Judge one submit as the step's current try, in a scratch copy of its starting journal."""
    number = len(step.submits) + 1
    seen = step.tools.seen() if step.tools is not None else Seen()
    with tempfile.TemporaryDirectory(prefix="tool-submit-") as scratch:
        copy = Path(scratch) / "journal"
        shutil.copytree(step.store.directory, copy)
        store = Execution(copy)
        submitted = submit_model_payload(
            store, step.attempt.ticket_id, step.step_id, payload, rules=_rules(step, seen)
        )
        outcome, issues = journal_outcome(store, step.step_id, submitted.journal)
    submit = Submit(
        number, call.number, call.attempt_id, payload, seen, outcome, issues, call.effort.sent
    )
    step.submits.append(submit)
    call.status, call.output, call.issues = outcome, payload, issues
    call.event("submit_judged", submit=number, outcome=outcome, issue_count=len(issues))
    rejected = sum(item.outcome == "rejected" for item in step.submits)
    floor = any(issue.startswith(INCOMPLETE) for issue in issues)
    if outcome == "rejected" and step.escalated is None and (rejected >= 2 or floor):
        reason = "a completeness-floor rejection" if floor else f"{rejected} rejected submits"
        step.escalated = reason
        call.event(
            "effort_escalated",
            reason=reason,
            to=step.plan.escalated(),
            ceiling=step.plan.ceiling,
            changed=step.plan.escalated() != step.plan.effort,
        )
    return submit


def _record_response(call: Call, ctx: _Context) -> None:
    reason = call.error or "no response received"
    ctx.writer.record_response(call.locator, response_envelope(call.result, reason), call.output)
    call.responded = True


def _after(step: _Step, call: Call, ctx: _Context) -> None:
    """The step's limits after this call, then, if the step ended, its last judged submit
    entered into the live journal (verdict checked against the scratch one)."""
    elapsed = ctx.monotonic() - step.started
    deadline = step.limits.deadline_s
    if elapsed >= deadline and (step.retry_pending or step.verdict in _TIMED_OUT):
        step.retry_pending = False
        step.verdict = LIMIT  # the call's bound was the step's deadline
        step.verdict_reason = f"deadline of {deadline} s reached during call {call.number}"
    elif step.verdict == NOT_RUN:
        if call.number >= step.limits.max_calls or elapsed + (step.wait_s or 0) >= deadline:
            # No call can follow: neither a retry nor an in-flight re-send (not waited out).
            call.not_re_sent = step.wait_s is not None
            step.retry_pending, step.wait_s = False, None
            step.verdict, step.verdict_reason = LIMIT, f"{call.number} calls, {elapsed:.1f} s"
    if step.verdict == NOT_RUN or not step.submits or step.journal is not None:
        return
    last = step.submits[-1]

    def resolved(paths: tuple[str, ...]) -> None:
        if paths:
            call.event("payload_nulls_resolved", paths=list(paths))

    submitted = submit_model_payload(
        step.store,
        step.attempt.ticket_id,
        step.step_id,
        last.payload,
        on_normalised=resolved,
        rules=_rules(step, last.seen),
    )
    composed_event(call.event, submitted)
    outcome, issues = journal_outcome(step.store, step.step_id, submitted.journal)
    call.event("journal_result", submit=last.number, outcome=outcome, issues=list(issues))
    if (outcome, issues) != (last.outcome, last.issues):
        raise ValueError(
            f"the live journal judged submit {last.number} {outcome} with {len(issues)} issues; "
            f"its scratch judgement was {last.outcome} with {len(last.issues)}"
        )
    step.journal = submitted.journal


def _close(step: _Step, call: Call, ctx: _Context) -> None:
    """Settle the call (when it was reserved) and seal it; the transcript before the seal."""
    if call.failure is not None:
        _interrupted(call, call.failure, ctx)
    # Review A item 1: the reservation is settled exactly once on every exit path. When the
    # response cannot be retained or the cost cannot be computed, the whole reservation is held
    # (worst case) and that error leaves after the settle and the seal attempt.
    cost = _Cost(None, "unknown", "cost not computed; reservation held as worst case")
    try:
        try:
            if not call.responded:
                _record_response(call, ctx)
            cost = _cost(step.candidate, call.result)
        except BaseException as error:
            if call.failure is None:
                _interrupted(call, error, ctx)
            raise
        finally:
            call.cost = cost
            call.settlement = ctx.ledger.settle(call.attempt_id, cost.amount, _reason(call, cost))
            call.event("ledger_settled", charged=call.settlement.charged, basis=cost.basis)
    finally:
        _record_tools(call, ctx)
        _seal(step, call, ctx, cost)


def _interrupted(call: Call, error: BaseException, ctx: _Context) -> None:
    call.status = "interrupted"
    call.error = redact(f"{type(error).__name__}: {error}", ctx.key)
    call.event("interrupted", error=call.error)


def _reason(call: Call, cost: _Cost) -> str:
    """The settle reason. An in-flight 402 ends with the runner's marks (`in_flight_refused`
    counts neither as a model try); one on a call no call can follow says it was not re-sent."""
    reason = f"{cost.reason}; status={call.status}"
    if call.credit is None or not call.credit.transient:
        return reason
    if call.credit.exhausted is not None:
        return reason + IN_FLIGHT_EXHAUSTED_MARK
    if call.not_re_sent:
        reason += "; not re-sent: no call can follow"
    return reason + IN_FLIGHT_SETTLE_MARK


def _record_tools(call: Call, ctx: _Context) -> None:
    """Retain the transcript and keep the hash of the bytes written (the manifest binds it)."""
    ctx.writer.record_tools(call.locator, call.transcript)
    path = ctx.writer.path_for(call.locator) / TOOL_TRANSCRIPT
    call.transcript_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()


def _seal_unsent(step: _Step, call: Call, ctx: _Context, status: str, reason: str) -> None:
    """Seal a call that never reached the provider (ineligible, or refused by the cap)."""
    call.status, call.error = status, reason
    call.event(status, reason=reason)
    _record_response(call, ctx)
    _seal(step, call, ctx, _Cost(None, "not-dispatched", f"{status}; nothing was sent"))


def _money(step: _Step) -> tuple[Decimal, Decimal]:
    """(settled at a measured or known cost, held at a reservation) over the step's calls."""
    settled = [c.settlement for c in step.calls if c.settlement is not None]
    return (
        sum((s.charged for s in settled if not s.unreconciled), Decimal(0)),
        sum((s.charged for s in settled if s.unreconciled), Decimal(0)),
    )


def telemetry(step: _Step, call: Call) -> dict[str, Any]:
    """The tool-loop fields of a call's metrics (task 8.0d item 9): this call's tool calls and
    effort, and the step as of this call (pages read, searches, submits, shrink and
    completeness flags, money). The last call's block is the step's."""
    settled, held = _money(step)
    records = [item.record(step.step_id) for item in step.submits]
    final = step.submits[-1].payload if step.submits else None
    financials = step.step_id == "financials"
    tools = step.tools  # None: a submit-only step, whose reading fields are null (task 8.9)
    read = tools.read if tools is not None else set()
    return {
        "call": call.number,
        "effort_level": call.level,
        "effort_sent": call.effort.sent,
        "effort_escalated": step.escalated,
        "cost_basis": call.cost.basis if call.cost else None,
        "tool_calls": dict(sorted(call.counts.items())),
        "tool_time_s": call.tool_time_s,
        "nudge_sent": call.nudged,
        "retry_of_attempt_id": call.retry_of,
        "step": {
            "calls": len(step.calls),
            "tool_set": step.kind,
            "tool_calls": dict(sorted(step.counts.items())),
            "pages_read": len(read) if tools is not None else None,
            "located_pages": tools.located_pages if tools is not None else None,
            "searches_run": len(tools.searched) if tools is not None else None,
            "spans_surfaced_by_search": len(tools.surfaced) if tools is not None else None,
            "submits": records,
            "first_submit_accepted": records[0]["outcome"] == "accepted" if records else None,
            "submit_shrinkage": shrinkage(records),
            "completeness_drop": completeness_drop(records) if financials else None,
            "final_payload_completeness": completeness(final) if financials and final else None,
            "final_payload_cited_not_read": sorted(
                list(item) for item in cited_locators(final) - read
            )
            if final
            else None,
            "verdict": step.verdict,
            "verdict_reason": step.verdict_reason,
            "cost_settled_usd": settled,
            "cost_held_usd": held,
            "rules": step.rules.to_record(step.step_id),
            "limits": asdict(step.limits),
        },
    }


def _metrics(step: _Step, call: Call, cost: _Cost) -> dict[str, Any]:
    result = call.result
    why = "not dispatched or no response received"
    unsent = not call.sent
    return {
        "provider": _provider_usage(result),
        "local": {
            **_nullable("latency_s", result.latency_s if result else None, why),
            **_nullable("time_to_first_token_s", None, "request is not streamed"),
            "tool_time_s": call.tool_time_s,
        },
        "estimate": {
            "prompt_tokens_upper_bound": call.bound,
            **_nullable(
                "reserved_usd",
                None if unsent else call.reserve,
                f"nothing reserved: {call.status}, nothing was sent",
            ),
            "request_bytes": request_bytes(call.chat.body()),
            "basis": (
                "ceil(request body UTF-8 bytes / prompt_bytes_per_token_lower_bound) plus "
                f"{TOKEN_OVERHEAD} fixed overhead tokens (decision 0008)"
            ),
        },
        "ledger": _ledger_block(cost, call.settlement),
        "validation": {"outcome": call.status, "issue_count": len(call.issues)},
        "repair_count": step.attempt.number,
        "retries_on_this_ticket_step": call.retry_of is not None,
        "tool_loop": telemetry(step, call),
    }


def _manifest(step: _Step, call: Call, ctx: _Context) -> dict[str, Any]:
    result = call.result
    classification = result.classification if result else None
    verified = bool(result and result.identity_verified)
    body = call.chat.body()
    return {
        "schema": "model-test-attempt/1",
        "experiment_id": call.locator.experiment,
        "case_id": call.locator.case,
        "attempt_id": call.attempt_id,
        "model": step.candidate.slug,
        "ticket_id": step.attempt.ticket_id,
        "module_id": step.spec.module_id,
        "step_id": step.step_id,
        "started_at": call.started_at,
        "finished_at": ctx.clock(),
        "cohort": COHORT,
        "pool_label": step.pool_label,
        "status": call.status,
        "classification": classification,
        "poolable": classification in SUBMITTED and verified and call.status in POOLABLE_STATUSES,
        "error": call.error,
        "code": {"live_package_sha256": code_sha256()},
        "hashes": {
            "prompt_sha256": step.prompt_sha256,
            "schema_sha256": hashlib.sha256(schema_text(step.spec.schema).encode()).hexdigest(),
            "request_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
            "declared_inputs": [],
            # The evidence file the absence and cited-page rules read (review A item 3).
            "tool_transcript_sha256": call.transcript_sha256,
            # Task 8.9, as the one-shot `quality` manifest (task 7.4 fix round 1).
            **(
                {}
                if step.quality_inputs_sha256 is None
                else {"quality_inputs_sha256": step.quality_inputs_sha256}
            ),
            "snapshot_sha256": step.snapshot_sha256,
            "journal_inputs": {item.input_id: item.sha256 for item in step.attempt.inputs},
        },
        "draw": step.drawn.to_record(),
        "effort": call.effort.to_record(),
        "endpoint": CHAT_URL,
        "routing": {"allow_fallbacks": False, "require_parameters": True, "models": None},
        "tools": {
            "offered": True,
            "tool_choice": TOOL_CHOICE,
            "names": [spec["function"]["name"] for spec in step.specs],
        },
        "served": {
            "model": result.served_model if result else None,
            "provider": result.served_provider if result else None,
            "provider_request_id": result.provider_request_id if result else None,
            "identity_verified": verified,
        },
        "budgets": {
            "cap_usd": ctx.ledger.cap,
            "max_tokens": step.limits.max_tokens,
            **_nullable(
                "reserved_usd",
                call.reserve if call.sent else None,
                f"nothing reserved: {call.status}, nothing was sent",
            ),
            "timeout_s": call.chat.timeout_s,
            "deadline_s": call.chat.timeout_s,  # the rest of the step's wall clock
            "step_deadline_s": step.limits.deadline_s,
        },
        "pinned_candidate": step.candidate.to_record(),
        "links": {
            **step.links,
            "retry_of_attempt_id": call.retry_of,
            "previous_call_attempt_id": f"{step.prefix}-{call.number - 1}"
            if call.number > 1
            else None,
        },
        "validator": {"outcome": call.status, "issues": list(call.issues)},
        "credential": {
            "recorded": False,
            "response_scrubbed": bool(result and result.redacted),
            **step.key_note,
        },
        "credit": call.credit.to_record() if call.credit else None,
        "tool_loop": {
            "call": call.number,
            "first_call_attempt_id": f"{step.prefix}-1",
            "step_try": step.current_try,
            "transcript": "tool-calls.jsonl" if call.sent else None,
        },
    }


def _seal(step: _Step, call: Call, ctx: _Context, cost: _Cost) -> None:
    checks: dict[str, Any] = {"validator": {"outcome": call.status, "issues": list(call.issues)}}
    if call.result is not None:
        checks["classification"] = {
            "classification": call.result.classification,
            "finish_reason": call.result.finish_reason,
            "identity_verified": call.result.identity_verified,
            "error_detail": call.result.error_detail,
        }
    upstream = ["response.json", "output.md"] if call.result and call.result.redacted else []
    ctx.writer.seal(
        call.locator,
        _manifest(step, call, ctx),
        call.events,
        _metrics(step, call, cost),
        checks,
        scrubbed_upstream=upstream,
    )


def _status(step: _Step) -> str:
    if step.journal is not None:
        return step.submits[-1].outcome
    if step.verdict == NOT_RUN:  # raised mid-step (`run_tool_step`'s `on_stop`)
        return step.calls[-1].status
    if step.verdict == "stopped: cap":
        return "refused"
    if step.verdict == "withheld-fallback":
        return "withheld-fallback"
    if step.verdict == "not sent: misfit":
        return "ineligible"
    if step.verdict.startswith("no-response") or step.verdict == "provider-schema-error":
        return "no-response"
    return NO_SUBMIT


def _result(step: _Step, ctx: _Context) -> ToolStepResult:
    last = step.submits[-1] if step.submits else None
    holder = next(
        (c for c in step.calls if last is not None and c.number == last.call), step.calls[-1]
    )
    settled, held = _money(step)
    first = step.calls[0]
    return ToolStepResult(
        step_id=step.step_id,
        attempt_id=holder.attempt_id,
        attempt_ids=tuple(c.attempt_id for c in step.calls),
        status=_status(step),
        verdict=step.verdict,
        verdict_reason=step.verdict_reason,
        classification=holder.result.classification if holder.result else None,
        draw=step.drawn,
        effort=first.effort.to_record(),
        directory=ctx.writer.path_for(holder.locator),
        journal=step.journal,
        cost_usd=settled + held,
        held_usd=held,
        held=held > 0 or any(c.settlement and c.settlement.unreconciled for c in step.calls),
        issues=last.issues if last is not None and step.journal is not None else (),
        attempt_pending=_pending(step.store, step.attempt.ticket_id),
        step_try=step.current_try,
        prompt_tokens_upper_bound=max(c.bound for c in step.calls),
        submits=tuple(item.record(step.step_id) for item in step.submits),
    )
