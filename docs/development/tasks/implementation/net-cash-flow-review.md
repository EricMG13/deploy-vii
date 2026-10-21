# Independent NCF increment review

Task `dvii-implementation-001`; base `32a9c01`, branch
`codex/development-environment`. Coordinator owns this checkout/publication.
Implements r14 CP-1 Step 7's operating/investing/financing-to-NCF check and makes
it mandatory for selected historical Model quarters. This advances milestone C;
no Module, analytical, rendering or native-host acceptance is promoted.
OpenRouter spend remains US$0 of the US$50 first-core qualification cap.

[Behavior and pinned requirement](../../net-cash-flow.md). No Deploy VI code or
policies were copied. The existing financial-review/3 statement contract supplies
source equations; source/period reports advance to /4 and readiness to /2.

## Confidence review

Least confident about, ranked by likelihood and impact:

1. **Incorrect signs from printed outflow magnitudes.** Traced `_statement_check`
   and `_identity_terms`: source equations use original amounts and explicit
   coefficients. `_ncf` changes only the completed target sign when the located
   NCF presentation requires negative-absolute normalization. Tests cover positive
   CFI/CFF magnitudes with negative equation coefficients and a positive printed
   cash decrease converted to canonical negative NCF in both APIs. Coordinator
   checks independently calculated 300 signed source equations, including all
   combinations of positive/negative category amounts and magnitude presentation.
   Verdict: verified fine; no double normalization.
2. **Source errors canceling beneath a parent or across periods.** Every reachable
   intermediate identity is checked against its reported target before NCF can
   calculate. A regression changes CFI from -10 to -9 and CFF from -30 to -31:
   both the direct total and expanded parent still equal 20, yet the NCF check
   blocks on the two wrong subtotals. Equal +1 source errors in Q1/H1 also cancel
   arithmetically but cannot produce a constructed PASS. Missing/partial disclosure
   and conflicting values remain BLOCK. Verdict: verified fine.
3. **Permissive equations or incomplete statements masquerading as completeness.**
   Traced the public validation boundary and NCF root classification. A root must
   reference operating, investing and financing totals, with only optional explicit
   FX. A generic -40 detail beside CFO60 can reconcile to NCF20 in the generic
   source checker, but is blocked by NCF completeness. A visible FX line is not
   included unless the source equation references it. Empty financing must be a
   cited zero, which remains an operand. Missing root equations block readiness
   despite matching cash balances. Verdict: verified fine; exact source mapping
   and the completeness assessment still require analytical interpretation.
4. **Missing source targets filled by unrelated canonical values.** A missing
   source NCF target with known canonical NCF20 retains the canonical observation
   but blocks calculated NCF. No source identity is invented. Unknown components
   survive expansion and period combination. The explicit compact input still
   takes precedence over fallback statement observations. Verdict: verified fine.
5. **Caching changes diagnostics, provenance or stale behavior.** The selected
   rewrite caches only pure source results within one `_period_ncf` invocation.
   Each occurrence still appends its own signed terms, citations and blockers.
   Coordinator differential verification matched 72 full serialized period
   records and six repeated/unknown-source plans, including errors and opposite
   signs. Source and report inputs remained unchanged. No cache survives a call.
   Verdict: verified fine; bounded additional memory is deliberate.
6. **Readiness or version drift outside the new check.** Traced the new kind into
   both source and period producers and `_MANDATORY_CHECKS`. Four-quarter readiness
   tests assert all four NCF checks are mandatory. Source error checks and existing
   CFO/cash/annual conditions remain. Synthetic ready fixtures now explicitly
   include CFI/CFF/NCF equations; cash-variation fixtures update both source and
   compact representations so they exercise cash behavior without creating an
   accidental validation conflict. Output versions advance and validators recompute
   content. Verdict: verified fine within the selected-historical scope.

Fixed: the missing independent NCF completeness gate and the ability of source
subtotal or period errors to hide within an agreeing NCF comparison. No additional
confirmed defect was found during confidence review. Initial test-import sorting
was corrected before verification.

Verified fine: source/canonical signs, subtotal and period failure propagation,
explicit FX/zero handling, missing targets, provenance and within-call cache
behavior through the tests and traced paths above.

By design: incomplete reviews remain retainable but cannot establish readiness;
source subtotals without their own equation remain located source operands.
CFO still has its separate mandatory independent equation. Cash balance/perimeter
reconciliation remains a separate check, with no balancing plug.

Still open: live source interpretation, other cross-statement comparisons,
remaining canonical narrative/gap/definition/conflict registers, full consumer
readiness and foreign-currency debt treatment, CP-1A, execution/Calculation/Module
binding and Workbench field acceptance. Pending DCF and FFO coverage definitions
remain unanswered; no option is adopted.

## Scoped post-edit tournament

Only `_ncf` and `_period_ncf` received rewrite tournaments. Routine wiring and
fixtures received focused checks and confidence review. All five roles used fresh
GPT-6.1 Sol/high contexts under the model matrix; coordinator settings unchanged.

GitNexus context failed because Deploy VII is not indexed. The fallback impact
search in `artifacts/ncf-impact.txt` identifies `_cash`/source reconciliation and
`_bridges`/period reconciliation, then public validators and Model readiness.
Strict mypy and focused tests verify this caller set. The cache introduces only a
`Reconciliation` type import; signatures and return contracts are unchanged.

**Winner: Snippet A**, speed candidate, replacing the two functions reproduced
below. Blind bracket: A beat B, C, then D. Original files were backed up before
application in `artifacts/ncf-tournament/`.

- Uses explicit named cash-flow categories, avoiding a less readable bit mask.
- Reuses immutable source terms when the canonical sign does not change.
- Reconciles repeated source periods once per call while preserving every signed
  occurrence, diagnostic and citation; no persistent cache is introduced.

Coordinator verification, performed after applying the winner:

```text
uv run pytest tests/product/test_ncf.py tests/product/test_cash_bridge.py tests/product/test_model_readiness.py tests/product/test_audit_basis.py tests/product/test_reconciliation.py tests/product/test_period_reconciliation.py tests/product/test_statements.py -q
165 passed
uv run mypy src
Success: no issues found in 33 source files
PYTHONPATH=. uv run python artifacts/ncf-tournament/verify.py
300 independent signed source equations, 72 period records and 6 repeated/unknown-source plans match; inputs unchanged
```

Concrete arithmetic: CFO60 + CFI(-10) + CFF(-30) = NCF20. Printed outflow
magnitudes CFI10/CFF30 with source coefficients -1 produce the same result.
A printed cash decrease 20 is compared as canonical -20 without altering leaves.
No end-to-end performance claim is made; caching helps only repeated source terms.

## Final tournament code

`src/deploy_vii/financial_reconciliation.py:410–481`

`src/deploy_vii/period_reconciliation.py:230–260`

```python
def _ncf(book: FinancialBook, period: FinancialPeriod) -> Reconciliation:
    """Prove reported NCF from the three source cash-flow categories.

    Source identities operate on printed amounts. Only the completed equation is
    converted to the canonical target sign; leaf amounts and source signs remain
    visible. Nested source errors cannot disappear in an agreeing parent sum.
    """
    source = _statement_check(book, period, "CFS", "net_cash_change", "NCF_IDENTITY")
    lines = {r.line_id: r for r in book.statement_lines if r.period_id == period.period_id}
    equations = {
        r.target_line_id: r for r in book.statement_identities if r.period_id == period.period_id
    }
    target = next(
        (r for r in lines.values() if r.statement == "CFS" and r.item_id == "net_cash_change"),
        None,
    )
    root = equations.get(target.line_id) if target else None
    required = {"cfo_ncfo", "investing_cash_flow", "financing_cash_flow"}
    components = tuple(lines[c.line_id] for c in root.components) if root else ()
    items = {r.item_id for r in components}
    blockers: list[str] = []
    if (
        not required <= items
        or not items <= required | {"fx_cash_effect"}
        or any(r.line_kind == "detail" for r in components if r.item_id in required)
    ):
        blockers.append(
            "NCF equation requires operating, investing and financing totals; "
            "only explicitly included source FX may accompany them"
        )
    if source.calculated_value is None or source.reported_value is None:
        blockers.append(source.explanation)
    contexts = list(source.context_citations)
    pending = [c.line_id for c in root.components] if root else []
    checked: set[str] = set()
    while pending:
        line_id = pending.pop()
        if line_id in checked:
            continue
        equation = equations.get(line_id)
        if equation is None:
            continue
        checked.add(line_id)
        row = lines[line_id]
        child = _statement_check(book, period, "CFS", row.item_id, "SOURCE_STATEMENT_IDENTITY")
        contexts.extend(child.context_citations)
        if child.status != "PASS":
            blockers.append(f"{line_id}: {child.explanation}")
        pending.extend(c.line_id for c in equation.components)
    flip = (
        account_outflow(book, period.period_id, "net_cash_change")
        and source.reported_value is not None
        and source.reported_value >= 0
    )
    terms = (
        tuple(
            term.model_copy(update={"coefficient": -term.coefficient}) for term in source.components
        )
        if flip
        else source.components
    )
    return _check(
        period,
        "NCF_IDENTITY",
        "net_cash_change",
        _account(book, period.period_id, "net_cash_change"),
        terms,
        "independent operating + investing + financing source equation leaves; "
        "FX only if explicitly in the equation; canonical target sign conversion",
        blocker="; ".join(blockers) or None,
        context=(*contexts, *(target.sign_citations if target else ())),
    )

def _period_ncf(
    book: FinancialBook, report: HistoricalReport, node: PeriodConstruction, reported: PeriodTerm
) -> PeriodCheck:
    periods = {p.period_id: p for p in book.periods}
    terms: list[PeriodTerm] = []
    contexts: list[Citation] = []
    blockers: list[str] = []
    sources: dict[str, Reconciliation] = {}
    for pid, sign in _source_periods(report, node):
        if pid is None:
            terms.append(_cell(None, "Missing period component", 1 if sign == 1 else -1))
            blockers.append("Missing period component")
            continue
        source = sources.get(pid)
        if source is None:
            source = _ncf(book, periods[pid])
            sources[pid] = source
        terms.extend(_source(term, sign) for term in source.components)
        contexts.extend(source.context_citations)
        if source.status != "PASS":
            blockers.append(f"{pid}: {source.explanation}")
    return _compare(
        node,
        "NCF_IDENTITY",
        "net_cash_change",
        reported,
        tuple(terms),
        "signed period combination of independently reconciled source NCF equation leaves",
        blocker=node.limitation or "; ".join(blockers) or None,
        context=tuple(contexts),
    )
```

## Final increment checks

`make product-check` passed lint, formatting, strict typing (33 source files),
JavaScript syntax and 579 product tests, including four existing browser
regressions. Combined coverage: 97.44%. Log: `artifacts/ncf-product-check.log`.
No frontend field changed and no completed-Module rendering claim is made.

`make check` passed repository hygiene. `make secrets` passed working-directory,
staged-diff and full Git-history scans with no leaks; logs are retained locally
as `artifacts/ncf-hygiene.log` and `artifacts/ncf-secrets.log`. The coordinator
inspected the complete candidate diff, including fixtures and documentation.

Design hook triage: the side-tab finding in `src/deploy_vii/assets/app.css:2`
is the intentional active-page navigation indicator retained from Direction C.
The existing rule/value/file exception in `.impeccable/config.json` covers it.
No CSS fix or additional suppression was needed; the intentional indicator remains.
