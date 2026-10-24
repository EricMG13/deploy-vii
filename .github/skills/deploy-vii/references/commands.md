# deploy-vii command surface

Derived from the argparse definitions at origin/main 14e81d2:
`src/deploy_vii/__main__.py`, `execution_cli.py`, `live/cli.py`. Entry point
`deploy-vii = deploy_vii.__main__:main`. Every path argument is caller-chosen.

## Top level

| Command | Flags | Writes |
| --- | --- | --- |
| `plan MODULE...` | none | prints the dependency order; nothing is written |
| `prepare` | `--request FILE --root DIR --output DIR` | new pack directory (`pack.json`, `originals/`, `complete.json`); refuses an existing output |
| `cp0` | `--pack DIR --review FILE --output DIR` | stateless CP-0 delivery without a journal; not used by this skill's flow |
| `preview` | `--run FILE --output DIR` | an unrun report shell from a Run JSON |
| `execution` | `--directory DIR` then an action | the journal at DIR |
| `live` | see below | development test runner |

## `execution --directory DIR <action>`

| Action | Flags | Effect |
| --- | --- | --- |
| `create` | `--pack DIR` | new journal for the pack's run |
| `replace-pack` | `--pack DIR` | swap the evidence; stales heads; refused while an attempt is pending or if the run identity differs |
| `status` | none | prints the snapshot |
| `begin` | `MODULE` | opens an attempt; prints its ticket |
| `interrupt` | `--ticket ID --reason TEXT` | finishes the attempt as interrupted |
| `cp0-submit` | `--ticket ID --review FILE` | validates and settles CP-0 |
| `cp1-submit` | `--ticket ID --step STEP --review FILE` | STEP is one of `source_context`, `financials`, `narrative`, `readiness` |
| `cp1-quality-inputs` | `--ticket ID` | prints the registers for the QA review |
| `cp1-promote` | `--ticket ID --review FILE` | retains the QA review and settles CP-1 |
| `step-output` | `--ticket ID --step STEP` | prints a retained valid step output |
| `statement-preview` | `--ticket ID --output DIR` | statement preview; never settles |
| `interface-preview` | `--ticket ID --output DIR` | statement preview with interface |
| `register-preview` | `--ticket ID --output DIR` | register preview |
| `envelope` | `--module CP-1 --output DIR` | writes the promoted CP-1 envelope; refuses an existing directory |
| `render` | `--envelope DIR --output DIR [--pathway ID]` | writes `accepted.html` or `refused.html` and `complete.json` |
| `cp-model-publish` | `--output DIR` | begins and settles CP-MODEL; exit 2 with a message when refused |
| `cp-model-verify` | `--output DIR` | re-derives from the journal; exit 2 when issues |

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

## Gaps in this surface

- No `setup`/`doctor`/`resume`/`run-all`/open-report command.
- No submit action for CP-1A or any module after CP-MODEL.
- No fixed delivery directory (the skill's `./deploy-vii-out/<run-id>/` is only a convention).
- `live` is not a host-model path.
