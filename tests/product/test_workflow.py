"""Offline protocol fixtures, not analyst sufficiency or Module acceptance."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from deploy_vii.contracts import Claim, Input
from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.cp1_workflow import FinancialStage, FinancialSubmission, submit_cp1_step
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReport, DownstreamReview
from deploy_vii.execution import Attempt, Execution, StepSubmission, StepValidation
from deploy_vii.financial_contracts import FinancialBook
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import ConsumerReadiness, ReadinessReview, SourceAssessment
from deploy_vii.registry import plan
from tests.product.test_canonical_gaps import case
from tests.product.test_execution import candidate_for, fixture_store, settled, step_text
from tests.product.test_model_readiness import ready_case
from tests.product.test_narrative import draft
from tests.product.test_readiness import readiness_fixture


def test_cp0_trusted_submission_and_crash_between_promotion_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = fixture_store(tmp_path)
    _, review = readiness_fixture()
    ticket = store.begin("CP-0")
    original = store.finish

    def crash(*args: object, **kwargs: object) -> Attempt:
        raise RuntimeError("interrupted before promotion")

    monkeypatch.setattr(store, "finish", crash)
    with pytest.raises(RuntimeError):
        submit_cp0_review(store, ticket.ticket_id, review.model_dump_json())
    saved = store.read().attempts[-1]
    assert saved.status == "pending" and saved.steps[0].status == "valid"
    assert store.read().heads == ()
    with pytest.raises(ValueError, match="different response"):
        submit_cp0_review(store, ticket.ticket_id, "{}")
    monkeypatch.setattr(store, "finish", original)
    result = submit_cp0_review(store, ticket.ticket_id, review.model_dump_json())
    assert settled(store, result).status == "restricted"
    assert store.payload(result.steps[0].payload_sha256) == review.model_dump_json()
    assert len(store.read().attempts) == 1
    assert store.begin("CP-1").number == 0


@pytest.mark.parametrize("payload", ["not json", "stale", "issuer", "unusable"])
def test_cp0_invalid_review_consumes_shared_repair(tmp_path: Path, payload: str) -> None:
    store = fixture_store(tmp_path)
    _, review = readiness_fixture()
    unusable = payload == "unusable"
    if payload == "stale":
        payload = review.model_copy(update={"pack_sha256": "0" * 64}).model_dump_json()
    elif payload == "issuer":
        payload = review.model_copy(update={"issuer_confirmed": False}).model_dump_json()
    elif payload == "unusable":
        review = review.model_copy(
            update={
                "consumers": tuple(
                    c.model_copy(update={"readiness": "BLOCKED", "source_ids": (), "citations": ()})
                    for c in review.consumers
                ),
                "sources": tuple(
                    s.model_copy(update={"fidelity": "blocked"}) for s in review.sources
                ),
            }
        )
        payload = review.model_dump_json()
    for expected in ("rejected", "blocked"):
        ticket = store.begin("CP-0")
        result = submit_cp0_review(store, ticket.ticket_id, payload)
        assert settled(store, result).status == expected
        assert (
            result.steps[0].status == "invalid"
            and store.payload(result.steps[0].payload_sha256) == payload
        )
        if unusable:
            assert result.issues == (
                "No usable identity-confirmed evidence for the requested work",
            )
    with pytest.raises(ValueError, match="repair"):
        store.begin("CP-0")


def test_stage_crash_retains_exact_response_and_requires_explicit_resolution(
    tmp_path: Path,
) -> None:
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")

    def crash(pack: PreparedPack, attempt: Attempt) -> StepValidation:
        assert Execution(store.directory).read().attempts[-1] == attempt
        raise RuntimeError("validator crash")

    with pytest.raises(RuntimeError):
        store.submit_step(ticket.ticket_id, "CP-0", ("a", "b"), "a", "raw", crash)
    assert store.read().attempts[-1].steps[0].status == "pending"
    with pytest.raises(ValueError, match="different response"):
        store.submit_step(ticket.ticket_id, "CP-0", ("a", "b"), "a", "edited", crash)
    with pytest.raises(ValueError, match="step response is pending"):
        store.finish(ticket.ticket_id, candidate_for(store, "CP-0").model_dump_json(), lambda _: ())
    with pytest.raises(ValueError, match="pending"):
        store.replace_pack(store.pack())

    def valid(pack: PreparedPack, attempt: Attempt) -> StepValidation:
        return StepValidation(output="retained Python output")

    first = store.submit_step(ticket.ticket_id, "CP-0", ("a", "b"), "a", "raw", valid)
    second = store.submit_step(ticket.ticket_id, "CP-0", ("a", "b"), "b", "next", valid)
    assert second.steps[1].inputs == (
        *ticket.inputs,
        Input(input_id="step:a", sha256=first.steps[0].content_hash()),
    )
    assert second.status == "pending" and store.read().heads == ()
    with pytest.raises(ValueError, match="in order"):
        store.submit_step(ticket.ticket_id, "CP-0", ("a", "b"), "b", "next", valid)
    result = store.interrupt(ticket.ticket_id, "Host stopped after stage validation")
    assert result.steps == second.steps and result.issues
    repair = store.begin("CP-0")
    assert repair.number == 1 and repair.steps == ()


def test_stage_failure_budget_is_per_module_not_per_step(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)

    def valid(pack: PreparedPack, attempt: Attempt) -> StepValidation:
        return StepValidation(output="output")

    def invalid(pack: PreparedPack, attempt: Attempt) -> StepValidation:
        return StepValidation(issues=("Invalid response",))

    first = store.begin("CP-0")
    store.submit_step(first.ticket_id, "CP-0", ("a", "b"), "a", "valid", valid)
    failed = store.submit_step(first.ticket_id, "CP-0", ("a", "b"), "b", "bad b", invalid)
    assert settled(store, failed).status == "rejected"
    second = store.begin("CP-0")
    blocked = store.submit_step(second.ticket_id, "CP-0", ("a", "b"), "a", "bad a", invalid)
    assert settled(store, blocked).status == "blocked"
    assert second.repair_issues == failed.issues
    with pytest.raises(ValueError, match="repair"):
        store.begin("CP-0")


def test_concurrent_stage_submission_settles_once(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")

    def submit() -> str:
        try:
            store.submit_step(
                ticket.ticket_id,
                "CP-0",
                ("a",),
                "a",
                "raw",
                lambda p, a: StepValidation(output="ok"),
            )
            return "valid"
        except ValueError:
            return "ordered"

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(lambda _: submit(), range(2))) == ["ordered", "valid"]
    assert len(store.read().attempts[-1].steps) == 1


def test_step_state_contract() -> None:
    for change in ({"output": "bad"}, {"status": "valid"}, {"status": "invalid"}):
        with pytest.raises(ValidationError):
            StepSubmission.model_validate_json(
                json.dumps({"step_id": "s", "inputs": [], "payload": "raw", **change})
            )


def cp1_case(
    tmp_path: Path, *, partial: bool = False, book: FinancialBook | None = None
) -> tuple[Execution, Attempt, FinancialSubmission]:
    value = ready_case() if book is None else book
    if partial:
        value = value.model_copy(
            update={
                "addback_disclosure": value.addback_disclosure.model_copy(
                    update={"status": "partial"}
                )
            }
        )
    args = case(value)
    pack, context, financial, definition, binding = args
    store = Execution.create(tmp_path / "journal", pack)
    citations = context.sources[0].citations
    readiness = ReadinessReview(
        pack_sha256=pack.content_hash(),
        objective="Synthetic workflow test",
        reporting_period="FY2025",
        issuer_confirmed=True,
        gaps=(),
        analysis=(
            Claim(
                claim_id="fixture",
                text="Synthetic source permits protocol checks only",
                citations=citations,
            ),
        ),
        sources=(
            SourceAssessment(
                source_id="S1",
                document_family="Synthetic",
                limitations=("Synthetic evidence; authority unqualified",),
                authority="unknown",
                entity="Synthetic",
                period="FY2025",
                version_relationship="fixture",
                fidelity="verified",
                citations=citations,
            ),
        ),
        consumers=tuple(
            ConsumerReadiness(
                module_id=m,
                readiness="READY_WITH_LIMITATIONS",
                evidence_demand="Synthetic workflow only",
                source_ids=("S1",),
                rationale="Protocol fixture",
                citations=citations,
                limitations=("Synthetic fixture",),
            )
            for m in plan(pack.run.requested_modules)
            if m != "CP-0"
        ),
    )
    submitted = submit_cp0_review(store, store.begin("CP-0").ticket_id, readiness.model_dump_json())
    assert not submitted.issues
    ticket = store.begin("CP-1")
    source = submit_cp1_step(store, ticket.ticket_id, "source_context", context.model_dump_json())
    assert not source.issues
    extraction = FinancialSubmission(
        context_step_sha256=source.steps[0].content_hash(),
        financial=financial,
        definition=definition,
        binding=binding,
    )
    return store, ticket, extraction


@pytest.mark.parametrize("partial", [False, True])
def test_source_first_cp1_full_stages_remain_unaccepted(tmp_path: Path, partial: bool) -> None:
    store, ticket, extraction = cp1_case(tmp_path, partial=partial)
    with pytest.raises(ValueError, match="in order"):
        submit_cp1_step(store, ticket.ticket_id, "readiness", "{}")
    finances = submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    assert not finances.issues
    output = FinancialStage.model_validate_json(step_text(store, finances.steps[-1]))
    assert (output.model is None) is partial
    assert bool(output.model_issues) is partial
    narrative = draft(output.narrative_inputs)
    synthesis = submit_cp1_step(store, ticket.ticket_id, "narrative", narrative.model_dump_json())
    assert not synthesis.issues
    downstream = DownstreamInputs.model_validate_json(step_text(store, synthesis.steps[-1]))
    review = DownstreamReview(inputs_sha256=downstream.content_hash())
    ready = submit_cp1_step(store, ticket.ticket_id, "readiness", review.model_dump_json())
    assert not ready.issues and ready.status == "pending"
    report = DownstreamReport.model_validate_json(step_text(store, ready.steps[-1]))
    assert report.analytical_qualification == "unrun"
    assert [s.step_id for s in ready.steps] == [
        "source_context",
        "financials",
        "narrative",
        "readiness",
    ]
    assert [h.module_id for h in store.read().heads] == ["CP-0"]
    assert store.read().attempts[-1] == ready
    for index, step in enumerate(ready.steps):
        assert step.inputs == (
            *ticket.inputs,
            *(
                Input(input_id="step:" + s.step_id, sha256=s.content_hash())
                for s in ready.steps[:index]
            ),
        )


def rejected_twice(store: Execution, ticket_id: str, stage: str, payload: str) -> Attempt:
    """Task 7.0g: a CP-1 step's first rejection is repaired within its attempt (the attempt stays
    pending); the second rejection finishes the attempt as a single one did before."""
    first = submit_cp1_step(store, ticket_id, stage, payload)
    assert first.status == "pending" and first.step_repairs[-1].step_id == stage
    return submit_cp1_step(store, ticket_id, stage, payload)


@pytest.mark.parametrize("stage", ["financials", "narrative", "readiness"])
def test_stale_stage_bindings_reject_and_retain_response(tmp_path: Path, stage: str) -> None:
    store, ticket, extraction = cp1_case(tmp_path)
    payload = extraction.model_copy(update={"context_step_sha256": "0" * 64}).model_dump_json()
    if stage != "financials":
        finances = submit_cp1_step(
            store, ticket.ticket_id, "financials", extraction.model_dump_json()
        )
        output = FinancialStage.model_validate_json(step_text(store, finances.steps[-1]))
        review = draft(output.narrative_inputs)
        payload = review.model_copy(update={"inputs_sha256": "0" * 64}).model_dump_json()
        if stage == "readiness":
            submit_cp1_step(store, ticket.ticket_id, "narrative", review.model_dump_json())
            payload = DownstreamReview(inputs_sha256="0" * 64).model_dump_json()
    result = rejected_twice(store, ticket.ticket_id, stage, payload)
    assert settled(store, result).status == "rejected"
    assert (
        store.payload(result.steps[-1].payload_sha256) == payload
        and result.steps[-1].status == "invalid"
    )
    assert result.issues and store.begin("CP-1").number == 1


def test_module_payload_blocks_new_steps_and_validator_bug_stays_pending(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    with pytest.raises(ValueError, match="retain its output"):
        store.submit_step(
            ticket.ticket_id, "CP-0", ("a",), "a", "raw", lambda p, a: StepValidation()
        )
    assert store.read().attempts[-1].steps[0].status == "pending"
    interrupted = store.interrupt(ticket.ticket_id, "Unrecoverable callback defect")
    assert store.payload(interrupted.steps[0].payload_sha256) == "raw"
    repair = store.begin("CP-0")

    def crash(candidate: object) -> tuple[str, ...]:
        raise RuntimeError("promotion interrupted")

    with pytest.raises(RuntimeError):
        store.finish(repair.ticket_id, candidate_for(store, "CP-0", 1).model_dump_json(), crash)
    with pytest.raises(ValueError, match="module response is already retained"):
        store.submit_step(
            repair.ticket_id, "CP-0", ("a",), "a", "raw", lambda p, a: StepValidation(output="ok")
        )


@pytest.mark.parametrize("stage", ["source_context", "financials", "narrative", "readiness"])
def test_malformed_response_at_every_cp1_stage_consumes_attempt(tmp_path: Path, stage: str) -> None:
    store, ticket, extraction = cp1_case(tmp_path)
    if stage == "source_context":
        store.interrupt(ticket.ticket_id, "Restart fixture at source stage")
        ticket = store.begin("CP-1")
    if stage in {"narrative", "readiness"}:
        finances = submit_cp1_step(
            store, ticket.ticket_id, "financials", extraction.model_dump_json()
        )
        output = FinancialStage.model_validate_json(step_text(store, finances.steps[-1]))
        if stage == "readiness":
            submit_cp1_step(
                store,
                ticket.ticket_id,
                "narrative",
                draft(output.narrative_inputs).model_dump_json(),
            )
    result = rejected_twice(store, ticket.ticket_id, stage, "malformed json")
    assert result.issues and store.payload(result.steps[-1].payload_sha256) == "malformed json"
    assert result.status == "finished"


def test_financial_binding_error_is_a_targeted_repair_issue(tmp_path: Path) -> None:
    store, ticket, extraction = cp1_case(tmp_path)
    invalid = extraction.model_copy(
        update={
            "binding": extraction.binding.model_copy(update={"financial_review_sha256": "0" * 64})
        }
    )
    result = submit_cp1_step(store, ticket.ticket_id, "financials", invalid.model_dump_json())
    # Task 7.0g: the first rejection is kept for the step's one repair within the attempt.
    (retained,) = result.step_repairs
    assert result.status == "pending" and retained.issues and retained.status == "invalid"


def test_unassessed_source_gate_blocks_extraction(tmp_path: Path) -> None:
    store, ticket, _ = cp1_case(tmp_path)
    store.interrupt(ticket.ticket_id, "Restart fixture at source stage")
    repair = store.begin("CP-1")
    from deploy_vii.source_context import SourceContextReview

    prior = SourceContextReview.model_validate_json(
        store.payload(store.read().attempts[-2].steps[0].payload_sha256)
    )
    empty = prior.model_copy(
        update={
            "sources": tuple(
                s.model_copy(update={"classification": "nonfinancial"}) for s in prior.sources
            )
        }
    )
    result = rejected_twice(store, repair.ticket_id, "source_context", empty.model_dump_json())
    assert result.issues and settled(store, result).status == "blocked"
    assert "source gate" in result.issues[0]


def test_execution_cli_runs_trusted_cp0_and_reads_stage_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    store = fixture_store(tmp_path)
    _, review = readiness_fixture()
    raw = tmp_path / "review.json"
    raw.write_text(review.model_dump_json())

    def cli(*arguments: str) -> str:
        monkeypatch.setattr(
            "sys.argv", ["deploy-vii", "execution", "--directory", str(store.directory), *arguments]
        )
        main()
        return capsys.readouterr().out

    ticket = json.loads(cli("begin", "CP-0"))["ticket_id"]
    result = json.loads(cli("cp0-submit", "--ticket", ticket, "--review", str(raw)))
    assert result["result"]["status"] == "restricted"
    output = json.loads(cli("step-output", "--ticket", ticket, "--step", "source_readiness"))
    assert output["status"] == "candidate"
    assert json.loads(cli("status"))["heads"][0]["module_id"] == "CP-0"
    with pytest.raises(ValueError, match="No valid"):
        cli("step-output", "--ticket", ticket, "--step", "missing")
    next_ticket = json.loads(cli("begin", "CP-1"))["ticket_id"]
    raw.write_text("not json")
    submit = ("cp1-submit", "--ticket", next_ticket, "--step", "source_context")
    submit += ("--review", str(raw))

    def rejected() -> dict[str, Any]:
        # M8c: a rejected review exits 1 (it exited 0 before), the attempt JSON still on stdout.
        with pytest.raises(SystemExit) as stop:
            cli(*submit)
        assert stop.value.code == 1
        return json.loads(capsys.readouterr().out)

    slipped = rejected()  # task 7.0g: kept for the step's one repair
    assert slipped["status"] == "pending" and slipped["step_repairs"][0]["issues"]
    failed = rejected()
    assert failed["issues"]
    repair = json.loads(cli("begin", "CP-1"))["ticket_id"]
    assert (
        json.loads(cli("interrupt", "--ticket", repair, "--reason", "Fixture stopped"))["result"][
            "status"
        ]
        == "blocked"
    )


def test_cli_creates_and_replaces_only_frozen_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main
    from deploy_vii.preparation import PreparationRequest, SourceRequest, prepare

    pack, _ = readiness_fixture()
    (tmp_path / "source.txt").write_text("Original frozen text")
    request = PreparationRequest(
        run=pack.run,
        sources=(SourceRequest(source_id="S", path="source.txt", media_type="text/plain"),),
    )
    prepare(request, tmp_path, tmp_path / "pack-one")
    (tmp_path / "source.txt").write_text("Changed frozen text")
    second = prepare(request, tmp_path, tmp_path / "pack-two")
    directory = tmp_path / "execution"
    for action, source in (("create", "pack-one"), ("replace-pack", "pack-two")):
        monkeypatch.setattr(
            "sys.argv",
            [
                "deploy-vii",
                "execution",
                "--directory",
                str(directory),
                action,
                "--pack",
                str(tmp_path / source),
            ],
        )
        main()
        assert json.loads(capsys.readouterr().out)["schema_version"] == "execution/5"
    assert Execution(directory).pack() == second


def test_invalid_quarter_selection_is_retained_readiness_gap(tmp_path: Path) -> None:
    store, ticket, extraction = cp1_case(tmp_path)
    extraction = extraction.model_copy(update={"quarter_ids": ("unknown", "unknown")})
    finances = submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    output = FinancialStage.model_validate_json(step_text(store, finances.steps[-1]))
    narrative = submit_cp1_step(
        store, ticket.ticket_id, "narrative", draft(output.narrative_inputs).model_dump_json()
    )
    assert not narrative.issues
    downstream = DownstreamInputs.model_validate_json(step_text(store, narrative.steps[-1]))
    assert downstream.model.requested_quarters == ("unknown", "unknown")
    assert '"quarter_selection"' in downstream.model.model_dump_json()
    assert '"BLOCK"' in downstream.model.model_dump_json()


def test_source_stage_requires_exact_current_pack_and_consumer_aliases_are_retained(
    tmp_path: Path,
) -> None:
    from deploy_vii.cp1_workflow import consumer_entries
    from deploy_vii.source_context import SourceContextReview

    store, ticket, _ = cp1_case(tmp_path)
    prior = SourceContextReview.model_validate_json(
        store.payload(store.read().attempts[-1].steps[0].payload_sha256)
    )
    store.interrupt(ticket.ticket_id, "Fixture restart")
    repair = store.begin("CP-1")
    failed = rejected_twice(
        store,
        repair.ticket_id,
        "source_context",
        prior.model_copy(update={"pack_sha256": "0" * 64}).model_dump_json(),
    )
    assert failed.issues and settled(store, failed).status == "blocked"
    pack = store.pack()
    selected = pack.model_copy(
        update={
            "run": pack.run.model_copy(update={"requested_modules": ("CP-4A", "CP-5A", "CP-2C")})
        }
    )
    entries = consumer_entries(selected)
    assert {"CP-4", "CP-4A", "CP-5", "CP-5A", "CP-1A", "CP-2C"} <= set(entries)
    assert "CP-0" not in entries and "CP-1" not in entries


def test_invalid_step_requests_do_not_mutate_journal(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    before = store.read().content_hash()
    for ticket_id, module, sequence, step in (
        (ticket.ticket_id, "CP-0", (), "a"),
        (ticket.ticket_id, "CP-0", ("a", "a"), "a"),
        ("absent", "CP-0", ("a",), "a"),
        (ticket.ticket_id, "CP-1", ("a",), "a"),
        (ticket.ticket_id, "CP-0", ("a", "b"), "b"),
    ):
        with pytest.raises(ValueError):
            store.submit_step(
                ticket_id,
                module,
                sequence,
                step,
                "raw",
                lambda p, a: StepValidation(output="valid"),
            )
        assert store.read().content_hash() == before


@pytest.mark.parametrize("version", ["execution/1", "execution/2", "execution/3"])
def test_legacy_snapshot_version_is_rejected_explicitly(tmp_path: Path, version: str) -> None:
    from deploy_vii.execution import ExecutionSnapshot

    store = fixture_store(tmp_path)
    legacy = store.read().model_copy(update={"schema_version": version})
    with pytest.raises(ValidationError, match="execution/5"):
        ExecutionSnapshot.model_validate_json(legacy.model_dump_json())
