#!/usr/bin/env python3
"""Run the local documentation quality gate used by ``make check-docs``."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE_VERSION_PATTERN = re.compile(r"v?(\d+)\.(\d+)\.(\d+)\s*")
VITE_MINIMUM_NODE_VERSION = (20, 19, 0)
VITE_MINIMUM_CURRENT_NODE_VERSION = (22, 12, 0)


def run(command: tuple[str, ...]) -> int:
    print("+ " + " ".join(command))
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def check_node_version() -> bool:
    """The editable package build needs the same Node major as docs CI."""
    node = shutil.which("node")
    if node is None:
        print("Node.js 22 is required for the docs gate; install Node.js 22 and retry.")
        return False
    result = subprocess.run((node, "--version"), check=False, capture_output=True, text=True)
    match = NODE_VERSION_PATTERN.fullmatch(result.stdout)
    version = tuple(map(int, match.groups())) if match is not None else None
    supported = version is not None and (
        (version[0] == 20 and version >= VITE_MINIMUM_NODE_VERSION)
        or (version[0] >= 22 and version >= VITE_MINIMUM_CURRENT_NODE_VERSION)
    )
    if result.returncode != 0 or not supported:
        version = result.stdout.strip() or result.stderr.strip() or "unknown"
        print(
            "The docs build needs Node.js ^20.19.0 or >=22.12.0, as required by the locked Vite version; "
            f"found {version}."
        )
        return False
    return True


def main() -> int:
    if not check_node_version():
        return 1
    commands = (
        ("uv", "sync", "--project", "docs/app", "--frozen", "--group", "dev"),
        ("uv", "run", "--project", "docs/app", "--no-sync", "pytest", "docs/app/tests", "-v"),
        (
            "uv",
            "run",
            "--project",
            "docs/app",
            "--no-sync",
            "python",
            "scripts/check_public_api.py",
            "--skip-lazy-import-check",
        ),
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
