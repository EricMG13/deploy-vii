"""Task 8.0d: the tool loop's parts: pack tools, evidence rules, requests, settings, ledgers."""

import json
import random
import re
import shutil
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast, get_args

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from deploy_vii.contracts import Source, Span
from deploy_vii.cp1_workflow import FinancialSubmission
from deploy_vii.execution import Execution
from deploy_vii.financial_contracts import FinancialBook, FinancialReview
from deploy_vii.live import corpus
from deploy_vii.live.client import ChatClient, ChatRequest, Response
from deploy_vii.live.ledger import OPENROUTER, Ledger, LedgerError, opening_provider
from deploy_vii.live.prompts import (
    EXTRACT_RULE,
    NO_TOOLS_RULE,
    STEP_CONTRACTS,
    PromptError,
    build,
    span_line,
    tools_rule,
)
from deploy_vii.live.retention import AttemptWriter
from deploy_vii.live.runner import journal_outcome
from deploy_vii.live.schema import exact_json, json_object, strict_schema
from deploy_vii.live.settings import EFFORT_LADDER, SettingsError, StepEffort, load_settings
from deploy_vii.live.submission import (
    BOOK_PARTS,
    PART_KINDS,
    STEPS,
    Parts,
    assemble,
    check_part,
    partial_schema,
    submit_model_payload,
)
from deploy_vii.live.tools import (
    ABSENCE,
    ABSENCE_MARKERS,
    EXTRACT,
    INCOMPLETE,
    MAX_PAGES_PER_EXTRACT,
    UNBACKED_ABSENCE,
    UNREAD,
    UNREAD_PAGE,
    PackTools,
    Seen,
    ToolError,
    ToolRules,
    absence_issues,
    absence_markers,
    applicable_rules,
    completeness_issues,
    expected_cells,
    extracted_coverage,
    fiscal_year,
    seen_tables,
    tool_specs,
    unread_citation_issues,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import shape_issues
from deploy_vii.registry import (
    PACK_TOOLS,
    STEP_CHAINS,
    SUBMIT_ONLY,
    StepChain,
    extract_tool_steps,
    pack_tool_steps,
    part_submit_steps,
    step_modules,
    tool_loop_steps,
    tool_set,
    tool_sets,
)
from deploy_vii.source_context import SourceContextReview
from deploy_vii.statement_extract import ExtractedTable, extract_statement_lines
from tests.product import test_cp4_legal as cp4_tests
from tests.product import test_source_context as source_context_tests
from tests.product.live_support import FAKE_KEY, make_rtf_key
from tests.product.test_live_cli_batches import SETTINGS as CLI_SETTINGS
from tests.product.test_live_loop import Rig, step_rig, tool_pool, tool_reply
from tests.product.test_statement_extract import _FILLER, _row
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


# Task 8.9, user decisions 1-3 (24 Oct 2026): every live step is a tool loop; these are the
# eight steps the decisions name, with the tool set each gets. CP-1's four 8.0d loops keep the
# pack tools they had (decision 1: unchanged).
DECISION_3 = {
    "source_readiness": PACK_TOOLS,
    "business_context": PACK_TOOLS,
    "relative_value": PACK_TOOLS,
    "legal_covenants": PACK_TOOLS,
    "quality": SUBMIT_ONLY,
    "credit_synthesis": SUBMIT_ONLY,
    "integrity_review": SUBMIT_ONLY,
    "committee_challenge": SUBMIT_ONLY,
}
EVERY_TOOL_SET = {**DECISION_3, **dict.fromkeys(CP1_STAGES, PACK_TOOLS)}


def test_every_live_step_of_every_module_is_a_tool_loop_step() -> None:
    assert tool_loop_steps() == set(step_modules())
    for chain in STEP_CHAINS:
        assert chain.tool_steps == frozenset(chain.steps) and chain.one_shot == frozenset()
    chain = next(c for c in STEP_CHAINS if c.module_id == "CP-1")
    with pytest.raises(ValueError, match="runs nowhere one-shot, not one of its steps"):
        StepChain(**{**chain.__dict__, "one_shot": frozenset({"nowhere"})})
    # A chain may still name a one-shot step (the one-shot path stays for the differential).
    some = StepChain(**{**chain.__dict__, "one_shot": frozenset({"quality"})})
    assert "quality" not in some.tool_steps and "quality" not in tool_sets((some,))
    assert tool_sets((some,))["financials"] == PACK_TOOLS


def test_the_tool_set_rule_matches_decision_3_exactly() -> None:
    assert {step: tool_set(step) for step in DECISION_3} == DECISION_3
    assert tool_sets() == EVERY_TOOL_SET
    assert pack_tool_steps() == {s for s, kind in EVERY_TOOL_SET.items() if kind == PACK_TOOLS}


def test_the_tool_set_is_derived_pack_iff_the_step_quotes_or_reads_the_pack() -> None:
    """The rule: a tool-loop step gets the pack tools iff its validator checks spans against the
    pack (`pack_sources`: it must read what it quotes) or its chain lists it in `pack_reads`
    (CP-1's narrative and readiness, which 8.0d ran with the pack tools; decision 1). Every
    other tool-loop step is submit-only. Nothing is typed twice."""
    for chain in STEP_CHAINS:
        for step in chain.tool_steps:
            pack = step in chain.pack_sources or step in chain.pack_reads
            assert tool_set(step) == (PACK_TOOLS if pack else SUBMIT_ONLY), step
    assert {s for c in STEP_CHAINS for s in c.pack_reads} == {"narrative", "readiness"}
    cp1 = next(c for c in STEP_CHAINS if c.module_id == "CP-1")
    with pytest.raises(ValueError, match="lists source_context in both pack_sources and"):
        StepChain(**{**cp1.__dict__, "pack_reads": frozenset({"source_context"})})
    with pytest.raises(ValueError, match="reads the pack in nowhere, not one of its steps"):
        StepChain(**{**cp1.__dict__, "pack_reads": frozenset({"nowhere"})})
    with pytest.raises(
        ValueError, match="reads the pack in narrative by tool, which runs one-shot"
    ):
        StepChain(**{**cp1.__dict__, "one_shot": frozenset({"narrative"})})
    with pytest.raises(ValueError, match="nowhere is not a tool-loop step"):
        tool_set("nowhere")


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
    assert body["tools"][3]["function"]["name"] == "submit_financials"
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


@pytest.mark.parametrize(
    ("function", "problem"),
    [
        ({"arguments": "{}"}, "malformed tool call without a function name"),
        ({"name": 7, "arguments": "{}"}, "malformed tool call without a function name"),
        ({"name": "", "arguments": "{}"}, "malformed tool call without a function name"),
        ({"name": "search_pack"}, "malformed tool call without text arguments"),
        (
            {"name": "search_pack", "arguments": {"query": "x"}},
            "malformed tool call without text arguments",
        ),
    ],
)
def test_a_tool_call_without_a_text_name_or_arguments_is_malformed(
    function: dict[str, object], problem: str
) -> None:
    """Review B item 12: never a tool named "None" or arguments of ""."""
    item = {"id": "c1", "type": "function", "function": function}
    message = {"role": "assistant", "tool_calls": [item]}
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
    (call,) = client.complete(request, key=FAKE_KEY).tool_calls
    assert call.problem == problem and json.loads(call.arguments) == item


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
    record = rules.to_record()
    assert {k: record[k] for k in ("completeness_floor_lines", "completeness_floor_reason")} == {
        "completeness_floor_lines": 2,
        "completeness_floor_reason": None,
    }
    assert record["checked"] == [] and record["extracted_coverage_min"] is None


# Task 8.9: the rules each tool-loop step checks. CP-1's four keep 8.0d's (both; vacuous for
# narrative and readiness, which cite evidence ids only). The new pack steps cite `page:N`
# locators, so the cited-page rule applies; none of them carries the fields the absence rule
# reads, so it is omitted. Submit-only steps read nothing and check no rule.
RULES_BY_STEP = {
    **dict.fromkeys(CP1_STAGES, (ABSENCE, UNREAD)),
    **dict.fromkeys(("source_readiness", "relative_value"), (UNREAD,)),
    # Fix round 1 (user decision, 24 Oct 2026): strict absence for CP-1A and CP-4.
    **dict.fromkeys(("business_context", "legal_covenants"), (ABSENCE, UNREAD)),
    **dict.fromkeys(("quality", "credit_synthesis", "integrity_review"), ()),
    "committee_challenge": (),
}
ABSENCE_FIELDS = ('"event_scan"', '"no_events_identified"', '"missing"', '"not_disclosed"')


def test_each_tool_step_checks_only_the_rules_its_contract_can_fail() -> None:
    assert {step: applicable_rules(step) for step in RULES_BY_STEP} == RULES_BY_STEP
    assert set(RULES_BY_STEP) == tool_loop_steps()
    for step in ("source_readiness", "business_context", "relative_value", "legal_covenants"):
        sent = json.dumps(strict_schema(STEPS[step].schema))
        assert '"locator"' in sent and not [f for f in ABSENCE_FIELDS if f in sent], step
    rules = ToolRules()
    for step, kind in tool_sets().items():
        assert rules.active(step) == (kind == PACK_TOOLS), step
    cited = json.dumps({"x": {"source_id": "S1", "locator": "page:4", "quote": "q"}})
    for step in ("source_readiness", "business_context", "relative_value", "legal_covenants"):
        found = rules.issues(step, cited, seen=Seen(), context=None)
        assert found == (f"{UNREAD_PAGE}: S1 page:4",), step
        read = Seen(read=frozenset({("S1", "page:4")}))
        assert rules.issues(step, cited, seen=read, context=None) == ()
    for step in ("quality", "credit_synthesis", "integrity_review", "committee_challenge"):
        assert not ToolRules(floor=1).active(step)
        with pytest.raises(ValueError, match=f"{step} is submit-only: it checks no tool-loop"):
            rules.issues(step, cited, seen=Seen(), context=None)
    assert rules.to_record("legal_covenants")["applied"] == [ABSENCE, UNREAD]
    assert rules.to_record("credit_synthesis")["applied"] == []


def test_the_absence_markers_come_from_each_steps_sent_schema() -> None:
    """Fix round 1: a CP-1A or CP-4 row that says the sources do not disclose something (its
    schema's enum carries the marker) needs a recorded search; CP-3's `kind: none` is not a
    marker (user decision), and CP-1's stages keep 8.0d's own absence fields."""
    assert {step: absence_markers(step) for step in RULES_BY_STEP if absence_markers(step)} == {
        "business_context": (("available", "No"), ("status", "Not disclosed")),
        "legal_covenants": (("threshold_unit", "not stated"),),
    }
    assert ("kind", "none") not in ABSENCE_MARKERS
    payload = json.dumps(
        {
            "disclosure_items": [{"available": "Yes"}, {"available": "No"}],
            "operating_drivers": [{"status": "Not disclosed"}],
            "covenants": [{"threshold_unit": "not stated"}],
            "market_evidence": [{"kind": "none"}],
        }
    )
    assert absence_issues("business_context", payload, Seen()) == (
        f"{UNBACKED_ABSENCE}: disclosure_items.1.available No; search_pack before claiming it is "
        "not disclosed",
        f"{UNBACKED_ABSENCE}: operating_drivers.0.status Not disclosed; search_pack before "
        "claiming it is not disclosed",
    )
    assert absence_issues("legal_covenants", payload, Seen()) == (
        f"{UNBACKED_ABSENCE}: covenants.0.threshold_unit not stated; search_pack before claiming "
        "it is not disclosed",
    )
    for searched in (Seen(searched=(None,)), Seen(searched=("indenture",))):
        assert absence_issues("business_context", payload, searched) == ()
        assert absence_issues("legal_covenants", payload, searched) == ()
    for step in ("relative_value", "source_readiness", "narrative", "readiness"):
        assert absence_issues(step, payload, Seen()) == (), step
    assert ToolRules().issues("relative_value", payload, seen=Seen(), context=None) == ()
    assert absence_issues("legal_covenants", "[1]", Seen()) == ()


def test_a_submit_only_step_is_offered_its_submit_tool_only() -> None:
    def names(specs: tuple[dict[str, Any], ...]) -> list[str]:
        return [spec["function"]["name"] for spec in specs]

    assert names(tool_specs("credit_synthesis", SUBMIT_ONLY)) == ["submit_credit_synthesis"]
    assert names(tool_specs("legal_covenants", PACK_TOOLS)) == [
        "search_pack",
        "read_pages",
        "submit_legal_covenants",
    ]
    for step, kind in tool_sets().items():  # without a kind: the registry's
        assert tool_specs(step) == tool_specs(step, kind)
    (only,) = tool_specs("quality")
    assert only["function"]["parameters"] == strict_schema(STEPS["quality"].schema)


def test_the_pack_tools_read_only_the_steps_declared_sources(tmp_path: Path) -> None:
    pack = cp4_tests.journal(tmp_path).pack()
    assert [s.source_id for s in pack.sources] == ["filing", "indenture", "deck"]
    tools = PackTools(pack, sources=("filing", "indenture"))
    assert tools.ids == ("filing", "indenture")
    for raw in (
        {"source_id": "deck", "first_page": 1, "last_page": 1},
        {"query": "the", "source_id": "deck"},
    ):
        with pytest.raises(ToolError, match="deck is not one of the sources this step reads"):
            (tools.read_pages if "first_page" in raw else tools.search_pack)(raw)
    text = tools.search_pack({"query": "the", "max_hits": 15})
    assert "<<<SOURCE id=deck " not in text
    assert tools.seen().searched == (None,)
    everything = PackTools(pack)
    assert everything.ids == ("filing", "indenture", "deck")
    with pytest.raises(ValueError, match="nowhere is not a source of the pack"):
        PackTools(pack, sources=("nowhere",))


def test_a_rule_issue_rejects_a_payload_the_stage_accepts(tmp_path: Path, case: Case) -> None:
    shutil.copytree(case.store.directory, tmp_path / "journal")
    journal = Execution(tmp_path / "journal")
    with pytest.raises(ValueError, match=r"pack-tool steps, not to quality$"):
        submit_model_payload(journal, case.ticket, "quality", "{}", rules=lambda _: ())
    found = submit_model_payload(
        journal, case.ticket, "financials", case.payload, rules=lambda _: ("Rule: broken",)
    ).journal
    assert found.step_repairs[-1].issues == ("Rule: broken",)
    assert found.status == "pending"  # the step's repair within the attempt is kept


# --- settings ----------------------------------------------------------------------------------


def settings_file(tmp_path: Path, extra: str) -> Path:
    """The CLI tests' settings (no 8.0d entries; the project file has its own table) plus
    `extra` ahead of the candidates."""
    text = CLI_SETTINGS.format(key=tmp_path / "key.rtf")
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


def test_the_extracted_coverage_floor_is_read_as_a_decimal_string(tmp_path: Path) -> None:
    """Task 8.12 item 3: `extracted_coverage_min`, a Decimal string from 0 to 1 with at most
    four places, in the floor's table, alone or beside `min_statement_lines`; absent: off."""
    table = "[model_tests.completeness_floor]\n"
    alone = load_settings(
        settings_file(tmp_path / "a", table + 'extracted_coverage_min = "0.70"\n'), root=tmp_path
    )
    assert (alone.extracted_coverage_min, alone.completeness_floor) == (Decimal("0.70"), None)
    both = load_settings(
        settings_file(
            tmp_path / "b",
            table + 'min_statement_lines = 2\nextracted_coverage_min = "1"\n',
        ),
        root=tmp_path,
    )
    assert (both.extracted_coverage_min, both.completeness_floor) == (Decimal("1"), 2)
    assert ToolRules.from_settings(both) == ToolRules(floor=2, coverage_min=Decimal("1"))
    off = load_settings(settings_file(tmp_path / "c", ""), root=tmp_path)
    assert (off.extracted_coverage_min, off.completeness_floor) == (None, None)
    assert ToolRules.from_settings(off) == ToolRules()
    reason = "extracted_coverage_min must be a decimal string from 0 to 1"
    for number, (bad, why) in enumerate(
        [
            ('extracted_coverage_min = "abc"\n', reason),
            ('extracted_coverage_min = "-0.1"\n', reason),
            ('extracted_coverage_min = "1.5"\n', reason),
            ('extracted_coverage_min = "NaN"\n', reason),
            ('extracted_coverage_min = "0.12345"\n', reason),
            ("extracted_coverage_min = 0.7\n", reason),
            ('min_lines = 2\nextracted_coverage_min = "0.7"\n', "unknown key min_lines"),
            ("", "needs min_statement_lines or extracted_coverage_min"),
        ]
    ):
        with pytest.raises(SettingsError, match=why):
            load_settings(settings_file(tmp_path / f"bad{number}", table + bad), root=tmp_path)


def test_the_project_settings_plan_every_tool_step_at_medium_with_a_high_ceiling() -> None:
    """Task 8.9 item 4: a row per tool-loop step, each with its reason as a comment; Sol at
    medium (decision 0005, 24 Oct 2026) and one escalation to high at most. The floor stays
    off (user decision, 24 Oct 2026)."""
    path = Path("settings/project.toml")
    loaded = load_settings(path)
    assert loaded.tool_loop and loaded.completeness_floor is None
    assert loaded.extracted_coverage_min is None  # task 8.12: off (user decision "C")
    # Task 8.12 item 5: the suggested floor is the commented default; the floor stays off.
    text = path.read_text(encoding="utf-8")
    assert '\n# extracted_coverage_min = "0.50"\n' in text
    assert "\nextracted_coverage_min" not in text
    assert set(loaded.step_efforts) == tool_loop_steps()
    assert set(loaded.step_efforts.values()) == {StepEffort("medium", "high")}
    table = path.read_text(encoding="utf-8").split("[model_tests.step_effort]\n", 1)[1]
    rows = table.split("\n\n[", 1)[0].splitlines()
    for step in tool_loop_steps():
        (index,) = [n for n, line in enumerate(rows) if line.startswith(f"{step} = ")]
        assert rows[index - 1].startswith("# "), f"{step} has no reason above its row"


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


# --- extract_statements (task 8.10b, user decision "A" phase 2) ------------------------------

STATEMENT_PAGE = "\n".join(
    (
        "                       December 31,",
        "(In millions)          2025          2024",
        "CURRENT ASSETS:",
        "   Cash               $    887    $    866",
        "Accumulated deficit      (3,303)    (2,801)",
        "Revenue (1)        (1)        100        200",
        "Total 1,234 5,678        9,012        3,456",
    )
)
DECK_PAGE = "Deck revenue        1        2"


def statement_pack(store: Execution) -> PreparedPack:
    """The synthetic pack with S1's spans as pages 1-9 (page:2 a statement page), a second
    source `deck` holding a statement page too, and a missing (not ready) source `gone`."""
    pack = store.pack()
    source = pack.sources[0]
    spans = tuple(
        Span(locator=f"page:{n}", text=STATEMENT_PAGE if n == 2 else f"Page {n} revenue")
        for n in range(1, 10)
    )
    deck = source.model_copy(
        update={"source_id": "deck", "spans": (Span(locator="page:1", text=DECK_PAGE),)}
    )
    paged_source = source.model_copy(update={"spans": spans})
    gone = Source(source_id="gone", name="Missing filing", status="missing", limitation="absent")
    return pack.model_copy(update={"sources": (paged_source, deck, gone)})


def names(specs: tuple[dict[str, Any], ...]) -> list[str]:
    return [spec["function"]["name"] for spec in specs]


def test_only_financials_is_offered_extract_statements() -> None:
    assert extract_tool_steps() == {"financials"}
    assert names(tool_specs("financials")) == [
        "search_pack",
        "read_pages",
        EXTRACT,
        "submit_financials",
    ]
    for step in tool_sets():
        if step != "financials":
            assert EXTRACT not in names(tool_specs(step)), step
            assert EXTRACT not in names(tool_specs(step, PACK_TOOLS)), step
    assert names(tool_specs("financials", SUBMIT_ONLY)) == ["submit_financials"]
    (spec,) = (s for s in tool_specs("financials") if s["function"]["name"] == EXTRACT)
    parameters = spec["function"]["parameters"]
    assert parameters["required"] == ["source_id", "locators"]
    assert parameters["additionalProperties"] is False
    assert parameters["properties"]["locators"]["maxItems"] == MAX_PAGES_PER_EXTRACT == 8
    assert parameters["properties"]["locators"]["minItems"] == 1


def test_the_extract_tool_steps_quote_the_pack() -> None:
    cp1 = next(c for c in STEP_CHAINS if c.module_id == "CP-1")
    assert cp1.extract_tools == {"financials"}
    assert all(not c.extract_tools for c in STEP_CHAINS if c.module_id != "CP-1")
    with pytest.raises(ValueError, match="extracts statements in narrative, not one of its"):
        StepChain(**{**cp1.__dict__, "extract_tools": frozenset({"narrative"})})
    with pytest.raises(ValueError, match="extracts statements in nowhere, not one of its"):
        StepChain(**{**cp1.__dict__, "extract_tools": frozenset({"nowhere"})})
    assert extract_tool_steps((cp1,)) == {"financials"}


def test_extract_statements_renders_the_lines_as_delimited_source_data(case: Case) -> None:
    tools = PackTools(statement_pack(case.store), sources=("S1",))
    text = tools.extract_statements({"source_id": "S1", "locators": ["page:2", "page:3"]})
    digest = tools.ready["S1"].sha256
    assert text == (
        f"<<<SOURCE id=S1 sha256={digest}>>>\n"
        "locator=page:2 | statement lines extracted by Python from this page's text\n"
        "header:                        December 31,\n"
        "header: (In millions)          2025          2024\n"
        "line_no | label | caption | raw_values | flags\n"
        "4 | Cash | CURRENT ASSETS: | 887 866 | -\n"
        "5 | Accumulated deficit | CURRENT ASSETS: | (3,303) (2,801) | -\n"
        "6 | Revenue (1) | CURRENT ASSETS: | (1) 100 200 | more_values_than_header_years,"
        "label_ends_numeric\n"
        "7 | Total 1,234 5,678 | CURRENT ASSETS: | 9,012 3,456 | label_ends_numeric\n"
        "<<<END>>>\n"
        f"<<<SOURCE id=S1 sha256={digest}>>>\n"
        "locator=page:3 | statement lines extracted by Python from this page's text\n"
        "no statement lines extracted from this page\n"
        "<<<END>>>"
    )
    # A page extracted counts as read: the model saw its lines (the cited-page rule). It is
    # kept apart from the full reads (`read`), which telemetry's `pages_read` counts.
    assert tools.seen().read == {("S1", "page:2"), ("S1", "page:3")}
    assert tools.extracted == {("S1", "page:2"), ("S1", "page:3")} and tools.read == set()
    cited = json.dumps({"x": {"source_id": "S1", "locator": "page:2", "quote": "Cash"}})
    assert unread_citation_issues(cited, tools.seen()) == ()
    assert unread_citation_issues(cited, Seen()) == (f"{UNREAD_PAGE}: S1 page:2",)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({"source_id": "deck", "locators": ["page:1"]}, "deck is not one of the sources this"),
        # Review m6: declared, but not ready.
        ({"source_id": "gone", "locators": ["page:1"]}, "source gone is unavailable"),
        ({"source_id": "S9", "locators": ["page:1"]}, "unknown source_id 'S9'"),
        ({"source_id": "S1", "locators": ["page:99"]}, "page:99 is not a located span of S1"),
        ({"source_id": "S1", "locators": ["page:02"]}, "page:02 is not a located span of S1"),
        (
            {"source_id": "S1", "locators": [f"page:{n}" for n in range(1, 10)]},
            "at most 8 pages per call",
        ),
        ({"source_id": "S1", "locators": "page:2"}, "locators must be a list of page:N"),
        ({"source_id": "S1", "locators": {"page:2": 1}}, "locators must be a list of page:N"),
        ({"source_id": "S1", "locators": None}, "locators must be a list of page:N"),
        ({"source_id": "S1", "locators": []}, "locators must name at least one page"),
        ({"source_id": "S1", "locators": [2]}, "locators must be a list of page:N"),
        ({"source_id": "S1", "locators": ["sheet:x"]}, "locators must be a list of page:N"),
        ({"source_id": "S1", "locators": ["page:2", "page:2"]}, "locators repeat page:2"),
        ({"source_id": "S1"}, "missing"),
        ({"source_id": "S1", "locators": ["page:2"], "pages": 1}, "unexpected"),
    ],
)
def test_an_extract_call_outside_the_declared_sources_or_the_pack_is_refused(
    case: Case, raw: dict[str, Any], reason: str
) -> None:
    tools = PackTools(statement_pack(case.store), sources=("S1", "gone"))
    with pytest.raises(ToolError, match=reason):
        tools.extract_statements(raw)
    assert tools.seen() == Seen()  # a refused call records nothing


def test_extract_statements_needs_page_locators(case: Case) -> None:
    with pytest.raises(ToolError, match="has no page:N locators"):
        PackTools(case.store.pack()).extract_statements({"source_id": "S1", "locators": ["page:1"]})


def test_extract_reads_each_page_locator_as_written(case: Case) -> None:
    """Confidence review: `page:1` and `page:01` are distinct locators of one source (the
    contract forbids only a repeated locator); each is extracted from its own span."""
    pack = case.store.pack()
    spans = (Span(locator="page:1", text=DECK_PAGE), Span(locator="page:01", text=_ONE_ROW))
    source = pack.sources[0].model_copy(update={"spans": spans})
    tools = PackTools(pack.model_copy(update={"sources": (source,)}))
    for locator, raws in (("page:1", ["1", "2"]), ("page:01", ["3", "4"])):
        ((_, shown, rows),) = rendered(
            tools.extract_statements({"source_id": "S1", "locators": [locator]})
        )
        assert shown == locator and rows[0][1] == raws


_ONE_ROW = "Other revenue        3        4"


def test_the_financials_rules_add_the_extract_rule_verbatim(case: Case) -> None:
    """Task 8.10b item 3 (fix round 1, B1: the coordinator's wording, consistent with rules a
    and f): one added `financials` rule; no other step."""
    assert EXTRACT_RULE == (
        "Statement lines come from `extract_statements`: keep its labels verbatim and take "
        "each amount from the line's raw_values, written as rule a says, never retyped from "
        "memory or prose. You map `item_id`/`period_id`, choose `line_kind` and "
        "`sign_convention`, and cite the page. A value no extracted line holds keeps its rule "
        "f `item_id`, is read with `read_pages` and cited there, and carries a limitation "
        "saying it was not extracted. Verify a line the tool flags with `read_pages` before "
        "using it."
    )
    assert STEP_CONTRACTS["financials"].endswith(f"\nk. {EXTRACT_RULE}")
    assert [step for step, text in STEP_CONTRACTS.items() if EXTRACT_RULE in text] == ["financials"]
    system = build(
        "financials", case.store.pack(), (), STEPS["financials"].schema, submit_tool="x"
    )[0].content
    assert system.count(EXTRACT_RULE) == 1


# --- decision 0012 for 8.10b: property, differential, loop ----------------------------------

_BLOCK = re.compile(r"<<<SOURCE id=(\S+) sha256=\S+>>>\n(.*?)\n<<<END>>>", re.DOTALL)


def rendered(text: str) -> Iterator[tuple[str, str, list[tuple[int, list[str]]]]]:
    """(source_id, locator, [(line_no, raw_values)]) of each page `extract_statements` showed."""
    for match in _BLOCK.finditer(text):
        source_id, body = match.groups()
        first, *rows = body.split("\n")
        locator = first.removeprefix("locator=").split(" | ")[0]
        found = []
        for row in rows:
            cells = row.split(" | ")
            if len(cells) == 5 and cells[0].isdigit():
                found.append((int(cells[0]), cells[3].split(" ")))
        yield source_id, locator, found


_PAGE_TEXT = st.lists(
    st.one_of(_FILLER, _row(st.integers(2, 6)).map(lambda row: row[0])), max_size=12
).map("\n".join)


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    pages=st.lists(_PAGE_TEXT, min_size=1, max_size=4),
    declared=st.sets(st.sampled_from(("S1", "deck")), min_size=1),
    source=st.sampled_from(("S1", "deck", "S9")),
    asked=st.lists(st.integers(0, 6), max_size=10),
)
def test_extract_shows_only_printed_tokens_of_declared_sources(
    case: Case, pages: list[str], declared: set[str], source: str, asked: list[int]
) -> None:
    """Property (8.10b item 4): every raw_values token the tool renders is a substring of its
    page's text (of the very line it names), and every page it renders, and records as read, is
    a page of a declared source; anything else is a refused call that records nothing."""
    base = case.store.pack().sources[0]
    texts = {f"page:{n}": text for n, text in enumerate(pages, 1)}
    spans = tuple(Span(locator=locator, text=text) for locator, text in texts.items())
    sources = tuple(
        base.model_copy(update={"source_id": ident, "spans": spans}) for ident in ("S1", "deck")
    )
    pack = case.store.pack().model_copy(update={"sources": sources})
    tools = PackTools(pack, sources=tuple(sorted(declared)))
    raw = {"source_id": source, "locators": [f"page:{n}" for n in asked]}
    try:
        text = tools.extract_statements(raw)
    except ToolError:
        assert tools.seen() == Seen()
        return
    assert source in declared and asked
    shown = list(rendered(text))
    assert [(ident, locator) for ident, locator, _ in shown] == [
        (source, f"page:{n}") for n in asked
    ]
    for ident, locator, rows in shown:
        lines = texts[locator].split("\n")
        for line_no, raws in rows:
            assert all(token in texts[locator] for token in raws)
            assert all(token in lines[line_no - 1] for token in raws)
        table = extract_statement_lines(texts[locator], locator, source_id=ident)
        assert [(x.line_no, list(x.raw_values)) for x in table.lines] == rows
    assert tools.seen().read == {(source, f"page:{n}") for n in asked}
    assert {ident for ident, _ in tools.seen().read} <= declared


# A printed cash-flow page for the synthetic CP-1 case's six CFS lines (Q1-Q4 and FY 2025 in
# the case's book), added to S1 as `page:1`.
CFS_PAGE = "\n".join(
    (
        "                       Three Months Ended                               Year Ended",
        "                       March 31    June 30    September 30  December 31  December 31,",
        "(In millions)          2025        2025       2025          2025         2025",
        "CASH FLOWS:",
        "Synthetic profit       40          40         40            40           160",
        "Synthetic noncash      20          20         20            20           80",
        "Synthetic cfo          60          60         60            60           240",
        "Synthetic cfi          (10)        (10)       (10)          (10)         (40)",
        "Synthetic cff          (30)        (30)       (30)          (30)         (120)",
        "Synthetic ncf          20          20         20            20           80",
    )
)
COLUMNS = ("Q1", "Q2", "Q3", "Q4", "FY")  # the model's mapping of the page's columns
# The same six lines as a person would type them from the page (decision 0012's reference).
TYPED = {
    "profit": ("Synthetic profit", ("40", "40", "40", "40", "160")),
    "noncash": ("Synthetic noncash", ("20", "20", "20", "20", "80")),
    "cfo": ("Synthetic cfo", ("60", "60", "60", "60", "240")),
    "cfi": ("Synthetic cfi", ("-10", "-10", "-10", "-10", "-40")),
    "cff": ("Synthetic cff", ("-30", "-30", "-30", "-30", "-120")),
    "ncf": ("Synthetic ncf", ("20", "20", "20", "20", "80")),
}


@dataclass(frozen=True)
class PagedCase:
    store: Execution  # the synthetic CP-1 case with CFS_PAGE as S1 page:1, at financials
    ticket: str
    context: SourceContextReview
    payload: str  # its valid financials payload (no page citation)


@pytest.fixture(scope="module")
def paged_case(tmp_path_factory: pytest.TempPathFactory) -> PagedCase:
    freeze = source_context_tests.freeze

    def with_page(value: FinancialBook) -> tuple[PreparedPack, FinancialReview]:
        pack, review = freeze(value)
        source = pack.sources[0]
        spans = (*source.spans, Span(locator="page:1", text=CFS_PAGE))
        pack = pack.model_copy(update={"sources": (source.model_copy(update={"spans": spans}),)})
        return pack, review.model_copy(update={"pack_sha256": pack.content_hash()})

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(source_context_tests, "freeze", with_page)
        store, _, extraction = cp1_case(tmp_path_factory.mktemp("paged"))
    assert any(span.locator == "page:1" for span in store.pack().sources[0].spans)
    attempt = store.read().attempts[1]
    context = SourceContextReview.model_validate_json(
        store.payload(attempt.steps[0].payload_sha256)
    )
    payload = extraction.model_copy(
        update={"context_step_sha256": attempt.steps[0].content_hash()}
    ).model_dump_json()
    return PagedCase(store, attempt.ticket_id, context, payload)


def _cited(document: dict[str, Any], lines: dict[str, tuple[str, tuple[str, ...]]]) -> str:
    """`document` with the named CFS lines' label and per-period amounts replaced, each value
    citing page:1 with its label as the quote."""
    book = document["financial"]["books"][0]
    sha = next(
        c["source_sha256"] for line in book["statement_lines"] for c in line["value"]["citations"]
    )
    for line in book["statement_lines"]:
        if line["line_id"] not in lines:
            continue
        label, amounts = lines[line["line_id"]]
        line["label"] = label
        line["value"]["amount"] = amounts[COLUMNS.index(line["period_id"])]
        line["value"]["citations"] = [
            {"source_id": "S1", "source_sha256": sha, "locator": "page:1", "quote": label}
        ]
    return json.dumps(document)


def from_extracted(payload: str, tools: PackTools) -> str:
    """The payload built from `extract_statements`' lines: labels and amounts as extracted (the
    model's part is the line-id and column-to-period mapping)."""
    table = extract_statement_lines(CFS_PAGE, "page:1", source_id="S1")
    ids = {label: line_id for line_id, (label, _) in TYPED.items()}
    tools.extract_statements({"source_id": "S1", "locators": ["page:1"]})
    lines = {
        ids[line.label]: (line.label, tuple(str(value) for value in line.values))
        for line in table.lines
    }
    return _cited(json.loads(payload), lines)


def by_hand(payload: str) -> str:
    return _cited(json.loads(payload), TYPED)


def verdict(case: PagedCase, root: Path, payload: str, seen: Seen) -> tuple[str, tuple[str, ...]]:
    shutil.copytree(case.store.directory, root)
    journal = Execution(root)
    rules = ToolRules()
    found = submit_model_payload(
        journal,
        case.ticket,
        "financials",
        payload,
        rules=lambda text: rules.issues("financials", text, seen=seen, context=case.context),
    ).journal
    return journal_outcome(journal, "financials", found)


@pytest.mark.parametrize(
    "mutate",
    ["none", "unread", "swapped-columns", "wrong-quote"],
)
def test_extracted_and_typed_payloads_get_the_same_verdicts(
    tmp_path: Path, paged_case: PagedCase, mutate: str
) -> None:
    """Differential (8.10b item 4): the financials validators and the loop's rules judge a
    payload built from extracted lines exactly as the hand-typed payload of the same lines,
    under the same mutation of both."""
    tools = PackTools(paged_case.store.pack())
    extracted = from_extracted(paged_case.payload, tools)
    typed = by_hand(paged_case.payload)
    # The real claim (review m2): extraction reproduces the typed payload byte for byte, so the
    # verdicts below compare the extract-read path with the read_pages path.
    assert extracted == typed
    read = PackTools(paged_case.store.pack())
    read.read_pages({"source_id": "S1", "first_page": 1, "last_page": 1})
    assert tools.seen().read == read.seen().read == {("S1", "page:1")}
    # Both searched the pack once (the synthetic book's `missing` observations need it).
    seen_extracted = Seen(read=tools.seen().read, searched=(None,))
    seen_read = Seen(read=read.seen().read, searched=(None,))
    if mutate == "unread":
        seen_extracted = seen_read = Seen(searched=(None,))
    pairs = [extracted, typed]
    if mutate == "swapped-columns":
        pairs = [p.replace('"period_id": "Q1"', '"period_id": "QX"') for p in pairs]
        pairs = [p.replace('"period_id": "Q2"', '"period_id": "Q1"') for p in pairs]
        pairs = [p.replace('"period_id": "QX"', '"period_id": "Q2"') for p in pairs]
    if mutate == "wrong-quote":
        pairs = [p.replace('"quote": "Synthetic cfi"', '"quote": "Synthetic cfx"') for p in pairs]
    one = verdict(paged_case, tmp_path / "extracted", pairs[0], seen_extracted)
    two = verdict(paged_case, tmp_path / "typed", pairs[1], seen_read)
    assert one == two
    if mutate == "none":
        assert one == ("accepted", ())
    if mutate == "unread":
        assert one[0] == "rejected" and f"{UNREAD_PAGE}: S1 page:1" in one[1]
    if mutate == "wrong-quote":
        assert one[0] == "rejected"


def test_a_typed_amount_that_differs_from_the_extracted_one_changes_the_verdict(
    tmp_path: Path, paged_case: PagedCase
) -> None:
    """Review m2: the differential is not tautological. A retyping slip (FY cash from operations
    2400 for the printed 240) is judged differently from the extracted line: the extracted
    payload is accepted, the mistyped one rejected by the statement/account check."""
    tools = PackTools(paged_case.store.pack())
    extracted = from_extracted(paged_case.payload, tools)
    slip = {**TYPED, "cfo": ("Synthetic cfo", ("60", "60", "60", "60", "2400"))}
    typed = _cited(json.loads(paged_case.payload), slip)
    assert extracted != typed
    seen = Seen(read=tools.seen().read, searched=(None,))
    assert verdict(paged_case, tmp_path / "extracted", extracted, seen) == ("accepted", ())
    assert verdict(paged_case, tmp_path / "typed", typed, seen) == (
        "rejected",
        ("consolidated: Statement/account disagreement requires explicit conflict: cfo_ncfo FY",),
    )


def paged_rig(root: Path, case: PagedCase) -> Rig:
    shutil.copytree(case.store.directory, root / "journal")
    keys = root / "keys"
    keys.mkdir()
    return Rig(
        Execution(root / "journal"),
        case.ticket,
        Ledger(root / "artifacts" / ".ledgers" / "loop.jsonl", Decimal(5), provider="openrouter"),
        tool_pool(),
        AttemptWriter(root / "artifacts"),
        make_rtf_key(keys),
        case.payload,
        root,
    )


def _state(rig: Rig) -> list[tuple[str, str, tuple[str, ...]]]:
    attempt = next(a for a in rig.store.read().attempts if a.ticket_id == rig.ticket)
    return [(s.step_id, s.status, s.issues) for s in attempt.steps]


def test_the_financials_loop_extracts_then_submits_to_the_same_accepted_state(
    tmp_path: Path, paged_case: PagedCase
) -> None:
    """8.0d's scripted replies (search, then submit) and a model that searches, extracts the
    page and submits the payload built from its lines reach the same accepted state."""
    search = ("c-s", "search_pack", json.dumps({"query": "cash"}))
    extract = ("c-e", EXTRACT, json.dumps({"source_id": "S1", "locators": ["page:1"]}))
    built = from_extracted(paged_case.payload, PackTools(paged_case.store.pack()))
    runs = {
        "8.0d": [tool_reply(search), tool_reply(("c-1", "submit_financials", paged_case.payload))],
        "extract": [
            tool_reply(search),
            tool_reply(extract),
            tool_reply(("c-1", "submit_financials", built)),
        ],
    }
    states = {}
    for name, replies in runs.items():
        rig = paged_rig(tmp_path / name, paged_case)
        script = rig.script(*replies)
        result = rig.run(script, step_id="financials")
        assert (result.status, result.verdict) == ("accepted", "accepted"), name
        assert [s["outcome"] for s in result.submits] == ["accepted"]
        states[name] = _state(rig)
        bodies = script.bodies()
        assert all(
            [t["function"]["name"] for t in body["tools"]]
            == ["search_pack", "read_pages", EXTRACT, "submit_financials"]
            for body in bodies
        )
        if name == "extract":
            tool = bodies[2]["messages"][-1]
            assert tool["role"] == "tool" and tool["tool_call_id"] == "c-e"
            assert tool["content"] == PackTools(paged_case.store.pack()).extract_statements(
                json.loads(extract[2])
            )
        # Review m3: `pages_read` counts full `read_pages` reads only, as 8.0d defined it;
        # extracts are counted apart, and the cited-not-read list follows the rule's view.
        step = rig.metrics(result.attempt_id)["tool_loop"]["step"]
        expected = (0, 1) if name == "extract" else (0, 0)
        assert (step["pages_read"], step["pages_extracted"]) == expected, name
        # (It lists every cited locator not read, `metadata`-style ones included, as 8.0d did.)
        assert ["S1", "page:1"] not in step["final_payload_cited_not_read"], name
    assert (
        states["8.0d"]
        == states["extract"]
        == [
            ("source_context", "valid", ()),
            ("financials", "valid", ()),
        ]
    )


def test_a_pack_step_other_than_financials_is_refused_the_extract_tool(tmp_path: Path) -> None:
    """The loop runs `extract_statements` only for an `extract_tool_steps()` step: for any
    other pack-tool step it is an unknown tool, counted invalid and never run."""
    rig = step_rig(tmp_path, "business_context")
    extract = ("c-e", EXTRACT, json.dumps({"source_id": "S1", "locators": ["page:1"]}))
    script = rig.script(tool_reply(extract), tool_reply())
    result = rig.run(script, step_id="business_context", rules=ToolRules(checked=()))
    assert result.verdict != "accepted"
    tool = script.bodies()[1]["messages"][-1]
    assert tool["content"] == "error: unknown tool 'extract_statements'"
    step = rig.metrics(result.attempt_id)["tool_loop"]["step"]
    assert (step["pages_read"], step["pages_extracted"]) == (0, 0)


def test_a_submit_only_step_reports_no_pages_extracted(tmp_path: Path) -> None:
    """Review m3: like every reading field, `pages_extracted` is null on a submit-only step."""
    rig = step_rig(tmp_path, "quality")
    script = rig.script(tool_reply(("c-1", "submit_quality", rig.context)))
    result = rig.run(script, step_id="quality")
    step = rig.metrics(result.attempt_id)["tool_loop"]["step"]
    assert step["tool_set"] == SUBMIT_ONLY and step["pages_extracted"] is None


# --- extracted coverage (task 8.12, user decision "C") -----------------------------------------

CFS_FY = "CFS S1 scope FY (2025-01-01 to 2025-12-31)"
IS_FY = "IS S1 scope FY (2025-01-01 to 2025-12-31)"
CFS_TABLE = extract_statement_lines(CFS_PAGE, "page:1", source_id="S1")
FY_LINES = ("profit", "noncash", "cfo", "cfi", "cff", "ncf")


def built(case: PagedCase) -> dict[str, Any]:
    """The paged case's payload built from the extracted CFS page (every CFS line cites page:1
    with its label as the quote), as a document to edit."""
    document: dict[str, Any] = json.loads(
        from_extracted(case.payload, PackTools(case.store.pack()))
    )
    return document


def cfs_line(document: dict[str, Any], line_id: str, period_id: str) -> dict[str, Any]:
    line: dict[str, Any] = next(
        item
        for item in document["financial"]["books"][0]["statement_lines"]
        if (item["line_id"], item["period_id"]) == (line_id, period_id)
    )
    return line


def rename(line: dict[str, Any]) -> None:
    """The line keeps citing its page, with a label and quote that cover nothing there."""
    line["label"] = line["value"]["citations"][0]["quote"] = "Renamed"


def cell(measured: dict[str, Any] | None, key: str = CFS_FY) -> dict[str, Any]:
    assert measured is not None
    found: dict[str, Any] = measured["cells"][key]
    return found


def test_coverage_counts_each_cells_cited_statement_pages(paged_case: PagedCase) -> None:
    """Task 8.12 item 1: a cell's extracted lines are those of the pages its statement's lines
    cite; each is covered by a line of a period in the cell's scope citing that page."""
    payload = json.dumps(built(paged_case))
    measured = extracted_coverage(payload, paged_case.context, (CFS_TABLE,))
    assert measured is not None
    assert measured["cells"] == {
        IS_FY: {
            "extracted": 0,
            "covered": 0,
            "coverage": None,
            "reason": "no IS line of a book bound to issuer cites a page of S1",
            "pages": [],
        },
        CFS_FY: {
            "extracted": 6,
            "covered": 6,
            "coverage": "1.0000",
            "reason": None,
            "pages": ["page:1"],
        },
    }
    assert measured["overall"] == {
        "extracted": 6,
        "covered": 6,
        "coverage": "1.0000",
        "reason": None,
    }
    # The case's own payload cites no page: nothing is extracted for any cell.
    plain = extracted_coverage(paged_case.payload, paged_case.context, (CFS_TABLE,))
    assert plain is not None and plain["overall"] == {
        "extracted": 0,
        "covered": 0,
        "coverage": None,
        "reason": "no expected cell has extracted lines",
    }
    # A cited page without a table (not read or extracted), or a table without lines.
    unread = extracted_coverage(payload, paged_case.context, ())
    assert cell(unread)["reason"] == (
        "no page of S1 the CFS lines cite has an extracted table (read or extracted)"
    )
    empty = replace(CFS_TABLE, lines=())
    assert cell(extracted_coverage(payload, paged_case.context, (empty,)))["reason"] == (
        "the cited pages page:1 hold no extracted statement lines"
    )
    assert extracted_coverage("not json", paged_case.context, (CFS_TABLE,)) is None
    assert extracted_coverage("{}", paged_case.context, (CFS_TABLE,)) is None


def test_coverage_is_a_decimal_ratio_rounded_down_to_four_places(paged_case: PagedCase) -> None:
    document = built(paged_case)
    for line_id in ("cfo", "cfi", "cff"):  # three FY lines no longer cover theirs
        rename(cfs_line(document, line_id, "FY"))
    found = cell(extracted_coverage(json.dumps(document), paged_case.context, (CFS_TABLE,)))
    assert (found["extracted"], found["covered"], found["coverage"]) == (6, 3, "0.5000")
    rename(cfs_line(document, "ncf", "FY"))
    # 2 of 6 is 0.3333...: shown rounded down, so a shown coverage never passes a floor above it.
    found = cell(extracted_coverage(json.dumps(document), paged_case.context, (CFS_TABLE,)))
    assert (found["covered"], found["coverage"]) == (2, "0.3333")


def _covering(document: dict[str, Any], rule: str) -> dict[str, Any]:
    """Every FY CFS line renamed (covering nothing), then one changed by `rule`: so that it
    covers its extracted line by that rule alone, or so that it cannot."""
    for line_id in FY_LINES:
        rename(cfs_line(document, line_id, "FY"))
    line = cfs_line(document, "cfo" if rule == "near-number" else "cfi", "FY")
    citation = line["value"]["citations"][0]
    if rule == "quote":  # the quote holds the printed (40), the label differs
        line["label"], citation["quote"] = "Investing", "Synthetic cfi (40)"
    elif rule == "label":  # the label matches; the quote holds none of its values
        line["label"], citation["quote"] = "Synthetic  cfi", "Synthetic"
    elif rule == "near-number":  # 240 in 1,240 or 2400, 60 in 60.5 or (60): not cfo's values
        line["label"], citation["quote"] = "Operating", "1,240 and 2400 and 60.5 and (60)"
    elif rule == "wrong-statement":  # the label matches but the line is an IS line
        line["label"], line["statement"] = "Synthetic cfi", "IS"
    elif rule == "uncited-page":  # the label matches but the citation names another page
        line["label"], citation["locator"] = "Synthetic cfi", "page:2"
    # "wrong-period": the Q1-Q4 lines still cite page:1 with the printed labels.
    return document


@pytest.mark.parametrize(
    ("rule", "covered"),
    [
        ("quote", 1),
        ("label", 1),
        ("near-number", 0),
        ("wrong-statement", 0),
        ("wrong-period", 0),
        ("uncited-page", 0),
    ],
)
def test_each_covering_rule(paged_case: PagedCase, rule: str, covered: int) -> None:
    """A line is covered by a payload line of its statement, of a period in the cell's scope,
    citing its page with a quote holding one of its printed values (as a whole number) or with
    its label (whitespace normalised); a wrong statement, period or page never covers it."""
    document = _covering(built(paged_case), rule)
    page_two = replace(CFS_TABLE, locator="page:2", lines=())
    measured = extracted_coverage(json.dumps(document), paged_case.context, (CFS_TABLE, page_two))
    assert (cell(measured)["extracted"], cell(measured)["covered"]) == (6, covered)


def test_agreement_compares_each_cited_lines_amount_with_its_labels_values(
    paged_case: PagedCase,
) -> None:
    """Agreement (telemetry): a payload line on an extracted page agrees when its amount is one
    of the values of the extracted line of its label there; a retyped -100 for the printed
    (10) disagrees; a flipped sign is a sign difference (Python cannot tell it from a `signed`
    expense printed as a magnitude); a label the page does not print is unmatched."""
    document = built(paged_case)
    measured = extracted_coverage(json.dumps(document), paged_case.context, (CFS_TABLE,))
    assert measured is not None
    assert measured["agreement"] == {
        "agreed": 30,
        "sign_differs": 0,
        "disagreed": 0,
        "unmatched": 0,
        "not_on_an_extracted_page": 11,  # the BS and IS lines cite no page
        "without_amount": 0,
        "disagreements": [],
        "sign_differences": [],
    }
    cfs_line(document, "cfi", "Q1")["value"]["amount"] = -100
    cfs_line(document, "cff", "Q2")["value"]["amount"] = 30
    cfs_line(document, "ncf", "FY")["label"] = "Net change"
    measured = extracted_coverage(json.dumps(document), paged_case.context, (CFS_TABLE,))
    assert measured is not None
    agreement = measured["agreement"]
    counts = [agreement[k] for k in ("agreed", "sign_differs", "disagreed", "unmatched")]
    assert counts == [27, 1, 1, 1]
    assert agreement["disagreements"] == [
        {
            "pages": [["S1", "page:1"]],
            "line_id": "cfi",
            "period_id": "Q1",
            "label": "Synthetic cfi",
            "payload_value": "-100",
            "sign_convention": "signed",
            "extracted_values": [["-10", "-10", "-10", "-10", "-40"]],
        }
    ]
    assert agreement["sign_differences"] == [
        {
            "pages": [["S1", "page:1"]],
            "line_id": "cff",
            "period_id": "Q2",
            "label": "Synthetic cff",
            "payload_value": "30",
            "sign_convention": "signed",
            "extracted_values": [["-30", "-30", "-30", "-30", "-120"]],
        }
    ]


def test_a_payload_zero_agrees_with_a_printed_nil_dash(paged_case: PagedCase) -> None:
    dashed = CFS_PAGE.replace("Synthetic ncf          20", "Synthetic ncf          —")
    table = extract_statement_lines(dashed, "page:1", source_id="S1")
    document = built(paged_case)
    cfs_line(document, "ncf", "Q1")["value"]["amount"] = 0
    measured = extracted_coverage(json.dumps(document), paged_case.context, (table,))
    assert measured is not None
    assert (measured["agreement"]["agreed"], measured["agreement"]["disagreed"]) == (30, 0)
    cfs_line(document, "ncf", "Q1")["value"]["amount"] = 5  # not zero: no printed value holds it
    measured = extracted_coverage(json.dumps(document), paged_case.context, (table,))
    assert measured is not None
    assert (measured["agreement"]["agreed"], measured["agreement"]["disagreed"]) == (29, 1)


def test_a_nil_dash_is_never_quote_matched_and_a_nil_only_line_needs_its_label(
    paged_case: PagedCase,
) -> None:
    """Fix round 1 (review F4): a quote holding a printed dash covers no line by that dash, so a
    line printing only nil dashes is covered by its label alone; a line printing a dash beside
    numbers is still covered by a quote holding one of the numbers."""
    row = "Synthetic ncf          20          20         20            20           80"
    nil_only = "Synthetic ncf          —           —          —             —            —"
    assert row in CFS_PAGE
    table = extract_statement_lines(CFS_PAGE.replace(row, nil_only), "page:1", source_id="S1")
    ncf = next(line for line in table.lines if line.label == "Synthetic ncf")
    assert ncf.values == (None,) * 5 and ncf.raw_values == ("—",) * 5

    def covered(label: str, quote: str, page: ExtractedTable = table) -> int:
        document = built(paged_case)
        for line_id in FY_LINES:  # nothing else covers anything
            rename(cfs_line(document, line_id, "FY"))
        line = cfs_line(document, "ncf", "FY")
        line["label"], line["value"]["citations"][0]["quote"] = label, quote
        found = cell(extracted_coverage(json.dumps(document), paged_case.context, (page,)))
        assert found["extracted"] == 6
        count: int = found["covered"]
        return count

    assert covered("Net change", "Synthetic ncf — —") == 0  # the dash is not quoted
    assert covered("Net change", "—") == 0
    assert covered("Synthetic ncf", "x") == 1  # by its label alone
    mixed = CFS_PAGE.replace(
        row, row.replace("          20           80", "          —            83")
    )
    with_dash = extract_statement_lines(mixed, "page:1", source_id="S1")
    assert None in next(x for x in with_dash.lines if x.label == "Synthetic ncf").values
    assert covered("Net change", "—", with_dash) == 0
    assert covered("Net change", "ncf 83", with_dash) == 1  # 83: no other line prints it


def test_agreement_lists_the_first_five_disagreements(paged_case: PagedCase) -> None:
    document = built(paged_case)
    for period in ("Q1", "Q2", "Q3", "Q4", "FY"):
        for line_id in ("cfo", "cfi"):
            cfs_line(document, line_id, period)["value"]["amount"] = 7
    measured = extracted_coverage(json.dumps(document), paged_case.context, (CFS_TABLE,))
    assert measured is not None
    assert measured["agreement"]["disagreed"] == 10
    assert [(d["line_id"], d["period_id"]) for d in measured["agreement"]["disagreements"]] == [
        ("cfo", "Q1"),
        ("cfi", "Q1"),
        ("cfo", "Q2"),
        ("cfi", "Q2"),
        ("cfo", "Q3"),
    ]


def test_coverage_refuses_ambiguous_tables(paged_case: PagedCase) -> None:
    nameless = replace(CFS_TABLE, source_id=None)
    with pytest.raises(ValueError, match="names no source"):
        extracted_coverage(paged_case.payload, paged_case.context, (nameless,))
    with pytest.raises(ValueError, match="two extracted tables"):
        extracted_coverage(paged_case.payload, paged_case.context, (CFS_TABLE, CFS_TABLE))


def _states(document: dict[str, Any], states: list[str]) -> dict[str, Any]:
    """Each of the 30 CFS lines as `none` (a non-page citation), `cover` (page:1 with its
    label) or `miss` (page:1 with a label and quote that cover nothing)."""
    lines = [
        line
        for line in document["financial"]["books"][0]["statement_lines"]
        if line["statement"] == "CFS"
    ]
    assert len(lines) == len(states) == 30
    for line, state in zip(lines, states, strict=True):
        if state == "none":
            line["value"]["citations"][0]["locator"] = f"{line['line_id']}.{line['period_id']}"
        elif state == "miss":
            rename(line)
    return document


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    states=st.lists(st.sampled_from(("none", "cover", "miss")), min_size=30, max_size=30),
    flip=st.integers(0, 29),
    order=st.randoms(use_true_random=False),
)
def test_coverage_properties(
    paged_case: PagedCase, states: list[str], flip: int, order: random.Random
) -> None:
    """Properties (decision 0012): coverage is in [0, 1] and None iff nothing is extracted;
    unchanged by the order of the payload's lines and of the extracted lines; and never lower
    once a line is made to cover its extracted line while page:1 is already counted (a line
    citing a page not yet counted adds that page's lines, so it may lower the ratio)."""
    base = built(paged_case)
    payload = json.dumps(_states(json.loads(json.dumps(base)), states))
    measured = extracted_coverage(payload, paged_case.context, (CFS_TABLE,))
    assert measured is not None
    for found in [*measured["cells"].values(), measured["overall"]]:
        assert (found["coverage"] is None) == (found["extracted"] == 0)
        assert 0 <= found["covered"] <= found["extracted"]
        if found["coverage"] is not None:
            assert Decimal(0) <= Decimal(found["coverage"]) <= Decimal(1)
    shuffled = json.loads(payload)
    order.shuffle(shuffled["financial"]["books"][0]["statement_lines"])
    lines = list(CFS_TABLE.lines)
    order.shuffle(lines)
    again = extracted_coverage(
        json.dumps(shuffled), paged_case.context, (replace(CFS_TABLE, lines=tuple(lines)),)
    )
    assert again is not None
    assert (again["cells"], again["overall"]) == (measured["cells"], measured["overall"])
    agreement = {k: v for k, v in again["agreement"].items() if k != "disagreements"}
    assert agreement == {k: v for k, v in measured["agreement"].items() if k != "disagreements"}
    if all(state == "none" for state in states):
        assert cell(measured)["coverage"] is None
        return
    more = [*states[:flip], "cover", *states[flip + 1 :]]
    after = cell(
        extracted_coverage(
            json.dumps(_states(json.loads(json.dumps(base)), more)),
            paged_case.context,
            (CFS_TABLE,),
        )
    )
    before = cell(measured)
    assert after["extracted"] == before["extracted"] == 6
    assert after["covered"] >= before["covered"]
    assert Decimal(after["coverage"]) >= Decimal(before["coverage"])


def test_the_coverage_tables_are_the_shown_pages_of_the_financial_sources(case: Case) -> None:
    """Item 2: the loop extracts, per submit, only the page:N spans of the review's financial
    sources the model had been shown (read or extracted), in page order; never another page."""
    tools = PackTools(statement_pack(case.store))
    assert [s.source_id for s in case.context.sources if s.classification == "financial"] == ["S1"]
    seen = Seen(read=frozenset({("S1", "page:5"), ("S1", "page:2"), ("deck", "page:1")}))
    tables = seen_tables(tools, seen, case.context)
    assert [(t.source_id, t.locator, len(t.lines)) for t in tables] == [
        ("S1", "page:2", 4),
        ("S1", "page:5", 0),
    ]
    assert tables[0] == extract_statement_lines(STATEMENT_PAGE, "page:2", source_id="S1")
    assert seen_tables(tools, Seen(), case.context) == ()


def test_the_overall_reason_says_when_no_shown_page_holds_a_statement_line(
    paged_case: PagedCase,
) -> None:
    payload = json.dumps(built(paged_case))
    prose = replace(CFS_TABLE, lines=())
    measured = extracted_coverage(payload, paged_case.context, (prose,))
    assert measured is not None
    assert measured["overall"]["reason"] == "none of the 1 extracted pages holds a statement line"
    measured = extracted_coverage(payload, paged_case.context, ())
    assert measured is not None
    assert measured["overall"]["reason"] == "none of the 0 extracted pages holds a statement line"


def test_every_financials_submit_records_its_extracted_coverage(
    tmp_path: Path, paged_case: PagedCase
) -> None:
    """Item 2: next to `completeness`, every financials submit's record holds
    `extracted_coverage` of the retained (pre-filled) payload over the pages shown by then;
    the case's own payload cites no page (every cell None with its reason), the built one
    covers the extracted page; the verdicts are those without the field."""
    search = ("c-s", "search_pack", json.dumps({"query": "cash"}))
    extract = ("c-e", EXTRACT, json.dumps({"source_id": "S1", "locators": ["page:1"]}))
    built_payload = from_extracted(paged_case.payload, PackTools(paged_case.store.pack()))
    rig = paged_rig(tmp_path, paged_case)
    # The first submit (before the extract) cites page:1 unread: rejected by the cited-page rule.
    script = rig.script(
        tool_reply(search),
        tool_reply(("c-0", "submit_financials", built_payload)),
        tool_reply(extract),
        tool_reply(("c-1", "submit_financials", built_payload)),
    )
    result = rig.run(script, step_id="financials")
    assert [s["outcome"] for s in result.submits] == ["rejected", "accepted"]
    first, second = (s["extracted_coverage"] for s in result.submits)
    assert cell(first)["reason"] == (
        "no page of S1 the CFS lines cite has an extracted table (read or extracted)"
    )
    assert first["overall"]["reason"] == "none of the 0 extracted pages holds a statement line"
    assert cell(second) == {
        "extracted": 6,
        "covered": 6,
        "coverage": "1.0000",
        "reason": None,
        "pages": ["page:1"],
    }
    assert second["agreement"]["agreed"] == 30
    assert all(s["extracted_coverage_reason"] is None for s in result.submits)
    recorded = rig.metrics(result.attempt_id)["tool_loop"]["step"]["submits"]
    assert [s["extracted_coverage"] for s in recorded] == [first, second]
    assert all("completeness" in s for s in recorded)


def test_a_financials_submit_that_does_not_parse_records_no_coverage_with_the_reason(
    tmp_path: Path, paged_case: PagedCase
) -> None:
    rig = paged_rig(tmp_path, paged_case)
    script = rig.script(tool_reply(("c-1", "submit_financials", json.dumps({"financial": 1}))))
    result = rig.run(script, step_id="financials", rules=ToolRules(checked=()))
    (record, *_) = result.submits
    assert record["outcome"] == "rejected" and record["extracted_coverage"] is None
    assert record["extracted_coverage_reason"] == (
        "the retained payload does not parse as a financials submission (the stage validator "
        "rejects it)"
    )


def test_a_step_other_than_financials_records_no_coverage(tmp_path: Path) -> None:
    rig = step_rig(tmp_path, "business_context")
    script = rig.script(tool_reply(("c-1", "submit_business_context", "{}")))
    result = rig.run(script, step_id="business_context", rules=ToolRules(checked=()))
    (record, *_) = result.submits
    assert "extracted_coverage" not in record and "completeness" not in record


def _half(case: PagedCase) -> str:
    """The built payload with three FY CFS lines renamed: 3 of the 6 extracted lines covered."""
    document = built(case)
    for line_id in ("cfo", "cfi", "cff"):
        rename(cfs_line(document, line_id, "FY"))
    return json.dumps(document)


HALF_ISSUE = (
    f"{INCOMPLETE}: coverage 0.5000 of {CFS_FY} below the floor 0.70 (3 of 6 extracted lines "
    "covered)"
)


def test_the_coverage_floor_rejects_each_measured_cell_below_it(paged_case: PagedCase) -> None:
    """Item 3: with `coverage_min` set, a financials submit fails per cell whose coverage is
    below the floor (exactly: covered < floor x extracted); a cell with nothing extracted is
    not judged (the line-count floor judges a cell's lines); the old floor stays apart."""
    rules = ToolRules(coverage_min=Decimal("0.70"), checked=())
    assert rules.active("financials") and not rules.active("narrative")
    context, tables = paged_case.context, (CFS_TABLE,)

    def found(rule: ToolRules, payload: str) -> tuple[str, ...]:
        return rule.issues("financials", payload, seen=Seen(), context=context, tables=tables)

    assert found(rules, _half(paged_case)) == (HALF_ISSUE,)
    assert found(rules, json.dumps(built(paged_case))) == ()
    assert found(ToolRules(coverage_min=Decimal("0.5"), checked=()), _half(paged_case)) == ()
    assert found(rules, paged_case.payload) == ()  # every cell unmeasured: none judged
    assert found(rules, "not json") == ()
    both = ToolRules(floor=31, coverage_min=Decimal("0.70"), checked=())
    lines = completeness_issues(_half(paged_case), context, 31)
    assert len(lines) == 2 and found(both, _half(paged_case)) == (*lines, HALF_ISSUE)
    with pytest.raises(ValueError, match="needs the extracted tables"):
        rules.issues("financials", "{}", seen=Seen(), context=context)
    with pytest.raises(ValueError, match="retained source_context review"):
        rules.issues("financials", "{}", seen=Seen(), context=None, tables=tables)


@pytest.mark.parametrize(
    "bad", [Decimal("-0.01"), Decimal("1.0001"), Decimal("0.12345"), Decimal("NaN"), 0.7, "0.7"]
)
def test_the_coverage_floor_is_a_decimal_from_zero_to_one_of_four_places(bad: object) -> None:
    with pytest.raises(ValueError, match="extracted-coverage floor"):
        ToolRules(coverage_min=cast(Decimal, bad))


def test_the_rules_record_both_floors_and_why_each_is_off() -> None:
    unmeasured = (
        "a cell with no extracted lines is not judged by this floor (its reason is in "
        "extracted_coverage); min_statement_lines judges a cell's line count"
    )
    assert ToolRules(checked=()).to_record() == {
        "completeness_floor_lines": None,
        "completeness_floor_reason": "no [model_tests.completeness_floor] in settings",
        "extracted_coverage_min": None,
        "extracted_coverage_min_reason": (
            "no [model_tests.completeness_floor] extracted_coverage_min in settings"
        ),
        "extracted_coverage_unmeasured": unmeasured,
        "checked": [],
    }
    record = ToolRules(coverage_min=Decimal("0.70"), checked=()).to_record()
    assert (record["extracted_coverage_min"], record["extracted_coverage_min_reason"]) == (
        "0.70",
        None,
    )


def test_a_loop_submit_below_the_coverage_floor_is_rejected_and_escalates(
    tmp_path: Path, paged_case: PagedCase
) -> None:
    """The loop judges the floor on the pages shown by the submit (scratch and live journal
    alike: the live journal's judgement of the last submit must equal the scratch one), and a
    coverage rejection is a completeness-floor rejection for escalation. (`_half`'s renamed
    labels fail the stage too; the floor alone rejecting an accepted payload is the recorded
    transcripts' differential.)"""
    search = ("c-s", "search_pack", json.dumps({"query": "cash"}))
    extract = ("c-e", EXTRACT, json.dumps({"source_id": "S1", "locators": ["page:1"]}))
    rig = paged_rig(tmp_path, paged_case)
    script = rig.script(
        tool_reply(search, extract),
        tool_reply(("c-1", "submit_financials", _half(paged_case))),
        tool_reply(("c-2", "submit_financials", json.dumps(built(paged_case)))),
    )
    rules = ToolRules(coverage_min=Decimal("0.70"))
    result = rig.run(script, step_id="financials", rules=rules)
    assert [s["outcome"] for s in result.submits] == ["rejected", "accepted"]
    assert result.submits[0]["issues"][-1] == HALF_ISSUE
    assert not any(i.startswith(INCOMPLETE) for i in result.submits[0]["issues"][:-1])
    assert result.submits[0]["completeness_floor_failed"] is True
    events = (rig.directory(result.submits[0]["attempt_id"]) / "events.jsonl").read_text()
    assert '"reason": "a completeness-floor rejection"' in events
    step = rig.metrics(result.attempt_id)["tool_loop"]["step"]
    assert step["rules"]["extracted_coverage_min"] == "0.70"


# --- task 8.11 (user decision "B"): the financials submit in parts ------------------------------

# The brief's table: what each part holds of a `FinancialBook` (`book_id` names the book in each).
# `statement_lines` and `statement_identities` are split by statement over IS, CFS and BS.
PART_TABLE = {
    "frame": {
        "entity_perimeter",
        "accounting_basis",
        "currency",
        "unit",
        "periods",
        "statement_disclosures",
        "addback_disclosure",
        "segment_disclosure",
    },
    "IS": {"statement_lines", "statement_identities"},
    "CFS": {"statement_lines", "statement_identities", "cash_movement_bridges"},
    "BS": {
        "statement_lines",
        "statement_identities",
        "balance_movements",
        "balance_movement_bridges",
    },
    "other": {
        "accounts",
        "addbacks",
        "segments",
        "kpis",
        "facilities",
        "facility_fx_conversions",
        "pro_forma",
        "audit_basis_explanations",
        "segment_allocation",
        "limitations",
    },
}
SPLIT_BY_STATEMENT = {"statement_lines", "statement_identities"}
STATEMENTS = ("IS", "CFS", "BS")


def test_every_book_field_belongs_to_exactly_one_part() -> None:
    """Pin (item 1): the parts' book fields are the brief's table; every `FinancialBook` field
    but `book_id` is in exactly one part, the two statement registers in IS, CFS and BS split
    by statement; the frame holds every top-level field of the submission and the review."""
    assert PART_KINDS == ("frame", "IS", "CFS", "BS", "other")
    assert {kind: set(fields) for kind, fields in BOOK_PARTS.items()} == PART_TABLE
    owners: dict[str, set[str]] = {}
    for kind, fields in PART_TABLE.items():
        for name in fields:
            owners.setdefault(name, set()).add(kind)
    assert set(owners) == set(FinancialBook.model_fields) - {"book_id"}
    for name, kinds in owners.items():
        assert kinds == set(STATEMENTS) if name in SPLIT_BY_STATEMENT else len(kinds) == 1, name
    frame = partial_schema("frame")
    assert list(frame.model_fields) == list(FinancialSubmission.model_fields)
    review = frame.model_fields["financial"].annotation
    assert isinstance(review, type) and issubclass(review, BaseModel)
    assert list(review.model_fields) == list(FinancialReview.model_fields)
    for kind in (*STATEMENTS, "other"):
        assert list(partial_schema(kind).model_fields) == ["books"]


def _book_model(kind: str) -> type[BaseModel]:
    model = partial_schema(kind)
    holder = model.model_fields["financial"].annotation if kind == "frame" else model
    assert isinstance(holder, type) and issubclass(holder, BaseModel)
    book = get_args(holder.model_fields["books"].annotation)[0]
    assert isinstance(book, type) and issubclass(book, BaseModel)
    return book


@pytest.mark.parametrize("kind", ["frame", "IS", "CFS", "BS", "other"])
def test_each_partial_schema_is_the_contracts_own_fields(kind: str) -> None:
    """Nothing retyped: each part's fields have the stored contract's own JSON schema (types,
    bounds, defaults, markers), and its `books` keep `FinancialReview.books`' bounds."""
    full = FinancialBook.model_json_schema()["properties"]
    book = _book_model(kind)
    assert list(book.model_fields) == [
        name for name in FinancialBook.model_fields if name == "book_id" or name in PART_TABLE[kind]
    ]
    own = book.model_json_schema()["properties"]
    assert own == {name: full[name] for name in own}
    holder: type[BaseModel] = partial_schema(kind)
    if kind == "frame":
        top = FinancialSubmission.model_json_schema()["properties"]
        mine = holder.model_json_schema()["properties"]
        assert {k: v for k, v in mine.items() if k != "financial"} == {
            k: v for k, v in top.items() if k != "financial"
        }
        holder = cast(type[BaseModel], holder.model_fields["financial"].annotation)
        review = FinancialReview.model_json_schema()["properties"]
        mine = holder.model_json_schema()["properties"]
        assert {k: v for k, v in mine.items() if k != "books"} == {
            k: v for k, v in review.items() if k != "books"
        }
    books = holder.model_json_schema()["properties"]["books"]
    wanted = FinancialReview.model_json_schema()["properties"]["books"]
    assert {k: v for k, v in books.items() if k != "items"} == {
        k: v for k, v in wanted.items() if k != "items"
    }


def split(payload: str) -> dict[str, str]:
    """The five parts of a one-shot payload (the property's reference, apart from the code under
    test): the frame is every field but each book's part fields, a statement line goes to its
    statement's part and an identity to its target line's (same `line_id` and `period_id`)."""
    document = json_object(payload)
    assert document is not None
    financial = document["financial"]
    frame = {key: value for key, value in document.items() if key != "financial"}
    frame["financial"] = {key: value for key, value in financial.items() if key != "books"}
    frame["financial"]["books"] = [
        {
            key: value
            for key, value in book.items()
            if key == "book_id" or key in PART_TABLE["frame"]
        }
        for book in financial["books"]
    ]
    parts = {"frame": frame}
    for kind in (*STATEMENTS, "other"):
        books = []
        for book in financial["books"]:
            row = {
                key: value
                for key, value in book.items()
                if key in PART_TABLE[kind] - SPLIT_BY_STATEMENT
            }
            if kind in STATEMENTS:
                lines = [x for x in book.get("statement_lines", []) if x["statement"] == kind]
                keys = {(x["line_id"], x["period_id"]) for x in lines}
                row["statement_lines"] = lines
                row["statement_identities"] = [
                    x
                    for x in book.get("statement_identities", [])
                    if (x["target_line_id"], x["period_id"]) in keys
                ]
            books.append({"book_id": book["book_id"], **row})
        parts[kind] = {"books": books}
    return {kind: exact_json(part) for kind, part in parts.items()}


def grouped(payload: str) -> dict[str, Any]:
    """`payload` with each book's statement lines grouped IS, CFS, BS and its identities by their
    target line's statement, each group in payload order (the order Python assembles)."""
    document = json_object(payload)
    assert document is not None
    for book in document["financial"]["books"]:
        lines = book.get("statement_lines", [])
        of = {(x["line_id"], x["period_id"]): x["statement"] for x in lines}
        book["statement_lines"] = sorted(lines, key=lambda x: STATEMENTS.index(x["statement"]))
        identities = book.get("statement_identities", [])
        book["statement_identities"] = sorted(
            identities,
            key=lambda x: STATEMENTS.index(of[(x["target_line_id"], x["period_id"])]),
        )
    return document


@st.composite
def submissions(draw: st.DrawFn, base: str) -> str:
    """A `FinancialSubmission` generated from `base` (the synthetic case's): its statement lines
    reordered, thinned and moved between statements (one statement per line id), identities kept
    for the lines left, some other registers emptied, and sometimes a second book."""
    document = json_object(base)
    assert document is not None
    book = document["financial"]["books"][0]
    lines = draw(st.permutations(book["statement_lines"]))
    kept = [line for line in lines if draw(st.booleans()) or draw(st.booleans())]
    statements = {
        line_id: draw(st.sampled_from(STATEMENTS))
        for line_id in sorted({line["line_id"] for line in kept})
    }
    book["statement_lines"] = [{**line, "statement": statements[line["line_id"]]} for line in kept]
    keys = {(line["line_id"], line["period_id"]) for line in kept}
    book["statement_identities"] = [
        x
        for x in draw(st.permutations(book["statement_identities"]))
        if (x["target_line_id"], x["period_id"]) in keys and draw(st.booleans())
    ]
    for name in ("accounts", "facilities", "balance_movement_bridges", "statement_disclosures"):
        if draw(st.booleans()):
            book[name] = []
    if draw(st.booleans()):
        second = json_object(exact_json(book))
        assert second is not None
        document["financial"]["books"].append({**second, "book_id": "second"})
    payload = exact_json(document)
    FinancialSubmission.model_validate_json(payload)  # a contract-valid submission
    return payload


def held_parts(parts: dict[str, str], order: Sequence[str]) -> Parts:
    held = Parts()
    for kind in order:
        assert held.submit(kind, parts[kind]) == (), kind
    return held


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(data=st.data(), order=st.permutations(["frame", "IS", "CFS", "BS", "other"]))
def test_split_then_assemble_round_trips_in_any_order_of_arrival(
    case: Case, data: st.DataObject, order: list[str]
) -> None:
    """Property (item 1, decision 0012): for a generated submission, its parts accepted in any
    order assemble to the one-shot payload of the same objects byte for byte (Python's order:
    contract field order, statement lines IS, CFS, BS), which parses to the same model; a part
    re-sent replaces the earlier one of its kind."""
    payload = data.draw(submissions(case.payload))
    parts = split(payload)
    assembled = assemble(held_parts(parts, order))
    expected = grouped(payload)
    assert assembled == exact_json(expected)
    assert FinancialSubmission.model_validate_json(assembled) == (
        FinancialSubmission.model_validate_json(exact_json(expected))
    )
    # Replace semantics: an earlier part of each kind (another generated submission's) is
    # replaced by the later one, whatever the order.
    other = split(data.draw(submissions(case.payload)))
    held = held_parts(other, order)
    for kind in order:
        assert held.submit(kind, parts[kind]) == ()
    assert assemble(held) == assembled


def test_a_one_shot_payload_in_contract_order_assembles_byte_for_byte(case: Case) -> None:
    """The synthetic case's payload, whose lines interleave BS, IS and CFS per period, assembles
    to its own bytes once its lines are grouped; grouped as Python groups them, it is already
    canonical (assembling it again changes nothing)."""
    assembled = assemble(held_parts(split(case.payload), PART_KINDS))
    assert assembled == exact_json(grouped(case.payload))
    assert assembled != exact_json(json_object(case.payload))  # the interleave is regrouped
    assert assemble(held_parts(split(assembled), PART_KINDS)) == assembled


def _part(kind: str, payload: str) -> dict[str, Any]:
    document = json_object(split(payload)[kind])
    assert document is not None
    return document


def test_a_part_is_checked_on_arrival_against_its_partial_schema(case: Case) -> None:
    """A part answers its own shape issues (in the stored contract's wording) and the checks a
    split needs: each line in its statement's part, each identity with its target line, each
    book once. A field Python fills (a hash, a scope dimension) is never asked for."""
    frame = _part("frame", case.payload)
    for book in frame["financial"]["books"]:
        for name in ("currency", "unit", "accounting_basis", "entity_perimeter"):
            del book[name]
            for period in book["periods"]:
                del period[name]
    del frame["context_step_sha256"]
    del frame["binding"]["financial_review_sha256"]
    for period in frame["financial"]["books"][0]["periods"]:
        for citation in period["citations"]:
            del citation["source_sha256"]
    assert check_part("frame", exact_json(frame)) == ()
    frame["financial"]["run_id"] = 7
    frame["surplus"] = 1
    assert check_part("frame", exact_json(frame)) == (
        "surplus: Extra inputs are not permitted",
        "financial.run_id: Input should be a valid string",
    )
    cfs = _part("CFS", case.payload)
    book = cfs["books"][0]
    assert check_part("CFS", exact_json(cfs)) == ()
    assert check_part("IS", exact_json(cfs))[0] == (
        "books.0.cash_movement_bridges: Extra inputs are not permitted"
    )
    del book["cash_movement_bridges"]
    first = book["statement_lines"][0]
    assert check_part("IS", exact_json(cfs))[0] == (
        f"books.0.statement_lines.0.statement: a CFS line ({first['line_id']} "
        f"{first['period_id']}) in the IS part; send it in the CFS part"
    )
    target = book["statement_identities"][0]
    book["statement_lines"] = [
        x
        for x in book["statement_lines"]
        if (x["line_id"], x["period_id"]) != (target["target_line_id"], target["period_id"])
    ]
    assert check_part("CFS", exact_json(cfs)) == (
        f"books.0.statement_identities.0.target_line_id: {target['target_line_id']} "
        f"{target['period_id']} is not a line of book consolidated in this CFS part",
    )
    twice = {"books": [_part("IS", case.payload)["books"][0]] * 2}
    assert check_part("IS", exact_json(twice)) == (
        "books.1.book_id: consolidated repeats books.0; a part holds each book once",
    )
    assert check_part("other", "[1]") == ("(root): Input should be an object",)
    assert check_part("BS", '{"books": []}') == (
        "books: Tuple should have at least 1 item after validation, not 0",
    )
    with pytest.raises(ValueError, match="unknown part"):
        check_part("KPI", "{}")


def test_a_rejected_part_changes_nothing_held_and_a_resent_one_replaces_it(case: Case) -> None:
    parts = split(case.payload)
    held = held_parts(parts, ["frame", "IS"])
    wrong = _part("CFS", case.payload)
    assert held.submit("IS", exact_json(wrong)) != ()
    assert held.held["IS"] == json_object(parts["IS"])
    fewer = _part("IS", case.payload)
    fewer["books"][0]["statement_lines"] = fewer["books"][0]["statement_lines"][:2]
    fewer["books"][0]["statement_identities"] = []
    assert held.submit("IS", exact_json(fewer)) == ()
    assert held.held["IS"] == fewer
    assert held.listing() == (
        "parts held: frame (11 entries), IS (2 lines); parts not sent: CFS, BS, other"
    )


def test_a_part_with_a_null_for_a_defaulted_field_is_held_with_the_default(case: Case) -> None:
    """The sent schema makes a defaulted field nullable (`live.schema`); the part is held
    null-resolved against its own schema, as `normalise` resolves a one-shot payload."""
    bs = _part("BS", case.payload)
    bs["books"][0]["balance_movements"] = None
    held = Parts()
    assert held.submit("BS", exact_json(bs)) == ()
    assert held.held["BS"]["books"][0]["balance_movements"] == []


def contract_issues(document: dict[str, Any]) -> tuple[str, ...]:
    """The stored contract's own shape issues of an assembled payload."""
    try:
        FinancialSubmission.model_validate_json(exact_json(document))
    except ValidationError as error:
        return shape_issues(error)
    return ()


def test_missing_parts_contribute_nothing_and_no_value_is_invented(case: Case) -> None:
    """An assembly holds what was sent: an absent part's fields are absent (the contract's own
    default, or its "Field required"), never filled; with nothing sent it is `{}`."""
    parts = split(case.payload)
    assert assemble(Parts()) == "{}"
    only = json_object(assemble(held_parts(parts, ["IS"])))
    assert only is not None
    assert list(only) == ["financial"] and list(only["financial"]) == ["books"]
    (book,) = only["financial"]["books"]
    assert list(book) == ["book_id", "statement_lines", "statement_identities"]
    assert {x["statement"] for x in book["statement_lines"]} == {"IS"}
    no_other = json_object(assemble(held_parts(parts, ["frame", "IS", "CFS", "BS"])))
    assert no_other is not None
    (book,) = no_other["financial"]["books"]
    assert not set(book) & PART_TABLE["other"]
    issues = contract_issues(no_other)
    assert "financial.books.0.accounts: Field required" in issues
    assert "financial.books.0.segment_allocation: Field required" in issues


def test_the_part_submit_steps_are_financials_and_quote_the_pack() -> None:
    cp1 = next(chain for chain in STEP_CHAINS if chain.module_id == "CP-1")
    assert part_submit_steps() == cp1.part_submits == {"financials"}
    assert all(not chain.part_submits for chain in STEP_CHAINS if chain.module_id != "CP-1")
    with pytest.raises(ValueError, match="submits narrative in parts, not one of its steps"):
        StepChain(**{**cp1.__dict__, "part_submits": frozenset({"narrative"})})
