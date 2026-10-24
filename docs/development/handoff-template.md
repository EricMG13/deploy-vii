# Coding-session handoff template

Copy into the existing task folder as `handoff.md` only when needed. This is a
development record, not an executable lock or an authorization to create a chat.
Unknown fields must say unknown and explain what must be checked; never infer
permission, a zero balance, stopped processes or completed reviews from omission.

## Identity and authoritative inputs

- Stable task ID / goal ID (or explicitly no managed goal):
- Snapshot UTC timestamp / outgoing owner session / intended successor session:
- Workspace / branch / base commit / observed head commit:
- Working/index state: clean or local patch hashes + paths; untracked file manifest;
  ignored evidence needed for recovery (private material stays local):
- Goal, acceptance criteria and source-linked user constraints:
- Latest user corrections, pauses/cancellations and instruction precedence:
- Editable paths / protected sources / dependency identities:

## Continuity and ownership

- Actual host/model/provider/effort/tool permissions, or unknown with reason:
- Budget source, total cap, consumed amount and remaining amount across ALL
  continuations, reviews, compaction/handoff calls; time/money/token units separate:
- Current authorization and publication owner; pending approvals/denials and scope:
- Outstanding tools, processes, agents, external writes and uncertain outcomes:
  identifiers, expected effects, how to reconcile, and who owns them:
- Transfer status: NOT READY until the old writer is stopped/reconciled and one
  successor is explicitly assigned. A file assertion alone does not prove this.
- User pause/exhausted budget means no work resumes; a new session changes neither.

## Evidence and next step

- **Verified facts:** claim, original source/command, artifact/hash, tested commit:
- **Hypotheses:** what remains uncertain, counterevidence and next falsifying check:
- **Decisions:** rationale, authoritative requirement and conditions for revisiting:
- Failed approaches: exact failure and why it should not be blindly repeated:
- Tests/reviews completed, failed, blocked or pending, bound to the tested tree;
  confidence-review and key-area differential/property-test obligations remain visible:
- Smallest next action; prerequisites; when earlier evidence becomes stale:

## Successor preflight

Read the original goal/constraints and latest corrections, then inspect Git status,
base/head/index/worktree, pending actions and host routing. Resolve discrepancies
before writing or retrying an external action. A resumed/forked session can replay
history; a new ID alone does not establish a fresh context. Revalidate important
facts from sources, not just an outgoing summary or a summary of that summary.

Preserve requested pauses, limits, credentials policy and publication authority.
Request missing approval only for an actually unapproved action; the handoff adds
no general approval chain. Do not rerun successful reviews indefinitely solely
because a session changed; rerun checks whose inputs or assumptions changed.
