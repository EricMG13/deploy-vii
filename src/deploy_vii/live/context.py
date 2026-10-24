"""What a later CP-1 step is shown of each retained earlier step (task 7.5, decision 0008).

The journal retains each step's full validated output, and every validator recomputes from those
retained artifacts, never from a prompt. A model is shown a bounded projection of them, chosen
per consumer and producer step by `PROJECTIONS`; a pair the table does not list raises (fail
closed). E1 batch 6 measured why: the raw `financials` output (the whole `FinancialStage`) held
8,023,867 characters on the real Caesars pack, and the `narrative` prompt carrying it could not
be sent to any pool model.

- `full`: the retained output as it is (`financials` reads the source-context report).
- `narrative-evidence`: the financial stage as the narrative review may reference it: one
  evidence-table line per catalogue entry (its `evidence_id`, the only handle a passage has, and
  a compact value summary; no `record_json`, no citation, since `validate_narrative_review`
  checks no span), the scope, calculation status, the ledger's limitations, its source-context
  report without citations or hashes, and the model's metrics. The audit, the period
  reconciliation, the gap rows and the historical table are Python's and are not sent; the
  catalogue lines carry what a passage can reference (its historical_value, construction and
  source_period lines are the historical register).
- `readiness-inputs`: the narrative step's `DownstreamInputs` as `validate_downstream_review`
  lets a review reference it: the consumer requests, the narrative review and status, the gaps
  the narrative added, and the same evidence table with each gap line's `gap_id`.
- `omitted`: nothing is sent (the consumer's own block, or Python's QA scope, carries it).

Pack SOURCE blocks go only to a step whose validator checks spans against the pack text
(`PACK_SOURCE_STEPS`); `narrative`, `readiness` and `quality` reference evidence ids only.

Task 8.6: the one-step modules after CP-1A read settled heads, not retained steps. Their CONTEXT
is Python's view of the attempt's bound upstream (`module_context`), each module's own
`context_block`: CP-2 over `cp2_upstream`, CP-4 over `cp4_legal.upstream_of`, CP-3 over
`cp3_upstream` and (task 8.7) CP-6 over `cp6_upstream`, merged into the prepared-pack block as
CP-1A's `cp1_facts` are. CP-5's review scope is its own block (`integrity_scope`), projected to
the facts the review can name (`integrity_projection`). `declared_sources` narrows the SOURCE
blocks: CP-4 is sent the ready sources CP-0 classes executed or filed, CP-3 the ready sources it
classes `third_party`; every other step gets `step_sources`.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from deploy_vii import (
    cp2_synthesis,
    cp3_relative_value,
    cp4_legal,
    cp5_integrity,
    cp6_committee,
    prose,
)
from deploy_vii.contracts import Fact, Module
from deploy_vii.cp1_workflow import FinancialStage
from deploy_vii.downstream_readiness import DownstreamInputs
from deploy_vii.execution import Attempt, Execution
from deploy_vii.narrative import EvidenceRecord
from deploy_vii.registry import FULL as FULL
from deploy_vii.registry import NARRATIVE_EVIDENCE as NARRATIVE_EVIDENCE
from deploy_vii.registry import OMITTED as OMITTED
from deploy_vii.registry import READINESS_INPUTS as READINESS_INPUTS
from deploy_vii.registry import pack_source_steps, projections

# (consumer step, producer step) -> projection, from the registry's step chains (task 8.0a):
# every later-earlier pair of each chain (CP-0 and CP-1A have one step each, so no earlier step
# of their attempt is ever retained when they are dispatched).
PROJECTIONS: Mapping[tuple[str, str], str] = projections()

# Steps whose validators match citations against the pack's span text (the registry's).
PACK_SOURCE_STEPS = pack_source_steps()

TEXT_LIMIT = 120  # a description or explanation
LABEL_LIMIT = 60  # a statement line's label


class ProjectionError(ValueError):
    """A retained step has no projection for this consumer, or its output cannot be projected."""


def projection_name(consumer_step_id: str, producer_step_id: str) -> str:
    name = PROJECTIONS.get((consumer_step_id, producer_step_id))
    if name is None:
        raise ProjectionError(
            f"no projection of step {producer_step_id} is defined for step {consumer_step_id}"
        )
    return name


def step_sources(step_id: str, source_ids: Sequence[str]) -> tuple[str, ...]:
    """The pack sources a step declares: all of them where its validator checks spans."""
    return tuple(source_ids) if step_id in PACK_SOURCE_STEPS else ()


# --- the one-step modules after CP-1A (task 8.6) ----------------------------------------------

INTEGRITY = cp5_integrity.STEP_ID
# Per step, the CONTEXT entries Python adds to the prepared-pack block from the bound upstream.
MODULE_CONTEXTS: Mapping[str, Callable[[Execution, Attempt], dict[str, object]]] = {
    cp2_synthesis.STEP_ID: lambda store, attempt: cp2_synthesis.context_block(
        store.pack(), cp2_synthesis.cp2_upstream(store, attempt)
    ),
    cp4_legal.STEP_ID: lambda store, attempt: cp4_legal.context_block(
        store.pack(), cp4_legal.upstream_of(store, attempt)
    ),
    cp3_relative_value.STEP_ID: lambda store, attempt: cp3_relative_value.context_block(
        store.pack(), cp3_relative_value.cp3_upstream(store, attempt)
    ),
    # Task 8.7: CP-6 over the settled CP-1, CP-2, CP-3 and CP-5 heads its ticket binds.
    cp6_committee.STEP_ID: lambda store, attempt: cp6_committee.context_block(
        store.pack(), cp6_committee.cp6_upstream(store, attempt)
    ),
}


def module_context(store: Execution, attempt: Attempt, step_id: str) -> dict[str, object] | None:
    """The module CONTEXT entries of `step_id` over `attempt`'s bound upstream; None for a step
    that has none."""
    build = MODULE_CONTEXTS.get(step_id)
    return None if build is None else build(store, attempt)


def _cp3_market_sources(store: Execution, attempt: Attempt) -> tuple[str, ...]:
    market = cp3_relative_value.cp3_upstream(store, attempt).market_sources
    return tuple(
        s.source_id for s in store.pack().sources if s.source_id in market and s.status == "ready"
    )


# The steps whose SOURCE blocks are the bound upstream's choice, not every pack source: CP-4's
# legal sources (task 8.2 ruling 1) and CP-3's market sources (task 8.3 ruling 1), pack order.
SOURCE_SCOPES: Mapping[str, Callable[[Execution, Attempt], tuple[str, ...]]] = {
    cp4_legal.STEP_ID: lambda store, attempt: cp4_legal.upstream_of(store, attempt).legal_sources,
    cp3_relative_value.STEP_ID: _cp3_market_sources,
}


def declared_sources(
    store: Execution, attempt: Attempt, step_id: str, source_ids: Sequence[str]
) -> tuple[str, ...]:
    """The pack sources `step_id` is sent on `attempt`: its source scope's, in pack order and
    within `source_ids`, else `step_sources`."""
    scope = SOURCE_SCOPES.get(step_id)
    if scope is None:
        return step_sources(step_id, source_ids)
    return tuple(source_id for source_id in scope(store, attempt) if source_id in source_ids)


def integrity_projection(scope: cp5_integrity.ReviewScope) -> cp5_integrity.FactProjection:
    """The facts of each head the CP-5 CONTEXT lists (`cp5_integrity.context_block`'s seam): the
    facts a claim names as `{ref|unit}`, every member of a cross-module identity group and
    every reference a Python check flags, in head order. The checks and the validator still read
    every fact; a promoted CP-1 holds tens of thousands, nearly all named by nothing."""
    checks = cp5_integrity.python_checks(scope)
    kept: dict[str, set[str]] = {}
    for _, head in scope.heads:
        bound = prose.bind(head.facts)
        named = {
            bound[run.text].fact_id
            for claim in head.claims
            for run in prose.tokenize(claim.text)
            if run.kind != "text" and run.text in bound
        }
        kept[head.module_id] = named | set(checks.ref_marks.get(head.module_id, ()))
    for group in checks.groups:
        for module_id, fact_id in group.members:
            kept.setdefault(module_id, set()).add(fact_id)

    def project(head: Module) -> Sequence[Fact]:
        wanted = kept.get(head.module_id, set())
        return tuple(fact for fact in head.facts if fact.fact_id in wanted)

    return project


def integrity_scope(store: Execution, attempt: Attempt) -> dict[str, object]:
    """The CP-5 review scope block of `attempt`: its review scope, facts projected."""
    scope = cp5_integrity.review_scope(store, attempt)
    return cp5_integrity.context_block(scope, facts=integrity_projection(scope))


def upstream_text(consumer_step_id: str, producer_step_id: str, output_json: str) -> str:
    """The body sent to `consumer_step_id` for the retained output of `producer_step_id`."""
    name = projection_name(consumer_step_id, producer_step_id)
    if name == FULL:
        return output_json
    if name == NARRATIVE_EVIDENCE:
        return narrative_evidence(FinancialStage.model_validate_json(output_json))
    if name == READINESS_INPUTS:
        return readiness_inputs(DownstreamInputs.model_validate_json(output_json))
    raise ProjectionError(f"step {producer_step_id} is not sent to step {consumer_step_id}")


# --- the evidence table ----------------------------------------------------------------------

Data = dict[str, Any]
Labels = Mapping[str, str]


def _clip(value: str | None, limit: int) -> str | None:
    """One line, at most `limit` characters; a cut ends in an ellipsis."""
    if value is None:
        return None
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _label(labels: Labels, key: str) -> str:
    try:
        return labels[key]
    except KeyError:
        raise ProjectionError(
            f"evidence references {key}, which the retained output lacks"
        ) from None


def _value(d: Data) -> list[Any]:
    value = d["value"]
    return [value["amount"], d["unit"], d["currency"], value["calculation_status"]]


def _statement(d: Data, _: Labels) -> list[Any]:
    label = _clip(d["label"], LABEL_LIMIT)
    return [
        d["period_id"],
        d["item_id"],
        d["line_id"],
        label,
        d["line_kind"],
        d["status"],
        d["normalized_amount"],
    ]


def _definition(d: Data, _: Labels) -> list[Any]:
    periods = ",".join(d["period_ids"])
    return [d["kind"], d["status"], d["metric"], periods, _clip(d["explanation"], TEXT_LIMIT)]


def _gap(d: Data, _: Labels) -> list[Any]:
    periods = ",".join(p["label"] for p in d["periods"])
    # A calculation gap's description opens with its metric, which has its own column.
    description, metric = d["description"], d["metric"]
    description = description.removeprefix(f"{metric}: ") if metric else description
    return [d["severity"], d["origin"], metric, periods, _clip(description, TEXT_LIMIT)]


Row = Callable[[Data, Labels], list[Any]]
VALUE_COLUMNS = ("amount", "unit", "currency", "status")
STATEMENT: tuple[tuple[str, ...], Row] = (
    ("period_id", "item_id", "line_id", "label", "line_kind", "status", "amount"),
    _statement,
)
DEFINITION: tuple[tuple[str, ...], Row] = (
    ("kind", "status", "metric", "periods", "explanation"),
    _definition,
)
# Every kind `narrative._catalogue` emits; a record of any other kind raises.
KINDS: Mapping[str, tuple[tuple[str, ...], Row]] = {
    "source": (
        ("source_id", "document_type", "availability", "extraction_status", "evidence_class"),
        lambda d, _: [
            d["source_id"],
            d["assessment"]["document_type"],
            d["availability"],
            d["extraction_status"],
            d["assessment"]["evidence_class"],
        ],
    ),
    "entity": (
        ("entity_id", "name", "entity_type", "roles"),
        lambda d, _: [
            d["entity"]["entity_id"],
            d["entity"]["name"],
            d["entity"]["entity_type"],
            ",".join(d["entity"]["roles"]),
        ],
    ),
    "subsequent_event": (
        ("event_id", "event_date", "status", "description"),
        lambda d, _: [
            d["event_id"],
            d["event_date"],
            d["status"],
            _clip(d["description"], TEXT_LIMIT),
        ],
    ),
    "observation": (
        ("observation_id", "register_id", "period_id", "status", "amount", "unit", "currency"),
        lambda d, _: [
            d["observation"]["observation_id"],
            d["register_id"],
            d["period_id"],
            d["observation"]["status"],
            d["observation"]["amount"],
            d["unit"],
            d["currency"],
        ],
    ),
    "statement_IS": STATEMENT,
    "statement_CFS": STATEMENT,
    "statement_BS": STATEMENT,
    "normalization": (
        ("observation_id", "period_id", "before", "after"),
        lambda d, _: [d["observation_id"], d["period_id"], d["before"], d["after"]],
    ),
    "definition": DEFINITION,
    "multi_figure_event": DEFINITION,
    "source_check": (
        ("check_type", "metric_id", "period_id", "status", "reported", "calculated", "difference"),
        lambda d, _: [
            d["check_type"],
            d["metric_id"],
            d["period_id"],
            d["status"],
            d["reported_value"],
            d["calculated_value"],
            d["difference"],
        ],
    ),
    "gap": (("severity", "origin", "metric", "periods", "description"), _gap),
    "source_period": (
        ("period_id", "period_type", "start_date", "end_date", "unit", "currency", "audit_status"),
        lambda d, _: [
            d["period_id"],
            d["period_type"],
            d["start_date"],
            d["end_date"],
            d["unit"],
            d["currency"],
            d["audit_status"],
        ],
    ),
    "construction": (
        ("label", "kind", "start_date", "end_date"),
        lambda d, _: [d["label"], d["kind"], d["start_date"], d["end_date"]],
    ),
    "historical_value": (
        ("series_key", "period", *VALUE_COLUMNS),
        lambda d, labels: [d["series_key"], _label(labels, d["construction_id"]), *_value(d)],
    ),
    "basis": (
        ("label", "kind", "scope", "start_date", "end_date"),
        lambda d, _: [d["label"], d["kind"], d["scope"], d["start_date"], d["end_date"]],
    ),
    "canonical_value": (
        ("key", "period", *VALUE_COLUMNS),
        lambda d, labels: [d["key"], _label(labels, d["basis_id"]), *_value(d)],
    ),
    "kpi": (
        ("key", "period", *VALUE_COLUMNS),
        lambda d, labels: [d["key"], _label(labels, d["display_basis_id"]), *_value(d)],
    ),
    "computation": (
        ("operation", "amount", "status"),
        lambda d, _: [d["operation"], d["value"]["amount"], d["value"]["calculation_status"]],
    ),
    "period_check": (
        ("check_type", "metric_id", "period", "status", "calculated", "difference"),
        lambda d, labels: [
            d["check_type"],
            d["metric_id"],
            _label(labels, d["construction_id"]),
            d["status"],
            d["calculated_value"],
            d["difference"],
        ],
    ),
}


def _line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def evidence_table(catalogue: Sequence[EvidenceRecord], *, gap_ids: bool = False) -> list[str]:
    """One line per catalogue entry, grouped by kind in catalogue order; with `gap_ids` each gap
    line also carries the `gap_id` a readiness gap scope names (the record's `reference`)."""
    parsed = [(record, json.loads(record.record_json)) for record in catalogue]
    labels = {
        data[key]: data["label"]
        for record, data in parsed
        for kind, key in (("basis", "basis_id"), ("construction", "construction_id"))
        if record.kind == kind
    }
    groups: dict[str, list[str]] = {}
    for record, data in parsed:
        spec = KINDS.get(record.kind)
        if spec is None:
            raise ProjectionError(f"no evidence line is defined for kind {record.kind}")
        extra = [record.reference] if gap_ids and record.kind == "gap" else []
        try:
            row = [record.evidence_id, *extra, *spec[1](data, labels)]
        except (KeyError, TypeError) as error:
            raise ProjectionError(
                f"evidence {record.evidence_id} ({record.kind}) does not have its kind's shape"
            ) from error
        groups.setdefault(record.kind, []).append(_line(row))
    lines = [
        f"evidence: {len(catalogue)} entries; one JSON array per line under its kind's header; "
        "the first column is the evidence_id a passage or assessment names"
    ]
    for kind, rows in groups.items():
        extra_columns = ("gap_id",) if gap_ids and kind == "gap" else ()
        columns = ("evidence_id", *extra_columns, *KINDS[kind][0])
        lines.append(f"kind={kind} entries={len(rows)} columns={_line(columns)}")
        lines.extend(rows)
    return lines


# --- the projections -------------------------------------------------------------------------


def _uncited(value: object) -> object:
    """`value` without its citation lists and content hashes (keys ending so)."""
    if isinstance(value, dict):
        return {
            key: _uncited(item)
            for key, item in value.items()
            if not key.endswith(("citations", "sha256"))
        }
    if isinstance(value, list):
        return [_uncited(item) for item in value]
    return value


def narrative_evidence(stage: FinancialStage) -> str:
    inputs, model = stage.narrative_inputs, stage.model
    ledger = inputs.ledger
    lines = [
        f"projection={NARRATIVE_EVIDENCE}: the retained CP-1 financial stage as the narrative "
        "review may reference it. Python keeps the full stage and recomputes from it; amounts "
        "are the registers' own, statement amounts in their period's unit and currency.",
        f"scope: {_line(inputs.scope)}",
        f"calculation_status: {_line(ledger.calculation_status)}",
        f"calculation_issues: {_line(ledger.calculation_issues)}",
        f"limitations: {_line(ledger.limitations)}",
        f"context: {_line(_uncited(ledger.context.model_dump(mode='json')))}",
    ]
    if model is None:
        lines.append("model_metrics: none (no model report: the calculation gate is blocked)")
    else:
        bases = {basis.basis_id: basis.label for basis in model.bases}
        columns = ("key", "period", *VALUE_COLUMNS)
        lines.append(f"model_metrics: entries={len(model.metrics)} columns={_line(columns)}")
        lines.extend(
            _line(
                [
                    metric.key,
                    _label(bases, metric.display_basis_id),
                    *_value(metric.model_dump(mode="json")),
                ]
            )
            for metric in model.metrics
        )
        lines.append(f"model_limitations: {_line(model.limitations)}")
    return "\n".join([*lines, *evidence_table(inputs.catalogue)])


def readiness_inputs(inputs: DownstreamInputs) -> str:
    narrative = inputs.narrative
    ledger_gaps = {gap.gap_id for gap in narrative.inputs.ledger.gaps}
    added = [gap for gap in narrative.gaps if gap.gap_id not in ledger_gaps]
    review = narrative.review.model_dump(mode="json", exclude={"inputs_sha256"})
    consumer_columns = ("entry", "canonical_module", "consumer_type", "policy", "requirements")
    gap_columns = ("gap_id", "severity", "origin", "reference", "description")
    lines = [
        f"projection={READINESS_INPUTS}: the retained CP-1 downstream inputs as the readiness "
        "review may reference them. Python keeps the full inputs and recomputes from them; a "
        "gap_id is a gap line's gap_id in the evidence table or a narrative_gaps line's.",
        f"requested_consumers: {_line(inputs.requested_consumers)}",
        f"consumers: entries={len(inputs.consumers)} columns={_line(consumer_columns)}",
        *(
            _line([c.entry, c.canonical_module, c.consumer_type, c.policy, c.requirements])
            for c in inputs.consumers
        ),
        f"narrative_status: {_line(narrative.status)}",
        f"narrative_limitations: {_line(narrative.limitations)}",
        f"narrative_review: {_line(review)}",
        f"narrative_gaps: entries={len(added)} columns={_line(gap_columns)}",
        *(
            _line([g.gap_id, g.severity, g.origin, g.reference, _clip(g.description, TEXT_LIMIT)])
            for g in added
        ),
    ]
    return "\n".join([*lines, *evidence_table(narrative.inputs.catalogue, gap_ids=True)])
