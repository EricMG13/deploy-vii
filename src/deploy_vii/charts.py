"""Static SVG charts for the report view (decision 0004 section 7, design DS-05).

Pure Python and stdlib: a ``ChartSpec`` goes in, an SVG string comes out. Every data point is a
focusable ``<g tabindex="0">`` whose ``aria-label`` names the series, category, the display text
(Python-formatted upstream, checked against ``display.format_value`` by ``ChartSpec``) and the
provenance reference. Colour is never written here: elements carry token classes (``s1``..``s5``,
``paper``, ``ax``) that ``app.css`` maps to ``--rb-*`` variables. The table twin of a chart is the
spec's ``table_twin`` block, which the shell shows beside the chart.
"""

import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from decimal import Decimal

from deploy_vii.display import format_value
from deploy_vii.report_view import ChartMark, ChartSpec

_NS = "http://www.w3.org/2000/svg"
_CHART_ID = re.compile(r"[A-Za-z0-9_-]+")
_PROVENANCE_OF_PREFIX = {"C": "cited", "K": "calculated", "S": "synthetic", "G": "gap"}
_SERIES_CLASSES = 5


def _n(value: float) -> str:
    return f"{value:.2f}"


def _el(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    element = ET.SubElement(
        parent, tag, {name.replace("_", "-"): value for name, value in attrs.items()}
    )
    if text is not None:
        element.text = text
    return element


def _series_class(spec: ChartSpec, series: str) -> int:
    return spec.series.index(series) % _SERIES_CLASSES + 1


def _nice(maximum: float) -> float:
    if maximum <= 0:
        return 1.0
    power = 10.0 ** math.floor(math.log10(maximum))
    ratio = maximum / power
    step = (
        1 if ratio <= 1 else 2 if ratio <= 2 else 2.5 if ratio <= 2.5 else 5 if ratio <= 5 else 10
    )
    return step * power


def _bounds(values: list[float], headroom: float = 1.12) -> tuple[float, float]:
    high = _nice(max([*values, 0.0]) * headroom)
    low = -_nice(abs(min([*values, 0.0])) * headroom) if min(values) < 0 else 0.0
    return low, high


def _ticks(low: float, high: float, count: int) -> list[float]:
    step = _nice((high - low) / count)
    first = math.ceil(low / step - 1e-9)
    ticks = []
    value = first * step
    while value <= high + 1e-9:
        ticks.append(round(value, 6))
        value += step
    return ticks


def _provenance(mark: ChartMark) -> str:
    if mark.ref_id is None:
        return "no reference"
    kind = _PROVENANCE_OF_PREFIX.get(mark.ref_id[:1], "referenced")
    return f"{kind} {mark.ref_id}"


def _label(mark: ChartMark, extra: str = "") -> str:
    suffix = f", {extra}" if extra else ""
    return f"{mark.series}, {mark.label}: {mark.text}{suffix} ({_provenance(mark)})"


def _is_synthetic(mark: ChartMark) -> bool:
    return mark.ref_id is not None and mark.ref_id.startswith("S")


def _tick_text(spec: ChartSpec, value: float) -> str:
    return format_value(Decimal(repr(value)), spec.unit_class, "known")


_EDGE = 14.0
_DEBT_ROW = 17
_DEBT_TOP = 6


def _size(spec: ChartSpec) -> tuple[int, int]:
    if spec.kind == "waterfall":
        return 640, 200
    if spec.kind == "debt_stack":
        return 460, _DEBT_TOP + len(spec.marks) * _DEBT_ROW + 20
    return 320, 160


def _frame(width: int, height: int) -> ET.Element:
    return ET.Element(
        "svg",
        {
            "xmlns": _NS,
            "viewBox": f"0 0 {width} {height}",
            "width": str(width),
            "height": str(height),
            "class": "chart",
        },
    )


def _mark_group(
    parent: ET.Element,
    mark: ChartMark,
    label: str,
    cx: float,
    cy: float,
    shape: Callable[[ET.Element], None] | None,
) -> ET.Element:
    group = _el(parent, "g", tabindex="0", role="img", aria_label=label, data_role=mark.role)
    group.set("class", "mark")
    if mark.ref_id is not None:
        group.set("data-ref", mark.ref_id)
    _el(group, "title", label)
    if shape is not None:
        shape(group)
    _el(
        group,
        "rect",
        x=_n(cx - 12),
        y=_n(cy - 12),
        width="24",
        height="24",
        fill="none",
        pointer_events="all",
    )
    return group


def _marker(index: int, x: float, y: float, cls: int, hollow: bool) -> Callable[[ET.Element], None]:
    radius = 4

    def draw(group: ET.Element) -> None:
        css = f"pt k{cls}" + (" paper-fill" if hollow else f" f{cls}")
        if index % 3 == 1:
            _el(
                group, "rect", x=_n(x - radius), y=_n(y - radius), width="8", height="8", class_=css
            )
        elif index % 3 == 2:
            d = f"M{_n(x)} {_n(y - 5)}L{_n(x + 5)} {_n(y)}L{_n(x)} {_n(y + 5)}L{_n(x - 5)} {_n(y)}Z"
            _el(group, "path", d=d, class_=css)
        else:
            _el(group, "circle", cx=_n(x), cy=_n(y), r=str(radius), class_=css)

    return draw


def _fixup_class(root: ET.Element) -> None:
    """``class_`` keyword arguments become the ``class`` attribute (``class`` is reserved)."""
    for element in root.iter():
        if "class-" in element.attrib:
            element.set("class", element.attrib.pop("class-"))


def _categories(spec: ChartSpec) -> list[str]:
    seen: list[str] = []
    for mark in spec.marks:
        if mark.label not in seen:
            seen.append(mark.label)
    return seen


def _lookup(spec: ChartSpec) -> dict[tuple[str, str], ChartMark]:
    return {(mark.series, mark.label): mark for mark in spec.marks}


def _hatches(root: ET.Element, spec: ChartSpec, chart_id: str) -> None:
    if spec.kind == "waterfall":  # its stripes follow the step role, see _waterfall
        return
    classes = sorted({_series_class(spec, m.series) for m in spec.marks if _is_synthetic(m)})
    if not classes:
        return
    defs = _el(root, "defs")
    for cls in classes:
        pattern = _el(
            defs,
            "pattern",
            id=f"hatch-{chart_id}-s{cls}",
            width="6",
            height="6",
            patternUnits="userSpaceOnUse",
            patternTransform="rotate(45)",
        )
        _el(pattern, "rect", width="6", height="6", class_="paper")
        _el(pattern, "rect", width="2", height="6", class_=f"f{cls}")


def _fill(mark: ChartMark, cls: int, chart_id: str) -> dict[str, str]:
    if _is_synthetic(mark):
        return {"class_": f"bar k{cls}", "fill": f"url(#hatch-{chart_id}-s{cls})"}
    return {"class_": f"bar s{cls}"}


def _axis_y(
    root: ET.Element,
    spec: ChartSpec,
    ticks: list[float],
    y_of: Callable[[float], float],
    left: float,
    right: float,
) -> None:
    for tick in ticks:
        _el(
            root,
            "line",
            x1=_n(left),
            x2=_n(right),
            y1=_n(y_of(tick)),
            y2=_n(y_of(tick)),
            class_="grid zero" if tick == 0 else "grid",
        )
        _el(
            root,
            "text",
            _tick_text(spec, tick),
            x=_n(left - 6),
            y=_n(y_of(tick) + 4),
            text_anchor="end",
            class_="ax",
        )


def _na_slot(root: ET.Element, x: float, y: float) -> None:
    _el(root, "text", "n/a", x=_n(x), y=_n(y), text_anchor="middle", class_="ax na")


def _line(spec: ChartSpec, root: ET.Element) -> None:
    width, height = 320, 160
    left, right, top, bottom = 40.0, 48.0, 14.0, 26.0
    categories = _categories(spec)
    points = _lookup(spec)
    values = [float(m.value) for m in spec.marks if m.value is not None]
    low, high = _bounds(values, 1.15)
    ticks = _ticks(low, high, 3)
    span = width - left - right

    def x_of(i: int) -> float:
        inner = span - 2 * _EDGE  # keep end points clear of the axis labels
        return (
            left
            + _EDGE
            + (inner / 2 if len(categories) == 1 else i * inner / (len(categories) - 1))
        )

    def y_of(v: float) -> float:
        return top + (height - top - bottom) * (1 - (v - low) / (high - low))

    _axis_y(root, spec, ticks, y_of, left, width - right)
    for i, category in enumerate(categories):
        _el(
            root,
            "text",
            category,
            x=_n(x_of(i)),
            y=str(height - 8),
            text_anchor="middle",
            class_="ax",
        )
    for series in spec.series:
        cls = _series_class(spec, series)
        path, pen, last = "", False, None
        for i, category in enumerate(categories):
            mark = points.get((series, category))
            if mark is None or mark.value is None:
                pen = False
                continue
            y = y_of(float(mark.value))
            path += f"{'L' if pen else 'M'}{_n(x_of(i))} {_n(y)}"
            pen, last = True, (i, mark, y)
        if path:
            _el(root, "path", d=path, class_=f"ln k{cls}")
        if last is not None:
            i, mark, y = last
            _el(root, "text", mark.text, x=_n(x_of(i) + 9), y=_n(y + 4), class_=f"lb f{cls}")
    for si, series in enumerate(spec.series):
        cls = _series_class(spec, series)
        for i, category in enumerate(categories):
            mark = points.get((series, category))
            if mark is None:
                continue
            if mark.value is None:
                _na_slot(root, x_of(i), top + 2)
                _mark_group(root, mark, _label(mark), x_of(i), top + 2, None)
                continue
            y = y_of(float(mark.value))
            _mark_group(
                root,
                mark,
                _label(mark),
                x_of(i),
                y,
                _marker(si, x_of(i), y, cls, _is_synthetic(mark)),
            )


def _columns(spec: ChartSpec, root: ET.Element, chart_id: str, *, stacked: bool) -> None:
    width, height = 320, 160
    left, right, top, bottom = 40.0, 8.0, 18.0, 26.0
    categories = _categories(spec)
    points = _lookup(spec)

    def at(series: str, category: str) -> ChartMark | None:
        return points.get((series, category))

    def positive_total(category: str) -> float:
        found = (at(s, category) for s in spec.series)
        return sum(max(0.0, float(m.value)) for m in found if m is not None and m.value is not None)

    values = [float(m.value) for m in spec.marks if m.value is not None]
    if stacked:
        values = values + [positive_total(c) for c in categories]
    low, high = _bounds(values)
    ticks = _ticks(low, high, 3)
    group_width = (width - left - right) / len(categories)

    def y_of(v: float) -> float:
        return top + (height - top - bottom) * (1 - (v - low) / (high - low))

    _axis_y(root, spec, ticks, y_of, left, width - right)
    count = len(spec.series)
    bar_width = min(group_width * 0.56, 44.0) if stacked else min(group_width / (count + 1), 28.0)
    for ci, category in enumerate(categories):
        centre = left + group_width * (ci + 0.5)
        _el(
            root,
            "text",
            category,
            x=_n(centre),
            y=str(height - 8),
            text_anchor="middle",
            class_="ax",
        )
        up = down = 0.0
        for si, series in enumerate(spec.series):
            mark = at(series, category)
            if mark is None:
                continue
            cls = _series_class(spec, series)
            x = (
                centre - bar_width / 2
                if stacked
                else centre - count * bar_width / 2 + si * bar_width
            )
            if mark.value is None:
                _na_slot(root, x + bar_width / 2, y_of(0) - 6)
                _mark_group(root, mark, _label(mark), x + bar_width / 2, y_of(0) - 6, None)
                continue
            amount = float(mark.value)
            if stacked:
                start, end = (up, up + amount) if amount >= 0 else (down, down + amount)
                up, down = (up + amount, down) if amount >= 0 else (up, down + amount)
            else:
                start, end = 0.0, amount
            top_y, bottom_y = y_of(max(start, end)), y_of(min(start, end))

            def draw(
                group: ET.Element,
                m: ChartMark = mark,
                c: int = cls,
                x0: float = x,
                t: float = top_y,
                b: float = bottom_y,
            ) -> None:
                _el(
                    group,
                    "rect",
                    x=_n(x0),
                    y=_n(t),
                    width=_n(max(1.0, bar_width - (0 if stacked else 2))),
                    height=_n(max(1.0, b - t)),
                    **_fill(m, c, chart_id),
                )

            _mark_group(root, mark, _label(mark), x + bar_width / 2, (top_y + bottom_y) / 2, draw)
            if not stacked and bar_width >= 22:
                _el(
                    root,
                    "text",
                    mark.text,
                    x=_n(x + bar_width / 2),
                    y=_n(top_y - 4 if amount >= 0 else bottom_y + 11),
                    text_anchor="middle",
                    class_="lb small",
                )
        if stacked and down == 0 and up > 0:
            # Exact total of the stack, spelled by the display formatter like every other figure.
            found = (at(series, category) for series in spec.series)
            exact = sum(
                (m.value for m in found if m is not None and m.value is not None), Decimal(0)
            )
            total = format_value(exact, spec.unit_class, "known")
            _el(
                root,
                "text",
                total,
                x=_n(centre),
                y=_n(y_of(up) - 4),
                text_anchor="middle",
                class_="lb small",
            )


def _wrap(text: str, width: int = 14) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and len(f"{lines[-1]} {word}") <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines or [text]


def _step_kind(step: ChartMark) -> str:
    if step.role in {"total", "residual"}:
        return step.role
    return "down" if step.value is not None and step.value < 0 else "up"


def _waterfall(spec: ChartSpec, root: ET.Element, chart_id: str) -> None:
    width, height = 640, 200
    left, right, top = 44.0, 8.0, 18.0
    steps = list(spec.marks)
    bottom = 58.0 if (width - 52) / len(steps) < 56 else 40.0
    running = Decimal(0)
    spans: list[tuple[Decimal, Decimal]] = []
    for step in steps:
        if step.value is None:
            spans.append((running, running))
        elif step.role == "total":
            spans.append((Decimal(0), step.value))
            running = step.value
        else:
            spans.append((running, running + step.value))
            running += step.value
    flat = [float(v) for pair in spans for v in pair]
    low = min(0.0, *flat)
    high = _nice(max(flat) * 1.1)
    ticks = _ticks(low, high, 4)
    group_width = (width - left - right) / len(steps)
    bar_width = min(group_width * 0.64, 48.0)

    def y_of(v: float) -> float:
        return top + (height - top - bottom) * (1 - (v - low) / (high - low))

    _axis_y(root, spec, ticks, y_of, left, width - right)
    stripe_kinds = sorted(
        {_step_kind(step) for step in steps if _is_synthetic(step) and step.value is not None}
    )
    if stripe_kinds:
        defs = _el(root, "defs")
        for stripe in stripe_kinds:
            pattern = _el(
                defs,
                "pattern",
                id=f"hatch-{chart_id}-wf-{stripe}",
                width="6",
                height="6",
                patternUnits="userSpaceOnUse",
                patternTransform="rotate(45)",
            )
            _el(pattern, "rect", width="6", height="6", class_="paper")
            _el(pattern, "rect", width="2", height="6", class_=f"wf-{stripe}")
    for i, (step, (start, end)) in enumerate(zip(steps, spans, strict=True)):
        x = left + group_width * (i + 0.5) - bar_width / 2
        label = _label(
            step,
            "running total " + format_value(end, spec.unit_class, "known")
            if step.value is not None and step.role != "total"
            else "",
        )
        lines = _wrap(step.label)
        for k, part in enumerate(lines[:2]):
            _el(
                root,
                "text",
                part,
                x=_n(x + bar_width / 2),
                y=_n(height - bottom + 14 + k * 10),
                text_anchor="middle",
                class_="ax small",
            )
        if step.value is None:
            _na_slot(root, x + bar_width / 2, y_of(0) - 6)
            _mark_group(root, step, _label(step), x + bar_width / 2, y_of(0) - 6, None)
            continue
        top_y, bottom_y = y_of(float(max(start, end))), y_of(float(min(start, end)))
        kind = _step_kind(step)

        def draw(
            group: ET.Element,
            t: float = top_y,
            b: float = bottom_y,
            xx: float = x,
            m: ChartMark = step,
            k: str = kind,
        ) -> None:
            attrs = {"class_": f"bar wf-{k}"}
            if _is_synthetic(m):
                attrs = {"class_": f"bar wf-{k}-edge", "fill": f"url(#hatch-{chart_id}-wf-{k})"}
            _el(
                group,
                "rect",
                x=_n(xx),
                y=_n(t),
                width=_n(bar_width),
                height=_n(max(2.0, b - t)),
                **attrs,
            )

        _mark_group(root, step, label, x + bar_width / 2, (top_y + bottom_y) / 2, draw)
        _el(
            root,
            "text",
            step.text,
            x=_n(x + bar_width / 2),
            y=_n(top_y - 4),
            text_anchor="middle",
            class_="lb small",
        )
        if i < len(steps) - 1:
            level = y_of(float(end))
            _el(
                root,
                "line",
                x1=_n(x + bar_width),
                x2=_n(left + group_width * (i + 1.5) - bar_width / 2),
                y1=_n(level),
                y2=_n(level),
                class_="connector",
            )


def _debt_stack(spec: ChartSpec, root: ET.Element, chart_id: str) -> None:
    if spec.denominator is None:  # ChartSpec guarantees it; refuse rather than assume
        raise ValueError("A debt stack needs a denominator")
    width, height = _size(spec)
    row_height, pad_top = _DEBT_ROW, float(_DEBT_TOP)
    pad_left, pad_right = 140.0, 10.0
    rows = list(spec.marks)
    total = sum((m.value for m in rows if m.value is not None), Decimal(0))
    axis_max = max(1, math.ceil(total / spec.denominator))

    def x_of(multiple: Decimal) -> float:
        return pad_left + (width - pad_left - pad_right) * float(multiple) / axis_max

    for tick in range(1, axis_max + 1):
        _el(
            root,
            "line",
            x1=_n(x_of(Decimal(tick))),
            x2=_n(x_of(Decimal(tick))),
            y1=_n(pad_top),
            y2=str(height - 18),
            class_="grid",
        )
        _el(
            root,
            "text",
            format_value(Decimal(tick), "multiple", "known"),
            x=_n(x_of(Decimal(tick))),
            y=str(height - 4),
            text_anchor="middle",
            class_="ax",
        )
    cumulative = Decimal(0)
    for i, row in enumerate(rows):
        y = pad_top + i * row_height
        name = row.label if len(row.label) <= 24 else row.label[:23] + "…"
        _el(
            root,
            "text",
            name,
            x=_n(pad_left - 6),
            y=_n(y + 12),
            text_anchor="end",
            class_="ax small",
        )
        if row.value is None:
            _na_slot(root, pad_left + 20, y + 12)
            _mark_group(root, row, _label(row), pad_left + 20, y + row_height / 2, None)
            continue
        start = cumulative / spec.denominator
        cumulative += row.value
        end = cumulative / spec.denominator
        cls = _series_class(spec, row.series)
        label = _label(row, "cumulative " + format_value(end, "multiple", "known"))

        def draw(
            group: ET.Element,
            a: Decimal = start,
            b: Decimal = end,
            yy: float = y,
            r: ChartMark = row,
            c: int = cls,
        ) -> None:
            _el(
                group,
                "rect",
                x=_n(x_of(a)),
                y=_n(yy + 3),
                width=_n(max(1.5, x_of(b) - x_of(a))),
                height=str(row_height - 6),
                **_fill(r, c, chart_id),
            )

        _mark_group(root, row, label, (x_of(start) + x_of(end)) / 2, y + row_height / 2, draw)


def _na(spec: ChartSpec, title: str) -> ET.Element:
    width, height = 300, 120
    reason = spec.reason or ""
    shown = reason if len(reason) <= 60 else reason[:58] + "…"
    interactive = bool(spec.marks)
    root = _frame(width, height)
    root.set("role", "group" if interactive else "img")
    root.set("aria-label", f"{title}: not available. {reason}".rstrip())
    _el(
        root,
        "rect",
        x="0.5",
        y="0.5",
        width=str(width - 1),
        height=str(height - 1),
        class_="na-box",
    )
    _el(
        root,
        "text",
        "n/a",
        x=str(width // 2),
        y=str(height // 2 - 6),
        text_anchor="middle",
        class_="lb na big",
    )
    _el(
        root,
        "text",
        shown,
        x=str(width // 2),
        y=str(height // 2 + 12),
        text_anchor="middle",
        class_="ax small",
    )
    for i, mark in enumerate(spec.marks):
        x = width * (i + 1) / (len(spec.marks) + 1)
        _mark_group(root, mark, _label(mark), x, height - 14, None)
        _el(
            root,
            "text",
            mark.text,
            x=_n(x),
            y=str(height - 10),
            text_anchor="middle",
            class_="ax small",
        )
    return root


def render_svg(spec: ChartSpec, *, chart_id: str, title: str) -> str:
    """The chart as an SVG string; ``chart_id`` keeps pattern ids unique within a page."""
    if not _CHART_ID.fullmatch(chart_id):
        raise ValueError("A chart id uses letters, digits, underscore and hyphen only")
    if spec.kind == "na" or not any(mark.value is not None for mark in spec.marks):
        root = _na(spec, title)
    else:
        root = _frame(*_size(spec))
        root.set("role", "group")
        root.set("aria-label", title)
        _hatches(root, spec, chart_id)
        if spec.kind == "line":
            _line(spec, root)
        elif spec.kind in {"grouped", "stacked"}:
            _columns(spec, root, chart_id, stacked=spec.kind == "stacked")
        elif spec.kind == "waterfall":
            _waterfall(spec, root, chart_id)
        else:
            _debt_stack(spec, root, chart_id)
    _fixup_class(root)
    svg = ET.tostring(root, encoding="unicode")
    try:
        ET.fromstring(svg)
    except ET.ParseError as error:  # e.g. a control character XML 1.0 cannot carry
        raise ValueError(f"Chart text cannot be written as SVG: {error}") from error
    return svg
