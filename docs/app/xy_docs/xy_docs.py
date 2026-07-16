"""Markdown-backed XY documentation site."""

import reflex as rx
from reflex_site_shared import styles
from reflex_site_shared.docs import DocsLayoutConfig, register_docs
from reflex_site_shared.telemetry import get_pixel_website_trackers

from xy_docs.breadcrumb import xy_docs_breadcrumb
from xy_docs.config import DOCS_CONFIG
from xy_docs.footer import xy_docs_footer
from xy_docs.navbar import xy_docs_navbar
from xy_docs.sidebar import xy_docs_sidebar

app = rx.App(
    style=styles.BASE_STYLE,
    app_wraps={},
    theme=rx.theme(
        has_background=True,
        radius="large",
        accent_color="violet",
    ),
    head_components=get_pixel_website_trackers(),
)


register_docs(
    app,
    DOCS_CONFIG,
    layout_config=DocsLayoutConfig(
        site_title="XY",
        github_url="https://github.com/reflex-dev/xy",
        show_github_navbar=False,
        navbar=xy_docs_navbar,
        sidebar=xy_docs_sidebar,
        breadcrumb=xy_docs_breadcrumb,
        page_footer=xy_docs_footer,
    ),
)
