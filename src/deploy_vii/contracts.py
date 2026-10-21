"""Versioned immutable evidence and report contracts. Decimal values serialize as strings."""

import hashlib
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", max_length=160)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1)]
Status = Literal["unrun", "candidate", "accepted", "restricted", "blocked", "stale", "rejected"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    def content_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class Run(Contract):
    schema_version: Literal["run/1"] = "run/1"
    run_id: Identifier
    issuer_id: Identifier
    issuer_name: Text
    as_of: date
    method_version: Literal["deploy-v-r14"] = "deploy-v-r14"
    case_kind: Literal["public", "private", "synthetic"]
    requested_modules: tuple[str, ...] = (
        "CP-0",
        "CP-1",
        "CP-1A",
        "CP-2",
        "CP-4",
        "CP-3",
        "CP-5",
        "CP-6",
    )


class Span(Contract):
    locator: Text
    text: str
    formula: str | None = None
    cached_value: str | None = None
    hidden: bool = False


class Source(Contract):
    schema_version: Literal["source/1"] = "source/1"
    source_id: Identifier
    name: Text
    status: Literal["ready", "missing", "unreadable"]
    sha256: Hash | None = None
    media_type: str | None = None
    spans: tuple[Span, ...] = ()
    limitation: str | None = None

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
        return self


class Citation(Contract):
    source_id: Identifier
    source_sha256: Hash
    locator: Text
    quote: Text


class Input(Contract):
    input_id: Identifier
    sha256: Hash


class Fact(Contract):
    fact_id: Identifier
    label: Text
    table_id: Identifier = "summary"
    row_id: Identifier = "summary"
    field: Identifier = "value"
    amount: Decimal | None = None
    text: str | None = None
    status: Literal["known", "missing", "conflicting"] = "known"
    unit: str | None = None
    currency: str | None = None
    scale: Decimal = Decimal(1)
    period: str | None = None
    basis: str | None = None
    denominator: str | None = None
    citations: tuple[Citation, ...] = ()
    calculation_id: Identifier | None = None
    limitation: str | None = None

    @model_validator(mode="after")
    def value_semantics(self) -> Self:
        if self.scale <= 0:
            raise ValueError("scale must be positive")
        if self.amount is not None and self.text is not None:
            raise ValueError("fact cannot contain both amount and text")
        if self.status == "known" and self.amount is None and self.text is None:
            raise ValueError("known fact requires a value")
        if self.status != "known" and (self.amount is not None or self.text is not None):
            raise ValueError("missing/conflicting fact cannot carry a settled value")
        if self.status != "known" and not self.limitation:
            raise ValueError("missing/conflicting fact requires a limitation")
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


class Module(Contract):
    schema_version: Literal["module/1"] = "module/1"
    run_id: Identifier
    issuer_id: Identifier
    as_of: date
    method_version: Literal["deploy-v-r14"] = "deploy-v-r14"
    module_id: Identifier
    status: Status = "candidate"
    inputs: tuple[Input, ...] = ()
    facts: tuple[Fact, ...] = ()
    claims: tuple[Claim, ...] = ()
    limitations: tuple[str, ...] = ()
    attempt: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def distinct_records(self) -> Self:
        for identities in (
            [fact.fact_id for fact in self.facts],
            [claim.claim_id for claim in self.claims],
            [item.input_id for item in self.inputs],
        ):
            if len(set(identities)) != len(identities):
                raise ValueError("duplicate artifact record identity")
        if self.status in {"restricted", "blocked", "stale", "rejected"} and not self.limitations:
            raise ValueError("limited artifact requires explicit limitations")
        if self.status == "unrun" and (self.facts or self.claims):
            raise ValueError("unrun module cannot carry outputs")
        return self


class ModuleView(Contract):
    module_id: Identifier
    title: Text
    aliases: tuple[str, ...]
    status: Status = "unrun"
    artifact_sha256: Hash | None = None
    facts: tuple[Fact, ...] = ()
    claims: tuple[Claim, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def output_identity(self) -> Self:
        if (self.facts or self.claims) and not self.artifact_sha256:
            raise ValueError("view outputs require an artifact hash")
        if self.status == "unrun" and (self.facts or self.claims or self.artifact_sha256):
            raise ValueError("unrun view cannot contain outputs")
        return self


class View(Contract):
    schema_version: Literal["view/1"] = "view/1"
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
            module.status not in {"accepted", "restricted", "unrun", "blocked", "stale"}
            for module in self.modules
        ):
            raise ValueError("accepted view cannot contain candidate or rejected outputs")
        return self
