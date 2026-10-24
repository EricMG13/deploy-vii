import json
from pathlib import Path

import pytest

from deploy_vii.contracts import PATHWAY_MODULES
from deploy_vii.registry import dependencies, edge_rule, modules, plan


def test_edge_rule_defaults_required_block_optional_restricted() -> None:
    assert edge_rule("CP-3", "CP-2") == "block"
    assert edge_rule("CP-3", "CP-4") == "restricted"


@pytest.mark.parametrize(
    ("consumer", "producer", "rule"),
    [
        ("CP-2", "CP-1A", "restricted"),
        ("CP-4", "CP-1", "restricted"),
        ("CP-8", "CP-6", "block"),
        ("CP-MEMO", "CP-6", "restricted"),
    ],
)
def test_edge_rule_overrides_from_decision_0007(consumer: str, producer: str, rule: str) -> None:
    assert edge_rule(consumer, producer) == rule


def test_cp5_fan_in_is_restricted() -> None:
    graph = dependencies(("CP-5", "CP-4", "CP-3"))
    catalog = {module.module_id: module for module in modules()}
    analysts = graph["CP-5"] - set(catalog["CP-5"].required)
    assert {"CP-1", "CP-3", "CP-4"} <= analysts
    for producer in analysts:
        assert edge_rule("CP-5", producer) == "restricted"
    # CP-0 is CP-5's own required source readiness; it is not an analyst and still blocks.
    assert edge_rule("CP-5", "CP-0") == "block"


def test_edge_rule_unknown_edge_raises() -> None:
    with pytest.raises(ValueError, match="No dependency edge"):
        edge_rule("CP-3", "CP-8")
    with pytest.raises(ValueError, match="No dependency edge"):
        edge_rule("CP-99", "CP-0")
    with pytest.raises(ValueError, match="No dependency edge"):
        edge_rule("CP-5", "CP-6")


def test_methodology_edge_rules_only_name_declared_producers() -> None:
    for module in modules():
        declared = {*module.required, *module.optional}
        assert set(module.edge_rules) <= declared, module.module_id


def test_cp_model_requires_cp1_and_reaches_cp0_through_it() -> None:
    # Decision 0006 DC-5: the Model destination publishes accepted CP-1 output.
    catalog = {module.module_id: module for module in modules()}
    assert catalog["CP-MODEL"].required == ("CP-1",)
    assert plan(("CP-MODEL",)) == ("CP-0", "CP-1", "CP-MODEL")
    assert edge_rule("CP-MODEL", "CP-1") == "block"
    with pytest.raises(ValueError, match="No dependency edge"):
        edge_rule("CP-MODEL", "CP-0")


def test_cp5_fan_in_includes_selected_cp_model_but_does_not_pull_it_in() -> None:
    assert "CP-MODEL" in dependencies(("CP-5", "CP-MODEL"))["CP-5"]
    assert edge_rule("CP-5", "CP-MODEL") == "restricted"
    order = plan(("CP-5", "CP-MODEL"))
    assert order.index("CP-MODEL") < order.index("CP-5")
    # CP-5 itself requires only CP-0; only the presets whose composition holds a Model-owned
    # block request CP-MODEL (decision 0009), and CP-5 then follows it in the plan.
    assert "CP-MODEL" not in plan(("CP-5",))
    wanting = {pid for pid, requested in PATHWAY_MODULES.items() if "CP-MODEL" in requested}
    assert wanting == {"credit_snapshot", "earnings_update", "relative_value", "portfolio_decision"}
    for pid in wanting:
        order = plan(PATHWAY_MODULES[pid])
        assert order.index("CP-1") < order.index("CP-MODEL") < order.index("CP-5")


def test_coverage_map_cp_model_matches_dc5() -> None:
    path = Path(__file__).resolve().parents[2] / "docs/methodology/r14-coverage.json"
    coverage = json.loads(path.read_text())
    entry = next(m for m in coverage["modules"] if m["module_id"] == "CP-MODEL")
    contract = entry["artifact_contract"]
    assert contract["primary_kind"] == "html_model_destination"
    assert contract["calculation_json"] is True
    deferred = contract["deferred"]["xlsx_workbook"]
    assert "Credit Snapshot" in deferred["required_sheet_names"]
    assert "DC-5" in deferred["reason"]
    assert entry["implementation"].startswith("implemented")
    edges = {(e["source"], e["target"]) for e in coverage["reference_edges"]}
    assert ("CP-1", "CP-MODEL") in edges
    assert ("CP-0", "CP-MODEL") not in edges


def test_coverage_map_cp1a_records_task_7_2() -> None:
    path = Path(__file__).resolve().parents[2] / "docs/methodology/r14-coverage.json"
    coverage = json.loads(path.read_text())
    entry = next(m for m in coverage["modules"] if m["module_id"] == "CP-1A")
    assert entry["implementation"] == (
        "partial (contract, validator, bindings; T2D.8/T2D.9 derived in Python; live E1 pending)"
    )
    assert entry["analytical_qualification"] == "unrun"


@pytest.mark.parametrize("module_id", ["CP-2", "CP-4", "CP-3", "CP-5"])
def test_coverage_map_records_task_8_6_registration_and_pending_live_acceptance(
    module_id: str,
) -> None:
    path = Path(__file__).resolve().parents[2] / "docs/methodology/r14-coverage.json"
    coverage = json.loads(path.read_text())
    entry = next(m for m in coverage["modules"] if m["module_id"] == module_id)
    assert entry["implementation"].startswith("partial (task 8.")
    assert "registered in the live runner" in entry["implementation"]
    assert "live acceptance" in entry["implementation"]
    for status in ("analytical_qualification", "rendering_acceptance", "native_host_qualification"):
        assert entry[status] == "unrun", status
