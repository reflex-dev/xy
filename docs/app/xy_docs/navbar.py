"""XY documentation navbar built from the official shared primitives."""

import reflex as rx
import reflex_components_internal as ui
from reflex_site_shared.components.docs_shell import (
    docs_book_demo_action,
    docs_navbar_frame,
)
from reflex_site_shared.components.inkeep import inkeep
from reflex_site_shared.components.marketing_button import button
from reflex_site_shared.views.sidebar import navbar_sidebar_button

_REFLEX_NAV_LINKS = (
    ("Overview", "/docs/"),
    ("Build with AI", "/docs/ai/overview/best-practices/"),
    ("Framework", "/docs/getting-started/introduction/"),
    ("Cloud", "/docs/hosting/deploy-quick-start/"),
)


def xy_docs_logo() -> rx.Component:
    """Render the Reflex XY documentation wordmark.

    Returns:
        The responsive Reflex XY wordmark SVG.
    """
    wordmark_fill = rx.color_mode_cond(light="#1B212A", dark="#FFFFFF")
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
            fill="#6E56CF",
            fill_rule="evenodd",
            clip_rule="evenodd",
        ),
        rx.el.path(d="M108 7V10H113H115V7H108Z", fill="#6E56CF"),
        rx.el.path(d="M115 7H118V1H115V7Z", fill="#6E56CF"),
        rx.el.path(d="M105 1V7H108V1H105Z", fill="#6E56CF"),
        rx.el.path(d="M110 10V16H113V10H110Z", fill="#6E56CF"),
        xmlns="http://www.w3.org/2000/svg",
        width="118",
        height="16",
        view_box="0 0 118 16",
        fill="none",
        aria_label="Reflex XY",
    )


def _menu_item(label: str, href: str, *, active: bool = False) -> rx.Component:
    """Render one desktop navbar item with the official treatment.

    Args:
        label: Visible item label.
        href: Destination URL.
        active: Whether to render the active section underline.

    Returns:
        Official-style navigation menu item.
    """
    active_class = (
        "shadow-[inset_0_-1px_0_0_var(--primary-10)] "
        "[&_button]:text-primary-10 [&_div]:text-primary-10"
        if active
        else ""
    )
    return ui.navigation_menu.item(
        rx.el.elements.a(
            button(label, size="sm", variant="ghost", native_button=False),
            href=href,
            class_name="no-underline",
        ),
        class_name=ui.cn(
            "hidden h-full items-center justify-center md:flex",
            active_class,
        ),
        custom_attrs={"role": "menuitem"},
    )


def _navigation_menu() -> rx.Component:
    """Render the official desktop controls and mobile drawer trigger.

    Returns:
        XY navigation menu.
    """
    return ui.navigation_menu.root(
        ui.navigation_menu.list(
            *(_menu_item(label, href) for label, href in _REFLEX_NAV_LINKS),
            _menu_item("XY", "/docs/xy/", active=True),
            class_name="m-0 flex h-full list-none flex-row items-center gap-2",
            custom_attrs={"role": "menubar"},
        ),
        ui.navigation_menu.list(
            ui.navigation_menu.item(
                inkeep(),
                unstyled=True,
                custom_attrs={"role": "menuitem"},
            ),
            ui.navigation_menu.item(
                docs_book_demo_action(),
                unstyled=True,
                class_name="hidden xl:flex",
                custom_attrs={"role": "menuitem"},
            ),
            ui.navigation_menu.item(
                navbar_sidebar_button(),
                unstyled=True,
                class_name="flex md:hidden",
                custom_attrs={"role": "menuitem"},
            ),
            class_name="m-0 flex h-full list-none flex-row items-center gap-2 lg:gap-4",
            custom_attrs={"role": "menubar"},
        ),
        unstyled=True,
        class_name="relative mx-auto flex h-full w-full flex-row items-center justify-between gap-6",
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
            href="/",
            class_name="mr-10 flex shrink-0 items-center gap-2.5 no-underline",
        ),
        _navigation_menu(),
    )


__all__ = ["xy_docs_logo", "xy_docs_navbar"]
