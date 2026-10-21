# Cumulative CP-1 gap register review

Task `dvii-implementation-001`; base `2ca4097`, branch
`codex/development-environment`, coordinator owns checkout/publication. Previous
turn: progress (source/entity context committed). This advances T4.12 by combining
implemented source context, audit, constructed-period, reconciliation and KPI
registers. No Module, analytical, browser or native-host acceptance is promoted.
OpenRouter spend remains US$0 of the US$50 first-core qualification cap.

Scope: new `canonical_gaps.py`, explicit scope references in source-context output,
the source audit's optional facility-term exceptions, focused synthetic tests and documentation. No dependency, arithmetic or frontend
change. Pinned method: r14 CP-1 Step 12 cumulative-gap rule and model-interface
value-bearing-null rules in ignored `artifacts/cp1-steps-reference.md`.

## Confidence review

Ranked doubts, root paths and outcomes:

1. **Missing inputs or failed checks could disappear between registers.** Traced
   source context and audit rows, every null adapter input, historical value and
   construction operand, canonical value/KPI, unassessed KPI evidence, non-PASS
   period checks and artifact limitations. Tests compare originating ID sets with
   ledger references, retain exact check severities and validate all originating
   artifact hashes. Known zero remains a value. Verdict: verified for implemented
   registers; narrative and full consumer readiness still require implementation.
2. **Period labels could conceal the actual affected inputs.** Reproduced a
   missing H1 operand in a derived Q2, where the first implementation retained only
   Q2's construction ID and dates. Changed operand gaps to retain the parent and
   actual source/construction operand scopes. KPI gaps similarly retain display
   basis plus every actual signed-operand basis, including trailing-year inputs.
   Regressions compare exact scope IDs/dates and complete operand basis sets.
   Verdict: confirmed and fixed, without changing financial arithmetic.
3. **Overloaded source-context references could attach unrelated dates.**
   Reproduced an entity ID `issuer` colliding with a scope ID `issuer`: a
   cross-source currency warning incorrectly received only that scope's dates.
   Context gaps now carry explicit `scope_ids`, populated at their point of
   creation for scope limitations, basis differences and subsequent events.
   Source context output advances to `source-context/2`; review input remains /1.
   The ledger follows only those references. Regression requires both scopes.
   Verdict: confirmed and fixed at the originating contract boundary.
4. **Invalid binding could masquerade as readiness or prevent seeing gaps.**
   Schema-invalid inputs raise. Structurally valid stale hashes, unknown entities
   and incompatible source scopes produce exact BLOCK diagnostics while source
   registers remain visible. Calculation status describes generation only; it
   does not waive binding issues or grant readiness. Tests cover all three paths.
   Verdict: verified fine; this is a diagnostic register, not an acceptance gate.
5. **Incomplete disclosure could either become zero or hide a computation bug.**
   The existing adapter preflight rejects incomplete add-back assessments. Only
   that preflight's ValueError is represented as blocked generation, preserving
   source gaps with null calculation artifacts. An error in subsequent KPI
   computation propagates; an injected calculation defect verifies that boundary.
   Verdict: verified fine. No broad catch makes a broken calculation plausible.
6. **Nested unvalidated objects, substituted reports, ordering or collisions.**
   Reconstruct all five input contracts before traversal, recompute upstream
   artifacts, hash full gap details and remove only exact duplicates. Tests cover
   serialized nested objects, stale schema, deleted gaps/calculations, altered
   issue lists, substituted definition review, stable reruns and identical warning
   text from distinct origins. Source inputs remain unchanged. Verdict: verified
   fine mechanically; model-authored source interpretation is not authenticated.
7. **Null metadata or optional comparison fields could become spurious gaps.**
   Required missing values and unknown evidence tiers are represented. Optional
   absent stated-comparison amounts, non-ratio denominator objects and reference
   metadata are not treated as missing numerical observations. Original reasons,
   notes, alternatives and artifacts remain embedded. Verdict: by design; the
   register does not infer applicability or settle a definition.

8. **Inherited optional-term nulls could become false cumulative warnings.**
   The pinned model interface explicitly exempts an unstated floor, floating
   facility fixed coupon and fixed facility spread. The prior source audit warned
   on all non-known observations and left all of them unassessed. Three concrete
   regressions failed. Corrected the originating audit to exclude only those
   missing/not-applicable terms from missing-value and definition-coverage gaps,
   retaining the original observations and every conflict. Three adversarial
   conflicting-term cases remain BLOCK, and null annual amortisation remains a
   gap. Output advances to `canonical-audit/2`; definition-review/1 is unchanged.
   Verdict: confirmed and fixed. The targeted classification correction receives
   direct regressions and confidence review; the tournament remains capped at
   the two aggregation/provenance functions.

Fixed: derived-operand scope omission, overloaded context reference collision and
false missing-value warnings for the three pinned optional-term cases.
Initial mypy variable reuse and test fixture key mistakes were corrected before
verification. An expensive test-side repeated hash was hoisted; no performance
claim depends on that test cleanup.

Still open: source interpretation, analytical narrative, full consumer readiness,
CP-1/Model execution and Workbench binding, CP-1A and remaining milestones D–H.
DCF and FFO coverage questions remain pending; unavailable rows stay visible.

## Tournament scope

Only `_calculation_gaps` and `canonical_gaps` enter the no-argument post-edit
rewrite tournament, using fresh GPT-6.1 Sol/high roles under the requested matrix.
The source-context field propagation, schema declaration and recomputation wrapper
receive focused tests and confidence review. No arithmetic changes or broader
branch sweep. GitNexus returned repository-not-found; `rg` reference discovery and
strict typing cover the impact set: calculation-gap helper → ledger assembly →
external ledger validator and tests. No execution/renderer callers exist yet.


**Winner: Snippet A.** The blind bracket selected A over B, C and D. Coordinator
backed up the file and applied `_calculation_gaps` at
`src/deploy_vii/canonical_gaps.py:61-293` and `canonical_gaps` at lines 296-463,
wrapped long literals for
repository lint and verified AST identity with A. Signatures are unchanged.

Justification:

- Reuses immutable artifact hashes instead of serializing full nested reports for
  every limitation or binding issue, with unchanged identities and row ordering.
- Transfers already validated frozen period/citation values into ledger rows via
  a shallow field mapping; normal model validation and external JSON boundaries
  remain in place.
- Retains the explicit stage loops and exact full-detail deduplication, without
  extra manual cleanup points or positional schema copies.

Coordinator verification:

- `uv run python artifacts/canonical-gaps-tournament/differential.py`: 48 public
  ledger calls and three calculation-gap calls each compared to all three
  challengers (153 exact outcome/serialization comparisons), with unchanged
  serialized inputs. Covers three source fixtures, zeros, missing disclosure,
  stale/duplicate/empty bindings, unknown entities/books, source scope variations
  and nested serialized inputs. Invalid cases retain exact exception outcomes.
- The same scratch check timed five base-fixture builds: incumbent 0.3007s,
  A 0.1973s, B 0.1942s, C 0.3323s. This is a local smoke measurement, not a
  production benchmark or analytical qualification.
- `uv run pytest tests/product/test_canonical_gaps.py tests/product/test_source_context.py tests/product/test_canonical_audit.py tests/product/test_canonical_kpis.py tests/product/test_period_reconciliation.py -q`:
  121 passed with A applied.
- `uv run mypy src`: success, 37 source files. The full impacted caller set
  compiles and the external recomputation/tampering regressions pass.
- `uv run ruff check src/deploy_vii/canonical_gaps.py tests/product/test_canonical_gaps.py`:
  passed after literal wrapping and test-helper annotations.

Confidence follow-up: cached hashes identify the same immutable reports and are
never shared across calls. Shallow field transfer retains frozen nested values,
while all externally supplied inputs still undergo JSON reconstruction. Exact
serialization checks, caller typing and adversarial regressions verify these
changes; no extra confirmed issue remains in this scoped aggregation.

Final code:

```python
def _calculation_gaps(
    kpis: CanonicalKpiReport, reconciliation: PeriodReconciliationReport
) -> tuple[GapDetail, ...]:
    """Keep calculation failures, caveats and original basis identities together."""
    historical = kpis.historical
    historical_hash, kpi_hash, check_hash = (
        historical.content_hash(),
        kpis.content_hash(),
        reconciliation.content_hash(),
    )
    constructions = {
        row.construction_id: GapPeriod(
            kind="construction",
            reference=row.construction_id,
            label=row.label,
            start_date=row.start_date,
            end_date=row.end_date,
        )
        for row in historical.constructions
    }
    bases = {
        row.basis_id: GapPeriod(
            kind="basis",
            reference=row.basis_id,
            label=row.label,
            start_date=row.start_date,
            end_date=row.end_date,
        )
        for row in kpis.bases
    }
    source_periods = {
        p.period_id: GapPeriod(
            kind="source",
            reference=p.period_id,
            label=p.period_id,
            start_date=p.start_date,
            end_date=p.end_date,
        )
        for p in historical.periods
    }
    result: list[GapDetail] = []

    def append(
        origin: str,
        artifact: str,
        reference: str,
        metric: str | None,
        periods: tuple[GapPeriod, ...],
        description: str,
        severity: Literal["WARN", "BLOCK"] = "WARN",
        citations: tuple[Citation, ...] = (),
    ) -> None:
        result.append(
            GapDetail(
                origin=origin,
                artifact_sha256=artifact,
                reference=reference,
                metric=metric,
                periods=periods,
                description=description,
                severity=severity,
                citations=citations,
                downstream_impact="Affected period and metric remain limited for downstream use",
                recommended_action=(
                    "Resolve the cited input or retain the limitation; rerun affected calculations"
                ),
            )
        )

    def value_gap(
        origin: str,
        artifact: str,
        reference: str,
        metric: str,
        periods: tuple[GapPeriod, ...],
        value: PeriodValue,
    ) -> None:
        if (
            value.amount is None
            or value.reason
            or value.note
            or value.calculation_status not in {"Verified", "Calculated"}
        ):
            append(
                origin,
                artifact,
                reference,
                metric,
                periods,
                "; ".join(
                    dict.fromkeys(
                        part
                        for part in (
                            f"{metric}: {value.calculation_status}",
                            value.reason,
                            value.note,
                            "Value unavailable" if value.amount is None else None,
                        )
                        if part
                    )
                ),
                "BLOCK" if value.calculation_status == "Conflicted" else "WARN",
                value.citations,
            )

    if not historical.columns:
        append(
            "construction",
            historical_hash,
            "display-periods",
            None,
            (),
            "No historical display periods could be constructed",
            "BLOCK",
        )
    observations = {o.observation_id: o for o in historical.observations}
    for i, input_row in enumerate(historical.input_rows):
        if input_row.adapter_amount is None:
            observation = (
                observations.get(input_row.observation_id) if input_row.observation_id else None
            )
            append(
                "historical_input",
                historical_hash,
                f"input:{i}",
                input_row.series_key,
                (source_periods[input_row.period_id],),
                observation.reason
                if observation and observation.reason
                else "Adapter input unavailable",
                "BLOCK" if observation and observation.status == "conflicting" else "WARN",
                tuple(records(observation, Citation)) if observation else (),
            )
    for node in historical.constructions:
        period = constructions[node.construction_id]
        for text in (
            node.limitation,
            "Constructed period dates are incomplete"
            if period.start_date is None or period.end_date is None
            else None,
            "Construction has unavailable period operands"
            if any(t.kind == "missing" for t in node.terms)
            else None,
        ):
            if text:
                append("construction", historical_hash, node.construction_id, None, (period,), text)
    for row in historical.values:
        period = constructions[row.construction_id]
        value_gap(
            "historical_value", historical_hash, row.value_id, row.series_key, (period,), row.value
        )
        for i, operand in enumerate(row.operands):
            ref = operand.reference
            operand_period = (
                source_periods[ref.reference]
                if ref.kind == "period" and ref.reference
                else constructions[ref.reference]
                if ref.kind == "construction" and ref.reference
                else None
            )
            value_gap(
                "historical_operand",
                historical_hash,
                f"{row.value_id}:{i}",
                row.series_key,
                tuple(dict.fromkeys((period, operand_period))) if operand_period else (period,),
                operand.value,
            )
    for check in reconciliation.checks:
        if check.status != "PASS":
            append(
                "period_reconciliation",
                check_hash,
                check.check_id,
                check.metric_id,
                (constructions[check.construction_id],),
                check.explanation,
                check.status,
                tuple(dict.fromkeys(records(check, Citation))),
            )
    for basis in kpis.bases:
        for text in (
            basis.limitation,
            "Calculation basis dates are incomplete"
            if basis.start_date is None or basis.end_date is None
            else None,
        ):
            if text:
                append("basis", kpi_hash, basis.basis_id, None, (bases[basis.basis_id],), text)
    for value in kpis.values:
        value_gap(
            "canonical_value",
            kpi_hash,
            value.value_id,
            value.key,
            (bases[value.basis_id],),
            value.value,
        )
    values = {v.value_id: v for v in kpis.values}
    for kpi in kpis.kpis:
        period = bases[kpi.display_basis_id]
        affected = tuple(
            dict.fromkeys(
                (
                    period,
                    *(
                        bases[values[operand.value_id].basis_id]
                        for leg in (kpi.numerator, kpi.denominator)
                        if leg
                        for operand in leg.operands
                    ),
                )
            )
        )
        value_gap("kpi", kpi_hash, kpi.calculation_id, kpi.key, affected, kpi.value)
        if kpi.evidence_quality_tier is None:
            append(
                "kpi_evidence",
                kpi_hash,
                kpi.calculation_id,
                kpi.key,
                (period,),
                kpi.evidence_limitation,
                citations=kpi.value.citations,
            )
    for origin, report, report_hash in (
        ("historical", historical, historical_hash),
        ("canonical_kpis", kpis, kpi_hash),
        ("period_reconciliation", reconciliation, check_hash),
    ):
        for limitation in report.limitations:
            append("report_limitation", report_hash, origin, None, (), limitation)
    return tuple(result)

def canonical_gaps(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
) -> CanonicalGapReport:
    # Reconstruct before traversal, including nested model_copy/model_construct inputs.
    pack = PreparedPack.model_validate_json(pack.model_dump_json())
    context = SourceContextReview.model_validate_json(context.model_dump_json())
    financial = FinancialReview.model_validate_json(financial.model_dump_json())
    definition = DefinitionReview.model_validate_json(definition.model_dump_json())
    binding = FinancialContextBinding.model_validate_json(binding.model_dump_json())
    context_report = source_context(pack, context)
    audit = canonical_audit(pack, financial, definition)
    binding_issues = validate_financial_context(pack, context, financial, binding)
    book = next(b for b in financial.books if b.book_id == definition.book_id)
    source_periods = {
        p.period_id: GapPeriod(
            kind="source",
            reference=p.period_id,
            label=p.period_id,
            start_date=p.start_date,
            end_date=p.end_date,
        )
        for p in book.periods
    }
    scopes = {
        s.scope_id: GapPeriod(
            kind="context",
            reference=s.scope_id,
            label=s.period_label,
            start_date=s.start_date,
            end_date=s.end_date,
        )
        for source in context.sources
        for s in source.scopes
    }
    context_hash, audit_hash = context_report.content_hash(), audit.content_hash()
    details: list[GapDetail] = []
    for gap in context_report.gaps:
        details.append(
            GapDetail(
                origin="context",
                artifact_sha256=context_hash,
                reference=gap.gap_id,
                metric=None,
                periods=tuple(scopes[scope_id] for scope_id in gap.scope_ids),
                description=gap.description,
                severity="BLOCK"
                if gap.reference == "file-gate" and gap.category == "source"
                else "WARN",
                downstream_impact=(
                    "Source authority, entity scope or event treatment requires review"
                ),
                recommended_action=(
                    "Resolve the located source-context gap or retain its limitation"
                ),
                citations=gap.citations,
            )
        )
    for audit_gap in audit.gaps:
        details.append(
            GapDetail(
                origin="source_audit",
                artifact_sha256=audit_hash,
                reference=audit_gap.gap_id,
                metric=audit_gap.reference,
                periods=tuple(source_periods[p] for p in audit_gap.period_ids),
                description=audit_gap.description,
                severity=audit_gap.severity,
                downstream_impact=audit_gap.downstream_impact,
                recommended_action=audit_gap.recommended_action,
                citations=audit_gap.citations,
            )
        )
    binding_hash = binding.content_hash() if binding_issues else ""
    for issue in binding_issues:
        details.append(
            GapDetail(
                origin="context_binding",
                artifact_sha256=binding_hash,
                reference=book.book_id,
                metric=None,
                periods=(),
                description=issue,
                severity="BLOCK",
                downstream_impact=(
                    "Financial evidence is not bound to the declared source/entity context"
                ),
                recommended_action=(
                    "Correct the explicit binding and source scopes; do not infer compatibility"
                ),
                citations=(),
            )
        )
    # Retain a source-stage ledger when the Model adapter cannot accept the inputs.
    calculation_issues: tuple[str, ...] = ()
    try:
        kernel_registers(pack, financial, book.book_id)
    except ValueError as error:
        calculation_issues = (str(error),)
    kpis = None
    reconciliation = None
    if calculation_issues:
        for issue in calculation_issues:
            details.append(
                GapDetail(
                    origin="calculation_gate",
                    artifact_sha256=financial.content_hash(),
                    reference=book.book_id,
                    metric=None,
                    periods=(),
                    description=issue,
                    severity="BLOCK",
                    downstream_impact="Constructed-period and KPI registers cannot be generated",
                    recommended_action=(
                        "Complete the source assessments required by the calculation adapter"
                    ),
                    citations=book.addback_disclosure.citations,
                )
            )
    else:
        kpis = canonical_kpis(pack, financial, book.book_id)
        reconciliation = reconcile_periods(pack, financial, book.book_id)
        details.extend(_calculation_gaps(kpis, reconciliation))
    for origin, report, report_hash in (
        ("context", context_report, context_hash),
        ("source_audit", audit, audit_hash),
    ):
        for limitation in report.limitations:
            details.append(
                GapDetail(
                    origin="report_limitation",
                    artifact_sha256=report_hash,
                    reference=origin,
                    metric=None,
                    periods=(),
                    description=limitation,
                    severity="WARN",
                    downstream_impact="The originating artifact's scope remains limited",
                    recommended_action=(
                        "Retain the limitation when presenting or using this artifact"
                    ),
                    citations=(),
                )
            )
    gaps = tuple(
        LedgerGap(gap_id=_id("cp1-gap", book.book_id, detail.content_hash()), **dict(detail))
        for detail in dict.fromkeys(details)
    )
    return CanonicalGapReport(
        context=context_report,
        binding=binding,
        binding_issues=binding_issues,
        audit=audit,
        calculation_status="blocked" if calculation_issues else "generated",
        calculation_issues=calculation_issues,
        kpis=kpis,
        period_reconciliation=reconciliation,
        gaps=gaps,
        limitations=(
            "Cumulative implemented-register gaps only; narrative "
            "and full consumer readiness remain separate",
            "Generated calculations and absence of a gap do not "
            "establish analytical or Module acceptance",
        ),
    )
```


Post-tournament method check: added six source-term exception/conflict regressions;
the focused command above now passes 127 tests. Full product checks are rerun
after this source-audit correction. Both selected aggregation functions remain
AST-identical to the verified rewrite; only their recomputed upstream input changes.


The differential check was repeated after the source-audit method correction:
all 153 exact comparisons still pass, including input immutability. Updated local
five-build timings were D 0.3252s, A 0.2158s, B 0.2148s and C 0.3564s. These remain
smoke measurements only; no production speed or memory claim is made.


## Final checks and remaining work

- `make product-check`: passed after the method correction; 669 product tests,
  97.46% combined coverage, strict typing across 37 source files, lint/format and
  JavaScript syntax checks. Earlier 663-test run preceded the six new regressions.
- `make check`: passed locked dependency and all repository hygiene checks.
- `make secrets`: passed working files, staged diff and all reachable Git history;
  Gitleaks 8.30.1 reported no leaks.
- Coordinator inspected the complete candidate sources, tests, documentation and
  final diff. No dependency changes; no dependency audit needed.
- No frontend changes or new design suppression. The existing narrow side-tab
  exception still covers the intentional Direction C active navigation edge.
- No live/model-assisted analytical tests. OpenRouter spend remains US$0 of US$50.

Next: add evidence-risk-credit narrative and full requested-consumer readiness,
then connect CP-1/Model artifacts to execution and the Workbench. CP-1A and
milestones D–H remain outstanding. Keep unknown DCF and FFO coverage definitions
explicit; no unanswered clarification is treated as adoption. This is progress
on the full active goal, not completion or qualification of CP-1.
