"""Read the `[model_tests]` contract from settings/project.toml (stdlib tomllib only).

Task 8.0d adds three user-owned entries, each optional (absent: the earlier behaviour):
`tool_loop` (run the registry's tool-loop steps through `live.loop`), the per-step effort table
`[model_tests.step_effort]` (`<step> = { effort = "...", ceiling = "..." }`; without a row a
step uses `default_effort`) and `[model_tests.completeness_floor] min_statement_lines`.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from deploy_vii.registry import step_modules

# The effort values in escalation order (task 8.0d; OpenRouter's documented levels the catalog
# lists for the pool models).
EFFORT_LADDER = ("low", "medium", "high", "xhigh", "max")
# Escalation never passes this level unless a step's row names a higher ceiling.
DEFAULT_CEILING = "high"

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
class StepEffort:
    """A step's effort and the highest level its one-level escalation may reach (task 8.0d)."""

    effort: str
    ceiling: str

    def __post_init__(self) -> None:
        for value in (self.effort, self.ceiling):
            if value not in EFFORT_LADDER:
                raise SettingsError(f"effort {value!r} is not one of {', '.join(EFFORT_LADDER)}")
        if EFFORT_LADDER.index(self.ceiling) < EFFORT_LADDER.index(self.effort):
            raise SettingsError(f"ceiling {self.ceiling} is below effort {self.effort}")

    @classmethod
    def of(cls, effort: str, ceiling: str | None = None) -> "StepEffort":
        """`ceiling` defaults to `high`, or to `effort` when that is already above it."""
        if ceiling is None and effort in EFFORT_LADDER:
            top = max(EFFORT_LADDER.index(effort), EFFORT_LADDER.index(DEFAULT_CEILING))
            ceiling = EFFORT_LADDER[top]
        return cls(effort, DEFAULT_CEILING if ceiling is None else ceiling)

    def escalated(self) -> str:
        """One level above `effort`, never above `ceiling` (deterministic)."""
        level = min(EFFORT_LADDER.index(self.effort) + 1, EFFORT_LADDER.index(self.ceiling))
        return EFFORT_LADDER[level]


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
    tool_loop: bool = False
    step_efforts: Mapping[str, StepEffort] = field(default_factory=dict)
    completeness_floor: int | None = None  # statement lines per expected cell; None: no floor

    def step_effort(self, step_id: str) -> StepEffort:
        """The step's row of the effort table, else `default_effort` (`StepEffort.of`)."""
        return self.step_efforts.get(step_id) or StepEffort.of(self.default_effort)


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


def _step_efforts(tests: dict[str, Any]) -> dict[str, StepEffort]:
    table = tests.get("step_effort", {})
    if not isinstance(table, dict):
        raise SettingsError("settings [model_tests.step_effort] must be a table")
    known = step_modules()
    rows: dict[str, StepEffort] = {}
    for step_id, row in table.items():
        if step_id not in known:
            raise SettingsError(
                f"settings [model_tests.step_effort] names an unknown step {step_id}"
            )
        if not isinstance(row, dict) or set(row) - {"effort", "ceiling"} or "effort" not in row:
            raise SettingsError(f"settings step_effort.{step_id} needs effort (and ceiling only)")
        effort, ceiling = row["effort"], row.get("ceiling")
        if not isinstance(effort, str) or not (ceiling is None or isinstance(ceiling, str)):
            raise SettingsError(f"settings step_effort.{step_id} values must be text")
        rows[step_id] = StepEffort.of(effort, ceiling)
    return rows


def _floor(tests: dict[str, Any]) -> int | None:
    table = tests.get("completeness_floor")
    if table is None:
        return None
    value = table.get("min_statement_lines") if isinstance(table, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SettingsError(
            "settings [model_tests.completeness_floor] min_statement_lines must be an integer >= 1"
        )
    return value


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
        tool_loop=_flag(tests, "tool_loop"),
        step_efforts=_step_efforts(tests),
        completeness_floor=_floor(tests),
    )


def _flag(table: dict[str, Any], key: str) -> bool:
    value = table.get(key, False)
    if not isinstance(value, bool):
        raise SettingsError(f"settings [model_tests] {key} must be true or false")
    return value
