import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import pytest
from playwright.sync_api import expect, sync_playwright

from deploy_vii.contracts import Claim, Input, Module
from deploy_vii.execution import Execution, candidate_issues, current_inputs
from deploy_vii.preparation import PreparedPack
from deploy_vii.readiness import ReadinessReview, build_readiness, validate_review
from deploy_vii.render import render
from tests.product.test_readiness import readiness_fixture


def fixture_store(tmp_path: Path) -> Execution:
    pack, _ = readiness_fixture()
    return Execution.create(tmp_path / "execution", pack)


def candidate_for(store: Execution, module_id: str, attempt: int = 0) -> Module:
    snapshot = store.read()
    run = snapshot.pack.run
    return Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id=module_id,
        attempt=attempt,
        inputs=current_inputs(snapshot, module_id),
        claims=(
            Claim(
                claim_id="synthetic",
                text="Synthetic engine test only",
                citations=(),
                limitation="Tests engine ordering, not an implemented financial module",
            ),
        ),
        limitations=("Synthetic engine fixture; no financial qualification",),
    )


def accept_cp0(store: Execution) -> str:
    _, review = readiness_fixture()
    ticket = store.begin("CP-PARSE")
    candidate = build_readiness(store.read().pack, review)
    result = store.finish(ticket.ticket_id, candidate.model_dump_json(), lambda _: ())
    assert result.result is not None and result.result.status == "restricted"
    return ticket.ticket_id


def test_initial_gates_and_current_lineage(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    with pytest.raises(ValueError, match="upstream"):
        store.begin("CP-1")
    with pytest.raises(ValueError, match="not selected"):
        store.begin("CP-2G")
    ticket = accept_cp0(store)
    assert store.read().parent
    with pytest.raises(ValueError, match="settled"):
        store.begin("CP-0")
    with pytest.raises(ValueError, match="finished"):
        store.finish(ticket, "{}", lambda _: ())
    first = store.begin("CP-1")
    assert [item.input_id for item in first.inputs] == ["prepared-pack", "CP-0"]
    with pytest.raises(ValueError, match="pending"):
        store.begin("CP-1A")
    candidate = candidate_for(store, "CP-1")
    result = store.finish(first.ticket_id, candidate.model_dump_json(), lambda _: ())
    assert result.result is not None
    carried = {*result.result.limitations, *result.result.inherited_limitations}
    assert set(store.read().heads[0].limitations) <= carried
    assert store.view().mode == "accepted"


def test_one_targeted_repair_then_block_and_retain_payloads(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    first = store.begin("CP-0")
    rejected = store.finish(first.ticket_id, '{"bad":true}', lambda _: ())
    assert rejected.result is not None and rejected.result.status == "rejected"
    assert store.view().modules[0].status == "unrun"
    repair = store.begin("CP-0")
    assert repair.number == 1
    assert repair.repair_of == first.ticket_id
    assert repair.repair_issues == rejected.issues
    blocked = store.finish(repair.ticket_id, "not json", lambda _: ())
    assert blocked.result is not None and blocked.result.status == "blocked"
    assert [item.payload for item in store.read().attempts] == ['{"bad":true}', "not json"]
    assert store.view().modules[0].status == "blocked"
    assert not store.view().modules[0].facts
    with pytest.raises(ValueError, match="repair"):
        store.begin("CP-0")
    with pytest.raises(ValueError, match="upstream"):
        store.begin("CP-1")


def test_interruption_and_process_resume_keep_same_budget(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    first = store.begin("CP-0")
    resumed = Execution(store.directory)
    assert resumed.read().attempts[-1] == first
    with pytest.raises(ValueError, match="reason"):
        resumed.interrupt(first.ticket_id, " ")
    interrupted = resumed.interrupt(
        first.ticket_id, "Provider request interrupted; response unknown"
    )
    assert interrupted.issues == ("Interrupted: Provider request interrupted; response unknown",)
    assert interrupted.interruption
    repair = resumed.begin("CP-0")
    assert repair.number == 1
    _, review = readiness_fixture()
    candidate = build_readiness(resumed.read().pack, review, attempt=1)
    accepted = resumed.finish(repair.ticket_id, candidate.model_dump_json(), lambda _: ())
    assert accepted.result is not None and accepted.result.status == "restricted"
    with pytest.raises(ValueError, match="settled"):
        Execution(store.directory).begin("CP-0")


@pytest.mark.parametrize(
    "change", ["issuer", "date", "attempt", "status", "module", "pack", "extra"]
)
def test_false_identity_or_input_binding_rejected(tmp_path: Path, change: str) -> None:
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    _, review = readiness_fixture()
    candidate = build_readiness(store.read().pack, review)
    raw = json.loads(candidate.model_dump_json())
    if change == "issuer":
        raw["issuer_id"] = "different"
    elif change == "date":
        raw["as_of"] = "2001-01-01"
    elif change == "attempt":
        raw["attempt"] = 1
    elif change == "status":
        raw["status"] = "accepted"
    elif change == "module":
        raw["module_id"] = "CP-1"
    elif change == "pack":
        raw["inputs"][0]["sha256"] = "0" * 64
    else:
        raw["inputs"].append({"input_id": "CP-6", "sha256": "0" * 64})
    result = store.finish(ticket.ticket_id, json.dumps(raw), lambda _: ())
    assert result.issues
    with pytest.raises(ValueError, match="identity or provenance"):
        store.view(ticket.ticket_id)


def test_false_quote_never_reaches_module_validator(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    _, review = readiness_fixture()
    candidate = build_readiness(store.read().pack, review)
    claim = candidate.claims[0]
    false = claim.citations[0].model_copy(update={"quote": "Invented evidence"})
    candidate = candidate.model_copy(
        update={"claims": (claim.model_copy(update={"citations": (false,)}),)}
    )

    def must_not_run(_: Module) -> tuple[str, ...]:
        raise AssertionError("Untrusted candidate reached analytical validator")

    result = store.finish(ticket.ticket_id, candidate.model_dump_json(), must_not_run)
    assert any("Quote/locator" in issue for issue in result.issues)


def test_module_validation_failure_is_retained_and_repaired(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    _, review = readiness_fixture()
    candidate = build_readiness(store.read().pack, review)
    rejected = store.finish(
        ticket.ticket_id, candidate.model_dump_json(), lambda _: ("Required register absent",)
    )
    assert rejected.issues == ("Required register absent",)
    assert store.view(ticket.ticket_id).modules[0].status == "candidate"
    assert store.view().modules[0].status == "unrun"


def test_validator_error_leaves_pending_ticket_and_does_not_consume_extra_attempt(
    tmp_path: Path,
) -> None:
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    candidate = candidate_for(store, "CP-0")

    def crashed(_: Module) -> tuple[str, ...]:
        raise RuntimeError("validator fault")

    with pytest.raises(RuntimeError, match="validator fault"):
        store.finish(ticket.ticket_id, candidate.model_dump_json(), crashed)
    retained = store.read().attempts[-1]
    assert retained.status == "pending"
    assert retained.payload == candidate.model_dump_json()
    with pytest.raises(ValueError, match="different response"):
        store.finish(ticket.ticket_id, "{}", lambda _: ())
    store.finish(
        ticket.ticket_id, candidate.model_dump_json(), lambda _: ("Missing readiness fields",)
    )
    assert len(store.read().attempts) == 1


def test_changed_pack_stales_consumers_and_original_budget_cannot_be_reset(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    old_pack = store.read().pack
    cp0_ticket = accept_cp0(store)
    cp1_ticket = store.begin("CP-1")
    store.finish(cp1_ticket.ticket_id, candidate_for(store, "CP-1").model_dump_json(), lambda _: ())
    changed_source = old_pack.sources[0].model_copy(
        update={"limitation": "New fidelity restriction"}
    )
    changed_pack = old_pack.model_copy(update={"sources": (changed_source,)})
    store.replace_pack(changed_pack)
    assert all(item.status == "stale" for item in store.read().heads)
    assert all(not item.facts and not item.claims for item in store.view().modules)
    with pytest.raises(ValueError, match="stale"):
        store.view(cp0_ticket)
    with pytest.raises(ValueError, match="upstream"):
        store.begin("CP-1")
    new_ticket = store.begin("CP-0")
    assert new_ticket.number == 0
    with pytest.raises(ValueError, match="pending"):
        store.replace_pack(old_pack)
    store.interrupt(new_ticket.ticket_id, "Explicit test cancellation")
    store.replace_pack(old_pack)
    with pytest.raises(ValueError, match="settled"):
        store.begin("CP-0")
    store.replace_pack(old_pack)  # No-op leaves history intact.
    with pytest.raises(ValueError, match="identity"):
        store.replace_pack(
            old_pack.model_copy(
                update={"run": old_pack.run.model_copy(update={"issuer_id": "other"})}
            )
        )


def test_missing_cp0_readiness_command_fails_closed(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    store.finish(ticket.ticket_id, candidate_for(store, "CP-0").model_dump_json(), lambda _: ())
    with pytest.raises(ValueError, match="source readiness"):
        store.begin("CP-1")


def test_two_writers_cannot_reserve_two_initial_attempts(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)

    def reserve() -> str:
        try:
            return Execution(store.directory).begin("CP-0").ticket_id
        except ValueError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert results.count("refused") == 1
    assert len(store.read().attempts) == 1


def test_snapshot_tampering_incomplete_pointer_and_existing_store(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    original = store.read()
    with pytest.raises(FileExistsError):
        Execution.create(store.directory, original.pack)
    store._write(original)  # Identical content-addressed snapshot is idempotent.
    digest = (store.directory / "current").read_text().strip()
    path = store.directory / "snapshots" / f"{digest}.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        store.read()
    with pytest.raises(ValueError, match="corrupt"):
        store._write(original)
    (store.directory / "current").write_text("../../anything")
    with pytest.raises(ValueError, match="pointer"):
        store.read()


def test_transitive_invalidation_is_local_to_consumers() -> None:
    from deploy_vii.execution import invalidate

    pack, _ = readiness_fixture()
    run = pack.run

    def artifact(module_id: str, upstream: tuple[str, ...]) -> Module:
        return Module(
            run_id=run.run_id,
            issuer_id=run.issuer_id,
            as_of=run.as_of,
            module_id=module_id,
            status="accepted",
            inputs=tuple(Input(input_id=item, sha256="0" * 64) for item in upstream),
        )

    heads = (
        artifact("CP-1", ("CP-0",)),
        artifact("CP-2", ("CP-1",)),
        artifact("CP-3", ("CP-2",)),
        artifact("CP-4", ("CP-0",)),
    )
    changed = invalidate(heads, "CP-1")
    assert [item.status for item in changed] == ["accepted", "stale", "stale", "accepted"]
    assert invalidate(changed, "CP-1") == changed


@pytest.mark.browser
@pytest.mark.parametrize("width", [1440, 1280])
def test_cumulative_accepted_view_suppresses_stale_facts_offline(
    tmp_path: Path, width: int
) -> None:
    store = fixture_store(tmp_path)
    ticket = accept_cp0(store)
    evidence = Path("artifacts/rendering/execution") / tmp_path.parent.name / tmp_path.name
    evidence.mkdir(parents=True)
    for mode, view in (("candidate", store.view(ticket)), ("accepted", store.view())):
        (evidence / f"{mode}.json").write_text(view.model_dump_json(indent=2))
        (evidence / f"{mode}.html").write_text(render(view))
    snapshot = store.read()
    changed = snapshot.pack.model_copy(update={"sources": ()})
    store.replace_pack(changed)
    (evidence / "stale.html").write_text(render(store.view()))
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": width, "height": 900 if width == 1440 else 800}, offline=True
        )
        context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((evidence / "accepted.html").resolve().as_uri() + "#CP-0")
        expect(page.locator('[data-fact-id="T7.run.preparation"]')).to_have_text(
            snapshot.pack.content_hash()
        )
        page.screenshot(path=str(evidence / "accepted.png"), full_page=True)
        page.goto((evidence / "stale.html").resolve().as_uri() + "#CP-0")
        expect(page.locator("[data-fact-id]")).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
        page.screenshot(path=str(evidence / "stale.png"), full_page=True)
        context.tracing.stop(path=str(evidence / "trace.zip"))
        browser.close()


def test_retained_response_interruption_and_parent_chain(tmp_path: Path) -> None:
    from deploy_vii.execution import ExecutionSnapshot

    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    before = store.read()
    candidate = candidate_for(store, "CP-0")

    def crashed(_: Module) -> tuple[str, ...]:
        raise RuntimeError("Local validator crash")

    with pytest.raises(RuntimeError):
        store.finish(ticket.ticket_id, candidate.model_dump_json(), crashed)
    retained = store.read()
    assert retained.parent == before.content_hash()
    result = store.interrupt(ticket.ticket_id, "Interrupted after retained response")
    assert result.payload == candidate.model_dump_json()
    assert result.interruption == "Interrupted after retained response"
    final = store.read()
    assert final.parent == retained.content_hash()
    parent = store.directory / "snapshots" / f"{final.parent}.json"
    assert ExecutionSnapshot.model_validate_json(parent.read_bytes()) == retained
    with pytest.raises(ValueError, match="Unknown"):
        store.view("missing")
    repair = store.begin("CP-0")
    with pytest.raises(ValueError, match="Pending"):
        store.view(repair.ticket_id)
    with pytest.raises(ValueError, match="reason"):
        store.finish(repair.ticket_id, "", lambda _: (), interruption=" ")


def test_concurrent_finish_publishes_exactly_one_result(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    ticket = store.begin("CP-0")
    candidate = candidate_for(store, "CP-0").model_dump_json()

    def finish() -> str:
        try:
            return (
                Execution(store.directory).finish(ticket.ticket_id, candidate, lambda _: ()).status
            )
        except ValueError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: finish(), range(2)))
    assert sorted(results) == ["finished", "refused"]
    assert len(store.read().heads) == 1


# --- Degradation and status semantics (decision 0007) ---------------------------------------


def settle_module(store: Execution, module_id: str, candidate: Module | None = None) -> Module:
    ticket = store.begin(module_id)
    payload = candidate if candidate is not None else candidate_for(store, module_id)
    result = store.finish(ticket.ticket_id, payload.model_dump_json(), lambda _: ())
    assert result.result is not None
    return result.result


def block_module(store: Execution, module_id: str) -> Module:
    """Two failed attempts: the first is rejected, the repair leaves a blocked head."""
    for _ in range(2):
        ticket = store.begin(module_id)
        result = store.finish(ticket.ticket_id, "not json", lambda _: ())
    assert result.result is not None and result.result.status == "blocked"
    return result.result


def settle_through(store: Execution, *module_ids: str) -> None:
    accept_cp0(store)
    for module_id in module_ids:
        settle_module(store, module_id)


def bound(module: Module, module_id: str) -> Input:
    return next(item for item in module.inputs if item.input_id == module_id)


def test_blocked_optional_producer_does_not_halt_core_report(tmp_path: Path) -> None:
    """Review C2: a blocked CP-4 used to remove CP-3, CP-5 and CP-6 from the report."""
    store = fixture_store(tmp_path)
    settle_through(store, "CP-1", "CP-1A", "CP-2")
    blocked = block_module(store, "CP-4")

    cp3 = settle_module(store, "CP-3")
    cp5 = settle_module(store, "CP-5")
    cp6 = settle_module(store, "CP-6")

    for module in (cp3, cp5):
        assert bound(module, "CP-4") == Input(
            input_id="CP-4", sha256=blocked.content_hash(), status="blocked"
        )
    for module in (cp3, cp5, cp6):
        assert module.status == "restricted"
        assert any("Upstream CP-4 blocked" in text for text in module.inherited_limitations)
        assert not any("Upstream CP-4 blocked" in text for text in module.limitations)
    views = {item.module_id: item for item in store.view().modules}
    assert views["CP-4"].status == "blocked"
    assert {views[item].status for item in ("CP-3", "CP-5", "CP-6")} == {"restricted"}
    assert views["CP-3"].limitations == (*cp3.limitations, *cp3.inherited_limitations)


def test_blocked_required_producer_under_block_rule_still_halts(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    settle_through(store, "CP-1", "CP-1A")
    block_module(store, "CP-2")
    with pytest.raises(ValueError, match="upstream"):
        store.begin("CP-3")


def test_blocked_required_producer_under_restricted_rule_runs_limited(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    settle_through(store, "CP-1")
    blocked = block_module(store, "CP-1A")
    cp2 = settle_module(store, "CP-2")
    assert bound(cp2, "CP-1A") == Input(
        input_id="CP-1A", sha256=blocked.content_hash(), status="blocked"
    )
    assert cp2.status == "restricted"
    assert any("Upstream CP-1A blocked" in text for text in cp2.inherited_limitations)


def test_unrun_stale_or_rejected_producer_never_degrades(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    settle_through(store, "CP-1", "CP-1A", "CP-2")
    first = store.begin("CP-4")
    rejected = store.finish(first.ticket_id, "not json", lambda _: ())
    assert rejected.result is not None and rejected.result.status == "rejected"
    # CP-4 is selected and its edge to CP-3 is restricted, yet a rejected attempt has no head.
    with pytest.raises(ValueError, match="upstream"):
        store.begin("CP-3")

    repair = store.begin("CP-4")
    blocked = store.finish(repair.ticket_id, "not json", lambda _: ()).result
    assert blocked is not None and blocked.status == "blocked"
    snapshot = store.read()
    for status in ("stale", "rejected", "unrun"):
        changed = blocked.model_copy(update={"status": status})
        heads = tuple(changed if item.module_id == "CP-4" else item for item in snapshot.heads)
        with pytest.raises(ValueError, match="upstream"):
            current_inputs(snapshot.model_copy(update={"heads": heads}), "CP-3")
    assert store.begin("CP-3").number == 0  # only a settled blocked head degrades


def test_input_status_is_bound_exactly(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    settle_through(store, "CP-1", "CP-1A", "CP-2")
    blocked = block_module(store, "CP-4")
    ticket = store.begin("CP-3")
    candidate = candidate_for(store, "CP-3")
    assert candidate_issues(store.read(), ticket, candidate) == ()
    assert bound(candidate, "CP-4") == Input(
        input_id="CP-4", sha256=blocked.content_hash(), status="blocked"
    )
    for false_status in ("accepted", "restricted"):
        inputs = tuple(
            item.model_copy(update={"status": false_status}) if item.input_id == "CP-4" else item
            for item in candidate.inputs
        )
        issues = candidate_issues(
            store.read(), ticket, candidate.model_copy(update={"inputs": inputs})
        )
        assert issues == ("Candidate does not bind the exact current upstream inputs",)


def public_readiness_fixture() -> tuple[PreparedPack, ReadinessReview]:
    """Test fixture, not qualification: a public-case pack with one CP-0 note only."""
    pack, review = readiness_fixture()
    run = pack.run.model_copy(update={"case_kind": "public"})
    pack = PreparedPack.model_validate_json(pack.model_copy(update={"run": run}).model_dump_json())
    note = "Source authority is unknown; one text extract only"
    review = review.model_copy(
        update={
            "pack_sha256": pack.content_hash(),
            "sources": tuple(
                source.model_copy(update={"limitations": (note,)}) for source in review.sources
            ),
            "consumers": tuple(
                consumer.model_copy(update={"limitations": (note,)})
                for consumer in review.consumers
            ),
            "gaps": (),
        }
    )
    assert validate_review(pack, review) == ()
    return pack, review


def test_pass_reachable_with_immaterial_inherited_gap(tmp_path: Path) -> None:
    """Review W1, on a public-case test fixture (not a qualification run)."""
    pack, review = public_readiness_fixture()
    store = Execution.create(tmp_path / "execution", pack)
    ticket = store.begin("CP-0")
    candidate = build_readiness(store.read().pack, review)
    cp0 = store.finish(ticket.ticket_id, candidate.model_dump_json(), lambda _: ()).result
    assert cp0 is not None and cp0.status == "restricted"
    assert len(cp0.limitations) == 1 and not cp0.inherited_limitations

    clean = Module(
        run_id=pack.run.run_id,
        issuer_id=pack.run.issuer_id,
        as_of=pack.run.as_of,
        module_id="CP-1",
        inputs=current_inputs(store.read(), "CP-1"),
    )
    cp1 = settle_module(store, "CP-1", clean)
    assert cp1.status == "accepted"
    assert cp1.limitations == ()
    assert cp1.inherited_limitations == cp0.limitations
    assert [item.status for item in cp1.inputs] == ["accepted", "restricted"]
    shown = next(item for item in store.view().modules if item.module_id == "CP-1")
    assert shown.status == "accepted" and shown.limitations == cp0.limitations


def test_blocked_input_restricts_a_clean_module_even_when_not_synthetic(tmp_path: Path) -> None:
    """A blocked input is a material inherited gap: no own findings, still not accepted."""
    pack, review = public_readiness_fixture()
    store = Execution.create(tmp_path / "execution", pack)
    ticket = store.begin("CP-0")
    candidate = build_readiness(store.read().pack, review)
    store.finish(ticket.ticket_id, candidate.model_dump_json(), lambda _: ())

    def clean(module_id: str) -> Module:
        return Module(
            run_id=pack.run.run_id,
            issuer_id=pack.run.issuer_id,
            as_of=pack.run.as_of,
            module_id=module_id,
            inputs=current_inputs(store.read(), module_id),
        )

    settle_module(store, "CP-1", clean("CP-1"))
    block_module(store, "CP-1A")
    cp2 = settle_module(store, "CP-2", clean("CP-2"))
    assert cp2.limitations == ()
    assert cp2.status == "restricted"
    assert any("Upstream CP-1A blocked" in text for text in cp2.inherited_limitations)


def public_store_after_cp0(tmp_path: Path) -> Execution:
    """Test fixture, not qualification: public-case run with CP-0 settled."""
    pack, review = public_readiness_fixture()
    store = Execution.create(tmp_path / "execution", pack)
    ticket = store.begin("CP-0")
    candidate = build_readiness(store.read().pack, review)
    store.finish(ticket.ticket_id, candidate.model_dump_json(), lambda _: ())
    return store


def settle_clean(store: Execution, module_id: str, *limitations: str) -> Module:
    run = store.read().pack.run
    candidate = Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id=module_id,
        inputs=current_inputs(store.read(), module_id),
        limitations=limitations,
    )
    return settle_module(store, module_id, candidate)


def test_blocked_ancestor_restricts_transitive_consumers(tmp_path: Path) -> None:
    """Coordinator ruling on decision 0007 item 4: a blocked module anywhere up the chain."""
    store = public_store_after_cp0(tmp_path)
    for module_id in ("CP-1", "CP-1A", "CP-2"):
        assert settle_clean(store, module_id).status == "accepted"
    block_module(store, "CP-4")
    cp3 = settle_clean(store, "CP-3")
    cp5 = settle_clean(store, "CP-5")
    cp6 = settle_clean(store, "CP-6")
    assert bound(cp3, "CP-4").status == "blocked"
    assert bound(cp6, "CP-5").status == "restricted"
    assert not [item for item in cp6.inputs if item.status == "blocked"]  # indirect only
    assert (cp3.status, cp5.status, cp6.status) == ("restricted", "restricted", "restricted")
    assert cp6.limitations == ()
    assert any("Upstream CP-4 blocked" in text for text in cp6.inherited_limitations)


def test_blocked_ancestor_marker_cannot_be_spoofed_by_limitation_text(tmp_path: Path) -> None:
    store = public_store_after_cp0(tmp_path)
    assert settle_clean(store, "CP-1", "Upstream CP-4 blocked: plain text").status == "restricted"
    assert settle_clean(store, "CP-1A").status == "accepted"
    cp2 = settle_clean(store, "CP-2")
    assert cp2.status == "accepted"
    assert "Upstream CP-4 blocked: plain text" in cp2.inherited_limitations


def test_blocked_ancestors_terminates_on_diamond_and_cycle(tmp_path: Path) -> None:
    """A corrupted store with an input cycle must not hang; a diamond is walked once."""
    import signal

    from deploy_vii.execution import blocked_ancestors

    store = public_store_after_cp0(tmp_path)
    run = store.read().pack.run

    def head(module_id: str, *upstream: Input) -> Module:
        return Module(
            run_id=run.run_id,
            issuer_id=run.issuer_id,
            as_of=run.as_of,
            module_id=module_id,
            status="accepted",
            inputs=upstream,
        )

    def link(module_id: str, status: Literal["accepted", "blocked"] = "accepted") -> Input:
        return Input(input_id=module_id, sha256="0" * 64, status=status)

    # CP-1 and CP-1A reference each other (a cycle); CP-2 -> {CP-1, CP-1A} -> CP-4 is a diamond.
    heads = (
        head("CP-1", link("CP-1A"), link("CP-4", "blocked")),
        head("CP-1A", link("CP-1"), link("CP-4", "blocked")),
        head("CP-2", link("CP-1"), link("CP-1A")),
    )
    snapshot = store.read().model_copy(update={"heads": heads})
    clean = store.read().model_copy(
        update={"heads": (head("CP-1", link("CP-1A")), head("CP-1A", link("CP-1")))}
    )

    def expired(*_: object) -> None:
        raise TimeoutError("blocked_ancestors did not terminate")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(5)
    try:
        assert blocked_ancestors(snapshot, (link("CP-2"),)) == {"CP-4"}
        assert blocked_ancestors(snapshot, (link("CP-1"),)) == {"CP-4"}
        assert blocked_ancestors(clean, (link("CP-1"),)) == set()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def test_consumer_over_blocked_producer_is_staled_when_producer_changes(tmp_path: Path) -> None:
    from deploy_vii.execution import invalidate

    store = fixture_store(tmp_path)
    settle_through(store, "CP-1", "CP-1A", "CP-2")
    blocked = block_module(store, "CP-4")
    assert settle_module(store, "CP-3").status == "restricted"

    # A change to the blocked producer stales its restricted consumer, not the producer itself.
    changed = {item.module_id: item for item in invalidate(store.read().heads, "CP-4")}
    assert changed["CP-3"].status == "stale"
    assert "Input changed: CP-4; rerun required" in changed["CP-3"].limitations
    assert changed["CP-4"] == blocked
    assert changed["CP-2"].status == "restricted"  # not downstream of CP-4

    # Through the journal: replacing the pack stales the blocked producer and its consumer.
    pack = store.read().pack
    source = pack.sources[0].model_copy(update={"limitation": "New fidelity restriction"})
    store.replace_pack(pack.model_copy(update={"sources": (source,)}))
    heads = {item.module_id: item for item in store.read().heads}
    assert heads["CP-3"].status == heads["CP-4"].status == "stale"
    with pytest.raises(ValueError, match="upstream"):
        current_inputs(store.read(), "CP-3")


def test_omitted_input_status_is_rejected_for_restricted_producer(tmp_path: Path) -> None:
    store = fixture_store(tmp_path)
    accept_cp0(store)  # CP-0 settles restricted (synthetic run)
    ticket = store.begin("CP-1")
    candidate = candidate_for(store, "CP-1")
    assert bound(candidate, "CP-0").status == "restricted"
    assert candidate_issues(store.read(), ticket, candidate) == ()
    raw = json.loads(candidate.model_dump_json())
    for item in raw["inputs"]:
        item.pop("status", None)  # omission defaults to accepted
    omitted = Module.model_validate_json(json.dumps(raw))
    assert bound(omitted, "CP-0").status == "accepted"
    assert candidate_issues(store.read(), ticket, omitted) == (
        "Candidate does not bind the exact current upstream inputs",
    )
