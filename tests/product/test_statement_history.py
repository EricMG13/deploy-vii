"""Full statement-line constructions, including issuer detail and explicit gaps."""

from datetime import date
from decimal import localcontext

import pytest

from deploy_vii.financial_contracts import FinancialBook
from deploy_vii.financial_periods import historical_report
from deploy_vii.statement_history import (
    StatementHistoricalValue,
    StatementHistoryReport,
    statement_history,
    validate_statement_history,
)
from tests.product.test_financial_periods import frozen, periods_case, rolled_case
from tests.product.test_financials import conflict, period
from tests.product.test_statements import line


def history_book(*, rolled: bool = False) -> FinancialBook:
    book = rolled_case() if rolled else periods_case()
    amounts = (
        (("PYTD", "20"), ("FY24", "100"), ("CYTD", "30"), ("LTM", "999"))
        if rolled
        else (("Q1", "10"), ("H1", "30"), ("9M", "60"), ("FY", "100"))
    )
    rows = []
    for pid, amount in amounts:
        for item, statement, priority in (
            ("revenue", "IS", 1),
            ("other:issuer-detail", "IS", 2),
            ("cfo_ncfo", "CFS", 1),
            ("cash_and_equivalents", "BS", 1),
        ):
            # Same-day balance observations must agree despite conflicting stated LTM flow.
            cash = "30" if rolled and pid == "LTM" and statement == "BS" else amount
            rows.append(line(item, item, cash, priority, statement=statement, pid=pid))
    return book.model_copy(update={"accounts": (), "statement_lines": tuple(rows)})


def result(
    report: StatementHistoryReport, key: str, table: str = "T4.4", item: str = "revenue"
) -> StatementHistoricalValue:
    node = next(n for n in report.constructions if n.column_key == key)
    return next(
        v
        for v in report.values
        if (v.construction_id, v.table_id, v.item_id) == (node.construction_id, table, item)
    )


def test_all_statement_lines_have_exact_derived_quarters_and_closing_balances() -> None:
    book = history_book()
    pack, review = frozen(book)
    report = statement_history(pack, review, book.book_id)
    assert [result(report, key).value.amount for key in ("Q:H1-Q1", "Q:9M-H1", "Q:FY-9M")] == [
        20,
        30,
        40,
    ]
    assert result(report, "Q:H1-Q1", item="other:issuer-detail").value.amount == 20
    assert result(report, "Q:H1-Q1", "T4.5", "cfo_ncfo").value.amount == 20
    balance = result(report, "Q:H1-Q1", "T4.6", "cash_and_equivalents")
    assert balance.value.amount == 30 and balance.operands == ()
    assert balance.value.value_class == "source"
    q2 = result(report, "Q:H1-Q1")
    assert [o.reference.coefficient for o in q2.operands] == [1, -1]
    assert q2.value.value_class == "calculated" and q2.value.citations
    assert validate_statement_history(pack, review, report) == ()
    assert validate_statement_history(pack, review, report.model_copy(update={"values": ()}))
    assert validate_statement_history(
        pack,
        review,
        report.model_copy(
            update={"source": report.source.model_copy(update={"book_id": "unknown"})}
        ),
    )
    with localcontext() as context:
        context.prec = 2
        assert statement_history(pack, review, book.book_id) == report


def test_model_addback_gate_does_not_block_statement_construction() -> None:
    book = history_book()
    book = book.model_copy(
        update={
            "addback_disclosure": book.addback_disclosure.model_copy(update={"status": "partial"})
        }
    )
    pack, review = frozen(book)
    with pytest.raises(ValueError, match="add-back"):
        historical_report(pack, review, book.book_id)
    assert result(statement_history(pack, review, book.book_id), "Q:H1-Q1").value.amount == 20


def test_ltm_comparison_is_independent_and_missing_component_is_never_plugged() -> None:
    book = history_book(rolled=True)
    pack, review = frozen(book)
    report = statement_history(pack, review, book.book_id)
    value = result(report, "LTM:LTM")
    assert value.value.amount == 110 and value.value.stated_amount == 999
    assert value.stated_computation_id
    assert "differs" in value.value.note
    missing = tuple(
        row.model_copy(
            update={
                "value": row.value.model_copy(
                    update={
                        "amount": None,
                        "status": "not_applicable",
                        "reason": "Source marks this inapplicable",
                    }
                )
            }
        )
        if row.period_id == "PYTD" and row.item_id == "revenue"
        else row
        for row in book.statement_lines
    )
    pack, review = frozen(book.model_copy(update={"statement_lines": missing}))
    report = statement_history(pack, review, book.book_id)
    value = result(report, "LTM:LTM")
    assert value.value.amount is None and value.value.stated_amount == 999
    assert value.value.calculation_status == "Not Calculable"
    assert value.value.observation_ids and value.value.citations
    assert any(n.value.reason == "NOT_APPLICABLE" for n in report.computations)


def test_conflicting_flow_and_same_date_balance_cannot_become_known() -> None:
    book = history_book(rolled=True)
    book = book.model_copy(
        update={
            "statement_lines": tuple(
                row.model_copy(update={"value": conflict(row.value.observation_id)})
                if row.period_id == "CYTD" and row.item_id in {"revenue", "cash_and_equivalents"}
                else row
                for row in book.statement_lines
            )
        }
    )
    pack, review = frozen(book)
    report = statement_history(pack, review, book.book_id)
    for table, item in (("T4.4", "revenue"), ("T4.6", "cash_and_equivalents")):
        value = result(report, "LTM:LTM", table, item)
        assert value.value.amount is None and value.value.calculation_status == "Conflicted"
        assert value.value.citations and value.value.observation_ids


def test_mismatched_stubs_keep_inputs_but_block_flow_arithmetic() -> None:
    book = history_book()
    book = book.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"start_date": date(2025, 2, 1)}) if p.period_id == "H1" else p
                for p in book.periods
            )
        }
    )
    pack, review = frozen(book)
    value = result(statement_history(pack, review, book.book_id), "Q:H1-Q1")
    assert value.value.amount is None and len(value.operands) == 2
    assert value.value.observation_ids and value.value.citations
    assert "span" in value.value.note


def nested_book() -> FinancialBook:
    book = history_book()
    quarters = tuple(
        period(f"Q{i}", start, end, i)
        for i, start, end in (
            (1, "2025-01-01", "2025-03-31"),
            (2, "2025-04-01", "2025-06-30"),
            (3, "2025-07-01", "2025-09-30"),
            (4, "2025-10-01", "2025-12-31"),
        )
    )
    h1 = book.periods[1].model_copy(update={"component_period_ids": ("Q1", "Q2")})
    fy = book.periods[-1].model_copy(update={"component_period_ids": ("H1", "Q3", "Q4")})
    rows = tuple(
        line("revenue", "revenue", amount, 1, statement="IS", pid=pid)
        for pid, amount in (
            ("Q1", None),
            ("Q2", "20"),
            ("Q3", "30"),
            ("Q4", "40"),
            ("H1", "999"),
            ("FY", "888"),
        )
    )
    return book.model_copy(update={"periods": (*quarters, h1, fy), "statement_lines": rows})


def test_nested_missing_component_cannot_be_hidden_by_reported_subtotal() -> None:
    book = nested_book()
    pack, review = frozen(book)
    report = statement_history(pack, review, book.book_id)
    fy = result(report, "FY:FY")
    assert fy.value.amount is None
    assert fy.value.stated_amount == 888
    assert any(n.value.reason == "NOT_STATED" for n in report.computations)


def test_nested_known_components_retain_leaf_graph_and_reported_comparisons() -> None:
    from tests.product.test_financials import observed

    book = nested_book()
    book = book.model_copy(
        update={
            "statement_lines": tuple(
                row.model_copy(update={"value": observed(row.value.observation_id, "10")})
                if row.period_id == "Q1"
                else row
                for row in book.statement_lines
            )
        }
    )
    pack, review = frozen(book)
    report = statement_history(pack, review, book.book_id)
    fy = result(report, "FY:FY")
    assert fy.value.amount == 100 and fy.value.stated_amount == 888
    assert result(report, "YTD:H1").value.amount == 30
    assert result(report, "YTD:H1").value.stated_amount == 999
    nodes = {n.computation_id: n for n in report.computations}

    def leaves(identity: str) -> list[str]:
        node = nodes[identity]
        if not node.operands:
            return list(node.value.observation_ids)
        return [source for operand in node.operands for source in leaves(operand.computation_id)]

    assert set(leaves(fy.computation_id)) == {f"revenue.Q{i}" for i in range(1, 5)}
    assert set(fy.value.observation_ids) == {f"revenue.Q{i}" for i in range(1, 5)}


def test_reported_q4_suppresses_subtraction_and_outflows_normalize_before_arithmetic() -> None:
    book = history_book()
    q4 = period("Q4", "2025-10-01", "2025-12-31", 4)
    expense = tuple(
        line("expense", "cogs", amount, 3, statement="IS", pid=pid).model_copy(
            update={
                "sign_convention": "outflow_magnitude",
                "sign_citations": book.statement_lines[0].value.citations,
            }
        )
        for pid, amount in (("Q1", "10"), ("H1", "30"), ("9M", "60"), ("FY", "100"))
    )
    book = book.model_copy(
        update={
            "periods": (*book.periods, q4),
            "statement_lines": (
                *book.statement_lines,
                *expense,
                line("revenue", "revenue", "41", 1, statement="IS", pid="Q4"),
            ),
        }
    )
    pack, review = frozen(book)
    report = statement_history(pack, review, book.book_id)
    assert "Q:FY-9M" not in {n.column_key for n in report.constructions}
    assert result(report, "Q:H1-Q1", item="cogs").value.amount == -20
    assert any(c.period_id == "Q4" and c.normalized_amount == 41 for c in report.source.cells)
    assert any(n.value.value_class == "normalized" for n in report.computations)


def test_history_rejects_stale_review_and_precision_only_tampering() -> None:
    from decimal import Decimal

    book = history_book()
    pack, review = frozen(book)
    with pytest.raises(ValueError, match="bind"):
        statement_history(pack, review.model_copy(update={"pack_sha256": "0" * 64}), book.book_id)
    report = statement_history(pack, review, book.book_id)
    q2 = result(report, "Q:H1-Q1")
    changed = q2.model_copy(
        update={"value": q2.value.model_copy(update={"amount": Decimal("20.0")})}
    )
    forged = report.model_copy(
        update={"values": tuple(changed if v.value_id == q2.value_id else v for v in report.values)}
    )
    assert forged == report  # Decimal equality alone does not protect serialized precision.
    assert validate_statement_history(pack, review, forged)


def test_direct_kernel_component_cycle_and_depth_are_bounded() -> None:
    from dataclasses import replace
    from decimal import Decimal

    from deploy_vii.model import history
    from deploy_vii.model.frame import Cell
    from deploy_vii.model.registers import Cp1Registers, PeriodRow

    def evaluate(depth: int, *, cycle: bool = False) -> Cell:
        periods = [
            PeriodRow(
                period_id=f"p{i}",
                fiscal_year="2025",
                fiscal_quarter=None,
                period_type="FY",
                start_date="2025-01-01",
                end_date="2025-12-31",
                day_count=365,
                currency="USD",
                unit="MILLIONS",
                component_period_ids=(f"p{i + 1}",) if i + 1 < depth else (),
            )
            for i in range(depth)
        ]
        if cycle:
            periods[-1] = replace(periods[-1], component_period_ids=("p0",))
        register = history._register(
            Cp1Registers(tuple(periods), (), (), (), (), (), (), "USD", "MILLIONS")
        )
        series = history._Series("flow", {p.period_id: Cell(Decimal(7)) for p in periods})
        value = history._component(series, register, "p0")
        assert not series.resolved and not series.started
        return value

    assert evaluate(4).value == 7
    assert evaluate(5).value is None
    assert evaluate(2, cycle=True).value is None
