"""One entry point for the module steps the `execution` CLI submits (task M8b).

CP-0 and CP-1 keep their own commands (`cp0-submit`, `cp1-submit`); every other registered
module has one `submit_<m>_step(store, ticket_id, step_id, payload)` function, gathered here
by module id so the host's agent submits a step it wrote through one command.
"""

from collections.abc import Callable, Mapping

from deploy_vii.business_context import context_block as cp1a_context_block
from deploy_vii.business_context import (
    cp1_context_facts,
    submit_cp1a_step,
)
from deploy_vii.cp2_synthesis import submit_cp2_step
from deploy_vii.cp3_relative_value import submit_cp3_step
from deploy_vii.cp4_legal import submit_cp4_step
from deploy_vii.cp5_integrity import submit_cp5_step
from deploy_vii.cp6_committee import submit_cp6_step
from deploy_vii.execution import Attempt, Execution
from deploy_vii.live.context import declared_sources, integrity_scope, module_context
from deploy_vii.live.prompts import INTEGRITY_BLOCK_ID, PromptError, build, span_line
from deploy_vii.live.runner import StepSpec, expected_step, prompt_inputs, repair_prompt
from deploy_vii.preparation import PreparedPack
from deploy_vii.registry import step_chain

ModuleSubmit = Callable[[Execution, str, str, str], Attempt]

MODULE_SUBMITS: Mapping[str, ModuleSubmit] = {
    "CP-1A": submit_cp1a_step,
    "CP-2": submit_cp2_step,
    "CP-3": submit_cp3_step,
    "CP-4": submit_cp4_step,
    "CP-5": submit_cp5_step,
    "CP-6": submit_cp6_step,
}


def submit_module_step(
    store: Execution, module_id: str, ticket_id: str, step_id: str, payload: str
) -> Attempt:
    """Submit `payload` as `step_id` of `module_id` on `ticket_id`; an unknown module or a step
    outside the module's registry chain is refused naming the valid choices."""
    submit = MODULE_SUBMITS.get(module_id)
    if submit is None:
        raise ValueError(f"Unknown module {module_id}; choose one of {', '.join(MODULE_SUBMITS)}")
    steps = step_chain(module_id).steps
    if step_id not in steps:
        raise ValueError(
            f"{step_id} is not a step of {module_id}; choose one of {', '.join(steps)}"
        )
    return submit(store, ticket_id, step_id, payload)


def host_context(store: Execution, attempt: Attempt, step_id: str) -> dict[str, object] | None:
    """Every CONTEXT entry the live runner adds to the prepared-pack block for `step_id` on
    `attempt`, composed from the runner's own functions (`live.runner.prompt_inputs`,
    `live.prompts._context_body` and the scope block): the module context of CP-2, CP-3, CP-4
    and CP-6; CP-1A's CP-1 facts block; CP-5's review scope under its block id. None for a step
    with nothing."""
    if step_id == "business_context":
        return cp1a_context_block(store.pack(), cp1_context_facts(store, attempt))
    if step_id == "integrity_review":
        return {INTEGRITY_BLOCK_ID: integrity_scope(store, attempt)}
    return module_context(store, attempt, step_id)


def step_instructions(
    store: Execution, module_id: str, ticket_id: str, step_id: str, *, with_sources: bool
) -> str:
    """What the live runner would send for `step_id`, the next step of `ticket_id`: each
    message of `live.prompts.build` (contract, rules, JSON Schema, CONTEXT, upstream, REPAIR)
    under a `--- <role> ---` line, built by the runner's own seams (`prompt_inputs`,
    `repair_prompt`, `declared_sources`), so the host's agent reads what the runner's model does.

    With `with_sources` the messages are the runner's byte for byte. Without, the declared SOURCE
    blocks are left out of the user message and one `source:` line per declared source names the
    pack file the agent reads itself. A ticket or step the runner would not build the prompt for
    raises ValueError with the runner's message (a `PromptError` is one)."""
    snapshot = store.read()
    attempt = next((item for item in snapshot.attempts if item.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != module_id:
        raise ValueError(f"{ticket_id} is not a {module_id} ticket")
    steps = step_chain(module_id).steps
    if step_id not in steps:
        raise ValueError(
            f"{step_id} is not a step of {module_id}; choose one of {', '.join(steps)}"
        )
    expected = expected_step(attempt, module_id)
    if expected != step_id:
        raise ValueError(f"{step_id} is not the next step for this ticket; {expected} is")
    pack = store.pack(snapshot)
    declared = declared_sources(store, attempt, step_id, [s.source_id for s in pack.sources])
    spec = StepSpec(step_id, "step-instructions", declared)
    inputs = prompt_inputs(store, attempt, step_id)
    try:
        messages = build(
            step_id,
            pack,
            declared if with_sources else (),
            spec.schema,
            upstream=inputs.upstream,
            repair_issues=repair_prompt(snapshot, attempt, step_id).issues,
            cp1_facts=inputs.cp1_facts,
            module_context=inputs.module_context,
            scope=inputs.scope,
        )
    except PromptError as refusal:
        raise ValueError(str(refusal)) from refusal
    shown = "".join(f"--- {message.role} ---\n{message.content}\n" for message in messages)
    if with_sources:
        return shown
    return shown + "".join(_source_line(pack, source_id) + "\n" for source_id in declared)


def _source_line(pack: PreparedPack, source_id: str) -> str:
    """Where the host's agent reads a declared source: the original under `originals/` in the
    pack directory by its hash, with the byte length of the extracted text the runner would
    send for it (the original's own size is not in the journal)."""
    source = next(item for item in pack.sources if item.source_id == source_id)
    if source.status != "ready" or source.sha256 is None:
        return f"source: {source_id} -> unavailable ({source.status}): {source.limitation}"
    text = "\n".join(span_line(span) for span in source.spans)
    return (
        f"source: {source_id} -> originals/{source.sha256} "
        f"({len(text.encode())} bytes, sha256 {source.sha256})"
    )
