"""Task 8.0d: a CP-1 stage as a tool loop, with injected transports and a fake clock only."""

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.execution import Execution
from deploy_vii.live import loop
from deploy_vii.live.catalog import ModelSelection, PinnedPool
from deploy_vii.live.client import ChatClient, ChatResult, Request, Response, TransportError, Usage
from deploy_vii.live.credit import CreditExhausted
from deploy_vii.live.ledger import CapExceeded, Ledger
from deploy_vii.live.loop import (
    LIMIT,
    LIMITS,
    NO_SUBMIT,
    ToolLimits,
    ToolStepResult,
    call_nudge,
    issue_class,
    run_tool_step,
    transient,
)
from deploy_vii.live.prompts import tools_rule
from deploy_vii.live.retention import TOOL_TRANSCRIPT, AttemptWriter
from deploy_vii.live.runner import (
    IN_FLIGHT_EXHAUSTED_MARK,
    IN_FLIGHT_SETTLE_MARK,
    StepSpec,
    in_flight_refused,
)
from deploy_vii.live.settings import StepEffort, load_settings
from deploy_vii.live.tools import UNBACKED_ABSENCE, PackTools, ToolRules
from tests.product.live_support import catalog_of, catalog_row, make_rtf_key
from tests.product.test_live_credit import CREDIT_402, IN_FLIGHT_402
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
        limits: ToolLimits = LIMITS,
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
