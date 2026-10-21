# CP-1 source and entity context

`source_context(pack, review)` produces `source-context/2` from an explicit
`source-context-review/1`. It can run before financial extraction and does not
require a financial book. Every prepared source has exactly one assessment,
including missing/unreadable sources. The report binds the run, pack and review
hashes. Context gaps retain explicit reporting-scope IDs where applicable. Source filename, original hash, availability and extraction fidelity are
retained separately from the analyst's classification and evidence quality.

## Source register — T4.1

A located source assessment records document type, publication date, financial
relevance, evidence rationale, analytical use and limitations. Python maps the
explicit evidence class to the pinned hierarchy:

| Located classification | Tier |
| --- | --- |
| Audited financial statements | 1 |
| Unaudited with auditor involvement | 2a |
| Unaudited without auditor involvement | 2b |
| Lender/sponsor material | 2c |
| Rating material | 2d |
| Internal material | 3a |
| External material | 3b |

Unknown authority stays null. Neither filenames nor successful text extraction
supply a tier. A tier describes source authority; it is not certification of every
figure in a mixed document. Numerical conflicts remain unresolved regardless of
source rank. Source classification and scope citations must belong to that source.
No assessed metadata is invented for unavailable files.

The file gate is blocked without a readable source explicitly assessed as
containing financial data. Otherwise unresolved metadata, extraction limitations,
scans and source scope differences produce a restricted context report. A fully
specified context is still only a candidate, never analytical or Module acceptance.

## Entity and period register — T4.2

Entities retain located names, legal-entity/group distinction, issuer/borrower/
guarantor/restricted-group roles, fiscal-year-end description and limitations.
Reporting scopes cross-reference an explicit entity ID and source, period label,
duration or point-in-time kind, dates, currency, unit, perimeter and accounting
basis. Missing fields remain null with generated gaps; incomplete entity assertions
need an explicit limitation. Different known reporting bases for the same entity
are flagged for normalization review, never chosen or converted silently.

Historical scope cannot end after publication or the run's as-of date. Forecast
scopes are distinguishable and cannot satisfy a historical extraction binding.
This metadata layer does not turn a fiscal-year-end description into calculated
calendar dates.

Every source has a subsequent-event scan state. An empty event list defaults to
unassessed; a no-event conclusion requires located scan evidence. Identified events
retain reporting-scope ID, effective/event date, date the stated status became
known, completed/announced/proposed status, description, effect and citations.
They must fall after a known historical reporting end. Completion evidence cannot
predate a completed event, and completed events cannot lie beyond as-of.
Announced/proposed future events remain distinct. The known date cannot postdate
a cited publication.
Every event is attached to its evidence sources' scan records. Events are expressly
excluded from historical figures; this layer performs no pro-forma arithmetic.

## Financial extraction binding

`validate_financial_context(pack, context_review, financial_review, binding)`
checks `financial-context-binding/1`, which hashes both reviews and explicitly
maps every financial book to an entity. It checks evidence for periods and every
observation, including conflict alternatives, against that source's financial
classification and matching entity, dates, currency, unit, perimeter and basis.
A similar name or another source's valid citation cannot substitute for a mapping.
All inputs are reconstructed from their serialized contracts before traversal.

Pro-forma observations are checked separately against the corresponding located
subsequent event: entity, reporting end, dimensions, effective date, event status,
announcement/knowledge ordering and source coverage must agree. They are not
mislabelled historical observations. The original financial review is unchanged.

A successful binding proves mechanical compatibility of the declared scope. It
cannot prove semantic truth of the cited interpretation, source sufficiency or
full consumer readiness. CP-1 assembly/execution must require this context before
extraction and carry its gaps forward; chronological execution and Module delivery
are not yet connected to these internal APIs.

`validate_source_context_report(pack, review, report)` recomputes the entire
report against external inputs. Embedded output metadata is not its own authority.

Method source: Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`, r14 CP-1
Steps 01/02 and the binding subsequent-events rule. Reviewed locally in
`artifacts/cp1-steps-reference.md`; no Deploy VI code or policy was imported.
[Review evidence](tasks/implementation/source-context-review.md).
