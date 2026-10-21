# Canonical source audit increment review

Task `dvii-implementation-001`, base `736f5fd`, branch
`codex/development-environment`. Coordinator owns this checkout. Previous turn:
progress (committed independent NCF gate). This increment advances milestone C's
normalization, definition-conflict and source gap registers. It is not a completed
Module. OpenRouter spend remains US$0 of the US$50 first-core qualification cap.

Scope: new `src/deploy_vii/canonical_audit.py`, focused synthetic regressions and
related documentation. No dependencies, frontend assets or live calls changed.
[Behavior and requirements](../../canonical-audit.md).

## Confidence review

Ranked least-confident points and investigation:

1. **A model assessment might change a financial result or mask a conflict.**
   Traced all paths: the input carries definitions, observation IDs and commentary,
   not replacement numeric values. Source reconciliation is regenerated from the
   original financial review before assessment rows are assembled. Conflicting
   observations cannot be aligned; automatic debt-basis rows remain independent
   of scoped assessment status. Tests retain 100 carrying/105 principal and
   unsettled alternatives 10/11 with null settled amount. No gate consumes an
   alignment status. Verdict: verified fine; semantic accuracy of analyst text
   still requires analytical review.
2. **Source or scope substitution at a trust boundary.** Financial contracts are
   revalidated first; definition input is reserialized; exact financial hash and
   selected-book references are checked. Every nested citation uses the existing
   frozen-pack validator. Adversarial tests reject stale hashes, unknown books,
   cross-book observations with otherwise valid citations, duplicate/overlapping
   assessments, unknown/duplicate event figures, forged quotes and bad versions.
   Invalid nested financial contracts return issues before traversal. Output
   validation recomputes against an external definition input, preventing a
   self-consistent substituted assessment from becoming its own authority.
   Verdict: verified fine.
3. **A sign change could lose its justification or alter raw values.** The
   statement adapter remains authoritative for statement normalizations; compact
   accounts reuse canonical sign classification and exact Decimal copy operations.
   Inspection found compact rows initially carried only amount citations, omitting
   explicit source sign evidence. Added matching statement sign citations; a
   source-positive CFO60 case verifies compact -60 and its sign evidence. Positive
   COGS30 and capex8 retain originals and normalize to -30/-8. Negative/zero values
   are not falsely logged as changed. Verdict: fixed evidence omission; no
   arithmetic change. Ambient precision1 produces the same report.
4. **Gap extraction might omit evidence or affected periods.** The initial gap
   contract lacked citations and definition-coverage gaps lacked periods. Added
   nested observation/check evidence, disclosure/period/term citations and scoped
   definition-coverage periods. Added explicit maturity and NOT_STATED facility
   classification/rate warnings. Tests compare non-PASS source checks with the
   ledger, retain source/disclosure limitations, and verify period/evidence links.
   Verdict: fixed traceability omissions. Derived-period/KPI and analytical gaps
   remain explicitly outside this source-stage report and must be combined later.
5. **Distinct meanings or units could be collapsed.** Source positions retain the
   original typed observation for each schedule field. Facility rates use bps or
   decimal fractions without currency; carrying/principal remain book-scale values
   in facility currency; operating KPIs preserve their declared units. Event rows
   preserve ordered figure references/roles without summation, and missing debt
   values cannot create an inferred difference. Tests compare every original
   observation, check dimensions, null debt and event roles. Verdict: verified fine.
6. **An empty review might be treated as clean, or generated IDs might collide.**
   Unassessed observation IDs and gap rows are explicit. Assessment scope removes
   only its own observation from that list. Event registration does not imply
   definition alignment. Generated IDs use the existing length-prefixed hash helper;
   kinds/origins distinguish categories. Tests verify distinct IDs, scoped coverage,
   exact report recomputation, tampering detection and unchanged source input.
   Verdict: verified fine. Analytical completeness is never inferred from coverage.

Fixed: sign-evidence omission, gap citation/period omissions and explicit facility
term warning coverage found during review. Initial typing/import/format issues and
Pydantic's reserved `register` name warning were corrected before final checks.

By design: assessment materiality and recommendations are source-linked analyst
judgements, not adopted formula definitions; distinct debt bases are not necessarily
errors. Not-applicable observations retain reasons in the ledger. No arbitrary
financial threshold, automatic waiver or blanket alignment is introduced.

Still open: source-tier/entity metadata, KPI/constructed-period gap union,
quantitative materiality beyond retained source values, analytical completeness,
evidence-risk-credit narrative, consumer readiness, delivery binding and rendering.
Pending DCF and FFO coverage definitions remain unanswered; no choice is adopted.


## Scoped post-edit tournament

Only `validate_definition_review` and `_definitions` were selected: the trust
boundary and source-provenance assembly. Routine register formatting, sign-row
projection and gap collection receive focused tests and confidence review.
All five roles used fresh GPT-6.1 Sol/high contexts under the requested matrix;
coordinator settings unchanged. No provider fallback or recursive delegation.

GitNexus context reported Deploy VII is not indexed. The fallback impact search
in `artifacts/canonical-audit-tournament/impact.txt` shows the two targets feeding
`canonical_audit`, then `validate_canonical_audit` and the focused tests. Strict
mypy checks every source module. No execution or renderer caller is claimed.

**Winner: Snippet A (memory candidate)**, winning all three blind bracket rounds.

- Reuses per-assessment uniqueness sets and asks overlap with `isdisjoint`.
- Streams first-occurrence citations into one ordered dictionary, avoiding a
  temporary tuple containing repeated evidence.
- Retains explicit row groups, diagnostics and provenance order without adding
  cache state or a new abstraction.

The coordinator backed up the current file, applied only the two functions,
inspected the real diff and ran:

```text
uv run pytest tests/product/test_canonical_audit.py tests/product/test_financials.py tests/product/test_statements.py tests/product/test_reconciliation.py -q
132 passed
uv run mypy src
Success: no issues found in 34 source files
PYTHONPATH=. uv run python artifacts/canonical-audit-tournament/verify.py src/deploy_vii/canonical_audit.py
960 validation cases and 2252 serialized definition rows match across 160 varied source reviews; inputs unchanged
```

Concrete invariant: source carrying value100 and principal105 remain distinct
located values in one debt-basis row even with a separate aligned assessment.
Known conflict alternatives10/11 retain a null settled value. The differential
checks include errors, unknown/duplicate IDs and overlapping assessments; the
initial review in every generated case must independently validate successfully.
No measured end-to-end performance improvement is claimed.

## Final tournament code

`src/deploy_vii/canonical_audit.py:166–210`

`src/deploy_vii/canonical_audit.py:213–316`

```python
def validate_definition_review(
    pack: PreparedPack,
    review: FinancialReview,
    definition: DefinitionReview,
) -> tuple[str, ...]:
    issues = list(validate_financial_review(pack, review))
    if issues:
        return tuple(issues)
    try:
        definition = DefinitionReview.model_validate_json(definition.model_dump_json())
    except ValidationError as error:
        return (*issues, f"Invalid definition contract: {error}")
    if definition.financial_review_sha256 != review.content_hash():
        issues.append("Definition review does not bind current financial review")
    book = next((b for b in review.books if b.book_id == definition.book_id), None)
    if book is None:
        return (*issues, "Unknown definition review book")
    observations = {v.observation_id: v for v in records(book, Observation)}
    issues.extend(citation_issues(tuple(records(definition, Citation)), pack.sources))
    for rows, identity in (
        (definition.assessments, "assessment_id"),
        (definition.events, "event_id"),
    ):
        if len(rows) != len({getattr(row, identity) for row in rows}):
            issues.append(f"Duplicate definition record: {identity}")
    assessed: set[str] = set()
    for assessment in definition.assessments:
        ids = assessment.observation_ids
        unique_ids = set(ids)
        if len(ids) != len(unique_ids) or not unique_ids <= observations.keys():
            issues.append(
                f"Duplicate or unknown assessment observation: {assessment.assessment_id}"
            )
        if not assessed.isdisjoint(unique_ids):
            issues.append("An observation cannot have multiple definition assessments")
        assessed.update(unique_ids)
        if assessment.status == "aligned" and any(
            observations[oid].status == "conflicting" for oid in ids if oid in observations
        ):
            issues.append("Conflicting observations cannot be declared aligned")
    for event in definition.events:
        unique_ids = {figure.observation_id for figure in event.figures}
        if len(event.figures) != len(unique_ids) or not unique_ids <= observations.keys():
            issues.append(f"Duplicate or unknown event observation: {event.event_id}")
    return tuple(issues)

def _definitions(
    book: FinancialBook,
    positions: tuple[SourcePosition, ...],
    review: DefinitionReview,
) -> tuple[DefinitionRow, ...]:
    index = {p.observation.observation_id: p for p in positions}
    rows: list[DefinitionRow] = []

    def append(
        key: str,
        kind: Literal["assessment", "value_conflict", "debt_basis", "multi_figure_event"],
        status: Literal["aligned", "conflict", "distinct_bases"],
        metric: str,
        ids: tuple[str, ...],
        explanation: str,
        *,
        roles: tuple[str, ...] = (),
        canonical: str | None = None,
        issuer: str | None = None,
        materiality: str = "Not assessed; retained values must be reviewed",
        impact: str = "Consumers must retain the distinct source meanings",
        action: str = "Review source definitions; do not settle or substitute values silently",
        citations: tuple[Citation, ...] = (),
    ) -> None:
        evidence: dict[Citation, None] = dict.fromkeys(citations)
        for oid in ids:
            for citation in records(index[oid].observation, Citation):
                evidence[citation] = None
        rows.append(
            DefinitionRow(
                row_id=_id("definition", kind, key),
                kind=kind,
                status=status,
                metric=metric,
                canonical_definition=canonical,
                issuer_definition=issuer,
                observation_ids=ids,
                period_ids=tuple(dict.fromkeys(index[oid].period_id for oid in ids)),
                roles=roles,
                explanation=explanation,
                materiality=materiality,
                downstream_impact=impact,
                recommendation=action,
                citations=tuple(evidence),
            )
        )

    for row in review.assessments:
        append(
            row.assessment_id,
            "assessment",
            row.status,
            row.metric,
            row.observation_ids,
            "Evidence-linked analyst definition assessment; does not change Python formulas",
            canonical=row.canonical_definition,
            issuer=row.issuer_definition,
            materiality=row.materiality,
            impact=row.downstream_impact,
            action=row.recommendation,
            citations=row.citations,
        )
    for position in positions:
        value = position.observation
        if value.status == "conflicting":
            append(
                value.observation_id,
                "value_conflict",
                "conflict",
                position.row_id,
                (value.observation_id,),
                value.reason or "Unresolved source alternatives",
            )
    for facility in book.facilities:
        carrying, principal = facility.carrying_value, facility.principal
        if (
            carrying.amount is not None
            and principal.amount is not None
            and carrying.amount != principal.amount
        ):
            append(
                _id("facility", facility.facility_id, facility.period_id),
                "debt_basis",
                "distinct_bases",
                facility.facility_name,
                (carrying.observation_id, principal.observation_id),
                "Carrying value differs from gross principal; both source figures are retained",
                roles=("carrying_value", "gross_principal"),
                canonical="Canonical debt uses carrying value excluding both lease types",
                citations=facility.terms_citations,
            )
    for event in review.events:
        append(
            event.event_id,
            "multi_figure_event",
            "distinct_bases",
            event.description,
            tuple(f.observation_id for f in event.figures),
            event.explanation,
            roles=tuple(f.statement_role for f in event.figures),
            impact=event.downstream_impact,
            citations=event.citations,
        )
    return tuple(rows)
```


## Final increment checks

`make product-check` passed lint, formatting, strict mypy (34 source files),
JavaScript syntax and 599 product tests, including four existing browser
regressions. Combined coverage: 97.41%. Log:
`artifacts/canonical-audit-product-check.log`. `make check` passed repository
hygiene (`artifacts/canonical-audit-hygiene.log`). The coordinator inspected the
complete candidate diff, including all new contracts, code, tests and docs.
No frontend field changed and no completed-Module rendering acceptance is claimed.

`make secrets` passed working-directory, staged-diff and full-history scans with
no leaks (`artifacts/canonical-audit-secrets.log`). Source packs and raw test
evidence remain outside Git. No outstanding process or review is left running.
