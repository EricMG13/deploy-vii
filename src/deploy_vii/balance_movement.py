"""Validate sourced cross-statement movement coverage, never invent a plug."""

from deploy_vii.financial_contracts import FinancialBook
from deploy_vii.statement_validation import OPTIONAL_ITEMS, REQUIRED_ITEMS


def balance_movement_issues(book: FinancialBook) -> tuple[str, ...]:
    periods = {period.period_id: period for period in book.periods}
    movement_rows = {}
    issues = []
    definitions: dict[str, tuple[str, str]] = {}
    for row in book.balance_movements:
        key = row.period_id, row.movement_id
        if key in movement_rows:
            issues.append(f"Duplicate balance movement: {key}")
        definition = row.label, row.role
        if row.movement_id in definitions and definitions[row.movement_id] != definition:
            issues.append(
                f"Changed balance movement definition requires a new ID: {row.movement_id}"
            )
        definitions[row.movement_id] = definition
        movement_rows[key] = row
        period = periods.get(row.period_id)
        if period is None or period.period_type == "PERIOD_END":
            issues.append(f"Balance movement requires a flow period: {key}")

    bridge_ids: set[str] = set()
    bridge_scopes: set[tuple[str, str]] = set()
    assigned_movements: set[tuple[str, str]] = set()
    for bridge in book.balance_movement_bridges:
        key = bridge.period_id, bridge.balance_item_id
        if bridge.bridge_id in bridge_ids or key in bridge_scopes:
            issues.append(f"Duplicate balance movement bridge: {bridge.bridge_id}")
        bridge_ids.add(bridge.bridge_id)
        bridge_scopes.add(key)
        period = periods.get(bridge.period_id)
        if period is None or period.period_type == "PERIOD_END":
            issues.append(f"Balance movement bridge requires a flow period: {bridge.bridge_id}")
        item = bridge.balance_item_id
        if item not in (*REQUIRED_ITEMS["BS"], *OPTIONAL_ITEMS["BS"]) and not item.startswith(
            "other:"
        ):
            issues.append(f"Balance movement requires a BS item: {bridge.bridge_id}")
        movement_ids = bridge.movement_ids
        if len(movement_ids) != len(set(movement_ids)):
            issues.append(f"Duplicate movement reference: {bridge.bridge_id}")
        for movement_id in movement_ids:
            reference = bridge.period_id, movement_id
            if reference not in movement_rows:
                issues.append(
                    f"Unknown balance movement reference: {bridge.bridge_id} {movement_id}"
                )
            assigned_movements.add(reference)
        if movement_ids and bridge.disclosure.status in {"not_disclosed", "not_applicable"}:
            issues.append(
                f"Balance movement disclosure contradicts populated bridge: {bridge.bridge_id}"
            )
    if movement_rows.keys() - assigned_movements:
        issues.append("Balance movements require an explicit bridge assignment")
    return tuple(issues)
