# CP-1 narrative protocol review

Task `dvii-implementation-001`; base `46bdd32`, branch
`codex/development-environment`, coordinator owns checkout/publication. Previous
turn: progress (cumulative gap register committed). Scope: new narrative input,
review and report contracts; prior-row catalogue; evidence/coverage/story checks;
synthetic tests and documentation. No dependencies, arithmetic or frontend changes.
OpenRouter spend remains US$0 of the US$50 first-core qualification cap.

This advances Step 11 synthesis mechanics. It does not produce model-assisted
analytical qualification, completed Module delivery, browser or native acceptance.
Method source: pinned CP-1 Step 11/12 in ignored `artifacts/cp1-steps-reference.md`.

## Confidence review

Ranked doubts, investigation and outcomes:

1. **A finding could introduce new numbers or cite a substituted row.** Catalogue
   entries retain exact prior-row JSON, row/artifact hashes, namespaced identity
   and all citations. Reviews bind the full input hash. The validator recomputes
   the catalogue and KPI gate; external report validation recomputes every input
   from the actual pack/context/financial/definition/binding contracts. Tests
   alter catalogue content, delete entries, swap scope, change hashes and tamper
   reports. Numeric characters in title/prose/limitations, including full-width
   digits and fractions, are rejected after strict reconstruction. Verdict:
   mechanically verified; semantic paraphrases and spelled-out quantities remain
   open for model-assisted review and cannot be certified by this validator.
2. **Reference tokens could satisfy a required reasoning chain without analysis.**
   Reproduced a valid-looking finding whose entire risk mechanism was an issuer
   token; validation returned no issues. Risk and credit fields now require a
   nonblank prose part in addition to evidence/issuer requirements. Coverage and
   funding rationales likewise require prose. Regression rejects the empty chain.
   Verdict: confirmed and fixed; prose quality itself remains semantic work.
3. **Unrelated balance-sheet rows could be called operating float.** The initial
   material-funding fixture accepted a standard cash row. Restricted reviewed
   entries to actual located balance-sheet rows and material entries to named
   issuer detail, excluding standard assets/debt/payables/aggregates. Four
   regressions reject inappropriate standard items. A custom deposits row retains
   a required story; incomplete reviewed BS scope adds a gap. Verdict: confirmed
   and fixed structurally. Custom-row non-debt/non-interest-bearing meaning,
   materiality and refund/performance obligations still require source-grounded
   analytical verification; no name-based classifier is claimed.
4. **No-KPI inputs might produce unsupported financial synthesis.** Gate uses
   available numeric KPI values, not the existence of placeholder rows. Partial
   add-back disclosure produces data-quality-only inputs; financial findings fail
   while a data-quality chain remains possible. The report retains the gate gap.
   Verdict: verified fine; Python does not infer missing financial amounts.
5. **Required stories or dimensions could be hidden by empty declarations.**
   Checked duplicate dimension/story/finding IDs, dimensional finding membership,
   coverage-state consistency, not-applicable evidence, exact event/multi-figure
   links and material funding scope. Story finding IDs must exist and cite their
   own required entry. Missing stories produce BLOCK rows; absent dimensions stay
   unassessed. Tests cover events, multi-figure records, false links and funding.
   Verdict: verified mechanically; coverage completeness/materiality requires
   separate analytical assessment.
6. **Inherited gaps, source immutability or recomputation boundaries could weaken.**
   The report copies all upstream ledger rows before appending narrative gaps.
   Tests compare the exact prefix, reject deleted gaps/changed status/substituted
   reviews and check unchanged external inputs. Nested serialized records are
   reconstructed before lookup; model_copy numeric prose cannot bypass validation.
   Verdict: verified fine. validate_narrative_review alone validates its supplied
   bundle; only the full external recomputation boundary authenticates inputs.

Fixed: issuer-only reasoning chains and false funding designation of standard BS
rows. Initial local-variable typing, fixture item prefix and formatting issues
were corrected before verification. No additional confirmed issue remains in
this scoped protocol after reviewing the selected rewrite.

By design: a source-linked chain is still unqualified analysis. Funding is a
scoped analyst interpretation of prior BS detail, not new extraction. No figures
are calculated in this module. All old gaps remain, including unresolved DCF and
FFO coverage definitions. No unanswered user clarification is adopted.

Still open: model-assisted semantic review, full consumer readiness, source-first
execution order, canonical Markdown/Workbench projection, CP-1A and milestones
D–H. Global goal remains active, with no live spend or new Module acceptance.

## Scoped tournament

Only `_catalogue` and `validate_narrative_review` are selected in no-argument
post-edit mode: the immutable evidence and narrative validation boundaries.
Routine input/report assembly, prose check and wrappers receive focused tests and
confidence review. All roles explicitly use fresh GPT-6.1 Sol/high; coordinator
unchanged. GitNexus returned repository-not-found, so `rg` and strict mypy cover
callers: catalogue → input builder/validator → canonical narrative → external
report validator and tests. No CLI, execution or renderer caller exists yet.


Anonymous bracket: A = speed, B = memory, C = readability, D = incumbent.
Independent arbiter chose A over B, A over C, then A over D. Its three reasons
per match are recorded below; coordinator correctness is separate.

- A over B: explicit ordered list avoids overwrite/counter coupling; dimension
  and story indexes reduce repeated scans; funding reads authenticated catalogue
  records without duplicating the evidence-ID recipe.
- A over C: indexes reduce repeated scans; passage predicates remain beside their
  diagnostics; reused membership sets keep relationships explicit without adding
  a generic predicate helper.
- A over D: dimension membership is built once; story evidence is cached once per
  referenced finding; catalogue/funding sets express membership without unused
  values or repeated set construction.

**Winner: Snippet A.** `_catalogue` is unchanged; `validate_narrative_review`
uses dimension/funding indexes and a lazy story-evidence cache. Final code below.
Justification:

- The ordered catalogue, row/artifact hashes, citation order and duplicate
  rejection remain unchanged.
- Reused dimension, funding and story membership sets avoid repeated scans while
  retaining diagnostic ordering and duplicate-finding lookup semantics.
- Coordinator verification preserves serialized outputs, issues and input
  immutability on actual tests plus duplicate/coverage/story combinations; no
  benchmark or whole-module speed claim is made.

Coordinator backed up the complete file before applying A. The independent
comparison loads all four snippets in isolated function namespaces and runs the
narrative regression cases plus adversarial findings/coverage/story combinations.
All candidates matched the incumbent on 124 catalogue calls and 86 validation
calls each, including exact ordered diagnostics and unchanged inputs. The test
runner passed all 27 narrative tests. Seven literal dimensions exactly match the
indexed dimension set. Full source, caller paths and candidate diff were reviewed.

Commands and actual results:

- `uv run --locked python artifacts/narrative-tournament/compare.py`: 27 tests
  passed; 124 catalogue + 86 validator calls per candidate matched exactly.
- `uv run --locked pytest tests/product/test_narrative.py tests/product/test_canonical_gaps.py tests/product/test_source_context.py -q`:
  91 passed after applying the winner.
- `uv run --locked ruff check src/deploy_vii/narrative.py tests/product/test_narrative.py`:
  passed; matching `ruff format --check` passed for both files.
- `uv run --locked mypy src`: passed, 38 source files, including all callers.
- `make product-check`: passed lint, formatting, strict typing, JavaScript syntax
  and 696 product tests; combined branch coverage 97.29% (90% required).
- `make check`: passed locked dependency and all-file hygiene checks; both diff
  whitespace checks passed.
- `make secrets`: passed directory, staged diff and complete reachable-history
  scans with Gitleaks 8.30.1; no leaks found. No dependency change or audit needed.

Final confidence review found no further confirmed defect in the selected
rewrite. Invalid contracts still reconstruct before typed traversal; stale or
substituted catalogues fail before record JSON is trusted. Duplicate dimensions,
findings and story references retain exact diagnostic multiplicity and ordering.
The remaining analytical and delivery limits above are unchanged.

Design-hook triage: the existing side-tab finding is the intentional active-page
navigation marker in Direction C, not a new card accent. Existing narrow
`side-tab`/`*` exception applies only to `src/deploy_vii/assets/app.css` and cites
the preserved reference design. Fixed: no CSS change needed. Suppressed: retained
that existing exception, no new suppression. Left standing: the intentional
navigation marker; no unresolved design finding introduced by this increment.

## Final tournament code

Targets: `src/deploy_vii/narrative.py:134–209`, `src/deploy_vii/narrative.py:229–344`.

```python
def _catalogue(ledger: CanonicalGapReport) -> tuple[EvidenceRecord, ...]:
    result: list[EvidenceRecord] = []

    def add(kind: str, reference: str, artifact_hash: str, row: Contract) -> None:
        result.append(
            EvidenceRecord(
                evidence_id=_id("narrative-evidence", kind, reference),
                kind=kind,
                reference=reference,
                artifact_sha256=artifact_hash,
                record_sha256=row.content_hash(),
                record_json=row.model_dump_json(),
                citations=tuple(dict.fromkeys(records(row, Citation))),
            )
        )

    context, audit = ledger.context, ledger.audit
    context_hash, audit_hash, ledger_hash = (
        context.content_hash(),
        audit.content_hash(),
        ledger.content_hash(),
    )
    for source in context.sources:
        add("source", source.source_id, context_hash, source)
    for entity in context.entities:
        add("entity", entity.entity.entity_id, context_hash, entity)
    for event in context.events:
        add("subsequent_event", event.event_id, context_hash, event)
    for position in audit.source_positions:
        add("observation", position.observation.observation_id, audit_hash, position)
    statement_hash = audit.statements.content_hash()
    for cell in audit.statements.cells:
        add(
            "statement_" + cell.statement,
            _id("cell", cell.statement, cell.period_id, cell.item_id),
            statement_hash,
            cell,
        )
    for row in audit.normalizations:
        add("normalization", row.normalization_id, audit_hash, row)
    for definition in audit.definitions:
        add(
            "multi_figure_event" if definition.kind == "multi_figure_event" else "definition",
            definition.row_id,
            audit_hash,
            definition,
        )
    reconciliation_hash = audit.reconciliation.content_hash()
    for check in audit.reconciliation.checks:
        add("source_check", check.check_id, reconciliation_hash, check)
    for gap in ledger.gaps:
        add("gap", gap.gap_id, ledger_hash, gap)
    if ledger.kpis:
        kpis = ledger.kpis
        historical_hash, kpi_hash = kpis.historical.content_hash(), kpis.content_hash()
        for period in kpis.historical.periods:
            add("source_period", period.period_id, historical_hash, period)
        for construction in kpis.historical.constructions:
            add("construction", construction.construction_id, historical_hash, construction)
        for historical_value in kpis.historical.values:
            add("historical_value", historical_value.value_id, historical_hash, historical_value)
        for basis in kpis.bases:
            add("basis", basis.basis_id, kpi_hash, basis)
        for value in kpis.values:
            add("canonical_value", value.value_id, kpi_hash, value)
        for kpi in kpis.kpis:
            add("kpi", kpi.calculation_id, kpi_hash, kpi)
        for computation in kpis.computations:
            add("computation", computation.computation_id, kpi_hash, computation)
    if ledger.period_reconciliation:
        report_hash = ledger.period_reconciliation.content_hash()
        for period_check in ledger.period_reconciliation.checks:
            add("period_check", period_check.check_id, report_hash, period_check)
    if len(result) != len({r.evidence_id for r in result}):
        raise ValueError("Ambiguous narrative evidence identity")
    return tuple(result)

def validate_narrative_review(inputs: NarrativeInputs, review: NarrativeReview) -> tuple[str, ...]:
    """Validate against supplied inputs; canonical_narrative recomputes those inputs."""
    try:
        inputs = NarrativeInputs.model_validate_json(inputs.model_dump_json())
        review = NarrativeReview.model_validate_json(review.model_dump_json())
        if inputs.catalogue != _catalogue(inputs.ledger):
            return ("Narrative catalogue differs from its prior registers",)
        scope = (
            "financial_synthesis"
            if inputs.ledger.kpis
            and any(k.value.amount is not None for k in inputs.ledger.kpis.kpis)
            else "data_quality_only"
        )
        if inputs.scope != scope:
            return ("Narrative scope differs from available KPI evidence",)
    except ValueError as error:
        return (f"Invalid narrative contract: {error}",)
    issues: list[str] = []
    if review.inputs_sha256 != inputs.content_hash():
        issues.append("Narrative review does not bind current input registers")
    evidence = {r.evidence_id for r in inputs.catalogue}
    findings = {f.finding_id: f for f in review.findings}
    if len(findings) != len(review.findings):
        issues.append("Duplicate narrative finding identity")
    if len(review.coverage) != len({c.dimension for c in review.coverage}):
        issues.append("Duplicate narrative dimension coverage")
    if len(review.stories) != len({s.evidence_id for s in review.stories}):
        issues.append("Duplicate required-story coverage")
    for part in records(review, EvidencePart):
        if part.evidence_id not in evidence:
            issues.append(f"Unknown narrative evidence: {part.evidence_id}")
    dimension_findings: dict[Dimension, set[str]] = {d: set() for d in _DIMENSIONS}
    for finding in review.findings:
        dimension_findings[finding.dimension].add(finding.finding_id)
        if not any(isinstance(p, EvidencePart) for p in finding.evidence):
            issues.append(f"Finding lacks prior-register evidence: {finding.finding_id}")
        if not any(
            isinstance(p, IssuerPart)
            for p in (*finding.evidence, *finding.risk_mechanic, *finding.credit_implication)
        ):
            issues.append(f"Finding lacks explicit issuer binding: {finding.finding_id}")
        for name, passage in (
            ("risk", finding.risk_mechanic),
            ("credit", finding.credit_implication),
        ):
            if not any(isinstance(p, ProsePart) for p in passage):
                issues.append(f"Finding lacks {name} reasoning: {finding.finding_id}")
        if inputs.scope == "data_quality_only" and finding.dimension in _FINANCIAL:
            issues.append(f"Financial narrative requires an available KPI: {finding.finding_id}")
    for coverage in review.coverage:
        if not any(isinstance(p, ProsePart) for p in coverage.rationale):
            issues.append(f"Dimension lacks rationale: {coverage.dimension}")
        ids = coverage.finding_ids
        supplied = set(ids)
        if len(ids) != len(supplied) or any(
            i not in findings or findings[i].dimension != coverage.dimension for i in ids
        ):
            issues.append(f"Invalid dimension findings: {coverage.dimension}")
        if (coverage.status == "addressed") != bool(ids):
            issues.append(f"Dimension status contradicts findings: {coverage.dimension}")
        if supplied != dimension_findings[coverage.dimension]:
            issues.append(f"Dimension omits or contradicts supplied findings: {coverage.dimension}")
        if coverage.status == "not_applicable" and not any(
            isinstance(p, EvidencePart) for p in coverage.rationale
        ):
            issues.append(f"Inapplicable dimension lacks evidence: {coverage.dimension}")
    funding = review.funding
    reviewed, material = funding.reviewed_statement_ids, funding.material_statement_ids
    if not any(isinstance(p, ProsePart) for p in funding.rationale):
        issues.append("Funding assessment lacks rationale")
    balance_sheet = {
        r.evidence_id: StatementCell.model_validate_json(r.record_json)
        for r in inputs.catalogue
        if r.kind == "statement_BS"
    }
    reviewed_ids, material_ids = set(reviewed), set(material)
    for ids, distinct in ((reviewed, reviewed_ids), (material, material_ids)):
        if len(ids) != len(distinct) or any(
            i not in balance_sheet or balance_sheet[i].line_id is None for i in ids
        ):
            issues.append("Funding assessment requires distinct located prior balance-sheet rows")
    standard_items = {*REQUIRED_ITEMS["BS"], *OPTIONAL_ITEMS["BS"]}
    for evidence_id in material:
        cell = balance_sheet.get(evidence_id)
        if cell and (cell.line_kind != "detail" or cell.item_id in standard_items):
            issues.append(f"Funding story requires named non-debt liability detail: {evidence_id}")
    if not material_ids <= reviewed_ids:
        issues.append("Material funding rows must be part of the reviewed scope")
    if (funding.status == "material_items") != bool(material):
        issues.append("Funding conclusion contradicts material rows")
    if funding.status != "unassessed" and not reviewed:
        issues.append("Assessed funding conclusion requires reviewed balance-sheet scope")
    required = {
        r.evidence_id
        for r in inputs.catalogue
        if r.kind in {"subsequent_event", "multi_figure_event"}
    } | material_ids
    finding_evidence: dict[str, set[str]] = {}
    for story in review.stories:
        if story.evidence_id not in required:
            issues.append(f"Unknown required story: {story.evidence_id}")
        if len(story.finding_ids) != len(set(story.finding_ids)):
            issues.append(f"Duplicate story finding: {story.evidence_id}")
        for finding_id in story.finding_ids:
            story_finding = findings.get(finding_id)
            evidence_ids = finding_evidence.get(finding_id)
            if evidence_ids is None and story_finding is not None:
                evidence_ids = {
                    p.evidence_id for p in story_finding.evidence if isinstance(p, EvidencePart)
                }
                finding_evidence[finding_id] = evidence_ids
            if evidence_ids is None or story.evidence_id not in evidence_ids:
                issues.append(
                    f"Story finding lacks its required evidence: {story.evidence_id} {finding_id}"
                )
    return tuple(issues)
```
