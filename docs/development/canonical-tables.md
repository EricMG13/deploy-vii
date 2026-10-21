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

This is a register candidate, not the required final analytical Markdown export.
The [narrative projection](narrative-projection.md) adds findings, evidence trace,
analytical/funding/story coverage and declared statement coverage. Full
17-section/canonical envelope, QA and numeric confidence,
coverage/definition-alignment confirmation, final acceptance, CP-1A and live/native
qualification remain pending. JSON files are internal provenance, not another final
analytical handoff format. No existing artifact version, store or spend budget is
silently migrated or reset.

Review: [confidence review and single key-area tournament](tasks/implementation/canonical-tables-review.md).
