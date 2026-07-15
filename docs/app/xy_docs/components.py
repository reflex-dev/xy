"""Reusable components for the xy documentation shell."""

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
SEARCH_SCRIPT = """
if (!window.xyDocsSearchBound) {
  window.xyDocsSearchBound = true;
  document.addEventListener('input', (event) => {
    if (!event.target.matches('[data-doc-search-input]')) return;
    const query = event.target.value.toLowerCase().trim();
    const results = document.querySelectorAll('[data-doc-search]');
    let visible = 0;
    results.forEach((result) => {
      const matches = !query || result.dataset.docSearch.includes(query);
      result.hidden = !matches;
      if (matches) visible += 1;
    });
    const empty = document.querySelector('[data-search-empty]');
    if (empty) empty.hidden = visible !== 0;
  });
}
"""


def icon_button(icon: str, label: str, **props) -> rx.Component:
    """Render a consistently styled icon-only button."""
    class_name = props.pop("class_name", "icon-button")
    return rx.el.button(
        rx.icon(icon, size=18),
        type="button",
        aria_label=label,
        class_name=class_name,
        **props,
    )


def github_icon(size: int = 18) -> rx.Component:
    """Render the GitHub mark without relying on a removed Lucide brand icon."""
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


def wordmark() -> rx.Component:
    """Render the xy Docs wordmark."""
    return rx.el.a(
        rx.el.span(
            rx.el.span("x", class_name="wordmark-x"),
            rx.el.span("y", class_name="wordmark-y"),
            class_name="wordmark-symbol",
        ),
        rx.el.span(class_name="wordmark-rule"),
        rx.el.span("Docs", class_name="wordmark-docs"),
        href="/",
        class_name="wordmark",
        aria_label="xy documentation home",
    )


def search_dialog() -> rx.Component:
    """Render the searchable documentation command dialog."""

    def result(page: DocPage) -> rx.Component:
        return rx.dialog.close(
            rx.el.a(
                rx.el.span(page.title, class_name="search-result-title"),
                rx.el.span(page.description, class_name="search-result-description"),
                href=page.route,
                class_name="search-result",
                custom_attrs={"data-doc-search": f"{page.title} {page.description}".casefold()},
            )
        )

    return rx.fragment(
        rx.script(SEARCH_SCRIPT),
        rx.dialog.root(
            rx.dialog.trigger(
                rx.el.button(
                    rx.icon("search", size=16),
                    rx.el.span("Search docs", class_name="search-label"),
                    rx.el.kbd("⌘ K"),
                    type="button",
                    class_name="search-trigger",
                )
            ),
            rx.dialog.content(
                rx.dialog.title("Search xy docs", class_name="search-title"),
                rx.el.div(
                    rx.icon("search", size=18),
                    rx.el.input(
                        placeholder="Search guides, APIs, and architecture…",
                        auto_focus=True,
                        class_name="search-input",
                        custom_attrs={"data-doc-search-input": ""},
                    ),
                    class_name="search-input-wrap",
                ),
                rx.el.div(
                    *[result(page) for page in PAGES],
                    rx.el.p(
                        "No documentation matched that search.",
                        class_name="search-empty",
                        hidden=True,
                        custom_attrs={"data-search-empty": ""},
                    ),
                    class_name="search-results",
                ),
                rx.dialog.close(icon_button("x", "Close search", class_name="dialog-close")),
                class_name="search-dialog",
            ),
        ),
    )


def navbar(page: DocPage) -> rx.Component:
    """Render the fixed top navigation."""
    api_active = page.source == "api-examples.md"
    benchmark_active = page.source in {"benchmark.md", "benchmark_metrics.md"}
    docs_active = not api_active and not benchmark_active
    return rx.el.header(
        rx.el.div(
            wordmark(),
            rx.el.nav(
                rx.el.a(
                    "Documentation",
                    href="/",
                    class_name="top-nav-link active" if docs_active else "top-nav-link",
                ),
                rx.el.a(
                    "API examples",
                    href="/api-examples/",
                    class_name="top-nav-link active" if api_active else "top-nav-link",
                ),
                rx.el.a(
                    "Benchmarks",
                    href="/benchmark/",
                    class_name="top-nav-link active" if benchmark_active else "top-nav-link",
                ),
                class_name="top-nav-links",
                aria_label="Primary navigation",
            ),
            rx.el.div(
                search_dialog(),
                rx.el.a(
                    github_icon(19),
                    rx.el.span("GitHub", class_name="github-label"),
                    href=GITHUB_URL,
                    target="_blank",
                    rel="noopener noreferrer",
                    aria_label="View xy on GitHub",
                    class_name="github-link",
                ),
                rx.color_mode.button(class_name="color-mode-button"),
                rx.el.div(mobile_navigation(page), class_name="mobile-nav"),
                class_name="navbar-actions",
            ),
            class_name="navbar-inner",
        ),
        class_name="navbar",
    )


def sidebar_link(page: DocPage, current_page: DocPage, *, close: bool = False) -> rx.Component:
    """Render one left-navigation link."""
    link = rx.el.a(
        page.title,
        href=page.route,
        class_name="sidebar-link active" if page == current_page else "sidebar-link",
    )
    return rx.drawer.close(link) if close else link


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
    """Render one Reflex-style collapsible sidebar section."""
    is_open = current_page in section.pages
    return rx.el.li(
        rx.el.a(
            SECTION_EYEBROWS[section.title],
            href=section.pages[0].route,
            class_name="sidebar-section-title",
        ),
        rx.el.details(
            rx.el.summary(
                rx.icon(section.icon, size=16),
                rx.el.span(section.title),
                rx.el.span(class_name="sidebar-summary-spacer"),
                rx.icon("chevron-down", size=15, class_name="sidebar-chevron"),
                class_name="sidebar-summary",
            ),
            rx.el.ul(
                rx.el.li(class_name="sidebar-guide"),
                *[
                    rx.el.li(
                        sidebar_link(page, current_page, close=mobile),
                        class_name="sidebar-leaf",
                    )
                    for page in section.pages
                ],
                class_name="sidebar-children",
            ),
            open=is_open,
            class_name="sidebar-details",
        ),
        class_name="sidebar-group",
    )


def sidebar(current_page: DocPage, *, mobile: bool = False) -> rx.Component:
    """Render the same two-tier sidebar structure used by Reflex Docs."""
    current_area = area_for_page(current_page)
    return rx.el.nav(
        rx.el.ul(
            *[
                rx.el.li(
                    rx.el.a(
                        rx.icon(area.icon, size=16),
                        rx.el.h3(area.title),
                        href=area.sections[0].pages[0].route,
                        class_name=(
                            "sidebar-area active" if area == current_area else "sidebar-area"
                        ),
                        aria_label=f"Navigate to {area.title}",
                    ),
                    class_name="sidebar-area-item",
                )
                for area in AREAS
            ],
            class_name="sidebar-areas",
        ),
        rx.el.ul(
            *[
                sidebar_section(section, current_page, mobile=mobile)
                for section in current_area.sections
            ],
            class_name="sidebar-groups",
        ),
        aria_label="Documentation navigation",
        class_name="mobile-sidebar" if mobile else "sidebar",
        id="docs-sidebar",
    )


def mobile_navigation(page: DocPage) -> rx.Component:
    """Render the sidebar as a bottom drawer on small screens."""
    return rx.drawer.root(
        rx.drawer.trigger(icon_button("menu", "Open documentation navigation")),
        rx.drawer.portal(
            rx.drawer.overlay(class_name="drawer-overlay"),
            rx.drawer.content(
                rx.el.div(class_name="drawer-handle"),
                rx.el.div(
                    rx.el.div(
                        rx.el.span("xy documentation", class_name="drawer-title"),
                        rx.drawer.close(icon_button("x", "Close navigation")),
                        class_name="drawer-header",
                    ),
                    sidebar(page, mobile=True),
                    class_name="drawer-body",
                ),
                class_name="mobile-drawer",
            ),
        ),
        direction="bottom",
    )


def breadcrumbs(page: DocPage) -> rx.Component:
    """Render compact page breadcrumbs."""
    section = next(section for section in SECTIONS if page in section.pages)
    return rx.el.nav(
        rx.el.a("Docs", href="/"),
        rx.icon("chevron-right", size=14),
        rx.el.span(section.title),
        rx.icon("chevron-right", size=14),
        rx.el.span(page.title, class_name="breadcrumb-current"),
        class_name="breadcrumbs",
        aria_label="Breadcrumbs",
    )


def page_toc(page: DocPage, headings: tuple[Heading, ...]) -> rx.Component:
    """Render a page-aware right-hand table of contents."""
    visible = tuple(heading for heading in headings if heading.level in (2, 3))
    return rx.el.aside(
        rx.el.h2("On this page"),
        rx.el.nav(
            *[
                rx.el.a(
                    heading.title,
                    href=f"#{heading.slug}",
                    class_name=("toc-link toc-link-nested" if heading.level == 3 else "toc-link"),
                )
                for heading in visible
            ],
            aria_label="On this page",
        ),
        rx.el.a(
            github_icon(15),
            "Edit this page",
            href=f"{GITHUB_URL}/edit/main/docs/{page.source}",
            target="_blank",
            rel="noopener noreferrer",
            class_name="edit-link",
        ),
        class_name="toc",
    )


def pager(page: DocPage) -> rx.Component:
    """Render previous and next page links."""
    previous, following = adjacent_pages(page)

    def pager_link(target: DocPage, direction: str) -> rx.Component:
        is_previous = direction == "Previous"
        return rx.el.a(
            rx.icon("arrow-left" if is_previous else "arrow-right", size=17),
            rx.el.span(
                rx.el.small(direction),
                rx.el.strong(target.title),
                class_name="pager-copy",
            ),
            href=target.route,
            class_name="pager-link previous" if is_previous else "pager-link next",
        )

    return rx.el.nav(
        pager_link(previous, "Previous") if previous else rx.el.span(),
        pager_link(following, "Next") if following else rx.el.span(),
        class_name="pager",
        aria_label="Previous and next pages",
    )


def footer() -> rx.Component:
    """Render the compact documentation footer."""
    return rx.el.footer(
        rx.el.span("xy is open source under Apache-2.0."),
        rx.el.div(
            rx.el.a("GitHub", href=GITHUB_URL, target="_blank"),
            rx.el.a(
                "Issues",
                href=f"{GITHUB_URL}/issues",
                target="_blank",
            ),
            class_name="footer-links",
        ),
        class_name="docs-footer",
    )
