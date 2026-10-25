"""Write the input templates in docs/templates/, byte for byte the same on every run.

Run from the repository root: `uv run python scripts/build_templates.py`.

Each workbook is plain OOXML written with the standard library: inline strings, stored (not
deflated) ZIP members in a fixed order with a fixed 1980-01-01 timestamp, so the bytes depend
only on the rows below and not on the clock, the platform or the zlib build. Headers come from
the input modules' contracts (`rv_quotes.COLUMNS`, task RV-1; `portfolio.SHEETS`, task PF-1).
Every row is synthetic: a fictional fund, fictional issuers and fictional providers, no market
or fund data.
"""

import io
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from deploy_vii.inputs import portfolio
from deploy_vii.inputs.rv_quotes import COLUMNS, LEVELS, NUMBER, SHEET, TEMPLATE, cell_letters

ROOT = Path(__file__).resolve().parents[1]
README_SHEET = "README"
README_LINES = (
    "synthetic example — replace every row",
    "Every row on rv_quotes is invented for a fictional issuer; none of it is market data.",
    "Keep row 1 (A1 to M1) exactly as it is and enter one quote per row from row 2.",
    "Check the file before prepare: deploy-vii validate-input rv <file>",
    "Column guide and messages: docs/templates/README.md",
)
NOTE = "synthetic example — replace every row"
ISSUER = "Example Holdings Ltd (synthetic)"
LOAN = {"facility_id": "TLB-2030", "instrument": "Term Loan B due 2030 (synthetic)"}
NOTES = {"facility_id": "SN-2032", "instrument": "Senior Secured Notes due 2032 (synthetic)"}
DEALER = {"provider": "Synthetic Dealer A", "issuer": ISSUER, "currency": "USD", "note": NOTE}
SERVICE = DEALER | {"provider": "Synthetic Pricing Service B"}
SYNTHETIC_ROWS: tuple[Mapping[str, str], ...] = (
    DEALER
    | LOAN
    | {
        "as_of": "2026-09-30",
        "quote_kind": "observed",
        "price": "98.75",
        "yield_pct": "8.40",
        "spread_bps": "375",
        "bid": "98.50",
        "ask": "99.00",
    },
    DEALER
    | NOTES
    | {"as_of": "2026-09-30", "quote_kind": "observed", "price": "101.25", "yield_pct": "7.10"},
    SERVICE | LOAN | {"as_of": "2026-09-30", "quote_kind": "observed", "price": "98.60"},
    SERVICE
    | NOTES
    | {"as_of": "2026-09-30", "quote_kind": "observed", "bid": "100.875", "ask": "101.375"},
    DEALER | LOAN | {"as_of": "2026-10-15", "quote_kind": "indicative_talk", "spread_bps": "350"},
    DEALER | NOTES | {"as_of": "2026-10-15", "quote_kind": "indicative_talk", "price": "101.50"},
)
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"
SPREADSHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml"
TEXT_STYLE = 1  # cellXfs index of the Text number format (`@`, built-in id 49)
WIDTHS = {"provider": 28, "issuer": 32, "instrument": 40, "note": 40}

# The portfolio template (task PF-1): a fictional CLO whose NAV-level figures are the design
# mock's (NAV US$ 630,928,502 at 2026-05-29; limits C-01, C-04, C-05, C-10 and SECTOR), so the
# Portfolio Fit module's differential against the design `fit` object has data.
PORTFOLIO_README = (
    "synthetic example — replace every row",
    "Every row is invented for a fictional fund (Test CLO I Ltd (synthetic)) and fictional "
    "issuers; none of it is fund or market data.",
    "Keep each sheet's row 1 exactly as it is and enter one row per item from row 2. "
    "Holdings_Detail is optional: delete the sheet if you do not supply positions.",
    "Percent cells are plain numbers (2.5 means 2.5 % NAV); dates are text YYYY-MM-DD; enter "
    "values, not formulas.",
    "Python computes 1 % of NAV and every sum: leave out one_pct_nav and total rows.",
    "Check the file before prepare: deploy-vii validate-input portfolio <file>",
    "Sheet, column and message guide: docs/templates/README.md",
)
AS_OF = "2026-05-29"
FUND = "Test CLO I Ltd (synthetic)"


def mandate_row(section: str, field: str, value: str, notes: str = "") -> Mapping[str, str]:
    return {"section": section, "field": field, "value": value, "notes": notes}


def metric(name: str, value: str, unit: str) -> Mapping[str, str]:
    return {"metric": name, "value": value, "unit": unit, "as_of": AS_OF}


def limit(
    identifier: str, category: str, parameter: str, values: tuple[str, str, str, str, str]
) -> Mapping[str, str]:
    """A % NAV compliance row: (limit, breach_type, scope, current_value, headroom), with the
    status the validator's rules require."""
    ceiling, breach_type, scope, current, headroom = values
    status = "Watch" if identifier in ("C-01", "C-04") else "Pass"
    return {
        "id": identifier,
        "constraint_category": category,
        "parameter": parameter,
        "limit": ceiling,
        "limit_unit": "% NAV",
        "breach_type": breach_type,
        "scope": scope,
        "source_document": "Indenture §7.11 (synthetic)",
        "current_value": current,
        "headroom": headroom,
        "status": status,
        "last_checked": AS_OF,
        "checked_by": "analyst",
    }


ISSUERS = (
    ("Alpha Example Holdings (synthetic)", "Term Loan B due 2030 (synthetic)", "B3 / B"),
    ("Beta Sample Aerospace (synthetic)", "Term Loan B due 2031 (synthetic)", "Ba3 / BB-"),
    ("Gamma Illustrative Media (synthetic)", "Term Loan B due 2029 (synthetic)", "B2 / B"),
    ("Delta Placeholder Networks (synthetic)", "Term Loan due 2028 (synthetic)", "B1 / B+"),
    ("Epsilon Demo Leisure (synthetic)", "Senior Secured Notes due 2032 (synthetic)", "B2 / B+"),
)
POSITIONS = (  # facility_id, par, market_value, pct_nav, sector, seniority, maturity
    ("TLB-2030", "15000000", "14951250", "2.37", "Insurance", "1st Lien", "2030-06-30"),
    ("TLB-2031", "12100000", "12043500", "1.91", "Aerospace & Defense", "1st Lien", "2031-03-31"),
    ("TLB-2029", "9000000", "8990625", "1.42", "Entertainment Content", "1st Lien", "2029-12-31"),
    ("TL-2028", "6100000", "6031875", "0.96", "Cable & Satellite", "1st Lien", "2028-09-30"),
    (
        "SSN-2032",
        "6000000",
        "6026250",
        "0.96",
        "Leisure Facilities & Services",
        "Senior Secured",
        "2032-07-15",
    ),
)
PORTFOLIO_ROWS: Mapping[str, tuple[Mapping[str, str], ...]] = {
    "Mandate": (
        mandate_row("Strategy", "fund_name", FUND, "fictional fund"),
        mandate_row("Strategy", "strategy", "CLO"),
        mandate_row("Strategy", "non_call_period", "2025-03-15 to 2027-03-15", "2 years"),
        mandate_row("Strategy", "legal_final_maturity", "2038-03-15"),
        mandate_row("Key Parties", "collateral_manager", "Synthetic Asset Management LLP"),
        mandate_row("Key Parties", "trustee", "Synthetic Trustee Bank"),
        mandate_row("Capital Structure", "nav", "630928502", "collateral pool market value"),
        mandate_row("Capital Structure", "nav_currency", "USD"),
        mandate_row("Capital Structure", "subordinated_notes", "USD 50,000,000", "first loss"),
        mandate_row("Mandate Constraints", "constraint_schedule", "see Compliance_Monitor"),
        mandate_row("Liquidity Terms", "redemption", "none (CLO structure)", "callable after NC"),
        mandate_row("Fees", "senior_management_fee", "15 bps p.a. on collateral balance"),
        mandate_row("Reporting", "as_of", AS_OF, "NAV and compliance date"),
        mandate_row("Reporting", "investor_reporting", "monthly trustee report"),
    ),
    "Exposure_Summary": (
        metric("nav", "630928502", "USD"),
        metric("total_par", "634000000", "USD"),
        metric("obligors", "350", "count"),
        metric("positions", "383", "count"),
        metric("sectors", "52", "count"),
        metric("war_notch", "14.3", "rating notch (B1)"),
        metric("wa_margin", "313", "bps"),
        metric("wa_ytm", "3.29", "%"),
        metric("wal", "4.82", "years"),
        metric("wa_price", "99.578", "price"),
        metric("first_lien_pct_nav", "99.39", "% NAV"),
        metric("top10_pct_nav", "11.05", "% NAV"),
    ),
    "Rating_Distribution": tuple(
        {"rating_bucket": bucket, "pct_nav": pct, "issuers": issuers}
        for bucket, pct, issuers in (
            ("IG (Baa+)", "0.32", "1"),
            ("BB (Ba)", "25.02", "70"),
            ("B", "67.30", "259"),
            ("CCC (Caa+)", "0.14", "1"),
            ("Other", "3.50", "11"),
            ("Unrated", "3.73", "10"),
        )
    ),
    "Sector_Exposure": tuple(
        {
            "sector": sector,
            "pct_nav": pct,
            "issuers": issuers,
            "limit_pct_nav": "10.0",
            "headroom_pct_nav": headroom,
            "status": "Pass",
        }
        for sector, pct, issuers, headroom in (
            ("Health Care Facilities & Services", "7.16", "25", "2.84"),
            ("Commercial Support Services", "6.74", "36", "3.26"),
            ("Insurance", "5.63", "11", "4.37"),
            ("Software", "5.31", "39", "4.69"),
            ("Leisure Facilities & Services", "4.57", "19", "5.43"),
        )
    ),
    "Top_Holdings": tuple(
        {
            "rank": str(rank),
            "issuer": issuer,
            "instrument": instrument,
            "pct_nav": position[3],
            "rating": rating,
        }
        for rank, ((issuer, instrument, rating), position) in enumerate(
            zip(ISSUERS, POSITIONS, strict=True), 1
        )
    ),
    "Maturity_Profile": tuple(
        {"bucket": bucket, "pct_nav": pct}
        for bucket, pct in (
            ("< 1 Year", "0.15"),
            ("1-2 Years", "3.78"),
            ("2-3 Years", "12.56"),
            ("3-5 Years", "29.20"),
            ("5-7 Years", "54.31"),
        )
    ),
    "Compliance_Monitor": (
        limit(
            "C-01",
            "Single Name",
            "Max single issuer exposure",
            ("2.5", "Hard", "issuer", "2.37", "0.13"),
        ),
        limit(
            "C-04",
            "Rating - CCC Bucket",
            "Max CCC+ and below (incl. Unrated and Other)",
            ("7.5", "Hard", "rating_bucket", "7.36", "0.14"),
        ),
        limit(
            "C-05",
            "Rating - Unrated",
            "Max unrated exposure",
            ("5.0", "Soft", "rating_bucket", "3.73", "1.27"),
        ),
        limit(
            "C-10",
            "Instrument",
            "Max 2nd Lien / Unsecured",
            ("10.0", "Soft", "seniority", "0.61", "9.39"),
        ),
        limit(
            "SECTOR",
            "Sector",
            "Max single sector (candidate's sector: Leisure Facilities & Services)",
            ("10.0", "Soft", "sector", "4.57", "5.43"),
        ),
    ),
    "Holdings_Detail": tuple(
        {
            "issuer": issuer,
            "instrument": instrument,
            "facility_id": facility,
            "par": par,
            "market_value": value,
            "pct_nav": pct,
            "rating": rating,
            "sector": sector,
            "seniority": seniority,
            "maturity": maturity,
        }
        for (issuer, instrument, rating), (
            facility,
            par,
            value,
            pct,
            sector,
            seniority,
            maturity,
        ) in zip(ISSUERS, POSITIONS, strict=True)
    ),
}
PORTFOLIO_WIDTHS = {
    "field": 26,
    "value": 40,
    "notes": 32,
    "metric": 22,
    "unit": 20,
    "rating_bucket": 16,
    "sector": 36,
    "issuer": 40,
    "instrument": 44,
    "constraint_category": 22,
    "parameter": 60,
    "source_document": 28,
}


def cell(reference: str, value: str, *, numeric: bool) -> str:
    if numeric:
        return f'<c r="{reference}"><v>{value}</v></c>'
    return (
        f'<c r="{reference}" s="{TEXT_STYLE}" t="inlineStr">'
        f'<is><t xml:space="preserve">{escape(value)}</t></is></c>'
    )


def table_sheet(
    columns: Sequence[str],
    numeric: Collection[str],
    rows: Sequence[Mapping[str, str]],
    widths: Mapping[str, int],
) -> str:
    """Values in `numeric` columns that are plain numbers are numeric cells; every other value
    is a text cell, and the other columns are formatted as Text so Excel keeps a typed date or
    id as entered."""
    letters = [cell_letters(index) for index in range(1, len(columns) + 1)]
    cols = "".join(
        f'<col min="{index}" max="{index}" width="{widths.get(name, 14)}" customWidth="1"'
        + ("" if name in numeric else f' style="{TEXT_STYLE}"')
        + "/>"
        for index, name in enumerate(columns, 1)
    )
    header = "".join(
        cell(f"{letter}1", name, numeric=False)
        for letter, name in zip(letters, columns, strict=True)
    )
    body = [f'<row r="1">{header}</row>']
    for number, row in enumerate(rows, 2):
        cells = "".join(
            cell(
                f"{letter}{number}",
                row[name],
                numeric=name in numeric and NUMBER.match(row[name]) is not None,
            )
            for letter, name in zip(letters, columns, strict=True)
            if row.get(name, "")
        )
        body.append(f'<row r="{number}">{cells}</row>')
    return (
        f'<worksheet xmlns="{MAIN}"><cols>{cols}</cols>'
        f"<sheetData>{''.join(body)}</sheetData></worksheet>"
    )


def quote_sheet(rows: Sequence[Mapping[str, str]]) -> str:
    """The `rv_quotes` sheet: levels are the numeric columns."""
    return table_sheet(COLUMNS, LEVELS, rows, WIDTHS)


def readme_sheet(lines: Sequence[str]) -> str:
    rows = "".join(
        f'<row r="{number}">{cell(f"A{number}", line, numeric=False)}</row>'
        for number, line in enumerate(lines, 1)
    )
    return (
        f'<worksheet xmlns="{MAIN}"><cols><col min="1" max="1" width="96" customWidth="1"/>'
        f"</cols><sheetData>{rows}</sheetData></worksheet>"
    )


def package(sheets: Sequence[tuple[str, str]]) -> bytes:
    """A workbook of (sheet name, worksheet XML) in order, with the shared Text style."""
    numbers = range(1, len(sheets) + 1)
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{number}.xml" '
        f'ContentType="{SPREADSHEET}.worksheet+xml"/>'
        for number in numbers
    )
    entries = "".join(
        f'<sheet name="{escape(name, {chr(34): "&quot;"})}" sheetId="{number}" r:id="rId{number}"/>'
        for number, (name, _) in zip(numbers, sheets, strict=True)
    )
    relationships = "".join(
        f'<Relationship Id="rId{number}" Type="{OFFICE}/worksheet" '
        f'Target="worksheets/sheet{number}.xml"/>'
        for number in numbers
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{SPREADSHEET}.sheet.main+xml"/>'
            f"{overrides}"
            f'<Override PartName="/xl/styles.xml" ContentType="{SPREADSHEET}.styles+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{PACKAGE}"><Relationship Id="rId1" '
            f'Type="{OFFICE}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            f'<workbook xmlns="{MAIN}" xmlns:r="{OFFICE}"><sheets>{entries}</sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{PACKAGE}">{relationships}'
            f'<Relationship Id="rId{len(sheets) + 1}" Type="{OFFICE}/styles" '
            'Target="styles.xml"/>'
            "</Relationships>"
        ),
        "xl/styles.xml": (
            f'<styleSheet xmlns="{MAIN}">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border>'
            "</borders>"
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
            "</cellStyleXfs>"
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" '
            'applyNumberFormat="1"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/>'
            "</cellStyles></styleSheet>"
        ),
    } | {
        f"xl/worksheets/sheet{number}.xml": content
        for number, (_, content) in zip(numbers, sheets, strict=True)
    }
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_STORED) as archive:
        for name, content in parts.items():
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, content.encode("utf-8"), compress_type=ZIP_STORED)
    return stream.getvalue()


def workbook_bytes(
    rows: Sequence[Mapping[str, str]], readme: Sequence[str] = README_LINES
) -> bytes:
    """The quote template workbook for `rows` (column name to stored lexeme; an absent or empty
    value leaves its cell out)."""
    return package(((SHEET, quote_sheet(rows)), (README_SHEET, readme_sheet(readme))))


def portfolio_bytes(
    sheets: Mapping[str, Sequence[Mapping[str, str]]], readme: Sequence[str] = PORTFOLIO_README
) -> bytes:
    """The portfolio workbook: the contract's sheets present in `sheets`, in contract order,
    then README. Number, count and rank columns hold numeric cells; the rest are Text."""
    numeric = {"number", "count", "rank"}
    return package(
        (
            *(
                (
                    sheet.name,
                    table_sheet(
                        sheet.names,
                        {column.name for column in sheet.columns if column.kind in numeric},
                        sheets[sheet.name],
                        PORTFOLIO_WIDTHS,
                    ),
                )
                for sheet in portfolio.SHEETS
                if sheet.name in sheets
            ),
            (README_SHEET, readme_sheet(readme)),
        )
    )


def build(destination: Path) -> None:
    destination.write_bytes(workbook_bytes(SYNTHETIC_ROWS))


def build_portfolio(destination: Path) -> None:
    destination.write_bytes(portfolio_bytes(PORTFOLIO_ROWS))


def main() -> None:
    for template, write in ((TEMPLATE, build), (portfolio.TEMPLATE, build_portfolio)):
        destination = ROOT / template
        destination.parent.mkdir(parents=True, exist_ok=True)
        write(destination)
        print(destination.relative_to(ROOT))


if __name__ == "__main__":
    main()
