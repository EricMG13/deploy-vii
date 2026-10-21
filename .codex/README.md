# Codex development workers

Use the explicit `make codex-scaffold`, `make codex-feature`,
`make codex-sensitive`, `make codex-research` and `make codex-architect` targets.
They launch an interactive CLI with the selected model/effort; research and
architecture additionally request a read-only sandbox. Supply the scoped brief
in that session. These targets do not change the current desktop coordinator.

The installed Codex 0.163.0-alpha.10.2 CLI uses `--profile` to load
`$CODEX_HOME/<name>.config.toml`. A missing profile does not fail. Therefore the
older `[profiles.<name>]` project-TOML approach does not establish routing here.
This setup uses explicit native flags and does not install global profile files.
CLAUDE.md is the repository's only instruction file, so every target also passes
`project_doc_fallback_filenames=["CLAUDE.md"]` (not verified on this CLI build).
Keep checking native behavior when updating the CLI; a successful exit alone
does not prove the requested model/effort was selected.

See the [environment guide](../docs/development/environment.md) and
[model matrix](../docs/model-matrix.md). No custom Codex subagent is registered.
