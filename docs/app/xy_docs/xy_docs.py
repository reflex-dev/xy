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
from xy_docs.changelogs import CHANGELOG_DIRECTORY
from xy_docs.config import DOCS_CONFIG, DOCS_REDIRECTS
from xy_docs.constants import LLMS_TXT_PATH, PUBLIC_DOCS_URL, SOCIAL_IMAGE_URL
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


def _llms_txt_directive() -> rx.Component:
    """Return the hidden agent-facing documentation index directive."""
    return rx.el.blockquote(
        rx.el.span("For AI agents: the complete XY documentation index is at "),
        rx.el.a(
            "llms.txt",
            href=f"{PUBLIC_DOCS_URL}{LLMS_TXT_PATH}",
        ),
        rx.el.span(
            ". Markdown versions are available by appending .md or sending Accept: text/markdown."
        ),
        class_name="sr-only",
    )


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


# Changelog pages repeat "Added", "Fixed", and "Changed" under every release,
# so their TOC lists releases only. The same page copy is used, leaving the
# rendered body and its heading links untouched.
_CHANGELOG_ROUTE_PREFIX = f"/{CHANGELOG_DIRECTORY}/"


def _release_headings_only(page):
    """Return the page with per-release subsections removed from the TOC."""
    if not page.route.startswith(_CHANGELOG_ROUTE_PREFIX):
        return page
    in_fence = False
    lines: list[str] = []
    for line in page.content.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        elif not in_fence and line.startswith("### "):
            continue
        lines.append(line)
    return dataclasses.replace(page, content="\n".join(lines))


def xy_docs_layout(page, content, navigation) -> rx.Component:
    """Render the shared docs layout with Reflex's TOC scroll highlighter."""
    return rx.box(
        _llms_txt_directive(),
        docs_layout(
            page_with_api_reference_toc(_release_headings_only(_without_faq_in_toc(page))),
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


@dataclasses.dataclass(frozen=True, slots=True)
class _RedirectCopy:
    """On-page and metadata copy for one legacy route.

    Args:
        heading: In-page heading shown while the browser follows the redirect.
        description: In-page explanation of where the content moved.
        link_label: Label of the manual link to the destination.
        title: Browser and social title for the legacy route.
        meta_description: Metadata description for the legacy route.
    """

    heading: str
    description: str
    link_label: str
    title: str
    meta_description: str


_DEFAULT_REDIRECT_COPY = _RedirectCopy(
    heading="Page moved",
    description="This documentation page now lives at a new address.",
    link_label="Open the new page",
    title="Page moved · XY",
    meta_description="This documentation page has moved to a new address.",
)

_STYLING_REDIRECT_TITLE = "Styling guide moved · XY"
_STYLING_REDIRECT_DESCRIPTION = "This styling guide now lives in Customize Each Part."

_REDIRECT_COPY = {
    "/components/annotations/": _RedirectCopy(
        heading="Annotations moved",
        description="The chart gallery and component guide are now combined.",
        link_label="Open the combined Annotations guide",
        title="Annotations moved · XY",
        meta_description="Annotations are documented in one combined component guide.",
    ),
    "/styling/examples/#responsive-combo-chart": _RedirectCopy(
        heading="Recipe moved",
        description="The responsive combo chart now lives on the Examples page.",
        link_label="Open the responsive combo chart",
        title="Recipe moved · XY",
        meta_description="The responsive combo chart is now part of the Examples page.",
    ),
    "/styling/customize/#fill,-stroke,-opacity,-and-gradients": _RedirectCopy(
        heading="Mark styling moved",
        description="Mark paint is now documented in Customize Each Part.",
        link_label="Open fill, stroke, opacity, and gradients",
        title=_STYLING_REDIRECT_TITLE,
        meta_description=_STYLING_REDIRECT_DESCRIPTION,
    ),
    "/styling/customize/#legend": _RedirectCopy(
        heading="Chrome styling moved",
        description="Legend and slot styling now live in Customize Each Part.",
        link_label="Open legend styling",
        title=_STYLING_REDIRECT_TITLE,
        meta_description=_STYLING_REDIRECT_DESCRIPTION,
    ),
    "/styling/customize/#annotations": _RedirectCopy(
        heading="Component styling moved",
        description="Annotation and component styling now live in Customize Each Part.",
        link_label="Open annotation styling",
        title=_STYLING_REDIRECT_TITLE,
        meta_description=_STYLING_REDIRECT_DESCRIPTION,
    ),
    "/styling/examples/#palette-playground": _RedirectCopy(
        heading="Playground moved",
        description="The palette playground now lives on the Examples page.",
        link_label="Open Examples",
        title="Playground moved · XY",
        meta_description="The palette playground is now part of the combined Examples page.",
    ),
    "/changelog/": _RedirectCopy(
        heading="Changelog moved",
        description="Release notes now render from the repository changelogs.",
        link_label="Open the XY changelog",
        title="Changelog moved · XY",
        meta_description="The XY changelog is now published from the repository changelog.",
    ),
}


def _redirect_page(destination: str):
    """Render a useful fallback while the browser follows a legacy route."""
    copy = _REDIRECT_COPY.get(destination, _DEFAULT_REDIRECT_COPY)

    return lambda: rx.center(
        rx.vstack(
            rx.heading(copy.heading, size="6"),
            rx.text(copy.description),
            rx.link(copy.link_label, href=destination),
            align="center",
            spacing="4",
        ),
        min_height="100vh",
        padding="2rem",
    )


for _legacy_route, _destination in DOCS_REDIRECTS.items():
    _public_destination = f"/docs/xy{_destination}"
    _canonical_destination = f"{PUBLIC_DOCS_URL}{_destination}"
    _redirect_copy = _REDIRECT_COPY.get(_destination, _DEFAULT_REDIRECT_COPY)
    app.add_page(
        component=_redirect_page(_destination),
        route=_legacy_route,
        title=_redirect_copy.title,
        description=_redirect_copy.meta_description,
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
