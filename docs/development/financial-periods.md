# Historical series and constructed periods

`historical_report(pack, review, book_id)` now exposes the validated historical
input series as a hash-bound `financial-periods/1` artifact. It supplies the
period-construction layer needed by CP-1 T4.8 and later Model output/readiness.
It does not yet assemble statement/ratio calculations, grant Model readiness,
or connect to the CLI, journal or Workbench.

The report binds run, issuer, as-of date, method, prepared-pack/review hashes,
book, perimeter, accounting basis, currency and scale. It carries the original
period records, source observations (including explicit gaps/conflict alternatives),
and the adapter inputs before kernel normalization. Input rows identify the
original observation or the facility issuance evidence responsible for a
source-backed zero. An omitted input row is represented explicitly where the
validated adapter requires it; omission does not imply zero.

Each historical column has a stable construction ID and retains its original
kernel key, label, kind, fiscal identity, dates/day count, own/stated period
references, ordered signed components, formula and limitation. Nested
constructions remain linked nodes; direct period references resolve to the
original period register. Length-prefixed hashed IDs prevent long source IDs or
ambiguous delimiter combinations from corrupting artifact identities. Distinct
kernel constructions with the same column key are rejected rather than silently
overwritten.

Each series/column value retains its kind, unit/currency, amount, independently
stated amount, source/normalized/calculated category, canonical calculation
status, missing reason, notes, observation/issuance references and citations.
Flow constructions expose their operands with exact signs and values. Balances
use the column's closing date and are never subtracted as quarter flows. Rates
require their own exact-period observation. Foreign facility currency and KPI
units are preserved. PERCENT is a fractional rate for the canonical effective
tax-rate input, as in the reviewed kernel fixtures; no display multiplication
or rounding is performed here.

A source observation is `Verified` only in the r14 calculation-status sense: the
located submitted value is retained. This is not independent analytical
qualification. Normalized and derived amounts are `Calculated`; unavailable or
uncalculable outputs remain null with explicit reasons. The embedded source
register retains the finer missing/conflicting/not-applicable input states.
A reported LTM or FY amount remains a separate comparison and never fills a
missing construction input.

The pinned kernel's plan/readers own arithmetic under the existing 38-digit,
half-even Decimal context. Evidence is indexed once per report. Unknown source
references fail; sign-normalization evidence and issuance citations are not
silently dropped. `validate_historical_report` regenerates the complete report
and compares its content hash, including its source inputs and construction
metadata. Schema validation alone cannot authenticate a supplied result.

## Date corrections made during integration

Three adversarial cases exposed gaps in the original internal period behavior:

- H1 and Q1 with different starts could produce a known Q2 by subtraction.
  Calculated quarters now require the smaller period to be an actual prefix:
  same dated start, earlier end. Otherwise terms remain visible but flows are
  null with a comparability limitation and no invented day count.
- A supplied LTM day count could relabel a computed 365-day period as 364 days.
  Components now own the constructed span. An incompatible supplied LTM date
  span is explicit and blocks the constructed flows; it cannot change their dates.
- An FY with no established span could be treated as a known twelve-month period.
  Complete components must establish 364–371 days. Complete source dates can
  establish this even when optional day-count fields are missing; missing
  components or unprovable spans cannot.

The two affected kernel functions are explicitly adapted from the selected
Deploy VI port; all other port behavior remains under regression tests. Two
legacy day-count assertions were updated to require the computed 365-day span.
No original source hash or historical port evidence has been rewritten.

## Remaining work

The API inherits the validated Model input boundary, including the requirement
for an assessed complete add-back bridge. A partial review can still be retained
as a source artifact but cannot enter this Model conversion. Full CP-1 delivery
must show those input gaps separately.

[Historical Model output](model-output.md) now retains statement values and
explicit ratio numerators/denominators and computation graphs.
[Constructed-period reconciliation](period-reconciliation.md) now compares their
underlying accounts and source equations, with circular agreement identified.
Full canonical KPI coverage, source-backed difference treatment, final four-quarter
readiness, CP-1A and execution/HTML binding remain pending. Synthetic tests verify deterministic
behavior; public-case analytical qualification and native-host delivery remain
unrun. No completed-module browser acceptance is claimed for this internal API.
