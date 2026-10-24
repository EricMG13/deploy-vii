# Deploy VII development plan (v2)

> **For agentic workers:** execute through the `dv-*` workers under CLAUDE.md and
> [the model matrix](../../../model-matrix.md): one owner per worktree, local commits,
> and coordinator integration. A separate PR session owns publication
> ([decision 0006](../../../decisions/0006-delegated-choices-and-orchestration.md)). Before dispatch, the coordinator turns
> each task below into a scoped brief with the actual base/head, editable paths,
> required reads and acceptance evidence. Steps use checkbox (`- [ ]`) syntax.

**Goal:** a working core credit report (CP-0 → CP-6) on the frozen public Caesars case,
produced from live model output and rendered in the user's Direction C design system.
Then the rest of r14 (E–H) and native Copilot delivery. Modules are tested regularly,
internally and externally.

**Architecture:** keep Python arithmetic, the hash-bound execution journal, immutable
artifacts and the deterministic offline renderer. Change four things:
- a live-model evidence gate before further contract work;
- degradation rules, so a blocked module stays visible without halting the report;
- a Python report view model bound to the design system's Front Page blocks;
- evidence-led methodology changes for performance and reliability (MC-1 to MC-10).

**Tech stack:** Python 3.13.15, uv 0.12.5, strict pydantic, pytest/Hypothesis/Playwright,
a vanilla JS/CSS single-file HTML report, and OpenRouter for external tests only.

**Spec:**
- requirements as recorded in [brief.md](brief.md) ("Goal and fixed decisions",
  "Constraints and acceptance");
- the [adversarial review](../../reviews/2026-10-21-adversarial-review.md);
- [decision 0004](../../../decisions/0004-design-system-frontend.md) (frontend);
- [decision 0005](../../../decisions/0005-methodology-changes-and-regular-testing.md)
  (methodology changes and regular testing);
- [decision 0006](../../../decisions/0006-delegated-choices-and-orchestration.md)
  (delegated choices: orchestration, publication, DCF, CP-MODEL, caps, credential, proxy);
- [frontend contract](../../../frontend-direction-c.md);
- [testing contract](../../../testing-and-telemetry.md).

**Authority:** adopted 21 October 2026 on the user's instructions "Apply your
recommendations and create the new development plan" and "Your also authorised to alter
the methodology to improve performance and reliability. Include regular internal and
external testing of modules (with open router and stated model choice from my codex
chats)." This plan supersedes the milestone checklist in `brief.md:55-74`, which stays
there as history. The brief remains the append-only progress log. Base: `main` at
`7526dbc`. Decision 0006 records the choices the user delegated later that day
("Apply your recommendations (but keep a record of your choices)").

## Global constraints

- Python 3.13.15 and uv 0.12.5 with the committed lock. Run `make check` and
  `make product-check` per change, `make secrets` before publication, and `make audit` on
  dependency changes.
- Python owns arithmetic **and display formatting**. Models supply evidence-grounded
  analysis. No model-written number reaches the report unless it resolves to a Python
  fact.
- Methodology changes follow decision 0005's guardrails. Definitions, scales, judgment
  vocabularies, missing-data meaning and r14 coverage stay fixed. Each change gets a row
  in `docs/methodology-adaptation.md` with before/after evidence.
- External tests draw uniformly at random among eligible `openai/gpt-6-luna`,
  `z-ai/glm-5.3-flash` and the latest suitable DeepSeek, pinned per batch. Use high by
  default and xhigh only for predefined difficult cases where supported. Retries stay on
  the selected model.
- The first core batch is capped at US$50 in total, including failures and repairs.
  Never replenish credit. When it is exhausted, use the decision 0006 DC-8 proxy: native
  Luna if available, otherwise a labelled Claude-agent proxy cohort that never pools
  with pool results and never counts as qualification. Recurring caps and the US$200
  cumulative ceiling follow decision 0006 DC-6.
- The OpenRouter key is read at dispatch time from the credential file named in
  decision 0006 DC-7. Never print, log, persist, commit or pass it on a command line.
- Raw sources, responses, telemetry and credentials stay out of Git (`artifacts/` and
  `runs/` are ignored). The committed replay corpus holds only extracted payloads and
  expected outcomes.
- Test cases are the frozen public Caesars case, plus synthetic market, portfolio and
  adversarial fixtures that are explicitly labelled as synthetic.
- Each milestone tracks four separate statuses: implementation, analytical
  qualification, rendering acceptance and native-host qualification. The coverage-map
  vocabulary is `unrun | partial | implemented`.
- Reviews: confidence-review after every code change. Rewrite-tournament (no-argument
  post-edit mode) only for artifact state, provenance, financial calculations and
  execution ordering.
- Escalate to `dv-escalate` after two concrete failed repairs. No recursive agent
  spawning.
- Every task report ends with `Not verified:`. Update the owner's row in
  `docs/methodology/r14-coverage.json` in the same commit as its code.

## Testing regime (decision 0005)

| Tier | Kind | When | Command (built in M2) | Gate |
| --- | --- | --- | --- | --- |
| I1 | internal | every change | `make check`, `make product-check` | exit 0 |
| I2 | internal replay | every change to a model-facing contract, validator or prompt | `make replay` | no unexplained change in recorded outcomes |
| I3 | internal | each milestone | full suite, browser acceptance, bounded sweep | exit 0, sweep findings resolved or recorded |
| E1 | external | each module completion | `make live-module MODULE=<id> CAP=<usd>` | case recorded, four statuses updated |
| E2 | external | each milestone | `make live-regression CAP=<usd>` | no validity or accuracy regression against the previous E2; matched three-model comparison reported |
| E3 | external | weekly while development is active | `make live-canary CAP=<usd>` | a validity drop opens a finding |

Each external batch:
- writes `live-<batch-id>.md` (a summary, no raw data);
- retains raw evidence under `artifacts/model-tests/`;
- adds validated payloads to the I2 corpus.

CI runs only I1 and I2 (`model_calls = false`) once hosted CI is available.

## Review Focus

These are the inputs most likely to break a real run that no current test exercises.
Each is pinned by a test in its owning milestone.

1. **A selected module ends Blocked** (CP-3D with no market data, CP-4 with no
   indenture). The report still renders: the module shows Blocked and its consumers run
   restricted with the limitation. Owner: M4, test
   `test_blocked_optional_producer_does_not_halt_core_report`.
2. **Model prose that names periods, filings or tranches** ("FY2025", "10-K",
   "2032 notes") is accepted. A bare figure such as "5.2x" is rejected unless it is a
   resolved reference. Owner: M6, test `test_prose_runs_allow_labels_reject_bare_figures`.
3. **Negative, zero, missing and not-meaningful values on a Front Page** render as
   `(62)`, `0`, `∅ G#` and `∅ G41 n.m.`, never as `null`, `-62` or a scale-less `0.00`.
   Owner: M3, test `test_display_oracle_matches_design_system_examples`.
4. **An OpenRouter failure** (truncated JSON, insufficient credit, or a routed fallback
   model): the attempt is retained, spend reconciles, the cap is never exceeded and the
   cohort is recorded. Owner: M2, tests `test_reservation_refuses_dispatch_beyond_cap`
   and `test_fallback_model_is_classified_not_hidden`.
5. **A real-size pack** (tens of MB) passed through the journal keeps bytes written per
   transition independent of the number of attempts. Owner: M5, measurement recorded in
   its review file.

## Current state (verified at `7526dbc`, 21 October 2026)

| Area | Implementation | Analytical | Rendering | Note |
| --- | --- | --- | --- | --- |
| Development tooling | done | n/a | n/a | `devtools/` with 26 tests |
| A: r14 map and shell | done against the superseded phase-1 reference | n/a | **unmet**: "matches the attachment" fails | Reopened as M3 |
| B: preparation and CP-0 | done | unrun (synthetic only) | **unmet**: header shows run identity, not readiness | Closed by M7 |
| Execution journal | done | n/a | n/a | Blocked-module defect → M4; storage → M5 |
| C: CP-1 substrate | partial (registers, Model, reconciliations, narrative protocol, QA arithmetic) | unrun | candidate previews only | FFO coverage and DCF → M1; envelope → M6 |
| CP-1A, D–H | not started | unrun | unrun | M7–M11 |

Gates: 978 product tests pass locally. CI is blocked by GitHub billing. OpenRouter spend
is US$0 of US$50.

## Order and parallel lanes

```
M1 ──┬── M2 (runner, replay, probe) ──┐
     ├── M3 (design re-baseline) ──────┼── M6 ── M7 ── M8 ── M9 ── M10 (E, F, G) ── M11 (H)
     └── M4 (degradation) ── M5 ───────┘
```

M2, M3 and M4 write disjoint files and may run in parallel. M5 follows M4 because both
edit `execution.py`. M6 needs the M2 evidence, the M3 view model and the M4 status rules.

---

## M1. FFO interest coverage and DCF (review W9; decision 0006 DC-4) (merged a97bf77)

Scoped brief: [m1-kpi-definitions-brief.md](m1-kpi-definitions-brief.md).
Route: `dv-sensitive`.

**Acceptance:** the row computes (FFO + cash interest paid) / cash interest paid with
signed operands and provenance. A zero or missing denominator stays Not Calculable. The
false limitation text is removed. DCF computes as FCF − dividends paid and DCF/debt as
DCF / canonical total debt, each Not Calculable when an operand is missing; no KPI stays
undefined. I1 passes. Tournament: `_canonical_frame` (financial calculation).

## M2. Model runner, replay corpus and capped live probe (review C1; MC-1, MC-7, MC-10) (merged 5a8d36c)

**Editable:** `src/deploy_vii/live/` (new), `src/deploy_vii/execution_cli.py`, `Makefile`
(`replay`, `live-module`, `live-regression`, `live-canary`), `tests/product/test_live_*.py`,
`tests/product/replay/` (new), `docs/development/live-runner.md`,
`settings/project.toml` (`live_model_runner_implemented`).

- [x] **2.1 Coordinator.** Fetch the current OpenRouter API documentation through
  Context7 into the brief: chat completions, usage and cost fields, the reasoning-effort
  parameter, provider routing and fallback controls, and the key/credit endpoint. Keep
  project detail out of the query. Confirm the decision 0006 DC-7 credential file exists
  without reading its value. Resolve eligibility and pricing for the three candidates.
- [x] **2.2 `dv-sensitive`: runner core.** Build:
  - a credential loader that reads the DC-7 key file at dispatch time (RTF → text via
    `textutil`, whitespace stripped, `sk-or-` prefix checked) and holds it in memory only;
  - eligibility resolution;
  - a seeded uniform draw that records the ordered pool, exclusions, RNG algorithm,
    seed and draw before dispatch;
  - versions pinned per batch;
  - a **reservation ledger**: reserve the worst-case cost (prompt tokens plus
    `max_tokens`, at the pinned price) before dispatch, persist it atomically, reconcile
    against the returned usage, and refuse dispatch when reserved plus spent would
    exceed the cap;
  - retention per `docs/testing-and-telemetry.md`;
  - provider fallback disabled, or else classified as fallback;
  - retries on the same model as new attempts.

  Source text enters prompts only as delimited data, and the model gets no tools.
  *Amended by M8 task 8.0d (user decision, 24 Oct 2026; decision 0005 row 8.0d):* the CP-1
  stages may run as tool loops. These offer read-only `search_pack` and `read_pages` over the
  prepared pack, plus the step's own validating submit tool. Tool results are delimited
  SOURCE data and never instructions. The model gets no other tool: no write, network or host
  tool. The Copilot enterprise runtime (M11) is where this holds in production. There the
  backend blocks prompt injection and the sources are trusted-ish, so injection through tool text
  is a residual risk, not a blocker.
  Prompts carry only the module's declared inputs (MC-10). Tests:
  `test_reservation_refuses_dispatch_beyond_cap`,
  `test_fallback_model_is_classified_not_hidden`,
  `test_partial_json_is_retained_and_settles_rejected`,
  `test_unsupported_xhigh_maps_to_high_and_is_recorded`,
  `test_same_seed_reproduces_draw`, `test_missing_usage_is_null_with_reason` and
  `test_credential_never_appears_in_records_or_errors`.
  Tournament: the ledger (artifact state).
- [x] **2.3 `dv-feature`: CLI and Make targets.** `deploy-vii live
  {probe,module,regression,canary}` dispatches through the existing journal (`begin` /
  `submit_step` / `finish`), so payloads meet the same validators. Add the four Make
  targets from the testing regime. `regression` runs the matched three-model comparison
  in randomized order.
- [x] **2.4 `dv-feature`: replay (I2).** `make replay` re-validates every corpus entry
  under `tests/product/replay/` (extracted payload, the input hashes it binds, expected
  validator outcome) offline. Test `test_replay_detects_changed_validator_outcome`.
- [x] **2.5 `dv-feature`: backup cohort.** Detect when credit is exhausted, check native
  Luna availability, and otherwise accept a payload produced by a coordinator-dispatched
  Claude-agent proxy (decision 0006 DC-8) through the same journal validators. Record it
  as a separate `proxy:<agent>` cohort that never pools with pool results and never
  counts as qualification. Do not substitute silently.
- [x] **2.6 Coordinator: probe (the first E-tier batch).** CP-0 plus the CP-1
  `source_context` and `financials` steps on the frozen Caesars pack, three draws per
  eligible model, cap US$10. Write `live-probe-1.md` with `dv-research`: first-pass
  validity per step and model, issue classes, cost, tokens and latency. Seed the replay
  corpus from the probe.
- [x] **2.7 Decision 0008 and `dv-sensitive`: contract shape.** Use the probe evidence to
  apply:
  - MC-1: Python pre-fills mechanical fields; the model returns judgments and evidence
    references only;
  - MC-7: repairs are step-scoped, with a per-step budget if the probe shows a
    module-wide budget is unsurvivable;
  - a split of `FinancialSubmission` if first-pass validity requires it.

  Rerun the probe subset (US$5 or less, within the M2 cap) to record the after evidence.
  Add the rows to `methodology-adaptation.md`.

**Acceptance:**
- Implementation: the runner and replay tests pass; `live_model_runner_implemented = true`.
- Analytical: before/after probe reports exist. They are evidence, not qualification.
- Spend: at most US$10, and the ledger reconciles to provider usage.
- No further CP-1 contract change merges without citing the probe.

## M3. Design-system re-baseline, A′ (review C3, F1–F6, W6, N4) (merged 5fe525e)

**Editable:** `design/reference/`, `src/deploy_vii/assets/`, `src/deploy_vii/render.py`,
`src/deploy_vii/display.py` (new), `src/deploy_vii/report_view.py` (new),
`src/deploy_vii/bindings/` (new), `src/deploy_vii/charts.py` (new),
`src/deploy_vii/contracts.py` (Run and status only, in 3.5),
`tests/product/test_{display,report_view,bindings,charts,browser,render}.py`,
`docs/frontend-direction-c.md`.

- [x] **3.1 Coordinator (MCP-only): reference snapshots.** The design-system file is
  already snapshotted (decision 0004). Obtain the bytes of `RBOT FP 01`–`06`,
  `RBOT Report.dc.html` and `lib/{shell,vm,vm-fp,charts}.js`, from a user export or an
  MCP read verified against the listed size and etag. Render reference screenshots of
  FP 01 and FP 02 at 1440×900 with claude-design `render_preview` into
  `design/reference/screens/`.
- [x] **3.2 `dv-scaffold`: tokens and fonts.** Replace `tokens.css` with the DS-01
  `--rb-*` block verbatim and point `app.css` at it. Embed Red Hat Display 600/700,
  Text 400/500/600 and Mono 500/600 (OFL, with recorded provenance and hashes). Remove the
  `local()` faces.
- [x] **3.3 `dv-feature`: display formatter.** In `display.py`, implement
  `format_value(amount: Decimal | None, unit_class: UnitClass, state: CellState) -> str`
  using decision 0004's precision and state table. Test
  `test_display_oracle_matches_design_system_examples` uses an independent table of
  expected strings from DS-04 and DS-07. Add a Hypothesis property: the sign and
  magnitude of the displayed value round-trip to the source at the stated precision.
- [x] **3.4 `dv-feature`: report view model and bindings.** In `report_view.py`, define
  the typed `Pathway`, `CallItem`, `Line`/`Run`, `Block`, `Cell`, `Passport` and
  `ChartSpec` (with table twin). Use report-wide `C#`/`K#`/`G#` IDs with a reverse index.
  Per-module binding maps in `bindings/` map Fact coordinates to Block/Cell.
  `validate_bindings(view, maps) -> tuple[str, ...]` rejects unbound and doubly bound
  facts. Map statuses to the design's words. Tournament: the binding validator
  (provenance).
- [x] **3.5 Decision 0009 and `dv-sensitive`: Pathway presets.** Define the six Pathways
  (Credit Snapshot, Earnings Update, Relative Value, Covenant & Refinancing, Distressed &
  Restructuring, Portfolio Decision). Each maps to its requested modules and Front Page
  composition. Add `not_in_pathway` as a status distinct from `unrun`, and bump the Run
  schema to `run/2`.
- [x] **3.6 `dv-feature`: shell.** Build the rail (six destinations), the navigator
  (tally, family bars, outline, "/" search), the sticky call band in its three states,
  typed inspector passports with table twin, block anatomy and states, and dense,
  key/value and period-grid tables. Use `textContent` only and keep the CSP unchanged.
  Derive counts from the registry.
- [x] **3.7 `dv-feature`: charts.** Generate static SVG in Python for the kinds FP 01
  needs (line strip, grouped and stacked columns, waterfall, debt stack, n/a frame).
  Each has focusable marks naming series, value and provenance, plus a table twin. Add
  other kinds when an owner needs them.
- [x] **3.8 `dv-feature`: Credit Snapshot Front Page.** Populate it from a SYNTHETIC
  fixture plus today's CP-1 candidate registers where bound. Every other block shows its
  honest state.
- [x] **3.9 `dv-feature`: acceptance (I3 browser).** Cover:
  - structural comparison with the reference FP (block order, heads, marks, states);
  - reviewed screenshot baselines at 1440×900 (fold) and 1280×800;
  - zoom at 125% and 200%;
  - the keyboard path through rail, navigator, figures, inspector and chart marks;
  - chart/table-twin parity;
  - offline operation with zero requests.

  Replace the circular parity assertions (`test_report_tables.py:288`,
  `test_register_view.py:126`, `test_interface_view.py:92`) and the literal
  `"field_parity": "passed"` (`test_browser.py:62`) with oracle comparisons that fail
  closed.

**Acceptance:** rendering acceptance for the shell and the synthetic Credit Snapshot.
Analytical: n/a.

## M4. Degradation and status semantics (review C2, W1; MC-3, MC-4) (merged c66a238)

**Editable:** `src/deploy_vii/registry.py`, `src/deploy_vii/methodology.json`,
`src/deploy_vii/execution.py`, `src/deploy_vii/contracts.py` (`Input`, `Module`),
`src/deploy_vii/cp1_quality.py`, `tests/product/test_execution.py`,
`tests/product/test_registry*.py`, `docs/development/execution.md`.

- [x] **4.1 `dv-research`: edge rules.** From the pinned r14 `SKILL.md` texts
  (`bd71346`), classify each required and optional edge: block the consumer, or continue
  restricted. Start from `methodology-adaptation.md:39-41` (CP-1A → CP-2).
- [x] **4.2 Decision 0007.** A blocked optional producer reaches its consumer as a
  status-carrying input with an inherited limitation. A blocked required producer
  follows its edge rule. CP-5 always runs over the selected set and reports blocked
  analysts as findings. Status separates `own_status` from inherited limitations.
- [x] **4.3 `dv-sensitive`: implementation.** `Input` gains `status`. `current_inputs`
  admits blocked inputs per edge rule. Derive status from own findings plus material
  inherited gaps. Derive `cp1_quality` `module_status` from `own_status`. Test
  `test_blocked_optional_producer_does_not_halt_core_report` reproduces the review
  probe: CP-4 Blocked leaves CP-3, CP-5 and CP-6 runnable and restricted, with the
  limitation. Test `test_pass_reachable_with_immaterial_inherited_gap`. Tournament:
  `current_inputs` and status derivation (execution ordering, artifact state). Add the
  MC-3 and MC-4 rows.

**Acceptance:** both tests pass, and decision 0007 is recorded with the per-edge table.

## M5. Content-addressed journal storage (review W4) (merged 4705995)

**Editable:** `src/deploy_vii/execution.py`, `tests/product/test_execution.py`,
`docs/development/execution.md`.

- [x] **5.1 `dv-sensitive`.** Store the pack and each payload once as blobs named by
  their SHA-256. Snapshots reference them by hash; parent hashes cover the small
  snapshot. Use schema `execution/5`, and reject older stores (current policy).
  Tournament: `_write`/`read` (artifact state).
- [x] **5.2 Coordinator measurement.** Use the hash-pinned Caesars filing to record bytes
  written and wall time per `begin`/`submit_step`/`finish`, before and after.

**Acceptance:** bytes per transition do not grow with the number of attempts, and the
measurements are recorded.

## M6. CP-1 canonical envelope and handoff (review W2, W5, W10; MC-2, MC-5) (merged 2e5a050)

- [x] **6.1 `dv-feature`: CP-MODEL artifact (decision 0006 DC-5).** Encode the HTML Model
  destination plus the calculation JSON in `methodology.json` and the coverage map, with
  the r14 XLSX export marked deferred. CP-MODEL requires accepted CP-1 and joins CP-5's
  scope.
- [x] **6.2 `dv-sensitive`: shared prose runs (MC-2).** Replace free `Claim.text` with
  runs: text plus `{ref|unit}` figure references and `[G#]` gap references, resolved and
  formatted by Python. Numeric tokens must be resolved references. Labels for periods,
  filings and instruments are allowed, which relaxes `narrative.py:40-43`. Test
  `test_prose_runs_allow_labels_reject_bare_figures`. Tournament: the resolver
  (provenance). I2 replay shows the outcome changes on the probe corpus.
- [x] **6.3 `dv-sensitive`: QA lineage ceiling (MC-5).** Python derives each evidence
  ID's maximum lineage class from its producing register; the model may only downgrade
  it. Test `test_model_cannot_upgrade_lineage`. Tournament (provenance).
- [x] **6.4 `dv-sensitive`: envelope and handoff.** Build the canonical Markdown envelope
  (r14 ordered sections, `null` retained in the transport only), handoff verification
  and the reader. Promote CP-1 under the M4 status rules and the decision 0008 contract
  shape.
  Measured on the real Caesars pack (proxy journal e1-cp1-7, 23 Oct 2026, coordinator's
  ledger):
  - prompt sizes: `source_context` about 840 KB of pack sources; `financials` about 840 KB
    plus 38 KB; `narrative` user prompt 493,031 characters after task 7.5 (8,900,941
    before); `readiness` 609,635; `quality` 270,167;
  - render: the three heads in 0.28 s; HTML 1.47 MB for CP-0 (81 facts), 2.40 MB for CP-1A
    (840 facts) and 1.33 MB for the blocked CP-1 (0 facts);
  - r14 statuses after the first full chain, as the journal shows them: CP-0 restricted;
    CP-1A restricted (qualification implemented / unrun / unrun / unrun); CP-1 blocked (QA
    Blocked, confidence 0, Insufficient Information; 160 BLOCK gaps; source gate partial).
- [x] **6.5 `dv-feature`: CP-1 bindings.** Bind the envelope to the Model destination and
  the Credit Snapshot blocks (Financials and credit metrics, capital structure, EBITDA
  adjustments, metric strip).

**Acceptance:** implementation and I2, plus rendering of the CP-1 blocks from the probe's
live candidate.

## M7. CP-1 live acceptance and CP-1A

Lane state (23 Oct 2026, with the 24 Oct 2026 resume below; each task's result is in
`m7-live-acceptance-review.md`). Landed:
7.0 hardened the mismatch text, prompts and reports before E1; 7.0b runs the product suite
in parallel (decision 0011); 7.0c made the request deadline configurable; 7.0d put the Python
vocabularies into the `financials` sent schema; 7.0e lets the `module` driver dispatch the
MC-7 repair; 7.0f states the sign-convention rule to the model; 7.0g repairs each CP-1 stage
step once within its attempt; 7.0h stops a truncated try from consuming a repair; 7.0i has
Python fill every hash binding; 7.0j states the statement-register rules in the `financials`
prompt; 7.1a publishes CP-MODEL deterministically once CP-1 is promoted; 7.2 adds CP-1A
business and transaction context; 7.4 adds the live `quality` step that promotes CP-1; 7.5
sends later CP-1 steps bounded upstream projections; 7.6 states the narrative and readiness
validator rules in their prompts; 7.7 places the `segment-allocation` table in the r14
envelope; 7.8 reads a 402 for its reason before calling it exhaustion; 7.9 refines the
prompts from the first full proxy chain; 7.10 closes the review follow-ups; 7.11 closes what
E1 batch e1-cp1-13 (the first GPT-6.1 Sol at high chain) found: three prompt facts, a
quote-side hyphen wrap, reconciling an interrupted attempt and withholding a reply body whose
account id survives redaction; 7.12 (envelope memory sweep) adopted `_content_hash` over
pydantic's JSON bytes: `write_envelope` growth 0.525 to 0.395 GB, pipeline peak 1.34 to 0.98 GB,
byte-identical envelopes; 7.13 has Python prefill the book's and periods' four dimension strings
from the bound scope, and lets an interrupted attempt settle from the next batch's before-check;
7.14 requires `source_context` scopes to carry non-null, entity-consistent dimensions, and the
reconciled report cross-checks spend against the key's usage; 7.15 closes the whole-lane
review's pre-PR fixes. Not landed: 7.1 (E1 for CP-0 and CP-1, its box below still open) and 7.3
(E2, its box below still open): both were paused by the user on 23 Oct 2026 (all live testing)
and resumed on 24 Oct 2026 at Sol medium (decision 0005, 24 Oct 2026 amendment), the next batch
pending the user's choice of runner. 7.16 landed (Python-owned hash fields never reach the
model as "Field required"); the hybrid harness merged as devtools (97ae4bd); three of three
Sol-medium model outcomes passed CP-1 through the harness on 24 Oct 2026 (one draw lost to a
provider 502), recorded in the acceptance review §7.17; the product-runner port is M8 task 8.0d.

- [ ] **7.1 E1 for CP-0 and CP-1** on Caesars. This closes B's adopted condition: real
  readiness populates the header, Evidence and Limitations. It also closes C's CP-1
  condition: tables, capital structure and the Model grid reconcile to accepted
  artifacts. Measured in E1 batch 6 (23 Oct 2026): after the first accepted `financials` the
  `narrative` prompt held 8,900,941 characters (every retained step's raw output), so task 7.5
  sends each later step a bounded projection instead (decision 0008 amendment, task 7.5).
- [x] **7.1a `dv-feature`: CP-MODEL deterministic publication.** Give CP-MODEL a head when CP-1 is promoted: publish the promoted envelope as the Model destination plus the calculation JSON (DC-5), Python only, no model call; required before M8's CP-5 case under any preset that requests CP-MODEL (decision 0009 amendment).
- [x] **7.2 CP-1A** business and transaction context: contract over prose runs,
  validator, Company profile bindings, then E1.
- [ ] **7.3 E2 for the milestone:** matched three-model comparison over CP-0, CP-1 and
  CP-1A.

**Acceptance:** the adopted B and C completion conditions are met, with all four statuses
recorded and E2 reported.

## M8. Core slice D: CP-2 → CP-4 → CP-3 → CP-5 → CP-6 (MC-6)

M8's CP-5 case depends on task 7.1a: under the presets that request CP-MODEL, CP-5 cannot
begin until CP-MODEL has a head. Keep each module thin: a minimal contract over prose runs plus Python facts, bindings to
its Front Page blocks, and one E1 case. CP-5's mechanical checks run in Python: citation
existence and quote match, cross-module figure identity, stale inputs, gap propagation.
The model judges material support and contradictions only (MC-6). Final integrity
validation follows CP-6 without making CP-5 its consumer. Close with E2.

**Acceptance (adopted D):** a complete report for the core scope passes factual,
analytical and rendering checks, rendered as one Credit Snapshot. Stop before the batch
cap; use the backup cohort if credit is exhausted.

## M9. Scope extension, artifact reuse and concurrent dispatch (review W3; MC-8, MC-9)

- [ ] **9.1 `dv-sensitive` (MC-9).** A journal transition extends the requested set to a
  superset. It recomputes dependencies and stales only the heads whose resolved inputs
  change. Test `test_adding_cp1b_refreshes_only_affected_consumers`. Tournament
  (execution ordering).
- [ ] **9.2 `dv-sensitive` (MC-8).** Allow concurrent pending attempts for modules with
  disjoint, settled inputs (for example CP-1 ∥ CP-1A, CP-2 ∥ CP-4). The journal stays
  single-writer per transition. Adopt this only after an E2 run shows the wall-clock
  gain; otherwise record it as rejected. Tournament (execution ordering).

**Acceptance:** E's completion condition becomes testable, and the MC-8 decision is backed
by measurement.

## M10. E, F, G (scope unchanged from `brief.md:70-72`)

Each owner adds its contract, validator, Front Page bindings, coverage-map row and an E1
case. Each milestone closes with E2. Bind to these Front Pages:

| Front Page | Owners |
| --- | --- |
| Earnings Update | CP-1B and CP-1D |
| Relative Value | CP-1C, CP-3C and CP-3D |
| Covenant & Refinancing | CP-4 extensions and CP-2D |
| Distressed & Restructuring | CP-2A, CP-2G, CP-2H and CP-4C |
| Portfolio Decision | Portfolio Fit and CP-8 |

Portfolio Fit gets an owner contract before G (review N3).

## M11. H: native delivery (unchanged)

One packaged skill. Accept real native installation, invocation, interruption/resume and
report delivery. Keep external blockers visible.

---

## Decisions

| No. | Subject | Status |
| --- | --- | --- |
| 0004 | Design system and Front Pages are the normative frontend; display precision and state spelling | **Adopted** with this plan |
| 0005 | Methodology changes for performance and reliability (MC-1 to MC-10); regular internal and external testing | **Adopted** with this plan |
| 0006 | Delegated choices: orchestration, PR session, DCF, CP-MODEL, caps, credential, no-credit proxy, design bytes | **Adopted** 21 October 2026 |
| 0007 | Degradation and status semantics, with per-edge rules | M4 |
| 0008 | Model-facing contract shape and repair budget, from probe evidence | **Adopted** 21 October 2026 (M2.7) |
| 0009 | Pathway presets and the `not_in_pathway` status | M3.5 |

## Budget plan

First US$50 batch:

| Use | Cap |
| --- | --- |
| M2 probe, including the after-run | US$10 |
| M7 E1 and E2 (CP-0, CP-1, CP-1A) | US$15 |
| M8 E1 and E2 (core slice) | US$25 |

Unspent budget rolls forward within the batch only. Recurring caps (decision 0005,
applied under decision 0006 DC-6):

| Tier | Cap |
| --- | --- |
| E1 | US$3 per module case |
| E2 | US$15 per milestone |
| E3 | US$3 per week |

Cumulative ceiling: US$200 across OpenRouter and Anthropic spend (decision 0006 DC-6
amendment, 24 Oct 2026), including the first batch. Pause external
testing and ask the user before exceeding it. The reservation ledger enforces every cap.

## Per-task working rules

1. The coordinator writes a scoped brief with:
   - task ID, base/head and editable paths;
   - required reads, route, reviews and acceptance evidence;
   - testing tiers;
   - the blast radius (GitNexus `impact` where an index exists, otherwise a caller
     search);
   - any new public-library docs, fetched via Context7.
2. The worker works test-first and runs I1 (plus I2 when a model-facing contract
   changes). Its report ends with `Not verified:`.
3. The coordinator inspects the full diff, reruns the gates (and `make secrets` before
   publication), then confidence-review, then the tournament if the change is in a key
   area. It appends a dated result to `brief.md` and updates the coverage map and the
   methodology-adaptation rows.
4. The coordinator hands the verified local commits to the PR session (decision 0006
   DC-2, DC-3). The PR session pushes, opens the PR, squash-merges once local gates exit
   0 and the reviews are recorded, deletes the branch and reports the merge SHA.

## Resolved decisions

Decision 0006 resolved the former open decisions on 21 October 2026: DCF (DC-4),
CP-MODEL (DC-5), recurring caps and the ceiling (DC-6), the OpenRouter credential
(DC-7), the no-credit proxy (DC-8) and the design reference bytes (DC-9). Record
any new user-owned choice here and stop for the user's answer.

[Decision 0008](../../../decisions/0008-model-facing-contract-shape.md) is a coordinator
ruling on probe-2 evidence (plan 2.7, delegated to probe evidence; the user may override): MC-1
for `source_readiness` (the model returns a `ReadinessSubmission`, Python composes the stored
`ReadinessReview`), MC-7 issues-only repair prompts, and the prompt-token bound from a measured
3.0 bytes per token. Two choices are deferred for lack of evidence: a per-step repair budget
(revisit when the rerun shows a module-wide budget exhausted; the rerun reports `repair_count`
per step) and a `FinancialSubmission` split (revisit when `financials` first-pass validity on
the rerun is below 2 of 3 draws for any model).

User-owned choice, 22 October 2026 (E1 cap amendment, decision 0006 DC-6, relayed through the
Watcher session): E1 for the CP-1 case is US$10 per batch, with a batch cap of US$12 together
with the CP-0 case; other modules stay at US$3 per case; the US$200 cumulative ceiling is
unchanged; the orchestrator pauses and asks the user before any figure above these. E1 batches
1 to 5 (`e1-cp1-1` to `e1-cp1-5`) ran under it.

User-owned choice, 24 October 2026 ([decision
0005](../../../decisions/0005-methodology-changes-and-regular-testing.md), amendment of that
date): live testing resumes on GPT-6.1 Sol at effort `medium` (`--models
openai/gpt-6.1-sol@medium`; `settings/project.toml` `default_effort` and `complex_effort` are
`medium`), superseding the 22–23 October "stay with high". The user paused all live testing on
23 October 2026; the next batch waits for the user's choice between the hybrid harness and the
product runner.
