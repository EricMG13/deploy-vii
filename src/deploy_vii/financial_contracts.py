"""CP-1 source observations, before Python normalization or calculation.

One book is one entity perimeter/accounting basis/currency/unit. Multiple books
preserve industrial/finance and other distinct perimeters without blending them.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from deploy_vii.contracts import Citation, Claim, Contract, Hash, Identifier, Text
from deploy_vii.model.dates import fiscal_year_number
from deploy_vii.model.history import BALANCE_METRICS, FLOW_METRICS

Number = Annotated[
    Decimal,
    Field(gt=Decimal("-1e18"), lt=Decimal("1e18"), max_digits=28, decimal_places=10),
]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Unit = Literal["UNITS", "THOUSANDS", "MILLIONS"]
Located = Annotated[tuple[Citation, ...], Field(min_length=1)]
ACCOUNT_IDS = FLOW_METRICS | BALANCE_METRICS | {"effective_tax_rate"}


class Alternative(Contract):
    amount: Number
    citations: Located
    explanation: Text


class Observation(Contract):
    """A source value or explicit gap; arithmetic results use Calculation instead."""

    observation_id: Identifier
    status: Literal["known", "missing", "conflicting", "not_applicable"]
    amount: Number | None
    citations: tuple[Citation, ...]
    reason: Text | None = None
    alternatives: tuple[Alternative, ...] = ()

    @model_validator(mode="after")
    def value_state(self) -> Self:
        if self.status == "known":
            if self.amount is None or not self.citations or self.alternatives:
                raise ValueError("known observation requires amount and citations, no alternatives")
        elif self.amount is not None or not self.reason:
            raise ValueError("unsettled observation requires null amount and a reason")
        if self.status == "conflicting":
            if len(self.alternatives) < 2 or len(set(self.alternatives)) != len(self.alternatives):
                raise ValueError("conflict requires at least two distinct located alternatives")
        elif self.alternatives:
            raise ValueError("only a conflict may contain alternatives")
        return self


class Disclosure(Contract):
    status: Literal["complete", "partial", "not_disclosed", "not_applicable"]
    explanation: Text
    citations: Located


class FinancialPeriod(Contract):
    period_id: Identifier
    fiscal_year: Text
    fiscal_quarter: int | None = Field(ge=1, le=4)
    period_type: Literal["QUARTER", "YTD", "FY", "LTM", "PERIOD_END"]
    start_date: date | None
    end_date: date | None
    day_count: int | None = Field(ge=1, le=110000)
    audit_status: Text
    currency: Currency
    unit: Unit
    accounting_basis: Text
    entity_perimeter: Text
    citations: tuple[Citation, ...]
    component_period_ids: tuple[Identifier, ...] = ()
    expense_presentation: Literal["by_function", "by_nature", "unknown"] = "unknown"
    presentation_citations: tuple[Citation, ...] = ()
    limitation: Text | None = None

    @model_validator(mode="after")
    def span(self) -> Self:
        year = fiscal_year_number(self.fiscal_year)
        if year is None or not 1900 <= year <= 2200:
            raise ValueError("fiscal year must identify a year in 1900-2200")
        for day in (self.start_date, self.end_date):
            if day is not None and not 1900 <= day.year <= 2200:
                raise ValueError("period date outside 1900-2200")
        if self.end_date and abs(year - self.end_date.year) > 1:
            raise ValueError("fiscal year differs from end date by more than a year")
        if self.start_date and self.end_date:
            days = (self.end_date - self.start_date).days + 1
            if days <= 0 or (self.day_count is not None and self.day_count != days):
                raise ValueError("period dates and day count disagree")
        elif not self.limitation:
            raise ValueError("missing period dates require a limitation")
        if self.period_type == "QUARTER" and self.fiscal_quarter is None:
            raise ValueError("quarter requires fiscal quarter")
        if not self.citations and not self.component_period_ids:
            raise ValueError("period requires located evidence or component periods")
        if self.expense_presentation != "unknown" and not self.presentation_citations:
            raise ValueError("expense presentation requires evidence")
        return self


class AccountObservation(Contract):
    metric_id: Identifier
    period_id: Identifier
    value: Observation

    @model_validator(mode="after")
    def controlled_metric(self) -> Self:
        if self.metric_id not in ACCOUNT_IDS:
            raise ValueError("unknown CP-1 account metric")
        return self


class AddbackObservation(Contract):
    addback_id: Identifier
    addback_label: Text
    classification: Literal[
        "RESTRUCTURING",
        "SBC",
        "COST_SAVINGS",
        "RUN_RATE",
        "SYNERGY",
        "TRANSACTION_COSTS",
        "OTHER_EXPLICIT",
    ]
    realization_status: Literal["REALIZED", "UNREALIZED", "NOT_STATED"]
    display_priority: int = Field(ge=1)
    period_id: Identifier
    value: Observation
    source_definition: Text
    classification_citations: Located


class SegmentObservation(Contract):
    segment_id: Identifier
    segment_name: Text
    segment_type: Literal["OPERATING_SEGMENT", "CORPORATE_ELIMINATION"]
    display_priority: int = Field(ge=1)
    period_id: Identifier
    revenue: Observation
    classification_citations: Located


class SegmentAllocation(Contract):
    slot_id: Literal["DIVISION_1", "DIVISION_2", "DIVISION_3"]
    slot_label: Text
    component_segment_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    rationale: Text


class KpiObservation(Contract):
    kpi_id: Identifier
    kpi_label: Text
    business_unit: Text
    kpi_category: Text
    definition: Text
    display_priority: int = Field(ge=1)
    period_id: Identifier
    value: Observation
    unit: Text
    value_type: Literal["PERIOD_END", "PERIOD_FLOW", "RATE"]
    definition_citations: Located


class FacilityObservation(Contract):
    facility_id: Identifier
    facility_name: Text
    period_id: Identifier
    facility_type: Text
    currency: Currency
    carrying_value: Observation
    principal: Observation
    drawn_amount: Observation
    commitment: Observation
    secured_status: Literal["SECURED", "UNSECURED", "NOT_STATED"]
    seniority: Literal[
        "SUPER_SENIOR", "SENIOR", "SENIOR_SUBORDINATED", "SUBORDINATED", "JUNIOR", "NOT_STATED"
    ]
    lease_classification: Literal["FINANCE_LEASE", "OPERATING_LEASE", "NOT_LEASE", "NOT_STATED"]
    margin_or_coupon: Text
    maturity_date: date | None
    maturity_limitation: Text | None
    rate_type: Literal["FIXED", "FLOATING", "NOT_STATED"]
    reference_rate: Literal["SOFR", "TERM_SOFR", "EURIBOR", "SONIA", "NONE", "NOT_STATED"]
    spread_bps: Observation
    floor_bps: Observation
    fixed_rate: Observation
    annual_amortisation: Observation
    terms_citations: Located
    issued_on: date | None = None
    issuance_citations: tuple[Citation, ...] = ()

    @model_validator(mode="after")
    def terms(self) -> Self:
        if self.maturity_date is None and not self.maturity_limitation:
            raise ValueError("missing maturity requires limitation")
        if self.issued_on is not None and not self.issuance_citations:
            raise ValueError("issuance date requires evidence")
        for field in ("principal", "drawn_amount", "commitment", "annual_amortisation"):
            if (value := getattr(self, field).amount) is not None and value < 0:
                raise ValueError(f"{field} cannot be negative")
        if (value := self.carrying_value.amount) is not None and value < 0:
            if self.facility_type != "DEBT ADJUSTMENT":
                raise ValueError("only DEBT ADJUSTMENT may have negative carrying value")
        for value in (self.spread_bps.amount, self.floor_bps.amount):
            if value is not None and value != value.to_integral_value():
                raise ValueError("spread/floor must use whole basis points")
        if self.rate_type != "FIXED" and self.fixed_rate.amount is not None:
            raise ValueError("fixed coupon requires FIXED rate type")
        if self.rate_type == "FIXED" and self.spread_bps.amount is not None:
            raise ValueError("fixed instrument cannot also carry a spread")
        return self


class ProFormaObservation(Contract):
    adjustment_id: Identifier
    event_id: Identifier
    label: Text
    period_id: Identifier
    effective_date: date
    announced_on: date
    event_status: Literal["completed", "announced", "proposed"]
    classification: Literal[
        "ACQUISITION",
        "DISPOSAL",
        "REFINANCING",
        "SUBSEQUENT_EVENT",
        "LENDER_UPDATE",
        "OTHER_EXPLICIT",
    ]
    metric_id: Identifier
    value: Observation
    event_citations: Located


class StatementLine(Contract):
    """One located source statement line; issuer-specific detail is never dropped."""

    line_id: Identifier
    statement: Literal["IS", "CFS", "BS"]
    item_id: Identifier
    label: Text
    period_id: Identifier
    display_priority: int = Field(ge=1)
    line_kind: Literal["detail", "subtotal", "total"]
    value: Observation
    sign_convention: Literal["signed", "outflow_magnitude"] = "signed"
    sign_citations: tuple[Citation, ...] = ()

    @model_validator(mode="after")
    def sign_evidence(self) -> Self:
        if self.statement == "BS" and self.sign_convention == "outflow_magnitude":
            raise ValueError("balance-sheet amounts are signed balances, not outflow magnitudes")
        if self.sign_convention == "outflow_magnitude" and not self.sign_citations:
            raise ValueError("outflow magnitude normalization requires source evidence")
        return self


class StatementContribution(Contract):
    line_id: Identifier
    coefficient: Literal[-1, 1]

    @field_validator("coefficient", mode="before")
    @classmethod
    def integer_sign(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("coefficient must be the integer -1 or 1")
        return value


class StatementIdentity(Contract):
    """Source-supported statement structure, not a model-supplied calculation."""

    identity_id: Identifier
    period_id: Identifier
    target_line_id: Identifier
    components: Annotated[tuple[StatementContribution, ...], Field(min_length=1)]
    explanation: Text
    citations: Located


class StatementDisclosure(Contract):
    statement: Literal["IS", "CFS", "BS"]
    period_id: Identifier
    disclosure: Disclosure


class CashMovementBridge(Contract):
    """Cash delta = reported NCF + signed source adjustments; never a plug.

    An empty component list explicitly assesses that no adjustment is needed.
    Components reference detail lines in the same period's source CFS.
    """

    bridge_id: Identifier
    period_id: Identifier
    components: Annotated[tuple[StatementContribution, ...], Field(max_length=20000)]
    explanation: Text
    citations: Located


class AuditBasisExplanation(Contract):
    """Located explanation for one audited FY versus four unaudited quarters."""

    explanation_id: Identifier
    annual_period_id: Identifier
    metric_id: Identifier
    quarter_period_ids: Annotated[tuple[Identifier, ...], Field(min_length=4, max_length=4)]
    annual_observation_sha256: Hash
    quarter_observation_sha256: Annotated[tuple[Hash, ...], Field(min_length=4, max_length=4)]
    explanation: Text
    citations: Located


class FinancialBook(Contract):
    book_id: Identifier
    entity_perimeter: Text
    accounting_basis: Text
    currency: Currency
    unit: Unit
    periods: Annotated[tuple[FinancialPeriod, ...], Field(min_length=1, max_length=200)]
    accounts: Annotated[tuple[AccountObservation, ...], Field(max_length=20000)]
    addbacks: Annotated[tuple[AddbackObservation, ...], Field(max_length=20000)]
    segments: Annotated[tuple[SegmentObservation, ...], Field(max_length=20000)]
    kpis: Annotated[tuple[KpiObservation, ...], Field(max_length=20000)]
    facilities: Annotated[tuple[FacilityObservation, ...], Field(max_length=20000)]
    pro_forma: Annotated[tuple[ProFormaObservation, ...], Field(max_length=20000)]
    statement_lines: Annotated[tuple[StatementLine, ...], Field(max_length=20000)] = ()
    statement_identities: Annotated[tuple[StatementIdentity, ...], Field(max_length=20000)] = ()
    statement_disclosures: tuple[StatementDisclosure, ...] = ()
    cash_movement_bridges: Annotated[tuple[CashMovementBridge, ...], Field(max_length=200)] = ()
    audit_basis_explanations: Annotated[
        tuple[AuditBasisExplanation, ...], Field(max_length=20000)
    ] = ()
    segment_allocation: tuple[SegmentAllocation, ...]
    addback_disclosure: Disclosure
    segment_disclosure: Disclosure
    limitations: tuple[Text, ...] = ()


class FinancialReview(Contract):
    schema_version: Literal["financial-review/3"] = "financial-review/3"
    pack_sha256: Hash
    run_id: Identifier
    issuer_id: Identifier
    as_of: date
    method_version: Literal["deploy-v-r14"] = "deploy-v-r14"
    books: Annotated[tuple[FinancialBook, ...], Field(min_length=1, max_length=20)]
    analysis: tuple[Claim, ...]
    limitations: tuple[Text, ...] = ()
