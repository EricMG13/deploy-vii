"""CP-1 source/normalization/definition/gap registers; no analytical clearance.

Definition assessments are evidence-linked analyst judgements. They cannot
replace Python's definitions, settle observations or waive reconciliation checks.
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from deploy_vii.contracts import Citation, Contract, Hash, Identifier, Text
from deploy_vii.financial_contracts import FinancialBook, FinancialReview, Located, Observation
from deploy_vii.financial_periods import _id
from deploy_vii.financial_reconciliation import ReconciliationReport, reconcile_financials
from deploy_vii.financial_validation import records, validate_financial_review
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import citation_issues
from deploy_vii.statement_output import StatementReport, statement_report
from deploy_vii.statement_validation import ACCOUNT_LINKS, account_outflow


class DefinitionAssessment(Contract):
    assessment_id: Identifier
    metric: Text
    canonical_definition: Text
    issuer_definition: Text
    status: Literal["aligned", "conflict"]
    observation_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=20000)]
    citations: Located
    materiality: Text
    downstream_impact: Text
    recommendation: Text


class EventFigure(Contract):
    observation_id: Identifier
    statement_role: Text


class MultiFigureEvent(Contract):
    event_id: Identifier
    description: Text
    figures: Annotated[tuple[EventFigure, ...], Field(min_length=2, max_length=20000)]
    explanation: Text
    citations: Located
    downstream_impact: Text


class DefinitionReview(Contract):
    schema_version: Literal["definition-review/1"] = "definition-review/1"
    financial_review_sha256: Hash
    book_id: Identifier
    assessments: Annotated[tuple[DefinitionAssessment, ...], Field(max_length=20000)] = ()
    events: Annotated[tuple[MultiFigureEvent, ...], Field(max_length=20000)] = ()
    limitations: tuple[Text, ...] = ()


class SourcePosition(Contract):
    """An original observation and its dimensions, including all alternatives."""

    register_id: Identifier
    row_id: Identifier
    field: Identifier
    period_id: Identifier
    currency: Text | None
    unit: Text
    observation: Observation


class NormalizationRow(Contract):
    normalization_id: Identifier
    observation_id: Identifier
    period_id: Identifier
    before: Decimal
    after: Decimal
    operation: Literal["negative absolute source amount"] = "negative absolute source amount"
    rationale: Text
    citations: Located


class DefinitionRow(Contract):
    row_id: Identifier
    kind: Literal["assessment", "value_conflict", "debt_basis", "multi_figure_event"]
    status: Literal["aligned", "conflict", "distinct_bases"]
    metric: Text
    canonical_definition: Text | None
    issuer_definition: Text | None
    observation_ids: tuple[Identifier, ...]
    period_ids: tuple[Identifier, ...]
    roles: tuple[Text, ...]
    explanation: Text
    materiality: Text
    downstream_impact: Text
    recommendation: Text
    citations: tuple[Citation, ...]


class AuditGap(Contract):
    gap_id: Identifier
    origin: Text
    reference: Text
    period_ids: tuple[Identifier, ...]
    description: Text
    severity: Literal["WARN", "BLOCK"]
    downstream_impact: Text
    recommended_action: Text
    citations: tuple[Citation, ...]


class CanonicalAuditReport(Contract):
    schema_version: Literal["canonical-audit/2"] = "canonical-audit/2"
    # These existing artifacts bind run, issuer, dates, dimensions and hashes.
    statements: StatementReport
    reconciliation: ReconciliationReport
    definition_review: DefinitionReview
    source_positions: tuple[SourcePosition, ...]
    normalizations: tuple[NormalizationRow, ...]
    definitions: tuple[DefinitionRow, ...]
    unassessed_observation_ids: tuple[Identifier, ...]
    gaps: tuple[AuditGap, ...]
    limitations: tuple[Text, ...]


def _positions(book: FinancialBook) -> tuple[SourcePosition, ...]:
    positions: list[SourcePosition] = []
    for register, identity in (
        ("accounts", "metric_id"),
        ("addbacks", "addback_id"),
        ("segments", "segment_id"),
        ("kpis", "kpi_id"),
        ("facilities", "facility_id"),
        ("pro_forma", "adjustment_id"),
        ("statement_lines", "line_id"),
        ("balance_movements", "movement_id"),
    ):
        for row in getattr(book, register):
            for field in type(row).model_fields:
                value = getattr(row, field)
                if not isinstance(value, Observation):
                    continue
                unit: str = book.unit
                currency: str | None = book.currency
                if register == "kpis":
                    unit, currency = row.unit, None
                elif register == "facilities":
                    currency = row.currency
                    if field in {"spread_bps", "floor_bps", "fixed_rate"}:
                        unit = "basis_points" if field != "fixed_rate" else "decimal_fraction"
                        currency = None
                elif register == "accounts" and row.metric_id == "effective_tax_rate":
                    unit, currency = "decimal_fraction", None
                positions.append(
                    SourcePosition(
                        register_id=register,
                        row_id=getattr(row, identity),
                        field=field,
                        period_id=row.period_id,
                        currency=currency,
                        unit=unit,
                        observation=value,
                    )
                )
    return tuple(positions)


def validate_definition_review(
    pack: PreparedPack,
    review: FinancialReview,
    definition: DefinitionReview,
) -> tuple[str, ...]:
    issues = list(validate_financial_review(pack, review))
    if issues:
        return tuple(issues)
    try:
        definition = DefinitionReview.model_validate_json(definition.model_dump_json())
    except ValidationError as error:
        return (*issues, f"Invalid definition contract: {error}")
    if definition.financial_review_sha256 != review.content_hash():
        issues.append("Definition review does not bind current financial review")
    book = next((b for b in review.books if b.book_id == definition.book_id), None)
    if book is None:
        return (*issues, "Unknown definition review book")
    observations = {v.observation_id: v for v in records(book, Observation)}
    issues.extend(citation_issues(tuple(records(definition, Citation)), pack.sources))
    for rows, identity in (
        (definition.assessments, "assessment_id"),
        (definition.events, "event_id"),
    ):
        if len(rows) != len({getattr(row, identity) for row in rows}):
            issues.append(f"Duplicate definition record: {identity}")
    assessed: set[str] = set()
    for assessment in definition.assessments:
        ids = assessment.observation_ids
        unique_ids = set(ids)
        if len(ids) != len(unique_ids) or not unique_ids <= observations.keys():
            issues.append(
                f"Duplicate or unknown assessment observation: {assessment.assessment_id}"
            )
        if not assessed.isdisjoint(unique_ids):
            issues.append("An observation cannot have multiple definition assessments")
        assessed.update(unique_ids)
        if assessment.status == "aligned" and any(
            observations[oid].status == "conflicting" for oid in ids if oid in observations
        ):
            issues.append("Conflicting observations cannot be declared aligned")
    for event in definition.events:
        unique_ids = {figure.observation_id for figure in event.figures}
        if len(event.figures) != len(unique_ids) or not unique_ids <= observations.keys():
            issues.append(f"Duplicate or unknown event observation: {event.event_id}")
    return tuple(issues)


def _definitions(
    book: FinancialBook,
    positions: tuple[SourcePosition, ...],
    review: DefinitionReview,
) -> tuple[DefinitionRow, ...]:
    index = {p.observation.observation_id: p for p in positions}
    rows: list[DefinitionRow] = []

    def append(
        key: str,
        kind: Literal["assessment", "value_conflict", "debt_basis", "multi_figure_event"],
        status: Literal["aligned", "conflict", "distinct_bases"],
        metric: str,
        ids: tuple[str, ...],
        explanation: str,
        *,
        roles: tuple[str, ...] = (),
        canonical: str | None = None,
        issuer: str | None = None,
        materiality: str = "Not assessed; retained values must be reviewed",
        impact: str = "Consumers must retain the distinct source meanings",
        action: str = "Review source definitions; do not settle or substitute values silently",
        citations: tuple[Citation, ...] = (),
    ) -> None:
        evidence: dict[Citation, None] = dict.fromkeys(citations)
        for oid in ids:
            for citation in records(index[oid].observation, Citation):
                evidence[citation] = None
        rows.append(
            DefinitionRow(
                row_id=_id("definition", kind, key),
                kind=kind,
                status=status,
                metric=metric,
                canonical_definition=canonical,
                issuer_definition=issuer,
                observation_ids=ids,
                period_ids=tuple(dict.fromkeys(index[oid].period_id for oid in ids)),
                roles=roles,
                explanation=explanation,
                materiality=materiality,
                downstream_impact=impact,
                recommendation=action,
                citations=tuple(evidence),
            )
        )

    for row in review.assessments:
        append(
            row.assessment_id,
            "assessment",
            row.status,
            row.metric,
            row.observation_ids,
            "Evidence-linked analyst definition assessment; does not change Python formulas",
            canonical=row.canonical_definition,
            issuer=row.issuer_definition,
            materiality=row.materiality,
            impact=row.downstream_impact,
            action=row.recommendation,
            citations=row.citations,
        )
    for position in positions:
        value = position.observation
        if value.status == "conflicting":
            append(
                value.observation_id,
                "value_conflict",
                "conflict",
                position.row_id,
                (value.observation_id,),
                value.reason or "Unresolved source alternatives",
            )
    for facility in book.facilities:
        carrying, principal = facility.carrying_value, facility.principal
        if (
            carrying.amount is not None
            and principal.amount is not None
            and carrying.amount != principal.amount
        ):
            append(
                _id("facility", facility.facility_id, facility.period_id),
                "debt_basis",
                "distinct_bases",
                facility.facility_name,
                (carrying.observation_id, principal.observation_id),
                "Carrying value differs from gross principal; both source figures are retained",
                roles=("carrying_value", "gross_principal"),
                canonical="Canonical debt uses carrying value excluding both lease types",
                citations=facility.terms_citations,
            )
    for event in review.events:
        append(
            event.event_id,
            "multi_figure_event",
            "distinct_bases",
            event.description,
            tuple(f.observation_id for f in event.figures),
            event.explanation,
            roles=tuple(f.statement_role for f in event.figures),
            impact=event.downstream_impact,
            citations=event.citations,
        )
    return tuple(rows)


def _normalizations(
    book: FinancialBook, statements: StatementReport
) -> tuple[NormalizationRow, ...]:
    rows: list[NormalizationRow] = []
    for cell in statements.cells:
        if (
            cell.normalization_id
            and cell.observation_id
            and cell.source_amount is not None
            and cell.normalized_amount is not None
        ):
            rows.append(
                NormalizationRow(
                    normalization_id=cell.normalization_id,
                    observation_id=cell.observation_id,
                    period_id=cell.period_id,
                    before=cell.source_amount,
                    after=cell.normalized_amount,
                    rationale="Canonical outflow sign; source statement and sign evidence retained",
                    citations=cell.citations,
                )
            )
    for movement in book.balance_movements:
        value = movement.value
        if (
            movement.sign_convention == "outflow_magnitude"
            and value.amount is not None
            and value.amount > 0
        ):
            rows.append(
                NormalizationRow(
                    normalization_id=_id("normalization", value.observation_id),
                    observation_id=value.observation_id,
                    period_id=movement.period_id,
                    before=value.amount,
                    after=value.amount.copy_abs().copy_negate(),
                    rationale="Explicit source balance-movement outflow sign",
                    citations=tuple(dict.fromkeys((*value.citations, *movement.sign_citations))),
                )
            )
    for account in book.accounts:
        value = account.value
        if (
            value.amount is not None
            and value.amount > 0
            and account_outflow(book, account.period_id, account.metric_id)
        ):
            rows.append(
                NormalizationRow(
                    normalization_id=_id("normalization", value.observation_id),
                    observation_id=value.observation_id,
                    period_id=account.period_id,
                    before=value.amount,
                    after=value.amount.copy_abs().copy_negate(),
                    rationale="Canonical account outflow sign; original source amount retained",
                    citations=tuple(
                        dict.fromkeys(
                            (
                                *value.citations,
                                *(
                                    c
                                    for line in book.statement_lines
                                    if line.period_id == account.period_id
                                    and ACCOUNT_LINKS.get((line.statement, line.item_id))
                                    == account.metric_id
                                    for c in line.sign_citations
                                ),
                            )
                        )
                    ),
                )
            )
    return tuple(rows)


def canonical_audit(
    pack: PreparedPack,
    review: FinancialReview,
    definition: DefinitionReview,
) -> CanonicalAuditReport:
    issues = validate_definition_review(pack, review, definition)
    if issues:
        raise ValueError("; ".join(issues))
    review = FinancialReview.model_validate_json(review.model_dump_json())
    definition = DefinitionReview.model_validate_json(definition.model_dump_json())
    book = next(b for b in review.books if b.book_id == definition.book_id)
    statements = statement_report(pack, review, book.book_id)
    reconciliation = reconcile_financials(pack, review, book.book_id)
    positions = _positions(book)
    definitions = _definitions(book, positions, definition)
    assessed = {oid for a in definition.assessments for oid in a.observation_ids}
    # r14 exceptions: an unstated floor, fixed coupon on FLOATING debt, or
    # spread on FIXED debt is not a missing value. Conflicts still are.
    optional_terms = {
        value.observation_id
        for facility in book.facilities
        for field in ("floor_bps", "fixed_rate", "spread_bps")
        for value in (getattr(facility, field),)
        if value.amount is None
        and value.status in {"missing", "not_applicable"}
        and (
            field == "floor_bps"
            or (field == "fixed_rate" and facility.rate_type == "FLOATING")
            or (field == "spread_bps" and facility.rate_type == "FIXED")
        )
    }
    assessed_or_optional = assessed | optional_terms
    unassessed = tuple(
        p.observation.observation_id
        for p in positions
        if p.observation.observation_id not in assessed_or_optional
    )
    gaps: list[AuditGap] = []

    def gap(
        origin: str,
        reference: str,
        description: str,
        periods: tuple[str, ...] = (),
        severity: Literal["WARN", "BLOCK"] = "WARN",
        citations: tuple[Citation, ...] = (),
    ) -> None:
        gaps.append(
            AuditGap(
                gap_id=_id("gap", origin, reference),
                origin=origin,
                reference=reference,
                period_ids=periods,
                description=description,
                severity=severity,
                downstream_impact="CP-1 coverage and affected consumer calculations require review",
                recommended_action=(
                    "Obtain source evidence or retain the stated limitation; rerun affected checks"
                ),
                citations=citations,
            )
        )

    for position in positions:
        value = position.observation
        if value.status != "known" and value.observation_id not in optional_terms:
            gap(
                "observation",
                value.observation_id,
                value.reason or value.status,
                (position.period_id,),
                "BLOCK" if value.status == "conflicting" else "WARN",
                tuple(records(value, Citation)),
            )
    for cell in statements.cells:
        if cell.observation_id is None:
            gap(
                "statement",
                _id("cell", cell.statement, cell.period_id, cell.item_id),
                f"{cell.statement} {cell.item_id}: required statement item not supplied",
                (cell.period_id,),
            )
    for check in reconciliation.checks:
        if check.status != "PASS":
            gap(
                "reconciliation",
                check.check_id,
                check.explanation,
                (check.period_id,),
                check.status,
                tuple(dict.fromkeys(records(check, Citation))),
            )
    for row in definitions:
        if row.status != "aligned":
            gap("definition", row.row_id, row.explanation, row.period_ids, citations=row.citations)
    for position in positions:
        if position.observation.observation_id not in assessed_or_optional:
            gap(
                "definition_coverage",
                position.observation.observation_id,
                "Source definition has not been assessed",
                (position.period_id,),
                citations=tuple(records(position.observation, Citation)),
            )
    for period in book.periods:
        if period.limitation:
            gap(
                "period",
                period.period_id,
                period.limitation,
                (period.period_id,),
                citations=period.citations,
            )
    for facility in book.facilities:
        if facility.maturity_date is None:
            gap(
                "facility_term",
                _id("term", facility.facility_id, facility.period_id, "maturity"),
                facility.maturity_limitation or "Maturity unavailable",
                (facility.period_id,),
                citations=facility.terms_citations,
            )
        for field in (
            "secured_status",
            "seniority",
            "lease_classification",
            "rate_type",
            "reference_rate",
        ):
            if getattr(facility, field) == "NOT_STATED":
                gap(
                    "facility_term",
                    _id("term", facility.facility_id, facility.period_id, field),
                    f"{facility.facility_name}: {field} not stated",
                    (facility.period_id,),
                    citations=facility.terms_citations,
                )
    for name, disclosure in (
        ("addbacks", book.addback_disclosure),
        ("segments", book.segment_disclosure),
    ):
        if disclosure.status != "complete":
            gap("disclosure", name, disclosure.explanation, citations=disclosure.citations)
    for disclosure_row in book.statement_disclosures:
        if disclosure_row.disclosure.status != "complete":
            gap(
                "disclosure",
                _id("disclosure", disclosure_row.statement, disclosure_row.period_id),
                disclosure_row.disclosure.explanation,
                (disclosure_row.period_id,),
                citations=disclosure_row.disclosure.citations,
            )
    limitations = (*review.limitations, *book.limitations, *definition.limitations)
    for i, limitation in enumerate(limitations):
        gap("limitation", str(i), limitation)
    return CanonicalAuditReport(
        statements=statements,
        reconciliation=reconciliation,
        definition_review=definition,
        source_positions=positions,
        normalizations=_normalizations(book, statements),
        definitions=definitions,
        unassessed_observation_ids=unassessed,
        gaps=tuple(gaps),
        limitations=(
            *limitations,
            "Source-stage audit only: derived-period/KPI gaps, source tiers, narrative "
            "and full consumer readiness remain separate",
            "Definition and event completeness require analytical review; "
            "no global alignment or acceptance is inferred",
        ),
    )


def validate_canonical_audit(
    pack: PreparedPack,
    review: FinancialReview,
    definition: DefinitionReview,
    report: CanonicalAuditReport,
) -> tuple[str, ...]:
    try:
        report = CanonicalAuditReport.model_validate_json(report.model_dump_json())
        expected = canonical_audit(pack, review, definition)
    except ValueError as error:
        return (f"Invalid canonical audit: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Canonical audit differs from recomputed registers",)
    )
