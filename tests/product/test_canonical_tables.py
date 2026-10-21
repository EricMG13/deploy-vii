"""Canonical register parity; synthetic fixtures do not qualify financial analysis."""

import pytest

from deploy_vii.canonical_audit import DefinitionReview
from deploy_vii.canonical_tables import (
    COLUMNS,
    CanonicalTables,
    _calculations,
    _keys,
    canonical_tables,
)
from deploy_vii.context_binding import FinancialContextBinding
from deploy_vii.contracts import Fact
from deploy_vii.downstream_readiness import DownstreamReview, downstream_inputs
from deploy_vii.financial_contracts import FinancialBook, FinancialReview
from deploy_vii.model_interface import _Tables
from deploy_vii.narrative import NarrativeReview, narrative_inputs
from deploy_vii.preparation import PreparedPack
from deploy_vii.source_context import SourceContextReview
from deploy_vii.table_markdown import read_table_markdown, table_markdown
from tests.product.test_canonical_gaps import case
from tests.product.test_financials import book
from tests.product.test_model_readiness import ready_case
from tests.product.test_narrative import draft


def fixture(
    value: FinancialBook | None = None,
) -> tuple[
    PreparedPack,
    SourceContextReview,
    FinancialReview,
    DefinitionReview,
    FinancialContextBinding,
    NarrativeReview,
    tuple[str, ...],
    DownstreamReview,
]:
    args = case(value or ready_case())
    narrative = draft(narrative_inputs(*args))
    downstream = downstream_inputs(*args, narrative, ("CP-2A", "CP-4A"))
    review = DownstreamReview(inputs_sha256=downstream.content_hash())
    return (*args, narrative, downstream.requested_consumers, review)


@pytest.fixture(scope="module")
def report() -> CanonicalTables:
    return canonical_tables(*fixture())


def cells(report: CanonicalTables, table: str) -> list[dict[str, Fact]]:
    facts = {f.fact_id: f for f in report.module.facts}
    layout = next(t for t in report.module.tables if t.table_id == table)
    return [
        dict(zip((c.label for c in layout.columns), (facts[i] for i in r.fact_ids), strict=True))
        for r in layout.rows
    ]


def test_all_required_tables_and_single_interface_tags(report: CanonicalTables) -> None:
    ids = [t.table_id for t in report.module.tables]
    assert [f"T4.{i}" for i in range(1, 20) if i != 7] == ids[:18]
    assert report.module.status == "candidate" and not report.module.claims
    assert len({f.fact_id for f in report.module.facts}) == len(report.module.facts)
    assert {x.input_id for x in report.module.inputs} == {
        "pack",
        "financial-review",
        "downstream-report",
        "statement-history",
    }
    readiness = next(
        t for t in report.module.tables if t.interface_id == "cp1.downstream_readiness"
    )
    assert len(readiness.rows) == 1
    row = next(r for r in cells(report, "T4.13") if r["Downstream Module"].text == "CP-MODEL")
    assert row["Readiness Status"].text == report.downstream.model.status
    parsed = read_table_markdown(table_markdown(report.module, "model-readiness"))
    assert parsed.rows[0][1] == report.downstream.model.status


def test_sources_and_entities_keep_actual_scope_pairs(report: CanonicalTables) -> None:
    rows = cells(report, "T4.1")
    expected = [
        (source, scope)
        for source in report.downstream.inputs.narrative.inputs.ledger.context.sources
        for scope in source.assessment.scopes
    ]
    assert len(rows) == len(expected)
    for row, (source, scope) in zip(rows, expected, strict=True):
        assert row["Source File Name"].text == source.filename
        assert row["Currency"].text == scope.currency
        assert scope.period_label in row["Period Coverage"].text
        assert row["Evidence Quality Tier"].text == source.evidence_tier
        assert set(scope.citations) <= set(row["Currency"].citations)
    assert cells(report, "T4.2")


def test_kpis_and_calculations_keep_values_operands_and_exact_periods(
    report: CanonicalTables,
) -> None:
    kpis = report.downstream.inputs.narrative.inputs.ledger.kpis
    assert kpis is not None
    dashboard = cells(report, "T4.10")
    for item in kpis.kpis:
        fact = next(
            f
            for f in report.module.facts
            if f.table_id == "T4.10" and f.calculation_id == item.calculation_id
        )
        assert fact.amount == item.value.amount and fact.formula == item.formula
        basis = next(b for b in kpis.bases if b.basis_id == item.display_basis_id)
        assert str(basis.end_date) in fact.period
        if item.unit in {"PERCENT", "MULTIPLE"}:
            assert fact.currency is None
        if fact.amount is None:
            assert fact.limitation
    assert all(r["Trend Direction"].status == "missing" for r in dashboard)
    register = cells(report, "T4.9")
    for item in kpis.kpis:
        matches = [
            r for r in register if r["Calculated Value"].calculation_id == item.calculation_id
        ]
        assert len(matches) == 1
        row = matches[0]
        assert row["Numerator Value"].amount == item.numerator.amount
        if item.denominator:
            assert row["Denominator Value"].amount == item.denominator.amount
            for operand in item.denominator.operands:
                assert operand.value_id in row["Operand References"].text
        else:
            assert row["Denominator Value"].status == "not_applicable"
    assert any(r["Calculated Value"].amount is not None for r in register)


def test_all_upstream_and_projection_gaps_remain_visible(report: CanonicalTables) -> None:
    descriptions = [r["Gap Description"].text for r in cells(report, "T4.12")]
    for gap in report.downstream.inputs.narrative.gaps:
        assert any(gap.gap_id in text for text in descriptions)
    for gap in report.interface.gaps:
        assert any(f"{gap.table_id}/{gap.row_id}/{gap.field}" in text for text in descriptions)
    for f in report.module.facts:
        if f.table_id in {"T4.4", "T4.5", "T4.6"} and f.status != "known":
            assert any(f"{f.table_id}/{f.row_id}/{f.field}" in text for text in descriptions)
    assert set(r["Downstream Module"].text for r in cells(report, "T4.13")) == {
        "CP-2A",
        "CP-4A",
        "CP-MODEL",
    }


def test_incomplete_model_gate_does_not_hide_source_and_statement_registers() -> None:
    value = book()
    value = value.model_copy(
        update={
            "addback_disclosure": value.addback_disclosure.model_copy(update={"status": "partial"})
        }
    )
    result = canonical_tables(*fixture(value))
    assert result.downstream.inputs.narrative.inputs.ledger.kpis is None
    assert not cells(result, "T4.10")
    assert cells(result, "T4.1") and cells(result, "T4.8") and cells(result, "T4.9")
    assert result.downstream.model.status == "blocked"


def test_stale_external_binding_is_rejected() -> None:
    args = list(fixture(book()))
    args[1] = args[1].model_copy(update={"pack_sha256": "0" * 64})
    with pytest.raises(ValueError):
        canonical_tables(*args)


def test_source_graph_reused_across_metrics_keeps_both_contexts(report: CanonicalTables) -> None:
    history = report.statements
    first = history.values[0]
    alternate = first.model_copy(
        update={"item_id": "same_graph_other_metric", "value_id": "other-value"}
    )
    selected = history.model_copy(update={"values": (first, alternate)})
    tables = _Tables(
        report.downstream.inputs.financial_book,
        schemas={"T4.9": (COLUMNS["T4.9"][0], None, _keys("T4.9"))},
    )
    _calculations(tables, report.downstream, selected)
    root_names = [f.text for f in tables.facts if f.field == "field_0"]
    assert f"{first.table_id}/{first.item_id}" in root_names
    assert f"{first.table_id}/same_graph_other_metric" in root_names


def test_absent_optional_limitation_notes_are_not_missing_source_values(
    report: CanonicalTables,
) -> None:
    history = {v.value_id: v for v in report.statements.values}
    source = next(
        v
        for v in history.values()
        if v.value.amount is not None and not v.value.reason and not v.value.note
    )
    matching = next(
        f
        for f in report.module.facts
        if f.table_id == "T4.8" and f.calculation_id == source.computation_id
    )
    row = next(r for r in cells(report, "T4.8") if r["Derived Value"].fact_id == matching.fact_id)
    assert row["Limitations"].status == "not_applicable"


def test_definition_conflicts_show_both_debt_figures_and_their_roles(
    report: CanonicalTables,
) -> None:
    row = next(r for r in cells(report, "T4.11") if "debt_basis" in r["Source of Conflict"].text)
    positions = row["Source Positions"].text
    assert positions and "carrying_value" in positions and "gross_principal" in positions
    assert "100" in positions and "105" in positions and "USD" in positions


def test_context_block_overrides_standalone_historical_ready_in_both_tables() -> None:
    args = case(ready_case())
    args = (*args[:-1], args[-1].model_copy(update={"financial_review_sha256": "0" * 64}))
    narrative = draft(narrative_inputs(*args))
    inputs = downstream_inputs(*args, narrative, ())
    result = canonical_tables(
        *args, narrative, (), DownstreamReview(inputs_sha256=inputs.content_hash())
    )
    assert result.interface.readiness.readiness.status == "ready"
    assert result.downstream.model.status == "blocked"
    assert cells(result, "T4.13")[0]["Readiness Status"].text == "blocked"
    parsed = read_table_markdown(table_markdown(result.module, "model-readiness"))
    assert parsed.rows[0][1] == "blocked"


def test_sign_and_missing_fx_normalizations_retain_original_units() -> None:
    from tests.product.test_financials import observed

    value = book()
    value = value.model_copy(
        update={
            "accounts": tuple(
                a.model_copy(update={"value": observed(a.value.observation_id, "30")})
                if a.metric_id == "cogs"
                else a
                for a in value.accounts
            ),
            "facilities": tuple(f.model_copy(update={"currency": "EUR"}) for f in value.facilities),
            "addback_disclosure": value.addback_disclosure.model_copy(update={"status": "partial"}),
        }
    )
    result = canonical_tables(*fixture(value))
    rows = cells(result, "T4.3")
    sign = next(r for r in rows if r["Type"].text == "negative absolute source amount")
    assert sign["Before"].amount == 30 and sign["After"].amount == -30
    assert sign["After"].source_amount == 30
    fx = next(
        r for r in rows if r["Type"].text == "FX EUR to USD" and r["Before"].amount is not None
    )
    assert fx["Before"].currency == "EUR" and fx["After"].currency == "USD"
    assert fx["After"].amount is None and fx["After"].limitation


def test_report_validation_detects_precision_changes_with_equal_decimal_values() -> None:
    from decimal import Decimal

    from deploy_vii.canonical_tables import validate_canonical_tables

    value = book()
    value = value.model_copy(
        update={
            "addback_disclosure": value.addback_disclosure.model_copy(update={"status": "partial"})
        }
    )
    args = fixture(value)
    result = canonical_tables(*args)
    assert validate_canonical_tables(*args, result) == ()
    original = next(f for f in result.module.facts if f.amount is not None)
    altered = original.model_copy(
        update={
            "amount": Decimal(str(original.amount) + ".0")
            if "." not in str(original.amount)
            else Decimal(str(original.amount) + "0")
        }
    )
    assert original.amount == altered.amount
    changed = result.model_copy(
        update={
            "module": result.module.model_copy(
                update={
                    "facts": tuple(
                        altered if f.fact_id == original.fact_id else f for f in result.module.facts
                    )
                }
            )
        }
    )
    assert validate_canonical_tables(*args, changed) == (
        "Canonical registers differ from trusted external recomputation",
    )
