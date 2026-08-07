"""XY-specific Markdown rendering behavior."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace

import reflex as rx
from reflex_docgen.markdown import CodeBlock, HeadingBlock, parse_document
from reflex_site_shared.docs.markdown import (
    ReflexDocTransformer,
    _exec_code,
    _file_modules,
    _last_defined_name,
    _spans_to_plaintext,
)
from reflex_site_shared.docs.models import DocsPage
from reflex_site_shared.views.hosting_banner import HostingBannerState

from xy_docs.api_reference import (
    API_REFERENCE_HEADING,
    component_api_paths,
    component_api_references,
    component_page_api,
    split_faq_section,
)
from xy_docs.code import code_block
from xy_docs.examples import chart_example_demo

# A demo fence may split its hardcoded data from the chart code with this
# divider on its own line. Everything above is shown in the "Data" tab, the rest
# in "Code"; the whole fence still executes for the preview (leading data is
# plain literals, so it is valid before the imports below the divider).
_DEMO_DATA_DIVIDER = "# --- chart ---"
_DEMO_DATA_TAB_LINE_THRESHOLD = 10

# Namespace of the page module as of the end of each executed fence, keyed by
# (virtual filepath, fence source, occurrence of that source in the page). The
# occurrence disambiguates a page that repeats an identical fence: those are
# distinct positions in the page's fence sequence and saw different namespaces.
# See `_exec_fence`.
_FENCE_NAMESPACES: dict[tuple[str, str, int], dict] = {}

# Digest of the page source each filepath's snapshots were captured from. A
# snapshot's key includes the fence's *position*, so entries are only valid for
# the exact page content that produced them. See `_invalidate_stale_fences`.
_FENCE_PAGE_DIGESTS: dict[str, str] = {}


def _invalidate_stale_fences(virtual_filepath: str, content: str) -> None:
    """Drop a page's fence snapshots when its source no longer matches theirs.

    Snapshots are keyed by (filepath, fence source, occurrence index), so a
    fence's identity depends on where it sits in the page's fence sequence.
    Within one process that is exactly right — the repeat renders this cache
    exists for (frontend compile, then `reflex_xy`'s worker-startup pass) walk
    identical content. Across an edit it is not: adding, removing or reordering
    a duplicated fence shifts the occurrence index of every surviving copy, so
    a fence could restore a snapshot captured when it sat at a different
    position, silently reviving a namespace that predates the bindings now
    ahead of it. The dev server re-renders in-process on reload, which is
    precisely where that happens.

    So version the cache by page source: whenever a page renders with content
    that differs from the digest its entries were captured under, those entries
    are stale by construction and get dropped. This also bounds the cache —
    superseded page versions are evicted rather than retained for the life of
    the process, each one holding a full namespace snapshot (State classes,
    arrays, every binding) alive.
    """
    digest = hashlib.sha256(content.encode()).hexdigest()
    if _FENCE_PAGE_DIGESTS.get(virtual_filepath) == digest:
        return
    _FENCE_PAGE_DIGESTS[virtual_filepath] = digest
    for key in [key for key in _FENCE_NAMESPACES if key[0] == virtual_filepath]:
        del _FENCE_NAMESPACES[key]


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

    def __init__(
        self,
        virtual_filepath: str = "",
        filename: str = "",
        fence_occurrences: Counter[str] | None = None,
    ) -> None:
        super().__init__(virtual_filepath=virtual_filepath, filename=filename)
        # Counts exec fences by source as this render walks the page, so the
        # nth identical fence keys its own snapshot. `render_xy_markdown_page`
        # renders a page's body and its FAQ through two transformers; passing
        # one counter through keeps a single fence sequence across both.
        self.fence_occurrences: Counter[str] = (
            Counter() if fence_occurrences is None else fence_occurrences
        )

    def heading(self, block: HeadingBlock) -> rx.Component:
        """Render one route-local Markdown heading."""
        return _heading_link(_spans_to_plaintext(block.children), block.level)

    def code_block(self, block: CodeBlock) -> rx.Component:
        """Use the accessible XY code block for every visible source fence."""
        flags = set(block.flags)
        language = block.language or "plain"
        if language == "python" and "exec" in flags and not flags & {"demo", "demo-only"}:
            # Same contract as the shared renderer's bare-``exec`` branch, but
            # through the snapshot-aware seam below.
            self._exec_fence(block.content)
            return rx.fragment()
        if language == "python" and flags.intersection({"demo", "demo-only", "exec", "eval"}):
            return super().code_block(block)
        return code_block(block.content, language)

    def _exec_fence(self, content: str) -> None:
        """Execute one fence, or restore the namespace it left behind.

        Every exec fence in a page shares one synthetic module, and the shared
        renderer skips re-executing a fence it has already run (State classes
        must not be redefined). A page is evaluated more than once per process
        — the frontend compile, then `reflex_xy`'s worker-startup pass over the
        unevaluated pages (reflex-integration.md §"Plans") — and on those later
        renders the module namespace holds *end-of-page* values, so a fence's
        preview function reads whatever a later fence last bound its names to.
        Demos that reuse names (`months`, `x`, `y`) then build from another
        demo's data: silently different charts, mismatched plan digests, or a
        hard failure when the shadowing arrays disagree in length.

        So snapshot the namespace at the end of each fence's first execution
        and restore it in place (the module dict object is what the fence's
        functions close over) before the fence renders again. Every render
        sees exactly the namespace the first one did.

        A fence is identified by its source *and* its occurrence index within
        the page, never by source alone: a page that repeats an identical
        fence has two positions in its fence sequence, and keying on source
        alone would make the second one restore the first one's snapshot —
        discarding whatever the fences in between defined, which is not what
        the shared renderer does (it skips re-execution and lets the page's
        namespace keep accumulating).

        Because that identity is positional, it is only meaningful for the page
        source it was captured from; `_invalidate_stale_fences` drops a page's
        entries as soon as its content changes.
        """
        occurrence = self.fence_occurrences[content]
        self.fence_occurrences[content] += 1
        key = (self.virtual_filepath, content, occurrence)
        namespace = _FENCE_NAMESPACES.get(key)
        if namespace is None:
            _exec_code(content, self.env, self.virtual_filepath)
            _FENCE_NAMESPACES[key] = dict(self.env)
            return
        module = _file_modules.get(self.virtual_filepath)
        if module is not None:
            module.__dict__.clear()
            module.__dict__.update(namespace)
        self.env.clear()
        self.env.update(namespace)

    def _exec_and_get_last_callable(self, content: str):
        """Call the fence's last-defined callable against its own namespace."""
        self._exec_fence(content)
        last_name = _last_defined_name(content)
        if last_name is None:
            msg = "Exec block defines no function or class"
            raise RuntimeError(msg)
        last = self.env[last_name]
        if not callable(last):
            msg = f"Last defined name {last_name!r} is not callable"
            raise TypeError(msg)
        return last()

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
    # Cached snapshots are keyed by fence position, so they only survive while
    # the page source that produced them does.
    _invalidate_stale_fences(str(source_path), page.content)
    # One fence sequence per page render, even though the body and the FAQ are
    # transformed separately around the generated API section.
    fence_occurrences: Counter[str] = Counter()

    def _render(markdown_text: str) -> rx.Component:
        transformer = XyDocsMarkdownTransformer(
            virtual_filepath=str(source_path),
            filename=str(source_path),
            fence_occurrences=fence_occurrences,
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
