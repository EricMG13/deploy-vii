from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from deploy_vii.balance_movement import balance_movement_issues
from deploy_vii.contracts import Claim, Fact, Input, Module, ModuleView, Run, Source, Span, View
from deploy_vii.registry import canonical, modules, plan
from deploy_vii.statement_validation import statement_issues
from tests.product.test_balance_movement import bridge_case
from tests.product.test_statements import line, statements


def test_all_r14_owners_and_aliases_resolve() -> None:
    assert len(modules()) == 25
    assert sum(1 + len(module.aliases) for module in modules()) == 41
    for module in modules():
        assert canonical(module.module_id) == module.module_id
        for alias in module.aliases:
            assert canonical(alias) == module.module_id
    with pytest.raises(ValueError, match="Unknown"):
        canonical("CP-99")


def test_core_dependency_order_has_business_context_and_qa_before_challenge() -> None:
    order = plan(("CP-6", "CP-4"))
    for before, after in (("CP-1A", "CP-2"), ("CP-2", "CP-3"), ("CP-5", "CP-6")):
        assert order.index(before) < order.index(after)
    assert order.index("CP-4") < order.index("CP-5")
    assert len(order) == len(set(order))
    assert plan(("CP-3A",)) == plan(("CP-3",))


def test_run_identity_is_frozen_and_dates_parse_from_json() -> None:
    run = Run.model_validate_json(
        '{"run_id":"test","issuer_id":"synthetic","issuer_name":"Synthetic issuer",'
        '"as_of":"2026-10-21","case_kind":"synthetic"}'
    )
    assert run.as_of == date(2026, 10, 21)
    with pytest.raises(ValidationError):
        run.issuer_name = "changed"


def test_missing_fact_is_not_zero() -> None:
    with pytest.raises(ValidationError):
        Fact(fact_id="cash", label="Cash", amount=Decimal(0), status="missing", limitation="Absent")
    missing = Fact(fact_id="cash", label="Cash", status="missing", limitation="Absent")
    assert missing.amount is None
    assert missing.text is None


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_nonfinite_financial_values_rejected(value: Decimal) -> None:
    with pytest.raises(ValidationError):
        Fact(fact_id="cash", label="Cash", amount=value, unit="USD", period="FY2025")


def test_ready_source_requires_evidence_identity() -> None:
    with pytest.raises(ValidationError):
        Source(source_id="filing", name="Filing", status="ready")
    source = Source(source_id="filing", name="Filing", status="missing", limitation="Not supplied")
    assert source.sha256 is None


@pytest.mark.parametrize(
    "extra",
    [
        {"scale": Decimal(0), "text": "bad"},
        {"amount": Decimal(1), "text": "both", "period": "FY", "unit": "x"},
        {},
        {"status": "missing"},
        {"amount": Decimal(1)},
    ],
)
def test_fact_boundary_contracts(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Fact(fact_id="x", label="Test", **extra)


def test_source_contracts_and_stable_hash() -> None:
    with pytest.raises(ValidationError):
        Source(source_id="x", name="Absent", status="missing")
    with pytest.raises(ValidationError):
        Source(source_id="x", name="Absent", status="missing", sha256="a" * 64, limitation="Absent")
    with pytest.raises(ValidationError):
        Source(
            source_id="x",
            name="Duplicate",
            status="ready",
            sha256="a" * 64,
            spans=(Span(locator="same", text="one"), Span(locator="same", text="two")),
        )
    source = Source(source_id="x", name="Absent", status="missing", limitation="Absent")
    assert (
        source.content_hash() == Source.model_validate_json(source.model_dump_json()).content_hash()
    )


def test_module_duplicate_and_unrun_contracts() -> None:
    base = {"run_id": "r", "issuer_id": "i", "as_of": date(2026, 10, 21), "module_id": "CP-1"}
    fact = Fact(fact_id="x", label="Test", text="One")
    with pytest.raises(ValidationError):
        Module(**base, facts=(fact, fact))
    with pytest.raises(ValidationError):
        Module(**base, status="blocked")
    with pytest.raises(ValidationError):
        Module(**base, status="unrun", facts=(fact,))
    assert Module(**base, facts=(fact,)).status == "candidate"
    claim = Claim(claim_id="x", text="candidate", citations=())
    with pytest.raises(ValidationError):
        Module(**base, claims=(claim, claim))


def test_claim_text_is_run_text_with_well_formed_references() -> None:
    """MC-2: the contract checks reference syntax; resolution needs the module's facts."""
    text = "Revenue {fact-1|US$ m} in FY2025; debt [gap.debt] is open."
    assert Claim(claim_id="x", text=text, citations=()).text == text
    # Same shape as module/5: a bare figure is a module-validation issue, not a schema error.
    assert Claim(claim_id="x", text="Debt rose 12%", citations=()).text == "Debt rose 12%"
    for malformed in ("Revenue {fact-1", "Revenue {}", "See [] and", "Unit {fact-1|}"):
        with pytest.raises(ValidationError, match="Malformed run text"):
            Claim(claim_id="x", text=malformed, citations=())


def test_module_v5_inherited_limitations_input_status_and_old_store_rejection() -> None:
    base = {"run_id": "r", "issuer_id": "i", "as_of": date(2026, 10, 21), "module_id": "CP-3"}
    assert Input(input_id="CP-4", sha256="a" * 64).status == "accepted"
    with pytest.raises(ValidationError):
        Input(input_id="CP-4", sha256="a" * 64, status="stale")
    with pytest.raises(ValidationError):
        Module(**base, status="restricted")
    inherited = Module(
        **base, status="restricted", inherited_limitations=("Upstream CP-4 blocked",)
    )
    assert inherited.limitations == ()
    raw = inherited.model_dump_json().replace("module/5", "module/3")
    with pytest.raises(ValidationError, match="module/5"):
        Module.model_validate_json(raw)


def test_view_rejects_duplicate_and_unrun_outputs() -> None:
    fact = Fact(fact_id="x", label="Test", text="One")
    with pytest.raises(ValidationError):
        ModuleView(module_id="CP-1", title="Test", aliases=(), status="candidate", facts=(fact,))
    with pytest.raises(ValidationError):
        ModuleView(module_id="CP-1", title="Test", aliases=(), artifact_sha256="a" * 64)
    view = ModuleView(module_id="CP-1", title="Test", aliases=())
    run = Run(
        run_id="r",
        issuer_id="i",
        issuer_name="Issuer",
        as_of=date(2026, 10, 21),
        case_kind="synthetic",
    )
    with pytest.raises(ValidationError):
        View(run=run, mode="candidate", modules=(view, view))


def test_cycle_rejected_and_empty_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    from deploy_vii import registry

    assert plan(()) == ()
    cyclic = tuple(
        module.model_copy(update={"required": ("CP-1",)}) if module.module_id == "CP-0" else module
        for module in modules()
    )
    monkeypatch.setattr(registry, "modules", lambda: cyclic)
    with pytest.raises(ValueError, match="cyclic"):
        plan(("CP-1",))


@pytest.mark.parametrize("status", ["unrun", "not_in_pathway"])
def test_module_outside_a_run_state_carries_no_outputs(status: str) -> None:
    base = {"run_id": "r", "issuer_id": "i", "as_of": date(2026, 10, 21), "module_id": "CP-1"}
    fact = Fact(fact_id="x", label="Test", text="One")
    claim = Claim(claim_id="c", text="claim", citations=())
    for outputs in ({"facts": (fact,)}, {"claims": (claim,)}):
        with pytest.raises(ValidationError, match=f"{status} module cannot carry outputs"):
            Module(**base, status=status, **outputs)  # type: ignore[arg-type]
    assert Module(**base, status=status).status == status  # type: ignore[arg-type]


# --- task 7.0d fix 1: the sent schema lists statement item ids; Python still splits them ----


@pytest.mark.parametrize(
    "item, statement", [("invented_item", "CFS"), ("goodwill", "IS")], ids=["unknown", "wrong-kind"]
)
def test_an_unknown_or_wrong_statement_item_id_is_still_refused(item: str, statement: str) -> None:
    """The sent enum is the flat union of the three statements; the per-statement split and the
    message are Python's, unchanged."""
    book = statements()
    assert not [issue for issue in statement_issues(book) if "Unknown statement item" in issue]
    extra = line("x", item, "1", 9, statement=statement)
    changed = book.model_copy(update={"statement_lines": (*book.statement_lines, extra)})
    expected = f"Unknown statement item; issuer detail requires other: prefix: {item}"
    assert expected in statement_issues(changed)


def test_a_balance_bridge_on_a_non_bs_item_is_still_refused() -> None:
    book = bridge_case()
    assert not [issue for issue in balance_movement_issues(book) if "requires a BS item" in issue]
    first, *rest = book.balance_movement_bridges
    changed = book.model_copy(
        update={
            "balance_movement_bridges": (
                first.model_copy(update={"balance_item_id": "revenue"}),
                *rest,
            )
        }
    )
    expected = f"Balance movement requires a BS item: {first.bridge_id}"
    assert expected in balance_movement_issues(changed)
