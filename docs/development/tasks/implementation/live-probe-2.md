# Live batch probe-2

- Command: probe
- Seed: 1305688769
- Cap: 10 USD; reserved 0, spent 0.845304855990, remaining 9.154695144010
- Catalog: /Users/ericguei/Documents/DEPLOY VII/.claude/worktrees/focused-cray-a5417d/.superpowers/sdd/plan/inputs/openrouter-models-2026-10-21.json (sha256 b17fc211fe65e4347e6808adbb2d35b4d2106aca90e690a81fcc5e66c6b89c9f), looked up 2026-10-21T20:31:36Z
- Registry modules with a live step contract: 2 of 25
- Cells planned: 9; steps run: 9
- Stopped: no

## Pool

| Model | Eligible | Reason |
| --- | --- | --- |
| openai/gpt-6-luna | yes |  |
| z-ai/glm-5.3-flash | yes |  |
| deepseek/deepseek-v4.1-flash-1017 | yes |  |

## Steps

| Cell | Case | Step | Model | Seed | Attempt | Status | Class | USD | Issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| probe-00 | probe | source_readiness | openai/gpt-6-luna | 1305688769 | 2d1d9f0f-c9de-41be-b326-6c890a572756-source_readiness-1 | no-response | http_error | 0 | 0 |
| probe-01 | probe | source_readiness | openai/gpt-6-luna | 1305688770 | ea0af6cb-f58e-4c3c-b394-937a3702b2a8-source_readiness-1 | no-response | http_error | 0 | 0 |
| probe-02 | probe | source_readiness | openai/gpt-6-luna | 1305688771 | f818a0b6-ab0a-412c-b03d-de9e2814294d-source_readiness-1 | no-response | http_error | 0 | 0 |
| probe-03 | probe | source_readiness | z-ai/glm-5.3-flash | 1305688777 | d3497b71-cf39-4106-9751-e7a031ae3948-source_readiness-1 | rejected | ok | 0.002417062305 | 17 |
| probe-04 | probe | source_readiness | z-ai/glm-5.3-flash | 1305688779 | 3e3a9bbc-c5b3-442d-84fb-cb38e89b9322-source_readiness-1 | rejected | ok | 0.001819983555 | 1 |
| probe-05 | probe | source_readiness | z-ai/glm-5.3-flash | 1305688788 | a7bf53ae-3da6-4f65-9786-f6cc44dee8e9-source_readiness-1 | rejected | ok | 0.00266381013 | 1 |
| probe-06 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1305688790 | d7caf360-d6d6-4f1c-8e57-af5aa66de00a-source_readiness-1 | no-response | http_error | 0.2794680 | 0 |
| probe-07 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1305688793 | 61c37274-b5d8-47f0-b53b-4f08467fffb2-source_readiness-1 | no-response | http_error | 0.2794680 | 0 |
| probe-08 | probe | source_readiness | deepseek/deepseek-v4.1-flash-1017 | 1305688794 | b8416076-bc7b-48a0-9300-0cb0f82fadf2-source_readiness-1 | no-response | http_error | 0.2794680 | 0 |

## Cohorts

| Cohort | Attempts | Accepted | Rejected | Pooled | Qualification |
| --- | --- | --- | --- | --- | --- |
| openrouter-pool | 9 | 0 | 3 | yes | not decided here |

## Scope

CP-1 steps (`source_context`, `financials`) did not run because every `source_readiness` attempt was rejected or failed; plan 2.6 asked for them, so probe-2 did not meet that scope.

## Analysis

Sections 1-6 of the probe-2 analysis (dv-research, 21 October 2026), copied verbatim apart from heading levels. `SRC` = `src/deploy_vii/` at `claude/m2-lane` ac56e72; `ART` = `artifacts/model-tests/probe-2/probe/<model>/<attempt>/`. Task 2.7a fixed defects 5.1-5.3, the text half of 5.7 and the replay gap of section 6, and this record states the 5.9 scope; 5.4-5.6, 5.8 and the ordering half of 5.7 remain open (task 2.7b covers prompt wording, locators, the MC-1 skeleton and the prompt bound).

### 1. Summary by model

All 9 cells ran `source_readiness` only. Plan 2.6 also asked for `source_context` and `financials`; no cell reached CP-1, so there is no evidence on those steps or on `FinancialSubmission`.

| Model | First-pass valid | Status / class | Cost (ledger) | Tokens (prompt / completion) | Latency |
| --- | --- | --- | --- | --- | --- |
| openai/gpt-6-luna ×3 | 0 of 3 | no-response / http_error (HTTP 400 `invalid_json_schema`, "Missing 'limitation'") | US$0 (known-zero, "refused before inference") | none reported | 0.63, 0.69, 1.30 s |
| z-ai/glm-5.3-flash ×3 | 0 of 3 | rejected / ok, finish_reason `stop` | 0.002417 + 0.001820 + 0.002664 = US$0.006901, provider-reported | 154,609 / 14,161 (reasoning 5,696); 154,609 / 9,711 (2,174); 154,609 / 16,000 (8,280) | 175.3, 133.6, 206.3 s |
| deepseek/deepseek-v4.1-flash-1017 ×3 | 0 of 3 | no-response / http_error ("HTTP 200: A Timeout Occurred"), `unreconciled: true` | 3 × 0.279468 = US$0.838404 = the reservation, not a measured cost | none reported | 301.8, 300.6, 303.5 s |

- Batch spend 0.845305 = 0.838404 + 0.006901; DeepSeek reservations are 99.2 % of it.
- GLM cached tokens were 130,806 of 154,609 on every draw (prefix cache); cold-cache cost is not measured.
- Source: `metrics.json` in each attempt directory.

### 2. Issue classes and root causes

**A. Luna: strict-schema `required` (runner defect).**
- `response_format()` sends Pydantic's `model_json_schema()` unmodified with `strict: true` (`SRC/live/prompts.py:123-127`). Pydantic leaves any defaulted field out of `required`.
- `Claim.limitation: str | None = None` (`SRC/contracts.py:151`) is one such field. OpenAI requires every property in `required` and says so in `response.json`.
- OpenAI reports only the first violation. Likely next: `SourceAssessment.limitations`, `ConsumerReadiness.missing_source` and `limitations`, `ReadinessGap.citations`, `ReadinessReview.schema_version` (`SRC/readiness.py:36,46-47,65,69`).
- `live-runner.md:226-228` already flagged strict-mode acceptance of `default` as unknown; `pattern` and `minLength` acceptance is also unknown.
- The 400 costs US$0, so Luna is a cheap test of any corrected schema.

**B. DeepSeek: upstream 504 delivered inside an HTTP 200 (client defect, provider cause).**
- `response.json`: `http_status: 200`; body ≈1.2 KB whitespace then `{"id":"gen-…","error":{"message":"A Timeout Occurred","code":504,"metadata":{"error_type":"timeout"}}}`.
- Latency 300.6–303.5 s is far below the runner's own 600 s timeout (`SRC/live/runner.py:69`, `SRC/live/client.py:24`; manifest `timeout_s: 600.0`), so the 504 is upstream at ~300 s.
- Whitespace-then-error is consistent with a gateway that committed a 200 and padded the connection before the upstream failed (inference; OpenRouter docs not checked).
- `_classify` (`SRC/live/client.py:278-286`) only inspects body code 402; the embedded 504 becomes `http_error`. The `timeout` class (`client.py:244`) is reachable only from a local `TimeoutError`.
- Cost: `_cost` (`runner.py:425-443`) sees no usage and no 4xx, returns "unknown", charges the full reservation. The `gen-…` id is in the body but `provider_request_id` stayed null (`_answer` never reached).
- Whether DeepSeek/OpenRouter bill a timed-out call is unknown from these files.

**C. GLM draw 1 (17 issues): mostly runner and contract, partly model.**
- *Bracketed locators (runner defect), 13 of 17 issues.* The prompt renders spans as `[{locator}] {text}` (`SRC/live/prompts.py:93-95`), so the model sees `[page:1]`; the real locator is `page:1`. The model copied the brackets (`output.md` `"locator": "[page:1]"`). The validator matches exact strings (`SRC/readiness.py:90-92`), so each fails; the quote substring check never ran for these citations.
- *Locator format varies by draw.* Draw 1 `[page:N]`; draw 2 (`3e3a9bbc`) bare `page:N` plus invented `prepared-pack.run.sources[0]` and `page:12 to page:181`; draw 3 (`a7bf53ae`) `[page:1] (cover page)`, `[page:11] → [page:181] (continuity)`.
- *`prepared-pack` offered as a citable block but not citable (contract design).* Prompt presents it as a SOURCE block (`prompts.py:160`); `citation_issues` indexes only `pack.sources` (`readiness.py:83-88`) → "Unavailable or changed source: prepared-pack", and listing it as a source produces "Assess every prepared source exactly once" (`readiness.py:107-110`).
- *Consumer set not given to the model (contract design).* Validator requires `plan(requested_modules)` minus {CP-0, CP-MODEL, CP-MEMO, CP-OS} (`readiness.py:111-116`); the model returned 8 consumers including CP-0; the prompt never states the set.
- *Citation attachment rule.* "Consumer citation not in its attachment set: CP-1" (`readiness.py:176-177`): CP-1 cites `prepared-pack`, not in its `source_ids`.
- *Content error (model behaviour).* All three GLM outputs say pages 13–180 are absent and derive BLOCKED readiness for CP-1–CP-4 from that. `request.json` contains `[page:13]`…`[page:195]` with text (page 13 "Cautionary Statements…", page 100 "Item 14…"). Usage shows 154,609 prompt tokens billed, which argues against provider truncation but is not proof. No validator checks claims about absence.

**D. GLM draws 2 and 3 (1 issue each): validation masked (validator design).**
- Both fail the Pydantic parse, not the semantic validator. The single issue string holds 7 errors: "non-ready consumer requires limitations" on `consumers.1`–`consumers.7` (`readiness.py:49-52`). The cross-field rule is not in the schema, `limitations` is not in `required`, and the prompt does not state the rule (`prompts.py:153-154`).
- Semantic checks never ran on these two draws; their citations are unscored (draw 3's annotated locators would fail).
- The issue text embeds `errors.pydantic.dev/2.14` and truncated `input_value` reprs: brittle for replay (`issues-changed` on a library upgrade) and bulky for MC-7 repair prompts. The report's Issues column shows "1" for 7 errors.
- Draw 3: `completion_tokens` = 16000 = `max_tokens` with finish_reason `stop` and complete JSON — a coincidence to watch.

### 3. Cost

- Ledger vs reservation: GLM charged = provider `usage.cost` (reservations 0.037655 each, charged ≈6 % of reserved); Luna 0 of 0.185509 each; DeepSeek charged = reservation 0.279468, `cost_basis: unknown`, `unreconciled: true`.
- DeepSeek reconciliation: US$0.838 is a hold, not a measured charge. Plan acceptance "the ledger reconciles to provider usage" (`plan.md:231`) is unmet for 3 of 9 attempts. The ledger replays only `reserve` and `settle`, settle once per attempt (`SRC/live/ledger.py:163-188,260-286`); a correction needs a new event type or a documented note. The three `gen-…` ids are in each DeepSeek `response.json` (not looked up).
- Prompt size: each body ≈867 KB with the whole 195-page 10-K in one message plus the pack block and schema; not split by page or section. Follows MC-10 literally, not its intent ("prompt and token budgets come from measured external data", decision 0005). Measured prompt tokens 154,609 vs the runner bound 867,545 (one token per byte, `runner.py:124-126`): 5.6× inflation on the prompt side. Illustration: at DeepSeek's pinned prompt price 3e-7, 154.6k tokens ≈ US$0.046 vs 0.279 reserved.
- Guardrails: US$0.845 against a US$10 cap; E1 per-module US$3 not approached; but the bound eats headroom (a CP-1 batch of 3 steps × 9 draws carrying the 10-K reserves ≈US$0.19–0.28 per Luna/DeepSeek call).

### 4. Recommendations for 2.7

- **MC-1 (Python pre-fills mechanical fields): evidence supports.** Every verified GLM issue in draw 1 is mechanical: locator strings, source set, consumer set, attachment sets. Direction: Python supplies the source and consumer skeleton and resolves `source_sha256` and locator from `source_id` + quote; the model returns judgments and quotes. Hash copying was correct in draw 1. Python could also compute extraction coverage (the page-gap claim).
- **MC-7 (step-scoped repairs, per-step budget): evidence insufficient.** `repair_count` 0 on all attempts; one step ran. Precondition supported: normalise Pydantic issue text before it feeds a repair prompt.
- **`FinancialSubmission` split: evidence insufficient.** `financials` not exercised.

### 5. Runner defects to fix before any rerun

1. Strict schema: transform the `response_format` schema (`prompts.py:123-127`) so every property is in `required`, defaulted fields nullable, `default` handled; verify per step against Luna (US$0 on a 400); unit test that every object node has `required` == property keys.
2. Embedded error in a 200 body (`client.py:261-291`): map body `error.code` 504/408 or `metadata.error_type == "timeout"` to `timeout`; capture body `id` as `provider_request_id`; decide retryability (each retry reserves another US$0.28 for DeepSeek).
3. Charge reconciliation (`runner.py:425-443`, `ledger.py`): post-batch lookup by `gen-…` id and a ledger adjustment event; until then label DeepSeek rows "reservation held", not cost.
4. Locator rendering (`prompts.py:93-95`): stop wrapping locators in brackets; explicit `locator=page:1` or Python-resolved locators.
5. Citable `prepared-pack` (`prompts.py:160` vs `readiness.py:83-88`): exclude from citable blocks and say so, or accept with its own validation.
6. Prompt states what the validator enforces: exact consumer set (CP-0 excluded), source id list, non-ready consumers need limitations, `source_ids` must include every cited source.
7. Validator ordering and text: run semantic checks even when Pydantic fails where possible; report failing field paths in short form without the library URL.
8. Prompt bound (`runner.py:124-126`): replace 1-token-per-byte with a measured ratio; sizing the prompt to declared sections is a separate MC-10 question.
9. Probe scope: the report should state when CP-1 steps did not run and why; plan 2.6 scope was not met by probe-2.

### 6. Replay-corpus seeding

Rules (`docs/development/live-runner.md:162-182`): `live corpus` refuses no-response attempts; an unregistered pack hash replays as `stale-inputs`. Coordinator trial: entries for the three GLM attempts failed `tests/product/test_replay.py:53` (`entry["pack"]` must name a `replay_support.PACKS` builder; only synthetic-cp0/cp1 exist) and regenerated `expected.issues` were Pydantic shape errors rather than the live validator's list.

- Usable (expected `rejected`): GLM `d3497b71…` (17 issues; semantic validator ran; stays valid after a prompt fix since replay checks payload vs validator). GLM `3e3a9bbc…` and `a7bf53ae…` pin Pydantic wording (brittle): seed after issue-text normalisation or accept `--replace`.
- Caveat: the Caesars pack hash `0132418198863b1c7b4fbad4ffc4621fec852eec794b53b98ad450ecc23f776b` must be registered as a replay pack builder (or the entries carry a skip-with-reason) or they replay as `stale-inputs`.
- Not usable (6 of 9): Luna ×3 (400, no payload), DeepSeek ×3 (504 in a 200, no payload). Keep their `response.json` bodies as client-classification fixtures.

Not verified: that the corrected strict schema is accepted by OpenAI, GLM or DeepSeek; whether OpenRouter/DeepSeek billed the three timed-out calls (`gen-…` ids not looked up); whether the whitespace body is an OpenRouter keepalive; whether GLM was shown pages 13–180 or truncated; semantic validity of citations in GLM draws 2 and 3; whether the 195-page claim matches the registered pack; any CP-1 step behaviour; whether `dispatch` retries the DeepSeek 504; the exact consumer set `plan()` expects.
