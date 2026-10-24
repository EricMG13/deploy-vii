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
from tests.product.evidence import evidence_path
from tests.product.oracle import expected_by_fact, front_blocks, parity_record
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


def test_register_preview_front_page_is_built_from_the_bound_registers(tmp_path: Path) -> None:
    store, done = completed(tmp_path, partial=False)
    path = cp1_register_preview(store, done.ticket_id, tmp_path / "report")
    blocks = front_blocks(path.read_text())
    assert all(b["owner"] != "Unbound" for b in blocks.values())
    capital = blocks["capital-structure"]
    assert capital["state"] == "populated" and capital["tab_label"] == "Capital structure"
    assert [tab["label"] for tab in capital["tabs"]] == [
        "EBITDA adjustments",
        "Transaction and new debt",
    ]
    assert all(tab["note"] and not tab["rows"] for tab in capital["tabs"])  # registers hold no rows
    strip = blocks["model-chart-strip"]  # the KPI dashboard (T4.10) feeds the strip
    assert strip["state"] == "populated" and len(strip["rows"]) > 1
    assert blocks["key-findings"]["state"] == "not_run"


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
    evidence = evidence_path("canonical-registers", tmp_path)
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
        oracle = expected_by_fact(view)
        parity = parity_record({f.fact_id: oracle[f.fact_id] for f in module.facts}, dict(actual))
        assert parity["compared"] == len(module.facts) and not parity["mismatches"]
        assert all(text and text != "null" for _, text in actual)
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
                    "field_parity": parity,
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


def test_register_preview_prints_resolved_claim_text(tmp_path: Path) -> None:
    from deploy_vii.envelope import resolved_claims
    from deploy_vii.report_view import build_index
    from tests.product.test_cp1_workflow import staged

    store, done = staged(tmp_path)
    path = cp1_register_preview(store, done.ticket_id, tmp_path / "preview")
    view = View.model_validate_json((path.parent / "view.json").read_bytes())
    module = next(m for m in view.modules if m.module_id == "CP-1")
    text = (path.parent / "tables.md").read_text()
    analysis = text.split("## Analysis\n\n", 1)[1].split("\n\n## ", 1)[0]
    (expected, _), *_ = resolved_claims(module, build_index(view)[1], (view.run.issuer_name,))
    assert analysis == expected
    assert "interface-fact:" not in analysis and "{" not in analysis
    assert "[interface-fact:" in module.claims[0].text  # the stored run text keeps its refs
