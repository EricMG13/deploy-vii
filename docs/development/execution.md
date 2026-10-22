# Execution journal

`deploy_vii.execution.Execution` is the local execution substrate. The `execution`
CLI provides trusted CP-0 review submission and ordered CP-1 stage submission.
The standalone `cp0` delivery command remains separate. Live model calls go through
the runner (`deploy_vii.live`, [live-runner.md](live-runner.md)); CP-1 is settled by
promotion (below, task 6.4). A model-supplied success flag is never a validator. Synthetic protocol tests do not qualify analytical judgments.

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
  What counts as an own finding is the module's rule. For CP-1A (task 7.2, fix round 1), own
  limitations are only the model's `gaps` rows and an empty required register (company,
  source classification, credit translation, consumers). Validator defects reject before
  anything settles. An empty register for a fact class the filing may legitimately lack
  (acquisitions, behaviour flags, events, conflicts and so on) is one `not_applicable` row, not
  a limitation. An Insufficient Information row keeps its limitation in its own register. A
  CP-1A that fills only its required registers therefore settles `accepted`
  ([business context](business-context.md)).
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
  `20-F`, `6-K`, `40-F`, `S-1`, `F-1`, with `/A`; an SEC file number such as `001-36629`;
  `Regulation 14A`), instruments (a coupon followed by an instrument noun, as in
  `6.50% senior secured notes due 2032`; `2032s`; `Term Loan B-2`), sections (`Item 1A`,
  `Note 12`, `Section 4.03(a)`, `Exhibit 10.1`, `Rule 144A`; plural `Items` with ranges
  and lists, as in `Items 10-14`, `Items 7, 7A, 8`, `Items 7/7A`; page locators `page 16`,
  `pages 16-18`, `195-page`), pack-coverage counts (`195 of 195`, `195 pages`,
  `195 located spans`) and ordinals or versions (`2nd`, `r14`, `v2.1`, `CP-1A`). The
  run's issuer name is also literal. Coverage counts are labels because they describe the
  Source Pack's structure (how much of it was read), not the issuer; they are not analytic
  figures. The boundary: a duration (`120 days`), a count in any other shape
  (`195 located`, `1,200`) and every other numeric token are bare figures.
- Validation. `candidate_issues` adds `prose_issues(candidate, names=(issuer_name,))`:
  an unresolved reference, a bare figure, a figure that names a gap, a text or unsettled
  fact, a figure with neither a citation nor a calculation, a numeric fact used as a chip,
  or a unit token that is neither the fact's unit nor the unit Python shows
  (`report_view.figure_unit`) is an issue, so the attempt settles `rejected` (attempt 0)
  or `blocked` (the repair). The unit token is an expectation, never display text.
- Resolution. `report_view.resolve(text, prose.bind(facts), module_refs(index, module_id))`
  spells each figure with `fact_spelling` (the cell's number rule; exact text past the
  100-exponent bound) plus the amount's scale label, and marks provenance with the
  fact's report-wide id (`K#` before `C#`/`S#`, `G#` for gaps). It raises on any issue.
  That raise is a deliberate backstop: the main path settles a bad claim `rejected` through
  `candidate_issues` before it can be accepted, and the standalone `deliver_cp0` path, which
  does not use the journal, checks `prose_issues` first and publishes a `rejected` delivery
  (task 6.4: `rejected.json` with the issues, a candidate page showing CP-0 rejected with no
  findings, receipt `status: rejected`, no accepted view or page) instead of raising at
  render. Stored modules: a module
  accepted before this rule whose claims carry free figures no longer renders; a stored
  `[E1]`-style token parses as a chip and fails at render as an unresolved reference; a
  stored `[see note]` (not an identifier) fails when the module is parsed, as malformed.
- Limits. The rule is lexical. A year label also admits a four-digit count in the year
  range ("2000 employees"), a section or page label admits any number after its word
  ("Note 750", "page 750"), an `N of N` count admits any such pair ("2 of 3"), and
  spelled-out numbers ("twelve") are words. Semantic review of the
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
- `Head.qualification` (task 6.4) holds the plan's four statuses of the settled artifact
  (`implementation`, `analytical_qualification`, `rendering_acceptance`,
  `native_host_qualification`) where a promotion recorded them; CP-1 promotion records
  `implemented` and three `unrun`. `implemented` means the artifact passed every implemented
  structural gate, not the module's coverage-map row. A blocked result never carries them.
  When absent the key is omitted from the JSON, so every head written before it keeps its
  bytes and snapshot hashes; `execution/5` is unchanged and nothing is migrated.
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
- Inline text that remains in a snapshot is bounded: at most 20 lines of at most 600
  characters, then a line counting the rest (`bounded_issues`; a longer line ends in `…`).
  It applies to `Attempt.issues` and the `repair_issues` copy of them and to
  `StepSubmission.issues`; `Attempt.interruption` keeps 300 characters, marker included.
  The line cap was 300 until task 7.0, which raised it so a quote mismatch (a 200-character
  quoted fragment and the clause saying why it failed) reaches the REPAIR prompt whole.
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
requires explicit interruption, consuming the attempt. Each of CP-1's four model
steps (`WITHIN_ATTEMPT_REPAIR`: `source_context`, `financials`, `narrative`,
`readiness`) may be repaired once within its attempt (task 7.0g, decision 0008 MC-7
item 2): its first invalid submission moves to `Attempt.step_repairs` (the retained
invalid try, payload hash and issues, in order) and the attempt stays pending, with
no settlement and no head; the next submission of the same step is its repair, and
no later step may be submitted before it. `steps` keeps meaning the retained steps in
module order, so positional readers and the module's content hash never see the
repaired try, and an empty `step_repairs` is omitted from the JSON (stored
`execution/5` snapshots keep their bytes; no schema change). A second invalid
submission of the step, an invalid submission of any other step (CP-0, the `quality`
promotion step) or an interruption finishes the attempt and consumes the module's
one-repair allowance as before. Bound: two tries per step per attempt, two attempts
per input set; a third try of a step is refused before any write, and the contract
refuses a `step_repairs` entry that is not an invalid try with issues, or a second
entry for one step.
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

The final step leaves the ticket pending. It does not accept CP-1 or CP-MODEL;
promotion (below) does. Source and constructed statement previews are available through
`statement-preview`; see [table projection](report-tables.md). The accepted CP-1
envelope renders as the Front Page through `render` (task 6.5, below). Historical Model
calculations are not the CP-MODEL
workbook export. Every analytical qualification remains `unrun`.

### CP-1 promotion (task 6.4)

`promote_cp1(store, ticket_id, review_json)` (CLI `cp1-promote --ticket T --review FILE`)
retains a `QualityReview` (judgments only, decision 0008: materiality, lineage within each
ceiling, findings) as a fifth step, `quality`, of the same attempt and repair budget
(`CP1_PROMOTION`), then settles CP-1 with `finish`. The QA inputs to bind a review to are
printed by `cp1-quality-inputs --ticket T`. CP-1 is promoted only when every condition holds:

1. CP-0 authorised it: CP-0's T8 `exact_command` for CP-1 is `Run CP-1` (`current_inputs`
   raises `NotAuthorized` before anything is retained otherwise);
2. the module is accepted: the four stages are valid and each recomputes to its retained
   output, and the candidate passes `candidate_issues` and equals its recomputation;
3. the QA lineage ceilings hold (6.3): the review binds the current QA inputs, assesses every
   claim and evidence reference once and upgrades none; QA is not `Blocked`;
4. prose runs resolve (6.2): every claim resolves (the envelope writer and `prose_issues`);
5. the handoff verifies: the register envelope's `canonical-handoff` slot is present and the
   promoted envelope (with QA and the journal inputs) round-trips.

A failed condition makes the `quality` step invalid with its issues, so the attempt settles
`rejected` (attempt 0) or `blocked` (the repair), by status rather than by exception; a
Python exception (a retained stage that no longer recomputes) leaves the step pending. A
passing candidate is the registers' module bound to the attempt's journal inputs, without the
register-candidate note and, unless QA passed, with the own limitation
`CP-1 QA <status>: confidence <score> (<band>)`. Promotion adds no other limitation, so
`accepted` stays reachable. Settlement then follows the M4 rules (decision 0007): own
limitations, a blocked ancestor or a synthetic run make it `restricted`, otherwise
`accepted`. The register projection's own subartifact notes are own limitations, so the
fixture CP-1 settles `restricted`. The head records the four statuses. A crash between the step and the
settlement resumes from the retained valid step (the same review), as for CP-0. The retained
step output is `CP1Handoff` (`cp1-handoff/1`: registers hash, QA report, gap-register
limitations, candidate, envelope and sidecar hashes). `envelope --module CP-1 --output DIR`
exports the promoted head's envelope ([canonical envelope](canonical-tables.md)).

A data-driven QA `Blocked` (for example a blocked narrative) is refused like any other failed
condition, so it consumes the attempt and its repair before CP-1 settles `blocked`; a direct
`blocked` settlement of a valid but QA-Blocked candidate would change the M4 settlement rule
and is not implemented.

### CP-1A promotion (task 7.2)

CP-1A has one step, `business_context` (`business_context.CP1A_STEPS`), passed to
`submit_step` by `submit_cp1a_step` like CP-0's `source_readiness`; `execution/5` and `module/5`
are unchanged. Promotion is the accepted step, then the Python candidate
(`cp1a_module(business_context(...))`) settled by `finish` when it equals the candidate trusted
validation rebuilds: the step validator (`validate_business_context`: citations, run text,
semantic rules, prohibited conclusions, consumers) has no issue, every claim's run text resolves
(`candidate_issues`) and the composed registers pass the four `cp1a.*` rules. Settlement follows
the M4 rules, so the fixture's own gaps make it `restricted`; the head records `implemented` and
three `unrun` statuses (`business_context.PROMOTED`), as 6.4 does for CP-1. CP-1A's registry
edge is CP-0 alone. A settled CP-1 is bound as a context input when present
(`execution.CONTEXT_PRODUCERS`): `current_inputs` adds the CP-1 head (accepted or restricted;
never required, a blocked or stale CP-1 is left out) after the required upstreams, so the CP-1
figures CP-1A text references are lineage, CP-1A goes stale when CP-1 is rerun, and a CP-1
settled after CP-1A changes the input set, which allows a CP-1A rerun with figures. Like any
bound input, CP-1's limitations then show as CP-1A's inherited limitations (shown, not
penalised). The
referenced CP-1 facts are copied into CP-1A's `cp1_references` table. `deliver_cp1a` publishes
a standalone delivery like `deliver_cp0` (receipt `cp1a-delivery/1`; a submission with any
validator issue publishes `rejected` with those issues). It takes no CP-1 facts: only the
journal binds CP-1, so a standalone delivery cannot record a figure without its lineage.
CP-1A settled before CP-1 binds nothing of CP-1 and stays current when CP-1 settles later;
`begin("CP-1A")` then opens a new input set with CP-1 as context. A CP-1 finish stales a
CP-1A that bound it (`invalidate`). Through the public journal that state needs an upstream
change, because a settled CP-1 is not rerun on unchanged inputs.

CP-MODEL's artifact (decision 0006 DC-5) is the HTML Model destination plus the calculation
JSON of the accepted CP-1 financial model; the r14 XLSX workbook export is deferred and
recorded so in `docs/methodology/r14-coverage.json`. CP-MODEL requires accepted CP-1 (a
blocked CP-1 blocks it) and, when selected, is an analyst input to CP-5 (restricted if
blocked). The presets whose composition holds a Model-owned block (Credit Snapshot,
Earnings Update, Relative Value, Portfolio Decision) request it right after CP-1
(decision 0009, task 6.5). Until it is published it stays `unrun` and the Model
destination says "Model not run"; `publish_cp_model` below gives it a head.

### CP-MODEL publication (task 7.1a)

`publish_cp_model(store, output=DIR)` (CLI `cp-model-publish --output DIR`) is Python only:
no model call, no prompt, no review. It is refused (`CpModelRefused`; the CLI prints the
reason on stderr and exits 2) before any file is written and before any attempt begins unless:

1. the run requests CP-MODEL (decision 0009 presets: Credit Snapshot, Earnings Update,
   Relative Value, Portfolio Decision);
2. CP-1's head is `accepted` or `restricted` and records `Head.qualification` (so it was
   promoted by 6.4, not settled by the engine alone) and its promotion attempt retains the
   `quality` handoff and a `financials` stage that calculated a Model (`FinancialStage.model`);
3. `DIR` does not exist; and no attempt is pending (`begin` refuses otherwise).

Then it begins `CP-MODEL` and builds the candidate `Module` from the journal alone: three
text registers (the Model destination manifest, the calculation JSON identity, and the
provenance binding CP-1's head, the envelope Markdown and sidecar hashes and the pack hash)
and one claim without a figure. It settles that candidate in memory with the journal's own
`settle` to learn the head it will become, renders `model.html` for that head (the CP-1
page through the accepted route, `read_cp1_envelope`, with the Model panel populated),
writes `model.html`, `calculation.json` (CP-1's `ModelReport`, `financial-model/3`, in its
canonical JSON) and `receipt.json` (last), and only then calls `finish`. The validator
re-derives the candidate from the journal and refuses any difference, so two runs from the
same inputs give the same `model.html`, `calculation.json`, module and head hash, byte for
byte (tested); `receipt.json` differs between two runs by `ticket_id` only (tested). The page is
a function of the CP-1 envelope and the CP-MODEL module alone (an idle base view), so it
re-derives after later modules settle. By design (ruling R3) it shows CP-1 and CP-MODEL only,
says so on the page ("This destination shows CP-1 and CP-MODEL only; other modules appear on
the Front Page.") and leaves other modules to the Front Page route (`render`). A page cannot
hold its own hash and the receipt names the head, so the manifest lists those two files with
"Recorded in receipt.json" instead of a hash; the receipt holds the hashes of `model.html`
and `calculation.json`.

Failure. Any failure before `finish` (a file that cannot be written, a render error, a
candidate the journal would not settle) interrupts the attempt and is raised as
`CpModelRefused`, so the CLI exits 2 with the reason. That leaves no head from the attempt,
but it consumes the attempt: the one repair may publish into a new directory, and a second
consecutive failure leaves a `blocked` CP-MODEL head (decision 0007: the input set's repair
is consumed; the journal's rule, not changed here), which degrades CP-5 to `restricted`; a
third call is refused (`begin`). If `finish` itself raises (for example "Ticket inputs have
changed" after the files are written), the interrupt cannot succeed either, because
`interrupt` re-checks the inputs through `finish`: the ticket stays pending, the files stay on
disk, `CpModelRefused` names both facts, and every later publication is refused while the
ticket is pending. No CLI recovers a pending ticket whose inputs changed; concurrent writers
are unsupported. The receipt names the head the journal is to hold, so a directory whose head
is not in the journal is not a publication.

`verify_cp_model_publication(store, output)` (CLI `cp-model-verify --output DIR`, exit 2 with
the issues) re-derives from the journal alone: the CP-MODEL head must equal the candidate
rebuilt from the promoted CP-1, and `model.html`, `calculation.json` and `receipt.json` must
equal the bytes re-derived for that head. A tampered file, a missing file, a missing or stale
head or a CP-1 that no longer holds each yield an issue.

M4 inheritance: settlement follows the journal's rules unchanged. CP-1's limitations are
inherited and shown; a `restricted` CP-1 head also gives CP-MODEL the own limitation
"Published from a restricted CP-1 head; the Model carries its limitations", so CP-MODEL
settles `restricted`; a synthetic run restricts it as for any module. A blocked CP-1 blocks
CP-MODEL (the edge blocks). CP-MODEL is exempt from CP-0's consumer review.

The head records `Qualification(implementation="implemented")` and the other three statuses
`unrun`. The contract has no `not_applicable` literal for `analytical_qualification`, so
`unrun` is used: no analyst has qualified the Model's figures, and the contract is not
extended here. After publication CP-5 can begin under the presets that request CP-MODEL
(`test_cp5_is_held_until_cp_model_is_published_then_begins`).

### Rendering the accepted envelope (task 6.5)

`read_cp1_envelope(store, directory)` reads an exported envelope back and refuses it
(`EnvelopeRefused`, every issue listed) unless it verifies against the journal: the files
match the receipt's hashes, the Markdown verifies against its sidecar (`read_envelope`
checks the pair only against itself, so a consistently rewritten pair would pass it), and
the sidecar's module is the CP-1 head's settled module (`result_sha256`) on the journal's
run and prepared pack, with the head's status, QA report and statuses as the receipt
records them. `render_cp1_envelope` and the `render` command then build the Front Page
from that envelope: the CP-1 registers come from it, never from a candidate. A refused
envelope renders CP-1 blocked with the issues as its limitations and no CP-1 value at
all. The command records the head's `rendering_acceptance` as it stands (`unrun`) and
never sets it: only a browser acceptance run can, and the journal has no transition that
changes a settled head's statuses.

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
are projected with coverage. The preview reads the first four steps, so it still works
after promotion; the canonical envelope and promotion are above.
