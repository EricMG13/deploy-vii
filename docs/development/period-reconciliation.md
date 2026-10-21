# Reconciliation across historical constructions

`reconcile_periods(pack, review, book_id)` returns `period-reconciliation/2`.
It embeds the complete hash-bound historical report, including source and review
identity, currency/scale, original observations, period constructions and input
values. This adds comparisons over constructed quarters and LTM periods to the
existing supplied-period checks. It does not grant CP-MODEL readiness or complete
CP-1 delivery.

For every exposed historical column, checks compare:

- Consolidated revenue with the complete stable segment set. Genuine non-disclosure
  remains WARN with null; partial disclosure blocks.
- Reported EBITDA with independently supplied revenue, signed COGS where relevant,
  operating expenses and D&A. Unknown or mixed expense presentation blocks until
  an explicitly comparable bridge is supplied.
- Reported adjusted EBITDA with reported EBITDA and each stable add-back separately.
- Canonical debt with closing carrying values excluding both lease types, while
  retaining debt adjustments. Foreign currency has no inferred conversion.
- CFO with signed combinations of independent source-statement equation leaves.
  Every contributing source equation must be complete and free of an unresolved
  numeric difference. Equal source errors cannot cancel into acceptance. Missing
  period references remain explicit missing terms.
- Net cash change with closing less opening cash for the actual constructed span.
  An unexplained FX/other movement remains a difference; no Model residual proves it.

Reported FY is also compared with four dated, contiguous constructed quarters.
Separately stated flow figures on constructed FY/LTM periods remain separate
comparisons; they neither overwrite computed figures nor fill missing inputs.

Each check records the construction ID, metric, reported and component amounts,
signed coefficients, original observation IDs and citations, historical value IDs
where available, formula, tolerance, difference, status and explanation. Values
linked by ID retain their normalization metadata in the embedded historical report.
Arithmetic uses 38 significant digits, half-even, with half the reported amount's
last decimal place as tolerance. The difference is always retained unrounded.

The `independent` field means a numeric comparison has no shared observation IDs
between the reported term and components. It is a structural property, not proof
of source interpretation or analytical quality, and may be true for a mismatch.
If Q4 is FY minus nine months, summing quarters reuses FY: agreement is WARN with
the shared FY observation identified, never independent PASS. A mismatch still
blocks even when observations are shared. Unknown components never cancel to zero.

`validate_period_reconciliation` reconstructs the artifact from the frozen inputs
and compares its complete hash. Schema validity alone cannot authenticate a result.
No raw model-authored amount, PASS label or independent flag is trusted.

The API inherits the Model adapter's complete add-back disclosure requirement.
Partial reviews remain retainable as source artifacts. Exact-scope, sourced
[annual audit explanations](audit-basis.md) now permit eligible annual WARNs;
the [historical readiness gate](model-readiness.md) and
[canonical KPI register](canonical-kpis.md) are separate implemented layers.
Remaining work includes source-backed cash/FX treatment, explicit comparability
where presentation changes, pending KPI definitions, CP-1A and execution/Workbench
integration. No new module
analytical, rendering or native-host acceptance is claimed. Current evidence is
synthetic; live-model spend remains zero.

Review: [implementation review](tasks/implementation/period-reconciliation-review.md).
