"""New boundary regressions; all evidence here is explicitly synthetic."""

import hashlib
import re
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from deploy_vii.contracts import Citation, Run, Source, Span
from deploy_vii.financial_adapter import kernel_registers, source_citations
from deploy_vii.financial_contracts import (
    AccountObservation,
    AddbackObservation,
    Alternative,
    Disclosure,
    FacilityObservation,
    FinancialBook,
    FinancialPeriod,
    FinancialReview,
    KpiObservation,
    Observation,
    ProFormaObservation,
    SegmentAllocation,
    SegmentObservation,
)
from deploy_vii.financial_validation import (
    book_issues,
    period_issues,
    records,
    validate_financial_review,
)
from deploy_vii.model.frame import SourceRef
from deploy_vii.model.history import account_frame, historical_columns
from deploy_vii.model.statements import pro_forma_column, statement_frame
from deploy_vii.preparation import PreparedPack

_C = Citation(
    source_id="S1",
    source_sha256="1" * 64,
    locator="metadata",
    quote="Synthetic issuer, USD millions, US GAAP, consolidated; classifications are test inputs.",
)


def observed(name: str, amount: str | None = "10", *, status: str | None = None) -> Observation:
    return Observation.model_validate(
        {
            "observation_id": name,
            "status": status or ("known" if amount is not None else "missing"),
            "amount": Decimal(amount) if amount is not None else None,
            "citations": (_C.model_copy(update={"locator": name, "quote": f"{name} = {amount}"}),),
            "reason": "Synthetic gap" if amount is None else None,
        }
    )


def period(name: str, start: str, end: str, quarter: int, kind: str = "QUARTER") -> FinancialPeriod:
    return FinancialPeriod.model_validate(
        {
            "period_id": name,
            "fiscal_year": "2025",
            "fiscal_quarter": quarter,
            "period_type": kind,
            "start_date": date.fromisoformat(start),
            "end_date": date.fromisoformat(end),
            "day_count": None,
            "audit_status": "UNAUDITED",
            "currency": "USD",
            "unit": "MILLIONS",
            "accounting_basis": "US GAAP",
            "entity_perimeter": "Consolidated",
            "citations": (_C,),
            "expense_presentation": "by_function",
            "presentation_citations": (_C,),
        }
    )


def facility(pid: str = "Q2", fid: str = "loan") -> FacilityObservation:
    prefix = f"{fid}.{pid}"
    return FacilityObservation(
        facility_id=fid,
        facility_name="Synthetic loan",
        period_id=pid,
        facility_type="TERM LOAN",
        currency="USD",
        carrying_value=observed(prefix + ".carrying", "100"),
        principal=observed(prefix + ".principal", "105"),
        drawn_amount=observed(prefix + ".drawn", "105"),
        commitment=observed(prefix + ".commitment", "150"),
        secured_status="SECURED",
        seniority="SENIOR",
        lease_classification="NOT_LEASE",
        margin_or_coupon="Not stated",
        maturity_date=None,
        maturity_limitation="Not disclosed",
        rate_type="NOT_STATED",
        reference_rate="NOT_STATED",
        spread_bps=observed(prefix + ".spread", None),
        floor_bps=observed(prefix + ".floor", None),
        fixed_rate=observed(prefix + ".fixed", None),
        annual_amortisation=observed(prefix + ".amort", None),
        terms_citations=(_C,),
    )


def book() -> FinancialBook:
    periods = (
        period("Q1", "2025-01-01", "2025-03-31", 1),
        period("Q2", "2025-04-01", "2025-06-30", 2),
    )
    values = {
        "revenue": "100",
        "cogs": "-30",
        "opex_including_da": "-20",
        "depreciation_amortization": "-10",
        "cfo_ncfo": "60",
        "working_capital_change": "0",
        "cash_interest_paid": "-5",
        "cash_taxes_paid": "-5",
        "net_debt_issue_repay": "0",
        "cash_and_equivalents": "20",
    }
    return FinancialBook(
        book_id="consolidated",
        entity_perimeter="Consolidated",
        accounting_basis="US GAAP",
        currency="USD",
        unit="MILLIONS",
        periods=periods,
        accounts=tuple(
            AccountObservation(
                metric_id=metric,
                period_id=p.period_id,
                value=observed(f"{p.period_id}.{metric}", value),
            )
            for p in periods
            for metric, value in values.items()
        ),
        addbacks=(),
        segments=(),
        kpis=(),
        facilities=(facility(),),
        pro_forma=(),
        segment_allocation=(),
        addback_disclosure=Disclosure(
            status="complete", explanation="Source states no adjustments", citations=(_C,)
        ),
        segment_disclosure=Disclosure(
            status="not_disclosed", explanation="No segment disclosure", citations=(_C,)
        ),
    )


def freeze(value: FinancialBook) -> tuple[PreparedPack, FinancialReview]:
    run = Run(
        run_id="test",
        issuer_id="synthetic",
        issuer_name="Synthetic",
        as_of=date(2025, 7, 10),
        case_kind="synthetic",
        # The Credit Snapshot set before decision 0009 added CP-MODEL (task 6.5): the pack hash
        # the synthetic replay corpus records stays as recorded.
        requested_modules=("CP-0", "CP-1", "CP-1A", "CP-2", "CP-4", "CP-3", "CP-5", "CP-6"),
    )
    review = FinancialReview(
        pack_sha256="0" * 64,
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        books=(value,),
        analysis=(),
    )
    quotes = {citation.locator: citation.quote for citation in records(review, Citation)}
    digest = hashlib.sha256("\n".join(quotes.values()).encode()).hexdigest()
    source = Source(
        source_id="S1",
        name="Synthetic evidence",
        status="ready",
        sha256=digest,
        spans=tuple(Span(locator=key, text=text) for key, text in quotes.items()),
    )
    pack = PreparedPack(run=run, sources=(source,))
    review = FinancialReview.model_validate_json(review.model_dump_json().replace("1" * 64, digest))
    return pack, review.model_copy(update={"pack_sha256": pack.content_hash()})


def frames(value: FinancialBook) -> tuple[dict[str, object], FinancialReview]:
    pack, review = freeze(value)
    regs = kernel_registers(pack, review, value.book_id)
    columns = historical_columns(regs)
    return dict(statement_frame(account_frame(regs, columns), columns, regs)["Q:Q2"]), review


def test_omitted_financing_lines_stay_unknown_and_zero_requires_evidence() -> None:
    value = book()
    pack, review = freeze(value)
    assert validate_financial_review(pack, review) == ()
    regs = kernel_registers(pack, review, value.book_id)
    assert len(regs.accounts) == 36 * 2  # Net income is a controlled flow.
    assert all(r.value is None for r in regs.accounts if r.metric_id == "net_income")
    columns = historical_columns(regs)
    cells = statement_frame(account_frame(regs, columns), columns, regs)["Q:Q2"]
    assert cells["ebitda"].value == 60
    assert cells["cfo_adjusted"].value is None
    assert cells["lease_cash_not_in_ebitda"].reason == "NOT_STATED"
    extra = tuple(
        AccountObservation(metric_id=metric, period_id="Q2", value=observed(metric, "0"))
        for metric in ("lease_payments_in_financing", "interest_paid_in_financing")
    )
    pack, review = freeze(value.model_copy(update={"accounts": value.accounts + extra}))
    regs = kernel_registers(pack, review, value.book_id)
    columns = historical_columns(regs)
    cells = statement_frame(account_frame(regs, columns), columns, regs)["Q:Q2"]
    assert cells["cfo_adjusted"].value == 60
    assert source_citations(review, cells["cfo_adjusted"].sources)
    assert all(
        c.source_sha256 == pack.sources[0].sha256
        for c in source_citations(review, cells["ebitda"].sources)
    )


def test_omitted_cogs_never_selects_expenses_by_nature_without_evidence() -> None:
    value = book()
    value = value.model_copy(
        update={"accounts": tuple(a for a in value.accounts if a.metric_id != "cogs")}
    )
    pack, review = freeze(value)
    regs = kernel_registers(pack, review, value.book_id)
    cols = historical_columns(regs)
    assert statement_frame(account_frame(regs, cols), cols, regs)["Q:Q2"]["ebitda"].value is None
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"expense_presentation": "by_nature"}) for p in value.periods
            )
        }
    )
    pack, review = freeze(value)
    regs = kernel_registers(pack, review, value.book_id)
    cols = historical_columns(regs)
    assert statement_frame(account_frame(regs, cols), cols, regs)["Q:Q2"]["ebitda"].value == 90


def test_unknown_opening_facility_is_not_a_new_issue() -> None:
    value = book()
    pack, review = freeze(value)
    regs = kernel_registers(pack, review, value.book_id)
    cols = historical_columns(regs)
    cells = statement_frame(account_frame(regs, cols), cols, regs)["Q:Q2"]
    assert cells["debt_opening"].value is None
    assert cells["debt_non_cash"].value is None
    row = value.facilities[0].model_copy(
        update={"issued_on": date(2025, 4, 10), "issuance_citations": (_C,)}
    )
    pack, review = freeze(value.model_copy(update={"facilities": (row,)}))
    regs = kernel_registers(pack, review, value.book_id)
    cols = historical_columns(regs)
    cells = statement_frame(account_frame(regs, cols), cols, regs)["Q:Q2"]
    assert cells["debt_opening"].value == 0
    assert source_citations(review, cells["debt_opening"].sources) == (
        review.books[0].facilities[0].issuance_citations[0],
    )


@pytest.mark.parametrize("status", ["partial", "not_disclosed"])
def test_incomplete_bridge_cannot_silently_become_no_adjustments(status: str) -> None:
    value = book()
    value = value.model_copy(
        update={
            "addback_disclosure": value.addback_disclosure.model_copy(update={"status": status})
        }
    )
    pack, review = freeze(value)
    with pytest.raises(ValueError, match="add-back bridge"):
        kernel_registers(pack, review, value.book_id)


def test_unobserved_addback_period_is_null() -> None:
    value = book()
    addback = AddbackObservation(
        addback_id="restructuring",
        addback_label="Restructuring",
        classification="RESTRUCTURING",
        realization_status="REALIZED",
        display_priority=1,
        period_id="Q1",
        value=observed("addback"),
        source_definition="Synthetic restructuring",
        classification_citations=(_C,),
    )
    pack, review = freeze(value.model_copy(update={"addbacks": (addback,)}))
    regs = kernel_registers(pack, review, value.book_id)
    cols = historical_columns(regs)
    cells = statement_frame(account_frame(regs, cols), cols, regs)["Q:Q2"]
    assert cells["adjusted_ebitda"].value is None


@pytest.mark.parametrize(
    "amount", ["NaN", "Infinity", "-Infinity", "1e18", "-1e18", "0.00000000001"]
)
def test_numbers_are_finite_bounded_decimal_inputs(amount: str) -> None:
    with pytest.raises(ValidationError):
        observed("invalid", amount)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "known", "amount": None},
        {"citations": ()},
        {"amount": None, "status": "missing", "reason": None},
        {"status": "missing"},
        {"status": "conflicting", "amount": None, "reason": "Conflict"},
        {"alternatives": (Alternative(amount=Decimal(1), citations=(_C,), explanation="A"),)},
    ],
)
def test_observation_state_is_not_coercible_to_a_value(changes: dict[str, object]) -> None:
    data = observed("value").model_dump()
    data.update(changes)
    with pytest.raises(ValidationError):
        Observation.model_validate(data)


def conflict(name: str) -> Observation:
    return Observation(
        observation_id=name,
        status="conflicting",
        amount=None,
        citations=(),
        reason="Disagreement",
        alternatives=(
            Alternative(amount=Decimal(10), citations=(_C,), explanation="A"),
            Alternative(amount=Decimal(11), citations=(_C,), explanation="B"),
        ),
    )


def test_conflicts_are_retained_and_mask_same_date_known_balances() -> None:
    value = book()
    twin = value.periods[1].model_copy(update={"period_id": "END", "period_type": "PERIOD_END"})
    cash = AccountObservation(
        metric_id="cash_and_equivalents", period_id="END", value=conflict("cash.conflict")
    )
    fac = value.facilities[0].model_copy(
        update={"period_id": "END", "carrying_value": conflict("loan.conflict")}
    )
    # Re-identify other observations; IDs identify source cells even across periods.
    raw = fac.model_dump_json()
    for observation in records(fac, Observation):
        if observation.observation_id != "loan.conflict":
            raw = raw.replace(observation.observation_id, "END." + observation.observation_id)
    fac = FacilityObservation.model_validate_json(raw)
    pack, review = freeze(
        value.model_copy(
            update={
                "periods": (*value.periods, twin),
                "accounts": (*value.accounts, cash),
                "facilities": (*value.facilities, fac),
            }
        )
    )
    regs = kernel_registers(pack, review, value.book_id)
    cols = historical_columns(regs)
    cells = statement_frame(account_frame(regs, cols), cols, regs)["Q:Q2"]
    assert cells["cash_closing"].value is None
    assert cells["total_debt"].value is None
    tampered = review.model_dump_json().replace(
        "Synthetic issuer, USD millions", "Fabricated quote"
    )
    assert any(
        "Quote/locator" in x
        for x in validate_financial_review(pack, FinancialReview.model_validate_json(tampered))
    )


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (
            lambda b: b.model_copy(update={"periods": (*b.periods, b.periods[0])}),
            "Duplicate period",
        ),
        (
            lambda b: b.model_copy(
                update={
                    "periods": (
                        b.periods[0].model_copy(update={"component_period_ids": ("absent",)}),
                        b.periods[1],
                    )
                }
            ),
            "unknown period component",
        ),
        (
            lambda b: b.model_copy(
                update={
                    "periods": (
                        b.periods[0].model_copy(update={"component_period_ids": ("Q2",)}),
                        b.periods[1].model_copy(update={"component_period_ids": ("Q1",)}),
                    )
                }
            ),
            "Cyclic",
        ),
        (
            lambda b: b.model_copy(
                update={
                    "periods": (b.periods[0].model_copy(update={"unit": "THOUSANDS"}), b.periods[1])
                }
            ),
            "Mixed units",
        ),
        (
            lambda b: b.model_copy(update={"accounts": (*b.accounts, b.accounts[0])}),
            "Duplicate row",
        ),
        (
            lambda b: b.model_copy(
                update={"accounts": (b.accounts[0].model_copy(update={"period_id": "absent"}),)}
            ),
            "unknown period",
        ),
        (
            lambda b: b.model_copy(
                update={
                    "segment_allocation": (
                        SegmentAllocation(
                            slot_id="DIVISION_1",
                            slot_label="One",
                            component_segment_ids=("absent",),
                            rationale="Synthetic",
                        ),
                    )
                }
            ),
            "Allocate every",
        ),
    ],
)
def test_reference_boundaries(mutate: object, expected: str) -> None:
    from collections.abc import Callable

    assert isinstance(mutate, Callable)
    value = mutate(book())
    assert any(expected in issue for issue in book_issues(value))


def test_depth_limit_and_fiscal_slot_uniqueness() -> None:
    base = book().periods[0]
    chain = tuple(
        base.model_copy(
            update={
                "period_id": f"p{i}",
                "period_type": "PERIOD_END",
                "component_period_ids": (f"p{i + 1}",) if i < 4 else (),
            }
        )
        for i in range(5)
    )
    assert period_issues(chain) == ("Period component nesting exceeds four levels",)
    assert period_issues(chain[1:]) == ()
    assert (
        "Duplicate fiscal slot"
        in period_issues((base, base.model_copy(update={"period_id": "other"})))[0]
    )


def test_identity_and_unsafe_construct_are_revalidated() -> None:
    pack, review = freeze(book())
    for changes in ({"pack_sha256": "0" * 64}, {"issuer_id": "other"}, {"books": review.books * 2}):
        assert validate_financial_review(pack, review.model_copy(update=changes))
    invalid = review.books[0].accounts[0].value.model_copy(update={"amount": Decimal("NaN")})
    account = review.books[0].accounts[0].model_copy(update={"value": invalid})
    bad = review.model_copy(
        update={"books": (review.books[0].model_copy(update={"accounts": (account,)}),)}
    )
    assert "Invalid financial contract" in validate_financial_review(pack, bad)[0]
    with pytest.raises(ValueError, match="Unknown financial book"):
        kernel_registers(pack, review, "absent")
    with pytest.raises(ValueError, match="identity mismatch"):
        kernel_registers(pack, review.model_copy(update={"run_id": "other"}), "consolidated")
    with pytest.raises(ValueError, match="Unknown kernel provenance"):
        source_citations(review, (SourceRef("x", "unknown", "1"),))


def test_segments_and_kpis_retain_rows_and_explicit_missing_periods() -> None:
    value = book()
    segment = SegmentObservation(
        segment_id="digital",
        segment_name="Digital",
        segment_type="OPERATING_SEGMENT",
        display_priority=1,
        period_id="Q1",
        revenue=observed("segment", "40"),
        classification_citations=(_C,),
    )
    kpi = KpiObservation(
        kpi_id="arpu",
        kpi_label="ARPU",
        business_unit="Digital",
        kpi_category="Revenue per user",
        definition="Synthetic ARPU",
        display_priority=1,
        period_id="Q1",
        value=observed("arpu", "3"),
        unit="USD/user",
        value_type="RATE",
        definition_citations=(_C,),
    )
    allocation = SegmentAllocation(
        slot_id="DIVISION_1",
        slot_label="Digital",
        component_segment_ids=("digital",),
        rationale="Same business",
    )
    value = value.model_copy(
        update={
            "segments": (segment,),
            "kpis": (kpi,),
            "segment_allocation": (allocation,),
            "segment_disclosure": value.segment_disclosure.model_copy(update={"status": "partial"}),
        }
    )
    pack, review = freeze(value)
    regs = kernel_registers(pack, review, value.book_id)
    assert len(regs.segments) == len(regs.kpis) == 2
    frame = account_frame(regs, historical_columns(regs))
    assert frame["Q:Q2"]["bu:digital"].value is None
    assert frame["Q:Q2"]["kpi:arpu"].value is None
    broken = value.model_copy(
        update={
            "segments": (
                segment,
                segment.model_copy(update={"period_id": "Q2", "segment_name": "Other"}),
            )
        }
    )
    assert any("Changed definition" in x for x in book_issues(broken))


def test_pro_forma_events_are_separate_and_cannot_double_count() -> None:
    value = book()
    ltm = period("LTM", "2024-07-01", "2025-06-30", 2, "LTM")
    adjustment = ProFormaObservation(
        adjustment_id="acq",
        event_id="event",
        label="Acquisition",
        period_id="LTM",
        effective_date=date(2025, 7, 2),
        announced_on=date(2025, 7, 1),
        event_status="completed",
        classification="ACQUISITION",
        metric_id="facility:loan",
        value=observed("adjustment", "20"),
        event_citations=(_C,),
    )
    value = value.model_copy(update={"periods": (*value.periods, ltm), "pro_forma": (adjustment,)})
    pack, review = freeze(value)
    assert validate_financial_review(pack, review) == ()
    regs = kernel_registers(pack, review, value.book_id)
    cols = historical_columns(regs)
    frame = statement_frame(account_frame(regs, cols), cols, regs)
    result = pro_forma_column(regs, next(c for c in cols if c.kind == "LTM"), frame)
    assert result is not None
    assert result[1]["PF:LTM"]["total_debt"].value == 120
    assert frame["Q:Q2"]["total_debt"].value == 100
    duplicate = adjustment.model_copy(
        update={
            "adjustment_id": "acq2",
            "metric_id": "total_debt",
            "value": observed("adjustment2", "20"),
        }
    )
    assert any(
        "Double-counted" in x
        for x in book_issues(value.model_copy(update={"pro_forma": (adjustment, duplicate)}))
    )
    future = adjustment.model_copy(update={"announced_on": date(2025, 8, 1)})
    pack, review = freeze(value.model_copy(update={"pro_forma": (future,)}))
    assert any("not known" in x for x in validate_financial_review(pack, review))


@pytest.mark.parametrize(
    "changes",
    [
        {"fiscal_year": "FY24"},
        {"fiscal_year": "2201"},
        {"end_date": date(2201, 1, 1)},
        {"fiscal_year": "2020"},
        {"start_date": date(2025, 7, 1)},
        {"day_count": 1},
        {"start_date": None},
        {"fiscal_quarter": None},
        {"citations": ()},
        {"presentation_citations": ()},
    ],
)
def test_period_contract_rejects_ambiguous_or_unsupported_dimensions(
    changes: dict[str, object],
) -> None:
    data = book().periods[0].model_dump()
    data.update(changes)
    with pytest.raises(ValidationError):
        FinancialPeriod.model_validate(data)


@pytest.mark.parametrize(
    "field,amount",
    [
        ("principal", "-1"),
        ("drawn_amount", "-1"),
        ("commitment", "-1"),
        ("annual_amortisation", "-1"),
        ("carrying_value", "-1"),
        ("spread_bps", "1.5"),
        ("floor_bps", "2.1"),
        ("fixed_rate", "5"),
    ],
)
def test_facility_numeric_conventions_are_explicit(field: str, amount: str) -> None:
    data = facility().model_dump()
    data[field] = observed("bad", amount).model_dump()
    with pytest.raises(ValidationError):
        FacilityObservation.model_validate(data)


def test_facility_qualifiers_cannot_be_inferred_from_its_name() -> None:
    value = facility()
    data = value.model_dump()
    data["maturity_limitation"] = None
    with pytest.raises(ValidationError):
        FacilityObservation.model_validate(data)
    data = value.model_dump()
    data["issued_on"] = date(2025, 1, 1)
    with pytest.raises(ValidationError):
        FacilityObservation.model_validate(data)
    data = value.model_dump()
    data.update(rate_type="FIXED", spread_bps=observed("spread", "100").model_dump())
    with pytest.raises(ValidationError):
        FacilityObservation.model_validate(data)
    data = value.model_dump()
    data.update(
        facility_type="DEBT ADJUSTMENT", carrying_value=observed("carrying", "-3").model_dump()
    )
    assert FacilityObservation.model_validate(data).carrying_value.amount == -3
    assert value.rate_type == "NOT_STATED"
    with pytest.raises(ValidationError):
        AccountObservation(metric_id="invented_ffo_residual", period_id="Q1", value=observed("bad"))


def test_same_date_known_balance_disagreement_is_not_first_value_wins() -> None:
    value = book()
    twin = value.periods[1].model_copy(update={"period_id": "END", "period_type": "PERIOD_END"})
    cash = AccountObservation(
        metric_id="cash_and_equivalents", period_id="END", value=observed("END.cash", "30")
    )
    issues = book_issues(
        value.model_copy(
            update={"periods": (*value.periods, twin), "accounts": (*value.accounts, cash)}
        )
    )
    assert any("same-date account" in x for x in issues)
    value = value.model_copy(
        update={
            "accounts": (
                *value.accounts,
                AccountObservation(
                    metric_id="rcf_drawn", period_id="Q2", value=observed("negative", "-1")
                ),
            )
        }
    )
    assert any("Negative revolver" in x for x in book_issues(value))


def test_conflicting_cogs_cannot_select_nature_path() -> None:
    value = book()
    value = value.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"expense_presentation": "by_nature"}) for p in value.periods
            ),
            "accounts": tuple(
                a.model_copy(update={"value": conflict("conflicting." + a.period_id)})
                if a.metric_id == "cogs"
                else a
                for a in value.accounts
            ),
        }
    )
    pack, review = freeze(value)
    with pytest.raises(ValueError, match="COGS conflicts"):
        kernel_registers(pack, review, value.book_id)


def test_known_issuance_metadata_is_not_overwritten_by_an_unspecified_date() -> None:
    value = book()
    known = facility("Q2").model_copy(
        update={"issued_on": date(2025, 4, 1), "issuance_citations": (_C,)}
    )
    later_period = period("Q3", "2025-07-01", "2025-09-30", 3)
    later = facility("Q3")
    # Inspect typed conversion under a correspondingly later as-of date.
    value = value.model_copy(
        update={"periods": (*value.periods, later_period), "facilities": (known, later)}
    )
    pack, review = freeze(value)
    run = pack.run.model_copy(update={"as_of": date(2025, 10, 1)})
    pack = pack.model_copy(update={"run": run})
    review = review.model_copy(update={"as_of": run.as_of, "pack_sha256": pack.content_hash()})
    regs = kernel_registers(pack, review, value.book_id)
    opened = next(row for row in regs.facilities if row.period_id == "Q1")
    assert opened.carrying_value == 0
    assert opened.source is not None
    assert source_citations(review, (opened.source,))
    conflict_date = later.model_copy(
        update={"issued_on": date(2025, 4, 2), "issuance_citations": (_C,)}
    )
    assert any(
        "Conflicting facility issuance" in x
        for x in book_issues(value.model_copy(update={"facilities": (known, conflict_date)}))
    )


def test_nested_alternative_citation_hashes_are_checked() -> None:
    value = book()
    account = AccountObservation(
        metric_id="rcf_commitment", period_id="Q2", value=conflict("rcf.conflict")
    )
    pack, review = freeze(value.model_copy(update={"accounts": (*value.accounts, account)}))
    raw = review.model_dump_json().replace(pack.sources[0].sha256, "f" * 64, 1)
    assert any(
        "Unavailable or changed source" in x
        for x in validate_financial_review(pack, FinancialReview.model_validate_json(raw))
    )
    raw = review.model_dump_json().replace(
        '"observation_id":"Q2.revenue"', '"observation_id":"Q1.revenue"'
    )
    assert any(
        "Duplicate observation" in x
        for x in validate_financial_review(pack, FinancialReview.model_validate_json(raw))
    )


def test_explicit_derived_period_computes_sparse_values_without_assuming_zero() -> None:
    value = book()
    half = period("H1", "2025-01-01", "2025-06-30", 2, "YTD").model_copy(
        update={"component_period_ids": ("Q1", "Q2")}
    )
    additions = tuple(
        AccountObservation(metric_id=metric, period_id=pid, value=observed(f"{pid}.{metric}", "-2"))
        for pid in ("Q1", "Q2")
        for metric in ("lease_payments_in_financing", "interest_paid_in_financing")
    )
    addbacks = tuple(
        AddbackObservation(
            addback_id="restructuring",
            addback_label="Restructuring",
            classification="RESTRUCTURING",
            realization_status="REALIZED",
            display_priority=1,
            period_id=pid,
            value=observed(pid + ".restructuring", "3"),
            source_definition="Synthetic",
            classification_citations=(_C,),
        )
        for pid in ("Q1", "Q2")
    )
    value = value.model_copy(
        update={
            "periods": (*value.periods, half),
            "accounts": (*value.accounts, *additions),
            "addbacks": addbacks,
        }
    )
    pack, review = freeze(value)
    regs = kernel_registers(pack, review, value.book_id)
    cols = historical_columns(regs)
    frame = statement_frame(account_frame(regs, cols), cols, regs)
    assert frame["YTD:H1"]["acct:lease_payments_in_financing"].value == -4
    assert frame["YTD:H1"]["addback:restructuring"].value == 6
    assert frame["YTD:H1"]["cfo_adjusted"].value == 112
    missing = value.model_copy(update={"addbacks": (addbacks[0],)})
    pack, review = freeze(missing)
    regs = kernel_registers(pack, review, value.book_id)
    assert (
        account_frame(regs, historical_columns(regs))["YTD:H1"]["addback:restructuring"].value
        is None
    )


def test_sourced_issuance_date_applies_to_every_observation_of_the_facility() -> None:
    value = book()
    dated = facility("Q2").model_copy(
        update={"issued_on": date(2025, 4, 1), "issuance_citations": (_C,)}
    )
    inconsistent = facility("Q1")
    value = value.model_copy(update={"facilities": (inconsistent, dated)})
    assert any("balance precedes issuance" in issue for issue in book_issues(value))


# --- task 7.0d: the sent schema states the account metric vocabulary as an enum ---------------


def test_the_sent_financials_schema_lists_exactly_the_account_metrics() -> None:
    from deploy_vii.cp1_workflow import FinancialSubmission
    from deploy_vii.financial_contracts import ACCOUNT_IDS
    from deploy_vii.live.schema import strict_schema

    sent = strict_schema(FinancialSubmission)
    metric = sent["$defs"]["AccountObservation"]["properties"]["metric_id"]
    assert metric["enum"] == sorted(ACCOUNT_IDS)
    assert len(metric["enum"]) == 36
    assert metric["type"] == "string"  # required and not nullable: no null type, no null member
    assert "metric_id" in sent["$defs"]["AccountObservation"]["required"]
    # The Identifier pattern stays beside the enum and admits every member: no contradiction.
    assert all(re.fullmatch(metric["pattern"], value) for value in metric["enum"])
    # The other metric ids are not this vocabulary and stay free strings.
    for owner in ("ProFormaObservation", "AuditBasisExplanation"):
        assert "enum" not in sent["$defs"][owner]["properties"]["metric_id"], owner


def test_an_unknown_account_metric_is_still_refused_by_the_validator() -> None:
    with pytest.raises(ValidationError, match="unknown CP-1 account metric"):
        AccountObservation(metric_id="restricted_cash", period_id="Q1", value=observed("bad"))
    assert AccountObservation(metric_id="revenue", period_id="Q1", value=observed("ok"))
