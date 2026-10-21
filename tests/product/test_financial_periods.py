"""New period-artifact integration regressions, using explicit synthetic evidence."""

from decimal import Decimal, localcontext

import pytest

from deploy_vii.financial_contracts import AccountObservation, FinancialBook, FinancialReview
from deploy_vii.financial_periods import (
    HistoricalReport,
    HistoricalValue,
    historical_report,
    validate_historical_report,
)
from deploy_vii.preparation import PreparedPack
from tests.product.test_financials import book, freeze, observed, period


def periods_case() -> FinancialBook:
    value = book()
    periods = (
        period("Q1", "2025-01-01", "2025-03-31", 1),
        period("H1", "2025-01-01", "2025-06-30", 2, "YTD"),
        period("9M", "2025-01-01", "2025-09-30", 3, "YTD"),
        period("FY", "2025-01-01", "2025-12-31", 4, "FY"),
    )
    accounts = tuple(
        AccountObservation(
            metric_id=metric, period_id=pid, value=observed(f"{metric}.{pid}", amount)
        )
        for metric in ("revenue", "cash_interest_paid", "total_debt")
        for pid, amount in zip(("Q1", "H1", "9M", "FY"), ("10", "30", "60", "100"), strict=True)
    )
    return value.model_copy(
        update={
            "periods": periods,
            "accounts": accounts,
            "facilities": (),
            "segments": (),
            "segment_allocation": (),
            "segment_disclosure": value.segment_disclosure.model_copy(
                update={"status": "not_disclosed"}
            ),
            "addbacks": (),
            "kpis": (),
            "statement_lines": (),
            "statement_identities": (),
            "statement_disclosures": (),
        }
    )


def frozen(value: FinancialBook) -> tuple[PreparedPack, FinancialReview]:
    # freeze() fixes its run to July; this case deliberately spans the full year.
    pack, review = freeze(value)
    from datetime import date

    run = pack.run.model_copy(update={"as_of": date(2026, 2, 1)})
    pack = pack.model_copy(update={"run": run})
    review = review.model_copy(update={"as_of": run.as_of, "pack_sha256": pack.content_hash()})
    return pack, review


def entry(report: HistoricalReport, column: str, key: str = "acct:revenue") -> HistoricalValue:
    node = next(n for n in report.constructions if n.column_key == column)
    return next(
        v
        for v in report.values
        if v.construction_id == node.construction_id and v.series_key == key
    )


def test_calculated_quarters_retain_signed_operands_and_reported_fy() -> None:
    value = periods_case()
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    q2, q3, q4 = (entry(report, key) for key in ("Q:H1-Q1", "Q:9M-H1", "Q:FY-9M"))
    assert [v.value.amount for v in (q2, q3, q4)] == [20, 30, 40]
    assert [v.reference.coefficient for v in q2.operands] == [1, -1]
    assert [v.value.amount for v in q2.operands] == [30, 10]
    assert q2.value.value_class == "calculated"
    assert q2.value.observation_ids == ("revenue.H1", "revenue.Q1")
    assert q2.value.citations
    assert entry(report, "FY:FY").value.value_class == "source"
    assert entry(report, "LTM:FY").value.amount == 100
    assert report.review_sha256 == review.content_hash()
    assert validate_historical_report(pack, review, report) == ()


def test_missing_component_is_null_and_derived_balance_is_not_subtracted() -> None:
    value = periods_case()
    value = value.model_copy(
        update={
            "accounts": tuple(
                row.model_copy(update={"value": observed("revenue.H1", None)})
                if row.metric_id == "revenue" and row.period_id == "H1"
                else row
                for row in value.accounts
            )
        }
    )
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    q2 = entry(report, "Q:H1-Q1")
    assert q2.value.amount is None
    assert q2.value.calculation_status == "Not Calculable"
    assert q2.operands[0].value.amount is None
    debt = entry(report, "Q:H1-Q1", "acct:total_debt")
    assert debt.value.amount == 30
    assert debt.operands == ()
    assert "closing balance" in debt.formula


def test_sign_normalization_and_decimal_context_are_explicit() -> None:
    value = periods_case()
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    row = entry(report, "Q:Q1", "acct:cash_interest_paid")
    assert row.value.amount == -10
    assert row.value.value_class == "normalized"
    assert entry(report, "Q:H1-Q1", "acct:cash_interest_paid").value.amount == -20
    with localcontext() as context:
        context.prec = 2
        assert historical_report(pack, review, value.book_id) == report


def test_forged_historical_output_is_not_accepted() -> None:
    value = periods_case()
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    assert validate_historical_report(pack, review, report.model_copy(update={"values": ()}))
    assert validate_historical_report(
        pack, review, report.model_copy(update={"book_id": "missing"})
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        historical_report(pack, review.model_copy(update={"issuer_id": "other"}), value.book_id)


def test_no_partial_ltm_without_prior_year_components() -> None:
    value = book()
    pack, review = freeze(value)
    report = historical_report(pack, review, value.book_id)
    result = entry(report, "LTM:Q2")
    assert result.value.amount is None
    assert any(term.reference.kind == "missing" for term in result.operands)
    assert result.value.calculation_status == "Not Calculable"


def test_mismatched_stubs_do_not_produce_a_known_quarter() -> None:
    from datetime import date

    value = periods_case()
    value = value.model_copy(
        update={
            "periods": tuple(
                row.model_copy(update={"start_date": date(2025, 2, 1)})
                if row.period_id == "H1"
                else row
                for row in value.periods
            )
        }
    )
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    assert entry(report, "Q:H1-Q1").value.amount is None
    assert entry(report, "Q:9M-H1").value.amount is None
    assert entry(report, "Q:FY-9M").value.amount == 40


def rolled_case() -> FinancialBook:
    value = periods_case()
    periods = (
        period("PYTD", "2024-01-01", "2024-06-30", 2, "YTD"),
        period("FY24", "2024-01-01", "2024-12-31", 4, "FY"),
        period("CYTD", "2025-01-01", "2025-06-30", 2, "YTD"),
        period("LTM", "2024-07-01", "2025-06-30", 2, "LTM"),
    )
    periods = tuple(
        p.model_copy(update={"fiscal_year": "2024"}) if p.period_id in {"PYTD", "FY24"} else p
        for p in periods
    )
    accounts = tuple(
        AccountObservation(
            metric_id="revenue", period_id=pid, value=observed("revenue." + pid, amount)
        )
        for pid, amount in (("PYTD", "20"), ("FY24", "100"), ("CYTD", "30"), ("LTM", "999"))
    )
    return value.model_copy(update={"periods": periods, "accounts": accounts})


def test_ltm_keeps_reported_figure_separate_from_three_components() -> None:
    value = rolled_case()
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    row = entry(report, "LTM:LTM")
    assert row.value.amount == 110
    assert row.value.stated_amount == 999
    assert "differs" in (row.value.note or "")
    assert [o.value.amount for o in row.operands] == [100, 30, 20]
    assert [o.reference.coefficient for o in row.operands] == [1, 1, -1]
    nodes = {n.construction_id: n for n in report.constructions}
    assert all(o.reference.reference in nodes for o in row.operands)
    ltm = next(n for n in report.constructions if n.column_key == "LTM:LTM")
    assert ltm.days == 365
    assert ltm.start_date and ltm.start_date.isoformat() == "2024-07-01"


def test_ltm_stated_value_never_plugs_a_missing_input() -> None:
    value = rolled_case()
    value = value.model_copy(
        update={
            "accounts": tuple(
                row.model_copy(update={"value": observed("revenue.PYTD", None)})
                if row.period_id == "PYTD"
                else row
                for row in value.accounts
            )
        }
    )
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    row = entry(report, "LTM:LTM")
    assert row.value.amount is None and row.value.stated_amount == 999
    assert row.operands[2].value.amount is None


def test_explicit_fy_components_preserve_the_reported_comparison() -> None:
    value = periods_case()
    quarters = tuple(
        period(f"Q{i}", start, end, i)
        for i, start, end in (
            (1, "2025-01-01", "2025-03-31"),
            (2, "2025-04-01", "2025-06-30"),
            (3, "2025-07-01", "2025-09-30"),
            (4, "2025-10-01", "2025-12-31"),
        )
    )
    fy = value.periods[-1].model_copy(
        update={"component_period_ids": tuple(p.period_id for p in quarters)}
    )
    accounts = tuple(
        AccountObservation(
            metric_id="revenue", period_id=pid, value=observed("revenue." + pid, amount)
        )
        for pid, amount in (("Q1", "10"), ("Q2", "20"), ("Q3", "30"), ("Q4", "40"), ("FY", "999"))
    )
    value = value.model_copy(update={"periods": (*quarters, fy), "accounts": accounts})
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    row = entry(report, "FY:FY")
    assert row.value.amount == 100 and row.value.stated_amount == 999
    assert len(row.value.observation_ids) == 4
    assert report.periods[-1].component_period_ids == ("Q1", "Q2", "Q3", "Q4")


def test_missing_source_dates_block_subtraction_but_keep_reported_values() -> None:
    value = periods_case()
    value = value.model_copy(
        update={
            "periods": tuple(
                row.model_copy(
                    update={"start_date": None, "limitation": "Source start date unavailable"}
                )
                if row.period_id == "H1"
                else row
                for row in value.periods
            )
        }
    )
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    assert entry(report, "Q:H1-Q1").value.amount is None
    node = next(n for n in report.constructions if n.column_key == "Q:H1-Q1")
    assert node.days is None and node.start_date is None
    assert node.limitation
    assert entry(report, "FY:FY").value.amount == 100


def test_colliding_kernel_column_names_cannot_silently_overwrite_values() -> None:
    value = periods_case()
    q3 = period("H1-Q1", "2025-07-01", "2025-09-30", 3)
    value = value.model_copy(update={"periods": (*value.periods, q3)})
    pack, review = frozen(value)
    with pytest.raises(ValueError, match="Ambiguous kernel period construction"):
        historical_report(pack, review, value.book_id)


def test_long_source_ids_have_bounded_unambiguous_artifact_ids() -> None:
    value = periods_case()
    rename = {p.period_id: p.period_id + "x" * 150 for p in value.periods}
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"period_id": rename[p.period_id]}) for p in value.periods
            ),
            "accounts": tuple(
                r.model_copy(update={"period_id": rename[r.period_id]}) for r in value.accounts
            ),
        }
    )
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    assert all(len(n.construction_id) <= 160 for n in report.constructions)
    assert len({v.value_id for v in report.values}) == len(report.values)
    assert any(len(n.column_key) > 160 for n in report.constructions)


def test_input_registry_preserves_explicit_conflicts_and_unavailable_rows() -> None:
    from tests.product.test_financials import conflict

    value = periods_case()
    value = value.model_copy(
        update={
            "accounts": tuple(
                row.model_copy(update={"value": conflict("revenue.H1")})
                if row.period_id == "H1" and row.metric_id == "revenue"
                else row
                for row in value.accounts
            )
        }
    )
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    observed_inputs = {o.observation_id: o for o in report.observations}
    row = next(
        r for r in report.input_rows if r.series_key == "acct:revenue" and r.period_id == "H1"
    )
    assert row.adapter_amount is None and row.observation_id
    assert observed_inputs[row.observation_id].status == "conflicting"
    assert len(observed_inputs[row.observation_id].alternatives) == 2
    assert entry(report, "Q:H1-Q1").value.amount is None


def test_source_normalization_evidence_survives_period_projection() -> None:
    from tests.product.test_financials import _C
    from tests.product.test_statements import line

    value = periods_case()
    sign = _C.model_copy(
        update={"locator": "sign", "quote": "Synthetic positive expense magnitude"}
    )
    tax = line("tax", "income_tax_total", "10", 1, statement="IS", pid="Q1").model_copy(
        update={"sign_convention": "outflow_magnitude", "sign_citations": (sign,)}
    )
    pack, review = frozen(value.model_copy(update={"statement_lines": (tax,)}))
    report = historical_report(pack, review, value.book_id)
    row = entry(report, "Q:Q1", "acct:income_tax_expense")
    assert row.value.amount == -10 and row.value.value_class == "normalized"
    assert any(c.locator == "sign" for c in row.value.citations)


def test_facility_issuance_evidence_and_foreign_currency_are_retained() -> None:
    from datetime import date

    from tests.product.test_financials import _C, facility

    value = periods_case()
    loan = facility("H1").model_copy(
        update={"currency": "EUR", "issued_on": date(2025, 4, 1), "issuance_citations": (_C,)}
    )
    pack, review = frozen(value.model_copy(update={"facilities": (loan,)}))
    report = historical_report(pack, review, value.book_id)
    opening = entry(report, "Q:Q1", "fac:loan")
    assert opening.value.amount == 0
    assert opening.value.value_class == "normalized"
    assert opening.value.issuance_facility_ids == ("loan",)
    assert opening.value.citations and opening.currency == "EUR"
    assert entry(report, "Q:H1-Q1", "fac:loan").value.amount == 100


def test_stated_ltm_dates_cannot_relabel_the_computed_span() -> None:
    from datetime import date

    value = rolled_case()
    value = value.model_copy(
        update={
            "periods": tuple(
                row.model_copy(update={"start_date": date(2024, 7, 2)})
                if row.period_id == "LTM"
                else row
                for row in value.periods
            )
        }
    )
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    node = next(n for n in report.constructions if n.column_key == "LTM:LTM")
    assert node.days == 365
    assert node.limitation
    assert entry(report, "LTM:LTM").value.amount is None


def test_fy_without_a_proven_twelve_month_span_cannot_be_an_ltm() -> None:
    value = periods_case()
    value = value.model_copy(
        update={
            "periods": tuple(
                row.model_copy(update={"start_date": None, "limitation": "FY span not supplied"})
                if row.period_id == "FY"
                else row
                for row in value.periods
            )
        }
    )
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    assert entry(report, "FY:FY").value.amount == 100
    assert entry(report, "LTM:FY").value.amount is None


def test_kpi_units_and_exact_rate_semantics_remain_separate_from_money() -> None:
    from deploy_vii.financial_contracts import KpiObservation
    from tests.product.test_financials import _C

    value = periods_case()
    kpi = KpiObservation(
        kpi_id="occupancy",
        kpi_label="Occupancy",
        business_unit="Issuer",
        kpi_category="Operations",
        definition="Occupied rooms / available rooms",
        display_priority=1,
        period_id="Q1",
        value=observed("occupancy.Q1", "0.8"),
        unit="FRACTION",
        value_type="RATE",
        definition_citations=(_C,),
    )
    value = value.model_copy(update={"kpis": (kpi,)})
    pack, review = frozen(value)
    report = historical_report(pack, review, value.book_id)
    row = entry(report, "Q:Q1", "kpi:occupancy")
    assert row.value.amount == Decimal("0.8")
    assert row.unit == "FRACTION" and row.currency is None
    assert entry(report, "Q:H1-Q1", "kpi:occupancy").value.amount is None
    assert entry(report, "LTM:FY", "kpi:occupancy").operands == ()


def test_unresolved_provenance_refuses_instead_of_dropping_citations() -> None:
    from deploy_vii.financial_periods import _value
    from deploy_vii.model.frame import Cell, SourceRef

    with pytest.raises(KeyError):
        _value(
            Cell(
                Decimal(1),
                basis="REPORTED",
                sources=(SourceRef("unknown", "financial-observation", "1"),),
            ),
            {},
            {},
        )
