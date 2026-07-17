"""XY-specific Markdown rendering behavior."""

from __future__ import annotations

import json

import reflex as rx
from reflex_docgen.markdown import HeadingBlock, parse_document
from reflex_site_shared.docs.markdown import ReflexDocTransformer, _spans_to_plaintext
from reflex_site_shared.docs.models import DocsPage
from reflex_site_shared.views.hosting_banner import HostingBannerState

_HEADING_PRESENTATION = {
    1: ("h1", "4", "lg:text-4xl text-3xl font-semibold"),
    2: ("h2", "8", "lg:text-2xl text-xl font-semibold"),
    3: ("h3", "4", "lg:text-xl text-lg font-semibold"),
    4: ("h4", "2", "lg:text-base text-base font-semibold"),
}


def _heading_link(text: str, level: int) -> rx.Component:
    """Render a heading whose self-link stays on the current browser route."""
    normalized_level = min(max(level, 1), 4)
    tag, margin_top, class_name = _HEADING_PRESENTATION[normalized_level]
    slug = text.lower().replace(" ", "-")
    fragment = f"#{slug}"
    scroll_margin = rx.cond(
        HostingBannerState.is_banner_visible,
        "scroll-mt-[113px]",
        "scroll-mt-[77px]",
    )
    copy_href = (
        f"navigator.clipboard.writeText(new URL({json.dumps(fragment)}, window.location.href).href)"
    )

    return rx.link(
        rx.heading(
            text,
            id=slug,
            as_=tag,
            class_name=f"{class_name} " + scroll_margin + f" mt-{margin_top}",
        ),
        rx.icon(
            tag="link",
            size=18,
            class_name=(
                "!text-primary-11 invisible "
                "transition-[visibility_0.075s_ease-out] "
                f"group-hover:visible mt-{margin_top}"
            ),
        ),
        underline="none",
        href=fragment,
        on_click=rx.call_script(copy_href),
        class_name=(
            "flex flex-row items-center gap-2 hover:!text-primary-11 "
            "cursor-pointer mb-3 transition-colors group text-secondary-12"
        ),
    )


class XyDocsMarkdownTransformer(ReflexDocTransformer):
    """Render XY docs while keeping heading links independent of router state."""

    def heading(self, block: HeadingBlock) -> rx.Component:
        """Render one route-local Markdown heading."""
        return _heading_link(_spans_to_plaintext(block.children), block.level)


def render_xy_markdown_page(page: DocsPage) -> rx.Component:
    """Render one discovered XY documentation page."""
    source_path = page.source_path.resolve()
    document = parse_document(page.content)
    transformer = XyDocsMarkdownTransformer(
        virtual_filepath=str(source_path),
        filename=str(source_path),
    )
    return transformer.transform(document)


__all__ = ["XyDocsMarkdownTransformer", "render_xy_markdown_page"]
