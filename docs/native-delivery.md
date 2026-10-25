# Native delivery: the packaged Copilot skill (M11, task 11.1)

One skill, `deploy-vii`, in `.github/skills/deploy-vii/` (`SKILL.md` plus three short files
in `references/`). It tells a GitHub Copilot host which `deploy-vii` commands to run, in
what order, and how to interrupt and resume. It holds no methodology (that is
`src/deploy_vii/methods/`) and copies no Deploy VI policy text. The product baseline is
the one in [architecture](architecture.md): a native skill plus Python helpers.

Status: the package exists and is checked offline. No behaviour on a real Copilot host is
accepted or claimed.

## Installing the skill

Format per the GitHub docs read on 24 October 2026 (the pages carry no date): a
directory holding `SKILL.md` with `name` (lowercase, hyphens, matching the directory),
`description`, optional `license` and optional `allowed-tools`.

- Repository scope: the folder is already at `.github/skills/deploy-vii/`.
- User scope: copy it to `~/.copilot/skills/deploy-vii/` (or `~/.agents/skills/`). The docs
  do not promise a personal skill is available to a cloud-agent run.
- Copilot CLI: `copilot skill add` (terminal) or `/skills add`; then `/skills reload`,
  `/skills list`, `/skills info deploy-vii`.
- Explicit invocation names the skill with a slash in the prompt ("Use the /deploy-vii
  skill ..."); automatic invocation matches the description.

The skill declares no `allowed-tools`, so the host asks before running shell commands.
Install with `uv sync --locked` and check with `deploy-vii doctor`; the skill does not install
anything. The repository has no `LICENSE` file, so the skill sets no
`license` field.

## Offline checks

`tests/devtools/test_skill_package.py` (collected by `make dev-check`) checks:

1. frontmatter parses (stdlib), `name` equals the directory, lowercase-hyphen, non-empty
   `description`;
2. `allowed-tools` is absent or excludes `shell` and `bash`;
3. every relative path the skill files reference exists;
4. every `deploy-vii ...` command in a fenced block parses with the real argparse parser
   (the parser is reached through `deploy_vii.__main__.main` and stopped before it
   executes anything), after placeholders such as `<ticket>` are replaced by dummies;
5. no `sk-or-`/`sk-ant-` string and no claim of host acceptance in the skill files.

These prove package shape and that the documented flags exist. They do not prove that the
commands work in order, that a host loads or follows the skill, or any resume behaviour.

## Remaining gaps

- The host's behaviour for `doctor`, `run`, derived delivery paths, `resume` and `report-open`
  has only offline checks; none is qualified on a real Copilot host.
- `deploy-vii live` dispatches to OpenRouter with a local credential, never the host's
  model, so nothing in the CLI dispatches the host's own models.
- Source scope differs from the runner: for CP-3 and CP-4 the runner sends only the sources
  their upstream selects and normalises omitted defaults before validating; the host reads
  the sources `step-instructions` lists (the same scope), and the module's own schema and
  validator govern the review it writes.
- `step-instructions` names each declared source by the original's hash under the pack
  directory (`originals/<sha256>`) and gives the byte length of the extracted text the runner
  would send, not the original's size (the journal does not keep the original). The host reads
  the original with its own tools; the runner's model reads the extracted spans.
- Host-written reviews are not checked by the runner's tool-loop rules (absence claims need
  a prior search, cited pages must have been read), which depend on a tool loop's record; the
  module validators run in full.
- Modules after CP-6 (CP-8, Portfolio Fit) do not exist yet, so the report holds only
  what the registry has.

## Not accepted offline

External blockers (need the real enterprise Copilot host; never claimed offline), from the
M11 native-delivery research of 24 October 2026:

- Org skills support and whether `.github/skills` loads.
- Whether `/skills info` shows it and description matching dispatches it.
- Shell permission prompts and the effect of `allowed-tools`.
- Tool-output and context limits (no numbers are documented).
- Interruption, resume and long-running behaviour on the host (process kill, session loss, reload).
- Backend injection blocking versus source-derived text.
- Where report files land on the host and whether the user can open them.

## Live checks still to do

- The final rehearsal through CP-0 to CP-6, including the Credit Snapshot.
- Interrupt and resume a host session and verify retained pending work.
- Confirm the report location and opening behaviour on the host.

Not verified: any live Copilot host behaviour; the GitHub docs pages are undated.
