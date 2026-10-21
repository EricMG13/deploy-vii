# Facility FX increment review

Task `dvii-implementation-001`, owner session
`01a15bb5-b5bc-7151-94b3-4edbae9d7815`; base `1c4e03c` on
`codex/development-environment`, 21 October 2026. Scope: source-bound foreign
facility normalization through the internal CP-1/Model APIs. No dependencies,
frontend assets, live model calls or publication changed. OpenRouter spend remains
US$0 of the US$50 first-core cap. Full A–H goal remains active.

## Confidence review

Ranked doubts investigated against the implementation and actual callers:

1. **Wrong currency/date, stale evidence or invented results.** The public review
   validator reconstructs typed contracts, checks located evidence and unique
   observations, then checks row hashes, orientation, exact period end and positive
   quotes. Tests reject stale hashes, reversed currencies, missing references,
   duplicate scopes, nonpositive rates and non-spot rate types. Report validation
   catches an edited normalization result through deterministic recomputation.
   **Verified fine.** Original review hashes remain unchanged by calculations.
2. **Same-date alias selection hiding a conflict or inventing zero.** Traced both
   historical balance reading and Model debt-stack selection. The normalizer
   nulls every alias for source/rate conflicts before selection. Tested conflicting
   FY/Q4 quotes and source values, absent/missing quotes, missing source amounts,
   and source zero without FX. Independently supported aliases can still supply a
   known closing balance when another quote is merely missing. **Verified fine.**
3. **Normalization identity not binding its date.** A concrete missing-conversion
   case changed the period date but retained the same normalization ID. The output
   record changed, so the old identity was insufficient. Added the complete period
   hash to the payload; the regression now passes. **Fixed.**
4. **Loss of FX reasons/evidence in the cumulative ledger.** Traced null historical
   input rows: their new normalization references had no raw observation ID, so
   the prior path emitted an uncited generic gap. Resolve normalization records
   explicitly, retaining their reason/citations and BLOCK status. A focused
   regression verifies this path. A replay of the original function produced six
   uncited generic FX gaps; the patch produces six cited FX-specific BLOCK gaps
   (`artifacts/fx-gap-reproduction.txt`). **Fixed.** Source audit also retains every FX gap.
5. **Currency/scale mix-up and lease/principal substitution.** Adapter monetary
   fields use book currency and scale; original foreign dimensions remain in
   source positions and normalization records. Rates/coupons stay unchanged.
   Source reconciliation uses carrying values, excluding both lease types.
   A concrete FX finance-lease probe returned Model debt 200, independently
   reported canonical non-lease debt 100 and PASS source debt checks. **Verified
   fine.** CP-1's reported debt remains available even when missing FX blocks the
   facility aggregate; erasing that reported value would change adopted semantics.
6. **Ambient precision, negative adjustments and rate-one classification.** Tests
   exercise precision 3, exact negative debt adjustment multiplication, rate one,
   and converted amortisation while coupons remain unchanged. **Verified fine.**
7. **Alias evidence amplification and redundant work.** Source-register row limits
   alone permit large repeated alias input lists. Added an aggregate one-million
   reference guard before materialization and tested exactly-at-limit acceptance
   and just-over-limit rejection. Reused normalization maps during evidence
   assembly, indexed source debt candidates and cached citation resolution once
   per call. **Fixed/bounded.** No financial coverage is inferred from the limit.
8. **Optimization cache correctness and caller drift.** Selected caches are local
   to one call, keyed by identity of immutable contracts still retained in the
   book, never by possibly duplicated source IDs. Exact structured differential
   testing compares diagnostics, exceptions, JSON, hashes, ordering and citations.
   Strict typing and 209 focused tests pass on the applied winner. **Verified fine.**
9. **Source and live qualification.** Synthetic quoted rates test mechanics only;
   a valid literal quote does not establish market/source suitability. The source
   context and analyst review remain required. Source-first execution, CP-1/Model
   journal/Markdown/Workbench delivery, CP-1A and later Modules are still pending.
   **Open product work, not an external blocker.** No live/HTML/native acceptance
   is claimed for this internal API increment.

The pure normalization helper assumes callers first validate the whole review.
Direct use does not replace global facility-series, period or observation checks;
public entry points reconstruct and validate before invoking it. This is by design.

## Key-area post-edit rewrite tournament

Only `fx_conversion_issues` and `normalize_facilities` were selected. Routine
adapter/report assembly, audit/gap plumbing and test/schema changes use focused
checks and confidence review; no broader tournament was run.

Fresh GPT-6.1 Sol/high roles followed the user's model matrix: incumbent, speed,
memory, readability and blind arbiter, at most three workers concurrently.
Workers wrote ignored scratch candidates only; the coordinator owns all production
edits, checks and integration. Coordinator model was unchanged.

GitNexus context lookup for this repository returned repository-not-found. `rg`
traced callers through financial validation, adapter, source citation resolution,
historical evidence/values, source/period reconciliation, audit, Model, canonical
KPIs, actual computation traces and readiness/gaps. Strict mypy rechecked contracts.

**Winner: Snippet A (speed).** Replaces the two scoped functions in
`src/deploy_vii/facility_fx.py`; public signatures and outputs remain unchanged.
The blind bracket selected A over B, A over C, then A over D (incumbent).

- Per-call caches avoid repeated serialization of immutable facility, period,
  conversion and observation objects while retaining exact evidence ordering.
- The JSON payload remains encoded by `json.dumps`, avoiding a custom streaming
  encoder and its extra byte-compatibility invariant.
- Named count maps and local identity caches keep validation and provenance
  inspectable; caches never survive a call or collapse equal IDs with distinct data.

Coordinator verification: all three candidates exactly matched the incumbent on
318 cases each (159 cases under two Decimal precisions). This includes source/rate
states, signed/extreme values, duplicate/unknown/stale bindings, wrong currencies,
missing dates, repeated IDs and deterministic row-order permutations. Measured 50
small fixture normalizations: incumbent 0.0677s, winner 0.0271s, memory 0.0697s,
readability 0.0678s. This is one local micro-measurement, not a general benchmark.

Backed up production before applying A. Ran:

```text
uv run --locked pytest tests/product/test_facility_fx.py tests/product/test_financials.py tests/product/test_financial_periods.py tests/product/test_reconciliation.py tests/product/test_period_reconciliation.py tests/product/test_canonical_audit.py tests/product/test_model_readiness.py tests/product/test_calculation_trace.py tests/product/test_canonical_kpis.py -q
209 passed in 5.54s
uv run --locked mypy src
Success: no issues found in 41 source files
```

The exact-boundary regression also passed after tightening that test. Ignored raw
candidates, bracket, parity script and results are in `artifacts/fx-tournament/`.
Full `make product-check`: 774 tests pass, 97.49% branch-inclusive coverage,
Ruff lint/format, strict mypy and JavaScript syntax all pass. Log:
`artifacts/fx-product-check.log`. Final fixture-only correction makes synthetic
quote text match converted source amounts and the rate-one case; all 23 FX tests
rerun successfully (`artifacts/fx-final-fixtures.log`). Production code unchanged.
`make check` passed all hygiene gates. `make secrets` passed directory, staged
diff and full reachable-history scans; no leaks found. Logs: `artifacts/fx-check.log`
and `artifacts/fx-secrets.log`. Full candidate diff inspected by the coordinator.

## Design hook triage

No CSS changed. The side-tab finding is the intentional active-module navigation
marker retained from Direction C. Existing file-scoped `side-tab/*` ignore in
`.impeccable/config.json` already covers it. Fixed: none; new suppressions: none;
retained: the marker and existing narrow ignore. No rule/file-wide ignore added.

## Final code

```python
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

```
