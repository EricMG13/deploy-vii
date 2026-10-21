# Deterministic Model reuse

Selected 21 October 2026 against Deploy VI commit
`bd71346301b373afa72655916a4c1b42bf4c9823`, from clean Deploy VII base `9199be4`.
This is milestone C's internal arithmetic slice, not a completed CP-1 or Model
module. The validated financial, historical-period and Model output APIs now call it.
The journal retains internal calculations; candidate statement previews expose
source and constructed periods. Complete Model/CP-1 delivery is still pending.

The selected eight modules are `_cells`, `frame`, `registers`, `periods`,
`history`, `debt`, `statements` and `metrics`. Only three date functions and
their regular expressions come from `reader`. The [source manifest](../review-evidence/model-port-sources.json)
records every original path and SHA-256, including the synthetic regression
fixtures. The original port adapted imports and formatting; later dated-period
corrections are explicitly recorded below.
Documentation now describes finite precision accurately. The old table parser,
assembly/layout, projections, workbook, state, host policy and qualification
receipts are not included.

## Why this slice

The period-aware Decimal model retains component lineage, missing reasons,
quarter/FY/YTD/LTM distinctions and separately reported versus computed figures.
The older float-based credit-metrics helper lacks these boundaries. Porting only
ratio formulas would lose their period and statement semantics. The selected
closure uses only the Python standard library and itself; no old project code
is imported at runtime. Pinned CP-1 runbook and step references were reviewed
alongside the calculations. This source inspection is not a legal license audit.

The calculation context is 38 significant digits, half-even, with invalid
operations, division by zero and overflow trapped. It performs no display
quantization; divisions and sufficiently large calculations can still round.
Ratios marked PERCENT are fractions: 0.08 means 8%. A non-positive denominator
is missing with a reason, never infinity. Expense sign normalization is explicit.

## Required integration boundaries

The [validated financial input boundary](financial-inputs.md) now implements the
source-contract, sparse-row, presentation, issuance and same-date checks below.
Output reconciliation, readiness and report binding remain release conditions; a
passing legacy regression suite does not prove those conditions. The raw dataclasses are internal and
are not a safe model-response input contract.

| Boundary | Observed behavior | Required Deploy VII treatment |
| --- | --- | --- |
| Numbers and graphs | Kernel trusts typed rows; old reader enforced size, precision, uniqueness and acyclic bounded component graphs | New strict contract must check finite bounded Decimals, period identity/dates/spans, duplicates, references, graph depth and units before computation. |
| Evidence | `SourceRef` preserves source label, locator and original cell text, without a content hash | Bind every sourced value to the current frozen pack's hash and exact quote. Retain missing/conflicting alternatives and calculation inputs separately. |
| Sparse rows | Missing add-back or financing rows can contribute nothing; explicit null is missing | Materialize unknown rows as null. Permit zero only with source-backed evidence of absence; do not infer it from omission. Complete disclosure assessments must be explicit. |
| Expense presentation | An absent COGS row selects expenses-by-nature handling | Require an explicit sourced presentation classification; an unextracted COGS row cannot select this branch. |
| Opening facilities | A facility first observed after an opening date can be treated as newly issued | Require dated issuance evidence or an explicit unknown opening row; observation date alone cannot establish zero. |
| Same-date balances | First known balance wins across periods at the same end date | Reject unresolved disagreement or retain it as a conflict before this conversion. Null in one representation is not evidence of a conflicting known value. |
| Debt basis | Model total debt includes finance leases; CP-1 total debt excludes both lease types | Preserve separately named bases and their reconciliation. Never overwrite canonical CP-1 debt with the Model subtotal. Foreign facilities remain visibly excluded without an explicit conversion. |
| Pro forma | A facility without a historical balance can start at zero; EBITDA adjustments also affect adjusted EBITDA | Require explicit opening basis and event/effective-date evidence. Retain post-balance-sheet effects separately and detect duplicate EBITDA/adjusted-EBITDA effects. |
| House adjustments | Optional exclusion of unrealized positive add-backs preserves deductions | Keep the stated result and an explicitly selected house variant. Do not silently adopt the historical owner's setting. |
| Residuals | Other operating/financing/cash and debt non-cash figures reconcile arithmetic | Label as calculated residuals, never sourced facts or evidence of what caused a movement. |

The integration must also retain issuer/perimeter, as-of date, currency/scale,
source/normalized/calculated/judgment categories, all required CP-1 tables and
reconciliations, downstream readiness, and the four-complete-quarter Model
readiness condition. The subsequent source, period, statement and
[historical readiness](model-readiness.md) layers implement those named
boundaries; complete registers, other consumer readiness and delivery remain open.

## Evidence scope

219 synthetic kernel regressions pass, including Hypothesis flow/period and
sign properties. The fixture is invented Example Gaming Co, not the public
Caesars case. Imported tests establish preservation of selected behavior;
they are not independent analytical qualification. Matching old assembly tests
were excluded because assembly/layout was not selected. No new public module
output exists, so no completed-module browser or analytical acceptance is claimed.

The original port changed imports, documentation and formatting only.
Subsequent period integration adapts `_calculated_quarters` and `_host_ltm`
to reject mismatched stub subtraction, preserve component-owned LTM dates and
require a proven twelve-month span. See [period integration](financial-periods.md)
and tasks/implementation/period-review.md for reproduced cases and verification.
Historical Model output also validates four-quarter rolling spans in `history`
and supplies rolling metadata to statement assembly; see [Model output](model-output.md)
and tasks/implementation/model-output-review.md. Per the user's
key-area tournament limit and the skill's vendored/mechanical exclusion, no
tournament is run over unchanged imported algorithms. New calculation or
provenance logic will receive the scoped tournament and confidence review.

The next historical output increment adds keyword-only arithmetic/provenance
metadata to internal Cells without changing numeric equality or positional calls.
Sums, debt subtotals and working-capital days ratios retain their actual inputs.
Net income joins the controlled flows, with EBIT/net-income margins and reported
EBITDA growth added from the r14 canonical list. See
[arithmetic trace review](tasks/implementation/computation-review.md). The original
source manifest remains a record of the imported base, not a claim that current
files match their original hashes.

The separate [canonical KPI register](canonical-kpis.md) now preserves CP-1
carrying debt excluding both lease types and source-first reported/adjusted
earnings. Its rolling totals sum the selected canonical quarters; they never
replace a reported quarter with an aggregate recalculation. Source evidence and
the then-unresolved DCF/FFO coverage definitions are recorded in that increment's review
(closed by M1 on 21 October 2026: [canonical KPI register](canonical-kpis.md)).

Full statement-line construction now reuses the selected period plan and
arithmetic graph without applying the complete-addback Model gate to unrelated
statements. The shared `_component` reader recursively requires nested YTD/FY
inputs; a reproduced one-level subtotal plug is corrected. See
[statement history](statement-history.md) and its review. No additional Deploy VI
source or host policy was imported, and the original source manifest is unchanged.
