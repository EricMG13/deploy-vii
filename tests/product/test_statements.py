"""Synthetic full-statement coverage and independent arithmetic regressions."""

from decimal import Decimal, localcontext

import pytest

from deploy_vii.financial_adapter import kernel_registers
from deploy_vii.financial_contracts import (
    FinancialBook,
    StatementDisclosure,
    StatementIdentity,
    StatementLine,
)
from deploy_vii.financial_reconciliation import Reconciliation, reconcile_financials
from deploy_vii.financial_validation import validate_financial_review
from deploy_vii.statement_output import statement_report, validate_statement_report
from deploy_vii.statement_validation import REQUIRED_ITEMS, effective_accounts, statement_issues
from tests.product.test_financials import _C, book, conflict, freeze, observed


def line(
    name: str,
    item: str,
    amount: str | None,
    priority: int,
    *,
    statement: str = "CFS",
    kind: str = "detail",
    pid: str = "Q2",
) -> StatementLine:
    return StatementLine.model_validate(
        {
            "line_id": name,
            "statement": statement,
            "item_id": item,
            "label": "Synthetic " + name,
            "period_id": pid,
            "display_priority": priority,
            "line_kind": kind,
            "value": observed(name + "." + pid, amount),
        }
    )


def identity(target: str, *components: tuple[str, int], pid: str = "Q2") -> StatementIdentity:
    return StatementIdentity.model_validate(
        {
            "identity_id": "identity." + pid + "." + target,
            "period_id": pid,
            "target_line_id": target,
            "components": tuple(
                {"line_id": name, "coefficient": sign} for name, sign in components
            ),
            "explanation": "Synthetic source equation",
            "citations": (_C,),
        }
    )


def statements() -> FinancialBook:
    value = book()
    return value.model_copy(
        update={
            "statement_lines": (
                line("cfo", "cfo_ncfo", "60", 1, kind="total"),
                line("net_income", "net_income", "40", 2),
                line("depreciation", "other:depreciation", "25", 3),
                line("working_capital", "working_capital_change", "-5", 4),
            ),
            "accounts": tuple(
                a
                for a in value.accounts
                if not (a.period_id == "Q2" and a.metric_id == "working_capital_change")
            ),
            "statement_identities": (
                identity("cfo", ("net_income", 1), ("depreciation", 1), ("working_capital", 1)),
            ),
            "statement_disclosures": (
                StatementDisclosure(
                    statement="CFS",
                    period_id="Q2",
                    disclosure=value.addback_disclosure.model_copy(
                        update={"explanation": "Complete source operating statement"}
                    ),
                ),
            ),
        }
    )


def cfo(value: FinancialBook) -> Reconciliation:
    pack, review = freeze(value)
    return next(
        c
        for c in reconcile_financials(pack, review, value.book_id).checks
        if c.period_id == "Q2" and c.check_type == "CFO_IDENTITY"
    )


def test_independent_cfo_components_replace_the_residual_placeholder() -> None:
    row = cfo(statements())
    assert row.status == "PASS"
    assert row.reported_value == row.calculated_value == 60
    assert row.difference == 0
    assert [t.observation_id for t in row.components] == [
        "net_income.Q2",
        "depreciation.Q2",
        "working_capital.Q2",
    ]
    assert "residual" not in row.formula
    value = statements()
    changed = value.statement_lines[1].model_copy(update={"value": observed("net_income.Q2", "41")})
    value = value.model_copy(
        update={"statement_lines": (value.statement_lines[0], changed, *value.statement_lines[2:])}
    )
    assert cfo(value).status == "BLOCK"
    assert cfo(value).difference == 1


@pytest.mark.parametrize("change", ["missing", "incomplete", "no_identity", "no_disclosure"])
def test_cfo_does_not_pass_incomplete_or_unknown_components(change: str) -> None:
    value = statements()
    if change == "missing":
        changed = value.statement_lines[1].model_copy(
            update={"value": observed("net_income.Q2", None)}
        )
        value = value.model_copy(
            update={
                "statement_lines": (value.statement_lines[0], changed, *value.statement_lines[2:])
            }
        )
    elif change == "incomplete":
        disclosure = value.statement_disclosures[0]
        value = value.model_copy(
            update={
                "statement_disclosures": (
                    disclosure.model_copy(
                        update={
                            "disclosure": disclosure.disclosure.model_copy(
                                update={"status": "partial"}
                            )
                        }
                    ),
                )
            }
        )
    elif change == "no_identity":
        value = value.model_copy(update={"statement_identities": ()})
    else:
        value = value.model_copy(update={"statement_disclosures": ()})
    row = cfo(value)
    assert row.status == "BLOCK"
    assert row.calculated_value is None


def test_full_coverage_keeps_all_required_missing_and_additional_source_rows() -> None:
    value = statements()
    pack, review = freeze(value)
    report = statement_report(pack, review, value.book_id)
    assert report.review_sha256 == review.content_hash()
    assert report.pack_sha256 == pack.content_hash()
    for statement, items in REQUIRED_ITEMS.items():
        for period in value.periods:
            rows = [
                r
                for r in report.cells
                if r.statement == statement and r.period_id == period.period_id
            ]
            assert set(items) <= {r.item_id for r in rows}
    rows = [r for r in report.cells if r.statement == "CFS" and r.period_id == "Q2"]
    assert [r.line_id for r in rows[:4]] == [r.line_id for r in value.statement_lines]
    absent = next(r for r in rows if r.item_id == "capex_growth")
    assert absent.status == "missing"
    assert absent.normalized_amount is absent.source_amount is None
    assert absent.limitation
    assert validate_statement_report(pack, review, report) == ()
    assert validate_statement_report(pack, review, report.model_copy(update={"cells": ()}))
    assert validate_statement_report(pack, review, report.model_copy(update={"book_id": "unknown"}))
    with pytest.raises(ValueError, match="Unknown financial book"):
        statement_report(pack, review, "unknown")
    with pytest.raises(ValueError, match="identity mismatch"):
        statement_report(pack, review.model_copy(update={"issuer_id": "wrong"}), value.book_id)


def test_sign_normalization_keeps_source_amount_and_separate_normalization_ref() -> None:
    value = statements()
    capex = line("capex", "capex_total", "12345678.1234567890", 5)
    value = value.model_copy(update={"statement_lines": (*value.statement_lines, capex)})
    pack, review = freeze(value)
    report = statement_report(pack, review, value.book_id)
    row = next(r for r in report.cells if r.line_id == "capex")
    assert row.source_amount == Decimal("12345678.1234567890")
    assert row.normalized_amount == Decimal("-12345678.1234567890")
    assert row.value_class == "normalized"
    assert row.normalization_id and row.citations
    with localcontext() as context:
        context.prec = 3
        assert statement_report(pack, review, value.book_id) == report
    # Do not confuse IS cash expense with CFS cash paid or use source equations
    # to invent compact-model numeric observations.
    cash_expense = line("cash_expense", "interest_expense_cash", "9", 1, statement="IS")
    value = value.model_copy(update={"statement_lines": (*value.statement_lines, cash_expense)})
    assert all(a.value.observation_id != "cash_expense.Q2" for a in effective_accounts(value))


def test_source_statement_can_fill_absent_but_not_explicit_unknown_accounts() -> None:
    value = statements()
    value = value.model_copy(
        update={
            "accounts": tuple(
                a for a in value.accounts if not (a.metric_id == "cfo_ncfo" and a.period_id == "Q2")
            )
        }
    )
    pack, review = freeze(value)
    regs = kernel_registers(pack, review, value.book_id)
    row = next(r for r in regs.accounts if r.metric_id == "cfo_ncfo" and r.period_id == "Q2")
    assert row.value == 60
    assert row.source and row.source.source_id == "cfo.Q2"
    original = (
        book()
        .accounts[0]
        .model_copy(
            update={
                "metric_id": "cfo_ncfo",
                "period_id": "Q2",
                "value": observed("explicit.missing", None),
            }
        )
    )
    value = value.model_copy(update={"accounts": (*value.accounts, original)})
    pack, review = freeze(value)
    regs = kernel_registers(pack, review, value.book_id)
    row = next(r for r in regs.accounts if r.metric_id == "cfo_ncfo" and r.period_id == "Q2")
    assert row.value is None


@pytest.mark.parametrize(
    "change,expected",
    [
        ("cycle", "Cyclic"),
        ("duplicate", "Duplicate statement identity component"),
        ("unknown", "Unknown statement identity line"),
        ("cross_statement", "mixes statements"),
        ("detail_target", "subtotal or total"),
        ("same_target", "Duplicate statement identity target"),
    ],
)
def test_identity_structure_refuses_invalid_equations(change: str, expected: str) -> None:
    value = statements()
    if change == "cycle":
        identities = (identity("cfo", ("cfo", 1)),)
        value = value.model_copy(update={"statement_identities": identities})
    elif change == "duplicate":
        value = value.model_copy(
            update={
                "statement_identities": (identity("cfo", ("net_income", 1), ("net_income", 1)),)
            }
        )
    elif change == "unknown":
        value = value.model_copy(update={"statement_identities": (identity("cfo", ("absent", 1)),)})
    elif change == "cross_statement":
        changed = value.statement_lines[1].model_copy(update={"statement": "IS"})
        value = value.model_copy(
            update={
                "statement_lines": (value.statement_lines[0], changed, *value.statement_lines[2:])
            }
        )
    elif change == "detail_target":
        changed = value.statement_lines[0].model_copy(update={"line_kind": "detail"})
        value = value.model_copy(update={"statement_lines": (changed, *value.statement_lines[1:])})
    else:
        value = value.model_copy(update={"statement_identities": value.statement_identities * 2})
    assert any(expected in issue for issue in statement_issues(value))


def test_overlapping_sums_reject_double_counting_but_allow_explicit_netting() -> None:
    value = statements()
    subtotal = line("subtotal", "other:subtotal", "65", 5, kind="subtotal")
    value = value.model_copy(
        update={
            "statement_lines": (*value.statement_lines, subtotal),
            "statement_identities": (
                identity("subtotal", ("net_income", 1), ("depreciation", 1)),
                identity("cfo", ("subtotal", 1), ("depreciation", 1)),
            ),
        }
    )
    assert any("Overlapping" in issue for issue in statement_issues(value))
    # Taking D&A back out of an explicitly sourced subtotal is valid netting,
    # and must not be mistaken for additive double-counting.
    value = value.model_copy(
        update={
            "statement_identities": (
                value.statement_identities[0],
                identity("cfo", ("subtotal", 1), ("depreciation", -1)),
            )
        }
    )
    assert statement_issues(value) == ()


def test_full_statement_cannot_bypass_compact_account_safety_guards() -> None:
    value = statements()
    conflict_row = value.statement_lines[0].model_copy(update={"value": conflict("cfo.Q2")})
    value = value.model_copy(update={"statement_lines": (conflict_row, *value.statement_lines[1:])})
    pack, review = freeze(value)
    assert any("conflict" in issue.lower() for issue in validate_financial_review(pack, review))
    value = statements()
    cogs = line("cogs", "cogs", "30", 1, statement="IS")
    value = value.model_copy(
        update={
            "statement_lines": (*value.statement_lines, cogs),
            "accounts": tuple(a for a in value.accounts if a.metric_id != "cogs"),
            "periods": tuple(
                p.model_copy(update={"expense_presentation": "by_nature"}) for p in value.periods
            ),
        }
    )
    pack, review = freeze(value)
    assert any("COGS" in issue for issue in validate_financial_review(pack, review))


def test_nested_subtotal_cannot_conceal_wrong_cfo_or_erase_missing_leaf() -> None:
    value = statements()
    subtotal = line("subtotal", "other:subtotal", "65", 5, kind="subtotal")
    value = value.model_copy(
        update={
            "statement_lines": (*value.statement_lines, subtotal),
            "statement_identities": (
                identity("subtotal", ("net_income", 1), ("depreciation", 1)),
                identity("cfo", ("subtotal", 1), ("working_capital", 1)),
            ),
        }
    )
    assert cfo(value).calculated_value == 60
    # Reported subtotal changed to a plug, but its leaf inputs still sum to 65.
    wrong = subtotal.model_copy(update={"value": observed("subtotal.Q2", "75")})
    value = value.model_copy(update={"statement_lines": (*value.statement_lines[:-1], wrong)})
    pack, review = freeze(value)
    report = reconcile_financials(pack, review, value.book_id)
    assert (
        next(
            c
            for c in report.checks
            if c.check_type == "SOURCE_STATEMENT_IDENTITY" and c.metric_id == "CFS:other:subtotal"
        ).status
        == "BLOCK"
    )
    assert cfo(value).calculated_value == 60
    assert "subtotal" not in cfo(value).formula
    # Opposite-signed missing D&A operands must not turn into a known zero.
    missing = value.statement_lines[2].model_copy(
        update={"value": observed("depreciation.Q2", None)}
    )
    value = value.model_copy(
        update={
            "statement_lines": (*value.statement_lines[:2], missing, *value.statement_lines[3:]),
            "statement_identities": (
                value.statement_identities[0],
                identity("cfo", ("subtotal", 1), ("depreciation", -1)),
            ),
        }
    )
    assert cfo(value).calculated_value is None


def chain(length: int) -> FinancialBook:
    value = book()
    rows = tuple(line(f"n{i}", f"other:n{i}", "1", i + 1, kind="subtotal") for i in range(length))
    equations = tuple(identity(f"n{i}", (f"n{i + 1}", 1)) for i in range(length - 1))
    return value.model_copy(update={"statement_lines": rows, "statement_identities": equations})


def test_identity_depth_limit_applies_even_to_previously_memoized_descendants() -> None:
    assert statement_issues(chain(12)) == ()
    for equations in (
        chain(13).statement_identities,
        tuple(reversed(chain(13).statement_identities)),
    ):
        value = chain(13).model_copy(update={"statement_identities": equations})
        assert any("twelve" in issue for issue in statement_issues(value))


def test_identity_expansion_is_bounded_even_for_shared_subtrees() -> None:
    value = book()
    leaves = tuple(line(f"n{i}", f"other:n{i}", "1", i + 1) for i in range(1000))
    subtotal = line("subtotal", "other:subtotal", "1000", 1001, kind="subtotal")
    wrappers = tuple(
        line(f"wrap{i}", f"other:wrap{i}", "1000", 1002 + i, kind="total") for i in range(21)
    )
    equations = (
        identity("subtotal", *((leaf.line_id, 1) for leaf in leaves)),
        *(identity(w.line_id, ("subtotal", 1)) for w in wrappers),
    )
    value = value.model_copy(
        update={
            "statement_lines": (*leaves, subtotal, *wrappers),
            "statement_identities": equations,
        }
    )
    assert any("Expanded statement identities" in issue for issue in statement_issues(value))


@pytest.mark.parametrize(
    "change,expected",
    [
        ("duplicate_row", "Duplicate statement line"),
        ("unknown_period", "unknown period"),
        ("duplicate_item", "Duplicate canonical statement item"),
        ("unknown_item", "Unknown statement item"),
        ("metadata", "Changed statement definition"),
        ("priority", "Duplicate statement display priority"),
        ("disclosure_duplicate", "Duplicate statement disclosure"),
        ("disclosure_contradiction", "contradicts populated"),
        ("known_disagreement", "Statement/account disagreement"),
        ("negative_revolver", "Negative revolver"),
        ("instant_flow", "period-end-only"),
    ],
)
def test_statement_validation_boundaries(change: str, expected: str) -> None:
    value = statements()
    if change == "duplicate_row":
        value = value.model_copy(
            update={"statement_lines": (*value.statement_lines, value.statement_lines[0])}
        )
    elif change == "unknown_period":
        value = value.model_copy(
            update={
                "statement_lines": (
                    value.statement_lines[0].model_copy(update={"period_id": "unknown"}),
                )
            }
        )
    elif change == "duplicate_item":
        value = value.model_copy(
            update={
                "statement_lines": (
                    *value.statement_lines,
                    line("second", "cfo_ncfo", "60", 5, kind="total"),
                )
            }
        )
    elif change == "unknown_item":
        value = value.model_copy(
            update={
                "statement_lines": (*value.statement_lines, line("unknown", "invented", "1", 5))
            }
        )
    elif change == "metadata":
        changed = value.statement_lines[0].model_copy(
            update={
                "period_id": "Q1",
                "label": "Other definition",
                "value": observed("Q1.cfo", "60"),
            }
        )
        value = value.model_copy(update={"statement_lines": (*value.statement_lines, changed)})
    elif change == "priority":
        value = value.model_copy(
            update={
                "statement_lines": (*value.statement_lines, line("other", "other:item", "1", 1))
            }
        )
    elif change == "disclosure_duplicate":
        value = value.model_copy(update={"statement_disclosures": value.statement_disclosures * 2})
    elif change == "disclosure_contradiction":
        row = value.statement_disclosures[0]
        value = value.model_copy(
            update={
                "statement_disclosures": (
                    row.model_copy(
                        update={
                            "disclosure": row.disclosure.model_copy(
                                update={"status": "not_disclosed"}
                            )
                        }
                    ),
                )
            }
        )
    elif change == "known_disagreement":
        changed = value.statement_lines[0].model_copy(update={"value": observed("cfo.Q2", "99")})
        value = value.model_copy(update={"statement_lines": (changed, *value.statement_lines[1:])})
    elif change == "negative_revolver":
        value = value.model_copy(
            update={
                "statement_lines": (
                    *value.statement_lines,
                    line("rcf", "rcf_drawn", "-1", 1, statement="BS"),
                )
            }
        )
    else:
        value = value.model_copy(
            update={
                "periods": (
                    value.periods[0],
                    value.periods[1].model_copy(update={"period_type": "PERIOD_END"}),
                )
            }
        )
    pack, review = freeze(value)
    assert any(expected in issue for issue in validate_financial_review(pack, review))


def test_maximum_observation_id_has_a_bounded_normalization_reference() -> None:
    value = statements()
    long = line("capex", "capex_total", "1", 5).model_copy(
        update={"value": observed("a" * 160, "1")}
    )
    pack, review = freeze(
        value.model_copy(update={"statement_lines": (*value.statement_lines, long)})
    )
    report = statement_report(pack, review, value.book_id)
    result = next(c for c in report.cells if c.line_id == "capex")
    assert result.normalization_id and len(result.normalization_id) <= 160


def test_income_tax_benefit_is_not_turned_into_an_expense() -> None:
    value = statements()
    benefit = line("tax_benefit", "income_tax_total", "10", 1, statement="IS").model_copy(
        update={"label": "Income tax benefit"}
    )
    pack, review = freeze(
        value.model_copy(update={"statement_lines": (*value.statement_lines, benefit)})
    )
    row = next(
        c for c in statement_report(pack, review, value.book_id).cells if c.line_id == "tax_benefit"
    )
    assert row.source_amount == row.normalized_amount == 10
    assert row.value_class == "source"


def test_noncanonical_sign_normalization_requires_explicit_source_evidence() -> None:
    from pydantic import ValidationError

    row = line("sga", "sga", "20", 1, statement="IS")
    raw = row.model_dump()
    raw["sign_convention"] = "outflow_magnitude"
    with pytest.raises(ValidationError):
        StatementLine.model_validate(raw)
    sign_quote = _C.model_copy(
        update={
            "locator": "sign",
            "quote": "Synthetic source presents expenses as positive magnitudes",
        }
    )
    raw["sign_citations"] = (sign_quote,)
    row = StatementLine.model_validate(raw)
    value = statements().model_copy(
        update={"statement_lines": (*statements().statement_lines, row)}
    )
    pack, review = freeze(value)
    cell = next(
        c for c in statement_report(pack, review, value.book_id).cells if c.line_id == "sga"
    )
    assert cell.source_amount == 20 and cell.normalized_amount == -20
    assert any(c.locator == "sign" for c in cell.citations)


@pytest.mark.parametrize("coefficient", [True, False, 1.0, "1", 0, 2])
def test_statement_coefficients_are_exact_integer_signs(coefficient: object) -> None:
    from pydantic import ValidationError

    from deploy_vii.financial_contracts import StatementContribution

    with pytest.raises(ValidationError):
        StatementContribution.model_validate({"line_id": "line", "coefficient": coefficient})


def test_explicit_tax_expense_normalization_agrees_between_statement_and_model() -> None:
    value = statements()
    expense = line("tax_expense", "income_tax_total", "10", 1, statement="IS").model_copy(
        update={"sign_convention": "outflow_magnitude", "sign_citations": (_C,)}
    )
    value = value.model_copy(update={"statement_lines": (*value.statement_lines, expense)})
    pack, review = freeze(value)
    cell = next(
        c for c in statement_report(pack, review, value.book_id).cells if c.line_id == "tax_expense"
    )
    row = next(
        r
        for r in kernel_registers(pack, review, value.book_id).accounts
        if r.metric_id == "income_tax_expense" and r.period_id == "Q2"
    )
    assert cell.source_amount == 10
    assert cell.normalized_amount == row.value == -10
    assert row.source and row.source.cell_text == "10"


def test_all_statement_balances_require_consistent_same_date_values() -> None:
    value = statements()
    instant = value.periods[1].model_copy(update={"period_id": "END", "period_type": "PERIOD_END"})
    assets = line("assets", "total_assets", "100", 1, statement="BS")
    conflicting_assets = assets.model_copy(
        update={"period_id": "END", "value": observed("assets.END", "200")}
    )
    value = value.model_copy(
        update={
            "periods": (*value.periods, instant),
            "statement_lines": (*value.statement_lines, assets, conflicting_assets),
        }
    )
    pack, review = freeze(value)
    assert any(
        "same-date statement balances" in issue for issue in validate_financial_review(pack, review)
    )
    consistent = conflicting_assets.model_copy(update={"value": observed("assets.END", "100")})
    value = value.model_copy(update={"statement_lines": (*value.statement_lines[:-1], consistent)})
    pack, review = freeze(value)
    assert validate_financial_review(pack, review) == ()
