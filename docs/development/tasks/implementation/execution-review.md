# Execution journal review

Scope: `execution.py`, shared `registry.dependencies`, execution tests. This
implements an internal state substrate ahead of CP-1, not the live orchestration
adapter or a financial module. Public/source qualification remains unrun; actual
OpenRouter spending remains US$0. API and limitations: ../../execution.md.

## Confidence review

1. Response loss after a validator crash — CONFIRMED in initial implementation.
   Reproduced a raising validator leaving a pending ticket with no response.
   Fixed by publishing a retained-response snapshot before invoking validation.
   Test proves raw response survives, a different response cannot replace it,
   same-response local validation can resume, and interruption retains the raw.
2. Duplicate attempts or completion under concurrency — verified with two actual
   file-lock users in separate threads. Exactly one initial reservation succeeds;
   exactly one finalization succeeds. Lock spans read, validation and writes.
   This serializes state only, not ownership or external provider activity.
3. Retry count reset through restart or evidence replacement — tested reopening
   stores, consuming both attempts, changing pack and reverting. The original
   module/input tuple retains its count. First failure rejected, final failure
   blocked, every response retained. Empty response is distinct from absent.
4. Wrong issuer/date/attempt/status/module, stale hashes, invented quotes — tested
   adversarial submissions. Generic gates run before trusted module validation.
   Missing CP-0 readiness commands and stale/blocked upstreams fail closed.
   Semantic sufficiency and calculation correctness remain module-validator work.
5. Old financial values leaking after source changes — checked transitive graph
   invalidation with an unrelated branch preserved; pack change stales all heads.
   Browser tests show stale CP-0 has no fact fields, retains reason and restriction,
   and reports other modules unrun. Inspected 1440×900 stale screenshot. Existing
   CP-0 browser tests retain full field/keyboard/provenance/zoom coverage.
6. Registry refactor changing ordering — initial local variable/function collision
   caught immediately and fixed. Coordinator compared every singleton/pair/triple
   of 25 owners: 2,625 exact plans or error strings match the prior implementation.
7. Snapshot hash/parent/pointer corruption and interruption — corrupted bytes and
   escaping pointer rejected; existing store not overwritten; exact two-phase
   parent chain checked. Writes retain historical files and replace only current.
   POSIX/macOS semantics tested. Directory power-loss durability and malicious
   rewriting of all local evidence are explicitly outside these integrity claims.
8. Overstated acceptance from test stubs — by design tests isolate engine behavior
   with trusted synthetic callbacks. There is no generic CLI promoting arbitrary
   financial modules. Live adapters must supply real method validators and retain
   requests, costs and raw model outputs separately. Native interruption unrun.

Fixed: crash-response loss and dependency name collision. Verified: locking,
lineage, rejection/block distinction, bounded repair, stale suppression, retained
responses and parent chain. Open: adapter integration, native-host qualification,
provider request/budget tracking, automatic old-result reactivation and measured
storage needs. No memory/speed cache added: 25-owner state is small and file I/O
outweighs measured tuple micro-optimizations.

## Key-area tournament

No-argument post-edit scope selected only `Execution.finish` (state/provenance).
Other functions received focused checks and confidence review; the registry
extraction preserved the previously reviewed algorithm. Impact: interrupt calls
finish; execution tests invoke it; read/view consume stored results. No local
GitNexus index; rg plus strict mypy used. All five review roles requested fresh
GPT-6.1 Sol/high under the model matrix; no production edits or recursive workers.

Bracket: C beat B; D beat C; D beat A. Winner: Snippet D, Execution.finish.

- Named settled result and distinct phases make the transition easier to inspect.
- Retention, validation and final publication keep the exact write/parent order.
- No meaningful time/space change; existing tuple-unpacking style retained for Ruff.

Coordinator backed up before applying, inspected the actual diff, then ran
`make product-check`: 82 tests passed, 94.26% combined coverage, strict mypy over
9 files, Ruff lint/format and JS syntax passed. Concrete invariant check: retained
response interruption keeps its exact payload and final parent equals the retained
snapshot hash. Concurrent finish test publishes one result only. Candidate agent
claims were not used as a substitute for coordinator verification.

Repository hygiene and file/staged/history secret scans also passed. No dependency
changes in this increment. Evidence: artifacts/rendering/execution/pytest-832/;
backups and all candidates: artifacts/rewrite-execution/.

Final winning function (after repository formatting):

```python
    def finish(
        self, ticket_id: str, payload: str, validator: Validator, *, interruption: str | None = None
    ) -> Attempt:
        with self._locked():
            snapshot = self.read()
            attempt = next(
                (item for item in snapshot.attempts if item.ticket_id == ticket_id), None
            )
            if attempt is None or attempt.status != "pending":
                raise ValueError("Ticket is absent or already finished")
            if current_inputs(snapshot, attempt.module_id) != attempt.inputs:
                raise ValueError("Ticket inputs have changed")

            if interruption is not None:
                if not interruption.strip():
                    raise ValueError("An interruption requires a reason")
                if attempt.payload is not None:
                    payload = attempt.payload
            if attempt.payload is not None and attempt.payload != payload:
                raise ValueError(
                    "Ticket already retains a different response; finish or interrupt it"
                )
            if attempt.payload is None:
                attempt = attempt.model_copy(update={"payload": payload})
                snapshot = snapshot.model_copy(
                    update={
                        "parent": snapshot.content_hash(),
                        "attempts": tuple(
                            attempt if item.ticket_id == ticket_id else item
                            for item in snapshot.attempts
                        ),
                    }
                )
                self._write(snapshot)  # Retain response before a validator can fail or crash.

            finished = settle(snapshot, attempt, payload, validator, interruption)
            result = finished.result
            assert result is not None
            heads = invalidate(snapshot.heads, attempt.module_id)
            if result.status != "rejected":
                heads = (
                    *tuple(item for item in heads if item.module_id != attempt.module_id),
                    result,
                )
            snapshot = snapshot.model_copy(
                update={
                    "parent": snapshot.content_hash(),
                    "heads": heads,
                    "attempts": tuple(
                        finished if item.ticket_id == ticket_id else item
                        for item in snapshot.attempts
                    ),
                }
            )
            self._write(snapshot)
            return finished
```
