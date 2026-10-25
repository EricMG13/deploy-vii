"""Record a stand-in agent's rehearsal of the Deploy VII skill through the real CLI.

Run with `python -m devtools.skill_rehearsal`. The `proxy-claude` cohort (decision 0006 DC-8)
follows `.github/skills/deploy-vii/SKILL.md` literally; every `deploy-vii` command goes through
`run`, which logs argv, exit code, issue lines and stream hashes. `cost` keeps the capped ledger
and `summary` writes the acceptance check. See docs/development/rehearsals.md.
"""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

COHORT = "proxy-claude"
PROVIDER = "anthropic"
CAP_USD = "12"
STAMP = "%Y-%m-%dT%H:%M:%SZ"


class RehearsalError(Exception):
    """The rehearsal directory or an input is unusable; reported, never swallowed."""


def utc_now() -> str:
    return datetime.now(UTC).strftime(STAMP)


def open_rehearsal(directory: Path, *, create: bool) -> None:
    """Create the directory and its start record on first use; refuse another cohort's."""
    record = directory / "rehearsal.json"
    if record.exists():
        try:
            held = json.loads(record.read_text(encoding="utf-8"))
        except ValueError as bad:
            raise RehearsalError(f"{record} is not valid JSON") from bad
        if not isinstance(held, dict) or held.get("cohort") != COHORT:
            found = held.get("cohort") if isinstance(held, dict) else None
            raise RehearsalError(
                f"{directory} holds cohort {found}, not {COHORT}; "
                "a rehearsal directory is never shared between cohorts"
            )
        return
    if not create:
        raise RehearsalError(f"{directory} is not a rehearsal directory (no rehearsal.json)")
    directory.mkdir(parents=True, exist_ok=True)
    start = {
        "started_utc": utc_now(),
        "cohort": COHORT,
        "pooled": False,
        "provider": PROVIDER,
        "cap_usd": CAP_USD,
    }
    record.write_text(json.dumps(start, indent=2) + "\n", encoding="utf-8")


def _issue_strings(value: object) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def extract_issues(stdout: bytes) -> list[str]:
    """The attempt JSON's issue lines, as the CLI's own `issue_lines` reads them: the attempt's
    `issues`, else those of the rejected step (or the repaired step still waiting) of a pending
    attempt. Output that is not an attempt record gives `[]`."""
    try:
        attempt = json.loads(stdout)
    except ValueError:
        return []
    if not isinstance(attempt, dict):
        return []
    own = _issue_strings(attempt.get("issues"))
    if own is None:
        return []
    if own or attempt.get("status") != "pending":
        return own
    steps = [s for s in attempt.get("steps") or [] if isinstance(s, dict)]
    invalid = [s for s in steps if s.get("status") == "invalid"]
    if invalid:
        return _issue_strings(invalid[-1].get("issues")) or []
    valid = {s.get("step_id") for s in steps if s.get("status") == "valid"}
    repairs = [s for s in attempt.get("step_repairs") or [] if isinstance(s, dict)]
    waiting = [s for s in repairs if s.get("step_id") not in valid]
    return (_issue_strings(waiting[-1].get("issues")) or []) if waiting else []


def _tee(source: BinaryIO, sink: BinaryIO, kept: bytearray) -> None:
    while chunk := source.read1(65536):  # type: ignore[attr-defined]
        kept.extend(chunk)
        sink.write(chunk)
        sink.flush()


def _next_seq(directory: Path) -> int:
    log = directory / "commands.jsonl"
    if not log.exists():
        return 1
    return len(log.read_text(encoding="utf-8").splitlines()) + 1


def run_command(directory: Path, argv: list[str], interrupt_after: float | None = None) -> int:
    """Run `argv` (never through a shell), tee its streams, log one line, return its exit code.

    A child ended by a signal reports the shell convention 128 + signal. With `interrupt_after`
    the child gets SIGINT after that many seconds (the rehearsal's one interruption)."""
    open_rehearsal(directory, create=True)
    seq = _next_seq(directory)
    out, err = bytearray(), bytearray()
    started = time.monotonic()
    utc = utc_now()
    process = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert process.stdout is not None and process.stderr is not None
    readers = [
        threading.Thread(target=_tee, args=(process.stdout, sys.stdout.buffer, out)),
        threading.Thread(target=_tee, args=(process.stderr, sys.stderr.buffer, err)),
    ]
    for reader in readers:
        reader.start()
    interrupted = False
    timer: threading.Timer | None = None
    if interrupt_after is not None:

        def fire() -> None:
            nonlocal interrupted
            if process.poll() is None:
                interrupted = True
                process.send_signal(signal.SIGINT)

        timer = threading.Timer(interrupt_after, fire)
        timer.start()
    status = process.wait()
    if timer is not None:
        timer.cancel()
        timer.join()
    for reader in readers:
        reader.join()
    code = 128 - status if status < 0 else status
    entry: dict[str, Any] = {
        "seq": seq,
        "utc": utc,
        "argv": argv,
        "exit_code": code,
        "duration_s": round(time.monotonic() - started, 3),
        "stdout_sha256": hashlib.sha256(out).hexdigest(),
        "stderr_sha256": hashlib.sha256(err).hexdigest(),
        "issues": extract_issues(bytes(out)),
    }
    if interrupted:
        entry["interrupted"] = True
    (directory / f"cmd-{seq:03d}.out").write_bytes(out)
    (directory / f"cmd-{seq:03d}.err").write_bytes(err)
    with (directory / "commands.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry) + "\n")
        log.flush()
        os.fsync(log.fileno())
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one deploy-vii command and log it")
    run.add_argument("--rehearsal", type=Path, required=True)
    run.add_argument("--interrupt-after", type=float, metavar="SECONDS")
    run.add_argument("deploy_vii", nargs="*", help="after `--`: the deploy-vii arguments")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            command = list(args.deploy_vii)
            if not command:
                parser.error("run needs the deploy-vii arguments after `--`")
            return run_command(
                args.rehearsal,
                [sys.executable, "-m", "deploy_vii", *command],
                args.interrupt_after,
            )
    except RehearsalError as refused:
        print(f"skill_rehearsal refused: {refused}", file=sys.stderr)
        return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
