"""Task 8.6: CP-2, CP-4, CP-3 and CP-5 registered in the live runner's shared tables; task 8.7
appends CP-6 (`committee_challenge`) the same way.

SYNTHETIC journals and submissions come from each module's own tests (imported as modules, so
none of their tests or fixtures is collected twice). No live call: every dispatch below goes to
a `FakeTransport`.
"""

import hashlib
import json
import re
from collections.abc import Callable
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from pydantic import BaseModel

from deploy_vii import (
    cp2_synthesis,
    cp3_relative_value,
    cp4_legal,
    cp5_integrity,
    cp6_committee,
    registry,
)
from deploy_vii.contracts import Module
from deploy_vii.execution import Attempt, Execution
from deploy_vii.live import cli, context, prompts, runner, submission
from deploy_vii.live.client import ChatClient
from deploy_vii.live.ledger import Ledger
from deploy_vii.live.retention import AttemptWriter
from deploy_vii.live.runner import StepSpec
from deploy_vii.live.schema import schema_relaxations, strict_schema
from deploy_vii.registry import StepChain
from tests.product import test_cp2_synthesis as cp2_tests
from tests.product import test_cp3_relative_value as cp3_tests
from tests.product import test_cp4_legal as cp4_tests
from tests.product import test_cp5_integrity as cp5_tests
from tests.product import test_cp6_committee as cp6_tests
from tests.product.live_support import FakeTransport, fixture_pool, make_rtf_key
from tests.product.test_business_context import submission_fixture as cp1a_submission
from tests.product.test_execution import accept_cp0, fixture_store
from tests.product.test_live_runner import NOW, Rig, reply
from tests.product.test_readiness import as_submission, readiness_fixture

CP1_ROUTE = (
    "source_readiness",
    "source_context",
    "financials",
    "narrative",
    "readiness",
    "quality",
)
NEW_CHAINS = (
    StepChain(module_id="CP-2", cell="cp2", steps=("credit_synthesis",)),
    StepChain(
        module_id="CP-4",
        cell="cp4",
        steps=("legal_covenants",),
        pack_sources=frozenset({"legal_covenants"}),
    ),
    StepChain(
        module_id="CP-3",
        cell="cp3",
        steps=("relative_value",),
        pack_sources=frozenset({"relative_value"}),
    ),
    StepChain(module_id="CP-5", cell="cp5", steps=("integrity_review",)),
    # Task 8.7: CP-6 quotes nothing (no pack sources).
    StepChain(module_id="CP-6", cell="cp6", steps=("committee_challenge",)),
)
ROUTES = {
    "CP-2": (*CP1_ROUTE, "business_context", "credit_synthesis"),
    "CP-4": (*CP1_ROUTE, "legal_covenants"),
    "CP-3": (*CP1_ROUTE, "business_context", "credit_synthesis", "relative_value"),
    "CP-5": ("source_readiness", "integrity_review"),
    # Task 8.7: CP-0, the CP-1 chain, CP-1A (CP-2's required producer), CP-2, CP-3, CP-5.
    "CP-6": (
        *CP1_ROUTE,
        "business_context",
        "credit_synthesis",
        "relative_value",
        "integrity_review",
        "committee_challenge",
    ),
}
SCHEMAS: dict[str, tuple[str, type[BaseModel]]] = {
    "credit_synthesis": ("CP-2", cp2_synthesis.CreditSynthesisSubmission),
    "legal_covenants": ("CP-4", cp4_legal.CovenantInterpretationSubmission),
    "relative_value": ("CP-3", cp3_relative_value.RelativeValueSubmission),
    "integrity_review": ("CP-5", cp5_integrity.IntegritySubmission),
    "committee_challenge": ("CP-6", cp6_committee.CommitteeSubmission),
}
CONTEXT_STEPS = ("credit_synthesis", "legal_covenants", "relative_value", "committee_challenge")


# --- the registry --------------------------------------------------------------------------


def test_the_new_chains_follow_cp1a_in_the_brief_order() -> None:
    assert registry.STEP_CHAINS[3:] == NEW_CHAINS
    assert [c.module_id for c in registry.STEP_CHAINS[:3]] == ["CP-0", "CP-1", "CP-1A"]
    # The modules' own step sequences are the registry's.
    assert cp2_synthesis.CP2_STEPS == registry.step_chain("CP-2").steps
    assert cp4_legal.CP4_STEPS == registry.step_chain("CP-4").steps
    assert cp3_relative_value.CP3_STEPS == registry.step_chain("CP-3").steps
    assert cp5_integrity.CP5_STEPS == registry.step_chain("CP-5").steps
    assert cp6_committee.CP6_STEPS == registry.step_chain("CP-6").steps


@pytest.mark.parametrize("module_id", sorted(ROUTES))
def test_each_route_runs_the_required_producers_then_the_step(module_id: str) -> None:
    assert registry.module_route(module_id) == ROUTES[module_id]
    (cell,) = cli._module_cells(module_id, 7)
    assert cell.steps == ROUTES[module_id] and cell.case_id == module_id.lower()


def test_the_regression_cases_gain_the_new_cells_after_the_base_three() -> None:
    cases = registry.regression_cases()
    assert [cell for cell, _ in cases] == ["cp0", "cp1", "cp1a", "cp2", "cp4", "cp3", "cp5", "cp6"]
    assert dict(cases[3:]) == {chain.cell: ROUTES[chain.module_id] for chain in NEW_CHAINS}
    assert cli.REGRESSION_CASES == cases


def test_only_the_quoting_steps_are_sent_pack_sources_and_each_step_settles() -> None:
    steps = registry.pack_source_steps()
    assert {"legal_covenants", "relative_value"} <= steps
    assert not {"credit_synthesis", "integrity_review", "committee_challenge"} & steps
    assert context.PACK_SOURCE_STEPS == steps
    assert set(SCHEMAS) <= registry.settling_steps() == runner.SETTLING_STEPS
    assert registry.projections() == registry.projections(registry.STEP_CHAINS[:3])
    assert set(SCHEMAS) <= registry.tool_loop_steps()  # task 8.9: every step is a tool loop


# --- schemas and dispatch -------------------------------------------------------------------


def test_each_step_has_its_modules_thin_submission_as_schema() -> None:
    for step_id, (module_id, schema) in SCHEMAS.items():
        assert submission.STEPS[step_id] == submission.StepDef(module_id, schema)
    assert list(submission.STEPS)[-5:] == list(SCHEMAS)


def _objects(node: object) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        found = [node] if node.get("type") == "object" else []
        return found + [o for value in node.values() for o in _objects(value)]
    if isinstance(node, list):
        return [o for value in node for o in _objects(value)]
    return []


@pytest.mark.parametrize("step_id", sorted(SCHEMAS))
def test_the_sent_schema_is_strict(step_id: str) -> None:
    schema = SCHEMAS[step_id][1]
    sent = strict_schema(schema)
    assert schema_relaxations(schema) == []  # strict as Pydantic writes it: nothing relaxed
    assert sent == schema.model_json_schema()
    for node in _objects(sent):
        assert node.get("additionalProperties") is False, node
        assert sorted(node.get("required", ())) == sorted(node.get("properties", {})), node


def test_the_sent_schema_keeps_cp5s_two_claim_contradiction_minimum() -> None:
    sent = strict_schema(cp5_integrity.IntegritySubmission)
    refs = sent["$defs"]["Contradiction"]["properties"]["claim_refs"]
    assert refs["minItems"] == 2 and refs["items"] == {"$ref": "#/$defs/ClaimRef"}


def test_the_sent_schema_keeps_cp6s_one_challenge_minimum() -> None:
    sent = strict_schema(cp6_committee.CommitteeSubmission)
    challenges = sent["properties"]["thesis_challenges"]
    assert challenges["minItems"] == 1 and challenges["items"] == {
        "$ref": "#/$defs/ThesisChallenge"
    }


def test_each_one_step_module_has_its_own_journal_entry() -> None:
    assert dict(submission.MODULE_STEP_ENTRIES) == {
        "CP-1A": submission.submit_cp1a_step,
        "CP-2": cp2_synthesis.submit_cp2_step,
        "CP-4": cp4_legal.submit_cp4_step,
        "CP-3": cp3_relative_value.submit_cp3_step,
        "CP-5": cp5_integrity.submit_cp5_step,
        "CP-6": cp6_committee.submit_cp6_step,
    }


def cp2_case(tmp_path: Path) -> tuple[Execution, str]:
    return cp2_tests.journal(tmp_path), cp2_tests.synthesis().model_dump_json()


def cp4_case(tmp_path: Path) -> tuple[Execution, str]:
    return cp4_tests.journal(tmp_path), cp4_tests.submission_fixture().model_dump_json()


def cp3_case(tmp_path: Path) -> tuple[Execution, str]:
    return cp3_tests.journal(tmp_path), cp3_tests.valuation().model_dump_json()


def cp5_case(tmp_path: Path) -> tuple[Execution, str]:
    """The review is built over a twin journal's scope (the same heads, so the same claims and
    refs), leaving the returned journal's first CP-5 attempt unspent."""
    twin = cp5_tests.journal(tmp_path / "twin")
    scope = cp5_integrity.review_scope(twin, twin.begin("CP-5"))
    return cp5_tests.journal(tmp_path / "store"), cp5_tests.review_all(scope).model_dump_json()


def cp6_case(tmp_path: Path) -> tuple[Execution, str]:
    """CP-0 to CP-5 settled by their own step functions over the CP-3 market pack."""
    return cp6_tests.full_journal(tmp_path), cp6_tests.committee().model_dump_json()


CASES: dict[str, Callable[[Path], tuple[Execution, str]]] = {
    "credit_synthesis": cp2_case,
    "legal_covenants": cp4_case,
    "relative_value": cp3_case,
    "integrity_review": cp5_case,
    "committee_challenge": cp6_case,
}


def head_of(store: Execution, module_id: str) -> Module:
    found = next(h for h in store.read().heads if h.module_id == module_id)
    assert found.qualification is not None
    assert found.qualification.implementation == "implemented"
    return store.result(found.result_sha256)


@pytest.mark.parametrize("step_id", sorted(SCHEMAS))
def test_a_model_payload_settles_its_module_through_its_step_entry(
    step_id: str, tmp_path: Path
) -> None:
    module_id = SCHEMAS[step_id][0]
    store, payload = CASES[step_id](tmp_path)
    ticket = store.begin(module_id)
    entered = submission.submit_model_payload(store, ticket.ticket_id, step_id, payload)
    assert entered.journal.status == "finished" and entered.journal.issues == ()
    assert entered.payload == payload and entered.composition is None
    assert head_of(store, module_id).module_id == module_id
    assert runner.journal_outcome(store, step_id, entered.journal)[0] == "accepted"


@pytest.mark.parametrize("step_id", sorted(SCHEMAS))
def test_a_payload_the_module_rejects_finishes_the_attempt_rejected(
    step_id: str, tmp_path: Path
) -> None:
    module_id = SCHEMAS[step_id][0]
    store, _ = CASES[step_id](tmp_path)
    ticket = store.begin(module_id)
    entered = submission.submit_model_payload(store, ticket.ticket_id, step_id, "{}")
    assert entered.journal.status == "finished" and entered.journal.issues
    assert runner.journal_outcome(store, step_id, entered.journal)[0] == "rejected"
    assert not [h for h in store.read().heads if h.module_id == module_id]


SUBMIT_ONLY_STEPS = ("credit_synthesis", "integrity_review", "committee_challenge")


@pytest.mark.parametrize("step_id", SUBMIT_ONLY_STEPS)
def test_tool_loop_rules_are_refused_for_the_submit_only_steps(
    step_id: str, tmp_path: Path
) -> None:
    store, payload = CASES[step_id](tmp_path)
    ticket = store.begin(SCHEMAS[step_id][0])
    with pytest.raises(ValueError, match=f"not to {step_id} "):
        submission.submit_model_payload(
            store, ticket.ticket_id, step_id, payload, rules=lambda _: ()
        )


def cp0_case(tmp_path: Path) -> tuple[Execution, str]:
    return fixture_store(tmp_path), as_submission(readiness_fixture()[1]).model_dump_json()


def cp1a_case(tmp_path: Path) -> tuple[Execution, str]:
    store = fixture_store(tmp_path)
    accept_cp0(store)
    return store, cp1a_submission().model_dump_json()


# Task 8.9: the pack-tool steps besides CP-1's, whose submits a tool-loop rule may reject.
PACK_CASES: dict[str, tuple[str, Callable[[Path], tuple[Execution, str]]]] = {
    "source_readiness": ("CP-0", cp0_case),
    "business_context": ("CP-1A", cp1a_case),
    "legal_covenants": ("CP-4", cp4_case),
    "relative_value": ("CP-3", cp3_case),
}


Rules = Callable[[str], tuple[str, ...]] | None


def enter(
    tmp_path: Path, step_id: str, payload: str | None = None, rules: Rules = None
) -> tuple[str, tuple[str, ...], Execution]:
    module_id, case = PACK_CASES[step_id]
    store, fixture = case(tmp_path)
    ticket = store.begin(module_id).ticket_id
    entered = submission.submit_model_payload(
        store, ticket, step_id, fixture if payload is None else payload, rules=rules
    )
    return (*runner.journal_outcome(store, step_id, entered.journal), store)


def module_results(store: Execution, module_id: str) -> list[str]:
    return [
        store.result(h.result_sha256).model_dump_json()
        for h in store.read().heads
        if h.module_id == module_id
    ]


@pytest.mark.parametrize("step_id", sorted(PACK_CASES))
def test_a_rule_issue_rejects_a_pack_step_its_validator_accepts_and_nothing_else_changes(
    step_id: str, tmp_path: Path
) -> None:
    module_id = PACK_CASES[step_id][0]
    plain = enter(tmp_path / "plain", step_id)
    clean = enter(tmp_path / "clean", step_id, rules=lambda _: ())
    assert plain[:2] == clean[:2] and plain[0] == "accepted", plain[1]
    assert module_results(clean[2], module_id) == module_results(plain[2], module_id) != []
    ruled = enter(tmp_path / "ruled", step_id, rules=lambda _: ("Rule: broken",))
    assert ruled[:2] == ("rejected", ("Rule: broken",))
    assert not [h for h in ruled[2].read().heads if h.module_id == module_id]
    # A payload the validator rejects keeps its own issues, followed by the rule's.
    bare = enter(tmp_path / "bare", step_id, "{}")
    both = enter(tmp_path / "both", step_id, "{}", rules=lambda _: ("Rule: broken",))
    assert bare[0] == both[0] == "rejected"
    assert both[1] == (*bare[1], "Rule: broken")


# --- prompts --------------------------------------------------------------------------------


def method(name: str, *, until: str | None = None) -> str:
    text = files("deploy_vii").joinpath("methods", name).read_text(encoding="utf-8")
    return (text.split(until, 1)[0] if until else text).strip()


RULES = {
    "credit_synthesis": (
        prompts.CP2_BASIS_RULE,
        prompts.CP2_SIGNALS_RULE,
        prompts.CP2_RUN_TEXT_RULE,
        prompts.CP2_PROHIBITED_RULE,
    ),
    "legal_covenants": (
        prompts.CITATION_RULE,
        prompts.CP4_SOURCES_RULE,
        prompts.CP4_THRESHOLD_RULE,
        prompts.CP4_METRIC_RULE,
        prompts.CP4_HEADROOM_RULE,
        prompts.CP4_RUN_TEXT_RULE,
        prompts.CP4_ROW_RULES,
    ),
    "relative_value": (
        prompts.CITATION_RULE,
        prompts.CP3_EVIDENCE_RULE,
        prompts.CP3_TALK_RULE,
        prompts.CP3_BASIS_RULE,
        prompts.CP3_PREFERENCE_RULE,
        prompts.CP3_RUN_TEXT_RULE,
        prompts.CP3_PROHIBITED_RULE,
    ),
    "integrity_review": (
        prompts.CP5_SCOPE_RULE,
        prompts.CP5_REVIEW_RULE,
        prompts.CP5_CONTRADICTION_RULE,
        prompts.CP5_TEXT_RULE,
    ),
    "committee_challenge": (
        prompts.CP6_CHALLENGE_RULE,
        prompts.CP6_RECOMMENDATION_RULE,
        prompts.CP6_CP5_RULE,
        prompts.CP6_RUN_TEXT_RULE,
        prompts.CP6_PROHIBITED_RULE,
    ),
}
METHODS = {
    "credit_synthesis": method("cp2.md"),
    "legal_covenants": method("cp4.md", until="## Tables"),
    "relative_value": method("cp3.md"),
    "integrity_review": method("cp5.md"),
    "committee_challenge": method("cp6.md"),
}


def system_of(step_id: str) -> str:
    pack, _ = readiness_fixture()
    schema = submission.STEPS[step_id].schema
    return prompts.build(
        step_id,
        pack,
        (),
        schema,
        module_context={} if step_id in CONTEXT_STEPS else None,
        scope={} if step_id == prompts.INTEGRITY else None,
    )[0].content


@pytest.mark.parametrize("step_id", sorted(SCHEMAS))
def test_each_new_step_states_its_method_and_each_rule_once(step_id: str) -> None:
    system = system_of(step_id)
    assert METHODS[step_id] in system and system.count(METHODS[step_id]) == 1
    for rule in RULES[step_id]:
        assert rule in prompts.STEP_CONTRACTS[step_id], rule
        assert system.count(rule) == 1, rule
    others = set(prompts.STEP_CONTRACTS) - {step_id}
    for rule in set(RULES[step_id]) - {prompts.CITATION_RULE}:
        assert not [s for s in others if rule in prompts.STEP_CONTRACTS[s]], rule


def test_cp4_rides_its_method_up_to_the_tables_only() -> None:
    system = system_of("legal_covenants")
    assert "## Tables" not in system and "T4F.6" not in system
    assert "Never state compliance, a breach or an amount of headroom" in system


def test_the_rules_state_what_each_validator_checks() -> None:
    assert "below High" in prompts.CP2_SIGNALS_RULE and "`restate`" in prompts.CP2_SIGNALS_RULE
    assert "`cp1a_refs` of a `gaps` row" in prompts.CP2_SIGNALS_RULE
    assert "Python reads the number" in prompts.CP4_THRESHOLD_RULE
    assert "headroom" in prompts.CP4_HEADROOM_RULE and "Python" in prompts.CP4_HEADROOM_RULE
    assert "only in `market_evidence`" in prompts.CP3_EVIDENCE_RULE
    assert "never a market level" in prompts.CP3_TALK_RULE
    assert "may order" in prompts.CP3_PREFERENCE_RULE
    for phrase in ("buy", "sell", "overweight", "recommend"):
        assert phrase in prompts.CP3_PROHIBITED_RULE
    assert "upstream evidence by `ref`" in prompts.CP5_REVIEW_RULE
    assert "two modules" in prompts.CP5_CONTRADICTION_RULE
    assert "`challengeable` is true" in prompts.CP6_CHALLENGE_RULE
    assert "at most once" in prompts.CP6_CHALLENGE_RULE
    assert "Insufficient Information together" in prompts.CP6_RECOMMENDATION_RULE
    assert "`insufficient_information`" in prompts.CP6_RECOMMENDATION_RULE
    assert "`cp5_cp4_rows`" in prompts.CP6_RECOMMENDATION_RULE
    assert "below High" in prompts.CP6_CP5_RULE and "`confidence_caps`" in prompts.CP6_CP5_RULE
    assert "`cp5_flagged_claims`" in prompts.CP6_CP5_RULE
    for phrase in ("buy", "sell", "switch", "peers", "position size"):
        assert phrase in prompts.CP6_PROHIBITED_RULE


def test_a_module_context_is_required_where_declared_and_refused_elsewhere() -> None:
    pack, _ = readiness_fixture()
    schema = submission.STEPS["credit_synthesis"].schema
    with pytest.raises(prompts.PromptError, match="needs its module context"):
        prompts.build("credit_synthesis", pack, (), schema)
    with pytest.raises(prompts.PromptError, match="not a declared input of step source_context"):
        prompts.build("source_context", pack, (), schema, module_context={"a": 1})
    with pytest.raises(prompts.PromptError, match="would replace the pack facts: run, sources"):
        prompts.build("credit_synthesis", pack, (), schema, module_context={"run": 1, "sources": 2})
    with pytest.raises(prompts.PromptError, match="needs its review scope"):
        prompts.build("integrity_review", pack, (), cp5_integrity.IntegritySubmission)
    with pytest.raises(prompts.PromptError, match="not a declared input of step relative_value"):
        prompts.build("relative_value", pack, (), schema, module_context={}, scope={})


def context_of(user: str) -> dict[str, Any]:
    body = user.split("<<<CONTEXT id=prepared-pack", 1)[1].split(">>>\n", 1)[1]
    document: dict[str, Any] = json.loads(body.split("\n<<<END>>>", 1)[0])
    return document


def test_the_module_context_rides_in_the_pack_context_beside_the_pack_facts() -> None:
    pack, _ = readiness_fixture()
    schema = submission.STEPS["credit_synthesis"].schema
    user = prompts.build("credit_synthesis", pack, (), schema, module_context={"cp1a_rows": []})[
        1
    ].content
    shown = context_of(user)
    assert shown["cp1a_rows"] == [] and {"run", "sources", "note"} <= set(shown)
    assert "<<<SOURCE" not in user  # CP-2 quotes nothing


# --- the runner's per-module context and declared sources ----------------------------------


def begun(tmp_path: Path, step_id: str) -> tuple[Execution, Attempt]:
    store, _ = CASES[step_id](tmp_path)
    return store, store.begin(SCHEMAS[step_id][0])


def test_each_contexts_is_the_modules_own_block_over_the_bound_upstream(tmp_path: Path) -> None:
    store, ticket = begun(tmp_path / "cp2", "credit_synthesis")
    up2 = cp2_synthesis.cp2_upstream(store, ticket)
    assert context.module_context(store, ticket, "credit_synthesis") == (
        cp2_synthesis.context_block(store.pack(), up2)
    )
    store, ticket = begun(tmp_path / "cp4", "legal_covenants")
    up4 = cp4_legal.upstream_of(store, ticket)
    assert context.module_context(store, ticket, "legal_covenants") == (
        cp4_legal.context_block(store.pack(), up4)
    )
    store, ticket = begun(tmp_path / "cp3", "relative_value")
    up3 = cp3_relative_value.cp3_upstream(store, ticket)
    assert context.module_context(store, ticket, "relative_value") == (
        cp3_relative_value.context_block(store.pack(), up3)
    )
    assert context.module_context(store, ticket, "integrity_review") is None
    store, ticket = begun(tmp_path / "cp6", "committee_challenge")
    up6 = cp6_committee.cp6_upstream(store, ticket)
    assert context.module_context(store, ticket, "committee_challenge") == (
        cp6_committee.context_block(store.pack(), up6)
    )
    assert context.module_context(store, ticket, "business_context") is None


def test_cp4_declares_only_the_legal_sources_cp0_classes_executed_or_filed(
    tmp_path: Path,
) -> None:
    store, ticket = begun(tmp_path, "legal_covenants")
    every = tuple(s.source_id for s in store.pack().sources)
    assert every == ("filing", "indenture", "deck")
    declared = context.declared_sources(store, ticket, "legal_covenants", every)
    assert declared == cp4_legal.upstream_of(store, ticket).legal_sources == ("filing", "indenture")


def test_cp3_declares_only_its_ready_third_party_sources(tmp_path: Path) -> None:
    store, ticket = begun(tmp_path, "relative_value")
    every = tuple(s.source_id for s in store.pack().sources)
    assert every == ("filing", cp3_tests.MARKET)
    assert context.declared_sources(store, ticket, "relative_value", every) == (cp3_tests.MARKET,)


def test_cp3_does_not_declare_a_third_party_source_the_pack_does_not_hold_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CP-0's `third_party` class is read from its T3 rows, not from the pack's source status.
    store, ticket = begun(tmp_path, "relative_value")
    pack = store.pack()
    missing = tuple(
        s.model_copy(update={"status": "missing"}) if s.source_id == cp3_tests.MARKET else s
        for s in pack.sources
    )
    monkeypatch.setattr(store, "pack", lambda *_: pack.model_copy(update={"sources": missing}))
    assert cp3_tests.MARKET in cp3_relative_value.cp3_upstream(store, ticket).market_sources
    every = tuple(s.source_id for s in pack.sources)
    assert context.declared_sources(store, ticket, "relative_value", every) == ()


def no_market_cp3(tmp_path: Path) -> tuple[Execution, Attempt]:
    """CP-2 settled over the one-filing pack, CP-4 settled empty, then a CP-3 ticket: CP-0
    classes no source `third_party`."""
    store = cp2_tests.journal(tmp_path)
    ticket = store.begin("CP-2")
    cp2_synthesis.submit_cp2_step(
        store, ticket.ticket_id, "credit_synthesis", cp2_tests.synthesis().model_dump_json()
    )
    ticket = store.begin("CP-4")
    run = store.pack().run
    empty = Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id="CP-4",
        inputs=ticket.inputs,
    )
    store.finish(ticket.ticket_id, empty.model_dump_json(), lambda _: ())
    return store, store.begin("CP-3")


def test_an_absent_market_source_declares_nothing_and_offers_an_empty_catalogue(
    tmp_path: Path,
) -> None:
    store, ticket = no_market_cp3(tmp_path)
    assert context.declared_sources(store, ticket, "relative_value", ("filing",)) == ()
    shown = context.module_context(store, ticket, "relative_value")
    assert shown is not None and shown["market_evidence_sources"] == []
    assert "no market evidence" in str(shown["market_evidence_note"])


@pytest.mark.parametrize(
    ("step_id", "expected"),
    [("source_context", ("filing",)), ("credit_synthesis", ()), ("committee_challenge", ())],
)
def test_other_steps_declare_what_step_sources_gives(
    step_id: str, expected: tuple[str, ...], tmp_path: Path
) -> None:
    store, ticket = begun(tmp_path, "credit_synthesis")
    assert context.declared_sources(store, ticket, step_id, ("filing",)) == expected
    assert context.step_sources(step_id, ("filing",)) == expected


# --- the CP-5 context projection ------------------------------------------------------------

REF = re.compile(r"\{([^{}|]+)\|[^{}]*\}")


def naive_projection(scope: cp5_integrity.ReviewScope) -> dict[str, set[str]]:
    """What the projection keeps, by an independent reading: the facts a claim's text names by
    `{ref|unit}`, every fact of an identity group and every reference Python flags."""
    checks = cp5_integrity.python_checks(scope)
    kept: dict[str, set[str]] = {}
    for _, head in scope.heads:
        ids = {fact.fact_id for fact in head.facts}
        named = {m for claim in head.claims for m in REF.findall(claim.text)}
        grouped = {f for g in checks.groups for m, f in g.members if m == head.module_id}
        flagged = set(checks.ref_marks.get(head.module_id, ()))
        kept[head.module_id] = ids & (named | grouped | flagged)
    return kept


def without_facts(block: dict[str, Any]) -> dict[str, Any]:
    return {
        **block,
        "modules": [{k: v for k, v in m.items() if k != "facts"} for m in block["modules"]],
    }


@settings(max_examples=120, deadline=None)
@given(cp5_tests.heads())
def test_the_cp5_projection_keeps_exactly_the_referenced_grouped_and_flagged_facts(
    heads: tuple[Module, ...],
) -> None:
    scope = cp5_tests.scope_of(cp5_tests.PACK, heads)
    projected = cp5_integrity.context_block(scope, facts=context.integrity_projection(scope))
    whole = cp5_integrity.context_block(scope)
    expected = naive_projection(scope)
    for shown, (_, head) in zip(projected["modules"], sorted_heads(scope), strict=True):
        assert {f["ref"] for f in shown["facts"]} == expected[head.module_id]
        order = [f.fact_id for f in head.facts if f.fact_id in expected[head.module_id]]
        assert [f["ref"] for f in shown["facts"]] == order  # head order, no copy
    assert without_facts(projected) == without_facts(whole)


def sorted_heads(scope: cp5_integrity.ReviewScope) -> list[tuple[Any, Module]]:
    return sorted(scope.heads, key=lambda pair: cp5_integrity._rank(pair[0].input_id))


def test_the_integrity_scope_is_the_projected_block_of_the_attempts_review_scope(
    tmp_path: Path,
) -> None:
    store, ticket = begun(tmp_path, "integrity_review")
    scope = cp5_integrity.review_scope(store, ticket)
    assert context.integrity_scope(store, ticket) == cp5_integrity.context_block(
        scope, facts=context.integrity_projection(scope)
    )


# --- dispatch end to end (FakeTransport) ----------------------------------------------------


def module_rig(tmp_path: Path, step_id: str, payload: str | None = None) -> Rig:
    store, ticket = begun(tmp_path / "journal", step_id)
    _, fixture_payload = CASES[step_id](tmp_path / "payload")
    keys = tmp_path / "keys"
    keys.mkdir()
    return Rig(
        store=store,
        ticket_id=ticket.ticket_id,
        ledger=Ledger(tmp_path / "ledger" / "l.jsonl", Decimal("5"), clock=lambda: NOW),
        pool=fixture_pool("batch-m"),
        writer=AttemptWriter(tmp_path / "artifacts"),
        key_path=make_rtf_key(keys),
        review=readiness_fixture()[1],
        root=tmp_path,
        submission=payload or fixture_payload,
    )


def sent(transport: FakeTransport) -> tuple[str, str, dict[str, Any]]:
    body = json.loads((transport.requests[0].body or b"{}").decode())
    system, user = (message["content"] for message in body["messages"])
    return system, user, body


def spec(step_id: str, sources: tuple[str, ...] = ()) -> StepSpec:
    return StepSpec(step_id, f"case-{step_id}", sources, max_tokens=4000)


def test_a_credit_synthesis_dispatch_settles_cp2_with_its_upstream_context(
    tmp_path: Path,
) -> None:
    rig = module_rig(tmp_path, "credit_synthesis")
    transport = FakeTransport(reply(rig))
    result = rig.run(ChatClient(transport), step=spec("credit_synthesis"))
    assert result.status == "accepted", result.issues
    system, user, body = sent(transport)
    assert body["response_format"]["json_schema"]["name"] == "credit_synthesis"
    assert METHODS["credit_synthesis"] in system
    shown = context_of(user)
    assert [r["ref"] for r in shown["cp1a_rows"]] and "cp1a_signals" in shown
    assert "<<<SOURCE" not in user
    assert head_of(rig.store, "CP-2").status == "restricted"


def test_a_legal_covenants_dispatch_is_sent_the_legal_sources_only(tmp_path: Path) -> None:
    rig = module_rig(tmp_path, "legal_covenants")
    transport = FakeTransport(reply(rig))
    result = rig.run(ChatClient(transport), step=spec("legal_covenants", ("filing", "indenture")))
    assert result.status == "accepted", result.issues
    _, user, _ = sent(transport)
    assert "<<<SOURCE id=filing " in user and "<<<SOURCE id=indenture " in user
    assert "<<<SOURCE id=deck " not in user
    assert [s["source_id"] for s in context_of(user)["legal_sources"]] == ["filing", "indenture"]
    found = {f.fact_id: f for f in head_of(rig.store, "CP-4").facts}
    assert found["T4.9.r01.headroom"].amount == Decimal("0.80")  # Python's, from the bound CP-1


def test_a_source_outside_cp4s_legal_sources_is_refused_before_anything_is_spent(
    tmp_path: Path,
) -> None:
    rig = module_rig(tmp_path, "legal_covenants")
    transport = FakeTransport(reply(rig))
    with pytest.raises(ValueError, match="legal_covenants is sent deck, which is not one of"):
        rig.run(ChatClient(transport), step=spec("legal_covenants", ("indenture", "deck")))
    assert transport.requests == [] and rig.ledger.state().attempts == ()


def test_a_relative_value_dispatch_is_sent_the_market_source_only(tmp_path: Path) -> None:
    rig = module_rig(tmp_path, "relative_value")
    transport = FakeTransport(reply(rig))
    with pytest.raises(ValueError, match="relative_value is sent filing"):
        rig.run(ChatClient(transport), step=spec("relative_value", ("filing", cp3_tests.MARKET)))
    result = rig.run(ChatClient(transport), step=spec("relative_value", (cp3_tests.MARKET,)))
    assert result.status == "accepted", result.issues
    _, user, _ = sent(transport)
    assert f"<<<SOURCE id={cp3_tests.MARKET} " in user and "<<<SOURCE id=filing " not in user
    assert context_of(user)["cp2_rows"]


def test_an_integrity_review_dispatch_sends_the_projected_scope_block(tmp_path: Path) -> None:
    rig = module_rig(tmp_path, "integrity_review")
    transport = FakeTransport(reply(rig))
    result = rig.run(ChatClient(transport), step=spec("integrity_review"))
    assert result.status == "accepted", result.issues
    system, user, _ = sent(transport)
    assert METHODS["integrity_review"] in system
    assert user.count(f"<<<CONTEXT id={prompts.INTEGRITY_BLOCK_ID} ") == 1
    rest = user.split(f"<<<CONTEXT id={prompts.INTEGRITY_BLOCK_ID} sha256=", 1)[1]
    digest, rest = rest.split(">>>\n", 1)
    body = rest.split("\n<<<END>>>", 1)[0]
    assert digest == hashlib.sha256(body.encode()).hexdigest() and "\n" not in body
    assert {m["module_id"] for m in json.loads(body)["modules"]} == {"CP-1", "CP-MODEL", "CP-1A"}
    assert "<<<SOURCE" not in user
    assert head_of(rig.store, "CP-5").module_id == "CP-5"


def test_a_committee_challenge_dispatch_settles_cp6_with_its_upstream_context(
    tmp_path: Path,
) -> None:
    rig = module_rig(tmp_path, "committee_challenge")
    transport = FakeTransport(reply(rig))
    result = rig.run(ChatClient(transport), step=spec("committee_challenge"))
    assert result.status == "accepted", result.issues
    system, user, body = sent(transport)
    assert body["response_format"]["json_schema"]["name"] == "committee_challenge"
    assert METHODS["committee_challenge"] in system
    shown = context_of(user)
    assert [r["ref"] for r in shown["cp2_rows"] if r["challengeable"]]
    assert {h["module_id"] for h in shown["heads"]} == {"CP-1", "CP-2", "CP-3", "CP-5"}
    assert shown["action_biases"] == list(cp6_committee.ACTION_BIASES)
    assert "<<<SOURCE" not in user  # CP-6 quotes nothing
    settled = head_of(rig.store, "CP-6")
    assert settled.status == "restricted"
    assert cp6_committee.settled_call(settled).action_bias == "Neutral"


def test_a_committee_challenge_declaring_a_pack_source_is_refused(tmp_path: Path) -> None:
    rig = module_rig(tmp_path, "committee_challenge")
    transport = FakeTransport(reply(rig))
    with pytest.raises(prompts.PromptError, match="declares no pack sources"):
        rig.run(ChatClient(transport), step=spec("committee_challenge", ("filing",)))
    assert transport.requests == []


# --- the CLI ------------------------------------------------------------------------------


class Sent(Exception):
    """Raised by the stand-in dispatch once it has the spec the CLI built."""


def test_the_cli_send_path_declares_cp4s_legal_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = cp4_tests.journal(tmp_path / "journal")
    seen: list[StepSpec] = []

    def dispatch(step: StepSpec, **_: object) -> None:
        seen.append(step)
        raise Sent

    class Prepared:
        @staticmethod
        def create(*_: object) -> Execution:
            return store

    monkeypatch.setattr(cli, "dispatch", dispatch)
    monkeypatch.setattr(cli, "Execution", Prepared)
    cell = cli.Cell("module-00", "cp-4", ("legal_covenants",), 7)
    with pytest.raises(Sent):
        cli._run_cell(
            cell,
            base=store,
            journals=tmp_path / "cells",
            ledger=Ledger(tmp_path / "l.jsonl", Decimal("1"), clock=lambda: NOW),
            pool=fixture_pool(),
            client=ChatClient(FakeTransport()),
            writer=AttemptWriter(tmp_path / "artifacts"),
            key_path=tmp_path / "key.rtf",
            key_index=1,
            bytes_per_token=Decimal(1),
            effort="medium",
            max_tokens=4000,
            timeout_s=60.0,
            evidence=tmp_path / "evidence",
            batch=cli.Batch(),
            rejections={},
            repair=True,
            sleep=lambda _: None,
        )
    (step,) = seen
    assert step.step_id == "legal_covenants" and step.declared_sources == ("filing", "indenture")


def test_a_regression_plans_only_cases_with_a_recorded_corpus_entry(tmp_path: Path) -> None:
    recorded = cli.recorded_steps()
    assert {"source_readiness", "quality"} <= recorded
    assert not {"business_context", *SCHEMAS} & recorded
    assert cli.unrecorded_cases() == (
        ("cp1a", "business_context"),
        ("cp2", "credit_synthesis"),
        ("cp4", "legal_covenants"),
        ("cp3", "relative_value"),
        ("cp5", "integrity_review"),
        ("cp6", "committee_challenge"),
    )
    pool = fixture_pool()
    cells = cli._regression_cells(pool, [item.slug for item in pool.eligible], 7)
    assert {cell.case_id for cell in cells} == {"cp0", "cp1"}
    corpus = tmp_path / "replay"
    (corpus / "credit_synthesis").mkdir(parents=True)
    (corpus / "credit_synthesis" / "synthetic-entry.json").write_text("{}", encoding="utf-8")
    assert ("cp2", "credit_synthesis") not in cli.unrecorded_cases(cli.recorded_steps(corpus))
    planned = cli._regression_cells(
        pool, [item.slug for item in pool.eligible], 7, cli.recorded_steps(corpus)
    )
    assert {cell.case_id for cell in planned} == {"cp2"}


def test_the_skip_line_names_every_unrecorded_case_and_never_reads_as_a_pass() -> None:
    line = cli.skipped_line(cli.unrecorded_cases())
    assert line == (
        "- Cases skipped (no recorded corpus entry for the settling step; not run, not a pass): "
        "cp1a (business_context), cp2 (credit_synthesis), cp4 (legal_covenants), "
        "cp3 (relative_value), cp5 (integrity_review), cp6 (committee_challenge)"
    )
    assert cli.skipped_line(()) is None
