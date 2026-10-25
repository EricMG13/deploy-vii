"""Offline frozen CP-1 authentication and owner-local sufficiency; no owner integration."""

import json
import shutil
from pathlib import Path

import pytest

from deploy_vii.cp0_workflow import submit_cp0_addendum, submit_cp0_review
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_workflow import (
    FinancialStage,
    FinancialSubmission,
    cp1_frozen_producer,
    cp1_registers,
    promote_cp1,
    submit_cp1_step,
    write_cp1_envelope,
)
from deploy_vii.downstream_readiness import (
    ConsumerAssessment,
    DownstreamInputs,
    DownstreamReview,
    GapAssessment,
    RequirementAssessment,
    canonical_downstream_readiness,
)
from deploy_vii.execution import Attempt, Execution, ExecutionSnapshot, current_inputs, text_sha256
from deploy_vii.m10_sufficiency import (
    CP1Use,
    assess_cp1_sufficiency,
    cp1_sufficiency_inputs,
)
from deploy_vii.readiness import ReadinessReview
from deploy_vii.source_context import SourceContextReview
from tests.product.test_cp1_workflow import at_ceiling
from tests.product.test_narrative import populated
from tests.product.test_workflow import payload, production_journal

USE = CP1Use(version="synthetic-owner:1", description="Synthetic covenant evidence use")


def assessment(inputs: DownstreamInputs, status: str = "sufficient") -> ConsumerAssessment:
    request = inputs.consumers[0]
    refs = tuple(r.evidence_id for r in inputs.narrative.inputs.catalogue if r.kind != "gap")
    return ConsumerAssessment(
        entry=request.entry,
        requirements=tuple(
            RequirementAssessment.model_validate(
                dict(
                    requirement=r,
                    status=status,
                    evidence_ids=refs if status != "missing" else (),
                    rationale="Synthetic evidence-bound sufficiency judgment",
                    actions=() if status == "sufficient" else ("Obtain required evidence",),
                )
            )
            for r in request.requirements
        ),
        gaps=tuple(
            GapAssessment(
                gap_ids=(g.gap_id,),
                relevance="not_relevant",
                evidence_ids=refs,
                rationale="Synthetic scope excludes this retained gap",
            )
            for g in inputs.narrative.gaps
        ),
    )


@pytest.fixture(scope="module")
def production(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return production_journal(tmp_path_factory.mktemp("m10-production"), ("CP-1",)).directory


@pytest.fixture
def owner(production: Path, tmp_path: Path) -> tuple[Execution, ExecutionSnapshot, Attempt]:
    shutil.copytree(production, tmp_path / "journal")
    store = Execution(tmp_path / "journal")
    requested = (*store.read().run.requested_modules, "CP-4")
    raw, context = payload(store, requested)
    assert submit_cp0_addendum(store, requested, raw, context_sha256=context).extended
    ticket = store.begin("CP-4")
    assert ticket.inputs == current_inputs(store.read(), "CP-4")
    assert ticket.inputs[-1].input_id == "readiness-addendum"
    return store, store.read(), ticket


def test_real_frozen_producer_and_no_review_fail_closed(
    owner: tuple[Execution, ExecutionSnapshot, Attempt], tmp_path: Path
) -> None:
    store, snapshot, ticket = owner
    before = snapshot.model_dump_json()
    exported = write_cp1_envelope(store, tmp_path / "before").parent
    files = {p.name: p.read_bytes() for p in exported.iterdir()}
    producer = cp1_frozen_producer(store, snapshot, ticket)
    assert producer.ticket_id == next(
        a.ticket_id for a in snapshot.attempts if a.module_id == "CP-1"
    )
    inputs = cp1_sufficiency_inputs(store, snapshot, ticket, USE)
    assert inputs.original_row is None
    report = assess_cp1_sufficiency(store, snapshot, ticket, USE, None)
    assert report.status == "not_ready"
    assert report.downstream.consumers[0].unassessed_requirements
    assert report.analytical_qualification == "unrun"
    assert store.read().model_dump_json() == before
    again = write_cp1_envelope(store, tmp_path / "after").parent
    assert {p.name: p.read_bytes() for p in again.iterdir()} == files


def test_local_report_is_production_recomputation_and_omissions_cannot_improve(
    owner: tuple[Execution, ExecutionSnapshot, Attempt],
) -> None:
    store, snapshot, ticket = owner
    inputs = cp1_sufficiency_inputs(store, snapshot, ticket, USE)
    producer = cp1_frozen_producer(store, snapshot, ticket)
    review = assessment(inputs.downstream)
    report = assess_cp1_sufficiency(store, snapshot, ticket, USE, review)
    f = producer.financial
    expected = canonical_downstream_readiness(
        store.pack(snapshot),
        producer.context,
        f.financial,
        f.definition,
        f.binding,
        producer.narrative,
        (ticket.module_id,),
        DownstreamReview(inputs_sha256=inputs.downstream.content_hash(), consumers=(review,)),
        quarter_ids=f.quarter_ids,
    )
    assert report.downstream == expected
    assert report.status == expected.consumers[0].status == "ready"
    assert report.downstream.inputs.financial_book == inputs.downstream.financial_book
    # Differential over every missing-support combination, using the production composer.
    for missing_requirements, missing_gaps in ((True, False), (False, True), (True, True)):
        omitted = review.model_copy(
            update={
                "requirements": () if missing_requirements else review.requirements,
                "gaps": () if missing_gaps else review.gaps,
            }
        )
        result = assess_cp1_sufficiency(store, snapshot, ticket, USE, omitted)
        assert result.status == "not_ready"
        assert result.downstream.inputs.narrative.gaps == expected.inputs.narrative.gaps


@pytest.mark.parametrize("mode", ["consumer", "evidence", "requirement", "gap", "overlap"])
def test_malformed_owner_review_refuses(
    owner: tuple[Execution, ExecutionSnapshot, Attempt], mode: str
) -> None:
    store, snapshot, ticket = owner
    inputs = cp1_sufficiency_inputs(store, snapshot, ticket, USE)
    review = assessment(inputs.downstream)
    if mode == "consumer":
        review = review.model_copy(update={"entry": "CP-4A"})
    elif mode in {"evidence", "requirement"}:
        item = review.requirements[0].model_copy(
            update={
                "evidence_ids": ("unknown",),
            }
            if mode == "evidence"
            else {"requirement": "invented"}
        )
        review = review.model_copy(update={"requirements": (item, *review.requirements[1:])})
    elif mode == "gap":
        review = review.model_copy(
            update={"gaps": (review.gaps[0].model_copy(update={"gap_ids": ("unknown",)}),)}
        )
    else:
        review = review.model_copy(update={"gaps": (*review.gaps, review.gaps[0])})
    with pytest.raises(ValueError):
        assess_cp1_sufficiency(store, snapshot, ticket, USE, review)


def test_hash_locality_and_no_current_snapshot_reread(
    owner: tuple[Execution, ExecutionSnapshot, Attempt], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, snapshot, ticket = owner
    inputs = cp1_sufficiency_inputs(store, snapshot, ticket, USE)

    # Snapshot is supplied by the locked owner submission; rereading would deadlock/drift.
    def refuse_read() -> ExecutionSnapshot:
        raise AssertionError("Unexpected current snapshot read")

    monkeypatch.setattr(store, "read", refuse_read)
    extended = snapshot.model_copy(
        update={
            "run": snapshot.run.model_copy(
                update={
                    "requested_modules": (*snapshot.run.requested_modules, "CP-MODEL"),
                }
            ),
            "attempts": (
                *snapshot.attempts,
                ticket.model_copy(
                    update={
                        "ticket_id": "unrelated-later-attempt",
                        "module_id": "CP-MEMO",
                        "status": "finished",
                    }
                ),
            ),
        }
    )
    assert (
        cp1_sufficiency_inputs(store, extended, ticket, USE).content_hash() == inputs.content_hash()
    )
    revised = USE.model_copy(update={"version": "synthetic-owner:2"})
    assert (
        cp1_sufficiency_inputs(store, extended, ticket, revised).content_hash()
        != inputs.content_hash()
    )


def test_real_disjoint_extension_preserves_hash_and_source_replacement_refuses(
    owner: tuple[Execution, ExecutionSnapshot, Attempt],
) -> None:
    store, snapshot, ticket = owner
    inputs = cp1_sufficiency_inputs(store, snapshot, ticket, USE)
    old_head = next(h for h in snapshot.heads if h.module_id == "CP-1")
    old_result = store.payload(old_head.result_sha256)
    store.interrupt(ticket.ticket_id, "Synthetic locality check")
    store.extend_scope((*snapshot.run.requested_modules, "CP-MODEL"))
    repair = store.begin("CP-4")
    assert repair.inputs == ticket.inputs
    assert (
        cp1_sufficiency_inputs(store, store.read(), repair, USE).content_hash()
        == inputs.content_hash()
    )
    store.interrupt(repair.ticket_id, "Synthetic source replacement check")
    pack = store.pack()
    first = pack.sources[0]
    replacement = "Changed synthetic source"
    changed = first.model_copy(
        update={
            "sha256": text_sha256(replacement),
            "spans": (first.spans[0].model_copy(update={"text": replacement}),),
        }
    )
    store.replace_pack(pack.model_copy(update={"sources": (changed, *pack.sources[1:])}))
    refreshed = store.read()
    assert next(h for h in refreshed.heads if h.module_id == "CP-1").status == "stale"
    with pytest.raises(ValueError):
        cp1_sufficiency_inputs(store, refreshed, repair, USE)
    assert store.payload(old_head.result_sha256) == old_result


def test_unrelated_genuine_heads_and_blobs_do_not_enter_local_binding(tmp_path: Path) -> None:
    store = production_journal(tmp_path)
    requested = (*store.read().run.requested_modules, "CP-4")
    raw, context = payload(store, requested)
    assert submit_cp0_addendum(store, requested, raw, context_sha256=context).extended
    ticket = store.begin("CP-4")
    snapshot = store.read()
    before = cp1_sufficiency_inputs(store, snapshot, ticket, USE)
    unrelated = tuple(h for h in snapshot.heads if h.module_id in {"CP-1A", "CP-5"})
    assert len(unrelated) == 2
    for head in unrelated:
        (store.directory / "blobs" / head.result_sha256).unlink()
    changed = snapshot.model_copy(
        update={"heads": tuple(h for h in snapshot.heads if h not in unrelated)}
    )
    assert cp1_sufficiency_inputs(store, changed, ticket, USE) == before


def test_workbook_consumer_cannot_be_mistaken_for_an_analytical_row(
    owner: tuple[Execution, ExecutionSnapshot, Attempt],
) -> None:
    store, snapshot, ticket = owner
    store.interrupt(ticket.ticket_id, "Synthetic workbook consumer refusal")
    store.extend_scope((*snapshot.run.requested_modules, "CP-MODEL"))
    model = store.begin("CP-MODEL")
    with pytest.raises(ValueError, match="no CP-1 analytical consumer"):
        assess_cp1_sufficiency(store, store.read(), model, USE, None)


@pytest.mark.parametrize("mode", ["owner", "stale", "status", "producer", "missing", "corrupt"])
def test_authentication_refuses_instead_of_reporting_a_gap(
    owner: tuple[Execution, ExecutionSnapshot, Attempt], mode: str
) -> None:
    store, snapshot, ticket = owner
    head = next(h for h in snapshot.heads if h.module_id == "CP-1")
    producer = next(a for a in snapshot.attempts if a.result_sha256 == head.result_sha256)
    if mode == "owner":
        ticket = ticket.model_copy(update={"ticket_id": "invented"})
    elif mode in {"stale", "status"}:
        changed = head.model_copy(update={"status": "stale" if mode == "stale" else "accepted"})
        snapshot = snapshot.model_copy(
            update={"heads": tuple(changed if h == head else h for h in snapshot.heads)}
        )
    elif mode == "producer":
        snapshot = snapshot.model_copy(
            update={"attempts": tuple(a for a in snapshot.attempts if a != producer)}
        )
    else:
        blob = store.directory / "blobs" / producer.steps[1].payload_sha256
        if mode == "missing":
            blob.unlink()
        else:
            blob.write_text("{}")
    with pytest.raises((ValueError, FileNotFoundError)):
        assess_cp1_sufficiency(store, snapshot, ticket, USE, None)


@pytest.mark.parametrize("stage", range(5))
@pytest.mark.parametrize("kind", ["payload", "output"])
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_every_retained_blob_is_required(
    owner: tuple[Execution, ExecutionSnapshot, Attempt], stage: int, kind: str, damage: str
) -> None:
    store, snapshot, ticket = owner
    producer = next(a for a in snapshot.attempts if a.module_id == "CP-1")
    step = producer.steps[stage]
    digest = step.payload_sha256 if kind == "payload" else step.output_sha256
    path = store.directory / "blobs" / str(digest)
    if damage == "missing":
        path.unlink()
    else:
        path.write_text("{}")
    with pytest.raises((ValueError, FileNotFoundError)):
        cp1_frozen_producer(store, snapshot, ticket)


@pytest.mark.parametrize("kind", ["pack", "candidate", "result"])
def test_missing_root_provenance_refuses(
    owner: tuple[Execution, ExecutionSnapshot, Attempt], kind: str
) -> None:
    store, snapshot, ticket = owner
    producer = next(a for a in snapshot.attempts if a.module_id == "CP-1")
    digest = (
        snapshot.pack_sha256
        if kind == "pack"
        else producer.payload_sha256
        if kind == "candidate"
        else producer.result_sha256
    )
    (store.directory / "blobs" / str(digest)).unlink()
    with pytest.raises(ValueError, match="missing"):
        cp1_frozen_producer(store, snapshot, ticket)


def test_exact_producing_attempt_not_latest_and_raw_hashes_are_preserved(
    owner: tuple[Execution, ExecutionSnapshot, Attempt],
) -> None:
    store, snapshot, ticket = owner
    producer = cp1_frozen_producer(store, snapshot, ticket)
    original = next(a for a in snapshot.attempts if a.ticket_id == producer.ticket_id)
    later = original.model_copy(
        update={
            "ticket_id": "unbound-later-attempt",
            "result_sha256": "0" * 64,
            "steps": (),
        }
    )
    snapshot = snapshot.model_copy(update={"attempts": (*snapshot.attempts, later)})
    assert cp1_frozen_producer(store, snapshot, ticket) == producer
    for step in original.steps:
        assert text_sha256(store.payload(step.payload_sha256)) == step.payload_sha256


@pytest.mark.parametrize("mode", ["step_prefix", "quality", "qualification", "duplicate_producer"])
def test_retained_metadata_cannot_forge_a_promotion(
    owner: tuple[Execution, ExecutionSnapshot, Attempt], mode: str
) -> None:
    store, snapshot, ticket = owner
    original = next(a for a in snapshot.attempts if a.module_id == "CP-1")
    if mode == "qualification":
        snapshot = snapshot.model_copy(
            update={
                "heads": tuple(
                    h.model_copy(update={"qualification": None}) if h.module_id == "CP-1" else h
                    for h in snapshot.heads
                )
            }
        )
    elif mode == "duplicate_producer":
        snapshot = snapshot.model_copy(
            update={
                "attempts": (
                    *snapshot.attempts,
                    original.model_copy(update={"ticket_id": "duplicate-producing-attempt"}),
                )
            }
        )
    else:
        index = 1 if mode == "step_prefix" else 4
        step = original.steps[index].model_copy(
            update={
                "inputs": original.inputs,
            }
            if mode == "step_prefix"
            else {"status": "pending", "output_sha256": None}
        )
        changed = original.model_copy(
            update={"steps": tuple(step if i == index else s for i, s in enumerate(original.steps))}
        )
        snapshot = snapshot.model_copy(
            update={"attempts": tuple(changed if a == original else a for a in snapshot.attempts)}
        )
    with pytest.raises(ValueError):
        cp1_frozen_producer(store, snapshot, ticket)


def test_forged_settled_result_cannot_drop_inherited_limitations(
    owner: tuple[Execution, ExecutionSnapshot, Attempt],
) -> None:
    store, snapshot, ticket = owner
    head = next(h for h in snapshot.heads if h.module_id == "CP-1")
    original = next(a for a in snapshot.attempts if a.result_sha256 == head.result_sha256)
    module = store.head_module(head)
    assert module.inherited_limitations
    forged = module.model_copy(update={"inherited_limitations": ()})
    digest = store._store(forged.model_dump_json())
    owner_inputs = tuple(
        i.model_copy(update={"sha256": digest}) if i.input_id == "CP-1" else i
        for i in ticket.inputs
    )
    changed_owner = ticket.model_copy(update={"inputs": owner_inputs})
    changed_producer = original.model_copy(update={"result_sha256": digest})
    changed = snapshot.model_copy(
        update={
            "heads": tuple(
                h.model_copy(update={"result_sha256": digest}) if h == head else h
                for h in snapshot.heads
            ),
            "attempts": tuple(
                changed_owner if a == ticket else changed_producer if a == original else a
                for a in snapshot.attempts
            ),
        }
    )
    with pytest.raises(ValueError):
        cp1_frozen_producer(store, changed, changed_owner)


def test_cp0_only_original_scope_grants_cp1_and_later_consumer(
    production: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Execution(production)
    old = source.read()
    pack = source.pack(old)
    pack = pack.model_copy(
        update={
            "run": pack.run.model_copy(
                update={
                    "requested_modules": ("CP-0",),
                }
            )
        }
    )
    old_cp0 = next(a for a in old.attempts if a.module_id == "CP-0")
    review = ReadinessReview.model_validate_json(source.payload(old_cp0.steps[0].payload_sha256))
    review = review.model_copy(update={"pack_sha256": pack.content_hash(), "consumers": ()})
    store = Execution.create(tmp_path / "grant-journal", pack)
    assert not submit_cp0_review(
        store, store.begin("CP-0").ticket_id, review.model_dump_json()
    ).issues
    requested = ("CP-0", "CP-1")
    raw, context_hash = payload(store, requested)
    assert submit_cp0_addendum(store, requested, raw, context_sha256=context_hash).extended
    ticket = store.begin("CP-1")
    assert ticket.inputs[-1].input_id == "readiness-addendum"
    old_cp1 = next(a for a in old.attempts if a.module_id == "CP-1")
    context = SourceContextReview.model_validate_json(
        source.payload(old_cp1.steps[0].payload_sha256)
    )
    context = context.model_copy(update={"pack_sha256": pack.content_hash()})
    done = submit_cp1_step(store, ticket.ticket_id, "source_context", context.model_dump_json())
    assert not done.issues
    financial = FinancialSubmission.model_validate_json(
        source.payload(old_cp1.steps[1].payload_sha256)
    )
    extracted = financial.financial.model_copy(update={"pack_sha256": pack.content_hash()})
    financial = financial.model_copy(
        update={
            "context_step_sha256": done.steps[0].content_hash(),
            "financial": extracted,
            "definition": financial.definition.model_copy(
                update={
                    "financial_review_sha256": extracted.content_hash(),
                }
            ),
            "binding": financial.binding.model_copy(
                update={
                    "financial_review_sha256": extracted.content_hash(),
                    "source_context_review_sha256": context.content_hash(),
                }
            ),
        }
    )
    done = submit_cp1_step(store, ticket.ticket_id, "financials", financial.model_dump_json())
    assert not done.issues
    stage = FinancialStage.model_validate_json(
        store.step_output(done.steps[-1].output_sha256 or "")
    )
    done = submit_cp1_step(
        store, ticket.ticket_id, "narrative", populated(stage.narrative_inputs).model_dump_json()
    )
    assert not done.issues
    downstream = DownstreamInputs.model_validate_json(
        store.step_output(done.steps[-1].output_sha256 or "")
    )
    assert downstream.requested_consumers == ()
    done = submit_cp1_step(
        store,
        ticket.ticket_id,
        "readiness",
        DownstreamReview(inputs_sha256=downstream.content_hash()).model_dump_json(),
    )
    assert not done.issues
    quality = cp1_quality_inputs(cp1_registers(store, ticket.ticket_id))
    done = promote_cp1(store, ticket.ticket_id, at_ceiling(quality).model_dump_json())
    assert not done.issues
    first_grant = done.inputs[-1].sha256
    requested = (*requested, "CP-4")
    raw, context_hash = payload(store, requested)
    assert submit_cp0_addendum(store, requested, raw, context_sha256=context_hash).extended
    owner = store.begin("CP-4")
    snapshot = store.read()
    assert store.pack(snapshot).run.requested_modules == ("CP-0",)

    def refuse_pointer_read() -> ExecutionSnapshot:
        raise AssertionError("Frozen producer must use the supplied trusted snapshot")

    monkeypatch.setattr(store, "read", refuse_pointer_read)
    monkeypatch.setattr(store, "_snapshot", refuse_pointer_read)
    frozen = cp1_frozen_producer(store, snapshot, owner)
    assert frozen.inputs[-1].sha256 == first_grant != owner.inputs[-1].sha256
    assert frozen.registers.downstream.consumers == ()
    assert assess_cp1_sufficiency(store, snapshot, owner, USE, None).status == "not_ready"
    (store.directory / "blobs" / first_grant).unlink()
    with pytest.raises(ValueError, match="missing"):
        cp1_frozen_producer(store, snapshot, owner)


@pytest.mark.parametrize("ceiling", ["sufficient", "limited", "missing"])
def test_original_ceiling_never_raised_and_never_reused_by_name(
    tmp_path: Path, ceiling: str
) -> None:
    source = production_journal(tmp_path / "source", ("CP-1", "CP-4"))
    original = source.read()
    store = Execution.create(tmp_path / "replay", source.pack(original))
    cp0 = next(a for a in original.attempts if a.module_id == "CP-0")
    assert not submit_cp0_review(
        store, store.begin("CP-0").ticket_id, source.payload(cp0.steps[0].payload_sha256)
    ).issues
    old = next(a for a in original.attempts if a.module_id == "CP-1")
    ticket = store.begin("CP-1")
    for step in old.steps[:3]:
        done = submit_cp1_step(
            store, ticket.ticket_id, step.step_id, source.payload(step.payload_sha256)
        )
        assert not done.issues
    inputs = DownstreamInputs.model_validate_json(
        store.step_output(done.steps[-1].output_sha256 or "")
    )
    review = DownstreamReview(
        inputs_sha256=inputs.content_hash(), consumers=(assessment(inputs, ceiling),)
    )
    done = submit_cp1_step(
        store, ticket.ticket_id, "readiness", json.dumps(review.model_dump(mode="json"), indent=2)
    )
    assert not done.issues
    assert done.steps[-1].payload_sha256 != review.content_hash()
    quality = cp1_quality_inputs(cp1_registers(store, ticket.ticket_id))
    assert not promote_cp1(store, ticket.ticket_id, at_ceiling(quality).model_dump_json()).issues
    owner_ticket = store.begin("CP-4")
    snapshot = store.read()
    bound = cp1_sufficiency_inputs(store, snapshot, owner_ticket, USE)
    assert bound.original_row is not None
    no_review = assess_cp1_sufficiency(store, snapshot, owner_ticket, USE, None)
    assert no_review.status == "not_ready"
    report = assess_cp1_sufficiency(
        store, snapshot, owner_ticket, USE, assessment(bound.downstream)
    )
    assert report.status == bound.original_row.status
    assert set(bound.original_row.actions) <= set(report.limitations)
