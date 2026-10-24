---
name: deploy-vii
description: Run the Deploy VII evidence workbench on a named issuer source pack - freeze the sources, keep a local execution journal, submit CP-0 and CP-1 reviews step by step, publish the CP-MODEL page and render the CP-1 report - using the deploy-vii command line. Use when asked to produce, resume or interrupt a Deploy VII credit run.
---

# Deploy VII delivery skill

Python owns every number and every validation; you supply evidence-grounded review text
and run the commands below. The methodology lives in the repository, not in this skill.
No part of this has been tried on a real Copilot host (see `docs/native-delivery.md`,
"Not accepted offline"). This skill declares no `allowed-tools`: the host asks before
each shell command, so expect a prompt per step.

## Prerequisites

- A checkout of the Deploy VII repository, Python 3.13 and uv. Run `make setup` once
  (it runs `uv sync --locked`). Then run the CLI as `uv run --locked deploy-vii ...`, or
  as `deploy-vii ...` with `.venv/bin` on PATH. The commands below omit the prefix.
- **Gap:** no installer, `setup` or `doctor` command exists. `make setup` is the only
  route and nothing checks the install. `deploy-vii plan CP-0` shows that the CLI runs.
- A request file (JSON, schema `preparation-request/1`) naming the run and the source
  files, and a pack root directory holding those files (`references/commands.md`).

## Where outputs land

**Gap:** the product fixes no delivery directory; every command takes a caller-chosen
path. This skill's convention is `./deploy-vii-out/<run-id>/`, holding `pack/`,
`journal/`, `reviews/` and one directory per published artifact below. Several commands
refuse an output path that already exists: use a new directory each time.

## Flow

Module order follows `deploy-vii plan`. This skill covers what the CLI can submit today:
CP-0, CP-1 and CP-MODEL.

1. Show the order for the modules requested (prints only, runs nothing):

```
deploy-vii plan CP-0 CP-1 CP-MODEL
```

2. Freeze the named sources into a new pack directory (it must not exist):

```
deploy-vii prepare --request <request.json> --root <pack-root> --output ./deploy-vii-out/<run-id>/pack
```

3. Create the execution journal for the run:

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal create --pack ./deploy-vii-out/<run-id>/pack
```

4. CP-0. Begin an attempt (prints JSON; keep its `ticket_id`), write the source-readiness
   review to `reviews/cp0.txt`, then submit it. Printed `issues` mean the review was
   rejected; one repair attempt is allowed (`references/resume.md`).

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal begin CP-0
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp0-submit --ticket <ticket> --review ./deploy-vii-out/<run-id>/reviews/cp0.txt
```

5. CP-1. Begin, then submit the four steps in order (`source_context`, `financials`,
   `narrative`, `readiness`), one review file per step, then the QA review:

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal begin CP-1
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp1-submit --ticket <ticket> --step source_context --review ./deploy-vii-out/<run-id>/reviews/cp1-source_context.txt
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal step-output --ticket <ticket> --step source_context
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp1-quality-inputs --ticket <ticket>
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp1-promote --ticket <ticket> --review ./deploy-vii-out/<run-id>/reviews/cp1-quality.txt
```

   `step-output` prints a retained valid step output (read what a step produced before
   writing the next review); `cp1-quality-inputs` prints the registers for the QA review;
   `cp1-promote` submits that QA review and settles CP-1. Repeat `cp1-submit` for each
   step name.

6. Optional preview while CP-1 is pending (never settles a ticket):

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal statement-preview --ticket <ticket> --output ./deploy-vii-out/<run-id>/statement-preview
```

7. Write the CP-1 envelope and render the report page (both refuse an existing path):

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal envelope --module CP-1 --output ./deploy-vii-out/<run-id>/envelope
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal render --envelope ./deploy-vii-out/<run-id>/envelope --output ./deploy-vii-out/<run-id>/report
```

   The page is `report/accepted.html`, or `refused.html` which states why. Rendering does
   not accept the page: browser acceptance stays unrun. **Gap:** no command opens it.

8. CP-MODEL, only when the run requests it and CP-1 is accepted or restricted:

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp-model-publish --output ./deploy-vii-out/<run-id>/model
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp-model-verify --output ./deploy-vii-out/<run-id>/model
```

9. Inspect the journal at any point (prints the snapshot as JSON):

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal status
```

## Interrupt and resume

- Interrupt a pending attempt. This records a reason in the journal; it does not stop any
  process the host is running:

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal interrupt --ticket <ticket> --reason "<why>"
```

- **Gap:** there is no `resume` command. `begin` refuses while any attempt is pending
  ("resume or explicitly interrupt it first"). To resume, re-run the same `*-submit` with
  the same ticket and the same review text: the journal keeps each response before
  validating it, so a crash mid-validation continues from the kept response. Different
  text for the same step is refused. Details and line references: `references/resume.md`.
  Behaviour after a killed host session is not verified.
- **Gap:** only CP-0, CP-1 and CP-MODEL have submit or publish actions in the CLI. CP-1A
  and the later modules in `deploy-vii plan` cannot be submitted from here.

## Model dispatch

You (the host model) write the review texts. `deploy-vii live` is a different thing: a
capped OpenRouter test runner for development, using a local credential file, never the
host model. **Gap:** nothing dispatches the host's own models, and there is no single
run-all command. Do not run `deploy-vii live` unless the user asks for a capped
development test and names the cap (`references/commands.md`).

## Stop rules

- Never exceed a cap in `settings/project.toml` (`recurring_caps_usd`,
  `cumulative_ceiling_usd`) and never pass a larger `--cap` to `live`.
- No credit top-up and no workaround for missing credit. If `live` exits with code 4
  (credit exhausted), stop and report; the ticket stays pending for the coordinator.
- Report a refused or rejected result as it is. Never edit a journal, pack or output by
  hand, and never call a module accepted when the journal says otherwise.
- Never print or store credentials.

Command tables: `references/commands.md`. Journal semantics: `references/resume.md`.
Acceptance checklist and blockers: `references/acceptance.md`.
