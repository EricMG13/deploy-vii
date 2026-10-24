"""CP-4 legal covenant interpreter (task 8.2): the thin contract, the Python-only validator, the
Python headroom and the composed r14-id tables. SYNTHETIC data only: the indenture below is an
invented text, never an issuer's document, and every CP-1 figure is invented."""

import json
import random
import re
from decimal import Decimal
from fractions import Fraction
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from deploy_vii.bindings import validate_bindings
from deploy_vii.bindings.cp4 import BLOCKS, CP4
from deploy_vii.business_context import Gap
from deploy_vii.contracts import Citation, Claim, Fact, Input, Module, ModuleView, View
from deploy_vii.cp4_legal import (
    CP4_STEPS,
    MODULE_ID,
    NOT_CALCULABLE,
    REQUIRED_TABLES,
    STEP_ID,
    Basket,
    Covenant,
    CovenantInterpretationReport,
    CovenantInterpretationSubmission,
    LegalDocument,
    ProtectionScore,
    Quote,
    RedFlag,
    Upstream,
    context_block,
    covenant_interpretation,
    cp4_module,
    cp4_upstream,
    headroom,
    parse_threshold,
    submit_cp4_step,
    upstream_of,
    validate_covenant_interpretation,
)
from deploy_vii.execution import Execution, current_inputs
from deploy_vii.live.schema import schema_relaxations, strict_schema
from deploy_vii.preparation import PreparedPack, SourceRequest, prepare_source
from deploy_vii.prose import bare_figures
from deploy_vii.readiness import (
    ConsumerReadiness,
    ReadinessReview,
    SourceAssessment,
    build_readiness,
    validate_review,
)
from deploy_vii.registry import modules, plan
from deploy_vii.report_view import fact_spelling, pathways
from tests.product.test_render import synthetic_view

# --- the SYNTHETIC pack: a filed report, an executed indenture and a management deck ------------

INDENTURE = (
    "Section 4.09 Maximum Leverage. The Issuer shall not permit the Consolidated Net Leverage "
    "Ratio to exceed 5.00 to 1.00 as of the last day of any fiscal quarter.",
    '"Consolidated EBITDA" means net income plus interest expense, taxes, depreciation and '
    "amortisation, as adjusted for non-recurring items.",
    "Section 4.10 Limitation on Liens. The Issuer shall not create any Lien securing "
    "Indebtedness other than Permitted Liens.",
    "Section 4.07 Restricted Payments. The Issuer may make Restricted Payments in an aggregate "
    "amount not to exceed the greater of $50 million and 10% of Consolidated EBITDA.",
    "Section 4.11 Minimum Coverage. The Issuer shall maintain a ratio of Consolidated EBITDA to "
    "Consolidated Interest Expense of at least 2.50 to 1.00.",
    "This Indenture is dated as of March 1, 2025 among Synthetic Issuer Inc. and the Trustee.",
    "Section 4.12 Minimum Margin. The Issuer shall maintain an EBITDA margin of at least 10% "
    "for each fiscal year.",
)
FILING = "Synthetic issuer FY2025 annual report: net leverage is disclosed in the KPI table."
DECK = "Synthetic lender presentation: management expects ample covenant room."
AUTHORITY = {"filing": "filed", "indenture": "executed", "deck": "management"}


def legal_pack(deck: str = DECK, extra: str | None = None) -> PreparedPack:
    """The SYNTHETIC pack; `extra` is one more indenture line (line:8), for the wording cases."""
    lines = (*INDENTURE, extra) if extra is not None else INDENTURE
    texts = {"filing": FILING, "indenture": "\n".join(lines), "deck": deck}
    sources = tuple(
        prepare_source(
            SourceRequest(source_id=name, path=f"{name}.txt", media_type="text/plain"),
            (text + "\n").encode(),
        )
        for name, text in texts.items()
    )
    return PreparedPack(run=synthetic_view().run, sources=sources)


def cited(pack: PreparedPack, source_id: str, locator: str, quote: str) -> Citation:
    source = next(s for s in pack.sources if s.source_id == source_id)
    assert source.sha256
    return Citation(source_id=source_id, source_sha256=source.sha256, locator=locator, quote=quote)


def legal_review(pack: PreparedPack) -> ReadinessReview:
    note = ("Synthetic legal pack; not an issuer's documents",)
    first = {"filing": FILING[:30], "indenture": INDENTURE[0][:40], "deck": DECK[:30]}
    sources = tuple(
        SourceAssessment(
            source_id=name,
            document_family="synthetic text fixture",
            authority=AUTHORITY[name],  # type: ignore[arg-type]
            entity="Synthetic issuer",
            period="FY2025",
            version_relationship="standalone synthetic fixture",
            fidelity="verified",
            citations=(cited(pack, name, "line:1", first[name]),),
            limitations=note,
        )
        for name in AUTHORITY
    )
    consumers = tuple(
        ConsumerReadiness(
            module_id=module_id,
            readiness="READY_WITH_LIMITATIONS",
            evidence_demand="Bounded synthetic test only",
            source_ids=("indenture",),
            rationale="Synthetic test input only",
            citations=(cited(pack, "indenture", "line:1", INDENTURE[0][:40]),),
            limitations=note,
        )
        for module_id in plan(pack.run.requested_modules)
        if module_id != "CP-0"
    )
    review = ReadinessReview(
        pack_sha256=pack.content_hash(),
        objective="Exercise the CP-4 synthetic legal fixture",
        reporting_period="FY2025",
        issuer_confirmed=True,
        sources=sources,
        consumers=consumers,
        gaps=(),
        analysis=(
            Claim(
                claim_id="readiness",
                text="The synthetic indenture is readable for a bounded covenant test only.",
                citations=(cited(pack, "indenture", "line:1", INDENTURE[0][:40]),),
            ),
        ),
    )
    assert validate_review(pack, review) == ()
    return review


def cp0_module(pack: PreparedPack) -> Module:
    return build_readiness(pack, legal_review(pack))


def kpi(pack: PreparedPack, key: str, amount: str, unit: str = "MULTIPLE") -> Fact:
    return Fact(
        fact_id=f"T4.10.{key}.FY2025",
        label="FY2025",
        table_id="T4.10",
        row_id=key,
        field="FY2025",
        amount=Decimal(amount),
        unit=unit,
        period="FY2025: 2025-01-01 to 2025-12-31",
        basis="US GAAP · consolidated",
        citations=(cited(pack, "filing", "line:1", "net leverage is disclosed"),),
        value_class="calculated",
        formula=f"{key} recipe",
    )


def facility(pack: PreparedPack, facility_id: str, name: str) -> tuple[Fact, Fact]:
    citation = (cited(pack, "filing", "line:1", "Synthetic issuer FY2025"),)
    return (
        Fact(
            fact_id=f"T4.18.{facility_id}.facility_id",
            label="facility_id",
            table_id="T4.18",
            row_id=facility_id,
            field="facility_id",
            text=facility_id,
            citations=citation,
        ),
        Fact(
            fact_id=f"T4.18.{facility_id}.facility_name",
            label="facility_name",
            table_id="T4.18",
            row_id=facility_id,
            field="facility_name",
            text=name,
            citations=citation,
        ),
    )


def cp1_module(pack: PreparedPack, leverage: str = "4.20", coverage: str = "3.10") -> Module:
    run = pack.run
    return Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id="CP-1",
        status="accepted",
        facts=(
            kpi(pack, "net_leverage_reported", leverage),
            kpi(pack, "interest_coverage_reported", coverage),
            kpi(pack, "ebitda_margin", "0.25", unit="PERCENT"),
            *facility(pack, "TLB", "Term Loan B"),
            *facility(pack, "RCF", "Revolving Credit Facility"),
        ),
    )


def blocked_cp1(pack: PreparedPack) -> Module:
    run = pack.run
    return Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id="CP-1",
        status="blocked",
        attempt=1,
        limitations=("Malformed candidate: (root): Invalid JSON",),
    )


def inputs_for(pack: PreparedPack, cp0: Module, cp1: Module) -> tuple[Input, ...]:
    return (
        Input(input_id="prepared-pack", sha256=pack.content_hash()),
        Input(input_id="CP-0", sha256=cp0.content_hash(), status="restricted"),
        Input(input_id="CP-1", sha256=cp1.content_hash(), status=cp1.status),  # type: ignore[arg-type]
    )


def q(locator: int, quote: str, source_id: str = "indenture") -> Quote:
    return Quote(source_id=source_id, locator=f"line:{locator}", quote=quote)


LEVERAGE_QUOTE = q(1, "shall not permit the Consolidated Net Leverage Ratio to exceed 5.00 to 1.00")
COVERAGE_QUOTE = q(5, "of at least 2.50 to 1.00")
DEFINITION_QUOTE = q(2, '"Consolidated EBITDA" means net income plus interest expense')


def leverage_covenant(**changes: object) -> Covenant:
    row = Covenant(
        name="Maximum Consolidated Net Leverage Ratio",
        kind="maintenance",
        document_id="indenture",
        clause="Section 4.09 caps net leverage at each quarter end",
        definition_text="Consolidated EBITDA adds back interest, taxes and amortisation",
        test_formula="Consolidated net debt over Consolidated EBITDA",
        threshold_text="5.00 to 1.00",
        threshold_unit="multiple",
        threshold_value="5.00",
        comparison="<=",
        metric_ref="T4.10.net_leverage_reported.FY2025",
        metric_basis="Same definition",
        facility_ids=("TLB",),
        period_scope="Each fiscal quarter end",
        citations=(LEVERAGE_QUOTE, DEFINITION_QUOTE),
        limitation=None,
    )
    return row.model_copy(update=changes)


def coverage_covenant(**changes: object) -> Covenant:
    row = leverage_covenant(
        name="Minimum Interest Coverage Ratio",
        clause="Section 4.11 sets a floor on interest coverage",
        test_formula="Consolidated EBITDA over Consolidated Interest Expense",
        threshold_text="2.50 to 1.00",
        threshold_value="2.50",
        comparison=">=",
        metric_ref="T4.10.interest_coverage_reported.FY2025",
        facility_ids=("TLB", "RCF"),
        citations=(COVERAGE_QUOTE,),
    )
    return row.model_copy(update=changes)


def liens_covenant(**changes: object) -> Covenant:
    row = leverage_covenant(
        name="Limitation on Liens",
        kind="negative",
        clause="Section 4.10 bars liens other than Permitted Liens",
        definition_text="Permitted Liens is a defined term of the indenture",
        test_formula="No ratio test",
        threshold_text="not stated",
        threshold_unit="not stated",
        threshold_value=None,
        comparison="none",
        metric_ref=None,
        metric_basis="Not determinable",
        facility_ids=(),
        period_scope="At all times",
        citations=(q(3, "shall not create any Lien securing Indebtedness"),),
    )
    return row.model_copy(update=changes)


def submission_fixture(*, blocked: bool = False) -> CovenantInterpretationSubmission:
    """A valid synthetic submission over the indenture. With `blocked`, no CP-1 figure or facility
    is offered, so the rows name none."""
    unbound: dict[str, object] = (
        {"metric_ref": None, "metric_basis": "Not determinable", "facility_ids": ()}
        if blocked
        else {}
    )
    return CovenantInterpretationSubmission(
        documents=(
            LegalDocument(
                source_id="indenture",
                document_family="Indenture",
                governing_entity="Synthetic Issuer Inc.",
                date_or_amendment="Dated March 1, 2025; no amendment in the pack",
                citations=(q(6, "This Indenture is dated as of March 1, 2025"),),
                limitation=None,
            ),
        ),
        covenants=(
            leverage_covenant(**unbound),
            coverage_covenant(**unbound),
            liens_covenant(),
        ),
        capacity=(
            Basket(
                basket="Restricted payments general basket",
                permits="Restricted Payments up to a grower basket tied to Consolidated EBITDA",
                conditions="No condition beyond the cap is quoted",
                citations=(q(4, "the greater of $50 million and 10% of Consolidated EBITDA"),),
                limitation=None,
            ),
        ),
        red_flags=(
            RedFlag(
                flag="Grower basket",
                mechanic="Restricted payment capacity rises with Consolidated EBITDA",
                implication="Leakage capacity grows as add-backs grow",
                severity="Material",
                citations=(q(4, "10% of Consolidated EBITDA"),),
            ),
        ),
        protection_score=ProtectionScore(
            rating="Adequate",
            rationale="Two maintenance tests and a lien covenant protect lenders",
            basis="Section 4.09, Section 4.10 and Section 4.11",
            citations=(LEVERAGE_QUOTE, COVERAGE_QUOTE),
            limitation=None,
        ),
        gaps=(
            Gap(
                gap="No credit agreement in the pack",
                why_it_matters="Revolver springing tests cannot be read",
                affected_analysis="Covenant tests and headroom",
                severity="Material",
                action="Supply the executed credit agreement",
            ),
        ),
    )


def fixture(*, blocked: bool = False) -> tuple[PreparedPack, Upstream, tuple[Input, ...]]:
    pack = legal_pack()
    cp0 = cp0_module(pack)
    cp1 = blocked_cp1(pack) if blocked else cp1_module(pack)
    return pack, cp4_upstream(pack, cp0, cp1), inputs_for(pack, cp0, cp1)


def issues_of(
    submission: CovenantInterpretationSubmission, *, blocked: bool = False
) -> tuple[str, ...]:
    pack, upstream, inputs = fixture(blocked=blocked)
    return validate_covenant_interpretation(pack, submission, upstream, inputs)


def composed(
    submission: CovenantInterpretationSubmission | None = None, *, blocked: bool = False
) -> CovenantInterpretationReport:
    pack, upstream, inputs = fixture(blocked=blocked)
    submission = submission or submission_fixture(blocked=blocked)
    return covenant_interpretation(pack, submission, upstream, inputs)


def cells(report: CovenantInterpretationReport) -> dict[str, Fact]:
    return {fact.fact_id: fact for fact in report.facts}


def changed(
    submission: CovenantInterpretationSubmission, **lists: object
) -> CovenantInterpretationSubmission:
    return submission.model_copy(update=lists)


# --- acceptance, the r14 ids and the Python headroom (the oracle) ------------------------------


def test_a_valid_submission_composes_every_r14_table() -> None:
    assert issues_of(submission_fixture()) == ()
    report = composed()
    ids = [table.table_id for table in report.tables]
    assert len(REQUIRED_TABLES) == 31
    assert set(REQUIRED_TABLES) <= set(ids)
    assert len(ids) == len(set(ids))
    coverage = json.loads(Path("docs/methodology/r14-coverage.json").read_text(encoding="utf-8"))
    entry = next(m for m in coverage["modules"] if m["module_id"] == MODULE_ID)
    assert sorted(REQUIRED_TABLES) == sorted(entry["artifact_contract"]["required_table_ids"])
    assert (MODULE_ID, CP4_STEPS) == ("CP-4", (STEP_ID,))


def test_headroom_is_python_arithmetic_on_the_cp1_metric() -> None:
    found = cells(composed())
    # Maximum leverage: 5.00 threshold, CP-1 metric 4.20 -> 0.80x of room, 16% of the threshold.
    assert found["T4.9.r01.current"].amount == Decimal("4.20")
    assert found["T4.9.r01.headroom"].amount == Decimal("0.80")
    assert found["T4.9.r01.headroom"].unit == "MULTIPLE"
    assert found["T4.9.r01.headroom_share"].amount == Decimal("0.16")
    assert found["T4.9.r01.headroom_share"].unit == "PERCENT"
    assert found["T4.9.r01.test_on_cp_1_metric"].text == "Within threshold on the CP-1 metric"
    # Minimum coverage: 2.50 threshold, CP-1 metric 3.10 -> 0.60x of room, 24%.
    assert found["T4.9.r02.headroom"].amount == Decimal("0.60")
    assert found["T4.9.r02.headroom_share"].amount == Decimal("0.24")
    # A negative covenant has no ratio test: not applicable, and no own limitation for it.
    assert found["T4.9.r03.headroom"].status == "not_applicable"
    report = composed()
    assert not any("Limitation on Liens" in text for text in report.limitations)
    for fact_id in ("T4.9.r01.headroom", "T4.9.r01.headroom_share"):
        assert found[fact_id].value_class == "calculated" and found[fact_id].formula
        assert found[fact_id].period == "FY2025: 2025-01-01 to 2025-12-31"


def test_a_percentage_threshold_is_compared_as_a_decimal_fraction() -> None:
    base = submission_fixture()
    margin = leverage_covenant(
        name="Minimum EBITDA Margin",
        threshold_text="at least 10%",
        threshold_unit="percent",
        threshold_value="10",
        comparison=">=",
        metric_ref="T4.10.ebitda_margin.FY2025",
        citations=(q(7, "shall maintain an EBITDA margin of at least 10%"),),
    )
    submission = changed(base, covenants=(margin,))
    assert issues_of(submission) == ()
    found = cells(composed(submission))
    # CP-1 holds the margin as 0.25 (25%); the 10% floor is 0.10: 0.15 of room, 150% of it.
    # Fix round 1: room between two percentages is percentage points, shown as such (15 pp),
    # never as a percent of anything; the share stays a percent.
    room = found["T4.9.r01.headroom"]
    assert (room.amount, room.unit) == (Decimal("15.00"), "pp")
    assert fact_spelling(room, None)[2] == "15.00 pp"
    assert fact_spelling(found["T4.9.r01.headroom_share"], None)[2].endswith("%")
    assert found["T4.9.r01.headroom_share"].amount == Decimal("1.5")
    assert found["T4C.7.r01.parsed_value"].text == "10"
    assert found["T4F.3.r01.threshold_operand"].text == "0.1"
    assert found["T4F.3.r01.result"].text == "0.15"


def test_a_threshold_outside_the_test_is_reported_as_outside() -> None:
    pack = legal_pack()
    cp0, cp1 = cp0_module(pack), cp1_module(pack, leverage="5.40")
    report = covenant_interpretation(
        pack, submission_fixture(), cp4_upstream(pack, cp0, cp1), inputs_for(pack, cp0, cp1)
    )
    found = cells(report)
    assert found["T4.9.r01.headroom"].amount == Decimal("-0.40")
    assert found["T4.9.r01.test_on_cp_1_metric"].text == "Outside threshold on the CP-1 metric"


def test_python_parses_the_threshold_from_the_quote() -> None:
    assert parse_threshold("5.00 to 1.00", "multiple") == (Decimal("5.00"), None)
    assert parse_threshold("4.50:1.00", "multiple") == (Decimal("4.50"), None)
    assert parse_threshold("not more than 3.5x", "multiple") == (Decimal("3.5"), None)
    assert parse_threshold("3 times", "multiple") == (Decimal("3"), None)
    assert parse_threshold("at least 12.5%", "percent") == (Decimal("12.5"), None)
    assert parse_threshold("10 per cent", "percent") == (Decimal("10"), None)
    value, issue = parse_threshold("5.00 to 1.00, stepping down to 4.50 to 1.00", "multiple")
    assert value is None and issue and "more than one" in issue
    value, issue = parse_threshold("five to one", "multiple")
    assert value is None and issue and "no multiple" in issue
    value, issue = parse_threshold("5.00 to 0", "multiple")
    assert value is None and issue and "zero" in issue
    # Confidence review: a clock time is not a ratio, and Python never asks the model to divide:
    # a ratio to anything but one is not read (unit other, not calculable).
    assert parse_threshold("4.50:1.00, tested at 12:00", "multiple") == (Decimal("4.50"), None)
    assert parse_threshold("4.50 : 1", "multiple") == (Decimal("4.50"), None)
    value, issue = parse_threshold("3.00 to 2.00", "multiple")
    assert value is None and issue and "other than one" in issue


def test_a_threshold_value_that_differs_from_its_quote_is_rejected() -> None:
    base = submission_fixture()
    wrong = leverage_covenant(threshold_value="4.75")
    found = issues_of(changed(base, covenants=(wrong, *base.covenants[1:])))
    assert any("threshold_value 4.75 differs from 5.00" in issue for issue in found), found
    unquoted = leverage_covenant(threshold_text="6.00 to 1.00", threshold_value="6.00")
    found = issues_of(changed(base, covenants=(unquoted, *base.covenants[1:])))
    assert any("threshold_text is not part of the row's quotes" in issue for issue in found)
    silent = leverage_covenant(threshold_value=None)
    found = issues_of(changed(base, covenants=(silent, *base.covenants[1:])))
    assert any("states the threshold_value" in issue for issue in found)
    other = leverage_covenant(threshold_unit="other")
    found = issues_of(changed(base, covenants=(other, *base.covenants[1:])))
    assert any("threshold_value is null" in issue for issue in found)
    unstated = leverage_covenant(threshold_unit="not stated")
    found = issues_of(changed(base, covenants=(unstated, *base.covenants[1:])))
    assert any('"not stated"' in issue for issue in found)
    no_operator = leverage_covenant(comparison="none")
    found = issues_of(changed(base, covenants=(no_operator, *base.covenants[1:])))
    assert any("states its comparison" in issue for issue in found)
    unreadable = leverage_covenant(threshold_text="Consolidated Net Leverage Ratio")
    found = issues_of(changed(base, covenants=(unreadable, *base.covenants[1:])))
    assert any("cannot be read: no multiple threshold is written in it" in i for i in found)
    garbled = leverage_covenant(threshold_value="five")
    found = issues_of(changed(base, covenants=(garbled, *base.covenants[1:])))
    assert any("threshold_value five is not a number" in issue for issue in found)


# --- CP-1 blocked: restricted, inherited limitation, "not calculable" --------------------------


def test_a_blocked_cp1_leaves_headroom_not_calculable() -> None:
    assert issues_of(submission_fixture(blocked=True), blocked=True) == ()
    report = composed(blocked=True)
    found = cells(report)
    for row in ("r01", "r02"):
        assert found[f"T4.9.{row}.headroom"].amount is None
        assert found[f"T4.9.{row}.headroom"].status == "missing"
        assert found[f"T4.9.{row}.test_on_cp_1_metric"].text == NOT_CALCULABLE
        assert found[f"T4.9.{row}.current"].amount is None
        assert "CP-1 is blocked" in str(found[f"T4.9.{row}.headroom"].limitation)
    assert any(text.startswith("CP-1 is blocked") for text in report.limitations)
    assert found["T4F.1.cp-1.status"].text == "blocked"
    # A blocked CP-1 offers no figure: a metric reference is refused, never computed.
    base = submission_fixture(blocked=True)
    named = leverage_covenant(facility_ids=())
    found_issues = issues_of(changed(base, covenants=(named, *base.covenants[1:])), blocked=True)
    assert any("no CP-1 figure is offered" in issue for issue in found_issues), found_issues


def journal(tmp_path: Path, *, blocked: bool = False) -> Execution:
    pack = legal_pack()
    store = Execution.create(tmp_path / "execution", pack)
    ticket = store.begin("CP-0")
    store.finish(ticket.ticket_id, cp0_module(store.pack()).model_dump_json(), lambda _: ())
    for _ in range(2 if blocked else 1):
        ticket = store.begin("CP-1")
        if blocked:
            store.finish(ticket.ticket_id, "not json", lambda _: ())
            continue
        candidate = cp1_module(store.pack()).model_copy(
            update={"status": "candidate", "inputs": current_inputs(store.read(), "CP-1")}
        )
        store.finish(ticket.ticket_id, candidate.model_dump_json(), lambda _: ())
    return store


def test_the_journal_settles_cp4_restricted_with_the_inherited_limitation(tmp_path: Path) -> None:
    store = journal(tmp_path, blocked=True)
    ticket = store.begin(MODULE_ID)
    payload = submission_fixture(blocked=True).model_dump_json()
    finished = submit_cp4_step(store, ticket.ticket_id, STEP_ID, payload)
    assert finished.status == "finished" and finished.issues == ()
    assert finished.result_sha256
    module = store.result(finished.result_sha256)
    assert module.status == "restricted"
    assert any(text.startswith("Upstream CP-1 blocked: ") for text in module.inherited_limitations)
    assert any(text.startswith("CP-1 is blocked") for text in module.limitations)
    bound = next(item for item in module.inputs if item.input_id == "CP-1")
    assert bound.status == "blocked"
    headroom_facts = [f for f in module.facts if f.table_id == "T4.9" and f.field == "headroom"]
    assert headroom_facts and all(f.amount is None for f in headroom_facts)
    # Resubmitting the retained response is refused: the ticket is finished.
    with pytest.raises(ValueError, match="absent, finished"):
        submit_cp4_step(store, ticket.ticket_id, STEP_ID, payload)


def test_the_journal_computes_headroom_from_the_bound_cp1(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    upstream = upstream_of(store, ticket)
    assert upstream.cp1_status == "restricted"  # a synthetic run settles CP-1 restricted
    with pytest.raises(ValueError, match="one step"):
        submit_cp4_step(store, ticket.ticket_id, "other", "{}")
    finished = submit_cp4_step(
        store, ticket.ticket_id, STEP_ID, submission_fixture().model_dump_json()
    )
    assert finished.issues == () and finished.result_sha256
    module = store.result(finished.result_sha256)
    assert module.status == "restricted"  # synthetic case and own limitations
    found = {f.fact_id: f for f in module.facts}
    assert found["T4.9.r01.headroom"].amount == Decimal("0.80")


def test_a_crash_after_the_valid_step_resumes_from_it(tmp_path: Path) -> None:
    from deploy_vii import cp4_legal

    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    payload = submission_fixture().model_dump_json()
    # The step is retained valid, then the process stops before the module settles.
    pending = store.submit_step(
        ticket.ticket_id,
        MODULE_ID,
        CP4_STEPS,
        STEP_ID,
        payload,
        lambda pack, current: cp4_legal._validate_step(store, pack, current),
    )
    assert pending.status == "pending" and pending.steps[0].status == "valid"
    with pytest.raises(ValueError, match="different response"):
        submit_cp4_step(store, ticket.ticket_id, STEP_ID, payload + " ")
    finished = submit_cp4_step(store, ticket.ticket_id, STEP_ID, payload)
    assert finished.status == "finished" and finished.issues == ()


def test_an_invalid_payload_finishes_the_attempt_rejected(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    finished = submit_cp4_step(store, ticket.ticket_id, STEP_ID, '{"documents": []}')
    assert finished.status == "finished" and finished.issues
    bad = submission_fixture().model_copy(
        update={"covenants": (leverage_covenant(facility_ids=("XYZ",)),)}
    )
    repair = store.begin(MODULE_ID)
    finished = submit_cp4_step(store, repair.ticket_id, STEP_ID, bad.model_dump_json())
    assert any("unknown facility_id XYZ" in issue for issue in finished.issues)


# --- stale inputs -----------------------------------------------------------------------------


def test_stale_inputs_are_rejected() -> None:
    pack = legal_pack()
    cp0, cp1 = cp0_module(pack), cp1_module(pack)
    newer = cp1_module(pack, leverage="4.10")
    upstream = cp4_upstream(pack, cp0, newer)
    found = validate_covenant_interpretation(
        pack, submission_fixture(), upstream, inputs_for(pack, cp0, cp1)
    )
    assert any(issue.startswith("Stale input: CP-1") for issue in found), found
    other_pack = pack.model_copy(update={"sources": pack.sources[:2]})
    found = validate_covenant_interpretation(
        pack, submission_fixture(), upstream, inputs_for(other_pack, cp0, newer)
    )
    assert any(issue.startswith("Stale input: prepared-pack") for issue in found), found
    found = validate_covenant_interpretation(pack, submission_fixture(), upstream, ())
    assert "Stale input: CP-0 is not bound" in found


def test_a_changed_pack_stales_cp4_and_its_old_inputs_are_rejected(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    old = upstream_of(store, ticket)
    finished = submit_cp4_step(
        store, ticket.ticket_id, STEP_ID, submission_fixture().model_dump_json()
    )
    assert finished.result_sha256
    store.replace_pack(legal_pack(deck="Synthetic lender presentation, second version."))
    heads = {head.module_id: head.status for head in store.read().heads}
    assert heads[MODULE_ID] == "stale"
    with pytest.raises(ValueError, match="unrun, stale or blocked"):
        store.begin(MODULE_ID)
    found = validate_covenant_interpretation(store.pack(), submission_fixture(), old, ticket.inputs)
    assert any(issue.startswith("Stale input: prepared-pack") for issue in found), found


# --- the Python-only checks -------------------------------------------------------------------


def test_an_unknown_facility_id_is_rejected() -> None:
    base = submission_fixture()
    row = leverage_covenant(facility_ids=("TLB", "TLC", "TLB"))
    found = issues_of(changed(base, covenants=(row, *base.covenants[1:])))
    assert "covenants[0]: unknown facility_id TLC (not in the bound CP-1 T4.18)" in found
    assert "covenants[0]: facility_id TLB is listed more than once" in found


def test_a_covenant_needs_its_governing_document_and_a_quote() -> None:
    base = submission_fixture()
    orphan = leverage_covenant(document_id="credit-agreement")
    found = issues_of(changed(base, covenants=(orphan, *base.covenants[1:])))
    assert any("no documents row for credit-agreement" in issue for issue in found)
    bare = leverage_covenant(citations=())
    found = issues_of(changed(base, covenants=(bare, *base.covenants[1:])))
    assert "covenants[0]: a covenant quotes its governing document" in found
    elsewhere = leverage_covenant(citations=(q(1, "Synthetic issuer FY2025", "filing"),))
    found = issues_of(changed(base, covenants=(elsewhere, *base.covenants[1:])))
    assert "covenants[0]: a covenant quotes its governing document" in found


def test_only_executed_or_filed_sources_may_be_cited() -> None:
    base = submission_fixture()
    deck = q(1, "management expects ample covenant room", "deck")
    flag = base.red_flags[0].model_copy(update={"citations": (deck,)})
    found = issues_of(changed(base, red_flags=(flag,)))
    assert any("deck is not an executed or filed source" in issue for issue in found), found
    document = base.documents[0].model_copy(update={"source_id": "deck", "citations": (deck,)})
    found = issues_of(changed(base, documents=(document,)))
    assert any("documents[0]: deck is not an executed or filed source" in i for i in found)
    twice = changed(base, documents=(base.documents[0], base.documents[0]))
    assert "documents: indenture is registered more than once" in issues_of(twice)
    foreign = base.documents[0].model_copy(update={"citations": (LEVERAGE_QUOTE, deck)})
    found = issues_of(changed(base, documents=(foreign,)))
    assert "documents[0]: a document row quotes its own source only" in found
    missing = q(1, "anything", "absent")
    flag = base.red_flags[0].model_copy(update={"citations": (missing,)})
    assert "Unavailable or changed source: absent" in issues_of(changed(base, red_flags=(flag,)))


def test_a_source_without_a_cp0_authority_is_not_citable() -> None:
    """Fix round 1: a ready pack source with no CP-0 T3 authority row is not executed or filed,
    so a red flag, basket or score quoting it is rejected (it used to pass)."""
    pack = legal_pack()
    cp0, cp1 = cp0_module(pack), cp1_module(pack)
    unclassed = cp0.model_copy(
        update={
            "facts": tuple(
                f for f in cp0.facts if not (f.table_id == "T3" and f.row_id == "filing")
            ),
            "tables": (),
        }
    )
    upstream, inputs = cp4_upstream(pack, unclassed, cp1), inputs_for(pack, unclassed, cp1)
    assert "filing" not in upstream.legal_sources and "filing" not in upstream.authority
    base = submission_fixture()
    filing = q(1, "net leverage is disclosed in the KPI table", "filing")
    for name, rows in (
        ("red_flags", (base.red_flags[0].model_copy(update={"citations": (filing,)}),)),
        ("capacity", (base.capacity[0].model_copy(update={"citations": (filing,)}),)),
    ):
        found = validate_covenant_interpretation(
            pack, changed(base, **{name: rows}), upstream, inputs
        )
        expected = f"{name}[0]: filing is not an executed or filed source (CP-0 authority none"
        assert any(issue.startswith(expected) for issue in found), found
    score = base.protection_score.model_copy(update={"citations": (filing,)})
    found = validate_covenant_interpretation(
        pack, changed(base, protection_score=score), upstream, inputs
    )
    expected = "protection_score: filing is not an executed or filed source (CP-0 authority none"
    assert any(issue.startswith(expected) for issue in found), found


@pytest.mark.parametrize(
    ("comparison", "quote", "threshold"),
    [
        ("<=", "of not less than 2.50 to 1.00", "2.50 to 1.00"),
        ("<", "a minimum ratio of 2.50 to 1.00", "2.50 to 1.00"),
        ("<=", "of at least 2.50 to 1.00", "2.50 to 1.00"),
        (">=", "shall not exceed 5.00 to 1.00", "5.00 to 1.00"),
        (">", "not more than 5.00 to 1.00", "5.00 to 1.00"),
        (">=", "a maximum ratio of 5.00 to 1.00", "5.00 to 1.00"),
        (">=", "shall not be greater than 5.00 to 1.00", "5.00 to 1.00"),
        (">=", "an amount not to exceed 5.00 to 1.00", "5.00 to 1.00"),
    ],
)
def test_a_comparison_against_the_quote_wording_is_rejected(
    comparison: str, quote: str, threshold: str
) -> None:
    """Fix round 1: the cheap directional check on the threshold's own quote."""
    row = leverage_covenant(
        threshold_text=threshold,
        threshold_value=threshold.split()[0],
        comparison=comparison,
        citations=(Quote(source_id="indenture", locator="line:8", quote=quote),),
    )
    base = submission_fixture()
    pack, upstream, inputs = _quote_fixture(quote)
    submission = changed(base, covenants=(row, *base.covenants[1:]))
    found = validate_covenant_interpretation(pack, submission, upstream, inputs)
    assert any(f"comparison {comparison} contradicts the quote" in i for i in found), found


def _quote_fixture(quote: str) -> tuple[PreparedPack, Upstream, tuple[Input, ...]]:
    """`fixture()` with line:8 of the indenture holding `quote` (the directional cases)."""
    pack = legal_pack(extra=quote)
    cp0, cp1 = cp0_module(pack), cp1_module(pack)
    return pack, cp4_upstream(pack, cp0, cp1), inputs_for(pack, cp0, cp1)


def test_a_quote_without_direction_words_leaves_the_comparison_to_the_model() -> None:
    # "shall not permit ... to exceed" names no listed phrase: accepted, model judgement.
    assert issues_of(submission_fixture()) == ()
    both = "a minimum of 2.50 to 1.00 and not to exceed 5.00 to 1.00"
    row = leverage_covenant(
        threshold_text="2.50 to 1.00",
        threshold_value="2.50",
        comparison=">=",
        citations=(Quote(source_id="indenture", locator="line:8", quote=both),),
    )
    base = submission_fixture()
    pack, upstream, inputs = _quote_fixture(both)
    submission = changed(base, covenants=(row, *base.covenants[1:]))
    assert validate_covenant_interpretation(pack, submission, upstream, inputs) == ()


def test_run_text_carries_figures_only_as_offered_references() -> None:
    base = submission_fixture()
    bare = leverage_covenant(clause="Section 4.09 caps leverage at 5.00x")
    found = issues_of(changed(base, covenants=(bare, *base.covenants[1:])))
    assert any("covenants[0].clause" in issue and "5.00x" in issue for issue in found), found
    referenced = leverage_covenant(
        test_formula="Net debt over EBITDA, at {T4.10.net_leverage_reported.FY2025|x} for FY2025"
    )
    assert issues_of(changed(base, covenants=(referenced, *base.covenants[1:]))) == ()
    report = composed(changed(base, covenants=(referenced, *base.covenants[1:])))
    shown = cells(report)["T4.9.r01.test_formula"].text
    assert shown == "Net debt over EBITDA, at 4.20x for FY2025"
    unknown = leverage_covenant(test_formula="Net debt over EBITDA at {T4.10.other.FY2025|x}")
    found = issues_of(changed(base, covenants=(unknown, *base.covenants[1:])))
    assert any("T4.10.other.FY2025" in issue for issue in found), found
    blank = leverage_covenant(period_scope=" ")
    found = issues_of(changed(base, covenants=(blank, *base.covenants[1:])))
    assert "covenants[0].period_scope: empty text" in found


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("We recommend buying the notes", "instrument recommendation"),
        ("The expected recovery is high", "recovery conclusion"),
        ("The issuer is in compliance with the test", "compliance or headroom"),
        ("Headroom is ample at the last test date", "compliance or headroom"),
        ("The issuer was compliant at year end", "compliance or headroom"),
        ("There is a comfortable cushion", "compliance or headroom"),
    ],
)
def test_prohibited_and_python_owned_conclusions_are_rejected(text: str, kind: str) -> None:
    base = submission_fixture()
    flag = base.red_flags[0].model_copy(update={"implication": text})
    found = issues_of(changed(base, red_flags=(flag,)))
    assert any(f"({kind})" in issue for issue in found), found


@pytest.mark.parametrize(
    "text",
    [
        "The issuer must comply with the leverage test each quarter",
        # Confidence review: an obligation to stay compliant is a provision, not a status.
        "The issuer must remain in compliance with Section 4.09",
        # Confidence review: a contractual repayment term is a mechanic, not a recovery view.
        "The notes must be repaid in full upon a change of control",
    ],
)
def test_a_provision_naming_the_test_is_not_a_conclusion(text: str) -> None:
    base = submission_fixture()
    flag = base.red_flags[0].model_copy(update={"mechanic": text})
    assert issues_of(changed(base, red_flags=(flag,))) == ()


def test_a_recovery_outcome_is_still_rejected() -> None:
    base = submission_fixture()
    flag = base.red_flags[0].model_copy(update={"implication": "The notes would recover par"})
    assert any("(recovery conclusion)" in i for i in issues_of(changed(base, red_flags=(flag,))))


def test_a_metric_must_be_offered_and_match_the_threshold_unit() -> None:
    base = submission_fixture()
    percent = leverage_covenant(metric_ref="T4.10.ebitda_margin.FY2025")
    found = issues_of(changed(base, covenants=(percent, *base.covenants[1:])))
    assert any("is a PERCENT figure; the threshold is a multiple" in i for i in found), found
    unknown = leverage_covenant(metric_ref="T4.10.absent.FY2025")
    found = issues_of(changed(base, covenants=(unknown, *base.covenants[1:])))
    assert any("metric_ref T4.10.absent.FY2025 is not a CP-1 figure offered" in i for i in found)
    unjudged = leverage_covenant(metric_ref=None, metric_basis="Same definition")
    found = issues_of(changed(base, covenants=(unjudged, *base.covenants[1:])))
    assert any("metric_basis is Not determinable when no metric_ref" in i for i in found)


def test_the_definition_basis_gates_the_headroom() -> None:
    base = submission_fixture()
    for basis, words in (
        ("Different definition", "differs from the CP-1 metric"),
        ("Not determinable", "is not determinable"),
    ):
        row = leverage_covenant(metric_basis=basis)
        submission = changed(base, covenants=(row, *base.covenants[1:]))
        assert issues_of(submission) == ()
        report = composed(submission)
        found = cells(report)
        assert found["T4.9.r01.headroom"].amount is None
        assert words in str(found["T4.9.r01.headroom"].limitation)
        assert found["T4.9.r01.current"].amount == Decimal("4.20")  # shown, not compared
        assert any("Maximum Consolidated Net Leverage Ratio" in t for t in report.limitations)


def test_row_rules() -> None:
    base = submission_fixture()
    score = base.protection_score.model_copy(update={"citations": ()})
    assert "protection_score: a rating above Insufficient Information cites its basis" in (
        issues_of(changed(base, protection_score=score))
    )
    score = base.protection_score.model_copy(
        update={"rating": "Insufficient Information", "citations": ()}
    )
    assert (
        "protection_score: an Insufficient Information rating states its limitation"
        in issues_of(changed(base, protection_score=score))
    )
    basket = base.capacity[0].model_copy(update={"citations": ()})
    assert "capacity[0]: a capacity row quotes its basket" in issues_of(
        changed(base, capacity=(basket,))
    )
    flag = base.red_flags[0].model_copy(update={"citations": ()})
    assert "red_flags[0]: a red flag quotes its mechanic" in issues_of(
        changed(base, red_flags=(flag,))
    )
    document = base.documents[0].model_copy(update={"citations": ()})
    assert "documents[0]: a document row quotes its own source" in issues_of(
        changed(base, documents=(document,))
    )


def test_unusable_inputs_are_refused_not_guessed(tmp_path: Path) -> None:
    pack = legal_pack()
    cp0, cp1 = cp0_module(pack), cp1_module(pack)
    with pytest.raises(ValueError, match="reads the CP-0 and CP-1 modules"):
        cp4_upstream(pack, cp1, cp0)
    with pytest.raises(ValueError, match="CP-1 is candidate"):
        cp4_upstream(pack, cp0, cp1.model_copy(update={"status": "candidate"}))
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    with pytest.raises(ValueError, match="not a CP-4 attempt"):
        upstream_of(store, ticket.model_copy(update={"module_id": "CP-2"}))
    assert parse_threshold("the greater of $50 million", "other") == (
        None,
        "a other threshold is not parsed",
    )
    with pytest.raises(ValueError, match="no headroom"):
        headroom(Decimal("5"), "none", Decimal("4"))


def test_a_malformed_citation_or_value_is_rejected() -> None:
    base = submission_fixture()
    flag = base.red_flags[0].model_copy(update={"citations": (q(4, ""),)})
    assert "red_flags[0]: malformed citation (empty locator or quote)" in issues_of(
        changed(base, red_flags=(flag,))
    )
    for value in ("Infinity", "NaN"):
        row = leverage_covenant(threshold_value=value)
        found = issues_of(changed(base, covenants=(row, *base.covenants[1:])))
        assert any(f"threshold_value {value} differs from 5.00" in i for i in found), found


def test_an_invalid_submission_never_composes() -> None:
    pack, upstream, inputs = fixture()
    base = submission_fixture()
    broken = changed(base, covenants=(leverage_covenant(facility_ids=("XYZ",)),))
    with pytest.raises(ValueError, match="unknown facility_id XYZ"):
        covenant_interpretation(pack, broken, upstream, inputs)


# --- empty registers, limitations and the module ------------------------------------------------


def test_an_empty_legal_pack_composes_explicit_gaps() -> None:
    base = submission_fixture()
    empty = changed(base, documents=(), covenants=(), capacity=(), red_flags=(), gaps=())
    assert issues_of(empty) == ()
    report = composed(empty)
    found = cells(report)
    assert found["T4.2.none.document_family"].status == "missing"
    assert found["T4.3.none.kind"].status == "missing"
    assert found["T4.11.none.severity"].status == "not_applicable"
    assert "No document register rows in the CP-4 submission" in report.limitations
    assert "No covenant register rows in the CP-4 submission" in report.limitations


def test_capacity_amounts_are_never_shown_as_zero() -> None:
    found = cells(composed())
    cell = found["T4.10.r01.capacity_amount"]
    assert cell.amount is None and cell.status == "missing"
    assert "not calculated" in str(cell.limitation)


def test_the_module_is_a_valid_candidate_with_run_text_claims() -> None:
    pack, _, inputs = fixture()
    report = composed()
    module = cp4_module(report, inputs, 0)
    assert module.module_id == MODULE_ID and module.status == "candidate"
    assert module.inputs[-1].input_id == "covenant-interpretation-submission"
    assert {claim.claim_id for claim in module.claims} == {"red_flags.r01", "protection_score"}
    assert Module.model_validate_json(module.model_dump_json()) == module
    assert report.pack_sha256 == pack.content_hash()


# --- the CONTEXT block --------------------------------------------------------------------------


def test_the_context_block_prefills_what_the_validator_checks() -> None:
    pack, upstream, _ = fixture()
    block = context_block(pack, upstream)
    assert block["cp1_status"] == "accepted"
    assert [s["source_id"] for s in block["legal_sources"]] == ["filing", "indenture"]  # type: ignore[index]
    assert block["other_sources"] == [{"source_id": "deck", "authority": "management"}]
    assert block["facilities"] == [
        {"facility_id": "TLB", "facility_name": "Term Loan B"},
        {"facility_id": "RCF", "facility_name": "Revolving Credit Facility"},
    ]
    refs = [item["ref"] for item in block["cp1_facts"]]  # type: ignore[attr-defined]
    assert refs == [
        "T4.10.net_leverage_reported.FY2025",
        "T4.10.interest_coverage_reported.FY2025",
        "T4.10.ebitda_margin.FY2025",
    ]
    assert block["cp1_facts"][0]["shown"] == "4.20x"  # type: ignore[index]
    blocked_pack, blocked, _ = fixture(blocked=True)
    block = context_block(blocked_pack, blocked)
    assert block["cp1_status"] == "blocked"
    assert block["cp1_facts"] == [] and block["facilities"] == []
    assert block["inherited_gaps"] == [
        "Upstream CP-1 blocked: Malformed candidate: (root): Invalid JSON"
    ]
    assert "not calculable" in str(block["headroom_note"])


# --- bindings: the six Covenant & Refinancing blocks, with field parity -------------------------


def test_the_six_blocks_fill_and_every_fact_is_bound_once() -> None:
    report = composed()
    run = report.run.model_copy(update={"pathway": "covenant_refinancing"})
    view = View(
        run=run,
        mode="candidate",
        modules=(
            ModuleView(
                module_id=MODULE_ID,
                title="Legal covenant interpreter",
                aliases=(),
                status="candidate",
                artifact_sha256=report.submission_sha256,
                facts=report.facts,
                tables=report.tables,
            ),
        ),
    )
    assert validate_bindings(view, (CP4,)) == ()
    blocks = {entry.block_id for entry in CP4.entries}
    assert set(BLOCKS) <= blocks and len(BLOCKS) == 6
    pathway_blocks = set(next(p for p in pathways() if p.id == "covenant_refinancing").blocks)
    assert set(BLOCKS) <= pathway_blocks
    assert blocks - set(BLOCKS) <= {"evidence", "limitations"}
    # Field parity: each block shows exactly the composed facts of its tables, value for value.
    by_block: dict[str, list[Fact]] = {}
    for fact in report.facts:
        entry = next(e for e in CP4.entries if e.matches(MODULE_ID, fact))
        by_block.setdefault(entry.block_id, []).append(fact)
    tests = {f.fact_id: f for f in by_block["covenant-tests-headroom"]}
    assert tests["T4.9.r01.headroom"].amount == Decimal("0.80")
    assert tests["T4.9.r01.threshold"].text == "5.00 to 1.00"
    assert {f.table_id for f in by_block["documents-structure"]} == {"T4.2", "T4C.12"}
    assert {f.table_id for f in by_block["ebitda-definition"]} == {"T4C.6"}
    assert {f.table_id for f in by_block["capacity"]} == {"T4.10"}
    assert {f.table_id for f in by_block["red-flags"]} == {"T4.11"}
    assert {f.table_id for f in by_block["lender-protection-score"]} == {"T4.13"}
    rating = next(f for f in by_block["lender-protection-score"] if f.field == "rating")
    assert rating.text == "Adequate"
    slots = [entry.cell_slot for entry in CP4.entries]
    assert len(slots) == len(set(slots)) and all(slot.startswith("cp4-") for slot in slots)


# --- the method text ---------------------------------------------------------------------------


def test_the_method_text_states_no_figure_and_names_every_table_id() -> None:
    text = files("deploy_vii").joinpath("methods", "cp4.md").read_text(encoding="utf-8")
    method, tables = text.split("## Tables")
    # The model-facing method states labels only (the CONTEXT key `cp1_facts` aside).
    assert bare_figures(method.replace("`cp1_facts`", "")) == ()
    assert len(method.splitlines()) < 90
    for anchor in ("Reader question", "not zero", "Not calculable", "legal_sources"):
        assert anchor in method
    for table_id in REQUIRED_TABLES:
        assert re.search(rf"(?<![\w.]){re.escape(table_id)}(?![\w.]|\.\d)", tables), table_id
    assert "decision 0005" in tables


# --- the sent schema ----------------------------------------------------------------------------


def test_the_sent_schema_is_strict() -> None:
    sent = strict_schema(CovenantInterpretationSubmission)
    assert schema_relaxations(CovenantInterpretationSubmission) == []
    text = json.dumps(sent)
    assert '"default"' not in text and '"const"' not in text
    for value in ("maintenance", "<=", "Same definition", "Insufficient Information", "percent"):
        assert f'"{value}"' in text
    assert "CP-4" in {item.module_id for item in modules()}


# --- Property 1: figure identity ---------------------------------------------------------------

AMOUNTS = st.decimals(min_value=Decimal("-20"), max_value=Decimal("20"), places=2)


@settings(max_examples=60, deadline=None)
@given(AMOUNTS, AMOUNTS, st.text(alphabet="abcdefxyz_.", min_size=1, max_size=12))
def test_composed_figures_equal_the_upstream_facts(
    leverage: Decimal, coverage: Decimal, stray: str
) -> None:
    pack = legal_pack()
    cp0, cp1 = cp0_module(pack), cp1_module(pack, str(leverage), str(coverage))
    upstream, inputs = cp4_upstream(pack, cp0, cp1), inputs_for(pack, cp0, cp1)
    report = covenant_interpretation(pack, submission_fixture(), upstream, inputs)
    found = cells(report)
    upstream_facts = {fact.fact_id: fact for fact in cp1.facts}
    for row, ref in (
        ("r01", "T4.10.net_leverage_reported.FY2025"),
        ("r02", "T4.10.interest_coverage_reported.FY2025"),
    ):
        source, copy = upstream_facts[ref], found[f"T4.9.{row}.current"]
        keys = ("amount", "unit", "currency", "scale", "period", "basis", "citations")
        assert {k: getattr(copy, k) for k in keys} == {k: getattr(source, k) for k in keys}
    referenced = {f.fact_id: f for f in report.facts if f.table_id == "T4F.2"}
    for fact_id, fact in referenced.items():
        assert fact.amount == upstream_facts[fact_id].amount
    ref = f"T4.10.{stray}"
    row = leverage_covenant(test_formula=f"Net debt over EBITDA {{{ref}|x}}")
    base = submission_fixture()
    found_issues = validate_covenant_interpretation(
        pack, changed(base, covenants=(row, *base.covenants[1:])), upstream, inputs
    )
    assert any(ref in issue for issue in found_issues)


# --- Property 2: headroom is numeric only with every operand; differential vs a naive formula ---

UNITS = st.sampled_from(("multiple", "percent", "other", "not stated"))
BASES = st.sampled_from(("Same definition", "Different definition", "Not determinable"))


@settings(max_examples=120, deadline=None)
@given(st.booleans(), UNITS, st.booleans(), BASES, AMOUNTS)
def test_headroom_is_never_numeric_without_every_operand(
    blocked: bool, unit: str, with_metric: bool, basis: str, leverage: Decimal
) -> None:
    pack = legal_pack()
    cp0 = cp0_module(pack)
    cp1 = blocked_cp1(pack) if blocked else cp1_module(pack, str(leverage))
    upstream, inputs = cp4_upstream(pack, cp0, cp1), inputs_for(pack, cp0, cp1)
    metric = "T4.10.net_leverage_reported.FY2025" if with_metric and not blocked else None
    text = {"multiple": "5.00 to 1.00", "percent": "10%", "other": "the greater of $50 million"}
    quotes = {
        "percent": q(4, "10% of Consolidated EBITDA"),
        "other": q(4, "the greater of $50 million"),
    }
    row = leverage_covenant(
        threshold_text=text.get(unit, "not stated"),
        threshold_unit=unit,
        threshold_value={"multiple": "5.00", "percent": "10"}.get(unit),
        comparison="none" if unit == "not stated" else "<=",
        metric_ref=None if unit == "percent" else metric,
        metric_basis=basis if metric and unit != "percent" else "Not determinable",
        facility_ids=() if blocked else ("TLB",),
        citations=(LEVERAGE_QUOTE, *([quotes[unit]] if unit in quotes else [])),
    )
    base = submission_fixture(blocked=blocked)
    submission = changed(base, covenants=(row,))
    assert validate_covenant_interpretation(pack, submission, upstream, inputs) == ()
    found = cells(covenant_interpretation(pack, submission, upstream, inputs))
    calculable = (
        not blocked and unit == "multiple" and metric is not None and basis == "Same definition"
    )
    for field in ("headroom", "headroom_share"):
        cell = found[f"T4.9.r01.{field}"]
        if calculable:
            assert cell.amount is not None  # a 5.00 threshold always has a share
        else:
            assert cell.amount is None and cell.status == "missing" and cell.limitation
    verdict = found["T4.9.r01.test_on_cp_1_metric"].text
    assert (verdict == NOT_CALCULABLE) is (not calculable)


THRESHOLDS = st.decimals(min_value=Decimal("-10"), max_value=Decimal("10"), places=2)
COMPARISONS = st.sampled_from(("<=", "<", ">=", ">"))


def naive(threshold: Decimal, comparison: str, metric: Decimal) -> tuple[Any, ...]:
    """The reference, built apart from `headroom` (fix round 1): whether the test holds comes
    from the comparison itself; the room is the distance between metric and threshold, positive
    when the test holds and negative when it fails (zero at the threshold, strict or not); the
    share is the metric's exact rational ratio to the threshold less one, turned to the
    permitted side: a maximum test gains room as the ratio falls, and a negative threshold flips
    which way the ratio moves."""
    holds = {
        "<=": metric <= threshold,
        "<": metric < threshold,
        ">=": metric >= threshold,
        ">": metric > threshold,
    }[comparison]
    distance = abs(metric - threshold)
    room = distance if holds else -distance
    if threshold == 0:
        return room, None, holds
    ratio = Fraction(metric) / Fraction(threshold) - 1
    maximum = comparison in ("<=", "<")
    side = (-1 if maximum else 1) * (1 if threshold > 0 else -1)
    return room, ratio * side, holds


@settings(max_examples=300, deadline=None)
@given(THRESHOLDS, COMPARISONS, THRESHOLDS)
@example(Decimal("0"), "<=", Decimal("1.5"))
@example(Decimal("2.50"), "<", Decimal("2.50"))
@example(Decimal("2.50"), ">", Decimal("2.50"))
@example(Decimal("-1.00"), ">=", Decimal("-2.00"))
@example(Decimal("-1.00"), "<=", Decimal("-0.50"))
@example(Decimal("3.00"), "<=", Decimal("1.00"))  # a share with a repeating decimal
def test_python_headroom_matches_a_naive_reference(
    threshold: Decimal, comparison: str, metric: Decimal
) -> None:
    result = headroom(threshold, comparison, metric)  # type: ignore[arg-type]
    room, share, holds = naive(threshold, comparison, metric)
    assert result.amount == room
    assert result.within is holds
    if share is None:
        assert threshold == 0 and result.share is None and result.share_reason
        return
    assert result.share is not None
    # Decimal division rounds at 28 significant digits; the reference is exact.
    assert abs(Fraction(result.share) - share) <= Fraction(1, 10**25) * max(1, abs(share))
    assert (result.share > 0) is (share > 0) and (result.share == 0) is (share == 0)


# --- Property 3: the verdict does not depend on row order --------------------------------------


def _indexless(issues: tuple[str, ...]) -> list[str]:
    return sorted(re.sub(r"\[\d+\]", "[]", issue) for issue in issues)


@settings(max_examples=60, deadline=None)
@given(st.randoms(use_true_random=False), st.booleans())
def test_the_verdict_is_independent_of_row_order(rng: random.Random, broken: bool) -> None:
    base = submission_fixture()
    covenants = list(base.covenants)
    if broken:
        covenants[1] = coverage_covenant(threshold_value="9.99")
    original = changed(base, covenants=tuple(covenants))
    rng.shuffle(covenants)
    shuffled = changed(original, covenants=tuple(covenants))
    assert _indexless(issues_of(original)) == _indexless(issues_of(shuffled))
    if broken:
        return
    first, second = cells(composed(original)), cells(composed(shuffled))

    def results(found: dict[str, Fact]) -> dict[str, tuple[Any, ...]]:
        rows = {f.row_id for f in found.values() if f.table_id == "T4.9"}
        return {
            str(found[f"T4.9.{r}.threshold"].text): (
                found[f"T4.9.{r}.headroom"].amount,
                found[f"T4.9.{r}.test_on_cp_1_metric"].text,
            )
            for r in rows
        }

    assert results(first) == results(second)


# --- Property 4: a quote outside its span is always rejected ------------------------------------


@settings(max_examples=100, deadline=None)
@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=3, max_size=40))
def test_a_quote_outside_its_span_is_rejected(text: str) -> None:
    pack = legal_pack()
    span = next(s for s in pack.sources if s.source_id == "indenture").spans[3].text
    if not text.strip() or " ".join(text.split()) in " ".join(span.split()):
        return  # a substring of the span is a valid quote
    base = submission_fixture()
    flag = base.red_flags[0].model_copy(update={"citations": (q(4, text),)})
    found = issues_of(changed(base, red_flags=(flag,)))
    assert any("Quote/locator mismatch" in issue for issue in found), found
