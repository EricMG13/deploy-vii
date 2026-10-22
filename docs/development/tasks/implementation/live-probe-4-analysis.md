# Probe-4 analysis (M2, dv-research, read-only, 22 October 2026)

Roots. ART = `/Users/ericguei/Documents/DEPLOY VII/artifacts/model-tests/probe-4/probe/<model>/<attempt>/` (attempts by 8-char prefix). SRC = `src/deploy_vii/` at `claude/m2-lane` 87ba556 (read in the `m2-lane-run` worktree at 389a037, which carries the same runner code). Batch report: `live-probe-4.md`; reconciled: `live-probe-4-reconciled.md` (both in this folder; reconcile found no holds). No key-prefixed string was read or quoted. Page checks were grep reads of each `request.json`. Nothing was executed.

Pool: user-selected (coordinator ruling 22 Oct 2026, relayed user instruction): DeepSeek V4.1 Flash 1017 @max, Grok 4.7 @xhigh, MiMo-V2.6-Pro (reasoning enabled, no effort parameter in the catalog), GPT-6.1 Sol @high; 2 draws each; cap US$10.

## 1. Attempts

All have `max_tokens` 16000 and `timeout_s` 600 (manifest.json). Completion tokens include reasoning. USD is `metrics.json` `ledger.charged_usd`.

| Attempt | Model, effort sent | Status / class | Issues | USD | Prompt / completion / reasoning | Latency s | finish_reason |
|---|---|---|---|---|---|---|---|
| c1540d12 | DeepSeek, max | no-response / http_error | 0 | 0 | none (no usage object) | 2.05 | null (HTTP 429) |
| 9d68b734 | DeepSeek, max | rejected / ok | 1 | 0 | 214,966 / 16,000 / 35,064 | 1029.3 | error |
| 7812cd5f | Grok 4.7, xhigh | rejected / ok | 4 | 0.432076 | 154,352 / 20,850 / 17,159 | 220.1 | stop |
| 17a71fce | Grok 4.7, xhigh | rejected / ok | 2 | 0.27259 | 154,352 / 32,541 / 28,061 | 340.8 | stop |
| f33915f2 | MiMo, `reasoning.enabled`, no effort | rejected / truncated | 1 | 0.07520652 | 161,960 / 16,000 / 11,904 | 420.9 | length |
| 13d5a6bb | MiMo, same | rejected / truncated | 1 | 0.01306196064 | 161,960 / 16,000 / 11,470 | 326.9 | length |
| 9594d016 | Sol, high | rejected / ok | 3 | 0.478201 | 153,209 / 9,518 / 3,624 | 201.3 | stop |
| 944e569a | Sol, high | **accepted** / ok | 0 | 0.1068066 | 153,209 / 9,148 / 3,106 | 188.6 | stop |

- The USD column sums to US$1.37794208064, the batch report's "spent"; reconcile confirmed no holds.
- Two usage anomalies. Grok completion tokens (20,850 and 32,541) exceed `max_tokens` 16000 with `finish_reason` stop (xAI appears to apply the budget to visible tokens only). DeepSeek 9d68b734 reports reasoning 35,064, more than its completion 16,000.
- Routing (`response.json` provider fields): MiMo → DeepInfra; Sol → OpenAI; Grok → xAI; both DeepSeek attempts → OpenInference.

## 2. Rejected attempts by root cause

**DeepSeek c1540d12 (provider).** HTTP 429. Body `error.message` "Provider returned error", `error.code` 429; `metadata.raw` says the model "is temporarily rate-limited upstream", `provider_name` OpenInference, `limit_source` "upstream_provider_shared_pool". Ledger settled known-zero ("HTTP 429 refused before inference"). No retry (`retries_on_this_ticket_step` false).

**DeepSeek 9d68b734 (provider, plus a runner classification gap).** HTTP 200; `choices[0]` holds `finish_reason` "error" and `error.code` 502, "Upstream error from OpenInference: Internal server error", `error_type` "provider_unavailable"; `content` null; the body is mostly reasoning text. The validator issue "Invalid JSON: EOF" is a symptom. Runner gap: `SRC/live/client.py:322-334` checks only a top-level `error`; `_answer` (`client.py:363-366`) maps only `length` to a non-ok class, so a provider 502 was recorded as class `ok` (`checks/classification.json`: ok, finish_reason error, `error_detail` null) instead of a provider-error class. It ran 1,029 s against `timeout_s` 600: `client.py:420` passes the timeout to `urlopen`, a per-socket-operation timeout; OpenRouter's whitespace keep-alive (probe-3 analysis §5) would explain the overrun (not verified).

**Grok 7812cd5f (4 issues).** (1) Empty `analysis`: the validator (`SRC/readiness.py:300-301`) requires it non-empty; the schema sent has `analysis` required with no `minItems`; rules a–g (`SRC/live/prompts.py:57-78`) do not mention it; the request does not carry the cp0.md "analytical read-through" text → runner/contract, an unstated rule. (2) p37 "Consolidated net revenues increased…" sits within 3,000 chars of the `page:38` marker, not within 3,500 of `page:37` → model, wrong page. (3) p47 "we were in compliance with all of the applicable financial covenants": Grok's second draw cites p46 and passes → model, wrong page. (4) p72 "On September 14, 2023, we announced that an unauthorized actor…": the double-spaced occurrence is within 4,500 chars of `page:73` → model, wrong page (strong inference; page boundaries not read exactly).

**Grok 17a71fce (2 issues).** (1) p72 "It is not possible at this time to estimate the amount of loss or range of loss" is on p73 (where Sol and MiMo cite it) → model, wrong page, off by one again. (2) p102 "Previously filed on Form 8-K filed on September 27, 2021." is a two-column exhibit table: the text reads "Previously filed on Form 8-K filed\n<other column>  on September 27, 2021"; the model stitched across columns → layout, runner/contract. Sol's p104 failure is the same pattern.

**MiMo f33915f2 and 13d5a6bb (provider cut-off, shaped by our budget).** `finish_reason` and `native_finish_reason` both `length`; completion 16,000 = `max_tokens`. Reasoning used 11,904 and 11,470 (74%/72%), leaving ≈4,096/4,530 visible tokens. JSON cut mid-string at validator col 15,885 / 17,768 inside `gaps`; in alphabetical key order `sources` had not been written. Six spot-checked quotes from the partial outputs were found in the pack (p45 debt service, p51 impairment, p37 key metrics, p16, p90, p38); the p73 loss quote matches Sol's. Quote quality looked clean; nothing else validated. Class: provider truncation; the catalog lists no `reasoning_effort` for MiMo so reasoning could not be lowered; runner/budget cause (`SRC/live/runner.py:57`, `max_tokens: int = 16000`) plus model verbosity.

**Sol 9594d016 (3 issues, model-side copying; two layout-aggravated).** p13 "Forward-looking statements are only predictions…" — source "Such forward-looking statements…": case change (the normaliser does not touch case) → model misquote. p135 "…PUT-CALL RIGHT AGREEMENT" — source "PUT-\nCALL  RIGHT": the model rejoined a hyphenated line wrap → model, layout-invited; tolerating line-wrap hyphens is a validator design question. p104 "Credit Agreement…, as collateral agent." — the source interleaves a second column ("from time    Previously filed on Form 8-K filed\n to time, JPMorgan…"); Grok's and MiMo's shorter p104 quote ends at "from time" and passes → model stitching across a layout artefact.

## 3. DeepSeek 9d68b734 and the US$0

`metrics.json` `ledger`: `cost_basis` "provider-reported", `cost_reason` "usage.cost", `charged_usd` "0"; provider `usage.cost` is 0. `response.json` `usage.cost_details.upstream_inference_cost` is 0.02304762 (prompt 0.01504762, completions 0.008): OpenRouter billed nothing for the errored generation while the upstream cost was non-zero. The ledger records what OpenRouter charged. Reserve US$0.1061607 released to 0.

## 4. Sol accepted output (944e569a): spot checks

1. SR-HISTORICAL cites p97 "our report dated February 17, 2026, expressed an unqualified opinion on those financial statements." — in the ICFR auditor report, alongside the p54 audit opening. Sound. The claim's "segment disclosures, debt and lease information" is not supported by its citations (unsupported extension).
2. SR-FIDELITY says the map on p35 is not in the text: the quote is followed by a long run of blank lines and unrelated text. Supported. The p99 quote "available for futureremaining" is a real merged-heading artifact. Sound.
3. SR-LEGAL says CEI obligations are distinct from the Caesars Virginia facilities; p77 "…secured by substantially all material assets of Caesars Virginia, LLC… CEI does not provide a guarantee of these facilities." Sound.

Weak points: SR-FORWARD's citation "The following table summarizes our estimates for 2026 capital expenditures." is a table lead-in, not evidence of the figures. All seven consumers are CONDITIONAL: the CONTEXT block lists consumers by id only (`request.json` line 11) and each `missing_source` is the module brief — a defensible reading of the prompt that gives no actionable readiness (Sol's first draw is all-CONDITIONAL too). Acceptance means structure and quotes pass the validator, not that readiness is grounded (as in probe-3 §3).

## 5. The abort

- Probe cells run `PROBE_STEPS = ("source_readiness", "source_context", "financials")` (`SRC/live/cli.py:57`); loop `_run_cell` `cli.py:327-362`. After Sol's accepted step the row is appended (`:345-360`) and, status accepted, the loop continues (`:361-362`).
- Next step `source_context` is module CP-1 (`SRC/live/submission.py:133`); `cli.py:329-330` calls `store.begin("CP-1")` → `current_inputs` (`SRC/execution.py:289-295`) → `execution.py:96-110` requires the CP-0 head's T8 `exact_command` for CP-1 to be "Run CP-1", else `ValueError("CP-0 has not authorized this consumer's source readiness")`.
- `SRC/readiness.py:439-445` writes "Run <id>" only for READY / READY_WITH_LIMITATIONS, "DO NOT RUN" otherwise. Sol's CP-1 is CONDITIONAL (`missing_source` "Authoritative deploy-v-r14 CP-1 module brief and evidence-acceptance checklist"; rationale: "reflects unresolved scope, not absence of the financial statements").
- Uncaught in `_run_cell`; in `run_live` `except CapExceeded` (`cli.py:645`) does not match; `except BaseException` (`:647-649`) sets `batch.stopped = "aborted: ValueError"` and re-raises; `finally` (`:650-658`) writes the report; `execute` returns EXIT_FAILED (`:857-871`).
- Impact: probe-07 was the last cell, so no draw was lost. An earlier CONDITIONAL-CP-1 cell would have skipped every later cell.
- Verdict: runner defect. The gate (`execution.py:96-110`) is a methodology guard and stays; a CP-0 that returns CONDITIONAL for CP-1 is a valid accepted outcome, not an error. Fix: typed subclass raised at `execution.py:110`, caught in `_run_cell` around `store.begin` (`cli.py:330`); append a Row with status `not-authorized`, zero USD; end the cell; continue. Do not catch bare ValueError (`execution.py:88`, `:95` raise others). No test pins this behaviour.
- Contract question: the CP-0 prompt lists consumers by id only; careful models answer CONDITIONAL for every id-only consumer, so chained probes keep hitting this gate.

## 6. Ranking (user's rule: accepted results and failure classes, not reasoning-token counts)

1. **GPT-6.1 Sol @high** — the only accepted result (944e569a, 0 issues); fastest (188.6–201.3 s); both draws complete JSON, `stop`. Rejected draw: 3 copying issues (2 layout-aggravated, 1 case change). Cost US$0.585 for the pair; the accepted draw cost US$0.1068 because the prompt was cached (153,206 of 153,209 tokens). Caveat: all consumers CONDITIONAL; stitched/overreaching claims above.
2. **Grok 4.7 @xhigh** (second, low confidence) — zero accepted; both draws complete, valid structure, `stop`; issues 4 → 2 across draws; of 6 issues, 4 model wrong-page (same p72/p73 off-by-one twice), 1 layout stitch, 1 the unstated empty-`analysis` rule. Cost US$0.7047 total (0.27259 for the near-miss). Slowest completer (220–341 s).
3. **MiMo-V2.6-Pro** — zero validated; both `length` truncations (provider, budget-shaped); spot-checked quotes clean; cheapest (US$0.0883 total). No evidence on model quality either way: output never reached the validator.
4. **DeepSeek V4.1 Flash @max** — no usable output; 429 (2.05 s) and 502 after 1,029 s, the latter mis-recorded `ok`; charged US$0. With probe-2/3: 6 of 6 DeepSeek attempts across probes 2–4 produced no content.

**Best two: GPT-6.1 Sol and Grok 4.7.** Sol leads on the accepted result; Grok is the only other model with complete, validatable outputs and a visible improvement between draws.

What would change the ranking: MiMo could overtake Grok if a larger completion budget lets it complete (72–74% of 16,000 consumed by reasoning; US$0.013–0.075 per attempt vs Grok's 0.27–0.43). DeepSeek needs a run without the 429/502 before it can be placed. Fixing the empty-`analysis` rule and the column-interleave/hyphen-wrap validator pitfalls would remove 2 of Grok's 6 issues; wrong-page errors remain. Two draws per model is a small sample.

Not verified: bytes per page span (p72/p73, p37/p38 assignments rest on windowed regex matches); the cause of DeepSeek's 1,029 s run against the 600 s timeout; whether MiMo content beyond the six quotes would pass; whether a test pins the ValueError abort; whether Sol's all-CONDITIONAL result is wrong or the right answer to an id-only prompt; the p135 page assignment; runtime behaviour inferred from source and artifacts, nothing executed.
