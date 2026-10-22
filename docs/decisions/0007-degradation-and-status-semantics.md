# 0007: Degradation and status semantics, with per-edge rules

Date: 21 October 2026. Status: adopted under plan v2 M4 (review C2, W1; decision 0005
MC-3 and MC-4). Coordinator ruling under decision 0006 DC-1; the user may override.

## Context

`registry.py` turned every selected optional producer into a hard requirement and
`execution.py` refused to start a consumer unless every requirement was accepted or
restricted, so one blocked module (CP-4 without an indenture, CP-3D without market data)
removed CP-3, CP-5 and CP-6 from the report. Any inherited limitation also forced
`restricted`, so Pass was unreachable downstream of any gap.

## Decision

1. **Edge rules.** Every dependency edge has a rule, `block` or `restricted`, encoded in
   `methodology.json` as `edge_rules: {"<producer>": "block" | "restricted"}` on the consumer.
   Default: a `required` producer is `block`; an `optional` producer is `restricted`.
   Explicit overrides from the pinned r14 texts (`bd71346`):

   | Consumer | Producer | Listed as | Rule | r14 evidence |
   | --- | --- | --- | --- | --- |
   | CP-2 | CP-1A | required | restricted | CP-2 "Optional upstream, used when present: CP-1A"; adaptation record "explicitly limit the CP-2 result" |
   | CP-4 | CP-1 | required | restricted | CP-4 system reference: "CP-1 unavailable → formulas extracted but headroom/capacity not calculable" |
   | CP-8 | CP-6 | optional | block | CP-8: "No decision record available to attribute. STOP" |
   | CP-MEMO | CP-6 | required | restricted | CP-MEMO: blocked upstream artifacts "are exclusions only" |

   CP-5's fan-in over every selected analyst is `restricted`: CP-5 always runs over the
   selected set and reports blocked analysts as findings. CP-6 keeps `block` on CP-3 and
   CP-5 (CP-6 "runs only after CP-5's handoff is accepted (Passed or Restricted)").
2. **A blocked producer under a `restricted` edge** reaches its consumer as an input
   carrying `status: "blocked"` and the producer's hash. The consumer's attempt binds that
   input exactly, runs, and carries the inherited limitation
   `"Upstream <producer> blocked: <producer limitation>"`. Under a `block` edge the
   consumer is not runnable ("Required upstream is unrun, stale or blocked").
3. **Unrun, stale and rejected producers** block every consumer regardless of rule: only a
   settled `blocked` head degrades.
4. **Own status versus inherited limitations.** `Module.limitations` holds the module's own
   findings; `Module.inherited_limitations` holds limitations carried from inputs,
   de-duplicated by text. `own_status` derives from own findings only. The settled status
   is `restricted` when the module has own limitations, when any bound input is `blocked`
   or any module up the input chain is `blocked` (a material inherited gap, read from the
   structured input statuses of the bound heads, never from limitation text), or when the
   run is synthetic; otherwise `accepted`. Other inherited limitations, including those
   from `restricted` inputs, are displayed and do not downgrade. Display is transitive
   (a consumer carries the own and inherited lists of its restricted inputs); only blocked
   ancestors downgrade. (Transitive rule: coordinator ruling, M4 fix round 1.)
5. **QA.** `cp1_quality` derives `module_status` from `own_status`
   (`blocked → blocked`, own-restricted → `restricted`, else `complete`).
6. Schema: `Module` becomes `module/4` (`Input.status` and `inherited_limitations` added).
   Older stores are rejected, per current policy. `execution/4` is unchanged; M5 bumps it.

## Recorded, not adopted

- r14 lists upstreams for CP-MODEL (CP-1, CP-1A, CP-1B, CP-2, CP-2A required; CP-2G
  optional) that `methodology.json` omits. M6 task 6.1 (decision 0006 DC-5) resolved it: the
  CP-MODEL artifact is the HTML Model destination plus the calculation JSON of the accepted
  CP-1 financial model, so its one upstream edge is `CP-1 -> CP-MODEL` (required, rule
  `block`); CP-0 is reached through CP-1, and the other r14 upstreams stay unencoded while the
  r14 workbook export is deferred.
- CP-L10 and CP-DR (standalone mode) need no CP-0 per their texts; both are outside the
  core scope and keep `block` until their milestones.
- Twelve optional edges have no missing-input text in r14 and take the default
  `restricted` as a proposal (see the M4.1 research report in the brief's evidence).

Not verified: r14 shared files (`CANON_SHARED.md`, canon SEC5, D1 status map) were not
read; LITE_CREDIT_22 behaviour; runtime behaviour on a real pack.
