# Confidence review — development workflow

Scope: new `devtools` package, tests, CLI/Make/CI integration. Coordinator read
the full candidate. Required review roles used GPT-6.1 Sol/high under the matrix;
the coordinator owns fixes and verification.

Least confident about, ranked:

1. **Budget/pause/history loss through a new checkpoint.** Confirmed: the first
   implementation accepted replacements without continuity checks. Reproduced
   decreasing spend, changing cap and deleting budget. Fixed at checkpoint entry:
   immutable parent identity, stable task/goal/owner, retained corrections and
   constraints, fixed caps, nondecreasing spend; pause release needs recorded
   authorization evidence. Regression tests cover all three budget mutations and
   linked history. Assertions remain observational, not authenticated authority.
2. **Tree identity missing live inputs.** Confirmed: symlinks originally hashed
   their path only; a target changed without detection. Now hashes include the
   resolved regular file. Scratch-Git tests cover HEAD/index/unstaged/untracked,
   ignored explicit sources, target changes, missing files and detached HEAD.
   Detached HEAD initially failed symbolic-ref; fixed with rev-parse abbrev-ref.
3. **Atomic failure/concurrent writers.** Atomic temp-file/fsync/rename preserves
   old bytes on a simulated pre-rename failure and removes the temporary file.
   Nonblocking file locking serializes record updates; two fingerprint scans
   reject ordinary drift. By design this is not a worktree lock, process stop,
   transfer or atomic filesystem snapshot. External writers still need reconciliation.
4. **Telemetry double-counting and raw evidence corruption.** Explicit Codex
   cumulative vectors and Claude request IDs deduplicate; contradictory request
   usage is retained but excluded. Confirmed missing report-time hash checks;
   now manifest and raw hashes are checked, with a tamper regression. No sum of
   cumulative/cached/reasoning subtotals. No claim of billing or occupancy knowledge.
5. **Private content entering summaries.** Normalization allowlists only known
   host/kind/hashed identities and nonnegative integer metrics. Prompt/response
   text is retained only in ignored raw files. Explicit probes reject bool/negative
   metrics and prove prose/session text absent. Unknown metrics have null/reasons.
   Hashes are integrity checks, not signatures against an adversarial local writer.
6. **Malformed JSON, paths and unsupported host logs.** Context requires typed
   fields and finite JSON; budgets have unique units and explicit cap/consumed.
   Stores must be ignored and inside the checkout with no tracked files. Only
   explicitly supplied rollout/assistant JSONL formats are normalized; malformed
   lines and unrecognized events remain reported, not counted as success.
   Source symlink failures and directory/submodule inputs fail visibly.
7. **Prose scenarios mistaken for enforcement.** All C01–C09 now have executable
   tests against actual scratch Git or telemetry records. Every CLI command is
   exercised as a subprocess, including nonzero stale/malformed exits. A clean
   preflight still says ownership unverified, transfer NOT_READY, no automatic reset.
8. **Review or routing drift.** Full context equality detects removed/changed
   reviews, routes and corrections. The tool cannot establish whether a declared
   review, process status or model route is truthful. Revalidation of original
   evidence and actual host state remains necessary.

Fixed: budget reset, missing parent identity, symlink target omission, detached
HEAD failure, missing-input clean preflight, unchecked telemetry evidence hashes.

Verified fine: nine scenarios, CLI exits, atomic replacement failure, privacy
allowlist, cumulative/request separation and caller types. `make dev-check`:
26 passed; Ruff check/format passed; strict mypy passed on five source files.

Still open: actual native log-format qualification beyond the two documented
formats, live host ownership/control and causal context-quality experiments.
These are explicitly outside the observational CLI's demonstrated behavior.
No real telemetry was imported, no live reset occurred, no paid model test ran.

Bounded maintenance sweep: kept development code separate from product; no
extra framework, watcher or lifecycle controller. The rewrite winner removes
duplicate normalization and directly accumulates unique findings. No broad
performance benefit is claimed from microbenchmarks.
