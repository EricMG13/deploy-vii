"""Sourced annual audit differences are scoped warnings, never numeric repairs."""

from datetime import date
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from deploy_vii.audit_basis import annual_warning
from deploy_vii.financial_contracts import AuditBasisExplanation, FinancialBook, FinancialReview
from deploy_vii.financial_reconciliation import (
    Reconciliation,
    ReconciliationReport,
    reconcile_financials,
    validate_reconciliation_report,
)
from deploy_vii.financial_validation import validate_financial_review
from deploy_vii.model_readiness import assess_model_readiness, validate_model_readiness
from deploy_vii.period_reconciliation import (
    PeriodCheck,
    PeriodReconciliationReport,
    reconcile_periods,
    validate_period_reconciliation,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.statement_validation import effective_accounts
from tests.product.test_cash_bridge import ncf_amount
from tests.product.test_financial_periods import frozen as freeze_case
from tests.product.test_financials import _C, conflict
from tests.product.test_model_readiness import ready_case
from tests.product.test_reconciliation import accounts


def frozen(value: FinancialBook) -> tuple[PreparedPack, FinancialReview]:
    # The existing synthetic freezer replaces placeholder source hashes. Rebind
    # only fingerprints of unchanged observations; intentionally stale ones stay stale.
    pack, review = freeze_case(value)
    frozen_book = review.books[0]
    hashes = {
        before.value.content_hash(): after.value.content_hash()
        for before, after in zip(
            effective_accounts(value), effective_accounts(frozen_book), strict=True
        )
    }
    explanations = tuple(
        item.model_copy(
            update={
                "annual_observation_sha256": hashes.get(
                    item.annual_observation_sha256, item.annual_observation_sha256
                ),
                "quarter_observation_sha256": tuple(
                    hashes.get(h, h) for h in item.quarter_observation_sha256
                ),
            }
        )
        for item in frozen_book.audit_basis_explanations
    )
    return pack, review.model_copy(
        update={
            "books": (frozen_book.model_copy(update={"audit_basis_explanations": explanations}),)
        }
    )


def explain(value: FinancialBook, metric: str = "cash_interest_paid") -> FinancialBook:
    rows = {(r.period_id, r.metric_id): r.value for r in effective_accounts(value)}
    quarters = ("Q1", "Q2", "Q3", "Q4")
    item = AuditBasisExplanation(
        explanation_id="audit." + metric,
        annual_period_id="FY",
        metric_id=metric,
        quarter_period_ids=quarters,
        annual_observation_sha256=rows["FY", metric].content_hash(),
        quarter_observation_sha256=tuple(rows[pid, metric].content_hash() for pid in quarters),
        explanation="Synthetic year-end audit reclassification versus unaudited quarters",
        citations=(_C,),
    )
    return value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"audit_status": "AUDITED"}) if p.period_id == "FY" else p
                for p in value.periods
            ),
            "audit_basis_explanations": (*value.audit_basis_explanations, item),
        }
    )


def differing() -> FinancialBook:
    return accounts(ready_case(), "FY", cash_interest_paid="-21.00")


def annual_checks(
    pack: PreparedPack, review: FinancialReview, book_id: str, metric: str = "cash_interest_paid"
) -> tuple[
    ReconciliationReport, PeriodReconciliationReport, tuple[Reconciliation | PeriodCheck, ...]
]:
    source = reconcile_financials(pack, review, book_id)
    periods = reconcile_periods(pack, review, book_id)
    rows = tuple(
        next(c for c in report.checks if c.check_type == "FY_QUARTERS" and c.metric_id == metric)
        for report in (source, periods)
    )
    return source, periods, rows


def test_explicit_explanation_warns_without_changing_values_or_readiness_requirements() -> None:
    value = differing()
    pack, review = frozen(value)
    _, _, before = annual_checks(pack, review, value.book_id)
    assert all(row.status == "BLOCK" and row.difference == 1 for row in before)
    assert assess_model_readiness(pack, review, value.book_id).readiness.status == "blocked"
    value = explain(value)
    pack, review = frozen(value)
    source, periods, after = annual_checks(pack, review, value.book_id)
    for original, row in zip(before, after, strict=True):
        assert row.status == "WARN" and row.difference == 1
        assert row.calculated_value == -20 and row.reported.amount == -21
        assert row.reported == original.reported and row.components == original.components
        assert row.tolerance == original.tolerance
        assert row.audit_basis_explanation == review.books[0].audit_basis_explanations[0]
        assert set(row.audit_basis_explanation.citations) <= set(row.context_citations)
    ready = assess_model_readiness(pack, review, value.book_id)
    assert ready.readiness.status == "ready", ready.readiness.findings
    assert any("Audited FY" in f.explanation for f in ready.readiness.findings)
    assert validate_reconciliation_report(pack, review, source) == ()
    assert validate_period_reconciliation(pack, review, periods) == ()
    assert validate_model_readiness(pack, review, ready) == ()
    assert source.schema_version == "financial-reconciliation/4"
    assert periods.schema_version == "period-reconciliation/4"
    assert review.schema_version == "financial-review/3"


def test_explanation_is_not_a_blanket_metric_or_cash_override() -> None:
    value = explain(accounts(differing(), "FY", cash_taxes_paid="-22.00"))
    pack, review = frozen(value)
    _, _, rows = annual_checks(pack, review, value.book_id, "cash_taxes_paid")
    assert all(row.status == "BLOCK" and row.audit_basis_explanation is None for row in rows)
    assert assess_model_readiness(pack, review, value.book_id).readiness.status == "blocked"
    value = explain(ncf_amount(ready_case(), "FY", "81.00"), "net_cash_change")
    pack, review = frozen(value)
    source = reconcile_financials(pack, review, value.book_id)
    cash = next(
        c for c in source.checks if c.period_id == "FY" and c.check_type == "NCF_CASH_MOVEMENT"
    )
    assert cash.status == "BLOCK" and cash.audit_basis_explanation is None


@pytest.mark.parametrize("state", ["missing", "conflicting"])
def test_explanation_cannot_promote_missing_or_conflicting_inputs(state: str) -> None:
    value = accounts(differing(), "Q2", cash_interest_paid=None)
    if state == "conflicting":
        value = value.model_copy(
            update={
                "accounts": tuple(
                    r.model_copy(update={"value": conflict(r.value.observation_id)})
                    if r.period_id == "Q2" and r.metric_id == "cash_interest_paid"
                    else r
                    for r in value.accounts
                )
            }
        )
    value = explain(value)
    pack, review = frozen(value)
    _, _, rows = annual_checks(pack, review, value.book_id)
    assert all(
        c.status == "BLOCK" and c.difference is None and c.audit_basis_explanation is None
        for c in rows
    )
    assert assess_model_readiness(pack, review, value.book_id).readiness.status == "blocked"


@pytest.mark.parametrize(
    "change",
    [
        "annual",
        "quarter",
        "duplicate",
        "scope",
        "order",
        "metric",
        "gap",
        "derived",
        "basis",
        "annual_basis",
        "stale",
        "quote",
    ],
)
def test_malformed_scope_or_stale_evidence_is_refused_before_calculation(change: str) -> None:
    value = explain(differing())
    item = value.audit_basis_explanations[0]
    if change == "annual":
        item = item.model_copy(update={"annual_period_id": "unknown"})
    elif change == "quarter":
        item = item.model_copy(update={"quarter_period_ids": ("Q1", "Q2", "Q3", "unknown")})
    elif change == "scope":
        item = item.model_copy(update={"quarter_period_ids": ("Q1", "Q2", "Q3", "Q3")})
    elif change == "order":
        item = item.model_copy(update={"quarter_period_ids": ("Q4", "Q3", "Q2", "Q1")})
    elif change == "metric":
        item = item.model_copy(update={"metric_id": "total_debt"})
    elif change in {"gap", "derived", "basis", "annual_basis"}:
        updates = (
            {"start_date": date(2025, 4, 2)}
            if change == "gap"
            else (
                {"component_period_ids": ("Q1",)}
                if change == "derived"
                else {"audit_status": "UNKNOWN"}
            )
        )
        value = value.model_copy(
            update={
                "periods": tuple(
                    p.model_copy(update=updates)
                    if p.period_id == ("FY" if change == "annual_basis" else "Q2")
                    else p
                    for p in value.periods
                )
            }
        )
    elif change == "stale":
        value = accounts(value, "FY", cash_interest_paid="-100.00")
    elif change == "quote":
        item = item.model_copy(
            update={"citations": (_C.model_copy(update={"quote": "Not in pack"}),)}
        )
    value = value.model_copy(
        update={"audit_basis_explanations": (item, item) if change == "duplicate" else (item,)}
    )
    pack, review = frozen(value)
    if change == "quote":
        # Freeze creates located synthetic evidence; tamper only after freezing.
        frozen_book = review.books[0]
        bound = frozen_book.audit_basis_explanations[0]
        broken = bound.model_copy(
            update={
                "citations": (
                    bound.citations[0].model_copy(update={"quote": "Tampered after freeze"}),
                )
            }
        )
        review = review.model_copy(
            update={
                "books": (frozen_book.model_copy(update={"audit_basis_explanations": (broken,)}),)
            }
        )
        assert any(
            "Quote/locator mismatch" in issue for issue in validate_financial_review(pack, review)
        )
    assert validate_financial_review(pack, review)
    with pytest.raises(ValueError):
        reconcile_financials(pack, review, value.book_id)
    with pytest.raises(ValueError):
        reconcile_periods(pack, review, value.book_id)


def test_matching_values_do_not_gain_an_exception_and_decimal_context_is_irrelevant() -> None:
    value = explain(ready_case())
    pack, review = frozen(value)
    _, _, rows = annual_checks(pack, review, value.book_id)
    assert all(c.status == "PASS" and c.audit_basis_explanation is None for c in rows)
    value = explain(differing())
    pack, review = frozen(value)
    baseline = reconcile_periods(pack, review, value.book_id)
    with localcontext() as ctx:
        ctx.prec = 2
        assert reconcile_periods(pack, review, value.book_id) == baseline
    assert (
        annual_warning(
            value,
            "FY",
            "cash_interest_paid",
            ("Q1", "Q2", "Q3", None),
            Decimal(1),
            Decimal("0.005"),
        )
        is None
    )
    assert (
        annual_warning(
            value, "FY", "cash_interest_paid", ("Q1", "Q2", "Q3", "Q4"), None, Decimal("0.005")
        )
        is None
    )


def test_report_tampering_and_old_explicit_schema_are_rejected() -> None:
    value = explain(differing())
    pack, review = frozen(value)
    source, periods, rows = annual_checks(pack, review, value.book_id)
    for report, validator, row in (
        (source, validate_reconciliation_report, rows[0]),
        (periods, validate_period_reconciliation, rows[1]),
    ):
        altered = report.model_copy(
            update={
                "checks": tuple(
                    c.model_copy(update={"audit_basis_explanation": None})
                    if c.check_id == row.check_id
                    else c
                    for c in report.checks
                )
            }
        )
        assert validator(pack, review, altered)
    with pytest.raises(ValidationError):
        FinancialReview.model_validate_json(
            review.model_dump_json().replace("financial-review/3", "financial-review/1")
        )
