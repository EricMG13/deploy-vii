"""Read the `[model_tests]` contract from settings/project.toml (stdlib tomllib only)."""

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS = Path("settings/project.toml")


class SettingsError(ValueError):
    """The settings file does not hold a usable `[model_tests]` contract."""


@dataclass(frozen=True)
class CandidateSetting:
    key: str
    model_id: str
    resolution: str


@dataclass(frozen=True)
class RecurringCaps:
    e1_per_case: Decimal
    e2_per_milestone: Decimal
    e3_per_week: Decimal
    cumulative_ceiling: Decimal


@dataclass(frozen=True)
class LiveSettings:
    credential_file: Path
    credential_token_index: int  # 1-based token in the key file, in file order (DC-7)
    # Measured lower bound on request-body bytes per prompt token (decision 0008, MC-10).
    prompt_bytes_per_token_lower_bound: Decimal
    artifact_root: Path
    default_effort: str
    complex_effort: str
    candidates: tuple[CandidateSetting, ...]
    caps: RecurringCaps
    model_calls_in_ci: bool


def _table(document: dict[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name)
    if not isinstance(value, dict):
        raise SettingsError(f"settings are missing the [{name}] table")
    return value


def _text(table: dict[str, Any], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise SettingsError(f"settings [model_tests] needs a text value for {key}")
    return value


def _money(table: dict[str, Any], key: str) -> Decimal:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SettingsError(f"settings [model_tests] needs a number for {key}")
    return Decimal(str(value))


def _token_index(table: dict[str, Any]) -> int:
    value = table.get("credential_token_index", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SettingsError("settings [model_tests] credential_token_index must be an integer >= 1")
    return value


def _bytes_per_token(table: dict[str, Any]) -> Decimal:
    key = "prompt_bytes_per_token_lower_bound"
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SettingsError(f"settings [model_tests] needs a number for {key}")
    ratio = Decimal(str(value))
    if not ratio.is_finite() or ratio <= 0:
        raise SettingsError(f"settings [model_tests] {key} must be a positive number")
    return ratio


def load_settings(path: Path = DEFAULT_SETTINGS, *, root: Path | None = None) -> LiveSettings:
    """Load settings; relative paths resolve against `root` (default: the file's repository)."""
    base = root if root is not None else path.resolve().parent.parent
    with path.open("rb") as stream:
        document = tomllib.load(stream)
    tests = _table(document, "model_tests")
    rows = tests.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise SettingsError("settings [model_tests] declares no candidates")
    candidates = tuple(
        CandidateSetting(_text(row, "key"), _text(row, "model_id"), _text(row, "resolution"))
        for row in rows
    )
    if len({item.key for item in candidates}) != len(candidates):
        raise SettingsError("settings [model_tests] repeats a candidate key")
    caps = tests.get("recurring_caps_usd")
    if not isinstance(caps, dict):
        raise SettingsError("settings [model_tests] needs recurring_caps_usd")
    artifact_root = Path(_text(tests, "artifact_root"))
    if not artifact_root.is_absolute():
        artifact_root = base / artifact_root
    return LiveSettings(
        credential_file=Path(_text(tests, "credential_file")).expanduser(),
        credential_token_index=_token_index(tests),
        prompt_bytes_per_token_lower_bound=_bytes_per_token(tests),
        artifact_root=artifact_root,
        default_effort=_text(tests, "default_effort"),
        complex_effort=_text(tests, "complex_effort"),
        candidates=candidates,
        caps=RecurringCaps(
            e1_per_case=_money(caps, "e1_per_case"),
            e2_per_milestone=_money(caps, "e2_per_milestone"),
            e3_per_week=_money(caps, "e3_per_week"),
            cumulative_ceiling=_money(tests, "cumulative_ceiling_usd"),
        ),
        model_calls_in_ci=bool(_table(document, "ci").get("model_calls", False)),
    )
