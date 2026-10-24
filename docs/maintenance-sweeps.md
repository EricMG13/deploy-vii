# Refactoring and optimisation sweeps

Design added 20 October 2026 for later development. No sweep, benchmark or
performance change has been executed in Deploy VII.

## Cadence

| Trigger | Scope | Exit |
| --- | --- | --- |
| A core layer passes functional and live acceptance | Inspect that layer before dependent implementation | Justified fixes or a short no-change finding; revalidate changes. |
| CP-5 core integration is exercised | Contracts, shared preparation and ownership across Modules | Consistent accepted artifacts; no known blocking defect in the tested scope. |
| An extension/shared utility changes consumers | Inspect affected dependency closure | Check invalidated consumers; explain reuse of unaffected evidence. |
| Measured latency/memory/cost regression | Target the measured bottleneck | Comparable before/after evidence and correctness, or reject the change. |

One owner performs a bounded pass using the [model matrix](model-matrix.md).
A sweep may conclude no change is justified. It adds no approval chain or repeated
whole-repository scan after each small edit. Code edits still require the user's
confidence-review and, for key-area code, a committed differential or property test (CLAUDE.md review regime).

## Refactoring pass

Inspect actual callers/error paths for unclear ownership, duplicated parsing,
repeated logic, dead paths, overgrown functions and abstractions that hide the
financial meaning. Prefer a small coherent change. Do not split functions solely
to improve a complexity score or remove useful test cases as duplication.

Preserve contracts, calculations, periods/units, source lineage, typed gaps,
refusals and limitations. A suspected defect starts with a causal failing case.
A behavior-preserving refactor needs relevant regression evidence, not tests
that only restate its new implementation.

## Optimisation pass

1. Capture baseline input/method/code identities, command, host, accepted outputs
   and targeted metric. Use comparable repeated runs where practical; label single
   observations and distinguish local work from model/network variance.
2. Profile or count actual work before choosing a change. Repeated source parsing,
   duplicate XLSX extraction, redundant validation and startup imports are possible
   targets. Historical findings elsewhere remain hypotheses in Deploy VII.
3. Change one bottleneck at a time. Preserve admission/validation at trust boundaries.
   Reuse verified immutable content with explicit invalidation; path or elapsed
   time alone cannot qualify a cross-run cache of financial evidence.
4. Compare accepted outputs and error cases, then the targeted metric. Record
   elapsed time, memory, reads, tokens or cost only when measured. Do not add nested
   timings or concurrent intervals into an invented wall-time saving.
5. Keep a change only when benefit justifies complexity and correctness holds;
   otherwise revert it and record the outcome briefly.

Parallel Module scheduling is a separate optimisation. Prove required/optional
input, ownership and failure semantics before claiming a speed benefit.

## Checks and handoff

The owner runs confidence review: rank doubts, inspect real paths, try to refute
suspected defects and fix confirmed causes. Run affected functional tests and
applicable calculation/source properties; sensitive mutation checks belong at
financial/provenance boundaries where warranted. Rerun invalidated checks only.

One concise handoff records scope, baseline, changed files, actual checks,
measured comparison, uncertainty and next action. Publish through the
[coordinator workflow](pr-worktree-workflow.md). A benchmark does not authorize
a semantic change or replace live layer acceptance. This document does not
authorize starting implementation or live tests.

Not verified: sweep duration, performance gain or maintained equivalence on real
Deploy VII code/packs; implementation has not begun.
