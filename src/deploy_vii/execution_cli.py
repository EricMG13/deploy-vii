"""Local execution commands; supplied reviews only, no provider invocation."""

import argparse
import json
from pathlib import Path

from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_workflow import (
    CP1_STEPS,
    cp1_register_preview,
    cp1_registers,
    cp1_statement_preview,
    promote_cp1,
    submit_cp1_step,
    write_cp1_envelope,
)
from deploy_vii.execution import Attempt, Execution
from deploy_vii.preparation import load_pack


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--directory", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("create", "replace-pack"):
        actions.add_parser(name).add_argument("--pack", type=Path, required=True)
    actions.add_parser("status")
    actions.add_parser("begin").add_argument("module")
    for name in ("statement-preview", "interface-preview", "register-preview"):
        preview = actions.add_parser(name)
        preview.add_argument("--ticket", required=True)
        preview.add_argument("--output", type=Path, required=True)
    envelope = actions.add_parser("envelope")
    envelope.add_argument("--module", required=True, choices=("CP-1",))
    envelope.add_argument("--output", type=Path, required=True)
    actions.add_parser("cp1-quality-inputs").add_argument("--ticket", required=True)
    for name in ("interrupt", "cp0-submit", "cp1-submit", "cp1-promote", "step-output"):
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


def attempt_json(store: Execution, attempt: Attempt) -> str:
    """The attempt record, with its settled module read from its blob for display."""
    shown = attempt.model_dump(mode="json")
    if attempt.result_sha256 is not None:
        shown["result"] = store.result(attempt.result_sha256).model_dump(mode="json")
    return json.dumps(shown)


def execute(args: argparse.Namespace) -> str:
    if args.action == "create":
        return Execution.create(args.directory, load_pack(args.pack)).read().model_dump_json()
    store = Execution(args.directory)
    if args.action == "replace-pack":
        store.replace_pack(load_pack(args.pack))
    elif args.action == "register-preview":
        return str(cp1_register_preview(store, args.ticket, args.output))
    elif args.action == "cp1-quality-inputs":
        return cp1_quality_inputs(cp1_registers(store, args.ticket)).model_dump_json()
    elif args.action == "cp1-promote":
        review = args.review.read_text(encoding="utf-8")
        return attempt_json(store, promote_cp1(store, args.ticket, review))
    elif args.action == "envelope":
        return str(write_cp1_envelope(store, args.output))
    elif args.action in {"statement-preview", "interface-preview"}:
        return str(
            cp1_statement_preview(
                store,
                args.ticket,
                args.output,
                include_interface=args.action == "interface-preview",
            )
        )
    elif args.action == "begin":
        return attempt_json(store, store.begin(args.module))
    elif args.action == "interrupt":
        return attempt_json(store, store.interrupt(args.ticket, args.reason))
    elif args.action == "cp0-submit":
        return attempt_json(
            store,
            submit_cp0_review(store, args.ticket, args.review.read_text(encoding="utf-8")),
        )
    elif args.action == "cp1-submit":
        return attempt_json(
            store,
            submit_cp1_step(store, args.ticket, args.step, args.review.read_text(encoding="utf-8")),
        )
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
        if step is None or step.status != "valid" or step.output_sha256 is None:
            raise ValueError("No valid retained output for this ticket and step")
        return store.step_output(step.output_sha256)
    return store.read().model_dump_json()
