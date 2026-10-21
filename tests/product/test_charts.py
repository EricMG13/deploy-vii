"""Static SVG charts: well-formed, one focusable mark per data point, table-twin parity."""

import re
import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.charts import render_svg
from deploy_vii.display import format_value
from deploy_vii.report_view import Block, Cell, ChartKind, ChartMark, ChartSpec, Row

SVG = "{http://www.w3.org/2000/svg}"
CATEGORIES = ("FY2024", "FY2025", "LTM")


def mark(
    series: str,
    label: str,
    value: str | None,
    ref: str | None = "C1",
    *,
    unit_class: str = "amount",
    role: str = "value",
) -> ChartMark:
    amount = Decimal(value) if value is not None else None
    text = (
        format_value(amount, unit_class, "known")  # type: ignore[arg-type]
        if amount is not None
        else f"∅ {ref}"
    )
    return ChartMark(
        series=series,
        label=label,
        text=text,
        ref_id=ref,
        value=amount,
        role=role,  # type: ignore[arg-type]
    )


PROV = {"C": "cited", "K": "calculated", "S": "synthetic"}


def twin_for(marks: tuple[ChartMark, ...]) -> Block:
    if not marks:
        return Block(
            block_id="twin",
            title="Table twin",
            owner="CP-1",
            state="absent",
            kind="dense",
            note="No rows: nothing to chart.",
        )
    rows = tuple(
        Row(
            row_id=f"r{index}",
            label=f"{item.series} {item.label}",
            cells=(
                Cell(
                    text=item.text,
                    prov="gap" if item.value is None else PROV[(item.ref_id or "C")[0]],
                    ref_id=None if item.value is None else item.ref_id,
                    gap_ref=item.ref_id if item.value is None else None,
                    unit_class="amount",
                    state="gap" if item.value is None else "known",
                ),
            ),
        )
        for index, item in enumerate(marks)
    )
    return Block(
        block_id="twin",
        title="Table twin",
        owner="CP-1",
        state="populated",
        kind="dense",
        columns=("Value",),
        rows=rows,
    )


def spec(
    kind: ChartKind,
    marks: tuple[ChartMark, ...],
    series: tuple[str, ...],
    **extra: object,
) -> ChartSpec:
    return ChartSpec(
        kind=kind,
        series=series,
        table_twin=twin_for(marks),
        marks=marks,
        **extra,  # type: ignore[arg-type]
    )


def series_marks(series: tuple[str, ...], rows: dict[str, tuple[str | None, ...]]) -> tuple:
    return tuple(
        mark(name, category, value, f"C{1 + index}")
        for index, name in enumerate(series)
        for category, value in zip(CATEGORIES, rows[name], strict=True)
    )


def cases() -> dict[str, ChartSpec]:
    two = ("Total", "Net")
    values = {"Total": ("120", "135", "150"), "Net": ("80", "90", "95")}
    line_marks = series_marks(two, values)
    waterfall = (
        mark("Bridge", "Opening", "100", "C1", role="total"),
        mark("Bridge", "Inflow", "40", "K1"),
        mark("Bridge", "Outflow", "-25", "K2"),
        mark("Bridge", "Residual", "-3", "K3", role="residual"),
        mark("Bridge", "Closing", "112", "C2", role="total"),
    )
    debt = (
        mark("secured", "Revolver", "120", "C1"),
        mark("secured", "Term loan A", "619", "C2"),
        mark("unsecured", "Notes 2032", "1500", "C3"),
    )
    return {
        "line": spec("line", line_marks, two),
        "grouped": spec("grouped", line_marks, two),
        "stacked": spec("stacked", line_marks, two),
        "waterfall": spec("waterfall", waterfall, ("Bridge",)),
        "debt_stack": spec(
            "debt_stack", debt, ("secured", "unsecured"), denominator=Decimal("1000")
        ),
    }


def parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def mark_groups(root: ET.Element) -> list[ET.Element]:
    return [group for group in root.iter(f"{SVG}g") if group.get("tabindex") == "0"]


@pytest.mark.parametrize("kind", ["line", "grouped", "stacked", "waterfall", "debt_stack"])
def test_every_kind_renders_well_formed_svg_with_one_mark_per_point(kind: str) -> None:
    chart = cases()[kind]
    root = parse(render_svg(chart, chart_id="b1", title="Chart"))
    assert root.tag == f"{SVG}svg"
    assert root.get("viewBox")
    assert len(mark_groups(root)) == len(chart.marks)


@pytest.mark.parametrize("kind", ["line", "grouped", "stacked", "waterfall", "debt_stack"])
def test_chart_table_twin_parity(kind: str) -> None:
    chart = cases()[kind]
    root = parse(render_svg(chart, chart_id="b1", title="Chart"))
    labels = [group.get("aria-label", "") for group in mark_groups(root)]
    twin_cells = [cell for row in chart.table_twin.rows for cell in row.cells]
    assert len(labels) == len(twin_cells) == len(chart.marks)
    for item, twin in zip(chart.marks, twin_cells, strict=True):
        assert twin.text == item.text
        assert item.ref_id is not None
        prefix = f"{item.series}, {item.label}: {item.text}"
        matching = [label for label in labels if label.startswith(prefix)]
        assert len(matching) == 1 and item.ref_id in matching[0]


def test_marks_name_their_provenance_and_carry_the_reference() -> None:
    root = parse(render_svg(cases()["grouped"], chart_id="b1", title="Chart"))
    first = mark_groups(root)[0]
    assert first.get("role") == "img"
    assert "cited C1" in (first.get("aria-label") or "")
    assert first.get("data-ref") == "C1"
    assert first.find(f"{SVG}title") is not None


def test_colours_come_only_from_token_classes() -> None:
    for chart in cases().values():
        svg = render_svg(chart, chart_id="b1", title="Chart")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", svg)
        assert " style=" not in svg
        for tag in ET.fromstring(svg).iter():
            assert tag.get("fill") in {None, "none"} or str(tag.get("fill")).startswith("url(#")
            assert tag.get("stroke") in {None, "none"}


def test_no_data_is_the_na_frame_with_its_reason() -> None:
    chart = spec("line", (), ("Total",), reason="No rating-agency report in the Source Pack")
    root = parse(render_svg(chart, chart_id="b1", title="Rating triggers"))
    assert root.get("role") == "img"
    label = root.get("aria-label") or ""
    assert "Rating triggers" in label and "not available" in label
    assert "No rating-agency report" in label
    assert not mark_groups(root)
    assert "n/a" in "".join(root.itertext())


def test_all_gap_chart_is_the_na_frame_and_keeps_its_marks_focusable() -> None:
    gaps = tuple(mark("Total", category, None, "G15") for category in CATEGORIES)
    chart = spec("line", gaps, ("Total",), reason="Not extracted")
    root = parse(render_svg(chart, chart_id="b1", title="Leverage"))
    assert "not available" in (root.get("aria-label") or "")
    assert len(mark_groups(root)) == len(gaps)


def test_a_gap_in_a_series_prints_na_and_stays_a_focusable_mark() -> None:
    marks = (
        mark("Total", "FY2024", None, "G15"),
        mark("Total", "FY2025", "135", "C2"),
        mark("Total", "LTM", "150", "C3"),
    )
    chart = spec("line", marks, ("Total",))
    root = parse(render_svg(chart, chart_id="b1", title="Leverage"))
    groups = mark_groups(root)
    assert len(groups) == 3
    assert "∅ G15" in (groups[0].get("aria-label") or "")
    assert "gap G15" in (groups[0].get("aria-label") or "")
    assert "n/a" in "".join(root.itertext())


def test_hostile_text_is_escaped_not_interpreted() -> None:
    hostile = "</svg><script>window.injected=true</script>&"
    marks = (mark(hostile, "FY2024", "10", "C1"), mark(hostile, "FY2025", "12", "C2"))
    chart = spec("grouped", marks, (hostile,))
    svg = render_svg(chart, chart_id="b1", title=hostile)
    assert "<script" not in svg
    root = parse(svg)
    assert any(hostile in (g.get("aria-label") or "") for g in mark_groups(root))


def test_debt_stack_names_cumulative_multiples() -> None:
    chart = cases()["debt_stack"]
    labels = [
        g.get("aria-label") or ""
        for g in mark_groups(parse(render_svg(chart, chart_id="b", title="t")))
    ]
    cumulative = [Decimal("120"), Decimal("739"), Decimal("2239")]
    for label, total in zip(labels, cumulative, strict=True):
        assert f"cumulative {format_value(total / Decimal(1000), 'multiple', 'known')}" in label


def test_waterfall_marks_residual_and_total_roles() -> None:
    root = parse(render_svg(cases()["waterfall"], chart_id="b", title="t"))
    roles = [g.get("data-role") for g in mark_groups(root)]
    assert roles == ["total", "value", "value", "residual", "total"]


def test_the_debt_stack_needs_a_denominator() -> None:
    marks = (mark("secured", "Revolver", "120", "C1"),)
    with pytest.raises(ValueError, match="denominator"):
        spec("debt_stack", marks, ("secured",))


def test_a_mark_text_must_equal_the_formatted_value() -> None:
    bad = (ChartMark(series="s", label="FY", text="999", ref_id="C1", value=Decimal(1)),)
    with pytest.raises(ValueError, match="formatted"):
        ChartSpec(kind="line", series=("s",), table_twin=twin_for(bad), marks=bad)


def pattern_ids(svg: str) -> set[str | None]:
    return {e.get("id") for e in ET.fromstring(svg).iter() if e.get("id")}


def test_two_charts_on_one_page_do_not_share_pattern_ids() -> None:
    synthetic = tuple(
        mark("Total", category, value, f"S{index + 1}")
        for index, (category, value) in enumerate(zip(CATEGORIES, ("1", "2", "3"), strict=True))
    )
    chart = spec("grouped", synthetic, ("Total",))
    first = render_svg(chart, chart_id="b1", title="t")
    second = render_svg(chart, chart_id="b2", title="t")
    assert pattern_ids(first) and not pattern_ids(first) & pattern_ids(second)
    assert "url(#hatch-b1" in first


@settings(deadline=None, max_examples=60)
@given(
    st.lists(st.decimals(min_value=-10_000, max_value=10_000, places=2), min_size=1, max_size=8),
    st.sampled_from(["line", "grouped", "stacked"]),
)
def test_any_values_render_one_mark_each(values: list[Decimal], kind: str) -> None:
    marks = tuple(mark("Total", f"P{i}", str(v), f"C{i + 1}") for i, v in enumerate(values))
    chart = spec(kind, marks, ("Total",))  # type: ignore[arg-type]
    root = parse(render_svg(chart, chart_id="b", title="t"))
    assert len(mark_groups(root)) == len(values)


def test_text_xml_cannot_carry_fails_closed_instead_of_drawing_nothing() -> None:
    bad = "name\x00"
    marks = (mark(bad, "FY2024", "10", "C1"), mark(bad, "FY2025", "12", "C2"))
    with pytest.raises(ValueError, match="cannot be written as SVG"):
        render_svg(spec("grouped", marks, (bad,)), chart_id="b", title="t")


def test_a_chart_id_is_restricted_so_pattern_urls_stay_well_formed() -> None:
    with pytest.raises(ValueError, match="chart id"):
        render_svg(cases()["line"], chart_id="a b)", title="t")


def test_every_kind_has_a_hatched_synthetic_mark() -> None:
    for kind, chart in cases().items():
        synthetic = tuple(
            mark(m.series, m.label, str(m.value), f"S{i + 1}", role=m.role)
            for i, m in enumerate(chart.marks)
        )
        hatched = spec(kind, synthetic, chart.series, denominator=chart.denominator)  # type: ignore[arg-type]
        svg = render_svg(hatched, chart_id="h", title="t")
        if kind == "line":  # synthetic points are hollow markers, not hatched fills
            assert "paper-fill" in svg
        else:
            assert "url(#hatch-h" in svg and "<pattern" in svg


def test_stacked_columns_print_an_exact_total() -> None:
    chart = cases()["stacked"]
    texts = "".join(parse(render_svg(chart, chart_id="b", title="t")).itertext())
    assert format_value(Decimal("200"), "amount", "known") in texts  # 120 + 80
    assert format_value(Decimal("245"), "amount", "known") in texts  # 150 + 95


def test_every_url_reference_resolves_to_an_id_in_the_same_svg() -> None:
    steps = (
        ("Open", "100", "total"),
        ("In", "40", "value"),
        ("Out", "-25", "value"),
        ("Resid", "-3", "residual"),
        ("Close", "112", "total"),
    )
    bridge = tuple(
        mark("Bridge", label, value, f"S{i + 1}", role=role)
        for i, (label, value, role) in enumerate(steps)
    )
    variants = {**cases(), "waterfall-synthetic": spec("waterfall", bridge, ("Bridge",))}
    for kind, chart in variants.items():
        synthetic = tuple(
            mark(m.series, m.label, str(m.value), f"S{i + 1}", role=m.role)
            for i, m in enumerate(chart.marks)
        )
        for marks in (chart.marks, synthetic):
            built = spec(chart.kind, marks, chart.series, denominator=chart.denominator)  # type: ignore[arg-type]
            svg = render_svg(built, chart_id="u", title="t")
            ids = {e.get("id") for e in ET.fromstring(svg).iter() if e.get("id")}
            refs = set(re.findall(r"url\(#([^)]+)\)", svg))
            assert refs <= ids, (kind, refs - ids)
            if marks is synthetic and kind != "line":
                assert refs, kind
