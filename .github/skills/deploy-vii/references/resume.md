# Journal, attempts and resumption

Read from `src/deploy_vii/execution.py` at origin/main 14e81d2 (line numbers are for
that head and drift).

- `begin` (606) refuses while any attempt is `pending`: "An attempt is pending; resume or
  explicitly interrupt it first" (610-611). It also refuses when the input set is
  settled or its one module-wide repair is used (619).
- An attempt's ticket is the only handle. Responses are stored by hash before they are
  validated (`submit_step` 725, `finish` 638), so a crash during validation leaves the
  response retained and the attempt pending.
- Resume is implicit: submit the same ticket with the same review text again. This resumes
  only a step or response left pending (for example a crash during validation). A step that
  is already valid is refused by the order check: "Submit the next module step in order"
  (769-770).
  `submit_step` accepts a retained pending step only when the payload hash matches
  (773-781); otherwise "Step already retains a different response; resume or interrupt".
  `submit_cp0_review` and `promote_cp1` apply the same rule (`cp0_workflow.py` 43,
  `cp1_workflow.py` 467).
- Steps must go in order (770). A first invalid response to a step in
  `WITHIN_ATTEMPT_REPAIR` (121) keeps the attempt pending and the next submission of that
  step is its one repair (811-820). Any other invalid response finishes the attempt;
  `begin` then opens the module's one repair attempt.
- `begin` after `interrupt` (or after any finished attempt) turns on the previous attempt
  for the same inputs: it is the module's one repair only if that attempt has `issues`
  (619). `interrupt` settles with the issue "Interrupted: <reason>" (`settle` 413-415), so
  the next `begin` is the repair (`number` 1, `repair_of` the interrupted ticket). A second
  finished attempt for the same inputs (`len(previous) >= 2`) is refused, as is a first
  attempt that finished without issues (settled).
- Every submit command (`cp0-submit`, `cp1-submit`, `cp1-promote`, `module-submit`) prints the
  attempt JSON on stdout and exits 1 with the validator's issue lines on stderr when the review
  was rejected, including a first rejection kept for the step's one repair (the attempt is still
  `pending`: submit the corrected review for the same step on the same ticket). Exit 0 means the
  review was accepted; exit 2 is a one-line refusal (missing review file, unknown module or step).
- `interrupt` (848) finishes a pending attempt with a reason. It records an interruption
  in the journal; it does not stop a host process or a running command.
- `finish` refuses with "Ticket inputs have changed" when upstream evidence changed
  (651-655); `replace_pack` (854) is refused while an attempt is pending.
- A concurrent writer is serialised by the journal lock (`_locked`).
- `extend-scope <module...>` (task 9.1, MC-9) extends a finished or partly run execution to
  a superset of its requested modules instead of starting a new one: pass the full new set.
  It refuses while an attempt is pending, and refuses any added module (the required closure
  included) other than CP-0, CP-MODEL, CP-MEMO and CP-OS that CP-0's head has not assessed
  ("CP-0 has not assessed <ids>; create a new execution"); a refusal exits 2 and writes
  nothing. Otherwise it stales only the settled heads whose resolved inputs change (note
  "Scope extended: inputs changed (<ids>); rerun required"; today CP-5 when CP-MODEL joins its
  fan-in, and its consumers), keeps every other head with its attempts and repair count, and
  prints the added modules, kept and staled heads and the new plan; then `begin` the added
  and staled modules in plan order. Readers of the pack blob (CP-0 readiness, CP-1 and CP-1A
  consumer lists, the live runner) keep the original scope. Open defect: after any
  extension the CP-1 envelope export (`envelope`, the CP-1 render, `cp-model-publish`)
  refuses because the promoted handoff hashes the original run; do not extend a run whose
  CP-1 is promoted until that is fixed.

Gap: no `resume` command and no listing of resumable tickets other than `status`.
Not verified: behaviour after the host process is killed mid-command; the offline test
only checks that commands parse.
