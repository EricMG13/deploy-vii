"""Read-only pack tools and the tool-loop rules of a step (task 8.0d).

Ported from the hybrid harness (`devtools/hybrid_cp0.py`, `devtools/hybrid_cp1.py`, user
decision 24 Oct 2026): `search_pack` and `read_pages` over the prepared pack, with the same
arguments, ranking, snippets and SOURCE-block rendering, and each step's `submit_<step>` tool
whose parameters are the step's sent schema (`strict_schema`). `PackTools` records what the
model was shown: the pages `read_pages` returned and each search's scope, so the loop can check
the evidence rules below. Tool text is data: it is rendered as `<<<SOURCE ...>>>` blocks, and
`block` refuses a source that holds a delimiter.

Evidence measures (`evidence_counts`, `completeness`, `shrinkage`, `completeness_drop`,
`cited_locators`) are the harness's, for telemetry; they never raise on a paid payload.

Tool-loop rules (decision 0005 rows; the floor's threshold is the user's, in settings). Each is
added to the journal's own issues for the submit (`live.submission.submit_model_payload`'s
`rules`), so a submit it fails is rejected in the journal, never accepted with a limitation:

- `completeness_issues` (`financials`): the expected statements x fiscal years come from the
  retained `source_context` review's financial-source scopes. A fiscal-year
  `historical_duration` scope expects IS and CFS lines; a `period_end` scope expects BS lines.
  A cell is covered by at least the floor's number of lines in a book bound to the scope's
  entity, in periods the scope matches (`scope_matches_period`; for BS, a period ending on the
  scope's date). Quarters and other part-year durations are not fiscal years and expect none.
- `absence_issues`: a claim that something is not in the source needs a recorded search
  earlier in the step. A `source_context` source's `event_scan: no_events_identified` needs a
  `search_pack` over that source (or over every source). A `financials` `missing` observation
  or `not_disclosed` disclosure needs only some `search_pack` in the step, over any source: the
  payload does not name the source the absent value belongs to. A CP-1A or CP-4 row carrying an
  `ABSENCE_MARKERS` value needs the same (task 8.9 fix round 1).
- `unread_citation_issues`: every `page:N` the payload cites was returned by `read_pages`
  earlier in the step. Other locators are not pages and are not checked by this rule.

Task 8.9 (user decision 24 Oct 2026, every live step a tool loop): a step's tool set is the
registry's (`registry.tool_sets`). A `pack` step is offered `search_pack`, `read_pages` (over
its declared sources only: `PackTools(sources=...)`) and its submit; a `submit-only` step is
offered its submit alone. Each step applies the rules its contract can fail
(`applicable_rules`): CP-1's four stages both, as 8.0d set them; CP-0, CP-1A, CP-3 and CP-4 the
cited-page rule, and CP-1A and CP-4 the absence rule over their `ABSENCE_MARKERS` (fix round 1);
submit-only steps none.

Task 8.10b (user decision "A", phase 2): a step in the registry's `extract_tool_steps()` (CP-1's
`financials` only) is offered a fourth tool, `extract_statements`: the statement lines Python
extracts from up to `MAX_PAGES_PER_EXTRACT` pages of one declared source
(`deploy_vii.statement_extract`), rendered as SOURCE blocks: per page its locator, raw header
lines, then `line_no | label | caption | raw_values | flags`. A page it returns counts as read
for the cited-page rule (the model saw its printed lines), as `read_pages` does. A source
outside the step's declared sources, a locator the source does not hold, more than
`MAX_PAGES_PER_EXTRACT` pages or malformed locators are a refused call (`ToolError`).
"""

import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from pydantic import ValidationError

from deploy_vii.contracts import Span
from deploy_vii.cp1_workflow import FinancialSubmission
from deploy_vii.financial_contracts import FinancialBook, StatementLine
from deploy_vii.live.prompts import block, span_line
from deploy_vii.live.schema import strict_schema
from deploy_vii.live.settings import COVERAGE_FLOOR_PLACES, LiveSettings, valid_coverage_floor
from deploy_vii.live.submission import STEPS
from deploy_vii.preparation import PreparedPack
from deploy_vii.registry import SUBMIT_ONLY, ToolSet, extract_tool_steps, step_chain, tool_set
from deploy_vii.source_context import ReportingScope, SourceContextReview, scope_matches_period
from deploy_vii.statement_extract import ExtractedLine, ExtractedTable, extract_statement_lines

MAX_PAGES_PER_READ = 5
# Task 8.10b: an extracted page is compact (one row per printed data line), so a call may name
# more pages than `read_pages` returns.
MAX_PAGES_PER_EXTRACT = 8
MAX_HITS = 15
DEFAULT_HITS = 10
SNIPPET_CHARS = 300
TOOL_CHOICE = "required"
SEARCH, READ, EXTRACT = "search_pack", "read_pages", "extract_statements"
EXTRACT_COLUMNS = "line_no | label | caption | raw_values | flags"
_PAGE = re.compile(r"page:([0-9]+)")
# A fiscal year in days, inclusive of both ends: 52 weeks (364) to 53 weeks (371).
FISCAL_YEAR_DAYS = range(364, 372)
EVIDENCE = ("citations", "limitations", "claims", "objects")
CLAIM_LISTS = frozenset({"analysis", "claims", "events", "findings", "gaps", "stories"})
CITATION_LISTS = frozenset({"citations", "evidence", "evidence_ids"})
COMPLETENESS_COUNTED = ("statement_lines", "balance_movements")
# The first words of every tool-loop rule issue (`corpus` refuses an entry that holds one: a
# one-payload replay has no transcript to judge it by).
INCOMPLETE = "Financials incomplete"
UNBACKED_ABSENCE = "Absence claim without a recorded search"
UNREAD_PAGE = "Cited page not read through read_pages"
RULE_PREFIXES = (INCOMPLETE, UNBACKED_ABSENCE, UNREAD_PAGE)
ABSENCE, UNREAD = "absence", "unread-citations"
RULES = (ABSENCE, UNREAD)  # the floor is configured apart (`ToolRules.floor`)
# Task 8.12: `extracted_coverage` shows a ratio to four places, rounded down; the coverage floor
# (`ToolRules.coverage_min`) has at most four places, so the shown ratio and the floor compare
# as the exact ones do. Agreement lists at most this many disagreements.
COVERAGE_PLACES = Decimal("0.0001")
MAX_DISAGREEMENTS = 5
# A fail-open of the coverage floor, stated in every rules record (task 8.12): a cell with
# nothing extracted has no coverage to judge.
UNMEASURED_CELLS = (
    "a cell with no extracted lines is not judged by this floor (its reason is in "
    "extracted_coverage); min_statement_lines judges a cell's line count"
)
# Task 8.9 fix round 1 (user decision, 24 Oct 2026): the (field, value) pairs by which a row
# says the sources do not disclose something: CP-1A's `DisclosureItem.available` "No" and
# `OperatingDriver.status` "Not disclosed", CP-4's `Covenant.threshold_unit` "not stated". A
# step outside CP-1 checks those its sent schema can carry (`absence_markers`). CP-3's
# `MarketEvidence.kind` "none" is a legitimate "no market evidence" row (user decision): not one.
ABSENCE_MARKERS = (
    ("available", "No"),
    ("status", "Not disclosed"),
    ("threshold_unit", "not stated"),
)


class ToolError(Exception):
    """A tool call the loop refuses; its message becomes the tool result."""


def submit_name(step_id: str) -> str:
    return f"submit_{step_id}"


def _function(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def submit_spec(step_id: str) -> dict[str, Any]:
    return _function(
        submit_name(step_id),
        f"Submit the {step_id} JSON object. Answers `accepted` or the validator's issues.",
        strict_schema(STEPS[step_id].schema),
    )


def extract_spec() -> dict[str, Any]:
    return _function(
        EXTRACT,
        "The statement lines Python extracted from pages of one source (at most "
        f"{MAX_PAGES_PER_EXTRACT} per call), each page as a SOURCE block with its locator and "
        f"raw header lines, then one row per printed data line: {EXTRACT_COLUMNS}. Labels and "
        "raw_values are verbatim from the page (`$` dropped; `(n)` is negative; a dash is nil).",
        {
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "locators": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^page:[0-9]+$"},
                    "minItems": 1,
                    "maxItems": MAX_PAGES_PER_EXTRACT,
                },
            },
            "required": ["source_id", "locators"],
            "additionalProperties": False,
        },
    )


def tool_specs(step_id: str, kind: ToolSet | None = None) -> tuple[dict[str, Any], ...]:
    """The tools a tool-loop step is offered, by its tool set (`kind`, default the registry's,
    task 8.9): `pack` is `search_pack`, `read_pages` and `submit_<step_id>`, as the harness
    offers them, with `extract_statements` before the submit for an `extract_tool_steps()`
    step (task 8.10b); `submit-only` is `submit_<step_id>` alone."""
    kind = tool_set(step_id) if kind is None else kind
    if kind == SUBMIT_ONLY:
        return (submit_spec(step_id),)
    extract = (extract_spec(),) if step_id in extract_tool_steps() else ()
    return (
        _function(
            SEARCH,
            "Case-insensitive search of the pack's source text. Returns up to max_hits spans "
            "ranked by match count, each with its source id, locator and a snippet of up to "
            f"{SNIPPET_CHARS} characters either side of the first match.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "words or a phrase"},
                    "source_id": {"type": ["string", "null"], "description": "null: all"},
                    "max_hits": {"type": "integer", "minimum": 1, "maximum": MAX_HITS},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        _function(
            READ,
            f"Verbatim text of pages first_page..last_page (at most {MAX_PAGES_PER_READ}) of "
            "one source, each page as a SOURCE block with its locator.",
            {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "first_page": {"type": "integer", "minimum": 1},
                    "last_page": {"type": "integer", "minimum": 1},
                },
                "required": ["source_id", "first_page", "last_page"],
                "additionalProperties": False,
            },
        ),
        *extract,
        submit_spec(step_id),
    )


def _arguments(
    raw: Mapping[str, Any], required: Sequence[str], optional: Sequence[str] = ()
) -> None:
    missing = [name for name in required if name not in raw]
    extra = sorted(set(raw) - {*required, *optional})
    if missing or extra:
        raise ToolError(f"bad arguments: missing {missing}, unexpected {extra}")


def _integer(raw: Mapping[str, Any], name: str) -> int:
    value = raw[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"bad arguments: {name} must be an integer")
    return value


class PackTools:
    """`search_pack` and `read_pages` over the prepared pack; records what the model was shown.

    `read`: the (source, `page:N`) spans `read_pages` returned. `extracted` (task 8.10b): those
    `extract_statements` returned, kept apart for telemetry; `seen` counts both as read.
    `surfaced`: the spans a search showed a snippet of. `searched`: the scope of each search
    that returned a result (None: every source the step reads).

    `sources` (task 8.9): the step's declared sources, the only ones the tools read or search
    (CP-4's legal and CP-3's market sources, `live.context.readable_sources`); None is every
    pack source. A pack source outside them is refused by name; an unknown id raises."""

    def __init__(self, pack: PreparedPack, sources: Sequence[str] | None = None) -> None:
        every = tuple(source.source_id for source in pack.sources)
        if sources is not None and (unknown := [s for s in sources if s not in every]):
            raise ValueError(f"{', '.join(unknown)} is not a source of the pack")
        allowed = set(every if sources is None else sources)
        self.pack_ids = every
        self.ids = tuple(source_id for source_id in every if source_id in allowed)
        self.ready = {
            s.source_id: s
            for s in pack.sources
            if s.source_id in allowed and s.status == "ready" and s.sha256
        }
        self.pages = {
            source_id: {
                int(m.group(1)): span
                for span in source.spans
                if (m := _PAGE.fullmatch(span.locator))
            }
            for source_id, source in self.ready.items()
        }
        self.located_pages = sum(len(pages) for pages in self.pages.values())
        self.read: set[tuple[str, str]] = set()
        self.extracted: set[tuple[str, str]] = set()
        self.surfaced: set[tuple[str, str]] = set()
        self.searched: list[str | None] = []

    def _source(self, source_id: object) -> str:
        if isinstance(source_id, str) and source_id in self.pack_ids and source_id not in self.ids:
            raise ToolError(
                f"source {source_id} is not one of the sources this step reads: {list(self.ids)}"
            )
        if not isinstance(source_id, str) or source_id not in self.ids:
            raise ToolError(f"unknown source_id {source_id!r}; sources: {list(self.ids)}")
        if source_id not in self.ready:
            raise ToolError(f"source {source_id} is unavailable: see its status in CONTEXT")
        return source_id

    def search_pack(self, raw: Mapping[str, Any]) -> str:
        _arguments(raw, ("query",), ("source_id", "max_hits"))
        query = raw["query"]
        terms = list(dict.fromkeys(query.split())) if isinstance(query, str) else []
        if not terms:
            raise ToolError("bad arguments: query must be non-empty text")
        scope = raw.get("source_id")
        sources = self.ready if scope is None else {self._source(scope): None}
        limit = _integer(raw, "max_hits") if "max_hits" in raw else DEFAULT_HITS
        if not 1 <= limit <= MAX_HITS:
            raise ToolError(f"bad arguments: max_hits must be 1 to {MAX_HITS}")
        phrase = re.compile(r"\s+".join(map(re.escape, terms)), re.IGNORECASE)
        words = [re.compile(re.escape(term), re.IGNORECASE) for term in terms]
        found: list[tuple[int, int, int, int, str, Span, re.Match[str]]] = []
        for order, source_id in enumerate(sources):
            for position, span in enumerate(self.ready[source_id].spans):
                counts = [len(word.findall(span.text)) for word in words]
                if not sum(counts):
                    continue
                first = phrase.search(span.text) or min(
                    (m for w in words if (m := w.search(span.text))), key=lambda m: m.start()
                )
                exact = len(phrase.findall(span.text))
                found.append((-exact, -sum(counts), order, position, source_id, span, first))
        found.sort(key=lambda item: item[:4])
        lines = [f"{len(found)} spans match {query!r}; showing {min(limit, len(found))}."]
        for rank, (exact, total, _, _, source_id, span, match) in enumerate(found[:limit], 1):
            self.surfaced.add((source_id, span.locator))
            start, end = max(0, match.start() - SNIPPET_CHARS), match.end() + SNIPPET_CHARS
            lines.append(f"hit {rank}: matches={-total} phrase_matches={-exact}")
            lines.append(
                block(
                    "SOURCE",
                    source_id,
                    str(self.ready[source_id].sha256),
                    f"locator={span.locator} | {span.text[start:end]}",
                )
            )
        self.searched.append(scope if isinstance(scope, str) else None)
        return "\n".join(lines)

    def read_pages(self, raw: Mapping[str, Any]) -> str:
        _arguments(raw, ("source_id", "first_page", "last_page"))
        source_id = self._source(raw["source_id"])
        first, last = _integer(raw, "first_page"), _integer(raw, "last_page")
        if first < 1 or last < first:
            raise ToolError("bad arguments: need 1 <= first_page <= last_page")
        if last - first + 1 > MAX_PAGES_PER_READ:
            raise ToolError(f"bad arguments: at most {MAX_PAGES_PER_READ} pages per call")
        pages = self.pages[source_id]
        if not pages:
            raise ToolError(f"source {source_id} has no page:N locators")
        digest = str(self.ready[source_id].sha256)
        parts = []
        for number in range(first, last + 1):
            span = pages.get(number)
            if span is None:
                parts.append(f"page:{number} is not a located span of {source_id}.")
                continue
            parts.append(block("SOURCE", source_id, digest, span_line(span)))
            self.read.add((source_id, span.locator))
        return "\n".join(parts)

    def extract_statements(self, raw: Mapping[str, Any]) -> str:
        """The statement lines of the named pages of one declared source, as SOURCE blocks
        (task 8.10b); every page returned is recorded as extracted, which `seen` counts as read.
        A refused call records nothing."""
        _arguments(raw, ("source_id", "locators"))
        source_id = self._source(raw["source_id"])
        locators = raw["locators"]
        if not isinstance(locators, list) or not all(
            isinstance(item, str) and _PAGE.fullmatch(item) for item in locators
        ):
            raise ToolError("bad arguments: locators must be a list of page:N locators")
        if not locators:
            raise ToolError("bad arguments: locators must name at least one page")
        if len(locators) > MAX_PAGES_PER_EXTRACT:
            raise ToolError(f"bad arguments: at most {MAX_PAGES_PER_EXTRACT} pages per call")
        if repeated := sorted({item for item in locators if locators.count(item) > 1}):
            raise ToolError(f"bad arguments: locators repeat {', '.join(repeated)}")
        if not self.pages[source_id]:
            raise ToolError(f"source {source_id} has no page:N locators")
        # By locator as written: `self.pages` keys by page number, where `page:1` and
        # `page:01` (distinct locators) would collide.
        spans = {
            span.locator: span
            for span in self.ready[source_id].spans
            if _PAGE.fullmatch(span.locator)
        }
        if unknown := [item for item in locators if item not in spans]:
            raise ToolError(f"{', '.join(unknown)} is not a located span of {source_id}")
        digest = str(self.ready[source_id].sha256)
        parts = [
            block(
                "SOURCE",
                source_id,
                digest,
                extracted_body(
                    extract_statement_lines(spans[item].text, item, source_id=source_id)
                ),
            )
            for item in locators
        ]
        self.extracted.update((source_id, item) for item in locators)
        return "\n".join(parts)

    def seen(self) -> "Seen":
        """What the model has been shown so far, frozen (a submit is judged on this): a page
        read or extracted counts as read."""
        return Seen(frozenset(self.read | self.extracted), tuple(self.searched))


def extracted_body(table: ExtractedTable) -> str:
    """One extracted page as `extract_statements` renders it inside its SOURCE block: the
    locator, each raw header line, then a row per data line (`EXTRACT_COLUMNS`; raw values
    space-separated, `-` for no caption or no flag)."""
    rows = [f"locator={table.locator} | statement lines extracted by Python from this page's text"]
    rows += [f"header: {header.rstrip()}" for header in table.headers]
    if not table.lines:
        return "\n".join([*rows, "no statement lines extracted from this page"])
    rows.append(EXTRACT_COLUMNS)
    rows += [
        f"{line.line_no} | {line.label} | {line.caption or '-'} | {' '.join(line.raw_values)} | "
        f"{','.join(line.flags) or '-'}"
        for line in table.lines
    ]
    return "\n".join(rows)


@dataclass(frozen=True)
class Seen:
    """The pages `read_pages` or `extract_statements` returned (task 8.10b: the model saw an
    extracted page's printed lines) and the scope of each search (None: every source), as of
    one submit."""

    read: frozenset[tuple[str, str]] = frozenset()
    searched: tuple[str | None, ...] = ()

    def searched_source(self, source_id: str) -> bool:
        """Whether a recorded search covered `source_id` (scoped to it, or to every source)."""
        return any(scope is None or scope == source_id for scope in self.searched)


# --- evidence measures (telemetry) ------------------------------------------------------------


def _document(payload: str) -> dict[str, Any] | None:
    try:
        document = json.loads(payload)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def cited_locators(payload: str) -> set[tuple[str, str]]:
    """Every (source_id, locator) a payload cites (empty when it is not a JSON object)."""
    document = _document(payload)

    def walk(node: object) -> Iterator[tuple[str, str]]:
        if isinstance(node, dict):
            if isinstance(node.get("source_id"), str) and isinstance(node.get("locator"), str):
                yield node["source_id"], node["locator"]
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    return set(walk(document)) if document is not None else set()


def evidence_counts(payload: str) -> dict[str, int] | None:
    """What a payload holds, for evidence density and shrink-to-pass (None: not an object):
    citations (items of `citations`, `*_citations`, `evidence` and `evidence_ids` lists),
    limitations (`limitations` items plus non-empty `limitation`/`*_limitation` text), claims
    (items of analysis, claims, events, findings, gaps and stories lists) and every object."""
    document = _document(payload)
    if document is None:
        return None
    counts = dict.fromkeys(EVIDENCE, 0)

    def walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        counts["objects"] += 1
        for name, value in node.items():
            if isinstance(value, list):
                if name in CITATION_LISTS or name.endswith("_citations"):
                    counts["citations"] += len(value)
                elif name == "limitations":
                    counts["limitations"] += len(value)
                elif name in CLAIM_LISTS:
                    counts["claims"] += len(value)
            elif (
                isinstance(value, str)
                and value
                and (name == "limitation" or name.endswith("_limitation"))
            ):
                counts["limitations"] += 1
            walk(value)

    walk(document)
    return counts


def _objects(node: object, key: str) -> list[dict[str, Any]]:
    value = node.get(key) if isinstance(node, dict) else None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _scalar_id(value: object) -> str | int | None:
    return value if isinstance(value, str | int) and not isinstance(value, bool) else None


def completeness(payload: str) -> dict[str, Any] | None:
    """What a financials payload covers, summed over its books (None: not an object): statement
    lines by statement and by their period's fiscal year (`unknown` without one), accounts,
    balance movements and bridges, statement identities, definition assessments and the
    distinct observation ids they name. Ids that are not strings or integers count as unknown,
    with the reason recorded; a paid call's payload is measured, never raised on."""
    document = _document(payload)
    if document is None:
        return None
    by_statement: Counter[str] = Counter()
    by_year: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    reasons: list[str] = []

    def note(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    for book in _objects(document.get("financial"), "books"):
        years: dict[str | int, str] = {}
        for period in _objects(book, "periods"):
            ident = _scalar_id(period.get("period_id"))
            if ident is None:
                note("a period's period_id is not a string or integer; its lines count as unknown")
            else:
                years[ident] = str(period.get("fiscal_year"))
        for line in _objects(book, "statement_lines"):
            by_statement[str(line.get("statement"))] += 1
            ident = _scalar_id(line.get("period_id"))
            if ident is None:
                note("a statement line's period_id is not a string or integer; counted as unknown")
            by_year["unknown" if ident is None else years.get(ident, "unknown")] += 1
        for key in (
            "accounts",
            "balance_movements",
            "balance_movement_bridges",
            "statement_identities",
        ):
            sizes[key] += len(_objects(book, key))
    assessments = _objects(document.get("definition"), "assessments")
    observed = {
        ident
        for item in assessments
        if isinstance(item.get("observation_ids"), list)
        for ident in item["observation_ids"]
        if isinstance(ident, str)
    }
    return {
        "statement_lines": sum(by_statement.values()),
        "statement_lines_by_statement": dict(sorted(by_statement.items())),
        "statement_lines_by_fiscal_year": dict(sorted(by_year.items())),
        "accounts": sizes["accounts"],
        "balance_movements": sizes["balance_movements"],
        "balance_movement_bridges": sizes["balance_movement_bridges"],
        "statement_identities": sizes["statement_identities"],
        "definition_assessments": len(assessments),
        "definition_observation_ids": len(observed),
        "reasons": reasons,
    }


def shrinkage(submits: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Later submits whose evidence counts fall below the first submit's (null when the first
    is not an object): the harness's shrink-to-pass flag."""
    if len(submits) < 2:
        return {"flag": False, "dropped": [], "basis": "fewer than two submits"}
    first = submits[0]["counts"]
    if first is None:
        return {"flag": None, "dropped": [], "reason": "the first submit is not a JSON object"}
    dropped: list[dict[str, Any]] = []
    for later in submits[1:]:
        counts = later["counts"]
        if counts is None:
            dropped.append({"submit": later["submit"], "not_a_json_object": True})
            continue
        fewer = {k: [first[k], counts[k]] for k in EVIDENCE if counts[k] < first[k]}
        if fewer:
            dropped.append({"submit": later["submit"], "first_then_now": fewer})
    return {"flag": bool(dropped), "dropped": dropped, "basis": "each later submit vs the first"}


def completeness_drop(submits: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Later financials submits with fewer statement lines or balance movements than the most
    any earlier submit held (5 -> 200 -> 50 is a drop at the third)."""
    basis = "each later submit vs the most any earlier submit held"
    if len(submits) < 2:
        return {"flag": False, "dropped": [], "basis": "fewer than two submits"}
    most: dict[str, int] = {}
    dropped: list[dict[str, Any]] = []
    for index, item in enumerate(submits):
        counts = item["completeness"]
        if counts is None:
            if index:
                dropped.append({"submit": item["submit"], "not_a_json_object": True})
            continue
        fewer = {
            k: [most[k], counts[k]] for k in COMPLETENESS_COUNTED if counts[k] < most.get(k, 0)
        }
        if fewer:
            dropped.append({"submit": item["submit"], "most_before_then_now": fewer})
        most = {k: max(most.get(k, 0), counts[k]) for k in COMPLETENESS_COUNTED}
    return {"flag": bool(dropped), "dropped": dropped, "basis": basis}


# --- tool-loop rules ----------------------------------------------------------------------------


def fiscal_year(scope: ReportingScope) -> bool:
    """Whether a historical-duration scope spans one fiscal year (52 weeks to 53 weeks)."""
    if scope.period_kind != "historical_duration" or scope.start_date is None:
        return False
    if scope.end_date is None:
        return False
    return (scope.end_date - scope.start_date).days + 1 in FISCAL_YEAR_DAYS


@dataclass(frozen=True)
class Cell:
    """One expected (statement, source scope) of the completeness floor."""

    statement: str
    source_id: str
    scope: ReportingScope

    def label(self) -> str:
        start = self.scope.start_date
        dates = f"{start} to {self.scope.end_date}" if start else f"{self.scope.end_date}"
        return f"{self.source_id} scope {self.scope.scope_id} ({dates})"


def expected_cells(context: SourceContextReview) -> tuple[Cell, ...]:
    """The floor's cells: IS and CFS for each fiscal-year historical-duration scope, BS for
    each period-end scope, of every financial source, in the review's order."""
    cells: list[Cell] = []
    for source in context.sources:
        if source.classification != "financial":
            continue
        for scope in source.scopes:
            if fiscal_year(scope):
                cells += [Cell(s, source.source_id, scope) for s in ("IS", "CFS")]
            elif scope.period_kind == "period_end" and scope.end_date is not None:
                cells.append(Cell("BS", source.source_id, scope))
    return tuple(cells)


def _covers(cell: Cell, period_type: str, start: date | None, end: date | None) -> bool:
    if cell.statement == "BS":
        return end == cell.scope.end_date
    return scope_matches_period(cell.scope, period_type, start, end)


def completeness_issues(
    payload: str, context: SourceContextReview, min_lines: int
) -> tuple[str, ...]:
    """The floor's issues for a financials payload; none for a payload that does not parse
    (the stage validator rejects it with its own issues)."""
    try:
        submission = FinancialSubmission.model_validate_json(payload)
    except ValidationError:
        return ()
    entities = {item.book_id: item.entity_id for item in submission.binding.books}
    issues: list[str] = []
    for cell in expected_cells(context):
        count = 0
        for book in submission.financial.books:
            if entities.get(book.book_id) != cell.scope.entity_id:
                continue
            periods = {
                p.period_id
                for p in book.periods
                if _covers(cell, p.period_type, p.start_date, p.end_date)
            }
            count += sum(
                1
                for line in book.statement_lines
                if line.statement == cell.statement and line.period_id in periods
            )
        if count < min_lines:
            issues.append(
                f"{INCOMPLETE}: {count} {cell.statement} lines for {cell.label()}; the floor is "
                f"{min_lines} per statement and source scope"
            )
    return tuple(issues)


# --- extracted coverage (task 8.12, user decision "C") ------------------------------------------


def cell_key(cell: Cell) -> str:
    """A cell's name in `extracted_coverage` and the coverage floor's issues: its statement
    and label (an IS and a CFS cell share a scope, so the label alone is not unique)."""
    return f"{cell.statement} {cell.label()}"


def _normal(label: str) -> str:
    return " ".join(label.split())


def _quotes_value(quote: str, raw: str) -> bool:
    """Whether the printed numeric cell `raw` appears in `quote` verbatim as a whole number:
    not inside a longer one (`40` is not in `140`, `4,000` or `40.5`), and a bare number not
    inside parentheses (`40` is not in `(40)`, which prints -40)."""
    before, after = ("[0-9.,]", "[0-9]|[.,][0-9]")
    if not raw.startswith("("):
        before, after = "[0-9.,(]", "[0-9)]|[.,][0-9]"
    return re.search(rf"(?<!{before}){re.escape(raw)}(?!{after})", quote) is not None


def _ratio(covered: int, extracted: int) -> str | None:
    """covered / extracted as a Decimal string rounded down to `COVERAGE_PLACES` (None: nothing
    extracted). Rounded down, a shown ratio is never above the exact one, so with a floor of at
    most four places the shown ratio is below the floor exactly when the exact one is. (With
    fewer than 10**6 lines the exact ratio is at least 10**-10 from a four-place step, far above
    the default context's 28-digit rounding of the division.)"""
    if not extracted:
        return None
    quotient = Decimal(covered) / Decimal(extracted)
    return str(quotient.quantize(COVERAGE_PLACES, rounding=ROUND_FLOOR))


def _tables_by_page(tables: Sequence[ExtractedTable]) -> dict[tuple[str, str], ExtractedTable]:
    found: dict[tuple[str, str], ExtractedTable] = {}
    for table in tables:
        if table.source_id is None:
            raise ValueError(f"the extracted table {table.locator} names no source")
        key = (table.source_id, table.locator)
        if key in found:
            raise ValueError(f"two extracted tables for {table.source_id} {table.locator}")
        found[key] = table
    return found


def _page_order(locator: str) -> tuple[int, str]:
    match = _PAGE.fullmatch(locator)
    return (int(match.group(1)) if match else -1, locator)


def _covered(line: ExtractedLine, cited: Sequence[StatementLine], source_id: str) -> bool:
    """Whether a payload line of the cell (`cited`: its statement, its scope's periods) cites
    the extracted line's page with one of its printed values in the quote, or with its label."""
    raws = [
        raw for raw, value in zip(line.raw_values, line.values, strict=True) if value is not None
    ]
    label = _normal(line.label)
    return any(
        citation.source_id == source_id
        and citation.locator == line.locator
        and (_normal(item.label) == label or any(_quotes_value(citation.quote, r) for r in raws))
        for item in cited
        for citation in item.value.citations
    )


def _cell_coverage(
    cell: Cell, books: Sequence[FinancialBook], pages: Mapping[tuple[str, str], ExtractedTable]
) -> dict[str, Any]:
    statement, source_id = cell.statement, cell.source_id
    lines = [line for book in books for line in book.statement_lines if line.statement == statement]
    cited = {
        citation.locator
        for line in lines
        for citation in line.value.citations
        if citation.source_id == source_id and _PAGE.fullmatch(citation.locator)
    }
    shown = sorted((loc for loc in cited if (source_id, loc) in pages), key=_page_order)
    extracted = [item for loc in shown for item in pages[(source_id, loc)].lines]
    in_scope = [
        line
        for book in books
        for periods in [
            {
                p.period_id
                for p in book.periods
                if _covers(cell, p.period_type, p.start_date, p.end_date)
            }
        ]
        for line in book.statement_lines
        if line.statement == statement and line.period_id in periods
    ]
    covered = sum(1 for item in extracted if _covered(item, in_scope, source_id))
    reason = None
    if not cited:
        entity = cell.scope.entity_id
        reason = f"no {statement} line of a book bound to {entity} cites a page of {source_id}"
    elif not shown:
        reason = (
            f"no page of {source_id} the {statement} lines cite has an extracted table "
            "(read or extracted)"
        )
    elif not extracted:
        reason = f"the cited pages {', '.join(shown)} hold no extracted statement lines"
    return {
        "extracted": len(extracted),
        "covered": covered,
        "coverage": _ratio(covered, len(extracted)),
        "reason": reason,
        "pages": shown,
    }


def _printed(amount: Decimal, values: Sequence[Decimal | None]) -> bool:
    """Whether `amount` is one of a line's printed values; a nil dash (None) prints a zero."""
    return amount in values or (amount == 0 and None in values)


def _agreement_kind(amount: Decimal, matched: Sequence[ExtractedLine]) -> str:
    if not matched:
        return "unmatched"
    if any(_printed(amount, item.values) for item in matched):
        return "agreed"
    if any(_printed(-amount, item.values) for item in matched):
        return "sign_differs"
    return "disagreed"


def _agreement(
    books: Sequence[FinancialBook], pages: Mapping[tuple[str, str], ExtractedTable]
) -> dict[str, Any]:
    """Each payload statement line with an amount, on the extracted pages it cites (those with
    lines), against the extracted lines of its label (whitespace normalised) there: `agreed`
    when its amount is one of their `values` (a payload zero agrees with a printed nil dash),
    `sign_differs` when only its negation is (a `signed` expense the page prints as a magnitude,
    or a flipped sign: Python cannot tell which), `disagreed` otherwise, and `unmatched` when no
    extracted line there has its label. The first `MAX_DISAGREEMENTS` of the disagreements and
    of the sign differences are listed, in payload order."""
    kinds = ("agreed", "sign_differs", "disagreed", "unmatched")
    counts = dict.fromkeys((*kinds, "not_on_an_extracted_page", "without_amount"), 0)
    listed: dict[str, list[dict[str, Any]]] = {"disagreed": [], "sign_differs": []}
    for book in books:
        for line in book.statement_lines:
            amount = line.value.amount
            keys = dict.fromkeys((c.source_id, c.locator) for c in line.value.citations)
            on = [key for key in keys if key in pages and pages[key].lines]
            if amount is None or not on:
                counts["without_amount" if amount is None else "not_on_an_extracted_page"] += 1
                continue
            label = _normal(line.label)
            matched = [
                item for key in on for item in pages[key].lines if _normal(item.label) == label
            ]
            kind = _agreement_kind(amount, matched)
            counts[kind] += 1
            if kind in listed and len(listed[kind]) < MAX_DISAGREEMENTS:
                listed[kind].append(
                    {
                        "pages": [list(key) for key in on],
                        "line_id": line.line_id,
                        "period_id": line.period_id,
                        "label": line.label,
                        "payload_value": str(amount),
                        "sign_convention": line.sign_convention,
                        "extracted_values": [
                            [None if v is None else str(v) for v in item.values] for item in matched
                        ],
                    }
                )
    return {
        **counts,
        "disagreements": listed["disagreed"],
        "sign_differences": listed["sign_differs"],
    }


def extracted_coverage(
    payload: str, context: SourceContextReview, tables: Sequence[ExtractedTable]
) -> dict[str, Any] | None:
    """How much of the extracted statement lines a financials payload covers (task 8.12, user
    decision "C"; docs/testing-and-telemetry.md states the definition), and whether its amounts
    agree with them. Pure: `tables` are the extracted pages (each naming its source), the cells
    are `expected_cells(context)`. None for a payload that does not parse (the stage validator
    rejects it).

    Per cell (`cell_key`): the cell's extracted lines are every line of the tables of the
    `page:N` pages of the cell's source that the payload's lines of the cell's statement cite
    (in books bound to the scope's entity, any period). An extracted line is covered when a
    payload line of that statement, in a period the scope matches (`completeness_issues`'
    rule), cites its page with a quote holding one of its printed non-nil values as a whole
    number, or with its label equal after whitespace normalisation. Flagged lines count.
    `coverage` is covered / extracted (`_ratio`; None with the reason when nothing is
    extracted). `overall` sums every cell's counts (a line counts once per cell)."""
    try:
        submission = FinancialSubmission.model_validate_json(payload)
    except ValidationError:
        return None
    pages = _tables_by_page(tables)
    entities = {item.book_id: item.entity_id for item in submission.binding.books}
    cells: dict[str, dict[str, Any]] = {}
    for cell in expected_cells(context):
        books = [
            book
            for book in submission.financial.books
            if entities.get(book.book_id) == cell.scope.entity_id
        ]
        cells[cell_key(cell)] = _cell_coverage(cell, books, pages)
    extracted = sum(item["extracted"] for item in cells.values())
    covered = sum(item["covered"] for item in cells.values())
    reason = None
    if not any(table.lines for table in tables):
        reason = f"none of the {len(tables)} extracted pages holds a statement line"
    elif not extracted:
        reason = "no expected cell has extracted lines"
    return {
        "cells": cells,
        "overall": {
            "extracted": extracted,
            "covered": covered,
            "coverage": _ratio(covered, extracted),
            "reason": reason,
        },
        "agreement": _agreement(submission.financial.books, pages),
    }


def coverage_issues(
    payload: str, context: SourceContextReview, tables: Sequence[ExtractedTable], floor: Decimal
) -> tuple[str, ...]:
    """The coverage floor's issues (task 8.12): one per expected cell with extracted lines whose
    coverage is below `floor`, compared exactly (covered < floor x extracted; the shown
    four-place ratio agrees, `_ratio`). A cell with nothing extracted is not judged
    (`UNMEASURED_CELLS`), and a payload that does not parse has none (the stage validator
    rejects it with its own issues)."""
    measured = extracted_coverage(payload, context, tables)
    if measured is None:
        return ()
    return tuple(
        f"{INCOMPLETE}: coverage {item['coverage']} of {key} below the floor {floor} "
        f"({item['covered']} of {item['extracted']} extracted lines covered)"
        for key, item in measured["cells"].items()
        if item["extracted"] and Decimal(item["covered"]) < floor * item["extracted"]
    )


def seen_tables(
    tools: PackTools, seen: Seen, context: SourceContextReview
) -> tuple[ExtractedTable, ...]:
    """The extracted tables `extracted_coverage` reads for one `financials` submit (task 8.12):
    one per `page:N` span of a financial source of `context` (`classification: financial`) that
    the model had been shown by then (`seen.read`: through `read_pages` or
    `extract_statements`), in pack then page order. Never a page the model was not shown, so
    the work is bounded by what the step read, never the whole filing."""
    financial = {item.source_id for item in context.sources if item.classification == "financial"}
    tables: list[ExtractedTable] = []
    for source_id, source in tools.ready.items():
        if source_id not in financial:
            continue
        spans = {span.locator: span for span in source.spans if _PAGE.fullmatch(span.locator)}
        shown = sorted(
            (loc for ident, loc in seen.read if ident == source_id and loc in spans),
            key=_page_order,
        )
        tables += [
            extract_statement_lines(spans[loc].text, loc, source_id=source_id) for loc in shown
        ]
    return tuple(tables)


def _walk(node: object, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict):
        yield path, node
        for name, value in node.items():
            yield from _walk(value, f"{path}.{name}" if path else str(name))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}.{index}" if path else str(index))


def _enums(node: object) -> Iterator[tuple[str, str]]:
    """Every (property, enum value) a JSON schema allows, however nested."""
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            for name, spec in properties.items():
                yield from ((name, value) for value in _enum_values(spec))
        for value in node.values():
            yield from _enums(value)
    elif isinstance(node, list):
        for value in node:
            yield from _enums(value)


def _enum_values(spec: object) -> Iterator[str]:
    if isinstance(spec, dict):
        if isinstance(spec.get("enum"), list):
            yield from (v for v in spec["enum"] if isinstance(v, str))
        for option in spec.get("anyOf", ()):
            yield from _enum_values(option)


def absence_markers(step_id: str) -> tuple[tuple[str, str], ...]:
    """The `ABSENCE_MARKERS` a pack-tool step outside CP-1 can submit: those its sent schema's
    enums carry. None for CP-1's stages (8.0d's own fields) or a submit-only step."""
    if tool_set(step_id) == SUBMIT_ONLY or step_id in step_chain("CP-1").tool_steps:
        return ()
    allowed = set(_enums(strict_schema(STEPS[step_id].schema)))
    return tuple(marker for marker in ABSENCE_MARKERS if marker in allowed)


def absence_issues(step_id: str, payload: str, seen: Seen) -> tuple[str, ...]:
    """Absence claims made without a recorded search (none for a payload that is not an
    object). `source_context`: each source whose `event_scan` is `no_events_identified` needs a
    search over it. `financials`: a `missing` observation or a `not_disclosed` disclosure needs
    a search over some source. CP-1A and CP-4 (task 8.9 fix round 1): a row carrying one of the
    step's `absence_markers` needs a search over some source, as `financials` (the row does not
    name the source the undisclosed item belongs to). Other steps make no absence claim here."""
    document = _document(payload)
    if document is None:
        return ()
    markers = absence_markers(step_id)
    if markers and not seen.searched:
        return tuple(
            f"{UNBACKED_ABSENCE}: {path}.{name} {value}; search_pack before claiming it is not "
            "disclosed"
            for path, node in _walk(document)
            for name, value in markers
            if node.get(name) == value
        )
    issues: list[str] = []
    if step_id == "source_context":
        for path, node in _walk(document.get("sources")):
            source_id = node.get("source_id")
            if node.get("event_scan") == "no_events_identified" and isinstance(source_id, str):
                if not seen.searched_source(source_id):
                    issues.append(
                        f"{UNBACKED_ABSENCE}: sources.{path}.event_scan no_events_identified for "
                        f"{source_id}; search_pack that source before claiming no events"
                    )
    elif step_id == "financials" and not seen.searched:
        for path, node in _walk(document):
            status = node.get("status")
            observation = status == "missing" and "observation_id" in node
            disclosure = status == "not_disclosed" and "explanation" in node
            if observation or disclosure:
                issues.append(
                    f"{UNBACKED_ABSENCE}: {path}.status {status}; search_pack before claiming a "
                    "value or disclosure is absent"
                )
    return tuple(issues)


def unread_citation_issues(payload: str, seen: Seen) -> tuple[str, ...]:
    """Every cited `page:N` locator that `read_pages` never returned in this step."""
    unread = sorted(
        (source_id, locator)
        for source_id, locator in cited_locators(payload)
        if _PAGE.fullmatch(locator) and (source_id, locator) not in seen.read
    )
    return tuple(f"{UNREAD_PAGE}: {source_id} {locator}" for source_id, locator in unread)


def _cites_locators(step_id: str) -> bool:
    """Whether the step's sent schema has a `locator` field (a citation can name a page)."""

    def walk(node: object) -> bool:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict) and "locator" in properties:
                return True
            return any(walk(value) for value in node.values())
        return isinstance(node, list) and any(walk(value) for value in node)

    return walk(strict_schema(STEPS[step_id].schema))


def applicable_rules(step_id: str) -> tuple[str, ...]:
    """The rules a tool-loop step's submits can fail, in rule order (task 8.9).

    - CP-1's tool steps: both, as task 8.0d set them (for `narrative` and `readiness`, which
      cite evidence ids only and make no absence claim these rules read, both find nothing).
    - Every other pack-tool step (CP-0, CP-1A, CP-3, CP-4): the absence rule when its sent
      schema carries an `ABSENCE_MARKERS` value (CP-1A and CP-4, task 8.9 fix round 1; CP-0's
      and CP-3's do not), and the cited-page rule when it has a `locator` (each does).
    - A submit-only step: none (it reads nothing, so "read" and "searched" mean nothing)."""
    if tool_set(step_id) == SUBMIT_ONLY:
        return ()
    if step_id in step_chain("CP-1").tool_steps:
        return RULES
    applied = ((ABSENCE, bool(absence_markers(step_id))), (UNREAD, _cites_locators(step_id)))
    return tuple(rule for rule, applies in applied if applies)


@dataclass(frozen=True)
class ToolRules:
    """The evidence rules of the tool-loop steps. `floor`: the completeness floor's lines per
    statement and source scope for `financials` (settings; None: no floor). `coverage_min`
    (task 8.12, user decision "C"): the extracted-coverage floor for `financials`, a Decimal
    from 0 to 1 of at most four places (settings `extracted_coverage_min`; None: no floor;
    `coverage_issues`). Both floors may be set. `checked`: the rules turned on; each step
    applies those of them its contract can fail (`applicable_rules`)."""

    floor: int | None = None
    checked: tuple[str, ...] = RULES
    coverage_min: Decimal | None = None

    def __post_init__(self) -> None:
        if self.floor is not None and self.floor < 1:
            raise ValueError("the completeness floor is at least one line")
        if self.coverage_min is not None and not valid_coverage_floor(self.coverage_min):
            raise ValueError(
                "the extracted-coverage floor is a Decimal from 0 to 1 with at most "
                f"{COVERAGE_FLOOR_PLACES} decimal places, not {self.coverage_min!r}"
            )
        if unknown := sorted(set(self.checked) - set(RULES)):
            raise ValueError(f"unknown tool-loop rules {unknown}")

    @classmethod
    def from_settings(cls, settings: LiveSettings) -> "ToolRules":
        """The rules the settings turn on: both `[model_tests.completeness_floor]` floors."""
        return cls(floor=settings.completeness_floor, coverage_min=settings.extracted_coverage_min)

    def applied(self, step_id: str) -> tuple[str, ...]:
        """The rules turned on that `step_id` applies, in rule order."""
        return tuple(rule for rule in applicable_rules(step_id) if rule in self.checked)

    def floors(self, step_id: str) -> bool:
        """Whether a `financials` floor (line count or extracted coverage) judges `step_id`."""
        return step_id == "financials" and (self.floor, self.coverage_min) != (None, None)

    def active(self, step_id: str) -> bool:
        """Whether any rule can add an issue to `step_id`'s submits."""
        return bool(self.applied(step_id)) or self.floors(step_id)

    def issues(
        self,
        step_id: str,
        payload: str,
        *,
        seen: Seen,
        context: SourceContextReview | None,
        tables: Sequence[ExtractedTable] | None = None,
    ) -> tuple[str, ...]:
        """The rule issues of one submit, in rule order: the line-count floor's, the coverage
        floor's, then the absence and cited-page rules'. Either floor needs the retained
        `source_context` review (`context`), and the coverage floor the submit's extracted
        tables (`tables`, `seen_tables`); a `financials` submit without them raises, as does a
        submit-only step's (no rule is defined for it)."""
        if tool_set(step_id) == SUBMIT_ONLY:
            raise ValueError(f"{step_id} is submit-only: it checks no tool-loop rule")
        found: list[str] = []
        if self.floors(step_id):
            if context is None:
                raise ValueError("the completeness floor needs the retained source_context review")
            if self.floor is not None:
                found += completeness_issues(payload, context, self.floor)
            if self.coverage_min is not None:
                if tables is None:
                    raise ValueError("the extracted-coverage floor needs the extracted tables")
                found += coverage_issues(payload, context, tables, self.coverage_min)
        applied = self.applied(step_id)
        if ABSENCE in applied:
            found += absence_issues(step_id, payload, seen)
        if UNREAD in applied:
            found += unread_citation_issues(payload, seen)
        return tuple(found)

    def to_record(self, step_id: str | None = None) -> dict[str, Any]:
        """The settings, and with `step_id` the rules that step applies."""
        coverage = self.coverage_min
        record: dict[str, Any] = {
            "completeness_floor_lines": self.floor,
            "completeness_floor_reason": None
            if self.floor is not None
            else "no [model_tests.completeness_floor] in settings",
            "extracted_coverage_min": None if coverage is None else str(coverage),
            "extracted_coverage_min_reason": None
            if coverage is not None
            else "no [model_tests.completeness_floor] extracted_coverage_min in settings",
            "extracted_coverage_unmeasured": UNMEASURED_CELLS,
            "checked": list(self.checked),
        }
        if step_id is not None:
            record["applied"] = list(self.applied(step_id))
        return record
