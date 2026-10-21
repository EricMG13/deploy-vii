# PR creation and worktree management

Adopted procedure: 20 October 2026. The environment branch
`codex/development-environment` was squash-merged into `main` on 21 October 2026;
new work branches from `main`.
See the [setup result](development/tasks/environment/result.md) for publication state.

## Evidence and diagnosis

| Observed struggle | Evidence | Implication |
| --- | --- | --- |
| Dependency chains required publication rework | PRs #115–119 were closed/consolidated into #120 under that project's owner decision | Avoid stacks by default; use them with a clear dependency/retargeting owner. |
| Change budgets differed across snapshots | The consolidated PR used an explicitly authorized 4,000-line policy | Choose a Deploy VII budget explicitly; neither 800 nor 4,000 is inherited. Count the whole candidate diff. |
| Worktree bookkeeping accumulated | Local inventory: 54 entries, 19 detached, 7 prunable | Track ownership/lifecycle; counts alone do not prove every entry caused a fault. |
| Task checks missed integration behavior | Recorded CI failed on a CP-5 dependency-order mismatch | Test the combined candidate and affected consumers after integration. |
| Access/platform state differed from code health | Authentication, hosted-runner eligibility and private ruleset access had separate outcomes | Report each separately; a push is not acceptance and an unstarted job tests no code. |

Exact historical references/counts are in the [recovered findings](recovered-follow-up-findings.md).
They support this diagnosis, not a claim that every cancellation had one cause.
Worktrees isolate working files/indexes while sharing ordinary refs and default
repository configuration. They do not isolate credentials or remote pushes.
See [Git's documentation](https://git-scm.com/docs/git-worktree).

## Default: one publication owner

Since [decision 0006](decisions/0006-delegated-choices-and-orchestration.md) (21 October 2026), one long-lived PR session
started by the coordinator owns remote branches, pushes, PR creation/updates and
squash merges after local gates and reviews; the coordinator owns integration.
Workers implement and make local commits in assigned worktrees, returning commit
IDs and results. They do not independently push and open PRs by default.
This reduces races over publication, retargeting and branch updates.

This is an operating convention, not a sandbox/security boundary: shared refs and
credentials remain accessible unless the host actually restricts them. Do not copy
tokens to workers or expand authentication silently to make publication succeed.

## Implementation procedure

The [development ICM assessment](development-context.md) recommends one compact
task brief and result to carry these identities and evidence links. This is
development documentation, independent of the product's runtime folder layout.

1. **Assign:** repository, exact base commit, unique branch/worktree, owner, editable
   paths, dependencies and checks. Prefer available managed-worktree tools. Verify
   the predecessor instead of assuming a stale default branch is the right base.
2. **Work:** one writer owns a worktree/index, with isolated test/output state.
   Workers do not change another checkout, rewrite shared refs, run global cleanup,
   push or create PRs independently. Parallel jobs need disjoint writes.
3. **Return:** freeze the candidate and report base/head, ordered commits, changed
   paths, actual checks, dependencies and limits. Avoid concurrent tests/edits
   against another owner's changing worktree.
4. **Integrate:** use either the worker branch as PR head or one integration branch.
   Cherry-picks retain source commit IDs in the handoff; inspect resulting tree/diff.
   Conflicts create a new candidate and invalidate affected checks. Do not also
   merge the same worker changes through another route.
5. **Validate:** inspect the complete diff against the intended base, size and
   dependencies. Check the combined candidate. Reuse evidence only when relevant
   code, dependencies and assumptions match; a worker's green result is insufficient.
6. **Publish:** within authorized scope, push an explicit branch and verify its
   remote SHA. Check for an existing PR for that head, including after an uncertain
   response. Create one draft PR with explicit repository/base/head and a multiline
   description supplied through `--body-file`.
7. **Manage:** attach the PR to its task and retain its URL. Repair the same PR;
   track checks for the current candidate, not a green predecessor. Changed head/base
   invalidates affected evidence. Missing, cancelled or blocked checks are incomplete.
8. **Merge/clean up:** the PR session merges when decision 0006 DC-3 is met (local
   gates exit 0, reviews recorded, diff inspected; hosted CI noted if it did not run).
   Match expected head SHA where supported. Preserve result/needed artifacts, then
   archive completed managed worktrees. Check unpushed commits/ignored files first;
   do not blanket-prune work that belongs to other sessions.

[GitHub CLI creation](https://cli.github.com/manual/gh_pr_create) explains explicit
head behavior. The [merge guide](https://cli.github.com/manual/gh_pr_merge) documents
`--match-head-commit`. These flags do not supply authorization or configure gates.

## Exceptions and failure recovery

- A deliberate stack records parent PR, merge order and retargeting owner. After
  parent merge/rewrite, recompute child diffs/checks; squash does not preserve ancestry.
- If a worker must publish, give it one named branch and one bounded operation.
  The coordinator pauses writes to that branch and verifies the outcome.
- A rejected push calls for inspecting remote changes. An authorized rewrite uses
  an expected remote SHA and coordinated ownership, never a blind force push.
- If checks cannot start or protection is unavailable, record the platform blocker
  and keep acceptance pending. Do not weaken checks or alter paid plans automatically.

The environment request covers its setup branch and draft PR. It does not
authorize merging, unrelated cleanup or analytical product implementation.

Not verified: a live Deploy VII multi-worktree run, automated publication controls,
configured branch protection. Decision 0002 selects advisory full-diff reporting
without an arbitrary blocking line-count budget.
