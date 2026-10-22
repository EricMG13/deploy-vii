# Probe-5 and probe-5b analysis (M2, dv-research, read-only, 22 October 2026)

Roots. ART5 = `/Users/ericguei/Documents/DEPLOY VII/artifacts/model-tests/probe-5/probe/google__gemini-4-argon/`, ART5b = `.../probe-5b/probe/`. Attempts by 8-character prefix. SRC = `src/deploy_vii/` at `claude/m2-lane` a6678e7. Page checks were grep windows over each `request.json`; only the `response_format` schema was read from `request.json`; no message body copied; no key-prefixed string read; nothing executed. Batch reports: `live-probe-5.md`, `live-probe-5b.md` (+ `-reconciled.md`: no holds).

Pool (user instruction relayed 22 Oct 2026, "progress with gronk, sol and gemini 4"; ledger ruling under decision 0005): Grok 4.7 @xhigh, GPT-6.1 Sol @high, Gemini 4 Argon (`google/gemini-4-argon`; `xhigh` requested, `high` sent — the catalog lists low/medium/high only). Runner a6678e7 (task 2.10: consumer purposes in the CP-0 CONTEXT, rule h, `--max-tokens 32000`, hyphen-wrap, not-authorized outcome, deadline).

## 1. Attempts

| Attempt | Model | Effort req/sent | Status / class | Issues | USD | Prompt / completion / reasoning | Latency s | finish_reason |
|---|---|---|---|---|---|---|---|---|
| a3392cdd | Gemini 4 Argon | xhigh / high (mapped) | rejected / ok | 4 | 0.526488 | 164,229 / 19,803 / 9,226 (cached 0) | 240.5 | stop |
| 50115c10 | Gemini 4 Argon | xhigh / high | rejected / ok | 3 | 0.2775055 | 164,229 / 25,718 / 15,847 (cached 162,175) | 307.0 | stop |
| cf6bf65b | GPT-6.1 Sol | high / high | **accepted** / ok | 0 | 0.4822035 | 153,514 / 9,842 / 1,990 (cached 0) | 184.6 | stop |
| 5ae16ef9 | GPT-6.1 Sol (`source_context`) | high / high | no-response / http_error | 0 | 0 | none | 0.67 | null (HTTP 400) |
| 8c68df3d | Grok 4.7 | xhigh / xhigh | rejected / ok | 1 | 0.456882 | 154,683 / 24,874 / 18,653 (cached 1,152) | 283.9 | stop |

Spend: probe-5 US$0.8039935, probe-5b US$0.9390855 (row sums; no holds). Gemini routed to Google; Sol to OpenAI.

## 2. Rejected issues and root cause

**Gemini a3392cdd (4).** p84 "During the year ended December 31, 2025, the Company reached the limit of authorized repurchases…" — source says **2024** (the 2018 plan's exhaustion, a 2024 event) cited as 2025 evidence for CP-6: model misquote with a factual error (the "hyphen-wrap" in the issue text is only the normalisation list; no wrap involved). p102 Indenture 4.2 and p104 Credit Agreement 10.30: the known two-column exhibit-table interleave (page right, text stitched). p76 "On July 8, 2025, the Company fully redeemed … WSOP trademark sale.": the quote crosses the p76/p77 page break (page right, quote too long for the cited page).

**Gemini 50115c10 (3).** p44 "Uses of cash flows that are not reflected in Adjusted EBITDA include…": the sentence starts at the foot of p43 (page-break straddle; model with layout). p102, p104: the same interleave.

**Grok 8c68df3d (1).** p74 "The fair value of debt has been calculated primarily based on the borrowing rates…": on p75 (Gemini and Sol cite p75 and pass); model wrong page, off by one.

Pattern: of 8 issues, 4 are the p102/p104 stitch, 2 page-boundary straddles, 1 model misquote (year), 1 model wrong page. No runner defect except that the validator cannot express "the quote continues on the next page".

## 3. Sol cf6bf65b (accepted CP-0)

Consumer statuses: CP-1, CP-1A, CP-2, CP-5 READY_WITH_LIMITATIONS; CP-4, CP-3, CP-6 CONDITIONAL. CP-1 READY_WITH_LIMITATIONS, so the chain continued to `source_context` (no `not-authorized` record). **The all-CONDITIONAL pattern of probe-4 (944e569a: 7 of 7) changed**; prompt grew ≈305 tokens (153,209 → 153,514), consistent with the added titles and purposes; Grok 8c68df3d shows the same split; Gemini a3392cdd/50115c10 have CP-4/CP-3 CONDITIONAL and CP-6 READY_WITH_LIMITATIONS. `missing_source` values are specific (operative debt and lease documents, market pricing). Fix 7 plausibly caused the change; one prompt version per probe, so causation is not proven.

Spot checks: CP-5 p44 "Such figures are based on unaudited internal financial statements…" real, supports the limitation; A-5 p76 "$1.9 billion of available borrowing capacity…" verbatim, sound; CP-3 p193 "Because of regulatory restrictions, our ability to grant a security interest…" verbatim, sound. Weak: CP-1 cites a KPI definition (p37) that does not evidence the statements; G-1 cites the merged-heading artifact "available for futureremaining" (p99); p48 redemption quote duplicates p45. Acceptance = structure and quotes pass; readiness verdicts not thereby validated.

## 4. The `source_context` HTTP 400 (5ae16ef9)

Error (OpenAI raw, in `response.json` `body_text`): "Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema.", `param` `text.format.schema`, `code` `invalid_json_schema`; no keyword named; `allow_fallbacks` false, `require_parameters` true.

Diff against the readiness schema (cf6bf65b, accepted by OpenAI minutes earlier): readiness has `$defs`, `$ref`, `anyOf` with null, string enums, `additionalProperties:false`, all properties required, one `minItems` (`analysis`; manifest `schema_keywords_unverified: ["minItems"]`). The source_context schema adds: `minLength`/`maxLength` (Citation fields, `Identifier`, `Text`); `pattern` (`^[A-Za-z0-9][A-Za-z0-9_.:-]*$`, `^[0-9a-f]{64}$`, `^[A-Z]{3}$`); `format: "date"`; `const` inside `anyOf` (`schema_version`, `historical_treatment`); `maxItems` (2000, 20000); `type: ["array","null"]`/`["string","null"]` unions; an `enum` containing `null` with a type union (`event_scan`); an `anyOf` branch holding an `enum`; nested `minItems`. Manifest `schema_keywords_unverified: ["const","format","maxItems","maxLength","minItems","minLength","pattern"]`. Limits not approached (≈7 levels of 10). `minItems` is not the cause (accepted in cf6bf65b).

OpenAI structured-outputs rules (https://developers.openai.com/api/docs/guides/structured-outputs, fetched 22 Oct 2026 through a summarising fetch; paraphrase, page date not visible): supported string keywords `pattern`, `format` (date, date-time, time, duration, email, hostname, ipv4, ipv6, uuid); array `minItems`, `maxItems`; enum and `anyOf`; null via type arrays; limits 5,000 properties, 10 levels, 120,000 name+enum chars, 1,000 enum values. `minLength`/`maxLength` not listed as supported (listed as unsupported only for fine-tuned models); `const` neither listed. **Candidates: `minLength`/`maxLength`, `const`, nullable `enum` with `null`; none proven** (a US$0 bisect is possible: 400s cost nothing).

Transform: `strict_schema` (`SRC/live/schema.py:135-148`) copies the Pydantic schema; `_nullable` (`:94-108`) produces the type unions, `enum`+null and `anyOf`-wrapped `const`; unverified keywords are only named (`UNVERIFIED` `:30`, `unverified_keywords` `:151`), never removed. The constructs come from the stored contract (`STEPS["source_context"] = StepDef("CP-1", SourceContextReview)`, `SRC/live/submission.py:135`; class in `SRC/source_context.py` using `Identifier`, `Hash`, `Text`, `date`, `Literal`, `Field(max_length=…)`). Fix point: a provider-aware sent-schema step in `schema.py` that strips or relaxes unverified keywords on the way out while the trusted Pydantic validator keeps enforcing them.

Regression? **Pre-existing, not a 2.10 regression**: `schema_sha256` c1f3dc7f0ad3950c5d8f20a3d5c2d911df9725cace3d821b37f4e1fae84f07cd is byte-identical in probe-3 GLM f0391c45 (accepted by OpenInference) and probe-5b 5ae16ef9; same keyword list in probe-3's manifest; fix 5 touched the readiness schema only. First time OpenAI saw this schema (probe-4 Sol's `source_context` never ran because of the CP-0 abort). GLM leniency likely, not proven.

## 5. Ranking (accepted results and failure classes, not reasoning tokens)

Draw counts differ (Sol 1, Gemini 2, Grok 1 on the 2.10 prompt; probe-4 draws used the pre-2.10 prompt).

1. **GPT-6.1 Sol @high** — accepted 2 of 3 `source_readiness` attempts (944e569a pre-2.10; cf6bf65b 1 of 1 on 2.10), the only accepted attempts anywhere; rejected 9594d016: case change, hyphen rejoin, column stitch. Cost US$0.478 / 0.107 (cached) / 0.482; latency 185–201 s, fastest. Needs the `source_context` sent-schema fix; until then Sol cannot run any step after CP-0 on OpenAI.
2. **Gemini 4 Argon @high** — 0 of 2; issues 4 and 3; 4 of 7 the p102/p104 stitch, 2 page-break straddles, 1 misquote (year); no wrong page. Cost US$0.526 (uncached) / 0.278 (cached); latency 240–307 s. Without the layout/page-break class, 50115c10 would have no model-attributable issue and a3392cdd one (the year). Free-text `period` fields carry stray/garbled text (unchecked by the validator). `high` ceiling; `xhigh` mapped down.
3. **Grok 4.7 @xhigh** — 0 of 3 (4, 2, 1 issues); recurring class: model wrong page (p37, p47, p72×2, p74) plus one stitch. Cost US$0.432 / 0.273 / 0.457; latency 220–341 s. Needs page-assignment precision; issue trend 4→2→1.

Ranks 2 and 3 are close and low confidence (≤ 3 draws per model).

## 6. Runner defects beyond §4

`schema_keywords_unverified` recorded but not acted on (a rejecting provider is found only by a live 400, US$0 but ends the cell). Quotes crossing a page boundary are rejected with no hint; mismatch strings truncated at 60 chars. The mismatch text prints "hyphen-wrap" whenever the span contains a wrap, even when irrelevant (p84). Free-text identity fields (`period`) unchecked. Cohort tables have no column for no-response outcomes.

Not verified: which keyword OpenAI rejected; exact OpenAI doc wording (summarised fetch, undated); head of p77 and the p48 page; the full quote sets beyond the checks above; whether fix 7 caused the READY_WITH_LIMITATIONS split; whether Gemini or Grok `source_context` would pass; Gemini's reasoning behaviour at `xhigh`; runtime behaviour inferred from source and artifacts.
