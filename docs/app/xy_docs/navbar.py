"""XY documentation navbar built from the official shared primitives."""

import reflex as rx
import reflex_components_internal as ui
from reflex_site_shared.components.algolia import algolia_search
from reflex_site_shared.components.docs_shell import docs_navbar_frame
from reflex_site_shared.components.icons import get_icon
from reflex_site_shared.components.marketing_button import button

XY_REPOSITORY_URL = "https://github.com/reflex-dev/xy"

_XY_NAV_LINKS = (
    ("Overview", "/docs/xy/"),
    ("Reflex Integration", "/docs/xy/integrations/reflex/"),
)


def xy_docs_logo() -> rx.Component:
    """Render the Reflex XY documentation wordmark.

    Returns:
        The responsive Reflex XY wordmark SVG.
    """
    wordmark_fill = "var(--foreground)"
    return rx.el.svg(
        rx.el.path(
            d="M29 16H32V10H39V7H32V4H39V1H29V16ZM42 16H52V13H45V1H42V16ZM55 16H65V13H58.0439L58 10H65V7H58V4H65V1H55V16ZM68 7H71V10H68V16H71V10H77V16H80V10H77V7H80V1H77V7H71V1H68V7Z",
            fill=wordmark_fill,
            fill_rule="evenodd",
            clip_rule="evenodd",
        ),
        rx.el.path(
            d="M16 16V1H26V4H19V7H26V10H19L19.0439 13H26V16H16Z",
            fill=wordmark_fill,
        ),
        rx.el.path(d="M10 10V16H13V10H10Z", fill=wordmark_fill),
        rx.el.path(
            d="M1 1V16H4V10H10V7H4V4H10V7H13V1H1Z",
            fill=wordmark_fill,
        ),
        rx.el.path(
            d="M90 7H93V10H90V16H93V10H99V16H102V10H99V7H102V1H99V7H93V1H90V7Z",
            fill="var(--muted-foreground)",
            fill_rule="evenodd",
            clip_rule="evenodd",
        ),
        rx.el.path(d="M108 7V10H113H115V7H108Z", fill="var(--muted-foreground)"),
        rx.el.path(d="M115 7H118V1H115V7Z", fill="var(--muted-foreground)"),
        rx.el.path(d="M105 1V7H108V1H105Z", fill="var(--muted-foreground)"),
        rx.el.path(d="M110 10V16H113V10H110Z", fill="var(--muted-foreground)"),
        xmlns="http://www.w3.org/2000/svg",
        width="118",
        height="16",
        view_box="0 0 118 16",
        fill="none",
        aria_label="Reflex XY",
    )


def _menu_item(label: str, href: str) -> rx.Component:
    """Render one desktop navbar item with the official treatment.

    Args:
        label: Visible item label.
        href: Destination URL.

    Returns:
        Official-style navigation menu item.
    """
    path = rx.State.router.page.path
    relative = href.removeprefix("/docs/xy").rstrip("/") or "/"
    full = href.rstrip("/")
    active = (path == full) | (path == relative)
    if relative == "/":
        active = (
            active
            | (path == "/index")
            | path.startswith("/overview/")
            | path.startswith("/docs/xy/overview/")
        )
    else:
        active = active | path.startswith(full + "/") | path.startswith(relative + "/")
    return ui.navigation_menu.item(
        rx.el.a(
            label,
            href=href.removeprefix("/docs/xy") or "/",
            aria_current=rx.cond(active, "page", None),
            class_name=(
                "inline-flex h-9 items-center justify-center whitespace-nowrap px-4 "
                "text-sm font-medium leading-none text-foreground no-underline "
                "transition-colors hover:text-muted-foreground focus-visible:outline-2 "
                "focus-visible:outline-offset-2 focus-visible:outline-ring"
            ),
        ),
        class_name="flex h-full items-center justify-center",
        custom_attrs={"role": "menuitem"},
    )


def _github_button() -> rx.Component:
    """Render the external XY repository link."""
    label = "View XY on GitHub"
    return rx.el.elements.a(
        button(
            get_icon(icon="github_navbar", class_name="size-4 shrink-0"),
            "GitHub",
            custom_attrs={"aria-label": label},
            size="sm",
            variant="primary",
            native_button=False,
            class_name="whitespace-nowrap",
        ),
        href=XY_REPOSITORY_URL,
        target="_blank",
        rel="noopener noreferrer",
        aria_label=label,
    )


def _mobile_navigation() -> rx.Component:
    """Keep XY docs destinations available below the desktop breakpoint.

    Returns:
        A native disclosure containing the primary XY docs links.
    """
    return rx.el.details(
        rx.el.summary(
            ui.icon("Menu01Icon", class_name="size-5 group-open/xy-menu:hidden"),
            ui.icon("Cancel01Icon", class_name="hidden size-5 group-open/xy-menu:block"),
            aria_label="Toggle navigation menu",
            class_name="flex size-9 cursor-pointer list-none items-center justify-center rounded-full text-foreground hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden",
        ),
        rx.el.div(
            *[
                rx.el.a(
                    label,
                    ui.icon("ArrowUpRight01Icon", aria_hidden=True, class_name="size-4 shrink-0"),
                    href=href.removeprefix("/docs/xy") or "/",
                    on_click=rx.call_script(
                        "document.querySelector('header details[open]')?.removeAttribute('open')"
                    ),
                    class_name="flex w-full items-center justify-between gap-3 border-b border-border px-4 py-4 text-base font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
                )
                for label, href in _XY_NAV_LINKS
            ],
            rx.el.div(_github_button(), class_name="mt-4"),
            aria_label="XY documentation navigation",
            role="navigation",
            class_name="fixed inset-x-0 top-[var(--docs-header-height)] max-h-[calc(100dvh-var(--docs-header-height))] overflow-y-auto border-b border-border-subtle bg-background px-6 py-4 shadow-small",
        ),
        class_name="group/xy-menu",
    )


def _navigation_menu() -> rx.Component:
    """Render the official desktop controls and mobile drawer trigger.

    Returns:
        XY navigation menu.
    """
    return ui.navigation_menu.root(
        ui.navigation_menu.list(
            *(_menu_item(label, href) for label, href in _XY_NAV_LINKS),
            class_name="m-0 hidden xl:flex h-full list-none flex-row items-center gap-2",
            custom_attrs={"role": "menubar"},
        ),
        ui.navigation_menu.list(
            ui.navigation_menu.item(
                algolia_search(),
                unstyled=True,
                custom_attrs={"role": "menuitem"},
            ),
            ui.navigation_menu.item(
                _github_button(),
                unstyled=True,
                class_name="hidden xl:flex",
                custom_attrs={"role": "menuitem"},
            ),
            ui.navigation_menu.item(
                _mobile_navigation(),
                unstyled=True,
                class_name="flex xl:hidden",
                custom_attrs={"role": "menuitem"},
            ),
            class_name="m-0 flex h-full list-none flex-row items-center gap-2 lg:gap-4",
            custom_attrs={"role": "menubar"},
        ),
        unstyled=True,
        class_name="relative mx-auto flex h-full w-full flex-row items-center justify-end xl:justify-between gap-6",
    )


@rx.memo
def xy_docs_navbar() -> rx.Component:
    """Render the memoized XY navbar.

    Returns:
        Official documentation navbar with an active XY section.
    """
    return docs_navbar_frame(
        rx.el.elements.a(
            xy_docs_logo(),
            href="/docs/",
            class_name="mr-10 flex shrink-0 items-center gap-2.5 no-underline",
        ),
        _navigation_menu(),
    )


__all__ = [
    "XY_REPOSITORY_URL",
    "xy_docs_logo",
    "xy_docs_navbar",
]
