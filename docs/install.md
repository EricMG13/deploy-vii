# Install and run locally

Clone the repository, install the locked runtime with Python 3.13 and uv 0.12.5, then check it:

```sh
uv sync --locked
uv run --locked deploy-vii doctor
```

The doctor is network-free. It checks the active Python, lock-file presence, runtime imports,
the CP-0 plan, packaged skill, optional request/input files and delivery-root writability. It
does not resolve or compare the lock; use `uv lock --check` for that. Git may be needed for some
source provenance operations, but the installed CLI does not require Git at runtime.
Wheel installs use distribution metadata for the Python check and report lock-file and packaged
skill-location checks as skipped because those source-tree files are not in the wheel.

The default delivery root is `./deploy-vii-out`. Set `DEPLOY_VII_OUT` or put `--out <directory>`
before the CLI command to choose another root. `--run <id>` derives `pack`, `journal`, `reviews`
and `report` paths beneath it. Run ids may contain letters, digits, dot, underscore and hyphen.
Existing explicit path options take precedence.

The repository skill is `.github/skills/deploy-vii/`; copy it to
`~/.copilot/skills/deploy-vii/` for user scope. Cloud-host availability is not promised. The
`live` command is development-only and calls OpenRouter when explicitly run. `textutil` is
macOS-only and ordinary runtime does not require it. Do not run live checks during the project
pause.

To uninstall, remove the checkout and virtual environment. Retain needed packs, journals,
reviews and reports before removing the delivery root; the CLI does not clean it automatically.

## Platform parity

`make linux-parity` reproduces the hosted Linux recipe locally with Docker. It is not a CI job.
See [CI gates](ci-gates.md#linux-parity-local-only).
