"""SYNTHETIC Credit Snapshot fixture: invented figures, labelled, never an issuer's facts.

``credit_snapshot_view`` is a candidate View whose modules carry typed registers in the shapes
the shipped binding maps name (CP-1 T4.4, T4.10, T4.17, T4.18; CP-1A composed by Python from
the synthetic business-context submission) plus synthetic maps for the producers that have no
shipped map yet (CP-2, CP-3, CP-6). ``credit_snapshot_fixture``
runs ``report_view.build`` over them and adds what no producer supplies yet, each marked here:
the S.1 to S.5 and debt-stack charts (their marks are read from the registers' own facts, so
every mark resolves to a passport) and the "condition" state of the last block.
"""

from decimal import Decimal
from typing import Literal

from deploy_vii.bindings import Binding, BindingMap
from deploy_vii.bindings.cp1 import CP1
from deploy_vii.bindings.cp1a import CP1A
from deploy_vii.business_context import business_context
from deploy_vii.contracts import (
    Citation,
    Fact,
    ModuleView,
    ReportTable,
    TableColumn,
    TableRow,
    View,
)
from deploy_vii.display import UnitClass, format_value
from deploy_vii.report_view import (
    Block,
    CallItem,
    ChartMark,
    ChartSpec,
    FactCoord,
    Figure,
    Pathway,
    ReportView,
    Section,
    build,
    gap_refs,
    pathways,
)
from tests.product.test_business_context import pack_fixture, submission_fixture
from tests.product.test_charts import twin_for
from tests.product.test_render import synthetic_view

CITE = Citation(
    source_id="synthetic-fixture",
    source_sha256="c" * 64,
    locator="fixture:1",
    quote="Synthetic test data",
)
Row = tuple[str, str, tuple[Fact, ...]]
RowKind = Literal["row", "subtotal", "total", "memo"]


def fact(
    table: str,
    row: str,
    field: str,
    *,
    amount: str | None = None,
    unit: str | None = None,
    text: str | None = None,
    missing: str | None = None,
    calc: str | None = None,
    judgment: bool = False,
    period: str | None = None,
    label: str | None = None,
    inapplicable: str | None = None,
) -> Fact:
    unsettled = missing or inapplicable
    return Fact(
        fact_id=f"{table}.{row}.{field}",
        label=label or f"{row} {field}",
        table_id=table,
        row_id=row,
        field=field,
        amount=None if amount is None else Decimal(amount),
        unit=unit,
        currency="USD" if unit in {"MILLIONS", "THOUSANDS", "UNITS"} else None,
        text=text,
        status="missing" if missing else "not_applicable" if inapplicable else "known",
        limitation=unsettled,
        period=(period or field) if amount is not None else None,
        citations=() if unsettled else (CITE,),
        calculation_id=calc,
        formula="synthetic calculation" if calc else None,
        calculation_status="calculated" if calc else None,
        value_class="analyst_judgment" if judgment else None,
    )


def layout(
    table_id: str,
    title: str,
    columns: tuple[str, ...],
    rows: tuple[Row, ...],
    *,
    row_header: str = "Item",
    kinds: dict[str, RowKind] | None = None,
) -> tuple[ReportTable, tuple[Fact, ...]]:
    """A declared table; a column is ``field`` or ``field=Label`` (fields are identifiers)."""
    pairs = [(c.split("=")[0], c.split("=")[-1]) for c in columns]
    return (
        ReportTable(
            table_id=table_id,
            title=title,
            columns=tuple(TableColumn(field=field, label=label) for field, label in pairs),
            rows=tuple(
                TableRow(
                    row_id=row_id,
                    label=label,
                    fact_ids=tuple(f.fact_id for f in facts),
                    row_kind=(kinds or {}).get(row_id, "row"),
                )
                for row_id, label, facts in rows
            ),
            row_header=row_header,
        ),
        tuple(item for _, _, facts in rows for item in facts),
    )


def _cp1() -> tuple[tuple[ReportTable, ...], tuple[Fact, ...]]:
    periods = ("FY2024", "FY2025", "LTM", "PF-LTM")
    kpis = layout(
        "T4.10",
        "KPI Dashboard",
        periods[:3],
        (
            (
                "total_leverage",
                "Total leverage",
                (
                    fact(
                        "T4.10",
                        "total_leverage",
                        "FY2024",
                        unit="MULTIPLE",
                        missing="not extracted",
                    ),
                    fact(
                        "T4.10",
                        "total_leverage",
                        "FY2025",
                        amount="3.5",
                        unit="MULTIPLE",
                        calc="k1",
                    ),
                    fact(
                        "T4.10", "total_leverage", "LTM", amount="3.29", unit="MULTIPLE", calc="k2"
                    ),
                ),
            ),
            (
                "net_leverage",
                "Net leverage",
                (
                    fact(
                        "T4.10", "net_leverage", "FY2024", amount="3.1", unit="MULTIPLE", calc="k3"
                    ),
                    fact(
                        "T4.10", "net_leverage", "FY2025", amount="2.9", unit="MULTIPLE", calc="k4"
                    ),
                    fact("T4.10", "net_leverage", "LTM", amount="2.64", unit="MULTIPLE", calc="k5"),
                ),
            ),
            (
                "interest_cover",
                "Interest cover",
                (
                    fact(
                        "T4.10",
                        "interest_cover",
                        "FY2024",
                        amount="2.1",
                        unit="MULTIPLE",
                        calc="k6",
                    ),
                    fact(
                        "T4.10",
                        "interest_cover",
                        "FY2025",
                        amount="2.4",
                        unit="MULTIPLE",
                        calc="k7",
                    ),
                    fact(
                        "T4.10", "interest_cover", "LTM", amount="2.6", unit="MULTIPLE", calc="k8"
                    ),
                ),
            ),
            (
                "liquidity",
                "Liquidity",
                (
                    fact("T4.10", "liquidity", "FY2024", amount="900", unit="MILLIONS"),
                    fact("T4.10", "liquidity", "FY2025", amount="1100", unit="MILLIONS"),
                    fact("T4.10", "liquidity", "LTM", amount="1250", unit="MILLIONS"),
                ),
            ),
        ),
    )
    bridge = layout(
        "T4.17",
        "Adjusted EBITDA Bridge",
        ("FY2025", "LTM"),
        (
            (
                "reported",
                "Reported EBITDA",
                (
                    fact("T4.17", "reported", "FY2025", amount="3300", unit="MILLIONS"),
                    fact("T4.17", "reported", "LTM", amount="3420", unit="MILLIONS"),
                ),
            ),
            (
                "addbacks",
                "Add-backs",
                (
                    fact("T4.17", "addbacks", "FY2025", amount="150", unit="MILLIONS"),
                    fact("T4.17", "addbacks", "LTM", amount="172", unit="MILLIONS"),
                ),
            ),
            (
                "adjusted",
                "Adjusted EBITDA",
                (
                    fact("T4.17", "adjusted", "FY2025", amount="3450", unit="MILLIONS", calc="k9"),
                    fact("T4.17", "adjusted", "LTM", amount="3592", unit="MILLIONS", calc="k10"),
                ),
            ),
        ),
    )

    def facility(
        row: str, outstanding: str | None, mult: str | None, coupon: Fact, maturity: Fact, pct: str
    ) -> tuple[Fact, ...]:
        gone = "balance not extracted"
        return (
            coupon,
            maturity,
            fact(
                "T4.18",
                row,
                "outstanding",
                amount=outstanding,
                unit="MILLIONS",
                missing=None if outstanding else gone,
                period="LTM",
            ),
            fact(
                "T4.18",
                row,
                "x_ebitda",
                amount=mult,
                unit="MULTIPLE",
                missing=None if mult else gone,
                calc="k-" + row if mult else None,
            ),
            fact("T4.18", row, "pct_ev", amount=pct, unit="PERCENT", calc="p-" + row)
            if pct
            else fact("T4.18", row, "pct_ev", unit="PERCENT", missing=gone),
            fact("T4.18", row, "rec", unit="text", missing="CP-4C has not run"),
        )

    def subtotal(
        row: str, outstanding: str | None, mult: str | None, pct: str | None
    ) -> tuple[Fact, ...]:
        why = "a subtotal has no coupon, maturity or recovery"
        return (
            fact("T4.18", row, "coupon", inapplicable=why),
            fact("T4.18", row, "maturity", inapplicable=why),
            fact(
                "T4.18",
                row,
                "outstanding",
                amount=outstanding,
                unit="MILLIONS",
                missing=None if outstanding else "a facility balance is not extracted",
                period="LTM",
                calc="s-" + row if outstanding else None,
            ),
            fact(
                "T4.18",
                row,
                "x_ebitda",
                amount=mult,
                unit="MULTIPLE",
                missing=None if mult else "a facility balance is not extracted",
                calc="sm-" + row if mult else None,
            ),
            fact(
                "T4.18",
                row,
                "pct_ev",
                amount=pct,
                unit="PERCENT",
                missing=None if pct else "a facility balance is not extracted",
                calc="sp-" + row if pct else None,
            ),
            fact("T4.18", row, "rec", inapplicable=why),
        )

    debt = layout(
        "T4.18",
        "Debt Facility Register",
        (
            "coupon=Coupon",
            "maturity=Maturity",
            "outstanding=Outstanding",
            "x_ebitda=x EBITDA",
            "pct_ev=% EV",
            "rec=Rec.",
        ),
        (
            (
                "revolver",
                "Revolver",
                facility(
                    "revolver",
                    "120",
                    "0.03",
                    fact("T4.18", "revolver", "coupon", amount="250", unit="basis_points"),
                    fact("T4.18", "revolver", "maturity", text="2028-03-31"),
                    "0.0245",
                ),
            ),
            (
                "tla",
                "Term loan A",
                facility(
                    "tla",
                    None,
                    None,
                    fact("T4.18", "tla", "coupon", amount="275", unit="basis_points"),
                    fact("T4.18", "tla", "maturity", text="2029-06-30"),
                    "",
                ),
            ),
            (
                "notes",
                "Senior notes 2030",
                facility(
                    "notes",
                    "1500",
                    "0.42",
                    fact("T4.18", "notes", "coupon", amount="6.250", unit="decimal_percent"),
                    fact("T4.18", "notes", "maturity", text="2030-11-15"),
                    "0.3061",
                ),
            ),
            ("unsecured", "Total unsecured", subtotal("unsecured", "1500", "0.42", "0.3061")),
            ("total", "Total debt", subtotal("total", None, None, None)),
        ),
        row_header="Facility",
        kinds={"unsecured": "subtotal", "total": "total"},
    )

    def series(
        row: str, unit: str, values: tuple[str | None, ...], calc: str | None = None
    ) -> tuple[Fact, ...]:
        """One row across the periods; ``None`` is a gap with a stated reason."""
        return tuple(
            fact("T4.4", row, p, unit=unit, missing="merger debt unstated")
            if v is None
            else fact("T4.4", row, p, amount=v, unit=unit, calc=None if calc is None else calc + p)
            for p, v in zip(periods, values, strict=True)
        )

    income = layout(
        "T4.4",
        "Income statement",
        periods,
        (
            (
                "revenue",
                "Net revenues",
                series("revenue", "MILLIONS", ("9800", "10400", "10700", None)),
            ),
            (
                "ebitda",
                "Adjusted EBITDA",
                series("ebitda", "MILLIONS", ("3300", "3450", "3592", None)),
            ),
            (
                "margin",
                "Adjusted EBITDA margin",
                series("margin", "PERCENT", ("0.3367", "0.3317", "0.3357", None), calc="m-"),
            ),
        ),
    )
    tables = tuple(t for t, _ in (income, kpis, bridge, debt))
    facts = tuple(f for _, fs in (income, kpis, bridge, debt) for f in fs)
    return tables, facts


def _prose(table: str, lines: tuple[tuple[str, str, bool], ...]) -> tuple[Fact, ...]:
    return tuple(
        fact(table, row, "value", text=text, judgment=judged) for row, text, judged in lines
    )


def _labelled(table: str, lines: tuple[tuple[str, str, str], ...]) -> tuple[Fact, ...]:
    """Judged prose lines with a bold label: ``(row, label, text)``."""
    return tuple(
        fact(table, row, "value", text=text, judgment=True, label=label)
        for row, label, text in lines
    )


def _module(
    base: ModuleView, tables: tuple[ReportTable, ...] = (), facts: tuple[Fact, ...] = ()
) -> ModuleView:
    return ModuleView(
        module_id=base.module_id,
        title=base.title,
        aliases=base.aliases,
        status="candidate",
        artifact_sha256="d" * 64,
        tables=tables,
        facts=facts,
    )


def _entry(
    module: str,
    table: str,
    block: str,
    slot: str,
    label: str | None = None,
    section: Section | None = None,
) -> Binding:
    unit: UnitClass = "text"
    return Binding(
        fact_coord=FactCoord(module_id=module, table_id=table),
        block_id=block,
        cell_slot=slot,
        unit_class=unit,
        label=label,
        section=section,
    )


def _synthetic_map(module: str, *entries: tuple[str, str, str], **sections: Section) -> BindingMap:
    return BindingMap(
        module_id=module,
        entries=tuple(
            _entry(module, table, block, slot, section=sections.get(table))
            for table, block, slot in entries
        ),
    )


CREDIT_SNAPSHOT_MAPS: tuple[BindingMap, ...] = (
    CP1,
    CP1A,
    _synthetic_map(
        "CP-2",
        ("findings", "key-findings", "findings"),
        ("thesis", "strengths-weaknesses", "thesis"),
        ("strengths", "strengths-weaknesses", "strengths"),
        ("weaknesses", "strengths-weaknesses", "weaknesses"),
        thesis="thesis",
        strengths="strengths",
        weaknesses="weaknesses",
    ),
    _synthetic_map("CP-3", ("levels", "relative-value", "levels")),
    _synthetic_map(
        "CP-6", ("challenge", "committee-challenge", "challenge"), ("fit", "portfolio-fit", "fit")
    ),
)


def credit_snapshot_view() -> View:
    """A SYNTHETIC candidate view: five producers ran, the rest of the registry did not."""
    # Inherits the pre-6.5 `requested_modules` pinned in `synthetic_view` (no CP-MODEL), so the
    # synthetic pack hashes the replay corpus records stay as recorded.
    base = synthetic_view()
    cp1_tables, cp1_facts = _cp1()

    cp1a = business_context(pack_fixture(), submission_fixture())  # the shipped register shapes
    findings = (
        *_prose(
            "findings",
            (
                ("f1", "Leverage is moderate and falling in the synthetic case.", True),
                ("f2", "Liquidity covers the synthetic maturities to 2028.", True),
            ),
        ),
        fact("findings", "f3", "value", unit="MULTIPLE", missing="not extracted"),
    )
    mid = {
        "CP-1": _module(_by(base, "CP-1"), cp1_tables, cp1_facts),
        "CP-1A": _module(_by(base, "CP-1A"), cp1a.tables, cp1a.facts),
        "CP-2": _module(
            _by(base, "CP-2"),
            facts=(
                *findings,
                fact(
                    "thesis", "t1", "value", missing="Recommendation not produced", label="Thesis"
                ),
                *_labelled(
                    "strengths",
                    (
                        ("s1", "Scale", "Two regional markets carry the synthetic cash flow."),
                        ("s2", "Liquidity", "Synthetic liquidity covers maturities to 2028."),
                    ),
                ),
                *_labelled(
                    "weaknesses",
                    (
                        ("w1", "Maturities", "Synthetic maturities concentrate in 2029 and 2030."),
                        ("w2", "Capex", "Synthetic capital spending leaves little free cash flow."),
                    ),
                ),
            ),
        ),
        "CP-3": _module(
            _by(base, "CP-3"), facts=_prose("levels", (("l1", "Secured 2032s preferred.", True),))
        ),
        "CP-6": _module(
            _by(base, "CP-6"),
            facts=_prose("challenge", (("c1", "Two of three claims held.", True),))
            + _prose("fit", (("p1", "Test CLO I headroom is ample (synthetic).", False),)),
        ),
    }
    return View.model_validate_json(
        base.model_copy(
            update={
                "modules": tuple(mid.get(m.module_id, m) for m in base.modules),
                "sources": (),
            }
        ).model_dump_json()
    )


def _by(view: View, module_id: str) -> ModuleView:
    return next(m for m in view.modules if m.module_id == module_id)


def _ref(report: ReportView, fact_item: Fact) -> str:
    """The reference a cell of this fact carries: its gap, else its calculation, else its source."""
    entry = next(e for e in report.index.facts if e.coord.fact_id == fact_item.fact_id)
    for prefix in "GKSC":
        found = [r for r in entry.ref_ids if r.startswith(prefix)]
        if found:
            return found[0]
    raise AssertionError("a fixture fact has no reference")


def _marks(
    report: ReportView, facts: dict[str, Fact], keys: dict[tuple[str, str], tuple[str, str]]
) -> tuple[ChartMark, ...]:
    """Marks read from facts: ``keys`` maps (series, category) to (fact table, fact id)."""
    marks = []
    unit = {"MULTIPLE": "multiple", "MILLIONS": "amount", "PERCENT": "percent"}
    for (series, category), (_, fact_id) in keys.items():
        item = facts[fact_id]
        ref = _ref(report, item)
        cls: UnitClass = unit[item.unit or ""]  # type: ignore[assignment]
        if item.amount is None:
            marks.append(
                ChartMark(
                    series=series,
                    label=category,
                    text=format_value(None, cls, "gap", gap_id=ref),
                    ref_id=ref,
                )
            )
        else:
            marks.append(
                ChartMark(
                    series=series,
                    label=category,
                    text=format_value(item.amount, cls, "known"),
                    ref_id=ref,
                    value=item.amount,
                )
            )
    return tuple(marks)


def _spec(
    kind: str,
    series: tuple[str, ...],
    marks: tuple[ChartMark, ...],
    unit: str | None,
    uc: UnitClass,
    **x: object,
) -> ChartSpec:
    return ChartSpec(
        kind=kind,  # type: ignore[arg-type]
        series=series,
        table_twin=twin_for(marks),
        marks=marks,
        unit=unit,
        unit_class=uc,
        **x,  # type: ignore[arg-type]
    )


def synthetic_call() -> tuple[CallItem, ...]:
    """A populated call band: six scale and direction items, then the three line items.

    Invented judgements for the SYNTHETIC case; no module produces a call yet (CP-2 and CP-3 are
    M8), so real data shows the honest no-judgement state instead.
    """
    scales = (
        ("Credit view", "Neutral", 3),
        ("Business risk", "Moderate", 3),
        ("Financial risk", "Elevated", 4),
        ("Liquidity", "Adequate", 3),
    )
    return (
        *(CallItem(kind="scale", label=a, value_text=b, meter=c) for a, b, c in scales),
        CallItem(kind="direction", label="Outlook", value_text="Improving", direction="up"),
        CallItem(kind="scale", label="Relative value", value_text="Fair", meter=3),
        CallItem(
            kind="fact",
            label="Main risk",
            value_text="Refinancing. Synthetic maturities concentrate in 2029 and 2030.",
            line=True,
        ),
        CallItem(
            kind="fact",
            label="Portfolio Fit",
            value_text="Test CLO I (synthetic) has headroom for the secured notes.",
            line=True,
        ),
        CallItem(
            kind="fact",
            label="Instrument",
            value_text="Prefer the secured notes (synthetic).",
            line=True,
        ),
    )


def credit_snapshot_fixture(*, call: bool = True) -> tuple[View, ReportView]:
    """The view and the Credit Snapshot Front Page built over it, completed as documented above.

    ``call=True`` adds the populated call band; ``call=False`` keeps the honest no-judgement state.
    """
    view = credit_snapshot_view()
    pathway: Pathway = next(p for p in pathways() if p.id == "credit_snapshot")
    built = build(view, pathway, CREDIT_SNAPSHOT_MAPS)
    cp1 = _by(view, "CP-1")
    facts = {f.fact_id: f for f in cp1.facts}
    periods = ("FY2024", "FY2025", "LTM")

    def keyed(table: str, rows: dict[str, str]) -> dict[tuple[str, str], tuple[str, str]]:
        return {
            (series, p): (table, f"{table}.{row}.{p}")
            for series, row in rows.items()
            for p in periods
        }

    lev = _marks(built, facts, keyed("T4.10", {"Total": "total_leverage", "Net": "net_leverage"}))
    cover = _marks(built, facts, keyed("T4.10", {"Cover": "interest_cover"}))
    liq = _marks(built, facts, keyed("T4.10", {"Liquidity": "liquidity"}))
    wall_keys = {
        ("Revolver", "2028"): ("T4.18", "T4.18.revolver.outstanding"),
        ("Term loan A", "2029"): ("T4.18", "T4.18.tla.outstanding"),
        ("Senior notes", "2030"): ("T4.18", "T4.18.notes.outstanding"),
    }
    wall = _marks(built, facts, wall_keys)
    rev = _marks(
        built,
        facts,
        {
            (name, p): ("T4.4", f"T4.4.{row}.{p}")
            for name, row in (("Net revenues", "revenue"), ("Adjusted EBITDA", "ebitda"))
            for p in periods
        },
    )
    stack = _marks(
        built,
        facts,
        {
            ("Secured", "Revolver"): ("T4.18", "T4.18.revolver.outstanding"),
            ("Secured", "Term loan A"): ("T4.18", "T4.18.tla.outstanding"),
            ("Unsecured", "Senior notes"): ("T4.18", "T4.18.notes.outstanding"),
        },
    )
    strip = Block(
        block_id="model-chart-strip",
        title="Model chart strip",
        owner="MODEL",
        tags=("Synthetic",),
        state="populated",
        kind="chart",
        full_analysis_route="CP-1",
        route_label="Open in Model",
        figures=(
            Figure(
                fig_id="S.1",
                title="Leverage",
                chart=_spec("line", ("Total", "Net"), lev, "x", "multiple"),
                placement="above",
            ),
            Figure(
                fig_id="S.2",
                title="Interest cover",
                chart=_spec("line", ("Cover",), cover, "x", "multiple"),
                placement="above",
            ),
            Figure(
                fig_id="S.3",
                title="Liquidity",
                chart=_spec("line", ("Liquidity",), liq, "US$ m", "amount"),
                placement="above",
            ),
            Figure(
                fig_id="S.4",
                title="Maturity wall",
                chart=_spec(
                    "stacked", ("Revolver", "Term loan A", "Senior notes"), wall, "US$ m", "amount"
                ),
                placement="above",
            ),
        ),
    )
    blocks = {block.block_id: block for block in built.blocks}
    blocks["model-chart-strip"] = strip
    blocks["capital-structure"] = blocks["capital-structure"].model_copy(
        update={
            "figures": (
                Figure(
                    fig_id="S.6",
                    title="Debt stack by rank, cumulative multiple",
                    chart=_spec(
                        "debt_stack",
                        ("Secured", "Unsecured"),
                        stack,
                        None,
                        "amount",
                        denominator=facts["T4.17.adjusted.LTM"].amount,
                    ),
                ),
            )
        }
    )
    blocks["financials-credit-metrics"] = blocks["financials-credit-metrics"].model_copy(
        update={
            "figures": (
                Figure(
                    fig_id="S.5",
                    title="Net revenues and Adjusted EBITDA",
                    placement="beside",
                    summary=(
                        "Synthetic net revenues and Adjusted EBITDA move together "
                        "across the periods."
                    ),
                    chart=_spec(
                        "grouped", ("Net revenues", "Adjusted EBITDA"), rev, "US$ m", "amount"
                    ),
                ),
            )
        }
    )
    blocks["what-changed"] = Block(
        block_id="what-changed",
        title="What changed since the last Report",
        owner="CP-8",
        state="condition",
        kind="prose",
        note="Not shown: no Prior Case was accepted at Approval",
    )
    update: dict[str, object] = {"blocks": tuple(blocks[b] for b in pathway.blocks)}
    if call:
        update["call"] = synthetic_call()
    report = ReportView.model_validate_json(built.model_copy(update=update).model_dump_json())
    assert gap_refs(report.index), "the fixture must contain gaps"
    return view, report
