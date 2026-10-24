"""Tier I2: every corpus entry re-validates offline through the journal's own validators."""

import json
import os
import shutil
import socket
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from deploy_vii import cp1_quality, cp1_workflow
from deploy_vii import envelope as envelope_writer
from deploy_vii.canonical_tables import CanonicalTables
from deploy_vii.contracts import Contract
from deploy_vii.cp1_workflow import FinancialSubmission
from deploy_vii.downstream_readiness import DownstreamInputs, DownstreamReview
from deploy_vii.envelope import Envelope
from deploy_vii.execution import Execution, StepValidation
from deploy_vii.live import cli, corpus
from deploy_vii.live.client import ChatClient
from deploy_vii.live.cohort import accept_proxy_payload
from deploy_vii.live.corpus import CorpusError, entry_from_attempt, write_entry
from deploy_vii.live.ledger import Ledger
from deploy_vii.live.retention import AttemptWriter
from deploy_vii.live.runner import StepSpec
from deploy_vii.live.schema import marked_fields
from deploy_vii.live.submission import (
    PREFILLED,
    SUPERSEDED_SHAPE,
    known_bindings,
    prefill,
    quality_inputs,
)
from deploy_vii.preparation import PreparedPack, load_pack
from tests.product import replay_support, transcript_support
from tests.product.live_support import FakeTransport, fixture_pool, make_rtf_key, ok
from tests.product.replay_support import OK, corpus_entries, replay_entry
from tests.product.test_cp1_workflow import at_ceiling
from tests.product.test_execution import step_text
from tests.product.test_live_runner import CP0, NOW, Rig, make_rig, reply
from tests.product.test_narrative import populated
from tests.product.test_readiness import readiness_fixture


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted in an offline replay test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


ROOT = Path(__file__).resolve().parents[2]
ENTRIES = corpus_entries()
replay_support_validate = cp1_workflow._validate_stage


REAL_KEYS = {"pack_sha256", "pack_source", "live", "expected_basis"}


def load_entry(path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return entry


def test_corpus_holds_labelled_synthetic_seed_entries_and_real_probe_entries() -> None:
    assert {p.parent.name for p in ENTRIES} == {
        "source_readiness",
        "source_context",
        "financials",
        "quality",  # task 7.10: the promotion and the QA Blocked verdict
    }
    assert {load_entry(p)["expected"]["validator_outcome"] for p in ENTRIES} == {
        "accepted",
        "rejected",
    }
    for path in ENTRIES:
        entry = load_entry(path)
        required = {"step_id", "payload", "input_hashes", "expected", "provenance"}
        assert set(entry["expected"]) == {"validator_outcome", "issues"}
        assert set(entry["provenance"]) == {"batch_id", "model", "attempt_id", "cohort"}
        if "pack" in entry:
            assert required <= set(entry) <= required | {"pack", "upstream", "payload_kind"}
            assert entry["pack"] in replay_support.PACKS
            assert entry["provenance"]["cohort"] == "synthetic"
            assert "synthetic" in path.stem and entry["provenance"]["batch_id"] == "synthetic"
            assert entry.get("payload_kind", "model") in replay_support.PAYLOAD_KINDS
        else:
            optional = {"superseded_by", "outcome_changed_by"}
            assert required | REAL_KEYS <= set(entry) <= required | REAL_KEYS | optional
            assert entry["provenance"]["cohort"] == "openrouter-pool"
            assert entry["pack_sha256"] == entry["input_hashes"]["prepared-pack"]
            if "superseded_by" in entry:  # decision 0008: a pre-0008 payload kept as evidence
                assert entry["superseded_by"] == "0008"
                assert entry["expected"]["issues"] == [SUPERSEDED_SHAPE]
                assert entry["expected_basis"] == "revalidated"
    assert sum("synthetic" in p.stem for p in ENTRIES) >= 2
    # Both payload paths are covered by synthetic seeds: stored contracts and model submissions.
    kinds = {load_entry(p).get("payload_kind", "model") for p in ENTRIES if "synthetic" in p.stem}
    assert kinds == {"journal", "model"}


REAL_ENTRIES = [p for p in ENTRIES if "pack_source" in load_entry(p)]


@pytest.mark.parametrize("path", REAL_ENTRIES, ids=lambda p: p.stem)
def test_real_entries_expect_the_recorded_live_issues(path: Path) -> None:
    """`expected` is the live verdict, or (after a deliberate wording change) a revalidation
    over the same pack that kept the live outcome, or one whose outcome a named validator fix
    changed (`outcome_changed_by`, always a revalidation)."""
    entry = load_entry(path)
    assert entry["expected_basis"] in {"live", "revalidated"}
    if "outcome_changed_by" in entry:
        assert isinstance(entry["outcome_changed_by"], str)
        assert entry["outcome_changed_by"].strip()
        assert entry["expected_basis"] == "revalidated"
        assert entry["expected"]["validator_outcome"] != entry["live"]["validator_outcome"]
    else:
        assert entry["expected"]["validator_outcome"] == entry["live"]["validator_outcome"]
    if entry["expected_basis"] == "live":
        assert entry["expected"]["issues"] == entry["live"]["issues"]
    # Where the attempt's evidence is present (not in CI), `live` is exactly what it recorded.
    provenance = entry["provenance"]
    found = sorted(
        (corpus.REPOSITORY_ROOT / "artifacts" / "model-tests" / provenance["batch_id"]).glob(
            f"*/*/{provenance['attempt_id']}/checks/validator.json"
        )
    )
    if not found:
        pytest.skip(f"attempt evidence for {path.stem} is not in this checkout")
    (validator,) = found
    recorded = json.loads(validator.read_text(encoding="utf-8"))
    assert entry["live"] == {"validator_outcome": recorded["outcome"], "issues": recorded["issues"]}


def test_registered_pack_hashes_match_the_builders(tmp_path: Path) -> None:
    for name, build in replay_support.PACKS.items():
        store, _ = build(tmp_path / name)
        assert corpus.SYNTHETIC_PACKS[name] == store.pack().content_hash(), name


def test_synthetic_cp1_pack_hash_is_stable_across_hash_seeds() -> None:
    code = (
        "import pathlib, tempfile;"
        "from tests.product.replay_support import PACKS;"
        "d = pathlib.Path(tempfile.mkdtemp());"
        "print(PACKS['synthetic-cp1'](d)[0].pack().content_hash())"
    )
    hashes = {
        subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for seed in ("0", "1", "2")
    }
    assert hashes == {corpus.SYNTHETIC_PACKS["synthetic-cp1"]}


@pytest.mark.parametrize("path", ENTRIES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_corpus_entry_replays_as_recorded(
    path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each entry replays as recorded. Task 7.12: the envelope writer hashes ``to_json()`` bytes
    (``envelope._content_hash``); for every envelope and register set the replay writes, that
    hash is ``content_hash()``'s (pydantic 2.14.1 / pydantic-core 2.50.1 when adopted), so a
    dependency bump that changes the dumped bytes fails here rather than moving a provenance
    hash. Task 7.15: checked within this one replay per entry, so a failure names its entry."""
    checked: list[str] = []  # kinds checked; models are not retained
    mismatched: list[str] = []
    write, register = envelope_writer.write_envelope, envelope_writer.register_envelope

    def check(kind: str, *models: Contract) -> None:
        checked.append(kind)
        mismatched.extend(
            f"{kind} {type(m).__name__}"
            for m in models
            if envelope_writer._content_hash(m) != m.content_hash()
        )

    def write_seen(envelope: Envelope) -> tuple[str, str]:
        check("envelope", envelope, envelope.module)
        return write(envelope)

    def register_seen(registers: CanonicalTables) -> Envelope:
        check("registers", registers)
        return register(registers)

    monkeypatch.setattr(envelope_writer, "write_envelope", write_seen)
    monkeypatch.setattr(cp1_workflow, "write_envelope", write_seen)
    monkeypatch.setattr(cp1_quality, "register_envelope", register_seen)
    verdict = replay_entry(path, tmp_path)
    assert mismatched == []
    if path.parent.name == "quality":
        assert {"envelope", "registers"} <= set(checked), checked
    if verdict.status == replay_support.SKIPPED:
        pytest.skip(str(verdict))  # counted and listed by `make replay`; never a pass
    assert verdict.passed, str(verdict)


def test_the_corpus_replays_quality_entries() -> None:
    """The envelope hash identity above is exercised: the corpus holds `quality` entries."""
    assert [path for path in ENTRIES if path.parent.name == "quality"]


@pytest.mark.parametrize(("case", "steps"), cli.REGRESSION_CASES, ids=lambda v: str(v))
def test_each_regression_cell_settles_on_a_recorded_entry_or_is_a_named_skip(
    case: str, steps: tuple[str, ...]
) -> None:
    """Task 8.6: a regression cell (`live regression`) whose settling step has no recorded
    corpus entry has no I2 baseline. It is a named skip here, listed by `make replay`, and the
    live regression skips it the same way (`cli.unrecorded_cases`); no fixture is recorded to
    make it pass."""
    settling = steps[-1]
    entries = [path for path in ENTRIES if path.parent.name == settling]
    if not entries:
        why = (
            "the corpus cannot record this step yet (live.corpus.SUPPORTED_STEPS)"
            if settling not in corpus.SUPPORTED_STEPS
            else "no live attempt has been recorded"
        )
        pytest.skip(f"cell {case}: no recorded corpus entry for {settling}: {why}")
    assert (case, settling) not in cli.unrecorded_cases()
    assert {load_entry(path)["step_id"] for path in entries} == {settling}


def test_the_dimension_prefill_leaves_every_recorded_financials_payload_as_recorded(
    tmp_path: Path,
) -> None:
    """Task 7.13: every accepted `financials` payload the corpus records (an entry's own or a
    later entry's upstream) already carries its bound scopes' strings, so the prefill writes
    none of them and finds nothing it cannot bind."""
    recorded = []
    for path in ENTRIES:
        entry = load_entry(path)
        if entry.get("pack") != "synthetic-cp1":
            continue
        if (
            entry["step_id"] == "financials"
            and entry["expected"]["validator_outcome"] == "accepted"
        ):
            recorded.append((path, entry, entry["payload"]))
        elif "financials" in entry.get("upstream", {}):
            recorded.append((path, entry, entry["upstream"]["financials"]))
    assert {path.parent.name for path, _, _ in recorded} == {"financials", "quality"}
    for index, (path, entry, payload) in enumerate(recorded):
        store, ticket = replay_support.PACKS[entry["pack"]](tmp_path / str(index))
        upstream = entry.get("upstream", {})["source_context"]
        assert not replay_support._submit(store, ticket, "source_context", upstream), path
        known = known_bindings(store, ticket.ticket_id, "financials")
        result = prefill(FinancialSubmission, payload, known, PREFILLED["financials"])
        assert "scope-dimension" not in result.kinds and result.unbound == (), path
        dimensions = [
            item.path
            for item in marked_fields(FinancialSubmission, json.loads(payload))
            if item.kind == "scope-dimension"
        ]
        assert dimensions and not set(dimensions) & set(result.unset), path


def seed(step: str, name: str) -> Path:
    return next(
        p for p in ENTRIES if p.parent.name == step and "synthetic" in p.stem and name in p.stem
    )


def test_replay_detects_changed_validator_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = seed("source_readiness", "accepted")
    assert replay_entry(path, tmp_path / "before").passed
    monkeypatch.setattr(
        "deploy_vii.cp0_workflow._validate_review",
        lambda *_: StepValidation(issues=("validator now objects",)),
    )
    verdict = replay_entry(path, tmp_path / "after")
    assert not verdict.passed and verdict.status == "outcome-changed"
    assert path.name in str(verdict) and "source_readiness" in str(verdict)


def test_replay_detects_changed_issue_text(tmp_path: Path) -> None:
    entry = json.loads(seed("source_readiness", "accepted").read_text(encoding="utf-8"))
    entry["payload"] = "{}"
    entry["expected"] = {"validator_outcome": "rejected", "issues": ["something else"]}
    path = tmp_path / "corpus" / "source_readiness" / "tampered.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(entry), encoding="utf-8")
    verdict = replay_entry(path, tmp_path / "work")
    assert verdict.status == "issues-changed" and "something else" in str(verdict)


def test_unmatched_input_hashes_are_stale_with_a_reason_not_a_pass(tmp_path: Path) -> None:
    entry = json.loads(seed("source_readiness", "accepted").read_text(encoding="utf-8"))
    entry["input_hashes"]["prepared-pack"] = "0" * 64
    path = tmp_path / "corpus" / "source_readiness" / "stale.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(entry), encoding="utf-8")
    verdict = replay_entry(path, tmp_path / "work")
    assert verdict.status == "stale-inputs" and not verdict.passed
    assert "prepared-pack" in verdict.reason


def write_variant(tmp_path: Path, step: str, **changes: object) -> Path:
    entry = json.loads(seed("source_readiness", "accepted").read_text(encoding="utf-8"))
    entry.update(changes)
    path = tmp_path / "corpus" / step / "variant.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(entry), encoding="utf-8")
    return path


def test_proxy_attempt_becomes_an_entry_in_its_own_cohort_and_the_report_lists_it(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    done = accept_proxy_payload(
        CP0,
        rig.submission,
        "claude-agent",
        store=rig.store,
        ticket_id=rig.ticket_id,
        ledger=rig.ledger,
        writer=rig.writer,
        batch_id="b",
        clock=lambda: NOW,
    )
    target = write_entry(done.directory, "proxy-case", root=tmp_path / "corpus")
    entry = json.loads(target.read_text(encoding="utf-8"))
    assert entry["provenance"]["cohort"] == "proxy:claude-agent"  # never written as pool
    verdict = replay_entry(target, tmp_path / "replay")
    assert verdict.passed and verdict.cohort == "proxy:claude-agent"
    assert "proxy:claude-agent" in str(verdict)


def test_entry_without_a_cohort_is_malformed_not_a_pass(tmp_path: Path) -> None:
    path = write_variant(tmp_path, "source_readiness", provenance={"batch_id": "x"})
    verdict = replay_entry(path, tmp_path / "w")
    assert verdict.status == "malformed" and "cohort" in verdict.reason


def test_attempt_manifest_without_a_cohort_is_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig))))
    manifest = result.directory / "manifest.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    del document["cohort"]
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CorpusError, match="cohort"):
        entry_from_attempt(result.directory)


def test_unreplayable_entries_fail_closed(tmp_path: Path) -> None:
    path = write_variant(tmp_path, "mystery", step_id="mystery")
    assert replay_entry(path, tmp_path / "w").status == "unsupported-step"


@pytest.mark.parametrize(
    ("changes", "needle"),
    [
        ({"pack": "synthetic-nowhere"}, "unknown synthetic pack"),
        ({"step_id": "source_context"}, "is not in directory"),
        ({"upstream": {"source_context": "{}"}}, "upstream must hold exactly"),
    ],
)
def test_inconsistent_entries_are_malformed(
    tmp_path: Path, changes: dict[str, object], needle: str
) -> None:
    verdict = replay_entry(write_variant(tmp_path, "source_readiness", **changes), tmp_path / "w")
    assert verdict.status == "malformed" and needle in verdict.reason


def test_missing_expected_key_and_bad_json_are_malformed(tmp_path: Path) -> None:
    entry = json.loads(seed("source_readiness", "accepted").read_text(encoding="utf-8"))
    del entry["expected"]
    path = tmp_path / "source_readiness" / "no-expected.json"
    path.parent.mkdir()
    path.write_text(json.dumps(entry), encoding="utf-8")
    assert replay_entry(path, tmp_path / "w").status == "malformed"
    path.write_text("not json", encoding="utf-8")
    assert replay_entry(path, tmp_path / "w2").status == "malformed"


def test_entry_without_a_registered_pack_is_stale_with_a_reason(tmp_path: Path) -> None:
    entry = json.loads(seed("source_readiness", "accepted").read_text(encoding="utf-8"))
    del entry["pack"]
    path = tmp_path / "source_readiness" / "no-pack.json"
    path.parent.mkdir()
    path.write_text(json.dumps(entry), encoding="utf-8")
    verdict = replay_entry(path, tmp_path / "w")
    assert verdict.status == "stale-inputs" and "no registered synthetic pack" in verdict.reason


def test_cp1_replay_detects_changed_validator_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = seed("financials", "accepted")
    assert replay_entry(path, tmp_path / "before").passed
    monkeypatch.setattr(
        "deploy_vii.cp1_workflow._validate_stage",
        lambda store, pack, attempt: (
            StepValidation(issues=("validator now objects",))
            if attempt.steps[-1].step_id == "financials"
            else replay_support_validate(store, pack, attempt)
        ),
    )
    verdict = replay_entry(path, tmp_path / "after")
    assert verdict.status == "outcome-changed" and path.name in str(verdict)


# --- writing entries from retained attempts (so the 2.6 probe can populate the corpus) ---


def test_accepted_attempt_becomes_an_entry_that_replays(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig))))
    assert result.status == "accepted"
    target = write_entry(result.directory, "probe-case-a", root=tmp_path / "corpus")
    entry = json.loads(target.read_text(encoding="utf-8"))
    assert entry["expected"] == {"validator_outcome": "accepted", "issues": []}
    assert entry["provenance"]["attempt_id"] == result.attempt_id
    assert entry["provenance"]["model"] == "openai/gpt-6-luna"
    assert entry["provenance"]["cohort"] == "openrouter-pool"
    assert entry["payload"] == rig.submission  # the model's raw output, not the composed review
    assert "payload_kind" not in entry  # a model payload: replayed through the composer
    assert replay_entry(target, tmp_path / "replay").passed


def test_a_pre_0008_attempt_replays_as_superseded(tmp_path: Path) -> None:
    """A model payload in the stored-review shape (probe-2) is rejected with the superseded-
    shape issue, live and in replay alike."""
    rig = make_rig(tmp_path)
    raw = rig.review.model_dump_json()
    result = rig.run(ChatClient(FakeTransport(reply(rig, content=raw))))
    assert result.status == "rejected" and result.issues == (SUPERSEDED_SHAPE,)
    target = write_entry(result.directory, "superseded", root=tmp_path / "corpus")
    entry = json.loads(target.read_text(encoding="utf-8"))
    assert entry["payload"] == raw
    assert entry["expected"] == {"validator_outcome": "rejected", "issues": [SUPERSEDED_SHAPE]}
    assert replay_entry(target, tmp_path / "replay").passed
    # The same payload handed to the journal directly (a stored contract) is still accepted.
    accepted = {"validator_outcome": "accepted", "issues": []}
    journal = {**entry, "payload_kind": "journal", "expected": accepted}
    target.write_text(json.dumps(journal), encoding="utf-8")
    assert replay_entry(target, tmp_path / "replay-journal").passed
    target.write_text(json.dumps({**entry, "payload_kind": "other"}), encoding="utf-8")
    verdict = replay_entry(target, tmp_path / "replay-bad")
    assert verdict.status == "malformed" and "payload_kind" in verdict.reason


def test_rejected_attempt_records_its_issues_and_replays(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(ok("{}"))))
    assert result.status == "rejected"
    target = write_entry(result.directory, "probe-case-b", root=tmp_path / "corpus")
    entry = json.loads(target.read_text(encoding="utf-8"))
    assert entry["expected"]["validator_outcome"] == "rejected" and entry["expected"]["issues"]
    assert replay_entry(target, tmp_path / "replay").status == OK


def test_withheld_fallback_attempt_is_not_an_entry(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = rig.run(
        ChatClient(FakeTransport(reply(rig, served="z-ai/glm-5.3-flash", provider="Other")))
    )
    assert result.status == "withheld-fallback"
    with pytest.raises(CorpusError, match="never reached"):
        write_entry(result.directory, "x", root=tmp_path / "corpus")


def test_entry_is_never_replaced_and_case_id_is_checked(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig))))
    write_entry(result.directory, "same", root=tmp_path / "corpus")
    with pytest.raises(CorpusError, match="--replace"):
        write_entry(result.directory, "same", root=tmp_path / "corpus")
    replaced = write_entry(result.directory, "same", root=tmp_path / "corpus", replace=True)
    assert replaced.is_file()
    with pytest.raises(CorpusError, match="case id"):
        write_entry(result.directory, "../escape", root=tmp_path / "corpus")


def test_unreplayable_step_and_incomplete_attempt_are_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig))))
    manifest = result.directory / "manifest.json"
    original = manifest.read_text(encoding="utf-8")
    manifest.write_text(original.replace('"step_id": "source_readiness"', '"step_id": "mystery"'))
    with pytest.raises(CorpusError, match="not replayable"):
        entry_from_attempt(result.directory)
    manifest.unlink()
    with pytest.raises(CorpusError, match="incomplete"):
        entry_from_attempt(result.directory)


def test_scrubbed_output_is_not_a_payload(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig))))
    manifest = result.directory / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["scrubbed_files"] = ["output.md"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CorpusError, match="scrubbing"):
        entry_from_attempt(result.directory)


def cp1_rig(tmp_path: Path) -> tuple[Rig, str, str]:
    """A live-dispatch rig on a fresh synthetic CP-1 ticket, plus the two canned payloads."""
    payloads = replay_support.cp1_seed_payloads(tmp_path / "seedwork")
    store, ticket = replay_support.PACKS["synthetic-cp1"](tmp_path / "live")
    keys = tmp_path / "keys"
    keys.mkdir()
    rig = Rig(
        store=store,
        ticket_id=ticket.ticket_id,
        ledger=Ledger(tmp_path / "ledger" / "l.jsonl", Decimal("5"), clock=lambda: NOW),
        pool=fixture_pool("batch-c"),
        writer=AttemptWriter(tmp_path / "artifacts"),
        key_path=make_rtf_key(keys),
        review=readiness_fixture()[1],
        root=tmp_path,
    )
    return rig, payloads["source_context"], payloads["financials"]


def run_cp1(rig: Rig, context: str, financials: str) -> tuple[Path, Path]:
    sources = tuple(s.source_id for s in rig.store.pack().sources)
    first = rig.run(
        ChatClient(FakeTransport(ok(context))), step=StepSpec("source_context", "c1", sources)
    )
    second = rig.run(
        ChatClient(FakeTransport(ok(financials))), step=StepSpec("financials", "c1", sources)
    )
    assert (first.status, second.status) == ("accepted", "accepted")
    return first.directory, second.directory


def test_cp1_attempts_become_entries_with_pack_and_upstream_that_replay(tmp_path: Path) -> None:
    rig, context, financials = cp1_rig(tmp_path)
    first, second = run_cp1(rig, context, financials)
    corpus_root = tmp_path / "corpus"
    for directory, name in ((first, "live-context"), (second, "live-financials")):
        target = write_entry(directory, name, root=corpus_root)
        assert replay_entry(target, tmp_path / ("r-" + name)).passed
    entry = json.loads((corpus_root / "financials" / "live-financials.json").read_text("utf-8"))
    assert entry["pack"] == "synthetic-cp1" and entry["upstream"] == {"source_context": context}
    first_entry = json.loads(
        (corpus_root / "source_context" / "live-context.json").read_text("utf-8")
    )
    assert "upstream" not in first_entry


def model_review(store: Execution, ticket_id: str, *, critical: bool = False) -> str:
    """What a model returns for `quality`: the at-ceiling review without the binding Python
    fills; with `critical`, one open CRITICAL finding, so QA is Blocked."""
    review = json.loads(at_ceiling(quality_inputs(store, ticket_id)).model_dump_json())
    del review["inputs_sha256"]
    if critical:
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


def run_quality(rig: Rig, context: str, financials: str, *, critical: bool) -> list[Path]:
    """The five CP-1 steps dispatched through the runner on one ticket (fake transport)."""
    directories = list(run_cp1(rig, context, financials))
    store = rig.store

    def valid(step_id: str) -> str:
        attempt = next(a for a in store.read().attempts if a.ticket_id == rig.ticket_id)
        return step_text(store, next(s for s in attempt.steps if s.step_id == step_id))

    stage = cp1_workflow.FinancialStage.model_validate_json(valid("financials"))
    narrative = populated(stage.narrative_inputs).model_dump_json()
    for step_id, payload in (
        ("narrative", lambda: narrative),
        ("readiness", lambda: readiness_review(valid("narrative"))),
        ("quality", lambda: model_review(store, rig.ticket_id, critical=critical)),
    ):
        result = rig.run(ChatClient(FakeTransport(ok(payload()))), step=StepSpec(step_id, "c1", ()))
        assert result.status == ("rejected" if critical and step_id == "quality" else "accepted")
        directories.append(result.directory)
    return directories


def readiness_review(narrative_output: str) -> str:
    inputs = DownstreamInputs.model_validate_json(narrative_output)
    return DownstreamReview(inputs_sha256=inputs.content_hash()).model_dump_json()


@pytest.mark.parametrize("critical", [False, True], ids=["accepted", "qa-blocked"])
def test_a_quality_attempt_becomes_an_entry_with_four_upstream_steps_that_replays(
    tmp_path: Path, critical: bool
) -> None:
    """Task 7.10 item 4: a `quality` attempt is recorded and replayed like the other steps,
    the promotion (accepted) and the QA Blocked verdict (rejected) alike."""
    rig, context, financials = cp1_rig(tmp_path)
    *_, quality = run_quality(rig, context, financials, critical=critical)
    target = write_entry(quality, "live-quality", root=tmp_path / "corpus")
    entry = json.loads(target.read_text(encoding="utf-8"))
    assert entry["step_id"] == "quality" and entry["pack"] == "synthetic-cp1"
    assert set(entry["upstream"]) == set(cp1_workflow.CP1_STEPS)
    assert entry["upstream"]["source_context"] == context
    if critical:
        (blocked,) = entry["expected"]["issues"]
        assert entry["expected"]["validator_outcome"] == "rejected"
        assert cp1_workflow.is_qa_blocked(blocked)
    else:
        assert entry["expected"] == {"validator_outcome": "accepted", "issues": []}
    verdict = replay_entry(target, tmp_path / "replay")
    assert verdict.passed, str(verdict)


def test_missing_upstream_attempt_is_refused_not_guessed(tmp_path: Path) -> None:
    rig, context, financials = cp1_rig(tmp_path)
    first, second = run_cp1(rig, context, financials)
    shutil.rmtree(first)
    with pytest.raises(CorpusError, match="earlier step"):
        entry_from_attempt(second)


def test_scrubbed_upstream_payload_is_refused(tmp_path: Path) -> None:
    rig, context, financials = cp1_rig(tmp_path)
    first, second = run_cp1(rig, context, financials)
    manifest = first / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["scrubbed_files"] = ["output.md"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CorpusError, match="scrubbing"):
        entry_from_attempt(second)


def test_two_accepted_attempts_for_one_upstream_step_are_refused(tmp_path: Path) -> None:
    rig, context, financials = cp1_rig(tmp_path)
    first, second = run_cp1(rig, context, financials)
    twin = first.with_name("zz-duplicate")
    shutil.copytree(first, twin)
    with pytest.raises(CorpusError, match="more than one accepted"):
        entry_from_attempt(second)
    shutil.rmtree(twin)
    twin = first.with_name("0-duplicate")  # sorts before the original: order must not matter
    shutil.copytree(first, twin)
    with pytest.raises(CorpusError, match="more than one accepted"):
        entry_from_attempt(second)


def test_corrupt_upstream_is_upstream_invalid_not_a_pass(tmp_path: Path) -> None:
    entry = json.loads(seed("financials", "accepted").read_text(encoding="utf-8"))
    entry["upstream"]["source_context"] = "{}"
    path = tmp_path / "corpus" / "financials" / "corrupt.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(entry), encoding="utf-8")
    verdict = replay_entry(path, tmp_path / "w")
    assert verdict.status == "upstream-invalid" and not verdict.passed
    assert "source_context" in verdict.reason


def test_unregistered_pack_leaves_pack_unset_and_replays_stale(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig))))
    manifest = result.directory / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["hashes"]["journal_inputs"]["prepared-pack"] = "1" * 64
    manifest.write_text(json.dumps(data), encoding="utf-8")
    target = write_entry(result.directory, "other-pack", root=tmp_path / "corpus")
    assert "pack" not in json.loads(target.read_text(encoding="utf-8"))
    verdict = replay_entry(target, tmp_path / "w")
    assert verdict.status == "stale-inputs" and "no registered synthetic pack" in verdict.reason


# --- 2.7a: real-pack entries (artifacts/public-case/<dir>) ---------------------------------


def case_pack(repository: Path, name: str = "case-x") -> PreparedPack:
    """A real-shaped case directory (pack.json, complete.json, originals) on a pack that no
    synthetic builder produces."""
    pack, _ = readiness_fixture()
    pack = pack.model_copy(
        update={"run": pack.run.model_copy(update={"issuer_name": "Case Pack Issuer"})}
    )
    directory = repository / "artifacts" / "public-case" / name
    (directory / "originals").mkdir(parents=True)
    source = pack.sources[0]
    assert source.sha256 is not None
    (directory / "originals" / source.sha256).write_bytes(
        b"Synthetic issuer FY2025 cash USD million 0\n"
    )
    (directory / "pack.json").write_text(pack.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (directory / "complete.json").write_text(
        json.dumps({"pack_sha256": pack.content_hash()}), encoding="utf-8"
    )
    assert load_pack(directory) == pack and pack.content_hash() not in SYNTHETIC
    return pack


SYNTHETIC = set(corpus.SYNTHETIC_PACKS.values())


def real_rig(tmp_path: Path) -> tuple[Rig, Path]:
    repository = tmp_path / "repository"
    pack = case_pack(repository)
    store = Execution.create(tmp_path / "journal", pack)
    keys = tmp_path / "keys"
    keys.mkdir()
    _, review = readiness_fixture()
    rig = Rig(
        store=store,
        ticket_id=store.begin("CP-0").ticket_id,
        ledger=Ledger(tmp_path / "ledger" / "l.jsonl", Decimal("5"), clock=lambda: NOW),
        pool=fixture_pool("batch-real"),
        writer=AttemptWriter(tmp_path / "artifacts"),
        key_path=make_rtf_key(keys),
        review=review.model_copy(update={"pack_sha256": pack.content_hash()}),
        root=tmp_path,
    )
    return rig, repository


def real_entry(tmp_path: Path, content: str | None = None) -> tuple[Path, Path, Path]:
    rig, repository = real_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig, content=content))))
    assert result.status in {"accepted", "rejected"}
    target = write_entry(
        result.directory, "real-case", root=tmp_path / "corpus", repository=repository
    )
    return target, repository, result.directory


def test_a_real_attempt_records_its_pack_and_replays_where_the_pack_is(tmp_path: Path) -> None:
    target, repository, directory = real_entry(tmp_path)
    entry = load_entry(target)
    assert "pack" not in entry and entry["pack_source"] == "artifacts/public-case/case-x"
    assert entry["pack_sha256"] == entry["input_hashes"]["prepared-pack"]
    validator = json.loads((directory / "checks" / "validator.json").read_text(encoding="utf-8"))
    live = {"validator_outcome": validator["outcome"], "issues": validator["issues"]}
    assert entry["live"] == entry["expected"] == live and entry["expected_basis"] == "live"
    verdict = replay_entry(target, tmp_path / "replay", repository=repository)
    assert verdict.passed, str(verdict)


def test_a_rejected_real_attempt_replays_the_live_validator_issues(tmp_path: Path) -> None:
    target, repository, _ = real_entry(tmp_path, content="{}")
    entry = load_entry(target)
    assert entry["expected"]["validator_outcome"] == "rejected" and entry["expected"]["issues"]
    assert replay_entry(target, tmp_path / "replay", repository=repository).passed


def test_an_absent_pack_skips_with_the_reason_and_is_never_a_pass(tmp_path: Path) -> None:
    target, _, _ = real_entry(tmp_path)
    verdict = replay_entry(target, tmp_path / "replay", repository=tmp_path / "elsewhere")
    assert verdict.status == "skipped-pack-absent" and not verdict.passed
    assert "artifacts/public-case/case-x is not present" in verdict.reason


def unloadable_pack(repository: Path, name: str, pack_sha256: str) -> None:
    """A case directory whose marker records `pack_sha256` but whose pack.json does not load
    under the current contract (an earlier `run/1` preparation)."""
    directory = repository / "artifacts" / "public-case" / name
    directory.mkdir(parents=True)
    (directory / "pack.json").write_text('{"run": {"schema": "run/1"}}\n', encoding="utf-8")
    (directory / "complete.json").write_text(
        json.dumps({"pack_sha256": pack_sha256}), encoding="utf-8"
    )


def test_find_case_pack_skips_an_unloadable_pack_with_the_reason_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repository = tmp_path / "repository"
    pack = case_pack(repository)
    unloadable_pack(repository, "a-earlier-preparation", pack.content_hash())  # sorts first
    with caplog.at_level("WARNING", logger="deploy_vii.live.corpus"):
        found = corpus.find_case_pack(pack.content_hash(), repository)
    assert found == "artifacts/public-case/case-x"
    (skipped,) = caplog.messages
    assert "artifacts/public-case/a-earlier-preparation" in skipped
    assert "does not load under the current pack contract" in skipped


def test_find_case_pack_finds_nothing_when_no_candidate_loads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repository = tmp_path / "repository"
    unloadable_pack(repository, "a-earlier-preparation", "2" * 64)
    with caplog.at_level("WARNING", logger="deploy_vii.live.corpus"):
        assert corpus.find_case_pack("2" * 64, repository) is None
    assert len(caplog.messages) == 1 and "a-earlier-preparation" in caplog.messages[0]


def test_a_present_pack_that_hashes_differently_is_stale_inputs(tmp_path: Path) -> None:
    target, repository, _ = real_entry(tmp_path)
    marker = repository / "artifacts" / "public-case" / "case-x" / "complete.json"
    good = marker.read_text(encoding="utf-8")
    marker.write_text(json.dumps({"pack_sha256": "0" * 64}), encoding="utf-8")
    verdict = replay_entry(target, tmp_path / "replay", repository=repository)
    assert verdict.status == "stale-inputs" and "cannot be loaded" in verdict.reason
    # An intact pack whose hash is not the one the entry recorded.
    marker.write_text(good, encoding="utf-8")
    entry = load_entry(target)
    entry["pack_sha256"] = entry["input_hashes"]["prepared-pack"] = "1" * 64
    other = tmp_path / "corpus" / "source_readiness" / "other.json"
    other.write_text(json.dumps(entry), encoding="utf-8")
    verdict = replay_entry(other, tmp_path / "replay2", repository=repository)
    assert verdict.status == "stale-inputs" and "1" * 64 in verdict.reason


@pytest.mark.parametrize(
    "changes, needle",
    [
        ({"pack_sha256": "2" * 64}, "pack_sha256 must equal"),
        ({"pack": "synthetic-cp0"}, "not both"),
        ({"pack_source": "artifacts/public-case/../../etc"}, "is not artifacts/public-case"),
    ],
)
def test_inconsistent_real_entries_are_malformed(
    tmp_path: Path, changes: dict[str, object], needle: str
) -> None:
    target, repository, _ = real_entry(tmp_path)
    entry = {**load_entry(target), **changes}
    target.write_text(json.dumps(entry), encoding="utf-8")
    verdict = replay_entry(target, tmp_path / "replay", repository=repository)
    assert verdict.status == "malformed" and needle in verdict.reason


def test_expected_comes_from_the_recorded_validator_check(tmp_path: Path) -> None:
    rig, repository = real_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig, content="{}"))))
    check = result.directory / "checks" / "validator.json"
    check.write_text(json.dumps({"outcome": "rejected", "issues": ["edited"]}), encoding="utf-8")
    with pytest.raises(CorpusError, match="disagree"):
        entry_from_attempt(result.directory, repository=repository)


def test_revalidation_regenerates_wording_but_never_the_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, repository = real_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig, content="{}"))))
    live = entry_from_attempt(result.directory, repository=repository)["live"]
    monkeypatch.setattr(corpus, "_validate_now", lambda *_: ["reworded issue"])
    entry = entry_from_attempt(result.directory, repository=repository, revalidate=True)
    assert entry["expected"] == {"validator_outcome": "rejected", "issues": ["reworded issue"]}
    assert entry["live"] == live and entry["expected_basis"] == "revalidated"
    monkeypatch.setattr(corpus, "_validate_now", lambda *_: [])
    with pytest.raises(CorpusError, match="changed the outcome"):
        entry_from_attempt(result.directory, repository=repository, revalidate=True)
    with pytest.raises(CorpusError, match="needs a real case pack"):
        entry_from_attempt(result.directory, repository=tmp_path / "nowhere", revalidate=True)


FIXED_BY = "task 2.9 (decision 0008 amendment, 22 Oct 2026)"


def test_an_outcome_change_needs_a_named_validator_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, repository = real_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig, content="{}"))))
    live = entry_from_attempt(result.directory, repository=repository)["live"]
    assert live["validator_outcome"] == "rejected"
    # An unchanged outcome refuses the flag: it records nothing a wording change would not.
    with pytest.raises(CorpusError, match="did not change"):
        entry_from_attempt(
            result.directory, repository=repository, revalidate=True, outcome_changed_by=FIXED_BY
        )
    monkeypatch.setattr(corpus, "_validate_now", lambda *_: [])
    with pytest.raises(CorpusError, match="changed the outcome"):  # unflagged: still refused
        entry_from_attempt(result.directory, repository=repository, revalidate=True)
    for blank in ("", "  "):
        with pytest.raises(CorpusError, match="names the task or decision"):
            entry_from_attempt(
                result.directory, repository=repository, revalidate=True, outcome_changed_by=blank
            )
    with pytest.raises(CorpusError, match="only with --revalidate"):
        entry_from_attempt(result.directory, repository=repository, outcome_changed_by=FIXED_BY)
    entry = entry_from_attempt(
        result.directory, repository=repository, revalidate=True, outcome_changed_by=FIXED_BY
    )
    assert entry["expected"] == {"validator_outcome": "accepted", "issues": []}
    assert entry["live"] == live and entry["expected_basis"] == "revalidated"
    assert entry["outcome_changed_by"] == FIXED_BY


def test_an_entry_whose_outcome_a_validator_fix_changed_replays_the_new_outcome(
    tmp_path: Path,
) -> None:
    """A valid attempt recorded as rejected by an older validator (the probe-3 shape)."""
    rig, repository = real_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig))))
    assert result.status == "accepted"
    older = {"outcome": "rejected", "issues": ["Quote/locator mismatch: filing line:1"]}
    manifest = load_entry(result.directory / "manifest.json")
    manifest.update(status="rejected", validator=older)
    (result.directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (result.directory / "checks" / "validator.json").write_text(json.dumps(older), "utf-8")
    target = write_entry(
        result.directory,
        "fixed",
        root=tmp_path / "corpus",
        repository=repository,
        revalidate=True,
        outcome_changed_by=FIXED_BY,
    )
    entry = load_entry(target)
    assert entry["expected"]["validator_outcome"] == "accepted"
    assert entry["live"] == {"validator_outcome": "rejected", "issues": older["issues"]}
    verdict = replay_entry(target, tmp_path / "replay", repository=repository)
    assert verdict.passed, str(verdict)


def test_revalidating_a_pre_0008_real_attempt_marks_it_superseded(tmp_path: Path) -> None:
    rig, repository = real_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig, content=rig.review.model_dump_json()))))
    entry = entry_from_attempt(result.directory, repository=repository, revalidate=True)
    assert entry["expected"] == {"validator_outcome": "rejected", "issues": [SUPERSEDED_SHAPE]}
    assert entry["superseded_by"] == "0008" and entry["expected_basis"] == "revalidated"
    plain = entry_from_attempt(result.directory, repository=repository)
    assert "superseded_by" not in plain  # only revalidation decides it


def test_revalidation_runs_the_current_validator_over_the_real_pack(tmp_path: Path) -> None:
    rig, repository = real_rig(tmp_path)
    result = rig.run(ChatClient(FakeTransport(reply(rig, content="{}"))))
    entry = entry_from_attempt(result.directory, repository=repository, revalidate=True)
    assert entry["expected"] == entry["live"]  # same validator, same wording


def test_default_corpus_root_is_the_repository_corpus() -> None:
    assert corpus.CORPUS_ROOT == Path(replay_support.__file__).parent / "replay"
    assert CP0.step_id in corpus.SUPPORTED_STEPS


# --- task 8.0d: tool transcripts ------------------------------------------------------------------

TRANSCRIPTS = transcript_support.transcript_entries()


def test_the_transcripts_hold_synthetic_and_harness_entries_of_every_tool_step() -> None:
    entries = [load_entry(path) for path in TRANSCRIPTS]
    assert {e["schema"] for e in entries} == {transcript_support.SCHEMA}
    assert {e["kind"] for e in entries} == {"synthetic", "harness"}
    harness = {e["step_id"] for e in entries if e["kind"] == "harness"}
    assert harness == {"source_context", "financials", "narrative", "readiness"}
    # Raw artifacts stay out of Git: a harness entry names its files and their hashes only.
    assert all("replies" not in e for e in entries if e["kind"] == "harness")


@pytest.mark.parametrize("path", TRANSCRIPTS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_a_tool_transcript_replays_as_recorded(path: Path, tmp_path: Path) -> None:
    status, reason = transcript_support.check(load_entry(path), tmp_path)
    if status == transcript_support.SKIPPED:
        pytest.skip(f"{path.parent.name}/{path.stem}: {status}: {reason}")  # never a pass
    assert status == transcript_support.OK, f"{status}: {reason}"


SYNTHETIC_TRANSCRIPT = transcript_support.TRANSCRIPT_ROOT / "source_context"


def test_a_transcript_replay_detects_a_changed_reply_and_an_unnamed_prompt_change(
    tmp_path: Path,
) -> None:
    entry = load_entry(SYNTHETIC_TRANSCRIPT / "synthetic-search-reject-accept.json")
    changed = json.loads(json.dumps(entry))
    calls = changed["replies"][0]["choices"][0]["message"]["tool_calls"]
    calls[0]["function"]["arguments"] = json.dumps({"query": "debt"})
    status, reason = transcript_support.check(changed, tmp_path / "a")
    assert (status, reason) == ("request-changed", "call 2: the conversation, tools or parameters")
    prompt = json.loads(json.dumps(entry))
    prompt["expected"]["requests"][0]["system_sha256"] = "0" * 64
    status, reason = transcript_support.check(prompt, tmp_path / "b")
    assert (status, reason) == ("request-changed", "call 1: the system prompt (unnamed change)")
    verdict = json.loads(json.dumps(entry))
    verdict["expected"]["submits"][0]["outcome"] = "accepted"
    assert transcript_support.check(verdict, tmp_path / "c")[0] == "outcome-changed"
    ruled = json.loads(json.dumps(entry))
    ruled["rules"]["submits"] = []
    assert transcript_support.check(ruled, tmp_path / "d")[0] == "rules-changed"


def test_a_harness_transcript_whose_reply_file_changed_is_a_failure(tmp_path: Path) -> None:
    entry = load_entry(
        transcript_support.TRANSCRIPT_ROOT / "readiness" / "hybrid-cp1-6-sol-medium.json"
    )
    start = tmp_path / "repo" / entry["start_journal"]
    synthetic = transcript_support.synthetic_start(tmp_path / "s", {})
    shutil.copytree(synthetic, start)
    transcript = tmp_path / "repo" / entry["transcript"]
    transcript.mkdir(parents=True)
    for name in entry["evidence_sha256"]:
        (transcript / name).write_bytes(b"{}")
    status, reason = transcript_support.check(entry, tmp_path / "w", repository=tmp_path / "repo")
    assert status == "evidence-changed" and reason.endswith("does not hash as recorded")
