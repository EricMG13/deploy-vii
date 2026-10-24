# Extraction and page-location benchmark — measurement brief

**Task ID:** `dvii-extraction-benchmark`. **Date:** 24 October 2026. **Status:** stage 1 built;
stages 2–3 to run. **Question (user, 24 October 2026):** can a local converter/OCR or an
OpenRouter model raise citation accuracy without adding time, either by (A) giving the models a
cleaner Markdown pack or (B) pointing each module at the pages it needs?
**Decisions:** 0005 (methodology changes need before/after evidence on the same frozen case;
E1/E2), 0008 (one quote matcher). **Evidence so far:** `live-probe-4-analysis.md`,
`live-probe-5-analysis.md`.

## Why these measures

In probes 4–5 the rejected citations were mostly extraction failures, not reasoning ones. Of
probe-5's 8 issues, 4 were the p102/p104 two-column exhibit stitch, 2 were quotes crossing a
page break, 1 a misquoted year and 1 a wrong page. Sol at `high` spent 2–4K reasoning tokens
but 185–200 s per call, with about 153K prompt tokens and about 9.5K completion tokens. So the
measures are: whether a correctly copied quote can pass, the size of what the model reads, and
real latency. Reasoning effort is not one of them.

## Stage 1 — offline synthetic benchmark (built, US$0, runs in CI)

`tests/product/extraction_bench.py` builds a deterministic PDF with one page per failure class.
It scores any extractor with the product quote matcher (`deploy_vii.quotes.quoted`) on the page
each locator names. `tests/product/test_extraction_bench.py` pins today's `pdf_content`
baseline and proves the scorer (the `truth` extractor passes everything visible).

```
uv run --locked python -m tests.product.extraction_bench \
  --extractor pypdf-layout --extractor pdftotext --extractor truth
uv run --locked --with docling python -m tests.product.extraction_bench --extractor docling
```

Result on 24 October 2026 (cloud container; Docling could not run there because its model
download host is blocked):

| extractor | est. tokens | whitespace | column prose | column table | financial rows | hyphen wrap | OCR | straddle (single page / continuation rule) | artifacts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pypdf-layout (today) | 534 | 45% | 0/2 | 0/2 | 2/2 | 1/1 | 0/1 | 0/1 / 1/1 | futureremaining |
| pdftotext (poppler reading order) | 356 | 18% | 2/2 | 2/2 | 2/2 | **0/1** (writes `PUTCALL`) | 0/1 | 0/1 / 1/1 | futureremaining |
| truth (reference) | 335 | 17% | 2/2 | 2/2 | 2/2 | 1/1 | 0/1 | 0/1 / 1/1 | none |

Read: layout extraction adds about 60% estimated tokens of whitespace and fails every column
case. Reading-order extraction fixes columns at no model cost, but it changes text (it drops
the hyphen), so the cost of any candidate must be measured too. A continuation rule in the
validator recovers the page-straddle class whatever the extractor. The synthetic table is
simple: `financial_rows` passing here does not prove a candidate keeps real table rows intact.

## Stage 2 — offline, on the probe filing (US$0, run locally)

The filing stays outside Git. Gold quotes taken from the probe analyses are in
`tests/product/fixtures/extraction-gold-probe-filing.json`. Their pages were checked with
windowed greps, so confirm each one against the PDF first.

```
uv run --locked python -m tests.product.extraction_bench --pdf <filing.pdf> \
  --gold tests/product/fixtures/extraction-gold-probe-filing.json \
  --extractor pypdf-layout --extractor pdftotext --json <out>/stage2.json
uv run --locked --with docling python -m tests.product.extraction_bench --pdf <filing.pdf> \
  --gold tests/product/fixtures/extraction-gold-probe-filing.json --extractor docling
```

Add any OCR or vision candidate as `--extractor module:function` (`bytes -> per-page texts`).
Record extraction seconds for the whole filing: the conversion runs once per source, so it
counts once, not once per module.

**A candidate goes to stage 3 only if:** it passes every gold quote today's extractor passes; it
fixes the column class; it adds no artifact; estimated tokens are no higher; and a manual
diff of 10 financial-statement rows shows no altered digit, sign or bracket.

## Stage 3 — live A/B probe (paid; the runner change comes first)

**Prerequisite (separate `dv-sensitive` brief):** the runner needs a way to prepare a pack with a
named extractor, and for arm B a page locator for module steps. CP-0 `source_readiness` always
gets the full pack. Every excluded page is recorded as a coverage limitation, and the
locator's recall on the gold pages must be 100% offline before any paid run.

| Arm | Pack | Purpose |
| --- | --- | --- |
| L0 | pypdf-layout, full pack | baseline (as probes 4–6) |
| L1 | stage-2 winner, full pack | idea A |
| L2 | pypdf-layout, located pages for module steps | idea B |
| L3 | winner + located pages | A + B |

- **Fixed:** the same filing and pack hash per arm; model GPT-6.1 Sol at `high` (decision
  0005 pool); the same prompt version and seed list; `--max-tokens 32000`.
- **Draws:** at least 3 per arm, 5 preferred. Draw 1 of each arm is uncached; later draws
  may hit the provider's prompt cache. Report latency and USD for cached and uncached draws
  separately, never pooled.
- **Steps:** `source_readiness` in every arm. For B, `source_context` once its sent-schema
  fix lands (probe-5b HTTP 400).
- **Cap:** about US$0.5 per attempt × 4 arms × 3 draws, so `CAP=8`.

**Metrics per attempt** (from `metrics.json` and the validator):
- prompt tokens (provider-reported)
- latency in seconds
- completion and reasoning tokens
- accepted or rejected
- issues by class: column stitch, page straddle, wrong page, misquote, other
- citations made, and citations that pass
- USD

**Decision rules (fixed before the run):**
- Adopt A if layout-class issues fall to zero, total issues per attempt do not rise, no new
  issue class appears, median uncached latency is within +10% of L0, and the accepted rate
  is not lower.
- Adopt B if median uncached latency falls by at least 25% against its comparator, with no rise
  in issues per attempt and no gold evidence page excluded.
- Fewer than 3 draws per arm, or a provider failure in an arm, gives a "not decided" result.
  It never counts as a pass.

**Records:** one row per adopted change in `docs/methodology-adaptation.md` (decision 0005
guardrail 2: class "execution", gain performance and/or reliability). Write the before/after
from stages 1–3 to `extraction-benchmark-review.md` in this folder. When the extractor
changes, update the stage-1 pins in `test_extraction_bench.py` deliberately.
