# Context management for code development

Decision, 20 October 2026: keep native compaction and the existing development ICM
index, strengthen source-linked task state, and consider fresh context selectively
at safe coding-task boundaries. **No automatic reset is enabled.** The suggested
60% occupancy point is an experimental assessment checkpoint. Neither this
document nor `settings/project.toml` implements a lifecycle controller.

Scope is coding sessions and development workflow only. This does not change
analytical Modules, product storage, the product model-test pool or runtime
orchestration. Preserve the selected coordinator and explicit worker routes.

## Evidence and limits

The supplied research was independently checked against primary sources. These
findings justify evaluation, not a universal threshold or a measured benefit here.

| Source | Relevant result and limit |
| --- | --- |
| [Chroma Context Rot](https://www.trychroma.com/research/context-rot), July 2025 | Controlled tasks across 18 models show nonuniform degradation and sensitivity to input structure/distractors. Does not identify a 60% optimum for today's coding hosts. |
| [Lost in the Middle](https://arxiv.org/abs/2307.03172) | Evidence position changes performance; trimming only by size may remove useful evidence. |
| [Context Length Alone Hurts](https://aclanthology.org/2025.findings-emnlp.1264/) | Five-model experiments find effects beyond retrieval failure; model/task-specific evidence rather than a universal percentage. |
| [LLMs Get Lost in Multi-Turn Conversation](https://arxiv.org/abs/2505.06120) | Early assumptions can anchor later answers. A handoff can preserve the same mistaken diagnosis. Conversational requirements study, not a cutoff experiment. |
| [The Complexity Trap, v3](https://arxiv.org/html/2508.21433v3) | Observation masking competes with summarization in SWE-agent experiments; cost/solve-rate trade-offs differ across configurations. Retain original tool artifacts; do not generalize to arbitrary history deletion. |
| [Anthropic context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents) | Compaction, structured notes and targeted retrieval are useful patterns; compression can lose critical details. Engineering guidance, not Deploy VII acceptance. |
| [Anthropic long-running harnesses](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) | Durable progress/Git evidence and startup verification support continuity. A case study with open generalization questions. |
| [Anthropic March 2026 harness](https://www.anthropic.com/research/harness-design-long-running-apps) | Resets helped Sonnet 4.5, but were removed for Opus 4.5 in favor of continuous sessions with compaction. Direct counterevidence to universal reset policy. |
| [ReCAP preprint](https://arxiv.org/abs/2609.40118), September 2026 | Persistent attention-derived context graphs are exploratory and require additional infrastructure. Defer here. |

Our inference: authoritative goal/constraints, current evidence and correction
history should survive any compaction or handoff; redundant observations need
not all be replayed. Keep original artifacts available for selective retrieval.
Do not let an outgoing agent's preferred diagnosis become the only evidence.

## Current configuration audit

Baseline inspected: `c7c0ad05cb2b71f290442ead61a5e184527a4595` in the uppercase
workspace. The [evaluation result](tasks/context-policy/result.md) separates
confirmed gaps, proposed safeguards and remaining unknowns.

- ICM already serves development. The owner label lacked a stable session ID;
  the index/brief now identifies it. The [handoff template](handoff-template.md)
  adds continuity fields without a new context directory hierarchy.
- Codex 0.163.0-alpha.10.2 advertises token-usage notifications, manual compaction,
  resume and fork in its generated protocol. Token usage includes cumulative and
  last usage plus an optional model window. These fields do not by themselves
  establish current occupancy, reliable event delivery or safe reset control.
- Read-only native CLI config inspection returns null for the context window and
  auto-compaction limit/scope. No explicit override was found in the inspected
  user config. Null does not mean compaction is disabled; model/native defaults
  and this desktop session's live occupancy were not established.
- Claude 2.1.296's inspected user settings have no explicit auto-compaction
  percentage override. Headroom/claude-mem are enabled and hooks exist for tool
  and session events. Runtime transformations, inherited policies and latency
  remain unmeasured; project files do not disable them.
- Codex Make flags remain the worker route. No `.codex/config.toml`, global
  profile, hook, restart automation or coordinator-model change is introduced.
- CI remains deterministic with no model calls. Development-context comparisons
  hold model/provider/effort fixed; random product-test routing is a separate task.

## Small development procedure

At a natural task boundary, keep the brief/result current. If a handoff is needed,
use the template in that same task folder. Capture task/goal, concrete owner,
tree state, original constraints, corrections, facts versus hypotheses, failed
attempts, limits, pending operations and outstanding review obligations.

Before a successor writes, reconcile/stop the old execution and verify one owner.
Preserve goal identity, pauses, approvals and total consumed budgets. Inspect
unknown external outcomes before retrying them. A file is not a process lock;
host control must establish these facts. Resume/fork may replay history and is
not automatically the fresh-context arm of an experiment.

For low-overhead observations, record one sanitized row at task boundaries only
when useful: task/tree/model IDs, known compaction events, constraint/correction
incidents, repeated failed approaches, rereads/rework, elapsed time and reported
usage/cost. Unknown metrics are null with a reason. Keep raw logs in ignored
`artifacts/context-policy/`, with original evidence hashes. This is manual
recordkeeping, not a new monitor, token hook or automatic telemetry collector.

## Bounded evaluation plan

1. **Offline first:** replay the supplied synthetic handoff cases and real Git
   state probes. They test preservation/checklist completeness only. They do not
   show model quality, context-rot reduction, speed or savings.
2. **Qualify observability before a live experiment:** establish the actual
   host's current-context numerator/denominator, timestamp/turn semantics,
   compaction events, input reconstruction and stop/resume controls. Cumulative
   token usage is not occupancy. Never double-count cached/reasoning subtotals.
   Without reliable occupancy, leave the percentage arm unavailable.
3. **Matched pilot when live coding trials are authorized:** freeze three small
   development tasks (bounded bug repair with a corrected requirement, parser
   boundary repair with noisy logs, and integration recovery from stale state),
   their base trees, tests, tool permissions, host build and model/provider/effort.
   Run three repetitions of each of four arms in randomized order: current native
   compaction; a fresh context after the 60% checkpoint at the next safe boundary;
   task-boundary resets; and native compaction plus source-linked handoffs with
   selective resets. Record the delayed boundary and actual sent input; the 60%
   arm must not interrupt in-flight writes or replay the full old transcript.
   Record trials that never reach a checkpoint as no-treatment cases; do not
   attribute their results to a reset. Use tasks with explicit subtask boundaries.
4. **Equal total goal budgets:** allocate the same explicit token/cost/time caps
   to each trial, counting every continuation, handoff, review and retry. A reset
   never replenishes limits. Use identical acceptance and required review rules.
5. **Judge outcomes:** correctness/regressions, constraint violations, stale-tree
   errors, repeated failures, omissions, human corrections, rereads/rework, total
   cost, wall time and interruption overhead. Report raw failures and paired
   variation; preserve timeouts/budget exhaustion as outcomes rather than dropping
   them. Keep acceptance checks fixed and conceal the policy label from an evaluator
   where feasible. Observational development rows are a separate dataset; they cannot
   establish causation or substitute for matched trials.

The 36-trial pilot is a proposal, not a launched sweep or spending authorization.
Start smaller only to verify mechanics, and label those runs as pilot checks.
Adopt a reset policy only after repeatable benefit with preserved correctness,
constraints and total-budget accounting; otherwise keep the simpler native baseline.
