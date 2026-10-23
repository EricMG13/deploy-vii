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
