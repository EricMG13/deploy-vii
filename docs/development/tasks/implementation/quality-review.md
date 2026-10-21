# CP-1 QA and numeric confidence: confidence review

Task `dvii-implementation-001`, milestone C. Base `d02aece`, branch
`claude/focused-cray-a5417d`. Scope: `quality.py` (r14 `CP_CONFIDENCE_SCORE`, exact
fractions), `cp1_quality.py` (pre-handoff CP-1 scope and external recomputation) and their
tests. Method pinned to Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`
(`reference/deploy-v-r14/CANON_SHARED.md`, status taxonomy D1 and `CP_CONFIDENCE_SCORE`). The
r14 reference script was read as data only; none of its code is imported or copied. No new
dependency or provider call. Neither module has a caller in `src` yet (only tests), so no
runtime path changed.

## Confidence review

Least confident about (ranked):

1. **Rounding and the score drifting from r14.** The reference script uses binary floats and
   `round()`. Scanned the script against the exact rational over lineage mixes, coverage and
   gates: 85 inputs differ, all exact .5 ties (for example 1 Directly Sourced plus 11 Calculated
   material claims, 1 of 8 slots, pass gives exactly 59.5; script 59, exact ties-to-even 60).
   **By-design adaptation, not a defect:** exact half-even is the stated contract. Pinned as a
   test and in quality.md. An independent integer-exact `Decimal` restatement written from the
   r14 text (single common denominator, `Inexact` trapped) agrees with `assess_quality` for the
   score, band, QA status and exact unrounded raw score. No other divergence found.
2. **Property test vacuity.** Measuring the first strategy showed 0 uncapped exact ties in 400
   examples and 83% capped, so rounding and the Passed branch were barely exercised.
   **Confirmed weakness; fixed** by adding a near-tie strategy (only minor open findings,
   pass/partial gate) with ties in about 3% of draws. A half-up rounding mutant now fails the
   property (it passed before); the half-even-equivalent rewrites correctly survive.
3. **Source gate and module status promoting a clean review.** r14's script derives QA status
   from findings only, so a partial or failed gate would read Passed. **By-design adaptation per
   D1**, pinned for all four gate/module cases; the CP-1 projection also checks that complete
   coverage with a passing gate still gives Restricted (40, no claims) and that a blocked
   narrative gives Blocked at or below 39.
4. **Empty mandatory registers improving coverage by losing cells.** Removing a register's rows
   and facts removes its cells from the denominator. Traced the six `populated:` slots: they stay
   absent and the total present count falls. Tested for T4.1, T4.2, T4.4, T4.5 and T4.6, both as
   empty rows and as an absent table, plus a genuine empty T4.10 from an incomplete add-back
   disclosure. **Verified fine.**
5. **Claim evidence mis-scoped across passages.** One claim per finding with distinct evidence
   IDs in first-appearance order; the test repeats evidence across passages and mixes prose and
   issuer parts. **Verified fine.** Claim evidence IDs are always inside `references` (checked
   by the contract).
6. **Authentication boundary.** `cp1_quality_inputs` only shape-validates its registers (a
   nested context or narrative status can be edited and still validate; the tests rely on that
   to reach each mapping). The recompute path `canonical_quality` / `validate_canonical_quality`
   rebuilds registers from external inputs; tests show a tampered score, registers or inputs, a
   review bound to other hashes, a stale pack, a substituted narrative and an old schema all fail
   closed. **By-design; documented.**
7. **Vacuous assertions in my own tests.** Two assertions could not fail (a tautology over the
   filtered set and a substring check over hashed IDs). **Confirmed; removed.**
8. **Source-gate double weight.** A partial gate lowers both the `source-gate` coverage slot and
   the multiplier. This follows the r14 text (coverage includes the source gate; S multiplies).
   **By-design.**
9. **Cost.** The fixture projection has about 42,000 slots, so each external recomputation costs
   seconds. **Open** (limitation recorded): no large-pack or transport qualification.

Mutation spot-check of `cp1_quality.py`: 13 hand-made mutants (table presence, cell statuses,
module-status and gate mapping, evidence de-duplication and passage scan, populated check,
dimension and story presence, T4.7 exclusion, funding) were each killed by the new tests; the
source was restored byte for byte afterwards. Of `quality.py`: six mutants (rounding, blend coefficients,
penalty, gate cap, cap value, band boundary) were killed.

Fixed: weak tie coverage in the property, two vacuous test assertions. Verified fine: register,
cell, claim, gate and module-status projection, empty-register handling, external
recomputation and tamper detection. By-design: exact rounding, D1 gate/module mapping,
source-gate double weight, shape validation not being authentication. Still open: large-pack
cost, analytical meaning of the judgments, canonical envelope/handoff.

## Rewrite tournament

**Incumbent holds (coordinator, 21 October 2026).** The coordinator ran the scoped tournament on
`src/deploy_vii/quality.py::_compute_confidence` (lines 165-221). Every role ran on Sonnet 5.5/high
in a fresh context. Each challenger passed the 77-test oracle on a copy:

- **Speed:** single-pass loops, a merged-denominator `raw` and hand-rolled half-even rounding
  before clamp and cap. About 4 µs faster per call, and identical on 30,000 differential cases.
- **Memory:** running sums and booleans.
- **Readability:** cap-as-data and a band table. Identical on 50,000 differential cases.

The blind arbiter's bracket went Q over P, then R over Q, then S (the incumbent) over R. The
incumbent keeps the line-by-line mapping to the r14 formula, the clamp-then-cap-then-round order,
and the native exact `round(Fraction)`. Those matter more than microseconds when the output is
hash-compared by auditors. After the tournament the file is byte-identical to the incumbent, and
`uv run --locked pytest tests/product/test_quality.py tests/product/test_cp1_quality.py -q` gives
77 passed.

## Verification

- `make product-check` (exit 0): ruff check and format (115 files), strict mypy (54 source
  files), JavaScript syntax, then 978 passed in 395.67s; branch-inclusive coverage 97.59%
  (floor 90%; the coordinator's pre-change figure was 96.95% with 927 tests). `quality.py` and
  `cp1_quality.py` are in the report's "skipped due to complete coverage" list, that is 100%.
  A focused run of the two modules' tests with `--cov=deploy_vii.quality
  --cov=deploy_vii.cp1_quality --cov-branch` gave 208 statements, 0 missed, 38 branches, 0
  partial, 100%.
- `make check` (exit 0): lock check, all-file hygiene hooks (including secrets-key and
  whitespace), ruff, `git diff --check`.
- `uv run --locked pytest tests/product/test_quality.py` runs 48 checks in about 1 second;
  `tests/product/test_cp1_quality.py` runs 29 checks (about 1.5 minutes at fixture scale, since
  each external recomputation rebuilds the registers).
- `make secrets` was not run (publication step, owned by the coordinator).

Not verified: no live or model-assisted analytical run; materiality, lineage and severity
judgments are not qualified; the canonical envelope/handoff, CP-1A and native-host behavior
do not exist yet; no large-pack scale or memory test; the r14 text was read from a pinned copy,
not re-fetched from the Deploy VI repository; `make check` and the full suite were run on a
worktree that also carried the coordinator's unrelated uncommitted edits; tournament
challengers were differential-tested on copies, not on validated pydantic inputs.
