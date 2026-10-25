"""Local execution commands; supplied reviews only, no provider invocation."""

import argparse
import json
import sys
import webbrowser
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
from deploy_vii.delivery_dir import run_paths
from deploy_vii.execution import Attempt, Execution
from deploy_vii.live.prompts import readiness_addendum_instructions
from deploy_vii.module_submits import (
    MODULE_SUBMITS,
    host_context,
    step_instructions,
    submit_module_step,
)
from deploy_vii.preparation import PreparationRequest, load_pack, prepare
from deploy_vii.registry import STEP_CHAINS, canonical, modules, plan, step_chain
from deploy_vii.render import render as render_view
from deploy_vii.report_view import build, call_state, pathways

PATHWAY_IDS = tuple(item.id for item in pathways())


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--run", help="derive run paths under --out / DEPLOY_VII_OUT")
    actions = parser.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create")
    create.add_argument("--pack", type=Path)
    create.add_argument("--run", dest="create_run", help="derive pack and journal paths")
    actions.add_parser("replace-pack").add_argument("--pack", type=Path, required=True)
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
    render.add_argument("--output", type=Path)
    render.add_argument("--pathway", choices=PATHWAY_IDS)
    render.add_argument("--run", dest="render_run", help="derive the report directory")
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
    resume = actions.add_parser("resume", help="show or resubmit the pending host review")
    resume.add_argument("--ticket")
    resume.add_argument("--review", type=Path)
    report = actions.add_parser("report")
    report.add_argument("--pathway", required=True, choices=PATHWAY_IDS)
    report.add_argument("--output", type=Path)
    report.add_argument("--run", dest="report_run", help="derive the report directory")
    report_open = actions.add_parser("report-open")
    report_open.add_argument("--pathway", choices=PATHWAY_IDS)
    report_open.add_argument("--browser", action="store_true")
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


def read_review_file(path: Path, action: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise refusal_exit(f"{action} refused: cannot read review file at {path}") from error


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
    """The `--review` text; a missing or unreadable file is a one-line refusal, exit 2."""
    path: Path = args.readiness_addendum if args.action == "extend-scope" else args.review
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise refusal_exit(f"{args.action} refused: cannot read review file at {path}") from error


def read_request(path: Path) -> PreparationRequest:
    try:
        return PreparationRequest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise refusal_exit(f"run refused: request is unreadable or invalid at {path}") from error


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


def report_files(store: Execution, pathway_id: str) -> dict[str, str]:
    """Re-derive the complete report bytes from the current verified journal."""
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
    return {"index.html": html, "report.json": json.dumps(receipt, indent=2)}


def write_report(store: Execution, pathway_id: str, output: Path) -> str:
    """Write a new report directory; preserve the explicit command's no-overwrite contract."""
    files = report_files(store, pathway_id)
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exists:
        raise refusal_exit(f"report refused: {output} already exists") from exists
    for name, text in files.items():
        (output / name).write_text(text, encoding="utf-8")
    return json.dumps(json.loads(files["report.json"]))


def report_index(store: Execution, pathway_id: str, output: Path) -> str:
    """Reuse only a complete current report, refusing partial or unrelated private artifacts."""
    if output.is_symlink():
        raise refusal_exit("report refused: report paths must not be symlinks")
    if not output.exists():
        write_report(store, pathway_id, output)
    else:
        for name, expected in report_files(store, pathway_id).items():
            path = output / name
            if path.is_symlink():
                raise refusal_exit("report refused: report paths must not be symlinks")
            try:
                found = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise refusal_exit(
                    f"report refused: incomplete or unreadable report at {path}"
                ) from error
            if found != expected:
                raise refusal_exit(
                    f"report refused: existing report differs from the journal: {path}"
                )
    return str((output / "index.html").resolve())


def run_offline(args: argparse.Namespace) -> str:
    """Advance exactly one host review at a time; all model judgments remain supplied files."""
    try:
        paths = run_paths(getattr(args, "out", None), args.run)
    except ValueError as error:
        raise refusal_exit(f"run refused: {error}") from error
    pack_path = paths["pack"]
    journal = paths["journal"]
    journal.parent.mkdir(parents=True, exist_ok=True)
    reviews = args.reviews or paths["reviews"]
    request = read_request(args.request)
    requested = tuple(args.modules or request.run.requested_modules)
    if args.modules:
        request = request.model_copy(
            update={"run": request.run.model_copy(update={"requested_modules": requested})}
        )
    if not pack_path.exists():
        prepare(request, args.root, pack_path)
    pack = load_pack(pack_path)
    if tuple(pack.run.requested_modules) != requested:
        raise refusal_exit(
            "run refused: existing pack has a different requested module plan; choose a new run id"
        )
    if not journal.exists():
        store = Execution.create(journal, pack)
    else:
        store = Execution(journal)
        bound_pack = store.pack()
        if bound_pack != pack or bound_pack.content_hash() != pack.content_hash():
            raise refusal_exit(
                "run refused: existing journal is bound to a different prepared pack"
            )
    modules_to_run = ("CP-0", *plan(store.read().run.requested_modules))
    if reviews.is_symlink():
        raise refusal_exit(f"run refused: review directory must not be a symlink: {reviews}")
    snapshot = store.read()
    if any(head.module_id == "CP-MODEL" for head in snapshot.heads):
        output = journal.parent / "cp-model"
        if output.is_symlink() or any(
            (output / name).is_symlink()
            for name in ("model.html", "calculation.json", "receipt.json")
        ):
            raise refusal_exit("run refused: CP-MODEL output must not contain symlinks")
        issues = verify_cp_model_publication(store, output)
        if issues:
            raise refusal_exit("run refused: " + "; ".join(issues))
    while True:
        snapshot = store.read()
        pending = next((item for item in snapshot.attempts if item.status == "pending"), None)
        if pending is None:
            settled = {item.module_id for item in snapshot.heads if item.status != "stale"}
            module_id = next((item for item in modules_to_run if item not in settled), None)
            if module_id is None:
                report = paths["report"]
                return report_index(store, snapshot.run.pathway, report)
        else:
            module_id = pending.module_id
        if module_id == "CP-MODEL":
            # The deterministic publisher owns begin and settlement, with its own receipt.
            output = paths["journal"].parent / "cp-model"
            if output.is_symlink():
                raise refusal_exit("run refused: CP-MODEL output must not be a symlink")
            try:
                publish_cp_model(store, output=output)
            except CpModelRefused as error:
                raise refusal_exit(f"run refused: {error}") from error
            continue
        if pending is None:
            pending = store.begin(module_id)
        chain = step_chain(pending.module_id).steps
        valid = {item.step_id for item in pending.steps if item.status == "valid"}
        step = next((item for item in chain if item not in valid), chain[-1])
        retained = next((item for item in pending.steps if item.step_id == step), None)
        if retained is None and pending.payload_sha256 is None:
            instructions = step_instructions(
                store, pending.module_id, pending.ticket_id, step, with_sources=False
            )
            try:
                reviews.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise refusal_exit(
                    f"run refused: cannot create review directory {reviews}"
                ) from error
            revision = (
                f".{pending.ticket_id}.{len(pending.step_repairs)}"
                if pending.ticket_id
                != next(
                    (a.ticket_id for a in snapshot.attempts if a.module_id == pending.module_id),
                    pending.ticket_id,
                )
                or any(item.step_id == step for item in pending.step_repairs)
                else ""
            )
            instruction_path = reviews / f"{pending.module_id}-{step}{revision}.instructions.txt"
            if instruction_path.is_symlink():
                raise refusal_exit(
                    f"run refused: instructions path must not be a symlink: {instruction_path}"
                )
            try:
                with instruction_path.open("x", encoding="utf-8") as stream:
                    stream.write(instructions)
            except FileExistsError:
                try:
                    existing_instructions = instruction_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as error:
                    raise refusal_exit(
                        f"run refused: cannot read existing instructions at {instruction_path}"
                    ) from error
                if existing_instructions != instructions:
                    raise refusal_exit(
                        f"run refused: conflicting instructions file at {instruction_path}"
                    ) from None
            except OSError as error:
                raise refusal_exit(
                    f"run refused: cannot write instructions at {instruction_path}"
                ) from error
        review_path = reviews / f"{pending.module_id}-{step}.review.json"
        if review_path.is_symlink():
            raise refusal_exit(f"run refused: review path must not be a symlink: {review_path}")
        if not review_path.is_file():
            print(f"write {review_path} then rerun", file=sys.stderr)
            raise SystemExit(3)
        payload = read_review_file(review_path, "run")
        try:
            if pending.module_id == "CP-0":
                attempt = submit_cp0_review(store, pending.ticket_id, payload)
            elif pending.module_id == "CP-1" and step == "quality":
                attempt = promote_cp1(store, pending.ticket_id, payload)
            elif pending.module_id == "CP-1":
                attempt = submit_cp1_step(store, pending.ticket_id, step, payload)
            else:
                attempt = submit_module_step(
                    store, pending.module_id, pending.ticket_id, step, payload
                )
        except ValueError as error:
            raise refusal_exit(f"run refused: {error}") from error
        settled_json(store, attempt)


def execute(args: argparse.Namespace) -> str:
    run_id = (
        args.run
        or getattr(args, "create_run", None)
        or getattr(args, "report_run", None)
        or getattr(args, "render_run", None)
    )
    if args.directory is None and not run_id:
        raise SystemExit("execution requires --directory or --run")
    if run_id:
        try:
            paths = run_paths(getattr(args, "out", None), run_id)
        except ValueError as error:
            raise refusal_exit(f"execution refused: {error}") from error
        args.directory = args.directory or paths["journal"]
    else:
        paths = {}
    if args.action == "create":
        pack = args.pack or paths.get("pack")
        if pack is None:
            raise SystemExit("execution create requires --pack or --run")
        if run_id:
            args.directory.parent.mkdir(parents=True, exist_ok=True)
        return Execution.create(args.directory, load_pack(pack)).read().model_dump_json()
    store = Execution(args.directory)
    if args.action == "resume":
        snapshot = store.read()
        pending = next((item for item in snapshot.attempts if item.status == "pending"), None)
        if pending is None:
            remaining = [
                m
                for m in plan(snapshot.run.requested_modules)
                if m not in {h.module_id for h in snapshot.heads if h.status != "stale"}
            ]
            return "nothing to resume" + (
                f"; next runnable module: {remaining[0]}"
                if remaining
                else "; no runnable modules remain"
            )
        if pending.module_id == "CP-MODEL":
            if args.ticket or args.review:
                raise refusal_exit(
                    "resume refused: CP-MODEL takes no review; rerun run or cp-model-publish"
                )
            return (
                f"ticket {pending.ticket_id}; module CP-MODEL; deterministic publication pending; "
                "rerun run or cp-model-publish with its output directory"
            )
        chain = step_chain(pending.module_id).steps
        completed = {step.step_id for step in pending.steps if step.status == "valid"}
        current = next((step for step in chain if step not in completed), chain[-1])
        retained = next((step for step in pending.steps if step.step_id == current), None)
        retained_status = "yes" if retained else "no"
        message = (
            f"ticket {pending.ticket_id}; module {pending.module_id}; next step {current}; "
            f"retained response: {retained_status}; resubmit {current} with the same bytes "
            "if retained"
        )
        if not args.review and not args.ticket:
            return message
        if args.ticket != pending.ticket_id or args.review is None:
            raise refusal_exit("resume requires the pending --ticket and --review together")
        if args.review.is_symlink():
            raise refusal_exit(f"resume refused: review path must not be a symlink: {args.review}")
        args.module, args.step, args.action = pending.module_id, current, ""
        submitted = read_review_file(args.review, "resume")
        if pending.module_id == "CP-0":
            attempt = submit_cp0_review(store, pending.ticket_id, submitted)
        elif pending.module_id == "CP-1" and current == "quality":
            attempt = promote_cp1(store, pending.ticket_id, submitted)
        elif pending.module_id == "CP-1":
            attempt = submit_cp1_step(store, pending.ticket_id, current, submitted)
        else:
            attempt = submit_module_step(
                store, pending.module_id, pending.ticket_id, current, submitted
            )
        return settled_json(store, attempt)
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
        output = args.output or (paths["report"] if (args.render_run or args.run) else None)
        if output is None:
            raise SystemExit("render requires --output or --run")
        receipt = render_cp1_envelope(store, args.envelope, output, pathway=args.pathway)
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
        output = args.output or (paths["report"] if (args.report_run or args.run) else None)
        if output is None:
            raise SystemExit("report requires --output or --run")
        return write_report(store, args.pathway, output)
    elif args.action == "report-open":
        output = paths.get("report", args.directory.parent / "report")
        absolute = Path(report_index(store, args.pathway or store.read().run.pathway, output))
        if args.browser:
            webbrowser.open(absolute.as_uri())
        return str(absolute)
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
