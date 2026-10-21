# CP-1 financial input boundary

The `financial-review/3` contract now preserves source observations in canonical
register sets and converts validated sets to the internal deterministic Model.
This is an internal API, not a completed CP-1 Module or a financial acceptance
decision. The CLI, execution journal and report adapter are not yet connected.

`FinancialReview` in `src/deploy_vii/financial_contracts.py` binds the prepared
pack hash, run, issuer, as-of date and r14 method. Each `FinancialBook` has one
entity perimeter, accounting basis, currency and scale. Multiple books keep
industrial/finance or other distinct perimeters separate. Every period repeats
those dimensions; mixing them inside a book is rejected, not converted silently.

The seven schedules retain periods, accounts, add-backs, segments, operating
KPIs, facilities and pro-forma events. Segment allocation binds driver slots
without merging presentation rows. Source values have stable observation IDs,
finite Decimals, exact hash/locator/quote citations and explicit known, missing,
conflicting or not-applicable states. Conflicts preserve located alternatives;
they cannot carry a settled amount. Principal, carrying value, commitment and
drawn amount remain distinct. Rate and amortisation fields have their own
observations and citations. No term is inferred from an instrument name.

These observations are the **source** category. Python's sign/date normalization
and calculated frames remain distinguishable from them, and model analysis is
stored separately as claims. The full normalized/calculated/judgment output
register and Calculation artifact binding still need implementation; do not
label the current input contract as the entire CP-1 deliverable.

## Validation and conversion

`validate_financial_review(pack, review)` in `financial_validation.py` revalidates
both serialized contracts, then checks identity, every nested citation (including
conflict alternatives), register keys, stable definitions, component graphs,
same-date balances, dimensions and event relationships. Period graphs have unique
references, no cycles and at most four levels. Source statement equations have
their own twelve-level bound and expansion limit. Dates/quarters/units are not
guessed. Known conflicting same-date balances require explicit resolution;
unresolved conflicts mask all same-date representations in the numeric adapter.

`kernel_registers(pack, review, book_id)` in `financial_adapter.py` repeats that
validation and selects exactly one book. Omitted leaf accounts, sparse financing
lines and repeating schedule observations become explicit unknown values. An
unreported aggregate with explicit component periods may be computed; every
component must still be known. An explicitly unresolved aggregate remains
unknown. A missing COGS observation cannot select expenses-by-nature handling;
that classification requires cited evidence, and contradictory COGS is rejected.

An absent facility row becomes zero only before an explicitly sourced issuance
date. The first observed row is not issuance evidence. An actual row, including
an actual missing row, takes precedence. Issuance dates must agree across the
facility's observations and cannot contradict earlier balances or the as-of
date. Incomplete or undisclosed add-back bridges block conversion rather than
silently becoming no adjustments. Explicitly undisclosed segments stay empty.

Pro-forma adjustments retain event IDs, announcement/effective dates and
completed/announced/proposed status. They apply outside the reported LTM and
do not rewrite historical values. Duplicate effects on EBITDA/adjusted EBITDA
or debt/individual facilities for the same event are rejected. Unknown adjustment
values are retained in the source review but cannot enter calculation.

Kernel `SourceRef` IDs refer to canonical observation IDs. `source_citations`
resolves them to the original quotations (or explicit issuance evidence), and
raises on unknown provenance rather than dropping it. Output adapters must bind
the review's content hash and retain period/classification/disclosure evidence
alongside these numeric references. The [historical-period artifact](financial-periods.md) now binds source inputs,
normalizations and period constructions. Raw kernel cells are not accepted
report artifacts. The raw kernel remains an internal dependency; use the
validated adapter for model-response data.

The [source-register reconciliation API](financial-reconciliation.md) now performs
independent comparisons where source components are available. The
[statement layer](statements.md) retains all required statement items, source
amounts and sign normalizations, and supplies independent CFO components. These
internal artifacts do not provide final readiness or report acceptance.

[Annual audit explanations](audit-basis.md) bind explicit audited-FY versus
unaudited-quarter differences to located evidence and the compared observation
hashes. Only the exact eligible annual check may become WARN; other failures stay
visible. [Cash movement bridges](cash-movement.md) now bind explicit source
adjustments to the cash balance comparison. Explicit older-version inputs must be
rebuilt and dependent outputs regenerated.

## Remaining milestone C work

- Complete all required CP-1 narrative and T4 tables, gap/definition/conflict
  registers, category distinctions and financial reconciliations.
- Assemble deterministic Model calculations and readiness, including four
  complete quarters, segment disclosure/completeness and mandatory checks.
- Retain the Model's finance-lease-inclusive debt separately from CP-1's
  lease-exclusive total, with explicit reconciliation and foreign-currency limits.
- Bind inputs and outputs to immutable execution, Calculation and Module
  artifacts; render candidate and cumulative accepted views and test field parity.
- Implement CP-1A and qualify the public case and native host separately.

Current evidence is deterministic synthetic testing only. Exact quote matching
does not prove that a number or classification was interpreted correctly.
No live model call or analytical qualification is claimed.
