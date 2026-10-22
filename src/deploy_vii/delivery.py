"""Deterministic CP-0 delivery: retained candidate, validation receipt and limited report."""

import hashlib
import json
from pathlib import Path

from deploy_vii.contracts import Module, ModuleView, View
from deploy_vii.execution import bounded_issues
from deploy_vii.preparation import PreparedPack
from deploy_vii.prose import prose_issues
from deploy_vii.readiness import ReadinessReview, build_readiness
from deploy_vii.registry import idle_statuses, modules
from deploy_vii.render import render


def cp0_view(pack: PreparedPack, module: Module, *, accepted: bool) -> View:
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


def _deliver_rejected(
    pack: PreparedPack,
    review: ReadinessReview,
    candidate: Module,
    issues: tuple[str, ...],
    destination: Path,
) -> Path:
    """Publish a rejection, as the journal settles one: an empty module carrying the issues.

    Nothing is accepted, so there is no accepted view or page; the candidate page shows CP-0
    rejected with its issues and no findings (decision 0005 MC-2: fail closed by status).
    """
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
    view = cp0_view(pack, rejected, accepted=False)
    payloads = {
        "candidate.json": candidate.model_dump_json(indent=2),
        "rejected.json": rejected.model_dump_json(indent=2),
        "review.json": review.model_dump_json(indent=2),
        "candidate-view.json": view.model_dump_json(indent=2),
        "candidate.html": render(view),
    }
    receipt = {
        "schema_version": "cp0-delivery/1",
        "pack_sha256": pack.content_hash(),
        "candidate_sha256": candidate.content_hash(),
        "rejected_sha256": rejected.content_hash(),
        "structural_validation": "failed",
        "analytical_qualification": "unrun",
        "browser_acceptance": "unrun",
        "native_host_qualification": "unrun",
        "status": "rejected",
        "files": {
            name: hashlib.sha256(value.encode()).hexdigest() for name, value in payloads.items()
        },
    }
    destination.mkdir(parents=True, exist_ok=False)
    for name, payload in payloads.items():
        (destination / name).write_text(payload, encoding="utf-8")
    (destination / "complete.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return destination / "candidate.html"


def deliver_cp0(pack: PreparedPack, review: ReadinessReview, destination: Path) -> Path:
    """Validate before publication; acceptance here is structural, not live qualification.

    Claims whose run text does not resolve (a bare figure, an unknown reference) settle the
    delivery `rejected`, as the journal does, instead of raising when the page renders.
    """
    candidate = build_readiness(pack, review)
    if issues := prose_issues(candidate, names=(pack.run.issuer_name,)):
        return _deliver_rejected(pack, review, candidate, issues, destination)
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
    candidate_view = cp0_view(pack, candidate, accepted=False)
    accepted_view = cp0_view(pack, selected, accepted=True)
    payloads = {
        "candidate.json": candidate.model_dump_json(indent=2),
        "accepted.json": selected.model_dump_json(indent=2),
        "review.json": review.model_dump_json(indent=2),
        "candidate-view.json": candidate_view.model_dump_json(indent=2),
        "accepted-view.json": accepted_view.model_dump_json(indent=2),
        "candidate.html": render(candidate_view),
        "accepted.html": render(accepted_view),
    }
    receipt = {
        "schema_version": "cp0-delivery/1",
        "pack_sha256": pack.content_hash(),
        "candidate_sha256": candidate.content_hash(),
        "accepted_sha256": selected.content_hash(),
        "structural_validation": "passed",
        "analytical_qualification": "unrun",
        "browser_acceptance": "unrun",
        "native_host_qualification": "unrun",
        "status": status,
        "files": {
            name: hashlib.sha256(value.encode()).hexdigest() for name, value in payloads.items()
        },
    }
    destination.mkdir(parents=True, exist_ok=False)
    for name, payload in payloads.items():
        (destination / name).write_text(payload, encoding="utf-8")
    # Readers require this final receipt; interrupted directories are incomplete.
    (destination / "complete.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return destination / "accepted.html"
