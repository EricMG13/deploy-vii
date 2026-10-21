# CP-1 source audit registers

`canonical_audit(pack, financial_review, definition_review)` returns the immutable
`canonical-audit/1` report. `DefinitionReview` (`definition-review/1`) binds the
exact financial-review hash and one book. The report embeds the current statement
and reconciliation artifacts, which bind run, issuer, as-of date, method, source
pack, financial review and canonical dimensions. It is an internal source-stage
API; it does not grant Module acceptance or downstream readiness.

The report supplies:

- Original observation positions across accounts, add-backs, segments, operating
  KPIs, facilities, pro-forma events and statement lines. Every value retains its
  field, period, unit, currency, status, original citations and conflicting
  alternatives. Rates and operating KPI units are not labelled monetary amounts.
- Normalization rows for actual canonical sign changes, with original and final
  values, period, rationale and source/sign evidence. Statement rows retain their
  existing normalization IDs. Compact accounts have their own stable IDs. Source
  values remain unchanged. There is no inferred FX, unit or perimeter conversion.
- Definition assessments scoped to explicit observation IDs, including canonical
  and issuer definitions, materiality, downstream impact and recommendation.
  These are analyst judgements; their text cannot change Python formulas or
  settle source values. An observation cannot receive conflicting duplicate
  assessments. Unknown or cross-book references and stale hashes are rejected.
- Automatic rows for unresolved source alternatives and every known unequal
  carrying-value/gross-principal pair. Both figures and their roles are retained.
  Equal amounts do not create a divergence; missing amounts stay explicit gaps.
  A separate alignment assessment cannot suppress a debt-basis row.
- Multi-figure event rows retaining every supplied figure and its statement role,
  explanation, citations and downstream impact. Values are referenced directly
  from the original observations, never copied into model-authored numeric fields
  or combined across different accounting meanings.
- A source-stage gap ledger covering unsettled observations (including explicit
  not-applicable reasons), missing required statement items, every non-PASS source
  reconciliation, definition differences and unassessed observations, period
  limitations, unknown facility terms, disclosure limitations and supplied review
  limitations. Gaps retain affected periods and evidence where available.

An empty definition review means **unassessed**, never "no conflicts identified."
Even when all supplied observations have an assessment, completeness of extracted
metrics, source definitions and multi-figure events requires analytical review.
No global alignment statement is generated automatically. Source-stage WARN/BLOCK
records neither waive numeric failures nor modify the separate Model gate.

`validate_canonical_audit(pack, financial_review, definition_review, report)`
recomputes the entire report from the externally supplied inputs and compares its
content hash. It does not trust the report's embedded definition review as the
expected input. Missing rows, reordered/replaced values, altered evidence and
substituted assessments are detectable.

This increment implements source-stage portions of r14 T4.3, T4.11 and T4.12.
Derived-period/KPI gaps, source-tier/entity metadata, the evidence → risk → credit
narrative, full consumer readiness, execution binding and Workbench fields remain
required work. No complete CP-1 delivery or analytical qualification is claimed.

Method source: Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`, CP-1 reference
Steps 03 (normalization), 10 (definition conflicts, multi-figure events, carrying
versus principal), 12 (cumulative gaps), and the four-category separation discipline.
The local reference bundle is `artifacts/cp1-steps-reference.md`; no Deploy VI code,
policies or source packs are copied into this implementation.

Review evidence: [source audit review](tasks/implementation/canonical-audit-review.md).
