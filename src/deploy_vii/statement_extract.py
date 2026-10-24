"""Python statement-line extraction from whitespace-aligned page text (task 8.10).

User decision "A" (24 Oct 2026): Python extracts the printed statement lines and the model maps,
corrects and cites them instead of retyping them. One call reads one page's text and reports
only what is printed: each data line's label, its raw numeric cells and their exact `Decimal`
values, the label's indent, the caption above it and the raw header lines above the first data
line. It never rounds and never guesses a unit, period, item, statement or sign convention (the
model maps `period_id` and `item_id`). A line the rules cannot parse is omitted, never stubbed,
and prose yields an empty table.

Rules (docs/development/live-runner.md, "Statement extraction"):

- A line's cells are separated by two or more spaces. A data line is a label (with a letter)
  followed, to the end of the line, by two or more numeric cells: `10,441`, `2.42`, `(1,234)`
  (negative) or a lone em dash, en dash or hyphen (nil: value `None`, raw token kept). A `$`
  before a number, alone or attached, is folded into it and not kept in the raw value. A line
  whose cells are all bare four-digit years (`2025  2024`) is a header line, not data.
- A single cell of text with no digit and a lowercase letter, not ending in `:`, directly above
  a data line (no blank line between) continues its label; such lines join the label with one
  space and the indent is the first line's. A line ending in `:` is a sub-heading, not joined.
- A line with a letter, no lowercase letter and no digit is a caption; it applies to the data
  lines that follow until the next caption.
- `headers` are the raw lines nearest above the first data line holding two or more four-digit
  years or a month name, with the adjacent such lines above them (blank lines between allowed).
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_NIL_TOKENS = ("\u2014", "\u2013", "-")  # em dash, en dash, hyphen
_NILS = frozenset(_NIL_TOKENS)
_NIL = "|".join(_NIL_TOKENS)
_NUMERIC_CELL = re.compile(rf"(?P<dollar>\$ ?)?(?P<raw>\((?:{_NUMBER})\)|(?:{_NUMBER})|{_NIL})")
_CELL = re.compile(r"\S+(?: \S+)*")
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_BARE_YEAR = re.compile(r"(?:19|20)\d{2}")
_WORD = re.compile(r"[A-Za-z]+")
_MONTH_NAMES = (
    *("January", "February", "March", "April", "May", "June", "July", "August"),
    *("September", "October", "November", "December"),
)
_MONTHS = frozenset((*_MONTH_NAMES, *(name.upper() for name in _MONTH_NAMES)))


@dataclass(frozen=True)
class ExtractedLine:
    """One printed data line. `line_no` is the 1-based line of the page text holding the values;
    `raw_values[i]` is printed on that line and `values[i]` is its exact Decimal (None for a nil).
    """

    locator: str
    line_no: int
    label: str
    raw_values: tuple[str, ...]
    values: tuple[Decimal | None, ...]
    indent: int
    caption: str | None


@dataclass(frozen=True)
class ExtractedTable:
    """The data lines of one page's text, in page order, with the raw header lines."""

    locator: str
    headers: tuple[str, ...]
    lines: tuple[ExtractedLine, ...]


@dataclass(frozen=True)
class _Cells:
    label: str
    raw_values: tuple[str, ...]
    values: tuple[Decimal | None, ...]


def _value(raw: str) -> Decimal | None:
    if raw in _NILS:
        return None
    if raw.startswith("("):
        # Built from the string, never by negation: `-Decimal` would round to the context.
        return Decimal("-" + raw[1:-1].replace(",", ""))
    return Decimal(raw.replace(",", ""))


def _cells(line: str) -> _Cells | None:
    """The label and trailing numeric cells of a data line, or None for any other line."""
    found: list[tuple[str, bool]] = []  # (raw, a `$` is folded in), right to left
    start = len(line)
    for cell in reversed(list(_CELL.finditer(line))):
        text = cell.group()
        if text == "$" and found and not found[-1][1]:
            found[-1] = (found[-1][0], True)
        elif match := _NUMERIC_CELL.fullmatch(text):
            found.append((match["raw"], match["dollar"] is not None))
        else:
            break
        start = cell.start()
    label = line[:start].strip()
    if len(found) < 2 or not _WORD.search(label):
        return None
    if all(_BARE_YEAR.fullmatch(raw) and not dollar for raw, dollar in found):
        return None
    raws = tuple(raw for raw, _ in reversed(found))
    return _Cells(label=label, raw_values=raws, values=tuple(_value(raw) for raw in raws))


def _is_header(line: str) -> bool:
    return len(_YEAR.findall(line)) >= 2 or bool(_MONTHS.intersection(_WORD.findall(line)))


def _is_caption(stripped: str) -> bool:
    return (
        bool(_WORD.search(stripped))
        and not any(c.islower() for c in stripped)
        and not any(c.isdigit() for c in stripped)
    )


def _is_continuation(stripped: str) -> bool:
    return (
        _CELL.fullmatch(stripped) is not None
        and any(c.islower() for c in stripped)
        and not any(c.isdigit() for c in stripped)
        and not stripped.endswith(":")
        and not _is_header(stripped)
    )


def _headers(lines: Sequence[str], first: int) -> tuple[str, ...]:
    """The header block nearest above the 0-based line `first` (the first data line)."""
    index = first - 1
    while index >= 0 and not _is_header(lines[index]):
        index -= 1
    block: list[str] = []
    while index >= 0 and (_is_header(lines[index]) or not lines[index].strip()):
        if lines[index].strip():
            block.append(lines[index])
        index -= 1
    return tuple(reversed(block))


def extract_statement_lines(text: str, locator: str) -> ExtractedTable:
    """The printed data lines of one page's text (module docstring rules); prose yields none."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    found: list[ExtractedLine] = []
    first: int | None = None
    caption: str | None = None
    pending: list[str] = []  # continuation lines directly above the current line
    for index, line in enumerate(lines):
        stripped = line.strip()
        cells = _cells(line)
        if cells is not None:
            first = index if first is None else first
            head = pending[0] if pending else line
            found.append(
                ExtractedLine(
                    locator=locator,
                    line_no=index + 1,
                    label=" ".join((*(part.strip() for part in pending), cells.label)),
                    raw_values=cells.raw_values,
                    values=cells.values,
                    indent=len(head) - len(head.lstrip()),
                    caption=caption,
                )
            )
            pending = []
        elif _is_caption(stripped):
            caption = stripped
            pending = []
        elif _is_continuation(stripped):
            pending.append(line)
        else:
            pending = []
    headers = () if first is None else _headers(lines, first)
    return ExtractedTable(locator=locator, headers=headers, lines=tuple(found))


def _objects(value: object, missing: str, not_object: str) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(missing)
    objects: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(not_object)
        objects.append(item)
    return objects


def _pack_spans(pack_json: Mapping[str, object]) -> list[tuple[str, str, str]]:
    """(source_id, locator, text) of every span in pack order; a malformed pack raises."""
    found: list[tuple[str, str, str]] = []
    sources = pack_json.get("sources")
    for source in _objects(sources, "pack has no sources list", "a source is not an object"):
        source_id = source.get("source_id")
        if not isinstance(source_id, str):
            raise ValueError("a source has no string source_id")
        of = f"of source {source_id!r}"
        spans = source.get("spans")
        for span in _objects(
            spans, f"source {source_id!r} has no spans list", f"a span {of} is not an object"
        ):
            locator, text = span.get("locator"), span.get("text")
            if not isinstance(locator, str):
                raise ValueError(f"a span {of} has no string locator")
            if not isinstance(text, str):
                raise ValueError(f"span {locator!r} {of} has no string text")
            found.append((source_id, locator, text))
    return found


def extract_pack_statements(
    pack_json: Mapping[str, object], locators: Iterable[str] | None = None
) -> tuple[ExtractedTable, ...]:
    """One table per span of `sources[*].spans`, in pack order; read-only, no file I/O.

    With `locators` given, only those spans (phase 2 binds them to the step's declared sources).
    A table names its span by locator only, so a locator two sources share in scope raises
    rather than return a table whose source is ambiguous; a requested locator that no span has
    raises too. Every span in scope yields a table, an empty one for a page without data lines.
    """
    if isinstance(locators, str):
        # A str is an Iterable[str] of characters; reading it so would miss every page.
        raise TypeError("locators must be an iterable of locators, not one string")
    wanted = None if locators is None else frozenset(locators)
    owners: dict[str, str] = {}
    tables: list[ExtractedTable] = []
    for source_id, locator, text in _pack_spans(pack_json):
        if wanted is not None and locator not in wanted:
            continue
        if locator in owners:
            raise ValueError(
                f"locator {locator!r} is in sources {owners[locator]!r} and {source_id!r}; an "
                "extracted table names its span by locator only"
            )
        owners[locator] = source_id
        tables.append(extract_statement_lines(text, locator))
    if wanted is not None and (missing := sorted(wanted - owners.keys())):
        raise ValueError(f"locators not in the pack: {missing}")
    return tuple(tables)
