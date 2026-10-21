"""Single-writer execution journal; immutable snapshots, bounded repair, current lineage.

Validators are trusted Python module implementations, never model-supplied verdicts.
The journal does not invoke models, spend money, or claim analytical qualification.
"""

import fcntl
import hashlib
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError

from deploy_vii.contracts import (
    Claim,
    Contract,
    Fact,
    Hash,
    Identifier,
    Input,
    Module,
    ModuleView,
    Text,
    View,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import citation_issues
from deploy_vii.registry import canonical, dependencies, modules, plan

Validator = Callable[[Module], tuple[str, ...]]


class Attempt(Contract):
    ticket_id: Identifier
    module_id: Identifier
    inputs: tuple[Input, ...]
    number: int = Field(ge=0, le=1)
    status: Literal["pending", "finished"] = "pending"
    repair_of: Identifier | None = None
    repair_issues: tuple[str, ...] = ()
    payload: str | None = None
    issues: tuple[str, ...] = ()
    result: Module | None = None
    interruption: Text | None = None


class ExecutionSnapshot(Contract):
    schema_version: Literal["execution/1"] = "execution/1"
    parent: Hash | None = None
    pack: PreparedPack
    attempts: tuple[Attempt, ...] = ()
    heads: tuple[Module, ...] = ()


def current_inputs(snapshot: ExecutionSnapshot, module_id: str) -> tuple[Input, ...]:
    graph = dependencies(snapshot.pack.run.requested_modules)
    if module_id not in graph:
        raise ValueError("Module is not selected for this run")
    heads = {item.module_id: item for item in snapshot.heads}
    required = graph[module_id]
    if any(
        item not in heads or heads[item].status not in {"accepted", "restricted"}
        for item in required
    ):
        raise ValueError("Required upstream is unrun, stale or blocked")
    if module_id not in {"CP-0", "CP-MODEL", "CP-MEMO", "CP-OS"}:
        readiness = heads.get("CP-0")
        commands = (
            ()
            if readiness is None
            else tuple(
                fact.text
                for fact in readiness.facts
                if fact.table_id == "T8"
                and fact.row_id == module_id
                and fact.field == "exact_command"
            )
        )
        if commands != (f"Run {module_id}",):
            raise ValueError("CP-0 has not authorized this consumer's source readiness")
    return (
        Input(input_id="prepared-pack", sha256=snapshot.pack.content_hash()),
        *tuple(
            Input(input_id=item, sha256=heads[item].content_hash())
            for item in plan(snapshot.pack.run.requested_modules)
            if item in required
        ),
    )


def candidate_issues(
    snapshot: ExecutionSnapshot, attempt: Attempt, candidate: Module
) -> tuple[str, ...]:
    run = snapshot.pack.run
    issues: list[str] = []
    if (
        candidate.run_id != run.run_id
        or candidate.issuer_id != run.issuer_id
        or candidate.as_of != run.as_of
        or candidate.method_version != run.method_version
        or candidate.module_id != attempt.module_id
        or candidate.attempt != attempt.number
        or candidate.status != "candidate"
    ):
        issues.append("Candidate identity, attempt or status does not match the ticket")
    supplied = {item.input_id: item.sha256 for item in candidate.inputs}
    expected = {item.input_id: item.sha256 for item in attempt.inputs}
    if any(supplied.get(key) != value for key, value in expected.items()) or any(
        key.startswith("CP-") and key not in expected for key in supplied
    ):
        issues.append("Candidate does not bind the exact current upstream inputs")
    records: tuple[Fact | Claim, ...] = (*candidate.facts, *candidate.claims)
    for record in records:
        issues.extend(citation_issues(record.citations, snapshot.pack.sources))
    return tuple(dict.fromkeys(issues))


def invalidate(heads: tuple[Module, ...], changed: str) -> tuple[Module, ...]:
    affected = {changed}
    while True:
        expanded = affected | {
            module.module_id
            for module in heads
            if any(item.input_id in affected for item in module.inputs)
        }
        if expanded == affected:
            break
        affected = expanded
    return tuple(
        module.model_copy(
            update={
                "status": "stale",
                "limitations": (*module.limitations, f"Input changed: {changed}; rerun required"),
            }
        )
        if module.module_id in affected and module.module_id != changed and module.status != "stale"
        else module
        for module in heads
    )


def settle(
    snapshot: ExecutionSnapshot,
    attempt: Attempt,
    payload: str,
    validator: Validator,
    interruption: str | None = None,
) -> Attempt:
    """Retain every response; only valid current candidates can supply accepted facts."""
    candidate: Module | None = None
    try:
        candidate = Module.model_validate_json(payload)
        issues = candidate_issues(snapshot, attempt, candidate)
    except ValidationError as error:
        issues = (f"Malformed candidate: {error}",)
    if interruption is not None:
        issues = (f"Interrupted: {interruption}",)
    if candidate is not None and not issues:
        issues = validator(candidate)
    issues = tuple(dict.fromkeys(issues))
    if issues:
        result = Module(
            run_id=snapshot.pack.run.run_id,
            issuer_id=snapshot.pack.run.issuer_id,
            as_of=snapshot.pack.run.as_of,
            module_id=attempt.module_id,
            inputs=attempt.inputs,
            attempt=attempt.number,
            status="rejected" if attempt.number == 0 else "blocked",
            limitations=issues,
        )
    else:
        assert candidate is not None
        inherited = [
            text
            for module in snapshot.heads
            if module.module_id in {item.input_id for item in attempt.inputs}
            for text in module.limitations
        ]
        limits = tuple(
            dict.fromkeys(
                [*candidate.limitations, *inherited]
                + (
                    ["Synthetic case; not real issuer qualification"]
                    if snapshot.pack.run.case_kind == "synthetic"
                    else []
                )
            )
        )
        result = candidate.model_copy(
            update={"status": "restricted" if limits else "accepted", "limitations": limits}
        )
    return attempt.model_copy(
        update={
            "status": "finished",
            "payload": payload,
            "issues": issues,
            "result": result,
            "interruption": interruption,
        }
    )


class Execution:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @classmethod
    def create(cls, directory: Path, pack: PreparedPack) -> "Execution":
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        plan(pack.run.requested_modules)
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "snapshots").mkdir()
        store = cls(directory)
        store._write(ExecutionSnapshot(pack=pack))
        return store

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with (self.directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def read(self) -> ExecutionSnapshot:
        digest = (self.directory / "current").read_text(encoding="ascii").strip()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("Invalid execution pointer")
        raw = (self.directory / "snapshots" / (digest + ".json")).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Execution snapshot hash mismatch")
        return ExecutionSnapshot.model_validate_json(raw)

    def _write(self, snapshot: ExecutionSnapshot) -> None:
        # Full snapshots trade storage for simple, self-contained interruption recovery.
        raw = snapshot.model_dump_json().encode()
        digest = hashlib.sha256(raw).hexdigest()
        path = self.directory / "snapshots" / (digest + ".json")
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError("Existing execution snapshot is corrupt")
        else:
            with path.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        descriptor, temporary = tempfile.mkstemp(prefix=".current-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(digest + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / "current")
        finally:
            Path(temporary).unlink(missing_ok=True)

    def begin(self, module_id: str) -> Attempt:
        module_id = canonical(module_id)
        with self._locked():
            snapshot = self.read()
            if any(item.status == "pending" for item in snapshot.attempts):
                raise ValueError("An attempt is pending; resume or explicitly interrupt it first")
            inputs = current_inputs(snapshot, module_id)
            previous = [
                item
                for item in snapshot.attempts
                if item.module_id == module_id and item.inputs == inputs
            ]
            if previous and (len(previous) >= 2 or not previous[-1].issues):
                raise ValueError("Input set is settled or its one repair has been consumed")
            attempt = Attempt(
                ticket_id=str(uuid4()),
                module_id=module_id,
                inputs=inputs,
                number=len(previous),
                repair_of=previous[-1].ticket_id if previous else None,
                repair_issues=previous[-1].issues if previous else (),
            )
            self._write(
                snapshot.model_copy(
                    update={
                        "parent": snapshot.content_hash(),
                        "attempts": (*snapshot.attempts, attempt),
                    }
                )
            )
            return attempt

    def finish(
        self, ticket_id: str, payload: str, validator: Validator, *, interruption: str | None = None
    ) -> Attempt:
        with self._locked():
            snapshot = self.read()
            attempt = next(
                (item for item in snapshot.attempts if item.ticket_id == ticket_id), None
            )
            if attempt is None or attempt.status != "pending":
                raise ValueError("Ticket is absent or already finished")
            if current_inputs(snapshot, attempt.module_id) != attempt.inputs:
                raise ValueError("Ticket inputs have changed")

            if interruption is not None:
                if not interruption.strip():
                    raise ValueError("An interruption requires a reason")
                if attempt.payload is not None:
                    payload = attempt.payload
            if attempt.payload is not None and attempt.payload != payload:
                raise ValueError(
                    "Ticket already retains a different response; finish or interrupt it"
                )
            if attempt.payload is None:
                attempt = attempt.model_copy(update={"payload": payload})
                snapshot = snapshot.model_copy(
                    update={
                        "parent": snapshot.content_hash(),
                        "attempts": tuple(
                            attempt if item.ticket_id == ticket_id else item
                            for item in snapshot.attempts
                        ),
                    }
                )
                self._write(snapshot)  # Retain response before a validator can fail or crash.

            finished = settle(snapshot, attempt, payload, validator, interruption)
            result = finished.result
            assert result is not None
            heads = invalidate(snapshot.heads, attempt.module_id)
            if result.status != "rejected":
                heads = (
                    *tuple(item for item in heads if item.module_id != attempt.module_id),
                    result,
                )
            snapshot = snapshot.model_copy(
                update={
                    "parent": snapshot.content_hash(),
                    "heads": heads,
                    "attempts": tuple(
                        finished if item.ticket_id == ticket_id else item
                        for item in snapshot.attempts
                    ),
                }
            )
            self._write(snapshot)
            return finished

    def interrupt(self, ticket_id: str, reason: str) -> Attempt:
        if not reason.strip():
            raise ValueError("An interruption requires a reason")
        # The journal records an interruption, not a claim to have stopped a host process.
        return self.finish(ticket_id, "", lambda _: (), interruption=reason)

    def replace_pack(self, pack: PreparedPack) -> None:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        with self._locked():
            snapshot = self.read()
            if snapshot.pack.run != pack.run:
                raise ValueError("Run identity and scope are immutable; create a new execution")
            if any(item.status == "pending" for item in snapshot.attempts):
                raise ValueError("Cannot change evidence while an attempt is pending")
            if pack == snapshot.pack:
                return
            heads = tuple(
                item.model_copy(
                    update={
                        "status": "stale",
                        "limitations": (*item.limitations, "Prepared pack changed; rerun required"),
                    }
                )
                for item in snapshot.heads
            )
            self._write(
                snapshot.model_copy(
                    update={"parent": snapshot.content_hash(), "pack": pack, "heads": heads}
                )
            )

    def view(self, ticket_id: str | None = None) -> View:
        snapshot = self.read()
        heads = {item.module_id: item for item in snapshot.heads}
        if ticket_id is not None:
            attempt = next(
                (item for item in snapshot.attempts if item.ticket_id == ticket_id), None
            )
            if attempt is None:
                raise ValueError("Unknown candidate ticket")
            if attempt.payload is None:
                raise ValueError("Pending attempt has no candidate preview")
            if current_inputs(snapshot, attempt.module_id) != attempt.inputs:
                raise ValueError("Candidate inputs are stale")
            candidate = Module.model_validate_json(attempt.payload)
            if candidate_issues(snapshot, attempt, candidate):
                raise ValueError("Invalid candidate identity or provenance cannot render")
            heads[attempt.module_id] = candidate
        views: list[ModuleView] = []
        for entry in modules():
            module = heads.get(entry.module_id)
            visible = module is not None and module.status in {
                "accepted",
                "restricted",
                "candidate",
            }
            views.append(
                ModuleView(
                    module_id=entry.module_id,
                    title=entry.title,
                    aliases=entry.aliases,
                    status=module.status if module else "unrun",
                    artifact_sha256=module.content_hash() if module else None,
                    facts=module.facts if visible and module else (),
                    claims=module.claims if visible and module else (),
                    limitations=module.limitations if module else (),
                )
            )
        return View(
            run=snapshot.pack.run,
            mode="candidate" if ticket_id else "accepted",
            modules=tuple(views),
            sources=snapshot.pack.sources,
        )
