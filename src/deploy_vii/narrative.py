"""CP-1 synthesis over prior registers; model prose cannot supply numeric fields."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from deploy_vii import prose
from deploy_vii.canonical_audit import DefinitionReview
from deploy_vii.canonical_gaps import CanonicalGapReport, GapDetail, LedgerGap, canonical_gaps
from deploy_vii.context_binding import FinancialContextBinding
from deploy_vii.contracts import PREFILLED_MARKER, Citation, Contract, Hash, Identifier, Text
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.financial_periods import _id
from deploy_vii.financial_validation import records
from deploy_vii.preparation import PreparedPack
from deploy_vii.source_context import SourceContextReview
from deploy_vii.statement_output import StatementCell
from deploy_vii.statement_validation import OPTIONAL_ITEMS, REQUIRED_ITEMS

Dimension = Literal[
    "leverage",
    "coverage",
    "cash_flow_quality",
    "liquidity",
    "data_quality",
    "definition_risks",
    "key_gaps",
]
_DIMENSIONS: tuple[Dimension, ...] = (
    "leverage",
    "coverage",
    "cash_flow_quality",
    "liquidity",
    "data_quality",
    "definition_risks",
    "key_gaps",
)
_FINANCIAL = {"leverage", "coverage", "cash_flow_quality", "liquidity"}


def _prose(value: str) -> str:
    """Labels (periods, filings, instruments, sections, versions) pass; a bare figure fails.

    The shared run-text rule (``prose.check``, decision 0005 MC-2) with no resolvable ids:
    numbers and gaps enter CP-1 prose only as evidence parts, so any run reference fails too.
    """
    issues = prose.check(value, refs=(), gaps=())
    if not value.strip() or issues:
        raise ValueError(
            "Narrative prose must be nonblank and use evidence references for numbers"
            + "".join(f"; {issue}" for issue in issues)
        )
    return value


Prose = Annotated[Text, AfterValidator(_prose)]


class ProsePart(Contract):
    kind: Literal["prose"] = "prose"
    text: Prose


class EvidencePart(Contract):
    kind: Literal["evidence"] = "evidence"
    evidence_id: Identifier


class IssuerPart(Contract):
    kind: Literal["issuer"] = "issuer"


Part = Annotated[ProsePart | EvidencePart | IssuerPart, Field(discriminator="kind")]
Passage = Annotated[tuple[Part, ...], Field(min_length=1, max_length=100)]


class EvidenceRecord(Contract):
    evidence_id: Identifier
    kind: Text
    reference: Text
    artifact_sha256: Hash
    record_sha256: Hash
    # Exact serialized prior row, never model-authored replacement data.
    record_json: Text
    citations: tuple[Citation, ...]


class NarrativeInputs(Contract):
    schema_version: Literal["narrative-inputs/1"] = "narrative-inputs/1"
    ledger: CanonicalGapReport
    catalogue: tuple[EvidenceRecord, ...]
    scope: Literal["financial_synthesis", "data_quality_only"]


class Finding(Contract):
    finding_id: Identifier
    dimension: Dimension
    title: Prose
    evidence: Passage
    risk_mechanic: Passage
    credit_implication: Passage


class DimensionCoverage(Contract):
    dimension: Dimension
    status: Literal["addressed", "unassessed", "not_applicable"]
    finding_ids: tuple[Identifier, ...]
    rationale: Passage


class StoryCoverage(Contract):
    evidence_id: Identifier
    finding_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]


class FundingAssessment(Contract):
    status: Literal["unassessed", "no_material_items", "material_items"]
    reviewed_statement_ids: tuple[Identifier, ...]
    material_statement_ids: tuple[Identifier, ...]
    rationale: Passage


class NarrativeReview(Contract):
    schema_version: Literal["narrative-review/1"] = "narrative-review/1"
    inputs_sha256: Hash = Field(json_schema_extra={PREFILLED_MARKER: "step-inputs"})
    findings: Annotated[tuple[Finding, ...], Field(max_length=20000)] = ()
    coverage: tuple[DimensionCoverage, ...] = ()
    stories: tuple[StoryCoverage, ...] = ()
    funding: FundingAssessment
    limitations: tuple[Prose, ...] = ()


class NarrativeReport(Contract):
    schema_version: Literal["canonical-narrative/1"] = "canonical-narrative/1"
    inputs: NarrativeInputs
    review: NarrativeReview
    required_story_ids: tuple[Identifier, ...]
    gaps: tuple[LedgerGap, ...]
    status: Literal["candidate", "restricted", "blocked"]
    analytical_qualification: Literal["unrun"] = "unrun"
    limitations: tuple[Text, ...]


def _catalogue(ledger: CanonicalGapReport) -> tuple[EvidenceRecord, ...]:
    result: list[EvidenceRecord] = []

    def add(kind: str, reference: str, artifact_hash: str, row: Contract) -> None:
        result.append(
            EvidenceRecord(
                evidence_id=_id("narrative-evidence", kind, reference),
                kind=kind,
                reference=reference,
                artifact_sha256=artifact_hash,
                record_sha256=row.content_hash(),
                record_json=row.model_dump_json(),
                citations=tuple(dict.fromkeys(records(row, Citation))),
            )
        )

    context, audit = ledger.context, ledger.audit
    context_hash, audit_hash, ledger_hash = (
        context.content_hash(),
        audit.content_hash(),
        ledger.content_hash(),
    )
    for source in context.sources:
        add("source", source.source_id, context_hash, source)
    for entity in context.entities:
        add("entity", entity.entity.entity_id, context_hash, entity)
    for event in context.events:
        add("subsequent_event", event.event_id, context_hash, event)
    for position in audit.source_positions:
        add("observation", position.observation.observation_id, audit_hash, position)
    statement_hash = audit.statements.content_hash()
    for cell in audit.statements.cells:
        add(
            "statement_" + cell.statement,
            _id("cell", cell.statement, cell.period_id, cell.item_id),
            statement_hash,
            cell,
        )
    for row in audit.normalizations:
        add("normalization", row.normalization_id, audit_hash, row)
    for definition in audit.definitions:
        add(
            "multi_figure_event" if definition.kind == "multi_figure_event" else "definition",
            definition.row_id,
            audit_hash,
            definition,
        )
    reconciliation_hash = audit.reconciliation.content_hash()
    for check in audit.reconciliation.checks:
        add("source_check", check.check_id, reconciliation_hash, check)
    for gap in ledger.gaps:
        add("gap", gap.gap_id, ledger_hash, gap)
    if ledger.kpis:
        kpis = ledger.kpis
        historical_hash, kpi_hash = kpis.historical.content_hash(), kpis.content_hash()
        for period in kpis.historical.periods:
            add("source_period", period.period_id, historical_hash, period)
        for construction in kpis.historical.constructions:
            add("construction", construction.construction_id, historical_hash, construction)
        for historical_value in kpis.historical.values:
            add("historical_value", historical_value.value_id, historical_hash, historical_value)
        for basis in kpis.bases:
            add("basis", basis.basis_id, kpi_hash, basis)
        for value in kpis.values:
            add("canonical_value", value.value_id, kpi_hash, value)
        for kpi in kpis.kpis:
            add("kpi", kpi.calculation_id, kpi_hash, kpi)
        for computation in kpis.computations:
            add("computation", computation.computation_id, kpi_hash, computation)
    if ledger.period_reconciliation:
        report_hash = ledger.period_reconciliation.content_hash()
        for period_check in ledger.period_reconciliation.checks:
            add("period_check", period_check.check_id, report_hash, period_check)
    if len(result) != len({r.evidence_id for r in result}):
        raise ValueError("Ambiguous narrative evidence identity")
    return tuple(result)


def narrative_inputs(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
) -> NarrativeInputs:
    ledger = canonical_gaps(pack, context, financial, definition, binding)
    return NarrativeInputs(
        ledger=ledger,
        catalogue=_catalogue(ledger),
        scope="financial_synthesis"
        if ledger.kpis and any(k.value.amount is not None for k in ledger.kpis.kpis)
        else "data_quality_only",
    )


def validate_narrative_review(inputs: NarrativeInputs, review: NarrativeReview) -> tuple[str, ...]:
    """Validate against supplied inputs; canonical_narrative recomputes those inputs."""
    try:
        inputs = NarrativeInputs.model_validate_json(inputs.model_dump_json())
        review = NarrativeReview.model_validate_json(review.model_dump_json())
        if inputs.catalogue != _catalogue(inputs.ledger):
            return ("Narrative catalogue differs from its prior registers",)
        scope = (
            "financial_synthesis"
            if inputs.ledger.kpis
            and any(k.value.amount is not None for k in inputs.ledger.kpis.kpis)
            else "data_quality_only"
        )
        if inputs.scope != scope:
            return ("Narrative scope differs from available KPI evidence",)
    except ValueError as error:
        return (f"Invalid narrative contract: {error}",)
    issues: list[str] = []
    if review.inputs_sha256 != inputs.content_hash():
        issues.append("Narrative review does not bind current input registers")
    evidence = {r.evidence_id for r in inputs.catalogue}
    findings = {f.finding_id: f for f in review.findings}
    if len(findings) != len(review.findings):
        issues.append("Duplicate narrative finding identity")
    if len(review.coverage) != len({c.dimension for c in review.coverage}):
        issues.append("Duplicate narrative dimension coverage")
    if len(review.stories) != len({s.evidence_id for s in review.stories}):
        issues.append("Duplicate required-story coverage")
    for part in records(review, EvidencePart):
        if part.evidence_id not in evidence:
            issues.append(f"Unknown narrative evidence: {part.evidence_id}")
    dimension_findings: dict[Dimension, set[str]] = {d: set() for d in _DIMENSIONS}
    for finding in review.findings:
        dimension_findings[finding.dimension].add(finding.finding_id)
        if not any(isinstance(p, EvidencePart) for p in finding.evidence):
            issues.append(f"Finding lacks prior-register evidence: {finding.finding_id}")
        if not any(
            isinstance(p, IssuerPart)
            for p in (*finding.evidence, *finding.risk_mechanic, *finding.credit_implication)
        ):
            issues.append(f"Finding lacks explicit issuer binding: {finding.finding_id}")
        for name, passage in (
            ("risk", finding.risk_mechanic),
            ("credit", finding.credit_implication),
        ):
            if not any(isinstance(p, ProsePart) for p in passage):
                issues.append(f"Finding lacks {name} reasoning: {finding.finding_id}")
        if inputs.scope == "data_quality_only" and finding.dimension in _FINANCIAL:
            issues.append(f"Financial narrative requires an available KPI: {finding.finding_id}")
    for coverage in review.coverage:
        if not any(isinstance(p, ProsePart) for p in coverage.rationale):
            issues.append(f"Dimension lacks rationale: {coverage.dimension}")
        ids = coverage.finding_ids
        supplied = set(ids)
        if len(ids) != len(supplied) or any(
            i not in findings or findings[i].dimension != coverage.dimension for i in ids
        ):
            issues.append(f"Invalid dimension findings: {coverage.dimension}")
        if (coverage.status == "addressed") != bool(ids):
            issues.append(f"Dimension status contradicts findings: {coverage.dimension}")
        if supplied != dimension_findings[coverage.dimension]:
            issues.append(f"Dimension omits or contradicts supplied findings: {coverage.dimension}")
        if coverage.status == "not_applicable" and not any(
            isinstance(p, EvidencePart) for p in coverage.rationale
        ):
            issues.append(f"Inapplicable dimension lacks evidence: {coverage.dimension}")
    funding = review.funding
    reviewed, material = funding.reviewed_statement_ids, funding.material_statement_ids
    if not any(isinstance(p, ProsePart) for p in funding.rationale):
        issues.append("Funding assessment lacks rationale")
    balance_sheet = {
        r.evidence_id: StatementCell.model_validate_json(r.record_json)
        for r in inputs.catalogue
        if r.kind == "statement_BS"
    }
    reviewed_ids, material_ids = set(reviewed), set(material)
    for ids, distinct in ((reviewed, reviewed_ids), (material, material_ids)):
        if len(ids) != len(distinct) or any(
            i not in balance_sheet or balance_sheet[i].line_id is None for i in ids
        ):
            issues.append("Funding assessment requires distinct located prior balance-sheet rows")
    standard_items = {*REQUIRED_ITEMS["BS"], *OPTIONAL_ITEMS["BS"]}
    for evidence_id in material:
        cell = balance_sheet.get(evidence_id)
        if cell and (cell.line_kind != "detail" or cell.item_id in standard_items):
            issues.append(f"Funding story requires named non-debt liability detail: {evidence_id}")
    if not material_ids <= reviewed_ids:
        issues.append("Material funding rows must be part of the reviewed scope")
    if (funding.status == "material_items") != bool(material):
        issues.append("Funding conclusion contradicts material rows")
    if funding.status != "unassessed" and not reviewed:
        issues.append("Assessed funding conclusion requires reviewed balance-sheet scope")
    required = {
        r.evidence_id
        for r in inputs.catalogue
        if r.kind in {"subsequent_event", "multi_figure_event"}
    } | material_ids
    finding_evidence: dict[str, set[str]] = {}
    for story in review.stories:
        if story.evidence_id not in required:
            issues.append(f"Unknown required story: {story.evidence_id}")
        if len(story.finding_ids) != len(set(story.finding_ids)):
            issues.append(f"Duplicate story finding: {story.evidence_id}")
        for finding_id in story.finding_ids:
            story_finding = findings.get(finding_id)
            evidence_ids = finding_evidence.get(finding_id)
            if evidence_ids is None and story_finding is not None:
                evidence_ids = {
                    p.evidence_id for p in story_finding.evidence if isinstance(p, EvidencePart)
                }
                finding_evidence[finding_id] = evidence_ids
            if evidence_ids is None or story.evidence_id not in evidence_ids:
                issues.append(
                    f"Story finding lacks its required evidence: {story.evidence_id} {finding_id}"
                )
    return tuple(issues)


def canonical_narrative(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
    review: NarrativeReview,
) -> NarrativeReport:
    inputs = narrative_inputs(pack, context, financial, definition, binding)
    issues = validate_narrative_review(inputs, review)
    if issues:
        raise ValueError("; ".join(issues))
    review = NarrativeReview.model_validate_json(review.model_dump_json())
    gaps = list(inputs.ledger.gaps)
    review_hash = review.content_hash()
    book_id = inputs.ledger.audit.definition_review.book_id

    def gap(reference: str, description: str, severity: Literal["WARN", "BLOCK"] = "WARN") -> None:
        detail = GapDetail(
            origin="narrative",
            artifact_sha256=review_hash,
            reference=reference,
            metric=None,
            periods=(),
            description=description,
            severity=severity,
            citations=(),
            downstream_impact="CP-1 analytical synthesis remains incomplete or limited",
            recommended_action=(
                "Review the prior registers and supply an evidence-risk-credit chain"
            ),
        )
        gaps.append(
            LedgerGap(gap_id=_id("cp1-gap", book_id, detail.content_hash()), **dict(detail))
        )

    coverage = {c.dimension: c for c in review.coverage}
    for dimension in _DIMENSIONS:
        if inputs.scope == "data_quality_only" and dimension in _FINANCIAL:
            continue
        if dimension not in coverage or coverage[dimension].status == "unassessed":
            gap(dimension, f"Narrative dimension is unassessed: {dimension}")
    if inputs.scope == "data_quality_only":
        gap("financial-synthesis", "No available KPI: narrative is limited to data quality")
    if review.funding.status == "unassessed":
        gap("funding-liabilities", "Material non-debt funding liabilities have not been assessed")
    located_bs = {
        r.evidence_id
        for r in inputs.catalogue
        if r.kind == "statement_BS"
        and StatementCell.model_validate_json(r.record_json).line_id is not None
    }
    if review.funding.status != "unassessed" and not located_bs <= set(
        review.funding.reviewed_statement_ids
    ):
        gap(
            "funding-review-coverage",
            "Funding review does not cover every located balance-sheet row",
        )
    required = tuple(
        dict.fromkeys(
            (
                *(
                    r.evidence_id
                    for r in inputs.catalogue
                    if r.kind in {"subsequent_event", "multi_figure_event"}
                ),
                *review.funding.material_statement_ids,
            )
        )
    )
    supplied = {s.evidence_id for s in review.stories}
    for story_id in required:
        if story_id not in supplied:
            gap(story_id, "Required event or non-debt funding story is missing", "BLOCK")
    for i, limitation in enumerate(review.limitations):
        gap(f"limitation:{i}", limitation)
    return NarrativeReport(
        inputs=inputs,
        review=review,
        required_story_ids=required,
        gaps=tuple(gaps),
        status="blocked"
        if any(g.severity == "BLOCK" for g in gaps)
        else "restricted"
        if gaps
        else "candidate",
        limitations=(
            "Structural evidence binding cannot prove issuer-specific meaning, "
            "materiality or reasoning quality",
            "All numeric evidence is supplied by prior registers; "
            "prose still requires semantic review",
            "Funding classification is an analyst synthesis over prior balance-sheet rows, "
            "not new extraction",
            "No consumer readiness, analytical qualification "
            "or completed Module acceptance is inferred",
        ),
    )


def validate_canonical_narrative(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
    review: NarrativeReview,
    report: NarrativeReport,
) -> tuple[str, ...]:
    try:
        report = NarrativeReport.model_validate_json(report.model_dump_json())
        expected = canonical_narrative(pack, context, financial, definition, binding, review)
    except ValueError as error:
        return (f"Invalid canonical narrative: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Canonical narrative differs from recomputed registers and review",)
    )
