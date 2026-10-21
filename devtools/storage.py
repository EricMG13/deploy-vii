"""Atomic local evidence storage. The lock serializes files, not workspace owners."""

import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

type Json = bool | int | float | str | list[Json] | dict[str, Json] | None
type Object = dict[str, Json]


def encode(value: Json) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_object(path: Path) -> Object:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    encode(value)  # Reject non-finite JSON extensions.
    return cast(Object, value)


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def local_store(repo: Path, root: Path) -> Path:
    root = root.resolve()
    if not root.is_relative_to(repo.resolve()) or root == repo.resolve():
        raise ValueError("evidence store must be inside the repository's ignored local area")
    probe = root / ".devtools-probe"
    result = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", "--", str(probe)], check=False
    )
    if result.returncode != 0:
        raise ValueError("evidence store must be Git-ignored")
    if git(repo, "ls-files", "--", str(root)).strip():
        raise ValueError("evidence store contains tracked files")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


@contextmanager
def locked(root: Path) -> Iterator[None]:
    with (root / ".lock").open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another record update is active; retry after it finishes") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def immutable_write(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("immutable evidence collision")
        return
    atomic_write(path, data)
