"""Task 8.0d: a CP-1 stage as a tool loop, with injected transports and a fake clock only."""

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from deploy_vii.contracts import Span
from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_workflow import cp1_registers
from deploy_vii.cp3_relative_value import MarketEvidence
from deploy_vii.execution import Execution
from deploy_vii.live import loop
from deploy_vii.live.catalog import ModelSelection, PinnedPool
from deploy_vii.live.client import ChatClient, ChatResult, Request, Response, TransportError, Usage
from deploy_vii.live.context import SOURCE_SCOPES, declared_sources, readable_sources
from deploy_vii.live.credit import CreditExhausted
from deploy_vii.live.ledger import CapExceeded, Ledger
from deploy_vii.live.loop import (
    LIMIT,
    LIMITS,
    NO_SUBMIT,
    PART_LIMITS,
    TOOL_SET_LIMITS,
    ToolLimits,
    ToolStepResult,
    call_nudge,
    issue_class,
    limits_for,
    run_tool_step,
    transient,
)
from deploy_vii.live.prompts import NO_TOOLS_RULE, build, submit_only_rule, tools_rule
from deploy_vii.live.retention import TOOL_TRANSCRIPT, AttemptWriter
from deploy_vii.live.runner import (
    IN_FLIGHT_EXHAUSTED_MARK,
    IN_FLIGHT_SETTLE_MARK,
    StepSpec,
    in_flight_refused,
    prompt_inputs,
)
from deploy_vii.live.settings import StepEffort, load_settings
from deploy_vii.live.submission import STEPS
from deploy_vii.live.tools import (
    ABSENCE,
    INCOMPLETE,
    UNBACKED_ABSENCE,
    PackTools,
    ToolError,
    ToolRules,
    applicable_rules,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.registry import PACK_TOOLS, SUBMIT_ONLY, tool_set, tool_sets
from tests.product import test_cp3_relative_value as cp3_tests
from tests.product import test_live_modules as module_tests
from tests.product import transcript_support
from tests.product.live_support import catalog_of, catalog_row, make_rtf_key
from tests.product.test_business_context import submission_fixture as cp1a_submission
from tests.product.test_cp1_workflow import staged
from tests.product.test_execution import accept_cp0, fixture_store
from tests.product.test_live_credit import CREDIT_402, IN_FLIGHT_402
from tests.product.test_live_runner import model_review
from tests.product.test_readiness import as_submission, readiness_fixture
from tests.product.test_workflow import cp1_case

MODEL = "openai/gpt-6.1-sol"
PARAMETERS = (
    "max_tokens",
    "reasoning",
    "reasoning_effort",
    "response_format",
    "structured_outputs",
    "tools",
    "tool_choice",
)
BYTES_PER_TOKEN = load_settings(Path("settings/project.toml")).prompt_bytes_per_token_lower_bound
SEVEN = {
    "manifest.json",
    "request.json",
    "response.json",
    "output.md",
    "events.jsonl",
    "metrics.json",
    "checks",
    "render",
}
MEDIUM = StepEffort.of("medium")
# The synthetic context claims no events in S1, which the absence rule backs only by a search.
NO_RULES = ToolRules(checked=())


def no_wait(seconds: float) -> None:
    raise AssertionError(f"unexpected wait of {seconds} s")


def tool_reply(
    *calls: tuple[str, str, str],
    cost: object = 0.01,
    finish: str = "tool_calls",
    content: str | None = None,
    model: str = MODEL,
) -> Response:
    """An OpenRouter reply with tool calls `(id, name, arguments)` and opaque reasoning."""
    usage: dict[str, Any] = {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200}
    if cost is not None:
        usage["cost"] = cost
    message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "reasoning_details": [{"type": "reasoning.encrypted", "data": "opaque-1"}],
    }
    if calls:
        message["tool_calls"] = [
            {"id": ident, "type": "function", "function": {"name": name, "arguments": args}}
            for ident, name, args in calls
        ]
    body = {
        "id": "gen-loop-test",
        "model": model,
        "provider": "OpenAI",
        "choices": [{"finish_reason": finish, "message": message}],
        "usage": usage,
    }
    return Response(200, json.dumps(body).encode())


def search(ident: str = "c-s") -> Response:
    return tool_reply((ident, "search_pack", json.dumps({"query": "revenue"})))


def submit(payload: str, ident: str = "c-1") -> Response:
    return tool_reply((ident, "submit_source_context", payload))


class Clock:
    """The loop's monotonic clock; the transport moves it."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Script:
    """A transport that answers from a queue, moving the clock by `step_s` per call."""

    replies: list[Response | BaseException]
    clock: Clock
    step_s: float = 1.0
    requests: list[Request] = field(default_factory=list)
    fallback: Response | None = None

    def __call__(self, request: Request) -> Response:
        self.requests.append(request)
        self.clock.now += self.step_s
        reply = self.replies.pop(0) if self.replies else self.fallback
        if reply is None:
            raise AssertionError("the loop sent more calls than scripted")
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(request.body) for request in self.requests]


@dataclass(frozen=True)
class Frozen:
    journal: Path  # CP-0 accepted, nothing else
    context: str  # a valid source_context payload


@pytest.fixture(scope="module")
def frozen(tmp_path_factory: pytest.TempPathFactory) -> Frozen:
    root = tmp_path_factory.mktemp("loop-case")
    store, _, _ = cp1_case(root / "seed")
    snapshot = store.read()
    review = store.payload(snapshot.attempts[0].steps[0].payload_sha256)
    journal = Execution.create(root / "frozen", store.pack())
    assert not submit_cp0_review(journal, journal.begin("CP-0").ticket_id, review).issues
    context = store.payload(snapshot.attempts[1].steps[0].payload_sha256)
    return Frozen(root / "frozen", context)


def tool_pool(parameters: tuple[str, ...] = PARAMETERS) -> PinnedPool:
    row = catalog_row(
        MODEL, parameters=parameters, efforts=("low", "medium", "high", "xhigh", "max")
    )
    return catalog_of(row).pin_selected("loop", (ModelSelection(MODEL, None),))


@dataclass
class Rig:
    store: Execution
    ticket: str
    ledger: Ledger
    pool: PinnedPool
    writer: AttemptWriter
    key: Path
    context: str
    root: Path
    clock: Clock = field(default_factory=Clock)

    def run(
        self,
        script: Script | Callable[[Request], Response],
        *,
        effort: StepEffort = MEDIUM,
        rules: ToolRules | None = None,
        limits: ToolLimits | None = None,
        sleep: Callable[[float], None] = no_wait,
        on_stop: Callable[[ToolStepResult], None] | None = None,
        step_id: str = "source_context",
    ) -> ToolStepResult:
        return run_tool_step(
            StepSpec(step_id, "case-loop", ()),
            store=self.store,
            ticket_id=self.ticket,
            ledger=self.ledger,
            pool=self.pool,
            seed=0,
            client=ChatClient(script),
            writer=self.writer,
            key_path=self.key,
            key_index=1,
            bytes_per_token=BYTES_PER_TOKEN,
            effort=effort,
            rules=ToolRules() if rules is None else rules,
            limits=limits,
            clock=lambda: "2026-10-24T10:00:00Z",
            monotonic=self.clock,
            sleep=sleep,
            on_stop=on_stop,
        )

    def directory(self, attempt_id: str) -> Path:
        return (
            self.root / "artifacts" / "loop" / "case-loop" / MODEL.replace("/", "__") / attempt_id
        )

    def manifest(self, attempt_id: str) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(
            (self.directory(attempt_id) / "manifest.json").read_text()
        )
        return loaded

    def metrics(self, attempt_id: str) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(
            (self.directory(attempt_id) / "metrics.json").read_text()
        )
        return loaded

    def script(self, *replies: Response | BaseException, step_s: float = 1.0) -> Script:
        return Script(list(replies), self.clock, step_s)


def make_rig(
    root: Path, frozen: Frozen, *, cap: Decimal = Decimal(5), pool: PinnedPool | None = None
) -> Rig:
    shutil.copytree(frozen.journal, root / "journal")
    store = Execution(root / "journal")
    ticket = store.begin("CP-1").ticket_id
    keys = root / "keys"
    keys.mkdir()
    return Rig(
        store,
        ticket,
        Ledger(root / "artifacts" / ".ledgers" / "loop.jsonl", cap, provider="openrouter"),
        pool or tool_pool(),
        AttemptWriter(root / "artifacts"),
        make_rtf_key(keys),
        frozen.context,
        root,
    )


@pytest.fixture
def rig(tmp_path: Path, frozen: Frozen) -> Rig:
    return make_rig(tmp_path, frozen)


def first(rig: Rig, number: int) -> str:
    return f"{rig.ticket}-source_context-{number}"


def steps_of(rig: Rig) -> list[tuple[str, str]]:
    attempt = next(a for a in rig.store.read().attempts if a.ticket_id == rig.ticket)
    return [(s.step_id, s.status) for s in attempt.steps]


# --- an accepted step ------------------------------------------------------------------------


def test_an_accepted_step_is_one_conversation_with_a_ledger_attempt_per_call(rig: Rig) -> None:
    script = rig.script(search(), submit(rig.context))
    result = rig.run(script)
    assert (result.status, result.verdict) == ("accepted", "accepted")
    assert result.attempt_ids == (first(rig, 1), first(rig, 2))
    assert result.attempt_id == first(rig, 2) and result.journal is not None
    assert steps_of(rig) == [("source_context", "valid")]
    one, two = script.bodies()
    for body in (one, two):
        assert "response_format" not in body and body["tool_choice"] == "required"
        assert [t["function"]["name"] for t in body["tools"]] == [
            "search_pack",
            "read_pages",
            "submit_source_context",
        ]
        assert body["max_tokens"] == 128_000 and body["reasoning"] == {"effort": "medium"}
    system, user = one["messages"]
    assert tools_rule("submit_source_context") in system["content"]
    assert "<<<SOURCE id=S1" not in user["content"]
    # The conversation is kept: the assistant turn goes back unmodified, then its tool result.
    assistant = json.loads(search().body)["choices"][0]["message"]
    assert two["messages"][:2] == one["messages"] and two["messages"][2] == assistant
    tool = two["messages"][3]
    assert tool["role"] == "tool" and tool["tool_call_id"] == "c-s"
    assert tool["content"] == PackTools(rig.store.pack()).search_pack({"query": "revenue"})
    # Money: each call reserved and settled from usage.cost; the step sums them.
    records = {r.attempt_id: r for r in rig.ledger.state().attempts}
    assert {k: (r.status, r.charged_usd) for k, r in records.items()} == {
        first(rig, 1): ("settled", Decimal("0.01")),
        first(rig, 2): ("settled", Decimal("0.01")),
    }
    assert result.cost_usd == Decimal("0.02") and not result.held
    for number in (1, 2):
        directory = rig.directory(first(rig, number))
        assert {p.name for p in directory.iterdir()} == SEVEN | {TOOL_TRANSCRIPT}
    manifest = rig.manifest(first(rig, 2))
    assert manifest["tools"]["offered"] is True and manifest["tools"]["tool_choice"] == "required"
    assert manifest["links"]["previous_call_attempt_id"] == first(rig, 1)
    assert manifest["status"] == "accepted" and manifest["hashes"]["declared_inputs"] == []
    assert manifest["effort"]["sent"] == "medium"
    assert (rig.directory(first(rig, 2)) / "output.md").read_text() == rig.context
    entries = [
        json.loads(line)
        for line in (rig.directory(first(rig, 1)) / TOOL_TRANSCRIPT).read_text().splitlines()
    ]
    assert [(e["name"], e["status"]) for e in entries] == [("search_pack", "ok")]
    telemetry = rig.metrics(first(rig, 2))["tool_loop"]
    assert telemetry["effort_sent"] == "medium" and telemetry["cost_basis"] == "provider-reported"
    assert telemetry["step"]["searches_run"] == 1 and telemetry["step"]["calls"] == 2
    assert [s["outcome"] for s in telemetry["step"]["submits"]] == ["accepted"]
    assert telemetry["step"]["cost_settled_usd"] == "0.02"


def test_a_started_step_is_never_run_again(rig: Rig) -> None:
    rig.run(rig.script(tool_reply(content="no tools today", finish="stop")))
    with pytest.raises(ValueError, match="never re-run"):
        rig.run(rig.script())


# --- limits, nudge and verdicts --------------------------------------------------------------


def test_the_nudge_is_a_user_message_from_three_calls_left_never_tool_text(rig: Rig) -> None:
    limits = ToolLimits(max_calls=5)
    script = rig.script(*(search(f"c{n}") for n in range(5)))
    result = rig.run(script, limits=limits)
    assert result.verdict == LIMIT and result.status == NO_SUBMIT and len(script.requests) == 5
    assert steps_of(rig) == []  # nothing judged: the live journal is untouched
    for number, body in enumerate(script.bodies(), start=1):
        messages = body["messages"]
        assert not any(
            "calls remain" in str(m.get("content")) for m in messages if m["role"] == "tool"
        )
        left = limits.max_calls - (number - 1)
        if number >= 3:
            assert messages[-1] == {
                "role": "user",
                "content": call_nudge(left, "source_context", limits.max_calls),
            }, number
        else:
            assert messages[-1]["role"] != "user" or number == 1
    nudges = [
        json.loads(line)
        for n in range(1, 6)
        for line in (rig.directory(first(rig, n)) / TOOL_TRANSCRIPT).read_text().splitlines()
        if "nudge" in line
    ]
    assert [(e["call"], e["sent_as"]) for e in nudges] == [
        (2, "user message"),
        (3, "user message"),
        (4, "user message"),
    ]


def test_three_rejected_submits_end_the_step_and_escalate_after_the_second(rig: Rig) -> None:
    script = rig.script(submit("{}", "a"), submit("{}", "b"), submit("{}", "c"))
    result = rig.run(script)
    assert (result.status, result.verdict) == ("rejected", "rejected")
    assert [b["reasoning"]["effort"] for b in script.bodies()] == ["medium", "medium", "high"]
    assert result.attempt_pending and result.step_try == 1
    attempt = next(a for a in rig.store.read().attempts if a.ticket_id == rig.ticket)
    assert [s.step_id for s in attempt.step_repairs] == ["source_context"]  # the last submit
    assert result.issues == attempt.step_repairs[0].issues
    assert [s["outcome"] for s in result.submits] == ["rejected"] * 3
    events = [
        json.loads(line)
        for line in (rig.directory(first(rig, 2)) / "events.jsonl").read_text().splitlines()
    ]
    escalated = next(e for e in events if e["event"] == "effort_escalated")
    assert (escalated["reason"], escalated["to"]) == ("2 rejected submits", "high")
    # The second rejected tool result says how many submits remain.
    third = script.bodies()[2]["messages"][-1]
    assert third["role"] == "tool" and third["content"].startswith("rejected (1 submits left):")


def test_escalation_never_passes_the_ceiling(rig: Rig) -> None:
    script = rig.script(submit("{}", "a"), submit("{}", "b"), submit("{}", "c"))
    rig.run(script, effort=StepEffort("medium", "medium"))
    assert [b["reasoning"]["effort"] for b in script.bodies()] == ["medium"] * 3


def test_a_reply_without_a_tool_call_or_with_a_malformed_one_ends_the_step(
    tmp_path: Path, frozen: Frozen
) -> None:
    text = make_rig(tmp_path / "a", frozen)
    result = text.run(text.script(tool_reply(content="done", finish="stop")))
    assert result.verdict == "rejected: no-submit" and result.status == NO_SUBMIT
    broken = make_rig(tmp_path / "b", frozen)
    malformed = json.loads(search().body)
    del malformed["choices"][0]["message"]["tool_calls"][0]["id"]
    result = broken.run(broken.script(Response(200, json.dumps(malformed).encode())))
    assert result.verdict == "rejected: malformed tool call"
    assert result.verdict_reason == "malformed tool call without an id"


def test_an_absence_claim_needs_a_recorded_search(tmp_path: Path, frozen: Frozen) -> None:
    document = json.loads(frozen.context)
    source = document["sources"][0]
    source.update(
        event_scan="no_events_identified",
        event_scan_citations=source["citations"],
        event_scan_explanation="The synthetic statements report no subsequent events.",
    )
    claim = json.dumps(document)
    blind = make_rig(tmp_path / "a", frozen)
    result = blind.run(blind.script(submit(claim, "a"), submit(claim, "b"), submit(claim, "c")))
    assert result.status == "rejected"
    assert result.issues and all(i.startswith(UNBACKED_ABSENCE) for i in result.issues)
    searched = make_rig(tmp_path / "b", frozen)
    result = searched.run(searched.script(search(), submit(claim)))
    assert result.status == "accepted", result.issues


# --- failures, money and stops ---------------------------------------------------------------


def test_a_transient_failure_is_retried_once_as_a_new_call(rig: Rig) -> None:
    script = rig.script(
        Response(502, b'{"error": {"message": "Stream ended"}}'), submit(rig.context)
    )
    result = rig.run(script, rules=NO_RULES)
    assert result.status == "accepted" and result.attempt_ids == (first(rig, 1), first(rig, 2))
    failed = rig.manifest(first(rig, 1))
    assert failed["status"] == "no-response"
    assert rig.manifest(first(rig, 2))["links"]["retry_of_attempt_id"] == first(rig, 1)
    records = {r.attempt_id: r for r in rig.ledger.state().attempts}
    held = records[first(rig, 1)]
    assert held.status == "settled" and held.charged_usd == held.reserved_usd  # no cost: held
    assert result.held and result.cost_usd == held.charged_usd + Decimal("0.01")
    # The retry repeats the failed call's conversation: the failure is no turn.
    one, two = script.bodies()
    assert one["messages"] == two["messages"]


def test_a_second_failure_in_a_row_ends_the_step(rig: Rig) -> None:
    script = rig.script(TransportError("connection reset"), TransportError("connection reset"))
    result = rig.run(script)
    assert result.verdict == "no-response: transport_error" and result.status == "no-response"
    assert len(result.attempt_ids) == 2 and steps_of(rig) == []
    assert all(r.status == "settled" for r in rig.ledger.state().attempts)


def test_a_refusal_before_inference_is_not_retried(rig: Rig) -> None:
    result = rig.run(rig.script(Response(400, b'{"error": {"message": "bad request"}}')))
    assert result.verdict == "no-response: http_error" and len(result.attempt_ids) == 1
    assert rig.ledger.state().attempts[0].charged_usd == 0


def test_an_in_flight_402_is_waited_out_and_re_sent_once(rig: Rig) -> None:
    waits: list[float] = []
    script = rig.script(Response(402, IN_FLIGHT_402), submit(rig.context))
    result = rig.run(script, sleep=waits.append, rules=NO_RULES)
    assert waits == [120] and result.status == "accepted"
    refused = rig.ledger.state().attempts[0]
    assert refused.charged_usd == 0 and (refused.basis or "").endswith(IN_FLIGHT_SETTLE_MARK)


def test_an_in_flight_402_on_the_last_call_ends_the_step_with_its_last_submit(rig: Rig) -> None:
    """Confidence review: no call can follow the step's last one, so its in-flight refusal is not
    waited out, and the step's last judged submit still enters the live journal."""
    script = rig.script(submit("{}", "a"), Response(402, IN_FLIGHT_402))
    result = rig.run(script, limits=ToolLimits(max_calls=2), rules=NO_RULES)
    assert result.verdict == LIMIT and result.status == "rejected"
    attempt = next(a for a in rig.store.read().attempts if a.ticket_id == rig.ticket)
    assert [s.step_id for s in attempt.step_repairs] == ["source_context"]


def test_exhausted_credit_raises_after_the_call_is_sealed(rig: Rig) -> None:
    stopped: list[ToolStepResult] = []
    with pytest.raises(CreditExhausted):
        rig.run(rig.script(search(), Response(402, CREDIT_402)), on_stop=stopped.append)
    assert [r.attempt_ids for r in stopped] == [(first(rig, 1), first(rig, 2))]
    assert (rig.directory(first(rig, 2)) / "manifest.json").exists()
    assert steps_of(rig) == []


def test_the_cap_refuses_a_call_after_sealing_it_unsent(tmp_path: Path, frozen: Frozen) -> None:
    rig = make_rig(tmp_path, frozen, cap=Decimal("0.0001"))
    stopped: list[ToolStepResult] = []
    script = rig.script()
    with pytest.raises(CapExceeded):
        rig.run(script, on_stop=stopped.append)
    assert not script.requests and not rig.ledger.state().attempts
    assert rig.manifest(first(rig, 1))["status"] == "refused"
    assert [r.status for r in stopped] == ["refused"]


def test_a_route_without_tools_is_ineligible_and_sends_nothing(
    tmp_path: Path, frozen: Frozen
) -> None:
    rig = make_rig(tmp_path, frozen, pool=tool_pool(PARAMETERS[:-2]))
    script = rig.script()
    result = rig.run(script)
    assert result.status == "ineligible" and not script.requests
    assert result.verdict_reason == "the route lacks tools, tool_choice"
    assert not rig.ledger.state().attempts


def test_an_interrupted_call_settles_and_seals_before_the_error_leaves(rig: Rig) -> None:
    with pytest.raises(KeyboardInterrupt):
        rig.run(rig.script(KeyboardInterrupt()))
    record = rig.ledger.state().attempts[0]
    assert record.status == "settled" and record.charged_usd == record.reserved_usd
    manifest = rig.manifest(first(rig, 1))
    assert manifest["status"] == "interrupted" and manifest["error"].startswith("KeyboardInterrupt")


# --- fix round 1 ---------------------------------------------------------------------------------


def chain(error: BaseException | None) -> list[BaseException]:
    found = []
    while error is not None:
        found.append(error)
        error = error.__cause__ or error.__context__
    return found


def test_a_failure_retaining_the_response_still_settles_the_call_once(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review A item 1: the reservation is settled on every exit path, and a failure while
    closing the call never hides the original one."""

    def broken(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(rig.writer, "record_response", broken)
    with pytest.raises(BaseException) as caught:
        rig.run(rig.script(search()))
    assert any(isinstance(e, OSError) and str(e) == "disk full" for e in chain(caught.value))
    (record,) = rig.ledger.state().attempts
    assert record.status == "settled" and record.charged_usd == record.reserved_usd  # held


def test_a_failure_computing_the_cost_holds_the_reservation(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object) -> None:
        raise ArithmeticError("bad usage")

    monkeypatch.setattr(loop, "_cost", broken)
    with pytest.raises(ArithmeticError):
        rig.run(rig.script(search()))
    (record,) = rig.ledger.state().attempts
    assert record.status == "settled" and record.charged_usd == record.reserved_usd
    assert rig.manifest(first(rig, 1))["status"] == "interrupted"


def test_a_second_in_flight_402_in_one_step_is_exhaustion(rig: Rig) -> None:
    """Review A item 2: the second in-flight refusal of a step is exhaustion. It is settled
    with the exhaustion mark, so neither refusal counts as a model try; the step's last judged
    submit has entered the journal before CreditExhausted leaves."""
    waits: list[float] = []
    script = rig.script(
        submit("{}", "a"), Response(402, IN_FLIGHT_402), Response(402, IN_FLIGHT_402)
    )
    with pytest.raises(CreditExhausted):
        rig.run(script, sleep=waits.append, rules=NO_RULES)
    assert waits == [120]
    _, first_refusal, second = rig.ledger.state().attempts
    assert (first_refusal.basis or "").endswith(IN_FLIGHT_SETTLE_MARK)
    assert (second.basis or "").endswith(IN_FLIGHT_EXHAUSTED_MARK)
    assert in_flight_refused(first_refusal) and in_flight_refused(second)
    assert first_refusal.charged_usd == second.charged_usd == 0
    attempt = next(a for a in rig.store.read().attempts if a.ticket_id == rig.ticket)
    assert [s.step_id for s in attempt.step_repairs] == ["source_context"]


def test_the_manifest_hashes_the_tool_transcript(rig: Rig) -> None:
    """Review A item 3: the evidence file the citation rules read is bound by its hash."""
    rig.run(rig.script(search(), submit(rig.context)))
    for number in (1, 2):
        directory = rig.directory(first(rig, number))
        digest = hashlib.sha256((directory / TOOL_TRANSCRIPT).read_bytes()).hexdigest()
        assert rig.manifest(first(rig, number))["hashes"]["tool_transcript_sha256"] == digest


class Reads:
    """A monotonic clock that answers from a list, then keeps its last value."""

    def __init__(self, *values: float) -> None:
        self.values, self.now = list(values), 0.0

    def __call__(self) -> float:
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


def test_a_call_gets_the_rest_of_the_deadline_the_loop_head_measured(rig: Rig) -> None:
    """Review A item 4: a second clock read after the head's check could leave no time."""
    rig.clock = Reads(0.0, 3599.0, 3601.0)  # started, the loop head, any later read
    rig.run(rig.script(tool_reply(content="no", finish="stop")))
    request = json.loads((rig.directory(first(rig, 1)) / "request.json").read_text())
    assert request["non_secret_parameters"]["timeout_s"] == 1.0


def test_a_malformed_call_after_an_accepted_submit_leaves_the_step_accepted(rig: Rig) -> None:
    """Review A item 5: once a submit is accepted the verdict is final; a later malformed call
    in the same turn is only a transcript note."""
    body = json.loads(submit(rig.context).body)
    body["choices"][0]["message"]["tool_calls"].append({"id": "x", "type": "function"})
    result = rig.run(rig.script(Response(200, json.dumps(body).encode())), rules=NO_RULES)
    assert (result.status, result.verdict) == ("accepted", "accepted")
    lines = (rig.directory(first(rig, 1)) / TOOL_TRANSCRIPT).read_text().splitlines()
    note = json.loads(lines[-1])
    assert note["status"] == "not executed: the step has a final verdict"
    assert note["problem"] == "malformed tool call without a function"


def test_an_in_flight_402_on_the_last_call_says_it_was_not_re_sent(rig: Rig) -> None:
    """Review A item 6: the settle reason says which case the in-flight mark covers."""
    rig.run(rig.script(Response(402, IN_FLIGHT_402)), limits=ToolLimits(max_calls=1))
    (record,) = rig.ledger.state().attempts
    assert (record.basis or "").endswith(
        f"; not re-sent: no call can follow{IN_FLIGHT_SETTLE_MARK}"
    )
    assert in_flight_refused(record)


def test_the_prompt_states_the_steps_own_submit_limit(rig: Rig) -> None:
    """Review B item 11."""
    script = rig.script(tool_reply(content="no", finish="stop"))
    rig.run(script, limits=ToolLimits(max_submits=2))
    system = script.bodies()[0]["messages"][0]["content"]
    assert tools_rule("submit_source_context", 2) in system and "at most 2 submits" in system


@pytest.mark.parametrize(
    ("status", "retried"),
    [(None, True), (500, True), (502, True), (408, True), (200, True), (400, False), (401, False)],
)
def test_transport_stream_and_server_failures_are_transient(
    status: int | None, retried: bool
) -> None:
    usage = Usage(None, None, None, None, None, None, {})
    result = ChatResult(
        "http_error",
        status,
        None,
        False,
        None,
        None,
        None,
        None,
        None,
        False,
        None,
        usage,
        0.0,
        "x",
    )
    assert transient(result) is retried
    assert transient(None)


def test_an_issue_class_numbers_its_indices() -> None:
    assert issue_class("sources.0.event_scan 12: needs citations") == "sources.N.event_scan N"


# --- properties ------------------------------------------------------------------------------

ACTIONS = st.sampled_from(["search", "bad", "good", "502", "text", "read"])


@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    actions=st.lists(ACTIONS, min_size=1, max_size=10),
    max_calls=st.integers(1, 6),
    max_submits=st.integers(1, 3),
    step_s=st.sampled_from([1.0, 700.0, 1900.0]),
)
def test_the_limits_hold_and_the_ledger_sums_the_settled_calls(
    frozen: Frozen, actions: list[str], max_calls: int, max_submits: int, step_s: float
) -> None:
    limits = ToolLimits(max_calls=max_calls, max_submits=max_submits)
    with tempfile.TemporaryDirectory() as directory:
        rig = make_rig(Path(directory), frozen)
        replies: dict[str, Callable[[int], Response]] = {
            "search": lambda n: search(f"s{n}"),
            "bad": lambda n: submit("{}", f"b{n}"),
            "good": lambda n: submit(rig.context, f"g{n}"),
            "502": lambda n: Response(502, b"{}"),
            "text": lambda n: tool_reply(content="no", finish="stop"),
            "read": lambda n: tool_reply((f"r{n}", "read_pages", '{"source_id": "S1"}')),
        }
        script = Script(
            [replies[a](n) for n, a in enumerate(actions)],
            rig.clock,
            step_s,
            fallback=tool_reply(content="no", finish="stop"),
        )
        result = rig.run(script, limits=limits)
        bodies = script.bodies()
        assert len(bodies) <= limits.max_calls
        assert len(result.submits) <= limits.max_submits
        assert all(b["max_tokens"] == limits.max_tokens for b in bodies)
        timeouts = [
            json.loads((rig.directory(a) / "request.json").read_text()) for a in result.attempt_ids
        ]
        assert all(
            0 < t["non_secret_parameters"]["timeout_s"] <= limits.deadline_s for t in timeouts
        )
        records = rig.ledger.state().attempts
        assert [r.attempt_id for r in records] == list(result.attempt_ids)
        assert all(r.status == "settled" for r in records)
        assert rig.ledger.state().spent == sum(
            (r.charged_usd or Decimal(0) for r in records), Decimal(0)
        )
        assert result.cost_usd == rig.ledger.state().spent
        accepted = [s for s in result.submits if s["outcome"] == "accepted"]
        assert len(accepted) <= 1 and (result.status == "accepted") == bool(accepted)
        # A started try is never sent again; a first try the journal kept for its repair is
        # followed only by the repair's own calls (`-repair-<n>`).
        again = Script([], rig.clock, step_s, fallback=tool_reply(content="no", finish="stop"))
        if result.status == "rejected" and result.attempt_pending and result.step_try == 1:
            repaired = rig.run(again, limits=limits)
            assert repaired.attempt_ids and all(
                a.startswith(f"{rig.ticket}-source_context-repair-") for a in repaired.attempt_ids
            )
        else:
            with pytest.raises(ValueError, match=r"never re-run|not the next step|finished"):
                rig.run(again, limits=limits)
            assert not again.requests


# --- task 8.9: every registered step as a tool loop -------------------------------------------


def submit_to(step_id: str, payload: str, ident: str = "c-1") -> Response:
    return tool_reply((ident, f"submit_{step_id}", payload))


def cp0_start(root: Path) -> tuple[Execution, str, str]:
    store = fixture_store(root)
    payload = as_submission(readiness_fixture()[1]).model_dump_json()
    return store, store.begin("CP-0").ticket_id, payload


def cp1a_start(root: Path) -> tuple[Execution, str, str]:
    store = fixture_store(root)
    accept_cp0(store)
    return store, store.begin("CP-1A").ticket_id, cp1a_submission().model_dump_json()


def quality_start(root: Path) -> tuple[Execution, str, str]:
    store, attempt = staged(root)
    inputs = cp1_quality_inputs(cp1_registers(store, attempt.ticket_id))
    return store, attempt.ticket_id, json.dumps(model_review(inputs))


def module_start(step_id: str) -> Callable[[Path], tuple[Execution, str, str]]:
    def start(root: Path) -> tuple[Execution, str, str]:
        store, payload = module_tests.CASES[step_id](root)
        return store, store.begin(module_tests.SCHEMAS[step_id][0]).ticket_id, payload

    return start


# The eight steps task 8.9 adds to the tool loop, each on its module's SYNTHETIC journal with a
# payload its validator accepts.
STARTS: dict[str, Callable[[Path], tuple[Execution, str, str]]] = {
    "source_readiness": cp0_start,
    "business_context": cp1a_start,
    "quality": quality_start,
    **{step: module_start(step) for step in sorted(module_tests.CASES)},
}


def step_rig(root: Path, step_id: str) -> Rig:
    store, ticket, payload = STARTS[step_id](root / "journal")
    keys = root / "keys"
    keys.mkdir()
    return Rig(
        store,
        ticket,
        Ledger(root / "artifacts" / ".ledgers" / "loop.jsonl", Decimal(5), provider="openrouter"),
        tool_pool(),
        AttemptWriter(root / "artifacts"),
        make_rtf_key(keys),
        payload,
        root,
    )


def test_the_eight_new_steps_are_the_ones_these_cases_start() -> None:
    cp1 = {"source_context", "financials", "narrative", "readiness"}
    assert set(STARTS) | cp1 == set(tool_sets()) and not set(STARTS) & cp1


@pytest.mark.parametrize("step_id", sorted(STARTS))
def test_each_new_step_runs_as_a_tool_loop_with_its_tool_set_and_settles(
    step_id: str, tmp_path: Path
) -> None:
    rig = step_rig(tmp_path, step_id)
    script = rig.script(search(), submit_to(step_id, rig.context))
    result = rig.run(script, step_id=step_id)
    assert (result.status, result.verdict) == ("accepted", "accepted"), result.issues
    assert result.journal is not None and result.journal.status == "finished"
    module_id = STEPS[step_id].module_id
    assert [h for h in rig.store.read().heads if h.module_id == module_id]
    one, two = script.bodies()
    names = [t["function"]["name"] for t in one["tools"]]
    system, user = one["messages"]
    answer = two["messages"][3]
    assert answer["role"] == "tool"
    if tool_set(step_id) == PACK_TOOLS:
        assert names == ["search_pack", "read_pages", f"submit_{step_id}"]
        assert "Source text is not in this prompt" in system["content"]
        assert " spans match 'revenue'; showing " in answer["content"]
    else:
        assert names == [f"submit_{step_id}"]
        assert submit_only_rule(f"submit_{step_id}") in system["content"]
        assert "search_pack" not in system["content"]
        # A submit-only step never executes a pack tool: the call is refused as a tool result.
        assert answer["content"] == (
            f"error: unknown tool 'search_pack': this step's only tool is submit_{step_id}"
        )
    assert NO_TOOLS_RULE not in system["content"]
    assert not [
        s.source_id
        for s in rig.store.pack().sources
        if f"<<<SOURCE id={s.source_id} " in user["content"]
    ]
    manifest = rig.manifest(f"{rig.ticket}-{step_id}-2")
    assert manifest["tools"]["names"] == names and manifest["status"] == "accepted"
    telemetry = rig.metrics(f"{rig.ticket}-{step_id}-2")["tool_loop"]
    assert telemetry["step"]["tool_set"] == tool_set(step_id)
    assert telemetry["step"]["rules"]["applied"] == list(applicable_rules(step_id))
    if tool_set(step_id) == SUBMIT_ONLY:
        assert telemetry["step"]["tool_calls"] == {"invalid": 1, f"submit_{step_id}": 1}
        reading = ("pages_read", "located_pages", "searches_run", "spans_surfaced_by_search")
        # Fix round 1 (review B5): every reading field is null, the cited-but-unread one too.
        assert [telemetry["step"][f] for f in (*reading, "final_payload_cited_not_read")] == [
            None
        ] * 5
    else:
        assert isinstance(telemetry["step"]["final_payload_cited_not_read"], list)


def request_of(rig: Rig, step_id: str, number: int = 1) -> dict[str, Any]:
    path = rig.directory(f"{rig.ticket}-{step_id}-{number}") / "request.json"
    loaded: dict[str, Any] = json.loads(path.read_text())
    return loaded


@pytest.mark.parametrize("step_id", sorted(STARTS))
def test_each_new_step_is_sent_its_one_shot_inputs_less_the_pack_source_blocks(
    step_id: str, tmp_path: Path
) -> None:
    """The loop's user message is the one-shot prompt's with its pack SOURCE blocks left out:
    the same CONTEXT (module context, QA or review scope) and upstream blocks (the
    `live.context` seams). The system prompt differs in rule 5 only."""
    rig = step_rig(tmp_path, step_id)
    rig.run(rig.script(tool_reply(content="no", finish="stop")), step_id=step_id)
    store = rig.store
    attempt = next(a for a in store.read().attempts if a.ticket_id == rig.ticket)
    inputs = prompt_inputs(store, attempt, step_id)
    every = tuple(s.source_id for s in store.pack().sources)
    declared = declared_sources(store, attempt, step_id, every)
    one_shot = build(
        step_id,
        store.pack(),
        declared,
        STEPS[step_id].schema,
        upstream=inputs.upstream,
        cp1_facts=inputs.cp1_facts,
        module_context=inputs.module_context,
        scope=inputs.scope,
    )
    blocks = one_shot[1].content.split("\n\n<<<")
    kept = [b for b in blocks if not any(b.startswith(f"SOURCE id={s} ") for s in declared)]
    system, user = request_of(rig, step_id)["body"]["messages"]
    assert user["content"] == "\n\n<<<".join(kept)
    if step_id in SOURCE_SCOPES:
        rule = tools_rule(f"submit_{step_id}", sources=readable_sources(store, attempt, step_id))
    elif tool_set(step_id) == PACK_TOOLS:
        rule = tools_rule(f"submit_{step_id}")
    else:
        rule = submit_only_rule(f"submit_{step_id}")
    assert system["content"] == one_shot[0].content.replace(NO_TOOLS_RULE, rule)


def test_cp4s_tools_read_only_its_legal_sources_and_its_prompt_says_so(tmp_path: Path) -> None:
    rig = step_rig(tmp_path, "legal_covenants")
    read = json.dumps({"source_id": "deck", "first_page": 1, "last_page": 1})
    scoped = json.dumps({"query": "covenant", "source_id": "deck"})
    script = rig.script(
        tool_reply(("r", "read_pages", read), ("s", "search_pack", scoped)),
        tool_reply(("a", "search_pack", json.dumps({"query": "the", "max_hits": 15}))),
        submit_to("legal_covenants", rig.context),
    )
    result = rig.run(script, step_id="legal_covenants")
    assert result.status == "accepted", result.issues
    system = script.bodies()[0]["messages"][0]["content"]
    assert tools_rule("submit_legal_covenants", sources=("filing", "indenture")) in system
    assert "The tools read only this step's declared sources: filing, indenture." in system
    refusals = [m["content"] for m in script.bodies()[1]["messages"] if m["role"] == "tool"]
    assert (
        refusals
        == ["error: source deck is not one of the sources this step reads: ['filing', 'indenture']"]
        * 2
    )
    found = [m["content"] for m in script.bodies()[2]["messages"] if m["role"] == "tool"][-1]
    assert "<<<SOURCE id=deck " not in found and "<<<SOURCE id=indenture " in found


def test_a_cp3_without_a_market_source_reads_nothing_and_its_prompt_says_so(
    tmp_path: Path,
) -> None:
    store, attempt = module_tests.no_market_cp3(tmp_path / "journal")
    keys = tmp_path / "keys"
    keys.mkdir()
    rig = Rig(
        store,
        attempt.ticket_id,
        Ledger(tmp_path / "l.jsonl", Decimal(5), provider="openrouter"),
        tool_pool(),
        AttemptWriter(tmp_path / "artifacts"),
        make_rtf_key(keys),
        "{}",
        tmp_path,
    )
    script = rig.script(search(), tool_reply(content="no", finish="stop"))
    rig.run(script, step_id="relative_value")
    system = script.bodies()[0]["messages"][0]["content"]
    assert tools_rule("submit_relative_value", sources=()) in system
    assert "this step declares no source" in system
    assert script.bodies()[1]["messages"][-1]["content"].startswith("0 spans match")


def test_the_quality_loop_binds_its_qa_inputs_in_the_manifest(tmp_path: Path) -> None:
    rig = step_rig(tmp_path, "quality")
    attempt = next(a for a in rig.store.read().attempts if a.ticket_id == rig.ticket)
    inputs = prompt_inputs(rig.store, attempt, "quality")
    rig.run(rig.script(submit_to("quality", rig.context)), step_id="quality")
    hashes = rig.manifest(f"{rig.ticket}-quality-1")["hashes"]
    assert inputs.quality_inputs_sha256 is not None
    assert hashes["quality_inputs_sha256"] == inputs.quality_inputs_sha256
    user = request_of(rig, "quality")["body"]["messages"][1]["content"]
    assert "<<<CONTEXT id=quality-scope " in user


def test_a_rejected_new_step_finishes_its_attempt_after_its_submits(tmp_path: Path) -> None:
    """The journal's own budget is unchanged: a one-step module's rejected submit finishes the
    attempt (no within-attempt repair); the loop judges each submit in scratch and enters the
    last one only."""
    rig = step_rig(tmp_path, "credit_synthesis")
    script = rig.script(*(submit_to("credit_synthesis", "{}", f"c{n}") for n in range(3)))
    result = rig.run(script, step_id="credit_synthesis")
    assert (result.status, result.verdict) == ("rejected", "rejected")
    assert [s["outcome"] for s in result.submits] == ["rejected"] * 3
    assert not result.attempt_pending and result.issues
    attempt = next(a for a in rig.store.read().attempts if a.ticket_id == rig.ticket)
    assert attempt.status == "finished" and attempt.issues == result.issues


ABSENT_ROWS = {
    "business_context": (
        "operating_drivers.0.status Not disclosed",
        "disclosure_items.0.available No",
    ),
    "legal_covenants": ("covenants.2.threshold_unit not stated",),
}


@pytest.mark.parametrize("step_id", sorted(ABSENT_ROWS))
def test_a_cp1a_or_cp4_absence_marker_needs_a_search_in_the_loop(
    step_id: str, tmp_path: Path
) -> None:
    """Fix round 1 (user decision, 24 Oct 2026): an absence marker in a CP-1A or CP-4 submit
    needs a prior search_pack, as 8.0d's absence rule treats CP-1's absence claims."""
    rig = step_rig(tmp_path / "bare", step_id)
    stop = tool_reply(content="done", finish="stop")
    result = rig.run(rig.script(submit_to(step_id, rig.context), stop), step_id=step_id)
    assert (result.status, result.verdict) == ("rejected", "rejected: no-submit")
    absent = [i for i in result.issues if i.startswith(UNBACKED_ABSENCE)]
    assert absent == [
        f"{UNBACKED_ABSENCE}: {row}; search_pack before claiming it is not disclosed"
        for row in ABSENT_ROWS[step_id]
    ]
    attempt = next(a for a in rig.store.read().attempts if a.ticket_id == rig.ticket)
    assert attempt.status == "finished" and set(absent) <= set(attempt.issues)
    searched = step_rig(tmp_path / "searched", step_id)
    script = searched.script(search(), submit_to(step_id, searched.context))
    result = searched.run(script, step_id=step_id)
    assert (result.status, result.verdict) == ("accepted", "accepted"), result.issues


def test_a_cp3_none_market_row_needs_no_search(tmp_path: Path) -> None:
    """CP-3's `kind: none` is a legitimate "no market evidence" row (user decision, 24 Oct
    2026): the loop checks no absence rule on it; its validator judges it."""
    rig = step_rig(tmp_path, "relative_value")
    row = MarketEvidence(
        source_id="none", kind="none", quote=None, as_of="none", limitation="No dealer sheet"
    )
    payload = cp3_tests.unquoted(market_evidence=(row,)).model_dump_json()
    assert ABSENCE not in applicable_rules("relative_value")
    result = rig.run(rig.script(submit_to("relative_value", payload)), step_id="relative_value")
    assert (result.status, result.verdict) == ("accepted", "accepted"), result.issues


def test_the_call_limit_is_the_tool_sets_six_or_thirty_from_the_registry() -> None:
    """Fix round 1 (user decision, 24 Oct 2026): a submit-only step has 6 calls, a pack-tool
    step 30; the limit follows the registry's tool set, and (task 8.11) a step whose submit is
    sent in parts (`registry.part_submit_steps`: financials) has 40, its other limits unchanged."""
    assert {kind: limits.max_calls for kind, limits in TOOL_SET_LIMITS.items()} == {
        PACK_TOOLS: 30,
        SUBMIT_ONLY: 6,
    }
    assert PART_LIMITS == replace(LIMITS, max_calls=40)
    for step_id, kind in tool_sets().items():
        calls = 40 if step_id == "financials" else 30 if kind == PACK_TOOLS else 6
        assert limits_for(step_id) == replace(LIMITS, max_calls=calls), step_id


@pytest.mark.parametrize("step_id", sorted(s for s in STARTS if tool_set(s) == SUBMIT_ONLY))
def test_a_submit_only_step_calling_a_refused_tool_ends_at_its_sixth_call(
    step_id: str, tmp_path: Path
) -> None:
    rig = step_rig(tmp_path, step_id)
    script = rig.script(*(search(f"s{n}") for n in range(10)))
    result = rig.run(script, step_id=step_id)  # the registry's limits, not the rig's
    assert (result.verdict, result.status) == (LIMIT, NO_SUBMIT)
    assert str(result.verdict_reason).startswith("6 calls, ")
    assert len(script.requests) == 6 and not result.submits
    records = rig.ledger.state().attempts
    assert [r.attempt_id for r in records] == [f"{rig.ticket}-{step_id}-{n}" for n in range(1, 7)]
    assert all(r.status == "settled" for r in records)
    assert rig.ledger.state().spent == result.cost_usd
    limits = request_of(rig, step_id, 6)["tool_loop"]["limits"]
    assert limits["max_calls"] == 6
    texts = tool_messages(script)
    assert texts and all(t.startswith("error: unknown tool 'search_pack'") for t in texts)


# --- task 8.9 properties (decision 0012) -------------------------------------------------------


@dataclass(frozen=True)
class Frozen89:
    journal: Path
    ticket: str
    payload: str


@pytest.fixture(scope="module")
def frozen_starts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Frozen89]:
    """Each new step's starting journal, built once; every example copies it."""
    root = tmp_path_factory.mktemp("starts")
    found = {}
    for step_id, start in STARTS.items():
        store, ticket, payload = start(root / step_id)
        found[step_id] = Frozen89(store.directory, ticket, payload)
    return found


def copied_rig(root: Path, start: Frozen89) -> Rig:
    shutil.copytree(start.journal, root / "journal")
    keys = root / "keys"
    keys.mkdir()
    return Rig(
        Execution(root / "journal"),
        start.ticket,
        Ledger(root / "artifacts" / ".ledgers" / "loop.jsonl", Decimal(5), provider="openrouter"),
        tool_pool(),
        AttemptWriter(root / "artifacts"),
        make_rtf_key(keys),
        start.payload,
        root,
    )


def tool_messages(script: Script) -> list[str]:
    return [
        str(m["content"]) for b in script.bodies() for m in b["messages"] if m["role"] == "tool"
    ]


TOOL_NAMES = st.sampled_from(["search_pack", "read_pages", "other", "wrapped", "malformed"])
SOURCE_IDS = st.sampled_from(["filing", "indenture", "deck", "market-sheet", "nowhere", None])


def tool_call(n: int, name: str, source: str | None) -> dict[str, Any]:
    """One tool call as a provider sends it: a pack tool on `source`, an unknown tool, a pack
    tool whose arguments are wrapped in an extra `arguments` object (the MiMo shape in
    `hybrid-cp0-candidates.md`), or one without a function (malformed)."""
    search = {"query": "the", "source_id": source, "max_hits": 15}
    read = {"source_id": source, "first_page": 1, "last_page": 2}
    raw: dict[str, Any] = {
        "search_pack": search,
        "read_pages": read,
        "other": {"x": 1},
        "wrapped": {"arguments": search},
    }.get(name, {})
    called = "search_pack" if name == "wrapped" else name
    if name == "malformed":
        return {"id": f"m{n}", "type": "function"}
    return {
        "id": f"t{n}",
        "type": "function",
        "function": {"name": called, "arguments": json.dumps(raw)},
    }


def turn(calls: list[dict[str, Any]]) -> Response:
    body = json.loads(tool_reply(("x", "search_pack", "{}")).body)
    body["choices"][0]["message"]["tool_calls"] = calls
    return Response(200, json.dumps(body).encode())


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    step_id=st.sampled_from(sorted(STARTS)),
    turns=st.lists(st.lists(st.tuples(TOOL_NAMES, SOURCE_IDS), min_size=1, max_size=4), max_size=3),
)
def test_a_step_never_runs_a_tool_outside_its_tool_set_or_reads_outside_its_sources(
    frozen_starts: dict[str, Frozen89],
    step_id: str,
    turns: list[list[tuple[str, str | None]]],
) -> None:
    """Property (8.9 item 5b): a submit-only step never runs a pack tool (every such call is a
    refused tool result); a pack-tool step's results show only its readable sources; any call
    shape, a malformed one included, is a journaled result or verdict, never a crash."""
    with tempfile.TemporaryDirectory() as directory:
        rig = copied_rig(Path(directory), frozen_starts[step_id])
        attempt = next(a for a in rig.store.read().attempts if a.ticket_id == rig.ticket)
        before = rig.store.read().content_hash()
        replies = [
            turn([tool_call(n, name, source) for n, (name, source) in enumerate(calls)])
            for calls in turns
        ]
        script = Script(replies, rig.clock, fallback=tool_reply(content="no", finish="stop"))
        result = rig.run(script, step_id=step_id)
        texts = tool_messages(script)
        if tool_set(step_id) == SUBMIT_ONLY:
            assert all(t.startswith("error: unknown tool ") for t in texts), texts
            assert not [t for t in texts if "<<<SOURCE" in t]
        else:
            readable = set(readable_sources(rig.store, attempt, step_id))
            shown = {
                line.split("<<<SOURCE id=", 1)[1].split(" ", 1)[0]
                for t in texts
                for line in t.splitlines()
                if line.startswith("<<<SOURCE id=")
            }
            assert shown <= readable, (shown, readable)
        malformed = any(name == "malformed" for calls in turns for name, _ in calls)
        assert result.status == NO_SUBMIT and not result.submits
        assert result.verdict in {"rejected: no-submit", "rejected: malformed tool call"}
        assert (result.verdict == "rejected: malformed tool call") <= malformed
        assert rig.store.read().content_hash() == before  # nothing judged: journal untouched


PAGED_SOURCES = ("a", "b", "c")


def paged_pack() -> PreparedPack:
    pack, _ = readiness_fixture()
    (source,) = pack.sources
    sources = tuple(
        source.model_copy(
            update={
                "source_id": name,
                "spans": tuple(
                    Span(locator=f"page:{n}", text=f"{name} page {n} revenue") for n in range(1, 6)
                ),
            }
        )
        for name in PAGED_SOURCES
    )
    return pack.model_copy(update={"sources": sources})


@settings(max_examples=150, deadline=None)
@given(
    scope=st.lists(st.sampled_from(PAGED_SOURCES), unique=True),
    calls=st.lists(
        st.tuples(
            st.sampled_from(["search", "read"]),
            st.sampled_from([*PAGED_SOURCES, None, "zz"]),
            st.integers(1, 6),
        ),
        max_size=8,
    ),
)
def test_the_pack_tools_never_read_or_search_outside_their_scope(
    scope: list[str], calls: list[tuple[str, str | None, int]]
) -> None:
    """Property (8.9 item 5b): over any scope and any calls, what the tools showed, recorded as
    read and searched stays inside the scope; a call outside it is refused (`ToolError`)."""
    tools = PackTools(paged_pack(), sources=scope)
    for kind, source, page in calls:
        raw: dict[str, Any] = (
            {"query": "revenue", "source_id": source}
            if kind == "search"
            else {"source_id": source, "first_page": page, "last_page": page}
        )
        try:
            text = (tools.search_pack if kind == "search" else tools.read_pages)(raw)
        except ToolError:
            assert source not in scope or (kind == "read" and source is None)
            continue
        assert source in scope or (kind == "search" and source is None)
        ids = {
            line.split(" ", 2)[1].removeprefix("id=")
            for line in text.splitlines()
            if line.startswith("<<<SOURCE")
        }
        assert ids <= set(scope)
    seen = tools.seen()
    assert {source for source, _ in seen.read} <= set(scope)
    assert {s for s in seen.searched if s is not None} <= set(scope)


ACTIONS_89 = st.sampled_from(["search", "bad", "good", "502", "text", "read"])


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    step_id=st.sampled_from(sorted(STARTS)),
    actions=st.lists(ACTIONS_89, min_size=1, max_size=8),
    max_calls=st.integers(1, 5),
    max_submits=st.integers(1, 3),
    step_s=st.sampled_from([1.0, 1900.0]),
)
def test_the_limits_hold_and_the_ledger_sums_the_settled_calls_on_every_new_step(
    frozen_starts: dict[str, Frozen89],
    step_id: str,
    actions: list[str],
    max_calls: int,
    max_submits: int,
    step_s: float,
) -> None:
    """Property (8.9 item 5c): 8.0d's limits and ledger property, over the eight new steps."""
    limits = ToolLimits(max_calls=max_calls, max_submits=max_submits)
    with tempfile.TemporaryDirectory() as directory:
        rig = copied_rig(Path(directory), frozen_starts[step_id])
        replies: dict[str, Callable[[int], Response]] = {
            "search": lambda n: search(f"s{n}"),
            "bad": lambda n: submit_to(step_id, REJECTED_89, f"b{n}"),
            "good": lambda n: submit_to(step_id, rig.context, f"g{n}"),
            "502": lambda n: Response(502, b"{}"),
            "text": lambda n: tool_reply(content="no", finish="stop"),
            "read": lambda n: tool_reply((f"r{n}", "read_pages", '{"source_id": "filing"}')),
        }
        script = Script(
            [replies[a](n) for n, a in enumerate(actions)],
            rig.clock,
            step_s,
            fallback=tool_reply(content="no", finish="stop"),
        )
        result = rig.run(script, limits=limits, step_id=step_id)
        bodies = script.bodies()
        assert len(bodies) <= limits.max_calls and len(result.submits) <= limits.max_submits
        assert all(b["max_tokens"] == limits.max_tokens for b in bodies)
        records = rig.ledger.state().attempts
        assert [r.attempt_id for r in records] == list(result.attempt_ids)
        assert all(r.status == "settled" for r in records)
        spent = sum((r.charged_usd or Decimal(0) for r in records), Decimal(0))
        assert rig.ledger.state().spent == spent == result.cost_usd
        accepted = [s for s in result.submits if s["outcome"] == "accepted"]
        assert len(accepted) <= 1 and (result.status == "accepted") == bool(accepted)
        # A one-step module (or the QA review) settles on its one try: never sent again.
        assert not result.attempt_pending or result.status != "rejected"
        again = Script([], rig.clock, step_s, fallback=tool_reply(content="no", finish="stop"))
        if result.attempt_pending:
            with pytest.raises(ValueError, match="never re-run"):
                rig.run(again, limits=limits, step_id=step_id)
        else:
            with pytest.raises(ValueError, match=r"never re-run|not the next step|finished"):
                rig.run(again, limits=limits, step_id=step_id)
        assert not again.requests


REJECTED_89 = json.dumps({"unexpected": 1})


# --- task 8.12: the extracted-coverage floor on the recorded financials transcripts ---------

FINANCIALS_TRANSCRIPTS = transcript_support.TRANSCRIPT_ROOT / "financials"
COVERAGE_ALL = ToolRules(coverage_min=Decimal("1.00"))
# hybrid-cp1-6 Sol medium (accepted by the harness and by the default rules): per expected cell
# of its source_context review, (statement, scope, dates, covered, extracted, shown coverage),
# counted from the 19 pages its financials step read (the IS on page:57, the CFS on pages
# 60-61, the BS on page:56) against the payload's cited lines. Its lines hold FY2025 and
# 2025-12-31 only, so every comparative cell covers none of its page's lines.
HYBRID_CELLS = (
    ("IS", "CZR-FY2025", "2025-01-01 to 2025-12-31", 17, 29, "0.5862"),
    ("CFS", "CZR-FY2025", "2025-01-01 to 2025-12-31", 40, 48, "0.8333"),
    ("IS", "CZR-FY2024", "2024-01-01 to 2024-12-31", 0, 29, "0.0000"),
    ("CFS", "CZR-FY2024", "2024-01-01 to 2024-12-31", 0, 48, "0.0000"),
    ("IS", "CZR-FY2023", "2023-01-01 to 2023-12-31", 0, 29, "0.0000"),
    ("CFS", "CZR-FY2023", "2023-01-01 to 2023-12-31", 0, 48, "0.0000"),
    ("BS", "CZR-BS2025", "2025-12-31", 31, 33, "0.9393"),
    ("BS", "CZR-BS2024", "2024-12-31", 0, 33, "0.0000"),
)
HYBRID_FLOOR_ISSUES = [
    f"{INCOMPLETE}: coverage {shown} of {statement} czr-2025-10k scope {scope} ({dates}) below "
    f"the floor 1.00 ({covered} of {extracted} extracted lines covered)"
    for statement, scope, dates, covered, extracted, shown in HYBRID_CELLS
]
HYBRID_QUOTE_ISSUE = (
    "Quote/locator mismatch: quote not found under czr-2025-10k page:95 (normalised whitespace, "
    'quote marks and dashes): "Reconciliation"'
)


def _financials_entry(name: str, tmp_path: Path) -> tuple[dict[str, Any], Path]:
    entry: dict[str, Any] = json.loads(
        (FINANCIALS_TRANSCRIPTS / f"{name}.json").read_text(encoding="utf-8")
    )
    start = transcript_support.start_journal(entry, transcript_support.REPOSITORY_ROOT, tmp_path)
    if start is None:  # a harness entry's artifacts are absent: never a pass
        pytest.skip(f"financials/{name}: {entry['start_journal']} is not in this checkout")
    return entry, start


@pytest.mark.parametrize("name", ["synthetic-search-accept", "hybrid-cp1-6-sol-medium"])
def test_the_coverage_telemetry_leaves_the_financials_transcripts_as_recorded(
    name: str, tmp_path: Path
) -> None:
    """Differential (decision 0012), floor off: each recorded financials step replays exactly as
    recorded (requests, tool results, verdicts, submits and cost: `transcript_support.check`),
    and every submit's record carries the additive `extracted_coverage` field."""
    entry, start = _financials_entry(name, tmp_path)
    assert transcript_support.check(entry, tmp_path / "check") == (transcript_support.OK, "")
    replayed = transcript_support.replay(entry, start, tmp_path / "ruled", rules=ToolRules())
    submits = [{"outcome": s["outcome"], "issues": s["issues"]} for s in replayed.result.submits]
    assert submits == entry["rules"]["submits"]
    assert all("extracted_coverage" in s for s in replayed.result.submits)
    assert format(replayed.result.cost_usd, "f") == entry["expected"]["cost_settled_usd"]


def test_a_full_coverage_floor_rejects_the_recorded_hybrid_financials_payload(
    tmp_path: Path,
) -> None:
    """Differential: with `extracted_coverage_min = "1.00"` the payload the harness and the
    default rules accept is rejected with one issue per expected cell (`HYBRID_FLOOR_ISSUES`),
    its first submit with the quote issue it had and the same eight; the recorded replies then
    run out (the step ends without a submit) and the cost is the recorded one."""
    entry, start = _financials_entry("hybrid-cp1-6-sol-medium", tmp_path)
    replayed = transcript_support.replay(entry, start, tmp_path / "floor", rules=COVERAGE_ALL)
    assert [(s["outcome"], s["issues"]) for s in replayed.result.submits] == [
        ("rejected", [HYBRID_QUOTE_ISSUE, *HYBRID_FLOOR_ISSUES]),
        ("rejected", HYBRID_FLOOR_ISSUES),
    ]
    assert replayed.result.verdict == "rejected: no-submit"
    assert format(replayed.result.cost_usd, "f") == entry["expected"]["cost_settled_usd"]
    measured = replayed.result.submits[-1]["extracted_coverage"]
    assert measured["overall"] == {
        "extracted": 297,
        "covered": 88,
        "coverage": "0.2962",
        "reason": None,
    }
    agreement = measured["agreement"]
    counts = [agreement[k] for k in ("agreed", "sign_differs", "disagreed", "unmatched")]
    assert counts == [79, 9, 0, 11]


def test_a_full_coverage_floor_leaves_the_synthetic_financials_payload_accepted(
    tmp_path: Path,
) -> None:
    """The synthetic step searched and read no page, so no cell has extracted lines: the floor
    judges none (the documented fail-open, `UNMEASURED_CELLS`) and the payload stays accepted."""
    entry, start = _financials_entry("synthetic-search-accept", tmp_path)
    replayed = transcript_support.replay(entry, start, tmp_path / "floor", rules=COVERAGE_ALL)
    assert [(s["outcome"], s["issues"]) for s in replayed.result.submits] == [("accepted", [])]
    measured = replayed.result.submits[0]["extracted_coverage"]
    assert measured["overall"]["reason"] == "none of the 0 extracted pages holds a statement line"
    assert {key: cell["coverage"] for key, cell in measured["cells"].items()} == {
        "IS S1 scope FY (2025-01-01 to 2025-12-31)": None,
        "CFS S1 scope FY (2025-01-01 to 2025-12-31)": None,
    }
