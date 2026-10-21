# Narrative projection confidence review

Task `dvii-implementation-001`, milestone C; base `90e5352`, branch
`codex/development-environment`. Owner session
`01a15bb5-b5bc-7151-94b3-4edbae9d7815`. The preceding turn made verified progress:
its register projection and journal-bound preview are committed. This increment
adds reader-facing synthesis, evidence trace and coverage to that candidate.

Pinned method reviewed: Deploy VI
`bd71346301b373afa72655916a4c1b42bf4c9823`, CP-1 skill, schema and Steps 11–12.
Source files were read as reference; no old implementation or policies imported.
One coordinator owns implementation. Current model unchanged; no worker route or
provider was silently substituted. No live model call, dependency or budget change.

## Scope and review decisions

Changed `canonical_tables`, `register_view`, the Claim inspector in `app.js`, and
new `narrative_projection`. These adapt existing validated narrative records to
existing Claim/Fact/layout contracts. The journal trust boundary, analytical
validation, arithmetic and external hash comparison remain unchanged. Per the
user's key-area-only correction, no tournament for this presentation adapter.
Confidence review and behavioral/integration/browser checks cover the change.

GitNexus context lookup for this repository returned “Repository not found”.
`rg` supplied the actual impact set: `canonical_tables` calls `project_narrative`;
its three passage call sites cover findings, dimension rationale and funding
rationale. `register_view` serializes both Claims and tables; the existing CLI and
journal entry point call it. Strict typing covers Python callers. Shared Claim
rendering also affects CP-0 and execution/delivery views, included in the full suite.

## Confidence review — ranked concerns

1. **Projection could invent a number, lose order or sever evidence.** Traced
   `canonical_tables` through the already validated downstream/narrative report.
   `_passage` concatenates the existing discriminated tokens in order; only issuer
   names and generated trace labels are substituted. Original records supply
   every field. Repeated references retain all usages and ordered unique citations,
   but only one trace row. Claims preserve all three chain roles. The populated
   fixture checks those roles, issuer, references, actual record hashes and source
   citations. External recomputation rejects replaced Claim text. **Verified fine
   for projection.** No semantic correctness inferred from reference existence.
2. **Exact values/nulls or nested roles lost in human presentation.** `_fields`
   keeps every leaf with JSON-pointer escaping and JSON scalar spelling; Decimal
   source values are serialized strings in the prior contracts. Independent cases
   distinguish `"1.2300"`, null, `"null"`, booleans, empty arrays/objects and embedded
   newlines. The trace retains the originating artifact and exact record hashes.
   Dates, periods, units and accounting roles remain in the prior record and its
   canonical registers. **Verified fine on exercised records.** This is not a new
   typed downstream reader or a claim that arbitrary new record types qualify.
   The material-funding check exposed an overly broad scope label: standalone
   StatementCell records do not contain their book's units or full period dates.
   Added those dimensions from the validated statement book/period to the field
   inspector. Other records now explicitly require their canonical context when
   dimensions are not intrinsic; none are guessed from shared computation IDs.
   The regression retains `20.00`, USD, MILLIONS, exact Q2 end date, source citations,
   reviewed/material funding roles and the missing-story BLOCK.
3. **Missing assessments/stories could look complete.** All seven dimensions are
   shown; absent assessments remain unassessed. Funding preserves declared scope.
   Required events remain in the trace even without findings; the table says
   missing and inherited BLOCK remains in the report. Supplying a valid event story
   changes only the projected coverage. Source-period statement coverage lists
   missing required items; point-in-time flow statements are explicitly excluded.
   **Verified fine.** Filing extraction completeness remains unqualified.
4. **Global narrative limitations could disappear during composition.** Review
   found that adding Claims alone would leave `NarrativeReport.limitations` only
   inside the embedded report. **Confirmed omission:** added each limitation to
   the combined Module, prefixed `Narrative:`. The regression checks every note.
   Claim-level limitations also explicitly distinguish prior records from
   unqualified analyst synthesis. No inherited gap or readiness decision changed.
5. **Source text becomes executable or alters Markdown structure.** HTML enters
   text nodes through existing rendering. The initially considered generic HTML
   escaping did not cover Markdown links; final implementation uses the existing
   `markdown_cell` transport for Claim text as well. The browser fixture contains
   script markup, URL syntax and long text. It verifies literal text, absent script
   effects, no network requests and exact Markdown decoding. **Verified fine.**
   No model HTML or arbitrary Markdown renderer was added.
6. **Claims disappear from preview or lose inspector provenance.** Added Claims
   to the candidate view alongside facts/tables; every Claim gets an explicit DOM
   identity. Inspector includes the owning artifact hash as well as citations.
   Browser tests compare every Claim and Fact value and activate evidence using
   keyboard Enter at both required sizes and zoom. Journal hash stays unchanged.
   **Verified fine in synthetic browsers.** Acceptance fields remain unrun.
7. **Formats silently overwrite retained evidence.** New projection is explicit
   `canonical-tables/2`, with a rejection test for `/1`; receipt is `/2`. Existing
   directories still fail before replacement. `execution/4`, Module/View contracts,
   prior-stage schemas and the one-repair budget are unchanged. **By design:**
   preview receipts are last-written, not an atomic directory publication promise.
8. **Fixture green results misrepresent financial qualification.** Tests use
   explicitly synthetic sources. Early failures were test mistakes: issuer was
   `Synthetic`, not `Synthetic Issuer`; `line` defaults to CFS, not IS; a new revenue
   line must agree with the existing account; a substring assertion accidentally
   rejected “completeness is unqualified”. Corrected fixtures/assertions without
   changing production source values or weakening the intended checks. **Still
   open:** full analytical/live/native acceptance and final report delivery.

Fixed: combined narrative limitations, Claim transport into preview, inspector
artifact provenance, statement trace dimensions and Markdown text escaping. Verified fine: token order,
source hashes, null/precision distinctions, coverage, missing event stories,
external tampering rejection and offline parity. By design: preview only and
caller-trusted internal projection. Still open: canonical envelope/QA/confidence,
complete analytical assessment, full typed handoff, large-pack scale, CP-1A and D–H.

## Verification

- `make product-check`: 900 passed in 264.89s; reported branch-inclusive coverage
  97.44%. Ruff, format, strict typing and JavaScript syntax passed. Log:
  `artifacts/narrative-projection-product-check.log`. This run began before the
  final statement trace dimension change and its added regression; the final
  focused check below covers that code, including browser rendering.
- `uv run --locked pytest tests/product/test_narrative_projection.py tests/product/test_register_view.py tests/product/test_canonical_tables.py -q`:
  29 passed in 53.51s. Log: `artifacts/narrative-projection-all-focused.log`.
- After adding statement trace dimensions and their regression,
  `uv run --locked pytest tests/product/test_narrative_projection.py -q`:
  10 passed in 19.07s, including both browser sizes. Log:
  `artifacts/narrative-projection-final.log`.
- Final code: `uv run --locked ruff check src tests/product`, Ruff format and
  `make types` passed; 52 typed source files. No dependencies changed.
- `make check` passed; `make secrets` found no leaks in working files, staged
  changes or the 34 commits at the pre-commit base. Logs:
  `artifacts/narrative-projection-hygiene.log` and `artifacts/narrative-projection-secrets.log`.

The coordinator inspected the complete changed code, tests and documentation.
Synthetic rendering evidence lives under `artifacts/rendering/narrative-projection/`.
Both desktop sizes retain exact Claim and Fact text, keyboard inspection, 125%
zoom and offline behavior. The 1280×800 and zoom screenshots were visually
inspected, including the long inert script/link text and visible evidence hashes.
No chart was introduced. No cumulative acceptance is claimed for this unfinished
CP-1 candidate.

Design-hook triage: no CSS change, no new ignore and no unresolved design defect
identified. The existing narrow `side-tab` exception still preserves intentional
Direction C active navigation. Inspector provenance was improved in this increment.
OpenRouter spend remains US$0 of US$50. The A–H goal remains active.
