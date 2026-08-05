#!/usr/bin/env python3
"""Keep the dependency-audit lockfile inventory explicit and complete."""

from __future__ import annotations

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
EXCLUDED_DIRECTORIES = frozenset({".git", ".venv", "node_modules", "target", "launch_baselines"})


def _is_lockfile(path: Path) -> bool:
    return path.name in {"Cargo.lock", "package-lock.json", "bun.lock", "uv.lock"} or (
        path.name.startswith("requirements") and path.name.endswith(".lock")
    )


def find_dependency_lockfiles(root: Path = ROOT) -> frozenset[str]:
    """Return tracked dependency lockfiles, excluding generated environments."""
    paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and _is_lockfile(path)
        and not any(part in EXCLUDED_DIRECTORIES for part in path.relative_to(root).parts)
    }
    return frozenset(paths)


def main() -> int:
    actual = find_dependency_lockfiles()
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
