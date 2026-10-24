"""Persisted reservation ledger: the hard spend guard for live model calls.

Append-only JSON lines. Every change rewrites the whole file through a temp file, fsync and
rename, under an exclusive lock, so a reader never sees a torn line and a crash leaves
either the old or the new ledger. State is always recomputed by replaying the lines; the
`.state.json` sibling is a derived convenience and is never read back as authority.

Money is Decimal only. A reservation counts as committed until it is settled. If the actual
cost is unknown the whole reservation is held as spent (worst case, flagged unreconciled).
A cost above its reservation is recorded as an overrun, never clipped; later reservations
then see the true total and are refused.

Events: `reserve`, `settle` (once per reservation) and `adjust`, which replaces a held charge
(a settlement with an unknown cost) with the provider's figure for that generation: at most once
per attempt, only after its settle, lower or higher than the hold. Totals, the cap and the
CLI's cumulative-ceiling check all read the adjusted figure. An `adjust` names its `source`:
`generation-endpoint` (the generation record's `total_cost`) or `generation-404+usage-delta`
(decision 0008: the generation endpoint answered 404 and the batch's account-usage delta equals
the other attempts' measured costs, so the held attempt cost nothing). The second is always
zero and carries both facts in `evidence`. Task 7.0 adds `account-usage-delta`: a held attempt
with no generation id (a deadline expiry, nothing to look up) that is the batch's only held
attempt, every other attempt's cost being measured, takes the account-usage delta less those
costs. It names no generation (`generation_id` null), carries its facts in `evidence` and is at
most the attempt's reservation (a larger residual is other spend, never attributed). Task 7.13
adds `account-usage-delta/next-batch-before`: the same residual for an interrupted attempt of a
batch that recorded no after-check, over the window that closes at the next batch's
before-check with no other batch's reservation between the two checks; the same rules apply.

The first line records the cap the file was opened with; it is written together with the first
reservation, so a file that exists is always bound. Opening the same file with another
cap raises LedgerError; a different cap needs a different ledger file.

Task 8.0d: the first line also records the provider whose calls the ledger holds, when the
opener names one (the live runner: `openrouter`; the hybrid harness: each provider's own). A
ledger written before that records none and is an OpenRouter ledger (`opening_provider`).
Opening a file with a named provider that differs from the recorded one raises LedgerError.
"""

import fcntl
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

ADJUST_SOURCE = "generation-endpoint"
ADJUST_404_SOURCE = "generation-404+usage-delta"
ADJUST_USAGE_SOURCE = "account-usage-delta"
ADJUST_NEXT_BEFORE_SOURCE = "account-usage-delta/next-batch-before"
# The usage-delta sources: no generation, evidence required, at most the reservation.
_USAGE_SOURCES = frozenset({ADJUST_USAGE_SOURCE, ADJUST_NEXT_BEFORE_SOURCE})
ADJUST_SOURCES = frozenset({ADJUST_SOURCE, ADJUST_404_SOURCE, *_USAGE_SOURCES})
# Sources whose line must carry `evidence` (the facts behind the figure).
_EVIDENCED = frozenset({ADJUST_404_SOURCE, *_USAGE_SOURCES})
# Task 8.0d: the provider a ledger without a recorded one belongs to (every ledger before 8.0d
# that the runner wrote; the hybrid harness's Anthropic ledgers of 23-24 Oct 2026 record none
# either, so this rule counts them as OpenRouter's until the user decides otherwise).
OPENROUTER = "openrouter"


def opening_provider(entry: dict[str, Any]) -> str:
    """The provider an opening line records, `openrouter` when it records none (task 8.0d)."""
    provider = entry.get("provider")
    if provider is None:
        return OPENROUTER
    if not isinstance(provider, str) or not provider.strip():
        raise LedgerError("the opening line's provider is not a name")
    return provider


class LedgerError(Exception):
    """The ledger is corrupt or the operation is invalid. Never retried silently."""


class CapExceeded(Exception):
    def __init__(self, requested: Decimal, committed: Decimal, cap: Decimal) -> None:
        super().__init__(
            f"reserving {format(requested, 'f')} would exceed the cap "
            f"({format(committed, 'f')} committed of {format(cap, 'f')})"
        )
        self.requested = requested
        self.committed = committed
        self.cap = cap


@dataclass(frozen=True)
class Reservation:
    attempt_id: str
    usd: Decimal
    seq: int


@dataclass(frozen=True)
class Settlement:
    attempt_id: str
    charged: Decimal
    overrun: bool
    unreconciled: bool


@dataclass(frozen=True)
class Adjustment:
    """A held charge replaced by the provider's own figure for that generation."""

    previous_charged_usd: Decimal
    reconciled_usd: Decimal
    generation_id: str | None  # None only for a usage-delta adjustment (either source)
    checked_at: str
    seq: int
    source: str = ADJUST_SOURCE
    evidence: dict[str, Any] | None = None  # the facts behind a 404 or usage-delta figure


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    status: Literal["reserved", "settled"]
    reserved_usd: Decimal
    actual_usd: Decimal | None
    charged_usd: Decimal | None
    basis: str | None
    adjustment: Adjustment | None = None


@dataclass(frozen=True)
class LedgerState:
    cap: Decimal
    reserved: Decimal
    spent: Decimal
    overrun: Decimal
    attempts: tuple[AttemptRecord, ...]
    lines: int

    @property
    def remaining(self) -> Decimal:
        return self.cap - self.reserved - self.spent


# The one UTC second stamp of ledger lines, usage checks, manifests and the catalog lookup
# (task 7.15 item 6: the one `utc_stamp` of the live package; `reconcile._instant` parses it).
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def utc_stamp() -> str:
    return datetime.now(UTC).strftime(STAMP)


def _money(value: object, what: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise LedgerError(f"{what} is not a decimal amount") from None
    if not parsed.is_finite() or parsed < 0:
        raise LedgerError(f"{what} must be a finite non-negative amount")
    return parsed


def _text(value: Decimal) -> str:
    return format(value, "f")


class Ledger:
    def __init__(
        self,
        path: Path,
        cap_usd: Decimal,
        *,
        clock: Callable[[], str] = utc_stamp,
        provider: str | None = None,
    ) -> None:
        if not cap_usd.is_finite() or cap_usd <= 0:
            raise LedgerError("the cap must be a positive amount")
        if provider is not None and not provider.strip():
            raise LedgerError("a named provider cannot be blank")
        self.path = path
        self.cap = cap_usd
        self.provider = provider  # None: not asserted on open, not recorded on a new file
        self._clock = clock

    # -- reading -----------------------------------------------------------------------------

    def state(self) -> LedgerState:
        return self._replay(self._read())

    def _read(self) -> bytes:
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return b""

    def _replay(self, raw: bytes) -> LedgerState:
        records: dict[str, AttemptRecord] = {}
        count = 0
        for number, line in enumerate(raw.splitlines(), start=1):
            try:
                entry = json.loads(line)
            except ValueError:
                raise LedgerError(f"ledger line {number} is not valid JSON") from None
            if not isinstance(entry, dict) or entry.get("seq") != number:
                raise LedgerError(f"ledger line {number} breaks the sequence")
            if number == 1:
                self._check_opening(entry)
            else:
                self._apply(entry, number, records)
            count = number
        if raw and not raw.endswith(b"\n"):
            raise LedgerError("ledger ends in a torn line")
        attempts = tuple(records.values())
        spent = sum((r.charged_usd or Decimal(0) for r in attempts), Decimal(0))
        held = sum((r.reserved_usd for r in attempts if r.status == "reserved"), Decimal(0))
        overrun = sum(
            (
                max(Decimal(0), r.actual_usd - r.reserved_usd)
                for r in attempts
                if r.actual_usd is not None
            ),
            Decimal(0),
        )
        return LedgerState(self.cap, held, spent, overrun, attempts, count)

    def _check_opening(self, entry: dict[str, Any]) -> None:
        """The first line binds the file to its cap; a different cap needs a different file."""
        if entry.get("event") != "open":
            raise LedgerError("ledger has no opening line")
        opened = _money(entry.get("cap_usd"), "opening cap")
        if opened != self.cap:
            raise LedgerError(
                f"ledger was opened with a cap of {_text(opened)}, not {_text(self.cap)}; "
                "use a new ledger file for a new cap"
            )
        recorded = opening_provider(entry)
        if self.provider is not None and recorded != self.provider:
            raise LedgerError(
                f"ledger holds {recorded} calls, not {self.provider}; use a new ledger file"
            )

    @staticmethod
    def _apply(entry: dict[str, Any], number: int, records: dict[str, AttemptRecord]) -> None:
        event, name = entry.get("event"), entry.get("attempt_id")
        if not isinstance(name, str):
            raise LedgerError(f"ledger line {number} has no attempt id")
        if event == "reserve":
            if name in records:
                raise LedgerError(f"ledger line {number} reserves {name} twice")
            usd = _money(entry.get("usd"), f"line {number} reservation")
            records[name] = AttemptRecord(name, "reserved", usd, None, None, None)
        elif event == "settle":
            held = records.get(name)
            if held is None or held.status != "reserved":
                raise LedgerError(
                    f"ledger line {number} settles {name} without an open reservation"
                )
            actual = entry.get("actual_usd")
            records[name] = replace(
                held,
                status="settled",
                actual_usd=None if actual is None else _money(actual, f"line {number} actual"),
                charged_usd=_money(entry.get("charged_usd"), f"line {number} charge"),
                basis=str(entry.get("reason", "")),
            )
        elif event == "adjust":
            records[name] = Ledger._adjusted(entry, number, records.get(name))
        else:
            raise LedgerError(f"ledger line {number} has unknown event {event!r}")

    @staticmethod
    def _adjusted(entry: dict[str, Any], number: int, held: AttemptRecord | None) -> AttemptRecord:
        """Replay rules for `adjust`: once, after the settle, only on a held (unknown) charge."""
        name = entry.get("attempt_id")
        if held is None or held.status != "settled":
            raise LedgerError(f"ledger line {number} adjusts {name} before its settle")
        if held.adjustment is not None:
            raise LedgerError(f"ledger line {number} adjusts {name} twice")
        if held.actual_usd is not None:
            raise LedgerError(f"ledger line {number} adjusts {name}, whose cost was known")
        previous = _money(entry.get("previous_charged_usd"), f"line {number} previous charge")
        if previous != held.charged_usd:
            raise LedgerError(f"ledger line {number} does not start from the settled charge")
        source = entry.get("source")
        if source not in ADJUST_SOURCES:
            raise LedgerError(f"ledger line {number} adjusts from an unknown source")
        generation, checked = entry.get("generation_id"), entry.get("checked_at")
        if not isinstance(checked, str) or not checked.strip():
            raise LedgerError(f"ledger line {number} adjusts without a check time")
        reconciled = _money(entry.get("reconciled_usd"), f"line {number} reconciled cost")
        evidence = entry.get("evidence")
        Ledger._source_rules(number, str(source), generation, evidence, reconciled, held)
        return replace(
            held,
            actual_usd=reconciled,
            charged_usd=reconciled,
            basis=str(source),
            adjustment=Adjustment(
                previous, reconciled, generation, checked, number, str(source), evidence
            ),
        )

    @staticmethod
    def _source_rules(
        number: int,
        source: str,
        generation: object,
        evidence: object,
        reconciled: Decimal,
        held: AttemptRecord,
    ) -> None:
        """What each `adjust` source requires: a generation id except for the usage delta
        (which names none), evidence exactly for the 404 and usage-delta sources, zero for a
        404, at most the reservation for the usage delta."""
        if source in _USAGE_SOURCES:
            if generation is not None:
                raise LedgerError(
                    f"ledger line {number}: a {source} adjustment names no generation"
                )
        elif not isinstance(generation, str) or not generation.strip():
            raise LedgerError(f"ledger line {number} adjusts without a generation id")
        if source in _EVIDENCED:
            if not isinstance(evidence, dict) or not evidence:
                raise LedgerError(f"ledger line {number}: a {source} adjustment needs evidence")
        elif evidence is not None:
            raise LedgerError(
                f"ledger line {number}: only {ADJUST_404_SOURCE} or a usage-delta source "
                "carries evidence"
            )
        if source == ADJUST_404_SOURCE and reconciled != 0:
            raise LedgerError(f"ledger line {number}: a {source} adjustment is always zero")
        if source in _USAGE_SOURCES and reconciled > held.reserved_usd:
            raise LedgerError(
                f"ledger line {number}: a {source} adjustment above its reservation is not "
                "attributable to the attempt"
            )

    # -- writing -----------------------------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_name(self.path.name + ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _line(self, raw: bytes, entry: dict[str, Any]) -> bytes:
        stamped = {"seq": raw.count(b"\n") + 1, **entry, "at": self._clock()}
        return raw + json.dumps(stamped, sort_keys=False).encode() + b"\n"

    def _commit(self, raw: bytes, entry: dict[str, Any]) -> int:
        """Append one entry (after the opening line, written with the first one); return its seq."""
        if not raw:
            opening: dict[str, Any] = {"event": "open", "cap_usd": _text(self.cap)}
            if self.provider is not None:
                opening["provider"] = self.provider
            raw = self._line(raw, opening)
        content = self._line(raw, entry)
        state = self._replay(content)  # never persist a ledger that would not replay
        self._replace(self.path, content)
        # The derived file follows the authoritative one. If it fails, the change above is already
        # committed and the error propagates: a reservation then counts (safe side), never vanishes.
        derived = {
            "note": "derived from the .jsonl lines; the ledger file is the authority",
            "derived_from_lines": state.lines,
            "cap": _text(state.cap),
            "reserved": _text(state.reserved),
            "spent": _text(state.spent),
            "overrun": _text(state.overrun),
            "remaining": _text(state.remaining),
        }
        self._replace(
            self.path.with_name(self.path.name + ".state.json"),
            (json.dumps(derived, indent=1) + "\n").encode(),
        )
        return state.lines

    @staticmethod
    def _replace(destination: Path, content: bytes) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".ledger-", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            directory = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def reserve(self, attempt_id: str, usd: Decimal) -> Reservation:
        """Commit `usd` before dispatch; refuse if reserved + spent + `usd` would exceed the cap."""
        amount = _money(usd, "reservation")
        with self._locked():
            raw = self._read()
            state = self._replay(raw)
            if state.reserved + state.spent + amount > self.cap:
                raise CapExceeded(amount, state.reserved + state.spent, self.cap)
            seq = self._commit(
                raw, {"event": "reserve", "attempt_id": attempt_id, "usd": _text(amount)}
            )
            return Reservation(attempt_id, amount, seq)

    def settle(self, attempt_id: str, actual_usd: Decimal | None, reason: str) -> Settlement:
        """Release the reservation and charge the actual cost (or hold it all if unknown)."""
        if not reason.strip():
            raise LedgerError("a settlement needs a reason")
        actual = None if actual_usd is None else _money(actual_usd, "actual cost")
        with self._locked():
            raw = self._read()
            held = {r.attempt_id: r for r in self._replay(raw).attempts}.get(attempt_id)
            if held is None or held.status != "reserved":
                raise LedgerError(f"{attempt_id} has no open reservation")
            charged = held.reserved_usd if actual is None else actual
            self._commit(
                raw,
                {
                    "event": "settle",
                    "attempt_id": attempt_id,
                    "actual_usd": None if actual is None else _text(actual),
                    "charged_usd": _text(charged),
                    "reason": reason,
                },
            )
            return Settlement(
                attempt_id,
                charged,
                overrun=actual is not None and actual > held.reserved_usd,
                unreconciled=actual is None,
            )

    def adjust(
        self,
        attempt_id: str,
        reconciled_usd: Decimal,
        *,
        generation_id: str | None,
        checked_at: str,
        source: str = ADJUST_SOURCE,
        evidence: dict[str, Any] | None = None,
    ) -> Adjustment:
        """Replace a held charge with the provider's figure for its generation (once).

        Only a settlement whose cost was unknown can be adjusted, and only once. The figure may
        be lower or higher than the hold; a figure above the reservation is an overrun. The cap
        is not checked here: this records money already spent, it does not commit new money.
        `source` and `evidence` follow the replay rules in `_adjusted`."""
        amount = _money(reconciled_usd, "reconciled cost")
        with self._locked():
            raw = self._read()
            held = {r.attempt_id: r for r in self._replay(raw).attempts}.get(attempt_id)
            if held is None or held.charged_usd is None:
                raise LedgerError(f"{attempt_id} has no settlement to adjust")
            entry: dict[str, Any] = {
                "event": "adjust",
                "attempt_id": attempt_id,
                "previous_charged_usd": _text(held.charged_usd),
                "reconciled_usd": _text(amount),
                "source": source,
                "generation_id": generation_id,
                "checked_at": checked_at,
            }
            if evidence is not None:
                entry["evidence"] = evidence
            # Replaying the new line enforces the remaining rules (see `_adjusted`).
            seq = self._commit(raw, entry)
            return Adjustment(
                held.charged_usd, amount, generation_id, checked_at, seq, source, evidence
            )
