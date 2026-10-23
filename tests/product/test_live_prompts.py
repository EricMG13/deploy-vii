"""Task 2.9 fix 3: `source_context` states the readiness rules the validator now applies to it."""

import hashlib
import json
import re
import tempfile
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import pytest

from deploy_vii.business_context import BusinessContextSubmission, Conflict, cp1a_consumers
from deploy_vii.canonical_tables import CanonicalTables
from deploy_vii.context_binding import validate_financial_context
from deploy_vii.contracts import Fact, Span
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_workflow import cp1_registers
from deploy_vii.downstream_readiness import (
    _EVIDENCE_GROUPS,
    ConsumerAssessment,
    DownstreamInputs,
    DownstreamReview,
    GapAssessment,
    RequirementAssessment,
    downstream_inputs,
    validate_downstream_review,
)
from deploy_vii.financial_contracts import (
    FinancialBook,
    SegmentAllocation,
    SegmentObservation,
    StatementLine,
)
from deploy_vii.financial_validation import book_issues, validate_financial_review
from deploy_vii.live import prompts
from deploy_vii.live.context import (
    FULL,
    KINDS,
    NARRATIVE_EVIDENCE,
    PROJECTIONS,
    evidence_table,
    step_sources,
    upstream_text,
)
from deploy_vii.live.schema import strict_schema, unverified_keywords
from deploy_vii.live.submission import (
    STEPS,
    ReadinessSubmission,
    compose_payload,
    rejection_issues,
)
from deploy_vii.narrative import (
    _DIMENSIONS,
    _FINANCIAL,
    EvidencePart,
    Finding,
    FundingAssessment,
    IssuerPart,
    NarrativeInputs,
    NarrativeReview,
    ProsePart,
    StoryCoverage,
    canonical_narrative,
    narrative_inputs,
    validate_narrative_review,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.prose import bare_figures
from deploy_vii.quality import (
    CoverageField,
    EvidenceCeiling,
    QualityInputs,
    QualityReview,
    assess_quality,
)
from deploy_vii.quotes import quoted
from deploy_vii.readiness import live_consumers, validate_review
from deploy_vii.registry import modules
from deploy_vii.statement_validation import (
    ACCOUNT_LINKS,
    OPTIONAL_ITEMS,
    REQUIRED_ITEMS,
    statement_issues,
)
from tests.product.test_business_context import cp1_fact
from tests.product.test_canonical_gaps import case
from tests.product.test_downstream_readiness import evidence
from tests.product.test_financials import _C, book, conflict, observed
from tests.product.test_live_submission import paged_pack
from tests.product.test_model_readiness import ready_case
from tests.product.test_narrative import draft, populated
from tests.product.test_readiness import as_submission, readiness_fixture
from tests.product.test_source_context import case as context_case
from tests.product.test_source_context import event_case
from tests.product.test_statements import line as bs_line

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


@cache
def staged_scope() -> tuple[QualityInputs, CanonicalTables]:
    """The QA inputs and registers of the promotable 6.4 CP-1 case (built once)."""
    from tests.product.test_cp1_workflow import staged

    with tempfile.TemporaryDirectory() as directory:
        store, attempt = staged(Path(directory))
        registers = cp1_registers(store, attempt.ticket_id)
    return cp1_quality_inputs(registers), registers


@cache
def composed(step_id: str) -> str:
    pack, _ = readiness_fixture()
    schema = STEPS[step_id].schema
    scope = prompts.quality_scope(staged_scope()[1]) if step_id == prompts.QUALITY else None
    sources = step_sources(step_id, ("filing",))
    return prompts.build(step_id, pack, sources, schema, scope=scope)[0].content


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
    prompts.DECLARED_PERIOD_RULE,
)


def test_the_financials_step_asks_for_no_hash_and_keeps_rules_a_to_d() -> None:
    """Task 7.0i: Python fills `context_step_sha256`, so neither the step text nor the schema
    printed below it names the field (E1 batch 5 copied the wrong 64-hex value three times)."""
    contract = prompts.STEP_CONTRACTS["financials"]
    assert not hasattr(prompts, "CONTEXT_STEP_RULE")
    # Fix 1: no CP-1 step asks for any hash, in its text or in the schema printed below it.
    for step_id in ("source_context", "financials", "narrative", "readiness"):
        assert "sha256" not in prompts.STEP_CONTRACTS[step_id], step_id
        assert "sha256" not in composed(step_id).split("JSON Schema:")[1], step_id
    rules = [line[:3] for line in contract.splitlines() if line[1:3] == ". "]
    assert rules[:4] == ["a. ", "b. ", "c. ", "d. "]
    assert f"c. {prompts.DECLARED_PERIOD_RULE}" in contract
    assert f"d. {prompts.SIGN_RULE}" in contract


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
    # Fix round 1: the four evidence rules the validator enforces, each stated once.
    for rule in (
        "A source assessed above Insufficient cites its content.",
        "An unavailable source is assessed Insufficient.",
        "A source assessment cites only its own source.",
        "An available (Yes or Partial) disclosure item cites where it is disclosed.",
    ):
        assert system.count(rule) == 1, rule
    assert "`flag_topics`" in prompts.CP1A_CONSUMER_RULE
    assert "Management Language" in prompts.CP1A_PROHIBITED_RULE  # the labelled-quote allowance
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


def test_every_step_states_the_compact_output_rule_once() -> None:
    """Task 7.0h: the budget-saving rule rides in the common preamble of every step."""
    rule = prompts.COMPACT_OUTPUT_RULE
    assert "no indentation" in rule and "no line breaks between fields" in rule
    assert "cut before its last field" in rule
    for step_id in STEPS:
        assert composed(step_id).count(rule) == 1, step_id
        assert rule not in prompts.STEP_CONTRACTS[step_id], step_id


# --- 7.0j: the financials step states the statement-register rules the validator enforces ------


def statement_line(name: str, item: str, amount: str, priority: int, pid: str) -> StatementLine:
    return StatementLine.model_validate(
        {
            "line_id": name,
            "statement": "IS",
            "item_id": item,
            "label": "Synthetic " + item,
            "period_id": pid,
            "display_priority": priority,
            "line_kind": "detail",
            "value": observed(f"{name}.{pid}", amount),
        }
    )


def register_book(
    *, shared_line_id: bool, line_amount: str = "100", conflicting: bool = False
) -> FinancialBook:
    """Revenue and cogs lines for Q1 and Q2: one line_id per line, or the batch-6 shape."""
    base = book()
    lines = [
        statement_line(
            f"is-{item}" if shared_line_id else f"is-{item}-{pid}", item, amount, priority, pid
        )
        for item, amount, priority in (("revenue", line_amount, 1), ("cogs", "-30", 2))
        for pid in ("Q1", "Q2")
    ]
    accounts = base.accounts
    if conflicting:
        lines = [
            row.model_copy(update={"value": conflict("revenue.line.conflict")})
            if (row.item_id, row.period_id) == ("revenue", "Q2")
            else row
            for row in lines
        ]
        accounts = tuple(
            a.model_copy(update={"value": conflict("revenue.conflict")})
            if (a.metric_id, a.period_id) == ("revenue", "Q2")
            else a
            for a in accounts
        )
    return base.model_copy(update={"statement_lines": tuple(lines), "accounts": accounts})


REGISTER_RULES = (
    prompts.LINE_IDENTITY_RULE,
    prompts.STATEMENT_ITEMS_RULE,
    prompts.CONFLICT_RULE,
    prompts.SEGMENT_ALLOCATION_RULE,
)


def test_the_financials_step_letters_the_register_rules_e_to_h_once_each() -> None:
    contract = prompts.STEP_CONTRACTS["financials"]
    rules = [line[:3] for line in contract.splitlines() if line[1:3] == ". "]
    assert rules == ["a. ", "b. ", "c. ", "d. ", "e. ", "f. ", "g. ", "h. ", "i. "]  # 7.11: i
    for letter, rule in zip("efgh", REGISTER_RULES, strict=True):
        assert f"{letter}. {rule}" in contract
        assert composed("financials").count(rule) == 1, rule
    for step_id in ("source_readiness", "source_context", "narrative", "readiness"):
        assert not [rule for rule in REGISTER_RULES if rule in composed(step_id)], step_id


def test_the_line_identity_rule_matches_the_validator_checks() -> None:
    rule = prompts.LINE_IDENTITY_RULE
    for phrase in (
        "one `line_id`",
        "one `display_priority`",
        "same `statement`, `item_id`, `label` and `line_kind`",
        "one line per statement",
        "across all periods",
        "`kpi_id`",
        "`addback_label` and `classification`",
        "`segment_name` and `segment_type`",
        "`kpi_label`, `business_unit`, `definition`, `unit` and `value_type`",
        "never its own `line_id`",
        "`addback_id`",
        "`segment_id`",
        '"is-net-revenues"',
        "FY2025",
        "FY2024",
    ):
        assert phrase in rule, phrase
    assert statement_issues(register_book(shared_line_id=True)) == ()
    assert any(
        i.startswith("Duplicate statement display priority")
        for i in statement_issues(register_book(shared_line_id=False))
    )


def test_the_statement_item_lines_are_rendered_from_the_validators_tables() -> None:
    lines = {
        line.split(": ", 1)[0]: line
        for line in prompts.STATEMENT_ITEMS_RULE.splitlines()
        if line.split(": ", 1)[0] in REQUIRED_ITEMS
    }
    assert set(lines) == {"IS", "CFS", "BS"}
    for statement, line in lines.items():
        listed = line.removeprefix(f"{statement}: ").rstrip(".").split(", ")
        assert listed == [*REQUIRED_ITEMS[statement], *OPTIONAL_ITEMS[statement]]
    assert prompts.STATEMENT_ITEMS_RULE in composed("financials")
    assert "`other:deferred_revenue`" in prompts.STATEMENT_ITEMS_RULE
    assert "letters, digits and `_.:-` only, no spaces" in prompts.STATEMENT_ITEMS_RULE
    source = files("deploy_vii").joinpath("live", "prompts.py").read_text(encoding="utf-8")
    for items in (*REQUIRED_ITEMS.values(), *OPTIONAL_ITEMS.values()):
        for item_id in items:
            assert f'"{item_id}"' not in source, item_id


def test_the_conflict_rule_names_the_contract_mechanism_and_the_validator_accepts_it() -> None:
    rule = prompts.CONFLICT_RULE
    for phrase in ("`status`", "`conflicting`", "`alternatives`", "null `amount`", "`reason`"):
        assert phrase in rule, phrase
    renamed = {(st, it): m for (st, it), m in ACCOUNT_LINKS.items() if it != m}
    assert len(renamed) >= 4
    for (statement, item), metric in renamed.items():
        assert f"{statement} `{item}` is the `{metric}` account" in rule
    assert rule.count(" is the `") == len(renamed)
    silent = register_book(shared_line_id=True, line_amount="90")
    assert any(
        i.startswith("Statement/account disagreement requires explicit conflict")
        for i in statement_issues(silent)
    )
    both = statement_issues(register_book(shared_line_id=True, conflicting=True))
    assert not [i for i in both if "disagreement" in i or "source statement conflict" in i]
    # A conflicting statement line beside a canonical account amount is the other rejection.
    plain = register_book(shared_line_id=True)
    lines = tuple(
        row.model_copy(update={"value": conflict("revenue.line.conflict")})
        if (row.item_id, row.period_id) == ("revenue", "Q2")
        else row
        for row in plain.statement_lines
    )
    stale = statement_issues(plain.model_copy(update={"statement_lines": lines}))
    assert any(i.startswith("Unresolved source statement conflict") for i in stale)


def test_the_segment_allocation_rule_matches_the_validator_message() -> None:
    rule = prompts.SEGMENT_ALLOCATION_RULE
    for phrase in ("`segment_allocation`", "every `segment_id`", "exactly once", "presentation"):
        assert phrase in rule, phrase


def test_an_omitted_segment_is_rejected_with_the_message_the_rule_describes() -> None:
    base = book()
    segment = SegmentObservation(
        segment_id="digital",
        segment_name="Digital",
        segment_type="OPERATING_SEGMENT",
        display_priority=1,
        period_id="Q1",
        revenue=observed("segment", "40"),
        classification_citations=(_C,),
    )
    disclosure = base.segment_disclosure.model_copy(update={"status": "partial"})
    omitted = base.model_copy(
        update={"segments": (segment,), "segment_allocation": (), "segment_disclosure": disclosure}
    )
    assert any(i.startswith("Allocate every segment exactly once") for i in book_issues(omitted))
    placed = SegmentAllocation(
        slot_id="DIVISION_1",
        slot_label="Digital",
        component_segment_ids=("digital",),
        rationale="Same business",
    )
    ok = omitted.model_copy(update={"segment_allocation": (placed,)})
    assert not any(i.startswith("Allocate every segment") for i in book_issues(ok))


def test_the_register_rules_stay_inside_the_financials_prompt_budget() -> None:
    assert sum(len(rule) for rule in REGISTER_RULES) < 4500  # characters, about 1,100 tokens


# --- task 7.4: the `quality` step: the analyst's judgments, Python's arithmetic -------------

QUALITY_RULES = (
    prompts.QUALITY_CLAIMS_RULE,
    prompts.QUALITY_LINEAGE_RULE,
    prompts.QUALITY_FINDINGS_RULE,
)


def quality_prompt() -> tuple[str, str]:
    pack, _ = readiness_fixture()
    scope = prompts.quality_scope(staged_scope()[1])
    system, user = (
        m.content for m in prompts.build("quality", pack, (), QualityReview, scope=scope)
    )
    return system, user


def scope_block(user: str) -> tuple[str, str]:
    """The quality-scope block's header hash and its body."""
    rest = user.split(f"<<<CONTEXT id={prompts.QUALITY_BLOCK_ID} sha256=", 1)[1]
    digest, rest = rest.split(">>>\n", 1)
    return digest, rest.split("\n<<<END>>>", 1)[0]


def test_the_quality_step_states_each_rule_once_and_asks_for_no_score() -> None:
    system, _ = quality_prompt()
    for rule in QUALITY_RULES:
        assert rule in prompts.STEP_CONTRACTS["quality"], rule
        assert system.count(rule) == 1, rule
    assert "never state a score, band or status" in system
    assert "Python fills the inputs binding" in system
    # The validator's lineage order, strongest first (`quality.WEIGHTS`).
    order = "Directly Sourced, Calculated, Assumption-Based, Analyst Inference, Weak Lineage"
    assert order in prompts.QUALITY_LINEAGE_RULE
    assert "never a stronger one" in prompts.QUALITY_LINEAGE_RULE
    for step_id in ("source_context", "readiness", "business_context"):
        assert all(rule not in composed(step_id) for rule in QUALITY_RULES), step_id
    schema = system.split("JSON Schema:\n", 1)[1]
    assert "inputs_sha256" not in schema and "confidence" not in schema


def test_a_repair_never_licenses_softening_a_finding() -> None:
    """Fix round 1 (coordinator ruling): a Blocked QA verdict is an analytical outcome, so the
    contract says a REPAIR block is no reason to lower a severity or change a status."""
    rule = (
        "A REPAIR block never justifies lowering a severity or changing a status; keep every "
        "finding the CONTEXT block supports."
    )
    assert prompts.QUALITY_REPAIR_RULE == rule
    system, _ = quality_prompt()
    assert system.count(rule) == 1
    for step_id in ("source_context", "financials", "readiness", "business_context"):
        assert rule not in composed(step_id), step_id


def test_the_quality_context_is_the_qa_scope_as_compact_json_with_its_hash() -> None:
    inputs, registers = staged_scope()
    _, user = quality_prompt()
    assert user.count(f"<<<CONTEXT id={prompts.QUALITY_BLOCK_ID} ") == 1
    digest, body = scope_block(user)
    assert digest == hashlib.sha256(body.encode()).hexdigest()
    assert "\n" not in body and ": " not in body.split('"claims"', 1)[0]  # compact
    scope = json.loads(body)
    assert scope == json.loads(json.dumps(prompts.quality_scope(registers)))
    assert [c["claim_id"] for c in scope["claims"]] == [c.claim_id for c in inputs.claims]
    assert [c["evidence_ids"] for c in scope["claims"]] == [
        list(c.evidence_ids) for c in inputs.claims
    ]
    ceilings = {c.evidence_id: c for c in inputs.ceilings}
    named = {e for c in inputs.claims for e in c.evidence_ids}
    assert {e["evidence_id"] for e in scope["evidence"]} == named
    for entry in scope["evidence"]:
        bound = ceilings[entry["evidence_id"]]
        assert (entry["ceiling"], entry["basis"]) == (bound.ceiling, bound.basis)
        assert entry["record"]["record_json"] and "citations" in entry["record"]
    counted = len(scope["coverage_slots"]) + sum(c["slots"] for c in scope["coverage_cells"])
    assert counted == len(inputs.coverage)
    present = [s for s in inputs.coverage if s.present]
    assert sum(s["present"] for s in scope["coverage_slots"]) + sum(
        c["slots"] for c in scope["coverage_cells"] if c["present"]
    ) == len(present)
    assert sum(scope["references_by_basis"].values()) == len(inputs.references)
    assert (scope["source_gate"], scope["module_status"]) == (
        inputs.source_gate,
        inputs.module_status,
    )
    assert inputs.content_hash() not in user  # the binding is Python's, never shown
    assert len(body) < 20_000  # the cells are counted, not listed (about 45,000 here)


def test_the_qa_scope_with_held_inputs_equals_the_scope_it_computes() -> None:
    """Task 7.10 item 3: `runner._plan` passes the inputs it already holds (it also records their
    hash in the manifest), always `cp1_quality_inputs(registers)`, so the scope is unchanged."""
    inputs, registers = staged_scope()
    assert inputs == cp1_quality_inputs(registers)
    assert prompts.quality_scope(registers, inputs) == prompts.quality_scope(registers)


def test_the_qa_scope_is_required_for_quality_and_refused_elsewhere() -> None:
    pack, _ = readiness_fixture()
    with pytest.raises(prompts.PromptError, match="needs its QA scope"):
        prompts.build("quality", pack, (), QualityReview)
    with pytest.raises(prompts.PromptError, match="not a declared input of step readiness"):
        prompts.build("readiness", pack, (), STEPS["readiness"].schema, scope={})


def test_a_cell_slot_without_its_register_fact_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid registers cannot drop a fact (their own validator refuses it), so this stands in
    for a QA projection that drifts from the register facts: the scope fails closed."""
    inputs, registers = staged_scope()
    stray = CoverageField(field_id="qa-cell:stray", present=True, rationale="Drifted slot")
    drifted = inputs.model_copy(
        update={
            "coverage": (*inputs.coverage, stray),
            "references": (*inputs.references, stray.field_id),
            "ceilings": (*inputs.ceilings, EvidenceCeiling.of(stray.field_id, "coverage")),
        }
    )
    monkeypatch.setattr(prompts, "cp1_quality_inputs", lambda _: drifted)
    with pytest.raises(prompts.PromptError, match="qa-cell:stray matches no register fact"):
        prompts.quality_scope(registers)


def test_claim_evidence_without_its_register_record_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid narrative cites catalogue records only, so this stands in for a QA projection
    whose claim names evidence the catalogue lacks: the scope fails closed, never a bare id."""
    inputs, registers = staged_scope()
    claim = inputs.claims[0]
    stray = "gap:stray"
    drifted = inputs.model_copy(
        update={
            "claims": (
                claim.model_copy(update={"evidence_ids": (*claim.evidence_ids, stray)}),
                *inputs.claims[1:],
            ),
            "references": (*inputs.references, stray),
            "ceilings": (*inputs.ceilings, EvidenceCeiling.of(stray, "gap")),
        }
    )
    monkeypatch.setattr(prompts, "cp1_quality_inputs", lambda _: drifted)
    with pytest.raises(prompts.PromptError, match="gap:stray has no register record"):
        prompts.quality_scope(registers)


# --- task 7.5: bounded projections of the retained steps; pack sources only where spans count --


@pytest.mark.parametrize("step_id", ["narrative", "readiness", "quality"])
def test_a_step_that_checks_no_span_is_refused_the_pack_sources(step_id: str) -> None:
    """R6: these validators match no quote against the pack text, so the pack's SOURCE blocks
    (837 KB on the real pack) are never sent to them; a caller declaring them is refused."""
    pack, _ = readiness_fixture()
    scope = prompts.quality_scope(staged_scope()[1]) if step_id == prompts.QUALITY else None
    schema = STEPS[step_id].schema
    with pytest.raises(prompts.PromptError, match=f"step {step_id} checks no span"):
        prompts.build(step_id, pack, ("filing",), schema, scope=scope)
    user = prompts.build(step_id, pack, (), schema, scope=scope)[1].content
    assert "<<<SOURCE id=" not in user and user.count("<<<CONTEXT id=prepared-pack ") == 1


def test_an_upstream_block_names_its_projection_after_the_retained_content_hash() -> None:
    pack, _ = readiness_fixture()
    up = prompts.UpstreamInput(
        "step:financials", "b" * 64, "projection=narrative-evidence: x", NARRATIVE_EVIDENCE
    )
    user = prompts.build("narrative", pack, (), STEPS["narrative"].schema, upstream=(up,))[
        1
    ].content
    header = f"<<<SOURCE id=step:financials sha256={'b' * 64} projection=narrative-evidence>>>"
    assert f"{header}\nprojection=narrative-evidence: x\n<<<END>>>" in user


def test_the_narrative_and_readiness_contracts_name_what_their_block_holds() -> None:
    narrative = prompts.STEP_CONTRACTS["narrative"]
    assert "id=step:financials" in narrative and "projection=narrative-evidence" in narrative
    assert "evidence_id" in narrative and "cites the supplied spans" not in narrative
    readiness = prompts.STEP_CONTRACTS["readiness"]
    assert "id=step:narrative" in readiness and "projection=readiness-inputs" in readiness
    assert "gap_id" in readiness


# --- 7.6: the narrative and readiness steps state the rules their validators enforce ----------

NARRATIVE_RULES = (
    prompts.REVIEW_PROSE_RULE,
    prompts.NARRATIVE_PARTS_RULE,
    prompts.NARRATIVE_COVERAGE_RULE,
    prompts.NARRATIVE_FUNDING_RULE,
    prompts.NARRATIVE_STORIES_RULE,
    prompts.NARRATIVE_FIGURES_RULE,
)
READINESS_RULES = (
    prompts.REVIEW_PROSE_RULE,
    prompts.READINESS_CONSUMERS_RULE,
    prompts.READINESS_EVIDENCE_RULE,
    prompts.READINESS_STATUS_RULE,
    prompts.READINESS_GAPS_RULE,
)


@pytest.mark.parametrize(
    ("step_id", "rules"), [("narrative", NARRATIVE_RULES), ("readiness", READINESS_RULES)]
)
def test_the_review_steps_letter_their_rules_and_state_each_once(
    step_id: str, rules: tuple[str, ...]
) -> None:
    contract = prompts.STEP_CONTRACTS[step_id]
    lettered = [line[:3] for line in contract.splitlines() if line[1:3] == ". "]
    assert lettered == [f"{letter}. " for letter in "abcdef"[: len(rules)]]
    system = composed(step_id)
    for letter, rule in zip("abcdef"[: len(rules)], rules, strict=True):
        assert f"{letter}. {rule}" in contract
        assert system.count(rule) == 1, rule
    own_only = [r for r in rules if r is not prompts.REVIEW_PROSE_RULE]
    other = "readiness" if step_id == "narrative" else "narrative"
    for step in ("source_readiness", "source_context", "financials", "quality", other):
        assert not [r for r in own_only if r in composed(step)], step
    for step in ("source_readiness", "source_context", "financials", "quality"):
        assert prompts.REVIEW_PROSE_RULE not in composed(step), step


def test_the_prose_rule_matches_what_the_prose_validator_rejects() -> None:
    for text in (" ", "", "Debt rose 12%", "Debt {narrative-evidence:x|US$ m}", "See [x]"):
        with pytest.raises(ValueError):
            ProsePart(text=text)
    assert ProsePart(text=" faces refinancing in FY2025 after the 10-K").text
    assert ProsePart(text="Item 7A and Q3 2025 are read as labels").text
    assert "no braces or square brackets" in prompts.REVIEW_PROSE_RULE
    for text in ("See {x}", "See [1]", "See }"):
        with pytest.raises(ValueError):
            ProsePart(text=text)
    assert ProsePart(text="The 6.50% notes due 2032 and 195 of 195 pages").text
    for phrase in (
        "nonblank",
        "no bare figure",
        "`FY2025`",
        "`10-K`",
    ):
        assert phrase in prompts.REVIEW_PROSE_RULE, phrase


def test_the_parts_rule_matches_the_issues_the_validator_raises() -> None:
    inputs = base_inputs()
    good = populated(inputs)
    assert validate_narrative_review(inputs, good) == ()
    one = good.findings[0]

    def issues_of(**update: tuple[object, ...]) -> tuple[str, ...]:
        changed = one.model_copy(update=update)
        return validate_narrative_review(inputs, good.model_copy(update={"findings": (changed,)}))

    # Batch 6: six findings with no issuer part in any of their three passages.
    assert issues_of(risk_mechanic=one.risk_mechanic[1:]) == (
        "Finding lacks explicit issuer binding: liquidity",
    )
    assert issues_of(credit_implication=(IssuerPart(),)) == (
        "Finding lacks credit reasoning: liquidity",
    )
    assert issues_of(evidence=(IssuerPart(),)) == (
        "Finding lacks prior-register evidence: liquidity",
    )
    unknown = EvidencePart(evidence_id="narrative-evidence:nope")
    assert issues_of(evidence=(*one.evidence, unknown)) == (
        "Unknown narrative evidence: narrative-evidence:nope",
    )
    twice = good.model_copy(update={"findings": (one, one)})
    assert "Duplicate narrative finding identity" in validate_narrative_review(inputs, twice)
    shape = {**one.model_dump(mode="json"), "evidence": [{"kind": "issuer"}] * 100}
    assert Finding.model_validate_json(json.dumps(shape))
    with pytest.raises(ValueError):
        Finding.model_validate_json(json.dumps({**shape, "evidence": [{"kind": "issuer"}] * 101}))
    with pytest.raises(ValueError):
        Finding.model_validate_json(json.dumps({**shape, "evidence": []}))
    for phrase in (
        "1 to 100 parts",
        '{"kind":"prose","text":…}',
        '{"kind":"evidence","evidence_id":…}',
        '{"kind":"issuer"}',
        "A part holding only punctuation or whitespace is a separator and is forbidden",
        "at least one evidence part",
        "at least one issuer part",
        "at least one prose part",
        "`finding_id` is unique",
    ):
        assert phrase in prompts.NARRATIVE_PARTS_RULE, phrase


def test_the_coverage_rule_lists_the_validators_dimensions_and_financial_subset() -> None:
    rule = prompts.NARRATIVE_COVERAGE_RULE
    dimensions = rule.split("dimensions (", 1)[1].split(")", 1)[0].split(", ")
    assert dimensions == [f"`{d}`" for d in _DIMENSIONS]
    financial = rule.split("financial dimension (", 1)[1].split(")", 1)[0].split(", ")
    assert financial == [f"`{d}`" for d in _DIMENSIONS if d in _FINANCIAL]
    for phrase in ("`addressed`", "`not_applicable`", "`data_quality_only`", "exactly the"):
        assert phrase in rule, phrase
    source = files("deploy_vii").joinpath("live", "prompts.py").read_text(encoding="utf-8")
    # `coverage` is also a field name, so only the other names show nothing is hand-copied.
    assert not [d for d in _DIMENSIONS if d != "coverage" and f'"{d}"' in source]
    inputs = base_inputs()
    review = populated(inputs)
    moved = review.coverage[0].model_copy(
        update={"dimension": "leverage", "finding_ids": ("liquidity",)}
    )
    other = review.model_copy(update={"coverage": (moved,)})
    assert "Invalid dimension findings: leverage" in validate_narrative_review(inputs, other)
    na = review.coverage[0].model_copy(update={"status": "not_applicable"})
    issues = validate_narrative_review(inputs, review.model_copy(update={"coverage": (na,)}))
    assert "Inapplicable dimension lacks evidence: liquidity" in issues


@cache
def base_inputs() -> NarrativeInputs:
    return narrative_inputs(*case())


@cache
def funding_case() -> tuple[tuple[Any, ...], NarrativeInputs, str]:
    value = book().model_copy(
        update={
            "statement_lines": (
                bs_line("deposits", "other:customer_deposits", "20", 1, statement="BS"),
            )
        }
    )
    args = case(value)
    inputs = narrative_inputs(*args)
    bs = next(
        r.evidence_id
        for r in inputs.catalogue
        if r.kind == "statement_BS" and "customer_deposits" in r.record_json
    )
    return args, inputs, bs


def with_funding(
    review: NarrativeReview, reviewed: tuple[str, ...], material: tuple[str, ...]
) -> NarrativeReview:
    funding = FundingAssessment(
        status="material_items" if material else "no_material_items",
        reviewed_statement_ids=reviewed,
        material_statement_ids=material,
        rationale=(ProsePart(text="Prior balance sheet evidence needs funding analysis"),),
    )
    return review.model_copy(update={"funding": funding})


def test_the_funding_rule_lists_the_standard_balance_sheet_items_from_the_validator() -> None:
    rule = prompts.NARRATIVE_FUNDING_RULE
    listed = rule.split("standard balance-sheet items (", 1)[1].split(")", 1)[0].split(", ")
    assert listed == [f"`{i}`" for i in (*REQUIRED_ITEMS["BS"], *OPTIONAL_ITEMS["BS"])]
    source = files("deploy_vii").joinpath("live", "prompts.py").read_text(encoding="utf-8")
    for item_id in (*REQUIRED_ITEMS["BS"], *OPTIONAL_ITEMS["BS"]):
        assert f'"{item_id}"' not in source and f"`{item_id}`" not in source, item_id
    for phrase in (
        "`kind=statement_BS`",
        "`line_id` column is not null",
        "`line_kind` is `detail`",
        "`other:`",
        "`material_items`",
        "`unassessed`",
        "every material id",
    ):
        assert phrase in rule, phrase


def test_the_funding_rule_holds_for_a_non_balance_sheet_id_and_a_standard_row() -> None:
    _, inputs, bs = funding_case()
    definition = next(r.evidence_id for r in inputs.catalogue if r.kind == "definition")
    review = populated(inputs)
    # Batch 6: a definition row put in the funding lists.
    wrong = "Funding assessment requires distinct located prior balance-sheet rows"
    issues = validate_narrative_review(inputs, with_funding(review, (definition,), (definition,)))
    assert wrong in issues
    assert validate_narrative_review(inputs, with_funding(review, (bs,), (bs,))) == ()
    standard = next(
        r.evidence_id
        for r in inputs.catalogue
        if r.kind == "statement_BS" and f'"item_id":"{REQUIRED_ITEMS["BS"][0]}"' in r.record_json
    )
    issues = validate_narrative_review(inputs, with_funding(review, (standard,), (standard,)))
    assert f"Funding story requires named non-debt liability detail: {standard}" in issues
    issues = validate_narrative_review(inputs, with_funding(review, (), (bs,)))
    assert "Material funding rows must be part of the reviewed scope" in issues
    assert wrong in validate_narrative_review(inputs, with_funding(review, (bs, bs), (bs,)))


def test_the_stories_rule_admits_the_kinds_the_validator_requires_a_story_for() -> None:
    rule = prompts.NARRATIVE_STORIES_RULE
    for phrase in (
        "`kind=subsequent_event`",
        "`kind=multi_figure_event`",
        "`material_statement_ids`",
        "At most one story",
        "cites that same evidence id",
        "blocks the narrative",
        "empty array",
    ):
        assert phrase in rule, phrase
    args, inputs, bs = funding_case()
    definition = next(r.evidence_id for r in inputs.catalogue if r.kind == "definition")
    kpi = next(r.evidence_id for r in inputs.catalogue if r.kind == "kpi")
    review = populated(inputs)

    def stories(*ids: str) -> NarrativeReview:
        entries = tuple(StoryCoverage(evidence_id=i, finding_ids=("liquidity",)) for i in ids)
        return review.model_copy(update={"stories": entries})

    # Batch 6: stories written for a definition, a statement cell or a KPI.
    for evidence_id in (definition, bs, kpi):
        assert f"Unknown required story: {evidence_id}" in validate_narrative_review(
            inputs, stories(evidence_id)
        )
    funded = with_funding(review, (bs,), (bs,))
    assert validate_narrative_review(inputs, funded) == ()
    report = canonical_narrative(*args, funded)  # no story: Python blocks, no validator issue
    assert report.status == "blocked" and bs in report.required_story_ids
    entry = StoryCoverage(evidence_id=bs, finding_ids=("liquidity",))
    lacking = funded.model_copy(update={"stories": (entry,)})  # finding cites the KPI, not bs
    assert f"Story finding lacks its required evidence: {bs} liquidity" in (
        validate_narrative_review(inputs, lacking)
    )
    twice = funded.model_copy(update={"stories": (entry, entry)})
    assert "Duplicate required-story coverage" in validate_narrative_review(inputs, twice)


def test_a_subsequent_event_is_a_story_kind_the_rule_names() -> None:
    pack, context, financial, definition, binding = case()
    _, event_context = event_case()
    context = context.model_copy(
        update={
            "events": event_context.events,
            "sources": (
                context.sources[0].model_copy(
                    update={
                        "event_scan": "events_identified",
                        "event_ids": (event_context.events[0].event_id,),
                    }
                ),
            ),
        }
    )
    binding = binding.model_copy(update={"source_context_review_sha256": context.content_hash()})
    args = pack, context, financial, definition, binding
    inputs = narrative_inputs(*args)
    event = next(r.evidence_id for r in inputs.catalogue if r.kind == "subsequent_event")
    report = canonical_narrative(*args, populated(inputs))
    assert event in report.required_story_ids
    assert "`kind=subsequent_event`" in prompts.NARRATIVE_STORIES_RULE


# --- 7.6: readiness ---------------------------------------------------------------------------


@cache
def ready_args() -> tuple[Any, ...]:
    return case(ready_case())


@cache
def readiness_case(entries: tuple[str, ...]) -> DownstreamInputs:
    args = ready_args()
    return downstream_inputs(*args, draft(narrative_inputs(*args)), entries)


def review_of(
    inputs: DownstreamInputs, *assessments: ConsumerAssessment
) -> tuple[DownstreamReview, tuple[str, ...]]:
    review = DownstreamReview(inputs_sha256=inputs.content_hash(), consumers=assessments)
    return review, validate_downstream_review(inputs, review)


def requirement(
    key: str,
    status: Literal["sufficient", "limited", "missing"],
    ids: tuple[str, ...],
    *actions: str,
) -> RequirementAssessment:
    return RequirementAssessment(
        requirement=key,
        status=status,
        evidence_ids=ids,
        rationale="Synthetic readiness judgment for the prompt rules",
        actions=actions,
    )


def test_the_consumers_rule_matches_the_validator() -> None:
    inputs = readiness_case(("CP-2A",))
    keys = inputs.consumers[0].requirements
    for phrase in ("`entry`", "last column", "no other entry", "at most once", "unassessed"):
        assert phrase in prompts.READINESS_CONSUMERS_RULE, phrase
    ok = requirement(keys[0], "missing", (), "Obtain the missing source")
    assert review_of(inputs, ConsumerAssessment(entry="CP-2A", requirements=(ok,)))[1] == ()
    twice = ConsumerAssessment(entry="CP-2A", requirements=(ok, ok))
    assert f"Duplicate or unknown requirement: CP-2A {keys[0]}" in review_of(inputs, twice)[1]
    other = ConsumerAssessment(entry="CP-2D")
    assert "Unrequested consumer assessment: CP-2D" in review_of(inputs, other)[1]
    again = ConsumerAssessment(entry="CP-2A")
    assert "Duplicate consumer assessment" in review_of(inputs, again, again)[1]


def test_the_evidence_rule_renders_every_group_key_from_the_validators_table() -> None:
    rule = prompts.READINESS_EVIDENCE_RULE
    rendered = {
        key: groups
        for key, _, groups in (
            text.removeprefix("- ").partition(": ")
            for text in rule.splitlines()
            if text.startswith("- ")
        )
    }
    assert set(rendered) == set(_EVIDENCE_GROUPS)
    for key, groups in _EVIDENCE_GROUPS.items():
        parsed = [set(group.split(" | ")) for group in rendered[key].split("; ")]
        assert parsed == [set(g) for g in groups], key
    source = files("deploy_vii").joinpath("live", "prompts.py").read_text(encoding="utf-8")
    assert not [k for k in _EVIDENCE_GROUPS if f'"{k}"' in source]
    for phrase in ("`kpi:<key>`", "`observation:<register_id>`", "amount` is null", "`kind=gap`"):
        assert phrase in rule, phrase


def test_the_evidence_rule_holds_for_missing_ids_wrong_groups_and_null_values() -> None:
    inputs = readiness_case(("CP-2A",))
    fcf, entity = evidence(inputs, "kpi", "fcf"), evidence(inputs, "entity")
    gap = evidence(inputs, "gap")

    def run(
        key: str, status: Literal["sufficient", "limited", "missing"], *ids: str
    ) -> tuple[str, ...]:
        done = requirement(key, status, ids, "Obtain the missing source amount")
        return review_of(inputs, ConsumerAssessment(entry="CP-2A", requirements=(done,)))[1]

    assert run("cash_flow_metrics", "sufficient", fcf) == ()
    assert run("cash_flow_metrics", "missing") == ()
    assert "Sufficiency requires prior evidence: CP-2A cash_flow_metrics" in (
        run("cash_flow_metrics", "limited")
    )
    wrong = "Incompatible or unavailable dependency evidence: CP-2A cash_flow_metrics"
    assert wrong in run("cash_flow_metrics", "sufficient", entity)
    assert "Invalid requirement evidence: CP-2A cash_flow_metrics" in run(
        "cash_flow_metrics", "sufficient", fcf, fcf
    )
    assert run("cash_flow_metrics", "sufficient", fcf, gap) == ()


def test_a_key_without_groups_needs_a_cited_line_that_is_not_a_gap() -> None:
    inputs = readiness_case(("CP-8",))
    key = inputs.consumers[0].requirements[0]
    assert key not in _EVIDENCE_GROUPS
    entry = inputs.consumers[0].entry
    only_gap = f"Sufficiency requires register evidence: {entry} {key}"
    gap, entity = evidence(inputs, "gap"), evidence(inputs, "entity")

    def run(*ids: str) -> tuple[str, ...]:
        done = requirement(key, "sufficient", ids)
        return review_of(inputs, ConsumerAssessment(entry=entry, requirements=(done,)))[1]

    assert only_gap in run(gap)
    assert run(entity) == ()
    assert "at least one cited line" in prompts.READINESS_EVIDENCE_RULE


def test_a_missing_requirement_still_names_distinct_known_evidence() -> None:
    inputs = readiness_case(("CP-2A",))
    key, fcf = inputs.consumers[0].requirements[0], evidence(inputs, "kpi", "fcf")
    rule = prompts.READINESS_EVIDENCE_RULE
    assert (
        "`evidence_ids` are distinct and from the evidence table" in rule
        and "`missing` may name none" in rule
    )
    for ids in ((fcf, fcf), ("narrative-evidence:nope",)):
        done = requirement(key, "missing", ids, "Obtain the missing source")
        issues = review_of(inputs, ConsumerAssessment(entry="CP-2A", requirements=(done,)))[1]
        assert f"Invalid requirement evidence: CP-2A {key}" in issues


def test_an_empty_dashboard_is_not_sufficient() -> None:
    assert "at least one `kind=kpi` line exists" in prompts.READINESS_STATUS_RULE
    value = book()
    partial = value.addback_disclosure.model_copy(update={"status": "partial"})
    args = case(value.model_copy(update={"addback_disclosure": partial}))
    bare = downstream_inputs(*args, draft(narrative_inputs(*args)), ("CP-2",))
    assert bare.narrative.inputs.scope == "data_quality_only"
    assert not any(r.kind == "kpi" for r in bare.narrative.inputs.catalogue)
    done = requirement("kpi_dashboard", "sufficient", (evidence(bare, "entity"),))
    issues = review_of(bare, ConsumerAssessment(entry="CP-2", requirements=(done,)))[1]
    assert "Complete KPI dashboard has unavailable values: CP-2" in issues


def test_the_story_kinds_the_rule_names_are_evidence_table_headers() -> None:
    for kind in ("subsequent_event", "multi_figure_event"):
        assert kind in KINDS and f"`kind={kind}`" in prompts.NARRATIVE_STORIES_RULE


def test_the_status_rule_requires_actions_and_a_complete_dashboard() -> None:
    inputs = readiness_case(("CP-2",))
    fcf = evidence(inputs, "kpi", "fcf")
    for phrase in ("not `sufficient`", "`actions`", "`kpi_dashboard`", "non-null `amount`"):
        assert phrase in prompts.READINESS_STATUS_RULE, phrase
    limited = requirement("kpi_dashboard", "limited", (fcf,))
    review = ConsumerAssessment(entry="CP-2", requirements=(limited,))
    assert "Incomplete requirement needs action: CP-2 kpi_dashboard" in review_of(inputs, review)[1]
    kpis = inputs.narrative.inputs.ledger.kpis
    assert kpis is not None and any(k.value.amount is None for k in kpis.kpis)
    full = requirement("kpi_dashboard", "sufficient", (fcf,))
    issues = review_of(inputs, ConsumerAssessment(entry="CP-2", requirements=(full,)))[1]
    assert "Complete KPI dashboard has unavailable values: CP-2" in issues


def test_the_gaps_rule_matches_the_validator() -> None:
    inputs = readiness_case(("CP-2A",))
    gap_ids = [g.gap_id for g in inputs.narrative.gaps]
    assert len(gap_ids) >= 2
    entity = evidence(inputs, "entity")

    def scope(
        ids: tuple[str, ...], relevance: Literal["relevant", "not_relevant"], *refs: str
    ) -> GapAssessment:
        return GapAssessment(
            gap_ids=ids,
            relevance=relevance,
            evidence_ids=refs,
            rationale="Synthetic relevance judgment over the named scope",
        )

    def run(*scopes: GapAssessment) -> tuple[str, ...]:
        return review_of(inputs, ConsumerAssessment(entry="CP-2A", gaps=scopes))[1]

    assert run(scope((gap_ids[0],), "relevant", entity)) == ()
    again = run(scope((gap_ids[0],), "relevant"), scope((gap_ids[0], gap_ids[1]), "relevant"))
    assert "Duplicate or unknown gap scope: CP-2A" in again
    assert "Duplicate or unknown gap scope: CP-2A" in run(scope(("nope",), "relevant"))
    assert "Duplicate or unknown gap scope: CP-2A" in run(
        scope((gap_ids[0], gap_ids[0]), "relevant")
    )
    assert "Invalid gap-scope evidence: CP-2A" in run(
        scope((gap_ids[0],), "relevant", entity, entity)
    )
    assert "Excluding gaps requires prior evidence: CP-2A" in run(
        scope((gap_ids[0],), "not_relevant")
    )
    blocking = [
        g
        for g in inputs.narrative.gaps
        if g.severity == "BLOCK" and g.origin in {"context_binding", "context"}
    ]
    for g in blocking:
        issues = run(scope((g.gap_id,), "not_relevant", entity))
        assert "A source-integrity block cannot be excluded: CP-2A" in issues
    for phrase in (
        "`gap_id` column",
        "`narrative_gaps`",
        "`evidence_id` of a gap line is not its `gap_id`",
        "`not_relevant`",
        "`BLOCK`",
        "`context_binding` or `context`",
    ):
        assert phrase in prompts.READINESS_GAPS_RULE, phrase


def test_the_readiness_table_carries_the_columns_its_rules_refer_to() -> None:
    inputs = readiness_case(("CP-2A",))
    lines = evidence_table(inputs.narrative.inputs.catalogue, gap_ids=True)
    header = {
        h.split(" ")[0].removeprefix("kind="): json.loads(h.split("columns=", 1)[1])
        for h in lines
        if h.startswith("kind=")
    }
    assert "key" in header["kpi"] and "amount" in header["kpi"]
    assert {"register_id", "amount"} <= set(header["observation"])
    for kind in ("statement_IS", "statement_CFS", "statement_BS"):
        assert {"line_id", "line_kind", "item_id", "amount"} <= set(header[kind])
    assert header["gap"][:4] == ["evidence_id", "gap_id", "severity", "origin"]
    assert set(KINDS) >= set(header)


def test_the_rules_of_both_review_steps_stay_inside_their_budget() -> None:
    assert sum(len(rule) for rule in NARRATIVE_RULES) < 5400  # characters, about 1,350 tokens
    assert sum(len(rule) for rule in READINESS_RULES) < 4000  # characters, about 1,000 tokens


# --- 7.9: wording the first full proxy chain (batch e1-cp1-7) had to guess ---------------------
# Each sentence states a validator or contract fact once; the tests hold it to the code.


@cache
def retained_texts() -> dict[str, str]:
    """The retained step outputs of the synthetic CP-1 case, by step id (built once)."""
    from tests.product.test_cp1_workflow import staged
    from tests.product.test_execution import step_text

    with tempfile.TemporaryDirectory() as directory:
        store, attempt = staged(Path(directory))
        return {step.step_id: step_text(store, step) for step in attempt.steps}


def stated_once(step_id: str, *phrases: str) -> None:
    system = composed(step_id)
    for phrase in phrases:
        assert system.count(phrase) == 1, (step_id, phrase)
    for other in {"narrative", "readiness", "quality", "business_context"} - {step_id}:
        assert not [p for p in phrases if p in composed(other)], (step_id, other)


def test_the_funding_rule_names_the_intent_the_validator_message_only_hints_at() -> None:
    stated_once(
        "narrative",
        "A material row is a non-debt liability detail line",
        "An equity row, an asset row or `other:long_term_debt` is not a material funding item: "
        "the validator admits such a row, the review must not name it.",
        "Each period's row is its own evidence id, so list the periods you will tell: "
        "a story is required for every id in `material_statement_ids` and for no "
        "unlisted id.",
    )
    # The validator admits a detail row under any `other:` id, whatever it is a row of ...
    value = book().model_copy(
        update={
            "statement_lines": (
                bs_line("ltd", "other:long_term_debt", "20", 1, statement="BS"),
                bs_line("deposits", "other:customer_deposits", "30", 2, statement="BS"),
            )
        }
    )
    args = case(value)
    inputs = narrative_inputs(*args)
    ltd, deposits = (
        next(
            r.evidence_id
            for r in inputs.catalogue
            if r.kind == "statement_BS" and f'"item_id":"other:{name}"' in r.record_json
        )
        for name in ("long_term_debt", "customer_deposits")
    )
    both = with_funding(populated(inputs), (ltd, deposits), (ltd,))
    assert validate_narrative_review(inputs, both) == ()
    # ... and requires a story for exactly the ids listed as material, none for the others.
    assert canonical_narrative(*args, both).required_story_ids == (ltd,)


def test_the_parts_rule_states_separators_and_issuer_rendering_as_python_does_them() -> None:
    stated_once(
        "narrative",
        "A part holding only punctuation or whitespace is a separator and is forbidden "
        "(the validator rejects whitespace but admits a lone `.`, so this is the contract's "
        "rule, not the validator's).",
        "Put the spaces and sentence punctuation around an evidence part in the neighbouring "
        "prose part: the parts are joined with nothing added between them.",
        "An issuer part is replaced in place by the issuer's name, with no possessive or plural "
        "(`For <issuer>, …`).",
    )
    from deploy_vii.narrative_projection import _passage

    with pytest.raises(ValueError):
        ProsePart(text=" ")
    assert ProsePart(text=".").text == "."  # admitted by the validator; forbidden by the contract
    record = next(r for r in base_inputs().catalogue if r.kind == "kpi")
    text, _ = _passage(
        (
            ProsePart(text="For "),
            IssuerPart(),
            ProsePart(text=", liquidity is shown by "),
            EvidencePart(evidence_id=record.evidence_id),
            ProsePart(text="."),
        ),
        "Acme Corp",
        {record.evidence_id: record},
        {},
        {record.evidence_id: "E1"},
        "t",
    )
    assert text == "For Acme Corp, liquidity is shown by [E1]."


def test_the_figures_rule_is_a_lettered_narrative_rule_true_to_prose_and_the_context() -> None:
    assert f"f. {prompts.NARRATIVE_FIGURES_RULE}" in prompts.STEP_CONTRACTS["narrative"]
    stated_once(
        "narrative",
        "The `model_metrics` lines carry no evidence_id, so no evidence part can name one; a "
        "passage may say in prose that they have no evidence id and no more.",
        "A directional comparison of two cited figures (`exceeds`, `rose from` one evidence "
        "part `to` another) is allowed.",
        "A share, ratio or difference you work out is a figure Python did not compute: never "
        "write it, in digits or in words.",
        "As to figures the validator rejects only a digit outside a label",
    )
    # The context: model_metrics rows start with the metric key and carry no evidence id.
    text = upstream_text("narrative", "financials", retained_texts()["financials"])
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("model_metrics: entries="))
    end = next(i for i, line in enumerate(lines) if line.startswith("model_limitations:"))
    assert end > start + 1
    assert all("narrative-evidence:" not in line for line in lines[start:end])
    # prose.check: a directional comparison passes; a derived digit and a spelt-out range fail.
    assert ProsePart(text=", which exceeds ").text
    for bad in ("a 12% share", "Items 10 to 14", "up 3 points"):
        with pytest.raises(ValueError):
            ProsePart(text=bad)


def test_the_readiness_rules_state_the_sufficiency_request_gap_scoping_and_unlabelled_lines() -> (
    None
):
    from deploy_vii.downstream_readiness import _requests

    key = "consumer_specific_cp1_sufficiency"
    requests = _requests(("CP-1A", "CP-6"))
    assert [(r.requirements, r.policy) for r in requests] == [
        ((key,), "consumer_specific_review")
    ] * 2
    assert key not in _EVIDENCE_GROUPS
    stated_once(
        "readiness",
        "A consumer whose `policy` is `consumer_specific_review` (for example CP-1A or CP-6) has "
        "the one requirement `consumer_specific_cp1_sufficiency`: judge whether the cited CP-1 "
        "evidence suffices for that consumer's own use; it has no group, so one cited line that "
        "carries a tag and is not a `kind=gap` line is enough for `limited` or `sufficient`.",
        "A `kind=computation` line shows `operation`, `amount` and "
        "`status` but no label: recognise one by its `operation` and by an `amount` equal to a "
        "dashboard KPI's.",
        "A gap left out of every scope keeps that consumer `not_ready` (its action reads "
        '"Assess all retained gaps for this consumer"). The completion budget may not cover '
        "every gap of every consumer, so scope those that matter to each consumer by class: "
        "the `BLOCK` gaps first, then the gaps matched to that consumer's metrics. One scope "
        "may list many gap_ids.",
    )
    assert KINDS["computation"][0] == ("operation", "amount", "status")
    # A tagged, non-gap line is enough for the one request (the validator's no-group branch).
    inputs = readiness_case(("CP-1A",))
    tagged = next(
        r.evidence_id for r in inputs.narrative.inputs.catalogue if r.kind == "source_period"
    )
    _, issues = review_of(
        inputs,
        ConsumerAssessment(
            entry="CP-1A", requirements=(requirement(key, "sufficient", (tagged,)),)
        ),
    )
    assert issues == ()


def test_an_unscoped_gap_keeps_the_consumer_not_ready_whatever_else_is_assessed() -> None:
    from deploy_vii.downstream_readiness import _assess_consumers

    inputs = readiness_case(("CP-1A",))
    key = "consumer_specific_cp1_sufficiency"
    kpi = next(r.evidence_id for r in inputs.narrative.inputs.catalogue if r.kind == "kpi")
    review, issues = review_of(
        inputs,
        ConsumerAssessment(entry="CP-1A", requirements=(requirement(key, "sufficient", (kpi,)),)),
    )
    assert issues == ()
    (row,) = _assess_consumers(inputs, review)
    assert row.unassessed_gap_ids and row.status == "not_ready"
    assert "Assess all retained gaps for this consumer" in row.actions


def test_the_quality_findings_rule_says_the_module_status_is_not_a_defect_to_record() -> None:
    stated_once(
        "quality",
        "Add no finding for the CONTEXT block's `module_status` or `source_gate`: Python "
        "already sets the QA status from them (`blocked` or a failed gate forces Blocked), so "
        "the inputs carry them.",
    )
    inputs = QualityInputs(
        artifact_sha256="a" * 64,
        coverage_policy="p",
        claims=(),
        coverage=(CoverageField(field_id="f", present=True, rationale="Synthetic slot"),),
        source_gate="pass",
        module_status="blocked",
        references=(),
        ceilings=(),
    )
    report = assess_quality(
        inputs, QualityReview(inputs_sha256=inputs.content_hash(), claims=(), findings=())
    )
    assert report.confidence.qa_status == "Blocked" and report.findings == ()


def test_the_cp1a_rules_state_the_label_forms_conflicts_and_behaviour_flags() -> None:
    from tests.product.test_business_context import (
        QUOTE,
        changed,
        governance,
        issues_of,
        submission_fixture,
    )

    stated_once(
        "business_context",
        "A range or list of items uses a joiner the validator admits: `Items 10-14`, "
        "`Items 7, 7A`, `Items 7/7A` or `Items 7 and 8`; a range written with the word `to` "
        "is read as a bare figure and rejected.",
        "A source that contradicts itself is one `conflicts` entry quoting both spans: the "
        "validator needs two citations, not two sources.",
        "When no behaviour type fits, set `behaviour_type` to `other`; a flag "
        "informs a dimension's score only when it names a `dimension`, so set one if the row bears "
        "on it; a type you chose by reading rather than the source naming it is an "
        "Analyst Interpretation row.",
    )
    for good in ("Items 10-14", "Items 7, 7A", "Items 7/7A", "Items 7 and 8"):
        assert bare_figures(good) == (), good
    assert bare_figures("Items 10 to 14") == ("14",)
    # Both spans of one source are a valid conflict (the validator counts citations).
    base = submission_fixture()
    twin = QUOTE.model_copy(update={"quote": "cash"})
    assert twin.source_id == QUOTE.source_id
    one_source = Conflict(
        conflict_id="self-contradiction",
        conflict="One source gives two descriptions of cash",
        materiality="Minor",
        downstream_impact="CP-1 keeps both descriptions",
        citations=(QUOTE, twin),
    )
    assert issues_of(changed(base, conflicts=(one_source,))) == ()
    # `other` with a dimension and the Analyst Interpretation tag is accepted.
    flag = base.governance_and_sponsor[1].model_copy(
        update={
            "behaviour_type": "other",
            "dimension": "Disclosure transparency",
            "category": "Analyst Interpretation",
            "citations": (QUOTE,),
        }
    )
    assert flag.kind == "behaviour_flag"
    assert issues_of(changed(base, governance_and_sponsor=(governance(), flag))) == ()


# --- 7.11: what E1 batch e1-cp1-13 (GPT-6.1 Sol at high) had to guess -------------------------

ALL_STEPS = (
    "source_readiness",
    "source_context",
    "financials",
    "narrative",
    "readiness",
    "quality",
    "business_context",
)


def test_the_financials_step_states_the_bound_scope_rule_once_as_rule_i() -> None:
    rule = prompts.BOUND_SCOPE_RULE
    contract = prompts.STEP_CONTRACTS["financials"]
    assert f"h. {prompts.SEGMENT_ALLOCATION_RULE}\ni. {rule}" in contract
    assert composed("financials").count(rule) == 1
    for step_id in set(ALL_STEPS) - {"financials"}:
        assert rule not in composed(step_id), step_id
    for phrase in (
        "`currency`, `unit`, `accounting_basis` and `entity_perimeter` verbatim",
        "step:source_context `scopes` entry",
        "into every one of its `periods`",
        "exactly equal",
        "is a rejection",
    ):
        assert phrase in rule, phrase
    # The scopes the rule points at are in the block the financials prompt shows, whole.
    assert PROJECTIONS[("financials", "source_context")] == FULL


def _one_character_off(text: str) -> str:
    return text[:-1] + ("x" if text[-1] != "x" else "y")


def test_a_one_character_perimeter_difference_is_rejected_with_the_rules_two_messages() -> None:
    """Book against scope: only the binding message; book against period: only the mixed one."""
    pack, context, financial, binding = context_case()
    assert validate_financial_context(pack, context, financial, binding) == ()
    (source,) = context.sources
    scopes = tuple(
        s.model_copy(update={"entity_perimeter": _one_character_off(s.entity_perimeter)})
        for s in source.scopes
    )
    changed = context.model_copy(
        update={"sources": (source.model_copy(update={"scopes": scopes}),)}
    )
    rebound = binding.model_copy(update={"source_context_review_sha256": changed.content_hash()})
    (value,) = financial.books
    assert validate_financial_context(pack, changed, financial, rebound) == tuple(
        f"No matching entity/date/basis source scope: {value.book_id} {p.period_id} S1"
        for p in value.periods
    )
    first, *rest = value.periods
    off = first.model_copy(update={"entity_perimeter": _one_character_off(first.entity_perimeter)})
    mixed = financial.model_copy(
        update={"books": (value.model_copy(update={"periods": (off, *rest)}),)}
    )
    assert validate_financial_review(pack, mixed) == (
        f"{value.book_id}: Mixed units, currency, accounting basis or perimeter: {first.period_id}",
    )


def test_the_page_and_hyphen_rules_sit_once_in_the_preamble_every_step_receives() -> None:
    """`CITATION_RULE` does not reach `financials`, where batch 13 cited `page:95` for text in
    the `page:94` span and wrapped `first-` onto a new line; the preamble does."""
    for rule in (prompts.PAGE_SPAN_RULE, prompts.HYPHEN_COPY_RULE):
        assert rule not in prompts.CITATION_RULE
        assert not [s for s, contract in prompts.STEP_CONTRACTS.items() if rule in contract]
        for step_id in ALL_STEPS:
            assert composed(step_id).count(rule) == 1, (step_id, rule)
    assert "`locator=` marker that opens that span, above the text" in prompts.PAGE_SPAN_RULE
    assert "`first-priority`, never `first-` then a line break" in prompts.HYPHEN_COPY_RULE


def test_the_page_rule_is_true_of_how_a_span_is_rendered() -> None:
    """Each span is one `locator=<locator> | <text>` entry: the marker opens the span and its
    text, line breaks included, follows it until the next marker."""
    pack = paged_pack(range(94, 96))
    (source,) = pack.sources
    spans = (
        Span(locator="page:94", text="Total revenue\nReconciliation"),
        Span(locator="page:95", text="Next page text"),
    )
    pack = pack.model_copy(update={"sources": (source.model_copy(update={"spans": spans}),)})
    _, body = prompts._source_body(pack, source.source_id)
    assert body == (
        "locator=page:94 | Total revenue\nReconciliation\nlocator=page:95 | Next page text"
    )


def test_the_hyphen_guidance_is_a_quote_the_matcher_accepts_from_a_wrapped_span() -> None:
    span = "and\nfuture first-\npriority lien obligations"
    assert quoted("future first-priority lien obligations", span)
    assert not quoted("future first priority lien obligations", span)  # the hyphen is kept
