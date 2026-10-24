"""``report_view.build``: the Credit Snapshot Front Page from bound registers, honest elsewhere."""

import json
import re
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from deploy_vii.bindings.cp0 import CP0
from deploy_vii.contracts import Fact, ModuleView, PathwayId, Run, Status, View
from deploy_vii.delivery import cp0_view
from deploy_vii.readiness import build_readiness
from deploy_vii.render import empty_view, render
from deploy_vii.report_view import (
    AbsentColumn,
    Block,
    BlockTab,
    Figure,
    Row,
    build,
    fact_spelling,
    pathways,
)
from tests.product.credit_snapshot import (
    CREDIT_SNAPSHOT_MAPS,
    credit_snapshot_fixture,
    credit_snapshot_view,
)
from tests.product.oracle import expected_text, gap_ids
from tests.product.test_readiness import readiness_fixture
from tests.product.test_render import synthetic_view

CREDIT = next(p for p in pathways() if p.id == "credit_snapshot")


def built() -> tuple[View, dict[str, Block]]:
    view = credit_snapshot_view()
    report = build(view, CREDIT, CREDIT_SNAPSHOT_MAPS)
    assert tuple(b.block_id for b in report.blocks) == CREDIT.blocks
    return view, {b.block_id: b for b in report.blocks}


def test_build_fills_blocks_from_bound_registers_and_states_the_rest() -> None:
    _, blocks = built()
    states = {block_id: block.state for block_id, block in blocks.items()}
    assert states == {
        "key-findings": "populated",
        "company-operating-model": "populated",
        "model-chart-strip": "populated",
        "capital-structure": "populated",
        "financials-credit-metrics": "populated",
        "strengths-weaknesses": "populated",
        "relative-value": "collapsed",
        "company-profile": "collapsed",
        "transaction-summary": "collapsed",
        "portfolio-fit": "collapsed",
        "committee-challenge": "collapsed",
        # CP-8 is not part of the Credit Snapshot Pathway: its own word, not "Not run".
        "what-changed": "not_in_pathway",
    }
    assert blocks["what-changed"].note and blocks["what-changed"].note.startswith(
        "Not in this Pathway"
    )
    # FP 01's heads and owner codes.
    assert blocks["company-operating-model"].title == "Company and operating model"
    assert blocks["strengths-weaknesses"].owner == "CP-2 · CP-6"
    assert all("Synthetic" in b.tags for b in blocks.values() if b.state in {"populated"})


def test_capital_structure_is_tabbed_with_the_ebitda_bridge_and_an_honest_empty_tab() -> None:
    _, blocks = built()
    block = blocks["capital-structure"]
    assert block.tab_label == "Capital structure"
    assert [tab.label for tab in block.tabs] == ["EBITDA adjustments", "Transaction and new debt"]
    bridge, new_debt = block.tabs
    assert [row.label for row in bridge.rows] == ["Reported EBITDA", "Add-backs", "Adjusted EBITDA"]
    # The empty tab names its producer and the register; it does not restate "no rows".
    assert not new_debt.rows
    assert new_debt.note == "CP-1 reported an empty Transaction and new debt register in this run."
    assert block.columns == ("Coupon", "Maturity", "Outstanding", "x EBITDA", "% EV", "Rec.")
    assert block.row_header == "Facility"
    assert [row.style for row in block.rows] == ["row", "row", "row", "subtotal", "total"]
    # Amounts are scaled once, in the head (decision 0004 section 4).
    assert block.scale == "US$ m" and block.meta == "21 Oct 2026 · US$ m"
    assert bridge.scale == "US$ m"
    assert block.owner == "MODEL" and block.tab_label == "Capital structure"


def test_every_bound_cell_is_spelled_as_the_independent_oracle_does() -> None:
    view, blocks = built()
    gaps = gap_ids(view)
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")
    by_id = {f.fact_id: f for f in cp1.facts}
    layouts = {t.table_id: t for t in cp1.tables}
    checked = 0
    for block_id, table_id in (
        ("capital-structure", "T4.18"),
        ("financials-credit-metrics", "T4.4"),
        ("model-chart-strip", "T4.10"),
    ):
        rows = blocks[block_id].rows
        assert [r.row_id for r in rows] == [r.row_id for r in layouts[table_id].rows]
        for row, source in zip(rows, layouts[table_id].rows, strict=True):
            for cell, fact_id in zip(row.cells, source.fact_ids, strict=True):
                assert cell.text == expected_text(by_id[fact_id], gaps.get(("CP-1", fact_id)))
                checked += 1
    assert checked == 30 + 12 + 12


def test_fact_units_follow_the_display_classes_and_gaps_carry_their_reference() -> None:
    view, blocks = built()
    gaps = gap_ids(view)
    cells = {row.label: row.cells for row in blocks["capital-structure"].rows}
    revolver, tla, notes = cells["Revolver"], cells["Term loan A"], cells["Senior notes 2030"]
    assert [c.text for c in revolver[:5]] == ["250 bp", "2028-03-31", "120", "0.03x", "2.5%"]
    assert [c.unit_class for c in revolver[:5]] == ["text", "text", "amount", "multiple", "percent"]
    # Exact text plus the unit's label: the internal token never reaches the page.
    assert notes[0].text == "6.250%"
    gap = gaps["CP-1", "T4.18.tla.outstanding"]
    assert tla[2].text == f"∅ {gap}" and tla[2].prov == "gap" and tla[2].gap_ref == gap
    assert tla[2].state == "gap" and tla[2].ref_id is None
    # Synthetic case: a cited value is S#; a calculation stays K#.
    assert revolver[2].prov == "synthetic" and revolver[2].ref_id.startswith("S")  # type: ignore[union-attr]
    assert revolver[3].prov == "calculated" and revolver[3].ref_id.startswith("K")  # type: ignore[union-attr]
    # A subtotal has no coupon: not applicable, spelled n.m. with its gap reference.
    assert cells["Total unsecured"][0].state == "not_meaningful"
    assert cells["Total unsecured"][0].text.endswith("n.m.")


def test_period_grid_structure_comes_from_the_columns_and_the_gaps() -> None:
    _, blocks = built()
    grid = blocks["financials-credit-metrics"]
    assert grid.kind == "period_grid"
    assert [(g.label, g.span) for g in grid.groups] == [
        ("Fiscal year", 2),
        ("LTM", 1),
        ("Pro forma", 1),
    ]
    assert grid.base_column == 2
    # The reason is the first gap's own words, not a generic phrase.
    assert grid.absent_columns == (AbsentColumn(column=3, reason="merger debt unstated"),)
    assert grid.scale == "US$ m" and grid.meta == "US$ m; metrics in x; negatives in parentheses"
    margins = {r.label: [c.text for c in r.cells] for r in grid.rows}["Adjusted EBITDA margin"]
    assert margins[:3] == ["33.7%", "33.2%", "33.6%"]  # ROUND_HALF_UP at 1 dp
    assert margins[3].startswith("∅ G")


def test_prose_lines_mark_model_text_and_open_gaps() -> None:
    _, blocks = built()
    lines = blocks["key-findings"].lines
    assert len(lines) == 3
    assert [run.kind for run in lines[0].runs] == ["pen", "fig"]
    assert lines[0].runs[1].ref_id and lines[0].runs[1].ref_id.startswith("S")
    assert [run.kind for run in lines[2].runs] == ["text", "gap"]
    assert lines[2].runs[1].text.startswith("∅ G")


def test_a_register_without_rows_is_absent_and_states_why() -> None:
    view = credit_snapshot_view()
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")
    emptied = ModuleView(
        module_id="CP-1",
        title=cp1.title,
        aliases=cp1.aliases,
        status="candidate",
        artifact_sha256="e" * 64,
        facts=tuple(f for f in cp1.facts if f.table_id != "T4.10"),
        tables=tuple(t for t in cp1.tables if t.table_id != "T4.10"),
    )
    swapped = view.model_copy(
        update={"modules": tuple(emptied if m.module_id == "CP-1" else m for m in view.modules)}
    )
    block = {b.block_id: b for b in build(swapped, CREDIT, CREDIT_SNAPSHOT_MAPS).blocks}[
        "model-chart-strip"
    ]
    assert block.state == "absent"
    assert block.note == "Absent: CP-1 supplied no rows for this block."


def test_unbound_and_misplaced_facts_fail_closed() -> None:
    view = credit_snapshot_view()
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")
    stray = Fact(fact_id="stray", label="Stray", table_id="T9.9", row_id="r", text="x")
    widened = cp1.model_copy(update={"facts": (*cp1.facts, stray)})
    swapped = view.model_copy(
        update={"modules": tuple(widened if m.module_id == "CP-1" else m for m in view.modules)}
    )
    with pytest.raises(ValueError, match=r"unbound fact CP-1/T9\.9"):
        build(swapped, CREDIT, CREDIT_SNAPSHOT_MAPS)
    earnings = next(p for p in pathways() if p.id == "earnings_update")
    with pytest.raises(ValueError, match="Pathway"):
        build(view, earnings, CREDIT_SNAPSHOT_MAPS)


def run(pathway: PathwayId = "credit_snapshot") -> Run:
    return Run(
        run_id="r",
        issuer_id="i",
        issuer_name="Issuer",
        as_of=date(2026, 10, 21),
        case_kind="synthetic",
        pathway=pathway,
    )


def with_status(view: View, module_id: str, status: Status, limitation: str = "x") -> View:
    module = next(m for m in view.modules if m.module_id == module_id)
    swapped = ModuleView(
        module_id=module_id,
        title=module.title,
        aliases=module.aliases,
        status=status,
        limitations=(limitation,) if status in {"blocked", "stale", "rejected"} else (),
    )
    return view.model_copy(
        update={"modules": tuple(swapped if m.module_id == module_id else m for m in view.modules)}
    )


def test_an_unrun_pathway_shows_each_blocks_honest_state() -> None:
    blocks = {b.block_id: b for b in build(empty_view(run()), CREDIT, ()).blocks}
    assert {k: v.state for k, v in blocks.items()} == {
        "key-findings": "not_run",
        "company-operating-model": "not_run",
        "model-chart-strip": "not_run",
        "capital-structure": "not_run",
        "financials-credit-metrics": "not_run",
        "strengths-weaknesses": "not_run",
        "relative-value": "not_run",
        "company-profile": "not_run",
        "transaction-summary": "absent",  # no module produces it yet
        "portfolio-fit": "absent",
        "committee-challenge": "not_run",
        "what-changed": "not_in_pathway",
    }
    assert blocks["key-findings"].note == "Not run: CP-2 has not run."
    assert blocks["portfolio-fit"].note == "Absent: No module produces this block yet."
    assert all(b.owner != "Unbound" for b in blocks.values())


@pytest.mark.parametrize(
    ("status", "state", "words"),
    [
        ("blocked", "blocked", "Blocked: CP-2 is blocked"),
        ("stale", "not_run", "stale and must be rerun"),
        ("rejected", "not_run", "Not run: CP-2 has not run."),
    ],
)
def test_a_producer_that_cannot_supply_a_block_says_why(
    status: Status, state: str, words: str
) -> None:
    view = with_status(empty_view(run()), "CP-2", status)
    block = {b.block_id: b for b in build(view, CREDIT, ()).blocks}["key-findings"]
    assert block.state == state and block.note and words in block.note


def test_the_call_is_withheld_when_cp2_is_outside_the_pathway_or_blocked() -> None:
    credit = build(empty_view(run()), CREDIT, ())
    assert credit.call_withheld is None and [i.kind for i in credit.call] == ["na"]
    earnings_run = run("earnings_update")
    earnings = next(p for p in pathways() if p.id == "earnings_update")
    outside = build(empty_view(earnings_run), earnings, ())
    assert outside.call_withheld == "outside_pathway"
    blocked = build(with_status(empty_view(run()), "CP-2", "blocked"), CREDIT, ())
    assert blocked.call_withheld == "blocked"
    assert all(item.kind == "na" for item in blocked.call)


@pytest.mark.parametrize("pathway", [p.id for p in pathways()])
def test_every_pathway_builds_an_honest_front_page_for_an_unrun_view(pathway: PathwayId) -> None:
    preset = next(p for p in pathways() if p.id == pathway)
    report = build(empty_view(run(pathway)), preset, ())
    assert tuple(b.block_id for b in report.blocks) == preset.blocks
    assert {b.state for b in report.blocks} <= {"not_run", "absent", "not_in_pathway"}
    assert all(b.note and not b.rows and not b.lines for b in report.blocks)


def test_cp0_facts_reach_rail_destinations_only_never_a_front_page_block() -> None:
    pack, review = readiness_fixture()
    module = build_readiness(pack, review)
    view = cp0_view(pack, module, accepted=False)
    assert module.facts and {e.block_id for e in CP0.entries} == {
        "header",
        "evidence",
        "limitations",
    }
    report = build(view, CREDIT, (CP0,))
    assert not any(b.rows or b.lines or b.tabs for b in report.blocks)
    assert {b.state for b in report.blocks} <= {"not_run", "absent", "not_in_pathway"}


def test_render_builds_the_front_page_when_no_report_is_supplied() -> None:
    """Both branches of the production path: a view with output, and one without."""
    with_output = json.loads(_island(render(synthetic_view())))["report"]
    financials = next(
        b for b in with_output["blocks"] if b["block_id"] == "financials-credit-metrics"
    )
    assert financials["state"] == "populated"
    assert [row["label"] for row in financials["rows"]] == ["Cash and equivalents · FY2025"]
    assert financials["rows"][0]["cells"][0]["text"] == "0"  # unit "currency": 0 dp
    assert all(b["owner"] != "Unbound" for b in with_output["blocks"])
    without = json.loads(_island(render(empty_view(run()))))["report"]
    assert all(b["owner"] != "Unbound" for b in without["blocks"])
    assert {b["state"] for b in without["blocks"]} == {"not_run", "absent", "outside"}
    assert without["call_state"] == "no-judgement"


def _island(html: str) -> str:
    match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html)
    assert match
    return match.group(1)


def test_the_page_never_spells_null_or_the_internal_status_name() -> None:
    view, report = credit_snapshot_fixture()
    html = render(view, report)
    island = json.loads(_island(html))
    shown = [fact["table_display"] for module in island["modules"] for fact in module["facts"]]
    assert shown and "null" not in shown
    assert "not_in_pathway" not in html


# --- fact_spelling: the ruling's unit-class table, with independent expectations -------------


@pytest.mark.parametrize(
    ("unit", "amount", "expected"),
    [
        ("MILLIONS", "11648", "11,648"),
        ("THOUSANDS", "-62", "(62)"),
        ("UNITS", "1234567.5", "1,234,568"),
        ("currency", "0.4", "0"),  # statement lines stay at 0 dp
        ("currency", "31", "31"),
        ("PERCENT", "0.308", "30.8%"),
        ("decimal_fraction", "0.0125", "1.3%"),
        ("MULTIPLE", "3.285", "3.29x"),
        ("basis_points", "250", "250 bp"),
        ("decimal_percent", "6.500", "6.500%"),
        ("MILLIONS", "1E+200", "1E+200 MILLIONS"),  # beyond 100 digits: exact text, as rendered
        ("USD per EUR", "1.0825", "1.0825 USD per EUR"),
        ("ratio", "1E+200", "1E+200 ratio"),
    ],
)
def test_fact_spelling_follows_the_unit_classes(unit: str, amount: str, expected: str) -> None:
    fact = Fact(fact_id="f", label="F", amount=Decimal(amount), unit=unit, period="FY2025")
    assert fact_spelling(fact, None)[2] == expected


@pytest.mark.parametrize(
    "fact_unit", ["basis_points", "decimal_percent", "USD per EUR", "MILLIONS", "currency"]
)
def test_the_page_spells_each_unit_as_the_independent_oracle_does(fact_unit: str) -> None:
    for amount in ("250", "6.500", "1.0825", "1E+200"):
        fact = Fact(fact_id="f", label="F", amount=Decimal(amount), unit=fact_unit, period="FY")
        assert fact_spelling(fact, None)[2] == expected_text(fact, None)
        assert "basis_points" not in fact_spelling(fact, None)[2]
        assert "decimal_percent" not in fact_spelling(fact, None)[2]


def test_a_fact_declares_the_precision_of_a_per_unit_amount() -> None:
    per_share = Fact(
        fact_id="p", label="P", amount=Decimal("0.4"), unit="currency", period="FY", decimals=2
    )
    statement = per_share.model_copy(update={"decimals": None, "fact_id": "s"})
    assert fact_spelling(per_share, None)[2] == "0.40" == expected_text(per_share, None)
    assert fact_spelling(statement, None)[2] == "0" == expected_text(statement, None)
    with pytest.raises(ValidationError, match="decimals"):
        Fact(fact_id="x", label="X", text="t", decimals=9)


def test_fact_spelling_of_unsettled_and_text_facts() -> None:
    missing = Fact(fact_id="m", label="M", status="missing", unit="MULTIPLE", limitation="gone")
    assert fact_spelling(missing, "G8") == ("multiple", "gap", "∅ G8")
    inapplicable = Fact(
        fact_id="n", label="N", status="not_applicable", unit="PERCENT", limitation="no sense"
    )
    assert fact_spelling(inapplicable, "G41") == ("percent", "not_meaningful", "∅ G41 n.m.")
    assert fact_spelling(Fact(fact_id="t", label="T", text="None"), None) == (
        "text",
        "known",
        "None",
    )
    with pytest.raises(ValueError, match="G#"):
        fact_spelling(missing, None)  # an unsettled fact without its G# fails closed


# --- Block contract additions ---------------------------------------------------------------


def _row(label: str = "r") -> Row:
    from tests.product.test_browser import _cell

    return Row(row_id=label, label=label, cells=(_cell("1", "synthetic", "S1"),))


def test_tab_and_figure_rules() -> None:
    base: dict[str, Any] = {
        "block_id": "b",
        "title": "Capital structure",
        "owner": "CP-1",
        "state": "populated",
        "kind": "dense",
        "columns": ("US$ m",),
        "rows": (_row(),),
    }
    tab = BlockTab(label="EBITDA adjustments", columns=("US$ m",), rows=(_row("t"),))
    assert Block(**base, tab_label="Capital structure", tabs=(tab,)).tabs == (tab,)
    with pytest.raises(ValidationError, match="names its own tab"):
        Block(**base, tabs=(tab,))
    with pytest.raises(ValidationError, match="names its own tab"):
        Block(**base, tab_label="Capital structure")
    with pytest.raises(ValidationError, match="distinct"):
        Block(**base, tab_label="EBITDA adjustments", tabs=(tab,))
    with pytest.raises(ValidationError, match="Only table blocks"):
        Block(**{**base, "kind": "chart", "rows": ()}, tab_label="a", tabs=(tab,))
    with pytest.raises(ValidationError, match="Only a block with content"):
        Block(
            **{**base, "state": "not_run", "rows": (), "columns": ()},
            note="n",
            tab_label="a",
            tabs=(tab,),
        )
    with pytest.raises(ValidationError, match="states why"):
        BlockTab(label="x")
    with pytest.raises(ValidationError, match="carries no note"):
        BlockTab(label="x", rows=(_row(),), note="n", columns=("US$ m",))
    with pytest.raises(ValidationError, match="do not match"):
        BlockTab(label="x", columns=("a", "b"), rows=(_row(),))
    # Blocks outside the Pathway have their own state and need their note like the others.
    outside = Block(
        block_id="o", title="O", owner="CP-8", state="not_in_pathway", kind="prose", note="n"
    )
    assert outside.state == "not_in_pathway"
    with pytest.raises(ValidationError, match="states why"):
        Block(block_id="o", title="O", owner="CP-8", state="not_in_pathway", kind="prose")


def test_a_chart_block_holds_one_chart_or_a_figure_strip_never_both_or_neither() -> None:
    _, report = credit_snapshot_fixture()
    strip = next(b for b in report.blocks if b.block_id == "model-chart-strip")
    assert [f.fig_id for f in strip.figures] == ["S.1", "S.2", "S.3", "S.4"]
    fields = {k: getattr(strip, k) for k in ("block_id", "title", "owner", "state", "kind")}
    with pytest.raises(ValidationError, match="holds chart only"):
        Block(**fields)
    with pytest.raises(ValidationError, match="not both"):
        Block(**fields, chart=strip.figures[0].chart, figures=strip.figures)
    assert isinstance(strip.figures[0], Figure)


def test_the_base_column_cannot_also_be_an_absent_column() -> None:
    from tests.product.test_browser import _cell

    two = Row(
        row_id="r", label="x", cells=(_cell("1", "synthetic", "S1"), _cell("2", "synthetic", "S1"))
    )
    base: dict[str, Any] = {
        "block_id": "g",
        "title": "Financials",
        "owner": "CP-1",
        "state": "populated",
        "kind": "period_grid",
        "columns": ("FY", "LTM"),
        "rows": (two,),
    }
    assert Block(**base, base_column=1, absent_columns=(AbsentColumn(column=0, reason="r"),))
    with pytest.raises(ValidationError, match="base column cannot also be absent"):
        Block(**base, base_column=1, absent_columns=(AbsentColumn(column=1, reason="r"),))


# --- scale, mixed units, the chart-strip downgrade ----------------------------------------------


def _with_cp1(view: View, facts: tuple[Fact, ...]) -> View:
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")
    swapped = cp1.model_copy(update={"facts": facts})
    return view.model_copy(
        update={"modules": tuple(swapped if m.module_id == "CP-1" else m for m in view.modules)}
    )


def test_a_table_states_one_scale_and_refuses_to_mix_amount_units() -> None:
    view = credit_snapshot_view()
    block = {b.block_id: b for b in build(view, CREDIT, CREDIT_SNAPSHOT_MAPS).blocks}[
        "financials-credit-metrics"
    ]
    assert block.scale == "US$ m"
    revenue = next(r for r in block.rows if r.label == "Net revenues")
    assert revenue.cells[1].text == "10,400"  # bare number; the unit is in the head
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")
    mixed = tuple(
        f.model_copy(update={"unit": "THOUSANDS"}) if f.fact_id == "T4.4.revenue.LTM" else f
        for f in cp1.facts
    )
    with pytest.raises(ValueError, match=r"T4\.4 column 'LTM' mixes amount units"):
        build(_with_cp1(view, mixed), CREDIT, CREDIT_SNAPSHOT_MAPS)
    # A different currency is a different unit too.
    euro = tuple(
        f.model_copy(update={"currency": "EUR"}) if f.fact_id == "T4.4.revenue.FY2025" else f
        for f in cp1.facts
    )
    with pytest.raises(ValueError, match="column 'FY2025' mixes amount units"):
        build(_with_cp1(view, euro), CREDIT, CREDIT_SNAPSHOT_MAPS)


def test_statement_currency_is_checked_for_mixing_but_has_no_scale_label() -> None:
    view = credit_snapshot_view()
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")

    def with_unit(fact_id: str, **changes: object) -> tuple[Fact, ...]:
        return tuple(f.model_copy(update=changes) if f.fact_id == fact_id else f for f in cp1.facts)

    # Unscaled statement lines against scaled amounts: fail closed, column named.
    with pytest.raises(ValueError, match="column 'LTM' mixes amount units"):
        build(
            _with_cp1(view, with_unit("T4.4.revenue.LTM", unit="currency")),
            CREDIT,
            CREDIT_SNAPSHOT_MAPS,
        )
    # A table of statement lines alone is fine and states no scale.
    every = tuple(
        f.model_copy(update={"unit": "currency"})
        if f.table_id == "T4.4" and f.unit == "MILLIONS"
        else f
        for f in cp1.facts
    )
    grid = {
        b.block_id: b for b in build(_with_cp1(view, every), CREDIT, CREDIT_SNAPSHOT_MAPS).blocks
    }["financials-credit-metrics"]
    assert grid.scale is None
    # Two currencies are two units, whatever the unit.
    usd_eur = tuple(
        f.model_copy(update={"unit": "currency", "currency": "EUR"})
        if f.fact_id == "T4.4.revenue.FY2025"
        else f.model_copy(update={"unit": "currency"})
        if f.table_id == "T4.4" and f.unit == "MILLIONS"
        else f
        for f in cp1.facts
    )
    with pytest.raises(ValueError, match="column 'FY2025' mixes amount units"):
        build(_with_cp1(view, usd_eur), CREDIT, CREDIT_SNAPSHOT_MAPS)


def test_the_chart_strip_without_series_shows_four_na_frames_above_the_kpi_table() -> None:
    _, blocks = built()
    strip = blocks["model-chart-strip"]
    assert strip.state == "populated" and strip.kind == "dense"
    assert [(f.fig_id, f.title, f.chart.kind, f.placement) for f in strip.figures] == [
        ("S.1", "Leverage", "na", "above"),
        ("S.2", "Interest cover", "na", "above"),
        ("S.3", "Liquidity", "na", "above"),
        ("S.4", "Maturity wall", "na", "above"),
    ]
    assert strip.note == "Charts need S.1\u2013S.4 series; KPI register shown as a table"
    assert strip.rows and all(f.chart.reason for f in strip.figures)
    assert strip.full_analysis_route == "CP-1" and strip.route_label == "Open in Model"


def test_prose_sections_labels_and_numbering_come_from_the_bindings() -> None:
    _, blocks = built()
    findings = blocks["key-findings"]
    assert findings.numbered and findings.pinned and findings.width == "five"
    assert blocks["company-operating-model"].width == "seven"
    sw = blocks["strengths-weaknesses"]
    assert [(line.section, line.label) for line in sw.lines] == [
        ("thesis", "Thesis"),
        ("strengths", "Scale"),
        ("strengths", "Liquidity"),
        ("weaknesses", "Maturities"),
        ("weaknesses", "Capex"),
    ]
    thesis = sw.lines[0]
    assert [run.kind for run in thesis.runs] == ["gap"]  # the label is the line's, not a run


def test_collapsed_blocks_show_one_line_of_summary() -> None:
    _, blocks = built()
    assert blocks["relative-value"].summary == "Secured 2032s preferred."
    # Task 7.2: the shipped CP-1A map; a keyvalue row is its register row label and cells.
    profile = blocks["company-profile"].summary or ""
    # Fix round 1 (R1): the owner is the row header and is not repeated as a cell.
    assert profile.startswith(
        "Public shareholders [Management Language]: No controlling holder is disclosed"
    )
    assert all(b.summary is None for b in blocks.values() if b.state == "populated")


def test_the_shipped_cp1a_map_fills_the_company_and_transaction_blocks() -> None:
    _, blocks = built()
    company = blocks["company-operating-model"]
    assert company.kind == "keyvalue" and company.owner == "CP-1A"
    assert [row.label for row in company.rows] == [
        "Issuer",
        "Business description",
        "Country",
        "Sector",
    ]
    assert [tab.label for tab in company.tabs] == ["Operating model"]
    assert [tab.label for tab in blocks["company-profile"].tabs] == ["Revenue and business mix"]
    transaction = blocks["transaction-summary"]
    assert transaction.kind == "prose" and transaction.owner == "Primary"
    assert transaction.lines[0].runs[0].text.startswith("No transaction is described")


def test_a_doubly_bound_table_fails_closed_in_build() -> None:
    from deploy_vii.bindings import Binding, BindingMap
    from deploy_vii.report_view import FactCoord

    again = Binding(
        fact_coord=FactCoord(module_id="CP-1", table_id="T4.10"),
        block_id="capital-structure",
        cell_slot="kpis-again",
        unit_class="text",
    )
    cp1 = next(m for m in CREDIT_SNAPSHOT_MAPS if m.module_id == "CP-1")
    doubled = BindingMap(module_id="CP-1", entries=(*cp1.entries, again))
    maps = tuple(doubled if m.module_id == "CP-1" else m for m in CREDIT_SNAPSHOT_MAPS)
    with pytest.raises(ValueError, match=r"doubly bound fact CP-1/T4\.10"):
        build(credit_snapshot_view(), CREDIT, maps)


def test_mixed_unrun_and_outside_producers_use_both_words() -> None:
    # CP-2 has not run; CP-6 is outside the Pathway: the block says both.
    view = with_status(empty_view(run()), "CP-6", "not_in_pathway")
    block = {b.block_id: b for b in build(view, CREDIT, ()).blocks}["strengths-weaknesses"]
    assert block.state == "not_run"
    assert block.note == (
        "Not run · Not in this Pathway: CP-2 has not run; CP-6 is not part of Credit Snapshot."
    )


def test_the_navigator_logo_is_the_provenanced_brand_image() -> None:
    import base64
    import hashlib
    from pathlib import Path

    brand = Path(__file__).resolve().parents[2] / "src/deploy_vii/assets/brand"
    (entry,) = json.loads((brand / "provenance.json").read_text())
    data = (brand / entry["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"] and len(data) == entry["bytes"]
    assert entry["licence"] == "owner-supplied brand asset; internal use per decision 0004"
    source = Path(__file__).resolve().parents[2] / "design/reference/brand" / entry["file"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["sha256"]
    html = render(empty_view(run()))
    assert base64.b64encode(data).decode() in html
    assert 'class="logo-mark"' not in html
    assert "State Street Investment Management" in html


def test_the_data_island_is_compact_json() -> None:
    island = _island(render(empty_view(run())))
    compact = json.dumps(json.loads(island), ensure_ascii=True, separators=(",", ":"))
    assert island == compact.replace("<", "\\u003c")


# --- lane integration: Pathway-scoped bindings, token spelling, fail-closed maps ----------------


def _on_pathway(pathway_id: PathwayId) -> View:
    base = credit_snapshot_view()
    return base.model_copy(update={"run": base.run.model_copy(update={"pathway": pathway_id})})


@pytest.mark.parametrize("pathway_id", [p.id for p in pathways()])
def test_every_bound_block_is_composed_a_rail_destination_or_listed_under_limitations(
    pathway_id: PathwayId,
) -> None:
    from deploy_vii.bindings import RAIL_DESTINATIONS

    preset = next(p for p in pathways() if p.id == pathway_id)
    view = _on_pathway(pathway_id)
    report = build(view, preset, CREDIT_SNAPSHOT_MAPS)
    listed = {item.block_id for item in report.unplaced}
    shown = {
        entry.block_id
        for module_map in CREDIT_SNAPSHOT_MAPS
        for entry in module_map.entries
        if any(m.module_id == module_map.module_id and m.facts for m in view.modules)
    }
    # A register this Pathway places in another of its blocks is not "outside" it (task 6.5):
    # FP 02's EBITDA adjustments and metric strip are second placements in FP 01 and back.
    second = {
        entry.block_id
        for module_map in CREDIT_SNAPSHOT_MAPS
        for entry in module_map.entries
        if any(
            other.fact_coord == entry.fact_coord and other.block_id in preset.blocks
            for other in module_map.entries
        )
    }
    assert shown
    for block_id in shown:
        assert (
            block_id in preset.blocks
            or block_id in RAIL_DESTINATIONS
            or block_id in listed
            or block_id in second
        )
    assert listed.isdisjoint(preset.blocks) and listed.isdisjoint(RAIL_DESTINATIONS)
    assert all(item.title for item in report.unplaced)
    assert all(item.state == "absent" for item in report.unplaced)
    assert all(
        f"bound to {item.block_id}, not in this Pathway" in item.note for item in report.unplaced
    )


def test_earnings_update_lists_the_chart_strip_and_capital_structure_bindings() -> None:
    preset = next(p for p in pathways() if p.id == "earnings_update")
    report = build(_on_pathway("earnings_update"), preset, CREDIT_SNAPSHOT_MAPS)
    listed = {(item.module_id, item.block_id) for item in report.unplaced}
    # The KPI dashboard sits in FP 02's metric strip, so FP 01's strip is not "outside" it.
    assert ("CP-1", "model-chart-strip") not in listed
    assert ("CP-1", "capital-structure") in listed
    credit = build(credit_snapshot_view(), CREDIT, CREDIT_SNAPSHOT_MAPS)
    assert not credit.unplaced


def test_unplaced_bindings_reach_the_data_island() -> None:
    preset = next(p for p in pathways() if p.id == "earnings_update")
    view = _on_pathway("earnings_update")
    island = json.loads(_island(render(view, build(view, preset, CREDIT_SNAPSHOT_MAPS))))
    unplaced = island["report"]["unplaced"]
    assert "capital-structure" in {item["block_id"] for item in unplaced}
    # The block's head travels with its id, for the Limitations page.
    assert {"Capital structure"} == {
        item["title"] for item in unplaced if item["block_id"] == "capital-structure"
    }


def test_the_withheld_call_token_is_mapped_like_the_block_state() -> None:
    earnings = next(p for p in pathways() if p.id == "earnings_update")
    idle = empty_view(run("earnings_update"))
    report = build(idle, earnings, ())
    assert report.call_withheld == "outside_pathway"
    html = render(idle, report)
    assert json.loads(_island(html))["report"]["call_withheld"] == "outside"
    assert "outside_pathway" not in html


def test_build_fails_closed_for_a_fact_producer_without_a_shipped_map() -> None:
    from deploy_vii.bindings.shipped import SHIPPED_MAPS

    view = synthetic_view()
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")
    extra = ModuleView(
        module_id="CP-2A",
        title="Downside pathway",
        aliases=(),
        status="candidate",
        facts=cp1.facts,
        artifact_sha256="d" * 64,
    )
    swapped = view.model_copy(
        update={"modules": tuple(extra if m.module_id == "CP-2A" else m for m in view.modules)}
    )
    assert "CP-2A" not in {m.module_id for m in SHIPPED_MAPS}
    with pytest.raises(ValueError, match=r"unbound fact CP-2A/"):
        build(swapped, CREDIT, SHIPPED_MAPS)
    with pytest.raises(ValueError, match=r"unbound fact CP-2A/"):
        render(swapped)
