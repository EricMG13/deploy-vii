"""r14 ownership and sequential dependency planning; aliases never create new work.

Task 8.0a: each module with live steps has one `StepChain` record in `STEP_CHAINS`, and every
per-step table of the journal, the live runner and the CLI is derived from those records
(`step_modules`, `settling_steps`, `within_attempt_repair`, `prefilled_kinds`, `bound_steps`,
`projections`, `pack_source_steps`, `module_route`, `regression_cases`). It lives here, the
lowest layer, because `execution` (imported by every workflow) and `live` both read it.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from pydantic import Field

from deploy_vii.contracts import Contract, Identifier, Run, Status, Text

EdgeRule = Literal["block", "restricted"]

# CP-5 follows every selected analyst, CP-MODEL included (DC-5); challenge, exports and OS do not.
_NOT_CP5_FAN_IN = frozenset({"CP-5", "CP-6", "CP-8", "CP-MEMO", "CP-OS"})


class Responsibility(Contract):
    module_id: Identifier
    title: Text
    aliases: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...]
    edge_rules: dict[str, EdgeRule] = Field(default_factory=dict)
    purpose: Text
    table_ids: tuple[str, ...]


@lru_cache(maxsize=1)
def modules() -> tuple[Responsibility, ...]:
    raw = json.loads(files("deploy_vii").joinpath("methodology.json").read_text())
    return tuple(Responsibility.model_validate_json(json.dumps(row)) for row in raw)


def canonical(entry: str) -> str:
    for module in modules():
        if entry == module.module_id or entry in module.aliases:
            return module.module_id
    raise ValueError(f"Unknown r14 entry: {entry}")


def dependencies(requested: tuple[str, ...]) -> dict[str, set[str]]:
    catalog = {module.module_id: module for module in modules()}
    selected = {canonical(entry) for entry in requested}
    pending = list(selected)
    while pending:
        for dependency in catalog[pending.pop()].required:
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)

    # Optional dependencies constrain execution only when selected.
    remaining = {
        module_id: set(catalog[module_id].required) | (set(catalog[module_id].optional) & selected)
        for module_id in selected
    }
    if "CP-5" in selected:
        # QA follows every selected analyst; challenge and exports follow QA.
        remaining["CP-5"] |= selected - _NOT_CP5_FAN_IN

    return remaining


def edge_rule(consumer: str, producer: str) -> EdgeRule:
    """Degradation rule of one dependency edge (decision 0007).

    An explicit `edge_rules` entry wins. Otherwise a required producer blocks its
    consumer and an optional one, or CP-5's fan-in over analysts, restricts it.
    """
    entry = next((module for module in modules() if module.module_id == consumer), None)
    if entry is not None:
        if producer in entry.edge_rules:
            return entry.edge_rules[producer]
        if producer in entry.required:
            return "block"
        if producer in entry.optional or (
            consumer == "CP-5"
            and producer not in _NOT_CP5_FAN_IN
            and any(module.module_id == producer for module in modules())
        ):
            return "restricted"
    raise ValueError(f"No dependency edge from {producer} to {consumer}")


def idle_statuses(run: Run) -> dict[str, Status]:
    """Status of every registry module before it runs: ``unrun`` in scope, else ``not_in_pathway``.

    Scope is the run's requested modules plus their required producers (decision 0009); an
    unknown module id raises rather than silently widening or narrowing the scope. Every view
    builder takes its not-yet-run statuses from here.
    """
    in_scope = set(dependencies(run.requested_modules))
    return {
        m.module_id: "unrun" if m.module_id in in_scope else "not_in_pathway" for m in modules()
    }


def plan(requested: tuple[str, ...]) -> tuple[str, ...]:
    remaining = dependencies(requested)
    ordered: list[str] = []
    while remaining:
        ready = [
            module.module_id
            for module in modules()
            if module.module_id in remaining and not remaining[module.module_id]
        ]
        if not ready:
            raise ValueError("cyclic selected module dependencies")
        for module_id in ready:
            ordered.append(module_id)
            del remaining[module_id]
            for required in remaining.values():
                required.discard(module_id)
    return tuple(ordered)


# --- live step chains (task 8.0a) -------------------------------------------------------------

# What a later step is shown of a retained earlier step (`live.context.upstream_text`).
FULL = "full"
OMITTED = "omitted"
NARRATIVE_EVIDENCE = "narrative-evidence"
READINESS_INPUTS = "readiness-inputs"
PROJECTION_NAMES = frozenset({FULL, OMITTED, NARRATIVE_EVIDENCE, READINESS_INPUTS})


@dataclass(frozen=True)
class StepChain:
    """One module's live steps: the one place a module's step facts are kept.

    `steps` is the journal order. The last step settles the module (`settling`: its acceptance
    is the module's), so it is never repaired within the attempt. `cell` names the module's
    regression case. `repairable`: the steps whose first rejection is repaired once within the
    attempt (decision 0008 MC-7 item 2). `prefilled`: per step, the hash-binding kinds Python
    fills (task 7.0i); such a step binds every earlier step of its chain, in order.
    `projections`: (consumer, producer) -> what a later step is shown of an earlier one (task
    7.5), every such pair exactly once, so a dispatch never meets an unlisted pair.
    `pack_sources`: the steps whose validators check spans against the pack text, the only ones
    sent SOURCE blocks (task 7.5, R6). `tool_steps` (task 8.0d): the steps the live runner may
    run as a tool loop (`live.loop`): read-only pack tools and the step's own submit tool, no
    SOURCE blocks. A record breaking any of these raises ValueError.
    """

    module_id: str
    cell: str
    steps: tuple[str, ...]
    repairable: frozenset[str] = frozenset()
    prefilled: Mapping[str, frozenset[str]] = field(default_factory=dict)
    projections: Mapping[tuple[str, str], str] = field(default_factory=dict)
    pack_sources: frozenset[str] = frozenset()
    tool_steps: frozenset[str] = frozenset()

    @property
    def settling(self) -> str:
        return self.steps[-1]

    def pairs(self) -> tuple[tuple[str, str], ...]:
        """Every (later step, earlier step) pair of the chain, in chain order."""
        return tuple(
            (consumer, producer)
            for index, consumer in enumerate(self.steps)
            for producer in self.steps[:index]
        )

    def __post_init__(self) -> None:
        name = f"step chain {self.module_id}"
        if not self.steps:
            raise ValueError(f"{name} has no steps")
        if len(set(self.steps)) != len(self.steps):
            raise ValueError(f"{name} repeats a step: {', '.join(self.steps)}")
        steps = set(self.steps)
        if extra := sorted(self.repairable - set(self.steps[:-1])):
            raise ValueError(
                f"{name} repairs {', '.join(extra)} within the attempt; only a step before its "
                f"settling step {self.settling} may be"
            )
        if extra := sorted(set(self.prefilled) - steps):
            raise ValueError(f"{name} prefills {', '.join(extra)}, not one of its steps")
        if extra := sorted(self.pack_sources - steps):
            raise ValueError(
                f"{name} sends pack sources to {', '.join(extra)}, not one of its steps"
            )
        if extra := sorted(self.tool_steps - steps):
            raise ValueError(f"{name} runs {', '.join(extra)} as a tool loop, not one of its steps")
        pairs = self.pairs()
        for pair in self.projections:
            if pair not in pairs:
                raise ValueError(f"{name} lists a projection for {pair}, not a later-earlier pair")
        for consumer, producer in pairs:
            projection = self.projections.get((consumer, producer))
            if projection is None:
                raise ValueError(
                    f"{name} defines no projection of step {producer} for step {consumer}"
                )
            if projection not in PROJECTION_NAMES:
                raise ValueError(
                    f"{name} names an unknown projection {projection} of step {producer} for "
                    f"step {consumer}"
                )


def checked_chains(chains: Sequence[StepChain]) -> tuple[StepChain, ...]:
    """`chains` as one registry, in its order: one chain per module, one module per regression
    cell and per step id (a step id is the journal's and the ledger's key). Else ValueError."""
    modules_seen: set[str] = set()
    cells: dict[str, str] = {}
    owners: dict[str, str] = {}
    for chain in chains:
        if chain.module_id in modules_seen:
            raise ValueError(f"{chain.module_id} has two step chains")
        modules_seen.add(chain.module_id)
        if chain.cell in cells:
            raise ValueError(
                f"cell {chain.cell} names two modules: {cells[chain.cell]} and {chain.module_id}"
            )
        cells[chain.cell] = chain.module_id
        for step_id in chain.steps:
            if step_id in owners:
                raise ValueError(
                    f"step {step_id} belongs to two modules: {owners[step_id]} and "
                    f"{chain.module_id}"
                )
            owners[step_id] = chain.module_id
    return tuple(chains)


STEP_CHAINS = checked_chains(
    (
        # CP-0's one review; its acceptance settles the module.
        StepChain(
            module_id="CP-0",
            cell="cp0",
            steps=("source_readiness",),
            pack_sources=frozenset({"source_readiness"}),
        ),
        # Task 7.4: the four stages, then the analyst's QA review whose acceptance is the CP-1
        # promotion (`cp1_workflow.promote_cp1`); a rejected review finishes the attempt.
        StepChain(
            module_id="CP-1",
            cell="cp1",
            steps=("source_context", "financials", "narrative", "readiness", "quality"),
            repairable=frozenset({"source_context", "financials", "narrative", "readiness"}),
            prefilled={
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
            },
            projections={
                ("financials", "source_context"): FULL,
                # The financial stage's ledger holds the same source-context report
                # (`ledger.context`).
                ("narrative", "source_context"): OMITTED,
                ("narrative", "financials"): NARRATIVE_EVIDENCE,
                # The readiness validator reads the narrative step's output only; it holds the
                # same catalogue.
                ("readiness", "source_context"): OMITTED,
                ("readiness", "financials"): OMITTED,
                ("readiness", "narrative"): READINESS_INPUTS,
                # Task 7.4: Python's QA scope (`prompts.quality_scope`) is the quality model's
                # context.
                ("quality", "source_context"): OMITTED,
                ("quality", "financials"): OMITTED,
                ("quality", "narrative"): OMITTED,
                ("quality", "readiness"): OMITTED,
            },
            pack_sources=frozenset({"source_context", "financials"}),
            # Task 8.0d (user decision, 24 Oct 2026): the four stages the hybrid harness ran
            # with pack tools (`devtools/hybrid_cp1.py`); the QA review stays one-shot.
            tool_steps=frozenset({"source_context", "financials", "narrative", "readiness"}),
        ),
        # Task 7.2: CP-1A's one step; Python composes the registers as its output.
        StepChain(
            module_id="CP-1A",
            cell="cp1a",
            steps=("business_context",),
            pack_sources=frozenset({"business_context"}),
        ),
        # Task 8.6: one settling step each; Python composes every table. CP-2 and CP-5 quote
        # nothing (no SOURCE block); CP-4 is sent its legal sources and CP-3 its market sources
        # only (`live.context.declared_sources`).
        StepChain(module_id="CP-2", cell="cp2", steps=("credit_synthesis",)),
        StepChain(
            module_id="CP-4",
            cell="cp4",
            steps=("legal_covenants",),
            pack_sources=frozenset({"legal_covenants"}),
        ),
        StepChain(
            module_id="CP-3",
            cell="cp3",
            steps=("relative_value",),
            pack_sources=frozenset({"relative_value"}),
        ),
        StepChain(module_id="CP-5", cell="cp5", steps=("integrity_review",)),
        # Task 8.7: CP-6's one settling step after CP-5; it quotes no pack source (no SOURCE
        # block) and reads the settled CP-1, CP-2, CP-3 and CP-5 heads.
        StepChain(module_id="CP-6", cell="cp6", steps=("committee_challenge",)),
    )
)


def step_chain(module_id: str, chains: Sequence[StepChain] = STEP_CHAINS) -> StepChain:
    found = next((chain for chain in chains if chain.module_id == module_id), None)
    if found is None:
        raise ValueError(f"{module_id} has no live step contract")
    return found


def step_modules(chains: Sequence[StepChain] = STEP_CHAINS) -> dict[str, str]:
    """Every live step id and its module, in registry and then chain order."""
    return {step_id: chain.module_id for chain in chains for step_id in chain.steps}


def settling_steps(chains: Sequence[StepChain] = STEP_CHAINS) -> frozenset[str]:
    """The steps whose acceptance is their module's (each chain's last step)."""
    return frozenset(chain.settling for chain in chains)


def within_attempt_repair(chains: Sequence[StepChain] = STEP_CHAINS) -> dict[str, frozenset[str]]:
    """Per module that has any, the steps repaired once within their attempt."""
    return {chain.module_id: chain.repairable for chain in chains if chain.repairable}


def prefilled_kinds(chains: Sequence[StepChain] = STEP_CHAINS) -> dict[str, frozenset[str]]:
    """Per step Python pre-fills, the binding kinds it fills, in chain order."""
    return {
        step_id: chain.prefilled[step_id]
        for chain in chains
        for step_id in chain.steps
        if step_id in chain.prefilled
    }


def bound_steps(chains: Sequence[StepChain] = STEP_CHAINS) -> dict[str, tuple[str, ...]]:
    """Per step Python pre-fills, the retained steps its bindings come from: every earlier step
    of its chain, in order (`live.submission.known_bindings` checks them by position)."""
    return {
        step_id: chain.steps[:index]
        for chain in chains
        for index, step_id in enumerate(chain.steps)
        if step_id in chain.prefilled
    }


def projections(chains: Sequence[StepChain] = STEP_CHAINS) -> dict[tuple[str, str], str]:
    """(consumer step, producer step) -> projection, over every chain."""
    return {pair: chain.projections[pair] for chain in chains for pair in chain.pairs()}


def pack_source_steps(chains: Sequence[StepChain] = STEP_CHAINS) -> frozenset[str]:
    return frozenset(step_id for chain in chains for step_id in chain.pack_sources)


def tool_loop_steps(chains: Sequence[StepChain] = STEP_CHAINS) -> frozenset[str]:
    """The steps the live runner may run as a tool loop (task 8.0d)."""
    return frozenset(step_id for chain in chains for step_id in chain.tool_steps)


def module_route(module_id: str, chains: Sequence[StepChain] = STEP_CHAINS) -> tuple[str, ...]:
    """The steps a live run of `module_id` dispatches: the chains of its required producers and
    its own, in `plan` order (CP-1: CP-0's, then CP-1's). A planned module without a chain
    raises ValueError, as does an id r14 does not know."""
    return tuple(
        step_id for planned in plan((module_id,)) for step_id in step_chain(planned, chains).steps
    )


def regression_cases(
    chains: Sequence[StepChain] = STEP_CHAINS,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """The matched comparison's cases: each module's cell and route, in registry order."""
    return tuple((chain.cell, module_route(chain.module_id, chains)) for chain in chains)
