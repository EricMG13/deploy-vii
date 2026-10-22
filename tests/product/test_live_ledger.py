"""Reservation ledger: cap enforcement, atomic persistence, reconciliation (Decimal only)."""

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deploy_vii.live import ledger as ledger_module
from deploy_vii.live.ledger import ADJUST_404_SOURCE, CapExceeded, Ledger, LedgerError

D = Decimal


def make(tmp_path: Path, cap: str = "1.00") -> Ledger:
    return Ledger(tmp_path / "ledger.jsonl", D(cap), clock=lambda: "2026-10-21T10:00:00Z")


def lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_reservation_refuses_dispatch_beyond_cap(tmp_path: Path) -> None:
    ledger = make(tmp_path, "1.00")
    first = ledger.reserve("a1", D("0.60"))
    assert first.attempt_id == "a1" and first.usd == D("0.60")
    before = (tmp_path / "ledger.jsonl").read_bytes()
    with pytest.raises(CapExceeded) as raised:
        ledger.reserve("a2", D("0.41"))
    assert raised.value.requested == D("0.41") and raised.value.cap == D("1.00")
    assert raised.value.committed == D("0.60")
    assert (tmp_path / "ledger.jsonl").read_bytes() == before  # nothing written on refusal
    ledger.reserve("a3", D("0.40"))  # exactly at the cap is allowed
    state = ledger.state()
    assert state.reserved == D("1.00") and state.spent == D(0) and state.remaining == D(0)
    with pytest.raises(CapExceeded):
        ledger.reserve("a4", D("0.0000001"))
    # Spent money counts against the cap just as reservations do.
    ledger.settle("a1", D("0.55"), "usage.cost")
    assert ledger.state().remaining == D("0.05")
    with pytest.raises(CapExceeded):
        ledger.reserve("a5", D("0.06"))
    ledger.reserve("a5", D("0.05"))


def test_ledger_persists_atomically_and_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = make(tmp_path, "10")
    ledger.reserve("a1", D("2.50"))
    path = tmp_path / "ledger.jsonl"
    good = path.read_bytes()

    # A crash between writing the new content and the rename leaves the old ledger intact.
    def crash(src: object, dst: object) -> None:
        raise OSError("power cut")

    monkeypatch.setattr(ledger_module.os, "replace", crash)
    with pytest.raises(OSError, match="power cut"):
        ledger.reserve("a2", D("1.00"))
    monkeypatch.undo()
    assert path.read_bytes() == good
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".ledger-")] == []

    # Crash between reserve and settle: a fresh process still sees the reserved line.
    restarted = make(tmp_path, "10")
    state = restarted.state()
    assert state.reserved == D("2.50") and state.spent == D(0)
    assert [(a.attempt_id, a.status) for a in state.attempts] == [("a1", "reserved")]
    with pytest.raises(CapExceeded):
        restarted.reserve("a2", D("7.51"))  # the dangling reservation still counts
    restarted.reserve("a2", D("7.50"))

    # Reconcile against the returned cost: the reservation is released, only actual is spent.
    done = restarted.settle("a1", D("0.1234"), "usage.cost")
    assert done.charged == D("0.1234") and not done.overrun
    state = restarted.state()
    assert (state.reserved, state.spent) == (D("7.50"), D("0.1234"))
    record = {a.attempt_id: a for a in state.attempts}["a1"]
    assert record.status == "settled" and record.actual_usd == D("0.1234")
    assert record.basis == "usage.cost" and record.reserved_usd == D("2.50")

    # Unknown actual: the full reservation is held as spent (worst case), flagged as such.
    held = restarted.settle("a2", None, "usage absent; worst case held")
    assert held.charged == D("7.50") and held.unreconciled
    assert restarted.state().spent == D("7.6234") and restarted.state().reserved == D(0)

    # Append-only: earlier lines are never rewritten, and the derived state agrees.
    written = lines(path)
    assert [line["event"] for line in written] == ["open", "reserve", "reserve", "settle", "settle"]
    assert [line["seq"] for line in written] == [1, 2, 3, 4, 5]
    assert path.read_bytes().startswith(good)
    derived = json.loads((tmp_path / "ledger.jsonl.state.json").read_text(encoding="utf-8"))
    assert derived["spent"] == "7.6234" and derived["reserved"] == "0" and derived["cap"] == "10"
    assert derived["derived_from_lines"] == 5


def test_overrun_is_recorded_not_hidden(tmp_path: Path) -> None:
    ledger = make(tmp_path, "1.00")
    ledger.reserve("a1", D("0.10"))
    outcome = ledger.settle("a1", D("0.25"), "usage.cost exceeded the reservation")
    assert outcome.overrun and outcome.charged == D("0.25")
    state = ledger.state()
    assert state.spent == D("0.25") and state.overrun == D("0.15")
    ledger.reserve("a2", D("0.75"))
    with pytest.raises(CapExceeded):
        ledger.reserve("a3", D("0.01"))


def test_zero_actual_is_a_known_zero_not_unknown(tmp_path: Path) -> None:
    ledger = make(tmp_path)
    ledger.reserve("a1", D("0.30"))
    outcome = ledger.settle("a1", D(0), "rejected before inference")
    assert outcome.charged == D(0) and not outcome.unreconciled
    assert ledger.state().spent == D(0) and ledger.state().remaining == D("1.00")


@pytest.mark.parametrize(
    "action",
    [
        "duplicate-reserve",
        "settle-unknown",
        "double-settle",
        "negative",
        "negative-actual",
        "blank",
    ],
)
def test_invalid_ledger_operations_are_refused(tmp_path: Path, action: str) -> None:
    ledger = make(tmp_path)
    ledger.reserve("a1", D("0.1"))
    if action == "double-settle":
        ledger.settle("a1", D("0.05"), "r")
    with pytest.raises(LedgerError):
        if action == "duplicate-reserve":
            ledger.reserve("a1", D("0.1"))
        elif action == "settle-unknown":
            ledger.settle("zzz", D("0.1"), "r")
        elif action == "double-settle":
            ledger.settle("a1", D("0.05"), "r")
        elif action == "negative":
            ledger.reserve("a2", D("-0.1"))
        elif action == "negative-actual":
            ledger.settle("a1", D("-1"), "r")
        else:
            ledger.settle("a1", D("0.01"), "  ")


def test_corrupt_or_foreign_lines_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = make(tmp_path)
    ledger.reserve("a1", D("0.1"))
    good = path.read_bytes()
    for damage in (
        good + b'{"seq": 3, "event": "reserve"',  # torn final line
        good + b'{"seq": 3, "event": "reserve", "attempt_id": "x", "usd": "1"}',  # no newline
        good + b'{"seq": 3, "event": "reserve", "usd": "1"}\n',  # no attempt id
        good + b'{"seq": 3, "event": "settle", "attempt_id": "zzz", "charged_usd": "1"}\n',
        good + b'{"seq": 6, "event": "reserve", "attempt_id": "x", "usd": "1"}\n',  # gap
        good + b'{"seq": 3, "event": "refund", "attempt_id": "a1"}\n',  # unknown event
        good + b'{"seq": 3, "event": "settle", "attempt_id": "a1", "charged_usd": "q"}\n',
        b"[]\n",
    ):
        path.write_bytes(damage)
        with pytest.raises(LedgerError):
            make(tmp_path).state()
        with pytest.raises(LedgerError):
            make(tmp_path).reserve("zz", D("0.01"))
    path.write_bytes(good)
    assert make(tmp_path).state().reserved == D("0.1")


def test_ledger_is_bound_to_the_cap_it_was_opened_with(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = make(tmp_path, "1.00")
    ledger.reserve("a1", D("0.5"))
    first = lines(path)[0]
    assert first["event"] == "open" and first["seq"] == 1 and first["cap_usd"] == "1.00"
    assert make(tmp_path, "1").state().reserved == D("0.5")  # numerically equal is the same cap
    for other in ("2.00", "0.50"):
        with pytest.raises(LedgerError, match=r"opened with a cap of 1\.00"):
            make(tmp_path, other).state()
        with pytest.raises(LedgerError, match="new ledger file"):
            make(tmp_path, other).reserve("a2", D("0.01"))
        with pytest.raises(LedgerError, match="opened with a cap"):
            make(tmp_path, other).settle("a1", D("0.1"), "r")
    assert path.read_bytes().count(b"\n") == 2  # nothing was appended by the refused calls
    # A file whose first line is not an opening line, or that opens twice, is refused.
    body = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(body[1:]))
    with pytest.raises(LedgerError, match=r"no opening line|breaks the sequence"):
        make(tmp_path, "1.00").state()
    path.write_bytes(body[0] + body[0].replace(b'"seq": 1', b'"seq": 2') + b"".join(body[1:]))
    with pytest.raises(LedgerError):
        make(tmp_path, "1.00").state()
    first_line = json.loads(body[1])
    first_line["seq"] = 1
    path.write_bytes(json.dumps(first_line).encode() + b"\n")
    with pytest.raises(LedgerError, match="no opening line"):
        make(tmp_path, "1.00").state()


def test_an_absent_ledger_is_empty_and_cap_must_be_positive(tmp_path: Path) -> None:
    state = make(tmp_path, "3").state()
    assert (state.reserved, state.spent, state.attempts) == (D(0), D(0), ())
    with pytest.raises(LedgerError, match="cap"):
        Ledger(tmp_path / "x.jsonl", D(0))
    assert not (tmp_path / "ledger.jsonl").exists()  # reading never creates the ledger


def test_fsync_reaches_file_and_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[int] = []
    real = os.fsync
    monkeypatch.setattr(ledger_module.os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    make(tmp_path).reserve("a1", D("0.1"))
    assert len(synced) >= 3  # temp ledger, directory entry, derived state (+ its directory)


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=400),  # reserve in cents
            st.one_of(st.none(), st.integers(min_value=0, max_value=400)),  # settle cents/None
            st.booleans(),  # settle before the next reserve?
        ),
        max_size=14,
    )
)
def test_committed_money_never_exceeds_cap_unless_a_cost_overran(
    plan: list[tuple[int, int | None, bool]],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = Ledger(Path(directory) / "l.jsonl", D("5.00"))
        open_ids: list[tuple[str, int | None]] = []
        overran = False
        for number, (cents, actual, settle_now) in enumerate(plan):
            attempt = f"a{number}"
            try:
                ledger.reserve(attempt, D(cents) / 100)
            except CapExceeded:
                state = ledger.state()
                assert state.reserved + state.spent + D(cents) / 100 > D("5.00")
                continue
            open_ids.append((attempt, actual))
            if settle_now:
                name, value = open_ids.pop(0)
                result = ledger.settle(name, None if value is None else D(value) / 100, "r")
                overran = overran or result.overrun
            state = ledger.state()
            assert overran or state.reserved + state.spent <= D("5.00")


# --- 2.7a: `adjust`, a reconciled charge from the provider's generation record -------------


def held(tmp_path: Path, reserve: str = "0.28", cap: str = "1.00") -> Ledger:
    """A ledger with attempt a1 settled at an unknown cost (the reservation held)."""
    ledger = make(tmp_path, cap)
    ledger.reserve("a1", D(reserve))
    assert ledger.settle("a1", None, "usage and cost absent; reservation held").unreconciled
    return ledger


def adjust(ledger: Ledger, usd: str, attempt: str = "a1") -> ledger_module.Adjustment:
    return ledger.adjust(attempt, D(usd), generation_id="gen-1", checked_at="2026-10-22T09:00:00Z")


def test_adjust_lowers_an_unreconciled_charge_and_is_recorded_in_full(tmp_path: Path) -> None:
    ledger = held(tmp_path)
    assert ledger.state().spent == D("0.28")
    done = adjust(ledger, "0.0412")
    assert (done.previous_charged_usd, done.reconciled_usd) == (D("0.28"), D("0.0412"))
    state = ledger.state()
    assert state.spent == D("0.0412") and state.remaining == D("0.9588") and state.overrun == 0
    record = state.attempts[0]
    assert record.charged_usd == record.actual_usd == D("0.0412")
    assert record.basis == "generation-endpoint" and record.adjustment == done
    line = lines(tmp_path / "ledger.jsonl")[-1]
    assert line == {
        "seq": 4,
        "event": "adjust",
        "attempt_id": "a1",
        "previous_charged_usd": "0.28",
        "reconciled_usd": "0.0412",
        "source": "generation-endpoint",
        "generation_id": "gen-1",
        "checked_at": "2026-10-22T09:00:00Z",
        "at": "2026-10-21T10:00:00Z",
    }
    derived = json.loads((tmp_path / "ledger.jsonl.state.json").read_text(encoding="utf-8"))
    assert derived["spent"] == "0.0412"


def test_adjust_may_raise_the_charge_above_the_reservation_as_an_overrun(tmp_path: Path) -> None:
    ledger = held(tmp_path, "0.28", "0.50")
    adjust(ledger, "0.40")
    state = ledger.state()
    assert state.spent == D("0.40") and state.overrun == D("0.12")
    with pytest.raises(CapExceeded):
        ledger.reserve("a2", D("0.11"))  # later reservations see the reconciled total
    ledger.reserve("a2", D("0.10"))


def test_adjust_to_zero_releases_the_whole_hold(tmp_path: Path) -> None:
    ledger = held(tmp_path)
    adjust(ledger, "0")
    assert ledger.state().spent == D(0) and ledger.state().remaining == D("1.00")


@pytest.mark.parametrize("case", ["twice", "before-settle", "unknown", "reconciled", "negative"])
def test_invalid_adjustments_are_refused_and_nothing_is_written(tmp_path: Path, case: str) -> None:
    ledger = held(tmp_path)
    ledger.reserve("a2", D("0.1"))
    ledger.reserve("a3", D("0.1"))
    ledger.settle("a3", D("0.07"), "usage.cost")
    if case == "twice":
        adjust(ledger, "0.05")
    before = (tmp_path / "ledger.jsonl").read_bytes()
    target = {"before-settle": "a2", "unknown": "zzz", "reconciled": "a3"}.get(case, "a1")
    with pytest.raises(LedgerError):
        adjust(ledger, "-0.01" if case == "negative" else "0.05", target)
    assert (tmp_path / "ledger.jsonl").read_bytes() == before


def test_adjust_needs_a_generation_id_and_a_check_time(tmp_path: Path) -> None:
    ledger = held(tmp_path)
    for generation, checked in (("", "t"), ("gen-1", " ")):
        with pytest.raises(LedgerError):
            ledger.adjust("a1", D("0.1"), generation_id=generation, checked_at=checked)


def test_adjust_lines_that_break_the_rules_fail_replay(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    held(tmp_path)
    good = path.read_bytes()
    base = {
        "seq": 4,
        "event": "adjust",
        "attempt_id": "a1",
        "previous_charged_usd": "0.28",
        "reconciled_usd": "0.05",
        "source": "generation-endpoint",
        "generation_id": "gen-1",
        "checked_at": "t",
    }
    for change in (
        {"previous_charged_usd": "0.27"},  # does not match the settled charge
        {"source": "guess"},
        {"generation_id": None},
        {"checked_at": ""},
        {"reconciled_usd": "x"},
        {"attempt_id": "nobody"},
    ):
        path.write_bytes(good + json.dumps({**base, **change}).encode() + b"\n")
        with pytest.raises(LedgerError):
            make(tmp_path).state()
    twice = json.dumps(base).encode() + b"\n" + json.dumps({**base, "seq": 5}).encode() + b"\n"
    path.write_bytes(good + twice)
    with pytest.raises(LedgerError, match="twice"):
        make(tmp_path).state()
    path.write_bytes(good + json.dumps(base).encode() + b"\n")
    state = make(tmp_path).state()
    assert state.spent == D("0.05") and state.attempts[0].adjustment is not None


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=300),  # reservation in cents
            st.one_of(st.none(), st.integers(min_value=0, max_value=300)),  # settle or hold
            st.one_of(st.none(), st.integers(min_value=0, max_value=500)),  # later adjustment
        ),
        max_size=10,
    )
)
def test_spent_is_always_the_sum_of_final_charges(
    plan: list[tuple[int, int | None, int | None]],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = Ledger(Path(directory) / "l.jsonl", D("100"))
        expected = D(0)
        overrun = D(0)
        for number, (cents, actual, later) in enumerate(plan):
            name = f"a{number}"
            ledger.reserve(name, D(cents) / 100)
            ledger.settle(name, None if actual is None else D(actual) / 100, "r")
            final = None if actual is None else D(actual) / 100
            if later is not None and actual is None:
                ledger.adjust(name, D(later) / 100, generation_id="g", checked_at="t")
                final = D(later) / 100
            elif later is not None:
                with pytest.raises(LedgerError):
                    ledger.adjust(name, D(later) / 100, generation_id="g", checked_at="t")
            expected += D(cents) / 100 if final is None else final
            overrun += D(0) if final is None else max(D(0), final - D(cents) / 100)
        state = ledger.state()
        assert (state.spent, state.reserved, state.overrun) == (expected, D(0), overrun)


def test_a_generation_404_adjustment_is_zero_and_carries_its_evidence(tmp_path: Path) -> None:
    """Decision 0008: `generation-404+usage-delta` releases a hold to zero, with both facts."""
    ledger = Ledger(tmp_path / "l.jsonl", Decimal("1"), clock=lambda: "t")
    ledger.reserve("a", Decimal("0.28"))
    ledger.settle("a", None, "unknown")
    evidence = {"generation_status": 404, "usage_delta": "0.0069"}
    for amount, facts, message in (
        (Decimal("0.01"), evidence, "always zero"),
        (Decimal(0), None, "needs evidence"),
        (Decimal(0), {}, "needs evidence"),
    ):
        with pytest.raises(LedgerError, match=message):
            ledger.adjust(
                "a",
                amount,
                generation_id="gen-x",
                checked_at="t",
                source=ADJUST_404_SOURCE,
                evidence=facts,
            )
    with pytest.raises(LedgerError, match="carries evidence"):
        ledger.adjust("a", Decimal(0), generation_id="gen-x", checked_at="t", evidence=evidence)
    with pytest.raises(LedgerError, match="unknown source"):
        ledger.adjust("a", Decimal(0), generation_id="gen-x", checked_at="t", source="guess")
    done = ledger.adjust(
        "a",
        Decimal(0),
        generation_id="gen-x",
        checked_at="t",
        source=ADJUST_404_SOURCE,
        evidence=evidence,
    )
    assert done.source == ADJUST_404_SOURCE and done.evidence == evidence
    state = ledger.state()
    (record,) = state.attempts
    assert record.charged_usd == 0 and record.basis == ADJUST_404_SOURCE
    assert record.adjustment is not None and record.adjustment.evidence == evidence
    assert state.spent == 0
    line = json.loads(ledger.path.read_text(encoding="utf-8").splitlines()[-1])
    assert line["source"] == ADJUST_404_SOURCE and line["evidence"] == evidence
