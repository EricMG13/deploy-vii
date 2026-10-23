# M7 CP-1 live acceptance: result note

Date: 22 October 2026. Plan v2 M7 (CP-1 live acceptance). Later M7 tasks append sections.

## 7.0 Prompt and validator hardening before E1

Task `dvii-impl-m7-7.0-hardening`. Every live CP-0 rejection so far was mechanical:
probe-4 and probe-6 Sol on the p104 two-column exhibit interleave, Gemini on p102/p104
stitches and page-break straddles. E1 gets one MC-7 repair, which can succeed only if the
rejection says what to do. No quote is accepted that was rejected before: `quotes.quoted`
is unchanged; only messages, prompts, checks and reports change.

What changed:

- Mismatch text (`quotes.explain`, worded once, composed in `readiness.citation_issues`).
  A failed quote's issue now says why, in order: a case or lookalike-character difference
  (first differing character and its offset), a page straddle (`continues on <next
  locator>`, or `begins on <previous locator>` when cited where it ends), a column
  interleave (`two runs separated by interleaved text (columns or table cells) at offset
  N` when at most 400 normalised characters lie between the runs, else `two separate runs on
  this page`). Otherwise the text is as before. Quoted fragments show up to 200 characters cut on a
  word boundary (was 60). `hyphen-wrap` is named only when a wrap lies inside the region the
  failed quote occupies. Against the main checkout's pack the classes name Sol p104 (probe-4
  and probe-6) and Grok p102 (interleave), Sol p13 (case), Gemini p76 and p44 (straddle).
- Journal issue lines: `execution.MAX_ISSUE_CHARS` 300 to 600 (interruption text keeps
  300), because the REPAIR prompt carries journal issues and a 200-character fragment plus
  its clause does not fit 300 (a test forced it).
- Prompts: `CITATION_RULE` gains the contiguous-run and one-page sentences (both source
  steps); rule h gains the task 6.2 run-text rule (`RUN_TEXT_RULE`), also in
  `methods/cp0.md`.
- Reports: `No response` column in Cohorts; `-` issues on `no-response` rows; `Prompt token
  bound (largest)` in Pool.
- Ledger and reconcile: `account-usage-delta` adjust for a held attempt with no generation
  id that is the batch's only held attempt, every other charge measured; residual at most
  the reservation (rules in live-runner.md, Charge reconciliation). Holds with a generation
  id are looked up first. This adjust and the `generation-404+usage-delta` zero both need a
  fresh `GET /api/v1/key` reading at reconcile time equal to the recorded after-figure within
  US$0.000001; otherwise the hold stands with `usage moved since the after-check` and a later reconcile may retry (decision
  0008, task 7.0 amendment, which also records the 200-character quote bound).
- Corpus: `find_case_pack` skips a case directory whose pack does not load under the current
  contract (a `run/1` preparation) with a logged warning, and returns the first that loads.
- Makefile: `live-module` passes `MODELS=`, `MAX_TOKENS=`, `BATCH_ID=`, `SEED=` through.
- `test_execution.py` CP-5 preset test reads `registry._NOT_CP5_FAN_IN`; decision 0007
  records the QA-Blocked attempt consumption as a decision candidate.

Not done, with the reason:

- `period` grammar check (step 3): stopped twice. First pass: the stored corpus entry
  `tests/product/replay/source_context/synthetic-cp1-source-context-accepted.json` carries
  `period_label` values `OPEN`, `Q1`, `Q2`, `Q3`, `Q4` and `FY`, which the brief's grammar
  rejects. Under the coordinator's rescoping (identity periods get the grammar,
  `period_label` the closed set of `report_view._PERIOD_CLASSES`): the identity fields are
  `ReadinessSubmission.reporting_period` and `SourceJudgment.period` (no `SourceContext` or
  `ReportingScope` field names a reporting period; `EntityContext.fiscal_year_end` is a date,
  not a period), and stored accepted real entries carry prose there (GLM 76fc5c95 "FY2025 —
  fiscal year ended December 31, 2025", dccfe8f5, Luna f136b227), so the grammar would flip
  them. The `period_label` set passes both stored synthetic entries but rejects `H1` and `9M`,
  the year-to-date periods of the period-engine fixture (`test_financial_periods.periods_case`,
  scopes labelled by period id, used by canonical gaps, period reconciliation and statement
  history tests); `report_view` already leaves a grid with an unclassified label ungrouped.
  Neither set was widened and neither check landed. Step 3 is withdrawn from task 7.0 by
  coordinator ruling (22 October 2026: the periods are free text by design and the label set
  would cut H1/9M coverage); the unapplied patch is retained outside the repository at
  `/private/tmp/claude-501/-Users-ericguei-Documents-DEPLOY-VII--claude-worktrees-focused-cray-a5417d/bbc3f6f9-3db0-48bb-a291-6f454a3f0d88/scratchpad/period-label-check.patch`;
  revisit with E1 evidence.
- Rename `normalisation` to `quote_normalisation` (step 4d): no manifest field or stored
  record field has that name; the only uses are the issue label text and the function in
  `quotes.py`, which task 7.0 replaced by `explain`. Nothing renamed.

No `methodology-adaptation.md` row: acceptance (`quoted`) and every analytical rule are
unchanged; the new text explains a rejection, the prompt states rules the validator already
enforced, and the ledger rule is reconciliation of spend, not analysis.

Not verified: live model uptake of the new prompt rules and mismatch text (E1 answers it);
how long the account-usage counter takes to settle (the reconcile-time recheck refuses, it
does not wait).

## 7.0b Parallel product suite (decision 0011)

`pytest-xdist` 3.8.0 (dev group) and `make coverage` run `-n auto --dist loadfile`; the
`fail_under = 90` floor is unchanged and is evaluated on the one combined TOTAL line.
Measured on one 10-CPU, 64 GB Mac in the same hour (19:00 to 21:00 BST, 22 October 2026) while
a live E1 batch ran elsewhere on the machine, so the times are contended and relative:

| Run | Wall time | Tests | Coverage |
| --- | --- | --- | --- |
| serial, `-n 0` (final tree) | 27m22s | 2208 passed, 14 skipped | 97.49% |
| parallel, 10 workers, run 1 | 11m33s | 2208 passed, 14 skipped | 97.49% |
| parallel, 10 workers, run 2 | 11m23s | 2208 passed, 14 skipped | 97.49% |

An earlier serial run on the tree before the new tests (2205 passed, 26m43s) and a first
parallel run (2206 passed, 10m58s) gave the same 97.49%. Speed-up about 2.4x on 10 workers; the
tail is a few long files (`loadfile` cannot split a file), so `loadscope` would not help.
Peak RSS per worker was not measured. The 14 skips are the seven `pack-absent` replay entries
and the other counted skips, identical in both modes.

Worker safety: the first second-run attempt failed 9 browser tests with `FileExistsError`.
Cause: rendering evidence was named `<group>/<tmp_path parent>/<test>`; under xdist the parent is
`popen-gw<n>`, which repeats on every run. Fixed at the tests (no serial marker):
`tests/product/evidence.py` `evidence_path` names the directory by the run number, worker and
test, used by the eight evidence sites (`test_browser`, `test_delivery`, `test_execution`,
`test_interface_view`, `test_narrative_projection`, `test_register_view`, `test_report_tables`
twice) and tested in `test_evidence.py`. `conftest.py` is unchanged (its session fixture uses
`tmp_path_factory`, which is per worker). `ci.yml` is unchanged; the budget stays 40 minutes.

Carried test (7.0 re-review gap A): `test_a_connection_failure_in_the_fresh_usage_reading_stops_the_run_and_keeps_adjustments`
(`test_live_reconcile.py`). A `TransportError` on the reconcile-time `GET /api/v1/key` ends the
run with exit 2 after the report is written; the generation-endpoint adjustment already written
stays in the ledger (the file is appended to, never rewritten) and the deadline hold stands.
No production change was needed.

Plan: the 26 tasks of M1 to M6 are ticked and each milestone heading carries its merge sha.

Not verified: the hosted run time (the next PR shows it); `-n auto` resolving to 4 on the
hosted runner; worker memory on a 4 GiB VM (the parity script runs per file and is unaffected).

## 7.0c Configurable request deadline

E1 batch `e1-cp1-2` lost the CP-1 `financials` call to the fixed 600-second request deadline,
because a 64,000-token completion from Sol (about 70 tokens a second) can need 15 minutes.
`deploy-vii live` now takes `--timeout SECONDS` (and `make live-module` takes `TIMEOUT=`), default
600, applied to each socket operation and the whole call of every model, and printed in the report
header.

Evidence: batch `e1-cp1-2`: `financials` timed out at 600 s with a 64,000-token budget;
reconciled at US$0 (the provider did not bill the abandoned generation).

Not verified: a live call under a longer deadline (the coordinator reruns E1).

## 7.0e The module driver dispatches the MC-7 repair

Decision 0008 MC-7 gives each input set one repair, but `deploy-vii live module` ended a cell at its first rejected step, so no repair was ever dispatched. The driver now begins the repair attempt after a validator rejection (never after a no-response), reruns the module from its first step, and the batch report gains a `Repair` column and a `Repairs dispatched` header line. Only the `module` command repairs; `probe`, `regression` and `canary` stay one attempt per step.

Evidence: E1 batches 1 to 3 (22 October 2026) each ended at the rejected `financials` step with `repair_count` 0.

Not verified: a live repair (the coordinator runs E1 batch 4).

## 7.0d The financials sent schema states the Python vocabularies

The `financials` step's sent schema now enforces two rules that only Python held before. First,
every `Number` amount is a JSON number: the `decimal-number-only` relaxation in `live.schema`
drops the string branch of Pydantic's Decimal union. It selects the node by the
`DECIMAL_MARKER` that `financial_contracts.Number` adds, so a real number-or-text union is never
rewritten, and a marked node of another shape raises `ValueError`. Second,
`AccountObservation.metric_id` is an enum of the 36 `ACCOUNT_IDS`. The prompt replaces "Report
each amount exactly as the source states it." with four step rules: amounts as JSON numbers
(`3,624` is 3624; `(211)` is -211); `metric_id` from the enum, with a figure that has no account
metric going to `statement_lines` (issuer detail under the `other:` prefix); the
`context_step_sha256` binding; every `period_id` declared in its book's `periods`. Decision 0008
carries the amendment. The stored contracts, their validators and messages, and the replay
corpus are unchanged.

Evidence: batch `e1-cp1-3` (Sol @high, 61,035 completion tokens, 745 s, US$1.08) was rejected by
shape validation alone: 131 amounts sent as printed strings and 12 "unknown CP-1 account metric"
issues (19 of 22 `metric_id` values invented).

`schema_shape` of the `financials` sent schema: before, depth 14 (7 objects), 232 properties, 32
enum nodes with 100 members; after, depth 14 (7 objects), 232 properties, 33 enum nodes with 136
members. The keyword set is unchanged. The sent schema grew from 28,899 to 29,555 bytes. The
provider accepted that schema (cb4de52f…) on the coordinator's schema-check (US$0.0135).

Only `AccountObservation.metric_id` gained an enum. Every other model or field validator in
`financial_contracts`, `canonical_audit` and `context_binding` checks either a `Literal` (already
an enum) or a set that is derived from the payload or open by an `other:` prefix.

Fix round 1 (review): rule (a) now names the unit the system assigns to each amount. Money is
written as printed, in the book's `unit` and currency (a facility's in its own currency), and is
never arithmetic. `effective_tax_rate` is a decimal fraction (21.0% is 0.21), `spread_bps` and
`floor_bps` are basis points (2.75% is 275), `fixed_rate` is a percent (5.25% is 5.25), and FX
rates and KPIs carry their own units. The new `prefixed-enum` relaxation sends
`StatementLine.item_id` as `anyOf` [enum of the 78 r14 statement items, pattern
`^other:[A-Za-z0-9_.:-]*$`], and `BalanceMovementBridge.balance_item_id` the same way with the 32
BS items. Python still enforces the per-statement split, with the same messages.
`ProFormaObservation.metric_id` (6 ids or `facility:<id>`) is deferred. After the fix:
depth 14 (7 objects), 232 properties, 35 enum nodes with 246 members, 31,728 bytes.

No `methodology-adaptation.md` row: the accepted values and every analytical rule are unchanged.
The schema now states rules the validators already enforced.

Not verified: provider acceptance of the enum-bearing schema (the coordinator runs `live
schema-check --steps financials`) and live uptake (E1 batch 4).

## 7.1a CP-MODEL deterministic publication

`cp_model_workflow.publish_cp_model` (CLI `cp-model-publish`) gives CP-MODEL a head once CP-1
is promoted: the Model destination page, the calculation JSON and a receipt, Python only.
CP-5 can then begin under the four presets that request CP-MODEL. Preconditions, the M4
inheritance, the `Qualification` used (`implementation: implemented`, the rest `unrun`: the
contract has no `not_applicable`) and the file order are in `execution.md` "CP-MODEL
publication (task 7.1a)". `r14-coverage.json` CP-MODEL `implementation` is now `implemented`;
its `rendering_acceptance` stays `unrun` (no browser acceptance run has qualified the page).

Deviations from the brief: the manifest cannot hold the page's or the receipt's hash (cycle),
so the receipt does; the CP-MODEL bindings (`bindings/cp_model.py`, bound to the Evidence
destination) were needed because the report builder refuses unbound facts; the browser test of
the populated Model panel sits in `test_cp_model_workflow.py` beside its journal fixture.

Not verified: publication on a real promoted CP-1 (none exists until E1); the XLSX workbook
(deferred, decision 0006 DC-5); a CP-1 whose financial stage has no calculated Model (refused,
untested end to end); analytical qualification of the Model figures.

## 7.0f The sign-convention rule reaches the model

The `financials` contract now states when `sign_convention` is `signed` or `outflow_magnitude`
and that the latter needs a located `sign_citations` span, which no step text said before. The
two `sign_evidence` messages name their remedy, and `shape_issues` drops a container `min_length`
error that only echoes a failed item. No validator or arithmetic semantics changed. Evidence
(E1 batch `e1-cp1-4`): 14 sign-evidence issues and 1 derivative `financial.books` issue.

Not verified: live uptake (E1 batch 5).

## 7.0g Per-step repair within the attempt

Decision 0008 MC-7 item 2 is adopted (amendment "22 Oct 2026 (task 7.0g)"). Each of CP-1's four
model steps may be repaired once within its attempt: the journal keeps the step's rejected first
try in `Attempt.step_repairs`, the attempt stays pending, and the `module` driver re-sends only
that step with its own issues in the REPAIR block. A second rejection finishes the attempt and
the 7.0e module repair follows. Bound: two tries per step per attempt, two attempts per input
set. The `Repair` column shows `step` (`1+step` inside the repair attempt) and `Repairs
dispatched` counts both kinds. The manifest gains `retries.step_try` and
`links.step_repair_of_attempt_id`. `cp1_workflow.py`, `envelope.py` and the `execution/5`
schema are unchanged: an empty `step_repairs` is omitted from the JSON. CP-0 and the `quality`
promotion step keep the attempt-level repair only.

Evidence: E1 batch `e1-cp1-4` (22 October 2026, Sol) spent its one module repair on a
`source_context` quote slip; the repair's `financials` (62,980 tokens, 805 s, US$1.11) was then
rejected and the cell ended.

No `methodology-adaptation.md` row: validators, issues and acceptance are unchanged; this is an
execution-boundary change (decision 0005).

Not verified: a live within-attempt repair (E1 batch 5).


## 7.2 CP-1A business and transaction context

CP-1A (alias CP-2C) is one live step, `business_context`, after CP-0 (decision 0008 MC-1). The
model returns `BusinessContextSubmission`: judgments, closed-enum Five-Category tags and verbatim
quotes only. Python validates it (`validate_business_context`: sources once, CP-0 citation and
coverage rules, run text, category and row rules, conflicts logged not reconciled, prohibited
conclusions, consumers exactly as listed) and composes the 22 r14 registers plus
`cp1a.cp_model_snapshot_fields`, with T2D.8 scored and T2D.9 drawn from the credit translations
by documented rules (`docs/development/business-context.md`, two `methodology-adaptation.md`
rows). A settled CP-1 is bound as a context input of CP-1A (`execution.CONTEXT_PRODUCERS`), so
CP-1A text may reference its figures as `{ref|unit}`; without one the CONTEXT block says no
figure may be written. `module --module CP-1A` runs CP-0 then the step; promotion records the
four statuses as 6.4. `bindings/cp1a.py` ships the Front Page and rail bindings; the FP 01
fixture uses it in place of its synthetic CP-1A map, so both darwin pixel baselines were
regenerated (the company block now shows Company and Operating model tabs with the Issuer,
Business description, Country and Sector rows; the key-findings gap label moved from G20 to G74
because CP-1A's unsettled cells take earlier `G#` numbers). `deliver_cp1a` publishes a
standalone delivery like CP-0's.

Sent schema (`strict_schema(BusinessContextSubmission)`), after fix round 1: depth 6 (3
objects), 136 properties, 15,141 bytes, no relaxation. Prompt bound on the fixture pack:
15,690 tokens, or 15,737 with one CP-1 fact offered. Before the fix it was 134 properties,
14,954 bytes and 15,365 tokens.

Fix round 1 (review), in six parts:
- A register's first r14 column is its row header and is not repeated as a cell. Four
  registers keep it as a fact: the company row, the credit translation's Evidence (where
  figures resolve) and the transactions and events (prose lines).
- Own limitations are only the model's gaps and an empty required register. A legitimately
  empty fact class is "None" (`not_applicable`), so a submission filling only the required
  registers settles `accepted`.
- T2D.10 Source / Flag Link carries the consumer's cited sources and behaviour-flag ids (new
  `citations` and `flag_topics` on each consumer).
- The prohibited phrases are narrowed to creditor and instrument forms ("visitation will
  recover" passes; "the notes would recover" fails), with "ranks among" and "top quartile"
  added and "best-in-class" allowed in a Management Language row.
- The prompt states the four evidence rules it omitted.
- `deliver_cp1a` takes no CP-1 facts.

The pixel baselines did not shift: both screenshots are within tolerance.

Not verified: live uptake (E1, the coordinator runs it) and provider acceptance of the sent
schema (the coordinator runs `live schema-check --steps business_context`).

## 7.0h Truncation guard

E1 batch 5 showed a completion cut at the `--max-tokens` budget being re-sent twice at the same
budget. A `truncated` classification now consumes no repair: the step's in-attempt repair stays
unused, no module repair begins, the cell ends and the report counts it under `Truncated`. Every
step's preamble also asks for compact JSON, `live regression` gains the `cp1a` case, and
`step_repair_of` raises instead of returning `None` when the rejected try is absent.

Evidence: batch 5 `financials` was cut at 64,000 completion tokens twice (US$2.21 on the cuts),
and the module repair cost about US$1.6 more. Not verified: a live truncation under the guard and
the compact rule's live effect (E1 batch 6).

## 7.0i The model supplies no hash

Python fills every hash binding of the CP-1 steps: the context step, the pack, each citation's
source, the source-context review, the financial review (twice), FX facility rows, audit
observations, and the narrative and readiness inputs (decision 0008 amendment "23 Oct 2026
(task 7.0i)" lists them). Each binding is marked `x-deploy-vii-prefilled: <kind>` and left out of
the sent schemas (`drop-prefilled`). Rule c, the `source_context` `pack_sha256` sentence and the
block's `step_output_sha256=` line are gone, and every changed path is recorded in
`Submitted.prefilled` and the `payload_prefilled` event; the stored contracts and validator
checks are unchanged.

Evidence: E1 batch `e1-cp1-5` (23 October 2026, Sol) lost three `financials` attempts (about
US$3) to the context binding. The last one (46,020 tokens, 587 s, US$0.90, no shape issue)
copied the block's `step_output_sha256` (`fc55f2…`) where the header's `f56a66…` was required.
Behind that check, the payload still bound the model's own `FinancialReview` by hash.

Not verified: provider acceptance of the changed CP-1 sent schemas (the coordinator runs
`live schema-check --steps source_context,financials,narrative,readiness`) and live uptake (E1
batch 7).

## 7.0j The financials prompt states the statement-register rules

The `financials` contract now states, as step rules e to h, the register facts `statement_validation` and `financial_validation` enforce: a statement line is one row per period under one `line_id` and one `display_priority`; each statement admits only its own `item_id`s (listed from `REQUIRED_ITEMS` and `OPTIONAL_ITEMS`, never hand-copied, else `other:`); an account and its linked statement line carry one amount or an explicit `conflicting` observation; every segment is allocated exactly once. Tests hold each rule to the validator (the accepted shape passes, the batch-6 shape raises the same issue text) and the item lists to the tables. No validator, contract or methodology change (decision 0005).

Evidence: E1 batch 6 (DC-8 proxy cohort, 23 October 2026): the first `financials` submission past shape and binding validation drew 98 semantic issues (91 duplicate statement display priorities, 2 wrong-statement ids, 2 silent account/statement disagreements, 2 addback/segment duplicate priorities, 1 segment allocation).

Not verified: live uptake (the proxy module repair and the next pool batch).

Fix round 1: the rules also state the renamed statement/account links (rendered from `ACCOUNT_LINKS`), the stable fields of addbacks, segments and KPIs, one line per `item_id` per statement and the `other:` id spelling. The segment-priority sentence is stricter than the validator, which checks operating segments only; that is safe because a corporate/elimination segment given a distinct priority is accepted too.

## 7.4 The live quality step promotes CP-1

CP-1 gains a fifth live step, `quality` (`CP1_CHAIN`, `FULL_CHAIN`, the `module` driver and the
`regression` `cp1` case). The model returns the `QualityReview` over the QA scope Python projects
from the recomputed registers (`prompts.quality_scope`, a `quality-scope` CONTEXT block: claims
with text and evidence ids, each such id's ceiling, basis and record, the coverage slots with
register cells counted, the source gate and module status). Python fills `inputs_sha256`
(marker kind `quality-inputs`, dropped from the sent schema) and enters the review through
`promote_cp1`, so an accepted step is the promotion (head `PROMOTED`, envelope exportable). A
rejected review finishes the attempt (no within-attempt repair: the step settles the module);
the module repair re-runs the chain from `source_context`. The proxy cohort takes the same
route. No valid `readiness` step, or registers that do not stage, raise before any write.
`promote_cp1`, `validate_quality_review`, the ceilings and the status rules are unchanged
(decision 0008 amendment "23 Oct 2026 (task 7.4)").

Evidence: offline only (fake transport and proxy payloads on the synthetic 6.4 case): a CP-1
cell runs five steps to a promoted head whose envelope exports; a lineage above its ceiling is
rejected with the validator's message and repaired by the module repair; the synthetic scope
block is about 9.4 KB against 44,777 coverage slots and 48,836 references in the inputs.

Not verified: provider acceptance of the `quality` sent schema (the coordinator runs
`live schema-check --steps quality`); a live or proxy QA review on the real pack.

## 7.5 Bounded upstream projections

E1 batch 6 (proxy cohort, the first accepted `financials` on the real Caesars pack) could not
send the next step: the `narrative` prompt held 8,900,941 characters because `runner._upstream`
put every retained step's raw output (the 8,023,867-character `FinancialStage`) into a SOURCE
block. Each later CP-1 step is now sent the projection `live.context.PROJECTIONS` names for its
consumer/producer pair (an unlisted pair raises before anything is spent), under a header that
keeps the retained content hash and names the projection: `narrative` gets `narrative-evidence`
(one evidence-table line per catalogue entry, no `record_json` or citation, plus scope,
limitations, source context and model metrics); `readiness` gets `readiness-inputs` from the
narrative step (consumers, the narrative review and added gaps, the evidence table with gap
ids); `quality` gets none (its QA scope); `financials` keeps the source-context report whole.
Pack SOURCE blocks go only to the steps whose validators match quotes against the pack;
`narrative`, `readiness` and `quality` declare none (`cli`), and `build` refuses them. Validators,
retained outputs, hashes and acceptance are unchanged (decision 0008 amendment "23 Oct 2026
(task 7.5)"; the table is in `docs/development/live-runner.md`, "What each step receives").

Evidence: offline only. On the synthetic CP-1 case (2,913 catalogue entries) the narrative block
is 528 KB against the 10.2 MB raw output (5.2%, about 174 characters per evidence line), the
readiness block 599 KB against 9.9 MB (6.0%); each catalogue evidence id, and each gap id, is
on exactly one line; a narrative dispatch that the raw upstream made ineligible is now sent and
accepted.

Not verified: the real-pack block sizes (narrative target at most 600,000 characters; the
coordinator measures on the batch-6 journal); live or proxy uptake of the projections.

## 7.6 The narrative and readiness prompts state the rules their validators enforce

The `narrative` contract now states, as step rules a to e, the prose rule, the passage parts (an issuer part in every finding, no blank or separator parts), dimension coverage, funding rows (only `statement_BS` evidence with a `line_id`, never a definition row) and required stories (only `subsequent_event`, `multi_figure_event` and material funding rows, each citing the story's evidence id); the `readiness` contract states the prose rule, the consumer and requirement keys, the evidence tag groups per requirement key, the action and `kpi_dashboard` rules and the gap-scope rules. The dimension, financial-dimension, standard balance-sheet item and evidence-group lists are rendered from the validators' constants, and tests hold each rule to the exact issue the validator raises, with no validator, contract, projection or hash change (decision 0005).

Evidence: E1 batch 6 (DC-8 proxy cohort, 23 October 2026): the first `narrative` submission past shape validation drew 21 semantic issues (6 missing issuer bindings, 2 funding rows that were not located balance-sheet rows, 9 unknown required stories, 3 stories whose finding lacked the story's evidence, and on the first try 1 blank prose part used as a separator).

Not verified: proxy uptake (the next proxy narrative and readiness runs); the real-pack `readiness` prompt size (the rules add about 6,400 characters in all to the two system messages; the evidence table is unchanged).

## 7.7 The r14 envelope places the `segment-allocation` table

`model_interface` emits the `segment-allocation` table (Model Segment Allocation, `cp1.cp_model_segment_allocation`) only for a book with segments, and `envelope.SECTIONS` had no place for it, so `write_envelope` refused every segmented issuer (`No r14 envelope section for table: segment-allocation`), the registers' `canonical-handoff` QA slot was absent and `_quality_stage` refused every review. The table now sits in Module Handoff between T4.19 and `operating-kpis`, the model interface's own order; `_sections` still refuses any unplaced table, and a test derives the set of tables the CP-1 module can carry from the producers' schemas and both fixtures and requires exactly one section for each. For a book without segments the sidecar is byte-identical and the Markdown gains only the `Not produced: segment-allocation is not in this module.` block; validators, QA scoring and promotion rules are unchanged (decision 0005).

Evidence: E1 batch e1-cp1-7 (DC-8 proxy cohort, 23 October 2026), ticket c5d7cc31: `source_context`, `financials`, `narrative` and `readiness` accepted, then `quality` rejected by Python in `_sections` on the segmented Caesars book; offline, a segmented synthetic book now writes, verifies and fills the `canonical-handoff` slot.

Not verified: the real-pack re-run of the `quality` step (the coordinator repairs attempt c5d7cc31's input set on e1-cp1-7); on that pack QA is expected to stay Blocked (narrative `blocked`), an analytical outcome this task does not change.

## 7.8 A 402 is read before it is called exhaustion

A dispatch 402 is now read for its reason: the in-flight refusal (`in_flight_budget_exhausted`, limit source `openrouter_in_flight_budget`) is transient, so the runner seals it, waits its Retry-After (at most 300 s, 120 s when absent) and re-sends the step once as a new, separately reserved attempt that names the refused one (`links.in_flight_retry_of_attempt_id`); the refusal uses up no model try and keeps its report row. A second in-flight refusal, the credit refusal (`openrouter_credits`) and any 402 whose body cannot be read stay exhaustion (DC-8 exit 4, ticket pending, no model or cohort switched). The manifest `credit` block, the CLI abort line and the report's `Stopped:` line carry the reason and, where the body states them, the requested and affordable max_tokens, never the body's `user_id` (decision 0006 amendment "23 Oct 2026 (DC-8, task 7.8)"; details in `docs/development/live-runner.md`, "No-credit backup cohort").

Evidence: E1 batch e1-cp1-8 (23 October 2026): CP-0 accepted (US$0.484), then `source_context` refused 105 s later with the in-flight 402 and `Retry-After: 120`, which aborted the batch; batch e1-cp1-9: the first call (CP-0) refused with the credit 402 "You requested up to 128000 tokens, but can only afford 91075". Offline tests replay both bodies through a fake transport (fixture account id).

Not verified: a live 402 of either kind through the real transport (the coordinator's next pool batch); whether OpenRouter also sends `Retry-After` as an HTTP header on the in-flight 402 (the body carried it); whether the in-flight budget settles within the wait in practice.

## 7.9 Prompt refinements from the first full proxy chain

Thirteen of the fifteen wording items are stated once in the step contracts, each true to the code it names and held to it by a test: `narrative` (funding rows are non-debt liability detail lines; the story requirement follows the listed material ids; separator parts, part joining and issuer rendering; `model_metrics` carry no evidence id and comparisons are directional only), `readiness` (the `consumer_specific_cp1_sufficiency` request, unlabelled computation lines, unscoped gaps keep a consumer `not_ready`), `quality` (the module status and source gate are not findings), and `business_context` (item-range joiners, a single-source conflict, the `other` behaviour type). Item 3 (located rows) was already stated by 7.6; item 15 was dropped: `methods/cp1a.md` (line 48) defines a subsequent event, but no contract defines the status of an event that has not occurred (`Pending` versus `Announced`, `EventStatus` in `business_context.py`). No validator, contract, projection or hash change (decision 0005). The narrative rules grew from 3,724 to 5,037 characters and the readiness rules from 2,996 to 3,850.

Evidence: E1 batch e1-cp1-7 (DC-8 proxy cohort, 23 October 2026).

Not verified: live or proxy uptake of the new wording; whether the grown narrative and readiness prompts change completion-budget use on the real pack.

## 7.10 Review follow-ups (fix and docs batch)

Closed, one line per item (analytical meaning unchanged, decision 0005; no validator, scoring or promotion-rule change):

1. The QA Blocked verdict has one source: `cp1_workflow.qa_blocked_issue` builds it and `is_qa_blocked` checks it (the bands from `quality.Band`); `cli.qa_blocked_only` uses that check, and a test round-trips a Blocked review's verdict.
2. `qa_blocked_only(step_id, issues)` applies to a `quality` rejection only; the same text on any other step is an ordinary rejection that takes the module repair.
3. `quality_scope(registers, inputs)` keeps its second argument (the runner also records the inputs' hash in the manifest, so it computes them once); a test asserts the scope with held inputs equals the computed one.
4. The replay corpus records and replays `quality` attempts: the entry holds the four stages as `upstream` and replays through the promotion; two synthetic entries (`synthetic-cp1-quality-accepted`, `synthetic-cp1-quality-qa-blocked`) join the corpus.
5. `write_cp1_envelope` renders the handoff envelope again (the retained candidate, checked against `candidate_sha256`) and requires the `quality` step's recorded Markdown and sidecar hashes before writing; a mismatch raises naming both hashes. The exported files themselves carry the settled status, so they never hash as the handoff did; the check is on the handoff rendering.
6. A segmented book promotes and exports with `segment-allocation` in Module Handoff (no source change). `segmented_book()` discloses a `partial` schedule, whose BLOCK gaps make QA Blocked, so the test uses the same book with a complete schedule.
7. The manifest of an in-flight-refused 402 attempt that a re-send follows records `retries.exhausted: false`; the re-send keeps the real value (tested on the last allowed try).
8. Stored reply bodies (`response.json`) have every `user_id` value replaced by `"<redacted>"` in place, the key and every other byte kept; `body_sha256` and `body_bytes` describe the stored bytes, and `response.json` and the manifest carry `body_redactions: ["user_id"]`. A JSON body whose account id the in-place match cannot reach is withheld whole. DC-7 is unchanged.
9. `plan.md`: the M7 lane state and the 6.4 real-pack measurements (prompt sizes, render timing, r14 statuses of the first full chain).
10. Decision 0005: two methodology candidates recorded, not adopted (readiness gap scoping; BLOCK-gap extraction).
11. `frontend-direction-c.md`: prose cells of the Front Page company panel render in monospace, recorded for the design pass.
12. `live-runner.md`: `steps run` counts an in-flight-refused attempt, which is no model try.
13. This section.
14. Withdrawn (24 Oct 2026): the user kept Sol's pooled effort at `high`; nothing changed.
15. A pre-existing `prose` defect, found by the property test `test_any_digit_outside_labels_and_references_is_rejected` (Hypothesis counterexample `1900%`): a year-shaped number followed by `%` passed as a year label. A bare year is now a detached token, so `1900%`, `2025%` and `1950%` are bare figures, as `1900x` and `1900bn` already were; `FY2025`, `2025` and the other labels are unchanged. Present since M6 (2e5a050).

Deferred: the `FinancialSubmission` split (decision 0008); turning `WITHIN_ATTEMPT_REPAIR` into a `repairable` argument; reducing the 7.4 QA scope, which inlines `record_json` (270 KB on the real pack, inside budget, not reduced).

Not verified: real-pack replay (the corpus replays CP-1 entries on the synthetic pack only); a live stored body through the real transport.

## 7.11 Batch e1-cp1-13 findings (first GPT-6.1 Sol at high chain)

Batch e1-cp1-13 (DC-8 pool, GPT-6.1 Sol at `high`, cap US$12, 23 October 2026): 7 steps, 3 accepted (one `source_readiness`, two `source_context`) and 4 rejected (both input sets ended at `financials`, first try and step repair each), US$4.875576 spent, CP-1 not promoted. Two rejection families, each a fact the prompt left unsaid:

1. **Dimension strings.** Six `Mixed units, currency, accounting basis or perimeter` issues (both first tries: each period's `accounting_basis` and `entity_perimeter` differed from its book's) and three `No matching entity/date/basis source scope` issues (one repair: the book's `entity_perimeter` paraphrased the closest scope's string). The other repair, rejected for one quote only, also wrote a book whose `currency` and `entity_perimeter` match no scope; the binding check runs only once both reviews validate, so it was not reached. `context_binding` and `book_issues` compare the four strings exactly; the prompt showed the scopes but never said to copy them.
2. **Quotes.** Both first tries cited a heading under `page:95` that sits in the `page:94` span (the next span's marker read as its page); one repair quoted `first-` + newline + `priority` where the span prints `first-priority`, which the matcher rejected (it joined wraps on the span side only).

What each item closes:

1. Financials rule i (`prompts.BOUND_SCOPE_RULE`): copy the bound scope's four strings verbatim into the book and every period (family 1); a validator test holds both messages to a one-character difference.
2. `prompts.PAGE_SPAN_RULE` in the common preamble: a locator's page is the span that contains the text, read from the marker that opens it (family 2, page:95). The preamble is used because `CITATION_RULE` does not reach `financials`.
3. `prompts.HYPHEN_COPY_RULE` in the common preamble: copy a hyphenated word whole (family 2, guidance beside item 4).
4. `quotes.quoted` joins a hyphen line wrap on the quote side too (decision 0005 row, adopted, widening only). Read-only check on the batch-13 repair: its one wrapped quote among 489 citations now matches and no citation of that payload fails; the attempt would still be rejected by the binding check (family 1), which item 1 addresses.
5. `live reconcile` recognises an interrupted attempt (batch e1-cp1-12, stopped mid-`financials`: an open US$3.237196 reservation, `request.json` only), writes the manifest that shape supports and settles it by the `account-usage-delta` rule only where that rule holds. Batch e1-cp1-12 recorded no after-check, so there its reservation stays open (unresolved, no figure); the coordinator runs that reconcile.
6. A reply body in which `user_id` survives outside a redacted pair (OpenRouter's `error.metadata.raw` string, a non-JSON body) is withheld, and a withheld body records `body_redactions: []` (from the 7.10 review).
7. `live-runner.md` records that the DC-8 cohort path stores the proxy payload unredacted, hashed as received; `plan.md` ticks 7.1a and 7.2.
8. This section; decision 0005 also records candidate 7.11 (Python prefills the four dimension strings from the bound scope), not adopted.

Not verified: live uptake of the new sentences; reconciling the real e1-cp1-12 reservation (the coordinator runs it); the account-usage window on the real key.

## 7.13 Python fills the dimension strings; a killed batch's window; batch e1-cp1-14

Batch e1-cp1-14 (DC-8 pool, GPT-6.1 Sol at `high`, 23 October 2026, code 92b249b, before the 7.11 prompt sentences): 7 steps, 3 accepted and 4 rejected, US$4.738996, CP-1 not promoted. It reproduced batch 13 on both input sets: each `financials` first try was rejected for `Mixed units, currency, accounting basis or perimeter` on FY2025, FY2024 and FY2023 (the book's strings differed from its periods'), and each within-attempt repair fixed those and failed on one quote, a statement heading cited `page:95` that sits near the end of the `page:94` span. No new failure class.

What each item closes:

1. **Dimension prefill (adopted, user-approved 23 Oct 2026; decision 0005 row 7.13).** `FinancialBook` and `FinancialPeriod` mark `currency`, `unit`, `accounting_basis` and `entity_perimeter` with the binding kind `scope-dimension`; the sent `financials` schema leaves them out and `live/submission.prefill` copies them from the retained source-context scopes the model's entity binding and period dates select (`context_binding`'s date and kind rule, financial sources only). A book takes the one tuple its bound periods share. Fail closed: disagreeing scopes leave the book unfilled and reject with one issue (`Bound source scopes disagree on <fields>: <book> <periods>`); a period with no scope is left unfilled and rejected in `context_binding`'s own wording per cited source; a binding naming no single known entity, in that validator's binding wording; a null scope dimension is never written (the contract's `Field required` names it). The prefill record (`Submitted.prefilled`, the `payload_prefilled` event) lists every path Python wrote; output.md keeps what the model sent.
2. **Validators untouched.** A test sends a paraphrased perimeter, and a book whose strings differ from its periods', straight to `submit_cp1_step` (rejected with `No matching entity/date/basis source scope` and `Mixed units ...`) and through `submit_model_payload` (accepted, the scope's strings written).
3. **Rule i reworded.** `BOUND_SCOPE_RULE` no longer asks for a verbatim copy: it says Python fills the four strings, which model fields select the scope, that money amounts are in that scope's `unit` and `currency`, and what is a rejection.
4. **Replay.** `make replay` passes; every recorded `financials` payload of the corpus (the entry and the quality entries' upstream) is unchanged by the prefill (`test_replay.py`).
5. **Read only on the recorded batch payloads** (the dimension strings removed, as the sent schema now has it): batch 13's input set caad83cc is filled and bound (16 strings, no issue). Batch 13's c8272a66 and both batch 14 input sets would still be rejected, now with `Bound source scopes disagree on entity_perimeter: <book> FY2025, FY2024, FY2023`: their `source_context` scopes word the FY2025 perimeter differently from the comparative years', and every scope's `currency` is null. A `financials` repair cannot change those strings (they are the source-context step's), so this class now surfaces as an upstream scope problem rather than model drift.
6. **A killed batch's window (from the 7.11 rulings).** When a batch recorded no after-check, `live reconcile` may close its window at the earliest later batch's before-check under the same artifact root, only when both record the same key-file note, the batch's own ledger ends before it and no other batch reserved between the two checks (every `.ledgers/*.jsonl` read); the attempt is then settled as `account-usage-delta/next-batch-before` with both files, both times and the no-reservation fact in the evidence and the report. Read only on the real artifacts: e1-cp1-12's window closes at e1-cp1-13's before-check (08:39:00Z to 08:43:18Z, 32 ledgers, none reserving between); usage moved US$0.8463945, exactly its two settled charges, so the interrupted `financials` reservation (US$3.237196) would settle at US$0. The coordinator runs that reconcile. A resumed run reuses the manifest this path wrote only while the directory holds exactly `manifest.json` and `request.json` (7.11 review concern 1).
7. **Docs.** `live-runner.md` describes the three 7.11 prompt sentences (rule i as reworded) and the prefill and reconcile rules; the `quotes.py` docstring and the "Mismatch text" paragraph say what leaves `quoted` unchanged; the "Quote-matcher tolerance" row lists `test_quotes.py` and the batch-13 before/after.
8. **Locator correction: candidate only** (decision 0005, candidate 7.13). The heading was cited one page off on four consecutive tries across batches 13 and 14, before and after the issue text named the page. Moving a citation to the adjacent span where its quote is unique would change what the model claimed (provenance), so it is recorded, not adopted; the 7.11 preamble page sentence has not yet been exercised by a batch.

Concern for the next batch: the in-batch usage rule checks a reconcile-time reading because the provider may book a charge after the after-check, and batch 13 showed such lag (by its after-check its usage had moved US$1.0737551 less than its settled charges, and it moved by exactly that amount between its after-check and batch 14's before-check, with no reservation between). The next-batch-before window has no such corroboration. For e1-cp1-12 the longer window to batch 14's before-check also leaves a residual of exactly 0, but the rule itself does not look that far.

Not verified: a live `financials` attempt through the real transport with the prefill; real-pack replay (no pack in this checkout); the reconcile of the real e1-cp1-12 reservation; live uptake of the reworded rule i.

## 7.14 Scope dimensions agree at `source_context`; the spend cross-check

7.13 item 5 found the cause one step upstream: in three of the four input sets of batches e1-cp1-13 and -14 the accepted `source_context` left `currency` null on every scope and worded the FY2025 `entity_perimeter` unlike the comparative years', which no `financials` repair can change. What each item closes:

1. **Non-null dimensions (decision 0005 row 7.14, adopted, user-approved 23 Oct 2026).** `validate_source_context` rejects a `historical_duration` or `period_end` scope of a financial source without `currency`, `unit`, `entity_perimeter` or `accounting_basis` (`Financial scope lacks <field>: <scope_id>`, one per field and scope). Forecast and unspecified scopes, and a non-financial source's scopes, are untouched. `Currency` is a three-capital-letter pattern, so a sentinel such as `XXX` is admitted by the type; the type is not changed here (an enum is its own task).
2. **One entity's scopes agree.** All such scopes of one entity across every financial source state the same four strings, compared exactly (`Financial scopes of one entity disagree on <field>: <entity_id> <ids> vs <ids>`, one per entity and field, scope ids grouped by value; a null is item 1's alone). This is the scope set `live.submission._period_scopes` and `context_binding` choose from, so after a passing `source_context` every book has one complete tuple: the prefill's `Bound source scopes disagree` and its dimension `Field required` cannot follow (a property test over random dimension assignments holds it). The prefill keeps both as defence in depth; their tests now reach them through a replaced `known_bindings`, since no such context can be retained. Read only on the batch outputs: input set caad83cc passes; c8272a66 and both batch-14 input sets fail both rules, at the step that can repair them.
3. **Rule d.** `source_context` rule d (`SCOPE_DIMENSION_RULE`) states both rules once, and no other step carries it.
4. **Replay.** `make replay` passes. The one recorded `source_context` entry (synthetic, accepted) still passes the new rules; no corpus entry changed outcome.
5. **Spend cross-check.** `live reconcile` ends the reconciled report with the key's usage now less the earliest recorded before-check usage (today probe-2's), against the settled charges of every `.ledgers/*.jsonl` ledger opened since that check (earlier ledgers, today probe-1, are named with their settled sum and not counted; fix round 1); a failed key read for it says "not checked" and leaves the exit code unchanged (fix round 1); the difference is `Unattributed USD`, reported only (nothing settled or adjusted), with both inputs, their times and the ledger count; without a usable origin, ledger set or reading, the section says why and shows no figure. Addendum: the next-batch reason and the module docstring state the full window rule; the two refusals that said "key token(s)" now say "key-file note", as `live-runner.md` does.

Resolved in fix round 1 (coordinator ruling): the real root's earliest ledger, `probe-1`, recorded no before-check, so the origin is now the earliest recorded before-check and `probe-1` is named as not covered.

Not verified: live uptake of rule d and of the two validator rules; the cross-check against the real key (the coordinator runs `live reconcile`); a real-pack replay of a `source_context` entry (none is recorded).
