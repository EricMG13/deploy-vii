"""Ordered-stage register rendering and offline field parity."""

import hashlib
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from deploy_vii.contracts import View
from deploy_vii.cp1_workflow import FinancialStage, cp1_register_preview, submit_cp1_step
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview
from deploy_vii.execution import Attempt, Execution
from deploy_vii.render import table_display
from tests.product.test_execution import step_text
from tests.product.test_narrative import draft
from tests.product.test_workflow import cp1_case


def completed(tmp_path: Path, *, partial: bool = True) -> tuple[Execution, Attempt]:
    store, ticket, extraction = cp1_case(tmp_path, partial=partial)
    financial = submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    output = FinancialStage.model_validate_json(step_text(store, financial.steps[-1]))
    narrative = submit_cp1_step(
        store, ticket.ticket_id, "narrative", draft(output.narrative_inputs).model_dump_json()
    )
    inputs = DownstreamInputs.model_validate_json(step_text(store, narrative.steps[-1]))
    done = submit_cp1_step(
        store,
        ticket.ticket_id,
        "readiness",
        DownstreamReview(inputs_sha256=inputs.content_hash()).model_dump_json(),
    )
    assert not done.issues
    return store, done


def test_preview_requires_every_valid_stage_and_preserves_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    store, ticket, _ = cp1_case(tmp_path / "early")
    with pytest.raises(ValueError, match="must be valid"):
        cp1_register_preview(store, ticket.ticket_id, tmp_path / "missing")
    with pytest.raises(ValueError, match="not available"):
        cp1_register_preview(store, "missing", tmp_path / "missing")
    store, done = completed(tmp_path / "complete")
    before = store.read().content_hash()
    output = tmp_path / "preview"
    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy-vii",
            "execution",
            "--directory",
            str(store.directory),
            "register-preview",
            "--ticket",
            done.ticket_id,
            "--output",
            str(output),
        ],
    )
    main()
    assert capsys.readouterr().out.strip() == str(output / "candidate.html")
    assert store.read().content_hash() == before
    receipt = json.loads((output / "complete.json").read_text())
    assert receipt["execution_binding"]["snapshot_sha256"] == before
    assert receipt["module_acceptance"] == receipt["analytical_qualification"] == "unrun"
    for name, digest in receipt["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    text = (output / "tables.md").read_text()
    assert text.count("<!-- table-id: cp1.downstream_readiness -->") == 1
    assert "## T4.12" in text and "not the final downstream" in text
    with pytest.raises(FileExistsError):
        cp1_register_preview(store, done.ticket_id, output)


@pytest.mark.parametrize("stage", [0, 1, 2, 3])
def test_each_retained_stage_is_recomputed_before_any_files_are_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: int
) -> None:
    store, done = completed(tmp_path)
    snapshot = store.read()
    steps = list(done.steps)
    tampered = step_text(store, steps[stage]) + " "
    steps[stage] = steps[stage].model_copy(update={"output_sha256": store._store(tampered)})
    changed = done.model_copy(update={"steps": tuple(steps)})
    snapshot = snapshot.model_copy(
        update={
            "attempts": tuple(
                changed if a.ticket_id == done.ticket_id else a for a in snapshot.attempts
            )
        }
    )
    monkeypatch.setattr(store, "read", lambda: snapshot)
    target = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="differs from trusted"):
        cp1_register_preview(store, done.ticket_id, target)
    assert not target.exists()


@pytest.mark.browser
@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 800)])
def test_register_fields_and_provenance_offline(tmp_path: Path, width: int, height: int) -> None:
    store, done = completed(tmp_path)
    path = cp1_register_preview(store, done.ticket_id, tmp_path / "report")
    view = View.model_validate_json((path.parent / "view.json").read_bytes())
    module = next(m for m in view.modules if m.module_id == "CP-1")
    evidence = (
        Path("artifacts/rendering/canonical-registers") / tmp_path.parent.name / tmp_path.name
    )
    evidence.mkdir(parents=True)
    for name in ("view.json", "tables.md", "complete.json", "candidate.html"):
        (evidence / name).write_bytes((path.parent / name).read_bytes())
    errors, requests = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, offline=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.goto(path.as_uri() + "#CP-1")
        actual = page.locator("[data-fact-id]").evaluate_all(
            "nodes => nodes.map(n => [n.dataset.factId,n.textContent])"
        )
        assert len(actual) == len(module.facts)
        assert dict(actual) == {f.fact_id: table_display(f) for f in module.facts}
        fact = next(
            f
            for f in module.facts
            if f.table_id == "T4.9" and f.calculation_id and f.amount is not None
        )
        target = page.locator(f'[data-fact-id="{fact.fact_id}"]')
        target.focus()
        page.keyboard.press("Enter")
        inspector = page.get_by_role("complementary", name="Evidence inspector")
        expect(inspector).to_contain_text(fact.calculation_id)
        expect(inspector).to_contain_text(fact.formula)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(evidence / f"registers-{width}x{height}.png"))
        page.evaluate("document.body.style.zoom='1.25'")
        target.scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(evidence / "zoom.png"))
        assert not errors and not [r for r in requests if r.startswith(("http:", "https:"))]
        (evidence / "checks.json").write_text(
            json.dumps(
                {
                    "viewport": [width, height],
                    "field_parity": "passed",
                    "errors": errors,
                    "requests": requests,
                    "analytical_qualification": "unrun",
                }
            )
        )
        browser.close()


def test_preview_rejects_changed_upstream_identity_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, done = completed(tmp_path)
    snapshot = store.read()
    changed = done.model_copy(update={"inputs": ()})
    snapshot = snapshot.model_copy(
        update={
            "attempts": tuple(
                changed if a.ticket_id == done.ticket_id else a for a in snapshot.attempts
            )
        }
    )
    monkeypatch.setattr(store, "read", lambda: snapshot)
    with pytest.raises(ValueError, match="inputs are stale"):
        cp1_register_preview(store, done.ticket_id, tmp_path / "stale")
    assert not (tmp_path / "stale").exists()
