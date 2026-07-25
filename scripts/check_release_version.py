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

Both accept an optional PEP 440 pre-release suffix in its canonical spelling
(`a1`/`b2`/`rc3` — e.g. `reflex-xy-v0.0.1a1`), which the version derivation
serializes verbatim; PyPI accepts pre-releases but does not serve them to
default `pip install`. Only the canonical spelling passes: `-alpha1`-style
tags would be *normalized* by the derivation (`0.0.1a1`) and so could never
match their own artifacts. A pre-release still needs its own dated changelog
entry — publishing to PyPI is publishing, alpha or not.

The tag must also be shaped like the selected package's release tag, which is
what its version derivation matches on; the docs-deploy CalVer tags
(2026.WW.N) match neither shape and trigger neither workflow, and each
package's tags fail the other package's gate. Dev/post/local shapes stay
rejected: dev versions are the *between*-tags marker and must stay
unpublishable.
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
    # optionally a canonical pre-release suffix (aN/bN/rcN), nothing else.
    tag_re: re.Pattern[str]
    tag_shape: str
    changelog: Path


# Canonical PEP 440 spellings only: the derivation would normalize `alpha1`
# to `a1`, so a non-canonical tag can never equal its own built version.
_RELEASE = r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?"
_SHAPE = "vX.Y.Z with an optional aN/bN/rcN pre-release suffix"

PACKAGES = {
    "xy": _Package(
        tag_re=re.compile(rf"^v(?P<version>{_RELEASE})$"),
        tag_shape=_SHAPE,
        changelog=ROOT / "CHANGELOG.md",
    ),
    "reflex-xy": _Package(
        tag_re=re.compile(rf"^reflex-xy-v(?P<version>{_RELEASE})$"),
        tag_shape=f"reflex-xy-{_SHAPE}",
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
    # A heading with a real date. The gate checks substance (this version has
    # dated notes), not heading style: both spellings used in this repo pass —
    # Keep-a-Changelog brackets (`## [0.0.2] — 2026-07-24`) and the plain
    # v-prefixed form v0.0.2 was actually documented with
    # (`## v0.0.2 - 2026-07-24`); em dash or hyphen either way.
    dated = re.compile(
        rf"^## (?:\[{re.escape(version)}\]|v?{re.escape(version)}) [—-] "
        rf"\d{{4}}-\d{{2}}-\d{{2}}\s*$",
        re.M,
    )
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
