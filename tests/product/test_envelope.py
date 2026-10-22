"""Canonical CP-1 envelope: r14 order, lossless cells, resolved prose, round trip, tampering."""

import hashlib
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from deploy_vii.contracts import (
    Citation,
    Claim,
    Fact,
    Input,
    Module,
    ReportTable,
    Run,
    TableColumn,
    TableRow,
)
from deploy_vii.cp1_workflow import cp1_registers
from deploy_vii.envelope import (
    SECTIONS,
    Envelope,
    EnvelopeError,
    envelope_issues,
    handoff_issues,
    read_envelope,
    register_envelope,
    write_envelope,
)
from deploy_vii.table_markdown import read_table_markdown
from tests.product.test_cp1_workflow import staged

RUN = Run(
    run_id="envelope-run",
    issuer_id="issuer",
    issuer_name="Issuer Co",
    as_of=date(2026, 2, 1),
    case_kind="public",
)
SOURCE = "a" * 64
PACK = Input(input_id="pack", sha256="b" * 64)


def _fact(table: str, row: str, field: str, **values: object) -> Fact:
    return Fact.model_validate(
        {
            "fact_id": f"{table}:{row}:{field}",
            "label": f"{field} of {row}",
            "table_id": table,
            "row_id": row,
            "field": field,
            **values,
        }
    )


def _amount(table: str, row: str, field: str, amount: Decimal) -> Fact:
    return _fact(
        table,
        row,
        field,
        amount=amount,
        unit="MILLIONS",
        currency="USD",
        period="FY2025",
        calculation_id=f"calc:{table}:{row}:{field}",
        formula="supplied amount",
    )


def small_module(
    cells: list[list[Fact]],
    claims: tuple[Claim, ...] = (),
    *,
    interface: list[Fact] = (),
    table: str = "T4.1",
) -> Module:
    """A synthetic CP-1 module: rows of two cells and an optional T4.14 interface row."""
    rows = tuple(
        TableRow(row_id=row[0].row_id, label=row[0].row_id, fact_ids=tuple(f.fact_id for f in row))
        for row in cells
    )
    tables = [
        ReportTable(
            table_id=table,
            title="Source Register",
            columns=(
                TableColumn(field="amount", label="Amount | value"),
                TableColumn(field="note", label="Note <text>"),
            ),
            rows=rows,
        )
    ]
    if interface:
        tables.append(
            ReportTable(
                table_id="T4.14",
                title="Model Period Register",
                interface_id="cp1.model_period_register",
                columns=tuple(TableColumn(field=f.field, label=f.field) for f in interface),
                rows=(
                    TableRow(
                        row_id=interface[0].row_id,
                        label=interface[0].row_id,
                        fact_ids=tuple(f.fact_id for f in interface),
                    ),
                ),
            )
        )
    return Module(
        run_id=RUN.run_id,
        issuer_id=RUN.issuer_id,
        as_of=RUN.as_of,
        module_id="CP-1",
        inputs=(PACK,),
        facts=(*(f for row in cells for f in row), *interface),
        tables=tuple(tables),
        claims=claims,
        limitations=("Synthetic envelope module",),
    )


def small_envelope() -> Envelope:
    rows = [
        [
            _amount("T4.1", "r1", "amount", Decimal("1234.5")),
            _fact("T4.1", "r1", "note", text="Pipe | and <b>markup</b>\nsecond line"),
        ],
        [
            _fact("T4.1", "r2", "amount", status="missing", limitation="Not disclosed"),
            _fact("T4.1", "r2", "note", status="not_applicable", limitation="No note applies"),
        ],
    ]
    cite = Citation(source_id="S1", source_sha256=SOURCE, locator="page:1", quote="Revenue")
    claim = Claim(
        claim_id="liquidity",
        text="Liquidity is {T4.1:r1:amount} while [T4.1:r2:amount] stays open",
        citations=(cite,),
    )
    period = [
        _fact("T4.14", "p1", "period_id", text="FY2025"),
        _fact("T4.14", "p1", "day_count", status="missing", limitation="Dates not stated"),
    ]
    return Envelope(
        run=RUN,
        module=small_module(rows, (claim,), interface=period),
        registers_sha256="c" * 64,
        gap_limitations=("Synthetic gap register",),
    )


def _h2(markdown: str) -> list[str]:
    return [line[3:] for line in markdown.split("\n") if line.startswith("## ")]


def test_sections_are_the_seventeen_r14_h2s_in_order() -> None:
    markdown, _ = write_envelope(small_envelope())
    assert _h2(markdown) == [name for name, _ in SECTIONS]
    assert len(SECTIONS) == 17
    assert SECTIONS[0][0] == "Source Register" and SECTIONS[-1][0] == "Module Handoff"


def test_absent_tables_and_empty_sections_carry_their_line_never_omitted() -> None:
    markdown, _ = write_envelope(small_envelope())
    assert "Not produced: T4.4 is not in this module." in markdown
    assert "Not produced: no QA report is bound to this envelope." in markdown
    assert "### Inherited limitations\n\nNot applicable: none recorded." in markdown


def test_unsettled_cells_are_gap_markers_and_null_lives_only_in_the_sidecar() -> None:
    markdown, sidecar = write_envelope(small_envelope())
    body = markdown.split("### T4.1 — Source Register\n\n", 1)[1].split("\n\n", 1)[0]
    table = read_table_markdown(body)
    assert table.rows == (
        ("1234.5", "Pipe | and <b>markup</b>\nsecond line"),
        ("∅ G1", "∅ G2 n.m."),
    )
    cells = [cell.casefold() for row in table.rows for cell in row]
    assert "null" not in cells and "none" not in cells
    assert not re.search(r"\b(null|None)\b", markdown)
    assert '"amount":null' in sidecar


def test_claims_are_resolved_run_text_with_markers_listed_after() -> None:
    markdown, _ = write_envelope(small_envelope())
    line = next(x for x in markdown.split("\n") if x.startswith("- liquidity: "))
    assert line == "- liquidity: Liquidity is 1,235 US$ m [K1] while ∅ [G1] stays open"
    assert "{" not in line and "T4.1:r1" not in line
    evidence = markdown.split("### Evidence list\n\n", 1)[1].split("\n\n", 1)[0]
    markers = [row[0] for row in read_table_markdown(evidence).rows]
    assert markers == ["K1", "G1", "G2", "G3"]  # report-id allocation order, used ones only


def test_write_is_deterministic_and_round_trips() -> None:
    envelope = small_envelope()
    first, sidecar = write_envelope(envelope)
    second, again = write_envelope(Envelope.model_validate_json(sidecar))
    assert hashlib.sha256(first.encode()).digest() == hashlib.sha256(second.encode()).digest()
    assert sidecar == again
    assert read_envelope(first, sidecar) == envelope


def test_one_changed_digit_in_a_table_cell_is_detected() -> None:
    markdown, sidecar = write_envelope(small_envelope())
    tampered = markdown.replace("| 1234.5 |", "| 1234.6 |", 1)
    assert tampered != markdown
    issues = envelope_issues(tampered, sidecar)
    assert any(
        "Source Register / T4.1" in i and "'1234.6'" in i and "'1234.5'" in i for i in issues
    )
    with pytest.raises(EnvelopeError):
        read_envelope(tampered, sidecar)


def test_one_dropped_section_is_detected() -> None:
    markdown, sidecar = write_envelope(small_envelope())
    start = markdown.index("## Normalized BS\n")
    end = markdown.index("## Normalized CFS\n")
    issues = envelope_issues(markdown[:start] + markdown[end:], sidecar)
    assert "Missing section: Normalized BS" in issues


def test_reordered_sections_are_detected() -> None:
    markdown, sidecar = write_envelope(small_envelope())
    first, second = "## Normalized IS\n", "## Normalized BS\n"
    a, b, c = markdown.index(first), markdown.index(second), markdown.index("## Normalized CFS\n")
    swapped = markdown[:a] + markdown[b:c] + markdown[a:b] + markdown[c:]
    assert "Sections are not in the r14 order" in envelope_issues(swapped, sidecar)


def test_a_marker_that_does_not_resolve_is_detected() -> None:
    markdown, sidecar = write_envelope(small_envelope())
    row = next(x for x in markdown.split("\n") if x.startswith("| K1 | calculated |"))
    issues = envelope_issues(markdown.replace(row + "\n", ""), sidecar)
    assert "Marker K1 does not resolve in the evidence list" in issues


def test_a_footer_hash_that_does_not_match_the_sidecar_is_detected() -> None:
    envelope = small_envelope()
    markdown, sidecar = write_envelope(envelope)
    digest = envelope.module.content_hash()
    issues = envelope_issues(markdown.replace(digest, "0" * 64), sidecar)
    assert "Provenance footer module_sha256 does not match the sidecar" in issues


def test_a_bare_figure_in_the_markdown_prose_is_detected() -> None:
    markdown, sidecar = write_envelope(small_envelope())
    tampered = markdown.replace("stays open", "stays open at 5.2x", 1)
    assert any("Evidence Trace / Findings" in i for i in envelope_issues(tampered, sidecar))


def test_a_sidecar_claim_with_a_bare_figure_cannot_be_written_or_read() -> None:
    envelope = small_envelope()
    claim = envelope.module.claims[0].model_copy(update={"text": "Leverage is 5.2x"})
    module = envelope.module.model_copy(update={"claims": (claim,)})
    bad = envelope.model_copy(update={"module": module})
    with pytest.raises(ValueError, match="Bare figure"):
        write_envelope(bad)
    issues = handoff_issues(bad)
    assert len(issues) == 1 and issues[0].startswith("Canonical envelope cannot be written")


def test_an_unplaced_table_and_a_known_gap_marker_text_fail_closed() -> None:
    envelope = small_envelope()
    stray = small_module(
        [[_amount("T9.9", "r", "amount", Decimal(1)), _fact("T9.9", "r", "note", text="x")]],
        table="T9.9",
    )
    with pytest.raises(ValueError, match=r"No r14 envelope section for table: T9\.9"):
        write_envelope(envelope.model_copy(update={"module": stray}))
    marker = small_module(
        [[_amount("T4.1", "r", "amount", Decimal(1)), _fact("T4.1", "r", "note", text="∅ G7")]]
    )
    with pytest.raises(ValueError, match="would read as a gap marker"):
        write_envelope(envelope.model_copy(update={"module": marker}))


def test_sidecar_identity_must_match_the_run_and_bind_its_journal() -> None:
    envelope = small_envelope()
    with pytest.raises(ValueError, match="identity differs"):
        Envelope.model_validate(
            {**envelope.model_dump(), "run": RUN.model_copy(update={"run_id": "other"})}
        )
    with pytest.raises(ValueError, match="journal inputs are not bound"):
        Envelope.model_validate(
            {**envelope.model_dump(), "journal": (Input(input_id="CP-0", sha256="d" * 64),)}
        )
    assert envelope_issues("# anything\n", "{}")[0].startswith("Envelope sidecar is invalid")


_WORDS = st.sampled_from(["Liquidity", " is ", " tight", ", per the ", "notes", " and ", "cash"])
_TEXT = st.text(
    st.characters(blacklist_categories=("Cs",), blacklist_characters="\r"),
    min_size=1,
    max_size=24,
).filter(lambda value: not re.fullmatch(r"∅ G\d+( n\.m\.)?", value.strip()))
_AMOUNT = st.builds(
    lambda units, places: Decimal(units).scaleb(-places),
    st.integers(-(10**15), 10**15),
    st.integers(0, 6),
)
_CELL = st.one_of(
    st.tuples(st.just("amount"), _AMOUNT),
    st.tuples(st.just("text"), _TEXT),
    st.tuples(st.just("missing"), _TEXT),
    st.tuples(st.just("not_applicable"), _TEXT),
)


def _synthetic(kinds: list[tuple[str, object]], words: list[str]) -> Envelope:
    rows: list[list[Fact]] = []
    for index, (kind, value) in enumerate(kinds):
        row = f"r{index}"
        if kind == "amount":
            assert isinstance(value, Decimal)
            first = _amount("T4.1", row, "amount", value)
        elif kind == "text":
            first = _fact("T4.1", row, "amount", text=str(value))
        else:
            first = _fact("T4.1", row, "amount", status=kind, limitation=str(value))
        rows.append([first, _fact("T4.1", row, "note", text=f"row {index}")])
    references = [
        "{" + f.fact_id + "}" if f.amount is not None else "[" + f.fact_id + "]"
        for f in (row[0] for row in rows)
        if f.amount is not None or f.status != "known"
    ]
    text = "".join(w + (references[i] if i < len(references) else "") for i, w in enumerate(words))
    claims = (Claim(claim_id="c1", text=text, citations=()),) if text.strip() else ()
    return Envelope(
        run=RUN, module=small_module(rows, claims), registers_sha256="c" * 64, journal=()
    )


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(_CELL, min_size=1, max_size=6), st.lists(_WORDS, min_size=1, max_size=5))
def test_read_of_write_is_the_envelope(kinds: list[tuple[str, object]], words: list[str]) -> None:
    envelope = _synthetic(kinds, words)
    markdown, sidecar = write_envelope(envelope)
    assert read_envelope(markdown, sidecar) == envelope
    assert write_envelope(envelope) == (markdown, sidecar)


@pytest.fixture(scope="module")
def fixture_envelope(tmp_path_factory: pytest.TempPathFactory) -> tuple[Envelope, str, str]:
    store, attempt = staged(tmp_path_factory.mktemp("envelope"))
    envelope = register_envelope(cp1_registers(store, attempt.ticket_id))
    markdown, sidecar = write_envelope(envelope)
    return envelope, markdown, sidecar


def test_fixture_registers_round_trip_with_every_table_placed_once(
    fixture_envelope: tuple[Envelope, str, str], tmp_path: Path
) -> None:
    envelope, markdown, sidecar = fixture_envelope
    assert _h2(markdown) == [name for name, _ in SECTIONS]
    for table in envelope.module.tables:
        assert markdown.count(f"\n### {table.table_id} — ") == 1
    assert read_envelope(markdown, sidecar) == envelope
    assert write_envelope(envelope)[0] == markdown
    claim = envelope.module.claims[0]
    line = next(x for x in markdown.split("\n") if x.startswith(f"- {claim.claim_id}: "))
    assert "interface-fact:" not in line and "{" not in line  # resolved, never raw tokens
    (tmp_path / "envelope.md").write_text(markdown)


def test_fixture_tampering_with_a_statement_cell_is_detected(
    fixture_envelope: tuple[Envelope, str, str],
) -> None:
    _, markdown, sidecar = fixture_envelope
    section = markdown.index("### T4.4 — ")
    match = re.compile(r"\| (-?\d+)(\.\d+)? \|").search(markdown, section)
    assert match is not None
    digit = match.start(1) + len(match[1]) - 1
    changed = "1" if markdown[digit] != "1" else "2"
    tampered = markdown[:digit] + changed + markdown[digit + 1 :]
    issues = envelope_issues(tampered, sidecar)
    assert any(i.startswith("Normalized IS / T4.4") for i in issues)


def test_hostile_titles_and_text_cannot_open_sections_or_tables() -> None:
    envelope = small_envelope()
    module = envelope.module
    hostile = "Register\n\n## QA Status\n\n| forged | row |"
    tables = tuple(
        t.model_copy(update={"title": hostile}) if t.table_id == "T4.1" else t
        for t in module.tables
    )
    changed = envelope.model_copy(update={"module": module.model_copy(update={"tables": tables})})
    markdown, sidecar = write_envelope(changed)
    assert _h2(markdown) == [name for name, _ in SECTIONS]
    assert "| forged | row |" not in markdown
    assert read_envelope(markdown, sidecar) == changed
