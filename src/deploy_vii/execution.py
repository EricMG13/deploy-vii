"""Single-writer execution journal; immutable snapshots, bounded repair, current lineage.

A snapshot is small: the prepared pack and every response payload live once in
content-addressed blobs (`blobs/<sha256>`) that snapshots reference by hash.
Validators are trusted Python module implementations, never model-supplied verdicts.
The journal does not invoke models, spend money, or claim analytical qualification.
"""

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    model_serializer,
    model_validator,
)

from deploy_vii.contracts import (
    Claim,
    Contract,
    Fact,
    Hash,
    Identifier,
    Input,
    Module,
    ModuleView,
    Run,
    Text,
    View,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.prose import prose_issues
from deploy_vii.readiness import (
    NOT_CONSUMERS,
    Readiness,
    ReadinessAddendum,
    ReadinessAddendumSubmissionInput,
    citation_issues,
)
from deploy_vii.registry import (
    canonical,
    dependencies,
    edge_rule,
    idle_statuses,
    modules,
    plan,
    within_attempt_repair,
)

Validator = Callable[[Module], tuple[str, ...]]
SCHEMA = "execution/5"


class StepSubmission(Contract):
    step_id: Identifier
    inputs: tuple[Input, ...]
    payload_sha256: Hash
    status: Literal["pending", "valid", "invalid"] = "pending"
    output_sha256: Hash | None = None
    issues: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def coherent_state(self) -> Self:
        if self.status == "pending" and (self.output_sha256 is not None or self.issues):
            raise ValueError("Pending step cannot have a validation result")
        if self.status == "valid" and (self.output_sha256 is None or self.issues):
            raise ValueError("Valid step requires output and no issues")
        if self.status == "invalid" and not self.issues:
            raise ValueError("Invalid step requires issues")
        return self


class StepValidation(Contract):
    output: str | None = None
    issues: tuple[Text, ...] = ()

    def retained_as(self, step: "StepSubmission") -> bool:
        """Whether this recomputed output is exactly the output the step retains."""
        return (None if self.output is None else text_sha256(self.output)) == step.output_sha256


class Attempt(Contract):
    """One ticket of a module. `steps` are the retained steps in module order: the valid ones,
    then at most one pending or invalid entry where the attempt stopped. `step_repairs` holds
    each step's rejected first try that was repaired within this attempt (task 7.0g), in order;
    it is never part of `steps`, so positional step readers and content hashes ignore it, and it
    is omitted from the JSON while empty, so attempts written before it keep their bytes."""

    ticket_id: Identifier
    module_id: Identifier
    inputs: tuple[Input, ...]
    number: int = Field(ge=0, le=1)
    status: Literal["pending", "finished"] = "pending"
    repair_of: Identifier | None = None
    repair_issues: tuple[str, ...] = ()
    payload_sha256: Hash | None = None
    issues: tuple[str, ...] = ()
    result_sha256: Hash | None = None
    interruption: Text | None = None
    steps: tuple[StepSubmission, ...] = ()
    step_repairs: tuple[StepSubmission, ...] = ()

    @model_validator(mode="after")
    def bounded_step_repairs(self) -> Self:
        if any(item.status != "invalid" for item in self.step_repairs):
            raise ValueError("A step repair retains an invalid try")
        ids = [item.step_id for item in self.step_repairs]
        if len(ids) != len(set(ids)):
            raise ValueError("A step is repaired at most once per attempt")
        return self

    @model_serializer(mode="wrap")
    def _omit_empty_step_repairs(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if not self.step_repairs:
            data.pop("step_repairs", None)
        return data


# Decision 0008 MC-7 item 2 (task 7.0g): the steps that may be repaired once within their
# attempt. CP-1's four model steps; not its `quality` promotion step (it settles the module), and
# not CP-0's single review: those keep the attempt-level repair only. Derived from the
# registry's step chains (task 8.0a), which `cp1_workflow.CP1_STEPS` also reads.
WITHIN_ATTEMPT_REPAIR: Mapping[str, frozenset[str]] = within_attempt_repair()


class Command(Contract):
    """One CP-0 source-readiness command (a T8 `exact_command` fact), kept on the head."""

    row_id: Identifier
    text: str | None


class Qualification(Contract):
    """The plan's four statuses of one settled module artifact ("four statuses per module").

    They describe this artifact, not the module's coverage-map row: `implemented` means it
    passed every implemented structural gate; the other three stay `unrun` until a live,
    rendering or native-host test qualifies this artifact.
    """

    implementation: Literal["unrun", "partial", "implemented"]
    analytical_qualification: Literal["unrun", "partial", "qualified", "blocked"] = "unrun"
    rendering_acceptance: Literal["unrun", "partial", "accepted", "blocked"] = "unrun"
    native_host_qualification: Literal["unrun", "qualified", "blocked"] = "unrun"


class Head(Contract):
    """The current record of one module: a hash of its settled `Module` blob plus the few
    fields the journal reads on every transition, so no blob is loaded to resolve inputs.

    `status` and `notes` are the live state: staling changes them, never the blob.
    `qualification` holds the four statuses where a promotion recorded them (CP-1, task 6.4);
    absent, it is omitted from the JSON, so heads written before it keep their bytes and hashes.
    """

    module_id: Identifier
    status: Literal["accepted", "restricted", "blocked", "stale"]
    result_sha256: Hash
    inputs: tuple[Input, ...]
    commands: tuple[Command, ...] = ()
    notes: tuple[Text, ...] = ()
    qualification: Qualification | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_qualification(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.qualification is None:
            data.pop("qualification", None)
        return data


def commands_of(module: Module) -> tuple[Command, ...]:
    return tuple(
        Command(row_id=fact.row_id, text=fact.text)
        for fact in module.facts
        if fact.table_id == "T8" and fact.field == "exact_command"
    )


def head_of(result: Module, qualification: Qualification | None = None) -> Head:
    status = result.status
    if status not in ("accepted", "restricted", "blocked"):
        raise ValueError("Only an accepted, restricted or blocked module can be a head")
    return Head(
        module_id=result.module_id,
        status=status,
        result_sha256=result.content_hash(),
        inputs=result.inputs,
        commands=commands_of(result),
        # The statuses describe a promoted artifact; a blocked result never carries them.
        qualification=None if status == "blocked" else qualification,
    )


class ReadinessGrant(Contract):
    module_id: Identifier
    command: Text
    readiness: Readiness
    limitations: tuple[Text, ...]


class ReadinessAddendumRef(Contract):
    sha256: Hash
    pack_sha256: Hash
    cp0_result_sha256: Hash
    added_modules: tuple[Identifier, ...]
    grants: tuple[ReadinessGrant, ...]


def addendum_ref(addendum: ReadinessAddendum) -> ReadinessAddendumRef:
    return ReadinessAddendumRef(
        sha256=addendum.content_hash(),
        pack_sha256=addendum.context.pack_sha256,
        cp0_result_sha256=addendum.context.cp0_result_sha256,
        added_modules=addendum.context.added_modules,
        grants=tuple(
            ReadinessGrant(
                module_id=c.module_id,
                command=f"Run {c.module_id}"
                if c.readiness in {"READY", "READY_WITH_LIMITATIONS"}
                else "DO NOT RUN",
                readiness=c.readiness,
                limitations=tuple(
                    dict.fromkeys(
                        (
                            *c.limitations,
                            *(
                                g.description
                                for g in addendum.gaps
                                if c.module_id in g.affected_modules
                            ),
                        )
                    )
                ),
            )
            for c in addendum.consumers
        ),
    )


class ExecutionSnapshot(Contract):
    schema_version: Literal["execution/5"] = "execution/5"
    parent: Hash | None = None
    # Identity is immutable. `requested_modules` is the run's effective scope: it only extends
    # (`extend_scope`, task 9.1), so the pack blob carries the same run with a subset of it.
    run: Run
    pack_sha256: Hash  # SHA-256 of the canonical-JSON pack blob
    attempts: tuple[Attempt, ...] = ()
    heads: tuple[Head, ...] = ()
    readiness_addenda: tuple[ReadinessAddendumRef, ...] = ()

    @model_serializer(mode="wrap")
    def _omit_empty_addenda(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if not self.readiness_addenda:
            data.pop("readiness_addenda", None)
        return data


def readiness_command(
    snapshot: ExecutionSnapshot, module_id: str
) -> tuple[tuple[str | None, ...], ReadinessAddendumRef | None, ReadinessGrant | None]:
    head = next((h for h in snapshot.heads if h.module_id == "CP-0"), None)
    if head is None or head.status == "stale":
        return (), None, None
    original = tuple(c.text for c in head.commands if c.row_id == module_id)
    if original:
        return original, None, None
    matches = [
        (ref, grant)
        for ref in snapshot.readiness_addenda
        for grant in ref.grants
        if ref.pack_sha256 == snapshot.pack_sha256
        and ref.cp0_result_sha256 == head.result_sha256
        and head.status in {"accepted", "restricted"}
        and module_id in ref.added_modules
        and module_id in dependencies(snapshot.run.requested_modules)
        and grant.module_id == module_id
    ]
    if len(matches) > 1:
        raise ValueError("Ambiguous source-readiness addenda")
    if not matches:
        return (), None, None
    ref, grant = matches[0]
    return (grant.command,), ref, grant


class NotAuthorized(ValueError):
    """CP-0's head does not authorize this consumer: its T8 `exact_command` is not `Run <id>`.

    A ValueError like every other refusal here, so existing callers still fail closed. It is
    typed because a CP-0 that judges a consumer CONDITIONAL or BLOCKED is a valid accepted
    outcome (probe-4): the live batch runner records it as the step's result and ends the cell.
    `commands` holds the T8 `exact_command` texts found (empty when CP-0 has no head)."""

    def __init__(self, module_id: str, commands: tuple[str | None, ...]) -> None:
        super().__init__("CP-0 has not authorized this consumer's source readiness")
        self.module_id = module_id
        self.commands = commands


# Settled modules whose facts a consumer may reference without requiring them (CP-1A cites
# CP-1 figures as `{ref|unit}` only when CP-1 is settled; its registry edge stays CP-0 only).
CONTEXT_PRODUCERS: dict[str, tuple[str, ...]] = {"CP-1A": ("CP-1",)}


def current_inputs(snapshot: ExecutionSnapshot, module_id: str) -> tuple[Input, ...]:
    graph = dependencies(snapshot.run.requested_modules)
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
            return Input(input_id=item, sha256=head.result_sha256, status=head.status)
        if head.status == "blocked" and edge_rule(module_id, item) == "restricted":
            return Input(input_id=item, sha256=head.result_sha256, status="blocked")
        raise ValueError("Required upstream is unrun, stale or blocked")

    upstream = tuple(
        bound(item) for item in plan(snapshot.run.requested_modules) if item in required
    )
    # Task 7.2: a settled (accepted or restricted) context producer is bound when present, so
    # the figures a consumer cites from it are lineage and go stale with it; never required.
    context: list[Input] = []
    for item in CONTEXT_PRODUCERS.get(module_id, ()):
        head = heads.get(item)
        if item not in graph or item in required or head is None:
            continue
        if head.status == "accepted" or head.status == "restricted":
            context.append(Input(input_id=item, sha256=head.result_sha256, status=head.status))
    addendum_inputs: tuple[Input, ...] = ()
    if module_id not in NOT_CONSUMERS:
        commands, ref, grant = readiness_command(snapshot, module_id)
        if commands != (f"Run {module_id}",):
            raise NotAuthorized(module_id, commands)
        if ref is not None and grant is not None:
            addendum_inputs = (
                Input(
                    input_id="readiness-addendum",
                    sha256=ref.sha256,
                    status="accepted" if grant.readiness == "READY" else "restricted",
                ),
            )
    return (
        Input(input_id="prepared-pack", sha256=snapshot.pack_sha256),
        *upstream,
        *context,
        *addendum_inputs,
    )


def candidate_issues(
    snapshot: ExecutionSnapshot, attempt: Attempt, candidate: Module, *, pack: PreparedPack
) -> tuple[str, ...]:
    run = snapshot.run
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
        issues.extend(citation_issues(record.citations, pack.sources))
    # Decision 0005 MC-2: claim numbers are resolved references to this module's own facts.
    issues.extend(prose_issues(candidate, names=(run.issuer_name,)))
    return tuple(dict.fromkeys(issues))


def staled(head: Head, note: str) -> Head:
    """Mark a head stale with the first reason; a head that is already stale keeps its note."""
    if head.status == "stale":
        return head
    return head.model_copy(update={"status": "stale", "notes": (*head.notes, note)})


def invalidate(heads: tuple[Head, ...], changed: str) -> tuple[Head, ...]:
    affected = {changed}
    while True:
        expanded = affected | {
            head.module_id
            for head in heads
            if any(item.input_id in affected for item in head.inputs)
        }
        if expanded == affected:
            break
        affected = expanded
    return tuple(
        staled(head, f"Input changed: {changed}; rerun required")
        if head.module_id in affected and head.module_id != changed
        else head
        for head in heads
    )


# --- scope extension (task 9.1, decision 0005 MC-9) ------------------------------------------

Resolver = Callable[[str, Mapping[str, Head]], tuple[Input, ...]]
# A head's resolution: the inputs `current_inputs` binds now, or None where it refuses to bind
# (ValueError: an upstream unrun, stale or blocked under a block edge, or NotAuthorized).
Resolution = tuple[Input, ...] | None


def resolution(resolve: Resolver, module_id: str, heads: Mapping[str, Head]) -> Resolution:
    """`resolve`'s binding of `module_id`, or None when it refuses with ValueError.

    Only ValueError, the journal's refusal to bind, is a resolution outcome; anything else
    propagates."""
    try:
        return resolve(module_id, heads)
    except ValueError:
        return None


def _changed_ids(
    was: Resolution,
    now: Resolution,
    edges: Collection[str],
    current: Mapping[str, Head],
    order: Sequence[str],
) -> tuple[str, ...]:
    """The input ids whose binding differs between the two resolutions.

    Both resolved: ids whose (hash, status) differ or that appear or disappear; with the same
    bindings in another order, those whose position moved. Only the old one resolved: the
    upstream ids it bound that no longer bind as it bound them, then the producers the new
    graph adds. Otherwise, or when that names none, the fixed fallback: the module's upstream
    ids in the new graph, in plan order. Never exception text."""
    fallback = tuple(sorted(edges, key=order.index))
    if was is None:
        return fallback
    before = {item.input_id: item for item in was}
    if now is None:
        unbound = (
            item.input_id
            for item in was
            if item.input_id in current
            and (current[item.input_id].result_sha256, current[item.input_id].status)
            != (item.sha256, item.status)
        )
        added = (item for item in fallback if item not in before)
        return tuple(dict.fromkeys((*unbound, *added))) or fallback
    after = {item.input_id: item for item in now}
    ids = tuple(
        key for key in dict.fromkeys((*before, *after)) if before.get(key) != after.get(key)
    )
    if ids:
        return ids
    return tuple(old.input_id for old, new in zip(was, now, strict=True) if old != new)


def rebind_heads(
    order: Sequence[str],
    graph: Mapping[str, Collection[str]],
    heads: tuple[Head, ...],
    before: Mapping[str, Resolution],
    resolve: Resolver,
) -> tuple[Head, ...]:
    """The scope-extension staling rule (MC-9, fix round 1 ruling R1), without running anything.

    `before[module_id]` is the head's resolution before the extension (`current_inputs` on the
    old snapshot, None where it refused). Walks the heads in the new plan `order`, resolving
    each settled one with `resolve` under the new scope against the heads as already updated
    by this walk. A head is staled, with `Scope extended: inputs changed (<ids>); rerun
    required`, iff its new resolution differs from `before` (ids, hashes, statuses and order;
    exactly one side refusing counts as a difference, both refusing does not). So drift that
    predates the extension, such as a CP-1A settled before CP-1, is kept as it was. An
    already-stale head stays as it is. `graph` is the new dependency map
    (`registry.dependencies`), read only to name changed ids. Heads keep their tuple order;
    a head outside the new graph raises ValueError.
    """
    current = {head.module_id: head for head in heads}
    outside = sorted(set(current) - set(order))
    if outside:
        raise ValueError(f"Execution heads outside the run's dependency graph: {outside}")
    for module_id in order:
        head = current.get(module_id)
        if head is None or head.status == "stale":
            continue
        was, now = before[module_id], resolution(resolve, module_id, current)
        if now == was:
            continue
        ids = ", ".join(_changed_ids(was, now, graph.get(module_id, ()), current, order))
        current[module_id] = staled(head, f"Scope extended: inputs changed ({ids}); rerun required")
    return tuple(current[head.module_id] for head in heads)


def unassessed(
    added: Sequence[str], readiness: Head | None, snapshot: ExecutionSnapshot | None = None
) -> tuple[str, ...]:
    """Added modules CP-0 has no T8 `exact_command` row for (ruling B, task 9.1).

    CP-0, CP-MODEL, CP-MEMO and CP-OS need no readiness row. Any other added module needs a
    row (whatever its command) on a CP-0 head that is not stale; without one, every such
    module is unassessed (fail closed)."""
    rows = (
        set()
        if readiness is None or readiness.status == "stale"
        else {item.row_id for item in readiness.commands}
    )
    return tuple(
        item
        for item in added
        if item not in NOT_CONSUMERS
        and item not in rows
        and (snapshot is None or not readiness_command(snapshot, item)[0])
    )


class StaledHead(Contract):
    module_id: Identifier
    note: Text


class ExtendReport(Contract):
    """What `Execution.extend_scope` did. `extended` is False for a no-op (nothing written).

    `added`: modules new to the dependency graph, in plan order (no head; runnable as today).
    `kept`: heads this transition left unchanged (an already-stale head among them stays
    stale). `staled`: heads it staled, with their notes, in plan order. `plan`: the new plan.
    """

    extended: bool
    added: tuple[Identifier, ...]
    kept: tuple[Identifier, ...]
    staled: tuple[StaledHead, ...]
    plan: tuple[Identifier, ...]
    readiness_addendum_sha256: Hash | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_addendum(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.readiness_addendum_sha256 is None:
            data.pop("readiness_addendum_sha256", None)
        return data


def scope_within(blob: Run, effective: Run) -> bool:
    """`blob` is `effective` with its requested modules a subset: the same run before and after
    scope extensions (task 9.1). The pack blob against the snapshot, a CP-1 envelope against
    the view it is shown in."""
    return blob.model_dump(exclude={"requested_modules"}) == effective.model_dump(
        exclude={"requested_modules"}
    ) and set(blob.requested_modules) <= set(effective.requested_modules)


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
    snapshot: ExecutionSnapshot,
    attempt: Attempt,
    own: tuple[str, ...],
    load: Callable[[Head], Module],
) -> tuple[str, ...]:
    """Limitations carried by the bound inputs, de-duplicated and never repeating own findings.

    Loads the settled module of each directly bound head, and only here.
    """
    heads = {item.module_id: item for item in snapshot.heads}
    texts: list[str] = []
    for item in attempt.inputs:
        if item.input_id == "readiness-addendum":
            _, ref, grant = readiness_command(snapshot, attempt.module_id)
            if ref is None or grant is None or ref.sha256 != item.sha256:
                raise ValueError("Bound source-readiness addendum changed")
            texts.extend(grant.limitations)
            continue
        head = heads.get(item.input_id)
        if head is None:
            continue
        module = load(head)
        if item.status == "blocked":
            texts.extend(f"Upstream {item.input_id} blocked: {text}" for text in module.limitations)
        else:
            texts.extend((*module.limitations, *module.inherited_limitations))
    return tuple(text for text in dict.fromkeys(texts) if text not in own)


MAX_ISSUES = 20
# Task 7.0: an issue line holds a quote mismatch whole (a 200-character quoted fragment plus
# the clause saying why it failed), since the REPAIR prompt carries these lines.
MAX_ISSUE_CHARS = 600
MAX_INTERRUPTION_CHARS = 300


def shortened(text: str, limit: int = MAX_ISSUE_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def bounded_issues(issues: Sequence[str]) -> tuple[str, ...]:
    """At most 20 lines of at most 600 characters, then a count of the lines left out.

    Issue text can quote caller content (a citation locator, a field name), so no issue
    list reaches a snapshot unbounded.
    """
    shown = tuple(shortened(line) for line in issues[:MAX_ISSUES])
    rest = len(issues) - MAX_ISSUES
    return (*shown, f"{rest} further issues not listed") if rest > 0 else shown


def malformed_issues(error: ValidationError) -> tuple[str, ...]:
    """Schema errors as `loc: message` lines, without the input value or documentation URL."""
    return tuple(
        f"Malformed candidate: {'.'.join(map(str, item['loc'])) or '(root)'}: {item['msg']}"
        for item in error.errors(include_input=False, include_url=False, include_context=False)
    )


def settle(
    snapshot: ExecutionSnapshot,
    attempt: Attempt,
    payload: str,
    validator: Validator,
    interruption: str | None = None,
    *,
    pack: PreparedPack,
    load: Callable[[Head], Module],
) -> tuple[Attempt, Module]:
    """Retain every response; only valid current candidates can supply accepted facts.

    The attempt must already reference the stored blob of `payload`. Returns the finished
    attempt (carrying the result's hash) and the result, which the caller stores as a blob.
    """
    if attempt.payload_sha256 != text_sha256(payload):
        raise ValueError("Settled payload is not the retained response")
    candidate: Module | None = None
    try:
        candidate = Module.model_validate_json(payload)
        issues = candidate_issues(snapshot, attempt, candidate, pack=pack)
    except ValidationError as error:
        issues = malformed_issues(error)
    reason = None if interruption is None else shortened(interruption, MAX_INTERRUPTION_CHARS)
    if reason is not None:
        issues = (f"Interrupted: {reason}",)
    if candidate is not None and not issues:
        issues = validator(candidate)
    issues = bounded_issues(tuple(dict.fromkeys(issues)))
    if issues:
        result = Module(
            run_id=snapshot.run.run_id,
            issuer_id=snapshot.run.issuer_id,
            as_of=snapshot.run.as_of,
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
            if snapshot.run.case_kind == "synthetic"
            else ()
        )
        own = tuple(dict.fromkeys((*candidate.limitations, *synthetic)))
        inherited = inherited_limitations(snapshot, attempt, own, load)
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
    finished = attempt.model_copy(
        update={
            "status": "finished",
            "issues": issues,
            "result_sha256": result.content_hash(),
            "interruption": reason,
        }
    )
    return finished, result


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _require_hash(value: str, what: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"Invalid {what}")
    return value


def _atomic_write(path: Path, raw: bytes) -> None:
    """Write temp file, fsync, rename: readers see the old file or the whole new one."""
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _put_once(folder: Path, name: str, raw: bytes, what: str) -> None:
    """Content-addressed write, idempotent for identical bytes.

    Different bytes already at the path are corruption and are never overwritten.
    """
    path = folder / name
    if not path.exists():
        _atomic_write(path, raw)
    elif path.read_bytes() != raw:
        raise ValueError(f"Existing {what} is corrupt")


class Execution:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @classmethod
    def create(cls, directory: Path, pack: PreparedPack) -> "Execution":
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        plan(pack.run.requested_modules)
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "snapshots").mkdir()
        (directory / "blobs").mkdir()
        store = cls(directory)
        store._write(
            ExecutionSnapshot(run=pack.run, pack_sha256=store._store(pack.model_dump_json()))
        )
        return store

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with (self.directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _snapshot(self) -> ExecutionSnapshot:
        """Read metadata without following addendum refs; their verifier must not recurse."""
        digest = _require_hash(
            (self.directory / "current").read_text(encoding="ascii").strip(), "execution pointer"
        )
        raw = (self.directory / "snapshots" / (digest + ".json")).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Execution snapshot hash mismatch")
        probe = json.loads(raw)
        version = probe.get("schema_version") if isinstance(probe, dict) else None
        if version != SCHEMA:
            raise ValueError(
                f"Unsupported execution store schema {version!r}; this version reads {SCHEMA}. "
                "Retain the old store and create a new execution directory; nothing is migrated."
            )
        return ExecutionSnapshot.model_validate_json(raw)

    def read(self) -> ExecutionSnapshot:
        """Verify metadata, current CP-0 cache and the retained addendum authority chain."""
        snapshot = self._snapshot()
        self._verified_addenda(snapshot)
        return snapshot

    def readiness_addendum(self, ref: ReadinessAddendumRef) -> ReadinessAddendum:
        """A grant is authority only as a member of the authenticated snapshot history."""
        snapshot = self._snapshot()
        if snapshot.readiness_addenda.count(ref) != 1:
            raise ValueError("Source-readiness addendum ref is absent or ambiguous")
        return self._verified_addenda(snapshot)[ref.sha256]

    def _verified_addenda(self, snapshot: ExecutionSnapshot) -> dict[str, ReadinessAddendum]:
        from deploy_vii.cp0_workflow import _original_review

        # Original-command priority requires the actual cache, even if all refs were removed.
        head = next((h for h in snapshot.heads if h.module_id == "CP-0"), None)
        if head is not None:
            self.head_module(head)
        verified: dict[str, ReadinessAddendum] = {}
        for ref in snapshot.readiness_addenda:
            if ref.sha256 in verified:
                raise ValueError("Duplicate source-readiness addendum history")
            addendum = self._read_addendum(ref)
            context = addendum.context
            pack = PreparedPack.model_validate_json(self._load(context.pack_sha256))
            if not scope_within(pack.run, snapshot.run):
                raise ValueError("Source-readiness addendum belongs to a different run or scope")
            # Historical grants keep their own pack/producer, even after a legitimate refresh.
            producer = self.result(context.cp0_result_sha256)
            baseline = snapshot.model_copy(
                update={
                    "run": pack.run,
                    "pack_sha256": context.pack_sha256,
                    "heads": (head_of(producer),),
                    "readiness_addenda": (),
                }
            )
            if _original_review(self, baseline) != context.original_review:
                raise ValueError("Source-readiness addendum differs from its retained CP-0 review")
            prior = tuple(
                a
                for a in verified.values()
                if a.context.pack_sha256 == context.pack_sha256
                and a.context.cp0_result_sha256 == context.cp0_result_sha256
            )
            if (
                context.previous_addenda != tuple(a.content_hash() for a in prior)
                or context.prior_consumers != tuple(c for a in prior for c in a.consumers)
                or context.prior_gaps != tuple(g for a in prior for g in a.gaps)
                or context.prior_analysis != tuple(c for a in prior for c in a.analysis)
            ):
                raise ValueError("Source-readiness addendum history or projection differs")
            held = {canonical(m) for m in context.base_requested_modules}
            wanted = tuple(dict.fromkeys(canonical(m) for m in context.target_requested_modules))
            extended = (*context.base_requested_modules, *(m for m in wanted if m not in held))
            added = tuple(
                m for m in plan(extended) if m not in dependencies(context.base_requested_modules)
            )
            if (
                not held < set(wanted)
                or extended != context.target_requested_modules
                or added != context.added_modules
                or not {canonical(m) for m in pack.run.requested_modules} <= held
                or not set(wanted) <= {canonical(m) for m in snapshot.run.requested_modules}
                or any(
                    not {canonical(m) for m in a.context.target_requested_modules} <= held
                    for a in prior
                )
            ):
                raise ValueError("Source-readiness addendum scope or closure differs")
            verified[ref.sha256] = addendum
        return verified

    def _read_addendum(self, ref: ReadinessAddendumRef) -> ReadinessAddendum:
        """Check retained bytes/composition; authority additionally needs the verified history."""
        from deploy_vii.cp0_workflow import _check_addendum

        addendum = ReadinessAddendum.model_validate_json(self._load(ref.sha256))
        if addendum.content_hash() != ref.sha256 or addendum_ref(addendum) != ref:
            raise ValueError("Source-readiness addendum cache does not match its blob")
        if self.payload(addendum.context.content_hash()) != addendum.context.model_dump_json():
            raise ValueError("Source-readiness addendum context does not match its blob")
        pack = PreparedPack.model_validate_json(self._load(addendum.context.pack_sha256))
        if pack.content_hash() != addendum.context.pack_sha256:
            raise ValueError("Source-readiness addendum pack is not canonical")
        rebuilt = _check_addendum(pack, addendum.context, self.payload(addendum.payload_sha256))
        if rebuilt != addendum:
            raise ValueError("Source-readiness addendum differs from trusted composition")
        return addendum

    def _store(self, text: str) -> str:
        """Write `text` once as a blob and return its SHA-256 (idempotent for the same bytes)."""
        raw = text.encode()
        sha256 = hashlib.sha256(raw).hexdigest()
        _put_once(self.directory / "blobs", sha256, raw, "execution blob")
        return sha256

    def _load(self, sha256: str) -> bytes:
        path = self.directory / "blobs" / _require_hash(sha256, "blob hash")
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise ValueError(f"Execution blob {sha256} is missing") from None
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError(f"Execution blob {sha256} hash mismatch")
        return raw

    def payload(self, sha256: str) -> str:
        """Return the retained response text for a payload hash, verified against its bytes."""
        return self._load(sha256).decode()

    def step_output(self, sha256: str) -> str:
        """Return a step's validated output text, verified against its bytes."""
        return self._load(sha256).decode()

    def result(self, sha256: str) -> Module:
        """Return a settled module from its blob; the bytes must be its canonical JSON."""
        module = Module.model_validate_json(self._load(sha256))
        if module.content_hash() != sha256:
            raise ValueError("Execution result blob is not the canonical module")
        return module

    def head_module(self, head: Head) -> Module:
        """The head's module as currently known: its blob, checked against the head record,
        with the head's live status and staleness notes applied."""
        module = self.result(head.result_sha256)
        if module.module_id != head.module_id or module.inputs != head.inputs:
            raise ValueError("Execution head does not match its result blob")
        if commands_of(module) != head.commands:
            raise ValueError("Execution head commands do not match its result blob")
        # A head only ever holds a settled module; staleness is the head's, not the blob's.
        is_settled = module.status in ("accepted", "restricted", "blocked")
        if not is_settled or head.status not in ("stale", module.status):
            raise ValueError("Execution head status does not match its result blob")
        if head.status == "stale":
            return module.model_copy(
                update={"status": "stale", "limitations": (*module.limitations, *head.notes)}
            )
        return module

    def pack(self, snapshot: ExecutionSnapshot | None = None) -> PreparedPack:
        """Return the prepared pack of `snapshot` (default: the current one), verified.

        The blob's run is the snapshot's except that its requested modules may be a subset of
        the snapshot's effective set (task 9.1): the blob keeps the scope it was prepared with.
        """
        snapshot = self.read() if snapshot is None else snapshot
        pack = PreparedPack.model_validate_json(self._load(snapshot.pack_sha256))
        if not scope_within(pack.run, snapshot.run) or pack.content_hash() != snapshot.pack_sha256:
            raise ValueError("Execution pack blob is not the canonical pack of this snapshot")
        return pack

    def _write(self, snapshot: ExecutionSnapshot) -> None:
        # Snapshots are small: the pack and payloads are referenced by hash, never embedded.
        raw = snapshot.model_dump_json().encode()
        digest = hashlib.sha256(raw).hexdigest()
        _put_once(self.directory / "snapshots", digest + ".json", raw, "execution snapshot")
        _atomic_write(self.directory / "current", (digest + "\n").encode("ascii"))

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
        self,
        ticket_id: str,
        payload: str,
        validator: Validator,
        *,
        interruption: str | None = None,
        qualification: Qualification | None = None,
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

            retained = (
                None if attempt.payload_sha256 is None else self.payload(attempt.payload_sha256)
            )
            if interruption is not None:
                if not interruption.strip():
                    raise ValueError("An interruption requires a reason")
                if retained is not None:
                    payload = retained
            if retained is not None and retained != payload:
                raise ValueError(
                    "Ticket already retains a different response; finish or interrupt it"
                )
            if retained is None:
                attempt = attempt.model_copy(update={"payload_sha256": self._store(payload)})
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

            finished, result = settle(
                snapshot,
                attempt,
                payload,
                validator,
                interruption,
                pack=self.pack(snapshot),
                load=self.head_module,
            )
            self._save_finished(snapshot, finished, result, qualification)
            return finished

    def _save_finished(
        self,
        snapshot: ExecutionSnapshot,
        finished: Attempt,
        result: Module,
        qualification: Qualification | None = None,
    ) -> None:
        """Caller holds the execution lock; preserve the existing invalidation policy."""
        if self._store(result.model_dump_json()) != finished.result_sha256:
            raise ValueError("Settled result is not the attempt's result")
        heads = invalidate(snapshot.heads, finished.module_id)
        if result.status != "rejected":
            heads = (
                *tuple(h for h in heads if h.module_id != finished.module_id),
                head_of(result, qualification),
            )
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

        Sequence and validator come from the module implementation. An invalid response to
        a `WITHIN_ATTEMPT_REPAIR` step that has not been repaired in this attempt moves to
        `step_repairs` and the attempt stays pending: the next submission of the same step
        is its one repair (task 7.0g). Any other invalid response finishes this attempt, so
        a step gets at most two tries per attempt. Validator exceptions leave its exact
        input pending for resumption. A valid step is not module acceptance.
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
            if attempt.payload_sha256 is not None:
                raise ValueError("A module response is already retained; resume its validation")
            completed = tuple(step for step in attempt.steps if step.status == "valid")
            if tuple(step.step_id for step in completed) != sequence[: len(completed)]:
                raise ValueError("Retained steps do not match the module sequence")
            if len(completed) >= len(sequence) or step_id != sequence[len(completed)]:
                raise ValueError("Submit the next module step in order")

            if len(attempt.steps) > len(completed):
                submission = attempt.steps[-1]
                if submission.status != "pending" or submission.payload_sha256 != text_sha256(
                    payload
                ):
                    raise ValueError(
                        "Step already retains a different response; resume or interrupt"
                    )
                if submission.step_id != step_id:
                    raise ValueError("Pending step identity differs")
            else:
                submission = StepSubmission(
                    step_id=step_id,
                    payload_sha256=self._store(payload),
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

            pack = self.pack(snapshot)
            outcome = StepValidation.model_validate_json(validator(pack, attempt).model_dump_json())
            if not outcome.issues and outcome.output is None:
                raise ValueError("Successful step validator must retain its output")
            submitted = submission.model_copy(
                update={
                    "status": "invalid" if outcome.issues else "valid",
                    "output_sha256": None
                    if outcome.output is None
                    else self._store(outcome.output),
                    "issues": bounded_issues(outcome.issues),
                }
            )
            repairable = step_id in WITHIN_ATTEMPT_REPAIR.get(module_id, frozenset())
            if (
                outcome.issues
                and repairable
                and all(item.step_id != step_id for item in attempt.step_repairs)
            ):
                # The step's first rejection: retained apart from `steps`, and the attempt stays
                # pending (no settlement, no head, the module-wide repair untouched).
                attempt = attempt.model_copy(
                    update={"steps": completed, "step_repairs": (*attempt.step_repairs, submitted)}
                )
                self._write(with_attempt(snapshot, attempt))
                return attempt
            attempt = attempt.model_copy(update={"steps": (*completed, submitted)})
            if outcome.issues:
                empty = Module(
                    run_id=snapshot.run.run_id,
                    issuer_id=snapshot.run.issuer_id,
                    as_of=snapshot.run.as_of,
                    module_id=module_id,
                    inputs=attempt.inputs,
                    attempt=attempt.number,
                ).model_dump_json()
                attempt = attempt.model_copy(update={"payload_sha256": self._store(empty)})
                finished, result = settle(
                    snapshot,
                    attempt,
                    empty,
                    lambda _: outcome.issues,
                    pack=pack,
                    load=self.head_module,
                )
                self._save_finished(snapshot, finished, result)
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
        pack_json = pack.model_dump_json()
        with self._locked():
            snapshot = self.read()
            # Identity never changes. The scope is the snapshot's effective set or the scope of
            # the pack blob it replaces (task 9.1); before any extension the two are one run.
            same_identity = pack.run.model_dump(exclude={"requested_modules"}) == (
                snapshot.run.model_dump(exclude={"requested_modules"})
            )
            if not same_identity or (
                pack.run != snapshot.run and pack.run != self.pack(snapshot).run
            ):
                raise ValueError("Run identity and scope are immutable; create a new execution")
            if any(item.status == "pending" for item in snapshot.attempts):
                raise ValueError("Cannot change evidence while an attempt is pending")
            if text_sha256(pack_json) == snapshot.pack_sha256:
                return
            heads = tuple(
                staled(item, "Prepared pack changed; rerun required") for item in snapshot.heads
            )
            self._write(
                snapshot.model_copy(
                    update={
                        "parent": snapshot.content_hash(),
                        "pack_sha256": self._store(pack_json),
                        "heads": heads,
                    }
                )
            )

    def extend_scope(
        self,
        requested: Sequence[str],
        *,
        readiness_addendum: ReadinessAddendumSubmissionInput | None = None,
    ) -> ExtendReport:
        """Extend the run's requested modules to the superset `requested` (MC-9, task 9.1).

        Refusals, in order, write nothing: a pending attempt; an unknown module; a set that is
        not a superset of the current one; then, unless the set is unchanged (a no-op report),
        any module new to the dependency graph that CP-0 has not assessed (`unassessed`).
        Otherwise one transition records the extended set on `snapshot.run` (the pack blob is
        not rewritten) and rebinds every settled head under the new graph (`rebind_heads`):
        only the heads whose `current_inputs` resolution the extension changes are staled
        (drift that predates it stays as it was). Nothing runs.
        """
        with self._locked():
            snapshot = self.read()
            if any(item.status == "pending" for item in snapshot.attempts):
                raise ValueError("Cannot change scope while an attempt is pending")
            wanted = tuple(dict.fromkeys(canonical(entry) for entry in requested))
            old = snapshot.run.requested_modules
            held = {canonical(entry) for entry in old}
            if not held <= set(wanted):
                raise ValueError("Scope only extends; create a new execution to remove modules")
            if set(wanted) == held:
                return ExtendReport(
                    extended=False,
                    added=(),
                    kept=tuple(head.module_id for head in snapshot.heads),
                    staled=(),
                    plan=plan(old),
                )
            extended = (*old, *(item for item in wanted if item not in held))
            order = plan(extended)
            in_graph = dependencies(old)
            added = tuple(item for item in order if item not in in_graph)
            candidate_addendum = None
            refs = snapshot.readiness_addenda
            if readiness_addendum is not None:
                from deploy_vii.cp0_workflow import _addendum_context, _check_addendum

                context = _addendum_context(self, snapshot, extended, added)
                if context.content_hash() != readiness_addendum.context_sha256:
                    raise ValueError("Source-readiness addendum context changed")
                candidate_addendum = _check_addendum(
                    self.pack(snapshot), context, readiness_addendum.payload
                )
                refs = (*refs, addendum_ref(candidate_addendum))
            run = snapshot.run.model_copy(update={"requested_modules": extended})
            proposed = snapshot.model_copy(update={"run": run, "readiness_addenda": refs})
            readiness = next((head for head in snapshot.heads if head.module_id == "CP-0"), None)
            missing = unassessed(added, readiness, proposed)
            if missing:
                raise ValueError(
                    f"CP-0 has not assessed {', '.join(missing)}; create a new execution"
                )

            def resolve(module_id: str, current: Mapping[str, Head]) -> tuple[Input, ...]:
                probe = proposed.model_copy(update={"heads": tuple(current.values())})
                return current_inputs(probe, module_id)

            def previous(module_id: str, _heads: Mapping[str, Head]) -> tuple[Input, ...]:
                return current_inputs(snapshot, module_id)

            before = {
                head.module_id: resolution(previous, head.module_id, {}) for head in snapshot.heads
            }
            heads = rebind_heads(order, dependencies(extended), snapshot.heads, before, resolve)
            changed = {
                new.module_id: new.notes[-1]
                for old_head, new in zip(snapshot.heads, heads, strict=True)
                if new != old_head
            }
            report = ExtendReport(
                extended=True,
                added=added,
                kept=tuple(head.module_id for head in heads if head.module_id not in changed),
                staled=tuple(
                    StaledHead(module_id=item, note=changed[item])
                    for item in order
                    if item in changed
                ),
                plan=order,
                readiness_addendum_sha256=None
                if candidate_addendum is None
                else candidate_addendum.content_hash(),
            )
            if candidate_addendum is not None:
                assert readiness_addendum is not None
                self._store(readiness_addendum.payload)
                self._store(candidate_addendum.context.model_dump_json())
                self._store(candidate_addendum.model_dump_json())
            self._write(  # last: every refusal and failure above leaves the journal unchanged
                snapshot.model_copy(
                    update={
                        "parent": snapshot.content_hash(),
                        "run": run,
                        "heads": heads,
                        "readiness_addenda": refs,
                    }
                )
            )
            return report

    def view(self, ticket_id: str | None = None) -> View:
        snapshot = self.read()
        pack = self.pack(snapshot)
        heads = {item.module_id: self.head_module(item) for item in snapshot.heads}
        if ticket_id is not None:
            attempt = next(
                (item for item in snapshot.attempts if item.ticket_id == ticket_id), None
            )
            if attempt is None:
                raise ValueError("Unknown candidate ticket")
            if attempt.payload_sha256 is None:
                raise ValueError("Pending attempt has no candidate preview")
            if current_inputs(snapshot, attempt.module_id) != attempt.inputs:
                raise ValueError("Candidate inputs are stale")
            candidate = Module.model_validate_json(self.payload(attempt.payload_sha256))
            if candidate_issues(snapshot, attempt, candidate, pack=pack):
                raise ValueError("Invalid candidate identity or provenance cannot render")
            heads[attempt.module_id] = candidate
        views: list[ModuleView] = []
        idle = idle_statuses(snapshot.run)  # the effective scope, extended or not (task 9.1)
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
                    status=module.status if module else idle[entry.module_id],
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
            run=snapshot.run,
            mode="candidate" if ticket_id else "accepted",
            modules=tuple(views),
            sources=pack.sources,
        )
