# Source-backed cash movement reconciliation

`FinancialBook.cash_movement_bridges` records explicitly assessed cash-flow
reporting conventions. Each bridge states:

```text
closing canonical cash − opening canonical cash
  = reported net cash change + Σ(coefficient × source adjustment)
```

The bridge contains a unique ID, one flow period, an explanation, located
citations and signed references to source CFS detail lines in that period.
It accepts no numeric adjustment or calculated balancing figure. Permitted lines
are `fx_cash_effect` or issuer-specific `other:` detail, such as a sourced cash
perimeter movement. The classification and the relationship to canonical cash
must be explained in the cited evidence; a generic `other:` identifier alone is
not analytical proof. Canonical cash-flow items, subtotals, identity targets,
duplicate references and cross-period references are rejected.

An empty component tuple explicitly assesses that no adjustment is needed.
Merely supplying an FX line never activates an adjustment: some statements
already include FX in their reported net cash change. With no bridge, the
existing closing-minus-opening comparison remains unchanged. Missing or
conflicting source adjustments remain unknown, never zero.

Python compares reported NCF with cash delta less the signed adjustments, using
the existing 38-digit half-even Decimal context and reporting-precision tolerance.
Original amounts, normalized outflow signs, comparison coefficients, observation
IDs and citations remain visible. The bridge record and its explanation accompany
the check. A known residual difference still blocks; this is not a warning waiver.

Constructed quarters and LTM follow the historical flow plan to combine the same
source adjustments with the appropriate signs. Once any contributing period has
a bridge, every contributing period needs an explicit assessment, including
cited empty assessments where appropriate. Every contributing source cash check
must pass. Missing operands and equal source errors cannot disappear by subtraction.
The constructed check still uses its actual opening and closing cash balances.
Unadjusted comparisons retain their existing boundary behavior.

Historical Model readiness consumes these checks without weakening its other
conditions. This is an internal deterministic API, not completed CP-1 delivery.
It does not supply debt FX conversion, infer restricted-cash balances, implement
new Model cash forecasts or prove that the analytical classification is correct.
Independent [operating/investing/financing-to-NCF checking](net-cash-flow.md)
is now implemented separately from this cash-balance bridge. All new evidence is
explicitly synthetic; no
live model, module rendering or native-host qualification is claimed.

## Versions and provenance

This increment introduced `financial-review/3` and version 3 of both
reconciliation reports. The subsequent [NCF increment](net-cash-flow.md) keeps
the input version and advances the reports to version 4. Explicit older
versions are rejected. Rebuild reviews and regenerate dependent artifacts from
the frozen pack; do not relabel old artifacts. The review hash covers the bridge,
source amounts and citations. Both report validators recompute every result;
changing or deleting an assessment invalidates the old output.

Reviewed requirement: pinned Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`,
`reference/deploy-v-r14/skills/cp-1-canonical-data-foundation/references/REF_CP-1_STEPS.md`,
Step 5 and Step 7 (lines 90–107 and 132–149). SHA-256:
`e9552f0d2b128cbe27ec58cdc2360e0e67c96a9f6ec21a140854f310de201bc1`.
This is a new evidence-bound implementation; no Deploy VI code or policy was copied.

Review: [increment evidence](tasks/implementation/cash-movement-review.md).
