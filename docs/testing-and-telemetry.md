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

Not verified: account entitlement, per-provider effort mapping, adapter/tool
behavior, live quality, cost or performance. These require working tests and inputs.
