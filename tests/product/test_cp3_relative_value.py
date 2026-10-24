"""CP-3 relative value and security selection (task 8.3): the contract, its Python-only
validator, the composed tables, the Front Page binding and the method text.

SYNTHETIC data only: the pack is the one-line readiness fixture plus the SYNTHETIC dealer sheet
(`tests/product/cp3_market.py`), the CP-1 head carries SYNTHETIC canonical T4.18 facilities, the
CP-2 head is composed by Python from the CP-2 test's synthetic submission, and the Front Page
test runs over the SYNTHETIC Credit Snapshot fixture. Decision 0012: the key-area rules (figure
identity, market-gap propagation, order independence, quote spans, reference existence,
staleness and the prohibited-phrase boundary) are Hypothesis properties, three of them
differentials against naive references.
"""

import json
import random
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.bindings import BindingMap, validate_bindings
from deploy_vii.bindings.cp3 import CP3
from deploy_vii.business_context import (
    CP1_REFERENCES,
    PROHIBITED,
    Gap,
    Quote,
    business_context,
    cp1a_module,
    prohibited_issues,
    spelled,
    submit_cp1a_step,
)
from deploy_vii.contracts import Fact, Input, Module, ModuleView, View
from deploy_vii.cp2_synthesis import (
    CreditSynthesisSubmission,
    cp2_module,
    credit_synthesis,
    submit_cp2_step,
)
from deploy_vii.cp2_synthesis import Upstream as Cp2Upstream
from deploy_vii.cp3_relative_value import (
    MODULE_ID,
    PROHIBITED_KINDS,
    RELATIVE_VALUE,
    REQUIRED_TABLES,
    STEP_ID,
    Basis,
    Instrument,
    MarketEvidence,
    Preference,
    RelativeValueSubmission,
    Risk,
    Upstream,
    context_block,
    cp2_catalogue,
    cp3_module,
    cp3_upstream,
    facilities,
    relative_value,
    submit_cp3_step,
    validate_relative_value,
)
from deploy_vii.cp3_relative_value import _validate_step as validate_step
from deploy_vii.execution import (
    Attempt,
    Execution,
    ExecutionSnapshot,
    StepValidation,
    head_of,
    settle,
    text_sha256,
)
from deploy_vii.live.schema import relax, schema_relaxations, strict_copy, strict_schema
from deploy_vii.preparation import PreparedPack
from deploy_vii.prose import bare_figures
from deploy_vii.readiness import build_readiness
from deploy_vii.registry import StepChain, pack_source_steps
from deploy_vii.report_view import build, pathways
from tests.product.cp3_market import (
    FACILITIES,
    MARKET,
    MARKET_TEXT,
    NOTES_LINE,
    TALK_LINE,
    TLB_LINE,
    TLB_SPREAD,
    cp1a_submission,
    market_pack,
    market_review,
)
from tests.product.credit_snapshot import CREDIT_SNAPSHOT_MAPS, credit_snapshot_view
from tests.product.oracle import expected_text, gap_ids, parity_record
from tests.product.test_business_context import cp1_fact, pack_fixture
from tests.product.test_cp2_synthesis import (
    bound_inputs,
    cp1a_head,
    figures_only,
    leverage_fact,
    module_of,
    synthesis,
)
from tests.product.test_readiness import readiness_fixture

LIQUIDITY = "{T4.10.liquidity.FY2025|US$ m}"
ASSESSMENT = "T2.1.assessment"
WEAKNESS = "T2.7.w01"
RISK = "T2.11.r01"
ORDER = ("tlb", "notes", "revolver")
# The step chain the registration commit adds (ruling 1): one settling step sent pack sources.
CHAIN = StepChain(
    module_id=MODULE_ID, cell="cp3", steps=(STEP_ID,), pack_sources=frozenset({STEP_ID})
)


# --- fixtures: SYNTHETIC upstream heads -------------------------------------------------------


def public(pack: PreparedPack) -> PreparedPack:
    """`pack` as a public case, so settlement adds no synthetic limitation and `accepted` is
    reachable (test fixture, not qualification)."""
    run = pack.run.model_copy(update={"case_kind": "public"})
    return PreparedPack.model_validate_json(pack.model_copy(update={"run": run}).model_dump_json())


def quote(line: tuple[str, str]) -> Quote:
    return Quote(source_id=MARKET, locator=line[0], quote=line[1])


def cp0_head(pack: PreparedPack) -> Module:
    """CP-0 over `pack`: the sheet `third_party` when the pack holds it, else the filing only."""
    if any(s.source_id == MARKET for s in pack.sources):
        review = market_review(pack)
    else:
        review = readiness_fixture()[1].model_copy(update={"pack_sha256": pack.content_hash()})
    module = build_readiness(pack, review)
    return module.model_copy(update={"status": "restricted"})


def cp1_head(pack: PreparedPack, facts: tuple[Fact, ...] | None = None) -> Module:
    base = (cp1_fact(pack), leverage_fact(), *FACILITIES)
    return module_of(pack, "CP-1", facts=base if facts is None else facts)


def cp2_head(cp1: Module, *, accepted: bool = False) -> Module:
    """CP-2 composed by Python over `cp1`: the CP-2 test's synthesis (restricted by its own gap
    row) or, `accepted`, its figures-only synthesis over a READY CP-1A (no own limitation)."""
    pack = pack_fixture()
    cp1a = cp1a_head(pack, gaps=(), cp2_status="READY") if accepted else cp1a_head(pack)
    submission: CreditSynthesisSubmission = figures_only(gaps=()) if accepted else synthesis()
    bound = bound_inputs(pack, module_of(pack, "CP-0"), cp1, cp1a)
    up = Cp2Upstream(bound=bound, current=bound, cp1=cp1, cp1a=cp1a, inherited=())
    module = cp2_module(credit_synthesis(pack, submission, up), bound, 0)
    return module.model_copy(update={"status": "restricted" if module.limitations else "accepted"})


def cp4_head(pack: PreparedPack, status: str = "accepted") -> Module:
    if status == "blocked":
        limitation = ("Malformed candidate: (root): Invalid JSON",)
        return module_of(pack, "CP-4", status="blocked", limitations=limitation)
    return module_of(pack, "CP-4")


def entry(module: Module) -> Input:
    return Input(input_id=module.module_id, sha256=module.content_hash(), status=module.status)


class _Default:
    """The sentinel `upstream_of` reads as "the fixture's own head"."""


DEFAULT = _Default()


def upstream_of(
    pack: PreparedPack | None = None,
    *,
    cp1: Module | None = None,
    cp2: Module | None = None,
    cp1a: Module | _Default | None = DEFAULT,
    cp4: Module | _Default | None = DEFAULT,
    current: tuple[Input, ...] | str | None = None,
) -> Upstream:
    """In-memory heads in plan order; `cp1a`/`cp4` None leaves that optional input unbound."""
    pack = pack or market_pack()
    cp0 = cp0_head(pack)
    cp1 = cp1 or cp1_head(pack)
    cp2 = cp2 or cp2_head(cp1)
    drawn = {
        "CP-1A": cp1a_head(pack_fixture()) if isinstance(cp1a, _Default) else cp1a,
        "CP-4": cp4_head(pack) if isinstance(cp4, _Default) else cp4,
    }
    optional = {k: v for k, v in drawn.items() if v is not None}
    heads = [cp0, cp1, *(optional[k] for k in ("CP-1A",) if k in optional), cp2]
    heads += [optional["CP-4"]] if "CP-4" in optional else []
    bound = (Input(input_id="prepared-pack", sha256=pack.content_hash()), *map(entry, heads))
    return Upstream(
        bound=bound,
        current=bound if current is None else current,
        cp0=cp0,
        cp1=cp1,
        cp2=cp2,
        optional=optional,
        inherited=(),
    )


def instruments() -> tuple[Instrument, ...]:
    return (
        Instrument(
            facility_id="tlb",
            fundamental_view=f"The secured Term Loan B-2 pays a spread of {TLB_SPREAD} on a "
            "thinly disclosed credit.",
            market_observation="The dealer sheet quotes the Term Loan B-2 near par.",
            basis=Basis(cp2_refs=(ASSESSMENT,), quotes=(quote(TLB_LINE),)),
            limitation=None,
        ),
        Instrument(
            facility_id="notes",
            fundamental_view="The unsecured notes sit behind the secured debt.",
            market_observation="The dealer sheet shows the notes at a discount.",
            basis=Basis(cp2_refs=(WEAKNESS,), quotes=(quote(NOTES_LINE),)),
            limitation=None,
        ),
        Instrument(
            facility_id="revolver",
            fundamental_view="The revolver is secured and the shortest dated.",
            market_observation="none",
            basis=Basis(cp2_refs=(RISK,), quotes=()),
            limitation="No observed level for the revolver",
        ),
    )


def evidence() -> tuple[MarketEvidence, ...]:
    return (
        MarketEvidence(
            source_id=MARKET,
            kind="observed",
            quote=quote(TLB_LINE),
            as_of="30 June 2026",
            limitation="SYNTHETIC dealer sheet",
        ),
        MarketEvidence(
            source_id=MARKET,
            kind="observed",
            quote=quote(NOTES_LINE),
            as_of="30 June 2026",
            limitation="SYNTHETIC dealer sheet",
        ),
        MarketEvidence(
            source_id=MARKET,
            kind="indicative_talk",
            quote=quote(TALK_LINE),
            as_of="30 June 2026",
            limitation="Talk for an extension, not a level",
        ),
    )


def valuation(**changes: object) -> RelativeValueSubmission:
    """A valid synthetic submission over `upstream_of()`."""
    base = RelativeValueSubmission(
        instruments=instruments(),
        market_evidence=evidence(),
        preference=Preference(
            ordering=ORDER,
            rationale="The secured term loan is better compensated for its risk than the "
            "unsecured notes.",
            basis=Basis(cp2_refs=(ASSESSMENT,), quotes=(quote(TLB_LINE), quote(NOTES_LINE))),
            confidence="Low",
            limitation=None,
        ),
        risks=(
            Risk(
                risk="Disclosure",
                mechanic="Thin disclosure limits the fundamental view behind the ordering.",
                implication="The ordering may change when fuller filings arrive.",
                severity="Material",
                cp2_refs=(RISK,),
            ),
        ),
        gaps=(
            Gap(
                gap="No observed level for the revolver",
                why_it_matters="Its compensation cannot be judged",
                affected_analysis="Security selection",
                severity="Minor",
                action="Obtain a dealer level",
            ),
        ),
    )
    return base.model_copy(update=changes)


def unquoted(**changes: object) -> RelativeValueSubmission:
    """A valid submission with no market evidence at all: an Insufficient preference."""
    base = valuation()
    rows = tuple(
        row.model_copy(
            update={
                "market_observation": "none",
                "basis": Basis(cp2_refs=row.basis.cp2_refs, quotes=()),
            }
        )
        for row in base.instruments
    )
    preference = base.preference.model_copy(
        update={
            "basis": Basis(cp2_refs=(ASSESSMENT,), quotes=()),
            "confidence": "Insufficient Information",
            "limitation": "No market evidence in the pack",
        }
    )
    return valuation(instruments=rows, market_evidence=(), preference=preference).model_copy(
        update=changes
    )


def issues_of(submission: RelativeValueSubmission, up: Upstream | None = None) -> tuple[str, ...]:
    return validate_relative_value(market_pack(), submission, up or upstream_of())


def cells_of(facts: tuple[Fact, ...]) -> dict[str, Fact]:
    return {f.fact_id: f for f in facts}


# --- acceptance and composition ---------------------------------------------------------------


def test_a_valid_submission_composes_the_tables_and_the_front_page_table() -> None:
    pack, up = market_pack(), upstream_of()
    assert validate_relative_value(pack, valuation(), up) == ()
    report = relative_value(pack, valuation(), up)
    tables = {t.table_id: t for t in report.tables}
    assert REQUIRED_TABLES == ("T3.1", "T3.3", "T3.4", "T3.9", "T3.10")
    assert set(REQUIRED_TABLES) | {RELATIVE_VALUE, CP1_REFERENCES} == tables.keys()
    cells = cells_of(report.facts)
    spread = spelled(next(f for f in FACILITIES if f.field == "spread_bps"))
    assert cells["T3.1.i01.fundamental_view"].text == (
        f"The secured Term Loan B-2 pays a spread of {spread} on a thinly disclosed credit."
    )
    assert cells["T3.1.i01.facility_id"].text == "tlb"
    assert [r.label for r in tables["T3.1"].rows] == [
        "Term Loan B-2",
        "Senior notes due 2030",
        "Revolving credit facility",
    ]
    assert cells["T3.1.i01.basis"].text == (
        "CP-2 T2.1.assessment (Credit assessment); Market evidence market-sheet line:2 "
        "(observed); CP-1 Term Loan B-2 spread · FY2025"
    )
    assert cells["T3.1.i03.market_observation"].text == "No market evidence cited."
    assert cells["T3.4.preference.ordering"].text == (
        "Term Loan B-2 > Senior notes due 2030 > Revolving credit facility"
    )
    assert cells["T3.4.preference.confidence"].text == "Low"
    assert cells["T3.3.m03.kind"].text == "Indicative talk"
    quoted = cells["T3.3.m01.quote"]
    assert quoted.text == TLB_LINE[1] and [c.locator for c in quoted.citations] == ["line:2"]
    assert quoted.value_class is None  # a quote is source text, not CP-3's judgment
    assert cells["T3.10.g01.gap_id"].text == "CP-3-GAP-001"
    assert report.limitations == ("Gap (Minor): No observed level for the revolver",)
    assert [c.claim_id for c in report.claims] == ["T3.4.preference", "T3.1.i01", "T3.1.i02"]
    assert [len(c.citations) for c in report.claims] == [2, 1, 1]
    assert report.schema_version == "relative-value/1"
    module = cp3_module(report, up.bound, 0)  # the Module validator holds the table layout
    assert module.module_id == MODULE_ID and module.status == "candidate"
    assert module.inputs[-1].input_id == "relative-value-submission"
    assert module.inputs[:-1] == up.bound


def test_the_front_page_table_leads_with_the_preference_then_each_instrument() -> None:
    report = relative_value(market_pack(), valuation(), upstream_of())
    front = [f for f in report.facts if f.table_id == RELATIVE_VALUE]
    assert [f.label for f in front] == [
        "Preference",
        "Term Loan B-2",
        "Senior notes due 2030",
        "Revolving credit facility",
    ]
    assert front[0].text == (
        "Preference: Term Loan B-2 > Senior notes due 2030 > Revolving credit facility. The "
        "secured term loan is better compensated for its risk than the unsecured notes."
    )
    assert front[3].text == (
        "Revolving credit facility: The revolver is secured and the shortest dated. Market: No "
        "market evidence cited."
    )
    assert all(f.value_class == "analyst_judgment" for f in front)


def test_referenced_cp1_figures_are_carried_verbatim() -> None:
    report = relative_value(market_pack(), valuation(), upstream_of())
    carried = [f for f in report.facts if f.table_id == CP1_REFERENCES]
    upstream = next(f for f in FACILITIES if f.fact_id == "T4.18.tlb-fy2025.spread_bps")
    assert [f.fact_id for f in carried] == [upstream.fact_id]
    place = {"table_id": upstream.table_id, "row_id": upstream.row_id, "field": upstream.field}
    assert carried[0].model_copy(update=place) == upstream


def test_empty_registers_are_explicit_rows_and_only_required_ones_limit() -> None:
    empty = unquoted(risks=(), gaps=())
    report = relative_value(market_pack(), empty, upstream_of())
    cells = cells_of(report.facts)
    assert "No relative value risks rows in the CP-3 submission" in report.limitations
    assert cells["T3.9.none.risk"].status == "missing"
    assert cells["T3.3.none.quote"].status == "not_applicable"
    assert cells["T3.10.none.gap"].status == "not_applicable"
    nothing = unquoted(
        instruments=(), preference=unquoted().preference.model_copy(update={"ordering": ()})
    )
    found = relative_value(market_pack(), nothing, upstream_of())
    assert "No instrument relative value rows in the CP-3 submission" in found.limitations
    assert cells_of(found.facts)["T3.4.preference.ordering"].text == "No ordering"


# --- market evidence --------------------------------------------------------------------------


def test_no_market_evidence_makes_the_preference_insufficient_and_limits() -> None:
    report = relative_value(market_pack(), unquoted(), upstream_of())
    assert report.limitations == (
        "Gap (Minor): No observed level for the revolver",
        "No observed or indicative market evidence: relative value is not assessed",
        "Relative value preference is Insufficient Information: No market evidence in the pack",
    )
    cells = cells_of(report.facts)
    assert cells["T3.4.preference.rationale"].text.endswith("[Insufficient Information]")
    low = unquoted().preference.model_copy(update={"confidence": "Low", "limitation": None})
    found = issues_of(unquoted(preference=low))
    assert (
        "preference.confidence: Insufficient Information without observed or indicative market "
        "evidence"
    ) in found
    assert "preference: a relative value preference cites a market_evidence quote" in found
    silent = unquoted().preference.model_copy(update={"limitation": None})
    assert "preference: an Insufficient Information preference states its limitation" in (
        issues_of(unquoted(preference=silent))
    )


def test_a_none_evidence_row_quotes_nothing_and_states_why() -> None:
    row = MarketEvidence(
        source_id="none", kind="none", quote=None, as_of="none", limitation="No dealer sheet"
    )
    assert issues_of(unquoted(market_evidence=(row,))) == ()
    report = relative_value(market_pack(), unquoted(market_evidence=(row,)), upstream_of())
    assert "No observed or indicative market evidence: relative value is not assessed" in (
        report.limitations
    )  # a none row is no evidence
    quoted = row.model_copy(update={"quote": quote(TLB_LINE), "limitation": None})
    found = issues_of(unquoted(market_evidence=(quoted,)))
    assert "market_evidence[0]: a none row quotes nothing" in found
    assert "market_evidence[0]: a none row states its limitation" in found
    bare = evidence()[0].model_copy(update={"quote": None})
    assert "market_evidence[0]: an observed row quotes its source" in issues_of(
        unquoted(market_evidence=(bare,))
    )


def test_indicative_talk_is_never_accepted_as_observed() -> None:
    observed = evidence()[2].model_copy(update={"kind": "observed"})
    found = issues_of(valuation(market_evidence=(*evidence()[:2], observed)))
    assert 'market_evidence[2]: an observed row quotes indicative talk: "talk"' in found
    assert 'market_evidence[2]: an observed row quotes indicative talk: "indicative"' in found


def test_indicative_talk_is_never_worded_as_a_market_level() -> None:
    revolver = instruments()[2].model_copy(
        update={
            "market_observation": "The revolver extension trades at the talk.",
            "basis": Basis(cp2_refs=(RISK,), quotes=(quote(TALK_LINE),)),
        }
    )
    found = issues_of(valuation(instruments=(*instruments()[:2], revolver)))
    assert (
        'instruments[2].market_observation: indicative talk worded as a market level: "trades at"'
    ) in found
    worded = evidence()[2].model_copy(update={"limitation": "The extension is priced at talk"})
    assert (
        'market_evidence[2].limitation: indicative talk worded as a market level: "priced at"'
    ) in issues_of(valuation(market_evidence=(*evidence()[:2], worded)))
    # The same wording over an observed quote is a level, not talk.
    level = instruments()[0].model_copy(update={"market_observation": "The loan trades at par."})
    assert issues_of(valuation(instruments=(level, *instruments()[1:]))) == ()


def test_a_span_is_quoted_by_one_market_evidence_row_only() -> None:
    """Confidence review: a span quoted twice under two kinds was re-kinded by the later row."""
    again = evidence()[0].model_copy(update={"kind": "indicative_talk"})
    found = issues_of(valuation(market_evidence=(*evidence(), again)))
    assert (
        "market_evidence[3]: quotes the same span as market_evidence[0] (market-sheet line:2)"
    ) in found


def test_talk_stated_as_not_a_level_is_accepted() -> None:
    """Confidence review: the guard matches level verbs, not an honest negation."""
    honest = evidence()[2].model_copy(update={"limitation": "Indicative talk, not a market level"})
    assert issues_of(valuation(market_evidence=(*evidence()[:2], honest))) == ()


def test_talk_only_evidence_caps_and_limits() -> None:
    talk = evidence()[2]
    rows = tuple(
        row.model_copy(
            update={
                "market_observation": "none",
                "basis": Basis(cp2_refs=row.basis.cp2_refs, quotes=()),
            }
        )
        for row in instruments()
    )
    preference = valuation().preference.model_copy(
        update={"basis": Basis(cp2_refs=(ASSESSMENT,), quotes=(quote(TALK_LINE),))}
    )
    submission = valuation(instruments=rows, market_evidence=(talk,), preference=preference)
    up = upstream_of(cp2=cp2_head(cp1_head(market_pack()), accepted=True))
    assert issues_of(submission, up) == ()
    assert "Market evidence is indicative talk only, not an observed market level" in (
        relative_value(market_pack(), submission, up).limitations
    )
    high = preference.model_copy(update={"confidence": "High"})
    assert (
        "preference.confidence: capped below High because the market evidence is indicative "
        "talk only"
    ) in issues_of(valuation(instruments=rows, market_evidence=(talk,), preference=high), up)


def test_a_market_claim_needs_a_market_evidence_quote() -> None:
    claim = instruments()[0].model_copy(update={"basis": Basis(cp2_refs=(ASSESSMENT,), quotes=())})
    assert "instruments[0]: a market observation cites a market_evidence quote" in issues_of(
        valuation(instruments=(claim, *instruments()[1:]))
    )
    stray = Quote(source_id=MARKET, locator="line:1", quote="SYNTHETIC dealer sheet")
    other = instruments()[0].model_copy(
        update={"basis": Basis(cp2_refs=(ASSESSMENT,), quotes=(stray,))}
    )
    assert (
        "instruments[0].basis.quotes[0]: quotes no market_evidence row (market-sheet line:1)"
    ) in issues_of(valuation(instruments=(other, *instruments()[1:])))


def test_market_evidence_comes_only_from_a_third_party_source() -> None:
    filing = MarketEvidence(
        source_id="filing",
        kind="observed",
        quote=Quote(source_id="filing", locator="line:1", quote="cash USD million"),
        as_of="FY2025",
        limitation=None,
    )
    found = issues_of(valuation(market_evidence=(*evidence(), filing)))
    assert "market_evidence[3]: filing is not a third_party source (CP-0 T3)" in found
    crossed = evidence()[0].model_copy(update={"source_id": "filing"})
    found = issues_of(valuation(market_evidence=(crossed, *evidence()[1:])))
    assert "market_evidence[0].quote: quotes market-sheet, not filing" in found
    # Without the sheet in the pack there is no market source: the catalogue is empty.
    bare = upstream_of(pack_fixture())
    assert bare.market_sources == frozenset()
    found = validate_relative_value(pack_fixture(), valuation(), bare)
    assert "Unavailable or changed source: market-sheet" in found


def test_a_quote_outside_its_span_is_rejected() -> None:
    moved = evidence()[0].model_copy(
        update={"quote": Quote(source_id=MARKET, locator="line:3", quote=TLB_LINE[1])}
    )
    found = issues_of(valuation(market_evidence=(moved, *evidence()[1:])))
    mismatch = "market_evidence[0]: Quote/locator mismatch: quote not found"
    assert any(i.startswith(mismatch) for i in found)
    nowhere = evidence()[0].model_copy(
        update={"quote": Quote(source_id=MARKET, locator="line:9", quote=TLB_LINE[1])}
    )
    found = issues_of(valuation(market_evidence=(nowhere, *evidence()[1:])))
    absent = "market_evidence[0]: Quote/locator mismatch: no locator"
    assert any(i.startswith(absent) for i in found)


# --- rejections ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Investors should buy the secured term loan.", "instrument action"),
        ("We would sell the notes.", "instrument action"),
        ("Overweight the term loan.", "instrument action"),
        ("We recommend the secured term loan.", "instrument action"),
        ("The final recommendation is the term loan.", "instrument action"),
        ("Switch into the term loan from the notes.", "instrument action"),
        ("Switch out of the notes.", "instrument action"),
        ("The notes look cheap relative to peers.", "peer ranking"),
        ("The notes would recover in full.", "recovery conclusion"),
        ("An expected recovery protects the term loan.", "recovery conclusion"),
    ],
)
def test_action_recommendation_recovery_and_peer_ranking_are_prohibited(
    text: str, kind: str
) -> None:
    preference = valuation().preference.model_copy(update={"rationale": text})
    found = issues_of(valuation(preference=preference))
    assert any(f"preference.rationale: prohibited conclusion ({kind})" in i for i in found)


@pytest.mark.parametrize(
    "text",
    [
        "The secured term loan is preferred over the unsecured notes.",
        "We prefer the term loan to the notes for its security.",
        "The term loan comes first in the ordering, ahead of the notes.",
        "The secured term loan is better compensated than the notes.",
        "Recovery prospects favour the secured debt as a mechanic.",
    ],
)
def test_an_intra_issuer_ordering_is_cp3s_own_output(text: str) -> None:
    preference = valuation().preference.model_copy(update={"rationale": text})
    assert issues_of(valuation(preference=preference)) == ()


def test_a_bare_figure_and_an_unoffered_reference_are_rejected() -> None:
    bare = instruments()[0].model_copy(update={"market_observation": "The loan is at 99.25."})
    assert "instruments[0].market_observation: Bare figure: 99.25" in issues_of(
        valuation(instruments=(bare, *instruments()[1:]))
    )
    ghost = instruments()[1].model_copy(
        update={"fundamental_view": "Cover was {T4.10.interest_cover.FY2025|x}."}
    )
    assert (
        "instruments[1].fundamental_view: Unresolved reference: T4.10.interest_cover.FY2025"
    ) in issues_of(valuation(instruments=(instruments()[0], ghost, instruments()[2])))


def test_unknown_facility_and_cp2_refs_are_rejected() -> None:
    unknown = instruments()[2].model_copy(update={"facility_id": "tla"})
    found = issues_of(valuation(instruments=(*instruments()[:2], unknown)))
    assert "instruments[2].facility_id: unknown CP-1 facility tla" in found
    refs = Basis(cp2_refs=("T2.7.s09", "cp2.thesis.thesis", f"{CP1_REFERENCES}.ref01"), quotes=())
    row = instruments()[2].model_copy(update={"basis": refs})
    found = issues_of(valuation(instruments=(*instruments()[:2], row)))
    for ref in refs.cp2_refs:
        assert f"instruments[2].basis.cp2_refs: unknown CP-2 row {ref}" in found
    risk = valuation().risks[0].model_copy(update={"cp2_refs": ("T2.12.g09",)})
    assert "risks[0].cp2_refs: unknown CP-2 row T2.12.g09" in issues_of(valuation(risks=(risk,)))


def test_every_row_needs_a_basis() -> None:
    bare = instruments()[2].model_copy(update={"basis": Basis(cp2_refs=(), quotes=())})
    assert (
        "instruments[2]: an instrument cites a CP-2 row, a market_evidence quote or a CP-1 figure"
        in (issues_of(valuation(instruments=(*instruments()[:2], bare))))
    )
    risk = valuation().risks[0].model_copy(update={"cp2_refs": ()})
    assert "risks[0]: a risk cites a CP-2 row or a CP-1 figure" in issues_of(
        valuation(risks=(risk,))
    )
    figured = risk.model_copy(update={"mechanic": f"Liquidity of {LIQUIDITY} is thin."})
    assert issues_of(valuation(risks=(figured,))) == ()


@pytest.mark.parametrize(
    ("ordering", "issue"),
    [
        (
            ("tlb", "notes", "notes", "revolver"),
            "preference.ordering: notes appears more than once",
        ),
        (("tlb", "notes"), "preference.ordering: revolver is missing"),
        (("tlb", "notes", "revolver", "tla"), "preference.ordering: tla is not an instruments row"),
    ],
)
def test_the_ordering_names_each_instrument_exactly_once(
    ordering: tuple[str, ...], issue: str
) -> None:
    preference = valuation().preference.model_copy(update={"ordering": ordering})
    assert issue in issues_of(valuation(preference=preference))


def test_an_instrument_appears_once() -> None:
    twice = (*instruments(), instruments()[0])
    assert "instruments: facility tlb appears more than once" in issues_of(
        valuation(instruments=twice)
    )


def test_a_stale_or_refused_input_set_is_rejected() -> None:
    up = upstream_of()
    moved = tuple(
        item.model_copy(update={"sha256": "f" * 64}) if item.input_id == "CP-2" else item
        for item in up.bound
    )
    found = validate_relative_value(market_pack(), valuation(), upstream_of(current=moved))
    cp2 = next(i for i in up.bound if i.input_id == "CP-2")
    assert [i for i in found if i.startswith("Stale input")] == [
        f"Stale input CP-2: bound restricted {cp2.sha256[:12]}, current restricted {'f' * 12}"
    ]
    refused = upstream_of(current="Required upstream is unrun, stale or blocked")
    assert "Stale inputs: Required upstream is unrun, stale or blocked" in (
        validate_relative_value(market_pack(), valuation(), refused)
    )


def test_an_upstream_module_must_be_the_bound_head() -> None:
    up = upstream_of()
    other = cp2_head(up.cp1, accepted=True)
    swapped = Upstream(
        bound=up.bound,
        current=up.current,
        cp0=up.cp0,
        cp1=up.cp1,
        cp2=other,
        optional=up.optional,
        inherited=(),
    )
    assert "Upstream CP-2: the supplied module is not the bound input" in issues_of(
        valuation(), swapped
    )
    lost = Upstream(
        bound=up.bound,
        current=up.current,
        cp0=up.cp0,
        cp1=up.cp1,
        cp2=up.cp2,
        optional={"CP-1A": up.optional["CP-1A"]},
        inherited=(),
    )
    assert "Upstream CP-4: the supplied module is not the bound input" in issues_of(
        valuation(), lost
    )
    blocked = tuple(
        i.model_copy(update={"status": "blocked"}) if i.input_id == "CP-2" else i for i in up.bound
    )
    probe = Upstream(
        bound=blocked,
        current=blocked,
        cp0=up.cp0,
        cp1=up.cp1,
        cp2=up.cp2,
        optional=up.optional,
        inherited=(),
    )
    found = issues_of(valuation(), probe)
    assert "Required upstream CP-2 is blocked" in found
    assert f"instruments[0].basis.cp2_refs: unknown CP-2 row {ASSESSMENT}" in found


def test_text_is_never_blank_and_malformed_references_are_issues() -> None:
    blank = instruments()[0].model_copy(update={"fundamental_view": "  "})
    assert "instruments[0].fundamental_view: empty text" in issues_of(
        valuation(instruments=(blank, *instruments()[1:]))
    )
    broken = valuation().preference.model_copy(update={"rationale": "Spread {T4.18.tlb"})
    found = issues_of(valuation(preference=broken))
    assert any(i.startswith("preference.rationale: Malformed run text") for i in found)


# --- optional upstreams (decision 0007, ruling 4) ---------------------------------------------


def test_a_blocked_or_missing_optional_upstream_limits_and_caps_never_halts() -> None:
    accepted = cp2_head(cp1_head(market_pack()), accepted=True)
    high = valuation().preference.model_copy(update={"confidence": "High"})
    assert issues_of(valuation(preference=high), upstream_of(cp2=accepted)) == ()
    for cp1a, cp4, wording in (
        (
            DEFAULT,
            cp4_head(market_pack(), "blocked"),
            "Optional upstream CP-4 blocked: CP-3 reads no covenant and legal context",
        ),
        (
            DEFAULT,
            None,
            "Optional upstream CP-4 not in this run: CP-3 reads no covenant and legal context",
        ),
        (
            None,
            DEFAULT,
            "Optional upstream CP-1A not in this run: CP-3 reads no business and transaction "
            "context",
        ),
    ):
        up = upstream_of(cp2=accepted, cp1a=cp1a, cp4=cp4)
        assert validate_relative_value(market_pack(), valuation(), up) == ()
        assert wording in relative_value(market_pack(), valuation(), up).limitations
        found = issues_of(valuation(preference=high), up)
        assert any(i.startswith("preference.confidence: capped below High because") for i in found)


def test_a_restricted_cp2_caps_the_confidence() -> None:
    high = valuation().preference.model_copy(update={"confidence": "High"})
    assert "preference.confidence: capped below High because CP-2 is restricted" in issues_of(
        valuation(preference=high)
    )


# --- the journal: one step settles CP-3 -------------------------------------------------------


def journal(tmp_path: Path, *, cp4: str = "accepted") -> Execution:
    """A SYNTHETIC journal over the market pack: CP-0, CP-1, CP-1A, CP-2 and CP-4 settled (CP-4
    accepted, or blocked by two malformed attempts)."""
    pack = market_pack()
    store = Execution.create(tmp_path / "execution", pack)
    ticket = store.begin("CP-0")
    store.finish(
        ticket.ticket_id,
        build_readiness(store.pack(), market_review(pack)).model_dump_json(),
        lambda _: (),
    )
    ticket = store.begin("CP-1")
    cp1 = cp1_head(pack).model_copy(update={"inputs": ticket.inputs, "status": "candidate"})
    store.finish(ticket.ticket_id, cp1.model_dump_json(), lambda _: ())
    ticket = store.begin("CP-1A")
    submit_cp1a_step(
        store, ticket.ticket_id, "business_context", cp1a_submission(pack).model_dump_json()
    )
    ticket = store.begin("CP-2")
    submit_cp2_step(store, ticket.ticket_id, "credit_synthesis", synthesis().model_dump_json())
    if cp4 == "blocked":
        for _ in range(2):
            ticket = store.begin("CP-4")
            store.finish(ticket.ticket_id, "not json", lambda _: ())
    else:
        ticket = store.begin("CP-4")
        run = pack.run
        cp4_module = Module(
            run_id=run.run_id,
            issuer_id=run.issuer_id,
            as_of=run.as_of,
            module_id="CP-4",
            inputs=ticket.inputs,
        )
        store.finish(ticket.ticket_id, cp4_module.model_dump_json(), lambda _: ())
    return store


def head(store: Execution, module_id: str) -> Module:
    found = next(h for h in store.read().heads if h.module_id == module_id)
    return store.result(found.result_sha256)


def test_the_step_settles_cp3_with_the_python_candidate(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    upstream = cp3_upstream(store, ticket)
    assert upstream.cp2_status == "restricted" and upstream.current == ticket.inputs
    assert set(upstream.optional) == {"CP-1A", "CP-4"}
    assert upstream.market_sources == frozenset({MARKET})
    attempt = submit_cp3_step(store, ticket.ticket_id, STEP_ID, valuation().model_dump_json())
    assert attempt.status == "finished" and attempt.issues == ()
    cp3 = head(store, MODULE_ID)
    assert cp3.status == "restricted"  # own gap row, and a synthetic case
    assert "Synthetic case; not real issuer qualification" in cp3.limitations
    assert "Gap (Material): No segment disclosure" in cp3.inherited_limitations  # CP-2's own
    assert {i.input_id for i in cp3.inputs} >= {"CP-0", "CP-1", "CP-1A", "CP-2", "CP-4"}
    quoted = next(f for f in cp3.facts if f.fact_id == "T3.3.m01.quote")
    assert quoted.citations[0].source_sha256 == next(
        s.sha256 for s in store.pack().sources if s.source_id == MARKET
    )
    record = next(h for h in store.read().heads if h.module_id == MODULE_ID)
    assert record.qualification is not None
    assert record.qualification.implementation == "implemented"
    with pytest.raises(ValueError, match="one step"):
        submit_cp3_step(store, ticket.ticket_id, "credit_synthesis", "{}")
    with pytest.raises(ValueError, match="absent, finished"):
        submit_cp3_step(store, ticket.ticket_id, STEP_ID, valuation().model_dump_json())


def test_a_blocked_cp4_reaches_cp3_with_the_0007_wording(tmp_path: Path) -> None:
    store = journal(tmp_path, cp4="blocked")
    ticket = store.begin(MODULE_ID)
    assert next(i for i in ticket.inputs if i.input_id == "CP-4").status == "blocked"
    attempt = submit_cp3_step(store, ticket.ticket_id, STEP_ID, valuation().model_dump_json())
    assert attempt.issues == ()
    cp3 = head(store, MODULE_ID)
    assert cp3.status == "restricted"
    assert "Optional upstream CP-4 blocked: CP-3 reads no covenant and legal context" in (
        cp3.limitations
    )
    blocked = head(store, "CP-4")
    assert [f"Upstream CP-4 blocked: {text}" for text in blocked.limitations] == [
        text for text in cp3.inherited_limitations if text.startswith("Upstream CP-4 blocked")
    ]


def test_an_invalid_step_rejects_then_blocks_with_its_issues(tmp_path: Path) -> None:
    store = journal(tmp_path)
    unknown = valuation(
        instruments=(instruments()[0].model_copy(update={"facility_id": "x"}), *instruments()[1:])
    )
    for number, status in ((0, "rejected"), (1, "blocked")):
        ticket = store.begin(MODULE_ID)
        assert ticket.number == number
        attempt = submit_cp3_step(store, ticket.ticket_id, STEP_ID, unknown.model_dump_json())
        assert "instruments[0].facility_id: unknown CP-1 facility x" in attempt.issues
        assert store.result(str(attempt.result_sha256)).status == status
    malformed = journal(tmp_path / "other")
    ticket = malformed.begin(MODULE_ID)
    attempt = submit_cp3_step(malformed, ticket.ticket_id, STEP_ID, '{"preference": 1}')
    assert any(i.startswith("instruments: Field required") for i in attempt.issues)


def test_a_changed_pack_stales_the_bound_inputs(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    attempt = submit_cp3_step(store, ticket.ticket_id, STEP_ID, valuation().model_dump_json())
    pack = store.pack()
    source = pack.sources[0].model_copy(update={"name": "Renamed synthetic filing"})
    store.replace_pack(pack.model_copy(update={"sources": (source, *pack.sources[1:])}))
    upstream = cp3_upstream(store, attempt)
    assert upstream.current == "Required upstream is unrun, stale or blocked"
    assert "Stale inputs: Required upstream is unrun, stale or blocked" in (
        validate_relative_value(store.pack(), valuation(), upstream)
    )


def test_a_resumed_step_reuses_the_retained_response(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    payload = valuation().model_dump_json()
    store.submit_step(
        ticket.ticket_id,
        MODULE_ID,
        (STEP_ID,),
        STEP_ID,
        payload,
        lambda pack, current: validate_step(store, pack, current),
    )
    with pytest.raises(ValueError, match="different response"):
        submit_cp3_step(store, ticket.ticket_id, STEP_ID, valuation(gaps=()).model_dump_json())
    attempt = submit_cp3_step(store, ticket.ticket_id, STEP_ID, payload)
    assert attempt.status == "finished" and head(store, MODULE_ID).status == "restricted"


def test_a_retained_output_trusted_validation_does_not_reproduce_is_refused(
    tmp_path: Path,
) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    payload = valuation().model_dump_json()
    store.submit_step(
        ticket.ticket_id,
        MODULE_ID,
        (STEP_ID,),
        STEP_ID,
        payload,
        lambda _pack, _current: StepValidation(output="not the composed report"),
    )
    with pytest.raises(ValueError, match="differs from trusted validation"):
        submit_cp3_step(store, ticket.ticket_id, STEP_ID, payload)
    assert not any(h.module_id == MODULE_ID for h in store.read().heads)


def test_an_attempt_without_its_required_inputs_fails_closed(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    with pytest.raises(ValueError, match="binds no CP-2 input"):
        cp3_upstream(
            store,
            ticket.model_copy(
                update={"inputs": tuple(i for i in ticket.inputs if i.input_id != "CP-2")}
            ),
        )


# --- the CONTEXT block and the step chain -----------------------------------------------------


def test_the_context_block_prefills_facilities_rows_sources_and_statuses() -> None:
    up = upstream_of(cp4=None)
    block = context_block(market_pack(), up)
    assert block["upstream"] == [
        {"module_id": "CP-0", "status": "restricted"},
        {"module_id": "CP-1", "status": "accepted"},
        {"module_id": "CP-1A", "status": "restricted"},
        {"module_id": "CP-2", "status": "restricted"},
    ]
    assert [f["facility_id"] for f in block["cp1_facilities"]] == list(ORDER)
    tlb = block["cp1_facilities"][0]
    assert tlb["name"] == "Term Loan B-2" and tlb["terms"]["seniority"] == "Senior"
    assert tlb["figures"] == ["T4.18.tlb-fy2025.spread_bps"]
    assert "T4.18.tlb-fy2025.spread_bps" in [f["ref"] for f in block["cp1_facts"]]
    rows = {row["ref"] for row in block["cp2_rows"]}
    assert rows == set(cp2_catalogue(up.cp2)) and {ASSESSMENT, WEAKNESS, RISK} <= rows
    assert not any(ref.startswith(("cp2.", CP1_REFERENCES)) for ref in rows)
    assert block["optional_upstream"][1] == {
        "module_id": "CP-4",
        "status": "not in this run",
        "limitations": [],
    }
    assert block["pack_sources"] == [
        {"source_id": "filing", "name": "filing.txt", "status": "ready", "authority": "unknown"},
        {
            "source_id": MARKET,
            "name": "market-sheet.txt",
            "status": "ready",
            "authority": "third_party",
        },
    ]
    assert block["market_evidence_sources"] == [
        {"source_id": MARKET, "name": "market-sheet.txt", "spans": 4}
    ]
    assert block["confidence_caps"] == ["CP-2 is restricted", "optional CP-4 is not in this run"]
    bare = context_block(pack_fixture(), upstream_of(pack_fixture()))
    assert bare["market_evidence_sources"] == []
    assert "Insufficient Information" in str(bare["market_evidence_note"])


def test_the_step_chain_sends_pack_sources_to_the_one_step() -> None:
    assert CHAIN.settling == STEP_ID and pack_source_steps((CHAIN,)) == frozenset({STEP_ID})


def test_the_fixture_is_small_and_labelled_synthetic() -> None:
    assert len(MARKET_TEXT.encode()) == 286  # measured: 286 bytes, four lines
    assert all(line.startswith("SYNTHETIC") for line in MARKET_TEXT.splitlines())
    block = json.dumps(context_block(market_pack(), upstream_of()))
    assert len(block.encode()) < 8_000  # the CONTEXT block over the fixture: 5,888 bytes


# --- the sent schema ----------------------------------------------------------------------------


def nodes(node: object) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        return [node, *(n for value in node.values() for n in nodes(value))]
    if isinstance(node, list):
        return [n for item in node for n in nodes(item)]
    return []


def test_the_sent_schema_is_strict_and_needs_no_relaxation() -> None:
    sent = strict_schema(RelativeValueSubmission)
    assert relax(strict_copy(RelativeValueSubmission)) == sent
    text = json.dumps(sent)
    assert '"const"' not in text and '"oneOf"' not in text and '"default"' not in text
    for node in nodes(sent):
        assert None not in node.get("enum", ()), node
        if "properties" in node:
            assert node["required"] == list(node["properties"]) and not node["additionalProperties"]
    assert sent["properties"]["instruments"]["minItems"] == 1
    assert list(sent["properties"]) == [
        "instruments",
        "market_evidence",
        "preference",
        "risks",
        "gaps",
    ]
    assert schema_relaxations(RelativeValueSubmission) == []


# --- Property 1: figure identity ----------------------------------------------------------------

GOOD = (TLB_SPREAD, "{T4.10.liquidity.FY2025|US$ m}", "{synthetic-revolver-fy2025-spread_bps|bp}")
BAD = (
    "99.25",
    "350bp",
    "{T4.18.tlb-fy2025.spread_bps|bps}",
    "{T4.18.ghost.spread_bps|bp}",
    "{T4.10.interest_cover.FY2025|x}",
    "[T4.18.tlb-fy2025.spread_bps]",
)
WORDS = ("the", "loan", "is", "secured", "Term Loan B-2", "30 June 2026", "senior")


@settings(max_examples=150, deadline=None)
@given(
    st.lists(st.sampled_from((*WORDS, *GOOD, *BAD)), min_size=1, max_size=8),
    st.sampled_from((*ORDER, "tla", "T4.18")),
    st.sampled_from((ASSESSMENT, WEAKNESS, "T2.7.s09", "cp2.thesis.thesis")),
)
def test_composed_figures_are_the_upstream_facts_and_nothing_else_resolves(
    words: list[str], facility: str, ref: str
) -> None:
    pack, up = market_pack(), upstream_of()
    text = " ".join(words)
    rows = list(instruments())
    rows[2] = rows[2].model_copy(
        update={
            "facility_id": facility,
            "fundamental_view": text,
            "basis": Basis(cp2_refs=(ref,), quotes=()),
        }
    )
    ordering = tuple(dict.fromkeys(row.facility_id for row in rows))
    submission = valuation(
        instruments=tuple(rows),
        preference=valuation().preference.model_copy(update={"ordering": ordering}),
    )
    issues = validate_relative_value(pack, submission, up)
    unknown = facility not in ORDER[2:] and facility not in ORDER[:2]
    duplicate = facility in ORDER[:2]
    bad_ref = ref not in (ASSESSMENT, WEAKNESS)
    assert bool(issues) == (any(w in BAD for w in words) or unknown or duplicate or bad_ref)
    assert (f"instruments[2].facility_id: unknown CP-1 facility {facility}" in issues) == unknown
    assert (f"instruments[2].basis.cp2_refs: unknown CP-2 row {ref}" in issues) == bad_ref
    if issues:
        with pytest.raises(ValueError):
            relative_value(pack, submission, up)
        return
    report = relative_value(pack, submission, up)
    offered = {f.fact_id: f for f in (cp1_fact(pack), *FACILITIES)}
    carried = {f.fact_id: f for f in report.facts if f.table_id == CP1_REFERENCES}
    for fact_id, fact in carried.items():
        source = offered[fact_id]
        place = {"table_id": source.table_id, "row_id": source.row_id, "field": source.field}
        assert fact.model_copy(update=place) == source
    expected = text
    spread = {f.calculation_id: f for f in FACILITIES if f.calculation_id}
    for token, fact in (
        (GOOD[0], offered["T4.18.tlb-fy2025.spread_bps"]),
        (GOOD[1], offered["T4.10.liquidity.FY2025"]),
        (GOOD[2], spread["synthetic-revolver-fy2025-spread_bps"]),
    ):
        expected = expected.replace(token, spelled(fact))
    assert cells_of(report.facts)["T3.1.i03.fundamental_view"].text == expected


# --- Property 2: market-gap propagation is monotone ---------------------------------------------


def settled_cp3(pack: PreparedPack, up: Upstream, submission: RelativeValueSubmission) -> Module:
    """CP-3 settled by the journal's own `settle` over in-memory heads (decision 0007), with no
    store."""
    candidate = cp3_module(relative_value(pack, submission, up), up.bound, 0)
    payload = candidate.model_dump_json()
    modules = {m.module_id: m for m in (up.cp0, up.cp1, up.cp2, *up.optional.values())}
    snapshot = ExecutionSnapshot(
        run=pack.run,
        pack_sha256=pack.content_hash(),
        heads=tuple(head_of(module) for module in modules.values()),
    )
    attempt = Attempt(
        ticket_id="t",
        module_id=MODULE_ID,
        inputs=up.bound,
        number=0,
        payload_sha256=text_sha256(payload),
    )
    _, result = settle(
        snapshot,
        attempt,
        payload,
        lambda _: (),
        pack=pack,
        load=lambda item: modules[item.module_id],
    )
    return result


KINDS = ("observed", "indicative_talk")
CONFIDENCES = ("High", "Medium", "Low", "Insufficient Information")


@settings(max_examples=120, deadline=None)
@given(
    st.lists(st.sampled_from(KINDS), max_size=3),
    st.booleans(),
    st.sampled_from(("accepted", "blocked", "absent")),
    st.sampled_from(CONFIDENCES),
    st.booleans(),
)
def test_missing_market_evidence_and_upstream_gaps_always_limit_and_cap(
    kinds: list[str], cp2_accepted: bool, cp4: str, confidence: str, gapped: bool
) -> None:
    pack = public(market_pack())
    lines = (TLB_LINE, NOTES_LINE, TALK_LINE)
    rows = tuple(
        MarketEvidence(
            source_id=MARKET,
            kind=kind,
            quote=quote(lines[i]),
            as_of="30 June 2026",
            limitation=None,
        )
        for i, kind in enumerate(kinds)
    )
    mislabelled = kinds[2:] == ["observed"]  # the talk line drawn as an observed level
    drawn = set(kinds)
    cp1 = cp1_head(pack)
    up = upstream_of(
        pack,
        cp1=cp1,
        cp2=cp2_head(cp1, accepted=cp2_accepted),
        cp1a=cp1a_head(pack_fixture(), gaps=(), cp2_status="READY"),
        cp4={"accepted": DEFAULT, "blocked": cp4_head(pack, "blocked"), "absent": None}[cp4],
    )
    quotes = tuple(row.quote for row in rows if row.quote is not None)
    limitation = "No sufficient evidence" if confidence == "Insufficient Information" else None
    preference = valuation().preference.model_copy(
        update={
            "basis": Basis(cp2_refs=(ASSESSMENT,), quotes=quotes),
            "confidence": confidence,
            "limitation": limitation,
        }
    )
    plain = tuple(
        row.model_copy(
            update={
                "market_observation": "none",
                "basis": Basis(cp2_refs=row.basis.cp2_refs, quotes=()),
            }
        )
        for row in instruments()
    )
    submission = valuation(
        instruments=plain,
        market_evidence=rows,
        preference=preference,
        risks=valuation().risks,
        gaps=valuation().gaps if gapped else (),
    )
    issues = validate_relative_value(pack, submission, up)
    # The expectation is read from the drawn inputs, not from the code under test.
    talk = 'market_evidence[2]: an observed row quotes indicative talk: "talk"'
    assert (talk in issues) == mislabelled  # indicative talk is never accepted as observed
    none = not drawn
    upstream_cap = (not cp2_accepted) or cp4 != "accepted"
    capped = upstream_cap or drawn == {"indicative_talk"} or none
    capping = any(i.startswith("preference.confidence: capped below High") for i in issues)
    # A missing evidence base is its own issue (Insufficient Information), not a cap.
    assert capping == ((upstream_cap or drawn == {"indicative_talk"}) and confidence == "High")
    if none:
        assert (confidence == "Insufficient Information") == (
            "preference.confidence: Insufficient Information without observed or indicative "
            "market evidence" not in issues
        )
    if capped and confidence == "High":
        held = ("preference.confidence: Insufficient", "preference.confidence: capped below")
        assert any(i.startswith(held) for i in issues)
    if issues:
        assert mislabelled or capping or none or confidence == "Insufficient Information"
        return
    result = settled_cp3(pack, up, submission)
    cells = {f.fact_id: f for f in result.facts}
    if none:
        assert cells["T3.4.preference.confidence"].text == "Insufficient Information"
        assert result.status == "restricted"
    if capped:
        assert cells["T3.4.preference.confidence"].text != "High"
        assert result.limitations or result.inherited_limitations
    if cp4 != "accepted" or none or drawn == {"indicative_talk"} or gapped:
        assert result.status == "restricted"
    if not cp2_accepted:
        assert "Gap (Material): No segment disclosure" in result.inherited_limitations
    if not (
        none
        or gapped
        or cp4 != "accepted"
        or drawn == {"indicative_talk"}
        or confidence == "Insufficient Information"
    ):
        assert result.status == "accepted" and result.limitations == ()


# --- Property 3: the verdict does not depend on row order ---------------------------------------


def _unindexed(issues: tuple[str, ...]) -> set[str]:
    return {re.sub(r"\[[0-9]+\]", "[]", issue) for issue in issues}


@settings(max_examples=80, deadline=None)
@given(st.randoms(use_true_random=False), st.booleans(), st.booleans(), st.booleans())
def test_the_verdict_and_composition_do_not_depend_on_row_order(
    rng: random.Random, unknown: bool, bare: bool, high: bool
) -> None:
    pack, up = market_pack(), upstream_of()
    rows = list(instruments())
    if unknown:
        rows[2] = rows[2].model_copy(
            update={"basis": Basis(cp2_refs=("T2.7.s09", RISK), quotes=())}
        )
    risks = [*valuation().risks]
    if bare:
        risks.append(valuation().risks[0].model_copy(update={"mechanic": "Cover is 2.4x."}))
    preference = valuation().preference.model_copy(update={"confidence": "High" if high else "Low"})
    first = valuation(instruments=tuple(rows), risks=tuple(risks), preference=preference)

    def shuffled(items: list[Any]) -> tuple[Any, ...]:
        out = list(items)
        rng.shuffle(out)
        return tuple(out)

    ordering = shuffled(list(first.preference.ordering))
    second = first.model_copy(
        update={
            "instruments": shuffled(list(first.instruments)),
            "market_evidence": shuffled(list(first.market_evidence)),
            "risks": shuffled(list(first.risks)),
            "gaps": shuffled(list(first.gaps)),
        }
    )
    one = validate_relative_value(pack, first, up)
    two = validate_relative_value(pack, second, up)
    assert bool(one) == bool(two) == (unknown or bare or high)
    assert _unindexed(one) == _unindexed(two)
    if not one:
        a, b = relative_value(pack, first, up), relative_value(pack, second, up)
        assert set(a.limitations) == set(b.limitations)
        assert {f.text for f in a.facts} == {f.text for f in b.facts}
    # The ordering is the output: reordering it changes the composition, never the verdict.
    reordered = first.model_copy(
        update={"preference": first.preference.model_copy(update={"ordering": ordering})}
    )
    assert _unindexed(validate_relative_value(pack, reordered, up)) == _unindexed(one)


# --- Property 4: a quote outside its span is rejected --------------------------------------------

FULL = {f"line:{i}": text for i, text in enumerate(MARKET_TEXT.splitlines(), 1)}


@settings(max_examples=150, deadline=None)
@given(
    st.sampled_from(sorted(FULL)),
    st.sampled_from(sorted(FULL)),
    st.integers(min_value=0, max_value=40),
    st.integers(min_value=4, max_value=30),
)
def test_a_quote_binds_only_inside_its_own_span(
    taken: str, cited: str, start: int, length: int
) -> None:
    fragment = FULL[taken][start : start + length]
    if len(fragment.strip()) < 4 or "talk" in fragment or "indicative" in fragment:
        return  # too short to tell apart, or an observed row may not quote talk at all
    row = MarketEvidence(
        source_id=MARKET,
        kind="observed",
        quote=Quote(source_id=MARKET, locator=cited, quote=fragment),
        as_of="30 June 2026",
        limitation=None,
    )
    found = issues_of(valuation(market_evidence=(*evidence(), row)))
    mismatch = any(i.startswith("market_evidence[3]: Quote/locator mismatch") for i in found)
    # Naive reference: the fragment, its outer and repeated spaces dropped, is a substring of
    # the cited span's text (the fixture is plain ASCII with single spaces and no line wraps).
    assert mismatch == (" ".join(fragment.split()) not in FULL[cited])


# --- differentials: reference existence, staleness and prohibited phrases -----------------------

REF_POOL = (
    ASSESSMENT,
    "T2.7.thesis",
    "T2.7.s01",
    "T2.7.s02",
    WEAKNESS,
    "T2.7.w02",
    "T2.10.kf01",
    "T2.10.kf02",
    RISK,
    "T2.12.g01",
    "T2.12.none",
    "cp2.thesis.thesis",
    f"{CP1_REFERENCES}.ref01",
    "T2.7.s09",
)


@settings(max_examples=120, deadline=None)
@given(
    st.lists(st.lists(st.sampled_from(REF_POOL), min_size=1, max_size=3), min_size=3, max_size=3),
    st.booleans(),
    st.booleans(),
)
def test_reference_existence_matches_a_naive_set_reference(
    refs: list[list[str]], accepted: bool, blocked: bool
) -> None:
    cp1 = cp1_head(market_pack())
    cp2 = cp2_head(cp1, accepted=accepted)
    up = upstream_of(cp1=cp1, cp2=cp2)
    if blocked:
        bound = tuple(
            i.model_copy(update={"status": "blocked"}) if i.input_id == "CP-2" else i
            for i in up.bound
        )
        up = Upstream(
            bound=bound,
            current=bound,
            cp0=up.cp0,
            cp1=up.cp1,
            cp2=up.cp2,
            optional=up.optional,
            inherited=(),
        )
    rows = tuple(
        row.model_copy(update={"basis": row.basis.model_copy(update={"cp2_refs": tuple(r)})})
        for row, r in zip(instruments(), refs, strict=True)
    )
    issues = issues_of(valuation(instruments=rows), up)
    # The naive reference reads the composed CP-2 tables directly: settled rows of T2.*.
    registers = {"T2.1", "T2.7", "T2.10", "T2.11", "T2.12"}
    facts = {f.fact_id: f for f in cp2.facts}
    settled = {
        f"{t.table_id}.{r.row_id}"
        for t in cp2.tables
        if t.table_id in registers
        for r in t.rows
        if any(facts[i].status == "known" for i in r.fact_ids)
    }
    citable = set() if blocked else settled
    naive = {(i, ref) for i, row in enumerate(refs) for ref in row if ref not in citable}
    found = {
        (int(m.group(1)), m.group(2))
        for issue in issues
        if (
            m := re.fullmatch(
                r"instruments\[([0-9]+)\]\.basis\.cp2_refs: unknown CP-2 row (\S+)", issue
            )
        )
    }
    assert found == naive
    assert set(facilities(cp1)) == set(ORDER)


IDS = ("prepared-pack", "CP-0", "CP-1", "CP-1A", "CP-2", "CP-4")
SHAS = ("a" * 64, "b" * 64)
STATUSES = ("accepted", "restricted", "blocked")


@settings(max_examples=150, deadline=None)
@given(
    st.one_of(
        st.none(),
        st.lists(
            st.tuples(st.sampled_from(IDS), st.sampled_from(SHAS), st.sampled_from(STATUSES)),
            max_size=6,
            unique_by=lambda item: item[0],
        ),
    ),
    st.lists(st.sampled_from(IDS), max_size=6, unique=True),
)
def test_staleness_matches_a_naive_set_reference(
    current: list[tuple[str, str, str]] | None, keep: list[str]
) -> None:
    up = upstream_of()
    bound = {i.input_id: i for i in up.bound}
    if current is None:
        state: tuple[Input, ...] | str = "Required upstream is unrun, stale or blocked"
    else:
        generated = {
            i: Input.model_validate({"input_id": i, "sha256": s, "status": t})
            for i, s, t in current
        }
        generated.update({i: bound[i] for i in keep})
        state = tuple(generated.values())
    probe = Upstream(
        bound=up.bound,
        current=state,
        cp0=up.cp0,
        cp1=up.cp1,
        cp2=up.cp2,
        optional=up.optional,
        inherited=(),
    )
    issues = issues_of(valuation(), probe)
    if isinstance(state, str):
        assert [i for i in issues if i.startswith("Stale")] == [f"Stale inputs: {state}"]
        return
    now = {i.input_id: i for i in state}
    naive = {key for key in bound.keys() | now.keys() if bound.get(key) != now.get(key)}
    found = {m.group(1) for i in issues if (m := re.match(r"Stale input (\S+):", i))}
    assert found == naive


SUBJECTS = ("The secured term loan", "The unsecured notes", "The revolver")
ALLOWED = (
    "is better compensated than the notes",
    "is preferred over the unsecured notes",
    "comes ahead of the notes in the ordering",
    "is senior to the notes",
    "offers more spread for its risk",
    "is the most attractive of the issuer's instruments",
)
FORBIDDEN = {
    "should be bought; buy it": "instrument action",
    "is a sell": "instrument action",
    "merits an overweight": "instrument action",
    "warrants an underweight": "instrument action",
    "is what we recommend": "instrument action",
    "is our recommendation": "instrument action",
    "is a reason to switch into the loan": "instrument action",
    "is a reason to switch out of the notes": "instrument action",
    "ranks above peers": "peer ranking",
    "looks cheap versus peers": "peer ranking",
    "would recover in full": "recovery conclusion",
    "has an expected recovery near par": "recovery conclusion",
}


@settings(max_examples=200, deadline=None)
@given(
    st.lists(
        st.tuples(st.sampled_from(SUBJECTS), st.sampled_from((*ALLOWED, *FORBIDDEN))),
        min_size=1,
        max_size=3,
    )
)
def test_the_prohibited_phrase_check_matches_a_naive_reference(
    clauses: list[tuple[str, str]],
) -> None:
    text = " ".join(f"{subject} {middle}." for subject, middle in clauses)
    found = {
        m.group(1)
        for issue in prohibited_issues("t", text, kinds=PROHIBITED_KINDS)
        if (m := re.search(r"prohibited conclusion \(([^)]+)\)", issue))
    }
    naive = {FORBIDDEN[middle] for _, middle in clauses if middle in FORBIDDEN}
    assert found == naive


TOKENS = (
    "buy",
    "the",
    "notes",
    "ranks above",
    "would recover",
    "prefer the",
    "recovery rate",
    "we recommend",
    "switch into",
    "overweight",
    "sell",
)


@settings(max_examples=100, deadline=None)
@given(st.lists(st.sampled_from(TOKENS), max_size=8).map(" ".join))
def test_the_default_prohibited_kinds_are_cp1a_s_unchanged(text: str) -> None:
    default = prohibited_issues("t", text)
    assert default == prohibited_issues("t", text, kinds=tuple(PROHIBITED))
    assert not any("(instrument action)" in issue for issue in default)


def test_an_unknown_prohibited_kind_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unknown prohibited kind"):
        prohibited_issues("t", "text", kinds=("buy signal",))


# --- the Front Page: the relative-value block fills, with field parity (SYNTHETIC) --------------


def snapshot_with_cp3() -> tuple[View, Module]:
    """The SYNTHETIC Credit Snapshot view with its synthetic CP-3 rows replaced by a composed
    CP-3 module. Its CP-1 head is the fixture's own CP-1 figures with the display-shaped T4.18
    replaced by the canonical SYNTHETIC facilities (CP-3 names facilities by `facility_id`)."""
    view = credit_snapshot_view()
    pack = market_pack()
    by_id = {m.module_id: m for m in view.modules}
    figures = tuple(f for f in by_id["CP-1"].facts if f.table_id != "T4.18")
    cp1 = cp1_head(pack, (*figures, *FACILITIES))
    up = upstream_of(pack, cp1=cp1)
    assert validate_relative_value(pack, valuation(), up) == ()
    module = cp3_module(relative_value(pack, valuation(), up), up.bound, 0)
    shown = ModuleView(
        module_id=MODULE_ID,
        title=by_id[MODULE_ID].title,
        aliases=by_id[MODULE_ID].aliases,
        status="candidate",
        artifact_sha256=module.content_hash(),
        facts=module.facts,
        tables=module.tables,
        claims=module.claims,
    )
    modules = tuple(shown if m.module_id == MODULE_ID else m for m in view.modules)
    return view.model_copy(update={"modules": modules}), module


def maps_with_cp3() -> tuple[BindingMap, ...]:
    return (*(m for m in CREDIT_SNAPSHOT_MAPS if m.module_id != MODULE_ID), CP3)


def test_the_relative_value_block_fills_with_field_parity_on_the_synthetic_snapshot() -> None:
    view, module = snapshot_with_cp3()
    assert validate_bindings(view, maps_with_cp3()) == ()  # every CP-3 fact bound exactly once
    pathway = next(p for p in pathways() if p.id == "credit_snapshot")
    blocks = {b.block_id: b for b in build(view, pathway, maps_with_cp3()).blocks}
    block = blocks["relative-value"]
    assert block.state == "collapsed" and block.owner == "CP-3" and "Synthetic" in block.tags
    bound = [f for f in module.facts if f.table_id == RELATIVE_VALUE]
    gaps = gap_ids(view)
    expected = {f.fact_id: expected_text(f, gaps.get((MODULE_ID, f.fact_id))) for f in bound}
    assert len(block.lines) == len(bound) == 4
    actual = {
        fact.fact_id: "".join(run.text for run in line.runs if run.kind != "fig")
        for fact, line in zip(bound, block.lines, strict=True)
    }
    parity = parity_record(expected, actual)
    assert parity["compared"] == 4 and not parity["mismatches"], parity
    summary = block.summary or ""  # the collapsed block shows the preference line, shortened
    assert summary.startswith("Preference: Term Loan B-2 > ")
    assert str(bound[0].text).startswith(summary.rstrip("…"))
    assert [str(f.text).split(":")[0] for f in bound] == [
        "Preference",
        "Term Loan B-2",
        "Senior notes due 2030",
        "Revolving credit facility",
    ]
    assert all(line.label is None for line in block.lines)  # unlabelled: the name leads the text


def test_the_binding_map_places_the_tables_on_the_rails() -> None:
    destinations = {e.fact_coord.table_id: e.block_id for e in CP3.entries}
    assert destinations == {
        RELATIVE_VALUE: "relative-value",
        "T3.1": "evidence",
        "T3.3": "evidence",
        "T3.4": "evidence",
        "T3.9": "evidence",
        CP1_REFERENCES: "evidence",
        "T3.10": "limitations",
    }
    assert all(e.cell_slot.startswith("cp3-") for e in CP3.entries)
    assert CP3.module_id == MODULE_ID


# --- method text and the r14 coverage map -------------------------------------------------------


def test_the_method_text_names_the_tables_and_the_market_rules_and_states_no_figure() -> None:
    brief = files("deploy_vii").joinpath("methods", "cp3.md").read_text(encoding="utf-8")
    assert len(brief.splitlines()) < 100
    for table_id in REQUIRED_TABLES:
        assert f"`{table_id}`" in brief
    for anchor in (
        "decision 0005",
        "SKILL.md",
        "Reader question",
        "cp2_refs",
        "third_party",
        "indicative_talk",
        "never a market level",
        "Prohibited",
        "ordering",
        "Insufficient Information",
    ):
        assert anchor in brief
    keys = {"cp2_refs", "cp2_rows", "cp1_facts", "cp1_facilities", "T4.18", "T4.10"}
    assert {f.strip("`") for f in bare_figures(brief)} <= {*REQUIRED_TABLES, "0005", *keys}


def test_the_required_tables_are_r14_cp3_ids() -> None:
    coverage = json.loads(Path("docs/methodology/r14-coverage.json").read_text(encoding="utf-8"))
    entry = next(m for m in coverage["modules"] if m["module_id"] == MODULE_ID)
    assert set(REQUIRED_TABLES) <= set(entry["artifact_contract"]["required_table_ids"])


def test_a_submission_built_around_validation_reports_shape_issues() -> None:
    bogus = valuation().preference.model_copy(update={"confidence": "Certain"})
    found = issues_of(valuation(preference=bogus))
    assert any(i.startswith("preference.confidence: Input should be") for i in found)
    with pytest.raises(ValueError, match=r"preference\.confidence"):
        relative_value(market_pack(), valuation(preference=bogus), upstream_of())


def test_a_figure_free_valuation_carries_no_cp1_facts() -> None:
    plain = instruments()[0].model_copy(update={"fundamental_view": "The loan is secured."})
    report = relative_value(
        market_pack(), valuation(instruments=(plain, *instruments()[1:])), upstream_of()
    )
    assert CP1_REFERENCES not in {t.table_id for t in report.tables}
    assert cp3_module(report, (), 0).facts == report.facts


def test_a_cp1a_head_over_the_market_pack_assesses_the_sheet() -> None:
    pack = market_pack()
    head_ = cp1a_module(business_context(pack, cp1a_submission(pack)), (), 0)
    assert head_.module_id == "CP-1A"


def test_facilities_are_the_known_facility_ids_of_t4_18_merged_across_periods() -> None:
    later = tuple(
        f.model_copy(
            update={
                "fact_id": f.fact_id.replace("fy2025", "ltm"),
                "row_id": "tlb-ltm",
                "calculation_id": "synthetic-tlb-ltm" if f.amount else None,
            }
        )
        for f in FACILITIES
        if f.row_id == "tlb-fy2025" and f.field in {"facility_id", "spread_bps"}
    )
    unnamed = Fact(
        fact_id="T4.18.x.facility_id",
        label="facility_id",
        table_id="T4.18",
        row_id="x",
        field="facility_id",
        status="missing",
        limitation="not stated",
    )
    found = facilities(cp1_head(market_pack(), (*FACILITIES, *later, unnamed)))
    assert list(found) == list(ORDER)
    assert [f.fact_id for f in found["tlb"].figures] == [
        "T4.18.tlb-fy2025.spread_bps",
        "T4.18.tlb-ltm.spread_bps",
    ]
    assert dict(found["tlb"].terms)["maturity_date"] == "2031-06-30"
    # The display-shaped Credit Snapshot T4.18 carries no facility_id cell: no facility.
    snapshot = next(m for m in credit_snapshot_view().modules if m.module_id == "CP-1")
    assert facilities(cp1_head(market_pack(), snapshot.facts)) == {}


def test_a_malformed_quote_or_text_is_an_issue_not_a_crash() -> None:
    empty = evidence()[0].model_copy(
        update={"quote": Quote(source_id=MARKET, locator="", quote=TLB_LINE[1])}
    )
    assert "market_evidence[0]: malformed citation (empty locator or quote)" in issues_of(
        valuation(market_evidence=(empty, *evidence()[1:]))
    )
    broken = instruments()[2].model_copy(
        update={
            "fundamental_view": "Spread {T4.18.revolver",
            "basis": Basis(cp2_refs=(), quotes=()),
        }
    )
    found = issues_of(valuation(instruments=(*instruments()[:2], broken)))
    assert any(i.startswith("instruments[2].fundamental_view: Malformed run text") for i in found)
    assert (
        "instruments[2]: an instrument cites a CP-2 row, a market_evidence quote or a CP-1 figure"
    ) in found
