"""Task 6.5: CP-1 registers in the Earnings Update blocks, the Model presets, unplaced titles."""

import pytest

from deploy_vii.contracts import PATHWAY_MODULES, View
from deploy_vii.registry import plan
from deploy_vii.report_view import (
    Block,
    Pathway,
    ReportView,
    build,
    pathway_has_model_block,
    pathways,
)
from tests.product.credit_snapshot import CREDIT_SNAPSHOT_MAPS, credit_snapshot_view


def _pathway(name: str) -> Pathway:
    return next(p for p in pathways() if p.id == name)


def _built(name: str) -> ReportView:
    view = View.model_validate_json(
        credit_snapshot_view()
        .model_copy(update={"run": credit_snapshot_view().run.model_copy(update={"pathway": name})})
        .model_dump_json()
    )
    return build(view, _pathway(name), CREDIT_SNAPSHOT_MAPS)


def _block(report: ReportView, block_id: str) -> Block:
    return next(b for b in report.blocks if b.block_id == block_id)


def test_the_earnings_update_ebitda_adjustments_hold_the_t4_17_register() -> None:
    credit = _built("credit_snapshot")
    update = _built("earnings_update")
    block = _block(update, "ebitda-adjustments")
    assert (block.title, block.owner, block.state, block.kind) == (
        "EBITDA adjustments",
        "MODEL",
        "populated",
        "dense",
    )
    tab = next(
        t for t in _block(credit, "capital-structure").tabs if t.label == "EBITDA adjustments"
    )
    # The same pack-derived cells by both placements: one register, spelled once.
    assert block.columns == tab.columns and block.scale == tab.scale == "US$ m"
    assert [(r.row_id, [c.text for c in r.cells]) for r in block.rows] == [
        (r.row_id, [c.text for c in r.cells]) for r in tab.rows
    ]
    assert all(c.ref_id for r in block.rows for c in r.cells if c.state == "known")


def test_the_earnings_update_metric_strip_is_fed_by_the_kpi_register_with_no_series_yet() -> None:
    block = _block(_built("earnings_update"), "metric-strip")
    assert (block.title, block.owner, block.state, block.kind) == (
        "Metric strip",
        "MODEL",
        "populated",
        "dense",  # a degraded strip holds its frames in `figures` and the register as a table
    )
    # FP 02 prints S.1 to S.3 (leverage, interest cover, liquidity); no producer supplies series.
    assert [(f.fig_id, f.title, f.chart.kind) for f in block.figures] == [
        ("S.1", "Leverage", "na"),
        ("S.2", "Interest cover", "na"),
        ("S.3", "Liquidity", "na"),
    ]
    assert block.note is not None and "S.1\u2013S.3" in block.note
    # The KPI register is the table the strip falls back to: the register's own rows.
    credit_strip = _block(_built("credit_snapshot"), "model-chart-strip")
    assert [(r.row_id, [c.text for c in r.cells]) for r in block.rows] == [
        (r.row_id, [c.text for c in r.cells]) for r in credit_strip.rows
    ]
    assert len(credit_strip.figures) == 4 and "S.1\u2013S.4" in (credit_strip.note or "")


def test_a_second_placement_is_not_listed_as_bound_outside_the_pathway() -> None:
    credit = _built("credit_snapshot")
    placed = {(u.module_id, u.block_id) for u in credit.unplaced}
    assert ("CP-1", "ebitda-adjustments") not in placed
    assert ("CP-1", "metric-strip") not in placed
    update = _built("earnings_update")
    listed = {(u.module_id, u.block_id): u for u in update.unplaced}
    assert ("CP-1", "model-chart-strip") not in listed  # T4.10 sits in the metric strip here
    # The facility register has no Earnings Update block: listed, with the block's own title.
    entry = listed[("CP-1", "capital-structure")]
    assert entry.title == "Capital structure"
    assert ("CP-1", "financials-credit-metrics") not in listed


def test_an_unplaced_block_carries_its_spec_title() -> None:
    update = _built("earnings_update")
    entry = next(u for u in update.unplaced if u.block_id == "key-findings")
    assert entry.title == "Key findings"  # CP-2's block, which Earnings Update does not compose


MODEL_PATHWAYS = {"credit_snapshot", "earnings_update", "relative_value", "portfolio_decision"}


@pytest.mark.parametrize("pathway", pathways(), ids=lambda p: p.id)
def test_presets_with_a_model_owned_block_request_cp_model_after_cp1(pathway: Pathway) -> None:
    requested = PATHWAY_MODULES[pathway.id]
    assert pathway_has_model_block(pathway) == (pathway.id in MODEL_PATHWAYS)
    assert ("CP-MODEL" in requested) == pathway_has_model_block(pathway)
    if "CP-MODEL" in requested:
        assert requested.index("CP-MODEL") == requested.index("CP-1") + 1
        order = plan(requested)
        assert order.index("CP-1") < order.index("CP-MODEL")
    else:
        assert "CP-MODEL" not in plan(requested)
