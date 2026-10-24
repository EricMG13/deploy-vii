"""Write docs/templates/rv-quotes.template.xlsx, byte for byte the same on every run (task RV-1).

Run from the repository root: `uv run python scripts/build_templates.py`.

The workbook is plain OOXML written with the standard library: inline strings, stored (not
deflated) ZIP members in a fixed order with a fixed 1980-01-01 timestamp, so the bytes depend
only on the rows below and not on the clock, the platform or the zlib build. The header comes
from `deploy_vii.inputs.rv_quotes.COLUMNS`. Every row is synthetic: a fictional issuer and
fictional providers, no market data.
"""

import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from deploy_vii.inputs.rv_quotes import COLUMNS, LETTERS, LEVELS, NUMBER, SHEET, TEMPLATE

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


def cell(reference: str, value: str, *, numeric: bool) -> str:
    if numeric:
        return f'<c r="{reference}"><v>{value}</v></c>'
    return (
        f'<c r="{reference}" s="{TEXT_STYLE}" t="inlineStr">'
        f'<is><t xml:space="preserve">{escape(value)}</t></is></c>'
    )


def quote_sheet(rows: Sequence[Mapping[str, str]]) -> str:
    """Levels that are plain numbers are numeric cells; every other value is a text cell, and
    the text columns are formatted as Text so Excel keeps a typed date or id as entered."""
    columns = "".join(
        f'<col min="{index}" max="{index}" width="{WIDTHS.get(name, 14)}" customWidth="1"'
        + ("" if name in LEVELS else f' style="{TEXT_STYLE}"')
        + "/>"
        for index, name in enumerate(COLUMNS, 1)
    )
    header = "".join(
        cell(f"{letter}1", name, numeric=False)
        for letter, name in zip(LETTERS, COLUMNS, strict=True)
    )
    body = [f'<row r="1">{header}</row>']
    for number, row in enumerate(rows, 2):
        cells = "".join(
            cell(
                f"{letter}{number}",
                row[name],
                numeric=name in LEVELS and NUMBER.match(row[name]) is not None,
            )
            for letter, name in zip(LETTERS, COLUMNS, strict=True)
            if row.get(name, "")
        )
        body.append(f'<row r="{number}">{cells}</row>')
    return (
        f'<worksheet xmlns="{MAIN}"><cols>{columns}</cols>'
        f"<sheetData>{''.join(body)}</sheetData></worksheet>"
    )


def readme_sheet(lines: Sequence[str]) -> str:
    rows = "".join(
        f'<row r="{number}">{cell(f"A{number}", line, numeric=False)}</row>'
        for number, line in enumerate(lines, 1)
    )
    return (
        f'<worksheet xmlns="{MAIN}"><cols><col min="1" max="1" width="96" customWidth="1"/>'
        f"</cols><sheetData>{rows}</sheetData></worksheet>"
    )


def workbook_bytes(
    rows: Sequence[Mapping[str, str]], readme: Sequence[str] = README_LINES
) -> bytes:
    """The template workbook for `rows` (column name to stored lexeme; an absent or empty value
    leaves its cell out)."""
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{SPREADSHEET}.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            f'ContentType="{SPREADSHEET}.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" '
            f'ContentType="{SPREADSHEET}.worksheet+xml"/>'
            f'<Override PartName="/xl/styles.xml" ContentType="{SPREADSHEET}.styles+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{PACKAGE}"><Relationship Id="rId1" '
            f'Type="{OFFICE}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            f'<workbook xmlns="{MAIN}" xmlns:r="{OFFICE}"><sheets>'
            f'<sheet name="{SHEET}" sheetId="1" r:id="rId1"/>'
            f'<sheet name="{README_SHEET}" sheetId="2" r:id="rId2"/>'
            "</sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{PACKAGE}">'
            f'<Relationship Id="rId1" Type="{OFFICE}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{OFFICE}/worksheet" Target="worksheets/sheet2.xml"/>'
            f'<Relationship Id="rId3" Type="{OFFICE}/styles" Target="styles.xml"/>'
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
        "xl/worksheets/sheet1.xml": quote_sheet(rows),
        "xl/worksheets/sheet2.xml": readme_sheet(readme),
    }
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_STORED) as archive:
        for name, content in parts.items():
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, content.encode("utf-8"), compress_type=ZIP_STORED)
    return stream.getvalue()


def build(destination: Path) -> None:
    destination.write_bytes(workbook_bytes(SYNTHETIC_ROWS))


def main() -> None:
    destination = ROOT / TEMPLATE
    destination.parent.mkdir(parents=True, exist_ok=True)
    build(destination)
    print(destination.relative_to(ROOT))


if __name__ == "__main__":
    main()
