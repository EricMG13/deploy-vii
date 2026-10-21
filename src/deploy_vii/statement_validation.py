"""Full source-statement keys, completeness and independent equation structure."""

from datetime import date
from decimal import Decimal

from deploy_vii.financial_contracts import AccountObservation, FinancialBook
from deploy_vii.model.history import OUTFLOW_METRICS

# r14 CP-1 steps 4-6: missing required entries must remain visible, including
# maintenance/growth capex, interest income and minority interests.
REQUIRED_ITEMS: dict[str, tuple[str, ...]] = {
    "IS": (
        "revenue",
        "cogs",
        "gross_profit",
        "sga",
        "other_operating",
        "ebitda_reported",
        "ebitda_adjusted",
        "depreciation_amortization",
        "ebit",
        "interest_expense_total",
        "interest_expense_cash",
        "interest_income",
        "other_non_operating",
        "pretax_income",
        "income_tax_total",
        "income_tax_cash",
        "net_income",
        "exceptionals",
        "sbc",
    ),
    "CFS": (
        "ocf_before_wc",
        "cfo_ncfo",
        "working_capital_change",
        "capex_maintenance",
        "capex_growth",
        "capex_total",
        "fcf_levered",
        "fcf_unlevered",
        "dividends_paid",
        "acquisitions",
        "disposals",
        "debt_issuance",
        "debt_repayment",
        "equity_issuance",
        "equity_buybacks",
        "net_cash_change",
        "cash_taxes_paid",
        "cash_interest_paid",
    ),
    "BS": (
        "cash_and_equivalents",
        "restricted_cash",
        "short_term_investments",
        "trade_receivables",
        "inventory",
        "other_current_assets",
        "total_current_assets",
        "ppe_net",
        "goodwill",
        "other_intangibles",
        "other_noncurrent_assets",
        "total_assets",
        "short_term_debt",
        "current_portion_long_term_debt",
        "trade_payables",
        "other_current_liabilities",
        "total_current_liabilities",
        "senior_secured_debt",
        "senior_unsecured_debt",
        "subordinated_debt",
        "total_debt",
        "pension_obligations",
        "lease_obligations",
        "other_noncurrent_liabilities",
        "total_liabilities",
        "shareholders_equity",
        "minority_interests",
        "total_equity",
    ),
}
OPTIONAL_ITEMS: dict[str, tuple[str, ...]] = {
    "IS": ("opex_including_da", "operating_lease_cost"),
    "CFS": (
        "investing_cash_flow",
        "financing_cash_flow",
        "fx_cash_effect",
        "opening_cash",
        "closing_cash",
        "net_income",
        "lease_payments_in_financing",
        "interest_paid_in_financing",
    ),
    "BS": ("rcf_drawn", "rcf_commitment", "net_accounts_receivable", "accounts_payable"),
}
# Only identities with the same meaning are linked. IS cash interest/tax are
# deliberately not aliases of the CFS cash-paid observations.
ACCOUNT_LINKS: dict[tuple[str, str], str] = {
    **{
        ("IS", key): key
        for key in (
            "revenue",
            "cogs",
            "gross_profit",
            "depreciation_amortization",
            "ebit",
            "pretax_income",
            "net_income",
            "opex_including_da",
            "operating_lease_cost",
        )
    },
    ("IS", "ebitda_reported"): "ebitda",
    ("IS", "ebitda_adjusted"): "adjusted_ebitda",
    ("IS", "income_tax_total"): "income_tax_expense",
    **{
        ("CFS", key): key
        for key in (
            "cfo_ncfo",
            "working_capital_change",
            "dividends_paid",
            "net_cash_change",
            "cash_taxes_paid",
            "cash_interest_paid",
            "lease_payments_in_financing",
            "interest_paid_in_financing",
        )
    },
    ("CFS", "capex_total"): "capex_and_intangible_investment",
    **{
        ("BS", key): key
        for key in (
            "cash_and_equivalents",
            "inventory",
            "senior_secured_debt",
            "total_debt",
            "rcf_drawn",
            "rcf_commitment",
            "net_accounts_receivable",
            "accounts_payable",
        )
    },
}


def _identity_issues(book: FinancialBook) -> list[str]:
    """Reject circular, duplicate and overlapping arithmetic within one statement."""
    lines = {(r.period_id, r.line_id): r for r in book.statement_lines}
    identities = {(r.period_id, r.target_line_id): r for r in book.statement_identities}
    issues: list[str] = []
    if len(identities) != len(book.statement_identities):
        issues.append("Duplicate statement identity target")
    if len({r.identity_id for r in book.statement_identities}) != len(book.statement_identities):
        issues.append("Duplicate statement identity ID")
    references = 0
    for row in book.statement_identities:
        references += len(row.components)
        target = lines.get((row.period_id, row.target_line_id))
        keys = [(row.period_id, c.line_id) for c in row.components]
        if target is None or any(k not in lines for k in keys):
            issues.append(f"Unknown statement identity line: {row.identity_id}")
            continue
        if target.line_kind == "detail":
            issues.append(
                f"Statement identity target must be a subtotal or total: {row.identity_id}"
            )
        if any(lines[k].statement != target.statement for k in keys):
            issues.append(f"Statement identity mixes statements: {row.identity_id}")
        if len(set(keys)) != len(keys):
            issues.append(f"Duplicate statement identity component: {row.identity_id}")
    if issues:
        return issues
    if references > 20000:
        return ["Statement identities exceed 20000 component references"]
    active: set[tuple[str, str]] = set()
    memo: dict[tuple[str, str], tuple[dict[tuple[str, str], int], int, int]] = {}
    expanded = 0

    def descend(key: tuple[str, str], depth: int) -> tuple[dict[tuple[str, str], int], int, int]:
        nonlocal expanded
        if key in active:
            raise ValueError(f"Cyclic statement identity: {key[0]} {key[1]}")
        cached = memo.get(key)
        if depth > 12 or (cached is not None and depth + cached[1] - 1 > 12):
            raise ValueError("Statement identity nesting exceeds twelve levels")
        if cached is not None:
            return cached
        active.add(key)
        equation = identities.get(key)
        covered: dict[tuple[str, str], int] = {key: 1} if equation is None else {}
        height = 1
        size = 1 if equation is None else 0
        if equation is not None:
            for term in equation.components:
                part, child_height, child_size = descend((key[0], term.line_id), depth + 1)
                height = max(height, 1 + child_height)
                size += child_size
                for leaf, weight in part.items():
                    contribution = weight * term.coefficient
                    prior = covered.get(leaf, 0)
                    if prior * contribution > 0:
                        raise ValueError(
                            f"Overlapping statement identity components: {key[0]} {key[1]}"
                        )
                    covered[leaf] = prior + contribution
        covered = {leaf: weight for leaf, weight in covered.items() if weight}
        if not covered:
            raise ValueError(f"Statement identity has no independent components: {key[0]} {key[1]}")
        expanded += size
        if expanded > 20000:
            raise ValueError("Expanded statement identities exceed 20000 terms")
        active.remove(key)
        result = covered, height, size
        memo[key] = result
        return result

    try:
        for key in identities:
            descend(key, 1)
    except ValueError as error:
        issues.append(str(error))
    return issues


def statement_issues(book: FinancialBook) -> tuple[str, ...]:
    periods = {p.period_id for p in book.periods}
    instant_periods = {p.period_id for p in book.periods if p.period_type == "PERIOD_END"}
    issues: list[str] = []
    seen: set[tuple[str, str]] = set()
    canonical: set[tuple[str, str, str]] = set()
    metadata: dict[str, tuple[str, str, str, int, str]] = {}
    priorities: dict[tuple[str, int], str] = {}
    end_dates = {p.period_id: p.end_date for p in book.periods}
    balances: dict[tuple[str, date], set[Decimal]] = {}
    for row in book.statement_lines:
        key = row.period_id, row.line_id
        if key in seen or row.period_id not in periods:
            issues.append(
                f"Duplicate statement line or unknown period: {row.line_id} {row.period_id}"
            )
        seen.add(key)
        if row.statement != "BS" and row.period_id in instant_periods:
            issues.append(f"Flow statement cannot use a period-end-only date: {row.line_id}")
        item_key = row.period_id, row.statement, row.item_id
        if item_key in canonical:
            issues.append(f"Duplicate canonical statement item: {row.item_id} {row.period_id}")
        canonical.add(item_key)
        if row.item_id not in (
            *REQUIRED_ITEMS[row.statement],
            *OPTIONAL_ITEMS[row.statement],
        ) and not row.item_id.startswith("other:"):
            issues.append(
                f"Unknown statement item; issuer detail requires other: prefix: {row.item_id}"
            )
        values = row.statement, row.item_id, row.label, row.display_priority, row.line_kind
        if row.line_id in metadata and metadata[row.line_id] != values:
            issues.append(
                f"Changed statement definition requires a distinct line ID: {row.line_id}"
            )
        metadata[row.line_id] = values
        priority_key = row.statement, row.display_priority
        if priority_key in priorities and priorities[priority_key] != row.line_id:
            issues.append(
                f"Duplicate statement display priority: {row.statement} {row.display_priority}"
            )
        priorities[priority_key] = row.line_id
        day = end_dates.get(row.period_id)
        if row.statement == "BS" and day is not None and row.value.amount is not None:
            balances.setdefault((row.item_id, day), set()).add(row.value.amount)
    for (item, day), amounts in balances.items():
        if len(amounts) > 1:
            issues.append(f"Unresolved same-date statement balances: {item} {day}")
    if len(metadata) * len(periods) > 20000:
        issues.append("Expanded statement register exceeds 20000 rows")
    disclosures: set[tuple[str, str]] = set()
    for disclosure_row in book.statement_disclosures:
        key = disclosure_row.period_id, disclosure_row.statement
        if key in disclosures or disclosure_row.period_id not in periods:
            issues.append(f"Duplicate statement disclosure or unknown period: {key}")
        disclosures.add(key)
        populated = any(
            r.period_id == disclosure_row.period_id and r.statement == disclosure_row.statement
            for r in book.statement_lines
        )
        if populated and disclosure_row.disclosure.status in {"not_disclosed", "not_applicable"}:
            issues.append(f"Statement disclosure contradicts populated statement: {key}")
    linked: dict[tuple[str, str], set[object]] = {}
    for account in book.accounts:
        amount = account.value.amount
        if amount is not None:
            normalized = (
                amount.copy_abs().copy_negate()
                if account_outflow(book, account.period_id, account.metric_id)
                else amount
            )
            linked.setdefault((account.period_id, account.metric_id), set()).add(normalized)
    for line in book.statement_lines:
        metric = ACCOUNT_LINKS.get((line.statement, line.item_id))
        amount = line.value.amount
        if metric is not None and amount is not None:
            normalized = (
                amount.copy_abs().copy_negate()
                if account_outflow(book, line.period_id, metric)
                else amount
            )
            linked.setdefault((line.period_id, metric), set()).add(normalized)
    for (period_id, metric), linked_values in linked.items():
        if len(linked_values) > 1:
            issues.append(
                f"Statement/account disagreement requires explicit conflict: {metric} {period_id}"
            )
    canonical_accounts = {(r.period_id, r.metric_id): r.value for r in book.accounts}
    for source in statement_accounts(book):
        canonical_value = canonical_accounts.get((source.period_id, source.metric_id))
        if (
            source.value.status == "conflicting"
            and canonical_value is not None
            and canonical_value.amount is not None
        ):
            issues.append(
                f"Unresolved source statement conflict: {source.metric_id} {source.period_id}"
            )
    issues.extend(_identity_issues(book))
    return tuple(issues)


def effective_accounts(book: FinancialBook) -> tuple[AccountObservation, ...]:
    """Fill only absent canonical accounts from exactly equivalent statement items.

    Explicit accounts, including explicit gaps/conflicts, take precedence. The
    original source Observation stays intact; the Model owns sign normalization.
    """
    result = list(book.accounts)
    present = {(r.period_id, r.metric_id) for r in result}
    for row in statement_accounts(book):
        if (row.period_id, row.metric_id) not in present:
            result.append(row)
            present.add((row.period_id, row.metric_id))
    return tuple(result)


def statement_accounts(book: FinancialBook) -> tuple[AccountObservation, ...]:
    return tuple(
        AccountObservation(metric_id=metric, period_id=row.period_id, value=row.value)
        for row in book.statement_lines
        if (metric := ACCOUNT_LINKS.get((row.statement, row.item_id))) is not None
    )


def account_outflow(book: FinancialBook, period_id: str, metric: str) -> bool:
    """Canonical outflow semantics or an explicitly cited source presentation."""
    return metric in OUTFLOW_METRICS or any(
        row.period_id == period_id
        and ACCOUNT_LINKS.get((row.statement, row.item_id)) == metric
        and row.sign_convention == "outflow_magnitude"
        for row in book.statement_lines
    )
