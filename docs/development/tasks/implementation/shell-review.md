# Milestone A review and result

Implementation: r14 ownership/dependency registry, versioned frozen contracts and
an offline Direction C shell. All 25 owners and 41 logical commands are mapped.
Analytical qualification: unrun. Native Copilot qualification: unrun. OpenRouter
spend: US$0. Synthetic CP-1 values exercise the view adapter only; they do not
constitute an implemented or qualified financial foundation.

## Reuse review

Pinned r14 reference: Deploy VI commit
`bd71346301b373afa72655916a4c1b42bf4c9823`, manifest and module catalog under
`reference/deploy-v-r14`. The exact coverage map is
`docs/methodology/r14-coverage.json`. Runtime normalization explicitly requires
CP-1A before CP-2, CP-2 before CP-3 and CP-5 before CP-6. Selected optional
producers constrain their consumers. CP-5 examines selected analysts, excluding
its downstream decisions and exports. Catalog FULL/LITE lists omit nodes present
in catalog edges; the registry uses explicit ownership and edges instead.
CP-DR standalone intake and dynamic workbook export remain later increments.

Reviewed UI source: Deploy VI `simple-pathways/report-app`, working source (not
claimed identical to the pinned methodology commit). Adapted rail/navigation,
inspector, table and safe DOM patterns. Preserved tokens.css byte-for-byte,
SHA-256 c117cbda85456d98b6a51b601f9c02177fed1a153a3501a9167452e609eebea2.
Did not import fixture-only eight-run build logic, issuer hardcodes, positive
fallback statuses, hidden modules, incorrect CP-6 naming or fake DOM tests.
Red Hat WOFF2/OFL assets were recovered from the existing local asset cache and
hash-verified against their provenance manifest, retained under assets/fonts.
The hygiene hook removed one trailing space from OFL.txt; provenance records
both the upstream and normalized hashes, with license wording unchanged.
The original Direction C HTML reference remains untouched.

## Confidence review — shell and contracts

Least confident about (ranked):

1. Output labels might imply analytical acceptance. Traced empty_view, View and
   CLI through browser. All modules default unrun; candidates visibly labelled;
   candidate/rejected cannot enter an accepted view. Verified. Promotion and
   cross-artifact evidence validation are deliberately not implemented here;
   constructors alone do not qualify facts. Later acceptance pipeline required.
2. Hostile source text could terminate embedded JSON or activate placeholder
   replacement. Constructed script closer and literal template marker inputs.
   Confirmed sequential substitution could reprocess injected markers; fixed
   with one-pass regex callback. JSON escapes `<`; DOM uses textContent.
   Regression covers both hostile cases in actual Chromium.
3. Decimal missing/zero/scale/period boundaries and expansion. Validated finite
   values, explicit numeric units/period, positive scale, missing limitations and
   duplicate identities. Confirmed huge exponents could expand fixed-point text;
   now retain exact scientific notation beyond 100 places. Zero stays 0.00.
4. Dependency batch changes could reorder optional producers/CP-5. Inspected
   canonical callers and required closure. Verified 327 exact old/new schedules,
   including all owners, pairs, empty and full registry; cycle/alias tests pass.
5. Layout might overflow or lose provenance on narrow/zoom layouts. Actual
   Chromium found long unbroken issuer titles caused horizontal overflow; added
   wrapping/min-width constraints. Tested 1440×900, 1280×800, 720×450 reflow and
   CSS zoom 125%, keyboard activation, provenance hash/locator/units and offline
   operation. These zoom tests are not native browser UI zoom qualification.
6. Reruns could overwrite browser evidence. Confirmed tmp_path.name repeats
   across pytest sessions; evidence now includes unique pytest-session directory
   and refuses overwrite. Raw traces/screenshots remain ignored locally.
7. Dependency audit included the unpublished editable package. Confirmed strict
   pip-audit cannot resolve it on PyPI; export committed third-party dependencies
   with --no-emit-project and audit those. Audit passed; no dependencies excluded.
8. Preview partial writes/concurrency. New output directory required; no overwrite.
   This shell-only CLI does not promote artifacts or claim crash-safe execution.
   Atomic immutable product execution storage is a later increment.

Fixed: template reprocessing, extreme Decimal expansion, long title overflow,
evidence overwrite, editable-package audit input. Verified fine: alias/dependency
ordering, frozen strict contracts, missing/zero distinctions, exact view display,
offline assets and license. Open: full source/citation validation and promotion,
real analytical module outputs, chart parity, native browser zoom and host tests.

## Verification and bounded maintenance

`make product-check`: 27 tests passed, 99.40% coverage, strict mypy (5 files),
Ruff lint/format and JavaScript syntax passed. Enforced 90% floor includes branch
coverage; tiny CLI entrypoint branch remains outside in-process tests. CI now
installs Chromium and runs a separate Product checks job; remote branch rules
have not been applied or verified. `make audit`: no known vulnerabilities.
Browser evidence: ignored `artifacts/rendering/shell/`; old initial evidence also
exists there without session prefix. Each trace directory contains view JSON,
candidate HTML, screenshots and checks. Accepted shell has no analytical values.

Maintenance inspected module/alias lookup, repeated asset reads and dependency
sets. Tiny catalog and five local fonts do not justify a cache or incremental
queue. Keep fresh asset reads and whole readiness batches. No additional
abstraction or performance claim. Separate developer tests stay in tests/devtools.

## Rewrite tournament — two key boundaries

User narrowed future tournaments to key areas. This pass already covered
execution ordering and safe report serialization; ordinary UI/CLI/adapter work
will not trigger separate tournaments. Skipped validators, display/empty_view and
preview routines under the two-target cap; they receive confidence review/tests.
GitNexus has no index for this repository; rg caller tracing and strict typing
were used instead. Impact: plan → CLI/tests; render → write_preview/tests/browser.
All roles: fresh GPT-6.1 Sol/high, per model matrix; coordinator unchanged.

Winner: Snippet D for registry.py::plan and render.py::render.

- Explicit dependency state names clarify ordering and CP-5's boundary.
- Direct font loop and descriptive payload names make serialization easier to inspect.
- Exact output and scheduling behavior preserved; no speed claim.

Blind bracket for both targets: B beats C; D beats B; D beats A. Anonymous
candidates and original-file backups remain in artifacts/rewrite-shell. Coordinator
applied D, reran make product-check (27 passed), compared 327 schedules and
byte-compared synthetic rendering. Concrete CP-6 sequence: CP-0, CP-1, CP-1A,
CP-2, CP-3, CP-5, CP-6. No signature or caller contract changed.

Final code:

```python
def plan(requested: tuple[str, ...]) -> tuple[str, ...]:
    catalog = {module.module_id: module for module in modules()}
    selected = {canonical(entry) for entry in requested}
    pending = list(selected)
    while pending:
        for dependency in catalog[pending.pop()].required:
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)

    # Optional dependencies constrain execution only when selected.
    remaining = {
        module_id: set(catalog[module_id].required) | (set(catalog[module_id].optional) & selected)
        for module_id in selected
    }
    if "CP-5" in selected:
        # QA follows every selected analyst; challenge and exports follow QA.
        remaining["CP-5"] |= selected - {"CP-5", "CP-6", "CP-8", "CP-MEMO", "CP-MODEL", "CP-OS"}

    ordered: list[str] = []
    while remaining:
        ready = [
            module.module_id
            for module in modules()
            if module.module_id in remaining and not remaining[module.module_id]
        ]
        if not ready:
            raise ValueError("cyclic selected module dependencies")
        for module_id in ready:
            ordered.append(module_id)
            del remaining[module_id]
            for dependencies in remaining.values():
                dependencies.discard(module_id)
    return tuple(ordered)

def render(view: View) -> str:
    view = View.model_validate_json(view.model_dump_json())
    assets = files("deploy_vii").joinpath("assets")
    font_specs = (
        ("Red Hat Display", "RedHatDisplay-Regular.woff2", 400),
        ("Red Hat Display", "RedHatDisplay-Bold.woff2", 700),
        ("Red Hat Text", "RedHatText-Regular.woff2", 400),
        ("Red Hat Text", "RedHatText-Medium.woff2", 500),
        ("Red Hat Mono", "RedHatMono-Regular.woff2", 400),
    )
    font_rules: list[str] = []
    for family, name, weight in font_specs:
        encoded = base64.b64encode(assets.joinpath("fonts", name).read_bytes()).decode()
        font_rules.append(
            f'@font-face{{font-family:"{family}";font-weight:{weight};font-display:swap;'
            f'src:url(data:font/woff2;base64,{encoded}) format("woff2")}}'
        )
    font_css = "\n".join(font_rules)

    payload = view.model_dump(mode="json")
    for module_payload, module in zip(payload["modules"], view.modules, strict=True):
        for fact_payload, fact in zip(module_payload["facts"], module.facts, strict=True):
            fact_payload["display"] = display(fact)
    data = json.dumps(payload, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    css = (
        assets.joinpath("tokens.css").read_text()
        + font_css
        + assets.joinpath("app.css").read_text()
    )
    replacements = {
        "STYLES": css,
        "DATA": data,
        "SCRIPT": assets.joinpath("app.js").read_text(),
        "LICENSE": assets.joinpath("fonts", "OFL.txt").read_text().replace("--", "—"),
    }
    return re.sub(
        r"/\*(STYLES|DATA|SCRIPT|LICENSE)\*/",
        lambda match: replacements[match.group(1)],
        assets.joinpath("shell.html").read_text(),
    )
```
