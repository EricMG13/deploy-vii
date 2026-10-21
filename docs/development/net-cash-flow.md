# Independent net cash flow reconciliation

`NCF_IDENTITY` implements r14 CP-1 Step 7's operating + investing + financing
cross-check. It complements `NCF_CASH_MOVEMENT`, which compares NCF with cash
balances and explicit source adjustments. Agreement with the balance sheet does
not establish that the cash-flow statement is complete.

The source CFS must have a reported `net_cash_change` line and a cited
`StatementIdentity` whose direct components include all three source categories:
`cfo_ncfo`, `investing_cash_flow` and `financing_cash_flow`. These components must
be subtotals or totals. An explicitly included `fx_cash_effect` is permitted;
its presence elsewhere in the statement does not add it to NCF. Other balancing
details cannot replace or supplement these categories. Map an issuer's categories
to the controlled meanings using source evidence; unresolved mappings remain gaps.

All source equations use original printed amounts and their explicit +1/-1
coefficients. Nested equations expand to source leaves. Every reachable nested
equation is also checked against its own reported target, so incorrect investing
and financing subtotals cannot offset each other beneath an agreeing parent.
Where no nested equation is supplied, the located reported component remains a
source operand. The separate mandatory CFO check still requires its own equation.

If reported NCF is explicitly presented as an outflow magnitude, Python converts
the completed equation to the canonical negative sign. It does not normalize
each printed leaf a second time. Original amounts, final coefficients, observation
IDs, root/intermediate equation citations and target sign evidence remain retained.
Arithmetic uses the existing Decimal context and reporting-precision tolerance.
Known root mismatches retain their difference; missing structure, source targets,
operands or complete disclosure cannot produce a numeric pass.

Constructed quarters and LTM use signed combinations of those independent source
equations. Each contributing source check must PASS before a constructed numeric
comparison is available. Equal source errors and opposite-signed unknown operands
cannot cancel into acceptance. Period limits and the original source plan remain
visible. No Model residual is used as independent evidence.

Historical CP-MODEL readiness now requires `NCF_IDENTITY` for every selected
quarter alongside the previous six check types. Older fixtures without CFS
component equations are insufficient evidence, even if their cash balances agree.
This is a deterministic input requirement, not analytical or Module acceptance.
Source interpretation, issuer-specific classifications and remaining cross-statement
checks still require work. Current evidence is synthetic; no live call was made.

Source and period reconciliation versions are now `financial-reconciliation/4`
and `period-reconciliation/4`; historical readiness is `model-readiness/2`.
The input remains `financial-review/3`: existing statement contracts represent
the equations. Regenerate dependent reports and readiness decisions from frozen
inputs; explicit older output versions are rejected rather than relabelled.

Reviewed requirement: Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`,
`reference/deploy-v-r14/skills/cp-1-canonical-data-foundation/references/REF_CP-1_STEPS.md`,
Step 7 (lines 132–149), SHA-256
`e9552f0d2b128cbe27ec58cdc2360e0e67c96a9f6ec21a140854f310de201bc1`.
No Deploy VI code or policies are copied.

Review: [increment evidence](tasks/implementation/net-cash-flow-review.md).
