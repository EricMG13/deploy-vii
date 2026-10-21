"""Deterministic table projection. No arithmetic or model-authored Markdown."""

import re
from html import escape

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
