"""The `rv_quotes` sheet: user-supplied relative-value market evidence (task RV-1).

The user supplies quotes as an XLSX workbook with a sheet `rv_quotes`; the file enters a pack as
an ordinary XLSX source (`preparation.SourceRequest`), the CP-0 reviewer classes its authority
and CP-3 quotes its cells by `sheet:rv_quotes!<cell>` locators. This module holds the template
contract as data (`COLUMNS`, the per-column fixes) and `validate_rv_quotes`, the self-check the
user runs before `prepare`. It changes no CP-3 rule and never sets an authority.

The validator reads the workbook through `preparation.prepare_source`, which calls
`preparation.xlsx_content`, so it sees exactly the stored lexemes `prepare` freezes: no
recalculation, hidden sheets, rows and columns read like any other (the pack marks them
hidden), merged ranges as metadata. Numbers are `Decimal`s parsed from the stored lexeme,
never floats.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, Self
from urllib.parse import quote, unquote

from pydantic import model_validator

from deploy_vii.contracts import Contract, Span
from deploy_vii.preparation import MAX_BYTES, SourceRequest, prepare_source

SHEET = "rv_quotes"
MEDIA_TYPE: Final[Literal["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]] = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
TEMPLATE = "docs/templates/rv-quotes.template.xlsx"
COLUMNS = (
    "provider",
    "as_of",
    "issuer",
    "facility_id",
    "instrument",
    "quote_kind",
    "price",
    "yield_pct",
    "spread_bps",
    "bid",
    "ask",
    "currency",
    "note",
)
LETTERS = tuple(chr(ord("A") + index) for index in range(len(COLUMNS)))
LEVELS = ("price", "yield_pct", "spread_bps", "bid", "ask")
QUOTE_KINDS = ("observed", "indicative_talk")
KEY = ("facility_id", "as_of", "provider", "quote_kind")
# Every column but the free-text note and the levels (at least one level is required).
REQUIRED = ("provider", "as_of", "issuer", "facility_id", "instrument", "quote_kind", "currency")
FIX: Mapping[str, str] = {
    "provider": "enter the dealer, broker or pricing service that supplied the quote",
    "as_of": (
        "enter the quote date as text YYYY-MM-DD (format the column as Text so Excel keeps it)"
    ),
    "issuer": "enter the issuer's name",
    "facility_id": "enter the facility's id using letters, digits, - and _ only, e.g. TLB-2030",
    "instrument": "describe the instrument, e.g. Term Loan B due 2030",
    "quote_kind": "enter observed or indicative_talk; leave out rows without a quote",
    "currency": "enter the three-letter upper-case ISO 4217 code, e.g. USD",
    "number": (
        "enter a plain number: digits, an optional sign and one decimal point "
        "(no %, units, spaces or thousands separators)"
    ),
    "levels": "enter at least one of price, yield_pct, spread_bps, bid or ask",
    "bid_ask": "check the quote: bid must not exceed ask",
    "issuer_provider": (
        "name the third party that supplied the quote, or leave the issuer's own levels "
        "out of this sheet"
    ),
    "duplicate": (
        "keep one row per facility_id, as_of, provider and quote_kind, or correct the "
        "repeated value"
    ),
    "formula": "replace the formula with its value (Paste Special, Values)",
    "header": (
        f"set row 1 to exactly: {', '.join(COLUMNS)} (A1 to {LETTERS[-1]}1, nothing after "
        f"{LETTERS[-1]}1)"
    ),
    "rows": "add one row per quote, starting in row 2",
    "empty": f"copy the header row from {TEMPLATE} and add one row per quote",
    "sheet": f"name the quote sheet {SHEET}, as in {TEMPLATE}",
    "workbook": "save the file as an Excel Workbook (.xlsx) and validate again",
    "read": "check the path and that the file is readable",
}
ADDRESS = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SERIAL = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
CURRENCY = re.compile(r"^[A-Z]{3}$")


class Issue(Contract):
    file: str
    sheet: str
    cell: str
    problem: str
    fix: str

    def render(self) -> str:
        """One line: a cell value's line breaks or other control characters are escaped."""
        line = f"{self.file}:{self.sheet}!{self.cell}: {self.problem} — fix: {self.fix}"
        return "".join(
            char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
            for char in line
        )


class ValidationReport(Contract):
    ok: bool
    rows: int
    issues: tuple[Issue, ...]

    @model_validator(mode="after")
    def agreement(self) -> Self:
        if self.ok != (not self.issues):
            raise ValueError("ok must be true exactly when there are no issues")
        return self

    def lines(self) -> tuple[str, ...]:
        summary = f"OK: {self.rows} rows" if self.ok else f"FAILED: {len(self.issues)} issues"
        return (*(issue.render() for issue in self.issues), summary)


def report(rows: int, issues: Sequence[Issue]) -> ValidationReport:
    return ValidationReport(ok=not issues, rows=rows, issues=tuple(issues))


def validate_rv_quotes(path: Path) -> ValidationReport:
    """Validate one user-supplied quote workbook; every finding is an `Issue` with a fix."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except OSError as error:
        reason = error.strerror or type(error).__name__
        problem = f"cannot read the file: {reason}"
        return report(
            0, (Issue(file=path.name, sheet=SHEET, cell="A1", problem=problem, fix=FIX["read"]),)
        )
    return validate_rv_bytes(path.name, raw)


def validate_rv_bytes(file: str, raw: bytes) -> ValidationReport:
    """`validate_rv_quotes` on bytes already read; `file` names the workbook in each issue."""

    def issue(cell: str, problem: str, fix: str) -> Issue:
        return Issue(file=file, sheet=SHEET, cell=cell, problem=problem, fix=fix)

    source = prepare_source(
        SourceRequest(source_id="rv-quotes", path=file, media_type=MEDIA_TYPE), raw
    )
    if not source.coverage:
        # `prepare_source` failed to extract: the same refusal `prepare` would freeze.
        problem = f"prepare cannot read this file as an OOXML workbook: {source.limitation}"
        return report(0, (issue("A1", problem, FIX["workbook"]),))
    sheets = [unquote(item.locator.removeprefix("sheet:")) for item in source.coverage]
    if SHEET not in sheets:
        found = ", ".join(sheets) or "none"
        return report(0, (issue("A1", f"no sheet named {SHEET} (found: {found})", FIX["sheet"]),))
    grid = cells(source.spans)
    if not any(span.text.strip() for span in grid.values()):
        return report(0, (issue("A1", f"sheet {SHEET} is empty", FIX["empty"]),))
    data = sorted({row for _, row in grid if row > 1 and nonblank(grid, row)})
    header = header_issue(grid)
    if header is not None:
        return report(len(data), (issue(*header, FIX["header"]),))
    if not data:
        return report(0, (issue("A2", "no quote rows below the header", FIX["rows"]),))
    issues: list[Issue] = []
    seen: dict[tuple[str, ...], int] = {}
    for row in data:
        findings, key = row_findings(grid, row)
        issues += [issue(*finding) for finding in findings]
        if key is not None and key in seen:
            problem = f"duplicates row {seen[key]} on facility_id, as_of, provider and quote_kind"
            issues.append(issue(f"A{row}:F{row}", problem, FIX["duplicate"]))
        elif key is not None:
            seen[key] = row
    return report(len(data), issues)


def cells(spans: Sequence[Span]) -> dict[tuple[int, int], Span]:
    """The `rv_quotes` cell spans by (column number, row number); merged-range metadata and
    comment parts are not cells."""
    prefix = "sheet:" + quote(SHEET, safe="") + "!"
    grid: dict[tuple[int, int], Span] = {}
    for span in spans:
        match = ADDRESS.match(span.locator.removeprefix(prefix))
        if span.locator.startswith(prefix) and match is not None:
            column = 0
            for char in match.group(1):
                column = column * 26 + ord(char) - ord("A") + 1
            grid[column, int(match.group(2))] = span
    return grid


def text(grid: Mapping[tuple[int, int], Span], column: int, row: int) -> str:
    span = grid.get((column, row))
    return "" if span is None else span.text.strip()


def nonblank(grid: Mapping[tuple[int, int], Span], row: int) -> bool:
    return any(text(grid, column, row) for column in range(1, len(COLUMNS) + 1))


def header_issue(grid: Mapping[tuple[int, int], Span]) -> tuple[str, str] | None:
    """The first header cell that is not the template's, as (cell, problem)."""
    for column, expected in enumerate(COLUMNS, 1):
        found = text(grid, column, 1)
        if found != expected:
            shown = f"'{found}'" if found else "empty"
            return f"{LETTERS[column - 1]}1", f"header is {shown}, expected '{expected}'"
    extra = sorted(column for column, row in grid if row == 1 and column > len(COLUMNS))
    for column in extra:
        found = text(grid, column, 1)
        if found:
            letters = cell_letters(column)
            return f"{letters}1", f"header is '{found}', expected nothing after {LETTERS[-1]}1"
    return None


def cell_letters(column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def row_findings(
    grid: Mapping[tuple[int, int], Span], row: int
) -> tuple[list[tuple[str, str, str]], tuple[str, ...] | None]:
    """One data row's findings as (cell, problem, fix), and its duplicate key when every key
    column holds a valid value."""
    values: dict[str, str] = {}
    findings: list[tuple[str, str, str]] = []
    flagged: set[str] = set()
    for column, name in enumerate(COLUMNS, 1):
        span = grid.get((column, row))
        values[name] = "" if span is None else span.text.strip()
        if span is not None and span.formula is not None:
            problem = (
                f"{name} holds a formula; prepare freezes stored values and never recalculates"
            )
            findings.append((f"{LETTERS[column - 1]}{row}", problem, FIX["formula"]))
            flagged.add(name)
    for name in COLUMNS:
        if name in flagged:
            continue
        found = column_problem(name, values)
        if found is not None:
            flagged.add(name)
            findings.append((f"{LETTERS[COLUMNS.index(name)]}{row}", *found))
    findings += level_findings(values, flagged, row)
    key = None if flagged & set(KEY) else tuple(values[name] for name in KEY)
    return findings, key


def column_problem(name: str, values: Mapping[str, str]) -> tuple[str, str] | None:
    """What is wrong with one cell of a row, as (problem, fix), judged on its stored lexeme
    alone (or, for `provider`, against the row's issuer)."""
    value = values[name]
    if name in REQUIRED and not value:
        return f"{name} is empty", FIX[name]
    if name == "provider" and folded(value) == folded(values["issuer"]):
        issuer = (
            f"provider '{value}' is the issuer; a quote the issuer supplies is not "
            "third-party evidence"
        )
        return issuer, FIX["issuer_provider"]
    problem: str | None = None
    if name == "as_of" and not iso_date(value):
        kind = "an Excel date serial, not" if SERIAL.match(value) else "not"
        problem = f"as_of '{value}' is {kind} an ISO date YYYY-MM-DD"
    elif name == "facility_id" and not IDENTIFIER.match(value):
        problem = f"facility_id '{value}' has characters other than letters, digits, - and _"
    elif name == "quote_kind" and value not in QUOTE_KINDS:
        problem = f"quote_kind '{value}' is not observed or indicative_talk"
    elif name == "currency" and not CURRENCY.match(value):
        problem = f"currency '{value}' is not a three-letter ISO 4217 code"
    elif name in LEVELS and value and not NUMBER.match(value):
        problem = f"{name} '{value}' is not a number"
    if problem is None:
        return None
    return problem, FIX["number"] if name in LEVELS else FIX[name]


def level_findings(
    values: Mapping[str, str], flagged: set[str], row: int
) -> list[tuple[str, str, str]]:
    """At least one level per row; bid not above ask. A flagged level counts as present (its
    own finding already names it)."""
    first, last = LETTERS[COLUMNS.index(LEVELS[0])], LETTERS[COLUMNS.index(LEVELS[-1])]
    if not any(values[name] or name in flagged for name in LEVELS):
        problem = "no price, yield_pct, spread_bps, bid or ask"
        return [(f"{first}{row}:{last}{row}", problem, FIX["levels"])]
    bid, ask = values["bid"], values["ask"]
    if bid and ask and not {"bid", "ask"} & flagged and Decimal(bid) > Decimal(ask):
        bid_cell, ask_cell = LETTERS[COLUMNS.index("bid")], LETTERS[COLUMNS.index("ask")]
        cell = f"{bid_cell}{row}:{ask_cell}{row}"
        return [(cell, f"bid {bid} exceeds ask {ask}", FIX["bid_ask"])]
    return []


def folded(value: str) -> str:
    return " ".join(value.casefold().split())


def iso_date(value: str) -> bool:
    if not ISO_DATE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True
