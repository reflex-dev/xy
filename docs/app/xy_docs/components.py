"""XY documentation shell ported from the Reflex Docs component structure."""

from __future__ import annotations

import reflex as rx

from .markdown import Heading
from .navigation import (
    AREAS,
    PAGES,
    SECTIONS,
    DocPage,
    NavSection,
    adjacent_pages,
    area_for_page,
)

GITHUB_URL = "https://github.com/reflex-dev/xy"

SCROLLABLE_SIDEBAR = """
function scrollToActiveSidebarLink() {
  const sidebarContainer = document.getElementById('sidebar-container');
  if (!sidebarContainer) return;
  const currentPath = window.location.pathname.replace(/\\/+$/, '') + '/';
  const activeLink =
    sidebarContainer.querySelector(`a[href="${currentPath}"]`) ||
    sidebarContainer.querySelector(`a[href="${currentPath.slice(0, -1)}"]`);
  if (!activeLink) return;
  const scrollableParent =
    activeLink.closest('[class*="overflow-y-scroll"]') || sidebarContainer;
  const linkRect = activeLink.getBoundingClientRect();
  const containerRect = scrollableParent.getBoundingClientRect();
  const scrollTop =
    scrollableParent.scrollTop +
    (linkRect.top - containerRect.top) -
    containerRect.height / 2 +
    linkRect.height / 2;
  scrollableParent.scrollTo({top: scrollTop, behavior: 'instant'});
}
setTimeout(scrollToActiveSidebarLink, 100);
window.addEventListener('popstate', () => setTimeout(scrollToActiveSidebarLink, 100));
document.addEventListener('click', (event) => {
  const link = event.target.closest('#sidebar-container a[href]');
  if (link && !link.getAttribute('href')?.startsWith('http')) {
    setTimeout(scrollToActiveSidebarLink, 200);
  }
});
"""


def github_icon(size: int = 16) -> rx.Component:
    """Render the GitHub mark."""
    return rx.el.svg(
        rx.el.path(
            d=(
                "M12 .7a11.5 11.5 0 0 0-3.64 22.41c.58.11.79-.25.79-.56v-2.23"
                "c-3.23.7-3.91-1.56-3.91-1.56-.53-1.36-1.3-1.72-1.3-1.72-1.06"
                "-.72.08-.7.08-.7 1.17.08 1.79 1.2 1.79 1.2 1.04 1.78 2.74 1.27"
                " 3.41.97.1-.75.4-1.27.73-1.56-2.58-.29-5.29-1.29-5.29-5.69"
                " 0-1.26.45-2.3 1.2-3.11-.12-.3-.52-1.53.11-3.19 0 0 .98-.31"
                " 3.16 1.19a10.9 10.9 0 0 1 5.75 0C17.22 5.4 18.2 5.7 18.2 5.7"
                "c.63 1.66.23 2.89.11 3.19.75.81 1.2 1.85 1.2 3.11 0 4.41"
                "-2.72 5.39-5.31 5.68.41.36.77 1.05.77 2.13v3.16c0 .31.21.68.8.56"
                "A11.5 11.5 0 0 0 12 .7Z"
            ),
            fill="currentColor",
        ),
        width=str(size),
        height=str(size),
        view_box="0 0 24 24",
        aria_hidden="true",
    )


def announcement_banner() -> rx.Component:
    """Use the same fixed announcement-bar geometry as Reflex Docs."""
    return rx.el.div(
        rx.el.div(
            rx.el.a(
                rx.el.div(
                    rx.el.img(
                        src=("https://web.reflex-assets.dev/common/light/squares_banner.svg"),
                        alt="",
                        class_name=("pointer-events-none absolute -left-[16rem] max-lg:hidden"),
                    ),
                    rx.el.div(
                        rx.el.span(
                            "New",
                            class_name=(
                                "items-center font-[525] px-2.5 h-7 rounded-lg "
                                "text-sm text-white z-[1] max-lg:hidden lg:inline-flex "
                                "border border-white/16"
                            ),
                        ),
                        rx.el.span(
                            "XY documentation is now built with Reflex",
                            class_name=("text-white font-[525] text-sm text-nowrap inline-block"),
                        ),
                        rx.el.span(
                            class_name=(
                                "w-px h-7 bg-gradient-to-b from-transparent "
                                "via-white/24 to-transparent max-lg:hidden"
                            ),
                        ),
                        rx.el.span(
                            "View source",
                            rx.icon("arrow-right", size=15),
                            class_name=(
                                "max-lg:hidden text-white hover:text-primary-10 "
                                "flex items-center gap-1 text-sm font-[525]"
                            ),
                        ),
                        class_name="flex flex-row items-center md:gap-4 gap-2",
                    ),
                    rx.el.img(
                        src=("https://web.reflex-assets.dev/common/light/squares_banner.svg"),
                        alt="",
                        class_name=("pointer-events-none absolute -right-[16rem] max-lg:hidden"),
                    ),
                    class_name="flex flex-row items-center relative",
                ),
                href=GITHUB_URL,
                target="_blank",
                rel="noopener noreferrer",
                class_name=("flex justify-start md:justify-center md:col-start-2 max-w-[73rem]"),
            ),
            rx.el.button(
                rx.icon("x", size=16),
                aria_label="Close banner",
                type="button",
                class_name=(
                    "cursor-pointer hover:text-white/80 transition-colors text-white "
                    "z-10 size-10 flex items-center justify-center shrink-0 "
                    "md:col-start-3 justify-self-end ml-auto"
                ),
            ),
            class_name=(
                "px-5 lg:px-0 w-screen min-h-[2rem] lg:h-10 flex md:grid "
                "md:grid-cols-[1fr_auto_1fr] items-center bg-secondary-12 "
                "dark:bg-[#6550B9] gap-4 overflow-hidden relative lg:py-0 py-2 "
                "max-w-full group"
            ),
        ),
    )


def logo() -> rx.Component:
    """Render an XY-specific wordmark inside the Reflex navbar slot."""
    return rx.el.a(
        rx.el.span(
            "XY",
            class_name=(
                "font-mono text-[1.25rem] leading-none font-bold tracking-[-0.08em] "
                "text-secondary-12"
            ),
        ),
        rx.el.span(
            "DOCS",
            class_name=(
                "font-mono text-[1.05rem] leading-none font-bold tracking-[-0.04em] text-primary-10"
            ),
        ),
        href="/",
        class_name=("flex flex-row gap-2.5 items-center shrink-0 mr-10 no-underline w-36"),
        aria_label="XY documentation home",
    )


def search_dialog() -> rx.Component:
    """Render documentation search in the same navbar position as Reflex Docs."""

    def result(page: DocPage) -> rx.Component:
        return rx.dialog.close(
            rx.el.a(
                rx.el.span(page.title, class_name="text-sm font-[525] text-secondary-12"),
                rx.el.span(
                    page.description,
                    class_name="text-xs text-secondary-10 line-clamp-1",
                ),
                href=page.route,
                class_name=(
                    "flex flex-col gap-0.5 rounded-md px-3 py-2 no-underline hover:bg-secondary-3"
                ),
            )
        )

    return rx.dialog.root(
        rx.dialog.trigger(
            rx.el.button(
                rx.icon("search", size=17),
                type="button",
                aria_label="Search documentation",
                class_name=(
                    "size-9 flex items-center justify-center rounded-lg border border-secondary-5 "
                    "bg-secondary-1 text-secondary-11 shadow-small hover:bg-secondary-3 "
                    "hover:text-secondary-12 transition-colors cursor-pointer"
                ),
            )
        ),
        rx.dialog.content(
            rx.el.div(
                rx.icon("search", size=18),
                rx.el.input(
                    placeholder="Search XY docs",
                    class_name=(
                        "w-full bg-transparent outline-none text-sm text-secondary-12 "
                        "placeholder:text-secondary-9"
                    ),
                ),
                class_name=("flex items-center gap-2 border-b border-secondary-4 px-4 py-3"),
            ),
            rx.el.div(
                *[result(page) for page in PAGES],
                class_name="flex max-h-[60vh] flex-col gap-1 overflow-y-auto p-2",
            ),
            class_name=(
                "p-0 overflow-hidden border border-secondary-5 bg-secondary-1 "
                "rounded-xl shadow-xl max-w-[36rem]"
            ),
        ),
    )


def navbar_link(label: str, href: str, active: bool) -> rx.Component:
    """Render one Reflex navbar menu item."""
    active_class = (
        "shadow-[inset_0_-1px_0_0_var(--primary-10)] text-primary-10"
        if active
        else "text-secondary-12"
    )
    return rx.el.a(
        label,
        href=href,
        class_name=(
            "md:flex hidden h-full items-center justify-center px-3 text-sm font-[525] "
            f"no-underline hover:text-primary-10 transition-colors {active_class}"
        ),
    )


def navbar(page: DocPage) -> rx.Component:
    """Port the Reflex Docs fixed navbar, substituting XY routes and branding."""
    area = area_for_page(page)
    return rx.el.div(
        announcement_banner(),
        rx.el.header(
            rx.el.div(
                logo(),
                rx.el.nav(
                    rx.el.div(
                        navbar_link("Overview", "/", page.route == "/"),
                        navbar_link("Guides", "/styling/", area.title == "Learn"),
                        navbar_link(
                            "Architecture",
                            "/design-dossier/",
                            area.title == "Architecture",
                        ),
                        navbar_link(
                            "Benchmarks",
                            "/benchmark/",
                            area.title == "Performance",
                        ),
                        class_name="flex flex-row items-center gap-2 m-0 h-full",
                    ),
                    rx.el.div(
                        rx.el.a(
                            github_icon(),
                            "XY",
                            href=GITHUB_URL,
                            target="_blank",
                            rel="noopener noreferrer",
                            class_name=(
                                "md:flex hidden items-center justify-center gap-2 h-9 "
                                "w-[66px] rounded-lg "
                                "text-sm font-[525] text-secondary-12 no-underline "
                                "hover:bg-secondary-3"
                            ),
                        ),
                        search_dialog(),
                        rx.el.a(
                            "Get Started",
                            href="/",
                            class_name=(
                                "xl:flex hidden h-9 w-[102px] items-center justify-center "
                                "rounded-lg bg-primary-9 text-sm font-[525] text-white "
                                "no-underline hover:bg-primary-10 transition-colors"
                            ),
                        ),
                        rx.el.div(mobile_navigation(page), class_name="lg:hidden flex"),
                        class_name="flex flex-row lg:gap-4 gap-2 h-full items-center",
                    ),
                    class_name=(
                        "relative flex w-full items-center h-full justify-between gap-6 "
                        "mx-auto flex-row"
                    ),
                    aria_label="Primary navigation",
                ),
                class_name=(
                    "relative flex w-full items-center h-full justify-between gap-6 "
                    "mx-auto flex-row max-w-[108rem]"
                ),
            ),
            class_name=(
                "w-full max-full h-[4.5rem] mx-auto flex flex-row items-center "
                "3xl:px-16 px-6 backdrop-blur-[16px] "
                "shadow-[0_-2px_2px_1px_rgba(0,0,0,0.02),0_1px_1px_0_rgba(0,0,0,0.08),"
                "0_4px_8px_0_rgba(0,0,0,0.03),0_0_0_1px_#FFF_inset] dark:shadow-none "
                "dark:border-b dark:border-secondary-4 bg-gradient-to-b "
                "from-secondary-2 to-secondary-1"
            ),
        ),
        class_name="flex flex-col w-full top-0 z-[9999] fixed self-center",
    )


def sidebar_leaf(page: DocPage, current_page: DocPage, *, mobile: bool) -> rx.Component:
    """Port the active and inactive Reflex Docs leaf markup."""
    active = page == current_page
    link = rx.el.a(
        (
            rx.el.div(
                class_name=(
                    "absolute left-0 top-1/2 -translate-y-1/2 w-full h-8 rounded-lg "
                    "bg-secondary-3 z-[-1]"
                )
            )
            if active
            else rx.fragment()
        ),
        rx.el.div(
            (
                rx.el.div(
                    class_name=(
                        "absolute left-0 -top-1 -bottom-1 w-px bg-primary-10 pointer-events-none"
                    )
                )
                if active
                else rx.fragment()
            ),
            rx.el.p(
                page.title,
                class_name=(
                    "m-0 text-sm text-primary-10 font-[525] transition-color pl-4"
                    if active
                    else (
                        "m-0 text-sm text-secondary-11 hover:text-secondary-12 "
                        "transition-color w-full font-[525]"
                    )
                ),
            ),
            class_name=(
                "relative ml-[3rem] max-w-[14rem] h-8 flex items-center"
                if active
                else "relative pl-4 h-8 flex items-center"
            ),
        ),
        href=page.route,
        class_name=("block w-full relative" if active else "block w-full ml-[3rem] no-underline"),
    )
    return rx.drawer.close(link) if mobile else link


def sidebar_group(
    section: NavSection,
    current_page: DocPage,
    *,
    mobile: bool,
) -> rx.Component:
    """Render a collapsible Reflex Docs sidebar group."""
    is_open = current_page in section.pages
    return rx.el.li(
        rx.el.details(
            rx.el.summary(
                rx.icon(section.icon, size=16, class_name="mr-4"),
                rx.el.p(section.title, class_name="m-0 text-sm font-[525]"),
                rx.el.span(class_name="flex-grow"),
                rx.icon(
                    "chevron-down",
                    size=16,
                    class_name=("size-4 group-open/details:rotate-180 transition-transform"),
                ),
                class_name=(
                    "!px-0 m-0 flex items-center justify-start !ml-[2.5rem] "
                    "!bg-transparent !py-1 !pr-0 w-[calc(100%-2.5rem)] "
                    "!text-secondary-11 hover:!text-secondary-12 transition-color "
                    "group xl:max-w-[14rem] cursor-pointer list-none "
                    "[&::-webkit-details-marker]:hidden [&::marker]:hidden"
                ),
            ),
            rx.el.ul(
                rx.el.li(
                    class_name=(
                        "m-0 p-0 absolute left-[3rem] top-0 bottom-0 w-px "
                        "bg-secondary-4 z-[-1] pointer-events-none !rounded-none list-none"
                    )
                ),
                *[
                    rx.el.li(
                        sidebar_leaf(page, current_page, mobile=mobile),
                        class_name=("m-0 p-0 !overflow-visible w-full relative list-none"),
                    )
                    for page in section.pages
                ],
                class_name=(
                    "!my-1 p-0 flex flex-col items-start gap-1 list-none "
                    "!bg-transparent !rounded-none !shadow-none relative"
                ),
            ),
            open=is_open,
            class_name="group/details m-0 p-0 w-full !bg-transparent border-none",
        ),
        class_name="m-0 p-0 border-none w-full !bg-transparent list-none",
    )


SECTION_EYEBROWS = {
    "Get started": "Onboarding",
    "Matplotlib": "Compatibility",
    "Performance": "Benchmarks",
    "Architecture": "Architecture",
    "Project": "Project",
}


def sidebar_section(
    section: NavSection,
    current_page: DocPage,
    *,
    mobile: bool,
) -> rx.Component:
    """Render the uppercase section title and its groups."""
    return rx.el.li(
        rx.el.a(
            rx.el.h2(
                SECTION_EYEBROWS[section.title],
                class_name=(
                    "m-0 font-mono text-secondary-12 hover:text-primary-10 "
                    "dark:hover:text-primary-9 uppercase text-[0.8125rem] "
                    "leading-6 font-medium"
                ),
            ),
            href=section.pages[0].route,
            class_name=("h-8 mb-2 flex items-center justify-start ml-[2.5rem] no-underline"),
        ),
        rx.el.ul(
            sidebar_group(section, current_page, mobile=mobile),
            class_name=(
                "m-0 ml-0 p-0 pl-0 w-full !bg-transparent !shadow-none "
                "rounded-[0px] flex flex-col list-none gap-0 relative"
            ),
        ),
        class_name="m-0 p-0 flex flex-col items-start ml-0 w-full list-none",
    )


def sidebar_category(area, current_page: DocPage) -> rx.Component:
    """Render a top-level category entry using Reflex Docs markup."""
    active = area == area_for_page(current_page)
    return rx.el.li(
        rx.el.a(
            (
                rx.el.div(
                    class_name=(
                        "absolute left-0 top-1/2 -translate-y-1/2 w-full h-8 "
                        "rounded-lg bg-secondary-3 z-[-1]"
                    )
                )
                if active
                else rx.fragment()
            ),
            rx.el.div(
                rx.icon(area.icon, size=16),
                rx.el.h3(area.title, class_name="m-0 w-full font-[525]"),
                class_name=(
                    "cursor-pointer flex flex-row justify-start items-center gap-2.5 "
                    "ml-[3rem] text-sm h-8 "
                    + (
                        "text-primary-10 hover:text-primary-10"
                        if active
                        else "text-secondary-11 hover:text-secondary-12"
                    )
                ),
            ),
            href=area.sections[0].pages[0].route,
            class_name="block w-full relative no-underline",
            aria_label=f"Navigate to {area.title}",
        ),
        class_name="m-0 p-0 w-full relative list-none",
    )


def sidebar(current_page: DocPage, *, mobile: bool = False) -> rx.Component:
    """Render the Reflex Docs sidebar structure with XY navigation data."""
    current_area = area_for_page(current_page)
    content = rx.el.div(
        rx.el.ul(
            *[sidebar_category(area, current_page) for area in AREAS],
            class_name="flex flex-col items-start gap-2 w-full list-none m-0 p-0",
        ),
        rx.el.ul(
            *[
                sidebar_section(section, current_page, mobile=mobile)
                for section in current_area.sections
            ],
            class_name=("m-0 p-0 flex flex-col items-start gap-8 w-full list-none list-style-none"),
        ),
        class_name=(
            "flex flex-col pb-24 gap-8 items-start h-full pt-8 pr-4 scroll-p-4 "
            "overflow-y-scroll overflow-x-hidden hidden-scrollbar w-full 3xl:pl-0 pl-6"
        ),
    )
    return rx.el.nav(
        content,
        on_mount=rx.call_script(SCROLLABLE_SIDEBAR),
        id="sidebar-container",
        class_name="flex justify-end w-full h-full",
        aria_label="Documentation navigation",
    )


def mobile_navigation(page: DocPage) -> rx.Component:
    """Render the Reflex-style mobile sidebar drawer."""
    return rx.drawer.root(
        rx.drawer.trigger(
            rx.el.button(
                rx.icon("menu", size=18),
                type="button",
                aria_label="Open documentation navigation",
                class_name=(
                    "size-9 flex items-center justify-center rounded-lg border "
                    "border-secondary-5 bg-secondary-1 text-secondary-11"
                ),
            )
        ),
        rx.drawer.portal(
            rx.drawer.overlay(class_name="fixed inset-0 bg-black/40 z-[10000]"),
            rx.drawer.content(
                rx.el.div(
                    rx.el.div(
                        rx.el.span("XY Docs", class_name="font-semibold text-secondary-12"),
                        rx.drawer.close(
                            rx.el.button(
                                rx.icon("x", size=18),
                                type="button",
                                aria_label="Close navigation",
                                class_name="size-9 flex items-center justify-center",
                            )
                        ),
                        class_name=(
                            "h-14 flex items-center justify-between px-5 border-b "
                            "border-secondary-4"
                        ),
                    ),
                    rx.el.div(
                        sidebar(page, mobile=True),
                        class_name="h-[calc(85vh-3.5rem)]",
                    ),
                    class_name="h-full bg-secondary-1",
                ),
                class_name="fixed inset-x-0 bottom-0 h-[85vh] rounded-t-xl z-[10001]",
            ),
        ),
        direction="bottom",
    )


def breadcrumbs(page: DocPage) -> rx.Component:
    """Render the Reflex Docs breadcrumb row."""
    section = next(section for section in SECTIONS if page in section.pages)
    return rx.el.div(
        rx.el.div(
            rx.el.a(
                section.title,
                href=section.pages[0].route,
                class_name=(
                    "min-h-8 flex items-center text-sm font-[525] text-secondary-12 "
                    "hover:text-primary-10 no-underline"
                ),
            ),
            rx.icon("chevron-right", size=16, class_name="text-secondary-11"),
            rx.el.a(
                page.title,
                href=page.route,
                class_name=(
                    "min-h-8 flex items-center text-sm font-[525] text-secondary-11 "
                    "truncate no-underline"
                ),
            ),
            class_name="flex flex-row items-center gap-4 overflow-hidden",
        ),
        rx.el.div(
            rx.el.a(
                rx.icon("copy", size=16),
                href=f"{GITHUB_URL}/blob/main/docs/{page.source}",
                target="_blank",
                rel="noopener noreferrer",
                aria_label="View Markdown source",
                class_name=(
                    "flex items-center justify-center px-2.5 h-8 border "
                    "border-secondary-5 border-r-0 rounded-l-md text-secondary-11 "
                    "hover:text-secondary-12 hover:bg-secondary-3"
                ),
            ),
            rx.el.button(
                rx.icon("chevron-down", size=14),
                type="button",
                aria_label="Copy page options",
                class_name=(
                    "flex items-center justify-center px-1.5 h-8 border "
                    "border-secondary-5 rounded-r-md text-secondary-11 "
                    "hover:text-secondary-12 hover:bg-secondary-3 cursor-pointer"
                ),
            ),
            class_name="hidden lg:flex flex-row items-center shrink-0",
        ),
        class_name=(
            "relative z-10 flex flex-row justify-between items-center gap-4 "
            "border-secondary-4 mt-[139px] lg:p-0 border-b lg:border-none "
            "w-full max-lg:py-2"
        ),
        aria_label="Breadcrumbs",
    )


def page_toc(page: DocPage, headings: tuple[Heading, ...]) -> rx.Component:
    """Render the Reflex Docs right-hand table of contents."""
    visible = tuple(heading for heading in headings if heading.level in (2, 3))
    return rx.el.nav(
        rx.el.div(
            rx.el.p(
                rx.icon("align-left", size=14, class_name="text-secondary-12"),
                "On This Page",
                class_name=(
                    "text-sm h-8 flex items-center gap-1.5 justify-start "
                    "font-[525] text-secondary-12"
                ),
            ),
            rx.el.ul(
                *[
                    rx.el.li(
                        rx.el.a(
                            heading.title,
                            href=f"{page.route}#{heading.slug}",
                            class_name=(
                                "text-sm font-[525] text-secondary-11 py-1 "
                                "hover:text-secondary-12 transition-colors line-clamp-2 "
                                + ("pl-8" if heading.level == 3 else "pl-4")
                            ),
                        )
                    )
                    for heading in visible
                ],
                id="toc-navigation",
                class_name=(
                    "flex flex-col gap-y-1 list-none "
                    "shadow-[1.5px_0_0_0_var(--secondary-4)_inset] "
                    "max-h-[60vh] overflow-y-auto scroll-mask-y-10 "
                    "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden m-0 p-0"
                ),
            ),
            rx.el.a(
                rx.icon("pencil", size=15),
                "Edit this page",
                href=f"{GITHUB_URL}/edit/main/docs/{page.source}",
                target="_blank",
                rel="noopener noreferrer",
                class_name=(
                    "mt-2 pl-0 text-sm font-[525] text-secondary-11 "
                    "hover:text-secondary-12 flex items-center gap-2 no-underline"
                ),
            ),
            class_name="flex flex-col justify-start gap-y-4 overflow-y-auto sticky top-4",
        ),
        class_name="w-full h-full mt-[146px]",
        aria_label="On this page",
    )


def pager(page: DocPage) -> rx.Component:
    """Render previous/next links with the Reflex Docs spacing and typography."""
    previous, following = adjacent_pages(page)

    def item(target: DocPage, direction: str) -> rx.Component:
        previous_item = direction == "Back"
        return rx.el.div(
            rx.el.a(
                (rx.icon("arrow-left", size=16) if previous_item else rx.fragment()),
                direction,
                (rx.icon("arrow-right", size=16) if not previous_item else rx.fragment()),
                href=target.route,
                class_name=(
                    "py-0.5 rounded-lg font-small text-secondary-9 "
                    "hover:!text-secondary-11 transition-color flex items-center gap-2 "
                    "no-underline"
                ),
            ),
            rx.el.p(
                target.title,
                class_name="font-smbold text-secondary-12 m-0",
            ),
            class_name=(
                "flex flex-col justify-start gap-1 items-end"
                if not previous_item
                else "flex flex-col justify-start gap-1"
            ),
        )

    return rx.el.nav(
        item(previous, "Back") if previous else rx.fragment(),
        rx.el.span(class_name="flex-grow"),
        item(following, "Next") if following else rx.fragment(),
        class_name="flex flex-row gap-2 mt-8 lg:mt-10 mb-6 lg:mb-12",
        aria_label="Previous and next pages",
    )


def footer(page: DocPage) -> rx.Component:
    """Render a compact footer using the Reflex Docs borders and type scale."""
    return rx.el.footer(
        rx.el.div(
            rx.el.p(
                "Did you find this useful?",
                class_name="font-small text-secondary-11 m-0",
            ),
            rx.el.div(
                rx.el.a(
                    "Raise an issue",
                    href=f"{GITHUB_URL}/issues/new",
                    target="_blank",
                    class_name=(
                        "px-3 py-1 rounded-full border border-secondary-5 "
                        "font-small text-secondary-9 hover:text-secondary-11 no-underline"
                    ),
                ),
                rx.el.a(
                    "Edit this page",
                    href=f"{GITHUB_URL}/edit/main/docs/{page.source}",
                    target="_blank",
                    class_name=(
                        "px-3 py-1 rounded-full border border-secondary-5 "
                        "font-small text-secondary-9 hover:text-secondary-11 no-underline"
                    ),
                ),
                class_name="flex flex-row items-center gap-2",
            ),
            class_name=(
                "flex flex-row justify-between items-center border-secondary-4 border-y py-8 w-full"
            ),
        ),
        rx.el.div(
            rx.el.span(
                "XY is open source under Apache-2.0.",
                class_name="font-small text-secondary-9",
            ),
            rx.el.a(
                github_icon(),
                "GitHub",
                href=GITHUB_URL,
                target="_blank",
                class_name=("font-small text-secondary-11 flex items-center gap-2 no-underline"),
            ),
            class_name="flex flex-row items-center justify-between py-8",
        ),
        class_name="flex flex-col w-full",
    )
