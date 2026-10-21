# Facility FX normalization

`FacilityFxConversion` binds a cited period-end spot quote to the complete original
facility row hash, facility/period IDs, exact period end and currency pair. The rate
means **book-currency units per source-currency unit**. The source facility's money
fields use the book's declared scale; this increment converts currency, not scale.
Inverse, average, inferred or undated rates are not accepted. The original review
and its source observations remain unchanged.

Python converts carrying value, principal, drawn amount, commitment and annual
amortisation under Decimal precision 38, half-even. Coupons, spreads, floors and
classifications remain unchanged. Principal never substitutes for carrying value.
Every foreign row has five normalization records, including null results. Records
retain original and target currency, scale, original amount, rate/date, input
observation IDs, source-row hash, formula, citations and any missing reason. IDs
bind the full facility, period and conversion evidence, including same-date alias
inputs. A rate of one still produces a normalized value, never a reported value.

Duplicate/stale bindings, wrong currencies, nonpositive known rates and divergent
known same-date quotes fail validation. Conflicting source amounts or FX rates
propagate across every same-date alias; a known alias cannot hide a conflict.
An individually missing quote does not erase a separately supported same-date
conversion. Missing source amounts or conversions stay null, including a source
zero without a conversion. A separately sourced pre-issuance zero remains valid.
Validation bounds expanded alias evidence to one million input references before
materialization; normal source-register limits also apply.

The Model adapter emits facility amounts in the book currency, including unknown
amounts when conversion is unavailable. It points to normalization records rather
than representing converted amounts as original observations. Historical and Model
artifacts, actual calculation traces, source/period reconciliations and the audit
retain these records and original inputs. FX-specific gaps retain citations and
reasons in the cumulative ledger. The source-context boundary sees original rate
observations with unit `target per source`; it still requires explicit source
context and does not infer external market-source suitability.

CP-1 canonical debt continues to use the independently reported non-lease debt
account. Source and constructed-period checks compare that account with converted
carrying values excluding both lease classes. The Model's debt aggregate includes
finance leases, as before. A missing FX conversion can therefore leave a reported
CP-1 debt figure available while blocking reconciliation and selected historical
Model readiness. Neither calculation nor reconciliation proves analytical quality.

Input contract is `financial-review/5`; affected reports are
`financial-periods/2`, `financial-model/3`, `canonical-kpis/2`,
`financial-reconciliation/6`, `period-reconciliation/5`, and `canonical-audit/3`.
External report validation recomputes from the original frozen pack and review;
editing a converted result or binding invalidates the artifact.

Synthetic verification and scoped reviews are recorded in
[the increment review](tasks/implementation/facility-fx-review.md). This is an
internal CP-1/Model increment. Source-first execution, canonical Markdown/Workbench
delivery, CP-1A and live financial qualification remain separate work.
