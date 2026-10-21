# Cross-statement balance movements

CP-1 Step 7 now checks total equity for every source flow period:

`closing BS total equity = opening BS total equity + IS net income + signed sourced movements`

Both balances use the exact period-end dates: closing at the flow end, opening
one day before its start. Net income comes from that period's source income
statement, not the Model's residual or the cash-flow reconciliation's starting
figure. Same-date conflicting balances remain unknown even when another source
has a known amount. All located evidence remains available.

`BalanceMovement` records a stable movement ID, period, label, source observation
and role (distribution, capital transaction, OCI, perimeter, period flow or other).
Values are signed source amounts. Explicit outflow-magnitude normalization needs
its own source evidence and appears in the normalization register. Roles and
labels cannot change under the same stable ID. Nothing calculates an unexplained
movement to force agreement.

`BalanceMovementBridge` binds a source flow period, BS item and ordered movement
IDs to an explicit disclosure assessment. A complete empty bridge explicitly
states that no additional movements are required; omission is not zero. Partial,
unassessed or unavailable coverage cannot pass. Every supplied movement must be
assigned to a bridge. Duplicate bridges, duplicate/unknown references, unknown
periods and period-end-only scopes are rejected. Across bridges, expanded movement
references are limited to 20,000 before arithmetic.

Total-equity checks are emitted even without a bridge, retaining a BLOCK and null
calculated value. Additional source-backed bridges can compare other BS positions
with their period movements. They use opening balance plus the declared movements,
without automatically including net income. Existing cash-flow/NCF/cash-movement
checks remain separate. Absence of an additional bridge does not establish that
all other BS positions have been semantically reviewed.

Every comparison retains original and normalized terms, observation IDs, citations,
formula, reported/calculated amounts, the unrounded difference, reporting-precision
tolerance and the complete bridge assessment. Arithmetic uses the existing
38-significant-digit half-even Decimal context. Missing evidence is not a partial
sum. Materiality and completeness are analytical judgments; unexplained differences
remain blocking pending that review, never silently waived by Python.

Movement observations enter source audit, definition coverage and entity/context
binding. Non-PASS comparisons feed the cumulative gap ledger. Historical Model
readiness requires every balance-movement comparison on its selected source
operands, including null/structurally blocked checks. A derived quarter cannot
cancel a source YTD/FY failure. A separately reported FY unused by selected
quarters retains its gap without being misrepresented as a selected operand.

Input schema advances to `financial-review/4`, source reconciliation to
`financial-reconciliation/5` and historical Model readiness to `model-readiness/3`.
Recompute dependent artifacts against the new hashes; old input schemas are not
automatically accepted as reviewed bridge coverage. This is an internal milestone
C increment. Foreign-currency debt treatment, canonical delivery, CP-1A and live
analytical/rendering/native-host qualification remain outstanding.

[Review evidence](tasks/implementation/balance-movements-review.md).
