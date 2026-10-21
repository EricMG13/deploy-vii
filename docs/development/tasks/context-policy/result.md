# Code-development context evaluation result

Task: `dvii-dev-context-001`, owner session `01a15b2e-4bf1-72f1-bf44-e6abbfff34cc`.
Inspection baseline: `c7c0ad05cb2b71f290442ead61a5e184527a4595`.
Scope: coding-session continuity only, as explicitly clarified by the user.

Recommendation: retain native compaction plus the existing source-linked ICM
task records; use selective handoffs at safe task boundaries. Treat 60% as a
proposed experimental checkpoint, with no automatic reset. Current evidence
does not establish an optimum or measured development-quality benefit here.
The [policy/evaluation plan](../../context-management.md) links all nine sources,
including the model-dependent counterevidence from Anthropic's March 2026 case.

## Confirmed gaps and changes

| Finding in the current tree | Change / boundary |
| --- | --- |
| The setup owner was identified only relative to the current chat | Stable task IDs and a concrete owner session added to the ICM index/brief. This identifies ownership; it does not lock the worktree. |
| No common handoff record explicitly covered pause/budget/pending actions/corrections/reviews | Added one optional template inside the existing development workflow. It separates verified facts, hypotheses and decisions and requires source revalidation. |
| Project settings did not distinguish a context experiment from the product's random model pool | Added an explicit development-only context block: fixed routing within comparisons, total-goal budgets, no automatic reset and no implemented lifecycle controller. Product settings remain unchanged. |

These are resumability/documentation gaps, not observed coding failures caused
by context length. No conflicting 60% reset policy was found in the inspected
project/user configuration. No global settings were changed.

## Host audit and unknowns

- Codex CLI **0.163.0-alpha.10.2**: native configuration readback reports null for
  context window and compaction limit/scope, with system/user/project layers
  present. This is not proof of disabled compaction or the desktop's live state.
- Generated native protocol includes token-usage, compact, resume and fork
  surfaces. The window is optional/null, usage contains both last and cumulative
  counters, and `excludeTurns` controls response hydration rather than proving
  old context is excluded from model input. No lifecycle method was invoked.
- Claude **2.1.296**: inspected settings have no explicit auto-compaction
  percentage override. Headroom and claude-mem remain enabled; tool/session hooks
  are present. Actual invocation, transformation, retention and performance were
  not measured. Native defaults/inherited runtime state remain unknown.
- No managed goal was active. No numerical live-trial budget was supplied; no
  model call, new chat, reset, global hook or product change was made.

## Offline results

Nine [synthetic cases](fixtures.json) were walked through using the handoff
checklist. Four also have executable local probes. This evaluates checklist
coverage and recoverable state, **not** the model's behavior under a reset and
not an automated resume guard.

| Case | Method / observed result | Required handling |
| --- | --- | --- |
| C01 clean handoff | Tabletop: complete information permits a preflight; no transfer occurred | Continue only after owner assignment and verified authority, not merely a new session ID. |
| C02 stale HEAD | Scratch Git repository: an additional commit changed HEAD; mismatch detected | Reconcile the new tree and invalidate affected evidence. |
| C03 same HEAD, dirty index/worktree | Scratch Git repository: HEAD unchanged, staged and unstaged patches both nonempty with distinct hashes | Inspect/preserve both; a commit ID alone is insufficient. |
| C04 pause/exhaustion | Tabletop: both conditions remain explicit in the template | A handoff cannot revoke a pause or replenish a budget. No runtime guard is implemented. |
| C05 pending action | A synthetic local process was confirmed running, then explicitly terminated/reaped | Confirm old execution state before a successor writes; uncertain remote outcomes need separate reconciliation. |
| C06 misleading summary | Tabletop: source-linked corrections and fact/hypothesis fields expose the omitted counterevidence requirement | Re-read original evidence. Template fields cannot prove a summary is truthful. |
| C07 routing/review drift | Tabletop: fixed comparison routing and outstanding reviews are carried explicitly | Reject a confounded comparison or false completed-review claim. |
| C08 missing occupancy denominator | Native schema inspection verifies the model window may be absent/null | Mark occupancy unknown; no percentage-trigger claim. No live event was collected. |
| C09 fork with replayed history | Tabletop plus protocol inspection: session identity and response hydration do not establish model input | Verify actual input construction before classifying as a fresh-context trial. |

Raw probe output: ignored `artifacts/context-policy/offline-probes.json` and
`native-config.json`. The probes used temporary Git/process state and were cleaned
up. There were no live resets, paid sweeps, quality rankings, measured token
savings or causal comparisons. The proposed matched 36-trial pilot remains
unrun, subject to available controls and authorized live-development scope.

## Confidence review

1. **Accidental product scope:** compared parsed project settings against HEAD;
   only `development.context` is added. Product model pool/frontend/runtime/CI
   settings are unchanged. No code-development policy is wired into the product.
2. **Prose mistaken for enforcement:** explicitly label settings/template as
   workflow contracts; no runtime controller, context monitor or automatic
   transfer is claimed. Native schema availability is not a demonstrated reset.
3. **Unsafe continuation:** negative Git/process probes confirm why stale HEAD,
   dirty state and pending actions must be carried. Single-writer control,
   pause/budget continuity and external idempotency remain proposed safeguards
   requiring real host enforcement before an automated implementation.
4. **Biased evidence or overgeneralization:** original sources, corrections and
   counterevidence are preserved. Tabletop cases and executable probes are
   distinguished from model trials; 60% and the pilot size are experimental choices.
5. **Review/publication drift:** prior confidence-review and rewrite-tournament
   requirements remain. This update is docs/config/fixtures only; tournament is
   inapplicable. Existing draft PR remains the sole publication target; no merge.

Validation: project TOML/fixture JSON parsing, local Markdown links, `make check`
and `make secrets` are required for this candidate. Hosted execution retains
the [existing account restriction](../environment/result.md); no attempt is made
to change billing, repository visibility or global host policy.
