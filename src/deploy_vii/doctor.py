"""Offline checks for a usable Deploy VII installation."""

import json
import platform
import re
import sys
import tempfile
import tomllib
from importlib.metadata import metadata
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from deploy_vii.delivery_dir import delivery_root
from deploy_vii.inputs import KINDS
from deploy_vii.preparation import PreparationRequest


def checks(
    request: Path | None = None, inputs: tuple[Path, ...] = (), out: Path | None = None
) -> list[dict[str, str]]:
    root = Path(__file__).resolve().parents[2]
    project_file = root / "pyproject.toml"
    result: list[dict[str, str]] = []

    def add(name: str, ok: bool | None, fix: str, detail: str = "") -> None:
        result.append(
            {
                "name": name,
                "status": "skip" if ok is None else "ok" if ok else "FAIL",
                "fix": fix,
                **({"detail": detail} if detail else {}),
            }
        )

    if project_file.is_file():
        with project_file.open("rb") as stream:
            requirement = tomllib.load(stream)["project"]["requires-python"]
    else:
        requirement = metadata("deploy-vii").get("Requires-Python", "")
    major, minor = sys.version_info[:2]
    bounds = re.fullmatch(r">=(\d+)\.(\d+),<(?:(\d+)\.(\d+))", requirement)
    if not requirement:
        python_ok: bool | None = None
        python_fix = "Install from the project source to check its Python requirement."
    else:
        python_ok = (
            bounds is not None
            and (major, minor)
            >= (
                int(bounds[1]),
                int(bounds[2]),
            )
            and (major, minor) < (int(bounds[3]), int(bounds[4]))
        )
        python_fix = f"Use a Python version satisfying {requirement}."
    add("python", python_ok, python_fix, platform.python_version())
    add(
        "uv-lock-present",
        (root / "uv.lock").is_file() if project_file.is_file() else None,
        "This checks lock-file presence only; run `uv lock --check` to verify consistency."
        if project_file.is_file()
        else "Lock-file inspection is available from a source checkout.",
    )
    for name in ("openpyxl", "pydantic", "pypdf", "deploy_vii"):
        try:
            __import__(name)
            ok = True
        except ImportError:
            ok = False
        add(f"import-{name}", ok, f"Run `uv sync --locked` to install {name}.")
    try:
        from deploy_vii.registry import plan

        plan(("CP-0",))
        ok = True
    except (ImportError, ValueError):
        ok = False
    add("plan-cp0", ok, "Repair the installation and confirm `deploy-vii plan CP-0` works.")
    skill = root / ".github/skills/deploy-vii/SKILL.md"
    try:
        skill_ok: bool | None = (
            skill.is_file() and len(skill.read_text(encoding="utf-8").splitlines()) <= 150
            if project_file.is_file()
            else None
        )
    except OSError:
        skill_ok = False
    add(
        "skill",
        skill_ok,
        "Restore the packaged skill at .github/skills/deploy-vii/SKILL.md (maximum 150 lines)."
        if project_file.is_file()
        else "Install from a repository checkout to check the packaged skill location.",
    )
    add(
        "git-runtime",
        None,
        "Git is needed for some source installs, not to run the installed application.",
    )
    if request is None:
        add("request", None, "Pass --request to validate a preparation-request/1 file.")
    else:
        try:
            parsed = PreparationRequest.model_validate_json(request.read_bytes())
            missing = []
            for item in parsed.sources:
                try:
                    with Path(item.path).open("rb") as source:
                        source.read(1)
                except OSError:
                    missing.append(item.path)
            ok = not missing
            detail = "missing/unreadable: " + ", ".join(missing) if missing else ""
        except (OSError, ValueError):
            ok, detail = False, "request is unreadable or invalid"
        add(
            "request",
            ok,
            "Correct the JSON schema and ensure every named source exists and is readable.",
            detail,
        )
    for file in inputs:
        kind = "rv or portfolio"
        try:
            reports = [(kind, validator(file)) for kind, validator in KINDS.items()]
            valid = next(((kind, report) for kind, report in reports if report.ok), None)
            if valid is None:
                detail = "; ".join(line for _, report in reports for line in report.lines())
                ok = False
            else:
                kind, report = valid
                ok, detail = True, "; ".join(report.lines())
        except (
            OSError,
            ValueError,
            UnicodeError,
            BadZipFile,
            ParseError,
            KeyError,
            IndexError,
            TypeError,
            NotImplementedError,
        ):
            ok, detail = False, "input is unreadable or invalid"
        add(
            f"input-{file.name}",
            ok,
            f"Correct the {kind} input using `deploy-vii validate-input {kind} <file>`.",
            detail,
        )
    target = delivery_root(out)
    try:
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".deploy-vii-doctor-", dir=target):
            pass
        ok = True
    except OSError:
        ok = False
    add("delivery-root", ok, f"Choose a writable delivery root (currently {target}).", str(target))
    return result


def render(
    request: Path | None = None,
    inputs: tuple[Path, ...] = (),
    out: Path | None = None,
    as_json: bool = False,
) -> tuple[str, int]:
    items = checks(request, inputs, out)
    if as_json:
        output = json.dumps({"delivery_root": str(delivery_root(out)), "checks": items}, indent=2)
    else:
        output = "\n".join(
            f"{item['status']} {item['name']}: {item.get('detail', item['fix'])}" for item in items
        )
        output += f"\ndelivery root: {delivery_root(out)}"
    return output, int(any(item["status"] == "FAIL" for item in items))
