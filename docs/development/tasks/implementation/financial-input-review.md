# CP-1 financial input review

Scope: new `financial_contracts.py`, `financial_validation.py`,
`financial_adapter.py` and 55 synthetic boundary tests, on base `ccbe3c7`.
This internal boundary is not a completed CP-1 or Model Module. There is no new
report promotion, live analytical acceptance or native-host qualification.

## Confidence review

Least confident about (ranked):

1. Missing versus zero across sparse components — investigation traced the
   adapter through `account_frame` and statement aggregation. A synthetic H1
   composed of Q1/Q2 failed to compute financing -4 and add-backs 6 because the
   adapter inserted an explicit unknown aggregate. **Confirmed bug, fixed:**
   omit only unreported aggregate sparse rows with explicit components; leaf
   omissions and explicitly missing aggregates remain unknown. The regression
   checks CFO 112 and preserves null when one component is missing.
2. Facility opening inference and source dates — the raw kernel can infer
   issuance from first observation. Expansion now supplies explicit unknown
   rows unless cited issuance proves a zero opening. Review reproduced a second
   bug: an undated Q1 balance could contradict an April issuance date stated on
   Q2. **Confirmed bug, fixed:** check every observation against all known
   issuance dates for that facility. Missing date metadata does not erase known
   metadata. Conflicting dates, future issuance and same-date carrying conflicts
   cannot become settled values. Tests exercise these cases.
3. Finite inputs and graph trust — typed dataclasses alone are insufficient.
   JSON round-trip validation rejects unsafe constructed/copied nonfinite data;
   exact dimensions, unique keys, bounded expansion, fiscal slots, graph cycles
   and four-level depth are checked before the kernel. Adversarial tests cover
   NaN/infinity, precision/bounds, identity drift, unknown components and cycles.
   **Verified fine for the stated mechanical contract**, not economic meaning.
4. Evidence loss and invented source provenance — every nested citation,
   including conflict alternatives, is hash/locator/quote checked. Kernel refs
   resolve to observation IDs or explicit issuance evidence. Tests reject
   tampered quotes, source hashes and unknown references. **By design:** numeric
   source resolution does not return all period/classification/disclosure
   context. The future output adapter must bind the review hash and preserve
   that context; raw kernel cells are not accepted report artifacts.
5. Silent expense/debt/perimeter changes — omitted COGS remains unknown;
   expenses-by-nature requires cited classification and rejects contradictory
   COGS. Principal, carrying, drawn and commitment are distinct; books cannot
   mix basis/currency/units/perimeters. **Verified fine** with explicit tests.
   Model finance-lease-inclusive debt still needs separate output reconciliation
   to CP-1 lease-exclusive debt. Foreign currency treatment remains a report gate.
6. Dynamic schedules and pro forma — missing segment/KPI/add-back periods
   remain null, rates are not averaged, incomplete add-back bridges block
   conversion. Event dates, supported targets and duplicate EBITDA/debt effects
   are checked. **Still open:** full readiness/reconciliations and analytical
   interpretation; tests here use explicitly synthetic evidence only.
7. Ordering, mutation and failure — these functions perform no IO or shared
   mutation. Frozen contracts and new tuples isolate callers. Invalid reviews
   raise before conversion. Stable diagnostics and facility order were compared
   against the pre-tournament implementation over 1,300 generated cases.
   **Verified fine** for this pure internal boundary. Journal integration is future work.

Fixed: sparse aggregate suppression and facility-wide issuance contradictions.
Verified fine: mechanical input/evidence/graph/dimension guards under the tested
cases; strict caller types and generated tournament equivalence.
By design: source observations are separate from calculations/judgments; missing
stays unknown; source quote matching is not analytical correctness.
Still open: required CP-1 T4/narrative tables, normalized/calculated/judgment
output categories, reconciliations, four-quarter Model readiness, immutable
output and report binding, CP-1A and live/native qualification.

## Key-area tournament

No-argument post-edit selection: only `period_issues` and `_facilities`, the
highest-risk graph and opening-balance/provenance symbols. Other new validation,
contracts and routine conversion functions receive tests and confidence review;
no blanket tournament, per the user's correction.

Five distinct fresh-context GPT-6.1 Sol/high roles followed the model matrix;
the coordinator route remained unchanged. Candidates A incumbent, B memory,
C speed and D readability were blinded for arbitration. No timing or memory
improvement is claimed. Period bracket C > B, D > C, D > A. Facility bracket
B > C, D > B, D > A. Coordinator backups and full bracket are retained locally
under ignored `artifacts/rewrite-financial/`.

Winner: **Snippet D (readability)** for both functions below.

Justification:

- Period validation computes the component set once and returns cached depths
  directly; graph outcomes are explicit tuple returns.
- Facility expansion states the last-dated-row preference and first insertion
  order, with one visible branch containing every condition for an inferred zero.
- Signatures, diagnostics, values and ordering remain unchanged; no new data
  structure or asymptotic complexity is introduced.

Final code (verified selected function bodies):

```python
def period_issues(periods: tuple[FinancialPeriod, ...]) -> tuple[str, ...]:
    """Validate a bounded, unique, acyclic component graph and fiscal slots."""
    index = {period.period_id: period for period in periods}
    if len(index) != len(periods):
        return ("Duplicate period identity",)
    issues: list[str] = []
    slots: set[tuple[str, int | None, int | None]] = set()
    for period in periods:
        components = set(period.component_period_ids)
        if len(components) != len(period.component_period_ids) or not components <= index.keys():
            issues.append(f"Duplicate or unknown period component: {period.period_id}")
        if period.period_type in {"QUARTER", "YTD", "FY"}:
            slot = (
                period.period_type,
                fiscal_year_number(period.fiscal_year),
                None if period.period_type == "FY" else period.fiscal_quarter,
            )
            if slot in slots:
                issues.append(f"Duplicate fiscal slot: {period.period_id}")
            slots.add(slot)
    if issues:
        return tuple(issues)
    active: set[str] = set()
    depths: dict[str, int] = {}

    def depth(period_id: str) -> int:
        if period_id in active:
            raise ValueError(f"Cyclic period components: {period_id}")
        if period_id in depths:
            return depths[period_id]
        active.add(period_id)
        depths[period_id] = 1 + max(
            (depth(part) for part in index[period_id].component_period_ids), default=0
        )
        active.remove(period_id)
        return depths[period_id]

    try:
        if max(depth(period_id) for period_id in index) > 4:
            return ("Period component nesting exceeds four levels",)
    except ValueError as error:
        return (str(error),)
    return ()

def _facilities(book: FinancialBook) -> tuple[FacilityRow, ...]:
    supplied = {(row.facility_id, row.period_id): row for row in book.facilities}
    templates = {row.facility_id: row for row in book.facilities}
    # Prefer the last dated row, retaining each facility's first insertion position.
    templates.update({row.facility_id: row for row in book.facilities if row.issued_on})
    periods = {period.period_id: period for period in book.periods}
    conflicted = {
        (row.facility_id, periods[row.period_id].end_date)
        for row in book.facilities
        if row.carrying_value.status == "conflicting"
    }
    result: list[FacilityRow] = []
    for period in book.periods:
        for facility_id, template in templates.items():
            supplied_row = supplied.get((facility_id, period.period_id))
            row = supplied_row or template
            carrying = row.carrying_value.amount if supplied_row else None
            source = _ref(row.carrying_value) if supplied_row else None
            if (facility_id, period.end_date) in conflicted:
                carrying = None
            elif (
                supplied_row is None
                and row.issued_on
                and period.end_date
                and row.issued_on > period.end_date
            ):
                carrying = Decimal(0)
                source = SourceRef(facility_id, f"facility-issuance:{book.book_id}", "0")
            result.append(
                _facility(row, period.period_id, supplied_row is not None, carrying, source)
            )
    return tuple(result)

```

Verification:

- `uv run --locked pytest tests/product/test_financials.py tests/product/model`
  — 274 passed in 6.07 seconds after selection.
- Coordinator generated differential checks (seed 8271): 1,000 period graphs
  and 300 facility cases equal to backups; local `verification.json` records counts.
- `make product-check` — lint/format, strict mypy (22 source files), JavaScript
  syntax and 356 product tests passed; 96.74% combined line/branch coverage.
- Impact set: `book_issues` calls `period_issues`; `kernel_registers` calls
  `_facilities`; direct boundary tests and internal kernel callers remain typed
  and passing. No indexed GitNexus graph exists for this project; references
  were inspected with `rg` and strict mypy used as the caller-contract check.

`make check` and `make secrets` passed, including directory, staged diff and
reachable-history secret scans. The coordinator inspected all candidate source
and test files and the staged changes before committing.

No dependencies changed. OpenRouter spend remains US$0; no live calls were made.
