#!/usr/bin/env python3
"""Release gate: the pushed tag and the package's CHANGELOG must agree.

The tag *is* the version now — each pyproject derives it via
uv-dynamic-versioning — so the old tag-vs-pyproject leg of this gate is gone
along with the drift it existed to catch. What a tag cannot vouch for is that
anyone wrote down what changed, so this runs first in the publish job on tag
pushes: the package's changelog must carry a dated entry for the tagged
version (an "unreleased" heading fails — date it as part of cutting the
release).

Two release lines share the repo, in disjoint tag namespaces (`--package`):

- ``xy`` (default): bare `vX.Y.Z` tags, gated against `CHANGELOG.md`.
- ``reflex-xy``: `reflex-xy-vX.Y.Z` tags, gated against
  `python/reflex-xy/CHANGELOG.md`.

The tag must also be shaped like the selected package's release tag, which is
what its version derivation matches on; the docs-deploy CalVer tags
(2026.WW.N) match neither shape and trigger neither workflow, and each
package's tags fail the other package's gate.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple, Optional

ROOT = Path(__file__).resolve().parents[1]


class _Package(NamedTuple):
    # The release tag shape uv-dynamic-versioning derives this package's
    # distribution version from: prefix + `v` + a PEP 440 release number,
    # nothing else.
    tag_re: re.Pattern[str]
    tag_shape: str
    changelog: Path


PACKAGES = {
    "xy": _Package(
        tag_re=re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$"),
        tag_shape="vX.Y.Z",
        changelog=ROOT / "CHANGELOG.md",
    ),
    "reflex-xy": _Package(
        tag_re=re.compile(r"^reflex-xy-v(?P<version>\d+\.\d+\.\d+)$"),
        tag_shape="reflex-xy-vX.Y.Z",
        changelog=ROOT / "python" / "reflex-xy" / "CHANGELOG.md",
    ),
}
DEFAULT_CHANGELOG = PACKAGES["xy"].changelog
# Backward-compatible alias for the pre-adapter, xy-only gate.
TAG_RE = PACKAGES["xy"].tag_re


def check_release(tag: str, changelog: Path, package: str = "xy") -> list[str]:
    errors: list[str] = []
    spec = PACKAGES[package]
    match = spec.tag_re.match(tag)
    if match is None:
        return [
            f"tag {tag!r} is not a release tag for {package} — expected "
            f"{spec.tag_shape!r}, the shape the distribution version is derived from"
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
            f"{changelog.name} has no dated '## [{version}]' entry — date the "
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
    parser.add_argument(
        "--package",
        choices=sorted(PACKAGES),
        default="xy",
        help="which release line the tag belongs to (default: xy)",
    )
    parser.add_argument(
        "--changelog",
        type=Path,
        default=None,
        help="changelog to gate against (defaults to the package's own)",
    )
    args = parser.parse_args(argv)

    if not args.tag:
        print("release version gate: no tag provided (--tag or GITHUB_REF_NAME)", file=sys.stderr)
        return 1
    changelog = args.changelog if args.changelog is not None else PACKAGES[args.package].changelog
    errors = check_release(args.tag, changelog, args.package)
    if errors:
        print("release version gate failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"release version gate OK: {args.tag} has a dated {changelog.name} entry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
