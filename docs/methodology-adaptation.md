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
| MC-4 | Status of a module that inherits limitations | Own findings and inherited limitations are separate; only own findings or a blocked module in the input chain restrict | execution | Pass is reachable downstream of an immaterial inherited note | W1 probe, before: any inherited limitation forced `restricted`, so Pass was unreachable; after: a public-case CP-1 with no own findings settles `accepted` beside CP-0's note | All modules after CP-0; CP-1 QA | `test_pass_reachable_with_immaterial_inherited_gap`, `test_blocked_ancestor_restricts_transitive_consumers`, `test_blocked_ancestor_marker_cannot_be_spoofed_by_limitation_text`, `test_module_status_derives_from_own_findings_only` |
| MC-1 | CP-0 readiness review (`methods/cp0.md`): sources, consumer readiness, gaps, claims | `source_readiness` returns a `ReadinessSubmission` (judgments and evidence references, no hashes, no attachment sets); Python composes the stored `ReadinessReview` (`readiness-review/1`, unchanged) from it and the pack. Omitted sources and consumers become explicit not-assessed placeholders with a critical gap, never ready. The prompt states the consumer list, extraction coverage and the validator's rules; spans render `locator=page:N`. New validator rule: an absence claim contradicted by the pack's coverage is rejected | packaging (execution boundary); the absence rule is a mechanical check | reliability: probe-2 GLM draw 1 had 17 issues, 13 bracketed locators plus a cited CONTEXT pack, a CP-0 self-consumer and an attachment mismatch, none of them judgment | before: probe-2 (`live-probe-2.md`), 0 of 9 first-pass; after: the rerun (not run) | CP-0 consumers (`source_context`, `financials` and the CP-1 steps read the stored review, unchanged) | `test_live_submission.py`, `test_live_runner.py`, `test_readiness.py`, `test_replay.py` (I1, I2) |
| MC-7 | Targeted repair (decision 0005) | A repair prompt's REPAIR block carries only the failing step's issues, on that step only; the module issues where no step failed. Budget unchanged (module-wide) | execution | reliability; smaller repair prompts | before: no repair ran in probe-2 (`repair_count` 0); after: the rerun reports `repair_count` per step (not run) | every live module step | `test_live_runner.py` (repair-prompt tests) |
| MC-10 | Prompt and token budgets from measured data | Reservation prompt bound `ceil(request bytes / 3.0) + 64` instead of one token per byte; the ratio is a required setting citing probe-2 | packaging | performance: probe-2 body bounds at 289,225 tokens instead of 867,545 (DeepSeek reservation about US$0.087 instead of US$0.279 at pinned prices) | before: 867,481 request bytes, 154,609 prompt tokens billed (5.61 bytes per token); after: the rerun's billed tokens against the bound (not run) | reservation ledger, caps | `test_live_runner.py` (bound against probe-2 figures, property test), `test_live_credential.py` (settings) |
| Strict schema | Contract packaging (task 2.7a, decision 0008) | `response_format` sends the strict-mode copy of each step schema and the system prompt prints the same text; nulls for omitted defaults are resolved before the journal. Contracts and hashes unchanged | packaging | reliability: probe-2 Luna x3 HTTP 400 `invalid_json_schema` on the untransformed schema (US$0) | before: probe-2 Luna refusals; after: the rerun (not run) | every live step | `test_live_schema.py` |
| Quote-matcher tolerance | Verbatim evidence (`methods/cp0.md`: located content, exact locators; every citation check; tasks 2.9 and 2.10, decision 0005) | One matcher (`deploy_vii.quotes`) for every citation check. Task 2.9: both sides compared after removing soft hyphens, mapping curly quotes, dashes and the minus sign to ASCII and collapsing whitespace runs. Task 2.10: on the span side, the span is also tried with each hyphenated line wrap joined (`hyphen-wrap`). Task 7.11 (E1 batch e1-cp1-13): the same join on the quote side, so a quote that breaks the line after a hyphen the span prints whole matches; no hyphen is dropped or added, and every quote accepted before still is. The verbatim-substring rule is kept (one contiguous substring of the span the locator names; case and every other character exact; no fuzzy match, no other span); only what counts as the same bytes is widened. Issue text names the normalisation applied | execution boundary (layout extraction artefacts; analytical meaning unchanged) | reliability: probe-3 Luna f136b227 and GLM 76fc5c95 were rejected only for whitespace and negated-coverage artefacts; probe-4 Sol 9594d016 p135 only for a line-wrap hyphen | before: probe-3 (`live-probe-3-analysis.md`), probe-4 (`live-probe-4-analysis.md`); after: revalidation on the same pack (f136b227, 76fc5c95 accepted; 9594d016 3 to 2 issues); next probe not run | every citation check: CP-0, CP-1 steps, definitions, the journal's candidate check | `test_readiness.py` (normalisation, hyphen-wrap, property tests), `test_replay.py` |
| Consumer purpose | CP-0 consumer readiness (`methods/cp0.md`: "affected consumers"; task 2.10, decision 0005) | The `source_readiness` CONTEXT block lists each consumer with its module registry title and purpose (`methodology.json` `title`, `purpose`, verbatim) instead of its id alone; rule b says that text states what the consumer needs. The block stays non-citable; no new definition, scale or brief content; validator unchanged | execution boundary (the model is told what each consumer needs; analytical meaning unchanged) | reliability: probe-4 Sol's accepted CP-0 (944e569a) judged all seven id-only consumers CONDITIONAL, naming the module brief as the missing source, and the CONDITIONAL CP-1 then gated the chain | before: probe-4 (`live-probe-4-analysis.md` sections 4 and 5); after: the next probe (not run) | CP-0 consumers (the T8 commands that gate CP-1 and later modules) | `test_live_prompts.py`, `test_live_runner.py` |
| MC-1 (CP-1A) | CP-1A business and transaction fact pack (r14 `cp-1a-business-transaction-fact-pack`, sha256 `3bed15de…`): the 22 registers, the Five Categories, Evidence → Risk Mechanic → Credit Implication, the absorbed CP-2C phase; task 7.2 | One live step `business_context` after CP-0 returns a `BusinessContextSubmission` (judgments, closed-enum categories and verbatim quotes only); Python composes the 22 registers and `cp1a.cp_model_snapshot_fields` with r14 table ids and column labels, writes the identity, ids, tags, source traces and statuses, and checks the four `cp1a.*` rules on the composed registers. Text is run text: figures only as references to the facts of a settled CP-1 the journal binds as a context input; CP-1A has no amounts of its own. Conflicts are logged, never reconciled. Details: `docs/development/business-context.md` | packaging (execution boundary) | reliability: no cell, id, figure or consumer the model can invent; every fact row cited; consumers fixed by the registry | before: none (CP-1A unrun); after: E1 (not run; the coordinator runs it) | CP-2 (restricted edge, decision 0007), CP-3, CP-5, CP-6, CP-3C, CP-MODEL snapshot fields; Front Page company, profile and transaction blocks | `test_business_context.py`, `test_live_prompts.py`, `test_live_runner.py`, `test_execution.py`, `test_bindings.py`, `test_delivery.py`, `test_credit_snapshot.py` |
| T2D.8 derivation | CP-2C Step 9 scoring (`REF_CP-2C_STEPS.md` 6, `CP-2C_SYSTEM_REFERENCE.md` 3): nine dimensions scored 1 / 3 / 5 or Not Scorable; a composite only with at least four evidence-supported dimensions, else Not Scorable and Insufficient Information unless one clearly High-risk documented action | Not asked of the model. `governance_sponsor_score` scores each dimension from its evidenced governance rows: all Supportive 1; Extraction-Oriented or Creditor-Adverse with no Supportive 5; any other mix 3; none Not Scorable. The composite is the most adverse dimension score and sets the level (1 Low, 3 Medium, 5 High); with fewer than four scored, an adverse row on High evidence is the High-risk action. No weights or averages. A dimension's Evidence Quality is the strongest among the rows that decided its score (High over Medium over Low; Insufficient when none): the score rests on those rows, so the best-supported one states how well-founded it is, and a weaker row beside it cannot lower a score it did not set | analytical semantics (narrowed): r14 states the scale, the four-dimension floor and the override but leaves the per-dimension score and the composite to the analyst; here they are a fixed rule over the model's categorised directions, and the composite is conservative (most adverse) | reliability: a reproducible score traced to cited rows; no model-set number | before: none; after: unit and property tests; live E1 not run | T2D.8 register, the risk level in Limitations, CP-2's sponsor and governance read | `test_business_context.py` (rubric, composite, override, order-free property, register) |
| T2D.9 derivation | CP-2C Sponsor risk-level drivers (Risk-Level Driver, Evidence, Risk Mechanic, Credit Implication, Evidence Quality, Source Trace, Countervailing Evidence, Limitation) | Not asked separately: Python emits the credit translations row for row. The Risk-Level Driver is the translation's theme, a closed enum (Revenue Durability, Margin/CF Risk, Concentration Risk, Sponsor Alignment, Key Uncertainties), not a free driver name. Evidence Quality is the translation's confidence, level for level (r14 uses the same four grades). Countervailing Evidence is the text of the logged conflicts the row names, else `Insufficient Information: no logged conflict counters this driver` | analytical semantics (fix round 1 reclassification): r14 grades a driver's evidence and names the driver itself; here the grade is the model's confidence in the translation and the driver is one of five themes. Chosen so that one judgment per driver cannot drift from a second list, at the cost of r14's free driver naming and a separate evidence grade | reliability: one judgment per driver, no second list to drift from the first | before: none; after: unit tests; live E1 not run | T2D.9 register (Evidence) | `test_business_context.py` |

Later qualification uses the same authorized pack, method version and scope:
exact calculation/source checks plus comparisons of material claims, conflicting
evidence, refusals and limitations. Wording may vary. A schema or HTML pass does
not prove analytical equivalence. No live runs are authorized by this document.

Not verified: clause-by-clause fidelity, live equivalence, prompt-budget benefits
or a completed methodology port; those require the chosen method and working code.
