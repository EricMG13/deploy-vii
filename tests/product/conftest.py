"""Suite-wide fixtures.

Hosted CI runs Linux without macOS `textutil`. When the real tool is absent every test gets a
test double of it first on PATH (`fake_textutil.py`), so the credential loader's conversion
branch and the live-runner tests run on every platform. Where the real tool exists it is used.
"""

import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from tests.product import fake_textutil


@pytest.fixture(scope="session")
def fake_textutil_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("fake-textutil")
    launcher = directory / "textutil"
    script = Path(fake_textutil.__file__).resolve()
    launcher.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -I "{script}" "$@"\n', encoding="utf-8"
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return directory


@pytest.fixture(autouse=True)
def textutil_on_path(monkeypatch: pytest.MonkeyPatch, fake_textutil_dir: Path) -> None:
    if shutil.which("textutil") is None:
        monkeypatch.setenv("PATH", os.pathsep.join([str(fake_textutil_dir), os.environ["PATH"]]))
