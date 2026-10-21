# M6 canonical envelope: result note

Date: 21 October 2026. Plan v2 M6; review W10. Later M6 tasks append sections.

## 6.1 CP-MODEL artifact

Task `dvii-impl-m6-cp-model`. Encodes decision 0006 DC-5: CP-MODEL's artifact is the
HTML Model destination plus the calculation JSON (the `ModelReport` CP-1 computes), not
the r14 XLSX workbook, which is deferred.

What changed:

- `methodology.json` CP-MODEL: `required: ["CP-1"]`, title and purpose reworded. The
  direct CP-0 edge is dropped: CP-0 reaches CP-MODEL through CP-1
  (`plan(("CP-MODEL",)) == ("CP-0", "CP-1", "CP-MODEL")`), and no test needed the direct
  edge. `edge_rule("CP-MODEL", "CP-0")` now raises, as for any transitive pair.
- No new `Responsibility` field (the smaller change): the artifact kind lives in
  `purpose` and the coverage map.
- `registry.py`: CP-MODEL leaves `_NOT_CP5_FAN_IN`, so a selected CP-MODEL is a CP-5
  analyst input (`restricted` edge). `edge_rule("CP-MODEL", "CP-1")` is the default
  `block`.
- `docs/methodology/r14-coverage.json`: `primary_kind` is `html_model_destination`,
  `calculation_json: true`, the workbook sheet list moved under
  `deferred.xlsx_workbook` with the DC-5 reason; edge `CP-0 -> CP-MODEL` replaced by
  `CP-1 -> CP-MODEL`; implementation is `partial (artifact defined; destination
  rendering in M6.5/M8)`, the other three statuses unchanged.

Pathways: no preset requests CP-MODEL (decision 0009 owns them, not edited). `plan()`
does not pull CP-MODEL in for CP-5 (CP-5 requires only CP-0, the fan-in applies only to
selected modules), so CP-MODEL runs when requested explicitly. Asserted in
`test_cp5_fan_in_includes_selected_cp_model_but_does_not_pull_it_in`.

Evidence: `tests/product/test_registry.py` (requirement, plan order, fan-in,
coverage map) and `tests/product/test_execution.py` (blocked CP-1 blocks CP-MODEL;
blocked CP-MODEL restricts CP-5). CP-MODEL stays outside the CP-0 consumer-readiness
review (`validate_review` and `current_inputs` already exempt it).

Not verified: destination rendering and calculation-JSON emission (M6.5/M8); that
CP-5's prompt consumes a CP-MODEL input; whether product intent wants Pathways to
request CP-MODEL.

## 6.3 QA lineage ceiling

Task `dvii-impl-m6-lineage-ceiling`. Review W2, decision 0005 MC-5: Python derives each
evidence ID's highest lineage class from the register that produced it; the QA model may
only keep or lower it.

What changed:

- `quality.py`: `EvidenceCeiling` (`evidence_id`, `ceiling`, `basis`) and the basis table
  `CEILINGS` (citation Directly Sourced; calculation Calculated; gap, missing and coverage
  Insufficient Information). A ceiling that disagrees with its basis is rejected.
  `QualityInputs` is now `quality-inputs/2` with a required `ceilings` field, exactly one
  per reference. Reviews bound to `quality-inputs/1` inputs no longer bind.
- `validate_quality_review` rejects any supplied class whose weight exceeds its ceiling's
  weight with `QA lineage upgrade rejected: <evidence_id> <lineage_class> above ceiling
  <ceiling>`, and `assess_quality` raises on it. `_compute_confidence` is unchanged.
- `cp1_quality.py`: `_lineage_basis` maps every narrative catalogue kind. A record needs a
  citation, and a located value also needs a settled status, to cap at Directly Sourced. An
  unavailable source, a missing or conflicting observation or statement cell (24 fixture
  observations cite where a missing value was sought) and a calculated register with no
  amount (Not Calculable or Not Available KPIs, values and computations) cap at Insufficient
  Information. Coverage slots and gap IDs cap at Insufficient Information. An unlisted kind
  raises with its name, and an identity reached from two registers with different bases
  raises.

Deviations from the brief: the brief's table keyed only on register kind. Reading the
fixture registers showed that a kind-only rule would let the model rate a Not Calculable
KPI as Calculated or a missing observation as Directly Sourced, so the producer also reads
the record's own value state. `coverage` was added as a basis because coverage slots are
references (finding targets) but not evidence. `tests/product/test_cp1_quality.py` changed
because its synthetic lineage review supplied Directly Sourced for KPI evidence, which is
now an upgrade; it now caps each supplied class at the ceiling.

Evidence: `tests/product/test_quality.py` (`test_model_cannot_upgrade_lineage`,
`test_downgrade_is_accepted`, `test_ceilings_must_cover_every_reference_exactly_once`, the
basis table, bottom ceilings, required field, and the hypothesis property
`test_review_is_accepted_iff_no_supplied_weight_exceeds_its_ceiling`) and
`tests/product/test_cp1_quality.py` (per-kind derivation checked against an independent
restatement over the raw rows, unavailable source, `test_unknown_register_kind_fails_closed`,
conflicting registers, and a CP-1 upgrade rejected end to end). Rewrite tournament on
`_lineage_basis`, `_ceilings` and the upgrade check: the incumbent held.

Not verified: that a kind-level ceiling is semantically right for every record (for
example historical values stated from source cap at Calculated, and Estimated or Proxy
calculations cap at Calculated rather than Assumption-Based); any live model output against
the ceilings.
