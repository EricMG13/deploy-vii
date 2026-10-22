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
optionally spaces, then `CALL`) is copied by a careful model as `PUT-CALL`. On the span side
only, `HYPHEN_WRAP` therefore also tries the span with each such wrap joined (`-`, newline and
the spaces after it become `-`). The model's quote is normalised as before and its hyphens are
never altered; the hyphen itself is never dropped. Both readings of the span are tried, so the
quote is still a contiguous substring of one of them. A two-column layout that interleaves
another column inside a sentence (probe-4 Sol p104, Grok p102) is not handled: a quote stitched
across it does not match (a known layout limit).

Normalisation only widens matching: any exact substring with visible text still matches. A quote
with no visible text (only whitespace or soft hyphens) matches nothing.
"""

import re

NORMALISATION = "normalised whitespace, quote marks and dashes"
HYPHEN_WRAP = "hyphen-wrap"
PREFIX_CHARS = 60
ELLIPSIS = chr(0x2026)

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


def normalise(text: str) -> str:
    """Mapped characters, every whitespace run as one space, no leading or trailing space.

    `str.split()` splits on exactly the characters `str.isspace()` (and the regex `\\s`) holds."""
    return " ".join(text.translate(_MAP).split())


def hyphen_wrapped(text: str) -> bool:
    """Whether the raw span text holds a hyphenated line wrap (`HYPHEN_WRAP` applies to it)."""
    return _WRAP.search(text) is not None


def quoted(quote: str, text: str) -> bool:
    """Whether `quote` is a contiguous substring of `text`, both normalised, or of `text` with
    its hyphenated line wraps joined first (span side only)."""
    needle = normalise(quote)
    if not needle:
        return False
    return needle in normalise(text) or (
        hyphen_wrapped(text) and needle in normalise(_WRAP.sub("-", text))
    )


def normalisation(text: str) -> str:
    """How a quote was compared with the span `text`, for an issue text."""
    return f"{NORMALISATION}; {HYPHEN_WRAP}" if hyphen_wrapped(text) else NORMALISATION


def prefix(quote: str) -> str:
    """The normalised quote's first `PREFIX_CHARS` characters, for an issue text (one line)."""
    needle = normalise(quote)
    return needle if len(needle) <= PREFIX_CHARS else needle[:PREFIX_CHARS] + ELLIPSIS
