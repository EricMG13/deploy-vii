"""Synthetic independent source-check cases; no analytical qualification claim."""

from datetime import date
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from deploy_vii.financial_contracts import (
    AccountObservation,
    AddbackObservation,
    FinancialBook,
    SegmentAllocation,
    SegmentObservation,
)
from deploy_vii.financial_reconciliation import (
    Reconciliation,
    ReconciliationReport,
    ReconciliationTerm,
    reconcile_financials,
    validate_reconciliation_report,
)
from tests.product.test_financials import _C, book, conflict, facility, freeze, observed, period


def accounts(value: FinancialBook, pid: str, **amounts: str | None) -> FinancialBook:
    keep = tuple(
        a for a in value.accounts if (a.period_id, a.metric_id) not in {(pid, m) for m in amounts}
    )
    additions = tuple(
        AccountObservation(metric_id=m, period_id=pid, value=observed(pid + "." + m, n))
        for m, n in amounts.items()
    )
    return value.model_copy(update={"accounts": (*keep, *additions)})


def run(value: FinancialBook) -> ReconciliationReport:
    pack, review = freeze(value)
    # Test fixtures may cover the complete synthetic year; adjust both frozen identities.
    run_date = date(2026, 1, 15)
    pack = pack.model_copy(update={"run": pack.run.model_copy(update={"as_of": run_date})})
    review = review.model_copy(update={"as_of": run_date, "pack_sha256": pack.content_hash()})
    result = reconcile_financials(pack, review, value.book_id)
    assert result.review_sha256 == review.content_hash()
    assert result.pack_sha256 == pack.content_hash()
    return result


def check(
    value: FinancialBook, kind: str, pid: str = "Q2", metric: str | None = None
) -> Reconciliation:
    return next(
        c
        for c in run(value).checks
        if c.period_id == pid and c.check_type == kind and (metric is None or c.metric_id == metric)
    )


def complete() -> FinancialBook:
    value = accounts(
        book(),
        "Q2",
        ebitda="60.00",
        adjusted_ebitda="65.00",
        total_debt="100",
        net_cash_change="5",
        cash_and_equivalents="25",
    )
    segment = SegmentObservation(
        segment_id="digital",
        segment_name="Digital",
        segment_type="OPERATING_SEGMENT",
        display_priority=1,
        period_id="Q2",
        revenue=observed("segment.revenue", "100"),
        classification_citations=(_C,),
    )
    addback = AddbackObservation(
        addback_id="restructuring",
        addback_label="Restructuring",
        classification="RESTRUCTURING",
        realization_status="REALIZED",
        display_priority=1,
        period_id="Q2",
        value=observed("addback.restructuring", "5"),
        source_definition="Synthetic",
        classification_citations=(_C,),
    )
    return value.model_copy(
        update={
            "segments": (segment,),
            "addbacks": (addback,),
            "segment_disclosure": value.segment_disclosure.model_copy(
                update={"status": "complete"}
            ),
            "segment_allocation": (
                SegmentAllocation(
                    slot_id="DIVISION_1",
                    slot_label="Digital",
                    component_segment_ids=("digital",),
                    rationale="Same scope",
                ),
            ),
        }
    )


def test_independent_checks_retain_inputs_amounts_differences_and_hashes() -> None:
    result = run(complete())
    latest = {c.check_type: c for c in result.checks if c.period_id == "Q2"}
    for kind in (
        "SEGMENT_REVENUE",
        "EBITDA_BRIDGE",
        "ADJUSTED_EBITDA_BRIDGE",
        "DEBT_TOTAL_EX_LEASES",
        "NCF_CASH_MOVEMENT",
    ):
        assert latest[kind].status == "PASS", kind
        assert latest[kind].difference == 0
        assert latest[kind].reported.citations
        assert all(t.citations for t in latest[kind].components)
    assert latest["EBITDA_BRIDGE"].calculated_value == 60
    assert latest["ADJUSTED_EBITDA_BRIDGE"].calculated_value == 65
    assert latest["CFO_IDENTITY"].status == "BLOCK"
    assert latest["CFO_IDENTITY"].calculated_value is None
    assert "independent" in latest["CFO_IDENTITY"].explanation
    assert ReconciliationReport.model_validate_json(result.model_dump_json()) == result
    assert len({c.check_id for c in result.checks}) == len(result.checks)


def test_reporting_precision_preserves_real_difference_and_boundary() -> None:
    value = accounts(complete(), "Q2", ebitda="60.005")
    row = check(value, "EBITDA_BRIDGE")
    assert row.status == "BLOCK"
    assert row.difference == Decimal("-0.005")
    assert row.tolerance == Decimal("0.0005")
    value = accounts(complete(), "Q2", opex_including_da="20.005")
    row = check(value, "EBITDA_BRIDGE")
    assert row.status == "PASS"  # Exactly half the source EBITDA's last decimal place.
    assert row.difference == Decimal("-0.005")
    assert row.components[2].original_amount == Decimal("20.005")
    assert row.components[2].amount == Decimal("-20.005")
    value = accounts(complete(), "Q2", opex_including_da="20.006")
    assert check(value, "EBITDA_BRIDGE").status == "BLOCK"


def test_arithmetic_is_independent_of_ambient_decimal_context() -> None:
    value = accounts(complete(), "Q2", revenue="123456789012345.1234567890")
    before = run(value)
    with localcontext() as context:
        context.prec = 4
        after = run(value)
    assert before == after


def test_missing_components_never_pass_or_become_a_partial_sum() -> None:
    value = accounts(complete(), "Q2", cogs=None)
    row = check(value, "EBITDA_BRIDGE")
    assert row.status == "BLOCK"
    assert row.calculated_value is row.difference is None
    assert row.components[1].amount is None
    assert row.components[1].reason
    value = accounts(complete(), "Q2", ebitda=None)
    assert check(value, "EBITDA_BRIDGE").status == "BLOCK"
    assert check(value, "ADJUSTED_EBITDA_BRIDGE").calculated_value is None


def test_by_nature_requires_evidence_and_has_no_cogs_component() -> None:
    value = complete()
    value = value.model_copy(
        update={
            "accounts": tuple(a for a in value.accounts if a.metric_id != "cogs"),
            "periods": tuple(
                p.model_copy(update={"expense_presentation": "by_nature"}) for p in value.periods
            ),
        }
    )
    value = accounts(value, "Q2", ebitda="90")
    row = check(value, "EBITDA_BRIDGE")
    assert row.status == "PASS"
    assert len(row.components) == 3
    assert row.context_citations
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"expense_presentation": "unknown"}) for p in value.periods
            )
        }
    )
    assert check(value, "EBITDA_BRIDGE").calculated_value is None


def test_no_disclosure_warns_but_partial_disclosure_blocks() -> None:
    row = check(book(), "SEGMENT_REVENUE")
    assert row.status == "WARN"
    assert row.calculated_value is None
    value = complete()
    value = value.model_copy(
        update={
            "segment_disclosure": value.segment_disclosure.model_copy(update={"status": "partial"})
        }
    )
    row = check(value, "SEGMENT_REVENUE")
    assert row.status == "BLOCK"
    assert row.calculated_value is None
    # A source row in one period establishes a series; missing Q1 is not absence.
    assert check(complete(), "SEGMENT_REVENUE", "Q1").status == "BLOCK"


def test_addbacks_keep_exact_granularity_and_negative_deductions() -> None:
    value = complete()
    second = value.addbacks[0].model_copy(
        update={
            "addback_id": "deduction",
            "addback_label": "Deduction",
            "display_priority": 2,
            "value": observed("deduction", "-2"),
        }
    )
    value = accounts(
        value.model_copy(update={"addbacks": (*value.addbacks, second)}), "Q2", adjusted_ebitda="63"
    )
    row = check(value, "ADJUSTED_EBITDA_BRIDGE")
    assert row.status == "PASS"
    assert [t.label for t in row.components] == ["ebitda", "restructuring", "deduction"]
    assert row.components[-1].amount == -2
    value = value.model_copy(
        update={
            "addback_disclosure": value.addback_disclosure.model_copy(update={"status": "partial"})
        }
    )
    assert check(value, "ADJUSTED_EBITDA_BRIDGE").calculated_value is None
    empty = accounts(book(), "Q2", ebitda="60", adjusted_ebitda="60")
    assert check(empty, "ADJUSTED_EBITDA_BRIDGE").status == "PASS"


def test_debt_uses_carrying_excludes_both_leases_and_retains_cost_adjustments() -> None:
    value = complete()
    finance = facility(fid="finance").model_copy(update={"lease_classification": "FINANCE_LEASE"})
    operating = facility(fid="operating").model_copy(
        update={"lease_classification": "OPERATING_LEASE"}
    )
    adjustment = facility(fid="cost").model_copy(
        update={
            "facility_type": "DEBT ADJUSTMENT",
            "carrying_value": observed("cost.carrying", "-3"),
        }
    )
    value = accounts(
        value.model_copy(
            update={"facilities": (*value.facilities, finance, operating, adjustment)}
        ),
        "Q2",
        total_debt="97",
    )
    row = check(value, "DEBT_TOTAL_EX_LEASES")
    assert row.status == "PASS"
    assert row.calculated_value == 97  # Principal 105 and commitment 150 never substitute.
    assert [t.label for t in row.components] == ["loan", "cost"]
    foreign = adjustment.model_copy(update={"currency": "EUR"})
    value = value.model_copy(update={"facilities": (*value.facilities[:-1], foreign)})
    row = check(value, "DEBT_TOTAL_EX_LEASES")
    assert row.status == "BLOCK"
    assert row.calculated_value is None
    assert "foreign" in row.explanation


def test_same_date_conflict_blocks_cash_without_first_known_value_winning() -> None:
    value = complete()
    ending = value.periods[-1].model_copy(update={"period_id": "END", "period_type": "PERIOD_END"})
    row = AccountObservation(
        metric_id="cash_and_equivalents", period_id="END", value=conflict("cash.conflict")
    )
    value = value.model_copy(
        update={"periods": (*value.periods, ending), "accounts": (*value.accounts, row)}
    )
    result = check(value, "NCF_CASH_MOVEMENT")
    assert result.status == "BLOCK"
    assert result.components[0].amount is None
    assert result.components[0].citations
    assert [c.check_type for c in run(value).checks if c.period_id == "END"] == [
        "DEBT_TOTAL_EX_LEASES"
    ]


def year() -> FinancialBook:
    value = book()
    q3 = period("Q3", "2025-07-01", "2025-09-30", 3)
    q4 = period("Q4", "2025-10-01", "2025-12-31", 4)
    fy = period("FY", "2025-01-01", "2025-12-31", 4, "FY").model_copy(
        update={"audit_status": "AUDITED"}
    )
    value = value.model_copy(update={"periods": (*value.periods, q3, q4, fy)})
    for pid in ("Q3", "Q4"):
        value = accounts(value, pid, revenue="100")
    return accounts(value, "FY", revenue="400")


def test_fy_comparison_does_not_replace_reported_or_force_audited_difference_to_zero() -> None:
    value = year()
    row = check(value, "FY_QUARTERS", "FY", "revenue")
    assert row.status == "PASS"
    assert row.calculated_value == row.reported_value == 400
    value = accounts(value, "FY", revenue="410")
    row = check(value, "FY_QUARTERS", "FY", "revenue")
    assert row.status == "BLOCK"
    assert row.reported_value == 410
    assert row.calculated_value == 400
    assert row.difference == -10
    assert check(value, "FY_QUARTERS", "FY", "cogs").calculated_value is None


@pytest.mark.parametrize("change", ["gap", "missing", "unknown_dates"])
def test_fy_requires_four_dated_quarters_spanning_exactly_the_year(change: str) -> None:
    value = year()
    periods = list(value.periods)
    if change == "gap":
        periods[2] = periods[2].model_copy(update={"start_date": date(2025, 7, 2)})
    elif change == "missing":
        periods = [p for p in periods if p.period_id != "Q3"]
        value = value.model_copy(
            update={"accounts": tuple(a for a in value.accounts if a.period_id != "Q3")}
        )
    else:
        periods[2] = periods[2].model_copy(update={"start_date": None, "limitation": "Not stated"})
    value = value.model_copy(update={"periods": tuple(periods)})
    row = check(value, "FY_QUARTERS", "FY", "revenue")
    assert row.status == "BLOCK"
    assert row.calculated_value is None


def test_reconciliation_revalidates_contract_and_rejects_identity_drift() -> None:
    pack, review = freeze(complete())
    with pytest.raises(ValueError, match="identity mismatch"):
        reconcile_financials(pack, review.model_copy(update={"issuer_id": "other"}), "consolidated")
    with pytest.raises(ValueError, match="Unknown financial book"):
        reconcile_financials(pack, review, "unknown")
    with pytest.raises(ValidationError):
        ReconciliationTerm(
            label="Missing", observation_id=None, original_amount=None, amount=None, citations=()
        )
    with pytest.raises(ValidationError):
        ReconciliationTerm(
            label="Known",
            observation_id=None,
            original_amount=Decimal(1),
            amount=Decimal(1),
            reason="Contradiction",
            citations=(),
        )


def test_missing_balance_evidence_and_lease_exclusion_context_are_retained() -> None:
    value = complete()
    missing = facility().model_copy(update={"carrying_value": observed("missing.carrying", None)})
    lease_quote = _C.model_copy(
        update={"locator": "lease.classification", "quote": "Synthetic facility is a finance lease"}
    )
    lease = facility(fid="lease").model_copy(
        update={"lease_classification": "FINANCE_LEASE", "terms_citations": (lease_quote,)}
    )
    value = accounts(
        value.model_copy(update={"facilities": (missing, lease)}), "Q2", cash_and_equivalents=None
    )
    debt = check(value, "DEBT_TOTAL_EX_LEASES")
    assert debt.components[0].observation_id == "missing.carrying"
    assert debt.components[0].citations
    assert any(c.locator == "lease.classification" for c in debt.context_citations)
    cash = check(value, "NCF_CASH_MOVEMENT")
    assert cash.components[0].observation_id == "Q2.cash_and_equivalents"
    assert cash.components[0].citations


def test_recomputation_rejects_numeric_status_and_identity_tampering() -> None:
    pack, review = freeze(complete())
    result = reconcile_financials(pack, review, "consolidated")
    assert validate_reconciliation_report(pack, review, result) == ()
    for updates in ({"issuer_id": "other"}, {"checks": ()}, {"review_sha256": "f" * 64}):
        assert validate_reconciliation_report(pack, review, result.model_copy(update=updates))
    tampered = result.checks[0].model_copy(update={"status": "PASS", "difference": Decimal(0)})
    assert validate_reconciliation_report(
        pack, review, result.model_copy(update={"checks": (tampered, *result.checks[1:])})
    )
    invalid = result.checks[0].model_copy(update={"difference": Decimal("NaN")})
    assert validate_reconciliation_report(
        pack, review, result.model_copy(update={"checks": (invalid,)})
    )
    assert validate_reconciliation_report(
        pack, review, result.model_copy(update={"book_id": "unknown"})
    )
