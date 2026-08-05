#!/usr/bin/env python3
"""Run the local documentation quality gate used by ``make check-docs``."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: tuple[str, ...]) -> int:
    print("+ " + " ".join(command))
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main() -> int:
    commands = (
        ("uv", "run", "--project", "docs/app", "--no-sync", "pytest", "docs/app/tests", "-v"),
        (
            "uv",
            "run",
            "--project",
            "docs/app",
            "--no-sync",
            "python",
            "scripts/verify_docs_quickstart.py",
        ),
        (
            "uv",
            "run",
            "--project",
            "docs/app",
            "--no-sync",
            "pre-commit",
            "run",
            "ruff-format",
            "--all-files",
        ),
        (
            "uv",
            "run",
            "--project",
            "docs/app",
            "--no-sync",
            "pre-commit",
            "run",
            "ruff-check",
            "--all-files",
        ),
        (
            "uv",
            "run",
            "--project",
            "docs/app",
            "--no-sync",
            "pre-commit",
            "run",
            "docs-app-codespell",
            "--all-files",
        ),
    )
    for command in commands:
        rc = run(command)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
