# Source preparation and CP-0 implementation review

Implemented: explicitly named PDF/text/XLSX snapshots, source coverage and hashes,
CP-0 review contract/validator/register assembler, candidate and structurally
accepted offline reports. Live analytical qualification: unrun. Native host:
unrun. Core OpenRouter spend: US$0. No source sufficiency claim follows solely
from extraction, schema validation or these synthetic tests.

## Method and bindings

Reviewed pinned r14 CP-0 SKILL.md, CP-0_SCHEMA_REFERENCE.md and REF_CP-0_STEPS.md
at Deploy VI commit bd71346301b373afa72655916a4c1b42bf4c9823. Transport differs
under the adopted user request: immutable JSON artifacts and HTML replace the
historical Markdown-only host boundary. Imported no invocation/approval machinery.
The internal method prompt is src/deploy_vii/methods/cp0.md. It preserves source
inventory/identity/version/fidelity, authority separation, source-to-consumer
readiness, gaps/conflicts, command safety and source-only model-route assertions.

P3 is per-source content classification/identity/version; P5 is extraction and
reviewed fidelity; T1 is objective/run/period gate; T2 source inventory; T3 original
authority; T4 evidence demand/readiness/rationale; T5 gaps/conflicts; T6 located
trace; T7 pack/method/assertion scope; T8 dependency-ordered canonical commands,
attachments and carried limitations. Missing register contents are visibly absent,
not fabricated. No automatic duplicate/amendment collapse or conflict resolution.
All facts bind module/table/row/field IDs to data-fact-id; Evidence binds source IDs.
All other modules stay unrun. See ../../product-cli.md for input schema and commands.

## Confidence review — ranked doubts

1. Can unsupported or changed evidence be promoted? Traced CLI load_pack through
   review validation, assembly and delivery. Pack/original hashes are checked;
   citations require available source, original hash, locator and exact substring.
   Confirmed frozen model_copy bypass could evade nested constraints: validator
   now roundtrip-revalidates the complete pack/review. Tests reject empty quotes,
   changed packs, invented quotes and missing assessments. Structural support is
   not semantic entailment; analytical qualification remains open.
2. Can a source assessment cite another document or drop relevant limits? Found
   classification citations were not constrained to the assessed source; added
   same-source check and regression. Unresolved authority/entity/period requires
   limitations. T8 now carries preparation, source and applicable gap limitations
   mechanically; READY still rejects relevant limits. No unavailable attachment
   can be smuggled through a readiness row. Confirmed/fixed.
3. Does XLSX preserve exact values? Read OOXML numeric strings directly, avoiding
   binary-float conversion. Test preserves 12345678901234567890.0010, formula cache
   0 versus absent, hidden sheet state, number format, merged ranges and comments.
   Reproduced phonetic text wrongly appended to shared strings and negative index
   selecting the last entry. Fixed by selecting real text/rich-text runs and
   explicit index bounds. Macro/formula execution and link fetching do not occur.
4. Can malformed XML bypass the declaration guard? UTF-16 could hide ASCII DTD
   tokens; parser now explicitly decodes supported UTF-8 first and rejects NUL,
   DTD/entities. ZIP member duplication/expanded size and worksheet path checks
   fail closed. Original and expanded limits are not hard OS memory limits;
   PDF decompression may allocate before its content-stream check. Open limitation.
5. Can partial PDFs become complete? Every page is retained or recorded empty/
   unreadable. Encrypted/corrupt PDFs have no original fallback; blank page test
   retains its locator and OCR limitation. All PDFs remain degraded until visual
   fidelity review. Formula caches similarly remain stale/absent unless separately
   supported. No OCR, slide, chart or image-region fidelity is claimed.
6. Can snapshots overwrite or mislabel missing data? Only explicit root-contained
   paths; snapshot destination must be new. Originals captured once and hashed.
   Missing and unreadable are distinct; directory I/O failure is unreadable with
   unknown hash. Duplicate cell locators produce an unreadable source record;
   oversized inputs retain no misleading truncated-prefix hash. Regression tests
   cover both cases. Final marker required; original/marker tampering tested. Marker
   write is completion detection, not an OS power-loss durability guarantee.
   Files remain physically writable; malicious edits to data and all hashes are
   outside this local integrity check, not cryptographic authenticity protection.
7. Could model review order alter execution or blocked output leak? Command rows
   follow registry dependency order even for reversed input review. Conditional/
   blocked commands say DO NOT RUN. Blocked accepted views suppress facts/claims;
   candidates remain inspectable. Synthetic cases are restricted. Tested.
8. Does the HTML actually show source metadata? Initial source panel exposed only
   text; added extractor/status/coverage, hidden/type/format/formula/cache/note
   fields. Added row identity column to distinguish repeated CP-0 fields. Browser
   tests check every emitted fact, provenance, evidence metadata, keyboard, CSS
   zoom, offline requests and overflow at both viewports. Reviewed 1440×900 top
   screenshot. No charts apply to CP-0; financial chart parity is still pending.

Fixed: strict review revalidation, same-source classification, carried limitations,
command ordering, shared-string phonetics/negative indices, UTF-16 declaration
seam, duplicate cell failure handling, oversized-prefix hashing, source metadata display. Verified fine: hash/locator/quote rejection,
missing/zero/cache fidelity, fresh snapshot constraints, no formula/link execution.
By-design: typed supplied review precedes live adapter; structural acceptance is
not analytical qualification; images/slides/OCR are explicit unsupported gaps.
Open: full public-pack/live method evaluation, semantic entailment, native zoom,
execution invalidation and enforced cross-attempt repair count in upcoming runtime.

## Actual evidence and maintenance

make product-check: 60 passed, 92.81% statement/branch coverage, strict mypy over
8 files, Ruff lint/format and JS syntax passed. make check and make secrets
also passed, including full-history and staged-diff secret scans. Evidence lives in artifacts/rendering/cp0/
<pytest-session>/<case>/ (candidate/accepted JSON+HTML, hashes, screenshots, trace,
field-parity/offline checks). Maintenance retained the simple separate parser,
validator and renderer boundaries; no new dependencies or cache justified.

Public case preparation: issuer FY2025 10-K filed 17 February 2026; preliminary
case as-of 18 February 2026. Original IR URL returned HTTP403 to direct download;
public AnnualReports mirror succeeded. Cover identity matched original filing
view. The complete core pack is not yet frozen. Source bytes remain ignored at
source-packs/caesars-fy2025-v1/; retrieval provenance is retained there.
Original SHA-256 6840cafaafbd84b432c3c6eaeba5642c39b1a87c02f8236ee0ec3177e0c587f5.
Preparation at artifacts/public-case/caesars-fy2025-preparation-1/ retained 195/195
page spans, no empty-page gaps, degraded visual-fidelity status; 14.76 seconds on
this host. Pack SHA-256 0132418198863b1c7b4fbad4ffc4621fec852eec794b53b98ad450ecc23f776b.

## Key-area rewrite tournament

Only validate_review selected; all parser/CLI/adapter changes received confidence
review and tests instead, per the user's narrower tournament instruction. Impact:
validate_review → build_readiness → deliver_cp0 → CLI cp0, plus readiness/delivery
tests. No GitNexus index; rg and strict mypy traced callers. Five roles requested
GPT-6.1 Sol/high in fresh contexts. No production worker edits or recursive agents.

Winner: Snippet D, src/deploy_vii/readiness.py::validate_review.

- Descriptive source/assessment indexes clarify validation phases.
- One runnable predicate serves evidence and issuer checks.
- Shared citation validation avoids duplicated cached implementations.

Bracket: B beat C; D beat B; D beat A. Backups/candidates in ignored
artifacts/rewrite-readiness. Coordinator reran make product-check (58 passed),
checked six exact old/new issue tuples, and specifically verified an invented
quote fails. Signature, issue strings and first-occurrence order preserved.

Final code:

```python
def validate_review(pack: PreparedPack, review: ReadinessReview) -> tuple[str, ...]:
    try:
        pack = PreparedPack.model_validate_json(pack.model_dump_json())
        review = ReadinessReview.model_validate_json(review.model_dump_json())
    except ValidationError as error:
        return (f"Invalid readiness contract: {error}",)

    issues: list[str] = []
    if review.pack_sha256 != pack.content_hash():
        issues.append("Review does not bind the current prepared pack")
    sources_by_id = {source.source_id: source for source in pack.sources}
    if len(review.sources) != len(sources_by_id) or {
        item.source_id for item in review.sources
    } != set(sources_by_id):
        issues.append("Assess every prepared source exactly once")
    selected = set(plan(pack.run.requested_modules)) - {"CP-0", "CP-MODEL", "CP-MEMO", "CP-OS"}
    if (
        len(review.consumers) != len(selected)
        or {item.module_id for item in review.consumers} != selected
    ):
        issues.append("Assess each selected canonical live consumer exactly once")
    if len({item.gap_id for item in review.gaps}) != len(review.gaps):
        issues.append("Duplicate gap identity")
    if not review.analysis:
        issues.append("Source readiness requires an evidence-grounded analytical read-through")

    for source_review in review.sources:
        source = sources_by_id.get(source_review.source_id)
        if source is None:
            continue
        if source.status != "ready" and source_review.fidelity != "blocked":
            issues.append(f"Unavailable source cannot pass fidelity: {source.source_id}")
        if source.status == "ready" and not source_review.citations:
            issues.append(f"Source classification must cite content: {source.source_id}")
        if source_review.fidelity != "verified" and not source_review.limitations:
            issues.append(f"Limited fidelity requires explanation: {source.source_id}")
        if (
            source_review.authority == "unknown"
            or not source_review.entity
            or not source_review.period
        ) and not source_review.limitations:
            issues.append(
                f"Unresolved source classification requires limitation: {source.source_id}"
            )
        if any(citation.source_id != source.source_id for citation in source_review.citations):
            issues.append(f"Classification cites a different source: {source.source_id}")
        issues.extend(citation_issues(source_review.citations, pack.sources))

    assessments_by_id = {item.source_id: item for item in review.sources}
    for consumer in review.consumers:
        try:
            owner = canonical(consumer.module_id)
        except ValueError:
            issues.append(f"Unknown consumer: {consumer.module_id}")
            continue
        if owner != consumer.module_id:
            issues.append(f"Alias is not a separate consumer: {consumer.module_id}")
        if len(set(consumer.source_ids)) != len(consumer.source_ids):
            issues.append(f"Duplicate consumer source: {consumer.module_id}")
        runnable = consumer.readiness in {"READY", "READY_WITH_LIMITATIONS"}
        for source_id in consumer.source_ids:
            source = sources_by_id.get(source_id)
            assessment = assessments_by_id.get(source_id)
            if (
                source is None
                or source.status != "ready"
                or assessment is None
                or assessment.fidelity == "blocked"
            ):
                issues.append(
                    f"Consumer attaches unusable source: {consumer.module_id} {source_id}"
                )
            elif consumer.readiness == "READY" and (
                source.limitation or assessment.limitations or assessment.fidelity != "verified"
            ):
                issues.append(
                    f"Consumer must carry source limitations: {consumer.module_id} {source_id}"
                )
        if runnable and (not consumer.source_ids or not consumer.citations):
            issues.append(f"Runnable consumer needs located evidence: {consumer.module_id}")
        if any(citation.source_id not in consumer.source_ids for citation in consumer.citations):
            issues.append(f"Consumer citation not in its attachment set: {consumer.module_id}")
        if not review.issuer_confirmed and runnable:
            issues.append(f"Issuer unconfirmed: {consumer.module_id}")
        issues.extend(citation_issues(consumer.citations, pack.sources))

    for gap in review.gaps:
        issues.extend(citation_issues(gap.citations, pack.sources))
        if not set(gap.affected_modules) <= selected | {"CP-0"}:
            issues.append(f"Gap names unselected consumers: {gap.gap_id}")
        for consumer in review.consumers:
            if consumer.module_id in gap.affected_modules and consumer.readiness == "READY":
                issues.append(f"Consumer omits relevant gap: {consumer.module_id} {gap.gap_id}")

    for claim in review.analysis:
        if not claim.citations and not claim.limitation:
            issues.append(f"Unsupported readiness claim: {claim.claim_id}")
        issues.extend(citation_issues(claim.citations, pack.sources))

    return tuple(dict.fromkeys(issues))
```
