# Model interface: confidence review and scoped parser tournament

Task `dvii-implementation-001`, milestone C increment. Base `0429e81`, branch
`codex/development-environment`, owner session
`01a15bb5-b5bc-7151-94b3-4edbae9d7815`. Scope: new source interface and combined
candidate writer, canonical table codec, CLI integration, coupon metadata and
readability of wide tables. No dependency or provider route changes.

## Confidence review — interface projection and transport

Least confident about (ranked):

1. **Coupon units and source currencies.** Traced facility input contracts,
   source audit and kernel conventions against pinned r14 Model interface
   lines 484–522 in `artifacts/cp1-steps-reference.md`. **Confirmed bug:** audit
   labelled 6.500 fixed coupons decimal fractions, although the method requires
   decimal percentages. Reproduction: `artifacts/model-interface-coupon-repro.log`.
   Corrected the metadata, leaving actual amounts unchanged; advanced audit to
   `/4`, with explicit old-schema rejection. Tax rates remain fractions and
   spreads/floors remain basis points. EUR facility source amounts remain EUR;
   kernel normalization does not overwrite originals. Regression tests inspect
   units, currencies, zero amortisation and raw coupon precision. Review also
   found that the new projection discarded units when a value was null; it now
   preserves cell units independently of amount availability, asserted on a
   conflicting revenue observation.
2. **Silent Markdown changes to source text or null semantics.** Traced writer,
   one-pass reader and trusted-module parity validator. **Confirmed bug:** the
   old writer's broad null-marker guard also rejected the legitimate controlled
   `reference_rate=NONE`. Narrowly exempted only that exact field/value/interface.
   All other known null markers remain rejected. Adversarial cases cover literal
   entities, generated line breaks, markup, pipes, whitespace, Unicode U+2028,
   malformed tags/separators, duplicate headings and trailing prose. Precision
   changes and interface substitution fail parity. The reader returns strings;
   it neither validates finances nor authenticates an arbitrary input Module.
3. **Register identity, scope and source substitution.** Read the full new
   adapter and compared schemas with the pinned reference. Exact field sets,
   duplicate identities and rectangular layouts are validated. Tests cover
   sign-normalized source accounts, conflicting alternatives, dynamic schedules,
   missing periods, source definitions, separate pro-forma events, and explicit
   historical readiness. All field citations survive; primary row locators are
   not represented as complete field evidence. **Verified fine within this
   candidate's scope.** Facilities contain actual supplied rows; absent periods
   remain readiness findings. T4.19 projects source reconciliation; constructed
   checks remain in the companion readiness artifact pending full canonical
   projection. No claim that all CP-1 registers are implemented.
4. **Copied input objects bypassing nested typing.** JSON revalidation inside
   child functions did not replace the original pack object used later by the
   new preview. **Confirmed bug:** a `model_copy` containing a dictionary-valued
   run caused View validation errors. Reproduction retained in
   `artifacts/model-interface-pack-repro.log`. Revalidate the pack at the preview
   entry point; the regression exercises the real writer and passes. Financial
   review is independently validated against that pack and recomputed interface
   content hashes detect altered or stale outputs.
5. **Rendered parity hiding unusable layout.** Exact DOM field parity passed,
   but visual inspection showed the 22-column debt register wrapping 6.500 into
   five lines. **Confirmed issue**, reproduced by text-range line count in
   `artifacts/model-interface-layout-repro.log`. Added minimum table cell widths
   while retaining keyboard-accessible local horizontal scrolling. Moved scope
   notes outside the scrolling region so focus scrolling cannot hide them.
   Browser regressions verify one-line coupon text, all field IDs/strings,
   keyboard inspection, original locator, unit, offline behavior and no page-wide
   overflow at 1440×900/1280×800 and 125% zoom. Retained viewport screenshots were
   visually inspected; this is candidate rendering evidence, not analytical
   qualification. No chart is introduced for these source registers.
6. **Journal ordering and partial output.** Traced CLI through the existing
   source/financial stage gate, trusted recomputation and current-input binding.
   Test confirms unchanged journal hash, all receipt file hashes, ticket/snapshot
   binding, early-stage refusal and existing-output refusal. **Verified fine.**
   No new stage transition, acceptance or repair allowance. By design files are
   written into a fresh directory and the receipt is last; a failed write can
   leave an incomplete directory. No power-loss or atomic publication guarantee.
7. **Resource limits and completion claims.** Parser bounds are explicit and
   tested in the tournament differential corpus. The returned result is linear
   in table size. Dynamic schedule expansion and duplicate-row scans are not a
   benchmarked large-pack performance claim. **Open for full delivery:** reconcile
   transport limits with maximum accepted source schedules and implement the
   full typed canonical-envelope consumer. Keep candidate labels, gaps and
   readiness scope; partial source extraction never becomes full acceptance.

Fixed: coupon-unit metadata, controlled NONE handling, copied-pack validation,
null-cell units, narrow table columns and horizontally hidden scope notes.
Verified fine: table identity/precision/citations, original source currencies,
pro-forma separation, explicit gaps, readiness scope, journal and file bindings.
By design: string-only table reader, candidate status, last-written receipt,
transport bounds and separate source/constructed reconciliation artifacts.
Still open: full canonical envelope/QA and typed reader, remaining CP-1 registers,
complete Model presentation, CP-1A, all subsequent modules and live/native
qualification. No unresolved confirmed bug in this increment is being waived.

## Post-edit tournament — one key area

Only `table_markdown.read_table_markdown` was selected: this is the provenance
transport seam. Routine adapters, CLI, UI and metadata edits received focused
checks and the confidence review above. Fresh isolated review roles used the
requested model matrix: GPT-6.1 Sol, high effort. The coordinator route was not
changed. GitNexus could not find the project; the fallback `rg` caller inventory
is retained in `artifacts/interface-parser-tournament/impact.txt`. No other
project index was used.

The anonymous bracket was A (speed), B (memory), C (readability), D (incumbent).
A defeated B, C defeated A, C defeated D. Full match reasons are retained in
`scratcharbiter.md`. Winner: **Snippet C**, replacing
`src/deploy_vii/table_markdown.py:69` through the end of `read_table_markdown`.

- One decode-and-round-trip path remains easy to audit; no literal-key bypass.
- Runtime and retained-result space remain linear without iterator bookkeeping.
- Explicit encoded/decoded names and the malformed-row precedence comment clarify
  the contract without changing behavior.

Final code:

```python
def read_table_markdown(text: str) -> MarkdownTable:
    """Read one canonical table, decoding source text once; reject ambiguous syntax.

    This is a transport reader, not financial validation or artifact authentication.
    The literal null token remains text until a typed consumer interprets its field.
    """
    if len(text) > 4_000_000 or "\r" in text:
        raise ValueError("Noncanonical or oversized table")
    lines = text.split("\n")
    interface = None
    if lines[0].startswith("<!--"):
        match = re.fullmatch(r"<!-- table-id: ([A-Za-z0-9][A-Za-z0-9_.:-]{0,159}) -->", lines[0])
        if match is None or len(lines) < 4 or lines[1] != "":
            raise ValueError("Invalid table interface comment")
        interface = match[1]
        lines = lines[2:]
    if not 2 <= len(lines) <= 20_002:
        raise ValueError("Invalid table row count")

    def decode_row(line: str) -> tuple[str, ...]:
        if not line.startswith("| ") or not line.endswith(" |"):
            raise ValueError("Noncanonical table row")
        encoded_cells = line[2:-2].split(" | ")
        if not 1 <= len(encoded_cells) <= 1024:
            raise ValueError("Invalid table column count")
        decoded_cells = tuple(unescape(cell.replace("<br>", "\n")) for cell in encoded_cells)
        if any(
            markdown_cell(decoded) != encoded
            for decoded, encoded in zip(decoded_cells, encoded_cells, strict=True)
        ):
            raise ValueError("Noncanonical cell encoding")
        return decoded_cells

    headings = decode_row(lines[0])
    if any(not heading for heading in headings) or len(set(headings)) != len(headings):
        raise ValueError("Empty or duplicate table heading")
    separator = "|" + "|".join("---" for _ in headings) + "|"
    if lines[1] != separator:
        raise ValueError("Table separator differs from its headings")
    # Decode every row before checking shape, preserving malformed-row precedence.
    rows = tuple(decode_row(line) for line in lines[2:])
    if any(len(row) != len(headings) for row in rows):
        raise ValueError("Nonrectangular table")
    if interface and any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", heading) for heading in headings
    ):
        raise ValueError("Interface headings must be literal field keys")
    return MarkdownTable(interface, headings, rows)
```

Verification:

- `uv run --locked python artifacts/interface-parser-tournament/readability_check.py`
  — 30,037 exact output/error differential cases passed before applying the winner.
  The coordinator read and ran the harness against the original implementation.
- Backed up the full production file to `before-winner.py`, then applied C.
- `uv run --locked pytest tests/product/test_model_interface.py tests/product/test_report_tables.py -q`
  — 52 passed at winner application; later added cases are covered below.
- Concrete invariant: literal source `&amp;` and `<br>` remain literal text after
  one decode; generated newlines return LF. Noncanonical encodings fail closed.
- Impact-set checks: writer validator, interface preview and tests; all compile
  and type-check. Actual candidate diff reviewed by the coordinator.
- `make product-check` — 871 passed, 97.44% branch-inclusive coverage, strict
  typing, lint/format and JavaScript syntax passed. Retained log:
  `artifacts/model-interface-product-check.log`.
- After the final layout correction:
  `uv run --locked pytest tests/product/test_interface_view.py tests/product/test_report_tables.py tests/product/test_statement_history.py tests/product/test_browser.py -q`
  — 48 passed. The earlier command naming nonexistent `test_statement_view.py`
  collected no tests; the corrected command above is the evidence.
- After preserving null units:
  `uv run --locked pytest tests/product/test_model_interface.py -q` — 24 passed.
- Final `ruff check`, `ruff format --check`, `mypy src` (49 files) and
  `node --check src/deploy_vii/assets/app.js` passed.
- Final zoom-evidence refresh: `uv run --locked pytest tests/product/test_interface_view.py -q`
  — 4 passed; coupon remains in view at 125% and screenshots were inspected.
- `make check` passed. `make secrets` passed directory, staged-diff and complete
  reachable-history scans with no findings. Dependencies are unchanged.

Browser evidence lives under `artifacts/rendering/model-interface/`; raw fixtures
and screenshots are ignored. Full suite ran before the final small layout/unit
corrections; affected tests and final static checks cover those corrections.

## Design hook triage and remaining work

The side-tab finding is the active-page navigation indicator, retained in the
required Direction C reference. The existing file/value-scoped exception in
`.impeccable/config.json` is sufficient; no new suppression was added. No card
accent was introduced. The separate table-width problem was fixed, not suppressed.
The intentional navigation indicator remains standing; no unresolved design
finding in the current increment.

OpenRouter spend remains US$0 of the US$50 total cap. No provider call, native
qualification, push, PR or publication. Canonical envelope/QA, remaining registers,
complete Model output and final promotion are next; the full A–H goal stays active.
