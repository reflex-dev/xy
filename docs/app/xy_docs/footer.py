"""XY-specific footer configuration for the documentation site."""

from datetime import datetime
from urllib.parse import quote

import reflex as rx
from reflex_site_shared.components.docs_shell import (
    docs_feedback_button,
    docs_footer_shell,
)
from reflex_site_shared.docs import DocsPage
from reflex_site_shared.views.footer import dark_mode_toggle

from xy_docs.constants import DOCS_CHANNEL, PUBLIC_XY_VERSION

REPOSITORY_URL = "https://github.com/reflex-dev/xy"


def _footer_link(text: str, href: str) -> rx.Component:
    """Render one XY footer link."""
    router_href = href.removeprefix("/docs/xy") if href.startswith("/docs/xy/") else href
    return rx.el.a(
        text,
        href=router_href,
        class_name=(
            "font-small text-secondary-9 no-underline transition-colors hover:!text-secondary-11"
        ),
    )


def _footer_column(heading: str, *links: rx.Component) -> rx.Component:
    """Render one compact footer navigation column."""
    return rx.box(
        rx.el.h4(
            heading,
            class_name=("text-sm font-semibold tracking-[-0.01313rem] text-secondary-12"),
        ),
        *links,
        class_name="flex min-w-[9rem] flex-col gap-4",
    )


def _page_action(text: str, href: str) -> rx.Component:
    """Render one source-aware page action."""
    return rx.el.a(
        text,
        href=href,
        target="_blank",
        rel="noreferrer",
        class_name=(
            "rounded-full border border-secondary-5 bg-secondary-1 px-3 py-0.5 "
            "font-small text-secondary-9 no-underline shadow-large "
            "transition-colors hover:bg-secondary-3 hover:!text-secondary-11"
        ),
    )


def xy_docs_footer(page: DocsPage) -> rx.Component:
    """Render project links and source-aware actions for an XY docs page."""
    public_path = f"/docs/xy{page.route}"
    issue_title = quote(f"Issue with reflex.dev{public_path}")
    issue_body = quote("Path: " + public_path + "\n\n")
    issue_href = (
        f"{REPOSITORY_URL}/issues/new"
        "?template=documentation.md"
        "&labels=documentation"
        f"&title={issue_title}"
        f"&body={issue_body}"
    )
    edit_href = f"{REPOSITORY_URL}/blob/main/docs/{page.relative_path.as_posix()}"

    feedback = rx.box(
        rx.text(
            "Did this page help?",
            class_name=("whitespace-nowrap font-small text-secondary-11 lg:text-secondary-9"),
        ),
        docs_feedback_button(),
        class_name=(
            "flex w-full flex-col items-center gap-3 rounded-lg bg-secondary-3 "
            "p-4 lg:w-auto lg:flex-row lg:gap-4 lg:bg-transparent lg:p-0"
        ),
    )
    actions = rx.box(
        _page_action("Raise an issue", issue_href),
        _page_action("Edit this page", edit_href),
        class_name="hidden flex-row items-center gap-2 lg:flex",
    )
    link_columns = rx.box(
        _footer_column(
            "Start",
            _footer_link("Overview", "/docs/xy/"),
            _footer_link("Why XY", "/docs/xy/#why-xy"),
            _footer_link("Installation", "/docs/xy/overview/installation/"),
            _footer_link("First chart", "/docs/xy/overview/first-chart/"),
        ),
        _footer_column(
            "Build",
            _footer_link("Gallery", "/docs/xy/overview/gallery/"),
            _footer_link("Real data", "/docs/xy/guides/dataframes-and-real-data/"),
            _footer_link("Deployment", "/docs/xy/guides/deployment-recipes/"),
            _footer_link("API reference", "/docs/xy/api-reference/"),
        ),
        _footer_column(
            "Project",
            _footer_link("GitHub", REPOSITORY_URL),
            _footer_link("Changelog", "/docs/xy/api-reference/changelog/"),
            _footer_link("Getting help", "/docs/xy/guides/getting-help/"),
            _footer_link("Security", f"{REPOSITORY_URL}/blob/main/SECURITY.md"),
        ),
        class_name="flex w-full flex-wrap justify-between gap-12",
    )
    controls = rx.box(
        rx.box(dark_mode_toggle(), class_name="[&>div]:!ml-0"),
        _footer_link("View XY on GitHub ↗", REPOSITORY_URL),
        class_name="flex w-full flex-row items-end justify-between gap-6",
    )
    channel_label = "main-branch preview" if DOCS_CHANNEL == "preview" else "stable docs"
    copyright_status = rx.el.div(
        rx.text(
            f"XY {PUBLIC_XY_VERSION} · {channel_label}",
            class_name="font-small text-secondary-9",
        ),
        rx.text(
            f"Copyright © {datetime.now().year} Pynecone, Inc. · Apache-2.0",
            class_name="font-small text-secondary-9",
        ),
        class_name=("flex w-full flex-col justify-between gap-2 sm:flex-row sm:items-center"),
    )
    return docs_footer_shell(
        feedback,
        actions,
        link_columns,
        controls,
        copyright_status,
    )


__all__ = ["xy_docs_footer"]
