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


def test_live_module_passes_models_max_tokens_batch_id_and_seed_through() -> None:
    """Task 7.0: E1 runs `make live-module` with its pinned model, budget, batch id and seed."""
    done = make(
        "live-module",
        "MODULE=CP-1",
        "CAP=3",
        "MODELS=openai/gpt-6.1-sol@high",
        "MAX_TOKENS=32000",
        "BATCH_ID=e1-cp1",
        "SEED=1404762132",
    )
    assert done.returncode == 0
    assert (
        '--module "CP-1" --cap "3" --models "openai/gpt-6.1-sol@high" --max-tokens "32000" '
        '--batch-id "e1-cp1" --seed "1404762132"'
    ) in done.stdout


def test_live_module_without_the_optional_variables_sends_no_such_option() -> None:
    done = make("live-module", "MODULE=CP-0", "CAP=2")
    assert done.returncode == 0
    for option in ("--models", "--max-tokens", "--batch-id", "--seed"):
        assert option not in done.stdout


def test_makefile_never_names_the_key() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "OPENROUTER" not in text and "sk-or" not in text and "--key" not in text
