"""The r14 audited-FY exception, scoped to explicit independent source periods.

This changes the severity of an explained annual comparison, never its arithmetic.
It is not an override for source identities, cash differences or missing inputs.
"""

from decimal import Decimal
from itertools import pairwise

from deploy_vii.financial_contracts import AuditBasisExplanation, FinancialBook
from deploy_vii.model.dates import fiscal_year_number
from deploy_vii.model.history import FLOW_METRICS
from deploy_vii.statement_validation import effective_accounts


def audit_explanation_issues(book: FinancialBook) -> tuple[str, ...]:
    periods = {p.period_id: p for p in book.periods}
    ids: set[str] = set()
    targets: set[tuple[str, str]] = set()
    issues: list[str] = []
    observations = {(r.period_id, r.metric_id): r.value for r in effective_accounts(book)}
    for item in book.audit_basis_explanations:
        explanation_id = item.explanation_id
        annual_id = item.annual_period_id
        metric_id = item.metric_id
        quarter_ids = item.quarter_period_ids
        target = annual_id, metric_id
        if explanation_id in ids or target in targets:
            issues.append(f"Duplicate annual audit explanation: {explanation_id}")
        ids.add(explanation_id)
        targets.add(target)
        annual = periods.get(annual_id)
        known = [q for pid in quarter_ids if (q := periods.get(pid)) is not None]
        if annual is None or len(known) != len(quarter_ids):
            issues.append(f"Unknown audit explanation period: {explanation_id}")
            continue
        if metric_id not in FLOW_METRICS:
            issues.append(f"Annual audit explanation requires a flow metric: {explanation_id}")
        for pid, expected in zip(
            (annual_id, *quarter_ids),
            (item.annual_observation_sha256, *item.quarter_observation_sha256),
            strict=True,
        ):
            observation = observations.get((pid, metric_id))
            if observation is None or observation.content_hash() != expected:
                issues.append(f"Stale audit explanation observation: {explanation_id} {pid}")
        if annual.period_type != "FY" or annual.audit_status.strip().upper() != "AUDITED":
            issues.append(f"Annual audit explanation requires audited FY: {explanation_id}")
        if (
            len(set(quarter_ids)) != 4
            or [q.fiscal_quarter for q in known] != [1, 2, 3, 4]
            or any(
                q.period_type != "QUARTER"
                or q.audit_status.strip().upper() != "UNAUDITED"
                or q.component_period_ids
                or fiscal_year_number(q.fiscal_year) != fiscal_year_number(annual.fiscal_year)
                for q in known
            )
        ):
            issues.append(
                f"Audit explanation requires ordered independent unaudited quarters: "
                f"{explanation_id}"
            )
        if (
            annual.start_date is None
            or annual.end_date is None
            or known[0].start_date != annual.start_date
            or known[-1].end_date != annual.end_date
            or any(q.start_date is None or q.end_date is None for q in known)
            or any(
                a.end_date is None
                or b.start_date is None
                or a.end_date.toordinal() + 1 != b.start_date.toordinal()
                for a, b in pairwise(known)
            )
        ):
            issues.append(f"Audit explanation quarters do not span FY: {explanation_id}")
    return tuple(issues)


def annual_warning(
    book: FinancialBook,
    annual_period_id: str,
    metric_id: str,
    quarter_period_ids: tuple[str | None, ...],
    difference: Decimal | None,
    tolerance: Decimal | None,
) -> AuditBasisExplanation | None:
    """Select only a validated, exact-scope explanation for a numeric discrepancy.

    Callers pass null difference for structural failures and non-independent
    constructions. Book and citation validation precedes both public consumers.
    """
    if difference is None or tolerance is None or difference.copy_abs() <= tolerance:
        return None
    for item in book.audit_basis_explanations:
        if (
            item.annual_period_id == annual_period_id
            and item.metric_id == metric_id
            and item.quarter_period_ids == quarter_period_ids
        ):
            return item
    return None
