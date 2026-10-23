# Hybrid CP-0 probe: read-only pack tools vs the one-shot baseline (23 October 2026)

Experiment, not an adoption: the runner still offers no tools. Harness `devtools/hybrid_cp0.py`
(commits f8e42b7, 2a1d732 on base 2e5a050). Batch `hybrid-cp0-1`: GPT-6.1 Sol (`openai/gpt-6.1-sol`)
at effort high, `max_tokens` 32000 per call, provider block `allow_fallbacks: false,
require_parameters: true`, `tool_choice: "required"`, 3 draws run in order, cap US$5. Pack
`czr-fy2025-v2` (Caesars FY2025 10-K, one source `czr-2025-10k`, 195 located pages, pack sha256
`77395ae0…af3c`). The baseline is the one-shot probe-5 Sol attempt cf6bf65b, not re-run here
(coordinator scope change).

Design in one paragraph: the model gets the runner's own system prompt and CONTEXT block
(`prompts.build`) with the SOURCE blocks removed and only rule 5 ("You have no tools.") replaced
by the tool instruction. It reads the pack through `search_pack` (ranked spans, ±300-character
snippets) and `read_pages` (at most 5 pages per call, each page as the same `<<<SOURCE …>>>` block
and `locator=page:N | …` line the one-shot prompt uses), and submits through `submit_readiness`.
Each submit is judged on the runner's trusted path (a fresh execution journal, `begin CP-0`,
`submit_model_payload`, `journal_outcome`), the same verdict probe-5 recorded. At most 3 submits,
25 calls and 900 s per draw.

Roots. ART = `/Users/ericguei/Documents/DEPLOY VII/artifacts/model-tests/hybrid-cp0-1/`
(`plan.json`, `batch-summary.json`, and per draw `call-NN-request.json`,
`call-NN-response.json`, `tool-calls.jsonl`, `metrics.json`, `journal-submit-N/`). Ledger
`/Users/ericguei/Documents/DEPLOY VII/artifacts/model-tests/.ledgers/hybrid-cp0-1.jsonl`. Figures
below are copied from `metrics.json`; medians and changes were computed in Python (Decimal).

## 1. Draws

| Draw | Verdict | Wall s | Calls | Prompt / completion / reasoning (cached) | USD | Submits | Issue classes (rejected submits) | Pages read | Shrink flag |
|---|---|---|---|---|---|---|---|---|---|
| hybrid-1 | **accepted** | 230.6 | 8 | 276,983 / 13,585 / 2,708 (cached 212,341) | 0.3181851 | 2: rejected, accepted | Quote/locator mismatch ×1 | 47 of 195 (24.1%) | no |
| hybrid-2 | **accepted** | 160.3 | 7 | 240,543 / 8,122 / 1,147 (cached 174,724) | 0.2627989 | 1: accepted | none | 61 of 195 (31.3%) | no (one submit) |
| hybrid-3 | **accepted** | 207.8 | 6 | 172,928 / 12,582 / 1,225 (cached 123,615) | 0.2610860 | 2: rejected, accepted | Quote/locator mismatch ×1; Absence claim contradicts extraction coverage ×1 | 34 of 195 (17.4%) | **yes**: limitations 35 → 34 |

All 21 calls: served by `openai/gpt-6.1-sol` via OpenAI (identity verified), classification ok,
`finish_reason` `tool_calls`, `usage.cost` reported (nothing held). Tool calls per draw
(search / read / submit / refused): hybrid-1 5 / 12 / 2 / 1, hybrid-2 6 / 14 / 1 / 2,
hybrid-3 5 / 12 / 2 / 0. Every refused call asked `read_pages` for 6 pages; the model retried
within the 5-page limit on the next turn.

Rejected submits, verbatim:
- hybrid-1 submit 1: `Quote/locator mismatch: quote not found under czr-2025-10k page:95 …
  "Reconciliation of Net Income (Loss) Attributable to Caesars …"`. Submit 2 kept every count.
- hybrid-3 submit 1: `Quote/locator mismatch: quote not found under czr-2025-10k page:104 …
  "Previously filed on Form 8-K filed on November 25, 2024."` and `Absence claim contradicts
  extraction coverage: page:1 to page:195 retained in czr-2025-10k`.

## 2. Arm medians against the one-shot baseline

| | Hybrid median (n = 3) | Probe-5 Sol cf6bf65b (one-shot, n = 1) | Change |
|---|---|---|---|
| Verdict | 3 of 3 accepted | accepted | |
| Wall clock s | 207.8 (range 160.3–230.6) | 184.6 (probe-5 Sol range 185–201) | +12.6% |
| Prompt tokens | 240,543 (71.5–76.7% cached) | 153,514 (cached 0) | +56.7% |
| Completion tokens | 12,582 | 9,842 | +27.8% |
| Reasoning tokens | 1,225 | 1,990 | |
| USD | 0.2627989 | 0.4822035 | −45.5% |
| Calls | 7 | 1 | |

Hybrid sends more prompt tokens in total, because every call re-sends the conversation, but
most of them are cache reads, so the cost per accepted draw is about half the baseline's.
Wall clock is a little longer than the baseline. The tools themselves are not the cost: tool
time, including judging each submit in a fresh journal, was 0.28–0.35 s per draw. The time goes
into the calls that return a submit: 127.0 s and 66.3 s (hybrid-1), 119.7 s (hybrid-2), 106.0 s
and 71.9 s (hybrid-3). The reading turns take 2.3–18.0 s each.

## 3. Coverage and citations

- Pages read: 47, 61 and 34 of 195 (17–31%). All three draws read pages 1–4, 43–46, 54–57,
  73–77, 94–95 and 101–105 (`tool-calls.jsonl`). Search queries included "covenant(s)",
  "subsequent", dates ("February 17, 2026", "2026"), statement titles ("CONSOLIDATED BALANCE",
  "CONSOLIDATED STATEMENTS"), "Adjusted EBITDA", "restricted cash", "Exhibit 10" and, in two
  draws, a bare "[".
- Every locator the accepted payloads cite was read through `read_pages` in that conversation
  (`cited_not_read` is empty in all three; none was seen only in a search snippet). Distinct
  cited locators: 21, 27 and 24.
- The one-shot prompt puts all 195 pages in front of the model; the hybrid model read at most a
  third of them and was still accepted 3 of 3. Acceptance means the validator's rules hold; it
  is not an analytical-quality judgment, and this probe does not compare the content of the
  hybrid and one-shot judgments.

## 4. Shrink-to-pass detection

The harness records each submit's counts (source judgments, consumer judgments, gaps, claims,
citations, limitation entries) and flags a draw whose later submit drops any count against its
first.

- hybrid-1: submit 1 and 2 have identical counts (54 citations, 4 claims, 7 consumers, 3 gaps,
  34 limitations); only the failing quote changed. Not flagged.
- hybrid-3: **flagged**. Submit 2 dropped exactly one limitation entry, on the source
  judgment, the sentence the coverage validator rejected: "Coverage retains pages 1 through 195
  with no intervening missing pages; unreviewed pages are not treated as absent." The model
  deleted it rather than rephrasing it. The sentence asserts coverage, not absence, so the
  absence-claim matcher fired on a false positive (a matcher question for the product, not
  decided here); the deletion lost no evidence. It is still the shrink-to-pass pattern the flag
  exists to catch: with the validator in the loop, the model removed text that drew an issue.
  The other counts did not change (65 citations, 4 claims, 4 gaps).

## 5. Spend and ledger

- Batch spend US$0.8420700 (settled; nothing held, no overrun), 21 attempts. Per-call
  reservations ran from US$0.502140 (call 1) to US$1.009472 (a 72k-token prompt); the cap of
  US$5 was never approached.
- Cumulative-ceiling check: prior ledgers US$33.646866219830 + cap US$5 ≤ US$200. One prior line
  was counted at its pre-adjust charge (worst case, user decision 23 Oct 2026), because this
  code (2e5a050) cannot replay M7's `account-usage-delta` adjust source:
  `e1-cp1-2.jsonl` seq 8, attempt `05d99407-4351-42db-b499-38f65905b886-financials-1`, source
  `account-usage-delta`, previous_charged_usd 2.293576.

## 6. Limits

- n is small: 3 hybrid draws against one one-shot attempt (cf6bf65b; probe-5 Sol latency range
  185–201 s over its attempts). Medians of three are indicative only.
- One issuer, one source, page locators only.
- Same-day provider variance is not controlled: the baseline ran on 22 October on runner a6678e7;
  this batch ran on 23 October at base 2e5a050, whose CONTEXT and rules may differ in wording
  from a6678e7's. Prompt caching depends on the provider's cache state.
- The hybrid submit tool is not strict (`strict` not set); the one-shot arm used strict
  `response_format`. Both are judged by the same journal path.
- Cost compares settled `usage.cost`; the baseline had no cache reads, the hybrid draws had
  71.5–76.7%.

## 7. Medium effort (hybrid-cp0-2)

Evidence only, not adoption: decision 0005 (amended 22 Oct 2026) says every run uses GPT-6.1 Sol
at high. User request (23 Oct 2026): 3 more hybrid draws at medium effort, US$3 cap, same
harness. Harness commit 27fbbb6 adds `--effort {high,medium}` (default high); the effort is
pinned in the catalog selection and refused if the catalog would map it, and `medium` was sent
unmapped (catalog efforts low/medium/high/xhigh/max). Every other setting is the same as
hybrid-cp0-1: `max_tokens` 32000, 25 calls, 900 s, 3 submits, `tool_choice` "required", same pack
and prompt. Root `/Users/ericguei/Documents/DEPLOY VII/artifacts/model-tests/hybrid-cp0-2/`, ledger
`.ledgers/hybrid-cp0-2.jsonl` (cap 3). Ceiling check: prior US$34.488936219830 (now including
hybrid-cp0-1) + cap US$3 ≤ US$200, with the same worst-case line (`e1-cp1-2.jsonl` seq 8).

| Draw | Verdict | Wall s | Calls | Prompt / completion / reasoning (cached) | USD | Submits | Issue classes (rejected submits) | Pages read | Shrink flag |
|---|---|---|---|---|---|---|---|---|---|
| hybrid-1 | **accepted** | 73.3 | 4 | 56,050 / 3,945 / 91 (cached 24,191) | 0.1212646 | 1: accepted | none | 24 of 195 (12.3%) | no (one submit) |
| hybrid-2 | **accepted** | 101.6 | 6 | 109,539 / 6,137 / 100 (cached 77,789) | 0.1481459 | 2: rejected, accepted | Quote/locator mismatch ×1 | 25 of 195 (12.8%) | no |
| hybrid-3 | **accepted** | 66.6 | 5 | 71,925 / 3,556 / 98 (cached 49,684) | 0.0958159 | 1: accepted | none | 21 of 195 (10.8%) | no (one submit) |

All 15 calls were served by `openai/gpt-6.1-sol` via OpenAI (identity verified), classified ok,
`finish_reason` `tool_calls`, with `usage.cost` reported (nothing held); no tool call was refused.
The one rejected submit (hybrid-2 submit 1) was `Quote/locator mismatch: quote not found under
czr-2025-10k page:95 … "Reconciliation of"`, the same page as hybrid-cp0-1's hybrid-1. Every
cited locator was read through `read_pages` (`cited_not_read` empty in all three). Batch spend
US$0.3652264 (15 attempts, nothing held, no overrun); both batches together US$1.2072964.

### High vs medium

| | High (hybrid-cp0-1) | Medium (hybrid-cp0-2) | Change |
|---|---|---|---|
| Median wall clock s (range) | 207.8 (160.3–230.6) | 73.3 (66.6–101.6) | −64.7% |
| Median latency of a submit-producing call s (n calls) | 106.0 (5) | 53.1 (4) | −49.9% |
| Median per-draw time in submit-producing calls s | 177.8 | 63.9 | |
| Median reasoning tokens | 1,225 | 98 | −92.0% |
| Median completion tokens | 12,582 | 3,945 | −68.6% |
| Median prompt tokens | 240,543 | 71,925 | |
| Median calls | 7 | 5 | |
| Median USD (batch total) | 0.2627989 (0.8420700) | 0.1212646 (0.3652264) | −53.9% |
| First-pass acceptance | 1 of 3 | 2 of 3 | |
| Final acceptance | 3 of 3 | 3 of 3 | |
| Issue classes (rejected submits) | Quote/locator mismatch ×2, Absence claim contradicts extraction coverage ×1 | Quote/locator mismatch ×1 | |
| Pages read (median) | 47, 61, 34 (47) | 24, 25, 21 (24) | |
| Shrink flag | 1 of 3 (hybrid-3) | 0 of 3 | |

Medians and changes were computed in Python from `metrics.json` and `tool-calls.jsonl`.

What the comparison shows, and what it does not:
- Both efforts were accepted 3 of 3 on the same trusted journal path, and all six accepted
  payloads reach the same verdicts: issuer confirmed, source fidelity `degraded`, CP-1, CP-1A,
  CP-2 and CP-5 READY_WITH_LIMITATIONS, CP-3, CP-4 and CP-6 CONDITIONAL.
- Medium is faster mainly because it reads and writes less: about half the pages, and smaller
  accepted payloads. Accepted payload counts at medium: citations 43, 30, 31 (high: 54, 65,
  65); limitation entries 21, 18, 24 (high: 34, 37, 34); claims 3, 2, 3 (high: 4, 6, 4); gaps
  3, 3, 3 (high: 3, 5, 4); 7 consumer judgments and 1 source judgment in every draw. The
  validator accepts both; this probe does not judge whether the thinner evidence is enough for
  the downstream modules.
- Medium's cache share was lower in one draw (43.2% in hybrid-1; 71.0% and 69.1% in the
  others), which narrows its cost advantage relative to its token reduction.
- Same limits as section 6: n = 3 per effort, one issuer, same-day provider variance; the medium
  batch ran about 30 minutes after the high batch.
