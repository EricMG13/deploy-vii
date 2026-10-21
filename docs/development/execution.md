# Execution journal

`deploy_vii.execution.Execution` is the local execution substrate. The `execution`
CLI provides trusted CP-0 review submission and ordered CP-1 stage submission.
The standalone `cp0` delivery command remains separate. Live model invocation and
CP-1 final module projection are pending; a model-supplied success flag is never
a validator. Synthetic protocol tests do not qualify analytical judgments.

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

## Ordered review submissions

`submit_step` is an internal API: sequence and validator are trusted Python module
implementation arguments, never model-controlled choices. It retains raw UTF-8
response text before invoking validation. Every step binds the current pack and
upstream heads, plus every prior completed submission hash (including its retained
output). Runtime exceptions leave the same response pending. A changed response
requires explicit interruption, consuming the attempt. Invalid submissions consume
the module's existing one-repair allowance; stages do not get separate budgets.
A blocked stage may retain a diagnostic report. On failure, the module payload
is a Python-built empty candidate; the actual raw response remains in its step.
Finishing a module while a stage response awaits validation is disallowed;
explicit interruption remains available.

`submit_cp0_review` validates source readiness and constructs the candidate in
Python, then promotes only that exact candidate. It resumes a crash between stage
validation and module promotion without another review or attempt. No usable,
identity-confirmed source produces rejection, then blocking if repair also fails.

`submit_cp1_step` fixes the sequence:

1. `source_context`: validate source/entity/event review and retain its report;
   no usable assessed financial source stops extraction.
2. `financials`: require `FinancialSubmission.context_step_sha256` to equal the
   completed source submission hash; validate financial/context/definition bindings
   and build `FinancialStage` with narrative inputs and historical Model output.
   Calculation-gate failures retain `model: null` and explicit issues.
3. `narrative`: validate `NarrativeReview` against the retained narrative inputs,
   then build the selected consumers' `DownstreamInputs`.
4. `readiness`: validate `DownstreamReview` against those exact inputs, then retain
   the canonical downstream report with historical Model readiness distinct.

The final step leaves the ticket pending. It does not accept CP-1 or CP-MODEL.
Source and constructed statement previews are available through `statement-preview`;
see [table projection](report-tables.md). Canonical Markdown, complete Workbench
projection, final module validation and promotion remain pending. Historical Model
calculations are not the CP-MODEL workbook export. Every analytical qualification remains `unrun`.

New stores use `execution/4`, embedding `module/3` table layouts, stated comparisons
and calculation status. Existing explicit `execution/1`, `execution/2` and
`execution/3` snapshots fail schema validation
rather than being silently rewritten. Migration is not implemented;
retain old stores and use a new execution directory for this version. This is an
artifact format boundary, not permission to reset a live provider budget.

`interface-preview` extends the statement candidate with Model interface registers
and canonical table transport checks; it does not settle the ticket. See
[interface scope](model-interface.md). The source-audit coupon-unit correction now
requires `canonical-audit/4`; older financial stage outputs embedding `/3` must be
regenerated in a new attempt/directory. Preserve earlier stores and spend records.
