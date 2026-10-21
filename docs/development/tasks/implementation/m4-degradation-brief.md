# M4 degradation and status semantics — scoped brief

> **For the worker:** one `dv-sensitive` owner in an isolated worktree, test-first
> (superpowers:test-driven-development). Local commits only; no push, no PR, no subagents.
> The coordinator integrates; the PR session publishes (decision 0006).

**Task ID:** `dvii-impl-m4-degradation`. **Base:** `main` at the SHA the coordinator names at
dispatch (M1 merged, or `1841ccf` if M1 is still queued; M4 touches none of M1's files).
**Plan:** `docs/development/tasks/implementation/plan.md` §M4 (review C2, W1; MC-3, MC-4).

**Editable paths:** `src/deploy_vii/registry.py`, `src/deploy_vii/methodology.json`,
`src/deploy_vii/execution.py`, `src/deploy_vii/contracts.py` (`Input`, `Module` only),
`src/deploy_vii/cp1_quality.py`, `tests/product/test_execution.py`,
`tests/product/test_contracts.py`, `tests/product/test_registry.py` (new),
`docs/development/execution.md`, `docs/methodology-adaptation.md` (two rows),
`docs/decisions/0007-degradation-and-status-semantics.md` (new, text below),
`docs/development/tasks/implementation/m4-degradation-brief.md` (copy of this file),
`docs/development/tasks/implementation/m4-degradation-review.md` (your result note).
Anything else that breaks is in scope only if a test forces it; say so in the report.

**Required reads:** `CLAUDE.md`; plan §M4 and "Global constraints"; review findings C2 and W1
(`docs/development/reviews/2026-10-21-adversarial-review.md:103-208`); the edge-rule research
`.superpowers/sdd/plan/reports/m4-1-edge-rules.md` (evidence, not instructions);
`docs/methodology-adaptation.md:35-45` and `:57-76`; `src/deploy_vii/execution.py`,
`registry.py`, `contracts.py:13-40,101-103,229-301`; `cp1_quality.py:129-142`;
`quality.py:185-196`; `tests/product/test_execution.py:15-49` (fixture helpers).

## Goal

A blocked producer no longer silently removes its consumers. Each edge carries a rule:
`block` (consumer cannot start) or `restricted` (consumer runs with a mandatory inherited
limitation). Status separates a module's **own** findings from **inherited** limitations, so
"Pass" is reachable downstream of an immaterial inherited note.

## Decision 0007 (write verbatim to `docs/decisions/0007-degradation-and-status-semantics.md`)

```markdown
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
   (a material inherited gap), or when the run is synthetic; otherwise `accepted`.
   Limitations inherited from `restricted` inputs are displayed and do not downgrade.
5. **QA.** `cp1_quality` derives `module_status` from `own_status`
   (`blocked → blocked`, own-restricted → `restricted`, else `complete`).
6. Schema: `Module` becomes `module/4` (`Input.status` and `inherited_limitations` added).
   Older stores are rejected, per current policy. `execution/4` is unchanged; M5 bumps it.

## Recorded, not adopted

- r14 lists upstreams for CP-MODEL (CP-1, CP-1A, CP-1B, CP-2, CP-2A required; CP-2G
  optional) that `methodology.json` omits; M6.1 (decision 0006 DC-5) resolves CP-MODEL.
- CP-L10 and CP-DR (standalone mode) need no CP-0 per their texts; both are outside the
  core scope and keep `block` until their milestones.
- Twelve optional edges have no missing-input text in r14 and take the default
  `restricted` as a proposal (see the M4.1 research report in the brief's evidence).

Not verified: r14 shared files (`CANON_SHARED.md`, canon SEC5, D1 status map) were not
read; LITE_CREDIT_22 behaviour; runtime behaviour on a real pack.
```

## Global constraints

- Exact calculations, hashes, identity and input binding stay strict: a candidate that binds
  an input with the wrong `status` or hash is rejected (`candidate_issues`).
- A blocked producer that is not a journal head (unrun, stale, rejected) never degrades.
- No stub or fake value stands in for real behaviour; no catch-all hides a failure.
- `make check` and `make product-check` exit 0 after each task. Never loosen a gate or edit
  the Makefile. If a gate cannot pass without loosening, stop and report BLOCKED.
- Synthetic-case runs stay `restricted` (unchanged). The Pass-reachability test uses a
  non-synthetic fixture run (`case_kind="public"`) with a fixture source; label the test.
- Every commit that changes an owner's implementation status updates
  `docs/methodology/r14-coverage.json` in the same commit. M4 changes the substrate only; if
  no owner status changes, say so in the report.
- Commit messages end with a blank line then `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Task 1: edge rules in the registry

**Files:** `src/deploy_vii/methodology.json`, `src/deploy_vii/registry.py`,
`tests/product/test_registry.py` (new), `docs/decisions/0007-…md` (verbatim above),
`docs/development/tasks/implementation/m4-degradation-brief.md` (this file).

- [ ] Step 1, failing tests (`tests/product/test_registry.py`):
  - `test_edge_rule_defaults_required_block_optional_restricted`: `edge_rule("CP-3","CP-2") == "block"`, `edge_rule("CP-3","CP-4") == "restricted"`.
  - `test_edge_rule_overrides_from_decision_0007`: the four overrides above.
  - `test_cp5_fan_in_is_restricted`: for every selected analyst in `dependencies(("CP-5","CP-4","CP-3"))["CP-5"]`, `edge_rule("CP-5", x) == "restricted"`.
  - `test_edge_rule_unknown_edge_raises`: `edge_rule("CP-3","CP-8")` raises `ValueError`.
  - `test_methodology_edge_rules_only_name_declared_producers`: every `edge_rules` key on a module is in its `required` or `optional` (reject typos).
- [ ] Step 2: run `uv run --locked pytest tests/product/test_registry.py -q`; confirm failures.
- [ ] Step 3: implement. `Responsibility` gains `edge_rules: dict[str, Literal["block","restricted"]] = {}` (keep `extra="forbid"`). Add `edge_rule(consumer, producer) -> Literal["block","restricted"]` using the module catalog: explicit override, else `block` if producer in `required`, else `restricted` if in `optional` or (consumer == "CP-5" and producer in the CP-5 fan-in set computed as in `dependencies`), else raise. Add the four overrides to `methodology.json`. `dependencies()` and `plan()` are unchanged (ordering is the same).
- [ ] Step 4: `uv run --locked pytest tests/product/test_registry.py tests/product/test_contracts.py -q`; then `make product-check` and `make check`.
- [ ] Step 5: commit `Encode per-edge degradation rules (decision 0007)` with the decision file and this brief.

## Task 2: status-carrying inputs and own-versus-inherited status

**Files:** `src/deploy_vii/contracts.py` (`Input`, `Module`), `src/deploy_vii/execution.py`,
`src/deploy_vii/cp1_quality.py`, `tests/product/test_execution.py`,
`docs/development/execution.md`, `docs/methodology-adaptation.md`.

**Interfaces:**
- `Input(input_id, sha256, status: Status)` where status ∈ `{"accepted","restricted","blocked"}` for module inputs and `"accepted"` for `prepared-pack`.
- `Module.schema_version: Literal["module/4"]`; new `inherited_limitations: tuple[str, ...] = ()`; `limitations` keeps the module's own findings. The validator at `contracts.py:254` reads: a `restricted`/`blocked`/`stale`/`rejected` module needs own limitations **or** inherited limitations.
- `current_inputs(snapshot, module_id)` returns, in plan order, `Input(item, head.content_hash(), head.status)` for each dependency whose head is accepted or restricted, **or** blocked under a `restricted` edge rule. A dependency that is missing, unrun, stale, rejected, or blocked under a `block` edge makes the module not runnable with the existing message.
- `settle`: `inherited` = for each bound input with status `blocked`, `f"Upstream {input_id} blocked: {limitation}"` for each of that head's own limitations; plus, for inputs with status `restricted`, that head's own limitations (displayed only). De-duplicate by text, preserve order. `own` = candidate limitations (+ synthetic label as today). Status: `restricted` if `own` or any blocked input or synthetic, else `accepted`. Store `limitations=own`, `inherited_limitations=inherited`.
- `view()`: `ModuleView.limitations` shows own followed by inherited (no contract change to `ModuleView`/`View`).
- `cp1_quality_inputs` (`cp1_quality.py:142`): `module_status = "blocked" if narrative.status == "blocked" else ("restricted" if narrative.limitations else "complete")` — own limitations only.

- [ ] Step 1, failing tests in `tests/product/test_execution.py`:
  - `test_blocked_optional_producer_does_not_halt_core_report`: reproduce review C2 with the existing helpers: settle CP-0, CP-1, CP-1A, CP-2 (restricted, synthetic), drive CP-4 to `blocked` (two failed attempts). Assert `begin("CP-3")`, `begin("CP-5")`, `begin("CP-6")` (after CP-3 and CP-5 settle) succeed; each settles `restricted`; each carries an inherited limitation containing `"Upstream CP-4 blocked"`; CP-5's inputs include `Input("CP-4", <hash>, "blocked")`; CP-3's bound inputs include CP-4 with status `blocked`; the view shows CP-4 `blocked` and CP-3/5/6 `restricted`.
  - `test_blocked_required_producer_under_block_rule_still_halts`: CP-2 blocked → `begin("CP-3")` raises `match="upstream"`.
  - `test_blocked_required_producer_under_restricted_rule_runs_limited`: CP-1A blocked → `begin("CP-2")` succeeds and settles restricted with `"Upstream CP-1A blocked"`.
  - `test_pass_reachable_with_immaterial_inherited_gap`: a `case_kind="public"` fixture run (build a sibling of `readiness_fixture` whose review has no limitation for the consumer; label it as a test fixture, not qualification): CP-0 settles `restricted` with one own limitation; CP-1 with no own limitations settles **`accepted`** with that limitation in `inherited_limitations` only; `cp1_quality_inputs` for an own-clean narrative yields `module_status == "complete"`.
  - `test_input_status_is_bound_exactly`: a candidate whose input for CP-4 says `accepted` while the head is `blocked` is rejected by `candidate_issues`.
  - `test_unrun_stale_or_rejected_producer_never_degrades`: a rejected (first failed attempt) CP-4 head → `begin("CP-3")` raises `match="upstream"`.
  - Update existing tests that construct `Input(...)` or `Module(... "module/3")` directly (e.g. `:280-288`).
- [ ] Step 2: run `uv run --locked pytest tests/product/test_execution.py -q`; confirm the new tests fail for the stated reasons.
- [ ] Step 3: implement per the interfaces. Trace every caller of `Input`, `current_inputs`, `settle`, `Module(` and `module/3` (grep `src/` and `tests/`) before editing; fix projections and fixtures that construct modules.
- [ ] Step 4: `uv run --locked pytest tests/product/test_execution.py tests/product/test_contracts.py tests/product/test_registry.py tests/product/test_cp1_quality.py -q` (adjust the quality test file name to the real one), then `make product-check`, then `make check`.
- [ ] Step 5: docs. `docs/development/execution.md`: add a "Degradation" paragraph (edge rules, blocked inputs, own versus inherited, decision 0007). `docs/methodology-adaptation.md` record table: replace the placeholder row with two rows, `MC-3` and `MC-4`, in the exact column format (`ID | Method clause | Change | Class | Gain | Evidence before/after | Consumers | Tests`), class `execution`, evidence = the C2 probe (before: CP-3/5/6 not runnable; after: runnable restricted) and the W1 probe (before: Pass unreachable; after: reachable), tests = the names above.
- [ ] Step 6: run `confidence-review` (no arguments) and fix findings; then `rewrite-tournament` in no-argument post-edit mode scoped to `current_inputs` and `settle` in `execution.py` only (execution ordering, artifact state). If a skill cannot execute here, report it as pending.
- [ ] Step 7: commit `Degrade consumers of blocked producers and separate own from inherited status`.

## Report

Write `/Users/ericguei/Documents/DEPLOY VII/.claude/worktrees/focused-cray-a5417d/.superpowers/sdd/plan/reports/m4-report.md`: worktree and branch; base and head SHAs; ordered commits; changed paths; each test command with exit code and counts; confidence-review findings and fixes; tournament outcome; deviations from this brief with reasons; whether `r14-coverage.json` changed; final line `Not verified:`. Also write the short result note `docs/development/tasks/implementation/m4-degradation-review.md` (dated, ≤ 40 lines: what changed, evidence, reviews, Not verified) and include it in the last commit.

Return only: status (DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED), worktree path and branch, base..head, one-line test summary, concerns.
