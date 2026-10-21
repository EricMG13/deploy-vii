# Typed table and source-statement preview review

Base: `729eaeb`, branch `codex/development-environment`, owner session
`01a15bb5-b5bc-7151-94b3-4edbae9d7815`. Scope: typed fact layouts, shared table
value projection, source-period statement preview and its journal/CLI adapter.
No dependencies, provider routing or budgets changed. This is progress within C,
not CP-1 completion. OpenRouter spend remains $0 of the authorized $50 cap.

## Confidence review — all changed code

Least confident about, ranked:

1. **A layout could hide, duplicate or transpose canonical values.** Traced
   `Module`/`ModuleView` validation through rendering, delivery and execution views.
   Adversarial cases cover duplicate identities, wrong coordinates, unknown/reused
   facts, short rows and omitted facts. Every declared table must cover exactly
   its facts; undeclared legacy tables remain visible in the generic view.
   Verdict: verified fine by corruption tests, rendering parity and strict typing.
2. **A preview could display stale data or imply acceptance.** The CLI requires
   the first two retained CP-1 stages to be valid, checks current upstream/pack
   inputs, and recomputes the financial stage before writing. Tests show early
   and stale requests fail, the journal hash stays unchanged, and its pending
   ticket remains pending. The receipt binds the snapshot and financial step.
   Verdict: verified fine for invocation-time lineage. Existing files are static
   snapshots, not live views; later source changes do not rewrite them.
3. **New serialized fields could silently invalidate old artifact hashes.** Added
   layouts and fact provenance change JSON even with default empty values.
   Advanced formats to module/2, view/2 and execution/3. Tests reject old module,
   view and both prior execution versions. Verdict: explicit compatibility
   boundary; automatic migration remains unimplemented. Preserve old stores and
   provider-spend history rather than overwriting or resetting them.
4. **Markdown escaping could alter machine fields or null semantics.** Pinned
   r14 parser inspection confirmed it expects literal field names. The first
   escaping implementation changed `source_id` to `source&#95;id`. Fixed controlled
   keys to remain literal and required exact interface headers with no extra
   row-header column. Known null-like interface text now raises rather than being
   confused with unknown data. Tests retain exact tags/headers and reject bad
   shapes. Verdict: confirmed issue fixed. General prose remains entity-escaped;
   the legacy parser does not decode it. A dedicated canonical reader/adapter and
   round-trip verification remain open before full handoff interoperability.
5. **Zero, conflict or sign normalization could lose meaning.** Traced source
   statements through `statement_report`, the Fact projection, Python formatting
   and browser inspector. The synthetic fixture retains 0.00, distinguishes absent
   rows and conflicts, and shows source COGS 30 alongside normalized -30 and its
   formula. Currency, million scale, dates, basis and citations match. Source
   extra rows form the union across periods; absent cells have explicit reasons.
   Point-in-time-only books yield empty flow tables. A final adversarial test
   reproduced `not_applicable` source cells becoming `missing`. Extended Fact to
   retain this source status and copied it directly from StatementCell; null/
   reason requirements remain enforced. Browser inspection checks the exact
   original status/reason. Verdict: confirmed status-loss bug fixed; remaining
   numeric/status paths verified fine.
6. **Partial scope and units could be overlooked below long tables.** Visual
   inspection confirmed both appeared too late. Moved the first module limitation
   and each table's units/scope before values. Reinspected 1440×900, 1280×800 and
   720×450 screenshots. Verdict: confirmed presentation issue fixed; no CSS change.
7. **Source text could inject markup or break keyboard/zoom use.** DOM construction
   uses text nodes; JSON escapes `<`. Tests exercise hostile long labels, empty
   schedules, every fact's exact field, row headers, keyboard activation/scroll,
   125% CSS zoom, viewport overflow, offline requests and browser errors. Verdict:
   verified fine in Chromium on these fixtures; not general assistive-technology
   or issuer-level qualification.
8. **Output writes or concurrent journal changes could produce a misleading
   receipt.** Validation/rendering finish before destination creation; existing
   directories are refused. File hashes and a last-written receipt detect complete
   output. The journal is read into an immutable snapshot and is not mutated.
   Verdict: by design, partial files may remain after I/O failure; without the
   receipt they are incomplete. Atomic directory publication and power-loss
   durability are not claimed. A concurrent update leaves a historical preview
   bound to its original snapshot, not a claim of present-day freshness.
9. **Projection completeness could be mistaken for analytical completion.** The
   page and receipt explicitly retain candidate/unrun states. Source matrices do
   not contain derived periods, remaining CP-1 registers, the complete Markdown
   envelope/QA or a Model workbook. Synthetic acceptance-path tests only verify
   engine layout propagation and stale hiding. Verdict: intentionally partial;
   those product requirements and live/native qualification remain open.

Fixed: machine-field escaping, ambiguous interface text handling, scope/units
placement and not-applicable source status loss. Verified fine: table ownership/coverage, exact values and provenance,
current journal bindings, unchanged attempt state, safe offline browser behavior.
By design: empty schedules, explicit version rejection, static snapshot previews,
last-written receipts. Still open: complete CP-1 canonical delivery and promotion,
Markdown reader interoperability, derived statements and later milestones.

## Tournament scope and model matrix

Only `validate_tables` receives the no-argument post-edit tournament: canonical
fact-to-cell ownership is the key provenance boundary. Routine statement assembly,
Markdown formatting, renderer and CLI changes receive confidence review and focused
tests. Fresh workers use the explicit `gpt-6.1-sol` high review route; coordinator
model is unchanged. No unrelated provider or live analytical call was made.

GitNexus could not find this repository. The recorded fallback impact set is
`Module.distinct_records`, `ModuleView.output_identity`, `render`, `table_markdown`,
`delivery`, execution snapshots/views and `statement_view`. Strict mypy and the
affected tests are the caller-contract checks. Scratch candidates, backup and
impact evidence are under ignored `artifacts/table-tournament/`.

## Tournament result

Winner: **Snippet C**, replacing `src/deploy_vii/contracts.py:186–220` (now
186–224). The blind bracket selected B over A, C over B, then C over D.

- Explicit canonical/reference names make fact ownership and coverage auditable.
- Validation stages, exception order, signature and main allocations are preserved.
- The speed candidate's cache and fallback branches add maintenance cost without
  evidence of an application bottleneck; the memory candidate's savings are small.

Final code:

```python
def validate_tables(tables: tuple[ReportTable, ...], facts: tuple[Fact, ...]) -> None:
    """Validate declared layouts against canonical facts; permit undeclared tables."""
    if len({table.table_id for table in tables}) != len(tables):
        raise ValueError("Duplicate report table")
    interface_ids = [table.interface_id for table in tables if table.interface_id is not None]
    if len(interface_ids) != len(set(interface_ids)):
        raise ValueError("Duplicate table interface identity")
    facts_by_id = {fact.fact_id: fact for fact in facts}
    if len(facts_by_id) != len(facts):
        raise ValueError("Duplicate fact identity")

    for table in tables:
        if table.interface_id and (
            table.row_header is not None
            or any(column.label != column.field for column in table.columns)
        ):
            raise ValueError(
                "Interface table requires exact field headings without an extra row header"
            )
        column_fields = [column.field for column in table.columns]
        if len(column_fields) != len(set(column_fields)):
            raise ValueError("Duplicate report column")
        if len({row.row_id for row in table.rows}) != len(table.rows):
            raise ValueError("Duplicate report row")

        referenced_fact_ids: set[str] = set()
        for row in table.rows:
            if len(row.fact_ids) != len(column_fields):
                raise ValueError("Report row does not match its columns")
            for field, fact_id in zip(column_fields, row.fact_ids, strict=True):
                fact = facts_by_id.get(fact_id)
                if fact_id in referenced_fact_ids or fact is None:
                    raise ValueError("Report cell repeats or references an unknown fact")
                if (fact.table_id, fact.row_id, fact.field) != (table.table_id, row.row_id, field):
                    raise ValueError("Report cell differs from its canonical fact coordinates")
                referenced_fact_ids.add(fact_id)
        canonical_fact_ids = {fact.fact_id for fact in facts if fact.table_id == table.table_id}
        if referenced_fact_ids != canonical_fact_ids:
            raise ValueError("Declared report table omits canonical facts")
```

Coordinator verification: `uv run --locked python
artifacts/table-tournament/coordinator-check.py` passed 1,200 seeded differential
cases across all four snippets, signature parity, input purity and a concrete
swapped-row rejection. The target file was backed up before applying C. The full
candidate diff was inspected; final in-tree checks are recorded below.

## Design hook triage

The side-tab finding at `assets/app.css:2` refers to
`.module-link[aria-current=page]`, the active navigation indicator preserved by
Direction C. The existing file-scoped `side-tab/*` exception remains; no CSS fix
or new suppression was added. No unresolved design finding remains in this scope.

## Final checks

- `uv run --locked pytest tests/product/test_report_tables.py tests/product/test_contracts.py -q`: 43 passed in 5.45s on the selected function in-tree, including its renderer/Markdown callers.
- `make product-check`: passed on the final code, 828 tests and 97.48%
  branch-inclusive coverage. Ruff lint/format, strict mypy for 46 source files and
  Node JavaScript syntax passed. Earlier full runs preceded the selected rewrite
  and the not-applicable fix; the final run includes both.
- `uv run --locked python artifacts/table-tournament/coordinator-check.py`: all
  four snippets matched across 1,200 seeded cases; exact signatures and unchanged
  inputs passed, including a concrete swapped-financial-row rejection.
- `make check`: lock consistency, all-file hygiene and working/staged diff checks
  passed. `make secrets`: working files, staged diff and all reachable history
  passed with Gitleaks 8.30.1. No dependency change required an audit.
- Browser fixtures retain exact field/value parity, status/reasons and provenance
  at 1440×900, 1280×800 and 720×450, with keyboard use, 125% CSS zoom, long hostile
  content, empty schedules and no remote requests or JavaScript errors. Viewport
  screenshots were inspected after the scope/units placement fix.
- Coordinator inspected the full candidate, including new files and the final
  status fix. The selected function in-tree exactly matches snippet C.

Raw local evidence: `artifacts/tables-product-check.log`, `tables-focused.log`,
`tables-check.log`, `tables-secrets.log`, `tables-not-applicable-before.log`,
`table-tournament/coordinator-check.log` and `rendering/statements/`. Raw runs and
screenshots stay ignored. Review completion does not promote analytical,
completed-Module, or native-host qualification.
