"""Per-attempt evidence under artifacts/model-tests/<experiment>/<case>/<model>/<attempt>/.

Layout from docs/testing-and-telemetry.md: manifest.json, request.json, response.json,
output.md, events.jsonl, metrics.json, checks/ and render/. Files are written once (never
overwritten) through temp-file, fsync and link. Raw evidence is staged first; the manifest
is written last, so a directory without manifest.json is an incomplete attempt. Nothing here
receives the credential; as defence in depth every text is also scrubbed of key-shaped tokens.
"""

import base64
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from deploy_vii.live.client import ACCOUNT_ID, REDACTED, ChatResult, account_id_left
from deploy_vii.live.credential import scrub_key

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]*$")


class RetentionError(Exception):
    """The evidence location is unsafe or the attempt directory already exists."""


@dataclass(frozen=True)
class AttemptLocator:
    experiment: str
    case: str
    model: str
    attempt: str

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any]) -> "AttemptLocator":
        return cls(
            str(manifest["experiment_id"]),
            str(manifest["case_id"]),
            str(manifest["model"]),
            str(manifest["attempt_id"]),
        )

    def parts(self) -> tuple[str, ...]:
        names = (self.experiment, self.case, self.model.replace("/", "__"), self.attempt)
        for name in names:
            if not _SAFE.match(name) or ".." in name:
                raise RetentionError(f"unsafe evidence path component {name!r}")
        return names


# A JSON object key `"user_id"` and its scalar value. The key's opening quote follows no
# backslash: in valid JSON a quote inside a string is always escaped, a token quote never is.
_ACCOUNT_VALUE = re.compile(
    rb'(?<!\\)("user_id"\s*:\s*)("(?:[^"\\]|\\.)*"|-?[0-9][0-9.eE+-]*|true|false|null)'
)


def redact_account_id(raw: bytes) -> tuple[bytes, tuple[str, ...]]:
    """`raw` with every `user_id` value replaced by `"<redacted>"` in place (key, spacing and
    every other byte kept), and `("user_id",)` when anything was replaced (task 7.10 item 8)."""
    stored, count = _ACCOUNT_VALUE.subn(
        lambda match: match.group(1) + b'"' + REDACTED.encode() + b'"', raw
    )
    return stored, (ACCOUNT_ID,) if count else ()


def response_envelope(result: ChatResult | None, reason: str | None = None) -> dict[str, Any]:
    """Keep the returned bytes (text when UTF-8, else base64) plus the stored bytes' hash.

    The only change is the account id: every `user_id` value is stored as `"<redacted>"`
    (`body_redactions` names it, and `AttemptWriter.seal` copies it into the manifest). A body
    whose account id cannot be redacted in place is withheld whole (`body_withheld`), never
    stored with it; nothing is stored, so its `body_redactions` is empty (task 7.11)."""
    if result is None or result.raw is None:
        return {
            "http_status": None if result is None else result.http_status,
            "body_text": None,
            "reason": reason or (result.error_detail if result else "no response received"),
        }
    stored, redactions = redact_account_id(result.raw)
    envelope: dict[str, Any] = {
        "http_status": result.http_status,
        "scrubbed_of_credential_shapes": result.redacted,
    }
    if account_id_left(stored):
        return {
            **envelope,
            "body_text": None,
            "body_withheld": "a user_id could not be redacted in place",
            "body_redactions": [],
        }
    envelope.update(body_bytes=len(stored), body_sha256=hashlib.sha256(stored).hexdigest())
    if redactions:
        envelope["body_redactions"] = list(redactions)
    try:
        envelope["body_text"] = stored.decode("utf-8")
    except UnicodeDecodeError:
        envelope["body_text"] = None
        envelope["body_base64"] = base64.b64encode(stored).decode("ascii")
    return envelope


def _default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"{type(value).__name__} is not retention-serializable")


def dump(document: object) -> str:
    return (
        json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False, default=_default) + "\n"
    )


def write_once(path: Path, text: str) -> bool:
    """Write a new evidence file (temp file, fsync, link: an existing file is never replaced).

    Only key-shaped tokens are replaced (never header-like prose); True if any were."""
    scrubbed = scrub_key(text, "")
    data = scrubbed.encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".part-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # fails if the file exists: evidence is never replaced
    finally:
        Path(temporary).unlink(missing_ok=True)
    return scrubbed != text


class AttemptWriter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._altered: dict[Path, list[str]] = {}
        self._redacted: dict[Path, list[str]] = {}  # `body_redactions` of each staged response

    def path_for(self, locator: AttemptLocator) -> Path:
        return self.root.joinpath(*locator.parts())

    def _put(self, path: Path, text: str) -> None:
        """Write once; remember any file whose key-shaped tokens had to be replaced."""
        if self._write_new(path, text):
            parent = path.parent.parent if path.parent.name in {"checks", "render"} else path.parent
            self._altered.setdefault(parent, []).append(str(path.relative_to(parent)))

    @staticmethod
    def _write_new(path: Path, text: str) -> bool:
        return write_once(path, text)

    def begin(self, locator: AttemptLocator, request: Mapping[str, Any]) -> Path:
        """Create the attempt directory and retain the exact request before it is sent."""
        directory = self.path_for(locator)
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise RetentionError(
                "attempt directory already exists; attempts are immutable"
            ) from None
        self._put(directory / "request.json", dump(request))
        return directory

    def record_response(
        self, locator: AttemptLocator, response: Mapping[str, Any], output: str | None
    ) -> None:
        """Retain the raw response and extracted output before any validation can fail."""
        directory = self.path_for(locator)
        self._put(directory / "response.json", dump(response))
        self._put(directory / "output.md", output or "")
        if redactions := response.get("body_redactions"):
            self._redacted[directory] = list(redactions)

    def stage(
        self,
        locator: AttemptLocator,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
        output: str | None,
    ) -> Path:
        """`begin` then `record_response` in one call."""
        directory = self.begin(locator, request)
        self.record_response(locator, response, output)
        return directory

    def seal(
        self,
        locator: AttemptLocator,
        manifest: Mapping[str, Any],
        events: Sequence[Mapping[str, Any]],
        metrics: Mapping[str, Any],
        checks: Mapping[str, Any] | None = None,
        *,
        scrubbed_upstream: Sequence[str] = (),
    ) -> Path:
        """Write events, metrics, checks and render notes, then the manifest last.

        `scrubbed_upstream` names files the caller scrubbed before handing them over."""
        directory = self.path_for(locator)
        if not (directory / "output.md").exists():
            raise RetentionError("the response was never retained; call record_response first")
        (directory / "checks").mkdir(exist_ok=True)
        (directory / "render").mkdir(exist_ok=True)
        self._put(
            directory / "events.jsonl",
            "".join(json.dumps(event, sort_keys=True, default=_default) + "\n" for event in events),
        )
        self._put(directory / "metrics.json", dump(metrics))
        for name, check in (checks or {}).items():
            self._put(directory / "checks" / f"{name}.json", dump(check))
        self._put(
            directory / "render" / "not-run.json",
            dump({"status": "not_run", "reason": "the runner core renders nothing; see Task C/M3"}),
        )
        # Files whose key-shaped tokens were replaced (by the writer, or by the caller before the
        # writer saw them) are named in the manifest. manifest.json itself is not listed.
        scrubbed = sorted({*self._altered.pop(directory, []), *scrubbed_upstream})
        sealed = {**manifest, "scrubbed_files": scrubbed}
        # The stored response body's redactions (`response_envelope`), named when applied.
        if redactions := self._redacted.pop(directory, None):
            sealed["body_redactions"] = redactions
        self._put(directory / "manifest.json", dump(sealed))
        return directory

    def write(
        self,
        manifest: Mapping[str, Any],
        request: Mapping[str, Any],
        response: Mapping[str, Any],
        output: str | None,
        events: Sequence[Mapping[str, Any]],
        metrics: Mapping[str, Any],
        checks: Mapping[str, Any] | None = None,
    ) -> Path:
        """Stage and seal one attempt in a single call; the manifest is written last."""
        locator = AttemptLocator.from_manifest(manifest)
        self.stage(locator, request, response, output)
        return self.seal(locator, manifest, events, metrics, checks)
