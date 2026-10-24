"""The per-module step tables (task 8.0a, M7 whole-lane review F3).

The pins hold the hand-kept values of base ceba3dc literally: every table the live runner,
the journal and the CLI read must keep exactly these values, whichever code builds them.
"""

from typing import Literal

import pytest

from deploy_vii.business_context import BusinessContextSubmission
from deploy_vii.cp1_workflow import CP1_PROMOTION, CP1_STEPS, FinancialSubmission
from deploy_vii.downstream_readiness import DownstreamReview
from deploy_vii.execution import WITHIN_ATTEMPT_REPAIR, Attempt, StepSubmission
from deploy_vii.live import cli, context, runner
from deploy_vii.live.reconcile import _run_identity
from deploy_vii.live.submission import BOUND_STEPS, PREFILLED, STEPS, ReadinessSubmission
from deploy_vii.narrative import NarrativeReview
from deploy_vii.quality import QualityReview
from deploy_vii.source_context import SourceContextReview

HASH = "0" * 64

BASE_STEPS = (
    ("source_readiness", "CP-0", ReadinessSubmission),
    ("source_context", "CP-1", SourceContextReview),
    ("financials", "CP-1", FinancialSubmission),
    ("narrative", "CP-1", NarrativeReview),
    ("readiness", "CP-1", DownstreamReview),
    ("quality", "CP-1", QualityReview),
    ("business_context", "CP-1A", BusinessContextSubmission),
)
BASE_PREFILLED = {
    "source_context": frozenset({"pack", "source"}),
    "financials": frozenset(
        {
            "context-step",
            "pack",
            "source",
            "source-context-review",
            "facility",
            "annual-observation",
            "quarter-observations",
            "financial-review",
            "scope-dimension",
        }
    ),
    "narrative": frozenset({"step-inputs"}),
    "readiness": frozenset({"step-inputs"}),
    "quality": frozenset({"quality-inputs"}),
}
BASE_BOUND_STEPS = {
    "source_context": (),
    "financials": ("source_context",),
    "narrative": ("source_context", "financials"),
    "readiness": ("source_context", "financials", "narrative"),
    "quality": ("source_context", "financials", "narrative", "readiness"),
}
BASE_WITHIN_ATTEMPT_REPAIR = {
    "CP-1": frozenset({"source_context", "financials", "narrative", "readiness"})
}
BASE_PROJECTIONS = {
    ("financials", "source_context"): "full",
    ("narrative", "source_context"): "omitted",
    ("narrative", "financials"): "narrative-evidence",
    ("readiness", "source_context"): "omitted",
    ("readiness", "financials"): "omitted",
    ("readiness", "narrative"): "readiness-inputs",
    ("quality", "source_context"): "omitted",
    ("quality", "financials"): "omitted",
    ("quality", "narrative"): "omitted",
    ("quality", "readiness"): "omitted",
}
BASE_PACK_SOURCE_STEPS = frozenset(
    {"source_readiness", "source_context", "financials", "business_context"}
)
BASE_CP1_PROMOTION = ("source_context", "financials", "narrative", "readiness", "quality")
BASE_CP0_STEPS = ("source_readiness",)
BASE_FULL_CHAIN = ("source_readiness", *BASE_CP1_PROMOTION)
BASE_CP1A_CHAIN = ("source_readiness", "business_context")
BASE_REGRESSION_CASES = (
    ("cp0", BASE_CP0_STEPS),
    ("cp1", BASE_FULL_CHAIN),
    ("cp1a", BASE_CP1A_CHAIN),
)
BASE_MODULE_ROUTES = {"CP-0": BASE_CP0_STEPS, "CP-1": BASE_FULL_CHAIN, "CP-1A": BASE_CP1A_CHAIN}


def attempt(module_id: str, *steps: tuple[str, Literal["valid", "invalid"]]) -> Attempt:
    """A pending ticket of `module_id` retaining `steps` as (step id, status)."""
    retained = tuple(
        StepSubmission(
            step_id=step_id,
            inputs=(),
            payload_sha256=HASH,
            status=status,
            output_sha256=HASH if status == "valid" else None,
            issues=("Rejected",) if status == "invalid" else (),
        )
        for step_id, status in steps
    )
    return Attempt(ticket_id="t", module_id=module_id, inputs=(), number=0, steps=retained)


def test_the_step_tables_keep_their_base_values() -> None:
    assert [(step_id, d.module_id, d.schema) for step_id, d in STEPS.items()] == list(BASE_STEPS)
    assert dict(PREFILLED) == BASE_PREFILLED
    assert dict(BOUND_STEPS) == BASE_BOUND_STEPS
    assert dict(WITHIN_ATTEMPT_REPAIR) == BASE_WITHIN_ATTEMPT_REPAIR
    assert dict(context.PROJECTIONS) == BASE_PROJECTIONS
    assert context.PACK_SOURCE_STEPS == BASE_PACK_SOURCE_STEPS
    assert CP1_PROMOTION == BASE_CP1_PROMOTION and CP1_STEPS == BASE_CP1_PROMOTION[:4]
    assert cli.CP0_STEPS == BASE_CP0_STEPS and cli.CP1_CHAIN == BASE_CP1_PROMOTION
    assert cli.FULL_CHAIN == BASE_FULL_CHAIN and cli.CP1A_CHAIN == BASE_CP1A_CHAIN
    assert cli.REGRESSION_CASES == BASE_REGRESSION_CASES


@pytest.mark.parametrize("module_id", sorted(BASE_MODULE_ROUTES))
def test_a_module_cell_runs_its_base_route(module_id: str) -> None:
    (cell,) = cli._module_cells(module_id, 7)
    assert cell.steps == BASE_MODULE_ROUTES[module_id]
    assert (cell.cell_id, cell.case_id, cell.seed) == ("module-00", module_id.lower(), 7)


def test_a_module_without_a_live_step_contract_is_refused_with_the_base_wording() -> None:
    with pytest.raises(cli.CliError, match=r"CP-2 has no live step contract; supported: "):
        cli._module_cells("CP-2", 7)
    with pytest.raises(cli.CliError, match=r"supported: CP-0, CP-1, CP-1A$"):
        cli._module_cells("CP-2", 7)


@pytest.mark.parametrize(
    ("module_id", "chain"),
    [("CP-0", BASE_CP0_STEPS), ("CP-1", BASE_CP1_PROMOTION), ("CP-1A", ("business_context",))],
)
def test_the_next_step_walks_each_base_chain(module_id: str, chain: tuple[str, ...]) -> None:
    for done in range(len(chain)):
        held = attempt(module_id, *((step_id, "valid") for step_id in chain[:done]))
        assert runner.expected_step(held, module_id) == chain[done]


@pytest.mark.parametrize(
    ("module_id", "chain", "message"),
    [
        ("CP-0", BASE_CP0_STEPS, "CP-0 already retains its review step; resume it through"),
        ("CP-1", BASE_CP1_PROMOTION, "every CP-1 step is already retained"),
        ("CP-1A", ("business_context",), "CP-1A already retains its one step; resume it"),
    ],
)
def test_a_complete_chain_is_refused_with_the_base_wording(
    module_id: str, chain: tuple[str, ...], message: str
) -> None:
    held = attempt(module_id, *((step_id, "valid") for step_id in chain))
    with pytest.raises(ValueError, match=message):
        runner.expected_step(held, module_id)


def test_the_run_identity_reads_every_base_step_in_base_order() -> None:
    for step_id, _, _ in BASE_STEPS:
        assert _run_identity(f"case-1-{step_id}-2") == {"ticket_id": "case-1", "step_id": step_id}
        assert _run_identity(f"case-1-{step_id}-repair-1") == {
            "ticket_id": "case-1",
            "step_id": step_id,
        }
    assert _run_identity("case-1-unknown-1") == {}
