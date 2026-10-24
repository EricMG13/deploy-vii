# Development model and reasoning matrix

Updated 21 October 2026. Claude Code coordinates development; worker definitions
live in `.claude/agents/` (see the [environment guide](development/environment.md)).
Codex/GPT development routes were retired on 21 October 2026. These routes do not
change the coordinator's model. Analytical Modules in the future Copilot product
require separate qualification.

| Responsibility | Claude route (agent) | Reason |
| --- | --- | --- |
| Mechanical scaffolding | Sonnet 5.5 / low (`dv-scaffold`) | Complete file contract, small decision space. |
| Bounded implementation and normal repairs | Sonnet 5.5 / medium (`dv-feature`) | Default balance for caller tracing, edits and affected checks. |
| Financial/provenance/parser/state boundary | Opus 5.5 / high (`dv-sensitive`) | Interacting invariants and consequential error paths; the review regime's key areas ([decision 0010](decisions/0010-opus-sensitive-route.md)). |
| Research and dependency tracing | Sonnet 5.5 / medium (`dv-research`) | Source-grounded comparison; high for unresolved interacting constraints. |
| Architecture diagnosis | Fable 5.1 / high (`dv-architect`) | Concrete blocked boundary requiring sustained reasoning. |
| Escalated repair | Fable 5.1 / high (`dv-escalate`) | Fresh diagnosis after two concrete failed repairs or a design blocker. |
| Refactoring/optimisation sweep | Sonnet 5.5 / medium (`dv-feature`) | Bounded inspection; financial/state changes route to `dv-sensitive`. Scripts measure performance. |
| Coordinator and PR owner | The Claude Code session's selected model | Own scope/publication; routine Git/CLI work needs no extra agent. |

Haiku 5.5 remains an optional worker candidate for simple classification or
extraction. Separately, the user's model-assisted test pool is the set named in
decision 0005, currently GPT-6.1 Sol at high (amendment, 22 Oct 2026; the Luna, GLM 5.3
Flash and latest DeepSeek pool is superseded), under the [testing policy](testing-and-telemetry.md);
that is product testing through OpenRouter, not development routing. Python still
owns arithmetic.

Native identifiers: `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-fable-5-1`,
`claude-haiku-5-5`. The tiers are Sonnet for routine work, Opus for key-area
implementation and Fable for diagnosis and escalation.
Verify the actual interface and account entitlement. One implementation owner
carries each task through its checks. The user's confidence-review and key-area
differential/property-test requirements apply; this matrix adds no extra approval chain.

## Routing rules

- Record task, requested model/effort, editable paths and checks. Low needs
  a complete brief; normal work starts at medium; sensitive work starts at high.
- The escalation trigger is two concrete failed repairs or a demonstrated
  design blocker. File count or elapsed time alone is insufficient.
- Model/effort changes use a fresh context and concise handoff of causal failures,
  never a silent switch.
- xhigh/max/ultra are outside the development-worker defaults. The user's
  test-pool instruction separately permits high/xhigh as appropriate. Ultra may
  delegate and needs suitable scope.
- Parallel work needs disjoint writes and isolated test state; no recursive agent
  spawning. Research/architecture roles diagnose without production edits.
- Inspect effective routing: `CLAUDE_CODE_SUBAGENT_MODEL` defaults only agents
  without a model; frontmatter models win. Prose alone does not create a read-only
  sandbox or remove inherited credentials.

The [Claude catalog](https://platform.claude.com/docs/en/models/overview),
[Claude effort guidance](https://platform.claude.com/docs/en/build-with-claude/effort)
and [Claude sub-agent configuration](https://code.claude.com/docs/en/sub-agents)
inform these starting assignments; their suitability here is our inference, not
benchmark proof.

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
