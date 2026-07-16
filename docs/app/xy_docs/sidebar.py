"""Curated sidebar for the XY documentation site."""

from __future__ import annotations

import reflex as rx
from reflex_site_shared.docs import (
    docs_sidebar_category,
    docs_sidebar_group,
    docs_sidebar_leaf,
    docs_sidebar_section,
)


def _leaf(
    title: str,
    href: str,
    url: rx.vars.StringVar[str],
) -> rx.Component:
    """Render one memoized XY documentation leaf.

    Args:
        title: Visible navigation label.
        href: Documentation route.
        url: Current normalized route.

    Returns:
        Shared official documentation leaf.
    """
    return docs_sidebar_leaf(
        title=title,
        href=href,
        active=url == href,
        guide_margin_class="ml-[3rem]",
    )


@rx.memo
def xy_docs_sidebar_comp(url: rx.vars.StringVar[str]) -> rx.Component:
    """Render the memoized XY sidebar tree.

    Args:
        url: Current normalized documentation route.

    Returns:
        Curated XY documentation navigation.
    """
    categories = rx.el.ul(
        docs_sidebar_category(
            "Learn",
            "/getting-started/",
            "graduation-cap",
            url.startswith("/getting-started/")
            | url.startswith("/core-concepts/")
            | url.startswith("/guides/"),
        ),
        docs_sidebar_category(
            "Charts",
            "/charts/",
            "chart-column",
            url.startswith("/charts/"),
        ),
        docs_sidebar_category(
            "Components",
            "/components/",
            "layout-panel-left",
            url.startswith("/components/"),
        ),
        docs_sidebar_category(
            "API Reference",
            "/api-reference/",
            "book-text",
            url.startswith("/api-reference/"),
        ),
        class_name="flex w-full list-none flex-col items-start gap-2",
    )
    content = rx.el.ul(
        docs_sidebar_section(
            "Learn",
            "/getting-started/",
            docs_sidebar_group(
                "Getting Started",
                _leaf("Introduction", "/getting-started/", url),
                icon="rocket",
                open_=url.startswith("/getting-started/"),
            ),
            docs_sidebar_group(
                "Core Concepts",
                _leaf("Overview", "/core-concepts/", url),
                _leaf("Composition", "/core-concepts/composition/", url),
                _leaf("Data and Columns", "/core-concepts/data/", url),
                _leaf("Axes and Scales", "/core-concepts/axes-and-scales/", url),
                _leaf("Interactions", "/core-concepts/interactions/", url),
                _leaf("Styling and Themes", "/core-concepts/styling/", url),
                icon="boxes",
                open_=url.startswith("/core-concepts/"),
            ),
            connected_line=False,
        ),
        docs_sidebar_section(
            "Charts",
            "/charts/",
            docs_sidebar_group(
                "Charts",
                _leaf("Overview", "/charts/", url),
                _leaf("Line and Area Charts", "/charts/line-and-area/", url),
                _leaf("Scatter Charts", "/charts/scatter/", url),
                _leaf("Bar and Column Charts", "/charts/bar-and-column/", url),
                _leaf("Distribution Charts", "/charts/distributions/", url),
                _leaf("Density and Grid Charts", "/charts/density-and-grids/", url),
                _leaf("Error Bars and Bands", "/charts/uncertainty/", url),
                _leaf("Specialized Charts", "/charts/specialized/", url),
                _leaf("Facets and Layers", "/charts/facets-and-layers/", url),
                icon="chart-column",
                open_=url.startswith("/charts/"),
            ),
            connected_line=False,
        ),
        docs_sidebar_section(
            "Components",
            "/components/",
            docs_sidebar_group(
                "Components",
                _leaf("Overview", "/components/", url),
                _leaf("Annotations", "/components/annotations/", url),
                _leaf("Chart Chrome", "/components/chart-chrome/", url),
                icon="layout-panel-left",
                open_=url.startswith("/components/"),
            ),
            connected_line=False,
        ),
        docs_sidebar_section(
            "Guides",
            "/guides/",
            docs_sidebar_group(
                "Guides",
                _leaf("Overview", "/guides/", url),
                _leaf("Exporting", "/guides/exporting/", url),
                _leaf("Notebooks and Pyplot", "/guides/notebooks-and-pyplot/", url),
                _leaf("Large Datasets", "/guides/large-datasets/", url),
                _leaf("Streaming Data", "/guides/streaming-data/", url),
                _leaf("Framework Integration", "/guides/framework-integration/", url),
                icon="book-open",
                open_=url.startswith("/guides/"),
            ),
            connected_line=False,
        ),
        docs_sidebar_section(
            "API Reference",
            "/api-reference/",
            docs_sidebar_group(
                "API Reference",
                _leaf("Overview", "/api-reference/", url),
                _leaf("Components", "/api-reference/components/", url),
                icon="book-text",
                open_=url.startswith("/api-reference/"),
            ),
            connected_line=False,
        ),
        class_name="m-0 flex w-full list-none flex-col items-start gap-8 p-0",
    )
    return rx.box(
        categories,
        content,
        style={
            "&::-webkit-scrollbar-thumb": {"background_color": "transparent"},
            "&::-webkit-scrollbar": {"background_color": "transparent"},
        },
        class_name="hidden-scrollbar flex h-full w-full flex-col items-start gap-8 overflow-x-hidden overflow-y-scroll scroll-p-4 pb-24 pl-6 pr-4 pt-8 3xl:pl-0",
    )


def xy_docs_sidebar(route: str) -> rx.Component:
    """Render the XY sidebar for one static documentation route.

    Args:
        route: Current page route.

    Returns:
        Memoized XY sidebar component.
    """
    normalized_route = route.rstrip("/") + "/"
    return xy_docs_sidebar_comp(url=normalized_route)


__all__ = ["xy_docs_sidebar", "xy_docs_sidebar_comp"]
