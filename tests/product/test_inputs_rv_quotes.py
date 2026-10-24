"""Task RV-1: the user-supplied relative-value quote sheet (`rv_quotes`) and its validator.

Workbooks here are written by openpyxl, an independent OOXML writer, so the validator is
exercised on bytes it did not produce. Every row is synthetic: a fictional issuer and
fictional providers, no market data.
"""

import sys
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from deploy_vii.inputs.rv_quotes import COLUMNS, Issue, ValidationReport, validate_rv_quotes

FILE = "quotes.xlsx"
HEADER_FIX = (
    "set row 1 to exactly: provider, as_of, issuer, facility_id, instrument, quote_kind, "
    "price, yield_pct, spread_bps, bid, ask, currency, note (A1 to M1, nothing after M1)"
)
VALID: dict[str, Any] = {
    "provider": "Synthetic Dealer A",
    "as_of": "2026-09-30",
    "issuer": "Example Holdings Ltd (synthetic)",
    "facility_id": "TLB-2030",
    "instrument": "Term Loan B due 2030",
    "quote_kind": "observed",
    "price": 98.75,
    "yield_pct": None,
    "spread_bps": None,
    "bid": None,
    "ask": None,
    "currency": "USD",
    "note": "synthetic example row",
}


def write(
    directory: Path,
    rows: list[dict[str, Any]],
    *,
    header: tuple[str, ...] = COLUMNS,
    sheet: str = "rv_quotes",
) -> Path:
    book = openpyxl.Workbook()
    worksheet = book.active
    assert worksheet is not None
    worksheet.title = sheet
    if header:
        worksheet.append(list(header))
    for row in rows:
        worksheet.append([row.get(column) for column in header or COLUMNS])
    path = directory / FILE
    book.save(path)
    return path


def rendered(report: ValidationReport) -> list[str]:
    return [issue.render() for issue in report.issues]


def test_issue_renders_file_sheet_cell_problem_and_fix() -> None:
    issue = Issue(file="f.xlsx", sheet="rv_quotes", cell="B2", problem="p", fix="x")
    assert issue.render() == "f.xlsx:rv_quotes!B2: p — fix: x"


def test_two_valid_rows_are_ok(tmp_path: Path) -> None:
    second = VALID | {"quote_kind": "indicative_talk", "price": None, "bid": 97, "ask": 98.5}
    report = validate_rv_quotes(write(tmp_path, [VALID, second]))
    assert rendered(report) == []
    assert report.ok
    assert report.rows == 2
    assert report.lines() == ("OK: 2 rows",)


AS_OF_FIX = "enter the quote date as text YYYY-MM-DD (format the column as Text so Excel keeps it)"
NUMBER_FIX = (
    "enter a plain number: digits, an optional sign and one decimal point "
    "(no %, units, spaces or thousands separators)"
)
QUOTE_KIND_FIX = "enter observed or indicative_talk; leave out rows without a quote"
CURRENCY_FIX = "enter the three-letter upper-case ISO 4217 code, e.g. USD"
FACILITY_FIX = "enter the facility's id using letters, digits, - and _ only, e.g. TLB-2030"
PROVIDER_FIX = "enter the dealer, broker or pricing service that supplied the quote"
LEVEL_FIX = "enter at least one of price, yield_pct, spread_bps, bid or ask"


@pytest.mark.parametrize(
    "change, cell, problem, fix",
    [
        ({"provider": None}, "A2", "provider is empty", PROVIDER_FIX),
        ({"provider": "  "}, "A2", "provider is empty", PROVIDER_FIX),
        (
            {"provider": " example holdings LTD  (synthetic) "},
            "A2",
            "provider 'example holdings LTD  (synthetic)' is the issuer; a quote the issuer "
            "supplies is not third-party evidence",
            "name the third party that supplied the quote, or leave the issuer's own levels "
            "out of this sheet",
        ),
        ({"as_of": None}, "B2", "as_of is empty", AS_OF_FIX),
        (
            {"as_of": "30/09/2026"},
            "B2",
            "as_of '30/09/2026' is not an ISO date YYYY-MM-DD",
            AS_OF_FIX,
        ),
        (
            {"as_of": "2026-02-30"},
            "B2",
            "as_of '2026-02-30' is not an ISO date YYYY-MM-DD",
            AS_OF_FIX,
        ),
        (
            {"as_of": 46295},
            "B2",
            "as_of '46295' is an Excel date serial, not an ISO date YYYY-MM-DD",
            AS_OF_FIX,
        ),
        ({"issuer": None}, "C2", "issuer is empty", "enter the issuer's name"),
        ({"facility_id": None}, "D2", "facility_id is empty", FACILITY_FIX),
        (
            {"facility_id": "TLB 2030"},
            "D2",
            "facility_id 'TLB 2030' has characters other than letters, digits, - and _",
            FACILITY_FIX,
        ),
        (
            {"instrument": None},
            "E2",
            "instrument is empty",
            "describe the instrument, e.g. Term Loan B due 2030",
        ),
        ({"quote_kind": None}, "F2", "quote_kind is empty", QUOTE_KIND_FIX),
        (
            {"quote_kind": "none"},
            "F2",
            "quote_kind 'none' is not observed or indicative_talk",
            QUOTE_KIND_FIX,
        ),
        (
            {"quote_kind": "Observed"},
            "F2",
            "quote_kind 'Observed' is not observed or indicative_talk",
            QUOTE_KIND_FIX,
        ),
        ({"price": "1,000.5"}, "G2", "price '1,000.5' is not a number", NUMBER_FIX),
        (
            {"price": None, "yield_pct": "7.5%"},
            "H2",
            "yield_pct '7.5%' is not a number",
            NUMBER_FIX,
        ),
        (
            {"price": None, "spread_bps": "NaN"},
            "I2",
            "spread_bps 'NaN' is not a number",
            NUMBER_FIX,
        ),
        ({"price": None, "bid": "1_000"}, "J2", "bid '1_000' is not a number", NUMBER_FIX),
        ({"price": None, "ask": "abc"}, "K2", "ask 'abc' is not a number", NUMBER_FIX),
        ({"price": None}, "G2:K2", "no price, yield_pct, spread_bps, bid or ask", LEVEL_FIX),
        (
            {"bid": "99.50", "ask": "99.25"},
            "J2:K2",
            "bid 99.50 exceeds ask 99.25",
            "check the quote: bid must not exceed ask",
        ),
        ({"currency": None}, "L2", "currency is empty", CURRENCY_FIX),
        (
            {"currency": "usd"},
            "L2",
            "currency 'usd' is not a three-letter ISO 4217 code",
            CURRENCY_FIX,
        ),
        (
            {"currency": "US$"},
            "L2",
            "currency 'US$' is not a three-letter ISO 4217 code",
            CURRENCY_FIX,
        ),
        (
            {"price": "=97+1"},
            "G2",
            "price holds a formula; prepare freezes stored values and never recalculates",
            "replace the formula with its value (Paste Special, Values)",
        ),
    ],
)
def test_each_column_rule_fails_with_its_exact_message(
    tmp_path: Path, change: dict[str, Any], cell: str, problem: str, fix: str
) -> None:
    report = validate_rv_quotes(write(tmp_path, [VALID | change]))
    assert rendered(report) == [f"{FILE}:rv_quotes!{cell}: {problem} — fix: {fix}"]
    assert not report.ok
    assert report.rows == 1
    assert report.lines()[-1] == "FAILED: 1 issues"


def test_note_and_bid_equal_ask_are_accepted(tmp_path: Path) -> None:
    row = VALID | {"note": None, "price": None, "bid": "99.25", "ask": "99.250"}
    assert rendered(validate_rv_quotes(write(tmp_path, [row]))) == []


def test_stored_lexemes_are_read_as_decimals_not_floats(tmp_path: Path) -> None:
    # 0.1 + 0.2 > 0.3 in binary floating point; as decimals bid 0.3 does not exceed ask 0.3.
    row = VALID | {"price": None, "bid": "0.30000000000000000001", "ask": "0.3000000000000000001"}
    assert rendered(validate_rv_quotes(write(tmp_path, [row]))) == []
    flipped = VALID | {
        "price": None,
        "bid": "0.3000000000000000001",
        "ask": "0.30000000000000000001",
    }
    assert rendered(validate_rv_quotes(write(tmp_path, [flipped]))) == [
        f"{FILE}:rv_quotes!J2:K2: bid 0.3000000000000000001 exceeds ask 0.30000000000000000001"
        " — fix: check the quote: bid must not exceed ask"
    ]


def test_duplicate_quote_key_is_one_issue_on_the_later_row(tmp_path: Path) -> None:
    other = VALID | {"facility_id": "SN-2032", "instrument": "Senior Notes due 2032"}
    report = validate_rv_quotes(write(tmp_path, [VALID, other, VALID | {"price": 99}]))
    assert rendered(report) == [
        f"{FILE}:rv_quotes!A4:F4: duplicates row 2 on facility_id, as_of, provider and quote_kind"
        " — fix: keep one row per facility_id, as_of, provider and quote_kind, or correct the"
        " repeated value"
    ]
    assert report.rows == 3


def test_blank_rows_between_quotes_are_skipped(tmp_path: Path) -> None:
    other = VALID | {"quote_kind": "indicative_talk"}
    empty = dict.fromkeys(COLUMNS)
    report = validate_rv_quotes(write(tmp_path, [VALID, empty, other]))
    assert rendered(report) == []
    assert report.rows == 2


def test_header_out_of_order_fails_on_the_header_not_on_rows(tmp_path: Path) -> None:
    swapped = ("as_of", "provider", *COLUMNS[2:])
    report = validate_rv_quotes(write(tmp_path, [VALID], header=swapped))
    assert rendered(report) == [
        f"{FILE}:rv_quotes!A1: header is 'as_of', expected 'provider' — fix: {HEADER_FIX}"
    ]


def test_missing_header_column_is_one_issue(tmp_path: Path) -> None:
    report = validate_rv_quotes(write(tmp_path, [], header=COLUMNS[:-1]))
    assert rendered(report) == [
        f"{FILE}:rv_quotes!M1: header is empty, expected 'note' — fix: {HEADER_FIX}"
    ]


def test_extra_header_column_is_one_issue(tmp_path: Path) -> None:
    report = validate_rv_quotes(write(tmp_path, [VALID], header=(*COLUMNS, "comment")))
    assert rendered(report) == [
        f"{FILE}:rv_quotes!N1: header is 'comment', expected nothing after M1 — fix: {HEADER_FIX}"
    ]


def test_header_only_sheet_has_no_quote_rows(tmp_path: Path) -> None:
    report = validate_rv_quotes(write(tmp_path, []))
    assert rendered(report) == [
        f"{FILE}:rv_quotes!A2: no quote rows below the header"
        " — fix: add one row per quote, starting in row 2"
    ]
    assert report.rows == 0


def test_empty_sheet_is_one_issue(tmp_path: Path) -> None:
    report = validate_rv_quotes(write(tmp_path, [], header=()))
    assert rendered(report) == [
        f"{FILE}:rv_quotes!A1: sheet rv_quotes is empty — fix: copy the header row from"
        " docs/templates/rv-quotes.template.xlsx and add one row per quote"
    ]


def test_missing_sheet_names_the_sheets_found(tmp_path: Path) -> None:
    report = validate_rv_quotes(write(tmp_path, [VALID], sheet="RV Quotes"))
    assert rendered(report) == [
        f"{FILE}:rv_quotes!A1: no sheet named rv_quotes (found: RV Quotes) — fix: name the"
        " quote sheet rv_quotes, as in docs/templates/rv-quotes.template.xlsx"
    ]
    assert report.rows == 0


def test_a_file_that_is_not_a_workbook_is_one_issue(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    path.write_text("provider,as_of\nSynthetic Dealer A,2026-09-30\n")
    report = validate_rv_quotes(path)
    assert rendered(report) == [
        "quotes.csv:rv_quotes!A1: prepare cannot read this file as an OOXML workbook:"
        " Preparation failed (BadZipFile): File is not a zip file"
        " — fix: save the file as an Excel Workbook (.xlsx) and validate again"
    ]
    assert report.lines() == (*rendered(report), "FAILED: 1 issues")


def test_an_unreadable_path_is_one_issue(tmp_path: Path) -> None:
    report = validate_rv_quotes(tmp_path / "absent.xlsx")
    assert rendered(report) == [
        "absent.xlsx:rv_quotes!A1: cannot read the file: No such file or directory"
        " — fix: check the path and that the file is readable"
    ]


def test_report_ok_must_agree_with_issues() -> None:
    issue = Issue(file="f", sheet="rv_quotes", cell="A1", problem="p", fix="x")
    with pytest.raises(ValueError, match="ok"):
        ValidationReport(ok=True, rows=0, issues=(issue,))
    with pytest.raises(ValueError, match="ok"):
        ValidationReport(ok=False, rows=0, issues=())


def run_cli(arguments: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    from deploy_vii.__main__ import main

    monkeypatch.setattr(sys, "argv", ["deploy-vii", "validate-input", *arguments])
    with pytest.raises(SystemExit) as exit_info:
        main()
    code = exit_info.value.code
    assert isinstance(code, int)
    return code


def test_cli_prints_ok_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, [VALID, VALID | {"quote_kind": "indicative_talk"}])
    assert run_cli(["rv", str(path)], monkeypatch) == 0
    assert capsys.readouterr().out == "OK: 2 rows\n"


def test_cli_prints_one_line_per_issue_and_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, [VALID | {"currency": "usd", "as_of": None}])
    assert run_cli(["rv", str(path)], monkeypatch) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"{FILE}:rv_quotes!B2: as_of is empty — fix: {AS_OF_FIX}",
        f"{FILE}:rv_quotes!L2: currency 'usd' is not a three-letter ISO 4217 code"
        f" — fix: {CURRENCY_FIX}",
        "FAILED: 2 issues",
    ]


def test_cli_json_prints_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, [VALID | {"currency": "usd"}])
    assert run_cli(["rv", str(path), "--json"], monkeypatch) == 1
    printed = ValidationReport.model_validate_json(capsys.readouterr().out)
    assert printed == validate_rv_quotes(path)
    assert not printed.ok


def test_cli_kind_comes_from_the_input_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.inputs import KINDS

    assert tuple(KINDS) == ("rv",)
    assert KINDS["rv"] is validate_rv_quotes
    assert run_cli(["portfolio", str(tmp_path / "x.xlsx")], monkeypatch) == 2
    assert "invalid choice: 'portfolio'" in capsys.readouterr().err
