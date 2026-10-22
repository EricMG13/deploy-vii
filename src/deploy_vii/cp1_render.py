"""Render the Model destination and Credit Snapshot blocks from an accepted CP-1 envelope.

The accepted route (task 6.5): the CP-1 registers come from the verified canonical envelope,
never from a candidate. An envelope that does not verify against its journal renders no CP-1
block at all: CP-1 is shown blocked, with every verification issue as its limitation, so a
page can never mix refused data into a Front Page.
"""

import hashlib
import json
from pathlib import Path

from deploy_vii.contracts import ModuleView, View
from deploy_vii.cp1_workflow import EnvelopeRefused, read_cp1_envelope
from deploy_vii.envelope import Envelope
from deploy_vii.execution import Execution
from deploy_vii.render import render


def _with_cp1(base: View, cp1: ModuleView) -> View:
    if not any(item.module_id == "CP-1" for item in base.modules):
        raise ValueError("The view has no CP-1 module")
    return View.model_validate_json(
        base.model_copy(
            update={
                "modules": tuple(cp1 if item.module_id == "CP-1" else item for item in base.modules)
            }
        ).model_dump_json()
    )


def _cp1_of(base: View) -> ModuleView:
    return next(item for item in base.modules if item.module_id == "CP-1")


def envelope_view(base: View, envelope: Envelope) -> View:
    """`base` with its CP-1 module replaced by the envelope's settled module.

    `base` supplies every other module (the journal's accepted view, or an idle one); only an
    accepted or restricted envelope module is shown, and only for the base view's own run.
    """
    module = envelope.module
    if base.run != envelope.run:
        raise ValueError("The envelope belongs to another run than the view")
    if module.status not in ("accepted", "restricted"):
        raise ValueError(f"A {module.status} envelope module is not shown")
    return _with_cp1(
        base,
        _cp1_of(base).model_copy(
            update={
                "status": module.status,
                "artifact_sha256": module.content_hash(),
                "facts": module.facts,
                "tables": module.tables,
                "claims": module.claims,
                "limitations": tuple(
                    dict.fromkeys((*module.limitations, *module.inherited_limitations))
                ),
            }
        ),
    )


def refused_view(base: View, issues: tuple[str, ...]) -> View:
    """`base` with CP-1 blocked and without output; each issue is one limitation."""
    if not issues:
        raise ValueError("A refusal states its issues")
    return _with_cp1(
        base,
        _cp1_of(base).model_copy(
            update={
                "status": "blocked",
                "artifact_sha256": None,
                "facts": (),
                "tables": (),
                "claims": (),
                "limitations": tuple(f"Canonical envelope refused: {issue}" for issue in issues),
            }
        ),
    )


def render_cp1_envelope(
    store: Execution, directory: Path, destination: Path, *, pathway: str | None = None
) -> dict[str, object]:
    """Render the run's Pathway from the CP-1 envelope exported to `directory`.

    Writes `accepted.html` (or `refused.html` when the envelope does not verify) and a
    `complete.json` receipt into the new `destination`, and returns the receipt. The command
    does not accept rendering: the head's `rendering_acceptance` is recorded as it stands, and
    browser acceptance stays `unrun` until a browser test qualifies the page.
    """
    base = store.view()
    if pathway is not None and pathway != base.run.pathway:
        raise ValueError(
            f"The run's Pathway is {base.run.pathway}; its scope is immutable, not {pathway}"
        )
    issues: tuple[str, ...] = ()
    module_sha256: str | None = None
    try:
        envelope = read_cp1_envelope(store, directory)
    except EnvelopeRefused as refused:
        issues = refused.issues
        view = refused_view(base, issues)
    else:
        view = envelope_view(base, envelope)
        module_sha256 = envelope.module.content_hash()
    head = next((h for h in store.read().heads if h.module_id == "CP-1"), None)
    page = "refused.html" if issues else "accepted.html"
    html = render(view)
    receipt: dict[str, object] = {
        "schema_version": "cp1-render/1",
        "envelope": "refused" if issues else "verified",
        "issues": list(issues),
        "module_sha256": module_sha256,
        "pathway": view.run.pathway,
        "head_rendering_acceptance": (
            None
            if head is None or head.qualification is None
            else head.qualification.rendering_acceptance
        ),
        "browser_acceptance": "unrun",
        "files": {page: hashlib.sha256(html.encode()).hexdigest()},
    }
    destination.mkdir(parents=True, exist_ok=False)
    (destination / page).write_text(html, encoding="utf-8")
    (destination / "complete.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt
