# deploy-vii command surface

Entry point `deploy-vii = deploy_vii.__main__:main`. Global `--out DIR` (before the command) or
`DEPLOY_VII_OUT` selects the delivery root; default is `./deploy-vii-out`.

## Top level

| Command | Flags | Writes |
| --- | --- | --- |
| `plan MODULE...` | none | prints the dependency order; nothing is written |
| `doctor` | `[--request FILE] [--inputs FILE...] [--json]` | network-free installation and optional input checks |
| `prepare` | `--request FILE --root DIR [--output DIR \| --run ID]` | new pack directory (`pack.json`, `originals/`, `complete.json`); refuses an existing output |
| `run` | `--request FILE --root DIR --run ID [--modules MODULE...] [--reviews DIR]` | prepare, retain journal and stop for each host review in plan order; no model dispatch |
| `cp0` | `--pack DIR --review FILE --output DIR` | stateless CP-0 delivery without a journal; not used by this skill's flow |
| `preview` | `--run FILE --output DIR` | an unrun report shell from a Run JSON |
| `execution` | `--directory DIR` or `--run ID`, then an action | the journal at DIR or derived run path |
| `live` | see below | development test runner |

## `execution (--directory DIR | --run ID) <action>`

| Action | Flags | Effect |
| --- | --- | --- |
| `create` | `[--pack DIR]` | new journal for the pack's run; with `--run`, pack and journal are derived |
| `replace-pack` | `--pack DIR` | swap the evidence; stales heads; refused while an attempt is pending or if the run identity differs |
| `status` | none | prints the snapshot |
| `begin` | `MODULE` | opens an attempt; prints its ticket; an unknown module exits 2 listing the valid ids |
| `interrupt` | `--ticket ID --reason TEXT` | finishes the attempt as interrupted |
| `cp0-submit` | `--ticket ID --review FILE` | validates and settles CP-0; rejected: attempt JSON on stdout, issue lines on stderr, exit 1; missing file: exit 2 |
| `cp1-submit` | `--ticket ID --step STEP --review FILE` | STEP is one of `source_context`, `financials`, `narrative`, `readiness`; a rejected review (kept for the step's one repair or final) exits 1 as `cp0-submit` |
| `cp1-quality-inputs` | `--ticket ID` | prints the registers for the QA review |
| `cp1-promote` | `--ticket ID --review FILE` | retains the QA review and settles CP-1; a rejected review exits 1 as `cp0-submit` |
| `step-output` | `--ticket ID --step STEP` | prints a retained valid step output |
| `statement-preview` | `--ticket ID --output DIR` | statement preview; never settles |
| `interface-preview` | `--ticket ID --output DIR` | statement preview with interface |
| `register-preview` | `--ticket ID --output DIR` | register preview |
| `envelope` | `--module CP-1 --output DIR` | writes the promoted CP-1 envelope; refuses an existing directory |
| `render` | `--envelope DIR [--output DIR] [--pathway ID]` | writes `accepted.html` or `refused.html` and `complete.json`; `--run` derives the report path |
| `module-submit` | `--module CP-1A\|CP-2\|CP-3\|CP-4\|CP-5\|CP-6 --ticket ID --step STEP --review FILE` | validates and settles the module; rejected: issue lines on stderr, exit 1; unknown step: exit 2 |
| `module-context` | `--module M --ticket ID --step STEP` | prints the step's CONTEXT entries as indent-1 JSON (CP-5's scope is compact JSON in the runner's prompt; `step-instructions --with-sources` shows the exact text) |
| `step-instructions` | `--module M --ticket ID --step STEP [--with-sources]` | prints the step's instructions as the development runner composes them: `--- system ---` (contract, rules, JSON Schema) and `--- user ---` (CONTEXT, upstream, REPAIR after a rejection). Declared sources become `source: ID -> originals/<sha256> (extracted text N bytes, sha256 H)` lines under a `--- sources ... ---` header (path under the pack directory; N is the extracted text's length); `--with-sources` prints that text inline as the runner sends it. Exit 2: ticket not of that module, step not in the chain or not the ticket's next |
| `report` | `--pathway ID [--output DIR]` | writes `index.html` and `report.json`; the pathway must be the run's; `--run` derives the report path |
| `resume` | `[--ticket ID --review FILE]` | prints pending ticket/module/step/retention or resubmits through the same workflow |
| `report-open` | `[--pathway ID] [--browser]` | renders if absent and prints absolute `index.html`; browser opening is optional |
| `cp-model-publish` | `--output DIR` | begins and settles CP-MODEL; exit 2 with a message when refused |
| `cp-model-verify` | `--output DIR` | re-derives from the journal; exit 2 when issues |

### Steps and instructions

`step-instructions` serves every step: CP-0 `source_readiness`; CP-1 `source_context`,
`financials`, `narrative`, `readiness`, `quality`; and, for `module-submit`/`module-context`, one
step each in `deploy-vii plan` order: CP-1A `business_context`, CP-2 `credit_synthesis`, CP-4
`legal_covenants`, CP-3 `relative_value`, CP-5 `integrity_review`, CP-6 `committee_challenge`
(CP-4 runs only when the run requests it). The flow per step: `begin MODULE` once, then
`step-instructions` (read its rules and JSON Schema; the `source:` lines name the files under
`pack/` to read yourself; CONTEXT carries the CP-1A/CP-2/3/4/6 upstream entries and CP-5's
`integrity-scope`; after a rejection it ends with the REPAIR block), write the review file, then
the submit command. A rejected review prints the attempt JSON on stdout and the validator's issue
lines on stderr with exit 1 (all four submit commands); repair the review from those lines and
resubmit or `begin MODULE` again (one repair attempt, `resume.md`). Exit 2 is a refusal with one
line: unknown module, step or ticket, a missing review file, or `report` for another pathway
than the run's. Do not run a module the journal shows blocked or stale; report it.

## `live` (development only, not a delivery route)

`live` calls OpenRouter with a credential read from the file named in
`settings/project.toml`, under a mandatory USD cap bound to a batch ledger. It never
uses the host's model. Subcommands: `probe`, `module --module CP-0|CP-1|CP-1A`,
`regression`, `canary`, `corpus ATTEMPT CASE_ID`, `reconcile --directory DIR --batch-id ID`,
`schema-check --models ID,...`. Common flags: `--directory DIR --cap USD` (both required for
probe/module/regression/canary), `--seed`, `--batch-id`, `--artifact-root`, `--effort
{high,xhigh}`, `--models`, `--max-tokens`, `--timeout`, `--catalog`, `--report-directory`,
`--settings`. Exit codes: 0 ok, 2 failed, 3 cap reached, 4 credit exhausted.

Run `live` only when the user asks and names the cap. Example shape (a dummy cap):

```
deploy-vii live module --module CP-0 --directory ./deploy-vii-out/<run-id>/journal --cap 1
```

## Offline boundary

`doctor`, `run`, `resume`, derived paths and `report-open` are available offline. Their native
Copilot-host behaviour is still deferred. `live` remains a separate OpenRouter development path,
not a host-model path.
# Existing single-step commands

The `run` command is the compact host-review loop. These commands remain available for operators
who need to inspect or advance one journal step directly. Global `--out` goes before the command.

```sh
deploy-vii doctor
deploy-vii execution --directory <journal> resume
deploy-vii execution --directory <journal> report-open
deploy-vii --out <delivery-root> execution create --run <run-id>
deploy-vii --out <delivery-root> execution --directory <journal> report --pathway credit_snapshot --run <run-id>
deploy-vii --out <delivery-root> execution --directory <journal> render --envelope <envelope> --run <run-id>
deploy-vii prepare --request <request.json> --root <pack-root> --output <pack>
deploy-vii execution --directory <journal> create --pack <pack>
deploy-vii execution --directory <journal> begin CP-0
deploy-vii execution --directory <journal> cp0-submit --ticket <ticket> --review <review.json>
deploy-vii execution --directory <journal> begin CP-1
deploy-vii execution --directory <journal> cp1-submit --ticket <ticket> --step source_context --review <review.json>
deploy-vii execution --directory <journal> step-output --ticket <ticket> --step source_context
deploy-vii execution --directory <journal> cp1-quality-inputs --ticket <ticket>
deploy-vii execution --directory <journal> cp1-promote --ticket <ticket> --review <review.json>
deploy-vii execution --directory <journal> statement-preview --ticket <ticket> --output <preview>
deploy-vii execution --directory <journal> envelope --module CP-1 --output <envelope>
deploy-vii execution --directory <journal> render --envelope <envelope> --output <page>
deploy-vii execution --directory <journal> cp-model-publish --output <model>
deploy-vii execution --directory <journal> cp-model-verify --output <model>
deploy-vii execution --directory <journal> status
deploy-vii execution --directory <journal> interrupt --ticket <ticket> --reason <reason>
deploy-vii live module --directory <directory> --module CP-2 --cap 1
```

The run-all command preserves the initial instructions and writes journal-bound repair prompts
with a ticket/repair suffix. Review filenames stay unchanged. CP-MODEL publishes through its
existing deterministic publisher into `<out>/<run-id>/cp-model/`, separate from `report/`.
Report reuse verifies both HTML and receipt against the current journal; stale, partial,
conflicting or symlinked files are refused and preserved. Use a fresh explicit report destination
when an earlier report must be retained.
