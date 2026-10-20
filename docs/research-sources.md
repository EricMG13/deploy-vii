# Research sources and evidence boundaries

Research date: 2026-10-20. Primary documentation was accessed on that date.
Capabilities are documented facts; project suitability and gate choices are
engineering judgments. No model, framework or throughput benchmark was run.

## Primary external sources

Follow-up update on 20 October 2026: [GPT model guidance](https://developers.openai.com/codex/models),
[Codex custom-agent settings](https://developers.openai.com/codex/subagents),
[Git worktree behavior](https://git-scm.com/docs/git-worktree),
[GitHub CLI PR creation](https://cli.github.com/manual/gh_pr_create) and
[merge matching](https://cli.github.com/manual/gh_pr_merge) support the updated
development documents. The local model catalog was checked separately; route
pairings remain project recommendations, not benchmark results.

- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents): workflow patterns, chaining, routing and bounded evaluation. Conceptual source; its tooling discussion carries an age caveat.
- [Copilot CLI custom agents](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-custom-agents): specialist profiles and separate subagent context.
- [Copilot agent skills](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills): reusable instructions/resources.
- [Copilot SDK](https://docs.github.com/en/copilot/how-tos/copilot-sdk): programmatic integration capabilities. The January 2026 preview announcement is not treated as current release status.
- [Pydantic AI OpenRouter](https://pydantic.dev/docs/ai/models/openrouter/): native OpenRouter model integration.
- [Pydantic AI multi-agent patterns](https://pydantic.dev/docs/ai/guides/multi-agent-applications/): delegation and programmatic handoffs.
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview): graph orchestration, durable execution and persistence.
- [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/): agents, explicit workflows and integrations; language-specific maturity varies.
- [CrewAI Flows](https://docs.crewai.com/v1.15.28/en/concepts/flows): explicit state/control flow around crews and agents.
- [Claude model IDs](https://platform.claude.com/docs/en/models/overview) and [effort](https://platform.claude.com/docs/en/build-with-claude/effort): current development-model identifiers and reasoning controls.
- [Claude subagents](https://code.claude.com/docs/en/sub-agents) and [settings](https://code.claude.com/docs/en/settings): profile fields and precedence.
- [GitHub Actions security](https://docs.github.com/en/actions/reference/security/secure-use): least privileges, untrusted inputs and pinned actions.
- [OpenRouter API](https://openrouter.ai/docs/api_reference/overview): request/response metadata and provider boundary for future tests.

## Local evidence inspected

The latest [reuse assessment](deploy-vi-reuse.md) inspected selected source at
the recorded `bd71346301b373afa72655916a4c1b42bf4c9823` commit and separate working
Direction C report-app files. [Source hashes and catalog metadata](review-evidence/2026-10-20-sources.json)
identify them and the user's supplied HTML. This is a sampled source review,
not a rerun of historical tests or a fresh remote audit.

For the current requests, primary sources also include
[ICM](https://github.com/SorretAI/ICM),
[OpenRouter's model catalog](https://openrouter.ai/api/v1/models),
[reasoning controls](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
and [OpenAI endpoint guidance](https://developers.openai.com/api/docs/guides/deployment-checklist).
They support the development-context and testing documents, not account access
or live acceptance. ICM is assessed for development only.

- Deploy VI working tree: AGENTS.md, scoped simple-pathways policy/sequence,
  CI/pre-commit/pyproject, gate scripts and the 2026-10-13 scope amendment.
- Deploy VI recorded origin/main `bd71346301b373afa72655916a4c1b42bf4c9823`:
  CI/pyproject and size script. No fetch was used to certify current remote state.
- Tested checkpoint `16617a0b92b566f29f14e5c033a7206aed873a27`: CP-2/3/5
  contracts and Module inventory. Current working-tree foundation is not the
  complete implementation and was not copied into this repository.
- Existing 2026-10-18 performance review: repeated source parsing/qualification
  observations. Historical fixture measurements are not a Deploy VII speed claim.
- Claude and Codex plugin metadata, installed versions, explicit hook settings,
  dependency-guard and GitNexus hook source, selected plugin READMEs/hook manifests.

Only sanitized conclusions are included here. Credentials, personal settings,
raw memory, private issuer files and analytical outputs are not copied.

Not verified: latest remote Deploy VI code, live providers, framework benchmarks,
plugin runtime effects or complete source-method equivalence in Deploy VII.
