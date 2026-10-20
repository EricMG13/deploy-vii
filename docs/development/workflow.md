# Observational development workflow

Run from the project root with the committed environment. These commands manage
development context only; they never control the product, stop a process, reset a
context window or transfer workspace ownership.

```sh
uv run python -m devtools.workflow init --context docs/development/context-example.json
uv run python -m devtools.workflow checkpoint --context docs/development/context-example.json
uv run python -m devtools.workflow handoff --context docs/development/context-example.json
uv run python -m devtools.workflow validate --context docs/development/context-example.json
uv run python -m devtools.workflow import-events --host codex --session actual-session-id --source /absolute/path/to/supplied.jsonl
uv run python -m devtools.workflow report
```

The example is synthetic; copy it into ignored local storage and fill in actual
task state. Use `--repo` and `--store` before the subcommand for another checkout
or a task-specific store. The default is `artifacts/context-policy/workflow`.
Stores must be Git-ignored inside the checkout and contain no tracked files.
Raw telemetry stays under the store, including original bytes and SHA-256.

Checkpoints retain the complete submitted context and a parent hash. HEAD, index
entries, tracked and nonignored untracked files, modes, symlink targets and
explicit input files are fingerprinted. List relevant ignored/external evidence
under `sources`. Two matching scans detect ordinary concurrent changes; they do
not lock the worktree or guarantee a filesystem snapshot. Git submodules and
directory inputs require explicit file inputs and are not silently accepted.

Records are written atomically; the local update lock protects the evidence
store only. `handoff` is a checkpoint with a handoff label. It always says
`NOT_READY` for ownership transfer: use the [handoff template](handoff-template.md)
and actual host controls to reconcile writers and assign a successor.

Validation compares the record with the live tree and a separately supplied
current context. It detects drift, missing explicit inputs, pauses, exhausted or
unknown budgets, pending operations and unverified fresh-context claims. It does
not prove the truth of a submitted fact, review or authorization. Checkpointing
cannot change task/goal/owner, erase constraints/corrections, raise a budget cap,
or decrease consumed usage. Append superseding corrections. Clearing a pause
requires explicit `resume_authorization` evidence in the submitted context;
this is a recorded assertion, not authentication of the human instruction.

Supported telemetry inputs are Codex rollout JSONL `event_msg/token_count` with
`info.total_token_usage`, and Claude JSONL `assistant.message` with `id` and
`usage`. Other formats/events are counted as unrecognized; malformed lines are
retained and reported. Imports require an explicit host/session and file path;
there is no log discovery, tailer or host hook.

Codex cumulative counters and Claude request counters remain separate series.
Duplicate cumulative vectors and duplicate message IDs are not counted twice;
conflicting usage for a request ID is excluded and reported. Cached/reasoning
subtotals are never added to token totals. No cumulative sum or token-window
occupancy is inferred. Cost, latency and occupancy remain null with reasons for
these formats. Summary fields exclude prompts, response prose and credentials.
Raw evidence and manifest hashes are verified when reporting; hashes establish
integrity against accidental mutation, not authenticity against a malicious writer.

Exit codes: `0` successful observation; `1` preflight findings, malformed telemetry
lines or conflicts; `2` invalid input/storage/Git operation. A zero exit never
means ownership transfer, financial qualification or permission to resume.

`make dev-check` runs lint, formatting, strict typing and the executable context
scenarios. `make test` remains reserved for product tests.
