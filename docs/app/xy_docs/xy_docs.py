"""Markdown-backed XY documentation site."""

import reflex as rx
from reflex_site_shared import styles
from reflex_site_shared.docs import DocsLayoutConfig, register_docs
from reflex_site_shared.telemetry import get_pixel_website_trackers
from reflex_site_shared.templates.docs import docs_layout
from reflex_site_shared.utils.docpage import right_sidebar_item_highlight

from xy_docs.breadcrumb import xy_docs_breadcrumb
from xy_docs.config import DOCS_CONFIG
from xy_docs.footer import xy_docs_footer
from xy_docs.markdown import render_xy_markdown_page
from xy_docs.navbar import xy_docs_navbar
from xy_docs.sidebar import xy_docs_sidebar

_CHART_STYLE = {
    "--chart-modebar-bg": "var(--secondary-2)",
    "--chart-modebar-active": "var(--primary-a4)",
    "--chart-text": "var(--secondary-11)",
    "--chart-grid": "var(--secondary-a5)",
    "--chart-axis": "var(--secondary-a8)",
    "--chart-legend-bg": "var(--secondary-2)",
    "--chart-tooltip-bg": "var(--secondary-3)",
    "--chart-tooltip-text": "var(--secondary-12)",
    "--chart-focus": "var(--primary-9)",
}

app = rx.App(
    style={**styles.BASE_STYLE, **_CHART_STYLE},
    app_wraps={},
    theme=rx.theme(
        has_background=True,
        radius="large",
        accent_color="violet",
    ),
    head_components=get_pixel_website_trackers(),
)

_LAYOUT_CONFIG = DocsLayoutConfig(
    site_title="XY",
    github_url="https://github.com/reflex-dev/xy",
    show_github_navbar=False,
    navbar=xy_docs_navbar,
    sidebar=xy_docs_sidebar,
    breadcrumb=xy_docs_breadcrumb,
    page_footer=xy_docs_footer,
)


def xy_docs_layout(page, content, navigation) -> rx.Component:
    """Render the shared docs layout with Reflex's TOC scroll highlighter."""
    return rx.box(
        docs_layout(page, content, navigation, config=_LAYOUT_CONFIG),
        display="contents",
        on_mount=rx.call_script(right_sidebar_item_highlight()),
    )


register_docs(
    app,
    DOCS_CONFIG,
    renderer=render_xy_markdown_page,
    layout=xy_docs_layout,
)
