# CP-1 source statements and independent equations

The internal `financial-review/1` input now includes full source statement lines,
source-supported component equations and disclosure assessments per statement and
period. `statement_report(pack, review, book_id)` produces the immutable
`financial-statements/1` projection for T4.4 income statements, T4.5 cash-flow
statements and T4.6 balance sheets. This advances milestone C; it does not complete
CP-1, Model readiness, analytical qualification or rendering acceptance.

Each line retains its stable line and item IDs, source label, source order,
period, detail/subtotal/total role and located Observation. The 65 required r14
items (19 income, 18 cash-flow, 28 balance-sheet) appear for every applicable
period, including explicit null gaps for omitted items. Income and cash-flow
statements exclude period-end-only records. Additional issuer detail uses an
`other:` item ID and remains visible; it is not truncated to template slots.
Stable definitions, unique priorities/items, same-date balance consistency and
explicit disclosure contradictions are checked before projection.

The report binds the prepared-pack and review hashes, run, issuer, as-of date,
book, perimeter, accounting basis, currency and scale. Every supplied cell retains
its observation ID, original source amount, normalized amount, status, citations
and limitation. A changed sign has a separate normalization reference. Canonical
Model outflow semantics use exact negative absolute values. Additional sign
normalization requires an explicit `outflow_magnitude` declaration and located
source evidence. Other signed values, including tax benefits, remain signed.
Neither currency nor scale is inferred or converted.

Exact semantic account links can fill an absent compact Model input. An explicit
missing/conflicting compact input stays unresolved. Known disagreements and
unresolved source conflicts cannot be hidden behind a known compact value.
Income-statement cash interest/tax are deliberately separate from cash-flow
cash-paid observations. Source rows also undergo the compact boundary's COGS
presentation, revolver and balance checks. This is an additive internal input
contract change: absent statement fields default empty but change the serialized
review hash. It is not a migration of previously accepted CP-1 artifacts.

## Independent source arithmetic

A `StatementIdentity` identifies a source subtotal/total and an ordered list of
source lines with exact integer +1/-1 coefficients, an explanation and located
citations. Boolean and floating-point coefficients are rejected. Components
must exist within the same period and statement. Cycles, duplicate references,
same-direction double-counting and identities without independent components
are rejected; explicit subtraction can remove a previously included component.
Nesting is bounded to twelve levels, including leaves, and both raw references
and cumulative expanded term paths are bounded to 20,000. Cached descendants
still count toward the depth of the path that reuses them.

Reconciliation recursively expands intermediate equations to original source
leaves. It never uses an intermediate reported subtotal as a balancing plug.
Each supplied equation also gets its own comparison, so a wrong reported subtotal
remains visible even if a parent's leaf sum is correct. Repeated opposite-signed
unknown leaves stay present and block arithmetic; cancellation cannot create a
known zero. Context retains equation and intermediate-target evidence, while
terms retain leaf observations and citations in deterministic order.

CFO identity can now pass when a complete source cash-flow disclosure supplies
an independent equation and all its operands reconcile. Missing components,
unassessed/partial disclosure or absent equations remain BLOCK with null
calculated values. Source equations use original signed amounts and explicit
coefficients; they do not silently apply the separate Model sign normalization.
The existing Decimal context, tolerance, difference and status rules are described
in [reconciliation](financial-reconciliation.md).

`validate_statement_report` recomputes the projection from the bound inputs.
Schema-valid cells or a supplied content hash alone are insufficient. Source
interpretation, equation meaning and disclosure completeness still require
analytical qualification; exact quote matching cannot prove them.

## Remaining integration

These APIs have no CLI/journal/render consumer yet. The full normalization,
constructed-period, calculation, gap/definition/conflict and narrative registers,
Model readiness and CP-1A are still pending. Candidate/cumulative HTML field
parity and public-case model qualification must follow actual integration. All
current statement evidence is deterministic and synthetic; no completed Module
or live analytical claim is made.
