"""Tier I2 for tool loops (task 8.0d): a recorded tool transcript replays through `live.loop`.

An entry (`tests/product/replay_transcripts/<step>/<name>.json`, schema `tool-transcript/1`)
holds one step's model replies in order and what the step did with them: each call's request
(the system prompt's hash, and the hash of everything else the request carried: the rest of the
conversation, the tools and the request parameters), every tool result's hash, each submit's
outcome and issues, the verdict and the settled cost. Replay feeds the same replies to
`run_tool_step` (a fake transport and clock, no network) on the same starting journal, then
compares; it also records the step's outcomes under the default evidence rules (`rules`), which
the harness never applied.

Two kinds of entry:

- `synthetic`: replies held in the entry, on the registered synthetic CP-1 case (CI replays it).
- `harness`: a hybrid harness step directory (`devtools/hybrid_cp1.py`) under `artifacts/`,
  named by its repository-relative path with the hash of each reply file and of its tool log, and
  its starting journal (the cell's `journal-start`, or the previous step's accepted
  `journal-submit-<n>`). Raw artifacts stay out of Git, so such an entry replays only where the
  artifacts are present (`skipped-artifacts-absent` elsewhere, never a pass); a reply file whose
  hash differs is a failure. The harness ran no rules, so its submits are replayed without them.

A system prompt changed deliberately after the recording names the change (`system_prompt.
changed_by`, a task or decision), the recorded hash (which every recorded request must still
carry) and the hash it now has; any other change fails. Its other
messages, its tools and every tool result must still be identical.

A tool added to the step after the recording (task 8.10b) is named the same way: `tools_added`
lists the added tools' names and `tools_added_by` the dated reason. The check requires each
named tool exactly once in every replayed request, strips only those specs, and the rest must
then hash exactly as recorded, so any other change to the tool list (or a tool named but not
sent) still fails.
"""

import hashlib
import json
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from deploy_vii.cp0_workflow import submit_cp0_review
from deploy_vii.execution import Execution
from deploy_vii.live.catalog import ModelSelection, PinnedPool
from deploy_vii.live.client import ChatClient, Request, Response
from deploy_vii.live.ledger import Ledger
from deploy_vii.live.loop import ToolStepResult, run_tool_step
from deploy_vii.live.retention import TOOL_TRANSCRIPT, AttemptWriter
from deploy_vii.live.runner import StepSpec
from deploy_vii.live.settings import StepEffort
from deploy_vii.live.submission import submit_model_payload
from deploy_vii.live.tools import ToolRules
from tests.product.live_support import catalog_of, catalog_row, make_rtf_key
from tests.product.test_workflow import cp1_case

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TRANSCRIPT_ROOT = Path(__file__).parent / "replay_transcripts"
SCHEMA = "tool-transcript/1"
OK, SKIPPED = "ok", "skipped-artifacts-absent"
PARAMETERS = (
    "max_tokens",
    "reasoning",
    "reasoning_effort",
    "response_format",
    "structured_outputs",
    "tools",
    "tool_choice",
)
NO_RULES = ToolRules(checked=())
# Once the recorded replies run out (a rule rejected a submit the harness accepted), the model
# is taken to stop: a reply without a tool call ends the step as `rejected: no-submit`.
STOP = {
    "id": "gen-transcript-stop",
    "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": ""}}],
    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0},
}


def transcript_entries(root: Path = TRANSCRIPT_ROOT) -> list[Path]:
    return sorted(root.glob("*/*.json"))


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def request_record(body: dict[str, Any]) -> dict[str, str]:
    """A request as the entry records it: the system prompt apart from everything else."""
    messages = body["messages"]
    assert messages[0]["role"] == "system", "a tool-loop request opens with its system prompt"
    rest = {key: value for key, value in body.items() if key != "messages"}
    rest["messages"] = messages[1:]
    return {
        "system_sha256": sha256(messages[0]["content"]),
        "rest_sha256": sha256(json.dumps(rest, sort_keys=True)),
    }


@dataclass(frozen=True)
class Replayed:
    """What one replay did."""

    result: ToolStepResult
    requests: list[dict[str, str]]
    tool_results: list[str]
    bodies: list[dict[str, Any]]

    def record(self) -> dict[str, Any]:
        return {
            "verdict": self.result.verdict,
            "submits": [
                {"outcome": item["outcome"], "issues": item["issues"]}
                for item in self.result.submits
            ],
            "requests": self.requests,
            "tool_results_sha256": self.tool_results,
            "cost_settled_usd": format(self.result.cost_usd, "f"),
        }


def pool(entry: dict[str, Any]) -> PinnedPool:
    model = entry["model"]
    row = catalog_row(
        model["id"],
        context=model["context_length"],
        completion_limit=model["max_completion_tokens"],
        efforts=("low", "medium", "high", "xhigh", "max"),
        parameters=PARAMETERS,
        pricing=model["pricing"],
    )
    row["canonical_slug"] = model["canonical_slug"]
    return catalog_of(row).pin_selected("transcript", (ModelSelection(model["id"], None),))


def replies(entry: dict[str, Any], repository: Path) -> list[bytes]:
    if entry["kind"] == "synthetic":
        return [json.dumps(item).encode() for item in entry["replies"]]
    directory = repository / entry["transcript"]
    return [(directory / name).read_bytes() for name in entry["reply_files"]]


def _tool_results(writer: AttemptWriter, pool: PinnedPool, result: ToolStepResult) -> Iterator[str]:
    for attempt in result.attempt_ids:
        directory = (
            writer.root
            / pool.batch_id
            / "transcript"
            / pool.candidates[0].slug.replace("/", "__")
            / attempt
        )
        for line in (directory / TOOL_TRANSCRIPT).read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if "result" in item:
                yield sha256(item["result"])


def replay(
    entry: dict[str, Any],
    start: Path,
    work: Path,
    *,
    rules: ToolRules = NO_RULES,
    repository: Path = REPOSITORY_ROOT,
) -> Replayed:
    """Run the entry's step on a copy of `start` (a journal whose pending CP-1 ticket expects the
    step), answering each call with the next recorded reply."""
    pinned = pool(entry)
    shutil.copytree(start, work / "journal")
    store = Execution(work / "journal")
    ticket = next(a for a in store.read().attempts if a.status == "pending").ticket_id
    queue = [Response(200, body) for body in replies(entry, repository)]
    sent: list[dict[str, Any]] = []

    def transport(request: Request) -> Response:
        sent.append(json.loads(request.body or b"{}"))
        if queue:
            return queue.pop(0)
        stop = STOP | {"model": entry["model"]["id"]}
        return Response(200, json.dumps(stop).encode())

    keys = work / "keys"
    keys.mkdir()
    ticks = iter(range(1_000_000))
    writer = AttemptWriter(work / "artifacts")
    result = run_tool_step(
        StepSpec(entry["step_id"], "transcript", ()),
        store=store,
        ticket_id=ticket,
        ledger=Ledger(work / "ledger.jsonl", Decimal(1000)),
        pool=pinned,
        seed=0,
        client=ChatClient(transport),
        writer=writer,
        key_path=make_rtf_key(keys),
        key_index=1,
        bytes_per_token=Decimal(entry["bytes_per_token"]),
        effort=StepEffort.of(entry["effort"]),
        rules=rules,
        monotonic=lambda: float(next(ticks)),
        sleep=lambda _: None,
    )
    return Replayed(
        result,
        [request_record(body) for body in sent],
        list(_tool_results(writer, pinned, result)),
        sent,
    )


def _without_added_tools(
    replayed: Replayed, added: list[str]
) -> tuple[list[dict[str, str]], str | None]:
    """The request records with the named added tools stripped, or the first call that does
    not carry each named tool exactly once (as a reason)."""
    records: list[dict[str, str]] = []
    for number, body in enumerate(replayed.bodies, 1):
        tools = body.get("tools", [])
        sent = [spec["function"]["name"] for spec in tools]
        for name in added:
            if sent.count(name) != 1:
                return [], (
                    f"call {number}: tools_added names {name}, which the request carries "
                    f"{sent.count(name)} times"
                )
        kept = [spec for spec in tools if spec["function"]["name"] not in added]
        records.append(request_record({**body, "tools": kept}))
    return records, None


def start_journal(entry: dict[str, Any], repository: Path, work: Path) -> Path | None:
    """The step's starting journal: the harness's (None when the artifacts are absent), or the
    synthetic CP-1 case built up to the step from the entry's accepted upstream payloads."""
    if entry["kind"] == "harness":
        path = repository / entry["start_journal"]
        return path if path.is_dir() else None
    return synthetic_start(work / "start", entry.get("upstream", {}))


def synthetic_start(work: Path, upstream: dict[str, str]) -> Path:
    """The synthetic CP-1 case's journal: CP-0 accepted, CP-1 begun, then each upstream payload
    entered (each must be accepted), so the pending ticket expects the entry's step."""
    seed, _, _ = cp1_case(work / "seed")
    review = seed.payload(seed.read().attempts[0].steps[0].payload_sha256)
    journal = Execution.create(work / "journal", seed.pack())
    assert not submit_cp0_review(journal, journal.begin("CP-0").ticket_id, review).issues
    ticket = journal.begin("CP-1").ticket_id
    for step_id, payload in upstream.items():
        entered = submit_model_payload(journal, ticket, step_id, payload).journal
        assert entered.steps[-1].status == "valid", entered.steps[-1].issues
    return work / "journal"


def check(entry: dict[str, Any], work: Path, repository: Path = REPOSITORY_ROOT) -> tuple[str, str]:
    """(status, reason) of one entry: `ok`, `skipped-artifacts-absent` or the first difference."""
    start = start_journal(entry, repository, work)
    if start is None:
        return SKIPPED, f"{entry['start_journal']} is not in this checkout"
    if entry["kind"] == "harness":
        directory = repository / entry["transcript"]
        for name, digest in entry["evidence_sha256"].items():
            if sha256((directory / name).read_bytes()) != digest:
                return "evidence-changed", f"{entry['transcript']}/{name} does not hash as recorded"
        if Execution(start).pack().content_hash() != entry["pack_sha256"]:
            return "evidence-changed", "the starting journal's pack does not hash as recorded"
    added = entry.get("tools_added")
    if added is not None and not entry.get("tools_added_by"):
        return "entry-invalid", "tools_added needs tools_added_by"
    plain = replay(entry, start, work / "plain", repository=repository)
    replayed = plain.record()
    if added is not None:
        stripped, problem = _without_added_tools(plain, added)
        if problem is not None:
            return "request-changed", problem
        replayed["requests"] = stripped
    expected = entry["expected"]
    system = entry.get("system_prompt", {})
    if len(replayed["requests"]) != len(expected["requests"]):
        return "outcome-changed", "the number of calls differs"
    calls = zip(replayed["requests"], expected["requests"], strict=True)
    for number, (now, then) in enumerate(calls, 1):
        if now["rest_sha256"] != then["rest_sha256"]:
            return "request-changed", f"call {number}: the conversation, tools or parameters"
        if system.get("recorded_sha256", then["system_sha256"]) != then["system_sha256"]:
            return (
                "request-changed",
                f"call {number}: the recorded system prompt is not system_prompt.recorded_sha256",
            )
        wanted = system.get("now_sha256", then["system_sha256"])
        if now["system_sha256"] != wanted:
            return "request-changed", f"call {number}: the system prompt (unnamed change)"
    for key in ("verdict", "submits", "tool_results_sha256", "cost_settled_usd"):
        if replayed[key] != expected[key]:
            return "outcome-changed", f"{key}: {replayed[key]!r} != {expected[key]!r}"
    ruled = replay(entry, start, work / "ruled", rules=ToolRules(), repository=repository).record()
    if ruled["submits"] != entry["rules"]["submits"]:
        return "rules-changed", f"{ruled['submits']!r} != {entry['rules']['submits']!r}"
    return OK, ""


def harness_entry(
    cell: Path,
    step_id: str,
    start: Path,
    work: Path,
    *,
    model: dict[str, Any],
    effort: str,
    repository: Path,
    changed_by: str | None = None,
    bytes_per_token: str = "3.0",
) -> dict[str, Any]:
    """Write-side helper: the entry for one recorded harness step (its expected outcome is the
    harness's own record: requests, tool log, submits, verdict, cost)."""
    directory = cell / step_id
    reply_files = sorted(p.name for p in directory.glob("call-*-response.json"))
    log = [json.loads(line) for line in (directory / TOOL_TRANSCRIPT).read_text().splitlines()]
    step = next(
        s
        for s in json.loads((cell / "metrics.json").read_text())["steps"]
        if s["step_id"] == step_id
    )
    requests = [
        request_record(json.loads((directory / f"call-{n:02d}-request.json").read_text()))
        for n in range(1, len(reply_files) + 1)
    ]
    entry: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "harness",
        "step_id": step_id,
        "model": model,
        "effort": effort,
        "bytes_per_token": bytes_per_token,
        "transcript": str(directory.relative_to(repository)),
        "start_journal": str(start.relative_to(repository)),
        "pack_sha256": Execution(start).pack().content_hash(),
        "reply_files": reply_files,
        "evidence_sha256": {
            name: sha256((directory / name).read_bytes())
            for name in [*reply_files, TOOL_TRANSCRIPT]
        },
        "provenance": {
            "harness": "devtools/hybrid_cp1.py",
            "batch_id": cell.parent.name,
            "cell": cell.name,
            "cohort": "openrouter-pool",
        },
        "expected": {
            "verdict": step["verdict"],
            "submits": [{"outcome": s["outcome"], "issues": s["issues"]} for s in step["submits"]],
            "requests": requests,
            "tool_results_sha256": [sha256(item["result"]) for item in log if "result" in item],
            "cost_settled_usd": step["cost_settled_usd"],
        },
    }
    plain = replay(entry, start, work / "plain", repository=repository)
    if changed_by is not None:
        entry["system_prompt"] = {
            "changed_by": changed_by,
            "recorded_sha256": requests[0]["system_sha256"],
            "now_sha256": plain.requests[0]["system_sha256"],
        }
    ruled = replay(entry, start, work / "ruled", rules=ToolRules(), repository=repository).record()
    entry["rules"] = {"checked": list(ToolRules().checked), "submits": ruled["submits"]}
    return entry


def write(entry: dict[str, Any], name: str, root: Path = TRANSCRIPT_ROOT) -> Path:
    target = root / entry["step_id"] / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return target
