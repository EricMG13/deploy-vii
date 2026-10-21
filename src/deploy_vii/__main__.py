import argparse
from pathlib import Path

from deploy_vii.contracts import Run
from deploy_vii.delivery import deliver_cp0
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
    args = parser.parse_args()
    if args.command == "plan":
        print("\n".join(plan(tuple(args.modules))))
    elif args.command == "preview":
        run = Run.model_validate_json(args.run.read_bytes())
        print(write_preview(run, args.output))
    elif args.command == "prepare":
        request = PreparationRequest.model_validate_json(args.request.read_bytes())
        print(prepare(request, args.root, args.output).content_hash())
    else:
        pack = load_pack(args.pack)
        review = ReadinessReview.model_validate_json(args.review.read_bytes())
        print(deliver_cp0(pack, review, args.output))


if __name__ == "__main__":
    main()
