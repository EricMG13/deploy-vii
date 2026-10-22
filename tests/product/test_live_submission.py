"""Decision 0008 (MC-1): the model returns judgments and quotes; Python composes the review."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from deploy_vii.contracts import Source, Span
from deploy_vii.live.schema import strict_schema, unverified_keywords
from deploy_vii.live.submission import (
    NOT_ASSESSED,
    STEPS,
    SUPERSEDED_SHAPE,
    ConsumerJudgment,
    ReadinessSubmission,
    SubmittedCitation,
    compose,
    compose_payload,
    rejection_issues,
)
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import (
    absent_page_ranges,
    coverage_issues,
    extraction_coverage,
    live_consumers,
    validate_review,
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
