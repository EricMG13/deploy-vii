"""r14 arithmetic and QA binding, independent of analytical qualification."""

from collections.abc import Sequence
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
from typing import Any, get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.quality import (
    ClaimAssessment,
    ClaimCandidate,
    CoverageField,
    EvidenceLineage,
    Lineage,
    QaFinding,
    QualityInputs,
    QualityReport,
    QualityReview,
    Ratio,
    assess_quality,
    validate_quality_report,
    validate_quality_review,
)


def fixture(*, present: int = 19, total: int = 20) -> tuple[QualityInputs, QualityReview]:
    classes = ["Directly Sourced"] * 8 + ["Calculated"] * 2 + ["Assumption-Based"] * 2
    inputs = QualityInputs(
        artifact_sha256="a" * 64,
        coverage_policy="synthetic-required-fields/1",
        claims=tuple(ClaimCandidate(claim_id=f"c{i}", evidence_ids=(f"e{i}",)) for i in range(12)),
        coverage=tuple(
            CoverageField(
                field_id=f"f{i}", present=i < present, rationale="Synthetic required slot"
            )
            for i in range(total)
        ),
        source_gate="pass",
        module_status="complete",
        references=tuple(f"e{i}" for i in range(12)),
    )
    review = QualityReview(
        inputs_sha256=inputs.content_hash(),
        claims=tuple(
            ClaimAssessment.model_validate(
                {
                    "claim_id": f"c{i}",
                    "material": True,
                    "rationale": "Synthetic material claim",
                    "evidence": (
                        EvidenceLineage.model_validate(
                            {
                                "evidence_id": f"e{i}",
                                "lineage_class": cls,
                                "rationale": "Synthetic classification",
                            }
                        ),
                    ),
                }
            )
            for i, cls in enumerate(classes)
        ),
        findings=(QaFinding(finding_id="minor", severity="MINOR", description="Worked example"),),
    )
    return inputs, review


def bind(inputs: QualityInputs, review: QualityReview) -> QualityReview:
    return review.model_copy(update={"inputs_sha256": inputs.content_hash()})


def fraction(value: Ratio) -> Fraction:
    return Fraction(value.numerator, value.denominator)


def test_pinned_worked_example_and_external_recomputation() -> None:
    inputs, review = fixture()
    report = assess_quality(inputs, review)
    score = report.confidence
    assert fraction(score.evidence_quality) == 90 and fraction(score.coverage) == 95
    assert fraction(score.source_multiplier) == 1 and score.penalty == 3
    assert fraction(score.raw_score) == 89
    assert (score.confidence_score, score.confidence_band, score.qa_status) == (
        89,
        "High",
        "Passed",
    )
    assert score.material_claims == 12 and report.findings == review.findings
    assert report.analytical_qualification == "unrun"
    assert validate_quality_report(inputs, review, report) == ()
    changed = report.model_copy(
        update={"confidence": score.model_copy(update={"confidence_score": 100})}
    )
    assert validate_quality_report(inputs, review, changed)
    other = review.model_copy(update={"findings": ()})
    assert validate_quality_report(inputs, review, assess_quality(inputs, other))


@pytest.mark.parametrize(
    "severity,cap,status",
    [("CRITICAL", 39, "Blocked"), ("MATERIAL", 59, "Restricted"), ("MINOR", 100, "Passed")],
)
def test_open_findings_apply_penalties_then_caps(severity: str, cap: int, status: str) -> None:
    inputs, review = fixture(present=20)
    finding = QaFinding.model_validate(
        {"finding_id": "review", "severity": severity, "description": "Synthetic issue"}
    )
    score = assess_quality(inputs, review.model_copy(update={"findings": (finding,)})).confidence
    assert score.confidence_score <= cap and score.qa_status == status
    assert score.penalty == {"CRITICAL": 40, "MATERIAL": 15, "MINOR": 3}[severity]


@pytest.mark.parametrize("state", ["resolved", "closed", "cleared"])
def test_resolved_findings_remain_visible_without_open_penalty_or_cap(state: str) -> None:
    inputs, review = fixture()
    finding = QaFinding.model_validate(
        {
            "finding_id": "fixed",
            "severity": "CRITICAL",
            "status": state,
            "description": "Retained historical issue",
            "resolution": "Bound evidence was corrected",
            "references": ("e0",),
        }
    )
    report = assess_quality(inputs, review.model_copy(update={"findings": (finding,)}))
    assert report.confidence.penalty == 0 and report.confidence.qa_status == "Passed"
    assert report.findings == (finding,)
    with pytest.raises(ValueError):
        QaFinding.model_validate_json(
            finding.model_copy(update={"resolution": None}).model_dump_json()
        )


@pytest.mark.parametrize(
    "gate,run,cap,status",
    [
        ("fail", "complete", 39, "Blocked"),
        ("pass", "blocked", 39, "Blocked"),
        ("partial", "complete", 59, "Restricted"),
        ("pass", "restricted", 59, "Restricted"),
    ],
)
def test_source_and_module_status_cannot_be_promoted_by_clean_review(
    gate: str, run: str, cap: int, status: str
) -> None:
    inputs, review = fixture()
    inputs = QualityInputs.model_validate_json(
        inputs.model_copy(update={"source_gate": gate, "module_status": run}).model_dump_json()
    )
    score = assess_quality(
        inputs, bind(inputs, review.model_copy(update={"findings": ()}))
    ).confidence
    assert score.confidence_score <= cap and score.qa_status == status
    if gate == "fail":
        assert score.confidence_score == 0


def test_each_material_claim_uses_strongest_evidence_once() -> None:
    inputs, review = fixture()
    inputs = inputs.model_copy(
        update={"claims": (ClaimCandidate(claim_id="claim", evidence_ids=("e0", "e1")),)}
    )
    review = QualityReview(
        inputs_sha256=inputs.content_hash(),
        claims=(
            ClaimAssessment(
                claim_id="claim",
                material=True,
                rationale="Material",
                evidence=(
                    EvidenceLineage(
                        evidence_id="e0", lineage_class="Calculated", rationale="Arithmetic"
                    ),
                    EvidenceLineage(
                        evidence_id="e1", lineage_class="Directly Sourced", rationale="Source"
                    ),
                ),
            ),
        ),
    )
    score = assess_quality(inputs, review).confidence
    assert fraction(score.evidence_quality) == 100 and score.material_claims == 1


@pytest.mark.parametrize("present,expected", [(1, 2), (3, 8), (15, 38)])
def test_exact_half_even_rounding_and_empty_material_population(
    present: int, expected: int
) -> None:
    inputs, review = fixture(present=present, total=16)
    inputs = inputs.model_copy(update={"claims": ()})
    review = QualityReview(inputs_sha256=inputs.content_hash(), claims=())
    with localcontext() as ctx:
        ctx.prec = 1
        ctx.traps[Inexact] = True
        score = assess_quality(inputs, review).confidence
    assert score.confidence_score == expected and score.material_claims == 0
    assert fraction(score.evidence_quality) == 0


def test_inherited_finding_cannot_be_removed_replaced_or_cleared_by_review() -> None:
    inputs, review = fixture()
    inherited = QaFinding(
        finding_id="producer-critical",
        severity="CRITICAL",
        description="Machine finding",
        references=("e0",),
    )
    inputs = inputs.model_copy(update={"inherited_findings": (inherited,)})
    review = bind(inputs, review)
    report = assess_quality(inputs, review)
    assert report.findings[0] == inherited and report.confidence.qa_status == "Blocked"
    closed = inherited.model_copy(update={"status": "resolved", "resolution": "Claimed fixed"})
    assert validate_quality_review(inputs, review.model_copy(update={"findings": (closed,)}))


@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "missing_claim",
        "duplicate_claim",
        "missing_evidence",
        "unknown_evidence",
        "duplicate_evidence",
        "unknown_finding_ref",
        "duplicate_finding",
    ],
)
def test_malformed_or_substituted_review_fails_closed(change: str) -> None:
    inputs, review = fixture()
    claims = review.claims
    if change == "hash":
        review = review.model_copy(update={"inputs_sha256": "0" * 64})
    elif change == "missing_claim":
        review = review.model_copy(update={"claims": claims[1:]})
    elif change == "duplicate_claim":
        review = review.model_copy(update={"claims": (*claims, claims[0])})
    elif "evidence" in change:
        evidence = (
            ()
            if change == "missing_evidence"
            else (claims[0].evidence[0].model_copy(update={"evidence_id": "unknown"}),)
            if change == "unknown_evidence"
            else claims[0].evidence * 2
        )
        review = review.model_copy(
            update={"claims": (claims[0].model_copy(update={"evidence": evidence}), *claims[1:])}
        )
    elif change == "unknown_finding_ref":
        review = review.model_copy(
            update={
                "findings": (review.findings[0].model_copy(update={"references": ("unknown",)}),)
            }
        )
    else:
        review = review.model_copy(update={"findings": review.findings * 2})
    assert validate_quality_review(inputs, review)
    with pytest.raises(ValueError):
        assess_quality(inputs, review)


def test_copied_invalid_inputs_and_old_versions_are_revalidated() -> None:
    inputs, review = fixture()
    for changed in (
        inputs.model_copy(update={"coverage": ()}),
        inputs.model_copy(update={"coverage": inputs.coverage * 2}),
        inputs.model_copy(update={"references": inputs.references * 2}),
        inputs.model_copy(update={"schema_version": "old"}),
    ):
        assert validate_quality_review(changed, bind(changed, review))
    report = assess_quality(inputs, review)
    assert validate_quality_report(inputs, review, report.model_copy(update={"findings": ()}))
    with pytest.raises(ValueError):
        QualityReport.model_validate_json(
            report.model_copy(update={"schema_version": "old"}).model_dump_json()
        )


@given(st.integers(1, 40), st.integers(0, 40), st.integers(0, 8))
def test_penalties_never_increase_score(total: int, raw_present: int, count: int) -> None:
    inputs, review = fixture(total=total, present=min(total, raw_present))
    review = review.model_copy(update={"findings": ()})
    before = assess_quality(inputs, review).confidence
    findings = tuple(
        QaFinding(finding_id=f"minor{i}", severity="MINOR", description="Synthetic")
        for i in range(count)
    )
    after = assess_quality(inputs, review.model_copy(update={"findings": findings})).confidence
    assert 0 <= after.confidence_score <= before.confidence_score <= 100
    assert fraction(after.raw_score) == fraction(before.raw_score) - count * 3


def build(**changes: object) -> dict[str, Any]:
    """Valid raw QualityInputs fields; tests alter one field to reach a single validator branch."""
    base: dict[str, Any] = {
        "artifact_sha256": "a" * 64,
        "coverage_policy": "synthetic-required-fields/1",
        "claims": (ClaimCandidate(claim_id="c", evidence_ids=("e",)),),
        "coverage": (CoverageField(field_id="f", present=True, rationale="Synthetic slot"),),
        "source_gate": "pass",
        "module_status": "complete",
        "references": ("e", "f"),
    }
    return base | changes


def test_valid_raw_scope_is_the_baseline_for_each_rejection() -> None:
    assert QualityInputs.model_validate(build()).claims[0].claim_id == "c"


@pytest.mark.parametrize("text", ["", " ", "\n\t "])
def test_blank_explanations_are_rejected_everywhere(text: str) -> None:
    with pytest.raises(ValueError):
        CoverageField(field_id="f", present=True, rationale=text)
    with pytest.raises(ValueError):
        QaFinding(finding_id="x", severity="MINOR", description=text)
    with pytest.raises(ValueError, match="QA explanations must be nonblank"):
        QualityInputs.model_validate(build(coverage_policy=text if text else " "))
    with pytest.raises(ValueError, match="QA explanations must be nonblank"):
        QaFinding.model_validate(
            {
                "finding_id": "x",
                "severity": "MINOR",
                "status": "resolved",
                "description": "Real issue",
                "resolution": " ",
            }
        )


@pytest.mark.parametrize("status", ["resolved", "closed", "cleared"])
def test_a_non_open_finding_requires_a_resolution(status: str) -> None:
    with pytest.raises(ValueError, match="requires its resolution"):
        QaFinding.model_validate(
            {"finding_id": "x", "severity": "CRITICAL", "status": status, "description": "Issue"}
        )
    assert QaFinding(finding_id="x", severity="CRITICAL", description="Issue").status == "open"


def test_duplicate_finding_references_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate QA reference"):
        QaFinding(finding_id="x", severity="MINOR", description="Issue", references=("e", "e"))


def _claims(*ids: str) -> tuple[ClaimCandidate, ...]:
    return tuple(ClaimCandidate(claim_id=i, evidence_ids=("e",)) for i in ids)


def _coverage(*ids: str) -> tuple[CoverageField, ...]:
    return tuple(CoverageField(field_id=i, present=True, rationale="Slot") for i in ids)


@pytest.mark.parametrize(
    "changes",
    [
        {"claims": _claims("c", "c")},
        {"coverage": _coverage("f", "f")},
        {"references": ("e", "e", "f")},
        {
            "inherited_findings": (
                QaFinding(finding_id="i", severity="MINOR", description="One"),
                QaFinding(finding_id="i", severity="MINOR", description="Two"),
            )
        },
    ],
    ids=["claims", "coverage", "references", "inherited"],
)
def test_each_duplicate_scope_identity_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="Duplicate QA input identity"):
        QualityInputs.model_validate(build(**changes))


def test_claim_evidence_must_be_unique_and_inside_the_declared_scope() -> None:
    duplicate = (ClaimCandidate(claim_id="c", evidence_ids=("e", "e")),)
    with pytest.raises(ValueError, match="Duplicate claim evidence"):
        QualityInputs.model_validate(build(claims=duplicate))
    outside = (ClaimCandidate(claim_id="c", evidence_ids=("e", "outside")),)
    with pytest.raises(ValueError, match="outside the QA input scope"):
        QualityInputs.model_validate(build(claims=outside))


def test_inherited_findings_must_reference_declared_inputs_only() -> None:
    inherited = QaFinding(
        finding_id="i", severity="MINOR", description="Machine issue", references=("unknown",)
    )
    with pytest.raises(ValueError, match="Inherited finding references unknown input"):
        QualityInputs.model_validate(build(inherited_findings=(inherited,)))
    known = inherited.model_copy(update={"references": ("e",)})
    assert QualityInputs.model_validate(build(inherited_findings=(known,))).inherited_findings


def test_invalid_reports_and_mismatched_judgments_are_reported_not_raised() -> None:
    inputs, review = fixture()
    report = assess_quality(inputs, review)
    old = report.model_copy(update={"schema_version": "old"})
    assert validate_quality_report(inputs, review, old)[0].startswith("Invalid QA report:")
    other = review.model_copy(update={"inputs_sha256": "0" * 64})
    issues = validate_quality_report(inputs, other, report)
    assert issues[0].startswith("Invalid QA report:") and "does not bind" in issues[0]
    assert validate_quality_report(inputs, review, report) == ()


# --- Independent restatement of the r14 CP_CONFIDENCE_SCORE text -----------------------------
# Written from CANON_SHARED.md (Deploy VI bd71346) rather than from quality.py: integer-exact
# Decimal arithmetic over one common denominator, so ties are detected exactly.

R14_WEIGHT = {
    "Directly Sourced": Decimal("1.0"),
    "Calculated": Decimal("0.9"),
    "Assumption-Based": Decimal("0.5"),
    "Analyst Inference": Decimal("0.4"),
    "Weak Lineage": Decimal("0.3"),
    "Untraced": Decimal("0"),
    "Conflicting": Decimal("0"),
    "Insufficient Information": Decimal("0"),
}
R14_GATE = {"pass": Decimal("1.0"), "partial": Decimal("0.7"), "fail": Decimal("0.0")}
R14_PENALTY = {"CRITICAL": 40, "MATERIAL": 15, "MINOR": 3}
Claims = Sequence[tuple[bool, Sequence[Lineage]]]
Findings = Sequence[tuple[str, str, bool]]  # severity, status, producer-owned (inherited)


def restate_r14(
    claims: Claims,
    present: int,
    total: int,
    gate: str,
    module: str,
    findings: Findings,
) -> tuple[Fraction, int, str, str]:
    """Return unclamped raw score, rounded score, band and qa_status per r14 plus D1."""
    with localcontext() as ctx:
        ctx.prec = 80
        ctx.traps[Inexact] = True
        strongest = [
            max(R14_WEIGHT[x] for x in lineages) for material, lineages in claims if material
        ]
        denominator = max(len(strongest), 1) * total
        # 0.6*E + 0.4*C with E = sum(w)*100/n and C = present*100/total, over n*total.
        blend = Decimal("0.6") * sum(strongest, Decimal(0)) * 100 * total + Decimal(
            "0.4"
        ) * present * 100 * max(len(strongest), 1)
        open_ = [sev for sev, state, _ in findings if state == "open"]
        penalty = sum(R14_PENALTY[sev] for sev in open_)
        numerator = blend * R14_GATE[gate] - penalty * denominator
        raw = Fraction(numerator) / denominator
        clamped = min(max(numerator, Decimal(0)), 100 * denominator)
        if "CRITICAL" in open_ or module == "blocked" or gate == "fail":
            clamped, status = min(clamped, 39 * denominator), "Blocked"
        elif "MATERIAL" in open_ or module == "restricted" or gate == "partial":
            clamped, status = min(clamped, 59 * denominator), "Restricted"
        else:
            status = "Passed"
        whole, remainder = divmod(clamped, Decimal(denominator))
        if 2 * remainder > denominator or (2 * remainder == denominator and whole % 2 == 1):
            whole += 1
        score = int(whole)
    band = (
        "High"
        if score >= 80
        else "Medium"
        if score >= 60
        else "Low"
        if score >= 40
        else "Insufficient Information"
    )
    return raw, score, band, status


LINEAGES: tuple[Lineage, ...] = get_args(Lineage)


@st.composite
def scenarios(draw: st.DrawFn) -> tuple[Claims, int, int, str, str, Findings]:
    claims = draw(
        st.lists(
            st.tuples(
                st.booleans(),
                st.lists(st.sampled_from(LINEAGES), min_size=1, max_size=3),
            ),
            max_size=14,
        )
    )
    total = draw(st.integers(1, 40))
    present = draw(st.integers(0, total))
    gate = draw(st.sampled_from(["pass", "partial", "fail"]))
    module = draw(st.sampled_from(["complete", "restricted", "blocked"]))
    findings = draw(
        st.lists(
            st.tuples(
                st.sampled_from(["CRITICAL", "MATERIAL", "MINOR"]),
                st.sampled_from(["open", "open", "resolved", "closed", "cleared"]),
                st.booleans(),
            ),
            max_size=6,
        )
    )
    return claims, present, total, gate, module, findings


@st.composite
def near_tie_scenarios(draw: st.DrawFn) -> tuple[Claims, int, int, str, str, Findings]:
    """Uncapped-leaning mixes: only minor open findings, so exact .5 ties are frequent."""
    claims = draw(
        st.lists(
            st.tuples(
                st.just(True),
                st.lists(st.sampled_from(LINEAGES[:5]), min_size=1, max_size=2),
            ),
            min_size=1,
            max_size=14,
        )
    )
    total = draw(st.integers(1, 40))
    findings = draw(
        st.lists(st.tuples(st.just("MINOR"), st.just("open"), st.booleans()), max_size=3)
    )
    return (
        claims,
        draw(st.integers(0, total)),
        total,
        draw(st.sampled_from(["pass", "pass", "partial"])),
        draw(st.sampled_from(["complete", "complete", "restricted"])),
        findings,
    )


def _realize(
    claims: Claims, present: int, total: int, gate: str, module: str, findings: Findings
) -> tuple[QualityInputs, QualityReview]:
    def finding(i: int, severity: str, status: str) -> QaFinding:
        return QaFinding.model_validate(
            {
                "finding_id": f"f{i}",
                "severity": severity,
                "status": status,
                "description": "Synthetic finding",
                "resolution": None if status == "open" else "Synthetic resolution",
            }
        )

    items = [(i, *f) for i, f in enumerate(findings)]
    inputs = QualityInputs.model_validate(
        build(
            artifact_sha256="b" * 64,
            coverage_policy="synthetic-restatement/1",
            claims=tuple(
                ClaimCandidate(
                    claim_id=f"c{i}", evidence_ids=tuple(f"e{i}_{j}" for j in range(len(ls)))
                )
                for i, (_, ls) in enumerate(claims)
            ),
            coverage=tuple(
                CoverageField(field_id=f"f{i}", present=i < present, rationale="Synthetic slot")
                for i in range(total)
            ),
            source_gate=gate,
            module_status=module,
            references=tuple(
                f"e{i}_{j}" for i, (_, ls) in enumerate(claims) for j in range(len(ls))
            ),
            inherited_findings=tuple(finding(i, sev, st_) for i, sev, st_, own in items if own),
        )
    )
    review = QualityReview(
        inputs_sha256=inputs.content_hash(),
        claims=tuple(
            ClaimAssessment(
                claim_id=f"c{i}",
                material=material,
                rationale="Synthetic materiality",
                evidence=tuple(
                    EvidenceLineage(
                        evidence_id=f"e{i}_{j}", lineage_class=cls, rationale="Synthetic lineage"
                    )
                    for j, cls in enumerate(lineages)
                ),
            )
            for i, (material, lineages) in enumerate(claims)
        ),
        findings=tuple(finding(i, sev, st_) for i, sev, st_, own in items if not own),
    )
    return inputs, review


@settings(max_examples=400, deadline=None)
@given(st.one_of(scenarios(), near_tie_scenarios()))
def test_score_band_and_status_match_an_independent_r14_restatement(
    scenario: tuple[Claims, int, int, str, str, Findings],
) -> None:
    claims, present, total, _, _, findings = scenario
    raw, score, band, status = restate_r14(*scenario)
    inputs, review = _realize(*scenario)
    result = assess_quality(inputs, review).confidence
    assert (result.confidence_score, result.confidence_band, result.qa_status) == (
        score,
        band,
        status,
    )
    assert fraction(result.raw_score) == raw
    assert (result.fields_present, result.fields_total) == (present, total)
    assert result.material_claims == sum(1 for material, _ in claims if material)
    assert result.penalty == sum(R14_PENALTY[s] for s, state, _ in findings if state == "open")
    assert [x.finding_id for x in assess_quality(inputs, review).findings] == [
        f.finding_id for f in (*inputs.inherited_findings, *review.findings)
    ]


def test_restatement_agrees_with_the_canon_worked_example() -> None:
    claims = [(True, ["Directly Sourced"])] * 8 + [(True, ["Calculated"])] * 2
    claims += [(True, ["Assumption-Based"])] * 2
    raw, score, band, status = restate_r14(
        claims, 19, 20, "pass", "complete", [("MINOR", "open", False)]
    )
    assert (raw, score, band, status) == (89, 89, "High", "Passed")


# --- Deliberate adaptations of the r14 reference script --------------------------------------


def test_adaptation_exact_half_even_rounding_differs_from_float_round_on_a_real_tie() -> None:
    # 1 Directly Sourced + 11 Calculated material claims, 1 of 8 fields, gate pass:
    # E = 109/12*10, C = 12.5, so 0.6E + 0.4C is exactly 59.5. The r14 reference script
    # computes it in binary floats and its round() returned 59; exact ties-to-even is 60.
    claims = [(True, ["Directly Sourced"])] + [(True, ["Calculated"])] * 11
    raw, score, band, status = restate_r14(claims, 1, 8, "pass", "complete", [])
    assert raw == Fraction(119, 2)
    assert (score, band, status) == (60, "Medium", "Passed")
    inputs, review = _realize(claims, 1, 8, "pass", "complete", [])
    with localcontext() as ctx:
        ctx.prec = 1
        ctx.traps[Inexact] = True
        result = assess_quality(inputs, review).confidence
    assert fraction(result.raw_score) == Fraction(119, 2)
    assert (result.confidence_score, result.confidence_band) == (60, "Medium")
    assert result.rounding == "nearest_integer_ties_to_even"
    assert float(Fraction(119, 2)) == 59.5 and round(59.5) == 60  # python round is ties-to-even


@pytest.mark.parametrize(
    "gate,module,cap,status",
    [
        ("partial", "complete", 59, "Restricted"),
        ("pass", "restricted", 59, "Restricted"),
        ("fail", "complete", 0, "Blocked"),
        ("pass", "blocked", 39, "Blocked"),
    ],
)
def test_adaptation_source_gate_and_module_status_map_to_d1_without_any_finding(
    gate: str, module: str, cap: int, status: str
) -> None:
    # The r14 script derives qa_status only from findings, so a clean partial/fail gate would be
    # Passed there. D1 and the Deploy VII contract map the gate and module status to Restricted
    # or Blocked, so a clean review can never promote them. Fully covered, fully sourced:
    claims = [(True, ["Directly Sourced"])] * 3
    _, score, _, state = restate_r14(claims, 10, 10, gate, module, [])
    inputs, review = _realize(claims, 10, 10, gate, module, [])
    result = assess_quality(inputs, review).confidence
    assert (state, score) == (status, result.confidence_score)
    assert result.qa_status == status != "Passed"
    assert result.confidence_score == cap  # fully covered and sourced, so the cap binds
