from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.environment import SCHEMA_VERSION, collect_environment_metadata


def test_collect_environment_metadata_is_machine_readable(tmp_path: Path) -> None:
    def runner(command: Sequence[str], cwd: Path | None, timeout_s: float) -> str | None:
        del timeout_s
        command_tuple = tuple(command)
        if command_tuple == ("node", "--version"):
            return "v20.11.1"
        if command_tuple == ("rustc", "--version"):
            return "rustc 1.96.1"
        if command_tuple == ("cargo", "--version"):
            return "cargo 1.96.1"
        if command_tuple == ("/Applications/Chromium", "--version"):
            return "Chromium 126.0.0"
        if command_tuple == ("git", "rev-parse", "HEAD") and cwd == tmp_path:
            return "abc123"
        if command_tuple == ("git", "rev-parse", "--abbrev-ref", "HEAD") and cwd == tmp_path:
            return "main"
        if command_tuple == ("git", "status", "--porcelain") and cwd == tmp_path:
            return " M benchmarks/environment.py"
        return None

    metadata = collect_environment_metadata(
        chromium="/Applications/Chromium",
        package_names=("definitely-not-installed-fastcharts-test-package",),
        now=datetime(2026, 7, 4, 12, 0, tzinfo=UTC),
        root=tmp_path,
        command_runner=runner,
    )

    assert SCHEMA_VERSION == 2
    assert metadata["generated_at_utc"] == "2026-07-04T12:00:00Z"
    assert metadata["python"]["version"]
    assert metadata["platform"]["system"]
    assert metadata["cpu_count"] is None or metadata["cpu_count"] > 0
    assert metadata["package_versions"]["definitely-not-installed-fastcharts-test-package"] is None
    assert metadata["executables"] == {
        "node": "v20.11.1",
        "rustc": "rustc 1.96.1",
        "cargo": "cargo 1.96.1",
        "chromium": "Chromium 126.0.0",
    }
    assert metadata["git"] == {"commit": "abc123", "branch": "main", "dirty": True}
