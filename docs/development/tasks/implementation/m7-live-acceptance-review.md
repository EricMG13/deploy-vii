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

## 7.0c Configurable request deadline

E1 batch `e1-cp1-2` lost the CP-1 `financials` call to the fixed 600-second request deadline,
because a 64,000-token completion from Sol (about 70 tokens a second) can need 15 minutes.
`deploy-vii live` now takes `--timeout SECONDS` (and `make live-module` takes `TIMEOUT=`), default
600, applied to each socket operation and the whole call of every model, and printed in the report
header.

Evidence: batch `e1-cp1-2`: `financials` timed out at 600 s with a 64,000-token budget;
reconciled at US$0 (the provider did not bill the abandoned generation).

Not verified: a live call under a longer deadline (the coordinator reruns E1).
