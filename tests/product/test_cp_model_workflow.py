"""Task 7.1a: CP-MODEL's deterministic publication from a promoted CP-1 (decision 0006 DC-5)."""

import json
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

import tests.product.test_financials as financials
import tests.product.test_workflow as workflow
from deploy_vii import cp_model_workflow
from deploy_vii.contracts import PATHWAY_MODULES, Module, Run
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_render import model_destination_html
from deploy_vii.cp1_workflow import FinancialStage, cp1_registers, promote_cp1
from deploy_vii.cp_model_workflow import (
    OWN_RESTRICTION,
    CpModelRefused,
    _Basis,
    _basis,
    _verifier,
    candidate_module,
    publish_cp_model,
    verify_cp_model_publication,
)
from deploy_vii.execution import (
    Attempt,
    Execution,
    Head,
    Qualification,
    Validator,
    text_sha256,
)
from deploy_vii.financial_model import ModelReport
from deploy_vii.prose import prose_issues
from deploy_vii.registry import _NOT_CP5_FAN_IN, plan
from deploy_vii.report_view import status_display
from tests.product.test_browser import assert_offline, open_front
from tests.product.test_cp1_workflow import at_ceiling, staged
from tests.product.test_execution import cp_model_store, fixture_store, settle_module


@pytest.fixture(scope="module")
def model_scope() -> Iterator[pytest.MonkeyPatch]:
    """The synthetic CP-1 fixture, frozen into a run that requests CP-MODEL (decision 0009)."""
    patch = pytest.MonkeyPatch()
    patch.setattr(
        financials,
        "Run",
        lambda **kw: Run(**{**kw, "requested_modules": PATHWAY_MODULES["credit_snapshot"]}),
    )
    # CP-0 assesses live consumers only; CP-MODEL needs no readiness row (execution.current_inputs).
    patch.setattr(workflow, "plan", lambda scope: tuple(m for m in plan(scope) if m != "CP-MODEL"))
    yield patch
    patch.undo()


@pytest.fixture(scope="module")
def promoted(
    model_scope: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Execution:
    store, attempt = staged(tmp_path_factory.mktemp("journal"))
    inputs = cp1_quality_inputs(cp1_registers(store, attempt.ticket_id))
    promote_cp1(store, attempt.ticket_id, at_ceiling(inputs).model_dump_json())
    return store


def fresh(promoted: Execution, tmp_path: Path) -> Execution:
    """A private copy of the promoted journal, so a publication does not leak between tests."""
    shutil.copytree(promoted.directory, tmp_path / "journal")
    return Execution(tmp_path / "journal")


def heads(store: Execution) -> dict[str, Head]:
    return {h.module_id: h for h in store.read().heads}


def test_the_fixture_promotes_cp1_in_a_run_that_requests_cp_model(promoted: Execution) -> None:
    snapshot = promoted.read()
    assert "CP-MODEL" in snapshot.run.requested_modules
    assert heads(promoted)["CP-1"].status == "restricted"


def test_publication_writes_the_files_then_settles_a_head_that_names_them(
    promoted: Execution, tmp_path: Path
) -> None:
    store = fresh(promoted, tmp_path)
    finished = publish_cp_model(store, output=tmp_path / "model")
    assert not finished.issues and finished.status == "finished"
    head = heads(store)["CP-MODEL"]
    # CP-1 is restricted, so CP-MODEL carries its own restriction (and the synthetic marker).
    assert head.status == "restricted"
    assert head.qualification == Qualification(implementation="implemented")
    module = store.head_module(head)
    assert OWN_RESTRICTION in module.limitations and module.claims
    receipt = json.loads((tmp_path / "model" / "receipt.json").read_text())
    assert receipt["head_sha256"] == head.result_sha256 == finished.result_sha256
    assert receipt["cp1_head_sha256"] == heads(store)["CP-1"].result_sha256
    assert receipt["pack_sha256"] == store.read().pack_sha256
    assert receipt["qualification"] == head.qualification.model_dump(mode="json")
    assert {p.name for p in (tmp_path / "model").iterdir()} == {
        "model.html",
        "calculation.json",
        "receipt.json",
    }
    assert set(receipt["files"]) == {"model.html", "calculation.json"}
    for name, digest in receipt["files"].items():
        assert text_sha256((tmp_path / "model" / name).read_text()) == digest


def test_the_calculation_json_is_cp1s_model_report_and_the_manifest_binds_it(
    promoted: Execution, tmp_path: Path
) -> None:
    store = fresh(promoted, tmp_path)
    publish_cp_model(store, output=tmp_path / "model")
    raw = (tmp_path / "model" / "calculation.json").read_text()
    report = ModelReport.model_validate_json(raw)
    assert report.model_dump_json() == raw  # canonical: re-serialising changes nothing
    module = store.head_module(heads(store)["CP-MODEL"])
    text = {(f.table_id, f.row_id, f.field): f.text for f in module.facts}
    assert text["model-destination", "calculation-json", "path"] == "calculation.json"
    assert text["model-destination", "calculation-json", "sha256"] == text_sha256(raw)
    assert text["model-calculation", "schema-version", "value"] == "financial-model/3"
    assert text["model-provenance", "cp1-head", "sha256"] == heads(store)["CP-1"].result_sha256
    assert text["model-provenance", "pack", "sha256"] == store.read().pack_sha256
    assert [t.table_id for t in module.tables] == [
        "model-destination",
        "model-calculation",
        "model-provenance",
    ]
    # No bare figure in the claim text: it passes the journal's own prose check.
    assert prose_issues(module, names=(store.read().run.issuer_name,)) == ()


def test_publishing_twice_from_the_same_inputs_is_byte_identical(
    promoted: Execution, tmp_path: Path
) -> None:
    runs = []
    for label in ("a", "b"):
        (tmp_path / label).mkdir()
        store = fresh(promoted, tmp_path / label)
        publish_cp_model(store, output=tmp_path / label / "model")
        head = heads(store)["CP-MODEL"]
        runs.append(
            (
                head.result_sha256,
                store.head_module(head).model_dump_json(),
                (tmp_path / label / "model" / "model.html").read_bytes(),
                (tmp_path / label / "model" / "calculation.json").read_bytes(),
            )
        )
    assert runs[0] == runs[1]


def test_the_validator_refuses_a_candidate_that_is_not_its_rederivation(
    promoted: Execution, tmp_path: Path
) -> None:
    store = fresh(promoted, tmp_path)
    ticket = store.begin("CP-MODEL")
    candidate = candidate_module(store, ticket, _basis(store))
    extra = candidate.claims[0].model_copy(update={"claim_id": "extra"})
    forged = candidate.model_copy(update={"claims": (*candidate.claims, extra)})
    verdict = store.finish(
        ticket.ticket_id, forged.model_dump_json(), _verifier(store, ticket.ticket_id)
    )
    assert verdict.issues == ("CP-MODEL candidate differs from its re-derivation from the journal",)
    assert "CP-MODEL" not in heads(store)


def test_the_model_page_is_the_accepted_route_naming_the_published_head(
    promoted: Execution, tmp_path: Path
) -> None:
    store = fresh(promoted, tmp_path)
    publish_cp_model(store, output=tmp_path / "model")
    page = (tmp_path / "model" / "model.html").read_text()
    assert '"mode":"accepted"' in page and '"mode":"candidate"' not in page
    assert heads(store)["CP-MODEL"].result_sha256 in page  # the panel's head id is the journal's


def test_cp5_is_held_until_cp_model_is_published_then_begins(
    promoted: Execution, tmp_path: Path
) -> None:
    store = fresh(promoted, tmp_path)
    scope = store.read().run.requested_modules
    for module_id in plan(scope):
        if module_id not in _NOT_CP5_FAN_IN | {"CP-0", "CP-1", "CP-MODEL"}:
            settle_module(store, module_id)
    with pytest.raises(ValueError, match="upstream is unrun"):
        store.begin("CP-5")
    publish_cp_model(store, output=tmp_path / "model")
    assert store.begin("CP-5").module_id == "CP-5"


def refused_untouched(store: Execution, output: Path, match: str) -> None:
    before = store.read()
    with pytest.raises(CpModelRefused, match=match):
        publish_cp_model(store, output=output)
    assert store.read() == before  # no attempt begun, no head
    assert not output.exists() or (output.is_dir() and not any(output.iterdir()))


def test_a_run_that_does_not_request_cp_model_is_refused_before_any_write(
    tmp_path: Path,
) -> None:
    refused_untouched(fixture_store(tmp_path), tmp_path / "model", "does not request CP-MODEL")


def test_an_unpromoted_cp1_is_refused_before_any_write(tmp_path: Path) -> None:
    store = cp_model_store(tmp_path)
    refused_untouched(store, tmp_path / "model", "no accepted or restricted head")
    settle_module(store, "CP-1")  # settled by the engine, not promoted: no qualification
    refused_untouched(store, tmp_path / "model", "was not promoted")


def test_an_existing_output_directory_is_refused(promoted: Execution, tmp_path: Path) -> None:
    store = fresh(promoted, tmp_path)
    (tmp_path / "model").mkdir()
    refused_untouched(store, tmp_path / "model", "already exists")


def test_a_stale_cp1_head_is_refused(promoted: Execution, tmp_path: Path) -> None:
    store = fresh(promoted, tmp_path)
    store.replace_pack(store.pack().model_copy(update={"sources": ()}))
    assert heads(store)["CP-1"].status == "stale"
    refused_untouched(store, tmp_path / "model", "no accepted or restricted head")


def test_a_failed_write_interrupts_the_attempt_and_leaves_no_head(
    promoted: Execution, tmp_path: Path
) -> None:
    store = fresh(promoted, tmp_path)
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    with pytest.raises(CpModelRefused, match="publication failed"):
        publish_cp_model(store, output=blocker / "model")
    assert "CP-MODEL" not in heads(store)
    attempt = store.read().attempts[-1]
    assert attempt.module_id == "CP-MODEL" and attempt.status == "finished"
    assert attempt.interruption is not None and "publication failed" in attempt.interruption


def test_a_receipt_that_cannot_be_written_leaves_no_head(
    promoted: Execution, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = fresh(promoted, tmp_path)
    real = Path.write_text

    def fail_on_receipt(self: Path, data: str, **kwargs: str) -> int:
        if self.name == "receipt.json":
            raise OSError("disk full")
        return real(self, data, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_on_receipt)
    with pytest.raises(CpModelRefused, match="disk full"):
        publish_cp_model(store, output=tmp_path / "model")
    assert "CP-MODEL" not in heads(store)
    assert not (tmp_path / "model" / "receipt.json").exists()
    # The interruption consumed the attempt; the one repair may publish into a new directory.
    monkeypatch.undo()
    assert not publish_cp_model(store, output=tmp_path / "again").issues
    assert "CP-MODEL" in heads(store)


def test_the_cli_publishes_and_exits_2_with_the_reason_on_refusal(
    promoted: Execution,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from deploy_vii.__main__ import main

    store = fresh(promoted, tmp_path)
    argv = ["deploy-vii", "execution", "--directory", str(store.directory)]
    monkeypatch.setattr("sys.argv", [*argv, "cp-model-publish", "--output", str(tmp_path / "out")])
    main()
    shown = json.loads(capsys.readouterr().out)
    assert shown["module_id"] == "CP-MODEL" and shown["result"]["status"] == "restricted"
    with pytest.raises(SystemExit) as exit_:
        main()  # the output directory now exists
    assert exit_.value.code == 2
    assert "already exists" in capsys.readouterr().err


@pytest.mark.browser
def test_the_model_panel_of_the_published_page_shows_the_json_link_and_provenance(
    promoted: Execution, tmp_path: Path
) -> None:
    store = fresh(promoted, tmp_path)
    publish_cp_model(store, output=tmp_path / "model")
    head = heads(store)["CP-MODEL"]
    cp1 = heads(store)["CP-1"]
    with sync_playwright() as playwright:
        browser, page, requests, errors = open_front(
            playwright, tmp_path / "model" / "model.html", 1440, 900
        )
        page.goto((tmp_path / "model" / "model.html").as_uri() + "#CP-1")
        panel = page.locator("#view-root section", has_text="Calculation JSON")
        expect(panel.locator("h2")).to_have_text("Model")
        expect(panel.locator(".chip")).to_have_text(status_display("restricted")[1])
        link = panel.locator("a", has_text="calculation.json")
        assert (
            Path(link.evaluate("a => new URL(a.href).pathname"))
            == (tmp_path / "model" / "calculation.json").resolve()
        )
        expect(link).to_have_attribute("href", "calculation.json")
        provenance = (
            f"Published as head {head.result_sha256[:12]} from CP-1 head "
            f"{cp1.result_sha256[:12]} · pack {store.read().pack_sha256[:12]}"
        )
        expect(panel).to_contain_text(provenance)
        expect(page.locator("#view-root")).not_to_contain_text("Model not run")
        # The panel comes first, then CP-1's own register detail; no grid is invented.
        assert page.locator("#view-root section h2").first.text_content() == "Model"
        assert_offline(requests, errors)
        browser.close()


# --- fix round 1 -------------------------------------------------------------------------------


def test_a_second_consecutive_failure_leaves_a_blocked_head_and_a_third_is_refused(
    promoted: Execution, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 0007: the first failure leaves no head; the repair's failure blocks CP-MODEL."""
    store = fresh(promoted, tmp_path)
    real = Path.write_text

    def fail_on_receipt(self: Path, data: str, **kwargs: str) -> int:
        if self.name == "receipt.json":
            raise OSError("disk full")
        return real(self, data, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_on_receipt)
    with pytest.raises(CpModelRefused, match="disk full"):
        publish_cp_model(store, output=tmp_path / "one")
    assert "CP-MODEL" not in heads(store)
    with pytest.raises(CpModelRefused, match="disk full"):
        publish_cp_model(store, output=tmp_path / "two")
    blocked = heads(store)["CP-MODEL"]
    assert blocked.status == "blocked" and blocked.qualification is None
    limitations = store.head_module(blocked).limitations
    assert any("publication failed: " in text and "disk full" in text for text in limitations)
    monkeypatch.undo()
    with pytest.raises(CpModelRefused, match="settled or its one repair"):
        publish_cp_model(store, output=tmp_path / "three")
    assert not any(a.status == "pending" for a in store.read().attempts)


def test_a_pending_attempt_is_a_refusal_the_cli_reports_with_exit_2(
    promoted: Execution,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from deploy_vii.__main__ import main

    store = fresh(promoted, tmp_path)
    store.begin("CP-MODEL")  # left pending
    argv = ["deploy-vii", "execution", "--directory", str(store.directory)]
    monkeypatch.setattr("sys.argv", [*argv, "cp-model-publish", "--output", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as exit_:
        main()
    assert exit_.value.code == 2
    assert "An attempt is pending" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_inputs_changed_after_the_files_are_written_interrupts_the_ticket(
    promoted: Execution, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = fresh(promoted, tmp_path)
    real = Execution.finish
    calls: list[str] = []

    def finish_once_changed(self: Execution, ticket: str, *args: object, **kw: object) -> Attempt:
        calls.append(ticket)
        if len(calls) == 1:
            raise ValueError("Ticket inputs have changed")
        return real(self, ticket, *args, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(Execution, "finish", finish_once_changed)
    with pytest.raises(CpModelRefused, match="Ticket inputs have changed"):
        publish_cp_model(store, output=tmp_path / "model")
    assert not any(a.status == "pending" for a in store.read().attempts)
    assert "CP-MODEL" not in heads(store)
    assert (tmp_path / "model" / "receipt.json").is_file()  # a receipt without a head: unpublished


def tamper(store: Execution, change: Callable[[Attempt], Attempt]) -> None:
    """Rewrite the promoted CP-1 attempt in the journal (a test-only corruption)."""
    snapshot = store.read()
    head = heads(store)["CP-1"]
    attempts = tuple(
        change(a) if a.result_sha256 == head.result_sha256 else a for a in snapshot.attempts
    )
    store._write(snapshot.model_copy(update={"attempts": attempts}))


def steps_changed(index: int, **update: object) -> Callable[[Attempt], Attempt]:
    def change(attempt: Attempt) -> Attempt:
        steps = tuple(
            s.model_copy(update=update) if i == index else s for i, s in enumerate(attempt.steps)
        )
        return attempt.model_copy(update={"steps": steps})

    return change


@pytest.mark.parametrize(
    "change",
    [
        lambda a: a.model_copy(update={"steps": a.steps[:4]}),  # no quality step
        steps_changed(4, step_id="other"),
        steps_changed(1, step_id="other"),
        steps_changed(4, status="invalid", output_sha256=None, issues=("x",)),
        steps_changed(1, status="invalid", output_sha256=None, issues=("x",)),
    ],
    ids=["no-quality-step", "quality-id", "financials-id", "quality-output", "financials-output"],
)
def test_a_cp1_head_without_a_verified_handoff_is_refused(
    promoted: Execution, tmp_path: Path, change: Callable[[Attempt], Attempt]
) -> None:
    store = fresh(promoted, tmp_path)
    tamper(store, change)
    refused_untouched(store, tmp_path / "model", "not promoted through a verified handoff")


def test_a_cp1_without_a_calculated_model_is_refused_with_its_reasons(
    promoted: Execution, tmp_path: Path
) -> None:
    store = fresh(promoted, tmp_path)
    head = heads(store)["CP-1"]
    attempt = next(a for a in store.read().attempts if a.result_sha256 == head.result_sha256)
    assert attempt.steps[1].output_sha256 is not None
    stage = FinancialStage.model_validate_json(store.step_output(attempt.steps[1].output_sha256))
    bare = stage.model_copy(update={"model": None, "model_issues": ("No KPI inputs",)})
    sha = store._store(bare.model_dump_json())
    tamper(store, steps_changed(1, output_sha256=sha))
    refused_untouched(store, tmp_path / "model", "no calculated Model to publish: No KPI inputs")


def test_an_unreadable_journal_blob_is_a_refusal_not_a_traceback(
    promoted: Execution, tmp_path: Path
) -> None:
    store = fresh(promoted, tmp_path)
    head = heads(store)["CP-1"]
    attempt = next(a for a in store.read().attempts if a.result_sha256 == head.result_sha256)
    assert attempt.steps[4].output_sha256 is not None
    (store.directory / "blobs" / attempt.steps[4].output_sha256).unlink()
    refused_untouched(store, tmp_path / "model", "is missing")


def test_a_candidate_the_journal_would_not_settle_is_refused_and_interrupted(
    promoted: Execution, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = fresh(promoted, tmp_path)
    real = cp_model_workflow.candidate_module

    def with_a_bare_figure(store: Execution, attempt: Attempt, basis: _Basis) -> Module:
        module = real(store, attempt, basis)
        claim = module.claims[0].model_copy(update={"text": "Leverage reached 7.3 times."})
        return module.model_copy(update={"claims": (claim,)})

    monkeypatch.setattr(cp_model_workflow, "candidate_module", with_a_bare_figure)
    with pytest.raises(CpModelRefused, match="would settle rejected"):
        publish_cp_model(store, output=tmp_path / "model")
    assert "CP-MODEL" not in heads(store) and not (tmp_path / "model").exists()
    assert not any(a.status == "pending" for a in store.read().attempts)


def test_a_journal_that_settles_differently_than_predicted_is_reported(
    promoted: Execution, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = fresh(promoted, tmp_path)
    real = cp_model_workflow._verifier
    made: list[int] = []

    def verifier_that_turns(store: Execution, ticket: str) -> Validator:
        made.append(1)
        if len(made) == 1:  # the in-memory prediction; the finish gets a differing verdict
            return real(store, ticket)
        return lambda _: ("forced difference",)

    monkeypatch.setattr(cp_model_workflow, "_verifier", verifier_that_turns)
    with pytest.raises(CpModelRefused, match=r"settled a different CP-MODEL.*forced difference"):
        publish_cp_model(store, output=tmp_path / "model")
    assert "CP-MODEL" not in heads(store)


def test_the_destination_page_shows_only_a_settled_cp_model(
    promoted: Execution, tmp_path: Path
) -> None:
    store = fresh(promoted, tmp_path)
    ticket = store.begin("CP-MODEL")
    candidate = candidate_module(store, ticket, _basis(store))
    with pytest.raises(ValueError, match="settled CP-MODEL"):
        model_destination_html(store, tmp_path, candidate)  # a candidate, not a head
    other = candidate.model_copy(update={"module_id": "CP-1", "status": "accepted"})
    with pytest.raises(ValueError, match="settled CP-MODEL"):
        model_destination_html(store, tmp_path, other)


def test_an_accepted_cp1_head_adds_no_own_limitation(promoted: Execution, tmp_path: Path) -> None:
    """The candidate of an accepted CP-1 carries none. End to end, an accepted CP-1 cannot be
    built here: the fixture's CP-1 is restricted by its own subartifact notes and the run is
    synthetic, which would restrict CP-MODEL anyway."""
    store = fresh(promoted, tmp_path)
    ticket = store.begin("CP-MODEL")
    basis = _basis(store)
    accepted = basis.head.model_copy(update={"status": "accepted"})
    candidate = candidate_module(store, ticket, _Basis(accepted, basis.handoff, basis.report))
    assert candidate.limitations == ()


def test_the_receipt_differs_between_runs_by_ticket_only(
    promoted: Execution, tmp_path: Path
) -> None:
    receipts = []
    for label in ("a", "b"):
        (tmp_path / label).mkdir()
        store = fresh(promoted, tmp_path / label)
        publish_cp_model(store, output=tmp_path / label / "model")
        receipts.append(json.loads((tmp_path / label / "model" / "receipt.json").read_text()))
    assert receipts[0].pop("ticket_id") != receipts[1].pop("ticket_id")
    assert receipts[0] == receipts[1]


def published(promoted: Execution, tmp_path: Path) -> tuple[Execution, Path]:
    store = fresh(promoted, tmp_path)
    publish_cp_model(store, output=tmp_path / "model")
    return store, tmp_path / "model"


def test_an_untouched_publication_verifies_even_after_later_modules_settle(
    promoted: Execution, tmp_path: Path
) -> None:
    store, output = published(promoted, tmp_path)
    assert verify_cp_model_publication(store, output) == ()
    settle_module(store, "CP-1A")  # the journal moves on; the page does not depend on it
    assert verify_cp_model_publication(store, output) == ()


@pytest.mark.parametrize(
    ("name", "mutate", "expected"),
    [
        ("model.html", lambda raw: raw.replace("Model", "Mode1", 1), "model.html differs"),
        (
            "calculation.json",
            lambda raw: raw.replace("financial-model/3", "financial-model/9", 1),
            "calculation.json differs",
        ),
        (
            "receipt.json",
            lambda raw: raw.replace('"restricted"', '"accepted"', 1),
            "receipt.json differs",
        ),
    ],
)
def test_a_tampered_file_is_refused(
    promoted: Execution,
    tmp_path: Path,
    name: str,
    mutate: Callable[[str], str],
    expected: str,
) -> None:
    store, output = published(promoted, tmp_path)
    raw = (output / name).read_text()
    assert mutate(raw) != raw
    (output / name).write_text(mutate(raw))
    issues = verify_cp_model_publication(store, output)
    assert any(expected in issue for issue in issues), issues


def test_a_missing_file_a_missing_head_and_a_stale_head_are_refused(
    promoted: Execution, tmp_path: Path
) -> None:
    store, output = published(promoted, tmp_path)
    (output / "receipt.json").unlink()
    issues = verify_cp_model_publication(store, output)
    assert any("receipt.json cannot be read" in issue for issue in issues)
    (tmp_path / "x").mkdir()
    unpublished = fresh(promoted, tmp_path / "x")
    no_head = ("CP-MODEL has no accepted or restricted head in the journal",)
    assert verify_cp_model_publication(unpublished, output) == no_head
    store.replace_pack(store.pack().model_copy(update={"sources": ()}))
    assert verify_cp_model_publication(store, output) == no_head


def test_the_verify_command_prints_ok_and_exits_2_with_the_issues(
    promoted: Execution,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from deploy_vii.__main__ import main

    store, output = published(promoted, tmp_path)
    argv = ["deploy-vii", "execution", "--directory", str(store.directory)]
    monkeypatch.setattr("sys.argv", [*argv, "cp-model-verify", "--output", str(output)])
    main()
    assert json.loads(capsys.readouterr().out) == {"verified": True, "issues": []}
    (output / "calculation.json").write_text("{}")
    with pytest.raises(SystemExit) as exit_:
        main()
    assert exit_.value.code == 2
    assert "calculation.json differs" in capsys.readouterr().err
