"""M8b: the execution CLI submits every registered module step and renders the report.

SYNTHETIC data only: the journal is the CP-2 test's (CP-0, CP-1 and CP-1A settled over the
readiness fixture) and the reviews are the module tests' accepted fixtures
(`test_business_context.submission_fixture`, `test_cp2_synthesis.synthesis`).
"""

import json
from pathlib import Path

import pytest

from deploy_vii import registry
from deploy_vii.__main__ import main
from deploy_vii.contracts import Module
from deploy_vii.cp0_workflow import build_readiness
from deploy_vii.execution import Execution
from deploy_vii.live.context import module_context
from deploy_vii.module_submits import MODULE_SUBMITS, submit_module_step
from tests.product.test_business_context import cp1_fact, submission_fixture
from tests.product.test_cp2_synthesis import journal, synthesis
from tests.product.test_readiness import readiness_fixture

# What the live runner pins (`live.runner.MODULE_STEP_ENTRIES`), written out by hand so the
# CLI's table is held to the same modules without importing the runner.
LIVE_MODULES = {"CP-1A", "CP-2", "CP-3", "CP-4", "CP-5", "CP-6"}


def test_every_registered_module_but_cp0_and_cp1_has_a_submit() -> None:
    chained = {chain.module_id for chain in registry.STEP_CHAINS} - {"CP-0", "CP-1"}
    assert set(MODULE_SUBMITS) == chained == LIVE_MODULES


@pytest.mark.parametrize("module_id", sorted(LIVE_MODULES))
def test_a_step_outside_the_chain_is_refused_naming_the_valid_choices(
    tmp_path: Path, module_id: str
) -> None:
    store = journal(tmp_path)
    steps = registry.step_chain(module_id).steps
    with pytest.raises(ValueError, match="not a step of") as refused:
        submit_module_step(store, module_id, "t", "no_such_step", "{}")
    assert all(step in str(refused.value) for step in steps)


def test_an_unknown_module_is_refused_naming_the_valid_choices(tmp_path: Path) -> None:
    store = journal(tmp_path)
    with pytest.raises(ValueError, match="Unknown module") as refused:
        submit_module_step(store, "CP-9", "t", "x", "{}")
    assert all(module in str(refused.value) for module in LIVE_MODULES)


# --- item 2: the CLI commands ---


class Cli:
    def __init__(
        self, store: Execution, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.store, self.monkeypatch, self.capsys = store, monkeypatch, capsys

    def __call__(self, *arguments: str) -> tuple[int, str, str]:
        self.monkeypatch.setattr(
            "sys.argv",
            ["deploy-vii", "execution", "--directory", str(self.store.directory), *arguments],
        )
        code = 0
        try:
            main()
        except SystemExit as stop:
            code = stop.code if isinstance(stop.code, int) else 1
        out, err = self.capsys.readouterr()
        return code, out, err


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Cli:
    return Cli(journal(tmp_path), monkeypatch, capsys)


def test_begin_refuses_an_unknown_module_with_exit_2_and_the_valid_ids(cli: Cli) -> None:
    code, out, err = cli("begin", "CP-9")
    assert code == 2 and out == "" and "CP-9" in err and "CP-2" in err


def test_module_submit_settles_a_step_from_a_review_file(cli: Cli, tmp_path: Path) -> None:
    ticket = json.loads(cli("begin", "CP-2")[1])["ticket_id"]
    review = tmp_path / "review.json"
    review.write_text(synthesis().model_dump_json())
    code, out, _ = cli(
        "module-submit",
        *("--module", "CP-2", "--ticket", ticket, "--step", "credit_synthesis"),
        *("--review", str(review)),
    )
    shown = json.loads(out)
    assert code == 0 and shown["status"] == "finished" and shown["issues"] == []
    assert shown["result"]["module_id"] == "CP-2"


def test_module_submit_settles_cp1a_from_the_business_context_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pack, review = readiness_fixture()
    store = Execution.create(tmp_path / "execution", pack)
    ticket = store.begin("CP-0")
    store.finish(
        ticket.ticket_id, build_readiness(store.pack(), review).model_dump_json(), lambda _: ()
    )
    ticket = store.begin("CP-1")
    run = pack.run
    cp1 = Module(
        run_id=run.run_id,
        issuer_id=run.issuer_id,
        as_of=run.as_of,
        module_id="CP-1",
        inputs=ticket.inputs,
        facts=(cp1_fact(pack),),
    )
    store.finish(ticket.ticket_id, cp1.model_dump_json(), lambda _: ())
    run_cli = Cli(store, monkeypatch, capsys)
    ticket_id = json.loads(run_cli("begin", "CP-1A")[1])["ticket_id"]
    file = tmp_path / "bc.json"
    file.write_text(submission_fixture(pack).model_dump_json())
    code, out, _ = run_cli(
        "module-submit",
        *("--module", "CP-1A", "--ticket", ticket_id, "--step", "business_context"),
        *("--review", str(file)),
    )
    assert code == 0 and json.loads(out)["status"] == "finished"
    assert "CP-1A" in {h.module_id for h in store.read().heads}


def test_a_rejected_review_returns_the_validator_issue_lines_and_a_nonzero_exit(
    cli: Cli, tmp_path: Path
) -> None:
    ticket = json.loads(cli("begin", "CP-2")[1])["ticket_id"]
    review = tmp_path / "review.json"
    review.write_text("not json")
    code, out, err = cli(
        "module-submit",
        *("--module", "CP-2", "--ticket", ticket, "--step", "credit_synthesis"),
        *("--review", str(review)),
    )
    issues = json.loads(out)["issues"]
    assert code == 1 and issues and "Traceback" not in err
    assert err.splitlines() == issues


def test_module_submit_refuses_a_step_outside_the_chain_with_exit_2(
    cli: Cli, tmp_path: Path
) -> None:
    ticket = json.loads(cli("begin", "CP-2")[1])["ticket_id"]
    review = tmp_path / "review.json"
    review.write_text("{}")
    code, out, err = cli(
        "module-submit",
        *("--module", "CP-2", "--ticket", ticket, "--step", "nope"),
        *("--review", str(review)),
    )
    assert code == 2 and out == "" and "credit_synthesis" in err


def test_module_context_equals_the_live_runners_module_context_byte_for_byte(cli: Cli) -> None:
    ticket = json.loads(cli("begin", "CP-2")[1])["ticket_id"]
    code, out, err = cli(
        "module-context", *("--module", "CP-2", "--ticket", ticket, "--step", "credit_synthesis")
    )
    attempt = next(a for a in cli.store.read().attempts if a.ticket_id == ticket)
    expected = module_context(cli.store, attempt, "credit_synthesis")
    assert expected and code == 0 and err == ""
    assert out == json.dumps(expected, indent=1, sort_keys=True) + "\n"


def test_a_step_with_no_context_prints_empty_json_and_says_so_on_stderr(cli: Cli) -> None:
    # CP-1A (settled in the journal) has no module context: the step reads the pack alone.
    step = registry.step_chain("CP-1A").steps[0]
    attempt = next(a for a in cli.store.read().attempts if a.module_id == "CP-1A")
    assert module_context(cli.store, attempt, step) is None
    code, out, err = cli(
        "module-context", *("--module", "CP-1A", "--ticket", attempt.ticket_id, "--step", step)
    )
    assert code == 0 and json.loads(out) == {} and "no module context" in err
