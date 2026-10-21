# Typed tables and statement previews

`ReportTable` declares ordered columns and rows that reference canonical `Fact`
IDs. It stores no replacement values. Validation rejects duplicate tables,
interfaces, columns and rows; unknown or repeated facts; nonrectangular rows;
coordinate substitutions; and omitted facts belonging to a declared table.
Facts in undeclared tables retain the generic record view. Empty schedules retain
headers without manufactured rows. `Module` and `ModuleView` validate the same
layout; stale/blocked execution output hides layouts with its facts.

Python supplies identical table value strings to HTML and Markdown. Unknown and
conflicting/not-applicable values display literal `null`; their distinct status
and reason remain inspectable. Zero retains its source precision.
The inspector keeps status, reason, source and normalized amounts, value class,
normalization/derivation formula, stated comparison, calculation status, exact
units/scale, dates, entity/accounting basis, citations and artifact hash. Table wrappers support keyboard scrolling and row headers.
Units and partial-output scope appear before the values.

`table_markdown(module, table_id)` is a table projection primitive, not the full
r14 canonical Markdown handoff. Interface tables require literal field headings,
no extra row-header column, and their exact `<!-- table-id: ... -->` tag.
Known interface text matching null markers is rejected, except the controlled
`NONE` reference rate in the debt-facility interface. Source markup and pipes
are entity-escaped; newlines become generated `<br>` (CRLF/CR normalize to LF).
The raw JSON remains authoritative for this internal preview. The new
[canonical table codec](model-interface.md) decodes generated entities once and
checks exact table parity against a trusted Module. Full-envelope parsing and the
typed downstream adapter remain pending before claiming complete Markdown
interoperability. No legacy parser was adopted.

## Statement preview

After valid `source_context` and `financials` submissions:

```sh
uv run --locked deploy-vii execution --directory runs/example/execution-1 statement-preview --ticket TICKET --output runs/example/statements-1
```

The command rechecks current inputs and recomputes the retained financial stage.
It writes a new directory containing `statement-report.json`,
`statement-history.json`, `view.json`, `candidate.html` and a last-written
`complete.json` with file, pack, review, history and source-report hashes,
and execution snapshot/ticket/financial-step bindings.
The receipt uses `statement-preview/2`. Existing directories
are rejected. A failed write can leave an incomplete directory; absence of the
receipt means incomplete output. The receipt is not an atomic directory publish
or power-loss guarantee. The preview is bound to the snapshot read at invocation;
subsequent journal changes do not update an existing HTML file.

T4.4 income, T4.5 cash flow and T4.6 balance-sheet matrices cover source periods
and disclosed line items plus required gaps, followed by
[constructed-period columns](statement-history.md). Each cell retains its actual source
label even when the row label is selected from another period. A disclosed item
missing in another period has an explicit null and reason. Point-in-time-only
books have empty flow tables, not invented flow periods.

This command does not settle the ticket, accept CP-1, create an accepted report,
or call a model. The separate [canonical register preview](canonical-tables.md)
adds the other CP-1 tables. Canonical Markdown envelope/QA, complete Model presentation and final module promotion
remain pending. Charts are not applicable to these statement matrices;
Model chart/table parity remains a later check. Synthetic fixture rendering does
not qualify analytical judgments or a completed Module.

## Format boundary

Layouts and additional fact provenance fields change serialized artifact hashes.
New artifacts use `module/4`, `view/3` and `execution/4` after adding stated
comparisons and calculation status. Explicit previous versions
are rejected. There is no automatic migration: retain old stores and outputs.
This boundary does not authorize a new provider budget or discard earlier spend.

Original table validation: [review](tasks/implementation/report-tables-review.md).
Constructed statements: [review](tasks/implementation/statement-history-review.md).

The combined [Model interface preview](model-interface.md) adds T4.14–T4.19 and
contextual schedules to these statements. Table cells have a readable minimum
width; horizontal overflow stays inside the keyboard-accessible table region.

The [canonical register preview](canonical-tables.md) combines all 18 required
table IDs and Model schedules after all four journal stages. Its Markdown remains
a verified table preview; full analytical export and acceptance are separate.
