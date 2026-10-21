import pytest

from deploy_vii.registry import dependencies, edge_rule, modules


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
