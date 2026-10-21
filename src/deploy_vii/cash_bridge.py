"""Validate explicitly sourced cash movement adjustments, without inferring FX."""

from deploy_vii.financial_contracts import FinancialBook


def cash_bridge_issues(book: FinancialBook) -> tuple[str, ...]:
    if not book.cash_movement_bridges:
        return ()
    periods = {p.period_id: p for p in book.periods}
    lines = {(r.period_id, r.line_id): r for r in book.statement_lines}
    targets = {(r.period_id, r.target_line_id) for r in book.statement_identities}
    ids: set[str] = set()
    assessed: set[str] = set()
    issues: list[str] = []
    for bridge in book.cash_movement_bridges:
        bridge_id, period_id = bridge.bridge_id, bridge.period_id
        if bridge_id in ids or period_id in assessed:
            issues.append(f"Duplicate cash movement bridge: {bridge_id}")
        ids.add(bridge_id)
        assessed.add(period_id)
        period = periods.get(period_id)
        if period is None or period.period_type == "PERIOD_END":
            issues.append(f"Cash movement bridge requires a flow period: {bridge_id}")
        seen: set[str] = set()
        for part in bridge.components:
            line_id = part.line_id
            if line_id in seen:
                issues.append(f"Duplicate cash adjustment line: {bridge_id} {line_id}")
            seen.add(line_id)
            key = period_id, line_id
            line = lines.get(key)
            if line is None:
                issues.append(f"Unknown cash adjustment line: {bridge_id} {line_id}")
            elif (
                line.statement != "CFS"
                or line.line_kind != "detail"
                or key in targets
                or not (line.item_id == "fx_cash_effect" or line.item_id.startswith("other:"))
            ):
                issues.append(
                    f"Cash adjustment requires a source FX/perimeter detail: {bridge_id} {line_id}"
                )
    return tuple(issues)
