# CP-1 source-register reconciliation

`reconcile_financials(pack, review, book_id)` now produces the immutable
`financial-reconciliation/5` internal artifact. It binds the prepared pack and
financial review hashes, run, issuer, as-of date, book, currency, scale,
accounting basis and entity perimeter. It is not a Module acceptance or Model
readiness decision. No CLI, journal or renderer consumes it yet.

Each check retains the reported term, every component (including its original
amount, normalized amount, sign, observation ID, reason and citations), formula,
reported and calculated values, difference, tolerance, status and contextual
citations. Missing and conflicting inputs remain unknown. Lease classification
citations survive even when the associated balances are excluded from debt.
`validate_reconciliation_report` recomputes the artifact from the bound inputs;
schema-valid numbers or PASS labels alone cannot establish correctness.

The selected r14 requirements are recorded in the pinned CP-1 step reference.
The implementation adds these source-register comparisons:

- Segment revenue, including corporate/elimination rows, against consolidated
  revenue. Genuine non-disclosure produces WARN with a null calculated value;
  partial disclosure or a missing member of a disclosed series blocks.
- EBITDA from revenue, COGS where expenses are by function, operating expenses
  including D&A, and D&A. The source presentation classification is required.
- Adjusted EBITDA from reported EBITDA and each stable add-back ID separately.
  Negative deductions remain negative. An explicitly complete empty bridge has
  no adjustments; an unassessed bridge cannot become zero.
- CP-1 debt from carrying values, excluding both lease types while retaining
  debt adjustments. Principal, drawn amounts and commitments never substitute.
  Same-date conflicts block; foreign amounts have no inferred conversion.
- Independent source statement equations, recursively expanded to original leaves.
  CFO identity requires a complete source cash-flow disclosure and independent
  components; the Model residual is never used to prove its own construction.
- Net cash change from the operating, investing and financing source equation,
  including checks of every supplied intermediate equation. See
  [independent NCF](net-cash-flow.md).
- Net cash change against closing less opening cash, including explicitly sourced
  [cash movement adjustments](cash-movement.md); no invented FX plug.
- Each controlled flow metric's reported FY against four directly supplied,
  contiguous quarters spanning exactly that FY. Reported FY remains independent.

Arithmetic uses the kernel's 38-significant-digit half-even Decimal context.
Sign normalization is exact and independent of the ambient Decimal context.
Tolerance is half the last decimal place of the submitted reported amount,
following the reviewed kernel convention. The unrounded difference remains
visible even within tolerance. Correct source interpretation and reporting
precision still require analytical review; quote matching does not prove them.

## Explicit gaps

CFO identity remains BLOCK with a null calculated value when independent source
components, an equation or a complete disclosure assessment are absent. The
[source statement layer](statements.md) now supplies this representation and
compares every nested equation independently; missing leaves cannot disappear
through signed cancellation.

These checks compare supplied canonical periods and observations.
[Constructed-period comparisons](period-reconciliation.md) now cover historical
quarters and LTM separately. [Selected historical Model readiness](model-readiness.md)
now binds four-quarter coverage and mandatory reconciliations. Complete
normalization registers and other consumer readiness remain separate work.
Statement coverage now has its own
hash-bound projection; it does not establish analytical or Module acceptance.
Missing direct schedule rows remain blocked even where the kernel might derive
a value. An explicit, sourced [annual audit explanation](audit-basis.md) can now
make its exact audited-FY versus unaudited-quarter comparison WARN, retaining the
actual difference. No automatic exception is inferred. Source-register comparisons
still do not infer pre-issuance zero balances or absorb unexplained FX differences.
Explicit cash/FX bridges now retain the sourced adjustments and their signs;
unexplained differences are never forced to zero.

There is no live model qualification or new completed-module rendering claim.
All current evidence is explicitly synthetic. This artifact advances milestone
C; the full CP-1, Model report and CP-1A deliverables remain unfinished.

Source-backed [balance movement checks](balance-movements.md) now cover equity
and explicitly declared other BS bridges, with source audit and readiness binding.
