"""Constructed-period checks must use independent source inputs, never Model plugs."""

from decimal import Decimal, localcontext

import pytest

from deploy_vii.financial_contracts import FinancialBook, StatementDisclosure
from deploy_vii.period_reconciliation import (
    PeriodCheck,
    PeriodReconciliationReport,
    reconcile_periods,
    validate_period_reconciliation,
)
from tests.product.test_financial_periods import frozen, periods_case
from tests.product.test_financials import observed
from tests.product.test_reconciliation import accounts
from tests.product.test_statements import identity, line


def constructed_case() -> FinancialBook:
    value = periods_case()
    value = value.model_copy(update={"accounts": ()})
    for pid, scale in (("Q1", 1), ("H1", 2), ("9M", 3), ("FY", 4)):
        value = accounts(
            value,
            pid,
            **{
                name: str(Decimal(amount) * scale)
                for name, amount in {
                    "revenue": "100.00",
                    "cogs": "-30.00",
                    "opex_including_da": "-20.00",
                    "depreciation_amortization": "-10.00",
                    "ebitda": "60.00",
                    "adjusted_ebitda": "60.00",
                    "cfo_ncfo": "55.00",
                }.items()
            },
        )
    lines = tuple(
        row
        for pid, scale in (("Q1", 1), ("H1", 2), ("9M", 3), ("FY", 4))
        for row in (
            line("cfo", "cfo_ncfo", str(55 * scale), 1, pid=pid, kind="total"),
            line("profit", "net_income", str(40 * scale), 2, pid=pid),
            line("noncash", "other:noncash", str(15 * scale), 3, pid=pid),
        )
    )
    return value.model_copy(
        update={
            "statement_lines": lines,
            "statement_identities": tuple(
                identity("cfo", ("profit", 1), ("noncash", 1), pid=p.period_id)
                for p in value.periods
            ),
            "statement_disclosures": tuple(
                StatementDisclosure(
                    statement="CFS", period_id=p.period_id, disclosure=value.addback_disclosure
                )
                for p in value.periods
            ),
        }
    )


def run(value: FinancialBook) -> PeriodReconciliationReport:
    pack, review = frozen(value)
    return reconcile_periods(pack, review, value.book_id)


def check(
    report: PeriodReconciliationReport, column: str, kind: str, metric: str | None = None
) -> PeriodCheck:
    node = next(n for n in report.historical.constructions if n.column_key == column)
    return next(
        c
        for c in report.checks
        if c.construction_id == node.construction_id
        and c.check_type == kind
        and (metric is None or c.metric_id == metric)
    )


def test_derived_quarter_and_ltm_income_bridges_are_independent_and_resolvable() -> None:
    report = run(constructed_case())
    values = {v.value_id: v for v in report.historical.values}
    for column, amount in (("Q:H1-Q1", 60), ("Q:FY-9M", 60), ("LTM:FY", 240)):
        row = check(report, column, "EBITDA_BRIDGE")
        assert row.status == "PASS" and row.independent
        assert row.reported.amount == row.calculated_value == amount
        assert row.difference == 0 and row.tolerance == Decimal("0.005")
        assert all(p.value_id in values for p in row.components)
        assert all(p.citations for p in row.components)
    assert len({c.check_id for c in report.checks}) == len(report.checks)


def test_source_cfo_equations_are_subtracted_without_residuals() -> None:
    row = check(run(constructed_case()), "Q:H1-Q1", "CFO_IDENTITY")
    assert row.status == "PASS" and row.independent
    assert row.reported.amount == row.calculated_value == 55
    assert [p.amount for p in row.components] == [80, 30, 40, 15]
    assert [p.coefficient for p in row.components] == [1, 1, -1, -1]
    assert [p.observation_ids for p in row.components] == [
        ("profit.H1",),
        ("noncash.H1",),
        ("profit.Q1",),
        ("noncash.Q1",),
    ]
    assert row.context_citations and "residual" not in row.formula


def test_fy_minus_nine_months_cannot_independently_verify_the_same_fy() -> None:
    row = check(run(constructed_case()), "FY:FY", "FY_QUARTERS", "revenue")
    assert row.reported.amount == row.calculated_value == 400
    assert row.status == "WARN" and not row.independent
    assert row.shared_observation_ids == ("FY.revenue",)
    assert "construction" in row.explanation


@pytest.mark.parametrize("mode", ["missing", "wrong", "undisclosed"])
def test_source_cfo_defects_cannot_be_hidden_by_period_subtraction(mode: str) -> None:
    value = constructed_case()
    if mode == "undisclosed":
        value = value.model_copy(
            update={
                "statement_disclosures": tuple(
                    r for r in value.statement_disclosures if r.period_id != "H1"
                )
            }
        )
    else:
        value = value.model_copy(
            update={
                "statement_lines": tuple(
                    r.model_copy(
                        update={
                            "value": observed("noncash.H1", None if mode == "missing" else "31")
                        }
                    )
                    if r.line_id == "noncash" and r.period_id == "H1"
                    else r
                    for r in value.statement_lines
                )
            }
        )
    row = check(run(value), "Q:H1-Q1", "CFO_IDENTITY")
    assert row.status == "BLOCK" and row.calculated_value is None
    assert row.difference is None and not row.independent
    assert "H1" in row.explanation


def test_unknown_ltm_component_is_not_silently_omitted() -> None:
    value = constructed_case()
    value = value.model_copy(
        update={
            "periods": value.periods[:2],
            "accounts": tuple(r for r in value.accounts if r.period_id in {"Q1", "H1"}),
            "statement_lines": tuple(
                r for r in value.statement_lines if r.period_id in {"Q1", "H1"}
            ),
            "statement_identities": tuple(
                r for r in value.statement_identities if r.period_id in {"Q1", "H1"}
            ),
            "statement_disclosures": tuple(
                r for r in value.statement_disclosures if r.period_id in {"Q1", "H1"}
            ),
        }
    )
    row = check(run(value), "LTM:H1", "CFO_IDENTITY")
    assert row.status == "BLOCK" and row.calculated_value is None
    assert any(p.amount is None for p in row.components)


def test_mismatches_and_null_operands_never_become_passes() -> None:
    value = accounts(constructed_case(), "H1", ebitda="121.00")
    row = check(run(value), "Q:H1-Q1", "EBITDA_BRIDGE")
    assert row.status == "BLOCK" and row.difference == -1
    assert row.independent
    value = accounts(value, "H1", cogs=None)
    row = check(run(value), "Q:H1-Q1", "EBITDA_BRIDGE")
    assert row.status == "BLOCK" and row.calculated_value is None


def test_undisclosed_segments_warn_with_null_and_not_independent() -> None:
    row = check(run(constructed_case()), "Q:H1-Q1", "SEGMENT_REVENUE")
    assert row.status == "WARN" and not row.independent
    assert row.calculated_value is None


def test_context_and_tamper_validation() -> None:
    value = constructed_case()
    pack, review = frozen(value)
    report = reconcile_periods(pack, review, value.book_id)
    with localcontext() as context:
        context.prec = 2
        assert reconcile_periods(pack, review, value.book_id) == report
    assert validate_period_reconciliation(pack, review, report) == ()
    assert validate_period_reconciliation(pack, review, report.model_copy(update={"checks": ()}))
    bad = report.checks[0].model_copy(update={"calculated_value": Decimal("NaN")})
    assert validate_period_reconciliation(
        pack, review, report.model_copy(update={"checks": (bad,)})
    )
    bad_history = report.historical.model_copy(update={"book_id": "unknown"})
    assert validate_period_reconciliation(
        pack, review, report.model_copy(update={"historical": bad_history})
    )


def test_equal_source_errors_cannot_cancel_into_cfo_agreement() -> None:
    value = constructed_case()
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(
                    update={"value": observed(r.value.observation_id, str(r.value.amount + 1))}
                )
                if r.line_id == "noncash" and r.period_id in {"Q1", "H1"}
                else r
                for r in value.statement_lines
            )
        }
    )
    row = check(run(value), "Q:H1-Q1", "CFO_IDENTITY")
    assert sum(p.amount * p.coefficient for p in row.components) == row.reported.amount
    assert row.status == "BLOCK" and row.calculated_value is None


def test_direct_quarters_independently_check_fy_and_gaps_block() -> None:
    from datetime import date

    from tests.product.test_financial_model import model_case

    value = model_case()
    row = check(run(value), "FY:FY", "FY_QUARTERS", "revenue")
    assert row.status == "PASS" and row.independent and row.calculated_value == 400
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"start_date": date(2025, 4, 2)}) if p.period_id == "Q2" else p
                for p in value.periods
            )
        }
    )
    row = check(run(value), "FY:FY", "FY_QUARTERS", "revenue")
    assert row.status == "BLOCK" and row.calculated_value is None


@pytest.mark.parametrize("lease_class", ["FINANCE_LEASE", "OPERATING_LEASE"])
def test_constructed_segment_bridge_debt_excludes_both_leases_and_no_fx(lease_class: str) -> None:
    from deploy_vii.financial_contracts import SegmentAllocation, SegmentObservation
    from tests.product.test_financials import _C, facility

    value = constructed_case()
    segments = tuple(
        SegmentObservation(
            segment_id="all",
            segment_name="All operations",
            segment_type="OPERATING_SEGMENT",
            display_priority=1,
            period_id=p.period_id,
            revenue=observed("segment." + p.period_id, str(scale * 100)),
            classification_citations=(_C,),
        )
        for p, scale in zip(value.periods, (1, 2, 3, 4), strict=True)
    )
    facilities = tuple(facility(p.period_id) for p in value.periods)
    lease = facility("H1", "lease").model_copy(update={"lease_classification": lease_class})
    value = accounts(
        value.model_copy(
            update={
                "segments": segments,
                "segment_allocation": (
                    SegmentAllocation(
                        slot_id="DIVISION_1",
                        slot_label="All",
                        component_segment_ids=("all",),
                        rationale="Same scope",
                    ),
                ),
                "facilities": (*facilities, lease),
                "segment_disclosure": value.addback_disclosure,
            }
        ),
        "H1",
        total_debt="100",
    )
    report = run(value)
    row = check(report, "Q:H1-Q1", "SEGMENT_REVENUE")
    assert row.status == "PASS" and row.calculated_value == 100
    debt = check(report, "Q:H1-Q1", "DEBT_TOTAL_EX_LEASES")
    assert debt.status == "PASS" and debt.calculated_value == 100
    assert [p.label for p in debt.components] == ["loan"]
    value = value.model_copy(
        update={
            "facilities": tuple(
                r.model_copy(update={"currency": "EUR"}) if r.facility_id == "loan" else r
                for r in value.facilities
            )
        }
    )
    debt = check(run(value), "Q:H1-Q1", "DEBT_TOTAL_EX_LEASES")
    assert (
        debt.status == "BLOCK"
        and debt.calculated_value is None
        and "conversion" in debt.explanation
    )


def test_cash_bridge_uses_quarter_opening_and_preserves_unexplained_difference() -> None:
    value = accounts(constructed_case(), "Q1", cash_and_equivalents="10")
    value = accounts(value, "H1", cash_and_equivalents="25", net_cash_change="20")
    value = accounts(value, "Q1", net_cash_change="5")
    row = check(run(value), "Q:H1-Q1", "NCF_CASH_MOVEMENT")
    assert row.status == "PASS" and row.reported.amount == row.calculated_value == 15
    value = accounts(value, "H1", cash_and_equivalents="26")
    row = check(run(value), "Q:H1-Q1", "NCF_CASH_MOVEMENT")
    assert row.status == "BLOCK" and row.difference == 1


def test_mixed_expense_presentation_cannot_be_silently_combined() -> None:
    value = constructed_case()
    # A by-nature source must have no COGS fact.
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"expense_presentation": "by_nature"})
                if p.period_id == "Q1"
                else p
                for p in value.periods
            ),
            "accounts": tuple(
                r for r in value.accounts if (r.period_id, r.metric_id) != ("Q1", "cogs")
            ),
        }
    )
    row = check(run(value), "Q:H1-Q1", "EBITDA_BRIDGE")
    assert (
        row.status == "BLOCK" and row.calculated_value is None and "presentation" in row.explanation
    )


def test_separately_reported_ltm_cannot_be_replaced_by_its_computation() -> None:
    from tests.product.test_financial_periods import rolled_case

    row = check(run(rolled_case()), "LTM:LTM", "REPORTED_DERIVED_PERIOD", "revenue")
    assert row.reported.amount == 999 and row.calculated_value == 110
    assert row.difference == -889 and row.status == "BLOCK" and row.independent
    assert row.reported.observation_ids == ("revenue.LTM",)
    assert row.components[0].observation_ids == ("revenue.FY24", "revenue.CYTD", "revenue.PYTD")


@pytest.mark.parametrize(
    ("amount", "shared", "blocker", "warning", "status", "difference"),
    [
        ("1.005", False, None, None, "PASS", "0.005"),
        ("1.006", False, None, None, "BLOCK", "0.006"),
        ("1.005", True, None, None, "WARN", "0.005"),
        ("1.006", True, None, "advisory", "BLOCK", "0.006"),
        ("1.00", False, "incomplete", "advisory", "BLOCK", None),
        (None, False, None, None, "BLOCK", None),
    ],
)
def test_tolerance_boundary_shared_sources_and_blocker_precedence(
    amount: str | None,
    shared: bool,
    blocker: str | None,
    warning: str | None,
    status: str,
    difference: str | None,
) -> None:
    from deploy_vii.period_reconciliation import PeriodTerm, _compare

    report = run(constructed_case())
    node = report.historical.constructions[0]
    reported = PeriodTerm(
        label="stated",
        value_id=None,
        amount=Decimal("1.00"),
        observation_ids=("source",),
        citations=(),
        reason=None,
    )
    part = PeriodTerm(
        label="component",
        value_id=None,
        amount=Decimal(amount) if amount else None,
        observation_ids=("source" if shared else "other",),
        citations=(),
        reason=None if amount else "missing",
    )
    row = _compare(
        node,
        "EBITDA_BRIDGE",
        "ebitda",
        reported,
        (part,),
        "one component",
        blocker=blocker,
        warning=warning,
    )
    assert row.status == status
    assert row.difference == (Decimal(difference) if difference else None)
