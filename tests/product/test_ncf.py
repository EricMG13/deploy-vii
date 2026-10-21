"""Independent cash-flow completeness and cancellation regressions (synthetic)."""

from decimal import Decimal, localcontext

import pytest

from deploy_vii.financial_contracts import FinancialBook
from deploy_vii.financial_reconciliation import reconcile_financials, validate_reconciliation_report
from deploy_vii.period_reconciliation import reconcile_periods, validate_period_reconciliation
from tests.product.test_cash_bridge import ncf_amount
from tests.product.test_financial_periods import frozen
from tests.product.test_financials import _C, conflict, observed
from tests.product.test_model_readiness import assess, ready_case
from tests.product.test_period_reconciliation import check as period_check
from tests.product.test_period_reconciliation import constructed_case, run
from tests.product.test_reconciliation import accounts
from tests.product.test_reconciliation import check as source_check
from tests.product.test_statements import identity, line


def nested_case() -> FinancialBook:
    value = ready_case()
    return value.model_copy(
        update={
            "statement_lines": (
                *value.statement_lines,
                line("capex", "capex_total", "-8", 20),
                line("invest", "other:investment", "-2", 21),
                line("dividend", "dividends_paid", "-2", 22),
                line("finance", "other:financing", "-28", 23),
            ),
            "accounts": tuple(
                a
                for a in value.accounts
                if not (a.period_id == "Q2" and a.metric_id == "capex_and_intangible_investment")
            ),
            "statement_identities": (
                *value.statement_identities,
                identity("cfi", ("capex", 1), ("invest", 1)),
                identity("cff", ("dividend", 1), ("finance", 1)),
            ),
        }
    )


def derived_case() -> FinancialBook:
    value = constructed_case()
    for pid, scale in (("Q1", 1), ("H1", 2), ("9M", 3), ("FY", 4)):
        value = accounts(value, pid, net_cash_change=str(20 * scale))
        value = value.model_copy(
            update={
                "statement_lines": (
                    *value.statement_lines,
                    line(
                        "cfi", "investing_cash_flow", str(-10 * scale), 10, kind="subtotal", pid=pid
                    ),
                    line(
                        "cff", "financing_cash_flow", str(-25 * scale), 11, kind="subtotal", pid=pid
                    ),
                    line("ncf", "net_cash_change", str(20 * scale), 12, kind="total", pid=pid),
                ),
                "statement_identities": (
                    *value.statement_identities,
                    identity("ncf", ("cfo", 1), ("cfi", 1), ("cff", 1), pid=pid),
                ),
            }
        )
    return value


def test_source_ncf_retains_independent_leaves_and_is_mandatory() -> None:
    value = ready_case()
    row = source_check(value, "NCF_IDENTITY")
    assert row.status == "PASS" and row.reported_value == row.calculated_value == 20
    assert [p.observation_id for p in row.components] == [
        "profit.Q2",
        "noncash.Q2",
        "cfi.Q2",
        "cff.Q2",
    ]
    assert row.context_citations and all(p.citations for p in row.components)
    report = assess(value)
    assert report.readiness.status == "ready"
    assert report.period_reconciliation
    required = set(report.readiness.mandatory_check_ids)
    checks = [
        c
        for c in report.period_reconciliation.checks
        if c.check_type == "NCF_IDENTITY"
        and c.construction_id in report.readiness.selected_quarters
    ]
    assert len(checks) == 4 and all(c.check_id in required for c in checks)


def test_numerically_agreeing_cash_balances_do_not_prove_ncf_completeness() -> None:
    value = ready_case().model_copy(
        update={
            "statement_identities": tuple(
                r for r in ready_case().statement_identities if r.target_line_id != "ncf"
            )
        }
    )
    assert source_check(value, "NCF_CASH_MOVEMENT").status == "PASS"
    row = source_check(value, "NCF_IDENTITY")
    assert row.status == "BLOCK" and row.calculated_value is None
    assert assess(value).readiness.status == "blocked"


@pytest.mark.parametrize("mode", ["missing", "conflicting", "partial", "wrong", "no_cff"])
def test_incomplete_or_wrong_source_cash_components_block(mode: str) -> None:
    value = ready_case()
    if mode == "partial":
        value = value.model_copy(
            update={
                "statement_disclosures": tuple(
                    r.model_copy(
                        update={"disclosure": r.disclosure.model_copy(update={"status": "partial"})}
                    )
                    if r.period_id == "Q2"
                    else r
                    for r in value.statement_disclosures
                )
            }
        )
    elif mode == "no_cff":
        value = value.model_copy(
            update={
                "statement_identities": tuple(
                    identity("ncf", ("cfo", 1), ("cfi", 1))
                    if r.period_id == "Q2" and r.target_line_id == "ncf"
                    else r
                    for r in value.statement_identities
                )
            }
        )
    else:
        value = value.model_copy(
            update={
                "statement_lines": tuple(
                    r.model_copy(
                        update={
                            "value": conflict("cff.Q2")
                            if mode == "conflicting"
                            else observed("cff.Q2", None if mode == "missing" else "-29")
                        }
                    )
                    if r.period_id == "Q2" and r.line_id == "cff"
                    else r
                    for r in value.statement_lines
                )
            }
        )
    row = source_check(value, "NCF_IDENTITY")
    assert row.status == "BLOCK"
    assert row.difference == (1 if mode == "wrong" else None)
    assert assess(value).readiness.status == "blocked"


def test_nested_equation_errors_cannot_cancel_under_an_agreeing_parent() -> None:
    value = nested_case()
    assert source_check(value, "NCF_IDENTITY").status == "PASS"
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(
                    update={
                        "value": observed(
                            r.value.observation_id, "-9" if r.line_id == "cfi" else "-31"
                        )
                    }
                )
                if r.period_id == "Q2" and r.line_id in {"cfi", "cff"}
                else r
                for r in value.statement_lines
            )
        }
    )
    generic = source_check(value, "SOURCE_STATEMENT_IDENTITY", metric="CFS:net_cash_change")
    assert generic.status == "PASS" and generic.calculated_value == 20
    row = source_check(value, "NCF_IDENTITY")
    assert sum(p.amount * p.coefficient for p in row.components) == row.reported_value
    assert row.status == "BLOCK" and row.calculated_value is None
    assert "cfi" in row.explanation and "cff" in row.explanation


def test_positive_source_outflow_magnitudes_use_equation_signs_once() -> None:
    value = ready_case()
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(
                    update={
                        "value": observed(r.value.observation_id, str(abs(r.value.amount))),
                        "sign_convention": "outflow_magnitude",
                        "sign_citations": (_C,),
                    }
                )
                if r.period_id == "Q2" and r.line_id in {"cfi", "cff"}
                else r
                for r in value.statement_lines
            ),
            "statement_identities": tuple(
                identity("ncf", ("cfo", 1), ("cfi", -1), ("cff", -1))
                if r.period_id == "Q2" and r.target_line_id == "ncf"
                else r
                for r in value.statement_identities
            ),
        }
    )
    row = source_check(value, "NCF_IDENTITY")
    assert row.status == "PASS" and row.calculated_value == 20
    assert [(p.original_amount, p.coefficient) for p in row.components[-2:]] == [(10, -1), (30, -1)]


def test_explicit_zero_financing_is_retained_as_a_source_operand() -> None:
    value = ncf_amount(ready_case(), "Q2", "50")
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(update={"value": observed("cff.Q2", "0")})
                if r.period_id == "Q2" and r.line_id == "cff"
                else r
                for r in value.statement_lines
            )
        }
    )
    row = source_check(value, "NCF_IDENTITY")
    assert row.status == "PASS" and row.calculated_value == 50
    assert row.components[-1].amount == 0 and row.components[-1].citations


def test_source_cash_decrease_magnitude_is_converted_to_canonical_target_sign() -> None:
    value = ready_case()
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(
                    update={"sign_convention": "outflow_magnitude", "sign_citations": (_C,)}
                )
                if r.period_id == "Q2" and r.line_id == "ncf"
                else r.model_copy(update={"value": observed("cff.Q2", "-70")})
                if r.period_id == "Q2" and r.line_id == "cff"
                else r
                for r in value.statement_lines
            ),
            "statement_identities": tuple(
                identity("ncf", ("cfo", -1), ("cfi", -1), ("cff", -1))
                if r.period_id == "Q2" and r.target_line_id == "ncf"
                else r
                for r in value.statement_identities
            ),
        }
    )
    source = source_check(value, "NCF_IDENTITY")
    assert source.status == "PASS" and source.reported.original_amount == 20
    assert source.reported_value == source.calculated_value == -20
    row = period_check(run(value), "Q:Q2", "NCF_IDENTITY")
    assert row.status == "PASS" and row.reported.amount == row.calculated_value == -20


def test_fx_is_only_present_when_explicitly_part_of_source_ncf_equation() -> None:
    value = ready_case()
    value = value.model_copy(
        update={
            "statement_lines": (
                *value.statement_lines,
                line("fx", "fx_cash_effect", "2", 4),
            )
        }
    )
    assert source_check(value, "NCF_IDENTITY").calculated_value == 20
    value = ncf_amount(value, "Q2", "22")
    assert source_check(value, "NCF_IDENTITY").status == "BLOCK"
    value = value.model_copy(
        update={
            "statement_identities": tuple(
                identity("ncf", ("cfo", 1), ("cfi", 1), ("cff", 1), ("fx", 1))
                if r.period_id == "Q2" and r.target_line_id == "ncf"
                else r
                for r in value.statement_identities
            )
        }
    )
    row = source_check(value, "NCF_IDENTITY")
    assert row.status == "PASS" and row.calculated_value == 22
    assert row.components[-1].observation_id == "fx.Q2"


def test_generic_balancing_detail_cannot_replace_the_three_cash_categories() -> None:
    value = ready_case()
    value = value.model_copy(
        update={
            "statement_lines": (*value.statement_lines, line("plug", "other:combined", "-40", 20)),
            "statement_identities": tuple(
                identity("ncf", ("cfo", 1), ("plug", 1))
                if r.period_id == "Q2" and r.target_line_id == "ncf"
                else r
                for r in value.statement_identities
            ),
        }
    )
    assert (
        source_check(value, "SOURCE_STATEMENT_IDENTITY", metric="CFS:net_cash_change").status
        == "PASS"
    )
    row = source_check(value, "NCF_IDENTITY")
    assert row.status == "BLOCK" and row.calculated_value is None
    assert "operating, investing and financing" in row.explanation


def test_constructed_quarter_subtracts_source_leaves_without_canceling_errors() -> None:
    value = derived_case()
    row = period_check(run(value), "Q:H1-Q1", "NCF_IDENTITY")
    assert row.status == "PASS" and row.calculated_value == 20
    assert [p.coefficient for p in row.components] == [1] * 4 + [-1] * 4
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(
                    update={"value": observed(r.value.observation_id, str(r.value.amount + 1))}
                )
                if r.line_id == "cfi" and r.period_id in {"Q1", "H1"}
                else r
                for r in value.statement_lines
            )
        }
    )
    row = period_check(run(value), "Q:H1-Q1", "NCF_IDENTITY")
    assert sum(p.amount * p.coefficient for p in row.components) == row.reported.amount
    assert row.status == "BLOCK" and row.calculated_value is None
    assert "Q1" in row.explanation and "H1" in row.explanation


def test_missing_source_target_cannot_be_replaced_with_a_known_canonical_value() -> None:
    value = ready_case()
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(update={"value": observed("ncf.Q2", None)})
                if r.line_id == "ncf" and r.period_id == "Q2"
                else r
                for r in value.statement_lines
            )
        }
    )
    row = source_check(value, "NCF_IDENTITY")
    assert row.reported_value == 20 and row.calculated_value is None and row.status == "BLOCK"


def test_ncf_reports_recompute_and_do_not_use_ambient_precision() -> None:
    value = nested_case()
    pack, review = frozen(value)
    source = reconcile_financials(pack, review, value.book_id)
    periods = reconcile_periods(pack, review, value.book_id)
    with localcontext() as context:
        context.prec = 1
        assert reconcile_financials(pack, review, value.book_id) == source
        assert reconcile_periods(pack, review, value.book_id) == periods
    assert validate_reconciliation_report(pack, review, source) == ()
    assert validate_period_reconciliation(pack, review, periods) == ()
    assert source.schema_version == "financial-reconciliation/6"
    assert periods.schema_version == "period-reconciliation/5"
    assert assess(ready_case()).schema_version == "model-readiness/3"
    check = next(c for c in source.checks if c.check_type == "NCF_IDENTITY")
    altered = check.model_copy(update={"calculated_value": Decimal("999")})
    assert validate_reconciliation_report(
        pack, review, source.model_copy(update={"checks": (altered,)})
    )
