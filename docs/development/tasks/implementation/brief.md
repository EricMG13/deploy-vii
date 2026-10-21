# Deploy VII implementation

Task: `dvii-implementation-001`. Owner: `01a15bb5-b5bc-7151-94b3-4edbae9d7815`.
Workspace: `/Users/ericguei/Documents/DEPLOY VII`.
Starting branch: `codex/development-environment`; clean HEAD: `3715b3c`.
Authorization: user's pasted request, 21 October 2026, attachment
`c9350fcb-2166-4c25-8ef2-94a8eec4c8c8/Pasted text.txt`.

## Goal and fixed decisions

Implement development tooling and milestones A–H: one Copilot CLI skill, Python
helpers and an offline Direction C Workbench. Preserve r14's 25 physical packages
and 41 logical entries from Deploy VI commit
`bd71346301b373afa72655916a4c1b42bf4c9823`. Review selective reuse; import no old
project policies, hooks, agent profiles, approvals or completion claims.
Python owns arithmetic; models own evidence-grounded analysis. Start sequentially
with versioned immutable run/source/module/calculation/view contracts, explicit
dependencies, invalidation and at most one targeted repair.

## Constraints and acceptance

- Keep development context tooling separate from the product. Preserve native
  compaction; no automatic reset, process-stop or ownership-transfer claims.
- CP-1A precedes core synthesis; CP-3 requires CP-2; CP-5 precedes CP-6.
  Final integrity validation does not make CP-5 consume CP-6.
- Every completed module test: labelled preview, artifact/field parity, browser
  evidence, cumulative accepted report. Test 1440×900, 1280×800, zoom, keyboard,
  long content, provenance, chart/table parity and offline behavior.
- Frozen public Caesars case; explicitly synthetic market/portfolio/adversarial
  cases. Raw sources/telemetry/credentials stay ignored and local.
- First core OpenRouter qualification batch: US$50 total, including failures and
  repairs. Uniform eligible Luna/GLM 5.3 Flash/latest suitable DeepSeek selection;
  pin batch routes, high or justified supported xhigh. No credit replenishment.
- On exhausted OpenRouter credit, check actual native Luna availability; otherwise
  requested GLM/DeepSeek only. Preserve separate host cohorts and unknown metrics.
- Confidence review after code; per the user's latest correction, limit post-edit
  rewrite tournaments to key areas (artifact state, provenance, financial
  calculations, execution ordering). Routine UI, CLI and adapter work uses focused
  tests and confidence review. Bounded maintenance after accepted layers.
- Track implementation, analytical qualification, rendering acceptance and native
  host qualification independently. No schema/browser pass implies financial fidelity.

## Execution plan

Implementation is inline; discovery/rewrite review may delegate within skill scope.
User correction: use the development model matrix. Initial discovery workers
inherited the coordinator route before this correction. Subsequent state/provenance
rewrite roles explicitly request GPT-6.1 Sol/high in fresh contexts. Research
defaults to GPT-6.1 Sol/medium; normal implementation to medium; mechanical work
to low; architecture escalation to GPT-6 Astra/high only on an evidenced blocker.
No successor assigned. Current coordinator model and global host settings stay as is.

- [x] Inspect clean Git, project instructions, context, settings, architecture,
  methodology, reuse, frontend, telemetry and maintenance documents; run setup.
- [x] Development tooling: `devtools/{storage,state,telemetry,workflow}.py` and
  `tests/devtools/`. CLI: init/checkpoint/handoff/validate/import-events/report.
  Test real scratch Git drift, pause/budget, unresolved operations, correction
  sources, review/routing preservation, unknown occupancy and replayed forks.
- [x] A: map pinned r14 packages/aliases and adapt reviewed Direction C shell,
  with no fixture verdicts. Establish contract and dependency tests.
- [ ] B: PDF/text/XLSX preparation and CP-0, hash/locator/missing/unreadable tests.
- [ ] C: canonical registers, reviewed deterministic Model, CP-1A, regressions
  for periods/units/conflicts/overrides/fallbacks and field parity.
- [ ] D: CP-2, CP-4, CP-3, CP-5, CP-6 and final integrity in dependency order.
- [ ] E: CP-1B/1C/1D/aliases, CP-2A/2D/2E.
- [ ] F: CP-2G/2H, CP-3C/3D, CP-4C.
- [ ] G: CP-DR, CP-L10/aliases, Portfolio Fit, CP-8, CP-MEMO/CP-OS.
- [ ] H: one packaged skill; real native installation/invocation/interruption/
  resume/report-delivery acceptance. Keep external qualification blockers visible.

For each code increment: write behavioral tests, run the focused tests, implement,
run strict typing/lint and required reviews, rerun affected checks, inspect full
diff. Run `make check`, `make secrets` before publication and `make audit` on
dependency changes. Keep development tests separate from product tests.

## Implementation design

Development records use explicit JSON input and local ignored content-addressed
snapshots. Checkpoints retain the complete submitted context plus Git and explicit
input fingerprints. Atomic writes and a short local file lock serialize record
updates only; they are not workspace ownership locks. Validation compares current
sources and tree, and reports preflight findings without controlling the host.
Telemetry imports only explicitly named files; raw bytes remain local, while
summary fields are numeric/allowlisted and IDs hashed. Cumulative and request
usage are separate series; occupancy is unknown without a qualified host signal.

Product contracts separate accepted analysis, deterministic calculations and view
binding. The renderer formats validated artifacts without inventing values.
Unrun/restricted/blocked/stale remain explicit. All model adapters share frozen
inputs/rubrics but retain distinct cohort identity and telemetry availability.

## Current evidence and next action

`make setup` and `make dev-check` passed (26 tests, strict typing, lint/format).
Development review evidence is in `tooling-review.md`. No product/live analytical
qualification yet; OpenRouter spend in this task: US$0. The pinned r14 coverage
map is in `docs/methodology/r14-coverage.json`; all product modules remain unrun.
Milestone A: see shell-review.md; 27 product tests pass. Next: source preparation,
CP-0 and immutable validation/promotion. User narrowed tournaments to key areas;
confidence review remains required for all code changes.
