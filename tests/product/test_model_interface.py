"""r14 Model interface projection and canonical Markdown transport regressions."""

from decimal import Decimal

import pytest

from deploy_vii.model_interface import SCHEMAS, model_interface, validate_model_interface
from deploy_vii.table_markdown import (
    markdown_cell,
    read_table_markdown,
    table_markdown,
    validate_table_markdown,
)
from tests.product.test_financials import book, conflict, freeze, observed


def test_exact_registers_sources_and_immutable_recomputation() -> None:
    value = book()
    pack, review = freeze(value)
    report = model_interface(pack, review, value.book_id)
    assert report.module.status == "candidate"
    assert len(report.module.tables) == 9
    assert validate_model_interface(pack, review, report) == ()
    assert validate_model_interface(pack, review, report.model_copy(update={"gaps": ()}))
    assert validate_model_interface(pack, review, report.model_copy(update={"book_id": "unknown"}))
    for table in report.module.tables:
        assert tuple(c.field for c in table.columns) == SCHEMAS[table.table_id][2]
        raw = table_markdown(report.module, table.table_id)
        parsed = read_table_markdown(raw)
        assert parsed.interface_id == table.interface_id
        assert len(parsed.rows) == len(table.rows)
        assert validate_table_markdown(report.module, table.table_id, raw) == ()
    assert next(t for t in report.module.tables if t.table_id == "T4.16").rows == ()
    assert next(t for t in report.module.tables if t.table_id == "T4.17").rows == ()
    readiness = next(t for t in report.module.tables if t.table_id == "model-readiness")
    assert len(readiness.rows) == 1 and report.readiness.readiness.status == "blocked"
    for fact in report.module.facts:
        if fact.amount is not None:
            assert fact.period and fact.unit and fact.currency == "USD"
    assert any(g.field == "annual_amortisation" for g in report.gaps)
    assert not any(
        g.field in {"component_period_ids", "conflict_refs", "limitation_refs"} for g in report.gaps
    )
    with pytest.raises(ValueError, match="bind"):
        model_interface(pack, review.model_copy(update={"pack_sha256": "0" * 64}), value.book_id)


def test_fixed_coupon_is_percent_foreign_money_stays_foreign_and_none_is_not_null() -> None:
    value = book()
    facility = value.facilities[0].model_copy(
        update={
            "currency": "EUR",
            "rate_type": "FIXED",
            "reference_rate": "NONE",
            "fixed_rate": observed("loan.Q2.fixed", "6.500"),
            "annual_amortisation": observed("loan.Q2.amort", "0"),
        }
    )
    value = value.model_copy(update={"facilities": (facility,)})
    pack, review = freeze(value)
    report = model_interface(pack, review, value.book_id)
    facts = {f.field: f for f in report.module.facts if f.table_id == "T4.18"}
    assert facts["carrying_value"].amount == 100 and facts["carrying_value"].currency == "EUR"
    assert facts["fixed_rate"].amount == Decimal("6.500")
    assert facts["fixed_rate"].unit == "decimal_percent" and facts["fixed_rate"].currency is None
    assert facts["annual_amortisation"].amount == 0
    assert facts["spread_bps"].status == "not_applicable"
    parsed = read_table_markdown(table_markdown(report.module, "T4.18"))
    assert dict(zip(parsed.headings, parsed.rows[0], strict=True))["reference_rate"] == "NONE"
    assert not any(
        g.field in {"spread_bps", "floor_bps", "annual_amortisation"}
        for g in report.gaps
        if g.table_id == "T4.18"
    )


def test_missing_conflicting_and_normalized_accounts_keep_distinct_provenance() -> None:
    value = book()
    value = value.model_copy(
        update={
            "accounts": tuple(
                row.model_copy(update={"value": observed(row.value.observation_id, "30")})
                if row.metric_id == "cogs"
                else row.model_copy(update={"value": conflict(row.value.observation_id)})
                if row.metric_id == "revenue"
                else row
                for row in value.accounts
            )
        }
    )
    pack, review = freeze(value)
    report = model_interface(pack, review, value.book_id)
    facts = {f.fact_id: f for f in report.module.facts}
    for row in next(t for t in report.module.tables if t.table_id == "T4.15").rows:
        cells = {facts[f].field: facts[f] for f in row.fact_ids}
        if cells["metric_id"].text == "cogs":
            assert cells["value"].amount == -30 and cells["value"].source_amount == 30
            assert cells["value"].value_class == "normalized" and cells["value"].formula
        if cells["metric_id"].text == "revenue":
            assert cells["value"].status == "conflicting" and cells["value"].amount is None
            assert cells["value"].citations and cells["conflict_refs"].text
            assert cells["value"].unit == "MILLIONS" and cells["value"].currency == "USD"


@pytest.mark.parametrize(
    "source",
    [
        "<br> &amp; &#10; | `x` **a** [x](url) \\ newline\nnext",
        " leading and trailing ",
        "源—é",
        "a\u2028b",
        "NONE",
    ],
)
def test_reader_decodes_generated_cells_once_and_preserves_source_text(source: str) -> None:
    raw = "| field |\n|---|\n| " + markdown_cell(source) + " |"
    assert read_table_markdown(raw).rows == ((source,),)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "| a |\n|---|\n| x | y |",
        "| a | a |\n|---|---|",
        "| a |\n|---|\n| <img src=x> |",
        "| a |\n|---|\n| &#x41; |",
        "| a |\n|---|\n| x|y |",
        "| a |\n|:---|\n| x |",
        "<!-- table-id: cp1.test -->\nprose\n| a |\n|---|",
        "<!-- table-id: cp1.test -->\n\n| a b |\n|---|",
        "| a |\n|---|\n| x |\n<!-- table-id: cp1.evil -->",
        "| a |\r\n|---|",
    ],
)
def test_reader_rejects_ambiguous_or_noncanonical_table_syntax(raw: str) -> None:
    with pytest.raises(ValueError):
        read_table_markdown(raw)


def test_hash_bound_table_verification_rejects_precision_and_identity_changes() -> None:
    value = book()
    pack, review = freeze(value)
    module = model_interface(pack, review, value.book_id).module
    raw = table_markdown(module, "T4.18")
    assert validate_table_markdown(module, "T4.18", raw.replace("100", "100.0", 1))
    assert validate_table_markdown(module, "T4.18", raw.replace("cp1.debt", "cp1.other", 1))
    assert validate_table_markdown(module, "T4.18", raw + "\n")
    assert validate_table_markdown(module, "unknown", raw)


def test_dynamic_schedules_preserve_labels_order_missing_periods_and_source_definitions() -> None:
    from deploy_vii.financial_contracts import (
        AddbackObservation,
        KpiObservation,
        SegmentAllocation,
        SegmentObservation,
    )
    from tests.product.test_financials import _C

    value = book()
    segment = SegmentObservation(
        segment_id="gaming",
        segment_name="Gaming | Resorts & <hotels>",
        segment_type="OPERATING_SEGMENT",
        display_priority=1,
        period_id="Q2",
        revenue=observed("segment.Q2", "100"),
        classification_citations=(_C,),
    )
    addback = AddbackObservation(
        addback_id="oneoff",
        addback_label="Issuer restructuring",
        classification="RESTRUCTURING",
        realization_status="UNREALIZED",
        display_priority=1,
        period_id="Q2",
        value=observed("addback.Q2", "5"),
        source_definition="Restructuring scope",
        classification_citations=(_C,),
    )
    kpi = KpiObservation(
        kpi_id="occupancy",
        kpi_label="Occupancy",
        business_unit="Hotels",
        kpi_category="Operations",
        definition="Occupied / available",
        display_priority=1,
        period_id="Q2",
        value=observed("occupancy.Q2", "0.8"),
        unit="FRACTION",
        value_type="RATE",
        definition_citations=(_C,),
    )
    value = value.model_copy(
        update={
            "segments": (segment,),
            "addbacks": (addback,),
            "kpis": (kpi,),
            "segment_allocation": (
                SegmentAllocation(
                    slot_id="DIVISION_1",
                    slot_label="Hotels",
                    component_segment_ids=("gaming",),
                    rationale="Explicit fixture mapping",
                ),
            ),
            "segment_disclosure": value.segment_disclosure.model_copy(update={"status": "partial"}),
            "addback_disclosure": value.addback_disclosure.model_copy(update={"status": "partial"}),
        }
    )
    pack, review = freeze(value)
    report = model_interface(pack, review, value.book_id)
    assert report.readiness.readiness.status == "blocked"
    for tableid in ("T4.16", "T4.17", "operating-kpis"):
        raw = read_table_markdown(table_markdown(report.module, tableid))
        assert len(raw.rows) == 2
        rows = [dict(zip(raw.headings, r, strict=True)) for r in raw.rows]
        field = "revenue" if tableid == "T4.16" else "value"
        assert rows[0][field] == "null" and rows[0]["period_id"] == "Q1"
        assert rows[1][field] != "null"
    rows = read_table_markdown(table_markdown(report.module, "T4.16"))
    assert rows.rows[0][1] == segment.segment_name
    assert (
        len(next(t for t in report.module.tables if t.table_id == "segment-allocation").rows) == 1
    )
    kpis = [f for f in report.module.facts if f.table_id == "operating-kpis" and f.field == "value"]
    assert all(f.currency is None and f.unit == "FRACTION" for f in kpis if f.amount is not None)


def test_ready_row_stays_scoped_and_reference_nulls_do_not_create_gaps() -> None:
    from tests.product.test_financial_periods import frozen
    from tests.product.test_model_readiness import ready_case

    value = ready_case()
    pack, review = frozen(value)
    report = model_interface(pack, review, value.book_id)
    assert report.readiness.readiness.status == "ready"
    assert report.module.status == "candidate"
    assert not any(g.table_id == "model-readiness" for g in report.gaps)
    assert "selected_historical_quarters" == report.readiness.readiness.scope


def test_pro_forma_schedule_is_separate_from_original_source_accounts() -> None:
    from datetime import date

    from deploy_vii.financial_contracts import ProFormaObservation
    from tests.product.test_financials import _C, period

    value = book()
    ltm = period("LTM", "2024-07-01", "2025-06-30", 2, "LTM")
    adjustment = ProFormaObservation(
        adjustment_id="acq",
        event_id="event",
        label="Acquisition",
        period_id="LTM",
        effective_date=date(2025, 7, 2),
        announced_on=date(2025, 7, 1),
        event_status="completed",
        classification="ACQUISITION",
        metric_id="facility:loan",
        value=observed("acquisition", "20"),
        event_citations=(_C,),
    )
    value = value.model_copy(update={"periods": (*value.periods, ltm), "pro_forma": (adjustment,)})
    pack, review = freeze(value)
    result = model_interface(pack, review, value.book_id)
    table = read_table_markdown(table_markdown(result.module, "pro-forma"))
    row = dict(zip(table.headings, table.rows[0], strict=True))
    assert row["value"] == "20" and row["metric_id"] == "facility:loan"
    assert row["effective_date"] == "2025-07-02"
    assert (
        next(
            f for f in result.module.facts if f.table_id == "T4.18" and f.field == "carrying_value"
        ).amount
        == 100
    )


def test_prior_coupon_unit_schema_cannot_be_silently_reinterpreted() -> None:
    from pydantic import ValidationError

    from deploy_vii.canonical_audit import CanonicalAuditReport, canonical_audit
    from tests.product.test_canonical_audit import case

    report = canonical_audit(*case(book()))
    assert report.schema_version == "canonical-audit/4"
    with pytest.raises(ValidationError, match="canonical-audit/4"):
        CanonicalAuditReport.model_validate_json(
            report.model_copy(update={"schema_version": "canonical-audit/3"}).model_dump_json()
        )
