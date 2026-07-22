"""Markdown-backed XY documentation site."""

import dataclasses
import re

import reflex as rx
from reflex_site_shared import styles
from reflex_site_shared.docs import DocsLayoutConfig, build_docs_routes
from reflex_site_shared.telemetry import get_pixel_website_trackers
from reflex_site_shared.templates.docs import docs_layout
from reflex_site_shared.utils.docpage import right_sidebar_item_highlight

from xy_docs.breadcrumb import xy_docs_breadcrumb
from xy_docs.config import DOCS_CONFIG, DOCS_REDIRECTS
from xy_docs.constants import PUBLIC_DOCS_URL, SOCIAL_IMAGE_URL
from xy_docs.footer import xy_docs_footer
from xy_docs.markdown import page_with_api_reference_toc, render_xy_markdown_page
from xy_docs.navbar import xy_docs_navbar
from xy_docs.sidebar import xy_docs_sidebar

_CHART_STYLE = {
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
    head_components=[
        *get_pixel_website_trackers(),
        rx.el.meta(name="application-name", content="XY"),
        rx.el.meta(name="theme-color", content="#6E56CF"),
    ],
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


# FAQ sections stay on the page but are omitted from the right-sidebar
# "On This Page" list: docs_layout derives that list from page.content, so
# stripping the FAQ section from a copy of the page hides its headings from
# the TOC without touching the rendered body.
_FAQ_SECTION = re.compile(r"^## FAQ\s*$.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def _without_faq_in_toc(page):
    """Return the page with its FAQ section removed from TOC-visible content."""
    stripped = _FAQ_SECTION.sub("", page.content)
    if stripped == page.content:
        return page
    return dataclasses.replace(page, content=stripped)


def xy_docs_layout(page, content, navigation) -> rx.Component:
    """Render the shared docs layout with Reflex's TOC scroll highlighter."""
    return rx.box(
        docs_layout(
            page_with_api_reference_toc(_without_faq_in_toc(page)),
            content,
            navigation,
            config=_LAYOUT_CONFIG,
        ),
        display="contents",
        on_mount=rx.call_script(right_sidebar_item_highlight()),
    )


_DOCS_ROUTES = build_docs_routes(
    DOCS_CONFIG,
    renderer=render_xy_markdown_page,
    layout=xy_docs_layout,
)

for _route in _DOCS_ROUTES:
    _canonical_url = f"{PUBLIC_DOCS_URL}{_route.path}"
    _seo_title = f"{_route.title or 'Documentation'} · XY"
    _description = _route.description or "Build responsive interactive Python charts with XY."
    app.add_page(
        component=_route.component,
        route=_route.path,
        title=_seo_title,
        description=_description,
        image=SOCIAL_IMAGE_URL,
        meta=(
            rx.el.link(rel="canonical", href=_canonical_url),
            rx.el.meta(property="og:type", content="website"),
            rx.el.meta(property="og:site_name", content="XY"),
            rx.el.meta(property="og:title", content=_seo_title),
            rx.el.meta(property="og:description", content=_description),
            rx.el.meta(property="og:url", content=_canonical_url),
            rx.el.meta(name="twitter:card", content="summary_large_image"),
            rx.el.meta(name="twitter:title", content=_seo_title),
            rx.el.meta(name="twitter:description", content=_description),
            rx.el.meta(name="twitter:image", content=SOCIAL_IMAGE_URL),
        ),
        context={"sitemap": {"loc": _canonical_url}},
    )


def _redirect_page(destination: str):
    """Render a useful fallback while the browser follows a legacy route."""
    if destination == "/components/annotations/":
        heading = "Annotations moved"
        description = "The chart gallery and component guide are now combined."
        link_label = "Open the combined Annotations guide"
    elif destination == "/styling/examples/#responsive-combo-chart":
        heading = "Recipe moved"
        description = "The responsive combo chart now lives on the Examples page."
        link_label = "Open the responsive combo chart"
    elif destination == "/styling/customize/#fill,-stroke,-opacity,-and-gradients":
        heading = "Mark styling moved"
        description = "Mark paint is now documented in Customize Each Part."
        link_label = "Open fill, stroke, opacity, and gradients"
    elif destination == "/styling/customize/#legend":
        heading = "Chrome styling moved"
        description = "Legend and slot styling now live in Customize Each Part."
        link_label = "Open legend styling"
    elif destination == "/styling/customize/#annotations":
        heading = "Component styling moved"
        description = "Annotation and component styling now live in Customize Each Part."
        link_label = "Open annotation styling"
    else:
        heading = "Playground moved"
        description = "The palette playground now lives on the Examples page."
        link_label = "Open Examples"

    return lambda: rx.center(
        rx.vstack(
            rx.heading(heading, size="6"),
            rx.text(description),
            rx.link(link_label, href=destination),
            align="center",
            spacing="4",
        ),
        min_height="100vh",
        padding="2rem",
    )


for _legacy_route, _destination in DOCS_REDIRECTS.items():
    _public_destination = f"/docs/xy{_destination}"
    _canonical_destination = f"{PUBLIC_DOCS_URL}{_destination}"
    _is_annotations_redirect = _destination == "/components/annotations/"
    _is_recipe_redirect = _destination == "/styling/examples/#responsive-combo-chart"
    _is_customize_redirect = _destination.startswith("/styling/customize/")
    app.add_page(
        component=_redirect_page(_destination),
        route=_legacy_route,
        title=(
            "Annotations moved · XY"
            if _is_annotations_redirect
            else "Recipe moved · XY"
            if _is_recipe_redirect
            else "Styling guide moved · XY"
            if _is_customize_redirect
            else "Playground moved · XY"
        ),
        description=(
            "Annotations are documented in one combined component guide."
            if _is_annotations_redirect
            else "The responsive combo chart is now part of the Examples page."
            if _is_recipe_redirect
            else "This styling guide now lives in Customize Each Part."
            if _is_customize_redirect
            else "The palette playground is now part of the combined Examples page."
        ),
        on_load=rx.redirect(_destination, replace=True),
        meta=(
            rx.el.link(rel="canonical", href=_canonical_destination),
            rx.el.meta(
                http_equiv="refresh",
                content=f"0; url={_public_destination}",
            ),
        ),
        context={"sitemap": None},
    )
