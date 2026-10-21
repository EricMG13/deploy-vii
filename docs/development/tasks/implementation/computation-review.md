# Historical computation provenance review

Base: `31a0bb1`, branch `codex/development-environment`, 21 October 2026.
Scope: historical statement arithmetic metadata and its immutable artifact,
controlled net income, EBIT/net-income margins and reported EBITDA growth.
No dependencies, UI, host settings, live calls or analytical acceptance changed.

## Confidence review

Least confident about, ranked:

1. Traces could silently change money or omit failed arithmetic. Investigated
   `calc`, history sums, debt subtotals, statement days ratios and every new
   `Cell`/`replace` path. Metadata is keyword-only and excluded from legacy
   numeric equality; arithmetic order and Decimal context stay unchanged.
   Independent tests recompute every sum and three-input days ratio in the
   synthetic report. Missing COGS remains null and reachable with its original
   observation/citation; zero-denominator DIO retains all inputs. Verdict: fine
   for the historical operations exposed by this API. Early semantic refusals
   that execute no arithmetic remain unavailable with their reason; PF arithmetic
   and projections are outside this report and remain pending.
2. Provenance could collapse equal amounts from different origins or change
   output order. Object-identity memoization is separate from complete-content
   deduplication. Model roots resolve to exactly the same `PeriodValue`, and
   nodes retain ordered signed operands. Shared/copy graphs test root order,
   topological order and deduplication. Missing input sources are retained
   separately from aggregate sources; unknown source lookup fails closed.
   Verdict: fine; no source inference or floating-point conversion introduced.
3. Serialization could accept altered graphs. `financial-model/2` explicitly
   changes the schema and requires computation roots/register. Deterministic
   regeneration compares the complete artifact hash; removing operands from an
   actual arithmetic node is rejected. Verdict: fine. Raw frozen Cells are an
   internal trusted kernel interface, not a model-response validation boundary.
4. New canonical ratios could invent net income or pro forma comparability.
   The source IS mapping is explicit and net income uses the existing flow
   period rules. Tests verify quarter/LTM margins, no pretax-minus-tax plug,
   distinct reported EBITDA growth and PF margin exclusions. Verdict: fine.
   The first fixture used unstable line IDs across periods and correctly failed
   source validation; the fixture now uses a stable line identity. The existing
   controlled-flow count intentionally increases from 25 to 26. The full suite
   found a second stale adapter account-count assertion (35 to 36); it now
   also verifies that omitted net income stays unknown.
5. Shared graphs could expand exponentially or cycle. Identity memoization visits
   each shared object once; a 100-level shared graph emits 101 nodes. A forged
   cycle raises the documented ValueError. Public inputs pass period validation
   (maximum four component levels) and fixed statement constructors before this
   serializer. Verdict: fine for this bounded pipeline. Arbitrarily deep direct
   internal graphs can hit Python's recursion limit; no claim of an unbounded
   graph API is made. No global cache, mutation or I/O is added.
6. Canonical completeness could be overstated. The pinned r14 material names
   DCF but provides no formula in the inspected runbook, steps, system reference
   or selected calculation code. An explicit question is pending: source-defined
   only, FCF less dividends, or FCF less dividends and buybacks. No answer or
   default has been adopted. Remaining canonical KPIs, derived-period independent
   reconciliation, readiness, CP-1A, delivery and live qualification remain open.

Fixed: original missing-input provenance and absent calculation edges are now
retained; required margins/growth are added. The fixture identity error was fixed.
Verified fine: numerical regressions, failed/zero arithmetic, content identity,
ordering, tamper rejection, explicit source mapping and PF exclusions as above.
By design: internal trusted Cells, bounded recursion, no source inference,
separate finance-lease Model debt basis, explicit unavailable early refusals.
Still open: DCF definition and the remaining product/qualification work above.

## Scoped post-edit tournament

Only `calculation_trace.trace_cells` (including nested `visit`) was selected:
this is new provenance identity/traversal logic. Small arithmetic metadata
attachments and declarative metric mappings received focused tests and confidence
review. Routine code and imported unchanged algorithms were not tournamented.
All five review roles used fresh GPT-6.1 Sol/high contexts under the user's model
matrix; coordinator settings were unchanged. No repository graph index was
available; actual references establish `model_report` and `validate_model_report`
as callers, with direct graph tests. Strict typing checks that impact set.

**Winner: Incumbent holds**, `src/deploy_vii/calculation_trace.py:37–102`.
Anonymous bracket: A over B; C over A; D (incumbent) over C.

- Separate active-path and completed-object collections make cycle/shared-node
  behavior explicit without a sentinel assumption.
- Direct input-source normalization avoids extra dependency-sensitive branches.
- Compact local expressions preserve clear traversal and exception ordering;
  no challenger demonstrated a material improvement.

Coordinator verification compared complete node serialization, root order and
exceptions across all four candidates on 100 deterministic shared DAGs plus five
source/cycle/mixed-error cases. All matched. The target was backed up locally;
no replacement was necessary. No speed or memory benchmark claim is made.
Final code is reproduced below so the accepted candidate is reviewable.

```python
def trace_cells(
    cells: Mapping[str, Cell], book: FinancialBook
) -> tuple[tuple[Computation, ...], dict[str, str]]:
    """Return a content-addressed DAG and each output ID's computation root.

    Shared subexpressions are visited once by object identity and identical
    nodes are deduplicated by complete content. No Python object IDs escape.
    """
    observations = {o.observation_id: o for o in records(book, Observation)}
    evidence = _evidence(book)
    nodes: dict[str, Computation] = {}
    visited: dict[int, str] = {}
    active: set[int] = set()

    def visit(cell: Cell) -> str:
        identity = id(cell)
        if identity in visited:
            return visited[identity]
        if identity in active:
            raise ValueError("Cyclic kernel arithmetic")
        active.add(identity)
        arithmetic = cell.arithmetic
        operands = (
            tuple(
                ComputationOperand(computation_id=visit(part), coefficient=sign)
                for part, sign in arithmetic.operands
            )
            if arithmetic is not None
            else ()
        )
        located = (
            replace(cell, sources=cell.input_sources, basis="REPORTED")
            if cell.input_sources
            else cell
        )
        value = _value(located, observations, evidence)
        operation: Literal["sum", "ratio_times", "input", "constant", "unavailable"]
        if arithmetic is not None:
            operation = arithmetic.operation
        elif located.sources:
            operation = "input"
        else:
            operation = "unavailable" if cell.value is None else "constant"
        node_id = _id(
            "computation",
            operation,
            value.content_hash(),
            *(f"{o.computation_id}:{o.coefficient}" for o in operands),
        )
        node = Computation(
            computation_id=node_id,
            operation=operation,
            operands=operands,
            value=value,
            formula=_FORMULAS[operation],
        )
        existing = nodes.get(node_id)
        if existing is not None and existing != node:
            raise ValueError("Conflicting computation identity")
        nodes[node_id] = node
        visited[identity] = node_id
        active.remove(identity)
        return node_id

    roots = {key: visit(cell) for key, cell in cells.items()}
    return tuple(nodes.values()), roots
```

## Verification

- `uv run --locked pytest tests/product/test_calculation_trace.py tests/product/test_financial_model.py tests/product/test_financial_periods.py tests/product/model -q`: 263 passed.
- `make product-check`: 457 passed, 97.24% coverage; Ruff lint/format, strict mypy (28 source files) and JavaScript syntax passed.
- `make check`: passed (locked environment, full-file hooks and both diff checks).
- `make secrets`: passed for files, staged changes and reachable history; no leaks found. No dependency changes required an audit.

Design-hook triage: the prior narrow `side-tab` exception remains intentional
for Direction C active navigation, as recorded in `.impeccable/config.json` and
commit `9199be4`. No CSS changed, no new suppression was added and no design
finding remains unresolved in this increment.
