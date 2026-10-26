# Journal, attempts and resumption

Read from `src/deploy_vii/execution.py` (task 9.1 fix round 1); functions are cited by name.

- `Execution.begin` refuses while any attempt is `pending`: "An attempt is pending; resume
  or explicitly interrupt it first". It also refuses when the input set is settled or its one
  module-wide repair is used ("Input set is settled or its one repair has been consumed").
- An attempt's ticket is the only handle. Responses are stored by hash before they are
  validated (`Execution.submit_step`, `Execution.finish`), so a crash during validation
  leaves the response retained and the attempt pending.
- Resume is implicit: submit the same ticket with the same review text again. This resumes
  only a step or response left pending (for example a crash during validation). A step that
  is already valid is refused by the order check in `submit_step`: "Submit the next module
  step in order".
  `submit_step` accepts a retained pending step only when the payload hash matches;
  otherwise "Step already retains a different response; resume or interrupt".
  `cp0_workflow.submit_cp0_review` and `cp1_workflow.promote_cp1` apply the same rule.
- Steps must go in order. A first invalid response to a step in `WITHIN_ATTEMPT_REPAIR`
  keeps the attempt pending and the next submission of that step is its one repair. Any
  other invalid response finishes the attempt; `begin` then opens the module's one repair
  attempt.
- `begin` after `interrupt` (or after any finished attempt) turns on the previous attempt
  for the same inputs: it is the module's one repair only if that attempt has `issues`.
  `interrupt` settles with the issue "Interrupted: <reason>" (`settle`), so the next `begin`
  is the repair (`number` 1, `repair_of` the interrupted ticket). A second finished attempt
  for the same inputs (`len(previous) >= 2`) is refused, as is a first attempt that finished
  without issues (settled).
- Every submit command (`cp0-submit`, `cp1-submit`, `cp1-promote`, `module-submit`) prints the
  attempt JSON on stdout and exits 1 with the validator's issue lines on stderr when the review
  was rejected, including a first rejection kept for the step's one repair (the attempt is still
  `pending`: submit the corrected review for the same step on the same ticket). Exit 0 means the
  review was accepted; exit 2 is a one-line refusal (missing review file, unknown module or step).
- `Execution.interrupt` finishes a pending attempt with a reason. It records an interruption
  in the journal; it does not stop a host process or a running command.
- `finish` refuses with "Ticket inputs have changed" when upstream evidence changed;
  `Execution.replace_pack` is refused while an attempt is pending.
- A concurrent writer is serialised by the journal lock (`_locked`).
- `extend-scope <module...>` (`Execution.extend_scope`, task 9.1, MC-9) extends a finished
  or partly run execution to a superset of its requested modules instead of starting a new
  one: pass the full new set. It refuses while an attempt is pending, and refuses any added
  module (the required closure included) other than CP-0, CP-MODEL, CP-MEMO and CP-OS that
  CP-0's head has not assessed ("CP-0 has not assessed <ids>; create a new execution"); a
  refusal exits 2 and writes nothing. Otherwise a head is staled iff its `current_inputs`
  resolution under the new scope differs from its resolution before the extension (note
  "Scope extended: inputs changed (<ids>); rerun required"; today CP-5 when a new member such
  as CP-MODEL joins its fan-in, and its consumers); every other head is kept with its
  attempts and repair count, including drift that predates the extension. It prints the
  added modules, kept and staled heads and the new plan; then `begin` the added and staled
  modules in plan order. Readers of the pack blob keep the original scope: CP-0 readiness,
  the CP-1 and CP-1A consumer lists, the live runner, the CP-1 envelope, the CP-1 render and
  the Model page. The earlier defect (after an extension the CP-1 envelope export, render and
  `cp-model-publish` refused) is fixed (task 9.1 fix round 1, commit 61cce94).

`execution resume` inspects the pending ticket and retained response, or identifies the next
runnable module when none is pending. For host reviews, `--ticket <ticket> --review <file>`
resubmits through the existing workflow with the same retained bytes. Offline tests exercise
production validation, injected interruptions and same-ticket resumption.

Not verified: native host behaviour or recovery after an actual host process kill mid-command.
