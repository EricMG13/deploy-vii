# Source-register reconciliation review

Scope: `financial_reconciliation.py`, 16 synthetic tests and usage documentation,
on clean base `ab3091e`. No existing kernel algorithm was changed. The pinned
r14 CP-1 steps, account/debt/segment conventions and reconciliation/readiness
section were read before implementation. This is milestone C internal work;
it is not completed CP-1, Model or CP-1A acceptance.

## Confidence review

Least confident about (ranked):

1. Circular cash-flow evidence — traced the kernel waterfall: its Other residual
   is computed using reported CFO, so recomputing CFO with that residual proves
   construction only. **By design:** CFO_IDENTITY explicitly BLOCKs with a null
   calculation until full source operating components are represented. The
   test verifies this even when every implemented comparison passes.
2. Unknown observations losing evidence — reproduced a missing carrying value
   that became anonymous `Not supplied`, losing its observation ID and quote.
   Cash selection had the same fallthrough. **Confirmed bug, fixed:** conflict
   wins, otherwise first known, otherwise first actual missing observation.
   A regression checks both original missing IDs and their citations.
3. Debt exclusion without classification provenance — the lease filter ran
   before terms citations were collected. **Confirmed bug, fixed:** retain
   same-date terms evidence before excluding either lease class. The regression
   supplies a unique lease-classification quote and checks it survives.
4. Wrong debt basis or currency addition — inspected each inclusion condition;
   both lease types are excluded, debt adjustments override that exclusion,
   and only carrying values enter. Foreign relevant facilities force a null
   reconciled total, not a converted or incomplete sum. **Verified fine:** test
   proves 100 less a 3 cost adjustment equals 97 despite principal 105 and
   commitment 150, plus foreign-currency blocking and retained lease evidence.
5. Numeric precision, signs and hidden differences — arithmetic remains under
   the shared 38-digit context; exact copy/negate avoids ambient-context rounding
   during sign normalization. **Verified fine:** a precision-four host context
   produces the same report; inclusive tolerance retains a nonzero difference;
   an amount just outside tolerance blocks. Source interpretation of the
   submitted reporting precision remains an analytical obligation.
6. Empty/partial schedules and span assumptions — missing components never sum,
   an undisclosed segment schedule warns with null rather than zero, a disclosed
   partial schedule blocks, and each add-back ID remains separate, including
   negative deductions. FY needs four dated contiguous quarters spanning exactly
   the FY; audited differences are not silently waived. **Verified fine** for
   the supplied-period checks; derived-period reconciliation remains open.
7. Forged statuses or stale identity — reports are immutable contracts bound to
   the source/review hashes and dimensions. Schema validity is insufficient;
   `validate_reconciliation_report` reruns the deterministic checks and compares
   the serialized content hash. **Verified fine:** tests alter check status,
   difference, identity, inputs, book and nonfinite values; each is refused.
8. Ordering, exceptions and concurrency — functions have no IO or shared mutable
   state. The tournament preserves component/citation order, conflict/known/null
   precedence, exact Decimal serialization and exceptions. Coordinator-generated
   comparisons and strict caller typing are recorded below.

Fixed: missing-observation provenance and lease-exclusion evidence.
Verified fine: the listed mechanical cases, including nonzero differences,
unknowns, carrying-value basis, complete-quarter spans and artifact recomputation.
By design: no readiness/promotion decision; incomplete independent CFO components
block; no inferred FX, issuance or audited-basis exception.
Still open: full statement coverage, normalization and derived output registers,
source-backed explanations/adjustments, final Model assembly/readiness, CP-1A,
immutable Module/report integration, live analytical and native-host qualification.

## Verification

Initial `make product-check`: 372 passed in 24.01 seconds, 96.94% combined
line/branch coverage; strict mypy checks 23 source files, lint/format and JS syntax
passed. Final post-tournament verification is recorded below.

## Key-area post-edit tournament

Only `_check` (financial arithmetic/status/provenance) and `_debt` (carrying-value
selection/provenance) were selected. Other new helpers and routine conversion
receive focused tests and confidence review. No blanket tournament. Five distinct
roles used the requested GPT-6.1 Sol/high route; coordinator unchanged.

Winner: **Snippet D** replaces `_check`; **Snippet B** replaces `_debt` in
`src/deploy_vii/financial_reconciliation.py` (final bodies below).

Justification:

- D makes the complete-input gate explicit, retaining the original Decimal sum,
  context, status precedence, hash and citation ordering.
- B groups same-date observations and citations once, removing the per-facility
  full-row scan while preserving first-conflict/known/missing selection.
- Both preserve the callers' contracts and exact serialized output in coordinator
  comparisons; B uses extra index storage for a better time-complexity bound.
  No measured runtime or memory improvement is claimed.

Blind bracket: `_check`: B > C, D > B, D > A. `_debt`: B > C, B > D, B > A.
A incumbent, B speed, C memory, D readability. Backups, full three-bullet-per-match
arbitration and candidates remain local under `artifacts/rewrite-reconciliation/`.

Final code:

```python
def _check(
    period: FinancialPeriod,
    kind: CheckType,
    metric: str,
    reported: ReconciliationTerm,
    components: tuple[ReconciliationTerm, ...],
    formula: str,
    *,
    blocker: str | None = None,
    warning: str | None = None,
    context: tuple[Citation, ...] = (),
) -> Reconciliation:
    """Calculate only complete components; never change a difference to fit tolerance."""
    with localcontext(CONTEXT):
        calculated: Decimal | None = None
        if components and all(term.amount is not None for term in components):
            calculated = sum(
                (term.amount * term.coefficient for term in components if term.amount is not None),
                Decimal(0),
            )
        # A structural blocker makes even a numeric subtotal incomplete.
        if blocker:
            calculated = None
        stated = reported.amount
        tolerance = (
            None if stated is None else Decimal("0.5").scaleb(int(stated.as_tuple().exponent))
        )
        difference = None if stated is None or calculated is None else calculated - stated
        status: Literal["PASS", "WARN", "BLOCK"] = "BLOCK"
        explanation = blocker or "Missing reported value or complete independent components"
        if difference is not None and tolerance is not None:
            if abs(difference) <= tolerance:
                status, explanation = "PASS", "Agrees within half the last reported decimal place"
            else:
                explanation = "Difference exceeds reporting-precision tolerance; unresolved"
        if warning and not blocker:
            status, explanation = "WARN", warning
    identity = json.dumps((period.period_id, kind, metric), separators=(",", ":"))
    return Reconciliation(
        check_id="recon:" + hashlib.sha256(identity.encode()).hexdigest(),
        period_id=period.period_id,
        check_type=kind,
        metric_id=metric,
        reported=reported,
        components=components,
        reported_value=stated,
        calculated_value=calculated,
        difference=difference,
        tolerance=tolerance,
        status=status,
        formula=formula,
        explanation=explanation,
        context_citations=tuple(dict.fromkeys((*period.citations, *context))),
    )

def _debt(book: FinancialBook, period: FinancialPeriod) -> Reconciliation:
    """Use same-date carrying values, excluding both lease classes; no FX inference."""
    ids = {p.period_id for p in book.periods if period.end_date and p.end_date == period.end_date}
    templates = {r.facility_id: r for r in book.facilities}
    values_by_id: dict[str, list[Observation]] = {}
    citations_by_id: dict[str, list[Citation]] = {}
    for row in book.facilities:
        if row.period_id in ids:
            values_by_id.setdefault(row.facility_id, []).append(row.carrying_value)
            citations_by_id.setdefault(row.facility_id, []).extend(row.terms_citations)
    terms: list[ReconciliationTerm] = []
    context: list[Citation] = []
    blockers: list[str] = []
    for fid, template in templates.items():
        context.extend(citations_by_id.get(fid, ()))
        if template.facility_type != "DEBT ADJUSTMENT" and template.lease_classification in {
            "OPERATING_LEASE",
            "FINANCE_LEASE",
        }:
            continue
        values = values_by_id.get(fid, [])
        value = next((v for v in values if v.status == "conflicting"), None)
        value = value or next((v for v in values if v.amount is not None), next(iter(values), None))
        if template.currency != book.currency:
            blockers.append(f"{fid}: foreign currency has no explicit conversion")
        terms.append(_term(fid, value))
    return _check(
        period,
        "DEBT_TOTAL_EX_LEASES",
        "total_debt",
        _balance(book, period.end_date, "total_debt"),
        tuple(terms),
        "sum(non-lease carrying values, including separately sourced debt adjustments)",
        blocker="; ".join(blockers) or None,
        context=tuple(context),
    )

```

Coordinator verification:

- `uv run --locked pytest tests/product/test_reconciliation.py tests/product/test_financials.py`
  — 71 passed in 0.29 seconds after applying both selected functions.
- `uv run --locked python -c "import runpy; runpy.run_path('artifacts/rewrite-reconciliation/verify.py', run_name='__main__')"`
  — seed 20261021, 1,200 `_check` and 400 `_debt` cases match the backed-up
  incumbent's serialized results/exceptions. Includes missing/zero/conflicting
  observations, same-date aliases, unknown dates, foreign/lease classifications,
  changed ambient precision and warning/blocker precedence. The scratch harness
  first needed import-path and shared-contract-class fixes; these were harness
  errors, not changes to production behavior.
- Actual post-selection diff inspected: only the selected function bodies changed
  relative to the coordinator backup.
- Impact set: `_segments`, `_income`, `_debt`, `_cash`, `_year` call `_check`;
  `reconcile_financials` calls `_debt`, and the regeneration validator consumes
  that report. `rg` reference inspection and strict mypy (23 source files) pass.

Final `make product-check` after selection: **372 passed in 23.75 seconds**,
**96.95%** combined line/branch coverage. Product lint/format, strict typing
and JavaScript syntax also passed.

`make check` and `make secrets` passed (directory, staged diff and all reachable
history); the coordinator inspected the complete staged source/test changes.

OpenRouter spend remains US$0. No dependencies changed or live calls made.
