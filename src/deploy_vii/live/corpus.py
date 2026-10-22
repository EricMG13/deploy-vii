"""Replay corpus entries (tier I2) written from a retained attempt.

`tests/product/replay/<step>/<case-id>.json` holds one payload, the journal input hashes it was
produced against, the recorded validator outcome and its provenance, plus optional keys:

- `pack`, the name of a registered synthetic builder whose prepared-pack hash equals the
  attempt's;
- for a real attempt (task 2.7a), `pack_sha256` (the prepared-pack hash already bound in
  `input_hashes`) and `pack_source`, the repository-relative case directory
  (`artifacts/public-case/<case-dir>`) whose `complete.json` records that hash, plus `live`, the
  validator verdict the live attempt recorded (`checks/validator.json`), and `expected_basis`:
  `live` when `expected` is that verdict, `revalidated` when `expected` was regenerated against
  the current validator over the same pack after a deliberate wording change (the outcome must be
  unchanged), plus `superseded_by: "0008"` when that revalidation finds the pre-0008 payload
  shape (the stored contract instead of a `ReadinessSubmission`). A revalidation whose outcome
  differs from `live` is refused unless the validator fix that changed it is named
  (`--outcome-changed-by <task-or-decision>`); the entry then also records `outcome_changed_by`,
  and `live` stays as recorded (tier I2 tracks validator-driven outcome changes, task 2.9);
- `upstream`, the accepted payloads of the earlier CP-1 steps of the same ticket.

An attempt on a pack that is neither registered nor found under `artifacts/public-case/` gets none
of the pack keys, so it replays as `stale-inputs` with the reason. Only attempts whose payload
reached the journal (status accepted or rejected) and whose evidence is unaltered can become
entries. Packs are never copied into the repository: CI has no artifacts, so real entries replay
there as `skipped-pack-absent`.
"""

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from deploy_vii.cp1_workflow import CP1_STEPS
from deploy_vii.execution import Attempt, Execution
from deploy_vii.live.submission import SUPERSEDED_SHAPE, submit_model_payload
from deploy_vii.preparation import PreparedPack, load_pack

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CORPUS_ROOT = REPOSITORY_ROOT / "tests" / "product" / "replay"
CASE_PACKS = "artifacts/public-case"
SUPPORTED_STEPS = ("source_readiness", *CP1_STEPS)
# Prepared-pack hashes of the synthetic builders in tests/product/replay_support.py (a test
# asserts they still match, so drift is caught there, not here).
SYNTHETIC_PACKS = {
    "synthetic-cp0": "fdd5a1eee9773517b2285cb211067edffa5636351f3d6825cc20cc3babd0a164",
    "synthetic-cp1": "4e9b00f5c670fedcd5c22bfc34190ff9df351bbdeab26c3c3eb93dae7bb311b0",
}
_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}")
PACK_SOURCE = re.compile(r"artifacts/public-case/[A-Za-z0-9][A-Za-z0-9_.-]{0,159}")


class CorpusError(Exception):
    """The attempt cannot become a corpus entry, or the entry would replace another."""


class PackAbsent(CorpusError):
    """The real case pack an entry names is not present in this checkout (CI has none)."""


class PackMismatch(CorpusError):
    """The case pack is present but cannot be loaded or does not hash as recorded."""


def _json(path: Path, what: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise CorpusError(f"{what} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise CorpusError(f"{what} is not an object")
    return document


def _manifest(directory: Path) -> dict[str, Any]:
    path = directory / "manifest.json"
    if not path.is_file():
        raise CorpusError(f"{directory} has no manifest.json (incomplete attempt)")
    return _json(path, "manifest.json")


def _live_verdict(directory: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """The validator verdict the attempt recorded (`checks/validator.json` = manifest copy)."""
    recorded = manifest["validator"]
    path = directory / "checks" / "validator.json"
    if path.is_file() and _json(path, "checks/validator.json") != recorded:
        raise CorpusError("checks/validator.json and the manifest validator block disagree")
    return {"validator_outcome": recorded["outcome"], "issues": list(recorded["issues"])}


def find_case_pack(pack_sha256: str, repository: Path = REPOSITORY_ROOT) -> str | None:
    """The `artifacts/public-case/<dir>` whose completion marker records `pack_sha256`."""
    for marker in sorted((repository / CASE_PACKS).glob("*/complete.json")):
        try:
            recorded = json.loads(marker.read_text(encoding="utf-8")).get("pack_sha256")
        except (OSError, ValueError, AttributeError):
            continue  # an unreadable marker is not this pack; load_case_pack verifies a match
        if recorded == pack_sha256:
            return f"{CASE_PACKS}/{marker.parent.name}"
    return None


def load_case_pack(pack_source: str, pack_sha256: str, repository: Path) -> PreparedPack:
    """Load and verify a real case pack: PackAbsent if missing, PackMismatch if it differs."""
    if not PACK_SOURCE.fullmatch(pack_source):
        raise CorpusError(f"pack_source {pack_source!r} is not artifacts/public-case/<dir>")
    directory = repository / pack_source
    if not (directory / "complete.json").is_file():
        raise PackAbsent(f"{pack_source} is not present in this checkout")
    try:
        pack = load_pack(directory)
    except (OSError, ValueError) as error:
        raise PackMismatch(f"{pack_source} cannot be loaded: {type(error).__name__}") from None
    if pack.content_hash() != pack_sha256:
        raise PackMismatch(f"{pack_source} hashes to {pack.content_hash()}, not {pack_sha256}")
    return pack


def real_pack_ticket(pack: PreparedPack, work: Path) -> tuple[Execution, Attempt]:
    """A fresh journal on a real pack with an open CP-0 ticket (the only real step so far)."""
    store = Execution.create(work, pack)
    return store, store.begin("CP-0")


def _validate_now(entry: dict[str, Any], repository: Path) -> list[str]:
    """The current validator's issues for a real source_readiness entry over its pack."""
    if entry["step_id"] != "source_readiness":
        raise CorpusError("only source_readiness entries can be revalidated on a real pack")
    pack = load_case_pack(entry["pack_source"], entry["pack_sha256"], repository)
    with tempfile.TemporaryDirectory() as work:
        store, ticket = real_pack_ticket(pack, Path(work) / "journal")
        if {item.input_id: item.sha256 for item in ticket.inputs} != entry["input_hashes"]:
            raise PackMismatch("the pack's journal input hashes differ from the attempt's")
        submitted = submit_model_payload(
            store, ticket.ticket_id, "source_readiness", entry["payload"]
        )
        return list(submitted.journal.issues)


def entry_from_attempt(
    directory: Path,
    *,
    repository: Path = REPOSITORY_ROOT,
    revalidate: bool = False,
    outcome_changed_by: str | None = None,
) -> dict[str, Any]:
    """Build the corpus entry from a sealed attempt directory; refuse anything unreplayable.

    `outcome_changed_by` names the validator fix that changed a revalidated outcome; it is
    refused without `revalidate`, when blank, and when the outcome did not change."""
    if outcome_changed_by is not None and not revalidate:
        raise CorpusError("--outcome-changed-by is accepted only with --revalidate")
    if outcome_changed_by is not None and not outcome_changed_by.strip():
        raise CorpusError("--outcome-changed-by names the task or decision that changed it")
    manifest = _manifest(directory)
    try:
        step_id = manifest["step_id"]
        status = manifest["status"]
        hashes = manifest["hashes"]["journal_inputs"]
        live = _live_verdict(directory, manifest)
        provenance = {
            "batch_id": manifest["experiment_id"],
            "model": manifest["model"],
            "attempt_id": manifest["attempt_id"],
            # Required: a proxy or other non-pool attempt keeps its own cohort in the corpus.
            "cohort": manifest["cohort"],
        }
    except (KeyError, TypeError) as error:
        raise CorpusError(f"manifest lacks {error}") from error
    if step_id not in SUPPORTED_STEPS:
        raise CorpusError(f"step {step_id!r} is not replayable from one payload")
    if status not in {"accepted", "rejected"}:
        raise CorpusError(f"status {status!r} never reached the journal validators")
    if status != live["validator_outcome"] or (status == "accepted") == bool(live["issues"]):
        raise CorpusError("manifest status and validator issues disagree")
    if "output.md" in manifest.get("scrubbed_files", []):
        raise CorpusError("output.md was altered by credential scrubbing; it is not the payload")
    entry: dict[str, Any] = {
        "step_id": step_id,
        "payload": (directory / "output.md").read_text(encoding="utf-8"),
        "input_hashes": dict(hashes),
        "expected": live,
        "provenance": provenance,
    }
    pack_hash = hashes.get("prepared-pack")
    pack_name = next((k for k, v in SYNTHETIC_PACKS.items() if v == pack_hash), None)
    source = (
        None
        if pack_name or not isinstance(pack_hash, str)
        else find_case_pack(pack_hash, repository)
    )
    if pack_name is not None:
        entry["pack"] = pack_name
    elif source is not None:
        entry.update(pack_sha256=pack_hash, pack_source=source, live=live, expected_basis="live")
    if revalidate:
        if source is None:
            raise CorpusError("--revalidate needs a real case pack present in this checkout")
        issues = _validate_now(entry, repository)
        outcome = "rejected" if issues else "accepted"
        changed = outcome != live["validator_outcome"]
        if changed and outcome_changed_by is None:
            raise CorpusError(
                "revalidation changed the outcome; that is not a wording change "
                "(name the validator fix with --outcome-changed-by)"
            )
        if outcome_changed_by is not None and not changed:
            raise CorpusError("--outcome-changed-by given but the outcome did not change")
        entry["expected"] = {"validator_outcome": outcome, "issues": issues}
        entry["expected_basis"] = "revalidated"
        if changed:
            entry["outcome_changed_by"] = outcome_changed_by
        if issues == [SUPERSEDED_SHAPE]:
            # The payload predates the model-facing submission shape; it stays as evidence.
            entry["superseded_by"] = "0008"
    if step_id in CP1_STEPS and CP1_STEPS.index(step_id) > 0:
        entry["upstream"] = _upstream(directory, manifest, step_id)
    return entry


def _upstream(directory: Path, manifest: dict[str, Any], step_id: str) -> dict[str, str]:
    """Accepted payloads of the earlier steps of this ticket, from its sibling attempt dirs."""
    found: dict[str, str] = {}
    for sibling in sorted(directory.parent.iterdir()):
        if not (sibling / "manifest.json").is_file():
            continue
        other = _manifest(sibling)
        if (
            other.get("ticket_id") == manifest.get("ticket_id")
            and other.get("status") == "accepted"
            and other.get("step_id") in CP1_STEPS[: CP1_STEPS.index(step_id)]
        ):
            step = other["step_id"]
            if step in found:
                raise CorpusError(f"more than one accepted attempt retained for step {step}")
            if "output.md" in other.get("scrubbed_files", []):
                raise CorpusError(f"earlier step {step}: output.md was altered by scrubbing")
            found[step] = (sibling / "output.md").read_text(encoding="utf-8")
    missing = [s for s in CP1_STEPS[: CP1_STEPS.index(step_id)] if s not in found]
    if missing:
        raise CorpusError("no accepted attempt retained for earlier step(s): " + ", ".join(missing))
    return {s: found[s] for s in CP1_STEPS if s in found}


def write_entry(
    directory: Path,
    case_id: str,
    *,
    root: Path = CORPUS_ROOT,
    replace: bool = False,
    repository: Path = REPOSITORY_ROOT,
    revalidate: bool = False,
    outcome_changed_by: str | None = None,
) -> Path:
    """Write `<root>/<step>/<case_id>.json` for a sealed attempt; `replace` must be explicit."""
    if not _CASE_ID.fullmatch(case_id):
        raise CorpusError(f"case id {case_id!r} may hold letters, digits, '.', '_' and '-'")
    entry = entry_from_attempt(
        directory,
        repository=repository,
        revalidate=revalidate,
        outcome_changed_by=outcome_changed_by,
    )
    target = root / str(entry["step_id"]) / f"{case_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(entry, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        with target.open("w" if replace else "x", encoding="utf-8") as stream:
            stream.write(text)
    except FileExistsError:
        raise CorpusError(
            f"{target} exists; corpus entries are replaced only with --replace"
        ) from None
    return target
