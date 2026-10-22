# 0009: Pathway presets and the `not_in_pathway` status

Date: 21 October 2026. Status: adopted under plan M3.5 (decision
[0004](0004-design-system-frontend.md) item 3 and item 6 reserve this decision).

## Context

The design system has six Pathway Front Pages. A Run so far had one hard-coded module
list, and `empty_view` marked every module `unrun`, so a Front Page could not tell "this
module has not run yet" from "this Pathway never asks for it". Showing the second as
"Not run" invites a rerun that cannot help; showing the first as "Not in this Pathway"
hides work still owed.

## Decision

1. **Six Pathways.** Ids, titles and questions follow the cards of
   `design/reference/rbot-report.dc.html`. `report_view.pathways()` returns them in FP
   order; the module sets live in `contracts.PATHWAY_MODULES` so `Run` and the report view
   share one table.

   | Id | Title | Question |
   | --- | --- | --- |
   | `credit_snapshot` | Credit Snapshot | Should we own this issuer, in which instrument, and why? |
   | `earnings_update` | Earnings Update | What did the period change, and does the credit view move? |
   | `relative_value` | Relative Value | Which instrument is best compensated for its risk, and at what level? |
   | `covenant_refinancing` | Covenant & Refinancing | Which provisions protect creditors, and can the issuer refinance? |
   | `distressed_restructuring` | Distressed & Restructuring | Is the distress gate met; which path and fulcrum; what recoveries? |
   | `portfolio_decision` | Portfolio Decision | Should each portfolio own it, how much, and which instrument? |

2. **Requested modules** (the modules the Front Page asks for; required producers are
   added by `registry.dependencies` when a plan or view is built):

   | Pathway | Requested modules |
   | --- | --- |
   | Credit Snapshot | CP-0, CP-1, CP-MODEL, CP-1A, CP-2, CP-4, CP-3, CP-5, CP-6 (today's default) |
   | Earnings Update | CP-0, CP-1, CP-MODEL, CP-1B, CP-1D, CP-5 |
   | Relative Value | CP-0, CP-1, CP-MODEL, CP-1C, CP-2, CP-2D, CP-3, CP-3C, CP-3D, CP-5 |
   | Covenant & Refinancing | CP-0, CP-1, CP-1A, CP-2, CP-2D, CP-4, CP-3C, CP-5 |
   | Distressed & Restructuring | CP-0, CP-1, CP-1A, CP-2, CP-2A, CP-2G, CP-2H, CP-4, CP-4C, CP-5 |
   | Portfolio Decision | CP-0, CP-1, CP-MODEL, CP-2, CP-3, CP-5, CP-6, CP-8 |

   **Amendment (task 6.5):** a preset whose composition holds a block the Model destination
   owns (`_Spec.owner` `MODEL`: Credit Snapshot and Earnings Update through their chart
   strip, capital structure, EBITDA adjustments and financials blocks, Relative Value and
   Portfolio Decision through capital structure) also requests CP-MODEL, listed right after
   CP-1; Covenant & Refinancing and Distressed & Restructuring are unchanged (FP 04 prints
   a MODEL-owned maturity wall, which has no spec yet). Consequence, asserted by
   `test_cp5_cannot_begin_while_a_requested_cp_model_has_never_run`: CP-5 follows every
   selected analyst, so in these presets `begin("CP-5")` is refused ("upstream is unrun")
   until CP-MODEL has a head; CP-MODEL stays `unrun` until plan task 7.1a (CP-MODEL deterministic
   publication) gives it a head, so CP-5 cannot start under them before then.

   **Portfolio Fit is pending an owner (plan M10).** It is not a module of any Pathway;
   the `portfolio-fit` block exists in the compositions below and shows its honest state
   until a module owns it. Portfolio Decision adds Portfolio Fit to its set at M10.

3. **Front Page composition.** Block ids in order, from each Front Page's outline in
   `rbot-fp-0N-*.dc.html`. "The call" is not a block: the sticky call band is
   `ReportView.call`. Ids that bindings already name (`financials-credit-metrics`,
   `capital-structure`) keep those spellings.

   | Pathway | Blocks |
   | --- | --- |
   | Credit Snapshot (FP 01) | key-findings, company-operating-model, model-chart-strip, capital-structure, financials-credit-metrics, strengths-weaknesses, relative-value, company-profile, transaction-summary, portfolio-fit, committee-challenge, what-changed |
   | Earnings Update (FP 02) | headline-results, variance-drivers, kpi-changes, guidance-signals, ebitda-adjustments, metric-strip, watch-items, financials-credit-metrics, historical-performance, company-profile, portfolio-fit, what-changed |
   | Relative Value (FP 03) | instrument-levels, yield-against-maturity, market-against-fundamentals, compensation-preference, peer-positioning, recommendation-portfolio-fit, capital-structure, loan-hy-relative-value, credit-view, what-changed |
   | Covenant & Refinancing (FP 04) | covenant-tests-headroom, liquidity-runway, maturity-wall, funding-gap, red-flags, lender-protection-score, refinancing-paths, capacity, lme-creditor-exposure, ebitda-definition, documents-structure |
   | Distressed & Restructuring (FP 05) | distress-gate, recovery-by-class, value-allocation-claims, liquidity-runway, funding-gap-lme, covenant-levers, rating-triggers, restructuring-paths, instrument-decision, portfolio-fit, what-changed |
   | Portfolio Decision (FP 06) | portfolio-recommendation, portfolio-fit, instrument-decision, binding-limitations, strengths-weaknesses, thesis-catalysts-challenge, capital-structure, what-changed |

   The composition is fixed per Pathway. FP 02 and FP 03 outline `portfolio-fit` and
   `what-changed` as "n/a" and FP 05 swaps in "Recoveries" (n/a) when the gate is not met:
   those blocks stay in the composition and render in the `absent` or `not_run` block
   state with a note, never removed. FP 05's default composition (gate unclear) is the
   preset; with the gate not met, `recovery-by-class` renders `absent` and
   `value-allocation-claims` renders `absent`. FP 04's outline has no Portfolio Fit block
   (its card says "Fit not in this Pathway"), so that Pathway has none.
   Modules the design's navigator lists but a preset does not request (for example
   CP-1B in Credit Snapshot) appear in the navigator footer as "Not in this Pathway".

4. **`not_in_pathway` is not `unrun`.** `Status` gains `not_in_pathway`, shown as
   "Not in this Pathway" with its own icon (decision 0004 item 6). `unrun` means the module
   is in scope and has not run (an action is owed); `not_in_pathway` means the Run will not
   execute it. The scope is the Run's requested modules plus their required producers
   (`registry.dependencies`), so Portfolio Decision, which lists CP-2 but not CP-1A, still
   shows CP-1A as `unrun`. `render.empty_view` assigns the status; an unknown module id
   raises. A `not_in_pathway` module view carries no facts, tables, claims or artifact
   hash, like `unrun`, and is allowed in an accepted view.

5. **`run/2`.** `Run.schema_version` becomes `run/2` and gains `pathway: PathwayId`,
   default `credit_snapshot`. `requested_modules` defaults to the Pathway's preset and an
   explicit value overrides it (the view scope then follows what will execute). `run/1`
   documents are refused, not upgraded: no committed fixture or document holds a `run/1`
   Run (an operator's unreviewed local run files would need re-creating). Fixtures that
   build a `Run` do not name the schema. `run/2` also changes the hashes of the
   `preparation-request/1`, `prepared-pack/1` and `source-context/2` documents that embed a
   Run, without a literal of their own: old documents are rejected through the `run/2`
   literal (a test covers a `run/1` request and prepared pack).

## Consequences

- `execution.py` still plans from `Run.requested_modules`; only its view builder changed.
- Every builder of a `View` takes the status of modules that have not run from
  `registry.idle_statuses(run)`: `empty_view`, `delivery.cp0_view` (modules other than CP-0)
  and `ExecutionStore.view` (modules without a head). An Earnings Update run therefore
  shows CP-2 as `not_in_pathway` from all three; a test covers this.
- `contracts.Module` shares the `Status` type, but a `Module` with status `unrun` or
  `not_in_pathway` may carry no facts, claims or tables (the error names the status).
  `Run.requested_modules` must hold at least one module.
- The legacy shell prints the raw status text until the M3 shell rebuild (Task D).

Not verified:
- the FP 05 gate-not-met composition and the n/a block states, which no code renders yet;
- that the module sets match the intended analytical scope of each Pathway beyond the
  brief and the design navigators (taken from the brief, not re-derived from the methodology);
- Portfolio Fit's eventual module id and its place in Portfolio Decision's set (plan M10).
