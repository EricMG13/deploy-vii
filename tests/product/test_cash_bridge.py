"""Synthetic cash FX/perimeter bridges; no live analytical qualification."""

from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from deploy_vii.financial_contracts import CashMovementBridge, FinancialBook, FinancialReview
from deploy_vii.financial_reconciliation import (
    reconcile_financials,
    validate_reconciliation_report,
)
from deploy_vii.financial_validation import validate_financial_review
from deploy_vii.period_reconciliation import reconcile_periods, validate_period_reconciliation
from tests.product.test_financial_periods import frozen
from tests.product.test_financials import _C, conflict, observed
from tests.product.test_model_readiness import assess, ready_case
from tests.product.test_period_reconciliation import check as period_check
from tests.product.test_period_reconciliation import constructed_case, run
from tests.product.test_reconciliation import accounts
from tests.product.test_reconciliation import check as source_check
from tests.product.test_statements import identity, line


def bridge(pid: str, *parts: tuple[str, int]) -> CashMovementBridge:
    return CashMovementBridge.model_validate(
        {
            "bridge_id": "cash." + pid,
            "period_id": pid,
            "components": tuple({"line_id": name, "coefficient": sign} for name, sign in parts),
            "explanation": "Synthetic source: cash delta equals NCF plus listed adjustments",
            "citations": (_C,),
        }
    )


def ncf_amount(value: FinancialBook, pid: str, amount: str) -> FinancialBook:
    """Keep both synthetic representations aligned when varying the cash test."""
    value = accounts(value, pid, net_cash_change=amount)
    return value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(update={"value": observed(r.value.observation_id, amount)})
                if r.period_id == pid and r.item_id == "net_cash_change"
                else r
                for r in value.statement_lines
            )
        }
    )


def direct_case() -> FinancialBook:
    value = ready_case()
    # FX adds 2 to each quarter's cash delta, but is outside reported NCF.
    for pid, total in (("Q1", 22), ("Q2", 44), ("Q3", 66), ("Q4", 88), ("FY", 88)):
        value = accounts(value, pid, cash_and_equivalents=str(total))
    return value.model_copy(
        update={
            "statement_lines": (
                *value.statement_lines,
                *(
                    line("fx", "fx_cash_effect", "8" if p == "FY" else "2", 4, pid=p)
                    for p in ("Q1", "Q2", "Q3", "Q4", "FY")
                ),
            ),
            "cash_movement_bridges": tuple(
                bridge(pid, ("fx", 1)) for pid in ("Q1", "Q2", "Q3", "Q4", "FY")
            ),
        }
    )


def derived_case() -> FinancialBook:
    value = constructed_case()
    opening = next(p for p in ready_case().periods if p.period_id == "OPEN")
    value = accounts(
        value.model_copy(update={"periods": (*value.periods, opening)}),
        "OPEN",
        cash_and_equivalents="0",
    )
    for pid, n in (("Q1", 1), ("H1", 2), ("9M", 3), ("FY", 4)):
        value = accounts(value, pid, net_cash_change=str(20 * n), cash_and_equivalents=str(22 * n))
    return value.model_copy(
        update={
            "statement_lines": (
                *value.statement_lines,
                *(
                    line("fx", "fx_cash_effect", str(2 * n), 4, pid=pid)
                    for pid, n in (("Q1", 1), ("H1", 2), ("9M", 3), ("FY", 4))
                ),
            ),
            "cash_movement_bridges": tuple(
                bridge(pid, ("fx", 1)) for pid in ("Q1", "H1", "9M", "FY")
            ),
        }
    )


def test_explicit_fx_preserves_source_amounts_and_readiness() -> None:
    value = direct_case()
    row = source_check(value, "NCF_CASH_MOVEMENT")
    assert row.status == "PASS" and row.reported_value == row.calculated_value == 20
    assert [p.amount for p in row.components] == [44, 22, 2]
    assert [p.coefficient for p in row.components] == [1, -1, -1]
    assert row.components[-1].original_amount == 2
    assert row.components[-1].observation_id == "fx.Q2"
    assert row.cash_movement_bridges[0].bridge_id == "cash.Q2"
    assert row.context_citations and row.components[-1].citations
    assert assess(value).readiness.status == "ready"


def test_present_fx_line_does_not_implicitly_change_cash_or_double_count() -> None:
    value = direct_case().model_copy(update={"cash_movement_bridges": ()})
    row = source_check(value, "NCF_CASH_MOVEMENT")
    assert row.status == "BLOCK" and row.difference == 2
    assert row.cash_movement_bridges == ()
    # The alternative reporting convention already includes FX in NCF.
    value = ncf_amount(value, "Q2", "22")
    value = value.model_copy(update={"cash_movement_bridges": (bridge("Q2"),)})
    row = source_check(value, "NCF_CASH_MOVEMENT")
    assert row.status == "PASS" and len(row.components) == 2
    assert row.cash_movement_bridges[0].components == ()


@pytest.mark.parametrize("sign", [-1, 1])
def test_signed_perimeter_adjustment_and_explicit_outflow_convention(sign: int) -> None:
    value = ready_case()
    adjustment = line("restricted", "other:restricted_cash_movement", "3", 4).model_copy(
        update={"sign_convention": "outflow_magnitude", "sign_citations": (_C,)}
    )
    value = ncf_amount(value, "Q2", str(20 + sign * 3))
    value = value.model_copy(
        update={
            "statement_lines": (*value.statement_lines, adjustment),
            "cash_movement_bridges": (bridge("Q2", ("restricted", sign)),),
        }
    )
    row = source_check(value, "NCF_CASH_MOVEMENT")
    assert row.status == "PASS"
    assert row.components[-1].original_amount == 3
    assert row.components[-1].amount == -3
    assert row.components[-1].coefficient == -sign


@pytest.mark.parametrize("amount", ["0", "-2", "0.0000000001"])
def test_zero_negative_and_small_fx_are_exact_source_values(amount: str) -> None:
    value = ready_case()
    value = accounts(value, "Q2", cash_and_equivalents=str(Decimal(40) + Decimal(amount)))
    value = value.model_copy(
        update={
            "statement_lines": (*value.statement_lines, line("fx", "fx_cash_effect", amount, 4)),
            "cash_movement_bridges": (bridge("Q2", ("fx", 1)),),
        }
    )
    with localcontext() as context:
        context.prec = 1
        row = source_check(value, "NCF_CASH_MOVEMENT")
    assert row.status == "PASS" and row.difference == 0
    assert row.components[-1].amount == Decimal(amount)


@pytest.mark.parametrize("mode", ["missing", "conflicting", "wrong"])
def test_unknown_conflicting_or_wrong_adjustments_cannot_pass(mode: str) -> None:
    value = direct_case()
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(
                    update={
                        "value": conflict("fx.Q2")
                        if mode == "conflicting"
                        else observed("fx.Q2", None if mode == "missing" else "1")
                    }
                )
                if r.line_id == "fx" and r.period_id == "Q2"
                else r
                for r in value.statement_lines
            )
        }
    )
    row = source_check(value, "NCF_CASH_MOVEMENT")
    assert row.status == "BLOCK"
    assert row.difference == (1 if mode == "wrong" else None)
    assert assess(value).readiness.status == "blocked"


def test_constructed_quarters_and_ltm_keep_signed_adjustment_leaves() -> None:
    report = run(derived_case())
    row = period_check(report, "Q:H1-Q1", "NCF_CASH_MOVEMENT")
    assert row.status == "PASS" and row.independent
    assert row.reported.amount == row.calculated_value == 20
    assert [p.amount for p in row.components] == [44, 22, 4, 2]
    assert [p.coefficient for p in row.components] == [1, -1, -1, 1]
    assert [b.period_id for b in row.cash_movement_bridges] == ["H1", "Q1"]
    assert [p.observation_ids for p in row.components[2:]] == [("fx.H1",), ("fx.Q1",)]
    ltm = period_check(report, "LTM:FY", "NCF_CASH_MOVEMENT")
    assert ltm.status == "PASS" and ltm.calculated_value == 80


def test_equal_source_errors_cannot_cancel_in_constructed_cash_check() -> None:
    value = derived_case()
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(
                    update={"value": observed(r.value.observation_id, str(r.value.amount + 1))}
                )
                if r.line_id == "fx" and r.period_id in {"Q1", "H1"}
                else r
                for r in value.statement_lines
            )
        }
    )
    row = period_check(run(value), "Q:H1-Q1", "NCF_CASH_MOVEMENT")
    assert sum(p.amount * p.coefficient for p in row.components) == row.reported.amount
    assert row.status == "BLOCK" and row.calculated_value is None
    assert "H1" in row.explanation and "Q1" in row.explanation


def test_partial_assessment_is_not_a_zero_adjustment() -> None:
    value = derived_case()
    value = value.model_copy(
        update={
            "cash_movement_bridges": tuple(
                b for b in value.cash_movement_bridges if b.period_id != "Q1"
            )
        }
    )
    row = period_check(run(value), "Q:H1-Q1", "NCF_CASH_MOVEMENT")
    assert row.status == "BLOCK" and row.calculated_value is None
    assert "Unassessed cash bridge: Q1" in row.explanation
    assert row.components[-1].amount is None
    # An explicit empty assessment is allowed, but still must reconcile.
    value = accounts(value, "Q1", net_cash_change="22")
    value = value.model_copy(
        update={
            "cash_movement_bridges": (
                *value.cash_movement_bridges,
                bridge("Q1"),
            )
        }
    )
    row = period_check(run(value), "Q:H1-Q1", "NCF_CASH_MOVEMENT")
    assert row.status == "PASS" and row.calculated_value == 18


def test_unknown_adjustments_survive_opposite_signed_quarter_terms() -> None:
    value = derived_case()
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(update={"value": observed(r.value.observation_id, None)})
                if r.line_id == "fx" and r.period_id in {"Q1", "H1"}
                else r
                for r in value.statement_lines
            )
        }
    )
    row = period_check(run(value), "Q:H1-Q1", "NCF_CASH_MOVEMENT")
    unknowns = [p for p in row.components if p.observation_ids in {("fx.H1",), ("fx.Q1",)}]
    assert {p.coefficient for p in unknowns} == {-1, 1}
    assert all(p.amount is None and p.reason for p in unknowns)
    assert row.status == "BLOCK" and row.calculated_value is None


def test_missing_source_period_cannot_complete_adjusted_ltm() -> None:
    value = derived_case()
    keep = {"OPEN", "Q1", "H1"}
    value = value.model_copy(
        update={
            field: tuple(r for r in getattr(value, field) if r.period_id in keep)
            for field in (
                "periods",
                "accounts",
                "statement_lines",
                "statement_identities",
                "statement_disclosures",
                "cash_movement_bridges",
            )
        }
    )
    row = period_check(run(value), "LTM:H1", "NCF_CASH_MOVEMENT")
    assert row.status == "BLOCK" and row.calculated_value is None
    assert any(
        p.label == "Unassessed cash bridge: None" and p.amount is None for p in row.components
    )


@pytest.mark.parametrize(
    "mode",
    [
        "duplicate_id",
        "duplicate_period",
        "duplicate_line",
        "unknown",
        "period_end",
        "wrong_period",
        "subtotal",
        "canonical",
        "other_statement",
        "identity_target",
    ],
)
def test_invalid_bridges_are_rejected_at_public_boundary(mode: str) -> None:
    value = direct_case()
    item = bridge("Q2", ("fx", 1))
    if mode == "duplicate_id":
        bridges = (item, item.model_copy(update={"period_id": "Q1"}))
    elif mode == "duplicate_period":
        bridges = (item, item.model_copy(update={"bridge_id": "second"}))
    elif mode == "duplicate_line":
        bridges = (bridge("Q2", ("fx", 1), ("fx", -1)),)
    elif mode == "unknown":
        bridges = (bridge("unknown", ("fx", 1)),)
    elif mode == "period_end":
        bridges = (bridge("OPEN"),)
    elif mode == "wrong_period":
        bridges = (item,)
        value = value.model_copy(
            update={
                "statement_lines": tuple(
                    r
                    for r in value.statement_lines
                    if not (r.line_id == "fx" and r.period_id == "Q2")
                )
            }
        )
    elif mode == "identity_target":
        bridges = (item,)
        value = value.model_copy(
            update={
                "statement_identities": (
                    *value.statement_identities,
                    identity("fx", ("profit", 1)),
                )
            }
        )
    else:
        bridges = (item,)
        changes = {
            "subtotal": {"line_kind": "subtotal"},
            "canonical": {"item_id": "net_cash_change"},
            "other_statement": {"statement": "IS", "item_id": "other:fx"},
        }[mode]
        value = value.model_copy(
            update={
                "statement_lines": tuple(
                    r.model_copy(update=changes) if r.line_id == "fx" else r
                    for r in value.statement_lines
                )
            }
        )
    value = value.model_copy(update={"cash_movement_bridges": bridges})
    pack, review = frozen(value)
    issues = validate_financial_review(pack, review)
    assert any("cash" in issue.lower() for issue in issues)
    with pytest.raises(ValueError):
        reconcile_financials(pack, review, value.book_id)
    with pytest.raises(ValueError):
        reconcile_periods(pack, review, value.book_id)


def test_sources_and_report_are_bound_and_independent_of_decimal_context() -> None:
    pack, review = frozen(derived_case())
    book = review.books[0]
    source = reconcile_financials(pack, review, book.book_id)
    periods = reconcile_periods(pack, review, book.book_id)
    with localcontext() as context:
        context.prec = 2
        assert reconcile_financials(pack, review, book.book_id) == source
        assert reconcile_periods(pack, review, book.book_id) == periods
    assert validate_reconciliation_report(pack, review, source) == ()
    assert validate_period_reconciliation(pack, review, periods) == ()
    changed = book.model_copy(update={"cash_movement_bridges": ()})
    altered = review.model_copy(update={"books": (changed,)})
    assert validate_reconciliation_report(pack, altered, source)
    assert validate_period_reconciliation(pack, altered, periods)
    bad_bridge = book.cash_movement_bridges[0].model_copy(
        update={
            "citations": (
                book.cash_movement_bridges[0]
                .citations[0]
                .model_copy(update={"source_sha256": "0" * 64}),
            )
        }
    )
    changed = book.model_copy(update={"cash_movement_bridges": (bad_bridge,)})
    assert validate_financial_review(pack, review.model_copy(update={"books": (changed,)}))


def test_bridge_cannot_supply_a_numeric_plug_or_coerce_a_sign() -> None:
    data = bridge("Q2", ("fx", 1)).model_dump()
    with pytest.raises(ValidationError, match="Extra inputs"):
        CashMovementBridge.model_validate({**data, "amount": "2"})
    data["components"][0]["coefficient"] = True
    with pytest.raises(ValidationError, match="coefficient must be the integer"):
        CashMovementBridge.model_validate(data)
    _, review = frozen(direct_case())
    with pytest.raises(ValidationError):
        FinancialReview.model_validate_json(
            review.model_dump_json().replace("financial-review/3", "financial-review/2")
        )
