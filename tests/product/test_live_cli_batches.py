"""`deploy-vii live` subcommands over a fake transport: no network, key never an argument."""

import argparse
import hashlib
import json
import socket
import stat
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from deploy_vii.execution import Attempt, Execution
from deploy_vii.live import cli
from deploy_vii.live.client import CHAT_URL, KEY_URL, Request, Response
from deploy_vii.live.draw import draw
from deploy_vii.live.ledger import Ledger
from deploy_vii.live.prompts import schema_text
from deploy_vii.live.schema import (
    VariantRefused,
    bisect_variant,
    nullable_array_fields,
    schema_shape,
    strict_copy,
    strict_schema,
)
from deploy_vii.registry import modules
from tests.product.live_support import (
    FAKE_KEY,
    FIXTURES,
    SECOND_FAKE_KEY,
    catalog_row,
    fixture_pool,
    make_rtf_key,
    ok,
)
from tests.product.test_execution import fixture_store
from tests.product.test_live_client import choice_error_body
from tests.product.test_readiness import as_submission, readiness_fixture

LUNA, GLM, DEEPSEEK = "openai/gpt-6-luna", "z-ai/glm-5.3-flash", "deepseek/deepseek-v4.1-flash-1017"
SETTINGS = """
[model_tests]
credential_file = "{key}"
artifact_root = "artifacts/model-tests"
default_effort = "high"
complex_effort = "xhigh"
cumulative_ceiling_usd = 200
prompt_bytes_per_token_lower_bound = 3.0
recurring_caps_usd = {{ e1_per_case = 3, e2_per_milestone = 15, e3_per_week = 3 }}

[[model_tests.candidates]]
key = "luna"
model_id = "openai/gpt-6-luna"
resolution = "explicit-version"

[[model_tests.candidates]]
key = "glm"
model_id = "z-ai/glm-5.3-flash"
resolution = "explicit-version"

[[model_tests.candidates]]
key = "deepseek"
model_id = "deepseek/deepseek-v4.1-flash-1017"
resolution = "refresh-latest-suitable-deepseek-before-batch"

[ci]
model_calls = false
"""


def key_status(usage: str) -> Response:
    """A `GET /api/v1/key` reply (no spending limit) reporting account `usage` in USD."""
    # A JSON number written with its exact digits, as OpenRouter sends it.
    return Response(200, f'{{"data":{{"limit_remaining":null,"usage":{usage}}}}}'.encode())


class Responder:
    """Fake transport: answers every chat call as the requested model and the account-usage
    checks with `usage` (before) then `usage` plus the served cost (after). `requests` holds
    the chat calls only; `key_requests` the usage checks."""

    def __init__(self, content: str, *, junk_after_first: bool = False, usage: str = "1.5") -> None:
        self.content = content
        self.junk_after_first = junk_after_first
        self.requests: list[Request] = []
        self.key_requests: list[Request] = []
        self.usage = Decimal(usage)

    def __call__(self, request: Request) -> Response:
        if request.url == KEY_URL:
            self.key_requests.append(request)
            return key_status(format(self.usage, "f"))
        self.requests.append(request)
        model = json.loads(request.body or b"{}")["model"]
        junk = self.junk_after_first and len(self.requests) > 1
        self.usage += Decimal("0.00033")  # what `ok` reports as usage.cost
        return ok("{}" if junk else self.content, model=model)


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        keys = tmp_path / "keys"
        keys.mkdir()
        self.key = make_rtf_key(keys)
        (tmp_path / "settings").mkdir()
        self.settings = tmp_path / "settings" / "project.toml"
        self.settings.write_text(SETTINGS.format(key=self.key), encoding="utf-8")
        self.store = fixture_store(tmp_path)
        # What a model returns for source_readiness (decision 0008: the submission shape).
        self.review = as_submission(readiness_fixture()[1]).model_dump_json()
        self.reports = tmp_path / "reports"

    def argv(self, *words: str, cap: str | None = "5.00", batch: str = "b1") -> list[str]:
        out = [
            *words,
            "--directory",
            str(self.store.directory),
            "--settings",
            str(self.settings),
            "--catalog",
            str(FIXTURES / "models-subset.json"),
            "--report-directory",
            str(self.reports),
            "--batch-id",
            batch,
            "--seed",
            "3",
        ]
        return out + (["--cap", cap] if cap else [])

    def run(self, argv: list[str], responder: cli.Transport) -> int:
        parser = argparse.ArgumentParser()
        cli.configure(parser)
        return cli.execute(parser.parse_args(argv), transport=responder)

    def report(self, batch: str = "b1") -> str:
        return (self.reports / f"live-{batch}.md").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any real socket connection in these tests is a failure, not a skipped check."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted in an offline CLI test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def step_lines(text: str, prefix: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in line.strip("| ").split(" | ")]
        for line in text.splitlines()
        if line.startswith(f"| {prefix}")
    ]


def test_cap_is_required_on_every_live_subcommand(rig: Rig) -> None:
    for word in (["probe"], ["module", "--module", "CP-0"], ["regression"], ["canary"]):
        with pytest.raises(SystemExit) as stop:
            rig.run(rig.argv(*word, cap=None), Responder(rig.review))
        assert stop.value.code == 2


def test_no_option_takes_the_key(rig: Rig) -> None:
    parser = argparse.ArgumentParser()
    cli.configure(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["probe", "--key", "x", "--cap", "1", "--directory", "d"])


def test_cap_cannot_be_raised_after_the_ledger_is_opened(rig: Rig) -> None:
    ledger = rig.root / "artifacts" / "model-tests" / ".ledgers" / "b2.jsonl"
    Ledger(ledger, Decimal("0.10")).reserve("earlier", Decimal("0.01"))  # opens and binds the cap
    responder = Responder(rig.review)
    argv = rig.argv("module", "--module", "CP-0", cap="50.00", batch="b2")
    assert rig.run(argv, responder) == cli.EXIT_FAILED
    assert responder.requests == []


def test_existing_report_is_not_overwritten(rig: Rig) -> None:
    responder = Responder(rig.review)
    assert rig.run(rig.argv("module", "--module", "CP-0"), responder) == 0
    assert rig.run(rig.argv("module", "--module", "CP-0"), responder) == cli.EXIT_FAILED
    assert len(responder.requests) == 1


def test_cap_above_cumulative_ceiling_is_refused(rig: Rig) -> None:
    responder = Responder(rig.review)
    assert rig.run(rig.argv("canary", cap="201"), responder) == cli.EXIT_FAILED
    assert responder.requests == []


def test_module_cp0_runs_offline_and_report_has_no_raw_data(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    responder = Responder(rig.review)
    assert rig.run(rig.argv("module", "--module", "CP-0"), responder) == 0
    assert [r.url for r in responder.requests] == [CHAT_URL]  # no catalog fetch, no other host
    assert [r.url for r in responder.key_requests] == [KEY_URL, KEY_URL]  # before and after
    text = rig.report()
    (row,) = step_lines(text, "module-00")
    assert row[2:4] == ["source_readiness", row[3]] and row[6] == "accepted"
    for forbidden in ("Synthetic issuer", FAKE_KEY, "choices", "messages", "<<<SOURCE"):
        assert forbidden not in text
    assert f"{len({d.module_id for d in cli.STEPS.values()})} of {len(modules())}" in text
    assert FAKE_KEY not in capsys.readouterr().out


def _use_two_token_key(rig: Rig, index: int) -> None:
    two = make_rtf_key(rig.root / "keys", f"old {FAKE_KEY}\nnew {SECOND_FAKE_KEY}", name="two.rtf")
    text = SETTINGS.format(key=two).replace(
        f'credential_file = "{two}"\n',
        f'credential_file = "{two}"\ncredential_token_index = {index}\n',
    )
    assert f"credential_token_index = {index}" in text
    rig.settings.write_text(text, encoding="utf-8")


def test_cli_reads_the_credential_token_index_and_records_it_in_the_manifest(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_two_token_key(rig, 2)
    responder = Responder(rig.review)
    assert rig.run(rig.argv("module", "--module", "CP-0"), responder) == 0
    assert [r.headers["Authorization"] for r in responder.requests] == [f"Bearer {SECOND_FAKE_KEY}"]
    manifest = json.loads(next(rig.root.rglob("manifest.json")).read_text(encoding="utf-8"))
    assert manifest["credential"]["key_tokens_found"] == 2
    assert manifest["credential"]["key_token_used"] == 2
    assert "sk-or-" not in rig.report() + capsys.readouterr().out


def test_cli_refuses_an_index_beyond_the_file_without_sending_or_echoing_a_token(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_two_token_key(rig, 3)
    responder = Responder(rig.review)
    assert rig.run(rig.argv("module", "--module", "CP-0"), responder) == cli.EXIT_FAILED
    assert responder.requests == []
    out = capsys.readouterr().out
    assert "credential_token_index 3 but only 2 key-shaped tokens" in out
    assert "sk-or-" not in out + rig.report()


def test_unsupported_module_fails_before_spending(rig: Rig) -> None:
    responder = Responder(rig.review)
    assert rig.run(rig.argv("module", "--module", "CP-2"), responder) == cli.EXIT_FAILED
    assert responder.requests == [] and not (rig.reports / "live-b1.md").exists()


def test_probe_draws_each_eligible_model_and_stops_a_cell_on_rejection(rig: Rig) -> None:
    responder = Responder(rig.review, junk_after_first=True)
    assert rig.run(rig.argv("probe", "--draws-per-model", "2"), responder) == 0
    assert {r.url for r in responder.requests} == {CHAT_URL}
    rows = step_lines(rig.report(), "probe-")
    first = [r for r in rows if r[2] == "source_readiness"]
    assert sorted(r[3] for r in first) == sorted([LUNA, GLM, DEEPSEEK] * 2)
    # Only the first request carried a valid review; every other cell stopped at CP-0, and the
    # one cell that went on stopped at its rejected source_context step.
    assert sorted(r[6] for r in first) == ["accepted"] + ["rejected"] * 5
    assert [r[2] for r in rows if r[2] != "source_readiness"] == ["source_context"]


def test_canary_is_one_cell_per_eligible_model(rig: Rig) -> None:
    responder = Responder(rig.review, junk_after_first=True)
    rig.run(rig.argv("canary"), responder)
    assert responder.requests and {r.url for r in responder.requests} == {CHAT_URL}
    rows = step_lines(rig.report(), "canary-")
    assert sorted({r[3] for r in rows if r[2] == "source_readiness"}) == sorted(
        [LUNA, GLM, DEEPSEEK]
    )


def test_regression_order_is_seeded_and_matched(rig: Rig) -> None:
    first = Responder(rig.review, junk_after_first=True)
    rig.run(rig.argv("regression", batch="r1"), first)
    assert first.requests and {r.url for r in first.requests} == {CHAT_URL}
    rig.run(rig.argv("regression", batch="r2"), Responder(rig.review, junk_after_first=True))

    def order(batch: str, case: str) -> list[str]:
        return [
            r[3] for r in step_lines(rig.report(batch), f"{case}-") if r[2] == "source_readiness"
        ]

    for case in ("cp0", "cp1"):
        assert sorted(order("r1", case)) == sorted([LUNA, GLM, DEEPSEEK])  # matched arms
        assert order("r1", case) == order("r2", case)  # same seed, same order


def test_cap_exhaustion_stops_the_batch_and_sends_nothing(rig: Rig) -> None:
    responder = Responder(rig.review)
    code = rig.run(rig.argv("canary", cap="0.000001"), responder)
    assert code == cli.EXIT_CAP and responder.requests == []
    assert "Stopped: cap:" in rig.report()


def test_corpus_command_writes_an_entry_and_fails_closed_on_a_bad_attempt(
    rig: Rig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    responder = Responder(rig.review)
    assert rig.run(rig.argv("module", "--module", "CP-0"), responder) == 0
    attempt = next(rig.root.rglob("manifest.json")).parent
    root = tmp_path / "corpus"
    argv = ["corpus", str(attempt), "case-1", "--root", str(root)]
    parser = argparse.ArgumentParser()
    cli.configure(parser)
    assert cli.execute(parser.parse_args(argv)) == 0
    assert (root / "source_readiness" / "case-1.json").is_file()
    capsys.readouterr()
    assert cli.execute(parser.parse_args(argv)) == cli.EXIT_FAILED
    assert "--replace" in capsys.readouterr().out
    assert cli.execute(parser.parse_args([*argv, "--replace"])) == 0
    # The flag reaches the corpus: without --revalidate it is refused, never ignored.
    flagged = [*argv, "--replace", "--outcome-changed-by", "task 2.9"]
    assert cli.execute(parser.parse_args(flagged)) == cli.EXIT_FAILED
    assert "only with --revalidate" in capsys.readouterr().out


def test_bad_cap_batch_id_and_draw_count_are_refused(rig: Rig) -> None:
    for bad in (["--cap", "abc"], ["--cap", "0"], ["--cap", "NaN"], ["--batch-id", "../x"]):
        with pytest.raises(SystemExit):
            rig.run([*rig.argv("canary", cap=None), *bad], Responder(rig.review))
    responder = Responder(rig.review)
    assert rig.run(rig.argv("probe", "--draws-per-model", "0"), responder) == cli.EXIT_FAILED
    assert responder.requests == []


def test_regression_refuses_a_pool_with_an_ineligible_arm(rig: Rig) -> None:
    ghost = (
        "\n[[model_tests.candidates]]\n"
        'key = "ghost"\nmodel_id = "nobody/none"\nresolution = "explicit-version"\n'
    )
    rig.settings.write_text(rig.settings.read_text(encoding="utf-8") + ghost, encoding="utf-8")
    responder = Responder(rig.review, junk_after_first=True)
    assert rig.run(rig.argv("regression"), responder) == cli.EXIT_FAILED
    assert responder.requests == []
    assert rig.run(rig.argv("canary", batch="c1"), responder) == 0  # canary skips the arm
    assert "| nobody/none | no |" in rig.report("c1")


def test_connection_failure_still_writes_the_report_and_fails(rig: Rig) -> None:
    def broken(request: Request) -> Response:
        raise ConnectionError(f"boom {request.headers['Authorization']}")

    assert rig.run(rig.argv("module", "--module", "CP-0"), broken) == cli.EXIT_FAILED
    text = rig.report()
    assert "Stopped: aborted: TransportError" in text and FAKE_KEY not in text


def test_repeated_draws_use_pairwise_distinct_seeds_that_draw_the_intended_model(rig: Rig) -> None:
    responder = Responder(rig.review, junk_after_first=True)
    assert rig.run(rig.argv("probe", "--draws-per-model", "4"), responder) == 0
    rows = [r for r in step_lines(rig.report(), "probe-") if r[2] == "source_readiness"]
    seeds = [int(r[4]) for r in rows]
    assert len(rows) == 12 and len(set(seeds)) == 12
    pool = fixture_pool("b1")
    assert all(draw(pool, int(r[4])).slug == r[3] for r in rows)


def test_cumulative_ceiling_counts_every_prior_ledger(rig: Rig) -> None:
    ledgers = rig.root / "artifacts" / "model-tests" / ".ledgers"
    Ledger(ledgers / "old1.jsonl", Decimal("120")).reserve("a", Decimal("100"))
    Ledger(ledgers / "old2.jsonl", Decimal("80")).reserve("b", Decimal("60"))
    responder = Responder(rig.review)
    refused = rig.run(rig.argv("module", "--module", "CP-0", cap="50"), responder)
    assert refused == cli.EXIT_FAILED and responder.requests == []
    assert not (rig.reports / "live-b1.md").exists()
    allowed = rig.run(rig.argv("module", "--module", "CP-0", cap="40"), responder)
    assert allowed == 0  # 160 + 40 reaches the 200 ceiling without exceeding it


def test_cumulative_ceiling_message_names_both_numbers(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    ledgers = rig.root / "artifacts" / "model-tests" / ".ledgers"
    Ledger(ledgers / "old1.jsonl", Decimal("120")).reserve("a", Decimal("100"))
    Ledger(ledgers / "old2.jsonl", Decimal("80")).reserve("b", Decimal("60"))
    rig.run(rig.argv("module", "--module", "CP-0", cap="50"), Responder(rig.review))
    out = capsys.readouterr().out
    assert "160" in out and "50" in out and "200" in out


def test_report_write_failure_does_not_mask_the_original_error(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(request: Request) -> Response:
        if request.url == KEY_URL:
            return key_status("1.5")
        rig.reports.chmod(stat.S_IRUSR | stat.S_IXUSR)  # the report can no longer be created
        raise ConnectionError("boom")

    try:
        assert rig.run(rig.argv("module", "--module", "CP-0"), broken) == cli.EXIT_FAILED
    finally:
        rig.reports.chmod(stat.S_IRWXU)
    out = capsys.readouterr().out
    assert "TransportError" in out and "report not written" in out


def test_credit_exhaustion_mid_batch_aborts_cleanly_with_its_own_exit_code(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    served = Responder(rig.review)

    def pays_once(request: Request) -> Response:
        if served.requests and request.url != KEY_URL:
            served.requests.append(request)
            return Response(402, b'{"error":{"message":"no credit","code":402}}')
        return served(request)

    code = rig.run(rig.argv("canary"), pays_once)
    out = capsys.readouterr().out
    assert code == cli.EXIT_CREDIT and cli.EXIT_CREDIT not in (cli.EXIT_CAP, cli.EXIT_FAILED)
    assert "credit is exhausted" in out and "ticket pending; coordinator decision (DC-8)" in out
    assert "Traceback" not in out and FAKE_KEY not in out
    assert "Stopped: aborted: CreditExhausted" in rig.report()
    assert len(served.requests) == 2  # the 402 stopped the batch: no later cell, no other model


def test_a_402_inside_choices_stops_the_batch_as_dc8_requires(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    """Whole-lane review: the credit stop does not depend on where the 402 sits in the 200."""
    served = Responder(rig.review)

    def pays_once(request: Request) -> Response:
        if served.requests and request.url != KEY_URL:
            served.requests.append(request)
            body = json.loads(choice_error_body(error={"code": 402, "message": "no credit"}))
            body["model"] = json.loads(request.body or b"{}")["model"]
            return Response(200, json.dumps(body).encode())
        return served(request)

    code = rig.run(rig.argv("canary"), pays_once)
    out = capsys.readouterr().out
    assert code == cli.EXIT_CREDIT
    assert "ticket pending; coordinator decision (DC-8)" in out
    assert "Stopped: aborted: CreditExhausted" in rig.report()
    assert len(served.requests) == 2  # no later cell, no other model


def test_a_batch_records_account_usage_before_and_after_for_reconcile(rig: Rig) -> None:
    """Decision 0008: `GET /api/v1/key` once before and once after the batch, kept write-once
    under the batch directory with counts only (no key text)."""
    responder = Responder(rig.review, usage="25.7172663")
    assert rig.run(rig.argv("module", "--module", "CP-0"), responder) == 0
    batch = rig.root / "artifacts" / "model-tests" / "b1"
    before = json.loads((batch / "account-usage-before.json").read_text(encoding="utf-8"))
    after = json.loads((batch / "account-usage-after.json").read_text(encoding="utf-8"))
    assert before["schema"] == after["schema"] == "account-usage-check/1"
    assert before["recorded_by"] == "deploy-vii live module"
    assert before["credit"]["usage"] == "25.7172663"
    assert after["credit"]["usage"] == "25.7175963"  # one chat call at 0.00033
    assert before["credit"]["source"] == "key-endpoint" and "sk-or-" not in json.dumps(after)
    # The checks never land inside an attempt directory: reconcile's glob ignores them.
    assert not list(batch.glob("*/*/*/account-usage-*.json"))


def test_a_failed_after_batch_usage_check_is_recorded_not_raised(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    served = Responder(rig.review)

    def key_fails_after(request: Request) -> Response:
        if request.url == KEY_URL and served.key_requests:
            raise ConnectionError("key endpoint down")
        return served(request)

    assert rig.run(rig.argv("module", "--module", "CP-0"), key_fails_after) == 0
    after = rig.root / "artifacts" / "model-tests" / "b1" / "account-usage-after.json"
    record = json.loads(after.read_text(encoding="utf-8"))
    assert record["credit"] is None and record["failure"].startswith("TransportError")
    assert "account usage after the batch not recorded" in capsys.readouterr().out
    assert "accepted" in rig.report()


def test_a_failed_before_batch_usage_check_stops_before_any_spend(rig: Rig) -> None:
    served = Responder(rig.review)

    def key_down(request: Request) -> Response:
        if request.url == KEY_URL:
            raise ConnectionError("key endpoint down")
        return served(request)

    assert rig.run(rig.argv("module", "--module", "CP-0"), key_down) == cli.EXIT_FAILED
    assert served.requests == [] and "Stopped: aborted: TransportError" in rig.report()


DEEP, GROK, MIMO, SOL = (
    "deepseek/deepseek-v4.1-flash-1017",
    "x-ai/grok-4.7",
    "xiaomi/mimo-v2.6-pro",
    "openai/gpt-6.1-sol",
)
FOUR = f"{DEEP}@max,{GROK}@xhigh,{MIMO},{SOL}@high"
FULL = ("max_tokens", "reasoning", "reasoning_effort", "response_format", "structured_outputs")


def four_models(rig: Rig, **overrides: dict[str, object]) -> list[str]:
    """Write a catalog of the four chosen models; `overrides` change a row's catalog_row args."""
    specs: dict[str, dict[str, object]] = {
        DEEP: {"efforts": ("max", "high", "low")},
        GROK: {"context": 500_000, "efforts": ("xhigh", "high")},
        MIMO: {"efforts": None, "parameters": FULL[:2] + FULL[3:]},
        SOL: {"efforts": ("max", "high")},
    }
    rows = {
        name: catalog_row(name, **{**spec, **overrides.get(name, {})})
        for name, spec in specs.items()
    }
    catalog = rig.root / "four.json"
    catalog.write_text(json.dumps({"data": list(rows.values())}), encoding="utf-8")
    return ["--catalog", str(catalog)]


def chat_bodies(responder: Responder) -> list[dict[str, object]]:
    return [json.loads(item.body or b"{}") for item in responder.requests]


def test_models_option_is_accepted_by_every_batch_command_and_refuses_a_bad_effort(
    rig: Rig,
) -> None:
    parser = argparse.ArgumentParser()
    cli.configure(parser)
    for word in (["probe"], ["module", "--module", "CP-0"], ["regression"], ["canary"]):
        args = parser.parse_args([*word, "--cap", "1", "--directory", "d", "--models", FOUR])
        assert [item.model_id for item in args.models] == [DEEP, GROK, MIMO, SOL]
    with pytest.raises(SystemExit):
        parser.parse_args(["probe", "--cap", "1", "--directory", "d", "--models", f"{DEEP}@turbo"])
    assert parser.parse_args(["probe", "--cap", "1", "--directory", "d"]).models is None


def test_user_selected_pool_runs_in_the_given_order_with_each_models_effort(rig: Rig) -> None:
    responder = Responder(rig.review)
    argv = [*rig.argv("probe"), *four_models(rig), "--models", FOUR]
    assert rig.run(argv, responder) == 0
    first = [b for b in chat_bodies(responder) if "source_readiness" in json.dumps(b)]
    assert [b["model"] for b in first] == [DEEP, GROK, MIMO, SOL]
    assert [b["reasoning"] for b in first] == [
        {"effort": "max"},
        {"effort": "xhigh"},
        {"enabled": True},
        {"effort": "high"},
    ]
    text = rig.report()
    assert "- Pool: user-selected (coordinator ruling 22 October 2026)" in text
    pool = {r[0]: r for r in step_lines(text, "deepseek/") + step_lines(text, "x-ai/")}
    assert pool[DEEP][3:5] == ["max", "max"] and pool[GROK][3:5] == ["xhigh", "xhigh"]
    (mimo,) = step_lines(text, "xiaomi/")
    assert mimo[3] == "high (default)" and mimo[4].startswith("none; reasoning enabled")
    (sol,) = step_lines(text, "openai/")
    assert sol[3:5] == ["high", "high"] and Decimal(sol[5]) > 0
    manifests = list((rig.root / "artifacts" / "model-tests" / "b1").rglob("manifest.json"))
    assert len(manifests) == 8  # four models, CP-0 then source_context each
    assert {json.loads(m.read_text())["pool_label"] for m in manifests} == {"user-selected"}


def test_catalog_rule_report_says_so(rig: Rig) -> None:
    assert rig.run(rig.argv("module", "--module", "CP-0"), Responder(rig.review)) == 0
    assert "- Pool: catalog rule" in rig.report()


def test_the_one_model_catalog_rule_pool_runs_sol_at_high_with_a_trivial_draw(rig: Rig) -> None:
    """Decision 0005 amendment: the project's pool (settings/project.toml) is Sol alone."""
    project = (Path("settings") / "project.toml").read_text(encoding="utf-8")
    block = project[project.index("[[model_tests.candidates]]") : project.index("[frontend]")]
    template = SETTINGS.format(key=rig.key)
    start, end = template.index("[[model_tests.candidates]]"), template.index("[ci]")
    rig.settings.write_text(template[:start] + block + template[end:], encoding="utf-8")
    catalog = rig.root / "sol.json"
    sol = catalog_row(SOL, efforts=("max", "xhigh", "high", "medium", "low"))
    catalog.write_text(json.dumps({"data": [sol]}), encoding="utf-8")
    responder = Responder(rig.review)
    argv = [*rig.argv("module", "--module", "CP-0"), "--catalog", str(catalog)]
    assert rig.run(argv, responder) == 0
    assert {b["model"] for b in chat_bodies(responder)} == {SOL}
    assert {json.dumps(b["reasoning"]) for b in chat_bodies(responder)} == {'{"effort": "high"}'}
    text = rig.report()
    assert "- Pool: catalog rule" in text
    pool_section = text.split("## Pool", 1)[1].split("## Steps", 1)[0]
    (row,) = step_lines(pool_section, "openai/")
    assert row[0] == SOL and row[1] == "yes" and row[3:5] == ["high (default)", "high"]
    assert len([line for line in pool_section.splitlines() if line.startswith("| ")]) == 3
    manifests = list((rig.root / "artifacts" / "model-tests" / "b1").rglob("manifest.json"))
    draws = {json.loads(m.read_text())["draw"]["algorithm"] for m in manifests}
    assert manifests and draws == {"trivial-single-model-pool"}


def test_models_naming_an_id_absent_from_the_catalog_fails_closed_before_any_call(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    responder = Responder(rig.review)
    argv = [*rig.argv("probe"), *four_models(rig), "--models", f"{DEEP},x/not-there"]
    assert rig.run(argv, responder) == cli.EXIT_FAILED
    assert "x/not-there" in capsys.readouterr().out
    assert responder.requests == [] and responder.key_requests == []


def test_a_selected_model_without_structured_outputs_is_recorded_ineligible_before_the_draw(
    rig: Rig,
) -> None:
    responder = Responder(rig.review)
    weak = {"parameters": ("max_tokens", "reasoning", "reasoning_effort", "response_format")}
    argv = [*rig.argv("probe"), *four_models(rig, **{GROK: weak}), "--models", FOUR]
    assert rig.run(argv, responder) == 0
    text = rig.report()
    (grok,) = step_lines(text, "x-ai/")
    assert grok[1] == "no" and "structured_outputs" in grok[2]
    assert GROK not in {b["model"] for b in chat_bodies(responder)}
    assert {b["model"] for b in chat_bodies(responder)} == {DEEP, MIMO, SOL}


def test_a_model_whose_context_cannot_hold_the_prompt_is_ineligible_and_never_sent(
    rig: Rig,
) -> None:
    responder = Responder(rig.review)
    argv = [*rig.argv("probe"), *four_models(rig, **{GROK: {"context": 10_000}}), "--models", FOUR]
    assert rig.run(argv, responder) == 0
    assert GROK not in {b["model"] for b in chat_bodies(responder)}
    rows = [r for r in step_lines(rig.report(), "probe-") if r[3] == GROK]
    assert len(rows) == 1 and rows[0][6] == "ineligible"
    assert rows[0][7].startswith("ineligible: context 10000 < bound ")


# --- 2.10: CP-0 gate outcome, --max-tokens -------------------------------------------------


def conditional_cp1(review: str) -> str:
    """The rig's submission with CP-1 CONDITIONAL (probe-4, Sol 944e569a): still a valid,
    accepted CP-0, whose T8 command for CP-1 is DO NOT RUN."""
    document = json.loads(review)
    for consumer in document["consumers"]:
        if consumer["module_id"] == "CP-1":
            consumer["readiness"] = "CONDITIONAL"
            consumer["missing_source"] = "Authoritative CP-1 module brief"
    return json.dumps(document)


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


def test_a_cp0_that_does_not_authorize_cp1_ends_each_cell_and_the_batch_goes_on(
    rig: Rig,
) -> None:
    responder = Responder(conditional_cp1(rig.review))
    assert rig.run(rig.argv("probe"), responder) == 0  # not an abort: exit 0
    assert len(responder.requests) == 3  # one CP-0 call per cell, nothing sent for CP-1
    text = rig.report()
    rows = step_lines(text, "probe-")
    assert [(r[0], r[2], r[6]) for r in rows] == [
        (cell, step, status)
        for cell in ("probe-00", "probe-01", "probe-02")
        for step, status in (("source_readiness", "accepted"), ("source_context", "not-authorized"))
    ]
    for gated, refused in zip(rows[::2], rows[1::2], strict=True):
        assert refused[3:5] == gated[3:5]  # the cell's drawn model and seed
        # No attempt, status not-authorized, class ok, USD 0, no issues.
        assert refused[5:] == ["none", "not-authorized", "ok", "0", "0"]
    assert "- Stopped: no" in text
    assert "- Cells planned: 3; steps run: 3; not authorized by CP-0: 3" in text
    batch = rig.root / "artifacts" / "model-tests" / "b1"
    records = sorted((batch / "not-authorized").glob("*.json"))
    assert [p.stem for p in records] == ["probe-00", "probe-01", "probe-02"]
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["schema"] == "live-step-not-authorized/1"
    assert (record["step_id"], record["module_id"]) == ("source_context", "CP-1")
    assert record["cp0_exact_command"] == ["DO NOT RUN"]
    assert record["cp0_attempt_id"] == rows[0][5]  # the CP-0 attempt whose review gated it
    assert len(list(batch.glob("*/*/*/manifest.json"))) == 3  # no attempt was retained for CP-1

    assert rig.run(reconcile_argv(rig), responder) == 0
    reconciled = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    statuses = [r[6] for r in step_lines(reconciled, "probe-")]
    assert statuses.count("accepted") == 3 and statuses.count("not-authorized") == 3
    (later,) = {tuple(r[5:]) for r in step_lines(reconciled, "probe-") if r[6] == "not-authorized"}
    assert later == ("none", "not-authorized", "ok", "0", "0", "openrouter-pool")


@pytest.mark.parametrize(
    "content",
    [json.dumps({"schema": "something-else/1"}).encode(), b"{not json", b"\xff\xfe"],
    ids=["other-schema", "not-json", "not-utf8"],
)
def test_reconcile_refuses_a_not_authorized_record_it_cannot_read(
    rig: Rig, capsys: pytest.CaptureFixture[str], content: bytes
) -> None:
    responder = Responder(conditional_cp1(rig.review))
    assert rig.run(rig.argv("probe"), responder) == 0
    record = rig.root / "artifacts" / "model-tests" / "b1" / "not-authorized" / "probe-01.json"
    record.write_bytes(content)
    calls = len(responder.requests)
    assert rig.run(reconcile_argv(rig), responder) == cli.EXIT_FAILED
    out = capsys.readouterr().out
    assert "live reconcile failed: CliError: " in out  # a usage error naming the file
    assert "probe-01.json is not a live-step-not-authorized/1 record" in out
    assert len(responder.requests) == calls  # refused before any lookup
    assert not (rig.reports / "live-b1-reconciled.md").exists()


def test_a_journal_copy_fault_before_begin_still_aborts_the_batch(rig: Rig) -> None:
    """A fault before `store.begin` (the first cell's journal copy already exists) aborts."""
    (rig.store.directory / "live" / "b1" / "probe-00").mkdir(parents=True)
    responder = Responder(conditional_cp1(rig.review))
    assert rig.run(rig.argv("probe"), responder) == cli.EXIT_FAILED
    assert responder.requests == [] and "Stopped: aborted: FileExistsError" in rig.report()


def test_a_plain_value_error_from_begin_still_aborts_the_batch(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the typed not-authorized refusal is a step outcome: a plain ValueError from
    `Execution.begin` (any other journal refusal) aborts the batch exactly as before."""
    original = Execution.begin

    def refuse_cp1(store: Execution, module_id: str) -> Attempt:
        if module_id == "CP-1":
            raise ValueError("Required upstream is unrun, stale or blocked")
        return original(store, module_id)

    monkeypatch.setattr(Execution, "begin", refuse_cp1)
    responder = Responder(rig.review)  # CP-1 authorized: begin is reached for source_context
    assert rig.run(rig.argv("probe"), responder) == cli.EXIT_FAILED
    text = rig.report()
    assert "Stopped: aborted: ValueError" in text
    assert [r[2] for r in step_lines(text, "probe-")] == ["source_readiness"]  # first cell only
    assert len(responder.requests) == 1
    assert not (rig.root / "artifacts" / "model-tests" / "b1" / "not-authorized").exists()


def test_max_tokens_reaches_every_request_manifest_and_the_report_header(rig: Rig) -> None:
    responder = Responder(rig.review)
    argv = [*rig.argv("probe"), *four_models(rig), "--models", FOUR, "--max-tokens", "24000"]
    assert rig.run(argv, responder) == 0
    assert {b["max_tokens"] for b in chat_bodies(responder)} == {24000}
    manifests = list((rig.root / "artifacts" / "model-tests" / "b1").rglob("manifest.json"))
    assert manifests
    budgets = [json.loads(m.read_text())["budgets"] for m in manifests]
    assert {b["max_tokens"] for b in budgets} == {24000}
    assert "- Max tokens: 24000" in rig.report()
    default = Responder(rig.review)
    argv = [*rig.argv("probe", batch="b2"), *four_models(rig), "--models", FOUR]
    assert rig.run(argv, default) == 0
    assert {b["max_tokens"] for b in chat_bodies(default)} == {16000}
    assert "- Max tokens: 16000" in rig.report("b2")


def test_max_tokens_goes_through_the_context_fit_check(rig: Rig) -> None:
    """A model that fits the default budget is ineligible, and never sent, once the prompt bound
    plus --max-tokens exceeds its context_length (or max_tokens its max_completion_tokens)."""
    fits = Responder(rig.review)
    narrow = four_models(rig, **{GROK: {"context": 30_000}, MIMO: {"completion_limit": 20_000}})
    assert rig.run([*rig.argv("probe", batch="b0"), *narrow, "--models", FOUR], fits) == 0
    assert {b["model"] for b in chat_bodies(fits)} >= {GROK, MIMO}  # both fit at 16000
    responder = Responder(rig.review)
    argv = [*rig.argv("probe"), *narrow, "--models", FOUR, "--max-tokens", "28000"]
    assert rig.run(argv, responder) == 0
    assert {b["model"] for b in chat_bodies(responder)} == {DEEP, SOL}
    rows = {r[3]: r for r in step_lines(rig.report(), "probe-")}
    assert rows[GROK][6] == "ineligible"
    assert rows[GROK][7].startswith("ineligible: context 30000 < bound ")
    assert rows[MIMO][7] == "ineligible: max completion 20000 < max_tokens 28000"


@pytest.mark.parametrize("value", ["0", "-5", "many"])
def test_a_non_positive_max_tokens_is_refused_by_the_parser(value: str) -> None:
    parser = argparse.ArgumentParser()
    cli.configure(parser)
    for word in (["probe"], ["module", "--module", "CP-0"], ["regression"], ["canary"]):
        assert parser.parse_args([*word, "--cap", "1", "--directory", "d"]).max_tokens == 16000
        with pytest.raises(SystemExit):
            parser.parse_args([*word, "--cap", "1", "--directory", "d", "--max-tokens", value])


def test_one_batch_with_an_ineligible_model_a_refused_cp1_and_a_deadline_hold_then_reconcile(
    rig: Rig,
) -> None:
    """Whole-lane review: the four 2.8-2.10 outcomes in one probe batch, then `reconcile`.
    Grok cannot fit the prompt (ineligible), MiMo and Sol return a valid CP-0 that judges CP-1
    CONDITIONAL (not-authorized), DeepSeek's call passes its wall-clock deadline (the TimeoutError
    `urllib_transport` raises). Only the dispatched CP-0 attempts touch the ledger."""
    served = Responder(conditional_cp1(rig.review), usage="10")

    def transport(request: Request) -> Response:
        if request.url != KEY_URL and json.loads(request.body or b"{}")["model"] == DEEP:
            served.requests.append(request)
            raise TimeoutError(f"wall-clock deadline of {request.timeout_s} s exceeded")
        return served(request)

    narrow = four_models(rig, **{GROK: {"context": 10_000}})
    assert rig.run([*rig.argv("probe"), *narrow, "--models", FOUR], transport) == 0
    text = rig.report()
    rows = [(r[3], r[2], r[5] == "none", r[6], r[7], r[8]) for r in step_lines(text, "probe-")]
    deep = next(r for r in step_lines(text, "probe-") if r[3] == DEEP)
    assert deep[6:8] == ["no-response", "timeout"] and deep[8].startswith("reservation held ")
    grok = next(r for r in step_lines(text, "probe-") if r[3] == GROK)
    assert grok[6] == "ineligible" and grok[7].startswith("ineligible: context 10000 < bound ")
    for model in (MIMO, SOL):
        assert [r[1:] for r in rows if r[0] == model] == [
            ("source_readiness", False, "accepted", "ok", "0.00033"),
            ("source_context", True, "not-authorized", "ok", "0"),
        ]
    assert "- Stopped: no" in text and "steps run: 4; not authorized by CP-0: 2" in text
    assert {json.loads(r.body or b"{}")["model"] for r in served.requests} == {DEEP, MIMO, SOL}

    def ledger_state() -> tuple[object, ...]:
        state = ledger(rig).state()
        return (
            state.reserved,
            state.spent,
            [(a.attempt_id, a.charged_usd, a.actual_usd) for a in state.attempts],
        )

    before = ledger_state()
    reserved, spent, attempts = before
    assert reserved == Decimal(0) and len(attempts) == 3  # DeepSeek, MiMo and Sol CP-0 only
    held = next(a for a in attempts if a[2] is None)  # the one charge without a measured cost
    assert held[0] == deep[5]  # and it is DeepSeek's timed-out attempt
    assert spent == held[1] + Decimal("0.00066")
    assert all(not a[0].endswith("source_context-1") for a in attempts)

    assert rig.run(reconcile_argv(rig), served) == 0
    assert ledger_state() == before  # nothing to look up: the hold stands, no adjust line
    reconciled = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    statuses = sorted(r[6] for r in step_lines(reconciled, "probe-"))
    assert statuses == sorted(
        ["no-response", "ineligible", "accepted", "accepted", "not-authorized", "not-authorized"]
    )
    (outcome,) = [
        line for line in reconciled.splitlines() if held[0] in line and "unresolved" in line
    ]
    assert "no provider_request_id recorded; nothing to look up" in outcome
    assert "Looked up this run: 1; reconciled 0, unresolved 1" in reconciled


def ledger(rig: Rig, batch: str = "b1") -> Ledger:
    return cli.open_ledger(rig.root / "artifacts" / "model-tests" / ".ledgers" / f"{batch}.jsonl")


# --- 2.11: `live schema-check` ----------------------------------------------------------------

SOL_400 = (
    Path(__file__).parent / "fixtures" / "live" / "sol-400-invalid-json-schema-source-context.json"
)
CHECK_COST = Decimal("0.0000123")


class SchemaResponder:
    """Fake transport for `schema-check`: refuses the listed (model, step) with probe-5b's real
    400 body, answers every other call with 16 tokens cut at the length limit."""

    def __init__(
        self,
        refuse: set[tuple[str, str]] | Callable[[str, str, dict[str, Any]], bool],
        *,
        refusal: bytes | None = None,
        hang: Callable[[str, str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self.refuse = refuse
        fixture = json.loads(SOL_400.read_text(encoding="utf-8"))
        self.refusal = refusal or fixture["body_text"].encode("utf-8")
        self.hang = hang
        self.requests: list[Request] = []
        self.key_requests: list[Request] = []

    def schemas(self) -> list[tuple[str, str, dict[str, Any]]]:
        """(model, step, sent schema) of every chat call, in order."""
        out = []
        for request in self.requests:
            body = json.loads(request.body or b"{}")
            fmt = body["response_format"]["json_schema"]
            out.append((body["model"], fmt["name"], fmt["schema"]))
        return out

    def __call__(self, request: Request) -> Response:
        if request.url == KEY_URL:
            self.key_requests.append(request)
            return key_status("2.5")
        self.requests.append(request)
        model, step, schema = self.schemas()[-1]
        if self.hang is not None and self.hang(model, step, schema):
            raise TimeoutError("slow")
        refused = (
            self.refuse(model, step, schema)
            if callable(self.refuse)
            else (model, step) in self.refuse
        )
        if refused:
            return Response(400, self.refusal)
        usage = {"prompt_tokens": 900, "completion_tokens": 16, "cost": float(CHECK_COST)}
        return ok('{"sch', model=model, finish_reason="length", usage=usage)


def check_argv(
    rig: Rig, *words: str, batch: str | None = "s1", cap: str | None = None
) -> list[str]:
    out = [
        "schema-check",
        "--settings",
        str(rig.settings),
        "--catalog",
        str(FIXTURES / "models-subset.json"),
        "--report-directory",
        str(rig.reports),
        *words,
    ]
    out += ["--batch-id", batch] if batch else []
    return out + (["--cap", cap] if cap else [])


def check_rows(text: str) -> dict[tuple[str, str], list[str]]:
    """Rows of the plain `## Results` table only."""
    results = text.split("## Bisect", 1)[0]
    rows = step_lines(results, "openai/") + step_lines(results, "z-ai/")
    return {(row[0], row[1]): row for row in rows}


def test_schema_check_sends_one_minimal_strict_call_per_model_and_step_and_reports_each(
    rig: Rig,
) -> None:
    journal = rig.store.read().content_hash()
    responder = SchemaResponder({(LUNA, "source_context")})
    steps = "source_readiness,source_context"
    assert rig.run(check_argv(rig, "--models", f"{LUNA},{GLM}", "--steps", steps), responder) == 0
    bodies = [json.loads(item.body or b"{}") for item in responder.requests]
    sent = [(b["model"], b["response_format"]["json_schema"]["name"]) for b in bodies]
    assert sent == [(m, s) for m in (LUNA, GLM) for s in ("source_readiness", "source_context")]
    for body in bodies:
        assert body["max_tokens"] == 16 and "reasoning" not in body
        assert [message["role"] for message in body["messages"]] == ["user"]
        assert body["provider"] == {"allow_fallbacks": False, "require_parameters": True}
        fmt = body["response_format"]["json_schema"]
        assert fmt["strict"] is True
        assert fmt["schema"] == strict_schema(cli.STEPS[fmt["name"]].schema)  # as a probe sends
    assert len(responder.key_requests) == 2  # account usage before and after, for reconcile
    text = rig.report("s1")
    rows = check_rows(text)
    refused = rows[(LUNA, "source_context")]
    assert refused[2:6] == ["http_error", "http_error", "400", "0"]  # known-zero: refused
    assert refused[10] == "yes: schema rejection"
    assert refused[9].startswith("$defs, $ref, additionalProperties, anyOf, enum, format, items")
    assert refused[11] == (
        "HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for "
        "response_format 'source_context'. Please ensure it is a valid JSON Schema."
    )
    others = [rows[key] for key in rows if key != (LUNA, "source_context")]
    assert [row[2:6] for row in others] == [["accepted", "truncated", "200", "0.0000123"]] * 3
    assert rows[(GLM, "source_context")][8] == (
        "nullable-enum, const-to-enum, drop-length, nullable-array-anyof"
    )
    readiness = rows[(GLM, "source_readiness")]
    assert readiness[8] == "none" and readiness[10:] == ["-", "-"]
    # The Keywords column: every JSON-Schema keyword of the sent schema, annotations left out.
    assert readiness[9] == (
        "$defs, $ref, additionalProperties, anyOf, enum, items, minItems, "
        "properties, required, type; depth 6 (3 objects), 37 properties"
    )
    digest = hashlib.sha256(schema_text(cli.STEPS["source_context"].schema).encode()).hexdigest()
    assert refused[7] == digest
    assert "- Accepted: 3; http_error: 1; other: 0; ineligible: 0" in text
    for forbidden in (FAKE_KEY, '{"sch', "messages", "user_REDACTED"):
        assert forbidden not in text
    state = ledger(rig, "s1").state()
    assert state.cap == Decimal("0.05") and state.reserved == Decimal(0)
    assert state.spent == 3 * CHECK_COST and len(state.attempts) == 4
    evidence = rig.root / "artifacts" / "model-tests" / "s1" / "schema-check"
    manifests = {
        (m["model"], m["step_id"]): m
        for m in (json.loads(p.read_text()) for p in sorted(evidence.rglob("manifest.json")))
    }
    assert len(manifests) == 4
    record = manifests[(LUNA, "source_context")]
    assert record["schema"] == "schema-check-attempt/1" and record["status"] == "http_error"
    assert record["http_status"] == 400 and record["hashes"]["schema_sha256"] == digest
    assert record["schema_relaxations"] == [
        "nullable-enum",
        "const-to-enum",
        "drop-length",
        "nullable-array-anyof",
    ]
    assert record["journal"] == "none: schema-check submits nothing"
    # Nothing was submitted: no journal copy, the execution journal is unchanged.
    assert not (rig.store.directory / "live").exists()
    assert rig.store.read().content_hash() == journal


def test_schema_check_cap_refusal_sends_nothing_and_stops_the_batch(rig: Rig) -> None:
    responder = SchemaResponder(set())
    argv = check_argv(rig, "--models", LUNA, "--steps", "source_context", cap="0.0000001")
    assert rig.run(argv, responder) == cli.EXIT_CAP
    assert responder.requests == []
    text = rig.report("s1")
    assert "- Stopped: cap: " in text
    (row,) = step_lines(text, "openai/")
    assert row[2:4] == ["refused", "not sent"] and row[5] == "not dispatched"
    (manifest,) = (rig.root / "artifacts" / "model-tests" / "s1").rglob("manifest.json")
    assert json.loads(manifest.read_text())["status"] == "refused"
    path = rig.root / "artifacts" / "model-tests" / ".ledgers" / "s1.jsonl"
    assert Ledger(path, Decimal("0.0000001")).state().attempts == ()  # nothing was reserved


def test_schema_check_defaults_and_refusals(
    rig: Rig, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A fixed clock, so the two default-batch runs below cannot straddle a UTC midnight.
    monkeypatch.setattr(cli, "utc_stamp", lambda: "2026-10-22T23:59:59Z")
    parser = argparse.ArgumentParser()
    cli.configure(parser)
    args = parser.parse_args(["schema-check", "--models", LUNA])
    assert args.cap == Decimal("0.05") and args.steps == tuple(cli.STEPS)
    for bad in ("source_context,source_context", "nope", ""):
        with pytest.raises(SystemExit):
            parser.parse_args(["schema-check", "--models", LUNA, "--steps", bad])
    responder = SchemaResponder(set())
    # An effort cannot be honoured: schema-check sends no reasoning parameter.
    assert rig.run(check_argv(rig, "--models", f"{LUNA}@high"), responder) == cli.EXIT_FAILED
    assert "schema-check sends no reasoning" in capsys.readouterr().out
    assert responder.requests == [] and responder.key_requests == []
    argv = check_argv(rig, "--models", LUNA, "--steps", "financials", batch=None)
    assert rig.run(argv, responder) == 0
    (report,) = rig.reports.glob("live-schema-*.md")
    assert report.name == "live-schema-20261022.md"
    assert rig.run(argv, responder) == cli.EXIT_FAILED  # the day's batch exists: choose another


def test_schema_check_records_an_ineligible_model_without_sending(rig: Rig) -> None:
    responder = SchemaResponder(set())
    catalog = four_models(rig, **{SOL: {"parameters": FULL[:-1]}})  # no structured_outputs
    argv = [*check_argv(rig, "--models", f"{SOL},{DEEP}", "--steps", "source_context"), *catalog]
    assert rig.run(argv, responder) == 0
    assert [json.loads(r.body or b"{}")["model"] for r in responder.requests] == [DEEP]
    text = rig.report("s1")
    (row,) = step_lines(text, "openai/")
    assert row[2:4] == ["ineligible", "missing parameters: structured_outputs"]
    assert "ineligible: 1" in text


def test_a_recorded_schema_rejection_makes_that_step_ineligible_before_dispatch(
    rig: Rig,
) -> None:
    refusing = SchemaResponder({(LUNA, "source_context")})
    assert rig.run(check_argv(rig, "--models", LUNA, "--steps", "source_context"), refusing) == 0
    responder = Responder(rig.review)
    assert rig.run([*rig.argv("module", "--module", "CP-1"), "--models", LUNA], responder) == 0
    assert len(responder.requests) == 1  # CP-0 only; source_context was never sent
    cp0, context = step_lines(rig.report(), "module-00")
    assert cp0[2] == "source_readiness" and cp0[6] == "accepted"
    assert context[2] == "source_context" and context[6] == "ineligible"
    assert context[7] == "ineligible: schema rejected by provider (s1)"
    assert context[8] == "0"  # nothing reserved, nothing spent


def test_a_400_that_does_not_name_the_schema_is_reported_and_never_blocks(rig: Rig) -> None:
    """Review fix (2.11 round 1): schema-check sends max_tokens 16 and no reasoning, which a
    real run does not, so a 400 about those must not block the paid path."""
    floor = {"error": {"code": 400, "message": "max_tokens must be at least 32"}}
    refusing = SchemaResponder({(LUNA, "source_context")}, refusal=json.dumps(floor).encode())
    assert rig.run(check_argv(rig, "--models", LUNA, "--steps", "source_context"), refusing) == 0
    (row,) = step_lines(rig.report("s1"), "openai/")
    assert row[2:5] == ["http_error", "http_error", "400"]
    assert row[10] == "no: the 400 does not name the schema"
    responder = Responder(rig.review)
    assert rig.run([*rig.argv("module", "--module", "CP-1"), "--models", LUNA], responder) == 0
    assert len(responder.requests) == 2  # CP-0, then source_context was sent
    _, context = step_lines(rig.report(), "module-00")[:2]
    assert context[2] == "source_context" and context[6] != "ineligible"


# --- 2.11 fix round 1: `schema-check --bisect` ------------------------------------------------


def bisect_rows(text: str) -> list[list[str]]:
    """Rows of the `## Bisect` table (model, step, variant, outcome, ...)."""
    section = text.split("## Bisect", 1)[1].split("## First accepted variant", 1)[0]
    return step_lines(section, "openai/")


def has_pattern(model: str, step: str, schema: dict[str, Any]) -> bool:
    return '"pattern"' in json.dumps(schema)


def test_bisect_stops_at_the_first_accepted_variant_and_never_feeds_a_real_run(rig: Rig) -> None:
    responder = SchemaResponder(has_pattern)
    argv = check_argv(rig, "--models", LUNA, "--steps", "narrative", "--bisect")
    assert rig.run(argv, responder) == 0
    sent = [schema for _, _, schema in responder.schemas()]
    plain = strict_schema(cli.STEPS["narrative"].schema)
    assert sent == [plain, bisect_variant("drop-pattern", plain)]  # then it stopped
    text = rig.report("s1")
    (plain_row,) = check_rows(text).values()
    assert plain_row[2:5] == ["http_error", "http_error", "400"]
    *unsent, row = bisect_rows(text)
    # Since round 3 the sent narrative schema has no oneOf and no format: nothing to rewrite.
    assert [r[2:4] for r in unsent] == [
        ["one-of-to-any-of", "not applicable"],
        ["drop-format", "not applicable"],
    ]
    assert row[1:6] == ["narrative", "drop-pattern", "accepted", "truncated", "200"]
    digest = hashlib.sha256(
        json.dumps(sent[1], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert row[8] == digest
    assert f"- {LUNA} narrative: first accepted variant: drop-pattern" in text
    assert "- Bisect: yes" in text
    root = rig.root / "artifacts" / "model-tests"
    (variant_manifest,) = (root / "s1" / "schema-bisect").rglob("manifest.json")
    record = json.loads(variant_manifest.read_text())
    assert record["schema"] == "schema-bisect-attempt/1" and record["variant"] == "drop-pattern"
    # Round-1 re-review: the relaxations named are the base schema's, and the record says so.
    plain_digest = hashlib.sha256(schema_text(cli.STEPS["narrative"].schema).encode()).hexdigest()
    assert record["variant_base_schema_sha256"] == plain_digest
    assert record["hashes"]["schema_sha256"] == digest
    assert record["schema_relaxations_of"] == "variant_base_schema_sha256"
    assert record["schema_shape"] == schema_shape(sent[1])
    # The variant's acceptance neither lifts nor adds a block: only the plain verdict counts.
    plain_digest = hashlib.sha256(schema_text(cli.STEPS["narrative"].schema).encode()).hexdigest()
    assert cli.schema_rejections(root) == {(LUNA, "narrative", plain_digest): "s1"}


def test_bisect_reports_none_accepted_and_skips_variants_that_change_nothing(rig: Rig) -> None:
    responder = SchemaResponder({(LUNA, "source_context")})
    argv = check_argv(rig, "--models", LUNA, "--steps", "source_context", "--bisect")
    assert rig.run(argv, responder) == 0
    text = rig.report("s1")
    rows = [(r[2], r[3]) for r in bisect_rows(text)]
    assert rows == [
        ("one-of-to-any-of", "not applicable"),
        ("drop-format", "http_error"),
        ("drop-pattern", "http_error"),
        ("drop-items-bounds", "http_error"),
        ("open-object", "not applicable"),
        ("any-of-null-to-type-union", "http_error"),
        ("split-mixed-types", "not applicable"),
        # Round 3 sends nullable arrays as `anyOf`: these two have nothing left to change.
        ("nullable-array-to-anyof", "not applicable"),
        ("nullable-array-required", "not applicable"),
        ("anyof-enum-null-to-type-union", "http_error"),
        ("strip-titles", "http_error"),
        ("inline-refs", "http_error"),
        ("all", "http_error"),
    ]
    assert len(responder.requests) == 9  # the plain check and eight variants
    assert f"- {LUNA} source_context: none accepted" in text


def test_the_touches_column_names_the_fields_that_dropping_null_changes(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Touches column on a base schema that still has `type: [array, null]` nodes (as
    before round 3): the bisect's base is swapped for the unrelaxed strict copy."""
    monkeypatch.setattr(cli, "strict_schema", strict_copy)
    responder = SchemaResponder({(LUNA, "source_context")})
    argv = check_argv(rig, "--models", LUNA, "--steps", "source_context", "--bisect")
    assert rig.run(argv, responder) == 0
    touches = {r[2]: r[10] for r in bisect_rows(rig.report("s1"))}
    fields = nullable_array_fields(strict_copy(cli.STEPS["source_context"].schema))
    assert "SourceContext.event_scan_citations" in fields and len(fields) == 8
    assert touches["nullable-array-required"] == ", ".join(fields)
    assert {value for name, value in touches.items() if name != "nullable-array-required"} == {"-"}


def test_a_cap_refusal_mid_bisect_stops_the_batch_and_says_the_bisect_did_not_finish(
    rig: Rig,
) -> None:
    def drop_format_hangs(model: str, step: str, schema: dict[str, Any]) -> bool:
        return '"format"' not in json.dumps(schema)  # the first variant sent: its call times out

    responder = SchemaResponder({(LUNA, "source_context")}, hang=drop_format_hangs)
    argv = check_argv(rig, "--models", LUNA, "--steps", "source_context", "--bisect", cap="0.0008")
    assert rig.run(argv, responder) == cli.EXIT_CAP
    assert len(responder.requests) == 2  # the plain check and drop-format, nothing after
    text = rig.report("s1")
    rows = [(r[2], r[3], r[4]) for r in bisect_rows(text)]
    assert rows == [
        ("one-of-to-any-of", "not applicable", "not sent"),
        ("drop-format", "other", "timeout"),
        ("drop-pattern", "refused", "not sent"),
    ]
    assert "- Stopped: cap: " in text
    assert f"- {LUNA} source_context: not finished (cap)" in text
    assert cli.HELD_FOOTNOTE in text  # the timed-out variant's reservation is held


def test_a_402_mid_bisect_stops_the_batch_and_still_writes_the_report(rig: Rig) -> None:
    """Round-1 re-review: credit exhaustion on a variant leaves the cell "not finished
    (aborted)" and the report is written (DC-8 exit)."""
    responder = SchemaResponder({(LUNA, "source_context")})

    def no_credit_after_the_plain_check(request: Request) -> Response:
        if request.url != KEY_URL and responder.requests:
            responder.requests.append(request)
            return Response(402, b'{"error":{"message":"no credit","code":402}}')
        return responder(request)

    argv = check_argv(rig, "--models", LUNA, "--steps", "source_context", "--bisect")
    assert rig.run(argv, no_credit_after_the_plain_check) == cli.EXIT_CREDIT
    assert len(responder.requests) == 2  # the plain check and drop-format, nothing after
    text = rig.report("s1")
    assert "- Stopped: aborted: CreditExhausted" in text
    assert f"- {LUNA} source_context: not finished (aborted)" in text


def test_a_variant_that_cannot_be_built_is_reported_and_not_sent(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cyclic `$ref` refuses `inline-refs` (and so `all`): the row says why, nothing is sent,
    and the bisect carries on."""
    real = cli.bisect_variant

    def cyclic(name: str, schema: dict[str, Any]) -> dict[str, Any]:
        if name in {"inline-refs", "all"}:
            raise VariantRefused("cyclic $ref: A -> B -> A")
        return real(name, schema)

    monkeypatch.setattr(cli, "bisect_variant", cyclic)
    responder = SchemaResponder({(LUNA, "readiness")})
    argv = check_argv(rig, "--models", LUNA, "--steps", "readiness", "--bisect")
    assert rig.run(argv, responder) == 0
    text = rig.report("s1")
    rows = {r[2]: (r[3], r[4]) for r in bisect_rows(text)}
    assert rows["inline-refs"] == rows["all"] == ("not sendable", "cyclic $ref: A -> B -> A")
    sent = [schema for _, _, schema in responder.schemas()]
    assert all('"$ref"' in json.dumps(schema) for schema in sent)  # no inlined variant went out
    assert f"- {LUNA} readiness: none accepted" in text
