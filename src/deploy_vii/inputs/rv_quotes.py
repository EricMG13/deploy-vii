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
import zlib
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
from pathlib import Path
from typing import Final, Literal, Self, cast
from urllib.parse import quote, unquote

from pydantic import ValidationError, model_validator

from deploy_vii.contracts import Citation, Contract, Hash, Identifier, Source, Span
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
    "percent": "enter the level as a plain number in General format, not a percentage format",
    "error_cell": "replace the Excel error with a supported value",
    "boolean_cell": "replace TRUE/FALSE with a supported value",
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
    "damaged": (
        "save the file again as an Excel Workbook (.xlsx) and validate again; prepare would "
        "also refuse this file"
    ),
    "read": "check the path and that the file is readable",
}
ECHO = 80  # characters of a cell value a message quotes
# What `zipfile` raises for damaged members beyond `prepare_source`'s own refusals.
DAMAGED = (zlib.error, EOFError, RuntimeError)
# Native XLSX coordinates: bound the lexeme before integer/column arithmetic.
ADDRESS = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})")
NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
PERCENT_FORMATS = frozenset({"builtin:9", "builtin:10"})  # 0% and 0.00%
LITERAL = re.compile(r'"[^"]*"|\\.')  # quoted text or an escaped character in a format code
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


class RVQuotesRefused(ValueError):
    """The frozen quote source failed the same checks as the public validator."""

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(f"RV quotes workbook refused: {len(report.issues)} issues")
        self.report = report


class RVQuote(Contract):
    """One eligible row, with exact frozen citations for its nonempty cells."""

    row: int
    provider: str
    as_of: date
    issuer: str
    facility_id: str
    instrument: str
    quote_kind: Literal["observed", "indicative_talk"]
    price: Decimal | None
    yield_pct: Decimal | None
    spread_bps: Decimal | None
    bid: Decimal | None
    ask: Decimal | None
    currency: str
    note: str | None
    refs: tuple[Citation, ...]

    def locator(self, column: str) -> str:
        return f"sheet:{SHEET}!{LETTERS[COLUMNS.index(column)]}{self.row}"

    def ref(self, column: str) -> Citation | None:
        """Missing/empty cells have no citation; their typed level remains None."""
        locator = self.locator(column)
        return next((ref for ref in self.refs if ref.locator == locator), None)


class RVQuotesFacts(Contract):
    source_id: Identifier
    source_sha256: Hash
    limitation: str | None
    extraction_status: Literal["complete", "degraded", "blocked"]
    quotes: tuple[RVQuote, ...]


def percent_formatted(span: Span) -> bool:
    """A numeric cell scaled by 100 for display; quoted/escaped percent signs are literal."""
    code = span.number_format
    if span.data_type != "n" or code is None:
        return False
    if code.startswith("builtin:"):
        return code in PERCENT_FORMATS
    return "%" in LITERAL.sub("", code)


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

    request = SourceRequest(source_id="rv-quotes", path=file, media_type=MEDIA_TYPE)
    try:
        source = prepare_source(request, raw)
    except DAMAGED as error:
        # CPython's zipfile raises these for a corrupt deflate stream, a truncated member and a
        # ZipCrypto-encrypted member; `prepare_source` does not catch them (follow-up), so
        # `prepare` would stop on the same file. Reported, never swallowed.
        kind = type(error).__name__
        kind = kind if type(error).__module__ == "builtins" else f"{type(error).__module__}.{kind}"
        problem = (
            "prepare cannot read this file as an OOXML workbook: damaged ZIP member "
            f"({kind}: {error})"
        )
        return report(0, (issue("A1", problem, FIX["damaged"]),))
    return read(file, source)[0]


def rv_quotes_facts(source: Source) -> RVQuotesFacts:
    """Read only frozen spans/coverage. Refuse the whole source on any finding.

    The hash is the trusted frozen Source's raw-workbook identity, not a hash of these spans;
    verifying it against original bytes remains the pack loader/consumer's responsibility.
    No quote selection, price convention, authority or financial calculation is supplied.
    """
    name = getattr(source, "name", None)
    file = name if isinstance(name, str) and name else "<invalid frozen source>"
    result, facts = read(file, source)
    if facts is None:
        raise RVQuotesRefused(result)
    return facts


def read(file: str, source: Source) -> tuple[ValidationReport, RVQuotesFacts | None]:
    """One validation/parse path for public bytes and frozen typed facts."""

    def issue(cell: str, problem: str, fix: str) -> Issue:
        return Issue(file=file, sheet=SHEET, cell=cell, problem=problem, fix=fix)

    def refused(rows: int, issues: Sequence[Issue]) -> tuple[ValidationReport, None]:
        return report(rows, issues), None

    if not source.coverage:
        problem = f"prepare cannot read this file as an OOXML workbook: {source.limitation}"
        return refused(0, (issue("A1", problem, FIX["workbook"]),))
    try:
        # Revalidate even model_copy/model_construct objects at this production input boundary.
        source = Source.model_validate(source.model_dump())
    except ValidationError:
        return refused(
            0, (issue("A1", "invalid frozen source identity or metadata", FIX["workbook"]),)
        )
    sheets = []
    for item in source.coverage:
        name = unquote(item.locator.removeprefix("sheet:"))
        if item.locator != "sheet:" + quote(name, safe="") or not name:
            return refused(
                0, (issue("A1", "coverage locator is not a canonical sheet URI", FIX["workbook"]),)
            )
        if name == SHEET and item.status == "empty":
            return refused(0, (issue("A1", f"sheet {SHEET} is empty", FIX["empty"]),))
        if name == SHEET and item.status == "unreadable":
            return refused(
                0,
                (
                    issue(
                        "A1",
                        f"sheet {SHEET} coverage is {item.status}: {item.limitation}",
                        FIX["workbook"],
                    ),
                ),
            )
        sheets.append(name)
    if SHEET not in sheets:
        found = ", ".join(sheets) or "none"
        return refused(0, (issue("A1", f"no sheet named {SHEET} (found: {found})", FIX["sheet"]),))
    if source.status != "ready" or source.extraction_status == "blocked":
        problem = f"prepare cannot read this file as an OOXML workbook: {source.limitation}"
        return refused(0, (issue("A1", problem, FIX["workbook"]),))
    grids, locator_issues = sheet_cells(source.spans, file)
    if locator_issues:
        return refused(0, locator_issues)
    grid = grids.get(SHEET, {})
    if not any(span.text.strip() for span in grid.values()):
        return refused(0, (issue("A1", f"sheet {SHEET} is empty", FIX["empty"]),))
    data = sorted({row for _, row in grid if row > 1 and nonblank(grid, row)})
    header = header_issue(grid)
    if header is not None:
        return refused(len(data), (issue(*header, FIX["header"]),))
    if not data:
        return refused(0, (issue("A2", "no quote rows below the header", FIX["rows"]),))
    issues: list[Issue] = []
    seen: dict[tuple[str, ...], int] = {}
    quotes: list[RVQuote] = []
    for row in data:
        findings, key, levels = row_findings(grid, row)
        issues += [issue(*finding) for finding in findings]
        if key is not None and key in seen:
            problem = f"duplicates row {seen[key]} on facility_id, as_of, provider and quote_kind"
            issues.append(issue(f"A{row}:F{row}", problem, FIX["duplicate"]))
        elif key is not None:
            seen[key] = row
        if not findings:
            values = {name: text(grid, index, row) for index, name in enumerate(COLUMNS, 1)}
            refs = tuple(
                Citation(
                    source_id=source.source_id,
                    source_sha256=cast(Hash, source.sha256),
                    locator=span.locator,
                    quote=span.text,
                )
                for index in range(1, len(COLUMNS) + 1)
                if (span := grid.get((index, row))) is not None and span.text.strip()
            )
            quotes.append(
                RVQuote(
                    row=row,
                    provider=values["provider"],
                    as_of=date.fromisoformat(values["as_of"]),
                    issuer=values["issuer"],
                    facility_id=values["facility_id"],
                    instrument=values["instrument"],
                    quote_kind=cast(Literal["observed", "indicative_talk"], values["quote_kind"]),
                    currency=values["currency"],
                    note=values["note"] or None,
                    refs=refs,
                    **levels,
                )
            )
    result = report(len(data), issues)
    facts = (
        RVQuotesFacts(
            source_id=source.source_id,
            source_sha256=cast(Hash, source.sha256),
            limitation=source.limitation,
            extraction_status=source.extraction_status,
            quotes=tuple(quotes),
        )
        if result.ok
        else None
    )
    return result, facts


def sheet_cells(
    spans: Sequence[Span], file: str
) -> tuple[dict[str, dict[tuple[int, int], Span]], list[Issue]]:
    """Project only canonical frozen cell locators; keep comments and merged metadata separate."""
    grids: dict[str, dict[tuple[int, int], Span]] = {}
    issues: list[Issue] = []
    for span in spans:
        if not span.locator.startswith("sheet:"):
            continue
        encoded, separator, address = span.locator.removeprefix("sheet:").partition("!")
        name = unquote(encoded)
        problem = None
        if not name or encoded != quote(name, safe=""):
            problem = "sheet locator is not a canonical sheet URI"
        elif separator and address.startswith("merged:") and span.data_type == "metadata":
            continue
        else:
            match = ADDRESS.fullmatch(address)
            column = 0
            if match is not None:
                for char in match.group(1):
                    column = column * 26 + ord(char) - ord("A") + 1
            if match is None or column > 16384 or int(match.group(2)) > 1048576:
                problem = f"cell address '{echo(address)}' is not canonical A1 within A1:XFD1048576"
            else:
                grid = grids.setdefault(name, {})
                coordinate = column, int(match.group(2))
                if coordinate in grid:
                    problem = "cell address repeats a frozen coordinate"
                else:
                    grid[coordinate] = span
        if problem is not None:
            issues.append(
                Issue(
                    file=file,
                    sheet=name or SHEET,
                    cell=echo(address) or "A1",
                    problem=problem,
                    fix=FIX["workbook"],
                )
            )
    return grids, issues


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
            shown = f"'{echo(found)}'" if found else "empty"
            return f"{LETTERS[column - 1]}1", f"header is {shown}, expected '{expected}'"
    extra = sorted(column for column, row in grid if row == 1 and column > len(COLUMNS))
    for column in extra:
        found = text(grid, column, 1)
        if found:
            letters = cell_letters(column)
            return (
                f"{letters}1",
                f"header is '{echo(found)}', expected nothing after {LETTERS[-1]}1",
            )
    return None


def cell_letters(column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def row_findings(
    grid: Mapping[tuple[int, int], Span], row: int
) -> tuple[list[tuple[str, str, str]], tuple[str, ...] | None, dict[str, Decimal | None]]:
    """Cell findings, valid duplicate key and levels parsed exactly once."""
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
        elif span is not None and span.data_type in ("e", "b"):
            problem = (
                f"{name} holds the Excel error '{echo(values[name])}'"
                if span.data_type == "e"
                else f"{name} holds a TRUE/FALSE cell"
            )
            fix = FIX["error_cell" if span.data_type == "e" else "boolean_cell"]
            findings.append((f"{LETTERS[column - 1]}{row}", problem, fix))
            flagged.add(name)
        elif span is not None and name in LEVELS and values[name] and percent_formatted(span):
            problem = f"{name} '{echo(values[name])}' is formatted as a percentage"
            findings.append((f"{LETTERS[column - 1]}{row}", problem, FIX["percent"]))
            flagged.add(name)
    levels: dict[str, Decimal | None] = dict.fromkeys(LEVELS)
    for name in COLUMNS:
        if name in flagged:
            continue
        found = column_problem(name, values)
        if found is not None:
            flagged.add(name)
            findings.append((f"{LETTERS[COLUMNS.index(name)]}{row}", *found))
        elif name in LEVELS and values[name]:
            try:
                # Parse exactly without inheriting disabled traps or changing caller flags.
                with localcontext() as context:
                    context.traps[InvalidOperation] = True
                    levels[name] = Decimal(values[name])
            except DecimalException:
                flagged.add(name)
                problem = f"{name} '{echo(values[name])}' is not a supported Decimal representation"
                findings.append((f"{LETTERS[COLUMNS.index(name)]}{row}", problem, FIX["number"]))
    findings += level_findings(values, levels, flagged, row)
    key = None if flagged & set(KEY) else tuple(values[name] for name in KEY)
    return findings, key, levels


def column_problem(name: str, values: Mapping[str, str]) -> tuple[str, str] | None:
    """What is wrong with one cell of a row, as (problem, fix), judged on its stored lexeme
    alone (or, for `provider`, against the row's issuer)."""
    value = values[name]
    if name in REQUIRED and not value:
        return f"{name} is empty", FIX[name]
    if name == "provider" and folded(value) == folded(values["issuer"]):
        issuer = (
            f"provider '{echo(value)}' is the issuer; a quote the issuer supplies is not "
            "third-party evidence"
        )
        return issuer, FIX["issuer_provider"]
    problem: str | None = None
    if name == "as_of" and not iso_date(value):
        kind = "an Excel date serial, not" if SERIAL.match(value) else "not"
        problem = f"as_of '{echo(value)}' is {kind} an ISO date YYYY-MM-DD"
    elif name == "facility_id" and not IDENTIFIER.match(value):
        problem = f"facility_id '{echo(value)}' has characters other than letters, digits, - and _"
    elif name == "quote_kind" and value not in QUOTE_KINDS:
        problem = f"quote_kind '{echo(value)}' is not observed or indicative_talk"
    elif name == "currency" and not CURRENCY.match(value):
        problem = f"currency '{echo(value)}' is not a three-letter ISO 4217 code"
    elif name in LEVELS and value and not NUMBER.match(value):
        problem = f"{name} '{echo(value)}' is not a number"
    if problem is None:
        return None
    return problem, FIX["number"] if name in LEVELS else FIX[name]


def level_findings(
    values: Mapping[str, str], levels: Mapping[str, Decimal | None], flagged: set[str], row: int
) -> list[tuple[str, str, str]]:
    """At least one level per row; bid not above ask. A flagged level counts as present (its
    own finding already names it)."""
    first, last = LETTERS[COLUMNS.index(LEVELS[0])], LETTERS[COLUMNS.index(LEVELS[-1])]
    if not any(values[name] or name in flagged for name in LEVELS):
        problem = "no price, yield_pct, spread_bps, bid or ask"
        return [(f"{first}{row}:{last}{row}", problem, FIX["levels"])]
    bid, ask = values["bid"], values["ask"]
    bid_number, ask_number = levels["bid"], levels["ask"]
    if bid_number is not None and ask_number is not None:
        try:
            exceeds = bid_number > ask_number
        except DecimalException:
            return [
                (f"J{row}:K{row}", "bid/ask cannot be compared as exact Decimals", FIX["number"])
            ]
        if not exceeds:
            return []
        bid_cell, ask_cell = LETTERS[COLUMNS.index("bid")], LETTERS[COLUMNS.index("ask")]
        cell = f"{bid_cell}{row}:{ask_cell}{row}"
        return [(cell, f"bid {echo(bid)} exceeds ask {echo(ask)}", FIX["bid_ask"])]
    return []


def echo(value: str) -> str:
    """A cell value as a message quotes it: at most `ECHO` characters, then an ellipsis."""
    return value if len(value) <= ECHO else value[:ECHO] + "…"


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
