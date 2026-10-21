from pathlib import Path

import pytest

from deploy_vii.contracts import Citation, Claim
from deploy_vii.preparation import PreparedPack, SourceRequest, prepare_source
from deploy_vii.readiness import (
    ConsumerReadiness,
    ReadinessGap,
    ReadinessReview,
    SourceAssessment,
    build_readiness,
    citation_issues,
    validate_review,
)
from deploy_vii.registry import plan
from tests.product.test_render import synthetic_view


def readiness_fixture() -> tuple[PreparedPack, ReadinessReview]:
    source = prepare_source(
        SourceRequest(source_id="filing", path="filing.txt", media_type="text/plain"),
        b"Synthetic issuer FY2025 cash USD million 0\n",
    )
    pack = PreparedPack(run=synthetic_view().run, sources=(source,))
    assert source.sha256
    citation = Citation(
        source_id="filing",
        source_sha256=source.sha256,
        locator="line:1",
        quote="Synthetic issuer FY2025 cash USD million 0",
    )
    limitations = ("Synthetic partial source pack; full underwriting documents absent",)
    consumers = tuple(
        ConsumerReadiness(
            module_id=module_id,
            readiness="READY_WITH_LIMITATIONS",
            evidence_demand="Bounded source-limited test only",
            source_ids=("filing",),
            rationale="Synthetic test input only",
            citations=(citation,),
            limitations=limitations,
        )
        for module_id in plan(pack.run.requested_modules)
        if module_id != "CP-0"
    )
    review = ReadinessReview(
        pack_sha256=pack.content_hash(),
        objective="Exercise source-limited fixture handling",
        reporting_period="FY2025",
        issuer_confirmed=True,
        sources=(
            SourceAssessment(
                source_id="filing",
                document_family="synthetic text fixture",
                authority="unknown",
                entity="Synthetic issuer",
                period="FY2025",
                version_relationship="standalone synthetic fixture",
                fidelity="verified",
                citations=(citation,),
                limitations=limitations,
            ),
        ),
        consumers=consumers,
        gaps=(
            ReadinessGap(
                gap_id="missing-pack",
                kind="source",
                severity="material",
                description=limitations[0],
                affected_modules=tuple(item.module_id for item in consumers),
                remediation="Supply a frozen public issuer pack",
            ),
        ),
        analysis=(
            Claim(
                claim_id="readiness",
                text="Synthetic text is readable but cannot establish full underwriting readiness.",
                citations=(citation,),
            ),
        ),
    )
    return pack, review


def test_cp0_preserves_all_registers_exact_lineage_and_no_final_verdict() -> None:
    pack, review = readiness_fixture()
    assert validate_review(pack, review) == ()
    module = build_readiness(pack, review)
    assert module.status == "candidate"
    assert module.inputs[0].sha256 == pack.content_hash()
    assert {fact.table_id for fact in module.facts} == {
        "P3",
        "P5",
        "T1",
        "T2",
        "T3",
        "T4",
        "T5",
        "T6",
        "T7",
        "T8",
    }
    assert any(fact.text == "Run CP-1" for fact in module.facts)
    assert any("Synthetic" in text for text in module.limitations)
    assert not [fact for fact in module.facts if fact.amount is not None]


def test_changed_pack_unavailable_and_false_quotes_rejected() -> None:
    pack, review = readiness_fixture()
    assert (
        "Review does not bind"
        in validate_review(pack, review.model_copy(update={"pack_sha256": "0" * 64}))[0]
    )
    valid = review.analysis[0].citations[0]
    for update in (
        {"quote": "invented"},
        {"locator": "line:99"},
        {"source_sha256": "0" * 64},
        {"source_id": "missing"},
    ):
        assert citation_issues((valid.model_copy(update=update),), pack.sources)
    corrupt = review.model_copy(
        update={
            "analysis": (
                review.analysis[0].model_copy(
                    update={"citations": (valid.model_copy(update={"quote": "invented"}),)}
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="Quote/locator"):
        build_readiness(pack, corrupt)


def test_cannot_discard_source_consumer_or_limitations() -> None:
    pack, review = readiness_fixture()
    assert validate_review(pack, review.model_copy(update={"sources": ()}))
    assert validate_review(pack, review.model_copy(update={"consumers": review.consumers[:-1]}))
    optimistic = review.consumers[0].model_copy(update={"readiness": "READY", "limitations": ()})
    issues = validate_review(
        pack, review.model_copy(update={"consumers": (optimistic, *review.consumers[1:])})
    )
    assert any("limitations" in issue for issue in issues)
    assert any("gap" in issue for issue in issues)


def test_conditional_command_cannot_be_executed() -> None:
    pack, review = readiness_fixture()
    conditional = ConsumerReadiness(
        module_id="CP-1",
        readiness="CONDITIONAL",
        evidence_demand="Financial statements",
        source_ids=(),
        citations=(),
        rationale="No usable financial statements supplied",
        missing_source="Audited FY2025 statements",
        limitations=("Audited FY2025 statements absent",),
    )
    changed = review.model_copy(
        update={
            "consumers": tuple(
                conditional if item.module_id == "CP-1" else item for item in review.consumers
            )
        }
    )
    module = build_readiness(pack, changed)
    assert (
        next(fact.text for fact in module.facts if fact.fact_id == "T8.CP-1.exact_command")
        == "DO NOT RUN"
    )


def test_prepared_pack_and_review_survive_json_roundtrip(tmp_path: Path) -> None:
    pack, review = readiness_fixture()
    path = tmp_path / "review.json"
    path.write_text(review.model_dump_json())
    restored = ReadinessReview.model_validate_json(path.read_bytes())
    assert build_readiness(pack, restored) == build_readiness(pack, review)


def test_frozen_copy_does_not_bypass_required_limitations_or_nonempty_quote() -> None:
    pack, review = readiness_fixture()
    missing_limit = review.model_copy(
        update={
            "consumers": tuple(
                item.model_copy(update={"limitations": ()}) for item in review.consumers
            )
        }
    )
    assert "Invalid readiness contract" in validate_review(pack, missing_limit)[0]
    citation = review.analysis[0].citations[0].model_copy(update={"quote": ""})
    corrupt = review.model_copy(
        update={"analysis": (review.analysis[0].model_copy(update={"citations": (citation,)}),)}
    )
    assert "Invalid readiness contract" in validate_review(pack, corrupt)[0]


def test_source_classification_cannot_use_other_source_quote() -> None:
    pack, review = readiness_fixture()
    second = prepare_source(
        SourceRequest(source_id="other", path="other.txt", media_type="text/plain"),
        b"Other issuer and period",
    )
    pack = pack.model_copy(update={"sources": (*pack.sources, second)})
    assert second.sha256
    other_citation = Citation(
        source_id="other",
        source_sha256=second.sha256,
        locator="line:1",
        quote="Other issuer and period",
    )
    original = review.sources[0]
    review = review.model_copy(
        update={
            "pack_sha256": pack.content_hash(),
            "sources": (
                original.model_copy(update={"citations": (other_citation,)}),
                original.model_copy(update={"source_id": "other", "citations": (other_citation,)}),
            ),
        }
    )
    assert any("different source" in issue for issue in validate_review(pack, review))


def test_reverse_review_order_does_not_change_dependency_command_order() -> None:
    pack, review = readiness_fixture()
    module = build_readiness(
        pack, review.model_copy(update={"consumers": tuple(reversed(review.consumers))})
    )
    commands = [
        fact.row_id
        for fact in module.facts
        if fact.table_id == "T8" and fact.field == "exact_command"
    ]
    assert commands == list(plan(pack.run.requested_modules))[1:]
