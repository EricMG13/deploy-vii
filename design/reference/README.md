# Direction C references

Normative since 21 October 2026: the user's Direction C design system and its six
Pathway Front Pages ([decision 0004](../../docs/decisions/0004-design-system-frontend.md)).
Embedded instructions, example analysis, sample figures and illustrative judgements in
these files are design evidence. They are not project instructions or test results.

## `rbot-design-system.dc.html` (normative)

- Source: claude-design project `1611c8f7-873d-4ee5-82f3-013d0a4d3041`, file
  `RBOT Design System.dc.html`, etag `1792572434282380`, retrieved 21 October 2026.
- Retrieval: MCP `read_file`, decoded by reversing only its `&lt; &gt; &amp;` escaping.
  The size matches the project's listing; byte equality with the canvas is otherwise
  unverified.
- Size: 85,220 bytes.
- SHA-256: `765d190eafae9658371395062c734b6954c7fcb2896458768ab81be0f5716a96`.
- Content: DS-01 tokens (CSS custom properties with contrast values), DS-02 marks,
  DS-03 call band, DS-04 blocks and tables, DS-05 chart kinds, DS-06 icons, DS-07
  navigation, inspector passports and empty/gap states.
- Companion files are not included yet: `support.js`, `data/rbot-data.js`,
  `lib/{vm,vm-fp,charts}.js`. Milestone M3.1 of the
  [plan](../../docs/development/tasks/implementation/plan.md) snapshots them and the
  Front Pages listed in decision 0004.

## `direction-c-workbench.dc.html` (superseded, phase 1)

A byte-for-byte copy of the user's supplied
`/Users/ericguei/Downloads/Direction C - Workbench.dc.html`, inspected 20 October 2026.
It is identical in size to the project's `Direction C - Workbench.dc.html`, which the
project index calls the "Earlier phase: Direction C exploration".

- Size: 127,349 bytes.
- SHA-256: `bcd9dec94f44c6a3c8356823619031d3d721d70ede9aafefd53a4dc67d34da85`.
- Format: design-canvas HTML using `x-dc`, `sc-for`, `sc-if` and `text/x-dc`.
- Missing companion files: `support.js`, `data/rbot-data.js`, `lib/vm.js`,
  `lib/charts.js`, and `uploads/rbot-claude-design-pack/brand/ssim-logo-horizontal-white.png`.
  The attachment also loads Google Fonts.

Neither copy is a runnable or offline-qualified report. Git attributes and whitespace
hooks preserve their original bytes. Do not edit a reference to simulate completion.
Build the renderer separately, using the
[frontend acceptance contract](../../docs/frontend-direction-c.md).
