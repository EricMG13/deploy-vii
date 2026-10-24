"""The Product checks shards must cover tests/product exactly, with no gap or overlap."""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARD_LIST = ROOT / ".github" / "shards" / "product.txt"
SCRIPT = ROOT / ".github" / "scripts" / "shard_files.sh"


def listed() -> list[tuple[str, str]]:
    entries = []
    for line in SHARD_LIST.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            shard, path = line.split()
            entries.append((shard, path))
    return entries


def collectable() -> set[str]:
    base = ROOT / "tests" / "product"
    found = set(base.rglob("test_*.py")) | set(base.rglob("*_test.py"))
    return {p.relative_to(ROOT).as_posix() for p in found}


def test_every_test_file_is_in_exactly_one_shard() -> None:
    counts = Counter(path for _, path in listed())
    assert sorted(p for p, n in counts.items() if n > 1) == [], "file listed in two shards"
    assert sorted(collectable() - set(counts)) == [], "test file in no shard"
    assert sorted(set(counts) - collectable()) == [], "shard entry is not a test file"


def test_shard_union_equals_directory() -> None:
    names = sorted({shard for shard, _ in listed()})
    union: list[str] = []
    for name in names:
        out = subprocess.run(
            ["bash", str(SCRIPT), name], capture_output=True, text=True, check=True, cwd=ROOT
        ).stdout.split()
        union.extend(out)
    assert sorted(union) == sorted(collectable())


def test_unknown_shard_fails() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "shard-none"], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode != 0


def test_workflow_matrix_lists_every_shard() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    line = next(ln for ln in text.splitlines() if ln.strip().startswith("shard: ["))
    in_workflow = {s.strip() for s in line.split("[", 1)[1].rstrip("] ").split(",")}
    assert in_workflow == {shard for shard, _ in listed()}
