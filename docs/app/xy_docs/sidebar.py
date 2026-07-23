"""Curated sidebar for the XY documentation site."""

from __future__ import annotations

import reflex as rx
from reflex_site_shared.docs import (
    docs_sidebar_category,
    docs_sidebar_group,
    docs_sidebar_leaf,
    docs_sidebar_section,
)

from xy_docs.config import DOCS_SECTIONS

SIDEBAR_SECTION_GROUPS = (
    ("Learning", "/", (*DOCS_SECTIONS[:3], DOCS_SECTIONS[7])),
    ("Examples", "/overview/gallery/", DOCS_SECTIONS[3:5]),
    ("Other", "/integrations/", (*DOCS_SECTIONS[5:7], *DOCS_SECTIONS[8:])),
)

INTEGRATION_LINK_ICONS = {
    "/integrations/reflex/": "atom",
    "/integrations/notebooks/": "notebook-tabs",
    "/integrations/matplotlib/": "chart-no-axes-combined",
}


def _leaf(
    title: str,
    href: str,
    url: rx.vars.StringVar[str],
    *,
    guide_margin_class: str = "ml-[3rem]",
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
        guide_margin_class=guide_margin_class,
    )


def _section_leaves(
    landing_route: str,
    leaves: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Include a section landing page without adding another hierarchy level."""
    if any(route == landing_route for _title, route in leaves):
        return leaves
    return (("Overview", landing_route), *leaves)


def _top_level_link(
    title: str,
    href: str,
    icon: str,
    url: rx.vars.StringVar[str],
) -> rx.Component:
    """Render an icon-led direct link aligned with sidebar group headings."""
    active = url == href
    return rx.el.li(
        rx.el.a(
            rx.cond(
                active,
                rx.el.div(
                    class_name=(
                        "absolute left-0 top-1/2 -z-10 h-8 w-full "
                        "-translate-y-1/2 rounded-lg bg-secondary-3"
                    ),
                ),
                rx.fragment(),
            ),
            rx.box(
                rx.icon(tag=icon, size=16, class_name="mr-4 shrink-0"),
                rx.text(title, class_name="m-0 text-sm font-[525]"),
                class_name=rx.cond(
                    active,
                    (
                        "ml-[2.5rem] flex h-8 w-[calc(100%-2.5rem)] "
                        "items-center justify-start text-primary-10 "
                        "xl:max-w-[14rem]"
                    ),
                    (
                        "ml-[2.5rem] flex h-8 w-[calc(100%-2.5rem)] "
                        "items-center justify-start text-secondary-11 "
                        "transition-colors group-hover:text-primary-10 "
                        "dark:group-hover:text-primary-9 xl:max-w-[14rem]"
                    ),
                ),
            ),
            href=href,
            aria_current=rx.cond(active, "page", None),
            class_name="group relative block h-8 w-full no-underline",
        ),
        class_name="m-0 w-full list-none border-none bg-transparent p-0",
    )


def _section_items(
    title: str,
    landing_route: str,
    icon: str,
    leaves: tuple[tuple[str, str], ...],
    url: rx.vars.StringVar[str],
) -> tuple[rx.Component, ...]:
    """Render one sidebar section as a group or a set of direct links."""
    section_leaves = _section_leaves(landing_route, leaves)
    if title == "Integrations":
        return tuple(
            _top_level_link(
                title if leaf_route == landing_route else leaf_title,
                leaf_route,
                INTEGRATION_LINK_ICONS[leaf_route],
                url,
            )
            for leaf_title, leaf_route in section_leaves
            if leaf_route != landing_route
        )
    return (
        docs_sidebar_group(
            title,
            *(_leaf(leaf_title, leaf_route, url) for leaf_title, leaf_route in section_leaves),
            icon=icon,
            open_=(
                (url == "/") | url.startswith("/overview/")
                if landing_route == "/"
                else (
                    (url == landing_route) | url.startswith("/charts/")
                    if title == "Chart Gallery"
                    else url.startswith(landing_route)
                )
            ),
        ),
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
            "/",
            "graduation-cap",
            (url == "/")
            | (url.startswith("/overview/") & (url != "/overview/gallery/"))
            | url.startswith("/core-concepts/")
            | url.startswith("/guides/")
            | url.startswith("/advanced/"),
        ),
        docs_sidebar_category(
            "Gallery",
            "/overview/gallery/",
            "boxes",
            (url == "/overview/gallery/")
            | url.startswith("/styling/")
            | url.startswith("/charts/")
            | url.startswith("/components/")
            | url.startswith("/integrations/"),
        ),
        docs_sidebar_category(
            "API Reference",
            "/api-reference/",
            "book-text",
            url.startswith("/api-reference/"),
        ),
        class_name="m-0 flex w-full list-none flex-col items-start gap-2 p-0",
    )
    content = rx.el.ul(
        *(
            docs_sidebar_section(
                group_title,
                group_route,
                *(
                    item
                    for title, landing_route, icon, leaves in sections
                    for item in _section_items(title, landing_route, icon, leaves, url)
                ),
                connected_line=False,
            )
            for group_title, group_route, sections in SIDEBAR_SECTION_GROUPS
        ),
        class_name="m-0 flex w-full list-none flex-col items-start gap-6 p-0",
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


__all__ = [
    "INTEGRATION_LINK_ICONS",
    "SIDEBAR_SECTION_GROUPS",
    "xy_docs_sidebar",
    "xy_docs_sidebar_comp",
]
