# Deploy VII implementation

Task: `dvii-implementation-001`. Owner: `01a15bb5-b5bc-7151-94b3-4edbae9d7815`.
Workspace: `/Users/ericguei/Documents/DEPLOY VII`.
Starting branch: `codex/development-environment`; clean HEAD: `3715b3c`.
Since 21 October 2026: Claude Code coordinates and work branches from `main`
([decision 0003](../../../decisions/0003-claude-coordinated-environment.md)).
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
  evidence, cumulative accepted report. Parity is checked against the module's bound
  design-system Front Page blocks (decision 0004). Test 1440×900, 1280×800, zoom, keyboard,
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

Since 21 October 2026 implementation runs through the `dv-*` workers; the coordinator
plans, integrates and publishes (decision 0003). Milestones, acceptance and sequencing
now live in [plan.md](plan.md); this brief is the progress log.
User correction: use the development model matrix. Initial discovery workers
inherited the coordinator route before this correction. Until 21 October 2026,
state/provenance rewrite roles ran on GPT-6.1 Sol/high (Codex). Since then the routes
are the `dv-*` agents in ../../../model-matrix.md: tournament roles on Sonnet 5.5/high,
research on Sonnet 5.5/medium, mechanical work on low, and escalation or architecture
on Fable 5.1/high only after two failed repairs or an evidenced blocker.

Original milestone checklist, superseded by [plan.md](plan.md) on 21 October 2026 and
kept as history. A and B record implementation only: their adopted completion
conditions are unmet (A is reopened as plan M3; B closes in M7).

- [x] Inspect clean Git, project instructions, context, settings, architecture,
  methodology, reuse, frontend, telemetry and maintenance documents; run setup.
- [x] Development tooling: `devtools/{storage,state,telemetry,workflow}.py` and
  `tests/devtools/`. CLI: init/checkpoint/handoff/validate/import-events/report.
  Test real scratch Git drift, pause/budget, unresolved operations, correction
  sources, review/routing preservation, unknown occupancy and replayed forks.
- [x] A: map pinned r14 packages/aliases and adapt reviewed Direction C shell,
  with no fixture verdicts. Establish contract and dependency tests.
- [x] B implementation: PDF/text/XLSX preparation and CP-0 review/assembly,
  hash/locator/missing/unreadable tests. Live analytical qualification pending.
- [x] Execution substrate: immutable snapshots, current lineage, one targeted repair,
  stale propagation and cumulative views. Internal API; live adapters still pending.
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
map is in `docs/methodology/r14-coverage.json`; live analytical qualification
remains unrun for every product module.
Milestones A/B implementation: see shell-review.md and preparation-review.md.
900 product tests pass (reported 97.44% branch-inclusive coverage), followed by
10 focused checks for the final narrative trace dimensions; CP-0 synthetic output is
restricted, other modules unrun. The selected internal Model kernel and 219
synthetic regressions are ported; see model-port-review.md and
../../model-reuse.md. The validated CP-1 input boundary and kernel adapter now exist; see
financial-input-review.md and ../../financial-inputs.md. Full Module delivery, artifact binding and CP-1A remain pending; the later
increments below add independent reconciliation and consumer input readiness. Independent
source-register comparisons now exist; see reconciliation-review.md and
../../financial-reconciliation.md. Full source statements and independent equations
now exist; see statement-review.md and ../../statements.md. CFO can reconcile from original source components; no
final readiness or analytical claim is made. Hash-bound historical series and
constructed-period operands now exist; see period-review.md and
../../financial-periods.md. Three reproduced period/span defects are corrected.
The tournament covered only the two changed date algorithms, using fresh
GPT-6.1 Sol/high review roles; confidence review covered the complete increment.
Historical Model statement values and ratio numerators/denominators now exist;
see model-output-review.md and ../../model-output.md. Rolling statements use
verified full-year dates; gaps/overlaps cannot become known LTM flows. The two
key span/provenance functions received the scoped tournament with the same
explicit model matrix. Evidence tiers and analytical trends remain unassessed.
Historical statements now retain content-addressed arithmetic graphs, including
missing source observations; schema `financial-model/2` links every statement
value to its computation root. EBIT/net-income margins and reported EBITDA growth
are added. See computation-review.md. Only `trace_cells` received this increment's
scoped tournament (Sol/high review roles); the incumbent held. Confidence review
covered all changes.

Constructed-period reconciliation now compares historical account inputs and
independent source CFO equations, retains separately stated LTM/FY comparisons,
and labels shared-source FY agreement as construction-only WARN. See
period-reconciliation-review.md and ../../period-reconciliation.md. The two key
comparison/traversal functions received a scoped Sol/high tournament; the static
winner failed typing and the verified incumbent was retained. Remaining readiness
and delivery work is not promoted by these synthetic checks.

Historical CP-MODEL readiness now binds explicit quarter scope, complete input
coverage and mandatory source/period reconciliations into one recomputable row.
A reproduced short-year false-ready case and a fiscal-sequence gap were fixed.
See model-readiness-review.md and ../../model-readiness.md. Only `_evaluate`
received the scoped Sol/high tournament; verified Snippet A won. This does not
qualify forecasts, pro forma, other consumers or a delivered Module.

Pending user clarification: the pinned references name DCF without a formula.
The question offered explicitly source-defined only, FCF less dividends, or FCF
less dividends and buybacks. No answer has arrived; no default is adopted.
Continue independent work while that definition remains unresolved.

The canonical CP-1 KPI API now retains its own debt basis, explicit reported and
adjusted earnings, signed ratio legs, growth and arithmetic provenance. A rolling
source-selection regression is fixed: reported and derived quarters are selected
before summing. See canonical-kpis-review.md and ../../canonical-kpis.md. The
scoped Sol/high tournament covers only `_canonical_frame` and `_rolling_frame`.
DCF, DCF/debt and FFO interest coverage remain explicit unavailable rows.
The additional FFO coverage question offered (FFO + cash interest paid) / cash
interest paid, FFO / cash interest paid, or source-defined only. The user answered
in the Codex chat: (FFO + cash interest paid) / cash interest paid. It is recorded
here, not yet implemented; the row stays unavailable until a scoped change applies it
with tests. DCF remains unanswered. These definitions do not block independent work.

Sourced annual audit-basis differences now have an explicit representation bound
to one metric, audited FY, four independent unaudited quarters and the compared
observation hashes. Both reconciliation APIs retain numeric differences while
permitting eligible WARNs; unrelated/missing/conflicting/stale evidence cannot be
waived. Input and affected reconciliation schemas advance to /2. See
audit-basis-review.md and ../../audit-basis.md. The Sol/high tournament is limited
to the two financial eligibility functions; report assembly receives confidence
review and focused tests. Historical readiness consumes the warning without
relaxing its other conditions. This remains deterministic synthetic evidence.

Source-backed cash movement bridges now reference explicitly assessed FX/perimeter
source detail, retain original values/signs/citations and require complete passing
source assessments before constructed periods can combine adjustments. Missing
assessments and equal source errors cannot cancel into a pass. Input and affected
reconciliation schemas advance to /3. See cash-movement-review.md and
../../cash-movement.md. The tournament covered only validation and constructed
cash assembly (fresh Sol/high roles); 149 focused tests and 1,144 coordinator
comparisons verify the selected rewrite. All code received confidence review.
No new Module or live analytical/rendering/native-host qualification is claimed.

Independent NCF reconciliation now requires operating/investing/financing source
totals, explicit FX inclusion and passing intermediate equations. Equal subtotal
or source-period errors cannot cancel into a pass. It is mandatory for selected
historical Model quarters. Source/period report versions advance to /4 and
readiness to /2; financial-review/3 remains unchanged. See
net-cash-flow-review.md and ../../net-cash-flow.md. The Sol/high tournament covered
only the two financial checking functions; 165 focused tests and 378 coordinator
comparisons verified the chosen rewrite. Full product checks pass. This remains
synthetic implementation evidence, with no new Module or live qualification.

CP-1 source audit registers now retain original observation positions, sign-change
evidence, scoped definition assessments, unresolved alternatives, automatic debt
carrying/principal differences and multi-figure event roles. A source-stage gap
ledger retains periods and evidence, with unassessed definitions explicit. No
assessment can replace numeric values or waive checks. See canonical-audit-review.md
and ../../canonical-audit.md. Confidence review fixed sign/gap evidence omissions;
the two-function Sol/high tournament retained exact diagnostics/provenance across
960 validation cases and 2,252 definition rows. No Module acceptance is promoted.

CP-1 source/entity context now records explicit evidence tiers, reporting scope,
entity roles and dated subsequent events, preserving unknowns and scope differences.
Financial extraction binds every cited period/observation alternative to its
explicit entity/date/basis, with pro-forma evidence linked separately to events.
Confidence review fixed a nested-input traversal crash and an unlinked pro-forma
false pass. See source-context-review.md and ../../source-context.md. The tournament
covers only the two provenance validators using the explicit Sol/high review
matrix; routine assembly uses focused tests and confidence review. Source-first
execution ordering, CP-1/Model delivery and analytical acceptance remain pending.

The cumulative CP-1 gap API now combines every implemented source context/audit
warning with missing adapter/calculated values, operand scopes, non-PASS period
checks, unassessed KPI evidence and artifact limitations. Invalid bindings stay
BLOCK rows; incomplete add-back disclosure retains source gaps without inventing
calculations. Confidence review fixed missing operand scopes and a context
entity/scope ID collision; source-context output advances to /2 with explicit
scope IDs. A further method check fixes false gaps for r14's optional facility-term
nulls while preserving conflicts and unknown amortisation (`canonical-audit/2`).
See canonical-gaps-review.md and ../../canonical-gaps.md. The Sol/high
tournament covers only the two aggregation/provenance functions. This register
confers no consumer readiness or Module acceptance.

The CP-1 narrative protocol now binds evidence-risk-credit chains to immutable
prior-row catalogues, requires explicit dimensional coverage and named event,
multi-figure and material funding stories, and retains every upstream gap.
No available numeric KPI limits synthesis to data quality. Confidence review
fixed empty reasoning chains and false funding designations of standard BS rows.
See narrative-review.md and ../../narrative.md. The Sol/high tournament covers
only catalogue construction and narrative validation. Semantic qualification,
canonical Markdown and Workbench delivery remain pending; this is internal
protocol implementation, not a completed Module or analytical acceptance.

CP-1 downstream readiness now preserves each requested logical consumer and
its Step 12 dependencies, scopes every inherited gap, and derives statuses from
explicit evidence-bound assessments. The CP-MODEL row is always present and
retains its separate historical input/reconciliation gate. Source-integrity
blocks cannot be excluded. Confidence review fixed null-only limited support,
false complete-dashboard sufficiency and nested-book access before validation.
See downstream-readiness-review.md and ../../downstream-readiness.md. Only review
validation and status derivation receive the Sol/high tournament. Analytical
sufficiency judgments, delivery and qualification remain separate and unrun.

Cross-statement balance movements now compare exact opening/closing BS equity
with source IS net income and explicit signed source adjustments, plus declared
other BS bridges. Incomplete evidence and differences remain gaps and block
selected historical Model readiness, including derived-quarter source operands.
See balance-movements-review.md and ../../balance-movements.md. Confidence review
fixed unstable movement roles and unbounded cross-bridge term expansion. Only the
bridge validator and arithmetic assembler receive the scoped Sol/high tournament.
No analytical, rendering or native-host acceptance is implied.

Initial public Caesars FY2025 filing is locally hash-pinned; full core pack and
live qualification remain pending. Source-bound facility FX normalization now
preserves originals and exact-date quotes through the Model, reconciliation, audit
and gap APIs. Missing/conflicting conversions keep aggregates unknown. Confidence
review fixed period identity and gap-provenance omissions; only the validator and
normalizer received the Sol/high tournament. See facility-fx-review.md and
../../facility-fx.md. No analytical, rendering or native-host acceptance is implied.
Next: bind CP-1/Model outputs to the execution
journal, canonical Markdown and Workbench. CP-1A remains an explicit requirement;
current internal readiness decisions are not full CP-1 acceptance.
Tournaments remain key-area only; confidence review applies to all code changes.

Execution review: execution-review.md. Native/live qualification remains unrun.

Source-first CP-1 journal submission now retains source context, bound financial
extraction, Python calculations, narrative and downstream readiness in fixed
order. The trusted CP-0 adapter and local execution CLI support interruption and
exact-response resumption with the same module-wide one-repair budget. Final CP-1
readiness remains a pending internal handoff, not Module promotion. See
staged-execution-review.md and ../../execution.md. The scoped Sol/high tournament
covers only journal transition and stage validation; routine adapters/CLI use
confidence review and focused tests. Canonical Markdown/Workbench projection,
CP-1A and live/native qualification remain pending. OpenRouter spend stays $0 of
the authorized $50 cap; no live call or provider route changed.

Typed report layouts now bind each declared HTML/Markdown cell to a canonical
Fact and reject omissions, duplicates and coordinate substitutions. The journal
CLI can render source-period T4.4–T4.6 as a labelled candidate, retaining original
and normalized values, units, dates, citations and file/snapshot hashes without
settling CP-1. Confidence review fixed machine-field escaping, placement of
scope/units and loss of not-applicable source status. The one Sol/high tournament targets only table provenance validation;
routine UI/CLI/adapters use focused checks. See report-tables-review.md and
../../report-tables.md. Derived statement periods, remaining CP-1 registers,
canonical envelope/QA and reader interoperability, Model presentation and final
promotion remain pending. This preview does not qualify a completed Module.
Formats advance explicitly to module/2, view/2 and execution/3; no automatic
migration or provider-budget reset. OpenRouter spend remains $0/$50.

Full statement-line period construction now appends Q/YTD/FY/LTM derived columns
to the candidate T4.4–T4.6 matrices, preserving source figures and independent
comparisons, missing operands, sign normalizations, closing balances and actual
arithmetic graphs. Incomplete Model add-back disclosure does not prevent statement
arithmetic. Confidence review corrected a shared-kernel nested subtotal plug,
post-validation caller-object access and a misleading source-only scope note.
The one key-area Sol/high tournament targets only `_component`; routine assembly
and UI use behavioral checks. See statement-history-review.md and
../../statement-history.md. Formats advance to statement-history/1,
statement-preview/2, module/3, view/3 and execution/4; old stores remain intact.
Other CP-1 registers, canonical envelope/QA/reader, complete Model presentation,
final promotion and CP-1A remain pending. OpenRouter spend remains $0/$50; no live
or native analytical acceptance is claimed. Existing Direction C navigation
exception retained; no CSS edit or new suppression.

Model interface T4.14–T4.19, dynamic source schedules and historical readiness now
join the source/constructed statements in a journal-bound candidate preview.
Canonical table transport decodes source text once and verifies exact table parity;
the complete envelope and typed downstream consumer remain pending. Confidence
review fixed fixed-coupon unit metadata, controlled NONE handling, copied-pack
validation, null-cell units and unreadable wide tables. Only the parser received
the scoped Sol/high tournament (30,037 differential cases); routine adapters and
UI received focused checks. See model-interface-review.md and
../../model-interface.md. Source audit advances to /4 with explicit old-schema
rejection; keep prior stores and spend history. 871 product tests passed, followed
by 72 focused checks for final UI/unit changes. Full CP-1/Model delivery, CP-1A,
subsequent modules and live/native qualification remain pending. OpenRouter spend
remains $0/$50. Existing Direction C navigation exception retained; table readability
was fixed without adding an ignore.

All 18 canonical register table IDs now project recomputed source/financial/context
results, statement construction, arithmetic traces, conflicts, gaps and readiness.
`register-preview` revalidates all four retained stages before writing a hashed,
snapshot-bound candidate. It preserves the pending ticket. Confidence review fixed
conflict figure/role omissions, false optional-note gaps, contradictory merged
readiness and opaque inspector labels. Only this new journal trust boundary had a
tournament, using the matrix's fresh Sol/high roles; the verified memory candidate
releases each temporary stage result without changing order or comparisons.
See canonical-tables-review.md and ../../canonical-tables.md. Synthetic browser
evidence covers exact fields, keyboard provenance, both viewports, zoom and offline
operation. Full narrative/envelope, numeric confidence/QA, definition/coverage
confirmation, large-pack transport qualification, final CP-1 promotion and CP-1A
remain pending, followed by D–H. No live calls; OpenRouter spend stays $0/$50.
The existing Direction C navigation exception remains; no CSS change or new ignore.

CP-1 narrative findings now render with separate Evidence, Risk mechanic and Credit
implication passages, issuer binding, compact prior-record references and exact
evidence trace. Supplemental tables expose all analytical dimensions, required
event/funding stories, declared funding scope and source-statement coverage.
No missing assessment becomes accepted. Statement trace inspectors retain source
units and dates; records lacking intrinsic dimensions explicitly require canonical
context. All narrative limitations are carried into the combined output.
See narrative-projection-review.md and ../../narrative-projection.md. This is a
presentation adapter over the validated narrative; confidence review and behavioral
checks apply, with no new tournament. Formats are canonical-tables/2 and
register-preview/2; journal/stage contracts remain unchanged. Full canonical
envelope, QA/numeric confidence, complete analytical review, final promotion and
CP-1A remain next, followed by D–H. No live calls or spend; $0/$50 remains.

CP-1 QA and numeric confidence now exist as hash-bound contracts (quality-inputs/1,
quality-review/1, confidence/1, quality-report/1, cp1-quality/1). Python computes the
r14 CP_CONFIDENCE_SCORE with exact fractions, caps and bands; producers own coverage slots,
source gate, module status and inherited findings, and analysts supply only materiality,
lineage and findings. The CP-1 projection counts the 18 required registers, their cells,
empty mandatory registers, narrative dimensions, stories, funding and findings, keeps
canonical-handoff absent, and can never reach Passed before handoff. An independent Decimal
restatement of the r14 text is property-tested against it; two deliberate adaptations (exact
ties-to-even rounding; source gate and module status mapped to Blocked/Restricted per D1)
are pinned. See quality-review.md and ../../quality.md. Confidence review applies. The
scoped Sonnet 5.5/high tournament on `_compute_confidence` kept the incumbent. The canonical
envelope/handoff, analytical review that supplies the judgments, final promotion and CP-1A
remain next, followed by D-H. No live calls; OpenRouter spend remains $0/$50.

Environment, 21 October 2026 (decision 0003): Claude Code coordinates from `main`,
CLAUDE.md is the only instruction file, and Codex routes are retired. The setup branch
was squash-merged into `main`. The next session resumes at the canonical envelope/handoff
for CP-1.

Plan v2, 21 October 2026: an adversarial review of `7526dbc`
(../../reviews/2026-10-21-adversarial-review.md) returned BLOCK on three findings:
- no model runner or live probe behind the CP-1 contracts;
- one blocked module halts CP-3, CP-5 and CP-6 (reproduced with the test fixtures);
- the frontend follows the superseded phase-1 reference.

On the user's instruction "Apply your recommendations and create the new development
plan", [plan.md](plan.md) replaces the milestone checklist and
[decision 0004](../../../decisions/0004-design-system-frontend.md) makes the user's
Direction C design system normative. The design-system file is snapshotted under
`design/reference/`. The canonical envelope moves to M6, after the runner probe (M2),
the design re-baseline (M3) and the degradation semantics (M4). Next:
M1, FFO interest coverage (brief since renamed [m1-kpi-definitions-brief.md](m1-kpi-definitions-brief.md)).

The same day the user added: "Your also authorised to alter the methodology to improve
performance and reliability. Include regular internal and external testing of modules
(with open router and stated model choice from my codex chats)."
[Decision 0005](../../../decisions/0005-methodology-changes-and-regular-testing.md)
records this:
- guardrailed methodology changes MC-1 to MC-10;
- testing tiers I1–I3 (internal) and E1–E3 (external, with the Luna/GLM/DeepSeek pool);
- recurring external caps, proposed and awaiting confirmation.

CLAUDE.md now references decisions 0004 and 0005. No product code changed. 978 product
tests pass locally. OpenRouter spend: $0/$50.

Later on 21 October 2026 the user wrote: "Main orchestration session will be set by me
using fable. But all PR work to be handled by a sub-session. … Apply your
recommendations (but keep a record of your choices)", named the OpenRouter key file
("if no credit use agent as proxy") and asked to merge this work.
[Decision 0006](../../../decisions/0006-delegated-choices-and-orchestration.md) records
each choice (DC-1 to DC-10): a Fable orchestrator, a PR session that squash-merges after
local gates and reviews, DCF = FCF − dividends paid (M1, brief renamed
[m1-kpi-definitions-brief.md](m1-kpi-definitions-brief.md)), the HTML Model destination
for CP-MODEL, recurring caps under a US$200 ceiling, runtime-only key handling, and a
labelled Claude-agent proxy cohort without credit. Plan decisions are renumbered
(degradation 0007, contract shape 0008). The project now denies `Read` on the key file;
its contents were not read. No product code changed. OpenRouter spend: $0/$50.

M1, 21 October 2026 (`dvii-impl-m1-kpi-definitions`, `dv-sensitive`, base `1841ccf`, head
`e272b6d`): FFO interest coverage = (FFO + cash interest paid) / cash interest paid (user
answer) and DCF = FCF − dividends paid, DCF/debt = DCF / canonical total debt (decision 0006
DC-4) are computed as ratio recipes plus one derived scalar in `_canonical_frame`; the
`_UNDEFINED` rows and the false "definitions remain unresolved" limitation are gone, and no
KPI row is `unavailable`. Tests cover the zero/missing denominator, the sign-normalization
flip, missing dividends (Not Calculable, never FCF) and a sourced zero (DCF = FCF). Reviews:
worker confidence-review (one dead branch removed); the `_canonical_frame` tournament was
played inline (the worker may not spawn agents) and kept the incumbent; an independent task
review approved with minor notes (a one-missing-quarter TTM case is untested; recorded).
Coordinator reran `make product-check` (986 passed, 97.59% coverage), `make check` and
`make secrets`: all exit 0. `r14-coverage.json` unchanged (CP-1 stays `partial`). Not
verified: rendering of the new rows in Direction C fields (M3/M6), live or native
qualification, `make audit`. OpenRouter spend: $0/$50. Publication waits for the PR session.

M4, 21 October 2026 (`dvii-impl-m4-degradation`, `dv-sensitive`, base `1841ccf`, head
`bc9328c`): decision 0007 records per-edge degradation rules (`edge_rules` in
`methodology.json`; default required → block, optional → restricted; overrides CP-2←CP-1A,
CP-4←CP-1, CP-8←CP-6, CP-MEMO←CP-6 from the pinned r14 texts; CP-5 always runs over the
selected set). `Input` carries `status`; a blocked producer under a `restricted` edge reaches
its consumer as a blocked-status input; `Module` (`module/4`) separates own `limitations`
from `inherited_limitations`; status downgrades only for own findings, a blocked input or a
blocked ancestor (tracked structurally, not by text), or a synthetic case; `cp1_quality`
derives `module_status` from own status. The review C2 probe now leaves CP-3, CP-5 and CP-6
runnable and restricted when CP-4 is blocked, and Pass is reachable downstream of an
immaterial inherited note. MC-3 and MC-4 rows added. Reviews: inline confidence-review and
tournament (`settle` readability rewrite adopted); independent task review approved after one
fix round (transitive materiality). Coordinator reran `make product-check` (1001 passed,
97.61%) and `make check`: exit 0; `make secrets` failed only on the M3 lane's design
sample-data file in the all-branches history scan (being removed from that lane). Not
verified: r14 shared files, LITE_CREDIT_22, a real pack, the CP-8/CP-MEMO/CP-MODEL edges.
`r14-coverage.json` unchanged. OpenRouter spend: $0/$50.

M5, 21 October 2026 (`dvii-impl-m5-journal-storage`, `dv-sensitive`, base `0e56757` (M4 lane head), head `b735e83` plus the coordinator measurement `bfbc955`; merged as PR #6 `4705995` after a rebase onto main): schema `execution/5` stores the prepared pack and every attempt payload once as content-addressed blobs (`blobs/<sha256>`); snapshots reference them by hash, `parent` and `content_hash()` cover only the small snapshot, and `Execution.pack()`/`payload()` verify blobs on read (missing, mismatching or non-canonical blobs raise). Writes are temp → fsync → rename, idempotent for identical bytes and refusing a different file at an existing hash path; `read()` rejects `execution/1`–`/4` with a message naming the version and the remedy. The `Input("prepared-pack", …)` hash is unchanged (canonical `PreparedPack` JSON). Measurement on the hash-pinned Caesars pack (before `0e56757` → after `b735e83`): first `begin` 884,862 → 911 B; last `begin` 1,068,735 → 10,594 B; last `finish` 2,139,207 → 22,415 B; journal directory 46.9 MB → 3.87 MB; wall 8–17 ms → 1–6 ms per transition. Reviews: task review approved after three fix rounds; confidence review and the artifact-state tournaments on `_write`/`read` are recorded in `m5-journal-storage-review.md`. Gates on the merged head: `make product-check` (1029 passed, 97.52%), `make check`, `make secrets` all exit 0; hosted CI green. Not verified: Linux; a blob store under concurrent writers beyond the two-writer tests; `make audit`. OpenRouter spend: $0.

M3, 21 October 2026 (`dvii-impl-m3-design` Tasks A–E, `dv-feature`, base `1841ccf`, lane head `4425464`, squash-rebased onto `4705995` as this commit): the Direction C design system is the normative frontend (decision 0004). The design reference bytes were fetched by the coordinator and checked against the listed sizes (DC-9; `data/rbot-data.js` is referenced but not stored because it trips the secrets scan). The shell, navigator, rail and the Credit Snapshot composition are rebuilt from FP 01; six Pathway presets (decision 0009, `run/2`, status `not_in_pathway`) decide which modules a Front Page asks for; `module/5` and `view/4` carry `Fact.decimals` (currency stays 0 dp) and `TableRow.row_kind`; `report_view` binds module tables to blocks with every binding placed, routed to a rail destination, or listed under Limitations as "bound outside this Pathway" (never dropped); `call_withheld` and block states reach the data island as DOM tokens. Rendering acceptance for CP-0/CP-1 is recorded as `partial (synthetic fixture; real output in M7)` in `r14-coverage.json`; the coordinator compared the synthetic Front Page with FP 01 at the fold three times (logo, one-row call band, side-by-side blocks, chart legends, "Open in Model") and accepted it. Reviews: per-task reviews (Task E needed four rounds: fidelity items, `currency` precision ruling, schema-literal collisions with M4/M5 resolved as `module/5`/`view/4`), a whole-lane review and one integration round (Pathway-scoped bindings, `idle_statuses` moved to `registry`, `run/2` hash note in decision 0009, dead code removed, `.superpowers/` ignored); residuals carried to M6: the rail "with limitations" dot ignores out-of-Pathway bindings, no `source-context/2` run/1 rejection test, the Limitations panel prints block ids not titles. Gates on this commit: `make product-check` (1283 passed, 97.52%), `make check`, `make secrets` all exit 0; darwin pixel baselines unchanged; ubuntu skips the pixel tests with a stated reason. Not verified: real-data rendering (M7/M8), Linux baselines, the Limitations panel for out-of-Pathway entries in a real browser, native-host qualification. OpenRouter spend: $0 (M3 makes no model calls).

M2, 21–22 October 2026 (`dvii-impl-m2-runner` 2.1–2.10, `dv-feature`/`dv-sensitive`, base `1841ccf`, lane head `a6678e7`, squash-rebased onto `5fe525e` as this commit): the live model runner (`deploy-vii live {probe,module,regression,canary,corpus,reconcile}`) dispatches through the execution journal with a reserve-then-settle ledger bound to a per-batch cap and the US$200 cumulative ceiling; the OpenRouter key is read at call time only, selected by `credential_token_index` (DC-7); strict response schemas (every property required, optional → nullable, null → default before validation); mid-call provider errors inside a 200 body are classified (`timeout`/`insufficient_credit`/`http_error`); unknown charges are held at the worst-case reservation and reconciled against the generation endpoint, with a 404 corroborated by the account-usage delta before an `adjust` to 0; a labelled `proxy:<agent>` cohort is used only when credit is exhausted and never pooled (DC-8). Replay (I2) re-validates corpus entries offline, rebuilding the real Caesars pack context when present and skipping with reason when absent. Probes: probe-1 (first token, all 401, US$0), probe-2 (second token: Luna 400 on the untransformed schema, DeepSeek 504-in-200 timeouts held then reconciled to 0, GLM three draws all validator-rejected on mechanical grounds; ledger US$0.0069 after reconciliation), probe-3 after decision 0008 (Luna schema accepted but 0/2 first-pass, GLM 1/2 readiness accepted then `source_context` rejected, DeepSeek 2/2 timeouts reconciled to 0; US$0.0458), probe-4 with the user-selected pool of 22 October 2026 (GPT-6.1 Sol @high 1 accepted / 1 rejected, Grok 4.7 @xhigh 0/2 complete, MiMo-V2.6-Pro 0/2 truncated at 16,000 tokens, DeepSeek V4.1 Flash @max 429 and 502; US$1.378; ruling: Sol and Grok progress; the batch aborted on an uncaught CP-0 gate outcome, fixed in 2.10 with the other probe-4 runner findings). Decision 0008 (delegated, probe evidence): MC-1 applied to `source_readiness` (Python skeleton, `ReadinessSubmission` judgments only, Python composes hashes, sets, locators and coverage); MC-7 issues-only repair with the module-wide budget kept; `FinancialSubmission` split deferred; measured prompt-token bound (3.0 bytes/token). Reviews: per-task reviews (two Sonnet fix rounds max, Opus for sensitive tasks), whole-lane review APPROVE WITH FIXES (one integration round: `choices[0]` error codes reach DC-8 and the timeout path, quote-matcher tolerance row, combined ineligible + not-authorized + deadline-hold test), tournaments on the ledger, the key loader, the `adjust` replay rules, the composer, the token bound, the quote matcher, the absence rule, the not-authorized outcome and the deadline path. Gates on this commit: `make product-check` (1855 passed, 97.58%), `make replay` (49 passed, 14 skipped: 7 real-pack entries pack-absent and their 7 attempt-evidence checks), `make check`, `make secrets` all exit 0. Not verified: replay of the seven real-pack entries against `run/2` (the on-disk Caesars pack is `run/1`; decision 0009 rejects it, so those entries keep their recorded `run/1` pack hash until the pack is re-prepared in M7 and the entries re-keyed; with the pack upgraded to `run/2` in a scratch copy all seven replay `ok`), provider acceptance of the strict schema beyond the models probed, native Luna (no `codex` on PATH), Linux, provider acceptance of `minItems`, real-network deadline behaviour; a deadline-expiry hold without a generation id stands as spent (no ledger source for an id-less adjust). OpenRouter spend to date: ledger US$1.431 of the US$50 first batch, US$1.431 of the US$200 ceiling (probe-1 0, probe-2 0.0069, probe-3 0.0458, probe-4 1.3779).
