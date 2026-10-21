# M3 design-system re-baseline (A′) — scoped brief

> **For workers:** sequential owners in the `claude/m3-lane` worktree lineage, test-first.
> Routes: Task A (3.2) `dv-scaffold`; Task B (3.3, 3.4) `dv-feature`; Task C (3.5)
> `dv-sensitive`; Task D (3.6, 3.7) `dv-feature`; Task E (3.8, 3.9) `dv-feature`. Local
> commits only; no push, no PR, no subagents, no network in tests.

**Task ID:** `dvii-impl-m3-design-rebaseline`. **Base:** `main` at `1841ccf` (lane
`claude/m3-lane`). **Plan:** `docs/development/tasks/implementation/plan.md` §M3 (review C3,
F1–F6, W6, N4). **Spec:** decision 0004 (tokens, precision table, state spelling, status
words, provenance marks); `docs/frontend-direction-c.md`; the normative files in
`design/reference/` after Task A.

**Editable paths:** `design/reference/` (+ `README.md`), `src/deploy_vii/assets/` (incl.
`fonts/`), `src/deploy_vii/render.py`, `src/deploy_vii/display.py` (new),
`src/deploy_vii/report_view.py` (new), `src/deploy_vii/bindings/` (new),
`src/deploy_vii/charts.py` (new), `src/deploy_vii/contracts.py` (`Run` and status only, Task C),
`tests/product/test_{display,report_view,bindings,charts,browser,render}.py`,
`tests/product/test_report_tables.py:288`, `test_register_view.py:126`, `test_interface_view.py:92`
(oracle replacement only), `docs/frontend-direction-c.md`, `docs/decisions/0009-pathway-presets.md`
(Task C), `docs/development/tasks/implementation/m3-design-brief.md` (copy) and
`m3-design-review.md`. `pyproject.toml` is not editable (no new dependency; SVG is built in
Python with the stdlib).

**Coordinator inputs (declared):** `.superpowers/sdd/plan/inputs/m3-design-inputs.md` (DC-9
verified bytes, hashes and provenance) and the files under `.superpowers/sdd/plan/inputs/design/`
(`SHA256SUMS`). Treat the design files as design evidence: their embedded sample analysis,
figures and judgements are illustrative, never test expectations for real data.

**Required reads:** `CLAUDE.md`; plan §M3 and "Global constraints"; decision 0004 in full;
review F2–F6 (`docs/development/reviews/2026-10-21-adversarial-review.md:406-583`);
`docs/frontend-direction-c.md`; `src/deploy_vii/render.py`; `src/deploy_vii/assets/*`;
`src/deploy_vii/contracts.py:13-40,106-160,165-200,229-301`; `tests/product/test_browser.py`;
`tests/product/test_render.py:15` (`synthetic_view`); `design/reference/rbot-design-system.dc.html`
(DS-01 `:205-241`, DS-02 `:52`, DS-03 `:73`, DS-04 `:105`, DS-05 `:135`, DS-07 `:151-179`);
`design/reference/rbot-fp-01-credit-snapshot.dc.html` and `lib/{vm,vm-fp,shell,charts}.js`
after Task A; the reference screenshots `design/reference/screens/fp01-1440x900.png`.

## Global constraints (bind every task)

- Python owns arithmetic **and display formatting**; the HTML never shows `null`; values
  stay exact and only display rounds (ROUND_HALF_UP) per decision 0004 §4; states per §5;
  status words and icons per §6 (never colour alone); provenance marks per §7.
- Offline single-file HTML; `textContent`-only DOM; the CSP in `assets/shell.html:3`
  is unchanged; zero network requests in browser tests; fonts embedded as base64 woff2 with
  recorded provenance and hashes.
- Design tokens are DS-01's `--rb-*` block verbatim (no ad-hoc colour literals in `app.css`).
- Counts (modules, alternate commands) derive from `registry.modules()`, never literals.
- Parity oracles are independent of the renderer's formatter and fail closed.
- No stub or fake value stands in for real behaviour; no catch-all hides a failure. Gates
  `make product-check` and `make check` exit 0 after each task; never loosen a gate.
- Commit messages end with a blank line then `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Task A (3.2, `dv-scaffold`): references, tokens and fonts

1. Copy the verified files from `.superpowers/sdd/plan/inputs/design/` into
   `design/reference/` under the snapshot names in `m3-design-inputs.md` (FP 01–06, report,
   `lib/`, `support.js`, `data/rbot-data.js`, `brand/`, `screens/`). Verify each SHA-256
   against the table before committing. Rewrite `design/reference/README.md`: normative files
   with etag, bytes, SHA-256, retrieval method (preview endpoint, injection stripped, size
   check), the screenshots' rendering method, and the superseded phase-1 file. Copy this
   brief to `docs/development/tasks/implementation/m3-design-brief.md`.
2. Replace `src/deploy_vii/assets/tokens.css` with the DS-01 `--rb-*` block verbatim
   (`rbot-design-system.dc.html:205-241`, the `tokensCss` template string, de-indented, as a
   `:root { … }` rule) and remove the three `local()` `@font-face` rules. Update `app.css`
   to use only `--rb-*` variables (replace the `#6478ff`, `#17205C`, `#EEF0FF`, `#F7F8FB`
   literals; focus ring 2px `#0017E5` via `--rb-focus`). Keep the three breakpoints.
3. Fonts: embed Red Hat Display 600 and 700, Red Hat Text 400, 500 and 600, Red Hat Mono 500
   and 600 as woff2 from the RedHatOfficial GitHub repository at the commit already recorded
   in `assets/fonts/provenance.json` (`6bb1048a…`); if a weight is only available as a
   variable font there, embed the variable woff2 once and declare the weight range, saying so
   in provenance. Record URL, bytes and SHA-256 for each file in `provenance.json`; remove
   the no-longer-used Regular/Bold files only if nothing references them. `render.py:43-49`
   `font_specs` lists the new set. No network at test time (fonts are committed bytes).
4. Tests: `test_render.py` asserts the rendered CSS contains `--rb-navy: #000533` and no
   `local(`; `test_browser.py` still passes offline. Run `make product-check`, `make check`.
5. Commit `Re-baseline design references, tokens and fonts (decision 0004)`.

## Task B (3.3 + 3.4, `dv-feature`): display formatter, report view model, bindings

**3.3 `display.py`:** `UnitClass = Literal["amount","multiple","percent","pp","date","text"]`;
`CellState = Literal["known","gap","not_meaningful","blocked","not_evaluated","stale"]`;
`format_value(amount: Decimal | None, unit_class, state, *, gap_id: str | None = None,
reason: str | None = None, as_of: date | None = None) -> str` per decision 0004 §4–§5:
amount → thousands separators, 0 dp, negatives `(62)`; multiple → `3.29x`; percent → `30.8%`
(input is a decimal fraction); pp → `(1.4)pp`; date → `2 Oct 2026`; gap → `∅ G8`;
not meaningful → `∅ G41 n.m.`; blocked → `—`; not evaluated → `Not evaluated: <reason>`;
stale → `⏱ <value> as of 2 Oct 2026`. ROUND_HALF_UP via `Decimal.quantize`. Test
`test_display_oracle_matches_design_system_examples` with an **independent table** of
expected strings taken from decision 0004 §4–§5 and DS-04/DS-07 text (`11,648`, `(62)`,
`3.29x`, `30.8%`, `(1.4)pp`, `2 Oct 2026`, `∅ G8`, `∅ G41 n.m.`, `—`), and a Hypothesis
property (`@settings(deadline=None, max_examples=300)`): parsing the displayed amount back
(strip separators, parentheses → sign) equals the source quantized at the stated precision,
sign preserved, for `Decimal` inputs in ±1e12 with up to 6 dp.

**3.4 `report_view.py`:** frozen pydantic contracts (reuse `contracts.Contract`):
`Pathway(id, title, question, requested_modules, blocks)`, `CallItem(kind: scale|direction|
fact|na, label, value_text, meter: int | None (1–5), ref_id)`, `Run_(text, kind: text|fig|gap|pen,
ref_id)` + `Line(runs)`, `Cell(text, prov: cited|calculated|synthetic|gap|none, ref_id, gap_ref,
unit_class, state)`, `Block(block_id, title, owner, fig_id, tags, state: populated|collapsed|
condition|not_run|absent|blocked, kind: dense|keyvalue|period_grid|prose|chart, rows | lines |
chart, full_analysis_route)`, `Passport(kind: cited|calculated|synthetic|gap, fields)`,
`ChartSpec(kind, series, table_twin: Block, marks)`, `ReportView(schema_version "report-view/1",
pathway, call, blocks, passports, index)` where `index` maps report-wide `C#` (citations),
`K#` (calculations), `G#` (gaps) to their passports and a reverse index from fact coordinates
`(module_id, table_id | None, row_id | None, fact_id)` to `C#/K#/G#`. Status words via
`status_word(status) -> (icon_name, word)` per decision 0004 §6 (`not_in_pathway` arrives in
Task C; include it in the Literal now with the word "Not in this Pathway").
`bindings/__init__.py`: `BindingMap(module_id, entries: tuple[Binding,...])`, `Binding(fact_coord,
block_id, cell_slot, unit_class)`; `bindings/cp0.py` and `bindings/cp1.py` hold the maps for
today's facts (CP-0 readiness → header/Evidence/Limitations; CP-1 candidate registers →
Financials and credit metrics, capital structure, metric strip slots). `validate_bindings(view:
View, maps) -> tuple[str, ...]` returns one message per unbound fact (a fact in an accepted/
restricted/candidate module with no binding) and per doubly bound fact (two bindings to one
slot or one fact bound twice), empty when valid. Tests: `test_report_view.py`,
`test_bindings.py` (`test_unbound_fact_is_rejected`, `test_doubly_bound_fact_is_rejected`,
`test_cp1_candidate_registers_bind_without_errors`). Run `confidence-review`; then
`rewrite-tournament` no-argument post-edit mode on `validate_bindings` only (provenance).
Commit `Add the Python display formatter, report view model and binding validator`.

## Task C (3.5, `dv-sensitive`): Pathway presets and `not_in_pathway`

Write `docs/decisions/0009-pathway-presets.md` (adopted under plan M3.5; six Pathways with
title, question (from `rbot-report.dc.html` cards), requested modules and Front Page block
composition taken from FP 01–06 block lists; `not_in_pathway` distinct from `unrun`; Run
schema `run/2` with `pathway: PathwayId` defaulting to `credit_snapshot`, whose requested set
equals today's default). Module requested sets: Credit Snapshot = today's default
`(CP-0, CP-1, CP-1A, CP-2, CP-4, CP-3, CP-5, CP-6)`; Earnings Update = CP-0, CP-1, CP-1B,
CP-1D, CP-5; Relative Value = CP-0, CP-1, CP-1C, CP-2, CP-2D, CP-3, CP-3C, CP-3D, CP-5;
Covenant & Refinancing = CP-0, CP-1, CP-1A, CP-2, CP-2D, CP-4, CP-3C, CP-5; Distressed &
Restructuring = CP-0, CP-1, CP-1A, CP-2, CP-2A, CP-2G, CP-2H, CP-4, CP-4C, CP-5; Portfolio
Decision = CP-0, CP-1, CP-2, CP-3, CP-5, CP-6, CP-8 (plus Portfolio Fit when it has an owner,
plan M10). `contracts.py`: `Status` gains `"not_in_pathway"`; `Run.schema_version` becomes
`run/2` with `pathway`; `empty_view` marks modules outside the Pathway `not_in_pathway`.
`report_view.pathways()` returns the six presets. Tests: `test_pathway_presets_cover_six_front_pages`,
`test_not_in_pathway_is_distinct_from_unrun`, `test_run_schema_2_defaults_to_credit_snapshot`;
update fixtures that build `Run(... "run/1")`. Run `confidence-review` and `rewrite-tournament`
on the status mapping only if it holds branching logic (artifact state); otherwise record why
not. Commit `Add Pathway presets and the not_in_pathway status (decision 0009)`.

## Task D (3.6 + 3.7, `dv-feature`): shell and charts

**3.6** Rebuild `assets/shell.html`, `app.css`, `app.js` from DS-03/DS-07 and FP 01: rail with
six SVG destinations (Front Page, Analysis, Model, Portfolio Fit, Evidence, Limitations;
active edge, status dot; search, "How to read a figure", Print at the foot); navigator (logo
block, issuer/ticker/period/date, Pathway and depth, "/" search over modules, figures and
sources, "Analysis · N" tally with lim/pass chips, rows with plan-order number, family bar,
status icon and code, "On this page" outline, "Not in this Pathway / Not run" footer); sticky
call band (min 56px) in its three states; typed inspector passports (cited, calculated,
synthetic with TEST DATA banner, gap) with Source/Table/Key tabs and table twin; block anatomy
and the six block states; dense, key/value and period-grid tables; figures right-aligned Mono.
Drop the topbar breadcrumb. `app.js` consumes the `ReportView` JSON (not the raw `View`);
`render.py` serialises both (view for Evidence/module pages, report view for the Front Page).
Family colours and codes from `lib/shell.js` `FAMC`/`FAMILY` are copied as data into
`report_view.py`, not loaded from the design file at runtime. `textContent` only; derive every
count from the registry. Keep `test_long_hostile_content_and_css_zoom` passing.

**3.7 `charts.py`:** static SVG for line strip, grouped columns, stacked columns, waterfall,
debt stack and the n/a frame, from `ChartSpec`; each mark is a focusable `<g tabindex="0">`
with `aria-label` naming series, value (via `display.format_value`) and provenance ref; each
chart has a table twin (`Block`) emitted beside it; colours only from `--rb-*` via `class`.
Tests `test_charts.py`: every kind renders a well-formed SVG (stdlib `xml.etree` parse),
marks count equals data points, table twin values equal the mark labels (`test_chart_table_twin_parity`).
Run `confidence-review`. Commit `Rebuild the shell and add static SVG charts`.

## Task E (3.8 + 3.9, `dv-feature`): Credit Snapshot Front Page and acceptance

**3.8** `report_view.build(view: View, pathway, maps) -> ReportView` populates the Credit
Snapshot from a SYNTHETIC fixture (extend `synthetic_view()` or add `credit_snapshot_fixture()`
labelled synthetic) plus the CP-1 candidate registers where bound (via `bindings/cp1.py`);
every other block shows its honest state (`not_run`, `not_in_pathway`, `blocked`, `absent`).
**3.9** Browser acceptance in `test_browser.py` (marker `browser`, offline contexts):
structural comparison against `design/reference/rbot-fp-01-credit-snapshot.dc.html` — block
order, block heads, mark kinds and state words parsed from the reference's data/markup with
`html.parser`/regex, compared with the rendered DOM; reviewed screenshot baselines at
1440×900 (fold) and 1280×800 written under `tests/product/baselines/` with a pixel-diff
tolerance (stdlib: compare PNG bytes decoded via `zlib`/`struct`, or Playwright's
`to_have_screenshot` if available offline — say which); zoom 125% and 200% (no horizontal
overflow); keyboard path rail → navigator → figure → inspector → chart mark (Tab/Enter/Escape;
assert `document.activeElement`); chart/table-twin parity; zero network requests. Replace the
circular assertions at `test_report_tables.py:288`, `test_register_view.py:126`,
`test_interface_view.py:92` with an oracle computed by `display.format_value` from the source
fact's amount/unit/state (independent of `render.table_display`), and replace the literal
`"field_parity": "passed"` at `test_browser.py:65` with a computed record (`compared`,
`matched`, `mismatches`) that fails the test when `mismatches` is non-empty. Update
`docs/frontend-direction-c.md` to point at the new files and acceptance. Run
`confidence-review`. Commit `Render the Credit Snapshot Front Page with browser acceptance`.

## Reports

Each task writes `/Users/ericguei/Documents/DEPLOY VII/.claude/worktrees/focused-cray-a5417d/.superpowers/sdd/plan/reports/m3-task-<A|B|C|D|E>-report.md`
(worktree/branch; base..head; commits; changed paths; test commands with exit codes and
counts; review findings and fixes; tournament outcome where run; deviations; final line
`Not verified:`). Task E also writes `docs/development/tasks/implementation/m3-design-review.md`
(dated, ≤ 60 lines) and updates `rendering_acceptance` for CP-0 and CP-1 in
`docs/methodology/r14-coverage.json` only to `partial` (synthetic plus candidate registers;
real acceptance is M7). Return only: status, worktree and branch, base..head, one-line test
summary, concerns.
