# Historical Model readiness review

Base: `955f6e4`. Scope: new `model_readiness.py` and behavioral readiness tests.
No dependencies, source packs, model calls or UI changes. Coordinator owns the
checkout and integration; OpenRouter qualification spending remains US$0.

## Confidence review

Least confident about, ranked:

1. Four labelled quarters could represent a short period. Reproduced with four
   consecutive one-day quarters plus a matching four-day FY: the initial gate
   returned ready. Root cause: counting and continuity did not check full-year
   duration. Added the Model's existing 364–371-day convention to each rolling
   four-quarter window. Reversed fiscal-quarter labels on valid dates also need
   an explicit consecutive-slot check. Regression cases now block both inputs.
2. Derived quarters and fiscal spellings could be rejected or skip source checks.
   Traced historical construction IDs, signed source leaves and fiscal-year
   normalization. Q1/H1/9M/FY source data qualifies four complete quarters without
   direct Q2–Q4 source rows. An FY2024/25 annual mismatch remains mandatory for
   quarters labelled 2025. Verified by behavioral tests.
3. Missing source values and incomplete schedules could become accidental zeroes.
   Traced adapter nulls, stable member coverage and reconciliation statuses.
   Missing carrying values, absent schedules, partial/null/missing segments,
   incomplete add-back disclosure, tax gaps and cash mismatches block. Genuine
   non-disclosure and missing forecast terms warn within historical scope.
4. The COGS requirement could contradict evidenced by-nature statements. Traced
   the pinned prose and old validator; exempt only when every contributing source
   leaf is by-nature. A complete by-nature case passes without invented COGS.
   Source classification validation still rejects contradictory known COGS.
5. Source failures could cancel when constructing quarters. Traced mandatory
   source statement identities and numeric source comparisons alongside the six
   derived check types. Removing a required CFO identity blocks; the existing
   period suite exercises opposing source errors and independent comparisons.
6. Selection or editing the report could overstate authorization. Duplicate,
   unknown, empty and short selections block; explicit reverse selection resolves
   chronologically. Hash validation reconstructs both nested reports and the row.
   Tampered mandatory IDs, book identity and review identity fail closed.
7. Scope exclusions could be mistaken for complete readiness. By design, the
   contract is selected historical quarters only, with one CP-MODEL row; all
   unresolved book observation conflicts block conservatively. Forecasts, pro
   forma, consumer-specific conflict materiality, source-backed audit/FX
   exceptions, full CP-1 acceptance and rendering remain open and documented.

Fixed: false readiness for short annual windows and nonconsecutive fiscal slots.
Verified: direct/derived coverage, null/conflict preservation, source failures,
segment disclosure distinctions, tax alternatives, scope and recomputation.
By design: conservative book-wide conflict blocking and no debt-free inference.
Still open: documented integration and analytical qualification; DCF definition
awaits the user's answer, with no default adopted.

## Scoped post-edit rewrite tournament

Only `_evaluate` receives a tournament: it is the key financial readiness decision.
Routine report assembly and validation wrappers are skipped under the user's
key-area correction. Fresh roles use GPT-6.1 Sol/high from the model matrix;
coordinator and host settings remain unchanged.

GitNexus context returned repository-not-indexed. `rg` traced `_evaluate` to
`assess_model_readiness`, transitively `validate_model_readiness` and the readiness
tests. There is no CLI/UI consumer yet. Strict typing checks the public callers.

Winner: **Snippet A**, replacing `model_readiness.py:94-342` (`_evaluate`).
Bracket: A over B, A over C, A over D (incumbent).

- Indexing check types in one traversal removes a scan for every selected quarter.
- Caching the two possible ordered input-key sequences avoids repeated string
  creation and sorting while preserving diagnostic order.
- Reusing parsed fiscal years keeps the existing financial policy branches and
  public contract intact. This is an asymptotic improvement, not a measured
  end-to-end performance claim.

The coordinator backed up the full module, inspected the candidate diff and
applied A. All three challengers exactly matched the incumbent on 229 deterministic
selection/value/status cases, including serialized diagnostics and check order.
The chosen function passed `uv run --locked pytest tests/product/test_model_readiness.py
tests/product/test_period_reconciliation.py -q` (47 passed) and
`uv run --locked mypy src` (30 source files). Ruff passed. Concrete invariant:
four one-day quarters block despite matching FY arithmetic; the valid Q1/H1/9M/FY
case qualifies three derived quarters. Public-boundary testing also confirms an
uncited tax amount is refused. No additional confirmed issue remained after the
candidate diff review.

Final code for the reviewed symbol:


```python
def _evaluate(
    book: FinancialBook,
    periods: PeriodReconciliationReport,
    source: ReconciliationReport,
    requested: tuple[str, ...] | None,
) -> ModelReadinessRow:
    historical = periods.historical
    available = {n.construction_id: n for n in historical.constructions if n.kind == "QUARTER"}
    selected = tuple(available) if requested is None else requested
    findings: list[ReadinessFinding] = []
    missing: set[str] = set()

    def issue(
        code: str,
        text: str,
        node: str | None = None,
        refs: tuple[str, ...] = (),
        *,
        warning: bool = False,
    ) -> None:
        findings.append(
            ReadinessFinding(
                code=code,
                severity="WARN" if warning else "BLOCK",
                construction_id=node,
                references=refs,
                explanation=text,
            )
        )

    if len(selected) != len(set(selected)) or any(key not in available for key in selected):
        issue(
            "quarter_selection", "Selection contains duplicate or unknown quarter construction IDs"
        )
    quarters = sorted(
        (available[key] for key in dict.fromkeys(selected) if key in available),
        key=lambda n: (n.end_date or date.min, n.construction_id),
    )
    if len(quarters) < 4:
        issue("quarter_count", "At least four discrete complete quarters are required")
    quarter_years: list[int | None] = []
    for index, quarter in enumerate(quarters):
        previous_end = quarters[index - 1].end_date if index else None
        if (
            quarter.start_date is None
            or quarter.end_date is None
            or quarter.days is None
            or quarter.limitation
        ):
            issue(
                "quarter_span",
                "Quarter span is unavailable or not comparable",
                quarter.construction_id,
            )
        if index and (
            previous_end is None
            or quarter.start_date is None
            or previous_end.toordinal() + 1 != quarter.start_date.toordinal()
        ):
            issue(
                "quarter_continuity",
                "Selected quarters must be contiguous and non-overlapping",
                quarter.construction_id,
            )
        year = fiscal_year_number(quarter.fiscal_year)
        previous = quarters[index - 1] if index else None
        previous_year = quarter_years[index - 1] if index else None
        quarter_years.append(year)
        if (
            year is None
            or quarter.fiscal_quarter is None
            or (
                previous is not None
                and (
                    previous_year is None
                    or previous.fiscal_quarter is None
                    or 4 * year + quarter.fiscal_quarter
                    != 4 * previous_year + previous.fiscal_quarter + 1
                )
            )
        ):
            issue(
                "fiscal_sequence",
                "Selected fiscal quarter slots are not consecutive",
                quarter.construction_id,
            )
        if index >= 3:
            start = quarters[index - 3].start_date
            end = quarter.end_date
            if (
                start is None
                or end is None
                or not LTM_DAYS[0] <= (end - start).days + 1 <= LTM_DAYS[1]
            ):
                issue(
                    "annual_span",
                    "Each four-quarter window must span 364-371 days",
                    quarter.construction_id,
                )
    rows = {(v.construction_id, v.series_key): v for v in historical.values}
    by_period = {p.period_id: p for p in book.periods}
    used_periods: set[str] = set()
    required_by_year: dict[int | None, set[str]] = {}
    facilities = tuple(dict.fromkeys(r.facility_id for r in book.facilities))
    segments = tuple(dict.fromkeys(r.segment_id for r in book.segments))
    addbacks = tuple(dict.fromkeys(r.addback_id for r in book.addbacks))
    if not facilities:
        issue("facility_schedule", "A complete carrying-value facility schedule is required")
    input_keys: dict[bool, tuple[str, ...]] = {}
    schedule_keys = (
        *("fac:" + fid for fid in facilities),
        *("bu:" + sid for sid in segments),
        *("addback:" + aid for aid in addbacks),
    )
    for quarter, year in zip(quarters, quarter_years, strict=True):
        cid = quarter.construction_id
        leaves = _source_periods(historical, quarter)
        used_periods.update(pid for pid, _ in leaves if pid is not None)
        nature = bool(leaves) and all(
            pid is not None and by_period[pid].expense_presentation == "by_nature"
            for pid, _ in leaves
        )
        flow_metrics = REQUIRED_FLOWS - ({"cogs"} if nature else set())
        required_by_year.setdefault(year, set()).update(flow_metrics)
        if nature not in input_keys:
            input_keys[nature] = (
                *("acct:" + metric for metric in sorted(flow_metrics | BALANCE_METRICS)),
                *schedule_keys,
            )
        keys = input_keys[nature]
        for key in keys:
            row = rows.get((cid, key))
            if row is None or row.value.amount is None:
                missing.add(key)
                issue("missing_input", "Required historical input is unknown", cid, (key,))
            elif not row.value.citations:
                issue(
                    "source_locator",
                    "Required historical input has no located evidence",
                    cid,
                    (key,),
                )
        tax = rows.get((cid, "acct:effective_tax_rate"))
        components = [
            rows.get((cid, "acct:" + key)) for key in ("pretax_income", "income_tax_expense")
        ]
        if (tax is None or tax.value.amount is None) and any(
            v is None or v.value.amount is None for v in components
        ):
            missing.add("effective_tax_rate_or_pretax_and_tax")
            issue(
                "tax_inputs",
                "Tax rate requires a source rate or both pretax income and tax expense",
                cid,
            )
    # Every selected quarter must carry the six mandatory comparisons, including
    # a WARN/null segment comparison for genuine non-disclosure.
    mandatory = []
    selected_ids = {q.construction_id for q in quarters}
    selected_years = set(quarter_years)
    nodes = {n.construction_id: n for n in historical.constructions}
    check_kinds: dict[str, set[str]] = {}
    for check in periods.checks:
        check_kinds.setdefault(check.construction_id, set()).add(check.check_type)
        selected_check = (
            check.construction_id in selected_ids and check.check_type in _MANDATORY_CHECKS
        )
        year_check = (
            check.check_type in {"FY_QUARTERS", "REPORTED_DERIVED_PERIOD"}
            and fiscal_year_number(nodes[check.construction_id].fiscal_year) in selected_years
            and (
                (
                    check.check_type == "FY_QUARTERS"
                    and check.metric_id
                    in required_by_year.get(
                        fiscal_year_number(nodes[check.construction_id].fiscal_year), set()
                    )
                )
                or check.reported.amount is not None
            )
        )
        if selected_check or year_check:
            mandatory.append(check.check_id)
            if check.status != "PASS":
                issue(
                    "reconciliation",
                    check.explanation,
                    check.construction_id,
                    (check.check_id,),
                    warning=check.status == "WARN",
                )
    for quarter in quarters:
        cid = quarter.construction_id
        kinds = check_kinds.get(cid, set())
        if not _MANDATORY_CHECKS <= kinds:
            issue("missing_checks", "Mandatory reconciliation types are absent", cid)
    # A source error must not disappear through period subtraction. Derived FY
    # checks replace the direct-only quarterly comparison, which lacks computed Q4.
    for source_check in source.checks:
        if (
            source_check.period_id in used_periods
            and source_check.check_type != "FY_QUARTERS"
            and (
                source_check.check_type == "SOURCE_STATEMENT_IDENTITY"
                or source_check.difference is not None
            )
        ):
            mandatory.append(source_check.check_id)
            if source_check.status != "PASS":
                issue(
                    "source_reconciliation",
                    source_check.explanation,
                    refs=(source_check.check_id,),
                    warning=source_check.status == "WARN",
                )
    conflicts = tuple(
        o.observation_id for o in records(book, Observation) if o.status == "conflicting"
    )
    if conflicts:
        issue(
            "source_conflicts",
            "Unresolved source conflicts require explicit resolution",
            refs=conflicts,
        )
    for facility in book.facilities:
        if facility.period_id in used_periods and (
            facility.rate_type == "NOT_STATED"
            or facility.annual_amortisation.amount is None
            or facility.maturity_date is None
        ):
            issue(
                "facility_terms",
                "Historical carrying value does not establish forecast rate, "
                "amortisation or maturity terms",
                refs=(facility.facility_id, facility.period_id),
                warning=True,
            )
    ready = not any(f.severity == "BLOCK" for f in findings)
    return ModelReadinessRow(
        status="ready" if ready else "blocked",
        selected_quarters=tuple(q.construction_id for q in quarters),
        missing_metric_ids=tuple(sorted(missing)),
        conflict_refs=conflicts,
        mandatory_check_ids=tuple(dict.fromkeys(mandatory)),
        findings=tuple(findings),
        explanation="Selected historical quarters satisfy deterministic Model input requirements"
        if ready
        else "Selected historical quarters do not satisfy Model input requirements",
    )
```

## Final validation

- `make product-check`: passed; 504 product tests, 97.33% combined coverage,
  strict mypy on 30 source files, lint/format and JS syntax. Existing browser
  regressions passed; this internal gate introduces no new accepted Module view.
- `make check`: passed, including staged diff whitespace checks.
- `make secrets`: passed for working files, staged changes and reachable history.
- Full staged candidate diff inspected by the coordinator. No dependency changes;
  dependency audit not rerun. No live test call; spending remains US$0.
- Design hook: no CSS fix or new suppression. Existing narrow `side-tab`
  exception in `.impeccable/config.json` still matches the active navigation
  indicator in Direction C; intentional styling is retained. No unresolved
  design finding was introduced by this change.
