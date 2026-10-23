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
