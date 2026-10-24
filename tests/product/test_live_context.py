"""Task 7.5: what each later CP-1 step is shown of the retained steps (bounded projections)."""

import json
from collections import Counter
from datetime import date
from decimal import Decimal

import pytest

from deploy_vii.canonical_audit import DefinitionRow, NormalizationRow
from deploy_vii.cp1_workflow import CP1_PROMOTION, FinancialStage
from deploy_vii.downstream_readiness import DownstreamInputs
from deploy_vii.live import context
from deploy_vii.narrative import EvidenceRecord, _catalogue
from deploy_vii.source_context import SubsequentEvent
from tests.product.test_cp1_workflow import staged
from tests.product.test_execution import step_text

Outputs = dict[str, str]
EVIDENCE = '["narrative-evidence:'


@pytest.fixture(scope="module")
def outputs(tmp_path_factory: pytest.TempPathFactory) -> Outputs:
    """The retained outputs of the four valid CP-1 stages of the synthetic case."""
    store, attempt = staged(tmp_path_factory.mktemp("context"))
    return {step.step_id: step_text(store, step) for step in attempt.steps}


@pytest.fixture(scope="module")
def partial(tmp_path_factory: pytest.TempPathFactory) -> Outputs:
    """The same with no KPI: no model report and a data-quality-only narrative."""
    store, attempt = staged(tmp_path_factory.mktemp("partial"), partial=True)
    return {step.step_id: step_text(store, step) for step in attempt.steps}


def evidence(text: str) -> dict[str, list[list[object]]]:
    """The evidence table's rows by kind, checked against each kind header's columns."""
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("evidence: "))
    table: dict[str, list[list[object]]] = {}
    columns: list[str] = []
    kind = ""
    for line in lines[start + 1 :]:
        if line.startswith("kind="):
            kind = line.split()[0].removeprefix("kind=")
            columns = json.loads(line.split("columns=", 1)[1])
            assert int(line.split()[1].removeprefix("entries=")) >= 1
            table[kind] = []
            continue
        row = json.loads(line)
        assert len(row) == len(columns) and columns[0] == "evidence_id", line
        table[kind].append(row)
    return table


def ids(table: dict[str, list[list[object]]]) -> Counter[object]:
    return Counter(row[0] for rows in table.values() for row in rows)


def test_the_table_is_complete_for_cp1_and_an_unlisted_pair_fails_closed() -> None:
    for index, consumer in enumerate(CP1_PROMOTION):
        for producer in CP1_PROMOTION[:index]:
            assert context.projection_name(consumer, producer) in {
                context.FULL,
                context.OMITTED,
                context.NARRATIVE_EVIDENCE,
                context.READINESS_INPUTS,
            }, (consumer, producer)
    assert len(context.PROJECTIONS) == sum(range(len(CP1_PROMOTION)))
    for pair in (("financials", "narrative"), ("narrative", "mystery"), ("business_context", "x")):
        with pytest.raises(context.ProjectionError, match="no projection"):
            context.projection_name(*pair)
        with pytest.raises(context.ProjectionError, match="no projection"):
            context.upstream_text(*pair, "{}")
    with pytest.raises(context.ProjectionError, match="is not sent"):
        context.upstream_text("quality", "readiness", "{}")
    # R4: Python's QA scope is the quality model's context; R5: financials keeps its block.
    assert all(context.projection_name("quality", p) == context.OMITTED for p in CP1_PROMOTION[:4])
    assert context.projection_name("financials", "source_context") == context.FULL


def test_financials_receives_the_source_context_report_unchanged(outputs: Outputs) -> None:
    raw = outputs["source_context"]
    assert context.upstream_text("financials", "source_context", raw) == raw


def test_the_narrative_table_names_each_catalogue_evidence_id_exactly_once(
    outputs: Outputs,
) -> None:
    stage = FinancialStage.model_validate_json(outputs["financials"])
    text = context.upstream_text("narrative", "financials", outputs["financials"])
    table = evidence(text)
    catalogue = _catalogue(stage.narrative_inputs.ledger)
    shown = ids(table)
    assert set(shown.values()) == {1}
    assert list(shown) == [
        r.evidence_id for r in sorted(catalogue, key=lambda r: list(table).index(r.kind))
    ]
    assert set(shown) == {r.evidence_id for r in catalogue}
    assert set(table) == {r.kind for r in catalogue}


def test_the_narrative_projection_is_bounded_and_carries_no_record_or_citation(
    outputs: Outputs,
) -> None:
    raw = outputs["financials"]
    text = context.upstream_text("narrative", "financials", raw)
    rows = [line for line in text.split("\n") if line.startswith(EVIDENCE)]
    assert sum(map(len, rows)) / len(rows) <= 180  # characters per catalogue line, on average
    assert len(text) <= raw.__len__() // 10  # R2: at most 10% of the raw output
    for absent in ("record_json", '"quote"', '"locator"', "citations", "sha256"):
        assert absent not in text, absent
    stage = FinancialStage.model_validate_json(raw)
    assert stage.model is not None
    assert f"model_metrics: entries={len(stage.model.metrics)} " in text
    for key in ("historical", "period_reconciliation", "audit", "kpis", "values"):
        assert f'"{key}":' not in text, key  # Python's registers are not sent
    assert f"scope: {json.dumps(stage.narrative_inputs.scope)}" in text


def test_the_narrative_lines_summarise_each_kind_from_its_own_record(outputs: Outputs) -> None:
    stage = FinancialStage.model_validate_json(outputs["financials"])
    table = evidence(context.upstream_text("narrative", "financials", outputs["financials"]))
    records = {r.evidence_id: json.loads(r.record_json) for r in stage.narrative_inputs.catalogue}
    bases = {
        d["basis_id"]: d["label"] for d in records.values() if "basis_id" in d and "label" in d
    }
    for kpi in table["kpi"]:
        data = records[kpi[0]]
        assert kpi[1:] == [
            data["key"],
            bases[data["display_basis_id"]],
            data["value"]["amount"],
            data["unit"],
            data["currency"],
            data["value"]["calculation_status"],
        ]
    cell = table["statement_BS"][0]
    data = records[cell[0]]
    assert cell[1:] == [
        data["period_id"],
        data["item_id"],
        data["line_id"],
        data["label"],
        data["line_kind"],
        data["status"],
        data["normalized_amount"],
    ]
    for row in table["gap"]:
        assert isinstance(row[5], str) and len(row[5]) <= context.TEXT_LIMIT
        assert records[row[0]]["severity"] == row[1] and records[row[0]]["origin"] == row[2]


def test_the_projections_are_deterministic_and_total_on_the_partial_case(
    outputs: Outputs, partial: Outputs
) -> None:
    for case in (outputs, partial):
        for consumer, producer in (("narrative", "financials"), ("readiness", "narrative")):
            first = context.upstream_text(consumer, producer, case[producer])
            assert first == context.upstream_text(consumer, producer, case[producer])
    stage = FinancialStage.model_validate_json(partial["financials"])
    assert stage.model is None and stage.narrative_inputs.scope == "data_quality_only"
    text = context.upstream_text("narrative", "financials", partial["financials"])
    assert "model_metrics: none" in text
    assert set(ids(evidence(text))) == {r.evidence_id for r in stage.narrative_inputs.catalogue}


def rare_records(stage: FinancialStage) -> tuple[EvidenceRecord, ...]:
    """One record of each catalogue kind the synthetic case does not produce."""
    cited = next(r for r in stage.narrative_inputs.catalogue if r.citations).citations[:1]
    rows = {
        "subsequent_event": SubsequentEvent(
            event_id="event-1",
            reporting_scope_id="FY",
            event_date=date(2026, 1, 15),
            known_on=date(2026, 1, 20),
            status="completed",
            description="Synthetic refinancing " * 12,
            effect="Synthetic effect",
            citations=cited,
        ),
        "normalization": NormalizationRow(
            normalization_id="normalization-1",
            observation_id="Q1.capex",
            period_id="Q1",
            before=Decimal("5"),
            after=Decimal("-5"),
            rationale="Synthetic sign",
            citations=cited,
        ),
        "multi_figure_event": DefinitionRow(
            row_id="definition-event",
            kind="multi_figure_event",
            status="distinct_bases",
            metric="Synthetic event",
            canonical_definition=None,
            issuer_definition=None,
            observation_ids=("Q1.capex", "Q1.revenue"),
            period_ids=("Q1",),
            roles=("a", "b"),
            explanation="Separate accounting meanings",
            materiality="Not assessed",
            downstream_impact="Keep the roles separate",
            recommendation="Review",
            citations=cited,
        ),
    }
    template = stage.narrative_inputs.catalogue[0]
    return tuple(
        template.model_copy(
            update={
                "evidence_id": f"narrative-evidence:{kind}",
                "kind": kind,
                "reference": kind,
                "record_json": row.model_dump_json(),
            }
        )
        for kind, row in rows.items()
    )


def test_every_catalogue_kind_has_a_line_and_an_unknown_kind_fails_closed(
    outputs: Outputs,
) -> None:
    stage = FinancialStage.model_validate_json(outputs["financials"])
    rare = rare_records(stage)
    catalogue = (*stage.narrative_inputs.catalogue, *rare)
    table = evidence("\n".join(context.evidence_table(catalogue)))
    assert set(table) == set(context.KINDS)  # every kind `_catalogue` emits is exercised
    event = table["subsequent_event"][0]
    assert event[:4] == [
        "narrative-evidence:subsequent_event",
        "event-1",
        "2026-01-15",
        "completed",
    ]
    assert len(event[4]) == context.TEXT_LIMIT and event[4].endswith("…")
    assert table["normalization"][0][1:] == ["Q1.capex", "Q1", "5", "-5"]
    assert table["multi_figure_event"][0][1:4] == [
        "multi_figure_event",
        "distinct_bases",
        "Synthetic event",
    ]
    stray = rare[0].model_copy(update={"kind": "mystery"})
    with pytest.raises(
        context.ProjectionError, match="no evidence line is defined for kind mystery"
    ):
        context.evidence_table((*catalogue, stray))
    misshapen = rare[1].model_copy(update={"kind": "kpi"})
    with pytest.raises(context.ProjectionError, match="does not have its kind's shape"):
        context.evidence_table((*catalogue, misshapen))
    orphan = next(r for r in catalogue if r.kind == "kpi")
    without_bases = tuple(r for r in catalogue if r.kind != "basis")
    assert orphan in without_bases
    with pytest.raises(context.ProjectionError, match="which the retained output lacks"):
        context.evidence_table(without_bases)


def test_the_readiness_projection_names_every_id_its_validator_accepts_once(
    outputs: Outputs,
) -> None:
    raw = outputs["narrative"]
    inputs = DownstreamInputs.model_validate_json(raw)
    text = context.upstream_text("readiness", "narrative", raw)
    table = evidence(text)
    shown = ids(table)
    assert set(shown.values()) == {1}
    assert set(shown) == {r.evidence_id for r in inputs.narrative.inputs.catalogue}
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("narrative_gaps: "))
    count = int(lines[start].split()[1].removeprefix("entries="))
    added = [json.loads(line)[0] for line in lines[start + 1 : start + 1 + count]]
    assert lines[start + 1 + count].startswith("evidence: ")
    gap_ids = Counter([*added, *(row[1] for row in table["gap"])])
    assert set(gap_ids.values()) == {1}
    assert set(gap_ids) == {g.gap_id for g in inputs.narrative.gaps}
    assert added  # the synthetic narrative adds unassessed-dimension gaps
    consumers = [json.loads(line) for line in lines if line.startswith('["CP-')]
    assert [c[0] for c in consumers] == [c.entry for c in inputs.consumers]
    assert [c[4] for c in consumers] == [list(c.requirements) for c in inputs.consumers]
    shown_review = next(line for line in lines if line.startswith("narrative_review: "))
    review = json.loads(shown_review.removeprefix("narrative_review: "))
    assert review == inputs.narrative.review.model_dump(mode="json", exclude={"inputs_sha256"})
    for absent in ("record_json", '"quote"', "citations", "inputs_sha256", inputs.content_hash()):
        assert absent not in text, absent
    assert len(text) <= len(raw) // 10


def test_only_steps_that_check_spans_against_the_pack_declare_its_sources() -> None:
    sources = ("filing", "deck")
    for step_id in ("source_readiness", "source_context", "financials", "business_context"):
        assert context.step_sources(step_id, sources) == sources
    for step_id in ("narrative", "readiness", "quality"):
        assert context.step_sources(step_id, sources) == ()
