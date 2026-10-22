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
`account-usage-{before,after}.json` under the batch directory, same key token) moved by exactly
the sum of the other pool attempts' measured costs (provider-reported, known-zero or reconciled
from the endpoint) within US$0.000001, the held attempts together cost nothing measurable, so
the attempt is adjusted to 0 with source `generation-404+usage-delta` and both facts in the
ledger line. Anything short of that (no record, a usage figure missing, different key tokens,
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
"""

import json
import os
import tempfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from deploy_vii.live.client import GENERATION_ID, ChatClient, Response
from deploy_vii.live.credit import from_key_response
from deploy_vii.live.ledger import (
    ADJUST_404_SOURCE,
    ADJUST_SOURCE,
    ADJUST_USAGE_SOURCE,
    AttemptRecord,
    Ledger,
    LedgerError,
)
from deploy_vii.live.retention import dump

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


def read_usage(artifact_root: Path, batch_id: str) -> tuple[UsageWindow | None, str]:
    """The batch's recorded usage window, or None with the reason it cannot be used."""
    found: dict[str, tuple[Decimal, object, object, object]] = {}
    for phase in ("before", "after"):
        path = usage_path(artifact_root, batch_id, phase)
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
        found[phase] = (
            value,
            credit.get("checked_at"),
            credit.get("key_file"),
            document.get("recorded_by"),
        )
    before, after = found["before"], found["after"]
    if before[2] != after[2]:
        return None, "the two account usage checks read different key tokens"
    return (
        UsageWindow(before[0], after[0], before[1], after[1], (before[3], after[3]), after[2]),
        "",
    )


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
        return None, f"the usage check now reads another key token than the after-check; {retry}"
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


def candidates(artifact_root: Path, batch_id: str) -> list[RetainedAttempt]:
    """Pool attempts of the batch still flagged unreconciled (proxy attempts cost nothing)."""
    return [
        attempt
        for attempt in batch_attempts(artifact_root, batch_id)
        if attempt.unreconciled and attempt.manifest.get("cohort") == POOL_COHORT
    ]
