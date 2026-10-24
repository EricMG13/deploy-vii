"""CP-3 relative value and security selection -> Relative value, rails.

FP 01's ``relative-value`` (owner CP-3, prose, collapsed; its ``report_view._Spec`` exists, so
no report_view change, ruling 6) shows ``cp3.relative_value``: one line per bound row, the
preference first (the collapsed block's summary: the Python-spelled ordering and the model's
rationale), then each instrument's fundamental view and market observation, labelled with its
CP-1 facility name. The full tables (instruments, market evidence with its cited quotes,
preference, risks) and the referenced CP-1 facts go to Evidence and the gaps ledger to
Limitations, as ``bindings/cp2.py`` does. FP 03's Relative Value blocks and the call band are
M10. Slots carry a ``cp3-`` prefix: a slot is unique across all shipped maps. Not yet in
``SHIPPED_MAPS`` (registration is separate).
"""

from deploy_vii.bindings import Binding, BindingMap
from deploy_vii.business_context import CP1_REFERENCES
from deploy_vii.cp3_relative_value import MODULE_ID, RELATIVE_VALUE
from deploy_vii.report_view import FactCoord


def _bind(table: str, block: str, label: str) -> Binding:
    return Binding(
        fact_coord=FactCoord(module_id=MODULE_ID, table_id=table),
        block_id=block,
        cell_slot="cp3-" + table.lower().replace(".", "-").replace("_", "-"),
        unit_class="text",
        label=label,
    )


CP3 = BindingMap(
    module_id=MODULE_ID,
    entries=(
        _bind(RELATIVE_VALUE, "relative-value", "Relative value"),
        # Evidence.
        _bind("T3.1", "evidence", "Instrument relative value"),
        _bind("T3.3", "evidence", "Market evidence"),
        _bind("T3.4", "evidence", "Security selection preference"),
        _bind("T3.9", "evidence", "Relative value risks"),
        _bind(CP1_REFERENCES, "evidence", "CP-1 facts referenced in CP-3 text"),
        # Limitations.
        _bind("T3.10", "limitations", "CP-3 gaps ledger"),
    ),
)
