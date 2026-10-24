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
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from deploy_vii.execution import Execution
from deploy_vii.live.catalog import ModelSelection
from deploy_vii.live.client import ChatClient, Request, Response
from deploy_vii.live.ledger import Ledger
from deploy_vii.live.loop import ToolLimits, ToolStepResult, run_tool_step
from deploy_vii.live.retention import TOOL_TRANSCRIPT, AttemptWriter
from deploy_vii.live.runner import StepSpec
from deploy_vii.live.settings import StepEffort
from deploy_vii.live.tools import ToolRules
from devtools import hybrid_cp0 as cp0
from devtools import hybrid_cp1 as cp1
from tests.devtools.test_hybrid_cp0 import PARAMETERS, PRICING, reply
from tests.devtools.test_hybrid_cp1 import CELL, Case, case, make_harness
from tests.product.live_support import catalog_of, catalog_row, make_rtf_key

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
