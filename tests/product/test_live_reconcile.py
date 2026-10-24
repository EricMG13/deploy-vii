"""`deploy-vii live reconcile`: held charges replaced by the generation endpoint's cost."""

import argparse
import hashlib
import json
import os
import socket
import time
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from deploy_vii.live import cli
from deploy_vii.live.client import (
    CHAT_URL,
    GENERATION_URL,
    KEY_URL,
    ChatClient,
    Request,
    Response,
    TransportError,
)
from deploy_vii.live.ledger import AttemptRecord, Ledger
from deploy_vii.live.reconcile import (
    INTERRUPTED_SETTLE,
    RetainedAttempt,
    generation_cost,
    spend_cross_check,
)
from tests.product.live_support import FAKE_KEY, SECOND_FAKE_KEY, make_rtf_key, ok
from tests.product.test_live_cli_batches import DEEPSEEK, Responder, Rig, key_status, step_lines

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
        # Task 7.15 item 6: a record of another schema is not read as a usage check.
        ("other-schema", "account usage after the batch is not an account-usage-check/1 record"),
        # 7.14 addendum: the refusals use the documented "key-file note" wording.
        ("other-token", "the two account usage checks record different key-file notes"),
        (
            "other-note-now",
            "the usage check now records another key-file note than the after-check; "
            "not attributed",
        ),
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
    elif edit == "other-note-now":  # both checks agree; the one-token reading now has no note
        for path in (before, after):
            record = load(path)
            record["credit"]["key_file"] = {"key_tokens_found": 2, "key_token_used": 2}
            path.write_text(json.dumps(record), encoding="utf-8")
    else:
        record = load(after)
        if edit == "null-usage":
            record["credit"]["usage"] = None
        elif edit == "other-schema":
            record["schema"] = "account-usage-check/2"
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


def outcome_line(rig: Rig, attempt_id: str) -> str:
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    (line,) = [row for row in report.splitlines() if row.startswith(f"| {attempt_id}")]
    return line


def test_a_resumed_interrupted_path_never_settles_a_directory_the_runner_got_further_in(
    rig: Rig,
) -> None:
    """7.11 review concern 1: the manifest this path wrote earlier is found again, but the
    directory now holds a `response.json` (the runner got further), so no usage delta settles
    it over a measured cost."""
    responder, directory = interrupted(rig)
    usage_after = rig.root / "artifacts" / "model-tests" / "b1" / "account-usage-after.json"
    kept = usage_after.read_bytes()
    usage_after.unlink()
    assert rig.run(reconcile_argv(rig), responder) == 0  # writes the manifest, stays open
    assert load(directory / "manifest.json")["recorded_by"] == "deploy-vii live reconcile"
    (directory / "response.json").write_text("{}", encoding="utf-8")
    usage_after.write_bytes(kept)  # the batch's own window would now attribute it
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines  # no settle, no adjust
    assert record_of(rig, directory.name).status == "reserved"
    outcome = outcome_line(rig, directory.name)
    assert "| unresolved |" in outcome
    assert "holds manifest.json, request.json, response.json" in outcome
    assert "not manifest.json and request.json only" in outcome


# --- 7.13: the next batch's before-check closes an interrupted batch's window ----------------

NEXT_SOURCE = "account-usage-delta/next-batch-before"


def _stamp(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def killed_batch(rig: Rig, *, held_cost: str = "0.0123") -> tuple[AllAnswered, Path, Path]:
    """The e1-cp1-12 shape (synthetic): batch b1 was killed mid-step, so it has its
    before-check and no after-check; batch b2's before-check follows a minute later, the
    account having moved by b1's measured charges plus `held_cost`."""
    responder, directory = interrupted(rig, unexplained="0")
    model_tests = rig.root / "artifacts" / "model-tests"
    (model_tests / "b1" / "account-usage-after.json").unlink()
    before = load(model_tests / "b1" / "account-usage-before.json")
    attempts = ledger(rig).state().attempts
    charged = sum((a.charged_usd or Decimal(0) for a in attempts), Decimal(0))
    later = json.loads(json.dumps(before))
    usage = Decimal(before["credit"]["usage"]) + charged + Decimal(held_cost)
    later["credit"]["usage"] = format(usage, "f")
    later["credit"]["checked_at"] = _stamp(time.time() + 60)
    (model_tests / "b2").mkdir()
    next_before = model_tests / "b2" / "account-usage-before.json"
    next_before.write_text(json.dumps(later), encoding="utf-8")
    return responder, directory, next_before


def test_a_killed_batch_is_settled_from_the_next_batchs_before_check_over_an_empty_gap(
    rig: Rig,
) -> None:
    responder, directory, next_before = killed_batch(rig)
    before = ledger(rig).state()
    keys = responder.key_checks
    assert rig.run(reconcile_argv(rig), responder) == 0
    # No reconcile-time reading for the window (later spend moved it); the one reading is the
    # task 7.14 spend cross-check's, taken after every adjust (`usage_now_usd` is absent below).
    assert responder.key_checks == keys + 1
    assert events_of(rig, directory.name) == ["reserve", "settle", "adjust"]
    record = record_of(rig, directory.name)
    assert record.charged_usd == Decimal("0.0123")
    adjustment = record.adjustment
    assert adjustment is not None and adjustment.source == NEXT_SOURCE
    assert adjustment.generation_id is None
    evidence = adjustment.evidence
    assert evidence is not None
    b1 = load(rig.root / "artifacts" / "model-tests" / "b1" / "account-usage-before.json")
    assert evidence["usage_window_closed_by"] == "next-batch-before"
    assert evidence["usage_before_file"] == "b1/account-usage-before.json"
    assert evidence["usage_after_file"] == "b2/account-usage-before.json"
    assert evidence["usage_before_checked_at"] == b1["credit"]["checked_at"]
    assert evidence["usage_after_checked_at"] == load(next_before)["credit"]["checked_at"]
    assert evidence["next_batch_id"] == "b2"
    assert evidence["reservations_between_checks"] == 0
    assert evidence["ledgers_read"] == ["b1.jsonl"]
    assert evidence["held_attempts"] == [directory.name]
    others = [a for a in before.attempts if a.attempt_id != directory.name]
    assert Decimal(evidence["other_attempts_measured_usd"]) == sum(
        (a.charged_usd or Decimal(0) for a in others), Decimal(0)
    )
    assert "usage_now_usd" not in evidence
    # Review fix: the record names the window's limit (a later booking is not seen).
    assert evidence["reconcile_time_reading"] is False
    closing_at = load(next_before)["credit"]["checked_at"]
    outcome = outcome_line(rig, directory.name)
    assert "| reconciled |" in outcome and f"settled by {NEXT_SOURCE}" in outcome
    for fact in (
        "b1/account-usage-before.json",
        "b2/account-usage-before.json",
        b1["credit"]["checked_at"],
        # 7.14 addendum: the reason states the full window rule.
        "no other batch held a reservation open at the before-check, nor reserved or settled "
        "inside the window",
        f"no reconcile-time reading: a charge booked after {closing_at} is not seen",
    ):
        assert fact in outcome, fact


def test_a_reservation_between_the_two_checks_leaves_the_killed_batch_unresolved(
    rig: Rig,
) -> None:
    responder, directory, _ = killed_batch(rig)
    gap = _stamp(time.time() + 30)  # after b1's lines, before b2's check
    other = rig.root / "artifacts" / "model-tests" / ".ledgers" / "b3.jsonl"
    lines_b3 = [
        {"seq": 1, "event": "open", "cap_usd": "1", "at": gap},
        {"seq": 2, "event": "reserve", "attempt_id": "x-1", "usd": "0.1", "at": gap},
    ]
    other.write_text("".join(json.dumps(line) + "\n" for line in lines_b3), encoding="utf-8")
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines  # the reservation stays open
    assert record_of(rig, directory.name).status == "reserved"
    outcome = outcome_line(rig, directory.name)
    assert "| unresolved |" in outcome
    assert "no account usage was recorded after the batch" in outcome
    assert f"b3.jsonl reserved x-1 at {gap}, between the two checks" in outcome


def test_the_next_batchs_own_first_reservation_in_its_check_second_is_not_in_the_gap(
    rig: Rig,
) -> None:
    """The runner records a batch's before-check before its first reservation, and both carry
    second-resolution stamps: the next batch's own line in that second follows its check."""
    responder, directory, next_before = killed_batch(rig)
    at = load(next_before)["credit"]["checked_at"]
    own = rig.root / "artifacts" / "model-tests" / ".ledgers" / "b2.jsonl"
    lines_b2 = [
        {"seq": 1, "event": "open", "cap_usd": "1", "at": at},
        {"seq": 2, "event": "reserve", "attempt_id": "y-1", "usd": "0.1", "at": at},
    ]
    own.write_text("".join(json.dumps(line) + "\n" for line in lines_b2), encoding="utf-8")
    assert rig.run(reconcile_argv(rig), responder) == 0
    adjustment = record_of(rig, directory.name).adjustment
    assert adjustment is not None and adjustment.source == NEXT_SOURCE
    assert adjustment.evidence is not None
    assert adjustment.evidence["ledgers_read"] == ["b1.jsonl", "b2.jsonl"]


def test_a_next_check_before_the_killed_batchs_last_line_does_not_close_its_window(
    rig: Rig,
) -> None:
    responder, directory, _ = killed_batch(rig)
    late = Ledger(ledger(rig).path, Decimal("5.00"), clock=lambda: _stamp(time.time() + 120))
    late.reserve("late-1", Decimal("0.1"))
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines
    outcome = outcome_line(rig, directory.name)
    assert "| unresolved |" in outcome
    assert "follows the next batch's before-check; the window does not cover the batch" in outcome


def test_a_settle_left_after_the_closing_check_is_adjusted_once_from_the_same_window(
    rig: Rig,
) -> None:
    """Review fix 1: a reconcile stopped between its own settle and its adjust leaves a settle
    stamped after the next batch's check. That line is reconcile's, not the runner's, so the
    window still covers the batch and the next run writes the one adjust."""
    responder, directory, next_before = killed_batch(rig)
    kept = next_before.read_bytes()
    next_before.unlink()
    assert rig.run(reconcile_argv(rig), responder) == 0  # writes the manifest, stays open
    later = Ledger(ledger(rig).path, Decimal("5.00"), clock=lambda: _stamp(time.time() + 120))
    later.settle(directory.name, None, INTERRUPTED_SETTLE)
    next_before.write_bytes(kept)
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert events_of(rig, directory.name) == ["reserve", "settle", "adjust"]
    adjustment = record_of(rig, directory.name).adjustment
    assert adjustment is not None and adjustment.source == NEXT_SOURCE
    assert record_of(rig, directory.name).charged_usd == Decimal("0.0123")


def other_ledger(rig: Rig, name: str, lines: list[dict[str, object]]) -> None:
    path = rig.root / "artifacts" / "model-tests" / ".ledgers" / f"{name}.jsonl"
    numbered = [{"seq": n, **line} for n, line in enumerate(lines, start=1)]
    path.write_text("".join(json.dumps(line) + "\n" for line in numbered), encoding="utf-8")


def test_another_batchs_reservation_open_at_the_before_check_leaves_it_unresolved(
    rig: Rig,
) -> None:
    """Review ruling 3: a reservation of another batch opened before the window and settled
    after it (or never) may be billed inside it."""
    responder, directory, _ = killed_batch(rig)
    early, late = _stamp(time.time() - 3600), _stamp(time.time() + 300)
    other_ledger(
        rig,
        "b0",
        [
            {"event": "open", "cap_usd": "1", "at": early},
            {"event": "reserve", "attempt_id": "z-1", "usd": "0.1", "at": early},
            {
                "event": "settle",
                "attempt_id": "z-1",
                "actual_usd": "0.01",
                "charged_usd": "0.01",
                "reason": "usage.cost",
                "at": late,
            },
        ],
    )
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines
    outcome = outcome_line(rig, directory.name)
    assert "| unresolved |" in outcome
    assert f"b0.jsonl reservation z-1 (reserved at {early}) was still open at the before-check" in (
        outcome
    )


def test_another_batchs_settle_inside_the_window_leaves_it_unresolved(rig: Rig) -> None:
    responder, directory, _ = killed_batch(rig)
    early, gap = _stamp(time.time() - 3600), _stamp(time.time() + 30)
    other_ledger(
        rig,
        "b0",
        [
            {"event": "open", "cap_usd": "1", "at": early},
            {"event": "reserve", "attempt_id": "z-1", "usd": "0.1", "at": early},
            {
                "event": "settle",
                "attempt_id": "z-1",
                "actual_usd": "0.01",
                "charged_usd": "0.01",
                "reason": "usage.cost",
                "at": gap,
            },
        ],
    )
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines
    outcome = outcome_line(rig, directory.name)
    assert "| unresolved |" in outcome
    assert f"b0.jsonl settled z-1 at {gap}, inside the window" in outcome


def test_a_killed_batch_with_no_later_batch_stays_unresolved(rig: Rig) -> None:
    responder, directory, next_before = killed_batch(rig)
    next_before.unlink()
    lines = ledger(rig).path.read_bytes()
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines
    outcome = outcome_line(rig, directory.name)
    assert "| unresolved |" in outcome
    assert "no later batch recorded an account usage check before it" in outcome


# --- 7.14: the spend cross-check (key usage now against every ledger's settled charges) -------
# Reported only: nothing is settled or adjusted from it. Batch e1-cp1-13's after-check lagged its
# settled charges by US$1.0737551 and caught up before e1-cp1-14's before-check; no window rule
# sees that, the key's total usage against every settled charge does.

T0, T1, T2 = "2026-10-23T08:00:00Z", "2026-10-23T08:00:05Z", "2026-10-23T09:00:00Z"
NOW = "2026-10-23T12:00:00Z"
NOTE = {"key_token_used": 2, "key_tokens_found": 2}


class KeyOnly:
    """A transport answering `GET /api/v1/key` with `usage` (None: no usage reported); any
    other request fails the test."""

    def __init__(self, usage: str | None) -> None:
        self.usage = usage
        self.calls = 0

    def __call__(self, request: Request) -> Response:
        assert request.url == KEY_URL, request.url
        self.calls += 1
        if self.usage is None:
            return Response(200, b'{"data":{"limit_remaining":null,"usage":null}}')
        return key_status(self.usage)


def two_token_client(tmp_path: Path, transport: KeyOnly) -> ChatClient:
    """A client reading token 2 of a two-token key file, so each reading carries `NOTE`."""
    keys = tmp_path / "keys"
    keys.mkdir(exist_ok=True)
    key = make_rtf_key(keys, f"{SECOND_FAKE_KEY}\n{FAKE_KEY}", name="two.rtf")
    return ChatClient(transport, key_path=key, key_index=2)


def before_check(root: Path, batch: str, usage: str, at: str, note: object = NOTE) -> None:
    (root / batch).mkdir(parents=True, exist_ok=True)
    credit = {"checked_at": at, "usage": usage, "key_file": note, "source": "key-endpoint"}
    record = {"schema": "account-usage-check/1", "phase": "before", "credit": credit}
    (root / batch / "account-usage-before.json").write_text(json.dumps(record), encoding="utf-8")


def spent_ledger(root: Path, batch: str, opened: str, *lines: dict[str, object]) -> None:
    (root / ".ledgers").mkdir(parents=True, exist_ok=True)
    every = ({"event": "open", "cap_usd": "5", "at": opened}, *lines)
    numbered = [{"seq": n, **line} for n, line in enumerate(every, start=1)]
    text = "".join(json.dumps(line) + "\n" for line in numbered)
    (root / ".ledgers" / f"{batch}.jsonl").write_text(text, encoding="utf-8")


def charge(attempt: str, usd: str | None, at: str, reserved: str = "1") -> list[dict[str, object]]:
    """A reserve and its settle: `usd` the measured cost, None a hold at the reservation."""
    return [
        {"event": "reserve", "attempt_id": attempt, "usd": reserved, "at": at},
        {
            "event": "settle",
            "attempt_id": attempt,
            "actual_usd": usd,
            "charged_usd": reserved if usd is None else usd,
            "reason": "usage.cost" if usd else "no usage",
            "at": at,
        },
    ]


def two_batches(root: Path) -> None:
    """b-early (opened at T1, origin check at T0, usage 10) settled 0.4; b-late settled 0.6."""
    before_check(root, "b-early", "10", T0)
    spent_ledger(root, "b-early", T1, *charge("a-1", "0.4", T1))
    before_check(root, "b-late", "10.9", T2)
    spent_ledger(root, "b-late", T2, *charge("b-1", "0.6", T2))


@pytest.mark.parametrize(
    ("now", "unattributed"), [("11.25", "0.25"), ("11.0", "0"), ("10.9", "-0.1")]
)
def test_the_cross_check_names_billed_less_settled_as_unattributed_usd(
    tmp_path: Path, now: str, unattributed: str
) -> None:
    root = tmp_path / "model-tests"
    two_batches(root)
    transport = KeyOnly(now)
    found, why = spend_cross_check(two_token_client(tmp_path, transport), lambda: NOW, root)
    assert why == "" and found is not None and transport.calls == 1
    assert (found.origin_file, found.origin_usd, found.origin_at) == (
        "b-early/account-usage-before.json",
        Decimal("10"),
        T0,
    )
    assert (found.now_usd, found.now_at) == (Decimal(now), NOW)
    assert found.settled_usd == Decimal("1.0")
    assert found.ledgers == ("b-early.jsonl", "b-late.jsonl")
    assert (found.excluded, found.excluded_usd) == ((), Decimal(0))
    assert found.billed_usd == Decimal(now) - Decimal("10")
    assert found.unattributed_usd == Decimal(unattributed)
    # Exact Decimal arithmetic: billed less settled, with no rounding.
    assert found.unattributed_usd == found.billed_usd - found.settled_usd


def test_held_charges_count_at_their_reservation_and_open_reservations_not_at_all(
    tmp_path: Path,
) -> None:
    """The settled sum is the ledgers' own `spent` (adjusted figures where reconciled); the
    part held at a reservation (cost unknown) and the reservations still open are named."""
    root = tmp_path / "model-tests"
    before_check(root, "b1", "10", T0)
    spent_ledger(
        root,
        "b1",
        T1,
        *charge("a-1", "0.4", T1),
        *charge("a-2", None, T1, reserved="0.5"),
        *charge("a-3", None, T1, reserved="0.7"),
        {
            "event": "adjust",
            "attempt_id": "a-3",
            "previous_charged_usd": "0.7",
            "reconciled_usd": "0.05",
            "generation_id": "gen-a3",
            "checked_at": T2,
            "source": "generation-endpoint",
            "at": T2,
        },
        {"event": "reserve", "attempt_id": "a-4", "usd": "2", "at": T2},
    )
    found, why = spend_cross_check(two_token_client(tmp_path, KeyOnly("11")), lambda: NOW, root)
    assert why == "" and found is not None
    assert found.settled_usd == Decimal("0.95")  # 0.4 + 0.5 held + 0.05 adjusted
    assert found.held_usd == Decimal("0.5")
    assert found.open_reservations == 1
    assert found.unattributed_usd == Decimal("0.05")


def test_the_origin_is_the_earliest_recorded_before_check_and_earlier_ledgers_are_named(
    tmp_path: Path,
) -> None:
    """Fix round 1 (coordinator): the real root's earliest ledger, probe-1, has no before-check.
    The origin is the earliest recorded one; a ledger opened before it is not in the figure and
    is named with its settled sum."""
    root = tmp_path / "model-tests"
    spent_ledger(root, "p1", T0, *charge("p-1", "0.3", T0))  # no before-check recorded
    before_check(root, "b-late", "10.9", T1)
    spent_ledger(root, "b-late", T2, *charge("b-1", "0.6", T2))
    found, why = spend_cross_check(two_token_client(tmp_path, KeyOnly("11.6")), lambda: NOW, root)
    assert why == "" and found is not None
    assert (found.origin_file, found.origin_usd, found.origin_at) == (
        "b-late/account-usage-before.json",
        Decimal("10.9"),
        T1,
    )
    assert (found.ledgers, found.settled_usd) == (("b-late.jsonl",), Decimal("0.6"))
    assert (found.excluded, found.excluded_usd) == (("p1.jsonl",), Decimal("0.3"))
    assert found.unattributed_usd == Decimal("0.1")


def test_a_ledger_opened_in_the_origins_second_is_counted(tmp_path: Path) -> None:
    """The runner records the before-check before its first reservation, in the same second
    as the ledger's opening line (e1-cp1-13: 08:43:18Z for both)."""
    root = tmp_path / "model-tests"
    before_check(root, "b1", "10", T1)
    spent_ledger(root, "b1", T1, *charge("a-1", "0.4", T1))
    found, _ = spend_cross_check(two_token_client(tmp_path, KeyOnly("10.4")), lambda: NOW, root)
    assert found is not None and found.ledgers == ("b1.jsonl",) and found.excluded == ()
    assert found.unattributed_usd == Decimal(0)


def unreadable(path: Path) -> None:
    path.write_text("[]", encoding="utf-8")


def usage_of(path: Path, value: object) -> None:
    record = load(path)
    record["credit"]["usage"] = value
    path.write_text(json.dumps(record), encoding="utf-8")


EARLY = "b-early/account-usage-before.json"
LATE = "b-late/account-usage-before.json"


@pytest.mark.parametrize(
    ("arrange", "reason"),
    [
        (
            lambda root: [p.unlink() for p in root.glob("*/account-usage-before.json")],
            "no batch under the artifact root recorded an account usage check before it",
        ),
        (
            lambda root: unreadable(root / LATE),
            f"{LATE} is not a readable account usage check; the origin is unknown",
        ),
        (
            lambda root: usage_of(root / LATE, None),
            f"{LATE}: account usage before the batch is not a recorded number; the origin is "
            "unknown",
        ),
        (
            lambda root: before_check(root, "b-late", "10.9", "late morning"),
            f"{LATE} records no check time; the origin is unknown",
        ),
        (
            lambda root: before_check(root, "b-tie", "10", T0),
            f"{EARLY} and b-tie/account-usage-before.json checked account usage in the same "
            "second; the origin is unknown",
        ),
        (
            lambda root: (root / ".ledgers" / "b-late.jsonl").write_text("{}\n", encoding="utf-8"),
            "b-late.jsonl has no readable opening line",
        ),
        (
            lambda root: spent_ledger(root, "b-late", "noon"),
            "b-late.jsonl records no opening time",
        ),
        (
            lambda root: [p.unlink() for p in (root / ".ledgers").glob("*.jsonl")],
            "no ledger under .ledgers",
        ),
    ],
    ids=[
        "no-before-check",
        "unreadable-check",
        "check-without-usage",
        "check-without-time",
        "tie",
        "unreadable-ledger",
        "ledger-without-time",
        "no-ledger",
    ],
)
def test_an_unusable_origin_or_ledger_shows_no_figure_and_reads_no_key(
    tmp_path: Path, arrange: Callable[[Path], object], reason: str
) -> None:
    root = tmp_path / "model-tests"
    two_batches(root)
    arrange(root)
    transport = KeyOnly("11")
    found = spend_cross_check(two_token_client(tmp_path, transport), lambda: NOW, root)
    assert found == (None, reason)
    assert transport.calls == 0


@pytest.mark.parametrize(
    ("usage", "note", "reason"),
    [
        (None, NOTE, "the account usage now is not reported"),
        ("11", None, "the usage check now records another key-file note than the origin check"),
    ],
)
def test_a_reading_now_that_cannot_be_compared_shows_no_figure(
    tmp_path: Path, usage: str | None, note: object, reason: str
) -> None:
    root = tmp_path / "model-tests"
    two_batches(root)
    before_check(root, "b-early", "10", T0, note=note)
    found = spend_cross_check(two_token_client(tmp_path, KeyOnly(usage)), lambda: NOW, root)
    assert found == (None, reason)


def test_a_connection_failure_in_the_cross_check_reading_propagates(tmp_path: Path) -> None:
    root = tmp_path / "model-tests"
    two_batches(root)

    def down(request: Request) -> Response:
        raise TransportError(f"connection reset {FAKE_KEY}")

    client = ChatClient(down, key_path=make_rtf_key(tmp_path), key_index=1)
    with pytest.raises(TransportError):
        spend_cross_check(client, lambda: NOW, root)


def spend_section(report: str) -> list[str]:
    section = report.split("## Spend cross-check\n", 1)[1]
    return section.split("\n## ", 1)[0].strip().splitlines()


def test_the_reconciled_report_carries_the_section_with_both_inputs_and_no_key(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    responder.generations = {responder.ids[0]: generation(0.002)}
    assert rig.run(reconcile_argv(rig), responder) == 0
    model_tests = rig.root / "artifacts" / "model-tests"
    origin = load(model_tests / "b1" / "account-usage-before.json")["credit"]
    state = ledger(rig).state()
    now = responder.usage + responder.unexplained  # what the reconcile-time reading reports
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    lines = spend_section(report)
    assert lines[0] == "Reported only: nothing is settled or adjusted from this figure."
    assert (
        f"- Origin: b1/account-usage-before.json, usage {origin['usage']} USD at "
        f"{origin['checked_at']} (the earliest recorded before-check)"
    ) in lines
    assert "- Not covered: no ledger opened before the origin" in lines
    assert any(line.startswith(f"- Key usage now: {format(now, 'f')} USD at ") for line in lines)
    assert (
        f"- Settled in 1 ledger (.ledgers/*.jsonl): {format(state.spent, 'f')} USD, of which "
        "0 USD held at a reservation (cost unknown); 0 reservations open (not counted)"
    ) in lines
    billed = now - Decimal(origin["usage"])
    assert f"- Billed since the origin: {format(billed, 'f')} USD" in lines
    assert f"- Unattributed USD: {format(billed - state.spent, 'f')}" in "\n".join(lines)
    assert "sk-or-" not in report + capsys.readouterr().out


def test_without_an_origin_the_section_says_so_and_shows_no_figure(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    (rig.root / "artifacts" / "model-tests" / "b1" / "account-usage-before.json").unlink()
    responder.generations = {responder.ids[0]: generation(0.002)}
    assert rig.run(reconcile_argv(rig), responder) == 0
    lines = spend_section((rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8"))
    assert lines == [
        "Reported only: nothing is settled or adjusted from this figure.",
        "",
        "- No figure: no batch under the artifact root recorded an account usage check before it",
    ]


def test_the_section_names_a_ledger_opened_before_the_origin_with_its_settled_sum(
    rig: Rig,
) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    early = _stamp(time.time() - 3600)
    other_ledger(
        rig,
        "p0",
        [
            {"event": "open", "cap_usd": "1", "at": early},
            *charge("z-1", "0.07", early),
        ],
    )
    responder.generations = {responder.ids[0]: generation(0.002)}
    assert rig.run(reconcile_argv(rig), responder) == 0
    lines = spend_section((rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8"))
    assert (
        "- Not covered: 1 ledger opened before the origin (p0.jsonl), settled 0.07 USD; not in "
        "the figure"
    ) in lines
    assert any(line.startswith("- Settled in 1 ledger (.ledgers/*.jsonl): ") for line in lines)


def test_a_reconcile_stopped_before_the_cross_check_says_it_was_not_checked(rig: Rig) -> None:
    responder = ProbeResponder(rig.review)
    run_probe(rig, responder)
    responder.generations = {responder.ids[0]: OSError(f"reset {FAKE_KEY}")}
    assert rig.run(reconcile_argv(rig), responder) == cli.EXIT_FAILED
    lines = spend_section((rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8"))
    assert lines[-1] == "- No figure: not checked: the reconcile stopped before the cross-check"


class KeyDownAfterBatch(Responder):
    """Every chat call answered (nothing to look up later); the reconcile-time key read, the
    third, fails at the connection level."""

    def __call__(self, request: Request) -> Response:
        if request.url == KEY_URL and len(self.key_requests) >= 2:
            raise TransportError(f"connection reset {FAKE_KEY}")
        return super().__call__(request)


@pytest.mark.parametrize("failure", ["credential", "transport"])
def test_a_failed_cross_check_read_leaves_the_exit_code_to_the_lookups(
    rig: Rig, failure: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 1 (coordinator): the cross-check only reports. With nothing to look up, an
    unreadable credential file or a connection failure on its key read exits 0, and the
    section says "not checked" with the reason (no key text)."""
    responder = KeyDownAfterBatch(rig.review)
    assert rig.run(rig.argv("probe"), responder) == 0
    lines = ledger(rig).path.read_bytes()
    if failure == "credential":
        rig.key.write_text("no key here\n", encoding="utf-8")
    assert rig.run(reconcile_argv(rig), responder) == 0
    assert ledger(rig).path.read_bytes() == lines
    report = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    (line,) = [x for x in spend_section(report) if x.startswith("- No figure: ")]
    expected = "CredentialError: " if failure == "credential" else "TransportError: "
    assert line.startswith(f"- No figure: not checked: {expected}"), line
    out = capsys.readouterr().out
    assert "spend cross-check not checked: " in out
    assert "sk-or-" not in report + out and "TESTONLY" not in report + out


def test_the_cross_check_counts_only_openrouter_ledgers(tmp_path: Path) -> None:
    """Task 8.0d item 8: the key's usage is OpenRouter's, so a ledger whose opening line names
    another provider is named with its settled sum, not counted; a ledger that names none (every
    ledger before 8.0d) is OpenRouter's, as is one that names `openrouter`."""
    root = tmp_path / "model-tests"
    two_batches(root)  # b-early 0.4 and b-late 0.6, both without a recorded provider
    spent_ledger(root, "b-ant", T2, *charge("c-1", "2.5", T2))
    spent_ledger(root, "b-or", T2, *charge("d-1", "0.1", T2))
    for name, provider in (("b-ant", "anthropic"), ("b-or", "openrouter")):
        path = root / ".ledgers" / f"{name}.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[0] = json.dumps(json.loads(lines[0]) | {"provider": provider})
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    found, why = spend_cross_check(two_token_client(tmp_path, KeyOnly("11.25")), lambda: NOW, root)
    assert why == "" and found is not None
    assert found.ledgers == ("b-early.jsonl", "b-late.jsonl", "b-or.jsonl")
    assert found.settled_usd == Decimal("1.1")
    assert found.other_providers == (("b-ant.jsonl", "anthropic"),)
    assert found.other_providers_usd == Decimal("2.5")
    assert found.unattributed_usd == Decimal("0.15")
    lines = cli._spend_section((found, ""))
    assert (
        "- Not counted: 1 ledger of another provider (b-ant.jsonl: anthropic), settled 2.5 USD; "
        "the key's usage is OpenRouter's only"
    ) in lines
    assert not any(
        x.startswith("- Not counted")
        for x in cli._spend_section((replace(found, other_providers=()), ""))
    )
