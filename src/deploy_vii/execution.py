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
from typing import Literal, Self
from uuid import uuid4

from pydantic import Field, ValidationError, model_validator

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
from deploy_vii.registry import canonical, dependencies, edge_rule, modules, plan

Validator = Callable[[Module], tuple[str, ...]]


class StepSubmission(Contract):
    step_id: Identifier
    inputs: tuple[Input, ...]
    payload: str
    status: Literal["pending", "valid", "invalid"] = "pending"
    output: str | None = None
    issues: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def coherent_state(self) -> Self:
        if self.status == "pending" and (self.output is not None or self.issues):
            raise ValueError("Pending step cannot have a validation result")
        if self.status == "valid" and (self.output is None or self.issues):
            raise ValueError("Valid step requires output and no issues")
        if self.status == "invalid" and not self.issues:
            raise ValueError("Invalid step requires issues")
        return self


class StepValidation(Contract):
    output: str | None = None
    issues: tuple[Text, ...] = ()


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
    steps: tuple[StepSubmission, ...] = ()


class ExecutionSnapshot(Contract):
    schema_version: Literal["execution/4"] = "execution/4"
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

    def bound(item: str) -> Input:
        head = heads.get(item)
        if head is None:
            raise ValueError("Required upstream is unrun, stale or blocked")
        # Only a settled blocked head degrades, and only under a restricted edge (decision 0007).
        if head.status == "accepted" or head.status == "restricted":
            return Input(input_id=item, sha256=head.content_hash(), status=head.status)
        if head.status == "blocked" and edge_rule(module_id, item) == "restricted":
            return Input(input_id=item, sha256=head.content_hash(), status="blocked")
        raise ValueError("Required upstream is unrun, stale or blocked")

    upstream = tuple(
        bound(item) for item in plan(snapshot.pack.run.requested_modules) if item in required
    )
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
    return (Input(input_id="prepared-pack", sha256=snapshot.pack.content_hash()), *upstream)


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
    supplied = {item.input_id: (item.sha256, item.status) for item in candidate.inputs}
    expected = {item.input_id: (item.sha256, item.status) for item in attempt.inputs}
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


def blocked_ancestors(snapshot: ExecutionSnapshot, inputs: tuple[Input, ...]) -> frozenset[str]:
    """Blocked modules in the bound input chain, read from structured input statuses.

    Never derived from limitation text, so plain wording cannot spoof or hide the marker.
    """
    heads = {item.module_id: item for item in snapshot.heads}
    found: set[str] = set()
    seen: set[str] = set()  # a diamond is walked once and a corrupted cycle cannot hang
    pending = list(inputs)
    while pending:
        item = pending.pop()
        if item.status == "blocked":
            found.add(item.input_id)
        elif item.input_id in heads and item.input_id not in seen:
            seen.add(item.input_id)
            pending.extend(heads[item.input_id].inputs)
    return frozenset(found)


def inherited_limitations(
    snapshot: ExecutionSnapshot, attempt: Attempt, own: tuple[str, ...]
) -> tuple[str, ...]:
    """Limitations carried by the bound inputs, de-duplicated and never repeating own findings."""
    heads = {item.module_id: item for item in snapshot.heads}
    texts: list[str] = []
    for item in attempt.inputs:
        head = heads.get(item.input_id)
        if head is None:
            continue
        if item.status == "blocked":
            texts.extend(f"Upstream {item.input_id} blocked: {text}" for text in head.limitations)
        else:
            texts.extend((*head.limitations, *head.inherited_limitations))
    return tuple(text for text in dict.fromkeys(texts) if text not in own)


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
        synthetic = (
            ("Synthetic case; not real issuer qualification",)
            if snapshot.pack.run.case_kind == "synthetic"
            else ()
        )
        own = tuple(dict.fromkeys((*candidate.limitations, *synthetic)))
        inherited = inherited_limitations(snapshot, attempt, own)
        # Own findings or a blocked module anywhere up the input chain (a material inherited
        # gap) restrict the module; other inherited limitations are shown, not penalised.
        material = bool(blocked_ancestors(snapshot, attempt.inputs))
        result = candidate.model_copy(
            update={
                "status": "restricted" if own or material else "accepted",
                "limitations": own,
                "inherited_limitations": inherited,
            }
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
            if interruption is None and any(s.status == "pending" for s in attempt.steps):
                raise ValueError("A step response is pending; resume that step first")

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
            self._save_finished(snapshot, finished)
            return finished

    def _save_finished(self, snapshot: ExecutionSnapshot, finished: Attempt) -> None:
        """Caller holds the execution lock; preserve the existing invalidation policy."""
        result = finished.result
        assert result is not None
        heads = invalidate(snapshot.heads, finished.module_id)
        if result.status != "rejected":
            heads = (*tuple(h for h in heads if h.module_id != finished.module_id), result)
        self._write(
            snapshot.model_copy(
                update={
                    "parent": snapshot.content_hash(),
                    "heads": heads,
                    "attempts": tuple(
                        finished if a.ticket_id == finished.ticket_id else a
                        for a in snapshot.attempts
                    ),
                }
            )
        )

    def submit_step(
        self,
        ticket_id: str,
        module_id: str,
        sequence: tuple[str, ...],
        step_id: str,
        payload: str,
        validator: Callable[[PreparedPack, Attempt], StepValidation],
    ) -> Attempt:
        """Retain an ordered response before trusted validation, sharing the module budget.

        Sequence and validator come from the module implementation. Invalid model
        responses finish this attempt; validator exceptions leave its exact input
        pending for resumption. A valid step is not module acceptance.
        """
        if not sequence or len(sequence) != len(set(sequence)):
            raise ValueError("Step sequence must be nonempty and unique")

        def with_attempt(snapshot: ExecutionSnapshot, updated: Attempt) -> ExecutionSnapshot:
            return snapshot.model_copy(
                update={
                    "parent": snapshot.content_hash(),
                    "attempts": tuple(
                        updated if prior.ticket_id == ticket_id else prior
                        for prior in snapshot.attempts
                    ),
                }
            )

        with self._locked():
            snapshot = self.read()
            attempt = next((a for a in snapshot.attempts if a.ticket_id == ticket_id), None)
            if attempt is None or attempt.status != "pending" or attempt.module_id != module_id:
                raise ValueError("Ticket is absent, finished or belongs to another module")
            if current_inputs(snapshot, module_id) != attempt.inputs:
                raise ValueError("Ticket inputs have changed")
            if attempt.payload is not None:
                raise ValueError("A module response is already retained; resume its validation")
            completed = tuple(step for step in attempt.steps if step.status == "valid")
            if tuple(step.step_id for step in completed) != sequence[: len(completed)]:
                raise ValueError("Retained steps do not match the module sequence")
            if len(completed) >= len(sequence) or step_id != sequence[len(completed)]:
                raise ValueError("Submit the next module step in order")

            if len(attempt.steps) > len(completed):
                submission = attempt.steps[-1]
                if submission.status != "pending" or submission.payload != payload:
                    raise ValueError(
                        "Step already retains a different response; resume or interrupt"
                    )
                if submission.step_id != step_id:
                    raise ValueError("Pending step identity differs")
            else:
                submission = StepSubmission(
                    step_id=step_id,
                    payload=payload,
                    inputs=(
                        *attempt.inputs,
                        *(
                            Input(input_id="step:" + step.step_id, sha256=step.content_hash())
                            for step in completed
                        ),
                    ),
                )
                attempt = attempt.model_copy(update={"steps": (*attempt.steps, submission)})
                snapshot = with_attempt(snapshot, attempt)
                self._write(snapshot)

            outcome = StepValidation.model_validate_json(
                validator(snapshot.pack, attempt).model_dump_json()
            )
            if not outcome.issues and outcome.output is None:
                raise ValueError("Successful step validator must retain its output")
            submitted = submission.model_copy(
                update={
                    "status": "invalid" if outcome.issues else "valid",
                    "output": outcome.output,
                    "issues": outcome.issues,
                }
            )
            attempt = attempt.model_copy(update={"steps": (*completed, submitted)})
            if outcome.issues:
                candidate = Module(
                    run_id=snapshot.pack.run.run_id,
                    issuer_id=snapshot.pack.run.issuer_id,
                    as_of=snapshot.pack.run.as_of,
                    module_id=module_id,
                    inputs=attempt.inputs,
                    attempt=attempt.number,
                )
                finished = settle(
                    snapshot, attempt, candidate.model_dump_json(), lambda _: outcome.issues
                )
                self._save_finished(snapshot, finished)
                return finished
            self._write(with_attempt(snapshot, attempt))
            return attempt

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
                    tables=module.tables if visible and module else (),
                    claims=module.claims if visible and module else (),
                    limitations=(
                        tuple(dict.fromkeys((*module.limitations, *module.inherited_limitations)))
                        if module
                        else ()
                    ),
                )
            )
        return View(
            run=snapshot.pack.run,
            mode="candidate" if ticket_id else "accepted",
            modules=tuple(views),
            sources=snapshot.pack.sources,
        )
