"""XY-specific Markdown rendering behavior."""

from __future__ import annotations

import json
from dataclasses import replace

import reflex as rx
from reflex_docgen.markdown import HeadingBlock, parse_document
from reflex_site_shared.docs.markdown import ReflexDocTransformer, _spans_to_plaintext
from reflex_site_shared.docs.models import DocsPage
from reflex_site_shared.views.hosting_banner import HostingBannerState

from xy_docs.api_reference import (
    API_REFERENCE_HEADING,
    component_api_paths,
    component_api_references,
    component_page_api,
    split_faq_section,
)
from xy_docs.examples import chart_example_demo

# A demo fence may split its hardcoded data from the chart code with this
# divider on its own line. Everything above is shown in the "Data" tab, the rest
# in "Code"; the whole fence still executes for the preview (leading data is
# plain literals, so it is valid before the imports below the divider).
_DEMO_DATA_DIVIDER = "# --- chart ---"
_DEMO_DATA_TAB_LINE_THRESHOLD = 10


def _split_demo_data(content: str) -> tuple[str | None, str]:
    """Split a demo fence into (data, code) around ``_DEMO_DATA_DIVIDER``.

    Returns ``(None, content)`` when the divider is absent, so demos without a
    dedicated data section keep the two-tab Preview/Code layout. A marked data
    section must exceed ``_DEMO_DATA_TAB_LINE_THRESHOLD`` nonblank lines to earn
    its own tab; shorter data stays with the chart code.
    """
    lines = content.split("\n")
    for index, line in enumerate(lines):
        if line.strip() == _DEMO_DATA_DIVIDER:
            data = "\n".join(lines[:index]).strip("\n")
            code = "\n".join(lines[index + 1 :]).strip("\n")
            data_line_count = sum(bool(line.strip()) for line in data.splitlines())
            if data_line_count > _DEMO_DATA_TAB_LINE_THRESHOLD:
                return (data or None), code
            return None, "\n\n".join(part for part in (data, code) if part)
    return None, content


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

    def _render_demo(self, content: str, flags: set[str]) -> rx.Component:
        """Render public chart demos with consistent Preview/Code/Data tabs."""
        component_id = next(
            (flag.split("=", 1)[1] for flag in flags if flag.startswith("id=")),
            None,
        )

        if "demo-only" in flags:
            return super()._render_demo(content, flags)

        preview = (
            self._exec_and_get_last_callable(content)
            if "exec" in flags
            else eval(content, self.env, self.env)
        )

        data, code = _split_demo_data(content)
        return chart_example_demo(
            code,
            preview,
            component_id=component_id,
            data=data,
        )


def render_xy_markdown_page(page: DocsPage) -> rx.Component:
    """Render one discovered XY documentation page."""
    source_path = page.source_path.resolve()

    def _render(markdown_text: str) -> rx.Component:
        transformer = XyDocsMarkdownTransformer(
            virtual_filepath=str(source_path),
            filename=str(source_path),
        )
        return transformer.transform(parse_document(markdown_text))

    component_paths = component_api_paths(page.metadata)
    if not component_paths:
        return _render(page.content)
    # The generated API section renders between the body and any FAQ, matching
    # the per-page Markdown and llms-full.txt order (append_component_api_markdown).
    body, faq = split_faq_section(page.content)
    references = component_api_references(component_paths)
    return rx.fragment(
        _render(body),
        _heading_link(API_REFERENCE_HEADING, 2),
        component_page_api(references),
        *((_render(faq),) if faq is not None else ()),
    )


def page_with_api_reference_toc(page: DocsPage) -> DocsPage:
    """Include an auto-generated API section in the shared page TOC.

    The rendered tables remain generated components; this synthetic Markdown
    heading is used only by the shared layout's source-based TOC parser.
    """
    if not component_api_paths(page.metadata):
        return page
    return replace(
        page,
        content=f"{page.content}\n\n## {API_REFERENCE_HEADING}",
    )


__all__ = [
    "XyDocsMarkdownTransformer",
    "page_with_api_reference_toc",
    "render_xy_markdown_page",
]
