"""CP-1 promotion (task 6.4): every condition, settlement by M4 rules, the envelope export."""

import json
import shutil
from pathlib import Path

import pytest

from deploy_vii.canonical_tables import REGISTER_NOTE
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_workflow import (
    PROMOTED,
    CP1Handoff,
    FinancialStage,
    cp1_register_preview,
    cp1_registers,
    promote_cp1,
    submit_cp1_step,
    write_cp1_envelope,
)
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview
from deploy_vii.envelope import read_envelope
from deploy_vii.execution import Attempt, Execution, NotAuthorized
from deploy_vii.quality import (
    ClaimAssessment,
    EvidenceLineage,
    QaFinding,
    QualityInputs,
    QualityReview,
)
from tests.product.test_execution import step_text
from tests.product.test_narrative import populated
from tests.product.test_narrative_projection import supplied
from tests.product.test_workflow import cp1_case


def staged(tmp_path: Path, *, partial: bool = False) -> tuple[Execution, Attempt]:
    """A CP-1 attempt with its four stages valid and one finding; the ticket is pending.

    The full case cites a KPI (ceiling Calculated); the partial case has no KPI, cites an
    observation and its narrative is blocked (its scope is data quality only).
    """
    store, ticket, extraction = cp1_case(tmp_path, partial=partial)
    financial = submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    output = FinancialStage.model_validate_json(step_text(store, financial.steps[-1]))
    narrative = submit_cp1_step(
        store,
        ticket.ticket_id,
        "narrative",
        (supplied if partial else populated)(output.narrative_inputs).model_dump_json(),
    )
    inputs = DownstreamInputs.model_validate_json(step_text(store, narrative.steps[-1]))
    done = submit_cp1_step(
        store,
        ticket.ticket_id,
        "readiness",
        DownstreamReview(inputs_sha256=inputs.content_hash()).model_dump_json(),
    )
    assert not done.issues and done.status == "pending"
    return store, done


def at_ceiling(inputs: QualityInputs, **update: object) -> QualityReview:
    """A review that keeps every lineage at its producer ceiling (the strongest allowed)."""
    ceiling = {c.evidence_id: c.ceiling for c in inputs.ceilings}
    review = QualityReview(
        inputs_sha256=inputs.content_hash(),
        claims=tuple(
            ClaimAssessment(
                claim_id=claim.claim_id,
                material=True,
                rationale="Synthetic materiality judgment",
                evidence=tuple(
                    EvidenceLineage(
                        evidence_id=e, lineage_class=ceiling[e], rationale="At its ceiling"
                    )
                    for e in claim.evidence_ids
                ),
            )
            for claim in inputs.claims
        ),
    )
    return review.model_copy(update=update)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str, QualityInputs]:
    store, attempt = staged(tmp_path_factory.mktemp("promotion"))
    inputs = cp1_quality_inputs(cp1_registers(store, attempt.ticket_id))
    return store.directory, attempt.ticket_id, inputs


@pytest.fixture
def journal(
    prepared: tuple[Path, str, QualityInputs], tmp_path: Path
) -> tuple[Execution, str, QualityInputs]:
    directory, ticket, inputs = prepared
    copy = tmp_path / "journal"
    shutil.copytree(directory, copy)
    return Execution(copy), ticket, inputs


def cp1_head(store: Execution) -> object:
    return next((h for h in store.read().heads if h.module_id == "CP-1"), None)


def test_promotion_settles_by_m4_rules_and_records_the_four_statuses(
    journal: tuple[Execution, str, QualityInputs], tmp_path: Path
) -> None:
    store, ticket, inputs = journal
    slot = next(f for f in inputs.coverage if f.field_id == "canonical-handoff")
    assert slot.present and "round-trips" in slot.rationale
    finished = promote_cp1(store, ticket, at_ceiling(inputs).model_dump_json())
    assert finished.status == "finished" and not finished.issues
    assert [s.step_id for s in finished.steps][-1] == "quality"
    head = next(h for h in store.read().heads if h.module_id == "CP-1")
    assert head.status == "restricted"  # own findings restrict (decision 0007)
    assert head.qualification == PROMOTED
    assert PROMOTED.model_dump() == {
        "implementation": "implemented",
        "analytical_qualification": "unrun",
        "rendering_acceptance": "unrun",
        "native_host_qualification": "unrun",
    }
    module = store.head_module(head)
    assert REGISTER_NOTE not in module.limitations
    assert any(t.startswith("CP-1 QA Restricted: confidence ") for t in module.limitations)
    assert module.inputs[: len(finished.inputs)] == finished.inputs
    handoff = CP1Handoff.model_validate_json(step_text(store, finished.steps[-1]))
    assert handoff.quality.confidence.qa_status == "Restricted"
    assert handoff.quality.inputs_sha256 == inputs.content_hash()

    path = write_cp1_envelope(store, tmp_path / "envelope")
    markdown, sidecar = path.read_text(), (path.parent / "envelope.json").read_text()
    envelope = read_envelope(markdown, sidecar)
    assert envelope.module.content_hash() == head.result_sha256
    assert envelope.journal == finished.inputs and envelope.quality == handoff.quality
    assert "| status | restricted |" in markdown
    assert f"| journal:CP-0 | {finished.inputs[1].sha256} restricted |" in markdown
    receipt = json.loads((path.parent / "complete.json").read_text())
    assert receipt["module_sha256"] == head.result_sha256
    assert receipt["qualification"] == PROMOTED.model_dump(mode="json")
    with pytest.raises(FileExistsError):
        write_cp1_envelope(store, tmp_path / "envelope")
    # The register preview still recomputes the four stages after promotion.
    assert cp1_register_preview(store, ticket, tmp_path / "preview").is_file()


def test_a_lineage_upgrade_never_promotes(journal: tuple[Execution, str, QualityInputs]) -> None:
    store, ticket, inputs = journal
    review = at_ceiling(inputs)
    claim = review.claims[0]
    calculated = next(e for e in claim.evidence if e.lineage_class == "Calculated")
    upgraded = claim.model_copy(
        update={
            "evidence": tuple(
                e.model_copy(update={"lineage_class": "Directly Sourced"}) if e == calculated else e
                for e in claim.evidence
            )
        }
    )
    review = review.model_copy(update={"claims": (upgraded, *review.claims[1:])})
    finished = promote_cp1(store, ticket, review.model_dump_json())
    assert finished.status == "finished"
    assert any("QA lineage upgrade rejected" in issue for issue in finished.issues)
    assert store.result(finished.result_sha256 or "").status == "rejected"
    assert cp1_head(store) is None


def test_a_review_bound_to_other_inputs_never_promotes(
    journal: tuple[Execution, str, QualityInputs],
) -> None:
    store, ticket, inputs = journal
    finished = promote_cp1(
        store, ticket, at_ceiling(inputs, inputs_sha256="0" * 64).model_dump_json()
    )
    assert "QA review does not bind current inputs" in finished.issues
    assert cp1_head(store) is None


def test_an_open_critical_qa_finding_blocks_and_is_not_promoted(
    journal: tuple[Execution, str, QualityInputs],
) -> None:
    store, ticket, inputs = journal
    critical = QaFinding(
        finding_id="critical", severity="CRITICAL", description="Synthetic critical finding"
    )
    finished = promote_cp1(
        store, ticket, at_ceiling(inputs, findings=(critical,)).model_dump_json()
    )
    assert any(i.startswith("CP-1 QA Blocked: confidence ") for i in finished.issues)
    assert store.result(finished.result_sha256 or "").status == "rejected"
    assert cp1_head(store) is None


def test_a_blocked_narrative_gives_blocked_qa_and_is_not_promoted(tmp_path: Path) -> None:
    store, attempt = staged(tmp_path, partial=True)
    inputs = cp1_quality_inputs(cp1_registers(store, attempt.ticket_id))
    assert inputs.module_status == "blocked"
    finished = promote_cp1(store, attempt.ticket_id, at_ceiling(inputs).model_dump_json())
    assert finished.issues == (
        "CP-1 QA Blocked: confidence 39 (Insufficient Information); "
        "a Blocked handoff is not promoted",
    )
    assert cp1_head(store) is None


def test_a_handoff_that_does_not_verify_never_promotes(
    journal: tuple[Execution, str, QualityInputs], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ticket, inputs = journal
    # Stands in for a writer/reader defect on the promoted envelope only.
    monkeypatch.setattr(
        "deploy_vii.cp1_workflow.envelope_issues", lambda markdown, sidecar: ("Synthetic defect",)
    )
    finished = promote_cp1(store, ticket, at_ceiling(inputs).model_dump_json())
    assert finished.issues == ("Canonical handoff verification failed: Synthetic defect",)
    assert cp1_head(store) is None


def test_an_absent_handoff_slot_never_promotes(
    journal: tuple[Execution, str, QualityInputs], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ticket, _ = journal
    monkeypatch.setattr(
        "deploy_vii.cp1_quality.handoff_issues", lambda envelope: ("Synthetic defect",)
    )
    inputs = cp1_quality_inputs(cp1_registers(store, ticket))
    slot = next(f for f in inputs.coverage if f.field_id == "canonical-handoff")
    assert not slot.present and slot.rationale.endswith("Synthetic defect")
    finished = promote_cp1(store, ticket, at_ceiling(inputs).model_dump_json())
    assert any(i.startswith("Canonical handoff does not verify: ") for i in finished.issues)
    assert cp1_head(store) is None


def test_a_claim_that_does_not_resolve_never_promotes(
    journal: tuple[Execution, str, QualityInputs], monkeypatch: pytest.MonkeyPatch
) -> None:
    from deploy_vii import cp1_workflow
    from deploy_vii.contracts import Claim

    store, ticket, inputs = journal
    original = cp1_workflow._candidate

    def with_bare_figure(*args: object, **kwargs: object) -> object:
        module = original(*args, **kwargs)  # type: ignore[arg-type]
        bare = Claim(claim_id="bare", text="Leverage is 5.2x", citations=())
        return module.model_copy(update={"claims": (*module.claims, bare)})

    monkeypatch.setattr(cp1_workflow, "_candidate", with_bare_figure)
    finished = promote_cp1(store, ticket, at_ceiling(inputs).model_dump_json())
    assert any("Bare figure" in issue for issue in finished.issues)
    assert cp1_head(store) is None


def test_cp0_must_authorise_cp1_before_anything_is_retained(
    journal: tuple[Execution, str, QualityInputs], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ticket, inputs = journal
    snapshot = store.read()
    heads = tuple(
        h.model_copy(
            update={
                "commands": tuple(
                    c.model_copy(update={"text": "DO NOT RUN"}) if c.row_id == "CP-1" else c
                    for c in h.commands
                )
            }
        )
        if h.module_id == "CP-0"
        else h
        for h in snapshot.heads
    )
    monkeypatch.setattr(store, "read", lambda: snapshot.model_copy(update={"heads": heads}))
    with pytest.raises(NotAuthorized):
        promote_cp1(store, ticket, at_ceiling(inputs).model_dump_json())
    monkeypatch.undo()
    assert store.read() == snapshot


def test_promotion_requires_the_four_valid_stages(tmp_path: Path) -> None:
    store, ticket, _ = cp1_case(tmp_path)
    with pytest.raises(ValueError, match="next module step in order"):
        promote_cp1(store, ticket.ticket_id, "{}")


def test_a_crash_before_settlement_resumes_from_the_retained_quality_step(
    journal: tuple[Execution, str, QualityInputs], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ticket, inputs = journal
    payload = at_ceiling(inputs).model_dump_json()

    def crash(*args: object, **kwargs: object) -> Attempt:
        raise RuntimeError("Simulated host crash before settlement")

    monkeypatch.setattr(store, "finish", crash)
    with pytest.raises(RuntimeError, match="Simulated"):
        promote_cp1(store, ticket, payload)
    monkeypatch.undo()
    pending = next(a for a in store.read().attempts if a.ticket_id == ticket)
    assert pending.status == "pending" and pending.steps[-1].status == "valid"
    with pytest.raises(ValueError, match="different QA review"):
        promote_cp1(store, ticket, at_ceiling(inputs, findings=()).model_dump_json() + " ")
    finished = promote_cp1(store, ticket, payload)
    assert finished.status == "finished" and not finished.issues
    assert len(finished.steps) == 5


def test_cli_quality_inputs_promotion_and_envelope(
    journal: tuple[Execution, str, QualityInputs],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from deploy_vii.__main__ import main

    store, ticket, inputs = journal
    base = ["deploy-vii", "execution", "--directory", str(store.directory)]
    monkeypatch.setattr("sys.argv", [*base, "cp1-quality-inputs", "--ticket", ticket])
    main()
    printed = QualityInputs.model_validate_json(capsys.readouterr().out)
    assert printed == inputs
    review = tmp_path / "quality-review.json"
    review.write_text(at_ceiling(printed).model_dump_json())
    monkeypatch.setattr(
        "sys.argv", [*base, "cp1-promote", "--ticket", ticket, "--review", str(review)]
    )
    main()
    assert json.loads(capsys.readouterr().out)["result"]["status"] == "restricted"
    output = tmp_path / "handoff"
    monkeypatch.setattr(
        "sys.argv", [*base, "envelope", "--module", "CP-1", "--output", str(output)]
    )
    main()
    assert capsys.readouterr().out.strip() == str(output / "envelope.md")
    assert {p.name for p in output.iterdir()} == {"envelope.md", "envelope.json", "complete.json"}


def test_envelope_export_requires_a_promoted_cp1_head(tmp_path: Path) -> None:
    store, _, _ = cp1_case(tmp_path)
    with pytest.raises(ValueError, match="no accepted or restricted head"):
        write_cp1_envelope(store, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_promotion_adds_no_limitation_beyond_a_non_passed_qa_line(
    journal: tuple[Execution, str, QualityInputs],
) -> None:
    """Accepted stays reachable (decision 0007): promotion itself is not an own finding."""
    from deploy_vii.cp1_workflow import _candidate
    from deploy_vii.quality import assess_quality

    store, ticket, inputs = journal
    registers = cp1_registers(store, ticket)
    attempt = next(a for a in store.read().attempts if a.ticket_id == ticket)
    quality = assess_quality(inputs, at_ceiling(inputs))
    passed = quality.model_copy(
        update={"confidence": quality.confidence.model_copy(update={"qa_status": "Passed"})}
    )
    rest = tuple(t for t in registers.module.limitations if t != REGISTER_NOTE)
    assert _candidate(registers, attempt, passed).limitations == rest
    restricted = _candidate(registers, attempt, quality).limitations
    assert restricted[1:] == rest and restricted[0].startswith("CP-1 QA Restricted: confidence ")
