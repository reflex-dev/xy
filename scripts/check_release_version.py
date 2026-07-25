#!/usr/bin/env python3
"""Release gate: the pushed tag and the CHANGELOG must agree.

The tag *is* the version now — pyproject derives it via uv-dynamic-versioning —
so the old tag-vs-pyproject leg of this gate is gone along with the drift it
existed to catch. What a tag cannot vouch for is that anyone wrote down what
changed, so this runs first in the publish job on tag pushes: CHANGELOG.md must
carry a dated entry for the tagged version (an "unreleased" heading fails —
date it as part of cutting the release).

The tag must also be shaped like a release tag (`vX.Y.Z`), which is what the
version derivation matches on; the docs-deploy CalVer tags (2026.WW.N) neither
match it nor trigger this workflow.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = ROOT / "CHANGELOG.md"
# The release tag shape uv-dynamic-versioning derives the distribution version
# from: `v` + a PEP 440 release number, nothing else.
TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")


def check_release(tag: str, changelog: Path) -> list[str]:
    errors: list[str] = []
    match = TAG_RE.match(tag)
    if match is None:
        return [
            f"tag {tag!r} is not a release tag — expected 'vX.Y.Z', the shape the "
            "distribution version is derived from"
        ]
    version = match.group("version")
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
    parser.add_argument("--changelog", type=Path, default=DEFAULT_CHANGELOG)
    args = parser.parse_args(argv)

    if not args.tag:
        print("release version gate: no tag provided (--tag or GITHUB_REF_NAME)", file=sys.stderr)
        return 1
    errors = check_release(args.tag, args.changelog)
    if errors:
        print("release version gate failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"release version gate OK: {args.tag} has a dated CHANGELOG entry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
