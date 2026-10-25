"""The skill-rehearsal harness: command log, cost ledger and acceptance summary."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from devtools import skill_rehearsal as rehearsal

PY = sys.executable


def child(code: str) -> list[str]:
    return [PY, "-c", code]


def lines(directory: Path) -> list[dict[str, object]]:
    text = (directory / "commands.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_run_propagates_exit_code_and_passes_output_through(
    tmp_path: Path, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    code = rehearsal.run_command(
        tmp_path / "r",
        child("import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)"),
    )
    shown = capfdbinary.readouterr()
    assert code == 7
    assert shown.out == b"out\n"
    assert shown.err == b"err\n"


def test_run_logs_one_json_line_with_pins_and_saved_streams(tmp_path: Path) -> None:
    directory = tmp_path / "r"
    argv = child("import sys; print('hello'); print('bad', file=sys.stderr)")
    assert rehearsal.run_command(directory, argv) == 0
    (entry,) = lines(directory)
    assert set(entry) == {
        "seq",
        "utc",
        "argv",
        "exit_code",
        "duration_s",
        "stdout_sha256",
        "stderr_sha256",
        "issues",
    }
    assert entry["seq"] == 1
    assert entry["argv"] == argv
    assert entry["exit_code"] == 0
    assert entry["issues"] == []
    assert entry["stdout_sha256"] == sha(b"hello\n")
    assert entry["stderr_sha256"] == sha(b"bad\n")
    assert (directory / "cmd-001.out").read_bytes() == b"hello\n"
    assert (directory / "cmd-001.err").read_bytes() == b"bad\n"
    meta = json.loads((directory / "rehearsal.json").read_text(encoding="utf-8"))
    assert meta["cohort"] == "proxy-claude"
    assert meta["pooled"] is False
    assert meta["provider"] == "anthropic"
    assert meta["cap_usd"] == "12"
    assert meta["started_utc"].endswith("Z")


def test_second_run_appends_and_keeps_the_start_record(tmp_path: Path) -> None:
    directory = tmp_path / "r"
    rehearsal.run_command(directory, child("pass"))
    started = (directory / "rehearsal.json").read_bytes()
    rehearsal.run_command(directory, child("pass"))
    assert [e["seq"] for e in lines(directory)] == [1, 2]
    assert (directory / "cmd-002.out").exists()
    assert (directory / "rehearsal.json").read_bytes() == started


def test_issues_come_from_the_attempt_json_issues_list(tmp_path: Path) -> None:
    directory = tmp_path / "r"
    payload = json.dumps({"issues": ["a is wrong", "b is missing"]})
    code = rehearsal.run_command(directory, child(f"print({payload!r}); raise SystemExit(1)"))
    assert code == 1
    assert lines(directory)[0]["issues"] == ["a is wrong", "b is missing"]


def test_issues_of_a_pending_attempt_come_from_its_rejected_step(tmp_path: Path) -> None:
    """The CLI's own `issue_lines`: an attempt still pending carries the rejected step's issues."""
    directory = tmp_path / "r"
    payload = json.dumps(
        {
            "status": "pending",
            "issues": [],
            "steps": [
                {"step_id": "s1", "status": "valid", "issues": []},
                {"step_id": "s2", "status": "invalid", "issues": ["s2 fails"]},
            ],
        }
    )
    rehearsal.run_command(directory, child(f"print({payload!r}); raise SystemExit(1)"))
    assert lines(directory)[0]["issues"] == ["s2 fails"]


@pytest.mark.parametrize(
    "stdout",
    ["not json", "[1, 2]", '{"issues": "text"}', '{"other": 1}', '{"issues": [1]}', ""],
)
def test_non_issue_output_gives_empty_issues(tmp_path: Path, stdout: str) -> None:
    directory = tmp_path / "r"
    rehearsal.run_command(directory, child(f"print({stdout!r})"))
    assert lines(directory)[0]["issues"] == []


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT delivery is POSIX")
def test_interrupt_after_sends_sigint_and_marks_the_line(tmp_path: Path) -> None:
    directory = tmp_path / "r"
    code = rehearsal.run_command(
        directory,
        child(
            "import sys, time\n"
            "try:\n"
            "    print('ready', flush=True)\n"
            "    time.sleep(30)\n"
            "except KeyboardInterrupt:\n"
            "    print('caught', flush=True)\n"
            "    sys.exit(130)\n"
        ),
        interrupt_after=1.0,
    )
    assert code == 130
    (entry,) = lines(directory)
    assert entry["interrupted"] is True
    assert entry["exit_code"] == 130
    assert (directory / "cmd-001.out").read_bytes() == b"ready\ncaught\n"
    assert float(str(entry["duration_s"])) < 20


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT delivery is POSIX")
def test_a_child_killed_by_the_signal_reports_the_shell_convention(tmp_path: Path) -> None:
    import signal

    directory = tmp_path / "r"
    code = rehearsal.run_command(
        directory,
        child(
            "import signal, time\n"
            "signal.signal(signal.SIGINT, signal.SIG_DFL)\n"
            "print('ready', flush=True)\n"
            "time.sleep(30)\n"
        ),
        interrupt_after=1.0,
    )
    assert code == 128 + signal.SIGINT
    assert lines(directory)[0]["exit_code"] == 128 + signal.SIGINT


def test_uninterrupted_lines_carry_no_interrupted_key(tmp_path: Path) -> None:
    rehearsal.run_command(tmp_path / "r", child("pass"), interrupt_after=None)
    assert "interrupted" not in lines(tmp_path / "r")[0]


def test_a_directory_of_another_cohort_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "r"
    directory.mkdir()
    (directory / "rehearsal.json").write_text(
        json.dumps({"cohort": "sol", "pooled": True}), encoding="utf-8"
    )
    with pytest.raises(rehearsal.RehearsalError, match="cohort"):
        rehearsal.run_command(directory, child("pass"))
    assert not (directory / "commands.jsonl").exists()


def test_main_run_builds_the_deploy_vii_command_without_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def fake(directory: Path, argv: list[str], interrupt_after: float | None = None) -> int:
        seen.append(argv)
        return 4

    monkeypatch.setattr(rehearsal, "run_command", fake)
    command = ["execution", "--directory", "j; rm", "status"]
    code = rehearsal.main(["run", "--rehearsal", str(tmp_path / "r"), "--", *command])
    assert code == 4
    assert seen[0] == [sys.executable, "-m", "deploy_vii", *command]


def test_main_run_requires_a_command(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stop:
        rehearsal.main(["run", "--rehearsal", str(tmp_path / "r"), "--"])
    assert stop.value.code == 2


def test_main_refuses_a_foreign_cohort_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "r"
    directory.mkdir()
    (directory / "rehearsal.json").write_text(json.dumps({"cohort": "sol"}), encoding="utf-8")
    assert rehearsal.main(["run", "--rehearsal", str(directory), "--", "plan", "CP-0"]) == 2
    assert "cohort" in capsys.readouterr().err
