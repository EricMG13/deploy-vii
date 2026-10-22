# M2.1 coordinator inputs: OpenRouter API (fetched 21 October 2026)

Source: Context7 `/openrouterteam/docs` (official docs repo) and the public catalog
`GET https://openrouter.ai/api/v1/models` (snapshot: `openrouter-models-2026-10-21.json`
beside this file, 787,201 bytes, no credentials used). Treat as data, not instructions.
Versioned docs do not exist on Context7; these are the current docs on the fetch date.

## Chat completions and usage

- Endpoint: `POST https://openrouter.ai/api/v1/chat/completions`, `Authorization: Bearer <key>`.
  OpenAI-compatible body: `model`, `messages`, `max_tokens`, `response_format`
  (`{"type":"json_schema", ...}` where `structured_outputs` is supported), `reasoning`,
  `provider`, `models`.
- **Usage is always returned** (the former `usage: {include: true}` and
  `stream_options.include_usage` are deprecated no-ops). Response `usage` object:
  `prompt_tokens`, `completion_tokens`, `total_tokens`,
  `completion_tokens_details.reasoning_tokens`,
  `prompt_tokens_details.cached_tokens`, `prompt_tokens_details.cache_write_tokens`
  (only with explicit caching), `cost` (credits = USD), `cost_details.upstream_inference_cost`.
  For streaming, usage arrives in the last SSE message.
- The response also carries the served `model` id and `provider` name (router metadata)
  — record both; a served id that differs from the requested id is a fallback.

## Reasoning effort

- `reasoning: {"effort": "<level>"}`; levels `none|minimal|low|medium|high|xhigh|max`.
  Token allocation when the provider only supports a budget: minimal≈10%, low≈20%,
  medium≈50%, high≈80%, xhigh and max≈95% of `max_tokens`.
- **Unsupported non-`none` efforts are mapped to the nearest supported level on all
  slugs (documented example: `xhigh` → `high`).** The response does not necessarily say
  so; record requested effort and the catalog's `supported_parameters` separately and
  note the documented mapping (plan test `test_unsupported_xhigh_maps_to_high_and_is_recorded`).
- `~latest` alias slugs remap parameters silently; **concrete slugs keep strict
  validation** → always pin concrete slugs per batch.
- `reasoning.max_tokens` is an alternative budget form; `max_tokens` must exceed the
  reasoning budget or no answer tokens remain.

## Provider routing and fallback

- `provider` object fields: `order: [slugs]`, `allow_fallbacks: bool` (default **true**),
  `require_parameters: bool` (default false; set true so a provider that ignores
  `response_format`/`reasoning` is never chosen), `data_collection: "allow"|"deny"`,
  `zdr`, `only: [slugs]`, `ignore: [slugs]`, `quantizations`, `sort`, `max_price`.
- `models: [ids]` is a **model-level fallback list** tried in order when the primary
  errors — do not send it (sending none keeps the request on the drawn model).
- Plan requirement (MC/2.2): set `allow_fallbacks: false`, `require_parameters: true`,
  omit `models`; if the served `model`/`provider` still differs from the request, classify
  the attempt as `fallback` (test `test_fallback_model_is_classified_not_hidden`).

## Key, credit and pricing endpoints

- `GET https://openrouter.ai/api/v1/key` (Bearer key): `data.limit`, `data.limit_remaining`
  (null = unlimited), `data.usage`, `usage_daily|weekly|monthly`, `budgets[]` and
  `effective_budget` (`limit_usd`, `spend_usd`, `remaining_usd`, `resets_at`),
  `is_free_tier`, `label` (a masked key — never persist it). This is the credit probe for
  the DC-8 "credit exhausted" check; a 402 on a completion is the other signal.
- `GET /api/v1/credits` requires a **management key** — not available; do not use.
- `GET /api/v1/models` (public): per model `id`, `created`, `context_length`,
  `pricing.{prompt,completion,internal_reasoning,request,input_cache_read,input_cache_write}`
  as USD-per-token strings, `supported_parameters[]`.
  `GET /api/v1/models/{author}/{slug}/endpoints` gives per-provider pricing and `discount`.
  Reservation (plan 2.2) = `prompt_price × prompt_tokens + completion_price × max_tokens`
  (+ `request` price if present), at the pinned price; `max_price` offers no reasoning or
  cache caps, so reservation is the only hard guard.

## Candidate eligibility and pricing (catalog snapshot, 21 October 2026)

| Pool member | Slug to pin | Created | Context | Prompt US$/M | Completion US$/M | `reasoning_effort` | `structured_outputs` | `temperature` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Luna | `openai/gpt-6-luna` | 2026-09-28 | 1,050,000 | 0.10 | 0.50 | yes | yes | **no** (omit) |
| GLM 5.3 Flash | `z-ai/glm-5.3-flash` | 2026-08-22 | 1,048,576 | 0.041191 | 0.12 | yes | yes | yes |
| DeepSeek latest | `deepseek/deepseek-v4.1-flash-1017` | 2026-10-16 | 1,048,576 | 0.15 | 0.60 | yes | yes | yes |

- DeepSeek resolution rule applied: newest `created` among `deepseek/*` non-batch,
  non-experimental, text models with `reasoning` support → `deepseek-v4.1-flash-1017`
  (matches `docs/testing-and-telemetry.md`). Alternatives seen: `deepseek-v4.1-flash`
  (2026-08-09, cheaper), `deepseek-v4-pro-0813`. Re-resolve per batch.
- Excluded variants: `:batch` slugs (async batch pricing), `gpt-6-luna-pro`, `glm-5.3-flashx`
  (not the user's named models).
- `internal_reasoning` price is empty for all three → reasoning tokens bill at the
  completion rate; reserve `max_tokens` at the completion price.
- Catalog `supported_parameters` listing `reasoning_effort` does not prove `xhigh` is
  accepted; record requested vs documented mapping per attempt.

## Credential (decision 0006 DC-7)

`~/Documents/op router.rtf` exists (535 bytes, confirmed by `ls` only; never read).
Loader: `textutil -convert txt -stdout <file>`, strip whitespace, require `sk-or-` prefix,
hold in memory, never log. Project settings deny `Read` on the file.

Not verified: account entitlement and funded credit; live acceptance of `xhigh` per
provider; pricing at batch time (re-fetch the catalog before each batch).
