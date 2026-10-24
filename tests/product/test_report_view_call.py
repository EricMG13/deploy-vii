"""Task 8.7: the Front Page call band reads the settled CP-6 head (`report_view._call`).

Three states (docs/frontend-direction-c.md): populated from a settled (accepted or restricted)
CP-6 head, the honest no-judgement item when there is no settled head, and the call withheld
when CP-6 is outside the Pathway or cannot run (CP-6 or a required producer of it blocked).
Every value is the head's own final-bias fact text (`T6-FINAL.final_bias.action_bias`
and `T6-FINAL.final_bias.confidence`, task CP6-R); the meter is `cp6_committee.call_scale`, held
here to a hand-written reference table (decision 0012 differential) and to a property over the
whole Literal. SYNTHETIC data only: the CP-6 head is composed by Python from the CP-6 test's
submission over the SYNTHETIC Credit Snapshot fixture.
"""

import itertools
from datetime import date
from typing import get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.bindings.shipped import SHIPPED_MAPS
from deploy_vii.contracts import Fact, Module, ModuleView, PathwayId, Run, Status, View
from deploy_vii.cp6_committee import (
    ACTION_BIAS_FACT,
    ACTION_BIASES,
    CALL_SCALE,
    CONFIDENCE_FACT,
    CONFIDENCES,
    MODULE_ID,
    ActionBias,
    committee_challenge,
    cp6_module,
    settled_call,
)
from deploy_vii.render import empty_view
from deploy_vii.report_view import CallItem, Pathway, ReportView, build, call_state, pathways
from tests.product import test_cp6_committee as cp6_tests
from tests.product.cp3_market import market_pack

PENDING = (CallItem(kind="na", label="Assessment", value_text="Assessment pending"),)
# The user decision of 24 Oct 2026, written out by hand (independent of `CALL_SCALE`).
REFERENCE_METER = {"Insufficient Information": 1, "Low": 2, "Medium": 3, "High": 5}


def run(pathway: PathwayId = "credit_snapshot") -> Run:
    return Run(
        run_id="r",
        issuer_id="i",
        issuer_name="Issuer",
        as_of=date(2026, 10, 21),
        case_kind="synthetic",
        pathway=pathway,
    )


def preset(pathway: PathwayId) -> Pathway:
    return next(p for p in pathways() if p.id == pathway)


def settled(view: View, status: Status = "restricted") -> View:
    """`view` with its CP-6 module given `status` (a composed CP-6 head is restricted)."""
    modules = tuple(
        ModuleView.model_validate({**m.model_dump(), "status": status})
        if m.module_id == MODULE_ID
        else m
        for m in view.modules
    )
    return View.model_validate({**view.model_dump(), "modules": modules})


def with_status(view: View, module_id: str, status: Status) -> View:
    """`view` with `module_id` in `status` and no output (an idle or blocked module)."""
    modules = tuple(
        ModuleView(
            module_id=m.module_id,
            title=m.title,
            aliases=m.aliases,
            status=status,
            limitations=("x",) if status in {"blocked", "stale", "rejected"} else (),
        )
        if m.module_id == module_id
        else m
        for m in view.modules
    )
    return view.model_copy(update={"modules": modules})


def snapshot_report(status: Status = "restricted") -> tuple[ReportView, View]:
    view, _, _ = cp6_tests.snapshot_with_cp6()
    view = settled(view, status)
    return build(view, preset("credit_snapshot"), cp6_tests.maps_with_cp6()), view


def facts_of(view: View) -> dict[str, Fact]:
    cp6 = next(m for m in view.modules if m.module_id == MODULE_ID)
    return {fact.fact_id: fact for fact in cp6.facts}


# --- populated: the SYNTHETIC fixture, once ---------------------------------------------------


def test_a_settled_cp6_head_populates_the_call_band_with_field_parity() -> None:
    report, view = snapshot_report()
    facts = facts_of(view)
    bias, confidence = facts[ACTION_BIAS_FACT].text, facts[CONFIDENCE_FACT].text
    assert (bias, confidence) == ("Neutral", "Low")  # the CP-6 test's SYNTHETIC submission
    assert report.call == (
        CallItem(kind="fact", label="Action bias", value_text=bias),
        CallItem(kind="scale", label="Confidence", value_text=confidence, meter=2),
    )
    assert report.call_withheld is None and call_state(report) == ("populated", None)
    # Field parity with the head: value text, meter and label, item by item.
    expected = {
        "Action bias": (facts[ACTION_BIAS_FACT].text, None),
        "Confidence": (facts[CONFIDENCE_FACT].text, CALL_SCALE[str(confidence)]),
    }
    assert {i.label: (i.value_text, i.meter) for i in report.call} == expected
    block = next(b for b in report.blocks if b.block_id == "committee-challenge")
    assert block.owner == MODULE_ID and "Synthetic" in block.tags  # SYNTHETIC-only exercise


def test_an_accepted_cp6_head_populates_the_call_band_too() -> None:
    report, _ = snapshot_report("accepted")
    assert [i.label for i in report.call] == ["Action bias", "Confidence"]


# --- no judgement ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["unrun", "stale", "rejected"])
def test_no_settled_cp6_head_shows_the_honest_no_judgement_item(status: Status) -> None:
    view = with_status(empty_view(run()), MODULE_ID, status)
    report = build(view, preset("credit_snapshot"), ())
    assert report.call == PENDING and report.call_withheld is None
    assert call_state(report) == ("no-judgement", None)


def test_a_candidate_cp6_is_not_a_settled_head_so_no_judgement_is_shown() -> None:
    report, _ = snapshot_report("candidate")
    assert report.call == PENDING and call_state(report) == ("no-judgement", None)


# --- withheld: blocked, outside the Pathway -------------------------------------------------


def test_a_blocked_cp6_withholds_the_call() -> None:
    view = with_status(empty_view(run()), MODULE_ID, "blocked")
    report = build(view, preset("credit_snapshot"), ())
    assert report.call == PENDING and report.call_withheld == "blocked"
    assert call_state(report) == ("blocked", ("blocked", "Blocked"))


@pytest.mark.parametrize("producer", ["CP-0", "CP-1", "CP-2", "CP-3", "CP-5"])
def test_a_blocked_required_producer_of_cp6_withholds_the_call(producer: str) -> None:
    view = with_status(empty_view(run()), producer, "blocked")
    report = build(view, preset("credit_snapshot"), ())
    assert report.call == PENDING and report.call_withheld == "blocked"


def test_a_blocked_optional_or_non_edge_module_does_not_withhold_the_call() -> None:
    for module_id in ("CP-1A", "CP-4"):
        view = with_status(empty_view(run()), module_id, "blocked")
        report = build(view, preset("credit_snapshot"), ())
        assert report.call == PENDING and report.call_withheld is None, module_id


@pytest.mark.parametrize("pathway", ["earnings_update", "relative_value", "covenant_refinancing"])
def test_cp6_outside_the_pathway_withholds_the_call_as_not_in_pathway(pathway: PathwayId) -> None:
    view = empty_view(run(pathway))
    assert next(m for m in view.modules if m.module_id == MODULE_ID).status == "not_in_pathway"
    report = build(view, preset(pathway), ())
    assert report.call == PENDING and report.call_withheld == "outside_pathway"
    assert call_state(report) == ("outside", ("na", "Not in this Pathway"))


def test_a_settled_head_without_its_pair_fails_closed() -> None:
    view, _, _ = cp6_tests.snapshot_with_cp6()
    view = settled(view)
    cp6 = next(m for m in view.modules if m.module_id == MODULE_ID)
    bad = tuple(
        f.model_copy(update={"text": "Strong OW"}) if f.fact_id == ACTION_BIAS_FACT else f
        for f in cp6.facts
    )
    broken = view.model_copy(
        update={
            "modules": tuple(
                m.model_copy(update={"facts": bad}) if m.module_id == MODULE_ID else m
                for m in view.modules
            )
        }
    )
    with pytest.raises(ValueError, match="no settled action bias and confidence"):
        build(broken, preset("credit_snapshot"), cp6_tests.maps_with_cp6())


# --- the mapping: differential against the reference, total and monotone --------------------


def head_view(bias: str, confidence: str) -> tuple[View, Module]:
    """An idle Credit Snapshot view whose CP-6 is a restricted head composed by Python, its two
    final-bias cells set to `bias` and `confidence`; and that head."""
    up = cp6_tests.upstream_of()
    module = cp6_module(
        committee_challenge(market_pack(), cp6_tests.committee(), up),
        up.bound,
        0,
    )
    text = {ACTION_BIAS_FACT: bias, CONFIDENCE_FACT: confidence}
    facts = tuple(
        f.model_copy(update={"text": text[f.fact_id]}) if f.fact_id in text else f
        for f in module.facts
    )
    base = empty_view(run())
    modules = tuple(
        ModuleView(
            module_id=m.module_id,
            title=m.title,
            aliases=m.aliases,
            status="restricted",
            artifact_sha256=module.content_hash(),
            facts=facts,
            tables=module.tables,
            claims=module.claims,
        )
        if m.module_id == MODULE_ID
        else m
        for m in base.modules
    )
    head = module.model_copy(update={"facts": facts})
    return View.model_validate({**base.model_dump(), "modules": modules}), head


@settings(max_examples=60, deadline=None)
@given(
    st.sampled_from(ACTION_BIASES),
    st.sampled_from(CONFIDENCES),
    st.sampled_from(CONFIDENCES),
)
def test_the_band_reads_any_settled_pair_and_its_meter_is_the_reference_and_monotone(
    bias: ActionBias, low: str, high: str
) -> None:
    meters: dict[str, int | None] = {}
    for confidence in (low, high):
        view, head = head_view(bias, confidence)
        report = build(view, preset("credit_snapshot"), SHIPPED_MAPS)
        action, scale = report.call
        assert (action.kind, action.label, action.value_text) == ("fact", "Action bias", bias)
        assert (scale.kind, scale.label, scale.value_text) == ("scale", "Confidence", confidence)
        assert scale.meter == REFERENCE_METER[confidence] == CALL_SCALE[confidence]
        call = settled_call(head)  # the module's own reader of the same head
        assert (call.action_bias, call.confidence, call.scale) == (bias, confidence, scale.meter)
        meters[confidence] = scale.meter
    if [c for c in CONFIDENCES if c in (low, high)] == [low, high] and low != high:
        assert (meters[low] or 0) < (meters[high] or 0)


def test_the_band_reads_every_action_bias_and_confidence_pair_exhaustively() -> None:
    for bias, confidence in itertools.product(ACTION_BIASES, CONFIDENCES):
        view, _ = head_view(bias, confidence)
        action, scale = build(view, preset("credit_snapshot"), SHIPPED_MAPS).call
        assert (action.label, action.value_text) == ("Action bias", bias), (bias, confidence)
        assert (scale.label, scale.value_text) == ("Confidence", confidence), (bias, confidence)
        assert scale.meter == REFERENCE_METER[confidence], (bias, confidence)


def test_a_settled_head_without_its_confidence_fact_fails_closed() -> None:
    view, _ = head_view(ACTION_BIASES[0], CONFIDENCES[0])
    modules = tuple(
        m.model_copy(update={"facts": tuple(f for f in m.facts if f.fact_id != CONFIDENCE_FACT)})
        if m.module_id == MODULE_ID
        else m
        for m in view.modules
    )
    broken = view.model_copy(update={"modules": modules})
    with pytest.raises(ValueError, match="no settled action bias and confidence"):
        build(broken, preset("credit_snapshot"), SHIPPED_MAPS)


def test_a_settled_head_with_a_confidence_outside_the_literal_fails_closed() -> None:
    view, _ = head_view(ACTION_BIASES[0], "Very High")
    assert "Very High" not in CONFIDENCES
    with pytest.raises(ValueError, match="no settled action bias and confidence"):
        build(view, preset("credit_snapshot"), SHIPPED_MAPS)


def test_the_reference_covers_the_whole_literal() -> None:
    assert set(REFERENCE_METER) == set(CONFIDENCES) == set(CALL_SCALE)
    assert set(ACTION_BIASES) == set(get_args(ActionBias))
