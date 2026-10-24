"""Task 8.0d: the tool loop's parts: pack tools, evidence rules, requests, settings, ledgers."""

import json
import shutil
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from deploy_vii.contracts import Span
from deploy_vii.cp1_workflow import FinancialSubmission
from deploy_vii.execution import Execution
from deploy_vii.live import corpus
from deploy_vii.live.client import ChatClient, ChatRequest, Response
from deploy_vii.live.ledger import OPENROUTER, Ledger, LedgerError, opening_provider
from deploy_vii.live.prompts import NO_TOOLS_RULE, PromptError, build, span_line, tools_rule
from deploy_vii.live.settings import EFFORT_LADDER, SettingsError, StepEffort, load_settings
from deploy_vii.live.submission import STEPS, submit_model_payload
from deploy_vii.live.tools import (
    INCOMPLETE,
    UNBACKED_ABSENCE,
    UNREAD_PAGE,
    PackTools,
    Seen,
    ToolError,
    ToolRules,
    absence_issues,
    completeness_issues,
    expected_cells,
    fiscal_year,
    tool_specs,
    unread_citation_issues,
)
from deploy_vii.registry import STEP_CHAINS, StepChain, tool_loop_steps
from deploy_vii.source_context import SourceContextReview
from tests.product.live_support import FAKE_KEY
from tests.product.test_workflow import cp1_case

CP1_STAGES = {"source_context", "financials", "narrative", "readiness"}


@dataclass(frozen=True)
class Case:
    store: Execution  # the synthetic CP-1 case: a pending CP-1 attempt after source_context
    ticket: str
    context: SourceContextReview
    payload: str  # its valid financials payload


@pytest.fixture(scope="module")
def case(tmp_path_factory: pytest.TempPathFactory) -> Case:
    store, _, extraction = cp1_case(tmp_path_factory.mktemp("parts"))
    attempt = store.read().attempts[1]
    context = SourceContextReview.model_validate_json(
        store.payload(attempt.steps[0].payload_sha256)
    )
    payload = extraction.model_copy(
        update={"context_step_sha256": attempt.steps[0].content_hash()}
    ).model_dump_json()
    return Case(store, attempt.ticket_id, context, payload)


# --- registry, prompt, request -----------------------------------------------------------------


def test_the_four_cp1_stages_are_the_tool_loop_steps() -> None:
    assert tool_loop_steps() == CP1_STAGES
    chain = next(c for c in STEP_CHAINS if c.module_id == "CP-1")
    with pytest.raises(ValueError, match="as a tool loop, not one of its steps"):
        StepChain(**{**chain.__dict__, "tool_steps": frozenset({"nowhere"})})


def test_a_tool_loop_prompt_names_the_tools_and_sends_no_source_block(case: Case) -> None:
    pack = case.store.pack()
    plain = build("source_context", pack, ("S1",), STEPS["source_context"].schema)
    looped = build(
        "source_context", pack, (), STEPS["source_context"].schema, submit_tool="submit_x"
    )
    assert NO_TOOLS_RULE in plain[0].content and NO_TOOLS_RULE not in looped[0].content
    assert looped[0].content == plain[0].content.replace(NO_TOOLS_RULE, tools_rule("submit_x"))
    assert "<<<SOURCE id=S1" in plain[1].content and "<<<SOURCE id=S1" not in looped[1].content
    with pytest.raises(PromptError, match="no pack SOURCE blocks"):
        build("source_context", pack, ("S1",), STEPS["source_context"].schema, submit_tool="x")
    span = Span(locator="page:3", text="Revenue 10", formula="=A1", hidden=True)
    assert span_line(span) == "locator=page:3 | formula==A1; hidden | Revenue 10"


def test_a_request_with_tools_drops_the_response_format_and_copies_the_conversation() -> None:
    turn: dict[str, Any] = {"role": "assistant", "content": None, "reasoning_details": [{"x": 1}]}
    request = ChatRequest(
        model="m",
        messages=({"role": "user", "content": "go"}, turn),
        max_tokens=10,
        response_format={"type": "json_schema"},
        reasoning_effort="medium",
        accepted_model_ids=("m",),
        tools=tool_specs("financials"),
        tool_choice="required",
    )
    body = request.body()
    assert "response_format" not in body and body["tool_choice"] == "required"
    assert body["messages"][1] == turn and body["messages"][1] is not turn
    assert body["tools"][2]["function"]["name"] == "submit_financials"
    with pytest.raises(ValueError, match="together"):
        replace(request, tool_choice=None)
    with pytest.raises(ValueError, match="together"):
        replace(request, tools=())


def test_a_tool_call_without_a_function_is_kept_with_its_reason() -> None:
    message = {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function"}]}
    body = {
        "id": "g",
        "model": "m",
        "choices": [{"finish_reason": "tool_calls", "message": message}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost": 0.0},
    }
    client = ChatClient(lambda _: Response(200, json.dumps(body).encode()))
    request = ChatRequest(
        model="m",
        messages=({"role": "user", "content": "go"},),
        max_tokens=10,
        response_format={},
        reasoning_effort=None,
        accepted_model_ids=("m",),
        tools=tool_specs("financials"),
        tool_choice="required",
    )
    result = client.complete(request, key=FAKE_KEY)
    assert result.message == message
    (call,) = result.tool_calls
    assert call.problem == "malformed tool call without a function" and call.call_id == ""


# --- pack tools ------------------------------------------------------------------------------


def paged(store: Execution) -> PackTools:
    pack = store.pack()
    source = pack.sources[0]
    spans = tuple(Span(locator=f"page:{n}", text=f"Page {n} revenue") for n in range(1, 8))
    return PackTools(
        pack.model_copy(update={"sources": (source.model_copy(update={"spans": spans}),)})
    )


def test_the_pack_tools_record_what_the_model_was_shown(case: Case) -> None:
    tools = paged(case.store)
    assert tools.located_pages == 7
    text = tools.read_pages({"source_id": "S1", "first_page": 6, "last_page": 9})
    assert "locator=page:6 | Page 6 revenue" in text and "page:9 is not a located span" in text
    tools.search_pack({"query": "revenue", "source_id": "S1", "max_hits": 2})
    tools.search_pack({"query": "revenue"})
    seen = tools.seen()
    assert seen.read == {("S1", "page:6"), ("S1", "page:7")}
    assert seen.searched == ("S1", None) and seen.searched_source("S9")
    for raw, reason in [
        ({"source_id": "S1", "first_page": 1, "last_page": 6}, "at most 5 pages"),
        ({"source_id": "S1", "first_page": 2, "last_page": 1}, "need 1 <= first_page"),
        ({"source_id": "S9", "first_page": 1, "last_page": 1}, "unknown source_id"),
        ({"source_id": "S1", "first_page": True, "last_page": 1}, "must be an integer"),
        ({"source_id": "S1"}, "missing"),
    ]:
        with pytest.raises(ToolError, match=reason):
            tools.read_pages(raw)
    for raw, reason in [
        ({"query": " "}, "non-empty"),
        ({"query": "x", "max_hits": 16}, "max_hits must be 1 to 15"),
        ({"query": "x", "extra": 1}, "unexpected"),
    ]:
        with pytest.raises(ToolError, match=reason):
            tools.search_pack(raw)
    assert tools.seen().searched == ("S1", None)  # a refused search records nothing
    with pytest.raises(ToolError, match="has no page:N locators"):
        PackTools(case.store.pack()).read_pages(
            {"source_id": "S1", "first_page": 1, "last_page": 1}
        )


# --- evidence rules ----------------------------------------------------------------------------


def test_the_floor_expects_is_and_cfs_per_fiscal_year_and_bs_per_period_end(case: Case) -> None:
    context, payload = case.context, case.payload
    cells = expected_cells(context)
    assert [(c.statement, c.scope.scope_id) for c in cells] == [("IS", "FY"), ("CFS", "FY")]
    assert not fiscal_year(next(s for s in context.sources[0].scopes if s.scope_id == "Q1"))
    lines = FinancialSubmission.model_validate_json(payload).financial.books[0].statement_lines
    assert completeness_issues(payload, context, 1) == ()
    many = len(lines) + 1
    issues = completeness_issues(payload, context, many)
    assert len(issues) == 2 and all(i.startswith(f"{INCOMPLETE}: ") for i in issues)
    assert issues[0].endswith(f"the floor is {many} per statement and source scope")
    assert "IS lines for S1 scope FY (2025-01-01 to 2025-12-31)" in issues[0]
    assert completeness_issues("not json", context, 1) == ()
    # A period-end scope expects balance-sheet lines on that date.
    source = context.sources[0]
    fy = next(s for s in source.scopes if s.scope_id == "FY")
    end = fy.model_copy(
        update={"scope_id": "BS25", "period_kind": "period_end", "start_date": None}
    )
    widened = context.model_copy(
        update={"sources": (source.model_copy(update={"scopes": (*source.scopes, end)}),)}
    )
    assert [c.statement for c in expected_cells(widened)] == ["IS", "CFS", "BS"]


def test_the_floor_counts_only_the_scopes_entity(case: Case) -> None:
    context, payload = case.context, case.payload
    document = json.loads(payload)
    for book in document["binding"]["books"]:
        book["entity_id"] = "someone-else"
    issues = completeness_issues(json.dumps(document), context, 1)
    assert [i.split(" lines")[0] for i in issues] == [f"{INCOMPLETE}: 0 IS", f"{INCOMPLETE}: 0 CFS"]


def test_an_absence_claim_needs_a_search_over_its_source() -> None:
    claim = json.dumps({"sources": [{"source_id": "S1", "event_scan": "no_events_identified"}]})
    (issue,) = absence_issues("source_context", claim, Seen())
    assert issue.startswith(f"{UNBACKED_ABSENCE}: sources.0.event_scan no_events_identified for S1")
    assert absence_issues("source_context", claim, Seen(searched=("S2",)))
    assert not absence_issues("source_context", claim, Seen(searched=("S1",)))
    assert not absence_issues("source_context", claim, Seen(searched=(None,)))
    gap = {"observation_id": "o", "status": "missing"}
    disclosure = {"status": "not_disclosed", "explanation": "none"}
    financial = json.dumps({"financial": {"books": [{"x": [gap], "d": disclosure}]}})
    issues = absence_issues("financials", financial, Seen())
    assert [i.split(";")[0] for i in issues] == [
        f"{UNBACKED_ABSENCE}: financial.books.0.x.0.status missing",
        f"{UNBACKED_ABSENCE}: financial.books.0.d.status not_disclosed",
    ]
    assert not absence_issues("financials", financial, Seen(searched=("S1",)))
    assert not absence_issues("narrative", financial, Seen())
    assert not absence_issues("financials", "[1]", Seen())


def test_a_cited_page_must_have_been_read() -> None:
    payload = json.dumps(
        {
            "a": {"source_id": "S1", "locator": "page:4", "quote": "q"},
            "b": [{"source_id": "S1", "locator": "metadata"}],
        }
    )
    assert unread_citation_issues(payload, Seen()) == (f"{UNREAD_PAGE}: S1 page:4",)
    assert unread_citation_issues(payload, Seen(read=frozenset({("S1", "page:4")}))) == ()


def test_the_rules_validate_their_settings_and_need_the_context_for_the_floor() -> None:
    with pytest.raises(ValueError, match="at least one line"):
        ToolRules(floor=0)
    with pytest.raises(ValueError, match="unknown tool-loop rules"):
        ToolRules(checked=("nope",))
    rules = ToolRules(floor=2, checked=())
    assert rules.active("financials") and not rules.active("narrative")
    with pytest.raises(ValueError, match="retained source_context review"):
        rules.issues("financials", "{}", seen=Seen(), context=None)
    assert rules.to_record() == {
        "completeness_floor_lines": 2,
        "completeness_floor_reason": None,
        "checked": [],
    }


def test_a_rule_issue_rejects_a_payload_the_stage_accepts(tmp_path: Path, case: Case) -> None:
    shutil.copytree(case.store.directory, tmp_path / "journal")
    journal = Execution(tmp_path / "journal")
    with pytest.raises(ValueError, match="CP-1 stages"):
        submit_model_payload(journal, case.ticket, "quality", "{}", rules=lambda _: ())
    found = submit_model_payload(
        journal, case.ticket, "financials", case.payload, rules=lambda _: ("Rule: broken",)
    ).journal
    assert found.step_repairs[-1].issues == ("Rule: broken",)
    assert found.status == "pending"  # the step's repair within the attempt is kept


# --- settings ----------------------------------------------------------------------------------


def settings_file(tmp_path: Path, extra: str) -> Path:
    text = (Path("settings/project.toml")).read_text(encoding="utf-8")
    path = tmp_path / "settings" / "project.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        text.replace("[[model_tests.candidates]]", extra + "\n[[model_tests.candidates]]", 1),
        encoding="utf-8",
    )
    return path


def test_the_effort_table_floor_and_flag_are_read_and_checked(tmp_path: Path) -> None:
    rows = (
        '[model_tests.step_effort]\nfinancials = { effort = "medium", ceiling = "xhigh" }\n'
        'narrative = { effort = "low" }\n'
    )
    loaded = load_settings(settings_file(tmp_path / "a", rows), root=tmp_path)
    assert loaded.step_effort("financials") == StepEffort("medium", "xhigh")
    assert loaded.step_effort("narrative") == StepEffort("low", "high")
    assert loaded.step_effort("readiness") == StepEffort.of(loaded.default_effort)
    for number, (bad, reason) in enumerate(
        [
            ('[model_tests.step_effort]\nnowhere = { effort = "low" }\n', "unknown step"),
            ('[model_tests.step_effort]\nnarrative = { ceiling = "low" }\n', "needs effort"),
            ("[model_tests.step_effort]\nnarrative = { effort = 1 }\n", "must be text"),
            (
                '[model_tests.step_effort]\nnarrative = { effort = "high", ceiling = "low" }\n',
                "below",
            ),
            ("[model_tests.completeness_floor]\nmin_statement_lines = 0\n", "integer >= 1"),
            ("[model_tests.completeness_floor]\nmin_statement_lines = true\n", "integer >= 1"),
            ("tool_loop = 1\n", "true or false"),
        ]
    ):
        with pytest.raises(SettingsError, match=reason):
            load_settings(settings_file(tmp_path / str(number), bad), root=tmp_path)


@given(st.sampled_from(EFFORT_LADDER), st.sampled_from(EFFORT_LADDER))
@example("medium", "high")
@example("max", "max")
def test_escalation_is_one_level_and_never_above_the_ceiling(effort: str, ceiling: str) -> None:
    rank = EFFORT_LADDER.index
    if rank(ceiling) < rank(effort):
        with pytest.raises(SettingsError):
            StepEffort(effort, ceiling)
        return
    plan = StepEffort(effort, ceiling)
    assert rank(plan.escalated()) == min(rank(effort) + 1, rank(ceiling))
    default = StepEffort.of(effort)
    assert default.ceiling == EFFORT_LADDER[max(rank(effort), rank("high"))]


# --- ledgers and the spend cross-check -----------------------------------------------------------


def test_a_ledger_records_its_provider_and_refuses_another(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    Ledger(path, Decimal(1), provider="anthropic").reserve("a", Decimal("0.1"))
    assert json.loads(path.read_text().splitlines()[0])["provider"] == "anthropic"
    with pytest.raises(LedgerError, match="holds anthropic calls, not openrouter"):
        Ledger(path, Decimal(1), provider=OPENROUTER).state()
    assert Ledger(path, Decimal(1)).state().reserved == Decimal("0.1")  # no provider: no check
    legacy = tmp_path / "legacy.jsonl"
    Ledger(legacy, Decimal(1)).reserve("a", Decimal("0.1"))
    assert "provider" not in json.loads(legacy.read_text().splitlines()[0])
    assert Ledger(legacy, Decimal(1), provider=OPENROUTER).state().reserved == Decimal("0.1")
    assert opening_provider({"event": "open"}) == OPENROUTER
    with pytest.raises(LedgerError, match="not a name"):
        opening_provider({"provider": " "})
    with pytest.raises(LedgerError, match="blank"):
        Ledger(path, Decimal(1), provider="")


def test_corpus_refuses_a_verdict_that_holds_a_tool_loop_rule(tmp_path: Path) -> None:
    directory = tmp_path / "attempt"
    (directory / "checks").mkdir(parents=True)
    issues = [f"{UNREAD_PAGE}: S1 page:4"]
    manifest = {
        "step_id": "financials",
        "status": "rejected",
        "hashes": {"journal_inputs": {}},
        "experiment_id": "b",
        "model": "m",
        "attempt_id": "a",
        "cohort": "openrouter-pool",
        "validator": {"outcome": "rejected", "issues": issues},
        "scrubbed_files": [],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "checks" / "validator.json").write_text(
        json.dumps({"outcome": "rejected", "issues": issues})
    )
    (directory / "output.md").write_text("{}")
    with pytest.raises(corpus.CorpusError, match="tool-loop evidence rule"):
        corpus.entry_from_attempt(directory)
