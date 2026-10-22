"""Binding maps and the provenance validator: unbound and doubly bound facts are rejected."""

from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from deploy_vii.bindings import Binding, BindingMap, validate_bindings
from deploy_vii.bindings.cp0 import CP0
from deploy_vii.bindings.cp1 import CP1
from deploy_vii.canonical_tables import COLUMNS
from deploy_vii.contracts import Fact, ModuleView, View
from deploy_vii.cp1_workflow import cp1_register_preview
from deploy_vii.delivery import cp0_view
from deploy_vii.model_interface import SCHEMAS
from deploy_vii.readiness import build_readiness
from deploy_vii.report_view import FactCoord, pathways
from tests.product.test_readiness import readiness_fixture
from tests.product.test_register_view import completed
from tests.product.test_render import synthetic_view


def with_facts(module_id: str, facts: tuple[Fact, ...], status: str = "candidate") -> View:
    base = synthetic_view()
    original = next(m for m in base.modules if m.module_id == module_id)
    module = ModuleView(
        module_id=module_id,
        title=original.title,
        aliases=original.aliases,
        status=status,  # type: ignore[arg-type]
        facts=facts,
        artifact_sha256="b" * 64,
    )
    return View.model_validate_json(
        base.model_copy(
            update={
                "modules": tuple(module if m.module_id == module_id else m for m in base.modules)
            }
        ).model_dump_json()
    )


def fact(fact_id: str, table: str = "T4.4", row: str = "r1") -> Fact:
    return Fact(fact_id=fact_id, label=fact_id, table_id=table, row_id=row, text="x")


def binding(
    slot: str, table: str | None = "T4.4", row: str | None = None, fid: str | None = None
) -> Binding:
    return Binding(
        fact_coord=FactCoord(module_id="CP-1", table_id=table, row_id=row, fact_id=fid),
        block_id="financials-credit-metrics",
        cell_slot=slot,
        unit_class="text",
    )


def test_unbound_fact_is_rejected() -> None:
    view = with_facts("CP-1", (fact("a"), fact("b", table="T9.9")))
    issues = validate_bindings(view, (BindingMap(module_id="CP-1", entries=(binding("is"),)),))
    assert len(issues) == 1
    assert (
        "unbound" in issues[0] and "CP-1" in issues[0] and "T9.9" in issues[0] and "b" in issues[0]
    )


def test_doubly_bound_fact_is_rejected() -> None:
    view = with_facts("CP-1", (fact("a"), fact("b", row="r2")))
    maps = (
        BindingMap(
            module_id="CP-1",
            entries=(binding("table"), binding("exact-row", row="r2", fid="b")),
        ),
    )
    issues = validate_bindings(view, maps)
    assert len(issues) == 1 and "doubly bound" in issues[0] and "'b'" in issues[0]


def test_two_bindings_to_one_slot_are_rejected_even_when_they_match_nothing() -> None:
    maps = (
        BindingMap(module_id="CP-1", entries=(binding("slot", "T4.4"), binding("slot", "T4.5"))),
    )
    issues = validate_bindings(with_facts("CP-1", ()), maps)
    assert len(issues) == 1 and "slot" in issues[0]


def test_two_maps_for_one_module_are_rejected() -> None:
    maps = (
        BindingMap(module_id="CP-1", entries=(binding("a"),)),
        BindingMap(module_id="CP-1", entries=(binding("b", "T4.5"),)),
    )
    issues = validate_bindings(with_facts("CP-1", (fact("a"),)), maps)
    assert len(issues) == 1 and "more than one" in issues[0]


def test_module_without_a_map_has_every_fact_unbound() -> None:
    issues = validate_bindings(with_facts("CP-1", (fact("a"), fact("b"))), ())
    assert len(issues) == 2 and all("unbound" in message for message in issues)


@pytest.mark.parametrize("status", ["unrun", "blocked", "stale", "rejected"])
def test_modules_that_show_no_facts_are_not_checked(status: str) -> None:
    base = synthetic_view()
    module = ModuleView(module_id="CP-1", title="t", aliases=(), status=status)  # type: ignore[arg-type]
    view = View.model_validate_json(
        base.model_copy(
            update={"modules": tuple(module if m.module_id == "CP-1" else m for m in base.modules)}
        ).model_dump_json()
    )
    assert validate_bindings(view, ()) == ()


@pytest.mark.parametrize("status", ["accepted", "restricted", "candidate"])
def test_modules_that_show_facts_are_checked(status: str) -> None:
    view = with_facts("CP-1", (fact("a"),), status)
    assert len(validate_bindings(view, ())) == 1


def test_a_map_must_stay_in_its_module() -> None:
    other = Binding(
        fact_coord=FactCoord(module_id="CP-0", table_id="T1"),
        block_id="header",
        cell_slot="x",
        unit_class="text",
    )
    with pytest.raises(ValidationError):
        BindingMap(module_id="CP-1", entries=(other,))


def test_an_all_wildcard_coordinate_is_rejected() -> None:
    # Only module_id set would match every fact of the module: a hidden catch-all.
    with pytest.raises(ValidationError, match="wildcard"):
        Binding(
            fact_coord=FactCoord(module_id="CP-1"),
            block_id="b",
            cell_slot="s",
            unit_class="text",
        )
    assert binding("s", table="T4.4").fact_coord.table_id == "T4.4"
    assert binding("s", table=None, fid="f").fact_coord.fact_id == "f"


def test_cp0_readiness_binds_without_errors() -> None:
    pack, review = readiness_fixture()
    module = build_readiness(pack, review)
    view = cp0_view(pack, module, accepted=False)
    assert module.facts
    assert validate_bindings(view, (CP0,)) == ()


def test_cp0_review_without_gaps_binds_too() -> None:
    pack, review = readiness_fixture()
    module = build_readiness(pack, review.model_copy(update={"gaps": ()}))
    assert any(f.table_id == "T5" and f.row_id == "review" for f in module.facts)
    assert validate_bindings(cp0_view(pack, module, accepted=False), (CP0,)) == ()


@pytest.fixture(scope="module", params=[True, False], ids=["partial", "complete"])
def cp1_view(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> View:
    root: Path = tmp_path_factory.mktemp("cp1")
    store, done = completed(root, partial=request.param)
    path = cp1_register_preview(store, done.ticket_id, root / "report")
    return View.model_validate_json((path.parent / "view.json").read_bytes())


def test_cp1_candidate_registers_bind_without_errors(cp1_view: View) -> None:
    cp1 = next(m for m in cp1_view.modules if m.module_id == "CP-1")
    assert cp1.status == "candidate" and cp1.facts
    assert validate_bindings(cp1_view, (CP1,)) == ()


def test_cp1_map_binds_every_declared_table() -> None:
    bound = {e.fact_coord.table_id for e in CP1.entries}
    declared = set(COLUMNS) | set(SCHEMAS)
    assert declared <= bound


def test_cp1_map_binds_every_table_id_any_producer_emits(cp1_view: View) -> None:
    """Every producer's schema, plus the tables an actual preview emitted, has a binding."""
    from deploy_vii.narrative_projection import SCHEMAS as NARRATIVE_SCHEMAS

    bound = {e.fact_coord.table_id for e in CP1.entries}
    producers = {
        "canonical_tables": set(COLUMNS),
        "model_interface": set(SCHEMAS),
        "narrative_projection": set(NARRATIVE_SCHEMAS),
        "statement_view": {"T4.4", "T4.5", "T4.6"},
    }
    for producer, ids in producers.items():
        assert ids <= bound, (producer, sorted(ids - bound))
    cp1 = next(m for m in cp1_view.modules if m.module_id == "CP-1")
    emitted = {f.table_id for f in cp1.facts} | {t.table_id for t in cp1.tables}
    assert emitted and emitted <= bound, sorted(emitted - bound)


def test_shipped_maps_use_each_slot_once_and_stay_in_their_module() -> None:
    for module_map in (CP0, CP1):
        slots = Counter((e.block_id, e.cell_slot) for e in module_map.entries)
        assert max(slots.values()) == 1
        assert {e.fact_coord.module_id for e in module_map.entries} == {module_map.module_id}


def test_fp01_chart_strip_and_tabbed_capital_structure_bindings() -> None:
    from deploy_vii.bindings import RAIL_DESTINATIONS

    by_table = {
        e.fact_coord.table_id: e
        for e in CP1.entries
        if e.block_id not in {"ebitda-adjustments", "metric-strip"}  # FP 02 second placements
    }
    # FP 01 has no separate metric strip: the KPI dashboard feeds the Model chart strip.
    assert by_table["T4.10"].block_id == "model-chart-strip"
    # Capital structure is tabbed, in the order FP 01 prints the tabs.
    assert [e.title for e in CP1.entries if e.block_id == "capital-structure"] == [
        "Capital structure",
        "EBITDA adjustments",
        "Transaction and new debt",
    ]
    assert by_table["T4.17"].block_id == "capital-structure"
    # Narrative registers the preview carries are accounted for under the rail destinations
    # (bookkeeping: the module page shows them, not these block facts); they never fall out.
    assert by_table["evidence-trace"].block_id == "evidence"
    assert by_table["required-stories"].block_id == "limitations"
    # Every other target is a rail destination, named once as a constant.
    assert {e.block_id for e in CP0.entries} <= RAIL_DESTINATIONS
    assert RAIL_DESTINATIONS == {"evidence", "limitations", "header"}
    assert Binding.model_validate_json(by_table["T4.17"].model_dump_json()) == by_table["T4.17"]


def _on_pathway(view: View, pathway: str) -> View:
    return View.model_validate_json(
        view.model_copy(
            update={"run": view.run.model_copy(update={"pathway": pathway})}
        ).model_dump_json()
    )


def _placement(table: str, block: str, slot: str) -> Binding:
    return Binding(
        fact_coord=FactCoord(module_id="CP-1", table_id=table),
        block_id=block,
        cell_slot=slot,
        unit_class="text",
    )


def test_a_register_may_be_placed_once_per_pathway_composition() -> None:
    """T4.17 feeds FP 01's capital-structure tab and FP 02's ebitda-adjustments block."""
    both = BindingMap(
        module_id="CP-1",
        entries=(
            _placement("T4.17", "capital-structure", "bridge"),
            _placement("T4.17", "ebitda-adjustments", "bridge"),
        ),
    )
    fact_ = fact("a", table="T4.17")
    # Each Pathway composes exactly one of the two blocks: one placement, not a double binding.
    for pathway in ("credit_snapshot", "earnings_update"):
        view = _on_pathway(with_facts("CP-1", (fact_,)), pathway)
        assert validate_bindings(view, (both,)) == (), pathway


def test_two_placements_inside_one_composition_are_still_doubly_bound() -> None:
    twice = BindingMap(
        module_id="CP-1",
        entries=(
            _placement("T4.17", "capital-structure", "bridge"),
            _placement("T4.17", "model-chart-strip", "bridge"),  # FP 01 composes both
        ),
    )
    issues = validate_bindings(with_facts("CP-1", (fact("a", table="T4.17"),)), (twice,))
    assert len(issues) == 1 and "doubly bound" in issues[0]
    # A rail destination is composed in every Pathway, so it counts as a placement too.
    rail = BindingMap(
        module_id="CP-1",
        entries=(
            _placement("T4.17", "capital-structure", "bridge"),
            _placement("T4.17", "evidence", "bridge"),
        ),
    )
    assert len(validate_bindings(with_facts("CP-1", (fact("a", table="T4.17"),)), (rail,))) == 1


def test_the_same_block_twice_is_doubly_bound_even_outside_the_composition() -> None:
    outside = BindingMap(
        module_id="CP-1",
        entries=(
            _placement("T4.17", "ebitda-adjustments", "one"),
            _placement("T4.17", "ebitda-adjustments", "two"),
        ),
    )
    issues = validate_bindings(with_facts("CP-1", (fact("a", table="T4.17"),)), (outside,))
    assert len(issues) == 1 and "doubly bound" in issues[0]


def test_cp1_places_the_adjustment_bridge_and_kpi_register_twice_by_pathway() -> None:
    by_block = {(e.fact_coord.table_id, e.block_id): e for e in CP1.entries}
    assert ("T4.17", "capital-structure") in by_block
    assert ("T4.17", "ebitda-adjustments") in by_block
    assert ("T4.10", "model-chart-strip") in by_block
    assert ("T4.10", "metric-strip") in by_block
    for pathway_ in pathways():
        composed = {e.block_id for e in CP1.entries if e.block_id in pathway_.blocks}
        for table in ("T4.17", "T4.10"):
            placed = [b for (t, b) in by_block if t == table and b in composed]
            assert len(placed) <= 1, (pathway_.id, table, placed)
