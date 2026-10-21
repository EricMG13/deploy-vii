# Historical period artifact review

Base: `6b14433`. Scope: `financial_periods.py`, two deliberate corrections in
`model/periods.py`, new integration regressions and two legacy day-count assertion
updates. Coordinator owns the worktree. This advances milestone C; Model
statement/ratio artifacts, readiness, CP-1A and journal/HTML integration remain
pending. No Module acceptance, analytical qualification, native-host acceptance,
dependency change or live model spend is claimed.

## Confidence review

Ranked doubts and investigated results:

1. **Incompatible periods yielding plausible arithmetic — confirmed bugs, fixed.**
   A source H1 starting in February minus Q1 starting in January returned known
   Q2=20. A source LTM's 364-day span relabelled a component-built 365-day period.
   An FY without a provable duration yielded a known LTM. Each was reproduced
   in the new artifact tests before patching. Calculated quarters now require
   a dated common-start prefix. LTM days come from component counts or complete
   source dates; unknown complete spans and spans outside 364–371 days block.
   Incompatible supplied LTM dates block flows while retaining computed days.
   Two old day-count assertions now explicitly adopt component-owned 365 days;
   monetary, rate, missing-component and remaining legacy assertions are intact.
2. **Overcorrecting legitimate missing optional counts — verified fine after
   refinement.** Initially marking every missing aggregate count unspanned
   changed missing-component notes and rejected complete dated quarters. Traced
   `_start`, `_dated`, `_term_days`, `_rolled` and all period callers. Calendar
   fallback now requires complete dated terms; genuinely absent terms retain
   the prior null diagnosis. Complete dates can establish 365 days even without
   an optional count. Raw-kernel malformed input behavior was compared across
   all tournament candidates; the public adapter validates inputs first.
3. **Balances/rates being summed like flows — verified fine.** Derived-quarter
   total debt retains its closing balance (30), not H1 minus Q1 (20). Exact
   rates do not fill derived periods, and KPI units stay separate from monetary
   currency/scale. Flow operand lists alone contain signed construction terms.
4. **Reported figures becoming plugs — verified fine.** LTM components 100 + 30
   - 20 produce 110 while reported 999 stays separate. Removing the prior stub
   makes the result null, still retaining 999 as stated. Explicit FY component
   values sum to 100 while independently stated 999 remains visible. Nested
   construction references resolve to nodes; direct period components resolve
   to the retained source-period register and input observations.
5. **Source/normalized/calculated categories and provenance — verified fine.**
   Original observations, including conflict alternatives and gap reasons, are
   embedded alongside the exact adapter inputs. Known source cells retain IDs
   and quotes; exact sign changes become normalized values with sign evidence.
   Issuance-derived zero keeps its separate facility evidence. Foreign facility
   currency survives; no FX inference is performed. Unknown provenance raises
   instead of yielding an uncited number. Evidence is indexed once per report,
   avoiding a full source scan for each cell.
6. **Identity collisions and stale/forged output — verified fine.** A raw quarter
   named like a generated subtraction produces a duplicate kernel key; the
   artifact rejects distinct constructions sharing it. Long valid source IDs
   produce bounded, unique artifact IDs. Run/issuer/date/method and input hashes
   are revalidated. Removing values or changing the book is rejected by complete
   deterministic recomputation. Decimal values remain exact strings at the
   contract boundary; no float conversion or display rounding is introduced.
7. **Ambient arithmetic context and limits — verified fine.** All reader/operand
   evaluation uses the kernel's 38-significant-digit half-even context. A caller
   context of precision two produces the same artifact. Input precision, period
   graphs, dates, dimensions and register bounds are inherited from the validated
   source boundary; private kernel rows are not accepted as external inputs.
8. **Mutation, concurrency and errors — by design.** The APIs perform no file or
   network I/O. Local kernel memo dictionaries are rebuilt per report and never
   escape; output contracts are immutable. Missing values retain reasons rather
   than acquiring inferred zero. Shape validation alone is not acceptance;
   downstream code must use `validate_historical_report` and the bound inputs.
9. **What the artifact proves — open integration work.** It exposes historical
   source/normalized series, constructed values and their operands, not the
   complete Model. It inherits the adapter's assessed-add-back-bridge requirement.
   Independent derived-period reconciliation, statement/ratio numerator and
   denominator registers, final readiness, CP-1A, HTML parity, public analytical
   tests and native host delivery remain unfinished. Source interpretation and
   classification require qualification; `Verified` is only the source-value
   calculation status, never an analytical acceptance claim.

Fixed: three reproduced period/span bugs. Verified fine and by-design findings
are supported above by source tracing and concrete regressions. Routine initial
lint/type issues were corrected before candidate review. No unresolved bug is
being promoted to readiness or Module acceptance.

## Scoped post-edit tournament

Only `_calculated_quarters` and `_host_ltm` entered, following the user's limit
on tournaments to key areas and two symbols per pass. The routine report adapter
received confidence review and focused tests. Five distinct reviewers used
explicit fresh GPT-6.1 Sol/high contexts from the model matrix; the coordinator
route and global settings were unchanged.

No repository GitNexus index exists. `rg` identified `_calculated_quarters` →
`_quarters` → `_plan`, and `_host_ltm` → `_plan`; consumers include
`historical_columns`, `account_frame`, `ltm_frames`, statement/metric assembly
and `historical_report`. Strict typing and the regression suite covered these
callers. Signatures, ordering, dataclass fields, error behavior and side effects
were held fixed. Backups were made before applying only the two function spans.

Anonymous bracket for each symbol: B versus C, winner versus D, winner versus A.
A was incumbent, B speed, C memory and D readability. The arbiter selected D for
both; the coordinator independently verified all candidates before adoption.
No benchmark or measured performance improvement is claimed.

### Winner: Snippet D — `_calculated_quarters`

Replaces the just-modified function in `src/deploy_vii/model/periods.py`.

- Explicit quarter-number/operand tuples express the three ordered recipes
  without a mapping used only for iteration.
- `whole_period` and `prefix_period` connect subtraction directly to the dated
  prefix requirement.
- The exact missing/reported-quarter handling, retained terms, dates and
  unspanned diagnosis remain intact.

### Winner: Snippet D — `_host_ltm`

Replaces the just-modified function in `src/deploy_vii/model/periods.py`.

- A signed accumulator with loop completion publishes a fallback span only when
  every dated component is usable.
- The named invalid-span predicate and docstring make component ownership of
  the span explicit.
- First matching source identity, term order, missing-component diagnoses and
  computed days on a stated mismatch remain unchanged.

### Verification

- `PYTHONPATH=. uv run --locked python artifacts/rewrite-periods/verify_candidates.py`:
  all three candidates matched the incumbent on **4,000 quarter cases and 3,990
  LTM cases**, comparing exact dataclasses or exception type/message; seed
  2026102102. Cases include optional/malformed dates, missing/duplicate rows,
  fiscal labels, absent/zero/negative day counts and ordering changes.
- `uv run --locked pytest tests/product/test_financial_periods.py tests/product/model -q`:
  **238 passed** after adoption (19 new integration cases and 219 kernel cases).
- `uv run --locked mypy src`: **26 files, no issues** after adoption.
- `make product-check`: **432 passed, 97.15% combined coverage**, including
  lint, formatting, strict typing and JavaScript syntax checks.
- `make check`: lock, repository hygiene, lint/format and diff checks passed.
- `make secrets`: working files, staged diff and reachable history passed;
  no dependency change required a new audit.

Design-hook triage: the existing `side-tab` finding identifies the intentional
Direction C active-navigation indicator, not a card accent. The previously
committed rule/value exception is restricted to `src/deploy_vii/assets/app.css`.
No CSS was changed, no suppression was broadened and no design finding remains
unresolved in this increment.

The coordinator inspected the full candidate diff and preserved the original
port source hashes. The final whole-product/hygiene results follow below.

### Final code

These are the adopted functions.

```python
def _calculated_quarters(regs: Cp1Registers) -> list[_Spec]:
    """Q2 = H1 - Q1, Q3 = 9M - H1 and Q4 = FY - 9M, where the register has
    no such quarter and both periods exist."""
    reported = _by_quarter(_of_type(regs, "QUARTER"))
    ytd = _by_quarter(_of_type(regs, "YTD"))
    fiscal = {_year(p): p for p in _of_type(regs, "FY")}
    specs = []
    for year in dict.fromkeys(_year(p) for p in regs.periods):
        candidates = (
            (2, ytd.get((year, 2)), reported.get((year, 1))),
            (3, ytd.get((year, 3)), ytd.get((year, 2))),
            (4, fiscal.get(year), ytd.get((year, 3))),
        )
        for number, whole_period, prefix_period in candidates:
            if (year, number) in reported or whole_period is None or prefix_period is None:
                continue
            terms = ((whole_period.period_id, 1), (prefix_period.period_id, -1))
            spec = _quarter_spec(whole_period, number, None, terms)
            whole, prefix = _dated(whole_period), _dated(prefix_period)
            comparable = (
                whole is not None
                and prefix is not None
                and whole[0] == prefix[0]
                and prefix[1] < whole[1]
            )
            days = _days(whole_period, prefix_period) if comparable else None
            specs.append(
                replace(
                    spec,
                    column=replace(spec.column, days=days),
                    unbuilt=None if comparable else UNSPANNED,
                )
            )
    return specs
```

```python
def _host_ltm(
    regs: Cp1Registers,
    anchor: PeriodRow,
    fiscal: list[_Spec],
    to_date: tuple[_Spec | None, _Spec | None],
) -> _Spec:
    """Build the LTM as the anchor FY or FY + YTD - PYTD.

    A stated LTM row supplies its identity and comparison figure. Its dates
    must agree with the computed span; its day count never replaces that span.
    """
    unbuilt = None
    if anchor.period_type == "FY":
        own_fy = next(spec for spec in fiscal if spec.own == anchor.period_id)
        terms: tuple[_Term, ...] = ((own_fy, 1),)
        number: int | None = 4
    else:
        terms, unbuilt = _rolled(regs, anchor, fiscal, to_date)
        number = _quarter_number(anchor)
    span = anchor.day_count if anchor.period_type == "FY" else _term_days(terms)
    complete = all(isinstance(ref, _Spec) for ref, _ in terms)
    if span is None and complete:
        # Only complete, dated components can establish a missing day count.
        periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
        dated_days = 0
        for ref, sign in terms:
            if isinstance(ref, _Spec):
                start, end = _start(ref, periods), iso_date(ref.column.end_date)
                if start is None or end is None or start > end.toordinal():
                    break
                dated_days += sign * (end.toordinal() - start + 1)
        else:
            span = dated_days
    invalid_span = (span is None and complete) or (
        span is not None and not LTM_DAYS[0] <= span <= LTM_DAYS[1]
    )
    if invalid_span:
        unbuilt = UNSPANNED  # Deploy VI: a stub year or a mislabelled interim
    stated = next((p for p in _of_type(regs, "LTM") if p.end_date == anchor.end_date), None)
    own = stated.period_id if stated is not None else None
    stated_span = _dated(stated)
    if (
        stated is not None
        and span is not None
        and (stated_span is None or stated_span[1] - stated_span[0] + 1 != span)
    ):
        unbuilt = UNSPANNED
    return _Spec(
        column=Column(
            column_id=f"LTM:{own or anchor.period_id}",
            kind="LTM",
            label=_ltm_label(anchor, number),
            period_id=own,
            fiscal_year=anchor.fiscal_year,
            end_date=anchor.end_date,
            days=span,
            case=None,
        ),
        own=own,
        terms=terms,
        stated=own,
        unbuilt=unbuilt,
    )
```
