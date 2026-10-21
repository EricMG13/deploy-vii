# Development model and reasoning matrix

Updated 20 October 2026. This is a development-routing design covering Claude
and GPT hosts. Explicit Codex launch targets and Claude worker definitions are now
installed in `Makefile` and `.claude/`; see the [environment guide](development/environment.md).
These do not change the coordinator's model. Analytical Modules in the
future Copilot product require separate qualification.

The pairings are task counterparts, not proven equality in quality, speed or cost.
Select an available host family explicitly for each task.

| Responsibility | Claude route | GPT route | Reason |
| --- | --- | --- | --- |
| Mechanical scaffolding | Sonnet 5.5 / low | GPT-6.1 Sol / low | Complete file contract, small decision space. |
| Bounded implementation and normal repairs | Sonnet 5.5 / medium | GPT-6.1 Sol / medium | Default balance for caller tracing, edits and affected checks. |
| Financial/provenance/parser/state boundary | Sonnet 5.5 / high | GPT-6.1 Sol / high | Interacting invariants and consequential error paths. |
| Research and dependency tracing | Sonnet 5.5 / medium | GPT-6.1 Sol / medium | Source-grounded comparison; high for unresolved interacting constraints. |
| Architecture diagnosis | Fable 5.1 / high | GPT-6 Astra / high | Concrete blocked boundary requiring sustained reasoning. |
| Escalated repair | Fable 5.1 / high | GPT-6 Astra / high | Fresh diagnosis after repeated causal failures. |
| Refactoring/optimisation sweep | Sonnet 5.5 / medium | GPT-6.1 Sol / medium | Bounded inspection; high for financial/state changes. Scripts measure performance. |
| Coordinator and PR owner | Current selected host model | Current selected host model | Own scope/publication; routine Git/CLI work needs no extra agent. |

Haiku 5.5 and GPT-6 Luna remain optional development-worker candidates for simple
classification or extraction. Separately, the user's model-assisted test pool is
Luna, GLM 5.3 Flash and latest DeepSeek at high/xhigh under the
[testing policy](testing-and-telemetry.md). Python still owns arithmetic.

Native identifiers: `claude-sonnet-5-5`, `claude-fable-5-1`, `claude-haiku-5-5`,
`gpt-6.1-sol`, `gpt-6-astra`, `gpt-6-luna`. GPT model/effort support was checked in
the local Codex catalog dated 2026-10-20; official sources are linked below.
These are not automatically OpenRouter slugs or Copilot labels. Verify the actual
interface and account entitlement. One implementation owner carries each task
through its checks. The user's confidence-review and key-area
rewrite-tournament requirements apply; this matrix adds no extra approval chain.

## Routing rules

- Record task, host, requested model/effort, editable paths and checks. Low needs
  a complete brief; normal work starts at medium; sensitive work starts at high.
- The proposed escalation trigger is two concrete failed repairs or a demonstrated
  design blocker. File count or elapsed time alone is insufficient.
- Model/effort changes use a fresh context and concise handoff of causal failures.
  Switching Claude/GPT is explicit, never a silent provider fallback.
- xhigh/max/ultra are outside the initial development-worker defaults. The user's
  test-pool instruction separately permits high/xhigh as appropriate. Ultra may
  delegate and needs suitable scope.
- Parallel work needs disjoint writes and isolated test state; no recursive agent
  spawning. Research/architecture roles diagnose without production edits.
- Inspect effective routing. Profile settings can override dispatch settings.
  Prose alone does not create a read-only sandbox or remove inherited credentials.

The [Claude catalog](https://platform.claude.com/docs/en/models/overview),
[Claude effort guidance](https://platform.claude.com/docs/en/build-with-claude/effort)
and [GPT model guidance](https://developers.openai.com/codex/models) inform these
starting assignments; their suitability here is our inference, not benchmark proof.
[Codex custom agents](https://developers.openai.com/codex/subagents) document native
precedence/inherited permissions. [Claude configuration](https://code.claude.com/docs/en/sub-agents)
differs; do not translate profile fields blindly. No worker model calls were made.

OpenRouter model-assisted tests use the user's random pool and retain exact
requested/returned IDs, provider metadata, effort support, usage, finish reason,
latency, fallback and every attempt's artifacts. See the [test selection,
telemetry and matched-comparison rules](testing-and-telemetry.md). This is separate
from worker routing and does not qualify final Copilot runtime assignments.

Later development comparisons use the same starting tree, inputs, tools and
acceptance criteria. Record first-pass correctness, defects, repairs, elapsed time
and usage/cost where available; equal effort labels do not imply equal compute.
See [sweeps](maintenance-sweeps.md) and [publication](pr-worktree-workflow.md).

Not verified: model account entitlement, live routing correctness,
quality/cost rankings or live OpenRouter analytical model acceptance.
