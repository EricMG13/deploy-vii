# CP-1 source-register reconciliation

`reconcile_financials(pack, review, book_id)` now produces the immutable
`financial-reconciliation/1` internal artifact. It binds the prepared pack and
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
- Net cash change against closing less opening cash, with no invented FX plug.
- Each controlled flow metric's reported FY against four directly supplied,
  contiguous quarters spanning exactly that FY. Reported FY remains independent.

Arithmetic uses the kernel's 38-significant-digit half-even Decimal context.
Sign normalization is exact and independent of the ambient Decimal context.
Tolerance is half the last decimal place of the submitted reported amount,
following the reviewed kernel convention. The unrounded difference remains
visible even within tolerance. Correct source interpretation and reporting
precision still require analytical review; quote matching does not prove them.

## Explicit gaps

CFO identity is currently BLOCK with a null calculated value: the compact
account register lacks the independent full source operating cash-flow
components. The Model's residual is defined using CFO, so testing that identity
would prove only its construction. Full statement coverage must supply those
components before this gate can pass.

These checks compare supplied canonical periods and observations. Derived
period construction, source normalization registers, independent statement
coverage and the final four-quarter readiness decision remain separate work.
Missing direct schedule rows remain blocked even where the kernel might derive
a value. The output does not yet grant an audited/unaudited FY exception, infer
pre-issuance zero balances, or absorb FX differences. Those cases require explicit
source-backed treatment; unexplained differences are never forced to zero.

There is no live model qualification or new completed-module rendering claim.
All current evidence is explicitly synthetic. This artifact advances milestone
C; the full CP-1, Model report and CP-1A deliverables remain unfinished.
