# Source and entity context increment review

Task `dvii-implementation-001`; base `02e01b1`, branch
`codex/development-environment`, coordinator owns checkout/publication. Previous
turn: progress (source audit registers committed). This advances milestone C's
T4.1/T4.2 and connects declared source scope to financial extraction. No Module,
analytical, rendering or native-host acceptance is promoted. OpenRouter spend
remains US$0 of the US$50 first-core qualification cap.

Scope: `source_context.py`, `context_binding.py`, synthetic context regressions and
documentation. No dependency or frontend changes. Pinned methodology and behavior:
[source context](../../source-context.md).

## Confidence review

Ranked doubts, investigation and outcomes:

1. **False binding to another entity, period or accounting basis.** Traced
   source assessments, exact pack/review hashes, explicit book/entity mapping and
   every period/observation citation, including alternative values. Matching
   requires declared entity ID plus exact dates/currency/unit/perimeter/basis.
   Regressions reject wrong entities, scopes, currencies, scales, perimeters,
   accounting bases, dates, unknown/duplicate books and nonfinancial sources.
   A conflict with its second alternative in another source/perimeter is rejected
   even though the settled amount is null. Verdict: verified fine mechanically;
   interpretation of the source remains an analytical responsibility.
2. **Nested model-copy input might evade the boundary or crash traversal.**
   Reproduced: a valid serialized FinancialBook held as a dictionary inside
   `FinancialReview.model_copy` passed the existing validator but then raised
   `AttributeError: 'dict' object has no attribute 'book_id'`. The binding now
   reconstructs all four inputs before traversing, then validates each boundary.
   A regression supplies nested dictionaries in both financial and context inputs
   and verifies the same valid result. Verdict: confirmed and fixed.
3. **Pro-forma values could be treated as historical or bypass event context.**
   Reproduced: a source-cited acquisition adjustment bound with no context event.
   Now pro-forma positions bypass historical-value matching and instead require
   a matching event's entity, reporting end, dimensions, effective date, status,
   known/announced ordering and financial source coverage. A regression first
   blocks an unlinked acquisition, then accepts its matched context without
   changing the financial review, and rejects date/status mismatch. Verdict:
   confirmed and fixed. Event amounts remain original observations; no arithmetic
   or retrospective historical mutation is introduced.
4. **Future information or an empty scan could be mistaken for evidence.**
   Located no-event assertions are explicit; empty default scans are unassessed.
   Checks reject missing/duplicate event references, unsupported scan claims,
   event dates inside the reporting period, unknown boundaries, future knowledge,
   future completed events and completion knowledge before the event. Historical
   scopes cannot end after publication/as-of. Event knowledge cannot postdate its
   cited publication. Future announced events remain flagged outside history.
   Two-source regressions require each event evidence source to record the event;
   another source's scan/scope citation cannot be borrowed. Verdict: verified fine.
5. **Readability or filename could imply authority, or incomplete metadata
   disappear.** Tier mapping is solely from the explicit cited classification.
   Seven hierarchy cases pass; renaming a source AUDITED_TIER_1_FINAL.pdf cannot
   fill an unknown tier. Missing files retain inventory/hash-null state and block
   the financial file gate. Unknown entity fields, publication dates, missing
   scope dimensions, source/basis differences and scan limitations remain gaps.
   Repeated identical limitations deduplicate without merging different sources.
   Verdict: verified fine; a source's tier does not automatically label every KPI.
6. **Output tampering, unstable order or source mutation.** Source reports bind
   current external inputs and are recomputed before hash comparison. Tests reject
   removed rows, old versions and substituted reviews; original inputs remain
   unchanged. Event-evidence sources and financial evidence pairs are sorted for
   deterministic diagnostic order; other rows preserve source/review order.
   Verdict: verified fine. No calculated or accepted state is created by these APIs.

Fixed: nested-input traversal crash and missing pro-forma/event binding. Initial
lint/type issues and a test import omission were corrected before final checks.

By design: context candidate/restricted status is not consumer readiness; a known
subsequent event remains visible as a warning. Multiple source bases can coexist,
with explicit warnings; binding chooses only the already-declared book basis and
never performs conversion. Missing roles remain visible rather than inferred.

Still open: full consumer readiness, derived-period/KPI gap union, evidence-risk-
credit narrative, source-first execution ordering and Module/Workbench delivery.
Currency conversion and source semantic correctness are not established here.
DCF and FFO coverage definition clarifications remain pending, with no adoption.


## Scoped rewrite tournament

Only `validate_source_context` and `validate_financial_context` were selected in
no-argument post-edit mode. Routine report/gap assembly, recomputation wrapper and
contract declarations received focused tests and confidence review instead.
Every role used explicit GPT-6.1 Sol/high; the coordinator model was unchanged.

Impact: source-context validation feeds source report assembly, external report
recomputation and financial-context binding. Binding currently has test callers
only. GitNexus could not resolve this repository, so `rg` reference discovery and
strict mypy covered callers; no other project's index was used.

Anonymous bracket: A (speed) beat B (memory), C (readability), then D (incumbent)
on static review. Coordinator applied A after backing up both files. Its 181
focused tests passed, but strict mypy rejected two incompatible variable reuse
assignments in the financial scope cache. A was rejected and the backups were
used to apply the next challenger, C. C passed the same tests and strict typing.
No performance claim is made.

**Winner: verified Snippet C (readability fallback).** Replaces
`source_context.py:144-300` and `context_binding.py:27-133` in this increment.

Justification:

- Positive scope and event predicates expose every entity/date/basis requirement
  together while retaining the historical/pro-forma boundary.
- It retains direct comparisons and original traversal order without positional
  cache keys or new indexes; the only reused set is local to source event checks.
- Coordinator differential checks preserve exact diagnostics and immutable inputs;
  focused tests and strict typing verify all affected callers.

Verification:

- `uv run python artifacts/source-context-tournament/differential.py`: 49 tests
  passed, 205 context calls and 21 binding calls each compared against all three
  challengers (678 exact result comparisons). Includes duplicate assessments with
  different publication dates, scan unions, duplicate events, chronology, all
  observation alternatives and matched/unmatched pro-forma evidence. Valid base
  context and financial binding independently assert an empty issue tuple.
- `uv run pytest tests/product/test_source_context.py tests/product/test_canonical_audit.py tests/product/test_financials.py tests/product/test_statements.py tests/product/test_reconciliation.py -q`:
  181 passed with the verified fallback applied.
- `uv run mypy src`: success, 36 source files. Public signatures and return types
  are unchanged. Full final candidate diff inspected by the coordinator.

Confidence follow-up: the positive event conjunction is the exact complement of
the old rejection disjunction, retaining null guards before dereferences and
matching source coverage. Concrete linked/unlinked event and alternative-evidence
regressions pass. No additional confirmed defect remains in this scoped increment.
Full consumer readiness and source semantic truth remain open as recorded above.

Final code (both selected functions):

```python
def validate_source_context(pack: PreparedPack, review: SourceContextReview) -> tuple[str, ...]:
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        review = SourceContextReview.model_validate_json(review.model_dump_json())
    except ValidationError as error:
        return (f"Invalid source context contract: {error}",)
    # Inventory and citation failures precede assertions about individual records.
    issues: list[str] = []
    if review.pack_sha256 != pack.content_hash():
        issues.append("Source context does not bind current prepared pack")
    sources = {s.source_id: s for s in pack.sources}
    if (
        len(review.sources) != len(sources)
        or {s.source_id for s in review.sources} != sources.keys()
    ):
        issues.append("Assess every prepared source exactly once")
    entities = {e.entity_id: e for e in review.entities}
    if len(entities) != len(review.entities):
        issues.append("Duplicate entity identity")
    scopes = {scope.scope_id: scope for source in review.sources for scope in source.scopes}
    if len(scopes) != sum(len(s.scopes) for s in review.sources):
        issues.append("Duplicate reporting scope identity")
    events = {e.event_id: e for e in review.events}
    if len(events) != len(review.events):
        issues.append("Duplicate subsequent-event identity")
    issues.extend(citation_issues(tuple(records(review, Citation)), pack.sources))
    # Entity assertions must be located; unresolved fields need explicit limitations.
    for entity in review.entities:
        if len(set(entity.roles)) != len(entity.roles):
            issues.append(f"Duplicate entity role: {entity.entity_id}")
        has_assertions = bool(
            entity.name or entity.roles or entity.fiscal_year_end or entity.entity_type != "unknown"
        )
        if has_assertions and not entity.citations:
            issues.append(f"Entity assertions require located content: {entity.entity_id}")
        is_incomplete = (
            not entity.name
            or not entity.roles
            or not entity.fiscal_year_end
            or entity.entity_type == "unknown"
        )
        if is_incomplete and not entity.limitations:
            issues.append(f"Incomplete entity context requires limitation: {entity.entity_id}")
    # Source-local checks retain review order, including event attachments.
    referenced_events: set[str] = set()
    for assessment in review.sources:
        source = sources.get(assessment.source_id)
        if source is None:
            continue
        if source.status != "ready" and (
            assessment.classification != "unassessed"
            or assessment.scopes
            or assessment.evidence_class
            or assessment.event_scan != "unassessed"
            or assessment.document_type
            or assessment.published_on
        ):
            issues.append(f"Unavailable source cannot supply assessed context: {source.source_id}")
        if (assessment.document_type or assessment.published_on) and not assessment.citations:
            issues.append(f"Source metadata requires located content: {source.source_id}")
        if assessment.classification != "unassessed" and (
            not assessment.citations or not assessment.document_type
        ):
            issues.append(
                f"Source classification requires type and located content: {source.source_id}"
            )
        if assessment.classification == "unassessed" and (
            assessment.evidence_class or assessment.scopes
        ):
            issues.append(
                "Unassessed source cannot supply evidence tier or reporting scope: "
                f"{source.source_id}"
            )
        if assessment.published_on and assessment.published_on > pack.run.as_of:
            issues.append(f"Source publication is after as-of date: {source.source_id}")
        if any(
            c.source_id != source.source_id
            for c in (*assessment.citations, *assessment.event_scan_citations)
        ):
            issues.append(f"Source context cites another source: {source.source_id}")
        for scope in assessment.scopes:
            if scope.entity_id not in entities:
                issues.append(f"Unknown scope entity: {scope.scope_id}")
            if any(c.source_id != source.source_id for c in scope.citations):
                issues.append(f"Reporting scope cites another source: {scope.scope_id}")
            if scope.start_date and scope.end_date and scope.start_date > scope.end_date:
                issues.append(f"Reversed reporting dates: {scope.scope_id}")
            if scope.period_kind == "period_end" and scope.start_date is not None:
                issues.append(f"Period-end scope cannot have a start date: {scope.scope_id}")
            if (
                scope.period_kind != "forecast"
                and scope.end_date
                and scope.end_date > pack.run.as_of
            ):
                issues.append(f"Historical reporting scope ends after as-of date: {scope.scope_id}")
            if (
                scope.period_kind in {"historical_duration", "period_end"}
                and scope.end_date
                and assessment.published_on
                and scope.end_date > assessment.published_on
            ):
                issues.append(
                    f"Historical reporting scope ends after publication: {scope.scope_id}"
                )
        source_event_ids = set(assessment.event_ids)
        if (
            len(source_event_ids) != len(assessment.event_ids)
            or not source_event_ids <= events.keys()
        ):
            issues.append(f"Duplicate or unknown source event: {source.source_id}")
        if (assessment.event_scan == "events_identified") != bool(assessment.event_ids):
            issues.append(f"Event scan conclusion and references disagree: {source.source_id}")
        if assessment.event_scan != "unassessed" and not assessment.event_scan_citations:
            issues.append(f"Event scan requires located evidence: {source.source_id}")
        for event_id in assessment.event_ids:
            event = events.get(event_id)
            if event and source.source_id not in {c.source_id for c in event.citations}:
                issues.append(
                    f"Event attachment lacks evidence from source: {source.source_id} {event_id}"
                )
        referenced_events.update(assessment.event_ids)
    # Event chronology and evidence coverage follow all source-local checks.
    for event in review.events:
        event_scope = scopes.get(event.reporting_scope_id)
        if (
            event_scope is None
            or event_scope.end_date is None
            or event_scope.period_kind not in {"historical_duration", "period_end"}
        ):
            issues.append(f"Subsequent event requires a dated historical scope: {event.event_id}")
        elif event.event_date <= event_scope.end_date:
            issues.append(f"Event is not after reporting period: {event.event_id}")
        if event.known_on > pack.run.as_of or (
            event.status == "completed" and event.event_date > pack.run.as_of
        ):
            issues.append(f"Subsequent event is not known at as-of date: {event.event_id}")
        if event.status == "completed" and event.known_on < event.event_date:
            issues.append(f"Completion evidence precedes event date: {event.event_id}")
        if event.event_id not in referenced_events:
            issues.append(f"Subsequent event is absent from source scans: {event.event_id}")
        for source_id in sorted({c.source_id for c in event.citations}):
            source_review = next((s for s in review.sources if s.source_id == source_id), None)
            if (
                source_review
                and source_review.published_on
                and event.known_on > source_review.published_on
            ):
                issues.append(
                    f"Event knowledge date is after cited publication: {source_id} {event.event_id}"
                )
            if not any(
                s.source_id == source_id and event.event_id in s.event_ids for s in review.sources
            ):
                issues.append(
                    f"Event evidence omitted by source scan: {source_id} {event.event_id}"
                )
    return tuple(issues)

def validate_financial_context(
    pack: PreparedPack,
    context: SourceContextReview,
    financial: FinancialReview,
    binding: FinancialContextBinding,
) -> tuple[str, ...]:
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        context = SourceContextReview.model_validate_json(context.model_dump_json())
        financial = FinancialReview.model_validate_json(financial.model_dump_json())
        binding = FinancialContextBinding.model_validate_json(binding.model_dump_json())
    except ValidationError as error:
        return (f"Invalid financial context binding: {error}",)
    # Fully validate both reviews before using their cross-references.
    issues = [*validate_source_context(pack, context), *validate_financial_review(pack, financial)]
    if issues:
        return tuple(issues)
    # Identity failures prevent traversal of bound books.
    if (
        binding.financial_review_sha256 != financial.content_hash()
        or binding.source_context_review_sha256 != context.content_hash()
    ):
        issues.append("Context binding does not identify current financial and source reviews")
    books = {b.book_id: b for b in financial.books}
    entities = {e.entity_id for e in context.entities}
    if len(binding.books) != len(books) or {b.book_id for b in binding.books} != books.keys():
        issues.append("Bind every financial book exactly once")
    for row in binding.books:
        if row.entity_id not in entities:
            issues.append(f"Unknown bound entity: {row.book_id} {row.entity_id}")
    if issues:
        return tuple(issues)
    source_index = {s.source_id: s for s in context.sources}
    event_index = {e.event_id: e for e in context.events}
    scope_index = {scope.scope_id: scope for s in context.sources for scope in s.scopes}
    for bound in binding.books:
        book = books[bound.book_id]
        periods = {p.period_id: p for p in book.periods}
        # Include period metadata and every located observation alternative.
        evidence: set[tuple[str, str]] = set()
        for period in book.periods:
            evidence.update((period.period_id, c.source_id) for c in period.citations)
        for position in _positions(book):
            if position.register_id == "pro_forma":
                continue
            evidence.update(
                (position.period_id, c.source_id) for c in records(position.observation, Citation)
            )
        for period_id, source_id in sorted(evidence):
            period = periods[period_id]
            source = source_index[source_id]
            if source.classification != "financial":
                issues.append(
                    "Financial evidence source not classified financial: "
                    f"{book.book_id} {source_id}"
                )
                continue
            # A matching name is insufficient: the explicit entity, dates and
            # canonical dimensions must all agree before extraction is bound.
            has_matching_scope = any(
                scope.entity_id == bound.entity_id
                and scope.currency == book.currency
                and scope.unit == book.unit
                and scope.entity_perimeter == book.entity_perimeter
                and scope.accounting_basis == book.accounting_basis
                and scope.end_date is not None
                and scope.end_date == period.end_date
                and scope.period_kind in {"historical_duration", "period_end"}
                and (
                    period.period_type == "PERIOD_END"
                    or (
                        scope.period_kind == "historical_duration"
                        and scope.start_date is not None
                        and scope.start_date == period.start_date
                    )
                )
                for scope in source.scopes
            )
            if not has_matching_scope:
                issues.append(
                    "No matching entity/date/basis source scope: "
                    f"{book.book_id} {period_id} {source_id}"
                )
        # Pro forma evidence is bound to its separate subsequent-event context.
        for adjustment in book.pro_forma:
            event = event_index.get(adjustment.event_id)
            scope = scope_index.get(event.reporting_scope_id) if event else None
            source_ids = {c.source_id for c in records(adjustment, Citation)}
            has_matching_event = (
                event is not None
                and scope is not None
                and scope.entity_id == bound.entity_id
                and scope.end_date == periods[adjustment.period_id].end_date
                and (scope.currency, scope.unit, scope.entity_perimeter, scope.accounting_basis)
                == (book.currency, book.unit, book.entity_perimeter, book.accounting_basis)
                and event.event_date == adjustment.effective_date
                and event.status == adjustment.event_status
                and event.known_on >= adjustment.announced_on
                and source_ids <= {c.source_id for c in event.citations}
                and all(source_index[sid].classification == "financial" for sid in source_ids)
            )
            if not has_matching_event:
                issues.append(
                    "Pro forma lacks matching located subsequent-event context: "
                    f"{book.book_id} {adjustment.adjustment_id}"
                )
    return tuple(issues)
```


## Final verification

- `make product-check`: passed; lint, format, strict typing (36 source files),
  JavaScript syntax, and 648 product tests with 97.38% combined coverage.
- `make check`: passed; locked dependency check, all repository hygiene hooks,
  working-tree and staged whitespace checks.
- `make secrets`: passed; working files, staged diff and all reachable Git history
  scanned with Gitleaks 8.30.1, no leaks found.
- No dependency change; no dependency audit required for this increment.
- Side-tab hook triage: intentional active Direction C navigation edge, covered by
  the existing narrow rule/value/file exception in `.impeccable/config.json`.
  No CSS fix or new suppression; the navigation indicator is left standing.
- No model-assisted calls or new Module acceptance. OpenRouter spend US$0 of US$50.

Next work: union source/constructed-period/KPI gaps, add the evidence-risk-credit
narrative and full consumer readiness, then connect CP-1/Model artifact execution
and Direction C fields; CP-1A and milestones D–H remain outstanding. Pending DCF
and FFO coverage definition questions remain unresolved with unavailable rows.
