# Rewrite tournament — development workflow

No-argument post-edit scope: the two most material validation/normalization
symbols in this pass. All new code received the separate confidence review.
Other new symbols (storage helpers, fingerprint, checkpoint, context_check,
preserve_continuity, import_events, report, CLI main) were skipped by this
pass's two-symbol cap, not declared trivial.

Impact set: validate → workflow.main and workflow tests; normalize → import_events
→ report/CLI/tests. GitNexus listed no index for this repository; repository-wide
rg and strict mypy were used. Invariants: exact signatures/errors/side effects,
recorded and current safety findings, sorted unique findings, no transfer/reset
claims, numeric-only telemetry, null unknowns and separate cumulative/request IDs.

Five distinct roles used explicit GPT-6.1 Sol/high fresh contexts under the model
matrix: incumbent, speed, memory, readability, blind arbiter. No worker changed
production files. Anonymous A/B/C/D candidates and full backups remain ignored
under artifacts/rewrite-tooling. Bracket: A beat B, then C, then D.

**Winner:** Snippet A, replacing validate and normalize in the paths below.

**Justification:**

- A string set directly expresses unique findings without redundant coercion.
- One normalized usage dictionary avoids repeating Codex metric normalization.
- Named normalized usage keeps it distinct from event identity and preserves
  clear host branches and existing callers.

**Verification:** Coordinator applied the candidate after saving backups, then ran
`make dev-check`: 26 passed, Ruff lint/format passed, strict mypy passed (five files).
Concrete invariants include C04 pause/exhausted budget, C08 cumulative-not-occupancy,
request conflicts excluded, and C03 untracked/index/worktree identity. Callers still
compile and pass. Full candidate diff inspected before committing.

**Final code:**

`devtools/state.py:206–247`

```python
def validate(repo: Path, record: Object, current_context: Object) -> Object:
    old = checked_context(record)
    context_check(current_context)
    findings: set[str] = set()
    snapshot = fingerprint(repo, old["sources"])
    same_tree = record.get("snapshot") == snapshot
    if not same_tree:
        findings.add("tree_changed")
    if old != current_context:
        findings.add("context_changed")
    explicit = snapshot["explicit_inputs"]
    assert isinstance(explicit, dict)
    if any(isinstance(value, dict) and value["status"] == "missing" for value in explicit.values()):
        findings.add("missing_explicit_inputs")
    # Never let a submitted replacement erase the recorded pause or exhausted budget.
    for context in (old, current_context):
        if context["paused"]:
            findings.add("paused")
        if context["pending_operations"]:
            findings.add("pending_operations")
        budgets = context["budgets"]
        assert isinstance(budgets, list)
        for budget in budgets:
            assert isinstance(budget, dict)
            cap, used = budget.get("cap"), budget.get("consumed")
            if cap is None or used is None:
                findings.add(f"budget_unknown:{budget['unit']}")
            elif isinstance(cap, (int, float)) and isinstance(used, (int, float)) and used >= cap:
                findings.add(f"budget_exhausted:{budget['unit']}")
        treatment = context["context_treatment"]
        assert isinstance(treatment, dict)
        if treatment.get("kind") == "fresh" and treatment.get("input_verified") is not True:
            findings.add("fresh_context_unverified")
    return {
        "schema_version": 1,
        "state_matches": same_tree,
        "findings": [item for item in sorted(findings)],
        "ownership_verified": False,
        "transfer_status": "NOT_READY",
        "automatic_reset": False,
        "limitation": "Observational only; no process stop, transfer or factual truth proof.",
    }
```

`devtools/telemetry.py:39–72`

```python
def normalize(event: Object, host: str, session: str) -> Object | None:
    session_hash = digest(session.encode())
    if host == "codex":
        payload = obj(event.get("payload"))
        info = obj(payload.get("info"))
        if event.get("type") != "event_msg" or payload.get("type") != "token_count":
            return None
        # Last usage is not a uniquely identified request; never add it to the ledger.
        usage = obj(info.get("total_token_usage"))
        if not usage:
            return None
        kind = "cumulative"
        normalized_usage = usage_fields(usage)
        identity: Json = normalized_usage
    elif host == "claude":
        message = obj(event.get("message"))
        usage = obj(message.get("usage"))
        request_id = message.get("id")
        if event.get("type") != "assistant" or not usage or not isinstance(request_id, str):
            return None
        kind = "per_request"
        normalized_usage = usage_fields(usage)
        identity = request_id
    else:
        raise ValueError("host must be codex or claude")
    record: Object = {
        "host": host,
        "session": session_hash,
        "kind": kind,
        "usage": normalized_usage,
        "missing_metric_reason": "not exposed as a nonnegative integer by the supplied event",
    }
    record["event_id"] = digest(encode([host, session_hash, kind, identity]))
    return record
```
