"""Observational task checkpoints and preflight validation, with no host control."""

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from devtools.storage import (
    Json,
    Object,
    atomic_write,
    digest,
    encode,
    git,
    immutable_write,
    local_store,
    locked,
    read_object,
)

REQUIRED = {
    "schema_version",
    "task_id",
    "goal",
    "owner",
    "constraints",
    "corrections",
    "routing",
    "budgets",
    "paused",
    "pending_operations",
    "reviews",
    "authorization",
    "publication_owner",
    "sources",
    "facts",
    "hypotheses",
    "failed_approaches",
    "next_action",
    "context_treatment",
}


def context_check(context: Object) -> None:
    if missing := REQUIRED - context.keys():
        raise ValueError(f"missing context fields: {sorted(missing)}")
    if context["schema_version"] != 1 or type(context["schema_version"]) is not int:
        raise ValueError("unsupported context schema")
    for field in ("task_id", "goal", "owner", "authorization", "publication_owner", "next_action"):
        if not isinstance(context[field], str) or not context[field]:
            raise ValueError(f"{field} must be a nonempty string")
    for field in (
        "constraints",
        "corrections",
        "sources",
        "facts",
        "hypotheses",
        "failed_approaches",
        "pending_operations",
        "budgets",
    ):
        if not isinstance(context[field], list):
            raise ValueError(f"{field} must be a list")
    for field in ("routing", "reviews", "context_treatment"):
        if not isinstance(context[field], dict):
            raise ValueError(f"{field} must be an object")
    if type(context["paused"]) is not bool:
        raise ValueError("paused must be boolean")
    budgets = context["budgets"]
    assert isinstance(budgets, list)
    units: set[str] = set()
    for budget in budgets:
        if not isinstance(budget, dict) or not isinstance(budget.get("unit"), str):
            raise ValueError("budget must name its unit")
        unit = str(budget["unit"])
        if not unit or unit in units or not {"cap", "consumed"} <= budget.keys():
            raise ValueError("budgets require unique units and explicit cap/consumed fields")
        units.add(unit)
        for field in ("cap", "consumed"):
            value = budget.get(field)
            if value is None:
                if not budget.get("reason"):
                    raise ValueError("unknown budget requires a reason")
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError("budget must be nonnegative or unknown with reason")
    encode(context)


def file_identity(path: Path) -> Object:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return {"status": "missing", "sha256": None}
    if stat.S_ISLNK(mode):
        target = path.resolve(strict=True)
        return {
            "status": "symlink",
            "sha256": digest(os.fsencode(os.readlink(path))),
            "target": file_identity(target),
            "mode": mode,
        }
    if not stat.S_ISREG(mode):
        raise ValueError(f"input is not a regular file or symlink: {path}")
    return {"status": "file", "sha256": digest(path.read_bytes()), "mode": mode}


def fingerprint(repo: Path, sources: Json) -> Object:
    if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources):
        raise ValueError("sources must be an explicit list of file paths")
    tracked = git(repo, "ls-files", "-z", "--cached").split(b"\0")
    untracked = git(repo, "ls-files", "-z", "--others", "--exclude-standard").split(b"\0")
    names = sorted({os.fsdecode(name) for name in tracked + untracked if name})
    files: Object = {name: file_identity(repo / name) for name in names}
    explicit: Object = {}
    for source in sources:
        assert isinstance(source, str)
        path = Path(source)
        explicit[source] = file_identity(path if path.is_absolute() else repo / path)
    return {
        "workspace": str(repo.resolve()),
        "head": git(repo, "rev-parse", "HEAD").decode().strip(),
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD").decode().strip(),
        "index_sha256": digest(git(repo, "ls-files", "--stage", "-z")),
        "files": files,
        "explicit_inputs": explicit,
    }


def checkpoint(repo: Path, root: Path, context: Object, *, kind: str = "checkpoint") -> Path:
    context_check(context)
    if kind not in {"init", "checkpoint", "handoff"}:
        raise ValueError("unsupported checkpoint kind")
    root = local_store(repo, root)
    with locked(root):
        current = root / "current.json"
        if kind == "init" and current.exists():
            raise ValueError("task store already initialized")
        previous = read_object(current) if current.exists() else None
        if previous is not None:
            prior_context = checked_context(previous)
            preserve_continuity(prior_context, context)
        snapshot = fingerprint(repo, context["sources"])
        if snapshot != fingerprint(repo, context["sources"]):
            raise ValueError("tree changed while capturing checkpoint; retry at a safe boundary")
        record: Object = {
            "schema_version": 1,
            "kind": kind,
            "created_at": datetime.now(UTC).isoformat(),
            "context": context,
            "previous_sha256": previous["sha256"] if previous else None,
            "snapshot": snapshot,
            "ownership_verified": False,
            "transfer_status": "NOT_READY",
            "host_control": "none; verify writers and assign successor outside this tool",
        }
        record["sha256"] = digest(encode(record))
        path = root / "checkpoints" / f"{record['sha256']}.json"
        immutable_write(path, encode(record))
        atomic_write(root / "current.json", encode(record))
        return path


def checked_context(record: Object) -> Object:
    payload = {key: value for key, value in record.items() if key != "sha256"}
    if record.get("sha256") != digest(encode(payload)):
        raise ValueError("checkpoint digest mismatch")
    old = record.get("context")
    if not isinstance(old, dict):
        raise ValueError("checkpoint context missing")
    context_check(old)
    return old


def preserve_continuity(old: Object, new: Object) -> None:
    for field in ("task_id", "goal", "owner", "publication_owner"):
        if old[field] != new[field]:
            raise ValueError(f"{field} cannot change within a task store")
    for field in ("constraints", "corrections"):
        before, after = old[field], new[field]
        assert isinstance(before, list) and isinstance(after, list)
        if any(item not in after for item in before):
            raise ValueError(f"{field} cannot be dropped; append superseding corrections")
    if old["paused"] and not new["paused"] and not new.get("resume_authorization"):
        raise ValueError(
            "resuming a recorded pause requires explicit resume_authorization evidence"
        )
    before, after = old["budgets"], new["budgets"]
    assert isinstance(before, list) and isinstance(after, list)
    for budget in before:
        assert isinstance(budget, dict)
        matches = [
            item for item in after if isinstance(item, dict) and item["unit"] == budget["unit"]
        ]
        if len(matches) != 1 or not isinstance(matches[0], dict):
            raise ValueError("existing budgets must be preserved uniquely")
        updated = matches[0]
        if updated["cap"] != budget["cap"]:
            raise ValueError("checkpoint cannot replenish or change a budget cap")
        used, next_used = budget["consumed"], updated["consumed"]
        if isinstance(used, (int, float)) and (
            not isinstance(next_used, (int, float)) or next_used < used
        ):
            raise ValueError("checkpoint cannot reduce consumed budget")


def validate(repo: Path, record: Object, current_context: Object) -> Object:
    old = checked_context(record)
    context_check(current_context)
    findings: set[str] = set()
    snapshot = fingerprint(repo, old["sources"])
    same_tree = record.get("snapshot") == snapshot
    if not same_tree:
        findings.add("tree_changed")
    if old != current_context:
        findings.add("context_changed")
    explicit = snapshot["explicit_inputs"]
    assert isinstance(explicit, dict)
    if any(isinstance(value, dict) and value["status"] == "missing" for value in explicit.values()):
        findings.add("missing_explicit_inputs")
    # Never let a submitted replacement erase the recorded pause or exhausted budget.
    for context in (old, current_context):
        if context["paused"]:
            findings.add("paused")
        if context["pending_operations"]:
            findings.add("pending_operations")
        budgets = context["budgets"]
        assert isinstance(budgets, list)
        for budget in budgets:
            assert isinstance(budget, dict)
            cap, used = budget.get("cap"), budget.get("consumed")
            if cap is None or used is None:
                findings.add(f"budget_unknown:{budget['unit']}")
            elif isinstance(cap, (int, float)) and isinstance(used, (int, float)) and used >= cap:
                findings.add(f"budget_exhausted:{budget['unit']}")
        treatment = context["context_treatment"]
        assert isinstance(treatment, dict)
        if treatment.get("kind") == "fresh" and treatment.get("input_verified") is not True:
            findings.add("fresh_context_unverified")
    return {
        "schema_version": 1,
        "state_matches": same_tree,
        "findings": [item for item in sorted(findings)],
        "ownership_verified": False,
        "transfer_status": "NOT_READY",
        "automatic_reset": False,
        "limitation": "Observational only; no process stop, transfer or factual truth proof.",
    }
