"""CP-1 consumer sufficiency decisions; analytical judgments remain unqualified."""

import json
from typing import Annotated, Literal

from pydantic import Field

from deploy_vii.canonical_audit import DefinitionReview
from deploy_vii.context_binding import FinancialContextBinding
from deploy_vii.contracts import Contract, Hash, Identifier, Text
from deploy_vii.financial_contracts import FinancialBook, FinancialReview
from deploy_vii.model_readiness import ModelReadinessReport, assess_model_readiness
from deploy_vii.narrative import (
    EvidenceRecord,
    NarrativeReport,
    NarrativeReview,
    Prose,
    canonical_narrative,
    validate_narrative_review,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.registry import canonical
from deploy_vii.source_context import SourceContextReview

# Step 12's named dependencies. Aliases retain their own row, including the
# more specific CP-4A and CP-5A requirements; they do not create duplicate work.
_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "CP-1B": ("normalized_financials", "entity_scope"),
    "CP-1C": ("normalized_financials", "period_coverage"),
    "CP-2": ("kpi_dashboard", "calculation_register", "fcf_build"),
    "CP-2A": ("cash_flow_metrics", "liquidity_data"),
    "CP-2D": ("earnings_quality_metrics",),
    "CP-3": ("debt_classification", "capital_structure"),
    "CP-3C": ("debt_schedule", "maturity_profile"),
    "CP-4": ("covenant_metrics", "ebitda_definitions"),
    "CP-4A": ("covenant_compliance",),
    "CP-5": ("structured_data",),
    "CP-5A": ("full_data_set",),
}


class ConsumerRequest(Contract):
    entry: Identifier
    canonical_module: Identifier
    consumer_type: Literal["analytical", "infra"]
    requirements: tuple[Identifier, ...]
    policy: Literal["step_12", "consumer_specific_review"]


class DownstreamInputs(Contract):
    schema_version: Literal["downstream-inputs/1"] = "downstream-inputs/1"
    requested_consumers: tuple[Identifier, ...]
    consumers: tuple[ConsumerRequest, ...]
    narrative: NarrativeReport
    model: ModelReadinessReport
    financial_book: FinancialBook


class RequirementAssessment(Contract):
    requirement: Identifier
    status: Literal["sufficient", "limited", "missing"]
    evidence_ids: tuple[Identifier, ...]
    rationale: Prose
    actions: tuple[Prose, ...] = ()


class GapAssessment(Contract):
    gap_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    relevance: Literal["relevant", "not_relevant"]
    evidence_ids: tuple[Identifier, ...]
    rationale: Prose


class ConsumerAssessment(Contract):
    entry: Identifier
    requirements: tuple[RequirementAssessment, ...] = ()
    gaps: tuple[GapAssessment, ...] = ()


class DownstreamReview(Contract):
    schema_version: Literal["downstream-review/1"] = "downstream-review/1"
    inputs_sha256: Hash
    consumers: tuple[ConsumerAssessment, ...] = ()


class ConsumerRow(Contract):
    entry: Identifier
    canonical_module: Identifier
    consumer_type: Literal["analytical", "infra"]
    status: Literal["ready", "ready_with_limitations", "not_ready"]
    requirements: tuple[RequirementAssessment, ...]
    unassessed_requirements: tuple[Identifier, ...]
    gap_assessments: tuple[GapAssessment, ...]
    blocking_gap_ids: tuple[Identifier, ...]
    relevant_gap_ids: tuple[Identifier, ...]
    unassessed_gap_ids: tuple[Identifier, ...]
    actions: tuple[Text, ...]


class WorkbookRow(Contract):
    entry: Literal["CP-MODEL"] = "CP-MODEL"
    status: Literal["ready", "partial", "blocked", "not_applicable"]
    scope: Literal["selected_historical_quarters"] = "selected_historical_quarters"
    blocking_gap_ids: tuple[Identifier, ...]
    missing_metric_ids: tuple[Text, ...]
    conflict_refs: tuple[Identifier, ...]
    actions: tuple[Text, ...]


class DownstreamReport(Contract):
    schema_version: Literal["downstream-readiness/1"] = "downstream-readiness/1"
    inputs: DownstreamInputs
    review: DownstreamReview
    consumers: tuple[ConsumerRow, ...]
    model: WorkbookRow
    analytical_qualification: Literal["unrun"] = "unrun"
    limitations: tuple[Text, ...]


def _requests(entries: tuple[str, ...]) -> tuple[ConsumerRequest, ...]:
    if len(entries) != len(set(entries)):
        raise ValueError("Duplicate requested downstream entry")
    result = []
    for entry in entries:
        module = canonical(entry)
        if module in {"CP-0", "CP-1"}:
            raise ValueError("CP-0 and CP-1 are not downstream consumers of CP-1")
        if module == "CP-MODEL":
            continue
        dependencies = _DEPENDENCIES.get(entry, _DEPENDENCIES.get(module))
        result.append(
            ConsumerRequest(
                entry=entry,
                canonical_module=module,
                consumer_type="infra" if module in {"CP-5", "CP-8", "CP-OS"} else "analytical",
                requirements=dependencies or ("consumer_specific_cp1_sufficiency",),
                policy="step_12" if dependencies else "consumer_specific_review",
            )
        )
    return tuple(result)


def downstream_inputs(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
    narrative: NarrativeReview,
    requested_consumers: tuple[str, ...],
    *,
    quarter_ids: tuple[str, ...] | None = None,
) -> DownstreamInputs:
    financial = FinancialReview.model_validate_json(financial.model_dump_json())
    consumers = _requests(requested_consumers)
    report = canonical_narrative(pack, context, financial, definition, binding, narrative)
    return DownstreamInputs(
        requested_consumers=requested_consumers,
        consumers=consumers,
        narrative=report,
        financial_book=next(b for b in financial.books if b.book_id == definition.book_id),
        model=assess_model_readiness(pack, financial, definition.book_id, quarter_ids=quarter_ids),
    )


_EVIDENCE_GROUPS: dict[str, tuple[frozenset[str], ...]] = {
    "normalized_financials": tuple(frozenset({"statement_" + s}) for s in ("IS", "CFS", "BS")),
    "entity_scope": (frozenset({"entity"}),),
    "period_coverage": (frozenset({"source_period", "construction"}),),
    "kpi_dashboard": (frozenset({"kpi"}),),
    "calculation_register": (frozenset({"computation"}),),
    "fcf_build": (frozenset({"kpi:fcf"}), frozenset({"computation"})),
    "cash_flow_metrics": (frozenset({"kpi:fcf", "kpi:ffo", "kpi:cfo_adjusted"}),),
    "liquidity_data": (frozenset({"kpi:liquidity", "kpi:undrawn_rcf", "kpi:cash_closing"}),),
    "earnings_quality_metrics": (frozenset({"kpi:ebitda", "kpi:adjusted_ebitda"}),),
    "debt_classification": (frozenset({"observation:facilities"}),),
    "capital_structure": (frozenset({"observation:facilities", "statement_BS"}),),
    "debt_schedule": (frozenset({"observation:facilities"}),),
    "maturity_profile": (frozenset({"observation:facilities"}),),
    "covenant_metrics": (frozenset({"kpi"}),),
    "ebitda_definitions": (frozenset({"definition"}),),
    "covenant_compliance": (frozenset({"kpi"}), frozenset({"definition"})),
}


def _evidence_tags(record: EvidenceRecord) -> set[str]:
    """Only compatible, available numeric evidence can support sufficient inputs."""
    data = json.loads(record.record_json)
    if (
        (record.kind == "kpi" and data["value"]["amount"] is None)
        or (record.kind.startswith("statement_") and data["normalized_amount"] is None)
        or (record.kind == "observation" and data["observation"]["amount"] is None)
    ):
        return set()
    tags = {record.kind}
    if record.kind == "kpi":
        tags.add("kpi:" + data["key"])
    if record.kind == "observation":
        tags.add("observation:" + data["register_id"])
    return tags


def validate_downstream_review(
    inputs: DownstreamInputs, review: DownstreamReview
) -> tuple[str, ...]:
    """Validate a review against supplied inputs; external assembly authenticates inputs."""
    try:
        inputs = DownstreamInputs.model_validate_json(inputs.model_dump_json())
        review = DownstreamReview.model_validate_json(review.model_dump_json())
        if inputs.consumers != _requests(inputs.requested_consumers):
            return ("Consumer requirements differ from the requested entries",)
    except ValueError as error:
        return (f"Invalid downstream contract: {error}",)
    prior_issues = validate_narrative_review(inputs.narrative.inputs, inputs.narrative.review)
    if prior_issues:
        return tuple("Invalid prior narrative: " + issue for issue in prior_issues)
    issues = []
    if review.inputs_sha256 != inputs.content_hash():
        issues.append("Downstream review does not bind current inputs")
    requests = {r.entry: r for r in inputs.consumers}
    evidence = {r.evidence_id: r for r in inputs.narrative.inputs.catalogue}
    gaps = {g.gap_id: g for g in inputs.narrative.gaps}
    evidence_tags: dict[str, set[str]] = {}
    if len(review.consumers) != len({c.entry for c in review.consumers}):
        issues.append("Duplicate consumer assessment")
    for consumer in review.consumers:
        request = requests.get(consumer.entry)
        if request is None:
            issues.append(f"Unrequested consumer assessment: {consumer.entry}")
            continue
        expected = set(request.requirements)
        assessed = set()
        for requirement in consumer.requirements:
            key = requirement.requirement
            if key in assessed or key not in expected:
                issues.append(f"Duplicate or unknown requirement: {consumer.entry} {key}")
            assessed.add(key)
            ids = requirement.evidence_ids
            unique_ids = set(ids)
            if len(ids) != len(unique_ids) or not unique_ids <= evidence.keys():
                issues.append(f"Invalid requirement evidence: {consumer.entry} {key}")
            if requirement.status != "missing" and not ids:
                issues.append(f"Sufficiency requires prior evidence: {consumer.entry} {key}")
            if requirement.status != "missing":
                tags: set[str] = set()
                for evidence_id in ids:
                    if evidence_id in evidence:
                        if evidence_id not in evidence_tags:
                            evidence_tags[evidence_id] = _evidence_tags(evidence[evidence_id])
                        tags.update(evidence_tags[evidence_id])
                groups = _EVIDENCE_GROUPS.get(key)
                if groups and any(tags.isdisjoint(group) for group in groups):
                    issues.append(
                        f"Incompatible or unavailable dependency evidence: {consumer.entry} {key}"
                    )
                if not groups and not (tags - {"gap"}):
                    issues.append(f"Sufficiency requires register evidence: {consumer.entry} {key}")
            if key == "kpi_dashboard" and requirement.status == "sufficient":
                dashboard = inputs.narrative.inputs.ledger.kpis
                if (
                    dashboard is None
                    or not dashboard.kpis
                    or any(kpi.value.amount is None for kpi in dashboard.kpis)
                ):
                    issues.append(
                        f"Complete KPI dashboard has unavailable values: {consumer.entry}"
                    )
            if requirement.status != "sufficient" and not requirement.actions:
                issues.append(f"Incomplete requirement needs action: {consumer.entry} {key}")
        scoped: set[str] = set()
        for scope in consumer.gaps:
            gap_ids = set(scope.gap_ids)
            if len(gap_ids) != len(scope.gap_ids) or not gap_ids <= gaps.keys() or gap_ids & scoped:
                issues.append(f"Duplicate or unknown gap scope: {consumer.entry}")
            scoped.update(gap_ids)
            refs = scope.evidence_ids
            unique_refs = set(refs)
            if len(refs) != len(unique_refs) or not unique_refs <= evidence.keys():
                issues.append(f"Invalid gap-scope evidence: {consumer.entry}")
            if scope.relevance == "not_relevant":
                if not refs:
                    issues.append(f"Excluding gaps requires prior evidence: {consumer.entry}")
                if any(
                    gaps[i].severity == "BLOCK" and gaps[i].origin in {"context_binding", "context"}
                    for i in gap_ids
                    if i in gaps
                ):
                    issues.append(f"A source-integrity block cannot be excluded: {consumer.entry}")
    return tuple(issues)


def _assess_consumers(
    inputs: DownstreamInputs, review: DownstreamReview
) -> tuple[ConsumerRow, ...]:
    """Derive statuses without dropping any inherited gap or unreviewed dependency."""
    assessments = {c.entry: c for c in review.consumers}
    gaps = inputs.narrative.gaps
    result = []
    for request in inputs.consumers:
        assessment = assessments.get(request.entry, ConsumerAssessment(entry=request.entry))
        requirements = {r.requirement: r for r in assessment.requirements}
        missing = tuple(r for r in request.requirements if r not in requirements)
        relevance = {i: s.relevance for s in assessment.gaps for i in s.gap_ids}
        blocking = tuple(
            g.gap_id
            for g in gaps
            if g.severity == "BLOCK"
            and (
                relevance.get(g.gap_id) != "not_relevant"
                or g.origin in {"context_binding", "context"}
            )
        )
        unassessed = tuple(g.gap_id for g in gaps if g.gap_id not in relevance)
        relevant = tuple(g.gap_id for g in gaps if relevance.get(g.gap_id) == "relevant")
        incomplete = any(r.status == "missing" for r in requirements.values())
        limited = any(r.status == "limited" for r in requirements.values())
        actions = [action for r in assessment.requirements for action in r.actions]
        actions.extend("Assess required CP-1 dependency: " + key for key in missing)
        if unassessed:
            actions.append("Assess all retained gaps for this consumer")
        actionable = set(relevant)
        actionable.update(blocking)
        actions.extend(g.recommended_action for g in gaps if g.gap_id in actionable)
        result.append(
            ConsumerRow(
                entry=request.entry,
                canonical_module=request.canonical_module,
                consumer_type=request.consumer_type,
                status="not_ready"
                if blocking or missing or unassessed or incomplete
                else "ready_with_limitations"
                if limited or relevant
                else "ready",
                requirements=tuple(
                    requirements[k] for k in request.requirements if k in requirements
                ),
                unassessed_requirements=missing,
                gap_assessments=assessment.gaps,
                blocking_gap_ids=blocking,
                relevant_gap_ids=relevant,
                unassessed_gap_ids=unassessed,
                actions=tuple(dict.fromkeys(actions)),
            )
        )
    return tuple(result)


def canonical_downstream_readiness(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
    narrative: NarrativeReview,
    requested_consumers: tuple[str, ...],
    review: DownstreamReview,
    *,
    quarter_ids: tuple[str, ...] | None = None,
) -> DownstreamReport:
    inputs = downstream_inputs(
        pack,
        context,
        financial,
        definition,
        binding,
        narrative,
        requested_consumers,
        quarter_ids=quarter_ids,
    )
    issues = validate_downstream_review(inputs, review)
    if issues:
        raise ValueError("; ".join(issues))
    review = DownstreamReview.model_validate_json(review.model_dump_json())
    # The workbook has its own deterministic gate, not a model-authored verdict.
    # Narrative omissions do not alter historical register completeness.
    blockers = tuple(
        g.gap_id
        for g in inputs.narrative.gaps
        if g.severity == "BLOCK" and g.origin in {"context_binding", "context"}
    )
    model = inputs.model.readiness
    status: Literal["ready", "partial", "blocked", "not_applicable"] = "blocked"
    if not blockers and model.status == "ready":
        status = "ready"
    elif (
        not blockers
        and inputs.model.period_reconciliation is not None
        and all(
            f.severity != "BLOCK" or f.code in {"quarter_count", "missing_input", "tax_inputs"}
            for f in model.findings
        )
    ):
        status = "partial"
    return DownstreamReport(
        inputs=inputs,
        review=review,
        consumers=_assess_consumers(inputs, review),
        model=WorkbookRow(
            status=status,
            blocking_gap_ids=blockers,
            missing_metric_ids=model.missing_metric_ids,
            conflict_refs=model.conflict_refs,
            actions=tuple(
                dict.fromkeys(
                    (
                        *(f.explanation for f in model.findings),
                        *(
                            g.recommended_action
                            for g in inputs.narrative.gaps
                            if g.gap_id in blockers
                        ),
                    )
                )
            ),
        ),
        limitations=(
            "Readiness concerns CP-1 input sufficiency, not completion of downstream Modules",
            "Sufficiency and warning relevance are evidence-bound analytical judgments; "
            "semantic qualification remains unrun",
            "Relevant BLOCK gaps prevent readiness; warning or gap exclusions require "
            "an explicit evidence-bound scope judgment and never delete the original gap",
            "The CP-MODEL row assesses selected historical quarters only; it does not "
            "qualify forecasts, pro forma or workbook delivery",
            "Consumers absent from Step 12 require explicit consumer-specific assessment",
        ),
    )


def validate_downstream_report(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    definition: DefinitionReview,
    binding: FinancialContextBinding,
    narrative: NarrativeReview,
    requested_consumers: tuple[str, ...],
    review: DownstreamReview,
    report: DownstreamReport,
    *,
    quarter_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    try:
        report = DownstreamReport.model_validate_json(report.model_dump_json())
        expected = canonical_downstream_readiness(
            pack,
            context,
            financial,
            definition,
            binding,
            narrative,
            requested_consumers,
            review,
            quarter_ids=quarter_ids,
        )
    except ValueError as error:
        return (f"Invalid downstream readiness: {error}",)
    return (
        () if report == expected else ("Downstream readiness differs from external recomputation",)
    )
