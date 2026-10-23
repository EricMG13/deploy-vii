"""Reconcile held charges against OpenRouter's generation records (`live reconcile`).

An attempt whose cost was unknown at settlement (no usage: a timeout, a 5xx, a mid-call error)
holds its whole reservation as spent and is flagged `unreconciled`. For each such pool attempt
of a batch, this looks up `GET /api/v1/generation?id=<gen>` with the key read for that call
(DC-7), writes one ledger `adjust` with the record's `total_cost`, and updates the attempt's
`metrics.json` ledger block. A 404, a non-JSON reply, a record for another generation, a record
without a non-negative numeric `total_cost`, or one whose `usage` differs from it leaves the
attempt unreconciled, with the reason in `metrics.json` and the report; no figure is ever
inferred. A connection failure stops the run (TransportError propagates).

One corroborated exception (decision 0008): when the generation endpoint answers 404 for a held
attempt and the batch's recorded account usage (`GET /api/v1/key` before and after the batch,
`account-usage-{before,after}.json` under the batch directory, same key-file note) moved by exactly
the sum of the other pool attempts' measured costs (provider-reported, known-zero or reconciled
from the endpoint) within US$0.000001, the held attempts together cost nothing measurable, so
the attempt is adjusted to 0 with source `generation-404+usage-delta` and both facts in the
ledger line. Anything short of that (no record, a usage figure missing, different key-file notes,
a difference above the tolerance) leaves the attempt unresolved with the reason. The delta also
moves with any other spend on the account in the batch window; that can only make the
difference larger, never fake a match.

Task 7.0: a held attempt with no generation id at all (a deadline expiry: nothing to look up)
is adjusted from the same usage window when it is the batch ledger's only held attempt and every
other attempt's charge is measured (provider-reported, known-zero or generation-endpoint): it
takes the delta less those charges, source `account-usage-delta`, both facts in the ledger line.
A residual below zero by more than US$0.000001, or above the attempt's reservation (other spend
on the account, which the delta cannot tell apart), leaves it held with the reason; so do two or
more held attempts, any charge that is not measured and a missing usage record. Attempts with a
generation id are looked up first (`lookup_order`), so the outcome does not depend on the order
the attempt directories sort in.

Both usage-window rules (`generation-404+usage-delta` and `account-usage-delta`) assume the
after-batch check already includes every charge of the batch, but the provider may bill a
404'd or given-up call later. So either adjust also needs a fresh `GET /api/v1/key` reading at
reconcile time equal to the recorded after-figure within the tolerance (`usage_unmoved`), else
the attempt stays held ("usage moved since the after-check") and a later reconcile may retry.

`metrics.json` is the one retained file this rewrites (atomically, temp file then rename). The
values it replaces are kept under `ledger.reconciliation.previous`, and the ledger line is the
authority. Request, response, output, events and manifest are never touched.

Task 7.11: an interrupted attempt (an open reservation whose directory holds `request.json` only:
the process ended before the reply) gets the one manifest that shape supports, written once as
a new file (`interrupted_manifest`), and is then settled by the `account-usage-delta` rule above
(settle held, then adjust) only where it holds; otherwise its reservation stays open and the
outcome is unresolved. It is processed after every lookup, as a hold without an id is.

Task 7.13: a batch killed before its after-check (e1-cp1-12) has no window of its own. Its
window may then close at the earliest later batch's before-check under the same artifact root
(`next_batch_window`), only when both checks record the same key-file note, the batch's own ledger
ends before that check, and no other batch held a reservation open at the before-check (reserved
before it, settled after it or never) nor reserved or settled inside the window (every
`.ledgers/*.jsonl` read). The same attribution settles the interrupted attempt, source
`account-usage-delta/next-batch-before`, with both files, both times and the no-reservation fact
in the evidence and the report. A reservation another batch's ledger never settled therefore
leaves every later killed batch's window unresolved until it is settled (fail closed). No
reconcile-time reading can corroborate that window (later batches moved the usage), so a charge
billed after the closing check is not seen. A manifest this path wrote earlier is reused only
while the directory holds exactly it and `request.json`.

Task 7.14: neither window sees a charge billed after it closes (batch e1-cp1-13's after-check
lagged its settled charges by US$1.0737551). The reconciled report therefore ends with a spend
cross-check (`spend_cross_check`): the key's usage now less the earliest recorded before-check
usage, against the settled charges of every ledger opened since that check (earlier ledgers are
named, not counted), the difference named unattributed USD. It is reported only; nothing is
settled or adjusted from it, and a failed key read for it leaves the exit code unchanged.
"""

import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from deploy_vii.live.client import CHAT_URL, GENERATION_ID, ChatClient, Response
from deploy_vii.live.credit import from_key_response
from deploy_vii.live.ledger import (
    ADJUST_404_SOURCE,
    ADJUST_NEXT_BEFORE_SOURCE,
    ADJUST_SOURCE,
    ADJUST_USAGE_SOURCE,
    AttemptRecord,
    Ledger,
    LedgerError,
    LedgerState,
)
from deploy_vii.live.retention import dump, write_once
from deploy_vii.live.runner import SCHEMA_BISECT_CASE, SCHEMA_CHECK_CASE
from deploy_vii.live.submission import STEPS

POOL_COHORT = "openrouter-pool"
USAGE_TOLERANCE_USD = Decimal("0.000001")
# Cost bases that are a measured figure (metrics.json `ledger.cost_basis`); an estimate is not.
MEASURED_BASES = frozenset({"provider-reported", "known-zero", ADJUST_SOURCE})
USAGE_FILE = "account-usage-{phase}.json"


@dataclass(frozen=True)
class Outcome:
    attempt_id: str
    generation_id: str | None
    id_source: str
    status: Literal["reconciled", "unresolved", "synchronised"]
    previous_usd: Decimal | None
    reconciled_usd: Decimal | None
    reason: str


@dataclass(frozen=True)
class RetainedAttempt:
    directory: Path
    manifest: dict[str, Any]
    metrics: dict[str, Any]

    @property
    def attempt_id(self) -> str:
        return str(self.manifest["attempt_id"])

    @property
    def unreconciled(self) -> bool:
        ledger = self.metrics.get("ledger")
        return isinstance(ledger, dict) and ledger.get("unreconciled") is True


def _read(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} is not a JSON object")
    return document


def batch_attempts(artifact_root: Path, batch_id: str) -> Iterator[RetainedAttempt]:
    """Every sealed attempt of the batch (`<root>/<batch>/<case>/<model>/<attempt>/`)."""
    for manifest_path in sorted((artifact_root / batch_id).glob("*/*/*/manifest.json")):
        directory = manifest_path.parent
        metrics_path = directory / "metrics.json"
        metrics = _read(metrics_path) if metrics_path.is_file() else {}
        yield RetainedAttempt(directory, _read(manifest_path), metrics)


def generation_id(attempt: RetainedAttempt) -> tuple[str | None, str]:
    """The generation id and where it came from: the manifest, else the retained body.

    Probe-2 attempts predate task 2.7a, whose client records the body `id` in the manifest;
    for them the id is read from `response.json` by the same rule (whitespace stripped)."""
    served = attempt.manifest.get("served")
    recorded = served.get("provider_request_id") if isinstance(served, dict) else None
    if isinstance(recorded, str) and recorded:
        return recorded, "manifest"
    response = attempt.directory / "response.json"
    body = _read(response).get("body_text") if response.is_file() else None
    try:
        document = json.loads(body.strip()) if isinstance(body, str) else None
    except ValueError:
        document = None
    found = document.get("id") if isinstance(document, dict) else None
    return (found, "response.json") if isinstance(found, str) and found else (None, "none")


def _usd(value: object) -> Decimal | None:
    """A non-negative JSON number (parsed exactly), else None; booleans are not numbers."""
    if isinstance(value, bool) or not isinstance(value, int | Decimal) or value < 0:
        return None
    return Decimal(value)


def generation_cost(response: Response, generation_id: str) -> tuple[Decimal | None, str]:
    """The record's `total_cost` (USD), or None with the reason. Never a guessed figure.

    Shape (OpenRouter API reference, GET /api/v1/generation): `{"data": {"id": "gen-...",
    "total_cost": <USD>, "usage": <USD>, ...}}`; a top-level record is read the same way. The
    record must name the requested generation. `usage` is also documented in USD and equals
    `total_cost` in the documented example; when it is present and differs, nothing is chosen
    between them and the attempt stays unreconciled. There is no `cost` field to fall back to."""
    if response.status != 200:
        return None, f"HTTP {response.status} from the generation endpoint"
    try:
        document = json.loads(response.body.decode("utf-8").strip(), parse_float=Decimal)
    except (UnicodeDecodeError, ValueError):
        document = None
    if not isinstance(document, dict):
        return None, "generation endpoint reply is not a JSON object"
    record = document["data"] if isinstance(document.get("data"), dict) else document
    if record.get("id") != generation_id:
        return None, (
            f"generation id mismatch: requested {generation_id}, record {record.get('id')}"
        )
    total = _usd(record.get("total_cost"))
    if total is None:
        return (
            None,
            "generation record has no total_cost (absent, null or not a non-negative number)",
        )
    if "usage" in record and _usd(record["usage"]) != total:
        return None, f"usage {record['usage']} differs from total_cost {total}; not reconciled"
    return total, f"generation endpoint total_cost for {generation_id}"


@dataclass(frozen=True)
class UsageWindow:
    """Account usage (USD) read from `GET /api/v1/key` before and after the batch."""

    before: Decimal
    after: Decimal
    before_at: object
    after_at: object
    recorded_by: tuple[object, object]
    key_file: object = None  # the key-file token counts both checks recorded (equal)

    @property
    def delta(self) -> Decimal:
        return self.after - self.before


def usage_path(artifact_root: Path, batch_id: str, phase: str) -> Path:
    return artifact_root / batch_id / USAGE_FILE.format(phase=phase)


@dataclass(frozen=True)
class _Check:
    """One recorded `GET /api/v1/key` reading (`account-usage-<phase>.json`)."""

    usage: Decimal
    checked_at: object
    key_file: object
    recorded_by: object


def _usage_check(path: Path, phase: str) -> tuple[_Check | None, str]:
    """The reading `path` records, or None with the reason it cannot be used."""
    if not path.is_file():
        return None, f"no account usage was recorded {phase} the batch"
    document = _read(path)
    credit = document.get("credit")
    usage = credit.get("usage") if isinstance(credit, dict) else None
    try:
        value = Decimal(usage) if isinstance(usage, str) else None
    except ArithmeticError:
        value = None
    if value is None or not value.is_finite():
        return None, f"account usage {phase} the batch is not a recorded number"
    assert isinstance(credit, dict)
    check = _Check(
        value, credit.get("checked_at"), credit.get("key_file"), document.get("recorded_by")
    )
    return check, ""


def read_usage(artifact_root: Path, batch_id: str) -> tuple[UsageWindow | None, str]:
    """The batch's recorded usage window, or None with the reason it cannot be used."""
    found: dict[str, _Check] = {}
    for phase in ("before", "after"):
        check, why = _usage_check(usage_path(artifact_root, batch_id, phase), phase)
        if check is None:
            return None, why
        found[phase] = check
    before, after = found["before"], found["after"]
    if before.key_file != after.key_file:
        return None, "the two account usage checks record different key-file notes"
    window = UsageWindow(
        before.usage,
        after.usage,
        before.checked_at,
        after.checked_at,
        (before.recorded_by, after.recorded_by),
        after.key_file,
    )
    return window, ""


# Task 7.13: the window of a batch with no after-check may close at the next batch's
# before-check. Times are `catalog.utc_stamp`'s, the clock of the ledger and the usage checks.
STAMP = "%Y-%m-%dT%H:%M:%SZ"
NEXT_BATCH_BEFORE = "next-batch-before"


def _instant(value: object) -> datetime | None:
    """A recorded `utc_stamp` time, or None for anything else."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, STAMP).replace(tzinfo=UTC)
    except ValueError:
        return None


@dataclass(frozen=True)
class NextBatchWindow:
    """A batch's usage window closed at the next batch's before-check, the facts that close
    it (ledger evidence) and the sentence the reconciled report gives them."""

    window: UsageWindow
    evidence: dict[str, Any]
    reason: str


def _next_before(
    artifact_root: Path, batch_id: str, start: datetime
) -> tuple[tuple[datetime, str, Path] | None, str]:
    """The earliest before-check of another batch under the root after `start`, or None with
    why it is not known (none; a check without a readable time; two in the same second)."""
    later: list[tuple[datetime, str, Path]] = []
    for path in sorted(artifact_root.glob(f"*/{USAGE_FILE.format(phase='before')}")):
        if path.parent.name == batch_id:
            continue
        where = path.relative_to(artifact_root).as_posix()
        try:
            credit = _read(path).get("credit")
        except ValueError:
            return None, f"{where} is not a readable account usage check; the next batch is unknown"
        at = _instant(credit.get("checked_at") if isinstance(credit, dict) else None)
        if at is None:
            return None, f"{where} records no check time; the next batch is unknown"
        if at > start:
            later.append((at, path.parent.name, path))
    if not later:
        return None, "no later batch recorded an account usage check before it"
    later.sort()
    if len(later) > 1 and later[1][0] == later[0][0]:
        return None, (
            f"batches {later[0][1]} and {later[1][1]} checked account usage in the same second; "
            "the next batch is unknown"
        )
    return later[0], ""


def _ledgers_between(
    ledgers: Path, batch_id: str, next_id: str, start: datetime, end: datetime
) -> tuple[list[str] | None, str]:
    """The ledger files read, when no other batch's spend can fall between `start` and `end`
    (inclusive), else None with why. Another batch may not reserve or settle in the window,
    nor hold a reservation opened before `start` and not settled by then (the next batch's own
    lines at `end` follow its check, which it records before its first reservation). Every
    line the runner wrote for `batch_id` (a reserve, a settle other than this module's
    `INTERRUPTED_SETTLE`) must precede `end`; `live reconcile`'s own settle and `adjust` lines
    may follow it (a reconcile stopped between its settle and its adjust)."""
    read: list[str] = []
    for path in sorted(ledgers.glob("*.jsonl")):
        read.append(path.name)
        opened: dict[object, str] = {}  # reserved before `start` and not yet settled
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                entry = json.loads(line)
            except ValueError:
                entry = None
            stamp = entry.get("at") if isinstance(entry, dict) else None
            at = _instant(stamp)
            if not isinstance(entry, dict) or at is None or stamp is None:
                return None, f"{path.name} line {number} records no readable time"
            event, attempt = entry.get("event"), entry.get("attempt_id")
            if path.stem == batch_id:
                runner = event == "reserve" or (
                    event == "settle" and entry.get("reason") != INTERRUPTED_SETTLE
                )
                if runner and at > end:
                    return None, (
                        f"{path.name} line {number} at {stamp} follows the next batch's "
                        "before-check; the window does not cover the batch"
                    )
                continue
            if event not in {"reserve", "settle"}:
                continue
            if at < start:
                if event == "reserve":
                    opened[attempt] = stamp
                else:
                    opened.pop(attempt, None)
                continue
            if at > end or (path.stem == next_id and at == end):
                continue
            done = "reserved" if event == "reserve" else "settled"
            where = "between the two checks" if event == "reserve" else "inside the window"
            return None, (
                f"{path.name} {done} {attempt} at {stamp}, {where}; the account usage delta is "
                "not this batch's alone"
            )
        if opened:
            attempt, stamp = next(iter(opened.items()))
            return None, (
                f"{path.name} reservation {attempt} (reserved at {stamp}) was still open at the "
                "before-check; it may be billed inside the window"
            )
    return read, ""


def next_batch_window(artifact_root: Path, batch_id: str) -> tuple[NextBatchWindow | None, str]:
    """Task 7.13: the usage window of a batch that recorded no after-check (a killed run),
    closed at the before-check of the earliest later batch under the same artifact root, only
    when both checks record the same key-file note (`credit.key_file`), no other batch
    reserved or settled between the two checks or held a reservation open at the first (every
    `.ledgers/*.jsonl` is read, `_ledgers_between`) and the runner's own lines for the batch
    precede the closing check. None with why otherwise. No reconcile-time reading is added, as
    the in-batch rule does (`usage_unmoved`): later batches have moved the usage since, so the
    record says so (`reconcile_time_reading: false` and the reason's last clause)."""
    own_path = usage_path(artifact_root, batch_id, "before")
    own, why = _usage_check(own_path, "before")
    if own is None:
        return None, why
    start = _instant(own.checked_at)
    if start is None:
        return None, "the before-check records no check time"
    found, why = _next_before(artifact_root, batch_id, start)
    if found is None:
        return None, why
    end_at, next_id, next_path = found
    closing = next_path.relative_to(artifact_root).as_posix()
    end, why = _usage_check(next_path, "before")
    if end is None:
        return None, f"{closing}: {why}"
    if end.key_file != own.key_file:
        return None, f"{closing} records another key-file note than the before-check"
    read, why = _ledgers_between(artifact_root / ".ledgers", batch_id, next_id, start, end_at)
    if read is None:
        return None, why
    opening = own_path.relative_to(artifact_root).as_posix()
    window = UsageWindow(
        own.usage,
        end.usage,
        own.checked_at,
        end.checked_at,
        (own.recorded_by, end.recorded_by),
        own.key_file,
    )
    evidence = {
        "usage_window_closed_by": NEXT_BATCH_BEFORE,
        "usage_before_file": opening,
        "usage_after_file": closing,
        "next_batch_id": next_id,
        "reservations_between_checks": 0,
        "ledgers_read": read,
        # The window's limit, on the record: nothing corroborates it after the closing check.
        "reconcile_time_reading": False,
    }
    reason = (
        f"window from {opening} at {own.checked_at} to the next batch's before-check {closing} "
        f"at {end.checked_at}; no other batch held a reservation open at the before-check, nor "
        f"reserved or settled inside the window ({len(read)} ledgers read); no reconcile-time "
        f"reading: a charge booked after {end.checked_at} is not seen"
    )
    return NextBatchWindow(window, evidence, reason), ""


def corroborate_404(
    attempt: RetainedAttempt,
    records: Sequence[AttemptRecord],
    batch: Sequence[RetainedAttempt],
    usage: tuple[UsageWindow | None, str],
) -> tuple[dict[str, Any] | None, str]:
    """Evidence that a 404'd held attempt cost nothing, or None with the reason it does not."""
    window, why = usage
    if window is None:
        return None, why
    retained = {item.attempt_id: item for item in batch}

    def measured(record: AttemptRecord) -> bool:
        other = retained.get(record.attempt_id)
        if other is None or other.manifest.get("cohort") != POOL_COHORT:
            return False
        block = other.metrics.get("ledger")
        basis = block.get("cost_basis") if isinstance(block, dict) else None
        return record.actual_usd is not None and basis in MEASURED_BASES

    others = [r for r in records if r.attempt_id != attempt.attempt_id and measured(r)]
    total = sum((r.charged_usd or Decimal(0) for r in others), Decimal(0))
    difference = window.delta - total
    if abs(difference) > USAGE_TOLERANCE_USD:
        return None, (
            f"account usage moved {format(window.delta, 'f')} but the other attempts' measured "
            f"costs sum to {format(total, 'f')} (difference {format(difference, 'f')}); "
            "not corroborated"
        )
    evidence = {
        "generation_status": 404,
        "usage_before_usd": format(window.before, "f"),
        "usage_before_checked_at": window.before_at,
        "usage_after_usd": format(window.after, "f"),
        "usage_after_checked_at": window.after_at,
        "usage_delta_usd": format(window.delta, "f"),
        "other_attempts_measured_usd": format(total, "f"),
        "other_attempts": sorted(r.attempt_id for r in others),
        "difference_usd": format(difference, "f"),
        "tolerance_usd": format(USAGE_TOLERANCE_USD, "f"),
        "usage_recorded_by": list(window.recorded_by),
    }
    return evidence, (
        f"generation 404; account usage moved {format(window.delta, 'f')}, the other attempts' "
        f"measured costs {format(total, 'f')} (within {format(USAGE_TOLERANCE_USD, 'f')}): "
        "the held attempt cost 0"
    )


@dataclass(frozen=True)
class Attribution:
    """The account-usage residual of the batch's only held attempt, or why there is none."""

    amount: Decimal | None
    evidence: dict[str, Any] | None
    reason: str


def _measured_now(record: AttemptRecord, retained: dict[str, RetainedAttempt]) -> bool:
    """Whether a ledger charge is a measured pool cost, read from the ledger where it was
    adjusted (metrics read at the start of a run may predate that adjust)."""
    other = retained.get(record.attempt_id)
    if other is None or other.manifest.get("cohort") != POOL_COHORT or record.actual_usd is None:
        return False
    if record.adjustment is not None:
        return record.adjustment.source == ADJUST_SOURCE
    block = other.metrics.get("ledger")
    return isinstance(block, dict) and block.get("cost_basis") in MEASURED_BASES


def attribute_usage(
    attempt: RetainedAttempt,
    records: Sequence[AttemptRecord],
    batch: Sequence[RetainedAttempt],
    usage: tuple[UsageWindow | None, str],
) -> Attribution:
    """The usage delta less every other charge, for a held attempt with no generation id that
    is the ledger's only held attempt; anything short of that names why (fail closed)."""
    window, why = usage
    if window is None:
        return Attribution(None, None, why)
    held = [r for r in records if r.actual_usd is None]
    if [r.attempt_id for r in held] != [attempt.attempt_id]:
        return Attribution(
            None,
            None,
            f"{len(held)} held attempts in the batch; the account usage delta is not "
            "attributable to one",
        )
    (own,) = held
    retained = {item.attempt_id: item for item in batch}
    others = [r for r in records if r.attempt_id != attempt.attempt_id]
    unmeasured = next((r for r in others if not _measured_now(r, retained)), None)
    if unmeasured is not None:
        return Attribution(
            None,
            None,
            f"the charge of {unmeasured.attempt_id} is not a measured cost; the account usage "
            "delta is not attributable",
        )
    total = sum((r.charged_usd or Decimal(0) for r in others), Decimal(0))
    residual = window.delta - total
    delta, measured = format(window.delta, "f"), format(total, "f")
    if residual < -USAGE_TOLERANCE_USD:
        return Attribution(
            None,
            None,
            f"account usage moved {delta}, less than the other attempts' measured costs "
            f"{measured} (difference {format(residual, 'f')}); not attributable",
        )
    if residual > own.reserved_usd:
        return Attribution(
            None,
            None,
            f"the residual {format(residual, 'f')} (usage moved {delta}, the other attempts' "
            f"measured costs {measured}) is above the attempt's reservation "
            f"{format(own.reserved_usd, 'f')}: other account spend; not attributable",
        )
    amount = max(residual, Decimal(0))
    evidence = {
        "usage_before_usd": format(window.before, "f"),
        "usage_before_checked_at": window.before_at,
        "usage_after_usd": format(window.after, "f"),
        "usage_after_checked_at": window.after_at,
        "usage_delta_usd": delta,
        "held_attempts": [attempt.attempt_id],
        "other_attempts": sorted(r.attempt_id for r in others),
        "other_attempts_measured_usd": measured,
        "residual_usd": format(residual, "f"),
        "reserved_usd": format(own.reserved_usd, "f"),
        "tolerance_usd": format(USAGE_TOLERANCE_USD, "f"),
        "usage_recorded_by": list(window.recorded_by),
    }
    return Attribution(
        amount,
        evidence,
        f"no generation id; account usage moved {delta}, the other attempts' measured costs "
        f"{measured}: the batch's only held attempt cost {format(amount, 'f')}",
    )


def usage_unmoved(
    client: ChatClient, clock: Callable[[], str], window: UsageWindow
) -> tuple[dict[str, Any] | None, str]:
    """A fresh `GET /api/v1/key` reading at reconcile time, as evidence that the account usage
    has not moved since the after-batch check, or None with why.

    The provider may bill a 404'd or given-up call after the after-batch check, which the delta
    would then omit. A usage-window adjust (404 corroboration or deadline attribution) therefore
    stands only when the usage now equals the recorded after-figure within the tolerance
    (decision 0008 amendment, task 7.0); otherwise the attempt stays held and a later reconcile
    may retry.
    A connection failure propagates (it stops the reconcile, as for every lookup)."""
    fetched = client.fetch_key_status()
    state = from_key_response(fetched.response, clock())
    key_file = dict(fetched.key_note) if fetched.key_note else None
    retry = "not attributed; a later reconcile may retry"
    if state.usage is None:
        return None, f"the account usage now is not reported; {retry}"
    if key_file != window.key_file:
        return None, (
            f"the usage check now records another key-file note than the after-check; {retry}"
        )
    moved = state.usage - window.after
    if abs(moved) > USAGE_TOLERANCE_USD:
        return None, (
            f"usage moved since the after-check ({format(window.after, 'f')} then, "
            f"{format(state.usage, 'f')} now); {retry}"
        )
    return {
        "usage_now_usd": format(state.usage, "f"),
        "usage_now_checked_at": state.checked_at,
    }, ""


def open_ledger(path: Path) -> Ledger:
    """An existing ledger file opened with the cap its first line records."""
    first = path.read_bytes().split(b"\n", 1)[0]
    try:
        cap = Decimal(str(json.loads(first)["cap_usd"]))
    except (ValueError, KeyError, TypeError, InvalidOperation):
        raise LedgerError(f"{path.name} has no readable opening line") from None
    return Ledger(path, cap)


@dataclass(frozen=True)
class SpendCrossCheck:
    """Task 7.14: the key's total usage now against the settled charges under the artifact
    root, from the earliest recorded before-check (the origin). Reported only.

    `settled_usd` is the sum of the own `spent` of every ledger opened at or after the origin
    (each replayed: a reconciled attempt counts its adjusted figure, a hold of unknown cost its
    whole reservation, `held_usd` of it); reservations still open are not in it
    (`open_reservations`). Ledgers opened before the origin are not in the figure; they are
    named in `excluded`, with their settled sum in `excluded_usd` (fix round 1: probe-1, the
    real root's first ledger, predates every recorded check)."""

    origin_file: str
    origin_usd: Decimal
    origin_at: object
    now_usd: Decimal
    now_at: object
    settled_usd: Decimal
    held_usd: Decimal
    open_reservations: int
    ledgers: tuple[str, ...]
    excluded: tuple[str, ...]
    excluded_usd: Decimal

    @property
    def billed_usd(self) -> Decimal:
        return self.now_usd - self.origin_usd

    @property
    def unattributed_usd(self) -> Decimal:
        """Positive: billed but in no counted ledger (late billing, spend outside the runner);
        negative: settled but not billed (refunds, lag). Exact; never rounded."""
        return self.billed_usd - self.settled_usd


@dataclass(frozen=True)
class _Origin:
    check: _Check
    where: str
    at: datetime


def _origin(artifact_root: Path) -> tuple[_Origin | None, str]:
    """The earliest recorded before-check under the root, or None with why it is not known.
    Fail closed: every recorded check must be readable, with a usage figure and a time, and
    the earliest must be alone in its second."""
    found: list[_Origin] = []
    for path in sorted(artifact_root.glob(f"*/{USAGE_FILE.format(phase='before')}")):
        where = path.relative_to(artifact_root).as_posix()
        unknown = "the origin is unknown"
        try:
            check, why = _usage_check(path, "before")
        except ValueError:  # not JSON, or not an object (`_read`)
            return None, f"{where} is not a readable account usage check; {unknown}"
        if check is None:
            return None, f"{where}: {why}; {unknown}"
        at = _instant(check.checked_at)
        if at is None:
            return None, f"{where} records no check time; {unknown}"
        found.append(_Origin(check, where, at))
    if not found:
        return None, "no batch under the artifact root recorded an account usage check before it"
    found.sort(key=lambda origin: (origin.at, origin.where))
    if len(found) > 1 and found[1].at == found[0].at:
        return None, (
            f"{found[0].where} and {found[1].where} checked account usage in the same second; "
            "the origin is unknown"
        )
    return found[0], ""


def _ledgers(artifact_root: Path) -> tuple[list[tuple[datetime, str, LedgerState]] | None, str]:
    """Every ledger's opening time, name and replayed state, or None with why: no ledger, or
    one that does not replay or records no opening time."""
    paths = sorted((artifact_root / ".ledgers").glob("*.jsonl"))
    if not paths:
        return None, "no ledger under .ledgers"
    read: list[tuple[datetime, str, LedgerState]] = []
    for path in paths:
        try:
            ledger = open_ledger(path)
        except LedgerError as error:
            return None, str(error)
        try:
            state = ledger.state()
        except LedgerError as error:
            return None, f"{path.name}: {error}"
        at = _instant(json.loads(path.read_bytes().split(b"\n", 1)[0]).get("at"))
        if at is None:
            return None, f"{path.name} records no opening time"
        read.append((at, path.name, state))
    return read, ""


def spend_cross_check(
    client: ChatClient, clock: Callable[[], str], artifact_root: Path
) -> tuple[SpendCrossCheck | None, str]:
    """Task 7.14: the reconciled report's spend cross-check, or None with why no figure is
    shown. The key's usage now is read once with `GET /api/v1/key`, as `usage_unmoved` reads
    it (DC-7: the key is read for this call, in memory, never printed), and only when the
    ledgers and the origin can be used. It must carry the origin check's key-file note. A
    ledger opened before the origin's second is left out of the settled sum and named. A
    connection or credential failure propagates; `live reconcile` reports it as "not checked"
    without changing its exit code (fix round 1). Nothing is settled or adjusted from it."""
    ledgers, why = _ledgers(artifact_root)
    if ledgers is None:
        return None, why
    origin, why = _origin(artifact_root)
    if origin is None:
        return None, why
    counted = [(name, state) for at, name, state in ledgers if at >= origin.at]
    excluded = [(name, state) for at, name, state in ledgers if at < origin.at]
    fetched = client.fetch_key_status()
    reading = from_key_response(fetched.response, clock())
    key_file = dict(fetched.key_note) if fetched.key_note else None
    if reading.usage is None:
        return None, "the account usage now is not reported"
    if key_file != origin.check.key_file:
        return None, "the usage check now records another key-file note than the origin check"
    attempts = [a for _, state in counted for a in state.attempts]
    return SpendCrossCheck(
        origin_file=origin.where,
        origin_usd=origin.check.usage,
        origin_at=origin.check.checked_at,
        now_usd=reading.usage,
        now_at=reading.checked_at,
        settled_usd=sum((state.spent for _, state in counted), Decimal(0)),
        held_usd=sum(
            (a.charged_usd or Decimal(0) for a in attempts if a.actual_usd is None), Decimal(0)
        ),
        open_reservations=sum(a.status == "reserved" for a in attempts),
        ledgers=tuple(name for name, _ in counted),
        excluded=tuple(name for name, _ in excluded),
        excluded_usd=sum((state.spent for _, state in excluded), Decimal(0)),
    ), ""


def lookup_order(attempts: Sequence[RetainedAttempt]) -> list[RetainedAttempt]:
    """Attempts with a recorded generation id first (stable), so a hold without one is
    attributed after every lookup that could settle another hold."""
    return sorted(attempts, key=lambda item: generation_id(item)[0] is None)


def _replace_metrics(directory: Path, metrics: dict[str, Any]) -> None:
    path = directory / "metrics.json"
    descriptor, temporary = tempfile.mkstemp(prefix=".metrics-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(dump(metrics).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _record_reconciled(
    attempt: RetainedAttempt, record: AttemptRecord, id_source: str, reason: str
) -> None:
    adjustment = record.adjustment
    if adjustment is None:
        raise LedgerError(f"{record.attempt_id} has no adjust line to record")
    block = dict(attempt.metrics["ledger"])
    previous = {
        key: block.get(key) for key in ("attempt_cost_usd", "cost_basis", "cost_reason")
    } | {"charged_usd": format(adjustment.previous_charged_usd, "f")}
    block.update(
        {
            "attempt_cost_usd": adjustment.reconciled_usd,
            "charged_usd": adjustment.reconciled_usd,
            "cost_basis": adjustment.source,
            "cost_reason": reason,
            "unreconciled": False,
            "overrun": adjustment.reconciled_usd > record.reserved_usd,
            "reconciliation": {
                "status": "reconciled",
                "source": adjustment.source,
                "generation_id": adjustment.generation_id,
                "generation_id_source": id_source,
                "checked_at": adjustment.checked_at,
                "ledger_seq": adjustment.seq,
                "previous": previous,
                **({"evidence": adjustment.evidence} if adjustment.evidence else {}),
            },
        }
    )
    _replace_metrics(attempt.directory, {**attempt.metrics, "ledger": block})


def _record_unresolved(
    attempt: RetainedAttempt, generation: str | None, id_source: str, reason: str, at: str
) -> None:
    block = dict(attempt.metrics["ledger"])
    block["reconciliation"] = {
        "status": "unresolved",
        "reason": reason,
        "generation_id": generation,
        "generation_id_source": id_source,
        "checked_at": at,
    }
    _replace_metrics(attempt.directory, {**attempt.metrics, "ledger": block})


def reconcile_attempt(
    attempt: RetainedAttempt,
    ledger: Ledger,
    client: ChatClient,
    clock: Callable[[], str],
    *,
    batch: Sequence[RetainedAttempt],
    usage: tuple[UsageWindow | None, str],
) -> Outcome:
    """Reconcile one held attempt; `batch` and `usage` serve the 404 corroboration only."""
    records = {item.attempt_id: item for item in ledger.state().attempts}
    record = records.get(attempt.attempt_id)
    generation, source = generation_id(attempt)
    if record is not None and record.adjustment is not None:
        # The ledger was adjusted but metrics.json was not updated (an interrupted run).
        reason = "ledger already adjusted; metrics synchronised from the ledger line"
        _record_reconciled(attempt, record, source, reason)
        return Outcome(
            attempt.attempt_id,
            record.adjustment.generation_id,
            source,
            "synchronised",
            record.adjustment.previous_charged_usd,
            record.adjustment.reconciled_usd,
            reason,
        )
    if record is None or record.status != "settled" or record.actual_usd is not None:
        # metrics.json and the ledger disagree; the ledger is the authority and is not changed.
        reason = "the batch ledger holds no unreconciled settlement for this attempt"
        _record_unresolved(attempt, generation, source, reason, clock())
        return Outcome(attempt.attempt_id, generation, source, "unresolved", None, None, reason)
    previous = record.charged_usd
    if generation is None:
        return _attribute(attempt, ledger, client, clock, records, batch, usage, source)
    if not GENERATION_ID.fullmatch(generation):
        reason = "the recorded id is not a generation id; not looked up"
        _record_unresolved(attempt, generation, source, reason, clock())
        return Outcome(attempt.attempt_id, generation, source, "unresolved", previous, None, reason)
    checked_at = clock()
    response = client.fetch_generation(generation)
    cost, reason = generation_cost(response, generation)
    if cost is None and response.status == 404:
        evidence, why = corroborate_404(attempt, tuple(records.values()), batch, usage)
        window = usage[0]
        if evidence is not None and window is not None:  # only once corroborated
            now, unmoved = usage_unmoved(client, clock, window)
            evidence, why = (None, unmoved) if now is None else ({**evidence, **now}, why)
        if evidence is None:
            reason = f"{reason}; {why}"
        else:
            ledger.adjust(
                attempt.attempt_id,
                Decimal(0),
                generation_id=generation,
                checked_at=checked_at,
                source=ADJUST_404_SOURCE,
                evidence=evidence,
            )
            zeroed = {item.attempt_id: item for item in ledger.state().attempts}
            _record_reconciled(attempt, zeroed[attempt.attempt_id], source, why)
            return Outcome(
                attempt.attempt_id, generation, source, "reconciled", previous, Decimal(0), why
            )
    if cost is None:
        _record_unresolved(attempt, generation, source, reason, checked_at)
        return Outcome(attempt.attempt_id, generation, source, "unresolved", previous, None, reason)
    ledger.adjust(attempt.attempt_id, cost, generation_id=generation, checked_at=checked_at)
    adjusted = {item.attempt_id: item for item in ledger.state().attempts}[attempt.attempt_id]
    _record_reconciled(attempt, adjusted, source, reason)
    return Outcome(attempt.attempt_id, generation, source, "reconciled", previous, cost, reason)


def _attribute(
    attempt: RetainedAttempt,
    ledger: Ledger,
    client: ChatClient,
    clock: Callable[[], str],
    records: dict[str, AttemptRecord],
    batch: Sequence[RetainedAttempt],
    usage: tuple[UsageWindow | None, str],
    source: str,
) -> Outcome:
    """A held attempt with no generation id: the usage residual, or unresolved with why."""
    previous = records[attempt.attempt_id].charged_usd
    checked_at = clock()
    found = attribute_usage(attempt, tuple(records.values()), batch, usage)

    def unresolved(why: str) -> Outcome:
        reason = f"no provider_request_id recorded; nothing to look up; {why}"
        _record_unresolved(attempt, None, source, reason, checked_at)
        return Outcome(attempt.attempt_id, None, source, "unresolved", previous, None, reason)

    window = usage[0]
    if found.amount is None or found.evidence is None or window is None:
        return unresolved(found.reason)
    now, why = usage_unmoved(client, clock, window)  # only once the delta attributes it
    if now is None:
        return unresolved(why)
    ledger.adjust(
        attempt.attempt_id,
        found.amount,
        generation_id=None,
        checked_at=checked_at,
        source=ADJUST_USAGE_SOURCE,
        evidence={**found.evidence, **now},
    )
    adjusted = {item.attempt_id: item for item in ledger.state().attempts}[attempt.attempt_id]
    _record_reconciled(attempt, adjusted, source, found.reason)
    return Outcome(
        attempt.attempt_id, None, source, "reconciled", previous, found.amount, found.reason
    )


# Task 7.11: an interrupted attempt (the process ended after its reservation, before the reply).
RECORDED_BY = "deploy-vii live reconcile"
INTERRUPTED = "interrupted"
INTERRUPTED_REASON = "process ended before the reply; no generation id"
INTERRUPTED_SETTLE = (
    "interrupted: process ended before the reply; cost unknown, reservation held (live reconcile)"
)
_CHECK_CASES = frozenset({SCHEMA_CHECK_CASE, SCHEMA_BISECT_CASE})  # their manifests differ
IDENTITY_BASIS = (
    "batch, case, model directory and attempt id from the attempt path; model, endpoint, draw "
    "and request hash from request.json; ticket_id and step_id from the attempt id "
    "(<ticket>-<step>-<n>); nothing about a reply"
)


def _open_or_held(record: AttemptRecord) -> bool:
    """A reservation still open, or a settlement with an unknown cost not yet adjusted."""
    return record.status == "reserved" or (record.actual_usd is None and record.adjustment is None)


def interrupted_attempts(artifact_root: Path, batch_id: str, state: LedgerState) -> list[Path]:
    """Attempt directories of the batch for the interrupted path, whose ledger charge is still
    open or held: one without `manifest.json`, or holding the manifest this path wrote. A
    directory the runner sealed is never one of them."""
    records = {record.attempt_id: record for record in state.attempts}
    found: list[Path] = []
    for directory in sorted((artifact_root / batch_id).glob("*/*/*")):
        record = records.get(directory.name)
        if record is None or not directory.is_dir() or not _open_or_held(record):
            continue
        manifest = directory / "manifest.json"
        if not manifest.is_file() or _read(manifest).get("recorded_by") == RECORDED_BY:
            found.append(directory)
    return found


def _run_identity(attempt_id: str) -> dict[str, str]:
    """`ticket_id` and `step_id` of a dispatch attempt id (`<ticket>-<step>-<n>`, a step repair
    `<ticket>-<step>-repair-<n>`; `runner._plan`), else nothing."""
    for step_id in STEPS:
        match = re.fullmatch(rf"(.+)-{re.escape(step_id)}(?:-repair)?-[0-9]+", attempt_id)
        if match is not None:
            return {"ticket_id": match.group(1), "step_id": step_id}
    return {}


def interrupted_manifest(directory: Path) -> tuple[dict[str, Any] | None, str]:
    """The manifest an interrupted pool attempt's directory supports (request.json only), or
    None with why the directory is not that shape."""
    names = sorted(path.name for path in directory.iterdir())
    if "request.json" not in names:
        return None, "the attempt directory holds no request.json"
    if names != ["request.json"]:
        return None, f"the attempt directory holds {', '.join(names)}, not request.json only"
    case = directory.parent.parent
    if case.name in _CHECK_CASES:
        return None, f"a {case.name} attempt; this path writes no {case.name} record"
    try:
        request = _read(directory / "request.json")
    except ValueError:
        return None, "request.json is not a readable JSON object"
    body = request.get("body")
    model = body.get("model") if isinstance(body, dict) else None
    if request.get("endpoint") != CHAT_URL or not isinstance(model, str):
        return None, "request.json is not a pool chat request"
    if model.replace("/", "__") != directory.parent.name:
        return None, "request.json names another model than its directory"
    # A call lives at most twice its deadline (`client.urllib_transport`: one socket operation
    # past it); before that the runner may still seal this directory, so it is not interrupted.
    parameters = request.get("non_secret_parameters")
    timeout = parameters.get("timeout_s") if isinstance(parameters, dict) else None
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
        return None, "request.json records no call deadline"
    age = time.time() - (directory / "request.json").stat().st_mtime
    if age <= 2 * timeout:
        return None, (
            f"request.json was written {age:.0f} s ago, within twice its {timeout:g} s deadline: "
            "the call may still be in flight"
        )
    selection = request.get("selection")
    draw = selection.get("draw") if isinstance(selection, dict) else None
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {
        "schema": "model-test-attempt/1",
        "recorded_by": RECORDED_BY,
        "identity_basis": IDENTITY_BASIS,
        "experiment_id": case.parent.name,
        "case_id": case.name,
        "attempt_id": directory.name,
        "model": model,
        **_run_identity(directory.name),
        "cohort": POOL_COHORT,
        "status": "no-response",
        "classification": INTERRUPTED,
        "reason": INTERRUPTED_REASON,
        "poolable": False,
        "endpoint": CHAT_URL,
        "hashes": {"request_sha256": digest},
        **({"draw": draw} if isinstance(draw, dict) else {}),
    }, ""


def reconcile_interrupted(
    directory: Path,
    ledger: Ledger,
    client: ChatClient,
    clock: Callable[[], str],
    *,
    batch: Sequence[RetainedAttempt],
    usage: tuple[UsageWindow | None, str],
    next_batch: tuple[NextBatchWindow | None, str] | None = None,
) -> Outcome:
    """Record an interrupted attempt and settle it from the usage window, or say why not.

    Writes the manifest the directory supports (once), then, only where `attribute_usage` and
    `usage_unmoved` both hold, settles the open reservation as held and adjusts it by the
    `account-usage-delta` rule; otherwise the reservation stays open (never a guessed figure).
    A manifest found from an earlier run is used only while the directory still holds exactly
    it and `request.json` (task 7.13: anything more means the runner got further, so no usage
    delta settles it). `next_batch` (task 7.13) is `next_batch_window`'s answer for a batch that
    recorded no after-check: the residual over that window settles it as
    `account-usage-delta/next-batch-before`, with no reconcile-time reading."""
    attempt_id = directory.name
    record = {item.attempt_id: item for item in ledger.state().attempts}[attempt_id]
    reserved = record.status == "reserved"
    held = record.reserved_usd if reserved else record.charged_usd
    kept = "reservation kept open" if reserved else "the charge stays held"

    def unresolved(why: str) -> Outcome:
        reason = f"interrupted attempt; {kept}: {why}"
        return Outcome(attempt_id, None, "none", "unresolved", held, None, reason)

    path = directory / "manifest.json"
    if path.is_file():
        names = sorted(item.name for item in directory.iterdir())
        if names != ["manifest.json", "request.json"]:
            return unresolved(
                f"the attempt directory holds {', '.join(names)}, not manifest.json and "
                "request.json only; not reconciled by this path"
            )
        manifest = _read(path)
        if manifest.get("recorded_by") != RECORDED_BY:
            return unresolved("its manifest was not written by this path; not reconciled by it")
    elif not reserved:
        return unresolved("the ledger settled it, but no manifest was sealed")
    else:
        written, refusal = interrupted_manifest(directory)
        if written is None:
            return unresolved(f"{refusal}; not reconciled by this path")
        write_once(path, dump(written))
        manifest = written
    checked_at = clock()
    attempts = ledger.state().attempts
    retained = RetainedAttempt(directory, manifest, {})
    source, closed = ADJUST_USAGE_SOURCE, ""
    if usage[0] is None and next_batch is not None:
        later, why = next_batch
        if later is None:
            return unresolved(f"{usage[1]}; {why}")
        found = attribute_usage(retained, attempts, batch, (later.window, ""))
        if found.amount is None or found.evidence is None:
            return unresolved(f"{later.reason}; {found.reason}")
        source, closed = ADJUST_NEXT_BEFORE_SOURCE, f"; {later.reason}"
        evidence = {**found.evidence, **later.evidence}
    else:
        found = attribute_usage(retained, attempts, batch, usage)
        window = usage[0]
        if found.amount is None or found.evidence is None or window is None:
            return unresolved(found.reason)
        now, why = usage_unmoved(client, clock, window)  # only once the delta attributes it
        if now is None:
            return unresolved(why)
        evidence = {**found.evidence, **now}
    if reserved:
        ledger.settle(attempt_id, None, INTERRUPTED_SETTLE)
    ledger.adjust(
        attempt_id,
        found.amount,
        generation_id=None,
        checked_at=checked_at,
        source=source,
        evidence=evidence,
    )
    reason = f"interrupted attempt ({INTERRUPTED_REASON}); settled by {source}: {found.reason}"
    return Outcome(attempt_id, None, "none", "reconciled", held, found.amount, reason + closed)


def candidates(artifact_root: Path, batch_id: str) -> list[RetainedAttempt]:
    """Pool attempts of the batch still flagged unreconciled (proxy attempts cost nothing)."""
    return [
        attempt
        for attempt in batch_attempts(artifact_root, batch_id)
        if attempt.unreconciled and attempt.manifest.get("cohort") == POOL_COHORT
    ]
