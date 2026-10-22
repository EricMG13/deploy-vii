"""Task 6.5: the accepted CP-1 envelope drives the Credit Snapshot blocks; a refused one none."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from deploy_vii.bindings.shipped import SHIPPED_MAPS
from deploy_vii.contracts import PATHWAY_MODULES, Input, Module, View
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_render import envelope_view, refused_view, render_cp1_envelope
from deploy_vii.cp1_workflow import (
    EnvelopeRefused,
    cp1_binding_issues,
    cp1_registers,
    promote_cp1,
    read_cp1_envelope,
    write_cp1_envelope,
)
from deploy_vii.envelope import Envelope, read_envelope, write_envelope
from deploy_vii.execution import Execution, text_sha256
from deploy_vii.render import empty_view, render
from deploy_vii.report_view import Block, ReportView, build, pathways
from tests.product.credit_snapshot import CREDIT_SNAPSHOT_MAPS, credit_snapshot_view
from tests.product.test_cp1_workflow import at_ceiling, staged

CP1_BLOCKS = ("financials-credit-metrics", "capital-structure", "model-chart-strip")


def synthetic_envelope(status: str = "accepted") -> Envelope:
    """A SYNTHETIC accepted CP-1 envelope: the Credit Snapshot fixture's registers, as module/5."""
    view = credit_snapshot_view()
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")
    # The Credit Snapshot's own scope (decision 0009: CP-MODEL after CP-1), not the fixture's pin.
    run = view.run.model_copy(update={"requested_modules": PATHWAY_MODULES["credit_snapshot"]})
    module = Module.model_validate(
        {
            "run_id": view.run.run_id,
            "issuer_id": view.run.issuer_id,
            "as_of": view.run.as_of,
            "module_id": "CP-1",
            "status": status,
            "inputs": (Input(input_id="pack", sha256="b" * 64),),
            "facts": cp1.facts,
            "tables": cp1.tables,
            "limitations": () if status == "accepted" else ("Synthetic limitation",),
        }
    )
    return Envelope(run=run, module=module, registers_sha256="c" * 64)


def accepted_view() -> View:
    """The envelope, written and read back through 6.4's codec, over an idle accepted view."""
    envelope = read_envelope(*write_envelope(synthetic_envelope()))
    return envelope_view(empty_view(envelope.run, candidate=False), envelope)


def front(view: View) -> ReportView:
    pathway = next(p for p in pathways() if p.id == view.run.pathway)
    return build(view, pathway, SHIPPED_MAPS)


def block(report: ReportView, block_id: str) -> Block:
    return next(item for item in report.blocks if item.block_id == block_id)


def cells(item: Block) -> list[object]:
    """Every cell of a block, tabs included, by what a reader sees and what it cites."""
    tables = [(item.columns, item.rows), *((tab.columns, tab.rows) for tab in item.tabs)]
    return [
        (columns, row.row_id, [(c.text, c.state, c.prov) for c in row.cells])
        for columns, rows in tables
        for row in rows
    ]


def test_the_same_values_reach_the_same_cells_by_both_routes() -> None:
    candidate_view = credit_snapshot_view()
    candidate = build(
        candidate_view,
        next(p for p in pathways() if p.id == "credit_snapshot"),
        CREDIT_SNAPSHOT_MAPS,
    )
    view = accepted_view()
    accepted = front(view)
    assert view.mode == "accepted"
    assert next(m for m in view.modules if m.module_id == "CP-1").status == "accepted"
    for block_id in CP1_BLOCKS:
        assert cells(block(accepted, block_id)), block_id
        assert cells(block(accepted, block_id)) == cells(block(candidate, block_id)), block_id
        assert block(accepted, block_id).state == "populated"
    tabs = [tab.label for tab in block(accepted, "capital-structure").tabs]
    assert tabs == [tab.label for tab in block(candidate, "capital-structure").tabs]
    assert block(accepted, "capital-structure").tab_label == "Capital structure"
    assert "EBITDA adjustments" in tabs and len(tabs) == 2  # three tabs with the first
    # Identical exact text per fact: the envelope route spells what the candidate route spells.
    from_candidate = {
        f.fact_id: (f.amount, f.text, f.status)
        for m in candidate_view.modules
        if m.module_id == "CP-1"
        for f in m.facts
    }
    from_envelope = {
        f.fact_id: (f.amount, f.text, f.status)
        for m in view.modules
        if m.module_id == "CP-1"
        for f in m.facts
    }
    assert from_envelope == from_candidate


def test_a_restricted_envelope_shows_its_limitations() -> None:
    envelope = read_envelope(*write_envelope(synthetic_envelope("restricted")))
    view = envelope_view(empty_view(envelope.run, candidate=False), envelope)
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")
    assert cp1.status == "restricted" and cp1.limitations == ("Synthetic limitation",)
    assert block(front(view), "financials-credit-metrics").state == "populated"


def test_an_envelope_for_another_run_or_an_unsettled_module_is_not_shown() -> None:
    envelope = synthetic_envelope()
    other = View.model_validate_json(
        empty_view(envelope.run, candidate=False)
        .model_copy(update={"run": envelope.run.model_copy(update={"run_id": "another-run"})})
        .model_dump_json()
    )
    with pytest.raises(ValueError, match="another run"):
        envelope_view(other, envelope)
    candidate = envelope.model_copy(
        update={"module": envelope.module.model_copy(update={"status": "candidate"})}
    )
    with pytest.raises(ValueError, match="candidate envelope module"):
        envelope_view(empty_view(envelope.run, candidate=False), candidate)


def test_a_refused_envelope_renders_no_cp1_block_and_says_why() -> None:
    base = empty_view(synthetic_envelope().run, candidate=False)
    reason = "Envelope module is not the CP-1 head's settled module"
    view = refused_view(base, (reason, "Receipt pack_sha256 does not match the journal"))
    report = front(view)
    cp1 = next(m for m in view.modules if m.module_id == "CP-1")
    assert cp1.status == "blocked" and not cp1.facts and not cp1.tables
    assert cp1.limitations[0] == f"Canonical envelope refused: {reason}"
    for block_id in CP1_BLOCKS:
        item = block(report, block_id)
        assert item.state == "blocked" and not item.rows and not item.tabs and not item.figures
        assert reason in (item.note or ""), block_id
    assert not report.passports  # no figure of the refused envelope has a passport
    with pytest.raises(ValueError, match="states its issues"):
        refused_view(base, ())


def test_the_accepted_page_is_not_a_candidate_preview(tmp_path: Path) -> None:
    html = render(accepted_view())
    assert '"mode":"accepted"' in html and '"mode":"candidate"' not in html
    (tmp_path / "accepted.html").write_text(html, encoding="utf-8")


# --- the journal-bound route: a real promoted CP-1, exported and read back ---------------------


@pytest.fixture(scope="module")
def promoted(tmp_path_factory: pytest.TempPathFactory) -> tuple[Execution, Path]:
    """A store with a promoted CP-1 and its exported envelope (promotion is the slow step)."""
    root = tmp_path_factory.mktemp("promoted")
    store, attempt = staged(root / "journal")
    inputs = cp1_quality_inputs(cp1_registers(store, attempt.ticket_id))
    promote_cp1(store, attempt.ticket_id, at_ceiling(inputs).model_dump_json())
    return store, write_cp1_envelope(store, root / "envelope").parent


def copy_of(source: Path, tmp_path: Path) -> Path:
    shutil.copytree(source, tmp_path / "copy")
    return tmp_path / "copy"


def test_the_exported_envelope_reads_back_against_the_journal(
    promoted: tuple[Execution, Path],
) -> None:
    store, directory = promoted
    envelope = read_cp1_envelope(store, directory)
    head = next(h for h in store.read().heads if h.module_id == "CP-1")
    assert envelope.module.content_hash() == head.result_sha256
    assert envelope.module == store.head_module(head)


def rewrite(directory: Path, change: Callable[[Envelope], Envelope], *, receipt: bool) -> None:
    """Rewrite the Markdown and sidecar consistently with each other (and the receipt, if asked)."""
    envelope = read_envelope(
        (directory / "envelope.md").read_text(), (directory / "envelope.json").read_text()
    )
    markdown, sidecar = write_envelope(change(envelope))
    (directory / "envelope.md").write_text(markdown, encoding="utf-8")
    (directory / "envelope.json").write_text(sidecar, encoding="utf-8")
    if receipt:
        data = json.loads((directory / "complete.json").read_text())
        data["files"] = {
            "envelope.md": text_sha256(markdown),
            "envelope.json": text_sha256(sidecar),
        }
        (directory / "complete.json").write_text(json.dumps(data), encoding="utf-8")


def one_digit_changed(envelope: Envelope) -> Envelope:
    """The same envelope with one known statement amount nudged: a valid, consistent forgery."""
    fact = next(f for f in envelope.module.facts if f.status == "known" and f.amount is not None)
    assert fact.amount is not None
    forged = fact.model_copy(update={"amount": fact.amount + 1})
    facts = tuple(forged if f.fact_id == fact.fact_id else f for f in envelope.module.facts)
    module = envelope.module.model_copy(update={"facts": facts})
    return envelope.model_copy(update={"module": module})


def test_a_consistently_rewritten_pair_is_refused_by_its_receipt(
    promoted: tuple[Execution, Path], tmp_path: Path
) -> None:
    store, source = promoted
    directory = copy_of(source, tmp_path)
    rewrite(directory, one_digit_changed, receipt=False)
    # The pair verifies against itself (6.4's reader accepts it) but not against the receipt.
    read_envelope(
        (directory / "envelope.md").read_text(), (directory / "envelope.json").read_text()
    )
    with pytest.raises(EnvelopeRefused, match=r"envelope\.md differs from the receipt"):
        read_cp1_envelope(store, directory)


def test_a_pair_and_receipt_rewritten_together_are_refused_by_the_journal(
    promoted: tuple[Execution, Path], tmp_path: Path
) -> None:
    store, source = promoted
    directory = copy_of(source, tmp_path)
    rewrite(directory, one_digit_changed, receipt=True)
    with pytest.raises(EnvelopeRefused) as refused:
        read_cp1_envelope(store, directory)
    assert "Envelope module is not the CP-1 head's settled module" in refused.value.issues
    assert "Receipt module_sha256 does not match the journal" not in refused.value.issues


def test_every_journal_binding_is_checked_on_its_own(promoted: tuple[Execution, Path]) -> None:
    store, directory = promoted
    snapshot = store.read()
    envelope = read_cp1_envelope(store, directory)
    receipt = json.loads((directory / "complete.json").read_text())
    assert cp1_binding_issues(envelope, receipt, snapshot) == ()
    moved = snapshot.model_copy(update={"pack_sha256": "e" * 64})
    assert "Envelope pack differs from the journal's prepared pack" in cp1_binding_issues(
        envelope, receipt, moved
    )
    other_run = snapshot.model_copy(
        update={"run": snapshot.run.model_copy(update={"issuer_name": "Another issuer"})}
    )
    assert "Envelope run differs from the journal's run" in cp1_binding_issues(
        envelope, receipt, other_run
    )
    for key in ("quality_report_sha256", "qualification", "status", "registers_sha256"):
        issues = cp1_binding_issues(envelope, {**receipt, key: "forged"}, snapshot)
        assert issues == (f"Receipt {key} does not match the journal",), key
    unsettled = snapshot.model_copy(update={"heads": ()})
    assert cp1_binding_issues(envelope, receipt, unsettled) == (
        "CP-1 has no accepted or restricted head in the journal",
    )


def test_a_missing_or_malformed_export_is_refused_not_guessed(
    promoted: tuple[Execution, Path], tmp_path: Path
) -> None:
    store, source = promoted
    with pytest.raises(EnvelopeRefused, match="cannot be read"):
        read_cp1_envelope(store, tmp_path / "absent")
    directory = copy_of(source, tmp_path)
    (directory / "complete.json").write_text("[]", encoding="utf-8")
    with pytest.raises(EnvelopeRefused, match="not a cp1-envelope receipt"):
        read_cp1_envelope(store, directory)


def test_a_stale_head_refuses_the_export(promoted: tuple[Execution, Path]) -> None:
    store, source = promoted
    snapshot = store.read()
    stale = tuple(
        h.model_copy(update={"status": "stale"}) if h.module_id == "CP-1" else h
        for h in snapshot.heads
    )
    issues = cp1_binding_issues(
        read_cp1_envelope(store, source),
        json.loads((source / "complete.json").read_text()),
        snapshot.model_copy(update={"heads": stale}),
    )
    assert issues == ("CP-1 has no accepted or restricted head in the journal",)


def test_the_render_command_writes_the_verified_page_and_a_receipt(
    promoted: tuple[Execution, Path], tmp_path: Path
) -> None:
    store, directory = promoted
    receipt = render_cp1_envelope(store, directory, tmp_path / "page")
    assert receipt["envelope"] == "verified" and receipt["issues"] == []
    assert receipt["head_rendering_acceptance"] == "unrun"  # recorded as it stands, not set here
    assert receipt["browser_acceptance"] == "unrun"
    html = (tmp_path / "page" / "accepted.html").read_text()
    assert '"mode":"accepted"' in html and (tmp_path / "page" / "complete.json").is_file()
    with pytest.raises(FileExistsError):
        render_cp1_envelope(store, directory, tmp_path / "page")
    with pytest.raises(ValueError, match="immutable"):
        render_cp1_envelope(store, directory, tmp_path / "other", pathway="earnings_update")


def test_the_render_command_shows_a_refused_export_as_blocked(
    promoted: tuple[Execution, Path], tmp_path: Path
) -> None:
    store, source = promoted
    directory = copy_of(source, tmp_path)
    rewrite(directory, one_digit_changed, receipt=True)
    receipt = render_cp1_envelope(store, directory, tmp_path / "page")
    assert receipt["envelope"] == "refused" and receipt["module_sha256"] is None
    assert not (tmp_path / "page" / "accepted.html").exists()
    html = (tmp_path / "page" / "refused.html").read_text()
    assert "Canonical envelope refused: Envelope module is not the CP-1 head" in html
    assert json.loads((tmp_path / "page" / "complete.json").read_text()) == receipt


def test_the_render_cli_prints_the_receipt_and_refuses_an_existing_directory(
    promoted: tuple[Execution, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from deploy_vii.__main__ import main

    store, envelope = promoted
    output = tmp_path / "page"
    argv = ["deploy-vii", "execution", "--directory", str(store.directory)]
    argv += ["render", "--envelope", str(envelope), "--output", str(output)]
    monkeypatch.setattr("sys.argv", [*argv, "--pathway", "credit_snapshot"])
    main()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["envelope"] == "verified" and receipt["pathway"] == "credit_snapshot"
    assert {p.name for p in output.iterdir()} == {"accepted.html", "complete.json"}
    with pytest.raises(FileExistsError):
        main()
