# 0012: Retire rewrite-tournament

Date: 24 October 2026. Status: adopted. Supersedes the tournament part of the
review row in [decision 0003](0003-claude-coordinated-environment.md).

## Context

Rewrite-tournament ran on key-area code (artifact state, provenance, financial
calculations, execution ordering): four candidate roles, a blind arbiter, a
backup-and-apply step and a long written result per run. The 28 recorded runs in
`docs/development/tasks/implementation/*-review.md` confirmed no defect. Every
challenger had to match the incumbent's output exactly, so a tournament could change
readability or speed only; speed wins were milliseconds. Three incumbents held, and in
one the arbiter preferred a candidate that failed strict typing
(period-reconciliation-review.md). The behaviour checks built for the tournaments, the
differential corpora, were the useful part, and they lived in ignored scratch folders.
Confidence review and dispatched task reviews did find defects (M2, M4, M5, M6).

## Decision

**User:** remove rewrite-tournament from the review regime. Key-area code lands with
a committed differential or property test (hypothesis, already a dependency):

- differential against the previous implementation or an independent reference over
  generated cases when behaviour must be preserved;
- properties of the function's invariants when behaviour is new.

Review notes stay short: what changed, findings and fixes, gate commands with exit
codes, deviations and `Not verified:`. They cite commits and paths and never copy code.
Confidence review and dispatched task reviews are unchanged.

## Consequences

- CLAUDE.md, the plan, the brief, `settings/project.toml`, the `dv-*` agents, the PR
  template and the docs that restated the rule are updated. Historical review notes and
  completed milestone briefs keep their tournament records.
- Not verified: that the committed tests catch what a tournament's corpus would have,
  and the time saved; no per-task timing was recorded.
