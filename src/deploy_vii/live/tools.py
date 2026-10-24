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
- `absence_issues`: a claim that something is not in the source (a source's
  `event_scan: no_events_identified`, a `missing` observation, a `not_disclosed` disclosure)
  needs a recorded `search_pack` over that source (or over every source) earlier in the step.
- `unread_citation_issues`: every `page:N` the payload cites was returned by `read_pages`
  earlier in the step. Other locators are not pages and are not checked by this rule.
"""

import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ValidationError

from deploy_vii.contracts import Span
from deploy_vii.cp1_workflow import FinancialSubmission
from deploy_vii.live.prompts import block, span_line
from deploy_vii.live.schema import strict_schema
from deploy_vii.live.submission import STEPS
from deploy_vii.preparation import PreparedPack
from deploy_vii.source_context import ReportingScope, SourceContextReview, scope_matches_period

MAX_PAGES_PER_READ = 5
MAX_HITS = 15
DEFAULT_HITS = 10
SNIPPET_CHARS = 300
TOOL_CHOICE = "required"
SEARCH, READ = "search_pack", "read_pages"
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


class ToolError(Exception):
    """A tool call the loop refuses; its message becomes the tool result."""


def submit_name(step_id: str) -> str:
    return f"submit_{step_id}"


def _function(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def tool_specs(step_id: str) -> tuple[dict[str, Any], ...]:
    """`search_pack`, `read_pages` and `submit_<step_id>`, as the harness offers them."""
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
        _function(
            submit_name(step_id),
            f"Submit the {step_id} JSON object. Answers `accepted` or the validator's issues.",
            strict_schema(STEPS[step_id].schema),
        ),
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

    `read`: the (source, `page:N`) spans `read_pages` returned. `surfaced`: the spans a search
    showed a snippet of. `searched`: the scope of each search that returned a result (None:
    every source)."""

    def __init__(self, pack: PreparedPack) -> None:
        self.ready = {s.source_id: s for s in pack.sources if s.status == "ready" and s.sha256}
        self.ids = tuple(source.source_id for source in pack.sources)
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
        self.surfaced: set[tuple[str, str]] = set()
        self.searched: list[str | None] = []

    def _source(self, source_id: object) -> str:
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

    def seen(self) -> "Seen":
        """What the model has been shown so far, frozen (a submit is judged on this)."""
        return Seen(frozenset(self.read), tuple(self.searched))


@dataclass(frozen=True)
class Seen:
    """The pages `read_pages` returned and the scope of each search (None: every source), as
    of one submit."""

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


def _walk(node: object, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict):
        yield path, node
        for name, value in node.items():
            yield from _walk(value, f"{path}.{name}" if path else str(name))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}.{index}" if path else str(index))


def absence_issues(step_id: str, payload: str, seen: Seen) -> tuple[str, ...]:
    """Absence claims made without a recorded search (none for a payload that is not an
    object). `source_context`: each source whose `event_scan` is `no_events_identified` needs a
    search over it. `financials`: a `missing` observation or a `not_disclosed` disclosure needs
    a search over some source. Other steps make no pack absence claim here."""
    document = _document(payload)
    if document is None:
        return ()
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


@dataclass(frozen=True)
class ToolRules:
    """The evidence rules of a tool-loop step. `floor`: the completeness floor's lines per
    statement and source scope for `financials` (settings; None: no floor)."""

    floor: int | None = None
    checked: tuple[str, ...] = RULES

    def __post_init__(self) -> None:
        if self.floor is not None and self.floor < 1:
            raise ValueError("the completeness floor is at least one line")
        if unknown := sorted(set(self.checked) - set(RULES)):
            raise ValueError(f"unknown tool-loop rules {unknown}")

    def active(self, step_id: str) -> bool:
        """Whether any rule can add an issue to `step_id`'s submits."""
        return bool(self.checked) or (step_id == "financials" and self.floor is not None)

    def issues(
        self,
        step_id: str,
        payload: str,
        *,
        seen: Seen,
        context: SourceContextReview | None,
    ) -> tuple[str, ...]:
        """The rule issues of one submit, in rule order. The floor needs the retained
        `source_context` review (`context`); a `financials` submit without one raises."""
        found: list[str] = []
        if step_id == "financials" and self.floor is not None:
            if context is None:
                raise ValueError("the completeness floor needs the retained source_context review")
            found += completeness_issues(payload, context, self.floor)
        if ABSENCE in self.checked:
            found += absence_issues(step_id, payload, seen)
        if UNREAD in self.checked:
            found += unread_citation_issues(payload, seen)
        return tuple(found)

    def to_record(self) -> dict[str, Any]:
        return {
            "completeness_floor_lines": self.floor,
            "completeness_floor_reason": None
            if self.floor is not None
            else "no [model_tests.completeness_floor] in settings",
            "checked": list(self.checked),
        }
