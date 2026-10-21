"""Canonical ratios retain their own debt/earnings basis and source operands."""

from decimal import Decimal, localcontext

import pytest

from deploy_vii.canonical_kpis import (
    CanonicalKpi,
    CanonicalKpiReport,
    canonical_kpis,
    validate_canonical_kpis,
)
from deploy_vii.financial_contracts import Alternative, FinancialBook
from deploy_vii.financial_model import model_report
from deploy_vii.model._cells import CONTEXT
from tests.product.test_financial_periods import frozen
from tests.product.test_financials import _C, facility, observed
from tests.product.test_model_readiness import ready_case
from tests.product.test_reconciliation import accounts


def case() -> FinancialBook:
    value = ready_case()
    for p in value.periods:
        if p.period_type != "PERIOD_END":
            n = 4 if p.period_type == "FY" else 1
            value = accounts(
                value,
                p.period_id,
                gross_profit=str(70 * n),
                ebit=str(50 * n),
                net_income=str(40 * n),
            )
    return value


def run(value: FinancialBook) -> CanonicalKpiReport:
    pack, review = frozen(value)
    return canonical_kpis(pack, review, value.book_id)


def kpi(report: CanonicalKpiReport, key: str, column: str = "Q:Q4") -> CanonicalKpi:
    basis = next(
        b.basis_id for b in report.bases if b.column_key == column and b.scope == "historical"
    )
    return next(k for k in report.kpis if k.key == key and k.display_basis_id == basis)


def test_canonical_debt_excludes_leases_and_never_uses_model_total() -> None:
    value = case()
    leases = tuple(
        facility(p.period_id, "lease").model_copy(
            update={
                "carrying_value": observed("lease." + p.period_id + ".carrying", "50"),
                "lease_classification": "FINANCE_LEASE",
            }
        )
        for p in value.periods
    )
    value = value.model_copy(update={"facilities": (*value.facilities, *leases)})
    pack, review = frozen(value)
    canonical = canonical_kpis(pack, review, value.book_id)
    model = model_report(pack, review, value.book_id)
    assert kpi(canonical, "total_debt").value.amount == 100
    assert kpi(canonical, "total_leverage_reported").numerator.amount == 100
    assert any(v.key == "total_debt" and v.value.amount == 150 for v in model.values)
    assert not ({v.value_id for v in canonical.values} & {v.value_id for v in model.values})
    assert kpi(canonical, "net_debt").value.amount == 20


def test_reported_and_adjusted_earnings_remain_distinct_without_fallback_preference() -> None:
    value = case()
    for p in value.periods:
        if p.period_type != "PERIOD_END":
            n = 4 if p.period_type == "FY" else 1
            value = accounts(value, p.period_id, ebitda=str(50 * n), adjusted_ebitda=str(80 * n))
    report = run(value)
    reported, adjusted = (
        kpi(report, "total_leverage_reported"),
        kpi(report, "total_leverage_adjusted"),
    )
    assert reported.denominator.amount == 200 and adjusted.denominator.amount == 320
    assert reported.value.amount == Decimal("0.5") and adjusted.value.amount == Decimal("0.3125")
    assert kpi(report, "ebitda_margin").value.amount == Decimal("0.5")
    assert kpi(report, "adjusted_ebitda_margin").value.amount == Decimal("0.8")
    assert kpi(report, "ffo").value.amount == 60


def test_missing_reported_income_derives_in_dependency_order() -> None:
    value = case()
    value = value.model_copy(
        update={
            "accounts": tuple(
                r
                for r in value.accounts
                if r.metric_id not in {"ebit", "ebitda", "adjusted_ebitda"}
            )
        }
    )
    value = accounts(value, "Q4", gross_profit="80")
    report = run(value)
    assert kpi(report, "ebit").value.amount == 60
    assert kpi(report, "ebitda").value.amount == 70
    assert kpi(report, "adjusted_ebitda").value.amount == 70
    assert "derived from components" in kpi(report, "ebitda").value.note


def test_conflicting_income_cannot_be_replaced_by_derived_earnings() -> None:
    value = case()
    target = next(r for r in value.accounts if r.metric_id == "ebitda" and r.period_id == "Q4")
    conflicted = target.value.model_copy(
        update={
            "amount": None,
            "status": "conflicting",
            "reason": "Synthetic competing definitions",
            "alternatives": tuple(
                Alternative(amount=Decimal(n), citations=(_C,), explanation=n) for n in ("50", "60")
            ),
        }
    )
    value = value.model_copy(
        update={
            "accounts": tuple(
                r.model_copy(update={"value": conflicted}) if r == target else r
                for r in value.accounts
            )
        }
    )
    report = run(value)
    for key in ("ebitda", "ebitda_margin", "total_leverage_reported"):
        row = kpi(report, key)
        assert row.value.amount is None and row.value.calculation_status == "Conflicted"
    assert kpi(report, "total_leverage_adjusted").value.amount is not None


def test_every_kpi_leg_resolves_to_exact_signed_operands_and_span() -> None:
    report = run(case())
    values = {v.value_id: v for v in report.values}
    bases = {b.basis_id: b for b in report.bases}
    roots = {c.computation_id for c in report.computations}
    assert all(v.computation_id in roots for v in values.values())
    with localcontext(CONTEXT):
        for row in report.kpis:
            for side in (row.numerator, row.denominator):
                if side is None:
                    continue
                assert all(p.value_id in values for p in side.operands)
                if side.amount is not None:
                    assert side.amount == sum(
                        values[p.value_id].value.amount * p.coefficient for p in side.operands
                    )
            if row.operation == "ratio" and row.value.amount is not None:
                assert row.value.amount == row.numerator.amount / row.denominator.amount
    leverage = kpi(report, "total_leverage_reported")
    assert all(
        bases[values[o.value_id].basis_id].scope == "trailing_four_quarters"
        for o in leverage.denominator.operands
    )
    assert kpi(report, "cfo_to_debt").numerator.amount == 240
    assert kpi(report, "fcf_to_adjusted_ebitda").numerator.amount == 50


@pytest.mark.parametrize("amount", [None, "0", "-1"])
def test_missing_or_nonpositive_denominators_never_produce_infinite_ratios(
    amount: str | None,
) -> None:
    value = case()
    for p in value.periods:
        if p.period_type != "PERIOD_END":
            value = accounts(value, p.period_id, total_debt=amount)
    row = kpi(run(value), "ffo_to_debt")
    assert row.value.amount is None
    assert row.value.calculation_status == "Not Calculable"


def test_ffo_interest_coverage_adds_back_cash_interest_paid() -> None:
    report = run(case())
    row = kpi(report, "ffo_interest_coverage")
    coverage = kpi(report, "interest_coverage_reported")
    ffo = kpi(report, "ffo_to_debt")
    assert row.operation == "ratio" and row.unit == "MULTIPLE"
    assert row.denominator.amount == coverage.denominator.amount == 20
    assert row.numerator.amount == ffo.numerator.amount + coverage.denominator.amount
    assert row.value.amount == row.numerator.amount / row.denominator.amount


@pytest.mark.parametrize("amount", [None, "0"])
def test_ffo_interest_coverage_without_interest_paid_is_not_calculable(
    amount: str | None,
) -> None:
    value = case()
    for p in value.periods:
        if p.period_type != "PERIOD_END":
            value = accounts(value, p.period_id, cash_interest_paid=amount)
    row = kpi(run(value), "ffo_interest_coverage")
    assert row.value.amount is None
    assert row.value.calculation_status == "Not Calculable"


def test_only_dcf_remains_undefined_in_limitations() -> None:
    limitations = " ".join(run(case()).limitations)
    assert "FFO interest coverage" not in limitations
    assert "DCF definition remains unresolved" in limitations


def test_undefined_formula_rows_remain_explicit_and_tampering_is_rejected() -> None:
    value = case()
    pack, review = frozen(value)
    report = canonical_kpis(pack, review, value.book_id)
    assert validate_canonical_kpis(pack, review, report) == ()
    for key in ("dcf", "dcf_to_debt"):
        row = kpi(report, key)
        assert row.operation == "unavailable" and row.value.amount is None
        assert row.value.note and not row.numerator.operands and row.denominator is None
    assert validate_canonical_kpis(
        pack, review, report.model_copy(update={"kpis": report.kpis[:-1]})
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        canonical_kpis(pack, review.model_copy(update={"issuer_id": "other"}), value.book_id)


def test_rolling_earnings_sum_canonical_quarters_after_each_source_choice() -> None:
    value = accounts(accounts(case(), "Q3", ebitda="80"), "Q2", ebitda=None)
    report = run(value)
    assert kpi(report, "ebitda", "Q:Q2").value.amount == 60
    assert kpi(report, "ebitda", "Q:Q3").value.amount == 80
    assert kpi(report, "total_leverage_reported").denominator.amount == 260


def test_invalid_rolling_span_stays_null_while_closing_balances_remain_known() -> None:
    from datetime import date

    value = case()
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"start_date": date(2025, 4, 2)}) if p.period_id == "Q2" else p
                for p in value.periods
            )
        }
    )
    report = run(value)
    row = kpi(report, "total_leverage_reported")
    assert row.numerator.amount == 100 and row.denominator.amount is None
    assert row.value.amount is None
    assert kpi(report, "ebitda_margin").value.amount == Decimal("0.6")


def test_explicit_not_applicable_earnings_do_not_fall_through_to_derivation() -> None:
    value = case()
    value = value.model_copy(
        update={
            "accounts": tuple(
                r.model_copy(
                    update={
                        "value": observed(r.value.observation_id, None, status="not_applicable")
                    }
                )
                if r.metric_id == "ebitda" and r.period_id == "Q4"
                else r
                for r in value.accounts
            )
        }
    )
    report = run(value)
    assert kpi(report, "ebitda").value.amount is None
    assert kpi(report, "total_leverage_reported").value.amount is None


def test_cash_outflow_signs_and_ambient_decimal_context_do_not_change_outputs() -> None:
    value = case()
    signed = run(value)
    flipped = value.model_copy(
        update={
            "accounts": tuple(
                r.model_copy(
                    update={
                        "value": observed(r.value.observation_id, str(r.value.amount.copy_abs()))
                    }
                )
                if r.metric_id in {"capex_and_intangible_investment", "cash_interest_paid"}
                else r
                for r in value.accounts
            )
        }
    )
    with localcontext() as context:
        context.prec = 3
        normalized = run(flipped)
    for key in (
        "capex_adjusted_coverage",
        "interest_coverage_reported",
        "fcf_to_adjusted_ebitda",
        "ffo_interest_coverage",
    ):
        assert kpi(signed, key).value.amount == kpi(normalized, key).value.amount
    assert kpi(normalized, "capex_adjusted_coverage").numerator.amount == 200
    assert kpi(normalized, "capex_adjusted_coverage").denominator.amount == 20


def test_growth_uses_canonical_like_period_and_resolvable_prior_values() -> None:
    import json

    current = case()
    payload = current.model_dump(mode="json")

    def previous(item: object) -> object:
        if isinstance(item, list):
            return [previous(part) for part in item]
        if not isinstance(item, dict):
            return item
        result = {key: previous(part) for key, part in item.items()}
        for key in ("period_id", "observation_id", "identity_id", "bridge_id", "locator"):
            if key in result:
                result[key] = "prior." + result[key]
        if "fiscal_year" in result:
            result["fiscal_year"] = str(int(result["fiscal_year"]) - 1)
        for key in ("start_date", "end_date"):
            if result.get(key):
                result[key] = str(int(result[key][:4]) - 1) + result[key][4:]
        if result.get("statement") == "BS" and result.get("item_id") == "total_equity":
            # The prior year's closing balance must equal the current opening
            # balance; shift the entire synthetic equity series, preserving flows.
            result["value"]["amount"] = str(Decimal(result["value"]["amount"]) - 160)
        return result

    prior = FinancialBook.model_validate_json(json.dumps(previous(payload)))
    for pid in ("prior.Q4", "prior.FY"):
        prior = accounts(prior, pid, cash_and_equivalents="0")
    current = accounts(current, "Q4", revenue="120", ebitda="72")
    current = current.model_copy(
        update={
            key: (*getattr(prior, key), *getattr(current, key))
            for key in (
                "periods",
                "accounts",
                "facilities",
                "statement_lines",
                "statement_identities",
                "statement_disclosures",
                "balance_movement_bridges",
            )
        }
    )
    report = run(current)
    row = kpi(report, "ebitda_growth")
    assert row.value.amount == Decimal("0.2")
    assert row.numerator.amount == 72 and row.denominator.amount == 60
    values = {v.value_id: v for v in report.values}
    bases = {b.basis_id: b for b in report.bases}
    assert all(
        bases[values[p.value_id].basis_id].column_key == "Q:prior.Q4"
        for p in row.denominator.operands
    )
