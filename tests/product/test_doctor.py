import sys
import tempfile
from pathlib import Path
from typing import Never

import pytest
from hypothesis import given
from hypothesis import strategies as st

from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.delivery_dir import delivery_root, run_paths
from deploy_vii.doctor import checks, render
from deploy_vii.execution import Attempt, Execution, StepValidation
from deploy_vii.preparation import PreparationRequest, PreparedPack, SourceRequest
from tests.product.test_execution import fixture_store
from tests.product.test_readiness import readiness_fixture


def test_doctor_reports_runtime_environment_and_resolved_delivery_root(tmp_path: Path) -> None:
    items = checks(out=tmp_path / "out")
    statuses = {item["name"]: item["status"] for item in items}
    assert statuses["python"] == "ok"
    assert statuses["import-pypdf"] == "ok"
    assert statuses["git-runtime"] == "skip"
    output, code = render(out=tmp_path / "out")
    assert code == 0
    assert str((tmp_path / "out").resolve()) in output


def test_delivery_root_prefers_flag_over_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEPLOY_VII_OUT", str(tmp_path / "environment"))
    explicit = tmp_path / "explicit"
    assert delivery_root(explicit) == explicit.resolve()
    assert delivery_root() == (tmp_path / "environment").resolve()


def test_doctor_validates_request_and_reports_bad_json(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    items = checks(request=request, out=tmp_path / "out")
    assert next(item for item in items if item["name"] == "request")["status"] == "FAIL"


def test_doctor_reports_unreadable_input_as_a_named_failure(tmp_path: Path) -> None:
    directory = tmp_path / "bad.xlsx"
    directory.mkdir()
    items = checks(inputs=(directory,), out=tmp_path / "out")
    failure = next(item for item in items if item["name"] == "input-bad.xlsx")
    assert failure["status"] == "FAIL"
    assert "validate-input" in failure["fix"]


def test_doctor_reports_source_only_checks_as_skipped_for_installed_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deploy_vii.doctor as doctor

    wheel_root = tmp_path / "site-packages/deploy_vii"
    wheel_root.mkdir(parents=True)
    monkeypatch.setattr(doctor, "__file__", str(wheel_root / "doctor.py"))
    monkeypatch.setattr(doctor, "metadata", lambda _name: {"Requires-Python": ">=3.13,<3.14"})
    items = doctor.checks(out=tmp_path / "out")
    statuses = {item["name"]: item["status"] for item in items}
    assert statuses["python"] == "ok"
    assert statuses["uv-lock-present"] == "skip"
    assert statuses["skill"] == "skip"


def test_run_paths_reject_traversal_and_symlink(tmp_path: Path) -> None:
    for run_id in ("../escape", ".", "a/b"):
        try:
            run_paths(tmp_path, run_id)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted unsafe run id {run_id}")
    (tmp_path / "linked").symlink_to(tmp_path / "target")
    try:
        run_paths(tmp_path, "linked")
    except ValueError:
        pass
    else:
        raise AssertionError("accepted symlink run directory")


def test_run_command_returns_refusal_for_traversal_without_creating_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    out = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy-vii",
            "--out",
            str(out),
            "run",
            "--request",
            "missing",
            "--root",
            "missing",
            "--run",
            "../escape",
        ],
    )
    with pytest.raises(SystemExit) as refused:
        main()
    assert refused.value.code == 2
    assert "run id" in capsys.readouterr().err
    assert not out.exists()


def test_run_paths_reject_symlink_owned_child_and_do_not_replace_artifacts(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    destination = tmp_path / "existing"
    destination.mkdir()
    (run / "report").symlink_to(destination)
    try:
        run_paths(tmp_path, "run")
    except ValueError:
        pass
    else:
        raise AssertionError("accepted symlink report path")
    marker = destination / "keep.txt"
    marker.write_text("retained", encoding="utf-8")
    assert marker.read_text(encoding="utf-8") == "retained"


@given(st.text())
def test_accepted_run_ids_never_escape_the_delivery_root(run_id: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        try:
            paths = run_paths(root, run_id)
        except ValueError:
            return
        assert all(path.parent == root / run_id for path in paths.values())
        assert all(path.parent.is_relative_to(root) for path in paths.values())


def test_report_open_renders_and_uses_optional_opener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = fixture_store(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy-vii",
            "execution",
            "--directory",
            str(store.directory),
            "report-open",
            "--browser",
        ],
    )
    from deploy_vii.__main__ import main

    main()
    output = capsys.readouterr().out.strip()
    assert Path(output).is_absolute() and Path(output).is_file()
    assert opened == [Path(output).as_uri()]


def test_report_open_refuses_a_symlink_without_touching_its_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = fixture_store(tmp_path)
    target = tmp_path / "external"
    target.mkdir()
    index = target / "index.html"
    index.write_text("keep", encoding="utf-8")
    (store.directory.parent / "report").symlink_to(target)
    monkeypatch.setattr(
        sys,
        "argv",
        ["deploy-vii", "execution", "--directory", str(store.directory), "report-open"],
    )
    from deploy_vii.__main__ import main

    with pytest.raises(SystemExit) as refused:
        main()
    assert refused.value.code == 2
    assert index.read_text(encoding="utf-8") == "keep"
    capsys.readouterr()


def test_prepare_explicit_output_takes_precedence_over_run_derived_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    pack, _ = readiness_fixture()
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "filing.txt").write_text(
        "Synthetic issuer FY2025 cash USD million 0\n", encoding="utf-8"
    )
    request = PreparationRequest(
        run=pack.run,
        sources=(SourceRequest(source_id="filing", path="filing.txt", media_type="text/plain"),),
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    explicit = tmp_path / "explicit-pack"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy-vii",
            "--out",
            str(tmp_path / "out"),
            "prepare",
            "--request",
            str(request_path),
            "--root",
            str(source_root),
            "--run",
            "same-id",
            "--output",
            str(explicit),
        ],
    )
    main()
    capsys.readouterr()
    assert (explicit / "complete.json").is_file()
    assert not (tmp_path / "out/same-id/pack").exists()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy-vii",
            "--out",
            str(tmp_path / "out"),
            "execution",
            "create",
            "--pack",
            str(explicit),
            "--run",
            "same-id",
        ],
    )
    main()
    capsys.readouterr()
    assert (tmp_path / "out/same-id/journal/current").is_file()


def test_run_rejected_review_uses_production_exit_one_and_issue_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    pack, _ = readiness_fixture()
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "filing.txt").write_text(
        "Synthetic issuer FY2025 cash USD million 0\n", encoding="utf-8"
    )
    request = PreparationRequest(
        run=pack.run,
        sources=(SourceRequest(source_id="filing", path="filing.txt", media_type="text/plain"),),
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    reviews = tmp_path / "out/rejected/reviews"
    reviews.mkdir(parents=True)
    (reviews / "CP-0-source_readiness.review.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy-vii",
            "--out",
            str(tmp_path / "out"),
            "run",
            "--request",
            str(request_path),
            "--root",
            str(source_root),
            "--run",
            "rejected",
        ],
    )
    with pytest.raises(SystemExit) as rejected:
        main()
    output, issues = capsys.readouterr()
    assert rejected.value.code == 1
    assert '"status": "finished"' in output
    assert issues.strip()


def test_run_stops_for_cp0_review_and_reuses_the_same_pending_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    pack, readiness = readiness_fixture()
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "filing.txt").write_text(
        "Synthetic issuer FY2025 cash USD million 0\n", encoding="utf-8"
    )
    request = PreparationRequest(
        run=pack.run,
        sources=(SourceRequest(source_id="filing", path="filing.txt", media_type="text/plain"),),
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    argv = [
        "deploy-vii",
        "--out",
        str(tmp_path / "out"),
        "run",
        "--request",
        str(request_path),
        "--root",
        str(source_root),
        "--run",
        "review-case",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 3
    journal = tmp_path / "out/review-case/journal"
    pending = Execution(journal).read().attempts
    assert len(pending) == 1 and pending[0].module_id == "CP-0"
    instruction = tmp_path / "out/review-case/reviews/CP-0-source_readiness.instructions.txt"
    first_text = instruction.read_text(encoding="utf-8")
    assert (
        f"write {tmp_path / 'out/review-case/reviews/CP-0-source_readiness.review.json'} then rerun"
        in capsys.readouterr().err
    )
    instruction.write_text("retain this conflicting file", encoding="utf-8")
    with pytest.raises(SystemExit) as conflict:
        main()
    assert conflict.value.code == 2
    assert instruction.read_text(encoding="utf-8") == "retain this conflicting file"
    instruction.write_text(first_text, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as repeated:
        main()
    assert repeated.value.code == 3
    assert Execution(journal).read().attempts[0].ticket_id == pending[0].ticket_id
    assert instruction.read_text(encoding="utf-8") == first_text
    cp0_review = tmp_path / "out/review-case/reviews/CP-0-source_readiness.review.json"
    cp0_review.write_text(readiness.model_dump_json(), encoding="utf-8")
    with pytest.raises(SystemExit) as next_step:
        main()
    assert next_step.value.code == 3
    cp1 = Execution(journal).read()
    assert [head.module_id for head in cp1.heads] == ["CP-0"]
    assert cp1.attempts[-1].module_id == "CP-1"
    assert "CP-1-source_context.review.json" in capsys.readouterr().err


def test_resume_reports_and_resubmits_the_retained_cp0_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")

    def crash(_pack: PreparedPack, _attempt: Attempt) -> Never:
        raise RuntimeError("simulate interruption during validation")

    with pytest.raises(RuntimeError, match="simulate interruption"):
        store.submit_step(
            ticket.ticket_id, "CP-0", ("source_readiness",), "source_readiness", "{}", crash
        )
    monkeypatch.setattr(
        sys, "argv", ["deploy-vii", "execution", "--directory", str(store.directory), "resume"]
    )
    main()
    status = capsys.readouterr().out
    assert ticket.ticket_id in status and "retained response: yes" in status
    review = tmp_path / "review.json"
    review.write_text("{}", encoding="utf-8")
    linked_review = tmp_path / "linked-review.json"
    linked_review.symlink_to(review)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy-vii",
            "execution",
            "--directory",
            str(store.directory),
            "resume",
            "--ticket",
            ticket.ticket_id,
            "--review",
            str(linked_review),
        ],
    )
    with pytest.raises(SystemExit) as refused:
        main()
    assert refused.value.code == 2
    assert store.read().attempts[0].status == "pending"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy-vii",
            "execution",
            "--directory",
            str(store.directory),
            "resume",
            "--ticket",
            ticket.ticket_id,
            "--review",
            str(review),
        ],
    )
    with pytest.raises(SystemExit) as rejected:
        main()
    assert rejected.value.code == 1
    assert store.read().attempts[0].ticket_id == ticket.ticket_id


def test_resume_sends_cp1_quality_to_the_promotion_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    pack, readiness = readiness_fixture()
    store = Execution.create(tmp_path / "execution", pack)
    cp0 = store.begin("CP-0")
    submit_cp0_review(store, cp0.ticket_id, readiness.model_dump_json())
    cp1 = store.begin("CP-1")

    def accept(_pack: PreparedPack, _attempt: Attempt) -> StepValidation:
        return StepValidation(output="synthetic accepted step")

    for step in ("source_context", "financials", "narrative", "readiness"):
        store.submit_step(
            cp1.ticket_id,
            "CP-1",
            ("source_context", "financials", "narrative", "readiness", "quality"),
            step,
            "{}",
            accept,
        )
    review = tmp_path / "quality.json"
    review.write_text("{}", encoding="utf-8")
    submitted: list[tuple[str, str]] = []

    def promote(_store: Execution, ticket: str, payload: str) -> Attempt:
        submitted.append((ticket, payload))
        return _store.read().attempts[-1]

    monkeypatch.setattr("deploy_vii.execution_cli.promote_cp1", promote)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy-vii",
            "execution",
            "--directory",
            str(store.directory),
            "resume",
            "--ticket",
            cp1.ticket_id,
            "--review",
            str(review),
        ],
    )
    main()
    capsys.readouterr()
    assert submitted == [(cp1.ticket_id, "{}")]


# M11 repair regressions use the real offline workflows, with synthetic evidence only.
def offline_args(tmp_path: Path, store: Execution) -> tuple[object, Execution]:
    import argparse
    import hashlib
    import json
    import shutil

    paths = run_paths(tmp_path / "out", "repair")
    pack = store.pack()
    paths["pack"].mkdir(parents=True)
    originals = paths["pack"] / "originals"
    originals.mkdir()
    for source in pack.sources:
        if source.sha256 is None:
            continue
        text = "\n".join(span.text for span in source.spans)
        raw = next(
            raw
            for raw in (text.encode(), (text + "\n").encode())
            if hashlib.sha256(raw).hexdigest() == source.sha256
        )
        (originals / source.sha256).write_bytes(raw)
    (paths["pack"] / "pack.json").write_text(pack.model_dump_json())
    (paths["pack"] / "complete.json").write_text(json.dumps({"pack_sha256": pack.content_hash()}))
    shutil.copytree(store.directory, paths["journal"])
    request = tmp_path / "request.json"
    request.write_text(PreparationRequest(run=pack.run, sources=()).model_dump_json())
    return argparse.Namespace(
        out=tmp_path / "out",
        run="repair",
        request=request,
        root=tmp_path,
        reviews=None,
        modules=None,
    ), Execution(paths["journal"])


@pytest.mark.parametrize("difference", ["issuer_id", "run_id", "source"])
def test_run_refuses_different_pack_before_any_journal_or_review_mutation(
    tmp_path: Path, difference: str
) -> None:
    import shutil

    from deploy_vii.execution_cli import run_offline

    args, store = offline_args(tmp_path, fixture_store(tmp_path / "fixture"))
    pack = store.pack()
    from deploy_vii.preparation import prepare_source

    other = (
        pack.model_copy(
            update={
                "sources": (
                    prepare_source(
                        SourceRequest(
                            source_id="filing", path="filing.txt", media_type="text/plain"
                        ),
                        b"Different synthetic source\n",
                    ),
                )
            }
        )
        if difference == "source"
        else pack.model_copy(update={"run": pack.run.model_copy(update={difference: "other"})})
    )
    shutil.rmtree(store.directory)
    explicit = Execution.create(store.directory, other)
    before = {
        p.relative_to(store.directory): p.read_bytes()
        for p in store.directory.rglob("*")
        if p.is_file()
    }
    assert explicit.pack().content_hash() != pack.content_hash()
    with pytest.raises(SystemExit) as refused:
        run_offline(args)
    assert refused.value.code == 2
    assert before == {
        p.relative_to(store.directory): p.read_bytes()
        for p in store.directory.rglob("*")
        if p.is_file()
    }
    assert not (store.directory.parent / "reviews").exists()


@pytest.mark.parametrize("module", ["CP-0", "CP-1", "CP-2"])
@pytest.mark.parametrize("phase", ["validation", "settlement"])
def test_run_resumes_exact_retained_response_without_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str, phase: str
) -> None:
    from deploy_vii.cp1_quality import cp1_quality_inputs
    from deploy_vii.cp1_workflow import cp1_registers
    from deploy_vii.execution_cli import run_offline
    from deploy_vii.registry import step_chain
    from tests.product.test_cp1_workflow import at_ceiling, staged
    from tests.product.test_cp2_synthesis import journal, synthesis

    if module == "CP-0":
        initial = fixture_store(tmp_path / "fixture")
        payload = readiness_fixture()[1].model_dump_json()
    elif module == "CP-1":
        initial, ticket = staged(tmp_path / "fixture")
        payload = at_ceiling(
            cp1_quality_inputs(cp1_registers(initial, ticket.ticket_id))
        ).model_dump_json()
    else:
        initial = journal(tmp_path / "fixture")
        payload = synthesis().model_dump_json()
    args, store = offline_args(tmp_path, initial)
    pending = next((a for a in store.read().attempts if a.status == "pending"), None)
    pending = pending or store.begin(module)
    step = step_chain(module).steps[-1]
    reviews = store.directory.parent / "reviews"
    reviews.mkdir()
    review = reviews / f"{module}-{step}.review.json"
    review.write_text(payload)
    original_submit, original_finish = Execution.submit_step, Execution.finish

    def crash(*_args: object, **_kwargs: object) -> Never:
        raise RuntimeError("causal interruption")

    if phase == "validation":

        def interrupted_submit(self: Execution, *values: object, **kwargs: object) -> Attempt:
            return original_submit(self, *values[:-1], crash, **kwargs)

        monkeypatch.setattr(Execution, "submit_step", interrupted_submit)
    else:

        def interrupted_finish(self: Execution, *values: object, **kwargs: object) -> Attempt:
            return original_finish(self, *values[:2], crash, **kwargs)

        monkeypatch.setattr(Execution, "finish", interrupted_finish)
    with pytest.raises(RuntimeError, match="causal interruption"):
        run_offline(args)
    retained = store.read().attempts[-1]
    assert retained.ticket_id == pending.ticket_id and retained.status == "pending"
    import shutil

    explicit_path = tmp_path / "explicit-resume"
    shutil.copytree(store.directory, explicit_path)
    explicit = Execution(explicit_path)
    monkeypatch.setattr(Execution, "submit_step", original_submit)
    monkeypatch.setattr(Execution, "finish", original_finish)
    from deploy_vii import execution_cli

    instructions = execution_cli.step_instructions

    def no_redispatch(store: Execution, module_id: str, *values: str, **kwargs: bool) -> str:
        assert module_id != module, "retained responses must bypass dispatch"
        return instructions(store, module_id, *values, **kwargs)

    monkeypatch.setattr(execution_cli, "step_instructions", no_redispatch)
    # A changed file must be refused without consuming or replacing the retained response.
    review.write_text("{}")
    before = store.read()
    with pytest.raises(SystemExit) as refused:
        run_offline(args)
    assert refused.value.code == 2 and store.read() == before
    review.write_text(payload)
    if module == "CP-0":
        direct = submit_cp0_review(explicit, pending.ticket_id, payload)
    elif module == "CP-1":
        from deploy_vii.cp1_workflow import promote_cp1

        direct = promote_cp1(explicit, pending.ticket_id, payload)
    else:
        from deploy_vii.module_submits import submit_module_step

        direct = submit_module_step(explicit, module, pending.ticket_id, step, payload)
    with pytest.raises(SystemExit) as stopped:
        run_offline(args)
    assert stopped.value.code == 3  # the next real module now needs its review
    finished = next(a for a in store.read().attempts if a.ticket_id == pending.ticket_id)
    assert finished == direct and finished.status == "finished" and not finished.issues
    assert store.payload(finished.steps[-1].payload_sha256) == payload
    assert len([a for a in store.read().attempts if a.module_id == module]) == 1


@pytest.mark.parametrize("module", ["CP-0", "CP-1"])
def test_run_preserves_first_prompt_and_delivers_journal_bound_repair(
    tmp_path: Path, module: str
) -> None:
    from deploy_vii.execution_cli import run_offline
    from tests.product.test_workflow import cp1_case

    if module == "CP-0":
        initial = fixture_store(tmp_path / "fixture")
        payload = readiness_fixture()[1].model_dump_json()
        step = "source_readiness"
    else:
        initial, _ticket, _ = cp1_case(tmp_path / "fixture")
        payload = initial.payload(initial.read().attempts[-1].steps[0].payload_sha256)
        # Recreate from this exact pack, retaining only the production CP-0 result.
        cp0 = initial.read().attempts[0]
        reset = Execution.create(tmp_path / "fresh", initial.pack())
        submit_cp0_review(
            reset, reset.begin("CP-0").ticket_id, initial.payload(cp0.steps[0].payload_sha256)
        )
        initial, step = reset, "source_context"
    args, store = offline_args(tmp_path, initial)
    with pytest.raises(SystemExit) as stopped:
        run_offline(args)
    assert stopped.value.code == 3
    reviews = store.directory.parent / "reviews"
    prompt = reviews / f"{module}-{step}.instructions.txt"
    first = prompt.read_bytes()
    review = reviews / f"{module}-{step}.review.json"
    review.write_text("{}")
    with pytest.raises(SystemExit) as rejected:
        run_offline(args)
    assert rejected.value.code == 1
    review.write_text(payload)
    with pytest.raises(SystemExit) as continued:
        run_offline(args)
    assert continued.value.code == 3
    assert prompt.read_bytes() == first
    repaired = list(reviews.glob(f"{module}-{step}.*.instructions.txt"))
    assert len(repaired) == 1 and b"REPAIR" in repaired[0].read_bytes()
    attempt = next(a for a in reversed(store.read().attempts) if a.module_id == module)
    assert (attempt.number, len(attempt.step_repairs)) == ((1, 0) if module == "CP-0" else (0, 1))


@pytest.mark.parametrize("kind", ["partial", "unrelated", "stale", "symlink", "receipt-symlink"])
@pytest.mark.parametrize("entry", ["run", "report-open"])
def test_report_reuse_refuses_conflicts_without_overwriting(
    tmp_path: Path, kind: str, entry: str
) -> None:
    import argparse

    from deploy_vii.execution_cli import execute, run_offline, write_report

    pack, readiness = readiness_fixture()
    pack = pack.model_copy(
        update={"run": pack.run.model_copy(update={"requested_modules": ("CP-0",)})}
    )
    readiness = readiness.model_copy(
        update={"pack_sha256": pack.content_hash(), "consumers": (), "gaps": ()}
    )
    initial = Execution.create(tmp_path / "fixture", pack)
    args, store = offline_args(tmp_path, initial)
    report = store.directory.parent / "report"
    private = tmp_path / "private.html"
    private.write_text("private retained")
    if kind in {"stale", "receipt-symlink"}:
        write_report(store, pack.run.pathway, report)
        if kind == "receipt-symlink":
            (report / "report.json").unlink()
            (report / "report.json").symlink_to(private)
    else:
        report.mkdir()
        if kind == "symlink":
            (report / "index.html").symlink_to(private)
        else:
            (report / "index.html").write_text("partial" if kind == "partial" else "unrelated")
    submit_cp0_review(store, store.begin("CP-0").ticket_id, readiness.model_dump_json())
    before = {p.name: p.read_bytes() for p in report.iterdir()}
    with pytest.raises(SystemExit) as refused:
        if entry == "run":
            run_offline(args)
        else:
            execute(
                argparse.Namespace(
                    directory=store.directory,
                    run=None,
                    action="report-open",
                    pathway=None,
                    browser=False,
                )
            )
    assert refused.value.code == 2
    assert {p.name: p.read_bytes() for p in report.iterdir()} == before
    assert private.read_text() == "private retained"


@pytest.mark.parametrize("dependency", ["pydantic", "pypdf", "openpyxl"])
def test_doctor_fresh_process_reports_missing_dependencies_as_json(
    tmp_path: Path, dependency: str
) -> None:
    import json
    import subprocess

    script = """
import importlib.abc, runpy, sys
missing = sys.argv[1]
class Missing(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == missing:
            raise ModuleNotFoundError('synthetic missing dependency: ' + fullname)
sys.meta_path.insert(0, Missing())
sys.argv = ['deploy-vii', '--out', sys.argv[2], 'doctor', '--json',
            '--request', 'absent', '--inputs', 'absent.xlsx']
runpy.run_module('deploy_vii', run_name='__main__')
"""
    script = "import sys\nsys.path[:0] = " + repr(sys.path) + "\n" + script
    result = subprocess.run(
        [sys.executable, "-c", script, dependency, str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1 and "Traceback" not in result.stderr
    items = json.loads(result.stdout)["checks"]
    assert (
        next(item for item in items if item["name"] == f"import-{dependency}")["status"] == "FAIL"
    )


def test_default_credit_snapshot_publishes_real_model_and_completes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    import tests.product.test_financials as financials
    import tests.product.test_workflow as workflow
    from deploy_vii.business_context import BusinessContextSubmission
    from deploy_vii.contracts import PATHWAY_MODULES, Run
    from deploy_vii.cp1_quality import cp1_quality_inputs
    from deploy_vii.cp1_workflow import cp1_registers
    from deploy_vii.cp2_synthesis import CreditSynthesisSubmission
    from deploy_vii.cp3_relative_value import RelativeValueSubmission
    from deploy_vii.cp4_legal import CovenantInterpretationSubmission
    from deploy_vii.cp5_integrity import review_scope
    from deploy_vii.cp6_committee import CommitteeSubmission
    from deploy_vii.cp_model_workflow import verify_cp_model_publication
    from deploy_vii.execution_cli import run_offline
    from deploy_vii.registry import plan, step_chain
    from tests.product.test_business_context import submission_fixture
    from tests.product.test_cp1_workflow import at_ceiling, staged
    from tests.product.test_cp5_integrity import review_all

    monkeypatch.setattr(
        financials,
        "Run",
        lambda **kw: Run(**{**kw, "requested_modules": PATHWAY_MODULES["credit_snapshot"]}),
    )
    monkeypatch.setattr(
        workflow, "plan", lambda scope: tuple(m for m in plan(scope) if m != "CP-MODEL")
    )
    initial, ticket = staged(tmp_path / "fixture")
    args, store = offline_args(tmp_path, initial)
    paths = run_paths(args.out, args.run)
    paths["reviews"].mkdir()
    quality = at_ceiling(cp1_quality_inputs(cp1_registers(store, ticket.ticket_id)))
    (paths["reviews"] / "CP-1-quality.review.json").write_text(quality.model_dump_json())
    # Gap judgments keep the synthetic financial fixture's absent business/market evidence explicit.
    business = submission_fixture(store.pack()).model_dump(mode="json")
    source = store.pack().sources[0]

    def bind_quotes(value: object) -> object:
        if isinstance(value, dict):
            if set(value) == {"source_id", "locator", "quote"}:
                return {
                    "source_id": source.source_id,
                    "locator": source.spans[0].locator,
                    "quote": source.spans[0].text,
                }
            return {key: bind_quotes(item) for key, item in value.items()}
        if isinstance(value, list):
            return [bind_quotes(item) for item in value]
        return value

    business["sources"][0]["source_id"] = source.source_id
    business = bind_quotes(business)
    gap = "Synthetic fixture lacks evidence for this judgment"
    submissions = {
        "CP-1A": BusinessContextSubmission.model_validate_json(json.dumps(business)),
        "CP-2": CreditSynthesisSubmission.model_validate_json(
            json.dumps(
                {
                    "assessment": {
                        "rationale": gap,
                        "category": "Insufficient Information",
                        "confidence": "Insufficient Information",
                        "cp1a_refs": [],
                        "limitation": gap,
                    },
                    "thesis": {
                        "text": gap,
                        "category": "Insufficient Information",
                        "cp1a_refs": [],
                        "limitation": gap,
                    },
                    "strengths": [],
                    "weaknesses": [],
                    "key_findings": [],
                    "risks": [],
                    "gaps": [
                        {
                            "gap": gap,
                            "why_it_matters": gap,
                            "affected_analysis": gap,
                            "severity": "Material",
                            "action": "Obtain issuer evidence",
                            "cp1a_refs": ["downstream_readiness.r01"],
                        }
                    ],
                }
            )
        ),
        "CP-4": CovenantInterpretationSubmission.model_validate_json(
            json.dumps(
                {
                    "documents": [],
                    "covenants": [],
                    "capacity": [],
                    "red_flags": [],
                    "gaps": [],
                    "protection_score": {
                        "rating": "Insufficient Information",
                        "rationale": gap,
                        "basis": gap,
                        "citations": [],
                        "limitation": gap,
                    },
                }
            )
        ),
        "CP-3": RelativeValueSubmission.model_validate_json(
            json.dumps(
                {
                    "instruments": [],
                    "market_evidence": [],
                    "risks": [],
                    "gaps": [],
                    "preference": {
                        "ordering": [],
                        "rationale": gap,
                        "basis": {"cp2_refs": [], "quotes": []},
                        "confidence": "Insufficient Information",
                        "limitation": gap,
                    },
                }
            )
        ),
        "CP-6": CommitteeSubmission.model_validate_json(
            json.dumps(
                {
                    "recommendation": {
                        "action_bias": "Insufficient Information",
                        "rationale": gap,
                        "conditions": gap,
                        "confidence": "Insufficient Information",
                        "limitation": gap,
                        "basis": {"cp2_refs": ["T2.1.assessment"], "cp3_refs": [], "cp5_refs": []},
                    },
                    "thesis_challenges": [],
                    "recovery_view": [],
                    "risks": [],
                    "gaps": [],
                }
            )
        ),
    }
    for _ in range(8):
        try:
            index = run_offline(args)
            break
        except SystemExit as stopped:
            assert stopped.code == 3
        pending = next(a for a in store.read().attempts if a.status == "pending")
        assert pending.module_id != "CP-MODEL"
        module = pending.module_id
        supplied = (
            review_all(review_scope(store, pending)) if module == "CP-5" else submissions[module]
        )
        (paths["reviews"] / f"{module}-{step_chain(module).steps[0]}.review.json").write_text(
            supplied.model_dump_json()
        )
    else:
        raise AssertionError("default Credit Snapshot failed to complete")
    assert Path(index) == paths["report"] / "index.html"
    assert verify_cp_model_publication(store, paths["journal"].parent / "cp-model") == ()
    receipt = json.loads((paths["report"] / "report.json").read_text())
    selected = set(PATHWAY_MODULES["credit_snapshot"])
    assert {head.module_id for head in store.read().heads} == selected
    assert all(
        row["status"] in {"accepted", "restricted"}
        for row in receipt["modules"]
        if row["module_id"] in selected
    )
    before = store.read()
    assert run_offline(args) == index and store.read() == before


def test_run_keeps_canonical_pack_binding_after_effective_scope_extension(tmp_path: Path) -> None:
    from deploy_vii.execution_cli import run_offline

    pack, _ = readiness_fixture()
    pack = pack.model_copy(
        update={"run": pack.run.model_copy(update={"requested_modules": ("CP-1",)})}
    )
    initial = Execution.create(tmp_path / "fixture", pack)
    # Adding an already required dependency is a valid administrative extension, with no rebinding.
    initial.extend_scope(("CP-1", "CP-0"))
    args, store = offline_args(tmp_path, initial)
    assert store.pack() == pack
    with pytest.raises(SystemExit) as stopped:
        run_offline(args)
    assert stopped.value.code == 3
    assert store.pack() == pack and store.read().run.requested_modules == ("CP-1", "CP-0")
