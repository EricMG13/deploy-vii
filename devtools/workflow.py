"""Run with uv run python -m devtools.workflow; all output is observational."""

import argparse
import json
import subprocess
from pathlib import Path

from devtools.state import checkpoint, validate
from devtools.storage import Object, read_object
from devtools.telemetry import import_events, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--store", type=Path, default=Path("artifacts/context-policy/workflow"))
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "checkpoint", "handoff", "validate"):
        command = commands.add_parser(name)
        command.add_argument(
            "--context",
            type=Path,
            required=True,
            help="complete current task context JSON; see example",
        )
        if name == "validate":
            command.add_argument("--record", type=Path)
    command = commands.add_parser("import-events")
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--host", choices=("codex", "claude"), required=True)
    command.add_argument("--session", required=True)
    commands.add_parser("report")
    args = parser.parse_args()
    repo = args.repo.resolve()
    store = args.store if args.store.is_absolute() else repo / args.store
    try:
        result: Object
        if args.command in {"init", "checkpoint", "handoff"}:
            path = checkpoint(repo, store, read_object(args.context), kind=args.command)
            result = {
                "record": str(path),
                "ownership_verified": False,
                "transfer_status": "NOT_READY",
            }
        elif args.command == "validate":
            result = validate(
                repo, read_object(args.record or store / "current.json"), read_object(args.context)
            )
        elif args.command == "import-events":
            result = import_events(repo, store / "telemetry", args.source, args.host, args.session)
        else:
            result = report(store / "telemetry")
        print(json.dumps(result, indent=2, sort_keys=True))
        return (
            1
            if result.get("findings") or result.get("invalid_lines") or result.get("conflicts")
            else 0
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        # Do not print input JSON, raw evidence, shell stderr or credentials.
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "message": "operation failed; verify inputs and repository",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
