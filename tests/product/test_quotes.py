"""Task 7.0: the mismatch issue says why a quote failed; acceptance (`quoted`) is unchanged."""

import hashlib
import re

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from deploy_vii.contracts import Citation, Source, Span
from deploy_vii.execution import bounded_issues
from deploy_vii.quotes import (
    NORMALISATION,
    PAGE_EDGE_CHARS,
    PREFIX_CHARS,
    explain,
    normalise,
    prefix,
    quoted,
    reading,
)
from deploy_vii.readiness import citation_issues

RULE = NORMALISATION
WRAP_RULE = f"{NORMALISATION}; hyphen-wrap"

# The probe-4/6 shape (Sol 9594d016 and d7970902 p104, Grok 17a71fce p102), synthetic text: a
# two-column exhibit table whose right column ("Method of Filing") is printed between the two
# lines of a left-column sentence.
TWO_COLUMN = (
    "   4.7        Credit Agreement, dated as of March 3, 2021, by and among Synthetic Holdings, "
    "Inc., the lenders party thereto from time                             Previously filed on "
    "Form 8-K filed\n                to time, Example Bank, N.A., as administrative agent, and "
    "Example Trust Company, as collateral agent.                             on March 4, 2021.\n"
)
LEFT_SENTENCE = (
    "Credit Agreement, dated as of March 3, 2021, by and among Synthetic Holdings, Inc., the "
    "lenders party thereto from time to time, Example Bank, N.A., as administrative agent, and "
    "Example Trust Company, as collateral agent."
)
LEFT_FIRST_RUN = LEFT_SENTENCE.split(" to time,")[0]
RIGHT_CELL = "Previously filed on Form 8-K filed on March 4, 2021."
# The probe-5 shape (Gemini a3392cdd p76 to p77, 50115c10 p43 to p44): a sentence that runs past
# the page footer into the next page's running header, synthetic text.
PAGE_76 = (
    "SYNTHETIC HOLDINGS, INC. NOTES TO FINANCIAL STATEMENTS (CONTINUED)\nThe notes were redeemed "
    "in full with proceeds received from the sale of\n$25 million of receivables related to the "
    "previously disclosed\n\n\nTable of Contents\n                     76\n"
)
PAGE_77 = (
    "SYNTHETIC HOLDINGS, INC. NOTES TO FINANCIAL STATEMENTS (CONTINUED)\n\n\ntrademark sale. As a "
    "result, the Company recognized a loss on extinguishment of debt.\n"
)
STRADDLE = (
    "The notes were redeemed in full with proceeds received from the sale of $25 million of "
    "receivables related to the previously disclosed trademark sale."
)
CASED = "actors. Such forward-looking statements are only predictions and involve known risks"
WRAPPED = (
    "This FIRST AMENDMENT TO SECOND AMENDED AND RESTATED PUT-\nCALL  RIGHT  AGREEMENT is entered "
    "into as of May 1, 2023, among the parties"
)


def source(*pages: tuple[int, str]) -> Source:
    return Source(
        source_id="filing",
        name="Synthetic Form 10-K",
        status="ready",
        sha256=hashlib.sha256("".join(text for _, text in pages).encode()).hexdigest(),
        spans=tuple(Span(locator=f"page:{number}", text=text) for number, text in pages),
    )


def issues(pack_source: Source, locator: str, quote: str) -> tuple[str, ...]:
    assert pack_source.sha256
    citation = Citation(
        source_id="filing", source_sha256=pack_source.sha256, locator=locator, quote=quote
    )
    return citation_issues((citation,), (pack_source,))


# --- the four classes ------------------------------------------------------------------------


def test_a_sentence_reassembled_across_a_table_column_names_the_interleave() -> None:
    table = source((104, TWO_COLUMN))
    assert not quoted(LEFT_SENTENCE, TWO_COLUMN) and quoted(LEFT_FIRST_RUN, TWO_COLUMN)
    assert issues(table, "page:104", LEFT_SENTENCE) == (
        f"Quote/locator mismatch: quote not found under filing page:104 ({RULE}): "
        f'"{prefix(LEFT_SENTENCE)}": the quote matches the span as two runs separated by '
        f"interleaved text (columns or table cells) at offset {len(LEFT_FIRST_RUN)}; quote one "
        "contiguous run or choose another locator",
    )
    assert len(LEFT_FIRST_RUN) == 119


def test_the_right_column_reassembled_across_the_left_one_names_the_interleave() -> None:
    table = source((102, TWO_COLUMN))
    first = "Previously filed on Form 8-K filed"
    assert issues(table, "page:102", RIGHT_CELL) == (
        f"Quote/locator mismatch: quote not found under filing page:102 ({RULE}): "
        f'"{RIGHT_CELL}": the quote matches the span as two runs separated by interleaved text '
        f"(columns or table cells) at offset {len(first)}; quote one contiguous run or choose "
        "another locator",
    )


def test_a_quote_that_runs_onto_the_next_page_names_that_page() -> None:
    pages = source((76, PAGE_76), (77, PAGE_77))
    assert not quoted(STRADDLE, PAGE_76) and not quoted(STRADDLE, PAGE_77)
    assert issues(pages, "page:76", STRADDLE) == (
        f"Quote/locator mismatch: quote not found under filing page:76 ({RULE}): "
        f'"{STRADDLE}": the quote continues on page:77; quote within one page',
    )


def test_a_straddle_needs_the_join_at_the_page_edges_and_the_next_span_of_the_source() -> None:
    far = PAGE_76.replace("Table of Contents", "x " * PAGE_EDGE_CHARS)
    late = PAGE_77.replace("trademark sale.", "y " * PAGE_EDGE_CHARS + "trademark sale.")
    for pages in (
        source((76, far), (77, PAGE_77)),  # more than a footer after the first run
        source((76, PAGE_76), (77, late)),  # more than a header before the second run
        source((76, PAGE_76), (78, "unrelated"), (77, PAGE_77)),  # page:77 is not the next span
        source((76, PAGE_76)),  # no next span at all
    ):
        (issue,) = issues(pages, "page:76", STRADDLE)
        assert "continues on" not in issue
        assert issue.endswith(f'"{STRADDLE}"')


def test_a_quote_cited_where_it_ends_names_the_page_it_begins_on() -> None:
    """Probe-5 Gemini 50115c10 p44: the sentence starts at the foot of the previous page."""
    pages = source((76, PAGE_76), (77, PAGE_77))
    assert issues(pages, "page:77", STRADDLE) == (
        f"Quote/locator mismatch: quote not found under filing page:77 ({RULE}): "
        f'"{STRADDLE}": the quote begins on page:76; quote within one page',
    )
    late = PAGE_77.replace("trademark sale.", "y " * PAGE_EDGE_CHARS + "trademark sale.")
    (issue,) = issues(source((76, PAGE_76), (77, late)), "page:77", STRADDLE)
    assert issue.endswith(f'"{STRADDLE}"')


def test_a_case_change_names_the_first_differing_character_and_its_offset() -> None:
    page = source((13, CASED))
    quote = "Forward-looking statements are only predictions"
    assert issues(page, "page:13", quote) == (
        f"Quote/locator mismatch: quote not found under filing page:13 ({RULE}): "
        f'"{quote}": the quote matches the span only ignoring case and character variants; first '
        'difference at offset 0: "F" (U+0046) in the quote, "f" (U+0066) in the span',
    )


def test_a_lookalike_character_names_the_first_difference() -> None:
    prime = chr(0x2032)
    page = source((5, f"the issuer{prime}s notes due 2030 are senior secured"))
    (issue,) = issues(page, "page:5", "the issuer's notes due 2030")
    assert issue.endswith(
        f'first difference at offset 10: "\'" (U+0027) in the quote, "{prime}" (U+2032) in the span'
    )


def test_otherwise_the_issue_keeps_its_text() -> None:
    page = source((13, CASED))
    assert issues(page, "page:13", "invented words entirely") == (
        f'Quote/locator mismatch: quote not found under filing page:13 ({RULE}): "invented words '
        'entirely"',
    )
    # A changed word is not a character variant, a straddle or an interleave.
    (issue,) = issues(page, "page:13", "Such forward-looking statements are only guesses")
    assert issue.endswith('"Such forward-looking statements are only guesses"')


def test_a_one_word_tail_found_elsewhere_is_not_called_an_interleave() -> None:
    page = source((45, "We estimate lease payments to be\napproximately $1.4 billion for 2026."))
    quote = "We estimate lease payments to be approximately $1.4 billion."
    (issue,) = issues(page, "page:45", quote)
    assert "two runs" not in issue


# --- hyphen-wrap label and quoted fragment length --------------------------------------------


def test_hyphen_wrap_is_named_only_when_the_wrap_is_inside_the_attempted_match() -> None:
    page = source((135, WRAPPED))
    # Probe-5 Gemini p84: the span has a wrap, the failed quote is nowhere near it.
    (far,) = issues(page, "page:135", "entered into as of May 1, 2024")
    assert f"({RULE}):" in far
    # The quote matches through the wrap and then differs: the wrap is inside the region.
    (near,) = issues(page, "page:135", "RESTATED PUT-CALL RIGHT AGREEMENT is signed")
    assert f"({WRAP_RULE}):" in near
    # A quote wholly unrelated to the span never names it either.
    (none,) = issues(page, "page:135", "invented")
    assert f"({RULE}):" in none


def test_hyphen_wrap_is_named_when_a_classified_region_crosses_the_wrap() -> None:
    page = source((135, WRAPPED))
    quote = "restated put-call right agreement"
    (issue,) = issues(page, "page:135", quote)
    assert f"({WRAP_RULE}):" in issue and "first difference at offset 0" in issue


def test_quoted_fragments_are_cut_at_200_characters_on_a_word_boundary() -> None:
    assert PREFIX_CHARS == 200
    words = " ".join(f"word{index:03d}" for index in range(60))  # 8 characters each
    shown = prefix(words)
    assert shown.endswith(chr(0x2026))
    kept = shown[:-1]
    assert len(kept) <= PREFIX_CHARS and words.startswith(kept + " ")
    assert re.fullmatch(r"(word[0-9]{3} )*word[0-9]{3}", kept)
    assert prefix("short quote") == "short quote"
    assert prefix("x" * 250) == "x" * PREFIX_CHARS + chr(0x2026)  # one long token: a hard cut


# --- invariants ------------------------------------------------------------------------------


# Layout characters as code points: soft hyphen, curly apostrophe, NBSP.
LAYOUT = "ab -\n" + chr(0x00AD) + chr(0x2019) + chr(0x00A0)


@given(st.text(alphabet=LAYOUT), st.booleans())
def test_the_located_reading_is_exactly_the_matcher_reading(text: str, join: bool) -> None:
    located = reading(text, join_wraps=join)
    expected = normalise(re.sub(r"-\n *", "-", text) if join else text)
    assert located.text == expected
    assert len(located.origin) == len(located.text)
    assert list(located.origin) == sorted(located.origin)
    assert all(0 <= at < len(text) for at in located.origin)


_ALPHABET = "aAbB -\n'" + chr(0x2019)
_TEXT = st.text(alphabet=_ALPHABET, max_size=40)
_QUOTE = st.text(alphabet=_ALPHABET, min_size=1, max_size=40)  # Citation.quote is Text


@given(_QUOTE, _TEXT, st.one_of(st.none(), _TEXT))
def test_no_classification_ever_turns_a_non_substring_into_an_acceptance(
    quote: str, text: str, following: str | None
) -> None:
    pages = source((1, text), *(() if following is None else ((2, following),)))
    found = issues(pages, "page:1", quote)
    if quoted(quote, text):
        assert found == ()
        with pytest.raises(ValueError, match="matches"):
            explain(quote, text)
    else:
        (issue,) = found
        assert issue.startswith("Quote/locator mismatch: quote not found under filing page:1 (")


_OFFSET = re.compile(r"two runs .* at offset ([0-9]+);")


@given(
    st.lists(st.sampled_from(["ab", "cd", "ef", "Ab", "x-\n"]), min_size=4, max_size=12),
    st.integers(min_value=1, max_value=10),
)
@example(["ab", "cd", "ef", "ab", "cd"], 1)  # "ab cd ab cd": an interleave is claimed
def test_an_interleave_claim_is_true_of_the_span(words: list[str], cut: int) -> None:
    """Drop one word from a run of span words: whenever the issue says "two runs at offset N",
    the quote's first N characters and the rest are both in the span, in that order, apart."""
    text = " ".join(words)
    cut = cut % (len(words) - 1) + 1
    quote = " ".join(words[:cut] + words[cut + 1 :])
    if not normalise(quote) or quoted(quote, text):
        return
    match = _OFFSET.search(explain(quote, text).hint)
    if match is None:
        assert words != ["ab", "cd", "ef", "ab", "cd"]  # the example above is classified
        return
    needle, offset = normalise(quote), int(match.group(1))
    assert needle[offset] == " "
    assert any(
        (start := item.text.find(needle[:offset])) >= 0
        and item.text.find(needle[offset + 1 :], start + offset + 1) > start + offset
        for item in (reading(text, join_wraps=False), reading(text, join_wraps=True))
    )


def test_a_classified_issue_survives_the_journal_issue_bound() -> None:
    """The REPAIR block carries journal issues (`bounded_issues`): the hint must survive it."""
    (issue,) = issues(source((104, TWO_COLUMN)), "page:104", LEFT_SENTENCE)
    assert len(prefix(LEFT_SENTENCE)) > 190 and issue.endswith("choose another locator")
    assert bounded_issues([issue]) == (issue,)
