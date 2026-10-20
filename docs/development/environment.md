# Development environment

The environment is project-local. [Decision 0002](../decisions/0002-development-environment.md)
explains choices and supersedes historical setup policy. Read the
[setup result](tasks/environment/result.md) for actual validation and remote status.

## Install and check

Prerequisites: Git, uv **0.12.5**, Python **3.13.15** (uv can provision it), and
Gitleaks **8.30.1** for secret scans. GitHub CLI is needed only for publication.
Run commands from the repository root:

```sh
make setup
make check
make secrets
make audit
```

`make setup` synchronizes the committed lock and installs a prek pre-commit hook
in this checkout. Each new checkout/worktree needs setup. It does not register
global plugins or hooks. `make check` checks the lock, all tracked applicable files,
and unstaged/staged whitespace. Hooks use the locked environment through uv.

`make secrets` scans working files, staged changes and full reachable Git history;
the staged scan catches a secret that is absent from the current working file.
It fails on
shallow history or scan errors. CI downloads Gitleaks with a verified checksum.
`make audit` audits installed locked dependencies; a network or resolution error
is a failed/unknown audit, never evidence of no vulnerabilities.

Use `uv add --group dev <tool>` for deliberate tool changes, review `pyproject.toml`
and `uv.lock`, then rerun check/audit. No global Python packages are installed.
Ignore rules keep caches, credentials, private packs and raw artifacts local.
They are convenience boundaries, not protection against `git add --force`.

## First product increment

The repository has no product Python files or test suite. These commands are
prepared, and deliberately fail if invoked before their inputs exist:

```sh
make types     # strict mypy on src
make test      # pytest, excluding live/private cases
make coverage  # branch measurement for the same suite
```

Introduce real `src/` and `tests/` with the first increment; wire their checks into
CI and the branch requirements at that point. Select a meaningful coverage floor
against actual behavior. Add parser/runtime dependencies only when needed.
Do not turn an empty test run into a green product gate.

## Explicit worker routes

The current coordinator retains its selected model. Codex workers use explicit
Make targets, for example `make codex-feature`. These launch interactive sessions
with native model/effort flags. They are not custom subagent registrations or
desktop model selectors. The installed CLI's `--profile` selects global profile
files, so this setup avoids the obsolete project profile-table assumption.
See [.codex/README.md](../../.codex/README.md) for the verified host behavior.

Claude definitions in `.claude/agents/` are project subagents. Select a named
worker explicitly for a scoped task; descriptions avoid automatic broad routing.

| Role (Claude name; Codex Make suffix) | Codex | Claude | Effort |
| --- | --- | --- | --- |
| dv-scaffold; scaffold | GPT-6.1 Sol | Sonnet 5.5 | low |
| dv-feature; feature | GPT-6.1 Sol | Sonnet 5.5 | medium |
| dv-sensitive; sensitive | GPT-6.1 Sol | Sonnet 5.5 | high |
| dv-research; research | GPT-6.1 Sol | Sonnet 5.5 | medium |
| dv-architect; architect | GPT-6 Astra | Fable 5.1 | high |

Research/architecture Codex launch targets request a read-only sandbox; Claude
definitions omit write/shell tools. Host policy, permission settings and model
entitlement still determine actual capability. Prose path scope does not isolate
Git refs/credentials. No worker calls or live entitlement tests are part of setup.
Use [model routing](../model-matrix.md) and [publication ownership](../pr-worktree-workflow.md).
Required review skills may delegate within their explicit scope; this is not
authorization for recursive task expansion.

## Settings versus running behavior

[settings/project.toml](../../settings/project.toml) is the versioned project
contract. Its flags explicitly say the product and live runner are absent.
The model pool, effort mapping, artifact retention and frontend acceptance fields
must be consumed and tested by the future runner. They do not perform model calls.
Copy `.env.example` to a local `.env` only when a live runner needs credentials;
setup does not load it or require a provider key.

The supplied [Direction C reference](../../design/reference/README.md) is preserved
exactly. It depends on missing companion assets, so it is not a functional report.
Each implemented Module must later populate its mapped fields and pass factual
and browser checks. Keep sample figures separate from real accepted outputs.

GitHub Actions uses `ubuntu-24.04` and defines **Repository hygiene** and **Secrets**
on PRs and main pushes. The OS label avoids the moving `ubuntu-latest` migration;
the [runner image documentation](https://github.com/actions/runner-images) lists
supported labels. The separate audit runs for dependency-change PRs and on a weekly/manual
schedule. Its schedule becomes active only after the workflow reaches main.
[Desired repository settings](../../settings/repository.json) and
[desired ruleset](../../settings/github-ruleset.json) are reviewable API payloads;
files alone do not apply them. Private ruleset access currently returns HTTP 403.
The setup result distinguishes applied settings, executed checks and unavailable
enforcement. Do not merge on an unstarted or failed required check.

Global plugins/MCP/hooks remain host state; this project does not disable them.
See the [assessment](../plugins-hooks.md). Raw output can still be observed by
enabled host tooling; sanitized ICM summaries do not change that host behavior.
