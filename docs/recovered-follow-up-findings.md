# Follow-up findings recovered from the conversation

Historical note: the formerly pending documentation updates have now been applied
to [methodology](methodology-adaptation.md), the [model matrix](model-matrix.md),
[sweeps](maintenance-sweeps.md) and [PR/worktree workflow](pr-worktree-workflow.md).
Statements below about incomplete procedures describe the earlier recovery point.

Recorded 20 October 2026. These observations and proposals were discussed after
the original research documents, before the user reset the project to setup only.
They are preserved here at the user's restoration request. No product changes,
live model tests or new project policy resulted from them.

## Methodology adaptation

The proposed architecture calls for explicit handoffs, dependency tracking,
artifact ownership and validation boundaries. It does not, by itself, justify
changing financial definitions, judgment rules or analytical depth. This is an
engineering inference, not a demonstrated equivalence result.

The inspected historical methodology decision already called for a partial port,
not a full rewrite: preserve analytical methods and change packaging only as
needed. The research identified required CP-1A context before CP-2 and optional
inputs that become available through serial order. A future parallel scheduler
must preserve those inputs or make the changed analytical scope explicit.
No clause-by-clause methodology adaptation assessment was completed.

## GPT counterparts for development roles

The local Codex model catalog and official documentation exposed these options.
The proposed mapping is by task responsibility, not proven model equivalence:

| Development responsibility | Existing Claude proposal | Proposed GPT counterpart |
| --- | --- | --- |
| Complete mechanical task | Sonnet 5.5, low | GPT-6.1 Sol, low |
| Bounded implementation/research | Sonnet 5.5, medium | GPT-6.1 Sol, medium |
| Difficult financial/provenance boundary | Sonnet 5.5, high | GPT-6.1 Sol, high |
| Architecture diagnosis/escalated repair | Fable 5.1, high | GPT-6 Astra, high |

Observed host identifiers were `gpt-6.1-sol` and `gpt-6-astra`; low/medium/high
efforts were advertised. These host identifiers do not establish OpenRouter
routing or analytical quality. No GPT profiles were created or invoked.
The original matrix remains unchanged; this table is supplementary research.
Native agent profiles can pin reasoning effort, so verify effective settings
rather than assuming a per-dispatch override wins.

## Refactoring and optimisation sweeps

The user requested adding sweeps, but their policy was not completed before the
scope correction. A proposed direction was a bounded sweep after a proven layer:
check cohesion, duplicated parsing and repeated validation, then make only
justified changes with affected checks. Optimisation needs before/after measures
and preserved financial/source behavior. No sweep, benchmark or speedup was run
for Deploy VII; no rewrite-tournament process is adopted by this note.

## PR and worktree management

Actual observations from Deploy VI were comparative evidence only:

- Its local worktree inventory listed 54 entries: 19 detached and 7 prunable.
  This establishes accumulated bookkeeping, not that every entry caused a fault.
- PRs #115–119 formed a dependency chain and were closed. The comment on
  [PR #115](https://github.com/EricMG13/deploy-vi/pull/115) says it was superseded
  under the owner's commit-only/cherry-pick batch workflow.
- [PR #120](https://github.com/EricMG13/deploy-vi/pull/120) consolidated five
  provenance-preserving cherry-picks onto main. Its recorded 2,907 changed lines
  used an explicitly owner-authorized 4,000-line policy in that project.
  Neither number establishes a Deploy VII size policy.
- [CI run 39083840064](https://github.com/EricMG13/deploy-vi/actions/runs/39083840064)
  failed `test_cp5_traces_every_step_before_it[full]`: an actual CP-5 dependency
  ordering mismatch, with 1 failed, 3,886 passed and 312 skipped. Individual
  implementation results therefore did not establish integrated correctness.
- Git worktrees share normal refs and repository configuration. They isolate
  working files and indexes; they do not isolate publication ownership or auth.

The proposed improvement was one coordinator owning remote pushes and PRs,
workers returning local commits from isolated branches, explicit PR base/head,
and integration checks on the precise candidate. The operating procedure was
not completed, implemented or tested. No old worktrees were pruned.

## Setup status observed later

Authentication subsequently worked and the initial repository was published.
Hosted Actions jobs did not start because of an account runner-eligibility block;
private ruleset access returned HTTP 403 under the account plan. These were
platform limits, not passing or failing product tests. The mistaken setup history
was then replaced at the user's request by the clean root commit `f49845d`.
This restoration does not reconnect that removed history.

## Primary technical references

- [Codex models](https://developers.openai.com/codex/models)
- [Codex custom agents and effort precedence](https://developers.openai.com/codex/subagents)
- [Git worktrees and shared refs/configuration](https://git-scm.com/docs/git-worktree)
- [GitHub CLI PR creation](https://cli.github.com/manual/gh_pr_create)
- [GitHub CLI merge commit matching](https://cli.github.com/manual/gh_pr_merge)

Not verified: methodological equivalence, model parity, live profile loading,
sweep benefits or a complete Deploy VII PR-management workflow.
