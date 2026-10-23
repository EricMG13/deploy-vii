"""Offline tests of the hybrid CP-0 harness: fake transport, synthetic paged pack, real journal."""

import hashlib
import json
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from deploy_vii.contracts import Span
from deploy_vii.live.cli import committed_elsewhere
from deploy_vii.live.client import ChatClient, Request, Response
from deploy_vii.live.ledger import Ledger, LedgerError, Reservation, Settlement
from deploy_vii.live.prompts import _source_body, block, build
from deploy_vii.live.submission import ReadinessSubmission, SubmittedCitation, rejection_issues
from deploy_vii.preparation import PreparedPack
from devtools import hybrid_cp0 as hybrid
from tests.product.live_support import FAKE_KEY, FakeTransport, catalog_of, catalog_row
from tests.product.test_readiness import submission_fixture

PAGES = 12
SETTINGS = Path(__file__).resolve().parents[2] / "settings" / "project.toml"
PARAMETERS = (
    "max_tokens",
    "reasoning",
    "reasoning_effort",
    "response_format",
    "structured_outputs",
    "tools",
    "tool_choice",
)
# 1,000 prompt tokens at 0.000001 plus 32,000 completion tokens at 0.000002: under 0.07 USD.
PRICING = {"prompt": "0.000001", "completion": "0.000002"}


def page_text(number: int) -> str:
    return f"Synthetic issuer FY2025 annual report page {number}. Liquidity covenant {number}."


def paged_pack() -> PreparedPack:
    base, _ = submission_fixture()
    spans = tuple(Span(locator=f"page:{n}", text=page_text(n)) for n in range(1, PAGES + 1))
    original = "".join(span.text for span in spans).encode()
    source = base.sources[0].model_copy(
        update={"spans": spans, "sha256": hashlib.sha256(original).hexdigest(), "coverage": ()}
    )
    return base.model_copy(update={"sources": (source,)})


def submission(quote: str = page_text(3)) -> str:
    """A submission that the trusted path accepts when `quote` is in page 3."""
    _, base = submission_fixture()
    cite = SubmittedCitation(source_id="filing", locator="page:3", quote=quote)

    def recite(items: tuple[Any, ...]) -> tuple[Any, ...]:
        return tuple(
            i.model_copy(update={"citations": (cite,) if i.citations else ()}) for i in items
        )

    fields = ("sources", "consumers", "gaps", "analysis")
    updated: ReadinessSubmission = base.model_copy(
        update={name: recite(getattr(base, name)) for name in fields}
    )
    return updated.model_dump_json()


def reply(
    *calls: tuple[str, str, str], cost: object = 0.01, finish: str = "tool_calls"
) -> Response:
    """A chat reply with tool calls `(id, name, arguments)` and opaque reasoning details."""
    usage: dict[str, Any] = {
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "total_tokens": 1200,
        "completion_tokens_details": {"reasoning_tokens": 150},
        "prompt_tokens_details": {"cached_tokens": 100},
    }
    if cost is not None:
        usage["cost"] = cost
    message: dict[str, Any] = {
        "role": "assistant",
        "content": None,
        "reasoning_details": [{"type": "reasoning.encrypted", "data": "opaque-1"}],
        "tool_calls": [
            {"id": ident, "type": "function", "function": {"name": name, "arguments": args}}
            for ident, name, args in calls
        ],
    }
    body = {
        "id": "gen-hybrid-test",
        "model": hybrid.MODEL,
        "provider": "OpenAI",
        "choices": [{"finish_reason": finish, "message": message}],
        "usage": usage,
    }
    return Response(200, json.dumps(body).encode())


def args(**values: object) -> str:
    return json.dumps(values)


class Events:
    """Interleaves ledger and transport events so their order can be asserted."""

    def __init__(self) -> None:
        self.log: list[str] = []


class LoggingLedger(Ledger):
    def __init__(self, path: Path, cap: Decimal, events: Events) -> None:
        super().__init__(path, cap)
        self.events = events

    def reserve(self, attempt_id: str, usd: Decimal) -> Reservation:
        self.events.log.append(f"reserve {attempt_id}")
        return super().reserve(attempt_id, usd)

    def settle(self, attempt_id: str, actual_usd: Decimal | None, reason: str) -> Settlement:
        self.events.log.append(f"settle {attempt_id}")
        return super().settle(attempt_id, actual_usd, reason)


def logging_transport(events: Events, inner: FakeTransport) -> Callable[[Request], Response]:
    def send(request: Request) -> Response:
        events.log.append("send")
        return inner(request)

    return send


def make_harness(
    tmp_path: Path,
    transport: Callable[[Request], Response],
    *,
    cap: Decimal = Decimal(5),
    events: Events | None = None,
    clock: Callable[[], float] | None = None,
) -> hybrid.Harness:
    catalog = catalog_of(catalog_row(hybrid.MODEL, parameters=PARAMETERS, pricing=PRICING))
    candidate = catalog.pin_selected("t", (hybrid.ModelSelection(hybrid.MODEL, "high"),))
    ledger_path = tmp_path / ".ledgers" / "hybrid-test.jsonl"
    ledger = LoggingLedger(ledger_path, cap, events) if events else Ledger(ledger_path, cap)
    harness = hybrid.Harness(
        pack=paged_pack(),
        candidate=candidate.candidate(hybrid.MODEL),
        effort_sent="high",
        ledger=ledger,
        client=ChatClient(transport),
        key=FAKE_KEY,
        bytes_per_token=Decimal("3.0"),
        batch_directory=tmp_path / "batch",
    )
    harness.batch_directory.mkdir()
    if clock is not None:
        harness.clock = clock
    return harness


def draws(harness: hybrid.Harness, count: int = 1) -> list[hybrid.Draw]:
    return [
        hybrid.Draw(f"hybrid-{n}", n, harness.batch_directory / f"hybrid-{n}")
        for n in range(1, count + 1)
    ]


def sent_bodies(transport: FakeTransport) -> list[dict[str, Any]]:
    return [json.loads(request.body or b"{}") for request in transport.requests]


# --- prompt -----------------------------------------------------------------------------------


def test_the_hybrid_prompt_is_the_runner_prompt_without_source_blocks() -> None:
    pack = paged_pack()
    schema = hybrid.STEPS[hybrid.STEP].schema
    one_shot = build(hybrid.STEP, pack, ("filing",), schema)
    system, user = hybrid.hybrid_messages(pack)
    assert system["content"] == one_shot[0].content.replace(hybrid.NO_TOOLS_RULE, hybrid.TOOLS_RULE)
    assert hybrid.NO_TOOLS_RULE not in system["content"]
    assert user["content"].startswith("<<<CONTEXT id=prepared-pack")
    assert "<<<SOURCE" not in user["content"]
    assert one_shot[1].content.startswith(user["content"] + "\n\n<<<SOURCE id=filing")


def test_the_request_sends_tools_and_the_conversation_without_response_format() -> None:
    conversation = ({"role": "user", "content": "x"}, {"role": "tool", "tool_call_id": "a"})
    body = hybrid.ToolChatRequest(
        model=hybrid.MODEL,
        messages=(),
        max_tokens=hybrid.MAX_TOKENS,
        response_format={},
        reasoning_effort="high",
        conversation=conversation,
        tools=hybrid.tool_specs(),
    ).body()
    assert "response_format" not in body
    assert body["messages"] == list(conversation)
    assert [tool["function"]["name"] for tool in body["tools"]] == [
        "search_pack",
        "read_pages",
        "submit_readiness",
    ]
    assert body["tool_choice"] == "required"
    assert body["provider"] == {"allow_fallbacks": False, "require_parameters": True}
    assert body["reasoning"] == {"effort": "high"} and body["max_tokens"] == 32000


# --- tools ------------------------------------------------------------------------------------


def test_read_pages_returns_the_one_shot_rendering_of_each_page_and_at_most_five() -> None:
    pack = paged_pack()
    source = pack.sources[0]
    digest, whole = _source_body(pack, "filing")
    assert "\n".join(hybrid.span_line(span) for span in source.spans) == whole
    tools = hybrid.PackTools(pack)
    text = tools.read_pages({"source_id": "filing", "first_page": 2, "last_page": 6})
    expected = [
        block("SOURCE", "filing", digest, f"locator=page:{n} | {page_text(n)}") for n in range(2, 7)
    ]
    assert text == "\n".join(expected)
    assert tools.read == {("filing", f"page:{n}") for n in range(2, 7)}
    with pytest.raises(hybrid.ToolError, match="at most 5 pages"):
        tools.read_pages({"source_id": "filing", "first_page": 1, "last_page": 6})
    tail = tools.read_pages({"source_id": "filing", "first_page": 11, "last_page": 13})
    assert "page:13 is not a located span of filing." in tail
    assert tools.located_pages == PAGES


def test_search_ranks_by_match_count_and_quotes_exact_snippets() -> None:
    pack = paged_pack()
    long_page = Span(locator="page:4", text="x" * 400 + " Covenant covenant COVENANT " + "y" * 400)
    spans = tuple(long_page if span.locator == "page:4" else span for span in pack.sources[0].spans)
    pack = pack.model_copy(
        update={"sources": (pack.sources[0].model_copy(update={"spans": spans}),)}
    )
    tools = hybrid.PackTools(pack)
    text = tools.search_pack({"query": "covenant", "source_id": "filing", "max_hits": 2})
    assert text.startswith("12 spans match 'covenant'; showing 2.")
    first = text.split("\n")[1:5]
    assert first[0] == "hit 1: matches=3 phrase_matches=3"
    assert first[1].startswith("<<<SOURCE id=filing sha256=") and first[3] == "<<<END>>>"
    assert first[2].startswith("locator=page:4 | ")
    snippet = first[2].split(" | ", 1)[1]
    assert snippet in long_page.text and len(snippet) == 300 + len("Covenant") + 300
    assert tools.surfaced == {("filing", "page:4"), ("filing", "page:1")}
    assert tools.read == set()
    phrase = tools.search_pack({"query": "annual   REPORT page 7."})
    assert phrase.split("\n")[3].startswith("locator=page:7 | ")


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("delete_pack", args(path="/"), "error: unknown tool 'delete_pack'"),
        ("read_pages", "{not json", "error: bad arguments: invalid JSON"),
        ("read_pages", "[1, 2]", "error: bad arguments: not a JSON object"),
        ("read_pages", args(source_id="filing", first_page="1", last_page=2), "first_page must"),
        ("read_pages", args(source_id="other", first_page=1, last_page=2), "unknown source_id"),
        ("search_pack", args(query="  "), "query must be non-empty"),
        ("search_pack", args(query="a", max_hits=16), "max_hits must be 1 to 15"),
        ("search_pack", args(query="a", max_hits=True), "max_hits must be an integer"),
        ("search_pack", args(query="a", shell="ls"), "unexpected ['shell']"),
        ("submit_readiness", "[]", "error: bad arguments: not a JSON object"),
    ],
)
def test_unknown_tools_and_bad_arguments_become_counted_error_results(
    tmp_path: Path, name: str, arguments: str, message: str
) -> None:
    harness = make_harness(tmp_path, FakeTransport())
    draw = draws(harness)[0]
    draw.tools = hybrid.PackTools(harness.pack)
    status, text = hybrid._execute(harness, draw, name, arguments)
    assert status == "error" and text.startswith("error: ") and message in text
    assert draw.counts["invalid"] == 1 and draw.submits == []


# --- judging ----------------------------------------------------------------------------------


def test_the_verdict_is_the_runners_journal_not_rejection_issues_alone(tmp_path: Path) -> None:
    pack = paged_pack()
    assert hybrid.judge(pack, tmp_path / "good", submission()) == hybrid.Verdict("accepted", ())
    false_quote = submission(quote="words the page never says")
    # The brief's check passes a payload that composes cleanly, false quotes included ...
    assert rejection_issues(pack, false_quote) == ()
    # ... while the runner's trusted path (validate_review) rejects it.
    verdict = hybrid.judge(pack, tmp_path / "bad", false_quote)
    assert verdict.outcome == "rejected"
    assert {hybrid.issue_class(issue) for issue in verdict.issues} == {"Quote/locator mismatch"}


# --- a scripted conversation ------------------------------------------------------------------


def test_a_scripted_conversation_produces_the_right_metrics(tmp_path: Path) -> None:
    transport = FakeTransport(
        reply(("c1", "search_pack", args(query="covenant", max_hits=3))),
        reply(("c2", "read_pages", args(source_id="filing", first_page=1, last_page=3))),
        reply(("c3", "submit_readiness", submission(quote="not in the page"))),
        reply(
            ("c4", "delete_pack", args()),
            ("c5", "submit_readiness", submission()),
            ("c6", "read_pages", args(source_id="filing", first_page=9, last_page=9)),
        ),
    )
    harness = make_harness(tmp_path, transport)
    summary = hybrid.run_batch(harness, draws(harness))
    metrics = json.loads((harness.batch_directory / "hybrid-1" / "metrics.json").read_text())
    assert metrics["verdict"] == "accepted" and summary["stopped"] is None
    assert metrics["calls"] == 4
    assert metrics["tool_calls"] == {
        "search_pack": 1,
        "read_pages": 1,
        "submit_readiness": 2,
        "invalid": 1,
    }
    assert [item["outcome"] for item in metrics["submits"]] == ["rejected", "accepted"]
    assert metrics["issue_classes"] == {"Quote/locator mismatch": 1}  # the journal de-duplicates
    assert metrics["submit_shrinkage"]["flag"] is False  # same counts, only the quote changed
    assert metrics["prompt_tokens"] == 4000 and metrics["completion_tokens"] == 800
    assert metrics["reasoning_tokens"] == 600 and metrics["cached_tokens"] == 400
    assert metrics["cost_settled_usd"] == "0.04" and metrics["cost_held_usd"] == "0"
    assert metrics["finish_reasons"] == ["tool_calls"] * 4
    assert metrics["served"] == [[hybrid.MODEL, "OpenAI"]]
    coverage = metrics["coverage"]
    assert coverage["pages_read"] == 3 and coverage["fraction_read"] == 3 / PAGES
    assert coverage["cited_not_read"] == [] and coverage["final_payload_cited_locators"] == 1
    assert all(call["latency_s"] is not None for call in metrics["per_call"])

    bodies = sent_bodies(transport)
    assert all(len(body["tools"]) == 3 for body in bodies)
    last = bodies[-1]["messages"]
    assert [m["role"] for m in last] == ["system", "user"] + ["assistant", "tool"] * 3
    assert last[2]["reasoning_details"] == [{"type": "reasoning.encrypted", "data": "opaque-1"}]
    assert last[5]["tool_call_id"] == "c2" and last[5]["content"].startswith("<<<SOURCE id=filing")
    assert last[7]["content"].startswith("rejected (2 submits left):\n- Quote/locator mismatch")
    log = [
        json.loads(line)
        for line in (harness.batch_directory / "hybrid-1" / "tool-calls.jsonl")
        .read_text()
        .splitlines()
    ]
    assert [entry["status"] for entry in log] == [
        "ok",
        "ok",
        "rejected",
        "error",
        "accepted",
        "not executed: the draw has a final verdict",
    ]
    assert log[1]["result"] == last[5]["content"]
    assert (harness.batch_directory / "hybrid-1" / "journal-submit-2" / "current").exists()


def test_the_third_rejected_submit_is_final(tmp_path: Path) -> None:
    bad = submission(quote="never said")
    transport = FakeTransport(*(reply((f"s{n}", "submit_readiness", bad)) for n in range(3)))
    harness = make_harness(tmp_path, transport)
    hybrid.run_batch(harness, draws(harness))
    metrics = json.loads((harness.batch_directory / "hybrid-1" / "metrics.json").read_text())
    assert metrics["verdict"] == "rejected" and metrics["calls"] == 3
    assert len(metrics["submits"]) == 3 and transport.replies == []


def test_a_reply_without_tool_calls_ends_the_draw(tmp_path: Path) -> None:
    body = json.loads(reply(cost=0.01).body)
    body["choices"][0] = {
        "finish_reason": "stop",
        "message": {"role": "assistant", "content": "{}"},
    }
    harness = make_harness(tmp_path, FakeTransport(Response(200, json.dumps(body).encode())))
    hybrid.run_batch(harness, draws(harness))
    metrics = json.loads((harness.batch_directory / "hybrid-1" / "metrics.json").read_text())
    assert metrics["verdict"] == "rejected: no-submit"


# --- limits, money and the cap ----------------------------------------------------------------


def test_the_call_limit_ends_the_draw(tmp_path: Path) -> None:
    search = args(query="covenant")
    transport = FakeTransport(*(reply((f"c{n}", "search_pack", search)) for n in range(25)))
    harness = make_harness(tmp_path, transport, cap=Decimal(100))
    hybrid.run_batch(harness, draws(harness))
    metrics = json.loads((harness.batch_directory / "hybrid-1" / "metrics.json").read_text())
    assert metrics["verdict"] == "rejected: limit" and metrics["calls"] == 25
    assert metrics["verdict_reason"].startswith("25 calls")


def test_the_wall_clock_limit_ends_the_draw(tmp_path: Path) -> None:
    ticks: Iterator[float] = iter(float(n * 200) for n in range(1000))
    transport = FakeTransport(*(reply((f"c{n}", "search_pack", args(query="x"))) for n in range(9)))
    harness = make_harness(tmp_path, transport, clock=lambda: next(ticks))
    hybrid.run_batch(harness, draws(harness))
    metrics = json.loads((harness.batch_directory / "hybrid-1" / "metrics.json").read_text())
    assert metrics["verdict"] == "rejected: limit"
    assert metrics["calls"] < 9 and metrics["wall_clock_s"] >= hybrid.DEADLINE_S


def test_reservation_precedes_each_send_and_a_missing_cost_holds_it(tmp_path: Path) -> None:
    events = Events()
    inner = FakeTransport(
        reply(("c1", "search_pack", args(query="covenant")), cost=None),
        reply(("c2", "submit_readiness", submission())),
    )
    harness = make_harness(tmp_path, logging_transport(events, inner), events=events)
    hybrid.run_batch(harness, draws(harness))
    assert events.log == [
        "reserve hybrid-1-call-01",
        "send",
        "settle hybrid-1-call-01",
        "reserve hybrid-1-call-02",
        "send",
        "settle hybrid-1-call-02",
    ]
    metrics = json.loads((harness.batch_directory / "hybrid-1" / "metrics.json").read_text())
    held = Decimal(metrics["per_call"][0]["reserved_usd"])
    assert Decimal(metrics["cost_held_usd"]) == held and metrics["per_call"][0]["cost_held"]
    assert metrics["cost_settled_usd"] == "0.01"
    assert metrics["per_call"][0]["cost_usd"] is None
    assert metrics["per_call"][0]["cost_usd_reason"] == "field absent from usage"
    for call in metrics["per_call"]:
        body = json.loads(
            (
                harness.batch_directory / "hybrid-1" / f"call-0{call['call']}-request.json"
            ).read_text()
        )["body"]
        bound = hybrid.prompt_token_bound(body, Decimal("3.0"))
        assert call["prompt_tokens_upper_bound"] == bound
        assert Decimal(call["reserved_usd"]) == hybrid.reservation_usd(
            harness.candidate, bound, 32000
        )


def test_the_batch_stops_when_a_reservation_would_exceed_the_cap(tmp_path: Path) -> None:
    transport = FakeTransport(
        reply(("c1", "search_pack", args(query="covenant")), cost=None),
        reply(("c2", "submit_readiness", submission())),
    )
    harness = make_harness(tmp_path, transport)
    # The cap admits the first call (held in full: no cost) but not a second of at least its size.
    (tmp_path / "probe").mkdir()
    probe = make_harness(tmp_path / "probe", FakeTransport())
    request = hybrid.ToolChatRequest(
        model=hybrid.MODEL,
        messages=(),
        max_tokens=hybrid.MAX_TOKENS,
        response_format={},
        reasoning_effort="high",
        conversation=tuple(hybrid.hybrid_messages(probe.pack)),
        tools=hybrid.tool_specs(),
    )
    one = hybrid.reservation_usd(
        probe.candidate, hybrid.prompt_token_bound(request.body(), Decimal("3.0")), 32000
    )
    harness.ledger = Ledger(tmp_path / ".ledgers" / "capped.jsonl", one + one / 2)
    summary = hybrid.run_batch(harness, draws(harness, 2))
    assert len(transport.requests) == 1  # the second call was refused before sending
    assert summary["stopped"].startswith("hybrid-1-call-02 not sent: reserving")
    rows = {row["draw_id"]: row for row in summary["draws"]}
    assert rows["hybrid-1"]["verdict"] == "stopped" and rows["hybrid-2"]["verdict"] == "not run"
    assert not (harness.batch_directory / "hybrid-2").exists()
    assert summary["ledger"]["reserved_open"] == 0 and summary["ledger"]["attempts"] == 1


def test_credit_exhaustion_stops_the_batch(tmp_path: Path) -> None:
    refused = Response(402, json.dumps({"error": {"code": 402, "message": "no credit"}}).encode())
    harness = make_harness(tmp_path, FakeTransport(refused))
    summary = hybrid.run_batch(harness, draws(harness, 2))
    assert summary["stopped"] == "credit exhausted (HTTP 402)"
    assert [row["verdict"] for row in summary["draws"]] == [
        "no-response: insufficient_credit",
        "not run",
    ]


# --- the key ----------------------------------------------------------------------------------


def test_the_key_never_appears_in_retained_files(tmp_path: Path) -> None:
    leaky = submission().replace("Synthetic issuer", f"Synthetic {FAKE_KEY} issuer", 1)
    transport = FakeTransport(
        reply(("c1", "search_pack", args(query=FAKE_KEY))),
        reply(("c2", "submit_readiness", leaky)),
        ConnectionError(f"Authorization: Bearer {FAKE_KEY}"),
    )
    harness = make_harness(tmp_path, transport)
    hybrid.run_batch(harness, draws(harness, 2))
    assert transport.requests[0].headers["Authorization"] == f"Bearer {FAKE_KEY}"
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(files) > 10
    for path in files:
        assert FAKE_KEY not in path.read_bytes().decode("utf-8", errors="replace"), path
    for name in ("call-01-response.json", "call-02-response.json", "tool-calls.jsonl"):
        assert "[REDACTED]" in (harness.batch_directory / "hybrid-1" / name).read_text()
    second = json.loads((harness.batch_directory / "hybrid-2" / "metrics.json").read_text())
    assert second["verdict"] == "no-response: transport_error"
    assert "[REDACTED]" in second["per_call"][0]["transport_error"]


# --- command line -----------------------------------------------------------------------------


def write_pack(directory: Path, pack: PreparedPack) -> Path:
    directory.mkdir()
    (directory / "pack.json").write_text(pack.model_dump_json(), encoding="utf-8")
    (directory / "complete.json").write_text(
        json.dumps({"pack_sha256": pack.content_hash()}), encoding="utf-8"
    )
    (directory / "originals").mkdir()
    original = "".join(span.text for span in pack.sources[0].spans).encode()
    (directory / "originals" / str(pack.sources[0].sha256)).write_bytes(original)
    return directory


def cli_args(tmp_path: Path, *extra: str) -> list[str]:
    catalog = tmp_path / "models.json"
    if not catalog.exists():
        row = catalog_row(hybrid.MODEL, parameters=PARAMETERS, pricing=PRICING)
        catalog.write_text(json.dumps({"data": [row]}), encoding="utf-8")
    pack = tmp_path / "pack"
    if not pack.exists():
        write_pack(pack, paged_pack())
    return [
        "--pack",
        str(pack),
        "--artifact-root",
        str(tmp_path / "root"),
        "--settings",
        str(SETTINGS),
        "--catalog",
        str(catalog),
        *extra,
    ]


def unexpected_send(request: Request) -> Response:
    raise AssertionError(f"dry run sent {request.url}")


def test_the_dry_run_prints_the_plan_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert hybrid.main(cli_args(tmp_path, "--dry-run"), transport=unexpected_send) == 0
    plan = json.loads(capsys.readouterr().out)
    assert [item["draw_id"] for item in plan["order"]] == ["hybrid-1", "hybrid-2", "hybrid-3"]
    assert plan["money"]["cap_usd"] == "5"
    first = plan["money"]["first_call"]
    assert Decimal(first["reserved_usd"]) == (
        first["prompt_tokens_upper_bound"] * Decimal("0.000001") + 32000 * Decimal("0.000002")
    )
    assert plan["pack"]["located_pages"] == PAGES
    assert not (tmp_path / "root").exists()


def test_the_command_refuses_a_used_batch_and_the_cumulative_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledgers = tmp_path / "root" / ".ledgers"
    Ledger(ledgers / "hybrid-cp0-1.jsonl", Decimal(5)).reserve("a", Decimal(1))
    assert hybrid.main(cli_args(tmp_path, "--dry-run"), transport=unexpected_send) == 2
    assert "already has a ledger" in capsys.readouterr().err
    Ledger(ledgers / "other.jsonl", Decimal(196)).reserve("b", Decimal(195))
    argv = cli_args(tmp_path, "--dry-run", "--batch-id", "fresh")
    assert hybrid.main(argv, transport=unexpected_send) == 2
    assert "exceeds 200" in capsys.readouterr().err


def test_the_command_refuses_a_model_without_tools(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    row = catalog_row(hybrid.MODEL, parameters=PARAMETERS[:-2], pricing=PRICING)
    (tmp_path / "models.json").write_text(json.dumps({"data": [row]}), encoding="utf-8")
    assert hybrid.main(cli_args(tmp_path, "--dry-run"), transport=unexpected_send) == 2
    assert "['tools', 'tool_choice']" in capsys.readouterr().err


def unknown_adjust(seq: int, **changes: object) -> dict[str, object]:
    """An `adjust` from a source this code's ledger cannot replay (M7's account-usage-delta)."""
    line: dict[str, object] = {
        "seq": seq,
        "event": "adjust",
        "attempt_id": "a",
        "previous_charged_usd": "1",
        "reconciled_usd": "0",
        "source": "account-usage-delta",
        "generation_id": "gen-x",
        "checked_at": "2026-10-23T00:00:00Z",
        "at": "2026-10-23T00:00:00Z",
    }
    return line | changes


def newer_ledger(ledgers: Path, adjust: dict[str, object] | None = None) -> Path:
    """a held at 1 (then adjusted from an unknown source), b settled at 0.5, c open at 0.25."""
    ledger = Ledger(ledgers / "newer.jsonl", Decimal(5))
    ledger.reserve("a", Decimal(1))
    ledger.settle("a", None, "held")
    ledger.reserve("b", Decimal(2))
    ledger.settle("b", Decimal("0.5"), "usage.cost")
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    lines.append(json.dumps(unknown_adjust(6) if adjust is None else adjust))
    lines.append(
        json.dumps({"seq": 7, "event": "reserve", "attempt_id": "c", "usd": "0.25", "at": "x"})
    )
    ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ledger.path


def test_an_unknown_adjust_counts_at_its_pre_adjust_charge_and_is_logged(tmp_path: Path) -> None:
    ledgers = tmp_path / ".ledgers"
    plain = Ledger(ledgers / "plain.jsonl", Decimal(5))
    plain.reserve("x", Decimal(3))
    plain.settle("x", Decimal(2), "usage.cost")
    assert committed_elsewhere(ledgers) == Decimal(2)  # the runner's own sum agrees
    assert hybrid.prior_committed(ledgers) == hybrid.PriorSpend(Decimal(2), ())
    newer_ledger(ledgers)
    with pytest.raises(LedgerError, match="unknown source"):
        committed_elsewhere(ledgers)  # the runner's code cannot replay it
    prior = hybrid.prior_committed(ledgers)
    assert prior.total == Decimal("3.75")  # 1 (worst case) + 0.5 + 0.25 open + 2
    assert prior.worst_case_adjusts == (
        {
            "ledger": "newer.jsonl",
            "seq": 6,
            "attempt_id": "a",
            "source": "account-usage-delta",
            "previous_charged_usd": "1",
        },
    )


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        ("torn", "torn line"),
        ("bad-json", "not valid JSON"),
        ("no-previous", "without a previous_charged_usd"),
        ("wrong-previous", "does not start from the settled charge"),
        ("other-error", "settles z without an open reservation"),
    ],
)
def test_any_other_unreadable_ledger_still_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], damage: str, message: str
) -> None:
    ledgers = tmp_path / "root" / ".ledgers"
    adjust = {
        "no-previous": {k: v for k, v in unknown_adjust(6).items() if k != "previous_charged_usd"},
        "wrong-previous": unknown_adjust(6, previous_charged_usd="0.9"),
    }.get(damage)
    path = newer_ledger(ledgers, adjust)
    text = path.read_text(encoding="utf-8")
    if damage == "torn":
        path.write_text(text + '{"seq": 8', encoding="utf-8")
    elif damage == "bad-json":
        path.write_text(text + "not json\n", encoding="utf-8")
    elif damage == "other-error":
        line = {"seq": 8, "event": "settle", "attempt_id": "z", "charged_usd": "1", "reason": "r"}
        path.write_text(text + json.dumps(line) + "\n", encoding="utf-8")
    with pytest.raises(LedgerError, match=message):
        hybrid.prior_committed(ledgers)
    assert hybrid.main(cli_args(tmp_path, "--dry-run"), transport=unexpected_send) == 2
    assert capsys.readouterr().err.startswith("refused: prior ledgers cannot be counted")


def test_the_dry_run_starts_and_prints_the_worst_case_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    newer_ledger(tmp_path / "root" / ".ledgers")
    assert hybrid.main(cli_args(tmp_path, "--dry-run"), transport=unexpected_send) == 0
    captured = capsys.readouterr()
    plan = json.loads(captured.out)
    assert plan["money"]["prior_committed_usd"] == "1.75"
    assert plan["money"]["prior_worst_case_adjusts"][0]["seq"] == 6
    assert "worst case: newer.jsonl seq 6 attempt a source account-usage-delta" in captured.err
    assert not (tmp_path / "root" / "hybrid-cp0-1").exists()


def test_the_batch_summary_records_the_worst_case_lines(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, FakeTransport(reply(("s", "submit_readiness", submission()))))
    prior = hybrid.prior_committed(newer_ledger(tmp_path / "prior").parent)
    summary = hybrid.run_batch(harness, draws(harness), prior=prior)
    assert summary["prior_committed"]["total_usd"] == Decimal("1.75")
    assert summary["prior_committed"]["worst_case_adjusts"][0]["attempt_id"] == "a"


def test_a_call_cut_short_by_the_draw_deadline_is_the_limit(tmp_path: Path) -> None:
    ticks = iter([0.0, 850.0, 950.0, 960.0])  # start, before call 1, after it, wall clock
    harness = make_harness(tmp_path, FakeTransport(TimeoutError()), clock=lambda: next(ticks))
    hybrid.run_batch(harness, draws(harness))
    metrics = json.loads((harness.batch_directory / "hybrid-1" / "metrics.json").read_text())
    assert metrics["verdict"] == "rejected: limit"
    assert metrics["verdict_reason"] == "deadline of 900.0 s reached during call 1"
    body = json.loads((harness.batch_directory / "hybrid-1" / "call-01-request.json").read_text())
    assert "timeout_s" not in body["body"]  # the 50 s bound is the client's, not the body's


def test_an_interrupted_draw_still_retains_its_metrics(tmp_path: Path) -> None:
    harness = make_harness(tmp_path, FakeTransport(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        hybrid.run_batch(harness, draws(harness))
    metrics = json.loads((harness.batch_directory / "hybrid-1" / "metrics.json").read_text())
    assert metrics["verdict"] == "not run" and metrics["calls"] == 1
    call = metrics["per_call"][0]
    assert call["cost_held"] and metrics["cost_held_usd"] == call["reserved_usd"]
    assert harness.ledger.state().reserved == 0  # settled: the reservation is held as spent


# --- shrink-to-pass detection -----------------------------------------------------------------


def with_extra_false_claim(payload: str) -> str:
    """`payload` plus a second claim whose quote is not in its page (so the submit is rejected)."""
    document = json.loads(payload)
    claim = json.loads(json.dumps(document["analysis"][0]))
    claim["claim_id"] = claim["claim_id"] + "-extra"
    claim["citations"] = [{"source_id": "filing", "locator": "page:5", "quote": "not on page 5"}]
    claim["limitation"] = "Extra claim limitation"
    document["analysis"].append(claim)
    return json.dumps(document)


def test_payload_counts_are_exact() -> None:
    document = json.loads(submission())
    counts = hybrid.payload_counts(submission())
    groups = ("sources", "consumers", "gaps", "analysis")
    assert counts == {
        "source_judgments": len(document["sources"]),
        "consumer_judgments": len(document["consumers"]),
        "gaps": len(document["gaps"]),
        "claims": len(document["analysis"]),
        "citations": sum(len(i["citations"]) for name in groups for i in document[name]),
        "limitations": sum(
            len(i["limitations"]) for i in document["sources"] + document["consumers"]
        )
        + sum(1 for i in document["analysis"] if i["limitation"] is not None),
    }
    extra = hybrid.payload_counts(with_extra_false_claim(submission()))
    assert extra is not None and counts is not None
    assert extra["claims"] == counts["claims"] + 1
    assert extra["citations"] == counts["citations"] + 1
    assert extra["limitations"] == counts["limitations"] + 1
    assert hybrid.payload_counts("[]") is None and hybrid.payload_counts("{not json") is None


def test_a_later_submit_with_fewer_claims_sets_the_shrinkage_flag(tmp_path: Path) -> None:
    transport = FakeTransport(
        reply(("s1", "submit_readiness", with_extra_false_claim(submission()))),
        reply(("s2", "submit_readiness", submission())),
    )
    harness = make_harness(tmp_path, transport)
    summary = hybrid.run_batch(harness, draws(harness))
    metrics = json.loads((harness.batch_directory / "hybrid-1" / "metrics.json").read_text())
    assert [item["outcome"] for item in metrics["submits"]] == ["rejected", "accepted"]
    first, second = (item["counts"] for item in metrics["submits"])
    shrink = metrics["submit_shrinkage"]
    assert shrink["flag"] is True
    assert shrink["dropped"] == [
        {
            "submit": 2,
            "first_then_now": {
                name: [first[name], second[name]] for name in ("claims", "citations", "limitations")
            },
        }
    ]
    assert second["claims"] == first["claims"] - 1
    assert summary["draws"][0]["submit_shrinkage"]["flag"] is True


def test_shrinkage_is_not_flagged_without_a_drop_or_a_second_submit() -> None:
    counts = hybrid.payload_counts(submission())
    same = [{"submit": 1, "counts": counts}, {"submit": 2, "counts": counts}]
    assert hybrid.shrinkage(same)["flag"] is False
    assert hybrid.shrinkage(same[:1]) == {
        "flag": False,
        "dropped": [],
        "basis": "fewer than two submits",
    }
    unreadable = [{"submit": 1, "counts": None}, {"submit": 2, "counts": counts}]
    assert hybrid.shrinkage(unreadable)["flag"] is None
    broken = [{"submit": 1, "counts": counts}, {"submit": 2, "counts": None}]
    assert hybrid.shrinkage(broken)["dropped"] == [{"submit": 2, "not_a_json_object": True}]
