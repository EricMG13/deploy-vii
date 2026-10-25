# Frozen CP-1 consumer sufficiency (M10-FND)

`m10_sufficiency.py` supplies the CP-1 prerequisite for later M10 owners. It does
not implement an owner, authorize sources, dispatch work or settle an attempt.
CP-1A assessment remains deferred until a direct consuming owner specifies its use.

An owner defines a fixed `CP1Use(version, description)` in its method code. From
the owner's actual `Attempt` and one trusted `ExecutionSnapshot`,
`cp1_sufficiency_inputs` authenticates the exact declared CP-1 head and derives
the book, entity perimeter, periods, facilities and selected historical quarters.
The binding includes the owner's direct inputs (including its source addendum),
the requirement/use version, frozen producer provenance and one local
`DownstreamInputs`. It does not hash the snapshot or effective requested set.
Changing code alone cannot reopen an already settled execution input set.

`cp1_frozen_producer` is a separately named read seam. It selects the finished
attempt by the bound result hash, verifies every retained step's input prefix,
recomputes all four stages and QA, and verifies the original candidate, handoff
and entire settled head. Settlement authentication reads only the producer's own
historically bound CP-0/result/grant through existing verification and settlement
rules; it adds no owner analytical prerequisite or CP-0 output. Producer scope
comes from its bound source grant, or the original pack when no grant was needed.
It uses the immutable pack's run for envelope identity. Raw
response hashes name retained bytes, including noncanonical JSON; canonical
contract hashes never substitute for blob names. Existing current-attempt APIs
keep their current-producer-input checks. This seam deliberately authenticates
the historical producer without substituting today's producer context.

`assess_cp1_sufficiency` accepts only the existing `ConsumerAssessment` judgments.
Python supplies its binding and computes the production downstream report.
Unknown consumer/evidence/requirement/gap claims are validation errors; absent
requirements or gap assessments produce `not_ready`. All source-integrity blocks
and original gaps remain subject to the existing downstream rules. Missing or
corrupt producer provenance raises; it cannot become an analytical gap.

An authenticated original matching row is a ceiling. Original `not_ready`
remains unavailable; original limitations and actions remain retained. Original
rows do not record a new owner's exact requirement/use version, so this seam
cannot prove equivalence and does not reuse an original ready row without local
review. The local production report and the ceiling-adjusted `status` are both
retained, together with the original row and producer limitations. Consumers
must use the outer status for their input gate.

The later owner must call the helper in its existing trusted submission using
the snapshot already held under its journal lock. The helper does not reread the
journal pointer. Retain the assessment as owner output, never as an additional
`Attempt.inputs` prerequisite: that would create a cycle. The owner must verify
its exact recomputed report on resume/promotion and implement its own permitted
input-gap-only artifact or supported conclusions. This helper does not loosen
hard stops, grant fresh analytical judgment approval or qualify those conclusions.

Offline tests use actual production CP-0/CP-1 promotion, source addendum and a
bound CP-4 attempt as an existing consumer fixture. That demonstrates the shared
seam, not future M10 owner submission/report integration. Analytical, live and
native qualification remain unrun; completeness floors remain off.
