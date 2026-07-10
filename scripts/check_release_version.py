#!/usr/bin/env python3
"""Release gate: the pushed tag, pyproject version, and CHANGELOG must agree.

The wheel/sdist verifiers check everything *inside* the artifacts, but nothing
else stops `git tag v0.2.0` from publishing whatever version happens to sit in
pyproject.toml under a mismatched tag. This runs first in the publish job on
tag pushes: the tag must equal `v` + the pyproject version, and CHANGELOG.md
must carry a dated entry for that version (an "unreleased" heading fails —
date it as part of cutting the release).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYPROJECT = ROOT / "pyproject.toml"
DEFAULT_CHANGELOG = ROOT / "CHANGELOG.md"


def check_release(tag: str, pyproject: Path, changelog: Path) -> list[str]:
    errors: list[str] = []
    try:
        version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, tomllib.TOMLDecodeError, KeyError) as exc:
        return [f"cannot read project version from {pyproject}: {exc}"]
    if tag != f"v{version}":
        errors.append(
            f"tag {tag!r} does not match pyproject version {version!r} (expected 'v{version}')"
        )
    try:
        text = changelog.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read {changelog}: {exc}")
        return errors
    # Keep-a-Changelog heading with a real date (this repo separates with an
    # em dash; accept a plain hyphen too): `## [X.Y.Z] — 2026-07-09`.
    dated = re.compile(rf"^## \[{re.escape(version)}\] [—-] \d{{4}}-\d{{2}}-\d{{2}}\s*$", re.M)
    if not dated.search(text):
        errors.append(
            f"CHANGELOG.md has no dated '## [{version}]' entry — date the "
            "release section before tagging"
        )
    return errors


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        default=os.environ.get("GITHUB_REF_NAME", ""),
        help="release tag (defaults to $GITHUB_REF_NAME)",
    )
    parser.add_argument("--pyproject", type=Path, default=DEFAULT_PYPROJECT)
    parser.add_argument("--changelog", type=Path, default=DEFAULT_CHANGELOG)
    args = parser.parse_args(argv)

    if not args.tag:
        print("release version gate: no tag provided (--tag or GITHUB_REF_NAME)", file=sys.stderr)
        return 1
    errors = check_release(args.tag, args.pyproject, args.changelog)
    if errors:
        print("release version gate failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"release version gate OK: {args.tag} matches pyproject and CHANGELOG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
