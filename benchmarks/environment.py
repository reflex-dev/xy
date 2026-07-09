"""Shared benchmark environment metadata.

Performance numbers are only useful when the machine, Python/runtime versions,
and source revision are attached to the artifact that carries the numbers. This
module is stdlib-only so every benchmark harness can use it, including the
dependency-light native probes.
"""

from __future__ import annotations

import os
import platform
import subprocess
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKAGE_NAMES = (
    "fastcharts",
    "numpy",
    "plotly",
    "matplotlib",
    "seaborn",
    "bokeh",
    "altair",
    "datashader",
    "holoviews",
    "hvplot",
    "pandas",
    "psutil",
    "kaleido",
)

CommandRunner = Callable[[Sequence[str], Path | None, float], str | None]


def collect_environment_metadata(
    *,
    chromium: str | None = None,
    fastcharts_backend: str | None = None,
    package_names: Iterable[str] = DEFAULT_PACKAGE_NAMES,
    now: datetime | None = None,
    root: Path = ROOT,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Return machine-readable context for a benchmark run.

    Missing tools or packages are reported as ``None`` instead of raising. The
    benchmark result should still be saved even on stripped-down CI runners.
    """

    generated_at = now or datetime.now(UTC)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)

    executables = {
        "node": _run_text(("node", "--version"), runner=command_runner),
        "rustc": _run_text(("rustc", "--version"), runner=command_runner),
        "cargo": _run_text(("cargo", "--version"), runner=command_runner),
    }
    if chromium:
        executables["chromium"] = _run_text((chromium, "--version"), runner=command_runner)

    return {
        "generated_at_utc": generated_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "compiler": platform.python_compiler(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "cpu_count": os.cpu_count(),
        "package_versions": _package_versions(package_names),
        "executables": executables,
        "fastcharts_backend": fastcharts_backend or _fastcharts_backend(),
        "browser_renderer": (
            "hardware" if os.environ.get("FASTCHARTS_BENCH_HARDWARE_GL") == "1" else "software-gl"
        ),
        "git": _git_metadata(root, command_runner),
    }


def _package_versions(package_names: Iterable[str]) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package_name in package_names:
        try:
            versions[package_name] = importlib_metadata.version(package_name)
        except importlib_metadata.PackageNotFoundError:
            versions[package_name] = None
    return versions


def _fastcharts_backend() -> str | None:
    try:
        import fastcharts.kernels as kernels
    except Exception:
        return None
    return str(getattr(kernels, "BACKEND", None))


def _git_metadata(root: Path, runner: CommandRunner | None) -> dict[str, Any]:
    commit = _run_text(("git", "rev-parse", "HEAD"), cwd=root, runner=runner)
    branch = _run_text(("git", "rev-parse", "--abbrev-ref", "HEAD"), cwd=root, runner=runner)
    dirty_text = _run_text(("git", "status", "--porcelain"), cwd=root, runner=runner)
    return {
        "commit": commit,
        "branch": branch,
        "dirty": None if dirty_text is None else bool(dirty_text.strip()),
    }


def _run_text(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout_s: float = 2.0,
    runner: CommandRunner | None = None,
) -> str | None:
    if runner is not None:
        return runner(command, cwd, timeout_s)
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    text = completed.stdout.strip()
    if not text:
        text = completed.stderr.strip()
    return text.splitlines()[0] if text else None
