# Deploy VII

Development environment configured from the reviewed research, 20 October 2026.
Start at the [development context](docs/development/CONTEXT.md) and
[environment guide](docs/development/environment.md). Decisions [0002](docs/decisions/0002-development-environment.md)
and [0003](docs/decisions/0003-claude-coordinated-environment.md) record active choices;
[CLAUDE.md](CLAUDE.md), the only instruction file, scopes the work.

```sh
make setup   # locked tools and local Git hook
make check   # configuration and repository hygiene
make secrets # Gitleaks 8.30.1, files, staged changes and reachable history
make audit   # dependency vulnerabilities
```

Python 3.13.15 and uv 0.12.5 are pinned. Runtime dependencies and analytical
product code are intentionally absent. Type, functional and coverage commands
are prepared for the first product increment; an empty suite is not a pass.

## Latest requirements and assessment

| Request | Document | Result |
| --- | --- | --- |
| Random Luna / GLM 5.3 Flash / latest DeepSeek tests | [Testing and telemetry](docs/testing-and-telemetry.md) | High/xhigh by case; retain every attempt, output, metric and rendering artifact; compare matched cases. |
| ICM for development, as clarified | [Development context](docs/development-context.md) | Installed a small context index and per-task brief/result; product structure is unaffected. |
| Preserve Direction C, populate modules incrementally | [Frontend acceptance](docs/frontend-direction-c.md) | Bind tested Module outputs to their fields and verify data, provenance and browser rendering each increment. |
| Reuse, adapt or leave behind from Deploy VI | [Reuse assessment](docs/deploy-vi-reuse.md) | Prioritise deterministic logic, regression cases and the existing Workbench app; qualify selected imports. |

The [preserved supplied HTML](design/reference/README.md) is the visual reference. Its missing companion assets and
illustrative figures are documented. [Source hashes and model catalog metadata](docs/review-evidence/2026-10-20-sources.json)
identify the inspected versions; they are not live test results.
[Project settings](settings/project.toml) record the requested test pool,
telemetry and incremental Direction C acceptance. They are a contract for the
future runner, not an implemented test or rendering engine.

## Earlier research updates

| Requested update | Current document | Result |
| --- | --- | --- |
| Review methodology adaptations | [Methodology adaptation](docs/methodology-adaptation.md) | Adapt execution contracts; preserve analytical meaning; reassess earlier cuts and budgets. |
| Include GPT counterparts | [Model/reasoning matrix](docs/model-matrix.md) | Claude routes by task, effort, escalation and verification; GPT/Codex routes retired 21 October 2026. |
| Add refactoring and optimisation sweeps | [Maintenance sweeps](docs/maintenance-sweeps.md) | Bounded layer/integration sweeps with correctness and measurement criteria. |
| Review PR/worktree struggles | [PR and worktree workflow](docs/pr-worktree-workflow.md) | Evidence-based diagnosis and one coordinator owning publication by default. |

Related: [architecture/framework comparison](docs/architecture.md),
[CI gate review](docs/ci-gates.md), [plugin/hook assessment](docs/plugins-hooks.md)
and [primary research sources](docs/research-sources.md).

## Historical evidence

The original documents/settings were recovered using their Git blob hashes.
Current documents have since been updated; that recovery verification does not
claim edited files are unchanged.

- [Recovered conversation findings](docs/recovered-follow-up-findings.md)
- [Historical setup decision](docs/decisions/0001-research-foundation.md)
- [Historical setup/verification snapshot](docs/setup-status.md)
- [Inactive gate-settings snapshot](docs/research-settings/gates.toml.reference)
- [Inactive ruleset snapshot](docs/research-settings/github-ruleset.json.reference)

Those snapshots describe an earlier attempt and do not establish current policy,
enabled gates or qualification. Current configuration includes CI, narrow local
Git hooks and explicit worker launch settings. Global host settings are unchanged.
No Deploy VII product, live model test or performance sweep has been run.

This project uses `/Users/ericguei/Documents/DEPLOY VII`, connected to the existing
private repository's root history. The separate lowercase checkout remains
untouched. See the [setup result](docs/development/tasks/environment/result.md)
for verified local checks, publication and platform limitations.
