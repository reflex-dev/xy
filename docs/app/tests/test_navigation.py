"""Tests for the documentation source map."""

from xy_docs.markdown import prepare_markdown, rewrite_links, slugify
from xy_docs.navigation import DOCS_ROOT, PAGES, SECTIONS, adjacent_pages


def test_navigation_sources_exist() -> None:
    """Every sidebar entry points to an existing Markdown document."""
    missing = [page.source for page in PAGES if not page.path.is_file()]
    assert missing == []


def test_routes_and_sources_are_unique() -> None:
    """Routes and source files are one-to-one."""
    assert len({page.route for page in PAGES}) == len(PAGES)
    assert len({page.source for page in PAGES}) == len(PAGES)


def test_all_public_markdown_is_in_navigation() -> None:
    """Do not leave a public Markdown document unreachable from the sidebar."""
    sources = {
        path.relative_to(DOCS_ROOT).as_posix()
        for path in DOCS_ROOT.rglob("*.md")
        if "app" not in path.relative_to(DOCS_ROOT).parts
    }
    assert sources == {page.source for page in PAGES}


def test_sections_are_not_empty() -> None:
    """Sidebar groups always contain at least one page."""
    assert all(section.pages for section in SECTIONS)


def test_adjacent_pages_follow_flattened_navigation() -> None:
    """Previous and next links follow sidebar order."""
    assert adjacent_pages(PAGES[0]) == (None, PAGES[1])
    assert adjacent_pages(PAGES[-1]) == (PAGES[-2], None)
    assert adjacent_pages(PAGES[3]) == (PAGES[2], PAGES[4])


def test_heading_ids_are_stable_and_skip_code_fences(tmp_path) -> None:
    """Headings get unique anchors while code samples stay untouched."""
    page = PAGES[0]
    markdown, headings = prepare_markdown(page)
    assert '<h1 id="xy">xy</h1>' in markdown
    assert headings[0].slug == "xy"
    assert len({heading.slug for heading in headings}) == len(headings)
    assert slugify("`xy.pyplot` — API") == "xypyplot-api"


def test_relative_markdown_links_become_routes() -> None:
    """Cross-document links survive the move from files to app routes."""
    source_path = DOCS_ROOT / "styling.md"
    source = "See [renderer](design/renderer-architecture.md#target)."
    assert rewrite_links(source, source_path) == (
        "See [renderer](/design/renderer-architecture/#target)."
    )
