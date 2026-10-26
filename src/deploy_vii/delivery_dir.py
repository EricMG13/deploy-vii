"""Safe paths for files owned by a single local delivery run."""

import os
import re
from pathlib import Path

RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


def delivery_root(out: Path | None = None) -> Path:
    return (
        (out or Path(os.environ.get("DEPLOY_VII_OUT", "./deploy-vii-out"))).expanduser().resolve()
    )


def run_paths(out: Path | None, run_id: str) -> dict[str, Path]:
    if not RUN_ID.fullmatch(run_id) or run_id in {".", ".."}:
        raise ValueError("run id must contain only letters, digits, dot, underscore or hyphen")
    root = delivery_root(out)
    run = root / run_id
    paths = {name: run / name for name in ("pack", "journal", "reviews", "report")}
    for path in (run, *paths.values()):
        if path.is_symlink():
            raise ValueError(f"delivery run path must not be a symlink: {path}")
    return paths
