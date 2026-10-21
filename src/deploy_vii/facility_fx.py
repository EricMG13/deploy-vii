"""Exact-date facility FX normalization; source registers are never overwritten."""

import hashlib
import json
from collections import Counter
from datetime import date
from decimal import Decimal, localcontext

from deploy_vii.contracts import Citation, Contract, Hash, Identifier, Text
from deploy_vii.financial_contracts import FinancialBook, Observation
from deploy_vii.model._cells import CONTEXT

MONETARY_FIELDS = (
    "carrying_value",
    "principal",
    "drawn_amount",
    "commitment",
    "annual_amortisation",
)


class FacilityNormalization(Contract):
    normalization_id: Identifier
    facility_id: Identifier
    period_id: Identifier
    field: Identifier
    facility_sha256: Hash
    conversion_id: Identifier | None
    source_observation_id: Identifier
    input_observation_ids: tuple[Identifier, ...]
    original_amount: Decimal | None
    source_currency: Text
    target_currency: Text
    unit: Text
    rate_date: date | None
    rate: Decimal | None
    amount: Decimal | None
    reason: Text | None
    formula: Text = "original amount * target currency units per source currency unit"
    arithmetic_context: Text = "decimal-38-half-even"
    citations: tuple[Citation, ...]


def fx_conversion_issues(book: FinancialBook) -> tuple[str, ...]:
    """Reject stale, ambiguous or wrongly oriented conversion bindings."""
    periods = {p.period_id: p for p in book.periods}
    facilities = {(r.facility_id, r.period_id): r for r in book.facilities}
    identities: set[str] = set()
    scopes: set[tuple[str, str]] = set()
    dated_rates: dict[tuple[str, date], Decimal] = {}
    rate_counts: Counter[tuple[str, date | None]] = Counter()
    issues: list[str] = []
    facility_hashes: dict[int, str] = {}
    for conversion in book.facility_fx_conversions:
        prefix = f"FX conversion {conversion.conversion_id}"
        scope = conversion.facility_id, conversion.period_id
        if conversion.conversion_id in identities:
            issues.append(f"{prefix}: duplicate ID")
        identities.add(conversion.conversion_id)
        if scope in scopes:
            issues.append(f"{prefix}: duplicate facility/period")
        scopes.add(scope)
        row = facilities.get(scope)
        period = periods.get(conversion.period_id)
        if row is None or period is None:
            issues.append(f"{prefix}: unknown facility/period")
            continue
        rate_counts[row.facility_id, period.end_date] += 1
        row_key = id(row)
        row_hash = facility_hashes.get(row_key)
        if row_hash is None:
            row_hash = row.content_hash()
            facility_hashes[row_key] = row_hash
        if conversion.facility_sha256 != row_hash:
            issues.append(f"{prefix}: stale facility hash")
        if (
            conversion.source_currency != row.currency
            or conversion.target_currency != book.currency
            or row.currency == book.currency
        ):
            issues.append(f"{prefix}: currencies must match foreign facility and book")
        if period.end_date != conversion.rate_date:
            issues.append(f"{prefix}: rate date must equal known period end")
        rate = conversion.rate.amount
        if rate is not None:
            if rate <= 0:
                issues.append(f"{prefix}: rate must be positive")
            key = row.facility_id, conversion.rate_date
            previous = dated_rates.setdefault(key, rate)
            if previous != rate:
                issues.append(f"{prefix}: same-date facility rates disagree")
    row_counts: Counter[tuple[str, date | None]] = Counter()
    conflict_counts: Counter[tuple[str, date | None]] = Counter()
    for row in book.facilities:
        period = periods.get(row.period_id)
        if row.currency != book.currency and period is not None:
            scope_date = row.facility_id, period.end_date
            row_counts[scope_date] += 1
            conflict_counts[scope_date] += sum(
                getattr(row, field).status == "conflicting" for field in MONETARY_FIELDS
            )
    # Bound retained alias evidence before materializing five records per row.
    if (
        sum(
            count * (5 * (1 + rate_counts[key]) + conflict_counts[key])
            for key, count in row_counts.items()
        )
        > 1_000_000
    ):
        issues.append("Expanded facility FX inputs exceed 1000000 references")
    return tuple(issues)


def _citations(observation: Observation) -> tuple[Citation, ...]:
    return (*observation.citations, *(c for a in observation.alternatives for c in a.citations))


def normalize_facilities(book: FinancialBook) -> tuple[FacilityNormalization, ...]:
    """Translate five money fields, retaining missing/conflicted rates as null.

    Callers validate the entire review first. This helper additionally refuses
    invalid FX bindings so direct use cannot apply a stale or reversed quote.
    A conflict on a same-date alias cannot be avoided by selecting a known row.
    """
    issues = fx_conversion_issues(book)
    if issues:
        raise ValueError("; ".join(issues))
    periods = {p.period_id: p for p in book.periods}
    conversions = {(c.facility_id, c.period_id): c for c in book.facility_fx_conversions}
    rate_groups: dict[tuple[str, date | None], list[Observation]] = {}
    conflicts: dict[tuple[str, date | None, str], list[Observation]] = {}
    for quote in book.facility_fx_conversions:
        key = quote.facility_id, quote.rate_date
        rate_groups.setdefault(key, []).append(quote.rate)
    for row in book.facilities:
        end = periods[row.period_id].end_date
        for field in MONETARY_FIELDS:
            value = getattr(row, field)
            if value.status == "conflicting":
                conflicts.setdefault((row.facility_id, end, field), []).append(value)
    # Contracts are immutable; object identity avoids conflating distinct evidence
    # records that happen to share an observation identifier.
    hashes: dict[int, str] = {}
    citation_cache: dict[int, tuple[Citation, ...]] = {}

    def content_hash(value: Contract) -> str:
        key = id(value)
        cached = hashes.get(key)
        if cached is None:
            cached = value.content_hash()
            hashes[key] = cached
        return cached

    def citations(value: Observation) -> tuple[Citation, ...]:
        key = id(value)
        cached = citation_cache.get(key)
        if cached is None:
            cached = _citations(value)
            citation_cache[key] = cached
        return cached

    result: list[FacilityNormalization] = []
    with localcontext(CONTEXT):
        for row in book.facilities:
            if row.currency == book.currency:
                continue
            end = periods[row.period_id].end_date
            conversion = conversions.get((row.facility_id, row.period_id))
            rate = conversion.rate.amount if conversion else None
            related_rates = rate_groups.get((row.facility_id, end), [])
            rate_conflict = any(r.status == "conflicting" for r in related_rates)
            for field in MONETARY_FIELDS:
                source: Observation = getattr(row, field)
                source_conflicts = conflicts.get((row.facility_id, end, field), [])
                inputs = (source, *source_conflicts, *related_rates)
                reason = (
                    "Same-date source amount is conflicting"
                    if source_conflicts
                    else source.reason
                    if source.amount is None
                    else "Same-date FX rate is conflicting"
                    if rate_conflict
                    else "No explicit source-bound FX conversion"
                    if conversion is None
                    else conversion.rate.reason
                    if rate is None
                    else None
                )
                # Hash the full row, conversion and alias inputs, not just numbers.
                payload = json.dumps(
                    (
                        book.book_id,
                        book.currency,
                        book.unit,
                        content_hash(row),
                        content_hash(periods[row.period_id]),
                        field,
                        content_hash(conversion) if conversion else "missing",
                        *(content_hash(value) for value in inputs),
                    )
                )
                result.append(
                    FacilityNormalization(
                        normalization_id="fx:" + hashlib.sha256(payload.encode()).hexdigest(),
                        facility_id=row.facility_id,
                        period_id=row.period_id,
                        field=field,
                        facility_sha256=content_hash(row),
                        conversion_id=conversion.conversion_id if conversion else None,
                        source_observation_id=source.observation_id,
                        input_observation_ids=tuple(
                            dict.fromkeys(v.observation_id for v in inputs)
                        ),
                        original_amount=source.amount,
                        source_currency=row.currency,
                        target_currency=book.currency,
                        unit=book.unit,
                        rate_date=end,
                        rate=rate,
                        amount=source.amount * rate
                        if reason is None and source.amount is not None and rate is not None
                        else None,
                        reason=reason,
                        citations=tuple(
                            dict.fromkeys(
                                (
                                    *(c for value in inputs for c in citations(value)),
                                    *row.terms_citations,
                                    *(conversion.citations if conversion else ()),
                                )
                            )
                        ),
                    )
                )
    return tuple(result)
