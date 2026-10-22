"""Synthetic located context and extraction-scope boundary tests."""

from datetime import date
from decimal import Decimal

import pytest

from deploy_vii.context_binding import (
    BookEntityBinding,
    FinancialContextBinding,
    validate_financial_context,
)
from deploy_vii.contracts import Citation, Source
from deploy_vii.financial_contracts import (
    Alternative,
    FinancialBook,
    FinancialReview,
    Observation,
    ProFormaObservation,
)
from deploy_vii.financial_validation import records
from deploy_vii.preparation import PreparedPack
from deploy_vii.source_context import (
    EntityContext,
    ReportingScope,
    SourceContext,
    SourceContextReview,
    SubsequentEvent,
    source_context,
    validate_source_context,
    validate_source_context_report,
)
from tests.product.test_financials import _C, book, freeze, observed, period
from tests.product.test_live_submission import (
    GLM_76FC5C95_LIMITATION,
    GLM_F0391C45_LIMITATION,
    LUNA_F136B227_LIMITATION,
    paged_pack,
)


def case(
    value: FinancialBook | None = None,
) -> tuple[PreparedPack, SourceContextReview, FinancialReview, FinancialContextBinding]:
    pack, financial = freeze(value or book())
    pack = pack.model_copy(
        update={"sources": (pack.sources[0].model_copy(update={"extraction_status": "complete"}),)}
    )
    financial = financial.model_copy(update={"pack_sha256": pack.content_hash()})
    value = financial.books[0]
    citations = value.periods[0].citations
    entity = EntityContext(
        entity_id="issuer",
        name="Synthetic borrower group",
        entity_type="group",
        roles=("issuer", "borrower", "guarantor_group", "restricted_group"),
        fiscal_year_end="31 December",
        citations=citations,
    )
    scopes = tuple(
        ReportingScope(
            scope_id=p.period_id,
            entity_id=entity.entity_id,
            period_label=p.period_id,
            period_kind="historical_duration",
            start_date=p.start_date,
            end_date=p.end_date,
            currency=p.currency,
            unit=p.unit,
            entity_perimeter=p.entity_perimeter,
            accounting_basis=p.accounting_basis,
            citations=p.citations,
        )
        for p in value.periods
    )
    source = SourceContext(
        source_id="S1",
        classification="financial",
        document_type="Interim statements",
        published_on=date(2025, 7, 8),
        evidence_class="unaudited_without_auditor",
        evidence_rationale="Synthetic class supplied explicitly",
        analytical_use="Historical credit analysis",
        citations=citations,
        scopes=scopes,
        event_scan="no_events_identified",
        event_ids=(),
        event_scan_citations=citations,
        event_scan_explanation="No event identified in this synthetic reviewed scope",
    )
    review = SourceContextReview(
        pack_sha256=pack.content_hash(), entities=(entity,), sources=(source,)
    )
    binding = FinancialContextBinding(
        financial_review_sha256=financial.content_hash(),
        source_context_review_sha256=review.content_hash(),
        books=(BookEntityBinding(book_id=value.book_id, entity_id=entity.entity_id),),
    )
    return pack, review, financial, binding


def event_case() -> tuple[PreparedPack, SourceContextReview]:
    pack, review, _, _ = case()
    event = SubsequentEvent(
        event_id="refinancing",
        reporting_scope_id="Q2",
        event_date=date(2025, 7, 5),
        known_on=date(2025, 7, 6),
        status="completed",
        description="Synthetic refinancing",
        effect="Historical debt remains at the reporting date; evaluate later in pro forma",
        citations=review.sources[0].citations,
    )
    source = review.sources[0].model_copy(
        update={"event_scan": "events_identified", "event_ids": (event.event_id,)}
    )
    return pack, review.model_copy(update={"sources": (source,), "events": (event,)})


def test_complete_context_and_explicit_binding_are_recomputable_but_not_accepted() -> None:
    pack, review, financial, binding = case()
    before = (pack.model_dump_json(), review.model_dump_json(), financial.model_dump_json())
    assert validate_source_context(pack, review) == ()
    report = source_context(pack, review)
    assert report.status == "candidate" and not report.gaps
    assert report.sources[0].evidence_tier == "2b"
    assert report.entities[0].scope_ids == ("Q1", "Q2")
    assert report.context_review_sha256 == review.content_hash()
    assert validate_source_context_report(pack, review, report) == ()
    assert validate_financial_context(pack, review, financial, binding) == ()
    assert before == (pack.model_dump_json(), review.model_dump_json(), financial.model_dump_json())


@pytest.mark.parametrize(
    ("kind", "tier"),
    [
        ("audited_financial_statements", "1"),
        ("unaudited_with_auditor", "2a"),
        ("unaudited_without_auditor", "2b"),
        ("lender_sponsor", "2c"),
        ("rating", "2d"),
        ("internal", "3a"),
        ("external", "3b"),
    ],
)
def test_evidence_tier_comes_only_from_located_classification(kind: str, tier: str) -> None:
    pack, review, _, _ = case()
    source = review.sources[0].model_copy(update={"evidence_class": kind})
    report = source_context(pack, review.model_copy(update={"sources": (source,)}))
    assert report.sources[0].evidence_tier == tier


def test_filename_and_readability_never_supply_an_evidence_tier() -> None:
    pack, review, _, _ = case()
    pack = pack.model_copy(
        update={
            "sources": (pack.sources[0].model_copy(update={"name": "AUDITED_TIER_1_FINAL.pdf"}),)
        }
    )
    source = review.sources[0].model_copy(update={"evidence_class": None})
    review = review.model_copy(update={"pack_sha256": pack.content_hash(), "sources": (source,)})
    report = source_context(pack, review)
    assert report.status == "restricted" and report.sources[0].evidence_tier is None
    assert any("tier" in gap.description for gap in report.gaps)


def test_missing_source_retains_inventory_and_blocks_file_gate() -> None:
    pack, _, _, _ = case()
    missing = Source(
        source_id="S1",
        name="Missing filing",
        status="missing",
        limitation="Not supplied",
        extraction_status="blocked",
    )
    pack = pack.model_copy(update={"sources": (missing,)})
    source = SourceContext(
        source_id="S1",
        classification="unassessed",
        document_type=None,
        published_on=None,
        evidence_class=None,
        evidence_rationale="Unavailable",
        analytical_use="Unassessed",
        citations=(),
        event_scan_explanation="Unavailable source cannot be reviewed",
    )
    review = SourceContextReview(pack_sha256=pack.content_hash(), entities=(), sources=(source,))
    report = source_context(pack, review)
    assert report.status == "blocked" and report.sources[0].filename == "Missing filing"
    assert report.sources[0].source_sha256 is None
    assert any(g.reference == "file-gate" for g in report.gaps)
    bad = review.model_copy(
        update={"sources": (source.model_copy(update={"document_type": "Audited financials"}),)}
    )
    assert validate_source_context(pack, bad)


def test_subsequent_events_are_dated_and_excluded_from_history() -> None:
    pack, review = event_case()
    report = source_context(pack, review)
    assert report.status == "restricted"
    assert report.events == review.events
    assert report.events[0].historical_treatment == "excluded_from_reported_period"
    assert any(g.category == "event" and g.citations for g in report.gaps)
    future = review.events[0].model_copy(
        update={"status": "announced", "event_date": date(2025, 8, 1)}
    )
    assert validate_source_context(pack, review.model_copy(update={"events": (future,)})) == ()


@pytest.mark.parametrize(
    "mode",
    [
        "inside_period",
        "unknown_scope",
        "unknown_boundary",
        "future_knowledge",
        "future_completed",
        "early_completion",
        "late_publication",
        "unattached",
        "missing_event",
        "duplicate_event",
        "duplicate_reference",
        "scan_mismatch",
        "no_scan_citation",
    ],
)
def test_inconsistent_event_evidence_is_rejected(mode: str) -> None:
    pack, review = event_case()
    event, source = review.events[0], review.sources[0]
    if mode == "inside_period":
        event = event.model_copy(update={"event_date": date(2025, 6, 30)})
    elif mode == "unknown_scope":
        event = event.model_copy(update={"reporting_scope_id": "unknown"})
    elif mode == "unknown_boundary":
        source = source.model_copy(
            update={
                "scopes": (source.scopes[0], source.scopes[1].model_copy(update={"end_date": None}))
            }
        )
    elif mode == "future_knowledge":
        event = event.model_copy(update={"known_on": date(2025, 7, 11)})
    elif mode == "future_completed":
        event = event.model_copy(update={"event_date": date(2025, 7, 11)})
    elif mode == "early_completion":
        event = event.model_copy(update={"known_on": date(2025, 7, 4)})
    elif mode == "late_publication":
        source = source.model_copy(update={"published_on": date(2025, 7, 1)})
    elif mode == "unattached":
        source = source.model_copy(update={"event_scan": "no_events_identified", "event_ids": ()})
    elif mode == "missing_event":
        source = source.model_copy(update={"event_ids": ("unknown",)})
    elif mode == "duplicate_reference":
        source = source.model_copy(update={"event_ids": (event.event_id, event.event_id)})
    elif mode == "scan_mismatch":
        source = source.model_copy(update={"event_scan": "no_events_identified"})
    elif mode == "no_scan_citation":
        source = source.model_copy(update={"event_scan_citations": ()})
    review = review.model_copy(
        update={
            "sources": (source,),
            "events": (event, event) if mode == "duplicate_event" else (event,),
        }
    )
    assert validate_source_context(pack, review)
    with pytest.raises(ValueError):
        source_context(pack, review)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entity_id", "unknown"),
        ("start_date", date(2025, 4, 1)),
        ("period_kind", "period_end"),
        ("end_date", date(2025, 7, 11)),
        ("end_date", date(2025, 7, 9)),
    ],
)
def test_invalid_reporting_scope_is_rejected(field: str, value: object) -> None:
    pack, review, _, _ = case()
    source = review.sources[0]
    source = source.model_copy(
        update={"scopes": (source.scopes[0].model_copy(update={field: value}), *source.scopes[1:])}
    )
    assert validate_source_context(pack, review.model_copy(update={"sources": (source,)}))


def test_invalid_contracts_duplicate_identity_and_unlocated_assertions_are_rejected() -> None:
    pack, review, _, _ = case()
    source, entity = review.sources[0], review.entities[0]
    variants = [
        review.model_copy(update={"pack_sha256": "0" * 64}),
        review.model_copy(update={"schema_version": "old"}),
        review.model_copy(update={"sources": (source, source)}),
        review.model_copy(update={"sources": ()}),
        review.model_copy(update={"entities": (entity, entity)}),
    ]
    for edits in (
        {"scopes": (source.scopes[0], source.scopes[0])},
        {"published_on": date(2025, 7, 11)},
        {"citations": ()},
        {"citations": (source.citations[0].model_copy(update={"quote": "invented"}),)},
        {"citations": (source.citations[0].model_copy(update={"source_id": "unknown"}),)},
        {"classification": "unassessed"},
    ):
        variants.append(review.model_copy(update={"sources": (source.model_copy(update=edits),)}))
    for edits in ({"roles": ("issuer", "issuer")}, {"citations": ()}, {"name": None}):
        variants.append(review.model_copy(update={"entities": (entity.model_copy(update=edits),)}))
    for variant in variants:
        assert validate_source_context(pack, variant)


def test_unresolved_fields_and_basis_differences_are_retained_as_gaps() -> None:
    pack, review, _, _ = case()
    source, entity = review.sources[0], review.entities[0]
    scope = source.scopes[0].model_copy(
        update={"scope_id": "different", "currency": "EUR", "unit": None}
    )
    source = source.model_copy(
        update={
            "scopes": (*source.scopes, scope),
            "event_scan": "unassessed",
            "event_scan_citations": (),
            "published_on": None,
        }
    )
    entity = entity.model_copy(
        update={"fiscal_year_end": None, "limitations": ("Fiscal year end not known",)}
    )
    review = review.model_copy(
        update={
            "sources": (source,),
            "entities": (entity,),
            "limitations": ("Review incomplete", "Review incomplete"),
        }
    )
    report = source_context(pack, review)
    assert report.status == "restricted"
    assert any("Different source currency" in g.description for g in report.gaps)
    assert any("unit" in g.description for g in report.gaps)
    assert any(g.category == "event_scan" for g in report.gaps)
    assert len({g.gap_id for g in report.gaps}) == len(report.gaps)


@pytest.mark.parametrize(
    "mode",
    [
        "financial_hash",
        "context_hash",
        "duplicate_book",
        "unknown_book",
        "unknown_entity",
        "wrong_entity",
        "currency",
        "unit",
        "perimeter",
        "basis",
        "dates",
        "nonfinancial",
        "schema",
    ],
)
def test_financial_binding_rejects_stale_or_mixed_scope(mode: str) -> None:
    pack, context, financial, binding = case()
    row = binding.books[0]
    if mode == "financial_hash":
        binding = binding.model_copy(update={"financial_review_sha256": "0" * 64})
    elif mode == "context_hash":
        binding = binding.model_copy(update={"source_context_review_sha256": "0" * 64})
    elif mode == "duplicate_book":
        binding = binding.model_copy(update={"books": (row, row)})
    elif mode == "unknown_book":
        binding = binding.model_copy(
            update={"books": (row.model_copy(update={"book_id": "unknown"}),)}
        )
    elif mode == "unknown_entity":
        binding = binding.model_copy(
            update={"books": (row.model_copy(update={"entity_id": "unknown"}),)}
        )
    elif mode == "schema":
        binding = binding.model_copy(update={"schema_version": "old"})
    else:
        source = context.sources[0]
        edits = {
            "currency": {"currency": "EUR"},
            "unit": {"unit": "THOUSANDS"},
            "perimeter": {"entity_perimeter": "Other group"},
            "basis": {"accounting_basis": "IFRS"},
            "dates": {"start_date": date(2025, 1, 2)},
            "wrong_entity": {"entity_id": "other"},
        }
        if mode == "nonfinancial":
            source = source.model_copy(update={"classification": "nonfinancial"})
        else:
            source = source.model_copy(
                update={"scopes": tuple(s.model_copy(update=edits[mode]) for s in source.scopes)}
            )
        if mode == "wrong_entity":
            context = context.model_copy(
                update={
                    "entities": (
                        *context.entities,
                        context.entities[0].model_copy(update={"entity_id": "other"}),
                    )
                }
            )
        context = context.model_copy(update={"sources": (source,)})
        binding = binding.model_copy(
            update={"source_context_review_sha256": context.content_hash()}
        )
    assert validate_financial_context(pack, context, financial, binding)


def test_context_report_tampering_and_input_substitution_are_detected() -> None:
    pack, review, _, _ = case()
    report = source_context(pack, review)
    assert validate_source_context_report(pack, review, report.model_copy(update={"sources": ()}))
    assert validate_source_context_report(
        pack, review, report.model_copy(update={"schema_version": "old"})
    )
    changed = review.model_copy(update={"limitations": ("Additional limitation",)})
    assert validate_source_context_report(pack, review, source_context(pack, changed))


def test_valid_serialized_nested_inputs_are_normalized_before_binding_traversal() -> None:
    pack, context, financial, binding = case()
    financial = financial.model_copy(
        update={"books": tuple(b.model_dump(mode="python") for b in financial.books)}
    )
    context = context.model_copy(
        update={"sources": tuple(s.model_dump(mode="python") for s in context.sources)}
    )
    with pytest.warns(UserWarning):
        assert validate_financial_context(pack, context, financial, binding) == ()


def test_pro_forma_requires_matching_separate_event_context() -> None:
    value = book()
    ltm = period("LTM", "2024-07-01", "2025-06-30", 2, "LTM")
    adjustment = ProFormaObservation(
        adjustment_id="acq",
        event_id="event",
        label="Acquisition",
        period_id="LTM",
        effective_date=date(2025, 7, 2),
        announced_on=date(2025, 7, 1),
        event_status="completed",
        classification="ACQUISITION",
        metric_id="facility:loan",
        value=observed("adjustment", "20"),
        event_citations=(_C,),
    )
    value = value.model_copy(update={"periods": (*value.periods, ltm), "pro_forma": (adjustment,)})
    pack, context, financial, binding = case(value)
    assert any(
        "Pro forma lacks" in issue
        for issue in validate_financial_context(pack, context, financial, binding)
    )
    event = SubsequentEvent(
        event_id="event",
        reporting_scope_id="Q2",
        event_date=date(2025, 7, 2),
        known_on=date(2025, 7, 3),
        status="completed",
        description="Synthetic acquisition",
        effect="Pro forma only",
        citations=tuple(records(financial.books[0].pro_forma[0], Citation)),
    )
    source = context.sources[0].model_copy(
        update={"event_scan": "events_identified", "event_ids": (event.event_id,)}
    )
    context = context.model_copy(update={"sources": (source,), "events": (event,)})
    binding = binding.model_copy(update={"source_context_review_sha256": context.content_hash()})
    original = financial.model_dump_json()
    assert validate_financial_context(pack, context, financial, binding) == ()
    assert financial.model_dump_json() == original
    for changes in (
        {"event_date": date(2025, 7, 3)},
        {"status": "announced"},
    ):
        changed = context.model_copy(update={"events": (event.model_copy(update=changes),)})
        new_binding = binding.model_copy(
            update={"source_context_review_sha256": changed.content_hash()}
        )
        assert validate_financial_context(pack, changed, financial, new_binding)


def test_event_scan_and_scope_evidence_cannot_be_borrowed_from_another_source() -> None:
    pack, review = event_case()
    second_source = pack.sources[0].model_copy(update={"source_id": "S2", "name": "Second source"})
    pack = pack.model_copy(update={"sources": (*pack.sources, second_source)})
    first = review.sources[0]
    second_citations = tuple(c.model_copy(update={"source_id": "S2"}) for c in first.citations)
    second = first.model_copy(
        update={
            "source_id": "S2",
            "citations": second_citations,
            "scopes": (),
            "event_scan": "no_events_identified",
            "event_ids": (),
            "event_scan_citations": second_citations,
        }
    )
    event = review.events[0].model_copy(
        update={"citations": (*review.events[0].citations, *second_citations)}
    )
    review = review.model_copy(
        update={"pack_sha256": pack.content_hash(), "sources": (first, second), "events": (event,)}
    )
    assert any("omitted by source scan" in issue for issue in validate_source_context(pack, review))
    second = second.model_copy(
        update={"event_scan": "events_identified", "event_ids": (event.event_id,)}
    )
    review = review.model_copy(update={"sources": (first, second)})
    assert validate_source_context(pack, review) == ()
    event = event.model_copy(update={"citations": first.citations})
    bad = review.model_copy(update={"events": (event,)})
    assert any("attachment lacks evidence" in issue for issue in validate_source_context(pack, bad))
    scope = first.scopes[0].model_copy(update={"citations": second_citations})
    first = first.model_copy(update={"scopes": (scope, *first.scopes[1:])})
    bad = review.model_copy(update={"sources": (first, second)})
    assert any(
        "scope cites another source" in issue for issue in validate_source_context(pack, bad)
    )


def test_financial_binding_checks_conflict_alternative_sources_not_just_settled_values() -> None:
    pack, context, financial, binding = case()
    second_source = pack.sources[0].model_copy(
        update={"source_id": "S2", "name": "Different perimeter"}
    )
    pack = pack.model_copy(update={"sources": (*pack.sources, second_source)})
    first = context.sources[0]
    citations = tuple(c.model_copy(update={"source_id": "S2"}) for c in first.citations)
    scopes = tuple(
        scope.model_copy(
            update={
                "scope_id": "S2." + scope.scope_id,
                "entity_perimeter": "Other",
                "citations": citations,
            }
        )
        for scope in first.scopes
    )
    second = first.model_copy(
        update={
            "source_id": "S2",
            "citations": citations,
            "event_scan_citations": citations,
            "scopes": scopes,
        }
    )
    context = context.model_copy(
        update={"pack_sha256": pack.content_hash(), "sources": (first, second)}
    )
    row = financial.books[0].accounts[0]
    conflict_value = Observation(
        observation_id=row.value.observation_id,
        status="conflicting",
        amount=None,
        reason="Different source scope",
        citations=(),
        alternatives=(
            Alternative(amount=Decimal(10), citations=first.citations, explanation="A"),
            Alternative(amount=Decimal(11), citations=citations, explanation="B"),
        ),
    )
    changed_book = financial.books[0].model_copy(
        update={
            "accounts": (
                row.model_copy(update={"value": conflict_value}),
                *financial.books[0].accounts[1:],
            )
        }
    )
    financial = financial.model_copy(
        update={"pack_sha256": pack.content_hash(), "books": (changed_book,)}
    )
    binding = binding.model_copy(
        update={
            "source_context_review_sha256": context.content_hash(),
            "financial_review_sha256": financial.content_hash(),
        }
    )
    issues = validate_financial_context(pack, context, financial, binding)
    assert any("Q1 S2" in issue and "No matching" in issue for issue in issues)


# --- task 2.9 fix 3: the readiness rules apply to source_context -----------------------------


def paged_context(**texts: str) -> tuple[PreparedPack, SourceContextReview]:
    """A context review over a pack holding pages 1-195, with `texts` in its prose fields."""
    pack = paged_pack(range(1, 196))
    source = pack.sources[0]
    assert source.sha256
    cited = (
        Citation(
            source_id=source.source_id,
            source_sha256=source.sha256,
            locator="page:3",
            quote=texts.get("quote", "Page 3 text"),
        ),
    )
    scope = ReportingScope(
        scope_id="FY2025",
        entity_id="issuer",
        period_label="FY2025",
        period_kind="historical_duration",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        currency="USD",
        unit="MILLIONS",
        entity_perimeter="Consolidated group",
        accounting_basis="US GAAP",
        citations=cited,
        limitations=tuple(filter(None, (texts.get("scope"),))),
    )
    entity = EntityContext(
        entity_id="issuer",
        name="Caesars Entertainment, Inc.",
        entity_type="group",
        roles=("issuer",),
        fiscal_year_end="31 December",
        citations=cited,
        limitations=tuple(filter(None, (texts.get("entity"),))),
    )
    context = SourceContext(
        source_id=source.source_id,
        classification="financial",
        document_type="Form 10-K",
        published_on=None,
        evidence_class="audited_financial_statements",
        evidence_rationale=texts.get("rationale", "Annual report on Form 10-K"),
        analytical_use="Historical credit analysis",
        citations=cited,
        scopes=(scope,),
        event_scan="unassessed",
        event_scan_explanation=texts.get("scan", "Not assessed in this test"),
        limitations=tuple(filter(None, (texts.get("source"),))),
    )
    review = SourceContextReview(
        pack_sha256=pack.content_hash(),
        entities=(entity,),
        sources=(context,),
        limitations=tuple(filter(None, (texts.get("review"),))),
    )
    return pack, review


ABSENT_53_96 = (
    "Absence claim contradicts extraction coverage: page:53 to page:96 retained in czr-2025-10k"
)


def test_a_clean_paged_context_has_no_issue() -> None:
    assert validate_source_context(*paged_context()) == ()


@pytest.mark.parametrize("field", ["source", "scope", "entity", "rationale", "scan", "review"])
def test_every_prose_field_is_held_to_the_extraction_coverage(field: str) -> None:
    # GLM f0391c45 (probe-3), verbatim: the pack retains pages 53-96.
    pack, review = paged_context(**{field: GLM_F0391C45_LIMITATION})
    assert validate_source_context(pack, review) == (ABSENT_53_96,)


def test_negated_coverage_statements_pass_in_source_context() -> None:
    pack, review = paged_context(source=LUNA_F136B227_LIMITATION, review=GLM_76FC5C95_LIMITATION)
    assert validate_source_context(pack, review) == ()


def test_an_absence_claim_stands_when_the_pack_lacks_the_pages() -> None:
    pack, review = paged_context(source=GLM_F0391C45_LIMITATION)
    holed = pack.sources[0].model_copy(
        update={
            "spans": tuple(
                span for span in pack.sources[0].spans if not 53 <= int(span.locator[5:]) <= 96
            )
        }
    )
    pack = pack.model_copy(update={"sources": (holed,)})
    review = review.model_copy(update={"pack_sha256": pack.content_hash()})
    assert validate_source_context(pack, review) == ()


def test_quoted_source_text_is_not_judged_as_a_claim() -> None:
    pack, review = paged_context()
    spans = list(pack.sources[0].spans)
    spans[2] = spans[2].model_copy(update={"text": "pages 53-96 are absent in this draft"})
    pack = pack.model_copy(
        update={"sources": (pack.sources[0].model_copy(update={"spans": tuple(spans)}),)}
    )
    _, review = paged_context(quote="pages 53-96 are absent")
    review = review.model_copy(update={"pack_sha256": pack.content_hash()})
    assert validate_source_context(pack, review) == ()


def test_source_context_quotes_use_the_layout_normalised_matcher() -> None:
    pack, review = paged_context(quote="Page  3\ntext")
    assert validate_source_context(pack, review) == ()
    pack, review = paged_context(quote="Page 4 text")
    issues = validate_source_context(pack, review)
    # One issue per failing citation (entity, source and scope), each naming the quote.
    assert (
        issues
        == (
            "Quote/locator mismatch: quote not found under czr-2025-10k page:3 (normalised "
            'whitespace, quote marks and dashes): "Page 4 text"',
        )
        * 3
    )
