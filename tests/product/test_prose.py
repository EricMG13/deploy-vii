"""Run text (decision 0005 MC-2): numbers in model prose appear only as resolved references."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from deploy_vii.contracts import Citation, Claim, Fact, Module
from deploy_vii.execution import candidate_issues
from deploy_vii.prose import (
    LABELS,
    Run,
    bare_figures,
    check,
    issues,
    prose_issues,
    tokenize,
    valid_syntax,
)
from deploy_vii.readiness import build_readiness
from tests.product.test_execution import fixture_store, settled
from tests.product.test_readiness import readiness_fixture

REFS = ("revenue", "interface-fact:" + "a" * 64, "K.12", "ebitda_fy2025")
GAPS = ("cp1-gap:" + "b" * 64, "debt-missing")

ACCEPTED = (
    # Periods: fiscal, calendar, quarter, half, dates and years.
    "Leverage is stated for FY2025, FY25 and FY2025/26.",
    "Revenue fell in Q2 2026 against Q2 FY25.",
    "The H1 FY25 interim period is unaudited.",
    "Liquidity is measured at 30 June 2026.",
    "The covenant test date is June 30, 2026, per the agreement.",
    "Cash was tested on 2026-06-30 and again in 2027.",
    # Filing forms.
    "The 10-K, the 10-Q, an 8-K and a 20-F are in the pack; the 10-K/A restates nothing.",
    # Instrument descriptors: coupon with an instrument noun, maturity shorthand, tranches.
    "The 6.50% notes due 2032 rank behind the 6.00% senior secured notes.",
    "The 2032s trade wide of the 7.125% senior secured 2032s.",
    "Term Loan B-2 amortises; Tranche B-1 does not.",
    # Section references.
    "Item 1A and Note 12 describe the risk; Section 4.03(a) and Exhibit 10.1 set the test.",
    "Rule 144A notes are excluded under Article 6 and Schedule 2.",
    # Ordinal and version labels.
    "Method r14 applies; CP-1 and CP-1A feed the 2nd lien view in v2.1.",
    # References and gaps.
    "Revenue was {revenue|US$ m} in FY2025 and EBITDA {ebitda_fy2025}; "
    "debt is unknown [debt-missing].",
    "The calculated cover {K.12|x} rests on [interface-fact:" + "a" * 64 + "].",
    "No digits at all, only words.",
)

REJECTED = (
    "Debt is US$ 1.2bn.",
    "Leverage is 3.5x.",
    "Margin rose 12%.",
    "The issuer has 1,200 employees.",
    "A ratio of 0.5 applies.",
    "Revenue was {revenue|US$ m}, up 4%.",
    "More than \uff12 times",
    "Ratio \u00bd",
    "Debt exceeds 9999",
    "A 12% decline in notes",
    "Cash of US$2,928m",
    "The 2032 notes total 750",
    "FY2025e revenue",
)


@pytest.mark.parametrize("text", ACCEPTED)
def test_prose_runs_allow_labels(text: str) -> None:
    assert check(text, refs=REFS, gaps=GAPS) == ()


@pytest.mark.parametrize("text", REJECTED)
def test_prose_runs_reject_bare_figures(text: str) -> None:
    issues = check(text, refs=REFS, gaps=GAPS)
    assert issues and all(issue.startswith("Bare figure: ") for issue in issues)


def test_prose_runs_allow_labels_reject_bare_figures() -> None:
    """The table-driven contract of MC-2: at least 12 accepted, 8 rejected, every label class."""
    assert len(ACCEPTED) >= 12 and len(REJECTED) >= 8
    assert set(LABELS) == {"period", "filing", "instrument", "section", "ordinal"}
    for name, pattern in LABELS.items():
        assert any(pattern.search(text) for text in ACCEPTED), name
    assert all(check(text, refs=REFS, gaps=GAPS) == () for text in ACCEPTED)
    assert all(check(text, refs=REFS, gaps=GAPS) for text in REJECTED)
    assert bare_figures("Debt is US$ 1.2bn and 3.5x.") == ("1.2bn", "3.5x")


def test_unresolved_reference_is_an_issue() -> None:
    assert check("Debt {unknown|US$ m} rose.", refs=REFS, gaps=GAPS) == (
        "Unresolved reference: unknown",
    )
    assert check("See [nowhere].", refs=REFS, gaps=GAPS) == ("Unresolved reference: nowhere",)
    # A gap is shown as a gap run, never spelled as a figure.
    assert check("Debt {debt-missing} is open.", refs=REFS, gaps=GAPS) == (
        "Figure reference names a gap: debt-missing",
    )


@pytest.mark.parametrize(
    "text",
    [
        *("Debt {revenue", "Debt revenue}", "Debt {}", "Debt []", "Debt {|US$ m}"),
        *(
            "Debt {revenue|}",
            "Debt {revenue| }",
            "Debt { revenue }",
            "[a]b]",
            "Debt [revenue",
            "{" + "x" * 161 + "}",
            "Debt} then {revenue}",
        ),
    ],
)
def test_malformed_tokens_are_rejected_by_the_claim_contract(text: str) -> None:
    with pytest.raises(ValueError, match="Malformed run text"):
        valid_syntax(text)
    with pytest.raises(ValidationError, match="Malformed run text"):
        Claim(claim_id="c", text=text, citations=())
    assert check(text, refs=REFS, gaps=GAPS)[0].startswith("Malformed run text")
    assert issues(text, {})[0].startswith("Malformed run text")


def test_tokenize_classifies_figures_chips_and_gaps() -> None:
    runs = tokenize("Debt {revenue|US$ m} and [debt-missing] per [revenue].", gaps=GAPS)
    assert runs == (
        Run(kind="text", text="Debt "),
        Run(kind="ref", text="revenue", unit="US$ m", figure=True),
        Run(kind="text", text=" and "),
        Run(kind="gap", text="debt-missing"),
        Run(kind="text", text=" per "),
        Run(kind="ref", text="revenue"),
        Run(kind="text", text="."),
    )


def test_names_mask_only_their_own_digits() -> None:
    assert check("3M Company reports for FY2025.", refs=(), gaps=(), names=("3M Company",)) == ()
    assert check("3M Company had 12 plants.", refs=(), gaps=(), names=("3M Company",)) == (
        "Bare figure: 12",
    )


_WORDS = st.sampled_from(
    ["the", "issuer", "leverage", "rose", "and", "liquidity", "is", "adequate", "Revenue", "."]
)
_LABEL_SAMPLES = st.sampled_from(
    [
        "FY2025",
        "Q2 2026",
        "H1 FY25",
        "30 June 2026",
        "2026",
        "10-K",
        "20-F",
        "6.50% notes due 2032",
        "2032s",
        "Item 1A",
        "Note 12",
        "r14",
        "CP-1",
    ]
)
_TOKENS = st.one_of(
    st.sampled_from(REFS).map(lambda ref: "{" + ref + "|US$ m}"),
    st.sampled_from(REFS).map(lambda ref: "{" + ref + "}"),
    st.sampled_from((*REFS, *GAPS)).map(lambda ref: "[" + ref + "]"),
)
_SAFE = st.lists(st.one_of(_WORDS, _LABEL_SAMPLES, _TOKENS), max_size=12)


def _figure(number: int, decimals: int, suffix: str, comma: bool) -> str | None:
    """A number spelled as a figure; ``None`` where it would spell a bare year label."""
    detached = not comma and not decimals and suffix in {"", " per cent"}
    if detached and 1900 <= number <= 2099:
        return None
    body = f"{number:,}" if comma else str(number)
    if decimals:
        body += "." + "5" * decimals
    return body + suffix


_FIGURES = st.builds(
    _figure,
    st.integers(min_value=0, max_value=10**7),
    st.integers(min_value=0, max_value=3),
    st.sampled_from(["", "%", "x", "bn", "m", " per cent"]),
    st.booleans(),
).filter(lambda text: text is not None)


@given(_SAFE, _SAFE)
def test_digits_inside_references_and_labels_are_accepted(head: list[str], tail: list[str]) -> None:
    assert check(" ".join((*head, *tail)), refs=REFS, gaps=GAPS) == ()


@given(_SAFE, _FIGURES, _SAFE)
def test_any_digit_outside_labels_and_references_is_rejected(
    head: list[str], figure: str, tail: list[str]
) -> None:
    text = " ".join((*head, f"; {figure};", *tail))
    issues = check(text, refs=REFS, gaps=GAPS)
    assert issues and any(issue.startswith("Bare figure: ") for issue in issues)


def _module(*claims: Claim) -> Module:
    cite = Citation(source_id="S1", source_sha256="c" * 64, locator="p:1", quote="Revenue")
    facts = (
        Fact(
            fact_id="revenue",
            label="Revenue",
            amount=Decimal("1234.5"),
            unit="MILLIONS",
            currency="USD",
            period="FY2025",
            citations=(cite,),
        ),
        Fact(
            fact_id="cover",
            label="Cover",
            row_id="cover",
            amount=Decimal("2.5"),
            unit="MULTIPLE",
            period="FY2025",
            calculation_id="calc-cover",
        ),
        Fact(
            fact_id="debt",
            label="Debt",
            row_id="debt",
            status="missing",
            limitation="Not disclosed",
        ),
        Fact(fact_id="name", label="Name", row_id="name", text="Senior notes", citations=(cite,)),
        Fact(
            fact_id="bare",
            label="Uncited",
            row_id="bare",
            amount=Decimal("7"),
            unit="UNITS",
            period="FY2025",
        ),
    )
    return Module(
        run_id="r",
        issuer_id="i",
        as_of=date(2026, 10, 22),
        module_id="CP-0",
        facts=facts,
        claims=claims,
    )


def test_module_claims_resolve_against_their_own_facts() -> None:
    good = Claim(
        claim_id="good",
        text="Revenue {revenue|US$ m}, cover {calc-cover|x}, debt [debt], tranche [name] in FY25.",
        citations=(),
    )
    assert prose_issues(_module(good)) == ()
    bad = (
        Claim(claim_id="a", text="Debt {debt|US$ m}.", citations=()),
        Claim(claim_id="b", text="Revenue {revenue|%}.", citations=()),
        Claim(claim_id="c", text="Revenue [revenue].", citations=()),
        Claim(claim_id="d", text="Seven {bare}.", citations=()),
        Claim(claim_id="e", text="Debt rose 12% to {nothing}.", citations=()),
        Claim(claim_id="f", text="Name {name}.", citations=()),
    )
    assert prose_issues(_module(*bad)) == (
        "Claim a: Figure reference names a gap: debt",
        "Claim b: Unit % differs from the fact's unit US$ m: revenue",
        "Claim c: A numeric fact needs a figure reference {revenue|unit}",
        "Claim d: Figure reference has no citation or calculation: bare",
        "Claim e: Bare figure: 12%",
        "Claim e: Unresolved reference: nothing",
        "Claim f: Figure reference needs a known numeric fact: name",
    )


def test_a_calculation_id_on_two_facts_is_not_a_reference() -> None:
    module = _module(Claim(claim_id="x", text="Cover {calc-cover|x}.", citations=()))
    twin = module.facts[1].model_copy(update={"fact_id": "cover-twin", "row_id": "cover-twin"})
    doubled = module.model_copy(update={"facts": (*module.facts, twin)})
    assert prose_issues(doubled) == ("Claim x: Unresolved reference: calc-cover",)


def test_a_claim_with_a_bare_figure_is_rejected_at_settlement(tmp_path: Path) -> None:
    """MC-2 at module validation: the outcome is ``rejected``, before any module validator."""
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    _, review = readiness_fixture()
    candidate = build_readiness(store.pack(), review)
    claim = candidate.claims[0]
    labelled = candidate.model_copy(
        update={"claims": (claim.model_copy(update={"text": "Readable for FY2025 per the 10-K."}),)}
    )
    numeric = claim.model_copy(update={"text": "Readable for FY2025 in 3 of 4 sources [nowhere]."})
    payload = candidate.model_copy(update={"claims": (numeric,)})

    def must_not_run(_: Module) -> tuple[str, ...]:
        raise AssertionError("A claim with a bare figure reached the module validator")

    attempt = next(a for a in store.read().attempts if a.ticket_id == ticket.ticket_id)
    # Labels alone pass: the period and filing labels are not figures.
    assert candidate_issues(store.read(), attempt, labelled, pack=store.pack()) == ()
    result = store.finish(ticket.ticket_id, payload.model_dump_json(), must_not_run)
    assert result.issues == (
        "Claim readiness: Bare figure: 3",
        "Claim readiness: Bare figure: 4",
        "Claim readiness: Unresolved reference: nowhere",
    )
    assert settled(store, result).status == "rejected"
