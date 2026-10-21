# Development context

Current phase: development tooling and product implementation, authorized by the
21 October 2026 request. [Implementation brief](tasks/implementation/brief.md)
records adopted decisions, acceptance, budgets and progress; the earlier research
does not override this request. [Decision 0002](../decisions/0002-development-environment.md)
still defines the selected environment.

| Need | Authoritative context |
| --- | --- |
| Install tools, select a worker, run checks | [Environment guide](environment.md) |
| Completed environment setup | [Brief](tasks/environment/brief.md) · [Result](tasks/environment/result.md); owner session: `01a15b2e-4bf1-72f1-bf44-e6abbfff34cc` |
| Coding-session context evaluation | [Brief](tasks/context-policy/brief.md) · [Result](tasks/context-policy/result.md); task ID: `dvii-dev-context-001`, same owner session |
| Context continuity and handoffs | [Policy/evaluation](context-management.md) · [Handoff template](handoff-template.md); development only |
| Product architecture and method | [Architecture](../architecture.md) · [Methodology adaptation](../methodology-adaptation.md) |
| Model roles and test pool | [Worker matrix](../model-matrix.md) · [Test/telemetry contract](../testing-and-telemetry.md) · [Settings](../../settings/project.toml) |
| Frontend and reuse | [Direction C](../frontend-direction-c.md) · [Deploy VI assessment](../deploy-vi-reuse.md) |
| Quality and publication | [CI](../ci-gates.md) · [Sweeps](../maintenance-sweeps.md) · [PR/worktrees](../pr-worktree-workflow.md) |
| Historical context | [Research index](../../README.md) · [Sources](../research-sources.md) |

For the next product task, create one scoped brief with the actual base/head,
editable paths, dependencies, required reads and acceptance evidence. Link a
short result after verification. Use a stable task ID and concrete owner/session,
worktree and snapshot base/head, rather than an owner label tied to the reader's
current chat. Re-read actual Git/process state on resume. Keep source code in normal product folders and
raw test artifacts outside these briefs. Do not create a parallel stage hierarchy.

Execution substrate: [internal API](execution.md).
Model kernel: [selected reuse and integration requirements](model-reuse.md).
CP-1 source boundary: [contracts, validation and remaining work](financial-inputs.md).
CP-1 statements: [source coverage and independent equations](statements.md) and
[typed tables/statement preview](report-tables.md).
CP-1 Model interface: [source registers, Markdown transport and candidate preview](model-interface.md).
CP-1 canonical registers: [all table projections and journal-bound preview](canonical-tables.md).
Full statement-line construction: [period arithmetic and source comparisons](statement-history.md).
CP-1 constructed periods: [historical series and operands](financial-periods.md).
Model historical output: [statement computations and ratio operands](model-output.md).
CP-1 arithmetic checks: [source-register reconciliation](financial-reconciliation.md)
and [constructed-period reconciliation](period-reconciliation.md).
CP-MODEL input gate: [selected historical readiness](model-readiness.md).
CP-1 KPI register: [canonical debt, income selection and ratio operands](canonical-kpis.md).
Annual audit differences: [sourced explanations and scope](audit-basis.md).
Cash movement: [explicit source adjustments and period combinations](cash-movement.md).
Net cash flow: [independent source equations and readiness](net-cash-flow.md).
Cross-statement checks: [equity and sourced balance movements](balance-movements.md).
Facility currencies: [source-bound FX normalization](facility-fx.md).
CP-1 source audit: [normalizations, definition conflicts and gap ledger](canonical-audit.md).
CP-1 source context: [evidence tiers, entity scopes and event binding](source-context.md).
CP-1 cumulative gaps: [source, period and KPI coverage](canonical-gaps.md).
CP-1 narrative: [prior evidence, analytical chains and story coverage](narrative.md).
CP-1 narrative delivery: [finding, evidence-trace and coverage projection](narrative-projection.md).
CP-1 readiness: [consumer sufficiency and historical Model gate](downstream-readiness.md).
Development CLI: [usage](workflow.md). Product CLI: [usage](product-cli.md). Product work starts with r14 coverage,
contracts and an honest unrun Direction C shell, followed by source readiness.
Reuse selected Deploy VI behavior only after validating dependencies and regression
cases. Implementation and live qualification are tracked separately in the brief.
