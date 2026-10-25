"""Local execution commands; supplied reviews only, no provider invocation."""

import argparse
import json
import sys
from pathlib import Path
from typing import get_args

from deploy_vii.contracts import PathwayId
from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.cp1_quality import cp1_quality_inputs
from deploy_vii.cp1_render import render_cp1_envelope
from deploy_vii.cp1_workflow import (
    CP1_STEPS,
    cp1_register_preview,
    cp1_registers,
    cp1_statement_preview,
    promote_cp1,
    submit_cp1_step,
    write_cp1_envelope,
)
from deploy_vii.cp_model_workflow import (
    CpModelRefused,
    publish_cp_model,
    verify_cp_model_publication,
)
from deploy_vii.execution import Attempt, Execution
from deploy_vii.live.context import module_context
from deploy_vii.module_submits import MODULE_SUBMITS, submit_module_step
from deploy_vii.preparation import load_pack
from deploy_vii.registry import canonical, modules, step_chain


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
    render = actions.add_parser("render")
    render.add_argument("--envelope", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--pathway", choices=get_args(PathwayId))
    for name in ("cp-model-publish", "cp-model-verify"):
        actions.add_parser(name).add_argument("--output", type=Path, required=True)
    submit = actions.add_parser("module-submit")
    submit.add_argument("--module", required=True, choices=tuple(MODULE_SUBMITS))
    submit.add_argument("--step", required=True)
    submit.add_argument("--review", type=Path, required=True)
    context = actions.add_parser("module-context")
    context.add_argument("--module", required=True, choices=tuple(MODULE_SUBMITS))
    context.add_argument("--step", required=True)
    for name in (submit, context):
        name.add_argument("--ticket", required=True)
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


def refusal_exit(message: str) -> SystemExit:
    """A one-line refusal on stderr, exit code 2 (raise the result)."""
    print(message, file=sys.stderr)
    return SystemExit(2)


def issue_lines(attempt: Attempt) -> tuple[str, ...]:
    """The validator's issues an attempt is waiting on: its own once finished, else those of the
    step that was rejected and kept for its one repair (task 7.0g)."""
    if attempt.issues:
        return attempt.issues
    held = [step for step in (*attempt.steps, *attempt.step_repairs) if step.issues]
    return held[-1].issues if held and attempt.status == "pending" else ()


def module_submit(store: Execution, args: argparse.Namespace) -> str:
    """Submit the review file as the module's step: the attempt record on stdout, and when the
    validator rejected it each issue line on stderr and exit 1 (the host agent repairs on them)."""
    try:
        attempt = submit_module_step(
            store, args.module, args.ticket, args.step, args.review.read_text(encoding="utf-8")
        )
    except ValueError as refusal:
        raise refusal_exit(f"module-submit refused: {refusal}") from refusal
    issues = issue_lines(attempt)
    if issues:
        print(attempt_json(store, attempt))
        print("\n".join(issues), file=sys.stderr)
        raise SystemExit(1)
    return attempt_json(store, attempt)


def module_context_json(store: Execution, args: argparse.Namespace) -> str:
    """The CONTEXT entries the live runner sends for this step of the ticket, as it serialises
    them (`live.prompts`); `{}` with a note on stderr for a step that has none."""
    attempt = next((a for a in store.read().attempts if a.ticket_id == args.ticket), None)
    if attempt is None or attempt.module_id != args.module:
        raise refusal_exit(f"module-context refused: {args.ticket} is not a {args.module} ticket")
    if args.step not in step_chain(args.module).steps:
        steps = ", ".join(step_chain(args.module).steps)
        raise refusal_exit(
            f"module-context refused: {args.step} is not a step of {args.module}; {steps}"
        )
    try:
        entries = module_context(store, attempt, args.step)
    except ValueError as refusal:
        raise refusal_exit(f"module-context refused: {refusal}") from refusal
    if entries is None:
        print(f"no module context for step {args.step}", file=sys.stderr)
        entries = {}
    return json.dumps(entries, indent=1, sort_keys=True)


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
    elif args.action == "cp-model-publish":
        try:
            return attempt_json(store, publish_cp_model(store, output=args.output))
        except CpModelRefused as refused:
            print(f"cp-model-publish refused: {refused}", file=sys.stderr)
            raise SystemExit(2) from refused
    elif args.action == "cp-model-verify":
        issues = verify_cp_model_publication(store, args.output)
        if issues:
            print("cp-model-verify refused: " + "; ".join(issues), file=sys.stderr)
            raise SystemExit(2)
        return json.dumps({"verified": True, "issues": []})
    elif args.action == "envelope":
        return str(write_cp1_envelope(store, args.output))
    elif args.action == "render":
        receipt = render_cp1_envelope(store, args.envelope, args.output, pathway=args.pathway)
        return json.dumps(receipt)
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
        try:
            module_id = canonical(args.module)
        except ValueError as unknown:
            valid = ", ".join(item.module_id for item in modules())
            raise refusal_exit(
                f"begin refused: {args.module} is not a module; choose one of {valid}"
            ) from unknown
        return attempt_json(store, store.begin(module_id))
    elif args.action == "module-submit":
        return module_submit(store, args)
    elif args.action == "module-context":
        return module_context_json(store, args)
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
