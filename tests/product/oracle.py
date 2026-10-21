"""Display oracle independent of the renderer: it spells a fact from the source fact alone.

The expected text comes from ``display.format_value`` applied to the fact's amount, unit and
state (the ruling's unit-class table, written out here rather than imported), with the report
wide ``G#`` recounted from the view. It shares no code with ``render.table_display`` or
``report_view.fact_spelling``, so a defect in either shows as a mismatch.
"""

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from deploy_vii.contracts import Fact, View
from deploy_vii.display import format_value

AMOUNT_UNITS = {"MILLIONS", "THOUSANDS", "UNITS"}
CURRENCY_UNITS = {"currency"}  # statement lines: an amount at 0 dp unless the fact says otherwise
PERCENT_UNITS = {"PERCENT", "decimal_fraction"}
# Internal unit tokens never reach the page; the label does (decision 0004 section 4).
UNIT_LABELS = {"basis_points": " bp", "decimal_percent": "%"}
EXACT_EXPONENT = 100  # beyond this adjusted exponent the exact decimal replaces fixed point


def gap_ids(view: View) -> dict[tuple[str, str], str]:
    """G# per unsettled fact: report-wide, one per fact, in module then fact order."""
    ordinal = 0
    found: dict[tuple[str, str], str] = {}
    for module in view.modules:
        for fact in module.facts:
            if fact.status != "known":
                ordinal += 1
                found[module.module_id, fact.fact_id] = f"G{ordinal}"
    return found


def expected_text(fact: Fact, gap_id: str | None) -> str:
    unit_class: Any
    if fact.unit in AMOUNT_UNITS:
        unit_class = "amount"
    elif fact.unit in CURRENCY_UNITS:
        unit_class = "amount"
    elif fact.unit in PERCENT_UNITS:
        unit_class = "percent"
    elif fact.unit == "MULTIPLE":
        unit_class = "multiple"
    else:
        unit_class = None
    if fact.status != "known":
        state = "not_meaningful" if fact.status == "not_applicable" else "gap"
        return format_value(None, unit_class or "text", state, gap_id=gap_id)
    if fact.text is not None:
        return format_value(None, "text", "known", text=fact.text)
    assert fact.amount is not None
    exponent = fact.amount.adjusted()
    if unit_class is None or abs(exponent) > EXACT_EXPONENT:
        digits = str(fact.amount) if abs(exponent) > EXACT_EXPONENT else format(fact.amount, "f")
        return digits + UNIT_LABELS.get(fact.unit or "", f" {fact.unit}")
    return format_value(fact.amount, unit_class, "known", decimals=fact.decimals)


def expected_by_fact(view: View, module_ids: Iterable[str] | None = None) -> dict[str, str]:
    """Expected cell text per fact id, over the view's displayed modules."""
    gaps = gap_ids(view)
    return {
        fact.fact_id: expected_text(fact, gaps.get((module.module_id, fact.fact_id)))
        for module in view.modules
        if module.status != "rejected" and (module_ids is None or module.module_id in module_ids)
        for fact in module.facts
    }


def expected_display(fact: Fact) -> str:
    """Independent spelling of the artifact-values path (``render.display``): exact, unrounded."""
    if fact.status != "known":
        return f"{fact.status.replace('_', ' ').capitalize()} — {fact.limitation or 'Not supplied'}"
    if fact.amount is not None:
        return format(fact.amount, "f")
    return fact.text or ""


def parity_record(expected: Mapping[str, str], actual: Mapping[str, str]) -> dict[str, Any]:
    """Field parity as a computed record: what was compared, what matched, what did not.

    A fact missing from the page, an unexpected extra and a differing text are all mismatches,
    so an empty page or a wrong oracle cannot read as parity.
    """
    mismatches = [
        {"fact_id": fact_id, "expected": expected.get(fact_id), "actual": actual.get(fact_id)}
        for fact_id in sorted(expected.keys() | actual.keys())
        if expected.get(fact_id) != actual.get(fact_id)
    ]
    return {
        "compared": len(expected.keys() | actual.keys()),
        "matched": len(expected.keys() & actual.keys())
        - sum(
            1 for item in mismatches if item["fact_id"] in expected and item["fact_id"] in actual
        ),
        "mismatches": mismatches,
    }


def gap_id_of(view: View, fact: Fact) -> str | None:
    """The recounted G# of ``fact`` (fact ids are unique within a module)."""
    return next(
        (gap for (_, fact_id), gap in gap_ids(view).items() if fact_id == fact.fact_id), None
    )


def front_blocks(html: str) -> dict[str, dict[str, Any]]:
    """The Front Page blocks of the rendered page's data island, by block id."""
    match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html)
    assert match, "the page carries no data island"
    return {b["block_id"]: b for b in json.loads(match.group(1))["report"]["blocks"]}


def rendered_table_display(html: str) -> dict[str, str]:
    """The ``table_display`` of every fact in the rendered page's data island."""
    match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html)
    assert match, "the page carries no data island"
    payload = json.loads(match.group(1))
    return {
        fact["fact_id"]: fact["table_display"]
        for module in payload["modules"]
        for fact in module["facts"]
    }
