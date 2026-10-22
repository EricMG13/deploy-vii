"""Deterministic CP-0 and CP-1A delivery: retained input, validation receipt, limited report."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from deploy_vii.business_context import (
    BusinessContextSubmission,
    business_context,
    cp1a_module,
    validate_business_context,
)
from deploy_vii.contracts import Fact, Input, Module, ModuleView, View
from deploy_vii.execution import bounded_issues
from deploy_vii.preparation import PreparedPack
from deploy_vii.prose import prose_issues
from deploy_vii.readiness import ReadinessReview, build_readiness
from deploy_vii.registry import idle_statuses, modules
from deploy_vii.render import render

UNRUN = {
    "analytical_qualification": "unrun",
    "browser_acceptance": "unrun",
    "native_host_qualification": "unrun",
}


def cp0_view(pack: PreparedPack, module: Module, *, accepted: bool) -> View:
    """A view of one delivered module (CP-0 or CP-1A); every other module shows its idle state."""
    visible = module.status not in {"blocked", "stale", "rejected"}
    idle = idle_statuses(pack.run)
    return View(
        run=pack.run,
        mode="accepted" if accepted else "candidate",
        modules=tuple(
            ModuleView(
                module_id=item.module_id,
                title=item.title,
                aliases=item.aliases,
                status=module.status,
                artifact_sha256=module.content_hash(),
                facts=module.facts if visible else (),
                tables=module.tables if visible else (),
                claims=module.claims if visible else (),
                limitations=module.limitations,
            )
            if item.module_id == module.module_id
            else ModuleView(
                module_id=item.module_id,
                title=item.title,
                aliases=item.aliases,
                status=idle[item.module_id],
            )
            for item in modules()
        ),
        sources=pack.sources,
    )


def _publish(destination: Path, payloads: dict[str, str], receipt: Mapping[str, object]) -> None:
    files = {name: hashlib.sha256(value.encode()).hexdigest() for name, value in payloads.items()}
    destination.mkdir(parents=True, exist_ok=False)
    for name, payload in payloads.items():
        (destination / name).write_text(payload, encoding="utf-8")
    # Readers require this final receipt; interrupted directories are incomplete.
    (destination / "complete.json").write_text(
        json.dumps({**receipt, "files": files}, indent=2), encoding="utf-8"
    )


def _deliver_rejected(
    pack: PreparedPack,
    rejected: Module,
    retained: dict[str, str],
    receipt: Mapping[str, object],
    destination: Path,
) -> Path:
    """Publish a rejection, as the journal settles one: an empty module carrying the issues.

    Nothing is accepted, so there is no accepted view or page; the candidate page shows the
    module rejected with its issues and no findings (decision 0005 MC-2: fail closed by status).
    """
    view = cp0_view(pack, rejected, accepted=False)
    payloads = {
        **retained,
        "candidate-view.json": view.model_dump_json(indent=2),
        "candidate.html": render(view),
    }
    _publish(
        destination,
        payloads,
        {
            **receipt,
            "rejected_sha256": rejected.content_hash(),
            "structural_validation": "failed",
            **UNRUN,
            "status": "rejected",
        },
    )
    return destination / "candidate.html"


def _deliver_selected(
    pack: PreparedPack,
    candidate: Module,
    selected: Module,
    retained: tuple[str, str],
    receipt: Mapping[str, object],
    destination: Path,
) -> Path:
    """Publish the candidate and the selected (accepted, restricted or blocked) module."""
    candidate_view = cp0_view(pack, candidate, accepted=False)
    accepted_view = cp0_view(pack, selected, accepted=True)
    name, text = retained
    payloads = {
        "candidate.json": candidate.model_dump_json(indent=2),
        "accepted.json": selected.model_dump_json(indent=2),
        name: text,
        "candidate-view.json": candidate_view.model_dump_json(indent=2),
        "accepted-view.json": accepted_view.model_dump_json(indent=2),
        "candidate.html": render(candidate_view),
        "accepted.html": render(accepted_view),
    }
    _publish(
        destination,
        payloads,
        {
            **receipt,
            "candidate_sha256": candidate.content_hash(),
            "accepted_sha256": selected.content_hash(),
            "structural_validation": "passed",
            **UNRUN,
            "status": selected.status,
        },
    )
    return destination / "accepted.html"


def deliver_cp0(pack: PreparedPack, review: ReadinessReview, destination: Path) -> Path:
    """Validate before publication; acceptance here is structural, not live qualification.

    Claims whose run text does not resolve (a bare figure, an unknown reference) settle the
    delivery `rejected`, as the journal does, instead of raising when the page renders.
    """
    candidate = build_readiness(pack, review)
    head = {"schema_version": "cp0-delivery/1", "pack_sha256": pack.content_hash()}
    if issues := prose_issues(candidate, names=(pack.run.issuer_name,)):
        rejected = Module(
            run_id=candidate.run_id,
            issuer_id=candidate.issuer_id,
            as_of=candidate.as_of,
            module_id=candidate.module_id,
            inputs=candidate.inputs,
            attempt=candidate.attempt,
            status="rejected",
            limitations=bounded_issues(issues),
        )
        payloads = {
            "candidate.json": candidate.model_dump_json(indent=2),
            "rejected.json": rejected.model_dump_json(indent=2),
            "review.json": review.model_dump_json(indent=2),
        }
        receipt = {**head, "candidate_sha256": candidate.content_hash()}
        return _deliver_rejected(pack, rejected, payloads, receipt, destination)
    usable = any(
        source.status == "ready" and assessment.fidelity != "blocked"
        for source in pack.sources
        for assessment in review.sources
        if source.source_id == assessment.source_id
    )
    status = (
        "blocked"
        if not usable or not review.issuer_confirmed
        else "restricted"
        if candidate.limitations
        else "accepted"
    )
    limitations = candidate.limitations
    if status == "blocked" and not limitations:
        limitations = ("No usable identity-confirmed evidence for the requested work",)
    selected = Module.model_validate_json(
        candidate.model_copy(
            update={"status": status, "limitations": limitations}
        ).model_dump_json()
    )
    retained = ("review.json", review.model_dump_json(indent=2))
    return _deliver_selected(pack, candidate, selected, retained, head, destination)


def deliver_cp1a(
    pack: PreparedPack,
    submission: BusinessContextSubmission,
    destination: Path,
    cp1_facts: Sequence[Fact] = (),
) -> Path:
    """CP-1A as CP-0: the Python candidate composed from a valid submission, then published.

    A submission with any validator issue (citations, run text, rules, consumers) settles the
    delivery `rejected` with those issues, as the journal does; nothing is composed from it.
    Acceptance is structural: `restricted` when the candidate carries limitations.
    """
    head = {
        "schema_version": "cp1a-delivery/1",
        "pack_sha256": pack.content_hash(),
        "submission_sha256": submission.content_hash(),
    }
    inputs = (Input(input_id="prepared-pack", sha256=pack.content_hash()),)
    retained = ("submission.json", submission.model_dump_json(indent=2))
    if issues := validate_business_context(pack, submission, cp1_facts):
        run = pack.run
        rejected = Module(
            run_id=run.run_id,
            issuer_id=run.issuer_id,
            as_of=run.as_of,
            module_id="CP-1A",
            inputs=inputs,
            status="rejected",
            limitations=bounded_issues(issues),
        )
        payloads = {"rejected.json": rejected.model_dump_json(indent=2), retained[0]: retained[1]}
        return _deliver_rejected(pack, rejected, payloads, head, destination)
    candidate = cp1a_module(business_context(pack, submission, cp1_facts), inputs, 0)
    status = "restricted" if candidate.limitations else "accepted"
    selected = Module.model_validate_json(
        candidate.model_copy(update={"status": status}).model_dump_json()
    )
    return _deliver_selected(pack, candidate, selected, retained, head, destination)
