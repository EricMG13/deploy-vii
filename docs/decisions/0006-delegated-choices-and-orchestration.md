# 0006: Delegated choices, orchestration and publication

Date: 21 October 2026. Status: adopted. User instruction:

> "Main orchestration session will be set by me using fable. But all PR work to be
> handled by a sub-session. Display a goal prompt for end to end plan completion in a
> new session. Apply your recommendations (but keep a record of your choices)
> 2. API key = documents/op router.rtf if no credit use agent as proxy. 3. Merge what
> has been done so I can start developing in the new session"

Items marked **user** restate the user's decision. Items marked **delegated** are the
coordinator's choices under that delegation. Each delegated choice lists the
alternatives considered. A later user instruction overrides any of them; record the
override here.

This decision supersedes:
- the "Publication" row of decision 0002 ("No automatic merge");
- the "Coordinator" row of decision 0003 ("plans, integrates and publishes").

## Choices

| ID | Subject | Choice | Basis | Alternatives considered |
| --- | --- | --- | --- | --- |
| DC-1 | Orchestration | **User:** the user's main session runs on Fable and orchestrates the plan. **Delegated:** it plans, dispatches `dv-*` workers and integrates. It writes no product code. | User instruction; CLAUDE.md coordinator role | — |
| DC-2 | Publication | **User:** all PR work runs in a sub-session. **Delegated:** one long-lived PR session per plan run, started by the orchestrator, owns pushes, PRs, CI reading, conflict resolution and merges. It changes no product code except mechanical conflict resolution, and reports failures back to the orchestrator for routing. | User instruction | A new PR session per milestone (more sessions, less context) |
| DC-3 | Merge policy | **Delegated:** the PR session squash-merges each milestone (or independent task) PR to `main` once local gates exit 0 (`make check`, `make product-check`, `make secrets`), the required reviews are recorded and the diff is inspected. Delete merged branches. While hosted CI is blocked by GitHub billing, local gates are the merge gate, and each PR states that hosted CI did not run. | User asked for end-to-end completion and PR work in a sub-session | Wait for the user to approve each merge (slower; the user can still pause at any time) |
| DC-4 | DCF definition | **Delegated:** DCF = FCF − dividends paid, i.e. discretionary cash flow in the S&P sense of free operating cash flow less dividends. DCF/debt = DCF / canonical total debt. Buybacks are not deducted, and the limitation says so. Implemented in plan M1. | Dividends already exist as a controlled account (`dividends_paid`); no repurchase account exists in the model, so the buyback variant would need a new source schedule | Source-defined only; FCF − dividends − buybacks |
| DC-5 | CP-MODEL artifact | **Delegated:** the HTML Model destination plus the calculation JSON artifact. The r14 XLSX workbook export is deferred, and recorded as such in the coverage map. CP-MODEL requires accepted CP-1 and joins CP-5's scope. Implemented in plan M6.1. | The design system has a Model destination; XLSX duplicates it | Keep the r14 XLSX export now |
| DC-6 | Recurring external-test caps | **Delegated:** E1 US$3 per module case, E2 US$15 per milestone, E3 US$3 per week. A **cumulative ceiling of US$200** of OpenRouter spend, including the first US$50 batch, applies. The orchestrator pauses external testing and asks the user before exceeding it (one ceiling across providers since 24 Oct 2026; see the amendment below). | Applies decision 0005's proposal; the ceiling bounds spend the user did not size | No recurring tests until the user sets caps |
| DC-7 | API credential | **User:** the key is in `~/Documents/op router.rtf`. **Delegated:** the runner reads the file at dispatch time, in process (RTF → text via macOS `textutil`, whitespace stripped, `sk-or-` prefix checked). The key is held in memory only. It is never printed, logged, persisted, committed, put in a URL or passed on a command line. Redaction tests cover request records and errors. Agents never read the file into a transcript; the project denies `Read` on it. | User instruction; the testing contract excludes credentials from evidence | Exporting `OPENROUTER_API_KEY` in the shell (does not persist across agent tool calls) |
| DC-8 | No-credit proxy | **User:** when OpenRouter has no credit, use an agent as proxy. **Delegated:** (1) a native Luna agent if one is installed and entitled; the Codex CLI was not on `PATH` on 21 October 2026. (2) Otherwise a Claude agent proxy running the same frozen case, prompt, schema and validators. Proxy results form a separate cohort labelled `proxy:<agent>`. They never pool with OpenRouter results and never count as qualification of Luna, GLM 5.3 Flash or DeepSeek. Usage is recorded where exposed; unknown metrics are null with a reason. | User instruction; earlier backup rule (`brief.md:36-37`) | Stop external testing when credit is exhausted |
| DC-9 | Design reference bytes | **Delegated:** the orchestrator fetches the remaining Front Page and `lib/` files through the claude-design connector (M3.1). Each is accepted only if its byte size matches the project listing. On a mismatch, the user is asked to export the project. | Avoids blocking M3 on a manual export | User export first |
| DC-10 | Current work | **User:** merge the review, plan and decisions to `main` now. **Delegated:** squash-merge as one PR from `claude/deploy-vii-adversarial-review-a78eab`. | User instruction | — |

### Amendment, 22 Oct 2026 (DC-6, user-approved E1 cap amendment)

The user ruled, relayed through the Watcher session on 22 Oct 2026: "approve US$10 per CP-1
case. E1 for the CP-1 case: US$10 per batch, batch cap US$12 with the CP-0 case. Other modules
stay at US$3 per case. The US$200 cumulative ceiling is unchanged. ... Pause and ask the user
before any figure above these." The orchestrator pauses and asks before any figure above them.

### Amendment, 23 Oct 2026 (DC-8, task 7.8)

A dispatch 402 is read for its reason before it is called exhaustion. OpenRouter's in-flight
refusal (`in_flight_budget_exhausted`, limit source `openrouter_in_flight_budget`) waits out its
Retry-After (at most 300 s, 120 s when absent) and is re-sent once as a new, separately
reserved attempt; like any credit refusal it uses up no model retry, and a second one is
exhaustion. The credit refusal (`openrouter_credits`), and
any 402 whose body cannot be read, is exhaustion as before, and the stop reports the requested
and affordable max_tokens the body states. Nothing else in DC-8 changes: no model or cohort is
switched, and the no-credit route stays a coordinator decision.

### Amendment, 24 Oct 2026 (DC-6, user: one ceiling across providers)

Amendment (user, 24 Oct 2026): the US$200 cumulative ceiling is one ceiling across providers
— OpenRouter and Anthropic-API spend count together, summed over every ledger under
`artifacts/model-tests/.ledgers`. Charged at the decision: US$60.11 of 200 (OpenRouter 40.94,
Anthropic 19.17).

## Consequences

- CLAUDE.md, `docs/pr-worktree-workflow.md`, `settings/project.toml` and
  [plan.md](../development/tasks/implementation/plan.md) are updated to match. Plan
  decisions are renumbered: degradation → 0007, contract shape → 0008, Pathways → 0009.
- Decision 0005's recurring caps now apply under DC-6.

Not verified:
- that the key file holds a valid, funded OpenRouter key (the file was not read);
- native Luna agent availability beyond the absence of `codex` on `PATH`;
- whether GitHub branch rules allow squash merges without hosted checks (to be observed
  at the first merge).
- that the `Read` deny rule binds shell reads; it covers the Read tool only, so not
  printing the key remains a convention for shell commands.
