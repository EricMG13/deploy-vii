"""Python-owned display formatting (decision 0004 sections 4 and 5)."""

import re
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.display import format_value

# Independent oracle: literal strings from decision 0004 sections 4-5 and DS-04/DS-07.
ORACLE = [
    (Decimal("11648"), "amount", "known", {}, "11,648"),
    (Decimal("-62"), "amount", "known", {}, "(62)"),
    (Decimal("3.29"), "multiple", "known", {}, "3.29x"),
    (Decimal("0.308"), "percent", "known", {}, "30.8%"),
    (Decimal("-1.4"), "pp", "known", {}, "(1.4)pp"),
    (None, "date", "known", {"as_of": date(2026, 10, 2)}, "2 Oct 2026"),
    (None, "amount", "gap", {"gap_id": "G8"}, "∅ G8"),
    (None, "multiple", "not_meaningful", {"gap_id": "G41"}, "∅ G41 n.m."),
    (None, "amount", "blocked", {}, "—"),
    (
        None,
        "amount",
        "not_evaluated",
        {"reason": "CP-3 did not run"},
        "Not evaluated: CP-3 did not run",
    ),
    (
        Decimal("11648"),
        "amount",
        "stale",
        {"as_of": date(2026, 10, 2)},
        "⏱ 11,648 as of 2 Oct 2026",
    ),
    # ROUND_HALF_UP on the exact decimal, never binary floats or banker's rounding.
    (Decimal("0.5"), "amount", "known", {}, "1"),
    (Decimal("-0.5"), "amount", "known", {}, "(1)"),
    (Decimal("2.5"), "amount", "known", {}, "3"),
    (Decimal("2.675"), "multiple", "known", {}, "2.68x"),
    (Decimal("0.3075"), "percent", "known", {}, "30.8%"),
    (Decimal("-0.4"), "amount", "known", {}, "0"),  # no negative zero
    (Decimal("1234567.5"), "amount", "known", {}, "1,234,568"),
    (Decimal("-0.0314"), "percent", "known", {}, "(3.1)%"),
    (Decimal("-0.5"), "multiple", "known", {}, "(0.50)x"),
    # An explicit precision keeps a per-share amount's cents (FP 01: "US$31.00 per share").
    (Decimal("0.4"), "amount", "known", {"decimals": 2}, "0.40"),
    (Decimal("31"), "amount", "known", {"decimals": 2}, "31.00"),
    (Decimal("-1234.565"), "amount", "known", {"decimals": 2}, "(1,234.57)"),
    (Decimal("0.4"), "amount", "known", {"decimals": 0}, "0"),
    (None, "amount", "gap", {"gap_id": "G3", "decimals": 2}, "∅ G3"),
    (None, "text", "known", {"text": "Pass"}, "Pass"),
    (None, "date", "known", {"as_of": date(2026, 1, 31)}, "31 Jan 2026"),
]


@pytest.mark.parametrize(("amount", "unit", "state", "kwargs", "expected"), ORACLE)
def test_display_oracle_matches_design_system_examples(
    amount: Decimal | None, unit: str, state: str, kwargs: dict[str, object], expected: str
) -> None:
    assert format_value(amount, unit, state, **kwargs) == expected  # type: ignore[arg-type]


def test_wide_values_round_half_up_without_the_default_28_digit_context() -> None:
    # 30 significant digits: a 28-digit intermediate product would round the tie away.
    assert format_value(Decimal("12345678901234567890123456784.5"), "amount", "known") == (
        "12,345,678,901,234,567,890,123,456,785"
    )
    # Scaling by 100 for percent also needs the wide context: ...567.85 must end ...567.9%.
    assert format_value(Decimal("1234567890123456789012345.6785"), "percent", "known") == (
        "123,456,789,012,345,678,901,234,567.9%"
    )
    assert format_value(Decimal("-12345678901234567890123456784.5"), "amount", "known") == (
        "(12,345,678,901,234,567,890,123,456,785)"
    )


@pytest.mark.parametrize("unit", ["amount", "percent"])
def test_a_value_wider_than_the_context_fails_closed_instead_of_rounding_early(unit: str) -> None:
    # 0.4999... (130 nines) is below the half-way point; rounding it to 120 digits first
    # would turn it into 0.5 and display "1".
    below_half = Decimal("0." + "4" + "9" * 130)
    with pytest.raises(ValueError, match="exactly"):
        format_value(below_half, unit, "known")


@pytest.mark.parametrize(
    ("amount", "unit", "state", "kwargs"),
    [
        (None, "amount", "known", {}),
        (Decimal("1"), "amount", "gap", {}),
        (None, "amount", "gap", {}),
        (None, "amount", "gap", {"gap_id": "8"}),
        (None, "amount", "not_meaningful", {}),
        (None, "amount", "not_evaluated", {}),
        (Decimal("1"), "amount", "stale", {}),
        (None, "amount", "stale", {"as_of": date(2026, 10, 2)}),
        (Decimal("1"), "date", "stale", {"as_of": date(2026, 10, 2)}),
        (Decimal("1e500"), "amount", "known", {}),
        (Decimal("NaN"), "amount", "known", {}),
        (Decimal("Infinity"), "amount", "known", {}),
        (Decimal("1"), "date", "known", {}),
        (Decimal("1"), "text", "known", {}),
        (None, "text", "known", {}),
        (None, "text", "known", {"text": ""}),
        (Decimal("1"), "amount", "bogus", {}),
        (None, "amount", "bogus", {}),
        (Decimal("1"), "bogus", "known", {}),
    ],
)
def test_incomplete_or_contradictory_inputs_fail_closed(
    amount: Decimal | None, unit: str, state: str, kwargs: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        format_value(amount, unit, state, **kwargs)  # type: ignore[arg-type]


def test_display_never_spells_null() -> None:
    for state, kwargs in (
        ("gap", {"gap_id": "G1"}),
        ("not_meaningful", {"gap_id": "G1"}),
        ("blocked", {}),
        ("not_evaluated", {"reason": "x"}),
    ):
        assert "null" not in format_value(None, "amount", state, **kwargs).lower()  # type: ignore[arg-type]


def parse_amount(text: str) -> Decimal:
    negative = text.startswith("(") and text.endswith(")")
    value = Decimal(text.strip("()").replace(",", ""))
    return -value if negative else value


SOURCE = st.decimals(
    min_value=Decimal("-1e12"), max_value=Decimal("1e12"), places=6, allow_nan=False
)


@settings(deadline=None, max_examples=300)
@given(SOURCE)
def test_amount_round_trips_to_the_quantized_source(value: Decimal) -> None:
    shown = format_value(value, "amount", "known")
    assert re.fullmatch(r"\(?\d{1,3}(,\d{3})*\)?", shown)
    expected = value.quantize(Decimal(1), rounding="ROUND_HALF_UP")
    assert parse_amount(shown) == expected
    if expected != 0:
        assert shown.startswith("(") == (value < 0)


@settings(deadline=None, max_examples=300)
@given(SOURCE)
def test_multiple_percent_and_pp_round_trip(value: Decimal) -> None:
    multiple = format_value(value, "multiple", "known")
    assert parse_amount(multiple.removesuffix("x").replace(",", "")) == value.quantize(
        Decimal("0.01"), rounding="ROUND_HALF_UP"
    )
    percent = format_value(value, "percent", "known")
    assert parse_amount(percent.removesuffix("%")) == (value * 100).quantize(
        Decimal("0.1"), rounding="ROUND_HALF_UP"
    )
    pp = format_value(value, "pp", "known")
    assert parse_amount(pp.removesuffix("pp")) == value.quantize(
        Decimal("0.1"), rounding="ROUND_HALF_UP"
    )
