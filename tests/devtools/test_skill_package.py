"""Offline package checks for the native Copilot skill (M11 task 11.1).

Shape only: nothing here exercises a Copilot host or executes a deploy-vii command.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".github" / "skills" / "deploy-vii"
SKILL_FILES = [SKILL_DIR / "SKILL.md", *sorted((SKILL_DIR / "references").glob("*.md"))]
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
PLACEHOLDER = re.compile(r"<[^>\s]+>")
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
PATH_REFERENCE = re.compile(r"`((?:references|docs|settings|src|tests)/[\w./-]+)`")
SECRET = re.compile(r"sk-or-|sk-ant-")
ACCEPTANCE_CLAIM = re.compile(
    r"accepted on (the|a) (real )?(copilot )?host|native acceptance passed", re.IGNORECASE
)


def frontmatter(text: str) -> dict[str, str]:
    parts = text.split("---\n")
    assert parts[0] == "" and len(parts) >= 3, "SKILL.md must open with a --- frontmatter block"
    fields: dict[str, str] = {}
    for line in parts[1].splitlines():
        key, separator, value = line.partition(":")
        assert separator, f"frontmatter line is not key: value: {line!r}"
        fields[key.strip()] = value.strip()
    return fields


def commands() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for path in SKILL_FILES:
        for block in FENCE.findall(path.read_text(encoding="utf-8")):
            found += [
                (path, line.strip())
                for line in block.splitlines()
                if line.strip().startswith("deploy-vii")
            ]
    return found


class Parsed(Exception):
    """Raised by the patched `parse_args` so `main` stops before it executes anything."""

    def __init__(self, namespace: argparse.Namespace) -> None:
        self.namespace = namespace


def parse_with_real_parser(
    line: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> argparse.Namespace:
    from deploy_vii.__main__ import main

    original = argparse.ArgumentParser.parse_args

    def stop(self: argparse.ArgumentParser, args: Sequence[str] | None = None) -> NoReturn:
        raise Parsed(original(self, args))

    argv = shlex.split(PLACEHOLDER.sub("dummy", line))
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", stop)
    try:
        main()
    except Parsed as parsed:
        return parsed.namespace
    except SystemExit:
        pytest.fail(f"real parser rejected: {line}\n{capsys.readouterr().err}")
    pytest.fail(f"main() returned without parsing: {line}")


def test_frontmatter() -> None:
    fields = frontmatter((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
    assert fields["name"] == SKILL_DIR.name == "deploy-vii"
    assert NAME.fullmatch(fields["name"])
    assert fields.get("description")


def test_no_shell_preapproval() -> None:
    fields = frontmatter((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
    tools = re.split(r"[\s,\[\]]+", fields.get("allowed-tools", "").lower())
    assert "shell" not in tools and "bash" not in tools


def test_body_stays_short() -> None:
    assert len((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").splitlines()) <= 150
    assert len(list((SKILL_DIR / "references").glob("*"))) <= 3


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.name)
def test_referenced_paths_exist(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for reference in PATH_REFERENCE.findall(text):
        base = SKILL_DIR if reference.startswith("references/") else ROOT
        assert (base / reference).exists(), f"{path.name} names a missing path: {reference}"
    if path.name == "SKILL.md":
        # The three reference files the body points to are exactly the ones that exist.
        named = set(re.findall(r"references/([\w.-]+\.md)", text))
        assert named == {p.name for p in (SKILL_DIR / "references").glob("*.md")}


def test_commands_parse_with_the_real_parser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    found = commands()
    assert found, "the skill names no deploy-vii command"
    seen: set[str] = set()
    for _, line in found:
        namespace = parse_with_real_parser(line, monkeypatch, capsys)
        seen.add(
            ":".join(
                str(getattr(namespace, key))
                for key in ("command", "action", "live_command")
                if getattr(namespace, key, None) is not None
            )
        )
    # Every command of the documented flow is present, so none can be dropped silently.
    flow = {
        "plan",
        "prepare",
        "execution:create",
        "execution:begin",
        "execution:cp0-submit",
        "execution:cp1-submit",
        "execution:step-output",
        "execution:cp1-quality-inputs",
        "execution:cp1-promote",
        "execution:statement-preview",
        "execution:envelope",
        "execution:render",
        "execution:cp-model-publish",
        "execution:cp-model-verify",
        "execution:status",
        "execution:interrupt",
        "live:module",
    }
    assert flow <= seen, f"flow commands missing from the skill: {sorted(flow - seen)}"


def test_parser_check_rejects_a_bad_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(pytest.fail.Exception, match="real parser rejected"):
        parse_with_real_parser("deploy-vii execution --directory d begin", monkeypatch, capsys)
    with pytest.raises(pytest.fail.Exception, match="real parser rejected"):
        parse_with_real_parser(
            "deploy-vii execution --directory d status --no-such-flag", monkeypatch, capsys
        )
    with pytest.raises(pytest.fail.Exception, match="real parser rejected"):
        parse_with_real_parser(
            "deploy-vii execution --directory d cp1-submit --ticket t --step nope --review r",
            monkeypatch,
            capsys,
        )


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.name)
def test_no_secret_or_acceptance_claim(path: Path) -> None:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        assert not SECRET.search(line), f"{path.name}:{number} holds a credential-shaped string"
        assert not ACCEPTANCE_CLAIM.search(line), f"{path.name}:{number} claims host acceptance"


def test_gaps_are_labelled() -> None:
    body = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert body.count("**Gap:**") >= 5


TABLE_ONLY = [
    "deploy-vii cp0 --pack p --review r --output o",
    "deploy-vii preview --run r --output o",
    "deploy-vii execution --directory d replace-pack --pack p",
    "deploy-vii execution --directory d interface-preview --ticket t --output o",
    "deploy-vii execution --directory d register-preview --ticket t --output o",
    "deploy-vii live probe --directory d --cap 1",
    "deploy-vii live regression --directory d --cap 1",
    "deploy-vii live canary --directory d --cap 1",
    "deploy-vii live corpus attempt case-1",
    "deploy-vii live reconcile --directory d --batch-id b",
    "deploy-vii live schema-check --models vendor/model",
]


@pytest.mark.parametrize("line", TABLE_ONLY)
def test_table_only_commands_parse(
    line: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Commands that references/commands.md lists in its tables, not in fenced blocks."""
    parse_with_real_parser(line, monkeypatch, capsys)
