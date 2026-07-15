"""The XY documentation app using the Reflex Docs layout verbatim."""

from __future__ import annotations

import reflex as rx

from .components import breadcrumbs, footer, navbar, page_toc, pager, sidebar
from .markdown import prepare_markdown
from .markdown_components import COMPONENT_MAP
from .navigation import PAGES, DocPage

BASE_STYLE = {
    "background_color": "var(--secondary-1)",
    "::selection": {
        "background_color": rx.color("accent", 5, True),
    },
    "font_family": "Instrument Sans",
    rx.heading: {
        "font_family": "Instrument Sans",
    },
    rx.divider: {"margin_bottom": "1em", "margin_top": "0.5em"},
    rx.vstack: {"align_items": "center"},
    rx.hstack: {"align_items": "center"},
    rx.markdown: {
        "background": "transparent",
    },
}

MARKDOWN_CLASS = " ".join(
    [
        "w-full bg-transparent",
        "[&_h1]:lg:text-4xl [&_h1]:text-3xl [&_h1]:font-semibold",
        "[&_h1]:text-secondary-12 [&_h1]:mb-3 [&_h1]:mt-4",
        "[&_h2]:lg:text-3xl [&_h2]:text-2xl [&_h2]:font-semibold",
        "[&_h2]:text-secondary-12 [&_h2]:mb-3 [&_h2]:mt-8",
        "[&_h3]:lg:text-xl [&_h3]:text-lg [&_h3]:font-semibold",
        "[&_h3]:text-secondary-12 [&_h3]:mb-3 [&_h3]:mt-4",
        "[&_h4]:text-base [&_h4]:font-semibold [&_h4]:text-secondary-12",
        "[&_h4]:mb-3 [&_h4]:mt-2",
        "[&_p]:font-normal [&_p]:text-secondary-11 [&_p]:mb-4 [&_p]:leading-7",
        "[&_a]:text-secondary-12 [&_a]:decoration-secondary-12 [&_a]:underline",
        "[&_li]:font-normal [&_li]:text-secondary-11 [&_li]:leading-7",
        "[&_ul]:mb-6 [&_ol]:mb-6",
        "[&_blockquote]:border-l-2 [&_blockquote]:border-primary-8",
        "[&_blockquote]:pl-4 [&_blockquote]:text-secondary-11",
        "[&_img]:rounded-lg [&_img]:border [&_img]:border-secondary-a4",
        "[&_img]:mb-2",
    ]
)


def doc_page(page: DocPage) -> rx.Component:
    """Render one XY Markdown file inside the transplanted Reflex Docs shell."""
    markdown, headings = prepare_markdown(page)
    show_right_sidebar = len([heading for heading in headings if heading.level in (2, 3)]) >= 2

    return rx.el.div(
        navbar(page),
        rx.el.main(
            rx.el.div(
                sidebar(page),
                class_name=(
                    "w-[19.5rem] shrink-0 hidden lg:block z-10 border-r "
                    "border-secondary-4 sticky left-0 top-[113px] "
                    "h-[calc(100vh-113px)] before:content-[''] before:absolute "
                    "before:top-0 before:bottom-0 before:right-0 before:w-[100vw] "
                    "before:bg-white-1 before:-z-10"
                ),
            ),
            rx.el.div(
                rx.el.div(
                    breadcrumbs(page),
                    class_name="px-0 pt-0 mb-[2rem] mt-[90px]",
                ),
                rx.el.div(
                    rx.el.article(
                        rx.markdown(
                            markdown,
                            component_map=COMPONENT_MAP,
                            class_name=MARKDOWN_CLASS,
                            use_math=True,
                            use_gfm=True,
                            use_raw=True,
                        ),
                        class_name="[&>div]:!p-0",
                    ),
                    pager(page),
                    footer(page),
                    class_name="lg:mt-0 h-auto",
                ),
                class_name=("flex-1 h-auto mx-auto lg:max-w-[52rem] px-4 overflow-y-auto"),
            ),
            (
                rx.el.div(
                    page_toc(page, headings),
                    class_name=("w-[240px] h-screen sticky top-0 shrink-0 hidden 2xl:block"),
                )
                if show_right_sidebar
                else rx.el.div(
                    class_name=("w-[180px] h-screen sticky top-0 shrink-0 hidden xl:block")
                )
            ),
            class_name=(
                "flex justify-center mx-auto mt-0 max-w-[108rem] h-full min-h-screen w-full"
            ),
        ),
        class_name="flex flex-col justify-center bg-secondary-1 w-full relative",
    )


app = rx.App(
    style=BASE_STYLE,
    stylesheets=["/fonts.css", "/custom-colors.css", "/tailwind-theme.css"],
    head_components=[
        rx.el.link(rel="icon", href="/favicon.svg"),
        rx.el.meta(name="theme-color", content="#151618"),
    ],
)

for page in PAGES:
    app.add_page(
        lambda page=page: doc_page(page),
        route=page.route,
        title=f"{page.title} · XY Docs",
        description=page.description,
        image="/social-card.svg",
    )
