# Historical Model output review

Base: `09f1768`. Coordinator owns this worktree. This increment advances C with
a historical Model artifact and ratio calculation register. It does not complete
CP-1/Model, readiness, CP-1A or delivery. Live spend remains US$0; no dependency
change or public analytical/native-host qualification is claimed.

## Confidence review

Ranked doubts and investigated results:

1. **Fiscal quarter labels can conceal gaps — confirmed bug, fixed.** Before
   the patch, changing Q2 2025 to start on April 2 in the legacy synthetic case
   still produced rolling revenue 11,519. Traced `_earlier`, `_ltm_cell`, `_start`
   and `_sum`. `_rolling_days` now requires exactly four usable spans, contiguous
   in fiscal-quarter order, covering 364–371 days. Gap, overlap and unknown-start
   cases now yield null flows; closing balances remain usable. A 371-day year
   passes and a 372-day year fails. Missing quarters retain missing references
   and the existing null diagnosis. All 219 kernel regressions pass unchanged.
2. **Rolling statements using quarter opening dates — confirmed integration
   hazard, corrected.** The legacy test assembler passed quarter metadata to
   `statement_frame` with rolling values. That gives cash/debt opening dates for
   the quarter instead of the rolling year. The new API uses `ltm_columns`,
   sharing the span predicate with `ltm_frames`. Synthetic Q4 rolling cash opens
   at 5 on December 31 of the prior year, rather than the quarter's 20, and
   retains rolling net change 12 and explicit cash residual 3. Actual start/end,
   days and ordered component IDs appear in the artifact.
3. **Plausible ratios citing the wrong basis — verified fine.** Every operand
   resolves to a retained ModelValue in a separate historical or rolling
   namespace. Quarterly leverage reads debt 100 and trailing EBITDA 240;
   quarterly EBITDA margin uses revenue 100 and EBITDA 60. Interim leverage is
   not applicable; interim liquidity/debt retains its own closing inputs. LTM
   growth falling back to a prior quarter references that quarter's rolling
   year (366 days in the leap-year fixture), with denominator 320 and growth
   0.25. Corporate growth is not applicable even with a positive prior value.
4. **Formula drift, signs, nulls and rounding — verified fine.** Ratio recipes,
   scope selection and prior selection come from the same kernel definitions
   used for the result. Tests resolve every signed operand, independently sum
   each known leg and reproduce each known quotient/offset. Missing components
   remain null; zero and negative denominators retain their values and reasons.
   Ambient precision two yields the identical artifact. No display rounding,
   percentage multiplication or floating-point arithmetic is introduced.
5. **Source interpretation and omitted exposures — bounded, explicit.** Original
   observations and normalization inputs remain in the embedded historical
   report; Model values retain source/normalized/calculated categories and
   original citations. Foreign facilities keep EUR while USD debt and ratios
   carry their exclusion note. No FX is inferred. Debt basis is explicitly the
   Model basis including finance leases. Evidence tiers remain null and
   unassessed, because quote matching does not establish an analytical tier.
6. **House setting silently changing the source bridge — verified fine.** The
   default keeps the reported bridge. An explicit `exclude_unrealised=True`
   changes the output identity and excludes positive unrealized add-backs while
   preserving negative deductions. Both variants embed the identical historical
   source artifact. No historical host setting is inherited.
7. **Residuals masquerading as independent evidence — verified fine by trace.**
   Four residuals retain their exact signed formulas and kernel residual notes.
   They are not used as independent reconciliation checks. Their source inputs
   remain visible, and the report explicitly limits what these differences mean.
8. **Forged/stale results and mutation — verified fine.** The public boundary
   validates source review/pack identity and serialized contracts. Validation
   regenerates the entire artifact with the selected variant and compares its
   hash; altered formula, removed values, invalid option type and changed issuer
   are rejected. APIs have no file/network I/O; private frame maps are local and
   output contracts frozen. Independent calls do not share mutable state.
9. **Incomplete report being mistaken for completed CP-1 — open work, explicit.**
   Canonical EBIT/net-income margins and other remaining CP-1 KPIs, the complete
   statement formula register, independent derived-period reconciliation,
   four-quarter readiness, pro forma/projection integration, analytical trends,
   CP-1A and CLI/journal/Workbench delivery remain outstanding. No Module or
   live/native acceptance follows from these synthetic tests.

Fixed: dated four-quarter validation and rolling metadata supplied to statement
assembly. Verified fine: operand lineage, signs/nulls/context, explicit variant,
source retention and recomputation rejection as above. By design: unassessed
analytical tiers and labelled residuals. Still open: the integration and
qualification work in item 9; no claim that the full objective is complete.

## Scoped post-edit tournament

Targets: `_rolling_days` and `_metric_rows` only. Routine schema, metadata,
serialization and validation wrappers received confidence review and focused
tests. The five distinct review roles use fresh GPT-6.1 Sol/high contexts per the
user's matrix; coordinator model/global host settings stay unchanged.

No repository GitNexus index is present. `rg` callers: `_rolling_days` feeds
`_ltm_cell`/`ltm_frames` and `ltm_columns`; `_metric_rows` feeds `model_report`.
Both reach `validate_model_report`; statement/metric consumers and kernel tests
cover the corresponding frames. Strict mypy is the caller-contract check.
Signatures, ordering, values, exception behavior and lack of side effects are
invariants. Candidate evidence and scratch backups are local under
`artifacts/rewrite-model-output/`.

Anonymous A was incumbent, B speed, C memory and D readability. The arbiter
ran B versus C, winner versus D, winner versus A independently for each symbol.
D won both. No measured performance claim is made.

### Winner: Snippet D — `_rolling_days`

Replaces the newly added function in `src/deploy_vii/model/history.py`.

- Named start boundaries make the contiguous-calendar requirement explicit.
- A named end ordinal is shared by validation and the next-boundary calculation.
- The four-quarter order, early null exits and inclusive span bound stay intact.

### Winner: Snippet D — `_metric_rows`

Replaces the newly added function in `src/deploy_vii/financial_model.py`.

- Names distinguish own, metric and prior basis IDs directly.
- A named rolling-basis predicate exposes the quarterly scope rule.
- Growth-target and corporate-growth names clarify the two provenance branches
  without introducing caches or changing formula/result order.

### Coordinator verification

- `PYTHONPATH=. uv run --locked python artifacts/rewrite-model-output/verify_candidates.py`:
  all three challengers matched on **6,000 rolling-span cases and 250 metric-frame
  cases**, comparing exact results or exception type/message; seed 2026102103.
  Cases include missing/malformed dates, gaps/overlaps, unbuilt spans, wrong
  component counts, null/negative/zero operands, ordering and invalid metric keys.
- Backed up both full files, applied only the two function spans, then ran
  `uv run --locked pytest tests/product/test_financial_model.py tests/product/model -q`:
  **235 passed** (16 integration cases plus 219 unchanged kernel regressions).
- `uv run --locked mypy src`: **27 source files, no issues** after adoption.
- `make product-check`: **448 passed, 97.23% combined coverage**, including
  lint, formatting, strict typing and JavaScript syntax checks.
- `make check`: lock, hygiene, lint/format and diff checks passed.
- `make secrets`: working files, staged diff and reachable history passed.
  Dependencies are unchanged, so no new dependency audit was required.
- Full candidate source/tests/docs were inspected by the coordinator. Original
  pinned port-source hashes remain unchanged.

### Final code

These are the adopted functions.

`src/deploy_vii/model/history.py:570-594`

```python
def _rolling_days(spec: _Spec, earlier: list[_Spec | None], register: _Register) -> int | None:
    """Return the span of four usable, contiguous quarters, else None."""
    quarters = (*reversed(earlier), spec)
    if len(quarters) != 4:
        return None
    first_start: int | None = None
    next_start: int | None = None
    for quarter in quarters:
        if quarter is None or quarter.unbuilt is not None:
            return None
        start = _start(quarter, register.periods)
        end = iso_date(quarter.column.end_date)
        if start is None or end is None:
            return None
        end_day = end.toordinal()
        if not 1 <= start <= end_day:
            return None
        if next_start is not None and start != next_start:
            return None
        if first_start is None:
            first_start = start
        next_start = end_day + 1
    assert first_start is not None and next_start is not None
    days = next_start - first_start
    return days if LTM_DAYS[0] <= days <= LTM_DAYS[1] else None
```

`src/deploy_vii/financial_model.py:192-255`

```python
def _metric_rows(
    columns: tuple[Column, ...],
    frame: Frame,
    rolling: Frame,
    result: Frame,
    book: FinancialBook,
    observations: dict[str, Observation],
) -> tuple[ModelMetric, ...]:
    evidence = _evidence(book)
    corporate = frozenset(
        s.segment_id for s in book.segments if s.segment_type == "CORPORATE_ELIMINATION"
    )
    rows: list[ModelMetric] = []
    for column in columns:
        own = frame[column.column_id]
        own_basis_id = _basis_id(column)
        prior = metrics._prior_cells(column, columns, frame, rolling)
        growth_targets = {
            **{f"{key}_growth": key for key in metrics._GROWTH},
            **{f"bu_growth:{key.removeprefix('bu:')}": key for key in own if key.startswith("bu:")},
        }
        for key, cell in result[column.column_id].items():
            if key.startswith("metric:"):
                recipe = metrics._METRICS[key.removeprefix("metric:")]
                cells = metrics._basis(column, own, rolling, recipe.scope)
                uses_rolling = column.kind == "QUARTER" and recipe.scope != "own"
                metric_basis_id = _basis_id(column, uses_rolling)
                numerator = _leg(metric_basis_id, cells, recipe.numerator)
                denominator = _leg(metric_basis_id, cells, recipe.denominator)
                offset: Literal[-1, 0] = 0
            elif key in growth_targets:
                target = growth_targets[key]
                corporate_growth = (
                    target.startswith("bu:") and target.removeprefix("bu:") in corporate
                )
                if prior is None or corporate_growth:
                    numerator = denominator = MetricLeg(amount=None, operands=())
                else:
                    prior_column, prior_cells = prior
                    prior_basis_id = _basis_id(
                        prior_column, column.kind == "LTM" and prior_column.kind == "QUARTER"
                    )
                    numerator = _leg(own_basis_id, own, ((target, 1),))
                    denominator = _leg(prior_basis_id, prior_cells, ((target, 1),))
                offset = -1
            else:
                continue
            rows.append(
                ModelMetric(
                    calculation_id=_id("model-metric", own_basis_id, key),
                    display_basis_id=own_basis_id,
                    key=key,
                    unit=metrics.unit_of(key),
                    currency=book.currency,
                    input_scale=book.unit,
                    formula="sum(numerator signed operands) / sum(denominator signed operands)"
                    + (" - 1" if offset else ""),
                    numerator=numerator,
                    denominator=denominator,
                    offset=offset,
                    value=_value(cell, observations, evidence),
                )
            )
    return tuple(rows)
```
