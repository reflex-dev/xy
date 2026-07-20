"""XY page breadcrumbs with the official mobile documentation drawer."""

import reflex as rx
import reflex_components_internal as ui
from reflex_base.config import get_config
from reflex_site_shared.docs import docs_page_actions
from reflex_site_shared.docs.models import DocsPage
from reflex_site_shared.views.sidebar import docs_sidebar_drawer

from xy_docs.constants import LLMS_FULL_TXT_PATH, PUBLIC_DOCS_URL
from xy_docs.plugins import markdown_asset_path

_BREADCRUMB_LABELS = {
    "charts": "Chart Gallery",
    "gallery": "Chart Gallery",
    "modebars-and-interaction-controls": "Modebars & Controls",
}

_BREADCRUMB_ROUTES = {
    "/charts": "/overview/gallery/",
}


def _breadcrumb_label(segment: str, *, page_title: str | None = None) -> str:
    """Convert one URL segment to its visible breadcrumb label.

    Args:
        segment: Kebab-case URL segment.

    Returns:
        Page title or title-cased breadcrumb label.
    """
    return _BREADCRUMB_LABELS.get(
        segment,
        page_title or segment.replace("-", " ").title(),
    )


def _breadcrumb_parts(page: DocsPage) -> tuple[tuple[str, str], ...]:
    """Return breadcrumb labels and destinations for one documentation page."""
    segments = [segment for segment in page.route.split("/") if segment]
    current_path = ""
    parts: list[tuple[str, str]] = []

    for index, segment in enumerate(segments):
        current_path += f"/{segment}"
        parts.append(
            (
                _breadcrumb_label(
                    segment,
                    page_title=page.title if index == len(segments) - 1 else None,
                ),
                _BREADCRUMB_ROUTES.get(current_path, f"{current_path}/"),
            )
        )
    return tuple(parts)


def xy_docs_breadcrumb(page: DocsPage, sidebar: rx.Component) -> rx.Component:
    """Render official-style XY breadcrumbs and the mobile sidebar drawer.

    Args:
        page: Current discovered documentation page.
        sidebar: Complete memoized XY sidebar supplied by the shared layout.

    Returns:
        Responsive breadcrumb row and drawer trigger.
    """
    parts = _breadcrumb_parts(page)
    breadcrumbs: list[rx.Component] = []

    for index, (label, href) in enumerate(parts):
        base_class = ui.cn(
            "min-h-8 flex items-center text-sm font-[525] text-secondary-12 last:text-secondary-11",
            "truncate" if index == len(parts) - 1 else "",
        )
        breadcrumbs.append(
            rx.el.a(
                label,
                class_name=ui.cn(
                    base_class,
                    "hover:text-primary-10 dark:hover:text-primary-9",
                ),
                underline="none",
                href=href,
            )
        )
        if index < len(parts) - 1:
            breadcrumbs.extend(
                (
                    ui.icon(
                        "ArrowRight01Icon",
                        class_name="hidden size-4 text-secondary-11 lg:flex",
                    ),
                    rx.text(
                        "/",
                        class_name="flex font-sm text-secondary-11 lg:hidden",
                    ),
                )
            )

    if not parts:
        breadcrumbs.append(
            rx.el.span(
                page.title,
                class_name="flex min-h-8 items-center text-sm font-[525] text-secondary-11",
            )
        )

    return rx.box(
        docs_sidebar_drawer(
            sidebar,
            trigger=rx.box(
                class_name="absolute inset-0 z-[1] flex bg-transparent lg:hidden",
            ),
        ),
        rx.box(
            *breadcrumbs,
            class_name="flex flex-row items-center gap-[5px] overflow-hidden lg:gap-4",
        ),
        rx.box(
            docs_page_actions(
                markdown_url=f"{PUBLIC_DOCS_URL}/{markdown_asset_path(page)}",
                llms_full_txt_url=f"{PUBLIC_DOCS_URL}{LLMS_FULL_TXT_PATH}",
                copy_url=f"{get_config().frontend_path}/{markdown_asset_path(page)}",
            ),
            ui.icon(
                "ArrowDown01Icon",
                size=14,
                class_name="flex !text-secondary-9 lg:hidden",
            ),
            class_name="flex flex-row items-center gap-2 p-[0.563rem] lg:p-0",
        ),
        class_name="relative z-10 mb-10 flex w-full flex-row items-center justify-between gap-4 border-b border-secondary-4 max-lg:py-2 lg:gap-0 lg:border-none lg:p-0",
    )


__all__ = ["xy_docs_breadcrumb"]
