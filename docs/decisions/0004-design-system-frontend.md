# 0004: Direction C design system as the normative frontend

Date: 21 October 2026. Status: adopted under the user's instruction "Apply your
recommendations and create the new development plan", following the
[adversarial review](../development/reviews/2026-10-21-adversarial-review.md) (C3, F1–F6).
This supersedes the "Frontend" row of [decision 0002](0002-development-environment.md).

## Context

The repository pinned `design/reference/direction-c-workbench.dc.html` (127,349 bytes).
That file is the design project's phase-1 "Direction C exploration". The project's index,
`RBOT Report.dc.html`, describes phase 2 as "tokens and components specified for variable
data, then each Pathway's Front Page composed only from them". The user judged the
current Direction C execution poor and asked for the shell, tokens, layout and rendering
pipeline to follow their design system.

## Decision

1. **Normative sources.** The following files in claude-design project
   `1611c8f7-873d-4ee5-82f3-013d0a4d3041` ("RBOT Report application design") are
   normative, at these versions:

   | File | Etag | Bytes | Local snapshot |
   | --- | --- | --- | --- |
   | `RBOT Design System.dc.html` (DS-01 to DS-07) | 1792572434282380 | 85,220 | `design/reference/rbot-design-system.dc.html` |
   | `RBOT FP 01 Credit Snapshot.dc.html` | 1792572434282380 | 40,230 | M3.1 |
   | `RBOT FP 02 Earnings Update.dc.html` | 1792572434282380 | 36,434 | M3.1 |
   | `RBOT FP 03 Relative Value.dc.html` | 1792572434282380 | 38,094 | M3.1 |
   | `RBOT FP 04 Covenant Refinancing.dc.html` | 1792572434282380 | 30,418 | M3.1 |
   | `RBOT FP 05 Distressed Restructuring.dc.html` | 1792572434282380 | 38,591 | M3.1 |
   | `RBOT FP 06 Portfolio Decision.dc.html` | 1792572434282380 | 39,493 | M3.1 |
   | `RBOT Report.dc.html` (index) | 1792572493845876 | 6,936 | M3.1 |
   | `lib/shell.js`, `lib/vm.js`, `lib/vm-fp.js`, `lib/charts.js` | 1792571076779382, 1792572381252034, 1792572593785622, 1792572434282380 | 10,650; 21,478; 17,053; 24,013 | M3.1 |

   The phase-1 file stays in place as history and is no longer the acceptance target.

2. **Tokens and type.** DS-01's `--rb-*` custom properties replace the Deploy VI
   `tokens.css`. Its type scale, spacing (4/6/8/10/12/18/24), radii (0/2/3/4), motion
   (120/180/260 ms, `cubic-bezier(.2,.7,.2,1)`), 2px `#0017E5` focus ring and 24px
   minimum targets apply. The report embeds the weights the system uses: Display
   600/700, Text 400/500/600 and Mono 500/600.

3. **Information architecture.** The rail has six destinations: Front Page, Analysis,
   Model, Portfolio Fit, Evidence and Limitations. There are six Pathway Front Pages,
   each composed of design-system blocks. Module pages hold "Full analysis" and register
   detail. The call band is sticky and has three states: populated, honest
   no-judgement, and not-in-Pathway or blocked.

4. **Display formatting is Python-owned.** These are proposed defaults; the user may
   override them. Values stay exact; only display rounds, using ROUND_HALF_UP.

   | Unit class | Display | Example |
   | --- | --- | --- |
   | Amount (scale stated once in the block head, e.g. "US$ m") | thousands separators, 0 dp, negatives in parentheses | `11,648`, `(62)` |
   | Multiple | 2 dp with `x` | `3.29x` |
   | Percent | 1 dp with `%` | `30.8%` |
   | Percentage points | 1 dp with `pp` | `(1.4)pp` |
   | Date | `D Mon YYYY` | `2 Oct 2026` |

5. **States and spelling.** These replace the HTML use of `null`. `null` remains only
   in the r14 Markdown transport.

   | State | Display |
   | --- | --- |
   | Gap | `∅ G#`, reason on hover and in the passport |
   | Not meaningful | `∅ G# n.m.` |
   | Blocked critical cell | `—` |
   | Not evaluated | `Not evaluated: …` |
   | Empty table | Block hidden and listed under Limitations |
   | Stale level | Clock glyph plus as-of date |

6. **Status words.** Every status shows an icon and a word, never colour alone.

   | Internal status | Shown as |
   | --- | --- |
   | accepted | Pass |
   | restricted | With limitations |
   | blocked | Blocked |
   | unrun | Not run |
   | `not_in_pathway` (decision 0009) | Not in this Pathway |
   | stale | Stale, rerun required |
   | candidate | Visible only in labelled candidate previews |
   | rejected | Never displayed; the attempt stays in evidence |

7. **Provenance marks.** Every figure carries the cited, calculated or synthetic glyph.
   Model-written prose carries the pen tag. Gaps use `∅` with an ID. Charts have table
   twins, and their marks are focusable.

## Consequences

- Milestone M3 in [plan.md](../development/tasks/implementation/plan.md) re-baselines the
  shell. A module's rendering acceptance now means "its bound Front Page blocks and
  passports populate correctly", not "its registers render".
- `docs/frontend-direction-c.md` and `settings/project.toml` (`[frontend]`) point to the
  new reference.

Not verified:
- byte equality of the local design-system snapshot with the canvas beyond its matching
  size (85,220 bytes). It was decoded from the MCP `read_file` output by reversing only
  the `&lt; &gt; &amp;` escaping; SHA-256
  `765d190eafae9658371395062c734b6954c7fcb2896458768ab81be0f5716a96`;
- the rendered appearance of the FP pages (they were read as source);
- `RBOT FP 01` and `03`–`06` and `lib/vm.js` were not read in full;
- the display precision in item 4 is inferred from the design's examples, not stated
  in the design system as a rule.
