# Adversarial review: architecture, system design and implementation plan

Date: 21 October 2026. Base: `main` at `7526dbc` (worktree
`claude/deploy-vii-adversarial-review-a78eab`, clean). Review only: no product code,
plan or settings changed. Personas: Saboteur (breaks it in production), New Hire
(must extend it in six months), Security Auditor (trust boundaries). A finding
raised by two or more personas is promoted one severity level.

**Scope.** `CLAUDE.md`; `docs/development/CONTEXT.md`; `docs/architecture.md`;
`docs/methodology-adaptation.md`; `docs/development/tasks/implementation/brief.md`;
`docs/frontend-direction-c.md`; `docs/model-matrix.md`; decisions 0002 and 0003;
`settings/project.toml`; `docs/methodology/r14-coverage.json`; `src/deploy_vii/`
(`render.py`, `registry.py`, `execution.py`, `cp1_workflow.py`, `quality.py`,
`contracts.py`, `cp1_quality.py`, `narrative.py`, `canonical_kpis.py`,
`assets/{app.js,app.css,tokens.css,shell.html}`); `design/reference/`; selected
tests. Requirements: the two Codex chats (`cx_6ad862a7…`, `cx_6ad86302…`), read in
full in the browser. Design: claude-design project `1611c8f7…` (RBOT Report
application design), Direction C and design-system files only.

**Verdict: BLOCK.** Three critical findings must be resolved in the plan before the
canonical envelope, CP-1A and D–H proceed. Local gates are green, but they test the
deterministic substrate against hand-written synthetic payloads; they do not test the
plan's two load-bearing assumptions: that models can satisfy these contracts, and
that the renderer produces Direction C.

Requirements used as the yardstick (from the chats unless noted):

- R1 "Build Deploy VII in phases, delivering a working core credit report first, then
  completing the r14 methodology."
- R2 Model-assisted tests randomly select Luna, GLM 5.3 Flash or latest DeepSeek at
  high/xhigh; store outputs, metrics and telemetry. The model runner enforces the
  US$50 cap "through conservative request reservations and persisted accounting";
  a native Luna agent is the backup when OpenRouter credit runs out.
- R3 "Frontend – still look like Direction C, with each completed module in testing
  populating their relevant fields of HTML to test rendering accuracy and design."
  Milestone A completion: "Offline shell matches the attachment and displays honest
  unrun states." Milestone B: "Real readiness output populates the header, Evidence
  and Limitations panels."
- R4 "One targeted repair attempt per failed module; persistent failures remain
  visibly restricted or blocked."
- R5 "New judgments and calculations invalidate and refresh affected core views
  correctly" (milestone E completion).
- R6 Python owns arithmetic; models supply evidence-grounded analysis (CLAUDE.md:45-46).
- R7 FFO interest coverage = (FFO + cash interest paid) / cash interest paid (user
  answer, chat 1). DCF remains unanswered.
- R8 Use the model matrix; tournaments only in key areas (chat 1; CLAUDE.md:50-56).

---

## Critical findings

### C1. Twenty increments of model-facing contracts, no model runner and no live probe

*Personas: Saboteur, New Hire (promoted from WARNING).*

**Evidence.**
- `settings/project.toml:6` `live_model_runner_implemented = false`; OpenRouter spend
  is US$0 of US$50 (`brief.md:101`, `brief.md:276-277`, `brief.md:363`).
- The brief's milestone list (`brief.md:55-74`) has no model-runner item. The adopted
  plan's "Model runner" section (eligibility resolution, uniform draw with recorded
  seed, pinned DeepSeek version, reservation-based US$50 cap, matched comparisons)
  appears nowhere as a deliverable with acceptance criteria. The backup-agent rule
  is recorded only as a constraint (`brief.md:36-37`).
- Every remaining milestone consumes model output: CP-1's four steps
  (`cp1_workflow.py:37`), CP-1A, D–H.
- The CP-1 payloads were designed without ever meeting a model. Measured JSON
  schemas: `FinancialSubmission` 30 nested types, 232 properties, 32 KB;
  `SourceContextReview` 52 properties; `NarrativeReview` 28; `DownstreamReview` 15.
  All are `strict=True`, `extra="forbid"` (`contracts.py:17`).
- The repair budget is one per module and is shared by all four CP-1 steps
  (`execution.py:66`, `execution.py:301-302`, `execution.py:463-476`). Any invalid
  step finishes the attempt.
- `narrative.py:40-43` rejects any numeric character in prose. `FY2025`, `Q2`,
  `10-K`, `2032 notes` and `Term Loan B-1` cannot appear in a sentence (see W5).

**Violated requirement / risk.** R1, R2. The plan proceeds to harden the envelope,
CP-1A and D–H on top of contracts whose first-pass validity with Luna, GLM 5.3 Flash
or DeepSeek is unknown. If a model fails two of the four CP-1 steps on the frozen
Caesars pack, CP-1 is permanently blocked for that input set. C2 then shows that a
blocked module stops the whole report. The likely first real run therefore produces
no report, with all the cost already spent.

**Correction.** Insert milestone **R (model runner and live probe)** before the
canonical envelope:
1. Build the OpenRouter adapter to `docs/testing-and-telemetry.md`: eligibility
   check, recorded seed and draw, pinned versions, a reservation ledger persisted
   before dispatch, and raw request/response/usage retention under `artifacts/`.
   Add the native-Luna backup as a separate host cohort.
2. Treat source text as data in every prompt: delimit it, give the model no tools,
   and never place source text in an instruction position.
3. Run a capped probe of US$5–10 of the US$50: CP-0 plus CP-1 `source_context` and
   `financials` on the frozen Caesars pack, three draws per model. Record first-pass
   validity per step and the issue classes found.
4. Let that evidence reshape the contracts. Python should pre-fill every
   mechanically derivable field so the model supplies only judgments. Split the
   single 232-property submission. Give each step its own repair budget, or keep
   the module-wide budget only after measurement shows it is survivable.

Acceptance: a recorded batch whose per-step validity rates, cost, latency and
failure classes are in the brief. Without that evidence, no further CP-1 contract
work proceeds.

### C2. One blocked module halts CP-3, CP-5 and CP-6, and run scope is immutable

*Personas: Saboteur, New Hire (promoted from WARNING).*

**Evidence (reproduced).** A scratch probe using the repository's own test fixtures
(`tests/product/test_execution.py:15-49`) on the default run scope
(`contracts.py:31-40`): CP-0, CP-1, CP-1A and CP-2 settled `restricted`; CP-4 was
driven to `blocked` after its one repair. Result:

```
CP-3 NOT runnable: Required upstream is unrun, stale or blocked
CP-5 NOT runnable: Required upstream is unrun, stale or blocked
CP-6 NOT runnable: Required upstream is unrun, stale or blocked
```

Cause:
- `registry.py:43-46` turns a *selected* optional producer into a hard requirement.
- `registry.py:48-50` makes CP-5 require every selected analyst.
- `execution.py:91-95` refuses to start unless every requirement is
  `accepted`/`restricted`.
- `execution.py:490-491` forbids changing run scope ("create a new execution"), so
  CP-4 cannot be deselected.

**Violated requirement / risk.** R4: persistent failures must remain *visibly*
blocked. Here they silently remove every downstream module. The method record says
"Supply that context or explicitly limit the CP-2 result"
(`docs/methodology-adaptation.md:39-41`). The design system's call-band state C
shows "CP-3D Blocked · spread curve not drawn" alongside populated modules, and its
blocked-module block keeps tables with critical cells shown as "—". The most likely
real outcome (CP-3D with no market data, or CP-4 without indentures) yields no
report.

**Correction.** Record a decision and implement it with tests:
1. A blocked *optional* producer is recorded in its consumers' inputs as a
   blocked-status input (hash plus status). The consumer runs and inherits an
   explicit limitation.
2. A blocked *required* producer either blocks the consumer or, where the method
   allows (CP-1A before CP-2), runs it `restricted` with a mandatory limitation.
   Encode which rule applies per edge in `methodology.json`.
3. CP-5 always runs over the selected set and reports blocked analysts as findings.
4. Add a regression case that reproduces the probe above.

This touches execution ordering, so a scoped rewrite tournament applies (R8).

### C3. The frontend is built against a superseded reference and renders register dumps, not Direction C fields

*Personas: New Hire, Saboteur (promoted from WARNING).* Detail is in the Frontend
section below.

**Evidence.**
- The repository pins `design/reference/direction-c-workbench.dc.html` at 127,349
  bytes, SHA-256 `bcd9dec9…` (`design/reference/README.md:3-7`; decision 0002 row
  "Frontend", `docs/decisions/0002-development-environment.md:25`). That is
  byte-for-byte the design project's `Direction C - Workbench.dc.html` (127,349
  bytes). The project's index, `RBOT Report.dc.html`, calls it the "Earlier phase:
  Direction C exploration". Phase 2 is `RBOT Design System.dc.html` (DS-01–DS-07)
  plus six Pathway Front Pages. DS-01 says the components are "specified so a Python
  template can render them from variable run data".
- `tokens.css` is Deploy VI's report-app file, "Preserved … byte-for-byte"
  (`tasks/implementation/shell-review.md:23`). It is not the design system's
  `--rb-*` tokens.
- `assets/app.js:83-140` renders every module as generic panels of its registers.
  `app.js:141-155` renders a static overview. There is no binding map anywhere in
  `src/`, `tests/` or `docs/` beyond the requirement text
  (`docs/frontend-direction-c.md:41-44`). There are no charts, no provenance marks
  and no gap IDs, and missing values print "null" (`render.py:35-37`).

**Violated requirement / risk.** R3. Milestone A is ticked (`brief.md:61-62`), but
its completion condition is not met even against the phase-1 file. That file
already has cited and calculated glyphs, Pass and With-limitations status marks, a
sticky call band and a source passport, none of which the shell has. Because the
renderer has no Direction C fields, "each completed module populating its relevant
fields" cannot be tested for any module. Every module integrated from now on adds
rework.

**Correction.** Insert milestone **A′ (design-system re-baseline)** before the CP-1
envelope is bound to the view. Do it in parallel with R, since they write disjoint
files. Concrete steps are in the Frontend section; acceptance is at the end of it.

---

## Warnings

### W1. Status collapse: "Pass" is unreachable downstream of any gap

*Personas: Saboteur, New Hire.*

- `execution.py:204-221`: a candidate becomes `restricted` if it has *any*
  limitation. That includes every limitation inherited from any input and the
  synthetic-case label. In the C2 probe, CP-1, CP-1A and CP-2 all settled
  `restricted`.
- `cp1_quality.py:142` hard-codes `module_status="restricted"` unless blocked.
- `quality.py:191-196` caps every restricted module at 59, which is band "Low" at
  best.
- A real CP-0 almost always carries gaps, so every module and every confidence band
  converges on With limitations/Low.

**Risk.** The design's Pass / With limitations / Blocked vocabulary (DS-02, DS-07)
and the confidence score lose their information. A reader cannot tell a module with
its own material defect from one that merely inherited a footnote.

**Correction.** Separate `own_status` (from the module's own validator findings and
material gaps) from `inherited_limitations` (displayed, de-duplicated by gap ID).
Downgrade only when a material inherited gap affects a bound field. Record the rule
in `docs/methodology-adaptation.md`. Execution state is in scope for a key-area
tournament.

### W2. QA evidence quality (60% of the score) is a model assertion

*Personas: Security Auditor.*

`quality.py:110-121` and `quality.py:169-174` take each claim's lineage class
("Directly Sourced" = 10 … "Untraced" = 0) from the analyst, which is the model.
`docs/development/quality.md` confirms "the analyst supplies … lineage class".
Python already knows the provenance of every evidence ID it produced: a citation, a
calculation, a gap.

**Risk.** A model, or a prompt injected through a source document it read, can
classify every reference as Directly Sourced and lift the score. That moves a
judgment Python could verify into the model, contrary to R6.

**Correction.** Python derives the lineage ceiling for each evidence ID from the
register that produced it: cited → Directly Sourced, calculation → Calculated,
gap/missing → Insufficient Information. The model may only downgrade, with a
rationale. Add a test where an upgrade attempt is rejected.

### W3. Run scope is immutable and nothing is reused across executions

*Personas: Saboteur, New Hire.*

`execution.py:490-491` rejects any run change, and `execution.py:239-246` starts
empty. There is no import of accepted heads from another execution.
`registry.py:43-46` resolves optional dependencies once, from the immutable request.

**Risk.** Milestone E's completion condition (R5), "invalidate and refresh affected
core views", cannot be exercised: adding CP-1B to a finished core run means rerunning
and re-paying CP-0 to CP-6. That inverts the architecture's own rationale ("caching …
validated artifacts, then rerunning only invalidated consumers",
`docs/architecture.md:29-31`) and multiplies cost against the US$50 cap.

**Correction.** Allow scope *extension* as a journal transition. The new requested
set must be a superset. Recompute dependencies, and mark stale only those accepted
heads whose resolved inputs change. Alternatively, allow a new execution to import
accepted heads whose input hashes still match. Either way it is a key-area
tournament (execution ordering).

### W4. The execution journal rewrites the whole pack on every transition

*Personas: Saboteur.*

`execution.py:266-287` serializes and fsyncs the full `ExecutionSnapshot`: the
complete `PreparedPack` with every source span, plus every attempt payload. It does
this on each `begin`, each step submission (twice: `execution.py:448`,
`execution.py:477`) and each `finish`. `snapshot.content_hash()` re-serializes the
whole snapshot for each `parent` (`execution.py:314`, `:349`, `:372`).
`current_inputs` hashes the whole pack on every call (`execution.py:112`). The brief
already lists "large-pack transport qualification" as pending (`brief.md:333`).

**Risk.** Storage and CPU grow with transitions × pack size. A real core pack
(10-K, 10-Qs, credit agreement, indentures) is tens of MB, and a core run makes
dozens of transitions. Not measured here.

**Correction.** Before the first real-pack run, store the pack and each payload once
as content-addressed blobs and reference them by hash from small snapshots. Measure
with the hash-pinned Caesars filing before and after.

### W5. The numeric-prose rule is too strict for CP-1 and absent for every other module

*Personas: Saboteur, Security Auditor.*

- `narrative.py:40-43` rejects any `isnumeric()` character in CP-1 prose. Periods,
  filings, tranche names and section numbers become impossible in a sentence.
  Combined with the shared one-repair budget (C1), this is a likely way to burn the
  budget.
- Conversely, the generic `Claim.text` used by every other module is unconstrained
  free text (`contracts.py:136-140`), and `app.js:91-99` renders it verbatim. From
  CP-1A onward a model can therefore write numbers that no fact backs, contrary to
  R6 and `docs/architecture.md:82-83`.

**Correction.** Generalize the design system's prose "runs" pattern. Model text
references figures as `{C19|US$ m}` and gaps as `[G8]`; Python resolves and formats
them (design `lib/vm-fp.js` `prose().runs`). Allow non-figure tokens such as
periods, document types and instrument names. Reject any numeric token that is not
a resolved reference. Apply this to `Claim` for every module, not only CP-1.

### W6. Field-parity evidence is circular, and one record is hard-coded

*Personas: New Hire, Saboteur.*

- Parity tests use the renderer's own formatter as the oracle:
  `tests/product/test_report_tables.py:288` (`to_have_text(table_display(fact))`),
  `test_register_view.py:126` and `test_interface_view.py:92`.
- `tests/product/test_browser.py:62` writes `"field_parity": "passed"` as a literal
  after checking one cell (`:43`, expecting `"0.00"`).

**Risk.** `docs/frontend-direction-c.md:69-71` requires parity of value, sign, period,
currency, scale, rounding, denominator, status and citation *against the source
artifact*. A formatting regression that agrees with itself passes, and the
retained evidence claims parity that was never computed.

**Correction.** Write an independent oracle from the design system's display rules
(DS-04: thousands separators, negatives in parentheses, `x`, `%`, `pp`, scale in the
block head, `∅ G#`, `n.m.`, `—`). Compute the parity record by comparing every bound
cell, and fail closed.

### W7. Milestone acceptance drifted and coverage tracking is stale

*Personas: New Hire.*

- A and B are ticked as "implementation" (`brief.md:61-64`), but the adopted plan's
  completion conditions (R3) are not recorded anywhere.
- B's condition, "real readiness output populates the header", is unmet: CP-0 output
  is synthetic and `restricted` (`brief.md:107`), and the Caesars filing is only
  hash-pinned (`brief.md:254-255`). The header shows `run.issuer_name`, not
  readiness (`app.js:202-203`).
- `docs/methodology/r14-coverage.json` lists all 25 owners as
  `"implementation": "unrun"` (`:37`, `:75`, …), although CP-0 and much of CP-1 exist.

**Correction.** Put each milestone's adopted completion condition into the brief as
acceptance. Track the four statuses (implementation, analytical, rendering, native)
per milestone. Update the coverage map in the same commit as each owner's code.

### W8. Sequencing: CP-1 depth before a vertical slice

*Personas: New Hire (ponytail lens).*

`src/deploy_vii` is 16,185 lines across about 54 modules. Almost all of it is CP-1
substrate: reconciliation (783 lines), canonical tables (881), period
reconciliation (546), audit (601), gaps (493), FX, cash and equity bridges. It has
had repeated schema bumps that reject old stores with no migration
(`brief.md:289-302`, `brief.md:316`). None of it has been exercised by real model
output or a real pack. R1 asks for a working core report *first*.

**Risk.** Contracts for CP-1A to CP-6 will be designed against a CP-1 shape that the
first live run (C1) may force to change, compounding the rework.

**Correction.** Freeze CP-1 internals after R and A′. Build the thinnest end-to-end
slice from CP-0 to CP-6, rendering one Credit Snapshot Front Page, on the Caesars
case. Then deepen. The remaining CP-1 items (envelope, QA wiring) go into that
slice, not ahead of it.

### W9. FFO interest coverage was answered but still reports "awaits an explicit definition"

*Personas: Saboteur.*

`canonical_kpis.py:135` still holds "FFO interest coverage formula awaits an explicit
definition", and `canonical_kpis.py:474` emits "DCF and FFO interest coverage
definitions remain unresolved" into output. The user's answer (R7) is recorded at
`brief.md:158-162`.

**Risk.** Every CP-1 artifact now carries a false limitation, and the row stays
unavailable.

**Correction.** Small `dv-sensitive` increment, test-first: (FFO + cash interest
paid) / cash interest paid. It needs a cash-interest-paid operand with provenance,
and a zero or missing denominator stays a gap. Keep DCF unavailable and correct the
limitation text.

### W10. CP-MODEL's artifact and ordering are undecided

*Personas: New Hire.*

- In `src/deploy_vii/methodology.json:608-617`, CP-MODEL requires only CP-0, yet its
  purpose is "from accepted upstream handoffs".
- `registry.py:50` excludes it from CP-5's scope.
- r14's artifact is an XLSX workbook with seven sheets
  (`r14-coverage.json:763-775`).
- `docs/architecture.md:57-60` records that the comparison method required MODEL
  before CP-2 and CP-3.
- Deploy VII computes the Model inside the CP-1 financial step
  (`cp1_workflow.py:102-108`).
- `docs/methodology-adaptation.md:28` leaves workbook output as an open "product
  choice".

**Correction.** Record a decision. Either CP-MODEL is a Python export from accepted
CP-1 (CP-1 required, inside CP-5's scope), or the XLSX is retired in favour of the
Model destination of the design system. Encode it in `methodology.json` and the
coverage map.

---

## Notes

- **N1.** `brief.md` is a 368-line changelog. The plan, acceptance and next step are
  scattered across it (next step at `:365-368`), and `CONTEXT.md:28-53` lists 26
  topic documents. Split it into a short plan (milestones, acceptance, sequencing,
  open decisions) and an append-only log.
- **N2.** `brief.md:47`, "Implementation is inline", predates decision 0003. CLAUDE.md
  routes implementation through the `dv-*` workers with coordinator integration.
  Update the line so the next session does not implement inline by default.
- **N3.** Portfolio Fit is a hard-coded route (`app.js:195`), not an owner in
  `methodology.json` (by decision, `r14-coverage.json` adaptation decisions). Give it
  a contract before milestone G, because the design makes it a rail destination and
  a call-band item.
- **N4.** `app.js:148` hard-codes "25 … responsibilities, including 16 alternate
  commands". Derive it from the registry so it cannot drift.
- **N5.** The CSP uses `script-src 'unsafe-inline'` (`shell.html:3`). That is
  acceptable for a single-file offline report because all data enters through
  `textContent` and `<` is JSON-escaped (`render.py:64`). Keep the hostile-text
  browser test as the guard.

---

## Frontend: Direction C + design system

Design files read: `RBOT FP 02 Earnings Update.dc.html` (in full),
`RBOT Design System.dc.html` (in full: DS-01 to DS-07 and its view logic),
`RBOT Report.dc.html`, `lib/shell.js` (in full), and the first 25 of 186 lines of
`lib/charts.js` and the first 40 of 100 lines of `lib/vm-fp.js`. Not read:
`RBOT FP 01` and `03`–`06`, `lib/vm.js`, `RBOT Direction C - Workbench.html` (555 KB
bundle), `data/`, `uploads/`.

### F1. Wrong normative reference (CRITICAL, part of C3)

Deploy VII's reference is the phase-1 exploration (`design/reference/README.md:3-7`).
The design project has since produced the system the plan should implement:

- tokens with contrast values (DS-01);
- provenance, status and scale marks (DS-02);
- three call-band states (DS-03);
- block anatomy and states, dense, key/value and period-grid tables (DS-04);
- twelve chart kinds including an n/a frame, each with a table twin (DS-05);
- one 16px SVG icon set (DS-06);
- navigation, search, inspector passports, and empty and gap states (DS-07);
- six Pathway Front Pages composed only from these components.

`docs/frontend-direction-c.md:7` still points at a `~/Downloads` copy.

**Change.** Adopt decision 0004: the design system and the six Front Pages are
normative, and the phase-1 file stays as history. Copy hashed snapshots of
`RBOT Design System.dc.html`, `RBOT FP 01`–`06`, `RBOT Report.dc.html` and
`lib/{shell,vm,vm-fp,charts}.js` into `design/reference/` with a provenance README.
Supersede the "Frontend" row of decision 0002.

### F2. Tokens (`tokens.css`, `app.css`, `render.py`) vs DS-01

| Area | Deploy VII (evidence) | Design system | Change |
| --- | --- | --- | --- |
| Token set | Deploy VI tokens, unprefixed (`tokens.css:16-56`) | `--rb-*` set incl. `--rb-head #F6F7FA`, `--rb-select #E7ECFF`, `--rb-ink-3 #9AA0B4`, `--rb-on-navy-2 #C7CBE0`, `--rb-blue-hover #0012B8` | Replace with the DS-01 block verbatim; drop ad-hoc literals (`#F7F8FB`, `#EEF0FF`, `#D7DBEE`, `#6478ff` in `app.css:1-2`) |
| Spacing | 4/8/12/16/24/32/40 (`tokens.css:42-48`); panel body 16px, cells `10px 12px` (`app.css:2`) | 4/6/8/10/12/18/24; panel padding 6/12; canvas gap 10; rows 24–26px | Adopt; current rows are about 38px, so far fewer rows fit above the 900px fold |
| Type | body 13px; h1 28px; panel head Display 16px; figures Mono 12/400 **left-aligned** (`app.css:1-2`, `.fact-value`) | page 20/700 Display; call 16/600; block head Text 11/600 caps .06em; body 13.5/1.5; labels 11.5/500; figures Mono 12/500 tabular **right-aligned**; tags 9.5/600 caps .08em | Adopt the type scale; right-align all figures |
| Embedded weights | Display 400/700, Text 400/500, Mono 400 (`render.py:43-49`), plus `local()` faces (`tokens.css:1-15`) | Weight 600 is the system's workhorse (heads, call items, totals, Mono 500/600 figures) | Embed Display 600/700, Text 400/500/600, Mono 500/600. Remove `local()` faces so rendering does not depend on what the reader has installed |
| Radii, motion, focus | single 2px radius; 140/220ms, `cubic-bezier(.16,1,.3,1)`; focus 3px `#6478ff` | 0 panels / 2 tags / 3 tiles / 4 nav; 120/180/260ms, `cubic-bezier(.2,.7,.2,1)`; focus 2px `#0017E5` offset 2; 24px minimum targets | Adopt |

### F3. Layout and shell (`shell.html`, `app.js`) vs FP 02 and DS-03/DS-07

- **Rail.** Five Unicode glyph links (`shell.html:7-14`). The design has six SVG
  destinations (Front Page, Analysis, Model, Portfolio Fit, Evidence, Limitations),
  each with an active 2px edge and status dot, plus search, "How to read a figure"
  and Print at the foot. "Financial model" currently routes to the CP-1 module page;
  the design has a separate Model destination.
- **Navigator.** Currently a text filter and module list. The design has: the logo;
  issuer, ticker, period and date; Pathway and depth; "/" search across modules,
  figures and sources; an "Analysis · N" tally with lim/pass chips; rows with
  plan-order number, family colour bar (`FAMC`/`FAMILY` in `lib/shell.js`), status
  icon and code; an "On this page" outline; and a "Not in this Pathway / Not run"
  footer.
- **Call band.** Currently static, overview only, titled "Assessment pending"
  (`app.js:141-146`). The design's band is sticky with a 56px minimum on every page.
  It holds Pathway-ordered items (scale tile plus 5-step meter, direction arrows,
  ∅ tile for N/A) and one-line facts whose figures are inline buttons and whose gaps
  are `∅ G#`. It has three states: populated, honest no-judgement, and
  not-in-Pathway or blocked (DS-03). The honest state replaces "Assessment pending".
- **Topbar.** `shell.html:20` spends a 58px row on a breadcrumb that the design does
  not have. Drop it, so the call and headline blocks sit above the 900px fold as in
  FP 02.
- **Canvas.** Currently one module per route. The design's Front Page is a two-column
  grid (gap 10) composing blocks from several owners. Each block links "Full analysis
  →" to the module page, where register detail belongs.
- **Inspector.** Currently a generic list of about 20 keys with "Not supplied" fillers
  (`app.js:69-80`). The design has typed passports (DS-07):
  - **Cited:** ID, label and period, value and unit as served, file with document
    icon, locator, excerpt, "Open in Evidence · Used in N places".
  - **Calculated:** formula plus clickable inputs.
  - **Synthetic:** a TEST DATA banner.
  - **Gap:** field, reason, "affects N figures".

  Around the passports are Source/Table/Key tabs, the table twin of the selected
  figure, "Not in this Pathway", "Steps not run", and the keyboard keys.

### F4. Components and states (DS-02, DS-04, DS-05, DS-07)

- **Provenance marks.** There are none in the shell. Every figure needs a cited,
  calculated or synthetic glyph before it, with shape and word, never colour alone.
  Model-written prose carries the pen tag.
- **Missing values.** "null" (`render.py:35-37`; adopted as spelling in
  `docs/development/model-interface.md:27`) contradicts DS-07. The design uses:
  - `∅ G#` with the reason on hover;
  - `∅ G41 n.m.` when not meaningful;
  - `—` for a blocked critical cell;
  - "Not evaluated: …";
  - an empty table hidden and listed under Limitations.

  `app.js:120` instead prints "No rows supplied for this register." Keep `null` in
  the r14 Markdown transport only.
- **Number formatting.** `display()` returns raw `Decimal` text (`render.py:28-31`;
  tests pin `"0.00"` and `"1E+1000000"`, `tests/product/test_render.py:107`,
  `test_report_tables.py:95`). The design uses `11,648 · (62) · 3.29x · 30.8% · pp`,
  with the scale stated once in the block head ("US$ m"). Add a Python display
  formatter keyed by unit class (amount, multiple, percent, percentage points, date,
  text), so Python still owns formatting.
- **Status vocabulary.** Internal enums (`accepted`, `restricted`, `stale`,
  `candidate`, `rejected`, `unrun`) are shown raw in mono tags (`app.js:12-16`,
  `contracts.py:13`). Map them to the design's words and icons:
  - accepted → Pass;
  - restricted → With limitations;
  - blocked → Blocked;
  - unrun → Not run;
  - out of scope → Not in this Pathway;
  - stale → clock plus "rerun required".
- **Blocks.** `panel()` holds only a title (`app.js:17-25`). The DS-04 anatomy is:
  title · owner code and figure ID · provenance tags · state word · "Full analysis →"
  · collapse. It must support the collapsed, condition-line, not-run, absent and
  blocked states.
- **Tables.** Add dense tables (provenance glyph per figure, subtotal rows on
  `#F6F7FA`, selected-cell 2px outline), key/value tables, and the Model period grid
  (column groups, tinted base column, greyed absent columns with reason, a basis tag
  per line).
- **Charts.** There are none. That makes "chart/table parity" (`brief.md:29-30`,
  `docs/frontend-direction-c.md:74-75`) untestable. Port the design's kit
  (`lib/charts.js`: line strip, grouped and stacked columns, waterfall, bullet,
  dumbbell, scatter, range strip, debt stack, n/a frame) with focusable marks and
  table twins.

  Lazier option: emit static SVG from Python, which is deterministic and
  snapshot-testable. That avoids porting React-based chart code to vanilla JS.

### F5. Rendering pipeline

**Design.** `data` (citations `C#`, calculations `K#`, gaps `G#`, blocks, pathways
with `nav`/`notRun`) → `vm.cell()`/`prose().runs` (inline `{C19|US$ m}` and `[G8]`)
→ a per-Pathway Front Page view model (`lib/vm-fp.js`) → chart kit → shell helpers
(`lib/shell.js`: `pg`, `chip`, `navRows`, `tally`, `outline`, `callItem`).

**Deploy VII.** `View` (modules → facts/tables/claims) → one JSON blob → `app.js`
builds generic DOM per module (`render.py:59-80`, `app.js:83-140`). It has no
report-wide ID namespace, so there are no "Used in N places" counts and no gap IDs on
cells. It has no Pathway, and no view-model layer between artifacts and DOM.

**Change.** Keep the sound parts: the Python-prepared view, single-file offline
output, `textContent`-only DOM and CSP. Add:

1. A typed **report view model** in Python mirroring the design's VM: `Pathway`,
   `CallItem`, `Line(runs)`, `Block(owner, fig_id, tags, state, rows | chart)`,
   `Cell(text, prov, ref_id, gap_ref)`, `Passport(kind)`, `ChartSpec` plus table twin.
   Use report-wide `C#`/`K#`/`G#` IDs and a reverse index.
2. Per-module **binding maps** (required by `docs/frontend-direction-c.md:41-44`,
   absent today): Fact coordinates → Block/Cell. A view-model validator rejects
   unbound or doubly bound facts.
3. **Pathway presets** (Credit Snapshot, Earnings Update, Relative Value, Covenant &
   Refinancing, Distressed & Restructuring, Portfolio Decision), each giving
   requested modules plus Front Page composition. Add "Not in this Pathway" as a
   status distinct from "Not run". `Run.requested_modules` (`contracts.py:31-40`)
   today has neither.
4. A vanilla renderer for those components only. Register dumps move to module
   "Full analysis" pages and Evidence.

### F6. Frontend plan changes and acceptance (milestone A′)

1. Land decision 0004 and refresh the references (F1).
2. Replace the tokens and font set (F2).
3. Rebuild the shell (rail, navigator, sticky call band with three states, typed
   inspector) from DS-03 and DS-07, against a synthetic fixture marked SYNTHETIC.
4. Python display formatter, report view model, binding-map validator and status
   mapping (F4, F5).
5. One Front Page end to end: Credit Snapshot (the default core run) or Earnings
   Update, populated from today's CP-1 candidate registers where bound, with every
   other block in its honest state.
6. Acceptance:
   - structural comparison against the reference Front Page (block order, heads,
     marks, states);
   - reviewed screenshot baselines at 1440×900 (fold) and 1280×800;
   - 125% and 200% zoom;
   - keyboard path through rail, navigator, figures, inspector and chart marks;
   - chart/table-twin parity;
   - an independent parity oracle (W6);
   - offline with no network requests.

   After A′, each module's rendering acceptance means "its bound Front Page blocks
   and passports populate correctly", not "its registers render".

---

## Recommended sequencing (pending your approval)

1. **W9:** FFO interest coverage implementation. Small, already decided.
2. **R (C1)** and **A′ (C3)** in parallel, on disjoint files: model runner plus a
   US$5–10 live probe; design-system re-baseline.
3. **C2 and W1:** blocked-propagation and own-vs-inherited status, as one
   execution-ordering decision plus a tournament.
4. **W4:** content-addressed journal blobs, measured on the Caesars pack.
5. **CP-1 canonical envelope and handoff,** bound to the Model destination and Front
   Page blocks, with W2 (lineage ceiling) and W5 (prose runs) in the shared contract.
6. **CP-1A,** then the thin core slice CP-2 → CP-4 → CP-3 → CP-5 → CP-6 to one
   rendered Credit Snapshot (W8). Then **W3** (scope extension) before E.
7. Decisions to record: W10 (CP-MODEL), Pathways (F5), DCF (still open).

## Summary

The deterministic substrate is careful work: exact arithmetic, hash-bound journals,
honest unrun states. But the plan is optimizing the part that is already strongest
while the three things R1 and R3 depend on are missing or wrong:

- live model output against these contracts (C1);
- a pipeline that survives a blocked module (C2);
- a renderer that implements the user's actual Direction C design system (C3).

The single most important change is to run the capped live probe before writing
more CP-1 contract code.

Not verified: live model behaviour against any contract (no calls were made); the
journal storage and CPU cost at real pack size (W4, inferred from code); CI (blocked
by GitHub billing); design files not read (`RBOT FP 01`, `03`–`06`, `lib/vm.js`, most
of `lib/charts.js` and `lib/vm-fp.js`, the 555 KB `RBOT Direction C - Workbench.html`
bundle); pixel rendering of the design pages (read as source, not rendered); whether
`devtools.workflow` checkpoints and handoffs have been used in practice; r14 SKILL.md
text beyond `r14-coverage.json` (the per-edge rules in C2 need it); coverage
percentage (the product suite was rerun during this review: 978 passed, exit 0;
coverage was not re-measured).
