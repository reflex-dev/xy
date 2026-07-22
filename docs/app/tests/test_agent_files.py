"""Tests for the agent-readable documentation files and page actions."""

from pathlib import Path

import pytest
from reflex_site_shared.docs.content import discover_docs
from rxconfig import config
from xy_docs.api_reference import API_REFERENCE_HEADING, component_api_paths
from xy_docs.breadcrumb import xy_docs_breadcrumb
from xy_docs.config import DOCS_CONFIG
from xy_docs.constants import LLMS_FULL_TXT_PATH, PUBLIC_DOCS_URL
from xy_docs.plugins import (
    XYDocsAgentFilesPlugin,
    build_llms_full_txt,
    build_llms_txt,
    markdown_asset_path,
    page_markdown_with_api_reference,
)
from xy_docs.prerender import XyDocsMarkdownPlugin
from xy_docs.sidebar import xy_docs_sidebar


def _headings(content: str, level: int) -> list[str]:
    """Collect headings of one level, ignoring fenced code blocks."""
    prefix = "#" * level + " "
    headings: list[str] = []
    in_fence = False
    for line in content.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        elif not in_fence and line.startswith(prefix):
            headings.append(line)
    return headings


def test_markdown_asset_paths_match_published_assets() -> None:
    """Every derived Markdown path is actually published for its page."""
    published = {
        path.as_posix()
        for path, _content in XyDocsMarkdownPlugin(docs=DOCS_CONFIG).get_static_assets()
    }
    for page in discover_docs(DOCS_CONFIG):
        asset = markdown_asset_path(page)
        assert any(path.endswith(asset) for path in published), page.route


def test_llms_txt_indexes_every_page_under_the_public_url() -> None:
    """The index links llms-full.txt and each page's public Markdown URL."""
    content = build_llms_txt(DOCS_CONFIG)
    assert f"({PUBLIC_DOCS_URL}{LLMS_FULL_TXT_PATH})" in content
    for page in discover_docs(DOCS_CONFIG):
        assert f"({PUBLIC_DOCS_URL}/{markdown_asset_path(page)})" in content


def test_llms_full_txt_keeps_section_headers_above_page_content() -> None:
    """The combined file has one H1 and an H2 section per page."""
    content = build_llms_full_txt(DOCS_CONFIG)
    assert _headings(content, level=1) == ["# XY Documentation"]
    section_headers = _headings(content, level=2)
    for page in discover_docs(DOCS_CONFIG):
        assert f"## {page.title}" in section_headers


def test_component_api_is_present_in_every_agent_markdown_export() -> None:
    """Publish Reflex-style API tables to page Markdown and llms-full.txt."""
    pages = {page.route: page for page in discover_docs(DOCS_CONFIG)}
    page = pages["/components/axes/"]
    component_paths = component_api_paths(page.metadata)
    assert component_paths == ("xy.x_axis", "xy.y_axis")

    page_markdown = page_markdown_with_api_reference(page)
    published_assets = dict(XyDocsMarkdownPlugin(docs=DOCS_CONFIG).get_static_assets())
    published_markdown = next(
        content
        for path, content in published_assets.items()
        if path.as_posix().endswith(markdown_asset_path(page))
    )
    llms_full = build_llms_full_txt(DOCS_CONFIG)

    for content in (page_markdown, published_markdown, llms_full):
        assert f"## {API_REFERENCE_HEADING}" in content
        assert "### xy.x_axis" in content
        assert "### xy.y_axis" in content
        assert "| Prop | Type | Description |" in content

    assert published_markdown.startswith("---\n")


def test_agent_files_publish_under_the_frontend_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both agent files land inside the configured frontend path."""
    monkeypatch.setattr("xy_docs.plugins.get_config", lambda: config)
    assets = XYDocsAgentFilesPlugin(docs=DOCS_CONFIG).get_static_assets()
    paths = {path for path, _content in assets}
    root = Path("public") / config.frontend_path.strip("/")
    assert paths == {root / "llms.txt", root / "llms-full.txt"}


def test_breadcrumb_actions_use_public_and_local_urls() -> None:
    """Page actions point at this site's Markdown, not root-relative paths."""
    for page in discover_docs(DOCS_CONFIG):
        if page.route.strip("/"):
            break
    rendered = str(xy_docs_breadcrumb(page, xy_docs_sidebar(page.route)))
    asset = markdown_asset_path(page)
    public_host_and_path = PUBLIC_DOCS_URL.removeprefix("https://")
    assert f"{public_host_and_path}/{asset}" in rendered
    assert f"{PUBLIC_DOCS_URL}{LLMS_FULL_TXT_PATH}" in rendered
    assert f"{config.frontend_path}/{asset}" in rendered
