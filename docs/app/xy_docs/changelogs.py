"""Package changelogs published on the XY documentation site.

XY and the ``reflex-xy`` adapter keep Keep-a-Changelog files beside the code
they describe, so the site publishes them as external documents: the repository
files remain the single source of truth and the docs gain one page per package,
matching how the main Reflex documentation surfaces its package changelogs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from reflex_site_shared.docs import ExternalDoc

from xy_docs.constants import REPO_ROOT

CHANGELOG_DIRECTORY = "changelog"


@dataclass(frozen=True, slots=True)
class ChangelogPackage:
    """One package changelog published on the documentation site.

    Args:
        package: Distribution name, used as the navigation label.
        source_path: Repository changelog the page is rendered from.
        virtual_name: Markdown filename inside the virtual changelog directory.
        route: Public route the virtual path resolves to.
        display_name: Product name used in the page title.
        description: Page description for search results and agent indexes.
    """

    package: str
    source_path: Path
    virtual_name: str
    route: str
    display_name: str
    description: str

    @property
    def title(self) -> str:
        """Return the canonical page title.

        Returns:
            The normalized changelog page title.
        """
        return f"{self.display_name} Changelog"

    @property
    def relative_path(self) -> Path:
        """Return the virtual path inside the documentation content tree.

        Returns:
            The Markdown path that determines the public route.
        """
        return Path(CHANGELOG_DIRECTORY) / self.virtual_name


CHANGELOG_PACKAGES = (
    ChangelogPackage(
        package="xy",
        source_path=REPO_ROOT / "CHANGELOG.md",
        virtual_name="index.md",
        route="/changelog/",
        display_name="XY",
        description="Every notable change to the XY charting engine, newest first.",
    ),
    ChangelogPackage(
        package="reflex-xy",
        source_path=REPO_ROOT / "python" / "reflex-xy" / "CHANGELOG.md",
        virtual_name="reflex-xy.md",
        route="/changelog/reflex-xy/",
        display_name="reflex-xy",
        description=("Every notable change to reflex-xy, the Reflex adapter for XY, newest first."),
    ),
)

CHANGELOG_LEAVES = tuple((changelog.package, changelog.route) for changelog in CHANGELOG_PACKAGES)


def normalize_changelog(source: str, title: str, description: str) -> str:
    """Give a repository changelog the frontmatter and heading a docs page needs.

    The published files open with a generic ``# Changelog`` heading and carry no
    metadata, so the canonical title replaces that heading and the description
    becomes frontmatter. Every other line is published unchanged.

    Args:
        source: Raw changelog Markdown.
        title: Canonical page title.
        description: Page description for search results and agent indexes.

    Returns:
        Documentation Markdown with frontmatter and a canonical heading.
    """
    lines = source.lstrip().splitlines()
    if lines and lines[0].startswith("# "):
        del lines[0]
    body = "\n".join(lines).strip("\n")
    frontmatter = f"---\ntitle: {json.dumps(title)}\ndescription: {json.dumps(description)}\n---"
    return f"{frontmatter}\n\n# {title}\n\n{body}\n"


def changelog_docs() -> tuple[ExternalDoc, ...]:
    """Return the changelog pages published from outside the docs tree.

    Returns:
        One external document per package changelog.
    """
    return tuple(
        ExternalDoc(
            source_path=changelog.source_path,
            relative_path=changelog.relative_path,
            source=normalize_changelog(
                changelog.source_path.read_text(encoding="utf-8"),
                changelog.title,
                changelog.description,
            ),
        )
        for changelog in CHANGELOG_PACKAGES
    )


__all__ = [
    "CHANGELOG_DIRECTORY",
    "CHANGELOG_LEAVES",
    "CHANGELOG_PACKAGES",
    "ChangelogPackage",
    "changelog_docs",
    "normalize_changelog",
]
