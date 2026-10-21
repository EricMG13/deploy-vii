# Historical Model readiness

`model_readiness.assess_model_readiness(pack, review, book_id, quarter_ids=None)`
returns a hash-bound `model-readiness/1` report with exactly one CP-MODEL row.
The row assesses **selected historical quarters**. It does not qualify forecasts,
pro forma adjustments, analytical interpretation, other consumers or report
presentation. Full CP-1 acceptance remains pending.

The report retains run/issuer/as-of/method identity, pack and review hashes, book,
requested and resolved quarter selection, findings, missing input keys, conflict
references, mandatory check IDs and both source and period reconciliation reports.
`validate_model_readiness` regenerates the decision from the frozen evidence;
editing a status or dropping a failed check cannot authorize a consumer.

## Selection and input requirements

Default selection includes every available historical quarter construction;
explicit selection accepts construction IDs. Duplicate and unknown selections
block. The resolved sequence is chronological and must contain at least four
quarters with known comparable spans, consecutive fiscal slots and contiguous,
non-overlapping dates. Each four-quarter window must span 364–371 days, matching
the reviewed Model's rolling-year convention. Direct and valid derived quarters
are eligible. Stub periods remain calculable but cannot establish this readiness.

Each selected quarter needs the r14 interface's eighteen flow accounts, the two
financing cash classifications consumed by adjusted CFO, nine balance accounts,
every stable carrying-value facility, segment and add-back, and a source tax rate
or both pretax income and tax expense. Known inputs need located evidence. Missing
or conflicting values never become zero. An absent facility table represents an
unknown schedule; an explicitly evidenced debt-free interface remains later work.

The by-nature expense presentation is an explicit adaptation of the prose method:
COGS is not invented when every source leaf used by a quarter has that evidenced
classification. The old standalone validator's unconditional COGS coverage is not
copied. Mixed or unknown presentation does not gain this exemption.

A genuinely undisclosed segment schedule remains an explained WARN/null check;
a disclosed schedule must contain the complete stable set in every selected
quarter. Partial disclosure blocks even if the numerical rows happen to sum.
Incomplete add-back disclosure cannot enter the selected kernel and is retained
as blocked with source checks rather than fabricated historical calculations.

## Checks and conservative boundaries

Each selected quarter requires segment/revenue, EBITDA, adjusted EBITDA, CFO,
debt excluding leases and cash-movement checks. Relevant fiscal-year checks cover
required flows plus independently stated values; independently stated FY/LTM
comparisons remain visible. Fiscal-year spelling is normalized when selecting
checks. Source statement identities and numerical source checks for contributing
periods also remain mandatory, so errors cannot disappear through subtraction.

Any mandatory BLOCK prevents readiness. Shared-source construction-only agreement
is still WARN, not independent proof. Every unresolved observation conflict in the
book blocks conservatively, including conflicts outside a selected window;
consumer-specific conflict materiality and explicit source-backed audit/FX
exceptions remain later work. No automatic exception or conflict resolution is
introduced here.

Missing rate, amortisation or maturity terms warn because historical carrying
values do not establish forecast inputs. The report never grants forecast
readiness. The stable source schedules are not truncated to presentation capacity.

## Verification and integration

Synthetic tests exercise complete and incomplete schedules, direct/derived
quarters, source identities, unknown values, calendar/fiscal sequencing, short
periods, tax routes, conflicts, scoped selection, annual mismatches and tampering.
See [review evidence](tasks/implementation/model-readiness-review.md).

This is an internal API. Binding the readiness result to a published Calculation,
Module and Direction C view, broader canonical CP-1 registers/KPIs and CP-1A remain
pending. No module or analytical acceptance is claimed by a synthetic ready row.
