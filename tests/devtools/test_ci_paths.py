"""Dry-run of the docs-only classifier used by the Product checks job."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "code_changed.sh"


def classify(paths: list[str]) -> str:
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input="".join(f"{p}\n" for p in paths),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["docs/x.md"], "false"),
        (["README.md"], "false"),
        (["docs/a.png", "LICENSE", ".gitignore", ".gitattributes", "CODEOWNERS"], "false"),
        (["docs/my notes.md"], "false"),
        (["docs/ci-gates.md", "src/deploy_vii/x.py"], "true"),
        (["settings/project.toml"], "true"),
        (["uv.lock"], "true"),
        (["pyproject.toml"], "true"),
        (["Makefile"], "true"),
        ([".github/workflows/ci.yml"], "true"),
        (["scripts/anything"], "true"),
        (["tests/devtools/t.py"], "true"),
        (["foo.txt"], "true"),
        (["src/with space/x.py"], "true"),
        ([], "true"),
    ],
)
def test_classification(paths: list[str], expected: str) -> None:
    assert classify(paths) == expected
