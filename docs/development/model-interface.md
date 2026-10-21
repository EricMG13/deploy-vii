# Model interface candidate

`model_interface(pack, review, book_id, quarter_ids=...)` builds an immutable
`model-interface/1` artifact from a validated financial review. It supplies r14
T4.14–T4.19 plus segment allocation, operating KPIs, pro-forma adjustments and one
CP-MODEL historical-readiness row. Exact field headings and table identifiers
come from the pinned Model interface reference. All tables retain headers when
empty; segment allocation is omitted when there are no supplied segments.

The account register contains the 35 controlled r14 account IDs per source
period. Full statements retain additional lines, including net income. Source
period metadata, account sign normalization and original observations remain
inspectable. Dynamic segment/add-back/KPI schedules preserve issuer labels and
stable display priorities, with explicit missing values across source periods.
Facility rows retain actual supplied periods and original currencies. No synthetic
facility is invented for an absent period. Readiness retains missing-schedule
findings separately. Pro-forma amounts remain separate from reported accounts.

Every numeric cell, including a missing/conflicting cell, retains its unit and
currency where applicable. Fixed coupons are decimal percentages (`6.500` means
6.5 percent); effective tax rates remain decimal fractions. Spreads and floors
use basis points. Source principal, carrying value, drawn balance and commitment
are distinct. Kernel FX conversions do not overwrite source amounts here.
Each field retains its citations; the row's primary source locator is only the
first applicable locator and does not represent every field's evidence.

Unknown values display `null` with reasons and gap entries. Empty reference lists,
non-quarter fiscal-quarter metadata and absent component references are explicit
not-applicable fields. The pinned exceptions for unstated floors and inapplicable
fixed/floating terms do not create value gaps; conflicts and unknown amortisation
still do. `reference_rate=NONE` is a literal controlled value, never a null marker.
The historical readiness result is scoped to selected quarters; it neither accepts
CP-1 nor establishes all-consumer analytical sufficiency.

## Journal-bound preview

After valid source-context and financial submissions:

```sh
uv run --locked deploy-vii execution --directory runs/example/execution-1 interface-preview --ticket TICKET --output runs/example/interface-1
```

The command rechecks the current financial stage against trusted recomputation.
It combines source/constructed statement matrices with the interface tables in a
Direction C candidate. It writes a fresh directory containing
`interface-preview.json`, `view.json`, `tables.md`, `candidate.html` and a last-written
`complete.json`. The receipt (`interface-preview-receipt/1`) binds file hashes,
pack/review hashes, snapshot, ticket and financial-step hash. Existing destinations
are rejected. Failed writes can leave an incomplete directory; no receipt means
incomplete output. This is not atomic directory publication or a power-loss promise.
The snapshot binding is fixed at invocation, not updated by later journal changes.

The HTML keeps inspectable fields, locally scrollable tables and readable minimum
column widths. Scope notes stay outside the horizontal scroller. Candidate tests
cover exact field parity, keyboard inspection, both desktop viewports, 125% zoom
and offline operation. These synthetic checks do not qualify a completed Module.

## Markdown transport boundary

`read_table_markdown` reads exactly one canonical table, with an optional exact
interface comment. It decodes generated entities once and verifies their canonical
re-encoding; literal source entities, markup characters and pipes survive as text.
CRLF/CR source newlines normalize to LF in the writer. Duplicate headings,
nonrectangular rows, raw markup, alternative escaping, trailing prose and altered
interface syntax are rejected. Limits are 4,000,000 characters, 20,000 data rows
and 1,024 columns per table. These are transport limits, not financial readiness
criteria. The reader returns strings, including literal `null`.

`validate_table_markdown` compares the complete decoded table with the writer's
projection of a caller-supplied trusted Module, including decimal precision and
identity. It cannot authenticate an arbitrary supplied Module. No Deploy VI
parser was copied. `tables.md` is explicitly a preview: the 17-section canonical
envelope, remaining registers, full QA, typed downstream reader/adapter, complete
Model presentation and final Module promotion remain pending. JSON files provide
internal provenance; they are not an alternative final analytical handoff.

The coupon unit correction advances the source audit to `canonical-audit/4`.
Retain old outputs/stores; stages embedding `/3` are not silently migrated and
must be regenerated in a new execution attempt/directory. Provider spend and
repair history are not reset by this format change.

Evidence: [confidence review and parser tournament](tasks/implementation/model-interface-review.md).
