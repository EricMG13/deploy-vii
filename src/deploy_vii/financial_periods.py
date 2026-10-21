"""Hash-bound historical period construction, before statement/ratio assembly.

The pinned kernel's plan and readers remain the arithmetic authority. This
adapter exposes their operands and keeps reported, normalized and calculated
figures distinct; it never accepts a model-authored construction result.
"""

import hashlib
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from deploy_vii.contracts import Citation, Contract, Hash, Identifier, Text
from deploy_vii.facility_fx import FacilityNormalization, normalize_facilities
from deploy_vii.financial_adapter import kernel_registers
from deploy_vii.financial_contracts import (
    FinancialBook,
    FinancialPeriod,
    FinancialReview,
    Observation,
)
from deploy_vii.financial_validation import records
from deploy_vii.model import history
from deploy_vii.model._cells import CONTEXT
from deploy_vii.model.frame import Cell, SourceRef
from deploy_vii.model.periods import _plan, _Spec
from deploy_vii.model.registers import Cp1Registers
from deploy_vii.preparation import PreparedPack

CalculationStatus = Literal[
    "Verified",
    "Calculated",
    "Estimated",
    "Proxy",
    "Not Calculable",
    "Partial",
    "Conflicted",
    "Not Available",
]


class PeriodReference(Contract):
    kind: Literal["period", "construction", "missing"]
    reference: Text | None
    coefficient: Literal[-1, 1]


class PeriodConstruction(Contract):
    construction_id: Identifier
    column_key: Text
    label: Text
    kind: Literal["QUARTER", "PYTD", "YTD", "FY", "LTM"]
    fiscal_year: Text
    fiscal_quarter: int | None
    start_date: date | None
    end_date: date | None
    days: int | None
    own_period_id: Identifier | None
    stated_period_id: Identifier | None
    terms: tuple[PeriodReference, ...]
    formula: Text
    limitation: Text | None


class PeriodValue(Contract):
    amount: Decimal | None
    stated_amount: Decimal | None
    value_class: Literal["source", "normalized", "calculated"]
    calculation_status: CalculationStatus
    reason: Text | None
    note: Text | None
    observation_ids: tuple[Identifier, ...]
    issuance_facility_ids: tuple[Identifier, ...]
    normalization_ids: tuple[Identifier, ...] = ()
    citations: tuple[Citation, ...]


class ConstructionOperand(Contract):
    reference: PeriodReference
    value: PeriodValue


class HistoricalValue(Contract):
    value_id: Identifier
    construction_id: Identifier
    series_key: Text
    series_kind: Literal["flow", "sparse", "balance", "exact"]
    unit: Text
    currency: Text | None
    value: PeriodValue
    operands: tuple[ConstructionOperand, ...]
    formula: Text


class HistoricalInput(Contract):
    """Adapter input, before kernel normalization; null rows stay explicit."""

    series_key: Text
    period_id: Identifier
    adapter_amount: Decimal | None
    observation_id: Identifier | None
    issuance_facility_id: Identifier | None
    normalization_id: Identifier | None = None


class HistoricalReport(Contract):
    schema_version: Literal["financial-periods/2"] = "financial-periods/2"
    run_id: Identifier
    issuer_id: Identifier
    as_of: date
    method_version: Literal["deploy-v-r14"] = "deploy-v-r14"
    pack_sha256: Hash
    review_sha256: Hash
    book_id: Identifier
    entity_perimeter: Text
    accounting_basis: Text
    currency: Text
    scale: Text
    periods: tuple[FinancialPeriod, ...]
    observations: tuple[Observation, ...]
    facility_normalizations: tuple[FacilityNormalization, ...]
    input_rows: tuple[HistoricalInput, ...]
    columns: tuple[Identifier, ...]
    constructions: tuple[PeriodConstruction, ...]
    values: tuple[HistoricalValue, ...]
    limitations: tuple[Text, ...]


def _id(kind: str, *parts: str) -> str:
    # Length-prefix fields so delimiters in valid source IDs cannot collide.
    payload = "".join(f"{len(part)}:{part}" for part in parts)
    return kind + ":" + hashlib.sha256(payload.encode()).hexdigest()


def _reference(ref: str | _Spec | None, coefficient: int) -> PeriodReference:
    if coefficient not in {-1, 1}:
        raise ValueError("Unsupported kernel period coefficient")
    sign: Literal[-1, 1] = 1 if coefficient == 1 else -1
    if isinstance(ref, _Spec):
        return PeriodReference(
            kind="construction", reference=_id("period", ref.column.column_id), coefficient=sign
        )
    return PeriodReference(
        kind="missing" if ref is None else "period", reference=ref, coefficient=sign
    )


def _constructions(specs: tuple[_Spec, ...]) -> tuple[PeriodConstruction, ...]:
    result: dict[str, PeriodConstruction] = {}

    def visit(spec: _Spec) -> None:
        column = spec.column
        identity = _id("period", column.column_id)
        terms = tuple(_reference(ref, sign) for ref, sign in spec.terms or ())
        end = date.fromisoformat(column.end_date) if column.end_date else None
        start = (
            date.fromordinal(end.toordinal() - column.days + 1)
            if end is not None and column.days is not None and 0 < column.days <= end.toordinal()
            else None
        )
        if column.kind not in {"QUARTER", "PYTD", "YTD", "FY", "LTM"}:
            raise ValueError("Nonhistorical column in period plan")
        node = PeriodConstruction(
            construction_id=identity,
            column_key=column.column_id,
            label=column.label,
            kind=column.kind,
            fiscal_year=column.fiscal_year,
            fiscal_quarter=spec.quarter[1] if spec.quarter else None,
            start_date=start,
            end_date=end,
            days=column.days,
            own_period_id=spec.own,
            stated_period_id=spec.stated,
            terms=terms,
            formula=" + ".join(
                f"({term.coefficient}) * {term.kind}:{term.reference or 'unavailable'}"
                for term in terms
            )
            if spec.terms is not None
            else "reported period observation",
            limitation=spec.unbuilt,
        )
        existing = result.get(identity)
        if existing is not None:
            if existing != node:
                raise ValueError(f"Ambiguous kernel period construction: {column.column_id}")
            return
        result[identity] = node
        for ref, _ in spec.terms or ():
            if isinstance(ref, _Spec):
                visit(ref)

    for spec in specs:
        visit(spec)
    return tuple(result.values())


def _value(
    cell: Cell,
    observations: dict[str, Observation],
    evidence: dict[tuple[str, str], tuple[Citation, ...]],
    normalizations: dict[str, FacilityNormalization],
) -> PeriodValue:
    sources: tuple[SourceRef, ...] = cell.sources or cell.input_sources
    normalized = tuple(
        dict.fromkeys(
            ref.source_id for ref in sources if ref.source_locator == "facility-normalization"
        )
    )
    ids = tuple(
        dict.fromkeys(
            [ref.source_id for ref in sources if ref.source_locator == "financial-observation"]
            + [
                oid
                for identity in normalized
                for oid in normalizations[identity].input_observation_ids
            ]
        )
    )
    issuance = tuple(
        dict.fromkeys(
            ref.source_id for ref in sources if ref.source_locator.startswith("facility-issuance:")
        )
    )
    source = observations.get(ids[0]) if len(ids) == 1 else None
    classification: Literal["source", "normalized", "calculated"] = "calculated"
    if cell.basis == "REPORTED" or cell.input_sources:
        classification = (
            "source"
            if not normalized and source is not None and cell.value == source.amount
            else "normalized"
        )
    status: CalculationStatus = "Calculated"
    if cell.value is None:
        status = (
            "Not Available"
            if cell.reason in {"NOT_SOURCED", "NOT_APPLICABLE"}
            else "Not Calculable"
        )
    elif classification == "source":
        status = "Verified"
    return PeriodValue(
        amount=cell.value,
        stated_amount=cell.stated,
        value_class=classification,
        calculation_status=status,
        reason=cell.reason,
        note=cell.note,
        observation_ids=ids,
        issuance_facility_ids=issuance,
        normalization_ids=normalized,
        citations=tuple(
            dict.fromkeys(
                citation
                for ref in sources
                for citation in evidence[ref.source_locator, ref.source_id]
            )
        ),
    )


def _evidence(
    book: FinancialBook, normalizations: dict[str, FacilityNormalization]
) -> dict[tuple[str, str], tuple[Citation, ...]]:
    result = {
        ("financial-observation", value.observation_id): (
            *value.citations,
            *(citation for alternative in value.alternatives for citation in alternative.citations),
        )
        for value in records(book, Observation)
    }
    for line in book.statement_lines:
        key = "financial-observation", line.value.observation_id
        result[key] = (*result[key], *line.sign_citations)
    for facility in book.facilities:
        if facility.issued_on:
            key = f"facility-issuance:{book.book_id}", facility.facility_id
            result[key] = (*result.get(key, ()), *facility.issuance_citations)
    for value in normalizations.values():
        result["facility-normalization", value.normalization_id] = value.citations
    return result


def _inputs(regs: Cp1Registers) -> tuple[HistoricalInput, ...]:
    rows = (
        *((f"acct:{r.metric_id}", r.period_id, r.value, r.source) for r in regs.accounts),
        *((f"bu:{r.segment_id}", r.period_id, r.revenue, r.source) for r in regs.segments),
        *((f"addback:{r.addback_id}", r.period_id, r.value, r.source) for r in regs.addbacks),
        *((f"kpi:{r.kpi_id}", r.period_id, r.value, r.source) for r in regs.kpis),
        *(
            (f"fac:{r.facility_id}", r.period_id, r.carrying_value, r.source)
            for r in regs.facilities
        ),
    )
    return tuple(
        HistoricalInput(
            series_key=key,
            period_id=period,
            adapter_amount=amount,
            observation_id=ref.source_id
            if ref and ref.source_locator == "financial-observation"
            else None,
            issuance_facility_id=ref.source_id
            if ref and ref.source_locator.startswith("facility-issuance:")
            else None,
            normalization_id=ref.source_id
            if ref and ref.source_locator == "facility-normalization"
            else None,
        )
        for key, period, amount, ref in rows
    )


def _unit(book: FinancialBook, key: str) -> tuple[str, str | None]:
    if key.startswith("kpi:"):
        row = next(row for row in book.kpis if row.kpi_id == key.removeprefix("kpi:"))
        return row.unit, None
    if key == "acct:effective_tax_rate":
        return "PERCENT", None
    return book.unit, book.currency


def historical_report(
    pack: PreparedPack, review: FinancialReview, book_id: str
) -> HistoricalReport:
    regs = kernel_registers(pack, review, book_id)
    review = FinancialReview.model_validate_json(review.model_dump_json())
    book = next(book for book in review.books if book.book_id == book_id)
    observations = {value.observation_id: value for value in records(book, Observation)}
    normalizations = {n.normalization_id: n for n in normalize_facilities(book)}
    evidence = _evidence(book, normalizations)
    specs = _plan(regs)
    series = history._series(regs)
    register = history._register(regs)
    values: list[HistoricalValue] = []
    with localcontext(CONTEXT):
        for spec in specs:
            construction_id = _id("period", spec.column.column_id)
            for key, data in series.items():
                operands = (
                    tuple(
                        ConstructionOperand(
                            reference=_reference(ref, sign),
                            value=_value(
                                history._term(data, register, ref),
                                observations,
                                evidence,
                                normalizations,
                            ),
                        )
                        for ref, sign in spec.terms
                    )
                    if spec.terms is not None and data.kind in {"flow", "sparse"}
                    else ()
                )
                cell = history._read(key, data, register, spec)
                unit, currency = _unit(book, key)
                values.append(
                    HistoricalValue(
                        value_id=_id("historical", spec.column.column_id, key),
                        construction_id=construction_id,
                        series_key=key,
                        series_kind=data.kind,
                        unit=unit,
                        currency=currency,
                        value=_value(cell, observations, evidence, normalizations),
                        operands=operands,
                        formula=(
                            "sum(coefficient * operand amount); "
                            "all required components must be known"
                            if operands
                            else "closing balance at column end date"
                            if data.kind == "balance"
                            else "exact-period observation"
                            if data.kind == "exact"
                            else "reported flow or complete explicitly supported component coverage"
                        ),
                    )
                )
    return HistoricalReport(
        run_id=review.run_id,
        issuer_id=review.issuer_id,
        as_of=review.as_of,
        pack_sha256=review.pack_sha256,
        review_sha256=review.content_hash(),
        book_id=book_id,
        entity_perimeter=book.entity_perimeter,
        accounting_basis=book.accounting_basis,
        currency=book.currency,
        scale=book.unit,
        periods=book.periods,
        observations=tuple(records(book, Observation)),
        facility_normalizations=tuple(normalizations.values()),
        input_rows=_inputs(regs),
        columns=tuple(_id("period", spec.column.column_id) for spec in specs),
        constructions=_constructions(specs),
        values=tuple(values),
        limitations=(
            "Historical input series and period constructions only; statement/ratio calculations "
            "and Model readiness are separate",
            "Verified denotes a retained located source observation, "
            "not independent analytical qualification",
            "Source interpretation, normalization and reporting precision "
            "require analytical review",
            *book.limitations,
        ),
    )


def validate_historical_report(
    pack: PreparedPack, review: FinancialReview, report: HistoricalReport
) -> tuple[str, ...]:
    try:
        report = HistoricalReport.model_validate_json(report.model_dump_json())
        expected = historical_report(pack, review, report.book_id)
    except ValueError as error:
        return (f"Invalid historical inputs: {error}",)
    return (
        ()
        if report.content_hash() == expected.content_hash()
        else ("Historical artifact differs from deterministic recomputation",)
    )
