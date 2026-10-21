# CP-1 QA and numeric confidence

`quality.py` implements the r14 `CP_CONFIDENCE_SCORE` (Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`,
`reference/deploy-v-r14/CANON_SHARED.md`, status taxonomy D1) as exact arithmetic over
hash-bound judgments. `cp1_quality.py` projects the CP-1 QA scope from the candidate
canonical registers. Neither module qualifies analytical meaning: the score is a
deterministic function of supplied judgments, not evidence that those judgments are right.

## Contracts

| Contract | Version | Owner | Content |
| :--- | :--- | :--- | :--- |
| `QualityInputs` | `quality-inputs/1` | Producer | Artifact hash, coverage slots, candidate claims, source gate, module status, reference scope, inherited findings |
| `QualityReview` | `quality-review/1` | Analyst | Per-claim materiality and per-evidence lineage class, additional findings; binds `inputs_sha256` |
| `Confidence` | `confidence/1` | Python | Exact ratios, penalty, raw and rounded score, band, QA status |
| `QualityReport` | `quality-report/1` | Python | Input and review hashes, confidence, all findings, fixed limitations |
| `CP1QualityReport` | `cp1-quality/1` | Python | Canonical registers, projected inputs and report (`scope: pre_handoff`) |

No schema version was changed by this increment and old versions are rejected rather than
migrated. The producer owns required-field inventory (coverage slots), the source gate, the
module status and inherited findings. The analyst supplies only materiality, lineage class,
finding severity/status/resolution and rationale. No analyst field can carry a score, band or
QA status; `Confidence` is computed, and `validate_quality_report` rejects any report that does
not hash-equal a trusted recomputation.

## r14 mapping

`score = clamp((0.6 * E + 0.4 * C) * S - P, 0, 100)`, then caps, then the band.

- **E**: for each material claim the strongest bound evidence weight (Directly Sourced 1.0,
  Calculated 0.9, Assumption-Based 0.5, Analyst Inference 0.4, Weak Lineage 0.3, Untraced,
  Conflicting and Insufficient Information 0.0), averaged over material claims, times 100.
  Weights are held as integers (x10). No material claims gives `E = 0` (not "perfect
  evidence"), as in the r14 reference script.
- **C**: present slots over total slots, times 100. **S**: pass 1, partial 7/10, fail 0.
- **P**: CRITICAL 40, MATERIAL 15, MINOR 3 for each finding whose status is `open`; resolved,
  closed and cleared findings stay visible but carry no penalty or cap.
- **Caps**: any open CRITICAL caps at 39 and gives Blocked; any open MATERIAL (no CRITICAL)
  caps at 59 and gives Restricted; the cap is applied after the clamp and only lowers.
- **Bands**: 80 and above High, 60 to 79 Medium, 40 to 59 Low, below 40 Insufficient Information,
  taken from the rounded integer score.

Every intermediate value is a `Fraction` and is reported as a numerator/denominator pair.

### Deliberate adaptations

1. **Exact rounding.** The r14 reference script rounds a binary float with `round()`. Here the
   exact rational is rounded to the nearest integer with ties to even (`rounding` is recorded in
   the report). They differ on real inputs: 1 Directly Sourced plus 11 Calculated material claims
   with 1 of 8 slots present and a passing gate is exactly 59.5, which the script returned as 59
   (float noise) and this module returns as 60 (tie to even). Pinned in
   `test_adaptation_exact_half_even_rounding_differs_from_float_round_on_a_real_tie`.
2. **Source gate and module status to QA status.** The script derives `qa_status` only from
   findings. D1 states that a module's own run status sets its QA status unless a finding caps
   it lower, and a failed or partial source gate cannot yield Passed. Here a `fail` gate or a
   `blocked` module status gives Blocked (cap 39) and a `partial` gate or a `restricted` module
   gives Restricted (cap 59), even with no finding. A clean review therefore cannot promote
   either. Pinned in `test_adaptation_source_gate_and_module_status_map_to_d1_without_any_finding`.

An independent restatement written from the r14 text (integer-exact `Decimal` over one common
denominator, not derived from `quality.py`) is compared by a `hypothesis` property against
`assess_quality` for the integer score, band, QA status and the exact unrounded raw score over
random lineage mixes, material and non-material claims, coverage, gates, module statuses and
open/resolved finding severities, including producer-owned inherited findings. No other
divergence from r14 was found.

## CP-1 scope

`cp1_quality_inputs` projects, from trusted `canonical-tables/2` registers:

- one slot per required table (the 18 IDs T4.1 to T4.19 except T4.7) and one slot per fact in
  those tables, present when the fact is `known` or `not_applicable`;
- `populated:` slots for the mandatory data registers T4.1, T4.2, T4.4, T4.5, T4.6 and T4.10, so
  an empty register is counted absent instead of improving coverage by losing its cells;
- one slot per narrative dimension (present when explicitly assessed, including evidence-backed
  not-applicable), per required event/funding story, plus funding, analytical findings and the
  source gate;
- `canonical-handoff`, always absent: the final canonical envelope and handoff verification do not
  exist yet;
- one candidate claim per narrative finding, listing the distinct evidence IDs referenced across
  its evidence, risk and credit passages in first-appearance order;
- source gate pass, partial or fail from candidate, restricted or any other context status;
- module status `blocked` when the narrative is blocked, otherwise `restricted`, so a pre-handoff
  CP-1 can never be Passed.

`canonical_quality` recomputes registers from the external pack, source, financial, definition,
binding, narrative and readiness inputs, then projects and assesses. `validate_canonical_quality`
recomputes the same way and compares content hashes; a stale or substituted input, a review bound
to other inputs, tampered registers, inputs or score, and an invalid report all return issues.
Shape validation of a report against its own embedded inputs is not authentication.

## Limitations

- Materiality, lineage, severity and resolution are judgments needing semantic review; the
  arithmetic does not qualify them. `analytical_qualification` stays `unrun`.
- Coverage counts register presence and explicit assessments, not the correctness of the
  extraction. Fixture tests use synthetic data.
- The projection is large (tens of thousands of slots for the fixture), so recomputation costs
  seconds at fixture scale; scalability on large packs is unqualified.
- Passed QA is distinct from committee readiness, Module acceptance, analytical qualification and
  native-host qualification.

## Remaining

The canonical Markdown envelope and handoff (and the `canonical-handoff` slot), the analytical
review that supplies lineage and materiality judgments, final promotion, CP-1A and live or
native-host qualification remain pending. The Python arithmetic is a key-area calculation; its
rewrite tournament kept the incumbent (see the review).

Review: [confidence review](tasks/implementation/quality-review.md).
