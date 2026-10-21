# Staged CP-1 execution review

Task: continue A–H implementation from `880682b`, on
`codex/development-environment`, in `/Users/ericguei/Documents/DEPLOY VII`.
Owner: coordinator session `01a15bb5-b5bc-7151-94b3-4edbae9d7815`.
Scope: retain source-first CP-1 submissions in the existing bounded execution
journal, trusted CP-0 promotion, and local CLI access. No provider invocation,
new dependency, CSS change, final CP-1 projection, or Module qualification.

## Confidence review

Least confident about, ranked by likelihood and impact:

1. Crash recovery could overwrite a retained response or grant another repair.
   Investigated `submit_step`, `finish`, `settle`, `begin`, interruption and pointer
   publication. Concrete tests crash inside validation, read the persisted pending
   response from the callback, try changed payloads, and resume exact data. A failed
   second stage followed by a failed first-stage repair blocks the entire Module.
   Verdict: verified fine. Runtime errors remain pending; explicit interruption
   consumes the attempt and preserves steps. Existing whole-module tests also pass.
2. CP-0 could promote a supplied success flag or skip source/issuer gates.
   The adapter parses/validates the actual review, constructs its candidate in
   Python, requires usable identity-confirmed evidence, then recomputes the exact
   candidate before promotion. Crash between step validation and promotion resumes
   the same valid step. Malformed/stale/unconfirmed/unusable reviews reject and
   consume the shared repair. Verdict: verified fine. The generic execution API
   still accepts trusted Python validators; this is not an untrusted plugin sandbox.
3. Later CP-1 stages could bind stale or unrelated evidence, or run before context.
   Tests reject out-of-order stages, stale source/financial/narrative/readiness
   hashes and incorrect extraction bindings. Every completed step input tuple is
   checked against exact upstream inputs and prior completed submission hashes.
   Verdict: verified fine. The wrapper owns the fixed sequence; internal callers
   are trusted. Python performs all arithmetic, with no model-generated verdict.
4. Missing calculations or selected quarters could masquerade as complete output.
   Complete and partial add-back fixtures go through every stage. Partial evidence
   retains `model: null`, calculation issues and data-quality narrative scope.
   Unknown/duplicate quarters produce readiness BLOCK findings, not a runtime
   exception or fabricated calculation. Selected logical aliases remain explicit.
   Verdict: verified fine. No valid stage creates a CP-1 or CP-MODEL head.
5. Concurrency or a refactor could change publication/exception sequencing.
   Concurrent submissions serialize under the existing lock; one succeeds and the
   second fails ordering. The full snapshot and response traces of all four
   tournament candidates match across 36 comparisons, including callback crashes
   and invalid stages. Verdict: verified fine. No directory-fsync or Windows
   durability claim is added; existing POSIX/local-hash limitations remain.
6. New state fields or old journals could be silently misread.
   Added state-coherence checks for pending/valid/invalid submissions. Invalid
   state construction is tested. `execution/2` rejects explicit `/1` snapshots;
   no silent migration resets provenance or budgets. Verdict: by design; migration
   remains open and is documented. This cannot reset provider spend.
7. CLI or tests could imply completion of delivery or analyst qualification.
   CLI smoke tests cover create, frozen pack replacement, status, begin, CP-0/CP-1
   submission, retained outputs, and interruption. Views/HTML and CSS are unchanged.
   The final readiness stage leaves CP-1 pending. Verdict: verified fine for this
   increment. Canonical Markdown, Workbench fields, final module projection,
   CP-1A, and model/native qualification remain open product work.

Fixed during development: strict-type variable reuse; missing step-state
coherence validation. Test fixture corrections: required readiness fields and
located analysis/authority limitation; source gate fixture now uses a fully
assessed nonfinancial source rather than failing earlier coverage validation;
the unusable-source fixture now uses valid BLOCKED consumers without attachments
and asserts the exact identity/source gate issue, rather than an invalid enum.
No additional production defect was established by adversarial review.

Design-hook triage: no CSS fix. Retained the existing narrow `side-tab/*` exception
for `src/deploy_vii/assets/app.css`, which identifies the Direction C active-page
navigation marker. No new suppression and no unresolved design finding.

## Scoped post-edit tournament

Only `Execution.submit_step` and `cp1_workflow._validate_stage` were selected.
Routine CLI, CP-0 adapter, state-contract and finish-helper edits received focused
checks and confidence review. Incumbent, speed, memory, readability, and blind
arbiter each used a fresh `gpt-6.1-sol` / high worker under the explicit matrix;
no more than three workers ran concurrently. The coordinator model stayed unchanged.

GitNexus context for DEPLOY VII returned repository-not-found. Fallback `rg`
identified both wrappers, direct workflow tests and execution callers. Strict
mypy checks the complete source impact set. The internal callbacks/sequence remain
trusted arguments. No public signature, output, exception or write order changed.

Winner: Snippet B for `Execution.submit_step` (readability), replacing this turn's
new implementation; Snippet A for `_validate_stage` (memory).

- Snapshot reconstruction is centralized while the pre-validation and final
  writes stay explicit and in their original order.
- The later CP-1 stages keep narrative inputs while releasing the temporary
  parsed financial wrapper and historical Model report earlier; savings are
  bounded and no benchmark speed claim is made.
- Exact serialized journal/report comparisons and focused caller tests preserve
  provenance, null/gap semantics, error behavior and the shared repair budget.

The arbiter's comments about argument-evaluation timing do not establish a
production bug: these are immutable validated model fields. Adoption rests on
simpler snapshot maintenance, shorter object lifetimes, and the parity evidence.
Backups and anonymized candidates are retained under ignored
`artifacts/staged-tournament/`; no user changes were reverted.

Verification:

- `PYTHONPATH=. uv run --locked python artifacts/staged-tournament/parity.py`:
  36 exact trace comparisons passed, including all four candidates.
- `uv run --locked pytest tests/product/test_workflow.py tests/product/test_execution.py -q --tb=short`:
  49 passed before the final fixture-only source-gate correction; that corrected
  case is rechecked separately below.
- `uv run --locked mypy src`: passed, 44 source files.
- `make product-check`: passed, 801 tests, 97.48% branch-inclusive coverage;
  Ruff, strict mypy (44 files), JavaScript syntax and coverage threshold passed.
- `uv run --locked pytest 'tests/product/test_workflow.py::test_cp0_invalid_review_consumes_shared_repair[unusable]' -q --tb=short`:
  1 passed after the final fixture-only correction; no production code changed
  after the full suite began. The full suite collected the earlier fixture.
- `make check`: passed after the fixture correction.
- `make secrets`: directory, staged diff and all reachable history passed.
- Final diff inspection covered all production, test and documentation changes;
  recorded function code and hashes match the production winners. No dependencies
  changed, so dependency audit was not needed.

Raw local evidence: `artifacts/staged-product-check.log`, `staged-focused.log`,
`staged-check.log`, `staged-secrets.log`, and `staged-tournament/parity.log`.
These are ignored operational artifacts. The coordinator owns this local commit;
no PR, push, live model call, new worktree or model/provider switch occurred.

Final code of the two selected functions follows; file/line locations and hashes
identify the reviewed implementation. Final module acceptance remains separate.

### `src/deploy_vii/execution.py:382–478`

SHA-256 of this function text: `98872fc6a08ec786558c7af602941b8e05035c6d8991fc51429f1fa71237a5a0`.

```python
    def submit_step(
        self,
        ticket_id: str,
        module_id: str,
        sequence: tuple[str, ...],
        step_id: str,
        payload: str,
        validator: Callable[[PreparedPack, Attempt], StepValidation],
    ) -> Attempt:
        """Retain an ordered response before trusted validation, sharing the module budget.

        Sequence and validator come from the module implementation. Invalid model
        responses finish this attempt; validator exceptions leave its exact input
        pending for resumption. A valid step is not module acceptance.
        """
        if not sequence or len(sequence) != len(set(sequence)):
            raise ValueError("Step sequence must be nonempty and unique")

        def with_attempt(snapshot: ExecutionSnapshot, updated: Attempt) -> ExecutionSnapshot:
            return snapshot.model_copy(
                update={
                    "parent": snapshot.content_hash(),
                    "attempts": tuple(
                        updated if prior.ticket_id == ticket_id else prior
                        for prior in snapshot.attempts
                    ),
                }
            )

        with self._locked():
            snapshot = self.read()
            attempt = next((a for a in snapshot.attempts if a.ticket_id == ticket_id), None)
            if attempt is None or attempt.status != "pending" or attempt.module_id != module_id:
                raise ValueError("Ticket is absent, finished or belongs to another module")
            if current_inputs(snapshot, module_id) != attempt.inputs:
                raise ValueError("Ticket inputs have changed")
            if attempt.payload is not None:
                raise ValueError("A module response is already retained; resume its validation")
            completed = tuple(step for step in attempt.steps if step.status == "valid")
            if tuple(step.step_id for step in completed) != sequence[: len(completed)]:
                raise ValueError("Retained steps do not match the module sequence")
            if len(completed) >= len(sequence) or step_id != sequence[len(completed)]:
                raise ValueError("Submit the next module step in order")

            if len(attempt.steps) > len(completed):
                submission = attempt.steps[-1]
                if submission.status != "pending" or submission.payload != payload:
                    raise ValueError(
                        "Step already retains a different response; resume or interrupt"
                    )
                if submission.step_id != step_id:
                    raise ValueError("Pending step identity differs")
            else:
                submission = StepSubmission(
                    step_id=step_id,
                    payload=payload,
                    inputs=(
                        *attempt.inputs,
                        *(
                            Input(input_id="step:" + step.step_id, sha256=step.content_hash())
                            for step in completed
                        ),
                    ),
                )
                attempt = attempt.model_copy(update={"steps": (*attempt.steps, submission)})
                snapshot = with_attempt(snapshot, attempt)
                self._write(snapshot)

            outcome = StepValidation.model_validate_json(
                validator(snapshot.pack, attempt).model_dump_json()
            )
            if not outcome.issues and outcome.output is None:
                raise ValueError("Successful step validator must retain its output")
            submitted = submission.model_copy(
                update={
                    "status": "invalid" if outcome.issues else "valid",
                    "output": outcome.output,
                    "issues": outcome.issues,
                }
            )
            attempt = attempt.model_copy(update={"steps": (*completed, submitted)})
            if outcome.issues:
                candidate = Module(
                    run_id=snapshot.pack.run.run_id,
                    issuer_id=snapshot.pack.run.issuer_id,
                    as_of=snapshot.pack.run.as_of,
                    module_id=module_id,
                    inputs=attempt.inputs,
                    attempt=attempt.number,
                )
                finished = settle(
                    snapshot, attempt, candidate.model_dump_json(), lambda _: outcome.issues
                )
                self._save_finished(snapshot, finished)
                return finished
            self._write(with_attempt(snapshot, attempt))
            return attempt
```

### `src/deploy_vii/cp1_workflow.py:66–152`

SHA-256 of this function text: `1eff2160bb8a26624befc77b3e05a76baa652296575afe2cb013288d9e00f475`.

```python
def _validate_stage(pack: PreparedPack, attempt: Attempt) -> StepValidation:
    step = attempt.steps[-1]
    try:
        if step.step_id == "source_context":
            context = SourceContextReview.model_validate_json(step.payload)
            issues = validate_source_context(pack, context)
            if issues:
                return StepValidation(issues=issues)
            report = source_context(pack, context)
            return StepValidation(
                output=report.model_dump_json(),
                issues=("CP-1 source gate blocked: no usable assessed financial source",)
                if report.status == "blocked"
                else (),
            )
        context = SourceContextReview.model_validate_json(attempt.steps[0].payload)
        financial = FinancialSubmission.model_validate_json(attempt.steps[1].payload)
    except ValidationError as error:
        return StepValidation(issues=(f"Invalid CP-1 {step.step_id} submission: {error}",))
    if step.step_id == "financials":
        if financial.context_step_sha256 != attempt.steps[0].content_hash():
            return StepValidation(
                issues=("Financial extraction does not bind the retained source step",)
            )
        issues = (
            *validate_financial_context(pack, context, financial.financial, financial.binding),
            *validate_definition_review(pack, financial.financial, financial.definition),
        )
        if issues:
            return StepValidation(issues=tuple(dict.fromkeys(issues)))
        inputs = narrative_inputs(
            pack, context, financial.financial, financial.definition, financial.binding
        )
        output = FinancialStage(
            narrative_inputs=inputs,
            model=model_report(pack, financial.financial, financial.definition.book_id)
            if inputs.ledger.kpis is not None
            else None,
            model_issues=inputs.ledger.calculation_issues,
        )
        return StepValidation(output=output.model_dump_json())
    # These outputs came from trusted Python validation of the already retained
    # responses. Recompute the final artifacts from original contracts below.
    stage_inputs = FinancialStage.model_validate_json(
        attempt.steps[1].output or ""
    ).narrative_inputs
    try:
        narrative = NarrativeReview.model_validate_json(attempt.steps[2].payload)
        readiness = (
            DownstreamReview.model_validate_json(step.payload)
            if step.step_id == "readiness"
            else None
        )
    except ValidationError as error:
        return StepValidation(issues=(f"Invalid CP-1 {step.step_id} submission: {error}",))
    if step.step_id == "narrative":
        issues = validate_narrative_review(stage_inputs, narrative)
        if issues:
            return StepValidation(issues=issues)
        downstream = downstream_inputs(
            pack,
            context,
            financial.financial,
            financial.definition,
            financial.binding,
            narrative,
            consumer_entries(pack),
            quarter_ids=financial.quarter_ids,
        )
        return StepValidation(output=downstream.model_dump_json())
    assert step.step_id == "readiness" and readiness is not None
    prior = DownstreamInputs.model_validate_json(attempt.steps[2].output or "")
    issues = validate_downstream_review(prior, readiness)
    if issues:
        return StepValidation(issues=issues)
    result = canonical_downstream_readiness(
        pack,
        context,
        financial.financial,
        financial.definition,
        financial.binding,
        narrative,
        consumer_entries(pack),
        readiness,
        quarter_ids=financial.quarter_ids,
    )
    return StepValidation(output=result.model_dump_json())
```
