"""Synthetic source-bound FX evidence; no live rates or analytical acceptance."""

from datetime import date
from decimal import Decimal, localcontext

import pytest

from deploy_vii.canonical_audit import DefinitionReview, canonical_audit
from deploy_vii.canonical_gaps import _calculation_gaps
from deploy_vii.canonical_kpis import canonical_kpis, validate_canonical_kpis
from deploy_vii.facility_fx import MONETARY_FIELDS, fx_conversion_issues, normalize_facilities
from deploy_vii.financial_adapter import kernel_registers, source_citations
from deploy_vii.financial_contracts import (
    Alternative,
    FacilityFxConversion,
    FinancialBook,
    FinancialReview,
)
from deploy_vii.financial_model import model_report
from deploy_vii.financial_periods import historical_report, validate_historical_report
from deploy_vii.financial_reconciliation import reconcile_financials
from deploy_vii.financial_validation import validate_financial_review
from deploy_vii.model.frame import SourceRef
from deploy_vii.model_readiness import assess_model_readiness
from deploy_vii.period_reconciliation import reconcile_periods
from deploy_vii.preparation import PreparedPack
from tests.product.test_canonical_kpis import kpi
from tests.product.test_financial_periods import entry, frozen
from tests.product.test_financials import _C, observed
from tests.product.test_model_readiness import ready_case


def fx_case() -> FinancialBook:
    book = ready_case()
    facilities = tuple(
        row.model_copy(
            update={
                "currency": "EUR",
                **{
                    field: observed(
                        getattr(row, field).observation_id, str(getattr(row, field).amount / 2)
                    )
                    for field in MONETARY_FIELDS
                    if getattr(row, field).amount is not None
                },
            }
        )
        for row in book.facilities
    )
    periods = {p.period_id: p for p in book.periods}
    quotes = tuple(
        FacilityFxConversion(
            conversion_id="fx-" + row.period_id,
            facility_id=row.facility_id,
            period_id=row.period_id,
            facility_sha256=row.content_hash(),
            source_currency="EUR",
            target_currency="USD",
            rate_date=periods[row.period_id].end_date,
            rate_kind="period_end_spot",
            rate=observed("fx-rate-" + row.period_id, "2"),
            rationale="Synthetic closing quote, two USD per EUR",
            citations=(_C,),
        )
        for row in facilities
    )
    return book.model_copy(update={"facilities": facilities, "facility_fx_conversions": quotes})


def freeze_fx(book: FinancialBook) -> tuple[PreparedPack, FinancialReview]:
    # The existing fixture freezer rewrites source hashes. Bind the FX rows to
    # the resulting frozen facilities, never change production validation.
    pack, review = frozen(book)
    value = review.books[0]
    rows = {(r.facility_id, r.period_id): r for r in value.facilities}
    value = value.model_copy(
        update={
            "facility_fx_conversions": tuple(
                c.model_copy(
                    update={"facility_sha256": rows[c.facility_id, c.period_id].content_hash()}
                )
                for c in value.facility_fx_conversions
            )
        }
    )
    return pack, review.model_copy(update={"books": (value,)})


def test_conversion_reaches_debt_model_readiness_and_provenance() -> None:
    pack, review = freeze_fx(fx_case())
    book = review.books[0]
    original = review.content_hash()
    assert validate_financial_review(pack, review) == ()
    canonical = canonical_kpis(pack, review, book.book_id)
    assert kpi(canonical, "total_debt").value.amount == 100
    assert kpi(canonical, "total_leverage_reported").numerator.amount == 100
    # CP-1 canonical debt deliberately retains the independently reported account.
    assert kpi(canonical, "total_debt").value.value_class == "source"
    historical = canonical.historical
    leaf = entry(historical, "Q:Q4", "fac:loan").value
    assert leaf.amount == 100 and leaf.value_class == "normalized"
    assert leaf.calculation_status == "Calculated"
    assert "fx-rate-Q4" in leaf.observation_ids
    normalization = next(
        n
        for n in historical.facility_normalizations
        if n.normalization_id == leaf.normalization_ids[0]
    )
    assert normalization.original_amount == 50 and normalization.rate == 2
    assert normalization.source_currency == "EUR" and normalization.target_currency == "USD"
    assert normalization.rate_date == date(2025, 12, 31)
    assert normalization.citations == source_citations(
        review, (SourceRef(normalization.normalization_id, "facility-normalization", "100"),)
    )
    assert any(r.normalization_id == normalization.normalization_id for r in historical.input_rows)
    model = model_report(pack, review, book.book_id)
    assert any(v.key == "total_debt" and v.value.amount == 100 for v in model.values)
    assert any(n.value.normalization_ids for n in model.computations)
    source = reconcile_financials(pack, review, book.book_id)
    assert all(c.status == "PASS" for c in source.checks if c.check_type == "DEBT_TOTAL_EX_LEASES")
    assert all(
        c.components[0].normalization
        for c in source.checks
        if c.check_type == "DEBT_TOTAL_EX_LEASES"
    )
    periods = reconcile_periods(pack, review, book.book_id)
    assert all(c.status == "PASS" for c in periods.checks if c.check_type == "DEBT_TOTAL_EX_LEASES")
    assert assess_model_readiness(pack, review, book.book_id).readiness.status == "ready"
    assert validate_canonical_kpis(pack, review, canonical) == ()
    assert review.content_hash() == original


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"facility_sha256": "0" * 64}, "stale facility hash"),
        ({"source_currency": "GBP"}, "currencies"),
        ({"target_currency": "EUR"}, "currencies"),
        ({"rate_date": date(2025, 1, 1)}, "rate date"),
        ({"facility_id": "absent"}, "unknown facility"),
        ({"period_id": "absent"}, "unknown facility"),
        ({"rate": observed("bad-rate", "0")}, "positive"),
        ({"rate": observed("bad-rate", "-2")}, "positive"),
    ],
)
def test_invalid_binding_never_converts(change: dict[str, object], expected: str) -> None:
    book = fx_case()
    book = book.model_copy(
        update={
            "facility_fx_conversions": (
                book.facility_fx_conversions[0].model_copy(update=change),
                *book.facility_fx_conversions[1:],
            )
        }
    )
    assert any(expected in issue for issue in fx_conversion_issues(book))
    with pytest.raises(ValueError, match=expected):
        normalize_facilities(book)


def test_duplicate_and_same_date_disagreement_rejected() -> None:
    book = fx_case()
    quotes = book.facility_fx_conversions
    duplicate = book.model_copy(update={"facility_fx_conversions": (*quotes, quotes[0])})
    assert any("duplicate ID" in i for i in fx_conversion_issues(duplicate))
    assert any("duplicate facility/period" in i for i in fx_conversion_issues(duplicate))
    bad = tuple(
        c.model_copy(update={"rate": observed("fx-rate-FY", "3")}) if c.period_id == "FY" else c
        for c in quotes
    )
    assert any(
        "same-date" in i
        for i in fx_conversion_issues(book.model_copy(update={"facility_fx_conversions": bad}))
    )


@pytest.mark.parametrize("missing", ["conversion", "rate", "conflicting_rate", "amount"])
def test_unknown_fx_never_becomes_native_amount_or_zero(missing: str) -> None:
    book = fx_case()
    if missing == "conversion":
        book = book.model_copy(update={"facility_fx_conversions": ()})
    elif missing in {"rate", "conflicting_rate"}:
        rate = observed("missing-rate", None)
        if missing == "conflicting_rate":
            rate = rate.model_copy(
                update={
                    "status": "conflicting",
                    "alternatives": (
                        Alternative(amount=Decimal(2), citations=(_C,), explanation="First quote"),
                        Alternative(amount=Decimal(3), citations=(_C,), explanation="Second quote"),
                    ),
                }
            )
        book = book.model_copy(
            update={
                "facility_fx_conversions": tuple(
                    c.model_copy(
                        update={
                            "rate": rate.model_copy(
                                update={"observation_id": c.rate.observation_id}
                            )
                        }
                    )
                    if c.period_id == "Q4"
                    else c
                    for c in book.facility_fx_conversions
                )
            }
        )
        # A conflicting alias must null FY as well; a missing alias can use a
        # separately supported same-date quote, so remove FY for missing rate.
        if missing == "rate":
            book = book.model_copy(
                update={
                    "facility_fx_conversions": tuple(
                        c for c in book.facility_fx_conversions if c.period_id != "FY"
                    )
                }
            )
    else:
        book = book.model_copy(
            update={
                "facilities": tuple(
                    r.model_copy(
                        update={"carrying_value": observed(r.carrying_value.observation_id, None)}
                    )
                    for r in book.facilities
                )
            }
        )
    pack, review = freeze_fx(book)
    book = review.books[0]
    regs = kernel_registers(pack, review, book.book_id)
    assert all(r.currency == "USD" for r in regs.facilities)
    assert next(r for r in regs.facilities if r.period_id == "Q4").carrying_value is None
    canonical = canonical_kpis(pack, review, book.book_id)
    assert kpi(canonical, "total_debt").value.amount == 100
    model = model_report(pack, review, book.book_id)
    assert all(
        v.value.amount is None
        for v in model.values
        if v.key == "total_debt"
        and v.basis_id
        == next(
            b.basis_id for b in model.bases if b.column_key == "Q:Q4" and b.scope == "historical"
        )
    )
    assert assess_model_readiness(pack, review, book.book_id).readiness.status == "blocked"
    assert any(n.reason for n in canonical.historical.facility_normalizations)


def test_money_fields_only_and_normalization_even_at_one() -> None:
    book = fx_case()
    row = book.facilities[0]
    row = row.model_copy(
        update={
            "annual_amortisation": observed("amort", "3"),
            "fixed_rate": observed("coupon", "5"),
            "rate_type": "FIXED",
        }
    )
    book = book.model_copy(update={"facilities": (row, *book.facilities[1:])})
    pack, review = freeze_fx(book)
    regs = kernel_registers(pack, review, book.book_id)
    converted = next(r for r in regs.facilities if r.period_id == row.period_id)
    assert converted.annual_amortisation == 6 and converted.fixed_rate == 5
    assert converted.commitment == row.commitment.amount * 2
    book = fx_case()
    unit_rates = tuple(
        c.model_copy(update={"rate": observed(c.rate.observation_id, "1")})
        for c in book.facility_fx_conversions
    )
    # The quote cites the same synthetic locator; rebuild evidence for changed amounts.
    book = book.model_copy(update={"facility_fx_conversions": unit_rates})
    pack, review = freeze_fx(book)
    report = historical_report(pack, review, book.book_id)
    assert entry(report, "Q:Q4", "fac:loan").value.value_class == "normalized"


def test_audit_keeps_original_dimensions_rate_units_gaps_and_tamper_detection() -> None:
    pack, review = freeze_fx(fx_case())
    book = review.books[0]
    definition = DefinitionReview(
        financial_review_sha256=review.content_hash(), book_id=book.book_id
    )
    audit = canonical_audit(pack, review, definition)
    rates = [p for p in audit.source_positions if p.register_id == "facility_fx_conversions"]
    assert rates and all(p.currency is None and p.unit == "USD per EUR" for p in rates)
    assert all(
        p.currency == "EUR"
        for p in audit.source_positions
        if p.register_id == "facilities" and p.field == "carrying_value"
    )
    assert audit.facility_normalizations
    report = historical_report(pack, review, book.book_id)
    altered = report.model_copy(
        update={
            "facility_normalizations": (
                report.facility_normalizations[0].model_copy(update={"amount": Decimal(999)}),
                *report.facility_normalizations[1:],
            )
        }
    )
    assert validate_historical_report(pack, review, altered)
    missing = fx_case().model_copy(update={"facility_fx_conversions": ()})
    pack, review = freeze_fx(missing)
    audit = canonical_audit(
        pack,
        review,
        definition.model_copy(update={"financial_review_sha256": review.content_hash()}),
    )
    assert any(g.origin == "facility_fx" and g.severity == "BLOCK" for g in audit.gaps)


def test_decimal_context_and_negative_debt_adjustment() -> None:
    book = fx_case()
    rows = tuple(
        r.model_copy(
            update={
                "facility_type": "DEBT ADJUSTMENT",
                "carrying_value": observed(r.carrying_value.observation_id, "-3.1234567891"),
            }
        )
        for r in book.facilities
    )
    book = book.model_copy(update={"facilities": rows})
    _pack, review = freeze_fx(book)
    with localcontext() as context:
        context.prec = 3
        normalized = normalize_facilities(review.books[0])
    assert next(n for n in normalized if n.field == "carrying_value").amount == Decimal(
        "-6.2469135782"
    )


def test_missing_rate_gap_keeps_original_evidence_and_explanation() -> None:
    book = fx_case().model_copy(update={"facility_fx_conversions": ()})
    pack, review = freeze_fx(book)
    kpis = canonical_kpis(pack, review, book.book_id)
    periods = reconcile_periods(pack, review, book.book_id)
    gaps = [
        g
        for g in _calculation_gaps(kpis, periods)
        if g.origin == "historical_input" and g.metric == "fac:loan"
    ]
    assert gaps and all(g.citations and "FX conversion" in g.description for g in gaps)
    assert all(g.severity == "BLOCK" for g in gaps)


def test_missing_conversion_identity_changes_with_period_date() -> None:
    book = fx_case().model_copy(update={"facility_fx_conversions": ()})
    before = normalize_facilities(book)[0]
    changed = book.model_copy(
        update={
            "periods": tuple(
                p.model_copy(update={"end_date": date(2024, 12, 30)})
                if p.period_id == before.period_id
                else p
                for p in book.periods
            )
        }
    )
    after = normalize_facilities(changed)[0]
    assert before.rate_date != after.rate_date
    assert before.normalization_id != after.normalization_id


def test_large_alias_evidence_expansion_rejected_before_materialization() -> None:
    book = fx_case()
    period = book.periods[0]
    periods = tuple(
        period.model_copy(update={"period_id": f"p{i}", "period_type": "PERIOD_END"})
        for i in range(200)
    )
    template = book.facilities[0]
    quote = book.facility_fx_conversions[0]
    rows = tuple(
        template.model_copy(update={"facility_id": f"f{i}", "period_id": p.period_id})
        for i, count in enumerate((199, 199, 199, 199, 199, 31, 2, 1, 1))
        for p in periods[:count]
    )
    quotes = tuple(
        quote.model_copy(
            update={
                "conversion_id": f"{r.facility_id}-{r.period_id}",
                "facility_id": r.facility_id,
                "period_id": r.period_id,
                "facility_sha256": r.content_hash(),
                "rate_date": period.end_date,
            }
        )
        for r in rows
    )
    book = book.model_copy(
        update={"periods": periods, "facilities": rows, "facility_fx_conversions": quotes}
    )
    # The first eight groups expand to exactly 1m pre-dedup input references.
    at_limit = book.model_copy(
        update={"facilities": rows[:-1], "facility_fx_conversions": quotes[:-1]}
    )
    assert fx_conversion_issues(at_limit) == ()
    assert fx_conversion_issues(book) == ("Expanded facility FX inputs exceed 1000000 references",)
    with pytest.raises(ValueError, match="Expanded facility FX"):
        normalize_facilities(book)


def test_same_date_source_conflict_cannot_be_bypassed_by_known_alias() -> None:
    book = fx_case()
    rows = tuple(
        r.model_copy(
            update={
                "carrying_value": observed(r.carrying_value.observation_id, None).model_copy(
                    update={
                        "status": "conflicting",
                        "alternatives": (
                            Alternative(
                                amount=Decimal(50), citations=(_C,), explanation="First amount"
                            ),
                            Alternative(
                                amount=Decimal(60), citations=(_C,), explanation="Second amount"
                            ),
                        ),
                    }
                )
            }
        )
        if r.period_id == "Q4"
        else r
        for r in book.facilities
    )
    pack, review = freeze_fx(book.model_copy(update={"facilities": rows}))
    regs = kernel_registers(pack, review, book.book_id)
    assert all(r.carrying_value is None for r in regs.facilities if r.period_id in {"Q4", "FY"})
    assert all(
        n.amount is None and "conflicting" in n.reason
        for n in normalize_facilities(review.books[0])
        if n.field == "carrying_value" and n.period_id in {"Q4", "FY"}
    )


def test_zero_without_rate_stays_unknown_and_native_conversion_is_rejected() -> None:
    book = fx_case()
    rows = tuple(
        r.model_copy(update={"carrying_value": observed(r.carrying_value.observation_id, "0")})
        for r in book.facilities
    )
    book = book.model_copy(update={"facilities": rows, "facility_fx_conversions": ()})
    values = normalize_facilities(book)
    assert all(
        n.amount is None and n.original_amount == 0 for n in values if n.field == "carrying_value"
    )
    book = fx_case()
    book = book.model_copy(update={"currency": "EUR"})
    assert any("currencies" in issue for issue in fx_conversion_issues(book))


def test_stale_hash_and_non_spot_rate_rejected_at_public_boundary() -> None:
    from pydantic import ValidationError

    pack, review = freeze_fx(fx_case())
    book = review.books[0]
    row = book.facilities[0]
    changed = row.model_copy(update={"facility_name": "Changed source terms"})
    forged = review.model_copy(
        update={"books": (book.model_copy(update={"facilities": (changed, *book.facilities[1:])}),)}
    )
    assert any("stale facility hash" in i for i in validate_financial_review(pack, forged))
    with pytest.raises(ValueError, match="stale facility hash"):
        historical_report(pack, forged, book.book_id)
    data = book.facility_fx_conversions[0].model_dump(mode="json")
    data["rate_kind"] = "annual_average"
    with pytest.raises(ValidationError):
        FacilityFxConversion.model_validate_json(__import__("json").dumps(data))
