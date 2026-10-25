---
name: deploy-vii
description: Run the offline Deploy VII evidence workbench for a named issuer pack, review validated steps, resume retained tickets, and open the local report.
---

# Deploy VII delivery skill

Python owns arithmetic, hashes and validation. You provide evidence-grounded review text. Real
Copilot host behaviour remains unverified; see `docs/native-delivery.md`.

## Setup and delivery

- Install Python 3.13 and uv 0.12.5, then run `uv sync --locked` and `deploy-vii doctor`.
- The default delivery root is `./deploy-vii-out`; set `DEPLOY_VII_OUT` or pass global `--out`.
- Repository skill: `.github/skills/deploy-vii/`. User scope can copy the directory to
  `~/.copilot/skills/deploy-vii/`.
- Use a safe run id (letters, digits, dot, underscore and hyphen). Each run owns `pack/`,
  `journal/`, `reviews/`, `cp-model/` and `report/` below the delivery root.

## Offline review loop

1. Inspect the plan, prepare the named sources and start the offline runner:

```
deploy-vii plan CP-1 CP-2
deploy-vii run --request <request.json> --root <source-root> --run <run-id>
```

2. The command writes an instructions file, then stops with exit 3 and
   names the exact review file to write. Use the instructions, write that review
   as JSON and rerun the same command. It submits through the production validators, in plan
   order, and stops on a rejected review (exit 1) with issue lines. Exit 2 means refused input.
   Later tickets and repairs add the same ticket/repair suffix to both files, preserving earlier
   files. CP-MODEL publishes deterministically into `cp-model/`; it does not ask for a review.
3. To inspect a pending ticket, run `deploy-vii --out <delivery-root> execution --run <run-id>
   resume`. To resubmit explicitly, add `--ticket <ticket> --review <file>`.
4. When the run is complete, open the printed report path with `deploy-vii --out <delivery-root>
   execution --run <run-id> report-open`; add `--browser` to ask the platform opener.

The runner never dispatches a model. The host writes reviews; these are checked by module
validators, but do not carry tool-loop evidence such as search records. Never edit a pack or
journal by hand. Preserve existing files; use a new run id for a new source snapshot.

For direct single-step operation, inspect the instructions immediately before writing each review:

```
deploy-vii execution --directory <journal> step-instructions --module CP-0 --ticket <ticket> --step source_readiness
deploy-vii execution --directory <journal> cp0-submit --ticket <ticket> --review <review.json>
deploy-vii execution --directory <journal> step-instructions --module CP-1 --ticket <ticket> --step source_context
deploy-vii execution --directory <journal> cp1-submit --ticket <ticket> --step source_context --review <review.json>
deploy-vii execution --directory <journal> step-instructions --module CP-1 --ticket <ticket> --step quality
deploy-vii execution --directory <journal> cp1-quality-inputs --ticket <ticket>
deploy-vii execution --directory <journal> cp1-promote --ticket <ticket> --review <review.json>
deploy-vii execution --directory <journal> step-instructions --module CP-2 --ticket <ticket> --step credit_synthesis
deploy-vii execution --directory <journal> module-submit --module CP-2 --ticket <ticket> --step credit_synthesis --review <review.json>
```

**Gap:** The offline doctor has not been exercised on a clean machine install.
**Gap:** The run protocol has not been exercised on a native Copilot host.
**Gap:** Derived paths have not been checked on a native host workspace.
**Gap:** Process interruption and resume on a host remain untested.
**Gap:** Report location and opening on a host remain untested.

## Development-only commands

`deploy-vii live` is a capped OpenRouter development runner using a local credential. Do not run
it for host delivery. `textutil` is unavailable in some environments; offline tests use a
qualified test double there. Keep live/native checks paused unless the coordinator lifts the
pause. Modules after CP-6 (including CP-8 and Portfolio Fit) are not implemented.

Command details: `references/commands.md`; retained journal semantics: `references/resume.md`;
acceptance and deferred host checks: `references/acceptance.md`.
