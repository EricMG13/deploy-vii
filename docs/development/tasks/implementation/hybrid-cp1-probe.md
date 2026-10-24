# Hybrid CP-1 probe: pack tools across Sol, Opus and Sonnet on M7 (23–24 October 2026)

Evidence only under decision 0005: an experiment, not an adoption. The runner still offers no
tools, and nothing under `src/` changed. Harness `devtools/hybrid_cp1.py` on branch
`hybrid-cp1-m7`, cut from `claude/m7-lane` 098f05e. Commit 5533ae2 ran the first four cells;
9ab6689 added `--resume`/`--skipped-by-user` and ran sonnet-xhigh (see §4). Batch
`hybrid-cp1-1`, seed 3282685796, `--step-seconds 3600`, caps US$15 (OpenRouter) and US$25
(Anthropic). Pack `czr-fy2025-v2`: Caesars FY2025 10-K, one source `czr-2025-10k`, 195 located
pages.

Read these figures as follows:
- **One run per cell (n = 1).** Differences between cells are single observations, not
  estimates.
- **A single issuer.**
- **Claude costs are computed, not billed.** The Anthropic cells are priced from list prices
  (`computed-from-list-prices`; US$ per million tokens):

  | Model | Input | 5-min write | 1-h write | Cache read | Output |
  | --- | --- | --- | --- | --- | --- |
  | Opus | 4 | 5 | 8 | 0.20 | 20 |
  | Sonnet | 2 | 2.5 | 4 | 0.10 | 10 |

  The Sonnet cache-read price comes from Anthropic's 7 October 2026 release note. No Anthropic
  invoice was reconciled.
- **Sol costs are reported by OpenRouter** (`usage.cost`, `provider-reported`).

Design in one paragraph:
- Each cell runs `source_context` → `financials` → `narrative` → `readiness` on its own copy of
  the frozen CP-0 journal (`hybrid-cp0-1/hybrid-2/journal-submit-1`).
- Each step gets the runner's M7 prompt with its upstream projection, plus `search_pack`,
  `read_pages` and `submit_<step>`.
- Every submit is judged on the runner's trusted path (`submit_model_payload` and
  `journal_outcome`) in a fresh journal copy. Python pre-fills the hash bindings. An accepted
  copy becomes the next step's base.
- Limits per step: 3 submits, 30 calls and 3,600 s. `max_tokens` is 128,000 per call.
- Anthropic calls are streamed with adaptive thinking and `output_config.effort`. `tool_choice`
  is `any`, falling back to `auto` after the documented 400. Top-level `cache_control` is set.
- A cell stops at its first step that is not accepted.

Roots:
- ART = `/Users/ericguei/Documents/DEPLOY VII/artifacts/model-tests/hybrid-cp1-1/`
  - `plan.json`;
  - `plan-resume-sonnet-xhigh.json`;
  - `batch-summary-resume-sonnet-xhigh.json`;
  - per cell `metrics.json`;
  - per step `call-NN-request.json`, `call-NN-response.{json,sse}`, `tool-calls.jsonl` and
    `journal-submit-N/`.
- Ledgers `.ledgers/hybrid-cp1-1-openrouter.jsonl` and `.ledgers/hybrid-cp1-1-anthropic.jsonl`
  under the same artifact root.

Figures are copied from `metrics.json`. Sums and ratios were computed in Python.

## 1. Cell × step

Token columns:
- Thinking/reasoning tokens are a part of completion tokens.
- Cached tokens are a part of prompt tokens.
- For Anthropic, cached tokens are `cache_read_input_tokens`, and prompt tokens are
  `input_tokens` plus cache writes plus cache reads.

| Cell | Step | Verdict | Wall s | Calls | Prompt tok | Completion tok | Thinking/reasoning tok | Cached tok | USD settled | USD held | Basis | Submits | First submit accepted | Issue classes (rejected submits) | Pages read | Citations (final payload) | Shrink |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sonnet-max | source_context | rejected: limit | 496.3 | 30 | 3,679,315 | 69,273 | 64,620 | 3,430,167 | 1.6586 | 0 | computed-from-list-prices, known-zero | 0 | – | – | 114 | – | no |
| sol-high | source_context | accepted | 94.6 | 6 | 108,165 | 5,114 | 1,301 | 70,411 | 0.1522 | 0 | provider-reported | 1 | yes | – | 27 | 34 | no |
| sol-high | financials | accepted | 1,246.7 | 7 | 397,228 | 95,803 | 4,311 | 280,305 | 1.2779 | 0 | provider-reported | 2 | no | An observation cannot have multiple definition assessments ×1 | 27 | 381 | **yes** |
| sol-high | narrative | accepted | 182.9 | 3 | 648,953 | 12,554 | 1,656 | 428,650 | 0.7190 | 0 | provider-reported | 1 | yes | – | 5 | 163 | no |
| sol-high | readiness | accepted | 195.0 | 2 | 543,804 | 13,385 | 3,106 | 271,742 | 0.8411 | 0 | provider-reported | 1 | yes | – | 0 | 92 | no |
| sol-medium | source_context | accepted | 41.5 | 4 | 40,482 | 2,487 | 49 | 21,310 | 0.0747 | 0 | provider-reported | 1 | yes | – | 14 | 26 | no |
| sol-medium | financials | accepted | 730.6 | 6 | 205,286 | 58,661 | 1,276 | 140,136 | 0.7631 | 0 | provider-reported | 2 | no | Quote/locator mismatch ×2 | 13 | 268 | no |
| sol-medium | narrative | accepted | 110.7 | 3 | 558,131 | 6,222 | 118 | 371,540 | 0.5657 | 0 | provider-reported | 1 | yes | – | 0 | 86 | no |
| sol-medium | readiness | accepted | 87.9 | 2 | 468,067 | 5,525 | 338 | 233,874 | 0.6640 | 0 | provider-reported | 1 | yes | – | 0 | 51 | no |
| opus-medium | source_context | accepted | 35.6 | 7 | 135,441 | 3,493 | 336 | 108,066 | 0.2283 | 0 | computed-from-list-prices | 1 | yes | – | 9 | 14 | no |
| opus-medium | financials | accepted | 1,211.9 | 8 | 523,495 | 183,444 | 13,740 | 299,152 | 4.8504 | 0 | computed-from-list-prices | 2 | no | binding.financial_review_sha256 ×1, definition.financial_review_sha256 ×1, financial.books.N.periods.N ×2 | 13 | 543 | no |
| opus-medium | narrative | accepted | 288.9 | 1 | 321,976 | 25,497 | 13,991 | 0 | 2.1198 | 0 | computed-from-list-prices | 1 | yes | – | 0 | 121 | no |
| opus-medium | readiness | accepted | 171.4 | 1 | 397,894 | 13,490 | 6,021 | 0 | 2.2593 | 0 | computed-from-list-prices | 1 | yes | – | 0 | 59 | no |
| opus-high | – | skipped by user | – | 0 | – | – | – | – | 0 | 0 | – | 0 | – | – | – | – | – |
| sonnet-xhigh | source_context | accepted | 99.1 | 13 | 575,412 | 13,852 | 7,421 | 483,887 | 0.4157 | 0 | computed-from-list-prices, known-zero | 1 | yes | – | 38 | 27 | no |
| sonnet-xhigh | financials | accepted | 730.8 | 10 | 902,549 | 140,219 | 56,709 | 768,506 | 1.8141 | 0 | computed-from-list-prices | 1 | yes | – | 19 | 484 | no |
| sonnet-xhigh | narrative | accepted | 1,193.1 | 4 | 1,412,058 | 149,993 | 94,999 | 299,837 | 4.3105 | 0 | computed-from-list-prices | 3 | no | Funding assessment requires distinct located prior balance-sheet rows ×3, Unknown narrative evidence ×8 | 0 | 239 | **yes** |
| sonnet-xhigh | readiness | accepted | 498.9 | 2 | 764,663 | 49,352 | 35,781 | 371,160 | 1.5144 | 0 | computed-from-list-prices | 1 | yes | – | 0 | 81 | no |

USD figures are rounded to four places here. Exact values are in each `metrics.json`.

Notes on the table:
- **`known-zero`** marks the first Anthropic call of each process: the documented 400
  `tool_choice: type "tool" and "any" are not supported for this model.`, refused before
  inference.
  - It happened twice: sonnet-max call 1 in the first run, and sonnet-xhigh call 1 in the
    resume.
  - Every later Anthropic call used `tool_choice: auto`, opus-medium included, because the
    fallback carries over within a process.
  - The resume summary records it as `tool_choice_fallback`.
  - The other 107 calls were classified ok: 74 Anthropic and 33 OpenRouter.
- **Shrink flags.**
  - sol-high financials, second submit against the first: citations 534 → 381, objects
    1,466 → 1,016.
  - sonnet-xhigh narrative: citations 253 → 239, claims 21 → 20 → 19, objects
    325 → 310 → 309.
- **sonnet-max** spent its 30 calls on 27 `read_pages` and 16 `search_pack` tool calls
  (114 pages read). It never called `submit_source_context`. Its last call produced 42,287
  completion tokens, of which 42,183 were thinking, and ended in another tool call.
- **Cache use.** opus-medium narrative and readiness were one call each, with no cache reads
  (cached 0). They wrote 321,972 and 397,890 tokens to the five-minute cache, priced at the
  write rate (US$5 against US$4 input per million). Those writes bought no read.

Accepted payload evidence (citations / limitations / claims / objects):

| Cell | source_context | financials | narrative | readiness |
| --- | --- | --- | --- | --- |
| sol-high | 34 / 17 / 0 / 43 | 381 / 25 / 4 / 1,016 | 163 / 6 / 25 / 231 | 92 / 0 / 14 / 31 |
| sol-medium | 26 / 9 / 0 / 34 | 268 / 18 / 2 / 786 | 86 / 6 / 13 / 134 | 51 / 0 / 12 / 29 |
| opus-medium | 14 / 6 / 0 / 22 | 543 / 11 / 2 / 1,454 | 121 / 5 / 13 / 169 | 59 / 0 / 12 / 29 |
| sonnet-xhigh | 27 / 16 / 0 / 35 | 484 / 20 / 5 / 1,296 | 239 / 6 / 19 / 309 | 81 / 0 / 14 / 31 |

## 2. Per cell

| Order | Cell | Model | Effort | Module verdict | Wall s (cell) | USD settled | USD held |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | sonnet-max | claude-sonnet-5-5 | max | stopped at source_context (rejected: limit, 30 calls) | 496.4 | 1.6585867 | 0 |
| 2 | sol-high | openai/gpt-6.1-sol | high | **accepted** (4/4 steps) | 1,719.5 | 2.9901418 | 0 |
| 3 | sol-medium | openai/gpt-6.1-sol | medium | **accepted** (4/4) | 970.9 | 2.0674560 | 0 |
| 4 | opus-medium | claude-opus-5-5 | medium | **accepted** (4/4) | 1,708.1 | 9.4578216 | 0 |
| 5 | opus-high | claude-opus-5-5 | high | skipped by user | 0 | 0 | 0 |
| 6 | sonnet-xhigh | claude-sonnet-5-5 | xhigh | **accepted** (4/4) | 2,522.2 | 8.0546970 | 0 |

## 3. Comparison across cells

| Cell | Wall s | USD | Steps accepted on first submit | Final acceptance | Citations, four accepted payloads | Citations per USD |
| --- | --- | --- | --- | --- | --- | --- |
| sol-medium | 970.9 | 2.0675 | 3 of 4 (financials on submit 2) | 4/4 | 431 | 208.5 |
| sol-high | 1,719.5 | 2.9901 | 3 of 4 (financials on submit 2) | 4/4 | 670 | 224.1 |
| opus-medium | 1,708.1 | 9.4578 | 3 of 4 (financials on submit 2) | 4/4 | 737 | 77.9 |
| sonnet-xhigh | 2,522.2 | 8.0547 | 3 of 4 (narrative on submit 3) | 4/4 | 831 | 103.2 |
| sonnet-max | 496.4 | 1.6586 | 0 of 1 (no submit) | stopped at step 1 | – | – |

- **Speed.**
  - sol-medium was fastest end to end.
  - sol-high and opus-medium took about the same time, with financials about 1,200 s in each.
  - sonnet-xhigh was slowest. Its narrative step alone took 1,193 s over three submits.
  - Financials is the long step in every cell except sonnet-xhigh.
- **Cost.**
  - The Sol cells cost US$2.07–2.99.
  - The Claude cells cost US$8.05–9.46 (computed).
  - opus-medium's financials step alone (US$4.85) cost more than either whole Sol cell.
- **Acceptance.**
  - Every cell that submitted reached a module-level accept with no step failing outright.
  - Each such cell needed one repair, at financials (sol-high, sol-medium, opus-medium) or at
    narrative (sonnet-xhigh, two repairs).
  - sonnet-max never submitted.
- **Evidence density.**
  - sonnet-xhigh and opus-medium carried the most citations, both in total and in financials
    (484 and 543).
  - sol-high carried the most citations per dollar.
  - sol-high's accepted financials payload is the shrunken second submit (381 citations, down
    from 534). Its count understates what the model first found.

## 4. Opus-high: skipped by user

The user decision "skip opus high" arrived while opus-medium was running. The running process
could not read a stop file (its code was already loaded), so the batch was stopped from outside:
- A watcher polled every millisecond for the creation of `ART/opus-high/`.
  - `run_cell` makes that directory only after `run_batch` has written opus-medium's
    `metrics.json`.
  - The new cell then copies the frozen journal and begins CP-1 before its first reservation.
- The watcher sent SIGKILL when the directory appeared; the process exited 137.
  - The kill landed during the journal copy. `ART/opus-high/journal-start/` holds a partial copy
    (two snapshot files) and is kept as found.
- Ledger check after the stop:
  - neither ledger has any `opus-high` attempt;
  - open reservations: 0 on both ledgers.
  - **Opus-high spent US$0 and holds US$0.**
- sonnet-xhigh then ran alone with
  `--resume --cells sonnet-xhigh --skipped-by-user opus-high`, using the same batch id, seed,
  ledgers (each opened with its own cap) and step limit.
  - It wrote `plan-resume-sonnet-xhigh.json` and `batch-summary-resume-sonnet-xhigh.json` beside
    the untouched `plan.json`. That summary lists opus-high as `skipped by user` at order 5.
  - The killed run wrote no `batch-summary.json`. Every finished cell's `metrics.json` is
    complete.

## 5. Against the e1-cp1 one-shot Sol runs on M7 (e1-cp1-10 to 14)

Source: `ART/../e1-cp1-1{0..4}/cp-1/openai__gpt-6.1-sol/*/` (`manifest.json`, `metrics.json`,
`request.json`). Settings:
- `max_tokens` 128,000 and a 3,600 s timeout;
- the whole pack in the prompt, with no tools;
- one call per attempt, plus a separate `financials-repair` attempt;
- effort high, except e1-cp1-12 (medium).

Records:
- **e1-cp1-13 and e1-cp1-14:** two source_context → financials → financials-repair chains each,
  four chains in all, at high.
  - source_context was accepted every time (92.0–125.5 s, prompt 154,170 tokens).
  - financials was rejected 4 of 4 times (631.0–736.2 s; 45,941–51,954 completion tokens;
    US$0.88–0.97).
  - The repair was rejected 4 of 4 times (617.8–866.0 s; 43,938–65,347 completion tokens;
    US$0.88–1.07).
  - No chain reached narrative.
- **e1-cp1-12 (medium):** source_context was accepted (45.3 s, US$0.4159). Its financials attempt
  kept only `request.json`, with no manifest and no outcome.
- **e1-cp1-10 and -11:** `source_readiness` returned no response (0.3–0.4 s).

Comparison where the records allow it:
- **Financials acceptance.** One-shot Sol at high: 0 of 8 attempts (4 attempts and 4 repairs).
  Hybrid Sol at high and at medium: accepted on the second submit inside one step.
- **Financials time.** The hybrid financials step (sol-high 1,246.7 s; sol-medium 730.6 s) is
  about the length of one one-shot financials attempt plus its repair (1,299.8–1,497.0 s).
- **Financials cost.** The hybrid step cost US$1.28 (high) and US$0.76 (medium). A one-shot
  attempt plus repair cost US$1.84–1.95 (corrected from US$1.75–1.95 after review).
- **Source_context.** Hybrid source_context used fewer prompt tokens: 108,165 over 6 calls
  (sol-high) and 40,482 over 4 (sol-medium), against 154,170 in one one-shot call. The one-shot
  runs at high cost US$0.07–0.46. The lower figures appear to reflect provider caching; this was
  not verified.
- **Caveat.** The configurations differ: tools against a full-pack prompt, and different repair
  shape. These are paired single observations, not a controlled comparison.

## 6. Spend

| Ledger | Cap | Spent | Open | Overrun | Attempts | Remaining |
| --- | --- | --- | --- | --- | --- | --- |
| `hybrid-cp1-1-openrouter.jsonl` | 15 | 5.0575978 | 0 | 0 | 33 | 9.9424022 |
| `hybrid-cp1-1-anthropic.jsonl` | 25 | 19.1711053 (computed) | 0 | 0 | 76 | 5.8288947 |

- Batch total: US$24.2287031.
- Prior committed before the batch: US$32.560586619830. After the batch it is
  US$56.789289719830, against the cumulative ceiling of US$200.
- `account-usage-delta` lines are replayed natively; there were no worst-case adjustments.

## 7. Harness observations

- **Streaming worked.** Real Anthropic SSE frames carried padded whitespace and extra null
  fields, and `message_delta` repeated the input usage fields. The parser handled all of these.
  Every streamed call was classified ok, so no stream was incomplete, no idle timeout fired and
  no `error` event arrived.
- **No cell hit a provider stop** (cap, credit, 401/403) and no provider schema error occurred.
- **Single-call steps** (opus-medium narrative and readiness) paid cache writes with no reads.
- **Call budget.** A cell that never submits uses the whole call budget: sonnet-max used 30 calls
  and US$1.66 at source_context.

## 8. Luna at xhigh (batch hybrid-cp1-2)

Evidence only. Decision 0005's amendment superseded Luna as a model-test pool member, so this
cell informs nothing about adoption. It was run at the user's request after hybrid-cp1-1.

Setup:
- **Model.** Cell `luna-xhigh`, model `openai/gpt-6-luna`, served as
  `openai/gpt-6-luna-20260922` (canonical slug).
- **Effort.** The live catalog (sha256 `3df8a74a…9d`) lists low, medium, high, xhigh and max.
  xhigh was sent unmapped (`mapped: false`).
- **Prices.** US$0.20 input and US$0.75 output per million tokens.
- **Run shape.** The hybrid CP-1 shape and frozen CP-0 journal are the same as above.
  `max_tokens` 128,000; 3,600 s per step; seed 3282685796; harness commit 9ab6689.
- **Ledger.** The cell spent against hybrid-cp1-1's OpenRouter ledger
  (`--openrouter-ledger`, cap US$15, headroom US$9.9424022 at the start).
- **Artifacts.** `/Users/ericguei/Documents/DEPLOY VII/artifacts/model-tests/hybrid-cp1-2/`
  (`plan.json`, `batch-summary.json`, `luna-xhigh/…`).

| Step | Verdict | Wall s | Calls | Prompt tok | Completion tok | Reasoning tok | Cached tok | USD settled | Submits | First submit accepted | Issue classes (rejected submits) | Pages read | Citations | Shrink |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| source_context | accepted | 150.9 | 10 | 402,750 | 14,799 | 8,865 | 323,356 | 0.0205 | 2 | no | Quote/locator mismatch ×8 | 26 | 38 | no |
| financials | accepted | 245.7 | 6 | 265,852 | 35,007 | 9,835 | 192,918 | 0.0285 | 2 | no | binding.financial_review_sha256 ×1, definition.financial_review_sha256 ×1, financial.books.N.periods.N ×2 | 18 | 90 | **yes** |
| narrative | accepted | 77.9 | 2 | 154,350 | 7,411 | 5,171 | 76,746 | 0.0142 | 1 | yes | – | 0 | 22 | no |
| readiness | accepted | 160.6 | 3 | 294,595 | 19,252 | 11,897 | 188,173 | 0.0248 | 2 | no | Invalid gap-scope evidence ×1 | 0 | 34 | **yes** |

Cell outcome:
- **Verdict:** accepted (4/4 steps).
- **Wall clock:** 635.2 s.
- **Cost:** US$0.088024530, provider-reported, with nothing held.
- **Calls:** 21, all classified ok and all served by `openai/gpt-6-luna`.
- **Shrink flags:**
  - financials: citations 168 → 90, objects 450 → 242;
  - readiness: citations 36 → 34.
- **Invalid tool calls:** four in readiness.
- **Accepted payload evidence** (citations / limitations / claims / objects):
  - source_context 38 / 3 / 0 / 46;
  - financials 90 / 12 / 2 / 242;
  - narrative 22 / 4 / 3 / 54;
  - readiness 34 / 0 / 6 / 23.

Against the six hybrid-cp1-1 cells:

| Cell | Wall s | USD | Steps accepted on first submit | Final | Citations, four accepted payloads | Financials citations |
| --- | --- | --- | --- | --- | --- | --- |
| luna-xhigh | **635.2** | **0.0880** | 1 of 4 | 4/4 | 184 | 90 |
| sol-medium | 970.9 | 2.0675 | 3 of 4 | 4/4 | 431 | 268 |
| sol-high | 1,719.5 | 2.9901 | 3 of 4 | 4/4 | 670 | 381 |
| opus-medium | 1,708.1 | 9.4578 (computed) | 3 of 4 | 4/4 | 737 | 543 |
| sonnet-xhigh | 2,522.2 | 8.0547 (computed) | 3 of 4 | 4/4 | 831 | 484 |
| sonnet-max | 496.4 | 1.6586 (computed) | 0 of 1 | stopped at step 1 | – | – |
| opus-high | – | 0 | – | skipped by user | – | – |

- **Speed and cost.** Luna was the fastest cell to a module accept and about 23 times cheaper
  than sol-medium.
- **First-pass acceptance.** It had the lowest: three of four steps needed a second submit.
- **Evidence.** Its accepted payloads carry the fewest citations: 184 against 431–831, and in
  financials 90 against 268–543.
- **Completeness concern.** Its financials payload is the second submit, which shrank by about
  half from the first (168 → 90 citations). An accept here says the payload passed the runner's
  checks, not that it is as complete as the other cells'.
- **Caveat.** n = 1 and a single issuer, as above.

Spend for this batch: US$0.088024530 against hybrid-cp1-1's OpenRouter ledger. That ledger now
shows spent US$5.145622330 over 54 attempts, nothing open, no overrun, and remaining
US$9.854377670 of its US$15 cap. Prior committed across all ledgers after both batches is
US$56.877314249830.

## 9. Financials completeness (back-filled)

Both batches ran before submits recorded completeness, so this section is back-filled.
- **Source.** Each judged `submit_financials` in the cells' retained
  `financials/tool-calls.jsonl`, read only, with nothing re-run.
- **Computation.** `devtools.hybrid_cp1.completeness_from_log` and `completeness_drop`
  (commit 1d8c2d7, revised in 5f29460). The figures below are the same under either commit.
  No payload recorded an unreadable id.
- **Fields.** Counts are summed over the payload's books:
  - statement lines, split by `statement` and by the fiscal year of their period;
  - accounts;
  - balance movements and balance-movement bridges;
  - statement identities;
  - definition assessments and the distinct observation ids they name.
- **`completeness_drop`.** Set when a later submit has fewer statement lines or balance
  movements than the most any earlier submit held, so 5 → 200 → 50 is a drop. It sits beside
  the shrink flag, which counts citations, limitations, claims and objects.

| Batch | Cell | Submit | Call | Outcome | Lines | By statement | By fiscal year | Accounts | Bal. movements | Bridges | Identities | Def. assessments | Obs. ids |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid-cp1-1 | sol-high | 1 | 6 | rejected | 284 | BS 74, CFS 126, IS 84 | 2023 72, 2024 104, 2025 108 | 60 | 5 | 1 | 8 | 5 | 26 |
| hybrid-cp1-1 | sol-high | 2 | 7 | **accepted** | 143 | BS 51, CFS 59, IS 33 | 2023 11, 2024 26, 2025 106 | 60 | 0 | 0 | 7 | 5 | 23 |
| hybrid-cp1-1 | sol-medium | 1 | 5 | rejected | 102 | BS 35, CFS 41, IS 26 | 2025 102 | 47 | 0 | 0 | 19 | 3 | 10 |
| hybrid-cp1-1 | sol-medium | 2 | 6 | **accepted** | 102 | BS 35, CFS 41, IS 26 | 2025 102 | 47 | 0 | 0 | 19 | 3 | 10 |
| hybrid-cp1-1 | opus-medium | 1 | 7 | rejected | 256 | BS 58, CFS 123, IS 75 | 2023 66, 2024 95, 2025 95 | 51 | 5 | 1 | 16 | 3 | 7 |
| hybrid-cp1-1 | opus-medium | 2 | 8 | **accepted** | 256 | BS 58, CFS 123, IS 75 | 2023 66, 2024 95, 2025 95 | 51 | 5 | 1 | 16 | 3 | 7 |
| hybrid-cp1-1 | sonnet-xhigh | 1 | 10 | **accepted** | 223 | BS 60, CFS 94, IS 69 | 2023 39, 2024 92, 2025 92 | 59 | 0 | 0 | 0 | 4 | 11 |
| hybrid-cp1-2 | luna-xhigh | 1 | 5 | rejected | 96 | BS 36, CFS 33, IS 27 | 2023 20, 2024 38, 2025 38 | 37 | 0 | 0 | 0 | 1 | 3 |
| hybrid-cp1-2 | luna-xhigh | 2 | 6 | **accepted** | 34 | BS 10, CFS 6, IS 18 | 2023 8, 2024 13, 2025 13 | 34 | 0 | 0 | 0 | 1 | 3 |

| Cell | completeness_drop | Shrink flag (evidence counts) |
| --- | --- | --- |
| sol-high | **yes**: statement lines 284 → 143, balance movements 5 → 0 | yes |
| sol-medium | no (both submits identical in these counts) | no |
| opus-medium | no (both submits identical in these counts) | no |
| sonnet-xhigh | no (one submit) | no |
| luna-xhigh | **yes**: statement lines 96 → 34 (CFS 33 → 6) | yes |

Reading:
- **What the runner accepted.** It accepted payloads that cover very different amounts of
  the statements:
  - 223–256 lines over three fiscal years (opus-medium, sonnet-xhigh);
  - 143 lines weighted to FY2025 (sol-high after its drop);
  - 102 lines for FY2025 only (sol-medium);
  - 34 lines (luna-xhigh).
- **Shrinking after rejection.** sol-high and luna-xhigh answered their rejection by removing
  content: sol-high dropped all balance movements and most FY2023–2024 lines, and luna-xhigh
  dropped most CFS lines. The second submit then passed.
- **Repair without loss.** opus-medium and sol-medium repaired without losing any counted
  item.
- **Comparing cells.** Section 3's acceptance and evidence figures should be read with this
  table. An accepted financials step is not evidence of comparable coverage.

## 10. Harness rules added after these batches (commits 1d8c2d7 and 5f29460)

These rules were not in effect for hybrid-cp1-1 or hybrid-cp1-2. They are recorded in
`plan.json` for later batches.

- **Anthropic caching (unchanged from these batches).** Top-level
  `cache_control: {"type": "ephemeral"}` is sent on every step, with the default 5-minute TTL
  (`anthropic.cache_control`).
  - 1d8c2d7 dropped caching for narrative and readiness. 5f29460 reverted that, because those
    steps were multi-call in most cells:
    - sonnet-xhigh 4 and 2 calls;
    - sol-high and sol-medium 3 and 2;
    - luna-xhigh 2 and 3.
    Without the cache, sonnet-xhigh readiness would have cost US$2.022846 instead of
    US$1.5143905 (+33.6%), every cached token priced as input at list prices.
  - **Observed.** Every within-step cache miss in hybrid-cp1-1 followed a call longer than
    300 s, the TTL: opus-medium financials call 8 (after 633.4 s), sonnet-xhigh narrative calls 3
    and 4 (after 557.3 s and 329.0 s). No cache read followed such a call.
  - **Unmeasured option.** A top-level `ttl` of "1h" is documented (values "5m" and "1h") and
    left unchanged.
- **Call-limit nudge.** Once a step has 3 calls left, each turn's last tool result ends with one
  line: "Harness: N of 30 calls remain in this step; the step must end with submit_<step>."
  - It is first sent with the step's third-last call (`harness_rules.call_limit_nudge`).
  - Since 5f29460, `tool-calls.jsonl` records it as an entry with `nudge` and `appended_to` on
    the turn that carried it.
  - **Port note (review C6).** The nudge shares a string with untrusted pack text, which could
    spoof a "Harness:" line. A product port must put harness notes in a separate content block.
- **Completeness recording.** Financials submits and the accepted payload record completeness,
  and step metrics carry `completeness_drop` beside `submit_shrinkage`. Ids that are neither a
  string nor an integer count as unknown, with the reason recorded; they never raise.
- **Ledger safety.**
  - Attempt ids are `<batch>:<cell>-<step>-call-NN`. The earlier unprefixed ids of these two
    batches still read.
  - A run refuses at preflight when its ledger already holds attempts for the same batch and
    cell, and any ledger error while sending stops that provider.
  - `--skipped-by-user` refuses a cell that left step calls or ledger attempts.
  - A `--cap-*` given for an existing ledger must equal that ledger's opening cap.
