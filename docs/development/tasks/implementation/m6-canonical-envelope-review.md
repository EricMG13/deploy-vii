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

Pathways: no preset requests CP-MODEL (decision 0009 owns them, not edited) (superseded by 6.5). `plan()`
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
  `CEILINGS` (citation Directly Sourced; calculation Calculated; estimate
  Assumption-Based; gap, missing and coverage Insufficient Information). A ceiling that disagrees with its basis is rejected.
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

Review fix (coordinator ruling): an `Estimated` or `Proxy` calculated amount (historical
value, canonical value, KPI or computation) caps at Assumption-Based through the `estimate`
basis, so a supplied Calculated is an upgrade issue. Plain calculations still cap at
Calculated. Pinned by `test_an_estimated_or_proxy_figure_cannot_be_rated_calculated` and
`test_estimated_or_proxy_calculations_cap_at_assumption_based`. No producer in the
repository emits Estimated or Proxy yet, so the CP-1 test marks a record directly.

Accepted conservative ceilings (coordinator, recorded as accepted): historical values stated
from source cap at Calculated; normalized statement cells and cited `not_applicable` values
cap at Directly Sourced.

Not verified: that each register-level ceiling is semantically right for every record beyond
the fixture registers; an Estimated or Proxy record from a real producer; any live model
output against the ceilings.

## 6.2 Prose runs

Task `dvii-impl-m6-prose-runs`. Review W5, decision 0005 MC-2: numbers in model prose
appear only as resolved references, for `Claim.text` of every module and for CP-1's
narrative prose.

What changed:

- `prose.py` (new): the run-text grammar (`tokenize`, `check`, `bare_figures`, `LABELS`),
  binding (`bind`: fact ids and single-carrier calculation ids) and module validation
  (`issues`, `prose_issues`). Grammar, labels and limits are documented in
  `docs/development/execution.md` "Claim run text".
- `contracts.py`: `Claim.text` is `RunText`, a `Text` with an `AfterValidator` that refuses
  malformed references (unbalanced or empty braces and brackets, an empty unit, an id over
  160 characters). A bare figure is not a schema error, so `module/5` is unchanged: the
  shape is the same, no committed accepted fixture's bytes change, and a stored module
  whose claims carry free figures still loads (it cannot render; see below).
- `execution.candidate_issues` adds `prose_issues(candidate, names=(issuer_name,))`, so a
  claim with an unresolved reference or a bare figure settles `rejected` (or `blocked` on
  the repair) before any module validator runs.
- `narrative._prose` delegates to `prose.check` with no resolvable ids: periods, filings,
  instruments, sections and versions pass; bare figures and any run reference fail, as
  numbers enter CP-1 prose through evidence parts. This relaxes the old any-digit rule.
- `narrative_projection`: a finding's evidence part becomes `[<fact id>]` of its
  evidence-trace Evidence cell in the claim text (previously the literal `[E#]`), and the
  projection fails closed if a claim does not resolve. Table text keeps `[E#]`.
- `report_view`: `figure_unit`, `ClaimRun`, `module_refs` and `resolve`. `render()` adds
  `claims[].runs` and `claims[].plain` to the data island; `app.js` draws claims through the
  shared runs renderer (`runNodes`) and uses `plain` as the passport title.

Adopted id grammar: `contracts.Identifier`. A figure or chip names a `Fact.fact_id` of
the same module or a `Fact.calculation_id` exactly one of its facts carries; a gap is an
unsettled fact, shown with its report-wide `G#`. No new id space. Ledger gaps reach CP-1
claims as evidence chips to their trace rows.

Deviations from the brief:

- `resolve` lives in `report_view.py`, not `prose.py`. `contracts` imports `prose` for the
  `Claim` validator, so `prose` cannot import `report_view` (which imports `contracts`) at
  load; `resolve` needs the cell spelling and the report-wide ids that `report_view` owns.
  `prose._fact_issues` imports `report_view.figure_unit` inside the function for the same
  reason. Its signature is `resolve(text, bound, refs, *, names)` with `bound = prose.bind(facts)`
  (bound once per module) instead of `(facts, calculations, gaps)`: calculations and gaps
  are facts of the module here.
- Figures are spelled with `fact_spelling`, which uses `exact_text` on its exact path, not
  with `exact_text` alone: `exact_text` of a `decimal_fraction` followed by `%` would show
  0.125 as "0.125%". The prose figure therefore reads as its table cell does, with the
  amount's scale label appended.
- Edited outside the listed paths: `execution.py` (the module validator the brief names),
  `narrative_projection.py` and `tests/product/test_narrative_projection.py` (the one
  Python producer of CP-1 `Claim.text`; its `[E#]` labels would not resolve). The
  projection test's markdown-link injection prose changed to an `<img>` injection because
  brackets are now reserved in CP-1 prose.

I2 replay: `make replay` does not exist on this base (it comes from the M2 lane), so no
corpus entry was replayed. Expected effect: a `source_readiness` payload whose analysis
claims carry digits outside labels now passes its CP-0 step but settles `rejected` at
`finish` with `Claim <id>: Bare figure: <token>` issues; claims with only labels and words
are unchanged. A CP-1 narrative review whose prose has periods, filings or section numbers
now validates where it was refused; one with brackets or braces is now refused.

Evidence: `tests/product/test_prose.py` (`test_prose_runs_allow_labels_reject_bare_figures`
and its 16 accepted / 13 rejected rows, `test_unresolved_reference_is_an_issue`, malformed
tokens, tokenizer classification, names, two hypothesis properties, module-level fact-kind
and unit issues, calculation-id ambiguity, and settlement as `rejected`),
`test_narrative.py` (`test_cp1_narrative_accepts_period_and_filing_labels`, new rejected
rows), `test_contracts.py` (`Claim` syntax), `test_report_view.py` (resolution, spelling,
provenance, fail-closed paths), `test_render.py` (`test_claim_runs_reach_the_data_island_resolved`,
`test_a_claim_that_does_not_resolve_cannot_render`, and the browser test
`test_claim_runs_render_through_runs_renderer`) and the CP-1 preview browser test. The Front
Page shows no claims: pixel baselines are unchanged and were not regenerated. Rewrite
tournament on `resolve` (incumbent held) and `prose.issues` (readability challenger won: one
tokenization, no message-prefix test, issues in reading order).

Not verified: replay of the I2 probe corpus (target absent); live model output against the
grammar; the CP-0 method prompt (`methods/cp0.md`) does not yet teach run text, and changing
it is a model-facing change that needs E1/E2 evidence; the Markdown register preview
(`register_view`) still prints raw claim text, so CP-1 claims there show `[<fact id>]`
tokens; text facts reached by a chip are Python-held fact text, not checked by this rule.

Review fix round 1 (coordinator, real-text probe): three of the four `analysis[].text`
claims in probe-3's accepted GLM 5.3 Flash readiness output (`artifacts/model-tests/probe-3/`)
were rejected on label gaps. `LABELS` now also has SEC file numbers (`001-36629`) and
`Regulation 14A` (filing), plural `Items` with ranges and lists and `page N` / `pages N-M`
/ `N-page` (section), and a new `coverage` class for pack-coverage counts (`195 of 195`,
`195 pages`, `195 located spans`), which describe the Source Pack's structure, not the
issuer. Durations (`120 days`) and other bare counts (`195 located`, `1,200`) stay figures.
`test_probe_3_readiness_claims_pass_the_label_rule` pins the four probe texts; the table
rows add the probe shapes and the boundary rejects. The pack's own `page:N` locator form is
also a label (task 6.5 fix round); with the Caesars pack linked, `make replay` shows 63 `ok`,
the seven real-pack entries included.

Disclosures: (a) `deliver_cp0` raising at render is a deliberate backstop; the main path
settles a bad claim `rejected` through `candidate_issues`. (b) A stored `[E1]`-style token
parses as a chip and fails at render as unresolved, `[see note]` fails at parse as
malformed, and a stored module whose claims carry free figures no longer renders.
`N of N` admits any such pair ("2 of 3 covenants"), as page and section labels admit any
number after their word.

## 6.4 Envelope and handoff

Task `dvii-impl-m6-envelope`. Plan M6 6.4: the canonical Markdown envelope (r14 ordered
sections, `null` in the transport only), handoff verification, the reader, and CP-1 promotion
under the M4 status rules and the decision 0008 contract shape.

What changed:

- `envelope.py` (new): `Envelope` (`envelope/1`, the JSON sidecar: run, module, registers hash,
  gap-register limitations, QA report, journal inputs), `write_envelope`, `read_envelope`,
  `envelope_issues`, `handoff_issues`, `register_envelope`, `resolved_claims`. Section order is
  the r14 CP-1 "17-Section Output" (`CP-1_SCHEMA_REFERENCE.md`, pinned Deploy VI `bd71346`);
  the table placement, empty-section lines, cell spelling (`∅ G#`, never `null`), marker
  grammar, Evidence list and Provenance footer are in
  [canonical-tables.md](../../canonical-tables.md) "Canonical envelope".
- `cp1_quality.py`: the `canonical-handoff` slot is present when the register envelope
  round-trips and absent with the first issues otherwise (it was always absent). The register
  envelope has no QA section, since QA is computed from this slot.
- `cp1_workflow.py`: `cp1_registers`, `promote_cp1` (the QA review retained as a fifth step,
  `quality`, of the same attempt and budget), `CP1Handoff` (`cp1-handoff/1`, the step output)
  and `write_cp1_envelope`. A failed condition settles the attempt `rejected` (or `blocked` on
  the repair); it never promotes. `cp1_register_preview` shares the stage recomputation and
  reads the first four steps.
- `execution.py`: `Qualification` (the plan's four statuses) on `Head.qualification`, omitted
  from the JSON when absent so earlier heads keep their bytes (`execution/5` unchanged);
  `finish(..., qualification=)`; a blocked result never carries it.
- `execution_cli.py`: `cp1-quality-inputs`, `cp1-promote`, `envelope --module CP-1`.
- Carried from 6.2: `register_view` prints resolved claim text (`resolved_claims`), and
  `deliver_cp0` publishes a `rejected` delivery for claims that do not resolve instead of
  raising at render.
- Carried from 6.1: decision 0007's CP-MODEL line now states how 6.1 resolved the upstream
  edge; the coverage map's CP-MODEL label reads "task 6.5" (not "M6.5"), its adaptation list
  records DC-5, and the CP-1 row names this task.
- Carried from 6.3: `Partial`/`Conflicted` statuses still cap at Calculated; recorded as
  accepted (coordinator), unchanged here.
- Small refactors: `table_markdown.null_confusable` (the interface null-marker rule, shared by
  both writers), `canonical_tables.REGISTER_NOTE` (the register note promotion removes).

The contract comes from the sidecar (`envelope.json`); the Markdown is verified against it, not decoded.

Promotion conditions: CP-0 `Run CP-1`; the four stages valid and recomputing; the review binds
the current QA inputs and upgrades no ceiling; QA not `Blocked`; claims resolve; the
`canonical-handoff` slot present and the promoted envelope verifying. Settlement is decision
0007's: the fixture CP-1 settles `restricted` from its own register limitations. Promotion
adds only the `CP-1 QA <status>` line when QA did not pass, so `accepted` stays reachable.

Deviations from the brief:

- Edited outside the listed paths: `cp1_quality.py` (the slot lives there, not in
  `quality.py`), `canonical_tables.py` and `table_markdown.py` (constant and helper
  extraction, no behaviour change), `execution_cli.py`, `docs/development/product-cli.md`
  (`execution-cli.md` does not exist; the execution commands are documented there),
  `docs/decisions/0007-degradation-and-status-semantics.md` and
  `docs/methodology/r14-coverage.json` (the 6.1 carried items), and the tests
  `test_cp1_quality.py` (two assertions of the always-absent slot) and
  `test_narrative_projection.py` (its browser test asserted the raw claim text in the preview).
- r14's 17 sections have no Analysis H2; the findings open section 14, Evidence Trace.
- The QA review reaches the journal as a fifth step rather than a new CP-1 stage, so the live
  runner's four-step sequence is untouched.
- A data-driven QA `Blocked` (the partial fixture's blocked narrative) is refused like any
  failed condition, so it consumes the attempt and its repair before CP-1 settles `blocked`. A
  direct `blocked` settlement would change the M4 settlement rule; not done, flagged.

Evidence: `tests/product/test_envelope.py` (the 17 ordered H2s, absent and empty sections,
gap cells and sidecar nulls, resolved claims and the Evidence list, determinism by hash,
`test_read_of_write_is_the_envelope` (hypothesis), a changed digit, a dropped and a reordered
section, an unresolved marker, a footer hash, bare figures in Markdown and sidecar, an
unplaced table, gap-like known text, hostile titles, gap-like QA text, the fixture registers
round trip and a statement-cell tamper), `tests/product/test_cp1_workflow.py` (promotion,
the four statuses and export; lineage upgrade, unbound review, critical finding, blocked
narrative, failed and absent handoff, an unresolved claim, CP-0 not authorising, four stages
required, crash and resume, CLI), `test_cp1_quality.py` (slot present and absent with reason),
`test_execution.py` (head statuses omitted until recorded), `test_delivery.py` (rejected
delivery) and `test_register_view.py` (resolved preview text). Causal checks: the delivery,
register-preview, slot and hostile-title tests fail against the base code; the two
confidence-review tests failed before their fixes.

Reviews: confidence review fixed two defects (the promotion note made `accepted` unreachable;
the reader read gap-like QA text as markers). Rewrite tournament (inline, no subagents) on the
reader and on the promotion rule: the incumbent held both times; the speed challengers were
disqualified (one dropped the codec limits on the happy path, one changed the QA inputs hash).

Not verified: real Caesars packs (absent from the worktree, so `make replay` skips them as
`pack-absent`); envelope size and timing on a real-size pack (the fixture is 45k facts, 3.5 MB
Markdown, a 43 MB sidecar, about 22 s per promotion); the 20,000-row codec limit against real
gap counts; live model QA reviews; rendering of the envelope by downstream consumers; Linux CI.

## 6.5 CP-1 bindings

Task `dvii-impl-m6-cp1-bindings`. The accepted envelope drives the Model destination and
the Credit Snapshot blocks.

- Accepted route: `cp1_workflow.read_cp1_envelope(store, directory)` verifies an exported
  envelope against the journal (receipt file hashes, `read_envelope`, module hash equals the
  CP-1 head's `result_sha256`, run, prepared pack, status, QA report, qualification) and raises
  `EnvelopeRefused` with every issue otherwise. New `cp1_render.py`: `envelope_view`,
  `refused_view` (CP-1 blocked, issues as limitations, no values), `render_cp1_envelope`; CLI
  `execution render --envelope DIR --output DIR [--pathway P]` (see product-cli.md).
- FP 02: `ebitda-adjustments` (T4.17) and `metric-strip` (T4.10, S.1 to S.3 n/a frames) are
  second placements. `validate_bindings` now treats a fact as doubly bound only when two of its
  bindings name one block or two blocks the run's Pathway composes; `_unplaced` skips a second
  placement; `Unplaced.title` is exported.
- Presets: Credit Snapshot, Earnings Update, Relative Value and Portfolio Decision (each holds
  a `MODEL`-owned block by `_Spec.owner`) request CP-MODEL after CP-1 (decision 0009
  amendment). Covenant & Refinancing's maturity wall is MODEL-owned in the design but has no spec.
- Shell: the CP-1 page opens with a Model panel (CP-MODEL status; "Model not run" and no
  calculation JSON until M8); the rail dot also lights for unplaced bindings; the Limitations
  panel prints block titles.
- Statuses: CP-1 `implementation` -> implemented; CP-MODEL stays partial. The journal has no
  transition that sets a settled head's `rendering_acceptance`, so it stays `unrun`; the render
  receipt records it and `browser_acceptance: unrun`.
- Ripple: adding CP-MODEL to default Runs changed pack hashes and CP-0 consumer lists in
  fixtures. The shared synthetic Runs (`test_render.synthetic_view`, `test_financials.freeze`) are
  pinned to the previous set so the replay corpus and its hashes are untouched; other fixture
  assertions updated (`test_report_view`, `test_registry`, `test_credit_snapshot`).
- Baselines: none shifted (FP 01 fixture has no unplaced bindings or module limitations).
- Acceptance previews: `artifacts/rendering/m6-5/fp01-fixture-candidate.html` and
  `fp01-accepted-envelope.html` (untracked).

Deviations from the brief:

- Edited outside the listed paths: `contracts.py` (`_PRESETS`: CP-MODEL in four presets), new
  `cp1_render.py`, `execution_cli.py` (the `render` command), `docs/development/execution.md`
  and `product-cli.md` (`execution-cli.md` does not exist), new `test_cp1_render.py` and
  `test_cp1_bindings.py`, and the tests `test_report_view.py`, `test_registry.py`,
  `test_credit_snapshot.py`, `test_financials.py`, `test_execution.py`.
- `test_render.synthetic_view` and `test_financials.freeze` pin the pre-6.5 `requested_modules`
  (no CP-MODEL): the default Run now includes it, which changes the synthetic pack hashes the
  replay corpus records and the CP-0 consumer lists fixtures build from `plan(...)`.
- CP-5 consequence: in the four presets CP-5 cannot begin until CP-MODEL has a head
  (`test_cp5_cannot_begin_while_a_requested_cp_model_has_never_run`).
- `rendering_acceptance` is not set: the journal has no transition that changes a settled
  head's statuses; the render receipt records it as it stands.

Not verified: a live CP-1 render (none accepted yet; M7); `rendering_acceptance` on a real
head; Linux baselines.
