"""Deterministic offline Direction C delivery; no model-generated HTML or arithmetic in JS."""

import base64
import json
import re
from importlib.resources import files
from pathlib import Path

from deploy_vii import charts
from deploy_vii.bindings.shipped import SHIPPED_MAPS
from deploy_vii.contracts import Fact, ModuleView, Run, View
from deploy_vii.display import format_date, format_value
from deploy_vii.registry import idle_statuses, modules
from deploy_vii.report_view import (
    ReportView,
    block_state_display,
    build,
    call_state,
    exact_text,
    fact_spelling,
    gap_refs,
    navigator,
    pathways,
    status_display,
)


def empty_view(run: Run, *, candidate: bool = True) -> View:
    """No module has run. Modules the run will not execute are ``not_in_pathway``, not ``unrun``."""
    idle = idle_statuses(run)
    return View(
        run=run,
        mode="candidate" if candidate else "accepted",
        modules=tuple(
            ModuleView(
                module_id=m.module_id,
                title=m.title,
                aliases=m.aliases,
                status=idle[m.module_id],
            )
            for m in modules()
        ),
    )


def display(fact: Fact) -> str:
    if fact.status != "known":
        return (
            fact.status.replace("_", " ").capitalize() + " — " + (fact.limitation or "Not supplied")
        )
    if fact.amount is not None:
        return exact_text(fact.amount)  # One definition of the 100-exponent rule.
    return fact.text or ""


def table_display(fact: Fact, gap_ref: str | None) -> str:
    """The HTML cell spelling (decision 0004 sections 4 and 5), from ``display.format_value``.

    ``gap_ref`` is the fact's report-wide ``G#`` (from the report index); the HTML never
    spells ``null``.
    """
    return fact_spelling(fact, gap_ref)[2]


def markdown_display(fact: Fact) -> str:
    """The r14 Markdown transport spelling, which keeps the literal null token (never HTML)."""
    return "null" if fact.status != "known" else display(fact)


def _legend() -> list[dict[str, str]]:
    """Cell spellings for the inspector key, produced by the formatter (decision 0004 section 5)."""
    shown = (
        (
            "Gap",
            format_value(None, "amount", "gap", gap_id="G8"),
            "Not supplied; reason in its passport.",
        ),
        (
            "Not meaningful",
            format_value(None, "multiple", "not_meaningful", gap_id="G41"),
            "Supplied but the ratio has no sense.",
        ),
        (
            "Blocked cell",
            format_value(None, "amount", "blocked"),
            "A critical cell that could not be filled.",
        ),
        (
            "Not evaluated",
            format_value(None, "amount", "not_evaluated", reason="reason"),
            "The check was not performed.",
        ),
    )
    return [{"name": name, "sample": sample, "rule": rule} for name, sample, rule in shown]


# The internal name never reaches the HTML (decision 0004 section 6): the shell's DOM calls a
# block outside the Pathway "outside", as it does the call band (``call_withheld`` too).
_DOM_BLOCK_STATE = {"not_in_pathway": "outside", "outside_pathway": "outside"}


def _report_payload(report: ReportView) -> dict[str, object]:
    payload = report.model_dump(mode="json")
    for block_payload, block in zip(payload["blocks"], report.blocks, strict=True):
        block_payload["state"] = _DOM_BLOCK_STATE.get(block.state, block.state)
        if block.chart is not None:
            block_payload["chart"]["svg"] = charts.render_svg(
                block.chart, chart_id=block.block_id, title=block.title
            )
        for index, (figure_payload, figure) in enumerate(
            zip(block_payload["figures"], block.figures, strict=True)
        ):
            figure_payload["gaps_note"] = figure.gaps_note
            figure_payload["chart"]["svg"] = charts.render_svg(
                figure.chart, chart_id=f"{block.block_id}-f{index}", title=figure.title
            )
    if report.call_withheld is not None:
        payload["call_withheld"] = _DOM_BLOCK_STATE.get(report.call_withheld, report.call_withheld)
    state, words = call_state(report)
    payload["call_state"] = state
    payload["call_words"] = None if words is None else {"glyph": words[0], "word": words[1]}
    return payload


def render(view: View, report: ReportView | None = None) -> str:
    view = View.model_validate_json(view.model_dump_json())
    if report is None:
        pathway = next(item for item in pathways() if item.id == view.run.pathway)
        report = build(view, pathway, SHIPPED_MAPS)
    if report.pathway.id != view.run.pathway:
        raise ValueError("The report view's Pathway differs from the run's Pathway")
    assets = files("deploy_vii").joinpath("assets")
    font_specs = (
        ("Red Hat Display", "RedHatDisplay-SemiBold.woff2", 600),
        ("Red Hat Display", "RedHatDisplay-Bold.woff2", 700),
        ("Red Hat Text", "RedHatText-Regular.woff2", 400),
        ("Red Hat Text", "RedHatText-Medium.woff2", 500),
        ("Red Hat Text", "RedHatText-SemiBold.woff2", 600),
        ("Red Hat Mono", "RedHatMono-Medium.woff2", 500),
        ("Red Hat Mono", "RedHatMono-SemiBold.woff2", 600),
    )
    font_rules: list[str] = []
    for family, name, weight in font_specs:
        encoded = base64.b64encode(assets.joinpath("fonts", name).read_bytes()).decode()
        font_rules.append(
            f'@font-face{{font-family:"{family}";font-weight:{weight};font-display:swap;'
            f'src:url(data:font/woff2;base64,{encoded}) format("woff2")}}'
        )
    font_css = "\n".join(font_rules)

    payload = view.model_dump(mode="json")
    gap_ids = gap_refs(report.index)
    shown: list[dict[str, object]] = []
    for module_payload, module in zip(payload["modules"], view.modules, strict=True):
        if module.status == "rejected":
            continue  # A rejected attempt is never displayed; it stays in evidence.
        for fact_payload, fact in zip(module_payload["facts"], module.facts, strict=True):
            fact_payload["display"] = display(fact)
            fact_payload["table_display"] = table_display(
                fact, gap_ids.get((module.module_id, fact.fact_id))
            )
        # Status is shown as glyph and word; the internal token never reaches the HTML.
        module_payload["status_glyph"], module_payload["status_word"] = status_display(
            module.status
        )
        del module_payload["status"]
        shown.append(module_payload)
    payload["modules"] = shown
    # Scope counts come from the registry, not from the (rejected-free) navigator.
    payload["responsibilities"] = {
        "modules": len(modules()),
        "alternates": sum(len(item.aliases) for item in modules()),
    }
    payload["rejected_count"] = sum(item.status == "rejected" for item in view.modules)
    payload["run_display"] = {"as_of": format_date(view.run.as_of)}
    payload["nav"] = [row.model_dump(mode="json") for row in navigator(view)]
    payload["report"] = _report_payload(report)
    payload["block_states"] = {
        _DOM_BLOCK_STATE.get(state, state): {"glyph": glyph, "word": word}
        for state, (glyph, word) in block_state_display().items()
    }
    payload["legend"] = _legend()
    data = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    logo = base64.b64encode(
        assets.joinpath("brand", "ssim-logo-stacked-black-trim.png").read_bytes()
    ).decode()
    css = (
        assets.joinpath("tokens.css").read_text()
        + font_css
        + assets.joinpath("app.css").read_text()
    )
    replacements = {
        "STYLES": css,
        "DATA": data,
        "SCRIPT": assets.joinpath("app.js").read_text(),
        "LOGO": f"data:image/png;base64,{logo}",
        "LICENSE": assets.joinpath("fonts", "OFL.txt").read_text().replace("--", "—"),
    }
    return re.sub(
        r"/\*(STYLES|DATA|SCRIPT|LICENSE|LOGO)\*/",
        lambda match: replacements[match.group(1)],
        assets.joinpath("shell.html").read_text(),
    )


def write_preview(run: Run, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    view = empty_view(run)
    (destination / "view.json").write_text(view.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (destination / "candidate.html").write_text(render(view), encoding="utf-8")
    (destination / "accepted.html").write_text(
        render(empty_view(run, candidate=False)), encoding="utf-8"
    )
    return destination / "candidate.html"
