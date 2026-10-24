import argparse
import sys
from pathlib import Path

from deploy_vii.contracts import Run
from deploy_vii.delivery import deliver_cp0
from deploy_vii.execution_cli import configure, execute
from deploy_vii.inputs import KINDS
from deploy_vii.live.cli import configure as configure_live
from deploy_vii.live.cli import execute as execute_live
from deploy_vii.preparation import PreparationRequest, load_pack, prepare
from deploy_vii.readiness import ReadinessReview
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
    preparation = commands.add_parser("prepare", help="freeze named PDF/text/XLSX sources")
    preparation.add_argument("--request", type=Path, required=True)
    preparation.add_argument("--root", type=Path, required=True)
    preparation.add_argument("--output", type=Path, required=True)
    readiness = commands.add_parser("cp0", help="validate a supplied CP-0 source-readiness review")
    readiness.add_argument("--pack", type=Path, required=True)
    readiness.add_argument("--review", type=Path, required=True)
    readiness.add_argument("--output", type=Path, required=True)
    configure(commands.add_parser("execution", help="retain and resume staged reviews locally"))
    configure_live(commands.add_parser("live", help="capped OpenRouter model tests"))
    checking = commands.add_parser("validate-input", help="check a user-supplied input file")
    checking.add_argument("kind", choices=tuple(KINDS))
    checking.add_argument("file", type=Path)
    checking.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()
    if args.command == "plan":
        print("\n".join(plan(tuple(args.modules))))
    elif args.command == "preview":
        run = Run.model_validate_json(args.run.read_bytes())
        print(write_preview(run, args.output))
    elif args.command == "prepare":
        request = PreparationRequest.model_validate_json(args.request.read_bytes())
        print(prepare(request, args.root, args.output).content_hash())
    elif args.command == "cp0":
        pack = load_pack(args.pack)
        review = ReadinessReview.model_validate_json(args.review.read_bytes())
        print(deliver_cp0(pack, review, args.output))
    elif args.command == "live":
        sys.exit(execute_live(args))
    elif args.command == "validate-input":
        report = KINDS[args.kind](args.file)
        print(report.model_dump_json(indent=2) if args.json else "\n".join(report.lines()))
        sys.exit(0 if report.ok else 1)
    else:
        print(execute(args))


if __name__ == "__main__":
    main()
