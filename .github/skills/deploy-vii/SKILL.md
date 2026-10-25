---
name: deploy-vii
description: Run the Deploy VII evidence workbench on a named issuer source pack - freeze the sources, keep a local execution journal, submit the CP-0, CP-1 and later module reviews step by step, publish the CP-MODEL page and render the full report - using the deploy-vii command line. Use when asked to produce, resume or interrupt a Deploy VII credit run.
---

# Deploy VII delivery skill

Python owns every number and every validation; you supply evidence-grounded review text
and run the commands below. The methodology lives in the repository, not in this skill.
Nothing here has been tried on a real Copilot host (`docs/native-delivery.md`, "Not accepted
offline"). No `allowed-tools` is declared: the host asks before each shell command.

## Prerequisites
- A checkout of the Deploy VII repository, Python 3.13 and uv. Run `make setup` once
  (`uv sync --locked`), then `uv run --locked deploy-vii ...`, or `deploy-vii ...` with
  `.venv/bin` on PATH (the commands below omit the prefix).
- **Gap:** no installer, `setup` or `doctor` command exists; nothing checks the install.
  `deploy-vii plan CP-0` shows that the CLI runs.
- A request file (JSON, schema `preparation-request/1`) naming the run and the source files,
  and a pack root directory holding them (`references/commands.md`).

**Gap:** the product fixes no delivery directory; every command takes a caller-chosen path.
This skill's convention is `./deploy-vii-out/<run-id>/`, holding `pack/`, `journal/`,
`reviews/` and one directory per published artifact below. Several commands refuse an output
path that already exists: use a new directory each time.

## Flow
Module order follows `deploy-vii plan`. The CLI submits CP-0 to CP-6 and publishes CP-MODEL.

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

4. CP-0. Begin an attempt (prints JSON; keep its `ticket_id`), print the step's instructions
   (read its rules and JSON Schema; the sources it lists are the files under `pack/`), write
   the review to `reviews/cp0.txt`, then submit it. A rejected review exits 1 with the
   issues on stderr; one repair attempt is allowed (`references/resume.md`).

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal begin CP-0
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal step-instructions --module CP-0 --ticket <ticket> --step source_readiness
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp0-submit --ticket <ticket> --review ./deploy-vii-out/<run-id>/reviews/cp0.txt
```

5. CP-1. Begin; for each step in order (`source_context`, `financials`, `narrative`,
   `readiness`) print its instructions, submit a review file; then the QA review (`quality`):

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal begin CP-1
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal step-instructions --module CP-1 --ticket <ticket> --step source_context
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp1-submit --ticket <ticket> --step source_context --review ./deploy-vii-out/<run-id>/reviews/cp1-source_context.txt
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal step-output --ticket <ticket> --step source_context
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp1-quality-inputs --ticket <ticket>
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal step-instructions --module CP-1 --ticket <ticket> --step quality
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp1-promote --ticket <ticket> --review ./deploy-vii-out/<run-id>/reviews/cp1-quality.txt
```

   `step-output` prints a retained output (read it before the next review);
   `cp1-quality-inputs` prints the QA registers; `cp1-promote` settles CP-1. Repeat per step.

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
   not accept it: browser acceptance stays unrun. This is the CP-1 page; see step 10.

8. CP-MODEL, only when the run requests it and CP-1 is accepted or restricted:

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp-model-publish --output ./deploy-vii-out/<run-id>/model
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal cp-model-verify --output ./deploy-vii-out/<run-id>/model
```

9. Each later module (CP-1A, CP-2 to CP-6; names in `references/commands.md`): begin, print
   the step's instructions (rules, JSON Schema, CONTEXT; the sources it lists are files under
   `pack/`), write the review, submit. A rejected review prints the validator's issues on
   stderr and exits 1: repair, then `begin` again. Exit 2 refuses.

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal step-instructions --module CP-2 --ticket <ticket> --step credit_synthesis
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal module-submit --module CP-2 --ticket <ticket> --step credit_synthesis --review ./deploy-vii-out/<run-id>/reviews/cp2.txt
```

10. Deliver the full report in the run's pathway (`status` shows it); unrun or blocked
   modules show their state. Refuses an existing directory. **Gap:** nothing opens it.

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal report --pathway credit_snapshot --output ./deploy-vii-out/<run-id>/front-page
```

11. Inspect the journal at any point (prints the snapshot as JSON):

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal status
```

## Interrupt and resume
- Interrupt a pending attempt (records a reason; stops no host process):

```
deploy-vii execution --directory ./deploy-vii-out/<run-id>/journal interrupt --ticket <ticket> --reason "<why>"
```

- **Gap:** there is no `resume` command, and `begin` refuses while any attempt is pending.
  To resume a pending step, re-run the same `*-submit` with the same ticket and the same
  review text (`references/resume.md`). Behaviour after a killed host session is not verified.

## Model dispatch
You (the host model) write the review texts. `deploy-vii live` is a capped OpenRouter test
runner for development with a local credential file, never the host model. **Gap:** nothing
dispatches the host's own models and there is no run-all command. Do not run it unless the
user asks for a capped development test and names the cap (`references/commands.md`).

## Stop rules
- Never exceed a cap in `settings/project.toml` (`recurring_caps_usd`,
  `cumulative_ceiling_usd`); read the numbers there. Never pass a larger `--cap` to `live`.
  The cumulative ceiling spans OpenRouter and Anthropic spend together (decision 0006 DC-6,
  amendment of 24 Oct 2026: `docs/decisions/0006-delegated-choices-and-orchestration.md`).
- No credit top-up and no workaround for missing credit. If `live` exits with code 4
  (credit exhausted), stop and report; the ticket stays pending for the coordinator.
- Report a refused or rejected result as it is. Never edit a journal, pack or output by
  hand, and never call a module accepted when the journal says otherwise.
- Never print or store credentials.

Command tables: `references/commands.md`. Journal semantics: `references/resume.md`.
Acceptance checklist and blockers: `references/acceptance.md`.
