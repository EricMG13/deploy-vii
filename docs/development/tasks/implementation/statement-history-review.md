# Statement history: confidence review and scoped tournament

Task: full-product implementation, milestone C increment. Base `c1b2e0a`, branch
`codex/development-environment`, owner session
`01a15bb5-b5bc-7151-94b3-4edbae9d7815`. This review covers all changed production
functions and the resulting source/derived statement candidate; it is not full
CP-1 or analytical acceptance. No new dependency, provider call or route change.

## Confidence review — statement histories and preview

Least confident about (ranked):

1. **Nested component completeness and audit graph.** A reported H1 subtotal
   could substitute for its missing Q1 when deriving FY. Reproduced before the
   fix: FY became 1069 from H1 999 + Q3 30 + Q4 40, despite missing Q1.
   **Confirmed bug:** the existing kernel reader expanded only one level.
   Patched `_component` to recursively resolve additive periods with four-level,
   cycle and span guards. A regression requires null with the missing leaf and
   100 when the leaf is 10, while FY 888 and H1 999 remain separate comparisons.
   Actual leaf observations and recursive arithmetic metadata are asserted;
   dataclass numeric equality alone would miss audit-graph regressions.
2. **Statement derivations accidentally inheriting the Model add-back gate.**
   Traced `statement_report` through validated source input, then used a
   period-only internal register and the existing period/flow readers.
   **Verified fine:** partial add-back disclosure blocks `historical_report`
   as before but permits independent statement construction. Statement rows
   always use complete-input flow semantics, never sparse omission-as-zero.
3. **Null/conflict propagation and closing balances.** Tested not-applicable
   prior YTD, explicit conflicts, mismatched stubs, and same-date known/conflicted
   balance alternatives. **Verified fine:** flows remain null and retain input
   evidence; explicit closing-date conflict prevents known fallback. BS uses the
   actual closing observation without subtraction. Missingness is not a zero.
   The generic kernel's null node may omit source refs; the new child-first
   lineage projection retains missing operands and attempted unspanned terms.
4. **Wrong period/figure identity or source substitution.** Tested Q2/Q3/Q4,
   independently reported Q4, LTM 110 versus stated 999, issuer-only detail,
   sign-normalized outflows, and recursive FY components. Inspected construction
   traversal, collision checks and period/field identities. **Verified fine:**
   original source cells remain unchanged; derived cells have separate fields,
   computation IDs and comparisons. A formula names declared subcomponents so
   computed FY 100 cannot be mistaken for reported FY 888. Source-only books
   with point-in-time records retain empty flow tables.
5. **Caller objects read after validation.** A nested dictionary introduced by
   `model_copy` passed JSON revalidation but the preview reread the original
   caller's book. **Confirmed bug:** reproduced `'dict' object has no attribute
   'book_id'` using the pre-fix read. The preview now takes periods and units from
   the validated history artifact; the nested-object regression passes.
6. **Tampered results, ambient precision and stale formats.** Trusted history
   validation revalidates schema and compares recomputed content hashes. Tests
   reject removed values, an unknown book, stale review binding and precision-only
   `20`→`20.0` tampering despite equal Decimal values. Ambient precision two leaves
   the artifact unchanged. **Verified fine:** Module/View versions 1–2 and
   execution versions 1–3 reject the new formats. Contract-level finite-number
   validation also covers the new comparison field.
7. **View fidelity and misleading scope.** Browser checks compare every projected
   field with its Fact, inspect formulas/comparisons/status/citations by keyboard,
   and exercise both desktop viewports, zoom and offline operation. Visual review
   found the source report's “source and sign-normalized only” limitation presented
   as a whole-preview limitation. **Confirmed presentation issue:** prefix that
   inherited note “Source artifact:” while keeping the overall source+derived
   preview scope explicit. No CSS or source design change.
8. **File completeness and acceptance state.** Inspected write order and retained
   journal binding tests. **By design:** fresh directory, hashed files and receipt
   written last; incomplete writes remain recognizable by missing receipt. There
   is no atomic directory/power-loss promise. Existing journal/ticket state is not
   settled by a preview. Immutable prior outputs remain tied to their invocation
   snapshot; complete Module promotion is still pending.

Fixed: nested component subtotal plug; post-validation caller-object access;
misleading inherited source-only scope note.
Verified fine: explicit missingness/conflict handling, BS closing semantics,
source/derived separation, sign evidence, hash/precision identity, source gate,
legacy-format rejection and candidate-only preview behavior, using the checks above.
By design: original source comparisons are retained even when they disagree;
`Verified` is the r14 calculation status of a located source observation, not
analytical qualification. Raw graph and source artifacts remain authoritative.
Still open: remaining CP-1 registers, full canonical Markdown envelope/reader/QA,
Model presentation, final promotion, CP-1A and live/native qualification. These are
subsequent goal increments, not inferred from arithmetic or browser coverage.

## One key-area post-edit tournament

Per the user's limit, only `history._component` receives a tournament. Routine
statement assembly, adapters, renderer and contract changes receive confidence
review and behavioral checks. Fresh isolated `gpt-6.1-sol`/high roles implement
the requested model matrix; coordinator model is unchanged. No Astra escalation.

GitNexus lookup reported the repository unavailable; the fallback reference search
and strict type check establish the impact set: `_term` → `_flow`/`_read`,
`account_frame`, `ltm_frames`, historical-period/Model output, reconciliation,
readiness and the new full-statement projection. Private function signature and
sparse cache behavior must remain unchanged. Each recursive Cell's reason, basis,
stated amount, input refs and arithmetic DAG matter, as do Decimal order/context.

The three challengers and incumbent were read from scratch files. Blind bracket:
A beats B (immutable path over mutable cleanup state), C beats A (one leaf/lookup
path instead of duplication), C beats D (flat guards and named recursive terms).
The coordinator backed up the complete target before applying C and re-read the
actual diff. The original bug fix, not the buggy base, was the tournament incumbent.

**Winner: Snippet C**, replacing `src/deploy_vii/model/history.py:338` (`_component`).

Justification:

- Early leaf return keeps recursive span validation at one indentation level.
- Named `child_path` and `parts` expose the traversal state and aggregation inputs.
- Immutable ancestry preserves branch isolation without mutable cleanup machinery.

Final code:

```python
def _component(series: _Series, register: _Register, period_id: str | None) -> Cell:
    """Resolve all declared flow components; a reported subtotal is not a plug."""
    if period_id not in register.periods:
        return _MISSING
    if series.kind == "sparse":
        return _resolved(series, register, period_id)

    def resolve(identity: str | None, ancestors: tuple[str, ...]) -> Cell:
        period = register.periods.get(identity)
        if period is None:
            return _MISSING
        if period.period_id in ancestors or len(ancestors) >= 4:
            return _UNSPANNED_PARTS
        if period.period_type not in _ADDITIVE or not period.component_period_ids:
            return _sum(series, ((_reported(series, period.period_id), 1),))
        if not _spans(register, period):
            return _UNSPANNED_PARTS
        child_path = (*ancestors, period.period_id)
        parts = ((resolve(part, child_path), 1) for part in period.component_period_ids)
        return _sum(series, parts)

    return resolve(period_id, ())
```

Verification:

- `uv run --locked pytest tests/product/test_statement_history.py tests/product/test_financial_periods.py -q`
  → **29 passed** with the selected candidate in-tree. Concrete invariants: nested
  missing leaf stays null; known leaf sum is 100; depth four succeeds, five/cycle
  returns null; ordinary flow cache remains untouched.
- `uv run --locked python artifacts/statement-component-tournament/readability-check.py`
  → **38,800 complete metadata/state comparisons passed**. Coordinator inspected
  and executed the harness: all dataclass fields, Decimal tuples, absent/null,
  sign evidence, varied depth/span/cycle, all four kinds, low/default precision,
  pure ordinary flow and repeated sparse cache identity.
- Coordinator confidence probes retain the pre-fix nested-object failure and
  corrected projection plus nested FY formula/comparison in
  `artifacts/statement-history-confidence-probes.log`.

Final checks:

- `make product-check` → **843 passed**, **97.46% branch-inclusive coverage**;
  Ruff lint/format, strict mypy (**47 source files**) and Node syntax all pass.
  This includes all selected kernel regressions and execution/HTML integration.
- `make check` → locked environment, repository hygiene and diff checks pass.
- `make secrets` → working directory, staged candidate and reachable-history
  scans passed with no leaks. No dependency changes; dependency audit is not
  applicable to this increment.
- Retained evidence: `artifacts/statement-history-product-check.log`,
  `artifacts/statement-history-hygiene.log`, tournament scratch logs and
  `artifacts/rendering/statement-history/pytest-891/`.
  Offline field parity, comparison/formula/closing-balance inspection, keyboard
  activation, 1440×900 and 1280×800 screenshots and 125% CSS zoom pass without
  page errors or HTTP requests. Existing source-preview tests additionally cover
  narrow viewports, long hostile labels, null/conflicting/not-applicable cells
  and empty schedules. Visual review preserved Direction C and clarified scope.
  Charts are not applicable to these statement matrices. Complete Module and
  analytical/native acceptance remain unrun.

## Design-hook triage

Fixed: no CSS issue. Suppressed: the existing narrow `side-tab` exception for
`src/deploy_vii/assets/app.css` remains; no new ignore was added. The finding is
an intentional active-page navigation edge retained from Direction C, not a
card accent. Left standing: no unresolved design finding. Browser evidence and
fixture correctness do not imply a new visual baseline or analytical acceptance.
