"""CP-6 committee challenge -> Committee challenge, the CP-6 side of Strengths and weaknesses,
rails.

FP 01's ``committee-challenge`` (owner CP-6, prose, collapsed; its ``report_view._Spec`` exists)
shows ``cp6.committee_challenge``: the action bias first (the collapsed block's summary), then
one line per challenge led by the CP-2 row's name. ``strengths-weaknesses`` (owner "CP-2 ·
CP-6") gets CP-6's side: each challenge of a CP-2 thesis, strength or weakness row, in the
``Binding.section`` column of that row, keyed by the CP-2 row id; a CP-2 row CP-6 does not
challenge has no line (nothing is invented). The registers and the referenced CP-1 facts go to
Evidence and the gaps ledger to Limitations, as ``bindings/cp3.py`` does. The call band reads the
settled ``T6A.4`` cells (``cp6_committee.settled_call``); its wiring is a separate change. Slots
carry a ``cp6-`` prefix: a slot is unique across all shipped maps. In ``SHIPPED_MAPS`` since
task 8.7.
"""

from deploy_vii.bindings import Binding, BindingMap
from deploy_vii.business_context import CP1_REFERENCES
from deploy_vii.cp6_committee import (
    COMMITTEE_CHALLENGE,
    MODULE_ID,
    REGISTERS,
    STRENGTH_CHALLENGES,
    THESIS_CHALLENGE,
    WEAKNESS_CHALLENGES,
)
from deploy_vii.report_view import FactCoord, Section


def _bind(table: str, block: str, label: str, section: Section | None = None) -> Binding:
    return Binding(
        fact_coord=FactCoord(module_id=MODULE_ID, table_id=table),
        block_id=block,
        cell_slot="cp6-" + table.lower().replace(".", "-").replace("_", "-"),
        unit_class="text",
        label=label,
        section=section,
    )


CP6 = BindingMap(
    module_id=MODULE_ID,
    entries=(
        _bind(COMMITTEE_CHALLENGE, "committee-challenge", "Committee challenge"),
        _bind(THESIS_CHALLENGE, "strengths-weaknesses", "Thesis challenge", "thesis"),
        _bind(STRENGTH_CHALLENGES, "strengths-weaknesses", "Strength challenges", "strengths"),
        _bind(WEAKNESS_CHALLENGES, "strengths-weaknesses", "Weakness challenges", "weaknesses"),
        # Evidence.
        *(
            _bind(table_id, "evidence", register.title)
            for table_id, register in REGISTERS.items()
            if table_id != "T6E.11"
        ),
        _bind(CP1_REFERENCES, "evidence", "CP-1 facts referenced in CP-6 text"),
        # Limitations.
        _bind("T6E.11", "limitations", "CP-6 gaps ledger"),
    ),
)
