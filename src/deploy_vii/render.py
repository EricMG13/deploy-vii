"""Deterministic offline Direction C delivery; no model-generated HTML or arithmetic in JS."""

import base64
import json
import re
from importlib.resources import files
from pathlib import Path

from deploy_vii.contracts import Fact, ModuleView, Run, View
from deploy_vii.registry import modules


def empty_view(run: Run, *, candidate: bool = True) -> View:
    return View(
        run=run,
        mode="candidate" if candidate else "accepted",
        modules=tuple(
            ModuleView(module_id=m.module_id, title=m.title, aliases=m.aliases) for m in modules()
        ),
    )


def display(fact: Fact) -> str:
    if fact.status != "known":
        return (
            fact.status.replace("_", " ").capitalize() + " — " + (fact.limitation or "Not supplied")
        )
    if fact.amount is not None:
        if abs(fact.amount.adjusted()) > 100:
            return str(fact.amount)  # Exact scientific form avoids unbounded fixed-point expansion.
        return format(fact.amount, "f")
    return fact.text or ""


def table_display(fact: Fact) -> str:
    """Canonical null spelling; status and reason stay in the inspector/gap register."""
    return "null" if fact.status != "known" else display(fact)


def render(view: View) -> str:
    view = View.model_validate_json(view.model_dump_json())
    assets = files("deploy_vii").joinpath("assets")
    font_specs = (
        ("Red Hat Display", "RedHatDisplay-Regular.woff2", 400),
        ("Red Hat Display", "RedHatDisplay-Bold.woff2", 700),
        ("Red Hat Text", "RedHatText-Regular.woff2", 400),
        ("Red Hat Text", "RedHatText-Medium.woff2", 500),
        ("Red Hat Mono", "RedHatMono-Regular.woff2", 400),
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
    for module_payload, module in zip(payload["modules"], view.modules, strict=True):
        for fact_payload, fact in zip(module_payload["facts"], module.facts, strict=True):
            fact_payload["display"] = display(fact)
            fact_payload["table_display"] = table_display(fact)
    data = json.dumps(payload, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    css = (
        assets.joinpath("tokens.css").read_text()
        + font_css
        + assets.joinpath("app.css").read_text()
    )
    replacements = {
        "STYLES": css,
        "DATA": data,
        "SCRIPT": assets.joinpath("app.js").read_text(),
        "LICENSE": assets.joinpath("fonts", "OFL.txt").read_text().replace("--", "—"),
    }
    return re.sub(
        r"/\*(STYLES|DATA|SCRIPT|LICENSE)\*/",
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
