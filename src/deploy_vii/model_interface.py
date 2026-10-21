"""r14 Model interface tables from validated evidence, not a full CP-1 handoff.

Original facility currencies and source figures stay in this interface. Kernel
FX conversions and derived model periods remain separate calculation artifacts.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from deploy_vii.contracts import (
    Citation,
    Contract,
    Fact,
    Hash,
    Identifier,
    Input,
    Module,
    ReportTable,
    TableColumn,
    TableRow,
)
from deploy_vii.financial_contracts import FinancialBook, FinancialReview, Observation
from deploy_vii.financial_periods import _id
from deploy_vii.financial_validation import validate_financial_review
from deploy_vii.model_readiness import ModelReadinessReport, assess_model_readiness
from deploy_vii.preparation import PreparedPack
from deploy_vii.statement_validation import account_outflow, effective_accounts

# Exact r14 interface fields; these tables are emitted once, under their own headings.
SCHEMAS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "T4.14": (
        "Model Period Register",
        "cp1.model_period_register",
        tuple(
            (
                "period_id fiscal_year fiscal_quarter period_type start_date end_date "
                "day_count audit_status currency unit accounting_basis entity_perimeter "
                "source_id source_locator component_period_ids"
            ).split()
        ),
    ),
    "T4.15": (
        "Model Account Register",
        "cp1.model_account_register",
        tuple(
            (
                "metric_id period_id value sign_convention value_class calculation_status "
                "source_id source_locator conflict_refs limitation_refs"
            ).split()
        ),
    ),
    "T4.16": (
        "Segment Revenue Schedule",
        "cp1.segment_revenue_schedule",
        tuple(
            (
                "segment_id segment_name segment_type display_priority period_id revenue "
                "status source_id source_locator"
            ).split()
        ),
    ),
    "T4.17": (
        "Adjusted EBITDA Bridge",
        "cp1.adjusted_ebitda_bridge",
        tuple(
            (
                "addback_id addback_label addback_classification realization_status "
                "display_priority period_id value status source_definition source_id "
                "source_locator"
            ).split()
        ),
    ),
    "T4.18": (
        "Debt Facility Register",
        "cp1.debt_facility_register",
        tuple(
            (
                "facility_id facility_name period_id facility_type carrying_value principal "
                "drawn_amount commitment secured_status seniority currency margin_or_coupon "
                "maturity_date lease_classification rate_type reference_rate spread_bps "
                "floor_bps fixed_rate annual_amortisation source_id source_locator"
            ).split()
        ),
    ),
    "T4.19": (
        "Model Reconciliation Register",
        "cp1.model_reconciliation_register",
        tuple(
            (
                "check_id period_id check_type reported_value calculated_value difference "
                "tolerance status explanation source_refs"
            ).split()
        ),
    ),
    "segment-allocation": (
        "Model Segment Allocation",
        "cp1.cp_model_segment_allocation",
        tuple("slot_id slot_label component_segment_ids".split()),
    ),
    "operating-kpis": (
        "Operating KPI Schedule",
        "cp1.operating_kpi_schedule",
        tuple(
            (
                "kpi_id kpi_label business_unit kpi_category display_priority period_id "
                "value unit value_type status source_id source_locator"
            ).split()
        ),
    ),
    "pro-forma": (
        "Pro Forma Adjustment Register",
        "cp1.pro_forma_adjustment_register",
        tuple(
            (
                "adjustment_id label period_id effective_date classification metric_id "
                "value source_id source_locator"
            ).split()
        ),
    ),
    "model-readiness": (
        "Historical Model Readiness",
        "cp1.downstream_readiness",
        tuple("downstream_module status missing_metric_ids conflict_refs explanation".split()),
    ),
}
# net_income remains a full statement/Model input, not an extra r14 interface ID.
ACCOUNT_FIELDS = tuple(
    (
        "revenue cogs gross_profit opex_including_da ebit depreciation_amortization "
        "ebitda adjusted_ebitda cash_interest_paid cash_lease_payments "
        "cash_taxes_paid cfo_ncfo working_capital_change "
        "capex_and_intangible_investment acquisitions_disposals "
        "net_debt_issue_repay net_equity_issue_repay dividends_paid "
        "other_investing_financing net_cash_change cash_and_equivalents "
        "rcf_commitment rcf_drawn senior_secured_debt unsecured_debt total_debt "
        "net_accounts_receivable inventory accounts_payable pretax_income "
        "income_tax_expense effective_tax_rate operating_lease_cost "
        "lease_payments_in_financing interest_paid_in_financing"
    ).split()
)


class InterfaceGap(Contract):
    table_id: Identifier
    row_id: Identifier
    field: Identifier
    reason: str


class ModelInterface(Contract):
    schema_version: Literal["model-interface/1"] = "model-interface/1"
    pack_sha256: Hash
    review_sha256: Hash
    book_id: Identifier
    requested_quarters: tuple[Identifier, ...] | None
    module: Module
    readiness: ModelReadinessReport
    gaps: tuple[InterfaceGap, ...]


Scalar = str | int | Decimal | date | None


@dataclass(frozen=True)
class _Cell:
    value: Scalar
    citations: tuple[Citation, ...] = ()
    status: Literal["known", "missing", "conflicting", "not_applicable"] = "known"
    reason: str | None = None
    unit: str | None = None
    currency: str | None = None
    value_class: Literal["source", "normalized", "calculated"] = "source"
    source_amount: Decimal | None = None
    formula: str | None = None


def _citations(value: Observation) -> tuple[Citation, ...]:
    return tuple(
        dict.fromkeys((*value.citations, *(c for a in value.alternatives for c in a.citations)))
    )


def _observed(
    value: Observation | None,
    book: FinancialBook,
    *,
    unit: str | None = None,
    currency: str | None = None,
    outflow: bool = False,
) -> _Cell:
    amount = value.amount if value else None
    normalized = amount.copy_abs().copy_negate() if outflow and amount is not None else amount
    return _Cell(
        normalized,
        _citations(value) if value else (),
        value.status if value else "missing",
        value.reason if value else "No source observation supplied",
        unit or book.unit,
        currency if unit else (currency or book.currency),
        "normalized" if normalized != amount else "source",
        amount,
        "negative absolute source amount" if normalized != amount else None,
    )


def _sources(citations: tuple[Citation, ...]) -> dict[str, _Cell]:
    # A primary row locator is explicit; every field retains all of its own citations.
    return {
        name: _Cell(
            getattr(citations[0], attr) if citations else None,
            citations,
            reason="No primary source locator supplied",
        )
        for name, attr in (("source_id", "source_id"), ("source_locator", "locator"))
    }


@dataclass
class _Tables:
    book: FinancialBook
    facts: list[Fact] = field(default_factory=list)
    rows: dict[str, list[TableRow]] = field(default_factory=dict)
    gaps: list[InterfaceGap] = field(default_factory=list)

    def row(
        self,
        table: str,
        keys: tuple[str, ...],
        period: str,
        values: dict[str, Scalar | _Cell],
        citations: tuple[Citation, ...] = (),
        references: frozenset[str] = frozenset(),
    ) -> None:
        """Preserve every cell's coordinates, null state, units and exact evidence."""
        columns = SCHEMAS[table][2]
        if set(values) != set(columns):
            raise ValueError(f"Interface row fields differ from {table} schema")
        identity = _id("interface-row", table, *keys)
        if any(row.row_id == identity for row in self.rows.get(table, [])):
            raise ValueError("Duplicate interface row identity")
        ids = []
        for name in columns:
            raw = values[name]
            cell = raw if isinstance(raw, _Cell) else _Cell(raw, citations)
            absent = cell.value is None
            status = cell.status if cell.status != "known" else ("missing" if absent else "known")
            reason = cell.reason if absent else None
            if absent and name in references and status != "conflicting":
                status, reason = "not_applicable", "No reference or applicable value"
            elif absent:
                reason = reason or "Source does not supply this field"
                self.gaps.append(
                    InterfaceGap(table_id=table, row_id=identity, field=name, reason=reason)
                )
            numeric = isinstance(cell.value, Decimal)
            fid = _id("interface-fact", table, identity, name)
            self.facts.append(
                Fact(
                    fact_id=fid,
                    label=name,
                    table_id=table,
                    row_id=identity,
                    field=name,
                    amount=cell.value if isinstance(cell.value, Decimal) else None,
                    text=None if absent or numeric else str(cell.value),
                    status=status,
                    unit=cell.unit,
                    currency=cell.currency,
                    scale=Decimal(
                        {"UNITS": 1, "THOUSANDS": 1000, "MILLIONS": 1000000}.get(cell.unit or "", 1)
                    ),
                    period=period,
                    basis=f"{self.book.accounting_basis} · {self.book.entity_perimeter}",
                    citations=cell.citations,
                    value_class=cell.value_class,
                    source_amount=cell.source_amount,
                    formula=cell.formula,
                    limitation=reason,
                )
            )
            ids.append(fid)
        self.rows.setdefault(table, []).append(
            TableRow(row_id=identity, label=" / ".join(keys), fact_ids=tuple(ids))
        )

    def layouts(self) -> tuple[ReportTable, ...]:
        return tuple(
            ReportTable(
                table_id=key,
                title=title,
                interface_id=interface,
                columns=tuple(TableColumn(field=name, label=name) for name in columns),
                rows=tuple(self.rows.get(key, [])),
                limitation=(
                    "Candidate interface. Inspect each value for its units, "
                    "source and missing reason."
                ),
            )
            for key, (title, interface, columns) in SCHEMAS.items()
            if key != "segment-allocation" or self.book.segments
        )


def _period_accounts(tables: _Tables) -> None:
    book = tables.book
    accounts = {(r.metric_id, r.period_id): r.value for r in effective_accounts(book)}
    for p in book.periods:
        tables.row(
            "T4.14",
            (p.period_id,),
            p.period_id,
            {
                "period_id": p.period_id,
                "fiscal_year": p.fiscal_year,
                "fiscal_quarter": p.fiscal_quarter,
                "period_type": p.period_type,
                "start_date": p.start_date,
                "end_date": p.end_date,
                "day_count": p.day_count,
                "audit_status": p.audit_status,
                "currency": p.currency,
                "unit": p.unit,
                "accounting_basis": p.accounting_basis,
                "entity_perimeter": p.entity_perimeter,
                **_sources(p.citations),
                "component_period_ids": ";".join(p.component_period_ids) or None,
            },
            p.citations,
            frozenset(
                {"component_period_ids"}
                | ({"fiscal_quarter"} if p.period_type != "QUARTER" else set())
            ),
        )
        for metric in ACCOUNT_FIELDS:
            observation = accounts.get((metric, p.period_id))
            cell = _observed(
                observation,
                book,
                unit="decimal_fraction" if metric == "effective_tax_rate" else None,
                outflow=account_outflow(book, p.period_id, metric),
            )
            citations = cell.citations
            tables.row(
                "T4.15",
                (metric, p.period_id),
                p.period_id,
                {
                    "metric_id": metric,
                    "period_id": p.period_id,
                    "value": cell,
                    "sign_convention": "outflows negative; inflows and positive balances positive",
                    "value_class": cell.value_class,
                    "calculation_status": "Conflicted"
                    if cell.status == "conflicting"
                    else "Not Available"
                    if cell.value is None
                    else "Calculated"
                    if cell.value_class == "normalized"
                    else "Verified",
                    **_sources(citations),
                    "conflict_refs": observation.observation_id
                    if observation and observation.status == "conflicting"
                    else None,
                    "limitation_refs": observation.observation_id
                    if observation and observation.reason
                    else None,
                },
                citations,
                frozenset({"conflict_refs", "limitation_refs"}),
            )


def _schedules(tables: _Tables) -> None:
    book = tables.book
    for p in book.periods:
        for kind, identity, field_name, table in (
            ("segments", "segment_id", "revenue", "T4.16"),
            ("addbacks", "addback_id", "value", "T4.17"),
            ("kpis", "kpi_id", "value", "operating-kpis"),
        ):
            rows = getattr(book, kind)
            templates = {getattr(r, identity): r for r in rows}
            by_period = {(getattr(r, identity), r.period_id): r for r in rows}
            for key, template in sorted(
                templates.items(), key=lambda item: item[1].display_priority
            ):
                row = by_period.get((key, p.period_id))
                observation = getattr(row, field_name) if row else None
                cell = _observed(observation, book, unit=template.unit if kind == "kpis" else None)
                values: dict[str, Scalar | _Cell] = {
                    identity: key,
                    "period_id": p.period_id,
                    "display_priority": template.display_priority,
                    field_name: cell,
                    "status": cell.status,
                    **_sources(cell.citations),
                }
                if kind == "segments":
                    values.update(
                        segment_name=template.segment_name, segment_type=template.segment_type
                    )
                    citations = template.classification_citations
                elif kind == "addbacks":
                    values.update(
                        addback_label=template.addback_label,
                        addback_classification=template.classification,
                        realization_status=row.realization_status if row else "NOT_STATED",
                        source_definition=row.source_definition if row else None,
                    )
                    citations = (
                        row.classification_citations if row else template.classification_citations
                    )
                else:
                    values.update(
                        kpi_label=template.kpi_label,
                        business_unit=template.business_unit,
                        kpi_category=template.kpi_category,
                        unit=template.unit,
                        value_type=template.value_type,
                    )
                    citations = template.definition_citations
                tables.row(table, (key, p.period_id), p.period_id, values, citations)
    for row in book.segment_allocation:
        tables.row(
            "segment-allocation",
            (row.slot_id,),
            "Forecast mapping",
            {
                "slot_id": row.slot_id,
                "slot_label": row.slot_label,
                "component_segment_ids": ";".join(row.component_segment_ids),
            },
        )
    for row in book.pro_forma:
        tables.row(
            "pro-forma",
            (row.adjustment_id, row.period_id),
            row.period_id,
            {
                "adjustment_id": row.adjustment_id,
                "label": row.label,
                "period_id": row.period_id,
                "effective_date": row.effective_date,
                "classification": row.classification,
                "metric_id": row.metric_id,
                "value": _observed(row.value, book),
                **_sources(_citations(row.value)),
            },
            row.event_citations,
        )


def _facilities(tables: _Tables) -> None:
    book = tables.book
    for row in book.facilities:
        values: dict[str, Scalar | _Cell] = {
            name: getattr(row, name)
            for name in SCHEMAS["T4.18"][2]
            if name not in {"source_id", "source_locator"}
        }
        for name in (
            "carrying_value",
            "principal",
            "drawn_amount",
            "commitment",
            "spread_bps",
            "floor_bps",
            "fixed_rate",
            "annual_amortisation",
        ):
            unit = (
                "basis_points"
                if name in {"spread_bps", "floor_bps"}
                else "decimal_percent"
                if name == "fixed_rate"
                else None
            )
            values[name] = _observed(
                getattr(row, name), book, unit=unit, currency=None if unit else row.currency
            )
        values["maturity_date"] = _Cell(
            row.maturity_date, row.terms_citations, reason=row.maturity_limitation
        )
        values.update(
            _sources(tuple(dict.fromkeys((*_citations(row.carrying_value), *row.terms_citations))))
        )
        optional = {"floor_bps"}
        if row.rate_type == "FIXED":
            optional.add("spread_bps")
        if row.rate_type == "FLOATING":
            optional.add("fixed_rate")
        tables.row(
            "T4.18",
            (row.facility_id, row.period_id),
            row.period_id,
            values,
            row.terms_citations,
            frozenset(optional),
        )


def model_interface(
    pack: PreparedPack,
    review: FinancialReview,
    book_id: str,
    *,
    quarter_ids: tuple[str, ...] | None = None,
) -> ModelInterface:
    issues = validate_financial_review(pack, review)
    if issues:
        raise ValueError("; ".join(issues))
    review = FinancialReview.model_validate_json(review.model_dump_json())
    book = next((b for b in review.books if b.book_id == book_id), None)
    if book is None:
        raise ValueError(f"Unknown financial book: {book_id}")
    readiness = assess_model_readiness(pack, review, book_id, quarter_ids=quarter_ids)
    tables = _Tables(book)
    _period_accounts(tables)
    _schedules(tables)
    _facilities(tables)
    for row in readiness.source_reconciliation.checks:
        citations = tuple(
            dict.fromkeys(
                (
                    *row.reported.citations,
                    *(c for t in row.components for c in t.citations),
                    *row.context_citations,
                )
            )
        )
        numbers = {
            name: _Cell(
                getattr(row, name),
                citations,
                reason=row.explanation,
                unit=book.unit,
                currency=book.currency,
                value_class="calculated",
            )
            for name in ("reported_value", "calculated_value", "difference", "tolerance")
        }
        numbers["reported_value"] = _Cell(
            row.reported_value,
            row.reported.citations,
            reason=row.explanation,
            unit=book.unit,
            currency=book.currency,
        )
        tables.row(
            "T4.19",
            (row.check_id,),
            row.period_id,
            {
                "check_id": row.check_id,
                "period_id": row.period_id,
                "check_type": row.check_type,
                **numbers,
                "status": row.status,
                "explanation": row.explanation,
                "source_refs": "; ".join(f"{c.source_id}: {c.locator}" for c in citations) or None,
            },
            citations,
        )
    ready = readiness.readiness
    tables.row(
        "model-readiness",
        ("CP-MODEL",),
        "Selected historical quarters",
        {
            "downstream_module": ready.downstream_module,
            "status": ready.status,
            "missing_metric_ids": ";".join(ready.missing_metric_ids) or None,
            "conflict_refs": ";".join(ready.conflict_refs) or None,
            "explanation": ready.explanation,
        },
        references=frozenset({"missing_metric_ids", "conflict_refs"}),
    )
    module = Module(
        run_id=review.run_id,
        issuer_id=review.issuer_id,
        as_of=review.as_of,
        module_id="CP-1",
        inputs=(
            Input(input_id="pack", sha256=pack.content_hash()),
            Input(input_id="financial-review", sha256=review.content_hash()),
        ),
        facts=tuple(tables.facts),
        tables=tables.layouts(),
        limitations=(
            "Model interface preview only; not the full canonical Markdown handoff "
            "or CP-1 acceptance.",
            "Primary row locator shown; all field-specific citations remain inspectable.",
            *readiness.limitations,
        ),
    )
    return ModelInterface(
        pack_sha256=pack.content_hash(),
        review_sha256=review.content_hash(),
        book_id=book_id,
        requested_quarters=quarter_ids,
        module=module,
        readiness=readiness,
        gaps=tuple(tables.gaps),
    )


def validate_model_interface(
    pack: PreparedPack, review: FinancialReview, report: ModelInterface
) -> tuple[str, ...]:
    try:
        report = ModelInterface.model_validate_json(report.model_dump_json())
        expected = model_interface(
            pack, review, report.book_id, quarter_ids=report.requested_quarters
        )
    except ValueError as error:
        return (f"Invalid Model interface: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Model interface differs from trusted recomputation",)
    )
