"""CP-1A business and transaction context -> Company blocks, transaction summary, rails.

FP 01's ``company-operating-model`` shows the issuer row of ``company_description`` as
key/value rows (Issuer, Business description, Country, Sector) and the operating drivers as a
second tab: the renderer places one register per tab, so the drivers cannot continue the
company rows in one list. ``company-profile`` holds ownership and the business mix;
``transaction-summary`` keeps its owner code ``Primary`` (report_view) and shows the
transactions and events, one line per cell. Every other register goes to Evidence or
Limitations. Slots carry a ``cp1a-`` prefix: a slot is unique across all shipped maps.
"""

from deploy_vii.bindings import Binding, BindingMap
from deploy_vii.business_context import COMPANY_ROW, CP1_REFERENCES, MODULE_ID
from deploy_vii.report_view import FactCoord


def _bind(table: str, block: str, label: str, row: str | None = None) -> Binding:
    return Binding(
        fact_coord=FactCoord(module_id=MODULE_ID, table_id=table, row_id=row),
        block_id=block,
        cell_slot="cp1a-" + table.lower().replace(".", "-").replace("_", "-"),
        unit_class="text",
        label=label,
    )


CP1A = BindingMap(
    module_id=MODULE_ID,
    entries=(
        _bind("company_description", "company-operating-model", "Company", COMPANY_ROW),
        _bind("operating_model", "company-operating-model", "Operating model"),
        _bind("ownership_register", "company-profile", "Ownership"),
        _bind("revenue_business_mix", "company-profile", "Revenue and business mix"),
        _bind("transaction_summary", "transaction-summary", "Transactions"),
        _bind("events_timeline", "transaction-summary", "Events"),
        # Evidence.
        _bind("credit_translation", "evidence", "Credit translation"),
        _bind("T2D.8", "evidence", "Governance and sponsor score"),
        _bind("T2D.9", "evidence", "Sponsor risk-level drivers"),
        _bind("conflict_log", "evidence", "Conflict log"),
        _bind("source_classification", "evidence", "Source classification"),
        _bind("T2D.1", "evidence", "CP-1A source register"),
        _bind("T2D.2", "evidence", "Ownership and control register"),
        _bind("T2D.3", "evidence", "Governance register"),
        _bind("T2D.4", "evidence", "Behaviour flag register"),
        _bind("T2D.5", "evidence", "Capital allocation risk table"),
        _bind("T2D.6", "evidence", "Acquisition appetite and integration"),
        _bind("T2D.7", "evidence", "Disclosure quality log"),
        _bind("T2D.10", "evidence", "Cross-module handoff register"),
        _bind("cp1a.cp_model_snapshot_fields", "evidence", "CP-MODEL snapshot fields"),
        _bind(CP1_REFERENCES, "evidence", "CP-1 facts referenced in CP-1A text"),
        # Limitations.
        _bind("gaps_ledger", "limitations", "CP-1A gaps ledger"),
        _bind("downstream_readiness", "limitations", "CP-1A downstream readiness"),
        _bind("T2D.11", "limitations", "Governance gaps ledger"),
    ),
)
