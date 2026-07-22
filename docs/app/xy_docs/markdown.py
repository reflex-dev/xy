"""XY-specific Markdown rendering behavior."""

from __future__ import annotations

import json

import reflex as rx
from reflex_docgen.markdown import HeadingBlock, parse_document
from reflex_site_shared.components.blocks.demo import doccode
from reflex_site_shared.docs.markdown import ReflexDocTransformer, _spans_to_plaintext
from reflex_site_shared.docs.models import DocsPage
from reflex_site_shared.views.hosting_banner import HostingBannerState

from xy_docs.examples import chart_example_demo

# A demo fence may split its hardcoded data from the chart code with this
# divider on its own line. Everything above is shown in the "Data" tab, the rest
# in "Code"; the whole fence still executes for the preview (leading data is
# plain literals, so it is valid before the imports below the divider).
_DEMO_DATA_DIVIDER = "# --- chart ---"


def _split_demo_data(content: str) -> tuple[str | None, str]:
    """Split a demo fence into (data, code) around ``_DEMO_DATA_DIVIDER``.

    Returns ``(None, content)`` when the divider is absent, so demos without a
    dedicated data section keep the two-tab Preview/Code layout.
    """
    lines = content.split("\n")
    for index, line in enumerate(lines):
        if line.strip() == _DEMO_DATA_DIVIDER:
            data = "\n".join(lines[:index]).strip("\n")
            code = "\n".join(lines[index + 1 :]).strip("\n")
            return (data or None), code
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
        """Render styling demos on a consistent chart surface."""
        component_id = next(
            (flag.split("=", 1)[1] for flag in flags if flag.startswith("id=")),
            None,
        )

        if "preview-code" not in flags:
            normalized_path = "/" + self.virtual_filepath.replace("\\", "/").lstrip("/")
            uses_plain_chart_surface = "/docs/styling/" in normalized_path
            if not uses_plain_chart_surface:
                return super()._render_demo(content, flags)

        preview = (
            self._exec_and_get_last_callable(content)
            if "exec" in flags
            else eval(content, self.env, self.env)
        )

        if "preview-code" not in flags:
            return rx.el.div(
                rx.el.div(
                    preview,
                    class_name=(
                        "w-full overflow-hidden rounded-xl border border-secondary-4 "
                        "bg-white [--chart-bg:#ffffff] "
                        "dark:bg-black dark:[--chart-bg:#000000]"
                    ),
                ),
                doccode(content),
                id=component_id,
                class_name="flex w-full flex-col gap-4 py-4",
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
    document = parse_document(page.content)
    transformer = XyDocsMarkdownTransformer(
        virtual_filepath=str(source_path),
        filename=str(source_path),
    )
    return transformer.transform(document)


__all__ = ["XyDocsMarkdownTransformer", "render_xy_markdown_page"]
