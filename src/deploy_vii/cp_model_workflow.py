"""CP-MODEL's deterministic publication from a promoted CP-1; Python only, no model call.

Decision 0006 DC-5: CP-MODEL publishes the promoted CP-1 financial model as the Model
destination (an HTML page) and its calculation JSON. `publish_cp_model` builds the CP-MODEL
`Module` in Python, writes the files into a new directory and settles the head only once
every file is written; a failed write interrupts the attempt and leaves no head.
"""

import json
import tempfile
from pathlib import Path

from deploy_vii.contracts import Claim, Fact, Module, ReportTable, TableColumn, TableRow
from deploy_vii.cp1_render import model_destination_html
from deploy_vii.cp1_workflow import (
    CP1_STEPS,
    CP1Handoff,
    FinancialStage,
    write_cp1_envelope,
)
from deploy_vii.execution import (
    Attempt,
    Execution,
    Head,
    Qualification,
    Validator,
    settle,
    text_sha256,
)
from deploy_vii.financial_model import ModelReport

MODULE_ID = "CP-MODEL"
CALCULATION = "calculation.json"
PAGE = "model.html"
RECEIPT = "receipt.json"
RECEIPT_SCHEMA = "cp-model-publication/1"
# A page cannot hold its own hash and the receipt names the head, so neither is in the manifest.
RECORDED_IN_RECEIPT = f"Recorded in {RECEIPT}"
OWN_RESTRICTION = "Published from a restricted CP-1 head; the Model carries its limitations"
CLAIM = (
    "The Model destination and its calculation JSON were published from the promoted CP-1 "
    "head; Python calculated every figure and no model call was made."
)

# The four statuses a publication records on the CP-MODEL head. The contract has no
# `not_applicable` literal for analytical qualification and this task must not invent one, so
# it is `unrun` (no analyst has qualified the Model); the other two stay `unrun` until a
# browser or native-host test qualifies this artifact.
PUBLISHED = Qualification(implementation="implemented")


class CpModelRefused(ValueError):
    """Publication refused or failed; nothing was settled, and a refusal writes no file."""


class _Basis:
    """What a publication binds: the promoted CP-1 head, its handoff and its calculated Model."""

    def __init__(self, head: Head, handoff: CP1Handoff, report: ModelReport) -> None:
        self.head, self.handoff, self.report = head, handoff, report
        self.calculation = report.model_dump_json()


def _basis(store: Execution) -> _Basis:
    """The promoted CP-1 basis, or `CpModelRefused`; a journal that cannot be read is a refusal."""
    try:
        return _read_basis(store)
    except CpModelRefused:
        raise
    except (ValueError, OSError) as error:  # a missing or corrupt blob, an unreadable snapshot
        raise CpModelRefused(f"CP-1 basis cannot be read from the journal: {error}") from error


def _read_basis(store: Execution) -> _Basis:
    snapshot = store.read()
    if MODULE_ID not in snapshot.run.requested_modules:
        raise CpModelRefused("This run does not request CP-MODEL")
    head = next((h for h in snapshot.heads if h.module_id == "CP-1"), None)
    if head is None or head.status not in ("accepted", "restricted"):
        raise CpModelRefused("CP-1 has no accepted or restricted head")
    if head.qualification is None:
        raise CpModelRefused("CP-1 head was not promoted: it records no qualification")
    attempt = next((a for a in snapshot.attempts if a.result_sha256 == head.result_sha256), None)
    quality = len(CP1_STEPS)
    if attempt is None or len(attempt.steps) <= quality:
        raise CpModelRefused("CP-1 head was not promoted through a verified handoff")
    step, financials = attempt.steps[quality], attempt.steps[1]
    if (
        step.step_id != "quality"
        or financials.step_id != "financials"
        or step.output_sha256 is None
        or financials.output_sha256 is None
    ):
        raise CpModelRefused("CP-1 head was not promoted through a verified handoff")
    handoff = CP1Handoff.model_validate_json(store.step_output(step.output_sha256))
    stage = FinancialStage.model_validate_json(store.step_output(financials.output_sha256))
    if stage.model is None:
        reasons = "; ".join(stage.model_issues) or "no calculated KPIs"
        raise CpModelRefused(f"CP-1 retains no calculated Model to publish: {reasons}")
    return _Basis(head, handoff, stage.model)


def _fact(table: str, row: str, field: str, label: str, text: str) -> Fact:
    return Fact(
        fact_id=f"{table}.{row}.{field}",
        label=label,
        table_id=table,
        row_id=row,
        field=field,
        text=text,
    )


def _table(
    table: str,
    title: str,
    header: str,
    columns: tuple[tuple[str, str], ...],
    rows: list[tuple[str, str, tuple[str, ...]]],
) -> tuple[ReportTable, list[Fact]]:
    """One text register: `rows` are (row_id, label, value-per-column) in column order."""
    facts: list[Fact] = []
    layout: list[TableRow] = []
    for row_id, label, values in rows:
        cells = [
            _fact(table, row_id, field, f"{label} {name}", value)
            for (field, name), value in zip(columns, values, strict=True)
        ]
        facts.extend(cells)
        layout.append(
            TableRow(row_id=row_id, label=label, fact_ids=tuple(c.fact_id for c in cells))
        )
    columns_ = tuple(TableColumn(field=field, label=name) for field, name in columns)
    return ReportTable(
        table_id=table, title=title, columns=columns_, rows=tuple(layout), row_header=header
    ), facts


def candidate_module(store: Execution, attempt: Attempt, basis: _Basis) -> Module:
    """The CP-MODEL candidate, built from the journal and the promoted CP-1 alone."""
    snapshot = store.read()
    calculation_sha256 = text_sha256(basis.calculation)
    manifest, manifest_facts = _table(
        "model-destination",
        "Model destination manifest",
        "File",
        (("path", "path"), ("sha256", "SHA-256")),
        [
            ("model-html", "Model page", (PAGE, RECORDED_IN_RECEIPT)),
            ("calculation-json", "Calculation JSON", (CALCULATION, calculation_sha256)),
            ("receipt", "Publication receipt", (RECEIPT, RECORDED_IN_RECEIPT)),
        ],
    )
    calculation, calculation_facts = _table(
        "model-calculation",
        "Calculation JSON",
        "Item",
        (("value", "value"),),
        [
            ("schema-version", "Schema version", (basis.report.schema_version,)),
            ("report-sha256", "Model report SHA-256", (calculation_sha256,)),
        ],
    )
    provenance, provenance_facts = _table(
        "model-provenance",
        "Publication provenance",
        "Bound item",
        (("sha256", "SHA-256"),),
        [
            ("cp1-head", "CP-1 head", (basis.head.result_sha256,)),
            ("envelope-md", "CP-1 envelope Markdown", (basis.handoff.envelope_sha256,)),
            ("envelope-json", "CP-1 envelope sidecar", (basis.handoff.sidecar_sha256,)),
            ("pack", "Prepared pack", (snapshot.pack_sha256,)),
        ],
    )
    return Module(
        run_id=snapshot.run.run_id,
        issuer_id=snapshot.run.issuer_id,
        as_of=snapshot.run.as_of,
        module_id=MODULE_ID,
        inputs=attempt.inputs,
        attempt=attempt.number,
        facts=(*manifest_facts, *calculation_facts, *provenance_facts),
        tables=(manifest, calculation, provenance),
        claims=(Claim(claim_id="model-publication", text=CLAIM, citations=()),),
        limitations=(OWN_RESTRICTION,) if basis.head.status == "restricted" else (),
    )


def _attempt(store: Execution, ticket_id: str) -> Attempt:
    return next(a for a in store.read().attempts if a.ticket_id == ticket_id)


def _verifier(store: Execution, ticket_id: str) -> Validator:
    """The deterministic validator: the candidate must equal its re-derivation from the journal."""

    def validate(candidate: Module) -> tuple[str, ...]:
        expected = candidate_module(store, _attempt(store, ticket_id), _basis(store))
        if candidate != expected:
            return ("CP-MODEL candidate differs from its re-derivation from the journal",)
        return ()

    return validate


def _write(output: Path, files: dict[str, str]) -> None:
    """Create `output` (new) and write every file; the receipt is last."""
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        (output / name).write_text(raw, encoding="utf-8")


def _page(store: Execution, settled: Module) -> str:
    """The CP-1 page through the accepted route, with the settled CP-MODEL drawn in the panel."""
    with tempfile.TemporaryDirectory(prefix="cp-model-envelope-") as scratch:
        directory = Path(scratch) / "envelope"
        write_cp1_envelope(store, directory)
        return model_destination_html(store, directory, settled)


def _receipt(settled: Module, ticket: str, basis: _Basis, pack_sha256: str, page: str) -> str:
    return (
        json.dumps(
            {
                "schema_version": RECEIPT_SCHEMA,
                "head_sha256": settled.content_hash(),
                "status": settled.status,
                "qualification": PUBLISHED.model_dump(mode="json"),
                "ticket_id": ticket,
                "cp1_head_sha256": basis.head.result_sha256,
                "pack_sha256": pack_sha256,
                "files": {PAGE: text_sha256(page), CALCULATION: text_sha256(basis.calculation)},
            },
            indent=2,
        )
        + "\n"
    )


def _interrupt(store: Execution, ticket: str, reason: str) -> str:
    """End a ticket without a head; if the journal refuses even that, say so in the reason."""
    try:
        store.interrupt(ticket, reason)
    except (ValueError, OSError) as error:  # a refused transition or a journal write error
        return f"{reason}; the attempt could not be interrupted: {error}"
    return reason


def _prepare(
    store: Execution, attempt: Attempt, basis: _Basis
) -> tuple[str, Module, dict[str, str]]:
    """The candidate payload, the module the journal will settle it to, and the files to write.

    Nothing is written here. The settlement is `settle` run in memory, so the page can name the
    head it will become; the receipt is last in the mapping and so last on disk.
    """
    ticket = attempt.ticket_id
    candidate = candidate_module(store, attempt, basis)
    payload = candidate.model_dump_json()
    snapshot = store.read()
    _, settled = settle(
        snapshot,
        _attempt(store, ticket).model_copy(update={"payload_sha256": text_sha256(payload)}),
        payload,
        _verifier(store, ticket),
        pack=store.pack(snapshot),
        load=store.head_module,
    )
    if settled.status not in ("accepted", "restricted"):
        raise CpModelRefused(f"CP-MODEL would settle {settled.status}: {settled.limitations}")
    page = _page(store, settled)
    receipt = _receipt(settled, ticket, basis, snapshot.pack_sha256, page)
    return payload, settled, {PAGE: page, CALCULATION: basis.calculation, RECEIPT: receipt}


def publish_cp_model(store: Execution, *, output: Path) -> Attempt:
    """Publish the promoted CP-1 as the Model destination and its calculation JSON.

    Refused (`CpModelRefused`), before anything is written or begun, unless the run requests
    CP-MODEL, CP-1 holds an accepted or restricted head recorded by promotion, that head
    retains a calculated Model, `output` does not exist and the journal can begin an attempt
    (none pending, input set not settled). Then: begin, build the candidate in Python, settle
    it in memory (`settle`, the journal's own rule) to learn the head it will become, render the
    page for that head, write `model.html`, `calculation.json` and `receipt.json` (last), and
    only then finish the attempt. Any failure before or at the finish interrupts the attempt
    (no head from this attempt); a second consecutive failure leaves a `blocked` head, which is
    the journal's repair rule (decision 0007), not an addition here.
    """
    basis = _basis(store)
    if output.exists():
        raise CpModelRefused(f"Output {output} already exists; publish into a new directory")
    try:
        attempt = store.begin(MODULE_ID)
    except ValueError as error:
        raise CpModelRefused(f"CP-MODEL cannot begin: {error}") from error
    ticket = attempt.ticket_id
    try:
        payload, settled, files = _prepare(store, attempt, basis)
        _write(output, files)
    except Exception as error:
        # Documented fail-closed: record why this attempt ends without a head, then re-raise.
        reason = _interrupt(store, ticket, f"CP-MODEL publication failed: {error}")
        if isinstance(error, CpModelRefused):
            raise
        raise CpModelRefused(reason) from error
    try:
        finished = store.finish(ticket, payload, _verifier(store, ticket), qualification=PUBLISHED)
    except ValueError as error:  # e.g. the inputs changed after the files were written
        raise CpModelRefused(
            _interrupt(store, ticket, f"CP-MODEL publication failed: {error}")
        ) from error
    head = next((h for h in store.read().heads if h.module_id == MODULE_ID), None)
    if finished.issues or head is None or head.result_sha256 != settled.content_hash():
        raise CpModelRefused(
            "Journal settled a different CP-MODEL than the published files name: "
            + "; ".join(finished.issues)
        )
    return finished


NO_HEAD = "CP-MODEL has no accepted or restricted head in the journal"


def verify_cp_model_publication(store: Execution, output: Path) -> tuple[str, ...]:
    """Issues found checking `output` against the journal; empty means it verifies.

    Re-derives from the journal alone: the CP-MODEL head must equal the candidate rebuilt from
    the promoted CP-1, and `model.html`, `calculation.json` and `receipt.json` must equal the
    bytes re-derived for that head. Nothing is trusted from the directory.
    """
    snapshot = store.read()
    head = next((h for h in snapshot.heads if h.module_id == MODULE_ID), None)
    if head is None or head.status not in ("accepted", "restricted"):
        return (NO_HEAD,)
    attempt = next((a for a in snapshot.attempts if a.result_sha256 == head.result_sha256), None)
    if attempt is None:
        return ("CP-MODEL head has no attempt in the journal",)
    try:
        basis = _basis(store)
        settled = store.result(head.result_sha256)
        expected = candidate_module(store, attempt, basis)
        page = _page(store, settled)
    except ValueError as error:  # includes CpModelRefused and EnvelopeError
        return (f"CP-MODEL cannot be re-derived from the journal: {error}",)
    issues: list[str] = []
    if (settled.inputs, settled.facts, settled.tables, settled.claims) != (
        expected.inputs,
        expected.facts,
        expected.tables,
        expected.claims,
    ):
        issues.append("CP-MODEL head differs from its re-derivation from the journal")
    derived = {
        PAGE: page,
        CALCULATION: basis.calculation,
        RECEIPT: _receipt(settled, attempt.ticket_id, basis, snapshot.pack_sha256, page),
    }
    for name, text in derived.items():
        try:
            found = (output / name).read_text(encoding="utf-8")
        except (OSError, ValueError) as error:
            issues.append(f"{name} cannot be read: {error}")
            continue
        if found != text:
            issues.append(f"{name} differs from its re-derivation from the journal")
    return tuple(issues)
