# Execution journal

`deploy_vii.execution.Execution` is the local execution substrate. The `execution`
CLI provides trusted CP-0 review submission and ordered CP-1 stage submission.
The standalone `cp0` delivery command remains separate. Live model calls go through
the runner (`deploy_vii.live`, [live-runner.md](live-runner.md)); CP-1 final module
projection is pending. A model-supplied success flag is never a validator. Synthetic protocol tests do not qualify analytical judgments.

- `Execution.create(directory, pack)` starts a new store for a validated frozen
  pack. Use `load_pack` first when reading an on-disk prepared pack. Run identity,
  date, selected scope and method cannot change inside this execution.
- `begin(module_id)` resolves aliases, checks current selected dependencies and
  CP-0's source-readiness command, then reserves one attempt. Only one may be
  pending. The returned ticket contains exact pack/upstream hashes and, for the
  one permitted repair, the previous ticket and named validation issues. When
  CP-0's T8 `exact_command` for the consumer is not `Run <id>` it raises
  `NotAuthorized` (task 2.10), a `ValueError` subclass carrying the module id and
  the command texts found, so a caller can tell a CONDITIONAL or BLOCKED readiness
  judgment from a journal fault; every other refusal is a plain `ValueError`.
- `finish(ticket_id, module_json, validator)` retains the response before local
  validation. It checks identity, status, attempt, current input hashes and
  citations before calling the trusted Python validator. A validator exception
  leaves the response and ticket pending; resume with the same payload. A new
  response under the same ticket is rejected.
- Citations are checked by `readiness.citation_issues` here and in every module
  validator: exact source, hash and locator, and the quote as one contiguous
  substring of that span after the layout normalisation of `deploy_vii.quotes`
  (whitespace runs, curly quotes, dashes, soft hyphens; task 2.9; on the span side
  also hyphenated line wraps joined, `hyphen-wrap`, task 2.10). One issue per
  failing citation names the locator and the quote's first 60 characters.
- `interrupt(ticket_id, reason)` records the caller's explicit interruption. It
  preserves an already retained response and consumes that attempt. It does not
  stop or inspect a host process, reconcile provider billing or make a second call.
- The first failed attempt is rejected and inspectable; the second is blocked.
  Successful candidates become accepted or restricted by the degradation rules
  below. The count is per exact module/input set and
  survives store reopening and switching evidence away and back. Already settled
  inputs cannot be rerun just to obtain another model answer.
- `replace_pack(pack)` requires no pending attempt and stales all current heads.
  Accepted producer replacement invalidates transitive consumers. Old artifacts
  and attempts remain in immutable snapshots. Reverting to an earlier settled
  pack does not reset its budget; automatic old-result reactivation is not yet
  implemented.
- Degradation ([decision 0007](../decisions/0007-degradation-and-status-semantics.md)).
  Each dependency edge has a rule in `methodology.json` (`edge_rules`): `block`
  (the consumer cannot start) or `restricted` (it runs with an inherited limitation).
  Required producers default to `block`, optional ones and CP-5's analyst fan-in to
  `restricted`, with four explicit r14 overrides. A settled `blocked` head under a
  `restricted` edge is bound as an `Input` with `status: "blocked"` and its hash; an
  unrun, stale or rejected producer blocks every consumer. A module's own findings are
  `limitations`; those carried from inputs are `inherited_limitations`, shown by
  `view()` after the own findings. The settled status is `restricted` for own
  limitations, a blocked module anywhere up the bound input chain (found from the heads'
  structured input statuses, not limitation text) or a synthetic run, otherwise
  `accepted`, so Pass stays reachable downstream of an immaterial inherited note.
  Inherited limitations are displayed transitively (each consumer carries its
  restricted inputs' own and inherited lists), but only a blocked ancestor
  downgrades the status; other inherited text never does. A candidate must bind each
  input's hash and status exactly. CP-1 QA derives `module_status` from own findings.
- `view()` returns a cumulative accepted View. Stale and blocked heads expose
  status/limitations but no findings. `view(ticket_id)` returns a labelled
  candidate only when its input lineage and provenance remain current.

## Claim run text (decision 0005 MC-2)

`Claim.text` of every module is run text (`deploy_vii.prose`): literal text plus
references that Python resolves and spells. The model never writes a number.

- Grammar. `{<ref>}` or `{<ref>|<unit>}` is a figure; `[<ref>]` is a chip, drawn as a
  gap when `<ref>` names a gap. `<ref>` follows `contracts.Identifier`
  (`[A-Za-z0-9][A-Za-z0-9_.:-]*`, at most 160 characters) and names the module's own
  records: a `Fact.fact_id` (a table cell is a fact, so this is also the table-row
  reference) or a `Fact.calculation_id` that exactly one fact carries. A gap is an
  unsettled fact (`status` other than `known`); the page shows its report-wide `G#`.
  Braces and square brackets are reserved: one outside a well-formed reference is
  malformed, and the `Claim` contract refuses it.
- Labels. Outside references a numeric character must sit inside a label
  (`prose.LABELS`): periods (`FY2025`, `FY25`, `FY2025/26`, `Q2`, `H1`, `30 June 2026`,
  `June 30, 2026`, `2026-06-30`, a year `19xx`/`20xx`), filings (`10-K`, `10-Q`, `8-K`,
  `20-F`, `6-K`, `40-F`, `S-1`, `F-1`, with `/A`), instruments (a coupon followed by an
  instrument noun, as in `6.50% senior secured notes due 2032`; `2032s`;
  `Term Loan B-2`), sections (`Item 1A`, `Note 12`, `Section 4.03(a)`, `Exhibit 10.1`,
  `Rule 144A`) and ordinals or versions (`2nd`, `r14`, `v2.1`, `CP-1A`). The run's
  issuer name is also literal. Any other numeric token is a bare figure.
- Validation. `candidate_issues` adds `prose_issues(candidate, names=(issuer_name,))`:
  an unresolved reference, a bare figure, a figure that names a gap, a text or unsettled
  fact, a figure with neither a citation nor a calculation, a numeric fact used as a chip,
  or a unit token that is neither the fact's unit nor the unit Python shows
  (`report_view.figure_unit`) is an issue, so the attempt settles `rejected` (attempt 0)
  or `blocked` (the repair). The unit token is an expectation, never display text.
- Resolution. `report_view.resolve(text, prose.bind(facts), module_refs(index, module_id))`
  spells each figure with `fact_spelling` (the cell's number rule; exact text past the
  100-exponent bound) plus the amount's scale label, and marks provenance with the
  fact's report-wide id (`K#` before `C#`/`S#`, `G#` for gaps). It raises on any issue,
  so a stored module accepted before this rule cannot render a bare figure.
- Limits. The rule is lexical. A year label also admits a four-digit count in the year
  range ("2000 employees"), a section label admits any number after its word
  ("Note 750"), and spelled-out numbers ("twelve") are words. Semantic review of the
  prose remains required.
- CP-1 narrative prose uses the same label rule with no references (`narrative._prose`):
  its numbers and gaps are evidence parts. The projection writes each evidence part into
  the claim as `[<fact id>]` of its evidence-trace Evidence cell, which resolves to the
  `E#` label.

## Storage (`execution/5`)

```
<directory>/
  current                  pointer: hex SHA-256 of the current snapshot
  snapshots/<sha256>.json  small immutable snapshots, each naming its parent
  blobs/<sha256>           pack, payload, result and step-output blobs, each stored once
  .lock                    POSIX flock serialising transitions
```

- A snapshot holds the run identity (`run`), `pack_sha256`, the attempts and the heads,
  and nothing else of substance. An attempt carries `payload_sha256` and `result_sha256`;
  a step carries `payload_sha256` and `output_sha256`; a head is a small record (below).
  `parent` and `snapshot.content_hash()` cover only this snapshot, so the bytes written
  by a transition depend on the number of records, not on any pack, payload, result or
  output content.
- Four blob kinds, each named by the SHA-256 of its bytes (identical content is one blob):

  | Blob | Bytes (canonical form) | Read with | Checked |
  | --- | --- | --- | --- |
  | pack | `PreparedPack.model_dump_json()` UTF-8; its SHA-256 is `pack_sha256`, the hash bound as `Input("prepared-pack", ...)` | `pack(snapshot=None)` | hash; same `run` as the snapshot; bytes are exactly the canonical JSON |
  | payload | the response text, UTF-8 (module response or step response) | `payload(sha256)` | hash |
  | result | the settled `Module.model_dump_json()`, so `result_sha256 == module.content_hash()` (this is also the hash a consumer binds as an `Input`) | `result(sha256)` | hash; bytes are exactly the canonical module |
  | step output | the validator's output text, UTF-8 | `step_output(sha256)` | hash |

  The pack and module forms are deterministic (contract field order, Decimal strings),
  so hashes are stable across runs.
- A head is `Head(module_id, status, result_sha256, inputs, commands, notes)`. `status`
  and `notes` are the live state: staling sets `status: "stale"` and appends a note
  (`Input changed: ...` or `Prepared pack changed; ...`; an already-stale head keeps
  its first note) and never rewrites the result blob. `inputs` and `commands` (the CP-0
  T8 `exact_command` facts) duplicate fields of the blob so that no blob is loaded to
  resolve them. `Execution.head_module(head)`
  loads the blob, rejects it if its module id, inputs, commands or (for a live head)
  status differ from the head, and applies the status and notes, which reproduces the
  module the journal formerly kept inline (stale limitations included).
- What is loaded, and when. `current_inputs`, `invalidate`, `blocked_ancestors` and
  `begin` read only snapshot fields (no blob). `settle` loads the result blob of each
  directly bound upstream head, only when a candidate validates, to carry its
  limitations. `finish` and `submit_step` load the pack (after retaining the response)
  and, on resume, the retained payload. `view()` loads the pack and every head's
  result blob. `cp1_workflow` previews load the pack and the retained step payloads;
  recomputed step outputs are compared by hash, not loaded.
- Trust. Heads are trusted from the snapshot by `current_inputs`, `invalidate` and
  `blocked_ancestors`; only `head_module` (used by `view()` and `settle`) cross-checks a
  head against its blob, and a head blob must always be an `accepted`, `restricted` or
  `blocked` module, stale or not. The trust boundary is the snapshot and pointer pair,
  as before: a local hash chain detects changed bytes, not a rewritten snapshot.
- Inline text that remains in a snapshot is bounded by one cap: at most 20 lines of at
  most 300 characters, then a line counting the rest (`bounded_issues`; a longer line
  ends in `…`). It applies to `Attempt.issues` and the `repair_issues` copy of them, to
  `StepSubmission.issues`, and (300 characters, marker included) to `Attempt.interruption`.
  Schema errors of a malformed response are `loc: message` lines with no input value or
  URL, and pass through the same cap; citation and validator findings may quote caller
  text (a locator, a field name) and are cut by it. The cap hides lines beyond the
  twentieth from the stored record; the response itself is kept whole as a payload blob,
  so schema and citation findings can be re-derived from it, but dropped validator and
  step-validator lines are not recoverable without rerunning the validator, and a long
  interruption reason survives only in its 300-character form.
  Each attempt record also repeats its bound `inputs` (a few hundred bytes of hashes), so
  bytes per transition still grow by one such record per attempt, and by nothing else.
- Compatibility. A store written by the first `execution/5` commit (9a3f0c7: inline
  results, step outputs and head modules) is not supported and the schema string was
  not bumped, because `execution/5` is unreleased and no such store exists outside test
  fixtures. `execution/1` to `execution/4` stores are rejected with an explicit message.
- Every reader reads the blob, checks its SHA-256 against the name it was asked for, and
  rejects a missing or mismatching blob with `ValueError`, never an empty value.
  `read()` verifies the snapshot against the pointer and its schema but does not read
  blobs, so a bad blob is reported when it is used.
- Writes are temp file, fsync, rename. Writing bytes whose hash already exists is a
  no-op; a different file at an existing hash path is corruption and is refused, never
  overwritten. A blob is written before the snapshot that references it, so a crash
  leaves at worst an unreferenced blob or snapshot; never delete one as part of
  automatic recovery. The pointer is replaced atomically after the snapshot is durable.
- Transitions are serialised by POSIX file locking. This is tested on the macOS host
  and the configured POSIX workflow, not Windows. Directory fsync and power-loss
  durability are not claimed. No compaction or garbage collection is enabled.
  Local hashes detect changed bytes, not an adversary rewriting every hash and pointer.
- CLI: commands that print an attempt (`begin`, `interrupt`, `cp0-submit`, `cp1-submit`)
  add a `result` key read from the result blob for display; `create` and `status` print
  the snapshot itself, which holds hashes. `step-output` prints the output blob.
- `tests/product/test_execution.py::TransitionMeter` reports the bytes written per
  transition from a directory listing (new or changed files since its previous call).

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

CP-MODEL's artifact (decision 0006 DC-5) is the HTML Model destination plus the calculation
JSON of the accepted CP-1 financial model; the r14 XLSX workbook export is deferred and
recorded so in `docs/methodology/r14-coverage.json`. CP-MODEL requires accepted CP-1 (a
blocked CP-1 blocks it) and, when selected, is an analyst input to CP-5 (restricted if
blocked). No Pathway preset requests it, so it runs only when requested.

New stores use `execution/5` (blob storage above), embedding `module/5` table layouts,
status-carrying inputs, stated comparisons and calculation status. Existing
`execution/1` to `execution/4` snapshots are rejected with an explicit message
rather than being silently rewritten. An `execution/5` store embedding `module/4` or
older is rejected inside Module validation. Migration is not implemented;
retain old stores and use a new execution directory for this version. This is an
artifact format boundary, not permission to reset a live provider budget.

`interface-preview` extends the statement candidate with Model interface registers
and canonical table transport checks; it does not settle the ticket. See
[interface scope](model-interface.md). The source-audit coupon-unit correction now
requires `canonical-audit/4`; older financial stage outputs embedding `/3` must be
regenerated in a new attempt/directory. Preserve earlier stores and spend records.

`register-preview` requires all four valid CP-1 stages and recomputes each prefix
against one snapshot before writing. Exact retained output and current upstream
hashes must match. The candidate contains all canonical register table IDs with
context-aware readiness, preserving the journal and its pending ticket. See
[register projection and receipt](canonical-tables.md). Findings and evidence trace
are now projected with coverage; the final envelope, QA and
final acceptance remain pending.
