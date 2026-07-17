"""XY page breadcrumbs with the official mobile documentation drawer."""

import reflex as rx
import reflex_components_internal as ui
from reflex_site_shared.docs.models import DocsPage
from reflex_site_shared.views.sidebar import docs_sidebar_drawer

_BREADCRUMB_LABELS = {
    "charts": "Chart Gallery",
    "gallery": "Chart Gallery",
    "modebars-and-interaction-controls": "Modebars & Controls",
}

_BREADCRUMB_ROUTES = {
    "/charts": "/overview/gallery/",
}


def _breadcrumb_label(segment: str) -> str:
    """Convert one URL segment to its visible breadcrumb label.

    Args:
        segment: Kebab-case URL segment.

    Returns:
        Title-cased breadcrumb label.
    """
    return _BREADCRUMB_LABELS.get(segment, segment.replace("-", " ").title())


def xy_docs_breadcrumb(page: DocsPage, sidebar: rx.Component) -> rx.Component:
    """Render official-style XY breadcrumbs and the mobile sidebar drawer.

    Args:
        page: Current discovered documentation page.
        sidebar: Complete memoized XY sidebar supplied by the shared layout.

    Returns:
        Responsive breadcrumb row and drawer trigger.
    """
    segments = [segment for segment in page.route.split("/") if segment]
    breadcrumbs: list[rx.Component] = []
    current_path = ""

    for index, segment in enumerate(segments):
        current_path += f"/{segment}"
        href = _BREADCRUMB_ROUTES.get(current_path, f"{current_path}/")
        base_class = ui.cn(
            "min-h-8 flex items-center text-sm font-[525] text-secondary-12 last:text-secondary-11",
            "truncate" if index == len(segments) - 1 else "",
        )
        breadcrumbs.append(
            rx.el.a(
                _breadcrumb_label(segment),
                class_name=ui.cn(
                    base_class,
                    "hover:text-primary-10 dark:hover:text-primary-9",
                ),
                underline="none",
                href=href,
            )
        )
        if index < len(segments) - 1:
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

    if not breadcrumbs:
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
