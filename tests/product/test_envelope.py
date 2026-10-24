"""Canonical CP-1 envelope: r14 order, lossless cells, resolved prose, round trip, tampering."""

import hashlib
import re
import tracemalloc
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import deploy_vii.envelope as envelope_writer
from deploy_vii.canonical_tables import COLUMNS, CanonicalTables
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
from deploy_vii.cp1_quality import cp1_quality_inputs
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
from deploy_vii.financial_contracts import FinancialBook, SegmentAllocation, SegmentObservation
from deploy_vii.model_interface import SCHEMAS as INTERFACE_SCHEMAS
from deploy_vii.narrative_projection import SCHEMAS as NARRATIVE_SCHEMAS
from deploy_vii.table_markdown import read_table_markdown
from tests.product.test_cp1_workflow import staged
from tests.product.test_financials import _C, observed
from tests.product.test_model_readiness import ready_case

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


# Task 7.12: tracemalloc peaks (the Python heap) measured when adopted, plus 25 % headroom.
WRITE_PEAK_BOUND = 478_000_000  # 382.2 MB measured (416.9 MB before)
REGISTER_PEAK_BOUND = 79_000_000  # 63.3 MB measured (293.8 MB before task 7.12)


def _traced_peak[A, T](call: Callable[[A], T], argument: A) -> tuple[T, int]:
    """The call's result and its tracemalloc peak above what was traced when it began. An
    outside tracer (``PYTHONTRACEMALLOC``) is measured from ``reset_peak()`` and left running
    (task 7.15); otherwise tracing starts and stops around the call."""
    outside = tracemalloc.is_tracing()
    if not outside:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        before = tracemalloc.get_traced_memory()[0]
        result = call(argument)
        return result, tracemalloc.get_traced_memory()[1] - before
    finally:
        if not outside:
            tracemalloc.stop()


def test_the_traced_peak_neither_counts_nor_ends_an_outside_tracer() -> None:
    """Task 7.15 (7.12 review): under an outside tracer (``PYTHONTRACEMALLOC``) the helper
    measures from ``reset_peak()`` and leaves the tracer running, so what was traced before
    the call is not in the peak."""
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    try:
        held = bytearray(20_000_000)
        size, peak = _traced_peak(lambda n: len(bytearray(n)), 2_000_000)
        assert size == 2_000_000 and 2_000_000 <= peak < 10_000_000, peak
        assert tracemalloc.is_tracing()
        del held
    finally:
        if not was_tracing:
            tracemalloc.stop()


def test_the_synthetic_case_hashes_its_json_bytes_within_its_memory_bounds(
    fixture_envelope: tuple[Envelope, str, str], tmp_path: Path
) -> None:
    """The writer hashes ``__pydantic_serializer__.to_json()`` bytes and re-validates from them
    (task 7.12). Those are the bytes ``content_hash()`` encodes back from ``model_dump_json()``,
    which is ``to_json().decode()`` with the same defaults in pydantic 2.14.1 / pydantic-core
    2.50.1 (read when adopted); a dependency bump that changes either fails here and in
    ``test_replay``, never silently in a provenance hash.

    The bounds are tracemalloc peaks, deterministic for one interpreter. ``ru_maxrss`` would be
    vacuous here: it is the process's high-water mark, already reached when this module's
    fixture wrote the same envelope.
    """
    envelope, markdown, sidecar = fixture_envelope
    store, attempt = staged(tmp_path)
    registers = cp1_registers(store, attempt.ticket_id)
    for model in (registers, envelope, envelope.module):
        assert envelope_writer._content_hash(model) == model.content_hash()
    rebuilt, register_peak = _traced_peak(register_envelope, registers)
    assert rebuilt == envelope
    del registers, rebuilt
    written, write_peak = _traced_peak(write_envelope, envelope)
    assert written == (markdown, sidecar)
    assert register_peak < REGISTER_PEAK_BOUND, register_peak
    assert write_peak < WRITE_PEAK_BOUND, write_peak


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


def test_qa_text_that_looks_like_a_gap_marker_is_not_a_marker() -> None:
    from deploy_vii.quality import (
        CoverageField,
        EvidenceCeiling,
        QaFinding,
        QualityInputs,
        QualityReview,
        assess_quality,
    )

    inputs = QualityInputs(
        artifact_sha256="c" * 64,
        coverage_policy="synthetic",
        claims=(),
        coverage=(CoverageField(field_id="slot", present=True, rationale="Synthetic slot"),),
        source_gate="pass",
        module_status="complete",
        references=("ref",),
        ceilings=(EvidenceCeiling.of("ref", "gap"),),
    )
    finding = QaFinding(finding_id="minor", severity="MINOR", description="∅ G999")
    review = QualityReview(inputs_sha256=inputs.content_hash(), claims=(), findings=(finding,))
    envelope = small_envelope().model_copy(update={"quality": assess_quality(inputs, review)})
    markdown, sidecar = write_envelope(envelope)
    assert "| minor | MINOR | open | ∅ G999 |" in markdown
    assert read_envelope(markdown, sidecar) == envelope


def segmented_book() -> FinancialBook:
    """`ready_case` with one operating segment carrying each period's revenue and its slot."""
    value = ready_case()
    revenue = {r.period_id: r.value.amount for r in value.accounts if r.metric_id == "revenue"}
    segments = tuple(
        SegmentObservation(
            segment_id="gaming",
            segment_name="Gaming",
            segment_type="OPERATING_SEGMENT",
            display_priority=1,
            period_id=period_id,
            revenue=observed(f"segment.{period_id}", str(amount)),
            classification_citations=(_C,),
        )
        for period_id, amount in revenue.items()
    )
    allocation = SegmentAllocation(
        slot_id="DIVISION_1",
        slot_label="Gaming",
        component_segment_ids=("gaming",),
        rationale="Synthetic single-segment forecast mapping",
    )
    return FinancialBook.model_validate(
        {
            **value.model_dump(),
            "segments": segments,
            "segment_allocation": (allocation,),
            "segment_disclosure": value.segment_disclosure.model_copy(update={"status": "partial"}),
        }
    )


@pytest.fixture(scope="module")
def segmented_registers(tmp_path_factory: pytest.TempPathFactory) -> CanonicalTables:
    store, attempt = staged(tmp_path_factory.mktemp("segmented"), book=segmented_book())
    return cp1_registers(store, attempt.ticket_id)


def test_a_segmented_book_places_its_segment_allocation_in_module_handoff(
    segmented_registers: CanonicalTables,
) -> None:
    # Task 7.7 (e1-cp1-7): before the placement, write_envelope raised
    # "No r14 envelope section for table: segment-allocation" for every segmented issuer.
    envelope = register_envelope(segmented_registers)
    table = next(t for t in envelope.module.tables if t.table_id == "segment-allocation")
    assert table.interface_id == "cp1.cp_model_segment_allocation" and len(table.rows) == 1
    markdown, sidecar = write_envelope(envelope)
    assert envelope_issues(markdown, sidecar) == ()
    handoff = markdown[markdown.index("\n## Module Handoff\n") :]
    assert handoff.count("\n### segment-allocation — Model Segment Allocation\n") == 1
    slot = next(
        f
        for f in cp1_quality_inputs(segmented_registers).coverage
        if f.field_id == "canonical-handoff"
    )
    assert slot.present, slot.rationale


def test_every_table_the_cp1_module_can_carry_has_exactly_one_section(
    fixture_envelope: tuple[Envelope, str, str], segmented_registers: CanonicalTables
) -> None:
    # Derived from the producers: the register, model-interface and narrative schemas (the
    # conditional segment-allocation included) and the tables both fixtures emit (the
    # statement tables T4.4-T4.6 have no exported schema).
    placed = [table_id for _, ids in SECTIONS for table_id in ids]
    assert len(placed) == len(set(placed))
    carried = {
        *COLUMNS,
        *INTERFACE_SCHEMAS,
        *NARRATIVE_SCHEMAS,
        *(t.table_id for t in fixture_envelope[0].module.tables),
        *(t.table_id for t in segmented_registers.module.tables),
    }
    assert carried == set(placed)
    handoff = dict(SECTIONS)["Module Handoff"]
    assert tuple(key for key in INTERFACE_SCHEMAS if key in handoff) == handoff


def test_an_unsegmented_envelope_gains_only_the_segment_allocation_line(
    fixture_envelope: tuple[Envelope, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope, markdown, sidecar = fixture_envelope
    assert all(t.table_id != "segment-allocation" for t in envelope.module.tables)
    before = tuple(
        (name, tuple(i for i in ids if i != "segment-allocation")) for name, ids in SECTIONS
    )
    monkeypatch.setattr(envelope_writer, "SECTIONS", before)
    prior_markdown, prior_sidecar = write_envelope(envelope)
    assert prior_sidecar == sidecar
    line = "### segment-allocation\n\nNot produced: segment-allocation is not in this module.\n\n"
    anchor = "### operating-kpis — "
    assert prior_markdown.count(anchor) == 1
    assert markdown == prior_markdown.replace(anchor, line + anchor)
