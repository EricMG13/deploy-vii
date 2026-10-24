"""CP-6 committee challenge (task 8.5): the contract, its Python-only validator, the composed
tables, the Front Page bindings, the call-band values and the method text.

SYNTHETIC data only: the pack is the CP-3 market fixture (`tests/product/cp3_market.py`), the
CP-1, CP-1A and CP-2 heads are the CP-3 test's, the CP-3 head is composed by Python from the
CP-3 test's submission and the CP-5 head by Python from the CP-5 test's review helpers over
those heads. The Front Page tests run over the SYNTHETIC Credit Snapshot fixture. Decision 0012:
the key-area rules (figure and reference identity, gap propagation, row-order independence, the
call-band mapping, reference existence, staleness and the prohibited-phrase boundary) are
Hypothesis properties, four of them differentials against naive references.
"""

import json
import random
import re
from collections.abc import Mapping
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any, get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.bindings import BindingMap, validate_bindings
from deploy_vii.bindings.cp2 import CP2 as CP2_MAP
from deploy_vii.bindings.cp6 import CP6
from deploy_vii.business_context import CP1_REFERENCES, PROHIBITED, Confidence, Gap, spelled
from deploy_vii.contracts import Claim, Fact, Input, Module, ModuleView, View
from deploy_vii.cp2_synthesis import STRENGTHS, THESIS, WEAKNESSES
from deploy_vii.cp3_relative_value import cp3_module, relative_value, submit_cp3_step
from deploy_vii.cp5_integrity import (
    ClaimRef,
    Contradiction,
    ReviewScope,
    cp5_module,
    integrity_review,
    review_scope,
    submit_cp5_step,
)
from deploy_vii.cp6_committee import (
    ACTION_BIAS_FACT,
    ACTION_BIASES,
    CALL_SCALE,
    COMMITTEE_CHALLENGE,
    CONFIDENCE_FACT,
    CONFIDENCES,
    CP6_ACTIONS,
    MODULE_ID,
    REQUIRED_TABLES,
    STEP_ID,
    STRENGTH_CHALLENGES,
    THESIS_CHALLENGE,
    TRADE_TERMS,
    WEAKNESS_CHALLENGES,
    Basis,
    CommitteeReport,
    CommitteeSubmission,
    Recommendation,
    RecoveryView,
    Risk,
    ThesisChallenge,
    Upstream,
    call_scale,
    committee_challenge,
    context_block,
    cp5_review,
    cp6_module,
    cp6_prohibited_issues,
    cp6_upstream,
    settled_call,
    submit_cp6_step,
    validate_committee,
)
from deploy_vii.cp6_committee import _validate_step as validate_step
from deploy_vii.execution import Attempt, Execution, ExecutionSnapshot, head_of, settle, text_sha256
from deploy_vii.live.schema import relax, schema_relaxations, strict_copy, strict_schema
from deploy_vii.preparation import PreparedPack
from deploy_vii.prose import bare_figures
from deploy_vii.registry import StepChain, pack_source_steps
from deploy_vii.report_view import CallItem, build, pathways
from tests.product.cp3_market import FACILITIES, TLB_SPREAD, market_pack
from tests.product.credit_snapshot import CREDIT_SNAPSHOT_MAPS, credit_snapshot_view
from tests.product.oracle import expected_text, gap_ids, parity_record
from tests.product.test_business_context import cp1_fact, pack_fixture
from tests.product.test_cp2_synthesis import cp1a_head
from tests.product.test_cp3_relative_value import (
    BAD,
    GOOD,
    WORDS,
    cp0_head,
    cp1_head,
    cp2_head,
    public,
    unquoted,
    valuation,
)
from tests.product.test_cp3_relative_value import journal as cp3_journal
from tests.product.test_cp3_relative_value import upstream_of as cp3_upstream_of
from tests.product.test_cp5_integrity import review_all, scope_of

LIQUIDITY = "{T4.10.liquidity.FY2025|US$ m}"
ASSESSMENT = "T2.1.assessment"
THESIS_ROW = "T2.7.thesis"
STRENGTH = "T2.7.s01"
WEAKNESS = "T2.7.w01"
FINDING = "T2.10.kf02"
CP2_RISK = "T2.11.r01"
PREFERENCE = "T3.4.preference"
CP3_RISK = "T3.9.r01"
ORDER = ("CP-0", "CP-1", "CP-1A", "CP-2", "CP-3", "CP-5")
# The step chain the registration commit adds: one settling step, no pack sources (no quotes).
CHAIN = StepChain(module_id=MODULE_ID, cell="cp6", steps=(STEP_ID,), pack_sources=frozenset())


# --- fixtures: SYNTHETIC upstream heads -------------------------------------------------------


def status_of(module: Module) -> Module:
    """A composed candidate as the head settlement would store (limitations restrict)."""
    return module.model_copy(update={"status": "restricted" if module.limitations else "accepted"})


def cp3_head(pack: PreparedPack, cp1: Module, cp2: Module, *, evidence: bool = True) -> Module:
    """CP-3 composed by Python over `cp1` and `cp2`: the CP-3 test's valuation (observed
    evidence) or, without `evidence`, its Insufficient Information preference."""
    up = cp3_upstream_of(pack, cp1=cp1, cp2=cp2)
    submission = valuation() if evidence else unquoted()
    return status_of(cp3_module(relative_value(pack, submission, up), up.bound, 0))


def cp5_head(
    pack: PreparedPack,
    heads: tuple[Module, ...],
    support: dict[tuple[str, str], str] | None = None,
    contradictions: tuple[Contradiction, ...] = (),
) -> Module:
    """CP-5 composed by Python over `heads` with the CP-5 test's reviewer (`review_all`)."""
    scope = scope_of(pack, heads)
    submission = review_all(scope, support).model_copy(update={"contradictions": contradictions})
    report = integrity_review(scope, submission)
    return cp5_module(report, scope.inputs, 0).model_copy(update={"status": report.status})


@lru_cache(maxsize=1)
def heads() -> Mapping[str, Module]:
    """The default heads: CP-5 restricted by its own findings over CP-1, CP-1A, CP-2, CP-3."""
    pack = market_pack()
    cp1 = cp1_head(pack)
    cp1a = cp1a_head(pack_fixture())
    cp2 = cp2_head(cp1)
    cp3 = cp3_head(pack, cp1, cp2)
    return MappingProxyType(
        {
            "CP-0": cp0_head(pack),
            "CP-1": cp1,
            "CP-1A": cp1a,
            "CP-2": cp2,
            "CP-3": cp3,
            "CP-5": cp5_head(pack, (cp1, cp1a, cp2, cp3)),
        }
    )


@lru_cache(maxsize=1)
def clean_cp5() -> Module:
    """An accepted CP-5: its review of the CP-3 head alone records no finding."""
    head = cp5_head(market_pack(), (heads()["CP-3"],))
    assert head.status == "accepted", head.limitations
    return head


@lru_cache(maxsize=1)
def flagging_cp5() -> Module:
    """A restricted CP-5 that marks CP-2's assessment unsupported and records a contradiction
    between CP-2's second key finding and CP-3's preference."""
    h = heads()
    contradiction = Contradiction(
        claim_refs=(
            ClaimRef(producer_module="CP-2", claim_ref="T2.10.kf02"),
            ClaimRef(producer_module="CP-3", claim_ref=PREFERENCE),
        ),
        nature="Opposite readings of disclosure",
        rationale="The finding calls disclosure thin while the preference relies on it",
        severity="Material",
    )
    return cp5_head(
        market_pack(),
        (h["CP-2"], h["CP-3"]),
        {("CP-2", ASSESSMENT): "unsupported"},
        (contradiction,),
    )


@lru_cache(maxsize=1)
def blind_cp3() -> Module:
    """CP-3 with no market evidence: its preference is Insufficient Information."""
    h = heads()
    return cp3_head(market_pack(), h["CP-1"], h["CP-2"], evidence=False)


def entry(module: Module) -> Input:
    return Input(input_id=module.module_id, sha256=module.content_hash(), status=module.status)


class _Default:
    """The sentinel `upstream_of` reads as "the fixture's own head"."""


DEFAULT = _Default()


def blocked_cp1a() -> Module:
    pack = market_pack()
    run = pack.run
    return Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id="CP-1A",
        status="blocked",
        limitations=("Malformed candidate: (root): Invalid JSON",),
    )


def upstream_of(
    *,
    cp2: Module | None = None,
    cp3: Module | None = None,
    cp5: Module | None = None,
    cp1a: Module | _Default | None = DEFAULT,
    current: tuple[Input, ...] | str | None = None,
    blocked: frozenset[str] = frozenset(),
) -> Upstream:
    """In-memory heads in plan order; `cp1a` None leaves the optional input unbound; `blocked`
    adds blocked ancestors up the chain (as `execution.blocked_ancestors` reports them)."""
    h = heads()
    chosen: dict[str, Module | None] = {
        **h,
        "CP-1A": h["CP-1A"] if isinstance(cp1a, _Default) else cp1a,
        "CP-2": cp2 or h["CP-2"],
        "CP-3": cp3 or h["CP-3"],
        "CP-5": cp5 or h["CP-5"],
    }
    present = {k: v for k, v in chosen.items() if v is not None}
    bound = (
        Input(input_id="prepared-pack", sha256=market_pack().content_hash()),
        *(entry(present[k]) for k in ORDER if k in present),
    )
    return Upstream(
        bound=bound,
        current=bound if current is None else current,
        cp0=present["CP-0"],
        cp1=present["CP-1"],
        cp2=present["CP-2"],
        cp3=present["CP-3"],
        cp5=present["CP-5"],
        optional={"CP-1A": present["CP-1A"]} if "CP-1A" in present else {},
        blocked=blocked | {i.input_id for i in bound if i.status == "blocked"},
        inherited=(),
    )


def basis(cp2: tuple[str, ...] = (), cp3: tuple[str, ...] = (), cp5: tuple[str, ...] = ()) -> Basis:
    return Basis(cp2_refs=cp2, cp3_refs=cp3, cp5_refs=cp5)


def challenges() -> tuple[ThesisChallenge, ...]:
    return (
        ThesisChallenge(
            thesis_ref=THESIS_ROW,
            counter_case="Liquidity alone may not carry the credit if maturities come early.",
            evidence_for=f"Liquidity was {LIQUIDITY} in FY2025.",
            evidence_against="The maturity profile is not disclosed.",
            would_change_view="A disclosed debt schedule with no near-term maturity.",
            basis=basis(cp2=(WEAKNESS, CP2_RISK)),
        ),
        ThesisChallenge(
            thesis_ref=STRENGTH,
            counter_case="One reported figure is a thin base for a liquidity strength.",
            evidence_for="The figure is reported in the filing.",
            evidence_against="No cash flow statement corroborates it.",
            would_change_view="A full set of statements for the same period.",
            basis=basis(cp2=(FINDING,)),
        ),
        ThesisChallenge(
            thesis_ref=WEAKNESS,
            counter_case="Thin segment disclosure may matter less for a single-market issuer.",
            evidence_for="The issuer reports one annual figure.",
            evidence_against="The business lines are not described.",
            would_change_view="Segment notes showing concentrated revenue.",
            basis=basis(cp2=("T2.12.g01",)),
        ),
        ThesisChallenge(
            thesis_ref=FINDING,
            counter_case="A cautious posture may already be priced into the secured loan.",
            evidence_for="The dealer sheet shows the loan near par.",
            evidence_against="The notes sit at a discount.",
            would_change_view="Observed levels for every instrument.",
            basis=basis(cp3=("T3.1.i01", "T3.1.i02")),
        ),
    )


def recommendation(**changes: object) -> Recommendation:
    base = Recommendation(
        action_bias="Neutral",
        rationale=f"Liquidity of {LIQUIDITY} offsets thin disclosure, so the bias is neutral.",
        conditions="A debt schedule and segment notes would allow a directional view.",
        confidence="Low",
        limitation="The integrity review is restricted",
        basis=basis(cp2=(ASSESSMENT, THESIS_ROW), cp3=(PREFERENCE,)),
    )
    return base.model_copy(update=changes)


def recovery() -> RecoveryView:
    return RecoveryView(
        subject="Senior notes",
        view="No recovery view: no covenant or legal evidence reaches the committee.",
        confidence="Insufficient Information",
        limitation="No CP-4 evidence reaches CP-6",
        basis=basis(),
    )


def committee(**changes: object) -> CommitteeSubmission:
    """A valid synthetic submission over `upstream_of()`."""
    base = CommitteeSubmission(
        recommendation=recommendation(),
        thesis_challenges=challenges(),
        recovery_view=(recovery(),),
        risks=(
            Risk(
                risk="Disclosure",
                mechanic="Thin disclosure hides the maturity profile.",
                implication="The bias may move when fuller filings arrive.",
                severity="Material",
                basis=basis(cp2=(CP2_RISK,), cp3=(CP3_RISK,)),
            ),
        ),
        gaps=(
            Gap(
                gap="No covenant or legal evidence",
                why_it_matters="Recovery cannot be judged",
                affected_analysis="Recovery view",
                severity="Material",
                action="Run covenant and legal analysis",
            ),
        ),
    )
    return base.model_copy(update=changes)


def issues_of(submission: CommitteeSubmission, up: Upstream | None = None) -> tuple[str, ...]:
    return validate_committee(market_pack(), submission, up or upstream_of())


def cells_of(module_or_report: Module | CommitteeReport) -> dict[str, Fact]:
    return {f.fact_id: f for f in module_or_report.facts}


# --- acceptance and composition ---------------------------------------------------------------


def test_a_valid_submission_composes_the_tables() -> None:
    pack, up = market_pack(), upstream_of()
    assert validate_committee(pack, committee(), up) == ()
    report = committee_challenge(pack, committee(), up)
    tables = {t.table_id: t for t in report.tables}
    assert REQUIRED_TABLES == ("T6A.4", "T6E.4", "T6E.6", "T6E.7", "T6E.11")
    assert tables.keys() == {
        *REQUIRED_TABLES,
        COMMITTEE_CHALLENGE,
        THESIS_CHALLENGE,
        STRENGTH_CHALLENGES,
        WEAKNESS_CHALLENGES,
        CP1_REFERENCES,
    }
    cells = cells_of(report)
    liquidity = spelled(cp1_fact(pack))
    assert cells["T6A.4.recommendation.action_bias"].text == "Neutral"
    assert cells["T6A.4.recommendation.confidence"].text == "Low"
    assert cells["T6A.4.recommendation.rationale"].text == (
        f"Liquidity of {liquidity} offsets thin disclosure, so the bias is neutral."
    )
    assert cells["T6A.4.recommendation.basis"].text == (
        "CP-2 T2.1.assessment (Credit assessment); CP-2 T2.7.thesis (Thesis); "
        "CP-3 T3.4.preference (Preference); CP-1 Liquidity · FY2025"
    )
    assert [r.label for r in tables["T6E.4"].rows] == [
        "Thesis",
        "Liquidity",
        "Disclosure",
        "Key finding 2",
    ]
    assert cells["T6E.4.c01.thesis_ref"].text == "CP-2 T2.7.thesis (Thesis)"
    assert cells["T6E.4.c04.basis"].text == (
        "CP-3 T3.1.i01 (Term Loan B-2); CP-3 T3.1.i02 (Senior notes due 2030)"
    )
    assert cells["T6E.6.v01.confidence"].text == "Insufficient Information"
    assert cells["T6E.11.g01.gap_id"].text == "CP-6-GAP-001"
    assert all(f.amount is None for f in report.facts if f.table_id != CP1_REFERENCES)
    assert [c.claim_id for c in report.claims] == [
        "T6A.4.recommendation",
        "T6E.4.c01",
        "T6E.4.c02",
        "T6E.4.c03",
        "T6E.4.c04",
    ]
    assert all(c.citations == () for c in report.claims)  # CP-6 quotes no pack source
    assert report.schema_version == "committee-challenge/1"
    module = cp6_module(report, up.bound, 0)
    assert module.module_id == MODULE_ID and module.status == "candidate"
    assert module.inputs[-1].input_id == "committee-submission"
    assert module.inputs[:-1] == up.bound


def test_own_limitations_name_the_gaps_the_recovery_gap_and_the_cp5_handoff() -> None:
    up = upstream_of()
    report = committee_challenge(market_pack(), committee(), up)
    ids = [finding.finding_id for finding in cp5_review(up.cp5).findings]
    assert ids and up.status("CP-5") == "restricted"
    assert report.limitations == (
        "Gap (Material): No covenant or legal evidence",
        "CP-5 handoff caps the confidence below High: CP-5 is restricted; CP-5 marks 2 claims "
        f"unsupported or partly supported; findings {', '.join(ids)}",
        "Recovery view is Insufficient Information: No CP-4 evidence reaches CP-6",
    )


def test_the_committee_challenge_table_leads_with_the_action_bias() -> None:
    report = committee_challenge(market_pack(), committee(), upstream_of())
    front = [f for f in report.facts if f.table_id == COMMITTEE_CHALLENGE]
    assert [f.label for f in front] == [
        "Action bias",
        "Thesis",
        "Liquidity",
        "Disclosure",
        "Key finding 2",
    ]
    liquidity = spelled(cp1_fact(market_pack()))
    assert front[0].text == (
        f"Action bias: Neutral (confidence Low). Liquidity of {liquidity} offsets thin "
        "disclosure, so the bias is neutral. Conditions: A debt schedule and segment notes would "
        "allow a directional view."
    )
    assert front[2].text == (
        "Liquidity: One reported figure is a thin base for a liquidity strength. Would change "
        "the view: A full set of statements for the same period."
    )
    assert all(f.value_class == "analyst_judgment" for f in front)


def test_referenced_cp1_figures_are_carried_verbatim() -> None:
    report = committee_challenge(market_pack(), committee(), upstream_of())
    carried = [f for f in report.facts if f.table_id == CP1_REFERENCES]
    upstream = cp1_fact(market_pack())
    assert [f.fact_id for f in carried] == [upstream.fact_id]
    place = {"table_id": upstream.table_id, "row_id": upstream.row_id, "field": upstream.field}
    assert carried[0].model_copy(update=place) == upstream


def test_empty_registers_are_explicit_rows_and_required_ones_limit() -> None:
    empty = committee(thesis_challenges=(), recovery_view=(), risks=(), gaps=())
    report = committee_challenge(market_pack(), empty, upstream_of())
    cells = cells_of(report)
    for title in ("committee challenges", "recovery view", "committee risks"):
        assert f"No {title} rows in the CP-6 submission" in report.limitations
    assert cells["T6E.4.none.counter_case"].status == "missing"
    assert cells["T6E.11.none.gap"].status == "not_applicable"
    tables = {t.table_id for t in report.tables}
    # A CP-2 row without a challenge stays empty: no challenge-column table is invented.
    assert not tables & {THESIS_CHALLENGE, STRENGTH_CHALLENGES, WEAKNESS_CHALLENGES}


# --- references and figures -----------------------------------------------------------------


def test_unknown_refs_and_thesis_refs_are_rejected() -> None:
    stray = recommendation(basis=basis(cp2=("T2.7.s09",), cp3=("T3.4.none",), cp5=("T5.9.f999",)))
    found = issues_of(committee(recommendation=stray))
    assert "recommendation.basis.cp2_refs: unknown CP-2 row T2.7.s09" in found
    assert "recommendation.basis.cp3_refs: unknown CP-3 row T3.4.none" in found
    assert "recommendation.basis.cp5_refs: unknown CP-5 row or finding T5.9.f999" in found
    risk = challenges()[0].model_copy(update={"thesis_ref": CP2_RISK})
    found = issues_of(committee(thesis_challenges=(risk, *challenges()[1:])))
    assert (
        "thesis_challenges[0].thesis_ref: T2.11.r01 is not a CP-2 thesis, strength, weakness or "
        "key finding row"
    ) in found
    twice = issues_of(committee(thesis_challenges=(*challenges(), challenges()[1])))
    assert "thesis_challenges: T2.7.s01 is challenged more than once" in twice


def test_a_finding_id_and_its_register_row_are_both_cp5_refs() -> None:
    up = upstream_of()
    finding = cp5_review(up.cp5).findings[0]
    assert re.fullmatch(r"CP-5-FINDING-[0-9]{3}", finding.finding_id)
    for ref in (finding.finding_id, finding.ref, "T5B.8.status"):
        rec = recommendation(basis=basis(cp2=(THESIS_ROW,), cp5=(ref,)))
        assert issues_of(committee(recommendation=rec), up) == ()
    report = committee_challenge(
        market_pack(),
        committee(
            recommendation=recommendation(
                basis=basis(cp2=(THESIS_ROW,), cp5=(finding.finding_id, finding.ref))
            )
        ),
        up,
    )
    cell = cells_of(report)["T6A.4.recommendation.basis"].text
    assert cell.count(finding.finding_id) == 1  # one ref, however it is named
    assert f"CP-5 {finding.ref} ({finding.finding_id})" in cell


def test_every_row_needs_a_basis() -> None:
    bare = challenges()[1].model_copy(update={"basis": basis()})
    found = issues_of(committee(thesis_challenges=(*challenges()[:1], bare, *challenges()[2:])))
    assert "thesis_challenges[1]: a row cites a CP-2, CP-3 or CP-5 row or a CP-1 figure" in found
    risk = committee().risks[0].model_copy(update={"basis": basis()})
    assert "risks[0]: a row cites a CP-2, CP-3 or CP-5 row or a CP-1 figure" in issues_of(
        committee(risks=(risk,))
    )


def test_a_bare_figure_and_an_unoffered_reference_are_rejected() -> None:
    bare = recommendation(rationale="Leverage of 3.5x supports a neutral bias.")
    assert any(
        i.startswith("recommendation.rationale:") and "3.5x" in i
        for i in issues_of(committee(recommendation=bare))
    )
    ghost = recommendation(rationale="Cover of {T4.10.interest_cover.FY2025|x} is unknown.")
    assert any(
        i.startswith("recommendation.rationale:")
        for i in issues_of(committee(recommendation=ghost))
    )
    blank = recommendation(conditions="  ")
    assert "recommendation.conditions: empty text" in issues_of(committee(recommendation=blank))


# --- the recommendation boundary ------------------------------------------------------------


def test_insufficient_information_goes_with_its_confidence_and_states_its_limitation() -> None:
    split = recommendation(action_bias="Insufficient Information", confidence="Low")
    assert (
        "recommendation: action_bias and confidence are Insufficient Information together"
    ) in issues_of(committee(recommendation=split))
    silent = recommendation(
        action_bias="Insufficient Information",
        confidence="Insufficient Information",
        limitation=None,
    )
    assert "recommendation: an Insufficient Information action bias states its limitation" in (
        issues_of(committee(recommendation=silent))
    )


def test_no_cp3_market_evidence_forces_insufficient_information() -> None:
    up = upstream_of(cp3=blind_cp3())
    assert "CP-3 records no observed or indicative market evidence" in up.insufficient
    assert "CP-3's preference is Insufficient Information" in up.insufficient
    found = issues_of(committee(thesis_challenges=challenges()[:3]), up)
    assert (
        "recommendation.action_bias: Insufficient Information because CP-3 records no observed or "
        "indicative market evidence; CP-3's preference is Insufficient Information"
    ) in found
    honest = recommendation(
        action_bias="Insufficient Information",
        confidence="Insufficient Information",
        limitation="No market evidence for relative value",
    )
    submission = committee(recommendation=honest, thesis_challenges=challenges()[:3])
    assert issues_of(submission, up) == ()
    report = committee_challenge(market_pack(), submission, up)
    assert (
        "Action bias is Insufficient Information: No market evidence for relative value"
    ) in report.limitations


def test_a_recommendation_resting_only_on_cp5_flagged_claims_is_rejected() -> None:
    up = upstream_of(cp5=flagging_cp5())
    review = cp5_review(up.cp5)
    assert {("CP-2", ASSESSMENT), ("CP-2", FINDING), ("CP-3", PREFERENCE)} <= review.flagged
    flagged = recommendation(
        rationale="Thin disclosure keeps the bias neutral.",
        basis=basis(cp2=(ASSESSMENT, FINDING), cp3=(PREFERENCE,)),
    )
    assert (
        "recommendation.basis: rests only on CP-5-flagged claims (CP-2 T2.1.assessment, "
        "CP-2 T2.10.kf02, CP-3 T3.4.preference)"
    ) in issues_of(committee(recommendation=flagged), up)
    # A row that bears no claim (a thesis point) is never reviewed, so it is no support.
    with_row = flagged.model_copy(update={"basis": basis(cp2=(ASSESSMENT, THESIS_ROW))})
    assert (
        "recommendation.basis: rests only on CP-5-flagged claims (CP-2 T2.1.assessment)"
    ) in issues_of(committee(recommendation=with_row), up)
    with_claim = flagged.model_copy(update={"basis": basis(cp2=(ASSESSMENT,), cp3=("T3.1.i01",))})
    assert issues_of(committee(recommendation=with_claim), up) == ()
    with_figure = flagged.model_copy(update={"rationale": recommendation().rationale})
    assert issues_of(committee(recommendation=with_figure), up) == ()
    only_cp5 = flagged.model_copy(update={"basis": basis(cp5=(review.findings[0].finding_id,))})
    assert (
        "recommendation.basis: cites no CP-2 or CP-3 claim row or CP-1 figure CP-5 leaves "
        "unflagged" in (issues_of(committee(recommendation=only_cp5), up))
    )
    # An Insufficient Information bias may rest on CP-5's findings alone.
    honest = only_cp5.model_copy(
        update={"action_bias": "Insufficient Information", "confidence": "Insufficient Information"}
    )
    assert issues_of(committee(recommendation=honest), up) == ()


def test_gap_and_limitation_rows_are_never_support_for_a_call() -> None:
    """Fix round 1 ruling 3: support comes from claim-bearing rows or CP-1 figures; a gap row
    is cited only as the basis of a limitation."""
    up = upstream_of(cp5=clean_cp5())
    gap = recommendation(
        action_bias="Overweight",
        rationale="Thin disclosure is the open question.",
        basis=basis(cp2=("T2.12.g01",), cp3=("T3.10.g01",)),
    )
    assert (
        "recommendation.basis: cites no CP-2 or CP-3 claim row or CP-1 figure CP-5 leaves unflagged"
    ) in issues_of(committee(recommendation=gap), up)
    claimed = gap.model_copy(
        update={"basis": basis(cp2=("T2.12.g01", FINDING), cp3=("T3.10.g01",))}
    )
    assert issues_of(committee(recommendation=claimed), up) == ()


def test_a_figure_in_the_limitation_is_no_support_for_the_recommendation() -> None:
    """Confidence review: a CP-1 figure named only in the limitation once counted as the
    unflagged support of a recommendation resting on flagged claims."""
    up = upstream_of(cp5=flagging_cp5())
    rec = recommendation(
        rationale="Thin disclosure keeps the bias neutral.",
        limitation=f"Liquidity of {LIQUIDITY} is one figure",
        basis=basis(cp2=(ASSESSMENT,)),
    )
    assert (
        "recommendation.basis: rests only on CP-5-flagged claims (CP-2 T2.1.assessment)"
    ) in issues_of(committee(recommendation=rec), up)
    in_conditions = rec.model_copy(update={"conditions": f"Liquidity above {LIQUIDITY}."})
    assert issues_of(committee(recommendation=in_conditions), up) == ()


def test_a_cp5_restricted_handoff_limits_and_caps_below_high() -> None:
    up = upstream_of(cp5=flagging_cp5())
    # The assessment marked unsupported, and key finding 1 partly supported over CP-5's
    # figure-identity finding on CP-2's reference copy (review_all's rule).
    assert up.caps == (
        "CP-5 is restricted",
        "CP-5 marks 2 claims unsupported or partly supported",
        "CP-5 records 1 contradictions",
    )
    for bias in ("Overweight", "Neutral", "Underweight"):
        high = recommendation(action_bias=bias, confidence="High")
        assert (
            "recommendation.confidence: capped below High because CP-5 is restricted; CP-5 marks "
            "2 claims unsupported or partly supported; CP-5 records 1 contradictions"
        ) in issues_of(committee(recommendation=high), up)
    report = committee_challenge(market_pack(), committee(), up)
    assert (
        "CP-5 handoff caps the confidence below High: CP-5 is restricted; CP-5 marks 2 claims "
        "unsupported or partly supported; CP-5 records 1 contradictions; findings "
        + ", ".join(f.finding_id for f in cp5_review(up.cp5).findings)
    ) in report.limitations


def test_a_clean_cp5_allows_a_high_directional_bias() -> None:
    up = upstream_of(cp5=clean_cp5())
    assert up.caps == () and cp5_review(up.cp5).findings == ()
    high = recommendation(action_bias="Overweight", confidence="High", limitation=None)
    assert issues_of(committee(recommendation=high), up) == ()
    report = committee_challenge(market_pack(), committee(recommendation=high), up)
    assert not any(text.startswith("CP-5 handoff") for text in report.limitations)
    assert settled_call(cp6_module(report, up.bound, 0)).action_bias == "Overweight"


def test_a_blocked_ancestor_limits_and_caps_never_halts() -> None:
    up = upstream_of(blocked=frozenset({"CP-4"}))
    assert up.caps[0] == "CP-4 is blocked upstream"
    high = recommendation(confidence="High")
    assert any(
        i.startswith("recommendation.confidence: capped below High because CP-4 is blocked")
        for i in issues_of(committee(recommendation=high), up)
    )
    report = committee_challenge(market_pack(), committee(), up)
    assert "Blocked upstream CP-4: its outputs are outside CP-6's evidence" in report.limitations


def test_a_blocked_optional_cp1a_gets_the_0007_wording() -> None:
    up = upstream_of(cp1a=blocked_cp1a())
    assert "CP-1A is blocked upstream" in up.caps
    report = committee_challenge(market_pack(), committee(), up)
    assert (
        "Optional upstream CP-1A blocked: CP-6 reads no business and transaction context"
    ) in report.limitations
    assert not any(text.startswith("Blocked upstream CP-1A") for text in report.limitations)


def test_an_unselected_optional_cp1a_is_silent() -> None:
    """Ruling 1: not in the run is named in CONTEXT only; no cap, no limitation."""
    up = upstream_of(cp1a=None, cp5=clean_cp5())
    assert up.caps == () and up.limits == ()
    high = recommendation(confidence="High", limitation=None)
    assert issues_of(committee(recommendation=high), up) == ()
    report = committee_challenge(market_pack(), committee(recommendation=high), up)
    assert not any("CP-1A" in text for text in report.limitations)
    named = json.dumps(context_block(market_pack(), up)["optional_upstream"])
    assert '"status": "not in this run"' in named


def test_a_required_upstream_that_is_blocked_refuses_the_committee() -> None:
    """Decision 0007: CP-6 runs only after CP-5's handoff is Passed or Restricted."""
    h = heads()
    pack = market_pack()
    run = pack.run
    blocked = Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id="CP-5",
        status="blocked",
        limitations=("Malformed candidate: (root): Invalid JSON",),
    )
    up = upstream_of(cp5=blocked)
    found = issues_of(committee(), up)
    assert (
        "Required upstream CP-5 is blocked: its handoff is neither Passed nor Restricted" in found
    )
    assert h["CP-5"].status == "restricted"


def test_recovery_needs_cp4_evidence_through_cp5_or_is_insufficient() -> None:
    claimed = recovery().model_copy(
        update={
            "confidence": "Low",
            "view": "Holders of the notes would recover little.",
            "limitation": None,
        }
    )
    found = issues_of(committee(recovery_view=(claimed,)))
    assert (
        "recovery_view[0]: a recovery view that is not Insufficient Information cites a CP-5 "
        "finding or limitation carrying CP-4 evidence"
    ) in found
    silent = recovery().model_copy(update={"limitation": None})
    assert "recovery_view[0]: an Insufficient Information recovery view states its limitation" in (
        issues_of(committee(recovery_view=(silent,)))
    )


CP4_BLOCK = "Malformed candidate: (root): Invalid JSON"
CP4_CLAIM = "covenant_capacity"


def cp4_head(*, blocked: bool = False) -> Module:
    """A SYNTHETIC CP-4 head: blocked (limitations only) or carrying one covenant claim."""
    run = market_pack().run
    identity = {"run_id": run.run_id, "issuer_id": run.issuer_id, "as_of": run.as_of}
    if blocked:
        return Module(**identity, module_id="CP-4", status="blocked", limitations=(CP4_BLOCK,))
    claim = Claim(
        claim_id=CP4_CLAIM,
        text="The secured lenders hold a first lien over the operating assets.",
        citations=(),
    )
    return Module(**identity, module_id="CP-4", status="accepted", claims=(claim,))


@lru_cache(maxsize=1)
def blocked_cp4_cp5() -> Module:
    """CP-5 over CP-3 and a blocked CP-4: a Blocked upstream finding and the inherited
    "Upstream CP-4 blocked" limitation, both naming CP-4 without carrying its content."""
    pack, cp3, cp4 = market_pack(), heads()["CP-3"], cp4_head(blocked=True)
    items = tuple((entry(head), head) for head in (cp3, cp4))
    scope = ReviewScope(
        pack=pack,
        inputs=tuple(item for item, _ in items),
        heads=items,
        blocked=frozenset({"CP-4"}),
        inherited=(f"Upstream CP-4 blocked: {CP4_BLOCK}",),
    )
    report = integrity_review(scope, review_all(scope))
    return cp5_module(report, scope.inputs, 0).model_copy(update={"status": report.status})


@lru_cache(maxsize=1)
def evaluated_cp4_cp5() -> Module:
    """CP-5 over CP-3 and an evaluated CP-4 whose covenant claim it marks unsupported: a
    finding that carries CP-4 content."""
    support = {("CP-4", CP4_CLAIM): "unsupported"}
    return cp5_head(market_pack(), (heads()["CP-3"], cp4_head()), support)


def recovery_on(ref: str, confidence: Confidence = "Medium") -> RecoveryView:
    return RecoveryView(
        subject="Secured lenders",
        view="The first lien leaves the secured lenders well placed.",
        confidence=confidence,
        limitation=None,
        basis=basis(cp5=(ref,)),
    )


NO_CP4 = (
    "recovery_view[0]: a recovery view that is not Insufficient Information cites a CP-5 "
    "finding or limitation carrying CP-4 evidence"
)


def test_a_blocked_cp4_carries_no_recovery_evidence_through_cp5() -> None:
    """Fix round 1 (e): a blocked CP-4, CP-5's inherited "Upstream CP-4 blocked" row and its
    Blocked upstream finding name CP-4 but carry none of its content."""
    cp5 = blocked_cp4_cp5()
    facts = cells_of(cp5)
    refs = [f"T5B.7.{r.row_id}" for t in cp5.tables if t.table_id == "T5B.7" for r in t.rows]
    inherited = next(
        ref
        for ref in refs
        if facts[f"{ref}.origin"].text == "Inherited"
        and facts[f"{ref}.limitation"].text == f"Upstream CP-4 blocked: {CP4_BLOCK}"
    )
    finding = next(f.finding_id for f in cp5_review(cp5).findings if f.kind == "Blocked upstream")
    for blocked in (frozenset({"CP-4"}), frozenset()):  # CP-5's own not-evaluated list suffices
        up = upstream_of(cp5=cp5, blocked=blocked)
        for ref in (inherited, finding):
            found = issues_of(committee(recovery_view=(recovery_on(ref),)), up)
            assert NO_CP4 in found, (ref, blocked)


def test_a_cp5_finding_carrying_cp4_content_supports_a_recovery_view() -> None:
    up = upstream_of(cp5=evaluated_cp4_cp5())
    review = cp5_review(up.cp5)
    finding = next(f for f in review.findings if f.where == f"CP-4 claim {CP4_CLAIM}")
    for confidence in ("Low", "Medium"):
        view = recovery_on(finding.finding_id, confidence)  # type: ignore[arg-type]
        assert issues_of(committee(recovery_view=(view,)), up) == ()
    # Even so, a CP-4 that CP-6 sees blocked carries nothing.
    blocked = upstream_of(cp5=evaluated_cp4_cp5(), blocked=frozenset({"CP-4"}))
    assert blocked.cp4_evidence == frozenset()
    assert NO_CP4 in issues_of(committee(recovery_view=(recovery_on(finding.ref),)), blocked)


def test_cp4_evidence_rows_match_an_explicit_reference() -> None:
    """The differential: Python's CP-4 evidence rows against row ids read off each fixture by
    hand (no shared rule). Only the evaluated CP-4's unsupported-claim finding (T5.9.f001) and
    its own limitation row (T5B.7.r001) carry CP-4 content; the blocked CP-4's finding and
    inherited row carry none."""
    expected = {
        "default": frozenset(),
        "blocked": frozenset(),
        "evaluated": frozenset({"T5.9.f001", "T5B.7.r001"}),
    }
    found = {
        "default": upstream_of().cp4_evidence,
        "blocked": upstream_of(cp5=blocked_cp4_cp5(), blocked=frozenset({"CP-4"})).cp4_evidence,
        "evaluated": upstream_of(cp5=evaluated_cp4_cp5()).cp4_evidence,
    }
    assert found == expected
    evaluated = cells_of(evaluated_cp4_cp5())
    assert evaluated["T5.9.f001.where"].text == f"CP-4 claim {CP4_CLAIM}"
    assert evaluated["T5B.7.r001.origin"].text == "CP-5 finding"


# --- prohibited phrases (ruling 3) ----------------------------------------------------------


def test_cp6_states_a_recommendation_and_a_recovery_conclusion_but_no_ranking_or_trade() -> None:
    allowed = (
        "We recommend an overweight in the secured loan.",
        "The committee's recommendation is underweight the notes.",
        "Expected recovery for the secured loan is high.",
        "The notes would recover less than the loan.",
        "We prefer the secured loan.",
    )
    for text in allowed:
        assert cp6_prohibited_issues("t", text) == (), text
    assert cp6_prohibited_issues("t", "The loan ranks above peers.") == (
        't: prohibited conclusion (peer ranking): "ranks above"',
    )
    assert cp6_prohibited_issues("t", "Buy the loan.") == (
        't: prohibited conclusion (instrument action): "buy"',
    )
    assert cp6_prohibited_issues("t", "Set a target price for the notes.") == (
        't: prohibited conclusion (trade terms): "target price"',
    )
    bought = recommendation(rationale="Holders should buy the secured loan.")
    assert 'recommendation.rationale: prohibited conclusion (instrument action): "buy"' in (
        issues_of(committee(recommendation=bought))
    )


def test_the_cp6_action_phrases_are_cp3_s_minus_the_lifted_vocabulary() -> None:
    from deploy_vii.business_context import ACTIONS

    lifted = {p for p in ACTIONS["instrument action"] if p.startswith("recommend")}
    lifted |= {"overweight", "underweight"}
    assert set(CP6_ACTIONS) == set(ACTIONS["instrument action"]) - lifted
    assert {"buy", "sell", "switch into"} <= set(CP6_ACTIONS)
    assert "position size" in TRADE_TERMS


# --- the call-band values (ruling 2) --------------------------------------------------------


def test_the_settled_head_exposes_the_action_bias_and_the_confidence() -> None:
    up = upstream_of()
    module = cp6_module(committee_challenge(market_pack(), committee(), up), up.bound, 0)
    facts = cells_of(module)
    assert facts[ACTION_BIAS_FACT].text == "Neutral"
    assert facts[CONFIDENCE_FACT].text == "Low"
    call = settled_call(module)
    assert (call.action_bias, call.confidence, call.scale) == ("Neutral", "Low", 2)
    CallItem(kind="scale", label="Confidence", value_text=call.confidence, meter=call.scale)
    with pytest.raises(ValueError, match="not a CP-6 head"):
        settled_call(up.cp3)


def test_the_vocabulary_is_the_proposed_literal() -> None:
    """Ruling 3: neither docs/frontend-direction-c.md nor report_view.py spells an action bias,
    so the Literal is the proposed one."""
    assert ACTION_BIASES == ("Overweight", "Neutral", "Underweight", "Insufficient Information")
    assert CONFIDENCES == ("Insufficient Information", "Low", "Medium", "High")
    assert set(CONFIDENCES) == set(get_args(Recommendation.model_fields["confidence"].annotation))


# --- the journal: one step settles CP-6 -------------------------------------------------------


def full_journal(tmp_path: Path) -> Execution:
    """A SYNTHETIC journal over the market pack: CP-0 to CP-4 as the CP-3 test settles them,
    then CP-3 and CP-5 through their own step functions."""
    store = cp3_journal(tmp_path)
    ticket = store.begin("CP-3")
    submit_cp3_step(store, ticket.ticket_id, "relative_value", valuation().model_dump_json())
    ticket = store.begin("CP-5")
    submission = review_all(review_scope(store, ticket))
    submit_cp5_step(store, ticket.ticket_id, "integrity_review", submission.model_dump_json())
    return store


def head(store: Execution, module_id: str) -> Module:
    found = next(h for h in store.read().heads if h.module_id == module_id)
    return store.result(found.result_sha256)


def test_the_step_settles_cp6_with_the_python_candidate(tmp_path: Path) -> None:
    store = full_journal(tmp_path)
    assert head(store, "CP-5").status == "restricted"
    ticket = store.begin(MODULE_ID)
    upstream = cp6_upstream(store, ticket)
    assert upstream.current == ticket.inputs
    assert {i.input_id for i in ticket.inputs} == {"prepared-pack", *ORDER}
    assert set(upstream.optional) == {"CP-1A"}
    attempt = submit_cp6_step(store, ticket.ticket_id, STEP_ID, committee().model_dump_json())
    assert attempt.status == "finished" and attempt.issues == ()
    cp6 = head(store, MODULE_ID)
    assert cp6.status == "restricted"
    assert "Synthetic case; not real issuer qualification" in cp6.limitations
    assert any(text.startswith("CP-5 handoff caps the confidence") for text in cp6.limitations)
    assert settled_call(cp6).action_bias == "Neutral"
    record = next(h for h in store.read().heads if h.module_id == MODULE_ID)
    assert record.qualification is not None
    assert record.qualification.implementation == "implemented"
    with pytest.raises(ValueError, match="one step"):
        submit_cp6_step(store, ticket.ticket_id, "relative_value", "{}")
    with pytest.raises(ValueError, match="absent, finished"):
        submit_cp6_step(store, ticket.ticket_id, STEP_ID, committee().model_dump_json())


def test_a_blocked_cp5_blocks_the_committee(tmp_path: Path) -> None:
    store = cp3_journal(tmp_path)
    ticket = store.begin("CP-3")
    submit_cp3_step(store, ticket.ticket_id, "relative_value", valuation().model_dump_json())
    for _ in range(2):
        ticket = store.begin("CP-5")
        store.finish(ticket.ticket_id, "not json", lambda _: ())
    assert head(store, "CP-5").status == "blocked"
    with pytest.raises(ValueError, match="Required upstream is unrun, stale or blocked"):
        store.begin(MODULE_ID)


def test_an_invalid_step_rejects_then_blocks_with_its_issues(tmp_path: Path) -> None:
    store = full_journal(tmp_path)
    stray = committee(recommendation=recommendation(basis=basis(cp2=("T2.7.s09",))))
    for number, status in ((0, "rejected"), (1, "blocked")):
        ticket = store.begin(MODULE_ID)
        assert ticket.number == number
        attempt = submit_cp6_step(store, ticket.ticket_id, STEP_ID, stray.model_dump_json())
        assert "recommendation.basis.cp2_refs: unknown CP-2 row T2.7.s09" in attempt.issues
        assert store.result(str(attempt.result_sha256)).status == status


def test_a_stale_input_is_rejected(tmp_path: Path) -> None:
    store = full_journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    attempt = submit_cp6_step(store, ticket.ticket_id, STEP_ID, committee().model_dump_json())
    pack = store.pack()
    source = pack.sources[0].model_copy(update={"name": "Renamed synthetic filing"})
    store.replace_pack(pack.model_copy(update={"sources": (source, *pack.sources[1:])}))
    upstream = cp6_upstream(store, attempt)
    assert upstream.current == "Required upstream is unrun, stale or blocked"
    assert "Stale inputs: Required upstream is unrun, stale or blocked" in (
        validate_committee(store.pack(), committee(), upstream)
    )


def test_a_resumed_step_reuses_the_retained_response(tmp_path: Path) -> None:
    store = full_journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    payload = committee().model_dump_json()
    store.submit_step(
        ticket.ticket_id,
        MODULE_ID,
        (STEP_ID,),
        STEP_ID,
        payload,
        lambda pack, current: validate_step(store, pack, current),
    )
    with pytest.raises(ValueError, match="different response"):
        submit_cp6_step(store, ticket.ticket_id, STEP_ID, committee(gaps=()).model_dump_json())
    attempt = submit_cp6_step(store, ticket.ticket_id, STEP_ID, payload)
    assert attempt.status == "finished" and head(store, MODULE_ID).status == "restricted"


def test_an_attempt_without_its_required_inputs_fails_closed(tmp_path: Path) -> None:
    store = full_journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    without = ticket.model_copy(
        update={"inputs": tuple(i for i in ticket.inputs if i.input_id != "CP-5")}
    )
    with pytest.raises(ValueError, match="binds no CP-5 input"):
        cp6_upstream(store, without)


def test_an_upstream_module_must_be_the_bound_head() -> None:
    up = upstream_of()
    swapped = Upstream(
        bound=up.bound,
        current=up.current,
        cp0=up.cp0,
        cp1=up.cp1,
        cp2=up.cp2,
        cp3=up.cp3,
        cp5=clean_cp5(),
        optional=up.optional,
        blocked=up.blocked,
        inherited=(),
    )
    assert "Upstream CP-5: the supplied module is not the bound input" in issues_of(
        committee(), swapped
    )


# --- the CONTEXT block and the step chain -----------------------------------------------------


def test_the_context_block_prefills_heads_catalogues_findings_and_statuses() -> None:
    up = upstream_of()
    block = context_block(market_pack(), up)
    assert [m["module_id"] for m in block["upstream"]] == list(ORDER)
    modules = {m["module_id"]: m for m in block["heads"]}
    assert set(modules) == {"CP-1", "CP-2", "CP-3", "CP-5"}
    assert [c["claim_id"] for c in modules["CP-2"]["claims"]] == [c.claim_id for c in up.cp2.claims]
    assert modules["CP-3"]["claims"][0]["citations"][0]["source_id"] == "market-sheet"
    assert modules["CP-5"]["limitations"] == list(up.cp5.limitations)
    rows = {r["ref"]: r for r in block["cp2_rows"]}
    assert {ASSESSMENT, THESIS_ROW, STRENGTH, WEAKNESS, FINDING} <= rows.keys()
    assert rows[STRENGTH]["challengeable"] and not rows[CP2_RISK]["challengeable"]
    assert rows[ASSESSMENT]["claim"] and not rows[THESIS_ROW]["claim"]
    assert not rows["T2.12.g01"]["claim"]
    assert {r["ref"] for r in block["cp3_rows"] if r["claim"]} == {
        PREFERENCE,
        "T3.1.i01",
        "T3.1.i02",
    }
    assert PREFERENCE in {r["ref"] for r in block["cp3_rows"]}
    findings = cp5_review(up.cp5).findings
    assert [f["finding_id"] for f in block["cp5_findings"]] == [f.finding_id for f in findings]
    assert block["cp5_verdict"]["status"] == "Restricted over the evaluated set"
    assert "T4.10.liquidity.FY2025" in [f["ref"] for f in block["cp1_facts"]]
    assert block["optional_upstream"] == [
        {
            "module_id": "CP-1A",
            "status": "restricted",
            "limitations": list(up.optional["CP-1A"].limitations),
        }
    ]
    assert block["blocked_ancestors"] == []
    assert block["confidence_caps"] == list(up.caps)
    assert block["insufficient_information"] == []
    assert block["action_biases"] == list(ACTION_BIASES)


def test_the_step_chain_sends_no_pack_sources() -> None:
    assert CHAIN.settling == STEP_ID and pack_source_steps((CHAIN,)) == frozenset()


def test_the_context_block_stays_small() -> None:
    size = len(json.dumps(context_block(market_pack(), upstream_of())).encode())
    assert size < 60_000, size


# --- the sent schema ----------------------------------------------------------------------------


def nodes(node: object) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        return [node, *(n for value in node.values() for n in nodes(value))]
    if isinstance(node, list):
        return [n for item in node for n in nodes(item)]
    return []


def test_the_sent_schema_is_strict_and_needs_no_relaxation() -> None:
    sent = strict_schema(CommitteeSubmission)
    assert relax(strict_copy(CommitteeSubmission)) == sent
    text = json.dumps(sent)
    assert '"const"' not in text and '"oneOf"' not in text and '"default"' not in text
    for node in nodes(sent):
        assert None not in node.get("enum", ()), node
        if "properties" in node:
            assert node["required"] == list(node["properties"]) and not node["additionalProperties"]
    assert sent["properties"]["thesis_challenges"]["minItems"] == 1
    assert list(sent["properties"]) == [
        "recommendation",
        "thesis_challenges",
        "recovery_view",
        "risks",
        "gaps",
    ]
    assert schema_relaxations(CommitteeSubmission) == []


def test_a_submission_built_around_validation_reports_shape_issues() -> None:
    bogus = recommendation().model_copy(update={"action_bias": "Strong buy"})
    found = issues_of(committee(recommendation=bogus))
    assert any(i.startswith("recommendation.action_bias: Input should be") for i in found)
    with pytest.raises(ValueError, match=r"recommendation\.action_bias"):
        committee_challenge(market_pack(), committee(recommendation=bogus), upstream_of())


# --- Property 1: figure and reference identity --------------------------------------------------

CP2_POOL = (ASSESSMENT, THESIS_ROW, STRENGTH, CP2_RISK, "T2.7.s09", "cp2.thesis.thesis")
CP3_POOL = (PREFERENCE, CP3_RISK, "T3.1.i01", "T3.4.none", "cp3.relative_value.preference")
CP2_OFFERED = {ASSESSMENT, THESIS_ROW, STRENGTH, CP2_RISK}
CP3_OFFERED = {PREFERENCE, CP3_RISK, "T3.1.i01"}


@settings(max_examples=150, deadline=None)
@given(
    st.lists(st.sampled_from((*WORDS, *GOOD, *BAD)), min_size=1, max_size=8),
    st.lists(st.sampled_from(CP2_POOL), max_size=3),
    st.lists(st.sampled_from(CP3_POOL), max_size=3),
)
def test_composed_figures_are_the_upstream_facts_and_nothing_else_resolves(
    words: list[str], cp2: list[str], cp3: list[str]
) -> None:
    pack, up = market_pack(), upstream_of()
    text = " ".join(words)
    # The preference is an unflagged claim of the default CP-5: the call's support.
    support = basis(cp2=(THESIS_ROW, *cp2), cp3=(PREFERENCE, *cp3))
    rec = recommendation(rationale=text, basis=support)
    submission = committee(recommendation=rec)
    issues = validate_committee(pack, submission, up)
    bad_cp2 = [r for r in cp2 if r not in CP2_OFFERED]
    bad_cp3 = [r for r in cp3 if r not in CP3_OFFERED]
    assert bool(issues) == (any(w in BAD for w in words) or bool(bad_cp2) or bool(bad_cp3))
    for ref in bad_cp2:
        assert f"recommendation.basis.cp2_refs: unknown CP-2 row {ref}" in issues
    for ref in bad_cp3:
        assert f"recommendation.basis.cp3_refs: unknown CP-3 row {ref}" in issues
    if issues:
        with pytest.raises(ValueError):
            committee_challenge(pack, submission, up)
        return
    report = committee_challenge(pack, submission, up)
    offered = {f.fact_id: f for f in (cp1_fact(pack), *FACILITIES)}
    for fact in (f for f in report.facts if f.table_id == CP1_REFERENCES):
        source = offered[fact.fact_id]
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
    assert cells_of(report)["T6A.4.recommendation.rationale"].text == expected
    assert TLB_SPREAD == GOOD[0]


# --- Property 2: gap propagation is monotone ----------------------------------------------------


def settled_cp6(pack: PreparedPack, up: Upstream, submission: CommitteeSubmission) -> Module:
    """CP-6 settled by the journal's own `settle` over in-memory heads (decision 0007)."""
    candidate = cp6_module(committee_challenge(pack, submission, up), up.bound, 0)
    payload = candidate.model_dump_json()
    modules = {
        m.module_id: m for m in (up.cp0, up.cp1, up.cp2, up.cp3, up.cp5, *up.optional.values())
    }
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


@settings(max_examples=150, deadline=None)
@given(
    st.sampled_from(("none", "ancestor", "cp1a")),
    st.sampled_from(("clean", "restricted", "flagging")),
    st.booleans(),
    st.sampled_from(ACTION_BIASES),
    st.sampled_from(CONFIDENCES),
)
def test_upstream_gaps_always_limit_and_cap_and_propagate_monotonically(
    blocked: str, cp5: str, evidence: bool, bias: str, confidence: str
) -> None:
    pack = public(market_pack())
    head5 = {"clean": clean_cp5(), "restricted": heads()["CP-5"], "flagging": flagging_cp5()}[cp5]
    cp3 = heads()["CP-3"] if evidence else blind_cp3()
    up = upstream_of(
        cp3=cp3,
        cp5=head5,
        cp1a=blocked_cp1a() if blocked == "cp1a" else DEFAULT,
        blocked=frozenset({"CP-4"}) if blocked == "ancestor" else frozenset(),
    )
    clean = upstream_of(cp5=clean_cp5())
    insufficient = bias == "Insufficient Information"
    rec = recommendation(
        action_bias=bias,
        confidence=confidence,
        limitation="Stated limitation",
        rationale=recommendation().rationale,
        basis=basis(cp2=(THESIS_ROW,), cp3=(PREFERENCE,)),
    )
    submission = committee(recommendation=rec, thesis_challenges=challenges()[:3])
    issues = validate_committee(pack, submission, up)
    capped = blocked != "none" or cp5 != "clean"
    # Every cap has its own limitation (fix round 1, item 4).
    assert bool(up.caps) == capped
    for module_id in up.blocked_upstream:
        assert any(module_id in text for text in up.limits), module_id
    if any(reason.startswith("CP-5") for reason in up.caps):
        assert any(text.startswith("CP-5 handoff caps the confidence") for text in up.limits)
    if not issues:
        report = committee_challenge(pack, submission, up)
        assert set(up.limits) <= set(report.limitations)
        assert not (capped and confidence == "High")
        assert not (capped and bias in {"Overweight", "Underweight"} and confidence == "High")
        assert evidence or insufficient
        assert insufficient == (confidence == "Insufficient Information")
        # Monotone: what holds under the gaps holds without them.
        assert validate_committee(pack, submission, clean) == ()
        settled = settled_cp6(pack, up, submission)
        if capped or not evidence:
            assert settled.status == "restricted" and settled.limitations
    else:
        reasons = [
            capped and confidence == "High",
            not evidence and not insufficient,
            insufficient != (confidence == "Insufficient Information"),
        ]
        assert any(reasons), issues


# --- Property 3: the verdict does not depend on row order -----------------------------------------


@settings(max_examples=80, deadline=None)
@given(st.randoms(use_true_random=False), st.booleans())
def test_the_verdict_and_composition_do_not_depend_on_row_order(
    rng: random.Random, broken: bool
) -> None:
    pack, up = market_pack(), upstream_of()
    rows = list(challenges())
    if broken:
        rows[1] = rows[1].model_copy(update={"thesis_ref": CP2_RISK})
    refs = [ASSESSMENT, THESIS_ROW, STRENGTH]
    base = committee(
        thesis_challenges=tuple(rows),
        recommendation=recommendation(basis=basis(cp2=tuple(refs), cp3=(PREFERENCE, CP3_RISK))),
    )
    rng.shuffle(rows)
    rng.shuffle(refs)
    cp3 = [PREFERENCE, CP3_RISK]
    rng.shuffle(cp3)
    shuffled = base.model_copy(
        update={
            "thesis_challenges": tuple(rows),
            "recommendation": base.recommendation.model_copy(
                update={"basis": basis(cp2=tuple(refs), cp3=tuple(cp3))}
            ),
        }
    )

    def verdict(submission: CommitteeSubmission) -> set[str]:
        return {re.sub(r"\[[0-9]+\]", "[]", i) for i in validate_committee(pack, submission, up)}

    assert verdict(shuffled) == verdict(base)
    if broken:
        return
    one = committee_challenge(pack, base, up)
    two = committee_challenge(pack, shuffled, up)
    assert set(one.limitations) == set(two.limitations)
    cells = (cells_of(one), cells_of(two))
    assert (
        cells[0]["T6A.4.recommendation.basis"].text == cells[1]["T6A.4.recommendation.basis"].text
    )

    def challenged(cells: dict[str, Fact]) -> set[tuple[str | None, str | None]]:
        return {
            (f.text, cells[f.fact_id.replace("thesis_ref", "counter_case")].text)
            for f in cells.values()
            if f.table_id == "T6E.4" and f.field == "thesis_ref"
        }

    assert challenged(cells[0]) == challenged(cells[1])
    sw = {
        t.table_id: {r.row_id for r in t.rows}
        for report in (one, two)
        for t in report.tables
        if t.table_id in {THESIS_CHALLENGE, STRENGTH_CHALLENGES, WEAKNESS_CHALLENGES}
    }
    assert sw == {
        t.table_id: {r.row_id for r in t.rows}
        for t in one.tables
        if t.table_id in {THESIS_CHALLENGE, STRENGTH_CHALLENGES, WEAKNESS_CHALLENGES}
    }


# --- Property 4: the call-band confidence scale ---------------------------------------------------

# The independent reference: a table written out by hand (decision 0012 differential).
REFERENCE_SCALE = {"Insufficient Information": 1, "Low": 2, "Medium": 3, "High": 5}


@settings(max_examples=60, deadline=None)
@given(st.sampled_from(CONFIDENCES), st.sampled_from(CONFIDENCES))
def test_the_call_scale_is_total_monotone_and_matches_the_reference(
    a: Confidence, b: Confidence
) -> None:
    assert call_scale(a) == REFERENCE_SCALE[a] == CALL_SCALE[a]
    if CONFIDENCES.index(a) < CONFIDENCES.index(b):
        assert call_scale(a) < call_scale(b)
    assert 1 <= call_scale(a) <= 5
    CallItem(kind="scale", label="Confidence", value_text=a, meter=call_scale(a))
    assert set(CALL_SCALE) == set(CONFIDENCES)
    with pytest.raises(ValueError, match="Unknown confidence"):
        call_scale("Certain")  # type: ignore[arg-type]  # outside the Literal on purpose


# --- differentials: reference existence, staleness, the prohibited-phrase boundary ------------

CP5_TABLES = ("T5.9", "T5B.6", "T5B.7", "T5B.8")
UNKNOWN = re.compile(
    r"recommendation\.basis\.(cp[235])_refs: unknown CP-[235] (?:row or finding|row) (\S+)"
)


def naive_rows(module: Module, tables: tuple[str, ...]) -> set[str]:
    facts = {f.fact_id: f for f in module.facts}
    return {
        f"{t.table_id}.{r.row_id}"
        for t in module.tables
        if t.table_id in tables
        for r in t.rows
        if any(facts[i].status == "known" for i in r.fact_ids)
    }


def cp5_pool() -> tuple[str, ...]:
    up5 = heads()["CP-5"]
    labels = [r.label for t in up5.tables if t.table_id == "T5.9" for r in t.rows]
    some = sorted(naive_rows(up5, CP5_TABLES))[:6]
    return (*labels[:3], *some, "CP-5-FINDING-999", "T5.1.r001", "T5B.8.none", "T5.9.f999")


@settings(max_examples=120, deadline=None)
@given(
    st.lists(st.sampled_from((*CP2_POOL, *CP3_POOL)), max_size=4),
    st.lists(st.sampled_from(cp5_pool()), max_size=4),
)
def test_reference_existence_matches_a_naive_set_reference(
    mixed: list[str], cp5: list[str]
) -> None:
    up = upstream_of()
    cp2 = tuple(r for r in mixed if r.startswith(("T2", "cp2")))
    cp3 = tuple(r for r in mixed if r.startswith(("T3", "cp3")))
    rec = recommendation(basis=basis(cp2=(THESIS_ROW, *cp2), cp3=cp3, cp5=tuple(cp5)))
    issues = issues_of(committee(recommendation=rec), up)
    cp2_rows = naive_rows(up.cp2, ("T2.1", "T2.7", "T2.10", "T2.11", "T2.12"))
    cp3_rows = naive_rows(up.cp3, ("T3.1", "T3.3", "T3.4", "T3.9", "T3.10"))
    labels = {r.label for t in up.cp5.tables if t.table_id == "T5.9" for r in t.rows}
    cp5_rows = naive_rows(up.cp5, CP5_TABLES) | {x for x in labels if x.startswith("CP-5-FINDING-")}
    naive = (
        {("cp2", r) for r in cp2 if r not in cp2_rows}
        | {("cp3", r) for r in cp3 if r not in cp3_rows}
        | {("cp5", r) for r in cp5 if r not in cp5_rows}
    )
    found = {(m.group(1), m.group(2)) for issue in issues if (m := UNKNOWN.fullmatch(issue))}
    assert found == naive


IDS = ("prepared-pack", *ORDER)
SHAS = ("a" * 64, "b" * 64)
STATUSES = ("accepted", "restricted", "blocked")


@settings(max_examples=150, deadline=None)
@given(
    st.one_of(
        st.none(),
        st.lists(
            st.tuples(st.sampled_from(IDS), st.sampled_from(SHAS), st.sampled_from(STATUSES)),
            max_size=7,
            unique_by=lambda item: item[0],
        ),
    ),
    st.lists(st.sampled_from(IDS), max_size=7, unique=True),
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
    probe = upstream_of(current=state)
    issues = issues_of(committee(), probe)
    if isinstance(state, str):
        assert [i for i in issues if i.startswith("Stale")] == [f"Stale inputs: {state}"]
        return
    now = {i.input_id: i for i in state}
    naive = {key for key in bound.keys() | now.keys() if bound.get(key) != now.get(key)}
    found = {m.group(1) for i in issues if (m := re.match(r"Stale input (\S+):", i))}
    assert found == naive


SUBJECTS = ("The secured term loan", "The unsecured notes", "The committee")
ALLOWED = (
    "merits an overweight",
    "warrants an underweight",
    "is what we recommend",
    "is our recommendation",
    "would recover in full",
    "has an expected recovery near par",
    "is senior to the notes",
    "is better compensated than the notes",
)
FORBIDDEN = {
    "should be bought; buy it": "instrument action",
    "is a sell": "instrument action",
    "is a reason to switch into the loan": "instrument action",
    "is a reason to switch out of the notes": "instrument action",
    "ranks above peers": "peer ranking",
    "looks cheap versus peers": "peer ranking",
    "needs a target price": "trade terms",
    "sets the position size": "trade terms",
}


def naive_prohibited(text: str) -> set[str]:
    """The naive reference: every phrase of the three checked lists, word-bounded, any case."""
    lists = {
        "peer ranking": PROHIBITED["peer ranking"],
        "instrument action": CP6_ACTIONS,
        "trade terms": TRADE_TERMS,
    }
    return {
        kind
        for kind, phrases in lists.items()
        for phrase in phrases
        if re.search(rf"(?<![A-Za-z]){re.escape(phrase)}(?![A-Za-z])", text, re.IGNORECASE)
    }


@settings(max_examples=200, deadline=None)
@given(
    st.lists(
        st.tuples(st.sampled_from(SUBJECTS), st.sampled_from((*ALLOWED, *FORBIDDEN))),
        min_size=1,
        max_size=3,
    )
)
def test_the_prohibited_phrase_boundary_matches_a_naive_reference(
    clauses: list[tuple[str, str]],
) -> None:
    text = " ".join(f"{subject} {middle}." for subject, middle in clauses)
    found = {
        m.group(1)
        for issue in cp6_prohibited_issues("t", text)
        if (m := re.search(r"prohibited conclusion \(([^)]+)\)", issue))
    }
    assert found == naive_prohibited(text)
    assert found == {FORBIDDEN[middle] for _, middle in clauses if middle in FORBIDDEN}


# --- the Front Page: committee-challenge and the CP-6 side of strengths-weaknesses (SYNTHETIC) ----


def shown(module: Module, base: ModuleView) -> ModuleView:
    return ModuleView(
        module_id=module.module_id,
        title=base.title,
        aliases=base.aliases,
        status="candidate",
        artifact_sha256=module.content_hash(),
        facts=module.facts,
        tables=module.tables,
        claims=module.claims,
    )


def snapshot_with_cp6() -> tuple[View, Module, Module]:
    """The SYNTHETIC Credit Snapshot view with its synthetic CP-2 and CP-6 rows replaced by the
    composed CP-2 head and a composed CP-6 module."""
    view = credit_snapshot_view()
    up = upstream_of()
    module = cp6_module(committee_challenge(market_pack(), committee(), up), up.bound, 0)
    by_id = {m.module_id: m for m in view.modules}
    replaced = {"CP-2": shown(up.cp2, by_id["CP-2"]), MODULE_ID: shown(module, by_id[MODULE_ID])}
    modules = tuple(replaced.get(m.module_id, m) for m in view.modules)
    return view.model_copy(update={"modules": modules}), module, up.cp2


def maps_with_cp6() -> tuple[BindingMap, ...]:
    kept = (m for m in CREDIT_SNAPSHOT_MAPS if m.module_id not in {"CP-2", MODULE_ID})
    return (*kept, CP2_MAP, CP6)


def front(view: View) -> dict[str, Any]:
    pathway = next(p for p in pathways() if p.id == "credit_snapshot")
    return {b.block_id: b for b in build(view, pathway, maps_with_cp6()).blocks}


def test_the_committee_challenge_block_fills_with_field_parity() -> None:
    view, module, _ = snapshot_with_cp6()
    assert validate_bindings(view, maps_with_cp6()) == ()  # every CP-6 fact bound exactly once
    block = front(view)["committee-challenge"]
    assert block.state == "collapsed" and block.owner == "CP-6" and "Synthetic" in block.tags
    bound = [f for f in module.facts if f.table_id == COMMITTEE_CHALLENGE]
    gaps = gap_ids(view)
    expected = {f.fact_id: expected_text(f, gaps.get((MODULE_ID, f.fact_id))) for f in bound}
    assert len(block.lines) == len(bound) == 5
    actual = {
        fact.fact_id: "".join(run.text for run in line.runs if run.kind != "fig")
        for fact, line in zip(bound, block.lines, strict=True)
    }
    parity = parity_record(expected, actual)
    assert parity["compared"] == 5 and not parity["mismatches"], parity
    summary = block.summary or ""
    assert summary.startswith("Action bias: Neutral (confidence Low).")


def test_the_strengths_weaknesses_challenge_column_aligns_by_cp2_row_id() -> None:
    view, module, cp2 = snapshot_with_cp6()
    block = front(view)["strengths-weaknesses"]
    cp2_rows = {
        t.table_id: [r.row_id for r in t.rows]
        for t in cp2.tables
        if t.table_id in {THESIS, STRENGTHS, WEAKNESSES}
    }
    cp6_rows = {
        t.table_id: [r.row_id for r in t.rows]
        for t in module.tables
        if t.table_id in {THESIS_CHALLENGE, STRENGTH_CHALLENGES, WEAKNESS_CHALLENGES}
    }
    assert cp6_rows == {
        THESIS_CHALLENGE: ["thesis"],
        STRENGTH_CHALLENGES: ["s01"],
        WEAKNESS_CHALLENGES: ["w01"],
    }
    for side, mine in (
        (THESIS, THESIS_CHALLENGE),
        (STRENGTHS, STRENGTH_CHALLENGES),
        (WEAKNESSES, WEAKNESS_CHALLENGES),
    ):
        assert set(cp6_rows[mine]) <= set(cp2_rows[side])
    # s02 and w02 carry no challenge: no CP-6 line names them.
    challenge_lines = [
        line for line in block.lines if (line.label or "").startswith("Challenge · ")
    ]
    assert [(line.section, line.label) for line in challenge_lines] == [
        ("thesis", "Challenge · Thesis"),
        ("strengths", "Challenge · Liquidity"),
        ("weaknesses", "Challenge · Disclosure"),
    ]
    facts = cells_of(module)
    assert facts[f"{STRENGTH_CHALLENGES}.s01.value"].text == challenges()[1].counter_case
    texts = ["".join(r.text for r in line.runs if r.kind != "fig") for line in challenge_lines]
    assert texts[1] == challenges()[1].counter_case


def test_the_binding_map_places_the_tables_on_the_rails() -> None:
    destinations = {e.fact_coord.table_id: (e.block_id, e.section) for e in CP6.entries}
    assert destinations == {
        COMMITTEE_CHALLENGE: ("committee-challenge", None),
        THESIS_CHALLENGE: ("strengths-weaknesses", "thesis"),
        STRENGTH_CHALLENGES: ("strengths-weaknesses", "strengths"),
        WEAKNESS_CHALLENGES: ("strengths-weaknesses", "weaknesses"),
        "T6A.4": ("evidence", None),
        "T6E.4": ("evidence", None),
        "T6E.6": ("evidence", None),
        "T6E.7": ("evidence", None),
        CP1_REFERENCES: ("evidence", None),
        "T6E.11": ("limitations", None),
    }
    assert all(e.cell_slot.startswith("cp6-") for e in CP6.entries)
    assert CP6.module_id == MODULE_ID


# --- method text and the r14 coverage map -------------------------------------------------------


def test_the_method_text_names_the_tables_and_the_rules_and_states_no_figure() -> None:
    brief = files("deploy_vii").joinpath("methods", "cp6.md").read_text(encoding="utf-8")
    assert len(brief.splitlines()) < 110
    for table_id in REQUIRED_TABLES:
        assert f"`{table_id}`" in brief
    for anchor in (
        "decision 0005",
        "SKILL.md",
        "Reader question",
        "thesis_ref",
        "cp2_refs",
        "cp3_refs",
        "cp5_refs",
        "CP-5-FINDING",
        "Insufficient Information",
        "Prohibited",
        "blocked",
        "not in this run",
        "recovery_view",
        "assumption",
    ):
        assert anchor in brief, anchor
    keys = {"cp2_refs", "cp3_refs", "cp5_refs", "cp1_facts", "0004", "0005", "0007", "M10"}
    keys |= {"cp2_rows", "cp3_rows", "cp5_rows", "cp5_cp4_rows", "cp5_flagged_claims"}
    assert {f.strip("`") for f in bare_figures(brief)} <= {*REQUIRED_TABLES, *keys}


def test_the_required_tables_are_r14_cp6_ids() -> None:
    coverage = json.loads(Path("docs/methodology/r14-coverage.json").read_text(encoding="utf-8"))
    entry_ = next(m for m in coverage["modules"] if m["module_id"] == MODULE_ID)
    assert set(REQUIRED_TABLES) <= set(entry_["artifact_contract"]["required_table_ids"])
