# Refactoring and optimisation sweeps

Design added 20 October 2026 for later development. Sweeps executed since are
recorded under [Sweeps performed](#sweeps-performed).

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
confidence-review and, for key-area code (CLAUDE.md review regime), rewrite-tournament.

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

## Sweeps performed

### M7 7.12: envelope write path memory (23 October 2026, optimisation pass)

- **Scope.** `envelope.write_envelope` and `register_envelope` on the synthetic
  `staged()` case (3,529,566-character Markdown, 43,202,184-character sidecar).
  Trigger: measured memory regression (the 4 GiB Linux parity VM killed 14 test files).
- **Baseline** (base 1f9070f, macOS 26.5.1 arm64, Python 3.13.15, pydantic 2.14.1,
  `ru_maxrss` per stage, three runs): `write_envelope` adds 0.525 to 0.528 GB
  (peak 1.338 to 1.347 GB, 1.52 to 1.63 s); `register_envelope` adds 0.26 to 0.28 GB.
- **Profile.** The largest avoidable cost is the str form of large JSON. The JSON holds
  an em dash, so a `model_dump_json()` str takes two bytes per character (86 MB for
  the 43 MB module). `content_hash()` then encodes it back for hashing. This happens
  once for the module hash and once for the 57 MB registers hash, and once more for the
  re-validation input. The other two costs are fixed by design: the validated copy of
  the envelope (about 0.18 GB with its input) and the returned sidecar str (about
  0.13 GB).
- **Candidate** (measured, then reverted): hash the module and the registers from
  `__pydantic_serializer__.to_json()` bytes, which are the bytes `content_hash()`
  hashes, and validate from those bytes. It was byte-identical: 309 distinct
  write/read/register inputs across 15 envelope test files and the replay corpus gave
  the same outputs, refusal texts and issues. The `write_envelope` delta fell to 0.393
  to 0.399 GB, a 25 % cut, below the brief's 30 % threshold. Ordering the sidecar dump
  first had no effect.
- **Outcome: no change.** Both fixed costs stay because they are the re-validation
  trust boundary and the `(str, str)` API. Next action, for the coordinator to decide:
  adopt the candidate on its other measured benefits. It takes the pipeline peak from
  1.34 to 0.98 GB, the `register_envelope` delta from about 0.27 to 0.03 to 0.05 GB, and
  the round-trip test process from 1.52 to 1.04 GB.
- **Uncertainty.** No Linux figure; no real pack (absent).

Not verified: sweep duration, performance gain or maintained equivalence on real
Deploy VII packs (no sweep has run on one); the 7.12 figures are macOS only.
