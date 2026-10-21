# Source statement increment review

Base: `8b8296c`; scope: full source statements, source equations, deterministic
projection and their existing CP-1 adapter/reconciliation callers. Coordinator
owns this worktree. This is a milestone C increment, not a completed Module.
No live model calls, dependency changes, publication or native-host qualification.

## Confidence review

Least confident about, ranked by correctness impact:

1. Source statements bypassing canonical-account guards. Traced the adapter,
   reconciliation and validation paths; reproduced unresolved source CFO being
   hidden by a known compact value and source COGS bypassing expenses-by-nature
   validation. **Confirmed bugs, fixed:** validate every linked source observation,
   reject unresolved source/known compact conflicts and known numerical
   disagreements. Explicit compact missing values remain unknown; absent compact
   keys alone can use exact semantic source links.
2. Sign normalization changing analytical meaning. Reproduced a positive signed
   tax benefit becoming negative under a guessed outflow list, then a cited
   positive tax expense disagreeing between the statement and kernel adapters.
   **Confirmed bugs, fixed:** retain signed values outside the adopted canonical
   outflow semantics; require cited explicit magnitude semantics for additional
   normalization and apply them consistently. Preserve raw amounts and citations.
   Low ambient Decimal precision does not round exact sign changes. Income
   statement cash interest/tax do not alias cash-flow cash-paid observations.
3. Independent arithmetic accidentally proving itself. Traced `_statement_check`
   through `_identity_terms` to `_check`. **Verified fine:** original leaves are
   used; a reported subtotal changed from 65 to 75 is independently BLOCK while
   a parent's correct leaf sum remains 60. Missing opposite-signed D&A terms
   remain unknown rather than cancel to zero. Complete source disclosure is
   required; absent/partial disclosures or equations produce null BLOCK.
4. Equation graph safety and signed overlap. Reproduced valid subtraction being
   rejected by an initial unsigned overlap guard. **Confirmed bug, fixed:** track
   signed weights in component order; reject same-direction overlap and entirely
   cancelled equations. **Verified fine:** cycle/missing/cross-statement/detail/
   duplicate checks; twelve-level limit even through cached descendants; shared
   subtree expansion budget. Raw and expanded budgets serve different purposes.
5. Coefficient coercion. Reproduced Pydantic Literal accepting `True` and `1.0`
   as +1. **Confirmed bug, fixed:** a before-validator requires exact integer
   type before the -1/+1 literal check. Monetary inputs remain finite Decimal
   observations under the existing strict review boundary.
6. Same-date balance aliases beyond the compact Model vocabulary. Reproduced
   total assets 100 for Q2 and 200 for a period-end record on the same date being
   accepted. **Confirmed bug, fixed:** compare every source balance-sheet item
   across same-date periods. The equal-value case remains accepted.
7. Provenance and forged output. **Verified fine:** revalidation walks nested
   source, sign, equation and disclosure citations; report identity and hashes
   bind the input pack/review. Deterministic recomputation rejects removed cells,
   unknown books and identity drift. Long observation IDs get bounded hashed
   normalization IDs. Exact serialized term/citation comparisons cover traversal
   order, conflicting alternatives, repeated leaves and first-occurrence dedup.
8. Coverage and sparse input. **Verified fine:** all 65 required r14 items appear
   for applicable periods, omitted items remain null with reasons, extra source
   rows remain ordered, and flow statements reject period-end-only input. The
   full suite checks integration with the prior financial and execution code.
9. State/concurrency/error paths. **By design:** these helpers are deterministic,
   local and immutable; no file/network mutation or new asynchronous seam exists.
   They revalidate serialized review inputs before expansion/calculation.
   Unknown source amounts are not resolved by projection or algebra.
10. Analytical interpretation and delivery. **Open:** correct classifications,
    source equation meaning, completeness and reported precision require actual
    analytical qualification. Full CP-1 narrative/tables, constructed-period and
    calculation registers, readiness, CP-1A and journal/HTML binding remain next
    work. Synthetic correctness is not source interpretation or Module acceptance.

Fixed: source/compact bypasses, tax sign semantics and adapter disagreement,
signed-overlap false rejection, coefficient coercion, same-date full-statement
balances. Verified fine/by-design/open are detailed above, not inferred from a
green suite alone. Temporary first implementations also had an erroneous call
argument and identity attribute; strict typing and focused tests caught both.

## Scoped post-edit tournament

Per the user's correction, only `_identity_issues` (state of the financial
component graph) and `_identity_terms` (source provenance expansion) entered.
Routine contracts, projection, adapter helpers and tests received confidence
review and focused tests. No blanket branch tournament.

Five distinct roles ran on explicit GPT-6.1 Sol/high routes with fresh context,
except the already Sol/high memory reviewer reused for this scoped review.
The coordinator route stayed unchanged. The scratch brief included actual code,
callers, signatures, first-error/citation ordering, depth/expansion accounting and
unknown-cancellation invariants. Anonymous bracket: B versus C, winner versus D,
winner versus A. A was incumbent, B speed, C memory, D readability. No measured
performance claim was used.

Impact set (no repository GitNexus index): `_identity_issues` → `statement_issues`
→ `book_issues` → `validate_financial_review` → kernel/reconciliation/statement
adapters; `_identity_terms` → `_statement_check` → CFO and source-equation checks
→ `reconcile_financials` → deterministic report validation. `rg` confirmed the
references; strict mypy covered all 25 source files after adoption.

### Winner: Snippet B for `_identity_issues`

Replaces the just-written function in `src/deploy_vii/statement_validation.py`.

- Child weights, height and path count return together, removing dependence on
  reading a separate memo side effect immediately after recursion.
- Cached metadata and the equation are read once, making reuse and leaf handling
  easier to follow without introducing an alternate traversal state encoding.
- Structural diagnostics still precede reference/expansion checks; the bounded
  algorithm and signed accumulation order are preserved.

### Winner: Snippet D for `_identity_terms`

Replaces the just-written function in `src/deploy_vii/financial_reconciliation.py`.

- `inherited_sign` and `component` make path and operand signs distinct.
- The exact-sign multiplication comment explains the constrained equality test.
- Eager traversal, repeated leaf terms and ordered citation collection remain
  simple; no generator or alternate state abstraction is introduced.

### Verification

Coordinator independently ran:

- `PYTHONPATH=. uv run --locked python artifacts/rewrite-statements/verify_candidates.py`:
  all three candidates matched the incumbent on 1,817 graph comparisons and
  600 exact serialized term/citation expansions (seed 20261021). Includes invalid
  structural graphs, cycles, order changes, cached depths, signed overlap/netting,
  expansion limits, unknown/conflicting observations and repeated evidence.
- `uv run --locked pytest tests/product/test_statements.py tests/product/test_financials.py tests/product/test_reconciliation.py -q`:
  **112 passed** after adoption.
- `uv run --locked mypy src`: **25 files, no issues** after adoption.

Whole-file backups were made before adoption; only the two AST function spans
were replaced. The coordinator inspected the full candidate diff, including new
files, and rechecked callers. Final suite/hygiene results are recorded below.

### Final code

These are the adopted functions, not unverified proposals.

```python
def _identity_issues(book: FinancialBook) -> list[str]:
    """Reject circular, duplicate and overlapping arithmetic within one statement."""
    lines = {(r.period_id, r.line_id): r for r in book.statement_lines}
    identities = {(r.period_id, r.target_line_id): r for r in book.statement_identities}
    issues: list[str] = []
    if len(identities) != len(book.statement_identities):
        issues.append("Duplicate statement identity target")
    if len({r.identity_id for r in book.statement_identities}) != len(book.statement_identities):
        issues.append("Duplicate statement identity ID")
    references = 0
    for row in book.statement_identities:
        references += len(row.components)
        target = lines.get((row.period_id, row.target_line_id))
        keys = [(row.period_id, c.line_id) for c in row.components]
        if target is None or any(k not in lines for k in keys):
            issues.append(f"Unknown statement identity line: {row.identity_id}")
            continue
        if target.line_kind == "detail":
            issues.append(
                f"Statement identity target must be a subtotal or total: {row.identity_id}"
            )
        if any(lines[k].statement != target.statement for k in keys):
            issues.append(f"Statement identity mixes statements: {row.identity_id}")
        if len(set(keys)) != len(keys):
            issues.append(f"Duplicate statement identity component: {row.identity_id}")
    if issues:
        return issues
    if references > 20000:
        return ["Statement identities exceed 20000 component references"]
    active: set[tuple[str, str]] = set()
    memo: dict[tuple[str, str], tuple[dict[tuple[str, str], int], int, int]] = {}
    expanded = 0

    def descend(key: tuple[str, str], depth: int) -> tuple[dict[tuple[str, str], int], int, int]:
        nonlocal expanded
        if key in active:
            raise ValueError(f"Cyclic statement identity: {key[0]} {key[1]}")
        cached = memo.get(key)
        if depth > 12 or (cached is not None and depth + cached[1] - 1 > 12):
            raise ValueError("Statement identity nesting exceeds twelve levels")
        if cached is not None:
            return cached
        active.add(key)
        equation = identities.get(key)
        covered: dict[tuple[str, str], int] = {key: 1} if equation is None else {}
        height = 1
        size = 1 if equation is None else 0
        if equation is not None:
            for term in equation.components:
                part, child_height, child_size = descend((key[0], term.line_id), depth + 1)
                height = max(height, 1 + child_height)
                size += child_size
                for leaf, weight in part.items():
                    contribution = weight * term.coefficient
                    prior = covered.get(leaf, 0)
                    if prior * contribution > 0:
                        raise ValueError(
                            f"Overlapping statement identity components: {key[0]} {key[1]}"
                        )
                    covered[leaf] = prior + contribution
        covered = {leaf: weight for leaf, weight in covered.items() if weight}
        if not covered:
            raise ValueError(f"Statement identity has no independent components: {key[0]} {key[1]}")
        expanded += size
        if expanded > 20000:
            raise ValueError("Expanded statement identities exceed 20000 terms")
        active.remove(key)
        result = covered, height, size
        memo[key] = result
        return result

    try:
        for key in identities:
            descend(key, 1)
    except ValueError as error:
        issues.append(str(error))
    return issues
```

```python
def _identity_terms(
    book: FinancialBook,
    identity: StatementIdentity,
) -> tuple[tuple[ReconciliationTerm, ...], tuple[Citation, ...]]:
    """Expand validated identities to source leaves; never reuse a reported plug.

    Repeated opposite-signed leaves stay present, so unknown operands cannot
    disappear through algebraic cancellation. Validation bounds expansion/depth.
    """
    lines = {r.line_id: r for r in book.statement_lines if r.period_id == identity.period_id}
    equations = {
        r.target_line_id: r for r in book.statement_identities if r.period_id == identity.period_id
    }
    terms: list[ReconciliationTerm] = []
    context: list[Citation] = []

    def expand(equation: StatementIdentity, inherited_sign: Literal[-1, 1]) -> None:
        context.extend(equation.citations)
        source = lines[equation.target_line_id].value
        context.extend(source.citations)
        context.extend(c for alternative in source.alternatives for c in alternative.citations)
        for component in equation.components:
            # Multiplying two exact integer signs gives +1 when they agree.
            coefficient: Literal[-1, 1] = 1 if component.coefficient == inherited_sign else -1
            if component.line_id in equations:
                expand(equations[component.line_id], coefficient)
            else:
                terms.append(
                    _term(
                        component.line_id, lines[component.line_id].value, coefficient=coefficient
                    )
                )

    expand(identity, 1)
    return tuple(terms), tuple(dict.fromkeys(context))
```

### Final checks

- `make product-check`: **413 passed**, **97.03% combined coverage**; lint,
  formatting, strict typing and JavaScript syntax also pass.
- `make check`: lock, all tracked-file hygiene hooks and staged/unstaged whitespace
  checks pass, including newly staged files.
- `make secrets`: working files, the staged diff and reachable Git history pass;
  no secrets found. No dependency change, so no new dependency audit was needed.
- Full candidate diff inspected. No changes to CSS or the intentional Direction C
  active-navigation indicator; the previously recorded narrow side-tab exception
  remains the only design suppression. No unresolved design finding is introduced.
