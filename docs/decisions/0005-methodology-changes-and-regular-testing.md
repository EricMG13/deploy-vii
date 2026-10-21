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

## B. Regular internal and external testing

**Internal.** No model calls or credentials. Runs locally; CI runs I1 and I2 once hosted
CI is available.

| Tier | When | What |
| --- | --- | --- |
| I1 | Every change | `make check`, `make product-check` (unit, property, browser) |
| I2 | Every change to a model-facing contract, validator or prompt | Replay suite (`make replay`): recorded external responses are re-validated offline, so contracts are tested against real model output without new spend. The committed corpus holds only extracted payloads and expected outcomes for the public Caesars case and synthetic fixtures. Raw responses, telemetry and credentials stay in ignored `artifacts/` |
| I3 | Each milestone | Full product suite, browser acceptance and a bounded maintenance sweep (`docs/maintenance-sweeps.md`) |

**External.** OpenRouter, local only; CI keeps `model_calls = false`.

- **Selection.** Draw uniformly at random among eligible `openai/gpt-6-luna` (Luna),
  `z-ai/glm-5.3-flash` (GLM 5.3 Flash) and the latest suitable DeepSeek (re-resolved
  and pinned per batch). Record the pool, exclusions, seed and draw before dispatch.
- **Effort and retries.** Use high by default and xhigh for cases predefined as
  difficult. Where xhigh is unsupported, use high and record the mapping. Retries stay
  on the selected model.

| Tier | When | What |
| --- | --- | --- |
| E1 | Each module completion | Qualification case on the frozen Caesars pack plus one adversarial synthetic fixture |
| E2 | Each milestone | Regression over every implemented module, plus a matched comparison: the same frozen case on all three eligible models in randomized order. Compares payload validity, factual accuracy against Python facts, citation errors, repairs, refusals and limitations, tokens, cost and latency |
| E3 | Weekly while development is active | Canary: CP-0 and the CP-1 steps on the frozen case, one draw per eligible model. Detects provider or model drift, including a new DeepSeek release. A validity drop against the last E2 opens a finding |

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

Not verified:
- provider and model availability, effort support and pricing at batch time;
- whether a native Luna backup exists on this host;
- hosted CI (still blocked by GitHub billing; I1 and I2 run locally until then);
- that the recurring caps and ceiling suit the user (applied by delegation, decision 0006).
