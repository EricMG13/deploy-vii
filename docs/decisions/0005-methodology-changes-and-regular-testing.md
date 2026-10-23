# 0005: Methodology changes for performance and reliability; regular module testing

Date: 21 October 2026. Status: adopted. User instruction: "Your also authorised to alter
the methodology to improve performance and reliability. Include regular internal and
external testing of modules (with open router and stated model choice from my codex
chats)."

This decision amends CLAUDE.md's "preserve analytical meaning while adapting execution
boundaries". It is the explicit methodological authority that
[methodology adaptation](../methodology-adaptation.md) requires for changes beyond
packaging. The milestones are in the [development plan](../development/tasks/implementation/plan.md).

## A. Methodology changes

**Authority.** r14's execution, handoff, validation, repair, ordering, prompt and
division-of-labour rules may change where evidence shows a performance or reliability
gain.

**Guardrails.**
1. **Unchanged without a separate user decision:**
   - credit definitions and KPI formulas (DCF remains open);
   - house scales and judgment vocabularies (Recommendation 1–5, Valuation V1–V5,
     Credit Score, Fit, covenant and distress-gate words);
   - missing-data meaning (unknown is never zero);
   - r14 coverage: every responsibility keeps an owner or gets a recorded retirement.
2. **A record row per change** in `docs/methodology-adaptation.md`:
   `method clause → change → class (packaging | deterministic calculation | presentation |
   execution | analytical semantics) → gain (performance | reliability) → evidence
   before/after → affected consumers → tests`.
3. **Evidence.** Deterministic changes need offline tests. Model-facing changes need
   external results (E1/E2 below) on the same frozen case before and after. A change
   that lowers payload validity or factual accuracy in E2 is reverted.
4. **Disclosure.** A change of class "analytical semantics" is flagged in the progress
   log and in the next summary to the user.

**Initial changes adopted:**

| ID | Change | Class | Gain | Plan |
| --- | --- | --- | --- | --- |
| MC-1 | Python computes every mechanically derivable field; models return only judgments and evidence references | execution | reliability; smaller outputs | M2.7 |
| MC-2 | Numbers in all model prose appear only as resolved references (`{C#\|unit}`, `[G#]`); labels for periods, filings and instruments are allowed | presentation | reliability; no unbacked figures | M6.2 |
| MC-3 | A blocked producer degrades its consumers per edge rule instead of halting them; CP-5 always runs over the selected set | execution | reliability | M4 |
| MC-4 | Status derives from own findings plus material inherited gaps | execution | status keeps its information | M4 |
| MC-5 | Python sets each evidence item's lineage ceiling; the model may only downgrade | analytical semantics (QA input) | reliability; injection resistance | M6.3 |
| MC-6 | CP-5's mechanical checks move to Python: citation existence and quote match, cross-module figure identity, stale inputs, gap propagation. The model judges material support and contradictions only | execution | fewer tokens; reliability | M8 |
| MC-7 | A targeted repair receives only the failing step's validator issues. The budget becomes per step if the probe shows a module-wide budget is unsurvivable | execution | reliability | M2.7 (decision 0008) |
| MC-8 | Modules with disjoint, settled inputs dispatch concurrently (for example CP-1 ∥ CP-1A, CP-2 ∥ CP-4), adopted only after a measured latency gain | execution ordering | performance | M9 |
| MC-9 | Accepted artifacts are reused when scope extends; only invalidated consumers rerun | execution | performance; cost | M9 |
| MC-10 | Each module prompt carries only its declared inputs; prompt and token budgets come from measured external data, not inherited caps | packaging | performance | M2.6 onward |
| 7.11 quote-side hyphen wrap | The quote matcher (`quotes.quoted`) also joins a hyphenated line wrap on the quote side (`-`, newline and the spaces after it become `-`), as it has on the span side since task 2.10. Adopted: it widens matching only (every quote accepted before still is, a hyphen is never dropped or added, a quote with no visible text matches nothing); the owner may revert. E1 batch e1-cp1-13: GPT-6.1 Sol wrote `first-` then a newline and `priority` where the span prints `first-priority` | execution (layout artefact; analytical meaning unchanged) | reliability | M7 task 7.11 |
| 7.13 dimension prefill | Python fills each financial book's and each of its periods' `currency`, `unit`, `accounting_basis` and `entity_perimeter` with the strings of the retained `source_context` scope the model's own choices select: the book's `binding.books[].entity_id` and each period's `period_type`, `start_date` and `end_date`, by `context_binding`'s date and kind rule over the financial sources' scopes (`live/submission.prefill`, binding kind `scope-dimension`, as every hash binding since task 7.0i). The sent schema leaves the strings out; the prefill record lists every path Python wrote. A book takes the one tuple its periods' scopes share; where they share none the book is left unfilled and the attempt is rejected with one issue naming the periods and the fields (fail closed: no majority, no first-wins); a period with no matching scope is rejected with `context_binding`'s existing wording; a scope's null dimension is never written. `context_binding` and `book_issues` keep their exact-match rules. A period with no matching scope and no citations of its own is rejected by the shape check (`Field required`) rather than the binding wording; a null scope dimension is also rejected at the shape check (`Field required`), and its cause is upstream in `source_context` (task 7.14 tightens that step). **Adopted, user-approved 23 Oct 2026** (the user chose it in advance, after batch e1-cp1-13). E1 batches e1-cp1-13 and e1-cp1-14 (GPT-6.1 Sol at high): every input set's first `financials` try was rejected on dimension-string drift ("Mixed units, currency, accounting basis or perimeter" or "No matching entity/date/basis source scope"); all four of batch 13's rejections carried such drift (one masked by a quote issue), about US$0.95 a try | execution (which party writes eight identity strings; analytical meaning unchanged: the model still chooses the entity and the periods) | reliability; about one `financials` try per attempt | M7 task 7.13 |
| 7.14 scope dimension consistency | `validate_source_context` rejects, at the step the model can repair, what the 7.13 prefill cannot bind: every `historical_duration` and `period_end` scope of a financial source states `currency`, `unit`, `entity_perimeter` and `accounting_basis` ("Financial scope lacks <field>: <scope_id>"), and all such scopes of one entity across the financial sources state the same four strings, compared exactly with no normalisation ("Financial scopes of one entity disagree on <field>: ..."). Forecast and unspecified scopes are untouched; `source_context` rule d states both rules. Fail closed: it only rejects more, and a passing context gives every period of a book that matches a scope one complete tuple, the same for the book. Differences in currency, unit, perimeter or basis between one entity's historical scopes, which `source_context` used to keep as gaps ("Different source <field> values require normalization review"), are now rejections at that step (fail closed; the brief asked for the entity-wide rule); that gap now arises only from forecast or unspecified scopes, or from scopes of a non-financial source. **Adopted, user-approved 23 Oct 2026** ("apply what the batch highlights"). E1 batches e1-cp1-13 and e1-cp1-14 (GPT-6.1 Sol at high): in three of the four input sets the accepted `source_context` (about US$0.44) wrote `currency: null` on every scope and worded the FY2025 `entity_perimeter` "… and consolidated subsidiaries, with intercompany accounts and transactions eliminated" against the comparative years' "… subsidiaries as reported for the comparative year" or "… as presented comparatively in the FY2025 annual report"; only the fourth (USD, one perimeter wording) let the prefill bind | execution (validator tightening; analytical meaning unchanged: a perimeter is the consolidation perimeter, which one filing's comparative years share) | reliability; the defect is repaired at `source_context`, not rejected one step later where no repair reaches it | M7 task 7.14 |

**Candidates, recorded and not adopted (M7 task 7.10, 24 Oct 2026).** Found on the real
Caesars pack (proxy journal e1-cp1-7). The owner decides; nothing changes in code, and each
needs its own decision (and a `docs/methodology-adaptation.md` row) before adoption.

| ID | Observation | Options | Class | Status |
| --- | --- | --- | --- | --- |
| Candidate 7.10a: readiness gap scoping | An unscoped gap marks every consumer `not_ready`. Scoping all 1,251 gaps for 6 consumers is about 7,500 hex ids (about 560 KB), more than any 128k-token completion holds, so a model cannot reach `ready` on this pack through this route | gap scopes by gap class, resolved by Python; or Python pre-scoping with model confirmation (a contract change) | execution (contract change) | candidate, not adopted |
| Candidate 7.10b: BLOCK-gap extraction | A `degraded` extraction yields 160 BLOCK gaps, which block the narrative and therefore QA whatever the analyst judges; CP-1 cannot be promoted on such a pack | improve the extraction; or change the BLOCK-gap methodology | analytical semantics (gap methodology) | candidate, not adopted |
| Candidate 7.11: dimension prefill (M7 task 7.11, 23 Oct 2026) | E1 batch e1-cp1-13: three of the four `financials` rejections carried dimension-string issues; six "Mixed units, currency, accounting basis or perimeter" and three "No matching entity/date/basis source scope" issues came from the model rewriting a book's or period's `currency`, `unit`, `accounting_basis` or `entity_perimeter` instead of copying the bound scope's string. Task 7.11 states the copy rule in the prompt (financials rule i) | Python prefills the book's and every period's four dimension strings from the bound source scope (`live/submission.prefill`, as every hash binding is prefilled since task 7.0i), removing this failure class; or keep the prompt rule only | execution (contract change: the model no longer supplies the four strings) | superseded: adopted as row 7.13 above (user-approved 23 Oct 2026) |
| Candidate 7.13: locator correction (M7 task 7.13, 23 Oct 2026) | E1 batch e1-cp1-14 (code 92b249b, before the 7.11 preamble page sentence): both input sets' step repairs failed on one quote only, a statement heading cited `page:95` that sits near the end of the `page:94` span (the `locator=page:95` marker follows it). The same heading was cited one page off on four consecutive tries across batches e1-cp1-13 and e1-cp1-14, both before and after the issue text named the page | Python moves a citation to the adjacent span where its quote is unique; or keep the 7.11 preamble sentence (the page is the marker that opens the span) only, which no batch has yet exercised | execution (provenance: a correction would change what the model claimed) | candidate, not adopted; the owner decides |

## B. Regular internal and external testing

**Internal.** No model calls or credentials. Runs locally; CI runs I1 and I2 once hosted
CI is available.

| Tier | When | What |
| --- | --- | --- |
| I1 | Every change | `make check`, `make product-check` (unit, property, browser) |
| I2 | Every change to a model-facing contract, validator or prompt | Replay suite (`make replay`): recorded external responses are re-validated offline, so contracts are tested against real model output without new spend. The committed corpus holds only extracted payloads and expected outcomes for the public Caesars case and synthetic fixtures. Raw responses, telemetry and credentials stay in ignored `artifacts/` |
| I3 | Each milestone | Full product suite, browser acceptance and a bounded maintenance sweep (`docs/maintenance-sweeps.md`) |

**External.** OpenRouter, local only; CI keeps `model_calls = false`.

- **Selection.** (Superseded 22 Oct 2026 by the amendment below: the pool is GPT-6.1 Sol
  alone.) Draw uniformly at random among eligible `openai/gpt-6-luna` (Luna),
  `z-ai/glm-5.3-flash` (GLM 5.3 Flash) and the latest suitable DeepSeek (re-resolved
  and pinned per batch). Record the pool, exclusions, seed and draw before dispatch.
- **Effort and retries.** Use high by default and xhigh for cases predefined as
  difficult. Where xhigh is unsupported, use high and record the mapping. Retries stay
  on the selected model.

| Tier | When | What |
| --- | --- | --- |
| E1 | Each module completion | Qualification case on the frozen Caesars pack plus one adversarial synthetic fixture |
| E2 | Each milestone | (amended 22 Oct 2026: Sol alone; see the amendment below) Regression over every implemented module, plus a matched comparison: the same frozen case on all three eligible models in randomized order. Compares payload validity, factual accuracy against Python facts, citation errors, repairs, refusals and limitations, tokens, cost and latency |
| E3 | Weekly while development is active | (amended 22 Oct 2026: Sol alone; see the amendment below) Canary: CP-0 and the CP-1 steps on the frozen case, one draw per eligible model. Detects provider or model drift, including a new DeepSeek release. A validity drop against the last E2 opens a finding |

- **Retention.** As in `docs/testing-and-telemetry.md`: requests without credentials,
  responses, extracted outputs, events, metrics, checks and renders, failures included.
  Unknown metrics are null with a reason.
- **Reporting.** Each batch writes a summary,
  `docs/development/tasks/implementation/live-<batch-id>.md`, with no raw data. Its
  validated responses join the I2 replay corpus.
- **Budget.** Within the first US$50 batch, the plan's caps apply. Beyond it, these
  recurring caps apply ([decision 0006](0006-delegated-choices-and-orchestration.md) DC-6,
  21 October 2026), under a cumulative ceiling of US$200 including the first batch:
  - E1: US$3 per module case;
    (the CP-1 case is amended: US$10 per batch, US$12 with the CP-0 case; see the 22 Oct 2026
    amendment under DC-6 in decision 0006)
  - E2: US$15 per milestone;
  - E3: US$3 per week.

  At the ceiling, external testing pauses and the user is asked. Agents never replenish
  credit.
- **Backup.** When OpenRouter credit is exhausted, check whether native Luna is actually
  available; otherwise run the frozen case through a Claude-agent proxy (decision 0006
  DC-8). Either forms a separate cohort that never pools with OpenRouter results and
  never counts as qualification of the pool models.

**Make targets (built in M2).** `make replay`, `make live-module MODULE=<id> CAP=<usd>`,
`make live-regression CAP=<usd>`, `make live-canary CAP=<usd>`.

**Amendment, 22 Oct 2026 (user decision).** The external-test pool is the user-named set,
currently GPT-6.1 Sol (`openai/gpt-6.1-sol`) alone, at high effort for every step (also for
cases predefined as difficult). It is set in `settings/project.toml` (`[[model_tests.candidates]]`,
`default_effort`, `complex_effort`). §Selection's random draw applies only when the pool holds
more than one model. With one model, every seed selects it, and the draw is recorded as trivial
(`trivial-single-model-pool`), with the pool, eligibility, exclusions and seed recorded as before.
Eligibility checks are unchanged, so an ineligible Sol blocks the test. E2 becomes the milestone
regression on Sol alone. The matched comparison is dormant until the user adds models. E3 becomes
one Sol draw per week against the last E2, and still detects provider or model drift. The earlier
pools are superseded: Luna / GLM 5.3 Flash / latest DeepSeek (this decision's §Selection) and the
coordinator-selected Grok / Sol / Gemini probe pool (22 October 2026). Their stored outputs,
reports and replay entries are retained. The relaxation of the sent schema (decision 0008) must
be accepted by OpenAI; other providers' rows are information only.

Not verified:
- provider and model availability, effort support and pricing at batch time;
- whether a native Luna backup exists on this host;
- hosted CI (still blocked by GitHub billing; I1 and I2 run locally until then);
- that the recurring caps and ceiling suit the user (applied by delegation, decision 0006).
