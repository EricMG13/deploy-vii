import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from deploy_vii.contracts import Claim, Input, Module
from deploy_vii.execution import Execution, current_inputs
from deploy_vii.readiness import build_readiness
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
    assert set(store.read().heads[0].limitations) <= set(result.result.limitations)
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
