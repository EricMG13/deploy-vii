# Live model runner (M2, Task A: runner core)

Status: implemented and tested offline on 21 October 2026. No model has been called; every
HTTP exchange in the tests goes through an injected fake transport. Analytical qualification,
account entitlement and provider behaviour are unrun. Contract: [testing and
telemetry](../testing-and-telemetry.md); decisions [0005](../decisions/0005-methodology-changes-and-regular-testing.md)
and [0006](../decisions/0006-delegated-choices-and-orchestration.md) (DC-6 to DC-8). API facts used:
[coordinator inputs](live-runner-inputs-2026-10-21.md). Task 2.7b applied
[decision 0008](../decisions/0008-model-facing-contract-shape.md) (model-facing submission,
step-scoped repair prompt, measured prompt bound), offline only.

## What it does

`deploy_vii.live.runner.dispatch` runs one attempt of one module step against one model drawn
from a pinned pool:

1. Validate the ticket against the journal (module, next step, nothing pending) before any
   spending. Draw the model (`draw.draw`, seeded, uniform over eligible members; a one-model
   pool is not drawn from, and the draw is recorded as trivial). Resolve the
   effort. Build the prompt. Bound the prompt tokens and compute the reservation.
2. Load the key from the DC-7 file, then retain `request.json` (exact body, draw, effort).
3. `ledger.reserve`. Refusal retains a `refused` attempt and raises `CapExceeded`; nothing is sent.
4. `ChatClient.complete`. The response is retained (`response.json`, `output.md`) before the
   journal sees it.
5. `ok` and `truncated` payloads go to `submission.submit_model_payload` only: a
   `source_readiness` submission is composed into a `ReadinessReview` and submitted through
   `submit_cp0_review`, a CP-1 payload goes to `submit_cp1_step`, so the journal's validators
   decide acceptance. Fallback, HTTP error, 402 and timeout payloads are not submitted.
6. `ledger.settle`, then `manifest.json` last. Both run in a `finally`, so a crash in validation
   still settles money and seals evidence (status `interrupted`) and then propagates.

## Modules

| Module | Role |
| --- | --- |
| `settings.py` | Reads `[model_tests]` from `settings/project.toml` with `tomllib` (candidates, caps, artifact root, `credential_file`, `credential_token_index`: an integer >= 1, default 1 when absent; 0, negatives, booleans, floats and strings are refused; `prompt_bytes_per_token_lower_bound`: required, a positive finite number, no default). |
| `credential.py` | `load_key` (wraps `load_key_with_note`, which returns a `LoadedKey`): RTF to text with `textutil` (fails closed without it; the file-exists check runs first, so a missing file is reported the same on every platform), then keeps one whole `sk-or-` token from any surrounding label, prose, quotes, blank lines, BOM or CRLF; a repeated token counts once. `load_key_with_note(path, index=1)` returns the distinct token at that 1-based position in the converted text's order; `index` is `[model_tests].credential_token_index`, passed as a parameter through `dispatch(..., key_index=)` and `ChatClient(..., key_index=)`. An index beyond the distinct tokens fails closed ("credential_token_index N but only M key-shaped tokens"; a repeated token is one), and an index that is not an integer >= 1 is refused before the file is read. A refused key (for example a 401) is never retried with another token: there is no automatic fallback. `LoadedKey.note()` gives `{"key_tokens_found": M, "key_token_used": N}`, which the runner adds to the manifest's `credential` block and the key-status probe to the credit record (`key_file`), only when M > 1. Refuses an empty file or no token ("no key-shaped token among N non-empty lines"); messages and notes carry counts only, never file text; a `textutil` failure, timeout or non-UTF-8 output is a `CredentialError` with no chained cause. Documented fail-open: a key broken inside by an invisible format character or a line break yields a truncated token, which is sent (a 401 or a refused key check follows; nothing leaks or is spent). `scrub_key`, `redact`. |
| `catalog.py` | `Catalog` (fetch or file), `pin` to a `PinnedPool`, DeepSeek resolution, `resolve_effort`. |
| `draw.py` | `draw(pool, seed)`, algorithm `python-random-MT19937`; a one-model pool is not drawn from (algorithm `trivial-single-model-pool`, index 0, seed still recorded; decision 0005 amendment, 22 Oct 2026). |
| `ledger.py` | `Ledger`: append-only JSON lines (`reserve`, `settle`, `adjust`), atomic replace, derived `.state.json`. |
| `reconcile.py` | Generation-endpoint lookups for held charges, the account-usage corroboration of a 404; `adjust` lines and the `metrics.json` ledger block. |
| `client.py` | `ChatClient` (`key_index` required with `key_path`), `ChatRequest`, `KeyStatus` (a key-status reply with the key note of that call), classification, usage parsing, default `urllib` transport. |
| `retention.py` | `AttemptWriter`: `begin`, `record_response`, `seal` (manifest last), `write`. |
| `prompts.py` | `build`, `response_format`, delimited data blocks (CONTEXT, SOURCE, REPAIR), step contracts. |
| `submission.py` | `ReadinessSubmission` (the model-facing `source_readiness` schema), `STEPS` (each step's model-facing schema), `compose`, `submit_model_payload` (decision 0008). |
| `schema.py` | `strict_copy` (strict-mode copy of a step schema), `relax` and `relaxations` (the sent copy, task 2.11), `strict_schema` (the relaxed strict copy that is sent and printed), `schema_relaxations`, `normalise` (nulls for omitted defaults back to the default), `unverified_keywords`. |
| `runner.py` | `StepSpec`, `dispatch`, `DispatchResult`, `prompt_token_bound`, `repair_prompt`; `check_schema`, `schema_rejections` (`live schema-check`, task 2.11). |

## Rules and where they are enforced

- **Key.** Read at dispatch, held in memory, sent only in the `Authorization` header
  (`Request.headers` is excluded from `repr`). Provider bodies, model output and retained files lose
  only the exact key and key-shaped tokens (see Scrubbing below); transport exception text and the
  recorded error are also stripped of `Authorization` values. Redirects are never followed (urllib
  would resend the header).
- **Reservation.** `prompt_bound x prompt_price + max_tokens x completion_price + request_price`.
  The prompt bound is `ceil(request bytes / prompt_bytes_per_token_lower_bound) + 64` over the
  UTF-8 bytes of the whole request body (decision 0008, MC-10). The ratio is 3.0 in
  `settings/project.toml`: probe-2 measured 5.61 bytes per token (GLM 5.3 Flash, 867,481 bytes,
  154,609 prompt tokens), so the bound still over-estimates, by about 1.9x; the probe-2 body bounds
  at 289,225 tokens instead of 867,545. The ratio, the byte count and the basis are recorded in
  `request.json` and `metrics.json`. Prices are pinned per batch as the maximum of the base price and every published
  override (time-of-day and long-prompt tiers), with the base recorded. Reasoning tokens bill at the
  completion rate, so `max_tokens` is reserved in full.
- **Settlement.** Provider `usage.cost` when present; otherwise tokens x pinned price, marked as an
  estimate; HTTP 402 and other 4xx (except 408) are known zero; anything else (timeout, 5xx,
  transport failure, usage absent, and since task 2.10 a provider error inside a 200 that reports
  tokens but no `usage.cost`) holds the whole reservation as spent and is flagged
  `unreconciled`. A cost above its reservation is recorded as an overrun and counts against later
  reservations.
- **Routing.** `provider: {allow_fallbacks: false, require_parameters: true}`, no `models`, no
  `tools`, no `tool_choice`, no `temperature`. A served model outside `{requested, canonical_slug}`
  is `fallback`; it is retained, its cost is charged, and it is never submitted or pooled. The
  served provider is recorded in every manifest (`served.provider`) but never compared, because
  the request pins no provider; provider drift across attempts is visible in reports, not
  classified. A response with no `model` field stays `ok` but is `identity_verified: false` and
  `poolable: false`.
- **Retries and repairs.** The same seed re-draws the same model. A fallback, HTTP error, 402 or
  timeout leaves the journal ticket pending, and the caller may dispatch again on that ticket: a
  new attempt id with `retry_of_attempt_id`, on the same drawn model, bounded by `max_retries`
  (default 2, so at most three attempts per ticket step; refused attempts do not count). The
  attempt that uses the last try (also a connection failure that raises `TransportError`)
  calls `Execution.interrupt` on the ticket. **That consumes the input set's one repair**: the
  next `begin` is the repair attempt, and if the exhausted ticket was already the repair, the
  module is blocked for those inputs. The manifest `retries` block (`attempt_number`,
  `max_retries`, `exhausted`, `ticket_interrupted`, `journal_consequence`) records it, and a
  dispatch beyond the bound raises before any spending. If the last allowed attempt dies with a
  non-transport exception (for example a validator bug), the ticket stays pending: the caller
  must call `Execution.interrupt` before dispatching again, and the next dispatch raises naming
  that remedy. A journal repair (`Execution.begin` after
  a rejection or interruption) records `repair_of_ticket_id` and `repair_of_attempt_id` and puts
  the prior validator issues into the prompt as a delimited `REPAIR` block. Under MC-7 (decision
  0008) the block carries only the issues of the previous attempt's failing step, and only on that
  step's prompt; where no step failed validation (an interruption, a module-level refusal) the module issues are carried
  as before. A `repair_prompt` event records the scope (`failing-step`, `module` or `none`), the
  failing step and the issue count. The repair budget stays module-wide.
- **Scrubbing.** Evidence and model output are only ever changed by the exact key and key-shaped
  tokens (`scrub_key`); text such as "Authorization: the board..." stays verbatim. The wider
  `redact`, which also rewrites `Authorization` header values, is applied to exception and error
  text only. The key-shape match has a left boundary, so words such as "risk-or-reward" are never
  altered. The manifest `scrubbed_files` lists the retained files in which key-shaped text was
  replaced by the writer, plus `response.json` and `output.md` when the client had already
  scrubbed the provider body; `manifest.json` itself is not listed. `credential.response_scrubbed`
  says whether the provider body needed it.
- **Ledger cap.** The first ledger line records the cap. Opening the same file with a different cap
  raises `LedgerError`; a new cap needs a new ledger file.
- **Prompts.** Source text appears only inside `<<<SOURCE id=... sha256=...>>>` blocks in the user
  message. A source that contains a delimiter is refused, not escaped (escaping would break verbatim
  citations). Declared inputs only: the prepared-pack identity, the named sources, and retained
  earlier steps of the same ticket (`step:<id>`, with the step hash and the hash of its output).
  The pack identity is a `<<<CONTEXT id=prepared-pack sha256=...>>>` block marked not citable; it lists each
  source with its extraction coverage (located spans, first and last locator, page numbers missing
  between them) and, for `source_readiness`, the exact consumer list. Since task 2.10 each consumer
  is `{module_id, title, purpose}` with the module registry's own `title` and `purpose`
  (`methodology.json`, verbatim; no other text, no brief content), so the model is told what each
  consumer needs (probe-4: with ids alone Sol judged all seven CONDITIONAL); the block stays
  non-citable. Each span renders as `locator=page:1 | <text>`, so the locator is copied without
  brackets. The `source_readiness` contract states the rules the validator enforces (rules a to h;
  h, task 2.10: "`analysis`: at least one evidence-grounded read-through entry; an empty list is
  rejected", also sent as `minItems: 1` on `analysis`, which the manifest lists under
  `schema_keywords_unverified`; the validator still rejects an empty list in its own words);
  `source_context` states the same sources-once, citation and coverage rules
  (`prompts.SOURCES_ONCE_RULE`, `CITATION_RULE`, `COVERAGE_RULE`, one text each, task 2.9).
  Task 7.0 teaches what the validator enforces: `CITATION_RULE` (both steps) adds "Copy a run
  that is contiguous in the SOURCE block as printed; never reassemble a sentence across
  interleaved table text. Never continue a quote onto the next page.", and rule h adds the
  task 6.2 run-text rule for `analysis[].text` (`prompts.RUN_TEXT_RULE`: digits only in period,
  filing and section labels, SEC file numbers and coverage counts; every other figure belongs in
  a citation's quote), also a paragraph of `methods/cp0.md`. A test holds each example label in
  the rule to `prose.bare_figures`, so the prompt never allows a figure the validator rejects.
  Stored replay payloads are unaffected (the corpus replays payloads, not prompts).
- **Quotes and absence claims (task 2.9).** Every citation check uses `deploy_vii.quotes`: quote
  and span text are compared after removing soft hyphens, mapping curly quotes, dashes and the
  minus sign to ASCII and collapsing every whitespace run to one space; the quote must still be
  one contiguous substring of the span its locator names. A failing citation is one issue,
  `Quote/locator mismatch: quote not found under <source> <locator> (normalised whitespace, quote
  marks and dashes): "<quote>"` plus, since task 7.0, a clause saying why (below); the quote is
  shown normalised, cut on a word boundary after at most 200 characters (60 until task 7.0) and
  then `…` (`no locator <locator> in <source>` when the locator does not exist). The absence rule skips a negated absence ("no pages missing", "none
  missing", "not missing") and the coverage field restated as empty; `source_context` applies it
  to every free-text value outside citations.
- **Hyphen-wrap (task 2.10).** On the span side only, the matcher also tries the span with each
  ASCII hyphen that ends a line (plus the spaces after the newline) joined to the next word:
  `PUT-\nCALL  RIGHT` reads `PUT-CALL RIGHT` (probe-4 Sol 9594d016 p135). Both readings are
  tried, so matching only widens; the model's quote is normalised as before and never has its
  hyphens altered. The mismatch issue says `(normalised whitespace, quote marks and dashes;
  hyphen-wrap)` only when a wrap lies inside the span region the failed quote occupies (the
  classified region below, else its longest matching prefix); a wrap elsewhere in the span is
  not named (task 7.0; probe-5 Gemini p84 printed it for an unrelated wrap). Known layout limit:
  a two-column table that interleaves another column inside a sentence (Sol p104, Grok p102) is
  not matched, so a quote stitched across it fails; so do case changes and wrong-page
  citations. A quote that joins one wrap and copies another as a space matches neither reading.
- **Mismatch text (task 7.0).** `quotes.explain` says why a quote failed; it never accepts one
  (`quoted` is unchanged, and a property test holds that no classified quote is accepted). Over
  both span readings, in order, it appends to the issue: a case or lookalike difference (the
  quote matches once case and a closed set of quote-mark and dash lookalikes the normalisation
  leaves alone are folded) `: the quote matches the span only ignoring case and character
  variants; first difference at offset N: "F" (U+0046) in the quote, "f" (U+0066) in the span`;
  a page straddle (the quote's first run ends the cited span with at most 200 normalised
  characters of page furniture after it, and the rest starts the next span of the same source
  with at most 200 characters of running header before it) `: the quote continues on
  <next locator>; quote within one page`, or, cited on the page where it ends (probe-5 Gemini
  50115c10 p44), `: the quote begins on <previous locator>; quote within one page`; a column
  interleave (the quote is two runs of the span, in order, with other span text between them)
  `: the quote matches the span as two runs separated by interleaved text (columns or table
  cells) at offset N; quote one contiguous run or choose another locator` when at most 400
  normalised characters separate the runs (`quotes.INTERLEAVE_GAP_CHARS`), else `as two separate
  runs on this page` with the same advice. Offsets count
  characters of the normalised quote (for the interleave, the first run is its first N
  characters); every run has at least two words. Otherwise the issue is unchanged. Against the
  main checkout's pack this names Sol p104 (probe-4 and probe-6) and Grok p102 as interleaves,
  Sol p13 as a case change, Gemini p76 and p44 as straddles; wrong-page quotes, Gemini's p84 year
  and its whole-row p102/p104 reassemblies (cells out of order) stay unclassified. The journal
  keeps issue lines of up to 600 characters (`execution.MAX_ISSUE_CHARS`, 300 until task 7.0) so
  the clause reaches the MC-7 REPAIR prompt whole.
- **Effort.** `high` by default; `xhigh` is sent only where the catalog lists it (the Luna entry does,
  the GLM entry does not). Otherwise the nearest lower supported level is sent and the request,
  mapping and catalog efforts are recorded; provider acceptance is `null` with a reason.

## Retention layout

`artifacts/model-tests/<experiment=batch id>/<case>/<model with / as __>/<attempt id>/` holds
`request.json` (written before sending), `response.json` (an envelope keeping the exact bytes and their
SHA-256), `output.md`, `events.jsonl`, `metrics.json`, `checks/`, `render/not-run.json` and
`manifest.json` last. A directory without `manifest.json` is an incomplete attempt. Files are never
overwritten, with one exception: `live reconcile` rewrites the `ledger` block of `metrics.json`
(keeping the replaced values; see Charge reconciliation). Unknown metrics are `null` with a `_reason` sibling; provider values, local measurements
and estimates are separate objects.

## CLI and Make targets (Task B)

`deploy-vii live {probe,module,regression,canary,corpus,reconcile,schema-check}` (`live/cli.py`;
`reconcile` is described under Charge reconciliation below, `schema-check` at the end of this
section). Common options of the four batch commands:
`--directory` (execution journal; cells run on journal copies under `<directory>/live/<batch>/`),
`--settings`, `--cap USD` (required; positive; at most the settings cumulative ceiling), `--seed`
(default random, recorded in the report), `--batch-id`, `--artifact-root`, `--effort`, `--catalog`
(saved models JSON; without it the catalog is fetched), `--report-directory`, `--max-tokens N`
(task 2.10: the completion budget of every call in the batch, every model alike, default 16000,
`runner.DEFAULT_MAX_TOKENS`; a positive integer, no per-model syntax; it goes through the context
fit below, into each manifest's `budgets.max_tokens` and into the report header),
`--timeout SECONDS` (task 7.0c: the request deadline of every call, every model alike, default 600,
`client.DEFAULT_TIMEOUT_SECONDS`; a positive finite number in Python float syntax, so `1e3` is
1000 s; into each manifest's `budgets.timeout_s` and `budgets.deadline_s` and into the report
header as `- Timeout:`, shown as a float, `1800.0`; Sol at about 70 completion tokens a second
needs up to 15 minutes for 64,000 tokens, so raise it with the budget; `make live-module` takes
`TIMEOUT=`). There is no key
option: the runner reads the DC-7 file from settings at dispatch, taking the token at
`credential_token_index`.

- The ledger is `<artifact-root>/.ledgers/<batch>.jsonl`. Its `open` line (the cap) is written
  together with the first reservation, which binds the cap; a later run with another cap raises
  `LedgerError` and sends nothing. Before a ledger is opened the CLI replays every ledger under
  `.ledgers/` and refuses when their held plus settled spend plus `--cap` exceeds
  `cumulative_ceiling_usd` (the error names both amounts); the per-batch cap binding and this
  cross-batch check are separate. The same batch's own leftover ledger (for example after a crash)
  counts toward that sum as well as the new `--cap`. The cross-batch check is unlocked and advisory:
  concurrent batches can each pass it, and the overshoot is bounded by the sum of their caps. Live
  batches are run one at a time (one owner per worktree). Seeds of cells are strictly increasing, so they are distinct.
  An existing `live-<batch>.md` is never overwritten.
- `probe`: per eligible model, `--draws-per-model` cells of CP-0, `source_context`, `financials`.
  `canary`: one cell per eligible model over CP-0 and the four CP-1 steps. `module --module`: one
  seeded draw; CP-0 runs `source_readiness`, CP-1 runs CP-0 first (its prerequisite) then the four
  steps; other modules have no live step contract and are refused before spending.
  `regression`: cases `cp0` and `cp1`, every candidate once per case in an order shuffled by the
  seed; it refuses a pool with an ineligible arm.
- The catalog-rule pool (no `--models`) is `settings/project.toml` `[[model_tests.candidates]]`,
  with `default_effort`/`complex_effort`. Since the decision 0005 amendment (user decision,
  22 Oct 2026), it is GPT-6.1 Sol (`openai/gpt-6.1-sol`) alone at `high`, so every cell's draw is
  trivial and `regression` runs one arm per case. The earlier Luna / GLM 5.3 Flash / DeepSeek
  pool is superseded, and its stored outputs and replay entries are retained.
- `--models ID[@EFFORT],ID[@EFFORT],...` (task 2.8; `probe`, `module`, `regression`, `canary`)
  replaces the settings pool with the user's models, in the given order, and labels the pool
  `user-selected` in the report header (`Pool: user-selected (coordinator ruling 22 October 2026)`;
  `Pool: catalog rule` otherwise) and in every manifest (`pool_label`). Draws per model are
  unchanged (`probe` keeps `--draws-per-model`); `regression` keeps its seeded shuffle of the
  given arms. Entries are comma-separated; `@EFFORT` is one of `minimal, low, medium, high, xhigh,
  max`; without it the model gets `--effort` or the settings default. A repeated id or an unknown
  effort is refused at parse time. Eligibility is still checked per model: an id absent from the
  catalog fails closed with the id named (exit 2, nothing sent, no usage check); a model whose
  catalog entry does not list `max_tokens`, `reasoning`, `response_format` and
  `structured_outputs` (every parameter the request carries), or lists no `context_length`, is
  recorded `ineligible: <reason>` in the Pool table before any draw. `reasoning_effort` is not
  required. The context that counts is the smaller of the entry's `context_length` and
  `top_provider.context_length`.
- Effort under `--models`. Where the entry lists `reasoning_effort`, the model's effort goes through
  `resolve_effort` as before (a level the catalog does not list for it is mapped to the nearest
  lower one and recorded as mapped). Where it does not (MiMo-V2.6-Pro), no effort value is sent:
  the request carries `reasoning: {"enabled": true}` and the manifest `effort` block records
  `sent: null, reasoning_enabled: true, basis: "catalog lists no reasoning_effort; provider
  default reasoning depth"`. That is the strongest setting this runner can request for such a model
  without guessing a parameter the catalog does not list. The Pool table shows the requested and the
  sent effort and the largest per-attempt reservation of each model.
- Context fit. After the prompt bound is computed and before the ledger reserves, a model whose
  `context_length` is below bound + `max_tokens`, or whose `top_provider.max_completion_tokens` is
  below `max_tokens`, is recorded `ineligible: context <n> < bound <m>` (m = bound + max_tokens):
  the attempt is sealed with status `ineligible`, nothing is sent or reserved, the ticket is
  untouched and the cell stops. It applies to every pool, since the check needs the step's prompt.
  A repair attempt can hit it too: the repair prompt carries a REPAIR block, so its bound is
  larger than the first attempt's, and a model that fitted the first attempt can be
  `ineligible` for the repair (sealed the same way; the repair ticket stays pending).
- For `probe`, `canary` and `regression` the seed of each cell is the first seed at or after the
  base seed whose recorded draw selects the intended model, so coverage is guaranteed and the draw
  record stays honest. A cell stops at its first step that is not accepted (no automatic repair).
- CP-0 gate outcome (task 2.10). An accepted CP-0 whose T8 `exact_command` for the next module is
  not `Run <id>` (a CONDITIONAL or BLOCKED consumer) makes `Execution.begin` raise
  `execution.NotAuthorized`, a `ValueError` subclass; `_run_cell` catches exactly that type around
  `store.begin`, appends a row with status `not-authorized`, attempt `none`, class `ok`, USD 0 and
  0 issues, writes the write-once record `<artifact-root>/<batch>/not-authorized/<cell>.json`
  (`live-step-not-authorized/1`: cell, case, step, module, model, seed, cohort, the cell's CP-0
  attempt id `cp0_attempt_id`, the T8 command texts, the reason; a record that is not JSON, not
  UTF-8 or of another shape is a usage error naming its path) and ends the cell. Nothing is sent
  or reserved, the batch goes on with the next cell and `Stopped` stays `no`. Every other
  `begin` refusal still aborts the batch (probe-4: Sol's CONDITIONAL CP-1 raised a bare
  `ValueError` and aborted). `NotAuthorized` comes from `current_inputs`, which `finish`,
  `submit_step` and `view` also call: if CP-0's head changes while a consumer's ticket is open
  (for example a CP-0 rerun that no longer authorizes it), those paths raise it too, and there
  it is not caught: the batch aborts, as for any journal fault.
- Exit 0 on completion; 3 when the cap stopped the batch; 2 on any usage, settings, catalog,
  credential, ledger, transport or journal error. The report is written even when a batch aborts.
- Reports (`live-<batch>.md`): command, seed, cap and ledger totals, catalog source and hash,
  registry-derived module counts, max tokens, cells planned with steps run and steps not
  authorized by CP-0, the pool with exclusion reasons, and a per-step table (cell, model, seed,
  attempt, status, classification, cost, issue count). Task 7.0: an attempt with no model
  payload (status `no-response`: a timeout, an HTTP error or a provider error inside a 200, a
  deadline hold) shows `-` for its issue count and is counted in the Cohorts table's
  `No response` column, never as `Rejected`; the Pool table prints each model's largest
  `Prompt token bound` (the reservation's prompt bound, also for an attempt sealed ineligible)
  beside its largest reservation. The reconciled report lists the
  not-authorized steps from their records after the retained attempts (a record of another shape
  is refused before any lookup). No prompts, responses, source text or validator wording.
- Make: `replay` (pytest, below), `live-probe CAP=`, `live-module MODULE= CAP=` (task 7.0: also
  `MODELS=`, `MAX_TOKENS=`, `BATCH_ID=` and `SEED=`, each passed as its option only when set),
  `live-regression CAP=`,
  `live-canary CAP=`; `DIRECTORY=` (default `artifacts/execution`) names the journal.

### `live schema-check` (task 2.11)

`deploy-vii live schema-check --models ID,ID,... [--steps STEP,...] [--cap USD]` asks each
provider for its verdict on each sent step schema before a batch spends on it. Per model and step
(default steps: all five in `STEPS` order) it sends one request through the normal `ChatClient`
with the DC-7 key path and the same classification: the step's `response_format` exactly as a
probe sends it (`strict: true`, the relaxed strict copy), one user message ("Reply with one JSON
object that conforms to the response format."), `max_tokens` 16 and no `reasoning` parameter (the
provider default applies; `ChatRequest(reasoning=False)`). Routing stays pinned (`allow_fallbacks:
false`, `require_parameters: true`). `@EFFORT` on `--models` is refused (nothing to send it with);
eligibility is checked as for `--models` batches and an ineligible model gets one `ineligible`
row per step, unsent. Each call is reserved and settled in `<artifact-root>/.ledgers/<batch>.jsonl`
under `--cap` (default US$0.05; a call costs about US$0.0005, but the reservation is the
worst case, `ceil(request bytes / 3.0) + 64` prompt tokens at the pinned prompt price plus 16
completion tokens; the prompt bounds are 1,628 (`source_readiness`), 2,450 (`source_context`),
10,446 (`financials`), 2,044 (`narrative`) and 924 (`readiness`) tokens). The cumulative-ceiling
check and the account-usage records before and after are those of any batch, so `live
reconcile --batch-id schema-<date>` settles a held charge. The default batch id is
`schema-<UTC date YYYYMMDD>`; a second run that day needs `--batch-id`. Evidence goes to
`<artifact-root>/<batch>/schema-check/<model>/<attempt>/` (request, response, events, metrics,
checks, then `manifest.json` with schema `schema-check-attempt/1`: model, step, status, class,
HTTP status, `error_detail`, the sent `schema_sha256`, `schema_relaxations`,
`schema_keywords_unverified`, budgets, pinned candidate). Nothing is submitted: no journal copy,
no execution journal entry. A cap refusal seals the attempt `refused` and stops the batch (exit 3);
a 402 stops it as DC-8 (exit 4); a connection failure settles the reservation as held and aborts
(exit 2). Otherwise the exit is 0 whatever the verdicts.

The report `live-<batch>.md` has one row per (model, step): outcome (`accepted` when the
provider answered `ok` or `truncated`, so it took the schema; `http_error`; `other` for a timeout,
fallback or credit refusal; `ineligible`; `refused`), class, HTTP status, USD, attempt, the sent
schema hash, the relaxations, `Keywords` (every JSON-Schema keyword the sent schema uses,
`title`/`description` left out, so accepted and rejected schemas can be compared by eye; also
`schema_keywords` in the manifest; then `schema.schema_shape`, for example `depth 12 (7 objects),
232 properties`: the longest chain of schema nodes from the root with every `$ref` resolved, the
object nodes on the deepest chain of objects, and the properties written in the root and every
definition, each once; also `schema_shape` in the manifest), `Blocks later runs` and the provider
detail. The detail is
the client's `error_detail`, which since task 2.11 carries the upstream provider's own message
from OpenRouter's `error.metadata.raw` (prefixed with `provider_name` and `provider_error_code`,
key scrubbed, capped at 500 characters with `[truncated from N chars]`), for example `HTTP 400:
Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format
'source_context'. Please ensure it is a valid JSON Schema.` No prompt, response body or content
is shown.

Runner use. `probe`, `module`, `regression` and `canary` read every `schema-check-attempt/1`
manifest under their artifact root before the first cell (an unreadable one fails the batch
before any spend). Only verdicts on the schema count: an `accepted` row, or an HTTP 400 that is
schema-shaped (`runner.schema_shaped`: provider error code `invalid_json_schema`, or a detail
saying "invalid schema" (or `invalid_json_schema`) or naming `response_format`; a bare
`json_schema` can name the request feature and does not count), recorded as `schema_rejection: true` with
`provider_error_code` in the manifest. The latest such verdict per (model, step, sent schema
sha256) wins, by `finished_at` then batch id. A cell whose step has a standing rejection is
sealed `ineligible: schema rejected by provider (<batch>)` before anything is reserved or sent,
exactly like a context misfit, and the cell stops. A later accepted check lifts the rejection,
and a changed schema has a new hash, so an old verdict never blocks it. Review fix (2.11 round 1):
any other 400 never blocks and never lifts, because schema-check sends what a real run does not
(16 tokens, no `reasoning`, a one-line prompt), and a 400 about those ("max_tokens below
minimum", "reasoning required") would otherwise block the paid path with nothing able to lift
it. Such a row shows `no: the 400 does not name the schema`; Google's only text, "Request
contains an invalid argument", is one (the bisect still shows which variant Google accepts). A
record written before the field existed is non-blocking. Run `schema-check` for every pool
change before a CP-0 call.

`--bisect` (task 2.11 fix round 1, report only). For every (model, step) whose plain check
answered HTTP 400, schema-check then sends variants of the sent schema, each removing or
rewriting one suspect class (`schema.bisect_variant`), in this order, and stops at the first one
accepted: `one-of-to-any-of` (`oneOf` + `discriminator` to `anyOf`, no discriminator),
`drop-format`, `drop-pattern`, `drop-items-bounds` (`minItems`/`maxItems`), `open-object` (a node
whose `additionalProperties` is present and not false is reported as an open object and skipped,
never sent: closing it would change the contract; no step schema has one),
`any-of-null-to-type-union` (`anyOf: [X, {"type": "null"}]` to X with `type: [T, "null"]` where
X has one string type; a bare `$ref` X is inlined one level), `split-mixed-types` (a mixed-type
enum, or a `type` array of more than two types, to one `anyOf` branch per type), then (fix
round 2, after the first live bisect left OpenAI `source_context`, `financials`, `readiness` and
Google `financials` with none accepted) `nullable-array-to-anyof` (`type: [X, "null"]` with
`items` to `anyOf: [{type: X, items, minItems/maxItems}, {"type": "null"}]`),
`nullable-array-required` (drops `"null"` from those array types; the Bisect table's `Touches`
column lists the `Owner.field` paths it changes, because a reply could then no longer say null),
`anyof-enum-null-to-type-union` (`anyOf: [{enum, type: T}, {"type": "null"}]` to `type: [T,
"null"]` with the enum), `strip-titles`, `inline-refs` (every `#/$defs/` reference replaced by
its definition, `$defs` removed; a cyclic or unresolved reference makes the variant `not
sendable`, with the reason, and nothing is sent), and `all` (every rewrite at once except
`nullable-array-required`). A variant that leaves the schema unchanged is `not applicable` and
not sent. Each sent variant is one call like the plain check (same request otherwise, same ledger and
cap), with evidence under `<artifact-root>/<batch>/schema-bisect/<model>/<attempt>/` and manifest
schema `schema-bisect-attempt/1` with `variant` and `variant_base_schema_sha256` (the
relaxations named are that base schema's: `schema_relaxations_of`); `schema_rejections` reads `schema-check` only,
so a variant's verdict never blocks or lifts a real run, and no real run ever sends a variant.
The report adds a `## Bisect` table (model, step, variant, outcome, class, HTTP, USD, attempt,
the variant's schema hash, provider detail, touches) and `## First accepted variant`, one line per
bisected (model, step): `first accepted variant: <name>`, `none accepted`, or `not finished
(cap)` when a variant's reservation is refused (the batch stops, exit 3), or `not finished
(aborted)` when the batch stops on anything else (for example a 402; the report is still
written). Numeric bounds
(`minimum`, `maximum`, `exclusive*`, in `financials`) are not one of the classes.

## Replay corpus (Task C, tier I2)

`make replay` is `uv run --locked pytest tests/product/test_replay.py -q -rs`. The former
`deploy-vii live replay` placeholder was removed: the synthetic stores come from test fixtures, so
pytest is the single entry point and the CLI cannot report a pass the suite would not.

`tests/product/replay/<step>/<case-id>.json` holds `{step_id, payload, input_hashes, expected:
{validator_outcome: accepted|rejected, issues}, provenance: {batch_id, model, attempt_id, cohort}}`.
Replay rebuilds the synthetic store, checks that its journal input hashes equal `input_hashes`,
submits the payload through the journal's own `submit_cp0_review` and compares outcome and issues.
Since decision 0008 each entry carries `payload_kind`: `journal` for the synthetic seeds (a stored
contract supplied to the journal directly), `model` for a model payload, which replays through
`submit_model_payload` like a live attempt. An entry revalidated to the single issue `schema:
pre-0008 submission shape` carries `superseded_by: "0008"`.
Verdicts other than `ok` fail the entry and name it: `stale-inputs` (the synthetic store cannot
reproduce the hashes; the reason names the inputs), `upstream-invalid` (a retained earlier step is
now rejected), `outcome-changed`, `issues-changed`,
`unsupported-step`, `malformed`. Nothing is skipped silently. Issue text is compared exactly, so
a deliberate validator wording change shows up as `issues-changed` and the entry is regenerated.

`deploy-vii live corpus <attempt-dir> <case-id> [--root DIR]` writes an entry from a sealed attempt
(manifest.json plus output.md); it refuses attempts that never reached the validators
(fallback, no-response, interrupted), attempts whose output was credential-scrubbed, unreplayable
steps and existing entries (unless `--replace`). The four seed entries are labelled synthetic
(`synthetic` in the case id and `provenance.batch_id`) so `make replay` is green before any probe.

Optional keys beyond the five of the brief: `pack`, the name of a registered synthetic builder
(`synthetic-cp0`, `synthetic-cp1` in `tests/product/replay_support.py`; unknown name is `malformed`),
and `upstream`, `{step_id: payload}` of the earlier CP-1 steps, submitted in order through
`submit_cp1_step` before the target payload (it must hold exactly the predecessors, else
`malformed`). `live corpus` sets `pack` only when the attempt's `prepared-pack` hash equals a
registered builder's hash (`corpus.SYNTHETIC_PACKS`; a test asserts they still match the builders)
and leaves it unset otherwise, so a probe on another pack replays as `stale-inputs` with the
reason "no registered synthetic pack" until that pack is registered. `upstream` is read from the
accepted sibling attempts of the same ticket (their `output.md`); a missing predecessor is a
`CorpusError`, never a guess. Replayable steps: `source_readiness` and the four CP-1 steps; seeded
and tested are `source_readiness`, `source_context` and `financials`.

To regenerate an entry after a deliberate validator change (`issues-changed`), rerun
`deploy-vii live corpus <attempt-dir> <case-id> --replace`; without `--replace` an existing entry is
never touched. For a real-pack entry, `--replace` alone rewrites the live record again; a
deliberate wording change needs `--replace --revalidate` (below).

### Real-pack entries (task 2.7a)

Probe-2 entries could not replay: `entry["pack"]` named no builder and the regenerated issues were
Pydantic shape errors from a store without the real pack. Ruling applied: real entries replay the
live validator where the pack is present and skip with the reason where it is absent (CI has no
artifacts).

- `live corpus` looks under `<repository>/artifacts/public-case/*/complete.json` (`--repository`,
  default this checkout) for the attempt's `prepared-pack` hash. A match adds `pack_sha256` (the
  hash already bound in `input_hashes`), `pack_source: "artifacts/public-case/<case-dir>"`,
  `live` (the attempt's `checks/validator.json`, which must equal the manifest's validator block)
  and `expected_basis: "live"`, with `expected` equal to `live`. Packs are never copied into Git.
- Replay of such an entry loads the pack with `load_pack` (completion marker and every original
  re-hashed), requires its hash to equal `pack_sha256`, opens a CP-0 ticket on a fresh journal,
  checks the input hashes and submits the payload. Verdicts: the pack directory absent is
  `skipped-pack-absent` (reason names the directory; never a pass; pytest reports it as a skip
  and `make replay`, now `-q -rs`, counts and lists it); present but not loadable or hashing
  differently is `stale-inputs`; `pack_sha256` not equal to `input_hashes.prepared-pack`, both
  `pack` and `pack_source`, or a `pack_source` outside `artifacts/public-case/<dir>` is
  `malformed`. Real-pack replay covers `source_readiness` only (a CP-1 step would need the CP-0
  payload first); other steps are `unsupported-step`.
- `live corpus --replace --revalidate` regenerates `expected` with the current validator over the
  real pack (it must be present) and sets `expected_basis: "revalidated"`, keeping `live`
  unchanged. An outcome change is refused unless the validator fix that caused it is named with
  `--outcome-changed-by <task-or-decision>` (task 2.9, coordinator ruling: recording
  validator-driven outcome changes is what tier I2 is for); the entry then carries
  `outcome_changed_by: <reason>`, `expected_basis: "revalidated"` and `live` as recorded. The flag
  is refused without `--revalidate`, when blank, and when the outcome did not change. A test
  checks every real entry: `expected` equals `live` when the basis is `live`; the outcome equals
  the live outcome unless `outcome_changed_by` is present (then a non-empty reason, the
  `revalidated` basis and a different outcome are required); and, where the attempt's evidence is
  present, `live` equals its `checks/validator.json`.
- Seeded: `probe-2-glm-5.3-flash-{1,2,3}` (the three GLM attempts, all `rejected`; 17, 1 and 1
  recorded issues). Draws 2 and 3 were then regenerated with `--replace --revalidate` after the
  issue-text change below (their one recorded issue held seven Pydantic errors; `expected` now
  lists the seven short issues `consumers.1` to `consumers.7`, `live` keeps the original text).
  Task 2.7b regenerated all three with `--replace --revalidate`: their payloads are stored reviews,
  the superseded pre-0008 shape, so `expected` is now `["schema: pre-0008 submission shape"]`
  (still `rejected`), with `superseded_by: "0008"`; payloads and `live` are unchanged. Verified
  against the main checkout's pack: all three replay `ok`.
- Task 2.9 added `probe-3-glm-5.3-flash-dccfe8f5` (accepted live and now) and
  `probe-3-gpt-6-luna-8634aa17` (rejected live with seven per-page mismatches, now with two
  wrong-page quotes), both `--revalidate`, and `probe-3-gpt-6-luna-f136b227` and
  `probe-3-glm-5.3-flash-76fc5c95` (rejected live with 4 and 2 issues, now `accepted` with none)
  with `--revalidate --outcome-changed-by "task 2.9 (decision 0008 amendment, 22 Oct 2026)"`.
  Not added: GLM f0391c45 is a `source_context` attempt, which real-pack replay does not cover;
  its verbatim texts are unit fixtures (`test_live_submission.py`, `test_source_context.py`).
- Task 6.2 added the `page:N` locator label to the prose rule, so
  `probe-3-glm-5.3-flash-76fc5c95` stays `accepted` under it (its `outcome_changed_by` now
  also names task 6.2); the interim coordinator revalidation `ae15823` is superseded.
- Task 2.10 (hyphen-wrap) changed no entry: replayed against the main checkout's pack, every
  entry is still `ok` (no outcome or issue text moved; the spans the rejected Luna 8634aa17
  quotes cite have no hyphen line wrap). Probe-4 attempts were not added; the Sol 9594d016 spans
  and quotes are unit fixtures in `test_readiness.py`.
- Task 7.0 (mismatch text) changed one entry's wording: `probe-3-gpt-6-luna-8634aa17`'s first
  issue now quotes 200 characters instead of 60 (no clause applies to its two quotes). The
  corpus tool cannot revalidate it (`live corpus` reads the run/1 pack hash from the attempt
  manifest, see task 2.11 below), so a script ran the tool's own `corpus._validate_now` over the
  stored entry (its payload, input hashes and `czr-fy2025-v2` pack in the main checkout) and
  rewrote `expected` only, refusing any change of outcome or issue count; `live`,
  `expected_basis: "revalidated"` and every other key are as stored. With the main checkout's
  packs linked in, all seven real entries replay `ok`.
- Task 2.11 re-keyed the seven real entries to the `run/2` pack (main's `deploy-vii prepare`, 22
  October 2026, same PDF; pack sha256 77395ae0091b14ec0a5539ae45d3be0b272f2931c00a8a53e3e39d16eddeaf3c,
  was 0132418198863b1c7b4fbad4ffc4621fec852eec794b53b98ad450ecc23f776b at
  `artifacts/public-case/caesars-fy2025-preparation-1`, `run/1`, which the `run/2` loader rejects).
  A re-prepared case pack is placed as its own `artifacts/public-case/<case-dir>/` (here
  `czr-fy2025-v2`, whose `complete.json` records the new hash), so `find_case_pack` finds it by
  `pack_sha256` with no code change. Since task 7.0 `find_case_pack` returns the first directory
  (in name order) whose marker matches and whose pack loads under the current contract; one that
  cannot be read or loaded is skipped with a logged warning naming it and the reason. Only `pack_sha256`, `pack_source` and
  `input_hashes.prepared-pack` changed; each entry was revalidated on the new pack first and its
  outcome and issues were identical, so `expected`, `live`, `expected_basis` and
  `outcome_changed_by` are as before. `live corpus` cannot re-key (it reads the run/1 hash from
  the attempt manifest), so a script applied the three keys; `--outcome-changed-by` does not apply
  (no outcome changed). Against the main checkout's packs all 13 entries replay `ok`.

### Shape-error issue text (task 2.7a)

A payload that fails the Pydantic parse (`cp0_workflow`, both `cp1_workflow` parse sites, and
`readiness.validate_review`) now yields one issue per error, `<field.path>: <message>`, with no
library URL and no `input_value` repr (`readiness.shape_issues`); an unparseable payload is
`(root): Invalid JSON: ...`. Replay compares text exactly, so this is stable across Pydantic
upgrades, and the report's Issues column counts each error.

Earlier note corrected: the synthetic CP-1 pack is hash-stable. The instability was
`tests/product/test_model_readiness.py:31`, where `dict.fromkeys(ACCOUNT_IDS, ...)` iterated a
frozenset (`financial_contracts.py:24`) so `ready_case()` rows, and the pack hash, varied with
`PYTHONHASHSEED`; it now iterates `sorted(ACCOUNT_IDS)`, and a test checks the CP-1 pack hash across
three hash seeds.

## No-credit backup cohort (decision 0006 DC-8)

`live/cohort.py` and `live/credit.py`. The runner never switches on its own. This no-credit
route (native Luna, else a labelled proxy cohort; settings `no_credit_fallback`) is the user's
standing DC-8 instruction, not the test pool, so the 22 October 2026 pool amendment (Sol only)
leaves it unchanged.

- `credit_state(client)` calls `GET /api/v1/key` through a `ChatClient(transport, key_path=...,
  key_index=...)`; the client reads the DC-7 file for that one call, so no key value reaches
  `cohort.py`, and returns a `KeyStatus` carrying that call's key note. `limit_remaining`
  at or below 0, or a 402, gives `exhausted = true`. A `null` limit (a key with no spending limit)
  says nothing about account credit: it is recorded null with a reason and `exhausted` stays unknown.
- A 402 on dispatch retains the attempt (manifest `credit` block), settles the ledger at zero, leaves
  the journal ticket pending (credit is not a model failure, so the repair is not consumed) and
  raises `CreditExhausted`. `dispatch(..., credit=state)` raises it before sending when the state is
  already exhausted; the message names the ticket that stays pending. Nothing is substituted: native Luna or a proxy is a coordinator decision.
  The `credit=` pre-send refusal is library-only: the CLI never passes it. In the CLI a 402
  mid-batch aborts the batch (report line `Stopped: aborted: CreditExhausted`), prints
  "ticket pending; coordinator decision (DC-8)" and exits 4 (`EXIT_CREDIT`; 2 is a failure, 3 a
  cap stop). `accept_proxy_payload` has no CLI entry: the coordinator calls it from Python.
- Replay corpus entries carry a required `provenance.cohort` taken from the attempt manifest
  (`synthetic` for the seed entries, `proxy:<label>` for proxy attempts); the replay verdict lists it.
- A proxy attempt after a cap overrun is refused by its zero reservation (the cap's job); the
  attempt directory then holds only `request.json`, no manifest. The proxy manifest `credit` block
  holds the `CreditState` passed as `credit=` (null if none) and `backup.caller_supplied_payload`.
- `native_luna_check()` looks for a `codex` executable with `shutil.which` and records path or
  absence; `native_luna_available()` returns its `available` (None only if the lookup itself failed).
  Installed does not mean entitled.
- `accept_proxy_payload(step, payload, agent_label, store=, ticket_id=, ledger=, writer=, batch_id=)`
  runs the payload through `submit_cp0_review` / `submit_cp1_step`, retains the seven artifacts under
  model directory `proxy:<label>`, and writes `cohort: "proxy:<label>"`, `poolable: false`,
  `qualification: false`, unknown usage as null with a reason. The ledger line format is unchanged: a
  zero reservation settled with `actual_usd: null`, reason `proxy`; the cohort is the attempt-id
  prefix `proxy-<label>-`. It spends nothing, so it never moves the cap.
- `render_report` groups by cohort: pool rows under `## Steps`, every other cohort under
  `## Steps (<cohort>)`, and a `## Cohorts` table (attempts, accepted, rejected, pooled, qualification).
  Only the pool cohort is pooled; proxy cohorts show `Pooled: no`, `Qualification: false`.

## Strict response schemas (task 2.7a)

Probe-2 showed that OpenAI refuses the raw `model_json_schema()` under `strict: true` (HTTP 400
`invalid_json_schema`, "'required' is required to be supplied and to be an array including every
key in properties. Missing 'limitation'"; US$0). `live/schema.py` now builds the schema sent in
`response_format`: a pure transform of a copy of `model_json_schema()` in which every object node
has `additionalProperties: false` and `required` equal to all of its property keys; a property
that had a default becomes nullable instead (`type` gains `"null"`, an enum gained `null` until
task 2.11 and now keeps its values only, and
`$ref`, union and `const` nodes are wrapped in `anyOf` with `{"type": "null"}`); `default`
keywords are removed; `$defs` stay inside the schema. The tag of a discriminated union (the
narrative `kind`) stays required and non-null, because a null tag would leave the branch
unresolvable. Since task 2.7b the system prompt prints this same strict schema (compact JSON,
sorted keys; a test checks it equals `response_format`), and `schema_sha256` hashes the printed
text.

Contracts and hashes do not change. Before a payload reaches the journal, `schema.normalise`
replaces each null that stands for an omitted defaulted field with that field's default, walking
the payload with the original schema (the same field list); fields that were already nullable keep
their null. A payload with nothing to resolve reaches the journal byte-for-byte; a rewritten one
keeps every number's exact digits. The resolved paths are a `payload_nulls_resolved` event;
`output.md` keeps the raw model text. Proxy payloads and replay apply the same normaliser.

Known (fetched OpenAI docs, unversioned): `additionalProperties: false` and full `required` are
mandatory; optional means `"null"` in the type; `$defs` and recursion are supported; the keywords
`unevaluatedProperties`, `propertyNames`, `minProperties`, `maxProperties`, `unevaluatedItems`,
`contains`, `minContains`, `maxContains` and `uniqueItems` are unsupported, and none appears in a
step schema (a test checks). Still unknown: acceptance of `pattern`, `minLength`, `maxLength`,
`format`, `const`, `oneOf`/`discriminator` (narrative only), `minItems`/`maxItems` and the numeric
bounds. They are kept, not stripped, and each attempt manifest lists the ones its schema uses as
`schema_keywords_unverified`. A schema refusal costs US$0 on Luna, so a probe settles them. Since
task 2.10 the `source_readiness` submission schema uses one of them, `minItems: 1` on `analysis`.

### The sent copy (task 2.11)

Probe-5b: OpenAI refused the `source_context` schema (Sol 5ae16ef9, HTTP 400
`invalid_json_schema`, "Invalid schema for response_format 'source_context'. Please ensure it is a
valid JSON Schema.", no keyword named; US$0) minutes after accepting the readiness schema. The
schema was unchanged since probe-3 (same `schema_sha256`). Of the constructs only the refused
schema carried, three are now rewritten on the way out by `schema.relax`, a pure and idempotent
pass over the strict copy (`strict_schema = relax(strict_copy)`):

| Relaxation | Strict copy | Sent |
| --- | --- | --- |
| `nullable-enum` | `{"type": ["string", "null"], "enum": ["a", "b", null]}` | `{"type": ["string", "null"], "enum": ["a", "b"]}` (OpenAI's documented shape) |
| `const-to-enum` | `{"const": "v", "type": "string"}` | `{"enum": ["v"], "type": "string"}` |
| `drop-length` | `minLength` / `maxLength` | dropped |
| `nullable-array-anyof` (round 3) | `{"type": ["array", "null"], "items": X, "maxItems": n}` | `{"anyOf": [{"type": "array", "items": X, "maxItems": n}, {"type": "null"}]}` (annotations stay outside) |
| `oneof-anyof` (round 3) | `{"oneOf": [...], "discriminator": {...}}` | `{"anyOf": [...]}` (no discriminator) |

Round 3 rests on two live bisects of the sent schema (`schema-check --bisect`, batches
`schema-2026-10-22-bisect` and `schema-2026-10-22-bisect2`). OpenAI (GPT-6.1 Sol) accepted
`narrative` only once `oneOf` + `discriminator` became `anyOf` ("'oneOf' is not permitted"). It
rejected `source_context`, `financials` and `readiness` under every first-round variant, `all`
included. In the second bisect it rejected every variant before `nullable-array-to-anyof` and
accepted all three under it. The bisect stops at the first accepted variant, so the variants after
it were not sent. A plain check on the round-3 sent schemas (batch `schema-2026-10-22-r3`,
[live-schema-2026-10-22-r3.md](tasks/implementation/live-schema-2026-10-22-r3.md)) then had all
five step schemas accepted by Sol. So OpenAI refuses a nullable array written as a `type` union inside a strict schema and
accepts the same array as an `anyOf` with a null branch. Both rewrites are lossless. All 31
nullable arrays in the CP-1 step schemas are fields whose stored default is `[]` (`normalise`
turns a null back into `[]`). The reply is validated by the stored Pydantic contract, whose
discriminated unions are unchanged. A tag stays a required one-value enum in each branch, so an
`anyOf` branch is still unambiguous. A node with both `oneOf` and `anyOf` cannot be relaxed and
raises `ValueError`. Records:
[live-schema-2026-10-22-bisect.md](tasks/implementation/live-schema-2026-10-22-bisect.md),
[live-schema-2026-10-22-bisect2.md](tasks/implementation/live-schema-2026-10-22-bisect2.md).
Since round 3, the bisect variants `one-of-to-any-of`, `nullable-array-to-anyof` and
`nullable-array-required` find nothing to change in the sent schemas, and are `not applicable`.

`pattern`, `format`, `minItems`, `maxItems`, `anyOf` and `$ref` are kept. A shape the pass cannot
express (a null `const`, `const` beside `enum`, a null enum member whose type does not admit null)
raises `ValueError`, so nothing is sent for it; no step schema has one. The manifest lists the
relaxations applied as `schema_relaxations` (in that order, only those applied; `[]` for the
`source_readiness` submission, whose sent schema is unchanged), `schema_keywords_unverified` is
computed on the sent schema (so it no longer names `const`, `minLength` or `maxLength`), and
`schema_sha256` hashes the sent schema, which the prompt prints. Validation is unchanged:
`normalise` walks the original schema and the Pydantic contracts enforce every length, constant
and enum on the reply, so a dropped constraint is still a validator issue (and MC-7 repair input).
The model no longer reads the length limits in the schema text. The plain `live schema-check`
on Sol for every step (batch `schema-2026-10-22-r3`) accepted the round-3 schemas.

## Errors inside a 200 body (task 2.7a)

OpenRouter commits `200 OK` before inference and pads a non-streaming call with whitespace while it
runs, so a failure mid-call arrives as a 200 whose body holds `{"id": "gen-...", "error": {"code",
"message", "metadata": {"error_type"}}}` (probe-2: three DeepSeek attempts, ~1.1 KB of whitespace,
then code 504 "A Timeout Occurred" at ~300 s, well inside the runner's 600 s). The client strips
the whitespace before parsing and classifies a 2xx body that carries an `error` object (with or
without choice content; it fails closed) by `error.code` and `error.metadata.error_type`: 504, 408
or an `error_type` containing `timeout` is `timeout`; 402 is `insufficient_credit`; anything else
is `http_error`. The detail is `HTTP 200 body error <code>: <message>` (key-redacted). A
whitespace-only or non-JSON 2xx body is `http_error` with "empty or non-JSON 200 body", never
`ok`. The body `id` becomes `provider_request_id` (manifest `served`) in every branch, which is
what `live reconcile` looks up. There is no automatic retry inside an attempt: each retry would
reserve again (US$0.28 per DeepSeek call in probe-2), so a retry stays a new, separately reserved
attempt chosen by the caller. A timed-out call has no usage, so it settles `unknown` with the
reservation held and `unreconciled: true`. Fixtures: `tests/product/fixtures/live/` holds the three
DeepSeek bodies and two 400 bodies, probe-2 Luna and probe-5b Sol `source_context` (their
`user_id` values replaced; nothing else). A non-2xx error's detail is `HTTP <status>: <message>`
plus, since task 2.11, `; <provider_name> <provider_error_code>: <provider message>` taken from
`error.metadata.raw` (its `error.message` when the raw text is JSON, else the raw text).

Task 2.10 (probe-4). A provider error can also sit inside `choices[0]` of a 200: DeepSeek
9d68b734 returned `finish_reason: "error"`, `choices[0].error` `{code: 502, message: "Upstream
error from OpenInference: Internal server error"}` and null content, recorded as `ok` before this
task. When `choices[0].error` is present or `finish_reason` is `error`, the result is `http_error`
(no new class) with content null and the detail `HTTP <code>: <message>` from that error object
(key-redacted), or `HTTP <status>: choices[0] finish_reason error without an error object`. The
usage is kept: a `usage.cost` settles the attempt (probe-4 charged 0, so the reserve is released;
the body's `upstream_inference_cost` is not what OpenRouter charged), and without one the
reservation is held (`unknown`, reconcilable), never an estimate from the tokens. The tests use a
body synthesised from the 9d68b734 shape with short reasoning text.

Wall-clock deadline (task 2.10). urllib's `timeout` bounds each socket operation, and the
whitespace keep-alive resets it, so 9d68b734 ran 1,029 s against `timeout_s` 600. The default
transport now fixes a deadline of `timeout_s` before the connection opens and reads the body with
`read1` (at most one socket read each), raising `TimeoutError` at the first read that returns past
the deadline; the client classifies it `timeout` with no usage, so it settles exactly as the
504-in-200 case (reservation held, `cost_basis: unknown`, reconcilable). A silent socket still ends
at the per-operation timeout, so the overrun past the deadline is at most one such operation.
An HTTP error status body is read as before (whole, per-operation timeout only): it arrives at
once, without keep-alive padding.
Unlike a 504-in-200, an expiry keeps no body and so no generation id: `live reconcile` reports it
unresolved ("no provider_request_id recorded") until the coordinator settles it. The deadline is per call, set by `--timeout` (default 600 s):
each socket operation and the whole-call wall clock both use it. Each manifest records
`budgets.deadline_s` beside `budgets.timeout_s` (the same value: whole call, and each socket
operation).

Settling a deadline-expiry hold. With no generation id there is nothing to look up, so the
generation endpoint can never price it and `live reconcile` leaves it held. The only evidence that
could replace the hold is the batch's account usage (`account-usage-{before,after}.json`, same key
token): the delta less the other pool attempts' measured costs (provider-reported, known-zero or
reconciled), and only when the held attempt is the batch's one unpriced attempt (the delta cannot
be split between two). Other spend on the account in the batch window can only make that residual
larger, never smaller. The ledger cannot record that today: every `adjust` line needs a generation
id, its sources are only `generation-endpoint` and `generation-404+usage-delta`, and the latter is
always 0 and needs a 404 for a named generation (`live/ledger.py` replay rules). So until a ledger
source for an id-less usage-delta adjustment exists (a change to `live/ledger.py` and
`live/reconcile.py`, not made in task 2.10), a deadline-expiry hold stands as spent, and the
coordinator records the usage-delta residual beside it in the batch notes, not in the ledger.

## Charge reconciliation (task 2.7a)

A settlement with an unknown cost holds the whole reservation as spent (`unreconciled: true`).
Probe-2 held US$0.838404 this way for three DeepSeek timeouts, 99.2 % of the batch's ledger
spend, against US$0.0069 of provider usage; plan acceptance needs the ledger to reconcile.

- **Ledger event `adjust`** `{attempt_id, previous_charged_usd, reconciled_usd, source:
  "generation-endpoint", generation_id, checked_at}`. Replay rules: at most one per attempt, only
  after its `settle`, only when that settle had no known cost (`actual_usd: null`; an estimate
  or provider-reported cost is never adjusted), `previous_charged_usd` must equal the settled
  charge, and the source must be `generation-endpoint`. The figure may be lower or higher than
  the hold; above the reservation it is an overrun. `adjust` checks no cap: it records money
  already spent. Totals, later reservations and the cumulative-ceiling check (`committed_elsewhere`)
  all read the adjusted charge. The rules live in the replay, so `Ledger.adjust` cannot persist
  a line the replay would refuse.
- **`deploy-vii live reconcile --directory DIR --batch-id ID [--artifact-root R]
  [--settings S] [--report-directory D]`** takes no cap and no key option. For every pool attempt
  of the batch whose `metrics.json` says `unreconciled: true`, it takes the generation id from
  `manifest.served.provider_request_id` or, for attempts sealed before 2.7a (probe-2), from the
  `id` in the retained `response.json` body (the source is recorded), and calls `GET
  https://openrouter.ai/api/v1/generation?id=<gen>` with the key read from the DC-7 file for that
  call (`credential_token_index` from settings). Record shape, from the OpenRouter API reference
  (`https://openrouter.ai/docs/api-reference/get-a-generation.md`, fetched 21 October 2026):
  `{"data": {"id": "gen-...", "total_cost": <USD>, "usage": <USD>, "upstream_inference_cost":
  <BYOK only>, "cache_discount": <nullable>, token counts, ...}}`; there is no `cost` field (an
  earlier input's "cost" was guide wording) and none is read. A 200 whose record (under `data`,
  or at top level) names the requested generation in `id` and has a non-negative numeric
  `total_cost` becomes an `adjust`, unless `usage` is present and differs from `total_cost`
  (then nothing is chosen between them). `metrics.json.ledger` is then rewritten
  with `cost_basis: "generation-endpoint"`, `unreconciled: false`, the new charge and a
  `reconciliation` block keeping the previous values. A 404 (observed on 21 October 2026 for all
  three probe-2 DeepSeek generations, whose calls timed out upstream), another status, a non-JSON
  reply, an absent, null, negative or non-numeric `total_cost`, a differing `usage`, a record
  whose `id` is not the requested one ("generation id mismatch"), a missing or malformed
  recorded id, or a ledger that holds no unreconciled settlement leaves the attempt unreconciled
  with the reason in `metrics.json` and the report; no figure is inferred. A connection failure
  (a generation lookup or the fresh usage reading below) stops the run (exit 2) after the report
  is written; adjustments already written in that run stay, and a rerun picks up the attempts
  still held. A fixture holds the documented example
  record verbatim (`tests/product/fixtures/live/generation-documented-example.json`).
  `metrics.json` is the one retained file reconcile rewrites (atomic replace); the ledger line is
  the authority, and a rerun after an interrupted write re-synchronises metrics from it without a
  new call. Proxy attempts cost nothing and are not looked up.
- **Reports.** A batch report row whose charge is a held reservation reads `reservation held
  <amount>` in the USD column, with a footnote. Reconcile writes
  `live-<batch>-reconciled.md` beside the batch report (regenerated on each run; the batch report
  itself is never rewritten): ledger totals after adjustment, every attempt of the batch with
  its final charge (cell ids from the journal copies under `<directory>/live/<batch>/`), and one
  row per lookup with its outcome and reason.
- **Account usage and a generation 404 (decision 0008).** Each `probe`, `module`, `regression`
  and `canary` batch writes `account-usage-before.json` (before any dispatch; a failure aborts
  the batch before spending) and `account-usage-after.json` (in a `finally`) under
  `<artifact-root>/<batch>/`: write-once `{schema: "account-usage-check/1", phase, recorded_by,
  credit}` with `credit` the `GET /api/v1/key` `CreditState` record (usage, limit, checked time,
  key-file counts). A failed after-check is printed, noted on any in-flight exception and
  written as `credit: null` with `failure` (documented fail-open: money is already spent, so it
  never replaces the batch's outcome; reconcile then leaves 404s unresolved). On a 404,
  `live reconcile` adjusts the held attempt to 0 only when the usage delta equals the sum of the
  other pool attempts' measured costs (provider-reported, known-zero or generation-endpoint)
  within US$0.000001: ledger `adjust` with `source: "generation-404+usage-delta"`,
  `reconciled_usd` 0 and an `evidence` object (status 404, both usage figures and times, the
  delta, the other attempts and their sum, the difference, the tolerance, who recorded the
  usage). Replay refuses that source with a non-zero figure or without evidence. A missing
  record, a usage that is not a number, checks made with different key tokens or a difference
  above the tolerance leave the attempt unresolved with the reason. Probe-2 predates the
  records: its holds stay unresolved until the coordinator writes the two files from the
  recorded checks (25.7172663 before, 25.724167155 after).
- **Account usage and a hold without a generation id (task 7.0).** A held pool attempt with no
  recorded generation id (a deadline expiry: nothing reached the provider's response, so there is
  nothing to look up; it used to stand as spent) is adjusted from the same usage window only when
  the delta is attributable to it alone: it is the batch ledger's only attempt without a measured
  cost, and every other ledger attempt is a retained pool attempt whose charge is measured
  (provider-reported or known-zero, or adjusted from the generation endpoint, read from the
  ledger line). It then takes the delta less those charges (a residual below zero within
  US$0.000001 is 0): ledger `adjust` with `source: "account-usage-delta"`, `generation_id: null`,
  the figure and an `evidence` object (both usage figures and times, the delta, the held attempt,
  the other attempts and their sum, the residual, the reservation, the tolerance, who recorded
  the usage). Replay refuses that source with a generation id, without evidence, or above the
  attempt's reservation. Two or more held attempts, a charge that is not measured (an estimate,
  a 404 zero), a residual below zero by more than the tolerance, a residual above the
  reservation (other spend on the account in the window, which the delta cannot tell apart) or
  a missing usage record leave the attempt held, with `no provider_request_id recorded; nothing
  to look up; <reason>`. `live reconcile` looks up attempts with a generation id first
  (`reconcile.lookup_order`), so a hold that becomes the only one after those lookups is
  attributed in the same run whatever order the attempt directories sort in. Fail closed on the
  safe side of the cap: the figure never exceeds the hold it replaces.
- **Usage unmoved since the after-check (task 7.0).** Both usage-window rules,
  `generation-404+usage-delta` and `account-usage-delta`, assume the after-batch check already
  includes every charge of the batch; the provider may bill a 404'd or given-up call later,
  which the delta would then omit. So either adjust also needs a fresh `GET /api/v1/key` reading
  at reconcile time, taken only once the rule's own conditions hold, equal to the recorded
  after-figure within US$0.000001 and read through the same key-file token
  (`reconcile.usage_unmoved`; the evidence adds `usage_now_usd` and `usage_now_checked_at`).
  Otherwise the attempt stays held with `usage moved since the after-check (<after> then, <now>
  now); not attributed; a later reconcile may retry` (or that the usage now is not reported, or
  is read through another key token), after `HTTP 404 ...;` or `no provider_request_id
  recorded; nothing to look up;` (decision 0008, task 7.0 amendment).

## Not covered here

Model-facing submissions for `source_context`, `financials` and the narrative steps (they keep
their stored contracts until their own MC-1 skeletons); a per-step repair budget and a
`FinancialSubmission` split (deferred by decision 0008); provider acceptance of the
`ReadinessSubmission` schema and first-pass validity after MC-1 (the rerun).
