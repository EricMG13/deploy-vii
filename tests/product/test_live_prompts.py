"""Task 2.9 fix 3: `source_context` states the readiness rules the validator now applies to it."""

import json
import re
from importlib.resources import files
from typing import Any

import pytest

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
