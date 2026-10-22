"""Report view model: what the Front Page and inspector display, with Python-owned text.

Mirrors the shape of the design's view model (``design/reference/lib/vm.js``: cells,
prose runs, blocks, ``C#``/``K#``/``G#`` references) as typed immutable contracts. Every
displayed string is final text from ``display.format_value``; the HTML only places it.
Reference ids are report-wide: ``C#`` cited, ``K#`` calculated, ``S#`` synthetic, ``G#``
gap.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import model_validator

from deploy_vii import prose
from deploy_vii.contracts import (
    PATHWAY_MODULES,
    Contract,
    Fact,
    Identifier,
    ModuleView,
    PathwayId,
    ReportTable,
    Status,
    Text,
    View,
)
from deploy_vii.display import CellState, UnitClass, format_date, format_value

if TYPE_CHECKING:
    from deploy_vii.bindings import Binding, BindingMap

Provenance = Literal["cited", "calculated", "synthetic", "gap"]
DisplayStatus = Literal[
    "unrun",
    "candidate",
    "accepted",
    "restricted",
    "blocked",
    "stale",
    "rejected",
    "not_in_pathway",
]
BlockState = Literal[
    "populated", "collapsed", "condition", "not_run", "not_in_pathway", "absent", "blocked"
]
BlockKind = Literal["dense", "keyvalue", "period_grid", "prose", "chart"]
CallWithheld = Literal["outside_pathway", "blocked"]
ChartKind = Literal["line", "grouped", "stacked", "waterfall", "debt_stack", "na"]
FigurePlacement = Literal["above", "below", "beside"]
BlockWidth = Literal["full", "five", "seven"]

_PREFIX: dict[Provenance, str] = {"cited": "C", "calculated": "K", "synthetic": "S", "gap": "G"}
_KIND_OF_PREFIX: dict[str, Provenance] = {prefix: kind for kind, prefix in _PREFIX.items()}
_GAP_REF = re.compile(r"G\d+")
_REF_ID = re.compile(r"[CKSG]\d+")
_REF_OF_PROV = {kind: re.compile(prefix + r"\d+") for kind, prefix in _PREFIX.items()}
_FIGURE_REF = re.compile(r"[CKS]\d+")
_FORBIDDEN_TEXT = {"null", "none", "nan"}
_FORBIDDEN_IN_TEXT = {"null", "nan"}  # "None" can be a genuine answer in a text value

# Decision 0004 section 6. Icon names are the design system's status glyph keys.
_STATUS_WORDS: dict[str, tuple[str, str]] = {
    "accepted": ("pass", "Pass"),
    "restricted": ("lim", "With limitations"),
    "blocked": ("blocked", "Blocked"),
    "unrun": ("unrun", "Not run"),
    "not_in_pathway": ("not_in_pathway", "Not in this Pathway"),
    "stale": ("stale", "Stale, rerun required"),
    "candidate": ("candidate", "Candidate"),
}


# Module family colours and codes: data copied from ``design/reference/lib/shell.js`` lines
# 26 (``FAMC``) and 27 (``FAMILY``); never loaded from the design file at runtime. A module the
# design does not code falls back to the neutral grey, as the design's ``|| '#9AA0B4'`` does.
FAMILY_COLORS: Mapping[str, str] = MappingProxyType(
    {
        "sources": "#9AA0B4",
        "financials": "#0017E5",
        "business": "#2B8FD6",
        "earnings": "#C4410C",
        "synthesis": "#000533",
        "liquidity": "#0E7A46",
        "covenants": "#8A5300",
        "market": "#7A3DB8",
        "recovery": "#B3261E",
        "evidence": "#9AA0B4",
        "portfolio": "#000533",
    }
)
MODULE_FAMILY: Mapping[str, str] = MappingProxyType(
    {
        "CP-0": "sources",
        "CP-1": "financials",
        "CP-1A": "business",
        "CP-1B": "earnings",
        "CP-1C": "market",
        "CP-1D": "earnings",
        "CP-2": "synthesis",
        "CP-2A": "synthesis",
        "CP-2D": "liquidity",
        "CP-2E": "synthesis",
        "CP-2G": "liquidity",
        "CP-2H": "market",
        "CP-3": "market",
        "CP-3C": "liquidity",
        "CP-3D": "market",
        "CP-4": "covenants",
        "CP-4C": "recovery",
        "CP-5": "evidence",
        "CP-6": "portfolio",
    }
)
_NEUTRAL_FAMILY_COLOR = "#9AA0B4"


def family_color(module_id: str) -> str:
    return FAMILY_COLORS.get(MODULE_FAMILY.get(module_id, ""), _NEUTRAL_FAMILY_COLOR)


def status_word(status: DisplayStatus | Status) -> tuple[str, str]:
    """Icon name and word for a status; colour is never the only cue."""
    if status == "rejected":
        raise ValueError("A rejected attempt is never displayed; it stays in evidence")
    try:
        return _STATUS_WORDS[status]
    except KeyError:
        raise ValueError(f"Unknown status: {status}") from None


def _shown(text: str, *, genuine_text: bool = False) -> str:
    """Final display text: never blank, and never a null spelling.

    ``genuine_text`` is for values whose content is language, not a figure (a ``text``-class
    cell, a plain ``text`` run): "None" can be a real answer there, so only blankness,
    "null" and "nan" are refused. Figure, gap and pen spellings also refuse "none".
    """
    if not text.strip():
        raise ValueError("Displayed text must be non-empty")
    forbidden = _FORBIDDEN_IN_TEXT if genuine_text else _FORBIDDEN_TEXT
    if text.strip().lower() in forbidden:
        raise ValueError("Displayed text must never be a null spelling")
    return text


class FactCoord(Contract):
    """Fact coordinates; ``None`` parts are wildcards in a binding and set in the index."""

    module_id: Identifier
    table_id: Identifier | None = None
    row_id: Identifier | None = None
    fact_id: Identifier | None = None


class Cell(Contract):
    text: Text
    prov: Provenance | Literal["none"]
    ref_id: Identifier | None = None
    gap_ref: Identifier | None = None
    unit_class: UnitClass
    state: CellState

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _shown(self.text, genuine_text=self.unit_class == "text")
        is_gap_state = self.state in {"gap", "not_meaningful"}
        if is_gap_state != (self.gap_ref is not None):
            raise ValueError("A gap reference belongs to gap and not-meaningful cells only")
        if self.gap_ref is not None and not _GAP_REF.fullmatch(self.gap_ref):
            raise ValueError("Gap reference must be G#")
        if is_gap_state and self.prov != "gap":
            raise ValueError("Gap and not-meaningful cells carry gap provenance")
        if self.prov == "gap" and not is_gap_state:
            raise ValueError("Gap provenance requires a gap or not-meaningful state")
        if self.prov in {"cited", "calculated", "synthetic"}:
            if self.ref_id is None or not _REF_OF_PROV[self.prov].fullmatch(self.ref_id):
                raise ValueError(f"A {self.prov} cell needs a {_PREFIX[self.prov]}# reference")
        elif self.ref_id is not None:
            raise ValueError("Only cited, calculated and synthetic cells carry a ref_id")
        return self


class TextRun(Contract):
    """One span of a line: plain text, a figure, a gap marker or model-written (pen) prose."""

    text: Text
    kind: Literal["text", "fig", "gap", "pen"]
    ref_id: Identifier | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _shown(self.text, genuine_text=self.kind == "text")
        if self.kind == "fig" and not (self.ref_id and _FIGURE_REF.fullmatch(self.ref_id)):
            raise ValueError("A figure run needs a C#, K# or S# reference")
        if self.kind == "gap" and not (self.ref_id and _GAP_REF.fullmatch(self.ref_id)):
            raise ValueError("A gap run needs a G# reference")
        if self.kind in {"text", "pen"} and self.ref_id is not None:
            raise ValueError("Plain and pen runs carry no reference")
        return self


Section = Literal["thesis", "strengths", "weaknesses"]


class Line(Contract):
    runs: tuple[TextRun, ...]
    # FP 01 Strengths and weaknesses: a bold label before the runs, and the column a line sits in.
    label: Text | None = None
    section: Section | None = None

    @model_validator(mode="after")
    def non_empty(self) -> Self:
        if not self.runs:
            raise ValueError("A line needs at least one run")
        return self


RowStyle = Literal["row", "subtotal", "total", "memo"]


class Row(Contract):
    row_id: Identifier
    label: Text
    cells: tuple[Cell, ...]
    style: RowStyle = "row"


class ChartMark(Contract):
    """One data point. ``label`` is its category; ``value`` is None when it cannot be plotted.

    ``text`` is the final display text. When ``value`` is set it must equal
    ``display.format_value`` of that value, so the chart never carries a second spelling.
    ``role`` matters to waterfalls only (a running total, or an unexplained residual).
    """

    series: Text
    label: Text
    text: Text
    ref_id: Identifier | None = None
    value: Decimal | None = None
    role: Literal["value", "total", "residual"] = "value"


class ChartSpec(Contract):
    """A chart's data, final texts and table twin. Geometry is ``charts.py``'s job.

    A chart with no plottable point is drawn as the n/a frame and says why in ``reason``.
    ``denominator`` (debt stack) is the amount whose multiples the x axis shows.
    """

    kind: ChartKind
    series: tuple[str, ...]
    table_twin: "Block"
    marks: tuple[ChartMark, ...]
    unit: Text | None = None
    unit_class: UnitClass = "amount"
    reason: str | None = None
    denominator: Decimal | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.table_twin.kind == "chart":
            raise ValueError("A chart's table twin must be a table block")
        if len({(mark.series, mark.label) for mark in self.marks}) != len(self.marks):
            raise ValueError("A chart point is its series and category; they cannot repeat")
        for mark in self.marks:
            if mark.series not in self.series:
                raise ValueError(f"Mark series {mark.series!r} is not a chart series")
            if mark.value is None:
                if mark.ref_id is None or not _GAP_REF.fullmatch(mark.ref_id):
                    raise ValueError("A mark without a value is a gap and carries a G# reference")
                spellings = {
                    format_value(None, self.unit_class, "gap", gap_id=mark.ref_id),
                    format_value(None, self.unit_class, "not_meaningful", gap_id=mark.ref_id),
                }
                if mark.text not in spellings:
                    raise ValueError("A gap mark's text must be the gap spelling from display")
                continue
            if mark.text != format_value(mark.value, self.unit_class, "known"):
                raise ValueError("A mark's text must be the formatted display of its value")
        twin_texts = [cell.text for row in self.table_twin.rows for cell in row.cells]
        if twin_texts != [mark.text for mark in self.marks]:
            raise ValueError("The table twin's cell texts must equal the mark texts, in order")
        plottable = any(mark.value is not None for mark in self.marks)
        if self.kind == "debt_stack" and plottable:
            if self.denominator is None or self.denominator <= 0:
                raise ValueError("A debt stack needs a positive denominator")
        return self


class ColumnGroup(Contract):
    label: Text
    span: int

    @model_validator(mode="after")
    def positive(self) -> Self:
        if self.span < 1:
            raise ValueError("A column group spans at least one column")
        return self


class AbsentColumn(Contract):
    column: int
    reason: Text


class Figure(Contract):
    """A chart held by a block: the S.1 to S.4 strip, the debt stack, S.5 beside a table."""

    fig_id: Text | None = None  # FP 01 numbers S.1 to S.6
    title: Text
    chart: ChartSpec
    placement: FigurePlacement = "below"
    summary: Text | None = None  # the sentence under the caption (FP 01 S.5)

    @property
    def gaps_note(self) -> str | None:
        """``∅ G15 FY2024, FY2025`` for the marks that are gaps: the chart's own legend line."""
        gaps: dict[str, list[str]] = {}
        for item in self.chart.marks:
            if item.value is None and item.ref_id is not None:
                gaps.setdefault(item.ref_id, []).append(item.label)
        return " · ".join(f"∅ {ref} {', '.join(labels)}" for ref, labels in gaps.items()) or None


class BlockTab(Contract):
    """One further register of a tabbed block. A tab with no rows says why in its note."""

    label: Text
    scale: str | None = None
    row_header: Text | None = None
    columns: tuple[str, ...] = ()
    rows: tuple[Row, ...] = ()
    note: Text | None = None

    @model_validator(mode="after")
    def rows_or_reason(self) -> Self:
        if not self.rows and not self.note:
            raise ValueError("A tab without rows states why in its note")
        if self.rows and self.note:
            raise ValueError("A tab with rows carries no note")
        if self.columns and any(len(row.cells) != len(self.columns) for row in self.rows):
            raise ValueError("Row cells do not match the tab's columns")
        return self


class Block(Contract):
    block_id: Identifier
    title: Text
    owner: Text
    fig_id: str | None = None
    tags: tuple[str, ...] = ()
    state: BlockState
    kind: BlockKind
    scale: str | None = None
    row_header: Text | None = None
    columns: tuple[str, ...] = ()
    rows: tuple[Row, ...] = ()
    lines: tuple[Line, ...] = ()
    chart: ChartSpec | None = None
    figures: tuple[Figure, ...] = ()
    # FP 01's Capital structure | EBITDA adjustments | Transaction and new debt: the block's own
    # rows are the tab named ``tab_label``; ``tabs`` are the further registers.
    tab_label: Text | None = None
    tabs: tuple[BlockTab, ...] = ()
    note: str | None = None
    full_analysis_route: str | None = None
    route_label: Text | None = None  # "Open in Model" where the link is not "Full analysis"
    width: BlockWidth = "full"  # FP 01 sets Key findings (5fr) beside the operating model (7fr)
    numbered: bool = False  # prose lines are a numbered list
    pinned: bool = False  # the head says "pinned"
    meta: Text | None = None  # right-hand head text: as-of date and scale, stated once
    summary: Text | None = None  # the one line a collapsed block shows
    # Period grid structure (DS-07): column groups, the tinted base column, greyed absent columns.
    groups: tuple[ColumnGroup, ...] = ()
    base_column: int | None = None
    absent_columns: tuple[AbsentColumn, ...] = ()

    @model_validator(mode="after")
    def period_grid_structure(self) -> Self:
        if (self.groups or self.base_column is not None) and self.kind != "period_grid":
            raise ValueError("Column groups and the base column belong to period grids")
        if self.absent_columns and self.kind not in {"period_grid", "dense"}:
            raise ValueError("Absent columns belong to period grids and dense tables")
        count = len(self.columns)
        if self.groups and sum(group.span for group in self.groups) != count:
            raise ValueError("Column groups must cover every column exactly")
        if self.base_column is not None and not 0 <= self.base_column < count:
            raise ValueError("The base column must be one of the columns")
        absent = [item.column for item in self.absent_columns]
        if len(set(absent)) != len(absent) or any(not 0 <= index < count for index in absent):
            raise ValueError("Absent columns are distinct columns of the block")
        if self.base_column in absent:
            raise ValueError("The base column cannot also be absent")
        return self

    @model_validator(mode="after")
    def tab_structure(self) -> Self:
        if bool(self.tabs) != (self.tab_label is not None):
            raise ValueError("A tabbed block names its own tab and lists the further tabs")
        if self.tabs:
            if self.kind not in {"dense", "keyvalue", "period_grid"}:
                raise ValueError("Only table blocks carry tabs")
            if self.state not in {"populated", "collapsed"}:
                raise ValueError("Only a block with content carries tabs")
            labels = [self.tab_label, *(tab.label for tab in self.tabs)]
            if len(set(labels)) != len(labels):
                raise ValueError("Tab labels are distinct")
        return self

    @model_validator(mode="after")
    def state_matches_content(self) -> Self:
        present = tuple(
            name
            for name, value in (("rows", self.rows), ("lines", self.lines), ("chart", self.chart))
            if value
        )
        if self.state in {"populated", "collapsed"}:
            wants = {"prose": "lines", "chart": "chart"}.get(self.kind, "rows")
            if self.kind == "chart" and self.figures and not present:
                pass  # a chart strip holds figures instead of one chart
            elif present != (wants,):
                raise ValueError(f"A {self.state} {self.kind} block holds {wants} only")
            if self.figures and self.chart is not None:
                raise ValueError("A block holds one chart or a figure strip, not both")
        else:
            if present or self.figures or self.tabs:
                raise ValueError(f"A {self.state} block carries no content")
            if not self.note:
                raise ValueError(f"A {self.state} block states why in its note")
        if self.columns:
            for row in self.rows:
                if len(row.cells) != len(self.columns):
                    raise ValueError("Row cells do not match the block's columns")
        return self


ChartSpec.model_rebuild()
Figure.model_rebuild()


class CallItem(Contract):
    kind: Literal["scale", "direction", "fact", "na"]
    label: Text
    value_text: Text
    meter: int | None = None
    ref_id: Identifier | None = None
    direction: Literal["up", "down", "flat"] | None = None  # a direction item's arrow
    line: bool = False  # a full-width line under the row (Main risk, Portfolio Fit, Instrument)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _shown(self.value_text)
        if (self.kind == "scale") != (self.meter is not None):
            raise ValueError("Only scale items carry a meter")
        if (self.kind == "direction") != (self.direction is not None):
            raise ValueError("Only direction items carry a direction")
        if self.line and self.kind != "fact":
            raise ValueError("Only a fact item can be a line")
        if self.meter is not None and not 1 <= self.meter <= 5:
            raise ValueError("Meter runs from 1 to 5")
        return self


class Pathway(Contract):
    id: Identifier
    title: Text
    question: Text
    requested_modules: tuple[str, ...]
    blocks: tuple[Identifier, ...]


# Decision 0009. Titles and questions are the cards of ``design/reference/rbot-report.dc.html``;
# block ids follow each Front Page's outline (``rbot-fp-0N-*.dc.html``), "The call" excluded
# because the call band is ``ReportView.call``. Ids that existing bindings name
# (``financials-credit-metrics``, ``capital-structure``) keep those spellings.
_PRESETS: tuple[tuple[PathwayId, str, str, tuple[str, ...]], ...] = (
    (
        "credit_snapshot",
        "Credit Snapshot",
        "Should we own this issuer, in which instrument, and why?",
        (
            "key-findings",
            "company-operating-model",
            "model-chart-strip",
            "capital-structure",
            "financials-credit-metrics",
            "strengths-weaknesses",
            "relative-value",
            "company-profile",
            "transaction-summary",
            "portfolio-fit",
            "committee-challenge",
            "what-changed",
        ),
    ),
    (
        "earnings_update",
        "Earnings Update",
        "What did the period change, and does the credit view move?",
        (
            "headline-results",
            "variance-drivers",
            "kpi-changes",
            "guidance-signals",
            "ebitda-adjustments",
            "metric-strip",
            "watch-items",
            "financials-credit-metrics",
            "historical-performance",
            "company-profile",
            "portfolio-fit",
            "what-changed",
        ),
    ),
    (
        "relative_value",
        "Relative Value",
        "Which instrument is best compensated for its risk, and at what level?",
        (
            "instrument-levels",
            "yield-against-maturity",
            "market-against-fundamentals",
            "compensation-preference",
            "peer-positioning",
            "recommendation-portfolio-fit",
            "capital-structure",
            "loan-hy-relative-value",
            "credit-view",
            "what-changed",
        ),
    ),
    (
        "covenant_refinancing",
        "Covenant & Refinancing",
        "Which provisions protect creditors, and can the issuer refinance?",
        (
            "covenant-tests-headroom",
            "liquidity-runway",
            "maturity-wall",
            "funding-gap",
            "red-flags",
            "lender-protection-score",
            "refinancing-paths",
            "capacity",
            "lme-creditor-exposure",
            "ebitda-definition",
            "documents-structure",
        ),
    ),
    (
        "distressed_restructuring",
        "Distressed & Restructuring",
        "Is the distress gate met; which path and fulcrum; what recoveries?",
        (
            "distress-gate",
            "recovery-by-class",
            "value-allocation-claims",
            "liquidity-runway",
            "funding-gap-lme",
            "covenant-levers",
            "rating-triggers",
            "restructuring-paths",
            "instrument-decision",
            "portfolio-fit",
            "what-changed",
        ),
    ),
    (
        "portfolio_decision",
        "Portfolio Decision",
        "Should each portfolio own it, how much, and which instrument?",
        (
            "portfolio-recommendation",
            "portfolio-fit",
            "instrument-decision",
            "binding-limitations",
            "strengths-weaknesses",
            "thesis-catalysts-challenge",
            "capital-structure",
            "what-changed",
        ),
    ),
)


def pathways() -> tuple[Pathway, ...]:
    """The six Pathway presets in Front Page order (FP 01 to FP 06)."""
    return tuple(
        Pathway(
            id=pathway_id,
            title=title,
            question=question,
            requested_modules=PATHWAY_MODULES[pathway_id],
            blocks=blocks,
        )
        for pathway_id, title, question, blocks in _PRESETS
    )


class PassportField(Contract):
    name: Text
    value: str


class Passport(Contract):
    ref_id: Identifier
    kind: Provenance
    fields: tuple[PassportField, ...]

    @model_validator(mode="after")
    def prefix_matches_kind(self) -> Self:
        if not _REF_ID.fullmatch(self.ref_id) or _KIND_OF_PREFIX[self.ref_id[0]] != self.kind:
            raise ValueError("Passport id prefix must match its kind (C cited, K, S, G)")
        return self


class FactRefs(Contract):
    coord: FactCoord
    ref_ids: tuple[Identifier, ...]


class ReportIndex(Contract):
    """Reverse index from fact coordinates to the report-wide ids that explain them."""

    facts: tuple[FactRefs, ...]


class Unplaced(Contract):
    """A shown module binding to a block this Pathway does not compose (listed, never dropped)."""

    module_id: Identifier
    block_id: Identifier
    state: Literal["absent"] = "absent"
    note: Text


class ReportView(Contract):
    schema_version: Literal["report-view/1"] = "report-view/1"
    pathway: Pathway
    call: tuple[CallItem, ...]
    # Third call-band state (decision 0004 section 3): the call is withheld, with its words.
    call_withheld: CallWithheld | None = None
    blocks: tuple[Block, ...]
    # Bindings of shown modules to blocks outside this Pathway; the Limitations page lists them.
    unplaced: tuple[Unplaced, ...] = ()
    passports: tuple[Passport, ...]
    index: ReportIndex

    def passport(self, ref_id: str) -> Passport:
        for item in self.passports:
            if item.ref_id == ref_id:
                return item
        raise KeyError(ref_id)

    @model_validator(mode="after")
    def closed_references(self) -> Self:
        if self.call_withheld is not None and (
            not self.call or any(item.kind != "na" for item in self.call)
        ):
            raise ValueError("A withheld call shows only n/a items")
        known = [item.ref_id for item in self.passports]
        if len(set(known)) != len(known):
            raise ValueError("Duplicate passport id")
        block_ids = [block.block_id for block in self.blocks]
        if len(set(block_ids)) != len(block_ids):
            raise ValueError("Duplicate block id")
        if tuple(block_ids) != self.pathway.blocks:
            raise ValueError("Blocks must follow the Pathway's block composition")
        if any(item.block_id in block_ids for item in self.unplaced):
            raise ValueError("An unplaced binding names a block the Pathway composes")
        used = _references(self)
        used.update(ref for entry in self.index.facts for ref in entry.ref_ids)
        if missing := sorted(used - set(known)):
            raise ValueError(f"References without a passport: {', '.join(missing)}")
        return self


def _block_references(block: Block) -> set[str]:
    refs: set[str] = set()
    for row in block.rows:
        for item in row.cells:
            refs.update(r for r in (item.ref_id, item.gap_ref) if r)
    for line in block.lines:
        refs.update(run.ref_id for run in line.runs if run.ref_id)
    for tab in block.tabs:
        for row in tab.rows:
            for item in row.cells:
                refs.update(r for r in (item.ref_id, item.gap_ref) if r)
    charts = [block.chart] if block.chart is not None else []
    charts.extend(figure.chart for figure in block.figures)
    for chart in charts:
        refs.update(mark.ref_id for mark in chart.marks if mark.ref_id)
        refs |= _block_references(chart.table_twin)
    return refs


def _references(view: ReportView) -> set[str]:
    refs = {item.ref_id for item in view.call if item.ref_id}
    for block in view.blocks:
        refs |= _block_references(block)
    return refs


def build_index(view: View) -> tuple[tuple[Passport, ...], ReportIndex]:
    """Allocate report-wide ids for a view's facts, in module then fact order.

    A distinct citation gets one ``C#`` (``S#`` in a synthetic case, whose values are test
    data), a distinct calculation one ``K#``, and each unsettled fact one ``G#``.
    """
    synthetic = view.run.case_kind == "synthetic"
    passports: list[Passport] = []
    allocated: dict[tuple[str, ...], str] = {}
    counters = {"C": 0, "K": 0, "S": 0, "G": 0}

    def allocate(key: tuple[str, ...], kind: Provenance, fields: dict[str, str | None]) -> str:
        if key in allocated:
            return allocated[key]
        prefix = _PREFIX[kind]
        counters[prefix] += 1
        ref_id = f"{prefix}{counters[prefix]}"
        allocated[key] = ref_id
        passports.append(
            Passport(
                ref_id=ref_id,
                kind=kind,
                fields=tuple(
                    PassportField(name=name, value=value) for name, value in fields.items() if value
                ),
            )
        )
        return ref_id

    entries: list[FactRefs] = []
    for module in view.modules:
        for fact in module.facts:
            refs: list[str] = []
            if fact.status != "known":
                refs.append(
                    allocate(
                        ("gap", module.module_id, fact.fact_id),
                        "gap",
                        {
                            "Item": fact.label,
                            "Status": fact.status.replace("_", " "),
                            "Reason": fact.limitation,
                        },
                    )
                )
            for cite in fact.citations:
                refs.append(
                    allocate(
                        ("cite", cite.source_id, cite.source_sha256, cite.locator, cite.quote),
                        "synthetic" if synthetic else "cited",
                        {
                            "Source": cite.source_id,
                            "Locator": cite.locator,
                            "Quote": cite.quote,
                            "SHA-256": cite.source_sha256,
                            "Data": "Synthetic test data" if synthetic else None,
                        },
                    )
                )
            if fact.calculation_id:
                refs.append(
                    allocate(
                        ("calc", fact.calculation_id),
                        "calculated",
                        {
                            "Calculation": fact.calculation_id,
                            "Formula": fact.formula,
                            "Status": fact.calculation_status,
                            "Period": fact.period,
                            "Basis": fact.basis,
                        },
                    )
                )
            if refs:
                entries.append(
                    FactRefs(
                        coord=FactCoord(
                            module_id=module.module_id,
                            table_id=fact.table_id,
                            row_id=fact.row_id,
                            fact_id=fact.fact_id,
                        ),
                        ref_ids=tuple(refs),
                    )
                )
    return tuple(passports), ReportIndex(facts=tuple(entries))


# The glyph key the shell draws for a status. Distinct from ``status_word``'s icon name only
# where that name is the internal token, which the HTML must never carry.
_GLYPH_OF_ICON = {"not_in_pathway": "na"}


def status_display(status: DisplayStatus | Status) -> tuple[str, str]:
    """Glyph key and word for the shell; unlike ``status_word`` it never leaks an internal token."""
    icon, word = status_word(status)
    return _GLYPH_OF_ICON.get(icon, icon), word


def block_state_display() -> dict[str, tuple[str, str]]:
    """Glyph and word of each block state that is not plain content (DS-04).

    ``not_run`` and ``blocked`` reuse the status words so one spelling serves both.
    """
    return {
        "collapsed": ("chevron", "Collapsed"),
        "condition": ("unrun", "Condition"),
        "not_run": status_display("unrun"),
        "not_in_pathway": status_display("not_in_pathway"),
        "absent": ("na", "Absent"),
        "blocked": status_display("blocked"),
    }


class NavRow(Contract):
    """One navigator row: Python decides the number, colour and status spelling."""

    module_id: Identifier
    title: Text
    aliases: tuple[str, ...]
    number: int | None
    in_pathway: bool
    color: str
    glyph: str
    word: Text


def navigator(view: View) -> tuple[NavRow, ...]:
    """Rows in registry order. Modules in the Pathway are numbered 1..N; the rest are footer rows.

    A rejected attempt is never displayed, so it has no row.
    """
    rows: list[NavRow] = []
    number = 0
    for module in view.modules:
        if module.status == "rejected":
            continue
        in_pathway = module.status != "not_in_pathway"
        if in_pathway:
            number += 1
        glyph, word = status_display(module.status)
        rows.append(
            NavRow(
                module_id=module.module_id,
                title=module.title,
                aliases=module.aliases,
                number=number if in_pathway else None,
                in_pathway=in_pathway,
                color=family_color(module.module_id),
                glyph=glyph,
                word=word,
            )
        )
    return tuple(rows)


# --- Front Page production (M3 task 3.8) ------------------------------------------------------

# Amounts in these units are scaled: the scale is stated once in the block head (decision 0004
# section 4), so the cells show the bare number. ``currency`` (statement lines) is an
# amount at 0 dp too; a per-unit amount (a share price) declares ``Fact.decimals`` instead.
_AMOUNT_UNITS = frozenset({"MILLIONS", "THOUSANDS", "UNITS"})
_PERCENT_UNITS = frozenset({"PERCENT", "decimal_fraction"})
# Units that must not be mixed within one table: scaled amounts and unscaled statement lines.
_MIXABLE_UNITS = _AMOUNT_UNITS | {"currency"}
_TABLE_KINDS: tuple[BlockKind, ...] = ("dense", "keyvalue", "period_grid")
# Beyond this the exact decimal is shown as text: fixed-point expansion would be unbounded.
_EXACT_TEXT_ADJUSTED = 100
# Exact-text units: the internal token never reaches the page, its label does.
_UNIT_SUFFIX = {"basis_points": " bp", "decimal_percent": "%"}
_CURRENCY_LABEL = {"USD": "US$"}
_SCALE_LABEL = {"MILLIONS": "m", "THOUSANDS": "000", "UNITS": ""}
_SUMMARY_LIMIT = 140


def _unit_class(unit: str | None) -> UnitClass | None:
    """Display class of a fact unit; ``None`` means exact text plus the unit (no class).

    basis_points, decimal_percent, FX quotes ("USD per EUR") and any other unit keep their
    exact value: rounding them with a class they do not belong to would change their meaning.
    """
    if unit in _AMOUNT_UNITS or unit == "currency":
        return "amount"
    if unit in _PERCENT_UNITS:
        return "percent"
    if unit == "MULTIPLE":
        return "multiple"
    return None


def exact_text(amount: Decimal) -> str:
    """An amount's exact text: fixed-point, or scientific beyond 100 exponent digits (unbounded)."""
    return str(amount) if abs(amount.adjusted()) > _EXACT_TEXT_ADJUSTED else format(amount, "f")


def fact_spelling(fact: Fact, gap_ref: str | None) -> tuple[UnitClass, CellState, str]:
    """Unit class, cell state and display text of one fact, spelled by ``display.format_value``.

    ``gap_ref`` is the fact's report-wide ``G#``; an unsettled fact without one fails closed.
    """
    unit_class = _unit_class(fact.unit)
    if fact.status != "known":
        state: CellState = "not_meaningful" if fact.status == "not_applicable" else "gap"
        shown_class: UnitClass = unit_class or "text"
        return shown_class, state, format_value(None, shown_class, state, gap_id=gap_ref)
    if fact.text is not None:
        return "text", "known", format_value(None, "text", "known", text=fact.text)
    if fact.amount is None:  # unreachable for a validated Fact; fail closed if it ever is not
        raise ValueError(f"Known fact {fact.fact_id} has neither an amount nor text")
    if unit_class is None or abs(fact.amount.adjusted()) > _EXACT_TEXT_ADJUSTED:
        suffix = _UNIT_SUFFIX.get(fact.unit or "", f" {fact.unit}")
        text = f"{exact_text(fact.amount)}{suffix}"
        return "text", "known", format_value(None, "text", "known", text=text)
    return (
        unit_class,
        "known",
        format_value(fact.amount, unit_class, "known", decimals=fact.decimals),
    )


def scale_label(unit: str, currency: str | None) -> str | None:
    """``US$ m`` for MILLIONS in USD; ``None`` when there is nothing to state."""
    label = " ".join(
        part
        for part in (_CURRENCY_LABEL.get(currency or "", currency or ""), _SCALE_LABEL[unit])
        if part
    )
    return label or None


# --- Claim run text (decision 0005 MC-2, M6 task 6.2) -------------------------------------------


def figure_unit(fact: Fact) -> str | None:
    """The unit a figure in prose shows with its number, from the fact alone.

    An amount shows its scale label after the number (prose has no block head to state it);
    a percent, multiple or exact-text spelling already ends in its unit, which this returns.
    ``None`` for a text fact or an amount whose unit has no label.
    """
    if fact.amount is None:
        return None
    unit_class = _unit_class(fact.unit)
    if unit_class is None or abs(fact.amount.adjusted()) > _EXACT_TEXT_ADJUSTED:
        return _UNIT_SUFFIX.get(fact.unit or "", f" {fact.unit}").strip() or None
    if unit_class == "percent":
        return "%"
    if unit_class == "multiple":
        return "x"
    if fact.unit == "currency":
        return _CURRENCY_LABEL.get(fact.currency or "", fact.currency or "") or None
    return scale_label(str(fact.unit), fact.currency)


class ClaimRun(Contract):
    """One span of a resolved claim: literal text (spacing kept), a figure or chip, or a gap.

    ``prov`` is the DOM provenance token, as ``block.state`` is for blocks. A chip whose fact has
    neither a citation nor a calculation is literal text: Python's own spelling, no passport.
    """

    text: Text
    kind: Literal["text", "fig", "gap"]
    ref_id: Identifier | None = None
    prov: Provenance | Literal["none"] = "none"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.kind == "text":
            if self.ref_id is not None or self.prov != "none":
                raise ValueError("A literal claim run carries no reference")
            return self
        _shown(self.text)
        if self.kind == "gap" and not (
            self.prov == "gap" and self.ref_id and _GAP_REF.fullmatch(self.ref_id)
        ):
            raise ValueError("A gap claim run needs gap provenance and a G# reference")
        if self.kind == "fig" and not (
            self.prov in {"cited", "calculated", "synthetic"}
            and self.ref_id
            and _REF_OF_PROV[self.prov].fullmatch(self.ref_id)
        ):
            raise ValueError("A figure claim run needs a C#, K# or S# reference of its kind")
        return self


def module_refs(index: ReportIndex, module_id: str) -> dict[str, tuple[str, ...]]:
    """Report-wide ids of one module's facts, keyed by fact id."""
    return {
        fact_id: ids for (owner, fact_id), ids in _refs_by_fact(index).items() if owner == module_id
    }


def resolve(
    text: str,
    bound: Mapping[str, Fact],
    refs: Mapping[str, tuple[str, ...]],
    *,
    names: Iterable[str] = (),
) -> tuple[ClaimRun, ...]:
    """Resolve run text against one module's bound facts (``prose.bind``) and their
    report-wide ids (``module_refs``).

    Every figure is spelled by ``fact_spelling`` (the cell's number rule, exact text past
    the 100-exponent bound) with the unit of ``figure_unit``; the model's unit token is only
    checked. Fails closed on any ``prose.issues`` finding and on a figure with no report id.
    """
    names = tuple(names)
    found = prose.issues(text, bound, names=names)
    if found:
        raise ValueError("Claim run text does not resolve: " + "; ".join(found))
    gaps = {ref for ref, fact in bound.items() if fact.status != "known"}
    runs: list[ClaimRun] = []
    for run in prose.tokenize(text, gaps=gaps):
        if run.kind == "text":
            runs.append(ClaimRun(text=run.text, kind="text"))
            continue
        fact = bound[run.text]
        item = _cell(fact, refs.get(fact.fact_id, ()))
        if run.kind == "gap":
            runs.append(ClaimRun(text=item.text, kind="gap", ref_id=item.gap_ref, prov="gap"))
            continue
        shown = item.text
        unit = figure_unit(fact) if run.figure and item.unit_class == "amount" else None
        if unit:
            shown = f"{shown} {unit}"
        if item.ref_id is None and run.figure:
            raise ValueError(f"Figure {run.text} has no report reference")
        if item.ref_id is None:
            runs.append(ClaimRun(text=shown, kind="text"))
        else:
            runs.append(ClaimRun(text=shown, kind="fig", ref_id=item.ref_id, prov=item.prov))
    return tuple(runs)


@dataclass(frozen=True)
class _Spec:
    """A Front Page block's heading, producer modules and layout."""

    title: str
    owner: str
    kind: BlockKind
    producers: tuple[str, ...]
    collapsed: bool = False
    width: BlockWidth = "full"
    numbered: bool = False
    pinned: bool = False
    route_label: str | None = None
    dated: bool = False  # the head states the as-of date beside the scale


# Heads and owner codes as FP 01 prints them (``rbot-fp-01-credit-snapshot.dc.html``). The
# producers are the modules whose status explains a block no binding fills.
_CREDIT_SNAPSHOT: Mapping[str, _Spec] = MappingProxyType(
    {
        "key-findings": _Spec(
            "Key findings", "CP-2", "prose", ("CP-2",), width="five", numbered=True, pinned=True
        ),
        "company-operating-model": _Spec(
            "Company and operating model", "CP-1A", "keyvalue", ("CP-1A",), width="seven"
        ),
        "model-chart-strip": _Spec(
            "Model chart strip", "MODEL", "chart", ("CP-1",), route_label="Open in Model"
        ),
        "capital-structure": _Spec("Capital structure", "MODEL", "dense", ("CP-1",), dated=True),
        "financials-credit-metrics": _Spec(
            "Financials and credit metrics",
            "MODEL",
            "period_grid",
            ("CP-1",),
            route_label="Open in Model",
        ),
        "strengths-weaknesses": _Spec(
            "Strengths and weaknesses", "CP-2 · CP-6", "prose", ("CP-2", "CP-6")
        ),
        "relative-value": _Spec("Relative value", "CP-3", "prose", ("CP-3",), collapsed=True),
        "company-profile": _Spec(
            "Company profile", "CP-1A", "keyvalue", ("CP-1A",), collapsed=True
        ),
        "transaction-summary": _Spec(
            "Transaction summary and new debt issues", "Primary", "prose", (), collapsed=True
        ),
        "portfolio-fit": _Spec("Portfolio Fit", "FIT", "prose", (), collapsed=True),
        "committee-challenge": _Spec(
            "Committee challenge", "CP-6", "prose", ("CP-6",), collapsed=True
        ),
        "what-changed": _Spec("What changed since the last Report", "CP-8", "prose", ("CP-8",)),
    }
)
_NO_PRODUCER = "No module produces this block yet."
_UNBOUND_OWNER = "Unbound"
_PERIOD_CLASSES = (
    (re.compile(r"Q[1-4]\b"), "Quarter"),
    (re.compile(r"FY"), "Fiscal year"),
    (re.compile(r"LTM"), "LTM"),
    (re.compile(r"PF"), "Pro forma"),
    (re.compile(r"OPEN\b"), "Opening"),
)
# FP 01's Model chart strip: the series a producer must supply before a chart can be drawn.
_STRIP_FIGURES = (
    ("S.1", "Leverage", "x"),
    ("S.2", "Interest cover", "x"),
    ("S.3", "Liquidity", None),
    ("S.4", "Maturity wall", None),
)
_STRIP_NOTE = "Charts need S.1\u2013S.4 series; KPI register shown as a table"


def _spec_of(block_id: str) -> _Spec:
    if block_id in _CREDIT_SNAPSHOT:
        return _CREDIT_SNAPSHOT[block_id]
    # Blocks only another Pathway lists are not produced yet: they keep the idle view's wording.
    return _Spec(block_id.replace("-", " ").capitalize(), _UNBOUND_OWNER, "prose", ())


def _honest_state(
    spec: _Spec, statuses: Mapping[str, Status], pathway: Pathway
) -> tuple[BlockState, str]:
    """State and words of a block no binding filled, from its producers' statuses."""
    seen = {code: statuses.get(code) for code in spec.producers}
    codes = " · ".join(spec.producers)
    if not seen:
        if spec.owner == _UNBOUND_OWNER:
            return "not_run", "Not run: no module output is bound to this block yet."
        return "absent", f"Absent: {_NO_PRODUCER}"
    if any(status in {"accepted", "restricted", "candidate"} for status in seen.values()):
        return "absent", f"Absent: {codes} produced no output bound to this block."
    if any(status == "blocked" for status in seen.values()):
        return "blocked", f"Blocked: {codes} is blocked; the reasons are listed under Limitations."
    outside = [code for code, status in seen.items() if status == "not_in_pathway"]
    if len(outside) == len(seen):
        return "not_in_pathway", f"Not in this Pathway: {codes} is not part of {pathway.title}."
    if any(status == "stale" for status in seen.values()):
        return "not_run", f"Not run: {codes} is stale and must be rerun."
    if outside:  # both words: some producers have not run, others are not part of the Pathway
        pending = " · ".join(code for code in seen if code not in outside)
        return (
            "not_run",
            f"Not run · Not in this Pathway: {pending} has not run; "
            f"{' · '.join(outside)} is not part of {pathway.title}.",
        )
    return "not_run", f"Not run: {codes} has not run."


def _refs_by_fact(index: ReportIndex) -> dict[tuple[str, str], tuple[str, ...]]:
    return {
        (entry.coord.module_id, entry.coord.fact_id): entry.ref_ids
        for entry in index.facts
        if entry.coord.fact_id is not None
    }


def gap_refs(index: ReportIndex) -> dict[tuple[str, str], str]:
    """The ``G#`` of each unsettled fact, keyed by module and fact id."""
    return {
        key: next(ref for ref in refs if ref.startswith("G"))
        for key, refs in _refs_by_fact(index).items()
        if any(ref.startswith("G") for ref in refs)
    }


def _cell(fact: Fact, refs: tuple[str, ...]) -> Cell:
    gap = next((ref for ref in refs if ref.startswith("G")), None)
    unit_class, state, text = fact_spelling(fact, gap)
    if state != "known":
        return Cell(text=text, prov="gap", gap_ref=gap, unit_class=unit_class, state=state)
    ref = next((r for r in refs if r.startswith("K")), None) or next(
        (r for r in refs if r[0] in "CS"), None
    )
    prov: Provenance | Literal["none"] = "none" if ref is None else _KIND_OF_PREFIX[ref[0]]
    return Cell(text=text, prov=prov, ref_id=ref, unit_class=unit_class, state=state)


@dataclass(frozen=True)
class _Slot:
    label: str
    module_id: str
    columns: tuple[str, ...]
    rows: tuple[Row, ...]
    scale: str | None = None
    row_header: str | None = None
    limitation: str | None = None


def _scale_of(table: str, columns: tuple[str, ...], grid: list[list[Fact | None]]) -> str | None:
    """The one scale a table's amounts share; a table that mixes amount units cannot state it.

    ``grid[row][column]`` holds each cell's fact. The dominant (unit, currency) pair sets the
    scale; a column holding any other pair fails closed, naming the column.
    """
    pairs = [
        (fact.unit, fact.currency, column)
        for row in grid
        for column, fact in enumerate(row)
        if fact is not None and fact.status == "known" and fact.unit in _MIXABLE_UNITS
    ]
    if not pairs:
        return None
    counts = Counter((unit, currency) for unit, currency, _ in pairs)
    unit, currency = counts.most_common(1)[0][0]
    for other_unit, other_currency, column in pairs:
        if (other_unit, other_currency) != (unit, currency):
            raise ValueError(
                f"{table} column {columns[column]!r} mixes amount units "
                f"({other_unit} {other_currency} against {unit} {currency}); "
                "a block states its scale once"
            )
    assert unit is not None
    # Statement lines (``currency``) are checked for mixing but carry no scale label.
    return None if unit == "currency" else scale_label(unit, currency)


def _slot(
    entry: "Binding", module: ModuleView, refs: Mapping[tuple[str, str], tuple[str, ...]]
) -> _Slot:
    """One bound register: the module's declared layout when the binding names a whole table,
    else the matching facts as one value column."""
    coord = entry.fact_coord
    facts = {fact.fact_id: fact for fact in module.facts}

    def cell_of(fact_id: str) -> Cell:
        return _cell(facts[fact_id], refs.get((module.module_id, fact_id), ()))

    layout: ReportTable | None = None
    if coord.row_id is None and coord.fact_id is None:
        layout = next((t for t in module.tables if t.table_id == coord.table_id), None)
    if layout is not None:
        columns = tuple(c.label for c in layout.columns)
        rows = tuple(
            Row(
                row_id=row.row_id,
                label=row.label,
                cells=tuple(cell_of(fact_id) for fact_id in row.fact_ids),
                style=row.row_kind,
            )
            for row in layout.rows
        )
        grid: list[list[Fact | None]] = [[facts[i] for i in row.fact_ids] for row in layout.rows]
        scale = _scale_of(layout.table_id, columns, grid)
        return _Slot(
            entry.title,
            module.module_id,
            columns,
            rows,
            scale,
            layout.row_header,
            layout.limitation,
        )
    matching = tuple(f for f in module.facts if entry.matches(module.module_id, f))
    rows = tuple(
        Row(
            row_id=fact.fact_id,
            label=f"{fact.label} · {fact.period}" if fact.period else fact.label,
            cells=(cell_of(fact.fact_id),),
        )
        for fact in matching
    )
    scale = _scale_of(str(coord.table_id), ("Value",), [[fact] for fact in matching])
    return _Slot(entry.title, module.module_id, ("Value",), rows, scale)


def _period_class(label: str) -> str | None:
    return next((name for pattern, name in _PERIOD_CLASSES if pattern.match(label)), None)


def _columns_structure(
    slot: _Slot, *, kind: BlockKind, reasons: Mapping[str, str]
) -> tuple[tuple[ColumnGroup, ...], int | None, tuple[AbsentColumn, ...]]:
    """Column groups, the base column and absent columns of a table.

    A period grid groups its columns by period class (quarter, fiscal year, LTM, pro forma,
    opening); when any label has no class the grid is left ungrouped rather than guessed. The
    base column is the last LTM column. In any table a column whose every cell is unsettled is
    absent, with the reason of its first gap.
    """
    groups: list[ColumnGroup] = []
    base: int | None = None
    classes = [_period_class(label) for label in slot.columns]
    if kind == "period_grid" and slot.columns and None not in classes:
        for name in classes:
            if groups and groups[-1].label == name:
                groups[-1] = ColumnGroup(label=name, span=groups[-1].span + 1)
            else:
                groups.append(ColumnGroup(label=str(name), span=1))
        ltm = [i for i, name in enumerate(classes) if name == "LTM"]
        base = ltm[-1] if ltm else None
    absent: list[AbsentColumn] = []
    for column in range(len(slot.columns) if kind in {"period_grid", "dense"} else 0):
        cells = [row.cells[column] for row in slot.rows if row.style == "row"]
        if cells and all(item.state != "known" for item in cells):
            reason = reasons.get(cells[0].gap_ref or "") or "Not supplied for any row"
            absent.append(AbsentColumn(column=column, reason=reason))
    if base in {item.column for item in absent}:
        base = None
    return tuple(groups), base, tuple(absent)


def _clip(text: str) -> str:
    return text if len(text) <= _SUMMARY_LIMIT else text[: _SUMMARY_LIMIT - 1] + "…"


def _prose_lines(
    entries: Iterable["Binding"],
    view: View,
    refs: Mapping[tuple[str, str], tuple[str, ...]],
) -> tuple[Line, ...]:
    """One line per bound fact: its words, then a mark that opens its passport."""
    by_id = {module.module_id: module for module in view.modules}
    lines: list[Line] = []
    for entry in entries:
        module = by_id[entry.fact_coord.module_id]
        for fact in module.facts:
            if not entry.matches(module.module_id, fact):
                continue
            item = _cell(fact, refs.get((module.module_id, fact.fact_id), ()))
            labelled = (
                entry.section is not None
            )  # thesis, strength and weakness lines carry a label
            runs: list[TextRun] = []
            if item.gap_ref:
                if not labelled:
                    runs.append(TextRun(text=f"{fact.label}:", kind="text"))
                runs.append(TextRun(text=item.text, kind="gap", ref_id=item.gap_ref))
            elif fact.text is not None:
                judged = fact.value_class == "analyst_judgment"
                runs.append(TextRun(text=item.text, kind="pen" if judged else "text"))
                if item.ref_id:
                    runs.append(TextRun(text=item.ref_id, kind="fig", ref_id=item.ref_id))
            elif item.ref_id:
                runs += [
                    TextRun(text=f"{fact.label}:", kind="text"),
                    TextRun(text=item.text, kind="fig", ref_id=item.ref_id),
                ]
            else:
                runs.append(TextRun(text=f"{fact.label}: {item.text}", kind="text"))
            lines.append(
                Line(
                    runs=tuple(runs),
                    section=entry.section,
                    label=fact.label if labelled else None,
                )
            )
    return tuple(lines)


def _summary(lines: tuple[Line, ...], rows: tuple[Row, ...]) -> str | None:
    """The one line a collapsed block shows: its first line of prose or its first row."""
    if lines:
        return _clip(" ".join(run.text for run in lines[0].runs if run.kind != "fig"))
    if rows:
        return _clip(f"{rows[0].label}: " + ", ".join(cell.text for cell in rows[0].cells))
    return None


def _meta(spec: _Spec, scale: str | None, as_of: date) -> str | None:
    """Right-hand head text: the as-of date (where the block is dated) and the scale, once."""
    parts = [format_date(as_of)] if spec.dated else []
    if scale:
        parts.append(scale)
    if not parts:
        return None
    text = " · ".join(parts)
    return f"{text}; metrics in x; negatives in parentheses" if spec.kind == "period_grid" else text


def _na_strip(block_id: str, owner: str, scale: str | None) -> tuple[Figure, ...]:
    """The four chart frames of the strip when no producer supplies their series."""
    figures = []
    for fig_id, title, unit in _STRIP_FIGURES:
        reason = "The KPI register carries no series for this chart"
        twin = Block(
            block_id=f"{block_id}-{fig_id.replace('.', '').lower()}-twin",
            title=f"{title} table",
            owner=owner,
            state="absent",
            kind="dense",
            note=f"Absent: {reason}.",
        )
        chart = ChartSpec(
            kind="na",
            series=(),
            table_twin=twin,
            marks=(),
            unit=unit or scale,
            reason=reason,
        )
        figures.append(Figure(fig_id=fig_id, title=title, chart=chart, placement="above"))
    return tuple(figures)


def _block(
    block_id: str,
    pathway: Pathway,
    view: View,
    entries: tuple["Binding", ...],
    refs: Mapping[tuple[str, str], tuple[str, ...]],
    reasons: Mapping[str, str],
) -> Block:
    from deploy_vii.bindings import SHOWN_STATUSES

    spec = _spec_of(block_id)
    modules = {module.module_id: module for module in view.modules}
    statuses: dict[str, Status] = {code: module.status for code, module in modules.items()}
    shown = tuple(e for e in entries if modules[e.fact_coord.module_id].status in SHOWN_STATUSES)
    synthetic = ("Synthetic",) if view.run.case_kind == "synthetic" else ()
    state: BlockState = "collapsed" if spec.collapsed else "populated"
    route = spec.producers[0] if spec.producers else None
    shape: dict[str, Any] = {
        "block_id": block_id,
        "title": spec.title,
        "owner": spec.owner,
        "tags": synthetic,
        "state": state,
        "full_analysis_route": route,
        "route_label": spec.route_label,
        "width": spec.width,
        "numbered": spec.numbered,
        "pinned": spec.pinned,
    }
    if shown and spec.kind == "prose":
        lines = _prose_lines(shown, view, refs)
        if lines:
            return Block(
                **{**shape, "summary": _summary(lines, ()) if spec.collapsed else None},
                kind="prose",
                lines=lines,
            )
    elif shown:
        slots = [_slot(e, modules[e.fact_coord.module_id], refs) for e in shown]
        filled = [item for item in slots if item.rows]
        if filled:
            primary = filled[0]
            kind: BlockKind = spec.kind if spec.kind in _TABLE_KINDS else "dense"
            tabs = tuple(
                BlockTab(
                    label=item.label,
                    scale=item.scale,
                    row_header=item.row_header,
                    columns=item.columns,
                    rows=item.rows,
                )
                if item.rows
                else BlockTab(
                    label=item.label,
                    note=item.limitation
                    or f"{item.module_id} reported an empty {item.label} register in this run.",
                )
                for item in slots
                if item is not primary
            )
            groups, base, absent = _columns_structure(primary, kind=kind, reasons=reasons)
            degraded = spec.kind == "chart"  # no producer supplies S.1 to S.4 series yet
            return Block(
                **{**shape, "summary": _summary((), primary.rows) if spec.collapsed else None},
                kind=kind,
                scale=primary.scale,
                row_header=primary.row_header,
                meta=_meta(spec, primary.scale, view.run.as_of),
                columns=primary.columns,
                rows=primary.rows,
                tab_label=primary.label if tabs else None,
                tabs=tabs,
                groups=groups,
                base_column=base,
                absent_columns=absent,
                figures=_na_strip(block_id, spec.owner, primary.scale) if degraded else (),
                note=_STRIP_NOTE if degraded else None,
            )
    words_state, note = _honest_state(spec, statuses, pathway)
    if shown:
        words_state = "absent"
        note = f"Absent: {' · '.join(spec.producers)} supplied no rows for this block."
    kind = spec.kind if spec.kind != "chart" else "dense"
    return Block(
        block_id=block_id,
        title=spec.title,
        owner=spec.owner,
        state=words_state,
        kind=kind,
        note=note,
        width=spec.width,
    )


def _call(statuses: Mapping[str, Status]) -> tuple[tuple[CallItem, ...], CallWithheld | None]:
    """The call band: no module produces a judgement yet, so it says so; a call that cannot be
    made says why (CP-2 outside the Pathway or blocked)."""
    pending = (CallItem(kind="na", label="Assessment", value_text="Assessment pending"),)
    status = statuses.get("CP-2")
    if status == "not_in_pathway":
        return pending, "outside_pathway"
    if status == "blocked":
        return pending, "blocked"
    return pending, None


def _unplaced(view: View, pathway: Pathway, maps: tuple["BindingMap", ...]) -> tuple[Unplaced, ...]:
    """One entry per shown module and block it binds to that is neither composed nor a rail page.

    A binding counts when it matches a fact or table the module carries, so an unused wildcard
    entry does not list a block with nothing behind it.
    """
    from deploy_vii.bindings import RAIL_DESTINATIONS, SHOWN_STATUSES

    shown = {m.module_id: m for m in view.modules if m.status in SHOWN_STATUSES}
    carried = {
        module_id: {fact.table_id for fact in module.facts}
        | {table.table_id for table in module.tables}
        for module_id, module in shown.items()
    }
    listed: dict[tuple[str, str], None] = {}
    for module_map in maps:
        module = shown.get(module_map.module_id)
        if module is None:
            continue
        for entry in module_map.entries:
            if entry.block_id in pathway.blocks or entry.block_id in RAIL_DESTINATIONS:
                continue
            table_id = entry.fact_coord.table_id
            if table_id is None or table_id in carried[module.module_id]:
                listed[(module.module_id, entry.block_id)] = None
    return tuple(
        Unplaced(
            module_id=module_id,
            block_id=block_id,
            note=f"{module_id} output bound to {block_id}, not in this Pathway.",
        )
        for module_id, block_id in listed
    )


def build(view: View, pathway: Pathway, maps: Iterable["BindingMap"]) -> ReportView:
    """The Front Page of ``pathway`` from a view and its binding maps.

    Fails closed when a fact of an accepted, restricted or candidate module is unbound or
    doubly bound (``validate_bindings``), or when one table mixes amount units: a value is
    never placed by guess nor dropped. Bound registers become tables (several registers of one
    block become tabs), bound text becomes prose lines, and every block no binding fills shows
    its honest state.
    """
    # Function-local: ``bindings`` imports this module's contracts at import time.
    from deploy_vii.bindings import RAIL_DESTINATIONS, validate_bindings

    maps = tuple(maps)
    if pathway.id != view.run.pathway:
        raise ValueError("The Pathway differs from the run's Pathway")
    if issues := validate_bindings(view, maps):
        more = f" (and {len(issues) - 3} more)" if len(issues) > 3 else ""
        raise ValueError("Bindings do not cover the view: " + "; ".join(issues[:3]) + more)
    passports, index = build_index(view)
    refs = _refs_by_fact(index)
    reasons = {
        item.ref_id: field.value
        for item in passports
        if item.kind == "gap"
        for field in item.fields
        if field.name == "Reason"
    }
    placed = {
        block_id: tuple(
            entry
            for module_map in maps
            for entry in module_map.entries
            if entry.block_id == block_id and block_id not in RAIL_DESTINATIONS
        )
        for block_id in pathway.blocks
    }
    blocks = tuple(
        _block(block_id, pathway, view, placed[block_id], refs, reasons)
        for block_id in pathway.blocks
    )
    call, withheld = _call({module.module_id: module.status for module in view.modules})
    return ReportView(
        pathway=pathway,
        call=call,
        call_withheld=withheld,
        blocks=blocks,
        unplaced=_unplaced(view, pathway, maps),
        passports=passports,
        index=index,
    )


def call_state(report: ReportView) -> tuple[str, tuple[str, str] | None]:
    """Call band state for the shell and the words of a withheld call (no internal tokens)."""
    if report.call_withheld == "blocked":
        return "blocked", status_display("blocked")
    if report.call_withheld == "outside_pathway":
        return "outside", status_display("not_in_pathway")
    if any(item.kind != "na" for item in report.call):
        return "populated", None
    return "no-judgement", None
