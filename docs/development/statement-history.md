# Full statement-line period construction

`statement_history(pack, review, book_id)` produces `statement-history/1` for
T4.4–T4.6. It embeds the unchanged `financial-statements/1` source artifact,
original period records, ordered derived columns, construction records and the
actual arithmetic DAG. It computes every disclosed item and required gap;
issuer-specific detail is not reduced to Model account slots. The source boundary
is revalidated against the frozen pack before calculation. Complete add-back
assessment is not required for statement arithmetic; the separate Model gate
continues to enforce it.

Quarter flows use comparable H1−Q1, 9M−H1 and FY−9M only when the reported
quarter is absent. A reported Q4 remains independent. LTM uses FY+current
YTD−comparable prior YTD; explicit YTD/FY components are recursively resolved.
Every declared component is required. Missing, not-applicable or conflicting
components cannot be replaced by a reported subtotal or stated LTM. No statement
line uses the sparse add-back omission rule. The existing 38-digit half-even
Decimal context owns arithmetic, independent of ambient precision.

Each result retains ordered signed operands, a computation root, recursively
located input evidence, status/reason, and its separately stated comparison and
comparison computation root when available. Even an unspanned construction
retains attempted operand evidence. An unavailable result with conflicting
inputs retains `Conflicted`. Hash-based trusted recomputation detects changes to
precision, metadata, evidence and values; schema validity alone is insufficient.

Balance sheets use observations at the constructed column's exact closing date,
never flow subtraction. Selection prefers the own period, then register order.
A same-date explicit conflict blocks a known fallback; missing/not-applicable
observations do not invalidate an otherwise consistent known closing observation.
Original statuses and alternatives remain in the bound source review. No currency
or scale conversion is invented.

## Shared kernel correction

An adversarial FY→H1→Q1/Q2 case exposed the old one-level component reader:
missing Q1 could be hidden by reported H1 999, producing FY 1069 after Q3 30 and
Q4 40. `_component` now recursively checks declared additive periods. The result
is null when Q1 is missing, or 100 when Q1 is 10; reported FY 888 and H1 999 stay
separate comparisons. Four period levels, cycle/span guards, leaf arithmetic
wrappers, source metadata, order and caller Decimal context are preserved.
Sparse resolution retains its existing behavior. This is an explicit adaptation
of the previously selected kernel, not a new Deploy VI import or policy adoption.

## Delivery and limits

The existing journal `statement-preview` command now appends these constructed
columns to the source statement matrices. Inspectable Facts retain calculation
status, formula, comparison, dates, basis, currency/scale and citations. A formula
operand with declared subcomponents is identified accordingly; its full recursive
arithmetic lives in the companion JSON. Point-in-time-only books have empty flow
tables and no invented derived columns.

`statement-preview/2` writes `statement-history.json` and its hash alongside the
source report, View, HTML and file receipt. See [table projection](report-tables.md)
for snapshot bindings and write guarantees. This remains a candidate preview:
remaining CP-1 registers, canonical Markdown envelope/reader/QA, complete Model
presentation, CP-1A and final Module promotion are outstanding. No live model was
called. Synthetic arithmetic and browser evidence do not qualify analytical
judgments or a completed Module.

[Confidence review and the single key-area tournament](tasks/implementation/statement-history-review.md).
