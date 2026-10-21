# Constructed-period reconciliation review

Base `ddab4d4`, branch `codex/development-environment`, 21 October 2026.
Scope: `period_reconciliation.py`, the additive `REPORTED_DERIVED_PERIOD` check
kind, corrected Model limitation text and synthetic tests. No new dependencies, UI or live-model calls.

## Confidence review

Least confident about, ranked:

1. Circular construction could receive independent PASS. Investigated the actual
   observation IDs retained by historical values, including Q4 = FY − nine months.
   Comparison now records shared observations and returns WARN on agreement;
   a shared-source mismatch still blocks. `independent` is a structural property
   of a numeric comparison and remains true for an independent mismatch. Tests
   prove the circular FY case and direct-quarter independent case separately.
   Verdict: fine within this explicitly structural meaning; source interpretation
   and analytical independence still require qualification.
2. A partial or defective source CFO identity could disappear during subtraction.
   The traversal follows construction references recursively but expands FY/YTD
   period references only to immediate reported children, matching the kernel's
   flow reader. It preserves signs, duplicates and explicit missing leaves. Every
   source CFO equation is independently checked first; incomplete or numerically
   blocked equations suppress the derived calculation. Tests cover missing
   leaves/disclosure, wrong source equations, missing LTM references and equal
   errors that would cancel numerically. Verdict: fine. During implementation,
   missing-reference traversal was made explicit before accepting the tests;
   no partial CFO subtotal can escape as a known calculated value.
3. Model residuals or a separately reported amount could validate themselves.
   The new checks read canonical historical input values and original source
   equation leaves, never statement residuals. A separately stated LTM 999 stays
   beside its computed 110, with difference −889 and BLOCK. Net cash movement
   uses opening/closing balances at the actual quarter dates; an unexplained
   one-unit difference stays BLOCK. Verdict: fine. FX and audited/unaudited
   exceptions remain open source-backed work, not inferred fixes.
4. Leases, FX, presentation and missing disclosures could silently change the
   comparison basis. Tests verify both lease classes are excluded from canonical
   debt, a foreign carrying value blocks, segment non-disclosure warns with null,
   and mixed expense presentation blocks. Stable segment/add-back/facility IDs
   come from validated source contracts. Missing values cannot cancel to zero.
   Verdict: fine for supported comparisons. Mixed presentation requires explicit
   comparable treatment; no readiness claim is made.
5. Decimal precision or status priority could hide differences. All sums preserve
   operand order under the shared 38-digit half-even context. Tolerance retains
   the reported Decimal exponent; difference is unrounded. Exact-half-tolerance,
   just-above-tolerance, shared-source mismatch and blocker-over-warning tests
   pass, as does hostile ambient precision. Verdict: fine.
6. The report could accept tampered values or omit provenance. It embeds the
   frozen historical report and original observations; terms retain observation
   IDs/citations and historical value IDs where available. Regeneration checks
   the entire content hash. Dropped checks, nonfinite forged output and unknown
   book identity are rejected. No unvalidated external graph reaches traversal.
   Verdict: fine. Private functions assume the validated bounded plan; this is
   not an arbitrary graph API.
7. Fixture success could imply product completion. All new evidence is synthetic.
   Full Model readiness, source-backed exceptions, remaining canonical KPIs,
   CP-1A, journal/HTML integration and public/native qualification remain open.
   The DCF definition question is still pending without an adopted default.
   Verdict: explicitly incomplete product; this increment advances reconciliation.

Fixed: missing period terms remain explicit; source CFO defects cannot cancel;
separately reported FY/LTM comparisons are retained; circular agreement is labelled.
Verified fine: arithmetic/precision, source ordering, debt basis, nulls, mismatches,
provenance and deterministic validation as above. Fixture validation correctly
rejected reused facility observation IDs and an absent segment allocation; fixtures
were corrected using distinct facility identities and explicit allocation.
By design: structural independence only, mixed-presentation block, no inferred FX,
source interpretation/qualification separate, no readiness promotion.
Still open: the remaining product boundaries in item 7 and source-backed exceptions.

## Scoped post-edit tournament

Selected only `_compare` and `_source_periods` (including nested `visit`): the
key financial comparison and provenance traversal. Other functions assemble
existing source checks and historical values; they received focused testing and
confidence review. All five roles used fresh GPT-6.1 Sol/high contexts under the
user's model matrix. Coordinator settings stayed unchanged.

GitNexus reported that this repository has no index. `rg` established callers:
`_bridges`, `_cfo`, `_years`, `_stated`, then public `reconcile_periods` and
`validate_period_reconciliation`. Strict mypy is the caller-contract oracle.

**Winner: Incumbent holds.** The anonymous static bracket selected A over B,
C over A, C over D. Coordinator backed up the current file and applied C, but
strict typing rejected assignment of a variable-length tuple to its inferred
single-item tuple. C was rejected and the backup restored; no challenger code
remains. Restored incumbent typing and all focused checks pass.

- The incumbent preserves financial eligibility, Decimal order and status priority.
- Its source traversal follows actual kernel reference boundaries without
  cancellation or omission of missing evidence.
- No challenger both improved the implementation and passed the complete checks;
  static readability preference alone did not justify replacement.

Coordinator differential verification compared all four candidates on 1,000
seeded comparison cases, 16 real construction nodes and three adversarial
traversal cases. Complete output and lookup exceptions matched. No speed or
memory benchmark claim is made. The accepted functions follow.

```python
def _compare(
    node: PeriodConstruction,
    kind: CheckType,
    metric: str,
    reported: PeriodTerm,
    parts: tuple[PeriodTerm, ...],
    formula: str,
    *,
    blocker: str | None = None,
    warning: str | None = None,
    context: tuple[Citation, ...] = (),
) -> PeriodCheck:
    origins = {oid for part in parts for oid in part.observation_ids}
    shared = tuple(oid for oid in reported.observation_ids if oid in origins)
    with localcontext(CONTEXT):
        calculated = (
            sum((p.amount * p.coefficient for p in parts if p.amount is not None), Decimal(0))
            if parts and all(p.amount is not None for p in parts) and not blocker
            else None
        )
        tolerance = (
            Decimal("0.5").scaleb(int(reported.amount.as_tuple().exponent))
            if reported.amount is not None
            else None
        )
        difference = (
            calculated - reported.amount
            if calculated is not None and reported.amount is not None
            else None
        )
        status: Literal["PASS", "WARN", "BLOCK"] = "BLOCK"
        explanation = blocker or "Reported value or independent components are unavailable"
        if difference is not None and tolerance is not None:
            if abs(difference) > tolerance:
                explanation = "Difference exceeds reporting-precision tolerance; unresolved"
            elif shared:
                status, explanation = (
                    "WARN",
                    "Shared source observations: construction agreement only",
                )
            else:
                status, explanation = "PASS", "Independent agreement within reporting precision"
        if warning and not blocker and difference is None:
            status, explanation = "WARN", warning
    return PeriodCheck(
        check_id=_id("period-check", node.construction_id, kind, metric),
        construction_id=node.construction_id,
        check_type=kind,
        metric_id=metric,
        reported=reported,
        components=parts,
        calculated_value=calculated,
        difference=difference,
        tolerance=tolerance,
        independent=not shared and difference is not None,
        shared_observation_ids=shared,
        status=status,
        formula=formula,
        explanation=explanation,
        context_citations=tuple(dict.fromkeys(context)),
    )


def _source_periods(
    report: HistoricalReport, node: PeriodConstruction
) -> tuple[tuple[str | None, int], ...]:
    """Follow the flow plan to source periods; retain opposite signed terms."""
    nodes = {n.construction_id: n for n in report.constructions}
    periods = {p.period_id: p for p in report.periods}
    result: list[tuple[str | None, int]] = []

    def visit(current: PeriodConstruction, sign: int) -> None:
        if not current.terms:
            result.append((current.own_period_id, sign))
            return
        for term in current.terms:
            coefficient = sign * term.coefficient
            if term.kind == "construction" and term.reference is not None:
                visit(nodes[term.reference], coefficient)
            elif term.kind == "period" and term.reference is not None:
                period = periods[term.reference]
                # The kernel's flow component reads immediate reported children.
                ids = (
                    period.component_period_ids
                    if period.period_type in {"YTD", "FY"} and period.component_period_ids
                    else (period.period_id,)
                )
                result.extend((pid, coefficient) for pid in ids)
            else:
                result.append((None, coefficient))

    visit(node, 1)
    return tuple(result)

```

## Verification

- `uv run --locked pytest tests/product/test_period_reconciliation.py tests/product/test_financial_periods.py tests/product/test_reconciliation.py -q`: 58 passed.
- `uv run --locked mypy src`: 29 source files passed after incumbent restoration.
- `make product-check`: 480 passed, 97.34% coverage; Ruff lint/format, mypy and JavaScript syntax passed. The tested incumbent was restored byte-for-byte after rejecting the challenger.
- After correcting the Model limitation text, `uv run --locked pytest tests/product/test_financial_model.py tests/product/test_period_reconciliation.py -q`: 39 passed; strict mypy passed again.
- `make check`: passed for locked environment, full-file hooks and both diff checks.
- `make secrets`: files, staged changes and reachable history passed with no leaks. No dependency changes required an audit.

No CSS changed. The existing narrow `side-tab` exception still covers the
intentional Direction C active navigation indicator; no new suppression or
unresolved design finding was introduced.
