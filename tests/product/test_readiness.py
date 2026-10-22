import hashlib
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from deploy_vii.contracts import Citation, Claim, Source, Span
from deploy_vii.live.submission import (
    ClaimJudgment,
    ConsumerJudgment,
    GapJudgment,
    ReadinessSubmission,
    SourceJudgment,
    SubmittedCitation,
)
from deploy_vii.preparation import PreparedPack, SourceRequest, prepare_source
from deploy_vii.quotes import normalise, quoted
from deploy_vii.readiness import (
    ConsumerReadiness,
    ReadinessGap,
    ReadinessReview,
    SourceAssessment,
    build_readiness,
    citation_issues,
    validate_review,
)
from deploy_vii.registry import plan
from tests.product.test_render import synthetic_view


def readiness_fixture() -> tuple[PreparedPack, ReadinessReview]:
    source = prepare_source(
        SourceRequest(source_id="filing", path="filing.txt", media_type="text/plain"),
        b"Synthetic issuer FY2025 cash USD million 0\n",
    )
    pack = PreparedPack(run=synthetic_view().run, sources=(source,))
    assert source.sha256
    citation = Citation(
        source_id="filing",
        source_sha256=source.sha256,
        locator="line:1",
        quote="Synthetic issuer FY2025 cash USD million 0",
    )
    limitations = ("Synthetic partial source pack; full underwriting documents absent",)
    consumers = tuple(
        ConsumerReadiness(
            module_id=module_id,
            readiness="READY_WITH_LIMITATIONS",
            evidence_demand="Bounded source-limited test only",
            source_ids=("filing",),
            rationale="Synthetic test input only",
            citations=(citation,),
            limitations=limitations,
        )
        for module_id in plan(pack.run.requested_modules)
        if module_id != "CP-0"
    )
    review = ReadinessReview(
        pack_sha256=pack.content_hash(),
        objective="Exercise source-limited fixture handling",
        reporting_period="FY2025",
        issuer_confirmed=True,
        sources=(
            SourceAssessment(
                source_id="filing",
                document_family="synthetic text fixture",
                authority="unknown",
                entity="Synthetic issuer",
                period="FY2025",
                version_relationship="standalone synthetic fixture",
                fidelity="verified",
                citations=(citation,),
                limitations=limitations,
            ),
        ),
        consumers=consumers,
        gaps=(
            ReadinessGap(
                gap_id="missing-pack",
                kind="source",
                severity="material",
                description=limitations[0],
                affected_modules=tuple(item.module_id for item in consumers),
                remediation="Supply a frozen public issuer pack",
            ),
        ),
        analysis=(
            Claim(
                claim_id="readiness",
                text="Synthetic text is readable but cannot establish full underwriting readiness.",
                citations=(citation,),
            ),
        ),
    )
    return pack, review


def as_submission(review: ReadinessReview) -> ReadinessSubmission:
    """The model-facing submission that composes into `review` (decision 0008): the review
    without its hashes, pack binding and attachment sets."""

    def cited(citations: tuple[Citation, ...]) -> tuple[SubmittedCitation, ...]:
        return tuple(
            SubmittedCitation(source_id=c.source_id, locator=c.locator, quote=c.quote)
            for c in citations
        )

    return ReadinessSubmission(
        objective=review.objective,
        reporting_period=review.reporting_period,
        issuer_confirmed=review.issuer_confirmed,
        sources=tuple(
            SourceJudgment(
                **item.model_dump(exclude={"citations"}), citations=cited(item.citations)
            )
            for item in review.sources
        ),
        consumers=tuple(
            ConsumerJudgment(
                **item.model_dump(exclude={"citations", "source_ids"}),
                citations=cited(item.citations),
            )
            for item in review.consumers
        ),
        gaps=tuple(
            GapJudgment(**item.model_dump(exclude={"citations"}), citations=cited(item.citations))
            for item in review.gaps
        ),
        analysis=tuple(
            ClaimJudgment(**item.model_dump(exclude={"citations"}), citations=cited(item.citations))
            for item in review.analysis
        ),
    )


def submission_fixture() -> tuple[PreparedPack, ReadinessSubmission]:
    pack, review = readiness_fixture()
    return pack, as_submission(review)


def test_cp0_preserves_all_registers_exact_lineage_and_no_final_verdict() -> None:
    pack, review = readiness_fixture()
    assert validate_review(pack, review) == ()
    module = build_readiness(pack, review)
    assert module.status == "candidate"
    assert module.inputs[0].sha256 == pack.content_hash()
    assert {fact.table_id for fact in module.facts} == {
        "P3",
        "P5",
        "T1",
        "T2",
        "T3",
        "T4",
        "T5",
        "T6",
        "T7",
        "T8",
    }
    assert any(fact.text == "Run CP-1" for fact in module.facts)
    assert any("Synthetic" in text for text in module.limitations)
    assert not [fact for fact in module.facts if fact.amount is not None]


def test_changed_pack_unavailable_and_false_quotes_rejected() -> None:
    pack, review = readiness_fixture()
    assert (
        "Review does not bind"
        in validate_review(pack, review.model_copy(update={"pack_sha256": "0" * 64}))[0]
    )
    valid = review.analysis[0].citations[0]
    for update in (
        {"quote": "invented"},
        {"locator": "line:99"},
        {"source_sha256": "0" * 64},
        {"source_id": "missing"},
    ):
        assert citation_issues((valid.model_copy(update=update),), pack.sources)
    corrupt = review.model_copy(
        update={
            "analysis": (
                review.analysis[0].model_copy(
                    update={"citations": (valid.model_copy(update={"quote": "invented"}),)}
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="Quote/locator"):
        build_readiness(pack, corrupt)


def test_cannot_discard_source_consumer_or_limitations() -> None:
    pack, review = readiness_fixture()
    assert validate_review(pack, review.model_copy(update={"sources": ()}))
    assert validate_review(pack, review.model_copy(update={"consumers": review.consumers[:-1]}))
    optimistic = review.consumers[0].model_copy(update={"readiness": "READY", "limitations": ()})
    issues = validate_review(
        pack, review.model_copy(update={"consumers": (optimistic, *review.consumers[1:])})
    )
    assert any("limitations" in issue for issue in issues)
    assert any("gap" in issue for issue in issues)


def test_conditional_command_cannot_be_executed() -> None:
    pack, review = readiness_fixture()
    conditional = ConsumerReadiness(
        module_id="CP-1",
        readiness="CONDITIONAL",
        evidence_demand="Financial statements",
        source_ids=(),
        citations=(),
        rationale="No usable financial statements supplied",
        missing_source="Audited FY2025 statements",
        limitations=("Audited FY2025 statements absent",),
    )
    changed = review.model_copy(
        update={
            "consumers": tuple(
                conditional if item.module_id == "CP-1" else item for item in review.consumers
            )
        }
    )
    module = build_readiness(pack, changed)
    assert (
        next(fact.text for fact in module.facts if fact.fact_id == "T8.CP-1.exact_command")
        == "DO NOT RUN"
    )


def test_prepared_pack_and_review_survive_json_roundtrip(tmp_path: Path) -> None:
    pack, review = readiness_fixture()
    path = tmp_path / "review.json"
    path.write_text(review.model_dump_json())
    restored = ReadinessReview.model_validate_json(path.read_bytes())
    assert build_readiness(pack, restored) == build_readiness(pack, review)


def test_frozen_copy_does_not_bypass_required_limitations_or_nonempty_quote() -> None:
    pack, review = readiness_fixture()
    missing_limit = review.model_copy(
        update={
            "consumers": tuple(
                item.model_copy(update={"limitations": ()}) for item in review.consumers
            )
        }
    )
    assert validate_review(pack, missing_limit)[0] == (
        "consumers.0: Value error, non-ready consumer requires limitations"
    )
    citation = review.analysis[0].citations[0].model_copy(update={"quote": ""})
    corrupt = review.model_copy(
        update={"analysis": (review.analysis[0].model_copy(update={"citations": (citation,)}),)}
    )
    assert validate_review(pack, corrupt) == (
        "analysis.0.citations.0.quote: String should have at least 1 character",
    )


def test_source_classification_cannot_use_other_source_quote() -> None:
    pack, review = readiness_fixture()
    second = prepare_source(
        SourceRequest(source_id="other", path="other.txt", media_type="text/plain"),
        b"Other issuer and period",
    )
    pack = pack.model_copy(update={"sources": (*pack.sources, second)})
    assert second.sha256
    other_citation = Citation(
        source_id="other",
        source_sha256=second.sha256,
        locator="line:1",
        quote="Other issuer and period",
    )
    original = review.sources[0]
    review = review.model_copy(
        update={
            "pack_sha256": pack.content_hash(),
            "sources": (
                original.model_copy(update={"citations": (other_citation,)}),
                original.model_copy(update={"source_id": "other", "citations": (other_citation,)}),
            ),
        }
    )
    assert any("different source" in issue for issue in validate_review(pack, review))


def test_reverse_review_order_does_not_change_dependency_command_order() -> None:
    pack, review = readiness_fixture()
    module = build_readiness(
        pack, review.model_copy(update={"consumers": tuple(reversed(review.consumers))})
    )
    commands = [
        fact.row_id
        for fact in module.facts
        if fact.table_id == "T8" and fact.field == "exact_command"
    ]
    assert commands == list(plan(pack.run.requested_modules))[1:]


# --- quote matching (task 2.9 fix 1): layout whitespace and quote marks, never cross-page -----

# Verbatim excerpts of the Caesars FY2025 pack (`czr-2025-10k`) spans the probe-3 quotes cite.
P4 = (
    f"l on the NASDAQ Stock Market is {chr(0x201C)}CZR.{chr(0x201D)}\n\nOur primary source of "
    "revenue is generated "
    "by our gaming operations, which includes our casino properties, retail and online sports "
    "betting and online\ngaming. Additionally, we utilize our hotels, re"
)
P27 = "The growth of our online betting and gaming business will depend on expansion of"
P28 = (
    "al condition and results of operations.\nItem 1B.    Unr                   esolved Staff "
    "Comments\n\nNone.\nItem 1C.    Cybersecurity\n\nRisk "
)
P45 = (
    "e rent adjustment begins November 2027. We estimate our lease payments to VICI and GLPI "
    "to be\napproximately $1.4 billion for 2026.\n\nWe  make  capital  expenditures  and  "
)
P77 = (
    "The CEI Revolving Credit Facility, the CEI Term Loan A, the CEI Term Loan B, the CEI Term "
    "Loan B-1 and the indentures governing the CEI Senior\nSecured Notes due 2030"
)
LUNA_P45 = (
    "We estimate our lease payments to VICI and GLPI to be approximately $1.4 billion for 2026."
)
LUNA_P27 = "Item 1B.    Unr                   esolved Staff Comments"
GLM_P4 = (
    "Our primary source of revenue is generated by our gaming operations, which includes our "
    "casino properties, retail and online sports betting and online gaming."
)
LUNA_P77 = (
    "The CEI Revolving Credit Facility, the CEI Term Loan A, the CEI Term Loan B, the CEI Term "
    "Loan B-1 and the indentures governing the CEI Senior Secured Notes due 2030"
)
RULE = "normalised whitespace, quote marks and dashes"


def paged_source(**pages: str) -> Source:
    """`paged_source(p4=...)` holds the span `page:4`."""
    spans = tuple(Span(locator="page:" + name[1:], text=text) for name, text in pages.items())
    return Source(
        source_id="czr-2025-10k",
        name="FY2025 Form 10-K",
        status="ready",
        sha256=hashlib.sha256("".join(pages.values()).encode()).hexdigest(),
        spans=spans,
    )


def cite(source: Source, locator: str, quote: str) -> Citation:
    assert source.sha256
    return Citation(
        source_id=source.source_id, source_sha256=source.sha256, locator=locator, quote=quote
    )


def test_probe_3_layout_quotes_match_under_their_own_locator() -> None:
    source = paged_source(p4=P4, p28=P28, p45=P45, p77=P77)
    # Each differs from its span only in whitespace: Luna f136b227/8634aa17 p45, Luna f136b227
    # p77 and GLM 76fc5c95 p4 by a line break (the probe-3 analysis inferred a misquote for p4
    # and a wrong page for p77 from grep counts), the "Item 1B" heading by its space runs.
    found = citation_issues(
        (
            cite(source, "page:45", LUNA_P45),
            cite(source, "page:4", GLM_P4),
            cite(source, "page:28", LUNA_P27),
            cite(source, "page:77", LUNA_P77),
            cite(source, "page:4", 'Stock Market is "CZR."'),  # straight quotes for curly
        ),
        (source,),
    )
    assert found == ()


def test_a_quote_is_never_rescued_from_another_page_or_stitched_together() -> None:
    source = paged_source(p27=P27, p28=P28, p45=P45, p77=P77)
    stitched = "We estimate our lease payments to VICI and GLPI to be approximately $1.4 billion."
    issues = citation_issues(
        (
            cite(source, "page:27", LUNA_P27),  # Luna 8634aa17: the heading is on page 28
            cite(source, "page:45", LUNA_P77),  # page 77's text cited under page 45
            cite(source, "page:45", stitched),  # fragments joined across the sentence
            cite(source, "page:45", LUNA_P45.lower()),  # case is compared exactly
            cite(source, "page:99", LUNA_P45),  # no such locator
        ),
        (source,),
    )
    assert issues == (
        f"Quote/locator mismatch: quote not found under czr-2025-10k page:27 ({RULE}): "
        '"Item 1B. Unr esolved Staff Comments"',
        f"Quote/locator mismatch: quote not found under czr-2025-10k page:45 ({RULE}): "
        '"The CEI Revolving Credit Facility, the CEI Term Loan A, the …"',
        f"Quote/locator mismatch: quote not found under czr-2025-10k page:45 ({RULE}): "
        '"We estimate our lease payments to VICI and GLPI to be approx…"',
        f"Quote/locator mismatch: quote not found under czr-2025-10k page:45 ({RULE}): "
        '"we estimate our lease payments to vici and glpi to be approx…"',
        "Quote/locator mismatch: no locator page:99 in czr-2025-10k: "
        '"We estimate our lease payments to VICI and GLPI to be approx…"',
    )


def test_a_quote_joining_the_tail_of_one_page_to_the_head_of_the_next_is_rejected() -> None:
    source = paged_source(p27=P27, p28=P28)
    joined = P27[-30:] + " " + P28[:30]  # one sentence across the page break
    for locator in ("page:27", "page:28"):
        assert citation_issues((cite(source, locator, joined),), (source,))
    assert not quoted(joined, P27) and not quoted(joined, P28)
    assert quoted(joined, P27 + " " + P28)  # only the join of both spans would hold it


def test_a_quote_with_reordered_words_is_rejected() -> None:
    source = paged_source(p45=P45)
    reordered = "We estimate our lease payments to GLPI and VICI to be approximately $1.4 billion"
    assert citation_issues((cite(source, "page:45", reordered),), (source,))
    assert quoted(reordered.replace("GLPI and VICI", "VICI and GLPI"), P45)  # the original holds


def test_each_failing_citation_is_its_own_issue_even_on_one_page() -> None:
    source = paged_source(p45=P45)
    issues = citation_issues(
        (cite(source, "page:45", "invented one"), cite(source, "page:45", "invented two")),
        (source,),
    )
    assert len(issues) == 2 and issues[0] != issues[1]


@pytest.mark.parametrize(
    ("quote", "text"),
    [
        (f"lease {chr(0x201C)}payments{chr(0x201D)}", 'lease "payments"'),
        ('lease "payments"', f"lease {chr(0x201E)}payments{chr(0x201F)}"),
        (f"the issuer{chr(0x2019)}s notes", "the issuer's notes"),
        ("the issuer's notes", f"the issuer{chr(0x2018)}s notes"),
        ("2026-2032", f"2026{chr(0x2013)}2032"),
        (f"Term Loan B{chr(0x2014)}1", "Term Loan B-1"),
        (f"net {chr(0x2212)}1.4", "net -1.4"),
        ("Unresolved", f"Unre{chr(0x00AD)}solved"),
        ("lease payments", f"lease{chr(0x00A0)}payments"),
        ("lease payments", "lease \n\t payments"),
        ("  lease   payments  ", "the lease payments"),
    ],
)
def test_normalisation_covers_layout_whitespace_quote_marks_dashes_and_soft_hyphens(
    quote: str, text: str
) -> None:
    assert quoted(quote, text)


@pytest.mark.parametrize("quote", [" ", chr(0x00AD), "\n" + chr(0x00A0)])
def test_a_quote_with_no_visible_text_matches_nothing(quote: str) -> None:
    assert not quoted(quote, "any text at all")
    source = paged_source(p1="any text at all")
    assert citation_issues((cite(source, "page:1", quote),), (source,)) == (
        f'Quote/locator mismatch: quote not found under czr-2025-10k page:1 ({RULE}): ""',
    )


@given(st.text(), st.integers(min_value=0, max_value=200), st.integers(min_value=0, max_value=60))
def test_every_exact_substring_still_matches(text: str, start: int, length: int) -> None:
    """Normalisation only widens matching: an exact substring with visible text always passes."""
    start = start % (len(text) + 1)
    quote = text[start : start + length]
    if normalise(quote).strip():
        assert quoted(quote, text)


# --- 2.10: hyphen-wrap on the span side (probe-4, Sol 9594d016) ------------------------------

# Verbatim excerpts of the Caesars FY2025 10-K pack spans Sol 9594d016 cited.
P135 = (
    "        This FIRST AMENDMENT TO SECOND AMENDED AND RESTATED PUT-\nCALL  RIGHT  AGREEMENT"
    f"                  (this  {chr(0x201C)}Amendment{chr(0x201D)})  is  entered  into  as  of  "
    "May  1,  2023"
)
P13 = (
    "actors. Such forward-looking statements are only predictions and involve known and unknown "
    "risks\nand  uncertainties,  many  of  which  are  beyond  our  control"
)
P104 = (
    "   10.30        Credit Agreement, dated as of July 20, 2020, by and among Eldorado Resorts, "
    "Inc., the lenders party thereto from time                             Previously filed on "
    "Form 8-K filed\n                to time, JPMorgan Chase Bank, N.A., as administrative agent, "
    "and U.S. Bank National Association, as collateral agent.                             on July "
    "21, 2020."
)
# Sol 9594d016's quotes, verbatim.
SOL_P135 = "This FIRST AMENDMENT TO SECOND AMENDED AND RESTATED PUT-CALL RIGHT AGREEMENT"
SOL_P13 = (
    "Forward-looking statements are only predictions and involve known and unknown risks and "
    "uncertainties"
)
SOL_P104 = (
    "Credit Agreement, dated as of July 20, 2020, by and among Eldorado Resorts, Inc., the "
    "lenders party thereto from time to time, JPMorgan Chase Bank, N.A., as administrative agent, "
    "and U.S. Bank National Association, as collateral agent."
)
WRAP_RULE = f"{RULE}; hyphen-wrap"


def test_a_quote_that_rejoins_a_hyphenated_line_wrap_passes() -> None:
    source = paged_source(p135=P135)
    assert not quoted(SOL_P135, normalise(P135))  # the 2.9 normalisation alone rejected it
    assert quoted(SOL_P135, P135)
    assert citation_issues((cite(source, "page:135", SOL_P135),), (source,)) == ()


def test_hyphen_wrap_only_widens_the_span_side() -> None:
    assert quoted("RESTATED PUT- CALL RIGHT", P135)  # the line break copied as a space still holds
    assert quoted("PUT-\nCALL", P135)  # and the exact text
    assert not quoted("PUTCALL RIGHT", P135)  # the hyphen itself is never dropped
    assert not quoted("PUT-CALL", "PUT- CALL")  # a hyphen then a space is not a line wrap
    assert not quoted("PUT CALL", "PUT-\nCALL")  # nor is the model's hyphen ever altered
    assert quoted("PUT-CALL", "PUT-\n   CALL") and quoted("PUT-CALL", "PUT-\nCALL")


def test_hyphen_wrap_does_not_relax_case_or_column_interleave() -> None:
    p13, p104 = paged_source(p13=P13), paged_source(p104=P104)
    # p13: the source says "Such forward-looking statements"; case is compared exactly.
    assert citation_issues((cite(p13, "page:13", SOL_P13),), (p13,)) == (
        f"Quote/locator mismatch: quote not found under czr-2025-10k page:13 ({RULE}): "
        '"Forward-looking statements are only predictions and involve …"',
    )
    # p104: a two-column exhibit table interleaves "Previously filed on Form 8-K filed" between
    # "from time" and "to time" (a known layout limit, not handled); the shorter quote holds.
    assert citation_issues((cite(p104, "page:104", SOL_P104),), (p104,))
    shorter = SOL_P104.split(" to time,")[0]
    assert shorter.endswith("from time") and quoted(shorter, P104)


def test_the_issue_names_hyphen_wrap_only_where_the_span_has_one() -> None:
    wrapped, plain = paged_source(p135=P135), paged_source(p13=P13)
    assert citation_issues((cite(wrapped, "page:135", "invented"),), (wrapped,)) == (
        f"Quote/locator mismatch: quote not found under czr-2025-10k page:135 ({WRAP_RULE}): "
        '"invented"',
    )
    assert f"({RULE}):" in citation_issues((cite(plain, "page:13", "invented"),), (plain,))[0]


@given(st.text(alphabet="ab -\n"), st.integers(min_value=0, max_value=200), st.integers(0, 60))
def test_every_exact_substring_of_a_wrapped_span_still_matches(
    text: str, start: int, length: int
) -> None:
    start = start % (len(text) + 1)
    quote = text[start : start + length]
    if normalise(quote).strip():
        assert quoted(quote, text)
