# CP-1 narrative and evidence projection

The journal-bound `register-preview` now includes supplied CP-1 findings alongside
its canonical registers. `canonical-tables/2` binds the same recomputed source,
financial, definition, narrative and downstream reviews as before. It projects
the existing validated narrative; it does not invent findings, substitute numeric
values, change readiness, or grant acceptance.

Each finding preserves its dimension and title followed by the three separate
passages: Evidence, Risk mechanic, Credit implication. Prose tokens retain their
order and whitespace. Issuer tokens resolve from the prepared run. Evidence tokens
become compact `[E…]` references into the Evidence Trace. Labels are deterministic
within that exact input catalogue; persistent identity remains the evidence ID and
its hashes. All located citations used by any passage remain on the Claim.

The following supplemental tables use the existing Fact/layout contracts:

- **Analytical dimension coverage:** every dimension, supplied assessment and
  rationale. Omitted dimensions remain explicitly unassessed, including financial
  dimensions when the narrative scope is data-quality-only.
- **Non-debt funding assessment:** the declared reviewed and material row IDs,
  status and rationale. No inference of full filing coverage or new extraction.
- **Required event and funding stories:** each required prior record, supplied
  finding IDs or explicit missing story. Inherited BLOCK gaps remain in T4.12.
- **Evidence trace:** all referenced records, their usages (finding/passages,
  coverage, funding and required story), evidence ID, originating artifact hash,
  record hash and every leaf field. JSON-pointer paths preserve nested structure;
  strings, numeric strings, null, booleans and empty containers stay distinct.
  Currency, period IDs, roles, formulas and source locators are retained from each
  record, rather than inferred by this adapter. Other canonical tables retain the
  referenced period definitions and context.
  Statement-record fields additionally retain their validated book currency/unit
  and exact source-period dates in the inspector. For other record types, the
  inspector explicitly says to consult the canonical registers when dimensions
  are not intrinsic to that record; shared graph IDs do not imply one unit/period.
- **Financial statement coverage:** each source period and statement, supplied
  line count, missing required entries, conflicts and not-applicable entries.
  Point-in-time periods explicitly exclude flow statements. These rows describe
  the declared extraction, not completeness against unseen filing contents.

The offline Workbench renders Claims and every declared table field. Keyboard
inspection exposes located source evidence and the owning artifact hash. Narrative
text, including source markup or URLs, enters text nodes; Markdown uses the same
escaped cell-text transport as the registers. The preview's `## Analysis` contains
the identical Claim text; empty reviews explicitly state that no findings were
supplied. There are no charts in this projection.

The report uses `canonical-tables/2` and the last-written receipt uses
`register-preview/2`. Explicit older report versions are rejected. The journal
format remains `execution/5`: no stage output schema or validation order changed.
Create a new preview directory, retain earlier evidence, and do not reset spend.
The internal `project_narrative` helper expects a caller-recomputed report; it is
not an authentication API. `validate_canonical_tables` recomputes against external
inputs and rejects altered Claims or fields. `cp1_register_preview` remains the
journal trust boundary.

Remaining delivery work is definition-alignment and extraction-completeness
confirmation, the calculation JSON of CP-MODEL (M8) and large-pack transport
qualification. The canonical envelope, QA and promotion landed in task 6.4 and the
typed consumer that renders the accepted envelope (`read_cp1_envelope`) in task 6.5.
Rendering a supplied chain
does not prove its issuer-specific reasoning, contrary evidence, causal downside,
materiality or semantic sufficiency. Those require the full analytical review and
live qualification. CP-1A and subsequent milestones remain open.

Review and checks: [narrative projection review](tasks/implementation/narrative-projection-review.md).
