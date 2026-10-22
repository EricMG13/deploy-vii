import hashlib
import json
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from deploy_vii.contracts import View
from deploy_vii.delivery import deliver_cp0
from deploy_vii.preparation import PreparationRequest, SourceRequest
from deploy_vii.readiness import ReadinessReview
from deploy_vii.registry import dependencies
from tests.product.evidence import evidence_path
from tests.product.oracle import front_blocks
from tests.product.test_readiness import readiness_fixture


def test_candidate_and_accepted_delivery_are_distinct_and_hashed(tmp_path: Path) -> None:
    pack, review = readiness_fixture()
    target = tmp_path / "delivery"
    deliver_cp0(pack, review, target)
    receipt = json.loads((target / "complete.json").read_bytes())
    assert receipt["status"] == "restricted"
    assert receipt["analytical_qualification"] == "unrun"
    assert receipt["browser_acceptance"] == "unrun"
    for name, digest in receipt["files"].items():
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == digest
    candidate = View.model_validate_json((target / "candidate-view.json").read_bytes())
    accepted = View.model_validate_json((target / "accepted-view.json").read_bytes())
    assert candidate.modules[0].status == "candidate"
    assert accepted.modules[0].status == "restricted"
    assert candidate.modules[0].facts == accepted.modules[0].facts
    in_scope = set(dependencies(accepted.run.requested_modules))
    assert [item.status for item in accepted.modules[1:]] == [
        "unrun" if item.module_id in in_scope else "not_in_pathway" for item in accepted.modules[1:]
    ]
    # The Front Page is built, not idle: CP-0 binds to rail destinations only, so every block
    # of the Credit Snapshot shows its own honest state under its FP 01 owner.
    for name in ("candidate.html", "accepted.html"):
        blocks = front_blocks((target / name).read_text())
        assert all(b["owner"] != "Unbound" for b in blocks.values())
        assert {b["state"] for b in blocks.values()} <= {"not_run", "absent", "outside"}
        assert blocks["key-findings"]["note"] == "Not run: CP-2 has not run."
    with pytest.raises(FileExistsError):
        deliver_cp0(pack, review, target)


def test_invalid_review_never_publishes(tmp_path: Path) -> None:
    pack, review = readiness_fixture()
    with pytest.raises(ValueError, match="bind"):
        deliver_cp0(pack, review.model_copy(update={"pack_sha256": "0" * 64}), tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_unconfirmed_issuer_blocks_accepted_outputs(tmp_path: Path) -> None:
    pack, review = readiness_fixture()
    blocked = review.model_copy(
        update={
            "issuer_confirmed": False,
            "consumers": tuple(
                item.model_copy(update={"readiness": "BLOCKED", "source_ids": (), "citations": ()})
                for item in review.consumers
            ),
        }
    )
    deliver_cp0(pack, blocked, tmp_path / "blocked")
    accepted = View.model_validate_json((tmp_path / "blocked/accepted-view.json").read_bytes())
    assert accepted.modules[0].status == "blocked"
    assert not accepted.modules[0].facts
    assert not accepted.modules[0].claims


def test_cli_preparation_and_cp0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deploy_vii.__main__ import main

    pack, review = readiness_fixture()
    (tmp_path / "filing.txt").write_bytes(b"Synthetic issuer FY2025 cash USD million 0\n")
    request = PreparationRequest(
        run=pack.run,
        sources=(SourceRequest(source_id="filing", path="filing.txt", media_type="text/plain"),),
    )
    (tmp_path / "request.json").write_text(request.model_dump_json())
    (tmp_path / "review.json").write_text(review.model_dump_json())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy-vii",
            "prepare",
            "--request",
            str(tmp_path / "request.json"),
            "--root",
            str(tmp_path),
            "--output",
            str(tmp_path / "pack"),
        ],
    )
    main()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy-vii",
            "cp0",
            "--pack",
            str(tmp_path / "pack"),
            "--review",
            str(tmp_path / "review.json"),
            "--output",
            str(tmp_path / "report"),
        ],
    )
    main()
    assert (tmp_path / "report/accepted.html").is_file()


@pytest.mark.browser
@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 800)])
def test_cp0_actual_fields_browser_evidence_and_offline_report(
    tmp_path: Path, width: int, height: int
) -> None:
    pack, review = readiness_fixture()
    evidence = evidence_path("cp0", tmp_path)
    accepted_path = deliver_cp0(pack, review, evidence).resolve()
    (evidence / "pack.json").write_text(pack.model_dump_json(indent=2))
    errors: list[str] = []
    requests: list[str] = []
    view = View.model_validate_json((evidence / "accepted-view.json").read_bytes())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": height}, offline=True)
        context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.goto(accepted_path.as_uri() + "#CP-0")
        expect(page.get_by_role("heading", name="CP-0 · Source readiness")).to_be_visible()
        page.screenshot(path=str(evidence / f"cp0-top-{width}x{height}.png"))
        for fact in view.modules[0].facts:
            expect(page.locator(f'[data-fact-id="{fact.fact_id}"]')).to_have_text(fact.text or "")
        source = page.locator('[data-fact-id="T6.filing.evidence_0"]')
        source.focus()
        page.keyboard.press("Enter")
        inspector = page.get_by_role("complementary", name="Evidence inspector")
        expect(inspector).to_contain_text("line:1")
        expect(inspector).to_contain_text(pack.sources[0].sha256 or "")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(evidence / f"cp0-{width}x{height}.png"), full_page=True)
        page.evaluate("document.body.style.zoom = '1.25'")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.goto(accepted_path.as_uri() + "#evidence")
        page.locator('[data-source-id="filing"]').click()
        expect(inspector).to_contain_text("utf8-lines/1")
        expect(inspector).to_contain_text("document: retained")
        assert not errors
        assert not [url for url in requests if url.startswith(("http:", "https:"))]
        context.tracing.stop(path=str(evidence / "trace.zip"))
        browser.close()
    (evidence / "browser-checks.json").write_text(
        json.dumps(
            {
                "viewport": [width, height],
                "all_cp0_fact_fields": "passed",
                "keyboard": "passed",
                "offline": True,
                "errors": errors,
                "network_requests": requests,
                "charts": "not applicable: source-readiness registers are textual",
                "zoom": "CSS 125%; native browser zoom not qualified",
            },
            indent=2,
        )
    )
    assert ReadinessReview.model_validate_json((evidence / "review.json").read_bytes()) == review


def test_a_figure_bearing_claim_settles_rejected_instead_of_raising(tmp_path: Path) -> None:
    pack, review = readiness_fixture()
    claim = review.analysis[0].model_copy(update={"text": "Leverage reached 5.2x in FY2025"})
    target = tmp_path / "rejected"
    path = deliver_cp0(pack, review.model_copy(update={"analysis": (claim,)}), target)
    assert path == target / "candidate.html" and path.is_file()
    receipt = json.loads((target / "complete.json").read_bytes())
    assert receipt["status"] == "rejected" and receipt["structural_validation"] == "failed"
    assert not (target / "accepted.html").exists() and not (target / "accepted-view.json").exists()
    rejected = json.loads((target / "rejected.json").read_bytes())
    assert rejected["status"] == "rejected" and not rejected["claims"]
    assert any("Bare figure: 5.2x" in text for text in rejected["limitations"])
    view = View.model_validate_json((target / "candidate-view.json").read_bytes())
    assert view.modules[0].status == "rejected" and not view.modules[0].claims
    for name, digest in receipt["files"].items():
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == digest
