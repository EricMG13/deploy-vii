import json
import os
import re
import sys
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect, sync_playwright

from deploy_vii.contracts import Run, View
from deploy_vii.cp1_render import refused_view
from deploy_vii.display import format_value
from deploy_vii.render import empty_view, render
from deploy_vii.report_view import (
    AbsentColumn,
    Block,
    CallItem,
    Cell,
    ChartSpec,
    ColumnGroup,
    Line,
    Passport,
    PassportField,
    ReportIndex,
    ReportView,
    Row,
    TextRun,
    build,
    pathways,
)
from tests.product.credit_snapshot import (
    CREDIT_SNAPSHOT_MAPS,
    credit_snapshot_fixture,
    credit_snapshot_view,
)
from tests.product.evidence import evidence_path
from tests.product.oracle import expected_display, parity_record
from tests.product.png import decode, different_fraction, encode
from tests.product.test_charts import mark, twin_for
from tests.product.test_cp1_render import accepted_view
from tests.product.test_render import synthetic_view


@pytest.mark.browser
@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 800), (720, 450)])
def test_offline_shell_parity_keyboard_provenance_and_reflow(
    tmp_path: Path, width: int, height: int
) -> None:
    view = synthetic_view()
    html = tmp_path / "candidate.html"
    html.write_text(render(view), encoding="utf-8")
    evidence = evidence_path("shell", tmp_path)
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
        expect(page.get_by_role("region", name="The call")).to_contain_text("Assessment pending")
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
        # Field parity is computed: every fact on the page against an oracle from the source fact.
        shown = dict(
            page.locator("[data-fact-id]").evaluate_all(
                "nodes => nodes.map(n => [n.dataset.factId, n.textContent])"
            )
        )
        cp1 = next(m for m in view.modules if m.module_id == "CP-1")
        parity = parity_record({f.fact_id: expected_display(f) for f in cp1.facts}, shown)
        assert parity["compared"] == len(cp1.facts) and not parity["mismatches"]
        # Register figures are right-aligned Mono, like Front Page figures.
        cell_style = figure.evaluate(
            "e => { const s = getComputedStyle(e.closest('td')), f = getComputedStyle(e);"
            " return [s.textAlign, f.fontFamily]; }"
        )
        assert cell_style[0] == "right" and "Red Hat Mono" in cell_style[1]
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
                    "field_parity": parity,
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


def _cell(
    text: str, prov: str, ref: str | None, unit_class: str = "amount", state: str = "known"
) -> Cell:
    return Cell(
        text=text,
        prov=prov,  # type: ignore[arg-type]
        ref_id=None if prov == "gap" else ref,
        gap_ref=ref if prov == "gap" else None,
        unit_class=unit_class,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
    )


def front_report(
    view: View, call_withheld: Literal["outside_pathway", "blocked"] | None = None
) -> ReportView:
    """Every renderer branch on a synthetic Front Page: all six block states, all four kinds."""
    pathway = next(item for item in pathways() if item.id == view.run.pathway)
    amount = format_value(Decimal("11648"), "amount", "known")
    leverage = format_value(Decimal("3.29"), "multiple", "known")
    gap = format_value(None, "amount", "gap", gap_id="G1")
    rows = (
        Row(
            row_id="rcf",
            label="Revolver",
            cells=(
                _cell(amount, "synthetic", "S1"),
                _cell(leverage, "calculated", "K1", "multiple"),
            ),
        ),
        Row(
            row_id="tla",
            label="Term loan A",
            cells=(
                _cell(gap, "gap", "G1", state="gap"),
                _cell(leverage, "calculated", "K1", "multiple"),
            ),
        ),
    )
    marks = (
        mark("Total", "FY2024", None, "G1"),
        mark("Total", "FY2025", "135", "S1"),
        mark("Total", "LTM", "150", "S1"),
        mark("Net", "FY2024", "80", "S1"),
        mark("Net", "FY2025", "90", "S1"),
        mark("Net", "LTM", "95", "S1"),
    )
    blocks = {
        "key-findings": Block(
            block_id="key-findings",
            title="Key findings",
            owner="CP-2",
            state="populated",
            kind="prose",
            tags=("Synthetic",),
            lines=(
                Line(
                    runs=(
                        TextRun(text="Leverage is", kind="text"),
                        TextRun(text=leverage, kind="fig", ref_id="K1"),
                        TextRun(text="after the amendment.", kind="pen"),
                        TextRun(text=gap, kind="gap", ref_id="G1"),
                    )
                ),
            ),
        ),
        "company-operating-model": Block(
            block_id="company-operating-model",
            title="Company and operating model",
            owner="CP-1A",
            state="populated",
            kind="keyvalue",
            rows=(Row(row_id="seg", label="Segments", cells=(_cell(amount, "synthetic", "S1"),)),),
            full_analysis_route="CP-1A",
        ),
        "model-chart-strip": Block(
            block_id="model-chart-strip",
            title="Model chart strip",
            owner="MODEL",
            fig_id="S.1",
            state="populated",
            kind="chart",
            chart=ChartSpec(
                kind="line",
                series=("Total", "Net"),
                table_twin=twin_for(marks),
                marks=marks,
                unit="US$ m",
            ),
        ),
        "capital-structure": Block(
            block_id="capital-structure",
            title="Capital structure",
            owner="CP-1",
            state="populated",
            kind="dense",
            scale="US$ m",
            columns=("Outstanding", "x EBITDA"),
            rows=rows,
        ),
        "financials-credit-metrics": Block(
            block_id="financials-credit-metrics",
            title="Financials and credit metrics",
            owner="CP-1",
            state="populated",
            kind="period_grid",
            scale="US$ m",
            columns=("FY2024", "FY2025", "LTM", "PF-LTM"),
            rows=(
                Row(
                    row_id="ebitda",
                    label="Adjusted EBITDA",
                    cells=(
                        _cell(amount, "synthetic", "S1"),
                        _cell(amount, "synthetic", "S1"),
                        _cell(amount, "synthetic", "S1"),
                        _cell(gap, "gap", "G1", state="gap"),
                    ),
                ),
            ),
            groups=(
                ColumnGroup(label="Annual", span=2),
                ColumnGroup(label="Base", span=1),
                ColumnGroup(label="PF", span=1),
            ),
            base_column=2,
            absent_columns=(AbsentColumn(column=3, reason="merger debt unstated"),),
        ),
        "strengths-weaknesses": Block(
            block_id="strengths-weaknesses",
            title="Strengths and weaknesses",
            owner="CP-2",
            state="collapsed",
            kind="dense",
            columns=("Outstanding", "x EBITDA"),
            rows=rows[:1],
        ),
        "relative-value": Block(
            block_id="relative-value",
            title="Relative value",
            owner="CP-3",
            state="condition",
            kind="prose",
            note="Not shown: no instrument levels were supplied.",
        ),
        "transaction-summary": Block(
            block_id="transaction-summary",
            title="Transaction summary",
            owner="CP-1A",
            state="blocked",
            kind="dense",
            note="Blocked: the merger debt amount is not stated.",
        ),
        "portfolio-fit": Block(
            block_id="portfolio-fit",
            title="Portfolio fit",
            owner="FIT",
            state="absent",
            kind="prose",
            note="Portfolio Fit has no owner yet.",
        ),
        "what-changed": Block(
            block_id="what-changed",
            title="What changed",
            owner="CP-8",
            state="absent",
            kind="dense",
            note="No prior case was accepted.",
        ),
        "committee-challenge": Block(
            block_id="committee-challenge",
            title="Committee challenge",
            owner="CP-6",
            state="not_in_pathway",
            kind="prose",
            note="Not in this Pathway: CP-6 is not part of Credit Snapshot.",
        ),
    }
    idle = build(empty_view(view.run), pathway, ())
    by_id = {item.block_id: item for item in idle.blocks}
    passports = (
        Passport(
            ref_id="S1",
            kind="synthetic",
            fields=(
                PassportField(name="Source", value="fixture"),
                PassportField(name="Data", value="Synthetic test data"),
            ),
        ),
        Passport(
            ref_id="K1",
            kind="calculated",
            fields=(
                PassportField(name="Calculation", value="leverage"),
                PassportField(name="Formula", value="total debt / adjusted EBITDA"),
            ),
        ),
        Passport(
            ref_id="G1",
            kind="gap",
            fields=(
                PassportField(name="Item", value="Term loan A outstanding"),
                PassportField(name="Reason", value="not extracted from the fixture"),
            ),
        ),
    )
    return ReportView(
        pathway=pathway,
        call=idle.call,
        call_withheld=call_withheld,
        blocks=tuple(blocks.get(block_id, by_id[block_id]) for block_id in pathway.blocks),
        passports=passports,
        index=ReportIndex(facts=()),
    )


@pytest.mark.browser
def test_front_page_anatomy_states_passports_and_chart_keyboard(tmp_path: Path) -> None:
    view = synthetic_view()
    report = front_report(view)
    path = tmp_path / "front.html"
    path.write_text(render(view, report), encoding="utf-8")
    errors: list[str] = []
    requests: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, offline=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.goto(path.as_uri())
        ids = page.eval_on_selector_all(".block", "els => els.map(e => e.dataset.blockId)")
        assert ids == [
            b for b in report.pathway.blocks if b != "what-changed"
        ]  # hidden: empty table
        states = page.eval_on_selector_all(".block", "els => els.map(e => e.dataset.state)")
        assert set(states) == {
            "populated",
            "collapsed",
            "condition",
            "not_run",
            "outside",
            "absent",
            "blocked",
        }
        # Call band: 56px minimum and sticky.
        band = page.locator(".call-band")
        assert band.bounding_box()["height"] >= 56  # type: ignore[index]
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(100)
        assert band.bounding_box()["y"] == 0  # type: ignore[index]
        page.evaluate("window.scrollTo(0, 0)")
        # Block states carry words, never colour alone.
        expect(page.locator("#block-transaction-summary")).to_contain_text("Blocked")
        expect(page.locator("#block-portfolio-fit")).to_contain_text("Absent")
        expect(page.locator("#block-company-profile")).to_contain_text("Not run")
        expect(page.locator("#block-relative-value")).to_contain_text("Condition")
        expect(page.locator("#block-committee-challenge")).to_contain_text("Not in this Pathway")
        assert page.locator("#body-strengths-weaknesses").is_hidden()
        # Figures are right-aligned Mono with the provenance glyph before them.
        cell = page.locator("#block-capital-structure td.fig-cell").first
        style = cell.evaluate(
            "e => { const s = getComputedStyle(e); return [s.textAlign, s.fontFamily]; }"
        )
        assert style[0] == "right" and "Red Hat Mono" in style[1]
        assert cell.locator("svg.pg").count() == 1
        # A synthetic passport carries the TEST DATA banner; a gap shows its reason.
        page.locator("#block-capital-structure button.fig").first.click()
        inspector = page.get_by_role("complementary", name="Evidence inspector")
        expect(inspector.locator(".passport.synthetic")).to_contain_text("TEST DATA")
        assert page.evaluate("document.activeElement.id") == "inspector-content"
        page.keyboard.press("Escape")
        assert page.evaluate("document.activeElement.dataset.ref") == "S1"
        gap = page.locator("#block-capital-structure button.gap-fig")
        assert gap.get_attribute("title") == "not extracted from the fixture"
        gap.click()
        expect(inspector.locator(".passport.gap")).to_contain_text("∅ G1")
        page.get_by_role("tab", name="Table").click()
        expect(inspector).to_contain_text("Term loan A")
        # Chart: marks equal data points, arrows move between them, Enter opens the passport.
        marks = page.locator("#block-model-chart-strip g.mark")
        assert marks.count() == 6
        marks.nth(1).focus()
        page.keyboard.press("ArrowRight")
        label = page.evaluate("document.activeElement.getAttribute('aria-label')")
        assert label.startswith("Total, LTM: 150")
        page.keyboard.press("Enter")
        expect(inspector.locator(".passport.synthetic")).to_be_visible()
        page.keyboard.press("Escape")
        assert page.evaluate("document.activeElement.classList.contains('mark')")
        # Table twin is beside the chart and holds the same texts.
        page.get_by_role("button", name="Table", exact=True).click()
        twin = page.locator("#block-model-chart-strip .chart-twin")
        expect(twin).to_be_visible()
        chart = report.blocks[2].chart
        assert chart is not None
        for item in chart.marks:
            expect(twin).to_contain_text(item.text)
        # Search reaches figures and references; choosing a figure scrolls to its block.
        page.get_by_label("Filter modules").fill("Financials and credit")
        page.get_by_role("button", name="Figure: CP-1 Financials and credit metrics").click()
        assert page.evaluate(
            "(() => { const r = document.getElementById('block-financials-credit-metrics')"
            ".getBoundingClientRect(); return r.top >= 0 && r.top < window.innerHeight; })()"
        )
        page.get_by_label("Filter modules").fill("leverage")
        page.get_by_role("button", name="Reference: K1 leverage").click()
        expect(inspector.locator(".passport.calculated")).to_contain_text("total debt")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not [url for url in requests if url.startswith(("http:", "https:"))]
        assert not errors
        browser.close()


@pytest.mark.browser
def test_earnings_update_navigator_footer_shows_the_word_and_rail_edge(tmp_path: Path) -> None:
    run = Run(
        run_id="earnings",
        issuer_id="test",
        issuer_name="Synthetic issuer",
        as_of=synthetic_view().run.as_of,
        case_kind="synthetic",
        pathway="earnings_update",
    )
    path = tmp_path / "earnings.html"
    html = render(empty_view(run))
    assert "Not in this Pathway" in html and "not_in_pathway" not in html
    path.write_text(html, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, offline=True)
        page.goto(path.as_uri())
        footer = page.locator("#nav-foot")
        expect(footer).to_contain_text("Not in this Pathway")
        expect(footer).to_contain_text("Not run")
        expect(page.locator("#nav-pathway")).to_have_text("Earnings Update")
        # Rail: six destinations and an active edge on the current one.
        assert page.locator("[data-dest]").count() == 6
        current = page.locator("[data-dest][aria-current=page]")
        assert current.get_attribute("aria-label") == "Front Page"
        assert current.evaluate("e => getComputedStyle(e).borderLeftWidth") == "2px"
        # The search box border is --rb-ink-2.
        box = page.locator(".search-box")
        assert box.evaluate("e => getComputedStyle(e).borderTopColor") == "rgb(74, 80, 104)"
        # "/" focuses the search, which filters the module rows.
        page.keyboard.press("/")
        assert page.evaluate("document.activeElement.id") == "module-filter"
        page.keyboard.type("CP-1B")
        expect(page.locator(".module-link")).to_have_count(1)
        browser.close()


@pytest.mark.browser
def test_period_grid_and_hidden_empty_table_block(tmp_path: Path) -> None:
    view = synthetic_view()
    path = tmp_path / "grid.html"
    path.write_text(render(view, front_report(view)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, offline=True)
        page.goto(path.as_uri())
        grid = page.locator("#block-financials-credit-metrics table.period-grid")
        assert grid.locator("thead th.group").evaluate_all(
            "els => els.map(e => e.textContent)"
        ) == [
            "Annual",
            "Base",
            "PF",
        ]
        spans = grid.locator("thead th.group").evaluate_all("els => els.map(e => e.colSpan)")
        assert spans == [2, 1, 1]
        tint = grid.locator("td.base").evaluate("e => getComputedStyle(e).backgroundColor")
        assert tint == "rgb(231, 236, 255)"  # --rb-select
        assert grid.locator("th.fig-col.base").inner_text() == "LTM"
        absent = grid.locator("td.absent")
        assert absent.get_attribute("title") == "merger debt unstated"
        assert absent.evaluate("e => getComputedStyle(e).color") == "rgb(154, 160, 180)"
        expect(grid.locator("th.absent .sr-only")).to_contain_text("absent: merger debt unstated")
        # Under a group row the row-label heading is spoken, not an empty column heading.
        corner = grid.locator("thead tr").nth(1).locator("th").first
        assert corner.get_attribute("scope") == "col"
        assert corner.locator(".sr-only").text_content() == "US$ m"
        assert corner.locator(".sr-only").bounding_box()["width"] <= 1  # type: ignore[index]
        # A table block with nothing to show is hidden on the Front Page, listed under Limitations.
        assert page.locator("#block-what-changed").count() == 0
        assert page.locator("#block-portfolio-fit").count() == 1  # prose absent keeps its line
        assert "What changed" not in page.locator("#outline").inner_text()
        page.goto(path.as_uri() + "#limitations")
        expect(
            page.get_by_text("What changed (Absent): No prior case was accepted.")
        ).to_be_visible()
        browser.close()


@pytest.mark.browser
@pytest.mark.parametrize(
    ("withheld", "state", "word"),
    [
        (None, "populated", None),
        ("outside_pathway", "outside", "Not in this Pathway"),
        ("blocked", "blocked", "Blocked"),
    ],
)
def test_call_band_states(
    tmp_path: Path, withheld: str | None, state: str, word: str | None
) -> None:
    view = synthetic_view()
    report = front_report(view, withheld)  # type: ignore[arg-type]
    if withheld is None:
        items = (
            CallItem(kind="scale", label="Valuation", value_text="Modest", meter=2),
            CallItem(kind="fact", label="Main risk", value_text="Merger debt unknown"),
        )
        report = ReportView(
            pathway=report.pathway,
            call=items,
            blocks=report.blocks,
            passports=report.passports,
            index=report.index,
        )
    html = render(view, report)
    assert "not_in_pathway" not in html
    path = tmp_path / "call.html"
    path.write_text(html, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, offline=True)
        page.goto(path.as_uri())
        band = page.get_by_role("region", name="The call")
        assert band.get_attribute("data-call-state") == state
        if word is None:
            expect(band).to_contain_text("Merger debt unknown")
            assert band.locator(".tile").inner_text() == "2"
        else:
            expect(band.locator(".call-note .chip")).to_have_text(word)
            expect(band).to_contain_text("Assessment pending")
        assert band.bounding_box()["height"] >= 56  # type: ignore[index]
        browser.close()


def _tampered(html: str, svg: str) -> str:
    match = re.search(r'(<script id="report-data" type="application/json">)(.*?)(</script>)', html)
    assert match
    payload = json.loads(match.group(2))
    chart_block = next(b for b in payload["report"]["blocks"] if b["chart"])
    chart_block["chart"]["svg"] = svg
    data = json.dumps(payload, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    return html[: match.start(2)] + data + html[match.end(2) :]


SVG_NS = "http://www.w3.org/2000/svg"


@pytest.mark.browser
@pytest.mark.parametrize(
    "svg",
    [
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 10 10"><script>window.injected=true</script></svg>',
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 10 10"><foreignObject><p xmlns="http://www.w3.org/1999/xhtml">x</p></foreignObject></svg>',
    ],
)
def test_chart_svg_with_other_elements_is_refused(tmp_path: Path, svg: str) -> None:
    view = synthetic_view()
    path = tmp_path / "refused.html"
    path.write_text(_tampered(render(view, front_report(view)), svg), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, offline=True)
        page.goto(path.as_uri())
        host = page.locator("#block-model-chart-strip .chart-host")
        expect(host.locator(".chart-refused")).to_contain_text("could not be drawn")
        assert host.locator("svg, script, foreignObject").count() == 0
        assert not page.evaluate("Boolean(window.injected)")
        browser.close()


@pytest.mark.browser
def test_chart_svg_event_and_link_attributes_are_stripped(tmp_path: Path) -> None:
    view = synthetic_view()
    svg = (
        f'<svg xmlns="{SVG_NS}" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10"'
        ' onload="window.injected=true" style="fill:red">'
        '<rect width="5" height="5" onclick="window.injected=true" href="javascript:1"'
        ' xlink:href="javascript:1" style="fill:red" class="s1"/></svg>'
    )
    path = tmp_path / "stripped.html"
    path.write_text(_tampered(render(view, front_report(view)), svg), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, offline=True)
        page.goto(path.as_uri())
        host = page.locator("#block-model-chart-strip .chart-host")
        assert host.locator("svg").count() == 1
        attrs = host.evaluate(
            "e => Array.from(e.querySelectorAll('*')).flatMap(n => Array.from(n.attributes)"
            ".map(a => a.name.toLowerCase()))"
        )
        assert not [a for a in attrs if a.startswith("on") or a in {"href", "xlink:href", "style"}]
        host.locator("rect").dispatch_event("click")
        assert not page.evaluate("Boolean(window.injected)")
        browser.close()


# --- 3.9 Credit Snapshot Front Page acceptance ----------------------------------------------------
# The page under test is the SYNTHETIC fixture of ``credit_snapshot.py`` built by
# ``report_view.build``; every figure on it is invented and labelled so.

REFERENCE = (
    Path(__file__).resolve().parents[2] / "design/reference/rbot-fp-01-credit-snapshot.dc.html"
)
BASELINES = Path(__file__).parent / "baselines" / sys.platform
# A baseline matches when at most this fraction of pixels differs by more than the channel
# tolerance (anti-aliasing noise); a moved or restyled block moves far more than that.
PIXEL_TOLERANCE = 0.005
CHANNEL_TOLERANCE = 24
NETWORK_SCHEMES = ("http:", "https:", "ws:", "wss:", "ftp:")


class _ReferenceMarkup(HTMLParser):
    """Block heads (the first text of each section header) and figure captions of FP 01."""

    def __init__(self) -> None:
        super().__init__()
        self.heads: list[str] = []
        self.captions: list[tuple[str, ...]] = []
        self._in_header = self._want_head = self._in_caption = False
        self._caption: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "header":
            self._in_header = self._want_head = True
        elif tag == "figcaption":
            self._in_caption, self._caption = True, []

    def handle_endtag(self, tag: str) -> None:
        if tag == "header":
            self._in_header = False
        elif tag == "figcaption":
            self._in_caption = False
            self.captions.append(tuple(self._caption))

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_header and self._want_head:
            self.heads.append(text)
            self._want_head = False
        if self._in_caption:
            self._caption.append(text)


def reference_structure() -> dict[str, Any]:
    """Block order, heads, states, chart kinds and state words, read from the reference's markup
    and data with ``html.parser`` and regular expressions (never from our own renderer)."""
    text = REFERENCE.read_text(encoding="utf-8")
    markup = _ReferenceMarkup()
    markup.feed(text)
    collapsed = re.search(r"collapsedBlocks: \[(\{.*?)\],\n", text, re.S)
    assert collapsed, "the reference lists no collapsed blocks"
    entries = re.split(r"\}, \{", collapsed.group(1))
    blocks = [(head, "populated") for head in markup.heads] + [
        (
            re.search(r"title: '([^']+)'", entry).group(1),  # type: ignore[union-attr]
            "condition" if "skipped: true" in entry else "collapsed",
        )
        for entry in entries
    ]
    slots = re.findall(r"\{\{ (ch[A-Za-z]+) \}\}", text)
    built = {
        name: (kind, args)
        for name, kind, args in re.findall(r"(ch[A-Za-z]+): C\.(\w+)\(([^)]*)\)", text)
    }

    def kind_of(slot: str) -> str:
        constructor, args = built[slot]
        if constructor == "columns":
            return "stacked" if "stacked: true" in args else "grouped"
        return {"lineStrip": "line", "debtStack": "debt_stack"}[constructor]

    stack = re.search(
        r"(Debt stack by rank, cumulative multiple)\s*<span[^>]*>Fig\. (S\.\d)</span>", text
    )
    assert stack and len(markup.captions) == 5
    # Figures in page order: S.1 to S.4, then the debt stack under Capital structure, then S.5.
    captions: list[tuple[str | None, str, str | None]] = [
        (a, b, c)
        for a, b, c in markup.captions[:4]  # type: ignore[misc]
    ]
    captions.append((stack.group(2), stack.group(1), None))
    captions.append(markup.captions[4])  # type: ignore[arg-type]
    assert len(slots) == len(captions) == 6
    # The debt stack (S.6) sits under Capital structure, before S.5 in the Financials block.
    assert [cap[0] for cap in captions] == ["S.1", "S.2", "S.3", "S.4", "S.6", "S.5"]
    return {
        "blocks": blocks,
        "charts": [
            {"kind": kind_of(slot), "id": cap[0], "title": cap[1], "unit": cap[2]}
            for slot, cap in zip(slots, captions, strict=True)
        ],
        # Outline entries marked ``na`` carry the word "condition" in the reference.
        "condition_outline": re.findall(r"\{ t: '([^']+)', na: true", text),
        "condition_word": re.search(r"<i[^>]*>(condition)</i>", text).group(1),  # type: ignore[union-attr]
        "rail": re.findall(
            r"label: '([^']+)' \}",
            re.search(
                r"const DEST = (\[.*?\]);", (REFERENCE.parent / "lib/shell.js").read_text(), re.S
            ).group(1),
        ),  # type: ignore[union-attr]
    }


def structure_mismatches(
    blocks: list[Any] | None, charts: list[Any] | None, reference: dict[str, Any]
) -> list[str]:
    """What differs between the rendered block heads/charts and the reference (empty: equal)."""
    found: list[str] = []
    if blocks is not None and [tuple(item) for item in blocks] != reference["blocks"]:
        found.append("block order, heads or states differ")
    if charts is not None and charts != reference["charts"]:
        found.append("chart kinds, figure numbers, titles or units differ")
    return found


def open_front(
    playwright: Playwright,
    path: Path,
    width: int,
    height: int,
    *,
    scale: float = 1,
) -> tuple[Browser, Page, list[str], list[str]]:
    """An offline page on ``path`` with every request and page error recorded."""
    browser = playwright.chromium.launch()
    context = browser.new_context(
        viewport={"width": width, "height": height}, device_scale_factor=scale, offline=True
    )
    page = context.new_page()
    requests: list[str] = []
    errors: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(path.as_uri())
    page.evaluate("document.fonts.ready.then(() => true)")
    return browser, page, requests, errors


def assert_offline(requests: list[str], errors: list[str]) -> None:
    """Zero network requests: nothing but the file itself and embedded data URLs was asked for."""
    assert not [url for url in requests if url.startswith(NETWORK_SCHEMES)], requests
    assert all(url.startswith(("file:", "data:")) for url in requests), requests
    assert not errors


@pytest.fixture(scope="module")
def front_page(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, View, ReportView]:
    view, report = credit_snapshot_fixture()
    path = tmp_path_factory.mktemp("front") / "front.html"
    path.write_text(render(view, report), encoding="utf-8")
    return path, view, report


@pytest.mark.browser
def test_front_page_matches_the_reference_structure(
    front_page: tuple[Path, View, ReportView],
) -> None:
    path, _, report = front_page
    reference = reference_structure()
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        rendered = page.eval_on_selector_all(
            ".block",
            "els => els.map(e => [e.querySelector('h3').textContent, e.dataset.state])",
        )
        # Block order, heads and states.
        assert structure_mismatches(rendered, None, reference) == []
        assert [head for head, _ in rendered] == [block.title for block in report.blocks], (
            "the page renders the report view's blocks in its order"
        )
        # Mark kinds, figure numbers, titles and units, in page order.
        charts = page.eval_on_selector_all(
            "figure.chart-figure",
            """els => els.map(f => {
              const cap = f.querySelector('figcaption'), id = cap.querySelector('.fig-id'),
                    unit = cap.querySelector('.unit'),
                    title = [...cap.children].find(c => !c.matches('.fig-id, .unit, .seg'));
              return {kind: f.dataset.chartKind, id: id && id.textContent,
                      title: title.textContent, unit: unit && unit.textContent};
            })""",
        )
        assert structure_mismatches(None, charts, reference) == []
        # State words: the reference's "condition" outline note appears on the same block.
        outline = page.eval_on_selector_all(
            "#outline button",
            "els => els.map(b => [b.firstChild.textContent.trim(),"
            " (b.querySelector('.state-word') || {}).textContent || null])",
        )
        words = {label: word for label, word in outline if word}
        assert set(words.values()) == {reference["condition_word"]}
        assert [
            any(label.startswith(name) for label in words)
            for name in reference["condition_outline"]
        ] == [True]
        chip = page.locator(".block[data-state=condition] .chip")
        assert chip.text_content().strip().lower() == reference["condition_word"]  # type: ignore[union-attr]
        # Rail destinations, in the reference's order.
        labels = page.eval_on_selector_all("[data-dest]", "els => els.map(e => e.ariaLabel)")
        assert labels == reference["rail"]
        assert_offline(requests, errors)
        browser.close()


def test_the_structure_oracle_notices_a_swapped_head_or_a_dropped_chart() -> None:
    reference = reference_structure()
    blocks = [list(item) for item in reference["blocks"]]
    charts = [dict(item) for item in reference["charts"]]
    assert structure_mismatches(blocks, charts, reference) == []
    swapped = [blocks[1], blocks[0], *blocks[2:]]
    assert structure_mismatches(swapped, charts, reference)
    assert structure_mismatches(blocks, charts[:-1], reference)
    renumbered = [{**item, "id": None} if i == 4 else item for i, item in enumerate(charts)]
    assert structure_mismatches(blocks, renumbered, reference)  # the debt stack is S.6
    assert charts[4]["id"] == "S.6"


@pytest.mark.browser
def test_capital_structure_tabs_switch_by_click_and_arrow_keys(
    front_page: tuple[Path, View, ReportView],
) -> None:
    path, _, _ = front_page
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        tabs = page.locator("#block-capital-structure [role=tab]")
        assert tabs.all_text_contents() == [
            "Capital structure",
            "EBITDA adjustments",
            "Transaction and new debt",
        ]
        panel = page.locator("#panel-capital-structure")
        expect(panel).to_contain_text("Senior notes 2030")
        assert tabs.first.get_attribute("aria-selected") == "true"
        tabs.nth(1).click()
        expect(panel).to_contain_text("Adjusted EBITDA")
        assert panel.locator("th[scope=row]").all_text_contents() == [
            "Reported EBITDA",
            "Add-backs",
            "Adjusted EBITDA",
        ]
        tabs.nth(1).focus()
        page.keyboard.press("ArrowRight")
        assert page.evaluate("document.activeElement.textContent") == "Transaction and new debt"
        expect(panel).to_contain_text(
            "CP-1 reported an empty Transaction and new debt register in this run."
        )
        page.keyboard.press("ArrowRight")  # wraps to the first tab
        assert page.evaluate("document.activeElement.textContent") == "Capital structure"
        expect(panel).to_contain_text("Senior notes 2030")
        # A figure of the selected tab opens its passport with that tab's table twin.
        panel.locator("button.fig").first.click()
        inspector = page.get_by_role("complementary", name="Evidence inspector")
        expect(inspector.locator(".passport")).to_be_visible()
        page.get_by_role("tab", name="Table").click()
        expect(inspector).to_contain_text("Senior notes 2030")
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("zoom", [1.25, 2.0])
def test_front_page_reflows_at_browser_zoom(
    front_page: tuple[Path, View, ReportView], zoom: float
) -> None:
    """125% and 200% zoom of a 1440x900 window: the layout viewport shrinks, pixels scale."""
    path, _, report = front_page
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(
            playwright, path, round(1440 / zoom), round(900 / zoom), scale=zoom
        )
        assert page.evaluate("window.devicePixelRatio") == zoom
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        overflowing = page.evaluate(
            """() => [...document.querySelectorAll('.block, .call-band, table, figure')]
                 .filter(e => e.getBoundingClientRect().right > window.innerWidth + 1
                              && !e.closest('.table-scroll'))
                 .map(e => e.tagName + '.' + e.className)"""
        )
        assert overflowing == []
        assert page.locator(".block").count() == len(report.blocks)
        page.get_by_role("tab", name="EBITDA adjustments").click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_keyboard_path_rail_navigator_figure_inspector_and_chart_mark(
    front_page: tuple[Path, View, ReportView],
) -> None:
    path, _, _ = front_page
    regions = "[aria-label='Report destinations'], #navigator, #workbench, #inspector"
    where = f"""() => {{ const r = document.activeElement.closest("{regions}");
                         return r ? (r.id || 'rail') : null; }}"""
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)

        def tab_until(done: str, limit: int = 400) -> list[tuple[str | None, str]]:
            trail: list[tuple[str | None, str]] = []
            for _ in range(limit):
                page.keyboard.press("Tab")
                trail.append(
                    (
                        page.evaluate(where),
                        page.evaluate(
                            "document.activeElement.ariaLabel || document.activeElement.id"
                            " || document.activeElement.className.baseVal"
                            " || document.activeElement.className"
                        ),
                    )
                )
                if page.evaluate(done):
                    return trail
            raise AssertionError(f"never reached {done}: {trail[-5:]}")

        # 1. Rail, then navigator, then the first figure of the page.
        trail = tab_until("document.activeElement.classList.contains('fig')")
        order = [region for region, _ in trail if region]
        assert [r for i, r in enumerate(order) if i == 0 or r != order[i - 1]] == [
            "rail",
            "navigator",
            "workbench",
        ]
        rail = [name for region, name in trail if region == "rail"]
        assert [n for n in rail if n in reference_structure()["rail"]] == reference_structure()[
            "rail"
        ]
        navigator = [name for region, name in trail if region == "navigator"]
        assert "module-filter" in navigator and any("module-link" in name for name in navigator)
        # 2. A figure opens the inspector with focus inside; Escape returns to the same figure.
        page.evaluate("window.figure = document.activeElement")
        page.keyboard.press("Enter")
        assert page.evaluate("document.activeElement.id") == "inspector-content"
        assert page.evaluate(where) == "inspector"
        expect(page.locator("#inspector .passport")).to_be_visible()
        page.keyboard.press("Escape")
        assert page.evaluate("document.activeElement === window.figure")
        # 3. On to a chart mark: arrows move along the chart, Enter opens it, Escape comes back.
        tab_until("document.activeElement.classList.contains('mark')")
        assert page.evaluate("Boolean(document.activeElement.closest('#block-model-chart-strip'))")
        label = page.evaluate("document.activeElement.getAttribute('aria-label')")
        assert label and ("synthetic" in label or "∅" in label)
        page.evaluate("window.mark = document.activeElement")
        page.keyboard.press("ArrowRight")
        assert page.evaluate("document.activeElement.classList.contains('mark')")
        assert page.evaluate("document.activeElement !== window.mark")
        page.keyboard.press("ArrowLeft")
        assert page.evaluate("document.activeElement === window.mark")
        assert page.evaluate("Boolean(document.activeElement.dataset.ref)")
        page.keyboard.press("Enter")
        assert page.evaluate("document.activeElement.id") == "inspector-content"
        assert page.evaluate(where) == "inspector"
        page.keyboard.press("Escape")
        assert page.evaluate("document.activeElement === window.mark")
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_chart_marks_and_table_twins_agree_with_an_independent_oracle(
    front_page: tuple[Path, View, ReportView],
) -> None:
    path, _, report = front_page
    charts = [
        chart
        for block in report.blocks
        for chart in ([block.chart] if block.chart else []) + [f.chart for f in block.figures]
    ]
    assert len(charts) == 6
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        dom = page.eval_on_selector_all(
            "figure.chart-figure",
            """els => els.map(f => ({
              marks: [...f.querySelectorAll('g.mark')].map(g => g.getAttribute('aria-label')),
              twin: [...f.querySelectorAll('.chart-twin td')].map(td => {
                const fig = td.querySelector('.fig');
                return [...fig.childNodes].filter(n => n.nodeType === 3)
                  .map(n => n.textContent).join('');
              })}))""",
        )
        assert len(dom) == len(charts)
        for shown, chart in zip(dom, charts, strict=True):
            # Expected text from the value alone: ``format_value`` or the gap spelling, never
            # from the spec's own text or the renderer.
            expected = [
                f"∅ {item.ref_id}"
                if item.value is None
                else format_value(item.value, chart.unit_class, "known")
                for item in chart.marks
            ]
            assert shown["twin"] == expected
            assert len(shown["marks"]) == len(chart.marks)
            # Marks are drawn in the chart's own order (a grouped chart goes category by
            # category), so each data point is found by its series and category.
            for item, text in zip(chart.marks, expected, strict=True):
                found = [
                    m
                    for m in shown["marks"]
                    if m.startswith(f"{item.series}, {item.label}: {text}")
                ]
                assert len(found) == 1, (item, shown["marks"])
                assert item.ref_id and item.ref_id in found[0]
        assert_offline(requests, errors)
        browser.close()


DOM_TEXT = """() => {
  document.querySelectorAll('button[aria-expanded=false]').forEach(b => b.click());
  document.querySelectorAll('[role=tab]').forEach(b => b.click());
  const seen = [];
  const walker = document.createTreeWalker(
    document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let n = walker.currentNode; n; n = walker.nextNode()) {
    const hidden = (e) => e.closest('script, style, noscript');
    if (n.nodeType === 3) { if (!hidden(n.parentElement)) seen.push(n.textContent); }
    else if (!hidden(n)) for (const a of n.attributes) seen.push(a.name + '=' + a.value);
  }
  const figures = [...document.querySelectorAll('.fig')].map(f => f.textContent.trim());
  return {text: seen.join('\\n'), figures};
}"""


@pytest.mark.browser
@pytest.mark.parametrize("route", ["", "#CP-1"], ids=["front-page", "register-preview"])
def test_the_page_shows_no_null_spelling_anywhere(
    front_page: tuple[Path, View, ReportView], route: str
) -> None:
    """Text and attribute values of the whole DOM, collapsed blocks and every tab opened."""
    path, _, _ = front_page
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        if route:
            page.goto(path.as_uri() + route)
            # The walk must reach a register, not an empty shell.
            expect(page.locator("[data-table-id]").first).to_be_attached()
            assert page.locator("th[scope=row]").count() > 0
        else:
            assert page.locator(".block").count() > 0
        shown = page.evaluate(DOM_TEXT)
        assert not re.search(r"\b(null|nan)\b", shown["text"], re.IGNORECASE)
        assert not re.search(r"\bnot_in_pathway\b", shown["text"])
        assert not [f for f in shown["figures"] if f.lower() in {"none", "null", "nan"}]
        assert "∅ G" in shown["text"]  # gaps are spelled, not hidden
        assert_offline(requests, errors)
        browser.close()


def test_the_null_walk_detects_what_it_guards_against(tmp_path: Path) -> None:
    """The same walk over a page that does contain a forbidden spelling must find it."""
    page_html = (
        "<!doctype html><body><p title='x null y'>fine</p><button class='fig'>None</button>"
        + "<p>nan</p>" * 1
        + "<script>var s = 'null'</script></body>"
    )
    path = tmp_path / "leaky.html"
    path.write_text(page_html, encoding="utf-8")
    with sync_playwright() as playwright:
        browser, page, _, _ = open_front(playwright, path, 800, 600)
        shown = page.evaluate(DOM_TEXT)
        assert re.search(r"\b(null|nan)\b", shown["text"], re.IGNORECASE)
        assert "None" in shown["figures"]
        assert "var s" not in shown["text"]  # script content is not page text
        browser.close()


@pytest.mark.browser
def test_fp01_layout_key_findings_beside_the_model_and_the_head_anatomy(
    front_page: tuple[Path, View, ReportView],
) -> None:
    path, _, _ = front_page
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)

        def box(selector: str) -> dict[str, float]:
            return page.locator(selector).bounding_box()  # type: ignore[return-value]

        findings, model = box("#block-key-findings"), box("#block-company-operating-model")
        assert abs(findings["y"] - model["y"]) < 2  # side by side
        assert findings["x"] + findings["width"] <= model["x"] + 2
        assert 0.6 < findings["width"] / model["width"] < 0.8  # 5fr against 7fr
        # Key findings: a numbered list under a "pinned" head tag.
        items = page.locator("#block-key-findings ol.numbered li")
        assert items.count() == 3 and items.first.locator(".n").text_content() == "1"
        expect(page.locator("#block-key-findings .block-head .pinned")).to_have_text("pinned")
        # Capital structure: the tabs are the head; the right-hand text carries owner, date, scale.
        head = page.locator("#block-capital-structure .block-head")
        assert head.locator("[role=tab]").count() == 3
        expect(head.locator(".tab-meta")).to_have_text("MODEL · 21 Oct 2026 · US$ m")
        assert head.locator("[role=tab]").first.get_attribute("aria-selected") == "true"
        table = page.locator("#block-capital-structure table").first
        assert table.locator("thead th").all_text_contents()[:1] == ["Facility"]
        assert "subtotal" in table.locator("tr.row-subtotal").first.get_attribute("class")  # type: ignore[operator]
        # The Rec. column is absent: greyed with the producer's own reason.
        rec = table.locator("th.absent")
        expect(rec).to_contain_text("Rec.")
        assert rec.get_attribute("title") == "CP-4C has not run"
        # The debt stack carries its figure number.
        expect(
            page.locator("#block-capital-structure figure[data-fig-id='S.6'] .fig-id")
        ).to_have_text("S.6")
        # Financials: the table 7fr beside S.5 (5fr) with its summary sentence.
        beside = page.locator("#block-financials-credit-metrics .beside")
        grid, figure = (
            beside.locator(".table-scroll").first.bounding_box(),
            beside.locator("figure").bounding_box(),
        )
        assert grid and figure and grid["x"] + grid["width"] <= figure["x"] + 2
        expect(beside.locator(".fig-summary")).to_contain_text("move together")
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_chart_strip_collapsed_summaries_and_strengths_columns(
    front_page: tuple[Path, View, ReportView],
) -> None:
    path, _, _ = front_page
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        strip = page.locator("#block-model-chart-strip")
        expect(strip.locator(".block-head .hint")).to_contain_text("Select a mark")
        expect(strip.locator(".block-head a.full")).to_have_text("Open in Model →")
        legends = strip.locator("figure .legend").all_text_contents()
        assert len(legends) == 4 and any("∅ G" in item for item in legends)  # per-figure gap line
        # A collapsed block shows one line and an Expand link, not only the chevron.
        row = page.locator("#block-relative-value")
        expect(row.locator(".summary")).to_have_text("Secured 2032s preferred.")
        link = row.locator("button.expand-link")
        expect(link).to_have_text("Expand")
        assert page.locator("#body-relative-value").is_hidden()
        link.click()
        expect(link).to_have_text("Collapse")
        assert (
            row.locator(".summary").is_hidden()
            and page.locator("#body-relative-value").is_visible()
        )
        # Strengths and weaknesses: a thesis line, then two columns with tick and cross heads.
        sw = page.locator("#block-strengths-weaknesses")
        expect(sw.locator("p.thesis b")).to_have_text("Thesis.")
        expect(sw.locator("p.thesis")).to_contain_text("∅ G")
        columns = sw.locator(".sw-col")
        assert columns.all_text_contents()[0].startswith("Strengths")
        assert columns.nth(1).text_content().startswith("Weaknesses")  # type: ignore[union-attr]
        assert (
            columns.nth(0).locator("svg").count() >= 1
            and columns.nth(1).locator("svg").count() >= 1
        )
        first, second = columns.nth(0).bounding_box(), columns.nth(1).bounding_box()
        assert first and second and first["x"] + first["width"] <= second["x"] + 2
        assert columns.nth(0).locator(".sw-label").all_text_contents() == ["Scale", "Liquidity"]
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_the_populated_call_band_renders_every_call_item(tmp_path: Path) -> None:
    from tests.product.credit_snapshot import synthetic_call

    view, report = credit_snapshot_fixture()
    assert report.call == synthetic_call()
    items = [item for item in report.call if not item.line]
    lines = [item for item in report.call if item.line]
    assert len(items) == 6 and {i.kind for i in items} == {"scale", "direction"}
    with sync_playwright() as playwright:
        path = tmp_path / "call-populated.html"
        path.write_text(render(view, report), encoding="utf-8")
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        band = page.get_by_role("region", name="The call")
        assert band.get_attribute("data-call-state") == "populated"
        assert band.locator(".call-item").count() == 6
        assert band.locator(".call-item.scale .tile").all_text_contents() == [
            "3",
            "3",
            "4",
            "3",
            "3",
        ]
        assert band.locator(".call-item.direction .tile svg").count() == 1
        assert band.locator(".call-item.scale .meter").count() == 5
        assert band.locator(".call-line .lab").all_text_contents() == [i.label for i in lines]
        expect(band.locator(".call-line").first).to_contain_text("Refinancing")
        expect(band.locator(".tag")).to_have_text("SYNTHETIC")  # the invented call is labelled
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_the_honest_call_band_and_the_na_chart_strip_on_real_build_output(tmp_path: Path) -> None:
    """``build`` over the registers alone: no call, four n/a chart frames above the KPI table."""
    from tests.product.credit_snapshot import CREDIT_SNAPSHOT_MAPS, credit_snapshot_view

    view = credit_snapshot_view()
    pathway = next(item for item in pathways() if item.id == "credit_snapshot")
    path = tmp_path / "built.html"
    path.write_text(render(view, build(view, pathway, CREDIT_SNAPSHOT_MAPS)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        band = page.get_by_role("region", name="The call")
        assert band.get_attribute("data-call-state") == "no-judgement"
        expect(band).to_contain_text("Assessment pending")
        strip = page.locator("#block-model-chart-strip")
        assert strip.locator("figure[data-chart-kind=na]").count() == 4
        assert strip.locator("figure .fig-id").all_text_contents() == ["S.1", "S.2", "S.3", "S.4"]
        expect(strip.locator(".block-note")).to_have_text(
            "Charts need S.1\u2013S.4 series; KPI register shown as a table"
        )
        figures, table = (
            strip.locator(".fig-strip").bounding_box(),
            strip.locator(".block-body > .table-scroll").bounding_box(),
        )
        assert figures and table and figures["y"] + figures["height"] <= table["y"] + 2
        assert strip.locator(".block-head .hint").count() == 0  # no marks to select
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_call_items_share_one_row_and_heads_keep_their_toggle(
    front_page: tuple[Path, View, ReportView],
) -> None:
    path, _, _ = front_page
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        band = page.get_by_role("region", name="The call")
        ys = band.locator(".call-item").evaluate_all(
            "els => els.map(e => e.getBoundingClientRect().y)"
        )
        assert len(ys) == 6 and max(ys) - min(ys) < 1, ys  # one row at 1440
        word = band.locator(".call-item.scale").first
        meter, text = word.locator(".meter").bounding_box(), word.locator(".word").bounding_box()
        assert meter and text and text["y"] + text["height"] <= meter["y"] + 1  # word over meter
        for block_id in ("key-findings", "company-operating-model", "capital-structure"):
            head = page.locator(f"#block-{block_id} .block-head").bounding_box()
            toggle = page.locator(f"#block-{block_id} .block-head button.collapse").bounding_box()
            assert head and toggle
            assert (
                head["y"] <= toggle["y"]
                and toggle["y"] + toggle["height"] <= head["y"] + head["height"] + 1
            )
            # the link and the toggle stay together at the head's end
            assert page.locator(f"#block-{block_id} .head-end button.collapse").count() == 1
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_the_outline_reads_each_block_head_and_the_logo_is_the_brand_image(
    front_page: tuple[Path, View, ReportView],
) -> None:
    path, _, _ = front_page
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        heads = page.eval_on_selector_all(
            ".block", "els => els.map(e => e.querySelector('h3').textContent)"
        )
        outline = page.eval_on_selector_all(
            "#outline button", "els => els.map(b => b.firstChild.textContent.trim())"
        )
        assert outline == ["The call", *heads]
        logo = page.locator("#navigator img.logo-img")
        assert logo.get_attribute("alt") == "State Street Investment Management"
        assert logo.evaluate("e => e.complete && e.naturalWidth > 0")
        assert page.locator(".logo-mark").count() == 0
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
@pytest.mark.parametrize(("width", "height"), [(1440, 900), (1280, 800)])
def test_front_page_screenshot_matches_the_reviewed_baseline(
    front_page: tuple[Path, View, ReportView], width: int, height: int
) -> None:
    """Pixel comparison with the stdlib decoder of ``png.py`` (no screenshot plugin).

    Baselines are per platform (``baselines/<sys.platform>/``): glyph rasterisation differs
    between operating systems, so a baseline is only compared where it was reviewed. A platform
    without one skips, loudly, except darwin, where the baselines were reviewed and a missing
    one fails; ``UPDATE_BASELINES=1`` writes one for review.
    """
    path, _, _ = front_page
    baseline = BASELINES / f"credit-snapshot-{width}x{height}.png"
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, width, height)
        actual = page.screenshot(animations="disabled", caret="hide")
        assert_offline(requests, errors)
        browser.close()
    evidence = (
        Path("artifacts/rendering/front-page") / f"actual-{sys.platform}-{width}x{height}.png"
    )
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(actual)
    if os.environ.get("UPDATE_BASELINES") == "1":
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_bytes(actual)
        pytest.skip(f"baseline written to {baseline}; review it before committing")
    if not baseline.exists():
        message = f"no reviewed baseline for {sys.platform}; UPDATE_BASELINES=1 writes one"
        if sys.platform == "darwin":
            pytest.fail(message)  # the reviewed platform: a missing baseline is a failure
        pytest.skip(message)
    fraction = different_fraction(
        decode(baseline.read_bytes()), decode(actual), channel_tolerance=CHANNEL_TOLERANCE
    )
    assert fraction <= PIXEL_TOLERANCE, (
        f"{fraction:.4%} of pixels differ from {baseline} (tolerance {PIXEL_TOLERANCE:.2%}); "
        f"compare {evidence}"
    )


# --- task 6.5: the Model destination, FP 02 blocks, the accepted route, the shell items ---------


@pytest.fixture(scope="module")
def earnings_page(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """FP 02 over the Credit Snapshot fixture's registers (SYNTHETIC; the Pathway is the run's)."""
    candidate = credit_snapshot_view()
    view = View.model_validate_json(
        candidate.model_copy(
            update={"run": candidate.run.model_copy(update={"pathway": "earnings_update"})}
        ).model_dump_json()
    )
    pathway = next(p for p in pathways() if p.id == "earnings_update")
    path = tmp_path_factory.mktemp("earnings") / "earnings.html"
    path.write_text(render(view, build(view, pathway, CREDIT_SNAPSHOT_MAPS)), encoding="utf-8")
    return path


@pytest.mark.browser
def test_earnings_update_renders_its_ebitda_adjustments_and_metric_strip(
    earnings_page: Path,
) -> None:
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, earnings_page, 1440, 900)
        adjustments = page.locator("#block-ebitda-adjustments")
        expect(adjustments.locator("h3")).to_have_text("EBITDA adjustments")
        expect(adjustments.locator(".block-head")).to_contain_text("MODEL")
        expect(adjustments.locator(".block-head a.full")).to_have_text("Open in Model →")
        assert adjustments.locator("th[scope=row]").all_text_contents() == [
            "Reported EBITDA",
            "Add-backs",
            "Adjusted EBITDA",
        ]
        strip = page.locator("#block-metric-strip")
        expect(strip.locator("h3")).to_have_text("Metric strip")
        expect(strip.locator(".block-head")).to_contain_text("MODEL")
        # FP 02 prints S.1 to S.3; no producer supplies the series, so three honest n/a frames.
        assert strip.locator("figure.chart-figure").count() == 3
        assert strip.locator("figure .fig-id").all_text_contents() == ["S.1", "S.2", "S.3"]
        expect(strip).to_contain_text("Charts need S.1\u2013S.3 series")
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_the_rail_dot_and_limitations_panel_follow_bindings_outside_the_pathway(
    earnings_page: Path, front_page: tuple[Path, View, ReportView]
) -> None:
    credit_path, _, credit = front_page
    assert not credit.unplaced  # FP 01 places T4.17 and T4.10 itself: nothing is outside
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, credit_path, 1440, 900)
        expect(page.locator("[data-dest=limits] .rail-dot")).to_have_count(0)
        assert page.locator("[data-dest=limits]").get_attribute("aria-label") == "Limitations"
        browser.close()
        browser, page, requests, errors = open_front(playwright, earnings_page, 1440, 900)
        # No module has limitations here: only the bindings outside the Pathway light the rail.
        expect(page.locator("[data-dest=limits] .rail-dot")).to_have_count(1)
        assert (
            page.locator("[data-dest=limits]").get_attribute("aria-label")
            == "Limitations · with limitations"
        )
        page.goto(earnings_page.as_uri() + "#limitations")
        outside = page.locator("#view-root section", has_text="Bound outside this Pathway")
        items = outside.locator("li").all_text_contents()
        assert any(
            item.startswith("Capital structure · capital-structure (Absent): CP-1 output bound")
            for item in items
        ), items
        assert any(item.startswith("Key findings · key-findings ") for item in items), items
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_the_model_destination_states_that_the_model_has_not_run(tmp_path: Path) -> None:
    run = Run(
        run_id="covenant",
        issuer_id="test",
        issuer_name="Synthetic issuer",
        as_of=synthetic_view().run.as_of,
        case_kind="synthetic",
        pathway="covenant_refinancing",
    )
    other = tmp_path / "covenant.html"
    other.write_text(render(empty_view(run)), encoding="utf-8")
    path = tmp_path / "accepted.html"
    path.write_text(render(accepted_view()), encoding="utf-8")
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        page.locator("[data-dest=model]").click()  # the rail's Model goes to CP-1's page
        panel = page.locator("#view-root section", has_text="Model not run")
        expect(panel.locator("h2")).to_have_text("Model")
        expect(panel.locator(".chip")).to_have_text("Not run")
        expect(panel).to_contain_text("no calculation JSON has been emitted")
        # No grid is invented: the panel comes first, then CP-1's own register detail.
        assert page.locator("[data-dest][aria-current=page]").get_attribute("aria-label") == "Model"
        assert page.locator("#view-root section h2").first.text_content() == "Model"
        expect(page.locator("[data-table-id]").first).to_be_attached()
        page.goto(other.as_uri() + "#CP-1")
        expect(page.locator("#view-root section", has_text="not part of")).to_contain_text(
            "Model is not part of the Covenant & Refinancing Pathway"
        )
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_the_accepted_envelope_page_shows_the_cp1_blocks_and_no_candidate_label(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accepted.html"
    path.write_text(render(accepted_view()), encoding="utf-8")
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        expect(page.locator(".candidate-label")).to_have_count(0)
        expect(page.locator("#block-financials-credit-metrics")).to_have_attribute(
            "data-state", "populated"
        )
        assert page.locator("#block-capital-structure [role=tab]").all_text_contents() == [
            "Capital structure",
            "EBITDA adjustments",
            "Transaction and new debt",
        ]
        strip = page.locator("#block-model-chart-strip")
        assert strip.locator("figure .fig-id").all_text_contents() == ["S.1", "S.2", "S.3", "S.4"]
        # CP-1 is accepted: its chip says Pass, and the Model panel still states CP-MODEL unrun.
        page.goto(path.as_uri() + "#CP-1")
        expect(page.locator("#view-root > div > .chip")).to_have_text("Pass")
        expect(page.locator("#view-root")).to_contain_text("Model not run")
        assert_offline(requests, errors)
        browser.close()


@pytest.mark.browser
def test_a_refused_envelope_page_shows_every_cp1_block_blocked_with_the_reason(
    tmp_path: Path,
) -> None:
    reason = "Envelope module is not the CP-1 head's settled module"
    base = empty_view(synthetic_view().run, candidate=False)
    path = tmp_path / "refused.html"
    path.write_text(render(refused_view(base, (reason,))), encoding="utf-8")
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(playwright, path, 1440, 900)
        for block_id in ("model-chart-strip", "capital-structure", "financials-credit-metrics"):
            block = page.locator(f"#block-{block_id}")
            expect(block).to_have_attribute("data-state", "blocked")
            expect(block).to_contain_text(reason)
            assert block.locator("td, figure").count() == 0, block_id  # no refused data shown
        page.goto(path.as_uri() + "#limitations")
        expect(page.locator("#view-root")).to_contain_text(f"Canonical envelope refused: {reason}")
        assert_offline(requests, errors)
        browser.close()


# --- the helpers the acceptance relies on, tested on their own ---------------------------------


@pytest.mark.parametrize("channels", [1, 3, 4])
def test_png_decoder_reads_every_filter_type(channels: int) -> None:
    width, height = 5, 5
    rows = [
        bytes((x * 37 + y * 11 + c * 5) % 256 for x in range(width) for c in range(channels))
        for y in range(height)
    ]
    data = encode(width, height, channels, rows, [0, 1, 2, 3, 4])
    image = decode(data)
    assert (image.width, image.height, image.channels) == (width, height, channels)
    assert list(image.rows) == rows


def test_png_decoder_refuses_what_it_cannot_compare() -> None:
    with pytest.raises(ValueError, match="Not a PNG"):
        decode(b"GIF89a")
    data = encode(2, 2, 3, [bytes(6), bytes(6)], [0, 0])
    with pytest.raises(ValueError, match="Truncated"):
        decode(data[:-20])
    interlaced = bytearray(data)
    interlaced[28] = 1  # IHDR interlace byte
    with pytest.raises(ValueError):
        decode(bytes(interlaced))


def test_pixel_difference_fraction_and_tolerance() -> None:
    white = [bytes([255, 255, 255]) * 4 for _ in range(4)]
    base = decode(encode(4, 4, 3, white, [0] * 4))
    near = [bytes([250, 255, 255]) + bytes([255, 255, 255]) * 3, *white[1:]]
    far = [bytes([0, 0, 0]) + bytes([255, 255, 255]) * 3, *white[1:]]
    assert different_fraction(base, base, channel_tolerance=0) == 0
    assert (
        different_fraction(base, decode(encode(4, 4, 3, near, [0] * 4)), channel_tolerance=8) == 0
    )
    assert (
        different_fraction(base, decode(encode(4, 4, 3, far, [0] * 4)), channel_tolerance=8)
        == 1 / 16
    )
    smaller = decode(encode(2, 2, 3, [bytes(6), bytes(6)], [0, 0]))
    assert different_fraction(base, smaller, channel_tolerance=8) == 1.0


def test_parity_record_fails_closed_on_any_difference() -> None:
    expected = {"a": "1", "b": "2"}
    assert parity_record(expected, {"a": "1", "b": "2"}) == {
        "compared": 2,
        "matched": 2,
        "mismatches": [],
    }
    for actual in ({"a": "1", "b": "3"}, {"a": "1"}, {"a": "1", "b": "2", "c": "9"}, {}):
        record = parity_record(expected, actual)
        assert record["mismatches"], actual
        assert record["matched"] < record["compared"]
    # An empty page against an empty oracle compares nothing: callers assert ``compared``.
    assert parity_record({}, {})["compared"] == 0
