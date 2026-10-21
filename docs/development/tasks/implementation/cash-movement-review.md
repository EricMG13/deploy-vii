# Cash movement increment review

Task `dvii-implementation-001`; coordinator owns this checkout and publication.
Base `55a29ea`, branch `codex/development-environment`. Implements explicit
source adjustments for the cash balance reconciliation within milestone C.
No module, live analytical, rendering or native-host acceptance is promoted.
OpenRouter spend remains US$0 of the US$50 first-core-batch cap.

## Scope and evidence

New input: `CashMovementBridge`, referencing signed source CFS detail rather than
accepting a calculated amount. Shared validation enforces period/line identity
and permitted detail. Source and constructed reconciliations retain the bridge,
source operands and citations. Explicit empty assessments differ from omission;
all contributing source checks must pass before assessed adjustments combine.
Review/source/period reconciliation versions advance to /3. Existing annual
exceptions and unadjusted cash comparisons retain their behavior.

Pinned requirement and compatibility: [cash movement](../../cash-movement.md).
New code is independently written; no Deploy VI implementation or policy is copied.
Changed paths: financial contracts/validation, cash_bridge, source and period
reconciliation, tests and development documentation. Existing Direction C CSS
and the narrow side-tab exception remain unchanged. That finding refers to the
intentional active navigation indicator retained in the required reference.

## Confidence review

Least confident about, ranked by likelihood and impact:

1. **Signed cash/perimeter math or double-counting FX.** Traced the identity
   `cash delta = NCF + adjustments` into source `_cash_movement`: compared
   components subtract the bridge coefficient after explicit outflow normalization.
   Tests cover both coefficient signs, positive outflow magnitudes, zero, negative
   and ten-place FX, ambient Decimal precision 1, original values and source IDs.
   A visible FX line without a bridge is not added; an empty assessed bridge can
   represent FX already included in reported NCF. Verdict: verified fine.
2. **Constructed periods hiding source failures.** Traced `_source_periods` to
   historical flow plans and `_period_cash` to the actual opening/closing boundary.
   Equal +1 source errors in H1 and Q1 would cancel arithmetically; the regression
   retains their operands and blocks before calculating. Missing adjustments,
   omitted assessments and missing LTM source periods stay null/BLOCK. Explicit
   empty assessments work only when their own source comparison passes.
   Verdict: verified fine; no missing-as-zero or cancellation shortcut.
3. **References bypassing input validation.** Both public APIs serialize and
   revalidate the review before indexing source lines. Tests reject independent
   duplicate-ID and duplicate-period cases, duplicate adjustment lines, unknown
   and period-end periods, same-ID lines existing only in another period,
   canonical/non-CFS/subtotal/identity-target lines. Numeric plug fields and
   boolean coefficients are rejected at the contract boundary. Verdict: verified
   fine within the validated-book precondition; private helpers are not APIs.
4. **Lost evidence or stale accepted results.** Traced nested citation validation,
   original/normalized source terms, period coefficients and copied bridge records.
   Forged citation hashes fail; changing/deleting a bridge invalidates both
   recomputation validators. Review hashes cover source observations and bridge
   structure. The record provides an equation, not an amount-bound waiver.
   Verdict: verified fine. No output amount/status is trusted without recomputation.
5. **Changing established behavior or overclaiming interpretation.** No-bridge
   comparisons keep the previous own-span boundary, including the existing derived
   quarter regression whose earlier source period lacks opening cash. Adjusted
   combinations deliberately require complete contributing assessments and source
   passes. `other:` detail classification still needs evidence-grounded analysis;
   matching a quote is not proof that a cash-perimeter adjustment is appropriate.
   Verdict: boundary behavior verified; analytical interpretation remains open.
6. **Precision, bounds, mutation and schema drift.** Arithmetic reuses the existing
   Decimal context and exact sign helpers. Input contracts bound periods, lines,
   adjustments and values. Explicit /1 and /2 inputs are rejected, with rebuild
   guidance. Coordinator comparisons covered 1,000 ordered validation results and
   144 complete serialized period cash records against the pre-rewrite snapshots,
   with unchanged input hashes/serialization. Verdict: verified fine.

Fixed: the missing representation for explicitly sourced cash adjustments and
its propagation into constructed-period checks. No additional confirmed defect
was found during this review. Synthetic fixture construction was corrected to
use strict tuples and the actual period plan before verification.

Verified fine: signs, no inferred FX, missing states, source-error propagation,
identity validation, citation/hash binding, schema rejection and baseline behavior,
by the tests and traced paths above.

By design: explicit source detail and a cited structural explanation may adjust
this comparison; foreign-currency debt conversion and Model cash forecasting are
separate. No inference from cash residuals or source labels is introduced.

Still open: live source interpretation, complete CP-1 registers, independent
operating/investing/financing-to-NCF completeness, remaining consumer readiness,
CP-1A and execution/Workbench integration. Pending user definitions for DCF and
FFO interest coverage remain unanswered; no option has been adopted.

## Scoped post-edit rewrite tournament

Only `cash_bridge_issues` and `_period_cash` received the tournament. Contract
fields and source report assembly received confidence review and focused tests;
no routine wrapper or UI tournament. All five roles used fresh GPT-6.1 Sol/high
contexts under the model matrix; coordinator settings stayed unchanged.

GitNexus context was attempted for both symbols; this repository is not indexed.
Fallback impact search is retained in `artifacts/cash-bridge-impact.txt`:
`cash_bridge_issues` feeds book/input validation and all financial adapters;
`_period_cash` feeds period reconciliation and Model readiness. The source helper
is also called by source reconciliation. Public recomputation validators consume
these paths. Strict typing and focused tests recheck that caller set.

Blind bracket: A beat B, then C, then D. **Winner: Snippet A**, applied to the two
functions below after backing up the original files in the ignored tournament
scratch directory.

- Avoids building three validation indexes when there are no bridge records.
- Uses a set for assessment membership without retaining unused bridge values.
- Keeps the source order, diagnostics, signs, blockers and evidence unchanged,
  with shorter local identity references and no additional abstraction.

Coordinator verification (not delegated):

```text
uv run pytest tests/product/test_cash_bridge.py tests/product/test_audit_basis.py tests/product/test_reconciliation.py tests/product/test_period_reconciliation.py tests/product/test_model_readiness.py tests/product/test_statements.py -q
149 passed
uv run mypy src
Success: no issues found in 33 source files
PYTHONPATH=. uv run python artifacts/cash-bridge-tournament/verify.py
1000 ordered validation results and 144 complete period cash records match; inputs unchanged
```

Concrete invariant: Q2 cash delta 44 − 22 less FX 2 equals reported NCF 20.
Constructed Q2: 44 − 22 − H1 FX 4 + Q1 FX 2 also equals 20. Equal wrong source
adjustments of 5 and 3 preserve the arithmetic equality but produce BLOCK.
The coordinator inspected the actual resulting diff and all new files.

## Final tournament code

`src/deploy_vii/cash_bridge.py:6–43`

```python
def cash_bridge_issues(book: FinancialBook) -> tuple[str, ...]:
    if not book.cash_movement_bridges:
        return ()
    periods = {p.period_id: p for p in book.periods}
    lines = {(r.period_id, r.line_id): r for r in book.statement_lines}
    targets = {(r.period_id, r.target_line_id) for r in book.statement_identities}
    ids: set[str] = set()
    assessed: set[str] = set()
    issues: list[str] = []
    for bridge in book.cash_movement_bridges:
        bridge_id, period_id = bridge.bridge_id, bridge.period_id
        if bridge_id in ids or period_id in assessed:
            issues.append(f"Duplicate cash movement bridge: {bridge_id}")
        ids.add(bridge_id)
        assessed.add(period_id)
        period = periods.get(period_id)
        if period is None or period.period_type == "PERIOD_END":
            issues.append(f"Cash movement bridge requires a flow period: {bridge_id}")
        seen: set[str] = set()
        for part in bridge.components:
            line_id = part.line_id
            if line_id in seen:
                issues.append(f"Duplicate cash adjustment line: {bridge_id} {line_id}")
            seen.add(line_id)
            key = period_id, line_id
            line = lines.get(key)
            if line is None:
                issues.append(f"Unknown cash adjustment line: {bridge_id} {line_id}")
            elif (
                line.statement != "CFS"
                or line.line_kind != "detail"
                or key in targets
                or not (line.item_id == "fx_cash_effect" or line.item_id.startswith("other:"))
            ):
                issues.append(
                    f"Cash adjustment requires a source FX/perimeter detail: {bridge_id} {line_id}"
                )
    return tuple(issues)
```

`src/deploy_vii/period_reconciliation.py:228–279`

```python
def _period_cash(
    book: FinancialBook,
    report: HistoricalReport,
    node: PeriodConstruction,
    reported: PeriodTerm,
    closing: PeriodTerm,
) -> PeriodCheck:
    """Combine assessed source adjustments without canceling unresolved inputs.

    Unadjusted legacy comparisons keep their own opening/closing boundary. Once
    any contributing source uses a bridge, every contribution must be assessed
    and its cash check must pass before the constructed check can agree.
    """
    opening = (
        node.start_date - timedelta(days=1)
        if node.start_date and node.start_date.toordinal() > 1
        else None
    )
    parts = [closing, _source(_balance(book, opening, "cash_and_equivalents", sign=-1))]
    sources = _source_periods(report, node)
    assessments = {b.period_id for b in book.cash_movement_bridges}
    adjusted = any(pid in assessments for pid, _ in sources)
    bridges: list[CashMovementBridge] = []
    contexts: list[Citation] = []
    blockers: list[str] = []
    if adjusted:
        periods = {p.period_id: p for p in book.periods}
        for pid, sign in sources:
            if pid not in assessments:
                parts.append(_cell(None, f"Unassessed cash bridge: {pid}", 1 if sign == 1 else -1))
                blockers.append(f"Unassessed cash bridge: {pid}")
                continue
            assert pid is not None
            source = _cash_movement(book, periods[pid])
            parts.extend(_source(term, sign) for term in source.components[2:])
            bridges.extend(source.cash_movement_bridges)
            contexts.extend(source.context_citations)
            if source.status != "PASS":
                blockers.append(f"{pid}: {source.explanation}")
    check = _compare(
        node,
        "NCF_CASH_MOVEMENT",
        "net_cash_change",
        reported,
        tuple(parts),
        "closing cash - opening cash - signed period combination of source adjustments"
        if adjusted
        else "closing cash - opening cash; no inferred FX plug",
        blocker=node.limitation or "; ".join(blockers) or None,
        context=tuple(contexts),
    )
    return check.model_copy(update={"cash_movement_bridges": tuple(bridges)})
```

## Final increment checks

`make product-check` passed: lint, formatting, strict typing (33 source files),
JavaScript syntax and 563 product tests, including the four existing browser
regressions. Combined coverage is 97.46%. Log:
`artifacts/cash-movement-product-check.log`. No frontend field/module changed;
this browser regression pass does not establish acceptance for a new Module.

`make check` and `make secrets` passed; file, staged-diff and reachable-history
secret scans found no leaks. Logs: `artifacts/cash-movement-hygiene.log` and
`artifacts/cash-movement-secrets.log`. The full 16-file candidate diff was
inspected, including new tests and review documentation. No dependency changed.
