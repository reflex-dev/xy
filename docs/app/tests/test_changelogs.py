"""Tests for the package changelogs published on the documentation site."""

from pathlib import Path

import pytest
from reflex_site_shared.docs import DocsPage, discover_docs
from reflex_site_shared.docs.markdown import get_markdown_toc
from xy_docs.changelogs import (
    CHANGELOG_LEAVES,
    CHANGELOG_PACKAGES,
    changelog_docs,
    normalize_changelog,
)
from xy_docs.config import DOCS_CONFIG, DOCS_NAVIGATION, DOCS_REDIRECTS, DOCS_SECTIONS
from xy_docs.constants import REPO_ROOT, REPOSITORY_URL
from xy_docs.footer import xy_docs_footer
from xy_docs.markdown import render_xy_markdown_page
from xy_docs.plugins import build_llms_txt, markdown_asset_path
from xy_docs.prerender import XyDocsMarkdownPlugin
from xy_docs.sidebar import xy_docs_sidebar_comp
from xy_docs.xy_docs import _release_headings_only


@pytest.fixture(scope="module")
def changelog_pages() -> dict[str, DocsPage]:
    """Return the published changelog pages by route.

    Returns:
        Discovered changelog pages keyed by public route.
    """
    return {
        page.route: page
        for page in discover_docs(DOCS_CONFIG)
        if page.route.startswith("/changelog/")
    }


def test_changelog_sources_are_the_repository_changelogs() -> None:
    """Publish the maintained files instead of a copy inside the docs tree."""
    assert [changelog.source_path for changelog in CHANGELOG_PACKAGES] == [
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "python" / "reflex-xy" / "CHANGELOG.md",
    ]
    assert all(changelog.source_path.is_file() for changelog in CHANGELOG_PACKAGES)
    assert [changelog.relative_path for changelog in CHANGELOG_PACKAGES] == [
        Path("changelog") / "index.md",
        Path("changelog") / "reflex-xy.md",
    ]


def test_normalize_changelog_replaces_the_generic_heading() -> None:
    """Give each changelog canonical frontmatter and a package-specific title."""
    source = "# Changelog\n\n## [0.0.3] - 2026-07-24\n\n### Fixed\n\n- A change.\n"

    normalized = normalize_changelog(source, "XY Changelog", "Release notes.")

    assert normalized == (
        '---\ntitle: "XY Changelog"\ndescription: "Release notes."\n---\n\n'
        "# XY Changelog\n\n## [0.0.3] - 2026-07-24\n\n### Fixed\n\n- A change.\n"
    )


def test_normalize_changelog_keeps_bodies_without_a_heading() -> None:
    """A changelog that opens with content keeps every authored line."""
    normalized = normalize_changelog(
        "## [0.0.3] - 2026-07-24\n\n- A change.\n",
        "XY Changelog",
        "Release notes.",
    )

    assert normalized.endswith("# XY Changelog\n\n## [0.0.3] - 2026-07-24\n\n- A change.\n")


def test_changelog_docs_render_from_the_repository_files() -> None:
    """Each external document publishes its normalized repository changelog."""
    external_docs = changelog_docs()

    assert len(external_docs) == len(CHANGELOG_PACKAGES)
    for external_doc, changelog in zip(external_docs, CHANGELOG_PACKAGES, strict=True):
        raw = changelog.source_path.read_text(encoding="utf-8")
        assert external_doc.source_path == changelog.source_path
        assert external_doc.read_source() == normalize_changelog(
            raw,
            changelog.title,
            changelog.description,
        )
        body = raw.lstrip().removeprefix("# Changelog\n").strip()
        assert body in external_doc.read_source()


def test_changelog_pages_are_published_with_canonical_metadata(
    changelog_pages: dict[str, DocsPage],
) -> None:
    """Both packages get a documentation page with a title and description."""
    assert list(changelog_pages) == [changelog.route for changelog in CHANGELOG_PACKAGES]
    for changelog in CHANGELOG_PACKAGES:
        page = changelog_pages[changelog.route]
        assert page.title == changelog.title
        assert page.description == changelog.description
        assert page.content.startswith(f"# {changelog.title}\n")
        assert page.source_path == changelog.source_path
        assert "## [Unreleased]" in page.content


def test_changelog_pages_render_their_release_history(
    changelog_pages: dict[str, DocsPage],
) -> None:
    """Render the changelog Markdown as ordinary documentation content."""
    for changelog in CHANGELOG_PACKAGES:
        rendered = str(render_xy_markdown_page(changelog_pages[changelog.route]))
        assert changelog.title in rendered
        assert "Unreleased" in rendered


def test_changelog_table_of_contents_lists_releases_only(
    changelog_pages: dict[str, DocsPage],
) -> None:
    """Keep repeated Added/Fixed/Changed subsections out of "On this page"."""
    page = changelog_pages["/changelog/"]
    headings = get_markdown_toc(_release_headings_only(page).content)

    assert [level for level, _text in headings] == [1, *([2] * (len(headings) - 1))]
    assert (2, "[Unreleased]") in headings
    assert (3, "Added") in get_markdown_toc(page.content)

    authored = next(
        other for other in discover_docs(DOCS_CONFIG) if other.route == "/api-reference/"
    )
    assert _release_headings_only(authored) is authored


def test_changelog_navigation_lists_every_package() -> None:
    """The sidebar section mirrors the packages, ordered with XY first."""
    assert CHANGELOG_LEAVES == (("xy", "/changelog/"), ("reflex-xy", "/changelog/reflex-xy/"))
    section = next(
        (title, landing_route, leaves)
        for title, landing_route, _icon, leaves in DOCS_SECTIONS
        if title == "Changelog"
    )
    assert section == ("Changelog", "/changelog/", CHANGELOG_LEAVES)
    assert DOCS_NAVIGATION[-3:-1] == ("/changelog/", "/changelog/reflex-xy/")

    rendered = str(xy_docs_sidebar_comp._definition.component)
    for label, route in CHANGELOG_LEAVES:
        assert label in rendered
        assert route in rendered


def test_legacy_changelog_route_redirects_to_the_published_history() -> None:
    """Keep the retired API reference page pointing at the real changelog."""
    assert DOCS_REDIRECTS["/api-reference/changelog/"] == "/changelog/"
    assert not (REPO_ROOT / "docs" / "api-reference" / "changelog.md").exists()


def test_changelog_markdown_assets_publish_the_normalized_source(
    changelog_pages: dict[str, DocsPage],
) -> None:
    """Agent-readable Markdown carries the canonical title, not the raw file."""
    published = dict(XyDocsMarkdownPlugin(docs=DOCS_CONFIG).get_static_assets())
    for changelog in CHANGELOG_PACKAGES:
        page = changelog_pages[changelog.route]
        asset = markdown_asset_path(page)
        content = next(
            content for path, content in published.items() if path.as_posix().endswith(asset)
        )
        assert f'title: "{changelog.title}"' in content
        assert f"# {changelog.title}" in content

    assert markdown_asset_path(changelog_pages["/changelog/"]) == "changelog/index.md"
    assert markdown_asset_path(changelog_pages["/changelog/reflex-xy/"]) == "changelog/reflex-xy.md"


def test_llms_txt_indexes_the_changelog_section(
    changelog_pages: dict[str, DocsPage],
) -> None:
    """Agents discover both changelogs under their own index section."""
    content = build_llms_txt(DOCS_CONFIG)

    section = content.split("### Changelog\n", maxsplit=1)[1]
    for changelog in CHANGELOG_PACKAGES:
        page = changelog_pages[changelog.route]
        assert f"[{changelog.title}]" in section
        assert markdown_asset_path(page) in section


def test_changelog_footer_edits_the_repository_file(
    changelog_pages: dict[str, DocsPage],
) -> None:
    """Edit links follow the maintained file, not the virtual docs path."""
    rendered = str(xy_docs_footer(changelog_pages["/changelog/reflex-xy/"]))
    assert f"{REPOSITORY_URL}/blob/main/python/reflex-xy/CHANGELOG.md" in rendered

    authored = next(page for page in discover_docs(DOCS_CONFIG) if page.route == "/api-reference/")
    assert f"{REPOSITORY_URL}/blob/main/docs/api-reference/index.md" in str(
        xy_docs_footer(authored)
    )
