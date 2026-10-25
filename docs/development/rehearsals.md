# Skill rehearsals (`proxy-claude` cohort)

Real-world testing happens in the enterprise Copilot host, whose agent reads
`.github/skills/deploy-vii/SKILL.md`, writes each step's review file and runs the `deploy-vii`
CLI. The only proof available here is a rehearsal: a stand-in agent follows SKILL.md literally
against the real CLI on the real Caesars pack while `devtools/skill_rehearsal.py` records every
command, exit code, issue line, the rendered report and the cost. Cap: US$12 per rehearsal,
counted against the US$200 ceiling of decision 0006 DC-6.

## Cohort wording (decision 0006 DC-8)

The stand-in agent is `proxy-claude`, a labelled cohort. Its results are never pooled with the
Sol pool of decision 0005 and are never reported as a model-quality result: they show that the
skill, the CLI and the retained journal work end to end, not how any host model behaves. A
rehearsal directory records `cohort: "proxy-claude"` and `pooled: false`; the harness refuses a
directory that holds another cohort.

## How a rehearsal is run

1. Pick the directory: `artifacts/model-tests/rehearsals/<utc-stamp>/` (git-ignored, retained,
   never committed; the harness creates it on the first `run`).
2. Give the stand-in agent SKILL.md itself plus these instructions:
   - Run every `deploy-vii` command as
     `python -m devtools.skill_rehearsal run --rehearsal <dir> -- <deploy-vii args>`. The
     harness runs `python -m deploy_vii <args>` (an argument list, never a shell string), passes
     stdout and stderr through unchanged and exits with the command's exit code.
   - Exercise exactly one interruption: on one long step run the command with
     `--interrupt-after <seconds>` (before `--`), then follow `references/resume.md` and run the
     same command again. The harness records both runs; the first line carries
     `interrupted: true`. This harness SIGINT stops a running command from outside; it is not
     the CLI's `execution interrupt` command, which settles a pending attempt by ticket and
     reason (the next `begin` is then the repair).
   - When the run ends, report the stand-in agent's token usage and run
     `python -m devtools.skill_rehearsal cost --rehearsal <dir> --model <id> --input-tokens N --output-tokens N --usd-per-m-input X --usd-per-m-output Y --price-source "<where the prices came from>" --final`.
     Earlier calls without `--final` add partial usage reports. The first call reserves the
     US$12 cap in `<dir>/ledger.jsonl`; `--final` settles the total as an estimate at list prices.
     A total above the cap exits 3 with the figures and records nothing.
3. The coordinator runs
   `python -m devtools.skill_rehearsal summary --rehearsal <dir> --journal <journal-dir> --report <report-dir>`.

## What lands in the directory

| File | Content |
| :--- | :--- |
| `rehearsal.json` | start time, cohort, `pooled: false`, provider, cap |
| `commands.jsonl` | one line per command: `seq`, `utc`, `argv`, `exit_code`, `duration_s`, `stdout_sha256`, `stderr_sha256`, `issues`, and `interrupted` when the harness sent SIGINT |
| `cmd-NNN.out`, `cmd-NNN.err` | the command's stdout and stderr, byte for byte |
| `usage.jsonl`, `ledger.jsonl` | the reported usage, and the capped ledger (`Ledger`, provider `anthropic`) |
| `summary.md` | the acceptance check below |

`issues` is the attempt JSON's issue list as the CLI's own `issue_lines` reads it: the attempt's
`issues`, else those of the rejected step of a still-pending attempt. Note that `cp0-submit` and
`cp1-submit` print a rejected attempt and exit 0; only `module-submit` exits 1 on issues, so the
summary lists every command whose output carries issues, whatever its exit code.

## Acceptance (M11)

The summary exits 0 and prints `Result: ACCEPTED` when every in-scope module is settled
(accepted or restricted, none pending), no failed command is left without a later success of the
same argv, every interruption was resumed, and a given `--report` directory holds `index.html`.
M11 is met by a rehearsal that settles CP-0 to CP-6, renders a Credit Snapshot and survives its
one interruption. The summary reads the journal through `Execution(...).view()` only; it never
writes it.

## Not shown by this rehearsal

Host skill loading, host permission prompts, host model behaviour and the report's location on
the host. The summary prints this list verbatim.
