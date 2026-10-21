"""Synthetic Step 7 bridges: independent source values, no balancing residuals."""

from datetime import date
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from deploy_vii.balance_movement import balance_movement_issues
from deploy_vii.financial_contracts import BalanceMovement, BalanceMovementBridge, FinancialBook
from deploy_vii.financial_reconciliation import (
    Reconciliation,
    ReconciliationReport,
    reconcile_financials,
    validate_reconciliation_report,
)
from deploy_vii.financial_validation import validate_financial_review
from deploy_vii.model.history import BALANCE_METRICS
from tests.product.test_canonical_gaps import case
from tests.product.test_financial_periods import frozen
from tests.product.test_financials import _C, conflict, observed
from tests.product.test_model_readiness import assess, ready_case
from tests.product.test_statements import line


def bridge_case() -> FinancialBook:
    value = ready_case()
    # Q2 equity: opening 140 + income 40 - distributions 10 + OCI 5 = 175.
    movements = (
        BalanceMovement(
            movement_id="distribution",
            label="Declared distributions",
            period_id="Q2",
            role="distribution",
            value=observed("movement.distribution", "10.00"),
            sign_convention="outflow_magnitude",
            sign_citations=(_C,),
        ),
        BalanceMovement(
            movement_id="oci",
            label="Other comprehensive income",
            period_id="Q2",
            role="oci",
            value=observed("movement.oci", "5.00"),
        ),
    )
    return value.model_copy(
        update={
            "balance_movements": movements,
            "balance_movement_bridges": tuple(
                b.model_copy(update={"movement_ids": ("distribution", "oci")})
                if b.period_id == "Q2"
                else b
                for b in value.balance_movement_bridges
            ),
            "statement_lines": tuple(
                r.model_copy(update={"value": observed(r.value.observation_id, "175.00")})
                if r.statement == "BS" and r.period_id == "Q2"
                else r
                for r in value.statement_lines
            ),
        }
    )


def result(value: FinancialBook) -> ReconciliationReport:
    pack, review = frozen(value)
    return reconcile_financials(pack, review, value.book_id)


def equity(value: FinancialBook, pid: str = "Q2") -> Reconciliation:
    return next(
        c
        for c in result(value).checks
        if c.check_type == "BALANCE_MOVEMENT"
        and c.period_id == pid
        and c.metric_id == "total_equity"
    )


def test_equity_bridge_keeps_original_signs_sources_and_independent_difference() -> None:
    row = equity(bridge_case())
    assert row.status == "PASS" and row.reported_value == row.calculated_value == 175
    assert [c.amount for c in row.components] == [140, 40, -10, 5]
    assert row.components[2].original_amount == 10 and row.components[2].citations
    assert row.balance_movement_bridge and row.context_citations
    value = bridge_case()
    value = value.model_copy(
        update={
            "statement_lines": tuple(
                r.model_copy(update={"value": observed(r.value.observation_id, "174.99")})
                if r.statement == "BS" and r.period_id == "Q2"
                else r
                for r in value.statement_lines
            )
        }
    )
    row = equity(value)
    assert row.status == "BLOCK" and row.difference == Decimal("0.01")
    assert row.reported_value == Decimal("174.99") and row.calculated_value == 175


@pytest.mark.parametrize(
    "missing", ["opening", "closing", "income", "bridge", "movement", "partial", "dates"]
)
def test_missing_or_incomplete_support_never_implies_zero_movements(missing: str) -> None:
    value = bridge_case()
    if missing in {"opening", "closing", "income"}:
        value = value.model_copy(
            update={
                "statement_lines": tuple(
                    r
                    for r in value.statement_lines
                    if not (
                        (
                            r.statement == "BS"
                            and r.period_id == ("Q1" if missing == "opening" else "Q2")
                        )
                        if missing != "income"
                        else (r.statement == "IS" and r.period_id == "Q2")
                    )
                )
            }
        )
    elif missing == "bridge":
        value = ready_case().model_copy(update={"balance_movement_bridges": ()})
    elif missing == "movement":
        value = value.model_copy(
            update={
                "balance_movements": (
                    value.balance_movements[0].model_copy(
                        update={"value": observed("movement.distribution", None)}
                    ),
                    value.balance_movements[1],
                )
            }
        )
    elif missing == "partial":
        value = value.model_copy(
            update={
                "balance_movement_bridges": tuple(
                    b.model_copy(
                        update={"disclosure": b.disclosure.model_copy(update={"status": "partial"})}
                    )
                    if b.period_id == "Q2"
                    else b
                    for b in value.balance_movement_bridges
                )
            }
        )
    else:
        value = value.model_copy(
            update={
                "periods": tuple(
                    p.model_copy(update={"start_date": None, "limitation": "Not supplied"})
                    if p.period_id == "Q2"
                    else p
                    for p in value.periods
                )
            }
        )
    row = equity(value)
    assert row.status == "BLOCK" and row.difference is None
    assert row.calculated_value is None or missing == "closing"


def test_source_failures_cannot_cancel_through_derived_quarters_or_missing_support() -> None:
    value = ready_case()
    report = assess(value.model_copy(update={"balance_movement_bridges": ()}))
    assert report.readiness.status == "blocked"
    failed = [c for c in report.source_reconciliation.checks if c.check_type == "BALANCE_MOVEMENT"]
    assert failed and all(c.status == "BLOCK" and c.calculated_value is None for c in failed)
    assert {c.check_id for c in failed if c.period_id != "FY"} <= set(
        report.readiness.mandatory_check_ids
    )
    assert assess(ready_case()).readiness.status == "ready"


def test_optional_other_balance_bridge_uses_exact_dates_and_no_income_component() -> None:
    value = ready_case()
    movement = BalanceMovement(
        movement_id="ppe.flow",
        label="Net PPE movement",
        period_id="Q2",
        role="period_flow",
        value=observed("movement.ppe", "-4.00"),
    )
    bridge = BalanceMovementBridge(
        bridge_id="ppe.Q2",
        period_id="Q2",
        balance_item_id="ppe_net",
        movement_ids=(movement.movement_id,),
        disclosure=value.addback_disclosure,
    )
    value = value.model_copy(
        update={
            "balance_movements": (movement,),
            "balance_movement_bridges": (*value.balance_movement_bridges, bridge),
            "statement_lines": (
                *value.statement_lines,
                line("ppe", "ppe_net", "20.00", 2, statement="BS", pid="Q1"),
                line("ppe", "ppe_net", "16.00", 2, statement="BS", pid="Q2"),
            ),
        }
    )
    row = next(c for c in result(value).checks if c.metric_id == "ppe_net")
    assert row.status == "PASS" and len(row.components) == 2
    assert row.balance_movement_bridge
    assert row.balance_movement_bridge.movement_ids == bridge.movement_ids


def test_same_date_conflict_is_not_selected_away_and_all_evidence_is_retained() -> None:
    value = ready_case()
    alias = next(p for p in value.periods if p.period_id == "Q1").model_copy(
        update={"period_id": "END", "period_type": "PERIOD_END"}
    )
    source = line(
        "equity", "total_equity", "140.00", 1, statement="BS", kind="total", pid="END"
    ).model_copy(update={"value": conflict("alias.equity")})
    value = value.model_copy(
        update={
            "periods": (*value.periods, alias),
            "statement_lines": (*value.statement_lines, source),
        }
    )
    row = equity(value)
    assert row.status == "BLOCK" and row.components[0].amount is None
    assert row.components[0].observation_id == "alias.equity"
    assert row.components[0].citations


@pytest.mark.parametrize(
    "mode",
    [
        "duplicate_row",
        "duplicate_bridge",
        "duplicate_ref",
        "unknown_ref",
        "wrong_period",
        "instant",
        "unknown_item",
        "unassigned",
        "undisclosed",
    ],
)
def test_invalid_bridge_references_fail_at_boundary(mode: str) -> None:
    value = bridge_case()
    bridge = next(b for b in value.balance_movement_bridges if b.period_id == "Q2")
    row = value.balance_movements[0]
    if mode == "duplicate_row":
        value = value.model_copy(update={"balance_movements": (*value.balance_movements, row)})
    elif mode == "duplicate_bridge":
        value = value.model_copy(
            update={"balance_movement_bridges": (*value.balance_movement_bridges, bridge)}
        )
    elif mode == "unassigned":
        value = value.model_copy(
            update={
                "balance_movements": (
                    *value.balance_movements,
                    row.model_copy(
                        update={"movement_id": "unassigned", "value": observed("unassigned", "1")}
                    ),
                )
            }
        )
    else:
        update = (
            {"movement_ids": ("distribution", "distribution")}
            if mode == "duplicate_ref"
            else {"movement_ids": ("unknown",)}
            if mode == "unknown_ref"
            else {"period_id": "bad"}
            if mode == "wrong_period"
            else {"period_id": "OPEN"}
            if mode == "instant"
            else {"balance_item_id": "revenue"}
            if mode == "unknown_item"
            else {"disclosure": bridge.disclosure.model_copy(update={"status": "not_disclosed"})}
        )
        value = value.model_copy(
            update={
                "balance_movement_bridges": tuple(
                    b.model_copy(update=update) if b == bridge else b
                    for b in value.balance_movement_bridges
                )
            }
        )
    assert balance_movement_issues(value)
    pack, review = frozen(value)
    assert validate_financial_review(pack, review)
    with pytest.raises(ValueError):
        reconcile_financials(pack, review, value.book_id)


def test_sign_and_observation_evidence_is_required() -> None:
    with pytest.raises(ValidationError, match="normalization requires source evidence"):
        BalanceMovement(
            movement_id="dividend",
            label="Dividend",
            period_id="Q2",
            role="distribution",
            value=observed("dividend", "10"),
            sign_convention="outflow_magnitude",
        )
    value = bridge_case()
    pack, review = frozen(value)
    value = review.books[0]
    movement = value.balance_movements[0].model_copy(
        update={"value": value.balance_movements[0].value.model_copy(update={"citations": ()})}
    )
    value = value.model_copy(update={"balance_movements": (movement, value.balance_movements[1])})
    review = review.model_copy(update={"books": (value,)})
    assert validate_financial_review(pack, review)


def test_arithmetic_precision_recomputation_and_input_immutability() -> None:
    value = bridge_case()
    pack, review = frozen(value)
    before = review.model_dump_json()
    report = reconcile_financials(pack, review, value.book_id)
    with localcontext() as context:
        context.prec = 4
        assert reconcile_financials(pack, review, value.book_id) == report
    assert review.model_dump_json() == before
    assert validate_reconciliation_report(pack, review, report) == ()
    checks = tuple(
        c.model_copy(update={"calculated_value": Decimal(999)})
        if c.check_type == "BALANCE_MOVEMENT"
        else c
        for c in report.checks
    )
    assert validate_reconciliation_report(
        pack, review, report.model_copy(update={"checks": checks})
    )


def test_adjustments_enter_audit_context_binding_normalization_and_gap_ledger() -> None:
    from deploy_vii.canonical_gaps import canonical_gaps

    args = case(bridge_case())
    report = canonical_gaps(*args)
    positions = report.audit.source_positions
    assert any(
        p.register_id == "balance_movements"
        and p.observation.observation_id == "movement.distribution"
        for p in positions
    )
    assert any(
        n.observation_id == "movement.distribution" and n.before == 10 and n.after == -10
        for n in report.audit.normalizations
    )
    # Q3 still closes at 220 despite the lower Q2 equity: the unexplained +5 stays a gap.
    failed = equity(bridge_case(), "Q3")
    assert failed.status == "BLOCK" and failed.difference == -5
    assert any(g.metric == failed.check_id and g.severity == "BLOCK" for g in report.gaps)


def test_reused_movement_id_cannot_change_its_semantic_role() -> None:
    value = bridge_case()
    row = value.balance_movements[0].model_copy(
        update={"period_id": "Q3", "role": "oci", "value": observed("changed.role", "10")}
    )
    value = value.model_copy(
        update={
            "balance_movements": (*value.balance_movements, row),
            "balance_movement_bridges": tuple(
                b.model_copy(update={"movement_ids": ("distribution",)})
                if b.period_id == "Q3"
                else b
                for b in value.balance_movement_bridges
            ),
        }
    )
    pack, review = frozen(value)
    assert validate_financial_review(pack, review)


def test_derived_quarter_requires_its_annual_source_bridge() -> None:
    value = ready_case()
    updates = {
        key: tuple(r for r in getattr(value, key) if r.period_id != "Q4")
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
    # The reviewed kernel derives discrete quarters from YTD operands.
    for key, values in updates.items():
        changed = []
        for row in values:
            if row.period_id in {"Q2", "Q3"}:
                scale = int(row.period_id[-1])
                if key == "periods":
                    row = row.model_copy(
                        update={"period_type": "YTD", "start_date": date(2025, 1, 1)}
                    )
                elif (
                    key == "accounts"
                    and row.metric_id not in BALANCE_METRICS | {"effective_tax_rate"}
                ) or (key == "statement_lines" and row.statement != "BS"):
                    row = row.model_copy(
                        update={
                            "value": observed(
                                row.value.observation_id, str(row.value.amount * scale)
                            )
                        }
                    )
            changed.append(row)
        updates[key] = tuple(changed)
    value = value.model_copy(update=updates)
    assert assess(value).readiness.status == "ready"
    value = value.model_copy(
        update={
            "balance_movement_bridges": tuple(
                b for b in value.balance_movement_bridges if b.period_id != "FY"
            )
        }
    )
    report = assess(value)
    assert report.readiness.status == "blocked"
    row = next(
        c
        for c in report.source_reconciliation.checks
        if c.period_id == "FY" and c.check_type == "BALANCE_MOVEMENT"
    )
    assert row.status == "BLOCK" and row.check_id in report.readiness.mandatory_check_ids


def test_cross_bridge_expansion_is_bounded_before_arithmetic() -> None:
    value = bridge_case()
    template = value.balance_movements[0]
    rows = tuple(
        template.model_copy(update={"movement_id": f"m{i}", "value": observed(f"o{i}", "1")})
        for i in range(10001)
    )
    bridge = next(b for b in value.balance_movement_bridges if b.period_id == "Q2")
    bridge = bridge.model_copy(update={"movement_ids": tuple(r.movement_id for r in rows)})
    value = value.model_copy(
        update={
            "balance_movements": rows,
            "balance_movement_bridges": (
                bridge,
                bridge.model_copy(update={"bridge_id": "other", "balance_item_id": "ppe_net"}),
            ),
        }
    )
    assert balance_movement_issues(value) == ()
    with pytest.raises(ValidationError, match="Expanded balance movements exceed 20000 terms"):
        FinancialBook.model_validate_json(value.model_dump_json())


def test_earliest_date_cannot_underflow_or_pick_a_later_opening_balance() -> None:
    from deploy_vii.financial_reconciliation import _balance_movements

    value = ready_case()
    period = next(p for p in value.periods if p.period_id == "Q2")
    period = period.model_copy(update={"start_date": date.min})
    row = _balance_movements(value, period)[0]
    assert row.status == "BLOCK" and row.calculated_value is None
    assert row.components[0].amount is None
