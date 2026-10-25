"""Task PF-1: the user-supplied portfolio workbook (`portfolio`) and its validator.

Workbooks here are written by openpyxl, an independent OOXML writer, so the validator is
exercised on bytes it did not produce. Every row is synthetic: a fictional fund and fictional
issuers, no market or fund data.
"""

import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from deploy_vii.contracts import Source
from deploy_vii.inputs.portfolio import (
    FIXES,
    MEDIA_TYPE,
    SHEETS,
    PortfolioRefused,
    PortfolioReport,
    portfolio_facts,
    validate_portfolio,
    validate_portfolio_bytes,
)
from deploy_vii.preparation import SourceRequest, prepare_source

FILE = "portfolio.xlsx"
TEMPLATE_PATH = "docs/templates/portfolio.template.xlsx"
# The brief's contract, stated here independently of the module's constants.
BRIEF_SHEETS: dict[str, tuple[str, ...]] = {
    "Mandate": ("section", "field", "value", "notes"),
    "Exposure_Summary": ("metric", "value", "unit", "as_of"),
    "Rating_Distribution": ("rating_bucket", "pct_nav", "issuers"),
    "Sector_Exposure": (
        "sector",
        "pct_nav",
        "issuers",
        "limit_pct_nav",
        "headroom_pct_nav",
        "status",
    ),
    "Top_Holdings": ("rank", "issuer", "instrument", "pct_nav", "rating"),
    "Maturity_Profile": ("bucket", "pct_nav"),
    "Compliance_Monitor": (
        "id",
        "constraint_category",
        "parameter",
        "limit",
        "limit_unit",
        "breach_type",
        "scope",
        "source_document",
        "current_value",
        "headroom",
        "status",
        "last_checked",
        "checked_by",
    ),
    "Holdings_Detail": (
        "issuer",
        "instrument",
        "facility_id",
        "par",
        "market_value",
        "pct_nav",
        "rating",
        "sector",
        "seniority",
        "maturity",
    ),
}
OPTIONAL_COLUMNS = {
    "Mandate": {"notes"},
    "Sector_Exposure": {"limit_pct_nav", "headroom_pct_nav", "status"},
}


def mandate(section: str, field: str, value: object, notes: object = None) -> dict[str, Any]:
    return {"section": section, "field": field, "value": value, "notes": notes}


def control(**values: object) -> dict[str, Any]:
    row = {
        "id": "C-01",
        "constraint_category": "Single Name",
        "parameter": "Max single issuer exposure",
        "limit": "2.5",
        "limit_unit": "% NAV",
        "breach_type": "Hard",
        "scope": "issuer",
        "source_document": "Indenture s7.11 (synthetic)",
        "current_value": "2.37",
        "headroom": "0.13",
        "status": "Watch",
        "last_checked": "2026-05-29",
        "checked_by": "analyst",
    }
    return row | values


def valid() -> dict[str, list[dict[str, Any]]]:
    """A small valid synthetic portfolio, independent of the template builder. Row numbers:
    Mandate nav is C4, nav_currency C5; Exposure_Summary nav is row 2."""
    return {
        "Mandate": [
            mandate("Strategy", "fund_name", "Example Fund I (synthetic)"),
            mandate("Strategy", "strategy", "CLO", "synthetic"),
            mandate("Capital Structure", "nav", 1000),
            mandate("Capital Structure", "nav_currency", "USD"),
            mandate("Reporting", "as_of", "2026-05-29"),
            mandate("Key Parties", "trustee", "Synthetic Trustee Bank"),
        ],
        "Exposure_Summary": [
            {"metric": "nav", "value": "1000.00", "unit": "USD", "as_of": "2026-05-29"},
            {"metric": "obligors", "value": 12, "unit": "count", "as_of": "2026-05-29"},
        ],
        "Rating_Distribution": [
            {"rating_bucket": "B", "pct_nav": "60.5", "issuers": 8},
            {"rating_bucket": "BB", "pct_nav": 39.5, "issuers": "4"},
        ],
        "Sector_Exposure": [
            {
                "sector": "Software",
                "pct_nav": "7.16",
                "issuers": 5,
                "limit_pct_nav": "10.0",
                "headroom_pct_nav": "2.84",
                "status": "Pass",
            },
            {"sector": "Insurance", "pct_nav": "5", "issuers": 2},
        ],
        "Top_Holdings": [
            {
                "rank": 1,
                "issuer": "Alpha Example Holdings (synthetic)",
                "instrument": "Term Loan B due 2030",
                "pct_nav": "2.37",
                "rating": "B3 / B",
            },
            {
                "rank": "2",
                "issuer": "Beta Sample Industries (synthetic)",
                "instrument": "Senior Secured Notes due 2032",
                "pct_nav": "1.91",
                "rating": "Ba3 / BB-",
            },
        ],
        "Maturity_Profile": [
            {"bucket": "3-5 Years", "pct_nav": "40"},
            {"bucket": "5-7 Years", "pct_nav": "60"},
        ],
        "Compliance_Monitor": [
            control(),
            control(
                id="SECTOR",
                constraint_category="Sector",
                parameter="Max single sector",
                limit="10.0",
                breach_type="Soft",
                scope="sector",
                current_value="4.57",
                headroom="5.43",
                status="Pass",
            ),
        ],
    }


HOLDING = {
    "issuer": "Alpha Example Holdings (synthetic)",
    "instrument": "Term Loan B due 2030",
    "facility_id": "TLB-2030",
    "par": "15000000",
    "market_value": "14951250",
    "pct_nav": "2.37",
    "rating": "B3 / B",
    "sector": "Software",
    "seniority": "1st Lien",
    "maturity": "2030-06-30",
}


def workbook(
    data: dict[str, list[dict[str, Any]]],
    *,
    headers: dict[str, tuple[str, ...]] | None = None,
) -> bytes:
    book = openpyxl.Workbook()
    first = book.active
    assert first is not None
    book.remove(first)
    for name, rows in data.items():
        sheet = book.create_sheet(name)
        header = (headers or {}).get(name, BRIEF_SHEETS.get(name, ()))
        if header:
            sheet.append(list(header))
        for row in rows:
            sheet.append([row.get(column) for column in header or BRIEF_SHEETS[name]])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def check(
    data: dict[str, list[dict[str, Any]]], headers: dict[str, tuple[str, ...]] | None = None
) -> PortfolioReport:
    return validate_portfolio_bytes(FILE, workbook(data, headers=headers))


def rendered(report: PortfolioReport) -> list[str]:
    return [issue.render() for issue in report.issues]


def changed(sheet: str, index: int, change: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    data = valid()
    data[sheet][index] = data[sheet][index] | change
    return data


def test_contract_is_the_briefs() -> None:
    assert tuple(sheet.name for sheet in SHEETS) == tuple(BRIEF_SHEETS)
    for sheet in SHEETS:
        assert tuple(column.name for column in sheet.columns) == BRIEF_SHEETS[sheet.name]
        optional = {column.name for column in sheet.columns if not column.required}
        assert optional == OPTIONAL_COLUMNS.get(sheet.name, set()), sheet.name
    assert [sheet.name for sheet in SHEETS if sheet.optional] == ["Holdings_Detail"]
    assert MEDIA_TYPE == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_a_valid_workbook_is_ok_with_sheet_and_compliance_counts() -> None:
    report = check(valid())
    assert rendered(report) == []
    assert report.ok
    assert (report.sheets, report.compliance_rows, report.rows) == (7, 2, 18)
    assert report.lines() == ("OK: 7 sheets, 2 compliance rows",)


def test_the_optional_holdings_sheet_is_counted_when_present() -> None:
    report = check(valid() | {"Holdings_Detail": [HOLDING]})
    assert rendered(report) == []
    assert report.lines() == ("OK: 8 sheets, 2 compliance rows",)


NUMBER_FIX = (
    "enter a plain number: digits, an optional sign and one decimal point "
    "(no %, units, spaces or thousands separators)"
)
DATE_FIX = "enter the date as text YYYY-MM-DD (format the column as Text so Excel keeps it)"
PCT_FIX = "enter the share of NAV in percent as a plain number (2.5 means 2.5 % NAV)"
COUNT_FIX = "enter the number of issuers as a whole number of at least 0, e.g. 12"
STATUS_FIX = "enter Pass, Watch or Breach"
FORMULA_FIX = "replace the formula with its value (Paste Special, Values)"
SECTIONS = (
    "Strategy, Key Parties, Capital Structure, Mandate Constraints, Liquidity Terms, Fees "
    "or Reporting"
)
SCOPES = (
    "issuer, rating_bucket, sector, seniority, instrument, duration, diversification, "
    "yield, pricing, covenant, esg or other"
)


@pytest.mark.parametrize(
    "sheet, index, change, cell, problem, fix",
    [
        (
            "Mandate",
            5,
            {"section": "Parties"},
            "A7",
            f"section 'Parties' is not one of {SECTIONS}",
            f"enter one of {SECTIONS}",
        ),
        ("Mandate", 5, {"section": None}, "A7", "section is empty", f"enter one of {SECTIONS}"),
        (
            "Mandate",
            5,
            {"field": None},
            "B7",
            "field is empty",
            "enter the field's name, e.g. fund_name",
        ),
        (
            "Mandate",
            5,
            {"value": " "},
            "C7",
            "value is empty",
            "enter the field's value, or delete the row",
        ),
        (
            "Mandate",
            1,
            {"value": "Loans"},
            "C3",
            "strategy 'Loans' is not one of CLO, Indexed Loans, Indexed HY or Other",
            "enter one of CLO, Indexed Loans, Indexed HY or Other",
        ),
        ("Mandate", 2, {"value": "1,000"}, "C4", "nav '1,000' is not a number", NUMBER_FIX),
        (
            "Mandate",
            2,
            {"value": "0"},
            "C4",
            "nav 0 is not above 0",
            "enter the fund's NAV, a number above 0",
        ),
        (
            "Mandate",
            3,
            {"value": "US$"},
            "C5",
            "nav_currency 'US$' is not a three-letter ISO 4217 code",
            "enter the three-letter upper-case ISO 4217 code, e.g. USD",
        ),
        (
            "Mandate",
            4,
            {"value": "29-May-2026"},
            "C6",
            "as_of '29-May-2026' is not an ISO date YYYY-MM-DD",
            DATE_FIX,
        ),
        (
            "Mandate",
            4,
            {"value": 46171},
            "C6",
            "as_of '46171' is an Excel date serial, not an ISO date YYYY-MM-DD",
            DATE_FIX,
        ),
        (
            "Exposure_Summary",
            1,
            {"metric": None},
            "A3",
            "metric is empty",
            "enter the metric's name, e.g. nav",
        ),
        (
            "Exposure_Summary",
            1,
            {"value": "350 obligors"},
            "B3",
            "value '350 obligors' is not a number",
            NUMBER_FIX,
        ),
        (
            "Exposure_Summary",
            1,
            {"value": None},
            "B3",
            "value is empty",
            "enter the metric's value as a plain number",
        ),
        (
            "Exposure_Summary",
            1,
            {"unit": None},
            "C3",
            "unit is empty",
            "enter the unit, e.g. USD, % NAV, years or count",
        ),
        (
            "Exposure_Summary",
            1,
            {"as_of": "2026-13-01"},
            "D3",
            "as_of '2026-13-01' is not an ISO date YYYY-MM-DD",
            DATE_FIX,
        ),
        (
            "Rating_Distribution",
            0,
            {"rating_bucket": None},
            "A2",
            "rating_bucket is empty",
            "enter the rating bucket, e.g. B or Unrated",
        ),
        ("Rating_Distribution", 0, {"pct_nav": None}, "B2", "pct_nav is empty", PCT_FIX),
        (
            "Rating_Distribution",
            0,
            {"issuers": "-1"},
            "C2",
            "issuers '-1' is not a whole number of at least 0",
            COUNT_FIX,
        ),
        (
            "Rating_Distribution",
            0,
            {"issuers": "8.5"},
            "C2",
            "issuers '8.5' is not a whole number of at least 0",
            COUNT_FIX,
        ),
        (
            "Sector_Exposure",
            0,
            {"sector": None},
            "A2",
            "sector is empty",
            "enter the sector's name",
        ),
        (
            "Sector_Exposure",
            0,
            {"pct_nav": "7.16%"},
            "B2",
            "pct_nav '7.16%' is not a number",
            NUMBER_FIX,
        ),
        ("Sector_Exposure", 1, {"issuers": None}, "C3", "issuers is empty", COUNT_FIX),
        (
            "Sector_Exposure",
            0,
            {"limit_pct_nav": "≤ 10.0%"},
            "D2",
            "limit_pct_nav '≤ 10.0%' is not a number",
            NUMBER_FIX,
        ),
        (
            "Sector_Exposure",
            0,
            {"status": "OK"},
            "F2",
            "status 'OK' is not Pass, Watch or Breach",
            STATUS_FIX,
        ),
        (
            "Top_Holdings",
            0,
            {"rank": "0"},
            "A2",
            "rank '0' is not a whole number of at least 1",
            "number the holdings 1, 2, 3 and so on, with no gaps or repeats",
        ),
        ("Top_Holdings", 0, {"issuer": None}, "B2", "issuer is empty", "enter the issuer's name"),
        (
            "Top_Holdings",
            0,
            {"instrument": None},
            "C2",
            "instrument is empty",
            "describe the instrument, e.g. Term Loan B due 2030",
        ),
        ("Top_Holdings", 0, {"pct_nav": "n/a"}, "D2", "pct_nav 'n/a' is not a number", NUMBER_FIX),
        (
            "Top_Holdings",
            0,
            {"rating": None},
            "E2",
            "rating is empty",
            "enter the rating as reported, e.g. B2 / B",
        ),
        (
            "Maturity_Profile",
            0,
            {"bucket": None},
            "A2",
            "bucket is empty",
            "enter the maturity bucket, e.g. 3-5 Years",
        ),
        (
            "Maturity_Profile",
            1,
            {"pct_nav": "1e5000"},
            "B3",
            "pct_nav '1e5000' is not a number",
            NUMBER_FIX,
        ),
        (
            "Compliance_Monitor",
            0,
            {"id": "C1"},
            "A2",
            "id 'C1' is not of the form C-01 or SECTOR",
            "enter an id such as C-01 (capital letters, a hyphen, two digits), or SECTOR for "
            "the sector-limit row",
        ),
        (
            "Compliance_Monitor",
            0,
            {"constraint_category": None},
            "B2",
            "constraint_category is empty",
            "enter the constraint category, e.g. Single Name",
        ),
        (
            "Compliance_Monitor",
            0,
            {"parameter": None},
            "C2",
            "parameter is empty",
            "describe the constraint, e.g. Max single issuer exposure",
        ),
        (
            "Compliance_Monitor",
            0,
            {"limit": "≤ 2.5% NAV"},
            "D2",
            "limit '≤ 2.5% NAV' is not a number",
            NUMBER_FIX,
        ),
        (
            "Compliance_Monitor",
            0,
            {"limit_unit": "%NAV"},
            "E2",
            "limit_unit '%NAV' is not % NAV or a three-letter currency code",
            "enter % NAV, or the Mandate nav_currency code (e.g. USD) for an amount limit",
        ),
        (
            "Compliance_Monitor",
            0,
            {"breach_type": "—"},
            "F2",
            "breach_type '—' is not Hard or Soft",
            "enter Hard or Soft",
        ),
        (
            "Compliance_Monitor",
            0,
            {"scope": "Issuer"},
            "G2",
            f"scope 'Issuer' is not one of {SCOPES}",
            f"enter one of {SCOPES}",
        ),
        (
            "Compliance_Monitor",
            0,
            {"source_document": None},
            "H2",
            "source_document is empty",
            "enter the document that sets the limit, e.g. Indenture s7.11",
        ),
        (
            "Compliance_Monitor",
            0,
            {"current_value": None},
            "I2",
            "current_value is empty",
            "enter the current exposure as a plain number in limit_unit",
        ),
        (
            "Compliance_Monitor",
            0,
            {"headroom": "0.13%"},
            "J2",
            "headroom '0.13%' is not a number",
            NUMBER_FIX,
        ),
        (
            "Compliance_Monitor",
            0,
            {"status": None},
            "K2",
            "status is empty",
            STATUS_FIX,
        ),
        (
            "Compliance_Monitor",
            0,
            {"last_checked": "29-May-2026"},
            "L2",
            "last_checked '29-May-2026' is not an ISO date YYYY-MM-DD",
            DATE_FIX,
        ),
        (
            "Compliance_Monitor",
            0,
            {"checked_by": None},
            "M2",
            "checked_by is empty",
            "enter who checked the row, e.g. analyst",
        ),
        (
            "Compliance_Monitor",
            0,
            {"limit": "=2+0.5"},
            "D2",
            "limit holds a formula; prepare freezes stored values and never recalculates",
            FORMULA_FIX,
        ),
    ],
)
def test_each_column_rule_fails_with_its_exact_message(
    sheet: str, index: int, change: dict[str, Any], cell: str, problem: str, fix: str
) -> None:
    report = check(changed(sheet, index, change))
    assert rendered(report) == [f"{FILE}:{sheet}!{cell}: {problem} — fix: {fix}"]
    assert report.lines()[-1] == "FAILED: 1 issues"


@pytest.mark.parametrize(
    "column, change, cell, problem, fix",
    [
        ("issuer", None, "A2", "issuer is empty", "enter the issuer's name"),
        (
            "facility_id",
            "TLB 2030",
            "C2",
            "facility_id 'TLB 2030' has characters other than letters, digits, - and _",
            "enter the facility's id using letters, digits, - and _ only, e.g. TLB-2030",
        ),
        ("par", "15,000,000", "D2", "par '15,000,000' is not a number", NUMBER_FIX),
        (
            "market_value",
            None,
            "E2",
            "market_value is empty",
            "enter the market value as a plain number",
        ),
        (
            "seniority",
            None,
            "I2",
            "seniority is empty",
            "enter the seniority, e.g. 1st Lien",
        ),
        (
            "maturity",
            47664,
            "J2",
            "maturity '47664' is an Excel date serial, not an ISO date YYYY-MM-DD",
            DATE_FIX,
        ),
    ],
)
def test_holdings_detail_column_rules(
    column: str, change: object, cell: str, problem: str, fix: str
) -> None:
    report = check(valid() | {"Holdings_Detail": [HOLDING | {column: change}]})
    assert rendered(report) == [f"{FILE}:Holdings_Detail!{cell}: {problem} — fix: {fix}"]


@pytest.mark.parametrize(
    "field, row, fix",
    [
        ("fund_name", 0, "add a row: section Strategy, field fund_name, value the fund's name"),
        (
            "strategy",
            1,
            "add a row: section Strategy, field strategy, value CLO, Indexed Loans, Indexed HY "
            "or Other",
        ),
        (
            "nav",
            2,
            "add a row: section Capital Structure, field nav, value the fund's NAV as a plain "
            "number",
        ),
        (
            "nav_currency",
            3,
            "add a row: section Capital Structure, field nav_currency, value the NAV's "
            "three-letter currency code, e.g. USD",
        ),
        (
            "as_of",
            4,
            "add a row: section Reporting, field as_of, value the NAV and compliance date as "
            "text YYYY-MM-DD",
        ),
    ],
)
def test_a_missing_required_mandate_field_is_one_issue(field: str, row: int, fix: str) -> None:
    data = valid()
    section = data["Mandate"][row]["section"]
    del data["Mandate"][row]
    report = check(data)
    assert rendered(report) == [
        f"{FILE}:Mandate!A7: no {section} row with field {field} — fix: {fix}"
    ]


def test_a_required_field_in_the_wrong_section_is_missing() -> None:
    report = check(changed("Mandate", 4, {"section": "Strategy"}))
    assert [issue.problem for issue in report.issues] == ["no Reporting row with field as_of"]


def test_a_repeated_mandate_field_is_one_issue_on_the_later_row() -> None:
    data = valid()
    data["Mandate"].append(mandate("Capital Structure", "nav", 1000))
    assert rendered(check(data)) == [
        f"{FILE}:Mandate!A8:B8: duplicates row 4 on section and field — fix: keep one row per "
        "section and field, or correct the repeated value"
    ]


def test_exposure_nav_must_equal_the_mandate_nav() -> None:
    assert rendered(check(changed("Exposure_Summary", 0, {"value": "1000.01"}))) == [
        f"{FILE}:Exposure_Summary!B2: nav 1000.01 is not the Mandate nav 1000 (Mandate!C4)"
        " — fix: enter the same NAV on Exposure_Summary and Mandate"
    ]
    # Same number, different lexeme: equal as decimals.
    assert rendered(check(changed("Exposure_Summary", 0, {"value": "1e3"}))) == []


def test_exposure_nav_unit_must_be_the_mandate_currency() -> None:
    assert rendered(check(changed("Exposure_Summary", 0, {"unit": "EUR"}))) == [
        f"{FILE}:Exposure_Summary!C2: unit 'EUR' of nav is not the Mandate nav_currency USD"
        " — fix: enter the nav row's unit as the Mandate nav_currency, e.g. USD"
    ]


def test_exposure_without_nav_is_one_issue() -> None:
    data = valid()
    del data["Exposure_Summary"][0]
    assert rendered(check(data)) == [
        f"{FILE}:Exposure_Summary!A3: no metric nav — fix: add a row: metric nav, value the "
        "fund's NAV (the Mandate nav), unit the nav_currency, as_of the NAV date"
    ]


def test_one_pct_nav_is_computed_never_supplied() -> None:
    data = valid()
    data["Exposure_Summary"].append(
        {"metric": "one_pct_nav", "value": "10", "unit": "USD", "as_of": "2026-05-29"}
    )
    assert rendered(check(data)) == [
        f"{FILE}:Exposure_Summary!A4: one_pct_nav is computed from nav and is not supplied"
        " — fix: delete the one_pct_nav row; Python computes 1 % of NAV from nav"
    ]


def test_a_repeated_metric_is_one_issue() -> None:
    data = valid()
    data["Exposure_Summary"].append(data["Exposure_Summary"][1])
    assert [issue.render() for issue in check(data).issues] == [
        f"{FILE}:Exposure_Summary!A4: duplicates row 3 on metric — fix: keep one row per "
        "metric, or correct the repeated value"
    ]


@pytest.mark.parametrize(
    "rows, ok",
    [
        ([("B", "60"), ("BB", "39")], True),
        ([("B", "60"), ("BB", "41")], True),
        ([("B", "60"), ("BB", "38.99")], False),
        ([("B", "60"), ("BB", "41.01")], False),
        ([("B", "60"), ("BB", "30"), ("Unallocated", "10")], True),
    ],
)
def test_rating_distribution_sums_to_between_99_and_101(
    rows: list[tuple[str, str]], ok: bool
) -> None:
    data = valid()
    data["Rating_Distribution"] = [
        {"rating_bucket": bucket, "pct_nav": pct, "issuers": 1} for bucket, pct in rows
    ]
    report = check(data)
    if ok:
        assert rendered(report) == []
    else:
        total = sum((Decimal(pct) for _, pct in rows), Decimal(0))
        assert rendered(report) == [
            f"{FILE}:Rating_Distribution!B2:B3: pct_nav sums to {total}, outside 99.0 to 101.0"
            " — fix: correct the percentages, or add a row Unallocated with the remainder of NAV"
        ]


@pytest.mark.parametrize(
    "sheet, column, label, cell",
    [
        ("Rating_Distribution", "rating_bucket", "Total", "A2"),
        ("Sector_Exposure", "sector", "Top 20 Subtotal", "A2"),
        ("Maturity_Profile", "bucket", "total", "A2"),
    ],
)
def test_total_rows_are_refused(sheet: str, column: str, label: str, cell: str) -> None:
    report = check(changed(sheet, 0, {column: label}))
    assert rendered(report) == [
        f"{FILE}:{sheet}!{cell}: {column} '{label}' is a total row — fix: leave out total and "
        "subtotal rows; Python adds the rows up"
    ]


@pytest.mark.parametrize(
    "sheet, column, letter",
    [
        ("Rating_Distribution", "rating_bucket", "A"),
        ("Sector_Exposure", "sector", "A"),
        ("Maturity_Profile", "bucket", "A"),
        ("Top_Holdings", "rank", "A"),
    ],
)
def test_repeated_keys_are_one_issue(sheet: str, column: str, letter: str) -> None:
    data = valid()
    data[sheet][1] = data[sheet][1] | {column: data[sheet][0][column]}
    if sheet == "Rating_Distribution":
        data[sheet][1]["pct_nav"] = "39.5"
    assert rendered(check(data)) == [
        f"{FILE}:{sheet}!{letter}3: duplicates row 2 on {column} — fix: keep one row per "
        f"{column}, or correct the repeated value"
    ]


def test_ranks_must_run_from_one_without_gaps() -> None:
    report = check(changed("Top_Holdings", 1, {"rank": 3}))
    assert rendered(report) == [
        f"{FILE}:Top_Holdings!A2:A3: ranks are not 1 to 2: 2 missing — fix: number the "
        "holdings 1, 2, 3 and so on, with no gaps or repeats"
    ]


def test_holdings_detail_repeated_facility_is_one_issue() -> None:
    report = check(valid() | {"Holdings_Detail": [HOLDING, HOLDING]})
    assert rendered(report) == [
        f"{FILE}:Holdings_Detail!C3: duplicates row 2 on facility_id — fix: keep one row per "
        "facility_id, or correct the repeated value"
    ]


COMPLIANCE_HEADROOM_FIX = "enter limit minus current_value, or correct limit or current_value"


def test_compliance_headroom_must_be_limit_minus_current() -> None:
    assert rendered(check(changed("Compliance_Monitor", 0, {"headroom": "0.15"}))) == [
        f"{FILE}:Compliance_Monitor!J2: headroom 0.15 is not limit 2.5 minus current_value 2.37"
        f" = 0.13 (to within 0.01) — fix: {COMPLIANCE_HEADROOM_FIX}"
    ]
    # Within 0.01 either way is accepted.
    assert rendered(check(changed("Compliance_Monitor", 0, {"headroom": "0.14"}))) == []
    assert rendered(check(changed("Compliance_Monitor", 0, {"headroom": "0.12"}))) == []


def test_currency_limits_need_the_mandate_currency_and_skip_headroom_arithmetic() -> None:
    row = {
        "limit": "20000000",
        "limit_unit": "USD",
        "current_value": "15000000",
        "headroom": "1",
        "status": "Pass",
    }
    assert rendered(check(changed("Compliance_Monitor", 0, row))) == []
    assert rendered(check(changed("Compliance_Monitor", 0, row | {"limit_unit": "EUR"}))) == [
        f"{FILE}:Compliance_Monitor!E2: limit_unit EUR is not the Mandate nav_currency USD"
        " — fix: enter % NAV, or the Mandate nav_currency code (e.g. USD) for an amount limit"
    ]


@pytest.mark.parametrize(
    "change, problem, fix",
    [
        (
            {"current_value": "2.6", "headroom": "-0.1", "status": "Watch"},
            "status 'Watch' but current_value 2.6 exceeds limit 2.5",
            "enter Breach, or correct the values: a current value above its limit is a breach",
        ),
        (
            {"status": "Breach"},
            "status 'Breach' but current_value 2.37 does not exceed limit 2.5",
            "enter Pass or Watch, or correct the values: only a current value above its limit "
            "is a breach",
        ),
        (
            {"current_value": "2.25", "headroom": "0.25", "status": "Watch"},
            "status 'Watch' but the headroom 0.25 is at least 10 % of limit 2.5",
            "enter Pass: Watch is for headroom under 10 % of the limit",
        ),
    ],
)
def test_compliance_status_must_follow_the_values(
    change: dict[str, Any], problem: str, fix: str
) -> None:
    assert rendered(check(changed("Compliance_Monitor", 0, change))) == [
        f"{FILE}:Compliance_Monitor!K2: {problem} — fix: {fix}"
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"current_value": "2.6", "headroom": "-0.1", "status": "Breach"},
        {"current_value": "2.5", "headroom": "0", "status": "Watch"},
        {"current_value": "2.26", "headroom": "0.24", "status": "Watch"},
        {"current_value": "2.37", "headroom": "0.13", "status": "Pass"},
    ],
)
def test_compliance_status_accepted_combinations(change: dict[str, Any]) -> None:
    assert rendered(check(changed("Compliance_Monitor", 0, change))) == []


def test_sector_headroom_and_status_rules() -> None:
    def sector(change: dict[str, Any]) -> list[str]:
        return [issue.render() for issue in check(changed("Sector_Exposure", 0, change)).issues]

    assert sector({"headroom_pct_nav": "2.9"}) == [
        f"{FILE}:Sector_Exposure!E2: headroom_pct_nav 2.9 is not limit_pct_nav 10.0 minus "
        "pct_nav 7.16 = 2.84 (to within 0.01) — fix: enter limit_pct_nav minus pct_nav, or "
        "correct the limit or the exposure"
    ]
    assert sector({"limit_pct_nav": None, "status": None}) == [
        f"{FILE}:Sector_Exposure!E2: headroom_pct_nav is given without limit_pct_nav — fix: "
        "enter limit_pct_nav, or leave headroom_pct_nav empty"
    ]
    assert sector({"limit_pct_nav": None, "headroom_pct_nav": None}) == [
        f"{FILE}:Sector_Exposure!F2: status is given without limit_pct_nav — fix: enter "
        "limit_pct_nav, or leave status empty"
    ]
    assert sector({"status": "Breach"}) == [
        f"{FILE}:Sector_Exposure!F2: status 'Breach' but pct_nav 7.16 does not exceed "
        "limit_pct_nav 10.0 — fix: enter Pass or Watch, or correct the values: only a current "
        "value above its limit is a breach"
    ]
    assert sector({"headroom_pct_nav": None, "status": None}) == []


def test_numbers_are_exact_decimals_never_floats() -> None:
    # In binary floating point 0.3 - 0.1 - 0.19 is not 0.01; as decimals the headroom 0.02
    # differs from 0.3 - 0.29 = 0.01 by exactly 0.01, inside the tolerance.
    change = {"limit": "0.3", "current_value": "0.29", "headroom": "0.02", "status": "Watch"}
    assert rendered(check(changed("Compliance_Monitor", 0, change))) == []
    change |= {"headroom": "0.0200000000000000000001"}
    assert [issue.cell for issue in check(changed("Compliance_Monitor", 0, change)).issues] == [
        "J2"
    ]


def test_a_number_longer_than_40_characters_is_refused() -> None:
    long = "1" + "0" * 40
    assert rendered(check(changed("Exposure_Summary", 1, {"value": long}))) == [
        f"{FILE}:Exposure_Summary!B3: value '{long}' is longer than 40 characters — fix: enter "
        "the number with at most 40 characters (Excel keeps 15 significant digits)"
    ]


def source(raw: bytes, name: str = FILE) -> Source:
    request = SourceRequest(source_id="portfolio", path=name, media_type=MEDIA_TYPE)
    return prepare_source(request, raw)


def test_portfolio_facts_returns_typed_decimal_rows_with_locators() -> None:
    facts = portfolio_facts(source(workbook(valid() | {"Holdings_Detail": [HOLDING]})))
    assert facts.mandate.fund_name == "Example Fund I (synthetic)"
    assert facts.mandate.strategy == "CLO"
    assert facts.mandate.nav == Decimal("1000")
    assert facts.mandate.nav_currency == "USD"
    assert facts.mandate.as_of == date(2026, 5, 29)
    assert [(item.section, item.field) for item in facts.mandate.fields][-1] == (
        "Key Parties",
        "trustee",
    )
    assert facts.mandate.locator("nav") == "sheet:Mandate!C4"
    nav = facts.exposures[0]
    assert (nav.metric, nav.value, nav.unit, nav.as_of) == (
        "nav",
        Decimal("1000.00"),
        "USD",
        date(2026, 5, 29),
    )
    assert nav.locator("value") == "sheet:Exposure_Summary!B2"
    assert [(item.rating_bucket, item.pct_nav, item.issuers) for item in facts.ratings] == [
        ("B", Decimal("60.5"), 8),
        ("BB", Decimal("39.5"), 4),
    ]
    software, insurance = facts.sectors
    assert (software.limit_pct_nav, software.headroom_pct_nav, software.status) == (
        Decimal("10.0"),
        Decimal("2.84"),
        "Pass",
    )
    assert (insurance.limit_pct_nav, insurance.headroom_pct_nav, insurance.status) == (
        None,
        None,
        None,
    )
    assert [item.rank for item in facts.top_holdings] == [1, 2]
    assert [item.pct_nav for item in facts.maturities] == [Decimal("40"), Decimal("60")]
    issuer, sector = facts.compliance
    assert (issuer.id, issuer.limit, issuer.current_value, issuer.headroom) == (
        "C-01",
        Decimal("2.5"),
        Decimal("2.37"),
        Decimal("0.13"),
    )
    assert (issuer.breach_type, issuer.scope, issuer.status, issuer.last_checked) == (
        "Hard",
        "issuer",
        "Watch",
        date(2026, 5, 29),
    )
    assert sector.locator("current_value") == "sheet:Compliance_Monitor!I3"
    assert facts.holdings is not None
    (holding,) = facts.holdings
    assert (holding.par, holding.market_value, holding.maturity) == (
        Decimal("15000000"),
        Decimal("14951250"),
        date(2030, 6, 30),
    )
    every = [
        value
        for row in (*facts.exposures, *facts.ratings, *facts.sectors, *facts.compliance)
        for value in row.model_dump().values()
    ]
    assert not any(isinstance(value, float) for value in every)


def test_portfolio_facts_without_the_optional_sheet_has_no_holdings() -> None:
    assert portfolio_facts(source(workbook(valid()))).holdings is None


def test_portfolio_facts_refuses_an_invalid_workbook_with_its_report() -> None:
    raw = workbook(changed("Compliance_Monitor", 0, {"headroom": "0.15"}))
    with pytest.raises(PortfolioRefused) as refused:
        portfolio_facts(source(raw))
    assert refused.value.report == validate_portfolio_bytes(FILE, raw)
    assert [issue.cell for issue in refused.value.report.issues] == ["J2"]


def test_validate_portfolio_reads_the_file(tmp_path: Path) -> None:
    path = tmp_path / FILE
    path.write_bytes(workbook(valid()))
    assert validate_portfolio(path) == validate_portfolio_bytes(FILE, path.read_bytes())
    missing = validate_portfolio(tmp_path / "absent.xlsx")
    assert rendered(missing) == [
        "absent.xlsx:Mandate!A1: cannot read the file: No such file or directory"
        " — fix: check the path and that the file is readable"
    ]


def test_fixes_are_unique_strings() -> None:
    assert len(set(FIXES)) == len(FIXES)
    assert TEMPLATE_PATH in " ".join(FIXES)
