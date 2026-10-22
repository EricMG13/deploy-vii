"""CP-1 candidate registers -> Financials and credit metrics, capital structure, chart strip.

FP 01 has no separate metric strip: the Model chart strip holds S.1 to S.4 and the KPI
dashboard register (T4.10) feeds it. FP 02 places the same two registers again, in its own
``metric-strip`` and ``ebitda-adjustments`` blocks: a second placement per Pathway
composition, never a second binding inside one (``validate_bindings``). Capital structure is
a tabbed block: the debt facility register, the adjusted EBITDA bridge (T4.17) and the pro
forma adjustments.

Registers without a Front Page block go to Evidence or Limitations; module register detail
belongs on the module's Full analysis page. ``unit_class`` is the table's default; the
cell-level class follows each fact's unit (``report_view.fact_spelling``).
"""

from deploy_vii.bindings import Binding, BindingMap
from deploy_vii.display import UnitClass
from deploy_vii.report_view import FactCoord


def _bind(
    table: str,
    block: str,
    unit: UnitClass = "text",
    slot: str | None = None,
    label: str | None = None,
) -> Binding:
    return Binding(
        fact_coord=FactCoord(module_id="CP-1", table_id=table),
        block_id=block,
        cell_slot=slot or table.lower().replace(".", "-"),
        unit_class=unit,
        label=label,
    )


_FINANCIALS = "financials-credit-metrics"

CP1 = BindingMap(
    module_id="CP-1",
    entries=(
        # Financial statements, calculations and the model's schedules.
        _bind("T4.4", _FINANCIALS, "amount", "income-statement"),
        _bind("T4.5", _FINANCIALS, "amount", "cash-flow-statement"),
        _bind("T4.6", _FINANCIALS, "amount", "balance-sheet"),
        _bind("T4.8", _FINANCIALS, "amount", "constructed-periods"),
        _bind("T4.9", _FINANCIALS, "amount", "calculations"),
        _bind("T4.15", _FINANCIALS, "amount", "account-register"),
        _bind("T4.16", _FINANCIALS, "amount", "segment-revenue"),
        _bind("segment-allocation", _FINANCIALS, "amount"),
        _bind("operating-kpis", _FINANCIALS, "amount"),
        # Model chart strip (FP 01 S.1 to S.4).
        _bind("T4.10", "model-chart-strip", "text", "kpi-dashboard", "KPI dashboard"),
        # Capital structure tabs, in tab order.
        _bind("T4.18", "capital-structure", "amount", "debt-facilities", "Capital structure"),
        _bind(
            "T4.17", "capital-structure", "amount", "adjusted-ebitda-bridge", "EBITDA adjustments"
        ),
        _bind("pro-forma", "capital-structure", "amount", None, "Transaction and new debt"),
        # Earnings Update (FP 02): the same registers placed in that Pathway's own blocks.
        _bind("T4.17", "ebitda-adjustments", "amount", "adjusted-ebitda-bridge", "House view"),
        _bind("T4.10", "metric-strip", "text", "kpi-dashboard", "KPI dashboard"),
        # Evidence.
        _bind("T4.1", "evidence", "text", "source-register"),
        _bind("T4.2", "evidence", "text", "entity-periods"),
        _bind("T4.3", "evidence", "text", "normalizations"),
        _bind("T4.11", "evidence", "text", "definition-conflicts"),
        _bind("T4.14", "evidence", "text", "period-register"),
        _bind("T4.19", "evidence", "text", "model-reconciliation"),
        _bind("evidence-trace", "evidence", "text"),
        # Limitations.
        _bind("T4.12", "limitations", "text", "gaps-and-warnings"),
        _bind("T4.13", "limitations", "text", "downstream-readiness"),
        _bind("model-readiness", "limitations", "text"),
        _bind("analysis-coverage", "limitations", "text"),
        _bind("funding-assessment", "limitations", "text"),
        _bind("statement-coverage", "limitations", "text"),
        _bind("required-stories", "limitations", "text"),
    ),
)
