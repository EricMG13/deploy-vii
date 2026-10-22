# CP-1 QA and numeric confidence

`quality.py` implements the r14 `CP_CONFIDENCE_SCORE` (Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`,
`reference/deploy-v-r14/CANON_SHARED.md`, status taxonomy D1) as exact arithmetic over
hash-bound judgments. `cp1_quality.py` projects the CP-1 QA scope from the candidate
canonical registers. Neither module qualifies analytical meaning: the score is a
deterministic function of supplied judgments, not evidence that those judgments are right.

## Contracts

| Contract | Version | Owner | Content |
| :--- | :--- | :--- | :--- |
| `QualityInputs` | `quality-inputs/2` | Producer | Artifact hash, coverage slots, candidate claims, source gate, module status, reference scope, one lineage ceiling per reference, inherited findings |
| `QualityReview` | `quality-review/1` | Analyst | Per-claim materiality and per-evidence lineage class (at or below its ceiling), additional findings; binds `inputs_sha256` |
| `Confidence` | `confidence/1` | Python | Exact ratios, penalty, raw and rounded score, band, QA status |
| `QualityReport` | `quality-report/1` | Python | Input and review hashes, confidence, all findings, fixed limitations |
| `CP1QualityReport` | `cp1-quality/1` | Python | Canonical registers, projected inputs and report (`scope: pre_handoff`) |

Task 6.3 (decision 0005 MC-5) moved `QualityInputs` from `quality-inputs/1` to
`quality-inputs/2` by adding `ceilings`. Old versions are rejected rather than migrated, and
because the inputs version and content are hashed into `inputs_sha256`, a review bound to
`quality-inputs/1` inputs no longer binds and must be re-supplied. The producer owns
required-field inventory (coverage slots), the source gate, the module status, inherited
findings and each reference's lineage ceiling. The analyst supplies only materiality, a lineage
class at or below each ceiling, finding severity/status/resolution and rationale. No analyst
field can carry a score, band or QA status; `Confidence` is computed, and
`validate_quality_report` rejects any report that does not hash-equal a trusted recomputation.

## Lineage ceiling (MC-5)

Python, not the model, fixes each evidence ID's highest lineage class from the register that
produced it (`EvidenceCeiling`: `evidence_id`, `ceiling`, `basis`). The basis table is
`quality.CEILINGS`: `citation` caps at Directly Sourced, `calculation` at Calculated,
`estimate` at Assumption-Based, and `gap`, `missing` and `coverage` at Insufficient Information. A ceiling that does not follow its
basis is rejected, and `QualityInputs` must carry exactly one ceiling per reference, with no
extras, duplicates or omissions.

The analyst may keep the ceiling or lower it, with the nonblank rationale every
`EvidenceLineage` already requires. `validate_quality_review` compares weights: a supplied class
whose weight exceeds its ceiling's weight is the issue
`QA lineage upgrade rejected: <evidence_id> <lineage_class> above ceiling <ceiling>`, and
`assess_quality` raises on it. An upgrade is never a score input. Classes of equal weight are
not upgrades, so a bottom ceiling admits Untraced, Conflicting or Insufficient Information. The
score arithmetic is unchanged and uses the supplied (now bounded) class.

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
- `canonical-handoff` (task 6.4): present when the canonical envelope of these registers
  round-trips (`envelope.handoff_issues(register_envelope(registers))` is empty: written, read
  back, every r14 section, cell, evidence marker, prose run and footer hash verified against its
  sidecar); absent otherwise, with the first issues as its rationale (`Canonical envelope does
  not verify: ...`). The register envelope carries no QA section, because QA is computed from
  this slot, and no journal binding. The slot is a deterministic function of the registers, so an
  analyst can bind a review to the inputs before promotion. The promoted envelope, which adds QA
  and the journal inputs, is verified again at promotion; a failure there refuses promotion
  ([execution](execution.md)) but does not change these inputs;
- one candidate claim per narrative finding, listing the distinct evidence IDs referenced across
  its evidence, risk and credit passages in first-appearance order;
- source gate pass, partial or fail from candidate, restricted or any other context status;
- module status by the decision 0007 item 5 rule: `blocked` when the narrative is blocked,
  `restricted` when the module has own limitations or the narrative status is not
  `candidate`, otherwise `complete`, so a pre-handoff CP-1 can be Passed;
- one lineage ceiling per reference, from its register (`cp1_quality._lineage_basis`):
  - `citation` for source, entity, subsequent-event, source-period, definition and
    multi-figure-event records that carry a citation, and for observations and statement cells
    that carry a citation and a `known` or `not_applicable` status;
  - `missing` for those same registers without a citation, for a source whose availability
    is not `ready`, and for a `missing` or
    `conflicting` observation or statement cell even when it cites where the value was sought;
  - `calculation` for normalization, source-check, period-check, period-construction and
    model-basis records, and for historical values, canonical values, KPIs and computations
    with an amount; `missing` when one of those has no amount (Not Calculable, Not Available);
  - `estimate` for a historical value, canonical value, KPI or computation whose amount is
    `Estimated` or `Proxy` (its `calculation_status`): an estimated or proxied figure is
    assumption-based by definition, so a supplied Calculated is an upgrade;
  - `gap` for gap-register records and narrative gap IDs, and `coverage` for coverage slots,
    which are finding targets, not evidence;
  - any other catalogue kind raises `No QA lineage ceiling for register kind: <kind>`, and an
    identity reached from two registers with different bases raises instead of picking one.

`canonical_quality` recomputes registers from the external pack, source, financial, definition,
binding, narrative and readiness inputs, then projects and assesses. `validate_canonical_quality`
recomputes the same way and compares content hashes; a stale or substituted input, a review bound
to other inputs, tampered registers, inputs or score, and an invalid report all return issues.
Shape validation of a report against its own embedded inputs is not authentication.

## Limitations

- Materiality, lineage within its ceiling, severity and resolution are judgments needing
  semantic review; the arithmetic does not qualify them. `analytical_qualification` stays
  `unrun`. The ceiling bounds the lineage class; it does not prove the cited record supports the
  claim.
- Coverage counts register presence and explicit assessments, not the correctness of the
  extraction. Fixture tests use synthetic data.
- The projection is large (tens of thousands of slots for the fixture), so recomputation costs
  seconds at fixture scale; scalability on large packs is unqualified.
- Passed QA is distinct from committee readiness, Module acceptance, analytical qualification and
  native-host qualification.

## Remaining

The analytical review that supplies lineage and materiality judgments (a live model or analyst
QA review), CP-1A and live or native-host qualification remain pending. The envelope and the
promotion that consumes a `QualityReview` landed in task 6.4
([canonical envelope](canonical-tables.md), [execution](execution.md)). The Python arithmetic is
a key-area calculation; its rewrite tournament kept the incumbent (see the review).

Review: [confidence review](tasks/implementation/quality-review.md).
