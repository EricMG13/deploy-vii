"""Internal register rows and vocabularies for the deterministic calculation kernel.

Adapted from the pinned Deploy VI model slice; provenance is recorded in
`docs/review-evidence/model-port-sources.json`. These dataclasses are not an
external input contract. Callers must validate evidence, numbers, identity,
period graphs, units and missingness before calculation. No legacy parser or
host state is imported. See `docs/development/model-reuse.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from deploy_vii.model.dates import fiscal_year_number as fiscal_year_number
from deploy_vii.model.dates import iso_date as iso_date
from deploy_vii.model.frame import SourceRef

PERIOD_TYPES = frozenset({"QUARTER", "YTD", "FY", "LTM", "PERIOD_END"})
PERIOD_UNITS = frozenset({"UNITS", "THOUSANDS", "MILLIONS"})
CALCULATION_STATUSES = frozenset(
    {
        "VERIFIED",
        "CALCULATED",
        "ESTIMATED",
        "PROXY",
        "NOT CALCULABLE",
        "PARTIAL",
        "CONFLICTED",
        "NOT AVAILABLE",
    }
)
ADDBACK_CLASSIFICATIONS = frozenset(
    {
        "RESTRUCTURING",
        "SBC",
        "COST_SAVINGS",
        "RUN_RATE",
        "SYNERGY",
        "TRANSACTION_COSTS",
        "OTHER_EXPLICIT",
    }
)
REALIZATION_STATUSES = frozenset({"REALIZED", "UNREALIZED", "NOT_STATED"})
SEGMENT_TYPES = frozenset({"OPERATING_SEGMENT", "CORPORATE_ELIMINATION"})
KPI_VALUE_TYPES = frozenset({"PERIOD_END", "PERIOD_FLOW", "RATE"})
SECURED_STATUSES = frozenset({"SECURED", "UNSECURED", "NOT_STATED"})
SENIORITIES = frozenset(
    {"SUPER_SENIOR", "SENIOR", "SENIOR_SUBORDINATED", "SUBORDINATED", "JUNIOR", "NOT_STATED"}
)
LEASE_CLASSIFICATIONS = frozenset({"FINANCE_LEASE", "OPERATING_LEASE", "NOT_LEASE", "NOT_STATED"})
PF_CLASSIFICATIONS = frozenset(
    {
        "ACQUISITION",
        "DISPOSAL",
        "REFINANCING",
        "SUBSEQUENT_EVENT",
        "LENDER_UPDATE",
        "OTHER_EXPLICIT",
    }
)
RATE_TYPES = frozenset({"FIXED", "FLOATING", "NOT_STATED"})
REFERENCE_RATES = frozenset({"SOFR", "TERM_SOFR", "EURIBOR", "SONIA", "NONE", "NOT_STATED"})
FACILITY_TYPES = frozenset({"DEBT ADJUSTMENT"})  # open: other text reads in upper case


@dataclass(frozen=True, slots=True)
class PeriodRow:
    period_id: str
    fiscal_year: str
    fiscal_quarter: str | None
    period_type: str  # QUARTER|YTD|FY|LTM|PERIOD_END
    start_date: str | None
    end_date: str | None
    day_count: int | None
    currency: str
    unit: str
    component_period_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AccountRow:
    metric_id: str
    period_id: str
    value: Decimal | None
    calculation_status: str
    source: SourceRef | None


@dataclass(frozen=True, slots=True)
class AddbackRow:
    addback_id: str
    label: str
    classification: str
    realization_status: str
    display_priority: int
    period_id: str
    value: Decimal | None
    source: SourceRef | None


@dataclass(frozen=True, slots=True)
class SegmentRow:
    segment_id: str
    segment_name: str
    segment_type: str
    display_priority: int
    period_id: str
    revenue: Decimal | None
    source: SourceRef | None


@dataclass(frozen=True, slots=True)
class KpiRow:
    kpi_id: str
    kpi_label: str
    display_priority: int
    period_id: str
    value: Decimal | None
    unit: str
    value_type: str  # PERIOD_END|PERIOD_FLOW|RATE
    source: SourceRef | None


@dataclass(frozen=True, slots=True)
class FacilityRow:
    facility_id: str
    facility_name: str
    period_id: str
    facility_type: str
    currency: str
    carrying_value: Decimal | None
    commitment: Decimal | None
    drawn_amount: Decimal | None
    secured_status: str
    seniority: str
    lease_classification: str
    maturity_date: str | None
    margin_or_coupon: str
    rate_type: str
    reference_rate: str
    spread_bps: Decimal | None
    floor_bps: Decimal | None
    fixed_rate: Decimal | None
    annual_amortisation: Decimal | None
    source: SourceRef | None
    terms_out_of_range: bool = False


@dataclass(frozen=True, slots=True)
class PfAdjustmentRow:
    adjustment_id: str
    label: str
    period_id: str
    classification: str
    metric_id: str
    value: Decimal
    source: SourceRef | None


@dataclass(frozen=True, slots=True)
class Cp1Registers:
    periods: tuple[PeriodRow, ...]
    accounts: tuple[AccountRow, ...]
    addbacks: tuple[AddbackRow, ...]
    segments: tuple[SegmentRow, ...]
    kpis: tuple[KpiRow, ...]
    facilities: tuple[FacilityRow, ...]
    pro_forma: tuple[PfAdjustmentRow, ...]
    currency: str
    unit: str
