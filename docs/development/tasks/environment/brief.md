# Development environment implementation plan

**Goal:** turn the reviewed research into one usable, verifiable development setup.
**Architecture:** project-local tools/configuration and ICM context; no product runtime.
**Stack:** Python 3.13.15, uv, Ruff, mypy, pytest, prek and GitHub Actions.

## Inputs

- Owner: this session's coordinator. Working directory: `/Users/ericguei/Documents/DEPLOY VII`.
- Base: existing private `EricMG13/deploy-vii`, clean root `f49845d`.
- Read set: all research linked by README and decision 0002.
- Protected sources: Deploy VI, the separate lowercase checkout and the supplied
  Direction C attachment. Inspect them; do not mutate them.

## Work and acceptance

- [x] Connect this folder to the existing root history on `codex/development-environment`.
- [x] Add project-local Python/dependency/editor/ignore settings and locked tools.
- [x] Configure deterministic hygiene/secret checks, CI and explicit future test targets.
- [x] Add development ICM index, current instructions, worker configurations, model-test
  settings and a portable Direction C reference with verified hash.
- [x] Reconcile research/status claims with active configuration and verify local checks.
- [x] Run confidence-review; classify rewrite-tournament applicability.
- [ ] Commit and publish one draft PR; inspect hosted checks and read back supported
  repository settings. Record unavailable enforcement accurately.

Commands: `uv sync --locked`, `make check`, `make secrets`, `make audit`,
`git diff --check`, configuration parsing and native configuration readback.
Use synthetic failing inputs to ensure relevant hygiene/secret checks reject them.
No paid/model calls, no financial calculations and no visual-acceptance claim.

## Outputs

Environment/config files, committed lock, active development guide, reference
provenance, PR URL and one result record with actual checks and remaining limits.
All tool logs stay in ignored `artifacts/setup/`; publish only concise safe findings.
