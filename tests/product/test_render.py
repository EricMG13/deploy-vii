import json
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from deploy_vii.contracts import Citation, Fact, ModuleView, Run, Source, Span, View
from deploy_vii.render import display, empty_view, render


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
    assert all(
        item["status"] == "unrun"
        for item in json.loads((output / "view.json").read_text())["modules"]
    )
    with pytest.raises(FileExistsError):
        main()
