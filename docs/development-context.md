# ICM for development context

Assessment: 20 October 2026, incorporating the user's clarification that ICM is
for development work. Recommendation: use a small ICM-inspired documentation
layer for task context and handoffs. It does not determine product folders,
runtime orchestration or how analytical Modules store their outputs.

[ICM's primary description](https://github.com/SorretAI/ICM) uses a routing entry
point, scoped stage contracts, references and artifacts. Its useful development
principle here is making each task's required context and outputs explicit. The
layout and trade-offs below are a Deploy VII recommendation, not an imported ICM
policy or a measured productivity result.

## Where it helps

| Development need | Useful convention | Limit |
| --- | --- | --- |
| Resume a task without rereading the entire history | Short context index linking current decisions and active work | Keep it current; do not duplicate every research document. |
| Give a worker enough context | One brief listing exact source versions, required reads, scope and expected behavior | A read list guides attention; it is not a filesystem sandbox. |
| Keep writes and dependencies clear | One owner, editable paths, tested predecessor, dependencies and worktree | Folder separation alone does not isolate Git refs or credentials. |
| Compare model and rendering evidence | Link task/case IDs to immutable attempts and outputs | Do not paste raw telemetry or full model outputs into every brief. |
| Hand work back for integration | One result with commits, checks, gaps and next action | Coordinator still validates the combined candidate. |

Deploy VI already had an Inputs/Process/Outputs development brief. Preserve that
useful shape, but not its historical role restrictions, budgets or retired-review
instructions. The main opportunity is fewer duplicated plans and clearer evidence
links, not a new framework.

## Adopted development layout

The environment setup installs the index and first task brief/result below.
Create additional task folders only when needed:

```text
AGENTS.md                            project instructions and current scope
docs/development/CONTEXT.md           short development index and current state
docs/development/tasks/<task-id>/
  brief.md                           inputs, work, acceptance and ownership
  result.md                          implementation result and evidence links
docs/decisions/                      shared decisions linked by briefs
artifacts/model-tests/               local test evidence, outside brief context
```

The context index links current architecture, method, model, rendering and
publication documents. It names active task owners and dependencies. Keep only
one authoritative location for each decision. Ordinary product source/tests stay
in the source layout chosen for the product; do not move them into task folders.

Each brief contains:

- **Inputs:** task goal, exact predecessor/tree, required files/sections and why,
  relevant interfaces, fixture identities, and protected inputs.
- **Work:** expected behavior, one owner, permitted writes, dependency constraints,
  unresolved questions and the assigned host/model/effort when applicable.
- **Outputs and checks:** code/tests/docs, required Module-to-HTML fields, factual
  and rendering checks, evidence location and a short handoff.

Do not create fixed research/design/code/review folder stages for every trivial
edit, copy source files into briefs, or use numbered folders as the only dependency
tracker. Real development loops include repairs and integration. Start with one
active brief and add structure only when a concrete coordination need appears.

The user's confidence-review requirement applies after code changes, and
rewrite-tournament applies after non-trivial code changes. ICM adds no new approval
chain and does not waive either requirement. Publication stays with the
[coordinator](pr-worktree-workflow.md).

Assess usefulness after a few completed tasks using context rereads, repeated
clarifications, stale-predecessor mistakes, integration defects and time spent
maintaining the briefs. If upkeep exceeds the benefit, reduce the structure.
No token or speed saving has been measured.
