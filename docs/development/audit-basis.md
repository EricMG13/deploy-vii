# Sourced annual audit-basis differences

The pinned r14 Model interface permits a reported FY versus quarterly-sum
difference to remain WARN when the audited and unaudited bases differ and the
explanation is explicit. Deploy VII now represents that explanation without
changing the source amounts, signed components, calculated total, tolerance or
unrounded difference.

`FinancialBook.audit_basis_explanations` contains `AuditBasisExplanation` records.
Each has a unique ID, one annual period, one controlled flow metric, four ordered
quarter period IDs, the content hashes of the five compared source observations,
an explanation and located citations. Generate those fingerprints only after the
source observations and their citations are frozen. Updating a value, status or
citation requires a fresh explanation binding; old hashes fail validation.

The FY must be explicitly `AUDITED` and the four independently reported quarters
`UNAUDITED` (case and surrounding whitespace are normalized). The quarters must
be Q1–Q4 of the same fiscal year, contiguous and exactly span the FY. Component-
period constructions cannot be presented as independent reported quarters.
Duplicate IDs/targets, unknown periods, unsupported metrics, stale observations
and unlocated explanations are rejected by the common financial input boundary.
Quote matching checks location, not the analytical truth of the explanation.

Both source-register and constructed-period annual comparisons use the same
eligibility selector. A valid record produces WARN only when the exact comparison
has a known difference exceeding tolerance. Missing or conflicting inputs,
structural failures, constructed quarters and shared-source comparisons do not
gain an audit exception. Agreement within tolerance stays PASS. There is no
blanket FY waiver: other metrics, source identities, debt and cash checks retain
their own outcomes. No FX adjustment or unexplained difference is absorbed.

The applied record and its citations are retained on the check. Historical Model
readiness consumes the resulting WARN through its existing mandatory-check rules;
all other readiness conditions still apply. This does not confer analytical,
Module, rendering or native-host acceptance.

## Versions and migration

Inputs now use `financial-review/2`; source and period reconciliation artifacts
use `financial-reconciliation/2` and `period-reconciliation/2`. Explicit version-1
payloads are rejected, not silently reinterpreted. Rebuild source reviews under
the new contract and regenerate dependent artifacts from the frozen pack; do not
edit saved hashes or relabel accepted outputs. With no explanation records, the
existing numeric and severity behavior is preserved. Other output schemas retain
their existing shape and bind the new review hash or nested versioned reports.

Reviewed source: Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`,
`reference/deploy-v-r14/skills/cp-1-canonical-data-foundation/references/REF_CP-1_STEPS.md`,
Reconciliation and readiness (lines 556–562). SHA-256:
`e9552f0d2b128cbe27ec58cdc2360e0e67c96a9f6ec21a140854f310de201bc1`.
No Deploy VI code or policies were copied.

Review evidence: [increment review](tasks/implementation/audit-basis-review.md).
