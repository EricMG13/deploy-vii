import json
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from deploy_vii.contracts import Run
from deploy_vii.render import empty_view, render
from tests.product.test_render import synthetic_view


@pytest.mark.browser
@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 800), (720, 450)])
def test_offline_shell_parity_keyboard_provenance_and_reflow(
    tmp_path: Path, width: int, height: int
) -> None:
    view = synthetic_view()
    html = tmp_path / "candidate.html"
    html.write_text(render(view), encoding="utf-8")
    evidence = Path("artifacts/rendering/shell") / tmp_path.parent.name / tmp_path.name
    evidence.mkdir(parents=True, exist_ok=False)
    (evidence / "candidate.html").write_bytes(html.read_bytes())
    (evidence / "view.json").write_text(view.model_dump_json(indent=2), encoding="utf-8")
    errors: list[str] = []
    requests: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": height}, offline=True)
        context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.goto(html.as_uri())
        expect(page.get_by_role("heading", name="Assessment pending")).to_be_visible()
        expect(page.get_by_text("CANDIDATE PREVIEW · NOT ACCEPTED")).to_be_visible()
        page.screenshot(path=str(evidence / f"overview-{width}x{height}.png"), full_page=True)
        if width < 1350:
            page.get_by_role("button", name="Toggle module navigator").click()
        page.get_by_label("Filter modules").fill("CP-1")
        link = page.locator(".module-link").filter(has=page.get_by_text("CP-1", exact=True))
        link.focus()
        page.keyboard.press("Enter")
        expect(page.get_by_role("heading", name="CP-1 · Financial foundation")).to_be_visible()
        figure = page.get_by_role("button", name="Inspect Cash and equivalents")
        expect(figure).to_have_text("0.00")
        figure.focus()
        page.keyboard.press("Enter")
        inspector = page.get_by_role("complementary", name="Evidence inspector")
        expect(inspector).to_contain_text("FY2025")
        expect(inspector).to_contain_text("1000000")
        expect(inspector).to_contain_text("line:1")
        expect(inspector).to_contain_text("a" * 64)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not page.evaluate("Boolean(window.injected)")
        assert not [url for url in requests if url.startswith(("https:", "http:"))]
        assert not errors
        page.screenshot(path=str(evidence / f"provenance-{width}x{height}.png"), full_page=True)
        context.tracing.stop(path=str(evidence / "trace.zip"))
        (evidence / "checks.json").write_text(
            json.dumps(
                {
                    "viewport": [width, height],
                    "errors": errors,
                    "requests": requests,
                    "field_parity": "passed",
                    "offline": True,
                    "zoom_note": "720x450 exercises the layout viewport at 200% of 1440x900",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()


@pytest.mark.browser
def test_long_hostile_content_and_css_zoom(tmp_path: Path) -> None:
    hostile = (
        "Long issuer "
        + "unbroken" * 60
        + "</script><script>window.injected=true</script>/*SCRIPT*/"
    )
    run = Run.model_validate_json(
        synthetic_view().run.model_copy(update={"issuer_name": hostile}).model_dump_json()
    )
    path = tmp_path / "hostile.html"
    path.write_text(render(empty_view(run)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, offline=True)
        page.goto(path.as_uri())
        expect(page.get_by_role("heading", name=hostile, exact=True).last).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not page.evaluate("Boolean(window.injected)")
        page.evaluate("document.body.style.zoom = '1.25'")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        browser.close()
