"""CP-4 legal covenant interpretation -> the six Covenant & Refinancing blocks and the rails.

FP 04 ("Covenant & Refinancing") composes eleven blocks; CP-4 fills six of them (``BLOCKS``):
the covenant tests with Python's headroom, basket capacity, red flags, the lender protection
score, the covenant definitions (the EBITDA definition block) and the document register with the
facility coverage map (two tabs). Liquidity runway, maturity wall, funding gap, refinancing paths
and LME exposure belong to other owners and stay unbound here. Every other CP-4 table goes to
Evidence or Limitations. Slots carry a ``cp4-`` prefix: a slot is unique across all shipped maps.
``report_view`` has no FP 04 composition yet (M10), so until then these blocks render through
its unbound-owner path; this map is the data M10 composes from.
"""

from deploy_vii.bindings import Binding, BindingMap
from deploy_vii.cp4_legal import MODULE_ID
from deploy_vii.display import UnitClass
from deploy_vii.report_view import FactCoord

BLOCKS = (
    "covenant-tests-headroom",
    "capacity",
    "red-flags",
    "lender-protection-score",
    "ebitda-definition",
    "documents-structure",
)


def _bind(table: str, block: str, label: str, unit: UnitClass = "text") -> Binding:
    return Binding(
        fact_coord=FactCoord(module_id=MODULE_ID, table_id=table),
        block_id=block,
        cell_slot="cp4-" + table.lower().replace(".", "-"),
        unit_class=unit,
        label=label,
    )


CP4 = BindingMap(
    module_id=MODULE_ID,
    entries=(
        # The six FP 04 blocks.
        _bind("T4.9", "covenant-tests-headroom", "Covenant tests and headroom", "multiple"),
        _bind("T4.10", "capacity", "Capacity and baskets"),
        _bind("T4.11", "red-flags", "Red flags"),
        _bind("T4.13", "lender-protection-score", "Lender protection score"),
        _bind("T4C.6", "ebitda-definition", "Covenant definitions"),
        _bind("T4.2", "documents-structure", "Document register"),
        _bind("T4C.12", "documents-structure", "Facility coverage"),
        # Evidence.
        _bind("T4.3", "evidence", "Covenant register"),
        _bind("T4C.2", "evidence", "Maintenance covenants"),
        _bind("T4C.3", "evidence", "Incurrence covenants"),
        _bind("T4C.4", "evidence", "Negative covenants"),
        _bind("T4C.5", "evidence", "Other covenants"),
        _bind("T4C.7", "evidence", "Threshold check"),
        _bind("T4C.8", "evidence", "CP-1 metric binding"),
        _bind("T4C.11", "evidence", "Covenant-to-facility map"),
        _bind("T4D.1", "evidence", "Pack legal source eligibility"),
        _bind("T4D.2", "evidence", "Governing entities"),
        _bind("T4D.3", "evidence", "Dates and amendments"),
        _bind("T4D.4", "evidence", "Document quotations"),
        _bind("T4D.6", "evidence", "Capacity conditions"),
        _bind("T4D.7", "evidence", "Red flag implications"),
        _bind("T4D.8", "evidence", "Covenants by governing document"),
        _bind("T4F.2", "evidence", "CP-1 figures referenced in CP-4", "amount"),
        _bind("T4F.3", "evidence", "Headroom calculation trace"),
        _bind("T4F.4", "evidence", "Protection score basis"),
        _bind("T4F.6", "evidence", "CP-4 source trace"),
        # Limitations.
        _bind("T4.12", "limitations", "CP-4 gaps ledger"),
        _bind("T4C.9", "limitations", "Headroom calculability"),
        _bind("T4D.5", "limitations", "Document limitations"),
        _bind("T4F.1", "limitations", "CP-4 input status"),
        _bind("T4F.5", "limitations", "Inherited CP-1 gaps"),
    ),
)
