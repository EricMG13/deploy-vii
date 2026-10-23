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
  about the length of one one-shot financials attempt plus its repair (about 1,250–1,500 s).
- **Financials cost.** The hybrid step cost US$1.28 (high) and US$0.76 (medium). A one-shot
  attempt plus repair cost US$1.75–1.95.
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
