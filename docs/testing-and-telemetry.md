# Model testing, retained outputs and comparison

User requirement recorded 20 October 2026. Applies to model-assisted testing
during development, including live analytical Module tests. Deterministic unit,
calculation and browser checks still run directly. This document records future
test behavior; no model call or Deploy VII test runner has been executed.
[Project settings](../settings/project.toml) now encode this contract. Implement
and verify the runner before claiming that selection or retention is operational.

## Selection and reasoning

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
  E2 is the milestone regression with a matched three-model comparison. E3 is a weekly
  drift canary.

Each batch writes a summary without raw data, and its validated responses join the
replay corpus. Beyond the first US$50 batch, the recurring caps and the US$200
cumulative ceiling of [decision 0006](decisions/0006-delegated-choices-and-orchestration.md) DC-6 apply. The key is read
from the DC-7 credential file at dispatch time and never recorded. Without credit, the
DC-8 proxy cohort applies and is never pooled with pool results.
The runner disables tools: Luna's Chat Completions tool-calling limit above does not
apply until a tool-using module is admitted.

Not verified: account entitlement, per-provider effort mapping, adapter/tool
behavior, live quality, cost or performance. These require working tests and inputs.
