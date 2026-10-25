"""Local execution commands; supplied reviews only, no provider invocation."""

import argparse
import json
import sys
from pathlib import Path

from deploy_vii.bindings.shipped import SHIPPED_MAPS
from deploy_vii.cp0_workflow import (
    InvalidReadinessAddendum,
    cp0_addendum_context,
    submit_cp0_addendum,
    submit_cp0_review,
)
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
from deploy_vii.live.prompts import readiness_addendum_instructions
from deploy_vii.module_submits import (
    MODULE_SUBMITS,
    host_context,
    step_instructions,
    submit_module_step,
)
from deploy_vii.preparation import load_pack
from deploy_vii.registry import STEP_CHAINS, canonical, modules, step_chain
from deploy_vii.render import render as render_view
from deploy_vii.report_view import build, call_state, pathways

PATHWAY_IDS = tuple(item.id for item in pathways())


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--directory", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("create", "replace-pack"):
        actions.add_parser(name).add_argument("--pack", type=Path, required=True)
    actions.add_parser("status")
    actions.add_parser("begin").add_argument("module")
    extension = actions.add_parser(
        "extend-scope", help="extend the requested modules to a superset (task 9.1)"
    )
    extension.add_argument("modules", nargs="+", help="the full new requested set, aliases allowed")
    extension.add_argument("--readiness-addendum", type=Path)
    extension.add_argument("--context-sha256")
    actions.add_parser("cp0-addendum-context").add_argument("modules", nargs="+")
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
    render.add_argument("--pathway", choices=PATHWAY_IDS)
    for name in ("cp-model-publish", "cp-model-verify"):
        actions.add_parser(name).add_argument("--output", type=Path, required=True)
    submit = actions.add_parser("module-submit")
    submit.add_argument("--module", required=True, choices=tuple(MODULE_SUBMITS))
    submit.add_argument("--step", required=True)
    submit.add_argument("--review", type=Path, required=True)
    context = actions.add_parser("module-context")
    context.add_argument("--module", required=True, choices=tuple(MODULE_SUBMITS))
    context.add_argument("--step", required=True)
    for module_action in (submit, context):
        module_action.add_argument("--ticket", required=True)
    instructions = actions.add_parser("step-instructions")
    instructions.add_argument(
        "--module", required=True, choices=tuple(chain.module_id for chain in STEP_CHAINS)
    )
    instructions.add_argument("--ticket", required=True)
    instructions.add_argument("--step", required=True)
    instructions.add_argument("--with-sources", action="store_true")
    report = actions.add_parser("report")
    report.add_argument("--pathway", required=True, choices=PATHWAY_IDS)
    report.add_argument("--output", type=Path, required=True)
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
    if attempt.status != "pending":
        return ()
    invalid = [step for step in attempt.steps if step.status == "invalid"]
    if invalid:
        return invalid[-1].issues
    valid = {step.step_id for step in attempt.steps if step.status == "valid"}
    waiting = [step for step in attempt.step_repairs if step.step_id not in valid]
    return waiting[-1].issues if waiting else ()


def settled_json(store: Execution, attempt: Attempt) -> str:
    """The attempt record on stdout. When the validator rejected the review (or kept the step's
    first try for its one repair) each issue line goes to stderr and the exit is 1, so the host
    agent branches on the exit code; 0 only for an accepted review."""
    shown = attempt_json(store, attempt)
    issues = issue_lines(attempt)
    if issues:
        print(shown)
        print("\n".join(issues), file=sys.stderr)
        raise SystemExit(1)
    return shown


def review_text(args: argparse.Namespace) -> str:
    """The `--review` file's text; a missing file is a one-line refusal, exit 2."""
    path: Path = args.readiness_addendum if args.action == "extend-scope" else args.review
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as missing:
        raise refusal_exit(f"{args.action} refused: no review file at {path}") from missing


def module_submit(store: Execution, args: argparse.Namespace) -> str:
    """Submit the review file as the module's step (`settled_json`: exit 1 on a rejection)."""
    review = review_text(args)
    try:
        attempt = submit_module_step(store, args.module, args.ticket, args.step, review)
    except ValueError as refusal:
        raise refusal_exit(f"module-submit refused: {refusal}") from refusal
    return settled_json(store, attempt)


def module_context_json(store: Execution, args: argparse.Namespace) -> str:
    """The CONTEXT entries the live runner sends for this step of the ticket, as JSON with
    indent 1 and sorted keys (how the pack CONTEXT block carries them; `step-instructions` prints
    the exact bytes, CP-5's scope included, which the runner sends as compact JSON)."""
    attempt = next((a for a in store.read().attempts if a.ticket_id == args.ticket), None)
    if attempt is None or attempt.module_id != args.module:
        raise refusal_exit(f"module-context refused: {args.ticket} is not a {args.module} ticket")
    if args.step not in step_chain(args.module).steps:
        steps = ", ".join(step_chain(args.module).steps)
        raise refusal_exit(
            f"module-context refused: {args.step} is not a step of {args.module}; {steps}"
        )
    try:
        entries = host_context(store, attempt, args.step)
    except ValueError as refusal:
        raise refusal_exit(f"module-context refused: {refusal}") from refusal
    return json.dumps(entries, indent=1, sort_keys=True)


def instructions_text(store: Execution, args: argparse.Namespace) -> str:
    """The step's prompt as the live runner composes it (`module_submits.step_instructions`)."""
    try:
        return step_instructions(
            store, args.module, args.ticket, args.step, with_sources=args.with_sources
        ).removesuffix("\n")
    except ValueError as refusal:
        raise refusal_exit(f"step-instructions refused: {refusal}") from refusal


def write_report(store: Execution, pathway_id: str, output: Path) -> str:
    """Render the journal's accepted heads as the run's Pathway into `output`: `index.html` and
    the `report.json` receipt (modules by status, the call band's state). A module that has not
    run or is blocked renders in its own state, never as an error."""
    view = store.view()
    if pathway_id != view.run.pathway:
        raise refusal_exit(
            f"report refused: the run's Pathway is {view.run.pathway}; "
            f"its scope is immutable, not {pathway_id}"
        )
    pathway = next(item for item in pathways() if item.id == pathway_id)
    report = build(view, pathway, SHIPPED_MAPS)
    html = render_view(view, report)
    state, words = call_state(report)
    receipt = {
        "schema_version": "report/1",
        "pathway": pathway_id,
        "modules": [
            {"module_id": m.module_id, "status": m.status, "artifact_sha256": m.artifact_sha256}
            for m in view.modules
        ],
        "call_state": {
            "state": state,
            "words": None if words is None else {"glyph": words[0], "word": words[1]},
        },
    }
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exists:
        raise refusal_exit(f"report refused: {output} already exists") from exists
    (output / "index.html").write_text(html, encoding="utf-8")
    (output / "report.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return json.dumps(receipt)


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
        return settled_json(store, promote_cp1(store, args.ticket, review_text(args)))
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
        try:
            return attempt_json(store, store.begin(module_id))
        except ValueError as refusal:
            raise refusal_exit(f"begin refused: {refusal}") from refusal
    elif args.action == "report":
        return write_report(store, args.pathway, args.output)
    elif args.action == "module-submit":
        return module_submit(store, args)
    elif args.action == "step-instructions":
        return instructions_text(store, args)
    elif args.action == "module-context":
        return module_context_json(store, args)
    elif args.action == "extend-scope":
        try:
            if bool(args.readiness_addendum) != bool(args.context_sha256):
                raise ValueError("Supply --readiness-addendum and --context-sha256 together")
            if args.readiness_addendum:
                return submit_cp0_addendum(
                    store,
                    tuple(args.modules),
                    review_text(args),
                    context_sha256=args.context_sha256,
                ).model_dump_json()
            return store.extend_scope(tuple(args.modules)).model_dump_json()
        except InvalidReadinessAddendum as rejected:
            print(json.dumps({"issues": rejected.issues}))
            print("\n".join(rejected.issues), file=sys.stderr)
            raise SystemExit(1) from rejected
        except ValueError as refused:  # one line on stderr, exit 2; the journal is unchanged
            print(f"extend-scope refused: {refused}", file=sys.stderr)
            raise SystemExit(2) from refused
    elif args.action == "cp0-addendum-context":
        try:
            context = cp0_addendum_context(store, tuple(args.modules))
            return json.dumps(readiness_addendum_instructions(store.pack(), context))
        except ValueError as refused:
            raise refusal_exit(f"cp0-addendum-context refused: {refused}") from refused
    elif args.action == "interrupt":
        return attempt_json(store, store.interrupt(args.ticket, args.reason))
    elif args.action == "cp0-submit":
        return settled_json(store, submit_cp0_review(store, args.ticket, review_text(args)))
    elif args.action == "cp1-submit":
        return settled_json(
            store, submit_cp1_step(store, args.ticket, args.step, review_text(args))
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
