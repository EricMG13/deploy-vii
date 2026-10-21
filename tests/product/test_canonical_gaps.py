"""Cumulative gaps are synthetic implementation evidence, never Module acceptance."""

from datetime import date
from typing import Never

import pytest

from deploy_vii.canonical_audit import DefinitionReview
from deploy_vii.canonical_gaps import canonical_gaps, validate_canonical_gaps
from deploy_vii.context_binding import FinancialContextBinding
from deploy_vii.financial_contracts import FinancialBook, FinancialReview
from deploy_vii.preparation import PreparedPack
from deploy_vii.source_context import SourceContextReview
from tests.product.test_financial_periods import periods_case
from tests.product.test_source_context import case as context_case


def case(
    value: FinancialBook | None = None,
) -> tuple[
    PreparedPack, SourceContextReview, FinancialReview, DefinitionReview, FinancialContextBinding
]:
    pack, context, financial, binding = context_case(value)
    pack = pack.model_copy(update={"run": pack.run.model_copy(update={"as_of": date(2026, 2, 1)})})
    financial = financial.model_copy(
        update={"as_of": pack.run.as_of, "pack_sha256": pack.content_hash()}
    )
    context = context.model_copy(
        update={
            "pack_sha256": pack.content_hash(),
            "sources": tuple(
                s.model_copy(update={"published_on": date(2026, 1, 31)}) for s in context.sources
            ),
        }
    )
    binding = binding.model_copy(
        update={
            "financial_review_sha256": financial.content_hash(),
            "source_context_review_sha256": context.content_hash(),
        }
    )
    definition = DefinitionReview(
        financial_review_sha256=financial.content_hash(), book_id=financial.books[0].book_id
    )
    return pack, context, financial, definition, binding


def test_cumulative_register_preserves_every_source_gap_and_failed_check() -> None:
    args = case()
    before = tuple(x.model_dump_json() for x in args)
    report = canonical_gaps(*args)
    assert report.calculation_status == "generated" and not report.binding_issues
    assert report.kpis is not None and report.period_reconciliation is not None
    assert {g.reference for g in report.gaps if g.origin == "source_audit"} == {
        g.gap_id for g in report.audit.gaps
    }
    assert {g.reference for g in report.gaps if g.origin == "context"} == {
        g.gap_id for g in report.context.gaps
    }
    checks = {c.check_id: c for c in report.period_reconciliation.checks if c.status != "PASS"}
    for gap in (g for g in report.gaps if g.origin == "period_reconciliation"):
        assert gap.severity == checks[gap.reference].status
        assert gap.artifact_sha256 == report.period_reconciliation.content_hash()
        assert gap.periods[0].reference == checks[gap.reference].construction_id
    assert {
        g.reference for g in report.gaps if g.origin == "period_reconciliation"
    } == checks.keys()
    assert len({g.gap_id for g in report.gaps}) == len(report.gaps)
    assert tuple(x.model_dump_json() for x in args) == before
    assert validate_canonical_gaps(*args, report) == ()


def test_missing_values_unresolved_formulas_and_evidence_tiers_are_explicit() -> None:
    report = canonical_gaps(*case())
    assert report.kpis is not None
    kpis = report.kpis
    historical = kpis.historical
    assert {v.value_id for v in historical.values if v.value.amount is None} <= {
        g.reference for g in report.gaps if g.origin == "historical_value"
    }
    assert {v.value_id for v in kpis.values if v.value.amount is None} <= {
        g.reference for g in report.gaps if g.origin == "canonical_value"
    }
    assert {v.calculation_id for v in kpis.kpis if v.value.amount is None} <= {
        g.reference for g in report.gaps if g.origin == "kpi"
    }
    assert not any(g.origin == "kpi" and "definition" in g.description for g in report.gaps)
    assert {g.reference for g in report.gaps if g.origin == "kpi_evidence"} == {
        v.calculation_id for v in kpis.kpis
    }


def test_partial_addback_gate_retains_source_gaps_and_does_not_invent_calculations() -> None:
    base = periods_case()
    value = base.model_copy(
        update={
            "addback_disclosure": base.addback_disclosure.model_copy(update={"status": "partial"})
        }
    )
    report = canonical_gaps(*case(value))
    assert report.calculation_status == "blocked"
    assert report.kpis is None and report.period_reconciliation is None
    assert report.calculation_issues and report.audit.gaps
    assert any(g.origin == "calculation_gate" and g.severity == "BLOCK" for g in report.gaps)
    assert any(g.origin == "source_audit" for g in report.gaps)


@pytest.mark.parametrize("mode", ["stale", "scope", "unknown_entity"])
def test_invalid_binding_is_visible_as_block_without_discarding_source_registers(mode: str) -> None:
    pack, context, financial, definition, binding = case()
    if mode == "stale":
        binding = binding.model_copy(update={"financial_review_sha256": "0" * 64})
    elif mode == "unknown_entity":
        binding = binding.model_copy(
            update={"books": (binding.books[0].model_copy(update={"entity_id": "unknown"}),)}
        )
    else:
        source = context.sources[0]
        source = source.model_copy(
            update={
                "scopes": tuple(
                    s.model_copy(update={"accounting_basis": "IFRS"}) for s in source.scopes
                )
            }
        )
        context = context.model_copy(update={"sources": (source,)})
        binding = binding.model_copy(
            update={"source_context_review_sha256": context.content_hash()}
        )
    report = canonical_gaps(pack, context, financial, definition, binding)
    assert report.binding_issues
    assert {g.description for g in report.gaps if g.origin == "context_binding"} == set(
        report.binding_issues
    )
    assert all(g.severity == "BLOCK" for g in report.gaps if g.origin == "context_binding")
    assert report.audit.source_positions


def test_tampering_and_substituted_external_inputs_are_rejected() -> None:
    args = case()
    report = canonical_gaps(*args)
    for changes in (
        {"gaps": ()},
        {"schema_version": "old"},
        {"calculation_issues": ("invented",)},
        {"kpis": None},
    ):
        assert validate_canonical_gaps(*args, report.model_copy(update=changes))
    pack, context, financial, definition, binding = args
    changed = definition.model_copy(update={"limitations": ("New limitation",)})
    other = canonical_gaps(pack, context, financial, changed, binding)
    assert validate_canonical_gaps(*args, other)


def test_derived_operand_gaps_keep_parent_and_operand_periods() -> None:
    args = case(periods_case())
    report = canonical_gaps(*args)
    assert report.kpis is not None
    history = report.kpis.historical
    node = next(n for n in history.constructions if n.column_key == "Q:H1-Q1")
    row = next(
        r
        for r in history.values
        if r.construction_id == node.construction_id
        and r.series_key == "acct:capex_and_intangible_investment"
    )
    gap = next(
        g
        for g in report.gaps
        if g.origin == "historical_operand" and g.reference == f"{row.value_id}:0"
    )
    assert {p.reference for p in gap.periods} == {node.construction_id, "H1"}
    operand = next(p for p in gap.periods if p.reference == "H1")
    assert operand.start_date == date(2025, 1, 1) and operand.end_date == date(2025, 6, 30)


def test_binding_scope_collision_does_not_attach_unrelated_dates_to_context_gap() -> None:
    pack, context, financial, definition, binding = case()
    source = context.sources[0]
    source = source.model_copy(
        update={
            "scopes": (
                source.scopes[0].model_copy(update={"scope_id": "issuer"}),
                source.scopes[1].model_copy(update={"currency": "EUR"}),
            )
        }
    )
    context = context.model_copy(update={"sources": (source,)})
    binding = binding.model_copy(update={"source_context_review_sha256": context.content_hash()})
    report = canonical_gaps(pack, context, financial, definition, binding)
    gap = next(
        g
        for g in report.gaps
        if g.origin == "context" and "Different source currency" in g.description
    )
    assert {p.reference for p in gap.periods} == {"issuer", "Q2"}


def test_kpi_gap_tracks_actual_operand_bases_and_null_adapter_inputs() -> None:
    report = canonical_gaps(*case())
    assert report.kpis is not None
    values = {v.value_id: v for v in report.kpis.values}
    for row in report.kpis.kpis:
        if row.value.amount is not None:
            continue
        gap = next(
            g for g in report.gaps if g.origin == "kpi" and g.reference == row.calculation_id
        )
        expected = {row.display_basis_id} | {
            values[o.value_id].basis_id
            for leg in (row.numerator, row.denominator)
            if leg
            for o in leg.operands
        }
        assert {p.reference for p in gap.periods} == expected
    history = report.kpis.historical
    assert {f"input:{i}" for i, r in enumerate(history.input_rows) if r.adapter_amount is None} == {
        g.reference for g in report.gaps if g.origin == "historical_input"
    }


def test_known_zero_is_not_reclassified_missing_and_original_caveats_stay_visible() -> None:
    from tests.product.test_reconciliation import accounts

    value = accounts(periods_case(), "Q1", revenue="0")
    report = canonical_gaps(*case(value))
    assert report.kpis is not None
    history = report.kpis.historical
    index = next(
        i
        for i, r in enumerate(history.input_rows)
        if r.period_id == "Q1" and r.series_key == "acct:revenue"
    )
    assert history.input_rows[index].adapter_amount == 0
    assert not any(
        g.origin == "historical_input" and g.reference == f"input:{index}" for g in report.gaps
    )
    for artifact in (
        report.context,
        report.audit,
        history,
        report.kpis,
        report.period_reconciliation,
    ):
        assert artifact is not None
        artifact_hash = artifact.content_hash()
        assert set(artifact.limitations) <= {
            g.description for g in report.gaps if g.artifact_sha256 == artifact_hash
        }


def test_source_conflicts_cannot_be_hidden_by_generated_kpis() -> None:
    from tests.product.test_financials import book, conflict

    value = book()
    row = value.accounts[0]
    value = value.model_copy(
        update={
            "accounts": (
                row.model_copy(update={"value": conflict(row.value.observation_id)}),
                *value.accounts[1:],
            )
        }
    )
    report = canonical_gaps(*case(value))
    assert any(
        g.origin == "source_audit"
        and g.metric == row.value.observation_id
        and g.severity == "BLOCK"
        for g in report.gaps
    )
    assert report.calculation_status == "generated"


def test_calculation_errors_are_not_converted_into_plausible_source_only_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    module = importlib.import_module("deploy_vii.canonical_gaps")

    def fail(*args: object) -> Never:
        raise ValueError("Unexpected calculation defect")

    monkeypatch.setattr(module, "canonical_kpis", fail)
    with pytest.raises(ValueError, match="Unexpected calculation defect"):
        canonical_gaps(*case())


def test_nested_serialized_inputs_are_reconstructed_and_invalid_input_contract_rejected() -> None:
    pack, context, financial, definition, binding = case()
    expected = canonical_gaps(pack, context, financial, definition, binding)
    financial = financial.model_copy(
        update={"books": tuple(b.model_dump() for b in financial.books)}
    )
    context = context.model_copy(update={"sources": tuple(s.model_dump() for s in context.sources)})
    with pytest.warns(UserWarning):
        actual = canonical_gaps(pack, context, financial, definition, binding)
    assert actual == expected
    with pytest.raises(ValueError):
        canonical_gaps(*case()[:-1], binding.model_copy(update={"schema_version": "old"}))


def test_gap_ids_are_stable_and_distinguish_sources_with_identical_warning_text() -> None:
    pack, context, financial, definition, binding = case()
    source = context.sources[0]
    context = context.model_copy(
        update={
            "sources": (source.model_copy(update={"limitations": ("Same warning",)}),),
            "limitations": ("Same warning",),
        }
    )
    definition = definition.model_copy(update={"limitations": ("Same warning",)})
    binding = binding.model_copy(update={"source_context_review_sha256": context.content_hash()})
    first = canonical_gaps(pack, context, financial, definition, binding)
    second = canonical_gaps(pack, context, financial, definition, binding)
    assert first == second
    gaps = [g for g in first.gaps if g.description == "Same warning"]
    assert len(gaps) >= 3 and len({g.gap_id for g in gaps}) == len(gaps)
