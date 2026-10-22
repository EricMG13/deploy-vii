"""Task 2.9 fix 3: `source_context` states the readiness rules the validator now applies to it."""

import json
import re
from importlib.resources import files
from typing import Any

import pytest

from deploy_vii.business_context import BusinessContextSubmission, cp1a_consumers
from deploy_vii.contracts import Fact
from deploy_vii.live import prompts
from deploy_vii.live.schema import strict_schema, unverified_keywords
from deploy_vii.live.submission import (
    STEPS,
    ReadinessSubmission,
    compose_payload,
    rejection_issues,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.prose import bare_figures
from deploy_vii.readiness import live_consumers, validate_review
from deploy_vii.registry import modules
from tests.product.test_business_context import cp1_fact
from tests.product.test_live_submission import paged_pack
from tests.product.test_readiness import as_submission, readiness_fixture

SHARED = (prompts.SOURCES_ONCE_RULE, prompts.CITATION_RULE, prompts.COVERAGE_RULE)


def test_both_source_steps_state_the_shared_rules_word_for_word() -> None:
    for step_id in ("source_readiness", "source_context"):
        contract = prompts.STEP_CONTRACTS[step_id]
        assert all(rule in contract for rule in SHARED), step_id
    assert "every text field" in prompts.STEP_CONTRACTS["source_context"]


def test_the_citation_rule_states_what_the_matcher_tolerates() -> None:
    assert "verbatim substring" in prompts.CITATION_RULE
    assert "whitespace and line breaks may be written as one space" in prompts.CITATION_RULE
    assert "in the span its locator names" in prompts.CITATION_RULE


def test_the_source_context_prompt_carries_rules_and_coverage_but_no_consumer_list() -> None:
    pack = paged_pack(range(1, 196))
    system, user = (
        message.content
        for message in prompts.build(
            "source_context", pack, ("czr-2025-10k",), STEPS["source_context"].schema
        )
    )
    assert all(rule in system for rule in SHARED)
    assert "never do arithmetic" in system and "Cite only SOURCE blocks" in system
    body = user.split("<<<CONTEXT id=prepared-pack", 1)[1].split(">>>\n", 1)[1]
    context = json.loads(body.split("\n<<<END>>>", 1)[0])
    coverage = context["sources"][0]["extraction_coverage"]
    assert coverage["first_locator"] == "page:1" and coverage["last_locator"] == "page:195"
    assert coverage["pages_missing_between_first_and_last"] == []
    assert "consumers" not in context


# --- 2.10 -----------------------------------------------------------------------------------


def test_the_readiness_step_states_the_nonempty_analysis_rule() -> None:
    """Probe-4 Grok 7812cd5f: an empty `analysis` was rejected by a rule the prompt never said."""
    rule = (
        "`analysis`: at least one evidence-grounded read-through entry; an empty list is rejected"
    )
    assert rule in prompts.STEP_CONTRACTS["source_readiness"]
    pack, _ = readiness_fixture()
    system = prompts.build("source_readiness", pack, ("filing",), ReadinessSubmission)[0].content
    assert rule in system


def test_the_sent_schema_requires_at_least_one_analysis_entry() -> None:
    schema = strict_schema(ReadinessSubmission)
    assert schema["properties"]["analysis"]["minItems"] == 1
    sent = prompts.response_format("source_readiness", ReadinessSubmission)["json_schema"]
    assert sent["schema"]["properties"]["analysis"]["minItems"] == 1
    assert "minItems" in unverified_keywords(sent["schema"])  # named in every manifest
    assert '"minItems":1' in prompts.schema_text(ReadinessSubmission)  # and in the prompt


def test_an_empty_analysis_still_reaches_the_validator_with_its_own_wording() -> None:
    """The keyword is for the provider; the trusted validator stays the one that rejects, so the
    other issues of such a submission are still reported."""
    pack, review = readiness_fixture()
    document = json.loads(as_submission(review).model_dump_json())
    document["analysis"] = []
    assert rejection_issues(pack, json.dumps(document)) == ()  # it composes cleanly
    composed = compose_payload(pack, json.dumps(document)).review
    assert composed is not None
    assert validate_review(pack, composed) == (
        "Source readiness requires an evidence-grounded analytical read-through",
    )


def readiness_context(pack: PreparedPack) -> tuple[str, str, dict[str, Any]]:
    schema = STEPS["source_readiness"].schema
    system, user = (m.content for m in prompts.build("source_readiness", pack, ("filing",), schema))
    body = user.split("<<<CONTEXT id=prepared-pack", 1)[1].split(">>>\n", 1)[1]
    raw = body.split("\n<<<END>>>", 1)[0]
    return system, raw, json.loads(raw)


def test_each_consumer_in_the_context_carries_its_registry_title_and_purpose() -> None:
    """Probe-4: with ids only, careful models judged every consumer CONDITIONAL. Each line now
    carries the module registry's own title and purpose (methodology.json), nothing new."""
    pack, _ = readiness_fixture()
    system, raw, context = readiness_context(pack)
    registry = {item.module_id: item for item in modules()}
    assert context["consumers"] == [
        {
            "module_id": module_id,
            "title": registry[module_id].title,
            "purpose": registry[module_id].purpose,
        }
        for module_id in live_consumers(pack)
    ]
    for module_id in live_consumers(pack):
        assert registry[module_id].title in raw
    assert "not a source and cannot be cited" in context["note"]  # still the CONTEXT block
    assert "its title and purpose there (module registry text)" in system


def test_the_consumer_lines_carry_no_numeric_content() -> None:
    """Registry text only: with the module ids taken out, the consumer lines hold no digit, so
    no figure from a module brief (`methods/`) can reach the model through them."""
    pack, _ = readiness_fixture()
    _, _, context = readiness_context(pack)
    text = re.sub(r"\bCP-[A-Z0-9]+\b", "", json.dumps(context["consumers"]))
    assert not re.search(r"[0-9]", text)
    brief = files("deploy_vii").joinpath("methods", "cp0.md").read_text(encoding="utf-8")
    figures = set(re.findall(r"[0-9][0-9.,]*", brief))
    assert figures and not any(figure in text for figure in figures)


def test_other_steps_get_no_consumer_lines() -> None:
    pack, _ = readiness_fixture()
    schema = STEPS["source_context"].schema
    user = prompts.build("source_context", pack, ("filing",), schema)[1].content
    assert "consumers" not in user and "Canonical data foundation" not in user


# --- 7.0: the prompt states what the quote matcher and the run-text rule enforce ------------

INTERLEAVE_RULE = (
    "Copy a run that is contiguous in the SOURCE block as printed; never reassemble a sentence "
    "across interleaved table text."
)
PAGE_RULE = "Never continue a quote onto the next page."
RUN_TEXT_EXAMPLES = (
    "FY2025",
    "Q3 2025",
    "LTM",
    "Items 7, 7A",
    "page:12",
    "pages 16-18",
    "001-36629",
    "195 of 195 pages",
)


def composed(step_id: str) -> str:
    pack, _ = readiness_fixture()
    schema = STEPS[step_id].schema
    return prompts.build(step_id, pack, ("filing",), schema)[0].content


def test_the_citation_rule_states_the_interleave_and_page_rules_once() -> None:
    assert INTERLEAVE_RULE in prompts.CITATION_RULE and PAGE_RULE in prompts.CITATION_RULE
    for step_id in ("source_readiness", "source_context"):
        system = composed(step_id)
        assert system.count(INTERLEAVE_RULE) == 1 and system.count(PAGE_RULE) == 1, step_id


def test_the_readiness_step_states_the_run_text_rule_once_and_cp0_md_carries_it() -> None:
    system = composed("source_readiness")
    assert prompts.RUN_TEXT_RULE in prompts.STEP_CONTRACTS["source_readiness"]
    assert system.count(prompts.RUN_TEXT_RULE) == 1
    assert prompts.RUN_TEXT_RULE not in composed("source_context")
    assert "`analysis[].text`" in prompts.RUN_TEXT_RULE
    assert "the validator rejects a bare figure" in prompts.RUN_TEXT_RULE
    assert all(f"`{label}`" in prompts.RUN_TEXT_RULE for label in RUN_TEXT_EXAMPLES)
    brief = files("deploy_vii").joinpath("methods", "cp0.md").read_text(encoding="utf-8")
    assert " ".join(prompts.RUN_TEXT_RULE.split()) in " ".join(brief.split())


@pytest.mark.parametrize("label", RUN_TEXT_EXAMPLES)
def test_every_label_the_run_text_rule_allows_is_one_the_validator_allows(label: str) -> None:
    """The prompt never tells the model a figure is allowed that `prose` would reject."""
    assert bare_figures(f"Coverage is stated as {label} in the filing.") == ()


def test_a_bare_figure_the_rule_forbids_is_rejected() -> None:
    assert bare_figures("Revenue was 11,456 in the year.") == ("11,456",)


# --- 7.0d: the financials step states what its sent schema and validators enforce ------------

FINANCIAL_RULES = (
    prompts.AMOUNT_RULE,
    prompts.ACCOUNT_METRIC_RULE,
    prompts.CONTEXT_STEP_RULE,
    prompts.DECLARED_PERIOD_RULE,
)


def test_the_financials_step_states_each_rule_once_and_no_longer_asks_for_printed_amounts() -> None:
    system = composed("financials")
    for rule in FINANCIAL_RULES:
        assert rule in prompts.STEP_CONTRACTS["financials"]
        assert system.count(rule) == 1, rule
    assert "Report each amount exactly as the source states it." not in system
    for step_id in ("source_readiness", "source_context", "narrative", "readiness"):
        assert not [rule for rule in FINANCIAL_RULES if rule in composed(step_id)], step_id


def test_the_amount_rule_shows_the_two_printed_forms_e1_batch_3_sent_as_strings() -> None:
    rule = prompts.AMOUNT_RULE
    assert "JSON number" in rule and "never a string" in rule
    assert "`3,624` is 3624" in rule and "`(211)` is -211" in rule
    assert "never arithmetic" in rule


def test_the_amount_rule_names_the_unit_python_assigns_to_each_rate_and_facility_money() -> None:
    """Fix 1: the units `canonical_audit._positions` assigns. A rate is not written as printed:
    21.0% is a decimal fraction, 2.75% is basis points; facility money is in its own currency."""
    rule = prompts.AMOUNT_RULE
    assert "`effective_tax_rate` is a decimal fraction (21.0% is 0.21)" in rule
    assert "`spread_bps` and `floor_bps` are basis points (2.75% is 275)" in rule
    assert "`fixed_rate` is a percent (5.25% is 5.25)" in rule
    assert "the facility's own `currency`" in rule
    assert "KPI" in rule and "own `unit`" in rule
    assert "Money amounts" in rule and "never arithmetic" in rule


def test_the_account_rule_names_the_enum_and_where_other_figures_go() -> None:
    rule = prompts.ACCOUNT_METRIC_RULE
    assert "`metric_id`" in rule and "enum" in rule
    assert "`statement_lines`" in rule and "`other:`" in rule and "not in `accounts`" in rule
    # The enum the rule points at is the one the schema printed below the rule carries.
    enum = strict_schema(STEPS["financials"].schema)["$defs"]["AccountObservation"]["properties"][
        "metric_id"
    ]["enum"]
    assert json.dumps(enum, separators=(",", ":")) in composed("financials")


# --- 7.0f: the statement-line sign convention reaches the model --------------------------------


def test_the_financials_step_states_the_sign_rule_once_and_no_other_step_does() -> None:
    """E1 batch 4: 14 lines were `outflow_magnitude` with no `sign_citations`; nothing said so."""
    rule = prompts.SIGN_RULE
    assert rule in prompts.STEP_CONTRACTS["financials"]
    assert composed("financials").count(rule) == 1
    for step_id in ("source_readiness", "source_context", "narrative", "readiness"):
        assert rule not in composed(step_id), step_id


def test_the_sign_rule_matches_what_the_validator_and_python_do_with_the_convention() -> None:
    rule = prompts.SIGN_RULE
    assert "`sign_convention`" in rule and "`signed`" in rule and "`outflow_magnitude`" in rule
    assert "`sign_citations`" in rule and "at least one" in rule
    assert "repeat the value's citation in `sign_citations`" in rule
    assert "read as -abs(amount)" in rule and "use `signed` for a negative figure" in rule
    assert "balance-sheet" in rule


# --- 7.2: the CP-1A business_context step ---------------------------------------------------

CP1A_RULES = (
    prompts.SOURCES_ONCE_RULE,
    prompts.CITATION_RULE,
    prompts.COVERAGE_RULE,
    prompts.CP1A_RUN_TEXT_RULE,
    prompts.CP1A_CATEGORY_RULE,
    prompts.CP1A_CONFLICT_RULE,
    prompts.CP1A_PROHIBITED_RULE,
    prompts.CP1A_CONSUMER_RULE,
)


def cp1a_prompt(pack: PreparedPack, cp1_facts: tuple[Fact, ...] = ()) -> tuple[str, str]:
    system, user = (
        m.content
        for m in prompts.build(
            "business_context",
            pack,
            ("filing",),
            STEPS["business_context"].schema,
            cp1_facts=cp1_facts,
        )
    )
    return system, user


def context_of(user: str) -> dict[str, Any]:
    body = user.split("<<<CONTEXT id=prepared-pack", 1)[1].split(">>>\n", 1)[1]
    document: dict[str, Any] = json.loads(body.split("\n<<<END>>>", 1)[0])
    return document


def test_the_business_context_step_is_cp1a_with_its_thin_contract() -> None:
    assert STEPS["business_context"].module_id == "CP-1A"
    assert STEPS["business_context"].schema is BusinessContextSubmission


def test_the_business_context_step_states_each_validator_rule_once() -> None:
    pack, _ = readiness_fixture()
    system, _ = cp1a_prompt(pack)
    for rule in CP1A_RULES:
        assert rule in prompts.STEP_CONTRACTS["business_context"], rule
        assert system.count(rule) == 1, rule
    assert "logged, not reconciled" in prompts.CP1A_CONFLICT_RULE
    for phrase in ("peer ranking", "instrument recommendation", "recovery conclusion"):
        assert phrase in prompts.CP1A_PROHIBITED_RULE
    for category in ("Documentary Fact", "Management Language", "Analyst Interpretation"):
        assert category in prompts.CP1A_CATEGORY_RULE
    for step_id in ("source_readiness", "source_context", "financials"):
        assert prompts.CP1A_CONSUMER_RULE not in composed(step_id)
    # Every label the run-text rule shows is one the validator allows (the CONTEXT key aside).
    assert bare_figures(prompts.CP1A_RUN_TEXT_RULE.replace("`cp1_facts`", "")) == ()


def test_the_method_prose_rides_in_the_system_prompt_and_states_no_figure() -> None:
    brief = files("deploy_vii").joinpath("methods", "cp1a.md").read_text(encoding="utf-8")
    assert len(brief.splitlines()) < 90
    for anchor in ("Reader question", "decision drivers", "Evidence (a located quote)"):
        assert anchor in brief
    assert bare_figures(brief) == ()  # labels only (r14, CP-1A, CP-2C)
    pack, _ = readiness_fixture()
    system, _ = cp1a_prompt(pack)
    assert brief.strip() in system


def test_the_context_lists_the_cp1a_consumers_and_says_no_figure_without_cp1() -> None:
    pack, _ = readiness_fixture()
    _, user = cp1a_prompt(pack)
    context = context_of(user)
    registry = {item.module_id: item for item in modules()}
    assert [c["module_id"] for c in context["consumers"]] == list(cp1a_consumers(pack))
    assert all(c["title"] == registry[c["module_id"]].title for c in context["consumers"])
    assert context["cp1_facts"] == []
    assert "no figure may be referenced" in context["cp1_facts_note"]
    assert "sources" in context and "run" in context  # the pack facts stay


def test_the_context_offers_only_referencable_cp1_facts_with_python_spellings() -> None:
    pack, _ = readiness_fixture()
    figure = cp1_fact(pack)
    text_fact = figure.model_copy(
        update={"fact_id": "T4.10.note", "amount": None, "text": "a note", "unit": None}
    )
    _, user = cp1a_prompt(pack, (figure, text_fact))
    context = context_of(user)
    assert context["cp1_facts"] == [
        {
            "ref": "T4.10.liquidity.FY2025",
            "label": "Liquidity",
            "period": "FY2025",
            "unit": "US$ m",
            "shown": "1,100 US$ m",
        }
    ]
    assert "{ref|unit}" in context["cp1_facts_note"]


def test_the_cp1_facts_never_appear_in_another_steps_context() -> None:
    pack, _ = readiness_fixture()
    user = prompts.build(
        "source_readiness", pack, ("filing",), ReadinessSubmission, cp1_facts=(cp1_fact(pack),)
    )[1].content
    assert "cp1_facts" not in user and "T4.10.liquidity" not in user
