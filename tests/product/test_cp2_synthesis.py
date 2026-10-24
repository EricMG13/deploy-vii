"""CP-2 fundamental credit synthesis (task 8.1): the contract, its Python-only validator, the
composed registers, the Front Page bindings and the method text.

SYNTHETIC data only: the pack is the one-line readiness fixture, the CP-1A head is composed by
Python from the synthetic CP-1A submission, and the Front Page test runs over the SYNTHETIC
Credit Snapshot fixture (`tests/product/credit_snapshot.py`). Decision 0012: the key-area rules
(figure identity, gap propagation, order independence, reference existence and staleness) are
Hypothesis properties, two of them differentials against a naive set-based reference.
"""

import json
import random
import re
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.bindings import BindingMap, validate_bindings
from deploy_vii.bindings.cp2 import CP2
from deploy_vii.business_context import (
    CP1_REFERENCES,
    Gap,
    business_context,
    cp1a_module,
    spelled,
    submit_cp1a_step,
)
from deploy_vii.contracts import (
    Fact,
    Input,
    Module,
    ModuleView,
    ReportTable,
    Status,
    TableColumn,
    TableRow,
    View,
)
from deploy_vii.cp2_synthesis import (
    KEY_FINDINGS,
    MODULE_ID,
    REQUIRED_TABLES,
    STEP_ID,
    STRENGTHS,
    THESIS,
    WEAKNESSES,
    Assessment,
    CreditSynthesisSubmission,
    Finding,
    Point,
    Risk,
    SynthesisGap,
    Thesis,
    Upstream,
    context_block,
    cp1a_catalogue,
    cp2_module,
    cp2_signals,
    cp2_upstream,
    credit_synthesis,
    submit_cp2_step,
    validate_credit_synthesis,
)
from deploy_vii.cp2_synthesis import _validate_step as validate_step
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
from deploy_vii.report_view import build, pathways
from tests.product.credit_snapshot import CREDIT_SNAPSHOT_MAPS, credit_snapshot_view
from tests.product.oracle import expected_text, gap_ids, parity_record
from tests.product.test_business_context import cp1_fact, pack_fixture, submission_fixture
from tests.product.test_readiness import readiness_fixture

LIQUIDITY = "{T4.10.liquidity.FY2025|US$ m}"
TRANSLATION = "credit_translation.r01"
DEBT_SCHEDULE = "T2D.7.r01"
REPORTING = "T2D.3.r01"
SEGMENT_GAP = "gaps_ledger.r01"
CP2_READINESS = "downstream_readiness.r01"  # CP-1A judges CP-2 first
ABSENT = "absent"
ISSUER = "Synthetic issuer"


# --- fixtures: SYNTHETIC upstream heads -------------------------------------------------------


def public_pack() -> PreparedPack:
    """The readiness fixture pack as a public case, so settlement adds no synthetic limitation
    and an `accepted` status is reachable (test fixture, not qualification)."""
    pack = pack_fixture()
    run = pack.run.model_copy(update={"case_kind": "public"})
    return PreparedPack.model_validate_json(pack.model_copy(update={"run": run}).model_dump_json())


def module_of(
    pack: PreparedPack,
    module_id: str,
    *,
    status: Status = "accepted",
    facts: tuple[Fact, ...] = (),
    limitations: tuple[str, ...] = (),
    tables: tuple[ReportTable, ...] = (),
) -> Module:
    run = pack.run
    return Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id=module_id,
        status=status,
        facts=facts,
        tables=tables,
        limitations=limitations,
    )


def leverage_fact() -> Fact:
    """A calculated CP-1 figure (no citation, a calculation id): referencable."""
    return Fact(
        fact_id="T4.10.total_leverage.FY2025",
        label="Total leverage",
        table_id="T4.10",
        row_id="total_leverage",
        field="FY2025",
        amount=Decimal("3.5"),
        unit="MULTIPLE",
        period="FY2025",
        calculation_id="k1",
        formula="synthetic calculation",
        calculation_status="calculated",
    )


def unsettled_fact() -> Fact:
    """A CP-1 gap: never referencable as a figure."""
    return Fact(
        fact_id="T4.10.interest_cover.FY2025",
        label="Interest cover",
        table_id="T4.10",
        row_id="interest_cover",
        field="FY2025",
        unit="MULTIPLE",
        status="missing",
        limitation="not extracted",
    )


def cp0_head(pack: PreparedPack) -> Module:
    return module_of(pack, "CP-0", status="restricted", limitations=("Synthetic partial pack",))


def cp1_head(pack: PreparedPack) -> Module:
    return module_of(pack, "CP-1", facts=(cp1_fact(pack), leverage_fact(), unsettled_fact()))


def cp1a_head(
    pack: PreparedPack,
    gaps: tuple[Gap, ...] | None = None,
    *,
    cp2_status: str = "READY_WITH_LIMITATIONS",
    disclosures: tuple[str, ...] | None = None,
) -> Module:
    """The CP-1A head Python composes from the synthetic CP-1A submission; restricted when it
    records any own limitation. `gaps` replaces its gaps; `disclosures` replaces its disclosure
    log by one item per severity; `cp2_status` is its readiness judgment of CP-2 (the fixture's
    own is READY_WITH_LIMITATIONS), and ABSENT composes it over a run whose plan has no CP-2,
    so CP-1A judges no CP-2 at all."""
    scope = pack
    if cp2_status == ABSENT:
        run = pack.run.model_copy(update={"requested_modules": ("CP-0", "CP-1", "CP-1A")})
        scope = PreparedPack.model_validate_json(
            pack.model_copy(update={"run": run}).model_dump_json()
        )
    submission = submission_fixture(scope)
    changes: dict[str, object] = {}
    if gaps is not None:
        changes["gaps"] = gaps
    if disclosures is not None:
        item = submission.disclosure_items[0]
        changes["disclosure_items"] = tuple(
            item.model_copy(update={"item": f"Disclosure {chr(65 + i)}", "severity": severity})
            for i, severity in enumerate(disclosures)
        )
    if cp2_status != ABSENT:
        changes["consumers"] = tuple(
            c.model_copy(update={"status": cp2_status}) if c.module_id == MODULE_ID else c
            for c in submission.consumers
        )
    module = cp1a_module(business_context(scope, submission.model_copy(update=changes)), (), 0)
    status = "restricted" if module.limitations else "accepted"
    return module.model_copy(update={"status": status})


def blocked_cp1a(pack: PreparedPack) -> Module:
    """What the journal stores for a CP-1A whose repair failed: limitations, no registers."""
    return module_of(
        pack, "CP-1A", status="blocked", limitations=("Malformed candidate: (root): Invalid JSON",)
    )


def bound_inputs(pack: PreparedPack, cp0: Module, cp1: Module, cp1a: Module) -> tuple[Input, ...]:
    return (
        Input(input_id="prepared-pack", sha256=pack.content_hash()),
        Input(input_id="CP-0", sha256=cp0.content_hash(), status=cp0.status),
        Input(input_id="CP-1", sha256=cp1.content_hash(), status=cp1.status),
        Input(input_id="CP-1A", sha256=cp1a.content_hash(), status=cp1a.status),
    )


def upstream_of(
    pack: PreparedPack,
    *,
    cp1a: Module | None = None,
    current: tuple[Input, ...] | str | None = None,
) -> Upstream:
    cp0, cp1 = cp0_head(pack), cp1_head(pack)
    cp1a = cp1a if cp1a is not None else cp1a_head(pack)
    bound = bound_inputs(pack, cp0, cp1, cp1a)
    return Upstream(
        bound=bound, current=bound if current is None else current, cp1=cp1, cp1a=cp1a, inherited=()
    )


def synthesis(**changes: object) -> CreditSynthesisSubmission:
    """A valid synthetic submission over `upstream_of(pack_fixture())`."""
    base = CreditSynthesisSubmission(
        assessment=Assessment(
            rationale=f"Liquidity of {LIQUIDITY} carries a thinly disclosed issuer.",
            category="Analyst Interpretation",
            confidence="Low",
            cp1a_refs=(TRANSLATION,),
            limitation=None,
        ),
        thesis=Thesis(
            text="Liquidity, not disclosure, supports the credit.",
            category="Analyst Interpretation",
            cp1a_refs=(TRANSLATION,),
            limitation=None,
        ),
        strengths=(
            Point(
                label="Liquidity",
                text=f"Liquidity was {LIQUIDITY} in FY2025.",
                category="Documentary Fact",
                cp1a_refs=(),
                limitation=None,
            ),
            Point(
                label="Reporting",
                text="An annual figure is reported.",
                category="Documentary Fact",
                cp1a_refs=(REPORTING,),
                limitation=None,
            ),
        ),
        weaknesses=(
            Point(
                label="Disclosure",
                text="No segment disclosure limits revenue visibility.",
                category="Analyst Interpretation",
                cp1a_refs=(SEGMENT_GAP,),
                limitation=None,
            ),
            Point(
                label="Maturities",
                text="The maturity profile is not disclosed.",
                category="Insufficient Information",
                cp1a_refs=(),
                limitation="No debt schedule in the pack",
            ),
        ),
        key_findings=(
            Finding(text=f"Liquidity was {LIQUIDITY} in FY2025.", cp1a_refs=()),
            Finding(
                text="Thin disclosure keeps the monitoring posture cautious.",
                cp1a_refs=(TRANSLATION, DEBT_SCHEDULE),
            ),
        ),
        risks=(
            Risk(
                risk="Refinancing visibility",
                mechanic="No debt schedule hides the maturity profile.",
                implication="Refinancing risk cannot be bounded.",
                severity="Material",
                cp1a_refs=(DEBT_SCHEDULE,),
            ),
        ),
        gaps=(
            SynthesisGap(
                gap="No segment disclosure",
                why_it_matters="Revenue durability cannot be judged",
                affected_analysis="Business risk",
                severity="Material",
                action="Obtain the segment note",
                cp1a_refs=(SEGMENT_GAP, CP2_READINESS),
            ),
        ),
    )
    return base.model_copy(update=changes)


def figures_only(**changes: object) -> CreditSynthesisSubmission:
    """A valid submission that cites no CP-1A row (for a blocked CP-1A): every row's basis is a
    CP-1 figure, or it is Insufficient Information."""
    base = synthesis()
    return synthesis(
        assessment=base.assessment.model_copy(update={"cp1a_refs": ()}),
        thesis=base.thesis.model_copy(
            update={"text": f"Liquidity of {LIQUIDITY} supports the credit.", "cp1a_refs": ()}
        ),
        strengths=(base.strengths[0],),
        weaknesses=(base.weaknesses[1],),
        key_findings=(base.key_findings[0],),
        risks=(
            base.risks[0]
            .model_copy(update={"mechanic": f"Liquidity of {LIQUIDITY} meets no known maturity."})
            .model_copy(update={"cp1a_refs": ()}),
        ),
        gaps=(base.gaps[0].model_copy(update={"cp1a_refs": ()}),),
    ).model_copy(update=changes)


def issues_of(submission: CreditSynthesisSubmission, up: Upstream | None = None) -> tuple[str, ...]:
    pack = pack_fixture()
    return validate_credit_synthesis(pack, submission, up or upstream_of(pack))


# --- acceptance and composition ---------------------------------------------------------------


def test_a_valid_submission_composes_the_r14_registers_and_the_front_page_tables() -> None:
    pack = pack_fixture()
    up = upstream_of(pack)
    assert validate_credit_synthesis(pack, synthesis(), up) == ()
    report = credit_synthesis(pack, synthesis(), up)
    tables = {t.table_id: t for t in report.tables}
    assert REQUIRED_TABLES == ("T2.1", "T2.7", "T2.10", "T2.11", "T2.12")
    assert set(REQUIRED_TABLES) | {KEY_FINDINGS, THESIS, STRENGTHS, WEAKNESSES, CP1_REFERENCES} == (
        tables.keys()
    )
    cells = {f.fact_id: f for f in report.facts}
    shown = spelled(cp1_fact(pack))
    assert cells["T2.10.kf01.finding"].text == f"Liquidity was {shown} in FY2025."
    assert cells["T2.10.kf01.basis"].text == "CP-1 Liquidity · FY2025"
    assert cells["T2.10.kf02.basis"].text == (
        "CP-1A credit_translation.r01 (Credit translation 1); CP-1A T2D.7.r01 (Debt schedule)"
    )
    assert cells["T2.1.assessment.confidence"].text == "Low"
    assert cells["T2.1.assessment.assessment"].text == (
        f"Liquidity of {shown} carries a thinly disclosed issuer. [Analyst Interpretation]"
    )
    assert cells["T2.11.r01.severity"].text == "Material"
    assert cells["T2.12.g01.gap_id"].text == "CP-2-GAP-001"
    assert report.limitations == ("Gap (Material): No segment disclosure",)
    assert [c.claim_id for c in report.claims] == ["T2.1.assessment", "T2.10.kf01", "T2.10.kf02"]
    assert report.schema_version == "credit-synthesis/1"
    module = cp2_module(report, up.bound, 0)  # the Module validator holds the table layout
    assert module.module_id == MODULE_ID and module.status == "candidate"
    assert module.inputs[-1].input_id == "credit-synthesis-submission"
    assert module.inputs[:-1] == up.bound


def test_python_numbers_the_rows_labels_the_columns_and_tags_the_categories() -> None:
    report = credit_synthesis(pack_fixture(), synthesis(), upstream_of(pack_fixture()))
    tables = {t.table_id: t for t in report.tables}
    cells = {f.fact_id: f for f in report.facts}
    assert [r.label for r in tables["T2.7"].rows] == [
        "Thesis",
        "Strength 1",
        "Strength 2",
        "Weakness 1",
        "Weakness 2",
    ]
    assert [r.row_id for r in tables["T2.10"].rows] == ["kf01", "kf02"]
    assert [r.label for r in tables[KEY_FINDINGS].rows] == ["Key finding 1", "Key finding 2"]
    assert cells["T2.7.w02.text"].text == (
        "The maturity profile is not disclosed. [Insufficient Information]"
    )
    assert cells["T2.7.w02.basis"].text == "No CP-1A row or CP-1 figure cited"
    assert cells["T2.7.s01.side"].text == "Strength"
    assert cells["T2.7.thesis.side"].text == "Thesis"
    # The Front Page tables: one value per row, the strength's own label, text as the register.
    strengths = [f for f in report.facts if f.table_id == STRENGTHS]
    assert [f.label for f in strengths] == ["Liquidity", "Reporting"]
    assert [f.text for f in strengths] == [cells["T2.7.s01.text"].text, cells["T2.7.s02.text"].text]
    assert all(f.value_class == "analyst_judgment" for f in strengths)
    assert cells[f"{THESIS}.thesis.value"].label == "Thesis"
    assert tables["T2.12"].columns[0].label == "Gap ID"


def test_referenced_cp1_figures_are_carried_verbatim() -> None:
    pack = pack_fixture()
    report = credit_synthesis(pack, synthesis(), upstream_of(pack))
    carried = [f for f in report.facts if f.table_id == CP1_REFERENCES]
    upstream = cp1_fact(pack)
    assert [f.fact_id for f in carried] == [upstream.fact_id]
    assert (
        carried[0].model_copy(
            update={
                "table_id": upstream.table_id,
                "row_id": upstream.row_id,
                "field": upstream.field,
            }
        )
        == upstream
    )


def test_empty_registers_are_explicit_rows_and_only_required_ones_limit() -> None:
    pack = pack_fixture()
    up = upstream_of(pack, cp1a=cp1a_head(pack, cp2_status="READY"))  # no signal to restate
    empty = synthesis(strengths=(), risks=(), gaps=())
    assert validate_credit_synthesis(pack, empty, up) == ()
    report = credit_synthesis(pack, empty, up)
    cells = {f.fact_id: f for f in report.facts}
    assert report.limitations == (
        "No strengths rows in the CP-2 submission",
        "No key credit risks rows in the CP-2 submission",
    )
    assert cells[f"{STRENGTHS}.none.value"].status == "missing"
    assert cells["T2.11.none.risk"].status == "missing"
    assert cells["T2.12.none.gap"].status == "not_applicable"  # no gap is not a gap
    no_findings = synthesis(key_findings=())
    assert "No key findings rows in the CP-2 submission" in (
        credit_synthesis(pack, no_findings, up).limitations
    )


def test_an_insufficient_assessment_is_an_own_limitation() -> None:
    pack = pack_fixture()
    insufficient = synthesis(
        assessment=Assessment(
            rationale="The pack cannot support a credit view.",
            category="Insufficient Information",
            confidence="Insufficient Information",
            cp1a_refs=(),
            limitation="One synthetic line only",
        ),
        gaps=(),
    )
    ready = upstream_of(pack, cp1a=cp1a_head(pack, cp2_status="READY"))  # no signal to restate
    report = credit_synthesis(pack, insufficient, ready)
    assert report.limitations == (
        "Credit assessment is Insufficient Information: One synthetic line only",
    )


# --- rejections ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("The issuer ranks above peers on liquidity.", "peer ranking"),
        ("We recommend the secured notes.", "instrument recommendation"),
        ("The notes would recover in full.", "recovery conclusion"),
        ("An expected recovery protects holders.", "recovery conclusion"),
    ],
)
def test_prohibited_conclusions_belong_to_cp3_and_cp6(text: str, kind: str) -> None:
    finding = Finding(text=text, cp1a_refs=(TRANSLATION,))
    found = issues_of(synthesis(key_findings=(finding,)))
    assert any(f"key_findings[0].text: prohibited conclusion ({kind})" in i for i in found)
    # No quote exemption: CP-2 quotes nothing, so even a Documentary Fact row may not say it.
    thesis = synthesis().thesis.model_copy(update={"text": text, "category": "Documentary Fact"})
    assert any(
        "thesis.text: prohibited conclusion" in i for i in issues_of(synthesis(thesis=thesis))
    )


def test_a_bare_figure_and_an_unoffered_reference_are_rejected() -> None:
    bare = Finding(text="Liquidity was 1,100 in FY2025.", cp1a_refs=(TRANSLATION,))
    assert "key_findings[0].text: Bare figure: 1,100" in issues_of(synthesis(key_findings=(bare,)))
    gap = Finding(text="Cover was {T4.10.interest_cover.FY2025|x}.", cp1a_refs=(TRANSLATION,))
    assert "key_findings[0].text: Unresolved reference: T4.10.interest_cover.FY2025" in issues_of(
        synthesis(key_findings=(gap,))
    )
    label = synthesis().strengths[0].model_copy(update={"label": "Top 3"})
    assert "strengths[0].label: Bare figure: 3" in issues_of(synthesis(strengths=(label,)))


def test_unknown_or_placeholder_cp1a_refs_are_rejected() -> None:
    finding = Finding(text="Disclosure is thin.", cp1a_refs=("credit_translation.r09",))
    placeholder = Finding(text="Nothing conflicts.", cp1a_refs=("conflict_log.none",))
    found = issues_of(synthesis(key_findings=(finding, placeholder)))
    assert "key_findings[0].cp1a_refs: unknown CP-1A row credit_translation.r09" in found
    assert "key_findings[1].cp1a_refs: unknown CP-1A row conflict_log.none" in found
    referenced = issues_of(
        synthesis(key_findings=(Finding(text="x", cp1a_refs=(CP1_REFERENCES,)),))
    )
    assert f"key_findings[0].cp1a_refs: unknown CP-1A row {CP1_REFERENCES}" in referenced


def test_a_stale_or_refused_input_set_is_rejected() -> None:
    pack = pack_fixture()
    up = upstream_of(pack)
    moved = tuple(
        item.model_copy(update={"sha256": "f" * 64}) if item.input_id == "CP-1A" else item
        for item in up.bound
    )
    stale = upstream_of(pack, current=moved)
    found = validate_credit_synthesis(pack, synthesis(), stale)
    assert [i for i in found if i.startswith("Stale input")] == [
        f"Stale input CP-1A: bound restricted {up.bound[-1].sha256[:12]}, "
        f"current restricted {'f' * 12}"
    ]
    refused = upstream_of(pack, current="Required upstream is unrun, stale or blocked")
    assert "Stale inputs: Required upstream is unrun, stale or blocked" in (
        validate_credit_synthesis(pack, synthesis(), refused)
    )


def test_an_upstream_module_must_be_the_bound_head() -> None:
    pack = pack_fixture()
    up = upstream_of(pack)
    other = cp1a_head(pack, gaps=())
    swapped = Upstream(bound=up.bound, current=up.current, cp1=up.cp1, cp1a=other, inherited=())
    found = validate_credit_synthesis(pack, synthesis(), swapped)
    assert "Upstream CP-1A: the supplied module is not the bound input" in found
    unbound = Upstream(
        bound=up.bound[:3], current=up.bound[:3], cp1=up.cp1, cp1a=up.cp1a, inherited=()
    )
    assert "Upstream CP-1A: the supplied module is not the bound input" in (
        validate_credit_synthesis(pack, synthesis(), unbound)
    )


def test_every_row_needs_a_basis_unless_it_is_insufficient_information() -> None:
    base = synthesis()
    bare = base.strengths[1].model_copy(update={"cp1a_refs": ()})
    found = issues_of(synthesis(strengths=(base.strengths[0], bare)))
    assert "strengths[1]: a Documentary Fact row cites a CP-1A row or a CP-1 figure" in found
    finding = Finding(text="Disclosure is thin.", cp1a_refs=())
    assert "key_findings[0]: a key finding cites a CP-1A row or a CP-1 figure" in issues_of(
        synthesis(key_findings=(finding,))
    )
    risk = base.risks[0].model_copy(update={"cp1a_refs": ()})
    assert "risks[0]: a risk cites a CP-1A row or a CP-1 figure" in issues_of(
        synthesis(risks=(risk,))
    )
    silent = base.weaknesses[1].model_copy(update={"limitation": None})
    assert "weaknesses[1]: an Insufficient Information row states its limitation" in issues_of(
        synthesis(weaknesses=(base.weaknesses[0], silent))
    )
    unsure = base.assessment.model_copy(
        update={"confidence": "Insufficient Information", "cp1a_refs": ()}
    )
    found = issues_of(synthesis(assessment=unsure))
    assert "assessment: an Insufficient Information confidence states its limitation" in found
    assert not any("assessment: a" in i and "cites" in i for i in found)  # its figure is a basis
    gap = base.gaps[0].model_copy(update={"cp1a_refs": ()})
    ready = upstream_of(pack_fixture(), cp1a=cp1a_head(pack_fixture(), cp2_status="READY"))
    assert issues_of(synthesis(gaps=(gap,)), ready) == ()  # a gap needs no basis


def test_text_is_never_blank_and_malformed_references_are_issues() -> None:
    base = synthesis()
    blank = base.thesis.model_copy(update={"text": "  "})
    assert "thesis.text: empty text" in issues_of(synthesis(thesis=blank))
    broken = Finding(text="Liquidity {T4.10.liquidity.FY2025", cp1a_refs=())
    found = issues_of(synthesis(key_findings=(broken,)))
    assert any(i.startswith("key_findings[0].text: Malformed run text") for i in found)
    assert "key_findings[0]: a key finding cites a CP-1A row or a CP-1 figure" in found


def test_a_blocked_cp1a_offers_no_rows_and_caps_confidence() -> None:
    pack = pack_fixture()
    blocked = upstream_of(pack, cp1a=blocked_cp1a(pack))
    assert blocked.catalogue == {}
    assert "key_findings[1].cp1a_refs: unknown CP-1A row credit_translation.r01" in (
        validate_credit_synthesis(pack, synthesis(), blocked)
    )
    assert validate_credit_synthesis(pack, figures_only(), blocked) == ()
    high = figures_only().assessment.model_copy(update={"confidence": "High"})
    assert "assessment.confidence: capped below High because CP-1A is blocked" in (
        validate_credit_synthesis(pack, figures_only(assessment=high), blocked)
    )
    assert validate_credit_synthesis(pack, synthesis(assessment=synthesis().assessment.model_copy(
        update={"confidence": "High"})),
        upstream_of(pack, cp1a=cp1a_head(pack, cp2_status="READY"))) == ()  # fmt: skip


def critical(gap: str = "No debt schedule") -> Gap:
    return Gap(
        gap=gap,
        why_it_matters="Refinancing cannot be assessed",
        affected_analysis="Liquidity",
        severity="Critical",
        action="Obtain the debt footnote",
    )


def test_each_critical_cp1a_gap_is_restated_and_caps_confidence() -> None:
    pack = pack_fixture()
    head = cp1a_head(pack, gaps=(critical(), *submission_fixture(pack).gaps), cp2_status="READY")
    assert [(item.ref, item.status) for item in cp2_signals(head)] == [
        ("gaps_ledger.r01", "Critical")
    ]
    up = upstream_of(pack, cp1a=head)
    found = validate_credit_synthesis(pack, synthesis(), up)
    assert (
        "gaps: restate the Critical CP-1A gap gaps_ledger.r01 in a gaps row that cites it"
        not in (found)
    )  # the base gap row cites gaps_ledger.r01, which is now the Critical gap
    moved = synthesis(
        gaps=(synthesis().gaps[0].model_copy(update={"cp1a_refs": ("gaps_ledger.r02",)}),)
    )
    assert "gaps: restate the Critical CP-1A gap gaps_ledger.r01 in a gaps row that cites it" in (
        validate_credit_synthesis(pack, moved, up)
    )
    high = synthesis().assessment.model_copy(update={"confidence": "High"})
    assert "assessment.confidence: capped below High because CP-1A records a Critical gap" in (
        validate_credit_synthesis(pack, synthesis(assessment=high), up)
    )


def test_a_critical_disclosure_item_is_restated_and_caps_confidence() -> None:
    pack = pack_fixture()
    head_ = cp1a_head(pack, cp2_status="READY", disclosures=("Material", "Critical"))
    assert [(item.ref, item.status) for item in cp2_signals(head_)] == [("T2D.7.r02", "Critical")]
    up = upstream_of(pack, cp1a=head_)
    restate = (
        "gaps: restate the Critical CP-1A disclosure item T2D.7.r02 in a gaps row that cites it"
    )
    assert restate in validate_credit_synthesis(pack, synthesis(), up)
    gap = synthesis().gaps[0].model_copy(update={"cp1a_refs": (SEGMENT_GAP, "T2D.7.r02")})
    assert validate_credit_synthesis(pack, synthesis(gaps=(gap,)), up) == ()
    high = synthesis().assessment.model_copy(update={"confidence": "High"})
    capped = "assessment.confidence: capped below High because CP-1A records a Critical disclosure"
    assert f"{capped} item" in validate_credit_synthesis(
        pack, synthesis(assessment=high, gaps=(gap,)), up
    )


@pytest.mark.parametrize("status", ["READY_WITH_LIMITATIONS", "CONDITIONAL", "BLOCKED"])
def test_a_cp2_readiness_below_ready_is_restated_and_caps_confidence(status: str) -> None:
    pack = pack_fixture()
    up = upstream_of(pack, cp1a=cp1a_head(pack, cp2_status=status))
    assert [(item.ref, item.status) for item in up.signals] == [(CP2_READINESS, status)]
    unstated = synthesis().gaps[0].model_copy(update={"cp1a_refs": (SEGMENT_GAP,)})
    assert (
        f"gaps: restate CP-1A's {status} readiness of CP-2 ({CP2_READINESS}) in a gaps row "
        "that cites it"
    ) in validate_credit_synthesis(pack, synthesis(gaps=(unstated,)), up)
    high = synthesis().assessment.model_copy(update={"confidence": "High"})
    assert f"assessment.confidence: capped below High because CP-1A judges CP-2 {status}" in (
        validate_credit_synthesis(pack, synthesis(assessment=high), up)
    )
    assert validate_credit_synthesis(pack, synthesis(), up) == ()
    limited = "CP-1A judges CP-2 BLOCKED: Segment and transaction gaps"
    assert (limited in credit_synthesis(pack, synthesis(), up).limitations) == (status == "BLOCKED")


def test_a_ready_cp2_readiness_sends_no_signal() -> None:
    pack = pack_fixture()
    up = upstream_of(pack, cp1a=cp1a_head(pack, cp2_status="READY"))
    assert up.signals == ()
    high = synthesis().assessment.model_copy(update={"confidence": "High"})
    assert validate_credit_synthesis(pack, synthesis(assessment=high), up) == ()
    assert credit_synthesis(pack, synthesis(), up).limitations == (
        "Gap (Material): No segment disclosure",
    )


def test_a_missing_cp2_readiness_row_limits_and_caps() -> None:
    pack = pack_fixture()
    up = upstream_of(pack, cp1a=cp1a_head(pack, cp2_status=ABSENT))
    assert [(item.ref, item.status) for item in up.signals] == [(None, ABSENT)]
    high = synthesis().assessment.model_copy(update={"confidence": "High"})
    assert (
        "assessment.confidence: capped below High because CP-1A records no readiness judgment "
        "of CP-2"
    ) in validate_credit_synthesis(pack, synthesis(assessment=high), up)
    assert not any(i.startswith("gaps: restate") for i in validate_credit_synthesis(
        pack, synthesis(), up))  # fmt: skip
    assert "CP-1A records no readiness judgment of CP-2" in (
        credit_synthesis(pack, synthesis(), up).limitations
    )


# --- the journal: one step settles CP-2 -------------------------------------------------------


def journal(tmp_path: Path, *, block_cp1a: bool = False) -> Execution:
    """A SYNTHETIC journal with CP-0, CP-1 and CP-1A settled (or CP-1A blocked)."""
    pack, review = readiness_fixture()
    store = Execution.create(tmp_path / "execution", pack)
    ticket = store.begin("CP-0")
    store.finish(
        ticket.ticket_id, build_readiness(store.pack(), review).model_dump_json(), lambda _: ()
    )
    ticket = store.begin("CP-1")
    run = pack.run
    cp1 = Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id="CP-1",
        inputs=ticket.inputs,
        facts=(cp1_fact(pack),),
    )
    store.finish(ticket.ticket_id, cp1.model_dump_json(), lambda _: ())
    if block_cp1a:
        for _ in range(2):
            ticket = store.begin("CP-1A")
            store.finish(ticket.ticket_id, "not json", lambda _: ())
    else:
        ticket = store.begin("CP-1A")
        payload = submission_fixture(pack).model_dump_json()
        submit_cp1a_step(store, ticket.ticket_id, "business_context", payload)
    return store


def head(store: Execution, module_id: str) -> Module:
    found = next(h for h in store.read().heads if h.module_id == module_id)
    return store.result(found.result_sha256)


def test_the_step_settles_cp2_with_the_python_candidate(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    upstream = cp2_upstream(store, ticket)
    assert upstream.cp1a_status == "restricted" and upstream.current == ticket.inputs
    attempt = submit_cp2_step(store, ticket.ticket_id, STEP_ID, synthesis().model_dump_json())
    assert attempt.status == "finished" and attempt.issues == ()
    cp2 = head(store, MODULE_ID)
    assert cp2.status == "restricted"  # own gap row, and a synthetic case
    assert "Synthetic case; not real issuer qualification" in cp2.limitations
    assert "Gap (Material): No business segment disclosure" in cp2.inherited_limitations
    assert {i.input_id for i in cp2.inputs} >= {"CP-0", "CP-1", "CP-1A"}
    record = next(h for h in store.read().heads if h.module_id == MODULE_ID)
    assert record.qualification is not None
    assert record.qualification.implementation == "implemented"
    with pytest.raises(ValueError, match="one step"):
        submit_cp2_step(store, ticket.ticket_id, "business_context", "{}")
    with pytest.raises(ValueError, match="absent, finished"):
        submit_cp2_step(store, ticket.ticket_id, STEP_ID, synthesis().model_dump_json())


def test_an_invalid_step_rejects_then_blocks_with_its_issues(tmp_path: Path) -> None:
    store = journal(tmp_path)
    unknown = synthesis(
        key_findings=(Finding(text="Thin.", cp1a_refs=("credit_translation.r09",)),)
    )
    for number, status in ((0, "rejected"), (1, "blocked")):
        ticket = store.begin(MODULE_ID)
        assert ticket.number == number
        attempt = submit_cp2_step(store, ticket.ticket_id, STEP_ID, unknown.model_dump_json())
        assert "key_findings[0].cp1a_refs: unknown CP-1A row credit_translation.r09" in (
            attempt.issues
        )
        assert store.result(str(attempt.result_sha256)).status == status
    malformed = journal(tmp_path / "other")
    ticket = malformed.begin(MODULE_ID)
    attempt = submit_cp2_step(malformed, ticket.ticket_id, STEP_ID, '{"thesis": 1}')
    assert any(i.startswith("assessment: Field required") for i in attempt.issues)


def test_a_blocked_cp1a_restricts_cp2_through_the_inherited_limitation(tmp_path: Path) -> None:
    store = journal(tmp_path, block_cp1a=True)
    ticket = store.begin(MODULE_ID)
    assert next(i for i in ticket.inputs if i.input_id == "CP-1A").status == "blocked"
    submit_cp2_step(store, ticket.ticket_id, STEP_ID, figures_only().model_dump_json())
    cp2 = head(store, MODULE_ID)
    assert cp2.status == "restricted"
    blocked = head(store, "CP-1A")
    assert [f"Upstream CP-1A blocked: {text}" for text in blocked.limitations] == [
        text for text in cp2.inherited_limitations if text.startswith("Upstream CP-1A blocked")
    ]


def test_a_changed_pack_stales_the_bound_inputs(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    attempt = submit_cp2_step(store, ticket.ticket_id, STEP_ID, synthesis().model_dump_json())
    pack = store.pack()
    source = pack.sources[0].model_copy(update={"name": "Renamed synthetic filing"})
    store.replace_pack(pack.model_copy(update={"sources": (source,)}))
    upstream = cp2_upstream(store, attempt)
    assert upstream.current == "Required upstream is unrun, stale or blocked"
    assert "Stale inputs: Required upstream is unrun, stale or blocked" in (
        validate_credit_synthesis(store.pack(), synthesis(), upstream)
    )


def test_a_resumed_step_reuses_the_retained_response(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    payload = synthesis().model_dump_json()
    # A crash after the step was retained and validated, before settlement.
    store.submit_step(
        ticket.ticket_id,
        MODULE_ID,
        (STEP_ID,),
        STEP_ID,
        payload,
        lambda pack, current: validate_step(store, pack, current),
    )
    with pytest.raises(ValueError, match="different response"):
        submit_cp2_step(store, ticket.ticket_id, STEP_ID, synthesis(gaps=()).model_dump_json())
    attempt = submit_cp2_step(store, ticket.ticket_id, STEP_ID, payload)
    assert attempt.status == "finished" and head(store, MODULE_ID).status == "restricted"


# --- the CONTEXT block ---------------------------------------------------------------------------


def test_the_context_block_prefills_figures_rows_gaps_and_statuses() -> None:
    pack = pack_fixture()
    head_ = cp1a_head(pack, gaps=(critical(),))
    up = Upstream(
        bound=upstream_of(pack, cp1a=head_).bound,
        current=upstream_of(pack, cp1a=head_).bound,
        cp1=cp1_head(pack),
        cp1a=head_,
        inherited=("Gap (Critical): No debt schedule",),
    )
    block = context_block(pack, up)
    assert block["upstream"] == [
        {"module_id": "CP-0", "status": "restricted"},
        {"module_id": "CP-1", "status": "accepted"},
        {"module_id": "CP-1A", "status": "restricted"},
    ]
    assert [f["ref"] for f in block["cp1_facts"]] == [
        "T4.10.liquidity.FY2025",
        "T4.10.total_leverage.FY2025",
    ]
    assert block["cp1_facts"][0]["shown"] == spelled(cp1_fact(pack))
    rows = {row["ref"]: row for row in block["cp1a_rows"]}
    assert rows[TRANSLATION]["register"] == "Credit translation"
    assert rows[TRANSLATION]["row"] == "Credit translation 1"
    assert rows[TRANSLATION]["cells"]["confidence"] == "Low"
    assert "conflict_log.none" not in rows and CP1_REFERENCES not in json.dumps(list(rows))
    assert set(rows) == set(cp1a_catalogue(head_))
    assert block["cp1a_signals"] == [
        {
            "ref": "gaps_ledger.r01",
            "source": "gaps_ledger",
            "status": "Critical",
            "restate": True,
            "limits": False,
        },
        {
            "ref": CP2_READINESS,
            "source": "downstream_readiness",
            "status": "READY_WITH_LIMITATIONS",
            "restate": True,
            "limits": False,
        },
    ]
    assert block["inherited_limitations"] == ["Gap (Critical): No debt schedule"]
    blocked = context_block(pack, upstream_of(pack, cp1a=blocked_cp1a(pack)))
    assert blocked["cp1a_rows"] == [] and blocked["cp1a_signals"] == []
    absent = context_block(pack, upstream_of(pack, cp1a=cp1a_head(pack, cp2_status=ABSENT)))
    assert absent["cp1a_signals"] == [
        {"ref": None, "source": "downstream_readiness", "status": ABSENT, "restate": False,
         "limits": True}
    ]  # fmt: skip
    assert "CP-1A is blocked" in str(blocked["cp1a_rows_note"])
    bare = Upstream(
        bound=up.bound, current=up.bound, cp1=module_of(pack, "CP-1"), cp1a=head_, inherited=()
    )
    assert "no figure may be referenced" in str(context_block(pack, bare)["cp1_facts_note"])


# --- the sent schema ----------------------------------------------------------------------------


def nodes(node: object) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        return [node, *(n for value in node.values() for n in nodes(value))]
    if isinstance(node, list):
        return [n for item in node for n in nodes(item)]
    return []


def test_the_sent_schema_is_strict_and_needs_no_relaxation() -> None:
    sent = strict_schema(CreditSynthesisSubmission)
    assert relax(strict_copy(CreditSynthesisSubmission)) == sent
    text = json.dumps(sent)
    assert '"const"' not in text and '"oneOf"' not in text and '"default"' not in text
    for node in nodes(sent):
        assert None not in node.get("enum", ()), node
        if "properties" in node:
            assert node["required"] == list(node["properties"]) and not node["additionalProperties"]
    assert sent["properties"]["key_findings"]["minItems"] == 1
    assert list(sent["properties"]) == [
        "assessment",
        "thesis",
        "strengths",
        "weaknesses",
        "key_findings",
        "risks",
        "gaps",
    ]
    assert schema_relaxations(CreditSynthesisSubmission) == []
    assert '"quote"' not in text  # ruling 2: upstream references only, no pack quotes


# --- Property 1: figure identity ----------------------------------------------------------------

GOOD = ("{T4.10.liquidity.FY2025|US$ m}", "{T4.10.total_leverage.FY2025|x}", "{k1|x}")
BAD = (
    "1,100",
    "3.5x",
    "{T4.10.ghost.FY2025|US$ m}",
    "{T4.10.interest_cover.FY2025|x}",
    "[T4.10.liquidity.FY2025]",
    "{T4.10.liquidity.FY2025|x}",
)
WORDS = ("liquidity", "is", "stable", "FY2025", "Item 7A", "cover", "the")


@settings(max_examples=150, deadline=None)
@given(st.lists(st.sampled_from((*WORDS, *GOOD, *BAD)), min_size=1, max_size=8))
def test_composed_figures_are_the_upstream_facts_and_nothing_else_resolves(
    words: list[str],
) -> None:
    pack = pack_fixture()
    up = upstream_of(pack)
    text = " ".join(words)
    finding = Finding(text=text, cp1a_refs=(TRANSLATION,))
    strength = (
        synthesis().strengths[0].model_copy(update={"text": text, "cp1a_refs": (TRANSLATION,)})
    )
    submission = synthesis(key_findings=(finding,), strengths=(strength,))
    issues = validate_credit_synthesis(pack, submission, up)
    assert bool(issues) == any(word in BAD for word in words)
    if issues:
        with pytest.raises(ValueError):
            credit_synthesis(pack, submission, up)
        return
    report = credit_synthesis(pack, submission, up)
    offered = {f.fact_id: f for f in (cp1_fact(pack), leverage_fact())}
    carried = {f.fact_id: f for f in report.facts if f.table_id == CP1_REFERENCES}
    for fact_id, fact in carried.items():
        source = offered[fact_id]
        assert (
            fact.model_copy(
                update={"table_id": source.table_id, "row_id": source.row_id, "field": source.field}
            )
            == source
        )
    named = {"T4.10.liquidity.FY2025"} | {
        "T4.10.total_leverage.FY2025" for w in words if "leverage" in w or "k1" in w
    }
    assert set(carried) == named  # the base strength 0 and assessment name liquidity
    expected = text
    for ref, fact in (
        (GOOD[0], offered["T4.10.liquidity.FY2025"]),
        (GOOD[1], offered["T4.10.total_leverage.FY2025"]),
        (GOOD[2], offered["T4.10.total_leverage.FY2025"]),
    ):
        expected = expected.replace(ref, spelled(fact))
    cells = {f.fact_id: f for f in report.facts}
    assert cells["T2.10.kf01.finding"].text == expected
    assert cells[f"{KEY_FINDINGS}.kf01.value"].text == expected


# --- Property 2: gap propagation is monotone ----------------------------------------------------

SEVERITIES = ("Critical", "Material", "Minor")
CONFIDENCES = ("High", "Medium", "Low", "Insufficient Information")


def settled_cp2(pack: PreparedPack, up: Upstream, submission: CreditSynthesisSubmission) -> Module:
    """CP-2 settled by the journal's own `settle` over in-memory heads (the existing CP-1A
    inheritance and decision 0007 status path), with no store."""
    report = credit_synthesis(pack, submission, up)
    candidate = cp2_module(report, up.bound, 0)
    payload = candidate.model_dump_json()
    modules = {"CP-0": cp0_head(pack), "CP-1": up.cp1, "CP-1A": up.cp1a}
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


READINESS = ("READY", "READY_WITH_LIMITATIONS", "CONDITIONAL", "BLOCKED", ABSENT)


@settings(max_examples=100, deadline=None)
@given(
    st.booleans(),
    st.lists(st.sampled_from(SEVERITIES), max_size=3),
    st.lists(st.sampled_from(SEVERITIES), max_size=2),
    st.sampled_from(READINESS),
    st.sampled_from(CONFIDENCES),
    st.booleans(),
)
def test_a_blocked_cp1a_or_any_cp1a_signal_always_limits_and_caps_cp2(
    blocked: bool,
    severities: list[str],
    disclosures: list[str],
    readiness: str,
    confidence: str,
    restate: bool,
) -> None:
    pack = public_pack()
    gaps = tuple(critical(f"Gap {chr(65 + i)}").model_copy(update={"severity": s})
                 for i, s in enumerate(severities))  # fmt: skip
    cp1a = (
        blocked_cp1a(pack)
        if blocked
        else cp1a_head(pack, gaps=gaps, cp2_status=readiness, disclosures=tuple(disclosures))
    )
    up = upstream_of(pack, cp1a=cp1a)
    # The expectation is read from the drawn inputs, not from the code under test.
    capped = blocked or "Critical" in (*severities, *disclosures) or readiness != "READY"
    limits = not blocked and readiness in {"BLOCKED", ABSENT}
    assert bool(blocked or up.signals) == capped
    must = tuple(item.ref for item in up.signals if item.ref is not None)
    assert len(must) == (0 if blocked else (
        severities.count("Critical") + disclosures.count("Critical")
        + (readiness not in {"READY", ABSENT})))  # fmt: skip
    rows = tuple(
        SynthesisGap(
            gap="A CP-1A signal carried forward",
            why_it_matters="Confidence depends on it",
            affected_analysis="Credit assessment",
            severity="Critical",
            action="Obtain the missing source",
            cp1a_refs=(ref,),
        )
        for ref in must
        if restate
    )
    limitation = "No sufficient evidence" if confidence == "Insufficient Information" else None
    assessment = figures_only().assessment.model_copy(
        update={"confidence": confidence, "limitation": limitation}
    )
    submission = figures_only(assessment=assessment, gaps=rows)
    issues = validate_credit_synthesis(pack, submission, up)
    if capped and confidence == "High":
        assert any(i.startswith("assessment.confidence: capped below High") for i in issues)
    if must and not restate:
        assert any(i.startswith("gaps: restate") for i in issues)
    if issues:
        return
    result = settled_cp2(pack, up, submission)
    cells = {f.fact_id: f for f in result.facts}
    if capped:
        assert result.status == "restricted"
        assert result.limitations or result.inherited_limitations
        assert cells["T2.1.assessment.confidence"].text != "High"
    if blocked:
        assert "Upstream CP-1A blocked: Malformed candidate: (root): Invalid JSON" in (
            result.inherited_limitations
        )
    if must:
        assert any(text.startswith("Gap (Critical)") for text in result.limitations)
    assert limits == any(
        text.startswith("CP-1A judges CP-2 BLOCKED")
        or text == "CP-1A records no readiness judgment of CP-2"
        for text in result.limitations
    )


def test_a_clean_public_cp2_over_a_clean_cp1a_is_accepted() -> None:
    """The other side of Property 2: without a blocked input or any limitation, `accepted`."""
    pack = public_pack()
    up = upstream_of(pack, cp1a=cp1a_head(pack, gaps=(), cp2_status="READY"))
    assert up.cp1a.status == "accepted"
    clean_cp0 = cp0_head(pack)
    assert clean_cp0.status == "restricted"  # its limitation is inherited, never penalised
    result = settled_cp2(pack, up, figures_only(gaps=()))
    assert result.status == "accepted" and result.limitations == ()


# --- Property 3: the verdict does not depend on row order ---------------------------------------


def _unindexed(issues: tuple[str, ...]) -> set[str]:
    return {re.sub(r"\[[0-9]+\]", "[]", issue) for issue in issues}


@settings(max_examples=80, deadline=None)
@given(st.randoms(use_true_random=False), st.booleans(), st.booleans(), st.booleans())
def test_the_verdict_and_composition_do_not_depend_on_row_order(
    rng: random.Random, unknown: bool, bare: bool, high: bool
) -> None:
    pack = pack_fixture()
    head_ = cp1a_head(pack, gaps=(critical(), *submission_fixture(pack).gaps))
    up = upstream_of(pack, cp1a=head_)
    base = synthesis()
    findings = list(base.key_findings)
    if unknown:
        findings.append(Finding(text="Thin.", cp1a_refs=("credit_translation.r09", TRANSLATION)))
    if bare:
        findings.append(Finding(text="Cover is 2.4x.", cp1a_refs=(TRANSLATION,)))
    gaps = [
        base.gaps[0].model_copy(
            update={"cp1a_refs": ("gaps_ledger.r02", CP2_READINESS, "gaps_ledger.r01")}
        ),
        base.gaps[0].model_copy(update={"gap": "No debt schedule", "cp1a_refs": (DEBT_SCHEDULE,)}),
    ]
    assessment = base.assessment.model_copy(update={"confidence": "High" if high else "Low"})
    first = synthesis(assessment=assessment, key_findings=tuple(findings), gaps=tuple(gaps))

    def shuffled(items: list[Any]) -> tuple[Any, ...]:
        out = [i.model_copy(update={"cp1a_refs": tuple(rng.sample(i.cp1a_refs, len(i.cp1a_refs)))})
               for i in items]  # fmt: skip
        rng.shuffle(out)
        return tuple(out)

    second = first.model_copy(
        update={
            name: shuffled(list(getattr(first, name)))
            for name in ("strengths", "weaknesses", "key_findings", "risks", "gaps")
        }
    )
    one = validate_credit_synthesis(pack, first, up)
    two = validate_credit_synthesis(pack, second, up)
    assert bool(one) == bool(two) == (unknown or bare or high)
    assert _unindexed(one) == _unindexed(two)
    if not one:
        a, b = credit_synthesis(pack, first, up), credit_synthesis(pack, second, up)
        assert set(a.limitations) == set(b.limitations)
        assert {f.text for f in a.facts} == {f.text for f in b.facts}


# --- differentials: reference existence and staleness against a naive reference -------------


def synthetic_cp1a(pack: PreparedPack, rows: int, placeholder: bool) -> Module:
    """A CP-1A head with `rows` credit-translation rows and, optionally, an unsettled `none`
    row; only the settled rows are citable."""
    facts = [
        Fact(
            fact_id=f"credit_translation.r{i:02d}.evidence",
            label="Evidence",
            table_id="credit_translation",
            row_id=f"r{i:02d}",
            field="evidence",
            text=f"Synthetic evidence {chr(64 + i)}",
        )
        for i in range(1, rows + 1)
    ]
    if placeholder:
        facts.append(
            Fact(
                fact_id="credit_translation.none.evidence",
                label="Evidence",
                table_id="credit_translation",
                row_id="none",
                field="evidence",
                status="not_applicable",
                limitation="None in the CP-1A submission",
            )
        )
    table = ReportTable(
        table_id="credit_translation",
        title="Credit translation",
        columns=(TableColumn(field="evidence", label="Evidence"),),
        rows=tuple(
            TableRow(row_id=f.row_id, label=f"Credit translation {f.row_id}", fact_ids=(f.fact_id,))
            for f in facts
        ),
    )
    return module_of(pack, "CP-1A", facts=tuple(facts), tables=(table,))


REF_POOL = (
    *(f"credit_translation.r{i:02d}" for i in range(1, 7)),
    "credit_translation.none",
    "gaps_ledger.r01",
    "T2D.8.d01",
)


@settings(max_examples=120, deadline=None)
@given(
    st.integers(min_value=1, max_value=5),
    st.booleans(),
    st.lists(st.lists(st.sampled_from(REF_POOL), min_size=1, max_size=3), min_size=1, max_size=4),
    st.booleans(),
)
def test_reference_existence_matches_a_naive_set_reference(
    rows: int, placeholder: bool, refs: list[list[str]], blocked: bool
) -> None:
    pack = pack_fixture()
    head_ = synthetic_cp1a(pack, rows, placeholder)
    if blocked:  # the bound input says blocked: no row is citable, whatever the module holds
        head_ = head_.model_copy(update={"status": "blocked"})
    up = upstream_of(pack, cp1a=head_)
    findings = tuple(Finding(text="Thin disclosure.", cp1a_refs=tuple(r)) for r in refs)
    submission = figures_only(key_findings=findings)
    rows_ = {f"credit_translation.r{i:02d}" for i in range(1, rows + 1)}
    citable = set() if blocked else rows_
    naive = {(index, ref) for index, row in enumerate(refs) for ref in row if ref not in citable}
    found = {
        (int(m.group(1)), m.group(2))
        for issue in validate_credit_synthesis(pack, submission, up)
        if (
            m := re.fullmatch(
                r"key_findings\[([0-9]+)\]\.cp1a_refs: unknown CP-1A row (\S+)", issue
            )
        )
    }
    assert found == naive
    assert set(cp1a_catalogue(up.cp1a)) == rows_ and set(up.catalogue) == citable


IDS = ("prepared-pack", "CP-0", "CP-1", "CP-1A")
SHAS = ("a" * 64, "b" * 64)
STATUSES = ("accepted", "restricted", "blocked")


@settings(max_examples=150, deadline=None)
@given(
    st.one_of(
        st.none(),
        st.lists(
            st.tuples(st.sampled_from(IDS), st.sampled_from(SHAS), st.sampled_from(STATUSES)),
            max_size=4,
            unique_by=lambda item: item[0],
        ),
    ),
    st.lists(st.sampled_from(IDS), max_size=4, unique=True),
)
def test_staleness_matches_a_naive_set_reference(
    current: list[tuple[str, str, str]] | None, keep: list[str]
) -> None:
    pack = pack_fixture()
    up = upstream_of(pack)
    # Some current inputs are the bound ones unchanged (`keep`), the rest are generated.
    bound = {i.input_id: i for i in up.bound}
    if current is None:
        state: tuple[Input, ...] | str = "Required upstream is unrun, stale or blocked"
    else:
        generated = {i: Input.model_validate({"input_id": i, "sha256": s, "status": t})
                     for i, s, t in current}  # fmt: skip
        generated.update({i: bound[i] for i in keep})
        state = tuple(generated.values())
    probe = Upstream(bound=up.bound, current=state, cp1=up.cp1, cp1a=up.cp1a, inherited=())
    issues = validate_credit_synthesis(pack, synthesis(), probe)
    if isinstance(state, str):
        assert [i for i in issues if i.startswith("Stale")] == [f"Stale inputs: {state}"]
        return
    now = {i.input_id: i for i in state}
    naive = {key for key in bound.keys() | now.keys() if bound.get(key) != now.get(key)}
    found = {m.group(1) for i in issues if (m := re.match(r"Stale input (\S+):", i))}
    assert found == naive


# --- the Front Page: both blocks fill, with field parity (SYNTHETIC Credit Snapshot) -------------


def snapshot_with_cp2() -> tuple[View, Module]:
    """The SYNTHETIC Credit Snapshot view with its synthetic CP-2 rows replaced by a composed
    CP-2 module over the fixture's own CP-1 figures and CP-1A registers."""
    view = credit_snapshot_view()
    pack = pack_fixture()
    by_id = {m.module_id: m for m in view.modules}
    cp1 = module_of(pack, "CP-1", facts=by_id["CP-1"].facts)
    cp1a = cp1a_head(pack)
    cp0 = cp0_head(pack)
    bound = bound_inputs(pack, cp0, cp1, cp1a)
    up = Upstream(bound=bound, current=bound, cp1=cp1, cp1a=cp1a, inherited=())
    assert validate_credit_synthesis(pack, synthesis(), up) == ()
    module = cp2_module(credit_synthesis(pack, synthesis(), up), bound, 0)
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


def maps_with_cp2() -> tuple[BindingMap, ...]:
    return (*(m for m in CREDIT_SNAPSHOT_MAPS if m.module_id != MODULE_ID), CP2)


def test_both_cp2_blocks_fill_with_field_parity_on_the_synthetic_credit_snapshot() -> None:
    view, module = snapshot_with_cp2()
    assert validate_bindings(view, maps_with_cp2()) == ()  # every CP-2 fact bound exactly once
    pathway = next(p for p in pathways() if p.id == "credit_snapshot")
    blocks = {b.block_id: b for b in build(view, pathway, maps_with_cp2()).blocks}
    findings, sides = blocks["key-findings"], blocks["strengths-weaknesses"]
    assert findings.state == "populated" and findings.numbered and findings.pinned
    assert findings.owner == "CP-2" and "Synthetic" in findings.tags
    assert sides.state == "populated" and sides.owner == "CP-2 · CP-6"
    gaps = gap_ids(view)
    for block, tables in (
        (findings, (KEY_FINDINGS,)),
        (sides, (THESIS, STRENGTHS, WEAKNESSES)),
    ):
        bound = [f for t in tables for f in module.facts if f.table_id == t]
        expected = {f.fact_id: expected_text(f, gaps.get((MODULE_ID, f.fact_id))) for f in bound}
        assert len(block.lines) == len(bound)
        actual = {
            fact.fact_id: "".join(run.text for run in line.runs if run.kind != "fig")
            for fact, line in zip(bound, block.lines, strict=True)
        }
        parity = parity_record(expected, actual)
        assert parity["compared"] == len(bound) and not parity["mismatches"], parity
    assert [line.section for line in sides.lines] == ["thesis", "strengths", "strengths",
                                                      "weaknesses", "weaknesses"]  # fmt: skip
    assert [line.label for line in sides.lines] == [
        "Thesis",
        "Liquidity",
        "Reporting",
        "Disclosure",
        "Maturities",
    ]
    assert all(run.kind == "pen" for line in findings.lines for run in line.runs)


def test_the_binding_map_places_the_registers_on_the_rails() -> None:
    destinations = {e.fact_coord.table_id: e.block_id for e in CP2.entries}
    assert destinations == {
        KEY_FINDINGS: "key-findings",
        THESIS: "strengths-weaknesses",
        STRENGTHS: "strengths-weaknesses",
        WEAKNESSES: "strengths-weaknesses",
        "T2.1": "evidence",
        "T2.7": "evidence",
        "T2.10": "evidence",
        "T2.11": "evidence",
        CP1_REFERENCES: "evidence",
        "T2.12": "limitations",
    }
    sections = {e.fact_coord.table_id: e.section for e in CP2.entries if e.section}
    assert sections == {THESIS: "thesis", STRENGTHS: "strengths", WEAKNESSES: "weaknesses"}
    assert all(e.cell_slot.startswith("cp2-") for e in CP2.entries)
    assert CP2.module_id == MODULE_ID


# --- method text and the r14 coverage map -------------------------------------------------------


def test_the_method_text_names_the_r14_tables_and_states_no_figure() -> None:
    brief = files("deploy_vii").joinpath("methods", "cp2.md").read_text(encoding="utf-8")
    assert len(brief.splitlines()) < 90
    for table_id in REQUIRED_TABLES:
        assert f"`{table_id}`" in brief
    for anchor in (
        "decision 0005",
        "SKILL.md",
        "Reader question",
        "cp1a_refs",
        "Prohibited",
        "disclosure",
        "readiness judgment of CP-2",
    ):
        assert anchor in brief
    # The only digits outside labels are the r14 table ids, the decision number it records and
    # the contract and CONTEXT key names (identifiers, never figures).
    keys = {"cp1a_refs", "cp1a_rows", "cp1_facts", "cp1a_signals"}
    assert {f.strip("`") for f in bare_figures(brief)} <= {*REQUIRED_TABLES, "0005", *keys}


def test_the_required_tables_are_the_coverage_maps_cp2_ids() -> None:
    coverage = json.loads(Path("docs/methodology/r14-coverage.json").read_text(encoding="utf-8"))
    entry = next(m for m in coverage["modules"] if m["module_id"] == MODULE_ID)
    assert sorted(REQUIRED_TABLES) == sorted(entry["artifact_contract"]["required_table_ids"])
    # Ruling 1: CP-MODEL is no CP-2 input in M8, so its conditional table is never composed.
    assert entry["artifact_contract"]["conditional_table_ids"] == [
        "cp2.cp_model_strengths_weaknesses"
    ]


# --- edges ----------------------------------------------------------------------------------------


def test_a_submission_built_around_validation_reports_shape_issues() -> None:
    bogus = synthesis().assessment.model_copy(update={"confidence": "Certain"})
    found = issues_of(synthesis(assessment=bogus))
    assert any(i.startswith("assessment.confidence: Input should be") for i in found)
    with pytest.raises(ValueError, match=r"assessment\.confidence"):
        credit_synthesis(pack_fixture(), synthesis(assessment=bogus), upstream_of(pack_fixture()))


def test_a_figure_free_synthesis_carries_no_cp1_facts() -> None:
    pack = pack_fixture()
    base = synthesis()
    plain = synthesis(
        assessment=base.assessment.model_copy(update={"rationale": "Disclosure is thin."}),
        strengths=(base.strengths[1],),
        key_findings=(base.key_findings[1],),
    )
    report = credit_synthesis(pack, plain, upstream_of(pack))
    assert CP1_REFERENCES not in {t.table_id for t in report.tables}
    assert cp2_module(report, (), 0).facts == report.facts


def test_cp1a_copies_of_cp1_facts_are_not_citable_rows() -> None:
    pack = pack_fixture()
    submission = submission_fixture(pack)
    translation = submission.credit_translations[0].model_copy(
        update={"evidence": f"Liquidity was {LIQUIDITY}."}
    )
    cited = submission.model_copy(update={"credit_translations": (translation,)})
    head_ = cp1a_module(business_context(pack, cited, (cp1_fact(pack),)), (), 0)
    assert CP1_REFERENCES in {t.table_id for t in head_.tables}
    assert not any(ref.startswith(CP1_REFERENCES) for ref in cp1a_catalogue(head_))
    up = upstream_of(pack, cp1a=head_.model_copy(update={"status": "restricted"}))
    finding = Finding(text="Thin.", cp1a_refs=(f"{CP1_REFERENCES}.ref01",))
    assert f"key_findings[0].cp1a_refs: unknown CP-1A row {CP1_REFERENCES}.ref01" in (
        validate_credit_synthesis(pack, synthesis(key_findings=(finding,)), up)
    )


def test_the_bound_input_status_not_the_module_decides_a_blocked_cp1a() -> None:
    """Decision 0007: blocked is read from the structured input status. A blocked input whose
    module still carries registers (the journal never stores one) offers no row and no gap."""
    pack = pack_fixture()
    head_ = cp1a_head(pack, gaps=(critical(),))
    cp0, cp1 = cp0_head(pack), cp1_head(pack)
    bound = tuple(
        item.model_copy(update={"status": "blocked"}) if item.input_id == "CP-1A" else item
        for item in bound_inputs(pack, cp0, cp1, head_)
    )
    up = Upstream(bound=bound, current=bound, cp1=cp1, cp1a=head_, inherited=())
    assert up.catalogue == {} and up.signals == ()
    found = validate_credit_synthesis(pack, synthesis(), up)
    assert "key_findings[1].cp1a_refs: unknown CP-1A row credit_translation.r01" in found
    assert not any(i.startswith("gaps: restate") for i in found)


def test_an_attempt_without_its_required_inputs_fails_closed(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    with pytest.raises(ValueError, match="binds no CP-1 input"):
        cp2_upstream(store, ticket.model_copy(update={"inputs": ticket.inputs[:1]}))


def test_a_retained_output_trusted_validation_does_not_reproduce_is_refused(
    tmp_path: Path,
) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    payload = synthesis().model_dump_json()
    store.submit_step(
        ticket.ticket_id,
        MODULE_ID,
        (STEP_ID,),
        STEP_ID,
        payload,
        lambda _pack, _current: StepValidation(output="not the composed report"),
    )
    with pytest.raises(ValueError, match="differs from trusted validation"):
        submit_cp2_step(store, ticket.ticket_id, STEP_ID, payload)
    assert not any(h.module_id == MODULE_ID for h in store.read().heads)
