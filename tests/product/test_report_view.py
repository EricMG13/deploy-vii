"""Report view model: contracts, status words and the C#/K#/G# index."""

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from deploy_vii.contracts import Citation, Fact, ModuleView, Run, View
from deploy_vii.registry import canonical, dependencies
from deploy_vii.report_view import (
    Block,
    CallItem,
    Cell,
    ChartMark,
    ChartSpec,
    FactCoord,
    FactRefs,
    Line,
    Passport,
    PassportField,
    Pathway,
    ReportIndex,
    ReportView,
    Row,
    TextRun,
    build_index,
    pathways,
    status_word,
)
from tests.product.test_render import synthetic_view

# Independent oracle: decision 0004 section 6 table.
STATUS_WORDS = {
    "accepted": "Pass",
    "restricted": "With limitations",
    "blocked": "Blocked",
    "unrun": "Not run",
    "not_in_pathway": "Not in this Pathway",
    "stale": "Stale, rerun required",
    "candidate": "Candidate",
}


@pytest.mark.parametrize(("status", "word"), STATUS_WORDS.items())
def test_every_status_has_an_icon_and_a_word(status: str, word: str) -> None:
    icon, shown = status_word(status)  # type: ignore[arg-type]
    assert shown == word and icon


def test_status_icons_are_distinct_so_colour_is_never_the_only_cue() -> None:
    icons = [status_word(s)[0] for s in STATUS_WORDS]  # type: ignore[arg-type]
    assert len(set(icons)) == len(icons)


@pytest.mark.parametrize("status", ["rejected", "bogus"])
def test_rejected_and_unknown_status_are_never_displayed(status: str) -> None:
    with pytest.raises(ValueError, match=r"never displayed|Unknown"):
        status_word(status)  # type: ignore[arg-type]


def cell(**over: object) -> Cell:
    base: dict[str, object] = {
        "text": "11,648",
        "prov": "cited",
        "ref_id": "C1",
        "gap_ref": None,
        "unit_class": "amount",
        "state": "known",
    }
    return Cell(**{**base, **over})


def test_cell_rules() -> None:
    assert cell().text == "11,648"
    assert cell(text="∅ G8", prov="gap", ref_id=None, gap_ref="G8", state="gap").gap_ref == "G8"
    for bad in (
        {"text": "null"},
        {"text": "NULL"},
        {"text": ""},
        {"ref_id": None},  # cited without a reference
        {"ref_id": "K1"},  # prefix must match provenance
        {"state": "gap"},  # gap state needs gap prov and gap_ref
        {"prov": "none"},  # reference without provenance
        {"gap_ref": "G1"},  # known cell with a gap reference
    ):
        with pytest.raises(ValidationError):
            cell(**bad)


def test_text_run_rules() -> None:
    assert TextRun(text="x", kind="text", ref_id=None).kind == "text"
    assert TextRun(text="1.0x", kind="fig", ref_id="K2").ref_id == "K2"
    assert TextRun(text="∅ G8", kind="gap", ref_id="G8").ref_id == "G8"
    assert TextRun(text="note", kind="pen", ref_id=None).kind == "pen"
    for kind, ref in (("fig", None), ("fig", "G1"), ("gap", "C1"), ("gap", None), ("text", "C1")):
        with pytest.raises(ValidationError):
            TextRun(text="x", kind=kind, ref_id=ref)  # type: ignore[arg-type]


def test_null_spellings_are_refused_in_figures_but_genuine_text_is_allowed() -> None:
    # A text-class cell or a plain text run may genuinely read "None" (a covenant list, say).
    assert cell(text="None", unit_class="text", prov="none", ref_id=None).text == "None"
    assert TextRun(text="None", kind="text", ref_id=None).text == "None"
    # ...but "null" and "nan" are leaked-null spellings even there, in any case.
    for leaked in ("null", "NULL", " NaN ", "nan"):
        with pytest.raises(ValidationError):
            cell(text=leaked, unit_class="text", prov="none", ref_id=None)
        with pytest.raises(ValidationError):
            TextRun(text=leaked, kind="text", ref_id=None)
    for spelling in ("null", "None", "NaN", " nan "):
        with pytest.raises(ValidationError):
            cell(text=spelling)  # amount cell
        with pytest.raises(ValidationError):
            TextRun(text=spelling, kind="fig", ref_id="K1")
        with pytest.raises(ValidationError):
            CallItem(kind="fact", label="x", value_text=spelling)
    # Text is still never blank, in any class.
    with pytest.raises(ValidationError):
        cell(text=" ", unit_class="text", prov="none", ref_id=None)
    with pytest.raises(ValidationError):
        TextRun(text=" ", kind="text", ref_id=None)


def test_reference_ids_must_be_whole_not_just_prefixed() -> None:
    for bad in ("Cxyz", "C", "C1x", "C-1"):
        with pytest.raises(ValidationError):
            cell(ref_id=bad)
        with pytest.raises(ValidationError):
            TextRun(text="1x", kind="fig", ref_id=bad)
    assert cell(ref_id="C12").ref_id == "C12"


def grid(block_id: str = "b1", **over: object) -> Block:
    base: dict[str, object] = {
        "block_id": block_id,
        "title": "Capital structure",
        "owner": "CP-1",
        "fig_id": None,
        "tags": (),
        "state": "populated",
        "kind": "dense",
        "columns": ("US$ m",),
        "rows": (Row(row_id="r1", label="Cash", cells=(cell(),)),),
        "full_analysis_route": "#CP-1",
    }
    return Block(**{**base, **over})


def test_block_state_and_content_must_agree() -> None:
    assert grid().state == "populated"
    with pytest.raises(ValidationError):
        grid(rows=())  # populated needs content
    with pytest.raises(ValidationError):
        grid(kind="prose")  # prose needs lines, not rows
    with pytest.raises(ValidationError):
        grid(state="not_run")  # non-populated carries no content and needs a note
    with pytest.raises(ValidationError):
        grid(state="bogus")
    honest = grid(state="not_run", rows=(), note="CP-3 did not run")
    assert honest.rows == ()
    prose = grid(
        kind="prose",
        columns=(),
        rows=(),
        lines=(Line(runs=(TextRun(text="x", kind="text", ref_id=None),)),),
    )
    assert prose.lines


def test_chart_requires_a_non_chart_table_twin() -> None:
    twin = grid("twin", state="absent", rows=(), note="No rows: nothing to chart.")
    chart = ChartSpec(kind="line", series=("Total",), table_twin=twin, marks=())
    block = grid("c1", kind="chart", columns=(), rows=(), chart=chart)
    assert block.chart is chart
    with pytest.raises(ValidationError):
        ChartSpec(
            kind="line",
            series=("Total",),
            table_twin=grid("c2", kind="chart", columns=(), rows=(), chart=chart),
            marks=(),
        )


def passport(ref_id: str = "C1", kind: str = "cited") -> Passport:
    return Passport(
        ref_id=ref_id,
        kind=kind,
        fields=(PassportField(name="Source", value="s"),),  # type: ignore[arg-type]
    )


def test_passport_kind_must_match_its_id_prefix() -> None:
    with pytest.raises(ValidationError):
        passport("C1", "gap")
    with pytest.raises(ValidationError):
        passport("X1", "cited")


def pathway(*blocks: str) -> Pathway:
    return Pathway(
        id="credit_snapshot",
        title="Credit Snapshot",
        question="Can the issuer carry its debt?",
        requested_modules=("CP-0", "CP-1"),
        blocks=blocks,
    )


def test_report_view_checks_references_and_block_composition() -> None:
    ok = ReportView(
        pathway=pathway("b1"),
        call=(),
        blocks=(grid(),),
        passports=(passport(),),
        index=ReportIndex(facts=()),
    )
    assert ok.schema_version == "report-view/1"
    assert ok.passport("C1").kind == "cited"
    with pytest.raises(KeyError):
        ok.passport("C9")
    base: dict[str, object] = {
        "pathway": pathway("b1"),
        "call": (),
        "blocks": (grid(),),
        "passports": (passport(),),
        "index": ReportIndex(facts=()),
    }
    bad_cases = (
        {"passports": ()},  # the cell's C1 has no passport
        {"passports": (passport(), passport())},  # duplicate id
        {"pathway": pathway("b1", "b2")},  # composition names a missing block
        {"blocks": (grid(), grid())},  # duplicate block ids
        {
            "index": ReportIndex(
                facts=(
                    FactRefs(
                        coord=FactCoord(module_id="CP-1", table_id="t", row_id="r", fact_id="f"),
                        ref_ids=("C7",),
                    ),
                )
            )
        },  # index points to a missing passport
        {"schema_version": "report-view/0"},
    )
    for override in bad_cases:
        with pytest.raises((ValidationError, ValueError)):
            ReportView(**{**base, **override})


def fact(fact_id: str, **over: object) -> Fact:
    base: dict[str, object] = {
        "fact_id": fact_id,
        "label": fact_id,
        "table_id": "t1",
        "row_id": fact_id,
        "field": "value",
    }
    return Fact(**{**base, **over})


def view_with(facts: tuple[Fact, ...], case_kind: str = "public") -> View:
    base = synthetic_view()
    cp1 = next(m for m in base.modules if m.module_id == "CP-1")
    module = ModuleView(
        module_id="CP-1",
        title=cp1.title,
        aliases=cp1.aliases,
        status="candidate",
        facts=facts,
        artifact_sha256="b" * 64,
    )
    return View.model_validate_json(
        base.model_copy(
            update={
                "run": base.run.model_copy(update={"case_kind": case_kind}),
                "modules": tuple(module if m.module_id == "CP-1" else m for m in base.modules),
            }
        ).model_dump_json()
    )


A = Citation(source_id="s1", source_sha256="a" * 64, locator="p1", quote="Cash 5")
B = Citation(source_id="s1", source_sha256="a" * 64, locator="p2", quote="Debt 9")


def test_index_allocates_stable_report_wide_ids_with_a_reverse_index() -> None:
    facts = (
        fact("a", text="x", citations=(A,)),
        fact("b", text="y", citations=(A, B)),  # A is shared, not re-numbered
        fact(
            "c",
            amount=Decimal("2"),
            unit="x",
            period="FY25",
            calculation_id="calc-1",
            citations=(B,),
        ),
        fact("d", status="missing", limitation="not disclosed"),
        fact("e", text="z"),  # known without citation or calculation: no id
    )
    passports, index = build_index(view_with(facts))
    assert [(p.ref_id, p.kind) for p in passports] == [
        ("C1", "cited"),
        ("C2", "cited"),
        ("K1", "calculated"),
        ("G1", "gap"),
    ]
    refs = {r.coord.fact_id: r.ref_ids for r in index.facts}
    assert refs == {"a": ("C1",), "b": ("C1", "C2"), "c": ("C2", "K1"), "d": ("G1",)}
    assert {r.coord.module_id for r in index.facts} == {"CP-1"}
    gap = next(p for p in passports if p.kind == "gap")
    assert ("Reason", "not disclosed") in {(f.name, f.value) for f in gap.fields}
    # deterministic: a second call gives identical output
    assert build_index(view_with(facts)) == (passports, index)


def test_synthetic_runs_mark_cited_values_as_synthetic() -> None:
    passports, _ = build_index(view_with((fact("a", text="x", citations=(A,)),), "synthetic"))
    assert [(p.ref_id, p.kind) for p in passports] == [("S1", "synthetic")]


def test_index_over_the_real_synthetic_view_validates_in_a_report_view() -> None:
    passports, index = build_index(synthetic_view())
    assert passports and index.facts
    ReportView(
        pathway=pathway(),
        call=(),
        blocks=(),
        passports=passports,
        index=index,
    )


def test_remaining_contract_rules() -> None:
    with pytest.raises(ValidationError):
        Line(runs=())
    with pytest.raises(ValidationError):  # gap provenance outside a gap state
        cell(prov="gap", ref_id=None, gap_ref=None)
    with pytest.raises(ValidationError):  # gap state with settled provenance
        cell(text="∅ G8", prov="cited", ref_id="C1", gap_ref="G8", state="gap")
    with pytest.raises(ValidationError):  # non-populated block without its note
        grid(state="not_run", rows=(), note=None)
    with pytest.raises(ValidationError):  # malformed gap reference
        cell(text="x", prov="gap", ref_id=None, gap_ref="8", state="gap")
    with pytest.raises(ValidationError):  # cells must match the declared columns
        grid(columns=("a", "b"))
    ok = CallItem(kind="scale", label="Credit Score", value_text="3 - Fair", meter=3)
    assert ok.meter == 3
    for bad in (
        {"kind": "scale", "meter": None},
        {"kind": "scale", "meter": 6},
        {"kind": "fact", "meter": 2},
        {"kind": "fact", "value_text": "null"},
    ):
        with pytest.raises(ValidationError):
            CallItem(**{"label": "x", "value_text": "v", "meter": None, **bad})  # type: ignore[arg-type]


def test_report_view_collects_references_from_every_surface() -> None:
    twin = grid("twin", rows=(Row(row_id="r", label="x", cells=(cell(ref_id="C2"),)),))
    mark = ChartMark(series="s", label="l", text="11,648", ref_id="C3", value=Decimal("11648"))
    chart_block = grid(
        "c1",
        kind="chart",
        columns=(),
        rows=(),
        chart=ChartSpec(kind="line", series=("s",), table_twin=twin, marks=(mark,)),
    )
    prose = grid(
        "p1",
        kind="prose",
        columns=(),
        rows=(),
        lines=(Line(runs=(TextRun(text="1x", kind="fig", ref_id="K1"),)),),
    )
    args = {
        "pathway": pathway("c1", "p1"),
        "blocks": (chart_block, prose),
        "index": ReportIndex(facts=()),
    }
    full = tuple(
        passport(r, k) for r, k in (("C2", "cited"), ("C3", "cited"), ("K1", "calculated"))
    )
    call = (CallItem(kind="fact", label="x", value_text="1", ref_id="C9"),)
    ReportView(call=(), passports=full, **args)  # type: ignore[arg-type]
    for dropped in range(3):  # each surface alone makes a reference dangle
        with pytest.raises(ValueError, match="without a passport"):
            ReportView(call=(), passports=full[:dropped] + full[dropped + 1 :], **args)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="without a passport"):
        ReportView(call=call, passports=full, **args)  # type: ignore[arg-type]


# --- Pathway presets (decision 0009) -------------------------------------------------------

DESIGN = Path(__file__).resolve().parents[2] / "design" / "reference"
FRONT_PAGES = {
    "credit_snapshot": "rbot-fp-01-credit-snapshot.dc.html",
    "earnings_update": "rbot-fp-02-earnings-update.dc.html",
    "relative_value": "rbot-fp-03-relative-value.dc.html",
    "covenant_refinancing": "rbot-fp-04-covenant-refinancing.dc.html",
    "distressed_restructuring": "rbot-fp-05-distressed-restructuring.dc.html",
    "portfolio_decision": "rbot-fp-06-portfolio-decision.dc.html",
}
# Independent table: the module sets exactly as the M3 brief lists them (Task C).
BRIEF_MODULES = {
    "credit_snapshot": ("CP-0", "CP-1", "CP-1A", "CP-2", "CP-4", "CP-3", "CP-5", "CP-6"),
    "earnings_update": ("CP-0", "CP-1", "CP-1B", "CP-1D", "CP-5"),
    "relative_value": (
        *("CP-0", "CP-1", "CP-1C", "CP-2", "CP-2D"),
        *("CP-3", "CP-3C", "CP-3D", "CP-5"),
    ),
    "covenant_refinancing": (
        *("CP-0", "CP-1", "CP-1A", "CP-2", "CP-2D"),
        *("CP-4", "CP-3C", "CP-5"),
    ),
    "distressed_restructuring": (
        *("CP-0", "CP-1", "CP-1A", "CP-2", "CP-2A"),
        *("CP-2G", "CP-2H", "CP-4", "CP-4C", "CP-5"),
    ),
    "portfolio_decision": ("CP-0", "CP-1", "CP-2", "CP-3", "CP-5", "CP-6", "CP-8"),
}


def design_cards() -> dict[str, tuple[str, str]]:
    """Title and question per Pathway card of ``rbot-report.dc.html``."""
    text = (DESIGN / "rbot-report.dc.html").read_text(encoding="utf-8")
    cards = re.findall(r"title: '([^']+)', q: '([^']+)'", text)
    assert len(cards) == 6
    return {pid: card for pid, card in zip(FRONT_PAGES, cards, strict=True)}


def design_heads(page: str) -> list[str]:
    """Block heads of a Front Page outline, 'The call' excluded (the call band is not a block)."""
    text = (DESIGN / page).read_text(encoding="utf-8")
    start = text.index("S.outline(")
    outline = text[start : text.index(", 0)", start)]
    outline = outline.rsplit(" : [", 1)[-1]  # FP 05: the gate-unclear composition is the default
    heads = re.findall(r"'([^']+)'", outline)
    assert heads[0] == "The call"
    return heads[1:]


def test_pathway_presets_cover_six_front_pages() -> None:
    presets = pathways()
    assert tuple(p.id for p in presets) == tuple(FRONT_PAGES)
    cards = design_cards()
    for preset in presets:
        assert (preset.title, preset.question) == cards[preset.id]
        assert preset.requested_modules == BRIEF_MODULES[preset.id]
        # Block composition follows the Front Page's outline: same order, same count, and
        # each id names words of its head (the head is prose, the id is its stable slug).
        heads = design_heads(FRONT_PAGES[preset.id])
        assert len(preset.blocks) == len(heads) == len(set(preset.blocks))
        for block_id, head in zip(preset.blocks, heads, strict=True):
            assert set(block_id.split("-")) <= set(re.findall(r"[a-z]+", head.lower())), block_id
        # Every requested module is a canonical id and the set plans without a cycle.
        assert all(canonical(m) == m for m in preset.requested_modules)
        assert set(preset.requested_modules) <= set(dependencies(preset.requested_modules))


def test_pathway_blocks_agree_with_the_shipped_bindings() -> None:
    from deploy_vii.bindings import RAIL_DESTINATIONS
    from deploy_vii.bindings.cp0 import CP0
    from deploy_vii.bindings.cp1 import CP1

    credit = next(p for p in pathways() if p.id == "credit_snapshot")
    bound = {entry.block_id for entry in CP1.entries}
    # Bindings to Front Page blocks must name blocks of the Credit Snapshot composition; the
    # only other targets are the rail destinations (Evidence, Limitations, the issuer header).
    assert RAIL_DESTINATIONS == {"evidence", "limitations", "header"}
    assert {"financials-credit-metrics", "capital-structure", "model-chart-strip"} <= set(
        credit.blocks
    )
    assert bound - set(credit.blocks) <= RAIL_DESTINATIONS
    assert {e.block_id for e in CP0.entries} <= RAIL_DESTINATIONS
    # FP 01 has no separate metric strip: it stays in the Earnings Update composition only.
    assert "metric-strip" not in bound and "metric-strip" not in credit.blocks
    earnings = next(p for p in pathways() if p.id == "earnings_update")
    assert "metric-strip" in earnings.blocks


def test_portfolio_fit_block_is_present_though_it_has_no_module_yet() -> None:
    # Plan M10 owns Portfolio Fit; until then the block shows its honest state.
    decision = next(p for p in pathways() if p.id == "portfolio_decision")
    assert "portfolio-fit" in decision.blocks


def run(**over: object) -> Run:
    base: dict[str, object] = {
        "run_id": "r",
        "issuer_id": "i",
        "issuer_name": "Issuer",
        "as_of": date(2026, 10, 21),
        "case_kind": "synthetic",
    }
    return Run(**{**base, **over})  # type: ignore[arg-type]


def test_run_schema_2_defaults_to_credit_snapshot() -> None:
    default = run()
    assert default.schema_version == "run/2"
    assert default.pathway == "credit_snapshot"
    assert default.requested_modules == BRIEF_MODULES["credit_snapshot"]
    # Each Pathway carries its own requested set unless the caller overrides it.
    for pathway_id, modules in BRIEF_MODULES.items():
        assert run(pathway=pathway_id).requested_modules == modules
    assert run(pathway="earnings_update", requested_modules=("CP-0",)).requested_modules == (
        "CP-0",
    )
    # The pathway survives a JSON round trip and the old schema is refused, not upgraded.
    again = Run.model_validate_json(run(pathway="relative_value").model_dump_json())
    assert again.pathway == "relative_value"
    assert again.requested_modules == BRIEF_MODULES["relative_value"]
    old = json.loads(default.model_dump_json()) | {"schema_version": "run/1"}
    with pytest.raises(ValidationError, match="run/2"):
        Run.model_validate(old)
    with pytest.raises(ValidationError):  # a Run asks for at least one module
        run(requested_modules=())
    with pytest.raises(ValidationError):
        run(pathway="full_credit_assessment")


# --- shell support: family data, navigator rows, idle Front Page, chart contracts ----------------

# Independent oracle: the design's FAMC/FAMILY literals (lib/shell.js lines 26-27), spelled here.
DESIGN_FAMILY = {"CP-0": "sources", "CP-1": "financials", "CP-4C": "recovery", "CP-6": "portfolio"}
DESIGN_COLORS = {"sources": "#9AA0B4", "financials": "#0017E5", "recovery": "#B3261E"}


def test_family_data_matches_the_design_literals() -> None:
    from deploy_vii.report_view import FAMILY_COLORS, MODULE_FAMILY, family_color

    for module_id, family in DESIGN_FAMILY.items():
        assert MODULE_FAMILY[module_id] == family
    for family, color in DESIGN_COLORS.items():
        assert FAMILY_COLORS[family] == color
    assert len(MODULE_FAMILY) == 19 and len(FAMILY_COLORS) == 11
    assert family_color("CP-1") == "#0017E5"
    assert family_color("CP-OS") == "#9AA0B4"  # an uncoded module falls back to neutral grey


def test_status_display_never_returns_the_internal_token() -> None:
    from deploy_vii.report_view import status_display

    assert status_display("not_in_pathway") == ("na", "Not in this Pathway")
    assert status_display("unrun") == ("unrun", "Not run")
    for status in STATUS_WORDS:
        glyph, word = status_display(status)  # type: ignore[arg-type]
        assert "_" not in glyph and glyph and word == STATUS_WORDS[status]
    with pytest.raises(ValueError):
        status_display("rejected")


def test_navigator_numbers_the_pathway_and_leaves_the_rest_unnumbered() -> None:
    from deploy_vii.contracts import Run
    from deploy_vii.render import empty_view
    from deploy_vii.report_view import navigator

    run = Run(
        run_id="n",
        issuer_id="i",
        issuer_name="I",
        as_of=date(2026, 10, 21),
        case_kind="synthetic",
        pathway="earnings_update",
    )
    rows = navigator(empty_view(run))
    inside = [row for row in rows if row.in_pathway]
    assert [row.number for row in inside] == list(range(1, len(inside) + 1))
    assert {row.word for row in inside} == {"Not run"}
    assert all(
        row.number is None and row.word == "Not in this Pathway"
        for row in rows
        if not row.in_pathway
    )
    assert {row.module_id for row in inside} == set(dependencies(run.requested_modules))


def test_chart_points_are_unique_and_belong_to_a_series() -> None:
    twin = grid("twin")
    one = ChartMark(series="s", label="FY", text="1", ref_id="C1")
    with pytest.raises(ValidationError, match="cannot repeat"):
        ChartSpec(kind="line", series=("s",), table_twin=twin, marks=(one, one))
    stray = ChartMark(series="other", label="FY", text="1", ref_id="C1")
    with pytest.raises(ValidationError, match="not a chart series"):
        ChartSpec(kind="line", series=("s",), table_twin=twin, marks=(stray,))


def test_block_state_words_reuse_the_status_words() -> None:
    from deploy_vii.report_view import block_state_display

    shown = block_state_display()
    assert shown["not_run"] == ("unrun", "Not run")
    assert shown["blocked"] == ("blocked", "Blocked")
    assert shown["not_in_pathway"] == ("na", "Not in this Pathway")
    assert set(shown) == {
        *("collapsed", "condition", "not_run", "not_in_pathway", "absent", "blocked")
    }


# --- fix round 1: contract-level twin parity, gap spelling, period grid, withheld call -----------


def _twin_for_texts(texts: tuple[str, ...]) -> Block:
    rows = tuple(
        Row(row_id=f"r{i}", label=f"p{i}", cells=(cell(text=text),)) for i, text in enumerate(texts)
    )
    return grid("twin", rows=rows)


def _marks() -> tuple[ChartMark, ...]:
    return (
        ChartMark(series="s", label="a", text="1", ref_id="C1", value=Decimal(1)),
        ChartMark(series="s", label="b", text="2", ref_id="C1", value=Decimal(2)),
    )


def test_table_twin_cells_must_equal_mark_texts_in_order() -> None:
    marks = _marks()
    ChartSpec(kind="line", series=("s",), table_twin=_twin_for_texts(("1", "2")), marks=marks)
    for diverging in (("1", "3"), ("2", "1"), ("1",), ("1", "2", "2")):
        with pytest.raises(ValidationError, match="table twin"):
            ChartSpec(
                kind="line", series=("s",), table_twin=_twin_for_texts(diverging), marks=marks
            )


def test_a_gap_mark_carries_the_display_gap_spelling() -> None:
    twin_gap = _twin_for_texts(("∅ G4",))
    ok = ChartMark(series="s", label="a", text="∅ G4", ref_id="G4")
    ChartSpec(kind="line", series=("s",), table_twin=twin_gap, marks=(ok,))
    for bad in (
        ChartMark(series="s", label="a", text="n/a", ref_id="G4"),
        ChartMark(series="s", label="a", text="∅ G4", ref_id="C1"),
        ChartMark(series="s", label="a", text="∅ G4"),
    ):
        with pytest.raises(ValidationError):
            ChartSpec(
                kind="line",
                series=("s",),
                table_twin=_twin_for_texts((bad.text,)),
                marks=(bad,),
            )


def test_chart_unit_is_text_or_absent_never_blank() -> None:
    twin = grid("twin", state="absent", rows=(), note="x")
    assert ChartSpec(kind="na", series=(), table_twin=twin, marks=()).unit is None
    with pytest.raises(ValidationError):
        ChartSpec(kind="na", series=(), table_twin=twin, marks=(), unit="")


def test_period_grid_structure_is_checked() -> None:
    from deploy_vii.report_view import AbsentColumn, ColumnGroup

    two = Row(row_id="r", label="x", cells=(cell(), cell(ref_id="C2")))
    base = {"kind": "period_grid", "columns": ("FY", "PF"), "rows": (two,)}
    ok = grid(
        **base,
        groups=(ColumnGroup(label="Annual", span=1), ColumnGroup(label="PF", span=1)),
        base_column=0,
        absent_columns=(AbsentColumn(column=1, reason="merger debt unstated"),),
    )
    assert ok.base_column == 0
    for bad in (
        {"groups": (ColumnGroup(label="Annual", span=1),)},  # does not cover both columns
        {"base_column": 2},
        {"absent_columns": (AbsentColumn(column=5, reason="r"),)},
        {"absent_columns": (AbsentColumn(column=1, reason="r"),) * 2},
    ):
        with pytest.raises(ValidationError):
            grid(**base, **bad)
    with pytest.raises(ValidationError):
        grid(base_column=0)  # a dense table has no base column
    with pytest.raises(ValidationError):
        ColumnGroup(label="g", span=0)


def test_a_withheld_call_shows_only_na_items() -> None:
    from deploy_vii.contracts import Run
    from deploy_vii.render import empty_view
    from deploy_vii.report_view import build, call_state

    run = Run(
        run_id="n", issuer_id="i", issuer_name="I", as_of=date(2026, 10, 21), case_kind="synthetic"
    )
    preset = next(item for item in pathways() if item.id == run.pathway)
    idle = build(empty_view(run), preset, ())
    assert call_state(idle) == ("no-judgement", None)
    fields = {name: getattr(idle, name) for name in ("pathway", "blocks", "passports", "index")}
    blocked = ReportView(call=idle.call, call_withheld="blocked", **fields)
    assert call_state(blocked) == ("blocked", ("blocked", "Blocked"))
    outside = ReportView(call=idle.call, call_withheld="outside_pathway", **fields)
    assert call_state(outside) == ("outside", ("na", "Not in this Pathway"))
    item = CallItem(kind="fact", label="x", value_text="1")
    assert call_state(ReportView(call=(item,), **fields)) == ("populated", None)
    with pytest.raises(ValidationError, match="withheld"):
        ReportView(call=(item,), call_withheld="blocked", **fields)
    with pytest.raises(ValidationError, match="withheld"):
        ReportView(call=(), call_withheld="blocked", **fields)
