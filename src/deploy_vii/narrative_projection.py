"""Reader-facing synthesis and exact prior-row trace; projection, not acceptance."""

import json
from collections.abc import Iterator
from dataclasses import dataclass

from deploy_vii.contracts import Citation, Claim, Fact, ReportTable, TableColumn
from deploy_vii.financial_contracts import FinancialBook
from deploy_vii.model_interface import _Cell, _Tables
from deploy_vii.narrative import (
    _DIMENSIONS,
    EvidencePart,
    EvidenceRecord,
    IssuerPart,
    NarrativeReport,
    Passage,
    ProsePart,
)
from deploy_vii.statement_validation import REQUIRED_ITEMS

SCHEMAS = {
    "analysis-coverage": (
        "Analytical dimension coverage",
        None,
        ("Dimension", "Status", "Findings", "Rationale"),
    ),
    "funding-assessment": (
        "Non-debt funding assessment",
        None,
        ("Status", "Reviewed Evidence", "Material Evidence", "Rationale"),
    ),
    "required-stories": (
        "Required event and funding stories",
        None,
        ("Evidence", "Kind", "Reference", "Status", "Findings"),
    ),
    "evidence-trace": (
        "Evidence trace — exact prior records",
        None,
        (
            "Evidence",
            "Evidence ID",
            "Kind",
            "Reference",
            "Used By",
            "Artifact SHA256",
            "Record SHA256",
            "Fields",
        ),
    ),
    "statement-coverage": (
        "Financial statement coverage",
        None,
        (
            "Period",
            "Statement",
            "Supplied Lines",
            "Missing Required",
            "Conflicting",
            "Not Applicable",
            "Scope",
        ),
    ),
}


@dataclass(frozen=True)
class NarrativeProjection:
    claims: tuple[Claim, ...]
    facts: tuple[Fact, ...]
    tables: tuple[ReportTable, ...]


def _fields(value: object, path: str = "") -> Iterator[str]:
    """Lossless leaf text with JSON-pointer paths and JSON scalar spelling."""
    if isinstance(value, dict) and value:
        for key, child in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            yield from _fields(child, path + "/" + escaped)
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from _fields(child, path + "/" + str(index))
    else:
        yield f"{path or '/'} = {json.dumps(value, ensure_ascii=False, allow_nan=False)}"


def _passage(
    passage: Passage,
    issuer_name: str,
    catalogue: dict[str, EvidenceRecord],
    uses: dict[str, list[str]],
    labels: dict[str, str],
    owner: str,
) -> tuple[str, tuple[Citation, ...]]:
    """Resolve tokens in order; source records remain distinct from analyst prose."""
    fragments: list[str] = []
    citations: list[Citation] = []
    for part in passage:
        if isinstance(part, ProsePart):
            fragments.append(part.text)
        elif isinstance(part, IssuerPart):
            fragments.append(issuer_name)
        elif isinstance(part, EvidencePart):
            record = catalogue[part.evidence_id]
            fragments.append(f"[{labels[record.evidence_id]}]")
            citations.extend(record.citations)
            uses.setdefault(record.evidence_id, []).append(owner)
    return "".join(fragments), tuple(dict.fromkeys(citations))


def project_narrative(
    book: FinancialBook, report: NarrativeReport, issuer_name: str
) -> NarrativeProjection:
    """Project caller-recomputed records; this helper does not authenticate inputs."""
    catalogue = {r.evidence_id: r for r in report.inputs.catalogue}
    uses: dict[str, list[str]] = {}
    labels = {identity: f"E{index}" for index, identity in enumerate(catalogue, 1)}
    tables = _Tables(
        book,
        schemas={
            key: (title, None, tuple(c.lower().replace(" ", "_") for c in columns))
            for key, (title, _, columns) in SCHEMAS.items()
        },
    )
    claims: list[Claim] = []
    for finding in report.review.findings:
        sections = []
        citations: list[Citation] = []
        for label, field, passage in (
            ("Evidence", "evidence", finding.evidence),
            ("Risk mechanic", "risk_mechanic", finding.risk_mechanic),
            ("Credit implication", "credit_implication", finding.credit_implication),
        ):
            text, refs = _passage(
                passage, issuer_name, catalogue, uses, labels, f"{finding.finding_id}/{field}"
            )
            sections.append(f"{label}\n{text}")
            citations.extend(refs)
        claims.append(
            Claim(
                claim_id=finding.finding_id,
                text=f"{finding.dimension.replace('_', ' ').capitalize()} · {finding.title}\n\n"
                + "\n\n".join(sections),
                citations=tuple(dict.fromkeys(citations)),
                limitation=(
                    "Analyst synthesis over referenced prior records. Inspect Evidence Trace for "
                    "exact values, units, periods, roles and hashes. "
                    "Semantic qualification is unrun."
                ),
            )
        )
    coverage = {c.dimension: c for c in report.review.coverage}
    for dimension in _DIMENSIONS:
        assessment = coverage.get(dimension)
        if assessment:
            rationale, refs = _passage(
                assessment.rationale, issuer_name, catalogue, uses, labels, f"coverage/{dimension}"
            )
            status, findings = assessment.status, assessment.finding_ids
        else:
            rationale, refs = "No coverage assessment supplied", ()
            status, findings = "unassessed", ()
        tables.row(
            "analysis-coverage",
            (dimension,),
            "Narrative scope: " + report.inputs.scope,
            dict(
                zip(
                    tables.schemas["analysis-coverage"][2],
                    (
                        dimension,
                        status,
                        "; ".join(findings) or "None supplied",
                        rationale,
                    ),
                    strict=True,
                )
            ),
            refs,
        )
    funding = report.review.funding
    rationale, refs = _passage(
        funding.rationale, issuer_name, catalogue, uses, labels, "funding/rationale"
    )
    for role, identities in (
        ("reviewed", funding.reviewed_statement_ids),
        ("material", funding.material_statement_ids),
    ):
        for identity in identities:
            uses.setdefault(identity, []).append("funding/" + role)
    tables.row(
        "funding-assessment",
        ("funding",),
        "Declared prior balance-sheet scope",
        dict(
            zip(
                tables.schemas["funding-assessment"][2],
                (
                    funding.status,
                    "; ".join(funding.reviewed_statement_ids) or "None supplied",
                    "; ".join(funding.material_statement_ids) or "None supplied",
                    rationale,
                ),
                strict=True,
            )
        ),
        refs,
    )
    stories = {s.evidence_id: s for s in report.review.stories}
    for identity in report.required_story_ids:
        record = catalogue[identity]
        story = stories.get(identity)
        uses.setdefault(identity, []).append("required-story")
        tables.row(
            "required-stories",
            (identity,),
            "See exact event or funding record",
            dict(
                zip(
                    tables.schemas["required-stories"][2],
                    (
                        identity,
                        record.kind,
                        record.reference,
                        "supplied" if story else "missing",
                        "; ".join(story.finding_ids)
                        if story
                        else "No finding supplied; BLOCK gap retained",
                    ),
                    strict=True,
                )
            ),
            record.citations,
        )
    for identity, owners in uses.items():
        record = catalogue[identity]
        data = json.loads(record.record_json)
        period = next(
            (
                p
                for p in book.periods
                if record.kind.startswith("statement_") and p.period_id == data["period_id"]
            ),
            None,
        )
        fields = _Cell(
            "\n".join(_fields(data)),
            record.citations,
            unit=book.unit if period else None,
            currency=book.currency if period else None,
            period=f"{period.period_id}: {period.start_date} to {period.end_date}"
            if period
            else None,
            note=(
                "Statement dimensions come from its validated financial book and period."
                if period
                else "Exact prior record. Dimensions not intrinsic to this record "
                "must be read from the referenced canonical registers; do not infer them."
            ),
        )
        tables.row(
            "evidence-trace",
            (identity,),
            "Prior-record scope; inspect fields and canonical registers",
            dict(
                zip(
                    tables.schemas["evidence-trace"][2],
                    (
                        labels[identity],
                        identity,
                        record.kind,
                        record.reference,
                        "; ".join(dict.fromkeys(owners)),
                        record.artifact_sha256,
                        record.record_sha256,
                        fields,
                    ),
                    strict=True,
                )
            ),
            record.citations,
        )
    statement_cells = report.inputs.ledger.audit.statements.cells
    for period in book.periods:
        for statement in ("IS", "CFS", "BS"):
            rows = [
                c
                for c in statement_cells
                if c.period_id == period.period_id and c.statement == statement
            ]
            references = tuple(dict.fromkeys(c for row in rows for c in row.citations))
            tables.row(
                "statement-coverage",
                (period.period_id, statement),
                f"{period.start_date} to {period.end_date}",
                dict(
                    zip(
                        tables.schemas["statement-coverage"][2],
                        (
                            period.period_id,
                            statement,
                            str(sum(c.line_id is not None for c in rows)),
                            "; ".join(
                                c.item_id
                                for c in rows
                                if c.item_id in REQUIRED_ITEMS[statement] and c.status == "missing"
                            )
                            or "None in declared scope",
                            "; ".join(c.item_id for c in rows if c.status == "conflicting")
                            or "None in declared scope",
                            "; ".join(c.item_id for c in rows if c.status == "not_applicable")
                            or "None in declared scope",
                            "Point-in-time period; flow statement not applicable"
                            if period.period_type == "PERIOD_END" and statement != "BS"
                            else "Declared extraction only; filing completeness is unqualified",
                        ),
                        strict=True,
                    )
                ),
                references,
            )
    facts = tuple(
        f.model_copy(
            update={
                "label": f.table_id.replace("-", " ").capitalize() + " · " + f.field,
                "value_class": "analyst_judgment"
                if f.table_id in {"analysis-coverage", "funding-assessment", "required-stories"}
                else None,
            }
        )
        for f in tables.facts
    )
    layouts = tuple(
        t.model_copy(
            update={
                "columns": tuple(
                    TableColumn(field=c.field, label=label)
                    for c, label in zip(t.columns, SCHEMAS[t.table_id][2], strict=True)
                ),
                "limitation": (
                    "Candidate projection of prior records and supplied analysis; "
                    "no analytical acceptance inferred."
                ),
            }
        )
        for t in tables.layouts()
    )
    return NarrativeProjection(tuple(claims), facts, layouts)
