"""DC-8 backup cohort: credit detection, no silent substitution, the proxy cohort never pools.

Offline only: fake transports, fixture keys, and a socket guard.
"""

import json
import socket
from decimal import Decimal
from pathlib import Path

import pytest

from deploy_vii.live import cli
from deploy_vii.live.client import ChatClient, Response, TransportError
from deploy_vii.live.cohort import (
    CreditExhausted,
    CreditState,
    ProxyResult,
    accept_proxy_payload,
    credit_state,
    native_luna_available,
    native_luna_check,
)
from deploy_vii.live.credential import CredentialError
from deploy_vii.live.ledger import CapExceeded
from deploy_vii.live.retention import RetentionError
from deploy_vii.live.runner import COHORT, DispatchResult, StepSpec, dispatch
from tests.product.live_support import FAKE_KEY, SECOND_FAKE_KEY, FakeTransport, make_rtf_key, ok
from tests.product.test_live_runner import (
    BYTES_PER_TOKEN,
    CP0,
    LUNA,
    SEED_FOR,
    Rig,
    attempt_dir,
    cp1_rig,
    load,
    make_rig,
    reply,
)

NOW = "2026-10-21T10:00:00Z"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted in an offline cohort test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def key_reply(data: object, status: int = 200) -> Response:
    return Response(status, json.dumps({"data": data}).encode())


def keyed(rig: Rig, *replies: Response | BaseException) -> tuple[ChatClient, FakeTransport]:
    transport = FakeTransport(*replies)
    return ChatClient(transport, key_path=rig.key_path, key_index=1), transport


def proxy(rig: Rig, payload: str | None = None, label: str = "claude-agent") -> ProxyResult:
    return accept_proxy_payload(
        CP0,
        rig.submission if payload is None else payload,
        label,
        store=rig.store,
        ticket_id=rig.ticket_id,
        ledger=rig.ledger,
        writer=rig.writer,
        batch_id=rig.pool.batch_id,
        clock=lambda: NOW,
    )


@pytest.mark.parametrize(
    "data, exhausted, remaining, usage",
    [
        ({"limit": 10, "limit_remaining": 0, "usage": 10}, True, "0", "10"),
        ({"limit": 10, "limit_remaining": -0.25, "usage": 10.25}, True, "-0.25", "10.25"),
        ({"limit": 10, "limit_remaining": 0.0, "usage": 10}, True, "0.0", "10"),
        ({"limit": 10, "limit_remaining": 3.5, "usage": 6.5}, False, "3.5", "6.5"),
    ],
)
def test_exhausted_credit_is_detected_and_recorded(
    tmp_path: Path, data: dict[str, object], exhausted: bool, remaining: str, usage: str
) -> None:
    rig = make_rig(tmp_path)
    client, transport = keyed(rig, key_reply(data))
    state = credit_state(client, clock=lambda: NOW)
    assert state.exhausted is exhausted and state.source == "key-endpoint"
    assert state.limit_remaining == Decimal(remaining) and state.usage == Decimal(usage)
    record = state.to_record()
    assert record["checked_at"] == NOW and record["exhausted"] is exhausted
    assert record["limit_remaining"] == remaining
    request = transport.requests[0]
    assert request.method == "GET" and request.url.endswith("/api/v1/key") and request.body is None
    assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in repr(state) + json.dumps(record)


@pytest.mark.parametrize(
    "data, field",
    [
        ({"limit": None, "limit_remaining": None, "usage": 1.5}, "limit_remaining"),
        ({"usage": 1.5}, "limit_remaining"),
        ({"limit_remaining": 4, "usage": None}, "usage"),
        ({"limit_remaining": "4", "usage": 2}, "limit_remaining"),
    ],
)
def test_unknown_credit_fields_are_null_with_a_reason_not_exhausted(
    tmp_path: Path, data: dict[str, object], field: str
) -> None:
    rig = make_rig(tmp_path)
    client, _ = keyed(rig, key_reply(data))
    state = credit_state(client, clock=lambda: NOW)
    record = state.to_record()
    assert record[field] is None and record[f"{field}_reason"]
    if field == "limit_remaining":  # unknown credit is not declared exhausted
        assert state.exhausted is None
    else:
        assert state.exhausted is False


def test_key_endpoint_402_and_other_failures_are_recorded(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    paid, _ = keyed(rig, Response(402, b'{"error":{"message":"out of credits","code":402}}'))
    assert credit_state(paid, clock=lambda: NOW).exhausted is True
    denied, _ = keyed(rig, Response(401, b'{"error":{"message":"bad key"}}'))
    unknown = credit_state(denied, clock=lambda: NOW)
    assert unknown.exhausted is None and unknown.detail == "HTTP 401"
    junk, _ = keyed(rig, Response(200, b"not json"))
    garbled = credit_state(junk, clock=lambda: NOW)
    assert garbled.exhausted is None and garbled.to_record()["detail"]


def test_credit_probe_with_two_key_tokens_uses_the_first_and_records_the_count(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    two = make_rtf_key(tmp_path / "keys", f"{SECOND_FAKE_KEY}\n{FAKE_KEY}", name="two.rtf")
    transport = FakeTransport(key_reply({"limit_remaining": 3, "usage": 1}))
    state = credit_state(ChatClient(transport, key_path=two, key_index=1), clock=lambda: NOW)
    assert transport.requests[0].headers["Authorization"] == f"Bearer {SECOND_FAKE_KEY}"
    record = state.to_record()
    assert record["key_file"] == {"key_tokens_found": 2, "key_token_used": 1}
    assert "TESTONLY" not in repr(state) + json.dumps(record)
    single, _ = keyed(rig, key_reply({"limit_remaining": 3, "usage": 1}))
    assert "key_file" not in credit_state(single, clock=lambda: NOW).to_record()


def test_credit_probe_uses_the_client_token_index_and_records_it(tmp_path: Path) -> None:
    two = make_rtf_key(tmp_path, f"{FAKE_KEY}\n{SECOND_FAKE_KEY}", name="two.rtf")
    transport = FakeTransport(key_reply({"limit_remaining": 3, "usage": 1}))
    state = credit_state(ChatClient(transport, key_path=two, key_index=2), clock=lambda: NOW)
    assert transport.requests[0].headers["Authorization"] == f"Bearer {SECOND_FAKE_KEY}"
    assert state.to_record()["key_file"] == {"key_tokens_found": 2, "key_token_used": 2}
    beyond = ChatClient(FakeTransport(), key_path=two, key_index=3)
    with pytest.raises(CredentialError, match="credential_token_index 3 but only 2") as raised:
        credit_state(beyond, clock=lambda: NOW)
    assert "sk-or-" not in str(raised.value)


def test_credit_probe_needs_a_keyed_client_and_never_leaks_the_key(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    with pytest.raises(CredentialError, match="no credential file"):
        credit_state(ChatClient(FakeTransport()), clock=lambda: NOW)
    header = f"{{'Authorization': 'Bearer {FAKE_KEY}'}}"
    client, _ = keyed(rig, RuntimeError(f"headers were {header}"))
    with pytest.raises(TransportError) as raised:
        credit_state(client, clock=lambda: NOW)
    assert FAKE_KEY not in str(raised.value) and "TESTONLY" not in str(raised.value)


def test_dispatch_402_raises_credit_exhausted_and_records_the_state(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    body = b'{"error":{"message":"no credit","code":402}}'
    transport = FakeTransport(Response(402, body))
    with pytest.raises(CreditExhausted) as raised:
        rig.run(ChatClient(transport))
    # The message names the ticket that stays pending for the coordinator's choice.
    assert raised.value.ticket_id == rig.ticket_id
    assert f"ticket {rig.ticket_id} stays pending" in str(raised.value)
    state = raised.value.state
    assert isinstance(state, CreditState)
    assert state.exhausted is True and state.source == "dispatch-402" and state.detail == "HTTP 402"
    assert len(transport.requests) == 1  # no second call, to any model
    manifests = list((rig.root / "artifacts").rglob("manifest.json"))
    assert len(manifests) == 1
    manifest = load(manifests[0])
    assert (
        manifest["status"] == "no-response" and manifest["classification"] == "insufficient_credit"
    )
    assert (
        manifest["credit"]["exhausted"] is True and manifest["credit"]["source"] == "dispatch-402"
    )
    assert manifest["poolable"] is False
    ledger = rig.ledger.state()
    assert ledger.spent == Decimal(0) and ledger.reserved == Decimal(0)
    # The ticket stays open for the coordinator's explicit choice; credit is not a model failure.
    assert [a.status for a in rig.store.read().attempts] == ["pending"]


def test_dispatch_402_on_the_last_try_does_not_consume_the_repair(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    for _ in range(3):
        with pytest.raises(CreditExhausted):
            rig.run(ChatClient(FakeTransport(Response(402, b'{"error":{"code":402}}'))))
    assert [a.status for a in rig.store.read().attempts] == ["pending"]
    done = proxy(rig)
    assert done.status == "accepted"


def test_no_silent_substitution(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    exhausted = CreditState(
        checked_at=NOW,
        source="key-endpoint",
        exhausted=True,
        limit_remaining=Decimal(0),
        usage=Decimal(5),
        reasons={},
        detail=None,
    )
    transport = FakeTransport(reply(rig))
    with pytest.raises(CreditExhausted):
        _dispatch_with(rig, ChatClient(transport), exhausted)
    assert transport.requests == []  # nothing sent, nothing substituted
    assert not list((rig.root / "artifacts").rglob("*")), "no attempt, proxy or otherwise"
    assert rig.ledger.state().attempts == ()
    assert rig.store.read().attempts[-1].steps == ()  # journal untouched
    # A credit state that is not exhausted does not block dispatch.
    live = CreditState(NOW, "key-endpoint", False, Decimal(3), Decimal(1), {}, None)
    result = _dispatch_with(rig, ChatClient(FakeTransport(reply(rig))), live)
    assert result.status == "accepted"


def _dispatch_with(rig: Rig, client: ChatClient, credit: CreditState) -> DispatchResult:
    return dispatch(
        CP0,
        store=rig.store,
        ticket_id=rig.ticket_id,
        ledger=rig.ledger,
        pool=rig.pool,
        seed=SEED_FOR[LUNA],
        client=client,
        writer=rig.writer,
        key_path=rig.key_path,
        key_index=1,
        bytes_per_token=BYTES_PER_TOKEN,
        effort="high",
        clock=lambda: NOW,
        credit=credit,
    )


def test_native_luna_check_records_path_absence_and_inability() -> None:
    found = native_luna_check(which=lambda name: "/opt/bin/codex" if name == "codex" else None)
    assert found.available is True and found.path == "/opt/bin/codex"
    assert "does not establish entitlement" in found.reason
    absent = native_luna_check(which=lambda name: None)
    assert absent.available is False and absent.path is None and "not on PATH" in absent.reason

    def broken(name: str) -> str | None:
        raise OSError("PATH unreadable")

    unknown = native_luna_check(which=broken)
    assert unknown.available is None and "PATH unreadable" in unknown.reason
    assert unknown.to_record()["available"] is None
    assert native_luna_available(which=lambda name: None) is False
    assert native_luna_available(which=broken) is None


def test_proxy_payload_goes_through_the_journal_validators_and_is_recorded(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    result = proxy(rig)
    assert result.status == "accepted" and result.cohort == "proxy:claude-agent"
    assert rig.store.read().attempts[0].status != "pending"  # the journal took the payload
    manifest = load(result.directory / "manifest.json")
    assert manifest["cohort"] == "proxy:claude-agent" and manifest["model"] == "proxy:claude-agent"
    assert manifest["poolable"] is False and manifest["qualification"] is False
    assert manifest["status"] == "accepted" and manifest["validator"]["issues"] == []
    assert manifest["backup"]["native_luna"]["available"] in (True, False, None)
    assert manifest["backup"]["caller_supplied_payload"] is True
    assert "explicit_coordinator_call" not in manifest["backup"]
    assert manifest["credit"] is None  # no credit state was supplied, none is invented
    assert manifest["draw"] is None and manifest["draw_reason"]
    metrics = load(result.directory / "metrics.json")
    assert metrics["provider"]["cost_usd"] is None and metrics["provider"]["cost_usd_reason"]
    assert (result.directory / "output.md").read_text() == rig.submission
    # Same layout as a live attempt, minus nothing: the seven artifacts exist.
    assert {p.name for p in result.directory.iterdir()} >= {
        "manifest.json",
        "request.json",
        "response.json",
        "output.md",
        "events.jsonl",
        "metrics.json",
        "checks",
        "render",
    }


def test_proxy_ledger_line_has_null_cost_reason_proxy_and_never_counts(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = proxy(rig)
    lines = [json.loads(line) for line in rig.ledger.path.read_text().splitlines()]
    settle = lines[-1]
    assert settle["event"] == "settle" and settle["actual_usd"] is None
    assert settle["reason"] == "proxy" and settle["charged_usd"] == "0"
    assert settle["attempt_id"] == result.attempt_id
    assert result.attempt_id.startswith("proxy-claude-agent-")
    state = rig.ledger.state()
    assert state.spent == Decimal(0) and state.reserved == Decimal(0)


def test_rejected_proxy_payload_is_retained_and_still_not_poolable(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = proxy(rig, payload="{}")
    assert result.status == "rejected" and result.issues
    manifest = load(result.directory / "manifest.json")
    assert manifest["status"] == "rejected" and manifest["poolable"] is False
    assert manifest["validator"]["issues"] == list(result.issues)


def test_proxy_refuses_bad_labels_wrong_steps_and_unknown_tickets(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    for label in ("", "a b", "../x", "x/y", "a:b", "-lead"):
        with pytest.raises(ValueError, match="agent label"):
            proxy(rig, label=label)
    with pytest.raises(ValueError, match="ticket belongs to CP-0"):
        accept_proxy_payload(
            StepSpec("source_context", "case-cp0", ("filing",)),
            "{}",
            "agent",
            store=rig.store,
            ticket_id=rig.ticket_id,
            ledger=rig.ledger,
            writer=rig.writer,
            batch_id="b",
        )
    with pytest.raises(ValueError, match="unknown ticket"):
        accept_proxy_payload(
            CP0,
            "{}",
            "agent",
            store=rig.store,
            ticket_id="nope",
            ledger=rig.ledger,
            writer=rig.writer,
            batch_id="b",
        )
    assert not list((rig.root / "artifacts").rglob("*"))


def test_proxy_evidence_never_holds_a_key_shaped_token(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = proxy(rig, payload=f"key is {FAKE_KEY}")
    for path in result.directory.rglob("*"):
        if path.is_file():
            assert FAKE_KEY.encode() not in path.read_bytes(), path


def test_proxy_cohort_never_pools(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    pooled = rig.run(ChatClient(FakeTransport(reply(rig))))
    assert load(attempt_dir(pooled) / "manifest.json")["cohort"] == COHORT
    other = make_rig(tmp_path / "other")
    done = proxy(other)
    cells = [cli.Cell("probe-00", "case-cp0", ("source_readiness",), 1)]
    batch = cli.Batch(
        rows=[
            cli.Row(
                "probe-00",
                "case-cp0",
                "source_readiness",
                LUNA,
                1,
                pooled.attempt_id,
                pooled.status,
                pooled.classification or "none",
                "0.00033",
                0,
            ),
            cli.proxy_row("probe-00", "case-cp0", "source_readiness", done),
        ]
    )
    text = cli.render_report("probe", "b1", 1, rig.pool, rig.ledger, cells, batch, "high")
    summary = [
        [c.strip() for c in line.strip("| ").split(" | ")]
        for line in text.split("## Cohorts", 1)[1].splitlines()
        if line.startswith("| ") and not line.startswith("| Cohort") and "---" not in line
    ]
    by_cohort = {row[0]: row for row in summary}
    assert set(by_cohort) == {COHORT, "proxy:claude-agent"}  # never merged
    # Columns: attempts, accepted, rejected, no response (task 7.0), pooled, qualification.
    assert by_cohort["proxy:claude-agent"][1:] == ["1", "1", "0", "0", "no", "false"]
    assert by_cohort[COHORT][1] == "1" and by_cohort[COHORT][5] == "yes"
    assert by_cohort[COHORT][6] != "true"
    # Proxy attempts are listed under their own cohort, never in the pool steps table.
    pool_section = text.split("## Steps", 1)[1].split("##", 1)[0]
    assert done.attempt_id not in pool_section and pooled.attempt_id in pool_section
    assert f"## Steps ({done.cohort})" in text and done.attempt_id in text
    assert not cli.summarize_cohorts(batch.rows)[1].pooled
    assert cli.summarize_cohorts(batch.rows)[1].qualification is False
    # Direct invariant: nothing but the pool cohort is ever marked as pooled.
    assert [s.cohort for s in cli.summarize_cohorts(batch.rows) if s.pooled] == [COHORT]


def test_unknown_cohorts_do_not_pool_either() -> None:
    rows = [
        cli.Row("c", "k", "s", "m", 1, "a1", "accepted", "ok", "0", 0, cohort="proxy:x"),
        cli.Row("c", "k", "s", "m", 1, "a2", "accepted", "ok", "0", 0, cohort="other"),
    ]
    assert {s.cohort: s.pooled for s in cli.summarize_cohorts(rows)} == {
        COHORT: True,
        "proxy:x": False,
        "other": False,
    }


def test_proxy_manifest_records_the_credit_state_it_was_given(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    state = CreditState(NOW, "dispatch-402", True, None, None, {}, "HTTP 402")
    done = accept_proxy_payload(
        CP0,
        rig.submission,
        "claude-agent",
        store=rig.store,
        ticket_id=rig.ticket_id,
        ledger=rig.ledger,
        writer=rig.writer,
        batch_id=rig.pool.batch_id,
        clock=lambda: NOW,
        credit=state,
    )
    assert load(done.directory / "manifest.json")["credit"] == state.to_record()


def test_failed_begin_leaves_no_dangling_zero_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path)

    def broken(*_args: object, **_kwargs: object) -> None:
        raise RetentionError("disk refused")

    monkeypatch.setattr(rig.writer, "begin", broken)
    with pytest.raises(RetentionError):
        proxy(rig)
    assert rig.ledger.state().attempts == ()


def test_proxy_after_a_cap_overrun_is_refused_by_the_zero_reservation(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    rig.ledger.reserve("earlier", Decimal("5.00"))
    rig.ledger.settle("earlier", Decimal("6.00"), "overran")
    with pytest.raises(CapExceeded):
        proxy(rig)
    # Only an incomplete attempt remains (request.json, no manifest), and no ledger line.
    assert not list((rig.root / "artifacts").rglob("manifest.json"))
    assert [a.attempt_id for a in rig.ledger.state().attempts] == ["earlier"]


def cp1_proxy(rig: Rig, step_id: str, payload: str) -> ProxyResult:
    sources = tuple(s.source_id for s in rig.store.pack().sources)
    return accept_proxy_payload(
        StepSpec(step_id, "case-cp1", sources),
        payload,
        "claude-agent",
        store=rig.store,
        ticket_id=rig.ticket_id,
        ledger=rig.ledger,
        writer=rig.writer,
        batch_id=rig.pool.batch_id,
        clock=lambda: NOW,
    )


def test_a_proxy_step_repair_is_linked_as_a_repair_not_a_retry(tmp_path: Path) -> None:
    """Task 7.0g fix 1: a proxy payload submitted again after the journal kept the step's first
    rejection pending is that step's repair try: its own `-repair-<n>` id, a null
    `retry_of_attempt_id`, `step_try` 2 and a link to the rejected try."""
    rig, extraction = cp1_rig(tmp_path)
    failed = cp1_proxy(rig, "financials", "not json")
    assert failed.status == "rejected" and failed.journal is not None
    assert failed.journal.status == "pending" and len(failed.journal.step_repairs) == 1
    first = load(failed.directory / "manifest.json")
    assert first["retries"] == {"step_try": 1}
    assert first["links"]["step_repair_of_attempt_id"] is None
    fixed = cp1_proxy(rig, "financials", extraction.model_dump_json())
    assert fixed.status == "accepted", fixed.issues
    assert fixed.attempt_id.startswith(f"proxy-claude-agent-{rig.ticket_id}-financials-repair-")
    manifest = load(fixed.directory / "manifest.json")
    assert manifest["retries"] == {"step_try": 2}
    assert manifest["links"] == {
        "retry_of_attempt_id": None,
        "step_repair_of_attempt_id": failed.attempt_id,
    }


def test_a_proxy_repair_of_a_pool_rejection_links_the_pool_try(tmp_path: Path) -> None:
    rig, extraction = cp1_rig(tmp_path)
    sources = tuple(s.source_id for s in rig.store.pack().sources)
    pooled = rig.run(
        ChatClient(FakeTransport(ok("not json", model=LUNA))),
        step=StepSpec("financials", "case-cp1", sources),
    )
    assert pooled.status == "rejected" and pooled.attempt_pending
    fixed = cp1_proxy(rig, "financials", extraction.model_dump_json())
    assert fixed.status == "accepted", fixed.issues
    manifest = load(fixed.directory / "manifest.json")
    assert manifest["links"]["step_repair_of_attempt_id"] == pooled.attempt_id
    assert manifest["links"]["retry_of_attempt_id"] is None


def test_a_proxy_payload_records_the_bindings_python_filled(tmp_path: Path) -> None:
    """Task 7.0i: the proxy cohort enters payloads the same way, so its events say what Python
    pre-filled (paths, count and the count per kind)."""
    rig, extraction = cp1_rig(tmp_path)
    document = json.loads(extraction.model_dump_json())
    del document["context_step_sha256"]
    document["binding"]["source_context_review_sha256"] = "0" * 64
    result = cp1_proxy(rig, "financials", json.dumps(document))
    assert result.status == "accepted", result.issues
    events = [
        json.loads(line) for line in (result.directory / "events.jsonl").read_text().splitlines()
    ]
    (filled,) = [e for e in events if e["event"] == "payload_prefilled"]
    assert filled["paths"] == ["context_step_sha256", "binding.source_context_review_sha256"]
    assert filled["count"] == 2
    assert filled["by_kind"] == {"context-step": 1, "source-context-review": 1}
    attempt = rig.store.read().attempts[-1]
    assert filled["retained_payload_sha256"] == attempt.steps[-1].payload_sha256
