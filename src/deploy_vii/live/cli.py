"""`deploy-vii live`: capped, seeded batches over the runner. The key is never an option.

Every live subcommand requires `--cap`, which is bound to the batch ledger on first open and
can never be raised afterwards (the ledger refuses a different cap). The OpenRouter key is read
by the runner at dispatch from the DC-7 file named in settings; this module never sees it.
Each cell runs on its own journal copy so draws and repairs never share input sets. Reports hold
a summary table only: no response bodies, prompts, source text or validator wording.
"""

import argparse
import hashlib
import json
import math
import random
import re
import secrets
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import partial
from itertools import groupby
from pathlib import Path
from typing import Any

from deploy_vii.execution import Attempt, Execution, NotAuthorized
from deploy_vii.live.catalog import (
    USER_SELECTED,
    Catalog,
    CatalogError,
    ModelSelection,
    PinnedCandidate,
    PinnedPool,
    parse_selection,
    utc_stamp,
)
from deploy_vii.live.client import (
    DEFAULT_TIMEOUT_SECONDS,
    ChatClient,
    Request,
    Response,
    TransportError,
    urllib_transport,
)
from deploy_vii.live.cohort import ProxyResult, credit_state
from deploy_vii.live.context import step_sources
from deploy_vii.live.corpus import CORPUS_ROOT, REPOSITORY_ROOT, CorpusError, write_entry
from deploy_vii.live.credential import CredentialError
from deploy_vii.live.credit import CreditExhausted
from deploy_vii.live.draw import NoEligibleModel, draw
from deploy_vii.live.ledger import AttemptRecord, CapExceeded, Ledger, LedgerError
from deploy_vii.live.prompts import schema_text
from deploy_vii.live.reconcile import (
    Outcome,
    RetainedAttempt,
    batch_attempts,
    candidates,
    lookup_order,
    read_usage,
    reconcile_attempt,
    usage_path,
)
from deploy_vii.live.retention import AttemptWriter
from deploy_vii.live.runner import (
    COHORT,
    DEFAULT_MAX_TOKENS,
    SCHEMA_CHECK_MAX_TOKENS,
    STEPS,
    DispatchResult,
    SchemaCheck,
    StepSpec,
    check_schema,
    dispatch,
    expected_step,
    schema_rejections,
)
from deploy_vii.live.schema import (
    BISECT_VARIANTS,
    NULLABLE_ARRAY_REQUIRED,
    OPEN_OBJECT,
    VariantRefused,
    bisect_variant,
    nullable_array_fields,
    open_objects,
    schema_keywords,
    schema_relaxations,
    schema_shape,
    strict_schema,
)
from deploy_vii.live.settings import DEFAULT_SETTINGS, LiveSettings, SettingsError, load_settings
from deploy_vii.registry import canonical, modules

REPORT_DIRECTORY = Path("docs/development/tasks/implementation")
TRUNCATED = "truncated"  # a response classification: the completion was cut at the budget
CP0_STEPS = ("source_readiness",)
# Task 7.4: the four stages, then the QA review whose acceptance is the CP-1 promotion. A
# rejected review finishes the attempt (it settles the module), so `_run_cell` begins the
# module repair, which restarts at source_context.
CP1_CHAIN = ("source_context", "financials", "narrative", "readiness", "quality")
FULL_CHAIN = CP0_STEPS + CP1_CHAIN
# Fix round 1 (coordinator ruling): `cp1_workflow._quality_stage`'s Blocked verdict. A Blocked QA
# outcome is analytical, not a defect to repair: the cell ends at it, as at a truncation.
QA_BLOCKED = re.compile(
    r"CP-1 QA Blocked: confidence [0-9]+ \([^()]*\); a Blocked handoff is not promoted"
)
# Task 7.2: CP-1A needs CP-0 only (methodology.json), so its module route is CP-0, then its one
# step; CP-1 is not run, so its CONTEXT offers no CP-1 fact and no figure may be referenced.
CP1A_CHAIN = (*CP0_STEPS, "business_context")
# Task 7.0h: the matched comparison's cases, in shuffle order (cp1a draws after the other two,
# so the cp0 and cp1 orders are those of the two-case plan).
REGRESSION_CASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cp0", CP0_STEPS),
    ("cp1", FULL_CHAIN),
    ("cp1a", CP1A_CHAIN),
)
PROBE_STEPS = ("source_readiness", "source_context", "financials")
SEED_SEARCH_LIMIT = 100_000
BATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
EXIT_FAILED, EXIT_CAP, EXIT_CREDIT = 2, 3, 4  # EXIT_CREDIT: OpenRouter credit exhausted (DC-8)
POOL_RULING = "coordinator ruling 22 October 2026"
HELD = "reservation held"
HELD_FOOTNOTE = (
    "reservation held: no measured cost was returned, so the whole reservation counts as spent "
    "until `deploy-vii live reconcile` records the provider's charge for that generation."
)
# A step CP-0 did not authorize (its T8 command is not `Run <id>`): nothing sent, nothing spent.
NOT_AUTHORIZED = "not-authorized"
# The runner's status for an attempt that returned no model payload (timeout, an HTTP error or
# an error inside a 200, a deadline hold): never a validator verdict, so no issue count.
NO_RESPONSE = "no-response"
NOT_AUTHORIZED_SCHEMA = "live-step-not-authorized/1"
SCHEMA_CHECK_CAP = Decimal("0.05")  # a call costs about US$0.0005 (task 2.11)

Transport = Callable[[Request], Response]


class CliError(Exception):
    """A usage problem found before anything was spent."""


@dataclass(frozen=True)
class Cell:
    cell_id: str
    case_id: str
    steps: tuple[str, ...]
    seed: int


@dataclass(frozen=True)
class Row:
    cell_id: str
    case_id: str
    step_id: str
    model: str
    seed: int | None
    attempt_id: str
    status: str
    classification: str
    cost: str
    issue_count: int
    cohort: str = COHORT
    prompt_bound: int | None = None  # prompt tokens upper bound of the attempt (Pool table)
    repair: int = 0  # the journal's attempt number: 0 a first attempt, 1 the MC-7 repair
    step_try: int = 1  # 2 for the step's repair within its attempt (task 7.0g)

    def cells(self) -> tuple[object, ...]:
        return (
            self.cell_id,
            self.case_id,
            self.step_id,
            self.model,
            "-" if self.seed is None else self.seed,
            self.attempt_id,
            self.status,
            self.classification,
            self.cost,
            "-" if self.status == NO_RESPONSE else self.issue_count,
        )

    def step_cells(self) -> tuple[object, ...]:
        """A batch-report Steps row: `cells()` and the Repair column: `-` a first try of the
        first attempt, `step` the step's repair within its attempt, `1` the MC-7 repair attempt
        and `1+step` a step's repair within that repair attempt."""
        within = "step" if self.step_try == 2 else ""
        attempt = str(self.repair) if self.repair else ""
        return (*self.cells(), "+".join(filter(None, (attempt, within))) or "-")


@dataclass
class Batch:
    rows: list[Row] = field(default_factory=list)
    stopped: str | None = None


def proxy_row(cell_id: str, case_id: str, step_id: str, result: ProxyResult) -> Row:
    """A report row for a proxy attempt: its own cohort, no seed, no billed cost."""
    return Row(
        cell_id,
        case_id,
        step_id,
        result.cohort,
        None,
        result.attempt_id,
        result.status,
        "proxy",
        "0 (proxy)",
        len(result.issues),
        cohort=result.cohort,
    )


@dataclass(frozen=True)
class CohortSummary:
    """One cohort's results. Only the OpenRouter pool cohort is ever pooled; qualification is
    never asserted here (None = left to the coordinator's review) and is False for any other."""

    cohort: str
    attempts: int
    accepted: int
    rejected: int
    no_response: int
    pooled: bool
    qualification: bool | None


def summarize_cohorts(rows: Sequence[Row]) -> list[CohortSummary]:
    """Group by cohort, pool cohort first; `proxy:*` and any other cohort stay separate."""
    names = list(dict.fromkeys([COHORT, *(row.cohort for row in rows)]))
    summaries = []
    for name in names:
        group = [row for row in rows if row.cohort == name]
        pooled = name == COHORT
        summaries.append(
            CohortSummary(
                name,
                len(group),
                sum(row.status == "accepted" for row in group),
                sum(row.status == "rejected" for row in group),
                sum(row.status == NO_RESPONSE for row in group),
                pooled,
                None if pooled else False,
            )
        )
    return summaries


def _cap(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"{text!r} is not a USD amount") from None
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError("--cap must be a positive USD amount")
    return value


def _batch_id(text: str) -> str:
    if not BATCH_ID.fullmatch(text):
        raise argparse.ArgumentTypeError("--batch-id may hold letters, digits, '.', '_' and '-'")
    return text


def _max_tokens(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a token count") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("--max-tokens must be a positive token count")
    return value


def _timeout_s(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("--timeout must be a positive, finite number of seconds")
    return value


def _models(text: str) -> tuple[ModelSelection, ...]:
    try:
        return parse_selection(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _steps(text: str) -> tuple[str, ...]:
    names = tuple(text.split(","))
    unknown = [name for name in names if name not in STEPS]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown step(s) {unknown}; known: {', '.join(STEPS)}")
    if len(set(names)) != len(names):
        raise argparse.ArgumentTypeError("--steps names a step more than once")
    return names


def _schema_check_parser(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    check = actions.add_parser(
        "schema-check",
        help="one minimal strict response_format call per model and step schema (cents)",
    )
    check.add_argument("--models", type=_models, required=True, help="ID,... (no @EFFORT)")
    check.add_argument(
        "--steps", type=_steps, default=tuple(STEPS), help="STEP,... (default: every step)"
    )
    check.add_argument(
        "--cap", type=_cap, default=SCHEMA_CHECK_CAP, help=f"default {SCHEMA_CHECK_CAP} USD"
    )
    check.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    check.add_argument("--batch-id", type=_batch_id, help="default: schema-<UTC date>")
    check.add_argument("--artifact-root", type=Path, help="default: settings artifact_root")
    check.add_argument("--catalog", type=Path, help="saved models JSON; else fetched")
    check.add_argument("--report-directory", type=Path, default=REPORT_DIRECTORY)
    check.add_argument(
        "--bisect",
        action="store_true",
        help="for each HTTP 400, send schema variants (one suspect class each) until one is "
        "accepted; report only, no variant is ever used by a real run",
    )


def configure(parser: argparse.ArgumentParser) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--directory", type=Path, required=True, help="execution journal")
    common.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    common.add_argument("--cap", type=_cap, required=True, help="batch cap in USD (required)")
    common.add_argument("--seed", type=int, help="draw seed (default: random, recorded)")
    common.add_argument("--batch-id", type=_batch_id, help="default: UTC timestamp")
    common.add_argument("--artifact-root", type=Path, help="default: settings artifact_root")
    common.add_argument("--effort", choices=("high", "xhigh"), help="default: settings")
    common.add_argument(
        "--models",
        type=_models,
        help="ID[@EFFORT],... replaces the settings pool; eligibility is still checked",
    )
    common.add_argument(
        "--max-tokens",
        type=_max_tokens,
        default=DEFAULT_MAX_TOKENS,
        help=f"completion budget per call, every model (default {DEFAULT_MAX_TOKENS}); "
        "a model whose context or completion limit cannot hold it is ineligible",
    )
    common.add_argument(
        "--timeout",
        type=_timeout_s,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="request deadline per call in seconds, every model (default 600): each socket "
        "operation and the whole call",
    )
    common.add_argument("--catalog", type=Path, help="saved models JSON; else fetched")
    common.add_argument("--report-directory", type=Path, default=REPORT_DIRECTORY)
    actions = parser.add_subparsers(dest="live_command", required=True)
    probe = actions.add_parser("probe", parents=[common], help="CP-0, source_context, financials")
    probe.add_argument("--draws-per-model", type=int, default=1)
    module = actions.add_parser("module", parents=[common], help="one draw of one module")
    module.add_argument("--module", required=True)
    actions.add_parser(
        "regression",
        parents=[common],
        help="CP-0 and CP-1 cases, each pool model once (one model: a regression on it alone)",
    )
    actions.add_parser(
        "canary", parents=[common], help="CP-0 and CP-1, one cell per eligible pool model"
    )
    corpus = actions.add_parser(
        "corpus", help="write a replay corpus entry from a retained attempt"
    )
    corpus.add_argument("attempt", type=Path, help="sealed attempt directory (has manifest.json)")
    corpus.add_argument("case_id", help="entry file name without .json")
    corpus.add_argument("--replace", action="store_true", help="regenerate an existing entry")
    corpus.add_argument("--root", type=Path, default=CORPUS_ROOT, help="default: the repo corpus")
    corpus.add_argument(
        "--repository",
        type=Path,
        default=REPOSITORY_ROOT,
        help="checkout holding artifacts/public-case/ (default: this repository)",
    )
    corpus.add_argument(
        "--revalidate",
        action="store_true",
        help="expected = current validator over the real pack (outcome must not change)",
    )
    corpus.add_argument(
        "--outcome-changed-by",
        metavar="TASK_OR_DECISION",
        help="with --revalidate: the validator fix that changed the outcome (recorded)",
    )
    reconcile = actions.add_parser(
        "reconcile", help="replace held charges with the generation endpoint's cost"
    )
    reconcile.add_argument("--directory", type=Path, required=True, help="execution journal")
    reconcile.add_argument("--batch-id", type=_batch_id, required=True)
    reconcile.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    reconcile.add_argument("--artifact-root", type=Path, help="default: settings artifact_root")
    reconcile.add_argument("--report-directory", type=Path, default=REPORT_DIRECTORY)
    _schema_check_parser(actions)


def seed_for(pool: PinnedPool, slug: str, start: int) -> int:
    """First seed at or after `start` whose recorded draw selects `slug`."""
    for seed in range(start, start + SEED_SEARCH_LIMIT):
        if draw(pool, seed).slug == slug:
            return seed
    raise CliError(f"no seed near {start} draws {slug}")


def seeds_for(pool: PinnedPool, slugs: Sequence[str], start: int) -> list[int]:
    """One strictly increasing seed per slug, so no two cells share a seed."""
    seeds: list[int] = []
    cursor = start
    for slug in slugs:
        seeds.append(seed_for(pool, slug, cursor))
        cursor = seeds[-1] + 1
    return seeds


def _module_cells(module_arg: str, seed: int) -> list[Cell]:
    module = canonical(module_arg)
    steps = {"CP-0": CP0_STEPS, "CP-1": FULL_CHAIN, "CP-1A": CP1A_CHAIN}.get(module)
    if steps is None:
        supported = ", ".join(sorted({definition.module_id for definition in STEPS.values()}))
        raise CliError(f"{module} has no live step contract; supported: {supported}")
    return [Cell("module-00", module.lower(), steps, seed)]


def _regression_cells(pool: PinnedPool, slugs: list[str], seed: int) -> list[Cell]:
    excluded = [(item.slug, item.exclusion_reason) for item in pool.candidates if not item.eligible]
    if excluded:
        raise CliError(f"a matched comparison needs every candidate eligible; excluded: {excluded}")
    shuffler = random.Random(seed)
    plan: list[tuple[str, tuple[str, ...], str]] = []
    for case, steps in REGRESSION_CASES:
        order = list(slugs)
        shuffler.shuffle(order)
        plan += [(case, steps, slug) for slug in order]
    seeds = seeds_for(pool, [slug for _, _, slug in plan], seed)
    counts: dict[str, int] = {}
    cells: list[Cell] = []
    for (case, steps, _), cell_seed in zip(plan, seeds, strict=True):
        counts[case] = counts.get(case, -1) + 1
        cells.append(Cell(f"{case}-{counts[case]:02d}", case, steps, cell_seed))
    return cells


def _cells(args: argparse.Namespace, pool: PinnedPool, seed: int) -> list[Cell]:
    slugs = [item.slug for item in pool.eligible]
    if not slugs:
        raise NoEligibleModel("no eligible model in the pinned pool; the batch stays blocked")
    command = args.live_command
    if command == "module":
        return _module_cells(args.module, seed)
    if command == "regression":
        return _regression_cells(pool, slugs, seed)
    if command == "probe":
        if args.draws_per_model < 1:
            raise CliError("--draws-per-model must be at least 1")
        slugs = [slug for slug in slugs for _ in range(args.draws_per_model)]
    steps = PROBE_STEPS if command == "probe" else FULL_CHAIN
    return [
        Cell(f"{command}-{n:02d}", command, steps, cell_seed)
        for n, cell_seed in enumerate(seeds_for(pool, slugs, seed))
    ]


def _run_cell(
    cell: Cell,
    *,
    base: Execution,
    journals: Path,
    ledger: Ledger,
    pool: PinnedPool,
    client: ChatClient,
    writer: AttemptWriter,
    key_path: Path,
    key_index: int,
    bytes_per_token: Decimal,
    effort: str,
    max_tokens: int,
    timeout_s: float,
    evidence: Path,
    batch: Batch,
    rejections: Mapping[tuple[str, str, str], str],
    repair: bool,
) -> None:
    """Run one cell's steps in order, module by module. With `repair` (the `module` driver) a
    validator rejection that leaves the attempt pending is followed by that step's one repair
    within the attempt (task 7.0g); a rejection that finishes the attempt is followed by the
    module's one MC-7 repair attempt, which restarts the module from its first step. The cell
    ends at the first step that is not accepted."""
    store = Execution.create(journals / cell.cell_id, base.pack())
    sources = tuple(item.source_id for item in store.pack().sources)

    def send(step_id: str, attempt: Attempt) -> DispatchResult:
        result = dispatch(
            StepSpec(
                step_id,
                cell.case_id,
                step_sources(step_id, sources),  # task 7.5: only where spans are checked
                max_tokens=max_tokens,
                timeout_s=timeout_s,
            ),
            store=store,
            ticket_id=attempt.ticket_id,
            ledger=ledger,
            pool=pool,
            seed=cell.seed,
            client=client,
            writer=writer,
            key_path=key_path,
            key_index=key_index,
            bytes_per_token=bytes_per_token,
            effort=effort,
            schema_rejections=rejections,
        )
        batch.rows.append(
            Row(
                cell.cell_id,
                cell.case_id,
                step_id,
                result.draw.slug,
                cell.seed,
                result.attempt_id,
                result.status,
                result.classification or "none",
                usd_cell(
                    result.cost_usd, bool(result.settlement and result.settlement.unreconciled)
                ),
                len(result.issues),
                prompt_bound=result.prompt_tokens_upper_bound,
                repair=attempt.number,
                step_try=result.step_try,
            )
        )
        return result

    cp0_attempt = None

    def play(steps: Sequence[str], attempt: Attempt) -> DispatchResult:
        """Send the steps in order; the last result is the first non-accepted one, or the final."""
        nonlocal cp0_attempt
        for step_id in steps:
            result = send(step_id, attempt)
            if attempt.module_id == "CP-0":
                cp0_attempt = result.attempt_id  # the attempt whose review holds the T8 commands
            # A rejection the journal kept pending is the step's one repair within the attempt:
            # re-send the same step once. Its second rejection finishes the attempt (journal).
            # A truncated try is no verdict the model can act on (the budget is the operator's
            # knob, `--max-tokens`): a re-send at the same budget is a near-certain loss, so the
            # step's repair stays unused (task 7.0h).
            if (
                repair
                and result.status == "rejected"
                and result.attempt_pending
                and result.classification != TRUNCATED
            ):
                result = send(step_id, attempt)
            if result.status != "accepted":
                break
        return result

    for module, run in groupby(cell.steps, key=lambda step_id: STEPS[step_id].module_id):
        group = tuple(run)
        try:
            attempt = store.begin(module)
        except NotAuthorized as refusal:
            # CP-0 judged this consumer CONDITIONAL or BLOCKED: a valid accepted outcome,
            # recorded as this step's result. Nothing is sent; the cell ends, the batch goes on.
            record = _record_not_authorized(cell, group[0], refusal, pool, cp0_attempt, evidence)
            batch.rows.append(not_authorized_row(record))
            return
        steps = group
        while True:
            result = play(steps, attempt)
            if result.status == "accepted":
                break  # every step of the module is accepted: on to the next module
            # Only a validator verdict (rejected) on a first attempt earns the module's one MC-7
            # repair. A no-response or fallback leaves the ticket pending, and a repair already
            # used is spent: either ends the cell. A truncated rejection is a budget verdict, not a
            # validator one, and consumes no module repair either (task 7.0h); nor does a CP-1 QA
            # Blocked verdict, an analytical outcome that stands (task 7.4 fix round 1). `begin`
            # refuses a consumed repair loudly.
            if (
                not repair
                or result.status != "rejected"
                or result.classification == TRUNCATED
                or qa_blocked_only(result.issues)
                or attempt.number != 0
            ):
                return
            attempt = store.begin(module)
            steps = group[group.index(expected_step(attempt, module)) :]


def qa_blocked_only(issues: Sequence[str]) -> bool:
    """True when a rejection's issues are only the CP-1 QA Blocked verdict (`QA_BLOCKED`): the
    review is valid and its own judgments block QA, so the verdict stands and is not repaired."""
    return bool(issues) and all(QA_BLOCKED.fullmatch(issue) for issue in issues)


def _record_not_authorized(
    cell: Cell,
    step_id: str,
    refusal: NotAuthorized,
    pool: PinnedPool,
    cp0_attempt: str | None,
    evidence: Path,
) -> dict[str, object]:
    """Keep the refusal as batch evidence (write-once, beside the account-usage checks and
    outside every attempt directory) so the reconciled report lists the step too."""
    record: dict[str, object] = {
        "schema": NOT_AUTHORIZED_SCHEMA,
        "cell_id": cell.cell_id,
        "case_id": cell.case_id,
        "step_id": step_id,
        "module_id": refusal.module_id,
        "model": draw(pool, cell.seed).slug,  # the cell's drawn model, as dispatch draws it
        "seed": cell.seed,
        "cohort": COHORT,
        "status": NOT_AUTHORIZED,
        "cp0_attempt_id": cp0_attempt,  # this cell's CP-0 attempt (None if it ran none)
        "cp0_exact_command": list(refusal.commands),
        "reason": str(refusal),
        "recorded_at": utc_stamp(),
    }
    _write_once(evidence / "not-authorized" / f"{cell.cell_id}.json", record)
    return record


def not_authorized_row(record: Mapping[str, object]) -> Row:
    """The report row of a step CP-0 did not authorize: no attempt, class ok, USD 0, no issues."""
    seed = record.get("seed")
    return Row(
        str(record["cell_id"]),
        str(record["case_id"]),
        str(record["step_id"]),
        str(record["model"]),
        seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
        "none",
        NOT_AUTHORIZED,
        "ok",
        "0",
        0,
        cohort=str(record["cohort"]),
    )


def read_not_authorized(root: Path, batch_id: str) -> list[Row]:
    """The batch's not-authorized steps, by cell; a record of another schema is refused."""
    rows = []
    for path in sorted((root / batch_id / "not-authorized").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:  # a JSONDecodeError or undecodable bytes: the record is corrupt
            raise CliError(f"{path} is not a {NOT_AUTHORIZED_SCHEMA} record (not JSON)") from None
        if (
            not isinstance(record, dict)
            or record.get("schema") != NOT_AUTHORIZED_SCHEMA
            or not {"cell_id", "case_id", "step_id", "model", "cohort"} <= set(record)
        ):
            raise CliError(f"{path} is not a {NOT_AUTHORIZED_SCHEMA} record")
        rows.append(not_authorized_row(record))
    return rows


def usd_cell(charged: Decimal | None, held: bool) -> str:
    """The USD column: a held reservation is never shown as if it were a measured cost."""
    if charged is None:
        return "unknown"
    return f"{HELD} {format(charged, 'f')}" if held else format(charged, "f")


def _money_text(value: Decimal | None) -> str:
    return "-" if value is None else format(value, "f")


def _held_footnote(rows: Sequence[Row]) -> list[str]:
    return [HELD_FOOTNOTE, ""] if any(row.cost.startswith(HELD) for row in rows) else []


def _text(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _row(values: Sequence[object]) -> str:
    return "| " + " | ".join(_text(value) for value in values) + " |"


def _pool_cells(
    candidate: PinnedCandidate,
    default_effort: str,
    reserved: Mapping[str, Decimal],
    bounds: Mapping[str, int],
) -> tuple[str, ...]:
    held = reserved.get(candidate.slug)
    amount = "-" if held is None else format(held, "f")
    bound = str(bounds[candidate.slug]) if candidate.slug in bounds else "-"
    if not candidate.eligible:
        return (candidate.slug, "no", candidate.exclusion_reason or "", "-", "-", bound, amount)
    decision = candidate.effort_for(default_effort)
    own = candidate.requested_effort
    sent = (
        "none; reasoning enabled (" + decision.basis + ")"
        if decision.reasoning_enabled
        else f"{decision.sent}" + (" (mapped)" if decision.mapped else "")
    )
    return (
        candidate.slug,
        "yes",
        "",
        own if own else f"{default_effort} (default)",
        sent,
        bound,
        amount,
    )


def _repairs_dispatched(rows: Sequence[Row]) -> str:
    """Repairs that sent at least one step, both kinds: MC-7 repair attempts (per cell and
    module) and steps repaired within their attempt (task 7.0g; per cell, attempt and step). A
    repair stopped by the cap before its first dispatch has no row, and an `ineligible` row was
    sealed unsent; neither is counted."""
    sent = [row for row in rows if row.status != "ineligible"]
    modules = {(row.cell_id, STEPS[row.step_id].module_id) for row in sent if row.repair}
    steps = {(row.cell_id, row.repair, row.step_id) for row in sent if row.step_try == 2}
    return (
        f"{len(modules) + len(steps)} (module repair attempts {len(modules)}, "
        f"within-attempt step repairs {len(steps)})"
    )


def render_report(
    command: str,
    batch_id: str,
    seed: int,
    pool: PinnedPool,
    ledger: Ledger,
    cells: Sequence[Cell],
    batch: Batch,
    default_effort: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Summary tables only; counts come from the registry and the retained results."""
    state = ledger.state()
    models = {row.attempt_id: row.model for row in batch.rows}
    reserved: dict[str, Decimal] = {}
    for record in state.attempts:
        model = models.get(record.attempt_id)
        if model is not None:
            reserved[model] = max(reserved.get(model, Decimal(0)), record.reserved_usd)
    # The prompt bound behind each reservation, also for an attempt sealed ineligible.
    bounds: dict[str, int] = {}
    for row in batch.rows:
        if row.prompt_bound is not None:
            bounds[row.model] = max(bounds.get(row.model, 0), row.prompt_bound)
    pool_line = (
        f"user-selected ({POOL_RULING})" if pool.pool_label == USER_SELECTED else "catalog rule"
    )
    live = {definition.module_id for definition in STEPS.values()}
    refused = sum(row.status == NOT_AUTHORIZED for row in batch.rows)
    steps_header = ("Cell", "Case", "Step", "Model", "Seed", "Attempt", "Status", "Class", "USD")
    pool_header = (
        "Model",
        "Eligible",
        "Reason",
        "Requested effort",
        "Effort sent",
        "Prompt token bound (largest)",
        "Reserved USD per attempt (largest)",
    )
    lines = [
        f"# Live batch {batch_id}",
        "",
        f"- Command: {command}",
        f"- Pool: {pool_line}",
        f"- Seed: {seed}",
        f"- Cap: {format(state.cap, 'f')} USD; reserved {format(state.reserved, 'f')}, "
        f"spent {format(state.spent, 'f')}, remaining {format(state.remaining, 'f')}",
        f"- Catalog: {pool.catalog_source} (sha256 {pool.catalog_sha256}), looked up "
        f"{pool.looked_up_at}",
        f"- Registry modules with a live step contract: {len(live)} of {len(modules())}",
        f"- Max tokens: {max_tokens} per call (every model)",
        f"- Timeout: {timeout_s} s per call (every model)",
        f"- Cells planned: {len(cells)}; steps run: {len(batch.rows) - refused}; "
        f"not authorized by CP-0: {refused}",
        f"- Repairs dispatched: {_repairs_dispatched(batch.rows)}",
        f"- Truncated: {sum(row.classification == TRUNCATED for row in batch.rows)}",
        f"- Stopped: {batch.stopped or 'no'}",
        "",
        "## Pool",
        "",
        _row(pool_header),
        _row(("---",) * len(pool_header)),
        *(_row(_pool_cells(c, default_effort, reserved, bounds)) for c in pool.candidates),
        "",
        "## Steps",
        "",
        _row((*steps_header, "Issues", "Repair")),
        _row(("---",) * (len(steps_header) + 2)),
        *(_row(r.step_cells()) for r in batch.rows if r.cohort == COHORT),
        "",
    ]
    # Results are grouped by cohort and never merged: proxy cohorts (DC-8) get their own table
    # and are never pooled with, or counted as qualification of, a pool model.
    for summary in summarize_cohorts(batch.rows):
        if summary.cohort != COHORT:
            lines += [
                f"## Steps ({summary.cohort})",
                "",
                _row((*steps_header, "Issues", "Repair")),
                _row(("---",) * (len(steps_header) + 2)),
                *(_row(r.step_cells()) for r in batch.rows if r.cohort == summary.cohort),
                "",
            ]
    lines += _held_footnote(batch.rows)
    cohort_header = (
        "Cohort",
        "Attempts",
        "Accepted",
        "Rejected",
        "No response",
        "Pooled",
        "Qualification",
    )
    lines += [
        "## Cohorts",
        "",
        _row(cohort_header),
        _row(("---",) * len(cohort_header)),
        *(
            _row(
                (
                    s.cohort,
                    s.attempts,
                    s.accepted,
                    s.rejected,
                    s.no_response,
                    "yes" if s.pooled else "no",
                    "not decided here" if s.qualification is None else str(s.qualification).lower(),
                )
            )
            for s in summarize_cohorts(batch.rows)
        ),
        "",
    ]
    return "\n".join(lines)


def open_ledger(path: Path) -> Ledger:
    """An existing ledger file opened with the cap its first line records."""
    first = path.read_bytes().split(b"\n", 1)[0]
    try:
        cap = Decimal(str(json.loads(first)["cap_usd"]))
    except (ValueError, KeyError, TypeError, InvalidOperation):
        raise LedgerError(f"{path.name} has no readable opening line") from None
    return Ledger(path, cap)


def committed_elsewhere(directory: Path) -> Decimal:
    """Held plus settled spend over every ledger file under `directory` (each replayed).

    Settled spend is the final charge, so a reconciled (`adjust`) attempt counts its
    generation-endpoint cost, not the reservation it held before."""
    total = Decimal(0)
    for path in sorted(directory.glob("*.jsonl")):
        state = open_ledger(path).state()
        total += state.reserved + state.spent
    return total


def _finish_report(path: Path, content: str, inflight: BaseException | None) -> None:
    """Write the report; a failure here never replaces the exception `inflight`, if any."""
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    except OSError as problem:
        if inflight is None:
            raise
        inflight.add_note(f"live report not written: {type(problem).__name__}: {problem}")


USAGE_SCHEMA = "account-usage-check/1"


def record_usage(root: Path, batch_id: str, phase: str, client: ChatClient, command: str) -> None:
    """Keep one `GET /api/v1/key` reply as batch evidence (write-once, no key text).

    `live reconcile` reads the before/after pair to corroborate a generation 404 (decision
    0008). Errors propagate: before the batch nothing has been spent yet."""
    record = {
        "schema": USAGE_SCHEMA,
        "phase": phase,
        "recorded_by": f"deploy-vii live {command}",
        "credit": credit_state(client).to_record(),
    }
    _write_once(usage_path(root, batch_id, phase), record)


def _write_once(path: Path, record: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=1, sort_keys=True) + "\n")


def _record_usage_after(
    root: Path, batch_id: str, client: ChatClient, command: str, inflight: BaseException | None
) -> None:
    """The after-batch check. Money is already spent, so a failure is recorded in the evidence
    file (and as a note on any in-flight exception), never raised over the batch's outcome;
    reconcile then has no usage window and leaves 404s unresolved (documented fail-open)."""
    try:
        record_usage(root, batch_id, "after", client, command)
    except (TransportError, CredentialError, OSError) as problem:
        failure = f"{type(problem).__name__}: {problem}"
        print(f"account usage after the batch not recorded: {failure}")
        if inflight is not None:
            inflight.add_note(f"account usage after the batch not recorded: {failure}")
        try:
            _write_once(
                usage_path(root, batch_id, "after"),
                {
                    "schema": USAGE_SCHEMA,
                    "phase": "after",
                    "recorded_by": f"deploy-vii live {command}",
                    "credit": None,
                    "failure": failure,
                },
            )
        except OSError as unwritten:
            # The printed lines are then the only record of the failed check.
            print(f"account usage failure record not written: {type(unwritten).__name__}")


def _open_batch(args: argparse.Namespace, settings: LiveSettings, batch_id: str) -> Path:
    """Refuse a cap above the ceilings or an existing report; return the report path."""
    if args.cap > settings.caps.cumulative_ceiling:
        raise CliError(
            f"--cap {args.cap} exceeds the cumulative ceiling {settings.caps.cumulative_ceiling}"
        )
    root = args.artifact_root or settings.artifact_root
    report: Path = args.report_directory / f"live-{batch_id}.md"
    if report.exists():
        raise CliError(f"{report} already exists; choose another --batch-id")
    prior = committed_elsewhere(root / ".ledgers")
    if prior + args.cap > settings.caps.cumulative_ceiling:
        raise CliError(
            f"prior ledgers hold {format(prior, 'f')} USD and --cap is {format(args.cap, 'f')}: "
            f"together they exceed the cumulative ceiling {settings.caps.cumulative_ceiling}"
        )
    args.report_directory.mkdir(parents=True, exist_ok=True)  # fail before any spend
    return report


def run_live(args: argparse.Namespace, *, transport: Transport | None = None) -> int:
    """Run one live subcommand and return its exit status."""
    transport = transport or urllib_transport
    settings: LiveSettings = load_settings(args.settings)
    batch_id = args.batch_id or utc_stamp().replace(":", "").replace("-", "")
    root = args.artifact_root or settings.artifact_root
    report = _open_batch(args, settings, batch_id)
    ledgers = root / ".ledgers"
    rejections = schema_rejections(root)  # an unreadable schema-check record fails here
    seed = args.seed if args.seed is not None else secrets.randbits(31)
    catalog = Catalog.from_file(args.catalog) if args.catalog else Catalog.fetch(transport)
    pool = (
        catalog.pin_selected(batch_id, args.models)
        if args.models
        else catalog.pin(batch_id, settings.candidates)
    )
    default_effort = args.effort or settings.default_effort
    cells = _cells(args, pool, seed)
    ledger = Ledger(ledgers / f"{batch_id}.jsonl", args.cap)
    ledger.state()  # an opened ledger is bound to its first cap; a different one raises here
    usage_client = ChatClient(
        transport, key_path=settings.credential_file, key_index=settings.credential_token_index
    )
    batch = Batch()
    try:
        record_usage(root, batch_id, "before", usage_client, args.live_command)
        for cell in cells:
            _run_cell(
                cell,
                base=Execution(args.directory),
                journals=args.directory / "live" / batch_id,
                ledger=ledger,
                pool=pool,
                client=ChatClient(transport),
                writer=AttemptWriter(root),
                key_path=settings.credential_file,
                key_index=settings.credential_token_index,
                bytes_per_token=settings.prompt_bytes_per_token_lower_bound,
                effort=default_effort,
                max_tokens=args.max_tokens,
                timeout_s=args.timeout,
                evidence=root / batch_id,
                batch=batch,
                rejections=rejections,
                repair=args.live_command == "module",
            )
    except CapExceeded as stop:
        batch.stopped = f"cap: {stop}"
    except BaseException as failure:
        batch.stopped = f"aborted: {type(failure).__name__}"
        raise
    finally:
        _record_usage_after(root, batch_id, usage_client, args.live_command, sys.exception())
        _finish_report(
            report,
            render_report(
                args.live_command,
                batch_id,
                seed,
                pool,
                ledger,
                cells,
                batch,
                default_effort,
                args.max_tokens,
                args.timeout,
            ),
            sys.exception(),
        )
    state = ledger.state()
    print(
        f"{report}: {len(batch.rows)} steps, spent {format(state.spent, 'f')} "
        f"of {format(state.cap, 'f')} USD"
    )
    return EXIT_CAP if batch.stopped else 0


def _cell_names(journals: Path) -> tuple[dict[str, str], list[str]]:
    """ticket id -> cell id from the batch's journal copies, plus notes on unreadable ones."""
    names: dict[str, str] = {}
    notes: list[str] = []
    for directory in sorted(journals.iterdir()) if journals.is_dir() else ():
        if not (directory / "current").is_file():
            continue
        try:
            attempts = Execution(directory).read().attempts
        except (OSError, ValueError) as error:
            # A label only: the money is reconciled regardless, and the gap is reported.
            notes.append(f"journal {directory.name} unreadable ({type(error).__name__}); cell -")
            continue
        names.update({item.ticket_id: directory.name for item in attempts})
    return names, notes


def _reconciled_row(
    attempt: RetainedAttempt, record: AttemptRecord | None, cells: dict[str, str]
) -> Row:
    manifest = attempt.manifest
    cohort = str(manifest.get("cohort", "unknown"))
    draw_record = manifest.get("draw")
    seed = draw_record.get("seed") if isinstance(draw_record, dict) else None
    if cohort != COHORT:
        cost = "0 (proxy)"
    elif record is None or record.charged_usd is None:
        cost = "not dispatched"
    else:
        cost = usd_cell(record.charged_usd, record.actual_usd is None)
    validator = manifest.get("validator")
    issues = validator.get("issues", []) if isinstance(validator, dict) else []
    return Row(
        cells.get(str(manifest.get("ticket_id")), "-"),
        str(manifest.get("case_id")),
        str(manifest.get("step_id")),
        str(manifest.get("model")),
        seed if isinstance(seed, int) else None,
        attempt.attempt_id,
        str(manifest.get("status")),
        str(manifest.get("classification") or "none"),
        cost,
        len(issues),
        cohort=cohort,
    )


def render_reconciliation(
    batch_id: str,
    ledger: Ledger,
    attempts: Sequence[RetainedAttempt],
    cells: dict[str, str],
    notes: Sequence[str],
    outcomes: Sequence[Outcome],
    checked_at: str,
    not_authorized: Sequence[Row] = (),
) -> str:
    """The batch's steps with final charges (ledger after `adjust`) and the lookups made; the
    steps CP-0 did not authorize (no attempt, nothing charged) follow the retained attempts."""
    state = ledger.state()
    records = {item.attempt_id: item for item in state.attempts}
    order = {name: index for index, name in enumerate(records)}
    ranked = sorted(attempts, key=lambda a: (order.get(a.attempt_id, len(order)), a.attempt_id))
    rows = [_reconciled_row(a, records.get(a.attempt_id), cells) for a in ranked]
    rows += not_authorized
    steps_header = ("Cell", "Case", "Step", "Model", "Seed", "Attempt", "Status", "Class", "USD")
    outcome_header = ("Attempt", "Generation", "Id source", "Held USD", "Reconciled USD", "Outcome")
    lines = [
        f"# Live batch {batch_id} (reconciled)",
        "",
        f"- Checked: {checked_at}; regenerated on every `deploy-vii live reconcile`",
        f"- Batch report: live-{batch_id}.md (written at run time, never rewritten)",
        f"- Cap: {format(state.cap, 'f')} USD; reserved {format(state.reserved, 'f')}, "
        f"spent {format(state.spent, 'f')}, remaining {format(state.remaining, 'f')}, "
        f"overrun {format(state.overrun, 'f')}",
        f"- Looked up this run: {len(outcomes)}; reconciled "
        f"{sum(o.status != 'unresolved' for o in outcomes)}, unresolved "
        f"{sum(o.status == 'unresolved' for o in outcomes)}",
        *(f"- Note: {note}" for note in notes),
        "",
        "## Steps",
        "",
        _row((*steps_header, "Issues", "Cohort")),
        _row(("---",) * (len(steps_header) + 2)),
        *(_row((*r.cells(), r.cohort)) for r in rows),
        "",
        *_held_footnote(rows),
        "## Reconciliation",
        "",
        _row((*outcome_header, "Reason")),
        _row(("---",) * (len(outcome_header) + 1)),
        *(
            _row(
                (
                    o.attempt_id,
                    o.generation_id or "-",
                    o.id_source,
                    _money_text(o.previous_usd),
                    _money_text(o.reconciled_usd),
                    o.status,
                    o.reason,
                )
            )
            for o in outcomes
        ),
        "",
    ]
    return "\n".join(lines)


def _write_derived(path: Path, content: str) -> None:
    """Replace a derived report atomically (temp file then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def run_reconcile(args: argparse.Namespace, *, transport: Transport | None = None) -> int:
    """Look up every held pool charge of a batch; adjust the ledger where a cost is returned."""
    settings: LiveSettings = load_settings(args.settings)
    root = args.artifact_root or settings.artifact_root
    path = root / ".ledgers" / f"{args.batch_id}.jsonl"
    if not path.is_file():
        raise CliError(f"no ledger for batch {args.batch_id} under {root / '.ledgers'}")
    ledger = open_ledger(path)
    ledger.state()  # a corrupt ledger raises here, before any call
    client = ChatClient(
        transport or urllib_transport,
        key_path=settings.credential_file,
        key_index=settings.credential_token_index,
    )
    report = args.report_directory / f"live-{args.batch_id}-reconciled.md"
    outcomes: list[Outcome] = []
    checked_at = utc_stamp()
    retained = list(batch_attempts(root, args.batch_id))
    refused = read_not_authorized(root, args.batch_id)  # a bad record fails before any call
    usage = read_usage(root, args.batch_id)
    try:
        for attempt in lookup_order(candidates(root, args.batch_id)):
            outcomes.append(
                reconcile_attempt(attempt, ledger, client, utc_stamp, batch=retained, usage=usage)
            )
    finally:
        cells, notes = _cell_names(args.directory / "live" / args.batch_id)
        content = render_reconciliation(
            args.batch_id,
            ledger,
            list(batch_attempts(root, args.batch_id)),
            cells,
            notes,
            outcomes,
            checked_at,
            refused,
        )
        try:
            _write_derived(report, content)
        except OSError as problem:
            inflight = sys.exception()
            if inflight is None:
                raise
            inflight.add_note(f"reconciled report not written: {type(problem).__name__}")
    unresolved = sum(o.status == "unresolved" for o in outcomes)
    state = ledger.state()
    print(
        f"{report}: reconciled {len(outcomes) - unresolved}, unresolved {unresolved}; "
        f"spent {format(state.spent, 'f')} of {format(state.cap, 'f')} USD"
    )
    return 0


NON_SCHEMA_400 = "no: the 400 does not name the schema"


def _blocks(check: SchemaCheck) -> str:
    """Whether this verdict makes the cell ineligible in later runs (`schema_rejections`)."""
    if check.schema_rejection:
        return "yes: schema rejection"
    return NON_SCHEMA_400 if check.http_status == 400 else "-"


def _usd(check: SchemaCheck) -> str:
    return (
        "not dispatched" if check.charged_usd is None else usd_cell(check.charged_usd, check.held)
    )


def _keywords(sent: dict[str, Any]) -> str:
    """The Keywords cell: the sent schema's keywords, then its resolved depth and size."""
    return f"{', '.join(schema_keywords(sent))}; {schema_shape(sent)}"


def _check_cells(check: SchemaCheck) -> tuple[object, ...]:
    return (
        check.model,
        check.step_id,
        check.outcome,
        check.classification,
        "-" if check.http_status is None else check.http_status,
        _usd(check),
        check.attempt_id,
        check.schema_sha256,
        ", ".join(check.relaxations) or "none",
        _keywords(strict_schema(STEPS[check.step_id].schema)),
        _blocks(check),
        check.detail or "-",
    )


def _ineligible_check(candidate: PinnedCandidate, step_id: str) -> tuple[object, ...]:
    """The row of a model the catalog rules out: nothing reserved, nothing sent, no attempt."""
    schema = STEPS[step_id].schema
    return (
        candidate.slug,
        step_id,
        "ineligible",
        candidate.exclusion_reason or "",
        "-",
        "0",
        "none",
        hashlib.sha256(schema_text(schema).encode()).hexdigest(),
        ", ".join(schema_relaxations(schema)) or "none",
        _keywords(strict_schema(schema)),
        "-",
        "-",
    )


def _variant_cells(check: SchemaCheck, touches: str) -> tuple[object, ...]:
    return (
        check.model,
        check.step_id,
        check.variant,
        check.outcome,
        check.classification,
        "-" if check.http_status is None else check.http_status,
        _usd(check),
        check.attempt_id,
        check.schema_sha256,
        check.detail or "-",
        touches,
    )


def _unsent_variant(
    model: str, step_id: str, variant: str, outcome: str, why: str
) -> tuple[object, ...]:
    """A variant that is not sent: it changes nothing, it is an open object (reported), or it
    cannot be built (a cyclic or unresolved `$ref`)."""
    return (model, step_id, variant, outcome, why, "-", "0", "none", "-", "-", "-")


@dataclass
class Bisection:
    """`--bisect` results: variant rows and, per bisected (model, step), the first accepted
    variant ("none accepted" or "not finished (...)" otherwise)."""

    rows: list[tuple[object, ...]] = field(default_factory=list)
    verdicts: dict[tuple[str, str], str] = field(default_factory=dict)


def render_schema_report(
    batch_id: str,
    pool: PinnedPool,
    ledger: Ledger,
    steps: Sequence[str],
    rows: Sequence[tuple[object, ...]],
    stopped: str | None,
    bisection: Bisection | None = None,
) -> str:
    """One row per (model, step): the provider's verdict on the sent schema, then (with
    `--bisect`) the variant rows and each bisected cell's first accepted variant. The provider's
    error text is shown (key scrubbed); response bodies, prompts and content never are."""
    state = ledger.state()
    counts = {
        name: sum(row[2] == name for row in rows)
        for name in ("accepted", "http_error", "other", "ineligible", "refused")
    }
    header = (
        "Model",
        "Step",
        "Outcome",
        "Class",
        "HTTP",
        "USD",
        "Attempt",
        "Sent schema sha256",
        "Relaxations",
        "Keywords",
        "Blocks later runs",
        "Provider detail",
    )
    bisect_line = "yes (variants are reported only; no real run sends them)" if bisection else "no"
    lines = [
        f"# Live batch {batch_id} (schema-check)",
        "",
        "- Command: schema-check (one strict response_format call per model and step; "
        f"max_tokens {SCHEMA_CHECK_MAX_TOKENS}, no reasoning parameter, nothing submitted)",
        f"- Steps: {', '.join(steps)}",
        f"- Cap: {format(state.cap, 'f')} USD; reserved {format(state.reserved, 'f')}, "
        f"spent {format(state.spent, 'f')}, remaining {format(state.remaining, 'f')}",
        f"- Catalog: {pool.catalog_source} (sha256 {pool.catalog_sha256}), looked up "
        f"{pool.looked_up_at}",
        f"- Accepted: {counts['accepted']}; http_error: {counts['http_error']}; other: "
        f"{counts['other']}; ineligible: {counts['ineligible']}; refused: {counts['refused']}",
        f"- Bisect: {bisect_line}",
        f"- Stopped: {stopped or 'no'}",
        "",
        "## Results",
        "",
        _row(header),
        _row(("---",) * len(header)),
        *(_row(row) for row in rows),
        "",
        f"`Blocks later runs` `{NON_SCHEMA_400}`: the provider gave no schema reason (Google's "
        'is only "Request contains an invalid argument"), so the cell stays eligible.',
        "",
    ]
    held = any(str(row[5]).startswith(HELD) for row in rows)
    if bisection is not None:
        variant_header = (
            "Model",
            "Step",
            "Variant",
            "Outcome",
            "Class",
            "HTTP",
            "USD",
            "Attempt",
            "Variant schema sha256",
            "Provider detail",
            "Touches",
        )
        lines += [
            "## Bisect",
            "",
            _row(variant_header),
            _row(("---",) * len(variant_header)),
            *(_row(row) for row in bisection.rows),
            "",
            "## First accepted variant",
            "",
            *(
                f"- {model} {step}: {verdict}"
                for (model, step), verdict in bisection.verdicts.items()
            ),
            "",
        ]
        held = held or any(str(row[6]).startswith(HELD) for row in bisection.rows)
    lines += [HELD_FOOTNOTE, ""] if held else []
    return "\n".join(lines)


def _bisect(
    check: SchemaCheck,
    send: Callable[[tuple[str, dict[str, Any]] | None], SchemaCheck],
    bisection: Bisection,
) -> str | None:
    """Send the variants of a rejected cell's schema in order until one is accepted; return
    the stop reason when the cap refuses one. Variants are reported only, never applied."""
    key = (check.model, check.step_id)
    bisection.verdicts[key] = "not finished (aborted)"  # replaced unless something raises
    sent = strict_schema(STEPS[check.step_id].schema)
    for name in BISECT_VARIANTS:
        if name == OPEN_OBJECT:
            found = open_objects(sent)
            outcome, why = (
                ("open object", f"skipped: {found} node(s); closing them changes the contract")
                if found
                else ("not applicable", "not sent")
            )
            bisection.rows.append(_unsent_variant(check.model, check.step_id, name, outcome, why))
            continue
        try:
            variant = bisect_variant(name, sent)
        except VariantRefused as refused:  # reported in the row; nothing is sent for it
            row = _unsent_variant(check.model, check.step_id, name, "not sendable", str(refused))
            bisection.rows.append(row)
            continue
        if variant == sent:
            row = _unsent_variant(check.model, check.step_id, name, "not applicable", "not sent")
            bisection.rows.append(row)
            continue
        result = send((name, variant))
        # The one variant that changes what a reply may say names the fields it changes.
        touched = nullable_array_fields(sent) if name == NULLABLE_ARRAY_REQUIRED else []
        bisection.rows.append(_variant_cells(result, ", ".join(touched) or "-"))
        if result.outcome == "refused":
            bisection.verdicts[key] = "not finished (cap)"
            return f"cap: {result.detail}"
        if result.outcome == "accepted":
            bisection.verdicts[key] = f"first accepted variant: {name}"
            return None
    bisection.verdicts[key] = "none accepted"
    return None


def run_schema_check(args: argparse.Namespace, *, transport: Transport | None = None) -> int:
    """`live schema-check`: the provider's verdict on each sent step schema, for cents.

    A schema-shaped rejection recorded here (an HTTP 400 naming the schema, `schema_shaped`)
    makes the same (model, step, schema) cell of a later probe or module batch under the same
    artifact root ineligible before dispatch; `--bisect` variants never do."""
    transport = transport or urllib_transport
    effort = [item.model_id for item in args.models if item.effort is not None]
    if effort:
        raise CliError(f"schema-check sends no reasoning parameter; drop @EFFORT from {effort}")
    settings: LiveSettings = load_settings(args.settings)
    batch_id = args.batch_id or "schema-" + utc_stamp()[:10].replace("-", "")
    root = args.artifact_root or settings.artifact_root
    report = _open_batch(args, settings, batch_id)
    catalog = Catalog.from_file(args.catalog) if args.catalog else Catalog.fetch(transport)
    pool = catalog.pin_selected(batch_id, args.models)
    ledger = Ledger(root / ".ledgers" / f"{batch_id}.jsonl", args.cap)
    ledger.state()  # an opened ledger is bound to its first cap; a different one raises here
    usage_client = ChatClient(
        transport, key_path=settings.credential_file, key_index=settings.credential_token_index
    )
    rows: list[tuple[object, ...]] = []
    stopped: str | None = None
    writer, client = AttemptWriter(root), ChatClient(transport)
    bisection = Bisection() if args.bisect else None

    def send(
        candidate: PinnedCandidate, step_id: str, variant: tuple[str, dict[str, Any]] | None
    ) -> SchemaCheck:
        return check_schema(
            candidate,
            step_id,
            batch_id=batch_id,
            ledger=ledger,
            client=client,
            writer=writer,
            key_path=settings.credential_file,
            key_index=settings.credential_token_index,
            bytes_per_token=settings.prompt_bytes_per_token_lower_bound,
            variant=variant,
        )

    def checks() -> str | None:
        """Run every (model, step) in order, bisecting a 400 when asked; the reason the batch
        stopped, if it did."""
        for candidate in pool.candidates:
            for step_id in args.steps:
                if not candidate.eligible:
                    rows.append(_ineligible_check(candidate, step_id))
                    continue
                check = send(candidate, step_id, None)
                rows.append(_check_cells(check))
                if check.outcome == "refused":
                    return f"cap: {check.detail}"
                if bisection is not None and check.http_status == 400:
                    stop = _bisect(check, partial(send, candidate, step_id), bisection)
                    if stop is not None:
                        return stop
        return None

    try:
        record_usage(root, batch_id, "before", usage_client, args.live_command)
        stopped = checks()
    except BaseException as failure:
        stopped = f"aborted: {type(failure).__name__}"
        raise
    finally:
        _record_usage_after(root, batch_id, usage_client, args.live_command, sys.exception())
        _finish_report(
            report,
            render_schema_report(batch_id, pool, ledger, args.steps, rows, stopped, bisection),
            sys.exception(),
        )
    state = ledger.state()
    print(
        f"{report}: {len(rows)} checks, spent {format(state.spent, 'f')} "
        f"of {format(state.cap, 'f')} USD"
    )
    return EXIT_CAP if stopped else 0


def execute(args: argparse.Namespace, *, transport: Transport | None = None) -> int:
    if args.live_command == "corpus":
        try:
            target = write_entry(
                args.attempt,
                args.case_id,
                root=args.root,
                replace=args.replace,
                repository=args.repository,
                revalidate=args.revalidate,
                outcome_changed_by=args.outcome_changed_by,
            )
            print(target)
        except (CorpusError, OSError) as error:
            print(f"live corpus failed: {type(error).__name__}: {error}")
            return EXIT_FAILED
        return 0
    try:
        if args.live_command == "schema-check":
            return run_schema_check(args, transport=transport)
        if args.live_command == "reconcile":
            return run_reconcile(args, transport=transport)
        return run_live(args, transport=transport)
    except CreditExhausted as error:
        print(f"live {args.live_command} stopped: {error}")
        print("ticket pending; coordinator decision (DC-8)")
        return EXIT_CREDIT
    except (
        CliError,
        SettingsError,
        CatalogError,
        CredentialError,
        LedgerError,
        NoEligibleModel,
        TransportError,
        ValueError,
        OSError,
    ) as error:
        print(f"live {args.live_command} failed: {type(error).__name__}: {error}")
        for note in getattr(error, "__notes__", ()):
            print(note)
        return EXIT_FAILED
