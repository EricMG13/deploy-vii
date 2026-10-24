"""Offline tests of the hybrid CP-1 harness: fake transport, synthetic CP-1 case, real journal."""

import hashlib
import json
import random
import re
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
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
from deploy_vii.live.credential import CredentialError, LoadedKey
from deploy_vii.live.ledger import Ledger
from deploy_vii.live.prompts import build
from deploy_vii.live.runner import _upstream, prompt_token_bound
from deploy_vii.live.schema import strict_schema
from deploy_vii.live.submission import STEPS, submit_model_payload
from devtools import hybrid_cp0 as cp0
from devtools import hybrid_cp1 as cp1
from tests.devtools.test_hybrid_cp0 import PARAMETERS, PRICING, SETTINGS, reply, unexpected_send
from tests.product.live_support import FAKE_KEY, FakeTransport, catalog_of, catalog_row
from tests.product.test_narrative import populated
from tests.product.test_workflow import cp1_case

ANT_KEY = "sk-ant-api03-TESTONLY-not-a-real-key-0123456789"
OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"
CELL = {cell.cell_id: cell for cell in cp1.CELLS}
ANT_USAGE: dict[str, Any] = {
    "input_tokens": 1000,
    "cache_creation_input_tokens": 2000,
    "cache_read_input_tokens": 3000,
    "output_tokens": 400,
    "output_tokens_details": {"thinking_tokens": 300},
    "cache_creation": {"ephemeral_5m_input_tokens": 2000, "ephemeral_1h_input_tokens": 0},
}
TOOL_CHOICE_400 = Response(
    400,
    json.dumps(
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                # The documented text (claude-api reference, model-migration.md).
                "message": 'tool_choice: type "tool" and "any" are not supported for this model.',
            },
        }
    ).encode(),
)


@dataclass(frozen=True)
class Case:
    frozen: Path  # an execution journal whose only module is an accepted CP-0
    context: str  # a valid source_context payload
    extraction: FinancialSubmission  # valid once its context_step_sha256 is bound


@pytest.fixture(scope="module")
def case(tmp_path_factory: pytest.TempPathFactory) -> Case:
    root = tmp_path_factory.mktemp("cp1-case")
    store, _, extraction = cp1_case(root / "seed")
    snapshot = store.read()
    review = store.payload(snapshot.attempts[0].steps[0].payload_sha256)
    frozen = Execution.create(root / "frozen", store.pack())
    assert not submit_cp0_review(frozen, frozen.begin("CP-0").ticket_id, review).issues
    context = store.payload(snapshot.attempts[1].steps[0].payload_sha256)
    return Case(root / "frozen", context, extraction)


class Model:
    """A perfect model for one cell. It keeps its own copy of the frozen CP-0 journal, enters each
    step's correct payload there to learn the next step's inputs, and submits that payload with
    every hash binding left out, as M7's sent schemas do (Python pre-fills them)."""

    def __init__(self, case: Case, directory: Path, model: str = OPUS) -> None:
        shutil.copytree(case.frozen, directory)
        self.case, self.model, self.store = case, model, Execution(directory)
        self.ticket = self.store.begin("CP-1").ticket_id

    def output(self, index: int) -> str:
        attempt = next(a for a in self.store.read().attempts if a.ticket_id == self.ticket)
        return self.store.step_output(attempt.steps[index].output_sha256)

    def payload(self, step_id: str) -> str:
        if step_id == "source_context":
            return self.case.context
        if step_id == "financials":
            document = json.loads(self.case.extraction.model_dump_json())
            del document["context_step_sha256"]
        elif step_id == "narrative":
            stage = FinancialStage.model_validate_json(self.output(1))
            document = json.loads(populated(stage.narrative_inputs).model_dump_json())
            del document["inputs_sha256"]
        else:
            inputs = DownstreamInputs.model_validate_json(self.output(2))
            review = DownstreamReview(inputs_sha256=inputs.content_hash())
            document = json.loads(review.model_dump_json())
            del document["inputs_sha256"]
        return json.dumps(document)

    def __call__(self, request: Request) -> Response:
        step_id, _ = asked(request)
        payload = self.payload(step_id)
        entered = submit_model_payload(self.store, self.ticket, step_id, payload).journal
        assert entered.steps[-1].status == "valid", entered.steps[-1].issues
        if request.url == cp1.ANTHROPIC_URL:
            return ant_stream(("t1", f"submit_{step_id}", payload), model=self.model)
        answer = reply(("c1", f"submit_{step_id}", payload))
        if self.model == OPUS:  # the default: Sol is served, as `reply` states
            return answer
        served = json.loads(answer.body) | {"model": self.model}
        return Response(answer.status, json.dumps(served).encode())


def body_of(request: Request) -> dict[str, Any]:
    return dict(json.loads(request.body or b"{}", parse_float=Decimal))


def asked(request: Request) -> tuple[str, str]:
    """(step id, user prompt) of a sent request, Anthropic or OpenRouter shaped."""
    body = body_of(request)
    names = [t.get("name") or t["function"]["name"] for t in body["tools"]]
    step_id = next(n for n in names if n.startswith("submit_")).removeprefix("submit_")
    user = next(m for m in body["messages"] if m["role"] == "user")["content"]
    return step_id, user


def ant_reply(
    *calls: tuple[str, str, str],
    model: str = OPUS,
    stop: str = "tool_use",
    usage: dict[str, Any] | None = None,
) -> Response:
    """A Messages reply: a thinking block, then tool_use blocks whose `input` is the given JSON
    text spliced in verbatim (so its numbers keep their digits)."""
    content: list[dict[str, Any]] = [
        {"type": "thinking", "thinking": "Plan the step.", "signature": "opaque-signature=="}
    ]
    for n, (ident, name, _) in enumerate(calls):
        content.append({"type": "tool_use", "id": ident, "name": name, "input": f"@INPUT{n}@"})
    text = json.dumps(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop,
            "usage": ANT_USAGE if usage is None else usage,
        }
    )
    for n, (_, _, raw) in enumerate(calls):
        text = text.replace(json.dumps(f"@INPUT{n}@"), raw)
    return Response(200, text.encode())


def sse(*events: dict[str, Any]) -> bytes:
    """Server-sent events as the Messages API streams them (`event:` then `data:` lines)."""
    return b"".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode() for event in events
    )


def delta(index: int, kind: str, **value: str) -> dict[str, Any]:
    return {"type": "content_block_delta", "index": index, "delta": {"type": kind, **value}}


def stream_events(
    *calls: tuple[str, str, str],
    model: str = OPUS,
    stop: str = "tool_use",
    usage: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The events of `ant_reply`'s message: input-side usage on message_start, output usage on
    message_delta, the thinking text and each tool input's JSON split across deltas, a ping."""
    usage = ANT_USAGE if usage is None else usage
    late = ("output_tokens", "output_tokens_details")
    early = {k: v for k, v in usage.items() if k not in late} | {"output_tokens": 1}
    message = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [],
        "stop_reason": None,
        "usage": early,
    }
    thinking = {"type": "thinking", "thinking": "", "signature": ""}
    events: list[dict[str, Any]] = [
        {"type": "message_start", "message": message},
        {"type": "content_block_start", "index": 0, "content_block": thinking},
        delta(0, "thinking_delta", thinking="Plan the "),
        {"type": "ping"},
        delta(0, "thinking_delta", thinking="step."),
        delta(0, "signature_delta", signature="opaque-signature=="),
        {"type": "content_block_stop", "index": 0},
    ]
    for index, (ident, name, raw) in enumerate(calls, start=1):
        half = len(raw) // 2
        block = {"type": "tool_use", "id": ident, "name": name, "input": {}}
        events.append({"type": "content_block_start", "index": index, "content_block": block})
        events.append(delta(index, "input_json_delta", partial_json=raw[:half]))
        events.append(delta(index, "input_json_delta", partial_json=raw[half:]))
        events.append({"type": "content_block_stop", "index": index})
    final = {"delta": {"stop_reason": stop, "stop_sequence": None}}
    events.append(
        {"type": "message_delta", **final, "usage": {k: usage[k] for k in late if k in usage}}
    )
    events.append({"type": "message_stop"})
    return events


def ant_stream(
    *calls: tuple[str, str, str],
    model: str = OPUS,
    stop: str = "tool_use",
    usage: dict[str, Any] | None = None,
) -> Response:
    """`ant_reply`'s message, streamed."""
    return Response(200, sse(*stream_events(*calls, model=model, stop=stop, usage=usage)))


def as_stream(transport: Callable[[Request], Response]) -> cp1.StreamTransport:
    """A stream transport over a fake transport: its reply body, line by line."""

    def open_stream(request: Request, idle_s: float) -> cp1.Stream:
        response = transport(request)
        return cp1.Stream(response.status, iter(response.body.splitlines(keepends=True)))

    return open_stream


def make_harness(
    tmp_path: Path,
    transport: Callable[[Request], Response],
    frozen: Path,
    *,
    caps: dict[str, Decimal] | None = None,
) -> cp1.Harness:
    row = catalog_row(
        cp0.MODEL, parameters=PARAMETERS, pricing=PRICING, efforts=("low", "medium", "high")
    )
    pool = catalog_of(row).pin_selected("t", (ModelSelection(cp0.MODEL, None),))
    candidate = pool.candidate(cp0.MODEL)
    caps = caps or cp1.CAPS
    batch = tmp_path / "batch"
    batch.mkdir()
    return cp1.Harness(
        cp0_journal=frozen,
        providers={
            "openrouter": cp1.OpenRouter(
                ChatClient(transport), {cp0.MODEL: candidate}, Decimal("3.0")
            ),
            "anthropic": cp1.Anthropic(as_stream(transport), Decimal("3.0")),
        },
        ledgers={
            name: Ledger(tmp_path / ".ledgers" / f"t-{name}.jsonl", caps[name]) for name in caps
        },
        keys={"openrouter": FAKE_KEY, "anthropic": ANT_KEY},
        batch_directory=batch,
    )


def runs(harness: cp1.Harness, *cell_ids: str) -> list[cp1.CellRun]:
    return [
        cp1.CellRun(CELL[c], n, harness.batch_directory / c)
        for n, c in enumerate(cell_ids, start=1)
    ]


def tree_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        digest.update(str(path.relative_to(directory)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


# --- prompt ----------------------------------------------------------------------------------


def test_the_step_prompt_is_the_runner_prompt_with_its_upstream_blocks(
    case: Case, tmp_path: Path
) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(case.frozen, copy)
    store = Execution(copy)
    ticket = store.begin("CP-1").ticket_id
    submit_model_payload(store, ticket, "source_context", case.context)
    attempt = next(a for a in store.read().attempts if a.ticket_id == ticket)
    upstream = _upstream(store, attempt, "financials")
    assert [(u.input_id, u.projection) for u in upstream] == [("step:source_context", "full")]
    pack = store.pack()
    system, user = cp1.hybrid_prompt("financials", pack, upstream)
    one_shot = build("financials", pack, (), STEPS["financials"].schema, upstream=upstream)
    assert user == one_shot[1].content  # CONTEXT and step: blocks word for word
    assert system == one_shot[0].content.replace(
        cp0.NO_TOOLS_RULE, cp0.tools_rule("submit_financials")
    )
    assert "submit_financials" in system and cp0.NO_TOOLS_RULE not in system
    assert re.findall(r"<<<SOURCE id=(\S+)", user) == ["step:source_context"]
    assert cp0.TOOLS_RULE == cp0.tools_rule("submit_readiness")


def test_each_step_offers_the_pack_tools_and_its_own_submit_schema() -> None:
    for step_id in cp1.CP1_STEPS:
        tools = cp1.step_tools(step_id)
        assert [name for name, _, _ in tools] == ["search_pack", "read_pages", f"submit_{step_id}"]
        assert tools[2][2] == strict_schema(STEPS[step_id].schema)


# --- Anthropic adapter -----------------------------------------------------------------------


def test_the_anthropic_request_has_the_documented_shape() -> None:
    transport = FakeTransport(ant_stream(("t1", "search_pack", '{"query": "covenant"}')))
    provider = cp1.Anthropic(as_stream(transport), Decimal("3.0"))
    tools = cp1.step_tools("source_context")
    prepared = provider.prepare(
        CELL["sonnet-xhigh"],
        "system text",
        [{"role": "user", "content": "u"}],
        tools,
        60.0,
    )
    body = json.loads(prepared.payload)
    assert body == {
        "model": SONNET,
        "max_tokens": 128000,
        "system": "system text",
        "messages": [{"role": "user", "content": "u"}],
        "tools": [{"name": n, "description": d, "input_schema": s} for n, d, s in tools],
        "tool_choice": {"type": "any"},
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "xhigh"},
        "cache_control": {"type": "ephemeral"},
        "stream": True,
    }
    provider.send(CELL["sonnet-xhigh"], prepared, ANT_KEY)
    sent = transport.requests[0]
    assert sent.url == "https://api.anthropic.com/v1/messages" and sent.method == "POST"
    assert dict(sent.headers) == {
        "x-api-key": ANT_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    assert sent.body == prepared.payload and sent.timeout_s == 60.0
    assert prepared.bound == cp1.token_bound(len(prepared.payload), Decimal("3.0"))


def test_token_bound_is_the_runner_bound_over_the_same_bytes() -> None:
    body = {"messages": [{"role": "user", "content": "x" * 1000}]}
    size = len(json.dumps(body, sort_keys=True).encode())
    assert cp1.token_bound(size, Decimal("3.0")) == prompt_token_bound(body, Decimal("3.0"))


def test_the_anthropic_reservation_is_the_bound_at_the_write_price_plus_full_output() -> None:
    prices = cp1.PRICES[OPUS]
    assert cp1.anthropic_reservation(prices, 10_000) == (
        10_000 * Decimal("5.00") + 128_000 * Decimal("20.00")
    ) / Decimal(1_000_000)


def test_assistant_content_goes_back_unmodified_with_one_tool_result_message(
    case: Case, tmp_path: Path
) -> None:
    calls = (
        ("t1", "search_pack", '{"query": "statement", "max_hits": 2}'),
        ("t2", "read_pages", '{"source_id": "nope", "first_page": 1, "last_page": 1}'),
    )
    first = ant_reply(*calls)
    transport = FakeTransport(ant_stream(*calls), Model(case, tmp_path / "model"))
    harness = make_harness(tmp_path, transport, case.frozen)
    anthropic = harness.providers["anthropic"]
    assert isinstance(anthropic, cp1.Anthropic)
    anthropic.tool_choice = "auto"
    run = cp1.CellRun(CELL["opus-medium"], 1, harness.batch_directory / "opus-medium")
    run.directory.mkdir()
    base = run.directory / "journal-start"
    shutil.copytree(case.frozen, base)
    ticket = Execution(base).begin("CP-1").ticket_id
    step = cp1.StepRun("source_context", run.directory / "source_context")
    cp1.run_step(harness, run.cell, step, base, ticket)
    assert step.verdict == "accepted"
    second = body_of(transport.requests[1])
    reply_content = json.loads(first.body, parse_float=Decimal)["content"]
    assert second["messages"][1] == {"role": "assistant", "content": reply_content}
    assert reply_content[0]["type"] == "thinking"
    assert reply_content[0]["signature"] == "opaque-signature=="
    results = second["messages"][2]
    assert results["role"] == "user"
    assert [(b["type"], b["tool_use_id"]) for b in results["content"]] == [
        ("tool_result", "t1"),
        ("tool_result", "t2"),
    ]
    assert all(isinstance(b["content"], str) for b in results["content"])
    assert results["content"][1]["content"].startswith("error: unknown source_id")


def test_numbers_in_assistant_content_and_tool_input_keep_their_digits() -> None:
    raw = '{"amount": 1.50, "scale": 1E+3, "count": 7}'
    response = ant_reply(("t1", "submit_financials", raw))
    parsed = cp1.anthropic_reply(OPUS, 200, response.body, ANT_KEY, 0.1)
    assert parsed.tool_calls[0].arguments == '{"amount":1.50,"scale":1E+3,"count":7}'
    resent = cp1.exact_json(list(parsed.turn))
    assert '"amount":1.50' in resent and '"scale":1E+3' in resent


def test_the_cost_is_computed_from_usage_at_list_prices() -> None:
    usage, missing, cost, reason = cp1.anthropic_usage(ANT_USAGE, cp1.PRICES[OPUS])
    # 1,000 x 4 + 2,000 x 5 (5-minute writes) + 3,000 x 0.20 + 400 x 20, per million.
    assert cost == Decimal("0.0226") and reason.startswith("computed-from-list-prices")
    assert usage == {
        "prompt_tokens": 6000,
        "completion_tokens": 400,
        "reasoning_tokens": 300,
        "cached_tokens": 3000,
    }
    assert not missing
    _, _, sonnet, _ = cp1.anthropic_usage(ANT_USAGE, cp1.PRICES[SONNET])
    # 1,000 x 2 + 2,000 x 2.50 + 3,000 x 0.10 (7 October 2026 price) + 400 x 10, per million.
    assert sonnet == Decimal("0.0113")
    no_split = {k: v for k, v in ANT_USAGE.items() if k != "cache_creation"}
    _, _, conservative, why = cp1.anthropic_usage(no_split, cp1.PRICES[OPUS])
    assert conservative == Decimal("0.0286") and "1-hour rate" in why
    partial = {k: v for k, v in ANT_USAGE.items() if k != "output_tokens"}
    counts, missing, held, why = cp1.anthropic_usage(partial, cp1.PRICES[OPUS])
    assert held is None and "held" in why
    assert counts["completion_tokens"] is None and "output_tokens" in missing["completion_tokens"]


def test_a_dated_id_of_the_requested_model_is_not_a_fallback() -> None:
    dated = cp1.anthropic_reply(OPUS, 200, ant_reply(model=f"{OPUS}-20261101").body, ANT_KEY, 0.1)
    assert dated.classification == "ok" and dated.served_model == f"{OPUS}-20261101"
    other = cp1.anthropic_reply(OPUS, 200, ant_reply(model=SONNET).body, ANT_KEY, 0.1)
    assert other.classification == "fallback"


@pytest.mark.skipif(shutil.which("textutil") is None, reason="macOS textutil only")
def test_the_anthropic_loader_reads_the_file_through_textutil(tmp_path: Path) -> None:
    path = tmp_path / "keys.rtf"
    rtf = "{\\rtf1\\ansi OpenRouter " + FAKE_KEY + "\\par Claude " + ANT_KEY + "\\par}"
    path.write_text(rtf, encoding="utf-8")
    loaded = cp1.load_anthropic_key(path)
    assert loaded.key == ANT_KEY
    assert loaded.note() == {"key_tokens_found": 2, "key_token_used": 2}
    with pytest.raises(CredentialError):
        cp1.load_anthropic_key(tmp_path / "absent.rtf")


def test_errors_settle_at_zero_only_when_refused_before_inference() -> None:
    refused = cp1.anthropic_reply(OPUS, 400, TOOL_CHOICE_400.body, ANT_KEY, 0.1)
    assert (refused.cost, refused.cost_basis, refused.tool_choice_rejected) == (
        Decimal(0),
        "known-zero",
        True,
    )
    overloaded = cp1.anthropic_reply(OPUS, 529, b'{"type":"error"}', ANT_KEY, 0.1)
    assert overloaded.cost is None and overloaded.classification == "http_error"
    credit = b'{"type":"error","error":{"message":"Your credit balance is too low"}}'
    assert cp1.anthropic_reply(OPUS, 400, credit, ANT_KEY, 0.1).classification == (
        "insufficient_credit"
    )


def test_replies_are_scrubbed_of_the_key_and_any_anthropic_key_shape() -> None:
    other = "sk-ant-api03-SOMEONE-ELSES-fake-key-000"
    body = json.dumps(
        {"type": "error", "error": {"message": f"bad key {ANT_KEY} or {other} or {FAKE_KEY}"}}
    ).encode()
    parsed = cp1.anthropic_reply(OPUS, 401, body, ANT_KEY, 0.1)
    for secret in (ANT_KEY, other, FAKE_KEY):
        assert parsed.raw is not None and secret.encode() not in parsed.raw
        assert secret not in (parsed.error_detail or "")


def test_a_transport_failure_is_scrubbed_and_holds_the_reservation(
    case: Case, tmp_path: Path
) -> None:
    transport = FakeTransport(OSError(f"connection reset; x-api-key: {ANT_KEY}"))
    harness = make_harness(tmp_path, transport, case.frozen)
    [run] = runs(harness, "opus-high")
    summary = cp1.run_batch(harness, [run], seed=1)
    step = run.steps[0]
    assert step.verdict == "no-response: transport_error"
    assert ANT_KEY not in (step.calls[0].transport_error or "")
    assert step.calls[0].settlement is not None and step.calls[0].settlement.unreconciled
    assert summary["cells"][0]["verdict"] == "stopped at source_context: no-response: " + (
        "transport_error"
    )
    for path in harness.batch_directory.rglob("*"):
        if path.is_file():
            assert ANT_KEY.encode() not in path.read_bytes()


# --- the key -----------------------------------------------------------------------------------


def test_the_anthropic_key_is_the_one_sk_ant_token_and_only_counts_are_noted() -> None:
    text = f"OpenRouter old: {FAKE_KEY}\nOpenRouter: sk-or-v1-second-fake-0000\nClaude {ANT_KEY}\n"
    loaded = cp1.anthropic_token(text)
    assert loaded.key == ANT_KEY
    assert loaded.note() == {"key_tokens_found": 3, "key_token_used": 3}
    assert ANT_KEY not in repr(loaded)
    for bad in (f"{FAKE_KEY}", f"{ANT_KEY} sk-ant-api03-another-fake-key-1111"):
        with pytest.raises(CredentialError) as raised:
            cp1.anthropic_token(bad)
        assert "sk-ant-" in str(raised.value) and ANT_KEY not in str(raised.value)
        assert "TESTONLY" not in str(raised.value) and "another" not in str(raised.value)


# --- chaining and stops --------------------------------------------------------------------


def test_four_steps_chain_on_a_copy_of_the_frozen_cp0_journal(case: Case, tmp_path: Path) -> None:
    before = tree_digest(case.frozen)
    opus, sonnet = Model(case, tmp_path / "m1"), Model(case, tmp_path / "m2", SONNET)
    transport = FakeTransport(TOOL_CHOICE_400, *[opus] * 4, *[sonnet] * 4)
    harness = make_harness(tmp_path, transport, case.frozen)
    cells = runs(harness, "opus-medium", "sonnet-max")
    summary = cp1.run_batch(harness, cells, seed=3)
    assert [run.verdict for run in cells] == ["accepted", "accepted"]
    assert [s.step_id for s in cells[0].steps] == list(cp1.CP1_STEPS)
    # any -> auto: the refused call settles at zero; every later call sends auto.
    bodies = [body_of(r) for r in transport.requests]
    assert [b["tool_choice"]["type"] for b in bodies] == ["any"] + ["auto"] * 8
    assert summary["tool_choice_fallback"]["cell"] == "opus-medium"
    first = cells[0].steps[0].calls[0]
    assert first.settlement is not None and first.settlement.charged == 0
    # Each step sees the accepted upstream steps as M7's runner projects them.
    users = [asked(r)[1] for r in transport.requests[1:5]]
    seen = [re.findall(r"<<<SOURCE id=step:(\S+) sha256=\S+ projection=(\S+)>>>", u) for u in users]
    assert seen == [
        [],
        [("source_context", "full")],
        [("financials", "narrative-evidence")],
        [("narrative", "readiness-inputs")],
    ]
    # The model left every hash binding out; Python pre-filled it.
    sent = [json.loads(step.final_payload or "{}") for step in cells[0].steps]
    assert "context_step_sha256" not in sent[1]
    assert "inputs_sha256" not in sent[2] and "inputs_sha256" not in sent[3]
    assert tree_digest(case.frozen) == before
    # The final journal holds all four valid steps on a pending CP-1 ticket.
    last = cells[0].steps[-1].accepted_journal
    assert last is not None
    attempt = Execution(last).read().attempts[-1]
    assert [s.status for s in attempt.steps] == ["valid"] * 4
    cell = summary["cells"][0]
    assert cell["cost_settled_usd"] == 4 * Decimal("0.0226") and cell["cost_held_usd"] == 0
    metrics = json.loads((cells[0].directory / "metrics.json").read_text())
    assert metrics["steps"][1]["first_submit_accepted"] is True
    assert metrics["steps"][1]["prompt_tokens"] == 6000 and metrics["steps"][0]["calls"] == 2


def test_a_prompt_beyond_the_context_window_is_not_sent_and_stops_the_cell(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = cp1.MAX_TOKENS + 1_000  # below any synthetic step's bound plus MAX_TOKENS
    monkeypatch.setattr(cp1, "CONTEXT_TOKENS", window)
    transport = FakeTransport()  # any call would fail on an empty queue
    harness = make_harness(tmp_path, transport, case.frozen)
    [run] = runs(harness, "opus-high")
    cp1.run_batch(harness, [run], seed=1)
    assert run.verdict.startswith("stopped at source_context: not sent: misfit")
    assert run.steps[0].verdict_reason is not None
    assert run.steps[0].verdict_reason.startswith(f"context {window} < bound")
    assert not run.steps[0].calls and not transport.requests
    assert not harness.ledgers["anthropic"].state().attempts  # nothing reserved


def test_a_rejected_step_stops_its_cell_and_the_next_cell_runs(case: Case, tmp_path: Path) -> None:
    bad = ant_stream(("t1", "submit_source_context", "{}"))
    sonnet = Model(case, tmp_path / "m", SONNET)
    transport = FakeTransport(TOOL_CHOICE_400, bad, bad, bad, *[sonnet] * 4)
    harness = make_harness(tmp_path, transport, case.frozen)
    cells = runs(harness, "opus-high", "sonnet-xhigh")
    cp1.run_batch(harness, cells, seed=5)
    stopped = cells[0]
    assert stopped.verdict == "stopped at source_context: rejected"
    assert stopped.stopped_at == "source_context" and len(stopped.steps) == 1
    assert len(stopped.steps[0].submits) == 3
    assert not (stopped.directory / "financials").exists()
    assert cells[1].verdict == "accepted"


def test_a_provider_schema_error_stops_only_its_cell(case: Case, tmp_path: Path) -> None:
    raw = json.dumps({"error": {"message": "Invalid schema for function 'submit_financials'"}})
    schema_400 = Response(
        400,
        json.dumps(
            {
                "error": {
                    "code": 400,
                    "message": "Provider returned error",
                    "metadata": {"raw": raw, "provider_name": "OpenAI"},
                }
            }
        ).encode(),
    )
    sol, opus = Model(case, tmp_path / "m1"), Model(case, tmp_path / "m2")
    transport = FakeTransport(sol, schema_400, TOOL_CHOICE_400, *[opus] * 4)
    harness = make_harness(tmp_path, transport, case.frozen)
    cells = runs(harness, "sol-high", "opus-medium")
    summary = cp1.run_batch(harness, cells, seed=9)
    assert cells[0].verdict == "stopped at financials: provider-schema-error"
    assert "Invalid schema" in (cells[0].steps[1].verdict_reason or "")
    assert cells[1].verdict == "accepted"
    assert summary["stopped_providers"] == {}
    sol = body_of(transport.requests[0])
    assert sol["tool_choice"] == "required" and sol["reasoning"] == {"effort": "high"}
    assert [t["function"]["name"] for t in sol["tools"]][2] == "submit_source_context"


def test_a_cap_stops_that_provider_and_the_other_provider_goes_on(
    case: Case, tmp_path: Path
) -> None:
    transport = FakeTransport(*[Model(case, tmp_path / "m")] * 4)
    caps = {"openrouter": Decimal(8), "anthropic": Decimal("0.10")}
    harness = make_harness(tmp_path, transport, case.frozen, caps=caps)
    cells = runs(harness, "opus-medium", "sonnet-max", "sol-medium")
    summary = cp1.run_batch(harness, cells, seed=2)
    assert cells[0].verdict.startswith(
        "stopped at source_context: batch:opus-medium-source_context-"
    )
    assert cells[1].verdict == "not run: anthropic stopped"
    assert cells[2].verdict == "accepted"
    assert set(summary["stopped_providers"]) == {"anthropic"}
    assert all(r.url != cp1.ANTHROPIC_URL for r in transport.requests)
    assert body_of(transport.requests[0])["reasoning"] == {"effort": "medium"}


def test_exhausted_credit_stops_that_provider(case: Case, tmp_path: Path) -> None:
    credit = Response(
        400,
        b'{"type":"error","error":{"type":"invalid_request_error",'
        b'"message":"Your credit balance is too low to access the Anthropic API."}}',
    )
    transport = FakeTransport(credit)
    harness = make_harness(tmp_path, transport, case.frozen)
    cells = runs(harness, "sonnet-max", "opus-high")
    summary = cp1.run_batch(harness, cells, seed=4)
    assert cells[0].steps[0].verdict == "no-response: insufficient_credit"
    assert cells[1].verdict == "not run: anthropic stopped"
    assert "anthropic" in summary["stopped_providers"] and len(transport.requests) == 1


# --- evidence counts -------------------------------------------------------------------------


def test_evidence_counts_cover_citations_limitations_and_claims() -> None:
    payload = json.dumps(
        {
            "findings": [{"evidence": ["e1", "e2"], "limitation": "thin"}],
            "sources": [{"citations": [{"locator": "page:1"}], "limitations": ["a", "b"]}],
            "definition": {"definition_citations": [{}], "maturity_limitation": None},
        }
    )
    assert cp1.evidence_counts(payload) == {
        "citations": 4,
        "limitations": 3,
        "claims": 1,
        "objects": 6,
    }
    assert cp1.evidence_counts("[1]") is None and cp1.evidence_counts("nope") is None


# --- command line ----------------------------------------------------------------------------


LUNA = "openai/gpt-6-luna"


def cli(
    tmp_path: Path,
    frozen: Path,
    *extra: str,
    luna_efforts: tuple[str, ...] = ("low", "medium", "high", "xhigh"),
) -> list[str]:
    catalog = tmp_path / "models.json"
    rows = [
        catalog_row(
            cp0.MODEL, parameters=PARAMETERS, pricing=PRICING, efforts=("low", "medium", "high")
        ),
        catalog_row(LUNA, parameters=PARAMETERS, pricing=PRICING, efforts=luna_efforts),
    ]
    catalog.write_text(json.dumps({"data": rows}), encoding="utf-8")
    return [
        "--cp0-journal",
        str(frozen),
        "--artifact-root",
        str(tmp_path / "root"),
        "--settings",
        str(SETTINGS),
        "--catalog",
        str(catalog),
        *extra,
    ]


def fake_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # The loaders need macOS textutil and the real file; the test supplies fake keys in memory.
    monkeypatch.setattr(cp1, "load_key_with_note", lambda *_: LoadedKey(FAKE_KEY, 2, 2))
    monkeypatch.setattr(cp1, "load_anthropic_key", lambda *_: LoadedKey(ANT_KEY, 3, 3))


def test_the_dry_run_prints_order_reservations_and_key_index_and_sends_nothing(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    args = cli(tmp_path, case.frozen, "--dry-run", "--seed", "7")
    assert cp1.main(args, transport=unexpected_send) == 0
    captured = capsys.readouterr()
    plan = json.loads(captured.out)
    expected = list(cp1.CELLS)
    random.Random(7).shuffle(expected)
    assert [item["cell_id"] for item in plan["order"]] == [c.cell_id for c in expected]
    assert plan["seed"] == 7
    assert plan["credential"]["anthropic"]["key_token_used"] == 3
    assert plan["credential"]["openrouter"] == {"key_tokens_found": 2, "key_token_used": 2}
    first = plan["money"]["first_call_per_cell"]
    opus = first["opus-medium"]
    assert Decimal(opus["reserved_usd"]) == cp1.anthropic_reservation(
        cp1.PRICES[OPUS], opus["prompt_tokens_upper_bound"]
    )
    sol = first["sol-high"]
    assert Decimal(sol["reserved_usd"]) == (
        sol["prompt_tokens_upper_bound"] * Decimal("0.000001") + 128000 * Decimal("0.000002")
    )
    assert plan["money"]["caps_usd"] == {"openrouter": "15", "anthropic": "25"}
    for text in (captured.out, captured.err):
        assert ANT_KEY not in text and FAKE_KEY not in text
        assert not re.search(r"sk-(ant|or)-[A-Za-z0-9_\-]{6,}", text)  # no key-shaped text
    assert not (tmp_path / "root").exists()


def test_a_journal_that_cannot_start_cp1_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    Execution.create(tmp_path / "unaccepted", cp1_case(tmp_path / "seed")[0].pack())
    args = cli(tmp_path, tmp_path / "unaccepted", "--dry-run")
    assert cp1.main(args, transport=unexpected_send) == 2
    assert "cannot start CP-1" in capsys.readouterr().err


def test_the_dry_run_measures_every_step_with_retained_payloads(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    model = Model(case, tmp_path / "model")
    for step_id in cp1.CP1_STEPS:  # retained payloads laid out as PREFIX-<step>-1/output.md
        payload = model.payload(step_id)
        submit_model_payload(model.store, model.ticket, step_id, payload)
        (tmp_path / f"e1-{step_id}-1").mkdir()
        (tmp_path / f"e1-{step_id}-1" / "output.md").write_text(payload, encoding="utf-8")
    before = tree_digest(case.frozen)
    args = cli(tmp_path, case.frozen, "--dry-run", "--upstream-from", str(tmp_path / "e1"))
    assert cp1.main(args, transport=unexpected_send) == 0
    steps = json.loads(capsys.readouterr().out)["step_prompts"]["steps"]
    assert [s["step_id"] for s in steps] == list(cp1.CP1_STEPS)
    assert [s["representative_payload"]["outcome"] for s in steps] == ["accepted"] * 4
    assert [[u["projection"] for u in s["upstream"]] for s in steps] == [
        [],
        ["full"],
        ["narrative-evidence"],
        ["readiness-inputs"],
    ]
    narrative = steps[2]["first_call_per_cell"]["opus-high"]
    assert Decimal(narrative["reserved_usd"]) == cp1.anthropic_reservation(
        cp1.PRICES[OPUS], narrative["prompt_tokens_upper_bound"]
    )
    assert all(c["misfit"] is None for s in steps for c in s["first_call_per_cell"].values())
    assert tree_digest(case.frozen) == before and not (tmp_path / "root").exists()


# --- streaming -------------------------------------------------------------------------------


def read(body: bytes, clock: Callable[[], float] = lambda: 0.0) -> cp1.Events:
    return cp1.read_events(iter(body.splitlines(keepends=True)), 10.0, clock, cp1.IDLE_S)


def test_a_stream_rebuilds_the_content_exactly_and_merges_usage() -> None:
    calls = (("t1", "submit_financials", '{"amount": 1.50, "scale": 1E+3, "note": "a b"}'),)
    events = stream_events(*calls)
    assert {"type": "ping"} in events  # a ping between the thinking deltas
    reply = cp1.stream_reply(OPUS, 200, read(sse(*events)), ANT_KEY, 0.1)
    assert reply.classification == "ok" and reply.raw_kind == "sse"
    unstreamed = json.loads(ant_reply(*calls).body, parse_float=Decimal)["content"]
    assert reply.turn == ({"role": "assistant", "content": unstreamed},)
    assert unstreamed[0] == {
        "type": "thinking",
        "thinking": "Plan the step.",
        "signature": "opaque-signature==",
    }
    # The input's JSON arrived in two pieces split mid-text; its digits are kept.
    assert reply.tool_calls[0].arguments == '{"amount":1.50,"scale":1E+3,"note":"a b"}'
    # Input-side usage from message_start, output_tokens (1 there) from message_delta.
    assert reply.usage == {
        "prompt_tokens": 6000,
        "completion_tokens": 400,
        "reasoning_tokens": 300,
        "cached_tokens": 3000,
    }
    assert reply.cost == Decimal("0.0226") and reply.cost_basis == "computed-from-list-prices"
    assert reply.raw is not None and b"event: ping" in reply.raw


def test_a_stream_that_cannot_be_rebuilt_exactly_is_incomplete() -> None:
    events = stream_events(("t1", "search_pack", '{"query": "x"}'))
    unknown = [*events[:2], delta(0, "citations_delta", citation="?"), *events[2:]]
    reply = cp1.stream_reply(OPUS, 200, read(sse(*unknown)), ANT_KEY, 0.1)
    assert reply.classification == "stream-incomplete"
    assert reply.error_detail == "unknown delta type 'citations_delta'"
    unstarted = [*events[:2], delta(5, "text_delta", text="x"), *events[2:]]
    assert cp1.stream_reply(OPUS, 200, read(sse(*unstarted)), ANT_KEY, 0.1).cost is None


def test_the_wall_clock_deadline_cuts_a_stream() -> None:
    ticks = iter(range(100))
    events = read(ant_stream(("t1", "search_pack", "{}")).body, lambda: float(next(ticks)))
    assert events.cut == "the step's wall-clock deadline passed mid-stream"


def stream_cell(tmp_path: Path, case: Case, body: bytes) -> tuple[cp1.CellRun, cp1.Harness]:
    harness = make_harness(tmp_path, FakeTransport(Response(200, body)), case.frozen)
    anthropic = harness.providers["anthropic"]
    assert isinstance(anthropic, cp1.Anthropic)
    anthropic.tool_choice = "auto"
    [run] = runs(harness, "sonnet-max")
    cp1.run_batch(harness, [run], seed=1)
    return run, harness


def test_an_error_event_mid_stream_holds_the_reservation_and_stops_the_cell(
    case: Case, tmp_path: Path
) -> None:
    error = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
    body = sse(*stream_events(("t1", "search_pack", "{}"))[:3], error)
    run, _ = stream_cell(tmp_path, case, body)
    step = run.steps[0]
    assert step.verdict == "no-response: http_error"
    assert step.verdict_reason == "stream error overloaded_error: Overloaded"
    assert run.verdict == "stopped at source_context: no-response: http_error"
    settled = step.calls[0].settlement
    assert settled is not None and settled.unreconciled  # held
    assert (step.directory / "call-01-response.sse").read_bytes() == body  # partial events


def test_a_cut_stream_is_incomplete_holds_and_stops_the_cell(case: Case, tmp_path: Path) -> None:
    body = sse(*stream_events(("t1", "submit_source_context", case.context))[:-2])
    run, harness = stream_cell(tmp_path, case, body)
    step = run.steps[0]
    assert step.verdict == "no-response: stream-incomplete"
    assert step.verdict_reason == "the stream ended before message_stop"
    assert not step.submits  # nothing from a cut stream is judged
    settled = step.calls[0].settlement
    assert settled is not None and settled.unreconciled
    assert (step.directory / "call-01-response.sse").read_bytes() == body
    assert harness.ledgers["anthropic"].state().reserved == 0


def test_the_connection_is_closed_once_message_stop_is_read() -> None:
    closed: list[bool] = []

    def open_stream(request: Request, idle_s: float) -> cp1.Stream:
        def lines() -> Iterator[bytes]:
            try:
                yield from ant_stream(("t1", "search_pack", "{}")).body.splitlines(keepends=True)
                yield b": the server could keep the connection open\n"
            finally:
                closed.append(True)

        return cp1.Stream(200, lines())

    provider = cp1.Anthropic(open_stream, Decimal("3.0"), tool_choice="auto")
    user = [{"role": "user", "content": "u"}]
    prepared = provider.prepare(CELL["opus-high"], "s", user, (), 60)
    assert provider.send(CELL["opus-high"], prepared, ANT_KEY).classification == "ok"
    assert closed == [True]


def test_an_idle_stream_is_cut_at_the_idle_limit() -> None:
    seen: list[float] = []

    def silent_after_start(request: Request, idle_s: float) -> cp1.Stream:
        seen.append(idle_s)
        start = sse(*stream_events(("t1", "search_pack", "{}"))[:2]).splitlines(keepends=True)

        def lines() -> Iterator[bytes]:
            yield from start
            raise TimeoutError("timed out")

        return cp1.Stream(200, lines())

    provider = cp1.Anthropic(silent_after_start, Decimal("3.0"), tool_choice="auto")
    user = [{"role": "user", "content": "u"}]
    prepared = provider.prepare(CELL["opus-high"], "s", user, (), 900.0)
    reply = provider.send(CELL["opus-high"], prepared, ANT_KEY)
    assert seen == [cp1.IDLE_S]
    assert reply.classification == "stream-incomplete" and reply.cost is None
    assert reply.error_detail == f"no byte for {cp1.IDLE_S} s (idle timeout)"
    assert reply.served_model == OPUS and reply.raw is not None


# --- the extra Luna cell on a shared OpenRouter ledger -----------------------------------------


def earlier_batch_ledger(tmp_path: Path) -> Path:
    """hybrid-cp1-1's OpenRouter ledger after one settled Sol call (cap 15)."""
    path = tmp_path / "root" / ".ledgers" / "hybrid-cp1-1-openrouter.jsonl"
    path.parent.mkdir(parents=True)
    ledger = Ledger(path, Decimal(15))
    ledger.reserve("sol-high-source_context-call-01", Decimal(2))
    ledger.settle("sol-high-source_context-call-01", Decimal("0.5"), "usage.cost")
    return path


def test_luna_runs_on_the_earlier_batchs_openrouter_ledger(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    loaded: list[str] = []
    monkeypatch.setattr(cp1, "load_anthropic_key", lambda *_: loaded.append("anthropic"))
    shared = earlier_batch_ledger(tmp_path)
    before = shared.read_bytes()
    luna = Model(case, tmp_path / "model", LUNA)
    transport = FakeTransport(*[luna] * 4)
    args = cli(tmp_path, case.frozen, "--cells", "luna-xhigh", "--batch-id", "hybrid-cp1-2")
    args += ["--openrouter-ledger", str(shared), "--seed", "1", "--step-seconds", "3600"]
    assert cp1.main(args, transport=transport, stream_transport=unexpected_stream) == 0
    plan, summary = cp0_json_documents(capsys.readouterr().out)
    assert [o["cell_id"] for o in plan["order"]] == ["luna-xhigh"]
    assert plan["openrouter"]["efforts"]["luna-xhigh"]["sent"] == "xhigh"
    assert not plan["openrouter"]["efforts"]["luna-xhigh"]["mapped"]
    assert plan["money"]["ledgers"]["openrouter"]["shared"] is True
    assert Decimal(plan["money"]["ledgers"]["openrouter"]["headroom"]) == Decimal("14.5")
    assert "anthropic" not in plan["money"]["ledgers"] and not loaded
    assert summary["cells"][0]["verdict"] == "accepted"
    sent = [body_of(r) for r in transport.requests]
    assert {b["model"] for b in sent} == {LUNA} and {b["reasoning"]["effort"] for b in sent} == {
        "xhigh"
    }
    # The earlier batch's lines stand as written; Luna's attempts follow them.
    after = shared.read_bytes()
    assert after.startswith(before)
    state = Ledger(shared, Decimal(15)).state()
    names = [a.attempt_id for a in state.attempts]
    assert names[0] == "sol-high-source_context-call-01"
    assert all(n.startswith("hybrid-cp1-2:luna-xhigh-") for n in names[1:]) and len(names) == 5
    assert not (tmp_path / "root" / ".ledgers" / "hybrid-cp1-2-openrouter.jsonl").exists()
    assert (tmp_path / "root" / "hybrid-cp1-2" / "luna-xhigh" / "metrics.json").exists()


def test_luna_is_not_run_when_xhigh_would_be_mapped(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    shared = earlier_batch_ledger(tmp_path)
    args = cli(tmp_path, case.frozen, "--cells", "luna-xhigh", luna_efforts=("low", "high"))
    args += ["--openrouter-ledger", str(shared), "--batch-id", "hybrid-cp1-2"]
    assert cp1.main(args, transport=unexpected_send, stream_transport=unexpected_stream) == 2
    assert "luna-xhigh: effort xhigh would be sent as" in capsys.readouterr().err
    assert not (tmp_path / "root" / "hybrid-cp1-2").exists()


def test_a_missing_shared_ledger_is_refused(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    absent = tmp_path / "absent.jsonl"
    args = cli(tmp_path, case.frozen, "--cells", "luna-xhigh", "--openrouter-ledger", str(absent))
    assert cp1.main(args, transport=unexpected_send) == 2
    assert "does not exist" in capsys.readouterr().err


def unexpected_stream(request: Request, idle_s: float) -> cp1.Stream:
    raise AssertionError(f"an Anthropic call was opened: {request.url}")


def cp0_json_documents(out: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The plan and the batch summary main prints, one JSON document after the other."""
    decoder = json.JSONDecoder()
    plan, end = decoder.raw_decode(out)
    summary, _ = decoder.raw_decode(out[end:].lstrip())
    return plan, summary


# --- resuming hybrid-cp1-1 after the user skipped opus-high ------------------------------------


def stopped_batch(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    """hybrid-cp1-1 as the stop left it: four cells done, opus-high's directory begun (no call),
    sonnet-xhigh not started, both ledgers holding earlier attempts."""
    batch = tmp_path / "root" / "hybrid-cp1-1"
    order = ["sonnet-max", "sol-high", "sol-medium", "opus-medium", "opus-high", "sonnet-xhigh"]
    for cell_id in order[:4]:
        (batch / cell_id).mkdir(parents=True)
    (batch / "opus-high" / "journal-start").mkdir(parents=True)
    rows = [{"order": n, "cell_id": cell_id} for n, cell_id in enumerate(order, start=1)]
    (batch / "plan.json").write_text(json.dumps({"order": rows}), encoding="utf-8")
    shared = earlier_batch_ledger(tmp_path)
    anthropic = shared.with_name("hybrid-cp1-1-anthropic.jsonl")
    ledger = Ledger(anthropic, Decimal(25))
    ledger.reserve("opus-medium-source_context-call-01", Decimal(3))
    ledger.settle("opus-medium-source_context-call-01", Decimal("1.25"), "computed")
    before = {p.name: p.read_bytes() for p in (shared, anthropic, batch / "plan.json")}
    return batch, before


def test_a_resume_runs_only_the_named_cell_and_records_the_skip(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    batch, before = stopped_batch(tmp_path)
    sonnet = Model(case, tmp_path / "model", SONNET)
    transport = FakeTransport(*[sonnet] * 4)
    args = cli(tmp_path, case.frozen, "--resume", "--cells", "sonnet-xhigh", "--seed", "1")
    args += ["--skipped-by-user", "opus-high", "--step-seconds", "3600"]
    assert cp1.main(args, transport=unexpected_send, stream_transport=as_stream(transport)) == 0
    plan, summary = cp0_json_documents(capsys.readouterr().out)
    ledgers = plan["money"]["ledgers"]
    assert set(ledgers) == {"anthropic"} and ledgers["anthropic"]["shared"] is True
    assert Decimal(ledgers["anthropic"]["headroom"]) == Decimal("23.75")
    assert plan["resume"] == {"of": "plan.json"} and plan["skipped_by_user"] == ["opus-high"]
    assert [(c["cell_id"], c["order"]) for c in plan["order"]] == [("sonnet-xhigh", 6)]
    cells = {c["cell_id"]: c for c in summary["cells"]}
    assert cells["opus-high"]["verdict"] == "skipped by user" and cells["opus-high"]["order"] == 5
    assert cells["opus-high"]["steps"] == [] and cells["opus-high"]["cost_settled_usd"] == "0"
    assert cells["sonnet-xhigh"]["verdict"] == "accepted" and cells["sonnet-xhigh"]["order"] == 6
    assert not (batch / "opus-high" / "metrics.json").exists()
    assert (batch / "sonnet-xhigh" / "metrics.json").exists()
    assert (batch / "plan-resume-sonnet-xhigh.json").exists()
    assert (batch / "batch-summary-resume-sonnet-xhigh.json").exists()
    assert not (batch / "batch-summary.json").exists()
    # Earlier evidence stands as written; the Anthropic ledger gains only sonnet-xhigh lines.
    ledger_dir = batch.parent / ".ledgers"
    assert (batch / "plan.json").read_bytes() == before["plan.json"]
    openrouter = ledger_dir / "hybrid-cp1-1-openrouter.jsonl"
    assert openrouter.read_bytes() == before[openrouter.name]
    anthropic = ledger_dir / "hybrid-cp1-1-anthropic.jsonl"
    assert anthropic.read_bytes().startswith(before[anthropic.name])
    names = [a.attempt_id for a in Ledger(anthropic, Decimal(25)).state().attempts]
    assert names[0] == "opus-medium-source_context-call-01"
    assert len(names) == 5 and all(n.startswith("hybrid-cp1-1:sonnet-xhigh-") for n in names[1:])


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        (("--cells", "opus-medium"), "already started: ['opus-medium']"),
        (("--cells", "opus-high"), "already started: ['opus-high']"),
        (("--cells", "luna-xhigh"), "not in hybrid-cp1-1's plan: ['luna-xhigh']"),
        (("--cells", "sonnet-xhigh", "--skipped-by-user", "sonnet-xhigh"), "both run and skipped"),
    ],
)
def test_a_resume_never_reruns_a_started_cell(
    case: Case,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: tuple[str, ...],
    reason: str,
) -> None:
    fake_keys(monkeypatch)
    batch, _ = stopped_batch(tmp_path)
    args = cli(tmp_path, case.frozen, "--resume", *extra)
    assert cp1.main(args, transport=unexpected_send, stream_transport=unexpected_stream) == 2
    assert reason in capsys.readouterr().err
    assert sorted(p.name for p in batch.iterdir() if p.is_file()) == ["plan.json"]


def test_a_resume_needs_the_batchs_ledger(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    batch, _ = stopped_batch(tmp_path)
    (batch.parent / ".ledgers" / "hybrid-cp1-1-anthropic.jsonl").unlink()
    args = cli(tmp_path, case.frozen, "--resume", "--cells", "sonnet-xhigh")
    assert cp1.main(args, transport=unexpected_send, stream_transport=unexpected_stream) == 2
    assert "hybrid-cp1-1-anthropic.jsonl does not exist" in capsys.readouterr().err


# --- corrective fixes: caching per step, completeness, call-limit nudge -------------------------


@pytest.mark.parametrize("step_id", ["source_context", "financials", "narrative", "readiness"])
def test_top_level_cache_control_is_sent_on_every_step(step_id: str) -> None:
    # Review C3: narrative and readiness were multi-call in most cells; caching stays on.
    provider = cp1.Anthropic(as_stream(FakeTransport()), Decimal("3.0"))
    user = [{"role": "user", "content": "u"}]
    prepared = provider.prepare(CELL["opus-medium"], "s", user, cp1.step_tools(step_id), 60.0)
    body = json.loads(prepared.payload)
    assert body["cache_control"] == {"type": "ephemeral"}  # no ttl: the default 5 minutes


def test_the_plan_records_the_cache_ttl_observation_and_the_harness_rules(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    args = cli(tmp_path, case.frozen, "--dry-run", "--seed", "7")
    assert cp1.main(args, transport=unexpected_send) == 0
    plan = json.loads(capsys.readouterr().out)
    cache = plan["anthropic"]["cache_control"]
    assert "every step" in cache["sent"]
    assert "longer than 300 s" in cache["observed"]
    assert "1h" in cache["unmeasured_option"]
    assert "cache_control_by_step" not in plan["anthropic"]
    assert plan["harness_rules"]["call_limit_nudge"]["from_calls_left"] == 3
    assert "submit" in plan["harness_rules"]["call_limit_nudge"]["text"]


def test_the_call_limit_nudge_appears_from_the_third_last_call_only(
    case: Case, tmp_path: Path
) -> None:
    # Two tool calls a turn: the line goes once, on the turn's last result.
    search = ant_stream(
        ("t1", "search_pack", '{"query": "revenue"}'), ("t2", "search_pack", '{"query": "debt"}')
    )
    transport = FakeTransport(*[search] * cp1.MAX_CALLS)
    harness = make_harness(tmp_path, transport, case.frozen)
    [run] = runs(harness, "opus-medium")
    cp1.run_cell(harness, run)
    assert run.steps[0].verdict == "rejected: limit" and len(transport.requests) == cp1.MAX_CALLS
    third_last = cp1.MAX_CALLS - 2
    for number, request in enumerate(transport.requests, start=1):
        latest = body_of(request)["messages"][-1]
        texts = [block["content"] for block in latest["content"]] if number > 1 else []
        left = cp1.MAX_CALLS - number + 1  # calls left when this request's results were written
        if number < third_last:
            assert not any("calls remain" in text for text in texts), number
            continue
        assert texts[-1].endswith(
            f"\nHarness: {left} of {cp1.MAX_CALLS} calls remain in this step; "
            "the step must end with submit_source_context."
        ), number
        assert sum(text.count("calls remain") for text in texts) == 1
    # Review C5: the retained tool log records the line on the turn that carried it.
    log = run.steps[0].directory / "tool-calls.jsonl"
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    nudges = [(e["call"], e["nudge"]) for e in entries if "nudge" in e]
    assert nudges == [
        (
            cp1.MAX_CALLS - left,
            f"Harness: {left} of {cp1.MAX_CALLS} calls remain in this step; "
            "the step must end with submit_source_context.",
        )
        for left in (3, 2, 1)
    ]


# A financials payload shaped like sol-high's two submits: the second has 143 statement lines
# against the first's 284, and no balance movement against five.
FIRST_LINES = {
    ("IS", "2025"): 40,
    ("IS", "2024"): 40,
    ("IS", "2023"): 40,
    ("BS", "2025"): 50,
    ("BS", "2024"): 50,
    ("CFS", "2025"): 22,
    ("CFS", "2024"): 21,
    ("CFS", "2023"): 21,
}
SECOND_LINES = {("IS", "2025"): 40, ("IS", "2024"): 40, ("BS", "2025"): 43, ("CFS", "2025"): 20}


def financial_payload(
    lines: dict[tuple[str, str], int], movements: int, bridges: int, identities: int
) -> str:
    periods = [{"period_id": f"FY{year}", "fiscal_year": year} for year in ("2023", "2024", "2025")]
    statement_lines = [
        {"statement": statement, "period_id": f"FY{year}", "line_id": f"{statement}-{year}-{n}"}
        for (statement, year), count in lines.items()
        for n in range(count)
    ]
    book = {
        "periods": periods,
        "statement_lines": statement_lines,
        "accounts": [{"metric_id": f"m{n}"} for n in range(60)],
        "balance_movements": [{"movement_id": f"mv{n}"} for n in range(movements)],
        "balance_movement_bridges": [{"bridge_id": f"b{n}"} for n in range(bridges)],
        "statement_identities": [{"identity_id": f"i{n}"} for n in range(identities)],
    }
    assessments = [{"observation_ids": ["r25", "r24", f"x{n}"]} for n in range(5)]
    return json.dumps({"financial": {"books": [book]}, "definition": {"assessments": assessments}})


SOL_HIGH_FIRST = financial_payload(FIRST_LINES, movements=5, bridges=1, identities=8)
SOL_HIGH_SECOND = financial_payload(SECOND_LINES, movements=0, bridges=0, identities=7)


def test_completeness_counts_lines_by_statement_and_fiscal_year() -> None:
    assert cp1.completeness(SOL_HIGH_FIRST) == {
        "statement_lines": 284,
        "statement_lines_by_statement": {"BS": 100, "CFS": 64, "IS": 120},
        "statement_lines_by_fiscal_year": {"2023": 61, "2024": 111, "2025": 112},
        "accounts": 60,
        "balance_movements": 5,
        "balance_movement_bridges": 1,
        "statement_identities": 8,
        "definition_assessments": 5,
        "definition_observation_ids": 7,
        "reasons": [],
    }
    second = cp1.completeness(SOL_HIGH_SECOND)
    assert second is not None
    assert second["statement_lines"] == 143 and second["balance_movements"] == 0
    assert second["statement_lines_by_fiscal_year"] == {"2024": 40, "2025": 103}
    assert cp1.completeness("not json") is None and cp1.completeness("[]") is None
    # A line whose period the book does not list is counted, not dropped.
    odd = json.loads(SOL_HIGH_SECOND)
    odd["financial"]["books"][0]["statement_lines"].append({"statement": "IS", "period_id": "Q9"})
    counted = cp1.completeness(json.dumps(odd))
    assert counted is not None and counted["statement_lines_by_fiscal_year"]["unknown"] == 1


def test_completeness_counts_a_payload_with_unhashable_period_ids_and_says_why() -> None:
    # Review C2: a list or object where an id belongs raised TypeError after the call was paid.
    odd = json.loads(SOL_HIGH_SECOND)
    book = odd["financial"]["books"][0]
    book["periods"].append({"period_id": ["FY2022"], "fiscal_year": "2022"})
    book["statement_lines"].append({"statement": "BS", "period_id": {"id": "FY2025"}})
    odd["definition"]["assessments"].append({"observation_ids": [["nested"], "r25"]})
    counted = cp1.completeness(json.dumps(odd))
    assert counted is not None
    assert counted["statement_lines"] == 144
    assert counted["statement_lines_by_fiscal_year"] == {"2024": 40, "2025": 103, "unknown": 1}
    assert counted["definition_observation_ids"] == 7
    assert counted["reasons"] == [
        "a period's period_id is not a string or integer; its lines count as unknown",
        "a statement line's period_id is not a string or integer; counted as unknown",
    ]


def test_completeness_drop_compares_each_submit_with_the_most_seen_before() -> None:
    first = {"submit": 1, "completeness": cp1.completeness(SOL_HIGH_FIRST)}
    second = {"submit": 2, "completeness": cp1.completeness(SOL_HIGH_SECOND)}
    assert cp1.completeness_drop([first, second]) == {
        "flag": True,
        "dropped": [
            {
                "submit": 2,
                "most_before_then_now": {
                    "statement_lines": [284, 143],
                    "balance_movements": [5, 0],
                },
            }
        ],
        "basis": "each later submit vs the most any earlier submit held",
    }
    assert cp1.completeness_drop([first, first | {"submit": 2}])["flag"] is False
    assert cp1.completeness_drop([first])["flag"] is False
    # Review C4: 5 -> 200 -> 50 lines is a drop at submit 3, though 50 > the first's 5.
    rows = [
        {"submit": n, "completeness": {"statement_lines": lines, "balance_movements": moves}}
        for n, (lines, moves) in enumerate([(5, 0), (200, 40), (50, 10)], start=1)
    ]
    assert cp1.completeness_drop(rows)["dropped"] == [
        {
            "submit": 3,
            "most_before_then_now": {"statement_lines": [200, 50], "balance_movements": [40, 10]},
        }
    ]
    unreadable = [rows[0], {"submit": 2, "completeness": None}, rows[2]]
    assert cp1.completeness_drop(unreadable)["dropped"] == [
        {"submit": 2, "not_a_json_object": True}
    ]


def test_financials_metrics_carry_completeness_beside_the_shrink_flag(
    case: Case, tmp_path: Path
) -> None:
    opus = Model(case, tmp_path / "m")
    transport = FakeTransport(TOOL_CHOICE_400, *[opus] * 4)
    harness = make_harness(tmp_path, transport, case.frozen)
    [run] = runs(harness, "opus-medium")
    cp1.run_cell(harness, run)
    assert run.verdict == "accepted"
    metrics = {step.step_id: cp1.step_metrics(step) for step in run.steps}
    financials = metrics["financials"]
    expected = cp1.completeness(opus.payload("financials"))
    assert expected is not None and expected["statement_lines"] > 0
    assert financials["submits"][0]["completeness"] == expected
    assert financials["final_payload_completeness"] == expected
    assert financials["completeness_drop"]["flag"] is False
    assert "submit_shrinkage" in financials
    for other in ("source_context", "narrative", "readiness"):
        assert metrics[other]["final_payload_completeness"] is None
        assert "completeness" not in metrics[other]["submits"][0]


def test_completeness_is_back_filled_from_a_retained_tool_log(tmp_path: Path) -> None:
    log = tmp_path / "tool-calls.jsonl"
    entries = [
        {"call": 2, "index": 1, "name": "read_pages", "arguments": "{}", "status": "ok"},
        {
            "call": 4,
            "index": 1,
            "name": "submit_financials",
            "arguments": SOL_HIGH_FIRST,
            "status": "rejected",
        },
        {
            "call": 6,
            "index": 1,
            "name": "submit_financials",
            "arguments": SOL_HIGH_SECOND,
            "status": "accepted",
        },
    ]
    log.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    before = log.read_bytes()
    rows = cp1.completeness_from_log(log)
    assert [(r["submit"], r["call"], r["status"]) for r in rows] == [
        (1, 4, "rejected"),
        (2, 6, "accepted"),
    ]
    assert rows[0]["completeness"]["statement_lines"] == 284
    assert rows[1]["completeness"]["balance_movements"] == 0
    assert cp1.completeness_drop(rows)["flag"] is True
    assert log.read_bytes() == before  # read only


# --- review C1 / C7: shared ledgers, skips and caps ---------------------------------------------


def luna_args(tmp_path: Path, frozen: Path, batch: str, shared: Path, *extra: str) -> list[str]:
    args = cli(tmp_path, frozen, "--cells", "luna-xhigh", "--batch-id", batch, *extra)
    return [*args, "--openrouter-ledger", str(shared), "--seed", "1", "--step-seconds", "3600"]


def test_a_cell_reused_on_a_shared_ledger_runs_under_its_own_batch_ids(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Review C1: the second batch's ids equalled the first's and the reserve raised.
    fake_keys(monkeypatch)
    shared = earlier_batch_ledger(tmp_path)
    for batch, model in (("hybrid-cp1-2", "m1"), ("hybrid-cp1-3", "m2")):
        transport = FakeTransport(*[Model(case, tmp_path / model, LUNA)] * 4)
        args = luna_args(tmp_path, case.frozen, batch, shared)
        assert cp1.main(args, transport=transport, stream_transport=unexpected_stream) == 0
    capsys.readouterr()
    names = [a.attempt_id for a in Ledger(shared, Decimal(15)).state().attempts]
    assert names[0] == "sol-high-source_context-call-01"  # an earlier, unprefixed id still reads
    assert [n.split(":")[0] for n in names[1:]] == ["hybrid-cp1-2"] * 4 + ["hybrid-cp1-3"] * 4
    assert (tmp_path / "root" / "hybrid-cp1-3" / "batch-summary.json").exists()


def test_a_batch_and_cell_the_ledger_already_holds_is_refused_before_any_directory(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    shared = earlier_batch_ledger(tmp_path)
    ledger = Ledger(shared, Decimal(15))
    ledger.reserve("hybrid-cp1-2:luna-xhigh-source_context-call-01", Decimal(1))
    ledger.settle("hybrid-cp1-2:luna-xhigh-source_context-call-01", Decimal("0.01"), "usage.cost")
    args = luna_args(tmp_path, case.frozen, "hybrid-cp1-2", shared)
    assert cp1.main(args, transport=unexpected_send, stream_transport=unexpected_stream) == 2
    assert "already holds attempts for hybrid-cp1-2 luna-xhigh" in capsys.readouterr().err
    assert not (tmp_path / "root" / "hybrid-cp1-2").exists()


def test_a_ledger_error_in_send_stops_the_provider_not_the_batch(
    case: Case, tmp_path: Path
) -> None:
    transport = FakeTransport()  # nothing may be sent
    harness = make_harness(tmp_path, transport, case.frozen)
    taken = "batch:opus-medium-source_context-call-01"  # the id the first call would use
    harness.ledgers["anthropic"].reserve(taken, Decimal(1))
    cells = runs(harness, "opus-medium", "opus-high")
    summary = cp1.run_batch(harness, cells, seed=1)
    assert not transport.requests
    assert "reserves" in summary["stopped_providers"]["anthropic"]
    assert cells[0].verdict.startswith("stopped at source_context: ")
    assert cells[1].verdict == "not run: anthropic stopped"


@pytest.mark.parametrize("trace", ["step calls", "ledger attempt"])
def test_a_skip_is_refused_for_a_cell_that_already_made_calls(
    case: Case,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    trace: str,
) -> None:
    fake_keys(monkeypatch)
    batch, _ = stopped_batch(tmp_path)
    if trace == "step calls":
        step = batch / "opus-high" / "source_context"
        step.mkdir()
        (step / "call-01-request.json").write_text("{}", encoding="utf-8")
    else:
        ledger = Ledger(batch.parent / ".ledgers" / "hybrid-cp1-1-anthropic.jsonl", Decimal(25))
        ledger.reserve("opus-high-source_context-call-01", Decimal(1))
    args = cli(tmp_path, case.frozen, "--resume", "--cells", "sonnet-xhigh")
    args += ["--skipped-by-user", "opus-high"]
    assert cp1.main(args, transport=unexpected_send, stream_transport=unexpected_stream) == 2
    assert "opus-high cannot be recorded as skipped" in capsys.readouterr().err
    assert sorted(p.name for p in batch.iterdir() if p.is_file()) == ["plan.json"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (("--resume", "--cells", "sonnet-xhigh", "--cap-anthropic", "30"), "anthropic cap 30"),
        (("--resume", "--cells", "sol-medium", "--cap-openrouter", "16"), "openrouter cap 16"),
    ],
)
def test_a_cap_that_differs_from_an_existing_ledgers_cap_is_refused(
    case: Case,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: tuple[str, ...],
    message: str,
) -> None:
    fake_keys(monkeypatch)
    batch, _ = stopped_batch(tmp_path)
    shutil.rmtree(batch / "sol-medium")  # not started, so only the cap can refuse it
    args = cli(tmp_path, case.frozen, "--dry-run", *extra)
    assert cp1.main(args, transport=unexpected_send, stream_transport=unexpected_stream) == 2
    assert f"{message} differs from" in capsys.readouterr().err


def test_a_shared_ledger_cap_given_explicitly_must_match_and_then_runs(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_keys(monkeypatch)
    shared = earlier_batch_ledger(tmp_path)
    refused = luna_args(tmp_path, case.frozen, "hybrid-cp1-2", shared, "--cap-openrouter", "20")
    assert cp1.main([*refused, "--dry-run"], transport=unexpected_send) == 2
    assert "openrouter cap 20 differs from" in capsys.readouterr().err
    same = luna_args(tmp_path, case.frozen, "hybrid-cp1-2", shared, "--cap-openrouter", "15")
    assert cp1.main([*same, "--dry-run"], transport=unexpected_send) == 0


# --- rewrite tournament (24 Oct 2026): ledgers the cumulative ceiling cannot count --------------


def test_a_shared_ledger_outside_the_counted_ledgers_is_refused(
    case: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `cp0.prior_committed` sums only `<artifact-root>/.ledgers/*.jsonl`: spend on a ledger kept
    # elsewhere would be missing from this batch's ceiling check and from every later one's.
    fake_keys(monkeypatch)
    inside = earlier_batch_ledger(tmp_path)
    outside = tmp_path / "elsewhere" / inside.name
    outside.parent.mkdir()
    shutil.copyfile(inside, outside)
    inside.unlink()
    args = luna_args(tmp_path, case.frozen, "hybrid-cp1-2", outside, "--dry-run")
    assert cp1.main(args, transport=unexpected_send, stream_transport=unexpected_stream) == 2
    assert f"is not in {inside.parent}" in capsys.readouterr().err
    assert not (tmp_path / "root" / "hybrid-cp1-2").exists()
    # The same ledger reached through another spelling of the counted directory still runs.
    shutil.copyfile(outside, inside)
    respelled = inside.parent / ".." / ".ledgers" / inside.name
    args = luna_args(tmp_path, case.frozen, "hybrid-cp1-2", respelled, "--dry-run")
    assert cp1.main(args, transport=unexpected_send, stream_transport=unexpected_stream) == 0
