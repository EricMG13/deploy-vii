"""SYNTHETIC CP-3 market evidence (task 8.3): invented quotes and terms, never market data.

Coordinator ruling 1: market evidence enters only as a `third_party` pack source (CP-0 classes
the source; no new source kind, no ingest). `MARKET_TEXT` is one small dealer-sheet text, every
line labelled SYNTHETIC: two observed levels and one line of indicative price talk. `market_pack`
adds it to the one-line readiness fixture pack; `market_review` is the CP-0 review of both
sources (the filing `unknown`, the sheet `third_party`). `FACILITIES` are CP-1 Debt Facility
Register (T4.18) facts in the canonical interface shape (`facility_id`, `facility_name`,
`seniority`, `secured_status`, `maturity_date` and a spread or fixed-rate figure); their figures
carry a SYNTHETIC calculation id instead of a citation, so they are referencable without
inventing a source span. Only `test_cp3_relative_value.py` imports this module.
"""

from decimal import Decimal

from deploy_vii.business_context import BusinessContextSubmission, SourceUse
from deploy_vii.contracts import Citation, Fact
from deploy_vii.preparation import PreparedPack, SourceRequest, prepare_source
from deploy_vii.readiness import ReadinessReview, SourceAssessment
from tests.product.test_business_context import submission_fixture
from tests.product.test_readiness import readiness_fixture

MARKET = "market-sheet"
MARKET_TEXT = (
    "SYNTHETIC dealer sheet for protocol tests; not market data\n"
    "SYNTHETIC: on 30 June 2026 the Term Loan B-2 was quoted at 99.25 bid\n"
    "SYNTHETIC: on 30 June 2026 the 6.250% senior notes due 2030 traded at 97.50\n"
    "SYNTHETIC: indicative price talk for the revolver extension is SOFR plus 300 area\n"
)
TLB_LINE = ("line:2", "the Term Loan B-2 was quoted at 99.25 bid")
NOTES_LINE = ("line:3", "the 6.250% senior notes due 2030 traded at 97.50")
TALK_LINE = ("line:4", "indicative price talk for the revolver extension is SOFR plus 300 area")
MARKET_LIMITATION = "SYNTHETIC dealer sheet; not market data"


def market_pack() -> PreparedPack:
    """The readiness fixture pack with the SYNTHETIC dealer sheet as a second source."""
    pack, _ = readiness_fixture()
    sheet = prepare_source(
        SourceRequest(source_id=MARKET, path="market-sheet.txt", media_type="text/plain"),
        MARKET_TEXT.encode(),
    )
    return PreparedPack(run=pack.run, sources=(*pack.sources, sheet))


def market_review(pack: PreparedPack) -> ReadinessReview:
    """The readiness fixture review over `pack`: the filing as before, the sheet `third_party`,
    and each consumer's attachment set unchanged (the filing)."""
    _, review = readiness_fixture()
    sheet = next(s for s in pack.sources if s.source_id == MARKET)
    assert sheet.sha256
    cited = Citation(
        source_id=MARKET,
        source_sha256=sheet.sha256,
        locator="line:1",
        quote="SYNTHETIC dealer sheet for protocol tests; not market data",
    )
    assessment = SourceAssessment(
        source_id=MARKET,
        document_family="synthetic dealer sheet",
        authority="third_party",
        entity="Synthetic issuer",
        period="30 June 2026",
        version_relationship="standalone synthetic fixture",
        fidelity="verified",
        citations=(cited,),
        limitations=(MARKET_LIMITATION,),
    )
    return review.model_copy(
        update={"pack_sha256": pack.content_hash(), "sources": (*review.sources, assessment)}
    )


def cp1a_submission(pack: PreparedPack) -> BusinessContextSubmission:
    """The CP-1A fixture submission over `pack`, assessing the sheet too (CP-1A assesses every
    prepared source exactly once)."""
    base = submission_fixture(pack)
    sheet = next(s for s in pack.sources if s.source_id == MARKET)
    assert sheet.spans
    use = SourceUse(
        source_id=MARKET,
        source_class="third_party",
        quality="Insufficient",
        period=None,
        entity_covered="Synthetic issuer",
        data_supplied="SYNTHETIC trading levels",
        use="Not a business source",
        citations=(),
        limitation=MARKET_LIMITATION,
    )
    return base.model_copy(update={"sources": (*base.sources, use)})


def _fact(row: str, field: str, *, text: str | None = None, **figure: object) -> Fact:
    if text is not None:
        return Fact(
            fact_id=f"T4.18.{row}.{field}",
            label=field,
            table_id="T4.18",
            row_id=row,
            field=field,
            text=text,
        )
    return Fact(
        fact_id=f"T4.18.{row}.{field}",
        label=str(figure["label"]),
        table_id="T4.18",
        row_id=row,
        field=field,
        amount=Decimal(str(figure["amount"])),
        unit=str(figure["unit"]),
        period="FY2025",
        calculation_id=f"synthetic-{row}-{field}",
        formula="SYNTHETIC fixture value",
        calculation_status="calculated",
    )


def _facility(
    row: str, facility_id: str, name: str, secured: str, maturity: str, figure: Fact
) -> tuple[Fact, ...]:
    return (
        _fact(row, "facility_id", text=facility_id),
        _fact(row, "facility_name", text=name),
        _fact(row, "seniority", text="Senior"),
        _fact(row, "secured_status", text=secured),
        _fact(row, "maturity_date", text=maturity),
        figure,
    )


TLB_SPREAD = "{T4.18.tlb-fy2025.spread_bps|bp}"
FACILITIES: tuple[Fact, ...] = (
    *_facility(
        "tlb-fy2025",
        "tlb",
        "Term Loan B-2",
        "Secured",
        "2031-06-30",
        _fact(
            "tlb-fy2025",
            "spread_bps",
            label="Term Loan B-2 spread",
            amount=350,
            unit="basis_points",
        ),
    ),
    *_facility(
        "notes-fy2025",
        "notes",
        "Senior notes due 2030",
        "Unsecured",
        "2030-11-15",
        _fact(
            "notes-fy2025",
            "fixed_rate",
            label="Senior notes fixed rate",
            amount="0.0625",
            unit="decimal_percent",
        ),
    ),
    *_facility(
        "revolver-fy2025",
        "revolver",
        "Revolving credit facility",
        "Secured",
        "2028-03-31",
        _fact(
            "revolver-fy2025",
            "spread_bps",
            label="Revolver spread",
            amount=250,
            unit="basis_points",
        ),
    ),
)
