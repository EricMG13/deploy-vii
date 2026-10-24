"""Decision 0008 (MC-1): the model returns judgments and quotes; Python composes the review."""

import dataclasses
import hashlib
import json
import re
import shutil
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from deploy_vii.canonical_audit import DefinitionReview
from deploy_vii.context_binding import FinancialContextBinding
from deploy_vii.contracts import Contract, Source, Span
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_workflow import (
    PROMOTED,
    FinancialStage,
    FinancialSubmission,
    cp1_registers,
    submit_cp1_step,
)
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview
from deploy_vii.execution import Attempt, Execution, StepSubmission, StepValidation
from deploy_vii.financial_contracts import FinancialBook, FinancialReview
from deploy_vii.financial_validation import validate_financial_review
from deploy_vii.live.schema import (
    PREFILLED_MARKER,
    marked_fields,
    strict_schema,
    unverified_keywords,
)
from deploy_vii.live.submission import (
    NOT_ASSESSED,
    PREFILLED,
    STEPS,
    SUPERSEDED_SHAPE,
    ConsumerJudgment,
    Known,
    ReadinessSubmission,
    StepDef,
    SubmittedCitation,
    compose,
    compose_payload,
    known_bindings,
    prefill,
    rejection_issues,
    submit_model_payload,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.quality import QualityInputs, QualityReview
from deploy_vii.readiness import (
    absent_page_ranges,
    coverage_issues,
    extraction_coverage,
    live_consumers,
    validate_review,
)
from deploy_vii.source_context import (
    ReportingScope,
    SourceContextReview,
    validate_source_context,
)
from tests.product.test_readiness import as_submission, readiness_fixture, submission_fixture

FIXTURES = Path(__file__).parent / "fixtures" / "live"
EN_DASH = chr(0x2013)  # GLM draw 3 wrote ranges with an en dash


def nodes(node: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found += nodes(value)
    elif isinstance(node, list):
        for item in node:
            found += nodes(item)
    return found


def test_the_submission_is_the_model_facing_shape_of_source_readiness() -> None:
    assert STEPS["source_readiness"].schema is ReadinessSubmission
    assert STEPS["source_readiness"].module_id == "CP-0"


def test_the_submission_schema_is_strict_safe_and_carries_no_mechanical_field() -> None:
    schema = strict_schema(ReadinessSubmission)
    # Nothing to make nullable (no defaults) and plain strings, enums, arrays and objects only,
    # except task 2.10's `minItems: 1` on `analysis`, whose strict-mode acceptance is undocumented.
    assert unverified_keywords(schema) == ["minItems"]
    for node in nodes(schema):
        assert "default" not in node
        if "properties" in node:
            assert node["required"] == list(node["properties"])
            assert node["additionalProperties"] is False
    text = json.dumps(schema)
    for mechanical in ("sha256", "pack_sha256", "source_ids", "schema_version"):
        assert f'"{mechanical}"' not in text


def test_composition_round_trips_the_fixture_review_and_its_hash() -> None:
    pack, review = readiness_fixture()
    composition = compose(pack, as_submission(review))
    assert composition.issues == () and composition.placeholders == ()
    assert composition.review == review
    assert composition.review.content_hash() == review.content_hash()
    assert composition.review.pack_sha256 == pack.content_hash()


def test_hashes_and_attachment_sets_come_from_python_not_the_model() -> None:
    pack, submission = submission_fixture()
    consumer = submission.consumers[0]
    citation = consumer.citations[0]
    twice = consumer.model_copy(update={"citations": (citation, citation)})
    changed = submission.model_copy(update={"consumers": (twice, *submission.consumers[1:])})
    review = compose(pack, changed).review
    assert review is not None
    (source,) = pack.sources
    assert review.consumers[0].source_ids == ("filing",)  # distinct cited sources, in order
    assert {c.source_sha256 for c in review.consumers[0].citations} == {source.sha256}
    uncited = consumer.model_copy(
        update={"citations": (), "readiness": "BLOCKED", "missing_source": None}
    )
    blocked = submission.model_copy(update={"consumers": (uncited, *submission.consumers[1:])})
    composed = compose(pack, blocked).review
    assert composed is not None and composed.consumers[0].source_ids == ()


def test_an_omitted_consumer_becomes_a_blocked_placeholder_with_a_critical_gap() -> None:
    pack, submission = submission_fixture()
    dropped = submission.consumers[-1].module_id
    trimmed = submission.model_copy(update={"consumers": submission.consumers[:-1]})
    composition = compose(pack, trimmed)
    review = composition.review
    assert review is not None and composition.issues == ()
    assert composition.placeholders == (f"consumer:{dropped}",)
    placeholder = review.consumers[-1]
    assert placeholder.module_id == dropped and placeholder.readiness == "BLOCKED"
    assert placeholder.limitations == (NOT_ASSESSED,) and placeholder.source_ids == ()
    gap = review.gaps[-1]
    assert gap.gap_id == f"not-assessed.{dropped}" and gap.severity == "critical"
    assert gap.affected_modules == (dropped,)
    # Existing validator semantics decide: here the review stands, with the consumer blocked.
    assert validate_review(pack, review) == ()


def test_an_omitted_ready_source_is_never_ready_and_the_validator_rejects_it() -> None:
    pack, submission = submission_fixture()
    composition = compose(pack, submission.model_copy(update={"sources": ()}))
    review = composition.review
    assert review is not None and composition.placeholders == ("source:filing",)
    (placeholder,) = review.sources
    assert placeholder.fidelity == "blocked" and placeholder.limitations == (NOT_ASSESSED,)
    assert any(gap.gap_id == "not-assessed.filing" for gap in review.gaps)
    issues = validate_review(pack, review)
    assert "Source classification must cite content: filing" in issues


def test_an_omitted_unavailable_source_is_accepted_with_its_gap() -> None:
    pack, submission = submission_fixture()
    missing = Source(source_id="indenture", name="Indenture", status="missing", limitation="nil")
    bigger = pack.model_copy(update={"sources": (*pack.sources, missing)})
    blocked = tuple(
        item.model_copy(update={"readiness": "READY_WITH_LIMITATIONS"})
        for item in submission.consumers
    )
    composition = compose(bigger, submission.model_copy(update={"consumers": blocked}))
    assert composition.placeholders == ("source:indenture",)
    assert composition.review is not None
    assert validate_review(bigger, composition.review) == ()


@given(st.sets(st.sampled_from(live_consumers(readiness_fixture()[0]))))
def test_every_live_consumer_is_composed_exactly_once_and_omissions_never_run(
    omitted: set[str],
) -> None:
    pack, submission = submission_fixture()
    kept = tuple(item for item in submission.consumers if item.module_id not in omitted)
    review = compose(pack, submission.model_copy(update={"consumers": kept})).review
    assert review is not None
    assert sorted(item.module_id for item in review.consumers) == sorted(live_consumers(pack))
    for item in review.consumers:
        if item.module_id in omitted:
            assert item.readiness == "BLOCKED" and item.limitations == (NOT_ASSESSED,)


def test_duplicates_and_extras_are_kept_for_the_validator_to_reject() -> None:
    pack, submission = submission_fixture()
    extra = submission.consumers[0].model_copy(update={"module_id": "CP-0"})
    composed = compose(
        pack,
        submission.model_copy(
            update={
                "consumers": (*submission.consumers, extra),
                "sources": submission.sources * 2,
            }
        ),
    )
    assert composed.review is not None and composed.placeholders == ()
    issues = validate_review(pack, composed.review)
    assert "Assess every prepared source exactly once" in issues
    assert "Assess each selected canonical live consumer exactly once" in issues


def test_a_citation_of_the_context_block_cannot_be_bound_and_rejects_the_submission() -> None:
    pack, submission = submission_fixture()
    context = SubmittedCitation(source_id="prepared-pack", locator="run", quote="FY2025")
    claim = submission.analysis[0]
    cited = claim.model_copy(update={"citations": (*claim.citations, context)})
    changed = submission.model_copy(update={"analysis": (cited,)})
    composition = compose(pack, changed)
    assert composition.issues == ("Unavailable or changed source: prepared-pack",)
    assert composition.review is not None  # the bindable rest still meets the validator
    original = compose(pack, submission).review
    assert original is not None
    assert composition.review.analysis[0].citations == original.analysis[0].citations
    payload = changed.model_dump_json()
    assert rejection_issues(pack, payload) == ("Unavailable or changed source: prepared-pack",)


def test_locators_are_matched_exactly_so_bracketed_copies_are_rejected() -> None:
    pack, submission = submission_fixture()
    claim = submission.analysis[0]
    bracketed = claim.citations[0].model_copy(update={"locator": "[line:1]"})
    changed = submission.model_copy(
        update={"analysis": (claim.model_copy(update={"citations": (bracketed,)}),)}
    )
    composition = compose(pack, changed)
    assert composition.issues == () and composition.review is not None
    assert validate_review(pack, composition.review) == (
        'Quote/locator mismatch: no locator [line:1] in filing: "Synthetic issuer FY2025 cash USD '
        'million 0"',
    )


def test_payloads_that_cannot_be_composed_say_why() -> None:
    pack, review = readiness_fixture()
    # The stored contract (pre-0008 shape): it binds the pack itself.
    assert compose_payload(pack, review.model_dump_json()).issues == (SUPERSEDED_SHAPE,)
    assert rejection_issues(pack, review.model_dump_json()) == (SUPERSEDED_SHAPE,)
    assert compose_payload(pack, "not json").issues[0].startswith("(root): Invalid JSON")
    _, submission = submission_fixture()
    document = json.loads(submission.model_dump_json())
    del document["consumers"]
    assert compose_payload(pack, json.dumps(document)).issues == ("consumers: Field required",)
    # A composed review that breaks a stored-contract rule reports the short Pydantic form.
    unlimited = tuple(item.model_copy(update={"limitations": ()}) for item in submission.consumers)
    issues = compose_payload(
        pack, submission.model_copy(update={"consumers": unlimited}).model_dump_json()
    ).issues
    assert issues[0] == "consumers.0: Value error, non-ready consumer requires limitations"
    assert rejection_issues(pack, submission.model_dump_json()) == ()


def test_identifiers_are_enforced_on_the_composed_review() -> None:
    pack, submission = submission_fixture()
    bad = ConsumerJudgment(
        **{**submission.consumers[0].model_dump(), "module_id": "not an id", "citations": ()}
    )
    issues = compose(pack, submission.model_copy(update={"consumers": (bad,)})).issues
    assert any(issue.startswith("consumers.0.module_id: String should match") for issue in issues)


# --- extraction coverage (decision 0008 item 1, last bullet) -------------------------------


def paged_pack(pages: range, source_id: str = "czr-2025-10k") -> PreparedPack:
    pack, _ = readiness_fixture()
    spans = tuple(Span(locator=f"page:{n}", text=f"Page {n} text") for n in pages)
    digest = hashlib.sha256("".join(span.text for span in spans).encode()).hexdigest()
    source = Source(
        source_id=source_id,
        name="FY2025 Form 10-K",
        status="ready",
        sha256=digest,
        spans=spans,
        limitation="PDF text/layout extracted only",
    )
    return pack.model_copy(update={"sources": (source,)})


def test_extraction_coverage_states_first_last_count_and_gaps() -> None:
    whole = extraction_coverage(paged_pack(range(1, 196)).sources[0])
    assert whole == {
        "located_spans": 195,
        "first_locator": "page:1",
        "last_locator": "page:195",
        "coverage_not_retained": [],
        "pages_missing_between_first_and_last": [],
    }
    holed = paged_pack(range(1, 196)).sources[0]
    kept = tuple(span for span in holed.spans if not 12 <= int(span.locator[5:]) <= 180)
    record = extraction_coverage(holed.model_copy(update={"spans": kept}))
    assert record["pages_missing_between_first_and_last"] == ["page:12 to page:180"]
    assert record["located_spans"] == 26
    lines = extraction_coverage(readiness_fixture()[0].sources[0])
    assert (
        lines["first_locator"] == "line:1" and "pages_missing_between_first_and_last" not in lines
    )


def glm_draw_1() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        (FIXTURES / "glm-draw-1-absence-claims.json").read_text(encoding="utf-8")
    )
    return document


def glm_submission(pack: PreparedPack) -> ReadinessSubmission:
    """GLM draw 1's absence claims (verbatim) in a submission over a pack holding pages 1-195."""
    draw = glm_draw_1()
    _, base = submission_fixture()
    cite = SubmittedCitation(source_id="czr-2025-10k", locator="page:3", quote="Page 3")
    source = base.sources[0].model_copy(
        update={
            "source_id": "czr-2025-10k",
            "fidelity": "degraded",
            "citations": (cite,),
            "limitations": tuple(draw["source_limitations"]),
        }
    )
    consumers = []
    for item in base.consumers:
        judged = draw["consumers"].get(item.module_id)
        update: dict[str, Any] = {"citations": (cite,)}
        if judged:
            update |= {
                "readiness": judged["readiness"],
                "limitations": tuple(judged["limitations"]),
                "missing_source": judged["missing_source"],
            }
        consumers.append(item.model_copy(update=update))
    gap = base.gaps[0].model_copy(
        update={"description": draw["gap_description"], "citations": (cite,)}
    )
    claim = base.analysis[0].model_copy(
        update={"citations": (cite,), "limitation": draw["claim_limitation"]}
    )
    return base.model_copy(
        update={
            "sources": (source,),
            "consumers": tuple(consumers),
            "gaps": (gap,),
            "analysis": (claim,),
        }
    )


def test_glm_draw_1_absence_claims_are_rejected_against_a_pack_that_holds_the_pages() -> None:
    pack = paged_pack(range(1, 196))
    review = compose(pack, glm_submission(pack)).review
    assert review is not None
    found = coverage_issues(pack, review)
    claimed = {issue.split(": ", 1)[1].split(" retained")[0] for issue in found}
    assert claimed == {
        "page:53 to page:96",  # CP-1 missing_source
        "page:33 to page:52",  # CP-1A limitation and missing_source
        "page:16 to page:28",  # CP-5 missing_source and the gap
        "page:12 to page:180",  # the claim's limitation
    }
    assert all(issue.endswith("retained in czr-2025-10k") for issue in found)
    assert set(found) <= set(validate_review(pack, review))
    # "covers only pages 1-11 and 181-195" names no absent range; "(pages 186-189)" is present.
    assert absent_page_ranges(glm_draw_1()["source_limitations"][1]) == ()


def test_absence_claims_stand_when_the_pack_lacks_the_pages() -> None:
    present = [n for n in range(1, 196) if not 12 <= n <= 180]
    pack = paged_pack(range(1, 196))
    holed = pack.sources[0].model_copy(
        update={"spans": tuple(s for s in pack.sources[0].spans if int(s.locator[5:]) in present)}
    )
    pack = pack.model_copy(update={"sources": (holed,)})
    review = compose(pack, glm_submission(pack)).review
    assert review is not None
    assert coverage_issues(pack, review) == ()


@pytest.mark.parametrize(
    "text, ranges",
    [
        (f"pages 12{EN_DASH}180 of the tagged sequence are absent", ((12, 180),)),
        ("Missing extracted text of 10-K pages 13-180 (includes Item 1A)", ((13, 180),)),
        ("jumps from page 12 to page 181", ()),  # no absence word: not a claim of absence
        ("pages 33 to 52 were not delivered", ((33, 52),)),
        ("pages 52-33 are absent", ()),  # a reversed range is not a range
        ("Exhibit 97.1 is available in the excerpt (pages 186-189)", ()),
        # Content looked for on retained pages is a judgment, not a claim the pages are absent.
        ("Segment EBITDA reconciliation is missing from pages 40-60", ()),
        ("The lease maturity table is not included in the 10-K pages 100-110", ()),
        ("Item 1A text absent from supplied extraction (pages 16-28)", ((16, 28),)),
    ],
)
def test_absent_page_ranges(text: str, ranges: tuple[tuple[int, int], ...]) -> None:
    assert absent_page_ranges(text) == ranges


# Probe-3 limitation texts, verbatim (task 2.9 fix 2): two rule-f-compliant statements of full
# coverage the validator rejected, and the GLM source_context absence claim it did not check.
LUNA_F136B227_LIMITATION = (
    "The located coverage lists pages 1 through 195 with no pages missing between the first and "
    "last locator; no page-absence limitation is asserted."
)
GLM_76FC5C95_LIMITATION = (
    "Pack metadata flags extraction_status 'degraded': coverage is complete (195 located spans, "
    "page:1 through page:195, no pages missing between first and last), but extracted text "
    "fidelity is not verified and complex tables/financial statement pages may be misaligned."
)
# The same attempt's gap description: the identical issue text was deduplicated, so the live
# validator listed one absence issue for both.
GLM_76FC5C95_GAP = (
    "The pack's sole source (czr-2025-10k, 195 pages) has extraction_status 'degraded'. Coverage "
    "is complete (page:1 through page:195, no missing pages between first and last, 195 located "
    "spans), so no content is absent, but text fidelity is not verified. Complex tables "
    f"{chr(0x2014)} e.g., the collective bargaining summary on page 10 and the Item 8 financial "
    f"statements (pages 53-96) {chr(0x2014)} are the highest risk for misaligned columns, split "
    "rows, or garbled numerals."
)
GLM_F0391C45_LIMITATION = (
    "Extraction is flagged as degraded for this source; supplied spans are page-level excerpts "
    "and the financial statements (Item 8, pages 53-96) are absent from the supplied evidence, "
    "preventing confirmation of statement units, currency presentation, or comparative-period "
    "coverage."
)


@pytest.mark.parametrize(
    "text",
    [
        LUNA_F136B227_LIMITATION,
        GLM_76FC5C95_LIMITATION,
        GLM_76FC5C95_GAP,
        "pages 1-195 retained, none missing",
        "pages 1-195 retained and none are missing",
        "pages 1 to 195 are not missing",
        "pages 1-195 with nothing omitted",
        "page:1 to page:195, no missing pages",
        "pages 1-195; no other pages are absent",
        "pages 1-195 are present, with no pages missing between them",
        "pages 1-195 retained; none of the pages are missing",
        "pages 1-195 retained with no other pages actually absent",
        # Restating the CONTEXT block's coverage field.
        "page:1 to page:195, pages_missing_between_first_and_last: []",
        "page:1 to page:195 (pages missing between first and last: none)",
    ],
)
def test_negated_and_restated_coverage_is_not_an_absence_claim(text: str) -> None:
    assert absent_page_ranges(text) == ()


@pytest.mark.parametrize(
    ("text", "ranges"),
    [
        (GLM_F0391C45_LIMITATION, ((53, 96),)),
        ("pages 53-96 are absent", ((53, 96),)),
        ("pages 53-96 are absent and no other pages are missing", ((53, 96),)),
        ("pages 33-52 not present and also missing", ((33, 52),)),
        ("no reason is given, but pages 33-52 are missing", ((33, 52),)),
        ("the extraction is not complete with missing pages 53-96", ((53, 96),)),
        ("none of pages 53-96 are missing", ((53, 96),)),  # conservative: a range in between
        ("nothing explains why pages 53-96 are absent", ((53, 96),)),
        ("pages 12-180: missing", ((12, 180),)),
        ("page:12 to page:180 are not missing from the index but absent", ((12, 180),)),
    ],
)
def test_positive_absence_claims_still_count(
    text: str, ranges: tuple[tuple[int, int], ...]
) -> None:
    assert absent_page_ranges(text) == ranges


def test_probe_3_full_coverage_statements_pass_and_the_absence_claim_fails() -> None:
    pack = paged_pack(range(1, 196))
    _, base = submission_fixture()
    source = base.sources[0].model_copy(
        update={
            "source_id": "czr-2025-10k",
            "fidelity": "degraded",
            "citations": (
                SubmittedCitation(source_id="czr-2025-10k", locator="page:3", quote="Page 3"),
            ),
        }
    )
    for text, expected in (
        (LUNA_F136B227_LIMITATION, ()),
        (GLM_76FC5C95_LIMITATION, ()),
        (
            GLM_F0391C45_LIMITATION,
            (
                "Absence claim contradicts extraction coverage: page:53 to page:96 retained in "
                "czr-2025-10k",
            ),
        ),
    ):
        changed = base.model_copy(
            update={"sources": (source.model_copy(update={"limitations": (text,)}),)}
        )
        review = compose(pack, changed).review
        assert review is not None
        assert coverage_issues(pack, review) == expected


def test_an_absence_claim_about_a_source_without_page_locators_is_not_judged() -> None:
    pack, review = readiness_fixture()  # a line-located text source
    consumer = review.consumers[0].model_copy(
        update={"limitations": ("pages 1-2 are absent from the supplied text",)}
    )
    changed = review.model_copy(update={"consumers": (consumer, *review.consumers[1:])})
    assert coverage_issues(pack, changed) == ()


# --- task 7.0i: the model supplies no hash; Python fills every CP-1 binding (MC-1) ----------

CP1 = ("source_context", "financials", "narrative", "readiness")
ZERO = "0" * 64
NOT_BOUND = "Financial extraction does not bind the retained source step"


def journal_at(tmp_path: Path, step_id: str) -> tuple[Execution, str, Contract]:
    """A CP-1 ticket whose earlier steps are retained valid, and the valid stored contract that
    Python builds for `step_id` (every binding right)."""
    # Imported here: these fixtures reach this module through test_source_context.
    from tests.product.replay_support import PACKS, cp1_seed_payloads
    from tests.product.test_narrative import draft
    from tests.product.test_workflow import cp1_case

    if step_id == "source_context":
        store, ticket = PACKS["synthetic-cp1"](tmp_path)
        seed = cp1_seed_payloads(tmp_path / "seed")["source_context"]
        return store, ticket.ticket_id, SourceContextReview.model_validate_json(seed)
    store, ticket, extraction = cp1_case(tmp_path)
    if step_id == "financials":
        return store, ticket.ticket_id, extraction
    finances = submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    stage = FinancialStage.model_validate_json(output_of(store, finances.steps[-1]))
    narrative = draft(stage.narrative_inputs)
    if step_id == "narrative":
        return store, ticket.ticket_id, narrative
    held = submit_cp1_step(store, ticket.ticket_id, "narrative", narrative.model_dump_json())
    inputs = DownstreamInputs.model_validate_json(output_of(store, held.steps[-1]))
    return store, ticket.ticket_id, DownstreamReview(inputs_sha256=inputs.content_hash())


def output_of(store: Execution, step: StepSubmission) -> str:
    assert step.status == "valid" and step.output_sha256 is not None, step.issues
    return store.step_output(step.output_sha256)


def retained(store: Execution, ticket_id: str) -> str:
    attempt = next(a for a in store.read().attempts if a.ticket_id == ticket_id)
    return store.payload(attempt.steps[-1].payload_sha256)


def without_bindings(
    model: type[Contract], value: Contract, *, keep: frozenset[str] = frozenset()
) -> tuple[str, tuple[str, ...]]:
    """`value` as its sent schema lets a model write it (every marked binding left out, except
    those of a kind in `keep`), and the paths of the bindings left out."""
    document = json.loads(value.model_dump_json())
    marked = [item for item in marked_fields(model, document) if item.kind not in keep]
    for item in marked:
        del item.holder[item.name]
    return json.dumps(document), tuple(item.path for item in marked)


# A bare `FinancialReview` names no bound entity (the binding is the submission's), so Python
# cannot fill its dimension strings: the book-scoped hash tests keep them as the model sent them.
BOOK_ONLY = frozenset({"scope-dimension"})


def known_for(pack: PreparedPack) -> Known:
    ready = {s.source_id: s.sha256 for s in pack.sources if s.status == "ready" and s.sha256}
    return Known(pack_sha256=pack.content_hash(), sources=ready, step={})


@pytest.mark.parametrize("step_id", CP1)
def test_a_payload_without_any_hash_is_bound_by_python_and_accepted(
    tmp_path: Path, step_id: str
) -> None:
    store, ticket_id, value = journal_at(tmp_path, step_id)
    model = STEPS[step_id].schema
    payload, paths = without_bindings(model, value)
    assert paths and "sha256" not in payload  # nothing is left for the model to copy
    submitted = submit_model_payload(store, ticket_id, step_id, payload)
    step = submitted.journal.steps[-1]
    assert (step.step_id, step.status) == (step_id, "valid"), step.issues
    assert sorted(submitted.prefilled) == sorted(paths)
    assert retained(store, ticket_id) == submitted.payload
    assert model.model_validate_json(submitted.payload) == value


def test_the_bindings_filled_per_step_are_the_ones_its_validators_check(tmp_path: Path) -> None:
    kinds = {}
    for step_id in CP1:
        _, _, value = journal_at(tmp_path / step_id, step_id)
        document = json.loads(value.model_dump_json())
        kinds[step_id] = {
            (item.name, item.kind) for item in marked_fields(STEPS[step_id].schema, document)
        }
    assert kinds["source_context"] == {("pack_sha256", "pack"), ("source_sha256", "source")}
    assert kinds["financials"] == {
        ("context_step_sha256", "context-step"),
        ("pack_sha256", "pack"),
        ("source_sha256", "source"),
        ("financial_review_sha256", "financial-review"),
        ("source_context_review_sha256", "source-context-review"),
        # Task 7.13: the book's and each period's four strings, from the bound source scope.
        ("currency", "scope-dimension"),
        ("unit", "scope-dimension"),
        ("accounting_basis", "scope-dimension"),
        ("entity_perimeter", "scope-dimension"),
    }  # this fixture has no FX conversion or audit explanation (tested below)
    assert kinds["narrative"] == kinds["readiness"] == {("inputs_sha256", "step-inputs")}


@pytest.mark.parametrize("step_id", CP1)
def test_wrong_hashes_are_overwritten_and_recorded(tmp_path: Path, step_id: str) -> None:
    store, ticket_id, value = journal_at(tmp_path, step_id)
    model = STEPS[step_id].schema
    document = json.loads(value.model_dump_json())
    marked = marked_fields(model, document)
    for item in marked:
        current = item.holder[item.name]
        item.holder[item.name] = [ZERO] * len(current) if isinstance(current, list) else ZERO
    submitted = submit_model_payload(store, ticket_id, step_id, json.dumps(document))
    assert submitted.journal.steps[-1].status == "valid", submitted.journal.steps[-1].issues
    assert sorted(submitted.prefilled) == sorted(item.path for item in marked)
    assert model.model_validate_json(retained(store, ticket_id)) == value


def test_the_batch_5_copy_of_the_output_hash_is_overwritten(tmp_path: Path) -> None:
    """E1 batch 5: Sol copied the block's `step_output_sha256` line (the output hash)."""
    store, ticket_id, value = journal_at(tmp_path, "financials")
    source = store.read().attempts[-1].steps[0]
    document = json.loads(value.model_dump_json())
    document["context_step_sha256"] = source.output_sha256
    submitted = submit_model_payload(store, ticket_id, "financials", json.dumps(document))
    assert submitted.journal.steps[-1].status == "valid", submitted.journal.steps[-1].issues
    assert submitted.prefilled == ("context_step_sha256",)
    assert json.loads(retained(store, ticket_id))["context_step_sha256"] == source.content_hash()


@pytest.mark.parametrize("step_id", CP1)
def test_a_payload_already_bound_right_is_kept_byte_for_byte(tmp_path: Path, step_id: str) -> None:
    store, ticket_id, value = journal_at(tmp_path, step_id)
    payload = value.model_dump_json(indent=1)  # any spelling: nothing is rewritten
    submitted = submit_model_payload(store, ticket_id, step_id, payload)
    assert submitted.journal.steps[-1].status == "valid"
    assert submitted.prefilled == ()
    assert retained(store, ticket_id) == payload == submitted.payload


@pytest.mark.parametrize("case", ["facility", "audit"])
def test_facility_and_audit_observation_hashes_are_the_validators_values(case: str) -> None:
    """The book-scoped bindings: an FX conversion binds its facility row; an audit explanation
    binds the effective account values of its periods (fixtures the validators accept)."""
    from tests.product.test_audit_basis import differing, explain, frozen
    from tests.product.test_facility_fx import freeze_fx, fx_case

    pack, review = freeze_fx(fx_case()) if case == "facility" else frozen(explain(differing()))
    assert validate_financial_review(pack, review) == ()
    payload, paths = without_bindings(FinancialReview, review, keep=BOOK_ONLY)
    wanted = {"facility"} if case == "facility" else {"annual-observation", "quarter-observations"}
    document = json.loads(review.model_dump_json())
    assert wanted <= {item.kind for item in marked_fields(FinancialReview, document)}
    result = prefill(FinancialReview, payload, known_for(pack), PREFILLED["financials"])
    assert sorted(result.paths) == sorted(paths) and result.unbound == ()
    assert FinancialReview.model_validate_json(result.payload) == review


def test_an_unknown_facility_or_source_is_unbound_with_the_validators_wording() -> None:
    from tests.product.test_facility_fx import freeze_fx, fx_case

    pack, review = freeze_fx(fx_case())
    payload, _ = without_bindings(FinancialReview, review, keep=BOOK_ONLY)
    document = json.loads(payload)
    conversions = document["books"][0]["facility_fx_conversions"]
    conversions[0]["facility_id"] = "no-such-facility"
    conversions[1]["citations"][0]["source_id"] = "no-such-source"
    known = known_for(pack)
    result = prefill(FinancialReview, json.dumps(document), known, PREFILLED["financials"])
    filled = json.loads(result.payload)["books"][0]["facility_fx_conversions"]
    assert "facility_sha256" not in filled[0]  # nothing Python could bind it to
    assert "source_sha256" not in filled[1]["citations"][0]
    assert all("facility_sha256" in item for item in filled[1:])
    base = "books.0.facility_fx_conversions"
    assert result.unbound == (
        (f"{base}.1.citations.0.source_sha256", "Unavailable or changed source: no-such-source"),
        (
            f"{base}.0.facility_sha256",
            f"FX conversion {conversions[0]['conversion_id']}: unknown facility/period",
        ),
    )


def test_the_last_of_duplicate_facility_rows_is_bound_as_the_validator_reads_it() -> None:
    from deploy_vii.facility_fx import fx_conversion_issues
    from deploy_vii.financial_contracts import FinancialBook
    from tests.product.test_facility_fx import freeze_fx, fx_case

    pack, review = freeze_fx(fx_case())
    payload, _ = without_bindings(FinancialReview, review, keep=BOOK_ONLY)
    document = json.loads(payload)
    book = document["books"][0]
    conversion = book["facility_fx_conversions"][0]
    first = next(
        row
        for row in book["facilities"]
        if (row["facility_id"], row["period_id"])
        == (conversion["facility_id"], conversion["period_id"])
    )
    later = json.loads(json.dumps(first))
    later["currency"] = "GBP"  # a different row with the same facility and period
    book["facilities"].append(later)
    result = prefill(
        FinancialReview, json.dumps(document), known_for(pack), PREFILLED["financials"]
    )
    bound = FinancialReview.model_validate_json(result.payload).books[0]
    rows = [
        r
        for r in bound.facilities
        if (r.facility_id, r.period_id) == (conversion["facility_id"], conversion["period_id"])
    ]
    assert len(rows) == 2 and rows[0] != rows[1]
    assert bound.facility_fx_conversions[0].facility_sha256 == rows[-1].content_hash()
    issues = fx_conversion_issues(FinancialBook.model_validate_json(bound.model_dump_json()))
    assert not [i for i in issues if "stale facility hash" in i], issues


@pytest.mark.parametrize("change", ["unknown-period", "no-observation"])
def test_an_unbindable_audit_explanation_is_unbound_with_the_validators_wording(
    change: str,
) -> None:
    from tests.product.test_audit_basis import differing, explain, frozen

    pack, review = frozen(explain(differing()))
    payload, _ = without_bindings(FinancialReview, review, keep=BOOK_ONLY)
    document = json.loads(payload)
    item = document["books"][0]["audit_basis_explanations"][0]
    if change == "unknown-period":
        item["quarter_period_ids"][3] = "Q9"
        expected = f"Unknown audit explanation period: {item['explanation_id']}"
    else:
        item["metric_id"] = "no_such_metric"
        expected = f"Stale audit explanation observation: {item['explanation_id']} FY"
    result = prefill(
        FinancialReview, json.dumps(document), known_for(pack), PREFILLED["financials"]
    )
    assert result.unbound and result.unbound[0][1] == expected
    kept = json.loads(result.payload)["books"][0]["audit_basis_explanations"][0]
    assert "annual_observation_sha256" not in kept and "quarter_observation_sha256" not in kept


@pytest.mark.parametrize("change", ["unknown-period", "no-observation"])
def test_an_unbindable_audit_explanation_is_rejected_with_the_validators_wording_first(
    tmp_path: Path, change: str
) -> None:
    """Fix 3 (C): through `submit_model_payload`, as the source and facility cases."""
    store, ticket_id, value = journal_at(tmp_path, "financials")
    payload, _ = without_bindings(FinancialSubmission, value)
    document = json.loads(payload)
    book = document["financial"]["books"][0]
    periods = {period["period_id"] for period in book["periods"]}
    assert {"FY", "Q1", "Q2", "Q3", "Q4"} <= periods, periods
    citation = next(
        m.holder for m in marked_fields(FinancialSubmission, document) if m.kind == "source"
    )
    item = {
        "explanation_id": "audit.unbindable",
        "annual_period_id": "FY",
        "metric_id": "cash_interest_paid",
        "quarter_period_ids": ["Q1", "Q2", "Q3", "Q4"],
        "explanation": "Synthetic audit explanation",
        "citations": [dict(citation)],
    }
    if change == "unknown-period":
        item["quarter_period_ids"] = ["Q1", "Q2", "Q3", "Q9"]
        expected = "Unknown audit explanation period: audit.unbindable"
    else:
        item["metric_id"] = "no_such_metric"
        expected = "Stale audit explanation observation: audit.unbindable FY"
    book["audit_basis_explanations"] = [item]
    submitted = submit_model_payload(store, ticket_id, "financials", json.dumps(document))
    (rejected,) = submitted.journal.step_repairs
    assert rejected.issues[0] == expected, rejected.issues
    assert not [issue for issue in rejected.issues if "Field required" in issue], rejected.issues


def unknown_source(document: dict[str, Any], model: type[Contract]) -> str:
    """Point the first citation of `document` at a source the pack does not hold."""
    first = next(item for item in marked_fields(model, document) if item.kind == "source")
    first.holder["source_id"] = "no-such-source"
    return first.path


@pytest.mark.parametrize("step_id", ["source_context", "financials"])
def test_an_unknown_source_is_rejected_with_the_validators_wording_first(
    tmp_path: Path, step_id: str
) -> None:
    """Fix 2 (F1): never "...source_sha256: Field required", a field the sent schema forbids."""
    store, ticket_id, value = journal_at(tmp_path, step_id)
    model = STEPS[step_id].schema
    payload, _ = without_bindings(model, value)
    document = json.loads(payload)
    path = unknown_source(document, model)
    submitted = submit_model_payload(store, ticket_id, step_id, json.dumps(document))
    (rejected,) = submitted.journal.step_repairs  # rejected, as before; the repair is kept
    assert rejected.issues[0] == "Unavailable or changed source: no-such-source"
    assert f"{path}: Field required" not in rejected.issues
    assert not [issue for issue in rejected.issues if "Field required" in issue], rejected.issues
    assert store.payload(rejected.payload_sha256) == submitted.payload


def test_an_unknown_facility_is_rejected_with_the_validators_wording_first(
    tmp_path: Path,
) -> None:
    from tests.product.test_facility_fx import fx_case

    store, ticket_id, value = journal_at(tmp_path, "financials")
    payload, _ = without_bindings(FinancialSubmission, value)
    document = json.loads(payload)
    book = document["financial"]["books"][0]
    conversion = json.loads(fx_case().facility_fx_conversions[0].model_dump_json())
    citation = next(
        m.holder for m in marked_fields(FinancialSubmission, document) if m.kind == "source"
    )
    conversion.update(
        conversion_id="fx-unknown",
        facility_id="no-such-facility",
        period_id=book["periods"][0]["period_id"],
        citations=[dict(citation)],
    )
    conversion["rate"]["citations"] = [dict(citation)]
    del conversion["facility_sha256"]
    book["facility_fx_conversions"] = [conversion]
    submitted = submit_model_payload(store, ticket_id, "financials", json.dumps(document))
    (rejected,) = submitted.journal.step_repairs
    assert rejected.issues[0] == "FX conversion fx-unknown: unknown facility/period"
    assert not [issue for issue in rejected.issues if "Field required" in issue], rejected.issues


def test_a_resumed_unbound_step_recomputes_the_same_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A validator exception leaves the step pending; resuming the same payload recomputes the
    unbound issues from the retained payload and the bindings read before the write."""
    from deploy_vii.live import submission

    store, ticket_id, value = journal_at(tmp_path / "a", "source_context")
    payload, _ = without_bindings(SourceContextReview, value)
    document = json.loads(payload)
    unknown_source(document, SourceContextReview)
    payload = json.dumps(document)
    fresh_store, fresh_ticket, _ = journal_at(tmp_path / "b", "source_context")
    expected = submit_model_payload(fresh_store, fresh_ticket, "source_context", payload)
    real = submission.validate_cp1_stage
    calls: list[int] = []

    def flaky(store: Execution, pack: PreparedPack, attempt: Attempt) -> StepValidation:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("validator interrupted")
        return real(store, pack, attempt)

    monkeypatch.setattr(submission, "validate_cp1_stage", flaky)
    with pytest.raises(RuntimeError, match="interrupted"):
        submit_model_payload(store, ticket_id, "source_context", payload)
    pending = next(a for a in store.read().attempts if a.ticket_id == ticket_id).steps[-1]
    assert pending.status == "pending"
    resumed = submit_model_payload(store, ticket_id, "source_context", payload)
    (rejected,) = resumed.journal.step_repairs
    assert rejected.payload_sha256 == pending.payload_sha256
    assert rejected.issues == expected.journal.step_repairs[0].issues
    assert rejected.issues[0] == "Unavailable or changed source: no-such-source"


def test_a_financial_review_that_does_not_parse_leaves_its_two_hashes_unset(
    tmp_path: Path,
) -> None:
    store, ticket_id, value = journal_at(tmp_path, "financials")
    payload, _ = without_bindings(FinancialSubmission, value)
    document = json.loads(payload)
    document["financial"]["books"] = "not books"
    submitted = submit_model_payload(store, ticket_id, "financials", json.dumps(document))
    kept = json.loads(submitted.payload)
    assert "financial_review_sha256" not in kept["definition"]
    assert "financial_review_sha256" not in kept["binding"]
    assert kept["binding"]["source_context_review_sha256"] and kept["context_step_sha256"]
    (rejected,) = submitted.journal.step_repairs  # the shape rejection stands (task 7.0g)
    assert any(issue.startswith("financial.books") for issue in rejected.issues), rejected.issues


MISSING_DATES = (
    "financial.books.0.periods.0: Value error, missing period dates require a limitation"
)


def test_a_shape_failure_never_asks_the_model_for_the_financial_review_hashes(
    tmp_path: Path,
) -> None:
    """Task 7.16 (hybrid CP-1 probes, 23-24 Oct): a balance-sheet period with a null start date
    and no limitation fails the financial object's own shape, so its review hash cannot be
    computed and both `financial_review_sha256` fields stay unset with no unbound reference. The
    model is told the shape issue, never "Field required" of a field its schema never offers;
    the rejection, the retained payload and the recorded pre-fill are the plain path's."""
    store, ticket_id, value = journal_at(tmp_path / "a", "financials")
    payload, _ = without_bindings(FinancialSubmission, value)
    document = json.loads(payload)
    period = document["financial"]["books"][0]["periods"][0]
    assert (period["period_type"], period["limitation"]) == ("PERIOD_END", None)
    period["start_date"] = None
    payload = json.dumps(document)
    submitted = submit_model_payload(store, ticket_id, "financials", payload)
    (rejected,) = submitted.journal.step_repairs
    assert MISSING_DATES in rejected.issues, rejected.issues
    assert not [i for i in rejected.issues if "financial_review_sha256" in i], rejected.issues
    # The plain path on a fresh journal: same retained payload, same pre-fill, and the same
    # issues but for the two stripped lines.
    fresh, fresh_ticket, _ = journal_at(tmp_path / "b", "financials")
    plain = submit_cp1_step(fresh, fresh_ticket, "financials", submitted.payload)
    (expected,) = plain.step_repairs
    stripped = (
        "definition.financial_review_sha256: Field required",
        "binding.financial_review_sha256: Field required",
    )
    assert set(stripped) <= set(expected.issues), expected.issues
    assert rejected.issues == tuple(i for i in expected.issues if i not in stripped)
    assert (rejected.status, rejected.payload_sha256) == ("invalid", expected.payload_sha256)
    assert rejected.output_sha256 == expected.output_sha256
    assert retained_repair(store, ticket_id) == submitted.payload
    assert not [p for p in submitted.prefilled if "financial_review_sha256" in p]


def test_stripping_the_unset_fields_lines_never_turns_a_rejection_into_an_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: were the stage's only issues the "Field required" of unset marked fields,
    they stay, so a payload with an unset marked field is rejected exactly as before."""
    from deploy_vii.live import submission

    store, ticket_id, value = journal_at(tmp_path, "financials")
    payload, _ = without_bindings(FinancialSubmission, value)
    document = json.loads(payload)
    document["financial"]["books"][0]["periods"][0]["start_date"] = None
    only = (
        "definition.financial_review_sha256: Field required",
        "binding.financial_review_sha256: Field required",
    )
    monkeypatch.setattr(submission, "validate_cp1_stage", lambda *_: StepValidation(issues=only))
    submitted = submit_model_payload(store, ticket_id, "financials", json.dumps(document))
    (rejected,) = submitted.journal.step_repairs
    assert (rejected.status, rejected.issues) == ("invalid", only)


def retained_repair(store: Execution, ticket_id: str) -> str:
    attempt = next(a for a in store.read().attempts if a.ticket_id == ticket_id)
    return store.payload(attempt.step_repairs[-1].payload_sha256)


def test_a_rewritten_payload_keeps_every_number_and_text_exactly() -> None:
    digest = "a" * 64
    payload = '{"amount":3624.10,"tiny":1e-7,"n":-0,"text":"caf\\u00e9 \\u2013 \\"q\\"","x":[1,2]}'
    known = Known(pack_sha256=ZERO, sources={}, step={"step-inputs": digest})
    result = prefill(DownstreamReview, payload, known, PREFILLED["readiness"])
    assert (result.paths, result.kinds) == (("inputs_sha256",), ("step-inputs",))
    text = result.payload
    assert text == (
        f'{{"amount":3624.10,"tiny":1E-7,"n":0,"text":"café {EN_DASH} \\"q\\"","x":[1,2],'
        f'"inputs_sha256":"{digest}"}}'
    )
    assert json.loads(text, parse_float=Decimal) == {
        **json.loads(payload, parse_float=Decimal),
        "inputs_sha256": digest,
    }


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        '{"schema_version":"cp1-financial-submission/1","financial":{',  # truncated
        "[1, 2]",
        '"text"',
        '{"amount": NaN}',
        '{"text": "\\ud800"}',  # a lone surrogate: Pydantic refuses the text as invalid JSON
    ],
    ids=["prose", "truncated", "array", "string", "nan", "lone-surrogate"],
)
def test_a_payload_that_is_not_a_json_object_is_handed_on_untouched(
    tmp_path: Path, payload: str
) -> None:
    store, ticket_id, _ = journal_at(tmp_path, "financials")
    known = known_bindings(store, ticket_id, "financials")
    result = prefill(FinancialSubmission, payload, known, PREFILLED["financials"])
    assert (result.payload, result.paths, result.unbound) == (payload, (), ())
    submitted = submit_model_payload(store, ticket_id, "financials", payload)
    assert (submitted.payload, submitted.prefilled) == (payload, ())
    (rejected,) = submitted.journal.step_repairs  # the step's first rejection (task 7.0g)
    assert store.payload(rejected.payload_sha256) == payload
    assert rejected.issues and NOT_BOUND not in rejected.issues


@pytest.mark.parametrize("step_id", ["financials", "narrative", "readiness"])
def test_a_missing_bound_step_raises_before_anything_is_written(
    tmp_path: Path, step_id: str
) -> None:
    from tests.product.replay_support import PACKS  # imported here, as in journal_at

    store, ticket = PACKS["synthetic-cp1"](tmp_path)
    rejected = submit_cp1_step(store, ticket.ticket_id, "source_context", "{}")
    assert rejected.steps == () and rejected.step_repairs[0].status == "invalid"
    for ticket_id in (ticket.ticket_id, "absent-ticket"):
        before = store.read().content_hash()
        with pytest.raises(ValueError, match="no valid source_context step"):
            submit_model_payload(store, ticket_id, step_id, "{}")
        assert store.read().content_hash() == before


def test_narrative_needs_the_retained_financial_step(tmp_path: Path) -> None:
    store, ticket_id, _ = journal_at(tmp_path, "financials")
    before = store.read().content_hash()
    with pytest.raises(ValueError, match="no valid financials step"):
        submit_model_payload(store, ticket_id, "narrative", "{}")
    assert store.read().content_hash() == before


def test_a_marked_kind_nothing_fills_raises(tmp_path: Path) -> None:
    store, ticket_id, value = journal_at(tmp_path, "financials")
    known = known_bindings(store, ticket_id, "financials")
    with pytest.raises(ValueError, match="No pre-fill for the marked binding kinds"):
        prefill(FinancialSubmission, value.model_dump_json(), known, frozenset({"pack"}))


@pytest.mark.parametrize(
    ("step_id", "field", "message"),
    [
        ("financials", ("context_step_sha256",), NOT_BOUND),
        (
            "financials",
            ("binding", "source_context_review_sha256"),
            "Context binding does not identify current financial and source reviews",
        ),
        ("narrative", ("inputs_sha256",), "Narrative review does not bind current input registers"),
        ("readiness", ("inputs_sha256",), "Downstream review does not bind current inputs"),
    ],
    ids=["context-step", "source-context-review", "narrative-inputs", "readiness-inputs"],
)
def test_the_validator_still_rejects_a_mismatched_binding_that_bypasses_the_prefill(
    tmp_path: Path, step_id: str, field: tuple[str, ...], message: str
) -> None:
    """R3: the independent-artefact checks stay real guards when the pre-fill is bypassed."""
    store, ticket_id, value = journal_at(tmp_path, step_id)
    document = json.loads(value.model_dump_json())
    holder = document
    for key in field[:-1]:
        holder = holder[key]
    holder[field[-1]] = store.read().attempts[-1].steps[0].output_sha256
    journal = submit_cp1_step(store, ticket_id, step_id, json.dumps(document))
    (rejected,) = journal.step_repairs
    assert rejected.issues[0] == message, rejected.issues
    if field == ("context_step_sha256",):
        assert rejected.issues == (NOT_BOUND,)  # the check returns before any other


def test_every_marked_kind_is_one_python_fills_for_that_step() -> None:
    """The sent schema drops exactly the bindings the composer fills: a marked kind nothing
    fills would be required by the stored contract and never sent."""
    for step_id, definition in STEPS.items():
        text = json.dumps(definition.schema.model_json_schema())
        kinds = set(re.findall(f'"{PREFILLED_MARKER}": "([a-z-]+)"', text))
        assert kinds == set(PREFILLED.get(step_id, frozenset())), step_id
        assert text.count(PREFILLED_MARKER) == len(re.findall(f'"{PREFILLED_MARKER}": "', text))
    assert set(PREFILLED) == {*CP1, "quality"}


# --- task 7.13: Python copies the four dimension strings of the bound source scope ----------

DIMENSIONS = ("currency", "unit", "accounting_basis", "entity_perimeter")
type Case = tuple[
    PreparedPack, SourceContextReview, FinancialReview, DefinitionReview, FinancialContextBinding
]
# What a source_context model wrote in batch e1-cp1-13 is free text; these stand in for it
# (synthetic wording, not filing text).
SCOPE_PERIMETER = "Synthetic group and consolidated subsidiaries, intercompany eliminated"
SCOPE_BASIS = "U.S. GAAP (synthetic)"
PARAPHRASE = "Synthetic group and subsidiaries, intercompany eliminated"
MIXED = "Mixed units, currency, accounting basis or perimeter"
NO_SCOPE = "No matching entity/date/basis source scope"


def scoped_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: Callable[[ReportingScope], ReportingScope | None] | None = None,
) -> tuple[Execution, str, FinancialSubmission, SourceContextReview]:
    """A CP-1 ticket whose retained source_context scopes carry free-text strings (every scope
    `SCOPE_PERIMETER` / `SCOPE_BASIS`, then `change(scope)` where given, a scope it maps to
    None being left out), and the financial submission the synthetic case builds (its own
    strings: "Consolidated", "US GAAP")."""
    from tests.product import test_workflow

    real = test_workflow.case

    def scoped(value: FinancialBook | None = None) -> Case:
        pack, context, financial, definition, binding = real(value)
        (source,) = context.sources
        scopes = []
        for scope in source.scopes:
            worded = scope.model_copy(
                update={"entity_perimeter": SCOPE_PERIMETER, "accounting_basis": SCOPE_BASIS}
            )
            changed = worded if change is None else change(worded)
            if changed is not None:
                scopes.append(changed)
        update = {"sources": (source.model_copy(update={"scopes": tuple(scopes)}),)}
        return pack, context.model_copy(update=update), financial, definition, binding

    monkeypatch.setattr(test_workflow, "case", scoped)
    store, ticket, extraction = test_workflow.cp1_case(tmp_path)
    held = store.read().attempts[-1].steps[0]
    context = SourceContextReview.model_validate_json(store.payload(held.payload_sha256))
    binding = extraction.binding.model_copy(
        update={"source_context_review_sha256": context.content_hash()}
    )
    return store, ticket.ticket_id, extraction.model_copy(update={"binding": binding}), context


def refused_context_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: Callable[[ReportingScope], ReportingScope],
    refusal: str,
) -> tuple[Execution, str, FinancialSubmission]:
    """Task 7.14: `validate_source_context` now refuses scopes of one entity that disagree or
    lack a dimension, so no such context is retained. The prefill's own rejections stay as
    defence in depth; to reach them, the ticket retains the agreeing scopes and the prefill
    alone reads the changed ones (its `known_bindings` is replaced). The changed context's
    refusal by the source_context validator starts with `refusal`."""
    store, ticket_id, value, context = scoped_journal(tmp_path, monkeypatch)
    (source,) = context.sources
    changed = context.model_copy(
        update={
            "sources": (
                source.model_copy(update={"scopes": tuple(change(s) for s in source.scopes)}),
            )
        }
    )
    issues = validate_source_context(store.pack(store.read()), changed)
    assert issues and all(issue.startswith(refusal) for issue in issues), issues
    real = known_bindings

    def with_changed(store: Execution, ticket_id: str, step_id: str) -> Known:
        return dataclasses.replace(real(store, ticket_id, step_id), context=changed)

    monkeypatch.setattr("deploy_vii.live.submission.known_bindings", with_changed)
    return store, ticket_id, value


def rebound(document: dict[str, Any]) -> str:
    """`document` with its two financial-review hashes recomputed, as a payload that reaches
    the journal without the prefill must carry them."""
    digest = FinancialReview.model_validate_json(json.dumps(document["financial"])).content_hash()
    document["binding"]["financial_review_sha256"] = digest
    document["definition"]["financial_review_sha256"] = digest
    return json.dumps(document)


def dimension_paths(document: dict[str, Any]) -> list[str]:
    marked = marked_fields(FinancialSubmission, document)
    return [item.path for item in marked if item.kind == "scope-dimension"]


def set_strings(document: dict[str, Any], *, book: str, periods: str) -> None:
    """Write `book` / `periods` as the book's / every period's perimeter (a model's copy)."""
    (value,) = document["financial"]["books"]
    value["entity_perimeter"] = book
    for period in value["periods"]:
        period["entity_perimeter"] = periods


def strings_of(payload: str) -> set[tuple[str, ...]]:
    """The distinct four-string tuples the book and its periods carry in `payload`."""
    (value,) = json.loads(payload)["financial"]["books"]
    return {tuple(item.get(name) for name in DIMENSIONS) for item in (value, *value["periods"])}


def test_the_dimension_strings_leave_the_sent_schema_of_the_book_and_its_periods() -> None:
    definitions = strict_schema(FinancialSubmission)["$defs"]
    for name in ("FinancialBook", "FinancialPeriod"):
        properties = definitions[name]["properties"]
        assert not set(DIMENSIONS) & set(properties), name
        assert not set(DIMENSIONS) & set(definitions[name]["required"]), name
    # Other registers keep their own unit or currency (a facility's, a KPI's): not the book's.
    assert "currency" in definitions["FacilityObservation"]["properties"]
    assert "unit" in definitions["KpiObservation"]["properties"]


def test_python_writes_the_bound_scopes_strings_into_the_book_and_every_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ticket_id, value, context = scoped_journal(tmp_path, monkeypatch)
    payload, _ = without_bindings(FinancialSubmission, value)
    submitted = submit_model_payload(store, ticket_id, "financials", payload)
    step = submitted.journal.steps[-1]
    assert (step.step_id, step.status) == ("financials", "valid"), step.issues
    (scope, *_) = context.sources[0].scopes
    assert strings_of(submitted.payload) == {("USD", "MILLIONS", SCOPE_BASIS, SCOPE_PERIMETER)}
    assert (scope.entity_perimeter, scope.accounting_basis) == (SCOPE_PERIMETER, SCOPE_BASIS)
    # Provenance: every one of the 4 x (1 book + 6 periods) strings Python wrote is recorded.
    pairs = zip(submitted.prefilled, submitted.prefilled_kinds, strict=True)
    filled = [path for path, kind in pairs if kind == "scope-dimension"]
    assert sorted(filled) == sorted(dimension_paths(json.loads(submitted.payload)))
    assert len(filled) == 4 * 7
    assert retained(store, ticket_id) == submitted.payload


@pytest.mark.parametrize(
    ("book", "periods", "unfilled_issue"),
    [
        (PARAPHRASE, PARAPHRASE, NO_SCOPE),  # book and periods agree, scope paraphrased
        (PARAPHRASE, SCOPE_PERIMETER, MIXED),  # batch e1-cp1-13/14: book differs from periods
    ],
    ids=["paraphrased-scope", "book-differs-from-periods"],
)
def test_the_exact_match_rules_still_reject_drift_that_bypasses_the_prefill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, book: str, periods: str, unfilled_issue: str
) -> None:
    """Item 4: `context_binding` and `book_issues` are untouched. A model's own copy of the
    strings is rejected by them when it reaches the journal unfilled, and accepted once Python
    has written the scope's strings over it."""
    store, ticket_id, value, _ = scoped_journal(tmp_path, monkeypatch)
    document = json.loads(value.model_dump_json())
    set_strings(document, book=book, periods=periods)
    raw = rebound(document)
    bypassed = submit_cp1_step(store, ticket_id, "financials", raw)
    (rejected,) = bypassed.step_repairs
    assert rejected.issues and all(unfilled_issue in issue for issue in rejected.issues), (
        rejected.issues
    )
    submitted = submit_model_payload(store, ticket_id, "financials", raw)
    assert submitted.journal.steps[-1].status == "valid", submitted.journal.steps[-1].issues
    assert strings_of(submitted.payload) == {("USD", "MILLIONS", SCOPE_BASIS, SCOPE_PERIMETER)}
    assert "financial.books.0.entity_perimeter" in submitted.prefilled


def test_a_book_whose_periods_scopes_disagree_is_rejected_with_one_issue_and_no_book_strings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: no majority and no first-wins. Each period keeps its own scope's strings;
    the book gets none, and one issue names the periods and the field."""

    def q1_differs(scope: ReportingScope) -> ReportingScope:
        if scope.scope_id != "Q1":
            return scope
        return scope.model_copy(update={"entity_perimeter": PARAPHRASE})

    store, ticket_id, value = refused_context_journal(
        tmp_path, monkeypatch, q1_differs, "Financial scopes of one entity disagree on "
    )
    payload, _ = without_bindings(FinancialSubmission, value)
    submitted = submit_model_payload(store, ticket_id, "financials", payload)
    (rejected,) = submitted.journal.step_repairs
    assert rejected.issues[0] == (
        "Bound source scopes disagree on entity_perimeter: consolidated OPEN, Q1, Q2, Q3, Q4, FY"
    )
    assert not [issue for issue in rejected.issues if "Field required" in issue], rejected.issues
    (book,) = json.loads(submitted.payload)["financial"]["books"]
    assert not set(DIMENSIONS) & set(book)  # nothing filled for the book
    perimeters = {p["period_id"]: p["entity_perimeter"] for p in book["periods"]}
    assert perimeters.pop("Q1") == PARAPHRASE
    assert set(perimeters.values()) == {SCOPE_PERIMETER}


def test_a_period_without_a_matching_scope_is_left_unfilled_and_rejected_by_the_existing_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ticket_id, value, _ = scoped_journal(
        tmp_path, monkeypatch, lambda scope: None if scope.scope_id == "Q2" else scope
    )
    payload, _ = without_bindings(FinancialSubmission, value)
    submitted = submit_model_payload(store, ticket_id, "financials", payload)
    (rejected,) = submitted.journal.step_repairs
    assert rejected.issues[0] == f"{NO_SCOPE}: consolidated Q2 S1"
    assert not [issue for issue in rejected.issues if "Field required" in issue], rejected.issues
    assert not [issue for issue in rejected.issues if "disagree" in issue], rejected.issues
    (book,) = json.loads(submitted.payload)["financial"]["books"]
    (q2,) = [p for p in book["periods"] if p["period_id"] == "Q2"]
    assert not set(DIMENSIONS) & set(q2)
    assert book["entity_perimeter"] == SCOPE_PERIMETER  # the other periods' common strings


def test_a_scope_without_a_currency_leaves_the_currency_to_the_validators_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E1 batch e1-cp1-14: every scope's `currency` was null. Python writes no currency; the
    stored contract requires one, so the step is rejected with that field's message."""
    store, ticket_id, value = refused_context_journal(
        tmp_path,
        monkeypatch,
        lambda scope: scope.model_copy(update={"currency": None}),
        "Financial scope lacks currency: ",
    )
    payload, _ = without_bindings(FinancialSubmission, value)
    submitted = submit_model_payload(store, ticket_id, "financials", payload)
    (rejected,) = submitted.journal.step_repairs
    assert "financial.books.0.currency: Field required" in rejected.issues
    (book,) = json.loads(submitted.payload)["financial"]["books"]
    for item in (book, *book["periods"]):
        assert "currency" not in item
        assert (item["unit"], item["entity_perimeter"]) == ("MILLIONS", SCOPE_PERIMETER)


def test_a_null_scope_currency_stays_named_beside_a_disagreement_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confidence review: the batch-14 shape has both causes (a perimeter that differs by
    period and a null currency). The disagreement routes the step through `_validate_prefilled`,
    which drops the "Field required" of unset marked fields; the null currency is a cause of
    its own, so its message stays."""

    def batch_14(scope: ReportingScope) -> ReportingScope:
        update: dict[str, object] = {"currency": None}
        if scope.scope_id == "Q1":
            update["entity_perimeter"] = PARAPHRASE
        return scope.model_copy(update=update)

    store, ticket_id, value = refused_context_journal(
        tmp_path, monkeypatch, batch_14, "Financial scope"
    )
    payload, _ = without_bindings(FinancialSubmission, value)
    submitted = submit_model_payload(store, ticket_id, "financials", payload)
    (rejected,) = submitted.journal.step_repairs
    assert rejected.issues[0].startswith("Bound source scopes disagree on entity_perimeter: ")
    assert "financial.books.0.periods.1.currency: Field required" in rejected.issues
    assert "financial.books.0.currency: Field required" not in rejected.issues  # disagreement


@pytest.mark.parametrize(
    ("rows", "issue"),
    [
        ([], "Bind every financial book exactly once"),
        (
            [{"book_id": "consolidated", "entity_id": "issuer"}] * 2,
            "Bind every financial book exactly once",
        ),
        (
            [{"book_id": "consolidated", "entity_id": "no-such-entity"}],
            "Unknown bound entity: consolidated no-such-entity",
        ),
    ],
    ids=["unbound", "bound-twice", "unknown-entity"],
)
def test_a_book_bound_to_no_single_known_entity_names_the_binding_validators_issue(
    tmp_path: Path, rows: list[dict[str, str]], issue: str
) -> None:
    store, ticket_id, value = journal_at(tmp_path, "financials")
    payload, _ = without_bindings(FinancialSubmission, value)
    document = json.loads(payload)
    document["binding"]["books"] = rows
    known = known_bindings(store, ticket_id, "financials")
    result = prefill(FinancialSubmission, json.dumps(document), known, PREFILLED["financials"])
    assert [text for _, text in result.unbound] == [issue]
    assert not {k for k in result.kinds if k == "scope-dimension"}
    submitted = submit_model_payload(store, ticket_id, "financials", json.dumps(document))
    (rejected,) = submitted.journal.step_repairs
    assert rejected.issues[0] == issue, rejected.issues
    assert not [i for i in rejected.issues if "Field required" in i], rejected.issues


def test_a_known_without_the_source_context_fills_no_dimension(tmp_path: Path) -> None:
    """Only the financials step's bindings carry the retained scopes; anything else leaves the
    strings as sent."""
    _, _, value = journal_at(tmp_path, "financials")
    payload, _ = without_bindings(FinancialSubmission, value)
    known = Known(pack_sha256=ZERO, sources={}, step={})
    result = prefill(FinancialSubmission, payload, known, PREFILLED["financials"])
    assert "scope-dimension" not in result.kinds
    assert set(dimension_paths(json.loads(result.payload))) <= set(result.unset)


# --- task 7.4: the `quality` step: the model supplies the QA review, Python promotes ---------


@pytest.fixture(scope="module")
def staged_quality(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str, QualityInputs]:
    """A CP-1 ticket whose four stages are retained valid (the promotable 6.4 case)."""
    from tests.product.test_cp1_workflow import staged  # imported here, as in journal_at

    store, attempt = staged(tmp_path_factory.mktemp("quality"))
    inputs = cp1_quality_inputs(cp1_registers(store, attempt.ticket_id))
    return store.directory, attempt.ticket_id, inputs


@pytest.fixture
def quality_journal(
    staged_quality: tuple[Path, str, QualityInputs], tmp_path: Path
) -> tuple[Execution, str, QualityInputs]:
    directory, ticket_id, inputs = staged_quality
    shutil.copytree(directory, tmp_path / "journal")
    return Execution(tmp_path / "journal"), ticket_id, inputs


def unbound_review(inputs: QualityInputs, **update: object) -> tuple[QualityReview, str]:
    """The at-ceiling review and the payload a model writes for it: no `inputs_sha256`."""
    from tests.product.test_cp1_workflow import at_ceiling

    review = at_ceiling(inputs, **update)
    payload, paths = without_bindings(QualityReview, review)
    assert paths == ("inputs_sha256",) and "inputs_sha256" not in payload
    return review, payload


def test_the_quality_step_is_cp1_and_its_sent_schema_asks_for_no_binding() -> None:
    assert STEPS["quality"] == StepDef("CP-1", QualityReview)
    assert PREFILLED["quality"] == frozenset({"quality-inputs"})
    stored = QualityReview.model_json_schema()
    assert "inputs_sha256" in stored["required"]  # the stored contract still binds it
    assert stored["properties"]["inputs_sha256"][PREFILLED_MARKER] == "quality-inputs"
    sent = strict_schema(QualityReview)
    assert "inputs_sha256" not in sent["properties"] and "inputs_sha256" not in sent["required"]
    assert "inputs_sha256" not in json.dumps(sent)


def test_a_review_without_its_binding_is_bound_by_python_and_promotes_cp1(
    quality_journal: tuple[Execution, str, QualityInputs],
) -> None:
    store, ticket_id, inputs = quality_journal
    review, payload = unbound_review(inputs)
    submitted = submit_model_payload(store, ticket_id, "quality", payload)
    assert submitted.prefilled == ("inputs_sha256",)
    assert submitted.prefilled_kinds == ("quality-inputs",)
    assert QualityReview.model_validate_json(submitted.payload) == review
    journal = submitted.journal
    assert journal.status == "finished" and not journal.issues
    assert [(s.step_id, s.status) for s in journal.steps][-1] == ("quality", "valid")
    assert store.payload(journal.steps[-1].payload_sha256) == submitted.payload
    head = next(h for h in store.read().heads if h.module_id == "CP-1")
    assert head.status == "restricted" and head.qualification == PROMOTED
    assert head.result_sha256 == journal.result_sha256


def test_a_lineage_above_its_ceiling_is_rejected_with_the_validators_message(
    quality_journal: tuple[Execution, str, QualityInputs],
) -> None:
    store, ticket_id, inputs = quality_journal
    ceilings = {c.evidence_id: c.ceiling for c in inputs.ceilings}
    claim = inputs.claims[0]
    evidence_id = next(e for e in claim.evidence_ids if ceilings[e] == "Calculated")
    _, payload = unbound_review(inputs)
    document = json.loads(payload)
    for item in document["claims"][0]["evidence"]:
        if item["evidence_id"] == evidence_id:
            item["lineage_class"] = "Directly Sourced"
    submitted = submit_model_payload(store, ticket_id, "quality", json.dumps(document))
    journal = submitted.journal
    upgrade = (
        f"QA lineage upgrade rejected: {evidence_id} Directly Sourced above ceiling Calculated"
    )
    assert journal.status == "finished" and upgrade in journal.issues
    assert journal.steps[-1].status == "invalid" and upgrade in journal.steps[-1].issues
    # `quality` settles the module: no within-attempt repair (task 7.0g); the 7.0e repair remains.
    assert journal.step_repairs == ()
    assert store.result(journal.result_sha256 or "").status == "rejected"
    assert not [h for h in store.read().heads if h.module_id == "CP-1"]
    repair = store.begin("CP-1")
    assert repair.number == 1 and upgrade in repair.repair_issues


def test_a_wrong_supplied_binding_is_overwritten_and_recorded(
    quality_journal: tuple[Execution, str, QualityInputs],
) -> None:
    store, ticket_id, inputs = quality_journal
    _, payload = unbound_review(inputs)
    document = {**json.loads(payload), "inputs_sha256": ZERO}
    submitted = submit_model_payload(store, ticket_id, "quality", json.dumps(document))
    assert submitted.prefilled == ("inputs_sha256",)
    assert json.loads(submitted.payload)["inputs_sha256"] == inputs.content_hash()
    assert submitted.journal.status == "finished" and not submitted.journal.issues


def test_a_review_already_bound_right_is_kept_byte_for_byte(
    quality_journal: tuple[Execution, str, QualityInputs],
) -> None:
    store, ticket_id, inputs = quality_journal
    review, _ = unbound_review(inputs)
    payload = review.model_dump_json(indent=1)
    submitted = submit_model_payload(store, ticket_id, "quality", payload)
    assert submitted.prefilled == () and submitted.payload == payload
    assert store.payload(submitted.journal.steps[-1].payload_sha256) == payload
    assert submitted.journal.status == "finished" and not submitted.journal.issues


def test_quality_without_a_valid_readiness_step_raises_before_anything_is_written(
    tmp_path: Path,
) -> None:
    store, ticket_id, _ = journal_at(tmp_path, "readiness")  # narrative valid, no readiness
    for ticket, missing in ((ticket_id, "readiness"), ("absent-ticket", "source_context")):
        before = store.read().content_hash()
        files = sorted(store.directory.rglob("*"))
        with pytest.raises(ValueError, match=f"no valid {missing} step to bind"):
            submit_model_payload(store, ticket, "quality", "{}")
        assert store.read().content_hash() == before
        assert sorted(store.directory.rglob("*")) == files


def test_the_validator_still_rejects_a_wrong_qa_binding_that_the_prefill_writes(
    quality_journal: tuple[Execution, str, QualityInputs], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 1: the pre-fill and the validation compute the QA inputs independently, so a
    wrong value from the pre-fill side is still refused by `validate_quality_review` (as the
    7.0i bypass test shows for the stage bindings) and nothing is promoted."""
    from deploy_vii.live import submission

    store, ticket_id, inputs = quality_journal

    def wrong(store: Execution, ticket_id: str) -> QualityInputs:
        return inputs.model_copy(update={"coverage_policy": "drifted-policy/1"})

    monkeypatch.setattr(submission, "quality_inputs", wrong)
    _, payload = unbound_review(inputs)
    submitted = submit_model_payload(store, ticket_id, "quality", payload)
    written = json.loads(submitted.payload)["inputs_sha256"]
    assert written == wrong(store, ticket_id).content_hash() != inputs.content_hash()
    assert submitted.journal.status == "finished"
    assert "QA review does not bind current inputs" in submitted.journal.issues
    assert not [h for h in store.read().heads if h.module_id == "CP-1"]


def test_qa_inputs_python_cannot_compute_refuse_the_review_before_the_write(
    quality_journal: tuple[Execution, str, QualityInputs],
) -> None:
    """R5: registers that do not stage leave no `inputs_sha256` to fill; the review is refused
    with the staging issue and nothing is written. Here the narrative step's retained output
    blob is gone, so the readiness stage cannot be recomputed."""
    store, ticket_id, inputs = quality_journal
    attempt = next(a for a in store.read().attempts if a.ticket_id == ticket_id)
    output = attempt.steps[2].output_sha256
    assert output is not None
    (store.directory / "blobs" / output).unlink()
    _, payload = unbound_review(inputs)
    before = store.read().content_hash()
    files = sorted(store.directory.rglob("*"))
    with pytest.raises(ValueError, match=f"QA inputs cannot be computed: .*{output} is missing"):
        submit_model_payload(store, ticket_id, "quality", payload)
    assert store.read().content_hash() == before
    assert sorted(store.directory.rglob("*")) == files
