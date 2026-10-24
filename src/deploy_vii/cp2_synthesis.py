"""CP-2 fundamental credit synthesis (task 8.1): one live step, `credit_synthesis`.

Decision 0008 MC-1, as for CP-1A: the model returns a `CreditSynthesisSubmission`, judgments
only. Its evidence is upstream only (coordinator ruling 2): each row's `cp1a_refs` name rows of
the bound CP-1A head (`table.row`, the catalogue `cp1a_catalogue` lists), and its run text names
CP-1 figures as `{ref|unit}` references to the `referencable` facts of the bound CP-1 head; no
pack quote, no hash, no id Python can assign, no amount, no status. `validate_credit_synthesis`
holds it, in Python only, to:

- reference existence (every `cp1a_refs` id is a settled row of the bound CP-1A head) and the
  run-text rule of task 6.2 (`prose.issues`: figures only as resolved references, no bare
  figure, no chip);
- provenance and staleness: the supplied heads are the bound inputs, and the bound input set is
  still `execution.current_inputs` (a refusal there is a staleness issue, never swallowed);
- the basis rule (a row that is not Insufficient Information cites a CP-1A row or a CP-1 figure;
  an Insufficient Information row states its limitation);
- gap propagation (decision 0007, ruling 5): under a blocked CP-1A or any Critical CP-1A gap the
  assessment's confidence is below High, and each Critical CP-1A gap is restated by a `gaps`
  row that cites it;
- the prohibited conclusions of CP-1A (`business_context.prohibited_issues`): peer ranking,
  instrument recommendation and recovery conclusion belong to CP-3 and CP-6.

`credit_synthesis` then composes, in Python, the five r14 tables (T2.1, T2.7, T2.10, T2.11,
T2.12; their columns are composed from the contract rows because the r14 SKILL.md is not in the
repository, ruling 4 and `methods/cp2.md`), the four Front Page tables (`cp2.*`), the CP-1 facts
the text references (verbatim, `cp1_references`), the claims and the own limitations. The
status is the journal's: `execution.settle` restricts on own limitations, on a blocked ancestor
(with the inherited "Upstream CP-1A blocked: ..." limitation) or on a synthetic case, and a
failed repair leaves `blocked`. The conditional `cp2.cp_model_strengths_weaknesses` table is
not composed: CP-MODEL is no CP-2 input in M8 (ruling 1).

The journal path (`submit_cp2_step`) validates the one step and settles CP-2 with the Python
candidate in the same call, as `submit_cp1a_step` does; it needs no registry entry.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from deploy_vii import prose
from deploy_vii.business_context import (
    CP1_REFERENCES,
    LABEL,
    NONE_STATED,
    Category,
    Cell,
    Confidence,
    Register,
    Severity,
    prohibited_issues,
    referencable,
    spelled,
)
from deploy_vii.contracts import (
    Claim,
    Contract,
    Fact,
    Hash,
    Input,
    Module,
    ReportTable,
    Run,
    TableColumn,
    TableRow,
    Text,
)
from deploy_vii.execution import (
    Attempt,
    Execution,
    Qualification,
    StepValidation,
    current_inputs,
    inherited_limitations,
    text_sha256,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import shape_issues
from deploy_vii.report_view import figure_unit

MODULE_ID = "CP-2"
STEP_ID = "credit_synthesis"
CP2_STEPS = (STEP_ID,)
SCHEMA_VERSION = "credit-synthesis/1"
PROMOTED = Qualification(implementation="implemented")
CP1 = "CP-1"
CP1A = "CP-1A"

# --- the model-facing contract ---------------------------------------------------------------
# Plain `str` fields and `Literal` enums, as CP-1A: the validator, not the sent schema, holds the
# references and the text. `cp1a_refs` is the row's CP-1A basis; its CP-1 basis is the figure
# references in its text.


class Assessment(Contract):
    rationale: str
    category: Category
    confidence: Confidence
    cp1a_refs: tuple[str, ...]
    limitation: str | None


class Thesis(Contract):
    text: str
    category: Category
    cp1a_refs: tuple[str, ...]
    limitation: str | None


class Point(Contract):
    """One strength or one weakness."""

    label: str
    text: str
    category: Category
    cp1a_refs: tuple[str, ...]
    limitation: str | None


class Finding(Contract):
    text: str
    cp1a_refs: tuple[str, ...]


class Risk(Contract):
    risk: str
    mechanic: str
    implication: str
    severity: Severity
    cp1a_refs: tuple[str, ...]


class SynthesisGap(Contract):
    gap: str
    why_it_matters: str
    affected_analysis: str
    severity: Severity
    action: str
    cp1a_refs: tuple[str, ...]


SynthesisRow = Assessment | Thesis | Point | Finding | Risk | SynthesisGap


class CreditSynthesisSubmission(Contract):
    """What the model returns for `credit_synthesis`; every field is required (no defaults)."""

    assessment: Assessment
    thesis: Thesis
    strengths: tuple[Point, ...]
    weaknesses: tuple[Point, ...]
    # `minItems: 1` in the sent schema only, as CP-1A's `company`; empty composes as a gap.
    key_findings: tuple[Finding, ...] = Field(json_schema_extra={"minItems": 1})
    risks: tuple[Risk, ...]
    gaps: tuple[SynthesisGap, ...]


# --- the composed report ---------------------------------------------------------------------


class CreditSynthesisReport(Contract):
    schema_version: Literal["credit-synthesis/1"] = "credit-synthesis/1"
    run: Run
    pack_sha256: Hash
    submission_sha256: Hash
    tables: tuple[ReportTable, ...]
    facts: tuple[Fact, ...]
    claims: tuple[Claim, ...]
    limitations: tuple[Text, ...]


# --- the upstream heads a step binds ---------------------------------------------------------


@dataclass(frozen=True)
class CatalogueRow:
    """One citable CP-1A row: its register title, row label and settled cells by field."""

    register: str
    label: str
    cells: tuple[tuple[str, str], ...]


def cp1a_catalogue(cp1a: Module) -> dict[str, CatalogueRow]:
    """The CP-1A rows a `cp1a_refs` id may name, as `<table_id>.<row_id>`: every row of every
    CP-1A register that settles at least one cell. The `cp1_references` copies (CP-1 facts, named
    by `{ref|unit}` instead) and the explicit empty rows ("none", every cell unsettled) are not
    citable."""
    facts = {fact.fact_id: fact for fact in cp1a.facts}
    rows: dict[str, CatalogueRow] = {}
    for table in cp1a.tables:
        if table.table_id == CP1_REFERENCES:
            continue
        for row in table.rows:
            cells = [facts[fact_id] for fact_id in row.fact_ids]
            if all(cell.status != "known" for cell in cells):
                continue
            rows[f"{table.table_id}.{row.row_id}"] = CatalogueRow(
                register=table.title,
                label=row.label,
                cells=tuple(
                    (column.field, _cell_text(cell))
                    for column, cell in zip(table.columns, cells, strict=True)
                ),
            )
    return rows


def _cell_text(fact: Fact) -> str:
    if fact.status != "known":
        return f"{fact.status}: {fact.limitation}"
    return fact.text if fact.text is not None else spelled(fact)


def critical_gaps(cp1a: Module) -> tuple[str, ...]:
    """The `gaps_ledger` rows of a CP-1A head whose severity is Critical, as catalogue ids."""
    return tuple(
        f"gaps_ledger.{fact.row_id}"
        for fact in cp1a.facts
        if fact.table_id == "gaps_ledger" and fact.field == "severity" and fact.text == "Critical"
    )


@dataclass(frozen=True)
class Upstream:
    """What one CP-2 attempt binds, read once from the journal (`cp2_upstream`).

    `bound` is the attempt's input set; `current` is `execution.current_inputs` now, or its
    refusal text; `cp1` and `cp1a` are the settled modules of the bound CP-1 and CP-1A heads (a
    blocked CP-1A is its limitations only); `inherited` is what settlement will carry from them
    (`execution.inherited_limitations`, the same wording)."""

    bound: tuple[Input, ...]
    current: tuple[Input, ...] | str
    cp1: Module
    cp1a: Module
    inherited: tuple[str, ...]

    def status(self, module_id: str) -> str | None:
        return next((item.status for item in self.bound if item.input_id == module_id), None)

    @property
    def cp1a_status(self) -> str | None:
        return self.status(CP1A)

    @property
    def catalogue(self) -> dict[str, CatalogueRow]:
        return {} if self.cp1a_status == "blocked" else cp1a_catalogue(self.cp1a)

    @property
    def critical(self) -> tuple[str, ...]:
        return () if self.cp1a_status == "blocked" else critical_gaps(self.cp1a)


def _bound_module(store: Execution, attempt: Attempt, module_id: str) -> Module:
    item = next((i for i in attempt.inputs if i.input_id == module_id), None)
    if item is None:
        raise ValueError(f"The CP-2 attempt binds no {module_id} input")
    return store.result(item.sha256)


def cp2_upstream(store: Execution, attempt: Attempt) -> Upstream:
    """The bound CP-1 and CP-1A heads of `attempt`, the current input set and the inherited
    limitations. A refusal of `current_inputs` (an upstream gone stale, unrun or blocked under a
    block edge, or CP-0 no longer authorizing CP-2) is kept as text: the validator reports it as
    a staleness issue."""
    snapshot = store.read()
    current: tuple[Input, ...] | str
    try:
        current = current_inputs(snapshot, MODULE_ID)
    except ValueError as error:  # NotAuthorized included: reported, never passed as current
        current = str(error)
    inherited = inherited_limitations(snapshot, attempt, (), store.head_module)
    return Upstream(
        bound=attempt.inputs,
        current=current,
        cp1=_bound_module(store, attempt, CP1),
        cp1a=_bound_module(store, attempt, CP1A),
        inherited=inherited,
    )


# --- validation ------------------------------------------------------------------------------

_TEXT = (str, str | None)


def _rows(submission: CreditSynthesisSubmission) -> Iterator[tuple[str, SynthesisRow]]:
    yield "assessment", submission.assessment
    yield "thesis", submission.thesis
    for name in ("strengths", "weaknesses", "key_findings", "risks", "gaps"):
        for index, row in enumerate(getattr(submission, name)):
            yield f"{name}[{index}]", row


def _texts(row: BaseModel) -> Iterator[tuple[str, str]]:
    """(field, value) of each prose field of one row; enums and `cp1a_refs` excluded."""
    for name, info in type(row).model_fields.items():
        value = getattr(row, name)
        if info.annotation in _TEXT and value is not None:
            yield name, value


def _figures(row: BaseModel, bound: Mapping[str, Fact]) -> list[Fact]:
    """The CP-1 facts the row's text names by figure reference, in reading order. A malformed
    text names none here; `prose.issues` reports it."""
    found: list[Fact] = []
    for _, text in _texts(row):
        try:
            runs = prose.tokenize(text)
        except ValueError:
            continue
        found += [bound[r.text] for r in runs if r.kind == "ref" and r.figure and r.text in bound]
    return list({fact.fact_id: fact for fact in found}.values())


def _stale_issues(upstream: Upstream) -> list[str]:
    if isinstance(upstream.current, str):
        return [f"Stale inputs: {upstream.current}"]
    bound = {item.input_id: item for item in upstream.bound}
    current = {item.input_id: item for item in upstream.current}

    def state(item: Input | None) -> str:
        return "absent" if item is None else f"{item.status} {item.sha256[:12]}"

    return [
        f"Stale input {key}: bound {state(bound.get(key))}, current {state(current.get(key))}"
        for key in dict.fromkeys((*bound, *current))
        if bound.get(key) != current.get(key)
    ]


def _provenance_issues(upstream: Upstream) -> list[str]:
    """The supplied modules are the bound heads: same module, same canonical hash."""
    issues: list[str] = []
    for module_id, module in ((CP1, upstream.cp1), (CP1A, upstream.cp1a)):
        item = next((i for i in upstream.bound if i.input_id == module_id), None)
        if item is None or module.module_id != module_id or module.content_hash() != item.sha256:
            issues.append(f"Upstream {module_id}: the supplied module is not the bound input")
    return issues


_KIND: Mapping[type[BaseModel], str] = {Finding: "key finding", Risk: "risk"}


def _basis_issues(path: str, row: SynthesisRow, bound: Mapping[str, Fact]) -> list[str]:
    """The Five Categories rule on CP-2's upstream basis: a row that is not Insufficient
    Information cites a CP-1A row or names a CP-1 figure; an Insufficient one states why. A gap
    row records missing evidence and needs no basis."""
    issues: list[str] = []
    category = getattr(row, "category", None)
    limitation = getattr(row, "limitation", None)
    insufficient = category == "Insufficient Information"
    if insufficient and not limitation:
        issues.append(f"{path}: an Insufficient Information row states its limitation")
    if isinstance(row, Assessment) and row.confidence == "Insufficient Information":
        insufficient = True
        if not row.limitation:
            issues.append(f"{path}: an Insufficient Information confidence states its limitation")
    if isinstance(row, SynthesisGap) or insufficient:
        return issues
    if not row.cp1a_refs and not _figures(row, bound):
        kind = _KIND.get(type(row)) or f"{category} row"
        article = "an" if kind[0] in "AEIOU" else "a"
        issues.append(f"{path}: {article} {kind} cites a CP-1A row or a CP-1 figure")
    return issues


def _propagation_issues(submission: CreditSynthesisSubmission, upstream: Upstream) -> list[str]:
    """Decision 0007 and ruling 5 on the submission: a blocked CP-1A or a Critical CP-1A gap
    caps the assessment below High, and every Critical gap is restated by a citing gaps row."""
    issues: list[str] = []
    critical = upstream.critical
    if upstream.cp1a_status == "blocked":
        reason: str | None = "CP-1A is blocked"
    elif critical:
        reason = "CP-1A records a Critical gap"
    else:
        reason = None
    if reason and submission.assessment.confidence == "High":
        issues.append(f"assessment.confidence: capped below High because {reason}")
    restated = {ref for gap in submission.gaps for ref in gap.cp1a_refs}
    issues.extend(
        f"gaps: restate the Critical CP-1A gap {ref} in a gaps row that cites it"
        for ref in critical
        if ref not in restated
    )
    return issues


def validate_credit_synthesis(
    pack: PreparedPack, submission: CreditSynthesisSubmission, upstream: Upstream
) -> tuple[str, ...]:
    """Every issue of `submission` over the bound `upstream`, in a stable order; empty when it
    composes."""
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        submission = CreditSynthesisSubmission.model_validate_json(submission.model_dump_json())
    except ValidationError as error:
        return shape_issues(error)
    bound = prose.bind(referencable(upstream.cp1.facts))
    catalogue = upstream.catalogue
    names = (pack.run.issuer_name,)
    issues = [*_stale_issues(upstream), *_provenance_issues(upstream)]
    for path, row in _rows(submission):
        for ref in row.cp1a_refs:
            if ref not in catalogue:
                issues.append(f"{path}.cp1a_refs: unknown CP-1A row {ref}")
        issues.extend(_basis_issues(path, row, bound))
        for name, text in _texts(row):
            where = f"{path}.{name}"
            if not text.strip():
                issues.append(f"{where}: empty text")
                continue
            issues.extend(f"{where}: {issue}" for issue in prose.issues(text, bound, names=names))
            # CP-2 quotes nothing, so no row has a quoting category's exemption.
            issues.extend(prohibited_issues(where, text))
    issues.extend(_propagation_issues(submission, upstream))
    return tuple(dict.fromkeys(issues))


# --- composition -----------------------------------------------------------------------------

NO_BASIS = "No CP-1A row or CP-1 figure cited"
REGISTERS: Mapping[str, Register] = {
    item.table_id: item
    for item in (
        Register(
            "T2.1",
            "Credit assessment",
            (
                ("assessment", "Assessment"),
                ("category", "Category"),
                ("confidence", "Confidence"),
                ("basis", "Basis"),
                ("limitation", "Limitation"),
            ),
        ),
        Register(
            "T2.7",
            "Thesis, strengths and weaknesses",
            (
                ("side", "Side"),
                ("label", "Label"),
                ("text", "Text"),
                ("category", "Category"),
                ("basis", "Basis"),
                ("limitation", "Limitation"),
            ),
        ),
        Register("T2.10", "Key findings", (("finding", "Finding"), ("basis", "Basis"))),
        Register(
            "T2.11",
            "Key credit risks",
            (
                ("risk", "Risk"),
                ("mechanic", "Risk mechanic"),
                ("implication", "Credit implication"),
                ("severity", "Severity"),
                ("basis", "Basis"),
            ),
        ),
        Register(
            "T2.12",
            "Gaps ledger",
            (
                ("gap_id", "Gap ID"),
                ("gap", "Gap"),
                ("why_it_matters", "Why it matters"),
                ("affected_analysis", "Affected analysis"),
                ("severity", "Severity"),
                ("action", "Action"),
                ("basis", "Basis"),
            ),
        ),
    )
}
REQUIRED_TABLES = tuple(REGISTERS)
# The Front Page tables: one model text per row (a prose block shows one line per bound fact).
KEY_FINDINGS = "cp2.key_findings"
THESIS = "cp2.thesis"
STRENGTHS = "cp2.strengths"
WEAKNESSES = "cp2.weaknesses"
FRONT_TITLES: Mapping[str, str] = {
    KEY_FINDINGS: "Key findings",
    THESIS: "Thesis",
    STRENGTHS: "Strengths",
    WEAKNESSES: "Weaknesses",
}


@dataclass(frozen=True)
class _Row:
    row_id: str
    label: str
    cells: Sequence[Cell]


class _Composer:
    """Writes the tables: cells from validated rows, figures spelled by Python."""

    def __init__(self, bound: Mapping[str, Fact], catalogue: Mapping[str, CatalogueRow]) -> None:
        self.bound = bound
        self.catalogue = catalogue
        self.tables: list[ReportTable] = []
        self.facts: list[Fact] = []
        self.limitations: list[str] = []
        self.referenced: dict[str, Fact] = {}

    def text(self, value: str) -> str:
        """Validated run text with each figure reference spelled by Python (`spelled`)."""
        out: list[str] = []
        for run in prose.tokenize(value):
            if run.kind == "text":
                out.append(run.text)
                continue
            fact = self.bound[run.text]
            self.referenced.setdefault(fact.fact_id, fact)
            out.append(spelled(fact))
        return "".join(out)

    def said(self, value: str) -> Cell:
        return Cell(self.text(value), judged=True)

    def tagged(self, value: str, category: str) -> Cell:
        """Model text with its r14 category label ([Analyst Interpretation] ...)."""
        return Cell(self.text(value) + LABEL.get(category, ""), judged=True)

    def limit(self, limitation: str | None) -> Cell:
        return Cell(self.text(limitation) if limitation else NONE_STATED)

    def basis(self, row: SynthesisRow) -> Cell:
        """Python's basis cell: each cited CP-1A row with its label, in catalogue (register)
        order whatever order the model listed them in, then each CP-1 figure in reading order."""
        cited = set(row.cp1a_refs)
        parts = [
            f"CP-1A {ref} ({item.label})" for ref, item in self.catalogue.items() if ref in cited
        ]
        parts += [
            f"CP-1 {fact.label} · {fact.period}" if fact.period else f"CP-1 {fact.label}"
            for fact in _figures(row, self.bound)
        ]
        return Cell("; ".join(parts) or NO_BASIS)

    def _fact(self, table_id: str, row_id: str, field: str, label: str, cell: Cell) -> str:
        fact_id = f"{table_id}.{row_id}.{field}"
        self.facts.append(
            Fact(
                fact_id=fact_id,
                label=label,
                table_id=table_id,
                row_id=row_id,
                field=field,
                text=cell.text,
                status="known" if cell.text is not None else cell.status,
                value_class="analyst_judgment" if cell.judged else None,
                limitation=cell.reason if cell.text is None else None,
            )
        )
        return fact_id

    def _empty(self, title: str, required: bool) -> Cell:
        if required:
            reason = f"No {title.lower()} rows in the CP-2 submission"
            self.limitations.append(reason)
            return Cell(None, reason=reason, status="missing")
        return Cell(
            None, reason=f"None in the CP-2 submission ({title.lower()})", status="not_applicable"
        )

    def table(self, register: Register, rows: Sequence[_Row], *, required: bool) -> None:
        if not rows:
            cell = self._empty(register.title, required)
            rows = (_Row("none", "None", tuple(cell for _ in register.columns)),)
        table_rows = [
            TableRow(
                row_id=row.row_id,
                label=row.label,
                fact_ids=tuple(
                    self._fact(register.table_id, row.row_id, field, label, cell)
                    for (field, label), cell in zip(register.columns, row.cells, strict=True)
                ),
            )
            for row in rows
        ]
        self.tables.append(
            ReportTable(
                table_id=register.table_id,
                title=register.title,
                columns=tuple(TableColumn(field=f, label=label) for f, label in register.columns),
                rows=tuple(table_rows),
                row_header="Item",
            )
        )

    def front(self, table_id: str, lines: Sequence[tuple[str, str, Cell]]) -> None:
        """A Front Page table: one `value` fact per line, labelled as the block shows it (the
        thesis, a strength's or weakness's own label, the Python-numbered key finding)."""
        title = FRONT_TITLES[table_id]
        if not lines:
            cell = self._empty(title, True)
            lines = (("none", title, cell),)
        rows = [
            TableRow(
                row_id=row_id,
                label=label,
                fact_ids=(self._fact(table_id, row_id, "value", label, cell),),
            )
            for row_id, label, cell in lines
        ]
        self.tables.append(
            ReportTable(
                table_id=table_id,
                title=title,
                columns=(TableColumn(field="value", label="Value"),),
                rows=tuple(rows),
                row_header=title,
            )
        )


def _assessment(submission: CreditSynthesisSubmission, out: _Composer) -> None:
    row = submission.assessment
    out.table(
        REGISTERS["T2.1"],
        [
            _Row(
                "assessment",
                "Credit assessment",
                (
                    out.tagged(row.rationale, row.category),
                    Cell(row.category),
                    Cell(row.confidence),
                    out.basis(row),
                    out.limit(row.limitation),
                ),
            )
        ],
        required=True,
    )
    if "Insufficient Information" in (row.category, row.confidence):
        # The module's own central judgment is unsupported: an own limitation (restricted).
        out.limitations.append(
            f"Credit assessment is Insufficient Information: {out.text(row.limitation or '')}"
        )


def _sides(submission: CreditSynthesisSubmission, out: _Composer) -> None:
    """T2.7 and the thesis, strengths and weaknesses Front Page tables."""
    thesis = submission.thesis
    rows = [
        _Row(
            "thesis",
            "Thesis",
            (
                Cell("Thesis"),
                Cell("Thesis"),
                out.tagged(thesis.text, thesis.category),
                Cell(thesis.category),
                out.basis(thesis),
                out.limit(thesis.limitation),
            ),
        )
    ]
    out.front(THESIS, [("thesis", "Thesis", rows[0].cells[2])])
    for side, prefix, points, table_id in (
        ("Strength", "s", submission.strengths, STRENGTHS),
        ("Weakness", "w", submission.weaknesses, WEAKNESSES),
    ):
        lines: list[tuple[str, str, Cell]] = []
        for index, point in enumerate(points, 1):
            row_id = f"{prefix}{index:02d}"
            label = out.text(point.label)
            text = out.tagged(point.text, point.category)
            rows.append(
                _Row(
                    row_id,
                    f"{side} {index}",
                    (
                        Cell(side),
                        Cell(label, judged=True),
                        text,
                        Cell(point.category),
                        out.basis(point),
                        out.limit(point.limitation),
                    ),
                )
            )
            lines.append((row_id, label, text))
        out.front(table_id, lines)
    out.table(REGISTERS["T2.7"], rows, required=True)


def _findings(submission: CreditSynthesisSubmission, out: _Composer) -> None:
    """T2.10 and the key-findings Front Page table, numbered by Python."""
    rows: list[_Row] = []
    lines: list[tuple[str, str, Cell]] = []
    for index, finding in enumerate(submission.key_findings, 1):
        row_id, label = f"kf{index:02d}", f"Key finding {index}"
        text = out.said(finding.text)
        rows.append(_Row(row_id, label, (text, out.basis(finding))))
        lines.append((row_id, label, text))
    out.table(REGISTERS["T2.10"], rows, required=True)
    out.front(KEY_FINDINGS, lines)


def _risks_and_gaps(submission: CreditSynthesisSubmission, out: _Composer) -> None:
    out.table(
        REGISTERS["T2.11"],
        [
            _Row(
                f"r{index:02d}",
                f"Risk {index}",
                (
                    out.said(risk.risk),
                    out.said(risk.mechanic),
                    out.said(risk.implication),
                    Cell(risk.severity),
                    out.basis(risk),
                ),
            )
            for index, risk in enumerate(submission.risks, 1)
        ],
        required=True,
    )
    out.table(
        REGISTERS["T2.12"],
        [
            _Row(
                f"g{index:02d}",
                f"Gap {index}",
                (
                    Cell(f"CP-2-GAP-{index:03d}"),
                    out.said(gap.gap),
                    out.said(gap.why_it_matters),
                    out.said(gap.affected_analysis),
                    Cell(gap.severity),
                    out.said(gap.action),
                    out.basis(gap),
                ),
            )
            for index, gap in enumerate(submission.gaps, 1)
        ],
        required=False,
    )


def credit_synthesis(
    pack: PreparedPack, submission: CreditSynthesisSubmission, upstream: Upstream
) -> CreditSynthesisReport:
    """The composed CP-2 tables of a valid submission; raises ValueError on any issue."""
    issues = validate_credit_synthesis(pack, submission, upstream)
    if issues:
        raise ValueError("; ".join(issues))
    pack = PreparedPack.model_validate_json(pack.model_dump_json())
    submission = CreditSynthesisSubmission.model_validate_json(submission.model_dump_json())
    out = _Composer(prose.bind(referencable(upstream.cp1.facts)), upstream.catalogue)
    # Own limitations: the gaps rows (CP-1A's wording), an empty required register and an
    # Insufficient Information assessment. Inherited ones are settlement's (`execution.settle`).
    out.limitations.extend(f"Gap ({g.severity}): {out.text(g.gap)}" for g in submission.gaps)
    for compose in (_assessment, _sides, _findings, _risks_and_gaps):
        compose(submission, out)
    referenced = [
        fact.model_copy(
            update={"table_id": CP1_REFERENCES, "row_id": f"ref{index:02d}", "field": "value"}
        )
        for index, fact in enumerate(out.referenced.values(), 1)
    ]
    tables = list(out.tables)
    if referenced:
        tables.append(
            ReportTable(
                table_id=CP1_REFERENCES,
                title="CP-1 facts referenced in CP-2 text",
                columns=(TableColumn(field="value", label="Value"),),
                rows=tuple(
                    TableRow(
                        row_id=fact.row_id,
                        label=f"{fact.label} · {fact.period}" if fact.period else fact.label,
                        fact_ids=(fact.fact_id,),
                    )
                    for fact in referenced
                ),
                row_header="CP-1 fact",
            )
        )
    # Claims are the model's run text as written; their references resolve against the carried
    # CP-1 facts (`prose_issues` in `execution.candidate_issues`).
    claims = (
        Claim(
            claim_id="T2.1.assessment",
            text=submission.assessment.rationale,
            citations=(),
            limitation=submission.assessment.limitation,
        ),
        *(
            Claim(claim_id=f"T2.10.kf{index:02d}", text=finding.text, citations=())
            for index, finding in enumerate(submission.key_findings, 1)
        ),
    )
    return CreditSynthesisReport(
        run=pack.run,
        pack_sha256=pack.content_hash(),
        submission_sha256=submission.content_hash(),
        tables=tuple(tables),
        facts=(*out.facts, *referenced),
        claims=claims,
        limitations=tuple(dict.fromkeys(out.limitations)),
    )


# --- the module and the journal ---------------------------------------------------------------


def cp2_module(report: CreditSynthesisReport, inputs: Sequence[Input], attempt: int) -> Module:
    """The CP-2 candidate: the report's tables and claims bound to `inputs`."""
    run = report.run
    return Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id=MODULE_ID,
        inputs=(
            *inputs,
            Input(input_id="credit-synthesis-submission", sha256=report.submission_sha256),
        ),
        facts=report.facts,
        tables=report.tables,
        claims=report.claims,
        limitations=report.limitations,
        attempt=attempt,
    )


def _validate_step(store: Execution, pack: PreparedPack, attempt: Attempt) -> StepValidation:
    try:
        submission = CreditSynthesisSubmission.model_validate_json(
            store.payload(attempt.steps[0].payload_sha256)
        )
    except ValidationError as error:
        return StepValidation(issues=shape_issues(error))
    upstream = cp2_upstream(store, attempt)
    issues = validate_credit_synthesis(pack, submission, upstream)
    if issues:
        return StepValidation(issues=issues)
    return StepValidation(output=credit_synthesis(pack, submission, upstream).model_dump_json())


def submit_cp2_step(store: Execution, ticket_id: str, step_id: str, payload: str) -> Attempt:
    """Retain the one `credit_synthesis` response, validate it, then settle CP-2 with the Python
    candidate (as `submit_cp1a_step`): promotion is an accepted step and no validator issue. An
    invalid step finishes the attempt rejected (or blocked on the repair): there is no
    within-attempt repair (ruling 6). A crash after the step resumes from the retained step."""
    if step_id != STEP_ID:
        raise ValueError(f"CP-2 has one step, {STEP_ID}")
    attempt = next((a for a in store.read().attempts if a.ticket_id == ticket_id), None)
    if attempt is None or attempt.module_id != MODULE_ID or attempt.status != "pending":
        raise ValueError("Ticket is absent, finished or belongs to another module")
    if attempt.steps and attempt.steps[0].payload_sha256 != text_sha256(payload):
        raise ValueError("Ticket already retains a different response; resume or interrupt")
    if not attempt.steps or attempt.steps[0].status == "pending":
        attempt = store.submit_step(
            ticket_id,
            MODULE_ID,
            CP2_STEPS,
            STEP_ID,
            payload,
            lambda pack, current: _validate_step(store, pack, current),
        )
    if attempt.status == "finished":
        return attempt
    outcome = _validate_step(store, store.pack(), attempt)
    if outcome.issues or not outcome.retained_as(attempt.steps[0]):
        raise ValueError("Retained CP-2 output differs from trusted validation")
    report = CreditSynthesisReport.model_validate_json(outcome.output or "")
    candidate = cp2_module(report, attempt.inputs, attempt.number)
    return store.finish(
        ticket_id,
        candidate.model_dump_json(),
        lambda supplied: () if supplied == candidate else ("CP-2 candidate differs",),
        qualification=PROMOTED,
    )


def context_block(pack: PreparedPack, upstream: Upstream) -> dict[str, object]:
    """What the `credit_synthesis` CONTEXT block adds to the pack facts, all Python's: the
    upstream statuses, the CP-1 facts a figure reference may name (as CP-1A's block), the CP-1A
    rows `cp1a_refs` may cite, the Critical CP-1A gaps to restate and the limitations settlement
    will inherit."""
    facts = referencable(upstream.cp1.facts)
    blocked = upstream.cp1a_status == "blocked"
    critical = upstream.critical
    return {
        "upstream": [
            {"module_id": item.input_id, "status": item.status}
            for item in upstream.bound
            if item.input_id.startswith("CP-")
        ],
        "cp1_facts": [
            {
                "ref": fact.fact_id,
                "label": fact.label,
                "period": fact.period,
                "unit": figure_unit(fact) or fact.unit,
                "shown": spelled(fact),
            }
            for fact in facts
        ],
        "cp1_facts_note": (
            "Reference a figure only as {ref|unit} with a ref and unit listed in cp1_facts."
            if facts
            else "CP-1 offers no referencable figure: no figure may be referenced, so write no "
            "figure at all (labels only)."
        ),
        "cp1a_rows": [
            {"ref": ref, "register": row.register, "row": row.label, "cells": dict(row.cells)}
            for ref, row in upstream.catalogue.items()
        ],
        "cp1a_rows_note": (
            "CP-1A is blocked: no CP-1A row may be cited, so cp1a_refs stay empty; its "
            "limitations are inherited and the assessment's confidence is below High."
            if blocked
            else "Cite a CP-1A row only by listing its ref in a row's cp1a_refs."
        ),
        "critical_cp1a_gaps": list(critical),
        "critical_cp1a_gaps_note": (
            "Restate each listed gap in a gaps row whose cp1a_refs cite it; while any is listed "
            "the assessment's confidence is below High."
            if critical
            else "No Critical CP-1A gap is recorded."
        ),
        "inherited_limitations": list(upstream.inherited),
    }
