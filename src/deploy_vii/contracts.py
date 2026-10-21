"""Versioned immutable evidence and report contracts. Decimal values serialize as strings."""

import hashlib
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", max_length=160)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1)]
Status = Literal[
    "unrun",
    "candidate",
    "accepted",
    "restricted",
    "blocked",
    "stale",
    "rejected",
    "not_in_pathway",
]
InputStatus = Literal["accepted", "restricted", "blocked"]
PathwayId = Literal[
    "credit_snapshot",
    "earnings_update",
    "relative_value",
    "covenant_refinancing",
    "distressed_restructuring",
    "portfolio_decision",
]
# Requested module set per Pathway (decision 0009). Required producers are added when a view
# or plan is built (registry.dependencies), so these list the modules the Front Page asks for.
_PRESETS: dict[PathwayId, tuple[str, ...]] = {
    "credit_snapshot": ("CP-0", "CP-1", "CP-1A", "CP-2", "CP-4", "CP-3", "CP-5", "CP-6"),
    "earnings_update": ("CP-0", "CP-1", "CP-1B", "CP-1D", "CP-5"),
    "relative_value": ("CP-0", "CP-1", "CP-1C", "CP-2", "CP-2D", "CP-3", "CP-3C", "CP-3D", "CP-5"),
    "covenant_refinancing": ("CP-0", "CP-1", "CP-1A", "CP-2", "CP-2D", "CP-4", "CP-3C", "CP-5"),
    "distressed_restructuring": (
        *("CP-0", "CP-1", "CP-1A", "CP-2", "CP-2A", "CP-2G", "CP-2H", "CP-4", "CP-4C", "CP-5"),
    ),
    "portfolio_decision": ("CP-0", "CP-1", "CP-2", "CP-3", "CP-5", "CP-6", "CP-8"),
}
PATHWAY_MODULES: Mapping[PathwayId, tuple[str, ...]] = MappingProxyType(_PRESETS)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    def content_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class Run(Contract):
    schema_version: Literal["run/2"] = "run/2"
    run_id: Identifier
    issuer_id: Identifier
    issuer_name: Text
    as_of: date
    method_version: Literal["deploy-v-r14"] = "deploy-v-r14"
    case_kind: Literal["public", "private", "synthetic"]
    pathway: PathwayId = "credit_snapshot"
    # Defaults to the Pathway's preset; an explicit value overrides it and is what executes.
    requested_modules: tuple[str, ...] = Field(
        min_length=1,
        default_factory=lambda data: PATHWAY_MODULES[data.get("pathway", "credit_snapshot")],
    )


class Span(Contract):
    locator: Text
    text: str
    formula: str | None = None
    cached_value: str | None = None
    hidden: bool = False
    data_type: str | None = None
    number_format: str | None = None
    note: str | None = None


class Coverage(Contract):
    locator: Text
    status: Literal["retained", "unreadable", "empty"]
    limitation: str | None = None


class Source(Contract):
    schema_version: Literal["source/1"] = "source/1"
    source_id: Identifier
    name: Text
    status: Literal["ready", "missing", "unreadable"]
    sha256: Hash | None = None
    media_type: str | None = None
    spans: tuple[Span, ...] = ()
    limitation: str | None = None
    extractor: Text = "supplied-representation"
    extraction_status: Literal["complete", "degraded", "blocked"] = "degraded"
    coverage: tuple[Coverage, ...] = ()

    @model_validator(mode="after")
    def evidence_status(self) -> Self:
        if self.status == "ready" and (not self.sha256 or not self.spans):
            raise ValueError("ready source requires hash and located content")
        if self.status != "ready" and not self.limitation:
            raise ValueError("unavailable source requires limitation")
        if self.status == "missing" and (self.sha256 or self.spans):
            raise ValueError("missing source cannot have content")
        if len({span.locator for span in self.spans}) != len(self.spans):
            raise ValueError("duplicate source locators")
        if len({item.locator for item in self.coverage}) != len(self.coverage):
            raise ValueError("duplicate coverage locators")
        if self.status == "ready" and self.extraction_status == "blocked":
            raise ValueError("blocked extraction cannot supply ready evidence")
        if self.extraction_status == "complete" and (
            self.status != "ready" or any(item.status != "retained" for item in self.coverage)
        ):
            raise ValueError("complete extraction requires readable and retained coverage")
        return self


class Citation(Contract):
    source_id: Identifier
    source_sha256: Hash
    locator: Text
    quote: Text


class Input(Contract):
    """A bound input; a module input carries its producer's status (decision 0007)."""

    input_id: Identifier
    sha256: Hash
    status: InputStatus = "accepted"


class Fact(Contract):
    fact_id: Identifier
    label: Text
    table_id: Identifier = "summary"
    row_id: Identifier = "summary"
    field: Identifier = "value"
    amount: Decimal | None = None
    text: str | None = None
    status: Literal["known", "missing", "conflicting", "not_applicable"] = "known"
    unit: str | None = None
    currency: str | None = None
    scale: Decimal = Decimal(1)
    # Displayed decimal places of a per-unit amount (a share price keeps its cents); None means
    # the unit class's own precision, so statement lines stay at 0 dp. Ignored on the exact-text
    # path (no unit class, or an exponent beyond 100), where the exact decimal is shown.
    decimals: int | None = None
    period: str | None = None
    basis: str | None = None
    denominator: str | None = None
    citations: tuple[Citation, ...] = ()
    calculation_id: Identifier | None = None
    value_class: Literal["source", "normalized", "calculated", "analyst_judgment"] | None = None
    source_amount: Decimal | None = None
    stated_amount: Decimal | None = None
    calculation_status: Text | None = None
    formula: Text | None = None
    limitation: str | None = None

    @model_validator(mode="after")
    def value_semantics(self) -> Self:
        if self.scale <= 0:
            raise ValueError("scale must be positive")
        if self.decimals is not None and not 0 <= self.decimals <= 6:
            raise ValueError("decimals must be between 0 and 6")
        if self.amount is not None and self.text is not None:
            raise ValueError("fact cannot contain both amount and text")
        if self.status == "known" and self.amount is None and self.text is None:
            raise ValueError("known fact requires a value")
        if self.status != "known" and (self.amount is not None or self.text is not None):
            raise ValueError("unsettled fact cannot carry a settled value")
        if self.status != "known" and not self.limitation:
            raise ValueError("unsettled fact requires a limitation")
        if self.amount is not None and (not self.unit or not self.period):
            raise ValueError("numeric fact requires explicit unit and period")
        return self


class Claim(Contract):
    claim_id: Identifier
    text: Text
    citations: tuple[Citation, ...]
    limitation: str | None = None


class Calculation(Contract):
    schema_version: Literal["calculation/1"] = "calculation/1"
    calculation_id: Identifier
    method: Text
    method_version: Text
    formula: Text
    inputs: tuple[Input, ...]
    output: Fact
    limitations: tuple[str, ...] = ()


class TableColumn(Contract):
    field: Identifier
    label: Text


class TableRow(Contract):
    row_id: Identifier
    label: Text
    fact_ids: tuple[Identifier, ...]
    # How the row is drawn; the layout declares it, the page never infers it from the label.
    row_kind: Literal["row", "subtotal", "total", "memo"] = "row"


class ReportTable(Contract):
    """Layout references canonical facts; it never stores replacement values."""

    table_id: Identifier
    title: Text
    columns: Annotated[tuple[TableColumn, ...], Field(min_length=1)]
    rows: tuple[TableRow, ...]
    row_header: Text | None = None
    interface_id: Identifier | None = None
    limitation: Text | None = None


def validate_tables(tables: tuple[ReportTable, ...], facts: tuple[Fact, ...]) -> None:
    """Validate declared layouts against canonical facts; permit undeclared tables."""
    if len({table.table_id for table in tables}) != len(tables):
        raise ValueError("Duplicate report table")
    interface_ids = [table.interface_id for table in tables if table.interface_id is not None]
    if len(interface_ids) != len(set(interface_ids)):
        raise ValueError("Duplicate table interface identity")
    facts_by_id = {fact.fact_id: fact for fact in facts}
    if len(facts_by_id) != len(facts):
        raise ValueError("Duplicate fact identity")

    for table in tables:
        if table.interface_id and (
            table.row_header is not None
            or any(column.label != column.field for column in table.columns)
        ):
            raise ValueError(
                "Interface table requires exact field headings without an extra row header"
            )
        column_fields = [column.field for column in table.columns]
        if len(column_fields) != len(set(column_fields)):
            raise ValueError("Duplicate report column")
        if len({row.row_id for row in table.rows}) != len(table.rows):
            raise ValueError("Duplicate report row")

        referenced_fact_ids: set[str] = set()
        for row in table.rows:
            if len(row.fact_ids) != len(column_fields):
                raise ValueError("Report row does not match its columns")
            for field, fact_id in zip(column_fields, row.fact_ids, strict=True):
                fact = facts_by_id.get(fact_id)
                if fact_id in referenced_fact_ids or fact is None:
                    raise ValueError("Report cell repeats or references an unknown fact")
                if (fact.table_id, fact.row_id, fact.field) != (table.table_id, row.row_id, field):
                    raise ValueError("Report cell differs from its canonical fact coordinates")
                referenced_fact_ids.add(fact_id)
        canonical_fact_ids = {fact.fact_id for fact in facts if fact.table_id == table.table_id}
        if referenced_fact_ids != canonical_fact_ids:
            raise ValueError("Declared report table omits canonical facts")


class Module(Contract):
    schema_version: Literal["module/5"] = "module/5"
    run_id: Identifier
    issuer_id: Identifier
    as_of: date
    method_version: Literal["deploy-v-r14"] = "deploy-v-r14"
    module_id: Identifier
    status: Status = "candidate"
    inputs: tuple[Input, ...] = ()
    facts: tuple[Fact, ...] = ()
    tables: tuple[ReportTable, ...] = ()
    claims: tuple[Claim, ...] = ()
    limitations: tuple[str, ...] = ()
    inherited_limitations: tuple[str, ...] = ()
    attempt: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def distinct_records(self) -> Self:
        validate_tables(self.tables, self.facts)
        for identities in (
            [fact.fact_id for fact in self.facts],
            [claim.claim_id for claim in self.claims],
            [item.input_id for item in self.inputs],
        ):
            if len(set(identities)) != len(identities):
                raise ValueError("duplicate artifact record identity")
        if self.status in {"restricted", "blocked", "stale", "rejected"} and not (
            self.limitations or self.inherited_limitations
        ):
            raise ValueError("limited artifact requires explicit limitations")
        if self.status in {"unrun", "not_in_pathway"} and (
            self.facts or self.claims or self.tables
        ):
            raise ValueError(f"{self.status} module cannot carry outputs")
        return self


class ModuleView(Contract):
    module_id: Identifier
    title: Text
    aliases: tuple[str, ...]
    status: Status = "unrun"
    artifact_sha256: Hash | None = None
    facts: tuple[Fact, ...] = ()
    tables: tuple[ReportTable, ...] = ()
    claims: tuple[Claim, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def output_identity(self) -> Self:
        validate_tables(self.tables, self.facts)
        if (self.facts or self.claims or self.tables) and not self.artifact_sha256:
            raise ValueError("view outputs require an artifact hash")
        if self.status in {"unrun", "not_in_pathway"} and (
            self.facts or self.claims or self.tables or self.artifact_sha256
        ):
            raise ValueError(f"{self.status} view cannot contain outputs")
        return self


class View(Contract):
    schema_version: Literal["view/4"] = "view/4"
    run: Run
    mode: Literal["candidate", "accepted"]
    modules: tuple[ModuleView, ...]
    sources: tuple[Source, ...] = ()
    analytical_qualification: Literal["unrun", "partial", "qualified", "blocked"] = "unrun"
    native_host_qualification: Literal["unrun", "qualified", "blocked"] = "unrun"

    @model_validator(mode="after")
    def snapshot_status(self) -> Self:
        if len({module.module_id for module in self.modules}) != len(self.modules):
            raise ValueError("duplicate view module")
        if self.mode == "accepted" and any(
            module.status
            not in {"accepted", "restricted", "unrun", "not_in_pathway", "blocked", "stale"}
            for module in self.modules
        ):
            raise ValueError("accepted view cannot contain candidate or rejected outputs")
        return self
