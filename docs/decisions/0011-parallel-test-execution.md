# 0011: Parallel test execution with pytest-xdist

Date: 22 October 2026. Status: adopted (coordinator ruling, 22 October 2026).

## Context

PR #9's hosted "Product checks" job took 36m49s of its 40-minute budget
(`.github/workflows/ci.yml`, `timeout-minutes: 40`); `make product-check` takes about 26
minutes locally. M7 adds live-acceptance tests, CP-MODEL publication and CP-1A, so the suite
only grows. The hosted runner has 4 vCPUs and 16 GB; the suite ran on one process.

## Options

- **Raise the budget.** Hides the cost and slows every PR; rejected.
- **CI shards with coverage combine.** Matrix jobs plus an upload/download of coverage data
  and a combine job, all needing newly pinned actions and a new required status. Gains only
  hosted time; local runs stay slow. Rejected.
- **`pytest-xdist`.** One dev dependency (`pytest-xdist`, pinned by the lock like the other
  dev tools); local and hosted runs both gain; coverage from all workers is combined by
  `pytest-cov` into one report. Chosen.

## Decision

`make coverage` (and so `make product-check`) runs `-n auto --dist loadfile`. `loadfile`
keeps every test of one file on one worker, so module-scoped fixtures (the Playwright
browser, promoted stores) are created once per process and never shared across processes.
No test is marked serial. One test-side change was needed: rendering evidence directories were
named `<group>/<parent of tmp_path>/<test>`, and under xdist the parent is `popen-gw<n>`, which
repeats on every run, so a second run met the first run's directory. `tests/product/evidence.py`
(`evidence_path`) names them by every directory below the pytest root (run number, worker, test).

- **The coverage floor is evaluated on the combined report.** `fail_under = 90` applies to
  the single TOTAL line `pytest-cov` prints after merging every worker; it is unchanged, and
  a parallel run must report the serial run's percentage within 0.1.
- **Memory.** Workers multiply peak memory: the heaviest bindings tests peak near 2.3 GiB per
  process (`docs/ci-gates.md`, Linux parity). `--maxprocesses N` caps `-n auto`; set it on a
  small machine.
- **Serial runs.** Only `-n 0` is truly serial (no workers); use it when debugging an order- or
  path-sensitive failure. `PYTEST_XDIST_AUTO_NUM_WORKERS=1` with `-n auto` runs one xdist
  worker in a subprocess (`popen-gw0` paths), not a serial run.
- **Hosted worker count.** If `-n auto` resolves to 1 on the hosted runner, set
  `PYTEST_XDIST_AUTO_NUM_WORKERS: 4` in the job environment.

## Consequences

- `pyproject.toml` (dev group), `uv.lock`, the `coverage` target and `docs/ci-gates.md`
  change; the 40-minute budget stays.
- `tests/product/evidence.py` (`evidence_path`), `tests/product/test_evidence.py` and the seven
  test files whose evidence sites changed (`test_browser`, `test_delivery`, `test_execution`,
  `test_interface_view`, `test_narrative_projection`, `test_register_view`,
  `test_report_tables`) are new or changed because xdist names a test's temporary directory
  `popen-gw<n>`, which repeats across runs and collided with earlier evidence directories.
- Results must be identical serial and parallel; a test that needs a shared path takes a
  per-test path, never a serial marker.
- Not verified: the hosted wall time (the next PR shows it).
