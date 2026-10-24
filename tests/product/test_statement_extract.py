"""Python statement-line extraction from whitespace-aligned page text (task 8.10, decision "A").

Fixtures `fixtures/statement_pages/czr-2025-10k-page-<N>.txt` are the verbatim `text` of spans
`page:56` (balance sheet), `page:57` (income statement), `page:60` (cash-flow statement) and
`page:10` (prose) of source `czr-2025-10k` in the public CZR FY2025 case pack
`artifacts/public-case/czr-fy2025-v2/pack.json`, sha256
2e7041297cecf15bc063e85bd22db32360a947bed776cc058da967477c9a2a29 (extractor pypdf/6.21.1). Each
file adds the one final newline the repository's end-of-file hook requires; `_page` removes it
and checks the span text's sha256 (`_PAGE_SHA256`). Pinned values were checked by hand against
the page text. A differential is not required (decision 0012): this is new behaviour, so its
invariants are property-tested instead.
"""

import hashlib
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.statement_extract import (
    ExtractedLine,
    ExtractedTable,
    extract_pack_statements,
    extract_statement_lines,
)

_SMALL = "\n".join(
    (
        "                     December 31,",
        "(In millions)        2025          2024",
        "CURRENT ASSETS:",
        "   Cash               $    887    $    866",
        "   Restricted cash          85         95",
        "Accumulated deficit      (3,303)    (2,801)",
        "Treasury stock, at cost       \u2014          \u2014",
        "Basic per share      $  (2.42)   $  3.65",
        "STOCKHOLDERS' EQUITY:",
        "   Other comprehensive",
        "      income, net of tax     -          5",
        "Footer page                              56",
    )
)


def test_data_lines_fold_dollars_and_read_negatives_and_nils() -> None:
    table = extract_statement_lines(_SMALL, "page:1")
    assert table.locator == "page:1"
    labels = [line.label for line in table.lines]
    assert labels == [
        "Cash",
        "Restricted cash",
        "Accumulated deficit",
        "Treasury stock, at cost",
        "Basic per share",
        "Other comprehensive income, net of tax",
    ]
    cash, _, deficit, treasury, per_share, wrapped = table.lines
    assert cash == ExtractedLine(
        locator="page:1",
        line_no=4,
        label="Cash",
        raw_values=("887", "866"),
        values=(Decimal("887"), Decimal("866")),
        indent=3,
        caption="CURRENT ASSETS:",
    )
    assert deficit.values == (Decimal("-3303"), Decimal("-2801"))
    assert deficit.raw_values == ("(3,303)", "(2,801)")
    assert treasury.values == (None, None)
    assert treasury.raw_values == ("\u2014", "\u2014")
    assert per_share.values == (Decimal("-2.42"), Decimal("3.65"))
    assert wrapped.line_no == 11
    assert wrapped.indent == 3
    assert wrapped.caption == "STOCKHOLDERS' EQUITY:"
    assert wrapped.raw_values == ("-", "5")
    assert wrapped.values == (None, Decimal("5"))


def test_headers_are_the_raw_year_and_month_lines_above_the_first_data_line() -> None:
    table = extract_statement_lines(_SMALL, "page:1")
    assert table.headers == (
        "                     December 31,",
        "(In millions)        2025          2024",
    )


def test_values_are_decimal_never_float_and_never_rounded() -> None:
    table = extract_statement_lines("Ratio of things     1.005     12,345.6789", "page:2")
    (line,) = table.lines
    assert line.values == (Decimal("1.005"), Decimal("12345.6789"))
    assert all(type(value) is Decimal for value in line.values)


def test_a_colon_sub_heading_is_not_joined_to_the_next_label() -> None:
    text = "\n".join(
        (
            "Adjustments to reconcile net income (loss) to net cash:",
            "   Depreciation and amortization        1,417        1,324",
        )
    )
    (line,) = extract_statement_lines(text, "page:3").lines
    assert line.label == "Depreciation and amortization"
    assert line.indent == 3


def test_spread_column_headings_are_not_joined_to_the_first_label() -> None:
    text = "\n".join(
        (
            "                    Paid-in     Accumulated       Comprehensive",
            "Balance, January 1, 2023        6,953   $       (3,309)  $              92",
        )
    )
    (line,) = extract_statement_lines(text, "page:9").lines
    assert line.label == "Balance, January 1, 2023"
    assert line.indent == 0
    assert line.values == (Decimal("6953"), Decimal("-3309"), Decimal("92"))


def test_a_blank_line_breaks_a_continuation() -> None:
    text = "Some wrapped\n\n   tail of the label        1        2"
    (line,) = extract_statement_lines(text, "page:4").lines
    assert line.label == "tail of the label"


def test_a_caption_holds_until_the_next_caption() -> None:
    text = "\n".join(
        (
            "Before any caption        1        2",
            "NET REVENUES:",
            "   Casino        6,617        6,267",
            "Some prose without numbers",
            "   Hotel         1,945        2,016",
            "OPERATING EXPENSES:",
            "   Casino        3,602        3,370",
        )
    )
    captions = [line.caption for line in extract_statement_lines(text, "page:5").lines]
    assert captions == [None, "NET REVENUES:", "NET REVENUES:", "OPERATING EXPENSES:"]


def test_a_line_with_fewer_than_two_numeric_cells_or_trailing_text_is_omitted() -> None:
    text = "\n".join(
        (
            "Only one value        1,234",
            "Trailing text        1,234        5,678        note",
            "Percent row        12        5.6 %",
            "        1,234        5,678",
            "*        1,234        5,678",
            "Commitments and contingencies (Note 8          )",
        )
    )
    assert extract_statement_lines(text, "page:6").lines == ()


def test_single_spaced_numbers_stay_in_the_label() -> None:
    text = (
        "Preferred stock, $0.00001 par value, 150,000,000 shares authorized"
        "        \u2014        \u2014"
    )
    (line,) = extract_statement_lines(text, "page:7").lines
    assert line.label == "Preferred stock, $0.00001 par value, 150,000,000 shares authorized"
    assert line.values == (None, None)


def test_prose_and_empty_text_yield_an_empty_table() -> None:
    prose = "to  make  such  disclosure  may  be  grounds  for  finding\nWe have 50,000 people."
    for text in (prose, "", "\n\n"):
        table = extract_statement_lines(text, "page:8")
        assert table.lines == ()
        assert table.headers == ()


def _pack(*sources: tuple[str, tuple[tuple[str, str], ...]]) -> dict[str, object]:
    return {
        "schema_version": "pack/1",
        "sources": [
            {
                "source_id": source_id,
                "spans": [{"locator": locator, "text": text} for locator, text in spans],
            }
            for source_id, spans in sources
        ],
    }


_ROW = "Goodwill        10,441        10,601"


def test_pack_extraction_reads_every_span_in_pack_order() -> None:
    pack = _pack(("a", (("page:2", _ROW), ("page:1", "prose only"))), ("b", (("sheet:x", _ROW),)))
    tables = extract_pack_statements(pack)
    assert [table.locator for table in tables] == ["page:2", "page:1", "sheet:x"]
    assert tables[0] == extract_statement_lines(_ROW, "page:2")
    assert tables[1] == ExtractedTable(locator="page:1", headers=(), lines=())


def test_pack_extraction_restricts_to_the_given_locators_and_is_read_only() -> None:
    spans = (("page:1", _ROW), ("page:2", _ROW), ("page:3", _ROW))
    pack = MappingProxyType(_pack(("a", spans)))
    tables = extract_pack_statements(pack, iter(["page:3", "page:1"]))
    assert [table.locator for table in tables] == ["page:1", "page:3"]
    assert extract_pack_statements(pack, ()) == ()
    assert pack == _pack(("a", spans))


def test_pack_extraction_refuses_an_unknown_locator() -> None:
    pack = _pack(("a", (("page:1", _ROW),)))
    with pytest.raises(ValueError, match=r"not in the pack: \['page:9'\]"):
        extract_pack_statements(pack, ["page:1", "page:9"])


def test_pack_extraction_refuses_a_locator_two_sources_share() -> None:
    pack = _pack(("a", (("page:1", _ROW),)), ("b", (("page:1", _ROW),)))
    with pytest.raises(ValueError, match=r"page:1.*sources 'a' and 'b'"):
        extract_pack_statements(pack)
    with pytest.raises(ValueError, match=r"page:1.*sources 'a' and 'b'"):
        extract_pack_statements(pack, ["page:1"])


@pytest.mark.parametrize(
    ("pack", "message"),
    [
        ({}, "pack has no sources list"),
        ({"sources": "x"}, "pack has no sources list"),
        ({"sources": [{"source_id": "a"}]}, "source 'a' has no spans list"),
        ({"sources": [{"spans": []}]}, "a source has no string source_id"),
        ({"sources": [{"source_id": "a", "spans": [{"locator": "p"}]}]}, r"span 'p'.*no string"),
        ({"sources": [{"source_id": "a", "spans": [{"text": "t"}]}]}, "a span of source 'a'"),
        ({"sources": ["x"]}, "a source is not an object"),
        ({"sources": [{"source_id": "a", "spans": ["x"]}]}, "a span of source 'a' is not an"),
    ],
)
def test_pack_extraction_refuses_a_malformed_pack(pack: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        extract_pack_statements(pack)


_PAGES = Path(__file__).parent / "fixtures" / "statement_pages"
_PAGE_SHA256 = {
    10: "df9b63edbced212cdd97d0c607dd067812401b0733efde75b53924a1bd5cd588",
    56: "8ea96c84da5732d98238257e110153696618aa2ebb12c8ab6925e62e269cfe60",
    57: "f747065db07b2cb4cd86000ae3ad410ff759d72b1d6418ce8e2e261b59f92d12",
    60: "fce2685337e781c04825302eaeba6c7f7fadaec807f3c0a854b5628df0c0f648",
}


def _page(number: int) -> str:
    stored = (_PAGES / f"czr-2025-10k-page-{number}.txt").read_text(encoding="utf-8")
    assert stored.endswith("\n")
    text = stored.removesuffix("\n")
    assert hashlib.sha256(text.encode()).hexdigest() == _PAGE_SHA256[number]
    return text


def _table(number: int) -> ExtractedTable:
    return extract_statement_lines(_page(number), f"page:{number}")


def _by_label(table: ExtractedTable, label: str) -> ExtractedLine:
    (line,) = (line for line in table.lines if line.label == label)
    return line


def _decimals(*raw: str | None) -> tuple[Decimal | None, ...]:
    return tuple(None if value is None else Decimal(value) for value in raw)


# Extracted data lines per page (BS 56, IS 57, CFS 60, prose 10); decision "C"'s completeness
# check reads these counts.
_COUNTS = {56: 33, 57: 29, 60: 38, 10: 0}


@pytest.mark.parametrize(("number", "count"), sorted(_COUNTS.items()))
def test_czr_page_line_counts(number: int, count: int) -> None:
    table = _table(number)
    assert len(table.lines) == count
    page_lines = _page(number).split("\n")
    for line in table.lines:
        assert all(raw in page_lines[line.line_no - 1] for raw in line.raw_values)
        assert line.label in page_lines[line.line_no - 1]


def test_czr_balance_sheet_pins() -> None:
    table = _table(56)
    lines = _page(56).split("\n")
    assert table.headers == (lines[3], lines[4])
    assert table.headers[0].strip() == "December 31,"
    assert table.headers[1].startswith("(Dollars in millions, except par value)")
    total = _by_label(table, "Total assets")
    assert (total.line_no, total.indent, total.caption) == (20, 6, "CURRENT ASSETS:")
    assert total.raw_values == ("31,639", "32,590")
    assert total.values == _decimals("31639", "32590")
    goodwill = _by_label(table, "Goodwill")
    assert goodwill.raw_values == ("10,441", "10,601")
    assert goodwill.values == _decimals("10441", "10601")
    deficit = _by_label(table, "Accumulated deficit")
    assert deficit.raw_values == ("(3,303)", "(2,801)")
    assert deficit.values == _decimals("-3303", "-2801")
    treasury = _by_label(table, "Treasury stock, at cost")
    assert treasury.raw_values == ("\u2014", "\u2014")
    assert treasury.values == (None, None)
    assert _by_label(table, "Accounts payable").caption == "CURRENT LIABILITIES:"
    assert _by_label(table, "Additional paid-in capital").caption == "STOCKHOLDERS' EQUITY:"
    (preferred,) = (line for line in table.lines if line.line_no == 35)
    assert preferred.label.startswith("Preferred stock, $0.00001 par value, 150,000,000 shares")
    assert preferred.values == (None, None)
    assert table.lines[-1].label == "Total liabilities and stockholders\u2019 equity"
    assert table.lines[-1].values == _decimals("31639", "32590")


def test_czr_income_statement_pins() -> None:
    table = _table(57)
    assert table.headers[0].strip() == "Years Ended December 31,"
    assert table.headers[1].startswith("(In millions, except per share data)")
    assert table.headers[1].split()[-3:] == ["2025", "2024", "2023"]
    assert len(table.headers) == 2
    revenue = _by_label(table, "Net revenues")
    assert revenue.caption == "NET REVENUES:"
    assert revenue.values == _decimals("11486", "11245", "11528")
    other = _by_label(table, "Transaction and other costs, net")
    assert other.raw_values == ("38", "(331)", "(13)")
    assert other.values == _decimals("38", "-331", "-13")
    # The colon sub-heading above it is not joined, and the `$` cells are folded in.
    basic = _by_label(table, "Basic income (loss) per share")
    assert basic.raw_values == ("(2.42)", "(1.29)", "3.65")
    assert basic.values == _decimals("-2.42", "-1.29", "3.65")
    assert [line.label for line in table.lines].count("Casino") == 2


def test_czr_cash_flow_pins() -> None:
    table = _table(60)
    assert [header.split()[-3:] for header in table.headers][-1] == ["2025", "2024", "2023"]
    depreciation = _by_label(table, "Depreciation and amortization")
    assert (depreciation.line_no, depreciation.indent) == (9, 3)
    assert depreciation.caption == "CASH FLOWS FROM OPERATING ACTIVITIES:"
    assert depreciation.values == _decimals("1417", "1324", "1261")
    distributions = _by_label(table, "Distributions from unconsolidated affiliate")
    assert distributions.raw_values == ("23", "39", "\u2014")
    assert distributions.values == _decimals("23", "39", None)
    closing = _by_label(table, "Cash, cash equivalents and restricted cash, end of period")
    assert closing.values == _decimals("984", "1016", "1143")
    assert closing.caption == "CASH FLOWS FROM FINANCING ACTIVITIES:"


def test_czr_prose_page_yields_nothing() -> None:
    assert _table(10) == ExtractedTable(locator="page:10", headers=(), lines=())


def test_czr_pack_built_from_the_fixtures_matches_the_page_calls() -> None:
    spans = tuple((f"page:{number}", _page(number)) for number in sorted(_COUNTS))
    tables = extract_pack_statements(_pack(("czr-2025-10k", spans)), ["page:56", "page:60"])
    assert tables == (_table(56), _table(60))


# Verbatim lines 16-20 of span `page:59` (statement of stockholders' equity), same pack.
_WRAPPED = "\n".join(
    (
        "   Shares withheld related to",
        "      net share settlement of",
        (
            "      stock awards                      \u2014          \u2014        "
            "  \u2014          \u2014            (27)              \u2014               "
            "    \u2014               \u2014                  \u2014                (27)"
        ),
        "   Transactions with",
        (
            "      noncontrolling interests          \u2014          \u2014        "
            "  \u2014          \u2014            (29)              \u2014               "
            "    \u2014               \u2014                  88                59"
        ),
    )
)


def test_czr_wrapped_label_is_joined() -> None:
    shares, transactions = extract_statement_lines(_WRAPPED, "page:59").lines
    assert shares.label == "Shares withheld related to net share settlement of stock awards"
    assert (shares.line_no, shares.indent) == (3, 3)
    assert shares.values == (*(None,) * 4, Decimal("-27"), *(None,) * 4, Decimal("-27"))
    assert transactions.label == "Transactions with noncontrolling interests"
    assert (transactions.line_no, transactions.indent) == (5, 3)
    assert transactions.raw_values[-2:] == ("88", "59")


# Properties over generated label + numeric-cell lines.
Row = tuple[str, str, int, list[Decimal | None]]
_LABELS = st.from_regex(r"[A-Z][a-z]{1,8}(?: [a-z]{1,8}){0,4}", fullmatch=True)
_AMOUNTS = st.one_of(
    st.none(),
    st.integers(min_value=-(10**12), max_value=10**12).map(Decimal),
    st.decimals(min_value=-(10**9), max_value=10**9, places=2),
    # Beyond the default 28-digit context: a value built by arithmetic would round here.
    st.integers(min_value=10**28, max_value=10**40).map(lambda n: Decimal(-n)),
)


@st.composite
def _cell(draw: st.DrawFn) -> tuple[str, Decimal | None]:
    value = draw(_AMOUNTS)
    if value is None:
        number = draw(st.sampled_from(("\u2014", "\u2013", "-")))
    elif value < 0:
        number = f"({value.copy_abs():,f})"
    else:
        number = f"{value:,f}"
    dollar = draw(st.sampled_from(("", "$", "$ ", "$  ", "$" + " " * 19)))
    return " " * draw(st.integers(min_value=2, max_value=30)) + dollar + number, value


@st.composite
def _row(draw: st.DrawFn, cells: st.SearchStrategy[int]) -> Row:
    label = draw(_LABELS)
    indent = draw(st.integers(min_value=0, max_value=12))
    drawn = [draw(_cell()) for _ in range(draw(cells))]
    line = " " * indent + label + "".join(text for text, _ in drawn)
    return line, label, indent, [value for _, value in drawn]


@settings(max_examples=200, deadline=None)
@given(_row(st.integers(min_value=2, max_value=8)))
def test_generated_data_line_round_trips(row: Row) -> None:
    line, label, indent, values = row
    (extracted,) = extract_statement_lines(line, "page:1").lines
    assert (extracted.label, extracted.indent, extracted.line_no) == (label, indent, 1)
    assert all(raw in line for raw in extracted.raw_values)
    assert list(extracted.values) == values
    assert all(value is None or type(value) is Decimal for value in extracted.values)


@settings(max_examples=200, deadline=None)
@given(_row(st.integers(min_value=0, max_value=1)))
def test_generated_line_with_fewer_than_two_cells_is_never_extracted(row: Row) -> None:
    assert extract_statement_lines(row[0], "page:1").lines == ()


_FILLER = st.sampled_from(
    (
        "",
        "NET REVENUES:",
        "CASH FLOWS FROM INVESTING ACTIVITIES:",
        "   Other comprehensive",
        "Adjustments to reconcile net income to cash:",
        "Table of Contents",
        "                                  56",
        "                 Years Ended December 31,",
        "(In millions)        2025        2024",
    )
)


def _render(lines: Sequence[ExtractedLine]) -> str:
    out: list[str] = []
    caption: str | None = None
    for line in lines:
        if line.caption is not None and line.caption != caption:
            out.append(line.caption)
        caption = line.caption
        out.append(" " * line.indent + line.label + "".join(f"  {raw}" for raw in line.raw_values))
    return "\n".join(out)


def _shape(table: ExtractedTable) -> list[tuple[object, ...]]:
    return [(x.label, x.raw_values, x.values, x.indent, x.caption) for x in table.lines]


@settings(max_examples=150, deadline=None)
@given(st.lists(st.one_of(_FILLER, _row(st.integers(2, 6)).map(lambda row: row[0])), max_size=25))
def test_page_extraction_is_deterministic_and_idempotent(page_lines: list[str]) -> None:
    text = "\n".join(page_lines)
    first = extract_statement_lines(text, "page:1")
    assert extract_statement_lines(text, "page:1") == first
    for line in first.lines:
        assert all(raw in page_lines[line.line_no - 1] for raw in line.raw_values)
    again = extract_statement_lines(_render(first.lines), "page:1")
    assert _shape(again) == _shape(first)
    assert extract_statement_lines(_render(again.lines), "page:1") == again
