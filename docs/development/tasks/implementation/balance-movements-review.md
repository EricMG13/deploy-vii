# CP-1 cross-statement balance movement review

Task `dvii-implementation-001`; base `6066650`, branch
`codex/development-environment`. Coordinator owns this checkout. Previous goal
turn: progress, downstream readiness committed and verified. Scope: r14 Step 7
income-to-equity and explicit other opening/closing balance bridges, source audit
and selected historical Model readiness. Reference: pinned Deploy VI
`bd71346301b373afa72655916a4c1b42bf4c9823`, local ignored CP-1 step reference.
No VI policies or implementation were copied; arithmetic reuses VII's reviewed
reconciliation helpers. No dependencies or frontend changes. OpenRouter US$0/$50.

## Confidence review

1. **Source omissions or balancing residuals might manufacture agreement.**
   Equity always has a check. Exact dated source BS balances and same-period IS
   net income are required. A complete sourced bridge is mandatory even for no
   additional movement; partial/absent coverage blocks calculation. Null movements
   stay null. Tests remove each operand/assessment and preserve original amounts
   and differences. Other balances never implicitly include income. Verified fine.
2. **Date aliases or source errors might be selected away.** Same-date conflict
   observations take precedence over known values, and all source citations are
   retained. Source BS disagreement is already rejected by statement validation.
   Every selected source BALANCE_MOVEMENT check, including null results, enters
   mandatory readiness. Derived quarters require their source annual/YTD bridge.
   Verified by direct and derived-quarter regressions. Unused annual source periods
   remain in the gap ledger rather than being labelled selected operands.
3. **New observations might miss provenance or sign review.** Flat movement rows
   enter `_positions`, used by audit and context binding. Explicit magnitude
   normalization retains before/after values and citations. Global observation-ID
   uniqueness and source citation validation apply recursively. Tests verify missing
   evidence rejection, audit positions, sign normalization and inherited gaps.
4. **Stable movement IDs could change meaning across periods.** Reproduced a
   distribution ID reused as OCI in Q3; public validation returned no issues.
   Fixed at the bridge boundary: changing label or role requires a new ID. Exact
   regression now rejects the input. Original evidence remains unchanged.
5. **Cross-bridge expansion might exceed input row limits.** Reproduced 10,001
   unique movement rows used by two valid bridges: each individual list was within
   bounds but expanded arithmetic had 20,002 terms. The book contract now rejects
   total expansion above 20,000 before arithmetic. This guard is outside the two
   tournament targets and is verified by its boundary regression.
6. **Compatibility/version changes could hide behavior changes.** Input, source
   reconciliation and Model-readiness versions advance explicitly. The existing
   synthetic ready fixture now supplies independently sourced equity and IS income
   plus explicit empty bridges; derived fixtures scale flows, never BS stocks.
   Initial test failures were fixture expectations: source freezing replaces hashes,
   unused FY is not a selected operand, and gap references are audit IDs with the
   reconciliation ID in `metric`. A direct-quarter-only fixture did not trigger the
   kernel's YTD derivation path; changed to explicit YTD operands. No production
   rule was weakened to satisfy these expectations. The first full suite then
   caught a copied prior-year KPI fixture whose new closing equity disagreed with
   the current opening balance at the same date. Shifted the whole prior equity
   series by the known synthetic annual income and retained its bridge IDs/scopes,
   preserving movements and the intended growth assertion; source conflict
   validation correctly rejected the inconsistent fixture.

Fixed: unstable movement definitions and unbounded cross-bridge expansion.
Verified fine: source/null/sign/date integrity, selected-source readiness, audit
and gap propagation, exact Decimal arithmetic and external recomputation.
By design: additional BS bridges are source-declared; Python does not infer their
semantic completeness or materiality. Full CP-1 acceptance is still unproven.
Open: FX debt normalization, module delivery/CP-1A and all live qualification.

## Scoped tournament

Only `balance_movement_issues` and `_balance_movements` receive the post-edit
tournament. Routine schemas/wiring/audit projection and the source-balance helper
receive confidence review and focused tests. Fresh GPT-6.1 Sol/high roles follow
the model matrix; coordinator unchanged. GitNexus reports repository-not-found;
`rg` impact and strict typing are the caller-contract evidence. Validation feeds
all public financial boundaries; arithmetic feeds audit/gaps/narrative/downstream
and historical Model readiness. No CLI or renderer consumer yet.

## Winner and verification

Winner: **Snippet C**. Bracket: A over B (separate existence/assignment sets
avoid boolean flag interpretation), C over A (domain names and direct helper
calls), C over D (clearer names for dates, evidence and results).

- `movement_rows`, `bridge_ids`, `bridge_scopes` and `assigned_movements` make
  each collection's purpose explicit without changing diagnostic control flow.
- `opening_date`, `selected_movements` and `sign_citations` identify the financial
  and evidence data at their use sites.
- Direct helper calls preserve the existing calculation boundary and avoid
  aliases or additional state. No runtime performance gain is claimed.

Coordinator backed up and applied C, inspected the full applied diff, and
verified exact signatures, helper order, source evidence and null/block behavior.
The concrete regression 140 opening equity + 40 source income - 10 distributions
+ 5 OCI = 175 closing equity passes. An unexplained following-period movement
remains a BLOCK and propagates to the gap ledger. Missing source annual bridge
blocks a quarter derived from that annual operand.

`uv run --locked python artifacts/balance-tournament/compare.py`: 27 tests passed;
139 unique validator cases and 174 unique arithmetic cases per candidate, comparing
all four candidates exactly. Malformed references, duplicates, unknown periods,
last-value/first-position ordering, returned diagnostics, exception classes/messages
and input immutability were checked. Raw logs/candidates remain ignored.

`uv run --locked pytest tests/product/test_balance_movement.py tests/product/test_model_readiness.py tests/product/test_reconciliation.py tests/product/test_canonical_gaps.py -q`:
**82 passed** after applying C. Strict mypy passed all 40 source files; Ruff
lint/format passed. Earlier downstream/narrative/NCF regressions: 94 passed.
These are synthetic implementation checks, not live analytical qualification.

## Final code for the two selected functions

`src/deploy_vii/balance_movement.py:7–60`.

`src/deploy_vii/financial_reconciliation.py:553–629`.

```python
def balance_movement_issues(book: FinancialBook) -> tuple[str, ...]:
    periods = {period.period_id: period for period in book.periods}
    movement_rows = {}
    issues = []
    definitions: dict[str, tuple[str, str]] = {}
    for row in book.balance_movements:
        key = row.period_id, row.movement_id
        if key in movement_rows:
            issues.append(f"Duplicate balance movement: {key}")
        definition = row.label, row.role
        if row.movement_id in definitions and definitions[row.movement_id] != definition:
            issues.append(
                f"Changed balance movement definition requires a new ID: {row.movement_id}"
            )
        definitions[row.movement_id] = definition
        movement_rows[key] = row
        period = periods.get(row.period_id)
        if period is None or period.period_type == "PERIOD_END":
            issues.append(f"Balance movement requires a flow period: {key}")

    bridge_ids: set[str] = set()
    bridge_scopes: set[tuple[str, str]] = set()
    assigned_movements: set[tuple[str, str]] = set()
    for bridge in book.balance_movement_bridges:
        key = bridge.period_id, bridge.balance_item_id
        if bridge.bridge_id in bridge_ids or key in bridge_scopes:
            issues.append(f"Duplicate balance movement bridge: {bridge.bridge_id}")
        bridge_ids.add(bridge.bridge_id)
        bridge_scopes.add(key)
        period = periods.get(bridge.period_id)
        if period is None or period.period_type == "PERIOD_END":
            issues.append(f"Balance movement bridge requires a flow period: {bridge.bridge_id}")
        item = bridge.balance_item_id
        if item not in (*REQUIRED_ITEMS["BS"], *OPTIONAL_ITEMS["BS"]) and not item.startswith(
            "other:"
        ):
            issues.append(f"Balance movement requires a BS item: {bridge.bridge_id}")
        movement_ids = bridge.movement_ids
        if len(movement_ids) != len(set(movement_ids)):
            issues.append(f"Duplicate movement reference: {bridge.bridge_id}")
        for movement_id in movement_ids:
            reference = bridge.period_id, movement_id
            if reference not in movement_rows:
                issues.append(
                    f"Unknown balance movement reference: {bridge.bridge_id} {movement_id}"
                )
            assigned_movements.add(reference)
        if movement_ids and bridge.disclosure.status in {"not_disclosed", "not_applicable"}:
            issues.append(
                f"Balance movement disclosure contradicts populated bridge: {bridge.bridge_id}"
            )
    if movement_rows.keys() - assigned_movements:
        issues.append("Balance movements require an explicit bridge assignment")
    return tuple(issues)


def _balance_movements(book: FinancialBook, period: FinancialPeriod) -> tuple[Reconciliation, ...]:
    """Step 7: equity always checked; other sourced opening/closing bridges retained."""
    bridges = {
        bridge.balance_item_id: bridge
        for bridge in book.balance_movement_bridges
        if bridge.period_id == period.period_id
    }
    movements = {
        movement.movement_id: movement
        for movement in book.balance_movements
        if movement.period_id == period.period_id
    }
    opening_date = (
        period.start_date - timedelta(days=1)
        if period.start_date and period.start_date.toordinal() > 1
        else None
    )
    items = tuple(dict.fromkeys(("total_equity", *bridges)))
    reconciliations = []
    for item in items:
        bridge = bridges.get(item)
        components = [_statement_balance(book, opening_date, item)]
        if item == "total_equity":
            income = next(
                (
                    row
                    for row in book.statement_lines
                    if row.period_id == period.period_id
                    and row.statement == "IS"
                    and row.item_id == "net_income"
                ),
                None,
            )
            components.append(
                _term(
                    "IS net income",
                    income.value if income else None,
                    outflow=income is not None and income.sign_convention == "outflow_magnitude",
                )
            )
        selected_movements = tuple(movements[i] for i in bridge.movement_ids) if bridge else ()
        components.extend(
            _term(
                movement.movement_id,
                movement.value,
                outflow=movement.sign_convention == "outflow_magnitude",
            )
            for movement in selected_movements
        )

        blockers = []
        if opening_date is None or period.end_date is None:
            blockers.append("Exact opening and closing balance dates are unavailable")
        if bridge is None or bridge.disclosure.status != "complete":
            blockers.append(
                "A complete sourced balance movement assessment is required; "
                "no inferred zero movements"
            )
        sign_citations = tuple(
            citation for movement in selected_movements for citation in movement.sign_citations
        )
        if item == "total_equity" and income is not None:
            sign_citations = (*sign_citations, *income.sign_citations)
        check = _check(
            period,
            "BALANCE_MOVEMENT",
            item,
            _statement_balance(book, period.end_date, item),
            tuple(components),
            "opening BS balance + IS net income + signed sourced movements"
            if item == "total_equity"
            else "opening BS balance + signed sourced movements",
            blocker="; ".join(blockers) or None,
            context=(*sign_citations, *(bridge.disclosure.citations if bridge else ())),
        )
        reconciliations.append(check.model_copy(update={"balance_movement_bridge": bridge}))
    return tuple(reconciliations)
```

## Final checks

- `make product-check`: **751 passed**, **97.40%** branch-inclusive coverage;
  strict mypy (40 source files), Ruff lint/format and JavaScript syntax passed.
  The first run had one inconsistent prior-year fixture and 750 passing tests;
  after the documented fixture correction, all 14 KPI tests and the complete
  product suite passed. No production rule was relaxed.
- `make check`: passed lock consistency, all-file hygiene, lint/format and staged/
  working diff checks, including the final fixture correction.
- `make secrets`: passed directory, staged diff and all reachable history scans
  with Gitleaks 8.30.1. The final staged diff was scanned again after the fixture
  change. No dependencies changed; no dependency audit was required.
- Coordinator inspected the complete candidate production/test/documentation diff
  and the applied two-function rewrite. The source-balance helper, schema bounds,
  audit wiring and readiness integration were reviewed outside tournament scope.

No new completed Module, renderer acceptance or live/native-host qualification
is claimed. No CSS/suppression changes: the prior Direction C active-navigation
exception remains unchanged. OpenRouter spend remains US$0 of US$50. Goal active.
