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
from deploy_vii.live.context import integrity_scope, module_context
from deploy_vii.live.prompts import INTEGRITY_BLOCK_ID
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
