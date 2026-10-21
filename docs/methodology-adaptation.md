# Methodology adaptation under the new architecture

Review: 20 October 2026. Scope: the proposed orchestrator, analytical Modules,
Python calculations, Markdown/JSON handoffs and HTML renderer. This assesses
adaptation needs; it does not implement or qualify a methodology port.

## Finding

A different execution host requires changes to packaging and evidence flow.
It supplies no analytical reason to change credit definitions, judgment criteria,
scales, missing-data treatment or decision depth. Preserve the selected method's
meaning and change the smallest execution boundary that needs adaptation.
This is a Deploy VII design recommendation, not inherited project policy.

| Earlier adaptation / issue | Needed now? | Treatment |
| --- | --- | --- |
| Explicit Inputs / Process / Outputs | Yes | Give each Module bounded evidence, responsibility, outputs and refusal/limitation behavior. |
| Tagged Markdown, source IDs and typed calculation JSON | Yes | Separate execution contexts and rendering need stable handoffs as well as narrative. |
| Reliance on M365 retrieval/memory/alias machinery | Replace where present | Use explicit inputs and tools while retaining evidence identity and meaning. |
| Python owns arithmetic | Yes | Keep formulas, units, periods, rounding and reconciliation deterministic. |
| Agreement between method prose and validators | Yes | Resolve contradictions using the intended method and a concrete case; a checker does not win automatically. |
| Full methodology rewrite for every Module | No | Retain useful wording and reasoning. Rewrite only an evidenced incompatibility or ambiguity. |
| Previous prompt-size cap and aggressive compression | Reassess | Separate contexts change token pressure. Measure before carrying over a budget or cutting reasoning. |
| Delete every register without a renderer consumer | Not automatically | Reconciliation, challenge, CP-5 and audit may still consume it. Map those uses before removal. |
| One Module equals one agent/skill | No | Group coupled reasoning where useful; split for a meaningful ownership/context boundary. |
| Earlier merge/split of analytical phases | Reassess | Preserve their reader questions and coverage; fewer files do not prove equivalence. |
| House scales and judgment rules | Method choice | Select and document them explicitly; changing provider does not change their definitions. |
| Workbook/report-format choices | Product choice | XLSX intake, calculation artifacts and display exports are separate decisions; architecture alone settles none. |

The comparison uses the restored [architecture research](architecture.md),
[follow-up evidence](recovered-follow-up-findings.md) and methodology decision
identified in the [source record](research-sources.md). Historical constraints
are comparison inputs, not adopted Deploy VII rules.

## Dependencies and completeness

CP-0 through CP-5 is the proposed core development sequence. A layer number does
not waive a selected method's dependencies. The earlier method required CP-1A's
business/transaction context before CP-2, alongside CP-0, CP-1 and MODEL. Supply
that context or explicitly limit the CP-2 result; do not silently classify it as
an optional extension simply to fit the numbering.

Optional inputs also matter: serial order may previously have supplied them on
every run. Record which were used and invalidate affected consumers when they
arrive or change. Begin sequentially until that behavior is proven.

If the selected baseline includes add-back judgments, preserve its period and
latest-judgment selection, overrides in both directions, same-date conflict
behavior and visible fallback limitations. Test supported/conflicting cases.
This illustrates semantic fidelity; it does not import an old implementation.

CP-5 evaluates evidence and consistency; validators check structure/arithmetic.
Final challenge, recommendations and synthesis need explicit ownership if the
chosen method requires them. CP-5 alone does not prove a complete decision report.
The renderer formats accepted outputs without changing analytical judgments.

## Adaptation and qualification record

Before implementing each layer, keep one compact mapping:

`method question/clause → owner/artifact → evidence → check/live case → gap`

Classify a change as packaging, deterministic calculation, presentation or
analytical semantics. Record its reason and downstream effects. Semantic changes
need an explicit methodological decision rather than an infrastructure shortcut.
Plan the next layer; do not create a complete rewrite/documentation programme.

Since 21 October 2026, [decision 0005](decisions/0005-methodology-changes-and-regular-testing.md)
authorizes methodology changes that improve performance or reliability, within its
guardrails. Definitions, scales, judgment vocabularies, missing-data meaning and r14
coverage stay fixed unless the user decides otherwise. Record each change here when it
lands:

| ID | Method clause | Change | Class | Gain | Evidence before/after | Consumers | Tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MC-3 | Dependency edges between modules (r14 upstream texts, pinned `bd71346`) | Each edge carries `block` or `restricted`; a blocked producer under a `restricted` edge degrades its consumer instead of removing it | execution | A blocked optional producer no longer removes CP-3, CP-5 and CP-6 from the report | C2 probe, before: CP-4 blocked left CP-3, CP-5 and CP-6 not runnable; after: all three run, settle `restricted` and carry "Upstream CP-4 blocked" | CP-2, CP-3, CP-4, CP-5, CP-6, CP-8, CP-MEMO | `test_edge_rule_defaults_required_block_optional_restricted`, `test_edge_rule_overrides_from_decision_0007`, `test_cp5_fan_in_is_restricted`, `test_blocked_optional_producer_does_not_halt_core_report`, `test_blocked_required_producer_under_block_rule_still_halts`, `test_blocked_required_producer_under_restricted_rule_runs_limited`, `test_unrun_stale_or_rejected_producer_never_degrades`, `test_input_status_is_bound_exactly` |
| MC-4 | Status of a module that inherits limitations | Own findings and inherited limitations are separate; only own findings or a blocked input restrict | execution | Pass is reachable downstream of an immaterial inherited note | W1 probe, before: any inherited limitation forced `restricted`, so Pass was unreachable; after: a public-case CP-1 with no own findings settles `accepted` beside CP-0's note | All modules after CP-0; CP-1 QA | `test_pass_reachable_with_immaterial_inherited_gap`, `test_module_status_derives_from_own_findings_only` |

Later qualification uses the same authorized pack, method version and scope:
exact calculation/source checks plus comparisons of material claims, conflicting
evidence, refusals and limitations. Wording may vary. A schema or HTML pass does
not prove analytical equivalence. No live runs are authorized by this document.

Not verified: clause-by-clause fidelity, live equivalence, prompt-budget benefits
or a completed methodology port; those require the chosen method and working code.
