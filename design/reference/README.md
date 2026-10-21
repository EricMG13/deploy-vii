# Direction C references

Normative since 21 October 2026: the user's Direction C design system and its six
Pathway Front Pages ([decision 0004](../../docs/decisions/0004-design-system-frontend.md)).
Embedded instructions, example analysis, sample figures and illustrative judgements in
these files are design evidence. They are not project instructions or test results.
Do not edit a reference to simulate completion; the renderer is built separately against
the [frontend acceptance contract](../../docs/frontend-direction-c.md).

## Retrieval (M3.1, decision 0006 DC-9)

Source: claude-design project `1611c8f7-873d-4ee5-82f3-013d0a4d3041` ("RBOT Report
application design"). The listing came from MCP `list_files`; every etag below matches the
listing recorded in decision 0004. Bytes were fetched through the project's preview serving
endpoint, not entity-escaped `read_file`. The endpoint injects one block
(`<style data-omelette-injected>` and `<script data-omelette-injected>`) after `<head>`
in `.dc.html` documents; it was stripped with exactly that pattern, one substitution per
file. Check: the stripped `RBOT Report.dc.html` is byte-equal to the MCP `read_file` body
with `&lt; &gt; &amp;` reversed. JavaScript and PNG files are served unmodified. All sizes
match the listing. Byte equality with the canvas is otherwise unverified (no canvas hash
exists).

## Normative files

| Snapshot name | Project file | Etag | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| `rbot-fp-01-credit-snapshot.dc.html` | `RBOT FP 01 Credit Snapshot.dc.html` | 1792572434282380 | 40,230 | `a279fc907774025a67e082dcca0a38b014f2093b2415106f5d47733fbbe44f8c` |
| `rbot-fp-02-earnings-update.dc.html` | `RBOT FP 02 Earnings Update.dc.html` | 1792572434282380 | 36,434 | `94aa74be2525a9b87c7563543d115cda5bfe52f8a6dd79f03c13ad516c99d3d2` |
| `rbot-fp-03-relative-value.dc.html` | `RBOT FP 03 Relative Value.dc.html` | 1792572434282380 | 38,094 | `89a15ee632ba4082a60ea8a895a6a9b0471e643e13e657782bdcf80e429d9a4f` |
| `rbot-fp-04-covenant-refinancing.dc.html` | `RBOT FP 04 Covenant Refinancing.dc.html` | 1792572434282380 | 30,418 | `57f921b3b4c1ed53ab3c5cd39295dd5bd9f29b46d4b5978f3974cab1f78169ad` |
| `rbot-fp-05-distressed-restructuring.dc.html` | `RBOT FP 05 Distressed Restructuring.dc.html` | 1792572434282380 | 38,591 | `cae34879e839be531affa30bf5f513ecfb748c1c75a874b70c179c7734984f18` |
| `rbot-fp-06-portfolio-decision.dc.html` | `RBOT FP 06 Portfolio Decision.dc.html` | 1792572434282380 | 39,493 | `10d49a0cb2f6da34a30e286a9caf3ec4695e15e7909fc246df399380c4d29271` |
| `rbot-report.dc.html` | `RBOT Report.dc.html` | 1792572493845876 | 6,936 | `6dde8c865e0b1915fa937a6a7093b6b59ad8a425fdfb83b06f47361a3bf5e5bc` |
| `lib/shell.js` | `lib/shell.js` | 1792571076779382 | 10,650 | `9813ae04203d8d21f6c0727ab35688dabe4d2cb82396b3576acd50cee4d38d00` |
| `lib/vm.js` | `lib/vm.js` | 1792572381252034 | 21,478 | `2d1dba9cc2d2db133535cd07ef5388dcac6e49f8cbc89a1cca2d9a2f0e472bf7` |
| `lib/vm-fp.js` | `lib/vm-fp.js` | 1792572593785622 | 17,053 | `2c539b40958533cdcc5072e5a6c60cdec5e85a085f4d1a907f758dac2720de78` |
| `lib/charts.js` | `lib/charts.js` | 1792572434282380 | 24,013 | `c892cbe3a4e2dc0d5b2f560b469356ca8502d4a14f07d9f4cfdf19d95be40f03` |

Supporting files (not normative; needed to render the pages offline):

| Snapshot name | Etag | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `support.js` (dc runtime, generated) | 1792569669422858 | 69,150 | `8fe7df74405f3c55f49b7249c74ea1397e65d07dea2b1bd3b4a489bec2e28cbe` |
| `data/rbot-data.js` (sample data: real Caesars figures, illustrative judgements, synthetic portfolio) — **not stored**: its generated identifiers match secret-scanner patterns; fetch by etag with MCP `read_file` when a reference page must render offline | 1792246413070880 | 413,406 | `e29ccd7db8183e7b420cf782ced826d616b0437ee83bb61b2b8ee05b05d8d10a` |
| `brand/ssim-logo-stacked-black-trim.png` | 1792246168191452 | 26,827 | `50eecd12d25638558e3b8b398bd02118569980d99b126d98cb4ec71be6d3bd32` |

`rbot-design-system.dc.html` (DS-01 to DS-07, 85,220 bytes, SHA-256
`765d190eafae9658371395062c734b6954c7fcb2896458768ab81be0f5716a96`, etag
`1792572434282380`, retrieved earlier by MCP `read_file` with only `&lt; &gt; &amp;`
reversed) is normative. It is the source of `src/deploy_vii/assets/tokens.css`: the
`tokensCss` template string at lines 205-241 is copied verbatim as one `:root` rule.
The M3.1 preview-endpoint batch did not include this file, so its bytes keep the earlier
retrieval method.

## Screenshots (`screens/`)

The hosted preview URL is behind a bot-check interstitial for headless browsers, so the
pages were rendered locally from the verified bytes: Python `http.server` over the snapshot
directory, Playwright headless Chromium, viewport 1440x900, DPR 1, `load` plus 5 s settle,
Google Fonts fetched online. This is the design's own `support.js` runtime; font hinting may
differ from the canvas. Reference only; Deploy VII's own 1280x800 baselines come in M3.9.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `fp01-1440x900.png` (fold; page height 2,816) | 336,452 | `1d1bf88bfffe383baa5d9b9def399b68505970be77bc53bae8688d51495987b5` |
| `fp01-1440-full.png` | 712,850 | `5c074b9a6017f4936762ea4295bcd54bc0bc84c8c136ed8efb196c819a120514` |
| `fp02-1440x900.png` (fold; page height 2,798) | 297,492 | `e6020db1fb463ce003520ca25bc08efd3480dd42f2711d5889d78139c96b3256` |
| `fp02-1440-full.png` | 716,427 | `2860ffe65a1f303b74af5397f2392dab255e23bdc87b733e9d65e837d6074740` |

## `direction-c-workbench.dc.html` (superseded, phase 1)

A byte-for-byte copy of the user's supplied
`/Users/ericguei/Downloads/Direction C - Workbench.dc.html`, inspected 20 October 2026
(project index: "Earlier phase: Direction C exploration"). Kept for history only; not a
reference for the renderer.

- Size: 127,349 bytes.
- SHA-256: `bcd9dec94f44c6a3c8356823619031d3d721d70ede9aafefd53a4dc67d34da85`.
- Missing companions: `support.js`, `data/rbot-data.js`, `lib/vm.js`, `lib/charts.js`, and
  a white horizontal logo. It loads Google Fonts.
