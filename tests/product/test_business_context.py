"""CP-1A business context (task 7.2): the thin contract, its validator and the composed r14
registers. Synthetic data only: the fixture pack is one invented text line."""

import json
import random
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.business_context import (
    DIMENSIONS,
    NOT_SCORABLE,
    REGISTERS,
    REQUIRED_REGISTERS,
    BusinessContextReport,
    BusinessContextSubmission,
    BusinessLine,
    CompanyFact,
    Conflict,
    Consumer,
    CreditTranslation,
    DisclosureItem,
    Event,
    Gap,
    GovernanceItem,
    OperatingDriver,
    Owner,
    Quote,
    SourceUse,
    Transaction,
    business_context,
    cp1a_consumers,
    cp1a_module,
    governance_sponsor_score,
    register_rule_issues,
    spelled,
    validate_business_context,
)
from deploy_vii.contracts import Citation, Fact
from deploy_vii.live.schema import relax, schema_relaxations, strict_copy, strict_schema
from deploy_vii.preparation import PreparedPack
from deploy_vii.prose import bare_figures
from tests.product.test_live_submission import paged_pack
from tests.product.test_readiness import readiness_fixture

QUOTE = Quote(source_id="filing", locator="line:1", quote="Synthetic issuer FY2025 cash")
R14_PATH = "reference/deploy-v-r14/skills/cp-1a-business-transaction-fact-pack/SKILL.md"


def pack_fixture() -> PreparedPack:
    return readiness_fixture()[0]


def governance(**changes: object) -> GovernanceItem:
    row = GovernanceItem(
        kind="governance_topic",
        topic="Reporting cadence",
        documented_fact="An annual figure is reported",
        direction="Supportive",
        behaviour_type=None,
        amount_funding_source=None,
        legal_capacity_link=None,
        dimension="Reporting quality",
        risk_mechanic="Transparent reporting supports lender monitoring",
        credit_implication="Higher committee confidence in the reported period",
        evidence_quality="Medium",
        category="Documentary Fact",
        citations=(QUOTE,),
        limitation=None,
    )
    return row.model_copy(update=changes)


def submission_fixture(pack: PreparedPack | None = None) -> BusinessContextSubmission:
    """A valid synthetic submission: every list populated except capital allocation,
    acquisitions and conflicts (which compose as explicit empty rows)."""
    pack = pack or pack_fixture()
    return BusinessContextSubmission(
        sources=(
            SourceUse(
                source_id="filing",
                source_class="unknown",
                quality="Low",
                period="FY2025",
                entity_covered="Synthetic issuer",
                data_supplied="One synthetic cash line",
                use="Identity and period only",
                citations=(QUOTE,),
                limitation="Synthetic fixture; not an issuer filing",
            ),
        ),
        company=(
            CompanyFact(
                aspect="business_description",
                text="A synthetic issuer used for protocol tests",
                category="Documentary Fact",
                citations=(QUOTE,),
                limitation=None,
            ),
            CompanyFact(
                aspect="country",
                text="Not stated in the source",
                category="Insufficient Information",
                citations=(),
                limitation="The fixture names no country",
            ),
            CompanyFact(
                aspect="sector",
                text="Synthetic test sector",
                category="Analyst Interpretation",
                citations=(QUOTE,),
                limitation=None,
            ),
        ),
        business_lines=(
            BusinessLine(
                name="Synthetic operations",
                revenue_mix="Revenue mix is not disclosed",
                period="FY2025",
                category="Insufficient Information",
                citations=(),
                limitation="No segment table in the fixture",
            ),
        ),
        owners=(
            Owner(
                owner="Public shareholders",
                control="No controlling holder is disclosed",
                economic_interest="Not disclosed",
                credit_relevance="Ownership does not change creditor control here",
                evidence_quality="Low",
                credit_mechanic="No sponsor extraction channel is evidenced",
                credit_implication="Neutral for default risk in this synthetic case",
                category="Management Language",
                citations=(QUOTE,),
                limitation=None,
            ),
        ),
        operating_drivers=(
            OperatingDriver(
                driver="Cash balance",
                measure=None,
                period="FY2025",
                status="Not disclosed",
                credit_relevance="Liquidity cannot be judged from the fixture",
                category="Insufficient Information",
                citations=(),
                limitation="The fixture states no operating metric",
            ),
        ),
        transactions=(
            Transaction(
                transaction="No transaction is described",
                status="Insufficient Information",
                credit_relevance="No transaction dependency can be assessed",
                category="Insufficient Information",
                citations=(),
                limitation="No transaction document in the pack",
            ),
        ),
        events=(
            Event(
                date_window="FY2025",
                event="Fiscal year reported",
                credit_relevance="Sets the reporting period for every figure",
                status="Completed",
                category="Documentary Fact",
                citations=(QUOTE,),
                limitation=None,
            ),
        ),
        governance_and_sponsor=(
            governance(),
            governance(
                kind="behaviour_flag",
                topic="Distributions",
                documented_fact="No distribution is described",
                direction="Insufficient Information",
                behaviour_type="distribution",
                amount_funding_source="Not disclosed",
                legal_capacity_link="Insufficient Information",
                dimension="Shareholder extraction risk",
                evidence_quality="Insufficient",
                category="Insufficient Information",
                citations=(),
                limitation="No distribution evidence in the pack",
            ),
        ),
        capital_allocation=(),
        acquisitions=(),
        disclosure_items=(
            DisclosureItem(
                item="Debt schedule",
                available="No",
                detail="No debt schedule in the fixture",
                credit_relevance="Refinancing analysis needs the maturity profile",
                severity="Material",
                follow_up="Obtain the debt footnote",
                citations=(),
            ),
        ),
        credit_translations=(
            CreditTranslation(
                theme="Key Uncertainties",
                evidence="The fixture reports one cash line.",
                risk_mechanic="Thin disclosure limits liquidity visibility.",
                credit_implication="Monitoring posture stays cautious.",
                confidence="Low",
                countervailing_conflict_ids=(),
                citations=(QUOTE,),
                limitation=None,
            ),
        ),
        conflicts=(),
        gaps=(
            Gap(
                gap="No business segment disclosure",
                why_it_matters="Revenue durability cannot be judged",
                affected_analysis="Revenue and business mix",
                severity="Material",
                action="Obtain the segment note",
            ),
        ),
        consumers=tuple(
            Consumer(
                module_id=module_id,
                status="READY_WITH_LIMITATIONS",
                handoff_item="Business context with stated gaps",
                why_it_matters="Frames the credit synthesis",
                gap="Segment and transaction gaps",
                required_action="Carry the CP-1A gaps forward",
            )
            for module_id in cp1a_consumers(pack)
        ),
    )


def changed(submission: BusinessContextSubmission, **lists: object) -> BusinessContextSubmission:
    return submission.model_copy(update=lists)


def cp1_fact(pack: PreparedPack) -> Fact:
    """A synthetic accepted CP-1 figure (cited to the fixture line) that CP-1A may reference."""
    source = pack.sources[0]
    assert source.sha256
    citation = Citation(
        source_id="filing", source_sha256=source.sha256, locator="line:1", quote="cash"
    )
    return Fact(
        fact_id="T4.10.liquidity.FY2025",
        label="Liquidity",
        table_id="T4.10",
        row_id="liquidity",
        field="FY2025",
        amount=Decimal("1100"),
        unit="MILLIONS",
        currency="USD",
        period="FY2025",
        citations=(citation,),
    )


# --- acceptance and the composed registers --------------------------------------------------


def test_a_valid_submission_composes_every_r14_register_with_its_columns() -> None:
    pack, submission = pack_fixture(), submission_fixture()
    assert validate_business_context(pack, submission) == ()
    report = business_context(pack, submission)
    tables = {table.table_id: table for table in report.tables}
    assert len(REQUIRED_REGISTERS) == 22
    assert set(REQUIRED_REGISTERS) <= tables.keys()
    assert "cp1a.cp_model_snapshot_fields" in tables  # r14's conditional table, every run
    assert tables["company_description"].rows[0].row_id == "company"
    assert [c.label for c in tables["T2D.6"].columns] == [
        "Acquisition / Period",
        "Source-Supported Fact",
        "Funding Mix",
        "EBITDA / Pro Forma Basis",
        "Integration Evidence",
        "Leverage / Liquidity Effect",
        "Risk Mechanic",
        "Credit Implication",
        "Source Trace",
        "Limitation",
    ]
    assert [c.label for c in tables["credit_translation"].columns] == [
        "Evidence",
        "Risk mechanic",
        "Credit implication",
        "Confidence",
        "Limitation",
    ]
    assert report.schema_version == "business-context/1"
    assert register_rule_issues(report) == ()


def test_the_r14_register_ids_are_the_coverage_maps_required_ids() -> None:
    coverage = json.loads(open("docs/methodology/r14-coverage.json", encoding="utf-8").read())
    entry = next(m for m in coverage["modules"] if m["module_id"] == "CP-1A")
    assert sorted(REQUIRED_REGISTERS) == sorted(entry["artifact_contract"]["required_table_ids"])
    assert entry["artifact_contract"]["conditional_table_ids"] == ["cp1a.cp_model_snapshot_fields"]
    assert entry["source_path"] == R14_PATH


def test_python_owns_ids_names_and_dates_and_categories_label_the_fact_cells() -> None:
    pack = pack_fixture()
    report = business_context(pack, submission_fixture())
    cells = {fact.fact_id: fact for fact in report.facts}
    assert cells["company_description.company.issuer"].text == "Synthetic issuer"  # the run's
    assert cells["company_description.company.sector"].text == (
        "Synthetic test sector [Analyst Interpretation]"
    )
    assert cells["company_description.company.country"].text == (
        "Not stated in the source [Insufficient Information]"
    )
    assert cells["ownership_register.r01.owner_class"].text == (
        "Public shareholders [Management Language]"
    )
    assert cells["T2D.1.r01.source_document_name"].text == pack.sources[0].name
    assert cells["conflict_log.none.resolution"].status == "not_applicable"  # none logged
    assert cells["T2D.5.none.capital_allocation_item"].status == "missing"  # an explicit gap
    assert cells["operating_model.r01.measure"].status == "missing"  # r14: null, never 0
    snapshot = {
        fact.row_id: fact for fact in report.facts if fact.table_id.startswith("cp1a.") and
        fact.field == "status"
    }  # fmt: skip
    assert snapshot["issuer_name"].text == "READY"
    assert snapshot["country"].text == "GAP"  # an Insufficient Information row is not located
    assert snapshot["sector"].text == "READY"
    assert cells["cp1a.cp_model_snapshot_fields.sector.as_of"].text == "2026-10-21"
    assert "No capital allocation risk table rows in the CP-1A submission" in report.limitations
    assert "Gap (Material): No business segment disclosure" in report.limitations


def test_the_module_is_a_valid_candidate_with_run_text_claims() -> None:
    pack = pack_fixture()
    report = business_context(pack, submission_fixture())
    module = cp1a_module(report, (), 0)
    assert module.module_id == "CP-1A" and module.status == "candidate"
    assert module.claims[0].text.startswith("The fixture reports one cash line.")
    assert module.inputs[-1].input_id == "business-context-submission"


# --- rejections, rule by rule ---------------------------------------------------------------


def issues_of(submission: BusinessContextSubmission) -> tuple[str, ...]:
    return validate_business_context(pack_fixture(), submission)


def test_every_source_is_assessed_exactly_once() -> None:
    base = submission_fixture()
    twice = changed(base, sources=base.sources * 2)
    assert "cp1a.source_ids_unique: filing is assessed more than once" in issues_of(twice)
    assert "Assess every prepared source exactly once" in issues_of(changed(base, sources=()))


def test_citations_follow_the_cp0_rules() -> None:
    base = submission_fixture()
    wrong = QUOTE.model_copy(update={"locator": "line:9"})
    unknown = QUOTE.model_copy(update={"source_id": "elsewhere"})
    events = (base.events[0].model_copy(update={"citations": (wrong,)}),)
    found = issues_of(changed(base, events=events))
    assert any(i.startswith("events[0]: Quote/locator mismatch: no locator line:9") for i in found)
    events = (base.events[0].model_copy(update={"citations": (unknown,)}),)
    assert "Unavailable or changed source: elsewhere" in issues_of(changed(base, events=events))


def test_every_text_field_is_run_text() -> None:
    base = submission_fixture()
    company = (
        base.company[0].model_copy(update={"text": "Revenue was 11,456 in the year"}),
        *base.company[1:],
    )
    found = issues_of(changed(base, company=company))
    assert "company[0].text: Bare figure: 11,456" in found
    lines = (base.business_lines[0].model_copy(update={"limitation": "Only 3 segments"}),)
    assert "business_lines[0].limitation: Bare figure: 3" in issues_of(
        changed(base, business_lines=lines)
    )
    gaps = (base.gaps[0].model_copy(update={"action": "See {T4.10.missing|x}"}),)
    assert "gaps[0].action: Unresolved reference: T4.10.missing" in issues_of(
        changed(base, gaps=gaps)
    )


def test_a_figure_reference_resolves_only_against_the_cp1_facts_offered() -> None:
    pack = pack_fixture()
    fact = cp1_fact(pack)
    base = submission_fixture(pack)
    text = "Liquidity was {T4.10.liquidity.FY2025|US$ m} at FY2025."
    translations = (base.credit_translations[0].model_copy(update={"evidence": text}),)
    submission = changed(base, credit_translations=translations)
    assert "credit_translations[0].evidence: Unresolved reference: T4.10.liquidity.FY2025" in (
        issues_of(submission)
    )
    assert validate_business_context(pack, submission, (fact,)) == ()
    report = business_context(pack, submission, (fact,))
    cells = {f.fact_id: f for f in report.facts}
    assert cells["credit_translation.r01.evidence"].text == (
        f"Liquidity was {spelled(fact)} at FY2025."
    )
    assert spelled(fact) == "1,100 US$ m"
    copied = cells["T4.10.liquidity.FY2025"]
    assert copied.table_id == "cp1_references" and copied.amount == fact.amount
    assert copied.citations == fact.citations
    assert report.claims[0].text.startswith(text)  # the claim keeps the reference
    cp1a_module(report, (), 0)  # and resolves inside the module (prose_issues at validation)


def test_a_chip_to_a_numeric_fact_is_refused() -> None:
    pack = pack_fixture()
    base = submission_fixture(pack)
    gaps = (base.gaps[0].model_copy(update={"action": "Check [T4.10.liquidity.FY2025]"}),)
    found = validate_business_context(pack, changed(base, gaps=gaps), (cp1_fact(pack),))
    assert any("needs a figure reference" in issue for issue in found)


def test_consumers_are_exactly_the_context_list_and_unique() -> None:
    pack = pack_fixture()
    base = submission_fixture(pack)
    expected = cp1a_consumers(pack)
    assert expected[0] == "CP-2" and "CP-MODEL" in expected  # CP-MODEL is always judged
    twice = changed(base, consumers=base.consumers + base.consumers[:1])
    assert "cp1a.downstream_modules_unique: CP-2 is judged more than once" in issues_of(twice)
    short = changed(base, consumers=base.consumers[1:])
    assert any(i.startswith("Judge exactly the consumers listed") for i in issues_of(short))


def test_credit_translation_rules() -> None:
    base = submission_fixture()
    row = base.credit_translations[0]
    empty = row.model_copy(update={"evidence": "n/a", "risk_mechanic": "TBD"})
    found = issues_of(changed(base, credit_translations=(empty,)))
    assert any(i.startswith("cp1a.credit_translation_has_evidenced_row") for i in found)
    uncited = row.model_copy(update={"citations": ()})
    assert any(
        "cites its evidence" in i for i in issues_of(changed(base, credit_translations=(uncited,)))
    )
    with pytest.raises(ValueError, match="confidence"):
        BusinessContextSubmission.model_validate_json(
            submission_fixture()
            .model_dump_json()
            .replace('"confidence":"Low"', '"confidence":"Sure"')
        )


def test_the_semantic_rules_hold_on_the_composed_registers_too() -> None:
    report = business_context(pack_fixture(), submission_fixture())

    def tampered(fact_id: str, text: str) -> BusinessContextReport:
        facts = tuple(
            f.model_copy(update={"text": text}) if f.fact_id == fact_id else f for f in report.facts
        )
        return report.model_copy(update={"facts": facts})

    assert register_rule_issues(tampered("credit_translation.r01.confidence", "Sure"))[
        0
    ].startswith("cp1a.credit_translation_confidence_enum")
    assert register_rule_issues(tampered("credit_translation.r01.evidence", "n/a"))[0].startswith(
        "cp1a.credit_translation_has_evidenced_row"
    )
    rows = report.tables[0].rows
    duplicated = report.model_copy(
        update={
            "tables": (
                report.tables[0].model_copy(update={"rows": rows + rows}),
                *report.tables[1:],
            )
        }
    )
    assert register_rule_issues(duplicated)[0].startswith("cp1a.source_ids_unique")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("We recommend the secured notes", "instrument recommendation"),
        ("The issuer ranks above its peers on margin", "peer ranking"),
        ("An expected recovery near par for secured lenders", "recovery conclusion"),
    ],
)
def test_prohibited_conclusions_are_rejected(text: str, kind: str) -> None:
    base = submission_fixture()
    row = base.credit_translations[0].model_copy(update={"credit_implication": text})
    found = issues_of(changed(base, credit_translations=(row,)))
    assert any(f"prohibited conclusion ({kind})" in issue for issue in found), found


def test_a_recovery_mechanic_is_not_a_prohibited_conclusion() -> None:
    base = submission_fixture()
    row = base.credit_translations[0].model_copy(
        update={"credit_implication": "Weaker recovery prospects raise loss given default"}
    )
    assert issues_of(changed(base, credit_translations=(row,))) == ()


def test_the_five_categories_set_the_evidence_rules() -> None:
    base = submission_fixture()
    owner = base.owners[0].model_copy(update={"citations": ()})
    assert "owners[0]: a Management Language row cites located evidence" in issues_of(
        changed(base, owners=(owner,))
    )
    line = base.business_lines[0].model_copy(update={"limitation": None})
    assert "business_lines[0]: an Insufficient Information row states its limitation" in issues_of(
        changed(base, business_lines=(line,))
    )


def test_governance_rows_follow_their_kind() -> None:
    base = submission_fixture()
    flag = base.governance_and_sponsor[1].model_copy(update={"behaviour_type": None})
    found = issues_of(changed(base, governance_and_sponsor=(base.governance_and_sponsor[0], flag)))
    assert "governance_and_sponsor[1]: a behaviour flag states behaviour_type" in found
    topic = governance(direction="Extraction-Oriented", amount_funding_source="Cash")
    found = issues_of(changed(base, governance_and_sponsor=(topic,)))
    assert (
        "governance_and_sponsor[0]: a governance topic leaves amount_funding_source null" in found
    )
    assert any("Extraction-Oriented is a behaviour category" in i for i in found)


def test_conflicts_cite_both_spans_and_translations_name_known_conflicts() -> None:
    base = submission_fixture()
    conflict = Conflict(
        conflict_id="cash-label",
        conflict="Two spans describe cash differently",
        materiality="Minor",
        downstream_impact="CP-1 keeps both labels",
        citations=(QUOTE,),
    )
    row = base.credit_translations[0].model_copy(
        update={"countervailing_conflict_ids": ("cash-label", "other")}
    )
    found = issues_of(changed(base, conflicts=(conflict,), credit_translations=(row,)))
    assert "conflicts[0]: a conflict cites each conflicting span (at least two citations)" in found
    assert "credit_translations[0]: unknown conflict_id other" in found
    two = conflict.model_copy(
        update={"citations": (QUOTE, QUOTE.model_copy(update={"quote": "cash"}))}
    )
    row = row.model_copy(update={"countervailing_conflict_ids": ("cash-label",)})
    accepted = changed(base, conflicts=(two,), credit_translations=(row,))
    assert issues_of(accepted) == ()
    report = business_context(pack_fixture(), accepted)
    cells = {f.fact_id: f for f in report.facts}
    assert cells["conflict_log.r01.resolution"].text == "Logged, not reconciled"
    assert cells["T2D.9.r01.countervailing_evidence"].text == "Two spans describe cash differently"


def test_company_states_each_aspect_once_and_text_is_never_blank() -> None:
    base = submission_fixture()
    found = issues_of(changed(base, company=base.company[:2]))
    assert "company: state sector exactly once" in found
    blank = base.gaps[0].model_copy(update={"why_it_matters": "  "})
    assert "gaps[0].why_it_matters: empty text" in issues_of(changed(base, gaps=(blank,)))


def test_an_absence_claim_against_retained_pages_is_rejected() -> None:
    pack = paged_pack(range(1, 30), source_id="filing")
    base = submission_fixture(pack)
    span = Quote(source_id="filing", locator="page:3", quote="Page 3 text")
    sources = (base.sources[0].model_copy(update={"citations": (span,)}),)
    rows = {
        "company": tuple(
            c.model_copy(update={"citations": (span,) if c.citations else ()}) for c in base.company
        ),
        "owners": (base.owners[0].model_copy(update={"citations": (span,)}),),
        "events": (base.events[0].model_copy(update={"citations": (span,)}),),
        "governance_and_sponsor": (
            base.governance_and_sponsor[0].model_copy(update={"citations": (span,)}),
            base.governance_and_sponsor[1],
        ),
        "credit_translations": (
            base.credit_translations[0].model_copy(
                update={"citations": (span,), "limitation": "Pages 5-9 are missing from the pack"}
            ),
        ),
    }
    found = validate_business_context(pack, changed(base, sources=sources, **rows))
    assert any(i.startswith("Absence claim contradicts extraction coverage") for i in found), found


# --- the governance score (T2D.8) -----------------------------------------------------------


def scored(*rows: GovernanceItem) -> dict[str, str]:
    return {item.dimension: item.score for item in governance_sponsor_score(rows).dimensions}


def test_dimension_scores_follow_the_r14_rubric() -> None:
    adverse = governance(direction="Creditor-Adverse")
    extraction = governance(kind="behaviour_flag", direction="Extraction-Oriented",
                            behaviour_type="distribution", amount_funding_source="Debt",
                            legal_capacity_link="Indenture")  # fmt: skip
    assert scored(governance())["Reporting quality"] == "1"
    assert scored(adverse, extraction)["Reporting quality"] == "5"
    assert scored(governance(), adverse)["Reporting quality"] == "3"  # support beside adverse
    assert scored(governance(direction="Neutral"))["Reporting quality"] == "3"
    assert scored(governance(evidence_quality="Insufficient"))["Reporting quality"] == NOT_SCORABLE
    assert scored(governance(dimension=None))["Reporting quality"] == NOT_SCORABLE


def test_the_composite_needs_four_dimensions_unless_a_high_risk_action_is_documented() -> None:
    three = [governance(dimension=d) for d in DIMENSIONS[:3]]
    score = governance_sponsor_score(three)
    assert (score.composite, score.risk_level, score.scored) == (
        NOT_SCORABLE,
        "Insufficient Information",
        3,
    )
    severe = governance(
        dimension=DIMENSIONS[0], direction="Creditor-Adverse", evidence_quality="High"
    )
    score = governance_sponsor_score([severe])
    assert (score.composite, score.risk_level) == (NOT_SCORABLE, "High")
    four = [governance(dimension=d) for d in DIMENSIONS[:4]]
    assert governance_sponsor_score(four).risk_level == "Low"
    mixed = [*four, governance(dimension=DIMENSIONS[5], direction="Mixed")]
    score = governance_sponsor_score(mixed)
    assert (score.composite, score.risk_level) == ("3", "Medium")


def test_a_high_risk_documented_action_needs_no_dimension_label() -> None:
    # r14's override is the documented action itself: a flag the model left without a dimension
    # (so it scores none) still sets the level High when adverse and on High evidence.
    flag = governance(kind="behaviour_flag", direction="Extraction-Oriented",
                      behaviour_type="dividend recap", amount_funding_source="New term loan",
                      legal_capacity_link="Restricted payments basket", evidence_quality="High",
                      dimension=None)  # fmt: skip
    score = governance_sponsor_score([flag])
    assert (score.scored, score.composite, score.risk_level) == (0, NOT_SCORABLE, "High")
    unsupported = flag.model_copy(update={"category": "Insufficient Information"})
    assert governance_sponsor_score([unsupported]).risk_level == "Insufficient Information"


DIRECTIONS = ("Supportive", "Neutral", "Mixed", "Creditor-Adverse", "Insufficient Information")
QUALITIES = ("High", "Medium", "Low", "Insufficient")


@given(
    st.lists(
        st.tuples(
            st.sampled_from((*DIMENSIONS, None)),
            st.sampled_from(DIRECTIONS),
            st.sampled_from(QUALITIES),
        ),
        max_size=12,
    ),
    st.randoms(use_true_random=False),
)
def test_the_score_is_order_free_and_the_composite_is_the_worst_scored_dimension(
    specs: list[tuple[Any, str, str]], rng: random.Random
) -> None:
    rows = [governance(dimension=d, direction=r, evidence_quality=q) for d, r, q in specs]
    score = governance_sponsor_score(rows)
    shuffled = list(rows)
    rng.shuffle(shuffled)
    again = governance_sponsor_score(shuffled)
    assert [d.score for d in again.dimensions] == [d.score for d in score.dimensions]
    assert (again.composite, again.risk_level) == (score.composite, score.risk_level)
    numbers = [d.score for d in score.dimensions if d.score != NOT_SCORABLE]
    if len(numbers) >= 4:
        assert score.composite == max(numbers)
        assert score.risk_level == {"1": "Low", "3": "Medium", "5": "High"}[score.composite]
    else:
        assert score.composite == NOT_SCORABLE
        assert score.risk_level in {"High", "Insufficient Information"}


def test_the_score_register_carries_every_dimension_and_the_composite() -> None:
    report = business_context(pack_fixture(), submission_fixture())
    table = next(t for t in report.tables if t.table_id == "T2D.8")
    assert [row.label for row in table.rows] == [*DIMENSIONS, "Composite"]
    cells = {f.fact_id: f for f in report.facts}
    assert cells["T2D.8.d08.score"].text == "1"  # Reporting quality, one Supportive row
    assert cells["T2D.8.d02.score"].text == NOT_SCORABLE  # the Insufficient flag is not scored
    assert cells["T2D.8.composite.score"].text == NOT_SCORABLE
    assert cells["T2D.8.composite.assessment"].text == (
        "Sponsor / Governance Risk Level: Insufficient Information"
    )


# --- the property: no digit reaches a register except in a label or a resolved reference -----

WORDS = st.sampled_from(
    ("revenue", "grew", "in", "FY2025", "Q3", "notes", "11,456", "7", "Item 7A", "page 12", "the")
)
REFERENCE = "{T4.10.liquidity.FY2025|US$ m}"


@settings(max_examples=150, deadline=None)
@given(st.lists(st.one_of(WORDS, st.just(REFERENCE)), min_size=1, max_size=8))
def test_composed_registers_never_hold_a_digit_outside_a_label_or_a_resolved_reference(
    words: list[str],
) -> None:
    pack = pack_fixture()
    fact = cp1_fact(pack)
    text = " ".join(words)
    base = submission_fixture(pack)
    company = (base.company[0].model_copy(update={"text": text}), *base.company[1:])
    translation = base.credit_translations[0].model_copy(update={"risk_mechanic": text})
    submission = changed(base, company=company, credit_translations=(translation,))
    if validate_business_context(pack, submission, (fact,)):
        return  # rejected: nothing is composed
    report = business_context(pack, submission, (fact,))
    # Python-owned values that may carry digits: ids, locators, dates, scores and gap ids.
    owned = {"line:1", "2026-10-21", "1", "3", "5", "CP-1A-GAP-001", "CP-2C-FLAG-001"}
    for cell in report.facts:
        if cell.text is None:
            continue
        literal = cell.text.replace(spelled(fact), " ")
        assert set(bare_figures(literal, names=("Synthetic issuer",))) <= owned, cell.fact_id


# --- the sent schema (OpenAI strict-mode findings, task 2.11) -------------------------------


def nodes(node: object) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        return [node, *(n for value in node.values() for n in nodes(value))]
    if isinstance(node, list):
        return [n for item in node for n in nodes(item)]
    return []


def test_the_sent_schema_is_strict_and_carries_none_of_the_refused_constructs() -> None:
    sent = strict_schema(BusinessContextSubmission)
    assert relax(strict_copy(BusinessContextSubmission)) == sent
    text = json.dumps(sent)
    assert '"const"' not in text and '"oneOf"' not in text and '"default"' not in text
    for node in nodes(sent):
        assert None not in node.get("enum", ()), node
        assert node.get("type") != ["array", "null"], node
        if "properties" in node:
            assert node["required"] == list(node["properties"]) and not node["additionalProperties"]
    assert sent["properties"]["company"]["minItems"] == 1
    assert sent["properties"]["consumers"]["minItems"] == 1
    definitions = sent["$defs"]
    assert definitions["CreditTranslation"]["properties"]["confidence"]["enum"] == [
        "High",
        "Medium",
        "Low",
        "Insufficient Information",
    ]
    assert schema_relaxations(BusinessContextSubmission) == []  # nothing needed relaxing


def test_every_enum_of_the_contract_reaches_the_sent_schema() -> None:
    sent = json.dumps(strict_schema(BusinessContextSubmission))
    for value in (
        "Management Language",
        "Extraction-Oriented",
        "Leverage tolerance",
        "Not disclosed",
    ):
        assert f'"{value}"' in sent
    assert REGISTERS["T2D.8"].columns[5] == ("score", "Score")
