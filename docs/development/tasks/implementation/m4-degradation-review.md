# M4 degradation and status semantics: result note

Date: 21 October 2026. Task `dvii-impl-m4-degradation` (plan v2 M4; review C2, W1;
MC-3, MC-4). Decision: [0007](../../../decisions/0007-degradation-and-status-semantics.md).

## What changed

- `methodology.json` and `registry.py`: per-edge rule (`block` or `restricted`) with
  `edge_rule(consumer, producer)`; four r14 overrides (CP-2/CP-1A, CP-4/CP-1 restricted;
  CP-8/CP-6 block; CP-MEMO/CP-6 restricted); CP-5's analyst fan-in is restricted.
- `contracts.py`: `Module` is `module/4` with `inherited_limitations`; `Input` gains
  `status` (default `accepted`, so non-module inputs are unchanged).
- `execution.py`: `current_inputs` binds a settled blocked head under a restricted edge;
  `candidate_issues` binds hash and status exactly; `settle` separates own from inherited
  limitations (transitively displayed, never repeating own findings) and restricts only
  for own findings, a blocked module anywhere up the input chain (`blocked_ancestors`,
  from structured input statuses, never limitation text; fix round 1) or a synthetic
  run; `view` shows own then inherited.
- `cp1_quality.py`: `module_status` derives from the narrative's own findings.

## Evidence

- C2 probe: CP-4 blocked, then CP-3, CP-5 and CP-6 run and settle `restricted` with
  "Upstream CP-4 blocked" (`test_blocked_optional_producer_does_not_halt_core_report`).
- W1 probe: on a public-case test fixture (not qualification) CP-1 with no own findings
  settles `accepted` beside CP-0's note (`test_pass_reachable_with_immaterial_inherited_gap`).
- Transitive: `test_blocked_ancestor_restricts_transitive_consumers` (CP-4 blocked, CP-6
  restricted) and a spoof test; forcing "not material" fails a non-synthetic test.
- `make product-check` and `make check` exit 0.

## Reviews

confidence-review run inline, no confirmed defect. rewrite-tournament run inline
(sub-agents are not allowed in this lane): one readability rewrite of `settle` adopted.

## Not verified

r14 shared files and LITE_CREDIT_22 behaviour; runtime behaviour on a real pack;
a blocked ancestor head replaced outside the journal (the journal stales consumers);
the CP-8 (block on CP-6), CP-MEMO (restricted on CP-6) and CP-MODEL edges: the encoded
rules are unit-tested in the registry but never exercised end to end through the journal
(CP-MODEL's r14 upstreams are still unencoded, decision 0007 "Recorded, not adopted").
M4 follow-up (M5 pre-step): the blocked-ancestor walk now tracks visited modules, so a
diamond is traversed once and a corrupted cyclic store cannot hang it.
