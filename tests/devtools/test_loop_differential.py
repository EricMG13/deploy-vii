"""Task 8.0d: the product tool loop (`live.loop`) against the hybrid harness it ports.

The same scripted OpenRouter replies go to `devtools/hybrid_cp1.run_step` and to
`live.loop.run_tool_step` on copies of the same starting journal, with the evidence rules off
(the harness has none). Both must send the same requests (the one intended difference: the
harness appended its call-limit nudge to the last tool result, the product sends it as its own
user message, harness review C6), return the same tool results, judge the same submits the same
way, end with the same verdict and charge the same money per call.
"""

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.cp1_workflow import FinancialStage, FinancialSubmission
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview
from deploy_vii.execution import Execution
from deploy_vii.live.catalog import ModelSelection
from deploy_vii.live.client import ChatClient, Request, Response
from deploy_vii.live.context import declared_sources
from deploy_vii.live.ledger import Ledger
from deploy_vii.live.loop import ToolLimits, ToolStepResult, run_tool_step
from deploy_vii.live.retention import TOOL_TRANSCRIPT, AttemptLocator, AttemptWriter
from deploy_vii.live.runner import DispatchResult, StepSpec, dispatch, repair_prompt
from deploy_vii.live.settings import StepEffort
from deploy_vii.live.submission import STEPS, quality_inputs, submit_model_payload
from deploy_vii.live.tools import ToolRules, cited_locators
from deploy_vii.registry import tool_loop_steps
from devtools import hybrid_cp0 as cp0
from devtools import hybrid_cp1 as cp1
from tests.devtools.test_hybrid_cp0 import PARAMETERS, PRICING, reply
from tests.devtools.test_hybrid_cp1 import CELL, Case, case, make_harness
from tests.product import test_live_loop as loop_tests
from tests.product.live_support import catalog_of, catalog_row, make_rtf_key, ok
from tests.product.test_cp1_workflow import at_ceiling
from tests.product.test_execution import step_text
from tests.product.test_narrative import populated
from tests.product.test_workflow import cp1_case

__all__ = ["case"]  # the module-scoped CP-1 case fixture, shared with the harness tests
SEARCH = ("s", "search_pack", json.dumps({"query": "revenue", "max_hits": 2}))


def search(ident: str = "s") -> Response:
    return reply((ident, "search_pack", json.dumps({"query": "revenue", "max_hits": 2})))


def submit(payload: str, ident: str = "c") -> Response:
    return reply((ident, "submit_source_context", payload))


def text_only() -> Response:
    body = json.loads(reply().body)
    body["choices"][0]["message"] = {"role": "assistant", "content": "done"}
    body["choices"][0]["finish_reason"] = "stop"
    return Response(200, json.dumps(body).encode())


def malformed() -> Response:
    body = json.loads(search().body)
    del body["choices"][0]["message"]["tool_calls"][0]["function"]
    return Response(200, json.dumps(body).encode())


class Recorder:
    def __init__(self, replies: list[Response]) -> None:
        self.replies, self.bodies = list(replies), []

    def __call__(self, request: Request) -> Response:
        self.bodies.append(json.loads(request.body or b"{}"))
        return self.replies.pop(0)


def start(case: Case, directory: Path) -> tuple[Path, str]:
    shutil.copytree(case.frozen, directory)
    return directory, Execution(directory).begin("CP-1").ticket_id


def without_nudge(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The product conversation in the harness's form: each nudge user message folded into the
    turn's last tool result, as the harness wrote it."""
    folded: list[dict[str, Any]] = []
    for message in messages:
        if message["role"] == "user" and message["content"].startswith("Harness: "):
            assert folded[-1]["role"] == "tool"
            folded[-1] = folded[-1] | {"content": f"{folded[-1]['content']}\n{message['content']}"}
            continue
        folded.append(message)
    return folded


def run_both(
    case: Case, tmp_path: Path, script: Callable[[], list[Response]]
) -> tuple[Recorder, cp1.StepRun, Recorder, ToolStepResult, Path]:
    base, ticket = start(case, tmp_path / "base")
    harness_side = Recorder(script())
    (tmp_path / "h").mkdir()
    harness = make_harness(tmp_path / "h", harness_side, case.frozen)
    step = cp1.StepRun("source_context", tmp_path / "h" / "step")
    cp1.run_step(harness, CELL["sol-medium"], step, base, ticket)
    shutil.copytree(base, tmp_path / "p-journal")
    product_side = Recorder(script())
    row = catalog_row(
        cp0.MODEL, parameters=PARAMETERS, pricing=PRICING, efforts=("low", "medium", "high")
    )
    pool = catalog_of(row).pin_selected("t", (ModelSelection(cp0.MODEL, None),))
    keys = tmp_path / "keys"
    keys.mkdir()
    writer = AttemptWriter(tmp_path / "p")
    ticks = iter(range(100_000))
    result = run_tool_step(
        StepSpec("source_context", "diff", ()),
        store=Execution(tmp_path / "p-journal"),
        ticket_id=ticket,
        ledger=Ledger(tmp_path / "p.jsonl", Decimal(15)),
        pool=pool,
        seed=0,
        client=ChatClient(product_side),
        writer=writer,
        key_path=make_rtf_key(keys),
        key_index=1,
        bytes_per_token=Decimal("3.0"),
        effort=StepEffort("medium", "medium"),  # no escalation: the harness has none
        rules=ToolRules(checked=()),
        limits=ToolLimits(deadline_s=cp1.DEADLINE_S),
        monotonic=lambda: float(next(ticks)),
        sleep=lambda _: None,
    )
    return harness_side, step, product_side, result, tmp_path / "p" / "t" / "diff"


def product_log(directory: Path, result: ToolStepResult) -> list[dict[str, Any]]:
    entries = []
    for attempt in result.attempt_ids:
        path = directory / cp0.MODEL.replace("/", "__") / attempt / TOOL_TRANSCRIPT
        entries += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return entries


SCRIPTS: dict[str, Callable[[Case], list[Response]]] = {
    "search-then-accept": lambda c: [search(), submit(c.context)],
    "three-rejections": lambda c: [submit("{}", "a"), submit("{}", "b"), submit("{}", "c")],
    "reject-then-accept-then-ignored": lambda c: [
        submit("{}", "a"),
        reply(("b", "submit_source_context", c.context), ("late", *SEARCH[1:])),
    ],
    "bad-arguments-then-no-submit": lambda c: [
        reply(("x", "read_pages", "not json"), ("y", "nope", "{}"), ("z", *SEARCH[1:2], "[]")),
        text_only(),
    ],
    "malformed": lambda c: [malformed()],
    "limit-with-nudges": lambda c: [search(f"s{n}") for n in range(cp1.MAX_CALLS)],
}


@pytest.mark.parametrize("name", SCRIPTS)
def test_the_loop_and_the_harness_agree_on_the_same_replies(
    case: Case, tmp_path: Path, name: str
) -> None:
    harness_side, step, product_side, result, directory = run_both(
        case, tmp_path, lambda: SCRIPTS[name](case)
    )
    # Requests: identical bodies, the nudge's placement aside.
    assert len(harness_side.bodies) == len(product_side.bodies) == len(result.attempt_ids)
    for theirs, ours in zip(harness_side.bodies, product_side.bodies, strict=True):
        assert ours | {"messages": without_nudge(ours["messages"])} == theirs
    # Tool results, statuses and the submits' verdicts.
    harness_log = [
        json.loads(line)
        for line in (step.directory / TOOL_TRANSCRIPT).read_text(encoding="utf-8").splitlines()
    ]
    ours_log = product_log(directory, result)
    keys = ("call", "index", "name", "arguments", "status", "result", "problem")

    def calls(log: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return [tuple(item.get(k) for k in keys) for item in log if "nudge" not in item]

    assert calls(ours_log) == calls(harness_log)
    assert [e["call"] for e in ours_log if "nudge" in e] == [
        e["call"] for e in harness_log if "nudge" in e
    ]
    assert [(s["outcome"], s["issues"]) for s in result.submits] == [
        (s["outcome"], s["issues"]) for s in step.submits
    ]
    assert result.verdict == step.verdict
    # The reasons agree; a limit's elapsed seconds are each clock's own.
    assert (result.verdict_reason or "").split(",")[0] == (step.verdict_reason or "").split(",")[0]
    # Money: the same charge on every call, and the same reservation until a nudge is sent (its
    # own user message is a few bytes longer than the harness's appended line).
    ledger = Ledger(tmp_path / "p.jsonl", Decimal(15)).state().attempts
    assert [r.charged_usd for r in ledger] == [
        c.settlement.charged if c.settlement else None for c in step.calls
    ]
    nudged = min((e["call"] for e in ours_log if "nudge" in e), default=len(ledger))
    pairs = list(zip(ledger, step.calls, strict=True))
    assert all(r.reserved_usd == c.reserved_usd for r, c in pairs[:nudged])
    assert all(r.reserved_usd >= c.reserved_usd for r, c in pairs[nudged:])


# --- task 8.9: the tool loop against the one-shot dispatch, every registered step ------------
#
# Every live step now runs as a tool loop; the one-shot `runner.dispatch` stays (it is only out
# of the registry's plan) and is the reference here. On copies of the same starting journal the
# same payload goes once through `dispatch` and once through `run_tool_step`, which first
# searches and reads every page the payload cites (so the evidence rules, on at their
# defaults, find nothing) and then submits it. Both must reach the same verdict, issues,
# within-attempt state, journal records (retained payloads with Python's bindings, outputs,
# settled heads) and repair: the step's repair within the attempt for a CP-1 stage, the MC-7
# repair attempt's REPAIR issues for a settling step.

CP1_FIVE = ("source_context", "financials", "narrative", "readiness", "quality")
# A payload every step's contract refuses (an unknown field; the shapes forbid extras).
REJECTED = json.dumps({"unexpected": 1})


@dataclass(frozen=True)
class Start:
    journal: Path
    ticket: str
    payload: str


def cp1_payload(
    store: Execution, ticket: str, step_id: str, context: str, extraction: FinancialSubmission
) -> str:
    """A valid payload for `step_id` built from the journal as it stands (the CLI tests'
    `Chain.payload`)."""
    attempt = next(a for a in store.read().attempts if a.ticket_id == ticket)
    valid = {s.step_id: s for s in attempt.steps if s.status == "valid"}
    if step_id == "source_context":
        return context
    if step_id == "financials":
        bound = {"context_step_sha256": valid["source_context"].content_hash()}
        return extraction.model_copy(update=bound).model_dump_json()
    if step_id == "narrative":
        stage = FinancialStage.model_validate_json(step_text(store, valid["financials"]))
        return populated(stage.narrative_inputs).model_dump_json()
    if step_id == "readiness":
        inputs = DownstreamInputs.model_validate_json(step_text(store, valid["narrative"]))
        return DownstreamReview(inputs_sha256=inputs.content_hash()).model_dump_json()
    review = json.loads(at_ceiling(quality_inputs(store, ticket)).model_dump_json())
    del review["inputs_sha256"]  # Python binds it
    return json.dumps(review)


@pytest.fixture(scope="module")
def starts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Start]:
    """Each registered step's starting journal (frozen) and a payload its validator accepts:
    CP-1's five on the synthetic CP-1 case, built step by step; the others on their modules'
    SYNTHETIC journals (`tests.product.test_live_loop.STARTS`)."""
    root = tmp_path_factory.mktemp("one-shot-diff")
    seed, _, extraction = cp1_case(root / "seed")
    review = seed.payload(seed.read().attempts[0].steps[0].payload_sha256)
    context = seed.payload(seed.read().attempts[1].steps[0].payload_sha256)
    store = Execution.create(root / "cp1", seed.pack())
    assert not submit_cp0_review(store, store.begin("CP-0").ticket_id, review).issues
    ticket = store.begin("CP-1").ticket_id
    found: dict[str, Start] = {}
    for step_id in CP1_FIVE:
        payload = cp1_payload(store, ticket, step_id, context, extraction)
        shutil.copytree(store.directory, root / f"at-{step_id}")
        found[step_id] = Start(root / f"at-{step_id}", ticket, payload)
        entered = submit_model_payload(store, ticket, step_id, payload).journal
        assert entered.issues == () and entered.steps[-1].status == "valid", entered.issues
    for step_id, begin in loop_tests.STARTS.items():
        if step_id not in found:
            journal, ticket, payload = begin(root / f"m-{step_id}")
            found[step_id] = Start(journal.directory, ticket, payload)
    assert set(found) == tool_loop_steps()
    return found


def journal_record(store: Execution, ticket: str) -> dict[str, Any]:
    """What the journal holds for the ticket and every head, ids and hashes included."""
    attempt = next(a for a in store.read().attempts if a.ticket_id == ticket)

    def steps(items: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        return [
            (s.step_id, s.status, s.payload_sha256, s.output_sha256, s.issues, s.inputs)
            for s in items
        ]

    return {
        "status": attempt.status,
        "issues": attempt.issues,
        "result_sha256": attempt.result_sha256,
        "steps": steps(attempt.steps),
        "step_repairs": steps(attempt.step_repairs),
        "retained": [store.payload(s.payload_sha256) for s in attempt.steps],
        "heads": [(h.module_id, h.status, h.result_sha256) for h in store.read().heads],
    }


@dataclass
class Side:
    store: Execution
    ledger: Ledger
    writer: AttemptWriter
    key: Path


def side(start: Start, directory: Path) -> Side:
    shutil.copytree(start.journal, directory / "journal")
    keys = directory / "keys"
    keys.mkdir()
    return Side(
        Execution(directory / "journal"),
        Ledger(directory / "ledger.jsonl", Decimal(50), provider="openrouter"),
        AttemptWriter(directory / "artifacts"),
        make_rtf_key(keys),
    )


def run_one_shot(step_id: str, ticket: str, payload: str, there: Side) -> DispatchResult:
    store = there.store
    attempt = next(a for a in store.read().attempts if a.ticket_id == ticket)
    every = tuple(s.source_id for s in store.pack().sources)
    return dispatch(
        StepSpec(step_id, "diff", declared_sources(store, attempt, step_id, every)),
        store=store,
        ticket_id=ticket,
        ledger=there.ledger,
        pool=loop_tests.tool_pool(),
        seed=0,
        client=ChatClient(lambda _: ok(payload, model=loop_tests.MODEL)),
        writer=there.writer,
        key_path=there.key,
        key_index=1,
        bytes_per_token=Decimal("3.0"),
        effort="medium",
        sleep=lambda _: None,
    )


def reading(payload: str) -> list[tuple[str, str, str]]:
    """A search, then one `read_pages` per page the payload cites."""
    calls = [("s", "search_pack", json.dumps({"query": "revenue"}))]
    for n, (source, locator) in enumerate(sorted(cited_locators(payload))):
        if locator.startswith("page:"):
            page = int(locator.removeprefix("page:"))
            raw = {"source_id": source, "first_page": page, "last_page": page}
            calls.append((f"r{n}", "read_pages", json.dumps(raw)))
    return calls


def run_looped(step_id: str, ticket: str, payload: str, there: Side) -> ToolStepResult:
    replies = [
        loop_tests.tool_reply(*reading(payload)),
        loop_tests.tool_reply(("c", f"submit_{step_id}", payload)),
    ]
    stop = loop_tests.tool_reply(content="done", finish="stop")
    ticks = iter(range(100_000))
    return run_tool_step(
        StepSpec(step_id, "diff", ()),
        store=there.store,
        ticket_id=ticket,
        ledger=there.ledger,
        pool=loop_tests.tool_pool(),
        seed=0,
        client=ChatClient(lambda _: replies.pop(0) if replies else stop),
        writer=there.writer,
        key_path=there.key,
        key_index=1,
        bytes_per_token=Decimal("3.0"),
        effort=StepEffort.of("medium"),
        rules=ToolRules(),
        monotonic=lambda: float(next(ticks)),
        sleep=lambda _: None,
    )


def verdict(result: DispatchResult | ToolStepResult) -> tuple[Any, ...]:
    return (result.status, result.issues, result.attempt_pending, result.step_try)


def repair_block(directory: Path) -> str | None:
    """The REPAIR block of the request retained in `directory` (None without one)."""
    body = json.loads((directory / "request.json").read_text(encoding="utf-8"))["body"]
    user = next(m["content"] for m in body["messages"] if m["role"] == "user")
    marker = "<<<REPAIR id=prior-validation-issues"
    return marker + user.split(marker, 1)[1] if marker in user else None


@pytest.mark.parametrize("variant", ["valid", "rejected"])
@pytest.mark.parametrize("step_id", sorted(tool_loop_steps()))
def test_the_loop_and_the_one_shot_dispatch_agree_on_the_same_payload(
    starts: dict[str, Start], tmp_path: Path, step_id: str, variant: str
) -> None:
    start = starts[step_id]
    payload = start.payload if variant == "valid" else REJECTED
    one, two = side(start, tmp_path / "one-shot"), side(start, tmp_path / "loop")
    reference = run_one_shot(step_id, start.ticket, payload, one)
    looped = run_looped(step_id, start.ticket, payload, two)
    assert verdict(looped) == verdict(reference)
    assert reference.status == ("accepted" if variant == "valid" else "rejected")
    assert journal_record(two.store, start.ticket) == journal_record(one.store, start.ticket)
    if variant == "valid":
        return
    if reference.attempt_pending:  # a CP-1 stage: its one repair within the attempt
        assert reference.step_try == 1 and step_id in CP1_FIVE[:-1]
        fixed_one = run_one_shot(step_id, start.ticket, start.payload, one)
        fixed_two = run_looped(step_id, start.ticket, start.payload, two)
        assert verdict(fixed_two) == verdict(fixed_one) and fixed_one.step_try == 2
        assert fixed_one.status == "accepted"
        assert journal_record(two.store, start.ticket) == journal_record(one.store, start.ticket)
        first_call = two.writer.path_for(
            replace(
                AttemptLocator("loop", "diff", loop_tests.MODEL, ""),
                attempt=fixed_two.attempt_ids[0],
            )
        )
        assert repair_block(first_call) == repair_block(fixed_one.directory) is not None
        return
    # A settling step: the attempt is finished; the MC-7 repair attempt carries the same issues.
    module_id = STEPS[step_id].module_id
    again = [s.store.begin(module_id) for s in (one, two)]
    prompts = [
        repair_prompt(s.store.read(), a, step_id) for s, a in zip((one, two), again, strict=True)
    ]
    assert prompts[0] == prompts[1] and prompts[0].issues == reference.issues
