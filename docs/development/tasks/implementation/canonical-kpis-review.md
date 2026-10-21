# Canonical KPI increment review

Base: `a3f44fb`. New internal canonical calculation API and synthetic regressions;
no dependencies, UI edits or live model calls. Coordinator owns the worktree.

## Confidence review

Least confident about, ranked:

1. Canonical debt could silently inherit Model's lease-inclusive subtotal. Traced
   source account, statement and ratio paths. A synthetic finance lease makes
   Model debt 150 while canonical debt remains 100, with separate value IDs.
   Missing canonical debt stays null even when facilities are present. Verified.
2. Canonical earnings could silently prefer adjusted or recalculated EBITDA.
   Source reported and adjusted variants are explicit; differing source values
   produce distinct denominators. Missing direct income derives in dependency
   order; explicit zero/negative, conflict and not-applicable states do not select
   a different known figure. Missing derived-period components stay null.
3. A missing quarter could make rolling recalculation discard another quarter's
   source earnings. Reproduced: source Q3 EBITDA 80, missing Q2 calculated as 60;
   initial rolling result was 240 rather than 260. Root cause was rebuilding a
   single aggregate instead of summing canonical quarter selections. Added
   `_rolling_frame`, retaining all four actual operands and span checks.
4. FFO reconstruction could depend on an unrelated EBITDA residual. Reviewed the
   pinned FFO = CFO − working-capital identity and selected financing adjustments.
   Canonical FFO now uses those two explicit signed operands directly; Model
   calculation behavior is unchanged. No residual is called independent evidence.
5. Unit/sign/period or precision seams could misstate ratios. Tested signed capex
   and interest, ambient precision 3, exact ratio legs, positive denominator
   guards, quarter-own margins and rolling leverage. Like-period growth links
   the previous year's canonical values. Invalid calendar spans preserve known
   closing balances but cannot establish a known rolling denominator.
6. Nulls could erase conflicts or manufacture unsupported definitions. The source
   leaf traversal includes failed-sum operands. Affected KPIs remain null and
   carry Conflicted status. DCF and FFO interest coverage stay explicit Not
   Available rows with no made-up operands. The user's clarification is pending.
7. Provenance or report edits could be trusted without recomputation. Every leg
   resolves to retained canonical values; every value has a computation root.
   Frozen identity validation precedes calculation; removing a KPI or changing
   issuer identity is rejected. The report binds source/review hashes via its
   embedded historical artifact. Evidence tier/trend remain explicitly unassessed.

Fixed: lost reported-quarter contribution in rolling earnings; canonical income
selection/cascade and conflict propagation were verified during implementation.
Verified fine: debt separation, signed arithmetic, source choices, growth/period
basis, invalid spans, nulls and recomputation. By design: independent source
reconciliation and analytical approval are separate from calculation output.
Open: DCF and FFO interest coverage definitions, source-backed audit/FX exceptions,
full CP-1/Model binding and analytical/rendering/native acceptance.

## Scoped tournament

Only `_canonical_frame` and `_rolling_frame` are selected: source/derived financial
choices and rolling arithmetic are the key areas in this increment. Serialization,
report assembly and wrappers receive confidence review and focused tests. Fresh
incumbent/challengers/arbiter use GPT-6.1 Sol/high per the user model matrix.

GitNexus returned repository-not-indexed. `rg` identified only `canonical_kpis`
as their direct caller, then `validate_canonical_kpis` and the new tests.
Strict mypy is the caller-contract oracle. No CLI/journal/renderer uses this API yet.

Winner: **Snippet C**, replacing `_canonical_frame` (lines 172–214) and
`_rolling_frame` (lines 222–250) in `src/deploy_vii/canonical_kpis.py`.
Bracket: A over B; C over A; C over D (incumbent).

- Descriptive names make the operating-income dependency and construction-to-column
  lookup easier to inspect.
- Grouped income and cash/debt steps retain explicit signed operands and the same
  calculation order.
- The same control flow and allocation pattern avoid adding caches or mutable
  operand assembly. This is a readability choice, with no performance claim.

The coordinator backed up the module before applying C and inspected the exact
replacement diff: names, spacing and docstrings changed; financial behavior did not.
All three challengers matched the incumbent in 51 complete serialized-report
comparisons across 14 tests, including metadata, arithmetic graphs and input
immutability. Scratch comparison code and output remain in ignored
`artifacts/canonical-kpis-tournament/`. The arbiter's concern about B's generator
consumption was resolved by inspecting `calc`, which eagerly materializes its
iterable, and by the comparisons; B is not claimed incorrect.

After applying C, `uv run --locked pytest tests/product/test_canonical_kpis.py
tests/product/test_financial_model.py -q` passed **30 tests**. `uv run --locked
mypy src` passed all **31 source files**; focused Ruff lint/format passed.
Concrete financial invariant: Q3 reported EBITDA 80 plus three canonical quarters
of 60 yields rolling EBITDA 260 even when one quarter is derived. Closing debt
remains 100 and a broken annual span leaves rolling leverage unavailable.
The public builders/validator and typed caller set remain intact.

Final code for the two reviewed functions:

```python
def _canonical_frame(
    accounts: Frame, statements: Frame, observations: dict[str, Observation]
) -> Frame:
    """Select source income and carrying debt, then derive dependent scalars."""
    result: Frame = {}
    with localcontext(CONTEXT):
        for column_id, statement in statements.items():
            source = accounts[column_id]
            cells = {key: statement.get(key, ABSENT) for key in _SCALARS}

            cells["gross_profit"] = _preferred(
                source.get("acct:gross_profit", ABSENT), cells["gross_profit"], observations
            )
            operating_income_base = (
                cells["revenue"]
                if statement["cogs"].reason == "NOT_SOURCED"
                else cells["gross_profit"]
            )
            cells["ebit"] = _preferred(
                source.get("acct:ebit", ABSENT),
                calc(((operating_income_base, 1), (statement["opex_total"], 1))),
                observations,
            )
            cells["ebitda"] = _preferred(
                source.get("acct:ebitda", ABSENT),
                calc(((cells["ebit"], 1), (cells["da"], -1))),
                observations,
            )
            adjustments = tuple(
                (value, 1) for key, value in source.items() if key.startswith("addback:")
            )
            cells["adjusted_ebitda"] = _preferred(
                source.get("acct:adjusted_ebitda", ABSENT),
                calc(((cells["ebitda"], 1), *adjustments)),
                observations,
            )

            cells["ffo"] = calc(((cells["cfo_adjusted"], 1), (cells["working_capital_change"], -1)))
            cells["total_debt"] = source.get("acct:total_debt", ABSENT)
            cells["secured_debt"] = source.get("acct:senior_secured_debt", ABSENT)
            cells["net_debt"] = calc(((cells["total_debt"], 1), (cells["cash_closing"], -1)))
            result[column_id] = cells
    return result


def _rolling_frame(
    frame: Frame, rolling: Frame, bases: tuple[ModelBasis, ...], historical: HistoricalReport
) -> Frame:
    """Sum canonical flow cells for trailing quarters, retaining every operand."""
    column_by_construction = {
        node.construction_id: node.column_key for node in historical.constructions
    }
    result = {key: dict(cells) for key, cells in rolling.items()}
    with localcontext(CONTEXT):
        for basis in bases:
            if basis.scope != "trailing_four_quarters":
                continue
            for key in _SCALARS:
                if key in _BALANCES:
                    continue
                parts = tuple(
                    (ABSENT if part is None else frame[column_by_construction[part]][key], 1)
                    for part in basis.quarter_construction_ids
                )
                value = calc(parts)
                if basis.days is None:
                    value = replace(
                        value,
                        value=None,
                        reason="COMPONENT_MISSING",
                        note=join_notes(value.note, basis.limitation),
                    )
                result[basis.column_key][key] = value
    return result
```

## Pinned source evidence

Read-only Git objects; no old code copied in this increment.

| Source | SHA-256 |
| --- | --- |
| `reference/deploy-v-r14/skills/cp-1-canonical-data-foundation/references/CP-1_RUNBOOK.md` | `7934e8c562832b8320243cbf08e84b16575a0d2e4974fd918bf094b300fcd4ad` |
| `reference/deploy-v-r14/skills/cp-1-canonical-data-foundation/references/REF_CP-1_STEPS.md` | `e9552f0d2b128cbe27ec58cdc2360e0e67c96a9f6ec21a140854f310de201bc1` |
| `reference/deploy-v-r14/skills/cp-model/scripts/cp_model_v3/calculations.py` | `f29da526595bce63e652c729b6378a1898edf48b95846a7ddbea628a462d7840` |
| `reference/deploy-v-r14/skills/cp-model/scripts/cp_model_v3/workbook.py` | `28535e7aade8f1a010a9d2c35205a41864cf79f4ae38675e257c667eeabc337d` |

## Design hook triage

The attribution-unknown side-tab finding in `src/deploy_vii/assets/app.css:2`
selects `.module-link[aria-current=page]`, an active navigation indicator.
Direction C reference lines 243 and 291 retain navigation edges. The existing
rule/value/file exception in `.impeccable/config.json` already covers it.
Fixed: none. Newly suppressed: none. Left standing: intentional active-navigation
styling, with its existing narrow exception retained. No UI edits or new
completed-Module rendering acceptance are claimed.

## Final verification

`make product-check` passed: lint/format, strict typing of 31 source files,
JavaScript syntax and **518 product tests**, including four browser regressions.
Combined line/branch coverage is **97.37%** (90% floor); the new canonical module
reports 98%. Log: ignored `artifacts/canonical-kpis-product-check.log`.
No dependency changes, live calls or new analytical acceptance. OpenRouter spend
remains **US$0 / US$50**. DCF and FFO coverage questions remain unanswered.

`make check` passed all-file hygiene and diff checks. `make secrets` passed
working-directory, staged-diff and reachable-history scans with no leaks.
The full nine-file candidate diff was inspected by the coordinator before commit.
