"""CP-0 source readiness -> header, Evidence and Limitations blocks."""

from deploy_vii.bindings import Binding, BindingMap
from deploy_vii.display import UnitClass
from deploy_vii.report_view import FactCoord


def _bind(table: str, block: str, slot: str, unit: UnitClass = "text") -> Binding:
    return Binding(
        fact_coord=FactCoord(module_id="CP-0", table_id=table),
        block_id=block,
        cell_slot=slot,
        unit_class=unit,
    )


CP0 = BindingMap(
    module_id="CP-0",
    entries=(
        _bind("T1", "header", "run-identity"),
        _bind("T2", "evidence", "source-inventory"),
        _bind("P3", "evidence", "source-classification"),
        _bind("P5", "evidence", "preparation"),
        _bind("T3", "evidence", "authority"),
        _bind("T6", "evidence", "quotations"),
        _bind("T4", "evidence", "consumer-readiness"),
        _bind("T8", "evidence", "commands"),
        _bind("T5", "limitations", "gaps"),
        _bind("T7", "limitations", "assertion-scope"),
    ),
)
