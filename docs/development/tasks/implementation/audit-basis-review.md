# Annual audit-basis increment review

Base: `31c4a00`; clean tree verified before changes. Coordinator owns the checkout.
Scope: source-supported annual audit explanations, both annual comparison APIs,
input validation/versioning and focused regressions. No UI, dependencies or live
model calls. The previous goal turn made progress by committing canonical KPIs.

## Confidence review

Least confident about, ranked:

1. An explanation could become a blanket override. Traced source `_year` and
   period `_years`: only FY_QUARTERS calls the common selector, matching the FY,
   metric and exact ordered four-quarter tuple. Cash and other metric failures
   retain BLOCK. Reconciliation math remains unchanged; the positive synthetic
   case keeps source -21, calculated -20 and difference +1 while becoming WARN.
2. Missing evidence could be promoted. Public builders revalidate strict contracts,
   every nested quote/hash/locator and book relationships before calculation.
   Missing/conflicting values yield null differences and cannot match eligibility.
   Malformed/unknown/duplicate period scopes and unlocated explanations are refused.
3. A previously valid explanation could survive changed inputs. Records pin the
   five source observation hashes, including amount, state, alternatives and
   citations. A changed FY amount is rejected as stale. The synthetic fixture's
   freezer replaces placeholder source hashes; its test-only binding now maps
   unchanged observations to their final hashes, preserving intentionally stale
   fingerprints. The production rule was not weakened to accommodate the fixture.
4. Audit labels or constructions could create false independence. Only explicit
   AUDITED FY and UNAUDITED Q1–Q4 labels qualify; unknown labels, component periods,
   wrong fiscal order and gaps fail validation. The period consumer additionally
   requires independent comparison and four direct own-period IDs. Existing
   shared-source construction warnings are not converted into audit exceptions.
5. Decimal precision or outcome assembly could change values. The selector uses
   `copy_abs`, avoiding ambient precision. Arithmetic still uses the existing
   Decimal context. Both reports preserve the original reported term, every
   component and tolerance. Matching values remain PASS without an applied record.
6. Hash/schema validation could accept tampered outputs. Applied explanations are
   retained on each check, and validator recomputation rejects their removal.
   Input and both affected output schemas advance to /2; an explicit old input
   schema is refused. All other consumers bind changed review hashes or nested
   reports rather than accepting stale outputs.
7. A numeric warning might be misrepresented as analytical acceptance. By design,
   exact quote checks cannot establish that the cited explanation is true or
   material. Live analytical testing, report binding, Module acceptance and other
   readiness conditions remain separate. The remaining DCF/FFO definitions and
   source-backed cash/FX treatment are unchanged pending work.

Fixed during implementation: synthetic source-freezing fixture fingerprint order;
no production exception was relaxed. Verified: scoped severity, unchanged arithmetic,
missing/conflict blocking, stale/evidence rejection and recomputation. Open:
analytical interpretation and the broader documented delivery/qualification work.

## Scoped tournament

Only `audit_explanation_issues` and `annual_warning` receive a tournament: these
are the provenance and financial exception boundary. Schema declarations and
source/period report assembly receive confidence review and focused tests.
Fresh incumbent, speed, memory, readability and blind-arbiter roles use GPT-6.1
Sol/high under the user's model matrix; the coordinator model is unchanged.

GitNexus returned repository-not-found. `rg` traced validation through `book_issues`
to all public financial builders, and eligibility through the two annual comparison
builders to historical Model readiness. Strict mypy and the financial regression
suite are the caller-contract oracle. No product CLI or renderer directly consumes
this internal output yet.

Winner: **Snippet A**, replacing `audit_explanation_issues` lines 16–78, `annual_warning` lines 81–103 in
`src/deploy_vii/audit_basis.py`. Bracket: A over B, A over C, A over D (incumbent).

- Local scope names reduce repeated attribute access while retaining meaning.
- Resolving known quarters once removes an intermediate nullable list and scan;
  ordered diagnostic checks are preserved.
- The explicit first-match loop returns the original explanation without the
  nested generator. No measured performance improvement is claimed.

The coordinator backed up the module, applied A, and inspected the replacement
diff. All three candidates matched the incumbent over **2,808 comparisons** in
18 boundary tests, including exact diagnostic order, exception behavior, returned
object identity and input immutability. The scratch harness and results remain
under ignored `artifacts/audit-basis-tournament/`.

After application, `uv run --locked pytest tests/product/test_audit_basis.py
tests/product/test_reconciliation.py tests/product/test_period_reconciliation.py
tests/product/test_model_readiness.py -q` passed **81 tests**. `uv run --locked
mypy src` passed **32 source files**; Ruff passed. The concrete invariant is
source FY -21 versus quarterly sum -20: the eligible record produces WARN with
difference +1 retained, while changing another metric or cash movement still
produces BLOCK. Public validation still rejects the explanation after its bound
observation changes. No additional defect was confirmed during winner review.

Final code:

```python
def audit_explanation_issues(book: FinancialBook) -> tuple[str, ...]:
    periods = {p.period_id: p for p in book.periods}
    ids: set[str] = set()
    targets: set[tuple[str, str]] = set()
    issues: list[str] = []
    observations = {(r.period_id, r.metric_id): r.value for r in effective_accounts(book)}
    for item in book.audit_basis_explanations:
        explanation_id = item.explanation_id
        annual_id = item.annual_period_id
        metric_id = item.metric_id
        quarter_ids = item.quarter_period_ids
        target = annual_id, metric_id
        if explanation_id in ids or target in targets:
            issues.append(f"Duplicate annual audit explanation: {explanation_id}")
        ids.add(explanation_id)
        targets.add(target)
        annual = periods.get(annual_id)
        known = [q for pid in quarter_ids if (q := periods.get(pid)) is not None]
        if annual is None or len(known) != len(quarter_ids):
            issues.append(f"Unknown audit explanation period: {explanation_id}")
            continue
        if metric_id not in FLOW_METRICS:
            issues.append(f"Annual audit explanation requires a flow metric: {explanation_id}")
        for pid, expected in zip(
            (annual_id, *quarter_ids),
            (item.annual_observation_sha256, *item.quarter_observation_sha256),
            strict=True,
        ):
            observation = observations.get((pid, metric_id))
            if observation is None or observation.content_hash() != expected:
                issues.append(f"Stale audit explanation observation: {explanation_id} {pid}")
        if annual.period_type != "FY" or annual.audit_status.strip().upper() != "AUDITED":
            issues.append(f"Annual audit explanation requires audited FY: {explanation_id}")
        if (
            len(set(quarter_ids)) != 4
            or [q.fiscal_quarter for q in known] != [1, 2, 3, 4]
            or any(
                q.period_type != "QUARTER"
                or q.audit_status.strip().upper() != "UNAUDITED"
                or q.component_period_ids
                or fiscal_year_number(q.fiscal_year) != fiscal_year_number(annual.fiscal_year)
                for q in known
            )
        ):
            issues.append(
                f"Audit explanation requires ordered independent unaudited quarters: "
                f"{explanation_id}"
            )
        if (
            annual.start_date is None
            or annual.end_date is None
            or known[0].start_date != annual.start_date
            or known[-1].end_date != annual.end_date
            or any(q.start_date is None or q.end_date is None for q in known)
            or any(
                a.end_date is None
                or b.start_date is None
                or a.end_date.toordinal() + 1 != b.start_date.toordinal()
                for a, b in pairwise(known)
            )
        ):
            issues.append(f"Audit explanation quarters do not span FY: {explanation_id}")
    return tuple(issues)


def annual_warning(
    book: FinancialBook,
    annual_period_id: str,
    metric_id: str,
    quarter_period_ids: tuple[str | None, ...],
    difference: Decimal | None,
    tolerance: Decimal | None,
) -> AuditBasisExplanation | None:
    """Select only a validated, exact-scope explanation for a numeric discrepancy.

    Callers pass null difference for structural failures and non-independent
    constructions. Book and citation validation precedes both public consumers.
    """
    if difference is None or tolerance is None or difference.copy_abs() <= tolerance:
        return None
    for item in book.audit_basis_explanations:
        if (
            item.annual_period_id == annual_period_id
            and item.metric_id == metric_id
            and item.quarter_period_ids == quarter_period_ids
        ):
            return item
    return None
```

## Final verification

`make product-check` passed lint/format, strict typing of 32 source files,
JavaScript syntax and **536 product tests**, including all four browser regressions.
Combined line/branch coverage is **97.42%** against a 90% floor; the new audit-basis
module has complete coverage. Log: ignored `artifacts/audit-basis-product-check.log`.
The full candidate diff was inspected, including the unchanged arithmetic paths.
No dependencies or UI were changed. No new completed-Module rendering, analytical
or native-host acceptance is claimed; OpenRouter spend remains **US$0 / US$50**.
DCF/FFO coverage definitions remain unanswered. The overall goal remains active.

`make check` passed all-file hygiene and diff checks. `make secrets` passed the
working-directory, staged-diff and reachable-history scans with no leaks.
