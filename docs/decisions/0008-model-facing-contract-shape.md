# 0008: Model-facing contract shape and repair budget, from probe evidence

Date: 21 October 2026 (ruling), recorded 22 October 2026. Status: adopted under plan M2.7
(delegated choice, probe-2 evidence). Coordinator ruling under decision 0006 DC-1 and the
plan's delegation of 0008 to probe evidence; the user may override. Where the evidence was
insufficient, the decision says so and defers.

## Context

Probe-2 ([batch report](../development/tasks/implementation/live-probe-2.md),
[reconciled](../development/tasks/implementation/live-probe-2-reconciled.md)) ran
`source_readiness` only: nine cells on the frozen Caesars FY2025 pack (one source,
`czr-2025-10k`, 195 PDF pages, every page retained). First-pass validity was 0 of 9.

| Model | Result | Cost |
| --- | --- | --- |
| Luna x3 | HTTP 400 `invalid_json_schema` ("Missing 'limitation'"): the untransformed Pydantic schema under `strict: true` | US$0 (known zero) |
| GLM 5.3 Flash x3 | rejected: 17, 1 and 1 recorded issues | 0.002417062305 + 0.001819983555 + 0.00266381013 = US$0.00690085599, provider-reported |
| DeepSeek x3 | HTTP 504 "A Timeout Occurred" inside a 200 at about 300 s | 3 x 0.279468 = US$0.838404 held; the generation endpoint answered 404 for all three |

- **GLM draw 1 (17 issues) was mechanical, not judgment.** 13 issues were locators copied with
  the prompt's brackets (`[page:1]` for `page:1`). The others: `prepared-pack` cited as a source
  (the prompt presented it as a SOURCE block, the validator indexes only pack sources); eight
  consumers returned including CP-0 (the prompt never stated the consumer set); a consumer
  citing a source outside its own attachment set. Hash copying was correct.
- **GLM draws 2 and 3** failed the Pydantic parse with seven errors each, "non-ready consumer
  requires limitations" on `consumers.1` to `consumers.7`: a cross-field rule the prompt did
  not state. Semantic checks never ran.
- **All three GLM draws claimed pages 12 or 13 to 180 absent** and derived BLOCKED readiness
  from it, although the request carried every page 1 to 195 with text. No check compared such a
  claim with the pack.
- **Prompt size.** The GLM request body was 867,481 bytes; the reservation bound (one token per
  byte plus 64) was 867,545 tokens; GLM billed 154,609 prompt tokens (130,806 cached), 5.61
  bytes per token. At DeepSeek's pinned prompt price the bound reserved US$0.28 per call against
  about US$0.05 measured.
- **Repairs.** `repair_count` was 0 on every attempt and only one step ran, so no repair budget
  was exercised. `financials` never ran, so there is no evidence on `FinancialSubmission`.
- **Account usage** (`GET /api/v1/key`) moved 25.7172663 to 25.724167155 (US$0.006900855),
  which equals the three GLM costs within US$0.000000001.

## Decision

1. **MC-1 applied to `source_readiness` (evidence supports).** The model returns a
   `ReadinessSubmission` (`src/deploy_vii/live/submission.py`): per source its assessment
   (family, authority, entity, period, version relationship, fidelity, limitations, citations by
   `source_id` + `locator` + `quote`), per consumer its readiness judgment (readiness, evidence
   demand, rationale, missing source, limitations, citations), gaps and analysis claims. It
   holds no hash, no pack binding, no attachment set, no defaults and no pattern or length
   keyword. Python composes the stored `ReadinessReview` from it and the pack; that contract and
   its hash are unchanged (`readiness-review/1`):
   - `pack_sha256` and each citation's `source_sha256` come from the pack; a citation of a source
     the pack does not hold as ready cannot be bound and rejects the submission;
   - each consumer's `source_ids` (its attachment set) are the distinct sources it cites;
   - every pack source and every live consumer (`plan(requested_modules)` minus CP-0, CP-MODEL,
     CP-MEMO and CP-OS) is assessed exactly once structurally: an omitted one becomes an
     explicit placeholder (fidelity `blocked`, or readiness `BLOCKED`, with the limitation "Not
     assessed in the model submission") and a critical gap naming it, never a ready item;
     duplicates and extras are kept so the existing validator rejects them; the outcome
     (rejected, or accepted with gaps, that is restricted) is the existing validator's;
   - locators are matched exactly against the pack's span locators and quotes as substrings by
     the existing validator (the schema does not enumerate the catalogue, so it stays one static
     schema for every pack);
   - the prompt carries the pack as a non-citable CONTEXT block stating the source list with each
     source's extraction coverage (located span count, first and last locator, page numbers
     missing between them) and the exact consumer list, renders each span `locator=page:1 |
     <text>`, and states the rules the validator enforces (sources and consumers exactly once,
     a non-ready consumer lists a limitation, attachments are the cited sources, exact locators,
     no absence claim against stated coverage);
   - the validator rejects a limitation that calls a page range absent while the pack retains
     every page in it ("Absence claim contradicts extraction coverage"), checked against the
     source the text is about; tested with GLM draw 1's verbatim texts.

   A payload in the stored-review shape is the superseded pre-0008 shape: rejected with the one
   issue `schema: pre-0008 submission shape`. The three probe-2 GLM replay entries now expect
   exactly that and carry `superseded_by: "0008"`.
2. **MC-7: issues-only repair applied; the per-step budget deferred (evidence insufficient).**
   A repair ticket's REPAIR block carries the previous attempt's failing step issues (short
   form, task 2.7a) on that step's prompt only. Where no step failed validation (an
   interruption, a module-level refusal) the module issues are carried as before. The
   module-wide repair budget stays. The rerun must report `repair_count` per step and model; the
   per-step budget is reconsidered when a module-wide budget is observed exhausted.
3. **`FinancialSubmission` split: deferred (evidence insufficient).** `financials` has not run.
   Revisit when its first-pass validity on the rerun is below 2 of 3 draws for any model.
4. **Prompt-token bound (MC-10), the measured basis.** The reservation's prompt bound is
   `ceil(request bytes / prompt_bytes_per_token_lower_bound) + 64`, with
   `prompt_bytes_per_token_lower_bound = 3.0` in `settings/project.toml` (required, no default).
   Probe-2 measured 5.61 bytes per token, so 3.0 keeps a 1.9x margin: the probe-2 body bounds at
   289,225 tokens instead of 867,545. The 64-token template overhead of the previous bound is
   kept. Ledger behaviour is otherwise unchanged.

## Consequences

- `ReadinessSubmission` is the schema sent and printed for `source_readiness`; the prompt now
  prints the same strict schema that `response_format` sends (task 2.7a sent the strict copy but
  printed the untransformed one). Pool, proxy, corpus revalidation and replay enter the journal
  through one function, `submit_model_payload`. The journal retains the composed review for a
  composable submission and the payload as received for one that is not; `output.md` always
  keeps the raw model text, and each attempt records a `submission_composed` event (retained
  payload hash, placeholders, composition issues).
- A consumer can no longer attach a source it does not cite. Under the existing validator a
  runnable consumer already needed citations and every cited source attached, so this narrows
  only the uncited attachment; it is an execution-boundary change, not a change of readiness
  meaning, scales or missing-data treatment (decision 0005 guardrails).
- The absence-claim check is a new mechanical validator rule on the stored review; it applies to
  any review, and its scope is page locators only.
- Replay entries carry `payload_kind`: `journal` for the synthetic seeds (stored contracts
  supplied directly to the journal), otherwise model payloads replayed through the composer.
- Hook for M6: `submission.STEPS` names each step's model-facing schema; `source_context` and
  `financials` keep their stored contracts until their own MC-1 skeletons (M6, or earlier if the
  rerun shows the same mechanical failures there).
- The rerun (coordinator, at most US$5, all three probe steps) records the after evidence:
  first-pass validity per step and model, issue classes, `repair_count` per step, tokens, cost
  and latency. It also settles whether OpenAI, GLM and DeepSeek accept the submission schema.
- Carried from task 2.7a: live batches record the account usage before and after the batch, and
  `live reconcile` adjusts a held attempt whose generation 404s to zero only when that usage
  delta equals the other attempts' measured costs within US$0.000001 (source
  `generation-404+usage-delta`, both facts in the ledger line).

## Amendment, 22 Oct 2026

Probe-3 (the rerun, on the frozen Caesars pack) gave 1 of 7 first-pass valid steps (1 of 5
content-bearing; both DeepSeek calls timed out). Luna's `ReadinessSubmission` was accepted by the
strict schema on both draws; GLM 76fc5c95 was accepted. Two of the validator's own defects
rejected rule-compliant output: the absence rule read negated coverage statements ("no pages
missing between the first and last locator") as absence claims (Luna f136b227, GLM 76fc5c95),
and quotes were matched byte-exactly against layout-extracted text, so a line break inside a
sentence failed a clean copy. `source_context` stated none of the readiness rules and nothing
checked its absence claims (GLM f0391c45 called the retained pages 53-96 absent). Task 2.9
applied three execution-boundary fixes. (1) One quote matcher for every citation check
(`deploy_vii.quotes`): both sides are compared after removing soft hyphens, mapping curly quotes,
dashes and the minus sign to ASCII and collapsing whitespace runs; the quote must still be one
contiguous substring of the span its locator names (no fuzzy match, no other span searched), and
the issue names the locator, the normalisation and the normalised quote cut at a whole word
within 200 characters (task 7.0; 60 characters before), one per failing citation. It applies to the journal, financial and definition citation checks too,
because the journal re-checks the CP-0 candidate's citations with the same function. (2) A
negator followed by at most four words from a closed list and the absence word, or the coverage
field restated as empty, is not an absence word; positive claims still fail. (3) `source_context`
states the same sources-once, citation and coverage rules (one text each) and its validator
applies the absence rule to every free-text value outside citations. Revalidated over the same
pack, Luna f136b227 and GLM 76fc5c95 now have no issue (every live issue was a whitespace-only
quote difference or a negated statement), Luna 8634aa17 keeps two wrong-page quotes and GLM
f0391c45 keeps one wrong-page quote and gains three absence issues. Acceptance still means
substrings and structure held, not that the readiness reasoning is grounded (probe-3 analysis,
section 3). A stored review (a `source_context` review or any other) that carries a page-absence
claim about pages the pack retains now fails when it is re-validated. MC-1 for `source_context`
stays deferred. The next probe draws from the user-selected
pool (coordinator ledger ruling of 22 October 2026; the pool itself is task 2.8). The quote
tolerance is recorded as the methodology-adaptation row "Quote-matcher tolerance" (coordinator
ruling of 22 October 2026: an execution-boundary change under decision 0005; the
verbatim-substring rule is kept, only what counts as the same bytes widens).

## Amendment, 22 Oct 2026 (probe-4)

Probe-4 drew two attempts each from the user-selected pool (DeepSeek V4.1 Flash 1017 @max, Grok
4.7 @xhigh, MiMo-V2.6-Pro with reasoning enabled and no effort value, GPT-6.1 Sol @high) and
spent US$1.378 (US$1.37794208064; reconcile found no holds). Sol: 1 accepted (944e569a, 0
issues), 1 rejected (3 quote issues). Grok: 0 accepted, both complete and validatable (4 and 2
issues). MiMo: 0 of 2, both truncated at `finish_reason: length` with 72-74 % of the 16,000-token
budget spent on reasoning. DeepSeek: an HTTP 429 and a 502 inside `choices[0]` of a 200 after
1,029 s, the latter recorded as class `ok`. Ranking, under the user's rule (accepted results and
failure classes, not reasoning-token counts): Sol and Grok progress (coordinator ledger ruling of
22 October 2026, relaying the user's instruction). Task 2.10 fixed the runner and contract
defects found: (1) a CP-0 that does not authorize a consumer (T8 `DO NOT RUN`, from a valid
CONDITIONAL or BLOCKED judgment) ends that cell with a `not-authorized` step row (no attempt, USD
0) instead of aborting the batch; the gate itself stays; (2) a provider error inside
`choices[0]` (or `finish_reason: error`) is `http_error`, settled on its `usage.cost` when present
and held otherwise; (3) `timeout_s` bounds the whole call by the wall clock (recorded as
`deadline_s`), and an expiry settles like the 504-in-200 case; (4) `--max-tokens N` sets the
completion budget for every model of a batch, through the existing context-fit check; (5) the
non-empty `analysis` rule is stated in the prompt (rule h) and sent as `minItems: 1`; (6) the
quote matcher also tries the span with hyphenated line wraps joined (`hyphen-wrap`, span side
only; both readings tried, so matching only widens), which clears Sol 9594d016's p135 quote; a
two-column layout that interleaves another column inside a sentence (Sol p104, Grok p102) is
not handled and stays a known layout limit, as do case changes (Sol p13) and wrong-page
citations; (7) the CP-0 CONTEXT now carries each consumer's registry title and purpose, because
with ids alone Sol judged all seven consumers CONDITIONAL. No replay entry changed outcome.
Records: [live-probe-4.md](../development/tasks/implementation/live-probe-4.md),
[live-probe-4-reconciled.md](../development/tasks/implementation/live-probe-4-reconciled.md) and
the analysis, [live-probe-4-analysis.md](../development/tasks/implementation/live-probe-4-analysis.md).

## Amendment, 22 Oct 2026 (probe-5)

Probe-5 (Gemini 4 Argon, 2 draws, US$0.804) and probe-5b (Sol and Grok, US$0.939; no holds)
ran on the task 2.10 prompt. Gemini: 0 of 2, layout-dominated (4 of 7 issues the p102/p104
two-column stitch, 2 page-break straddles, 1 misquoted year). Sol: CP-0 accepted (cf6bf65b, 0
issues) with CP-1 READY_WITH_LIMITATIONS, so CP-1 was authorised and its `source_context` step
ran for the first time on OpenAI; the all-CONDITIONAL pattern of probe-4 ended once the CONTEXT
carried each consumer's title and purpose (plausible, not proven: one prompt per probe). That
step got HTTP 400 `invalid_json_schema` ("Invalid schema for response_format
'source_context'", no keyword named, US$0). The schema was not a task 2.10 regression: its
`schema_sha256` c1f3dc7f… is byte-identical to probe-3's, which GLM's provider accepted; it
comes from the stored contract, sent as its strict copy. Grok: 0 of 1 (one wrong page). Task
2.11 relaxes the *sent* copy only (`live.schema.relax`): a nullable enum lists its values without
null and is nullable through its type (OpenAI's documented shape), `const` becomes a one-value
`enum`, and `minLength`/`maxLength` are dropped; `pattern`, `format`, `minItems`, `maxItems`,
`anyOf` and `$ref` stay. The prompt prints the same relaxed schema (one source of truth), the
manifest names `schema_relaxations` beside `schema_keywords_unverified`, and `schema_sha256`
hashes what is sent. The way in is unchanged: `normalise` and the Pydantic contracts still
read the original schema, so an empty `period`, an over-long identifier, an unknown enum value or
a wrong constant is still rejected by the validator and repaired through MC-7. The cost is that
the model no longer sees length limits in the schema; it learns them from validator issues.
Which construct OpenAI refused is not known, so `deploy-vii live schema-check` sends one
16-token strict call per (model, step schema) through the normal client, ledger and key path
(default cap US$0.05, nothing submitted) and reports the provider's own error text; a recorded
schema-shaped HTTP 400 (`invalid_json_schema`, or a message naming the schema or
`response_format`) for the exact (model, step, sent schema hash) makes that step ineligible in
later batches under the same artifact root before anything is reserved, and any other 400 never
blocks. The first run (schema-2026-10-22, US$0.0777) showed the relaxation is not sufficient:
Grok accepted all five step schemas; OpenAI only `source_readiness` (`narrative`: "'oneOf' is
not permitted"; the others with no keyword named); Google `source_readiness` and `readiness`
("Request contains an invalid argument" for the rest). `schema-check --bisect` therefore sends,
for each rejected cell, schema variants that each remove or rewrite one suspect class, report
only ([live-schema-2026-10-22.md](../development/tasks/implementation/live-schema-2026-10-22.md)).
The first bisect (schema-2026-10-22-bisect, US$0.016,
[live-schema-2026-10-22-bisect.md](../development/tasks/implementation/live-schema-2026-10-22-bisect.md))
found OpenAI `narrative` accepted once `oneOf` became `anyOf`, Google `source_context` and
`narrative` once `minItems`/`maxItems` were dropped, and no variant accepted for OpenAI
`source_context`, `financials`, `readiness` or Google `financials`; fix round 2 adds variants for
nullable arrays (as an `anyOf`, or required), enum-or-null unions, titles and inlined references,
and reports each schema's resolved depth (`financials` 12 nodes, 7 objects) and property count.
Under the user's 22 October 2026 instruction, the relaxation finally chosen must be accepted by
OpenAI (GPT-6.1 Sol); the Grok and Google rows are information only. The second bisect
(schema-2026-10-22-bisect2, US$0.0175,
[live-schema-2026-10-22-bisect2.md](../development/tasks/implementation/live-schema-2026-10-22-bisect2.md))
found that OpenAI rejects `source_context`, `financials` and `readiness` under every variant
before `nullable-array-to-anyof` and accepts all three under it. The bisect stopped there, so the
variants after it were not sent. A plain check on the round-3 sent schemas
(schema-2026-10-22-r3, US$0.0214,
[live-schema-2026-10-22-r3.md](../development/tasks/implementation/live-schema-2026-10-22-r3.md)) then had all five step schemas accepted by
Sol. OpenAI refuses a nullable array
written as a `type` union (`type: ["array", "null"]`) inside a strict schema, and accepts the
same array as `anyOf: [{type: "array", items, minItems/maxItems}, {type: "null"}]`. Round 3
therefore adds two relaxations to the sent copy: `nullable-array-anyof` (that rewrite) and
`oneof-anyof` (`oneOf` + `discriminator` sent as `anyOf`, the narrative case). Both are lossless.
Every nullable array in these schemas defaults to `[]`, and `normalise` maps null back to `[]`.
Replies are validated by the stored contract, whose discriminated unions keep their tags. Every pool change is to be
checked this way before a CP-0 call. M7 backlog from the analysis (§6): a page-boundary hint for
a quote that continues on the next page; the 60-character truncation in quote-mismatch text;
the `hyphen-wrap` label printed only when the wrap is relevant; a check on free-text `period`
fields; a no-response column in the cohort tables. Records:
[live-probe-5.md](../development/tasks/implementation/live-probe-5.md),
[live-probe-5-reconciled.md](../development/tasks/implementation/live-probe-5-reconciled.md),
[live-probe-5b.md](../development/tasks/implementation/live-probe-5b.md),
[live-probe-5b-reconciled.md](../development/tasks/implementation/live-probe-5b-reconciled.md)
and the analysis,
[live-probe-5-analysis.md](../development/tasks/implementation/live-probe-5-analysis.md). Not
verified: acceptance beyond the 16-token schema check (probe-6 is to show Sol's replies under
the round-3 schemas).

## Amendment, 22 Oct 2026 (task 7.0)

Task 7.0 widened the quote shown in a citation issue from the first 60 characters to at most
200, cut at a whole word, so the REPAIR prompt carries the clause the model must correct. It also
adds the `account-usage-delta` adjust for a lone deadline hold that has no generation id. That
rule and the `generation-404+usage-delta` rule above share one exposure, now closed for both:
the provider may bill the call after the after-batch usage check, so the delta would omit its
cost, and therefore `live reconcile` takes a fresh `GET /api/v1/key` reading and makes either
adjust only when it equals the recorded after-figure within US$0.000001; otherwise the attempt
stays held with "usage moved since the after-check" and a later reconcile may retry.

## Amendment, 22 Oct 2026 (task 7.0d)

E1 batch `e1-cp1-3` (Sol @high) ran CP-1 `financials` to completion for the first time: 61,035
completion tokens, a 232 KB `FinancialSubmission`, 745 s and US$1.08. Shape validation then
rejected it for two causes the sent schema permitted: 131 amounts were strings copied as printed
(`"3,624"`, `"(211)"`; "Input should be a valid decimal"), and 19 of the 22 `metric_id` values
were invented (12 issues "unknown CP-1 account metric"). The sent copy now says both rules. The
new `decimal-number-only` relaxation keeps only the number branch, with its bounds and any null
branch, of each `Number` amount (Pydantic's `anyOf` of number and string). It selects these nodes
by a marker that `financial_contracts.Number` adds, never by shape. `AccountObservation.metric_id`
is sent as an enum of the 36 `ACCOUNT_IDS`. The `prefixed-enum` relaxation sends
`StatementLine.item_id` as `anyOf` of an enum of the 78 r14 statement item ids and the pattern
`^other:[A-Za-z0-9_.:-]*$`, and `BalanceMovementBridge.balance_item_id` the same way with the 32
BS ids. The pattern is exactly the `Identifier` ids the validators accept by their `other:`
prefix rule. The flat list is a superset for any one statement: Python still enforces the
per-statement split. `ProFormaObservation.metric_id` (6 ids or `facility:<facility_id>`, a
derived prefix) is deferred. The `financials` prompt states these rules and the unit of each
amount: money as printed in the book's `unit` and currency, or a facility's own currency, never
arithmetic; `effective_tax_rate` a decimal fraction; spreads and floors in basis points;
`fixed_rate` a percent; FX rates and KPIs in their own units. It also states the
`statement_lines` home of a figure that has no account metric, and the declared-period rule.
The stored contracts, their validators and the values they accept are unchanged: a stored
string amount still validates, and `controlled_metric` still refuses an unknown id with the same
message. Item 3 (`FinancialSubmission` split) stays deferred. Its measured basis is now one
draw: about 61k output tokens, 12.5 minutes and about US$1.1. Its trigger is first-pass validity
below 2 of 3 draws *after* the sent schema enforces the Python vocabularies.

## Amendment, 22 Oct 2026 (task 7.0g)

Item 2's trigger was met. E1 batch `e1-cp1-4` (Sol) exhausted the module-wide budget:
`source_context` was rejected on one case-variant quote, the module's one repair re-ran it
(accepted, US$0.47), then `financials` (62,980 tokens, 805 s, US$1.11) was rejected on a rule
its prompt had not stated, and with no repair left the cell ended. Item 2's per-step budget is
adopted as an execution-boundary change (decision 0005): each of CP-1's four model steps
(`source_context`, `financials`, `narrative`, `readiness`) may be repaired once within its
attempt, re-sending only that step with its own issues in the REPAIR block (scope
`failing-step`); the module-wide repair attempt is kept as the second line. Bound: at most two
tries per step per attempt and two attempts per input set. The journal keeps the rejected first
try in a new `Attempt.step_repairs` (the invalid submission with its payload hash and issues),
outside the positional `steps`, so the CP-1 workflow and envelope readers and the module's
content hash are unchanged: the same final payloads give the same `result_sha256` with or
without a repaired step. An empty `step_repairs` is omitted from the JSON, so stored
`execution/5` snapshots keep their bytes and the schema is not bumped. A reader older than this
amendment fails on a snapshot that holds `step_repairs` (an unexpected field, not the schema
message); no older reader is deployed. Analytical meaning is
unchanged: the same validators decide, the same issues are carried and acceptance semantics are
untouched. A REPAIR block comes from the step's own prior try (within the attempt, first) or from
the previous attempt, never both. CP-0's single review and CP-1's `quality` promotion step keep
the attempt-level repair only. The runner records `step_try` (1 or 2) and
`links.step_repair_of_attempt_id`; `repair_count` stays the attempt number. Not verified: a live
within-attempt repair (E1 batch 5).

## Evidence

- [live-probe-2.md](../development/tasks/implementation/live-probe-2.md): batch report and
  analysis.
- [live-probe-2-reconciled.md](../development/tasks/implementation/live-probe-2-reconciled.md):
  the 404 reconcile run.
- Replay entries `tests/product/replay/source_readiness/probe-2-glm-5.3-flash-{1,2,3}.json`
  (payloads unchanged; expectations regenerated against the Caesars pack).

Not verified: provider acceptance of the submission schema; first-pass validity after MC-1
(the rerun); whether GLM's absence claims came from the model or from provider-side truncation
(154,609 billed prompt tokens argues against truncation, not conclusively); whether the 3.0 ratio
holds for other models, packs and languages.

## Amendment, 23 Oct 2026 (task 7.0h)

E1 batch `e1-cp1-5` (Sol, 23 Oct 2026) met item 3's trigger: `financials` was cut at exactly
64,000 completion tokens (the `--max-tokens` budget; classification `truncated`) twice in the
first attempt, and a third time in the module repair. The
7.0g step repair re-sent the step at the same budget with a REPAIR block that said only
`(root): Invalid JSON: EOF while parsing a string at line 5928 column 13`; the model compacted
its JSON (184,578 characters on 100 statement lines, against 263,993 characters on 70 lines
indented) and was cut again (US$1.09 lost); the 7.0e module repair then re-ran `source_context`
(US$0.47) and `financials` (about US$1.1) at the same budget, and was cut a third time.

Rule: a `truncated` classification consumes no repair, step or module. A truncation is a budget
verdict, not a validator verdict the model can act on, and the budget is the operator's knob
(`--max-tokens`); a re-send at the same budget is a near-certain loss. The driver leaves the
step's one in-attempt repair unused, the ticket stays pending, the cell ends and the batch goes
on; the report counts such rows under `Truncated`. Compact-output rule: every step's preamble
states that the JSON object is emitted compactly (no indentation, no line breaks between fields)
because the completion budget is finite and charged per token. Item 3's trigger (truncation
observed) is now met; the `FinancialSubmission` split stays deferred until batch 6 measures
`--max-tokens 128000` (Sol's maximum completion). Analytical meaning is unchanged: no validator,
acceptance rule or journal rule moves.

Not verified: a live truncation under the guard and the compact rule's live effect (E1 batch 6).
