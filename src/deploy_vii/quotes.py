"""The one quote matcher every citation check uses (task 2.9; decision 0008 amendment).

Span text is extracted from page layout: line breaks inside sentences, runs of spaces between
columns, curly quote marks, typographic dashes and soft hyphens. A model that copies a sentence
cleanly differs from the span only in those characters. Both sides are therefore compared after
one normalisation, `NORMALISATION`: soft hyphens are removed, curly single and double quote
marks and dashes (and the minus sign) become their ASCII forms, and any run of whitespace
(Unicode, including NBSP and line breaks) becomes one space. Case and every other character are
compared exactly, and the quote must still be one contiguous substring of the normalised text of
the span its locator names: there is no fuzzy match and no search of other spans.

Task 2.10 (probe-4, Sol 9594d016 p135): a word hyphenated across a line (`PUT-` then a newline,
optionally spaces, then `CALL`) is copied by a careful model as `PUT-CALL`. `HYPHEN_WRAP`
therefore also tries the span with each such wrap joined (`-`, newline and the spaces after it
become `-`). Task 7.11 (E1 batch e1-cp1-13, decision 0005): the same join on the quote side, for
a model that broke the line after a hyphen the span prints whole (`first-` then a newline and
`priority` for `first-priority`); the quote is tried as written and with its wraps joined,
against both readings of the span. A hyphen is never dropped or added, on either side, so a
quote whose wrapped hyphen has no hyphen in the span (`first priority`) still fails, and the
quote is still a contiguous substring of one reading. A two-column layout that interleaves
another column inside a sentence (probe-4 Sol p104, Grok p102) is not matched: a quote stitched
across it does not match (a known layout limit).

Normalisation only widens matching: any exact substring with visible text still matches, and
every quote accepted before task 7.11 still is. A quote with no visible text (only whitespace or
soft hyphens) matches nothing.

Task 7.0: `explain` says why a quote that does not match failed, for the issue text only; it
never changes acceptance (`quoted` decides that; `explain` does not alter its verdict, while task
7.11 widened `quoted` itself with the quote-side join above). In the order tried, over both span
readings: a case or character variant (the quote matches once case and a closed set of lookalike
quote marks and dashes, `_VARIANTS`, are folded; the first difference is named), a page straddle
(the quote's first run ends the span, at most `PAGE_EDGE_CHARS` of page furniture after it, and
the rest starts the next span of the same source, at most `PAGE_EDGE_CHARS` of running header
before it; or, cited where it ends, the first run ends the previous span and the rest starts the
cited one), a column interleave (the quote is two runs of the span, in order, with other span
text between them; named as columns or table cells only when at most `INTERLEAVE_GAP_CHARS` lie
between the runs, else as two separate runs). Every run has at least `MIN_RUN_WORDS` words.
Offsets count characters of the normalised quote. The `hyphen-wrap` label is printed only when
a wrap lies inside the span region the classification (or, unclassified, the quote's longest
matching prefix) occupies. Task 7.11: a quote with a wrap of its own is classified as written
first, then with its wraps joined (offsets then count the joined quote); the label is also
printed when the reported region exists only with the quote's wraps joined (a class that only
the joined quote has, or a longest prefix the join makes longer).
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial

NORMALISATION = "normalised whitespace, quote marks and dashes"
HYPHEN_WRAP = "hyphen-wrap"
PREFIX_CHARS = 200
ELLIPSIS = chr(0x2026)
MIN_RUN_WORDS = 2
PAGE_EDGE_CHARS = 200
INTERLEAVE_GAP_CHARS = 400

# Code points, not literals: the characters are easy to misread in source.
_SINGLE = (0x2018, 0x2019, 0x201A, 0x201B)  # curly and low-9 single quotes, apostrophe
_DOUBLE = (0x201C, 0x201D, 0x201E, 0x201F)  # curly and low-9 double quotes
_DASHES = (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)  # hyphens, dashes, minus
_SOFT_HYPHEN = 0x00AD
_MAP: dict[int, str | None] = {
    **dict.fromkeys(_SINGLE, "'"),
    **dict.fromkeys(_DOUBLE, '"'),
    **dict.fromkeys(_DASHES, "-"),
    _SOFT_HYPHEN: None,
}
# An ASCII hyphen that ends a line in the raw span text, with the spaces that start the next.
_WRAP = re.compile(r"-\n *")
# Explanation only (never matching): lookalikes the normalisation leaves as they are.
_VARIANTS: dict[int, str] = {
    **dict.fromkeys((0x0060, 0x00B4, 0x02B9, 0x02BB, 0x02BC, 0x2032, 0x2035, 0xFF07), "'"),
    **dict.fromkeys((0x00AB, 0x00BB, 0x02BA, 0x2033, 0x2036, 0xFF02), '"'),
    **dict.fromkeys((0x2043, 0xFE58, 0xFE63, 0xFF0D), "-"),
}


def normalise(text: str) -> str:
    """Mapped characters, every whitespace run as one space, no leading or trailing space.

    `str.split()` splits on exactly the characters `str.isspace()` (and the regex `\\s`) holds."""
    return " ".join(text.translate(_MAP).split())


def hyphen_wrapped(text: str) -> bool:
    """Whether the raw text (a span or a quote) holds a hyphenated line wrap (`HYPHEN_WRAP`)."""
    return _WRAP.search(text) is not None


def _joined(text: str) -> str:
    """`text` normalised with its hyphenated line wraps joined (each hyphen kept)."""
    return normalise(_WRAP.sub("-", text))


def _needles(quote: str) -> tuple[str, ...]:
    """The normalised quote, then (task 7.11) the same with its own wraps joined, if it differs."""
    plain = normalise(quote)
    joined = _joined(quote) if hyphen_wrapped(quote) else plain
    return (plain,) if joined == plain else (plain, joined)


def quoted(quote: str, text: str) -> bool:
    """Whether `quote` is a contiguous substring of `text`, both normalised, or of `text` with
    its hyphenated line wraps joined; the quote is tried as written and with its own wraps
    joined (task 7.11). A quote with no visible text matches nothing."""
    needles = _needles(quote)
    if not needles[0]:
        return False

    def readings() -> Iterator[str]:  # the joined span only once the plain one misses
        yield normalise(text)
        if hyphen_wrapped(text):
            yield _joined(text)

    return any(needle in reading for reading in readings() for needle in needles)


def prefix(quote: str) -> str:
    """The normalised quote, cut after at most `PREFIX_CHARS` characters on a word boundary
    (a single longer word is cut at `PREFIX_CHARS`), for an issue text (one line)."""
    needle = normalise(quote)
    if len(needle) <= PREFIX_CHARS:
        return needle
    cut = needle.rfind(" ", 0, PREFIX_CHARS + 1)
    return needle[: cut if cut > 0 else PREFIX_CHARS] + ELLIPSIS


@dataclass(frozen=True)
class Reading:
    """A normalised reading of raw span text; `origin[i]` is the raw index of `text[i]`."""

    text: str
    origin: tuple[int, ...]


def reading(raw: str, *, join_wraps: bool) -> Reading:
    """`normalise(raw)` (or of `raw` with its hyphen wraps joined), keeping where each character
    came from, so a region of the reading can be located in the raw text."""
    wraps = {m.start(): m.end() for m in _WRAP.finditer(raw)} if join_wraps else {}
    chars: list[tuple[str, int]] = []
    index = 0
    while index < len(raw):
        if index in wraps:
            chars.append(("-", index))
            index = wraps[index]
            continue
        mapped = raw[index].translate(_MAP)
        if mapped:
            chars.append((mapped, index))
        index += 1
    text: list[str] = []
    origin: list[int] = []
    space: int | None = None
    for char, at in chars:
        if char.isspace():
            space = at if text and space is None else space
            continue
        if space is not None:
            text.append(" ")
            origin.append(space)
            space = None
        text.append(char)
        origin.append(at)
    return Reading("".join(text), tuple(origin))


@dataclass(frozen=True)
class Explanation:
    """Why a quote is not in its span: the comparison label and the clause the issue appends
    after the quoted fragment (empty when no class applies)."""

    label: str
    hint: str = ""


@dataclass(frozen=True)
class _Found:
    reading: Reading
    start: int
    end: int
    hint: str


def _readings(raw: str) -> tuple[Reading, ...]:
    plain = reading(raw, join_wraps=False)
    return (plain, reading(raw, join_wraps=True)) if hyphen_wrapped(raw) else (plain,)


def _splits(needle: str) -> Iterator[tuple[str, str]]:
    """(first run, second run) at each space, longest first run first; each run has at least
    `MIN_RUN_WORDS` words."""
    words = needle.split(" ")
    for count in range(len(words) - MIN_RUN_WORDS, MIN_RUN_WORDS - 1, -1):
        yield " ".join(words[:count]), " ".join(words[count:])


def _fold(text: str) -> str:
    """Case and lookalike marks folded, one character for one, so offsets are kept."""
    return "".join(
        lower if len(lower := char.lower()) == 1 else char for char in text.translate(_VARIANTS)
    )


def _show(char: str) -> str:
    return f'"{char}" (U+{ord(char):04X})'


def _variant(needle: str, span: Reading) -> _Found | None:
    start = _fold(span.text).find(_fold(needle))
    if start < 0:
        return None
    offset = next(i for i, char in enumerate(needle) if span.text[start + i] != char)
    return _Found(
        span,
        start,
        start + len(needle),
        ": the quote matches the span only ignoring case and character variants; first "
        f"difference at offset {offset}: {_show(needle[offset])} in the quote, "
        f"{_show(span.text[start + offset])} in the span",
    )


def _interleave(needle: str, span: Reading) -> _Found | None:
    for first, second in _splits(needle):
        start = span.text.find(first)
        if start < 0:
            continue
        after = start + len(first)
        # Not adjacent: a second run straight after the first is a spacing difference.
        later = span.text.find(second, after + 1)
        if later >= 0 and span.text[after:later].strip():
            # Columns interleave within a few lines; runs further apart are not called that.
            apart = (
                "two runs separated by interleaved text (columns or table cells)"
                if later - after <= INTERLEAVE_GAP_CHARS
                else "two separate runs on this page"
            )
            return _Found(
                span,
                start,
                later + len(second),
                f": the quote matches the span as {apart} at offset {len(first)}; quote one "
                "contiguous run or choose another locator",
            )
    return None


@dataclass(frozen=True)
class _Neighbour:
    """The span next to the cited one in the same source: its locator and readings."""

    locator: str
    readings: tuple[Reading, ...]


def _ending(span: Reading, run: str) -> int:
    """Where the run's last occurrence starts if at most `PAGE_EDGE_CHARS` follow it, else -1."""
    start = span.text.rfind(run)
    return start if start >= 0 and len(span.text) - start - len(run) <= PAGE_EDGE_CHARS else -1


def _starting(span: Reading, run: str) -> int:
    """Where the run first occurs if at most `PAGE_EDGE_CHARS` precede it, else -1."""
    start = span.text.find(run)
    return start if 0 <= start <= PAGE_EDGE_CHARS else -1


def _continues(needle: str, span: Reading, *, following: _Neighbour) -> _Found | None:
    """The quote's first run ends the cited span and the rest starts the next one."""
    for first, second in _splits(needle):
        start = _ending(span, first)
        if start >= 0 and any(_starting(item, second) >= 0 for item in following.readings):
            return _Found(
                span,
                start,
                start + len(first),
                f": the quote continues on {following.locator}; quote within one page",
            )
    return None


def _begins(needle: str, span: Reading, *, preceding: _Neighbour) -> _Found | None:
    """The quote's first run ends the previous span and the rest starts the cited one."""
    for first, second in _splits(needle):
        start = _starting(span, second)
        if start >= 0 and any(_ending(item, first) >= 0 for item in preceding.readings):
            return _Found(
                span,
                start,
                start + len(second),
                f": the quote begins on {preceding.locator}; quote within one page",
            )
    return None


def _longest_prefix(needle: str, span: Reading) -> _Found:
    """The quote's longest prefix found in the reading (prefix presence is monotone)."""
    low, high = 0, len(needle)
    while low < high:
        middle = (low + high + 1) // 2
        if needle[:middle] in span.text:
            low = middle
        else:
            high = middle - 1
    start = span.text.find(needle[:low]) if low else 0
    return _Found(span, start, start + low, "")


def _wrap_inside(raw: str, found: _Found) -> bool:
    if found.end <= found.start:
        return False
    first, last = found.reading.origin[found.start], found.reading.origin[found.end - 1]
    return any(first <= m.start() <= last for m in _WRAP.finditer(raw))


def _neighbour(span: tuple[str, str] | None) -> _Neighbour | None:
    return None if span is None else _Neighbour(span[0], _readings(span[1]))


def _classify(
    needle: str,
    spans: tuple[Reading, ...],
    following: _Neighbour | None,
    preceding: _Neighbour | None,
) -> _Found | None:
    """The first class that holds, in order: variant, straddle onto the next span, straddle
    from the previous span, interleave (each reading of the cited span in turn)."""
    checks: list[Callable[[Reading], _Found | None]] = [partial(_variant, needle)]
    if following is not None:
        checks.append(partial(_continues, needle, following=following))
    if preceding is not None:
        checks.append(partial(_begins, needle, preceding=preceding))
    checks.append(partial(_interleave, needle))
    for check in checks:
        for span in spans:
            found = check(span)
            if found is not None:
                return found
    return None


def explain(
    quote: str,
    text: str,
    following: tuple[str, str] | None = None,
    preceding: tuple[str, str] | None = None,
) -> Explanation:
    """Why `quote` is not in the span `text` (the issue text only; acceptance is `quoted`).

    `following` and `preceding` are the next and previous spans of the same source,
    `(locator, text)`, where they exist. Raises ValueError for a quote that matches: there is
    nothing to explain."""
    if quoted(quote, text):
        raise ValueError("the quote matches its span; there is no mismatch to explain")
    needles = _needles(quote)
    spans = _readings(text)
    around = (_neighbour(following), _neighbour(preceding))
    found: _Found | None = None
    joined = False  # whether the reported region exists only with the quote's wraps joined
    for index, needle in enumerate(needles if needles[0] else ()):
        found = _classify(needle, spans, *around)
        if found is not None:
            joined = index > 0
            break
    if found is not None:
        regions = [found]
    else:
        # Unclassified: the attempted region is the quote's longest matching prefix, from the
        # joined quote only where joining carries the match further than the quote as written.
        regions, best = [], -1
        for index, needle in enumerate(needles):
            attempts = [_longest_prefix(needle, span) for span in spans]
            length = max(item.end - item.start for item in attempts)
            if length > best:
                best, joined = length, index > 0
                regions = [item for item in attempts if item.end - item.start == length]
    wrapped = joined or any(_wrap_inside(text, region) for region in regions)
    label = f"{NORMALISATION}; {HYPHEN_WRAP}" if wrapped else NORMALISATION
    return Explanation(label, found.hint if found is not None else "")
