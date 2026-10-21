# Canonical CP-1 KPI register

`canonical_kpis(pack, review, book_id)` returns a `canonical-kpis/1` artifact.
It retains the frozen historical input report, period bases, every value used by
KPI operands, arithmetic graphs, calculation rows and unresolved definitions.
`validate_canonical_kpis` regenerates the complete report before hash comparison.
This internal API advances CP-1; it grants no analytical or Module acceptance.

Canonical total and senior-secured debt come from CP-1's carrying-value accounts,
excluding both lease types. Model's facility subtotal includes finance leases and
remains separate. Missing canonical debt never falls back to that subtotal or
gross principal. Canonical value IDs occupy their own namespace, so a different
amount cannot masquerade as the corresponding Model value.

Reported and adjusted EBITDA variants are explicit. The source value has priority,
including zero and negative values. For direct periods with no reported income
value, gross profit, EBIT, EBITDA and adjusted EBITDA can derive in dependency
order from available components. Conflicts, explicit not-applicable observations
and missing components of a derived period never fall through to a replacement
aggregate. A source-reported discrepancy remains visible for reconciliation; the
calculation does not silently repair it.

Rolling flows sum the selected canonical quarter values, after each quarter's
source/derivation choice. A missing component or unproven four-quarter span keeps
the rolling flow null. Closing debt, cash and liquidity retain the closing date.
This avoids replacing a reported quarter merely because another quarter required
calculation. FY/YTD/LTM comparisons preserve their existing separate bases.

The register includes scalar income/cash/debt/liquidity values, reported and
adjusted leverage/coverage/margins, FFO/debt, CFO/debt, FCF/debt, FCF conversion,
capex/revenue, liquidity/debt and like-period growth. It uses the reviewed Model's
period rules: quarterly leverage/coverage/flow-to-debt use the trailing year;
margins and FCF conversion use their own period; interim leverage is unavailable.

CFO retains explicit financing-classification adjustments. FFO is adjusted CFO
less signed working-capital change, consistent with the reviewed cash-flow
identity; its graph no longer needs an EBITDA residual to reconstruct that
identity. Cash conversion means FCF/adjusted EBITDA in the pinned Model workbook;
the register also retains the reported EBITDA variant. Expenses/outflows remain
negative internally. Ratios require positive denominators; percentages are decimal
fractions. Arithmetic uses Decimal precision 38, half-even, independent of ambient
context. Every signed leg identifies its retained values and actual period basis.

DCF, DCF/debt and FFO interest coverage are explicit unavailable rows with reasons.
The references name those metrics without defining the required formulas. User
clarifications remain pending; no selected option or elapsed time is treated as
an answer. Evidence tiers and analytical trends also remain unassessed.

## Method review and reuse

Reviewed against Deploy VI `bd71346301b373afa72655916a4c1b42bf4c9823`:

- CP-1 runbook canonical debt/event rules and Step 09 KPI/audit-trail requirements.
- Already selected Decimal Model metric recipes and period-selection semantics.
- `cp_model_v3/calculations.py`'s FFO = CFO − working capital identity; implemented
  with the selected Decimal helpers and explicit financing-classification basis.
- `cp_model_v3/workbook.py`'s labelled cash-conversion formula.
- The old `credit_metrics.py` helper was inspected but not imported. Its silent
  preference for adjusted EBITDA and float arithmetic are not adopted.

No old policies, parser, host state or completion claims were imported. The source
hashes and review details are in
[review evidence](tasks/implementation/canonical-kpis-review.md).
Full reconciliation exceptions, remaining CP-1 narrative registers, calculation/
Module binding, Direction C acceptance and live qualification remain outstanding.
