"""Synthetic CP-1 audit registers: no live analytical acceptance is implied."""

from decimal import Decimal, localcontext

import pytest

from deploy_vii.canonical_audit import (
    DefinitionAssessment,
    DefinitionReview,
    EventFigure,
    MultiFigureEvent,
    canonical_audit,
    validate_canonical_audit,
    validate_definition_review,
)
from deploy_vii.financial_contracts import (
    AccountObservation,
    FinancialBook,
    FinancialReview,
    Observation,
)
from deploy_vii.financial_validation import records
from deploy_vii.preparation import PreparedPack
from tests.product.test_financials import book, conflict, freeze, observed
from tests.product.test_statements import line


def case(
    value: FinancialBook | None = None,
) -> tuple[PreparedPack, FinancialReview, DefinitionReview]:
    pack, review = freeze(value or book())
    definition = DefinitionReview(
        financial_review_sha256=review.content_hash(), book_id="consolidated"
    )
    return pack, review, definition


def assessment(review: FinancialReview, **changes: object) -> DefinitionAssessment:
    value = review.books[0].accounts[0].value
    fields = dict(
        assessment_id="revenue-definition",
        metric="Revenue",
        canonical_definition="Revenue for the declared entity perimeter",
        issuer_definition="Consolidated revenue",
        status="aligned",
        observation_ids=(value.observation_id,),
        citations=value.citations,
        materiality="No difference in the reviewed definition",
        downstream_impact="Revenue comparability",
        recommendation="Retain declared perimeter",
    )
    return DefinitionAssessment.model_validate(fields | changes)


def test_empty_review_never_means_definitions_align_and_retains_every_observation() -> None:
    pack, review, definition = case()
    report = canonical_audit(pack, review, definition)
    original = tuple(records(review.books[0], Observation))
    assert tuple(p.observation for p in report.source_positions) == original
    assert set(report.unassessed_observation_ids) == {v.observation_id for v in original} - {
        "loan.Q2.floor"
    }
    assert not any(r.status == "aligned" for r in report.definitions)
    assert {g.reference for g in report.gaps if g.origin == "definition_coverage"} == set(
        report.unassessed_observation_ids
    )
    assert len({g.gap_id for g in report.gaps}) == len(report.gaps)
    assert validate_canonical_audit(pack, review, definition, report) == ()


def test_alignment_is_scoped_and_cannot_override_debt_basis_difference() -> None:
    pack, review, definition = case()
    definition = definition.model_copy(update={"assessments": (assessment(review),)})
    report = canonical_audit(pack, review, definition)
    assert "Q1.revenue" not in report.unassessed_observation_ids
    assert "Q2.revenue" in report.unassessed_observation_ids
    aligned, debt = report.definitions
    assert aligned.status == "aligned" and aligned.period_ids == ("Q1",)
    assert debt.kind == "debt_basis" and debt.roles == ("carrying_value", "gross_principal")
    positions = {p.observation.observation_id: p for p in report.source_positions}
    assert [positions[oid].observation.amount for oid in debt.observation_ids] == [100, 105]
    assert all(positions[oid].currency == "USD" for oid in debt.observation_ids)
    assert any(g.reference == debt.row_id for g in report.gaps)


@pytest.mark.parametrize("amount", ["100", None])
def test_no_invented_debt_difference_when_equal_or_missing(amount: str | None) -> None:
    value = book()
    facility = value.facilities[0]
    value = value.model_copy(
        update={
            "facilities": (
                facility.model_copy(update={"principal": observed("loan.Q2.principal", amount)}),
            )
        }
    )
    report = canonical_audit(*case(value))
    assert not any(r.kind == "debt_basis" for r in report.definitions)
    if amount is None:
        assert any(
            g.origin == "observation" and g.reference == "loan.Q2.principal" for g in report.gaps
        )


def test_conflict_alternatives_remain_unsettled_and_cannot_be_declared_aligned() -> None:
    value = book()
    row = value.accounts[0]
    value = value.model_copy(
        update={
            "accounts": (
                row.model_copy(update={"value": conflict(row.value.observation_id)}),
                *value.accounts[1:],
            )
        }
    )
    pack, review, definition = case(value)
    report = canonical_audit(pack, review, definition)
    conflict_row = next(r for r in report.definitions if r.kind == "value_conflict")
    assert conflict_row.citations
    source = next(
        p.observation
        for p in report.source_positions
        if p.observation.observation_id == "Q1.revenue"
    )
    assert source.amount is None and [a.amount for a in source.alternatives] == [10, 11]
    assert any(g.reference == "Q1.revenue" and g.severity == "BLOCK" for g in report.gaps)
    row = assessment(review, citations=source.alternatives[0].citations)
    with pytest.raises(ValueError, match="cannot be declared aligned"):
        canonical_audit(pack, review, definition.model_copy(update={"assessments": (row,)}))
    row = row.model_copy(update={"status": "conflict"})
    assert canonical_audit(pack, review, definition.model_copy(update={"assessments": (row,)}))


def test_event_preserves_all_figures_and_statement_roles_without_summing() -> None:
    pack, review, definition = case()
    observations = review.books[0].accounts
    event = MultiFigureEvent(
        event_id="event-1",
        description="Synthetic event, two statement roles",
        figures=(
            EventFigure(
                observation_id=observations[0].value.observation_id, statement_role="P&L charge"
            ),
            EventFigure(
                observation_id=observations[1].value.observation_id, statement_role="Cash paid"
            ),
        ),
        explanation="Distinct recognition and cash bases; do not combine",
        citations=observations[0].value.citations,
        downstream_impact="Retain both roles in earnings and cash analysis",
    )
    definition = definition.model_copy(update={"events": (event,)})
    report = canonical_audit(pack, review, definition)
    row = next(r for r in report.definitions if r.kind == "multi_figure_event")
    assert row.roles == ("P&L charge", "Cash paid")
    assert row.observation_ids == tuple(f.observation_id for f in event.figures)
    assert row.period_ids == ("Q1",)
    assert set(row.observation_ids) <= set(report.unassessed_observation_ids)
    for figures in (
        (event.figures[0], event.figures[0]),
        (event.figures[0], EventFigure(observation_id="unknown", statement_role="Other")),
    ):
        bad = definition.model_copy(
            update={"events": (event.model_copy(update={"figures": figures}),)}
        )
        assert validate_definition_review(pack, review, bad)
    assert validate_definition_review(
        pack, review, definition.model_copy(update={"events": (event, event)})
    )


@pytest.mark.parametrize(
    "change", ["hash", "book", "unknown", "duplicate", "overlap", "citation", "schema"]
)
def test_definition_input_rejects_stale_or_invalid_scope(change: str) -> None:
    pack, review, definition = case()
    row = assessment(review)
    definition = definition.model_copy(update={"assessments": (row,)})
    if change == "hash":
        definition = definition.model_copy(update={"financial_review_sha256": "0" * 64})
    elif change == "book":
        definition = definition.model_copy(update={"book_id": "another-book"})
    elif change == "unknown":
        definition = definition.model_copy(
            update={"assessments": (row.model_copy(update={"observation_ids": ("unknown",)}),)}
        )
    elif change == "duplicate":
        definition = definition.model_copy(update={"assessments": (row, row)})
    elif change == "overlap":
        definition = definition.model_copy(
            update={"assessments": (row, row.model_copy(update={"assessment_id": "second"}))}
        )
    elif change == "citation":
        definition = definition.model_copy(
            update={
                "assessments": (
                    row.model_copy(
                        update={
                            "citations": (
                                row.citations[0].model_copy(update={"quote": "invented"}),
                            )
                        }
                    ),
                )
            }
        )
    else:
        definition = definition.model_copy(update={"schema_version": "definition-review/0"})
    assert validate_definition_review(pack, review, definition)
    with pytest.raises(ValueError):
        canonical_audit(pack, review, definition)


def test_source_sign_changes_are_recorded_once_with_original_values_and_dimensions() -> None:
    value = book()
    value = value.model_copy(
        update={
            "accounts": tuple(
                r.model_copy(update={"value": observed(r.value.observation_id, "30")})
                if r.metric_id == "cogs"
                else r
                for r in value.accounts
            ),
            "statement_lines": (line("expense", "capex_total", "8", 1),),
        }
    )
    pack, review, definition = case(value)
    report = canonical_audit(pack, review, definition)
    assert {(n.before, n.after) for n in report.normalizations} == {
        (Decimal(30), Decimal(-30)),
        (Decimal(8), Decimal(-8)),
    }
    assert len(report.normalizations) == 3
    assert len({n.normalization_id for n in report.normalizations}) == 3
    assert all(n.citations for n in report.normalizations)
    assert all(n.before > 0 and n.after < 0 for n in report.normalizations)
    with localcontext() as context:
        context.prec = 1
        assert canonical_audit(pack, review, definition) == report


def test_gap_ledger_keeps_statement_omissions_reconciliation_disclosures_and_limitations() -> None:
    value = book().model_copy(update={"limitations": ("Synthetic basis limitation",)})
    report = canonical_audit(*case(value))
    assert {g.origin for g in report.gaps} >= {
        "statement",
        "reconciliation",
        "disclosure",
        "limitation",
        "observation",
        "definition_coverage",
    }
    assert {g.reference for g in report.gaps if g.origin == "reconciliation"} == {
        r.check_id for r in report.reconciliation.checks if r.status != "PASS"
    }
    assert any(g.description == "Synthetic basis limitation" for g in report.gaps)


def test_tampered_register_or_embedded_assessment_cannot_validate_against_expected_input() -> None:
    pack, review, definition = case()
    report = canonical_audit(pack, review, definition)
    assert validate_canonical_audit(
        pack, review, definition, report.model_copy(update={"gaps": ()})
    )
    assert validate_canonical_audit(
        pack, review, definition, report.model_copy(update={"schema_version": "wrong"})
    )
    changed = definition.model_copy(update={"assessments": (assessment(review),)})
    alternate = canonical_audit(pack, review, changed)
    assert validate_canonical_audit(pack, review, definition, alternate)
    bad_review = review.model_copy(update={"pack_sha256": "0" * 64})
    assert validate_definition_review(pack, bad_review, definition)


def test_rate_and_monetary_dimensions_are_not_conflated() -> None:
    value = book()
    value = value.model_copy(
        update={
            "accounts": (
                *value.accounts,
                AccountObservation(
                    metric_id="effective_tax_rate",
                    period_id="Q2",
                    value=observed("tax-rate", "0.2"),
                ),
            )
        }
    )
    report = canonical_audit(*case(value))
    positions = {p.observation.observation_id: p for p in report.source_positions}
    assert positions["tax-rate"].currency is None
    assert positions["tax-rate"].unit == "decimal_fraction"
    assert positions["loan.Q2.fixed"].unit == "decimal_percent"
    assert positions["loan.Q2.spread"].unit == "basis_points"
    assert positions["loan.Q2.spread"].currency is None
    assert positions["loan.Q2.carrying"].unit == "MILLIONS"


def test_explicit_source_sign_evidence_is_carried_into_compact_account_normalization() -> None:
    value = book()
    source = line("cash-flow", "cfo_ncfo", "60", 1).model_copy(
        update={
            "sign_convention": "outflow_magnitude",
            "sign_citations": value.periods[0].citations,
        }
    )
    value = value.model_copy(update={"statement_lines": (source,)})
    pack, review, definition = case(value)
    original = review.model_dump_json()
    report = canonical_audit(pack, review, definition)
    compact = next(n for n in report.normalizations if n.observation_id == "Q2.cfo_ncfo")
    assert (compact.before, compact.after) == (60, -60)
    assert set(review.books[0].statement_lines[0].sign_citations) <= set(compact.citations)
    assert review.model_dump_json() == original
    for gap in report.gaps:
        if gap.origin in {"observation", "definition_coverage", "facility_term"}:
            assert gap.period_ids
        if gap.origin in {"facility_term", "disclosure"}:
            assert gap.citations


def test_cross_book_references_cannot_be_adopted_even_with_valid_pack_citations() -> None:
    pack, review, definition = case()
    other = FinancialBook.model_validate_json(
        review.books[0].model_dump_json().replace('"observation_id":"', '"observation_id":"other:')
    ).model_copy(update={"book_id": "other"})
    review = review.model_copy(update={"books": (*review.books, other)})
    definition = definition.model_copy(
        update={
            "financial_review_sha256": review.content_hash(),
            "assessments": (assessment(review, observation_ids=("other:Q1.revenue",)),),
        }
    )
    assert any(
        "unknown assessment observation" in issue
        for issue in validate_definition_review(pack, review, definition)
    )


def test_invalid_nested_contract_does_not_reach_register_traversal() -> None:
    pack, review, definition = case()
    malformed = review.model_copy(update={"books": ({"book_id": "incomplete"},)})
    with pytest.warns(UserWarning):
        assert validate_definition_review(pack, malformed, definition)


@pytest.mark.parametrize(
    ("rate_type", "excluded"),
    [("FIXED", "spread_bps"), ("FLOATING", "fixed_rate"), ("NOT_STATED", "floor_bps")],
)
def test_inapplicable_null_facility_terms_are_not_missing_data_gaps(
    rate_type: str, excluded: str
) -> None:
    value = book()
    facility = value.facilities[0].model_copy(update={"rate_type": rate_type})
    value = value.model_copy(update={"facilities": (facility,)})
    pack, review, definition = case(value)
    report = canonical_audit(pack, review, definition)
    exempt_id = getattr(facility, excluded).observation_id
    assert exempt_id not in report.unassessed_observation_ids
    assert not any(g.reference == exempt_id for g in report.gaps)
    assert any(g.reference == facility.annual_amortisation.observation_id for g in report.gaps)
    assert any(p.observation.observation_id == exempt_id for p in report.source_positions)


@pytest.mark.parametrize("field", ["floor_bps", "fixed_rate", "spread_bps"])
def test_optional_term_exception_never_hides_conflicting_evidence(field: str) -> None:
    value = book()
    facility = value.facilities[0]
    observation = getattr(facility, field)
    facility = facility.model_copy(
        update={
            "rate_type": "FIXED" if field == "spread_bps" else "FLOATING",
            field: conflict(observation.observation_id),
        }
    )
    value = value.model_copy(update={"facilities": (facility,)})
    report = canonical_audit(*case(value))
    assert observation.observation_id in report.unassessed_observation_ids
    assert any(
        g.reference == observation.observation_id and g.severity == "BLOCK" for g in report.gaps
    )
