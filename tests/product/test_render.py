import hashlib
import json
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import expect, sync_playwright
from pydantic import ValidationError

from deploy_vii.contracts import Citation, Claim, Fact, ModuleView, Run, Source, Span, View
from deploy_vii.registry import dependencies, modules
from deploy_vii.render import display, empty_view, render
from deploy_vii.report_view import build, pathways, status_word


def synthetic_view() -> View:
    run = Run(
        run_id="synthetic-render",
        issuer_id="test",
        issuer_name="Synthetic issuer",
        as_of=date(2026, 10, 21),
        case_kind="synthetic",
    )
    empty = empty_view(run)
    citation = Citation(
        source_id="fixture", source_sha256="a" * 64, locator="line:1", quote="Cash: 0"
    )
    fact = Fact(
        fact_id="cash",
        label="Cash and equivalents",
        table_id="T4.6",
        row_id="cash",
        amount=Decimal("0.00"),
        unit="currency",
        currency="USD",
        period="FY2025",
        scale=Decimal(1000000),
        citations=(citation,),
    )
    module = ModuleView(
        module_id="CP-1",
        title="Financial foundation",
        aliases=(),
        status="candidate",
        facts=(fact,),
        artifact_sha256="b" * 64,
    )
    return View(
        run=run,
        mode="candidate",
        modules=tuple(
            module if item.module_id == module.module_id else item for item in empty.modules
        ),
        sources=(
            Source(
                source_id="fixture",
                name="Synthetic evidence",
                status="ready",
                sha256="a" * 64,
                spans=(Span(locator="line:1", text="Cash: 0"),),
            ),
        ),
    )


def test_render_preserves_exact_values_and_labels_candidate() -> None:
    view = synthetic_view()
    html = render(view)
    match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html)
    assert match
    payload = json.loads(match.group(1))
    fact = next(m for m in payload["modules"] if m["module_id"] == "CP-1")["facts"][0]
    assert fact["display"] == "0.00"
    assert fact["amount"] == "0.00"
    assert fact["scale"] == "1000000"
    assert fact["citations"][0]["locator"] == "line:1"
    assert payload["mode"] == "candidate"
    assert "https://fonts.googleapis.com" not in html


def test_render_embeds_design_tokens_and_provenanced_fonts_without_local_sources() -> None:
    html = render(synthetic_view())
    assert "--rb-navy: #000533" in html
    assert "local(" not in html
    assert html.index("--rb-navy: #000533") < html.index(".app-shell{")
    fonts = Path(__file__).resolve().parents[2] / "src/deploy_vii/assets/fonts"
    for entry in json.loads((fonts / "provenance.json").read_text()):
        data = (fonts / entry["file"]).read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert html.count("@font-face") == 7


def test_script_closers_and_template_markers_stay_data() -> None:
    hostile = "</script><script>window.injected=true</script>/*SCRIPT*//*LICENSE*/"
    run = Run(
        run_id="safe",
        issuer_id="test",
        issuer_name=hostile,
        as_of=date(2026, 10, 21),
        case_kind="synthetic",
    )
    html = render(empty_view(run))
    assert hostile not in html
    match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html)
    assert match
    assert json.loads(match.group(1))["run"]["issuer_name"] == hostile


def test_candidate_cannot_be_relabelled_as_accepted() -> None:
    with pytest.raises(ValidationError):
        render(synthetic_view().model_copy(update={"mode": "accepted"}))


def test_large_exponent_keeps_exact_scientific_not_giant_fixed_point() -> None:
    fact = Fact(
        fact_id="extreme",
        label="Extreme",
        amount=Decimal("1e1000000"),
        unit="ratio",
        period="synthetic",
    )
    assert display(fact) == "1E+1000000"


def test_missing_and_text_display() -> None:
    assert (
        display(Fact(fact_id="m", label="Missing", status="missing", limitation="Absent"))
        == "Missing — Absent"
    )
    assert display(Fact(fact_id="t", label="Text", text="Exact <text>")) == "Exact <text>"


def test_cli_plan_and_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    monkeypatch.setattr(sys, "argv", ["deploy-vii", "plan", "CP-6"])
    main()
    order = capsys.readouterr().out.splitlines()
    assert order.index("CP-5") < order.index("CP-6")
    run = tmp_path / "run.json"
    run.write_text(synthetic_view().run.model_dump_json(), encoding="utf-8")
    output = tmp_path / "preview"
    monkeypatch.setattr(
        sys, "argv", ["deploy-vii", "preview", "--run", str(run), "--output", str(output)]
    )
    main()
    assert (output / "candidate.html").is_file()
    assert (output / "accepted.html").is_file()
    previewed = {
        item["module_id"]: item["status"]
        for item in json.loads((output / "view.json").read_text())["modules"]
    }
    # Nothing ran: modules in the Pathway are unrun, the rest are outside it.
    assert set(previewed.values()) == {"unrun", "not_in_pathway"}
    assert previewed["CP-6"] == "unrun"
    with pytest.raises(FileExistsError):
        main()


# --- not_in_pathway (decision 0009) --------------------------------------------------------


def _run(**over: object) -> Run:
    base: dict[str, object] = {
        "run_id": "p",
        "issuer_id": "i",
        "issuer_name": "Issuer",
        "as_of": date(2026, 10, 21),
        "case_kind": "synthetic",
    }
    return Run(**{**base, **over})  # type: ignore[arg-type]


def _statuses(run: Run) -> dict[str, str]:
    return {m.module_id: m.status for m in empty_view(run).modules}


def test_not_in_pathway_is_distinct_from_unrun() -> None:
    statuses = _statuses(_run())
    assert set(statuses.values()) == {"unrun", "not_in_pathway"}
    in_scope = {m for m, s in statuses.items() if s == "unrun"}
    # Requested modules and their required producers are unrun; everything else is outside.
    assert in_scope == set(dependencies(_run().requested_modules))
    assert {"CP-0", "CP-1", "CP-1A", "CP-2", "CP-3", "CP-4", "CP-5", "CP-6"} == in_scope
    assert statuses["CP-1B"] == statuses["CP-8"] == statuses["CP-OS"] == "not_in_pathway"
    assert status_word("unrun") != status_word("not_in_pathway")
    assert status_word("not_in_pathway") == ("not_in_pathway", "Not in this Pathway")
    # The same module flips with the Pathway: CP-1B is Earnings Update work, not Credit Snapshot's.
    earnings = _statuses(_run(pathway="earnings_update"))
    assert earnings["CP-1B"] == "unrun"
    assert earnings["CP-2"] == "not_in_pathway"
    # Every registry module is classified exactly once.
    assert list(statuses) == [m.module_id for m in modules()]


def test_required_producers_join_the_pathway_scope() -> None:
    # Portfolio Decision lists CP-2 but not its required producer CP-1A.
    assert "CP-1A" not in _run(pathway="portfolio_decision").requested_modules
    assert _statuses(_run(pathway="portfolio_decision"))["CP-1A"] == "unrun"
    # Aliases resolve to their canonical module.
    assert _statuses(_run(requested_modules=("CP-2C",)))["CP-1A"] == "unrun"


def test_unknown_requested_module_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unknown r14 entry"):
        empty_view(_run(requested_modules=("CP-404",)))


def test_not_in_pathway_module_carries_no_outputs_and_renders() -> None:
    fact = Fact(fact_id="x", label="Test", text="One")
    with pytest.raises(ValidationError):
        ModuleView(
            module_id="CP-8",
            title="t",
            aliases=(),
            status="not_in_pathway",
            artifact_sha256="a" * 64,
            facts=(fact,),
        )
    view = empty_view(_run(), candidate=False)  # accepted mode accepts not_in_pathway
    assert view.mode == "accepted"
    html = render(view)
    assert "Not in this Pathway" in html
    assert "not_in_pathway" not in html


def test_earnings_update_html_shows_status_words_never_the_internal_token() -> None:
    html = render(empty_view(_run(pathway="earnings_update")))
    assert "Not in this Pathway" in html
    assert "Not run" in html
    assert "not_in_pathway" not in html
    payload = _payload(html)
    assert all("status" not in module for module in payload["modules"])
    words = {module["status_word"] for module in payload["modules"]}
    assert words == {"Not run", "Not in this Pathway"}
    rows = {row["module_id"]: row for row in payload["nav"]}
    assert rows["CP-1B"]["in_pathway"] and rows["CP-1B"]["word"] == "Not run"
    assert not rows["CP-2"]["in_pathway"] and rows["CP-2"]["number"] is None
    assert [r["number"] for r in payload["nav"] if r["in_pathway"]] == list(
        range(1, sum(r["in_pathway"] for r in payload["nav"]) + 1)
    )


def _payload(html: str) -> dict[str, Any]:
    match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html)
    assert match
    return json.loads(match.group(1))  # type: ignore[no-any-return]


def test_a_rejected_attempt_is_never_displayed() -> None:
    run = _run()
    view = empty_view(run)
    rejected = ModuleView(
        module_id="CP-1",
        title="Financial foundation",
        aliases=(),
        status="rejected",
        limitations=("Attempt failed validation",),
        artifact_sha256="c" * 64,
    )
    view = view.model_copy(
        update={"modules": tuple(rejected if m.module_id == "CP-1" else m for m in view.modules)}
    )
    payload = _payload(render(view))
    assert "CP-1" not in {m["module_id"] for m in payload["modules"]}
    assert "CP-1" not in {row["module_id"] for row in payload["nav"]}
    assert payload["rejected_count"] == 1
    assert "Attempt failed validation" not in json.dumps(payload["modules"])


def test_report_view_pathway_must_match_the_run() -> None:
    earnings = next(item for item in pathways() if item.id == "earnings_update")
    other = build(empty_view(_run(pathway="earnings_update")), earnings, ())
    with pytest.raises(ValueError, match="Pathway"):
        render(empty_view(_run()), other)


ASSETS = Path(__file__).resolve().parents[2] / "src/deploy_vii/assets"
CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; font-src data:; "
    "img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
)


def test_shell_keeps_its_csp_and_ships_no_network_references() -> None:
    shell = (ASSETS / "shell.html").read_text()
    assert f'<meta http-equiv="Content-Security-Policy" content="{CSP}">' in shell
    assets = shell + (ASSETS / "app.js").read_text() + (ASSETS / "app.css").read_text()
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", assets)
    assert "innerHTML" not in assets and "outerHTML" not in assets
    assert "insertAdjacentHTML" not in assets


def test_app_css_uses_tokens_only_and_embedded_weights() -> None:
    css = (ASSETS / "app.css").read_text()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "colour literal in app.css"
    assert not re.search(r"rgba?\(|hsla?\(", css)
    for rule in css.split("}"):
        weights = {int(w) for w in re.findall(r"font-weight:(\d+)", rule)}
        assert weights <= {400, 500, 600, 700}
        if 700 in weights:
            # Only Display embeds a bold weight (Text and Mono stop at 600).
            assert "--rb-font-display" in rule, rule
    # DS-02 semibold body weight is 600 and the search input border is --rb-ink-2.
    assert re.search(r"\.search-box\{[^}]*border:1px solid var\(--rb-ink-2\)", css)
    assert re.search(
        r"\.rail-btn\[aria-current=page\]\{[^}]*border-left-color:var\(--rb-on-navy\)", css
    )


def test_scope_counts_come_from_the_registry_even_with_rejected_modules() -> None:
    view = empty_view(_run())
    withdrawn = ModuleView(
        module_id="CP-1",
        title="Financial foundation",
        aliases=(),
        status="rejected",
        limitations=("x",),
        artifact_sha256="c" * 64,
    )
    swapped = tuple(withdrawn if m.module_id == "CP-1" else m for m in view.modules)
    counts = _payload(render(view.model_copy(update={"modules": swapped})))["responsibilities"]
    assert counts["modules"] == len(modules()) == len({m.module_id for m in modules()})
    assert counts["alternates"] == sum(len(m.aliases) for m in modules())
    assert counts == _payload(render(view))["responsibilities"]


def claim_view(text: str | None = None) -> View:
    """The synthetic view with a CP-1 claim that cites a figure and names a gap."""
    view = synthetic_view()
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")
    debt = Fact(
        fact_id="debt",
        label="Merger debt",
        table_id="T4.6",
        row_id="debt",
        status="missing",
        limitation="No stated amount",
    )
    claim = Claim(
        claim_id="c1",
        text=text or "Cash was {cash|US$} for FY2025 per the 10-K;\nmerger debt is open [debt].",
        citations=cp1.facts[0].citations,
    )
    module = cp1.model_copy(update={"facts": (*cp1.facts, debt), "claims": (claim,)})
    return View.model_validate_json(
        view.model_copy(
            update={"modules": tuple(module if m.module_id == "CP-1" else m for m in view.modules)}
        ).model_dump_json()
    )


PLAIN = "Cash was 0 US$ for FY2025 per the 10-K;\nmerger debt is open ∅ G1."


def test_claim_runs_reach_the_data_island_resolved() -> None:
    modules_payload = _payload(render(claim_view()))["modules"]
    claim = next(m for m in modules_payload if m["module_id"] == "CP-1")["claims"][0]
    literal = {"ref_id": None, "prov": "none", "kind": "text"}
    assert claim["runs"] == [
        {**literal, "text": "Cash was "},
        {"text": "0 US$", "kind": "fig", "ref_id": "S1", "prov": "synthetic"},
        {**literal, "text": " for FY2025 per the 10-K;\nmerger debt is open "},
        {"text": "∅ G1", "kind": "gap", "ref_id": "G1", "prov": "gap"},
        {**literal, "text": "."},
    ]
    assert claim["plain"] == PLAIN
    assert not any(c in run["text"] for run in claim["runs"] for c in "{}[]")


def test_a_claim_that_does_not_resolve_cannot_render() -> None:
    with pytest.raises(ValueError, match="Bare figure: 12%"):
        render(claim_view("Cash rose 12% to {cash|US$}."))
    with pytest.raises(ValueError, match="Unresolved reference: elsewhere"):
        render(claim_view("Cash is held [elsewhere]."))


@pytest.mark.browser
def test_claim_runs_render_through_runs_renderer(tmp_path: Path) -> None:
    html = tmp_path / "candidate.html"
    html.write_text(render(claim_view()), encoding="utf-8")
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800}, offline=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(html.as_uri() + "#CP-1")
        text = page.locator('[data-claim-id="c1"] p')
        shown = text.evaluate(
            "n => { const c = n.cloneNode(true);"
            " c.querySelectorAll('svg').forEach(s => s.remove()); return c.textContent; }"
        )
        assert shown == PLAIN
        gap = text.locator("button.gap-fig")
        expect(gap).to_have_text("∅ G1")
        expect(gap).to_have_attribute("data-ref", "G1")
        expect(gap).to_have_attribute("title", "No stated amount")
        figure = text.locator('button.fig[data-ref="S1"]')
        expect(figure).to_have_text("synthetic0 US$")  # the glyph's title, then the figure
        inspector = page.get_by_role("complementary", name="Evidence inspector")
        gap.click()
        expect(inspector).to_contain_text("No stated amount")
        page.locator('[data-claim-id="c1"]').get_by_role(
            "button", name="Inspect supporting evidence"
        ).click()
        expect(inspector.locator(".passport-title")).to_have_text(PLAIN)
        assert not errors
        browser.close()
