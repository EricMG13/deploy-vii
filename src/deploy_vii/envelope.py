"""Canonical CP-1 Markdown envelope (r14 17-section output), its JSON sidecar and its reader.

Python writes every line: section and block headings are constants, table cells are fact
spellings, claims are resolved run text (``report_view.resolve``) and every other value is an
escaped record field, so no model text reaches the Markdown unparsed. ``null`` lives only in the
JSON sidecar (``envelope.json``), which holds the typed values; the Markdown spells an unsettled
cell ``∅ G#`` (``∅ G# n.m.`` when not applicable), like the Workbench.

The reader parses the H2 sections, their H3 blocks, the tables and the evidence list, and checks
them against the sidecar: section order and completeness, every cell, every evidence marker,
every claim and the provenance footer. It authenticates the Markdown against its sidecar only;
callers bind the sidecar to the journal (the module hash) themselves.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import ValidationError, model_validator

from deploy_vii import prose
from deploy_vii.canonical_tables import CanonicalTables
from deploy_vii.contracts import (
    Contract,
    Fact,
    Hash,
    Input,
    Module,
    ModuleView,
    ReportTable,
    Run,
    Text,
    View,
)
from deploy_vii.quality import QualityReport, Ratio
from deploy_vii.render import display
from deploy_vii.report_view import (
    ReportIndex,
    build_index,
    fact_spelling,
    gap_refs,
    module_refs,
    resolve,
)
from deploy_vii.table_markdown import (
    MarkdownTable,
    markdown_cell,
    null_confusable,
    read_table_markdown,
)

TITLE = "# CP-1 canonical Markdown handoff"
LEAD = (
    "Canonical r14 CP-1 handoff (envelope/1). Python wrote every value; the typed values, "
    "unknown ones included, are in the JSON sidecar envelope.json."
)
# The r14 CP-1 17-section output (pinned Deploy VI bd71346,
# reference/deploy-v-r14/skills/cp-1-canonical-data-foundation/references/CP-1_SCHEMA_REFERENCE.md,
# "17-Section Output"), each with the module tables it carries, in order.
SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Source Register", ("T4.1",)),
    ("Entity Period Key", ("T4.2",)),
    ("FS Coverage", ("statement-coverage",)),
    ("Normalized IS", ("T4.4",)),
    ("Normalized BS", ("T4.6",)),
    ("Normalized CFS", ("T4.5",)),
    ("Normalization Register", ("T4.3",)),
    ("Calculation Register", ("T4.9",)),
    ("Constructed Period Register", ("T4.8",)),
    ("KPI Dashboard", ("T4.10",)),
    ("Definition Conflict Register", ("T4.11",)),
    ("Gaps & Warnings", ("T4.12",)),
    ("Downstream Readiness", ("T4.13", "model-readiness")),
    (
        "Evidence Trace",
        ("analysis-coverage", "funding-assessment", "required-stories", "evidence-trace"),
    ),
    ("QA Status", ()),
    ("Limitation Flags", ()),
    (
        "Module Handoff",
        ("T4.14", "T4.15", "T4.16", "T4.17", "T4.18", "T4.19", "operating-kpis", "pro-forma"),
    ),
)
FINDINGS = "Findings"
EVIDENCE_LIST = "Evidence list"
IDENTITY = "Identity"
PROVENANCE = "Provenance"
_NO_FINDINGS = "Not applicable: no analytical findings supplied."
_NO_QA = "Not produced: no QA report is bound to this envelope."
_NONE_RECORDED = "Not applicable: none recorded."
_NO_JOURNAL = "Not applicable: not bound to an execution journal"
_GAP_CELL = re.compile(r"∅ (G\d+)(?: n\.m\.)?")
_PROSE_MARKER = re.compile(r"\[([CKSG]\d+)\]")
_MAX_ISSUES = 20


class Envelope(Contract):
    """The typed content of one canonical CP-1 envelope; its JSON is the sidecar."""

    schema_version: Literal["envelope/1"] = "envelope/1"
    run: Run
    module: Module
    registers_sha256: Hash
    gap_limitations: tuple[Text, ...] = ()
    quality: QualityReport | None = None
    # The journal inputs the promoted attempt bound (prepared pack, CP-0 head); empty before.
    journal: tuple[Input, ...] = ()

    @model_validator(mode="after")
    def bound_identity(self) -> Self:
        module, run = self.module, self.run
        if module.module_id != "CP-1":
            raise ValueError("The canonical envelope carries the CP-1 module")
        if (module.run_id, module.issuer_id, module.as_of, module.method_version) != (
            run.run_id,
            run.issuer_id,
            run.as_of,
            run.method_version,
        ):
            raise ValueError("Envelope module identity differs from its run")
        pack = [item.sha256 for item in module.inputs if item.input_id == "pack"]
        if len(pack) != 1:
            raise ValueError("Envelope module must bind exactly one pack input")
        bound = {item.input_id: item for item in module.inputs}
        if any(bound.get(item.input_id) != item for item in self.journal):
            raise ValueError("Envelope journal inputs are not bound by its module")
        prepared = [item.sha256 for item in self.journal if item.input_id == "prepared-pack"]
        if prepared and prepared != pack:
            raise ValueError("Envelope journal pack differs from its module pack")
        return self

    @property
    def pack_sha256(self) -> str:
        return next(item.sha256 for item in self.module.inputs if item.input_id == "pack")


class EnvelopeError(ValueError):
    """A Markdown envelope that does not verify against its sidecar; ``issues`` lists why."""

    def __init__(self, issues: tuple[str, ...]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


@dataclass(frozen=True)
class _Block:
    heading: str | None  # None: the section's lead text, before any H3
    body: str
    table: bool


@dataclass(frozen=True)
class _Section:
    name: str
    blocks: tuple[_Block, ...]


def _grid(headings: tuple[str, ...], rows: Sequence[tuple[str, ...]], interface: str | None) -> str:
    """One table in the canonical table codec's format (``table_markdown.read_table_markdown``)."""
    lines = ["| " + " | ".join(markdown_cell(h) for h in headings) + " |"]
    lines.append("|" + "|".join("---" for _ in headings) + "|")
    lines.extend("| " + " | ".join(markdown_cell(v) for v in row) + " |" for row in rows)
    if interface is not None:
        lines.insert(0, f"<!-- table-id: {interface} -->\n")
    return "\n".join(lines)


def _cell(fact: Fact, gap: str | None, interface: str | None) -> str:
    """A fact's lossless cell: exact text when settled, ``∅ G#`` otherwise. Never ``null``."""
    if fact.status != "known":
        return fact_spelling(fact, gap)[2]
    if fact.text is not None and _GAP_CELL.fullmatch(fact.text.strip()):
        raise ValueError(f"Known text of {fact.fact_id} would read as a gap marker")
    if null_confusable(fact, interface):
        raise ValueError("Known interface text would be confused with a null marker")
    return display(fact)


def _table(
    table: ReportTable, facts: Mapping[str, Fact], gaps: Mapping[str, str], markers: dict[str, None]
) -> str:
    headings = tuple(c.label for c in table.columns)
    if table.row_header:
        headings = (table.row_header, *headings)
    rows: list[tuple[str, ...]] = []
    for row in table.rows:
        cells = []
        for fact_id in row.fact_ids:
            fact = facts[fact_id]
            if fact.status != "known":
                markers[gaps[fact_id]] = None
            cells.append(_cell(fact, gaps.get(fact_id), table.interface_id))
        rows.append((row.label, *cells) if table.row_header else tuple(cells))
    return _grid(headings, rows, table.interface_id)


def resolved_claims(
    module: Module | ModuleView, index: ReportIndex, names: tuple[str, ...]
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Each claim as one Markdown line of resolved run text, with the markers it uses.

    A figure or chip with provenance is its Python spelling followed by its report-wide marker
    (``[K3]``); a gap is ``∅ [G4]``; literal text is escaped. ``resolve`` fails closed on any
    unresolved reference or bare figure.
    """
    bound = prose.bind(module.facts)
    refs = module_refs(index, module.module_id)
    lines = []
    for claim in module.claims:
        parts: list[str] = []
        used: list[str] = []
        for run in resolve(claim.text, bound, refs, names=names):
            shown = markdown_cell(run.text)
            if run.ref_id is None:
                parts.append(shown)
            elif run.kind == "gap":
                parts.append(shown.replace(run.ref_id, f"[{run.ref_id}]", 1))
                used.append(run.ref_id)
            else:
                parts.append(f"{shown} [{run.ref_id}]")
                used.append(run.ref_id)
        lines.append((f"- {claim.claim_id}: " + "".join(parts), tuple(used)))
    return tuple(lines)


def _bullets(texts: tuple[str, ...]) -> str:
    return "\n".join("- " + markdown_cell(text) for text in texts) if texts else _NONE_RECORDED


def _quality_blocks(quality: QualityReport | None) -> tuple[_Block, ...]:
    if quality is None:
        return (_Block(None, _NO_QA, table=False),)
    confidence = quality.confidence

    def ratio(value: Ratio) -> str:
        return f"{value.numerator}/{value.denominator}"

    fields = (
        ("qa_status", confidence.qa_status),
        ("confidence_score", str(confidence.confidence_score)),
        ("confidence_band", confidence.confidence_band),
        ("raw_score", ratio(confidence.raw_score)),
        ("evidence_quality", ratio(confidence.evidence_quality)),
        ("coverage", ratio(confidence.coverage)),
        ("source_multiplier", ratio(confidence.source_multiplier)),
        ("penalty", str(confidence.penalty)),
        ("material_claims", str(confidence.material_claims)),
        ("fields_present", str(confidence.fields_present)),
        ("fields_total", str(confidence.fields_total)),
        ("rounding", confidence.rounding),
        ("inputs_sha256", quality.inputs_sha256),
        ("review_sha256", quality.review_sha256),
        ("analytical_qualification", quality.analytical_qualification),
    )
    findings = [
        (
            f.finding_id,
            f.severity,
            f.status,
            f.description,
            "; ".join(f.references) or "Not applicable",
            f.resolution or "Not applicable",
        )
        for f in quality.findings
    ]
    return (
        _Block("Confidence", _grid(("Field", "Value"), list(fields), None), table=True),
        _Block(
            "QA findings",
            _grid(
                ("Finding", "Severity", "Status", "Description", "References", "Resolution"),
                findings,
                None,
            ),
            table=True,
        ),
        _Block("QA limitations", _bullets(quality.limitations), table=False),
    )


def _handoff_blocks(envelope: Envelope, module_sha256: str) -> tuple[_Block, _Block]:
    module, run, quality = envelope.module, envelope.run, envelope.quality
    identity = (
        ("module_id", module.module_id),
        ("run_id", run.run_id),
        ("issuer_id", run.issuer_id),
        ("issuer_name", run.issuer_name),
        ("as_of", run.as_of.isoformat()),
        ("method_version", run.method_version),
        ("case_kind", run.case_kind),
        ("status", module.status),
        ("attempt", str(module.attempt)),
    )
    provenance = [
        ("module_sha256", module_sha256),
        ("registers_sha256", envelope.registers_sha256),
        ("quality_report_sha256", quality.content_hash() if quality else "Not produced"),
        ("quality_inputs_sha256", quality.inputs_sha256 if quality else "Not produced"),
        ("pack_sha256", envelope.pack_sha256),
        ("run_id", run.run_id),
        ("method_version", run.method_version),
    ]
    provenance.extend(
        (f"journal:{item.input_id}", f"{item.sha256} {item.status}") for item in envelope.journal
    )
    if not envelope.journal:
        provenance.append(("journal", _NO_JOURNAL))
    return (
        _Block(IDENTITY, _grid(("Field", "Value"), list(identity), None), table=True),
        _Block(PROVENANCE, _grid(("Field", "Value"), provenance, None), table=True),
    )


def _index(
    envelope: Envelope, module_sha256: str
) -> tuple[dict[str, tuple[str, str]], ReportIndex]:
    """Envelope-local report ids (``build_index`` over this module alone) and their details."""
    module = envelope.module
    view = View(
        run=envelope.run,
        mode="candidate",
        modules=(
            ModuleView(
                module_id=module.module_id,
                title="CP-1",
                aliases=(),
                status="candidate",
                artifact_sha256=module_sha256,
                facts=module.facts,
                tables=module.tables,
                claims=module.claims,
            ),
        ),
    )
    passports, index = build_index(view)
    details: dict[str, tuple[str, str]] = {
        p.ref_id: (p.kind, "\n".join(f"{f.name}: {f.value}" for f in p.fields)) for p in passports
    }
    return details, index


def _sections(envelope: Envelope) -> tuple[_Section, ...]:
    module = envelope.module
    placed = [table_id for _, ids in SECTIONS for table_id in ids]
    tables = {t.table_id: t for t in module.tables}
    if extra := sorted(set(tables) - set(placed)):
        raise ValueError("No r14 envelope section for table: " + ", ".join(extra))
    module_sha256 = module.content_hash()
    details, index = _index(envelope, module_sha256)
    gaps = {fact_id: ref for (_, fact_id), ref in gap_refs(index).items()}
    facts = {f.fact_id: f for f in module.facts}
    markers: dict[str, None] = {}
    claims = resolved_claims(module, index, (envelope.run.issuer_name,))
    for _, used in claims:
        markers.update(dict.fromkeys(used))
    sections: list[_Section] = []
    for name, ids in SECTIONS:
        blocks = [
            _Block(
                # A title is free text: escaped, so it can never open a heading or a table.
                f"{table_id} — {markdown_cell(tables[table_id].title)}",
                _table(tables[table_id], facts, gaps, markers),
                table=True,
            )
            if table_id in tables
            else _Block(table_id, f"Not produced: {table_id} is not in this module.", table=False)
            for table_id in ids
        ]
        if name == "QA Status":
            blocks.extend(_quality_blocks(envelope.quality))
        elif name == "Limitation Flags":
            blocks.extend(
                (
                    _Block("Own limitations", _bullets(module.limitations), table=False),
                    _Block(
                        "Inherited limitations", _bullets(module.inherited_limitations), table=False
                    ),
                    _Block(
                        "Gap register limitations", _bullets(envelope.gap_limitations), table=False
                    ),
                )
            )
        elif name == "Module Handoff":
            identity, provenance = _handoff_blocks(envelope, module_sha256)
            blocks = [identity, *blocks, provenance]
        elif name == "Evidence Trace":
            lines = "\n".join(line for line, _ in claims) or _NO_FINDINGS
            blocks.insert(0, _Block(FINDINGS, lines, table=False))
        sections.append(_Section(name, tuple(blocks)))
    # The evidence list closes Evidence Trace once every marker of every section is known.
    evidence = [(ref, *details[ref]) for ref in details if ref in markers]
    trace = next(i for i, s in enumerate(sections) if s.name == "Evidence Trace")
    sections[trace] = _Section(
        sections[trace].name,
        (
            *sections[trace].blocks,
            _Block(EVIDENCE_LIST, _grid(("Marker", "Kind", "Detail"), evidence, None), table=True),
        ),
    )
    return tuple(sections)


def _markdown(sections: tuple[_Section, ...]) -> str:
    parts = [TITLE, LEAD]
    for section in sections:
        parts.append(f"## {section.name}")
        for block in section.blocks:
            if block.heading is not None:
                parts.append(f"### {block.heading}")
            parts.append(block.body)
    return "\n\n".join(parts) + "\n"


def write_envelope(envelope: Envelope) -> tuple[str, str]:
    """The canonical Markdown and its JSON sidecar; byte-identical for the same envelope.

    Raises ``ValueError`` when the module cannot be written losslessly (an unplaced table, a
    known value that would read as a gap marker, a claim that does not resolve).
    """
    envelope = Envelope.model_validate_json(envelope.model_dump_json())
    return _markdown(_sections(envelope)), envelope.model_dump_json()


def _parse(markdown: str) -> tuple[list[str], list[tuple[str, list[tuple[str | None, str]]]]]:
    """Split Markdown into its preamble lines and its H2 sections of (H3 heading, body) blocks."""
    preamble: list[str] = []
    sections: list[tuple[str, list[tuple[str | None, list[str]]]]] = []
    for line in markdown.split("\n"):
        if line.startswith("## "):
            sections.append((line[3:], [(None, [])]))
        elif line.startswith("### ") and sections:
            sections[-1][1].append((line[4:], []))
        elif sections:
            sections[-1][1][-1][1].append(line)
        else:
            preamble.append(line)
    parsed = []
    for name, blocks in sections:
        bodies = [(heading, "\n".join(lines).strip("\n")) for heading, lines in blocks]
        if bodies and bodies[0][0] is None and not bodies[0][1]:
            bodies = bodies[1:]
        parsed.append((name, bodies))
    return preamble, parsed


def _decode(body: str) -> MarkdownTable | str:
    try:
        return read_table_markdown(body)
    except ValueError as error:
        return str(error)


def _table_issues(where: str, actual: MarkdownTable, expected: MarkdownTable) -> list[str]:
    if actual.interface_id != expected.interface_id:
        return [f"{where}: table interface tag differs from the sidecar"]
    if actual.headings != expected.headings:
        return [f"{where}: table headings differ from the sidecar"]
    if len(actual.rows) != len(expected.rows):
        return [f"{where}: {len(actual.rows)} rows where the sidecar has {len(expected.rows)}"]
    issues = []
    for number, (got, want) in enumerate(zip(actual.rows, expected.rows, strict=True), 1):
        for heading, cell, value in zip(expected.headings, got, want, strict=True):
            if cell != value:
                issues.append(
                    f"{where}: row {number} {heading!r} reads {cell!r}; the sidecar value is "
                    f"{value!r}"
                )
    return issues


def _block_issues(
    where: str, body: str, expected: _Block, tables: dict[str, MarkdownTable]
) -> list[str]:
    """Compare one parsed block with the sidecar's; a readable table is kept in ``tables``."""
    if not expected.table:
        if body == expected.body:
            return []
        got, want = body.split("\n"), expected.body.split("\n")
        line = next(
            (i for i, (a, b) in enumerate(zip(got, want, strict=False), 1) if a != b),
            min(len(got), len(want)) + 1,
        )
        return [f"{where}: line {line} differs from the sidecar"]
    actual = _decode(body)  # read even when identical: the codec's limits still apply
    if isinstance(actual, str):
        return [f"{where}: unreadable table: {actual}"]
    tables[where] = actual
    if body == expected.body:
        return []
    wanted = _decode(expected.body)
    if isinstance(wanted, str):  # unreachable: the same text read back above
        return [f"{where}: the canonical table does not read back: {wanted}"]
    return _table_issues(where, actual, wanted)


def _marker_issues(
    parsed: list[tuple[str, list[tuple[str | None, str]]]], tables: dict[str, MarkdownTable]
) -> list[str]:
    """Every marker in prose and cells resolves in the evidence list, and only those are listed."""
    used: dict[str, None] = {}
    for name, blocks in parsed:
        for heading, body in blocks:
            if name == "Evidence Trace" and heading == FINDINGS:
                used.update(dict.fromkeys(_PROSE_MARKER.findall(body)))
    listed: list[str] = []
    evidence = f"Evidence Trace / {EVIDENCE_LIST}"
    for where, table in tables.items():
        if where == evidence:
            listed = [row[0] for row in table.rows]
            continue
        for row in table.rows:
            for cell in row:
                if match := _GAP_CELL.fullmatch(cell):
                    used[match[1]] = None
    issues = [
        f"Marker {ref} does not resolve in the evidence list" for ref in used if ref not in listed
    ]
    issues.extend(
        f"Evidence list entry {ref} is not referenced" for ref in listed if ref not in used
    )
    if len(listed) != len(set(listed)):
        issues.append("Evidence list repeats a marker")
    return issues


def _footer_issues(tables: dict[str, MarkdownTable], envelope: Envelope) -> list[str]:
    """The provenance footer's hashes are the sidecar's, recomputed here."""
    table = tables.get(f"Module Handoff / {PROVENANCE}")
    if table is None:
        return ["Provenance footer is missing or unreadable"]
    footer = dict(row for row in table.rows if len(row) == 2)
    quality = envelope.quality
    expected = {
        "module_sha256": envelope.module.content_hash(),
        "registers_sha256": envelope.registers_sha256,
        "quality_report_sha256": quality.content_hash() if quality else "Not produced",
        "quality_inputs_sha256": quality.inputs_sha256 if quality else "Not produced",
        "pack_sha256": envelope.pack_sha256,
        "run_id": envelope.run.run_id,
        "method_version": envelope.run.method_version,
        **{f"journal:{i.input_id}": f"{i.sha256} {i.status}" for i in envelope.journal},
    }
    return [
        f"Provenance footer {key} does not match the sidecar"
        for key, value in expected.items()
        if footer.get(key) != value
    ]


def envelope_issues(markdown: str, sidecar: str) -> tuple[str, ...]:
    """Verify Markdown against its sidecar; empty when the envelope round-trips cleanly."""
    try:
        envelope = Envelope.model_validate_json(sidecar)
    except ValidationError as error:
        return (f"Envelope sidecar is invalid: {error.error_count()} schema errors",)
    try:
        expected = _sections(envelope)
    except ValueError as error:
        return (f"Envelope sidecar cannot be written: {error}",)
    preamble, parsed = _parse(markdown)
    issues: list[str] = []
    if [line for line in preamble if line] != [TITLE, LEAD]:
        issues.append("Envelope title or lead differs from the canonical envelope")
    names = [name for name, _ in parsed]
    wanted = [section.name for section in expected]
    issues.extend(f"Missing section: {name}" for name in wanted if name not in names)
    issues.extend(f"Unexpected section: {name}" for name in names if name not in wanted)
    if len(names) != len(set(names)):
        issues.append("A section is repeated")
    elif not issues and names != wanted:
        issues.append("Sections are not in the r14 order")
    found = dict(parsed)
    tables: dict[str, MarkdownTable] = {}
    for section in expected:
        blocks = found.get(section.name)
        if blocks is None:
            continue
        headings = [heading for heading, _ in blocks]
        want = [block.heading for block in section.blocks]
        if headings != want:
            issues.append(f"Section {section.name}: blocks differ from the sidecar layout")
            continue
        for (heading, body), block in zip(blocks, section.blocks, strict=True):
            where = f"{section.name} / {heading}" if heading else section.name
            issues.extend(_block_issues(where, body, block, tables))
    issues.extend(_marker_issues(parsed, tables))
    issues.extend(_footer_issues(tables, envelope))
    bound = prose.bind(envelope.module.facts)
    names_ = (envelope.run.issuer_name,)
    for claim in envelope.module.claims:  # no bare figure survives in a sidecar claim
        issues.extend(
            f"Claim {claim.claim_id}: {i}" for i in prose.issues(claim.text, bound, names=names_)
        )
    if not issues and markdown != _markdown(expected):
        issues.append("Envelope differs from the canonical rendering of its sidecar")
    issues = list(dict.fromkeys(issues))
    if len(issues) > _MAX_ISSUES:
        issues = [*issues[:_MAX_ISSUES], f"{len(issues) - _MAX_ISSUES} further issues not listed"]
    return tuple(issues)


def read_envelope(markdown: str, sidecar: str) -> Envelope:
    """The envelope a verified Markdown handoff carries; raises ``EnvelopeError`` otherwise."""
    issues = envelope_issues(markdown, sidecar)
    if issues:
        raise EnvelopeError(issues)
    return Envelope.model_validate_json(sidecar)


def handoff_issues(envelope: Envelope) -> tuple[str, ...]:
    """Write the envelope and read it back; empty when the handoff verifies.

    A module the writer refuses is an issue here, not an exception, so a caller can record the
    reason (the QA ``canonical-handoff`` slot) and refuse promotion by status.
    """
    try:
        markdown, sidecar = write_envelope(envelope)
    except ValueError as error:
        return (f"Canonical envelope cannot be written: {error}",)
    return envelope_issues(markdown, sidecar)


def register_envelope(registers: CanonicalTables) -> Envelope:
    """The envelope of trusted canonical registers, before QA and promotion (no journal)."""
    ledger = registers.downstream.inputs.narrative.inputs.ledger
    return Envelope(
        run=ledger.context.run,
        module=registers.module,
        registers_sha256=registers.content_hash(),
        gap_limitations=ledger.limitations,
    )
