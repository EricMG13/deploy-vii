# 0010: Opus route for sensitive work

Date: 21 October 2026. Status: adopted. Numbers 0007–0009 are reserved by the
[implementation plan](../development/tasks/implementation/plan.md).

## Context

The [worker matrix](../model-matrix.md) had two tiers: Sonnet 5.5 for every routine
and sensitive role, and Fable 5.1 for architecture and escalation. Opus was not
considered, and no reason was recorded. Sensitive work therefore ran on Sonnet at
high effort, even though it covers the review regime's key areas: artifact state,
provenance, financial calculations and execution ordering.

## Decision

**User:** add an Opus route. `dv-sensitive` (financial, provenance, parser and
shared-state changes) moves from Sonnet 5.5 / high to Opus 5.5 / high
(`claude-opus-5-5`). All other routes, the escalation trigger and the Fable roles
are unchanged. Rewrite-tournament roles keep their current assignment.

## Consequences

- `.claude/agents/dv-sensitive.md`, the matrix and the
  [environment guide](../development/environment.md) are updated to match.
- Tasks already dispatched keep their recorded route. New `dv-sensitive`
  dispatches use Opus.
- Not verified: Opus 5.5 account entitlement or comparative quality and cost on
  this repository's tasks.
