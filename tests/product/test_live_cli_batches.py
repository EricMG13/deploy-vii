"""`deploy-vii live` subcommands over a fake transport: no network, key never an argument."""

import argparse
import hashlib
import json
import os
import socket
import stat
import tomllib
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from deploy_vii.cp1_workflow import (
    PROMOTED,
    FinancialStage,
    FinancialSubmission,
    write_cp1_envelope,
)
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview
from deploy_vii.execution import Attempt, Execution
from deploy_vii.live import cli
from deploy_vii.live.catalog import PinnedCandidate
from deploy_vii.live.client import CHAT_URL, KEY_URL, Request, Response
from deploy_vii.live.draw import draw
from deploy_vii.live.ledger import Ledger
from deploy_vii.live.prompts import QUALITY_BLOCK_ID, schema_text
from deploy_vii.live.schema import (
    VariantRefused,
    bisect_variant,
    nullable_array_fields,
    schema_shape,
    strict_copy,
    strict_schema,
)
from deploy_vii.live.settings import StepEffort
from deploy_vii.live.submission import quality_inputs
from deploy_vii.live.tools import ToolRules
from deploy_vii.readiness import ReadinessReview
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
from tests.product.test_business_context import submission_fixture
from tests.product.test_cp1_workflow import at_ceiling
from tests.product.test_execution import fixture_store, step_text
from tests.product.test_live_client import choice_error_body
from tests.product.test_live_credit import ACCOUNT, CREDIT_402, IN_FLIGHT_402
from tests.product.test_live_loop import tool_reply
from tests.product.test_live_runner import no_wait
from tests.product.test_narrative import populated
from tests.product.test_readiness import as_submission, readiness_fixture
from tests.product.test_workflow import cp1_case

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

    def run(
        self,
        argv: list[str],
        responder: cli.Transport,
        sleep: Callable[[float], None] = no_wait,
    ) -> int:
        parser = argparse.ArgumentParser()
        cli.configure(parser)
        return cli.execute(parser.parse_args(argv), transport=responder, sleep=sleep)

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
    assert rig.run(rig.argv("module", "--module", "CP-1B"), responder) == cli.EXIT_FAILED
    assert responder.requests == [] and not (rig.reports / "live-b1.md").exists()


class StepResponder(Responder):
    """Answers each chat call with the content for its step (the response_format name)."""

    def __init__(self, contents: dict[str, str]) -> None:
        super().__init__("")
        self.contents = contents

    def __call__(self, request: Request) -> Response:
        if request.url != KEY_URL:
            step = json.loads(request.body or b"{}")["response_format"]["json_schema"]["name"]
            self.content = self.contents[step]
        return super().__call__(request)


def test_module_cp1a_runs_cp0_then_its_one_step(rig: Rig) -> None:
    """Task 7.2: `module --module CP-1A` (or its alias CP-2C) is CP-0, then business_context."""
    contents = {
        "source_readiness": rig.review,
        "business_context": submission_fixture().model_dump_json(),
    }
    responder = StepResponder(contents)
    assert rig.run(rig.argv("module", "--module", "CP-2C"), responder) == 0
    rows = step_lines(rig.report(), "module-00")
    assert [(r[1], r[2], r[6]) for r in rows] == [
        ("cp-1a", "source_readiness", "accepted"),
        ("cp-1a", "business_context", "accepted"),
    ]
    assert len(responder.requests) == 2


def test_module_cp1a_records_a_cp0_that_does_not_authorise_it(rig: Rig) -> None:
    document = json.loads(rig.review)
    for consumer in document["consumers"]:
        if consumer["module_id"] == "CP-1A":
            consumer["readiness"] = "CONDITIONAL"
            consumer["missing_source"] = "Ownership filings"
    responder = StepResponder({"source_readiness": json.dumps(document)})
    assert rig.run(rig.argv("module", "--module", "CP-1A"), responder) == 0
    rows = step_lines(rig.report(), "module-00")
    assert [(r[2], r[6]) for r in rows] == [
        ("source_readiness", "accepted"),
        ("business_context", "not-authorized"),
    ]
    assert len(responder.requests) == 1  # nothing was sent for CP-1A


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
    cells = [r[1] for r in step_lines(rig.report("r1"), "cp") if r[2] == "source_readiness"]
    # Task 8.6: cp1a and the four new cases have no recorded corpus entry for their settling
    # step, so they are named as skipped, never run and never counted as a pass.
    assert cells == ["cp0"] * 3 + ["cp1"] * 3
    assert cli.skipped_line(cli.unrecorded_cases()) in rig.report("r1").splitlines()


def test_a_skipped_case_moves_no_other_cases_model_order_but_does_move_its_seeds() -> None:
    """Task 8.7 (8.6 review): every case draws its shuffle, so skipping one leaves every other
    case's model order as it is with nothing skipped; seeds are drawn over the planned cells
    only, so a later case's seeds shift, while each seed still draws its cell's model."""
    pool = fixture_pool()
    slugs = [item.slug for item in pool.eligible]
    every = frozenset(steps[-1] for _, steps in cli.REGRESSION_CASES)
    whole = cli._regression_cells(pool, slugs, 7, every)
    some = cli._regression_cells(pool, slugs, 7, every - {"business_context"})  # cp1a skipped

    def models(cells: list[cli.Cell]) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for cell in cells:
            assert cell.seed is not None
            found.setdefault(cell.case_id, []).append(draw(pool, cell.seed).slug)
        return found

    assert "cp1a" in models(whole) and "cp1a" not in models(some)
    assert models(some) == {k: v for k, v in models(whole).items() if k != "cp1a"}
    seeds = {c.cell_id: c.seed for c in whole}
    assert [c.seed for c in some if c.case_id == "cp1"] == [
        seeds[c.cell_id] for c in some if c.case_id == "cp1"
    ]
    assert [c.seed for c in some if c.case_id == "cp2"] != [
        seeds[c.cell_id] for c in some if c.case_id == "cp2"
    ]


def test_the_report_names_the_cases_skipped_at_planning_time(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task 8.7 (8.6 review): a corpus entry written while the batch runs (another process)
    does not drop a case from the skipped line: the report names what was planned."""
    real = cli.recorded_steps()
    calls: list[int] = []

    def recorded(*_: object) -> frozenset[str]:
        calls.append(1)
        return real if len(calls) == 1 else real | {"credit_synthesis"}

    monkeypatch.setattr(cli, "recorded_steps", recorded)
    assert rig.run(rig.argv("regression", batch="r1"), Responder(rig.review)) == 0
    planned = cli.unrecorded_cases(real)
    assert ("cp2", "credit_synthesis") in planned
    assert cli.skipped_line(planned) in rig.report("r1").splitlines()
    assert not step_lines(rig.report("r1"), "cp2-")


def test_the_regression_cases_are_cp0_cp1_then_the_cp1a_chain() -> None:
    assert cli.REGRESSION_CASES[:3] == (
        ("cp0", cli.CP0_STEPS),
        ("cp1", cli.FULL_CHAIN),
        ("cp1a", cli.CP1A_CHAIN),
    )
    # Task 8.6: then each new module's cell, in registry order.
    assert [case for case, _ in cli.REGRESSION_CASES[3:]] == ["cp2", "cp4", "cp3", "cp5", "cp6"]
    assert cli.CP1A_CHAIN[-1] == "business_context" and cli.CP1A_CHAIN[:-1] == cli.CP0_STEPS
    # Task 7.4: the CP-1 chain ends in the QA review whose acceptance promotes CP-1.
    assert cli.CP1_CHAIN == ("source_context", "financials", "narrative", "readiness", "quality")
    assert cli.FULL_CHAIN == (*cli.CP0_STEPS, *cli.CP1_CHAIN)


def test_the_cp1_module_and_regression_cells_plan_five_cp1_steps() -> None:
    (module,) = cli._module_cells("CP-1", 7)
    assert module.steps == cli.FULL_CHAIN and module.steps[1:] == cli.CP1_CHAIN
    pool = fixture_pool()
    cells = cli._regression_cells(pool, [item.slug for item in pool.eligible], 7)
    planned = {cell.case_id: cell.steps for cell in cells}
    assert planned["cp1"] == ("source_readiness", *cli.CP1_CHAIN)
    assert planned["cp1"][-1] == "quality" and len(planned["cp1"]) == 6
    assert planned["cp0"] == cli.CP0_STEPS and "cp1a" not in planned  # no corpus entry (8.6)


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
    if os.geteuid() == 0:
        pytest.skip("chmod cannot deny root; the write-failure path needs an unprivileged user")

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


def refuses_after_first(served: Responder, *bodies: bytes) -> Callable[[Request], Response]:
    """Answer the first chat call, then each of `bodies` as a 402, then answer again."""
    queue = list(bodies)

    def transport(request: Request) -> Response:
        if served.requests and request.url != KEY_URL and queue:
            served.requests.append(request)
            return Response(402, queue.pop(0))
        return served(request)

    return transport


def test_an_in_flight_402_mid_batch_waits_and_retries_and_both_attempts_are_reported(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    """Task 7.8 (batch e1-cp1-8): the in-flight refusal no longer aborts the batch."""
    served = Responder(rig.review)
    waits: list[float] = []
    code = rig.run(rig.argv("canary"), refuses_after_first(served, IN_FLIGHT_402), waits.append)
    assert code == 0 and waits == [120]
    rows = step_lines(rig.report(), "canary-")
    assert rows[0][6:8] == ["accepted", "ok"]
    assert rows[1][6:9] == ["no-response", "insufficient_credit", "0"]
    assert rows[2][7] == "ok"  # the re-send got a model answer (the validator's verdict aside)
    assert rows[1][5] != rows[2][5] and rows[1][2] == rows[2][2]  # same step, a new attempt
    assert len(rows) == len(served.requests)  # every chat call has its row
    assert "- Stopped: no" in rig.report()
    assert ACCOUNT not in capsys.readouterr().out


def test_a_second_in_flight_402_aborts_naming_both_attempts(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    served = Responder(rig.review)
    waits: list[float] = []
    transport = refuses_after_first(served, IN_FLIGHT_402, IN_FLIGHT_402)
    code = rig.run(rig.argv("canary"), transport, waits.append)
    out = capsys.readouterr().out
    assert code == cli.EXIT_CREDIT == 4 and waits == [120]
    assert "reason in_flight_budget_exhausted" in out and "again after one retry of" in out
    assert "ticket pending; coordinator decision (DC-8)" in out
    stopped = next(line for line in rig.report().splitlines() if line.startswith("- Stopped:"))
    assert stopped.startswith("- Stopped: aborted: CreditExhausted (reason in_flight_budget")
    assert len(served.requests) == 3
    # The first refusal has its row; the raising re-send is named on the abort line.
    rows = step_lines(rig.report(), "canary-")
    assert [row[6:8] for row in rows] == [
        ["accepted", "ok"],
        ["no-response", "insufficient_credit"],
    ]
    assert rows[1][5] in out


def first_refused_row(rig: Rig) -> list[str]:
    rows = step_lines(rig.report(), "canary-")
    assert len(rows) == 2 and rows[0][6] == "accepted"
    assert rows[1][6:9] == ["no-response", "insufficient_credit", "0"]
    return rows[1]


def test_a_cap_refusal_on_the_re_send_still_reports_the_refused_attempt(rig: Rig) -> None:
    """Fix round 1 (F1): the refused attempt is reported even when the re-send raises."""
    served = Responder(rig.review)
    ledger_path = rig.root / "artifacts" / "model-tests" / ".ledgers" / "b1.jsonl"

    def elsewhere_takes_the_cap(seconds: float) -> None:
        # Something outside this batch reserves what is left while the runner waits.
        ledger = cli.open_ledger(ledger_path)
        ledger.reserve("outside-this-batch", ledger.state().remaining)

    code = rig.run(
        rig.argv("canary"), refuses_after_first(served, IN_FLIGHT_402), elsewhere_takes_the_cap
    )
    assert code == cli.EXIT_CAP and len(served.requests) == 2  # the re-send was never sent
    first_refused_row(rig)
    assert "- Stopped: cap: " in rig.report()


def test_a_transport_error_on_the_re_send_still_reports_the_refused_attempt(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    served = Responder(rig.review)
    refusals = refuses_after_first(served, IN_FLIGHT_402)

    def then_the_connection_drops(request: Request) -> Response:
        if request.url != KEY_URL and len(served.requests) == 2:
            served.requests.append(request)
            raise ConnectionError("reset")
        return refusals(request)

    waits: list[float] = []
    code = rig.run(rig.argv("canary"), then_the_connection_drops, waits.append)
    assert code == cli.EXIT_FAILED and waits == [120] and len(served.requests) == 3
    first_refused_row(rig)
    assert "- Stopped: aborted: TransportError" in rig.report()
    assert "TransportError" in capsys.readouterr().out


def test_a_credit_402_aborts_with_the_affordable_budget_on_both_lines(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    """Task 7.8 (batch e1-cp1-9): the owner sees what the balance can afford."""
    served = Responder(rig.review)
    code = rig.run(rig.argv("canary"), refuses_after_first(served, CREDIT_402))
    out = capsys.readouterr().out
    assert code == cli.EXIT_CREDIT
    budget = "reason openrouter_credits; requested max_tokens 128000, affordable 91075"
    assert budget in out and ACCOUNT not in out
    assert f"- Stopped: aborted: CreditExhausted ({budget}; HTTP 402)" in rig.report()


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


def test_the_one_model_catalog_rule_pool_runs_sol_at_medium_with_a_trivial_draw(
    rig: Rig,
) -> None:
    """Decision 0005 amendment: the project's pool (settings/project.toml) is Sol alone, at the
    project's default effort, `medium` since the 24 Oct 2026 amendment (task 7.15 item 8)."""
    project = (Path("settings") / "project.toml").read_text(encoding="utf-8")
    block = project[project.index("[[model_tests.candidates]]") : project.index("[frontend]")]
    effort = tomllib.loads(project)["model_tests"]["default_effort"]
    template = SETTINGS.format(key=rig.key).replace(
        'default_effort = "high"', f'default_effort = "{effort}"'
    )
    assert f'default_effort = "{effort}"' in template
    start, end = template.index("[[model_tests.candidates]]"), template.index("[ci]")
    rig.settings.write_text(template[:start] + block + template[end:], encoding="utf-8")
    catalog = rig.root / "sol.json"
    sol = catalog_row(SOL, efforts=("max", "xhigh", "high", "medium", "low"))
    catalog.write_text(json.dumps({"data": [sol]}), encoding="utf-8")
    responder = Responder(rig.review)
    argv = [*rig.argv("module", "--module", "CP-0"), "--catalog", str(catalog)]
    assert rig.run(argv, responder) == 0
    assert {b["model"] for b in chat_bodies(responder)} == {SOL}
    assert {json.dumps(b["reasoning"]) for b in chat_bodies(responder)} == {'{"effort": "medium"}'}
    text = rig.report()
    assert "- Pool: catalog rule" in text
    pool_section = text.split("## Pool", 1)[1].split("## Steps", 1)[0]
    (row,) = step_lines(pool_section, "openai/")
    assert row[0] == SOL and row[1] == "yes" and row[3:5] == ["medium (default)", "medium"]
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
        assert refused[5:11] == ["none", "not-authorized", "ok", "0", "0", "-"]
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


def _deadlines(rig: Rig, batch: str) -> set[tuple[float, float]]:
    manifests = list((rig.root / "artifacts" / "model-tests" / batch).rglob("manifest.json"))
    assert manifests
    budgets = [json.loads(m.read_text())["budgets"] for m in manifests]
    return {(b["timeout_s"], b["deadline_s"]) for b in budgets}


def test_timeout_reaches_every_request_manifest_and_the_report_header(rig: Rig) -> None:
    """Task 7.0c: the request deadline is per call, every model; the default stays 600 s."""
    argv = [*rig.argv("probe"), *four_models(rig), "--models", FOUR, "--timeout", "1800"]
    assert rig.run(argv, Responder(rig.review)) == 0
    assert _deadlines(rig, "b1") == {(1800.0, 1800.0)}
    assert "- Timeout: 1800.0 s per call (every model)" in rig.report()
    argv = [*rig.argv("probe", batch="b2"), *four_models(rig), "--models", FOUR]
    assert rig.run(argv, Responder(rig.review)) == 0
    assert _deadlines(rig, "b2") == {(600.0, 600.0)}
    assert "- Timeout: 600.0 s per call (every model)" in rig.report("b2")


def test_exponent_notation_timeout_is_accepted_and_reaches_the_manifests(rig: Rig) -> None:
    argv = [*rig.argv("probe"), *four_models(rig), "--models", FOUR, "--timeout", "1e3"]
    assert rig.run(argv, Responder(rig.review)) == 0
    assert _deadlines(rig, "b1") == {(1000.0, 1000.0)}


@pytest.mark.parametrize("value", ["0", "-5", "nan", "inf", "-inf", "slow"])
def test_a_bad_timeout_is_refused_by_the_parser(value: str, rig: Rig) -> None:
    parser = argparse.ArgumentParser()
    cli.configure(parser)
    for word in (["probe"], ["module", "--module", "CP-0"], ["regression"], ["canary"]):
        assert parser.parse_args([*word, "--cap", "1", "--directory", "d"]).timeout == 600.0
        with pytest.raises(SystemExit) as refused:
            parser.parse_args([*word, "--cap", "1", "--directory", "d", "--timeout", value])
        assert refused.value.code == 2
    with pytest.raises(SystemExit):
        parser.parse_args([*rig.argv("probe"), "--timeout", value])
    assert not (rig.root / "artifacts" / "model-tests" / ".ledgers").exists()
    assert not list(rig.reports.glob("live-*.md"))


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
    # Task 7.0: nothing to look up, but it is the only hold and the account usage moved by
    # exactly the other two attempts' costs, so the deadline call is adjusted to 0.
    reserved_after, spent_after, attempts_after = ledger_state()
    assert reserved_after == 0 and spent_after == Decimal("0.00066")
    assert [a for a in attempts_after if a[0] == held[0]] == [(held[0], Decimal(0), Decimal(0))]
    (record,) = [a for a in ledger(rig).state().attempts if a.attempt_id == held[0]]
    assert record.adjustment is not None and record.adjustment.source == "account-usage-delta"
    reconciled = (rig.reports / "live-b1-reconciled.md").read_text(encoding="utf-8")
    statuses = sorted(r[6] for r in step_lines(reconciled, "probe-"))
    assert statuses == sorted(
        ["no-response", "ineligible", "accepted", "accepted", "not-authorized", "not-authorized"]
    )
    (outcome,) = [
        line for line in reconciled.splitlines() if held[0] in line and "reconciled |" in line
    ]
    assert "no generation id; account usage moved 0.00066" in outcome
    assert "Looked up this run: 1; reconciled 1, unresolved 0" in reconciled


def ledger(rig: Rig, batch: str = "b1") -> Ledger:
    return cli.open_ledger(rig.root / "artifacts" / "model-tests" / ".ledgers" / f"{batch}.jsonl")


# --- 7.0: report tables -----------------------------------------------------------------------


def test_a_cell_without_model_output_is_counted_as_no_response_never_as_a_rejection(
    rig: Rig,
) -> None:
    """Probe-5 analysis: the cohort table had no column for no-response outcomes. Luna's call
    passes its deadline (held), GLM's provider fails inside a 200 (5xx-in-200), DeepSeek returns
    a payload the validator rejects; only DeepSeek's cell is a rejection."""
    served = Responder("{}")

    def transport(request: Request) -> Response:
        if request.url == KEY_URL:
            return served(request)
        model = json.loads(request.body or b"{}")["model"]
        served.requests.append(request)
        if model == LUNA:
            raise TimeoutError(f"wall-clock deadline of {request.timeout_s} s exceeded")
        if model == GLM:
            return Response(200, choice_error_body(error={"code": 502, "message": "Upstream"}))
        return ok("{}", model=model)

    assert rig.run(rig.argv("probe"), transport) == 0
    text = rig.report()
    rows = {r[3]: r for r in step_lines(text, "probe-")}
    assert rows[LUNA][6:8] == ["no-response", "timeout"] and rows[LUNA][8].startswith("reservation")
    assert rows[GLM][6:8] == ["no-response", "http_error"]
    assert rows[LUNA][9] == rows[GLM][9] == "-"  # no payload reached the validator
    assert rows[DEEPSEEK][6] == "rejected" and int(rows[DEEPSEEK][9]) > 0
    cohorts = text.split("## Cohorts", 1)[1]
    assert "| Cohort | Attempts | Accepted | Rejected | No response | Pooled | Qualification |" in (
        cohorts
    )
    (pool,) = step_lines(cohorts, "openrouter-pool")
    assert pool[1:5] == ["3", "0", "1", "2"]


def test_the_pool_table_prints_the_prompt_token_bound_beside_the_reservation(rig: Rig) -> None:
    assert rig.run(rig.argv("module", "--module", "CP-0"), Responder(rig.review)) == 0
    text = rig.report()
    pool_section = text.split("## Pool", 1)[1].split("## Steps", 1)[0]
    assert (
        "| Model | Eligible | Reason | Requested effort | Effort sent | Prompt token bound "
        "(largest) | Reserved USD per attempt (largest) |" in pool_section
    )
    (manifest,) = (rig.root / "artifacts" / "model-tests" / "b1").rglob("manifest.json")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    metrics = json.loads((manifest.parent / "metrics.json").read_text(encoding="utf-8"))
    bound = metrics["estimate"]["prompt_tokens_upper_bound"]
    assert isinstance(bound, int) and bound > 0
    drawn = [r for r in step_lines(pool_section, "") if r[0] == record["model"]]
    (row,) = drawn
    assert row[5] == str(bound) and Decimal(row[6]) == Decimal(record["budgets"]["reserved_usd"])
    undrawn = [r for r in step_lines(pool_section, "") if r[0] not in {record["model"], "Model"}]
    assert undrawn and all(r[5] == "-" for r in undrawn if r[0] != "---")


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
        "nullable-enum, const-to-enum, drop-length, nullable-array-anyof, drop-prefilled"
    )  # task 7.0i: pack_sha256 and every citation's source_sha256 are filled by Python
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
        "drop-prefilled",
    ]
    assert record["journal"] == "none: schema-check submits nothing"
    # Nothing was submitted: no journal copy, the execution journal is unchanged.
    assert not (rig.store.directory / "live").exists()
    assert rig.store.read().content_hash() == journal


DETAIL_ACCOUNT = "u-account-77"


@pytest.mark.parametrize(
    "raw",
    [
        f"upstream refused: user_id={DETAIL_ACCOUNT}",  # not JSON: copied as it is
        json.dumps({"error": {"type": "invalid_request_error", "user_id": DETAIL_ACCOUNT}}),
    ],
    ids=["not-json", "escaped-key"],
)
def test_schema_check_withholds_a_provider_detail_that_names_the_account_id(
    rig: Rig, raw: str
) -> None:
    """Task 7.15 item 4, end to end: `error.metadata.raw` with a surviving `user_id` never
    reaches `checks/classification.json`, the manifest or the report's `Provider detail`; the
    fixed note stands in for the whole detail and the body is withheld (task 7.11 item 6)."""
    error = {"code": 400, "message": "Provider returned error", "metadata": {"raw": raw}}
    body = json.dumps({"error": error}).encode()
    assert DETAIL_ACCOUNT.encode() in body and (b"user_id=" in body or b'\\"user_id\\"' in body)
    responder = SchemaResponder({(LUNA, "source_context")}, refusal=body)
    argv = check_argv(rig, "--models", LUNA, "--steps", "source_context")
    assert rig.run(argv, responder) == 0
    note = "<provider detail withheld: account id>"
    text = rig.report("s1")
    row = check_rows(text)[(LUNA, "source_context")]
    assert row[2:5] == ["http_error", "http_error", "400"] and row[11] == note
    evidence = rig.root / "artifacts" / "model-tests" / "s1" / "schema-check"
    (manifest,) = evidence.rglob("manifest.json")
    directory = manifest.parent
    classification = json.loads((directory / "checks" / "classification.json").read_text())
    assert classification["error_detail"] == note
    assert json.loads((directory / "manifest.json").read_text())["error_detail"] == note
    assert json.loads((directory / "response.json").read_text())["body_text"] is None
    for path in [*directory.rglob("*"), *rig.reports.rglob("*")]:
        if path.is_file():
            assert DETAIL_ACCOUNT not in path.read_text(encoding="utf-8", errors="replace"), path


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
    # CP-0, source_context and its step repair (task 7.0g), then the MC-7 repair attempt's
    # source_context and its step repair: the responder answers every step with a CP-0 review.
    assert len(responder.requests) == 5
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


# --- 7.0e: the module driver dispatches the one MC-7 repair -----------------------------------

# The Steps table's last column: `-` a first try of the first attempt, `step` the step's repair
# within that attempt (task 7.0g), `1` the MC-7 repair attempt and `1+step` a step repair in it.
REPAIR_COLUMN = 10
BAD = "not json"
OUTAGE = "outage"
TRUNC = "truncated"  # a completion cut at the --max-tokens budget (finish_reason length)
UPGRADE = "upgrade"  # a QA review that lifts one lineage above its ceiling (task 7.4)
CRITICAL = "critical"  # a QA review with one open CRITICAL finding: QA Blocked (fix round 1)
CHAIN = ("source_readiness", "source_context", "financials", "narrative", "readiness", "quality")


class Chain:
    """Fake transport for one CP-1 `module` cell. `script` lists, per chat call in order, the
    step the cell must ask for and whether to answer it validly, with `BAD` (a payload the
    validator rejects), `UPGRADE` (for `quality`: one lineage above its ceiling), `CRITICAL`
    (for `quality`: an open CRITICAL finding, so QA is Blocked) or `OUTAGE` (HTTP 500: no model
    output). Each valid payload is built from the cell's own journal, so a
    step is accepted exactly as the validators would."""

    def __init__(
        self,
        rig: Rig,
        extraction: FinancialSubmission,
        script: list[tuple[str, str]],
        usage: str = "1.5",
    ) -> None:
        self.rig, self.extraction, self.script = rig, extraction, script
        base = rig.store.read().attempts[-1]  # the case's CP-1 attempt: its source_context step
        self.context = rig.store.payload(base.steps[0].payload_sha256)
        self.requests: list[Request] = []
        self.usage = Decimal(usage)
        self.cell = "module-00"  # the cell journal the valid payloads are built from

    def payload(self, step: str) -> str:
        journal = Execution(self.rig.store.directory / "live" / "b1" / self.cell)
        valid = {s.step_id: s for s in journal.read().attempts[-1].steps if s.status == "valid"}
        if step == "source_readiness":
            return self.rig.review
        if step == "source_context":
            return self.context
        if step == "financials":
            context_hash = valid["source_context"].content_hash()
            return self.extraction.model_copy(
                update={"context_step_sha256": context_hash}
            ).model_dump_json()
        if step == "narrative":
            stage = FinancialStage.model_validate_json(step_text(journal, valid["financials"]))
            return populated(stage.narrative_inputs).model_dump_json()
        if step == "readiness":
            inputs = DownstreamInputs.model_validate_json(step_text(journal, valid["narrative"]))
            return DownstreamReview(inputs_sha256=inputs.content_hash()).model_dump_json()
        assert step == "quality", step
        # What a model returns: the at-ceiling review without the binding Python fills.
        ticket = journal.read().attempts[-1].ticket_id
        review = json.loads(at_ceiling(quality_inputs(journal, ticket)).model_dump_json())
        del review["inputs_sha256"]
        return json.dumps(review)

    def upgraded(self) -> str:
        """The quality review with its first Calculated lineage lifted to Directly Sourced."""
        review = json.loads(self.payload("quality"))
        evidence = review["claims"][0]["evidence"]
        lifted = next(e for e in evidence if e["lineage_class"] == "Calculated")
        lifted["lineage_class"] = "Directly Sourced"
        return json.dumps(review)

    def critical(self) -> str:
        """The quality review with one open CRITICAL finding (its arithmetic blocks QA)."""
        review = json.loads(self.payload("quality"))
        review["findings"] = [
            {
                "finding_id": "qa.synthetic-critical",
                "severity": "CRITICAL",
                "status": "open",
                "description": "Synthetic critical defect",
                "references": [],
                "resolution": None,
            }
        ]
        return json.dumps(review)

    def __call__(self, request: Request) -> Response:
        if request.url == KEY_URL:
            return key_status(format(self.usage, "f"))
        step, verdict = self.script[len(self.requests)]  # a call beyond the script fails loudly
        self.requests.append(request)
        self.usage += Decimal("0.00033")
        if verdict == OUTAGE:
            return Response(500, b"upstream down")
        model = json.loads(request.body or b"{}")["model"]
        if verdict == TRUNC:
            return ok('{"sch', model=model, finish_reason="length")
        if verdict == UPGRADE:
            return ok(self.upgraded(), model=model)
        if verdict == CRITICAL:
            return ok(self.critical(), model=model)
        return ok(BAD if verdict == BAD else self.payload(step), model=model)

    def user_prompts(self) -> list[str]:
        return [json.loads(r.body or b"{}")["messages"][1]["content"] for r in self.requests]


def chain_rig(tmp_path: Path) -> tuple[Rig, FinancialSubmission]:
    """A rig whose pack is the CP-1 case that passes every validator (fake transport only)."""
    (tmp_path / "rig").mkdir(parents=True)
    rig = Rig(tmp_path / "rig")
    # The synthetic CP-1 case is large (its narrative step is not context-eligible at the
    # production 3 bytes per token bound); this changes only the ineligibility test, not a request.
    rig.settings.write_text(
        SETTINGS.format(key=rig.key).replace("lower_bound = 3.0", "lower_bound = 300.0"),
        encoding="utf-8",
    )
    (tmp_path / "case").mkdir()
    store, _, extraction = cp1_case(tmp_path / "case")
    rig.store = store
    review = ReadinessReview.model_validate_json(
        store.payload(store.read().attempts[0].steps[0].payload_sha256)
    )
    rig.review = as_submission(review).model_dump_json()
    return rig, extraction


def ok_steps(*steps: str) -> list[tuple[str, str]]:
    return [(step, "ok") for step in steps]


def module_rows(rig: Rig) -> list[list[str]]:
    return step_lines(rig.report(), "module-00")


def retained_manifests(rig: Rig) -> list[dict[str, Any]]:
    batch = rig.root / "artifacts" / "model-tests" / "b1"
    return [json.loads(p.read_text(encoding="utf-8")) for p in batch.glob("*/*/*/manifest.json")]


def run_chain(
    tmp_path: Path, script: list[tuple[str, str]], cap: str = "5.00"
) -> tuple[Rig, Chain, int]:
    rig, extraction = chain_rig(tmp_path)
    chain = Chain(rig, extraction, script)
    return rig, chain, rig.run(rig.argv("module", "--module", "CP-1", cap=cap), chain)


def test_a_rejected_financials_step_is_repaired_within_its_attempt_and_the_cell_runs_on(
    tmp_path: Path,
) -> None:
    """Task 7.0g (a): the rejected step alone is re-sent with its own issues; the attempt goes on
    to narrative and readiness and the module repair is not spent."""
    script = [*ok_steps(*CHAIN[:2]), ("financials", BAD), *ok_steps(*CHAIN[2:])]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0 and len(chain.requests) == len(script)
    rows = module_rows(rig)
    assert [(r[2], r[6], r[REPAIR_COLUMN]) for r in rows] == [
        ("source_readiness", "accepted", "-"),
        ("source_context", "accepted", "-"),
        ("financials", "rejected", "-"),
        ("financials", "accepted", "step"),
        ("narrative", "accepted", "-"),
        ("readiness", "accepted", "-"),
        ("quality", "accepted", "-"),
    ]
    text = rig.report()
    assert "- Repairs dispatched: 1 (module repair attempts 0, within-attempt step repairs 1)" in (
        text
    )
    assert "- Stopped: no" in text and "| Issues | Repair |" in text
    manifests = {m["attempt_id"]: m for m in retained_manifests(rig)}
    links = manifests[rows[3][5]]["links"]
    assert links["step_repair_of_attempt_id"] == rows[2][5]
    assert links["repair_of_ticket_id"] is None and links["retry_of_attempt_id"] is None
    assert manifests[rows[3][5]]["retries"]["step_try"] == 2
    prompts = chain.user_prompts()
    assert [("<<<REPAIR" in p) for p in prompts] == [False] * 3 + [True, False, False, False]
    assert "- (root): Invalid JSON" in prompts[3]


def test_a_step_rejected_twice_falls_back_to_the_module_repair(tmp_path: Path) -> None:
    """Task 7.0g (b): the step's own repair is rejected too, so the journal finishes the attempt
    and the 7.0e module repair re-runs the whole module from its first step."""
    script = [*ok_steps(*CHAIN[:2]), ("financials", BAD), ("financials", BAD)]
    script += ok_steps(*CHAIN[1:])
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0 and len(chain.requests) == len(script)
    rows = module_rows(rig)
    assert [(r[2], r[6], r[REPAIR_COLUMN]) for r in rows] == [
        ("source_readiness", "accepted", "-"),
        ("source_context", "accepted", "-"),
        ("financials", "rejected", "-"),
        ("financials", "rejected", "step"),
        ("source_context", "accepted", "1"),
        ("financials", "accepted", "1"),
        ("narrative", "accepted", "1"),
        ("readiness", "accepted", "1"),
        ("quality", "accepted", "1"),
    ]
    text = rig.report()
    assert "- Repairs dispatched: 2 (module repair attempts 1, within-attempt step repairs 1)" in (
        text
    )
    manifests = {m["attempt_id"]: m for m in retained_manifests(rig)}
    assert manifests[rows[5][5]]["links"]["repair_of_ticket_id"] is not None
    assert manifests[rows[5][5]]["links"]["step_repair_of_attempt_id"] is None
    prompts = chain.user_prompts()
    assert [("<<<REPAIR" in p) for p in prompts] == [False] * 3 + [True, False, True] + [False] * 3


def test_a_second_rejection_ends_the_cell_without_a_third_attempt(tmp_path: Path) -> None:
    script = [*ok_steps(*CHAIN[:2]), ("financials", BAD), ("financials", BAD)]
    script += [("source_context", "ok"), ("financials", BAD), ("financials", BAD)]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0 and len(chain.requests) == len(script)  # nothing is sent beyond it
    assert [(r[2], r[6], r[REPAIR_COLUMN]) for r in module_rows(rig)][2:] == [
        ("financials", "rejected", "-"),
        ("financials", "rejected", "step"),
        ("source_context", "accepted", "1"),
        ("financials", "rejected", "1"),
        ("financials", "rejected", "1+step"),
    ]
    text = rig.report()
    assert "- Repairs dispatched: 3 (module repair attempts 1, within-attempt step repairs 2)" in (
        text
    )
    assert "- Stopped: no" in text


@pytest.mark.parametrize(
    ("sent", "unsent", "counted"),
    [
        (3, ("financials", "ineligible", "step"), "0 (module repair attempts 0, within-attempt "),
        (4, ("source_context", "ineligible", "1"), "1 (module repair attempts 0, within-attempt "),
    ],
)
def test_a_repair_whose_first_step_is_ineligible_is_not_counted_as_dispatched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sent: int,
    unsent: tuple[str, str, str],
    counted: str,
) -> None:
    """An ineligible step is sealed unsent, so a repair that stops there sent nothing: the
    step's repair within the attempt (3 calls fit) or the module repair attempt (4 fit)."""
    original = PinnedCandidate.misfit
    calls: list[int] = []

    def misfit_after(self: PinnedCandidate, prompt_bound: int, max_tokens: int) -> str | None:
        calls.append(prompt_bound)
        if len(calls) > sent:  # the calls before the repair fit; the repair's first does not
            return "context too small (test)"
        return original(self, prompt_bound, max_tokens)

    monkeypatch.setattr(PinnedCandidate, "misfit", misfit_after)
    script = [*ok_steps(*CHAIN[:2]), *[("financials", BAD)] * (sent - 2)]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0 and len(chain.requests) == sent
    rejected = [("financials", "rejected", "-"), ("financials", "rejected", "step")]
    assert [(r[2], r[6], r[REPAIR_COLUMN]) for r in module_rows(rig)][2:] == [
        *rejected[: sent - 2],
        unsent,
    ]
    assert f"- Repairs dispatched: {counted}" in rig.report()


def test_a_truncated_first_try_is_not_resent_and_ends_the_cell(tmp_path: Path) -> None:
    """Task 7.0h (a): a cut at the --max-tokens budget is no validator verdict the model can act
    on, so the step's repair is left unused, no module repair begins and the cell ends."""
    script = [*ok_steps(*CHAIN[:2]), ("financials", TRUNC)]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0 and len(chain.requests) == 3  # nothing is re-sent
    assert [(r[2], r[6], r[7], r[REPAIR_COLUMN]) for r in module_rows(rig)][2:] == [
        ("financials", "rejected", "truncated", "-")
    ]
    text = rig.report()
    assert "- Repairs dispatched: 0 (module repair attempts 0, within-attempt step repairs 0)" in (
        text
    )
    assert "- Truncated: 1" in text and "- Stopped: no" in text


def test_a_truncated_step_repair_ends_the_cell_without_a_module_repair(tmp_path: Path) -> None:
    """Task 7.0h (c): the validator rejects the first try, the re-send is cut at the budget."""
    script = [*ok_steps(*CHAIN[:2]), ("financials", BAD), ("financials", TRUNC)]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0 and len(chain.requests) == 4
    assert [(r[2], r[6], r[7], r[REPAIR_COLUMN]) for r in module_rows(rig)][2:] == [
        ("financials", "rejected", "ok", "-"),
        ("financials", "rejected", "truncated", "step"),
    ]
    text = rig.report()
    assert "- Repairs dispatched: 1 (module repair attempts 0, within-attempt step repairs 1)" in (
        text
    )
    assert "- Truncated: 1" in text


def test_a_cut_cell_does_not_stop_the_batch(rig: Rig) -> None:
    """Task 7.0h (a): every cell of a regression is cut at its first step; each is counted and
    the batch still plans, runs and reports all of them."""

    def cut(request: Request) -> Response:
        if request.url == KEY_URL:
            return key_status("1.5")
        model = json.loads(request.body or b"{}")["model"]
        return ok('{"sch', model=model, finish_reason="length")

    assert rig.run(rig.argv("regression", batch="r1"), cut) == 0
    text = rig.report("r1")
    # Task 8.6: the cases with no recorded corpus entry are skipped (cp0 and cp1 run).
    assert "- Truncated: 6" in text and "- Cells planned: 6;" in text


def test_a_cell_with_no_model_output_is_not_repaired(tmp_path: Path) -> None:
    """A no-response is no validator verdict: the journal ticket stays pending, so no repair
    is begun, and the batch (here one cell) ends normally."""
    script = [*ok_steps(*CHAIN[:2]), ("financials", OUTAGE)]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0 and len(chain.requests) == 3
    assert [(r[2], r[6], r[REPAIR_COLUMN]) for r in module_rows(rig)][2:] == [
        ("financials", "no-response", "-")
    ]
    assert "- Repairs dispatched: 0" in rig.report()


def test_a_cap_that_cannot_cover_the_repair_ends_the_batch_without_a_partial_row(
    tmp_path: Path,
) -> None:
    """The repair prompt carries the REPAIR block, so its request is longer than the first
    attempt's (at this rig's 300 bytes per token the two reservations may still be equal, the
    token bound being a ceiling). A cap equal to the first reservation covers that attempt, and
    after its charge cannot cover the repair's: nothing is sent and the repair has no row."""
    script = [("source_readiness", BAD), *ok_steps(*CHAIN)]
    measured, chain_measured, _ = run_chain(tmp_path / "measure", script)  # ample cap
    first, repair = ledger(measured).state().attempts[:2]
    first_request, repair_request = chain_measured.requests[:2]
    assert len(repair_request.body or b"") > len(first_request.body or b"")
    assert repair.reserved_usd >= first.reserved_usd
    rig, chain, status = run_chain(tmp_path / "capped", script, cap=format(first.reserved_usd, "f"))
    assert status == cli.EXIT_CAP and len(chain.requests) == 1
    text = rig.report()
    assert "- Stopped: cap" in text and "- Repairs dispatched: 0" in text
    assert [(r[2], r[6]) for r in module_rows(rig)] == [("source_readiness", "rejected")]


def test_a_refused_repair_fails_the_batch_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Execution.begin
    calls: list[str] = []

    def refuse_second(store: Execution, module_id: str) -> Attempt:
        calls.append(module_id)
        if calls.count("CP-1") == 3:  # the case's own begin, the cell's first, then the repair
            raise ValueError("Input set is settled or its one repair has been consumed")
        return original(store, module_id)

    monkeypatch.setattr(Execution, "begin", refuse_second)
    script = [*ok_steps(*CHAIN[:2]), ("financials", BAD), ("financials", BAD)]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == cli.EXIT_FAILED and len(chain.requests) == 4
    assert "Stopped: aborted: ValueError" in rig.report()


def test_a_cp0_accepted_on_repair_still_authorizes_cp1(tmp_path: Path) -> None:
    script = [("source_readiness", BAD), *ok_steps(*CHAIN)]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0
    assert [(r[2], r[6], r[REPAIR_COLUMN]) for r in module_rows(rig)] == [
        ("source_readiness", "rejected", "-"),
        ("source_readiness", "accepted", "1"),
        ("source_context", "accepted", "-"),
        ("financials", "accepted", "-"),
        ("narrative", "accepted", "-"),
        ("readiness", "accepted", "-"),
        ("quality", "accepted", "-"),
    ]
    assert "- Repairs dispatched: 1" in rig.report()
    assert "<<<REPAIR" in chain.user_prompts()[1]


def cell_journal(rig: Rig, cell: str = "module-00") -> Execution:
    return Execution(rig.store.directory / "live" / "b1" / cell)


def test_a_cp1_module_cell_runs_five_steps_and_its_quality_review_promotes_cp1(
    tmp_path: Path,
) -> None:
    """Task 7.4: the fifth step's accepted review is the promotion, so a live cell reaches a
    promoted CP-1 head whose canonical envelope exports."""
    rig, chain, status = run_chain(tmp_path, ok_steps(*CHAIN))
    assert status == 0 and len(chain.requests) == len(CHAIN)
    assert [(r[2], r[6], r[REPAIR_COLUMN]) for r in module_rows(rig)] == [
        (step, "accepted", "-") for step in CHAIN
    ]
    journal = cell_journal(rig)
    attempt = journal.read().attempts[-1]
    assert attempt.status == "finished" and not attempt.issues
    assert [s.step_id for s in attempt.steps] == list(CHAIN[1:])
    head = next(h for h in journal.read().heads if h.module_id == "CP-1")
    assert head.status == "restricted" and head.qualification == PROMOTED
    exported = write_cp1_envelope(journal, tmp_path / "envelope")
    assert exported == tmp_path / "envelope" / "envelope.md"
    body = json.loads(chain.requests[-1].body or b"{}")
    assert body["response_format"]["json_schema"]["name"] == "quality"
    assert f"<<<CONTEXT id={QUALITY_BLOCK_ID} sha256=" in body["messages"][1]["content"]


def test_a_rejected_quality_review_takes_the_module_repair_and_promotes_on_it(
    tmp_path: Path,
) -> None:
    """R2: `quality` settles the module, so its rejection finishes the attempt (no step repair
    within it); the 7.0e module repair re-runs the CP-1 chain from source_context and the
    repaired review carries the rejected one's issues."""
    script = [*ok_steps(*CHAIN[:-1]), ("quality", UPGRADE), *ok_steps(*CHAIN[1:])]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0 and len(chain.requests) == len(script)
    rows = module_rows(rig)
    assert [(r[2], r[6], r[REPAIR_COLUMN]) for r in rows] == [
        *[(step, "accepted", "-") for step in CHAIN[:-1]],
        ("quality", "rejected", "-"),
        *[(step, "accepted", "1") for step in CHAIN[1:]],
    ]
    assert "- Repairs dispatched: 1 (module repair attempts 1, within-attempt step repairs 0)" in (
        rig.report()
    )
    prompts = chain.user_prompts()
    assert [("<<<REPAIR" in p) for p in prompts] == [False] * 6 + [False] * 4 + [True]
    assert "QA lineage upgrade rejected: " in prompts[-1]
    journal = cell_journal(rig)
    first, repair = journal.read().attempts[-2:]
    assert first.status == "finished" and first.step_repairs == ()
    assert repair.number == 1 and repair.status == "finished" and not repair.issues
    head = next(h for h in journal.read().heads if h.module_id == "CP-1")
    assert head.qualification == PROMOTED and head.result_sha256 == repair.result_sha256


def test_a_blocked_qa_verdict_stands_and_ends_the_cell_without_a_module_repair(
    tmp_path: Path,
) -> None:
    """Fix round 1 (coordinator ruling): a Blocked QA verdict is an analytical outcome, not a
    defect to repair, so the cell ends at it (as at a truncation) and the journal keeps it."""
    script = [*ok_steps(*CHAIN[:-1]), ("quality", CRITICAL)]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0 and len(chain.requests) == len(script)  # nothing is re-sent
    rows = module_rows(rig)
    assert [(r[2], r[6], r[REPAIR_COLUMN]) for r in rows][-1] == ("quality", "rejected", "-")
    text = rig.report()
    assert "- Repairs dispatched: 0 (module repair attempts 0, within-attempt step repairs 0)" in (
        text
    )
    assert "- Stopped: no" in text
    journal = cell_journal(rig)
    cp1 = [a for a in journal.read().attempts if a.module_id == "CP-1"]
    assert len(cp1) == 1 and cp1[0].status == "finished"  # no repair attempt was begun
    (blocked,) = cp1[0].issues
    assert blocked.startswith("CP-1 QA Blocked: confidence ")
    assert blocked.endswith("; a Blocked handoff is not promoted")
    assert not [h for h in journal.read().heads if h.module_id == "CP-1"]


def test_a_validator_rejection_beside_a_blocked_line_still_takes_the_module_repair() -> None:
    blocked = "CP-1 QA Blocked: confidence 12 (Insufficient Information); "
    blocked += "a Blocked handoff is not promoted"
    assert cli.qa_blocked_only("quality", (blocked,))
    assert not cli.qa_blocked_only("quality", ())
    assert not cli.qa_blocked_only("quality", (blocked, "QA review does not bind current inputs"))
    assert not cli.qa_blocked_only("quality", ("QA review does not bind current inputs",))


@pytest.mark.parametrize("step_id", [s for s in cli.FULL_CHAIN + cli.CP1A_CHAIN if s != "quality"])
def test_a_blocked_looking_issue_on_another_step_is_an_ordinary_rejection(step_id: str) -> None:
    """Task 7.10 item 2: only the `quality` step emits the QA Blocked verdict, so only there does
    it stand unrepaired; the same text on any other step takes the module repair as usual."""
    blocked = "CP-1 QA Blocked: confidence 12 (Insufficient Information); "
    blocked += "a Blocked handoff is not promoted"
    assert not cli.qa_blocked_only(step_id, (blocked,))


def test_a_truncated_quality_review_finishes_the_attempt_and_ends_the_cell(
    tmp_path: Path,
) -> None:
    """A cut `quality` is still submitted (as every truncated payload is), and the step settles
    the module: the attempt finishes rejected, its four accepted stages are not promoted, and
    the 7.0h guard ends the cell without a module repair, as for CP-0."""
    script = [*ok_steps(*CHAIN[:-1]), ("quality", TRUNC)]
    rig, chain, status = run_chain(tmp_path, script)
    assert status == 0 and len(chain.requests) == len(script)
    assert [(r[2], r[6], r[7], r[REPAIR_COLUMN]) for r in module_rows(rig)][-1] == (
        "quality",
        "rejected",
        "truncated",
        "-",
    )
    assert "- Repairs dispatched: 0" in rig.report() and "- Truncated: 1" in rig.report()
    cp1 = [a for a in cell_journal(rig).read().attempts if a.module_id == "CP-1"]
    assert len(cp1) == 1 and cp1[0].status == "finished" and cp1[0].issues


def test_probe_cells_are_never_repaired(rig: Rig) -> None:
    """Only the `module` driver spends the repair; a probe is one measured draw per cell."""
    responder = Responder(rig.review, junk_after_first=True)
    assert rig.run(rig.argv("probe"), responder) == 0
    assert len(responder.requests) == 4  # unchanged: one CP-0 call per cell, one extra step
    assert "- Repairs dispatched: 0" in rig.report()


def test_a_probe_cp1_rejection_leaves_the_attempt_pending_with_its_step_repair(
    tmp_path: Path,
) -> None:
    """Task 7.0g fix 1: a single-attempt driver never re-sends, so a first CP-1 rejection ends
    the cell with the journal attempt pending and the try kept in `step_repairs` (the journal
    no longer finishes it rejected)."""
    rig, extraction = chain_rig(tmp_path)
    chain = Chain(rig, extraction, [*ok_steps(*CHAIN[:2]), ("financials", BAD)])
    chain.cell = "probe-00"
    assert rig.run([*rig.argv("probe"), "--models", LUNA], chain) == 0
    assert len(chain.requests) == 3  # no re-send
    rows = step_lines(rig.report(), "probe-00")
    assert [(r[2], r[6], r[REPAIR_COLUMN]) for r in rows][2:] == [("financials", "rejected", "-")]
    journal = Execution(rig.store.directory / "live" / "b1" / "probe-00").read().attempts[-1]
    assert journal.module_id == "CP-1" and journal.status == "pending"
    assert [s.step_id for s in journal.step_repairs] == ["financials"]
    assert [s.step_id for s in journal.steps] == ["source_context"]


# --- 8.0d: the CP-1 stages as tool loops --------------------------------------------------------


class ToolChain(Chain):
    """The CP-1 cell with `tool_loop` on (task 8.9: every step a tool loop): each step first
    calls `search_pack` (a pack-tool step searches; the submit-only `quality` has it refused),
    then submits its valid payload through `submit_<step>`."""

    def __call__(self, request: Request) -> Response:
        if request.url == KEY_URL:
            return key_status(format(self.usage, "f"))
        self.requests.append(request)
        self.usage += Decimal("0.01")
        body = json.loads(request.body or b"{}")
        if "tools" not in body:
            step = body["response_format"]["json_schema"]["name"]
            return ok(self.payload(step), model=body["model"])
        step = body["tools"][-1]["function"]["name"].removeprefix("submit_")
        if body["messages"][-1]["role"] != "tool":
            found = tool_reply(("s", "search_pack", '{"query": "revenue"}'), model=body["model"])
            if step != "narrative":
                return found
            unmeasured = json.loads(found.body)  # no usage at all: the reservation is held
            del unmeasured["usage"]
            return Response(200, json.dumps(unmeasured).encode())
        return tool_reply(("c", f"submit_{step}", self.payload(step)), model=body["model"])


def test_the_module_driver_runs_every_step_as_a_tool_loop(tmp_path: Path) -> None:
    rig, extraction = chain_rig(tmp_path)
    text = rig.settings.read_text(encoding="utf-8")
    rig.settings.write_text(
        text.replace(
            "[[model_tests.candidates]]",
            'tool_loop = true\n\n[model_tests.step_effort]\nfinancials = { effort = "low" }\n\n'
            "[[model_tests.candidates]]",
            1,
        ),
        encoding="utf-8",
    )
    chain = ToolChain(rig, extraction, [])
    assert rig.run([*rig.argv("module", "--module", "CP-1"), "--models", LUNA], chain) == 0
    rows = module_rows(rig)
    assert [(r[2], r[6]) for r in rows] == [(step, "accepted") for step in CHAIN]
    assert all(r[5].endswith("(2 calls)") for r in rows)
    assert rows[1][8] == "0.02"  # the step's two settled calls
    assert len(chain.requests) == 12
    bodies = chat_bodies(chain)
    assert [b.get("tool_choice") for b in bodies] == ["required"] * 12
    assert not [b for b in bodies if "response_format" in b]
    names = [[t["function"]["name"] for t in b["tools"]] for b in bodies]
    assert names[0] == ["search_pack", "read_pages", "submit_source_readiness"]
    assert names[-1] == ["submit_quality"]  # submit-only
    efforts = [b["reasoning"] for b in bodies]
    assert efforts[:4] == [{"effort": "high"}] * 4  # default_effort: no row for the step
    assert efforts[4:6] == [{"effort": "low"}] * 2  # financials' own row
    report = rig.report()
    assert (
        "- Tool loop: source_readiness high (ceiling high; pack tools), source_context high "
        "(ceiling high; pack tools), financials low (ceiling high; pack tools)" in report
    )
    assert "quality high (ceiling high; submit-only tools)" in report
    path = rig.root / "artifacts" / "model-tests" / ".ledgers" / "b1.jsonl"
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["provider"] == "openrouter"
    assert len(Ledger(path, Decimal("5.00")).state().attempts) == 12
    # Fix round 1 (review B items 8 to 10): the report says what each line covers. Task 8.9:
    # no planned step is one-shot, so the one-shot budget lines say they are unused.
    assert "completeness floor: off (user decision 24 Oct 2026)" in report
    scope = "per call (unused: every planned step is a tool loop; see Tool loop)"
    assert f"- Max tokens: 16000 {scope}" in report and f"- Timeout: 600.0 s {scope}" in report
    assert "completeness floor: off" in report.split("- Tool loop:")[1].splitlines()[0]
    held = next(
        r for r in Ledger(path, Decimal("5.00")).state().attempts if r.basis and "held" in r.basis
    )
    total, kept = held.charged_usd + Decimal("0.01"), held.charged_usd
    assert rows[3][8] == f"{format(total, 'f')} ({cli.HELD} {format(kept, 'f')})"
    assert cli.HELD_FOOTNOTE in report


def test_the_budget_lines_name_the_one_shot_steps_only_while_one_is_planned(
    tmp_path: Path,
) -> None:
    """Task 8.9: the qualifier is accurate: a planned step outside the tool loop's plan (a
    chain's `one_shot` step) keeps the 8.0d wording; none planned says the lines are unused."""
    cells = [cli.Cell("module-00", "cp-1", ("source_readiness", "source_context"), 7)]
    ledger = Ledger(tmp_path / "l.jsonl", Decimal(1))

    def lines(*looped: str) -> list[str]:
        plan = cli.ToolLoop(dict.fromkeys(looped, StepEffort.of("high")), ToolRules())
        report = cli.render_report(
            "module", "b", 7, fixture_pool(), ledger, cells, cli.Batch(), "high", tool_loop=plan
        )
        return [line for line in report.splitlines() if line.startswith("- Max tokens:")]

    assert lines("source_context") == [
        "- Max tokens: 16000 per call (one-shot steps; tool-loop steps: see Tool loop)"
    ]
    assert lines("source_readiness", "source_context") == [
        "- Max tokens: 16000 per call (unused: every planned step is a tool loop; see Tool loop)"
    ]


def test_the_one_shot_budget_options_say_tool_loops_have_their_own() -> None:
    parser = argparse.ArgumentParser()
    cli.configure(parser)
    text = " ".join(parser._subparsers._group_actions[0].choices["module"].format_help().split())
    assert text.count("one-shot steps only; tool-loop steps use their own limits") == 2


def test_the_tool_loop_line_states_a_set_completeness_floor() -> None:
    plan = cli.ToolLoop({"financials": StepEffort.of("high")}, ToolRules(floor=3))
    (line,) = cli._tool_loop_lines(plan)
    assert line.endswith("; completeness floor: 3 statement lines per expected cell")
    # Task 8.9 fix round 1: the call limit is the tool set's; task 8.11: a part step's own.
    assert (
        "; per step at most 30 calls on pack-tool steps (40 on financials, its submit in parts) "
        "and 6 on submit-only steps, "
    ) in line
    plan = cli.ToolLoop({"source_context": StepEffort.of("high")}, ToolRules(floor=3))
    (line,) = cli._tool_loop_lines(plan)
    assert "; per step at most 30 calls on pack-tool steps and 6 on submit-only steps, " in line
    assert cli._tool_loop_lines(None) == []


def test_the_tool_loop_line_states_a_set_extracted_coverage_floor() -> None:
    """Task 8.12: a set coverage floor follows the line-count floor's text; off, nothing is
    added (the line ends as before)."""
    rules = ToolRules(coverage_min=Decimal("0.70"))
    (line,) = cli._tool_loop_lines(cli.ToolLoop({"financials": StepEffort.of("high")}, rules))
    assert line.endswith(
        "; completeness floor: off (user decision 24 Oct 2026); extracted-coverage floor: 0.70 "
        "of each expected cell's extracted statement lines"
    )
