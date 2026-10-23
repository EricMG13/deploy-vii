"""Offline tests of the hybrid CP-1 harness: fake transport, synthetic CP-1 case, real journal."""

import hashlib
import json
import random
import re
import shutil
from collections.abc import Callable
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
            return ant_reply(("t1", f"submit_{step_id}", payload), model=self.model)
        return reply(("c1", f"submit_{step_id}", payload))


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
            "openrouter": cp1.OpenRouter(ChatClient(transport), candidate, Decimal("3.0")),
            "anthropic": cp1.Anthropic(transport, Decimal("3.0")),
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
    transport = FakeTransport(ant_reply(("t1", "search_pack", '{"query": "covenant"}')))
    provider = cp1.Anthropic(transport, Decimal("3.0"))
    tools = cp1.step_tools("source_context")
    prepared = provider.prepare(
        CELL["sonnet-xhigh"], "system text", [{"role": "user", "content": "u"}], tools, 60.0
    )
    body = json.loads(prepared.payload)
    assert body == {
        "model": SONNET,
        "max_tokens": 32000,
        "system": "system text",
        "messages": [{"role": "user", "content": "u"}],
        "tools": [{"name": n, "description": d, "input_schema": s} for n, d, s in tools],
        "tool_choice": {"type": "any"},
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "xhigh"},
        "cache_control": {"type": "ephemeral"},
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
        10_000 * Decimal("5.00") + 32_000 * Decimal("20.00")
    ) / Decimal(1_000_000)


def test_assistant_content_goes_back_unmodified_with_one_tool_result_message(
    case: Case, tmp_path: Path
) -> None:
    first = ant_reply(
        ("t1", "search_pack", '{"query": "statement", "max_hits": 2}'),
        ("t2", "read_pages", '{"source_id": "nope", "first_page": 1, "last_page": 1}'),
    )
    transport = FakeTransport(first, Model(case, tmp_path / "model"))
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
    bad = ant_reply(("t1", "submit_source_context", "{}"))
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
    assert cells[0].verdict.startswith("stopped at source_context: opus-medium-source_context-")
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


def cli(tmp_path: Path, frozen: Path, *extra: str) -> list[str]:
    catalog = tmp_path / "models.json"
    row = catalog_row(
        cp0.MODEL, parameters=PARAMETERS, pricing=PRICING, efforts=("low", "medium", "high")
    )
    catalog.write_text(json.dumps({"data": [row]}), encoding="utf-8")
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
        sol["prompt_tokens_upper_bound"] * Decimal("0.000001") + 32000 * Decimal("0.000002")
    )
    assert plan["money"]["caps_usd"] == {"openrouter": "8", "anthropic": "17"}
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
