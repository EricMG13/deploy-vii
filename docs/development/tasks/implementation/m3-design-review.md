# M3 design re-baseline review (tasks 3.8 and 3.9)

Dated 21 October 2026. Scope: the Credit Snapshot Front Page build and its browser
acceptance, on top of tasks A to D. Author: Task E worker (confidence review, no tournament:
no key-area logic beyond the already-reviewed `validate_bindings`).

## What changed

- `report_view.build(view, pathway, maps)` replaces the idle Front Page in every production
  path: `render()` builds when no report is passed, which covers `delivery`, `statement_view`,
  `interface_view` and `register_view`. `idle_report_view` is removed; tests build the honest Front Page with `build` over an empty view.
- Unbound or doubly bound facts stop the build (`validate_bindings`); nothing is placed by
  guess. Blocks no binding fills show `not_run`, `not_in_pathway`, `blocked` or `absent`.
- `T4.10` feeds `model-chart-strip`, `T4.17` feeds `capital-structure`; `Block.tabs` carries
  the FP 01 tabs. `bindings.RAIL_DESTINATIONS` names Evidence, Limitations and the header.
- HTML cell text goes through `display.format_value` with the report-wide `G#`; the r14
  Markdown transport keeps `null` in `render.markdown_display`.
- Acceptance: structure against FP 01, per-platform screenshot baselines (stdlib PNG
  decoder), zoom, keyboard path, chart/table-twin parity, zero network, computed field parity.

## Confidence review findings

1. Unbound fact crashes a preview. By design (fail closed); every shipped producer's output
   binds, shown by tests over CP-0, statements, interface and registers.
2. A known text fact spelled `null` or `nan`, or empty text, fails `Cell` or `format_value`.
   Fail closed by design; no shipped fixture produces one.
3. Page size: the report view adds about 10 MB to a 59 MB complete CP-1 preview (8,161
   passports). Acceptable; the module data already dominates. Tabs build lazily in the DOM.
4. Screenshot baselines are darwin only. CI runs Linux, where the test skips with a stated
   reason until Linux baselines are generated and reviewed.
5. Charts are not derived from registers: the register data has generic columns, so no
   mapping to S.1 to S.4 exists. The strip shows the KPI dashboard as a table; charts appear
   only where a producer supplies them (the synthetic fixture reads its marks from facts).
6. Period-grid groups and the base column come from column-label classes (Q, FY, LTM, PF,
   OPEN); a grid with any other label stays ungrouped. Absent columns are those with no
   settled cell.

7. Schema versions advanced: `Fact.decimals` and `TableRow.row_kind` serialise as defaults, so
   every module hash would otherwise change silently. `module/3` and `view/3`
   became `module/5` and `view/4`; `execution` stays `execution/4` on this lane. `module/4` is
   the M4 lane's shape (`inherited_limitations`) and `execution/5` is the M5 lane's (content-addressed
   blobs), so this lane skips `module/4`; the merged contract carries both, and the merged store
   will be `execution/5` embedding `module/5`. The old versions are rejected with the
   explicit-version message. Artifacts hashed under the old versions re-hash differently
   under the new ones; old stores stay intact and are not migrated.

## Open

Real CP-0 and CP-1 rendering acceptance (M7); Linux baselines; a producer for the "condition"
block state (the fixture sets it by hand).
