"""Synthetic readiness mechanics; analyst sufficiency is not qualified by these tests."""

from decimal import Decimal

import pytest

from deploy_vii.canonical_audit import DefinitionReview
from deploy_vii.context_binding import FinancialContextBinding
from deploy_vii.downstream_readiness import (
    ConsumerAssessment,
    DownstreamInputs,
    DownstreamReview,
    GapAssessment,
    RequirementAssessment,
    canonical_downstream_readiness,
    downstream_inputs,
    validate_downstream_report,
    validate_downstream_review,
)
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.narrative import NarrativeReview, narrative_inputs
from deploy_vii.preparation import PreparedPack
from deploy_vii.source_context import SourceContextReview
from tests.product.test_canonical_gaps import case
from tests.product.test_model_readiness import ready_case
from tests.product.test_narrative import draft
from tests.product.test_reconciliation import accounts

type Base = tuple[
    tuple[
        PreparedPack,
        SourceContextReview,
        FinancialReview,
        DefinitionReview,
        FinancialContextBinding,
    ],
    NarrativeReview,
]


@pytest.fixture(scope="module")
def base() -> Base:
    args = case(ready_case())
    narrative = draft(narrative_inputs(*args))
    return args, narrative


def evidence(inputs: DownstreamInputs, kind: str, key: str | None = None) -> str:
    return next(
        r.evidence_id
        for r in inputs.narrative.inputs.catalogue
        if r.kind == kind and (key is None or f'"key":"{key}"' in r.record_json)
    )


def assessed(inputs: DownstreamInputs, *, relevant: bool = True) -> DownstreamReview:
    result = []
    for request in inputs.consumers:
        requirements = []
        for key in request.requirements:
            ref = (
                evidence(inputs, "kpi", "fcf")
                if key == "cash_flow_metrics"
                else evidence(inputs, "kpi", "liquidity")
                if key == "liquidity_data"
                else evidence(inputs, "entity")
            )
            requirements.append(
                RequirementAssessment(
                    requirement=key,
                    status="sufficient",
                    evidence_ids=(ref,),
                    rationale="Synthetic scoped sufficiency judgment for protocol testing",
                )
            )
        result.append(
            ConsumerAssessment(
                entry=request.entry,
                requirements=tuple(requirements),
                gaps=(
                    GapAssessment(
                        gap_ids=tuple(g.gap_id for g in inputs.narrative.gaps),
                        relevance="relevant" if relevant else "not_relevant",
                        evidence_ids=(evidence(inputs, "entity"),),
                        rationale="Synthetic relevance judgment over the named scope",
                    ),
                ),
            )
        )
    return DownstreamReview(inputs_sha256=inputs.content_hash(), consumers=tuple(result))


def test_every_requested_entry_and_alias_is_retained_and_model_is_always_present(
    base: Base,
) -> None:
    args, narrative = base
    entries = (
        "CP-1B",
        "CP-1C",
        "CP-2",
        "CP-2A",
        "CP-2D",
        "CP-3",
        "CP-3C",
        "CP-4",
        "CP-4A",
        "CP-5",
        "CP-5A",
        "CP-2B",
        "CP-6",
        "CP-MODEL",
    )
    inputs = downstream_inputs(*args, narrative, entries)
    review = DownstreamReview(inputs_sha256=inputs.content_hash())
    report = canonical_downstream_readiness(*args, narrative, entries, review)
    assert tuple(r.entry for r in report.consumers) == entries[:-1]
    assert all(r.status == "not_ready" for r in report.consumers)
    assert all(r.unassessed_requirements and r.unassessed_gap_ids for r in report.consumers)
    assert report.model.entry == "CP-MODEL" and report.model.status == "ready"
    policies = {r.entry: r for r in inputs.consumers}
    assert policies["CP-4A"].requirements == ("covenant_compliance",)
    assert policies["CP-5A"].requirements == ("full_data_set",)
    assert policies["CP-2B"].requirements == ("cash_flow_metrics", "liquidity_data")
    assert policies["CP-6"].policy == "consumer_specific_review"
    assert report.analytical_qualification == "unrun"
    assert report.inputs.narrative.gaps == inputs.narrative.gaps


def test_empty_request_still_assesses_model_and_recomputes_against_external_inputs(
    base: Base,
) -> None:
    args, narrative = base
    inputs = downstream_inputs(*args, narrative, ())
    review = DownstreamReview(inputs_sha256=inputs.content_hash())
    before = tuple(a.model_dump_json() for a in (*args, narrative))
    report = canonical_downstream_readiness(*args, narrative, (), review)
    assert not report.consumers and report.model.status == "ready"
    assert validate_downstream_report(*args, narrative, (), review, report) == ()
    assert tuple(a.model_dump_json() for a in (*args, narrative)) == before


@pytest.mark.parametrize("entries", [("CP-2A", "CP-2A"), ("unknown",), ("CP-0",), ("CP-1",)])
def test_invalid_or_upstream_requests_fail(base: Base, entries: tuple[str, ...]) -> None:
    args, narrative = base
    with pytest.raises(ValueError):
        downstream_inputs(*args, narrative, entries)


@pytest.mark.parametrize("relevant", [True, False])
def test_relevance_changes_consumer_status_without_deleting_any_gap(
    base: Base, relevant: bool
) -> None:
    args, narrative = base
    inputs = downstream_inputs(*args, narrative, ("CP-2A", "CP-5"))
    review = assessed(inputs, relevant=relevant)
    report = canonical_downstream_readiness(*args, narrative, inputs.requested_consumers, review)
    assert all(
        r.status == ("ready_with_limitations" if relevant else "ready") for r in report.consumers
    )
    assert all(not r.unassessed_gap_ids for r in report.consumers)
    assert (
        all(
            r.relevant_gap_ids == tuple(g.gap_id for g in inputs.narrative.gaps)
            for r in report.consumers
        )
        if relevant
        else all(not r.relevant_gap_ids for r in report.consumers)
    )
    assert report.inputs.narrative.gaps == inputs.narrative.gaps
    assert report.analytical_qualification == "unrun"


@pytest.mark.parametrize(
    "mode",
    [
        "stale",
        "consumer",
        "duplicate",
        "requirement",
        "evidence",
        "kind",
        "gap",
        "overlap",
        "exclusion",
        "action",
        "numeric",
    ],
)
def test_invalid_review_cannot_change_readiness(base: Base, mode: str) -> None:
    args, narrative = base
    inputs = downstream_inputs(*args, narrative, ("CP-2A",))
    review = assessed(inputs)
    consumer = review.consumers[0]
    requirement = consumer.requirements[0]
    scope = consumer.gaps[0]
    if mode == "stale":
        review = review.model_copy(update={"inputs_sha256": "0" * 64})
    elif mode == "consumer":
        consumer = consumer.model_copy(update={"entry": "CP-5"})
    elif mode == "duplicate":
        review = review.model_copy(update={"consumers": (consumer, consumer)})
    elif mode == "requirement":
        consumer = consumer.model_copy(update={"requirements": (requirement, requirement)})
    elif mode in {"evidence", "kind", "action", "numeric"}:
        changes = (
            {"evidence_ids": ("unknown",)}
            if mode == "evidence"
            else {"evidence_ids": (evidence(inputs, "entity"),)}
            if mode == "kind"
            else {"status": "limited", "actions": ()}
            if mode == "action"
            else {"rationale": "Invented amount 999"}
        )
        consumer = consumer.model_copy(
            update={"requirements": (requirement.model_copy(update=changes),)}
        )
    else:
        consumer = consumer.model_copy(
            update={
                "gaps": (
                    scope,
                    scope,
                )
                if mode == "overlap"
                else (
                    scope.model_copy(update={"gap_ids": ("unknown",)})
                    if mode == "gap"
                    else scope.model_copy(update={"relevance": "not_relevant", "evidence_ids": ()}),
                )
            }
        )
    if mode not in {"stale", "duplicate"}:
        review = review.model_copy(update={"consumers": (consumer,)})
    assert validate_downstream_review(inputs, review)
    with pytest.raises(ValueError):
        canonical_downstream_readiness(*args, narrative, inputs.requested_consumers, review)


def test_missing_or_limited_dependencies_and_partial_gap_scope_remain_visible(base: Base) -> None:
    args, narrative = base
    inputs = downstream_inputs(*args, narrative, ("CP-2A",))
    review = assessed(inputs, relevant=False)
    consumer = review.consumers[0]
    requirement = consumer.requirements[0]
    for state in ("missing", "limited"):
        changed = consumer.model_copy(
            update={
                "requirements": (
                    requirement.model_copy(
                        update={"status": state, "actions": ("Obtain the missing evidence",)}
                    ),
                    consumer.requirements[1],
                )
            }
        )
        report = canonical_downstream_readiness(
            *args,
            narrative,
            inputs.requested_consumers,
            review.model_copy(update={"consumers": (changed,)}),
        )
        assert report.consumers[0].status == (
            "not_ready" if state == "missing" else "ready_with_limitations"
        )
        assert "Obtain the missing evidence" in report.consumers[0].actions
    incomplete = consumer.model_copy(
        update={
            "gaps": (consumer.gaps[0].model_copy(update={"gap_ids": consumer.gaps[0].gap_ids[1:]}),)
        }
    )
    report = canonical_downstream_readiness(
        *args,
        narrative,
        inputs.requested_consumers,
        review.model_copy(update={"consumers": (incomplete,)}),
    )
    assert report.consumers[0].status == "not_ready"
    assert report.consumers[0].unassessed_gap_ids == (consumer.gaps[0].gap_ids[0],)


def test_source_binding_block_cannot_be_excluded_or_hidden_by_historical_model_ready(
    base: Base,
) -> None:
    args, _ = base
    args = (*args[:-1], args[-1].model_copy(update={"financial_review_sha256": "0" * 64}))
    narrative = draft(narrative_inputs(*args))
    inputs = downstream_inputs(*args, narrative, ("CP-5",))
    assert inputs.model.readiness.status == "ready"
    report = canonical_downstream_readiness(*args, narrative, ("CP-5",), assessed(inputs))
    assert report.model.status == "blocked" and report.model.blocking_gap_ids
    assert report.consumers[0].status == "not_ready" and report.consumers[0].blocking_gap_ids
    assert validate_downstream_review(inputs, assessed(inputs, relevant=False))


def test_relevant_financial_block_is_retained_and_scope_exclusion_never_waives_model_checks() -> (
    None
):
    value = accounts(ready_case(), "Q1", cfo_ncfo="61")
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                row.model_copy(
                    update={"value": row.value.model_copy(update={"amount": Decimal("61")})}
                )
                if row.period_id == "Q1" and row.item_id == "cfo_ncfo"
                else row
                for row in value.statement_lines
            )
        }
    )
    args = case(value)
    narrative = draft(narrative_inputs(*args))
    inputs = downstream_inputs(*args, narrative, ("CP-5",))
    assert any(g.severity == "BLOCK" for g in inputs.narrative.gaps)
    report = canonical_downstream_readiness(*args, narrative, ("CP-5",), assessed(inputs))
    assert report.consumers[0].status == "not_ready" and report.model.status == "blocked"
    # A synthetic database-input scope can retain failed checks as structured data.
    # This declaration does not qualify its semantic relevance or repair the source.
    other = canonical_downstream_readiness(
        *args, narrative, ("CP-5",), assessed(inputs, relevant=False)
    )
    assert other.consumers[0].status == "ready"
    assert other.model.status == "blocked"
    assert other.inputs.narrative.gaps == report.inputs.narrative.gaps


def test_external_requests_reviews_quarter_scope_and_report_content_cannot_be_substituted(
    base: Base,
) -> None:
    args, narrative = base
    inputs = downstream_inputs(*args, narrative, ("CP-2A",))
    review = assessed(inputs)
    report = canonical_downstream_readiness(*args, narrative, ("CP-2A",), review)
    for changes in (
        {"consumers": ()},
        {"model": report.model.model_copy(update={"status": "not_applicable"})},
        {
            "inputs": inputs.model_copy(
                update={"narrative": inputs.narrative.model_copy(update={"gaps": ()})}
            )
        },
    ):
        assert validate_downstream_report(
            *args, narrative, ("CP-2A",), review, report.model_copy(update=changes)
        )
    assert validate_downstream_report(*args, narrative, ("CP-5",), review, report)
    assert validate_downstream_report(*args, narrative, ("CP-2A",), review, report, quarter_ids=())
    assert validate_downstream_report(
        *args, narrative, ("CP-2A",), review.model_copy(update={"consumers": ()}), report
    )


def test_copied_requirements_and_prior_catalogue_cannot_bypass_validation(base: Base) -> None:
    args, narrative = base
    inputs = downstream_inputs(*args, narrative, ("CP-2A",))
    other = inputs.model_copy(update={"consumers": ()})
    assert validate_downstream_review(other, DownstreamReview(inputs_sha256=other.content_hash()))
    prior = inputs.narrative.inputs.model_copy(update={"catalogue": ()})
    other = inputs.model_copy(
        update={"narrative": inputs.narrative.model_copy(update={"inputs": prior})}
    )
    assert validate_downstream_review(other, DownstreamReview(inputs_sha256=other.content_hash()))


def test_partial_quarter_selection_never_authorizes_export(base: Base) -> None:
    args, narrative = base
    all_inputs = downstream_inputs(*args, narrative, ())
    quarter = all_inputs.model.readiness.selected_quarters[:3]
    inputs = downstream_inputs(*args, narrative, (), quarter_ids=quarter)
    report = canonical_downstream_readiness(
        *args,
        narrative,
        (),
        DownstreamReview(inputs_sha256=inputs.content_hash()),
        quarter_ids=quarter,
    )
    assert report.model.status == "partial"
    assert report.inputs.model.readiness.status == "blocked"


def test_limited_requirement_cannot_use_only_an_unavailable_financial_value() -> None:
    args = case(accounts(ready_case(), "Q1", capex_and_intangible_investment=None))
    narrative = draft(narrative_inputs(*args))
    inputs = downstream_inputs(*args, narrative, ("CP-2A",))
    review = assessed(inputs)
    consumer = review.consumers[0]
    requirement = consumer.requirements[0].model_copy(
        update={
            "status": "limited",
            "actions": ("Obtain the missing source amount",),
        }
    )
    review = review.model_copy(
        update={
            "consumers": (
                consumer.model_copy(
                    update={"requirements": (requirement, consumer.requirements[1])}
                ),
            )
        }
    )
    assert validate_downstream_review(inputs, review)


def test_nested_serialized_financial_book_is_reconstructed_before_access(base: Base) -> None:
    args, narrative = base
    pack, context, financial, definition, binding = args
    copied = financial.model_copy(update={"books": tuple(b.model_dump() for b in financial.books)})
    with pytest.warns(UserWarning):
        inputs = downstream_inputs(pack, context, copied, definition, binding, narrative, ())
    assert inputs.financial_book == financial.books[0]


def test_one_available_kpi_cannot_establish_complete_dashboard_sufficiency(base: Base) -> None:
    args, narrative = base
    inputs = downstream_inputs(*args, narrative, ("CP-2",))
    requirement = RequirementAssessment(
        requirement="kpi_dashboard",
        status="sufficient",
        evidence_ids=(evidence(inputs, "kpi", "fcf"),),
        rationale="Synthetic dashboard sufficiency claim",
    )
    review = DownstreamReview(
        inputs_sha256=inputs.content_hash(),
        consumers=(ConsumerAssessment(entry="CP-2", requirements=(requirement,)),),
    )
    assert validate_downstream_review(inputs, review)
