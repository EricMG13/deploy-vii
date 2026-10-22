"""CP-1 promotion (task 6.4): every condition, settlement by M4 rules, the envelope export."""

import json
import shutil
from pathlib import Path

import pytest

from deploy_vii.canonical_tables import REGISTER_NOTE, CanonicalTables
from deploy_vii.contracts import Input, Module
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
from deploy_vii.execution import Attempt, Execution, NotAuthorized, text_sha256
from deploy_vii.quality import (
    ClaimAssessment,
    EvidenceLineage,
    QaFinding,
    QualityInputs,
    QualityReport,
    QualityReview,
)
from tests.product.test_execution import step_text
from tests.product.test_narrative import populated
from tests.product.test_narrative_projection import supplied
from tests.product.test_workflow import cp1_case

SLIP = "not json"  # a payload every CP-1 step validator rejects ("(root): Invalid JSON")


def staged(
    tmp_path: Path, *, partial: bool = False, slip: str | None = None
) -> tuple[Execution, Attempt]:
    """A CP-1 attempt with its four stages valid and one finding; the ticket is pending.

    The full case cites a KPI (ceiling Calculated); the partial case has no KPI, cites an
    observation and its narrative is blocked (its scope is data quality only). With `slip`, that
    step is first rejected once and then repaired within the attempt (task 7.0g).
    """
    store, ticket, extraction = cp1_case(tmp_path, partial=partial)

    def submit(step_id: str, payload: str) -> Attempt:
        if step_id == slip:
            assert submit_cp1_step(store, ticket.ticket_id, step_id, SLIP).status == "pending"
        return submit_cp1_step(store, ticket.ticket_id, step_id, payload)

    financial = submit("financials", extraction.model_dump_json())
    output = FinancialStage.model_validate_json(step_text(store, financial.steps[-1]))
    narrative = submit(
        "narrative",
        (supplied if partial else populated)(output.narrative_inputs).model_dump_json(),
    )
    inputs = DownstreamInputs.model_validate_json(step_text(store, narrative.steps[-1]))
    done = submit(
        "readiness", DownstreamReview(inputs_sha256=inputs.content_hash()).model_dump_json()
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
    # Promotion settles the module, so `quality` keeps the attempt-level rule (task 7.0g).
    assert finished.step_repairs == ()
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

    def with_bare_figure(
        registers: CanonicalTables, attempt: Attempt, quality: QualityReport
    ) -> Module:
        module = original(registers, attempt, quality)
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


# --- 7.0g: one repair per step within the attempt (decision 0008 MC-7 item 2) ----------------


def test_the_within_attempt_repair_covers_the_four_cp1_model_steps_only() -> None:
    from deploy_vii.cp1_workflow import CP1_PROMOTION, CP1_STEPS
    from deploy_vii.execution import WITHIN_ATTEMPT_REPAIR

    assert WITHIN_ATTEMPT_REPAIR == {"CP-1": frozenset(CP1_STEPS)}
    assert "quality" in CP1_PROMOTION and "quality" not in WITHIN_ATTEMPT_REPAIR["CP-1"]


def files_of(store: Execution) -> set[Path]:
    return {path for path in store.directory.rglob("*") if path.is_file()}


def test_a_rejected_step_stays_pending_and_is_repaired_once_within_its_attempt(
    tmp_path: Path,
) -> None:
    store, ticket, extraction = cp1_case(tmp_path)
    heads = store.read().heads
    slipped = submit_cp1_step(store, ticket.ticket_id, "financials", SLIP)
    assert slipped.status == "pending" and slipped.number == 0
    assert slipped.payload_sha256 is None and slipped.result_sha256 is None and not slipped.issues
    assert [(s.step_id, s.status) for s in slipped.steps] == [("source_context", "valid")]
    (entry,) = slipped.step_repairs
    assert (entry.step_id, entry.status) == ("financials", "invalid")
    assert entry.payload_sha256 == text_sha256(SLIP)
    assert entry.issues[0].startswith("(root): Invalid JSON")
    assert entry.inputs == (
        *ticket.inputs,
        Input(input_id="step:source_context", sha256=slipped.steps[0].content_hash()),
    )
    assert store.read().heads == heads  # nothing settled, no head written
    with pytest.raises(ValueError, match="Submit the next module step in order"):
        submit_cp1_step(store, ticket.ticket_id, "narrative", "{}")
    repaired = submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    assert repaired.status == "pending" and not repaired.issues
    assert [(s.step_id, s.status) for s in repaired.steps] == [
        ("source_context", "valid"),
        ("financials", "valid"),
    ]
    assert repaired.step_repairs == slipped.step_repairs


def test_a_second_rejection_of_the_step_finishes_the_attempt_and_a_third_try_is_refused(
    tmp_path: Path,
) -> None:
    store, ticket, _ = cp1_case(tmp_path)
    submit_cp1_step(store, ticket.ticket_id, "financials", SLIP)
    finished = submit_cp1_step(store, ticket.ticket_id, "financials", "{}")
    assert finished.status == "finished"
    assert [(s.step_id, s.status) for s in finished.steps] == [
        ("source_context", "valid"),
        ("financials", "invalid"),
    ]
    assert finished.issues == finished.steps[-1].issues  # the second try's own issues
    assert not any("Invalid JSON" in issue for issue in finished.issues)
    assert [s.payload_sha256 for s in finished.step_repairs] == [text_sha256(SLIP)]
    assert store.result(finished.result_sha256 or "").status == "rejected"
    assert not [h for h in store.read().heads if h.module_id == "CP-1"]
    before = files_of(store)
    with pytest.raises(ValueError, match="absent, finished"):
        submit_cp1_step(store, ticket.ticket_id, "financials", "{ }")
    assert files_of(store) == before  # refused before any write
    repair = store.begin("CP-1")  # the module-wide repair is the second line
    assert repair.number == 1 and repair.repair_issues == finished.issues
    assert repair.step_repairs == ()


def test_a_crashed_repair_try_resumes_with_its_own_payload_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ticket, extraction = cp1_case(tmp_path)
    submit_cp1_step(store, ticket.ticket_id, "financials", SLIP)
    payload = extraction.model_dump_json()

    def crash(*_: object) -> object:
        raise RuntimeError("Simulated validator crash")

    monkeypatch.setattr("deploy_vii.cp1_workflow._validate_stage", crash)
    with pytest.raises(RuntimeError, match="Simulated"):
        submit_cp1_step(store, ticket.ticket_id, "financials", payload)
    monkeypatch.undo()
    pending = next(a for a in store.read().attempts if a.ticket_id == ticket.ticket_id)
    assert [s.status for s in pending.steps] == ["valid", "pending"]
    assert len(pending.step_repairs) == 1
    with pytest.raises(ValueError, match="different response"):
        submit_cp1_step(store, ticket.ticket_id, "financials", SLIP)
    resumed = submit_cp1_step(store, ticket.ticket_id, "financials", payload)
    assert [s.status for s in resumed.steps] == ["valid", "valid"]


def test_an_interruption_while_a_step_awaits_its_repair_finishes_as_today(
    tmp_path: Path,
) -> None:
    store, ticket, _ = cp1_case(tmp_path)
    submit_cp1_step(store, ticket.ticket_id, "financials", SLIP)
    finished = store.interrupt(ticket.ticket_id, "host stopped")
    assert finished.status == "finished" and finished.issues == ("Interrupted: host stopped",)
    assert [s.step_id for s in finished.steps] == ["source_context"]
    assert len(finished.step_repairs) == 1
    assert store.result(finished.result_sha256 or "").status == "rejected"
    assert store.begin("CP-1").repair_issues == finished.issues


@pytest.mark.parametrize("slip", ["financials", "readiness"])
def test_a_step_repaired_within_the_attempt_promotes_exactly_as_one_never_rejected(
    tmp_path: Path, slip: str
) -> None:
    """The rejected try is kept in `step_repairs`, outside the positional `steps` that every
    CP-1 reader and the module's content hash use: the same final payloads give the same
    `result_sha256` whether or not a step was repaired on the way."""
    results = []
    for name, step in (("clean", None), ("slipped", slip)):
        store, attempt = staged(tmp_path / name, slip=step)
        assert [s.step_id for s in attempt.step_repairs] == ([step] if step else [])
        inputs = cp1_quality_inputs(cp1_registers(store, attempt.ticket_id))
        finished = promote_cp1(store, attempt.ticket_id, at_ceiling(inputs).model_dump_json())
        assert finished.status == "finished" and not finished.issues
        results.append((finished.result_sha256, [s.content_hash() for s in finished.steps]))
    assert results[0] == results[1]
