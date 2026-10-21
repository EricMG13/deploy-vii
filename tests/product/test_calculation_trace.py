"""Independent arithmetic and provenance checks for the actual statement graph."""

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from deploy_vii.calculation_trace import trace_cells
from deploy_vii.financial_contracts import AccountObservation
from deploy_vii.financial_model import model_report, validate_model_report
from deploy_vii.model._cells import CONTEXT, calc
from deploy_vii.model.frame import Arithmetic, Cell, SourceRef
from tests.product.test_financial_model import metric, model_case
from tests.product.test_financial_periods import frozen
from tests.product.test_financials import observed


def test_every_statement_root_resolves_and_arithmetic_reproduces_exact_results() -> None:
    value = model_case()
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    nodes = {n.computation_id: n for n in report.computations}
    assert len(nodes) == len(report.computations)
    assert report.schema_version == "financial-model/2"
    for row in report.values:
        assert nodes[row.computation_id].value == row.value
    with localcontext(CONTEXT):
        for node in report.computations:
            parts = [nodes[p.computation_id].value.amount for p in node.operands]
            if node.operation == "sum":
                expected = (
                    None
                    if None in parts
                    else sum(
                        (v * p.coefficient for v, p in zip(parts, node.operands, strict=True)),
                        Decimal(0),
                    )
                )
                assert node.value.amount == expected
            elif node.operation == "ratio_times":
                assert len(parts) == 3
                expected = (
                    None if None in parts or parts[1] <= 0 else parts[0] / parts[1] * parts[2]
                )
                assert node.value.amount == expected
    assert validate_model_report(pack, review, report) == ()


def test_shared_subexpressions_are_content_addressed_without_repeated_trees() -> None:
    value = model_case()
    _pack, review = frozen(value)
    obs = review.books[0].accounts[0].value
    leaf = Cell(
        obs.amount,
        basis="REPORTED",
        sources=(SourceRef(obs.observation_id, "financial-observation", str(obs.amount)),),
    )
    shared = calc(((leaf, 1), (leaf, 1)))
    parent = calc(((shared, 1), (shared, -1)))
    nodes, roots = trace_cells(
        {"a": parent, "b": replace(parent), "shared": shared}, review.books[0]
    )
    assert len(nodes) == 3
    assert list(roots) == ["a", "b", "shared"]
    positions = {n.computation_id: i for i, n in enumerate(nodes)}
    assert all(
        positions[o.computation_id] < positions[n.computation_id] for n in nodes for o in n.operands
    )
    assert roots["a"] == roots["b"]
    node = next(n for n in nodes if n.computation_id == roots["a"])
    assert node.operands[0].computation_id == node.operands[1].computation_id == roots["shared"]
    assert node.value.amount == 0


def test_missing_source_is_retained_inside_failed_statement_sum() -> None:
    value = model_case()
    missing = observed("Q1.cogs", None)
    value = value.model_copy(
        update={
            "accounts": tuple(
                r.model_copy(update={"value": missing})
                if r.period_id == "Q1" and r.metric_id == "cogs"
                else r
                for r in value.accounts
            )
        }
    )
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    nodes = {n.computation_id: n for n in report.computations}
    ebitda = next(
        v
        for v in report.values
        if v.key == "ebitda"
        and v.basis_id == metric(report, "Q:Q1", "metric:ebitda_margin").display_basis_id
    )
    assert ebitda.value.amount is None
    reached = set()
    pending = [ebitda.computation_id]
    while pending:
        key = pending.pop()
        if key in reached:
            continue
        reached.add(key)
        pending.extend(o.computation_id for o in nodes[key].operands)
    sources = [
        n
        for key, n in nodes.items()
        if key in reached and missing.observation_id in n.value.observation_ids
    ]
    assert sources and all(n.value.amount is None for n in sources)
    assert any(n.operation == "input" and n.value.citations for n in sources)


def test_net_income_source_mapping_margin_and_derived_periods() -> None:
    from tests.product.test_statements import line

    value = model_case()
    lines = tuple(
        line(
            "income",
            "net_income",
            "40" if p.period_type == "FY" else "10",
            1,
            statement="IS",
            pid=p.period_id,
        )
        for p in value.periods
        if p.period_type != "PERIOD_END"
    )
    value = value.model_copy(update={"statement_lines": lines})
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    assert metric(report, "Q:Q4", "metric:net_income_margin").value.amount == Decimal("0.1")
    assert metric(report, "LTM:FY", "metric:net_income_margin").value.amount == Decimal("0.1")
    assert metric(report, "Q:Q1", "metric:ebit_margin").value.amount == Decimal("0.5")
    assert any("income.Q4" in oid for v in report.values for oid in v.value.observation_ids)


def test_net_income_is_never_plugged_from_pretax_minus_tax() -> None:
    value = model_case()
    rows = tuple(
        AccountObservation(metric_id=key, period_id="Q1", value=observed(key + ".extra", amount))
        for key, amount in (("pretax_income", "20"), ("income_tax_expense", "-5"))
    )
    pack, review = frozen(value.model_copy(update={"accounts": (*value.accounts, *rows)}))
    report = model_report(pack, review, value.book_id)
    row = metric(report, "Q:Q1", "metric:net_income_margin")
    assert row.numerator.amount is None and row.value.amount is None


def test_corrupt_computation_or_unknown_source_is_rejected() -> None:
    value = model_case()
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    # Select an actual arithmetic node so removing its inputs is material.
    node = next(n for n in report.computations if n.operands)
    forged = tuple(
        n.model_copy(update={"operands": ()}) if n == node else n for n in report.computations
    )
    assert validate_model_report(pack, review, report.model_copy(update={"computations": forged}))
    with pytest.raises(KeyError):
        trace_cells(
            {
                "bad": Cell(
                    Decimal(1), sources=(SourceRef("unknown", "financial-observation", "1"),)
                )
            },
            value,
        )


def test_cycle_fails_and_deep_shared_graph_grows_linearly() -> None:
    value = model_case()
    cell = Cell(Decimal(1), basis="CALCULATED")
    for _ in range(100):
        cell = calc(((cell, 1), (cell, -1)))
    nodes, _ = trace_cells({"root": cell}, value)
    assert len(nodes) == 101
    cycle = Cell(None, "COMPONENT_MISSING")
    object.__setattr__(cycle, "arithmetic", Arithmetic("sum", ((cycle, 1),)))
    with pytest.raises(ValueError, match="Cyclic"):
        trace_cells({"root": cycle}, value)


def test_working_capital_ratios_record_three_operands_and_positive_denominator_rule() -> None:
    value = model_case()
    rows = tuple(
        AccountObservation(
            metric_id=key, period_id=p.period_id, value=observed(f"{key}.{p.period_id}", amount)
        )
        for p in value.periods
        for key, amount in (
            ("net_accounts_receivable", "10"),
            ("inventory", "15"),
            ("accounts_payable", "20"),
        )
    )
    value = value.model_copy(update={"accounts": (*value.accounts, *rows)})
    pack, review = frozen(value)
    report = model_report(pack, review, value.book_id)
    basis = metric(report, "Q:Q1", "metric:ebitda_margin").display_basis_id
    nodes = {n.computation_id: n for n in report.computations}
    dso = next(v for v in report.values if v.basis_id == basis and v.key == "dso")
    computation = nodes[dso.computation_id]
    assert dso.value.amount == 9
    assert computation.operation == "ratio_times"
    assert [nodes[p.computation_id].value.amount for p in computation.operands] == [10, 100, 90]
    zero = value.model_copy(
        update={
            "accounts": tuple(
                r.model_copy(update={"value": observed(r.value.observation_id, "0")})
                if r.metric_id == "cogs" and r.period_id == "Q1"
                else r
                for r in value.accounts
            )
        }
    )
    pack, review = frozen(zero)
    report = model_report(pack, review, value.book_id)
    dio = next(v for v in report.values if v.basis_id == basis and v.key == "dio")
    node = next(n for n in report.computations if n.computation_id == dio.computation_id)
    assert dio.value.amount is None and dio.value.reason == "ZERO_OR_NEGATIVE_DENOMINATOR"
    assert node.operation == "ratio_times" and len(node.operands) == 3


def test_reported_ebitda_growth_and_pf_margin_exclusions_are_explicit() -> None:
    from deploy_vii.model.frame import Column
    from deploy_vii.model.metrics import metric_frame

    prior = Column("FY:prior", "FY", "Prior", "prior", "2024", "2024-12-31", 366, None)
    current = replace(prior, column_id="FY:now", fiscal_year="2025", end_date="2025-12-31")
    frames = {"FY:prior": {"ebitda": Cell(Decimal(80))}, "FY:now": {"ebitda": Cell(Decimal(100))}}
    result = metric_frame((prior, current), frames, {})
    assert result["FY:now"]["ebitda_growth"].value == Decimal("0.25")
    pf = replace(current, column_id="PF:now", kind="PF_LTM")
    result = metric_frame(
        (pf,),
        {
            pf.column_id: {
                "ebit": Cell(Decimal(50)),
                "net_income": Cell(Decimal(20)),
                "revenue": Cell(Decimal(100), basis="PRO_FORMA"),
            }
        },
        {},
    )
    assert result[pf.column_id]["metric:ebit_margin"].reason == "NOT_APPLICABLE"
    assert result[pf.column_id]["metric:net_income_margin"].reason == "NOT_APPLICABLE"
