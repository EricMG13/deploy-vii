"""Import supplied Claude JSONL evidence without copying prose into summaries."""

import json
from pathlib import Path

from devtools.storage import (
    Json,
    Object,
    digest,
    encode,
    immutable_write,
    local_store,
    locked,
    read_object,
)

METRICS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def obj(value: Json) -> Object:
    return value if isinstance(value, dict) else {}


def usage_fields(usage: Object) -> Object:
    return {
        key: value if type(value := usage.get(key)) is int and value >= 0 else None
        for key in METRICS
    }


def normalize(event: Object, host: str, session: str) -> Object | None:
    session_hash = digest(session.encode())
    message = obj(event.get("message"))
    usage = obj(message.get("usage"))
    request_id = message.get("id")
    if event.get("type") != "assistant" or not usage or not isinstance(request_id, str):
        return None
    kind = "per_request"
    normalized_usage = usage_fields(usage)
    identity = request_id
    record: Object = {
        "host": host,
        "session": session_hash,
        "kind": kind,
        "usage": normalized_usage,
        "missing_metric_reason": "not exposed as a nonnegative integer by the supplied event",
    }
    record["event_id"] = digest(encode([host, session_hash, kind, identity]))
    return record


def import_events(repo: Path, root: Path, source: Path, host: str, session: str) -> Object:
    if host != "claude" or not session:
        raise ValueError("explicit host and session required")
    root = local_store(repo, root)
    raw = source.read_bytes()
    source_hash = digest(raw)
    normalized: list[Json] = []
    invalid_lines: list[Json] = []
    ignored = 0
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("not an object")
            encode(value)
            event = normalize(value, host, session)
        except (ValueError, UnicodeDecodeError):
            invalid_lines.append(number)
            continue
        if event is None:
            ignored += 1
        else:
            normalized.append(event)
    manifest: Object = {
        "schema_version": 1,
        "raw_sha256": source_hash,
        "host": host,
        "session": digest(session.encode()),
        "events": normalized,
        "invalid_lines": invalid_lines,
        "unrecognized_events": ignored,
    }
    with locked(root):
        immutable_write(root / "raw" / f"{source_hash}.jsonl", raw)
        immutable_write(root / "imports" / f"{digest(encode(manifest))}.json", encode(manifest))
    return {
        "raw_sha256": source_hash,
        "recognized_events": len(normalized),
        "invalid_lines": invalid_lines,
        "unrecognized_events": ignored,
    }


def report(root: Path) -> Object:
    events: dict[str, Object] = {}
    conflicts: set[str] = set()
    invalid_lines = 0
    ignored = 0
    for path in sorted((root / "imports").glob("*.json")):
        manifest = read_object(path)
        if path.stem != digest(encode(manifest)):
            raise ValueError("telemetry import digest mismatch")
        source_hash = manifest.get("raw_sha256")
        if not isinstance(source_hash, str) or len(source_hash) != 64:
            raise ValueError("invalid raw evidence identity")
        if any(character not in "0123456789abcdef" for character in source_hash):
            raise ValueError("invalid raw evidence identity")
        if digest((root / "raw" / f"{source_hash}.jsonl").read_bytes()) != source_hash:
            raise ValueError("raw telemetry digest mismatch")
        manifest_events = manifest.get("events")
        if not isinstance(manifest_events, list):
            raise ValueError("malformed telemetry import")
        invalid = manifest.get("invalid_lines")
        invalid_lines += len(invalid) if isinstance(invalid, list) else 0
        count = manifest.get("unrecognized_events")
        ignored += count if isinstance(count, int) else 0
        for item in manifest_events:
            if not isinstance(item, dict) or not isinstance(item.get("event_id"), str):
                raise ValueError("malformed normalized event")
            identity = str(item["event_id"])
            if identity in events and events[identity] != item:
                conflicts.add(identity)
            events[identity] = item
    # Conflicting request variants are retained in imports but cannot establish usage.
    usable = [event for key, event in sorted(events.items()) if key not in conflicts]
    return {
        "schema_version": 1,
        "event_count": len(events),
        "conflicts": [item for item in sorted(conflicts)],
        "per_request": [event for event in usable if event["kind"] == "per_request"],
        "accounting": "Per-request series; never add cached subtotals to token totals.",
        "invalid_lines": invalid_lines,
        "unrecognized_events": ignored,
        "occupancy": {"value": None, "reason": "no qualified occupancy signal"},
        "cost_usd": {"value": None, "reason": "native token logs do not establish billed cost"},
        "latency_ms": {"value": None, "reason": "no qualified request start/end spans"},
    }
