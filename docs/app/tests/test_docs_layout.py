"""Integration contracts for XY's wrapper around the shared docs layout."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import reflex as rx
from reflex_site_shared.docs import DocsPage, NavigationItem
from xy_docs.xy_docs import xy_docs_layout


def _walk(component: rx.Component) -> Iterator[rx.Component]:
    """Find semantic elements without depending on the shared child order."""
    yield component
    for child in component.children:
        yield from _walk(child)


@pytest.mark.parametrize(
    ("route", "expected_links"),
    (
        ("/", (("Next", "/overview/installation/"),)),
        (
            "/overview/installation/",
            (("Back", "/"), ("Next", "/overview/first-chart/")),
        ),
        ("/overview/first-chart/", (("Back", "/overview/installation/"),)),
    ),
    ids=("first-page", "middle-page", "last-page"),
)
def test_shared_layout_preserves_article_and_adjacent_pages(
    tmp_path: Path,
    route: str,
    expected_links: tuple[tuple[str, str], ...],
) -> None:
    """Keep content styled and adjacent links correct at both navigation edges."""
    navigation = (
        NavigationItem(title="Overview", route="/"),
        NavigationItem(title="Installation", route="/overview/installation/"),
        NavigationItem(title="First chart", route="/overview/first-chart/"),
    )
    page = DocsPage(
        source_path=tmp_path / "index.md",
        relative_path=Path("index.md"),
        route=route,
        title="Layout contract",
        description=None,
        metadata={},
        content="# Layout contract",
    )
    content = rx.el.p("Article content must survive the layout wrapper.")
    nodes = tuple(_walk(xy_docs_layout(page, content, navigation)))

    articles = [node for node in nodes if node.tag == "article"]
    assert len(articles) == 1
    assert "docs-article" in str(articles[0].class_name).strip('"').split()
    assert content in articles[0].children

    pagers = [
        node
        for node in nodes
        if node.tag == "nav"
        and str(node.custom_attrs.get("aria-label")).strip('"') == "Previous and next pages"
    ]
    assert len(pagers) == 1
    pager = pagers[0]
    assert {"grid", "grid-cols-2"} <= set(str(pager.class_name).strip('"').split())
    # An exact child count also rejects leftover spacers or missing-link fragments.
    assert len(pager.children) == len(expected_links)
    for link, (label, destination) in zip(pager.children, expected_links, strict=True):
        assert link.tag == "Link"
        assert str(link.to).strip('"') == destination
        assert label in str(link.children[0])
        assert ("col-start-2" in str(link.class_name)) == (label == "Next")
