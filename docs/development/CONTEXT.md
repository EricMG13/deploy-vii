# Development context

Current phase: development environment. Product implementation has not started.
The user's request authorizes this setup; [AGENTS.md](../../AGENTS.md) and
[decision 0002](../decisions/0002-development-environment.md) define its boundaries.

| Need | Authoritative context |
| --- | --- |
| Install tools, select a worker, run checks | [Environment guide](environment.md) |
| Active setup task | [Brief](tasks/environment/brief.md) · [Result](tasks/environment/result.md); owner: this chat's coordinator |
| Product architecture and method | [Architecture](../architecture.md) · [Methodology adaptation](../methodology-adaptation.md) |
| Model roles and test pool | [Worker matrix](../model-matrix.md) · [Test/telemetry contract](../testing-and-telemetry.md) · [Settings](../../settings/project.toml) |
| Frontend and reuse | [Direction C](../frontend-direction-c.md) · [Deploy VI assessment](../deploy-vi-reuse.md) |
| Quality and publication | [CI](../ci-gates.md) · [Sweeps](../maintenance-sweeps.md) · [PR/worktrees](../pr-worktree-workflow.md) |
| Historical context | [Research index](../../README.md) · [Sources](../research-sources.md) |

For the next product task, create one scoped brief with the actual base/head,
editable paths, dependencies, required reads and acceptance evidence. Link a
short result after verification. Keep source code in normal product folders and
raw test artifacts outside these briefs. Do not create a parallel stage hierarchy.

Next product boundary to specify: CP-0 readiness and the accepted artifact
contract, including how its first real output populates Direction C. Reuse
selected Deploy VI behavior only after validating dependencies and regression
cases. This next-step note does not mark that implementation complete.
