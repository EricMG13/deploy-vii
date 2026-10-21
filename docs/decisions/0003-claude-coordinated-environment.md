# 0003 — Claude-coordinated environment and consolidated host settings

Date: 21 October 2026. Status: adopted under the user's request to consolidate the
workflow findings, the Codex chats and this documentation into coherent global and
project settings, with Claude in control and one instruction file. Supersedes the
Workers, Reviews and Plugins/hooks rows of [0002](0002-development-environment.md);
its other rows stand. Its Coordinator row's publication duty moved to the PR session
under [decision 0006](0006-delegated-choices-and-orchestration.md).

Underlying goal, as the chats and documents state it: reproducible,
evidence-preserving development in which calculations, provenance and gaps stay
exact. That means:

- explicit model routes;
- one owner per worktree;
- reviews scaled to key areas;
- deterministic gates judged by exit codes;
- native compaction with source-linked handoffs;
- host tooling that neither captures issuer data nor rewrites verification output.

| Area | Decision | Reason |
| --- | --- | --- |
| Instruction file | `CLAUDE.md` only; `AGENTS.md` removed. | User instruction. Claude Code reads only CLAUDE.md files when any exists in the directory chain, so two files invite drift. |
| Coordinator | The Claude Code session; it plans, integrates and publishes. | User instruction, 21 October 2026. |
| Codex | Development ended. Codex Make targets, `.codex/` notes, GPT matrix routes and the devtools `--host codex` telemetry path removed. | User instruction: nothing stays open only for Codex. Historical task records keep their original labels. |
| Workers | `dv-scaffold`, `dv-feature`, `dv-sensitive`, `dv-research`, `dv-architect`, plus `dv-escalate` (Fable 5.1, high) after two concrete failed repairs. | The matrix's escalation route had no agent. |
| Reviews | confidence-review after code; rewrite-tournament only for artifact state, provenance, financial calculations and execution ordering. | The user's recorded correction. The global reminder hook stays silent here because CLAUDE.md names the regime. |
| Project settings | `.claude/settings.json` disables the firebase and fallow plugins, sets ponytail to lite and denies reading `.env`. | Unrelated plugins cost context. Full ponytail can trim analytical nuance. Credentials stay unread. |
| Context | Native compaction at the global 500K-token window. The context-meter mod displays occupancy. No automatic resets. | Keeps the context policy and supplies the occupancy reading its 60% assessment lacked. |
| Host tooling (global) | claude-mem, headroom and presence disabled; rtk limited to read-only navigation commands; Opus review agents read-only. | claude-mem captured prompts and failed continuously. Headroom saved nothing and sat in the API path. rtk rewrote gate and git commands. |

Not verified:
- context-meter rendering in the Desktop Code tab;
- ponytail reading the project `env`;
- the effect of the 500K window on cost.
