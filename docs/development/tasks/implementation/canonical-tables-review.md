# Canonical registers: confidence review and journal-boundary tournament

Task `dvii-implementation-001`, milestone C. Base `fb62385`, branch
`codex/development-environment`, owner session
`01a15bb5-b5bc-7151-94b3-4edbae9d7815`. Scope: canonical register projection,
shared table metadata, combined preview and journal/CLI integration. No new
provider call or dependency. Pinned method: Deploy VI
`bd71346301b373afa72655916a4c1b42bf4c9823`, CP-1 schema and Steps 1–13 in the local
reference bundles. No reference-project code or policy was copied.

## Confidence review — remaining canonical tables

Least confident about (ranked):

1. **Untrusted retained output or later state slipping into a preview.** Traced
   `execution_cli.execute` → `cp1_register_preview` → `_validate_stage` and the
   writer. The command reads one snapshot, requires the exact four valid stages,
   checks current inputs, then recomputes every prefix before parsing final review
   contracts and writing. Tests alter each retained output independently and
   change upstream inputs; all fail before destination creation. Exact string
   comparison retains precision sensitivity. Tests confirm unchanged journal hash
   and complete receipt hashes. **Verified fine.** The internal writer only
   validates shape/pack binding and requires a trusted caller; it is not an
   arbitrary-upload authentication API. The external report validator separately
   recomputes all tables and compares content hashes, rejecting Decimal-equal
   precision tampering.
2. **Contradictory historical readiness.** The standalone interface uses the
   historical Model gate, while canonical downstream readiness also includes
   context binding. Simply merging both would expose a historical ready result
   beside a context block. **Confirmed integration hazard:** the new composition
   replaces the standalone tagged readiness projection with the context-aware
   result, preserving the underlying historical report as provenance. A stale
   context-binding fixture has standalone ready and context-aware blocked;
   both rendered readiness tables must show blocked. Requested aliases remain.
3. **Lost graph context, operand meanings or monetary units.** Traced statement
   history and canonical KPI graphs through T4.8/T4.9/T4.10. Each displayed use has
   its own identity; graph IDs are not assumed to define a unique period/metric.
   The shared-node regression retains both metric contexts. Sum descendants carry
   their root dimension; unknown non-sum intermediate dimensions are explicitly
   untyped, an outstanding full-delivery constraint rather than invented units.
   Ratios retain monetary numerator/denominator inputs but dimensionless result
   currencies; exact source precision, calculation IDs, formula, status, stated
   comparison, period dates and citations are retained. Dashboard cells use their
   actual period even within one multi-period row. **Verified in fixtures.** No new
   financial arithmetic is performed here; source models own all calculations.
4. **Conflict rows losing the figures they explain.** Initial T4.11 projection
   retained observation IDs and explanation but omitted actual figures/roles.
   **Confirmed omission:** the new regression failed because Source Positions was
   absent (`artifacts/canonical-registers-figures-repro.log`). Added that column,
   with every original observation, role, amount, unit, period and locator, plus
   unresolved alternatives. One economic event remains one row. Test asserts both
   carrying 100 and principal 105. An initial test incorrectly expected 110; the
   source fixture establishes 105 and the assertion was corrected. No source value
   was changed to satisfy the test. Declared column-count validation also caught
   an intermediate missing heading while adding the column; it was repaired.
5. **False gaps and omitted real gaps.** Every upstream narrative/financial gap
   remains in T4.12, supplemented by coordinate-bound interface/statement gaps.
   Initial optional limitation notes became missing source values. **Confirmed
   false gap**, reproduced in `artifacts/canonical-registers-note-repro.log`.
   Optional notes/references now retain explicit not-applicable status, with no
   fabricated warning. Missing numbers, unassessed trends and evidence quality
   remain gaps. Test traverses every original gap and unsettled statement cell.
   Projection gaps are appended once; the gap table cannot recursively generate
   unbounded copies of itself. There is no automatic alignment/all-clear claim.
6. **Source dimensions collapsed across scopes or normalizations.** Source/entity
   rows are emitted per explicit scope; test compares period, currency, tier and
   citations against the input scopes. T4.3 tests verify positive source outflows
   normalized negative without losing originals and foreign money retained in EUR
   when target USD conversion is missing. Zero and unknown remain distinct.
   **Verified fine for the projected fields.** Field-level source provenance is
   preserved; additional gaps do not settle conflicting source alternatives.
7. **Blocked historical gate suppressing useful statements.** A partial add-back
   fixture blocks Model calculations but still projects source context, statement
   construction and available arithmetic. The KPI dashboard keeps headers rather
   than inventing values. **Verified fine.** Initial test used a complete
   disclosure fixture and incorrectly expected the gate to block; corrected the
   fixture to explicitly partial disclosure.
8. **Misleading UI or enormous repeated validation.** Browser tests compare every
   cell ID/string, inspect a calculation by keyboard, and exercise offline desktop
   viewports/125% zoom. Visual inspection found opaque `field_9` labels in the
   inspector; changed labels to the human column plus metric/row while retaining
   machine coordinates. Tables remain locally scrollable and source text enters
   text nodes. The writer validates each table with its full set of facts, avoiding
   whole-report parsing for each table. **Verified at fixture scale.** Larger pack
   memory/time, transport limits and graph expansion remain unqualified; no
   performance acceptance is claimed.
9. **File failure, mutation and acceptance overclaim.** Fresh directory and
   last-written hashed receipt; existing destination rejected. Reports/contracts
   are revalidated at entry. Native frozen objects and external recomputation
   preserve the input boundary. **By design:** interrupted writes may leave an
   incomplete directory; no atomic/power-loss promise. The candidate never accepts
   CP-1 or consumes a repair. All analytical/browser acceptance fields remain
   unrun; synthetic browser evidence is recorded separately.

Fixed: inconsistent merged readiness, missing conflict figures/roles, false
optional-note gaps, opaque inspector labels. Verified fine: exact stage/input
binding, full table identity, numerator/denominator values, source scopes, FX/sign
separation, inherited/projection gap retention and offline field parity. Still
open: full narrative/envelope, numeric confidence/QA, extraction/definition
completeness, large-pack qualification and final promotion. No confirmed bug is
being waived as acceptance.

## One key-area post-edit tournament

Target: `cp1_workflow.cp1_register_preview`, lines 205–253. This is the new ordered
trust boundary. Declarative table adapters and UI received confidence review and
behavioral tests; no wider tournament. Fresh isolated roles explicitly used
GPT-6.1 Sol/high per the user's model matrix; coordinator route unchanged.
GitNexus reported this project absent, so `rg` supplied the actual caller inventory
in `artifacts/register-preview-tournament/impact.txt`. No other project index used.

Anonymous bracket: A speed, B memory, C readability, D incumbent. B won A/B,
B/C and B/D. Winner **Snippet B** replaces the target function after a full-file
backup to `before-winner.py`. Actual delta is one `del verified` after successful
validation, preserving every guard, call order, error and binding.

- Release the no-longer-needed recomputed output before the next stage/report.
- Preserve uniform prefix validation and exact comparisons without a second path.
- Actual fixture measurements show a modest benefit: 4.33 MB lower median traced
  peak (~1.06%); this is not a general large-pack memory guarantee.

Final code:

```python
def cp1_register_preview(store: Execution, ticket_id: str, destination: Path) -> Path:
    """Recompute every retained stage before projecting a complete register candidate."""
    from deploy_vii.canonical_tables import canonical_tables
    from deploy_vii.register_view import write_register_preview

    snapshot = store.read()
    attempt = next((a for a in snapshot.attempts if a.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != "CP-1":
        raise ValueError("CP-1 attempt is not available")
    if tuple(s.step_id for s in attempt.steps) != CP1_STEPS or any(
        s.status != "valid" for s in attempt.steps
    ):
        raise ValueError("All CP-1 source, financial, narrative and readiness stages must be valid")
    if current_inputs(snapshot, "CP-1") != attempt.inputs:
        raise ValueError("CP-1 register preview inputs are stale")
    for index, step in enumerate(attempt.steps, 1):
        verified = _validate_stage(
            snapshot.pack, attempt.model_copy(update={"steps": attempt.steps[:index]})
        )
        if verified.issues or verified.output != step.output:
            raise ValueError(f"{step.step_id} stage differs from trusted recomputation")
        del verified
    source = SourceContextReview.model_validate_json(attempt.steps[0].payload)
    financial = FinancialSubmission.model_validate_json(attempt.steps[1].payload)
    narrative = NarrativeReview.model_validate_json(attempt.steps[2].payload)
    readiness = DownstreamReview.model_validate_json(attempt.steps[3].payload)
    report = canonical_tables(
        snapshot.pack,
        source,
        financial.financial,
        financial.definition,
        financial.binding,
        narrative,
        consumer_entries(snapshot.pack),
        readiness,
        quarter_ids=financial.quarter_ids,
    )
    return write_register_preview(
        snapshot.pack,
        report,
        destination,
        execution_binding={
            "snapshot_sha256": snapshot.content_hash(),
            "ticket_id": ticket_id,
            "readiness_step_sha256": attempt.steps[-1].content_hash(),
        },
    )
```

## Verification and remaining work

Coordinator checks after applying the winner:

- `make product-check`: 890 passed in 210.37s; 97.45% branch-inclusive coverage.
  Ruff, format, strict mypy and JavaScript syntax also passed. Log:
  `artifacts/canonical-registers-product-check.log`. This full run preceded the
  final external-validator regression and small label/scope-note changes.
- `uv run --locked pytest tests/product/test_canonical_tables.py tests/product/test_register_view.py -q`:
  final current-tree check, 20 passed in 35.91s, including both browser viewports.
  Log: `artifacts/canonical-registers-final.log`. The earlier post-winner run also
  passed 20 checks; this run covers the final labels and subartifact scope notes.
- `uv run --locked ruff check src tests/product`,
  `uv run --locked ruff format --check src tests/product`, `make types`: passed on
  the final code; 109 formatted files and 51 typed source files.
- Rechecked every reference with `rg -n 'cp1_register_preview' src tests`.
  Only the CLI and the focused workflow/browser tests call this function. Their
  contracts and return type are unchanged; the CLI roundtrip passes. The concrete
  invariant check mutates each of the four retained stage outputs and verifies
  rejection before creating any output directory.
- `make check`: passed lock, all-file hygiene, lint/format and diff whitespace.
  `make secrets`: no leaks in working files, staged diff or all reachable history
  (33 commits at the pre-commit base). Logs: `artifacts/canonical-registers-hygiene.log`
  and `artifacts/canonical-registers-secrets.log`.

The coordinator inspected the full candidate code, tests, documentation and
post-tournament diff. Browser evidence is retained under
`artifacts/rendering/canonical-registers/pytest-907/`, including every projected
field, 1440×900 and 1280×800 screenshots and 125% zoom. The 1280×800 zoom image was
visually inspected: keyboard focus, formula, amount, period and human inspector
label remain readable; wide-table scrolling stays within the table.

Design-hook triage: **fixed** inspector labels in this increment; **suppressed**
no new finding. The existing file/value-specific `side-tab` exception is retained
for `.module-link[aria-current=page]`, the intentional navigation indicator in the
Direction C reference (lines 243 and 291). **Left standing:** this intentional
indicator, with no CSS change or unresolved design defect asserted.

OpenRouter spend remains US$0 of US$50; no model-assisted financial qualification
or native-host qualification was run. No dependency changes. Narrative projection,
canonical envelope/QA, explicit full intermediate dimensions, large-pack transport
qualification, final acceptance and CP-1A remain open; milestones D–H follow.
The overall A–H goal remains active.
