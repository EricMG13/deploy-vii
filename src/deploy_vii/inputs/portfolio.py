"""The `portfolio` workbook: the fund's mandate, exposures and compliance limits (task PF-1).

The user supplies one XLSX workbook in their environment; it enters a pack as an ordinary XLSX
source (`preparation.SourceRequest`), CP-0 classes its authority, and the Portfolio Fit and
Portfolio Debate owners quote its cells by `sheet:<name>!<cell>` locators. This module holds
the template contract as data (`SHEETS`, every column's fix), `validate_portfolio`, the
self-check the user runs before `prepare`, and `portfolio_facts`, the typed reader the
Portfolio Fit module consumes. It never sets an authority and computes nothing a module owns
(`one_pct_nav` is the Portfolio Fit module's arithmetic, not an input).

Like `rv_quotes`, the validator reads the workbook through `preparation.prepare_source`, so it
sees exactly the stored lexemes `prepare` freezes. Numbers are `Decimal`s parsed from the stored
lexeme and compared exactly (`EXACT`), never floats.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Context, Decimal
from itertools import pairwise
from pathlib import Path
from typing import ClassVar, Literal, cast
from urllib.parse import quote, unquote

from deploy_vii.contracts import Contract, Source, Span
from deploy_vii.inputs.rv_quotes import (
    CURRENCY,
    DAMAGED,
    FIX,
    IDENTIFIER,
    MEDIA_TYPE,
    SERIAL,
    Issue,
    ValidationReport,
    cell_letters,
    echo,
    iso_date,
    percent_formatted,
    sheet_cells,
)
from deploy_vii.preparation import MAX_BYTES, SourceRequest, prepare_source

__all__ = ["MEDIA_TYPE", "Issue"]

TEMPLATE = "docs/templates/portfolio.template.xlsx"
README_SHEET = "README"
WORKBOOK_SHEET = "Mandate"  # the sheet a workbook-level issue names
PCT_NAV = "% NAV"
SECTOR_ID = "SECTOR"
STRATEGIES = ("CLO", "Indexed Loans", "Indexed HY", "Other")
SECTIONS = (
    "Strategy",
    "Key Parties",
    "Capital Structure",
    "Mandate Constraints",
    "Liquidity Terms",
    "Fees",
    "Reporting",
)
STATUSES = ("Pass", "Watch", "Breach")
BREACH_TYPES = ("Hard", "Soft")
SCOPES = (
    "issuer",
    "rating_bucket",
    "sector",
    "seniority",
    "instrument",
    "duration",
    "diversification",
    "yield",
    "pricing",
    "covenant",
    "esg",
    "other",
)
TOLERANCE = Decimal("0.01")  # stated headroom against limit minus current value
WATCH_SHARE = Decimal("0.1")  # Watch is allowed while headroom is under 10 % of the limit
RATING_SUM = (Decimal("99.0"), Decimal("101.0"))
MAX_NUMBER = 40  # characters of a number lexeme
# A plain decimal with at most a two-digit exponent: with `MAX_NUMBER` characters every value
# lies within 1e-140..1e140, so `EXACT` adds, subtracts and takes a tenth without rounding.
NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,2})?$")
EXACT = Context(prec=2000, Emax=9999, Emin=-9999)
CONTROL_ID = re.compile(r"^[A-Z]+-[0-9]{2}$")
TOTAL = re.compile(r"\b(?:sub)?total\b")
# Columns whose numbers are percent of NAV, always or on a `% NAV` Compliance_Monitor row. A
# numeric cell Excel shows as a percentage stores the fraction (2.5 % is stored 0.025).
PCT_COLUMNS = frozenset({"pct_nav", "limit_pct_nav", "headroom_pct_nav"})
PCT_NAV_ROW_COLUMNS = frozenset({"limit", "current_value", "headroom"})

DATE_FIX = "enter the date as text YYYY-MM-DD (format the column as Text so Excel keeps it)"
PCT_FIX = "enter the share of NAV in percent as a plain number (2.5 means 2.5 % NAV)"
COUNT_FIX = "enter the number of issuers as a whole number of at least 0, e.g. 12"
RANK_FIX = "number the holdings 1, 2, 3 and so on, with no gaps or repeats"
STATUS_FIX = "enter Pass, Watch or Breach"
ISSUER_FIX = "enter the issuer's name"
INSTRUMENT_FIX = "describe the instrument, e.g. Term Loan B due 2030"
RATING_FIX = "enter the rating as reported, e.g. B2 / B"
SECTOR_FIX = "enter the sector's name"
UNIT_FIX = "enter % NAV, or the Mandate nav_currency code (e.g. USD) for an amount limit"
SHEET_LIST = (
    "Mandate, Exposure_Summary, Rating_Distribution, Sector_Exposure, Top_Holdings, "
    "Maturity_Profile, Compliance_Monitor, Holdings_Detail (optional) and README (optional)"
)
RULE_FIX: Mapping[str, str] = {
    "number": FIX["number"],
    "long": "enter the number with at most 40 characters (Excel keeps 15 significant digits)",
    "formula": FIX["formula"],
    "read": FIX["read"],
    "workbook": FIX["workbook"],
    "damaged": FIX["damaged"],
    "unknown_sheet": f"delete the sheet or move it to another workbook; keep only {SHEET_LIST}",
    "order": f"order the sheets as in {TEMPLATE}: {SHEET_LIST}",
    "duplicate": "keep one row per {key}, or correct the repeated value",
    "total": "leave out total and subtotal rows; Python adds the rows up",
    "nav_value": "enter the fund's NAV, a number above 0",
    "nav_currency": FIX["currency"],
    "strategy": "enter one of CLO, Indexed Loans, Indexed HY or Other",
    "exposure_nav": "enter the same NAV on Exposure_Summary and Mandate",
    "exposure_unit": "enter the nav row's unit as the Mandate nav_currency, e.g. USD",
    "exposure_missing": (
        "add a row: metric nav, value the fund's NAV (the Mandate nav), unit the "
        "nav_currency, as_of the NAV date"
    ),
    "one_pct_nav": "delete the one_pct_nav row; Python computes 1 % of NAV from nav",
    "rating_sum": "correct the percentages, or add a row Unallocated with the remainder of NAV",
    "ranks": RANK_FIX,
    "headroom": "enter limit minus current_value, or correct limit or current_value",
    "sector_headroom": "enter limit_pct_nav minus pct_nav, or correct the limit or the exposure",
    "sector_headroom_alone": "enter limit_pct_nav, or leave headroom_pct_nav empty",
    "sector_status_alone": "enter limit_pct_nav, or leave status empty",
    "breach": "enter Breach, or correct the values: a current value above its limit is a breach",
    "not_breach": (
        "enter Pass or Watch, or correct the values: only a current value above its limit is "
        "a breach"
    ),
    "watch": "enter Pass: Watch is for headroom under 10 % of the limit",
    "percent": "format the cell as General and enter 2.5 for 2.5 % NAV",
    "error_cell": "enter the real value in place of the error, or leave an optional cell empty",
    "boolean_cell": "enter text or a plain number, not TRUE or FALSE",
}
REQUIRED_FIELDS: Mapping[tuple[str, str], str] = {
    ("Strategy", "fund_name"): (
        "add a row: section Strategy, field fund_name, value the fund's name"
    ),
    ("Strategy", "strategy"): (
        "add a row: section Strategy, field strategy, value CLO, Indexed Loans, Indexed HY or Other"
    ),
    ("Capital Structure", "nav"): (
        "add a row: section Capital Structure, field nav, value the fund's NAV as a plain number"
    ),
    ("Capital Structure", "nav_currency"): (
        "add a row: section Capital Structure, field nav_currency, value the NAV's three-letter "
        "currency code, e.g. USD"
    ),
    ("Reporting", "as_of"): (
        "add a row: section Reporting, field as_of, value the NAV and compliance date as text "
        "YYYY-MM-DD"
    ),
}

Kind = Literal["text", "number", "count", "rank", "date", "choice", "identifier", "id", "unit"]


@dataclass(frozen=True)
class Column:
    name: str
    kind: Kind
    fix: str
    required: bool = True
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Sheet:
    name: str
    columns: tuple[Column, ...]
    noun: str
    key: tuple[str, ...]
    label: str | None = None  # the column whose total rows are refused
    optional: bool = False

    def letter(self, column: str) -> str:
        return cell_letters(self.names.index(column) + 1)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def header_fix(self) -> str:
        last = self.letter(self.names[-1])
        return (
            f"set row 1 to exactly: {', '.join(self.names)} (A1 to {last}1, nothing after {last}1)"
        )

    def fixes(self) -> tuple[str, ...]:
        return (
            self.header_fix(),
            f"copy the header row of {self.name} from {TEMPLATE} and add one row per {self.noun}",
            f"add one row per {self.noun}, starting in row 2",
            f"add the sheet {self.name} with its header row, as in {TEMPLATE}",
        )


def text(name: str, fix: str, *, required: bool = True) -> Column:
    return Column(name, "text", fix, required)


def choice(name: str, choices: tuple[str, ...], *, required: bool = True) -> Column:
    return Column(name, "choice", f"enter {alternatives(choices)}", required, choices)


def alternatives(choices: Sequence[str]) -> str:
    listed = ", ".join(choices[:-1]) + " or " + choices[-1]
    return listed if len(choices) <= 3 else "one of " + listed


def pct(name: str = "pct_nav") -> Column:
    return Column(name, "number", PCT_FIX)


MANDATE = Sheet(
    "Mandate",
    (
        choice("section", SECTIONS),
        text("field", "enter the field's name, e.g. fund_name"),
        text("value", "enter the field's value, or delete the row"),
        text("notes", "", required=False),
    ),
    "mandate field",
    ("section", "field"),
)
EXPOSURE = Sheet(
    "Exposure_Summary",
    (
        text("metric", "enter the metric's name, e.g. nav"),
        Column("value", "number", "enter the metric's value as a plain number"),
        text("unit", "enter the unit, e.g. USD, % NAV, years or count"),
        Column("as_of", "date", DATE_FIX),
    ),
    "metric",
    ("metric",),
)
RATINGS = Sheet(
    "Rating_Distribution",
    (
        text("rating_bucket", "enter the rating bucket, e.g. B or Unrated"),
        pct(),
        Column("issuers", "count", COUNT_FIX),
    ),
    "rating bucket",
    ("rating_bucket",),
    label="rating_bucket",
)
SECTORS = Sheet(
    "Sector_Exposure",
    (
        text("sector", SECTOR_FIX),
        pct(),
        Column("issuers", "count", COUNT_FIX),
        Column("limit_pct_nav", "number", PCT_FIX, required=False),
        Column("headroom_pct_nav", "number", PCT_FIX, required=False),
        choice("status", STATUSES, required=False),
    ),
    "sector",
    ("sector",),
    label="sector",
)
TOP_HOLDINGS = Sheet(
    "Top_Holdings",
    (
        Column("rank", "rank", RANK_FIX),
        text("issuer", ISSUER_FIX),
        text("instrument", INSTRUMENT_FIX),
        pct(),
        text("rating", RATING_FIX),
    ),
    "holding",
    ("rank",),
)
MATURITIES = Sheet(
    "Maturity_Profile",
    (text("bucket", "enter the maturity bucket, e.g. 3-5 Years"), pct()),
    "maturity bucket",
    ("bucket",),
    label="bucket",
)
COMPLIANCE = Sheet(
    "Compliance_Monitor",
    (
        Column(
            "id",
            "id",
            "enter an id such as C-01 (capital letters, a hyphen, two digits), or SECTOR for "
            "the sector-limit row",
        ),
        text("constraint_category", "enter the constraint category, e.g. Single Name"),
        text("parameter", "describe the constraint, e.g. Max single issuer exposure"),
        Column(
            "limit",
            "number",
            "enter the limit as a plain number in limit_unit (2.5 means 2.5 % NAV)",
        ),
        Column("limit_unit", "unit", UNIT_FIX),
        choice("breach_type", BREACH_TYPES),
        choice("scope", SCOPES),
        text("source_document", "enter the document that sets the limit, e.g. Indenture s7.11"),
        Column(
            "current_value", "number", "enter the current exposure as a plain number in limit_unit"
        ),
        Column("headroom", "number", "enter limit minus current_value as a plain number"),
        choice("status", STATUSES),
        Column("last_checked", "date", DATE_FIX),
        text("checked_by", "enter who checked the row, e.g. analyst"),
    ),
    "constraint",
    ("id",),
)
HOLDINGS = Sheet(
    "Holdings_Detail",
    (
        text("issuer", ISSUER_FIX),
        text("instrument", INSTRUMENT_FIX),
        Column("facility_id", "identifier", FIX["facility_id"]),
        Column("par", "number", "enter the par amount as a plain number"),
        Column("market_value", "number", "enter the market value as a plain number"),
        pct(),
        text("rating", RATING_FIX),
        text("sector", SECTOR_FIX),
        text("seniority", "enter the seniority, e.g. 1st Lien"),
        Column("maturity", "date", DATE_FIX),
    ),
    "position",
    ("facility_id",),
    optional=True,
)
SHEETS = (MANDATE, EXPOSURE, RATINGS, SECTORS, TOP_HOLDINGS, MATURITIES, COMPLIANCE, HOLDINGS)
BY_NAME = {sheet.name: sheet for sheet in SHEETS}
# Every fixed-text fix the validator can print (the README documents each verbatim). The
# per-sheet structure fixes (`Sheet.fixes`) and the repeated-key fix are patterns over a sheet's
# header, noun or key; the README documents those patterns.
FIXES = tuple(
    dict.fromkeys(
        fix
        for fix in (
            *RULE_FIX.values(),
            *REQUIRED_FIELDS.values(),
            *(column.fix for sheet in SHEETS for column in sheet.columns),
        )
        if fix and "{" not in fix
    )
)


class PortfolioReport(ValidationReport):
    """`rows` counts data rows on every contract sheet; `sheets` the contract sheets present
    (README excluded); `compliance_rows` the Compliance_Monitor data rows."""

    sheets: int
    compliance_rows: int

    def lines(self) -> tuple[str, ...]:
        summary = (
            f"OK: {self.sheets} sheets, {self.compliance_rows} compliance rows"
            if self.ok
            else f"FAILED: {len(self.issues)} issues"
        )
        return (*(issue.render() for issue in self.issues), summary)


class PortfolioRefused(ValueError):
    """`portfolio_facts` on a workbook the validator does not pass; `report` says why."""

    def __init__(self, report: PortfolioReport) -> None:
        super().__init__(f"portfolio workbook refused: {len(report.issues)} issues")
        self.report = report


def cell_locator(sheet: str, column: str, row: int) -> str:
    return f"sheet:{quote(sheet, safe='')}!{BY_NAME[sheet].letter(column)}{row}"


class SheetRow(Contract):
    """One data row; `row` is its worksheet row number, so `locator` names the frozen span."""

    SHEET: ClassVar[str]
    row: int

    def locator(self, column: str) -> str:
        return cell_locator(self.SHEET, column, self.row)


class MandateField(SheetRow):
    SHEET: ClassVar[str] = MANDATE.name
    section: str
    field: str
    value: str
    notes: str | None


class Mandate(Contract):
    fund_name: str
    strategy: Literal["CLO", "Indexed Loans", "Indexed HY", "Other"]
    nav: Decimal
    nav_currency: str
    as_of: date
    fields: tuple[MandateField, ...]

    def locator(self, name: str) -> str:
        """The value cell of a required field (`fund_name`, `strategy`, `nav`, `nav_currency`,
        `as_of`)."""
        (section,) = (section for section, field in REQUIRED_FIELDS if field == name)
        (item,) = (item for item in self.fields if (item.section, item.field) == (section, name))
        return item.locator("value")


class Exposure(SheetRow):
    SHEET: ClassVar[str] = EXPOSURE.name
    metric: str
    value: Decimal
    unit: str
    as_of: date


class RatingBucket(SheetRow):
    SHEET: ClassVar[str] = RATINGS.name
    rating_bucket: str
    pct_nav: Decimal
    issuers: int


Status = Literal["Pass", "Watch", "Breach"]


class SectorExposure(SheetRow):
    SHEET: ClassVar[str] = SECTORS.name
    sector: str
    pct_nav: Decimal
    issuers: int
    limit_pct_nav: Decimal | None
    headroom_pct_nav: Decimal | None
    status: Status | None


class TopHolding(SheetRow):
    SHEET: ClassVar[str] = TOP_HOLDINGS.name
    rank: int
    issuer: str
    instrument: str
    pct_nav: Decimal
    rating: str


class MaturityBucket(SheetRow):
    SHEET: ClassVar[str] = MATURITIES.name
    bucket: str
    pct_nav: Decimal


Scope = Literal[
    "issuer",
    "rating_bucket",
    "sector",
    "seniority",
    "instrument",
    "duration",
    "diversification",
    "yield",
    "pricing",
    "covenant",
    "esg",
    "other",
]


class ComplianceRow(SheetRow):
    """One Compliance_Monitor row. Every limit is a maximum (there is no direction field).
    Consumers compute room as `limit - current_value` and never read `headroom` for it."""

    SHEET: ClassVar[str] = COMPLIANCE.name
    id: str
    constraint_category: str
    parameter: str
    limit: Decimal
    limit_unit: str
    breach_type: Literal["Hard", "Soft"]
    scope: Scope
    source_document: str
    current_value: Decimal
    headroom: Decimal
    """The sheet's stated headroom, never used for room: checked to within 0.01 of
    `limit - current_value` on `% NAV` rows and unchecked on currency rows."""
    status: Status
    last_checked: date
    checked_by: str


class Holding(SheetRow):
    SHEET: ClassVar[str] = HOLDINGS.name
    issuer: str
    instrument: str
    facility_id: str
    par: Decimal
    market_value: Decimal
    pct_nav: Decimal
    rating: str
    sector: str
    seniority: str
    maturity: date


class PortfolioFacts(Contract):
    """The validated workbook as typed rows, in sheet row order; `holdings` is None when the
    optional Holdings_Detail sheet is absent."""

    mandate: Mandate
    exposures: tuple[Exposure, ...]
    ratings: tuple[RatingBucket, ...]
    sectors: tuple[SectorExposure, ...]
    top_holdings: tuple[TopHolding, ...]
    maturities: tuple[MaturityBucket, ...]
    compliance: tuple[ComplianceRow, ...]
    holdings: tuple[Holding, ...] | None


Value = str | Decimal | int | date


@dataclass
class Row:
    """One data row: `raw` holds every column's stripped lexeme, `values` the typed value of
    each non-empty cell without a finding, `flagged` the columns with a finding."""

    number: int
    raw: dict[str, str]
    values: dict[str, Value] = field(default_factory=dict)
    flagged: set[str] = field(default_factory=set)

    def ok(self, *names: str) -> bool:
        return all(name in self.values for name in names)

    def number_of(self, name: str) -> Decimal:
        return cast(Decimal, self.values[name])


@dataclass
class Table:
    sheet: Sheet
    rows: list[Row]


@dataclass
class Findings:
    file: str
    issues: list[Issue] = field(default_factory=list)

    def add(self, sheet: str, cell: str, problem: str, fix: str) -> None:
        self.issues.append(Issue(file=self.file, sheet=sheet, cell=cell, problem=problem, fix=fix))


@dataclass(frozen=True)
class NavBasis:
    """The Mandate's NAV and currency when valid, for the cross-sheet rules."""

    nav: Decimal | None = None
    nav_cell: str = ""
    currency: str | None = None


def report(
    rows: int, issues: Sequence[Issue], sheets: int = 0, compliance_rows: int = 0
) -> PortfolioReport:
    return PortfolioReport(
        ok=not issues,
        rows=rows,
        issues=tuple(issues),
        sheets=sheets,
        compliance_rows=compliance_rows,
    )


def validate_portfolio(path: Path) -> PortfolioReport:
    """Validate one user-supplied portfolio workbook; every finding is an `Issue` with a fix."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except OSError as error:
        reason = error.strerror or type(error).__name__
        issue = Issue(
            file=path.name,
            sheet=WORKBOOK_SHEET,
            cell="A1",
            problem=f"cannot read the file: {reason}",
            fix=RULE_FIX["read"],
        )
        return report(0, (issue,))
    return validate_portfolio_bytes(path.name, raw)


def validate_portfolio_bytes(file: str, raw: bytes) -> PortfolioReport:
    """`validate_portfolio` on bytes already read; `file` names the workbook in each issue."""
    request = SourceRequest(source_id="portfolio", path=file, media_type=MEDIA_TYPE)
    try:
        source = prepare_source(request, raw)
    except DAMAGED as error:
        # As in `rv_quotes`: CPython's zipfile raises these for a corrupt deflate stream, a
        # truncated member and a ZipCrypto-encrypted member, and `prepare_source` does not
        # catch them, so `prepare` would stop on the same file. Reported, never swallowed.
        kind = type(error).__name__
        kind = kind if type(error).__module__ == "builtins" else f"{type(error).__module__}.{kind}"
        problem = (
            "prepare cannot read this file as an OOXML workbook: damaged ZIP member "
            f"({kind}: {error})"
        )
        findings = Findings(file)
        findings.add(WORKBOOK_SHEET, "A1", problem, RULE_FIX["damaged"])
        return report(0, findings.issues)
    return read(file, source)[0]


def portfolio_facts(source: Source) -> PortfolioFacts:
    """The typed rows of a prepared portfolio source (a pack `Source` or `prepare_source`'s
    result). Pure: reads only the source's spans and coverage. Raises `PortfolioRefused`, with
    the validator's report, unless the workbook passes.

    `ComplianceRow.headroom` and `SectorExposure.headroom_pct_nav` are the stated figures:
    checked to within 0.01 on `% NAV` rows and unchecked on currency rows. A consumer computes
    room as `limit - current_value` (or `limit_pct_nav - pct_nav`) and never reads headroom."""
    result, typed_facts = read(source.name, source)
    if typed_facts is None:
        raise PortfolioRefused(result)
    return typed_facts


def read(file: str, source: Source) -> tuple[PortfolioReport, PortfolioFacts | None]:
    findings = Findings(file)
    if source.status != "ready" or source.extraction_status == "blocked" or not source.coverage:
        # `prepare_source` failed to extract: the same refusal `prepare` would freeze.
        problem = f"prepare cannot read this file as an OOXML workbook: {source.limitation}"
        findings.add(WORKBOOK_SHEET, "A1", problem, RULE_FIX["workbook"])
        return report(0, findings.issues), None
    names = []
    for item in source.coverage:
        name = unquote(item.locator.removeprefix("sheet:"))
        if not name or item.locator != "sheet:" + quote(name, safe=""):
            findings.add(
                WORKBOOK_SHEET,
                "A1",
                "coverage locator is not a canonical sheet URI",
                RULE_FIX["workbook"],
            )
        elif name in BY_NAME and item.status == "unreadable":
            findings.add(
                name,
                "A1",
                f"sheet {name} coverage is unreadable: {item.limitation}",
                RULE_FIX["workbook"],
            )
        elif name in BY_NAME and item.status == "empty":
            findings.add(name, "A1", f"sheet {name} is empty", BY_NAME[name].fixes()[1])
        names.append(name)
    grids, locator_issues = sheet_cells(source.spans, file)
    findings.issues.extend(locator_issues)
    if findings.issues:
        return report(0, findings.issues), None
    sheet_list_findings(names, findings)
    tables: dict[str, Table] = {}
    for sheet in SHEETS:
        if sheet.name in names:
            table = load_table(sheet, grids.get(sheet.name, {}), findings)
            if table is not None:
                tables[sheet.name] = table
                SHEET_RULES[sheet.name](table, tables, findings)
    present = sum(1 for sheet in SHEETS if sheet.name in names)
    compliance = len(tables[COMPLIANCE.name].rows) if COMPLIANCE.name in tables else 0
    rows = sum(len(table.rows) for table in tables.values())
    result = report(rows, findings.issues, present, compliance)
    return result, (build_facts(tables) if result.ok else None)


def sheet_list_findings(names: Sequence[str], findings: Findings) -> None:
    """Unknown, missing and out-of-order sheets."""
    known = {*BY_NAME, README_SHEET}
    for name in names:
        if name not in known:
            findings.add(name, "A1", f"unknown sheet '{echo(name)}'", RULE_FIX["unknown_sheet"])
    found = ", ".join(echo(name) for name in names) or "none"
    for sheet in SHEETS:
        if not sheet.optional and sheet.name not in names:
            problem = f"no sheet named {sheet.name} (found: {found})"
            findings.add(sheet.name, "A1", problem, sheet.fixes()[3])
    order = [name for name in names if name in BY_NAME]
    for before, after in pairwise(order):
        if SHEETS.index(BY_NAME[after]) < SHEETS.index(BY_NAME[before]):
            problem = f"sheet {after} comes after {before}"
            findings.add(after, "A1", problem, RULE_FIX["order"])
            break


def stored(grid: Mapping[tuple[int, int], Span], column: int, row: int) -> str:
    span = grid.get((column, row))
    return "" if span is None else span.text.strip()


def load_table(
    sheet: Sheet, grid: Mapping[tuple[int, int], Span], findings: Findings
) -> Table | None:
    """The sheet's parsed rows, or None (with one issue) when it is empty, its header is not
    the template's or it has no data rows."""
    width = len(sheet.columns)
    if not any(span.text.strip() for span in grid.values()):
        findings.add(sheet.name, "A1", f"sheet {sheet.name} is empty", sheet.fixes()[1])
        return None
    header = header_problem(sheet, grid)
    if header is not None:
        findings.add(sheet.name, *header, sheet.header_fix())
        return None
    numbers = sorted(
        {
            row
            for _, row in grid
            if row > 1 and any(stored(grid, column, row) for column in range(1, width + 1))
        }
    )
    if not numbers:
        findings.add(sheet.name, "A2", "no rows below the header", sheet.fixes()[2])
        return None
    rows = [parse_row(sheet, grid, number, findings) for number in numbers]
    key_findings(sheet, rows, findings)
    return Table(sheet, rows)


def header_problem(sheet: Sheet, grid: Mapping[tuple[int, int], Span]) -> tuple[str, str] | None:
    """The first header cell that is not the template's, as (cell, problem)."""
    for column, expected in enumerate(sheet.names, 1):
        found = stored(grid, column, 1)
        if found != expected:
            shown = f"'{echo(found)}'" if found else "empty"
            return f"{cell_letters(column)}1", f"header is {shown}, expected '{expected}'"
    last = cell_letters(len(sheet.columns))
    for column in sorted(column for column, row in grid if row == 1 and column > len(sheet.names)):
        found = stored(grid, column, 1)
        if found:
            return (
                f"{cell_letters(column)}1",
                f"header is '{echo(found)}', expected nothing after {last}1",
            )
    return None


def parse_row(
    sheet: Sheet, grid: Mapping[tuple[int, int], Span], number: int, findings: Findings
) -> Row:
    row = Row(number, {})
    for index, column in enumerate(sheet.columns, 1):
        span = grid.get((index, number))
        value = "" if span is None else span.text.strip()
        row.raw[column.name] = value
        cell = f"{cell_letters(index)}{number}"
        if span is not None and span.formula is not None:
            message = (
                f"{column.name} holds a formula; prepare freezes stored values and never "
                "recalculates"
            )
            findings.add(sheet.name, cell, message, RULE_FIX["formula"])
            row.flagged.add(column.name)
            continue
        if span is not None and span.data_type in ("e", "b"):
            # An Excel error (`t="e"`, e.g. #N/A) or a TRUE/FALSE cell (`t="b"`, stored 1 or
            # 0) is not a value in any column.
            if span.data_type == "e":
                message = f"{column.name} holds the Excel error '{echo(value)}'"
                findings.add(sheet.name, cell, message, RULE_FIX["error_cell"])
            else:
                message = f"{column.name} holds a TRUE/FALSE cell"
                findings.add(sheet.name, cell, message, RULE_FIX["boolean_cell"])
            row.flagged.add(column.name)
            continue
        if not value:
            if column.required:
                findings.add(sheet.name, cell, f"{column.name} is empty", column.fix)
                row.flagged.add(column.name)
            continue
        parsed, problem = parse_value(column, value)
        if problem is None:
            row.values[column.name] = parsed
        else:
            findings.add(sheet.name, cell, *problem)
            row.flagged.add(column.name)
    if sheet.label is not None and sheet.label in row.values:
        label = row.raw[sheet.label]
        if TOTAL.search(label.casefold()):
            message = f"{sheet.label} '{echo(label)}' is a total row"
            findings.add(
                sheet.name, f"{sheet.letter(sheet.label)}{number}", message, RULE_FIX["total"]
            )
            del row.values[sheet.label]
            row.flagged.add(sheet.label)
    percent_findings(sheet, grid, row, findings)
    return row


def percent_findings(
    sheet: Sheet, grid: Mapping[tuple[int, int], Span], row: Row, findings: Findings
) -> None:
    """Refuse percent-formatted numbers in percent columns: one issue per cell, and the value
    is dropped so no rule computes with a fraction."""
    pct_nav_row = row.raw.get("limit_unit") == PCT_NAV
    for index, column in enumerate(sheet.columns, 1):
        name = column.name
        span = grid.get((index, row.number))
        scaled = name in PCT_COLUMNS or (pct_nav_row and name in PCT_NAV_ROW_COLUMNS)
        if span is not None and scaled and name in row.values and percent_formatted(span):
            message = f"{name} '{echo(row.raw[name])}' is formatted as a percentage"
            findings.add(
                sheet.name, f"{cell_letters(index)}{row.number}", message, RULE_FIX["percent"]
            )
            del row.values[name]
            row.flagged.add(name)


def parse_number(name: str, value: str) -> tuple[Decimal, tuple[str, str] | None]:
    if not NUMBER.match(value):
        return Decimal(0), (f"{name} '{echo(value)}' is not a number", RULE_FIX["number"])
    if len(value) > MAX_NUMBER:
        problem = f"{name} '{echo(value)}' is longer than {MAX_NUMBER} characters"
        return Decimal(0), (problem, RULE_FIX["long"])
    return Decimal(value), None


def parse_date(name: str, value: str) -> tuple[date, tuple[str, str] | None]:
    if iso_date(value):
        return date.fromisoformat(value), None
    kind = "an Excel date serial, not" if SERIAL.match(value) else "not"
    return date.min, (f"{name} '{echo(value)}' is {kind} an ISO date YYYY-MM-DD", DATE_FIX)


def parse_value(column: Column, value: str) -> tuple[Value, tuple[str, str] | None]:
    """A non-empty stored lexeme as its typed value, or the (problem, fix) it fails with."""
    name, shown = column.name, echo(value)
    if column.kind == "number":
        return parse_number(name, value)
    if column.kind in ("count", "rank"):
        least = 0 if column.kind == "count" else 1
        number, problem = parse_number(name, value)
        if (
            problem is None
            and number == number.to_integral_value(context=EXACT)
            and number >= least
        ):
            return int(number), None
        return 0, (f"{name} '{shown}' is not a whole number of at least {least}", column.fix)
    if column.kind == "date":
        return parse_date(name, value)
    if column.kind == "choice" and value not in column.choices:
        return value, (f"{name} '{shown}' is not {alternatives(column.choices)}", column.fix)
    if column.kind == "identifier" and not IDENTIFIER.match(value):
        message = f"{name} '{shown}' has characters other than letters, digits, - and _"
        return value, (message, column.fix)
    if column.kind == "id" and not (CONTROL_ID.match(value) or value == SECTOR_ID):
        return value, (f"{name} '{shown}' is not of the form C-01 or SECTOR", column.fix)
    if column.kind == "unit" and not (value == PCT_NAV or CURRENCY.match(value)):
        message = f"{name} '{shown}' is not % NAV or a three-letter currency code"
        return value, (message, column.fix)
    return value, None


def key_findings(sheet: Sheet, rows: Sequence[Row], findings: Findings) -> None:
    """A repeated key is one issue on the later row; rows with an invalid key cell are not also
    duplicates."""
    seen: dict[tuple[Value, ...], int] = {}
    key = " and ".join(sheet.key)
    first, last = sheet.letter(sheet.key[0]), sheet.letter(sheet.key[-1])
    for row in rows:
        if not row.ok(*sheet.key):
            continue
        values = tuple(row.values[name] for name in sheet.key)
        if values in seen:
            cell = f"{first}{row.number}" + ("" if first == last else f":{last}{row.number}")
            problem = f"duplicates row {seen[values]} on {key}"
            findings.add(sheet.name, cell, problem, RULE_FIX["duplicate"].format(key=key))
        else:
            seen[values] = row.number


def nav_basis(tables: Mapping[str, Table]) -> NavBasis:
    table = tables.get(MANDATE.name)
    if table is None:
        return NavBasis()
    values = mandate_values(table)
    nav, currency = values.get("nav"), values.get("nav_currency")
    return NavBasis(
        nav=nav[0] if nav is not None and isinstance(nav[0], Decimal) else None,
        nav_cell=f"Mandate!C{nav[1]}" if nav is not None else "",
        currency=currency[0] if currency is not None and isinstance(currency[0], str) else None,
    )


def mandate_values(table: Table) -> dict[str, tuple[Value, int]]:
    """Each valid required field's typed value and row number (the first row when repeated)."""
    values: dict[str, tuple[Value, int]] = {}
    for row in table.rows:
        pair = (row.raw["section"], row.raw["field"])
        if (
            pair in REQUIRED_FIELDS
            and row.ok("section", "field", "value")
            and pair[1] not in values
        ):
            parsed, problem = mandate_value(pair[1], row.raw["value"])
            if problem is None:
                values[pair[1]] = (parsed, row.number)
    return values


def mandate_value(name: str, value: str) -> tuple[Value, tuple[str, str] | None]:
    if name == "strategy" and value not in STRATEGIES:
        return value, (
            f"strategy '{echo(value)}' is not {alternatives(STRATEGIES)}",
            RULE_FIX["strategy"],
        )
    if name == "nav":
        nav, problem = parse_number(name, value)
        if problem is None and nav <= 0:
            problem = f"nav {echo(value)} is not above 0", RULE_FIX["nav_value"]
        return nav, problem
    if name == "nav_currency" and not CURRENCY.match(value):
        message = f"nav_currency '{echo(value)}' is not a three-letter ISO 4217 code"
        return value, (message, RULE_FIX["nav_currency"])
    if name == "as_of":
        return parse_date(name, value)
    return value, None


def mandate_rules(table: Table, tables: Mapping[str, Table], findings: Findings) -> None:
    present: set[tuple[str, str]] = set()
    for row in table.rows:
        pair = (row.raw["section"], row.raw["field"])
        if row.ok("section", "field"):
            present.add(pair)
        if pair in REQUIRED_FIELDS and row.ok("section", "field", "value"):
            _, problem = mandate_value(pair[1], row.raw["value"])
            if problem is not None:
                findings.add(MANDATE.name, f"C{row.number}", *problem)
    last = table.rows[-1].number
    for (section, name), fix in REQUIRED_FIELDS.items():
        if (section, name) not in present:
            findings.add(MANDATE.name, f"A{last + 1}", f"no {section} row with field {name}", fix)


def exposure_rules(table: Table, tables: Mapping[str, Table], findings: Findings) -> None:
    basis = nav_basis(tables)
    sheet = EXPOSURE.name
    navs = [row for row in table.rows if row.raw["metric"] == "nav"]
    for row in table.rows:
        if row.raw["metric"] == "one_pct_nav":
            problem = "one_pct_nav is computed from nav and is not supplied"
            findings.add(sheet, f"A{row.number}", problem, RULE_FIX["one_pct_nav"])
    if not navs:
        last = table.rows[-1].number
        findings.add(sheet, f"A{last + 1}", "no metric nav", RULE_FIX["exposure_missing"])
        return
    nav = navs[0]
    if basis.nav is not None and nav.ok("value") and nav.number_of("value") != basis.nav:
        problem = (
            f"nav {echo(nav.raw['value'])} is not the Mandate nav {basis.nav} ({basis.nav_cell})"
        )
        findings.add(sheet, f"B{nav.number}", problem, RULE_FIX["exposure_nav"])
    if basis.currency is not None and nav.ok("unit") and nav.raw["unit"] != basis.currency:
        problem = (
            f"unit '{echo(nav.raw['unit'])}' of nav is not the Mandate nav_currency "
            f"{basis.currency}"
        )
        findings.add(sheet, f"C{nav.number}", problem, RULE_FIX["exposure_unit"])


def rating_rules(table: Table, tables: Mapping[str, Table], findings: Findings) -> None:
    if not all(row.ok("pct_nav") for row in table.rows):
        return
    total = Decimal(0)
    for row in table.rows:
        total = EXACT.add(total, row.number_of("pct_nav"))
    low, high = RATING_SUM
    if not low <= total <= high:
        cells = f"B{table.rows[0].number}:B{table.rows[-1].number}"
        problem = f"pct_nav sums to {total}, outside {low} to {high}"
        findings.add(RATINGS.name, cells, problem, RULE_FIX["rating_sum"])


def status_problem(row: Row, status: str, limit: str, current: str) -> tuple[str, str] | None:
    """Breach exactly when the current value exceeds the limit; Watch only while the headroom
    (limit minus current value, computed) is under 10 % of the limit."""
    value, ceiling = row.number_of(current), row.number_of(limit)
    state = row.raw[status]
    shown = f"{current} {echo(row.raw[current])}"
    bound = f"{limit} {echo(row.raw[limit])}"
    if value > ceiling and state != "Breach":
        return f"status '{state}' but {shown} exceeds {bound}", RULE_FIX["breach"]
    if value <= ceiling and state == "Breach":
        return f"status 'Breach' but {shown} does not exceed {bound}", RULE_FIX["not_breach"]
    room = EXACT.subtract(ceiling, value)
    if state == "Watch" and room >= EXACT.multiply(ceiling, WATCH_SHARE):
        return f"status 'Watch' but the headroom {room} is at least 10 % of {bound}", RULE_FIX[
            "watch"
        ]
    return None


def headroom_problem(
    row: Row, headroom: str, limit: str, current: str, fix: str
) -> tuple[str, str] | None:
    room = EXACT.subtract(row.number_of(limit), row.number_of(current))
    if EXACT.abs(EXACT.subtract(row.number_of(headroom), room)) <= TOLERANCE:
        return None
    problem = (
        f"{headroom} {echo(row.raw[headroom])} is not {limit} {echo(row.raw[limit])} minus "
        f"{current} {echo(row.raw[current])} = {room} (to within {TOLERANCE})"
    )
    return problem, fix


def sector_rules(table: Table, tables: Mapping[str, Table], findings: Findings) -> None:
    sheet = SECTORS.name
    for row in table.rows:
        limited = bool(row.raw["limit_pct_nav"])
        if row.raw["headroom_pct_nav"] and not limited:
            problem = "headroom_pct_nav is given without limit_pct_nav"
            findings.add(sheet, f"E{row.number}", problem, RULE_FIX["sector_headroom_alone"])
        elif row.ok("headroom_pct_nav", "limit_pct_nav", "pct_nav"):
            found = headroom_problem(
                row, "headroom_pct_nav", "limit_pct_nav", "pct_nav", RULE_FIX["sector_headroom"]
            )
            if found is not None:
                findings.add(sheet, f"E{row.number}", *found)
        if row.raw["status"] and not limited:
            problem = "status is given without limit_pct_nav"
            findings.add(sheet, f"F{row.number}", problem, RULE_FIX["sector_status_alone"])
        elif row.ok("status", "limit_pct_nav", "pct_nav"):
            found = status_problem(row, "status", "limit_pct_nav", "pct_nav")
            if found is not None:
                findings.add(sheet, f"F{row.number}", *found)


def top_holding_rules(table: Table, tables: Mapping[str, Table], findings: Findings) -> None:
    if not all(row.ok("rank") for row in table.rows):
        return
    ranks = {cast(int, row.values["rank"]) for row in table.rows}
    count = len(table.rows)
    if len(ranks) == count and ranks != set(range(1, count + 1)):
        missing = ", ".join(str(rank) for rank in range(1, count + 1) if rank not in ranks)
        cells = f"A{table.rows[0].number}:A{table.rows[-1].number}"
        problem = f"ranks are not 1 to {count}: {missing} missing"
        findings.add(TOP_HOLDINGS.name, cells, problem, RULE_FIX["ranks"])


def compliance_rules(table: Table, tables: Mapping[str, Table], findings: Findings) -> None:
    sheet = COMPLIANCE.name
    currency = nav_basis(tables).currency
    for row in table.rows:
        unit = row.raw["limit_unit"]
        if row.ok("limit_unit") and unit != PCT_NAV and currency is not None and unit != currency:
            problem = f"limit_unit {unit} is not the Mandate nav_currency {currency}"
            findings.add(sheet, f"E{row.number}", problem, UNIT_FIX)
        if row.ok("headroom", "limit", "current_value") and unit == PCT_NAV:
            found = headroom_problem(
                row, "headroom", "limit", "current_value", RULE_FIX["headroom"]
            )
            if found is not None:
                findings.add(sheet, f"J{row.number}", *found)
        if row.ok("status", "limit", "current_value"):
            found = status_problem(row, "status", "limit", "current_value")
            if found is not None:
                findings.add(sheet, f"K{row.number}", *found)


def no_rules(table: Table, tables: Mapping[str, Table], findings: Findings) -> None:
    """Holdings_Detail has only its column and key rules."""


SHEET_RULES = {
    MANDATE.name: mandate_rules,
    EXPOSURE.name: exposure_rules,
    RATINGS.name: rating_rules,
    SECTORS.name: sector_rules,
    TOP_HOLDINGS.name: top_holding_rules,
    MATURITIES.name: no_rules,
    COMPLIANCE.name: compliance_rules,
    HOLDINGS.name: no_rules,
}


def typed(row: Row, sheet: Sheet) -> dict[str, Value | None]:
    """A passing row's columns as model fields: optional empty cells are None."""
    fields: dict[str, Value | None] = {"row": row.number}
    fields.update((name, row.values.get(name)) for name in sheet.names)
    return fields


def build_facts(tables: Mapping[str, Table]) -> PortfolioFacts:
    """The typed rows of a workbook with no issues (every required cell holds a valid value)."""
    mandate_table = tables[MANDATE.name]
    required = {name: value for name, (value, _) in mandate_values(mandate_table).items()}
    holdings = tables.get(HOLDINGS.name)
    return PortfolioFacts(
        mandate=Mandate(
            fund_name=cast(str, required["fund_name"]),
            strategy=cast(
                Literal["CLO", "Indexed Loans", "Indexed HY", "Other"], required["strategy"]
            ),
            nav=cast(Decimal, required["nav"]),
            nav_currency=cast(str, required["nav_currency"]),
            as_of=cast(date, required["as_of"]),
            fields=tuple(
                MandateField.model_validate(typed(row, MANDATE)) for row in mandate_table.rows
            ),
        ),
        exposures=rows_of(tables, EXPOSURE, Exposure),
        ratings=rows_of(tables, RATINGS, RatingBucket),
        sectors=rows_of(tables, SECTORS, SectorExposure),
        top_holdings=rows_of(tables, TOP_HOLDINGS, TopHolding),
        maturities=rows_of(tables, MATURITIES, MaturityBucket),
        compliance=rows_of(tables, COMPLIANCE, ComplianceRow),
        holdings=None if holdings is None else rows_of(tables, HOLDINGS, Holding),
    )


def rows_of[RowModel: SheetRow](
    tables: Mapping[str, Table], sheet: Sheet, model: type[RowModel]
) -> tuple[RowModel, ...]:
    return tuple(model.model_validate(typed(row, sheet)) for row in tables[sheet.name].rows)
