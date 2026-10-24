# CI gates: purpose, issues and new settings

Updated 20 October 2026. The environment now includes local checks and GitHub
workflows. [Decision 0002](decisions/0002-development-environment.md) selects the
current gates; the [setup result](development/tasks/environment/result.md) records
execution and enforcement status. Historical settings under `docs/research-settings/`
remain inactive snapshots. Future product gates below are not yet executable.

Review date: 2026-10-20. Inspected Deploy VI's working-tree CI, pre-commit,
pyproject and gate scripts plus locally recorded `origin/main` at
`bd71346301b373afa72655916a4c1b42bf4c9823`. This is not a fresh remote audit.

## Findings from Deploy VI

| Existing gate | Purpose | Observed issue or trade-off | Deploy VII treatment |
| --- | --- | --- | --- |
| Locked dependency sync/check | Reproducible tools and runtime | Sync and lock-check partly overlap; both run even for docs | Keep when dependencies exist; no runtime install in research CI. |
| Ruff lint/format | Catch likely defects and keep readable diffs | Whole-tree work repeats in hooks and CI | Keep; fast local scope, full applicable CI. |
| Strict mypy | Contract/type correctness | Includes test helpers; migration cost can dominate small changes | Strict product code first; expand intentionally. |
| pytest + 80% branch coverage | Functional behavior and missed branches | One percentage is not proof of financial correctness | Keep functional/property checks; coverage is a floor, not acceptance. |
| Corpus replay | Real document/calculation regressions | Private data unavailable on hosted runners; synthetic corpus reruns after pytest | Synthetic CI; required private acceptance locally. Never equate them. |
| Contract/catalog checker | Match prompts, tables and consumers | Can couple every small change to unused future Modules | Validate implemented core and actual declared dependencies only. |
| Suppression-count ceiling | Prevent accumulating ignored warnings | Counts can encourage code contortions without judging justification | Require targeted reasoned suppressions; report growth, review substance. |
| Ruff complexity + complexipy 15 | Identify difficult logic | Overlapping blockers can force superficial splitting | One advisory complexity report; financial/error behavior remains blocking. |
| Bandit + scan floor | Detect risky Python and silent empty scans | Blanket findings/fixed LOC floor can misfit a tiny new repo | Activate with Python code; findings triaged explicitly, parse/scan errors block. |
| pip-audit --strict | Known dependency vulnerabilities | Registry/network failures differ from vulnerabilities | Lock-change and scheduled audit; failed scan is unknown, never clean. |
| jscpd 3% incl tests | Detect copy/paste | Repeated test cases may be clearer than abstractions; adds Node setup | Advisory for product code when it exists; no research-phase dependency. |
| Gitleaks | Keep secrets out of history | Long custom range/floor logic has maintenance cost | Pinned full reachable-history scan initially; no provider secret in CI. |
| PR line cap | Keep changes reviewable | Historical policies used 800 and separately authorized 4000 | Advisory full-diff reporting, no arbitrary blocking cap; justify scope in the PR. |
| Whole workflow timeout | Bound runaway work | Working tree 20 minutes; recorded origin/main 240 minutes | Separate jobs with 10/75/10-minute limits (Product checks 75 since 24 Oct 2026: M6 took 36m49s on the hosted runner and M7 adds tests; 40 since the M2 PR); investigate timeouts. |

The existing checks protect valuable invariants. The concern is overlapping
execution and misleading proxies for quality, not the existence of validation.
No CI timing distribution was collected, so this review claims no measured saving.

## Current environment checks

The workflow defines these named jobs (the product job is described under Product checks shards):

1. **Repository hygiene:** YAML/JSON/TOML syntax, merge markers, file endings,
   trailing whitespace, private-key patterns and unexpected large files. Ruff
   applies when Python files exist; the committed lock is checked.
2. **Secrets:** checksum-pinned Gitleaks scans all fetched reachable history,
   redacts output and refuses scan errors. A shallow/empty scan is not accepted.

The product test shards run the browser tests on ubuntu, where the Front Page pixel
comparison skips with the stated reason "no reviewed baseline for linux": glyph
rasterisation differs between operating systems, so baselines
(`tests/product/baselines/<platform>/`) exist only for darwin, where they were reviewed.
Structure, zoom, keyboard, parity and zero-network checks still run there. Generate and
review Linux baselines before treating the pixel comparison as a CI gate.

**Linux parity.** Hosted CI runs ubuntu-24.04 with no real case pack under
`artifacts/public-case/`, no attempt evidence and no macOS `textutil`. Local runs must not
rely on any of them for coverage or for a green result. Where `textutil` is absent
`tests/product/conftest.py` puts a test double (`tests/product/fake_textutil.py`, itself tested
and compared with the real tool on macOS) first on PATH (re-exported by `tests/devtools/conftest.py` for the devtools differential,
which also builds RTF key fixtures), so the credential loader and the
live-runner tests run on both platforms; real-pack replay entries stay counted skips
(`skipped-pack-absent`) and are never a pass, while synthetic case packs cover the same code.
To reproduce the hosted run, commit, write the committed tree to a tar under a directory the
Docker VM can mount (with Colima, under `$HOME`), and run a clean container with no key file,
no artifacts and no textutil: `git archive HEAD -o "$DIR/tree.tar"`, then
`docker run --rm -v "$DIR":/lx:ro ubuntu:24.04 bash /lx/run.sh`, where `run.sh` does
`apt-get update -qq && apt-get install -y -qq curl ca-certificates git make nodejs`,
`mkdir /w && tar -x -C /w -f /lx/tree.tar && cd /w`, installs uv 0.12.5
(`curl -LsSf https://astral.sh/uv/0.12.5/install.sh | sh`), then `uv sync --locked`,
`uv run --locked playwright install --with-deps chromium` and `make product-check`. The
memory-heavy bindings tests peak near 2.3 GiB, so a single pytest process was killed
(exit 137) in a 3.8 GiB Docker VM; give the VM more memory or run one process per test
file with `--cov-append`.

**Parallel execution.** `make coverage` runs `pytest -n auto --dist loadfile` (decision
[0011](decisions/0011-parallel-test-execution.md)): one worker per CPU, all tests of a file on
one worker. The 90% floor applies to the single combined TOTAL report. Debug serially with
`-n 0` (`PYTEST_XDIST_AUTO_NUM_WORKERS=1` still runs one worker subprocess); cap workers with `--maxprocesses N` where memory
is short (the heaviest tests peak near 2.3 GiB per worker).

**Product checks shards.** The single hosted job outgrew its budget (55 to 63 min of 75 on
the 4-vCPU runner), so `Product checks` is now a gate job over six jobs: `changes` (the
docs-only detection above), `Product static checks` (ruff, format, mypy, `node --check`:
`make product-static`), three `Product tests (shard-a|b|c)` matrix jobs and `Product coverage
(combined)`. Each shard runs `make coverage-shard SHARD=<name>`, the same pytest command as
`make coverage` (`-m 'not live and not private'`, `-n auto --dist loadfile`, branch coverage) on
the files that `.github/shards/product.txt` lists for it, writes its own data file
(`COVERAGE_FILE=cov-<shard>`, uploaded with `actions/upload-artifact`) and has `--cov-fail-under=0`
because a part of the suite cannot meet the floor alone. The combined job downloads the
three files, runs `coverage combine` and `coverage report`, which enforces the unchanged
`fail_under = 90` of `pyproject.toml` on the combined total. A missing shard file fails the upload.
The static split by test file needs no dependency; `tests/devtools/test_ci_shards.py` fails if a
`tests/product` test file is in no shard or in two, or if the workflow matrix differs from the
list. A new test file must be added to `product.txt` (the guard says so). The `Product checks`
gate (one status for branch rules) succeeds only if every job succeeded, or, for a docs-only
diff, every test job was skipped; a failed, cancelled or unexpectedly skipped job fails it.
Each shard keeps `timeout-minutes: 75`. `make product-check` is unchanged locally: one process,
all tests, one coverage report.

Use read-only contents permissions and checkout without persistent credentials.
Pin Actions to verified commits. Keep model calls, private packs, publication and
provider credentials outside hosted CI. The old tool pins in decision 0001 are
historical, not newly installed or qualified by this document.

`make diff` reports the whole candidate against origin/main, including docs/tests.
There is no inherited hard line cap or excluded-path loophole. A separate audit
checks dependency-change PRs and supports weekly/manual runs; it is not a required
status context because unrelated PRs do not run it. Network errors fail that audit.

Prefer PR checks plus default-branch pushes to avoid redundant full runs on every
worker push. Manual dispatch can cover a deliberate standalone candidate. Bind
results to the actual tested commit; a prior head's green check is insufficient.

## Introduce these gates with the first relevant code

| Change / milestone | Blocking evidence required |
| --- | --- |
| Python implementation | Ruff, strict types, affected functional tests and locked dependencies. |
| Module prompt/schema | Contract validation, missing/conflicting inputs, citation fidelity and live layer rubric. |
| Financial calculation | Exact expected values, reconciliation, properties and sensitive changed-code mutations. |
| Source/parser changes | Source hashes, page/row boundaries, hostile text, unreadable/partial inputs and corpus cases. |
| Renderer | Direction C field/number/limitation parity, HTML escaping, source links, offline behavior and browser visual/accessibility checks after each tested Module. |
| Layer completion | Applicable local tests plus a real run from the user's Luna/GLM/DeepSeek pool; retained outputs/telemetry, factual source checks, analytical rubric and incremental HTML acceptance. |
| Final delivery | Complete applicable corpus/integration/security gates and native Copilot CLI acceptance. |
| Integrated worker commits | Combined contracts, ordering and affected consumers on the actual publication candidate. |
| Refactoring/optimisation | Affected behavior/properties plus baseline/output parity; measured evidence for speed claims. |

These are selected future acceptance requirements, not executable checks. Introduce
relevant commands with the first applicable code increment. A research check
cannot qualify future product behavior. Select coverage/security thresholds
against the actual code; previous numeric floors are not inherited automatically.

Private/live tests run outside hosted CI against agreed packs. Record method and
input hashes, requested/returned models, actual command/exit, outputs and limits.
Use the [testing and telemetry policy](testing-and-telemetry.md) and
[Direction C acceptance](frontend-direction-c.md). An LLM evaluator supplements
deterministic checks and never proves arithmetic.
Missing private inputs or live access leave the relevant acceptance pending.

## Docs-only pull requests and superseded runs

On `pull_request` events the `changes` job runs
`.github/scripts/code_changed.sh` over the changed paths and the static, shard and combine
jobs are skipped (the `Product checks` gate, name and status unchanged, still reports success) only when every path matches the allow-list: anything under `docs/` except
`docs/templates/` (the generated RV template and its README, which product tests pin), top-level
`*.md` (no slash), `LICENSE`, `LICENSE.*`, `LICENSE-*`, `.gitignore`, `.gitattributes`,
`CODEOWNERS`. The default is fail-closed: an empty diff, a fetch or diff error, a non-PR
event, any path with a slash outside `docs/` (so `src/.../x.md` counts as code) or any
other path (including `src/`, `tests/`, `pyproject.toml`, `uv.lock`, `Makefile`,
`.github/`, `settings/`, scripts and unknown files) runs the full suite. Repository
hygiene and Secrets always run. `make audit` is a local gate for dependency changes; the
"Dependency vulnerabilities" job lives in `.github/workflows/dependency-audit.yml` with
its own `pull_request` path filter and weekly cron. Concurrency groups by PR number and cancels superseded runs for
pull requests only; other events group by `run_id`, so a push to `main` is never
cancelled.

| Changed paths | Product test run |
| :--- | :--- |
| `docs/x.md`; `README.md`; `CHANGELOG.md`; `docs/my notes.md`; `docs/sub/dir/x.md` | skipped |
| `LICENSE_x/a.py`; `src/deploy_vii/prompts/x.md`; `tests/fixtures/notes.md` | full |
| `docs/ci-gates.md` + `src/deploy_vii/x.py` | full |
| `settings/project.toml`; `uv.lock`; `.github/workflows/ci.yml` | full |
| `scripts/anything`; `tests/devtools/t.py`; `foo.txt` | full |
| (empty) | full |

## Branch settings

The [desired ruleset](../settings/github-ruleset.json) requires PRs, resolved
review threads and the two exact Actions job contexts; it blocks deletion and
force-push. It chooses zero mandatory human approvals for the current solo-owner
workflow, with no bypass actors or extra agent approval chain. This is a deliberate
new setting, not inherited authority from the old snapshot. The user's required
review skills remain applicable. GitHub Actions app ID 15368 was verified through
the GitHub API. A JSON file does not establish branch enforcement.

The current private ruleset API returns HTTP 403 requiring a different account
plan or public repository. Neither is changed. Earlier hosted jobs were unable
to start; the [historical status](setup-status.md) and
[later findings](recovered-follow-up-findings.md) describe different stages of that
attempt. Neither proves current checks/protection. Current outcomes belong in
the setup result, independently from the workflow and desired ruleset files.

Use the [PR/worktree workflow](pr-worktree-workflow.md) for publication and
[maintenance sweeps](maintenance-sweeps.md) for bounded refactoring/optimisation.

Not verified: new hosted execution, current branch enforcement, future code/domain
gates, private corpus coverage or latency improvement.
