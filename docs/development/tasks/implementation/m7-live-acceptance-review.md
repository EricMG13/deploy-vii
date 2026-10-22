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
  N`). Otherwise the text is as before. Quoted fragments show up to 200 characters cut on a
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
  id are looked up first.
- Makefile: `live-module` passes `MODELS=`, `MAX_TOKENS=`, `BATCH_ID=`, `SEED=` through.
- `test_execution.py` CP-5 preset test reads `registry._NOT_CP5_FAN_IN`; decision 0007
  records the QA-Blocked attempt consumption as a decision candidate.

Not done, with the reason:

- `period` grammar check (step 3): stopped. The stored corpus entry
  `tests/product/replay/source_context/synthetic-cp1-source-context-accepted.json` carries
  `period_label` values `OPEN`, `Q1`, `Q2`, `Q3`, `Q4` and `FY`, which the brief's grammar
  rejects; the grammar was not widened. `fiscal_year_end` ("31 December") is not a period.
- Rename `normalisation` to `quote_normalisation` (step 4d): no manifest field or stored
  record field has that name; the only uses are the issue label text and the function in
  `quotes.py`, which task 7.0 replaced by `explain`. Nothing renamed.

No `methodology-adaptation.md` row: acceptance (`quoted`) and every analytical rule are
unchanged; the new text explains a rejection, the prompt states rules the validator already
enforced, and the ledger rule is reconciliation of spend, not analysis.

Not verified: live model uptake of the new prompt rules and mismatch text (E1 answers it);
the account-usage counter's timing relative to the after-batch check.
