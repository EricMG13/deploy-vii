"""Offline protocol fixtures, not analyst sufficiency or Module acceptance."""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from deploy_vii.contracts import Claim, Input
from deploy_vii.cp0_workflow import (
    InvalidReadinessAddendum,
    cp0_addendum_context,
    submit_cp0_addendum,
    submit_cp0_review,
)
from deploy_vii.cp1_workflow import FinancialStage, FinancialSubmission, submit_cp1_step
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReport, DownstreamReview
from deploy_vii.execution import Attempt, Execution, StepSubmission, StepValidation, current_inputs
from deploy_vii.financial_contracts import FinancialBook
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import ConsumerReadiness, ReadinessReview, SourceAssessment
from deploy_vii.registry import plan
from tests.product.test_canonical_gaps import case
from tests.product.test_execution import candidate_for, fixture_store, settled, step_text
from tests.product.test_model_readiness import ready_case
from tests.product.test_narrative import draft
from tests.product.test_readiness import as_submission, readiness_fixture


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


# M9.1b: genuine retained CP-0 source-readiness addenda (synthetic/offline only).


def journal(tmp_path: Path) -> Execution:
    pack, review = readiness_fixture()
    pack = pack.model_copy(
        update={"run": pack.run.model_copy(update={"requested_modules": ("CP-1",)})}
    )
    review = review.model_copy(
        update={
            "pack_sha256": pack.content_hash(),
            "consumers": tuple(c for c in review.consumers if c.module_id == "CP-1"),
            "gaps": (),
        }
    )
    store = Execution.create(tmp_path / "journal", pack)
    # Retain noncanonical JSON: the review's canonical hash is not its raw blob name.
    payload = json.dumps(review.model_dump(mode="json"), indent=2)
    done = submit_cp0_review(store, store.begin("CP-0").ticket_id, payload)
    assert not done.issues
    return store


def payload(store: Execution, requested: tuple[str, ...]) -> tuple[str, str]:
    context = cp0_addendum_context(store, requested)
    _, review = readiness_fixture()
    template = as_submission(review)
    consumer = template.consumers[0]
    document = {
        "consumers": [
            consumer.model_copy(update={"module_id": m}).model_dump(mode="json")
            for m in context.added_modules
            if m != "CP-0"
        ],
        "gaps": [],
        "analysis": [
            c.model_copy(update={"claim_id": "new-readiness"}).model_dump(mode="json")
            for c in template.analysis
        ],
    }
    return json.dumps(document), context.content_hash()


def test_genuine_cp0_can_authorize_a_new_consumer_without_rewriting_old_rows(
    tmp_path: Path,
) -> None:
    store = journal(tmp_path)
    before = store.read()
    old_inputs = current_inputs(before, "CP-1")
    requested = (*before.run.requested_modules, "CP-4")
    with pytest.raises(ValueError, match="not assessed CP-4"):
        store.extend_scope(requested)
    raw, context_hash = payload(store, requested)
    report = submit_cp0_addendum(store, requested, raw, context_sha256=context_hash)
    after = Execution(store.directory).read()
    assert report.extended and report.readiness_addendum_sha256
    assert after.pack_sha256 == before.pack_sha256
    assert after.heads == before.heads and after.attempts == before.attempts
    assert current_inputs(after, "CP-1") == old_inputs
    assert "readiness_addenda" not in before.model_dump(mode="json")
    assert after.readiness_addenda[0].sha256 == report.readiness_addendum_sha256


def test_invalid_import_writes_nothing_and_stale_context_refuses(tmp_path: Path) -> None:
    store = journal(tmp_path)
    requested = ("CP-1", "CP-4")
    raw, context_hash = payload(store, requested)
    before = {
        p.relative_to(store.directory): p.read_bytes()
        for p in store.directory.rglob("*")
        if p.is_file()
    }
    with pytest.raises(ValueError):
        submit_cp0_addendum(store, requested, "{}", context_sha256=context_hash)
    with pytest.raises(ValueError, match="context"):
        submit_cp0_addendum(store, requested, raw, context_sha256="0" * 64)
    after = {
        p.relative_to(store.directory): p.read_bytes()
        for p in store.directory.rglob("*")
        if p.is_file()
    }
    assert before == after


def production_journal(
    tmp_path: Path, requested: tuple[str, ...] = ("CP-1", "CP-1A", "CP-5")
) -> Execution:
    """Genuine CP-0, all CP-1 stages/promotion, CP-1A and CP-5; original scope omits CP-4."""
    from deploy_vii.business_context import Quote, submit_cp1a_step
    from deploy_vii.contracts import Citation
    from deploy_vii.cp1_quality import cp1_quality_inputs
    from deploy_vii.cp1_workflow import (
        FinancialStage,
        FinancialSubmission,
        cp1_registers,
        promote_cp1,
        submit_cp1_step,
    )
    from deploy_vii.cp5_integrity import review_scope, submit_cp5_step
    from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview
    from deploy_vii.readiness import ConsumerReadiness, ReadinessReview, SourceAssessment
    from deploy_vii.registry import plan
    from tests.product.test_business_context import submission_fixture as business_submission
    from tests.product.test_canonical_gaps import case
    from tests.product.test_cp1_workflow import at_ceiling
    from tests.product.test_cp4_legal import legal_pack
    from tests.product.test_cp5_integrity import review_all
    from tests.product.test_execution import step_text
    from tests.product.test_model_readiness import ready_case
    from tests.product.test_narrative import populated

    pack, context, financial, definition, binding = case(ready_case())
    filing = readiness_fixture()[0].sources[0]
    indenture = legal_pack().sources[1]
    pack = pack.model_copy(
        update={
            "run": pack.run.model_copy(update={"requested_modules": requested}),
            "sources": (*pack.sources, filing, indenture),
        }
    )
    citations = tuple(
        Citation(
            source_id=s.source_id,
            source_sha256=s.sha256,
            locator=s.spans[0].locator,
            quote=s.spans[0].text,
        )
        for s in pack.sources
    )
    context = context.model_copy(
        update={
            "pack_sha256": pack.content_hash(),
            "sources": (
                *context.sources,
                *(
                    context.sources[0].model_copy(
                        update={
                            "source_id": c.source_id,
                            "classification": "nonfinancial",
                            "document_type": "Synthetic text",
                            "scopes": (),
                            "citations": (c,),
                            "event_scan_citations": (c,),
                        }
                    )
                    for c in citations[1:]
                ),
            ),
        }
    )
    financial = financial.model_copy(update={"pack_sha256": pack.content_hash()})
    definition = definition.model_copy(update={"financial_review_sha256": financial.content_hash()})
    binding = binding.model_copy(
        update={
            "financial_review_sha256": financial.content_hash(),
            "source_context_review_sha256": context.content_hash(),
        }
    )
    note = ("Synthetic evidence; no issuer qualification",)
    review = ReadinessReview(
        pack_sha256=pack.content_hash(),
        objective="Synthetic retained pipeline",
        reporting_period="FY2025",
        issuer_confirmed=True,
        sources=tuple(
            SourceAssessment(
                source_id=c.source_id,
                document_family="Synthetic text",
                authority="executed" if c.source_id == "indenture" else "unknown",
                entity="Synthetic",
                period="FY2025",
                version_relationship="Original frozen evidence",
                fidelity="verified",
                citations=(c,),
                limitations=note,
            )
            for c in citations
        ),
        consumers=tuple(
            ConsumerReadiness(
                module_id=m,
                readiness="READY_WITH_LIMITATIONS",
                evidence_demand="Synthetic workflow",
                source_ids=("S1",),
                rationale="Offline protocol check",
                citations=(citations[0],),
                limitations=note,
            )
            for m in plan(pack.run.requested_modules)
            if m != "CP-0"
        ),
        gaps=(),
        analysis=readiness_fixture()[1].analysis,
    )
    store = Execution.create(tmp_path / "journal", pack)
    assert not submit_cp0_review(
        store, store.begin("CP-0").ticket_id, json.dumps(review.model_dump(mode="json"), indent=2)
    ).issues
    ticket = store.begin("CP-1")
    done = submit_cp1_step(store, ticket.ticket_id, "source_context", context.model_dump_json())
    assert not done.issues
    extraction = FinancialSubmission(
        context_step_sha256=done.steps[0].content_hash(),
        financial=financial,
        definition=definition,
        binding=binding,
    )
    done = submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    assert not done.issues
    stage = FinancialStage.model_validate_json(step_text(store, done.steps[-1]))
    done = submit_cp1_step(
        store, ticket.ticket_id, "narrative", populated(stage.narrative_inputs).model_dump_json()
    )
    assert not done.issues
    inputs = DownstreamInputs.model_validate_json(step_text(store, done.steps[-1]))
    done = submit_cp1_step(
        store,
        ticket.ticket_id,
        "readiness",
        DownstreamReview(inputs_sha256=inputs.content_hash()).model_dump_json(),
    )
    assert not done.issues
    quality = cp1_quality_inputs(cp1_registers(store, ticket.ticket_id))
    done = promote_cp1(store, ticket.ticket_id, at_ceiling(quality).model_dump_json())
    assert not done.issues
    if "CP-1A" not in plan(requested):
        return store
    submission = business_submission(pack)
    source = submission.sources[0]
    submission = submission.model_copy(
        update={
            "sources": tuple(
                source.model_copy(
                    update={
                        "source_id": c.source_id,
                        "citations": (
                            Quote(source_id=c.source_id, locator=c.locator, quote=c.quote),
                        ),
                    }
                )
                for c in citations
            )
        }
    )
    done = submit_cp1a_step(
        store, store.begin("CP-1A").ticket_id, "business_context", submission.model_dump_json()
    )
    assert not done.issues
    ticket = store.begin("CP-5")
    done = submit_cp5_step(
        store,
        ticket.ticket_id,
        "integrity_review",
        review_all(review_scope(store, ticket)).model_dump_json(),
    )
    assert not done.issues
    return store


@pytest.fixture(scope="module")
def production(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return production_journal(tmp_path_factory.mktemp("readiness-addendum")).directory


def test_production_cp4_settles_with_legal_tools_and_old_envelope_identity(
    production: Path, tmp_path: Path
) -> None:
    from deploy_vii.cp1_render import read_cp1_envelope, render_cp1_envelope
    from deploy_vii.cp1_workflow import write_cp1_envelope
    from deploy_vii.cp4_legal import submit_cp4_step
    from deploy_vii.cp5_integrity import review_scope, submit_cp5_step
    from deploy_vii.live.context import module_context, readable_sources
    from deploy_vii.live.runner import prompt_inputs
    from deploy_vii.live.tools import PackTools, ToolError
    from tests.product.test_cp4_legal import INDENTURE, submission_fixture
    from tests.product.test_cp5_integrity import review_all

    shutil.copytree(production, tmp_path / "journal")
    store = Execution(tmp_path / "journal")
    before = store.read()
    exported = write_cp1_envelope(store, tmp_path / "before").parent
    files = {p.name: p.read_bytes() for p in exported.iterdir()}
    requested = (*before.run.requested_modules, "CP-4")
    with pytest.raises(ValueError, match="not assessed CP-4"):
        store.extend_scope(requested)
    raw, context_hash = payload(store, requested)
    document = json.loads(raw)
    document["consumers"][0].update(
        evidence_demand="Executed covenant terms and original CP-1 figures",
        rationale="Executed synthetic indenture supports bounded legal interpretation",
        citations=[{"source_id": "indenture", "locator": "line:1", "quote": INDENTURE[0]}],
        limitations=["Synthetic legal source attestation limit"],
    )
    document["gaps"] = [
        {
            "gap_id": "covenant-scope",
            "kind": "scope",
            "severity": "minor",
            "description": "Synthetic covenant scope attestation gap",
            "affected_modules": ["CP-4"],
            "remediation": "Review complete executed amendments",
            "citations": [],
        }
    ]
    raw = json.dumps(document)
    report = submit_cp0_addendum(store, requested, raw, context_sha256=context_hash)
    assert tuple(h.module_id for h in report.staled) == ("CP-5",)
    after = store.read()
    assert after.attempts == before.attempts and after.pack_sha256 == before.pack_sha256
    for module in ("CP-0", "CP-1", "CP-1A"):
        assert next(h for h in after.heads if h.module_id == module) == next(
            h for h in before.heads if h.module_id == module
        )
    ticket = store.begin("CP-4")
    assert ticket.inputs[-1].input_id == "readiness-addendum"
    shown = module_context(store, ticket, "legal_covenants")
    assert shown is not None and shown["source_readiness_addendum"]
    assert prompt_inputs(store, ticket, "legal_covenants").module_context == shown
    assert readable_sources(store, ticket, "legal_covenants") == ("indenture",)
    tools = PackTools(store.pack(), readable_sources(store, ticket, "legal_covenants"))
    assert "indenture" in tools.search_pack({"query": "Leverage"})
    with pytest.raises(ToolError, match="not one of"):
        tools.search_pack({"query": "cash", "source_id": "filing"})
    done = submit_cp4_step(
        store,
        ticket.ticket_id,
        "legal_covenants",
        submission_fixture(blocked=True).model_dump_json(),
    )
    assert not done.issues and done.status == "finished"
    cp4 = store.result(done.result_sha256 or "")
    assert "Synthetic legal source attestation limit" in cp4.inherited_limitations
    assert "Synthetic covenant scope attestation gap" in cp4.inherited_limitations
    ticket = store.begin("CP-5")
    done = submit_cp5_step(
        store,
        ticket.ticket_id,
        "integrity_review",
        review_all(review_scope(store, ticket)).model_dump_json(),
    )
    assert not done.issues
    assert set(cp4.inherited_limitations) <= set(
        store.result(done.result_sha256 or "").inherited_limitations
    )
    again = write_cp1_envelope(store, tmp_path / "after").parent
    assert {p.name: p.read_bytes() for p in exported.iterdir()} == files
    assert {p.name: p.read_bytes() for p in again.iterdir() if p.name != "complete.json"} == {
        name: raw for name, raw in files.items() if name != "complete.json"
    }
    old_receipt = json.loads(files["complete.json"])
    new_receipt = json.loads((again / "complete.json").read_text())
    assert {k: v for k, v in old_receipt.items() if k != "snapshot_sha256"} == {
        k: v for k, v in new_receipt.items() if k != "snapshot_sha256"
    }
    assert read_cp1_envelope(store, exported) == read_cp1_envelope(store, again)
    assert render_cp1_envelope(store, again, tmp_path / "page")["envelope"] == "verified"


@pytest.fixture(scope="module")
def original(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return journal(tmp_path_factory.mktemp("original-readiness")).directory


@pytest.fixture
def original_store(original: Path, tmp_path: Path) -> Execution:
    shutil.copytree(original, tmp_path / "journal")
    return Execution(tmp_path / "journal")


def retained_files(store: Execution) -> dict[str, bytes]:
    return {
        str(p.relative_to(store.directory)): p.read_bytes()
        for p in store.directory.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "extra",
        "alias",
        "closure",
        "quote",
        "locator",
        "source",
        "ready-limit",
        "empty-limits",
        "duplicate-gap",
        "old-gap",
        "empty-analysis",
        "source-override",
    ],
)
def test_bad_addenda_fail_closed_without_writing(original_store: Execution, mutation: str) -> None:
    store = original_store
    requested = ("CP-1", "CP-2") if mutation == "closure" else ("CP-1", "CP-4")
    raw, context_hash = payload(store, requested)
    doc = json.loads(raw)
    row = doc["consumers"][0]
    if mutation == "missing":
        doc["consumers"] = []
    elif mutation in {"duplicate", "extra"}:
        doc["consumers"].append(
            {**row, "module_id": row["module_id"] if mutation == "duplicate" else "CP-3"}
        )
    elif mutation == "alias":
        row["module_id"] = "CP-PARSE"
    elif mutation == "closure":
        doc["consumers"] = [c for c in doc["consumers"] if c["module_id"] != "CP-1A"]
    elif mutation in {"quote", "locator", "source"}:
        row["citations"][0][
            {"quote": "quote", "locator": "locator", "source": "source_id"}[mutation]
        ] = "invented"
    elif mutation == "ready-limit":
        row.update(readiness="READY", limitations=[])
    elif mutation == "empty-limits":
        row["limitations"] = []
    elif mutation in {"duplicate-gap", "old-gap"}:
        gap = {
            "gap_id": "new-gap",
            "kind": "source",
            "severity": "material",
            "description": "Synthetic gap",
            "affected_modules": ["CP-1" if mutation == "old-gap" else "CP-4"],
            "remediation": "Supply evidence",
            "citations": [],
        }
        doc["gaps"] = [gap, gap] if mutation == "duplicate-gap" else [gap]
    elif mutation == "empty-analysis":
        doc["analysis"] = []
    else:
        doc["sources"] = []
    before = retained_files(store)
    with pytest.raises(InvalidReadinessAddendum):
        submit_cp0_addendum(store, requested, json.dumps(doc), context_sha256=context_hash)
    assert retained_files(store) == before


@pytest.mark.parametrize(
    "requested,match",
    [
        (("CP-1", "CP-99"), "Unknown r14 entry"),
        (("CP-4",), "Scope only extends"),
    ],
)
def test_addendum_preserves_refusal_order(
    original_store: Execution, requested: tuple[str, ...], match: str
) -> None:
    store = original_store
    before = retained_files(store)
    with pytest.raises(ValueError, match=match):
        submit_cp0_addendum(store, requested, "{}", context_sha256="malformed")
    assert retained_files(store) == before
    report = submit_cp0_addendum(store, ("CP-1",), "{}", context_sha256="malformed")
    assert not report.extended and retained_files(store) == before
    store.begin("CP-1")
    before = retained_files(store)
    with pytest.raises(ValueError, match="attempt is pending"):
        submit_cp0_addendum(store, requested, "{}", context_sha256="malformed")
    assert retained_files(store) == before


@pytest.mark.parametrize(
    "state",
    [
        "missing-attempt",
        "bad-output",
        "step-inputs",
        "stale",
        "blocked",
        "head-cache",
        "pack-change",
        "head-change",
    ],
)
def test_original_cp0_provenance_and_current_context_are_required(
    original_store: Execution, state: str
) -> None:
    store = original_store
    raw, context_hash = payload(store, ("CP-1", "CP-4"))
    snapshot = store.read()
    head = snapshot.heads[0]
    if state == "missing-attempt":
        snapshot = snapshot.model_copy(update={"attempts": ()})
    elif state in {"bad-output", "step-inputs"}:
        attempt = snapshot.attempts[0]
        update = {"output_sha256": store._store("{}")} if state == "bad-output" else {"inputs": ()}
        step = attempt.steps[0].model_copy(update=update)
        snapshot = snapshot.model_copy(
            update={"attempts": (attempt.model_copy(update={"steps": (step,)}),)}
        )
    elif state in {"stale", "blocked"}:
        snapshot = snapshot.model_copy(
            update={"heads": (head.model_copy(update={"status": state}),)}
        )
    elif state == "head-cache":
        snapshot = snapshot.model_copy(
            update={"heads": (head.model_copy(update={"commands": ()}),)}
        )
    elif state == "pack-change":
        pack = store.pack().model_copy(update={"sources": ()})
        store.replace_pack(pack)
        snapshot = store.read()
    else:
        snapshot = snapshot.model_copy(
            update={"heads": (head.model_copy(update={"result_sha256": "f" * 64}),)}
        )
    store._write(snapshot)
    before = retained_files(store)
    with pytest.raises(ValueError):
        submit_cp0_addendum(store, ("CP-1", "CP-4"), raw, context_sha256=context_hash)
    assert retained_files(store) == before


@pytest.mark.parametrize("status", ["BLOCKED", "CONDITIONAL"])
def test_assessed_nonrunnable_extension_still_refuses_begin(
    production: Path, tmp_path: Path, status: str
) -> None:
    from deploy_vii.execution import NotAuthorized

    shutil.copytree(production, tmp_path / "journal")
    store = Execution(tmp_path / "journal")
    requested = (*store.read().run.requested_modules, "CP-4")
    raw, digest = payload(store, requested)
    doc = json.loads(raw)
    doc["consumers"][0].update(readiness=status, missing_source="Executed amendment")
    assert submit_cp0_addendum(store, requested, json.dumps(doc), context_sha256=digest).extended
    with pytest.raises(NotAuthorized):
        store.begin("CP-4")


def test_later_disjoint_grant_preserves_existing_consumer_input(
    production: Path, tmp_path: Path
) -> None:
    shutil.copytree(production, tmp_path / "journal")
    store = Execution(tmp_path / "journal")
    requested = (*store.read().run.requested_modules, "CP-4")
    raw, digest = payload(store, requested)
    first = submit_cp0_addendum(store, requested, raw, context_sha256=digest)
    inputs = current_inputs(store.read(), "CP-4")
    requested = (*requested, "CP-2")
    raw, digest = payload(store, requested)
    second = submit_cp0_addendum(store, requested, raw, context_sha256=digest)
    assert first.readiness_addendum_sha256 != second.readiness_addendum_sha256
    assert current_inputs(store.read(), "CP-4") == inputs
    assert current_inputs(store.read(), "CP-2")[-1].sha256 == second.readiness_addendum_sha256
    before = retained_files(store)
    assert not submit_cp0_addendum(store, requested, "{}", context_sha256="malformed").extended
    assert retained_files(store) == before


@pytest.mark.parametrize("corruption", ["missing", "bytes", "raw", "context", "cache"])
def test_grant_corruption_fails_closed_on_reopen(
    original_store: Execution, corruption: str
) -> None:
    store = original_store
    raw, digest = payload(store, ("CP-1", "CP-4"))
    submit_cp0_addendum(store, ("CP-1", "CP-4"), raw, context_sha256=digest)
    snapshot = store.read()
    ref = snapshot.readiness_addenda[0]
    addendum = store.readiness_addendum(ref)
    digest = ref.sha256
    if corruption == "cache":
        grant = ref.grants[0].model_copy(update={"limitations": ("Forged restriction",)})
        ref = ref.model_copy(update={"grants": (grant,)})
        store._write(snapshot.model_copy(update={"readiness_addenda": (ref,)}))
    else:
        digest = (
            addendum.payload_sha256
            if corruption == "raw"
            else addendum.context.content_hash()
            if corruption == "context"
            else digest
        )
        blob = store.directory / "blobs" / digest
        if corruption == "bytes":
            blob.write_text("{}")
        else:
            blob.unlink()
    with pytest.raises(ValueError):
        Execution(store.directory).read()


def test_interrupted_pointer_write_never_publishes_scope_without_attestation(
    original_store: Execution, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deploy_vii.execution as execution

    store = original_store
    raw, digest = payload(store, ("CP-1", "CP-4"))
    before = store.read()
    atomic = execution._atomic_write

    def interrupt(path: Path, raw: bytes) -> None:
        if path.name == "current":
            raise OSError("Synthetic interrupted pointer write")
        atomic(path, raw)

    monkeypatch.setattr(execution, "_atomic_write", interrupt)
    with pytest.raises(OSError, match="Synthetic interrupted"):
        submit_cp0_addendum(store, ("CP-1", "CP-4"), raw, context_sha256=digest)
    assert Execution(store.directory).read() == before
    monkeypatch.setattr(execution, "_atomic_write", atomic)
    assert submit_cp0_addendum(store, ("CP-1", "CP-4"), raw, context_sha256=digest).extended
    assert Execution(store.directory).read().readiness_addenda


@given(
    st.sampled_from(["READY", "READY_WITH_LIMITATIONS", "CONDITIONAL", "BLOCKED"]),
    st.booleans(),
    st.booleans(),
)
def test_composed_assessment_agrees_with_shared_validator(
    status: str, cite: bool, gap: bool
) -> None:
    """Differential: immutable pack, same full review, shared exact-set evidence rules."""
    from deploy_vii.cp0_workflow import _check_addendum
    from deploy_vii.live.submission import compose_addendum
    from deploy_vii.readiness import ReadinessAddendumContext, _validate_review_for, validate_review

    pack, original = readiness_fixture()
    pack = pack.model_copy(
        update={"run": pack.run.model_copy(update={"requested_modules": ("CP-1",)})}
    )
    original = original.model_copy(
        update={
            "pack_sha256": pack.content_hash(),
            "consumers": tuple(c for c in original.consumers if c.module_id == "CP-1"),
            "gaps": (),
        }
    )
    context = ReadinessAddendumContext(
        pack_sha256=pack.content_hash(),
        cp0_result_sha256="0" * 64,
        base_requested_modules=("CP-1",),
        target_requested_modules=("CP-1", "CP-4"),
        added_modules=("CP-4",),
        original_review=original,
    )
    template = as_submission(original)
    consumer = template.consumers[0].model_copy(
        update={
            "module_id": "CP-4",
            "readiness": status,
            "missing_source": "Executed amendment" if status == "CONDITIONAL" else None,
            "citations": template.consumers[0].citations if cite else (),
        }
    )
    raw = json.dumps(
        {
            "consumers": [consumer.model_dump(mode="json")],
            "gaps": [
                {
                    "gap_id": "new",
                    "kind": "scope",
                    "severity": "minor",
                    "description": "Synthetic coverage limit",
                    "affected_modules": ["CP-4"],
                    "remediation": "Review full evidence",
                    "citations": [],
                }
            ]
            if gap
            else [],
            "analysis": [c.model_dump(mode="json") for c in template.analysis],
        }
    )
    composed = compose_addendum(pack, context, raw)
    assert composed.review is not None
    expected = _validate_review_for(pack, composed.review, ("CP-1", "CP-4"))
    # The public CP-0 validator never broadens the immutable original scope.
    assert "Assess each selected canonical live consumer exactly once" in validate_review(
        pack, composed.review
    )
    try:
        accepted = _check_addendum(pack, context, raw)
    except InvalidReadinessAddendum as rejected:
        assert rejected.issues == expected
    else:
        assert not expected and accepted.consumers[0].module_id == "CP-4"
    assert _validate_review_for(pack, original, ("CP-1",)) == validate_review(pack, original)


def test_public_readiness_validator_preserves_shape_error_before_scope_resolution() -> None:
    from deploy_vii.readiness import _validate_review_for, validate_review

    pack, review = readiness_fixture()
    malformed = pack.model_copy(update={"run": None})
    assert (
        validate_review(malformed, review)
        == _validate_review_for(malformed, review, ())
        == ("run: Input should be an object",)
    )


def test_addendum_instructions_refuse_pack_drift_after_context(original_store: Execution) -> None:
    from deploy_vii.live.prompts import readiness_addendum_instructions

    context = cp0_addendum_context(original_store, ("CP-1", "CP-4"))
    changed = original_store.pack().model_copy(update={"sources": ()})
    with pytest.raises(ValueError, match="context pack changed"):
        readiness_addendum_instructions(changed, context)


@settings(max_examples=6, deadline=None)
@given(st.permutations(("CP-1", "CP-1A", "CP-5", "CP-OS")))
def test_no_addendum_keeps_real_inputs_and_old_bytes(
    production: Path, order: tuple[str, ...]
) -> None:
    """Generated M9 differential against the old non-consumer extension invariants."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "journal"
        shutil.copytree(production, path)
        store = Execution(path)
        before = store.read()
        old_inputs = {h.module_id: current_inputs(before, h.module_id) for h in before.heads}
        report = store.extend_scope(order)
        after = store.read()
        assert report.added == ("CP-OS",) and not report.staled
        assert after.heads == before.heads and after.attempts == before.attempts
        assert after.pack_sha256 == before.pack_sha256
        assert all(current_inputs(after, m) == inputs for m, inputs in old_inputs.items())
        assert "readiness_addenda" not in after.model_dump(mode="json")
        assert "readiness_addendum_sha256" not in report.model_dump(mode="json")
        assert not store.extend_scope(order).extended
        alias = store.extend_scope((*order, "CP-PARSE"))
        assert alias.extended and alias.added == () and alias.staled == ()
        assert not store.extend_scope((*order, "CP-PARSE")).extended


def test_cli_addendum_context_import_rejection_and_refusal(
    original_store: Execution,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tests.product.test_module_submits import Cli

    store = original_store
    cli = Cli(store, monkeypatch, capsys)
    code, out, err = cli("cp0-addendum-context", "CP-1", "CP-4")
    shown = json.loads(out)
    assert code == 0 and not err and shown["context"]["added_modules"] == ["CP-4"]
    assert set(shown["schema"]["properties"]) == {"consumers", "gaps", "analysis"}
    file = tmp_path / "addendum.json"
    raw, digest = payload(store, ("CP-1", "CP-4"))
    assert digest == shown["context_sha256"]
    before = retained_files(store)
    code, out, err = cli(
        "extend-scope",
        "CP-1",
        "CP-4",
        "--readiness-addendum",
        str(file),
        "--context-sha256",
        digest,
    )
    assert code == 2 and not out and "no review file" in err
    assert retained_files(store) == before
    file.write_text("{}")
    code, out, err = cli(
        "extend-scope",
        "CP-1",
        "CP-4",
        "--readiness-addendum",
        str(file),
        "--context-sha256",
        digest,
    )
    assert code == 1 and json.loads(out)["issues"] and err
    assert retained_files(store) == before
    file.write_text(raw)
    code, out, err = cli(
        "extend-scope",
        "CP-1",
        "CP-4",
        "--readiness-addendum",
        str(file),
        "--context-sha256",
        "0" * 64,
    )
    assert code == 2 and not out and "context changed" in err
    assert retained_files(store) == before
    code, out, err = cli(
        "extend-scope",
        "CP-1",
        "CP-4",
        "--readiness-addendum",
        str(file),
        "--context-sha256",
        digest,
    )
    assert code == 0 and not err and json.loads(out)["readiness_addendum_sha256"]


def test_addendum_cannot_override_an_original_blocked_row(original_store: Execution) -> None:
    from deploy_vii.execution import NotAuthorized, readiness_command

    store = original_store
    snapshot = store.read()
    review = cp0_addendum_context(store, ("CP-1", "CP-4")).original_review
    review = review.model_copy(
        update={
            "consumers": tuple(
                c.model_copy(update={"readiness": "BLOCKED"}) for c in review.consumers
            )
        }
    )
    other = Execution.create(store.directory.parent / "blocked", store.pack())
    assert not submit_cp0_review(
        other, other.begin("CP-0").ticket_id, review.model_dump_json()
    ).issues
    raw, digest = payload(other, ("CP-1", "CP-4"))
    submit_cp0_addendum(other, ("CP-1", "CP-4"), raw, context_sha256=digest)
    assert readiness_command(other.read(), "CP-1")[0] == ("DO NOT RUN",)
    with pytest.raises(NotAuthorized):
        current_inputs(other.read(), "CP-1")
    assert store.read() == snapshot


def test_ambiguous_or_revoked_grants_never_authorize(production: Path, tmp_path: Path) -> None:
    from deploy_vii.execution import NotAuthorized, readiness_command

    shutil.copytree(production, tmp_path / "journal")
    store = Execution(tmp_path / "journal")
    requested = (*store.read().run.requested_modules, "CP-4")
    raw, digest = payload(store, requested)
    submit_cp0_addendum(store, requested, raw, context_sha256=digest)
    snapshot = store.read()
    assert current_inputs(snapshot, "CP-4")[-1].input_id == "readiness-addendum"
    ambiguous = snapshot.model_copy(update={"readiness_addenda": snapshot.readiness_addenda * 2})
    with pytest.raises(ValueError, match="Ambiguous"):
        current_inputs(ambiguous, "CP-4")
    head = next(h for h in snapshot.heads if h.module_id == "CP-0")
    changed = snapshot.model_copy(
        update={
            "heads": tuple(
                h.model_copy(update={"result_sha256": "0" * 64}) if h == head else h
                for h in snapshot.heads
            )
        }
    )
    with pytest.raises(NotAuthorized):
        current_inputs(changed, "CP-4")
    assert readiness_command(changed, "CP-4")[0] == ()
    pack = store.pack().model_copy(update={"sources": store.pack().sources[:-1]})
    store.replace_pack(pack)
    assert readiness_command(store.read(), "CP-4")[0] == ()


def test_ready_grant_binds_accepted_input_and_begins(original_store: Execution) -> None:
    store = original_store
    review = cp0_addendum_context(store, ("CP-1", "CP-1A")).original_review
    review = review.model_copy(
        update={
            "sources": tuple(
                s.model_copy(update={"authority": "issuer", "limitations": ()})
                for s in review.sources
            ),
            "consumers": tuple(
                c.model_copy(update={"readiness": "READY", "limitations": ()})
                for c in review.consumers
            ),
        }
    )
    ready = Execution.create(store.directory.parent / "ready", store.pack())
    assert not submit_cp0_review(
        ready, ready.begin("CP-0").ticket_id, review.model_dump_json()
    ).issues
    raw, digest = payload(ready, ("CP-1", "CP-1A"))
    doc = json.loads(raw)
    doc["consumers"][0].update(readiness="READY", limitations=[])
    submit_cp0_addendum(ready, ("CP-1", "CP-1A"), json.dumps(doc), context_sha256=digest)
    attempt = ready.begin("CP-1A")
    assert (
        attempt.inputs[-1].input_id == "readiness-addendum"
        and attempt.inputs[-1].status == "accepted"
    )


@pytest.mark.parametrize("readiness", ["BLOCKED", "CONDITIONAL", "READY_WITH_LIMITATIONS"])
@pytest.mark.parametrize("mutation", ["insert", "remove", "replace", "inputs", "status"])
@pytest.mark.parametrize("access", ["read", "direct", "begin", "host", "runner", "instructions"])
@pytest.mark.parametrize("remove_refs", [False, True])
def test_current_cp0_cache_cannot_override_genuine_grant(
    original_store: Execution, readiness: str, mutation: str, access: str, remove_refs: bool
) -> None:
    from deploy_vii.execution import Command, NotAuthorized
    from deploy_vii.live.runner import prompt_inputs
    from deploy_vii.module_submits import host_context, step_instructions

    store = original_store
    requested = ("CP-1", "CP-1A")
    raw, digest = payload(store, requested)
    document = json.loads(raw)
    limitation = "Do not run without resolving the synthetic source gap"
    document["consumers"][0].update(
        readiness=readiness, missing_source="Required synthetic source", limitations=[limitation]
    )
    submit_cp0_addendum(store, requested, json.dumps(document), context_sha256=digest)
    snapshot = store.read()
    ref = snapshot.readiness_addenda[0]
    assert store.readiness_addendum(ref).consumers[0].readiness == readiness
    attempt = None
    if readiness == "READY_WITH_LIMITATIONS":
        attempt = store.begin("CP-1A")
        assert attempt.inputs[-1].input_id == "readiness-addendum"
        assert attempt.inputs[-1].sha256 == ref.sha256
        shown = prompt_inputs(store, attempt, "business_context").module_context
        assert shown is not None and limitation in str(shown)
        assert limitation in str(host_context(store, attempt, "business_context"))
        snapshot = store.read()
    else:
        with pytest.raises(NotAuthorized):
            store.begin("CP-1A")
    head = next(h for h in snapshot.heads if h.module_id == "CP-0")
    authentic = store.head_module(head)
    commands = {
        "insert": (*head.commands, Command(row_id="CP-1A", text="Run CP-1A")),
        "remove": (),
        "replace": (Command(row_id="CP-1A", text="Run CP-1A"),),
    }
    update: dict[str, Any] = {"commands": commands[mutation]} if mutation in commands else {}
    if mutation == "inputs":
        update = {"inputs": ()}
    elif mutation == "status":
        update = {"status": "accepted" if head.status != "accepted" else "restricted"}
    forged = head.model_copy(update=update)
    with pytest.raises(ValueError, match=r"Execution head.*result blob"):
        store.head_module(forged)
    store._write(
        snapshot.model_copy(
            update={
                "heads": (forged,),
                "readiness_addenda": () if remove_refs else snapshot.readiness_addenda,
            }
        )
    )
    files = {p: p.read_bytes() for p in store.directory.rglob("*") if p.is_file()}
    reopened = Execution(store.directory)
    refusal = (
        "ref is absent or ambiguous"
        if access == "direct" and remove_refs
        else "Execution head.*result blob"
    )
    with pytest.raises(ValueError, match=refusal):
        if access == "read":
            reopened.read()
        elif access == "direct":
            reopened.readiness_addendum(ref)
        elif access == "begin":
            reopened.begin("CP-1A")
        else:
            # Blocked/conditional grants must refuse before producing a context ticket.
            ticket = attempt if attempt is not None else reopened.begin("CP-1A")
            if access == "host":
                host_context(reopened, ticket, "business_context")
            elif access == "runner":
                prompt_inputs(reopened, ticket, "business_context")
            else:
                step_instructions(
                    reopened, "CP-1A", ticket.ticket_id, "business_context", with_sources=False
                )
    assert {p: p.read_bytes() for p in store.directory.rglob("*") if p.is_file()} == files
    assert reopened.result(head.result_sha256) == authentic


@settings(max_examples=20, deadline=None)
@example(1, [])
@given(
    st.integers(min_value=0, max_value=1),
    st.lists(
        st.tuples(
            st.sampled_from(("CP-1", "CP-1A", "CP-4")),
            st.sampled_from(("Run CP-1", "Run CP-1A", "DO NOT RUN", None)),
        ),
        max_size=3,
    ),
)
def test_current_cp0_authority_equals_retained_producer(
    original: Path, kept: int, additions: list[tuple[str, str | None]]
) -> None:
    """Real journal differential: only exact producer commands may retain grant authority."""
    import tempfile

    from deploy_vii.execution import Command, commands_of

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "journal"
        shutil.copytree(original, path)
        store = Execution(path)
        raw, digest = payload(store, ("CP-1", "CP-1A"))
        submit_cp0_addendum(store, ("CP-1", "CP-1A"), raw, context_sha256=digest)
        snapshot = store.read()
        ref = snapshot.readiness_addenda[0]
        grant = store.readiness_addendum(ref)
        inputs = current_inputs(snapshot, "CP-1A")
        head = snapshot.heads[0]
        original_commands = commands_of(store.result(head.result_sha256))
        changed = head.model_copy(
            update={
                "commands": (
                    *head.commands[:kept],
                    *(Command(row_id=row, text=text) for row, text in additions),
                )
            }
        )
        store._write(snapshot.model_copy(update={"heads": (changed,)}))
        files = {p: p.read_bytes() for p in store.directory.rglob("*") if p.is_file()}
        reopened = Execution(path)
        if changed.commands == original_commands:
            assert current_inputs(reopened.read(), "CP-1A") == inputs
            assert inputs[-1].sha256 == ref.sha256
            assert reopened.readiness_addendum(ref) == grant
        else:
            with pytest.raises(ValueError, match=r"Execution head commands.*result blob"):
                reopened.read()
            with pytest.raises(ValueError, match=r"Execution head commands.*result blob"):
                reopened.readiness_addendum(ref)
            with pytest.raises(ValueError, match=r"Execution head commands.*result blob"):
                reopened.begin("CP-1A")
        assert {p: p.read_bytes() for p in store.directory.rglob("*") if p.is_file()} == files


def test_self_consistent_forged_addendum_cannot_replace_true_cp0_baseline(
    original_store: Execution,
) -> None:
    """Attack fixture: retain genuine CP-0, forge only self-consistent addendum artifacts."""
    from deploy_vii.cp0_workflow import _check_addendum
    from deploy_vii.execution import addendum_ref

    store = original_store
    snapshot = store.read()
    requested = ("CP-1", "CP-1A")
    true_context = cp0_addendum_context(store, requested)
    forged_review = true_context.original_review.model_copy(
        update={
            "sources": tuple(
                s.model_copy(update={"authority": "issuer", "limitations": ()})
                for s in true_context.original_review.sources
            ),
        }
    )
    context = true_context.model_copy(
        update={
            "original_review": forged_review,
            "previous_addenda": ("f" * 64,),
        }
    )
    raw, _ = payload(store, requested)
    document = json.loads(raw)
    document["consumers"][0].update(readiness="READY", limitations=[])
    raw = json.dumps(document)
    forged = _check_addendum(store.pack(), context, raw)
    for value in (raw, context.model_dump_json(), forged.model_dump_json()):
        store._store(value)
    store._write(
        snapshot.model_copy(
            update={
                "run": snapshot.run.model_copy(update={"requested_modules": requested}),
                "readiness_addenda": (addendum_ref(forged),),
            }
        )
    )
    assert context.original_review != true_context.original_review
    assert (
        store.result(snapshot.heads[0].result_sha256).content_hash()
        == snapshot.heads[0].result_sha256
    )
    with pytest.raises(ValueError):
        reopened = Execution(store.directory)
        reopened.read()
        reopened.begin("CP-1A")


def test_removed_prior_addendum_ref_and_blob_cannot_leave_a_runnable_descendant(
    original_store: Execution,
) -> None:
    """Both grants are genuine; deleting prior authority must invalidate the descendant."""
    store = original_store
    requested = ("CP-1", "CP-4")
    raw, digest = payload(store, requested)
    submit_cp0_addendum(store, requested, raw, context_sha256=digest)
    requested = (*requested, "CP-1A")
    raw, digest = payload(store, requested)
    submit_cp0_addendum(store, requested, raw, context_sha256=digest)
    snapshot = store.read()
    prior, descendant = snapshot.readiness_addenda
    retained = store.readiness_addendum(descendant)
    assert retained.context.previous_addenda == (prior.sha256,)
    store._write(snapshot.model_copy(update={"readiness_addenda": (descendant,)}))
    (store.directory / "blobs" / prior.sha256).unlink()
    with pytest.raises(ValueError):
        reopened = Execution(store.directory)
        reopened.read()
        reopened.begin("CP-1A")


@pytest.mark.parametrize(
    "mutation",
    [
        "baseline",
        "missing-prior",
        "duplicate-prior",
        "forward-prior",
        "cyclic-prior",
        "consumer-projection",
        "gap-projection",
        "analysis-projection",
        "scope",
        "closure",
        "duplicate-ref",
        "reverse-refs",
        "producer-blob",
        "producer-payload",
        "ambiguous-producer",
        "missing-producer",
    ],
)
def test_read_use_authenticates_every_historical_authority_projection(
    original_store: Execution,
    mutation: str,
) -> None:
    from deploy_vii.execution import addendum_ref

    store = original_store
    requested = ("CP-1", "CP-4")
    raw, digest = payload(store, requested)
    document = json.loads(raw)
    document["gaps"] = [
        {
            "gap_id": "first-gap",
            "kind": "scope",
            "severity": "minor",
            "description": "Synthetic first-grant scope limit",
            "affected_modules": ["CP-4"],
            "remediation": "Review full covenant evidence",
            "citations": [],
        }
    ]
    submit_cp0_addendum(store, requested, json.dumps(document), context_sha256=digest)
    requested = (*requested, "CP-1A")
    raw, digest = payload(store, requested)
    submit_cp0_addendum(store, requested, raw, context_sha256=digest)
    snapshot = store.read()
    prior, descendant = snapshot.readiness_addenda
    retained = store.readiness_addendum(descendant)
    context = retained.context
    queried = descendant
    if mutation == "duplicate-ref":
        store._write(
            snapshot.model_copy(
                update={"readiness_addenda": (*snapshot.readiness_addenda, descendant)}
            )
        )
    elif mutation == "reverse-refs":
        store._write(snapshot.model_copy(update={"readiness_addenda": (descendant, prior)}))
    elif mutation in {"producer-blob", "producer-payload"}:
        digest = (
            context.cp0_result_sha256
            if mutation == "producer-blob"
            else snapshot.attempts[0].steps[0].payload_sha256
        )
        (store.directory / "blobs" / digest).unlink()
    elif mutation in {"ambiguous-producer", "missing-producer"}:
        attempts = (
            (*snapshot.attempts, snapshot.attempts[0]) if mutation == "ambiguous-producer" else ()
        )
        store._write(snapshot.model_copy(update={"attempts": attempts}))
    else:
        if mutation == "baseline":
            context = context.model_copy(
                update={
                    "original_review": context.original_review.model_copy(
                        update={"objective": "Forged baseline objective"}
                    )
                }
            )
        elif mutation in {"missing-prior", "duplicate-prior", "forward-prior", "cyclic-prior"}:
            hashes = (
                ()
                if mutation == "missing-prior"
                else (prior.sha256, prior.sha256)
                if mutation == "duplicate-prior"
                else (descendant.sha256, prior.sha256, descendant.sha256)
                if mutation == "cyclic-prior"
                else (descendant.sha256,)
            )
            context = context.model_copy(update={"previous_addenda": hashes})
        elif mutation == "consumer-projection":
            context = context.model_copy(
                update={
                    "prior_consumers": tuple(
                        c.model_copy(update={"rationale": "Forged prior rationale"})
                        for c in context.prior_consumers
                    )
                }
            )
        elif mutation == "gap-projection":
            context = context.model_copy(
                update={
                    "prior_gaps": tuple(
                        g.model_copy(update={"description": "Forged prior gap"})
                        for g in context.prior_gaps
                    )
                }
            )
        elif mutation == "analysis-projection":
            context = context.model_copy(
                update={
                    "prior_analysis": tuple(
                        c.model_copy(update={"text": "Forged prior analytical judgment"})
                        for c in context.prior_analysis
                    )
                }
            )
        elif mutation == "scope":
            context = context.model_copy(
                update={"base_requested_modules": ("CP-1", "CP-4", "CP-1A")}
            )
        else:
            context = context.model_copy(update={"added_modules": ("CP-1A", "CP-0")})
        forged = retained.model_copy(update={"context": context})
        store._store(context.model_dump_json())
        store._store(forged.model_dump_json())
        queried = addendum_ref(forged)
        store._write(snapshot.model_copy(update={"readiness_addenda": (prior, queried)}))
    with pytest.raises(ValueError):
        Execution(store.directory).read()
    with pytest.raises(ValueError):
        Execution(store.directory).readiness_addendum(queried)


@settings(max_examples=4, deadline=None)
@given(st.permutations(("CP-4", "CP-1A")), st.booleans())
def test_historical_grants_remain_readable_after_real_pack_and_cp0_refresh(
    original: Path,
    order: tuple[str, ...],
    full_scope: bool,
) -> None:
    import tempfile

    from deploy_vii.execution import NotAuthorized
    from deploy_vii.readiness import NOT_CONSUMERS
    from deploy_vii.registry import plan

    with tempfile.TemporaryDirectory() as directory:
        shutil.copytree(original, Path(directory) / "journal")
        store = Execution(Path(directory) / "journal")
        requested = store.read().run.requested_modules
        for module in order:
            requested = (*requested, module)
            raw, digest = payload(store, requested)
            submit_cp0_addendum(store, requested, raw, context_sha256=digest)
        before = store.read()
        old = {ref.sha256: store.readiness_addendum(ref) for ref in before.readiness_addenda}
        old_bytes = {p: p.read_bytes() for p in (store.directory / "blobs").iterdir()}
        original_review = next(iter(old.values())).context.original_review
        pack = store.pack()
        refreshed = pack.model_copy(
            update={
                "run": before.run if full_scope else pack.run,
                "sources": tuple(
                    s.model_copy(update={"name": "Refreshed synthetic source metadata"})
                    for s in pack.sources
                ),
            }
        )
        store.replace_pack(refreshed)
        reopened = Execution(store.directory)
        assert reopened.read().readiness_addenda == before.readiness_addenda
        assert all(
            reopened.readiness_addendum(ref) == old[ref.sha256] for ref in before.readiness_addenda
        )
        review = original_review.model_copy(
            update={
                "pack_sha256": refreshed.content_hash(),
                "consumers": tuple(
                    original_review.consumers[0].model_copy(update={"module_id": m})
                    for m in plan(refreshed.run.requested_modules)
                    if m not in NOT_CONSUMERS
                ),
            }
        )
        done = submit_cp0_review(
            reopened,
            reopened.begin("CP-0").ticket_id,
            json.dumps(review.model_dump(mode="json"), indent=2),
        )
        assert not done.issues
        current = reopened.read()
        assert all(
            reopened.readiness_addendum(ref) == old[ref.sha256] for ref in before.readiness_addenda
        )
        assert all(p.read_bytes() == raw for p, raw in old_bytes.items())
        if full_scope:
            assert all(i.input_id != "readiness-addendum" for i in current_inputs(current, "CP-1A"))
            next_scope = (*requested, "CP-2")
            context = cp0_addendum_context(reopened, next_scope)
            assert context.previous_addenda == () and context.prior_consumers == ()
            raw, digest = payload(reopened, next_scope)
            submit_cp0_addendum(reopened, next_scope, raw, context_sha256=digest)
            assert len(reopened.read().readiness_addenda) == 3
        else:
            with pytest.raises(NotAuthorized):
                current_inputs(current, "CP-1A")
