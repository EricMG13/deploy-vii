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
from deploy_vii.business_context import context_block
from deploy_vii.contracts import Module
from deploy_vii.cp0_workflow import build_readiness
from deploy_vii.execution import Attempt, Execution, StepSubmission
from deploy_vii.execution_cli import issue_lines
from deploy_vii.live.prompts import INTEGRITY_BLOCK_ID
from deploy_vii.live.runner import prompt_inputs
from deploy_vii.module_submits import MODULE_SUBMITS, host_context, submit_module_step
from deploy_vii.report_view import pathways
from tests.product.test_business_context import cp1_fact, submission_fixture
from tests.product.test_cp2_synthesis import journal, synthesis
from tests.product.test_live_modules import CASES, SCHEMAS, cp1a_case
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


def runner_context(store: Execution, attempt: Attempt, step: str) -> dict[str, object]:
    """The CONTEXT entries the live runner adds for `step`, from its own `prompt_inputs`."""
    inputs = prompt_inputs(store, attempt, step)
    entries: dict[str, object] = {}
    if step == "business_context":
        entries.update(context_block(store.pack(), inputs.cp1_facts))
    if inputs.module_context is not None:
        entries.update(inputs.module_context)
    if inputs.scope is not None:
        entries[INTEGRITY_BLOCK_ID] = inputs.scope
    return entries


CONTEXT_CASES = {
    "business_context": ("CP-1A", cp1a_case),
    **{step: (module, CASES[step]) for step, (module, _) in SCHEMAS.items()},
}


@pytest.mark.parametrize("step", sorted(CONTEXT_CASES))
def test_module_context_is_what_the_live_runner_sends_for_every_module_byte_for_byte(
    step: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module, case = CONTEXT_CASES[step]
    store, _ = case(tmp_path)
    attempt = store.begin(module)
    code, out, err = Cli(store, monkeypatch, capsys)(
        "module-context", *("--module", module, "--ticket", attempt.ticket_id, "--step", step)
    )
    expected = runner_context(store, attempt, step)
    assert expected and code == 0 and err == ""
    assert out == json.dumps(expected, indent=1, sort_keys=True) + "\n"


def test_a_step_with_no_context_entries_gets_none_as_the_runner_does(cli: Cli) -> None:
    attempt = next(a for a in cli.store.read().attempts if a.module_id == "CP-1")
    assert host_context(cli.store, attempt, "source_readiness") is None
    assert runner_context(cli.store, attempt, "source_readiness") == {}


def test_begin_is_refused_with_one_line_while_pending_and_after_the_repair_is_spent(
    cli: Cli, tmp_path: Path
) -> None:
    review = tmp_path / "review.json"
    review.write_text("not json")
    first = json.loads(cli("begin", "CP-2")[1])["ticket_id"]
    code, out, err = cli("begin", "CP-2")  # the first attempt is still pending
    assert (
        code == 2 and out == "" and err.startswith("begin refused:") and len(err.splitlines()) == 1
    )
    submit = ("module-submit", "--module", "CP-2", "--step", "credit_synthesis")
    assert cli(*submit, "--ticket", first, "--review", str(review))[0] == 1
    repair = json.loads(cli("begin", "CP-2")[1])["ticket_id"]  # the one repair attempt
    assert cli(*submit, "--ticket", repair, "--review", str(review))[0] == 1
    code, out, err = cli("begin", "CP-2")  # the repair is spent
    assert (
        code == 2 and out == "" and err.startswith("begin refused:") and len(err.splitlines()) == 1
    )


# --- item 3: report ---


def test_report_writes_the_front_page_with_every_pathway_block_and_a_receipt(
    cli: Cli, tmp_path: Path
) -> None:
    pathway_id = cli.store.read().run.pathway
    pathway = next(p for p in pathways() if p.id == pathway_id)
    out_dir = tmp_path / "report"
    code, out, _ = cli("report", "--pathway", pathway_id, "--output", str(out_dir))
    html = (out_dir / "index.html").read_text()
    receipt = json.loads((out_dir / "report.json").read_text())
    assert code == 0 and json.loads(out) == receipt
    assert all(block in html for block in pathway.blocks)
    assert receipt["pathway"] == pathway_id
    heads = {m["module_id"]: m["status"] for m in receipt["modules"]}
    assert heads["CP-0"] == "restricted" and "CP-6" in heads  # unrun modules show their state
    assert receipt["call_state"]["state"] in {"populated", "no-judgement", "blocked", "outside"}


def test_report_refuses_an_unknown_pathway_and_the_runs_other_pathways(
    cli: Cli, tmp_path: Path
) -> None:
    code, _, err = cli("report", "--pathway", "nope", "--output", str(tmp_path / "a"))
    assert code == 2 and "credit_snapshot" in err
    run_pathway = cli.store.read().run.pathway
    other = next(p.id for p in pathways() if p.id != run_pathway)
    code, _, err = cli("report", "--pathway", other, "--output", str(tmp_path / "b"))
    assert code == 2 and run_pathway in err and not (tmp_path / "b").exists()


def test_report_refuses_an_existing_output_directory(cli: Cli, tmp_path: Path) -> None:
    pathway_id = cli.store.read().run.pathway
    code, _, err = cli("report", "--pathway", pathway_id, "--output", str(tmp_path))
    assert code == 2 and "exists" in err


def test_issue_lines_read_a_kept_rejected_try_only_while_its_step_is_unrepaired() -> None:
    bad = StepSubmission(
        step_id="s", inputs=(), payload_sha256="0" * 64, status="invalid", issues=("bad",)
    )
    good = StepSubmission(
        step_id="s", inputs=(), payload_sha256="1" * 64, status="valid", output_sha256="2" * 64
    )
    kept = Attempt(ticket_id="t", module_id="CP-1", inputs=(), number=0, step_repairs=(bad,))
    assert issue_lines(kept) == ("bad",)
    repaired = Attempt(
        ticket_id="t", module_id="CP-1", inputs=(), number=0, steps=(good,), step_repairs=(bad,)
    )
    assert issue_lines(repaired) == ()
