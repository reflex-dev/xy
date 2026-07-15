"""The xy documentation Reflex application."""

from __future__ import annotations

import reflex as rx

from .code import code_block_markdown
from .components import breadcrumbs, footer, navbar, page_toc, pager, sidebar
from .markdown import prepare_markdown
from .navigation import PAGES, DocPage


def doc_page(page: DocPage) -> rx.Component:
    """Render a Markdown document inside the shared docs shell."""
    markdown, headings = prepare_markdown(page)
    return rx.el.div(
        navbar(page),
        rx.el.div(
            sidebar(page),
            rx.el.main(
                breadcrumbs(page),
                rx.markdown(
                    markdown,
                    component_map={"pre": code_block_markdown},
                    class_name="doc-markdown",
                    use_math=True,
                    use_gfm=True,
                    use_raw=True,
                ),
                pager(page),
                footer(),
                class_name="docs-main",
            ),
            page_toc(page, headings),
            class_name="docs-grid",
        ),
        class_name="site-shell",
    )


app = rx.App(
    stylesheets=["/styles.css"],
    head_components=[
        rx.el.link(rel="icon", href="/favicon.svg"),
        rx.el.meta(name="theme-color", content="#111014"),
    ],
)

for page in PAGES:
    app.add_page(
        lambda page=page: doc_page(page),
        route=page.route,
        title=f"{page.title} · xy Docs",
        description=page.description,
        image="/social-card.svg",
    )
