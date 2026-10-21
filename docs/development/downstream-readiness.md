# CP-1 downstream readiness

`downstream_inputs(pack, context, financial, definition, binding, narrative,
requested_consumers, quarter_ids=None)` recomputes the narrative/gap registers,
retains the full selected financial book and assesses historical Model inputs.
`DownstreamReview` binds that complete input hash. The canonical assembler and
external validator take the actual source contracts, narrative review, requested
entries, sufficiency review and quarter selection separately. An embedded report
cannot authorize a different request, review or selection.

This implements the Step 12 input-sufficiency matrix. It is an internal API;
canonical Markdown, execution and Workbench delivery remain to be connected.
A sufficiency row does not grant analytical qualification or complete a Module.

## Requested consumers and requirements

Each requested logical entry retains a row, including aliases. CP-4A keeps its
specific covenant-compliance requirement; CP-5A keeps its full-data-set requirement.
Other aliases inherit their physical module's Step 12 dependencies. Duplicate
requests, unknown entries and upstream CP-0/CP-1 requests are rejected.

The Step 12 map covers normalized financials/entity scope (CP-1B), financials/
period coverage (CP-1C), all KPIs/calculation register/FCF build (CP-2), cash flow/
liquidity (CP-2A), earnings quality (CP-2D), debt classification/capital structure
(CP-3), debt schedule/maturity (CP-3C), covenant metrics/EBITDA definitions (CP-4),
covenant compliance (CP-4A), structured data (CP-5) and full data set (CP-5A).
Other registered consumers require an explicitly labelled consumer-specific CP-1
sufficiency assessment. Their other module prerequisites remain governed by the
execution dependency graph; this matrix does not replace that graph.

A requirement is sufficient, limited or missing, with rationale, prior evidence
IDs and actions for incomplete inputs. Missing assessments remain explicit.
Evidence IDs must be distinct and current; applicable evidence families must
match the dependency. For example, a source/entity label cannot stand in for an
FCF calculation, and normalized financials need all three statement families.
Null numeric evidence cannot establish either sufficient or limited financial
support. A sufficient complete KPI dashboard also requires every dashboard value
to be available; one available KPI cannot hide unresolved definitions or other
missing calculations. Limited dashboard use remains possible with explicit actions.

These are mechanical minimums. Whether the cited periods, definitions, covenant
basis, maturity coverage or other evidence fully meet the consumer's intended
scope requires analytical review. The selected financial book retains complete
facility terms and source classifications alongside the prior catalogue. Python
does not infer materiality or semantic sufficiency from row presence alone.

## Gaps and statuses

Each consumer assesses the relevance of every cumulative narrative gap. A group
may share one rationale, but its IDs must be unique, known and disjoint from all
other groups for that consumer. Excluding a gap requires prior evidence and a
rationale. A relevant gap retains its original severity; source-context and
context-binding BLOCKs cannot be excluded. Other consumer-specific scope exclusions
remain analytical judgments, not resolutions of the underlying issue. Every gap
stays unchanged in the retained input report, regardless of relevance.

Python derives each status:

- `not_ready`: a required assessment is absent or missing, any gap is unassessed,
  or a relevant/source-integrity BLOCK remains.
- `ready_with_limitations`: coverage is complete but a dependency is limited or
  relevant warnings remain.
- `ready`: complete sufficient assessments and complete gap scoping leave no
  applicable block or limitation.

Rows retain requirements, gap assessments, blocking/relevant/unassessed IDs and
ordered, deduplicated actions. Missing assessments never disappear through an
empty list. A reviewer cannot supply an authoritative final status. All statuses
remain analytically unqualified until the separate model-assisted checks pass.

## Always-present CP-MODEL row

Exactly one workbook row is emitted even when the request is empty or omits
CP-MODEL. It derives from the independent historical Model readiness report and
source-integrity blocks; a model-authored consumer assessment cannot change it.
`ready` retains the existing selected-quarter completeness/reconciliation gate.
`partial` identifies incomplete quarter/input/tax coverage only when no other
blocking finding remains; it does not permit export. Other failures are `blocked`.
`not_applicable` is representable but never inferred from an omitted request or
missing data. The workbook exporter may accept only `ready`.

The row's scope remains selected historical quarters. Forecasts, pro forma,
rendered interface tables and workbook delivery require separate qualification.
Narrative omissions do not change historical calculation facts, and a financial
gap excluded from an analytical consumer cannot waive Model reconciliation.

Versioned contracts: `downstream-inputs/1`, `downstream-review/1`,
`downstream-readiness/1`. Analytical qualification is fixed to `unrun`.
[Review evidence](tasks/implementation/downstream-readiness-review.md).
