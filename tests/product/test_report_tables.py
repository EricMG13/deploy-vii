"""Real source-statement projections with synthetic evidence, never full CP-1 acceptance."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from pydantic import ValidationError

from deploy_vii.contracts import Fact, Module, ReportTable, TableColumn, TableRow
from deploy_vii.cp1_workflow import cp1_statement_preview, submit_cp1_step
from deploy_vii.financial_contracts import FinancialReview
from deploy_vii.preparation import PreparedPack
from deploy_vii.render import display, render, table_display
from deploy_vii.statement_output import statement_report
from deploy_vii.statement_view import statement_view, write_statement_preview
from deploy_vii.table_markdown import markdown_cell, table_markdown
from tests.product.test_financials import conflict, freeze
from tests.product.test_statements import line, statements
from tests.product.test_workflow import cp1_case


def data() -> tuple[PreparedPack, FinancialReview]:
    value = statements()
    income = line("revenue", "revenue", "100", 1, statement="IS")
    cogs = line("cogs", "cogs", "30", 2, statement="IS").model_copy(
        update={"sign_convention": "outflow_magnitude", "sign_citations": income.value.citations}
    )
    cash = line("cash", "cash_and_equivalents", "20", 1, statement="BS")
    zero = line("zero", "other:zero", "0.00", 2, statement="BS")
    disputed = line("disputed", "other:disputed", None, 3, statement="BS").model_copy(
        update={"value": conflict("disputed.Q2")}
    )
    inapplicable = line("not-applicable", "other:not-applicable", None, 4, statement="BS")
    inapplicable = inapplicable.model_copy(
        update={
            "value": inapplicable.value.model_copy(
                update={"status": "not_applicable", "reason": "This item does not apply"}
            )
        }
    )
    value = value.model_copy(
        update={
            "statement_lines": (
                *value.statement_lines,
                income,
                cogs,
                cash,
                zero,
                disputed,
                inapplicable,
            )
        }
    )
    return freeze(value)


def module() -> Module:
    pack, financial = data()
    view = statement_view(pack, financial, financial.books[0].book_id)
    rendered = next(m for m in view.modules if m.module_id == "CP-1")
    return Module(
        run_id=pack.run.run_id,
        issuer_id=pack.run.issuer_id,
        as_of=pack.run.as_of,
        module_id="CP-1",
        facts=rendered.facts,
        tables=rendered.tables,
    )


def test_source_statement_matrix_is_exact_and_missing_values_never_become_zero() -> None:
    pack, financial = data()
    view = statement_view(pack, financial, financial.books[0].book_id)
    record = statement_report(pack, financial, financial.books[0].book_id)
    projected = next(m for m in view.modules if m.module_id == "CP-1")
    assert view.mode == "candidate" and projected.status == "candidate"
    assert projected.artifact_sha256 == record.content_hash()
    assert [t.table_id for t in projected.tables] == ["T4.4", "T4.5", "T4.6"]
    facts = {(f.table_id, f.row_id, f.field): f for f in projected.facts}
    for source in record.cells:
        fact = facts[source.table_id, source.item_id, source.period_id]
        assert fact.amount == source.normalized_amount
        assert fact.status == source.status
        assert fact.source_amount == source.source_amount
        assert fact.citations == source.citations and fact.scale == Decimal(1000000)
        assert fact.value_class == source.value_class and fact.currency == "USD"
        assert source.period_id in fact.period
    assert table_display(facts["T4.6", "other:zero", "Q2"]) == "0.00"
    assert table_display(facts["T4.6", "other:zero", "Q1"]) == "null"
    assert facts["T4.6", "other:disputed", "Q2"].status == "conflicting"
    assert facts["T4.4", "cogs", "Q2"].amount == -30
    assert facts["T4.4", "cogs", "Q2"].source_amount == 30
    assert facts["T4.4", "cogs", "Q2"].formula == "negative absolute source amount"
    assert len({fid for t in projected.tables for r in t.rows for fid in r.fact_ids}) == len(
        projected.facts
    )
    assert "not delivered" in projected.limitations[0]
    assert all(m.status == "unrun" for m in view.modules if m.module_id != "CP-1")


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_table",
        "duplicate_column",
        "duplicate_row",
        "unknown",
        "short",
        "reused",
        "wrong_row",
        "wrong_field",
        "omitted",
        "duplicate_fact",
        "duplicate_interface",
    ],
)
def test_layout_corruption_rejected_before_render_or_markdown(mutation: str) -> None:
    raw = json.loads(module().model_dump_json())
    table = raw["tables"][0]
    if mutation == "duplicate_table":
        raw["tables"].append(table)
    elif mutation == "duplicate_column":
        table["columns"][1] = table["columns"][0]
    elif mutation == "duplicate_row":
        table["rows"].append(table["rows"][0])
    elif mutation == "unknown":
        table["rows"][0]["fact_ids"][0] = "unknown"
    elif mutation == "short":
        table["rows"][0]["fact_ids"] = []
    elif mutation == "reused":
        table["rows"][1]["fact_ids"] = table["rows"][0]["fact_ids"]
    elif mutation in {"wrong_row", "wrong_field"}:
        raw["facts"][0]["row_id" if mutation == "wrong_row" else "field"] = "wrong"
    elif mutation == "omitted":
        table["rows"].pop()
    elif mutation == "duplicate_fact":
        raw["facts"].append(raw["facts"][0])
    else:
        for t in raw["tables"]:
            t["interface_id"] = "cp1.same"
    with pytest.raises(ValidationError):
        Module.model_validate_json(json.dumps(raw))


def test_markdown_uses_identical_fact_values_and_fixed_interface_shape() -> None:
    value = module()
    output = table_markdown(value, "T4.6")
    assert output.startswith("| Line Item | Q1")
    assert "0.00" in output and "null" in output
    assert "Missing —" not in output
    for row in value.tables[2].rows:
        assert len(row.fact_ids) == len(value.tables[2].columns)
    empty = ReportTable(
        table_id="T4.16",
        title="Segment revenue",
        columns=(TableColumn(field="segment_id", label="segment_id"),),
        rows=(),
        interface_id="cp1.segment_revenue_schedule",
    )
    value = value.model_copy(update={"tables": (*value.tables, empty)})
    assert (
        table_markdown(value, "T4.16")
        == "<!-- table-id: cp1.segment_revenue_schedule -->\n\n| segment_id |\n|---|"
    )
    hostile = "</script> | [link](https://bad) `code` **strong** \\ \r\nnext"
    escaped = markdown_cell(hostile)
    assert "</script>" not in escaped and "[link]" not in escaped and "`code`" not in escaped
    assert "&#124;" in escaped and "<br>next" in escaped
    assert "\n" not in escaped


def test_preview_receipt_hashes_outputs_without_accepting_module(tmp_path: Path) -> None:
    pack, financial = data()
    path = write_statement_preview(
        pack, financial, financial.books[0].book_id, tmp_path / "preview"
    )
    receipt = json.loads((path.parent / "complete.json").read_text())
    assert receipt["module_acceptance"] == receipt["analytical_qualification"] == "unrun"
    for name, digest in receipt["files"].items():
        assert hashlib.sha256((path.parent / name).read_bytes()).hexdigest() == digest
    assert not (path.parent / "accepted.html").exists()
    with pytest.raises(FileExistsError):
        write_statement_preview(pack, financial, financial.books[0].book_id, path.parent)


def test_journal_preview_requires_valid_current_financial_stage_and_keeps_pending_ticket(
    tmp_path: Path,
) -> None:
    store, ticket, extraction = cp1_case(tmp_path)
    with pytest.raises(ValueError, match="not available"):
        cp1_statement_preview(store, ticket.ticket_id, tmp_path / "too-early")
    submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    before = store.read().content_hash()
    path = cp1_statement_preview(store, ticket.ticket_id, tmp_path / "preview")
    assert path.exists() and store.read().content_hash() == before
    receipt = json.loads((path.parent / "complete.json").read_text())
    assert receipt["execution_binding"]["snapshot_sha256"] == before
    assert store.read().attempts[-1].status == "pending"
    store.interrupt(ticket.ticket_id, "Fixture changes source snapshot")
    pack = store.read().pack
    changed = pack.model_copy(
        update={
            "sources": (
                pack.sources[0].model_copy(update={"limitation": "Changed evidence limitation"}),
            )
        }
    )
    store.replace_pack(changed)
    with pytest.raises(ValueError, match=r"upstream|stale"):
        cp1_statement_preview(store, ticket.ticket_id, tmp_path / "stale")


def test_statement_preview_cli_returns_file_and_preserves_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy_vii.__main__ import main

    store, ticket, extraction = cp1_case(tmp_path)
    submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    before = store.read().content_hash()
    output = tmp_path / "cli-preview"
    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy-vii",
            "execution",
            "--directory",
            str(store.directory),
            "statement-preview",
            "--ticket",
            ticket.ticket_id,
            "--output",
            str(output),
        ],
    )
    main()
    assert Path(capsys.readouterr().out.strip()) == output / "candidate.html"
    assert (output / "complete.json").is_file()
    assert store.read().content_hash() == before


def test_old_module_and_view_versions_are_rejected() -> None:
    value = module().model_copy(update={"schema_version": "module/1"})
    with pytest.raises(ValidationError, match="module/2"):
        Module.model_validate_json(value.model_dump_json())
    pack, financial = data()
    view = statement_view(pack, financial, financial.books[0].book_id)
    with pytest.raises(ValidationError, match="view/2"):
        type(view).model_validate_json(
            view.model_copy(update={"schema_version": "view/1"}).model_dump_json()
        )


@pytest.mark.browser
@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 800), (720, 450)])
def test_statement_panels_offline_exact_fields_keyboard_and_provenance(
    tmp_path: Path, width: int, height: int
) -> None:
    pack, financial = data()
    view = statement_view(pack, financial, financial.books[0].book_id)
    path = tmp_path / "candidate.html"
    path.write_text(render(view), encoding="utf-8")
    evidence = Path("artifacts/rendering/statements") / tmp_path.parent.name / tmp_path.name
    evidence.mkdir(parents=True)
    (evidence / "candidate.html").write_bytes(path.read_bytes())
    (evidence / "view.json").write_text(view.model_dump_json())
    errors, network = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": height}, offline=True)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: network.append(req.url))
        page.goto(path.as_uri() + "#CP-1")
        expect(page.get_by_text("CANDIDATE PREVIEW · NOT ACCEPTED")).to_be_visible()
        for fact in next(m for m in view.modules if m.module_id == "CP-1").facts:
            target = page.locator(
                f'[data-table-id="{fact.table_id}"] [data-fact-id="{fact.fact_id}"]'
            )
            expect(target).to_have_text(table_display(fact))
            assert target.count() == 1
        amount = page.locator(
            '[data-table-id="T4.4"] tr[data-row-id="cogs"] [data-field="Q2"] button'
        )
        amount.focus()
        page.keyboard.press("Enter")
        inspector = page.get_by_role("complementary", name="Evidence inspector")
        for text in (
            "-30",
            "30",
            "negative absolute source amount",
            "1000000",
            "USD",
            "2025-04-01",
            "2025-06-30",
            "US GAAP",
            "Consolidated",
        ):
            expect(inspector).to_contain_text(text)
        assert page.locator('[data-table-id="T4.4"] th[scope="row"]').count() > 0
        page.locator(
            '[data-table-id="T4.6"] tr[data-row-id="other:not-applicable"] [data-field="Q2"] button'
        ).click()
        expect(inspector).to_contain_text("not_applicable")
        expect(inspector).to_contain_text("This item does not apply")
        scroll = page.locator('[data-table-id="T4.4"]')
        scroll.focus()
        page.keyboard.press("ArrowRight")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(evidence / f"statements-{width}x{height}.png"), full_page=True)
        page.evaluate("document.body.style.zoom='1.25'")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors and not [u for u in network if u.startswith(("http:", "https:"))]
        (evidence / "checks.json").write_text(
            json.dumps(
                {
                    "viewport": [width, height],
                    "field_parity": "passed",
                    "errors": errors,
                    "requests": network,
                    "css_zoom": 1.25,
                    "analytical_qualification": "unrun",
                }
            )
        )
        browser.close()


def test_interface_headings_and_null_tokens_cannot_change_machine_meaning() -> None:
    value = module()
    table = ReportTable(
        table_id="interface",
        title="Interface",
        interface_id="cp1.test",
        columns=(TableColumn(field="source_id", label="source_id"),),
        rows=(TableRow(row_id="r", label="r", fact_ids=("f",)),),
    )
    fact = Fact(
        fact_id="f",
        label="Source",
        table_id="interface",
        row_id="r",
        field="source_id",
        text="source_one",
    )
    value = value.model_copy(update={"tables": (table,), "facts": (fact,)})
    assert "| source_id |" in table_markdown(value, "interface")
    assert "| source_one |" in table_markdown(value, "interface")
    for heading in ("Source ID", "source&#95;id"):
        changed = table.model_copy(
            update={"columns": (TableColumn(field="source_id", label=heading),)}
        )
        with pytest.raises(ValidationError, match="exact field"):
            table_markdown(value.model_copy(update={"tables": (changed,)}), "interface")
    with pytest.raises(ValidationError, match="extra row header"):
        table_markdown(
            value.model_copy(
                update={"tables": (table.model_copy(update={"row_header": "Record"}),)}
            ),
            "interface",
        )
    for text in ("null", "N/A", "", "none"):
        with pytest.raises(ValueError, match="null marker"):
            table_markdown(
                value.model_copy(update={"facts": (fact.model_copy(update={"text": text}),)}),
                "interface",
            )


def test_stale_review_rejected_and_empty_table_has_no_fabricated_row() -> None:
    pack, financial = data()
    with pytest.raises(ValueError, match="bind"):
        statement_view(
            pack, financial.model_copy(update={"pack_sha256": "0" * 64}), financial.books[0].book_id
        )
    value = module()
    empty = ReportTable(
        table_id="empty",
        title="Empty",
        columns=(TableColumn(field="value", label="Value"),),
        rows=(),
        limitation="No schedule disclosed",
    )
    amended = value.model_copy(update={"tables": (*value.tables, empty)})
    assert table_markdown(amended, "empty").splitlines() == ["| Value |", "|---|"]


def test_layout_survives_engine_candidate_and_accepted_views_then_is_hidden_when_stale(
    tmp_path: Path,
) -> None:
    from tests.product.test_execution import candidate_for, fixture_store

    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    fact = Fact(
        fact_id="fixture",
        label="Synthetic engine value",
        table_id="fixture",
        row_id="r",
        field="v",
        text="Protocol fixture only",
    )
    layout = ReportTable(
        table_id="fixture",
        title="Engine fixture",
        columns=(TableColumn(field="v", label="Value"),),
        rows=(TableRow(row_id="r", label="Row", fact_ids=("fixture",)),),
    )
    candidate = candidate_for(store, "CP-0").model_copy(
        update={"facts": (fact,), "tables": (layout,)}
    )
    store.finish(ticket.ticket_id, candidate.model_dump_json(), lambda _: ())
    assert store.view().modules[0].tables == (layout,)
    assert store.view(ticket.ticket_id).modules[0].tables == (layout,)
    pack = store.read().pack
    store.replace_pack(
        pack.model_copy(
            update={
                "sources": (pack.sources[0].model_copy(update={"limitation": "Changed fixture"}),)
            }
        )
    )
    assert store.view().modules[0].status == "stale"
    assert store.view().modules[0].tables == store.view().modules[0].facts == ()


def test_period_end_only_source_has_empty_flow_tables() -> None:
    from tests.product.test_financials import book

    value = book()
    point = value.periods[-1].model_copy(
        update={
            "period_type": "PERIOD_END",
            "start_date": None,
            "day_count": None,
            "limitation": "Point in time only",
        }
    )
    value = value.model_copy(update={"periods": (point,), "accounts": (), "facilities": ()})
    pack, financial = freeze(value)
    projected = next(
        m for m in statement_view(pack, financial, value.book_id).modules if m.module_id == "CP-1"
    )
    assert not projected.tables[0].rows and not projected.tables[1].rows
    assert projected.tables[2].rows
    assert all(
        fact.field == point.period_id and fact.table_id == "T4.6" for fact in projected.facts
    )


@pytest.mark.browser
def test_hostile_long_table_labels_and_empty_register_are_safe(tmp_path: Path) -> None:
    pack, financial = data()
    view = statement_view(pack, financial, financial.books[0].book_id)
    module_view = next(m for m in view.modules if m.module_id == "CP-1")
    hostile = '<img src="https://invalid" onerror="window.injected=true">' + "unbroken" * 80
    first = module_view.tables[0]
    first = first.model_copy(
        update={"rows": (first.rows[0].model_copy(update={"label": hostile}), *first.rows[1:])}
    )
    empty = ReportTable(
        table_id="empty",
        title="Empty schedule",
        columns=(TableColumn(field="value", label="Value"),),
        rows=(),
        limitation="No schedule disclosed",
    )
    changed = module_view.model_copy(update={"tables": (first, *module_view.tables[1:], empty)})
    view = view.model_copy(
        update={"modules": tuple(changed if m.module_id == "CP-1" else m for m in view.modules)}
    )
    path = tmp_path / "hostile.html"
    path.write_text(render(view))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800}, offline=True)
        page.goto(path.as_uri() + "#CP-1")
        expect(page.get_by_role("rowheader", name=hostile, exact=True)).to_have_text(hostile)
        assert not page.evaluate("Boolean(window.injected)")
        assert not page.locator("img").count()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        expect(page.locator('[data-table-id="empty"]')).to_contain_text("No rows supplied")
        browser.close()


def test_not_applicable_statement_cell_retains_its_source_status() -> None:
    pack, financial = data()
    view = statement_view(pack, financial, financial.books[0].book_id)
    fact = next(
        f
        for m in view.modules
        for f in m.facts
        if (f.table_id, f.row_id, f.field) == ("T4.6", "other:not-applicable", "Q2")
    )
    assert fact.status == "not_applicable"
    assert table_display(fact) == "null"
    assert display(fact) == "Not applicable — This item does not apply"
    for update in ({"amount": Decimal(0)}, {"limitation": None}):
        with pytest.raises(ValidationError, match="unsettled fact"):
            Fact.model_validate_json(fact.model_copy(update=update).model_dump_json())
