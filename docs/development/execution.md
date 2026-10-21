# Execution journal — internal Python API

`deploy_vii.execution.Execution` is the local execution substrate. It is not yet
wired to the live model runner or the standalone `cp0` CLI. Those adapters must
supply their actual module-specific validator; a model-supplied success flag is
never a validator. The synthetic engine tests use explicit test validators and
do not implement or qualify CP-1 or any other financial module.

- `Execution.create(directory, pack)` starts a new store for a validated frozen
  pack. Use `load_pack` first when reading an on-disk prepared pack. Run identity,
  date, selected scope and method cannot change inside this execution.
- `begin(module_id)` resolves aliases, checks current selected dependencies and
  CP-0's source-readiness command, then reserves one attempt. Only one may be
  pending. The returned ticket contains exact pack/upstream hashes and, for the
  one permitted repair, the previous ticket and named validation issues.
- `finish(ticket_id, module_json, validator)` retains the response before local
  validation. It checks identity, status, attempt, current input hashes and
  citations before calling the trusted Python validator. A validator exception
  leaves the response and ticket pending; resume with the same payload. A new
  response under the same ticket is rejected.
- `interrupt(ticket_id, reason)` records the caller's explicit interruption. It
  preserves an already retained response and consumes that attempt. It does not
  stop or inspect a host process, reconcile provider billing or make a second call.
- The first failed attempt is rejected and inspectable; the second is blocked.
  Successful candidates become accepted or restricted, carrying upstream and
  synthetic-case limitations. The count is per exact module/input set and
  survives store reopening and switching evidence away and back. Already settled
  inputs cannot be rerun just to obtain another model answer.
- `replace_pack(pack)` requires no pending attempt and stales all current heads.
  Accepted producer replacement invalidates transitive consumers. Old artifacts
  and attempts remain in immutable snapshots. Reverting to an earlier settled
  pack does not reset its budget; automatic old-result reactivation is not yet
  implemented.
- `view()` returns a cumulative accepted View. Stale and blocked heads expose
  status/limitations but no findings. `view(ticket_id)` returns a labelled
  candidate only when its input lineage and provenance remain current.

Snapshots are content-addressed JSON, with a parent hash and atomic current
pointer. POSIX file locking serializes transitions; raw files and pointer writes
are fsynced. This is tested on the macOS host and the configured POSIX workflow,
not Windows. Directory fsync/power-loss durability is not claimed. A failed
pointer publication can leave an unreferenced snapshot; never delete it as part
of automatic recovery. Full snapshots retain the pack and attempt history, trading
storage for simple recovery. No compaction or garbage collection is enabled.
Local hashes detect changed bytes, not an adversary rewriting every hash/pointer.

Analytical qualification, native-host qualification, model routing, provider
request tracking and the US$50 OpenRouter cap remain separate pending adapters.
Neither the journal nor its browser tests promote those qualification states.
