#!/usr/bin/env python3
"""Release gate: the pushed tag must be a shape the version derivation accepts.

The tag *is* the version now — each pyproject derives it via
uv-dynamic-versioning — so the old tag-vs-pyproject leg of this gate is gone
along with the drift it existed to catch. What remains is the one thing a tag
can still get wrong on its own: a shape the derivation cannot turn into the
version the artifacts are published under. This runs first in the publish job
on tag pushes.

Writing up the release in `CHANGELOG.md` is a checklist item
(`spec/process/production-readiness.md`), deliberately not a gate: a missing or
undated entry is fixed with a commit, and blocking the publish on it only ever
forced a tag to be deleted and re-cut for a documentation edit.

The ``xy`` distribution uses bare `vX.Y.Z` tags. Its bundled Reflex integration
and `reflex` extra ship on the same version line.

Tags accept an optional PEP 440 pre-release suffix in its canonical spelling
(`a1`/`b2`/`rc3`). PyPI accepts pre-releases but does not serve them to default
`pip install`. Only the canonical spelling passes: `-alpha1`-style tags would
be normalized by the derivation (`0.0.1a1`) and could never match their own
artifacts.

Docs-deploy CalVer tags (2026.WW.N) do not match the release shape.
Dev/post/local shapes stay rejected: dev versions are the between-tags marker
and must stay unpublishable.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import NamedTuple, Optional


class _Package(NamedTuple):
    # The release tag shape uv-dynamic-versioning derives this package's
    # distribution version from: prefix + `v` + a PEP 440 release number,
    # optionally a canonical pre-release suffix (aN/bN/rcN), nothing else.
    tag_re: re.Pattern[str]
    tag_shape: str


# Canonical PEP 440 spellings only: the derivation would normalize `alpha1`
# to `a1`, so a non-canonical tag can never equal its own built version.
_RELEASE = r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?"
_SHAPE = "vX.Y.Z with an optional aN/bN/rcN pre-release suffix"

PACKAGES = {
    "xy": _Package(
        tag_re=re.compile(rf"^v(?P<version>{_RELEASE})$"),
        tag_shape=_SHAPE,
    ),
}
# Backward-compatible alias for the pre-adapter, xy-only gate.
TAG_RE = PACKAGES["xy"].tag_re


def check_release(tag: str, package: str = "xy") -> list[str]:
    spec = PACKAGES[package]
    if spec.tag_re.match(tag) is None:
        return [
            f"tag {tag!r} is not a release tag for {package} — expected "
            f"{spec.tag_shape!r}, the shape the distribution version is derived from"
        ]
    return []


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        default=os.environ.get("GITHUB_REF_NAME", ""),
        help="release tag (defaults to $GITHUB_REF_NAME)",
    )
    parser.add_argument(
        "--package",
        choices=sorted(PACKAGES),
        default="xy",
        help="which release line the tag belongs to (default: xy)",
    )
    args = parser.parse_args(argv)

    if not args.tag:
        print("release version gate: no tag provided (--tag or GITHUB_REF_NAME)", file=sys.stderr)
        return 1
    errors = check_release(args.tag, args.package)
    if errors:
        print("release version gate failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"release version gate OK: {args.tag} is a release tag for {args.package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
