# CP-1 canonical register candidate

`canonical_tables` recomputes the source, financial, definition, narrative and
consumer-readiness pipeline from external contracts. Its immutable
`canonical-tables/2` report binds those results, statement history, Model interface
and a candidate Module. `validate_canonical_tables` recomputes from the caller's
external inputs and compares content hashes, including exact decimal precision.
It does not authenticate a report against its own embedded inputs.

The candidate contains all 18 required r14 table IDs (T4.1–T4.19, excluding T4.7)
and the contextual Model schedules. Empty schedules keep their headers. The
registers preserve different analytical roles:

- T4.1 and T4.2 use individual source/entity scopes so dates, currencies, units
  and perimeters cannot be combined into a misleading aggregate row.
- T4.3 shows sign changes and source-bound facility FX separately, preserving
  original/target currencies, source amounts, missing conversions and formulas.
- T4.4–T4.6 retain source and constructed statement matrices. T4.8 projects their
  construction components, statuses, dates, source references and limitations.
- T4.9 contains the reachable arithmetic graph for each statement/Model value use,
  plus each canonical KPI's numerator, denominator, exact operand references and
  result. Display-use IDs remain separate from shared graph-node IDs. Sum children
  inherit the sum's dimension; other intermediate dimensions remain explicitly
  unavailable rather than guessed. KPI rates/multiples are not labelled money.
- T4.10 presents exact-period KPI values and formula-family categories. Trend and
  analyst-note fields remain explicit gaps until assessed; no trend is invented
  from a partial comparison. Model financial inputs are identified separately from
  the six canonical ratio/flow categories.
- T4.11 preserves definition assessments, conflicting alternatives and all
  multi-figure/debt-basis positions. The extra Source Positions column retains each
  original amount, role, period, unit and locator in the one event row.
- T4.12 retains every upstream gap plus additional projection/statement/interface
  value-null coordinates. Missing optional reference/note fields are not fabricated
  source gaps. No recursive gaps are generated from the gap ledger itself.
- T4.13 retains requested consumer aliases and the historical CP-MODEL gate. Its
  CP-MODEL status and the tagged Model readiness table both use the context-aware
  downstream report; an isolated historical input pass cannot hide a context block.

The calculation table can contain repeated uses of a shared arithmetic node:
this preserves period/metric context rather than guessing one global scope.
The internal report keeps complete original computation graphs and observations.
Unknown numerical inputs, unassessed evidence quality and missing analytical
judgments remain limitations. Register coverage is not proof of completeness of
source extraction or financial/analytical correctness.

## Journal and preview

After all four valid CP-1 stages:

```sh
uv run --locked deploy-vii execution --directory runs/example/execution-1 register-preview --ticket TICKET --output runs/example/registers-1
```

The command reads one execution snapshot, checks current upstream inputs and
recomputes every retained stage in source → financial → narrative → readiness
order. It compares exact retained output strings before generating any files.
A mismatch fails closed. This read-only command leaves the ticket pending and
uses no new repair allowance or provider call.

A fresh output directory contains `canonical-registers.json`, `view.json`,
`tables.md`, `candidate.html` and a last-written `complete.json` (`register-preview/2`).
The receipt binds all file hashes, the candidate artifact, pack, snapshot, ticket
and readiness-step hash. Schema checking in the internal writer alone is not
external authentication; callers must supply recomputed reports. Existing output
directories are rejected. A partial write can leave a directory without a receipt;
there is no atomic directory publication or power-loss guarantee.

Each Markdown table is verified against a table-local projection containing every
declared Fact. This avoids repeatedly parsing the whole report for every table.
HTML field parity, keyboard inspection, local horizontal scrolling, both desktop
viewports, 125% zoom and offline behavior have synthetic browser evidence. These
registers introduce no charts. Charts and complete Model workbook delivery remain
separate requirements. Large source packs still need scalability/transport-boundary
qualification; small fixture performance is not a universal memory guarantee.

This is a register candidate, not the final analytical Markdown export, which is the
canonical envelope below. The [narrative projection](narrative-projection.md) adds
findings, evidence trace, analytical/funding/story coverage and declared statement
coverage. Its `## Analysis` prints each claim as resolved run text (the envelope's
claim line), never the raw `[<fact id>]` chips. Coverage/definition-alignment
confirmation, CP-1A and live/native qualification remain pending. JSON files are
internal provenance, not another final analytical handoff format. No existing artifact
version, store or spend budget is silently migrated or reset.

Review: [confidence review and single key-area tournament](tasks/implementation/canonical-tables-review.md).

## Canonical envelope (task 6.4)

`deploy_vii.envelope` writes the CP-1 handoff as one canonical Markdown file and a JSON
sidecar. `write_envelope(Envelope) -> (markdown, sidecar)` is deterministic (the same
envelope gives byte-identical output). `read_envelope(markdown, sidecar)` returns the
`Envelope` only when the Markdown verifies against its sidecar; otherwise it raises
`EnvelopeError` with the issues (`envelope_issues` returns them).

**Order.** An H1 title and one lead line, then the r14 CP-1 "17-Section Output" as H2s, in
this order (pinned Deploy VI `bd71346`,
`reference/deploy-v-r14/skills/cp-1-canonical-data-foundation/references/CP-1_SCHEMA_REFERENCE.md`):

| # | H2 | Carries |
| --- | --- | --- |
| 1 | Source Register | T4.1 |
| 2 | Entity Period Key | T4.2 |
| 3 | FS Coverage | `statement-coverage` |
| 4 | Normalized IS | T4.4 |
| 5 | Normalized BS | T4.6 |
| 6 | Normalized CFS | T4.5 |
| 7 | Normalization Register | T4.3 |
| 8 | Calculation Register | T4.9 |
| 9 | Constructed Period Register | T4.8 |
| 10 | KPI Dashboard | T4.10 |
| 11 | Definition Conflict Register | T4.11 |
| 12 | Gaps & Warnings | T4.12 (the cumulative gap register) |
| 13 | Downstream Readiness | T4.13, `model-readiness` |
| 14 | Evidence Trace | Findings, `analysis-coverage`, `funding-assessment`, `required-stories`, `evidence-trace`, Evidence list |
| 15 | QA Status | Confidence, QA findings, QA limitations |
| 16 | Limitation Flags | Own, inherited and gap-register limitations |
| 17 | Module Handoff | Identity, T4.14–T4.19, `operating-kpis`, `pro-forma`, Provenance |

r14 lists no Analysis H2 among the 17, so the findings open Evidence Trace beside the
records they stand on. Every section is present. A table the module lacks is an H3 with
`Not produced: <id> is not in this module.`; an empty list is `Not applicable: none
recorded.`; a missing QA report is `Not produced: no QA report is bound to this envelope.`
A table with no rows keeps its headers. A module table that has no section is refused
(`No r14 envelope section for table: <id>`).

**Tables and tags.** Each table is an H3 `<table id> — <title>` (the title escaped) and a
table in the canonical table codec's format (`table_markdown.read_table_markdown`), with
its `<!-- table-id: cp1.* -->` tag for the Model interface tables. A settled cell is the
fact's exact text (`render.display`: the exact decimal, never rounded). An unsettled cell is
`∅ G#` (`∅ G# n.m.` when not applicable), as on the Workbench; the Markdown never spells a
missing value `null` or `None`. Typed values, `null` included, live only in the sidecar
(`envelope.json`, the `Envelope` contract `envelope/1`: run, module, registers hash, gap
register limitations, QA report, journal inputs). Known text that would read as a gap
marker, and known interface text that would read as a null marker, are refused.

**Claims and markers.** Each claim is one line `- <claim id>: <runs>` of resolved run text
(`report_view.resolve`): literal text escaped, a figure or chip with provenance spelled by
Python and followed by its marker (`1,235 US$ m [K1]`), a gap as `∅ [G1]`. The markers are
envelope-local report ids (`build_index` over the CP-1 module). The Evidence list closes
Evidence Trace: one row per marker used anywhere (claims and gap cells), in allocation
order, with its kind and passport detail.

**Footer.** The Provenance table ends Module Handoff: `module_sha256`, `registers_sha256`,
`quality_report_sha256`, `quality_inputs_sha256`, `pack_sha256`, `run_id`,
`method_version`, and one `journal:<input>` row per bound journal input (prepared pack and
CP-0 head with their statuses), or `journal: Not applicable: not bound to an execution
journal` before promotion.

**Verification.** The reader checks section order and completeness, each section's
blocks, every table cell against the sidecar's spelling (reporting the table, row and
column), every marker against the Evidence list (and no unreferenced entry), the footer
hashes recomputed from the sidecar, that no sidecar claim carries a bare figure or an
unresolved reference, and finally byte equality with the canonical rendering. The reader
authenticates the Markdown against its sidecar only; binding the sidecar to the journal is
the caller's (promotion compares the candidate, the export reads the head's blob). Table
size limits are the codec's (20,000 rows, 1,024 columns, 4,000,000 characters per table),
the Evidence list included; a larger table fails verification and so never promotes.

Export after promotion: `deploy-vii execution --directory DIR envelope --module CP-1
--output OUT` writes `envelope.md`, `envelope.json` and a last-written receipt
`complete.json` (`cp1-envelope/1`: module, snapshot, ticket, pack, registers and QA
hashes, head status and its four statuses, file hashes) into a new directory, after the
written pair verifies. See [execution](execution.md) for promotion.

## Model destination manifest (task 7.1a)

CP-MODEL's module carries three text registers, all bound to the Evidence destination
(`bindings/cp_model.py`) because they are provenance of the published Model, not Front Page
figures: `model-destination` (the manifest: path and SHA-256 of `calculation.json`; for
`model.html` and `receipt.json` the cell reads "Recorded in receipt.json", since a page cannot
hold its own hash and the receipt names the head), `model-calculation` (the `ModelReport`
schema and SHA-256) and `model-provenance` (the CP-1 head, the envelope Markdown and sidecar
hashes and the pack hash). The Model panel reads them for its calculation JSON link and its
provenance line. See [execution](execution.md).
