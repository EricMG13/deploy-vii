"""Source-gated interface preview, with separate protocol and rendering evidence."""

import hashlib
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from deploy_vii.contracts import View
from deploy_vii.cp1_workflow import cp1_statement_preview, submit_cp1_step
from deploy_vii.interface_view import write_interface_preview
from tests.product.oracle import expected_by_fact, front_blocks, parity_record
from tests.product.test_financials import book, freeze, observed
from tests.product.test_workflow import cp1_case


def test_interface_preview_cli_retains_snapshot_and_hashes_all_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    store, ticket, submission = cp1_case(tmp_path)
    with pytest.raises(ValueError, match="not available"):
        cp1_statement_preview(store, ticket.ticket_id, tmp_path / "early", include_interface=True)
    submit_cp1_step(store, ticket.ticket_id, "financials", submission.model_dump_json())
    before = store.read().content_hash()
    output = tmp_path / "interface"
    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy-vii",
            "execution",
            "--directory",
            str(store.directory),
            "interface-preview",
            "--ticket",
            ticket.ticket_id,
            "--output",
            str(output),
        ],
    )
    main()
    assert Path(capsys.readouterr().out.strip()) == output / "candidate.html"
    assert store.read().content_hash() == before
    receipt = json.loads((output / "complete.json").read_text())
    assert receipt["execution_binding"]["snapshot_sha256"] == before
    assert receipt["module_acceptance"] == receipt["analytical_qualification"] == "unrun"
    for name, digest in receipt["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    blocks = front_blocks((output / "candidate.html").read_text())
    assert blocks["financials-credit-metrics"]["state"] == "populated"
    assert blocks["financials-credit-metrics"]["tab_label"] == "Income statement"
    assert all(b["owner"] != "Unbound" for b in blocks.values())
    markdown = (output / "tables.md").read_text()
    assert markdown.count("<!-- table-id: cp1.model_period_register -->") == 1
    assert "## Gaps & Conflicts" in markdown and "annual_amortisation" in markdown
    assert "not the canonical Markdown handoff" in markdown
    with pytest.raises(FileExistsError):
        cp1_statement_preview(store, ticket.ticket_id, output, include_interface=True)


@pytest.mark.browser
@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 800)])
def test_interface_fields_offline_and_coupon_inspection(
    tmp_path: Path, width: int, height: int
) -> None:
    value = book()
    loan = value.facilities[0].model_copy(
        update={
            "rate_type": "FIXED",
            "reference_rate": "NONE",
            "fixed_rate": observed("loan.Q2.fixed", "6.500"),
        }
    )
    value = value.model_copy(update={"facilities": (loan,)})
    pack, review = freeze(value)
    path = write_interface_preview(pack, review, value.book_id, tmp_path / "report")
    view = View.model_validate_json((path.parent / "view.json").read_bytes())
    module = next(m for m in view.modules if m.module_id == "CP-1")
    evidence = Path("artifacts/rendering/model-interface") / tmp_path.parent.name / tmp_path.name
    evidence.mkdir(parents=True)
    for name in ("candidate.html", "view.json", "tables.md", "complete.json"):
        (evidence / name).write_bytes((path.parent / name).read_bytes())
    errors, requests = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, offline=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.goto(path.as_uri() + "#CP-1")
        actual = page.locator("[data-fact-id]").evaluate_all(
            "(nodes) => nodes.map(n => [n.dataset.factId, n.textContent])"
        )
        assert len(actual) == len(module.facts)
        oracle = expected_by_fact(view)
        parity = parity_record({f.fact_id: oracle[f.fact_id] for f in module.facts}, dict(actual))
        assert parity["compared"] == len(module.facts) and not parity["mismatches"]
        assert all(text and text != "null" for _, text in actual)
        coupon = next(f for f in module.facts if f.table_id == "T4.18" and f.field == "fixed_rate")
        target = page.locator(f'[data-fact-id="{coupon.fact_id}"]')
        assert (
            target.evaluate(
                "node => { const range = document.createRange(); "
                "range.setStart(node.firstChild, 0); range.setEnd(node.firstChild, 5); "
                "return range.getClientRects().length; }"
            )
            == 1
        ), "The coupon's number must stay whole; only its unit may wrap"
        target.focus()
        page.keyboard.press("Enter")
        inspector = page.get_by_role("complementary", name="Evidence inspector")
        for text in ("6.500", "decimal_percent", "loan.Q2.fixed", "source"):
            expect(inspector).to_contain_text(text)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(evidence / f"interface-{width}x{height}.png"))
        page.evaluate("document.body.style.zoom='1.25'")
        target.scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(evidence / "zoom.png"))
        assert not errors and not [u for u in requests if u.startswith(("http:", "https:"))]
        (evidence / "checks.json").write_text(
            json.dumps(
                {
                    "viewport": [width, height],
                    "field_parity": parity,
                    "errors": errors,
                    "requests": requests,
                    "css_zoom": 1.25,
                    "analytical_qualification": "unrun",
                }
            )
        )
        browser.close()


def test_nested_pack_copy_revalidates_before_preview_reads_identity(tmp_path: Path) -> None:
    value = book()
    pack, review = freeze(value)
    copied = pack.model_copy(update={"run": pack.run.model_dump(mode="json")})
    with pytest.warns(UserWarning, match="Pydantic serializer warnings"):
        path = write_interface_preview(copied, review, value.book_id, tmp_path / "nested")
    assert path.exists()
