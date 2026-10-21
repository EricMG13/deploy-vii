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
