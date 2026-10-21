# M5 content-addressed journal storage — scoped brief

> **For the worker:** one `dv-sensitive` owner in an isolated worktree cut from the M4 lane
> head (M4 and M5 both edit `execution.py`), test-first. Local commits only; no push, no PR,
> no subagents. The coordinator runs the 5.2 measurement.

**Task ID:** `dvii-impl-m5-journal-storage`. **Base:** `claude/m4-lane` head (the coordinator
names the SHA at dispatch). **Plan:** `docs/development/tasks/implementation/plan.md` §M5
(review W4). **Editable paths:** `src/deploy_vii/execution.py`, `tests/product/test_execution.py`,
`docs/development/execution.md`, `docs/development/tasks/implementation/m5-journal-storage-brief.md`
(copy) and `m5-journal-storage-review.md`. Anything else only if a test forces it; say so.

**Required reads:** `CLAUDE.md`; plan §M5 and "Global constraints"; review W4
(`docs/development/reviews/2026-10-21-adversarial-review.md:249-267`); `execution.py` in full
(`ExecutionSnapshot`, `read` ~`:257`, `_write` ~`:266-287`, `content_hash` uses at `:314,:349,:372`,
`current_inputs` `:111-118`, `begin`/`finish`/`submit_step`/`_save_finished`);
`docs/development/execution.md`; the M4 result note `docs/development/tasks/implementation/m4-degradation-review.md`.

## Goal

Bytes written per journal transition stop growing with the number of attempts and with pack
size: the prepared pack and every attempt payload are stored once as content-addressed blobs
(`blobs/<sha256>`), snapshots reference them by hash, and `parent` hashes cover only the
small snapshot.

## Global constraints

- Hash-bound integrity is unchanged in meaning: a snapshot still commits to the exact pack
  and payload bytes (through their SHA-256), `read()` still rejects a tampered pointer or
  snapshot, and a missing or mismatching blob is an integrity error, never silently empty.
- Schema `execution/5`; older stores are rejected with a clear message (current policy).
  Nothing migrates silently.
- Atomicity: blob writes are write-temp → fsync → rename, idempotent on re-write of the same
  bytes (same hash), and refuse a different payload at an existing hash path.
- Single-writer semantics, the pending-ticket rule, the attempt budget and `invalidate` are
  untouched. `test_two_writers_cannot_reserve_two_initial_attempts` and
  `test_concurrent_finish_publishes_exactly_one_result` keep passing.
- The pack hash used in `Input("prepared-pack", …)` is the pack blob's SHA-256 of its
  canonical JSON (state the canonical form; it must be stable across runs).
- No stub or fake value; no catch-all. `make product-check` and `make check` exit 0; never
  loosen a gate. Commit messages end with a blank line then
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Task (5.1)

**Interfaces:** `ExecutionSnapshot` fields `pack_sha256: Hash` (replacing the inline
`PreparedPack`) and, per attempt, `payload_sha256: Hash | None` and per step
`payload_sha256` (replacing inline `payload: str`); `Execution.pack() -> PreparedPack` and
`Execution.payload(sha256) -> str` read blobs with hash verification; `read()` validates the
snapshot hash as today; `snapshot.content_hash()` is now over the small snapshot only.
Public call signatures (`create`, `begin`, `finish`, `submit_step`, `interrupt`, `replace_pack`,
`view`, `current_inputs`) are unchanged; callers that read `snapshot.pack` or
`attempt.payload` (grep `src/` and `tests/`: `cp0_workflow.py`, `cp1_workflow.py`, previews,
`execution_cli.py`) switch to the accessors.

- [ ] Step 1, failing tests: `test_blob_store_writes_pack_and_payload_once` (two attempts with
  the same payload bytes → one blob; the snapshot files do not contain the pack text);
  `test_snapshot_bytes_do_not_grow_with_attempts` (bytes of the snapshot written at
  transition *n* are within a constant of transition 1 while attempts accumulate — assert a
  bound derived from the fixture, not a magic number: e.g. `size(n=5) - size(n=1) <= 5 *
  len(one attempt record without payload)`); `test_missing_or_tampered_blob_is_rejected`;
  `test_execution_4_store_is_rejected_with_message`; `test_content_hash_is_over_snapshot_only`
  (replacing the pack blob bytes on disk with a same-hash copy changes nothing; a different
  pack changes `pack_sha256`). Update existing tests touching `snapshot.pack`/`payload`.
- [ ] Step 2: run `uv run --locked pytest tests/product/test_execution.py -q`; confirm failures.
- [ ] Step 3: implement. Measure as you go: a helper `transition_bytes(directory) -> int`
  (sum of bytes written since the last call, from a listing of new/changed files) used by the
  tests and by the coordinator's measurement script; keep it in `execution.py` only if it is
  small, else in the test module.
- [ ] Step 4: `uv run --locked pytest tests/product/test_execution.py tests/product/test_workflow.py
  tests/product/test_interface_view.py tests/product/test_register_view.py tests/product/test_report_tables.py -q`,
  then `make product-check`, `make check`.
- [ ] Step 5: `confidence-review` (no args); `rewrite-tournament` no-argument post-edit mode on
  `_write` and `read` only (artifact state). Record outcomes.
- [ ] Step 6: docs: `docs/development/execution.md` storage section (blob layout, schema
  `execution/5`, integrity rules). Commit `Store the pack and payloads as content-addressed blobs (execution/5)`.

## Measurement (5.2, coordinator)

The coordinator records bytes written and wall time per `begin`/`submit_step`/`finish` on
the hash-pinned Caesars pack before (M4 lane head) and after (this head) in
`docs/development/tasks/implementation/m5-journal-storage-review.md` (the worker leaves a
"Measurement" placeholder section that the coordinator fills).

## Report

`.superpowers/sdd/plan/reports/m5-report.md` inside your worktree (worktree/branch; base..head;
commits; changed paths; test commands with exit codes and counts; review findings and fixes;
tournament outcome; deviations; final line `Not verified:`). Return only: status, worktree and
branch, base..head, one-line test summary, concerns.
