#!/usr/bin/env python3
"""Keep the dependency-audit lockfile inventory explicit and complete."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_LOCKFILES = frozenset(
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
EXCLUDED_PATH_PARTS = frozenset({"launch_baselines"})


def _is_lockfile(path: Path) -> bool:
    return path.name in {"Cargo.lock", "package-lock.json", "bun.lock", "uv.lock"} or (
        path.name.startswith("requirements") and path.name.endswith(".lock")
    )


def find_dependency_lockfiles(root: Path = ROOT) -> frozenset[str]:
    """Return committed dependency lockfiles, excluding local generated files."""
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
        if not any(part in EXCLUDED_PATH_PARTS for part in Path(path).parts)
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
                "dependency lockfiles missing from the audit inventory: "
                f"{unexpected}",
                file=sys.stderr,
            )
        return 1
    print(f"dependency lockfile inventory OK ({len(actual)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
