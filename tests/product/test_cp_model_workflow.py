"""Task 7.1a: CP-MODEL's deterministic publication from a promoted CP-1 (decision 0006 DC-5)."""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

import tests.product.test_financials as financials
import tests.product.test_workflow as workflow
from deploy_vii.contracts import PATHWAY_MODULES, Run
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_workflow import cp1_registers, promote_cp1
from deploy_vii.cp_model_workflow import (
    OWN_RESTRICTION,
    CpModelRefused,
    _basis,
    _verifier,
    candidate_module,
    publish_cp_model,
)
from deploy_vii.execution import Execution, Head, Qualification, text_sha256
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
