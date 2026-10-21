# CP-1 downstream readiness review

Task `dvii-implementation-001`; base `0bca5b3`, branch
`codex/development-environment`. Coordinator owns this checkout and publication.
Previous goal turn: progress (narrative protocol committed). Scope: Step 12
consumer sufficiency contracts, requested aliases, cumulative gap scope,
deterministic statuses and always-present historical Model row. No dependencies,
arithmetic, frontend or live-model changes. Spend remains US$0 / US$50.

Pinned method: Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`, CP-1 Step 12
and the Model interface requirements (local ignored `artifacts/cp1-steps-reference.md`).
No old implementation or policy was copied. A/B remain implementation increments;
C–H and analytical/rendering/native-host qualification remain outstanding.

## Confidence review

1. **Incomplete financial evidence could establish sufficiency.** Reproduced a
   limited cash-flow requirement using only a null FCF row: the validator returned
   no issues. Compatible numeric evidence now needs an actual amount for both
   sufficient and limited claims. A missing requirement remains possible with an
   explicit action. A second adversarial case cited one available KPI for a
   sufficient complete dashboard despite unresolved/null other KPIs. Step 12
   explicitly requires all KPIs; the new completeness guard rejects that claim.
   Limited use does not pretend the full dashboard is complete. Both cases have
   regression tests. Semantic completeness of periods/definitions remains open.
2. **Nested input copies could bypass typed traversal.** Reproduced a financial
   review whose books were serialized dictionaries: canonical source checks
   reconstructed them internally but the new input assembler then accessed the
   original dictionaries and raised AttributeError. Normalize FinancialReview
   before any book access. The regression accepts equivalent serialized nested
   input while retaining its exact hash and prior narrative binding.
3. **Gap omission or exclusion could manufacture readiness.** Every requested
   consumer receives a row even without assessment; unassessed requirements and
   gaps force not_ready. Unknown, duplicate and overlapping gap scopes fail;
   exclusions require evidence and rationale. Relevant BLOCK severity is retained;
   context/source-binding BLOCKs are non-excludable. The complete input ledger is
   unchanged even for a consumer-specific exclusion. Synthetic database scope
   tests retain failed financial checks without waiving the independent Model gate.
   Whether a non-integrity gap is truly irrelevant is an explicit unqualified
   analytical judgment, not an automatic resolution or lost warning.
4. **A consumer verdict could authorize Model export.** Model status is calculated
   independently, always present, and additionally blocked by source integrity.
   A ready historical report with a stale context binding becomes blocked here.
   Three complete quarters remain partial, never ready. Omission of CP-MODEL does
   not become not_applicable. Selected historical scope does not qualify forecasts,
   pro forma or workbook delivery. Tests cover empty requests, source binding,
   partial selection and relevant financial reconciliation failures.
5. **Aliases or substitutions could evade dependencies.** CP-4A and CP-5A retain
   their specific Step 12 requirements; other aliases preserve entry identity and
   inherit the physical dependency map. Unknown/upstream/duplicate requests fail.
   A copied policy, changed request, external review swap, changed quarter scope,
   deleted gap register or forged Model status fails external recomputation.
   Registry entries beyond Step 12 carry an explicit consumer-specific assessment
   policy; this does not bypass their execution graph prerequisites.
6. **Compatibility checks could be mistaken for qualified analysis.** Minimum
   evidence families and numeric availability reject entity-only financial claims;
   they do not prove full scope, issuer-specific meanings or covenant treatment.
   The selected source book retains complete metadata. Every report fixes analytical
   qualification to unrun; synthetic judgments exercise protocol behavior only.
   Full CP-1 Markdown/Workbench delivery and live qualification remain open.

Fixed: null-only limited support, false complete-dashboard sufficiency, and nested
book access before normalization. Initial test fixture disagreement was corrected
by changing both the account and source CFO total, retaining the independent
component equation so the intended reconciliation BLOCK is tested. Initial local
set typing and test annotations/formatting were corrected. No unresolved confirmed
implementation defect remains in this scope; final rewrite verification follows.

## Scoped tournament

Selected only `validate_downstream_review` and `_assess_consumers`: review trust
and readiness status boundaries. Routine input/report assembly, evidence-tag
helper, request map and wrappers receive focused tests plus confidence review.
All roles explicitly use fresh GPT-6.1 Sol/high; coordinator unchanged. GitNexus
reported repository-not-found. `rg` impact: validator/assessor → canonical assembler
→ external validator; tests are the only current consumers. Strict mypy checks
all callers. CLI, execution and renderer integration remain later work.

The coordinator's final dashboard completeness guard was inserted identically
into incumbent, speed and memory snapshots before comparisons; the readability
role read the updated production source. This is a shared confirmed-bug fix,
not a claimed challenger optimization. The frozen scratch brief records the exact
functions, invariants, scope and command. Raw candidates/logs remain ignored.

## Winner and coordinator verification

Winner: **Snippet A**, replacing `validate_downstream_review` (lines 203–289)
and `_assess_consumers` (lines 292–345) in
`src/deploy_vii/downstream_readiness.py`. The blind bracket selected A over B,
then C, then incumbent D; all three matches had the same decisive properties:

- Set membership removes the potentially quadratic scan for actionable gaps;
  output still follows the original ledger order with stable deduplication.
- Reused evidence/requirement sets and lazy evidence-tag extraction avoid repeated
  work across shared dependencies, at linear temporary space cost.
- Local loops preserve visible validation boundaries, diagnostic order and status
  precedence without introducing nested helpers or changing caller contracts.

Coordinator purity check: `_evidence_tags` only parses authenticated immutable row
JSON and constructs a fresh set. It has no I/O or mutations. Each cache value is
read into a separate local tag set, never mutated by a requirement. Caching does
not alter observable behavior. No benchmark or measured speedup is claimed.

`uv run --locked python artifacts/downstream-tournament/compare.py` passed:
28 tests plus exact differential comparisons of 78 unique validator cases and
60 unique assessor cases per candidate across all four candidates. The harness
compares return values or exception class/message and checks input immutability.
It includes duplicate/unknown requests and gap scopes, last-wins internal maps,
empty assessments, consumer ordering and the shared dashboard guard. These
synthetic comparisons support behavioral equivalence, not analytical qualification.

Concrete invariant: a stale source binding remains a non-excludable consumer
BLOCK and blocks the separate workbook row even when historical Model inputs
otherwise report ready. Relevant financial reconciliation failures remain in the
ledger; a synthetic infra-only scope exclusion never waives Model checks.
The applied winner was backed up locally, inspected in the complete candidate
diff and formatted mechanically. Strict mypy passed all 39 source files.

## Final code for the two selected functions

```python
def validate_downstream_review(
    inputs: DownstreamInputs, review: DownstreamReview
) -> tuple[str, ...]:
    """Validate a review against supplied inputs; external assembly authenticates inputs."""
    try:
        inputs = DownstreamInputs.model_validate_json(inputs.model_dump_json())
        review = DownstreamReview.model_validate_json(review.model_dump_json())
        if inputs.consumers != _requests(inputs.requested_consumers):
            return ("Consumer requirements differ from the requested entries",)
    except ValueError as error:
        return (f"Invalid downstream contract: {error}",)
    prior_issues = validate_narrative_review(inputs.narrative.inputs, inputs.narrative.review)
    if prior_issues:
        return tuple("Invalid prior narrative: " + issue for issue in prior_issues)
    issues = []
    if review.inputs_sha256 != inputs.content_hash():
        issues.append("Downstream review does not bind current inputs")
    requests = {r.entry: r for r in inputs.consumers}
    evidence = {r.evidence_id: r for r in inputs.narrative.inputs.catalogue}
    gaps = {g.gap_id: g for g in inputs.narrative.gaps}
    evidence_tags: dict[str, set[str]] = {}
    if len(review.consumers) != len({c.entry for c in review.consumers}):
        issues.append("Duplicate consumer assessment")
    for consumer in review.consumers:
        request = requests.get(consumer.entry)
        if request is None:
            issues.append(f"Unrequested consumer assessment: {consumer.entry}")
            continue
        expected = set(request.requirements)
        assessed = set()
        for requirement in consumer.requirements:
            key = requirement.requirement
            if key in assessed or key not in expected:
                issues.append(f"Duplicate or unknown requirement: {consumer.entry} {key}")
            assessed.add(key)
            ids = requirement.evidence_ids
            unique_ids = set(ids)
            if len(ids) != len(unique_ids) or not unique_ids <= evidence.keys():
                issues.append(f"Invalid requirement evidence: {consumer.entry} {key}")
            if requirement.status != "missing" and not ids:
                issues.append(f"Sufficiency requires prior evidence: {consumer.entry} {key}")
            if requirement.status != "missing":
                tags: set[str] = set()
                for evidence_id in ids:
                    if evidence_id in evidence:
                        if evidence_id not in evidence_tags:
                            evidence_tags[evidence_id] = _evidence_tags(evidence[evidence_id])
                        tags.update(evidence_tags[evidence_id])
                groups = _EVIDENCE_GROUPS.get(key)
                if groups and any(tags.isdisjoint(group) for group in groups):
                    issues.append(
                        f"Incompatible or unavailable dependency evidence: {consumer.entry} {key}"
                    )
                if not groups and not (tags - {"gap"}):
                    issues.append(f"Sufficiency requires register evidence: {consumer.entry} {key}")
            if key == "kpi_dashboard" and requirement.status == "sufficient":
                dashboard = inputs.narrative.inputs.ledger.kpis
                if (
                    dashboard is None
                    or not dashboard.kpis
                    or any(kpi.value.amount is None for kpi in dashboard.kpis)
                ):
                    issues.append(
                        f"Complete KPI dashboard has unavailable values: {consumer.entry}"
                    )
            if requirement.status != "sufficient" and not requirement.actions:
                issues.append(f"Incomplete requirement needs action: {consumer.entry} {key}")
        scoped: set[str] = set()
        for scope in consumer.gaps:
            gap_ids = set(scope.gap_ids)
            if len(gap_ids) != len(scope.gap_ids) or not gap_ids <= gaps.keys() or gap_ids & scoped:
                issues.append(f"Duplicate or unknown gap scope: {consumer.entry}")
            scoped.update(gap_ids)
            refs = scope.evidence_ids
            unique_refs = set(refs)
            if len(refs) != len(unique_refs) or not unique_refs <= evidence.keys():
                issues.append(f"Invalid gap-scope evidence: {consumer.entry}")
            if scope.relevance == "not_relevant":
                if not refs:
                    issues.append(f"Excluding gaps requires prior evidence: {consumer.entry}")
                if any(
                    gaps[i].severity == "BLOCK" and gaps[i].origin in {"context_binding", "context"}
                    for i in gap_ids
                    if i in gaps
                ):
                    issues.append(f"A source-integrity block cannot be excluded: {consumer.entry}")
    return tuple(issues)


def _assess_consumers(
    inputs: DownstreamInputs, review: DownstreamReview
) -> tuple[ConsumerRow, ...]:
    """Derive statuses without dropping any inherited gap or unreviewed dependency."""
    assessments = {c.entry: c for c in review.consumers}
    gaps = inputs.narrative.gaps
    result = []
    for request in inputs.consumers:
        assessment = assessments.get(request.entry, ConsumerAssessment(entry=request.entry))
        requirements = {r.requirement: r for r in assessment.requirements}
        missing = tuple(r for r in request.requirements if r not in requirements)
        relevance = {i: s.relevance for s in assessment.gaps for i in s.gap_ids}
        blocking = tuple(
            g.gap_id
            for g in gaps
            if g.severity == "BLOCK"
            and (
                relevance.get(g.gap_id) != "not_relevant"
                or g.origin in {"context_binding", "context"}
            )
        )
        unassessed = tuple(g.gap_id for g in gaps if g.gap_id not in relevance)
        relevant = tuple(g.gap_id for g in gaps if relevance.get(g.gap_id) == "relevant")
        incomplete = any(r.status == "missing" for r in requirements.values())
        limited = any(r.status == "limited" for r in requirements.values())
        actions = [action for r in assessment.requirements for action in r.actions]
        actions.extend("Assess required CP-1 dependency: " + key for key in missing)
        if unassessed:
            actions.append("Assess all retained gaps for this consumer")
        actionable = set(relevant)
        actionable.update(blocking)
        actions.extend(g.recommended_action for g in gaps if g.gap_id in actionable)
        result.append(
            ConsumerRow(
                entry=request.entry,
                canonical_module=request.canonical_module,
                consumer_type=request.consumer_type,
                status="not_ready"
                if blocking or missing or unassessed or incomplete
                else "ready_with_limitations"
                if limited or relevant
                else "ready",
                requirements=tuple(
                    requirements[k] for k in request.requirements if k in requirements
                ),
                unassessed_requirements=missing,
                gap_assessments=assessment.gaps,
                blocking_gap_ids=blocking,
                relevant_gap_ids=relevant,
                unassessed_gap_ids=unassessed,
                actions=tuple(dict.fromkeys(actions)),
            )
        )
    return tuple(result)
```

## Verification results

- `uv run --locked pytest tests/product/test_downstream_readiness.py tests/product/test_narrative.py tests/product/test_model_readiness.py -q`: **79 passed** after applying and formatting A.
- `make product-check`: **724 passed**, **97.37%** branch-inclusive coverage; strict mypy (39 source files), Ruff lint/format and JavaScript syntax passed.
- `make check`: passed lock consistency, all-file hygiene, lint/format and staged/working diff checks.
- `make secrets`: passed local-directory, staged-diff and all reachable Git-history scans with Gitleaks 8.30.1.
- Complete production, test and documentation candidate diff inspected by the coordinator. No dependency changes; dependency audit is not needed for this increment.
- Design hook triage: the side-tab finding is the existing active-page navigation indicator, consistent with the preserved Direction C reference. The narrow `side-tab`/`*` exception for `src/deploy_vii/assets/app.css` already exists. No CSS or suppression change; no unresolved design finding in this scope.

No live model call, analytical qualification, new Module rendering acceptance or
native-host qualification was performed. OpenRouter spend remains US$0 / US$50.
