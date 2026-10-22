"""Hash-bound QA judgments and exact r14 confidence arithmetic.

Producer-owned inputs define coverage, source gate, inherited findings and each
evidence ID's lineage ceiling (MC-5). Analysts classify materiality, keep or lower
lineage within that ceiling and add findings; they never supply a score.
"""

from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from deploy_vii.contracts import Contract, Hash, Identifier, Text

Lineage = Literal[
    "Directly Sourced",
    "Calculated",
    "Assumption-Based",
    "Analyst Inference",
    "Weak Lineage",
    "Untraced",
    "Conflicting",
    "Insufficient Information",
]
Severity = Literal["CRITICAL", "MATERIAL", "MINOR"]
QaStatus = Literal["Passed", "Restricted", "Blocked"]
Band = Literal["High", "Medium", "Low", "Insufficient Information"]
SourceGate = Literal["pass", "partial", "fail"]
ModuleStatus = Literal["complete", "restricted", "blocked"]
WEIGHTS: dict[Lineage, int] = {
    "Directly Sourced": 10,
    "Calculated": 9,
    "Assumption-Based": 5,
    "Analyst Inference": 4,
    "Weak Lineage": 3,
    "Untraced": 0,
    "Conflicting": 0,
    "Insufficient Information": 0,
}
PENALTIES: dict[Severity, int] = {"CRITICAL": 40, "MATERIAL": 15, "MINOR": 3}
# MC-5: the register that produced an evidence ID fixes its highest lineage class.
LineageBasis = Literal["citation", "calculation", "estimate", "gap", "missing", "coverage"]
CEILINGS: dict[LineageBasis, Lineage] = {
    "citation": "Directly Sourced",
    "calculation": "Calculated",
    "estimate": "Assumption-Based",
    "gap": "Insufficient Information",
    "missing": "Insufficient Information",
    "coverage": "Insufficient Information",
}


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("QA explanations must be nonblank")
    return value


Explanation = Annotated[Text, AfterValidator(_nonblank)]


class ClaimCandidate(Contract):
    claim_id: Identifier
    evidence_ids: tuple[Identifier, ...]


class CoverageField(Contract):
    field_id: Identifier
    present: bool
    rationale: Explanation


class QaFinding(Contract):
    finding_id: Identifier
    severity: Severity
    status: Literal["open", "resolved", "closed", "cleared"] = "open"
    description: Explanation
    references: tuple[Identifier, ...] = ()
    resolution: Explanation | None = None

    @model_validator(mode="after")
    def explained_resolution(self) -> Self:
        if self.status != "open" and not self.resolution:
            raise ValueError("A resolved QA finding requires its resolution")
        if len(self.references) != len(set(self.references)):
            raise ValueError("Duplicate QA reference")
        return self


class EvidenceCeiling(Contract):
    """Producer-derived maximum lineage class; the analyst may keep or lower it."""

    evidence_id: Identifier
    ceiling: Lineage
    basis: LineageBasis

    @model_validator(mode="after")
    def ceiling_follows_basis(self) -> Self:
        if self.ceiling != CEILINGS[self.basis]:
            raise ValueError(f"QA lineage ceiling does not follow its basis: {self.evidence_id}")
        return self

    @classmethod
    def of(cls, evidence_id: str, basis: LineageBasis) -> Self:
        return cls(evidence_id=evidence_id, ceiling=CEILINGS[basis], basis=basis)


class QualityInputs(Contract):
    schema_version: Literal["quality-inputs/2"] = "quality-inputs/2"
    artifact_sha256: Hash
    coverage_policy: Explanation
    claims: tuple[ClaimCandidate, ...]
    coverage: Annotated[tuple[CoverageField, ...], Field(min_length=1)]
    source_gate: SourceGate
    module_status: ModuleStatus
    references: tuple[Identifier, ...]
    ceilings: tuple[EvidenceCeiling, ...]
    inherited_findings: tuple[QaFinding, ...] = ()

    @model_validator(mode="after")
    def distinct_scope(self) -> Self:
        for ids in (
            tuple(c.claim_id for c in self.claims),
            tuple(c.field_id for c in self.coverage),
            self.references,
            tuple(f.finding_id for f in self.inherited_findings),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate QA input identity")
        bounded = [c.evidence_id for c in self.ceilings]
        if len(bounded) != len(set(bounded)) or set(bounded) != set(self.references):
            raise ValueError("QA lineage ceilings must cover every reference exactly once")
        for claim in self.claims:
            if len(claim.evidence_ids) != len(set(claim.evidence_ids)):
                raise ValueError("Duplicate claim evidence")
            if not set(claim.evidence_ids) <= set(self.references):
                raise ValueError("Claim evidence is outside the QA input scope")
        if any(not set(f.references) <= set(self.references) for f in self.inherited_findings):
            raise ValueError("Inherited finding references unknown input")
        return self


class EvidenceLineage(Contract):
    evidence_id: Identifier
    lineage_class: Lineage
    rationale: Explanation


class ClaimAssessment(Contract):
    claim_id: Identifier
    material: bool
    evidence: tuple[EvidenceLineage, ...]
    rationale: Explanation


class QualityReview(Contract):
    schema_version: Literal["quality-review/1"] = "quality-review/1"
    inputs_sha256: Hash
    claims: tuple[ClaimAssessment, ...]
    findings: tuple[QaFinding, ...] = ()


class Ratio(Contract):
    numerator: int
    denominator: int = Field(gt=0)

    @classmethod
    def exact(cls, value: Fraction) -> Self:
        return cls(numerator=value.numerator, denominator=value.denominator)


class Confidence(Contract):
    schema_version: Literal["confidence/1"] = "confidence/1"
    evidence_quality: Ratio
    coverage: Ratio
    source_multiplier: Ratio
    penalty: int = Field(ge=0)
    raw_score: Ratio
    material_claims: int = Field(ge=0)
    fields_present: int = Field(ge=0)
    fields_total: int = Field(gt=0)
    confidence_score: int = Field(ge=0, le=100)
    confidence_band: Band
    qa_status: QaStatus
    rounding: Literal["nearest_integer_ties_to_even"] = "nearest_integer_ties_to_even"


class QualityReport(Contract):
    schema_version: Literal["quality-report/1"] = "quality-report/1"
    inputs_sha256: Hash
    review_sha256: Hash
    confidence: Confidence
    findings: tuple[QaFinding, ...]
    analytical_qualification: Literal["unrun"] = "unrun"
    limitations: tuple[Text, ...]


def _compute_confidence(
    inputs: QualityInputs, review: QualityReview, findings: tuple[QaFinding, ...]
) -> Confidence:
    """Exact arithmetic over caller-validated inputs; no classification or acceptance."""
    strongest = [
        max((WEIGHTS[e.lineage_class] for e in c.evidence), default=0)
        for c in review.claims
        if c.material
    ]
    evidence = Fraction(sum(strongest) * 10, len(strongest)) if strongest else Fraction(0)
    present, total = sum(f.present for f in inputs.coverage), len(inputs.coverage)
    coverage = Fraction(present * 100, total)
    multiplier = {"pass": Fraction(1), "partial": Fraction(7, 10), "fail": Fraction(0)}[
        inputs.source_gate
    ]
    open_severities = [f.severity for f in findings if f.status == "open"]
    penalty = sum(PENALTIES[s] for s in open_severities)
    raw = (Fraction(3, 5) * evidence + Fraction(2, 5) * coverage) * multiplier - penalty
    score = max(Fraction(0), min(Fraction(100), raw))
    status: QaStatus
    if (
        "CRITICAL" in open_severities
        or inputs.module_status == "blocked"
        or inputs.source_gate == "fail"
    ):
        score, status = min(score, Fraction(39)), "Blocked"
    elif (
        "MATERIAL" in open_severities
        or inputs.module_status == "restricted"
        or inputs.source_gate == "partial"
    ):
        score, status = min(score, Fraction(59)), "Restricted"
    else:
        status = "Passed"
    rounded = round(score)
    band: Band = (
        "High"
        if rounded >= 80
        else "Medium"
        if rounded >= 60
        else "Low"
        if rounded >= 40
        else "Insufficient Information"
    )
    return Confidence(
        evidence_quality=Ratio.exact(evidence),
        coverage=Ratio.exact(coverage),
        source_multiplier=Ratio.exact(multiplier),
        penalty=penalty,
        raw_score=Ratio.exact(raw),
        material_claims=len(strongest),
        fields_present=present,
        fields_total=total,
        confidence_score=rounded,
        confidence_band=band,
        qa_status=status,
    )


def validate_quality_review(inputs: QualityInputs, review: QualityReview) -> tuple[str, ...]:
    try:
        inputs = QualityInputs.model_validate_json(inputs.model_dump_json())
        review = QualityReview.model_validate_json(review.model_dump_json())
    except ValueError as error:
        return (f"Invalid QA contract: {error}",)
    issues = []
    if review.inputs_sha256 != inputs.content_hash():
        issues.append("QA review does not bind current inputs")
    candidates = {c.claim_id: c for c in inputs.claims}
    ceilings = {c.evidence_id: c.ceiling for c in inputs.ceilings}
    supplied = [c.claim_id for c in review.claims]
    if len(supplied) != len(set(supplied)) or set(supplied) != set(candidates):
        issues.append("QA review must assess every candidate claim exactly once")
    for claim in review.claims:
        candidate = candidates.get(claim.claim_id)
        ids = [e.evidence_id for e in claim.evidence]
        if candidate and (len(ids) != len(set(ids)) or set(ids) != set(candidate.evidence_ids)):
            issues.append(
                f"QA lineage must assess every bound evidence reference: {claim.claim_id}"
            )
        for e in claim.evidence:
            # Evidence outside the input scope has no ceiling and is already an issue above.
            ceiling = ceilings.get(e.evidence_id)
            if ceiling is not None and WEIGHTS[e.lineage_class] > WEIGHTS[ceiling]:
                issues.append(
                    f"QA lineage upgrade rejected: {e.evidence_id} {e.lineage_class} "
                    f"above ceiling {ceiling}"
                )
    inherited = {f.finding_id for f in inputs.inherited_findings}
    ids = [f.finding_id for f in review.findings]
    if len(ids) != len(set(ids)) or set(ids) & inherited:
        issues.append("QA review cannot duplicate findings or replace inherited findings")
    if any(not set(f.references) <= set(inputs.references) for f in review.findings):
        issues.append("QA finding references unknown input")
    return tuple(issues)


def assess_quality(inputs: QualityInputs, review: QualityReview) -> QualityReport:
    """Validate against producer-owned inputs, preserving all inherited findings."""
    issues = validate_quality_review(inputs, review)
    if issues:
        raise ValueError("; ".join(issues))
    inputs = QualityInputs.model_validate_json(inputs.model_dump_json())
    review = QualityReview.model_validate_json(review.model_dump_json())
    findings = (*inputs.inherited_findings, *review.findings)
    return QualityReport(
        inputs_sha256=inputs.content_hash(),
        review_sha256=review.content_hash(),
        confidence=_compute_confidence(inputs, review, findings),
        findings=findings,
        limitations=(
            "The producer owns required-field inventory, source gate, inherited findings and "
            "lineage ceilings. Input shape validation does not authenticate an arbitrary report.",
            "Materiality, lineage within its ceiling, severity and resolution are supplied "
            "judgments requiring semantic review; deterministic score arithmetic does not "
            "qualify those judgments.",
            "Passed QA is distinct from committee readiness, Module acceptance, "
            "analytical qualification and native-host qualification.",
        ),
    )


def validate_quality_report(
    inputs: QualityInputs, review: QualityReview, report: QualityReport
) -> tuple[str, ...]:
    try:
        report = QualityReport.model_validate_json(report.model_dump_json())
        expected = assess_quality(inputs, review)
    except ValueError as error:
        return (f"Invalid QA report: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("QA report differs from trusted recomputation",)
    )
