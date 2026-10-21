# Existing plugin and hook assessment

Inspected 2026-10-20: local Claude/Codex plugin registrations, Claude settings,
installed hook definitions and selected hook source. No global settings were
changed. Installed/enabled metadata is not proof that every hook ran in this chat.
This assessment recommends a project profile; it does not uninstall anything.

## Material findings

1. **Historical workflow policy conflicts with current instructions.** Claude
   SessionStart injects `REWRITE-TOURNAMENT ACTIVE`. Earlier notes retired it;
   the current user requires confidence-review after code changes and, per a
   later correction, rewrite-tournament for key-area code only. Current
   instructions govern. (Resolved 2026-10-21: see Applied state below.)
2. **Duplicate initialization paths.** Headroom is enabled as a plugin and also
   explicitly called in SessionStart/PreToolUse. Its README says the hook ensures
   a durable deployment. Duplicate checks exist; duplicate process creation or
   measurable latency has not been established.
3. **Overlapping memory installations.** Codex enables claude-mem from two
   marketplaces/caches (13.10.1 and 14.0.1), while a third registration is disabled.
   Claude also enables 14.0.1. Tool-observation/file-context hooks create a retention
   and stale-context risk for issuer data. Actual duplicate capture is unverified.
4. **Environment versions differ.** Claude Superpowers 7.0.0 and Ponytail 4.7.0
   differ from Codex's exposed versions. Instructions and defaults may differ
   between development hosts; installed skill count is not a capability benchmark.
5. **Dependency guard fails open by design.** Its source logs unexpected errors,
   uses a nine-second budget and has documented shell-parsing misses. It helps
   detect unknown/new package names; it cannot replace lockfiles or auditing.

## Recommended use

| Capability / observed plugin | Benefit | Issue / boundary | Recommendation |
| --- | --- | --- | --- |
| confidence-review skill + startup reminder | Concrete self-review of doubts and error paths | A reminder cannot enforce test quality | Keep the skill; one reminder is enough. |
| Superpowers | Structured design/debugging workflows | Mandatory planning/review chains can conflict with scoped owner policy | Use selected skills and the user's explicit review requirements; no inherited approval chain. |
| Ponytail | Encourages simple implementations | Terse/shortest-diff defaults can hide analytical nuance | Optional light use; invariants and complete evidence take precedence. |
| Caveman (Codex enabled; Claude disabled) | Compact routine communication | Compression can obscure reasons, units and limitations | Omit for financial reasoning and final reports. |
| Headroom | Potential context/output efficiency | Duplicate hooks and transformation fidelity require checks | Evaluate later on long tool output; retain originals and exit codes. |
| RTK Bash hook | Compresses command output | Can obscure details needed for gate diagnosis | Optional for navigation; keep raw validation logs. |
| Claude-mem | Cross-session development recall | Duplicate versions, stale authority, private-data retention | No automatic issuer/run capture; prefer explicit sanitized handoffs. |
| GitNexus hook/MCP | Call graph and impact exploration | Starts subprocesses on searches; requires a current index | Defer for tiny core; enable when code size justifies it. |
| Fallow + feedback hooks | Structural/dead-code investigation | Weak benefit before code exists; JS/TS emphasis | Defer until an applicable codebase exists. |
| SecureCoder | Dependency/security analysis | Broad mandatory scans can duplicate CI and create approval friction | Use targeted checks; retain CI as authoritative. |
| Chrome DevTools / browser / computer use | Visual and offline report acceptance | Overlapping browser surfaces, permissions, platform variance | Choose one route per task at renderer acceptance. |
| PDF / spreadsheet tools | Document inspection and XLSX intake research | Interactive extraction may differ from the shipped Python reader | Useful for inspection; validate with actual runtime readers. |
| Documents / presentations / templates / visualize | Research communication | Not needed in analytical runtime; artifact duplication | On demand only. |
| Vercel (disabled) / Firebase (Claude enabled) | Hosting/cloud tooling | Offline reports need no hosting backend | No project dependency. |
| Google Antigravity / modern-web guidance | Specialized development help | Additional model/tool surfaces without a current need | On demand only; no default runtime role. |
| App tools / GitHub | Project organization and repository actions | Access differs by interface and account | Keep scoped; verify actual outcomes. |

GitNexus's inspected hook already skips absent/locked indexes and warns on stale
ones; do not claim every search necessarily runs analysis. The dependency guard
and memory hooks have wider behavior than a short description reveals. No speed
or reliability improvement from disabling them was measured.

## Project policy

Local prek hooks now check syntax, whitespace, merge markers, private-key patterns,
file size and applicable Ruff rules. `make secrets` scans before publication;
the full secret scan is a CI job, not a model-powered hook. Keep hooks deterministic
and narrow. Avoid model-powered Stop hooks and
auto-retry/review loops. Never compress source quotations or calculated numbers.
Do not use remembered notes as analytical evidence or policy authority.

Project settings do not automatically subtract inherited hook lists. Claude's
[settings precedence](https://code.claude.com/docs/en/settings) explains merging;
verify effective settings before any later change. Do not solve duplication by
blanket-disabling security hooks. No broad permission grants.

## Applied state (2026-10-21, decision 0003)

User settings (`~/.claude`, backed up under `backups/2026-10-21-consolidation/`):

- **Removed or disabled:**
  - claude-mem: disabled. It captured prompts and tool use and had failed continuously.
  - headroom: plugin, hooks and `ANTHROPIC_BASE_URL` proxy route removed.
  - presence: disabled.
- **rtk:** runs through `hooks/rtk-scoped.sh`. Only read-only grep/rg/cat/ls/find/head/tail
  commands without pipes or counts reach it; git, test, gate and process commands
  run unmodified.
- **Review reminders:** the two fixed reminder hooks became `hooks/review-reminder.sh`,
  which is silent where the project's instruction file names its review regime
  (this repository's CLAUDE.md does). It also re-fires after compaction elsewhere.
- **Defaults:**
  - `autoCompactWindow` 500000 and `effortLevel` high;
  - at most 6 concurrent subagents;
  - unnamed subagents default to Sonnet (frontmatter models still win).
- **Mod:** the context-meter mod shows context occupancy.
- **Agents:**
  - Opus `mx-*` reviewers are read-only.
  - Every `mx-*` agent carries the standing no-stub, no-hidden-failure and `Not verified:` rules.
- **Skills:** 20 never-used global skills unrelated to any active stack were moved to `skills.disabled/`.

Project settings (`.claude/settings.json`):

- the firebase and fallow plugins are disabled here;
- ponytail runs at `lite`;
- reading `.env` is denied.

Not verified: hook invocation counts/latency, duplicate capture, private-data
retention behavior, effective host settings or a plugin-enabled performance A/B.
