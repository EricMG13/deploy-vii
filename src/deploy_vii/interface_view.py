"""Candidate statements plus Model interface tables; no Module promotion."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from deploy_vii.contracts import Contract, Module, View
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.model_interface import ModelInterface, model_interface
from deploy_vii.preparation import PreparedPack
from deploy_vii.render import render
from deploy_vii.statement_history import StatementHistoryReport, statement_history
from deploy_vii.statement_view import statement_view
from deploy_vii.table_markdown import markdown_cell, table_markdown, validate_table_markdown


class InterfacePreview(Contract):
    schema_version: Literal["interface-preview/1"] = "interface-preview/1"
    statements: StatementHistoryReport
    interface: ModelInterface


def write_interface_preview(
    pack: PreparedPack,
    financial: FinancialReview,
    book_id: str,
    destination: Path,
    *,
    quarter_ids: tuple[str, ...] | None = None,
    execution_binding: dict[str, str] | None = None,
) -> Path:
    pack = PreparedPack.model_validate_json(pack.model_dump_json())
    report = InterfacePreview(
        statements=statement_history(pack, financial, book_id),
        interface=model_interface(pack, financial, book_id, quarter_ids=quarter_ids),
    )
    source = statement_view(pack, financial, book_id)
    statement = next(m for m in source.modules if m.module_id == "CP-1")
    interface = report.interface.module
    module = Module(
        run_id=pack.run.run_id,
        issuer_id=pack.run.issuer_id,
        as_of=pack.run.as_of,
        module_id="CP-1",
        facts=(*statement.facts, *interface.facts),
        tables=(*statement.tables, *interface.tables),
        limitations=(*statement.limitations, *interface.limitations),
    )
    updated = statement.model_copy(
        update={
            "facts": module.facts,
            "tables": module.tables,
            "artifact_sha256": report.content_hash(),
            "limitations": module.limitations,
        }
    )
    view = View.model_validate_json(
        source.model_copy(
            update={
                "modules": tuple(updated if m.module_id == "CP-1" else m for m in source.modules),
            }
        ).model_dump_json()
    )
    sections = [
        "# CP-1 table preview",
        "Candidate only. This is not the canonical Markdown handoff; "
        "remaining CP-1 registers, narrative/QA envelope and final Module validation are pending.",
    ]
    for table in module.tables:
        raw = table_markdown(module, table.table_id)
        issues = validate_table_markdown(module, table.table_id, raw)
        if issues:
            raise ValueError("; ".join(issues))
        sections.extend((f"#### {table.table_id} — {table.title}", raw))
    labels = {(t.table_id, row.row_id): row.label for t in interface.tables for row in t.rows}
    gaps = [
        (g.table_id, labels[g.table_id, g.row_id], g.field, g.reason) for g in report.interface.gaps
    ]
    gaps.extend(
        (f.table_id, f.row_id, f.field, f.limitation or "Unavailable")
        for f in statement.facts
        if f.status != "known"
    )
    sections.append("## Gaps & Conflicts")
    sections.extend(
        f"- {markdown_cell(table)}, {markdown_cell(row)}, `{field}`: null — {markdown_cell(reason)}"
        for table, row, field, reason in gaps
    )
    sections.append("## Scope and limitations")
    sections.extend("- " + markdown_cell(note) for note in module.limitations)
    payloads = {
        "interface-preview.json": report.model_dump_json(),
        "view.json": view.model_dump_json(),
        "tables.md": "\n\n".join(sections) + "\n",
        "candidate.html": render(view),
    }
    receipt = {
        "schema_version": "interface-preview-receipt/1",
        "artifact_sha256": report.content_hash(),
        "pack_sha256": pack.content_hash(),
        "review_sha256": financial.content_hash(),
        "execution_binding": execution_binding,
        "module_acceptance": "unrun",
        "analytical_qualification": "unrun",
        "browser_acceptance": "unrun",
        "files": {name: hashlib.sha256(raw.encode()).hexdigest() for name, raw in payloads.items()},
    }
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        (destination / name).write_text(raw, encoding="utf-8")
    (destination / "complete.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return destination / "candidate.html"
