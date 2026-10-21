"""CP-1 QA scope projection; synthetic registers do not qualify analytical judgments."""

from decimal import Decimal
from typing import Any

import pytest

from deploy_vii.canonical_tables import CanonicalTables, canonical_tables
from deploy_vii.cp1_quality import (
    REQUIRED_TABLES,
    CP1QualityReport,
    canonical_quality,
    cp1_quality_inputs,
    validate_canonical_quality,
)
from deploy_vii.downstream_readiness import DownstreamReview, downstream_inputs
from deploy_vii.narrative import (
    DimensionCoverage,
    EvidencePart,
    Finding,
    FundingAssessment,
    IssuerPart,
    NarrativeReview,
    ProsePart,
    StatementCell,
    StoryCoverage,
    narrative_inputs,
)
from deploy_vii.quality import (
    ClaimAssessment,
    EvidenceLineage,
    Lineage,
    QualityInputs,
    QualityReview,
    assess_quality,
)
from tests.product.test_canonical_gaps import case
from tests.product.test_canonical_tables import fixture
from tests.product.test_narrative import draft, populated
from tests.product.test_quality import fraction, restate_r14
from tests.product.test_source_context import event_case

type Args = tuple[Any, ...]

MANDATORY = ("T4.1", "T4.2", "T4.4", "T4.5", "T4.6", "T4.10")


def with_narrative(base: Args, narrative: NarrativeReview) -> Args:
    """Rebuild the consumer-readiness binding around a different narrative."""
    upstream = base[:5]
    inputs = downstream_inputs(*upstream, narrative, ("CP-2A", "CP-4A"))
    review = DownstreamReview(inputs_sha256=inputs.content_hash())
    return (*upstream, narrative, inputs.requested_consumers, review)


def kpi_ids(args: Args) -> list[str]:
    return [r.evidence_id for r in narrative_inputs(*args[:5]).catalogue if r.kind == "kpi"]


def located_statement_ids(args: Args) -> tuple[str, ...]:
    return tuple(
        r.evidence_id
        for r in narrative_inputs(*args[:5]).catalogue
        if r.kind == "statement_BS" and StatementCell.model_validate_json(r.record_json).line_id
    )


def analysed(base: Args) -> NarrativeReview:
    """Two findings with repeated evidence across passages, one n/a and one unassessed dimension."""
    inputs = narrative_inputs(*base[:5])
    k = kpi_ids(base)
    assert len(k) >= 5
    liquidity = Finding(
        finding_id="liquidity",
        dimension="liquidity",
        title="Liquidity requires evidence review",
        evidence=(EvidencePart(evidence_id=k[0]), EvidencePart(evidence_id=k[1])),
        risk_mechanic=(
            IssuerPart(),
            ProsePart(text=" is exposed if available liquidity contracts"),
            EvidencePart(evidence_id=k[1]),
            EvidencePart(evidence_id=k[2]),
        ),
        credit_implication=(
            ProsePart(text="Retain the source limitations"),
            EvidencePart(evidence_id=k[0]),
            EvidencePart(evidence_id=k[3]),
        ),
    )
    leverage = Finding(
        finding_id="leverage",
        dimension="leverage",
        title="Leverage requires evidence review",
        evidence=(EvidencePart(evidence_id=k[4]),),
        risk_mechanic=(IssuerPart(), ProsePart(text=" depends on the debt basis")),
        credit_implication=(ProsePart(text="Retain the definition limitations"),),
    )
    coverage = (
        DimensionCoverage(
            dimension="liquidity",
            status="addressed",
            finding_ids=("liquidity",),
            rationale=(ProsePart(text="Covered by the finding"),),
        ),
        DimensionCoverage(
            dimension="leverage",
            status="addressed",
            finding_ids=("leverage",),
            rationale=(ProsePart(text="Covered by the finding"),),
        ),
        DimensionCoverage(
            dimension="coverage",
            status="not_applicable",
            finding_ids=(),
            rationale=(ProsePart(text="Not applicable given"), EvidencePart(evidence_id=k[0])),
        ),
        DimensionCoverage(
            dimension="cash_flow_quality",
            status="unassessed",
            finding_ids=(),
            rationale=(ProsePart(text="Not yet reviewed"),),
        ),
    )
    funding = FundingAssessment(
        status="no_material_items",
        reviewed_statement_ids=located_statement_ids(base),
        material_statement_ids=(),
        rationale=(ProsePart(text="Reviewed located balance-sheet rows"),),
    )
    return draft(inputs).model_copy(
        update={"findings": (liquidity, leverage), "coverage": coverage, "funding": funding}
    )


def lineage_review(inputs: QualityInputs) -> QualityReview:
    """Every candidate claim is material; evidence lineage alternates deterministically."""
    classes: tuple[Lineage, ...] = ("Calculated", "Directly Sourced", "Assumption-Based")
    return QualityReview(
        inputs_sha256=inputs.content_hash(),
        claims=tuple(
            ClaimAssessment(
                claim_id=claim.claim_id,
                material=True,
                rationale="Synthetic materiality judgment",
                evidence=tuple(
                    EvidenceLineage(
                        evidence_id=evidence_id,
                        lineage_class=classes[i % 3],
                        rationale="Synthetic lineage judgment",
                    )
                    for i, evidence_id in enumerate(claim.evidence_ids)
                ),
            )
            for claim in inputs.claims
        ),
    )


def altered(
    registers: CanonicalTables,
    *,
    context_status: str | None = None,
    narrative_status: str | None = None,
) -> CanonicalTables:
    """Shape-valid copy with one nested producer status changed (not authenticated)."""
    downstream = registers.downstream
    narrative = downstream.inputs.narrative
    ledger = narrative.inputs.ledger
    if context_status:
        context = ledger.context.model_copy(update={"status": context_status})
        ledger = ledger.model_copy(update={"context": context})
    narrative = narrative.model_copy(
        update={"inputs": narrative.inputs.model_copy(update={"ledger": ledger})}
    )
    if narrative_status:
        narrative = narrative.model_copy(update={"status": narrative_status})
    inputs = downstream.inputs.model_copy(update={"narrative": narrative})
    return registers.model_copy(
        update={"downstream": downstream.model_copy(update={"inputs": inputs})}
    )


def without_rows(registers: CanonicalTables, table_id: str, *, drop_table: bool) -> CanonicalTables:
    module = registers.module
    tables = tuple(
        t.model_copy(update={"rows": ()}) if t.table_id == table_id else t
        for t in module.tables
        if not (drop_table and t.table_id == table_id)
    )
    facts = tuple(f for f in module.facts if f.table_id != table_id)
    return registers.model_copy(
        update={"module": module.model_copy(update={"tables": tables, "facts": facts})}
    )


def flags(inputs: QualityInputs) -> dict[str, bool]:
    return {c.field_id: c.present for c in inputs.coverage}


@pytest.fixture(scope="module")
def base() -> Args:
    return fixture()


@pytest.fixture(scope="module")
def registers(base: Args) -> CanonicalTables:
    return canonical_tables(*base)


@pytest.fixture(scope="module")
def inputs(registers: CanonicalTables) -> QualityInputs:
    return cp1_quality_inputs(registers)


@pytest.fixture(scope="module")
def reviewed(base: Args) -> tuple[Args, CanonicalTables, QualityInputs]:
    args = with_narrative(base, analysed(base))
    registers = canonical_tables(*args)
    return args, registers, cp1_quality_inputs(registers)


def test_projection_requires_the_eighteen_registers_and_every_required_cell(
    registers: CanonicalTables, inputs: QualityInputs
) -> None:
    assert REQUIRED_TABLES == tuple(f"T4.{i}" for i in range(1, 20) if i != 7)
    assert len(REQUIRED_TABLES) == 18
    seen = flags(inputs)
    assert [f for f in seen if f.startswith("table:")] == [f"table:{t}" for t in REQUIRED_TABLES]
    assert all(seen[f"table:{t}"] for t in REQUIRED_TABLES)
    assert registers.module.status == "candidate"
    required = [f for f in registers.module.facts if f.table_id in REQUIRED_TABLES]
    cells = [c for c in inputs.coverage if c.field_id.startswith("qa-cell:")]
    assert len(cells) == len(required) and len({c.field_id for c in cells}) == len(cells)
    expected = [f.status in {"known", "not_applicable"} for f in required]
    assert [c.present for c in cells] == expected
    assert any(expected) and not all(expected)  # known/n-a and missing/other cells both occur
    assert {f.table_id for f in registers.module.facts} - set(REQUIRED_TABLES)  # contextual only


def test_cell_rationales_name_coordinates_status_and_limitations(
    registers: CanonicalTables, inputs: QualityInputs
) -> None:
    required = [f for f in registers.module.facts if f.table_id in REQUIRED_TABLES]
    cells = [c for c in inputs.coverage if c.field_id.startswith("qa-cell:")]
    for fact, cell in zip(required[:200], cells[:200], strict=True):
        head = f"{fact.table_id}/{fact.row_id}/{fact.field}: {fact.status}"
        assert cell.rationale.startswith(head)
    limited = next(i for i, f in enumerate(required) if f.limitation and f.status == "missing")
    assert cells[limited].rationale.endswith(f"; {required[limited].limitation}")
    plain = next(i for i, f in enumerate(required) if not f.limitation)
    assert cells[plain].rationale == (
        f"{required[plain].table_id}/{required[plain].row_id}/{required[plain].field}: "
        f"{required[plain].status}"
    )


@pytest.mark.parametrize("drop_table", [False, True], ids=["empty-rows", "absent-table"])
@pytest.mark.parametrize("table_id", ["T4.1", "T4.2", "T4.4", "T4.5", "T4.6"])
def test_empty_mandatory_registers_cannot_improve_coverage_by_losing_their_cells(
    registers: CanonicalTables, table_id: str, drop_table: bool
) -> None:
    before = cp1_quality_inputs(registers)
    after = cp1_quality_inputs(without_rows(registers, table_id, drop_table=drop_table))
    assert flags(before)[f"populated:{table_id}"] is True
    seen = flags(after)
    assert seen[f"populated:{table_id}"] is False
    assert seen[f"table:{table_id}"] is (not drop_table)
    assert sum(seen.values()) < sum(flags(before).values())
    assert len(after.coverage) < len(before.coverage)  # cells vanished, yet no score gain
    review = QualityReview(inputs_sha256=after.content_hash(), claims=())
    lost = assess_quality(after, review).confidence
    assert lost.fields_present < sum(flags(before).values())
    assert lost.qa_status != "Passed"


def test_an_empty_kpi_register_is_counted_absent_not_dropped(base: Args) -> None:
    value = base[2].books[0]
    partial = value.model_copy(
        update={
            "addback_disclosure": value.addback_disclosure.model_copy(update={"status": "partial"})
        }
    )
    args = fixture(partial)
    registers = canonical_tables(*args)
    seen = flags(cp1_quality_inputs(registers))
    assert seen["table:T4.10"] is True and seen["populated:T4.10"] is False
    assert all(seen[f"populated:{t}"] for t in MANDATORY if t != "T4.10")


def test_unassessed_narrative_leaves_every_analytical_scope_field_absent(
    inputs: QualityInputs,
) -> None:
    seen = flags(inputs)
    dimensions = [f for f in seen if f.startswith("dimension:")]
    assert dimensions == [
        f"dimension:{d}"
        for d in (
            "leverage",
            "coverage",
            "cash_flow_quality",
            "liquidity",
            "data_quality",
            "definition_risks",
            "key_gaps",
        )
    ]
    assert not any(seen[d] for d in dimensions)
    assert seen["funding-assessment"] is False and seen["analytical-findings"] is False
    assert inputs.claims == ()
    assert seen["canonical-handoff"] is False and seen["source-gate"] is True


def test_assessed_dimensions_funding_and_findings_count_present_but_handoff_never(
    reviewed: tuple[Args, CanonicalTables, QualityInputs],
) -> None:
    _, _, scope = reviewed
    seen = flags(scope)
    assert [seen[f"dimension:{d}"] for d in ("leverage", "coverage", "cash_flow_quality")] == [
        True,
        True,  # an evidence-backed not_applicable assessment is explicit
        False,  # an explicit "unassessed" is not
    ]
    assert seen["dimension:liquidity"] is True
    assert not any(seen[f"dimension:{d}"] for d in ("data_quality", "definition_risks", "key_gaps"))
    assert seen["funding-assessment"] and seen["analytical-findings"]
    assert seen["canonical-handoff"] is False
    handoff = next(c for c in scope.coverage if c.field_id == "canonical-handoff")
    assert "pending" in handoff.rationale


def test_required_stories_are_present_only_when_linked_to_a_validated_finding() -> None:
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
    upstream = (pack, context, financial, definition, binding)
    ledger = narrative_inputs(*upstream)
    event = next(r.evidence_id for r in ledger.catalogue if r.kind == "subsequent_event")
    kpi = next(r.evidence_id for r in ledger.catalogue if r.kind == "kpi")
    finding = Finding(
        finding_id="liquidity",
        dimension="liquidity",
        title="Subsequent event requires review",
        evidence=(EvidencePart(evidence_id=event), EvidencePart(evidence_id=kpi)),
        risk_mechanic=(IssuerPart(), ProsePart(text=" faces event sensitivity")),
        credit_implication=(ProsePart(text="Retain the event limitations"),),
    )
    unlinked = with_narrative(upstream, draft(ledger))
    linked_review = populated(ledger, finding).model_copy(
        update={"stories": (StoryCoverage(evidence_id=event, finding_ids=("liquidity",)),)}
    )
    linked = with_narrative(upstream, linked_review)
    gap_registers = canonical_tables(*unlinked)
    story_registers = canonical_tables(*linked)
    assert gap_registers.downstream.inputs.narrative.required_story_ids == (event,)
    assert story_registers.downstream.inputs.narrative.required_story_ids == (event,)
    stories = [
        c for c in cp1_quality_inputs(gap_registers).coverage if c.field_id.startswith("qa-story:")
    ]
    assert [c.present for c in stories] == [False]
    assert "linked to a validated finding" in stories[0].rationale
    scope = cp1_quality_inputs(story_registers)
    assert [c.present for c in scope.coverage if c.field_id.startswith("qa-story:")] == [True]
    # A genuine partial source context gates at partial; a blocked narrative blocks the Module.
    assert scope.source_gate == "partial" and flags(scope)["source-gate"] is False
    assert story_registers.downstream.inputs.narrative.status == "blocked"
    assert scope.module_status == "blocked"
    assert [c.claim_id for c in scope.claims] == ["liquidity"]


def test_claims_are_one_per_finding_with_distinct_evidence_ids_across_passages(
    reviewed: tuple[Args, CanonicalTables, QualityInputs],
) -> None:
    args, registers, scope = reviewed
    k = kpi_ids(args)
    assert [c.claim_id for c in scope.claims] == ["liquidity", "leverage"]
    # First occurrence order across evidence, risk mechanic, credit implication; prose/issuer
    # parts and the repeats of k[1] and k[0] contribute nothing.
    assert [c.evidence_ids for c in scope.claims] == [(k[0], k[1], k[2], k[3]), (k[4],)]
    for claim in scope.claims:
        assert len(claim.evidence_ids) == len(set(claim.evidence_ids))
        assert set(claim.evidence_ids) <= set(scope.references)
    review = registers.downstream.inputs.narrative.review
    assert len(scope.claims) == len(review.findings)


def test_references_cover_catalogue_fields_and_gaps_once(
    registers: CanonicalTables, inputs: QualityInputs
) -> None:
    narrative = registers.downstream.inputs.narrative
    expected = [
        *(r.evidence_id for r in narrative.inputs.catalogue),
        *(c.field_id for c in inputs.coverage),
        *(g.gap_id for g in narrative.gaps),
    ]
    assert list(inputs.references) == list(dict.fromkeys(expected))
    assert narrative.gaps  # gap ids are carried for inherited-finding references


@pytest.mark.parametrize(
    "status,gate,present",
    [("candidate", "pass", True), ("restricted", "partial", False), ("blocked", "fail", False)],
)
def test_source_context_status_maps_to_the_source_gate(
    registers: CanonicalTables, status: str, gate: str, present: bool
) -> None:
    scope = cp1_quality_inputs(altered(registers, context_status=status))
    assert scope.source_gate == gate
    assert flags(scope)["source-gate"] is present
    cell = next(c for c in scope.coverage if c.field_id == "source-gate")
    assert cell.rationale == f"Source context status: {status}"


@pytest.mark.parametrize(
    "status,module",
    [("blocked", "blocked"), ("restricted", "restricted"), ("candidate", "restricted")],
)
def test_module_status_is_blocked_or_restricted_never_complete_before_handoff(
    registers: CanonicalTables, status: str, module: str
) -> None:
    scope = cp1_quality_inputs(altered(registers, narrative_status=status))
    assert scope.module_status == module


def test_even_complete_coverage_and_a_passing_gate_cannot_pass_before_handoff(
    registers: CanonicalTables, inputs: QualityInputs
) -> None:
    covered = QualityInputs.model_validate_json(
        inputs.model_copy(
            update={
                "coverage": tuple(c.model_copy(update={"present": True}) for c in inputs.coverage)
            }
        ).model_dump_json()
    )
    assert covered.source_gate == "pass" and all(c.present for c in covered.coverage)
    score = assess_quality(
        covered, QualityReview(inputs_sha256=covered.content_hash(), claims=())
    ).confidence
    assert (score.qa_status, score.confidence_score) == ("Restricted", 40)  # 0.4*100, no claims
    blocked = cp1_quality_inputs(altered(registers, narrative_status="blocked"))
    blocked = QualityInputs.model_validate_json(
        blocked.model_copy(
            update={
                "coverage": tuple(c.model_copy(update={"present": True}) for c in blocked.coverage)
            }
        ).model_dump_json()
    )
    capped = assess_quality(blocked, QualityReview(inputs_sha256=blocked.content_hash(), claims=()))
    assert capped.confidence.qa_status == "Blocked" and capped.confidence.confidence_score <= 39


@pytest.fixture(scope="module")
def genuine(
    reviewed: tuple[Args, CanonicalTables, QualityInputs],
) -> tuple[Args, QualityReview, CP1QualityReport]:
    args, _, scope = reviewed
    review = lineage_review(scope)
    return args, review, canonical_quality(*args, review)


def test_canonical_quality_equals_an_external_recomputation(
    reviewed: tuple[Args, CanonicalTables, QualityInputs],
    genuine: tuple[Args, QualityReview, CP1QualityReport],
) -> None:
    _, registers, scope = reviewed
    _, review, report = genuine
    assert (report.schema_version, report.scope) == ("cp1-quality/1", "pre_handoff")
    assert report.registers == registers and report.inputs == scope
    assert report.quality == assess_quality(scope, review)
    assert report.quality.inputs_sha256 == report.inputs.content_hash()
    assert report.quality.review_sha256 == review.content_hash()
    assert report.inputs.artifact_sha256 == report.registers.content_hash()
    assert report.quality.analytical_qualification == "unrun"
    score = report.quality.confidence
    # Independent restatement from the supplied judgments and the producer-owned slots.
    lineages = [[e.lineage_class for e in c.evidence] for c in review.claims]
    raw, rounded, band, status = restate_r14(
        [(c.material, ls) for c, ls in zip(review.claims, lineages, strict=True)],
        sum(c.present for c in scope.coverage),
        len(scope.coverage),
        scope.source_gate,
        scope.module_status,
        [],
    )
    assert fraction(score.raw_score) == raw
    assert (score.confidence_score, score.confidence_band, score.qa_status) == (
        rounded,
        band,
        status,
    )
    assert status == "Restricted" and score.material_claims == 2
    assert (score.fields_present, score.fields_total) == (
        sum(c.present for c in scope.coverage),
        len(scope.coverage),
    )
    copy = CP1QualityReport.model_validate_json(report.model_dump_json())
    assert copy == report and copy.content_hash() == report.content_hash()
    assert any(isinstance(f.amount, Decimal) for f in copy.registers.module.facts)


def tampered_registers(report: CP1QualityReport) -> CanonicalTables:
    module = report.registers.module
    fact = next(f for f in module.facts if f.table_id in REQUIRED_TABLES and f.status == "known")
    altered_fact = fact.model_copy(update={"limitation": "Tampered after recomputation"})
    facts = tuple(altered_fact if f.fact_id == fact.fact_id else f for f in module.facts)
    return report.registers.model_copy(
        update={"module": module.model_copy(update={"facts": facts})}
    )


def test_validation_accepts_the_genuine_report_and_rejects_each_substitution(
    genuine: tuple[Args, QualityReview, CP1QualityReport],
) -> None:
    args, review, report = genuine
    assert validate_canonical_quality(*args, review, report) == ()
    differs = ("CP-1 QA report differs from trusted external recomputation",)
    score = report.quality.confidence.model_copy(update={"confidence_score": 100})
    bad_score = report.model_copy(
        update={"quality": report.quality.model_copy(update={"confidence": score})}
    )
    assert validate_canonical_quality(*args, review, bad_score) == differs
    bad_registers = report.model_copy(update={"registers": tampered_registers(report)})
    assert validate_canonical_quality(*args, review, bad_registers) == differs
    flipped = report.inputs.coverage[0].model_copy(update={"present": False})
    bad_inputs = report.model_copy(
        update={
            "inputs": report.inputs.model_copy(
                update={"coverage": (flipped, *report.inputs.coverage[1:])}
            )
        }
    )
    assert validate_canonical_quality(*args, review, bad_inputs) == differs


def test_validation_reports_a_review_bound_to_other_inputs_and_invalid_reports(
    genuine: tuple[Args, QualityReview, CP1QualityReport],
) -> None:
    args, review, report = genuine
    stale = review.model_copy(update={"inputs_sha256": "0" * 64})
    issues = validate_canonical_quality(*args, stale, report)
    assert len(issues) == 1 and issues[0].startswith("Invalid CP-1 QA report:")
    assert "does not bind current inputs" in issues[0]
    old = report.model_copy(update={"schema_version": "old"})
    issues = validate_canonical_quality(*args, review, old)
    assert len(issues) == 1 and issues[0].startswith("Invalid CP-1 QA report:")
    with pytest.raises(ValueError, match="does not bind current inputs"):
        canonical_quality(*args, stale)


def test_stale_external_context_and_substituted_narrative_are_rejected(
    base: Args, genuine: tuple[Args, QualityReview, CP1QualityReport]
) -> None:
    args, review, report = genuine
    stale = list(args)
    stale[1] = stale[1].model_copy(update={"pack_sha256": "0" * 64})
    issues = validate_canonical_quality(*stale, review, report)
    assert len(issues) == 1 and issues[0].startswith("Invalid CP-1 QA report:")
    # Recomputing against the unreviewed narrative: the supplied review no longer binds.
    issues = validate_canonical_quality(*base, review, report)
    assert len(issues) == 1 and issues[0].startswith("Invalid CP-1 QA report:")


@pytest.mark.parametrize(
    "status,limitations,module",
    [
        ("blocked", (), "blocked"),
        ("blocked", ("Own finding",), "blocked"),
        ("restricted", (), "restricted"),
        ("candidate", ("Own finding",), "restricted"),
        ("candidate", (), "complete"),
    ],
)
def test_module_status_derives_from_own_findings_only(
    registers: CanonicalTables, status: str, limitations: tuple[str, ...], module: str
) -> None:
    changed = altered(registers, narrative_status=status)
    downstream = changed.downstream
    narrative = downstream.inputs.narrative.model_copy(update={"limitations": limitations})
    inputs = downstream.inputs.model_copy(update={"narrative": narrative})
    changed = changed.model_copy(
        update={"downstream": downstream.model_copy(update={"inputs": inputs})}
    )
    assert cp1_quality_inputs(changed).module_status == module
