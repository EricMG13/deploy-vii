"""M8b: the execution CLI submits every registered module step and renders the report.

SYNTHETIC data only: the journal is the CP-2 test's (CP-0, CP-1 and CP-1A settled over the
readiness fixture) and the reviews are the module tests' accepted fixtures
(`test_business_context.submission_fixture`, `test_cp2_synthesis.synthesis`).
"""

from pathlib import Path

import pytest

from deploy_vii import registry
from deploy_vii.module_submits import MODULE_SUBMITS, submit_module_step
from tests.product.test_cp2_synthesis import journal

# What the live runner pins (`live.runner.MODULE_STEP_ENTRIES`), written out by hand so the
# CLI's table is held to the same modules without importing the runner.
LIVE_MODULES = {"CP-1A", "CP-2", "CP-3", "CP-4", "CP-5", "CP-6"}


def test_every_registered_module_but_cp0_and_cp1_has_a_submit() -> None:
    chained = {chain.module_id for chain in registry.STEP_CHAINS} - {"CP-0", "CP-1"}
    assert set(MODULE_SUBMITS) == chained == LIVE_MODULES


@pytest.mark.parametrize("module_id", sorted(LIVE_MODULES))
def test_a_step_outside_the_chain_is_refused_naming_the_valid_choices(
    tmp_path: Path, module_id: str
) -> None:
    store = journal(tmp_path)
    steps = registry.step_chain(module_id).steps
    with pytest.raises(ValueError, match="not a step of") as refused:
        submit_module_step(store, module_id, "t", "no_such_step", "{}")
    assert all(step in str(refused.value) for step in steps)


def test_an_unknown_module_is_refused_naming_the_valid_choices(tmp_path: Path) -> None:
    store = journal(tmp_path)
    with pytest.raises(ValueError, match="Unknown module") as refused:
        submit_module_step(store, "CP-9", "t", "x", "{}")
    assert all(module in str(refused.value) for module in LIVE_MODULES)
