# M5 content-addressed journal storage: result note

Date: 21 October 2026. Task `dvii-impl-m5-journal-storage` (plan v2 M5; review W4).
Brief: [m5-journal-storage-brief.md](m5-journal-storage-brief.md).

## What changed

- Schema `execution/5`. `ExecutionSnapshot` holds `run` (identity and scope, inline),
  `pack_sha256`, attempts and heads. `Attempt.payload_sha256` and
  `StepSubmission.payload_sha256` replace the inline text. The pack and every payload
  are stored once as `blobs/<sha256>`; `parent` and `content_hash()` cover only the
  small snapshot.
- `Execution.pack(snapshot=None)` and `Execution.payload(sha256)` read blobs and verify
  them (missing, mismatching or non-canonical blobs raise `ValueError`). `read()`
  verifies the snapshot hash and schema and rejects `execution/1` to `/4` with a
  message naming the version and the new-directory remedy.
- Pack hash: `Input("prepared-pack", ...)` binds the SHA-256 of the pack blob, which is
  the canonical `PreparedPack.model_dump_json()` bytes (same value as before).
- Writes use one `_atomic_write` (temp, fsync, rename) for snapshots, blobs and the
  pointer; `_put_once` is idempotent for identical bytes and refuses a different file
  at an existing hash path.
- `candidate_issues` and `settle` take a keyword-only `pack`; `cp0_workflow`,
  `cp1_workflow` read payloads through the store. Public signatures of `create`,
  `begin`, `finish`, `submit_step`, `interrupt`, `replace_pack`, `view` and
  `current_inputs` are unchanged.
- Pre-step (M4 review): `blocked_ancestors` tracks visited modules; pinning tests for
  restricted-over-blocked staling and omitted input status; docs clarified.

## Deviations

- `run: Run` is stored inline in the snapshot in addition to `pack_sha256`, because
  `current_inputs(snapshot, module_id)` must keep its signature and needs the selected
  modules without reading the pack. `pack()` rejects a blob whose run differs.
- Fix round 1 (coordinator ruling): the attempt `result` and the step `output` are blobs
  too (`result_sha256`, `output_sha256`), and `heads` became `Head` records (hash of the
  settled module blob, `inputs`, CP-0 `commands`, live `status`, staleness `notes`) so
  that no snapshot field holds module content. `current_inputs` keeps its signature by
  reading `commands` from the head. `invalidate` now works on heads, `settle` returns
  `(attempt, result)` and takes a `load` callable for upstream modules, and the CLI adds
  the settled module to the attempt JSON it prints. Details of what is loaded when are in
  docs/development/execution.md.

- Fix round 2 (re-review): schema errors of a malformed response are stored as at most 20
  `loc: message` lines of at most 300 characters (no input value, no URL); `replace_pack`
  no longer adds a second note to an already-stale head; `head_module` requires a settled
  blob status for stale heads too. Residual inline text (validator issues, `repair_issues`,
  `interruption`) is described in docs/development/execution.md.

## Reviews

- confidence-review (inline): no confirmed defect. Seven mutants of the integrity paths
  (no blob hash check, overwrite of a corrupt blob, no schema check, no canonical-pack
  check, missing blob read as empty, no hash-format check, retained payload unchecked)
  were each killed by the focused tests. Coverage gaps found in the new guards were
  closed (`test_pack_blob_must_be_canonical_and_match_the_snapshot_run`,
  `test_settle_refuses_a_payload_the_attempt_does_not_reference`).
- Fix round 2: rewrite-tournament (inline) on `settle`, `head_module`, `invalidate`:
  `settle` and `invalidate` incumbents hold; the `head_module` status condition was
  simplified (`is_settled` and `head.status not in ("stale", module.status)`), same
  tests pass.
- rewrite-tournament on `_write` and `read` (no sub-agents allowed here, run inline):
  `read` incumbent holds (a byte-prefix schema probe would be faster but brittle; the
  second JSON parse is small). `_write` readability rewrite adopted: the pointer write
  reuses `_atomic_write` instead of a second hand-rolled temp/fsync/rename block.

## Evidence

Focused: `pytest tests/product/test_execution.py test_workflow.py test_interface_view.py
test_register_view.py test_report_tables.py` pass. `make product-check` and `make check`
exit 0 (see the report for the final run).

## Measurement (coordinator)

To be filled by the coordinator: bytes written and wall time per `begin`, `submit_step`
and `finish` on the hash-pinned Caesars pack, before (M4 lane head `bc9328c`) and after
(this head). Helper: `TransitionMeter` in `tests/product/test_execution.py`
(`from tests.product.test_execution import TransitionMeter`; call `meter()` after each
transition for the bytes of new or changed files since its previous call).

## Not verified

Behaviour on a real Caesars pack and on stores over the size of the test fixtures;
Windows or non-POSIX filesystems; power-loss durability (no directory fsync); a concurrent
reader during `create`; models run (none invoked); the wall-time effect of the extra blob
reads and the second snapshot parse.
