"""The per-module step tables (task 8.0a, M7 whole-lane review F3).

The pins hold the hand-kept values of base ceba3dc literally: every table the live runner,
the journal and the CLI read must keep exactly these values, whichever code builds them.
Task 8.6 appends four one-step modules; the base rows stay as pinned.
"""

import dataclasses
from typing import Any, Literal

import pytest

from deploy_vii import registry
from deploy_vii.business_context import BusinessContextSubmission
from deploy_vii.cp1_workflow import CP1_PROMOTION, CP1_STEPS, FinancialSubmission
from deploy_vii.cp2_synthesis import CreditSynthesisSubmission
from deploy_vii.cp3_relative_value import RelativeValueSubmission
from deploy_vii.cp4_legal import CovenantInterpretationSubmission
from deploy_vii.cp5_integrity import IntegritySubmission
from deploy_vii.cp6_committee import CommitteeSubmission
from deploy_vii.downstream_readiness import DownstreamReview
from deploy_vii.execution import WITHIN_ATTEMPT_REPAIR, Attempt, StepSubmission
from deploy_vii.live import cli, context, runner, submission
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
# The registry's first three records are the base's; task 8.6 appends four one-step modules and
# task 8.7 a fifth, CP-6 (each settles its module, none prefills, repairs within the attempt or
# projects a step).
BASE_CHAINS = registry.STEP_CHAINS[:3]
M8_STEPS = (
    ("credit_synthesis", "CP-2", CreditSynthesisSubmission),
    ("legal_covenants", "CP-4", CovenantInterpretationSubmission),
    ("relative_value", "CP-3", RelativeValueSubmission),
    ("integrity_review", "CP-5", IntegritySubmission),
    ("committee_challenge", "CP-6", CommitteeSubmission),
)
REGISTERED_STEPS = (*BASE_STEPS, *M8_STEPS)
REGISTERED_PACK_SOURCE_STEPS = BASE_PACK_SOURCE_STEPS | {"legal_covenants", "relative_value"}
CP2_ROUTE = (*BASE_FULL_CHAIN, "business_context", "credit_synthesis")
M8_ROUTES = {
    "CP-2": CP2_ROUTE,
    "CP-4": (*BASE_FULL_CHAIN, "legal_covenants"),
    "CP-3": (*CP2_ROUTE, "relative_value"),
    "CP-5": (*BASE_CP0_STEPS, "integrity_review"),
    "CP-6": (*CP2_ROUTE, "relative_value", "integrity_review", "committee_challenge"),
}
REGISTERED_REGRESSION_CASES = (
    *BASE_REGRESSION_CASES,
    *((module_id.lower().replace("-", ""), route) for module_id, route in M8_ROUTES.items()),
)
MODULE_ROUTES = {**BASE_MODULE_ROUTES, **M8_ROUTES}


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
    assert [(step_id, d.module_id, d.schema) for step_id, d in STEPS.items()] == list(
        REGISTERED_STEPS
    )
    assert dict(PREFILLED) == BASE_PREFILLED
    assert dict(BOUND_STEPS) == BASE_BOUND_STEPS
    assert dict(WITHIN_ATTEMPT_REPAIR) == BASE_WITHIN_ATTEMPT_REPAIR
    assert dict(context.PROJECTIONS) == BASE_PROJECTIONS
    assert context.PACK_SOURCE_STEPS == REGISTERED_PACK_SOURCE_STEPS
    assert CP1_PROMOTION == BASE_CP1_PROMOTION and CP1_STEPS == BASE_CP1_PROMOTION[:4]
    assert cli.CP0_STEPS == BASE_CP0_STEPS and cli.CP1_CHAIN == BASE_CP1_PROMOTION
    assert cli.FULL_CHAIN == BASE_FULL_CHAIN and cli.CP1A_CHAIN == BASE_CP1A_CHAIN
    assert cli.REGRESSION_CASES == REGISTERED_REGRESSION_CASES


@pytest.mark.parametrize("module_id", sorted(MODULE_ROUTES))
def test_a_module_cell_runs_its_base_route(module_id: str) -> None:
    (cell,) = cli._module_cells(module_id, 7)
    assert cell.steps == MODULE_ROUTES[module_id]
    assert (cell.cell_id, cell.case_id, cell.seed) == ("module-00", module_id.lower(), 7)


def test_a_module_without_a_live_step_contract_is_refused_with_the_base_wording() -> None:
    with pytest.raises(cli.CliError, match=r"CP-1B has no live step contract; supported: "):
        cli._module_cells("CP-1B", 7)
    with pytest.raises(
        cli.CliError, match=r"supported: CP-0, CP-1, CP-1A, CP-2, CP-3, CP-4, CP-5, CP-6$"
    ):
        cli._module_cells("CP-1B", 7)


@pytest.mark.parametrize(
    ("module_id", "chain"),
    [
        ("CP-0", BASE_CP0_STEPS),
        ("CP-1", BASE_CP1_PROMOTION),
        ("CP-1A", ("business_context",)),
        *((module_id, (step_id,)) for step_id, module_id, _ in M8_STEPS),
    ],
)
def test_the_next_step_walks_each_base_chain(module_id: str, chain: tuple[str, ...]) -> None:
    for done in range(len(chain)):
        held = attempt(module_id, *((step_id, "valid") for step_id in chain[:done]))
        assert runner.expected_step(held, module_id) == chain[done]


@pytest.mark.parametrize(
    ("module_id", "chain", "message"),
    [
        # Task 8.0a (fix round 1): one neutral wording for every one-step module, CP-1A's base
        # text (base CP-0: "CP-0 already retains its review step; ..."); the refusal is raised
        # before anything is reserved, sent or written.
        ("CP-0", BASE_CP0_STEPS, "CP-0 already retains its one step; resume it through"),
        ("CP-1", BASE_CP1_PROMOTION, "every CP-1 step is already retained"),
        ("CP-1A", ("business_context",), "CP-1A already retains its one step; resume it"),
        *(
            (module_id, (step_id,), f"{module_id} already retains its one step; resume it")
            for step_id, module_id, _ in M8_STEPS
        ),
    ],
)
def test_a_complete_chain_is_refused_with_the_base_wording(
    module_id: str, chain: tuple[str, ...], message: str
) -> None:
    held = attempt(module_id, *((step_id, "valid") for step_id in chain))
    with pytest.raises(ValueError, match=message):
        runner.expected_step(held, module_id)


def test_the_run_identity_reads_every_base_step_in_base_order() -> None:
    for step_id, _, _ in REGISTERED_STEPS:
        assert _run_identity(f"case-1-{step_id}-2") == {"ticket_id": "case-1", "step_id": step_id}
        assert _run_identity(f"case-1-{step_id}-repair-1") == {
            "ticket_id": "case-1",
            "step_id": step_id,
        }
    assert _run_identity("case-1-unknown-1") == {}


# --- the registry (task 8.0a): one record per live module; every table above derives from it ---


def test_the_registry_derives_every_base_table() -> None:
    assert registry.step_modules() == {step_id: module for step_id, module, _ in REGISTERED_STEPS}
    assert list(registry.step_modules()) == [step_id for step_id, _, _ in REGISTERED_STEPS]
    assert registry.prefilled_kinds() == BASE_PREFILLED
    assert registry.bound_steps() == BASE_BOUND_STEPS
    assert registry.within_attempt_repair() == BASE_WITHIN_ATTEMPT_REPAIR
    assert registry.projections() == BASE_PROJECTIONS
    assert registry.pack_source_steps() == REGISTERED_PACK_SOURCE_STEPS
    assert registry.settling_steps() == {
        "source_readiness",
        "quality",
        "business_context",
        *(step_id for step_id, _, _ in M8_STEPS),
    }
    assert registry.step_chain("CP-1").steps == BASE_CP1_PROMOTION
    assert registry.step_chain("CP-1").settling == "quality"
    assert {m: registry.module_route(m) for m in MODULE_ROUTES} == MODULE_ROUTES
    assert registry.regression_cases() == REGISTERED_REGRESSION_CASES
    # The base records derive the base tables unchanged.
    assert registry.step_modules(BASE_CHAINS) == {s: m for s, m, _ in BASE_STEPS}
    assert registry.pack_source_steps(BASE_CHAINS) == BASE_PACK_SOURCE_STEPS
    assert registry.regression_cases(BASE_CHAINS) == BASE_REGRESSION_CASES


def test_each_consumer_table_is_the_registry_derivation() -> None:
    assert list(STEPS) == list(registry.step_modules())
    assert {s: d.module_id for s, d in STEPS.items()} == registry.step_modules()
    assert PREFILLED == registry.prefilled_kinds() and BOUND_STEPS == registry.bound_steps()
    assert WITHIN_ATTEMPT_REPAIR == registry.within_attempt_repair()
    assert context.PROJECTIONS == registry.projections()
    assert context.PACK_SOURCE_STEPS == registry.pack_source_steps()
    assert runner.SETTLING_STEPS == registry.settling_steps()
    assert CP1_PROMOTION == registry.step_chain("CP-1").steps and cli.CP1_CHAIN == CP1_PROMOTION
    assert CP1_STEPS == CP1_PROMOTION[:-1]
    assert cli.FULL_CHAIN == registry.module_route("CP-1")
    assert cli.CP1A_CHAIN == registry.module_route("CP-1A")
    assert cli.REGRESSION_CASES == registry.regression_cases()
    assert (context.FULL, context.OMITTED) == (registry.FULL, registry.OMITTED)
    assert (context.NARRATIVE_EVIDENCE, context.READINESS_INPUTS) == (
        registry.NARRATIVE_EVIDENCE,
        registry.READINESS_INPUTS,
    )


def test_the_step_names_still_kept_outside_the_registry_agree_with_it() -> None:
    """Not yet derived (task 8.0a scope): the workflows' own journal sequences and step names.
    A rename on either side fails here rather than in a live run."""
    from deploy_vii import business_context
    from deploy_vii.live import corpus, prompts

    assert business_context.CP1A_STEPS == registry.step_chain("CP-1A").steps
    assert business_context.STEP_ID == registry.step_chain("CP-1A").settling
    assert prompts.QUALITY == registry.step_chain("CP-1").settling
    assert corpus.SUPPORTED_STEPS == registry.module_route("CP-1")
    assert registry.step_chain("CP-0").steps == ("source_readiness",)  # cp0_workflow's sequence


def test_a_schema_table_that_misses_or_adds_a_step_is_refused() -> None:
    schemas = {step_id: schema for step_id, _, schema in REGISTERED_STEPS}
    assert submission.step_definitions(schemas) == dict(STEPS)
    with pytest.raises(ValueError, match="no model-facing schema for quality"):
        submission.step_definitions({k: v for k, v in schemas.items() if k != "quality"})
    with pytest.raises(ValueError, match="a schema for extra, which is no live step"):
        submission.step_definitions({**schemas, "extra": QualityReview})


SYNTHETIC = registry.StepChain(
    module_id="CP-2",
    cell="cp2",
    steps=("alpha", "beta", "gamma"),
    repairable=frozenset({"alpha", "beta"}),
    prefilled={"beta": frozenset({"pack"}), "gamma": frozenset({"step-inputs"})},
    projections={
        ("beta", "alpha"): registry.FULL,
        ("gamma", "alpha"): registry.OMITTED,
        ("gamma", "beta"): registry.FULL,
    },
    pack_sources=frozenset({"alpha"}),
)


def test_a_second_module_record_yields_consistent_tables_everywhere() -> None:
    """CP-2 needs CP-0, CP-1 and CP-1A (methodology.json): one more record extends every table
    and leaves the base rows as they were (over the base records: task 8.6 registers the real
    CP-2)."""
    chains = registry.checked_chains((*BASE_CHAINS, SYNTHETIC))
    base = BASE_CHAINS
    assert registry.step_modules(chains) == {
        **registry.step_modules(base),
        "alpha": "CP-2",
        "beta": "CP-2",
        "gamma": "CP-2",
    }
    assert list(registry.step_modules(chains))[-3:] == ["alpha", "beta", "gamma"]
    assert registry.within_attempt_repair(chains) == {
        **BASE_WITHIN_ATTEMPT_REPAIR,
        "CP-2": frozenset({"alpha", "beta"}),
    }
    assert registry.settling_steps(chains) == registry.settling_steps(base) | {"gamma"}
    assert registry.prefilled_kinds(chains) == {**BASE_PREFILLED, **SYNTHETIC.prefilled}
    assert registry.bound_steps(chains) == {
        **BASE_BOUND_STEPS,
        "beta": ("alpha",),
        "gamma": ("alpha", "beta"),
    }
    assert registry.projections(chains) == {**BASE_PROJECTIONS, **SYNTHETIC.projections}
    assert registry.pack_source_steps(chains) == BASE_PACK_SOURCE_STEPS | {"alpha"}
    route = ("source_readiness", *BASE_CP1_PROMOTION, "business_context", "alpha", "beta", "gamma")
    assert registry.module_route("CP-2", chains) == route
    assert registry.regression_cases(chains) == (*BASE_REGRESSION_CASES, ("cp2", route))
    assert registry.step_chain("CP-2", chains).settling == "gamma"


def test_a_route_through_a_module_without_live_steps_is_refused() -> None:
    chains = registry.checked_chains((*registry.STEP_CHAINS[:2], SYNTHETIC))  # no CP-1A
    with pytest.raises(ValueError, match="CP-1A has no live step contract"):
        registry.module_route("CP-2", chains)
    with pytest.raises(ValueError, match="CP-1B has no live step contract"):
        registry.step_chain("CP-1B")
    unknown = registry.checked_chains((dataclasses.replace(SYNTHETIC, module_id="CP-99"),))
    with pytest.raises(ValueError, match="Unknown r14 entry: CP-99"):
        registry.module_route("CP-99", unknown)


def test_every_chain_is_keyed_by_its_r14_module_id() -> None:
    assert all(registry.canonical(c.module_id) == c.module_id for c in registry.STEP_CHAINS)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"steps": ()}, "no steps"),
        ({"steps": ("alpha", "alpha", "gamma")}, "repeats a step"),
        ({"repairable": frozenset({"gamma"})}, "repairs gamma within the attempt"),
        ({"repairable": frozenset({"delta"})}, "repairs delta within the attempt"),
        ({"prefilled": {"delta": frozenset({"pack"})}}, "prefills delta"),
        ({"pack_sources": frozenset({"delta"})}, "sends pack sources to delta"),
        ({"projections": {("beta", "alpha"): registry.FULL}}, r"no projection.*gamma"),
        (
            {"projections": {**SYNTHETIC.projections, ("alpha", "beta"): registry.FULL}},
            r"projection.*\('alpha', 'beta'\)",
        ),
        (
            {"projections": {**SYNTHETIC.projections, ("beta", "alpha"): "raw"}},
            "unknown projection raw",
        ),
    ],
)
def test_an_inconsistent_record_is_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        dataclasses.replace(SYNTHETIC, **change)


@pytest.mark.parametrize(
    ("other", "message"),
    [
        (dataclasses.replace(SYNTHETIC, module_id="CP-1"), "CP-1 has two step chains"),
        (dataclasses.replace(SYNTHETIC, cell="cp1"), "cell cp1 names two modules"),
        (
            dataclasses.replace(
                SYNTHETIC,
                steps=("alpha", "quality"),
                prefilled={},
                projections={("quality", "alpha"): registry.OMITTED},
                repairable=frozenset(),
            ),
            "step quality belongs to two modules",
        ),
    ],
)
def test_records_that_collide_are_refused(other: registry.StepChain, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        registry.checked_chains((*BASE_CHAINS, other))
