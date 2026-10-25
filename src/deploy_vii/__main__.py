import argparse
import sys
from pathlib import Path

from deploy_vii.contracts import Run
from deploy_vii.delivery import deliver_cp0
from deploy_vii.delivery_dir import run_paths
from deploy_vii.doctor import render as render_doctor
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
    parser.add_argument("--out", type=Path, help="delivery root (or DEPLOY_VII_OUT)")
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview", help="render an unrun offline report shell")
    preview.add_argument("--run", type=Path, required=True)
    preview.add_argument("--output", type=Path, required=True)
    planning = commands.add_parser("plan")
    planning.add_argument("modules", nargs="+")
    preparation = commands.add_parser("prepare", help="freeze named PDF/text/XLSX sources")
    preparation.add_argument("--request", type=Path, required=True)
    preparation.add_argument("--root", type=Path, required=True)
    preparation.add_argument("--output", type=Path)
    preparation.add_argument("--run", help="derive the pack path under the delivery root")
    readiness = commands.add_parser("cp0", help="validate a supplied CP-0 source-readiness review")
    readiness.add_argument("--pack", type=Path, required=True)
    readiness.add_argument("--review", type=Path, required=True)
    readiness.add_argument("--output", type=Path, required=True)
    configure(commands.add_parser("execution", help="retain and resume staged reviews locally"))
    run_parser = commands.add_parser("run", help="advance an offline host-review run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--root", type=Path, required=True)
    run_parser.add_argument("--run", required=True)
    run_parser.add_argument("--modules", nargs="+")
    run_parser.add_argument("--reviews", type=Path)
    configure_live(commands.add_parser("live", help="capped OpenRouter model tests"))
    checking = commands.add_parser("validate-input", help="check a user-supplied input file")
    checking.add_argument("kind", choices=tuple(KINDS))
    checking.add_argument("file", type=Path)
    checking.add_argument("--json", action="store_true", help="print the report as JSON")
    doctor = commands.add_parser("doctor", help="check this offline installation")
    doctor.add_argument("--request", type=Path)
    doctor.add_argument("--inputs", type=Path, nargs="*")
    doctor.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "plan":
        print("\n".join(plan(tuple(args.modules))))
    elif args.command == "preview":
        run = Run.model_validate_json(args.run.read_bytes())
        print(write_preview(run, args.output))
    elif args.command == "prepare":
        try:
            derived = run_paths(args.out, args.run)["pack"] if args.run else None
        except ValueError as error:
            parser.error(str(error))
        output = args.output or derived
        if output is None:
            parser.error("prepare requires --output or --run")
        if args.run and args.output is None:
            output.parent.mkdir(parents=True, exist_ok=True)
        request = PreparationRequest.model_validate_json(args.request.read_bytes())
        print(prepare(request, args.root, output).content_hash())
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
    elif args.command == "doctor":
        output, code = render_doctor(args.request, tuple(args.inputs or ()), args.out, args.json)
        print(output)
        sys.exit(code)
    elif args.command == "run":
        from deploy_vii.execution_cli import run_offline

        try:
            print(run_offline(args))
        except SystemExit as error:
            raise error
    else:
        print(execute(args))


if __name__ == "__main__":
    main()
