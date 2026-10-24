"""Projection fidelity does not qualify the model's analytical judgments."""

import hashlib
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from deploy_vii.canonical_tables import CanonicalTables, canonical_tables, validate_canonical_tables
from deploy_vii.contracts import View
from deploy_vii.cp1_workflow import FinancialStage, cp1_register_preview, submit_cp1_step
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview, downstream_inputs
from deploy_vii.narrative import (
    DimensionCoverage,
    EvidencePart,
    IssuerPart,
    NarrativeInputs,
    NarrativeReview,
    ProsePart,
    StoryCoverage,
    canonical_narrative,
    narrative_inputs,
)
from deploy_vii.narrative_projection import _fields, project_narrative
from deploy_vii.prose import bind
from deploy_vii.report_view import resolve
from tests.product.evidence import evidence_path
from tests.product.oracle import expected_by_fact
from tests.product.test_canonical_gaps import case
from tests.product.test_canonical_tables import cells
from tests.product.test_execution import step_text
from tests.product.test_financials import book
from tests.product.test_model_readiness import ready_case
from tests.product.test_narrative import finding, populated
from tests.product.test_source_context import event_case
from tests.product.test_statements import line
from tests.product.test_workflow import cp1_case


def supplied(inputs: NarrativeInputs) -> NarrativeReview:
    entry = next(r for r in inputs.catalogue if r.kind == "observation")
    value = finding(inputs, entry.evidence_id).model_copy(
        update={
            "dimension": "data_quality",
            "evidence": (
                ProsePart(text="The cited position for "),
                IssuerPart(),
                ProsePart(text=" is retained in "),
                EvidencePart(evidence_id=entry.evidence_id),
            ),
            "risk_mechanic": (
                ProsePart(
                    text="Source labels <script>window.injected=true</script> "
                    "and <img src=https://example.invalid onerror=window.injected=true> "
                    "remain quoted evidence. " * 12
                ),
                EvidencePart(evidence_id=entry.evidence_id),
            ),
        }
    )
    return populated(inputs, value).model_copy(
        update={
            "coverage": (
                DimensionCoverage(
                    dimension="data_quality",
                    status="addressed",
                    finding_ids=(value.finding_id,),
                    rationale=(
                        ProsePart(text="This covers the cited scope"),
                        EvidencePart(evidence_id=entry.evidence_id),
                    ),
                ),
            ),
        }
    )


@pytest.fixture(scope="module")
def report() -> CanonicalTables:
    args = case(ready_case())
    review = supplied(narrative_inputs(*args))
    inputs = downstream_inputs(*args, review, ())
    return canonical_tables(
        *args, review, (), DownstreamReview(inputs_sha256=inputs.content_hash())
    )


def test_findings_preserve_order_issuer_binding_and_exact_evidence_trace(
    report: CanonicalTables,
) -> None:
    original = report.downstream.inputs.narrative
    finding_row = original.review.findings[0]
    claim = report.module.claims[0]
    record = next(
        r
        for r in original.inputs.catalogue
        if r.evidence_id == finding_row.evidence[-1].evidence_id
    )
    trace = cells(report, "evidence-trace")
    row = next(r for r in trace if r["Evidence ID"].text == record.evidence_id)
    # Claim text references the trace row's Evidence cell; Python resolves it to its E# label.
    assert f"[{row['Evidence'].fact_id}]" in claim.text
    plain = "".join(run.text for run in resolve(claim.text, bind(report.module.facts), {}))
    assert f"is retained in {row['Evidence'].text}" in plain
    assert "Evidence\nThe cited position for Synthetic is retained" in claim.text
    assert (
        claim.text.index("Evidence\n")
        < claim.text.index("Risk mechanic\n")
        < claim.text.index("Credit implication\n")
    )
    assert claim.citations == record.citations
    assert row["Artifact SHA256"].text == record.artifact_sha256
    assert row["Record SHA256"].text == hashlib.sha256(record.record_json.encode()).hexdigest()
    assert row["Fields"].text == "\n".join(_fields(json.loads(record.record_json)))
    assert f"{finding_row.finding_id}/evidence" in row["Used By"].text
    assert f"{finding_row.finding_id}/risk_mechanic" in row["Used By"].text
    assert "coverage/data_quality" in row["Used By"].text
    assert len(trace) == 1  # Repeated uses do not duplicate the prior record.
    assert report.module.status == "candidate" and "unrun" in claim.limitation
    assert all("Narrative: " + note in report.module.limitations for note in original.limitations)


def test_record_fields_keep_precision_null_types_paths_and_empty_containers() -> None:
    result = tuple(_fields({"a/b~c": ["1.2300", None, "null", False, [], {}], "text": "a\nb"}))
    assert result == (
        '/a~1b~0c/0 = "1.2300"',
        "/a~1b~0c/1 = null",
        '/a~1b~0c/2 = "null"',
        "/a~1b~0c/3 = false",
        "/a~1b~0c/4 = []",
        "/a~1b~0c/5 = {}",
        '/text = "a\\nb"',
    )


def test_unassessed_dimensions_and_funding_do_not_become_complete(report: CanonicalTables) -> None:
    coverage = cells(report, "analysis-coverage")
    assert len(coverage) == 7
    assert [r["Dimension"].text for r in coverage if r["Status"].text == "addressed"] == [
        "data_quality"
    ]
    assert sum(r["Status"].text == "unassessed" for r in coverage) == 6
    assert cells(report, "funding-assessment")[0]["Status"].text == "unassessed"
    assert report.downstream.inputs.narrative.gaps
    for row in cells(report, "statement-coverage"):
        if row["Period"].text == "OPEN" and row["Statement"].text != "BS":
            assert row["Supplied Lines"].text == "0"
            assert row["Scope"].text == "Point-in-time period; flow statement not applicable"


def test_statement_coverage_preserves_missing_required_scope() -> None:
    value = book()
    revenue = next(
        a.value.amount for a in value.accounts if a.period_id == "Q2" and a.metric_id == "revenue"
    )
    value = value.model_copy(
        update={"statement_lines": (line("given", "revenue", str(revenue), 1, statement="IS"),)}
    )
    args = case(value)
    narrative = canonical_narrative(*args, supplied(narrative_inputs(*args)))
    projection = project_narrative(value, narrative, args[0].run.issuer_name)
    facts = {f.fact_id: f for f in projection.facts}
    layout = next(t for t in projection.tables if t.table_id == "statement-coverage")
    rows = [
        dict(zip((c.field for c in layout.columns), (facts[i] for i in r.fact_ids), strict=True))
        for r in layout.rows
    ]
    row = next(r for r in rows if r["statement"].text == "IS" and r["supplied_lines"].text == "1")
    assert "cogs" in row["missing_required"].text
    assert "unqualified" in row["scope"].text
    assert all(
        r["scope"].text == "Declared extraction only; filing completeness is unqualified"
        for r in rows
    )


def test_required_event_trace_remains_when_story_missing_then_binds_supplied_story() -> None:
    pack, context, financial, definition, binding = case()
    _, event_context = event_case()
    context = context.model_copy(
        update={
            "events": event_context.events,
            "sources": (
                context.sources[0].model_copy(
                    update={
                        "event_scan": "events_identified",
                        "event_ids": (event_context.events[0].event_id,),
                    }
                ),
            ),
        }
    )
    binding = binding.model_copy(update={"source_context_review_sha256": context.content_hash()})
    args = pack, context, financial, definition, binding
    inputs = narrative_inputs(*args)
    review = supplied(inputs)
    original = canonical_narrative(*args, review)
    identity = next(r.evidence_id for r in inputs.catalogue if r.kind == "subsequent_event")
    projected = project_narrative(financial.books[0], original, pack.run.issuer_name)
    assert any(f.text == identity and f.table_id == "evidence-trace" for f in projected.facts)
    assert any(f.text == "missing" and f.table_id == "required-stories" for f in projected.facts)
    assert any(g.reference == identity and g.severity == "BLOCK" for g in original.gaps)
    linked = populated(inputs, finding(inputs, identity)).model_copy(
        update={
            "stories": (StoryCoverage(evidence_id=identity, finding_ids=("liquidity",)),),
        }
    )
    changed = project_narrative(
        financial.books[0], canonical_narrative(*args, linked), pack.run.issuer_name
    )
    assert any(f.text == "supplied" and f.table_id == "required-stories" for f in changed.facts)
    fields = next(
        f.text for f in changed.facts if f.table_id == "evidence-trace" and f.field == "fields"
    )
    assert "event_date" in fields and "excluded" in fields


def test_new_canonical_report_rejects_previous_explicit_schema(report: CanonicalTables) -> None:
    with pytest.raises(ValueError, match="canonical-tables/2"):
        CanonicalTables.model_validate_json(
            report.model_copy(update={"schema_version": "canonical-tables/1"}).model_dump_json()
        )


@pytest.mark.browser
@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 800)])
def test_narrative_preview_offline_exact_claims_and_provenance(
    tmp_path: Path, width: int, height: int
) -> None:
    store, ticket, extraction = cp1_case(tmp_path, partial=True)
    financial = submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    output = FinancialStage.model_validate_json(step_text(store, financial.steps[-1]))
    narrative = submit_cp1_step(
        store, ticket.ticket_id, "narrative", supplied(output.narrative_inputs).model_dump_json()
    )
    inputs = DownstreamInputs.model_validate_json(step_text(store, narrative.steps[-1]))
    submit_cp1_step(
        store,
        ticket.ticket_id,
        "readiness",
        DownstreamReview(inputs_sha256=inputs.content_hash()).model_dump_json(),
    )
    before = store.read().content_hash()
    path = cp1_register_preview(store, ticket.ticket_id, tmp_path / "preview")
    assert store.read().content_hash() == before
    view = View.model_validate_json((path.parent / "view.json").read_bytes())
    module = next(m for m in view.modules if m.module_id == "CP-1")
    claim = module.claims[0]
    markdown = (path.parent / "tables.md").read_text()
    # The preview prints resolved run text (task 6.4), never the raw [<fact id>] chips.
    from deploy_vii.envelope import resolved_claims
    from deploy_vii.report_view import build_index

    ((line, _),) = resolved_claims(module, build_index(view)[1], (view.run.issuer_name,))
    assert line in markdown.split("\n") and "interface-fact:" not in line
    assert claim.claim_id in line
    assert "<script>window.injected" not in markdown and "<img src" not in markdown
    evidence = evidence_path("narrative-projection", tmp_path)
    evidence.mkdir(parents=True)
    for name in ("view.json", "tables.md", "complete.json", "candidate.html"):
        (evidence / name).write_bytes((path.parent / name).read_bytes())
    errors, requests = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, offline=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.goto(path.as_uri() + "#CP-1")
        block = page.locator(f'[data-claim-id="{claim.claim_id}"]')
        # The claim is drawn from its resolved runs; provenance glyph titles are not text.
        shown = block.locator("p").evaluate(
            "n => { const c = n.cloneNode(true);"
            " c.querySelectorAll('svg').forEach(s => s.remove()); return c.textContent; }"
        )
        assert shown == "".join(run.text for run in resolve(claim.text, bind(module.facts), {}))
        assert "[" not in shown and "{" not in shown
        assert page.evaluate("window.injected === undefined")
        oracle = expected_by_fact(view)
        assert dict(
            page.locator("[data-fact-id]").evaluate_all(
                "nodes => nodes.map(n => [n.dataset.factId,n.textContent])"
            )
        ) == {f.fact_id: oracle[f.fact_id] for f in module.facts}
        inspect = block.get_by_role("button", name="Inspect supporting evidence")
        inspect.focus()
        page.keyboard.press("Enter")
        inspector = page.get_by_role("complementary", name="Evidence inspector")
        expect(inspector).to_contain_text(claim.citations[0].source_sha256)
        expect(inspector).to_contain_text(module.artifact_sha256)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(evidence / f"narrative-{width}x{height}.png"))
        page.evaluate("document.body.style.zoom='1.25'")
        inspect.scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(evidence / "zoom.png"))
        assert not errors and not [r for r in requests if r.startswith(("https:", "http:"))]
        (evidence / "checks.json").write_text(
            json.dumps(
                {
                    "viewport": [width, height],
                    "claims_and_fields": "passed",
                    "errors": errors,
                    "requests": requests,
                    "analytical_qualification": "unrun",
                }
            )
        )
        browser.close()


def test_altered_claim_is_rejected_by_external_recomputation() -> None:
    value = book()
    value = value.model_copy(
        update={
            "addback_disclosure": value.addback_disclosure.model_copy(update={"status": "partial"})
        }
    )
    args = case(value)
    narrative = supplied(narrative_inputs(*args))
    downstream = downstream_inputs(*args, narrative, ())
    review = DownstreamReview(inputs_sha256=downstream.content_hash())
    inputs = (*args, narrative, (), review)
    report = canonical_tables(*inputs)
    changed = report.model_copy(
        update={
            "module": report.module.model_copy(
                update={
                    "claims": (
                        report.module.claims[0].model_copy(
                            update={"text": "Unsupported replacement"}
                        ),
                    )
                }
            )
        }
    )
    assert validate_canonical_tables(*inputs, changed) == (
        "Canonical registers differ from trusted external recomputation",
    )


def test_material_funding_trace_keeps_roles_and_statement_dimensions() -> None:
    from deploy_vii.narrative import FundingAssessment

    value = book().model_copy(
        update={
            "statement_lines": (
                line("deposit", "other:customer_deposits", "20.00", 1, statement="BS"),
            )
        }
    )
    args = case(value)
    inputs = narrative_inputs(*args)
    record = next(
        r
        for r in inputs.catalogue
        if r.kind == "statement_BS" and '"line_id":"deposit"' in r.record_json
    )
    review = supplied(inputs).model_copy(
        update={
            "funding": FundingAssessment(
                status="material_items",
                reviewed_statement_ids=(record.evidence_id,),
                material_statement_ids=(record.evidence_id,),
                rationale=(ProsePart(text="The named liability needs its own credit story"),),
            )
        }
    )
    narrative = canonical_narrative(*args, review)
    projected = project_narrative(value, narrative, args[0].run.issuer_name)
    identity = next(
        f
        for f in projected.facts
        if f.table_id == "evidence-trace"
        and f.field == "evidence_id"
        and f.text == record.evidence_id
    )
    row = {
        f.field: f
        for f in projected.facts
        if f.table_id == "evidence-trace" and f.row_id == identity.row_id
    }
    assert all(
        role in row["used_by"].text
        for role in ("funding/reviewed", "funding/material", "required-story")
    )
    assert '/normalized_amount = "20.00"' in row["fields"].text
    assert row["fields"].unit == "MILLIONS" and row["fields"].currency == "USD"
    assert "Q2:" in row["fields"].period and "2025-06-30" in row["fields"].period
    assert row["fields"].citations == record.citations
    assert any(g.reference == record.evidence_id and g.severity == "BLOCK" for g in narrative.gaps)
