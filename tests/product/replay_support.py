"""Offline replay of corpus entries through the journal's own step validators (tier I2).

An entry holds one retained payload, the input hashes it was produced against and the
validator outcome recorded at the time, plus optionally `pack` (a registered synthetic builder)
or `pack_sha256` + `pack_source` (a real case pack under `artifacts/public-case/`), and
`upstream` (earlier CP-1 step payloads; a `quality` entry holds all four stages and replays
through the promotion, task 7.10). Replay builds the store, submits the upstream payloads
in order and then the payload the way a live dispatch does (`live.submission.
submit_model_payload`: null resolution, then for source_readiness Python's composition of the
review from the model's submission) and compares. An entry with `payload_kind: "journal"` holds
a stored contract supplied directly to the journal (the synthetic seeds), so it goes straight to
`submit_cp0_review` / `submit_cp1_step`; any other entry is a model payload. A pre-0008 model
payload (the stored `ReadinessReview` shape) therefore replays as rejected with the superseded-
shape issue; such entries carry `superseded_by: "0008"`.

Verdicts: `ok`; `skipped-pack-absent` when a real entry's pack directory is not in this checkout
(CI has no artifacts) - never a pass, counted and listed by `make replay`; `stale-inputs` when no
pack is named, or the pack is present but does not hash as recorded, or its journal input hashes
differ (a failure with the reason, never skipped); and the failures `upstream-invalid`,
`outcome-changed`, `issues-changed`, `unsupported-step`, `malformed`.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.cp1_workflow import CP1_PROMOTION, promote_cp1, submit_cp1_step
from deploy_vii.execution import Attempt, Execution
from deploy_vii.live.corpus import (
    CORPUS_ROOT,
    REPOSITORY_ROOT,
    SUPPORTED_STEPS,
    CorpusError,
    PackAbsent,
    PackMismatch,
    load_case_pack,
    real_pack_ticket,
)
from deploy_vii.live.runner import journal_outcome
from deploy_vii.live.schema import normalise
from deploy_vii.live.submission import submit_model_payload
from deploy_vii.readiness import ReadinessReview
from tests.product.test_execution import fixture_store
from tests.product.test_workflow import cp1_case

OK = "ok"
SKIPPED = "skipped-pack-absent"


@dataclass(frozen=True)
class Verdict:
    entry: str
    status: str
    reason: str
    cohort: str = "unknown"

    @property
    def passed(self) -> bool:
        return self.status == OK

    def __str__(self) -> str:
        return f"{self.entry} [{self.cohort}]: {self.status}: {self.reason}"


def corpus_entries(root: Path = CORPUS_ROOT) -> list[Path]:
    return sorted(root.glob("*/*.json"))


def _cp0_store(work: Path) -> tuple[Execution, Attempt]:
    store = fixture_store(work)
    return store, store.begin("CP-0")


def _cp1_store(work: Path) -> tuple[Execution, Attempt]:
    """A fresh CP-1 ticket on the synthetic CP-1 pack, CP-0 accepted via its retained payload."""
    base, _, _ = cp1_case(work / "base")
    snapshot = base.read()
    store = Execution.create(work / "fresh", base.pack())
    submit_cp0_review(
        store,
        store.begin("CP-0").ticket_id,
        base.payload(snapshot.attempts[0].steps[0].payload_sha256),
    )
    return store, store.begin("CP-1")


PACKS: dict[str, Callable[[Path], tuple[Execution, Attempt]]] = {
    "synthetic-cp0": _cp0_store,
    "synthetic-cp1": _cp1_store,
}


def cp1_seed_payloads(work: Path) -> dict[str, str]:
    """Synthetic `source_context` and `financials` payloads (used to seed the corpus)."""
    store, _, extraction = cp1_case(work)
    return {
        "source_context": store.payload(store.read().attempts[1].steps[0].payload_sha256),
        "financials": extraction.model_dump_json(),
    }


PAYLOAD_KINDS = ("model", "journal")


def _submit(
    store: Execution, ticket: Attempt, step_id: str, payload: str, kind: str = "model"
) -> list[str]:
    if kind == "journal":  # a stored contract handed to the journal directly (synthetic seeds)
        if step_id == "source_readiness":
            payload, _ = normalise(ReadinessReview, payload)
            return list(submit_cp0_review(store, ticket.ticket_id, payload).issues)
        if step_id == "quality":  # the review enters the journal only through the promotion
            journal = promote_cp1(store, ticket.ticket_id, payload)
        else:
            journal = submit_cp1_step(store, ticket.ticket_id, step_id, payload)
    else:
        journal = submit_model_payload(store, ticket.ticket_id, step_id, payload).journal
        if step_id == "source_readiness":
            return list(journal.issues)
    # The step's own verdict: a first CP-1 rejection is kept in `step_repairs` (task 7.0g).
    return list(journal_outcome(store, step_id, journal)[1])


def replay_entry(path: Path, work: Path, *, repository: Path = REPOSITORY_ROOT) -> Verdict:
    """Replay one entry; the verdict names the cohort its provenance records (required).

    `repository` is where `artifacts/public-case/` is looked up for real-pack entries."""
    verdict = _replay(path, work, repository)
    try:
        cohort = str(json.loads(path.read_text(encoding="utf-8"))["provenance"]["cohort"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        if not verdict.passed:
            return verdict  # keep the more specific failure
        reason = f"provenance.cohort is required ({type(error).__name__})"
        return Verdict(verdict.entry, "malformed", reason)
    return replace(verdict, cohort=cohort)


def _store(
    name: str, entry: dict[str, Any], work: Path, repository: Path
) -> tuple[Execution, Attempt] | Verdict:
    """The journal the entry replays against, or the verdict that stops the replay."""
    pack = entry.get("pack")
    real = "pack_source" in entry or "pack_sha256" in entry
    if pack is not None and real:
        return Verdict(name, "malformed", "an entry names a synthetic pack or a real one, not both")
    if pack is not None:
        return PACKS[pack](work)
    if not real:
        return Verdict(
            name, "stale-inputs", "entry names no registered synthetic pack or case pack"
        )
    source, digest = entry.get("pack_source"), entry.get("pack_sha256")
    if not isinstance(source, str) or digest != entry["input_hashes"].get("prepared-pack"):
        return Verdict(name, "malformed", "pack_sha256 must equal input_hashes.prepared-pack")
    if entry["step_id"] != "source_readiness":
        return Verdict(name, "unsupported-step", "real-pack replay covers source_readiness only")
    try:
        return real_pack_ticket(load_case_pack(source, digest, repository), work / "journal")
    except PackAbsent as absent:
        return Verdict(name, SKIPPED, f"{absent}; real entries replay only where the pack is")
    except PackMismatch as mismatch:
        return Verdict(name, "stale-inputs", str(mismatch))
    except CorpusError as error:
        return Verdict(name, "malformed", str(error))


def _replay(path: Path, work: Path, repository: Path = REPOSITORY_ROOT) -> Verdict:
    name = path.parent.name + "/" + path.name
    try:
        entry: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        step_id = entry["step_id"]
        payload = entry["payload"]
        expected_hashes = dict(entry["input_hashes"])
        expected_outcome = entry["expected"]["validator_outcome"]
        expected_issues = list(entry["expected"]["issues"])
        pack = entry.get("pack")
        upstream = dict(entry.get("upstream", {}))
        kind = entry.get("payload_kind", "model")
    except (OSError, ValueError, KeyError, TypeError) as error:
        return Verdict(name, "malformed", f"{type(error).__name__}: {error}")
    if kind not in PAYLOAD_KINDS:
        return Verdict(name, "malformed", f"payload_kind must be one of {list(PAYLOAD_KINDS)}")
    if step_id != path.parent.name:
        return Verdict(
            name, "malformed", f"step_id {step_id!r} is not in directory {path.parent.name!r}"
        )
    if step_id not in SUPPORTED_STEPS:
        return Verdict(name, "unsupported-step", f"{step_id!r} cannot be replayed")
    if pack is not None and pack not in PACKS:
        return Verdict(name, "malformed", f"unknown synthetic pack {pack!r}")
    earlier = CP1_PROMOTION[: CP1_PROMOTION.index(step_id)] if step_id in CP1_PROMOTION else ()
    if set(upstream) != set(earlier):
        return Verdict(name, "malformed", f"upstream must hold exactly {list(earlier)}")
    built = _store(name, entry, work, repository)
    if isinstance(built, Verdict):
        return built
    store, ticket = built
    actual_hashes = {item.input_id: item.sha256 for item in ticket.inputs}
    if actual_hashes != expected_hashes:
        differing = sorted(
            key
            for key in actual_hashes.keys() | expected_hashes.keys()
            if actual_hashes.get(key) != expected_hashes.get(key)
        )
        label = pack if pack is not None else entry["pack_source"]
        return Verdict(
            name,
            "stale-inputs",
            f"pack {label!r} cannot reproduce input hashes for " + ", ".join(differing),
        )
    for step in earlier:
        if _submit(store, ticket, step, upstream[step], kind):
            return Verdict(name, "upstream-invalid", f"retained upstream step {step} is rejected")
    issues = _submit(store, ticket, step_id, payload, kind)
    outcome = "rejected" if issues else "accepted"
    if outcome != expected_outcome:
        return Verdict(name, "outcome-changed", f"recorded {expected_outcome}, replayed {outcome}")
    if issues != expected_issues:
        return Verdict(name, "issues-changed", f"recorded {expected_issues!r}, replayed {issues!r}")
    return Verdict(name, OK, f"{outcome} as recorded")
