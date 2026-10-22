"""CP-MODEL publication registers -> Evidence page (task 7.1a).

The Model destination manifest, the calculation JSON identity and the publication provenance
are provenance of the published Model, not Front Page figures; the Model panel (app.js) and
the CP-MODEL module page draw them, so they bind to the Evidence rail destination only.
"""

from deploy_vii.bindings import Binding, BindingMap
from deploy_vii.report_view import FactCoord

CP_MODEL = BindingMap(
    module_id="CP-MODEL",
    entries=tuple(
        Binding(
            fact_coord=FactCoord(module_id="CP-MODEL", table_id=table),
            block_id="evidence",
            cell_slot=table,
            unit_class="text",
        )
        for table in ("model-destination", "model-calculation", "model-provenance")
    ),
)
