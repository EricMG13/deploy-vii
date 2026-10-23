"""`deploy-vii live reconcile`: held charges replaced by the generation endpoint's cost."""

import argparse
import hashlib
import json
import os
import socket
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from deploy_vii.live import cli
from deploy_vii.live.client import (
    CHAT_URL,
    GENERATION_URL,
    KEY_URL,
    Request,
    Response,
    TransportError,
)
from deploy_vii.live.ledger import AttemptRecord, Ledger
from deploy_vii.live.reconcile import RetainedAttempt, generation_cost
from tests.product.live_support import FAKE_KEY, ok
from tests.product.test_live_cli_batches import DEEPSEEK, Rig, key_status, step_lines

FIXTURE = Path(__file__).parent / "fixtures" / "live" / "deepseek-504-in-200-1.json"
TIMEOUT_BODY = json.loads(FIXTURE.read_text(encoding="utf-8"))["body_text"]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted in an offline reconcile test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


class ProbeResponder:
    """Chat calls: DeepSeek times out inside a 200 (probe-2 body), others answer `content`.

    Generation lookups are answered from `generations` (id -> Response or exception). The
    account-usage checks report `usage` before the batch and, after it, `usage` plus the cost
    of every answered chat call plus `unexplained` (spend the batch's measured costs do not
    account for: by default some, so a 404 is not corroborated unless a test says so)."""

    def __init__(
        self,
        content: str,
        generations: dict[str, Response | Exception] | None = None,
        *,
        usage: str = "25.7172663",
        unexplained: str = "0.01",
    ) -> None:
        self.content = content
        self.generations = generations or {}
        self.requests: list[Request] = []
        self.ids: list[str] = []
        self.usage = Decimal(usage)
        self.unexplained = Decimal(unexplained)
        self.key_checks = 0

    def __call__(self, request: Request) -> Response:
        if request.url == KEY_URL:
            self.key_checks += 1
            usage = self.usage + (self.unexplained if self.key_checks > 1 else 0)
            return key_status(format(usage, "f"))
        self.requests.append(request)
        if request.url.startswith(GENERATION_URL):
            reply = self.generations[request.url.split("id=", 1)[1]]
            if isinstance(reply, Exception):
                raise reply
            return reply
        model = json.loads(request.body or b"{}")["model"]
        if model == DEEPSEEK:
            generation = f"gen-timeout-{len(self.ids) + 1}"
            self.ids.append(generation)
            body = TIMEOUT_BODY.replace(json.loads(TIMEOUT_BODY)["id"], generation)
            return Response(200, body.encode())
        self.usage += Decimal("0.00033")  # what `ok` reports as usage.cost
        return ok(self.content, model=model)


DOCUMENTED = json.loads(
    (Path(__file__).parent / "fixtures" / "live" / "generation-documented-example.json").read_text(
        encoding="utf-8"
    )
)
ABSENT = object()
FIRST_ID = "gen-timeout-1"  # the first DeepSeek generation id ProbeResponder hands out


def generation(
    total: object,
    *,
    usage: object = "same",
    generation_id: object = FIRST_ID,
    wrapped: bool = True,
) -> Response:
    """The documented example record with its id and cost fields set (ABSENT drops a field)."""
    record = dict(DOCUMENTED["body"]["data"])
    for key, value in (
        ("total_cost", total),
        ("usage", total if usage == "same" else usage),
        ("id", generation_id),
    ):
        if value is ABSENT:
            del record[key]
        else:
            record[key] = value
    return Response(200, json.dumps({"data": record} if wrapped else record).encode())


def test_the_documented_example_reads_as_its_total_cost() -> None:
    body = json.dumps(DOCUMENTED["body"]).encode()
    record = DOCUMENTED["body"]["data"]
    assert "cost" not in record and record["total_cost"] == record["usage"] == 0.0015
    cost, reason = generation_cost(Response(200, body), "gen-3bhGkxlo4XFrqiabUM7NDtwDzWwG")
    assert cost == Decimal("0.0015") and "total_cost" in reason
    assert generation_cost(Response(200, body), "gen-other") == (
        None,
        "generation id mismatch: requested gen-other, record gen-3bhGkxlo4XFrqiabUM7NDtwDzWwG",
    )


def reconcile_argv(rig: Rig, batch: str = "b1") -> list[str]:
    return [
        "reconcile",
        "--directory",
        str(rig.store.directory),
        "--settings",
        str(rig.settings),
        "--report-directory",
        str(rig.reports),
        "--batch-id",
        batch,
    ]


def run_probe(rig: Rig, responder: ProbeResponder) -> None:
    assert rig.run(rig.argv("probe"), responder) == 0
    assert len(responder.ids) == 1  # one DeepSeek cell in a one-draw probe


def ledger(rig: Rig, batch: str = "b1") -> Ledger:
    path = rig.root / "artifacts" / "model-tests" / ".ledgers" / f"{batch}.jsonl"
    return Ledger(path, Decimal("5.00"))


def deepseek_dir(rig: Rig) -> Path:
    return next((rig.root / "artifacts" / "model-tests" / "b1").glob("probe/deepseek__*/*"))


def load(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def test_the_batch_report_says_reservation_held_for_an_unreconciled_attempt(rig: Rig) -> None:
    run_probe(rig, ProbeResponder(rig.review))
    text = rig.report()
    (row,) = [r for r in step_lines(text, "probe-") if r[3] == DEEPSEEK]
    assert row[7] == "timeout" and row[8].startswith("reservation held")
    assert "reservation held: no measured cost" in text  # the footnote
    others = [r for r in step_lines(text, "probe-") if r[3] != DEEPSEEK]
    assert all(not r[8].startswith("reservation held") for r in others)


@pytest.mark.parametrize("cost", ["0.0123", "0.9"])  # below and above the reservation
def test_reconcile_replaces_the_hold_with_the_generation_cost(
    rig: Rig, cost: str, capsys: pytest.CaptureFixture[str]
) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    before = ledger(rig).state()
    (held,) = [a for a in before.attempts if a.actual_usd is None]
    responder.generations = {responder.ids[0]: generation(json.loads(cost))}
    sent = len(responder.requests)
    assert rig.run(reconcile_argv(rig), responder) == 0
    (lookup,) = responder.requests[sent:]
    assert lookup.url == f"{GENERATION_URL}?id={responder.ids[0]}" and lookup.method == "GET"
    assert lookup.headers["Authorization"] == f"Bearer {FAKE_KEY}"  # read for this call (DC-7)
    after = ledger(rig).state()
    record = {a.attempt_id: a for a in after.attempts}[held.attempt_id]
    assert record.charged_usd == Decimal(cost) and record.adjustment is not None
    assert record.adjustment.previous_charged_usd == held.charged_usd
    assert after.spent == before.spent - (held.charged_usd or 0) + Decimal(cost)
    assert after.overrun == max(Decimal(0), Decimal(cost) - held.reserved_usd)
    metrics = load(deepseek_dir(rig) / "metrics.json")["ledger"]
    assert metrics["cost_basis"] == "generation-endpoint" and metrics["unreconciled"] is False
    assert metrics["charged_usd"] == cost and metrics["attempt_cost_usd"] == cost
    assert metrics["reconciliation"]["status"] == "reconciled"
    assert metrics["reconciliation"]["previous"]["cost_basis"] == "unknown"
    assert metrics["reconciliation"]["generation_id_source"] == "manifest"
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    (row,) = [r for r in step_lines(report, "probe-") if r[3] == DEEPSEEK]
    assert row[8] == cost
    assert f"spent {format(after.spent, 'f')}" in report and "reservation held" not in report
    assert rig.report().count("reservation held") >= 1  # the original report is never rewritten
    out = capsys.readouterr().out
    assert "reconciled 1, unresolved 0" in out and "sk-or-" not in out + report


def test_a_second_reconcile_makes_no_call_and_writes_no_second_adjust(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    responder.generations = {responder.ids[0]: generation(0.01)}
    assert rig.run(reconcile_argv(rig), responder) == 0
    lines = ledger(rig).path.read_bytes()
    sent = len(responder.requests)
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert len(responder.requests) == sent and ledger(rig).path.read_bytes() == lines


@pytest.mark.parametrize(
    "reply, reason",
    [
        (Response(404, b'{"error":{"message":"Not found","code":404}}'), "HTTP 404"),
        (generation(None, usage=ABSENT), "no total_cost"),
        (generation(ABSENT, usage=ABSENT), "no total_cost"),
        (generation("0.01", usage=ABSENT), "no total_cost"),  # a string is not a number
        (generation(-1, usage=ABSENT), "no total_cost"),
        (generation(True, usage=ABSENT), "no total_cost"),
        (generation(0.01, usage=0.02), "usage 0.02 differs from total_cost 0.01"),
        (generation(0.01, usage=None), "usage None differs from total_cost 0.01"),
        (generation(0.01, generation_id="gen-elsewhere"), "generation id mismatch"),
        (generation(0.01, generation_id=ABSENT), "generation id mismatch"),
        (Response(200, b'{"data": {"id": "gen-timeout-1", "cost": 0.01}}'), "no total_cost"),
        (Response(200, b"   "), "not a JSON object"),
    ],
)
def test_a_lookup_without_a_cost_leaves_the_attempt_unreconciled_with_the_reason(
    rig: Rig, reply: Response, reason: str
) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    lines = ledger(rig).path.read_bytes()
    responder.generations = {responder.ids[0]: reply}
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines  # no adjust, the hold stands
    metrics = load(deepseek_dir(rig) / "metrics.json")["ledger"]
    assert metrics["unreconciled"] is True and metrics["cost_basis"] == "unknown"
    assert metrics["reconciliation"]["status"] == "unresolved"
    assert reason in metrics["reconciliation"]["reason"]
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    (row,) = [r for r in step_lines(report, "probe-") if r[3] == DEEPSEEK]
    assert row[8].startswith("reservation held") and reason in report


def test_an_unwrapped_generation_record_is_read_too(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    responder.generations = {responder.ids[0]: generation(0.02, wrapped=False)}
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert load(deepseek_dir(rig) / "metrics.json")["ledger"]["charged_usd"] == "0.02"


def test_a_probe2_manifest_without_the_id_is_reconciled_from_its_retained_body(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    manifest_path = deepseek_dir(rig) / "manifest.json"
    manifest = load(manifest_path)
    manifest["served"]["provider_request_id"] = None  # as probe-2 recorded it
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    responder.generations = {responder.ids[0]: generation(0.03)}
    assert rig.run(reconcile_argv(rig), responder) == 0
    metrics = load(deepseek_dir(rig) / "metrics.json")["ledger"]
    assert metrics["charged_usd"] == "0.03"
    assert metrics["reconciliation"]["generation_id_source"] == "response.json"


def test_an_interrupted_metrics_write_is_resynchronised_from_the_ledger(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    metrics_path = deepseek_dir(rig) / "metrics.json"
    before = metrics_path.read_text(encoding="utf-8")
    responder.generations = {responder.ids[0]: generation(0.04)}
    assert rig.run(reconcile_argv(rig), responder) == 0
    metrics_path.write_text(before, encoding="utf-8")  # as if the run died after the adjust
    lines, sent = ledger(rig).path.read_bytes(), len(responder.requests)
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert len(responder.requests) == sent and ledger(rig).path.read_bytes() == lines
    block = load(metrics_path)["ledger"]
    assert block["charged_usd"] == "0.04" and block["unreconciled"] is False
    assert "synchronised" in block["cost_reason"]


def test_metrics_that_disagree_with_the_ledger_are_reported_not_adjusted(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    glm = next((rig.root / "artifacts" / "model-tests" / "b1").glob("probe/z-ai__*/*"))
    metrics = load(glm / "metrics.json")
    metrics["ledger"]["unreconciled"] = True  # the ledger knows this cost
    (glm / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    responder.generations = {responder.ids[0]: generation(0.01)}
    assert rig.run(reconcile_argv(rig), responder) == 0
    reason = load(glm / "metrics.json")["ledger"]["reconciliation"]["reason"]
    assert "no unreconciled settlement" in reason
    adjusted = [a for a in ledger(rig).state().attempts if a.adjustment]
    assert len(adjusted) == 1  # only the DeepSeek hold


def test_a_recorded_id_that_is_not_a_generation_id_is_never_looked_up(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    manifest_path = deepseek_dir(rig) / "manifest.json"
    manifest = load(manifest_path)
    manifest["served"]["provider_request_id"] = "gen-1&id=gen-2"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sent = len(responder.requests)
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert len(responder.requests) == sent
    reason = load(deepseek_dir(rig) / "metrics.json")["ledger"]["reconciliation"]["reason"]
    assert "not a generation id" in reason


def test_totals_and_the_cumulative_ceiling_use_the_adjusted_figure(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    ledgers = rig.root / "artifacts" / "model-tests" / ".ledgers"
    held = cli.committed_elsewhere(ledgers)
    responder.generations = {responder.ids[0]: generation(0)}
    assert rig.run(reconcile_argv(rig), responder) == 0
    reservation = next(a for a in ledger(rig).state().attempts if a.adjustment).reserved_usd
    assert cli.committed_elsewhere(ledgers) == held - reservation


def test_a_transport_failure_stops_the_reconcile_after_writing_the_report(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    lines = ledger(rig).path.read_bytes()
    responder.generations = {responder.ids[0]: OSError(f"reset {FAKE_KEY}")}
    assert rig.run(reconcile_argv(rig), responder) == cli.EXIT_FAILED
    assert ledger(rig).path.read_bytes() == lines
    assert (rig.reports / "live-b1-reconciled.md").exists()
    assert "TESTONLY" not in capsys.readouterr().out


def test_reconcile_refuses_an_unknown_batch_before_any_call(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    assert rig.run(reconcile_argv(rig, batch="nothing"), responder) == cli.EXIT_FAILED
    assert responder.requests == []


def test_reconcile_takes_no_cap_and_no_key_option() -> None:
    parser = argparse.ArgumentParser()
    cli.configure(parser)
    for extra in (["--cap", "1"], ["--key", "x"]):
        with pytest.raises(SystemExit):
            parser.parse_args(["reconcile", "--directory", "d", "--batch-id", "b", *extra])
    with pytest.raises(SystemExit):
        parser.parse_args(["reconcile", "--directory", "d"])  # the batch is required


def test_reconcile_never_calls_chat(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    responder.generations = {responder.ids[0]: generation(0.01)}
    sent = len(responder.requests)
    rig.run(reconcile_argv(rig), responder)
    assert CHAT_URL not in {r.url for r in responder.requests[sent:]}


# --- decision 0008: a generation 404 corroborated by the batch's account-usage delta -------

NOT_FOUND = Response(404, b'{"error":{"message":"Not found","code":404}}')


@pytest.mark.parametrize("unexplained", ["0", "0.000001", "-0.000001", "0.0000004"])
def test_a_404_whose_usage_delta_equals_the_other_costs_is_adjusted_to_zero(
    rig: Rig, unexplained: str
) -> None:
    """Probe-2: usage moved 25.7172663 -> 25.724167155, the other attempts' provider-reported
    costs, so the 404'd DeepSeek timeouts cost nothing (within US$0.000001)."""
    responder = ProbeResponder(rig.review, unexplained=unexplained)
    run_probe(rig, responder)
    before = ledger(rig).state()
    (held,) = [a for a in before.attempts if a.actual_usd is None]
    measured = sum(
        (a.charged_usd or Decimal(0) for a in before.attempts if a.actual_usd is not None),
        Decimal(0),
    )
    assert measured > 0 and len([a for a in before.attempts if a.actual_usd is not None]) > 1
    responder.generations = {responder.ids[0]: NOT_FOUND}
    assert rig.run(reconcile_argv(rig), responder) == 0
    after = ledger(rig).state()
    record = {a.attempt_id: a for a in after.attempts}[held.attempt_id]
    assert record.charged_usd == 0 and record.adjustment is not None
    assert record.adjustment.source == "generation-404+usage-delta"
    evidence = record.adjustment.evidence
    assert evidence is not None and evidence["generation_status"] == 404
    assert evidence["usage_before_usd"] == "25.7172663"
    assert Decimal(evidence["usage_delta_usd"]) == measured + Decimal(unexplained)
    assert Decimal(evidence["other_attempts_measured_usd"]) == measured
    assert evidence["tolerance_usd"] == "0.000001"
    assert evidence["usage_recorded_by"] == ["deploy-vii live probe"] * 2
    # The fresh reconcile-time reading equals the after-check: nothing was billed late.
    assert evidence["usage_now_usd"] == evidence["usage_after_usd"]
    assert evidence["usage_now_checked_at"]
    assert after.spent == before.spent - (held.charged_usd or 0)
    line = json.loads(ledger(rig).path.read_text(encoding="utf-8").splitlines()[-1])
    assert line["event"] == "adjust" and line["evidence"] == evidence
    block = load(deepseek_dir(rig) / "metrics.json")["ledger"]
    assert block["cost_basis"] == "generation-404+usage-delta" and block["unreconciled"] is False
    assert block["reconciliation"]["evidence"] == evidence


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"unexplained": "0.0000011"}, "not corroborated"),
        ({"unexplained": "0.279468"}, "not corroborated"),
        ({"unexplained": "-0.01"}, "not corroborated"),
    ],
)
def test_a_404_without_a_matching_usage_delta_stays_unresolved(
    rig: Rig, change: dict[str, str], reason: str
) -> None:
    responder = ProbeResponder(rig.review, **change)
    run_probe(rig, responder)
    lines = ledger(rig).path.read_bytes()
    responder.generations = {responder.ids[0]: NOT_FOUND}
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines  # no adjust, the hold stands
    block = load(deepseek_dir(rig) / "metrics.json")["ledger"]
    assert block["unreconciled"] is True
    assert "HTTP 404" in block["reconciliation"]["reason"]
    assert reason in block["reconciliation"]["reason"]


def test_a_404_billed_after_the_after_check_stays_held(rig: Rig) -> None:
    """The delta matched at the after-check, but the provider billed the 404'd call later: the
    fresh reading at reconcile time is above the recorded after-figure, so no zero is written."""
    responder = ProbeResponder(rig.review, unexplained="0")
    run_probe(rig, responder)
    lines = ledger(rig).path.read_bytes()
    responder.generations = {responder.ids[0]: NOT_FOUND}
    responder.usage += Decimal("0.004")
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines  # no adjust, the hold stands
    block = load(deepseek_dir(rig) / "metrics.json")["ledger"]
    assert block["unreconciled"] is True
    reason = block["reconciliation"]["reason"]
    assert "HTTP 404" in reason and "usage moved since the after-check" in reason
    assert "a later reconcile may retry" in reason


@pytest.mark.parametrize(
    "edit, reason",
    [
        ("delete-before", "no account usage was recorded before the batch"),
        ("delete-after", "no account usage was recorded after the batch"),
        ("null-usage", "is not a recorded number"),
        ("other-token", "different key tokens"),
    ],
)
def test_a_404_without_a_usable_usage_record_stays_unresolved(
    rig: Rig, edit: str, reason: str
) -> None:
    responder = ProbeResponder(rig.review, unexplained="0")
    run_probe(rig, responder)
    batch = rig.root / "artifacts" / "model-tests" / "b1"
    before, after = batch / "account-usage-before.json", batch / "account-usage-after.json"
    if edit == "delete-before":
        before.unlink()
    elif edit == "delete-after":
        after.unlink()
    else:
        record = load(after)
        if edit == "null-usage":
            record["credit"]["usage"] = None
        else:
            record["credit"]["key_file"] = {"key_tokens_found": 2, "key_token_used": 2}
        after.write_text(json.dumps(record), encoding="utf-8")
    lines = ledger(rig).path.read_bytes()
    responder.generations = {responder.ids[0]: NOT_FOUND}
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines
    block = load(deepseek_dir(rig) / "metrics.json")["ledger"]
    assert reason in block["reconciliation"]["reason"]


def test_only_a_404_is_corroborated_by_the_usage_delta(rig: Rig) -> None:
    responder = ProbeResponder(rig.review, unexplained="0")
    run_probe(rig, responder)
    lines = ledger(rig).path.read_bytes()
    responder.generations = {responder.ids[0]: Response(500, b"{}")}
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines
    reason = load(deepseek_dir(rig) / "metrics.json")["ledger"]["reconciliation"]["reason"]
    assert reason == "HTTP 500 from the generation endpoint"


# --- 7.0: a deadline hold without a generation id, attributed by the account-usage delta ----


class DeadlineResponder(ProbeResponder):
    """The first `deadlines` DeepSeek calls pass their wall-clock deadline (the TimeoutError
    `urllib_transport` raises: no body, so no generation id) yet cost the account `held_cost`;
    later DeepSeek calls time out inside a 200 with a generation id, as in ProbeResponder."""

    def __init__(
        self,
        content: str,
        *,
        held_cost: str = "0.0123",
        deadlines: int = 1,
        unexplained: str = "0",
    ) -> None:
        super().__init__(content, unexplained=unexplained)
        self.held_cost = Decimal(held_cost)
        self.deadlines = deadlines

    def __call__(self, request: Request) -> Response:
        if request.url == CHAT_URL and json.loads(request.body or b"{}")["model"] == DEEPSEEK:
            if self.deadlines > 0:
                self.deadlines -= 1
                self.requests.append(request)
                self.usage += self.held_cost
                raise TimeoutError(f"wall-clock deadline of {request.timeout_s} s exceeded")
        return super().__call__(request)


def deadline_hold(rig: Rig) -> AttemptRecord:
    (held,) = [a for a in ledger(rig).state().attempts if a.actual_usd is None]
    manifest = load(deepseek_dir(rig) / "manifest.json")
    assert manifest["served"]["provider_request_id"] is None  # nothing to look up
    assert manifest["classification"] == "timeout"
    return held


@pytest.mark.parametrize(
    ("held_cost", "unexplained", "expected"),
    [
        ("0.0123", "0", "0.0123"),  # the deadline call still cost the account
        ("0", "0", "0"),  # it cost nothing
        ("0", "-0.0000004", "0"),  # usage read a hair low: within the tolerance, never negative
    ],
)
def test_a_lone_deadline_hold_takes_the_account_usage_residual(
    rig: Rig, held_cost: str, unexplained: str, expected: str
) -> None:
    responder = DeadlineResponder(rig.review, held_cost=held_cost, unexplained=unexplained)
    assert rig.run(rig.argv("probe"), responder) == 0
    held = deadline_hold(rig)
    before = ledger(rig).state()
    sent = len(responder.requests)
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert len(responder.requests) == sent  # no generation lookup: there is no id
    after = ledger(rig).state()
    record = {a.attempt_id: a for a in after.attempts}[held.attempt_id]
    assert record.charged_usd == record.actual_usd == Decimal(expected)
    adjustment = record.adjustment
    assert adjustment is not None and adjustment.source == "account-usage-delta"
    assert adjustment.generation_id is None
    evidence = adjustment.evidence
    others = [a for a in before.attempts if a.attempt_id != held.attempt_id]
    measured = sum((a.charged_usd or Decimal(0) for a in others), Decimal(0))
    assert evidence is not None
    assert evidence["held_attempts"] == [held.attempt_id]
    assert evidence["other_attempts"] == sorted(a.attempt_id for a in others)
    assert Decimal(evidence["other_attempts_measured_usd"]) == measured
    assert Decimal(evidence["usage_delta_usd"]) == measured + Decimal(held_cost) + Decimal(
        unexplained
    )
    assert Decimal(evidence["reserved_usd"]) == held.reserved_usd
    assert evidence["tolerance_usd"] == "0.000001"
    # The fresh reconcile-time reading equals the after-check: the call was not billed late.
    assert evidence["usage_now_usd"] == evidence["usage_after_usd"]
    assert evidence["usage_now_checked_at"]
    assert after.spent == before.spent - held.reserved_usd + Decimal(expected)
    block = load(deepseek_dir(rig) / "metrics.json")["ledger"]
    assert block["cost_basis"] == "account-usage-delta" and block["unreconciled"] is False
    assert block["reconciliation"]["evidence"] == evidence
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    assert "Looked up this run: 1; reconciled 1, unresolved 0" in report


def _two_deadlines(rig: Rig) -> DeadlineResponder:
    responder = DeadlineResponder(rig.review, deadlines=2)
    assert rig.run(rig.argv("probe", "--draws-per-model", "2"), responder) == 0
    return responder


def _estimate_elsewhere(rig: Rig) -> DeadlineResponder:
    responder = DeadlineResponder(rig.review)
    assert rig.run(rig.argv("probe"), responder) == 0
    glm = next((rig.root / "artifacts" / "model-tests" / "b1").glob("probe/z-ai__*/*"))
    metrics = load(glm / "metrics.json")
    metrics["ledger"]["cost_basis"] = "estimate-from-tokens"
    (glm / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return responder


def _plain(rig: Rig, held_cost: str = "0.0123", unexplained: str = "0") -> DeadlineResponder:
    responder = DeadlineResponder(rig.review, held_cost=held_cost, unexplained=unexplained)
    assert rig.run(rig.argv("probe"), responder) == 0
    return responder


def _billed_after_the_check(rig: Rig) -> DeadlineResponder:
    """The provider bills the given-up call after the after-batch check: the fresh reading at
    reconcile time is above the recorded after-figure, so the delta would omit that charge."""
    responder = _plain(rig)
    responder.usage += Decimal("0.004")
    return responder


def _no_usage_after(rig: Rig) -> DeadlineResponder:
    responder = _plain(rig)
    (rig.root / "artifacts" / "model-tests" / "b1" / "account-usage-after.json").unlink()
    return responder


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (_two_deadlines, "2 held attempts in the batch"),
        (lambda rig: _plain(rig, held_cost="9"), "above the attempt's reservation"),
        (
            lambda rig: _plain(rig, held_cost="0", unexplained="-0.0000011"),
            "less than the other attempts",
        ),
        (_estimate_elsewhere, "is not a measured cost"),
        (_no_usage_after, "no account usage was recorded after the batch"),
        (_billed_after_the_check, "usage moved since the after-check"),
    ],
)
def test_a_deadline_hold_the_usage_delta_cannot_attribute_stays_held_with_the_reason(
    rig: Rig, setup: Callable[[Rig], DeadlineResponder], reason: str
) -> None:
    responder = setup(rig)
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines  # no adjust: the hold stands
    held = [a for a in ledger(rig).state().attempts if a.actual_usd is None]
    assert held
    for directory in (rig.root / "artifacts" / "model-tests" / "b1").glob("probe/deepseek__*/*"):
        block = load(directory / "metrics.json")["ledger"]
        assert block["unreconciled"] is True
        assert (
            "no provider_request_id recorded; nothing to look up"
            in block["reconciliation"]["reason"]
        )
        assert reason in block["reconciliation"]["reason"]


def test_a_deadline_hold_is_attributed_after_the_other_holds_are_looked_up(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execution order: held attempts with a generation id are reconciled first, so a lone
    hold without one is attributed in the same run whatever order the directories sort in."""
    responder = DeadlineResponder(rig.review, unexplained="0.002")  # the 200-error's real cost
    assert rig.run(rig.argv("probe", "--draws-per-model", "2"), responder) == 0
    (looked_up,) = responder.ids
    responder.generations = {looked_up: generation(0.002, generation_id=looked_up)}
    found = cli.candidates

    def no_id_first(root: Path, batch: str) -> list[RetainedAttempt]:
        def has_id(item: RetainedAttempt) -> bool:
            return item.manifest["served"]["provider_request_id"] is not None

        return sorted(found(root, batch), key=has_id)

    monkeypatch.setattr(cli, "candidates", no_id_first)
    assert rig.run(reconcile_argv(rig), responder) == 0
    state = ledger(rig).state()
    sources = sorted(a.adjustment.source for a in state.attempts if a.adjustment is not None)
    assert sources == ["account-usage-delta", "generation-endpoint"]
    usage = next(a for a in state.attempts if a.adjustment and a.adjustment.generation_id is None)
    assert usage.charged_usd == Decimal("0.0123")
    assert all(a.actual_usd is not None for a in state.attempts)


class KeyDownResponder(DeadlineResponder):
    """The reconcile-time account-usage reading (the third `GET /api/v1/key`, after the
    batch's before and after checks) fails at the connection level."""

    def __call__(self, request: Request) -> Response:
        if request.url == KEY_URL and self.key_checks >= 2:
            raise TransportError(f"connection reset {FAKE_KEY}")
        return super().__call__(request)


def test_a_connection_failure_in_the_fresh_usage_reading_stops_the_run_and_keeps_adjustments(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    """The lookup of the attempt with a generation id settles first and is written; the
    deadline hold then needs the fresh usage reading, which fails: exit 2 after the report is
    written, the hold stands and the earlier adjustment stays in the ledger."""
    responder = KeyDownResponder(rig.review, unexplained="0.002")
    assert rig.run(rig.argv("probe", "--draws-per-model", "2"), responder) == 0
    (looked_up,) = responder.ids
    responder.generations = {looked_up: generation(0.002, generation_id=looked_up)}
    before = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == cli.EXIT_FAILED
    state = ledger(rig).state()
    adjusted = [a for a in state.attempts if a.adjustment is not None]
    assert [a.adjustment.source for a in adjusted if a.adjustment] == ["generation-endpoint"]
    assert ledger(rig).path.read_bytes().startswith(before)  # appended to, never rewritten
    assert len(ledger(rig).path.read_bytes()) > len(before)
    assert [a for a in state.attempts if a.actual_usd is None]  # the deadline hold stands
    assert (rig.reports / "live-b1-reconciled.md").exists()
    out = capsys.readouterr().out
    assert "live reconcile failed: TransportError:" in out
    assert "connection reset [REDACTED]" in out
    assert "TESTONLY" not in out


# --- 7.11: an interrupted attempt (request.json only, reservation open) ------------------------

INTERRUPTED_RESERVE = Decimal("0.5")


class AllAnswered(ProbeResponder):
    """Every chat call answers with a measured usage cost; `unexplained` stands in for what the
    interrupted call cost the account (in the after-check and every later key reading)."""

    def __call__(self, request: Request) -> Response:
        if request.url == CHAT_URL:
            self.requests.append(request)
            self.usage += Decimal("0.00033")  # what `ok` reports as usage.cost
            return ok(self.content, model=json.loads(request.body or b"{}")["model"])
        return super().__call__(request)


def interrupted(rig: Rig, *, unexplained: str = "0.0123") -> tuple[AllAnswered, Path]:
    """A probe batch whose every attempt is measured, plus the e1-cp1-12 shape (synthetic): a
    further try of one cell's step reserved in the ledger whose directory holds request.json
    only, because the process was killed before the reply."""
    responder = AllAnswered(rig.review, unexplained=unexplained)
    assert rig.run(rig.argv("probe"), responder) == 0
    sealed = deepseek_dir(rig)
    assert sealed.name.endswith("-1")
    directory = sealed.with_name(sealed.name[: -len("-1")] + "-2")
    directory.mkdir()
    request = directory / "request.json"
    request.write_bytes((sealed / "request.json").read_bytes())
    # Written well before its call's longest possible life (twice the deadline) ran out.
    timeout_s = load(request)["non_secret_parameters"]["timeout_s"]
    written = time.time() - 2 * timeout_s - 60
    os.utime(request, (written, written))
    ledger(rig).reserve(directory.name, INTERRUPTED_RESERVE)
    return responder, directory


def record_of(rig: Rig, attempt_id: str) -> AttemptRecord:
    return {a.attempt_id: a for a in ledger(rig).state().attempts}[attempt_id]


def events_of(rig: Rig, attempt_id: str) -> list[str]:
    lines = ledger(rig).path.read_text(encoding="utf-8").splitlines()
    return [e["event"] for e in map(json.loads, lines) if e.get("attempt_id") == attempt_id]


def test_an_interrupted_attempt_with_a_measurable_window_is_settled_by_the_usage_delta(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    responder, directory = interrupted(rig)
    before = ledger(rig).state()
    sent = len(responder.requests)
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert len(responder.requests) == sent  # nothing to look up: there is no generation id
    record = record_of(rig, directory.name)
    assert events_of(rig, directory.name) == ["reserve", "settle", "adjust"]
    assert record.status == "settled" and record.charged_usd == Decimal("0.0123")
    adjustment = record.adjustment
    assert adjustment is not None and adjustment.source == "account-usage-delta"
    assert adjustment.generation_id is None and adjustment.previous_charged_usd == Decimal("0.5")
    evidence = adjustment.evidence
    assert evidence is not None and evidence["held_attempts"] == [directory.name]
    others = [a for a in before.attempts if a.attempt_id != directory.name]
    assert Decimal(evidence["other_attempts_measured_usd"]) == sum(
        (a.charged_usd or Decimal(0) for a in others), Decimal(0)
    )
    assert evidence["usage_now_usd"] == evidence["usage_after_usd"]
    after = ledger(rig).state()
    assert after.reserved == before.reserved - INTERRUPTED_RESERVE
    assert after.spent == before.spent + Decimal("0.0123")
    # The manifest it can truthfully write: no served, effort or usage block.
    manifest = load(directory / "manifest.json")
    request = load(directory / "request.json")
    assert manifest["status"] == "no-response" and manifest["classification"] == "interrupted"
    assert manifest["reason"] == "process ended before the reply; no generation id"
    assert manifest["hashes"] == {
        "request_sha256": hashlib.sha256(
            json.dumps(request["body"], sort_keys=True).encode()
        ).hexdigest()
    }
    # The runner hashed the same request body the same way (its sealed first try).
    sealed = load(directory.with_name(directory.name[: -len("-2")] + "-1") / "manifest.json")
    assert manifest["hashes"]["request_sha256"] == sealed["hashes"]["request_sha256"]
    assert manifest["attempt_id"] == directory.name and manifest["model"] == DEEPSEEK
    assert manifest["cohort"] == "openrouter-pool" and manifest["experiment_id"] == "b1"
    assert (manifest["ticket_id"], manifest["step_id"]) == (sealed["ticket_id"], sealed["step_id"])
    assert manifest["draw"] == request["selection"]["draw"]
    assert not {"served", "effort", "usage", "credit", "validator"} & set(manifest)
    assert sorted(p.name for p in directory.iterdir()) == ["manifest.json", "request.json"]
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    (row,) = [r for r in step_lines(report, "probe-") if r[5] == directory.name]
    assert row[6:8] == ["no-response", "interrupted"] and Decimal(row[8]) == Decimal("0.0123")
    (outcome,) = [line for line in report.splitlines() if line.startswith(f"| {directory.name}")]
    assert "| reconciled |" in outcome and "settled by account-usage-delta" in outcome
    assert "Looked up this run: 1; reconciled 1, unresolved 0" in report
    assert "reconciled 1, unresolved 0" in capsys.readouterr().out
    # A second run finds nothing to do: no call, no line, no file rewritten.
    lines, text = ledger(rig).path.read_bytes(), (directory / "manifest.json").read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines
    assert (directory / "manifest.json").read_bytes() == text


def test_an_interrupted_attempt_without_a_usage_window_stays_unresolved_and_open(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real e1-cp1-12 shape: the batch was killed, so no after-check was recorded; never a
    guessed zero, never a guessed charge."""
    responder, directory = interrupted(rig)
    (rig.root / "artifacts" / "model-tests" / "b1" / "account-usage-after.json").unlink()
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0  # unresolved keeps the exit code
    assert ledger(rig).path.read_bytes() == lines  # the reservation stays open
    record = record_of(rig, directory.name)
    assert record.status == "reserved" and record.charged_usd is None
    assert load(directory / "manifest.json")["classification"] == "interrupted"
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    (row,) = [r for r in step_lines(report, "probe-") if r[5] == directory.name]
    assert row[8] == "reserved 0.5 (open)"
    (outcome,) = [line for line in report.splitlines() if line.startswith(f"| {directory.name}")]
    assert "| unresolved |" in outcome and "reservation kept open" in outcome
    assert "no account usage was recorded after the batch" in outcome
    assert f"reserved {format(ledger(rig).state().reserved, 'f')}" in report
    assert "reconciled 0, unresolved 1" in capsys.readouterr().out
    # A later run retries from the manifest this path wrote; it is not rewritten.
    text = (directory / "manifest.json").read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert (directory / "manifest.json").read_bytes() == text
    assert ledger(rig).path.read_bytes() == lines


def test_a_settle_left_by_an_interrupted_reconcile_is_adjusted_once_and_never_settled_again(
    rig: Rig,
) -> None:
    """A reconcile killed between its settle and its adjust leaves a held charge; the next run
    adjusts it from the same window and writes no second settle (one settle per id)."""
    responder, directory = interrupted(rig)
    usage_after = rig.root / "artifacts" / "model-tests" / "b1" / "account-usage-after.json"
    kept = usage_after.read_bytes()
    usage_after.unlink()
    assert rig.run(reconcile_argv(rig), responder) == 0  # writes the manifest, stays open
    ledger(rig).settle(directory.name, None, "the hold the killed reconcile left")
    usage_after.write_bytes(kept)
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert events_of(rig, directory.name) == ["reserve", "settle", "adjust"]
    assert record_of(rig, directory.name).charged_usd == Decimal("0.0123")


def test_an_attempt_directory_with_a_manifest_is_untouched_by_the_interrupted_path(
    rig: Rig,
) -> None:
    responder, directory = interrupted(rig)
    sealed = load(directory.with_name(directory.name[: -len("-2")] + "-1") / "manifest.json")
    (directory / "manifest.json").write_text(
        json.dumps({**sealed, "attempt_id": directory.name}), encoding="utf-8"
    )
    files = {p.name: p.read_bytes() for p in directory.iterdir()}
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == files
    assert ledger(rig).path.read_bytes() == lines
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    assert "Looked up this run: 0" in report


def test_a_request_whose_call_may_still_be_in_flight_is_not_called_interrupted(rig: Rig) -> None:
    """Confidence review: reconcile run beside a live batch must not seal the runner's in-flight
    attempt (its own seal would then fail on the existing manifest). A call lives at most
    twice its deadline (`client.urllib_transport`: one socket operation past it)."""
    responder, directory = interrupted(rig)
    os.utime(directory / "request.json")  # written just now: the call may still be running
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert sorted(p.name for p in directory.iterdir()) == ["request.json"]
    assert ledger(rig).path.read_bytes() == lines
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    (outcome,) = [line for line in report.splitlines() if line.startswith(f"| {directory.name}")]
    assert "| unresolved |" in outcome and "may still be in flight" in outcome


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            lambda d: (d / "response.json").write_text("{}", encoding="utf-8"),
            "holds request.json, response.json, not request.json only",
        ),
        (lambda d: (d / "request.json").unlink(), "holds no request.json"),
        (
            lambda d: (d / "request.json").write_text('{"endpoint": null}', encoding="utf-8"),
            "not a pool chat request",
        ),
    ],
    ids=["reply-retained", "no-request", "proxy-shaped"],
)
def test_another_unsealed_shape_is_reported_unresolved_and_nothing_is_written(
    rig: Rig, change: Callable[[Path], object], reason: str
) -> None:
    responder, directory = interrupted(rig)
    change(directory)
    files = {p.name: p.read_bytes() for p in directory.iterdir()}
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == files
    assert ledger(rig).path.read_bytes() == lines
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    (outcome,) = [line for line in report.splitlines() if line.startswith(f"| {directory.name}")]
    assert "| unresolved |" in outcome and reason in outcome
