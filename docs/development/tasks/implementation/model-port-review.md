# Confidence review — selected deterministic Model port

Base `9199be4`; coordinator owns this checkout. This increment selects the
internal kernel and synthetic regressions described in
[reuse record](../../model-reuse.md). No delegated implementation, provider
switch or live model call. The development matrix leaves the coordinator as
selected; financial/provenance review workers, if needed, use Sol/high.

Least confident about, ranked:

1. **Old missingness assumptions becoming new analytical facts.** Traced sparse
   `history._sum/_resolved/_flow`, `statements._income/_zero_if_absent/_pf_add`
   and `debt._issued_after/_opening_debt`. Existing regression cases concretely
   demonstrate absent financing/add-back rows contributing zero, COGS absence
   selecting expenses by nature, and first observed facility rows implying zero
   opening. Explicit null behaves differently. Verdict: confirmed integration
   hazards, not new namespace-port regressions. No CLI, execution or report caller
   reaches this package (source-wide import search). These raw algorithms remain
   internal pending the new validated CP-1 adapter; required guards are recorded
   individually in the reuse document. This is not analytical acceptance.
2. **Debt bases or residuals silently changing meaning.** Traced facility keys,
   finance/operating lease handling, `_stated_total`, foreign exclusions and
   ratio note propagation. Synthetic regression reproduces Model debt 14,106
   versus CP-1 lease-exclusive debt 13,846, foreign exclusion and separate
   residuals. Verdict: behavior preserved; integration must label both bases and
   calculated residuals explicitly. No canonical CP-1 account is overwritten.
3. **A namespace/format adaptation altering arithmetic or imports.** Verified
   original bytes against the pinned Git objects and recorded SHA-256. AST
   comparison of all 30 complete production/test source files is equal after
   normalizing only import namespace/order and module docstrings. The three
   date helpers were extracted by AST source span; inspected regexes and helpers.
   Strict mypy checks all 19 source files. Verdict: verified preservation, no
   dependency on the old project at runtime. Only Python standard library and
   this package appear in the kernel import closure.
4. **Tests passing while preserving wrong financial expectations.** Inspected
   period, debt, missingness, sign, expense presentation and metric assertions
   against the reviewed pinned method. The 219 imported cases establish a
   baseline, including Hypothesis properties; they do not independently qualify
   CP-1 interpretation or model outputs. Their Example Gaming Co source labels
   are synthetic. Verdict: appropriate regression evidence with explicit limits.
5. **Precision claims and unvalidated input.** `_cells.CONTEXT` is 38 significant
   digits, half-even; public frame functions enter that local context. Raw
   dataclasses do not reject NaN, mixed units, duplicate IDs or cyclic graphs.
   Verdict: the old “no rounding” documentation was inaccurate; patched it to
   distinguish arithmetic precision from display quantization. Input validation
   remains an explicit open dependency, so these functions are not exposed as
   an external model-response API.
6. **Misleading coverage after editing during a test run.** The first complete
   run passed 301 tests but reported 82.59%, with executed definitions attributed
   to docstring lines: docstring edits changed line numbers while that run was
   active. Re-ran the real gate against a stationary source tree. Verdict:
   measurement invalidated by concurrent editing, not a coverage waiver. The
   clean run passes at 97.13%; keep source stationary during measurement.

Fixed: precision documentation; import namespace and ordering.

Verified fine: AST preservation, dependency closure, 219 kernel regressions,
301 full product tests, strict typing, formatting/lint, JS syntax. The full
product command was `make product-check` (301 passed in 23.93 seconds;
97.13% combined branch/statement coverage).

By design: no CLI/rendered output for this internal slice; no inherited parser,
host, projections, state, approvals or qualification. Thus no new completed
Module output or browser acceptance is claimed. Existing product browser tests
still pass as part of the full check.

Still open: the explicit CP-1 validation/adaptation boundaries in the reuse
document, full CP-1 tables and narrative, independent financial qualification,
Module report binding and CP-1A. Those are the next milestone-C work, not grounds
to mark C or the overall goal complete. OpenRouter spend remains US$0.

Rewrite tournament: skipped for unchanged imported algorithms and mechanical
import/doc edits under the skill's exclusion and user's key-area limit. No new
calculation/provenance/state algorithm was introduced in this port.
