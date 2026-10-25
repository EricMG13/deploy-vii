# Model testing, retained outputs and comparison

User requirement recorded 20 October 2026. Applies to model-assisted testing
during development, including live analytical Module tests. Deterministic unit,
calculation and browser checks still run directly. This document records future
test behavior; no model call or Deploy VII test runner has been executed.
[Project settings](../settings/project.toml) now encode this contract. Implement
and verify the runner before claiming that selection or retention is operational.

## Selection and reasoning

Amendment, 22 Oct 2026 (user decision,
[decision 0005](decisions/0005-methodology-changes-and-regular-testing.md)): the pool is the
user-named set, currently GPT-6.1 Sol (`openai/gpt-6.1-sol`) alone, at **medium** for every
step, including cases predefined as difficult, since the 24 Oct 2026 amendment to decision 0005
(the user's decision; at high before). The random draw below applies only to a pool of more
than one model. With one model, the draw is recorded as trivial, and the pool, exclusions and
seed are still recorded. The Luna / GLM 5.3 Flash / DeepSeek table and the xhigh rule below
describe the superseded pool. They are kept for the stored outputs and for a future pool of more
than one model.

Choose randomly, with equal probability, from the eligible members of this pool
for each new logical test case. Record the ordered pool, exclusions, RNG algorithm,
seed and draw before dispatch. Keep the selected model for that case's retries;
a change of model is a separately identified comparison, not a concealed repair.

| User choice | OpenRouter candidate | Resolution |
| --- | --- | --- |
| Luna | `openai/gpt-6-luna` | Interpret Luna as GPT-6 Luna. Keep the returned model and version metadata. |
| GLM 5.3 Flash | `z-ai/glm-5.3-flash` | Preserve the explicitly requested version. |
| DeepSeek latest | Resolve the newest suitable DeepSeek reasoning model at test time | The current candidate is `deepseek/deepseek-v4.1-flash-1017`. This is a dated observation, not a permanent definition of latest. |

The public catalog and model pages were checked on the review date:
[Luna](https://openrouter.ai/openai/gpt-6-luna),
[GLM](https://openrouter.ai/z-ai/glm-5.3-flash), and
[DeepSeek 1017](https://openrouter.ai/deepseek/deepseek-v4.1-flash-1017).
The [DeepSeek Flash latest alias](https://openrouter.ai/~deepseek/deepseek-flash-latest)
currently points to that release; the `~` is part of that alias's ID. Pin the
resolved version within a comparison batch and record the lookup time. Recheck
DeepSeek's catalog across families for a new batch, rather than assuming Flash
will always be the newest suitable model. Retain the [metadata snapshot](review-evidence/2026-10-20-sources.json).

Use **high** for bounded extraction, ordinary Module cases and routine test
analysis. Use **xhigh** for a case defined in advance as requiring difficult
cross-source reconciliation, ambiguous methodology, multi-step legal interpretation
or a difficult failure diagnosis. Record the reason before seeing the answer.
Reasoning effort does not move arithmetic from Python to the model.

Check the actual provider/endpoint's effort and tool support. Request xhigh only
where supported; otherwise use supported high and record the mapping. Catalog
`reasoning` support alone does not prove an accepted effort value or effective
compute. Record requested effort, request parameters, documented mapping and any
provider-reported effective effort separately; use null/unknown when not exposed.
[OpenRouter reasoning controls](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
can translate effort values. Equal labels are not equal compute.

[OpenAI's endpoint guidance](https://developers.openai.com/api/docs/guides/deployment-checklist)
documents a relevant Luna constraint: reasoning with tool calling requires the
appropriate Responses path; Chat Completions function calling is limited to
`none` for Luna. Verify the chosen OpenRouter adapter's handling of this boundary
before admitting a tool-using Luna test. Do not silently disable reasoning/tools.

If a route lacks the required tools, context, effort or account access, record
ineligibility and draw from the remaining requested candidates. If none qualify,
the model test remains blocked. A dispatched failure stays a failure in the
record. Provider fallbacks must be observable and separately classified; no
substitution outside the user's pool. This pool does not change implementation
worker assignments in the [development matrix](model-matrix.md).

## Evidence saved for every attempt

Use the configured local development evidence root,
`artifacts/model-tests/<experiment>/<case>/<model>/<attempt>/`. It is separate from
product runtime storage and ICM task briefs. Keep raw private evidence out of Git
when Git is introduced; publish only intentionally selected, redacted summaries.

| Artifact | Contents |
| --- | --- |
| `manifest.json` | Experiment/case/attempt IDs; UTC timestamps; code/tree or file hashes; method, prompt, schema, renderer and input hashes; upstream artifact identities; model draw; endpoint, provider, versions, tool permissions and budgets. |
| `request.json` | Exact submitted messages and non-secret parameters, including output/reasoning limits. Exclude authentication headers and credentials. |
| `response.json` and `output.md` | Raw returned response, extracted output, tool calls, finish/refusal status and provider-exposed metadata. Preserve unsuccessful and truncated responses too. |
| `events.jsonl` | Ordered attempt/span IDs, elapsed timestamps, tool start/end and results, retries, backoff, timeouts, provider request IDs and errors. Preserve actual tool results locally or reference hashed artifacts. |
| `metrics.json` | Usage, measured latency/cost, validation and rubric results, repair count and measurement availability. |
| `checks/` | Exact commands/exits, factual/source checks, expected-value comparisons, limitations and reviewer/rubric version. |
| `render/` | Candidate and accepted HTML snapshots as applicable, normalized view data, field-parity results, viewport screenshots, browser console/network logs and visual findings. |

Capture input/output/cached/reasoning tokens when exposed, reported cost and
currency, end-to-end wall time, time to first token where measured, tool time,
retry/backoff time, renderer time and peak memory where instrumented. Separate
provider values from local measurements and estimates. A missing value is null
with an availability reason, not zero. Do not double-count overlapping spans or
token categories. Store only telemetry the host actually exposes; unavailable
internal reasoning or native-host metrics remain unavailable.

**Tool loops (task 8.0d).** With `tool_loop` on in settings, the four CP-1 stages run as one
conversation each (`deploy_vii/live/loop.py`). Every call of that conversation is its own
attempt directory, named `<ticket>-<step>-<n>` (`-repair-<n>` in the step's repair). Its
evidence is the seven entries above plus `tool-calls.jsonl`, which holds each tool call with its
arguments, status and full result, each submit's verdict and any call-limit nudge. The call's
`metrics.json` adds a `tool_loop` block:

- for the call: its tool calls by name, the effort level and the effort sent, whether the effort
  was escalated and why, the cost basis, the tool time, whether a nudge followed, and the call it
  retries;
- for the step so far: calls, tool calls by name, pages read, searches run, every submit (outcome,
  issues by class, evidence counts and a completeness-floor flag), the shrink-to-pass flag, the
  `financials` completeness and completeness-drop flag, the final payload's cited-but-unread
  locators, the verdict, the settled and held USD, the evidence rules and the limits.

Task 8.9 (user decision, 24 Oct 2026) runs every live step of every module this way. The step
block's `tool_set` is the step's registry tool set: `pack` (`search_pack`, `read_pages` and the
submit) or `submit-only` (the submit alone). Its `rules` record adds `applied`, the evidence
rules that step checks. Its `limits` hold the step's own: 30 calls on a `pack` step and 6 on a
`submit-only` step. A `submit-only` step reads nothing, so its reading fields (`pages_read`,
`located_pages`, `searches_run`, `spans_surfaced_by_search`, `final_payload_cited_not_read`) are
null, not zero. Task 8.10b: `pages_read` counts full `read_pages` reads only, as 8.0d defined it;
`pages_extracted` counts the pages `extract_statements` returned (`financials`; null on a
`submit-only` step), and `final_payload_cited_not_read` treats an extracted page as read, as the
cited-page rule does. The CP-1 `quality` loop's `manifest.json` `hashes` add `quality_inputs_sha256`,
the hash of the QA inputs its prompt was built from.

**Extracted coverage (task 8.12, user decision "C", 24 Oct 2026).** Every `financials` submit's
record holds `extracted_coverage` next to `completeness` (`live.tools.extracted_coverage`), or
null with `extracted_coverage_reason` when the retained payload does not parse (the stage
validator rejects it). Python computes it; the model-facing prompt and schema are unchanged.

- **Pages.** Per submit, the loop extracts the `page:N` spans of the `source_context` review's
  financial sources that the model had been shown by then, through `read_pages` or
  `extract_statements` (`tools.seen_tables`). It never extracts a page the model was not
  shown, never the whole filing.
- **Cells.** The cells are the line-count floor's (`expected_cells`): IS and CFS per fiscal-year
  scope, BS per period-end scope. Each is keyed `<statement> <source> scope <id> (<dates>)`.
- **A cell's extracted lines.** Every line of the extracted pages of the cell's source that the
  payload's lines of the cell's statement cite (in books bound to the scope's entity, any
  period). "Cite" here and below means the line's `value.citations`; `sign_citations` do not
  count. The extractor tags no statement, and header years proved unreliable (CZR's
  statement headers print `December 31,` with the years on another line, while a note table
  prints both years). So the pages are the cited ones alone. A comparative year therefore
  counts its statement's page even when the payload holds none of its lines.
  The denominator is the cited pages only, which has two effects (fix round 1, review F1):
  - A statement page the payload never cites drops out of the measure, and no rule catches
    it. If no CFS line cited page:61, its 7 supplemental lines would simply not count.
  - A line citing another statement's page pulls that whole page into its own statement's
    cell and lowers the ratio (a CFS line citing the IS page adds the IS page's lines to the
    CFS cell).

  The measure, and the floor on it, is coverage of the cited pages, not of the statement.
- **Covered.** An extracted line is covered when a payload line of the same statement, in a
  period the cell's scope matches (`scope_matches_period`; for BS, the scope's end date), cites
  the line's page with either:
  - a quote holding one of the line's printed non-nil values verbatim as a whole number (`40`
    is not in `140`, `4,000`, `40.5` or `(40)`), or
  - a label equal to the extracted label after whitespace normalisation.

  Flagged lines count. A nil dash is never quote-matched, so a line holding only nil dashes
  is covered by its label alone. Known limitation (review F3): a whole-number match can still
  hit a small number by accident (a printed `1` matches `Note 1` in a quote).
- **Coverage.** Covered / extracted as a Decimal string rounded down to four places. It is null
  when nothing is extracted, with the reason: no line of the statement cites a page of the
  source; no cited page was read or extracted; or the cited pages hold no extracted line.
  `overall` sums the cells (a line counts once per cell) and gives the reason when nothing is
  extracted.
- **Agreement (telemetry only).** Each payload statement line with an amount, on the extracted
  pages it cites, is compared with the extracted lines of its label there (whitespace
  normalised):
  - `agreed`: its amount is one of their `values`; a payload 0 agrees with a printed nil dash;
  - `sign_differs`: only its negation is;
  - `disagreed`: neither is (a retyped `-100` for the printed `(10)`);
  - `unmatched`: no line there has its label.

  The comparison is against any column of the line, not the period's column. It checks the
  printed sign (parentheses), not the economic sign (review F2). So a FY2025 line carrying the
  FY2024 value agrees, and so does a `signed` expense written positive, which is a sign error
  under the contract. Conversely, `sign_differs` is mostly the contract's own `signed`
  normalisation of a printed magnitude (an expense written negative, as the contract asks;
  `development/statements.md`), not an error. Follow-up, not in this task: split `sign_differs` into
  "printed magnitude, payload negative under `signed`" (expected) and "printed
  parenthesised, payload positive" (a likely flip). Python can compute both.

  `not_on_an_extracted_page` and `without_amount` count the rest.
- **Fields.** Each cell holds `extracted`, `covered`, `coverage`, `reason` and `pages` (the
  cited pages counted, in page order). `overall` holds `extracted`, `covered`, `coverage` and
  `reason`. `agreement` holds the six counts plus `disagreements` and `sign_differences`. Each
  is a list of at most five entries, in payload order. An entry has `pages` (`[source_id,
  locator]` pairs), `line_id`, `period_id`, `label`, `payload_value` (a Decimal string),
  `sign_convention` and `extracted_values` (per matched extracted line, its values as Decimal
  strings, null for a nil dash).

Measured on the recorded `financials` payloads (25 Oct 2026):

- hybrid-cp1-6 Sol medium (19 pages read): IS FY2025 17 of 29 lines (0.5862), CFS FY2025 40 of 48
  (0.8333), BS 2025-12-31 31 of 33 (0.9393), and 0 for each of the five comparative cells.
  Overall 88 of 297 (0.2962). Agreement: 79 agreed, 9 sign differences (expenses and cash
  paid printed as magnitudes, written negative under `signed`: the contract's normalisation,
  not errors), 0 disagreed, 11 unmatched (8
  renamed IS lines such as `Casino revenue` for the printed `Casino`, `Other investing cash
  flow`, `Preferred stock`, `Common stock`). The 22 uncovered current-year lines are those 11
  renamed lines, 4 per-share and share-count lines and 7 supplemental cash-flow lines on
  page:61.
- synthetic-search-accept: no page read, so every cell is null with its reason.

The last call's block is the step's. `manifest.json` records the tools offered, `tool_choice`,
the previous call and the retried call, and its `hashes` include `tool-calls.jsonl`
(`tool_transcript_sha256`). In the batch report a tool-loop step's USD cell is the step's total
over its calls, with any held part named: `<total> (reservation held <held>)`.

Each attempt is immutable after completion. Repairs create a new attempt linked
to its predecessor. Store hashes and publish the completed manifest after its
artifacts are written. An interrupted attempt retains its partial evidence and
an interrupted status; it must never become a successful result by omission.

## Comparison and acceptance

Random sampling gives varied development coverage. It does not establish a
model ranking when different models receive different cases. For a deliberate
comparison, run the same frozen case across all eligible candidates in randomized
order, with the same upstream artifacts, tools, rubric and declared budgets.
Repeat where useful; report sample sizes, failures and uncertainty. A changed
DeepSeek version, effort, prompt or upstream output defines another cohort.

Track schema success, citation validity, expected-value parity, unsupported claims,
coverage of required questions, faithful gaps/refusals, first-pass acceptance,
repairs, rendering parity, latency and cost per accepted result including failed
attempts. Keep deterministic results separate from judgment scores. No arbitrary
weighted leaderboard or success-only average.

A completed Module test immediately feeds the [Direction C rendering checks](frontend-direction-c.md).
Preserve a labelled candidate preview when inspectable; promote only validated
artifacts to the accepted report. Other modules remain visibly not run, blocked,
stale or outside scope. A rendering pass does not qualify analytical correctness.

## Regular cadence

[Decision 0005](decisions/0005-methodology-changes-and-regular-testing.md), adopted
21 October 2026, makes this testing regular:

- **Internal tiers.** I1 runs on every change. I2 is the offline replay of recorded
  responses, run on every change to a model-facing contract, validator or prompt. I3
  runs at each milestone.
- **External tiers (this pool, via OpenRouter).** E1 is a module qualification case.
  E2 is the milestone regression on GPT-6.1 Sol alone. The matched comparison is dormant
  until the user adds models. E3 is one Sol draw per week against the last E2, still a
  provider and model drift canary (decision 0005 amendment, 22 Oct 2026).

Each batch writes a summary without raw data, and its validated responses join the
replay corpus. Beyond the first US$50 batch, the recurring caps and the US$200
cumulative ceiling of [decision 0006](decisions/0006-delegated-choices-and-orchestration.md) DC-6 apply. The key is read
from the DC-7 credential file at dispatch time and never recorded. Without credit, the
DC-8 proxy cohort applies and is never pooled with pool results.
One-shot steps are sent no tools. Since task 8.0d the CP-1 stages can run as tool loops: the
read-only pack tools and the step's own submit tool, with `tool_choice: required` (user decision,
24 Oct 2026; decision 0005 row 8.0d). Luna's Chat Completions tool-calling limit above therefore
applies before any Luna tool-loop test is admitted. The pool is currently Sol alone.

25 Oct 2026: skill rehearsals (task LP-1, [rehearsals](development/rehearsals.md)) form the
labelled `proxy-claude` cohort of DC-8. A stand-in agent follows the packaged skill through the
real CLI while `devtools/skill_rehearsal.py` records commands, issues, the report and an
estimated cost (US$12 cap per rehearsal, inside the US$200 ceiling). The cohort is never pooled
with the Sol pool and its results are never model-quality evidence.

Not verified: account entitlement, per-provider effort mapping, adapter/tool
behavior, live quality, cost or performance. These require working tests and inputs.
