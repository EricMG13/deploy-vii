"""Make targets for the live CLI: exact names, CAP/MODULE required, no key variable."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def make(*args: str, dry: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["make", *(["-n"] if dry else []), *args]
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        (["replay"], "pytest tests/product/test_replay.py -q"),
        (["live-probe", "CAP=1.5"], 'probe --directory "artifacts/execution" --cap "1.5"'),
        (["live-module", "MODULE=CP-0", "CAP=2"], '--module "CP-0" --cap "2"'),
        (["live-regression", "CAP=3"], 'regression --directory "artifacts/execution" --cap "3"'),
        (["live-canary", "CAP=4"], 'canary --directory "artifacts/execution" --cap "4"'),
    ],
)
def test_target_expands_to_the_live_command(args: list[str], needle: str) -> None:
    done = make(*args)
    assert done.returncode == 0 and needle in done.stdout


@pytest.mark.parametrize("target", ["live-probe", "live-regression", "live-canary", "live-module"])
def test_cap_is_required_by_every_live_target(target: str) -> None:
    done = make(target, "MODULE=CP-0", dry=False)
    assert done.returncode != 0 and "required" in done.stdout + done.stderr


def test_makefile_never_names_the_key() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "OPENROUTER" not in text and "sk-or" not in text and "--key" not in text
