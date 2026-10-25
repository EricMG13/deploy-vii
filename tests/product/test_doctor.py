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
