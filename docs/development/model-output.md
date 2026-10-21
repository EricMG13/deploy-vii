# Historical Model calculation artifact

`model_report(pack, review, book_id, exclude_unrealised=False)` produces the
immutable `financial-model/3` internal artifact. It embeds the complete
hash-bound historical input/period report, including run, issuer, as-of date,
method, source/review hashes, perimeter, accounting basis, currency and scale.
It does not grant Model readiness or complete CP-1 delivery.

The report retains every historical statement cell and every trailing-four-quarter
statement cell. Each has a stable ID, basis, key, unit/currency, amount,
source/normalized/calculated category, independent stated amount, calculation
status, reason, note and original observation/issuance citations. Quarter-own
and rolling values occupy separate ID namespaces even when the kernel uses the
same quarter key. [Explicit facility FX normalization](facility-fx.md) preserves
original amounts/currencies while Model values use book currency. Missing or
conflicted conversion evidence leaves the facility aggregate unknown. Model debt
includes finance leases, while
canonical CP-1 debt excludes both types of lease.

Each ratio records the displayed period, signed numerator and denominator
operand IDs, their unrounded sums, formula, unit, currency/input scale and exact
kernel result. Growth records the additional minus-one operation. All operand
IDs resolve to retained values, whose bases identify their actual dates and
source construction. Quarterly leverage and coverage use the trailing year;
quarterly margins use the quarter. Interim leverage is not applicable, while
interim liquidity/debt uses its own closing balances. LTM growth's prior-quarter
fallback points to that prior quarter's rolling year, not its own quarter.
Corporate/elimination segment growth remains not applicable.

Every statement value now references a content-addressed computation root. The
computation register retains the actual ordered, signed operands used by sums
and balance/flow × days calculations, including failed operations. Shared
subexpressions are stored once; children precede parents. Input leaves retain
observation/issuance citations and sign-normalization notes. Located null inputs
retain their evidence separately from generic unavailable leaves. Constants are
explicitly kernel constants, not source facts. Early refusals before arithmetic
retain their reason; their period construction remains in the historical report.
The graph describes calculation provenance, not an independent reconciliation.

EBIT and net-income margins use their own period's revenue. Net income comes
from a controlled account or an explicitly mapped income-statement line; it is
never filled from pretax income less tax. Reported EBITDA growth is separate
from adjusted EBITDA growth. Pro forma EBIT/net-income margins remain not
applicable because no corresponding adjustment rule is defined.

The kernel remains the arithmetic authority. The artifact reads the same metric
recipes, period selection and prior-period rules, and uses the existing
38-significant-digit, half-even Decimal context. Missing operands and
non-positive denominators remain explicit; no fallback estimates fill them.
`validate_model_report` reconstructs the artifact from the bound inputs and
selected variant and compares its entire hash. Schema-valid results alone are
not accepted.

`exclude_unrealised=True` is an explicit house variant. The default retains the
reported bridge. The option is included in the artifact; positive unrealized
add-backs are excluded only when selected and negative deductions remain. The
embedded source artifact is the same for both variants.

The four residual lines retain their formulas and the kernel's residual notes:
other operating cash, other investing/financing cash, FX/other cash, and debt
non-cash movements. These establish arithmetic differences, not independent
reconciliation or evidence about economic causes.

## Rolling-period correction

Four fiscal-quarter labels alone did not establish a valid LTM in the imported
kernel. A reproduced one-day gap in Q2 still yielded revenue 11,519 in the
synthetic legacy case. `_rolling_days` now requires four usable, dated,
contiguous quarters covering 364–371 days. Gaps, overlaps, missing/unprovable
boundaries and longer/shorter spans cannot produce known rolling flows.
Balances remain observations at the closing date; rates are not summed.
Missing quarters retain their original missing-component diagnosis.

`ltm_columns` supplies the same verified span to statement assembly. Rolling
cash and debt opening dates now use the beginning of the rolling year rather
than the start of the displayed quarter. The internal quarter key is retained
so the metric kernel selects the right rolling frame; the artifact names the
rolling basis separately and retains its four component construction IDs,
including explicit missing placeholders.

## Qualification and remaining work

This is deterministic implementation evidence only. Evidence quality tiers
remain null with an explicit unassessed reason; they are not inferred from a
matched quotation. Analytical KPI trends and commentary remain separate model
work. The separate [canonical KPI register](canonical-kpis.md) now retains CP-1
debt and explicit earnings variants, FFO interest coverage, DCF and DCF/debt.
[Selected historical readiness](model-readiness.md) now checks four complete
quarters and their source reconciliations. Pro forma, projection integration,
full CP-1 delivery and CP-1A remain outstanding. No CLI, execution journal
or Workbench consumer is connected to this API yet. No completed-Module browser,
public-case analytical or native-host acceptance is claimed.

[Constructed-period reconciliation](period-reconciliation.md) now checks the
underlying historical accounts and source equations; it remains a separate artifact
from this Model output and does not treat residuals as independent evidence.

DCF is named in the pinned r14 references without a formula. Decision 0006 DC-4
delegates it as FCF less dividends paid; share repurchases are not deducted. The
canonical KPI register computes it; this Model output does not.

Review and verification: [initial implementation review](tasks/implementation/model-output-review.md)
and [arithmetic trace review](tasks/implementation/computation-review.md).
