#!/usr/bin/env python3
"""Keep the dependency-audit lockfile inventory explicit and complete."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDITED_LOCKFILES = frozenset(
    {
        "Cargo.lock",
        "examples/osm/osmium-rs/Cargo.lock",
        "package-lock.json",
        "uv.lock",
        "docs/app/uv.lock",
        "docs/app/reflex.lock/bun.lock",
        "benchmarks/requirements-ci.lock",
    }
)
FROZEN_EVIDENCE_LOCKFILES = frozenset(
    {
        "benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/uv.lock",
        "benchmarks/launch_baselines/xy-main-2026-07-26/macos-arm64-m5-pro/uv.lock",
    }
)
EXPECTED_LOCKFILES = AUDITED_LOCKFILES | FROZEN_EVIDENCE_LOCKFILES

LOCKFILE_NAMES = frozenset(
    {
        "bun.lock",
        "bun.lockb",
        "cargo.lock",
        "composer.lock",
        "flake.lock",
        "gemfile.lock",
        "go.sum",
        "gradle.lockfile",
        "npm-shrinkwrap.json",
        "package-lock.json",
        "package.resolved",
        "packages.lock.json",
        "pdm.lock",
        "pipfile.lock",
        "pixi.lock",
        "pnpm-lock.yaml",
        "podfile.lock",
        "poetry.lock",
        "uv.lock",
        "yarn.lock",
    }
)


def _is_lockfile(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in LOCKFILE_NAMES
        or (name.startswith("requirements") and name.endswith(".lock"))
        or (name.startswith("pylock") and name.endswith(".toml"))
    )


def find_dependency_lockfiles(root: Path = ROOT) -> frozenset[str]:
    """Return recognized dependency lockfiles committed to the checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("dependency lock inventory requires a git checkout and git") from exc
    return frozenset(
        path
        for raw_path in result.stdout.split(b"\0")
        if raw_path
        for path in (raw_path.decode("utf-8", "surrogateescape"),)
        if _is_lockfile(Path(path))
    )


def main() -> int:
    try:
        actual = find_dependency_lockfiles()
    except RuntimeError as exc:
        print(f"dependency lockfile inventory failed: {exc}", file=sys.stderr)
        return 1
    missing = sorted(EXPECTED_LOCKFILES - actual)
    unexpected = sorted(actual - EXPECTED_LOCKFILES)
    if missing or unexpected:
        if missing:
            print(f"missing expected dependency lockfiles: {missing}", file=sys.stderr)
        if unexpected:
            print(
                f"dependency lockfiles missing from the audit inventory: {unexpected}",
                file=sys.stderr,
            )
        return 1
    print(
        "dependency lockfile inventory OK "
        f"({len(AUDITED_LOCKFILES)} audited, "
        f"{len(FROZEN_EVIDENCE_LOCKFILES)} frozen evidence)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
