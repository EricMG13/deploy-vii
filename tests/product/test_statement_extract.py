"""Python statement-line extraction from whitespace-aligned page text (task 8.10, decision "A")."""

from decimal import Decimal
from types import MappingProxyType

import pytest

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
        "Treasury stock, at cost       —          —",
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
    assert treasury.raw_values == ("—", "—")
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
            "Commitments and contingencies (Note 8          )",
        )
    )
    assert extract_statement_lines(text, "page:6").lines == ()


def test_single_spaced_numbers_stay_in_the_label() -> None:
    text = "Preferred stock, $0.00001 par value, 150,000,000 shares authorized        —        —"
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
