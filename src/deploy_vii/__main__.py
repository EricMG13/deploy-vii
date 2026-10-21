import argparse
from pathlib import Path

from deploy_vii.contracts import Run
from deploy_vii.registry import plan
from deploy_vii.render import write_preview


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy VII evidence workbench")
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview", help="render an unrun offline report shell")
    preview.add_argument("--run", type=Path, required=True)
    preview.add_argument("--output", type=Path, required=True)
    planning = commands.add_parser("plan")
    planning.add_argument("modules", nargs="+")
    args = parser.parse_args()
    if args.command == "plan":
        print("\n".join(plan(tuple(args.modules))))
    else:
        run = Run.model_validate_json(args.run.read_bytes())
        print(write_preview(run, args.output))


if __name__ == "__main__":
    main()
