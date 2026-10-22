"""Offline canonical-register candidate; final analytical handoff remains separate."""

import hashlib
import json
from pathlib import Path

from deploy_vii.canonical_tables import CanonicalTables
from deploy_vii.contracts import View
from deploy_vii.envelope import resolved_claims
from deploy_vii.preparation import PreparedPack
from deploy_vii.render import empty_view, render
from deploy_vii.report_view import build_index
from deploy_vii.table_markdown import table_markdown, validate_table_markdown


def write_register_preview(
    pack: PreparedPack,
    report: CanonicalTables,
    destination: Path,
    *,
    execution_binding: dict[str, str],
) -> Path:
    """Write a caller-recomputed report; schema validation alone is not authentication."""
    pack = PreparedPack.model_validate_json(pack.model_dump_json())
    report = CanonicalTables.model_validate_json(report.model_dump_json())
    if report.interface.pack_sha256 != pack.content_hash():
        raise ValueError("Register preview does not bind the supplied pack")
    base = empty_view(pack.run)
    digest = report.content_hash()
    module = report.module
    view = View.model_validate_json(
        base.model_copy(
            update={
                "mode": "candidate",
                "sources": pack.sources,
                "modules": tuple(
                    m.model_copy(
                        update={
                            "status": "candidate",
                            "artifact_sha256": digest,
                            "facts": module.facts,
                            "tables": module.tables,
                            "claims": module.claims,
                            "limitations": module.limitations,
                        }
                    )
                    if m.module_id == "CP-1"
                    else m
                    for m in base.modules
                ),
            }
        ).model_dump_json()
    )
    sections = [
        "# CP-1 canonical register preview",
        "Candidate only. This is not the final downstream Markdown handoff: the promoted "
        "canonical envelope is produced separately (`envelope --module CP-1`) once QA "
        "and promotion settle CP-1.",
    ]
    sections.append("## Analysis")
    # Resolved run text (decision 0005 MC-2), as in the canonical envelope: never raw tokens.
    _, index = build_index(view)
    claims = resolved_claims(module, index, (pack.run.issuer_name,))
    sections.extend(line for line, _ in claims)
    if not module.claims:
        sections.append("No analytical findings supplied. Review coverage and gap registers.")
    facts = {f.fact_id: f for f in module.facts}
    for table in module.tables:
        # A table-local validated artifact avoids parsing the complete large report
        # for each table while retaining every declared cell and its provenance.
        scoped = module.model_copy(
            update={
                "tables": (table,),
                "facts": tuple(facts[i] for row in table.rows for i in row.fact_ids),
            }
        )
        raw = table_markdown(scoped, table.table_id)
        issues = validate_table_markdown(scoped, table.table_id, raw)
        if issues:
            raise ValueError("; ".join(issues))
        sections.extend((f"## {table.table_id} — {table.title}", raw))
    payloads = {
        "canonical-registers.json": report.model_dump_json(),
        "view.json": view.model_dump_json(),
        "tables.md": "\n\n".join(sections) + "\n",
        "candidate.html": render(view),
    }
    receipt = {
        "schema_version": "register-preview/2",
        "artifact_sha256": digest,
        "pack_sha256": pack.content_hash(),
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
