"""Select PR checks from the complete git diff; unknown paths fail open to all checks."""

from __future__ import annotations

import argparse
import os
import subprocess

GROUPS = ("runtime", "pyplot", "packaging", "benchmarks", "conformance")


def select_checks(paths: list[str], *, full: bool = False) -> dict[str, bool]:
    selected = dict.fromkeys(GROUPS, full)
    for path in paths:
        if path.startswith(("docs/", "spec/", "news/")) or path in {
            "README.md",
            "CHANGELOG.md",
            "LICENSE",
            "CONTRIBUTING.md",
            "AGENTS.md",
        }:
            continue
        if path.startswith(
            (
                "python/xy/pyplot/",
                "python/xy/backends/",
                "tests/pyplot/",
                "tests/backends/",
                "scripts/pyplot_gallery/",
                "gallery/",
            )
        ) or path in {
            "scripts/generate_pyplot_compat_inventory.py",
            "scripts/sync_matplotlib_compat.py",
        }:
            selected["runtime"] = selected["pyplot"] = True
        elif path.startswith(("benchmarks/", "scripts/bench")):
            selected["benchmarks"] = True
        elif path.startswith(("tests/", "examples/")) or path.startswith(".binder/"):
            selected["runtime"] = True
        else:
            # Shared Python/Rust/JS, build configuration, CI and unfamiliar
            # paths can affect every consumer. Never silently omit their gates.
            selected = dict.fromkeys(GROUPS, True)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    paths = []
    if not args.full:
        if not args.base:
            parser.error("--base is required unless --full is set")
        diff = subprocess.check_output(
            ["git", "diff", "--name-only", "--no-renames", "-z", f"{args.base}...{args.head}"],
        )
        paths = diff.decode().rstrip("\0").split("\0") if diff else []
    selected = select_checks(paths, full=args.full)
    selected["build"] = any(selected.values())
    output = "".join(f"{key}={str(value).lower()}\n" for key, value in selected.items())
    print(output, end="")
    if destination := os.environ.get("GITHUB_OUTPUT"):
        with open(destination, "a") as stream:
            stream.write(output)


if __name__ == "__main__":
    main()
