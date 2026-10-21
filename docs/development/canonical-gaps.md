# Cumulative CP-1 gaps

`canonical_gaps(pack, context_review, financial_review, definition_review, binding)`
returns `canonical-gaps/1` for the definition review's financial book. It recomputes
and embeds source context, canonical source audit, historical/KPI output and period
reconciliation from explicit external inputs. The original register artifacts
retain run, issuer, as-of, method, source/review hashes and financial dimensions.

The cumulative ledger includes every implemented source-context and audit gap,
missing historical adapter input, historical value and construction operand,
canonical value and KPI, unassessed KPI evidence tier, non-PASS period check,
construction/basis limitation and originating artifact limitation. Known numerical
zero remains known. Optional absent comparison values and non-ratio denominator
objects are not missing numerical observations. DCF, DCF/debt and FFO interest
coverage are defined in the [canonical KPI register](canonical-kpis.md), so no KPI
gap cites a missing definition.

Every gap retains origin, artifact hash, original reference, affected metric when
applicable, explicit period kind/identity/dates, severity, downstream impact,
recommended action and available evidence. The embedded artifact is authoritative
for its complete original row, signs, alternatives and operand roles. Derived
operand gaps retain both result and actual input scopes; KPI gaps include both
display and actual operand bases. Period/source/basis namespaces are distinct.
The source audit applies r14's explicit optional facility-term null exceptions
(`canonical-audit/2`), while retaining conflicting terms and unknown amortisation.
Exact duplicate details are deduplicated in order; equal text with different
origins, references, periods or evidence remains separate. IDs hash the complete
detail and book identity.

Source-context output is now `source-context/2`: each context gap carries explicit
`scope_ids`. Input `source-context-review/1` is unchanged. Scope dates are never
inferred by matching a generic reference string, because source/entity/scope IDs
can coincide. Subsequent-event scope warnings retain the reporting scope; event
dates and descriptions remain in the context artifact.

Structurally valid binding failures are retained as BLOCK rows alongside the
source registers. Schema-invalid inputs raise. Calculation generation is a
separate state: an incomplete add-back disclosure rejected by the existing
adapter produces a blocked calculation stage and an explicit gap, with no
invented KPI or period-check artifact. Subsequent unexpected computation errors
propagate. Generated calculations never clear binding failures or confer consumer
readiness.

`validate_canonical_gaps` reconstructs the expected report from all five external
inputs. Embedded output data does not define the expected inputs. Deleted gaps,
changed severity/evidence, stale schemas and substituted reviews are detectable.

This implements the cumulative ledger over the current mechanical registers,
advancing pinned r14 CP-1 T4.12. Analytical narrative gaps and full downstream
readiness must join it when implemented. A generated ledger is not a completed
CP-1 Module, analytical qualification or browser acceptance.

Method: Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`, r14 CP-1 Step 12
and the model-interface missing-value rules. No Deploy VI code or policies were
imported. [Review evidence](tasks/implementation/canonical-gaps-review.md).
