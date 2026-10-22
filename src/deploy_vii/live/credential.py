"""Decision 0006 DC-7: read the OpenRouter key at dispatch time, hold it in memory only.

The key file is RTF written by a person. `textutil` (macOS) converts it to text, which may
carry a label, blank lines, quotes or other prose around the key; the loader keeps one whole
key-shaped token. When the file holds several distinct tokens, `[model_tests].
credential_token_index` (1-based, in the converted text's order, default 1) picks one; the choice
is explicit and recorded through `LoadedKey.note()` because probe-1 showed the first token can be
accepted by `GET /api/v1/key` yet refused on chat completions. There is no automatic fallback to
another token on any error. Every failure here is deliberately silent about file content:
messages never echo what was read, only counts. Without `textutil` the loader fails closed; there
is no fallback parser.

Known fail-open (documented, coordinator's choice, M2 key-loader review): a key broken inside by
an invisible format character (U+200B, a soft hyphen) or a line break yields a truncated token,
which is returned as the key. Truncation cannot be told from "key followed by prose" without a
length rule for OpenRouter keys, which none has been authorized. The effect is a wrong key sent
to OpenRouter (HTTP 401 or a refused key check, both recorded); nothing leaks and nothing is
spent.
"""

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REDACTED = "[REDACTED]"
# The left boundary keeps ordinary words ("risk-or-reward", "disk-or-network") untouched. It
# excludes only letters and digits, so a key glued on after "-" or "_" ("api-sk-or-v1-...") is
# still caught.
_KEY_SHAPE = re.compile(r"(?<![A-Za-z0-9])sk-or-[A-Za-z0-9_\-]{6,}")
# Loading is stricter than scrubbing: the token must stand alone, so a letter, digit, "_" or "-"
# (any script) on either side means it is not a token ("xsk-or-...", "api-sk-or-...", "...é").
_KEY_TOKEN = re.compile(r"(?<![\w-])sk-or-[A-Za-z0-9_\-]{6,}+(?![\w-])")
# Only a bearer token that follows an Authorization header name: "Bearer bonds" in a filing stays.
_AUTH_HEADER = re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+)?[^\s\"',;}]+")
_CONVERT_TIMEOUT_SECONDS = 30


class CredentialError(Exception):
    """The credential could not be loaded. The message never contains file content."""


@dataclass(frozen=True)
class LoadedKey:
    """The key in use and where it came from. `repr` and `note()` never carry the key."""

    key: str = field(repr=False)
    tokens_found: int  # distinct standalone tokens in the file
    index_used: int  # 1-based position of `key` among them, in file order

    def note(self) -> dict[str, int]:
        """The loader's choice for logs and manifests: counts only, never token text."""
        return {"key_tokens_found": self.tokens_found, "key_token_used": self.index_used}


def load_key(path: Path, index: int = 1) -> str:
    """Return the key from an RTF/text file; raise CredentialError without echoing content."""
    return load_key_with_note(path, index).key


def load_key_with_note(path: Path, index: int = 1) -> LoadedKey:
    """The distinct token at 1-based `index` in file order, with how many the file held."""
    # bool is an int subclass, and 0 or -1 would silently select from the end of the list.
    if isinstance(index, bool) or not isinstance(index, int) or index < 1:
        raise CredentialError("credential_token_index must be an integer >= 1")
    source = path.expanduser()
    if not source.is_file():
        raise CredentialError("credential file does not exist")
    textutil = shutil.which("textutil")
    if textutil is None:
        raise CredentialError("textutil is unavailable; credential loading fails closed")
    try:
        done = subprocess.run(
            [textutil, "-convert", "txt", "-stdout", str(source)],
            capture_output=True,
            check=False,
            timeout=_CONVERT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise CredentialError("textutil could not convert the credential file") from None
    if done.returncode != 0:
        raise CredentialError(f"textutil exited with status {done.returncode}")
    try:
        text = done.stdout.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CredentialError("credential file is not UTF-8 text") from None
    return _token_at(text, index)


def _token_at(text: str, index: int) -> LoadedKey:
    """The `index`-th distinct key token in `text`; the same token repeated counts once."""
    tokens = list(dict.fromkeys(match.group() for match in _KEY_TOKEN.finditer(text)))
    if not tokens:
        lines = sum(1 for line in text.splitlines() if line.strip())
        if lines == 0:
            raise CredentialError("credential file is empty")
        raise CredentialError(f"no key-shaped token among {lines} non-empty lines")
    if index > len(tokens):
        raise CredentialError(
            f"credential_token_index {index} but only {len(tokens)} key-shaped tokens"
        )
    return LoadedKey(tokens[index - 1], len(tokens), index)


def scrub_key(text: str, key: str) -> str:
    """Replace the exact key and any key-shaped token. Safe for evidence and model output:
    nothing else is rewritten, so quotes and source text stay verbatim."""
    if key:
        text = text.replace(key, REDACTED)
    return _KEY_SHAPE.sub(REDACTED, text)


def redact(text: str, key: str) -> str:
    """`scrub_key` plus Authorization header values. For exception and error text only: it
    would rewrite prose such as "Authorization: the board", so never use it on evidence."""
    return _AUTH_HEADER.sub(r"\1" + REDACTED, scrub_key(text, key))
