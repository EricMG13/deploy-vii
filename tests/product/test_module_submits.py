"""M8b: the execution CLI submits every registered module step and renders the report.

SYNTHETIC data only: the journal is the CP-2 test's (CP-0, CP-1 and CP-1A settled over the
readiness fixture) and the reviews are the module tests' accepted fixtures
(`test_business_context.submission_fixture`, `test_cp2_synthesis.synthesis`).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from deploy_vii import registry
from deploy_vii.__main__ import main
from deploy_vii.business_context import context_block
from deploy_vii.contracts import Module
from deploy_vii.cp0_workflow import build_readiness
from deploy_vii.cp1_workflow import FinancialStage, submit_cp1_step
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview
from deploy_vii.execution import Attempt, Execution, StepSubmission
from deploy_vii.execution_cli import issue_lines
from deploy_vii.live.context import declared_sources
from deploy_vii.live.prompts import INTEGRITY_BLOCK_ID, Message, build, span_line
from deploy_vii.live.runner import StepSpec, prompt_inputs, repair_prompt
from deploy_vii.module_submits import MODULE_SUBMITS, host_context, submit_module_step
from deploy_vii.report_view import pathways
from tests.product.test_business_context import cp1_fact, submission_fixture
from tests.product.test_cp1_workflow import staged
from tests.product.test_cp2_synthesis import journal, synthesis
from tests.product.test_execution import step_text
from tests.product.test_live_modules import CASES, SCHEMAS, cp0_case, cp1a_case
from tests.product.test_narrative import populated
from tests.product.test_readiness import readiness_fixture
from tests.product.test_workflow import cp1_case

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


def test_a_step_with_no_context_entries_gets_an_empty_mapping_as_the_runner_does(cli: Cli) -> None:
    attempt = next(a for a in cli.store.read().attempts if a.module_id == "CP-1")
    assert host_context(cli.store, attempt, "source_readiness") == {}
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


def test_a_missing_review_file_is_a_one_line_refusal_naming_the_path(
    cli: Cli, tmp_path: Path
) -> None:
    ticket = json.loads(cli("begin", "CP-2")[1])["ticket_id"]
    absent = tmp_path / "absent.json"
    code, out, err = cli(
        "module-submit",
        *("--module", "CP-2", "--ticket", ticket, "--step", "credit_synthesis"),
        *("--review", str(absent)),
    )
    assert code == 2 and out == "" and str(absent) in err and len(err.splitlines()) == 1


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


# --- M8c item 1: step-instructions ---

ENTRIES = {  # every step's module, for the argparse choice
    "source_readiness": "CP-0",
    "source_context": "CP-1",
    "financials": "CP-1",
    "narrative": "CP-1",
    "readiness": "CP-1",
    "quality": "CP-1",
    "business_context": "CP-1A",
    **{step: module for step, (module, _) in SCHEMAS.items()},
}


def runner_messages(store: Execution, ticket_id: str, step_id: str) -> list[Message]:
    """`live.runner._plan`'s own composition of the one-shot prompt for the ticket's next step."""
    snapshot = store.read()
    attempt = next(a for a in snapshot.attempts if a.ticket_id == ticket_id)
    step = StepSpec(
        step_id,
        "case",
        declared_sources(store, attempt, step_id, [s.source_id for s in store.pack().sources]),
    )
    inputs = prompt_inputs(store, attempt, step_id)
    return build(
        step_id,
        store.pack(snapshot),
        step.declared_sources,
        step.schema,
        upstream=inputs.upstream,
        repair_issues=repair_prompt(snapshot, attempt, step_id).issues,
        cp1_facts=inputs.cp1_facts,
        module_context=inputs.module_context,
        scope=inputs.scope,
    )


def printed(messages: list[Message]) -> str:
    return "".join(f"--- {m.role} ---\n{m.content}\n" for m in messages)


def check_instructions(cli: Cli, ticket: str, step: str) -> tuple[str, str]:
    """The CLI's two outputs for `step`; the full one is the runner's messages byte for byte."""
    base = ("step-instructions", "--module", ENTRIES[step], "--ticket", ticket, "--step", step)
    code, full, err = cli(*base, "--with-sources")
    assert code == 0 and err == ""
    assert full == printed(runner_messages(cli.store, ticket, step))
    code, short, err = cli(*base)
    assert code == 0 and err == ""
    return full, short


def source_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("source: ")]


def check_default(cli: Cli, full: str, short: str, ticket: str, step: str) -> None:
    """Without `--with-sources` exactly the declared SOURCE blocks are replaced, one line each."""
    store = cli.store
    attempt = next(a for a in store.read().attempts if a.ticket_id == ticket)
    pack = store.pack()
    ids = declared_sources(store, attempt, step, [s.source_id for s in pack.sources])
    lines = source_lines(short)
    assert len(lines) == len(ids)
    for line, source_id in zip(lines, ids, strict=True):
        source = next(s for s in pack.sources if s.source_id == source_id)
        assert line.startswith(f"source: {source_id} -> ")
        if source.status == "ready":
            assert f"originals/{source.sha256}" in line and f"sha256 {source.sha256}" in line
            body = "\n".join(span_line(span) for span in source.spans)
            assert body in full and body not in short
        assert f"<<<SOURCE id={source_id} " not in short
        assert f"<<<SOURCE id={source_id} " in full
    assert short.split("--- user ---\n")[0] == full.split("--- user ---\n")[0]


def test_the_cli_choice_covers_every_registry_step() -> None:
    for chain in registry.STEP_CHAINS:
        assert {s for s, m in ENTRIES.items() if m == chain.module_id} == set(chain.steps)


def test_cp0_instructions_are_the_runners_prompt_and_list_every_pack_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, _ = cp0_case(tmp_path)
    cli = Cli(store, monkeypatch, capsys)
    ticket = store.begin("CP-0").ticket_id
    full, short = check_instructions(cli, ticket, "source_readiness")
    check_default(cli, full, short, ticket, "source_readiness")
    assert source_lines(short)


def test_cp1_instructions_are_the_runners_prompt_at_every_step_incl_quality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, ticket, extraction = cp1_case(tmp_path)  # source_context is already submitted
    cli = Cli(store, monkeypatch, capsys)
    seen = []

    def at(step: str) -> None:
        full, short = check_instructions(cli, ticket.ticket_id, step)
        check_default(cli, full, short, ticket.ticket_id, step)
        seen.append(step)

    at("financials")
    financial = submit_cp1_step(store, ticket.ticket_id, "financials", extraction.model_dump_json())
    output = FinancialStage.model_validate_json(step_text(store, financial.steps[-1]))
    at("narrative")
    narrative = submit_cp1_step(
        store, ticket.ticket_id, "narrative", populated(output.narrative_inputs).model_dump_json()
    )
    inputs = DownstreamInputs.model_validate_json(step_text(store, narrative.steps[-1]))
    at("readiness")
    review = DownstreamReview(inputs_sha256=inputs.content_hash()).model_dump_json()
    submit_cp1_step(store, ticket.ticket_id, "readiness", review)
    at("quality")
    # A repair ticket after an interrupt starts at source_context again, a pack-source step.
    store.interrupt(ticket.ticket_id, "M8c: show source_context on the repair ticket")
    repair = store.begin("CP-1").ticket_id
    full, short = check_instructions(cli, repair, "source_context")
    check_default(cli, full, short, repair, "source_context")
    assert seen == ["financials", "narrative", "readiness", "quality"]
    assert source_lines(short)


@pytest.mark.parametrize("step", sorted(CONTEXT_CASES))
def test_module_instructions_are_the_runners_prompt_for_every_module_step(
    step: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module, case = CONTEXT_CASES[step]
    store, _ = case(tmp_path)
    ticket = store.begin(module).ticket_id
    cli = Cli(store, monkeypatch, capsys)
    full, short = check_instructions(cli, ticket, step)
    check_default(cli, full, short, ticket, step)
    assert "JSON Schema:" in full and "Rules:" in full


def test_a_step_rejected_once_within_its_attempt_shows_the_repair_block_in_both_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, ticket, _ = cp1_case(tmp_path)
    cli = Cli(store, monkeypatch, capsys)
    assert "<<<REPAIR" not in check_instructions(cli, ticket.ticket_id, "financials")[0]
    kept = submit_cp1_step(store, ticket.ticket_id, "financials", "not json")
    assert kept.status == "pending" and kept.step_repairs[0].issues
    full, short = check_instructions(cli, ticket.ticket_id, "financials")
    for text in (full, short):
        assert "<<<REPAIR id=prior-validation-issues" in text
        assert all(f"- {issue}" in text for issue in kept.step_repairs[0].issues)


def test_a_repair_ticket_shows_the_rejected_attempts_issues(cli: Cli, tmp_path: Path) -> None:
    ticket = json.loads(cli("begin", "CP-2")[1])["ticket_id"]
    review = tmp_path / "review.json"
    review.write_text("not json")
    submit = ("module-submit", "--module", "CP-2", "--ticket", ticket, "--step")
    code, out, _ = cli(*submit, "credit_synthesis", "--review", str(review))
    issues = json.loads(out)["issues"]
    assert code == 1 and issues
    repair = json.loads(cli("begin", "CP-2")[1])["ticket_id"]
    full, short = check_instructions(cli, repair, "credit_synthesis")
    for text in (full, short):
        assert all(f"- {issue}" in text for issue in issues)


def test_instructions_refuse_in_one_line_with_exit_2(cli: Cli, tmp_path: Path) -> None:
    ticket = json.loads(cli("begin", "CP-2")[1])["ticket_id"]
    base = ("step-instructions", "--ticket", ticket)
    refusals = {
        "wrong module": cli(*base, "--module", "CP-3", "--step", "relative_value"),
        "unknown ticket": cli(
            "step-instructions", *("--module", "CP-2", "--ticket", "nope", "--step", "x")
        ),
        "wrong step": cli(*base, "--module", "CP-2", "--step", "x"),
        "not next": cli("step-instructions", *("--module", "CP-0", "--ticket", "t", "--step", "y")),
    }
    for name, (code, out, err) in refusals.items():
        assert code == 2 and out == "" and len(err.splitlines()) == 1, name
    assert "credit_synthesis" in refusals["wrong step"][2]
    review = tmp_path / "r.json"
    review.write_text(synthesis().model_dump_json())
    settle = ("module-submit", "--module", "CP-2", "--ticket", ticket)
    assert cli(*settle, "--step", "credit_synthesis", "--review", str(review))[0] == 0
    code, out, err = cli(*base, "--module", "CP-2", "--step", "credit_synthesis")
    assert code == 2 and out == "" and "finished" in err and len(err.splitlines()) == 1


def test_a_step_that_is_not_the_tickets_next_is_refused_with_the_runners_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, ticket, _ = cp1_case(tmp_path)  # source_context is retained; financials is next
    cli = Cli(store, monkeypatch, capsys)
    code, out, err = cli(
        "step-instructions",
        *("--module", "CP-1", "--ticket", ticket.ticket_id, "--step", "quality"),
    )
    assert (
        code == 2
        and out == ""
        and err.splitlines()
        == [
            "step-instructions refused: quality is not the next step for this ticket; financials is"
        ]
    )


def test_the_live_runner_imports_without_a_credential_or_a_network() -> None:
    probe = "import deploy_vii.live.runner as r; print(len(r.STEPS))"
    done = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        env={"PATH": "", "HOME": "/nonexistent"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr


# --- M8c item 2: a rejected review exits 1 from every submit command ---


def rejected_exit(code: int, out: str, err: str) -> list[str]:
    """The attempt JSON on stdout, the validator's issue lines on stderr, exit 1."""
    issues = json.loads(out)["issues"] or next(
        s["issues"] for s in json.loads(out)["step_repairs"] if s["issues"]
    )
    assert code == 1 and issues and "Traceback" not in err
    assert err.splitlines() == issues
    return issues


def test_cp0_submit_exits_1_on_a_rejected_review_and_0_on_an_accepted_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, _ = cp0_case(tmp_path)
    cli = Cli(store, monkeypatch, capsys)
    ticket = json.loads(cli("begin", "CP-0")[1])["ticket_id"]
    review = tmp_path / "review.json"
    review.write_text("not json")
    rejected_exit(*cli("cp0-submit", "--ticket", ticket, "--review", str(review)))
    repair = json.loads(cli("begin", "CP-0")[1])["ticket_id"]
    review.write_text(readiness_fixture()[1].model_dump_json())
    code, out, err = cli("cp0-submit", "--ticket", repair, "--review", str(review))
    assert code == 0 and err == "" and json.loads(out)["status"] == "finished"


def test_cp1_submit_exits_1_on_a_rejected_review_kept_for_repair_and_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, ticket, _ = cp1_case(tmp_path)
    cli = Cli(store, monkeypatch, capsys)
    review = tmp_path / "review.json"
    review.write_text("not json")
    submit = ("cp1-submit", "--ticket", ticket.ticket_id, "--step", "financials")
    code, out, err = cli(*submit, "--review", str(review))
    assert json.loads(out)["status"] == "pending"  # kept for the step's one repair
    rejected_exit(code, out, err)
    code, out, err = cli(*submit, "--review", str(review))
    assert json.loads(out)["status"] == "finished"
    rejected_exit(code, out, err)


def test_cp1_promote_exits_1_on_a_rejected_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, attempt = staged(tmp_path)
    cli = Cli(store, monkeypatch, capsys)
    review = tmp_path / "review.json"
    review.write_text("not json")
    rejected_exit(*cli("cp1-promote", "--ticket", attempt.ticket_id, "--review", str(review)))


@pytest.mark.parametrize("command", ["cp0-submit", "cp1-submit", "cp1-promote"])
def test_a_missing_review_file_is_a_one_line_refusal_for_every_submit_command(
    cli: Cli, tmp_path: Path, command: str
) -> None:
    absent = tmp_path / "absent.json"
    step = ("--step", "source_context") if command == "cp1-submit" else ()
    code, out, err = cli(command, "--ticket", "t", *step, "--review", str(absent))
    assert code == 2 and out == "" and str(absent) in err and len(err.splitlines()) == 1
    assert err.startswith(f"{command} refused:")


def test_the_module_docstrings_name_no_private_runner_function() -> None:
    from deploy_vii import module_submits

    assert "_context_body" not in (module_submits.__doc__ or "")
    assert "_context_body" not in (host_context.__doc__ or "")
