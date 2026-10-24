"""CP-5 evidence trace validator (task 8.4): Python checks, the model's narrow verdict, status.

SYNTHETIC: every head here is test data over the CP-0 readiness fixture pack; nothing qualifies
an issuer. Heads are generic `Module`s: the CP-1 figure fixture (`cp1_fact`), the composed CP-1A
registers (`business_context` over its submission fixture) and a CP-MODEL head in its
publication shape. CP-2, CP-3 and CP-4 heads do not exist yet.
"""

import json
import random
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.bindings import validate_bindings
from deploy_vii.business_context import (
    CP1_REFERENCES,
    BusinessContextReport,
    business_context,
    cp1a_module,
)
from deploy_vii.contracts import (
    Citation,
    Claim,
    Fact,
    Input,
    Module,
    ReportTable,
    TableColumn,
    TableRow,
)
from deploy_vii.cp5_integrity import (
    CP5_STEPS,
    MODULE_ID,
    NOT_EVALUATED,
    STEP_ID,
    TABLE_IDS,
    ClaimRef,
    ClaimReview,
    Contradiction,
    IntegrityGap,
    IntegrityReport,
    IntegritySubmission,
    ReviewScope,
    context_block,
    cp5_module,
    figure_identity,
    integrity_review,
    python_checks,
    review_scope,
    submit_cp5_step,
    upstream_refs,
    validate_integrity,
)
from deploy_vii.cp_model_workflow import CLAIM as MODEL_CLAIM
from deploy_vii.cp_model_workflow import publish_cp_model
from deploy_vii.delivery import cp0_view
from deploy_vii.execution import Attempt, Execution, StepValidation, current_inputs
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import citation_issues
from deploy_vii.registry import STEP_CHAINS, StepChain, checked_chains, module_route
from deploy_vii.render import render
from deploy_vii.report_view import build, pathways
from tests.product import test_cp_model_workflow as cp_model_tests
from tests.product.oracle import expected_by_fact, rendered_table_display
from tests.product.test_business_context import cp1_fact, pack_fixture, submission_fixture
from tests.product.test_execution import cp_model_store, settle_module, settled, step_text

SCOPE = ("CP-0", "CP-1", "CP-MODEL", "CP-1A", "CP-5")
FIGURE = "T4.10.liquidity.FY2025"  # the CP-1 fixture figure CP-1A references
RATIONALE = "Synthetic review: the cited span and the named facts state the claim"


# --- heads ----------------------------------------------------------------------------------


def good_citation(pack: PreparedPack, quote: str = "cash") -> Citation:
    source = pack.sources[0]
    assert source.sha256
    return Citation(source_id="filing", source_sha256=source.sha256, locator="line:1", quote=quote)


def module(pack: PreparedPack, module_id: str, **fields: object) -> Module:
    run = pack.run
    record: dict[str, object] = {
        "run_id": run.run_id,
        "issuer_id": run.issuer_id,
        "as_of": run.as_of,
        "module_id": module_id,
        "status": "accepted",
        **fields,
    }
    return Module.model_validate(record)


def cp1_head(pack: PreparedPack) -> Module:
    # The shared fixture states MILLIONS at scale 1; a promoted CP-1 writes the scale its unit
    # implies (MILLIONS at 1e6), which CP-5 checks (fix round 1).
    fact = Fact.model_validate({**dict(cp1_fact(pack)), "scale": Decimal(1000000)})
    claim = Claim(
        claim_id="liquidity",
        text=f"Liquidity was {{{FIGURE}|MILLIONS}} at FY2025.",
        citations=(good_citation(pack),),
    )
    return module(pack, "CP-1", facts=(fact,), claims=(claim,))


def cp1a_report(pack: PreparedPack, cp1: Module) -> BusinessContextReport:
    """The composed CP-1A registers; its first credit translation cites the CP-1 figure."""
    base = submission_fixture(pack)
    text = f"Liquidity was {{{FIGURE}|US$ m}} at FY2025."
    translations = (base.credit_translations[0].model_copy(update={"evidence": text}),)
    submission = base.model_copy(update={"credit_translations": translations})
    return business_context(pack, submission, cp1.facts)


def cp1a_head(pack: PreparedPack, cp1: Module | None = None) -> Module:
    candidate = cp1a_module(cp1a_report(pack, cp1 or cp1_head(pack)), (), 0)
    status = "restricted" if candidate.limitations else "accepted"
    return Module.model_validate_json(
        candidate.model_copy(update={"status": status}).model_dump_json()
    )


def cp_model_head(pack: PreparedPack) -> Module:
    """A CP-MODEL head in its publication shape: text registers and one uncited Python claim."""
    fact = Fact(
        fact_id="model-calculation.schema-version.value",
        label="Schema version",
        table_id="model-calculation",
        row_id="schema-version",
        field="value",
        text="model-report/1",
    )
    table = ReportTable(
        table_id="model-calculation",
        title="Calculation JSON",
        columns=(TableColumn(field="value", label="value"),),
        rows=(TableRow(row_id="schema-version", label="Schema version", fact_ids=(fact.fact_id,)),),
        row_header="Item",
    )
    claim = Claim(claim_id="model-publication", text=MODEL_CLAIM, citations=())
    return module(pack, "CP-MODEL", facts=(fact,), tables=(table,), claims=(claim,))


def bound(head: Module) -> Input:
    return Input(input_id=head.module_id, sha256=head.content_hash(), status=head.status)


def scope_of(
    pack: PreparedPack, heads: tuple[Module, ...], blocked: frozenset[str] = frozenset()
) -> ReviewScope:
    items = tuple((bound(head), head) for head in heads)
    return ReviewScope(
        pack=pack,
        inputs=tuple(item for item, _ in items),
        heads=items,
        blocked=blocked | {h.module_id for h in heads if h.status == "blocked"},
    )


def clean_scope(pack: PreparedPack | None = None) -> ReviewScope:
    pack = pack or pack_fixture()
    cp1 = cp1_head(pack)
    return scope_of(pack, (cp1, cp1a_head(pack, cp1), cp_model_head(pack)))


def review_all(
    scope: ReviewScope,
    support: dict[tuple[str, str], str] | None = None,
    *,
    skip: frozenset[tuple[str, str]] = frozenset(),
) -> IntegritySubmission:
    """One review per evaluated claim: `supported` naming a ref Python does not flag (the
    claim's own citation refs first, else the module's facts), `partly_supported` where Python
    flags the claim or every ref, `unsupported` where nothing can be named; `support` overrides."""
    checks = python_checks(scope)
    reviews: list[ClaimReview] = []
    for item, head in scope.heads:
        if item.status == "blocked":
            continue
        refs = upstream_refs(head)
        marked = checks.ref_marks.get(head.module_id, frozenset())
        for claim in head.claims:
            key = (head.module_id, claim.claim_id)
            if key in skip:
                continue
            own = [r for r in refs if r.startswith(f"{claim.claim_id}#")]
            named = own or list(refs)
            clean = [r for r in named if r not in marked]
            chosen = (support or {}).get(key) or (
                "partly_supported" if key in checks.claim_marks or not clean else "supported"
            )
            pick = (clean or named)[:1] if chosen == "supported" else named[:1]
            if not pick:
                chosen = "unsupported"
            reviews.append(
                ClaimReview(
                    claim_ref=claim.claim_id,
                    producer_module=head.module_id,
                    support=chosen,  # type: ignore[arg-type]
                    rationale=RATIONALE,
                    upstream_refs=tuple(pick) if chosen != "unsupported" else (),
                )
            )
    return IntegritySubmission(claim_reviews=tuple(reviews), contradictions=(), gaps=())


def kinds(report: IntegrityReport) -> set[str]:
    return {finding.kind for finding in report.findings}


# --- focused cases --------------------------------------------------------------------------


def test_clean_heads_compose_accepted_over_the_evaluated_set() -> None:
    scope = clean_scope()
    assert python_checks(scope).findings == ()
    submission = review_all(scope)
    assert validate_integrity(scope, submission) == ()
    report = integrity_review(scope, submission)
    assert report.status == "accepted" and report.findings == () and report.limitations == ()
    assert [t.table_id for t in report.tables] == list(TABLE_IDS)
    assert len(TABLE_IDS) == 17
    assert [item.input_id for item in report.evaluated] == ["CP-1", "CP-1A", "CP-MODEL"]
    verdict = {f.row_id: f for f in report.facts if f.table_id == "T5B.8"}
    assert verdict["status"].text == "Accepted over the evaluated set"
    assert verdict["evaluated"].text == "CP-1, CP-1A, CP-MODEL"
    assert "evaluated set only" in (verdict["scope"].text or "")
    module_ = cp5_module(report, scope.inputs, 0)
    assert module_.module_id == MODULE_ID and module_.status == "candidate"
    assert module_.inputs[-1].input_id == "integrity-submission"
    assert module_.inputs[-1].sha256 == submission.content_hash()


def test_cp5_never_writes_a_value_for_another_modules_figure() -> None:
    scope = clean_scope()
    report = integrity_review(scope, review_all(scope))
    # Every CP-5 cell is Python text: no amount, no unit, no copied upstream fact identity.
    assert all(fact.amount is None and fact.unit is None for fact in report.facts)
    upstream = {f.fact_id for _, head in scope.heads for f in head.facts}
    assert not upstream & {fact.fact_id for fact in report.facts}
    assert not any(fact.citations for fact in report.facts)


def planted_scope() -> ReviewScope:
    """CP-1A carries the CP-1 figure altered: same fact id, another amount."""
    pack = pack_fixture()
    cp1 = cp1_head(pack)
    honest = cp1a_head(pack, cp1)
    facts = tuple(
        f.model_copy(update={"amount": Decimal("1200")}) if f.fact_id == FIGURE else f
        for f in honest.facts
    )
    altered = Module.model_validate_json(
        honest.model_copy(update={"facts": facts}).model_dump_json()
    )
    return scope_of(pack, (cp1, altered, cp_model_head(pack)))


def test_an_altered_fact_and_an_unsupported_claim_restrict_with_both_findings() -> None:
    scope = planted_scope()
    identity = [f for f in python_checks(scope).findings if f.kind == "figure_identity"]
    assert [(f.modules, f.subject) for f in identity] == [(("CP-1", "CP-1A"), f"fact_id {FIGURE}")]
    assert "value" in identity[0].detail and "1200" not in identity[0].detail
    submission = review_all(scope, {("CP-MODEL", "model-publication"): "unsupported"})
    assert validate_integrity(scope, submission) == ()
    report = integrity_review(scope, submission)
    assert report.status == "restricted"
    assert {"figure_identity", "unsupported_claim"} <= kinds(report)
    assert any("CP-MODEL" in text and "unsupported" in text for text in report.limitations)
    assert any(FIGURE in text for text in report.limitations)
    # The claim resting on the altered figure cannot be marked supported.
    key = ("CP-1A", "credit_translation.r01")
    assert key in python_checks(scope).claim_marks
    bad = review_all(scope, {key: "supported"})
    assert any("cannot be supported" in issue for issue in validate_integrity(scope, bad))


def test_an_unresolved_claim_ref_is_rejected() -> None:
    scope = clean_scope()
    base = review_all(scope)
    stray = base.claim_reviews[0].model_copy(update={"claim_ref": "no-such-claim"})
    issues = validate_integrity(
        scope, base.model_copy(update={"claim_reviews": (*base.claim_reviews, stray)})
    )
    assert any("unresolved claim_ref no-such-claim in CP-1" in issue for issue in issues)
    wrong = base.claim_reviews[0].model_copy(update={"producer_module": "CP-4"})
    issues = validate_integrity(scope, base.model_copy(update={"claim_reviews": (wrong,)}))
    assert any("CP-4 is not an evaluated module" in issue for issue in issues)
    with pytest.raises(ValueError, match="unresolved claim_ref"):
        integrity_review(
            scope, base.model_copy(update={"claim_reviews": (*base.claim_reviews, stray)})
        )


def test_an_unresolved_upstream_ref_and_an_unnamed_support_are_rejected() -> None:
    scope = clean_scope()
    base = review_all(scope)
    first = base.claim_reviews[0]
    cases = {
        "unresolved upstream_ref T5.1": first.model_copy(update={"upstream_refs": ("T5.1",)}),
        "names no upstream_ref": first.model_copy(update={"upstream_refs": ()}),
    }
    for expected, review in cases.items():
        submission = base.model_copy(update={"claim_reviews": (review, *base.claim_reviews[1:])})
        assert any(expected in issue for issue in validate_integrity(scope, submission))


def test_supported_over_a_python_failed_citation_is_rejected() -> None:
    pack = pack_fixture()
    head = cp1_head(pack)
    broken = head.claims[0].model_copy(
        update={"citations": (good_citation(pack, "words the filing never says"),)}
    )
    flawed = module(pack, "CP-1", facts=head.facts, claims=(broken,))
    scope = scope_of(pack, (flawed,))
    checks = python_checks(scope)
    assert [f.kind for f in checks.findings] == ["claim_citation"]
    supported = review_all(scope, {("CP-1", "liquidity"): "supported"})
    issues = validate_integrity(scope, supported)
    assert any("cannot be supported over Python findings" in issue for issue in issues)
    # Partly supported is consistent with the failed citation; the finding restricts.
    report = integrity_review(scope, review_all(scope))
    assert report.status == "restricted"
    assert {"claim_citation", "partly_supported_claim"} <= kinds(report)
    # A verdict resting on the failed citation itself is not supported either.
    ref = ClaimReview(
        claim_ref="liquidity",
        producer_module="CP-1",
        support="supported",
        rationale=RATIONALE,
        upstream_refs=("liquidity#c1",),
    )
    assert any(
        "cannot be supported" in issue
        for issue in validate_integrity(
            scope, supported.model_copy(update={"claim_reviews": (ref,)})
        )
    )


def test_an_incomplete_review_lists_the_unreviewed_material_claims() -> None:
    scope = clean_scope()
    submission = review_all(scope, skip=frozenset({("CP-MODEL", "model-publication")}))
    issues = validate_integrity(scope, submission)
    assert "Incomplete review: unreviewed material claims: CP-MODEL model-publication" in issues
    twice = submission.model_copy(
        update={"claim_reviews": (*submission.claim_reviews, submission.claim_reviews[0])}
    )
    assert any("reviewed more than once" in issue for issue in validate_integrity(scope, twice))


def test_contradictions_name_claims_of_two_modules_and_restrict() -> None:
    scope = clean_scope()
    base = review_all(scope)
    pair = (
        ClaimRef(producer_module="CP-1", claim_ref="liquidity"),
        ClaimRef(producer_module="CP-1A", claim_ref="credit_translation.r01"),
    )
    contradiction = Contradiction(
        claim_refs=pair, nature="Direction of liquidity", rationale=RATIONALE, severity="Material"
    )
    report = integrity_review(scope, base.model_copy(update={"contradictions": (contradiction,)}))
    assert report.status == "restricted" and kinds(report) == {"contradiction"}
    rows = [f for f in report.facts if f.table_id == "T5B.3" and f.field == "claims"]
    assert rows[0].text == "CP-1 liquidity; CP-1A credit_translation.r01"
    same = Contradiction(
        claim_refs=(pair[0], pair[0].model_copy(update={"claim_ref": "liquidity"})),
        nature="Self",
        rationale=RATIONALE,
        severity="Minor",
    )
    issues = validate_integrity(scope, base.model_copy(update={"contradictions": (same,)}))
    assert any("claims of at least two modules" in issue for issue in issues)
    unknown = Contradiction(
        claim_refs=(pair[0], ClaimRef(producer_module="CP-1A", claim_ref="ghost")),
        nature="Ghost",
        rationale=RATIONALE,
        severity="Minor",
    )
    issues = validate_integrity(scope, base.model_copy(update={"contradictions": (unknown,)}))
    assert any("unresolved claim_ref ghost in CP-1A" in issue for issue in issues)


def test_model_text_is_labels_only_and_gaps_restrict() -> None:
    scope = clean_scope()
    base = review_all(scope)
    figure = base.claim_reviews[0].model_copy(update={"rationale": "Liquidity of 1100 holds"})
    issues = validate_integrity(
        scope, base.model_copy(update={"claim_reviews": (figure, *base.claim_reviews[1:])})
    )
    assert any("Bare figure: 1100" in issue for issue in issues)
    ref = base.claim_reviews[0].model_copy(update={"rationale": f"See {{{FIGURE}|MILLIONS}}"})
    issues = validate_integrity(
        scope, base.model_copy(update={"claim_reviews": (ref, *base.claim_reviews[1:])})
    )
    assert any("Unresolved reference" in issue for issue in issues)
    gap = IntegrityGap(
        gap="No covenant compliance certificate",
        why_it_matters="Headroom cannot be traced",
        affected_modules=("CP-1",),
        severity="Material",
        action="Request the certificate",
    )
    report = integrity_review(scope, base.model_copy(update={"gaps": (gap,)}))
    assert report.status == "restricted" and report.findings == ()
    assert "Gap (Material): No covenant compliance certificate" in report.limitations
    stray = gap.model_copy(update={"affected_modules": ("CP-9",)})
    issues = validate_integrity(scope, base.model_copy(update={"gaps": (stray,)}))
    assert any("CP-9 is not a bound module" in issue for issue in issues)


def test_a_claim_resting_on_an_unsettled_fact_needs_a_limitation() -> None:
    pack = pack_fixture()
    gap = Fact(fact_id="T4.10.ebitda.FY2025", label="EBITDA", status="missing", limitation="Absent")
    claim = Claim(
        claim_id="ebitda", text="EBITDA is not stated [T4.10.ebitda.FY2025].", citations=()
    )
    head = module(pack, "CP-1", facts=(gap,), claims=(claim,))
    findings = python_checks(scope_of(pack, (head,))).findings
    assert [(f.kind, f.subject) for f in findings] == [("unsettled_fact", "claim ebitda")]
    limited = claim.model_copy(update={"limitation": "EBITDA is a gap in the pack"})
    head = module(pack, "CP-1", facts=(gap,), claims=(limited,))
    assert python_checks(scope_of(pack, (head,))).findings == ()


def test_a_blocked_upstream_is_a_finding_and_an_empty_set_is_not_accepted() -> None:
    pack = pack_fixture()
    blocked = module(pack, "CP-MODEL", status="blocked", limitations=("Synthetic block",))
    scope = scope_of(pack, (cp1_head(pack), blocked))
    report = integrity_review(scope, review_all(scope))
    assert report.status == "restricted"
    assert [(f.kind, f.subject) for f in report.findings] == [("blocked_upstream", "CP-MODEL")]
    empty = scope_of(pack, ())
    report = integrity_review(
        empty, IntegritySubmission(claim_reviews=(), contradictions=(), gaps=())
    )
    assert report.status == "restricted" and kinds(report) == {"empty_evaluated_set"}


def test_the_scope_refuses_a_head_that_is_not_its_bound_input() -> None:
    pack = pack_fixture()
    head = cp1_head(pack)
    other = Input(input_id="CP-1", sha256="0" * 64, status="accepted")
    with pytest.raises(ValueError, match="not the module its input names"):
        ReviewScope(pack=pack, inputs=(other,), heads=((other, head),))
    with pytest.raises(ValueError, match="is not a bound input"):
        ReviewScope(pack=pack, inputs=(), heads=((bound(head), head),))
    restricted = Input(input_id="CP-1", sha256=head.content_hash(), status="restricted")
    with pytest.raises(ValueError, match="status"):
        ReviewScope(pack=pack, inputs=(restricted,), heads=((restricted, head),))
    blocked = module(pack, "CP-1", status="blocked", limitations=("Synthetic block",))
    with pytest.raises(ValueError, match="blocked"):
        ReviewScope(pack=pack, inputs=(bound(blocked),), heads=((bound(blocked), blocked),))


def test_the_context_block_prefills_each_bound_module_and_the_source_list() -> None:
    scope = clean_scope()
    context = context_block(scope)
    assert [m["module_id"] for m in context["modules"]] == ["CP-1", "CP-1A", "CP-MODEL"]
    cp1 = context["modules"][0]
    assert cp1["status"] == "accepted" and cp1["limitations"] == []
    assert cp1["facts"][0]["ref"] == FIGURE and cp1["facts"][0]["shown"] == "1,100 US$ m"
    assert cp1["claims"][0]["citations"][0] == {
        "ref": "liquidity#c1",
        "source_id": "filing",
        "locator": "line:1",
        "quote": "cash",
    }
    assert cp1["claims"][0]["python_findings"] == []
    cp1a = context["modules"][1]
    assert cp1a["limitations"] and "inherited_limitations" in cp1a
    assert [s["source_id"] for s in context["sources"]] == ["filing"]
    assert ["CP-1", "liquidity"] in context["claims_to_review"]
    assert "evaluated set" in context["note"]
    flagged = context_block(planted_scope())["modules"][1]
    claim = next(c for c in flagged["claims"] if c["claim_id"] == "credit_translation.r01")
    assert claim["python_findings"] and "figure_identity" in claim["python_findings"][0]


def test_the_step_entry_registers_cleanly_and_routes_after_cp0() -> None:
    chain = StepChain(module_id=MODULE_ID, cell="cp5", steps=CP5_STEPS)
    assert chain.settling == STEP_ID and chain.pack_sources == frozenset()  # ruling 2
    chains = checked_chains((*STEP_CHAINS, chain))
    assert module_route(MODULE_ID, chains) == ("source_readiness", STEP_ID)
    assert NOT_EVALUATED == frozenset({"CP-0"})


def test_the_table_ids_are_the_coverage_maps_required_ids() -> None:
    coverage = json.loads(Path("docs/methodology/r14-coverage.json").read_text(encoding="utf-8"))
    entry = next(m for m in coverage["modules"] if m["module_id"] == "CP-5")
    assert list(TABLE_IDS) == entry["artifact_contract"]["required_table_ids"]


# --- rails ----------------------------------------------------------------------------------


def test_the_rails_carry_every_cp5_fact_once_with_parity() -> None:
    from deploy_vii.bindings.cp5 import CP5

    for scope, submission in (
        (clean_scope(), None),
        (planted_scope(), {("CP-MODEL", "model-publication"): "unsupported"}),
    ):
        report = integrity_review(scope, review_all(scope, submission))
        candidate = cp5_module(report, scope.inputs, 0)
        view = cp0_view(scope.pack, candidate, accepted=False)
        assert validate_bindings(view, (CP5,)) == ()
        pathway = next(item for item in pathways() if item.id == view.run.pathway)
        html = render(view, build(view, pathway, (CP5,)))
        shown = rendered_table_display(html)
        expected = expected_by_fact(view, (MODULE_ID,))
        assert expected and {k: shown[k] for k in expected} == expected
        assert {e.block_id for e in CP5.entries} == {"evidence", "limitations"}


def test_the_map_binds_every_table_and_routes_findings_to_limitations() -> None:
    from deploy_vii.bindings.cp5 import CP5

    by_table = {e.fact_coord.table_id: e.block_id for e in CP5.entries}
    assert sorted(map(str, by_table)) == sorted(TABLE_IDS)
    for table in ("T5.9", "T5B.2", "T5B.3", "T5B.5", "T5B.7"):
        assert by_table[table] == "limitations"
    assert all(e.cell_slot.startswith("cp5-") for e in CP5.entries)


def test_the_method_states_the_narrow_judgement_and_no_figure() -> None:
    from importlib.resources import files

    from deploy_vii.prose import bare_figures

    text = files("deploy_vii").joinpath("methods", "cp5.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) < 90
    for anchor in ("material support", "contradiction", "evaluated set only", "decision 0005"):
        assert anchor in text
    for table_id in TABLE_IDS:
        assert f"`{table_id}`" in text
    stripped = text
    for table_id in TABLE_IDS:
        stripped = stripped.replace(f"`{table_id}`", "")
    assert bare_figures(stripped.replace("decision 0005", "").replace("decision 0007", "")) == ()


# --- real heads -----------------------------------------------------------------------------

# The promoted CP-1 journal of the CP-MODEL tests (module-scoped fixtures, bound here by name).
model_scope = cp_model_tests.model_scope
promoted = cp_model_tests.promoted


def test_the_promoted_cp1_and_its_published_cp_model_raise_no_python_finding(
    promoted: Execution, tmp_path: Path
) -> None:
    """Real heads: every register of the promoted synthetic CP-1 and the CP-MODEL it publishes."""
    store = cp_model_tests.fresh(promoted, tmp_path)
    publish_cp_model(store, output=tmp_path / "model")
    heads = tuple(
        (
            Input(input_id=h.module_id, sha256=h.result_sha256, status=h.status),
            store.result(h.result_sha256),
        )
        for h in store.read().heads
        if h.module_id in {"CP-1", "CP-MODEL"}
    )
    scope = ReviewScope(pack=store.pack(), inputs=tuple(i for i, _ in heads), heads=heads)
    assert len(heads) == 2 and python_checks(scope).findings == ()
    report = integrity_review(scope, review_all(scope))
    assert report.status == "accepted" and report.findings == ()
    assert [i.input_id for i in report.evaluated] == ["CP-1", "CP-MODEL"]


# --- the journal ----------------------------------------------------------------------------


def candidate(store: Execution, head: Module) -> Module:
    return head.model_copy(
        update={"status": "candidate", "inputs": current_inputs(store.read(), head.module_id)}
    )


def journal(tmp_path: Path) -> Execution:
    """CP-0 accepted for the scope, then CP-1, CP-MODEL and CP-1A settled through the journal."""
    store = cp_model_store(tmp_path, SCOPE)
    pack = store.pack()
    cp1 = cp1_head(pack)
    settle_module(store, "CP-1", candidate(store, cp1))
    settle_module(store, "CP-MODEL", candidate(store, cp_model_head(pack)))
    inputs = current_inputs(store.read(), "CP-1A")
    settle_module(store, "CP-1A", cp1a_module(cp1a_report(pack, cp1), inputs, 0))
    return store


def test_the_journal_settles_cp5_over_the_bound_heads(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    scope = review_scope(store, ticket)
    assert scope.issues == ()
    assert {i.input_id for i, _ in scope.heads} == {"CP-1", "CP-MODEL", "CP-1A"}
    assert scope.inherited  # the synthetic and upstream limitations of the bound heads
    finished = submit_cp5_step(
        store, ticket.ticket_id, STEP_ID, review_all(scope).model_dump_json()
    )
    assert finished.status == "finished" and not finished.issues
    report = IntegrityReport.model_validate_json(step_text(store, finished.steps[-1]))
    assert report.status == "accepted"
    result = settled(store, finished)
    # A synthetic run restricts every module (decision 0007); CP-5's own findings are none.
    assert result.status == "restricted"
    assert result.limitations == ("Synthetic case; not real issuer qualification",)
    head = next(h for h in store.read().heads if h.module_id == MODULE_ID)
    assert head.qualification is not None and head.qualification.implementation == "implemented"
    rows = [f for f in result.facts if f.table_id == "T5B.7" and f.field == "origin"]
    assert rows and {f.text for f in rows} == {"Inherited"}


def test_an_incomplete_review_is_rejected_then_blocked_after_its_repair(tmp_path: Path) -> None:
    store = journal(tmp_path)
    statuses: list[str] = []
    for _ in range(2):
        ticket = store.begin(MODULE_ID)
        scope = review_scope(store, ticket)
        partial = review_all(scope, skip=frozenset({("CP-1", "liquidity")}))
        finished = submit_cp5_step(store, ticket.ticket_id, STEP_ID, partial.model_dump_json())
        result = settled(store, finished)
        statuses.append(result.status)
        assert any("Incomplete review" in text for text in result.limitations)
    assert statuses == ["rejected", "blocked"]
    head = next(h for h in store.read().heads if h.module_id == MODULE_ID)
    assert head.status == "blocked"


def test_a_stale_or_unreadable_input_makes_the_review_impossible(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)

    def changed(input_id: str, sha256: str) -> Attempt:
        inputs = tuple(
            item.model_copy(update={"sha256": sha256}) if item.input_id == input_id else item
            for item in ticket.inputs
        )
        return ticket.model_copy(update={"inputs": inputs})

    stale = review_scope(store, changed("CP-MODEL", "a" * 64))
    assert any("Stale input CP-MODEL" in issue for issue in stale.issues)
    assert any("Unreadable upstream head CP-MODEL" in issue for issue in stale.issues)
    assert validate_integrity(stale, review_all(clean_scope())) == stale.issues
    with pytest.raises(ValueError, match=r"Ticket is absent, finished or belongs to another"):
        submit_cp5_step(store, "missing-ticket", STEP_ID, "{}")
    with pytest.raises(ValueError, match="one step"):
        submit_cp5_step(store, ticket.ticket_id, "financials", "{}")


def test_a_malformed_submission_is_a_shape_rejection(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    finished = submit_cp5_step(store, ticket.ticket_id, STEP_ID, '{"claim_reviews": []}')
    result = settled(store, finished)
    assert result.status == "rejected"
    assert any("contradictions" in text and "Field required" in text for text in result.limitations)


def test_a_retained_valid_step_resumes_and_a_different_response_is_refused(
    tmp_path: Path,
) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    scope = review_scope(store, ticket)
    submission = review_all(scope)
    payload = submission.model_dump_json()
    output = integrity_review(scope, submission).model_dump_json()
    # The step is retained valid, then the process stops before CP-5 settles.
    pending = store.submit_step(
        ticket.ticket_id,
        MODULE_ID,
        CP5_STEPS,
        STEP_ID,
        payload,
        lambda _pack, _attempt: StepValidation(output=output),
    )
    assert pending.status == "pending" and pending.steps[0].status == "valid"
    other = review_all(scope, {("CP-1", "liquidity"): "unsupported"}).model_dump_json()
    with pytest.raises(ValueError, match="retains a different response"):
        submit_cp5_step(store, ticket.ticket_id, STEP_ID, other)
    finished = submit_cp5_step(store, ticket.ticket_id, STEP_ID, payload)
    assert finished.status == "finished" and settled(store, finished).status == "restricted"


def test_a_retained_output_that_trusted_validation_does_not_reproduce_is_refused(
    tmp_path: Path,
) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    scope = review_scope(store, ticket)
    submission = review_all(scope)
    gap = IntegrityGap(
        gap="A planted gap",
        why_it_matters="It changes the output",
        affected_modules=(),
        severity="Minor",
        action="None",
    )
    planted = integrity_review(scope, submission.model_copy(update={"gaps": (gap,)}))
    store.submit_step(
        ticket.ticket_id,
        MODULE_ID,
        CP5_STEPS,
        STEP_ID,
        submission.model_dump_json(),
        lambda _pack, _attempt: StepValidation(output=planted.model_dump_json()),
    )
    with pytest.raises(ValueError, match="differs from trusted validation"):
        submit_cp5_step(store, ticket.ticket_id, STEP_ID, submission.model_dump_json())


def test_unreadable_heads_and_underivable_inputs_refuse_the_review(tmp_path: Path) -> None:
    store = journal(tmp_path)
    ticket = store.begin(MODULE_ID)
    heads = {h.module_id: h for h in store.read().heads}
    swapped = tuple(
        item.model_copy(update={"sha256": heads["CP-1"].result_sha256})
        if item.input_id == "CP-MODEL"
        else item
        for item in ticket.inputs
    )
    wrong = review_scope(store, ticket.model_copy(update={"inputs": swapped}))
    assert "Unreadable upstream head CP-MODEL: not the bound module" in wrong.issues
    unselected = review_scope(store, ticket.model_copy(update={"module_id": "CP-8"}))
    assert any("current inputs cannot be derived" in issue for issue in unselected.issues)
    (store.directory / "blobs" / heads["CP-MODEL"].result_sha256).unlink()
    missing = review_scope(store, ticket)
    assert any(i.startswith("Unreadable upstream head CP-MODEL: ") for i in missing.issues)
    assert any("inherited limitations" in issue for issue in missing.issues)
    finished = submit_cp5_step(
        store, ticket.ticket_id, STEP_ID, review_all(clean_scope()).model_dump_json()
    )
    assert settled(store, finished).status == "rejected"


def test_a_scope_binds_each_head_once_and_model_text_is_never_blank() -> None:
    pack = pack_fixture()
    head = cp1_head(pack)
    with pytest.raises(ValueError, match="bound twice"):
        ReviewScope(pack=pack, inputs=(bound(head),), heads=((bound(head), head),) * 2)
    scope = clean_scope()
    base = review_all(scope)
    blank = base.claim_reviews[0].model_copy(update={"rationale": "  "})
    issues = validate_integrity(
        scope, base.model_copy(update={"claim_reviews": (blank, *base.claim_reviews[1:])})
    )
    assert "claim_reviews[0].rationale: empty text" in issues
    malformed = IntegritySubmission.model_construct(
        claim_reviews=(ClaimReview.model_construct(support="maybe"),),
        contradictions=(),
        gaps=(),
    )
    assert any("support" in issue for issue in validate_integrity(scope, malformed))


def test_each_contradiction_and_each_limitation_keeps_its_own_row() -> None:
    scope = clean_scope()
    pair = (
        ClaimRef(producer_module="CP-1", claim_ref="liquidity"),
        ClaimRef(producer_module="CP-MODEL", claim_ref="model-publication"),
    )
    one = Contradiction(claim_refs=pair, nature="Scope", rationale=RATIONALE, severity="Minor")
    two = one.model_copy(update={"nature": "Period", "severity": "Material"})
    gap = IntegrityGap(
        gap="No covenant compliance certificate",
        why_it_matters="Headroom cannot be traced",
        affected_modules=(),
        severity="Minor",
        action="Request the certificate",
    )
    submission = review_all(scope).model_copy(
        update={"contradictions": (one, two, one), "gaps": (gap,)}
    )
    report = integrity_review(scope, submission)

    def column(table_id: str, field: str) -> list[str | None]:
        return [f.text for f in report.facts if f.table_id == table_id and f.field == field]

    assert sorted(map(str, column("T5B.3", "nature"))) == ["Period", "Scope"]
    assert column("T5B.7", "origin") == ["CP-5 finding", "CP-5 finding", "CP-5 gap"]
    assert column("T5B.5", "affected_modules") == ["Report level"]


# --- properties (decision 0012) -------------------------------------------------------------

PACK = pack_fixture()
GOOD = good_citation(PACK)
BROKEN = (
    good_citation(PACK, "words the filing never says"),
    GOOD.model_copy(update={"locator": "line:9"}),
)
MODULES = ("CP-1", "CP-1A", "CP-MODEL")
FACT_IDS = ("f.a", "f.b", "f.c")


@st.composite
def figure(draw: st.DrawFn, fact_id: str) -> Fact:
    cited = draw(st.lists(st.sampled_from((GOOD, *BROKEN)), unique=True, max_size=2))
    if draw(st.integers(0, 5)) == 0:
        return Fact(fact_id=fact_id, label=fact_id, status="missing", limitation="Synthetic gap")
    return Fact(
        fact_id=fact_id,
        label=fact_id,
        table_id="T",
        row_id=draw(st.sampled_from(("r1", "r2"))),
        field="v",
        # 1000 at scale 1 is 1 at scale 1000: one value, two representations.
        amount=Decimal(draw(st.sampled_from(("1", "2", "2.0", "1000")))),
        unit=draw(st.sampled_from(("MILLIONS", "THOUSANDS", "currency"))),
        scale=Decimal(draw(st.sampled_from((1, 1000)))),
        currency=draw(st.sampled_from(("USD", "EUR"))),
        period=draw(st.sampled_from(("FY2024", "FY2025"))),
        citations=tuple(cited),
    )


@st.composite
def head(draw: st.DrawFn, module_id: str) -> Module:
    ids = draw(st.lists(st.sampled_from(FACT_IDS), unique=True, max_size=3))
    facts = tuple(draw(figure(fact_id)) for fact_id in ids)
    claims: list[Claim] = []
    for index in range(draw(st.integers(0, 2))):
        text = "Synthetic claim"
        if facts and draw(st.booleans()):
            fact = draw(st.sampled_from(facts))
            text = f"Synthetic {{{fact.fact_id}|MILLIONS}} claim"
        if draw(st.integers(0, 4)) == 0:
            text += " of 7"
        cited = draw(st.lists(st.sampled_from((GOOD, *BROKEN)), unique=True, max_size=2))
        limitation = draw(st.sampled_from((None, "Synthetic limitation")))
        claims.append(
            Claim(claim_id=f"c{index}", text=text, citations=tuple(cited), limitation=limitation)
        )
    return module(PACK, module_id, facts=facts, claims=tuple(claims))


@st.composite
def heads(draw: st.DrawFn, min_size: int = 1) -> tuple[Module, ...]:
    ids = draw(st.lists(st.sampled_from(MODULES), min_size=min_size, max_size=3, unique=True))
    return tuple(draw(head(module_id)) for module_id in ids)


def keys(scope: ReviewScope) -> set[tuple[str, str, tuple[str, ...]]]:
    """A finding's identity; an identity finding is keyed by its subject alone (a module that
    joins the group widens its module list without removing the disagreement)."""
    return {
        (f.kind, f.subject, () if f.kind == "figure_identity" else f.modules)
        for f in python_checks(scope).findings
    }


def replaced(heads_: tuple[Module, ...], new: Module) -> tuple[Module, ...]:
    return tuple(new if h.module_id == new.module_id else h for h in heads_)


def plant(heads_: tuple[Module, ...], data: st.DataObject) -> tuple[Module, str | None]:
    """One target head with a broken citation added, or a figure another module also carries
    altered beyond every amount; returns the head and the identity subject it must raise."""
    target = data.draw(st.sampled_from(heads_))
    mode = data.draw(st.sampled_from(("claim", "fact", "figure")))
    planted = good_citation(PACK, f"planted words {data.draw(st.integers(0, 999))}")
    others = [f for h in heads_ if h is not target for f in h.facts if f.amount is not None]
    if mode == "figure" and others:
        shared = data.draw(st.sampled_from(others))
        top = max(f.amount for h in heads_ for f in h.facts if f.amount is not None)
        mine = next((f for f in target.facts if f.fact_id == shared.fact_id), None)
        if mine is None or mine.amount is not None:
            altered = (mine or shared).model_copy(update={"amount": top + 1})
            kept = tuple(f for f in target.facts if f.fact_id != shared.fact_id)
            facts = (
                (*kept, altered)
                if mine is None
                else tuple(altered if f is mine else f for f in target.facts)
            )
            new = target.model_copy(update={"facts": facts})
            return Module.model_validate_json(new.model_dump_json()), f"fact_id {shared.fact_id}"
    if mode == "claim" and target.claims:
        claim = data.draw(st.sampled_from(target.claims))
        changed = claim.model_copy(update={"citations": (*claim.citations, planted)})
        claims = tuple(changed if c is claim else c for c in target.claims)
        new = target.model_copy(update={"claims": claims})
    else:
        fact = Fact(fact_id="planted", label="planted", text="x", citations=(planted,))
        new = target.model_copy(update={"facts": (*target.facts, fact)})
    return Module.model_validate_json(new.model_dump_json()), None


@settings(max_examples=80, deadline=None)
@given(heads(), st.data())
def test_findings_are_monotone_under_a_broken_citation_or_an_altered_figure(
    heads_: tuple[Module, ...], data: st.DataObject
) -> None:
    before_scope = scope_of(PACK, heads_)
    before = python_checks(before_scope).findings
    new, subject = plant(heads_, data)
    after_scope = scope_of(PACK, replaced(heads_, new))
    after = python_checks(after_scope).findings
    assert keys(before_scope) <= keys(after_scope)
    if subject is None:
        assert len(after) > len(before)
    else:
        assert len(after) >= len(before)
        assert ("figure_identity", subject, ()) in keys(after_scope)
    # Never a clean accept: either the verdict is refused or the review restricts.
    submission = review_all(after_scope)
    assert validate_integrity(after_scope, submission) == ()
    assert integrity_review(after_scope, submission).status == "restricted"


@settings(max_examples=60, deadline=None)
@given(heads(), st.randoms(use_true_random=False))
def test_the_verdict_is_independent_of_head_and_claim_order(
    heads_: tuple[Module, ...], rng: random.Random
) -> None:
    scope = scope_of(PACK, heads_)
    submission = review_all(scope)
    shuffled: list[Module] = []
    for item in heads_:
        claims, facts = list(item.claims), list(item.facts)
        rng.shuffle(claims)
        rng.shuffle(facts)
        shuffled.append(item.model_copy(update={"claims": tuple(claims), "facts": tuple(facts)}))
    rng.shuffle(shuffled)
    other = scope_of(PACK, tuple(shuffled))
    reviews = list(submission.claim_reviews)
    rng.shuffle(reviews)
    reordered = submission.model_copy(update={"claim_reviews": tuple(reviews)})
    assert python_checks(other).findings == python_checks(scope).findings
    assert validate_integrity(scope, submission) == validate_integrity(other, reordered) == ()
    first, second = integrity_review(scope, submission), integrity_review(other, reordered)
    assert (first.status, first.findings, first.limitations) == (
        second.status,
        second.findings,
        second.limitations,
    )

    # Reordered facts are another artifact (another content hash), which T5.1 records; every
    # other cell is the same.
    def cells(report: IntegrityReport) -> list[Fact]:
        return [f for f in report.facts if f.field != "bound_sha_256"]

    assert first.tables == second.tables and cells(first) == cells(second)


@settings(max_examples=60, deadline=None)
@given(heads(min_size=0), st.sets(st.sampled_from(MODULES), min_size=1), st.booleans())
def test_a_blocked_ancestor_is_restricted_never_accepted(
    heads_: tuple[Module, ...], blocked: set[str], as_head: bool
) -> None:
    if as_head:
        # A blocked analyst bound under its restricted edge: its head carries no output.
        stub = {
            m: module(PACK, m, status="blocked", limitations=("Synthetic block",)) for m in blocked
        }
        heads_ = (*(h for h in heads_ if h.module_id not in blocked), *stub.values())
    scope = scope_of(PACK, heads_, frozenset(blocked) | {"CP-1B"})
    submission = review_all(scope)
    assert validate_integrity(scope, submission) == ()
    report = integrity_review(scope, submission)
    assert report.status == "restricted"
    assert {f.subject for f in report.findings if f.kind == "blocked_upstream"} >= {"CP-1B"}


def naive_identity(modules: tuple[Module, ...]) -> set[str]:
    """Reference: a key held by two modules whose figure tuples, pooled as one set, differ.

    A figure is its exact value (amount times scale), unit, currency and period; under a
    fact id it is also its table, row and field. (The generator writes no reference-copy
    table, so the copy exemption is exercised by a focused test, not here.)"""
    pooled: dict[str, dict[str, set[tuple[object, ...]]]] = defaultdict(lambda: defaultdict(set))
    figured: dict[str, bool] = defaultdict(bool)
    for item in modules:
        for fact in item.facts:
            exact = None if fact.amount is None else fact.amount * fact.scale
            value = (exact, fact.unit, fact.currency, fact.period)
            placed = (*value, fact.table_id, fact.row_id, fact.field)
            pooled[f"fact_id {fact.fact_id}"][item.module_id].add(placed)
            figured[f"fact_id {fact.fact_id}"] |= fact.amount is not None
            if fact.amount is not None:
                where = f"coordinate {fact.table_id}/{fact.row_id}/{fact.field}/{fact.period}"
                pooled[where][item.module_id].add(value)
                figured[where] = True
    return {
        key
        for key, by_module in pooled.items()
        if len(by_module) > 1 and figured[key] and len(set().union(*by_module.values())) > 1
    }


@settings(max_examples=150, deadline=None)
@given(heads(min_size=2))
def test_figure_identity_matches_a_naive_set_comparison(heads_: tuple[Module, ...]) -> None:
    pair = heads_[:2]
    found = {f.subject for f in figure_identity(pair)}
    assert found == naive_identity(pair)
    assert all(f.kind == "figure_identity" and len(f.modules) > 1 for f in figure_identity(pair))


@settings(max_examples=100, deadline=None)
@given(heads())
def test_the_citation_pass_is_citation_issues_over_every_record(heads_: tuple[Module, ...]) -> None:
    found = {
        (f.modules[0], f.subject, f.detail)
        for f in python_checks(scope_of(PACK, heads_)).findings
        if f.kind in {"claim_citation", "fact_citation"}
    }
    direct = {
        (item.module_id, f"{kind} {record_id}", issue)
        for item in heads_
        for kind, record_id, citations in (
            *(("claim", c.claim_id, c.citations) for c in item.claims),
            *(("fact", f.fact_id, f.citations) for f in item.facts),
        )
        for issue in citation_issues(citations, PACK.sources)
    }
    assert found == direct


# --- fix round 1: placement, exact value and scale ---------------------------------------------


def placed(
    *,
    row: str = "r1",
    amount: str = "1100",
    unit: str = "currency",
    scale: str = "1",
    currency: str = "USD",
    table: str = "T",
) -> Fact:
    return Fact(
        fact_id="f.x",
        label="f.x",
        table_id=table,
        row_id=row,
        field="v",
        amount=Decimal(amount),
        unit=unit,
        scale=Decimal(scale),
        currency=currency,
        period="FY2025",
        citations=(GOOD,),
    )


def pair_findings(first: Fact, second: Fact) -> list[tuple[str, str, str]]:
    heads_ = (module(PACK, "CP-1", facts=(first,)), module(PACK, "CP-MODEL", facts=(second,)))
    return [(f.kind, f.subject, f.detail) for f in python_checks(scope_of(PACK, heads_)).findings]


def test_one_fact_id_at_another_row_is_a_mismatch_at_an_equal_amount() -> None:
    found = pair_findings(placed(row="r1"), placed(row="r2"))
    assert [(kind, subject) for kind, subject, _ in found] == [("figure_identity", "fact_id f.x")]
    assert found[0][2].startswith("differs in row_id between CP-1, CP-MODEL;")


def test_the_value_is_amount_times_scale_where_the_unit_leaves_scale_free() -> None:
    assert pair_findings(placed(amount="1.1", scale="1000"), placed(amount="1100")) == []


def test_a_scale_that_disagrees_with_its_unit_is_its_own_finding() -> None:
    found = pair_findings(
        placed(unit="THOUSANDS", amount="1100", scale="1"),
        placed(unit="THOUSANDS", amount="1.1", scale="1000"),
    )
    assert [(kind, subject) for kind, subject, _ in found] == [("scale_unit", "fact f.x")]
    assert "THOUSANDS" in found[0][2]
    consistent = placed(unit="MILLIONS", amount="1.1", scale="1000000")
    assert pair_findings(consistent, consistent) == []


def test_equal_amounts_in_two_currencies_are_a_mismatch() -> None:
    found = pair_findings(placed(currency="USD"), placed(currency="EUR"))
    assert {subject for _, subject, _ in found} == {"fact_id f.x", "coordinate T/r1/v/FY2025"}
    assert all("currency" in detail for _, _, detail in found)


def test_only_the_cp1a_reference_copy_keeps_python_assigned_coordinates() -> None:
    copy = placed(table=CP1_REFERENCES, row="ref01")
    assert pair_findings(placed(), copy) == []
    assert pair_findings(placed(), copy.model_copy(update={"amount": Decimal("1200")}))
    moved = pair_findings(placed(), placed(table="T4.10"))
    assert [(kind, subject) for kind, subject, _ in moved] == [("figure_identity", "fact_id f.x")]
    assert "table_id" in moved[0][2]


def test_the_context_block_takes_a_fact_projection() -> None:
    scope = clean_scope()
    whole = context_block(scope)
    assert context_block(scope, facts=lambda head: head.facts) == whole
    trimmed = context_block(scope, facts=lambda head: head.facts[:1])
    assert [len(m["facts"]) for m in trimmed["modules"]] == [1, 1, 1]
    assert [m["claims"] for m in trimmed["modules"]] == [m["claims"] for m in whole["modules"]]
    assert trimmed["python_findings"] == whole["python_findings"]
