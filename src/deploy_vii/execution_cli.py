"""Local execution commands; supplied reviews only, no provider invocation."""

import argparse
from pathlib import Path

from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.cp1_workflow import CP1_STEPS, cp1_statement_preview, submit_cp1_step
from deploy_vii.execution import Execution
from deploy_vii.preparation import load_pack


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--directory", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("create", "replace-pack"):
        actions.add_parser(name).add_argument("--pack", type=Path, required=True)
    actions.add_parser("status")
    actions.add_parser("begin").add_argument("module")
    preview = actions.add_parser("statement-preview")
    preview.add_argument("--ticket", required=True)
    preview.add_argument("--output", type=Path, required=True)
    for name in ("interrupt", "cp0-submit", "cp1-submit", "step-output"):
        action = actions.add_parser(name)
        action.add_argument("--ticket", required=True)
        if name == "interrupt":
            action.add_argument("--reason", required=True)
        elif name != "step-output":
            action.add_argument("--review", type=Path, required=True)
        if name in {"cp1-submit", "step-output"}:
            action.add_argument(
                "--step", required=True, choices=CP1_STEPS if name == "cp1-submit" else None
            )


def execute(args: argparse.Namespace) -> str:
    if args.action == "create":
        return Execution.create(args.directory, load_pack(args.pack)).read().model_dump_json()
    store = Execution(args.directory)
    if args.action == "replace-pack":
        store.replace_pack(load_pack(args.pack))
    elif args.action == "statement-preview":
        return str(cp1_statement_preview(store, args.ticket, args.output))
    elif args.action == "begin":
        return store.begin(args.module).model_dump_json()
    elif args.action == "interrupt":
        return store.interrupt(args.ticket, args.reason).model_dump_json()
    elif args.action == "cp0-submit":
        return submit_cp0_review(
            store, args.ticket, args.review.read_text(encoding="utf-8")
        ).model_dump_json()
    elif args.action == "cp1-submit":
        return submit_cp1_step(
            store, args.ticket, args.step, args.review.read_text(encoding="utf-8")
        ).model_dump_json()
    elif args.action == "step-output":
        step = next(
            (
                s
                for a in store.read().attempts
                if a.ticket_id == args.ticket
                for s in a.steps
                if s.step_id == args.step
            ),
            None,
        )
        if step is None or step.status != "valid" or step.output is None:
            raise ValueError("No valid retained output for this ticket and step")
        return step.output
    return store.read().model_dump_json()
