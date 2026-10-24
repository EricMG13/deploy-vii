"""CP-5 integrity review -> the Evidence and Limitations rails only (task 8.4, ruling 6).

No Front Page block shows CP-5 in M8 (docs/frontend-direction-c.md, CP-5 row): the evaluated
set, the Python checks, the support review, the verdict consistency, the module statuses and the
verdict go to Evidence; the findings register, the unsupported claims, the contradictions, the
gaps and the report-level limitations go to Limitations. Slots carry a ``cp5-`` prefix: a slot
is unique across all shipped maps.
"""

from deploy_vii.bindings import Binding, BindingMap
from deploy_vii.cp5_integrity import MODULE_ID, REGISTERS
from deploy_vii.report_view import FactCoord

LIMITATIONS = frozenset({"T5.9", "T5B.2", "T5B.3", "T5B.5", "T5B.7"})

CP5 = BindingMap(
    module_id=MODULE_ID,
    entries=tuple(
        Binding(
            fact_coord=FactCoord(module_id=MODULE_ID, table_id=table_id),
            block_id="limitations" if table_id in LIMITATIONS else "evidence",
            cell_slot="cp5-" + table_id.lower().replace(".", "-"),
            unit_class="text",
            label=register.title,
        )
        for table_id, register in REGISTERS.items()
    ),
)
