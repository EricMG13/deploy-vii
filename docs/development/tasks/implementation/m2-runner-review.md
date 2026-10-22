# M2 model runner review note (Task D close)

Date: 21 October 2026. Scope: plan 2.5, decision 0006 DC-8. Result of Tasks A-D on the lane;
the live probe (2.6) and decision 0008 (2.7) are the coordinator's and have not run.

- Built: OpenRouter client behind an injected transport, reservation ledger, seeded draw,
  per-attempt retention, journal-validated dispatch, CLI and Make targets, offline replay (I2),
  and the no-credit backup cohort (`live/cohort.py`, `live/credit.py`).
- Spend: none. Every test uses fake transports and a socket guard; no real key was read.
- Credit: `GET /api/v1/key` and a 402 on dispatch are the two signals. Exhausted credit raises
  `CreditExhausted`; no model or cohort is substituted.
- Proxy cohort: `proxy:<agent>` attempts pass the same journal validators, cost the cap nothing,
  and are never pooled or counted as qualification of Luna, GLM 5.3 Flash or DeepSeek.
- `live_model_runner_implemented = true` was set after every live test passed offline. It
  asserts the code and tests exist; it does not assert that the key is funded or that OpenRouter
  accepts the strict schemas (unknown until the probe).
- Credential file with several keys: first in file order is used (user ruling 21 Oct 2026,
  relayed from the desktop app); count recorded, never the value. (default; superseded by
  `credential_token_index`, see probe-2)
- Probe-1 (21 Oct 2026): with the first token, `GET /api/v1/key` answered 200 but all nine
  `POST /chat/completions` attempts returned HTTP 401 "User not found." before inference (US$0);
  the second token is untried. The token is now chosen by `[model_tests].credential_token_index`
  (default 1) and recorded as `key_token_used`; a 401 never falls back to another token.
- Ledger line format unchanged. A proxy line is a zero reservation settled with
  `actual_usd: null` and reason `proxy`; its cohort rides in the attempt id.
- Task 2.7a (after probe-2, `live-probe-2.md`): strict-mode `response_format` schema with nulls
  for omitted defaults resolved before the journal; errors inside a 200 body classified by code
  with the generation id kept; ledger `adjust` and `deploy-vii live reconcile` against the
  generation endpoint, with `reservation held` in report USD cells; real-pack replay
  (`skipped-pack-absent` where the pack is absent) and three GLM entries seeded; one short issue
  per shape error; `credential_token_index = 2`. Gates on 5559f6b (offline only, no model
  call): `make product-check` exit 0 (1335 passed, 6 skipped, coverage 97 %), `make replay`
  44 passed, 6 skipped (the three real entries skip without the pack; all three replay `ok`
  against the main checkout's pack), `make check` and `make secrets` passed (gitleaks: no
  leaks). Confidence review: no confirmed defect; ledger replay tournament: incumbent holds.
  Review fix round 1: reconcile read a `cost` field the generation endpoint does not have (the
  provider-docs input was wrong). It now reads `data.total_cost` (or a top-level record) as
  documented in the OpenRouter API reference, requires the record `id` to be the requested
  generation ("generation id mismatch" otherwise), refuses when `usage` differs from
  `total_cost`, and has no `cost` fallback; a fixture holds the documented example verbatim.
  On the real probe-2, the coordinator's reconcile run got HTTP 404 for all three DeepSeek
  generation ids, so nothing was reconciled and the US$0.838404 hold stands.
- Task 2.7b (decision 0008, offline only, no model call): `source_readiness` returns a
  `ReadinessSubmission` and Python composes the stored `ReadinessReview` (hash bindings,
  attachment sets, not-assessed placeholders); a non-citable CONTEXT block with extraction
  coverage and the consumer list; `locator=page:N` span rendering; an absence-claim validator
  rule; repair prompts scoped to the failing step; the prompt bound at 3.0 bytes per token;
  the printed schema equal to `response_format`; account usage recorded before and after each
  batch, with a generation 404 adjusted to 0 only when the usage delta matches; the 2.7a loader
  minors. The probe-2 GLM entries replay as `schema: pre-0008 submission shape`
  (`superseded_by: "0008"`). Gates on 2d694c1: `make product-check` exit 0 (1414 passed,
  6 skipped, coverage 97.56 %), `make replay` 47 passed, 6 skipped (all nine entries replay
  `ok` against the main checkout's pack), `make check` and `make secrets` passed. Confidence
  review: one confirmed defect fixed (the absence rule rejected content claims such as
  "missing from pages 40-60"); composer tournament: readability challenger applied; bound
  tournament: incumbent holds. Probe-2's holds stay unresolved until its usage files are written.
- Task 2.8 (offline only, no model call): `live --models ID[@EFFORT],...` on `probe`, `module`,
  `regression` and `canary` replaces the settings pool with the user's models (methodology change
  under decision 0005, coordinator ruling 22 October 2026). Eligibility is still checked per
  model (absent id fails closed; `max_tokens`, `reasoning`, `response_format`,
  `structured_outputs` and a context length are required, `reasoning_effort` is not). Each model
  carries its own effort through `resolve_effort`; a model with no `reasoning_effort` in its entry
  gets `reasoning: {"enabled": true}` and no effort value. A bound-plus-`max_tokens` that exceeds
  the model's context (or `max_tokens` its completion limit) seals an `ineligible` attempt before
  any reservation or request. The report header and every manifest carry the pool label; the Pool
  table shows requested and sent effort and the reservation.
- Task 2.9 (offline only, no model call; decision 0008 amendment): one quote matcher for every
  citation check (layout whitespace, curly quotes, dashes and soft hyphens normalised on both
  sides; still one contiguous substring of the cited span) with issue text naming the locator and
  the quote prefix; negated or restated coverage is no absence claim; `source_context` states the
  readiness source, citation and coverage rules and its validator applies the absence rule to
  every free-text value. Unsent (`ineligible`, `refused`) seals record `reserved_usd: null` with a
  reason. Revalidated on the Caesars pack: Luna f136b227 and GLM 76fc5c95 now have no issue,
  Luna 8634aa17 keeps two wrong-page quotes, GLM f0391c45 keeps one and gains three absence
  issues; corpus entries added for GLM dccfe8f5 and Luna 8634aa17. Gates on fd8b707 with the
  pack present: `make product-check` exit 0 (1511 passed, coverage 97.61 %), `make replay` 57
  passed. Quote-matcher tournament: readability challenger applied; absence-rule tournament:
  incumbent holds. Review fix round 1: `live corpus --revalidate --outcome-changed-by
  <task-or-decision>` records a validator-driven outcome change (`outcome_changed_by`), used to
  seed Luna f136b227 and GLM 76fc5c95 (now accepted); cross-page and reordered-quote pinning
  tests. Gates on 61279b5: `make product-check` exit 0 (1519 passed, coverage 97.61 %, pack
  present), `make replay` 63 passed with the pack, 49 passed and 14 skipped without it.
- Task 2.10 (offline only, no model call; decision 0008 amendment, probe-4): a CP-0 that does not
  authorize a consumer raises the typed `execution.NotAuthorized` and the batch records a
  `not-authorized` step (attempt `none`, USD 0) with a write-once record the reconciled report
  reads, then moves to the next cell instead of aborting; a provider error inside `choices[0]` is
  `http_error`, settled on `usage.cost` (probe-4: 0) or held; `timeout_s` bounds the whole call by
  the wall clock (`budgets.deadline_s`); `--max-tokens N` through the context fit; rule h and
  `minItems: 1` for a non-empty `analysis`; `hyphen-wrap` on the span side of the quote matcher
  (Sol 9594d016 p135 passes, p13 and the p104 column stitch still fail; column interleave is a
  known layout limit); each CP-0 consumer carries its registry title and purpose (methodology row
  "Consumer purpose"). No replay entry changed (13 of 13 `ok` against the main checkout's pack).
  Records added: probe-3 and probe-4 reports, reconciles and analyses; the current probe-2
  reconcile. Gates on a052163: `make product-check` exit 0 (1539 passed, 14 skipped, coverage
  97.62 %), `make replay` 49 passed, 14 skipped (pack absent), `make check` and `make secrets`
  passed. Confidence review: one defect fixed (a non-object `choices[0].error` was read as
  absent); tournaments on the cell loop and the deadline read: incumbent holds. Task review:
  spec and quality pass with one required fix. Review fix round 1: a CLI test where
  `Execution.begin` raises a plain `ValueError` now pins the narrow catch (it fails with `except
  ValueError`); the record names the cell's CP-0 attempt (`cp0_attempt_id`); a corrupt record is
  a usage error naming its path; live-runner.md states that a deadline-expiry hold (no generation
  id) cannot be adjusted by the current ledger, so it stands; the probe-3 reconcile and the two
  analyses copied, the probe-4 analysis linked from decision 0008. Round-1 gates are in the task
  report.
- Task 2.11 (offline only, no model call; decision 0008 amendment, probe-5): OpenAI's HTTP 400 on
  the `source_context` schema (Sol 5ae16ef9, pre-existing since the stored contract) is met by
  relaxing the sent copy only (`schema.relax`: nullable enums without a null member,
  `const` as a one-value `enum`, no `minLength`/`maxLength`; manifest `schema_relaxations`,
  `schema_sha256` of the sent schema; Pydantic validation unchanged). `deploy-vii live
  schema-check --models ... [--steps ...]` sends one 16-token strict call per (model, step) with no
  reasoning parameter, reserved and settled under a US$0.05 default cap, evidence under
  `<root>/<batch>/schema-check/`, nothing submitted; a recorded HTTP 400 for the exact (model,
  step, sent schema hash) makes that step `ineligible: schema rejected by provider (<batch>)` in
  later batches before any reservation. An HTTP error's detail now carries the upstream
  provider's own message (`metadata.raw`). The seven real-pack replay entries were re-keyed to
  the `run/2` pack 77395ae0… (`artifacts/public-case/czr-fy2025-v2`; outcomes and issues
  unchanged). Records: probe-5 and probe-5b reports, reconciles and analysis. Gates on cae6bd1
  with the main checkout's packs visible: `make product-check` exit 0 (1916 passed, 0 skipped,
  coverage 98 %), `make replay` 63 passed, 0 skipped; `make check` and `make secrets` passed.
  Confidence review: one defect fixed (the schema-check key was read after the reservation, so a
  refused credential left it open). Tournaments (inline): the relaxation pass, the rejection
  lookup, and `execution.current_inputs`/`NotAuthorized` and `runner.journal_outcome` as
  adapted to `execution/5`: incumbent holds in each. Fix round 1 (after the coordinator's first
  live schema-check, `live-schema-2026-10-22.md`): only a schema-shaped 400 blocks later runs
  (provider code `invalid_json_schema`, or a detail naming the schema or `response_format`;
  manifest `schema_rejection` and `provider_error_code`; older records do not block), so
  Google's "Request contains an invalid argument" is reported and never blocks;
  `schema-check --bisect` sends one-class variants of a 400'd cell's schema until one is accepted,
  as report-only evidence under `schema-bisect/` that no real run reads or sends; the plain
  report gains Keywords and Blocks columns; provider detail is capped at 500 characters.
  Confidence review: one stale docstring fixed; tournaments (inline) on `_bisect` and
  `schema_shaped`: incumbent holds. Round-1 gates are in the task report. Fix round 2 (after
  the first live bisect, `live-schema-2026-10-22-bisect.md`: OpenAI `narrative` accepted after
  `one-of-to-any-of`, Google `source_context`/`narrative` after `drop-items-bounds`, nothing
  accepted for OpenAI `source_context`/`financials`/`readiness` or Google `financials`) adds
  five bisect variants before `all`: `nullable-array-to-anyof`, `nullable-array-required` (with
  a Touches column), `anyof-enum-null-to-type-union`, `strip-titles` and `inline-refs` (a cyclic
  `$ref` makes it `not sendable`). It also adds the resolved depth and property count to the
  Keywords cell, and folds in the round-1 re-review lows (bisect records never block; a 402
  mid-bisect; variant manifests label their relaxations' base) and the `invalid schema`
  hardening. Then, by user decision (22 Oct 2026, decision 0005 amendment), the catalog-rule
  pool is GPT-6.1 Sol alone at high, and a one-model pool's draw is recorded as trivial.
  Round-2 gates are in the task report.

Not verified: account entitlement and funded credit; live acceptance of `xhigh` or of the
strict JSON schemas; whether a native Luna agent is entitled when `codex` is on PATH.
