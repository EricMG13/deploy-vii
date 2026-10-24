"""Bind financial extraction to explicit source/entity scope without conversions."""

from typing import Annotated, Literal

from pydantic import Field, ValidationError

from deploy_vii.canonical_audit import _positions
from deploy_vii.contracts import PREFILLED_MARKER, Citation, Contract, Hash, Identifier
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.financial_validation import records, validate_financial_review
from deploy_vii.preparation import PreparedPack
from deploy_vii.source_context import SourceContextReview, validate_source_context


class BookEntityBinding(Contract):
    book_id: Identifier
    entity_id: Identifier


class FinancialContextBinding(Contract):
    schema_version: Literal["financial-context-binding/1"] = "financial-context-binding/1"
    financial_review_sha256: Hash = Field(json_schema_extra={PREFILLED_MARKER: "financial-review"})
    source_context_review_sha256: Hash = Field(
        json_schema_extra={PREFILLED_MARKER: "source-context-review"}
    )
    books: Annotated[tuple[BookEntityBinding, ...], Field(min_length=1, max_length=20)]


def validate_financial_context(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    binding: FinancialContextBinding,
) -> tuple[str, ...]:
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        context = SourceContextReview.model_validate_json(context.model_dump_json())
        financial = FinancialReview.model_validate_json(financial.model_dump_json())
        binding = FinancialContextBinding.model_validate_json(binding.model_dump_json())
    except ValidationError as error:
        return (f"Invalid financial context binding: {error}",)
    # Fully validate both reviews before using their cross-references.
    issues = [*validate_source_context(pack, context), *validate_financial_review(pack, financial)]
    if issues:
        return tuple(issues)
    # Identity failures prevent traversal of bound books.
    if (
        binding.financial_review_sha256 != financial.content_hash()
        or binding.source_context_review_sha256 != context.content_hash()
    ):
        issues.append("Context binding does not identify current financial and source reviews")
    books = {b.book_id: b for b in financial.books}
    entities = {e.entity_id for e in context.entities}
    if len(binding.books) != len(books) or {b.book_id for b in binding.books} != books.keys():
        issues.append("Bind every financial book exactly once")
    for row in binding.books:
        if row.entity_id not in entities:
            issues.append(f"Unknown bound entity: {row.book_id} {row.entity_id}")
    if issues:
        return tuple(issues)
    source_index = {s.source_id: s for s in context.sources}
    event_index = {e.event_id: e for e in context.events}
    scope_index = {scope.scope_id: scope for s in context.sources for scope in s.scopes}
    for bound in binding.books:
        book = books[bound.book_id]
        periods = {p.period_id: p for p in book.periods}
        # Include period metadata and every located observation alternative.
        evidence: set[tuple[str, str]] = set()
        for period in book.periods:
            evidence.update((period.period_id, c.source_id) for c in period.citations)
        for position in _positions(book):
            if position.register_id == "pro_forma":
                continue
            evidence.update(
                (position.period_id, c.source_id) for c in records(position.observation, Citation)
            )
        for period_id, source_id in sorted(evidence):
            period = periods[period_id]
            source = source_index[source_id]
            if source.classification != "financial":
                issues.append(
                    "Financial evidence source not classified financial: "
                    f"{book.book_id} {source_id}"
                )
                continue
            # A matching name is insufficient: the explicit entity, dates and
            # canonical dimensions must all agree before extraction is bound.
            has_matching_scope = any(
                scope.entity_id == bound.entity_id
                and scope.currency == book.currency
                and scope.unit == book.unit
                and scope.entity_perimeter == book.entity_perimeter
                and scope.accounting_basis == book.accounting_basis
                and scope.end_date is not None
                and scope.end_date == period.end_date
                and scope.period_kind in {"historical_duration", "period_end"}
                and (
                    period.period_type == "PERIOD_END"
                    or (
                        scope.period_kind == "historical_duration"
                        and scope.start_date is not None
                        and scope.start_date == period.start_date
                    )
                )
                for scope in source.scopes
            )
            if not has_matching_scope:
                issues.append(
                    "No matching entity/date/basis source scope: "
                    f"{book.book_id} {period_id} {source_id}"
                )
        # Pro forma evidence is bound to its separate subsequent-event context.
        for adjustment in book.pro_forma:
            event = event_index.get(adjustment.event_id)
            scope = scope_index.get(event.reporting_scope_id) if event else None
            source_ids = {c.source_id for c in records(adjustment, Citation)}
            has_matching_event = (
                event is not None
                and scope is not None
                and scope.entity_id == bound.entity_id
                and scope.end_date == periods[adjustment.period_id].end_date
                and (scope.currency, scope.unit, scope.entity_perimeter, scope.accounting_basis)
                == (book.currency, book.unit, book.entity_perimeter, book.accounting_basis)
                and event.event_date == adjustment.effective_date
                and event.status == adjustment.event_status
                and event.known_on >= adjustment.announced_on
                and source_ids <= {c.source_id for c in event.citations}
                and all(source_index[sid].classification == "financial" for sid in source_ids)
            )
            if not has_matching_event:
                issues.append(
                    "Pro forma lacks matching located subsequent-event context: "
                    f"{book.book_id} {adjustment.adjustment_id}"
                )
    return tuple(issues)
