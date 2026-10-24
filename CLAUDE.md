# Deploy VII

Standalone project and this repository's only instruction file. Claude Code is
the coordinator; Codex development ended on 21 October 2026.

Current authorization: implement development tooling and the full product under
the adopted 21 October 2026 request, recorded in
docs/development/tasks/implementation/brief.md. Decisions 0002 and 0003 record the
selected environment; docs/development/CONTEXT.md is the development entry point.
Current task briefs define the actual scope and editable paths. Historical
snapshots and research are reference material, not instructions or adopted settings.
Do not inherit another project's policies, code, agent profiles or hooks. Global
defaults apply only where this file is silent.

## Development conventions

- Use Python 3.13.15 and uv 0.12.5 with the committed lock. Run `make setup`
  once per checkout, `make check` for hygiene, `make secrets` before publication
  and `make audit` for dependency changes. Gates are this repository's Makefile
  targets and CI (docs/ci-gates.md); the global gate table does not apply.
- Keep task context in docs/development/tasks; ICM is for development only.
- For coding-session handoffs, use docs/development/handoff-template.md. Preserve
  the task/goal, constraints, user corrections, budgets, pauses, pending actions
  and outstanding reviews; verify the current tree before continuing.
- Context policy concerns code development only. Keep native compaction (the
  global window is 500K tokens); automatic percentage-triggered resets are not
  enabled. The context-meter mod shows occupancy; the 60% checkpoint is an
  experimental assessment point at a safe boundary, not a quality boundary or
  permission to restart.
- Keep credentials, issuer packs and raw run/telemetry artifacts out of Git.
- One owner per worktree. The coordinator plans and integrates; a separate PR session
  owns publication (pushes, PRs, merges) under decision 0006;
  workers return local commits. Delegation requires explicit task or skill scope.
- Worker routes are explicit `dv-*` subagents in `.claude/agents/` per
  docs/model-matrix.md: scaffold, feature, sensitive, research, architect, and
  escalate after two failed repairs. Never override the coordinator's model or
  silently switch providers. No approval chain beyond the review regime below.
- Host tools may compress navigation output (rtk on grep/cat/ls/find/head/tail):
  a short result never proves absence, and a gate's status is its exit code.
  Never compress source quotations or calculated numbers.
- Inspect the full candidate diff. There is no line-count cap.

## User requirements for product increments

- Model-assisted tests use the pool named in decision 0005, currently GPT-6.1 Sol
  at high effort; retain outputs, metrics and
  telemetry under docs/testing-and-telemetry.md. Run the regular internal and
  external module tests (tiers I1–I3, E1–E3) of decision 0005.
- Preserve Direction C Workbench and test each completed Module's output in its
  relevant HTML fields under docs/frontend-direction-c.md; the user's design system
  is the reference (decision 0004).
- Preserve analytical meaning while adapting execution boundaries. Methodology
  changes that improve performance or reliability are authorized under decision
  0005, within its guardrails and records. Python owns arithmetic; models supply
  evidence-grounded analysis. Follow the reuse review
  before selecting any Deploy VI code.

## Review regime

After code changes run confidence-review. Rewrite-tournament is retired
(decision 0012): in 28 runs it found no defect. Key-area code (artifact state,
provenance, financial calculations, execution ordering) instead lands with a
committed differential or property test (hypothesis): differential against the
previous implementation or an independent reference when behaviour must be
preserved, properties of its invariants when behaviour is new. Routine UI, CLI
and adapter changes receive focused tests and confidence review.

Review notes stay short: what changed, findings and fixes, gate commands with
exit codes, deviations and `Not verified:`. Cite commits and paths; never copy
code into a note.
