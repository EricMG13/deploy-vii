"""Offline context-policy scenarios exercise real Git state, not prose checks."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from devtools.state import checkpoint, validate
from devtools.storage import read_object
from devtools.telemetry import import_events, report


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    (tmp_path / "source.txt").write_text("original\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


@pytest.fixture
def spec(repo: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": "test-task",
        "goal": "Preserve meaning",
        "owner": "session-1",
        "constraints": ["No automatic resets"],
        "corrections": ["Read counterevidence"],
        "routing": {"host": "claude", "model": "fixed", "effort": "high"},
        "budgets": [{"unit": "USD", "cap": 50, "consumed": 4, "reason": None}],
        "paused": False,
        "pending_operations": [],
        "reviews": {"confidence-review": "pending", "rewrite-tournament": "pending"},
        "authorization": "Implement tooling",
        "publication_owner": "coordinator",
        "sources": ["source.txt"],
        "facts": [],
        "hypotheses": ["A summary cannot prove analytical truth"],
        "failed_approaches": [],
        "next_action": "Verify state",
        "context_treatment": {"kind": "native", "input_verified": False},
    }


def capture(repo: Path, spec: dict[str, object]) -> Path:
    return checkpoint(repo, repo / "artifacts/state", spec)


def test_c01_clean_snapshot_is_not_ownership_transfer(repo: Path, spec: dict[str, object]) -> None:
    path = capture(repo, spec)
    result = validate(repo, read_object(path), spec)
    assert result["state_matches"] is True
    assert result["findings"] == []
    assert result["ownership_verified"] is False
    assert result["automatic_reset"] is False


def test_c02_head_drift(repo: Path, spec: dict[str, object]) -> None:
    path = capture(repo, spec)
    git(repo, "commit", "--allow-empty", "-qm", "later")
    assert "tree_changed" in validate(repo, read_object(path), spec)["findings"]


def test_c03_index_worktree_untracked_drift(repo: Path, spec: dict[str, object]) -> None:
    path = capture(repo, spec)
    (repo / "source.txt").write_text("staged\n", encoding="utf-8")
    git(repo, "add", "source.txt")
    (repo / "source.txt").write_text("unstaged\n", encoding="utf-8")
    (repo / "new.txt").write_text("input\n", encoding="utf-8")
    current = read_object(capture(repo, spec))
    original = read_object(path)
    assert original["snapshot"] != current["snapshot"]
    assert "tree_changed" in validate(repo, original, spec)["findings"]
    (repo / "new.txt").write_text("changed without changing HEAD\n", encoding="utf-8")
    assert "tree_changed" in validate(repo, current, spec)["findings"]


@pytest.mark.parametrize("paused,spent", [(True, 4), (False, 50)])
def test_c04_pause_and_total_budget(
    repo: Path, spec: dict[str, object], paused: bool, spent: int
) -> None:
    spec["paused"] = paused
    spec["budgets"] = [{"unit": "USD", "cap": 50, "consumed": spent, "reason": None}]
    result = validate(repo, read_object(capture(repo, spec)), spec)
    assert ("paused" if paused else "budget_exhausted:USD") in result["findings"]


def test_c05_pending_external_outcome(repo: Path, spec: dict[str, object]) -> None:
    spec["pending_operations"] = [{"id": "remote-write-1", "status": "unknown"}]
    result = validate(repo, read_object(capture(repo, spec)), spec)
    assert "pending_operations" in result["findings"]


def test_c06_correction_drift(repo: Path, spec: dict[str, object]) -> None:
    path = capture(repo, spec)
    corrected = copy.deepcopy(spec)
    corrected["corrections"] = ["New correction: do not trust the diagnosis"]
    assert "context_changed" in validate(repo, read_object(path), corrected)["findings"]
    assert read_object(path)["context"] == spec


@pytest.mark.parametrize("field,value", [("routing", {}), ("reviews", {})])
def test_c07_routing_review_drift(
    repo: Path, spec: dict[str, object], field: str, value: dict[str, str]
) -> None:
    path = capture(repo, spec)
    corrected = copy.deepcopy(spec)
    corrected[field] = value
    assert "context_changed" in validate(repo, read_object(path), corrected)["findings"]


def test_c08_per_request_usage_is_not_occupancy(repo: Path) -> None:
    log = repo / "artifacts/events.jsonl"
    log.parent.mkdir()
    event = {
        "type": "assistant",
        "message": {"id": "req-1", "usage": {"input_tokens": 100, "output_tokens": 20}},
    }
    log.write_text(json.dumps(event) + "\n", encoding="utf-8")
    root = repo / "artifacts/telemetry"
    import_events(repo, root, log, "claude", "session-1")
    import_events(repo, root, log, "claude", "session-1")
    result = report(root)
    assert result["event_count"] == 1
    assert result["occupancy"] == {"value": None, "reason": "no qualified occupancy signal"}
    assert result["per_request"][0]["usage"]["input_tokens"] == 100
    assert "cumulative" not in result


def test_codex_host_rejected_by_cli(repo: Path) -> None:
    log = repo / "events.jsonl"
    log.write_text("{}\n", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "devtools.workflow",
            "--repo",
            str(repo),
            "import-events",
            "--source",
            str(log),
            "--host",
            "codex",
            "--session",
            "s",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "invalid choice: 'codex'" in completed.stderr


def test_c09_fork_is_not_fresh_context(repo: Path, spec: dict[str, object]) -> None:
    spec["context_treatment"] = {"kind": "fresh", "input_verified": False}
    result = validate(repo, read_object(capture(repo, spec)), spec)
    assert "fresh_context_unverified" in result["findings"]


def test_tampered_record_fails(repo: Path, spec: dict[str, object]) -> None:
    record = read_object(capture(repo, spec))
    record["context"] = {}
    with pytest.raises(ValueError, match="digest"):
        validate(repo, record, spec)


def test_explicit_ignored_input_is_fingerprinted(repo: Path, spec: dict[str, object]) -> None:
    private = repo / "artifacts/input.txt"
    private.parent.mkdir()
    private.write_text("private input", encoding="utf-8")
    spec["sources"] = ["artifacts/input.txt"]
    path = capture(repo, spec)
    private.write_text("changed private input", encoding="utf-8")
    assert "tree_changed" in validate(repo, read_object(path), spec)["findings"]


def test_telemetry_allowlist_and_message_dedupe(repo: Path) -> None:
    log = repo / "artifacts/events.jsonl"
    log.parent.mkdir()
    event = {
        "type": "assistant",
        "message": {
            "id": "request-1",
            "content": "credential must not enter summary",
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
    }
    log.write_text(json.dumps(event) + "\n" + json.dumps(event) + "\n", encoding="utf-8")
    root = repo / "artifacts/telemetry"
    import_events(repo, root, log, "claude", "session-1")
    result = report(root)
    assert result["event_count"] == 1
    assert "credential" not in json.dumps(result)
    assert result["per_request"][0]["usage"]["output_tokens"] == 20
    assert result["cost_usd"]["value"] is None


def test_state_root_must_be_ignored(repo: Path, spec: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="ignored"):
        checkpoint(repo, repo / "tracked-state", spec)


@pytest.mark.parametrize(
    "budgets",
    [[], [{"unit": "USD", "cap": 50, "consumed": 0}], [{"unit": "USD", "cap": 60, "consumed": 4}]],
)
def test_checkpoint_cannot_reset_total_budget(
    repo: Path, spec: dict[str, object], budgets: list[dict[str, object]]
) -> None:
    capture(repo, spec)
    spec["budgets"] = budgets
    with pytest.raises(ValueError, match="budget"):
        capture(repo, spec)


def test_checkpoint_preserves_history(repo: Path, spec: dict[str, object]) -> None:
    first = capture(repo, spec)
    spec["next_action"] = "Next bounded action"
    second = capture(repo, spec)
    assert read_object(second)["previous_sha256"] == read_object(first)["sha256"]


def test_symlink_input_content_drift(repo: Path, spec: dict[str, object], tmp_path: Path) -> None:
    target = tmp_path / "artifacts/target.txt"
    target.parent.mkdir()
    target.write_text("before", encoding="utf-8")
    (repo / "link.txt").symlink_to(target)
    first = capture(repo, spec)
    target.write_text("after", encoding="utf-8")
    assert "tree_changed" in validate(repo, read_object(first), spec)["findings"]


def test_detached_head(repo: Path, spec: dict[str, object]) -> None:
    git(repo, "checkout", "--detach", "-q")
    record = read_object(capture(repo, spec))
    assert validate(repo, record, spec)["findings"] == []


def test_missing_source_is_not_a_clean_preflight(repo: Path, spec: dict[str, object]) -> None:
    spec["sources"] = ["absent.txt"]
    assert (
        "missing_explicit_inputs"
        in validate(repo, read_object(capture(repo, spec)), spec)["findings"]
    )


def test_tampered_telemetry_summary_rejected(repo: Path) -> None:
    root = repo / "artifacts/telemetry"
    log = repo / "input.jsonl"
    log.write_text("{}\n", encoding="utf-8")
    import_events(repo, root, log, "claude", "session")
    manifest = next((root / "imports").glob("*.json"))
    value = json.loads(manifest.read_text())
    value["events"] = [{"event_id": "evil", "kind": "per_request", "secret": "sensitive"}]
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        report(root)


def test_atomic_failure_preserves_previous_record(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from devtools import storage

    path = repo / "record.json"
    path.write_bytes(b"old")

    def fail_replace(source: str, target: Path) -> None:
        raise OSError("simulated interruption before rename")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(OSError):
        storage.atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert not list(repo.glob(".pending-*"))


def test_conflicting_request_usage_is_not_summed(repo: Path) -> None:
    root = repo / "artifacts/telemetry"
    log = repo / "input.jsonl"
    rows = [
        {"type": "assistant", "message": {"id": "same-request", "usage": {"output_tokens": n}}}
        for n in (1, 2)
    ]
    log.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    import_events(repo, root, log, "claude", "session")
    result = report(root)
    assert len(result["conflicts"]) == 1
    assert result["per_request"] == []


def test_every_cli_command_and_stale_exit(repo: Path, spec: dict[str, object]) -> None:
    context = repo / "context.json"
    context.write_text(json.dumps(spec), encoding="utf-8")
    base = [sys.executable, "-m", "devtools.workflow", "--repo", str(repo)]
    for command in ("init", "checkpoint", "handoff", "validate"):
        completed = subprocess.run([*base, command, "--context", str(context)], capture_output=True)
        assert completed.returncode == 0, completed.stdout
        assert json.loads(completed.stdout)["ownership_verified"] is False
    (repo / "source.txt").write_text("stale", encoding="utf-8")
    assert (
        subprocess.run(
            [*base, "validate", "--context", str(context)], capture_output=True
        ).returncode
        == 1
    )
    log = repo / "events.jsonl"
    log.write_text("{}\ninvalid-json\n", encoding="utf-8")
    completed = subprocess.run(
        [*base, "import-events", "--source", str(log), "--host", "claude", "--session", "test"],
        capture_output=True,
    )
    assert completed.returncode == 1
    completed = subprocess.run([*base, "report"], capture_output=True)
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["invalid_lines"] == 1
