"""Rendering evidence paths that stay unique under pytest-xdist (decision 0011).

Serial, a test's `tmp_path` is `<root>/pytest-<run>/<test>`; under xdist it is
`<root>/pytest-<run>/popen-gw<worker>/<test>`. Naming evidence by only the parent directory
repeated `popen-gw<worker>` on every run, so a second run met the first run's directory.
"""

from pathlib import Path

RENDERING = Path("artifacts/rendering")


def evidence_path(group: str, tmp_path: Path) -> Path:
    """`artifacts/rendering/<group>/` plus every directory of `tmp_path` below the pytest root
    (`pytest-of-<user>`): the run number, the worker when parallel, and the test."""
    names: list[str] = []
    for directory in (tmp_path, *tmp_path.parents):
        if directory.parent.name.startswith("pytest-of-") or directory == directory.parent:
            names.append(directory.name)
            break
        names.append(directory.name)
    return RENDERING.joinpath(group, *reversed(names))
