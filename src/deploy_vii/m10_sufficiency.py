"""CP-1-only sufficiency for a new owner's existing trusted submission/report.

This helper neither authorizes a consumer nor settles an owner. The owner must supply
its actual locked snapshot/attempt and keep this assessment as an output, not an input.
"""

from typing import Literal

from deploy_vii.contracts import Contract, Hash, Identifier, Input, Text
from deploy_vii.cp1_workflow import FrozenCP1Producer, cp1_frozen_producer
from deploy_vii.downstream_readiness import (
    ConsumerAssessment,
    ConsumerRow,
    DownstreamInputs,
    DownstreamReport,
    DownstreamReview,
    canonical_downstream_readiness,
    downstream_inputs,
)
from deploy_vii.execution import Attempt, Execution, ExecutionSnapshot
from deploy_vii.preparation import PreparedPack


class CP1Use(Contract):
    """An owner's fixed code-owned requirement/use description; never model input."""

    version: Text
    description: Text


class CP1Scope(Contract):
    book_id: Identifier
    entity_perimeter: Text
    period_ids: tuple[Identifier, ...]
    facility_ids: tuple[Identifier, ...]
    quarter_ids: tuple[Identifier, ...]


class M10CP1Inputs(Contract):
    schema_version: Literal["m10-cp1-sufficiency-inputs/1"] = "m10-cp1-sufficiency-inputs/1"
    consumer_id: Identifier
    use: CP1Use
    inputs: tuple[Input, ...]
    producer_sha256: Hash
    scope: CP1Scope
    downstream: DownstreamInputs
    original_row: ConsumerRow | None


class M10CP1Report(Contract):
    schema_version: Literal["m10-cp1-sufficiency/1"] = "m10-cp1-sufficiency/1"
    inputs: M10CP1Inputs
    downstream: DownstreamReport
    status: Literal["ready", "ready_with_limitations", "not_ready"]
    limitations: tuple[Text, ...]
    analytical_qualification: Literal["unrun"] = "unrun"


def _inputs(
    store: Execution, snapshot: ExecutionSnapshot, owner: Attempt, use: CP1Use
) -> tuple[PreparedPack, FrozenCP1Producer, M10CP1Inputs]:
    use = CP1Use.model_validate_json(use.model_dump_json())
    producer = cp1_frozen_producer(store, snapshot, owner)
    pack = store.pack(snapshot)
    financial = producer.financial
    downstream = downstream_inputs(
        pack,
        producer.context,
        financial.financial,
        financial.definition,
        financial.binding,
        producer.narrative,
        (owner.module_id,),
        quarter_ids=financial.quarter_ids,
    )
    if not downstream.consumers:
        raise ValueError("Owner has no CP-1 analytical consumer assessment row")
    book = downstream.financial_book
    original = next(
        (r for r in producer.registers.downstream.consumers if r.entry == owner.module_id), None
    )
    return (
        pack,
        producer,
        M10CP1Inputs(
            consumer_id=owner.module_id,
            use=use,
            inputs=owner.inputs,
            producer_sha256=producer.content_hash(),
            scope=CP1Scope(
                book_id=book.book_id,
                entity_perimeter=book.entity_perimeter,
                period_ids=tuple(p.period_id for p in book.periods),
                facility_ids=tuple(dict.fromkeys(f.facility_id for f in book.facilities)),
                quarter_ids=downstream.model.readiness.selected_quarters,
            ),
            downstream=downstream,
            original_row=original,
        ),
    )


def cp1_sufficiency_inputs(
    store: Execution, snapshot: ExecutionSnapshot, owner: Attempt, use: CP1Use
) -> M10CP1Inputs:
    """Authenticate bound CP-1 and derive one owner's scope and exact input hash."""
    return _inputs(store, snapshot, owner, use)[2]


def assess_cp1_sufficiency(
    store: Execution,
    snapshot: ExecutionSnapshot,
    owner: Attempt,
    use: CP1Use,
    review: ConsumerAssessment | None,
) -> M10CP1Report:
    """Validate judgments with production CP-1 rules and apply the original row ceiling.

    Original rows do not retain the owner's requirement/use version, so exact semantic
    equivalence cannot be proved here. Even original ready rows need a local review.
    """
    pack, producer, inputs = _inputs(store, snapshot, owner, use)
    financial = producer.financial
    bound_review = DownstreamReview(
        inputs_sha256=inputs.downstream.content_hash(),
        consumers=() if review is None else (review,),
    )
    report = canonical_downstream_readiness(
        pack,
        producer.context,
        financial.financial,
        financial.definition,
        financial.binding,
        producer.narrative,
        (owner.module_id,),
        bound_review,
        quarter_ids=financial.quarter_ids,
    )
    row = report.consumers[0]
    original = inputs.original_row
    statuses = (row.status,) if original is None else (row.status, original.status)
    status: Literal["ready", "ready_with_limitations", "not_ready"] = (
        "not_ready"
        if "not_ready" in statuses
        else "ready_with_limitations"
        if "ready_with_limitations" in statuses
        else "ready"
    )
    return M10CP1Report(
        inputs=inputs,
        downstream=report,
        status=status,
        limitations=tuple(
            dict.fromkeys(
                (
                    *report.limitations,
                    *producer.limitations,
                    *(original.actions if original is not None else ()),
                    *row.actions,
                )
            )
        ),
    )
