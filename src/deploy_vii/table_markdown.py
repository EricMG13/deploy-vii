"""Deterministic table projection. No arithmetic or model-authored Markdown."""

import re
from dataclasses import dataclass
from html import escape, unescape

from deploy_vii.contracts import Module, ReportTable
from deploy_vii.render import table_display


def markdown_cell(value: str) -> str:
    # Controlled keys stay literal for table readers (e.g. source_id, FY2025).
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value):
        return value
    # Escape source content before adding the sole generated inline HTML token.
    return (
        escape(value, quote=True)
        .replace("\\", "&#92;")
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("*", "&#42;")
        .replace("_", "&#95;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )


def table_markdown(module: Module, table_id: str) -> str:
    module = Module.model_validate_json(module.model_dump_json())
    table: ReportTable = next(t for t in module.tables if t.table_id == table_id)
    facts = {fact.fact_id: fact for fact in module.facts}
    headings = [column.label for column in table.columns]
    if table.row_header:
        headings.insert(0, table.row_header)
    lines = ["| " + " | ".join(markdown_cell(h) for h in headings) + " |"]
    lines.append("|" + "|".join("---" for _ in headings) + "|")
    for row in table.rows:
        if table.interface_id and any(
            fact.status == "known"
            and fact.text is not None
            and fact.text.strip().casefold() in {"", "null", "n/a", "none", "—", "\u2013"}
            and not (
                table.interface_id == "cp1.debt_facility_register"
                and fact.field == "reference_rate"
                and fact.text == "NONE"
            )
            for fact in (facts[identity] for identity in row.fact_ids)
        ):
            raise ValueError("Known interface text would be confused with a null marker")
        values = [table_display(facts[identity]) for identity in row.fact_ids]
        if table.row_header:
            values.insert(0, row.label)
        lines.append("| " + " | ".join(markdown_cell(v) for v in values) + " |")
    if table.interface_id:
        lines.insert(0, f"<!-- table-id: {table.interface_id} -->\n")
    return "\n".join(lines)


@dataclass(frozen=True)
class MarkdownTable:
    interface_id: str | None
    headings: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def read_table_markdown(text: str) -> MarkdownTable:
    """Read one canonical table, decoding source text once; reject ambiguous syntax.

    This is a transport reader, not financial validation or artifact authentication.
    The literal null token remains text until a typed consumer interprets its field.
    """
    if len(text) > 4_000_000 or "\r" in text:
        raise ValueError("Noncanonical or oversized table")
    lines = text.split("\n")
    interface = None
    if lines[0].startswith("<!--"):
        match = re.fullmatch(r"<!-- table-id: ([A-Za-z0-9][A-Za-z0-9_.:-]{0,159}) -->", lines[0])
        if match is None or len(lines) < 4 or lines[1] != "":
            raise ValueError("Invalid table interface comment")
        interface = match[1]
        lines = lines[2:]
    if not 2 <= len(lines) <= 20_002:
        raise ValueError("Invalid table row count")

    def decode_row(line: str) -> tuple[str, ...]:
        if not line.startswith("| ") or not line.endswith(" |"):
            raise ValueError("Noncanonical table row")
        encoded_cells = line[2:-2].split(" | ")
        if not 1 <= len(encoded_cells) <= 1024:
            raise ValueError("Invalid table column count")
        decoded_cells = tuple(unescape(cell.replace("<br>", "\n")) for cell in encoded_cells)
        if any(
            markdown_cell(decoded) != encoded
            for decoded, encoded in zip(decoded_cells, encoded_cells, strict=True)
        ):
            raise ValueError("Noncanonical cell encoding")
        return decoded_cells

    headings = decode_row(lines[0])
    if any(not heading for heading in headings) or len(set(headings)) != len(headings):
        raise ValueError("Empty or duplicate table heading")
    separator = "|" + "|".join("---" for _ in headings) + "|"
    if lines[1] != separator:
        raise ValueError("Table separator differs from its headings")
    # Decode every row before checking shape, preserving malformed-row precedence.
    rows = tuple(decode_row(line) for line in lines[2:])
    if any(len(row) != len(headings) for row in rows):
        raise ValueError("Nonrectangular table")
    if interface and any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", heading) for heading in headings
    ):
        raise ValueError("Interface headings must be literal field keys")
    return MarkdownTable(interface, headings, rows)


def validate_table_markdown(module: Module, table_id: str, text: str) -> tuple[str, ...]:
    """Verify complete table parity against the caller's trusted artifact."""
    try:
        actual = read_table_markdown(text)
        expected = read_table_markdown(table_markdown(module, table_id))
    except (ValueError, StopIteration) as error:
        return (f"Invalid table projection: {error}",)
    return () if actual == expected else ("Table differs from trusted artifact projection",)
