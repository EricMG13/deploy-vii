"""Synthetic narrative protocol checks; semantics require separate qualification."""

import pytest

from deploy_vii.narrative import (
    DimensionCoverage,
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
    validate_canonical_narrative,
    validate_narrative_review,
)
from tests.product.test_canonical_gaps import case
from tests.product.test_financials import book
from tests.product.test_source_context import event_case
from tests.product.test_statements import line


def draft(inputs: NarrativeInputs) -> NarrativeReview:
    return NarrativeReview(
        inputs_sha256=inputs.content_hash(),
        funding=FundingAssessment(
            status="unassessed",
            reviewed_statement_ids=(),
            material_statement_ids=(),
            rationale=(ProsePart(text="Funding classification has not been reviewed"),),
        ),
    )


def finding(inputs: NarrativeInputs, evidence_id: str | None = None) -> Finding:
    evidence_id = evidence_id or next(r.evidence_id for r in inputs.catalogue if r.kind == "kpi")
    return Finding(
        finding_id="liquidity",
        dimension="liquidity",
        title="Liquidity requires evidence review",
        evidence=(EvidencePart(evidence_id=evidence_id),),
        risk_mechanic=(
            IssuerPart(),
            ProsePart(text=" faces refinancing sensitivity if available liquidity contracts"),
        ),
        credit_implication=(
            ProsePart(text="Retain the source limitations before drawing a liquidity conclusion"),
        ),
    )


def populated(inputs: NarrativeInputs, value: Finding | None = None) -> NarrativeReview:
    value = value or finding(inputs)
    return draft(inputs).model_copy(
        update={
            "findings": (value,),
            "coverage": (
                DimensionCoverage(
                    dimension=value.dimension,
                    status="addressed",
                    finding_ids=(value.finding_id,),
                    rationale=(ProsePart(text="The finding covers the cited scope"),),
                ),
            ),
        }
    )


def test_catalogue_preserves_actual_register_rows_and_immutable_input_identity() -> None:
    args = case()
    before = tuple(a.model_dump_json() for a in args)
    inputs = narrative_inputs(*args)
    assert inputs.scope == "financial_synthesis"
    assert len({r.evidence_id for r in inputs.catalogue}) == len(inputs.catalogue)
    assert inputs.ledger.kpis is not None
    entry = next(r for r in inputs.catalogue if r.kind == "kpi")
    row = next(k for k in inputs.ledger.kpis.kpis if k.calculation_id == entry.reference)
    assert entry.record_json == row.model_dump_json() and entry.record_sha256 == row.content_hash()
    assert entry.artifact_sha256 == inputs.ledger.kpis.content_hash()
    assert tuple(a.model_dump_json() for a in args) == before
    review = populated(inputs)
    report = canonical_narrative(*args, review)
    assert report.review == review
    assert report.analytical_qualification == "unrun"
    assert validate_canonical_narrative(*args, review, report) == ()


def test_empty_review_retains_every_input_gap_and_explicit_unassessed_dimensions() -> None:
    args = case()
    inputs = narrative_inputs(*args)
    report = canonical_narrative(*args, draft(inputs))
    assert report.gaps[: len(inputs.ledger.gaps)] == inputs.ledger.gaps
    assert {g.reference for g in report.gaps if g.origin == "narrative"} >= {
        "leverage",
        "coverage",
        "cash_flow_quality",
        "liquidity",
        "data_quality",
        "definition_risks",
        "key_gaps",
        "funding-liabilities",
    }
    assert report.status != "candidate"


@pytest.mark.parametrize("text", ["Debt rose 12%", "More than \uff12 times", "Ratio ½", "   "])
def test_model_prose_cannot_introduce_numeric_literals_or_blank_reasoning(text: str) -> None:
    with pytest.raises(ValueError):
        ProsePart(text=text)


@pytest.mark.parametrize(
    "mode",
    [
        "stale",
        "unknown",
        "duplicate",
        "issuer",
        "evidence",
        "coverage",
        "contradiction",
        "unlocated_na",
    ],
)
def test_invalid_review_and_coverage_are_rejected(mode: str) -> None:
    inputs = narrative_inputs(*case())
    review = populated(inputs)
    value = review.findings[0]
    if mode == "stale":
        review = review.model_copy(update={"inputs_sha256": "0" * 64})
    elif mode == "unknown":
        value = value.model_copy(update={"evidence": (EvidencePart(evidence_id="unknown"),)})
    elif mode == "duplicate":
        review = review.model_copy(update={"findings": (value, value)})
    elif mode == "issuer":
        value = value.model_copy(update={"risk_mechanic": (ProsePart(text="Unbound issuer"),)})
    elif mode == "evidence":
        value = value.model_copy(update={"evidence": (ProsePart(text="Unsupported claim"),)})
    elif mode == "coverage":
        review = review.model_copy(update={"coverage": (review.coverage[0], review.coverage[0])})
    elif mode == "contradiction":
        review = review.model_copy(
            update={"coverage": (review.coverage[0].model_copy(update={"status": "unassessed"}),)}
        )
    else:
        review = review.model_copy(
            update={
                "findings": (),
                "coverage": (
                    DimensionCoverage(
                        dimension="liquidity",
                        status="not_applicable",
                        finding_ids=(),
                        rationale=(ProsePart(text="Not applicable"),),
                    ),
                ),
            }
        )
    if mode in {"unknown", "issuer", "evidence"}:
        review = review.model_copy(update={"findings": (value,)})
    assert validate_narrative_review(inputs, review)


def test_no_kpi_gate_allows_only_data_quality_synthesis() -> None:
    value = book()
    value = value.model_copy(
        update={
            "addback_disclosure": value.addback_disclosure.model_copy(update={"status": "partial"})
        }
    )
    args = case(value)
    inputs = narrative_inputs(*args)
    assert inputs.scope == "data_quality_only"
    ref = next(r.evidence_id for r in inputs.catalogue if r.kind == "gap")
    value_finding = finding(inputs, ref)
    assert validate_narrative_review(inputs, populated(inputs, value_finding))
    value_finding = value_finding.model_copy(update={"dimension": "data_quality"})
    report = canonical_narrative(*args, populated(inputs, value_finding))
    assert any(g.reference == "financial-synthesis" for g in report.gaps)


def test_subsequent_event_requires_its_own_evidence_linked_story() -> None:
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
    event_id = next(r.evidence_id for r in inputs.catalogue if r.kind == "subsequent_event")
    report = canonical_narrative(*args, draft(inputs))
    assert event_id in report.required_story_ids
    assert any(g.reference == event_id and g.severity == "BLOCK" for g in report.gaps)
    review = populated(inputs, finding(inputs, event_id))
    review = review.model_copy(
        update={"stories": (StoryCoverage(evidence_id=event_id, finding_ids=("liquidity",)),)}
    )
    report = canonical_narrative(*args, review)
    assert not any(g.origin == "narrative" and g.reference == event_id for g in report.gaps)
    wrong = review.model_copy(update={"findings": (finding(inputs),)})
    assert validate_narrative_review(inputs, wrong)


def test_material_funding_is_scoped_to_prior_balance_sheet_rows_and_requires_story() -> None:
    value = book().model_copy(
        update={
            "statement_lines": (
                line("deposits", "other:customer_deposits", "20", 1, statement="BS"),
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
    funding = FundingAssessment(
        status="material_items",
        reviewed_statement_ids=(bs,),
        material_statement_ids=(bs,),
        rationale=(ProsePart(text="Prior balance sheet evidence needs funding analysis"),),
    )
    review = draft(inputs).model_copy(update={"funding": funding})
    report = canonical_narrative(*args, review)
    assert bs in report.required_story_ids
    assert any(g.reference == bs and g.severity == "BLOCK" for g in report.gaps)
    wrong = funding.model_copy(
        update={"reviewed_statement_ids": (), "material_statement_ids": ("unknown",)}
    )
    assert validate_narrative_review(inputs, review.model_copy(update={"funding": wrong}))


def test_tampering_and_substitution_are_detected_by_external_recomputation() -> None:
    args = case()
    inputs = narrative_inputs(*args)
    review = populated(inputs)
    report = canonical_narrative(*args, review)
    for changes in (
        {"gaps": ()},
        {"status": "candidate"},
        {"required_story_ids": ("fake",)},
        {"schema_version": "old"},
    ):
        assert validate_canonical_narrative(*args, review, report.model_copy(update=changes))
    other = review.model_copy(update={"limitations": ("Additional limitation",)})
    assert validate_canonical_narrative(*args, review, canonical_narrative(*args, other))


def test_reference_tokens_alone_do_not_satisfy_risk_or_credit_reasoning() -> None:
    inputs = narrative_inputs(*case())
    value = finding(inputs).model_copy(update={"risk_mechanic": (IssuerPart(),)})
    assert validate_narrative_review(inputs, populated(inputs, value))


@pytest.mark.parametrize(
    "item", ["cash_and_equivalents", "trade_payables", "total_debt", "total_liabilities"]
)
def test_standard_assets_payables_and_debt_cannot_be_relabelled_operating_float(item: str) -> None:
    value = book().model_copy(
        update={"statement_lines": (line("given", item, "20", 1, statement="BS"),)}
    )
    inputs = narrative_inputs(*case(value))
    row = next(
        r.evidence_id
        for r in inputs.catalogue
        if r.kind == "statement_BS" and '"line_id":"given"' in r.record_json
    )
    funding = FundingAssessment(
        status="material_items",
        reviewed_statement_ids=(row,),
        material_statement_ids=(row,),
        rationale=(ProsePart(text="Claimed material float"),),
    )
    assert validate_narrative_review(inputs, draft(inputs).model_copy(update={"funding": funding}))


def test_catalogue_and_scope_cannot_be_substituted_even_with_a_matching_review_hash() -> None:
    inputs = narrative_inputs(*case())
    for changes in (
        {"scope": "data_quality_only"},
        {"catalogue": ()},
        {
            "catalogue": (
                inputs.catalogue[0].model_copy(update={"record_json": "invented"}),
                *inputs.catalogue[1:],
            )
        },
    ):
        changed = inputs.model_copy(update=changes)
        assert validate_narrative_review(changed, draft(changed))


def test_multifigure_event_requires_named_story_and_cannot_be_covered_by_unknown_finding() -> None:
    from deploy_vii.canonical_audit import EventFigure, MultiFigureEvent

    pack, context, financial, definition, binding = case()
    positions = financial.books[0].accounts[:2]
    event = MultiFigureEvent(
        event_id="event",
        description="Distinct financial roles",
        figures=tuple(
            EventFigure(observation_id=r.value.observation_id, statement_role=r.metric_id)
            for r in positions
        ),
        explanation="Separate accounting meanings",
        citations=positions[0].value.citations,
        downstream_impact="Keep the roles separate",
    )
    definition = definition.model_copy(update={"events": (event,)})
    args = pack, context, financial, definition, binding
    inputs = narrative_inputs(*args)
    identity = next(r.evidence_id for r in inputs.catalogue if r.kind == "multi_figure_event")
    assert identity in canonical_narrative(*args, draft(inputs)).required_story_ids
    review = draft(inputs).model_copy(
        update={"stories": (StoryCoverage(evidence_id=identity, finding_ids=("unknown",)),)}
    )
    assert validate_narrative_review(inputs, review)


def test_partial_funding_scan_cannot_hide_unreviewed_located_balance_sheet_rows() -> None:
    value = book().model_copy(
        update={
            "statement_lines": (
                line("deposits", "other:customer_deposits", "20", 1, statement="BS"),
                line("deferred", "other:deferred_revenue", "30", 2, statement="BS"),
            )
        }
    )
    args = case(value)
    inputs = narrative_inputs(*args)
    first = next(
        r.evidence_id
        for r in inputs.catalogue
        if r.kind == "statement_BS" and '"line_id":"deposits"' in r.record_json
    )
    funding = FundingAssessment(
        status="no_material_items",
        reviewed_statement_ids=(first,),
        material_statement_ids=(),
        rationale=(ProsePart(text="Reviewed this scoped line"),),
    )
    report = canonical_narrative(*args, draft(inputs).model_copy(update={"funding": funding}))
    assert any(
        g.origin == "narrative" and g.reference == "funding-review-coverage" for g in report.gaps
    )


def test_copied_numeric_prose_and_nested_contracts_do_not_bypass_validation() -> None:
    inputs = narrative_inputs(*case())
    review = populated(inputs)
    value = review.findings[0]
    bad = value.model_copy(update={"title": "Debt exceeds 9999"})
    assert validate_narrative_review(inputs, review.model_copy(update={"findings": (bad,)}))
    nested = review.model_copy(update={"findings": (value.model_dump(),)})
    with pytest.warns(UserWarning):
        assert validate_narrative_review(inputs, nested) == ()
