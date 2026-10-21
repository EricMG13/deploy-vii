# 0002 — Development environment and active settings

Date: 20 October 2026. Status: selected for implementation under the user's
request to reconcile the research and configure the development environment.
This supersedes research-only setup restrictions and conflicting historical
workflow recommendations. It authorizes environment setup, not analytical product work.
The Workers, Reviews and Plugins/hooks rows are superseded by
[decision 0003](0003-claude-coordinated-environment.md).

## Decisions

| Area | Selected configuration | Reason / boundary |
| --- | --- | --- |
| Workspace | This uppercase `DEPLOY VII` folder, based on the existing private repository's clean root | Preserve the restored research and the single repository history. The lowercase checkout stays untouched. |
| Python | 3.13.15 locally and in CI; supported development series 3.13 | Available locally and a conservative baseline for later PDF/XLSX libraries. Revisit broader runtime compatibility during packaging. |
| Dependency manager | uv 0.12.5; committed lock; `uv sync --locked` | Repeatable project environment without global package changes. |
| Development tools | Ruff, strict mypy, pytest/coverage/Hypothesis, prek, pre-commit-hooks, pip-audit | Retain the research's explicit strict-type decision. Use prek to run small deterministic hooks. No runtime library or agent framework yet. |
| Current gates | Repository hygiene and Secrets; dependency audit separately | Checks match environment/configuration work. Product tests/types/coverage become blocking with the first product code. No empty suite is labelled a pass. |
| Hosted OS | Ubuntu 24.04 label | Avoid the announced ubuntu-latest migration while retaining supported hosted images; image contents still receive updates. |
| Size/complexity | Report full diff; no arbitrary blocking line cap or duplicate complexity gate | Task scope and coherence matter more than inherited 800/4000 limits. Large changes need a clear rationale in the PR. |
| Development ICM | One index, per-task brief/result, shared decisions | Separate development context from product architecture; avoid a second mirrored plan hierarchy. |
| Workers | Explicit Claude subagents and Codex Make launch targets with model/effort; coordinator keeps current selected model | Installed Codex uses global profile-v2 files, so native CLI flags avoid global changes. No recursive task expansion; one owner per worktree; coordinator owns publication. |
| Reviews | confidence-review after code; rewrite-tournament after non-trivial code | Current user instructions override old retirement notes. No extra approval chain. |
| Model tests | User's random Luna / GLM 5.3 Flash / latest DeepSeek pool; high/xhigh; retained evidence | Store project settings now. A real runner and issuer/module tests belong to product increments. Do not fake a telemetry implementation. |
| Frontend | Preserve supplied Direction C reference byte-for-byte, with a provenance record | Each later tested Module must render its fields. No report app or backend is implemented by environment setup. |
| Plugins/hooks | No new MCP/plugin/global hook registration; narrow local Git hooks | Existing host plugins remain host state. Project instructions cannot prove inherited hooks are disabled. |
| Publication | One setup branch and reviewable draft PR; squash merges only, delete merged branches, read-only Actions token | No force-push or rewrite of the clean root. No automatic merge. |
| Branch protection | Prepare exact required-context ruleset; apply only if supported | Current private-repository ruleset access returns 403. Do not alter account plan or repository visibility. |

Alternatives considered: importing Deploy VI's environment would carry conflicting
policies and too much machinery; installing a full agent framework/runtime now
would select product architecture before its first tested boundary. The selected
setup installs only development tooling and explicit project configuration.

All current research documents were reviewed, including historical setup/settings,
methodology, architecture, model routes, CI, plugins, sweeps, publication, testing,
development ICM, frontend and reuse. Historical documents retain their labels.
The plugin assessment's tournament-retirement claim is corrected; source evidence
does not silently become active policy.

References: [uv locked environments](https://docs.astral.sh/uv/concepts/projects/sync/),
[uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/),
[Claude settings precedence](https://code.claude.com/docs/en/settings),
[GitHub ruleset availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).
