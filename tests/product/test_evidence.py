"""`evidence_path`: rendering evidence directories are unique per run, worker and test."""

from pathlib import Path

from tests.product.evidence import evidence_path

ROOT = Path("/tmp/pytest-of-someone")


def test_a_serial_and_a_parallel_run_get_distinct_paths_for_the_same_test() -> None:
    serial = evidence_path("shell", ROOT / "pytest-7" / "test_x0")
    parallel = evidence_path("shell", ROOT / "pytest-7" / "popen-gw2" / "test_x0")
    assert serial == Path("artifacts/rendering/shell/pytest-7/test_x0")
    assert parallel == Path("artifacts/rendering/shell/pytest-7/popen-gw2/test_x0")


def test_two_runs_on_the_same_worker_do_not_collide() -> None:
    first = evidence_path("shell", ROOT / "pytest-7" / "popen-gw2" / "test_x0")
    second = evidence_path("shell", ROOT / "pytest-8" / "popen-gw2" / "test_x0")
    assert first != second
