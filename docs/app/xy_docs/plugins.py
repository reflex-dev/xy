"""XY-specific compiler assets for agent-readable documentation."""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from pathlib import Path
from typing import Any

from reflex.constants import Dirs
from reflex_base.config import get_config
from reflex_base.plugins import Plugin
from reflex_site_shared.docs import DocsPage, DocsSiteConfig, discover_docs

from xy_docs.api_reference import append_component_api_markdown
from xy_docs.constants import LLMS_FULL_TXT_PATH, LLMS_TXT_PATH, PUBLIC_DOCS_URL

MARKDOWN_DIRECTIVE = (
    "> For AI agents: the complete XY documentation index is at "
    "[llms.txt]({llms_txt_url}). Markdown versions are available by appending "
    "`.md` or sending `Accept: text/markdown`."
)

_SECTION_TITLES = {
    "overview": "Overview",
    "core-concepts": "Core Concepts",
    "styling": "Styling",
    "charts": "Chart Gallery",
    "components": "Components",
    "integrations": "Integrations",
    "guides": "Guides",
    "advanced": "Advanced",
    "api-reference": "API Reference",
}
_SECTION_ORDER = tuple(_SECTION_TITLES.values())


def _public_url(path: str) -> str:
    """Return an absolute URL for an XY docs asset path."""
    return f"{PUBLIC_DOCS_URL}{path}"


def markdown_asset_path(page: DocsPage) -> str:
    """Return the route-relative Markdown asset path for a discovered page."""
    route = page.route.strip("/")
    if page.relative_path.stem.lower() == "index":
        return f"{route}/index.md" if route else "index.md"
    return f"{route}.md"


def _page_markdown_url(page: DocsPage) -> str:
    """Return the direct public Markdown asset URL for a discovered page."""
    return f"{PUBLIC_DOCS_URL}/{markdown_asset_path(page)}"


def _markdown_directive() -> str:
    """Return the standard agent discovery directive for published Markdown."""
    return MARKDOWN_DIRECTIVE.format(
        llms_txt_url=_public_url(LLMS_TXT_PATH),
    )


def _strip_markdown_directive(content: str) -> str:
    """Remove the generated discovery directive from combined page content."""
    directive = _markdown_directive()
    if content.startswith(directive):
        return content.removeprefix(directive).lstrip()
    return content


def _section_for_page(page: DocsPage) -> str:
    """Return the public navigation section for a discovered page."""
    if page.route == "/overview/gallery/":
        return "Chart Gallery"
    route_parts = tuple(part for part in page.route.split("/") if part)
    if not route_parts:
        return "Overview"
    segment = route_parts[0]
    return _SECTION_TITLES.get(segment, segment.replace("-", " ").title())


def _page_body(content: str) -> str:
    """Drop a page's leading H1 so section headers stay the top heading level."""
    first_line, separator, rest = content.lstrip("\n").partition("\n")
    if first_line.startswith("# "):
        return rest.lstrip("\n") if separator else ""
    return content


def page_markdown_with_api_reference(
    page: DocsPage,
    *,
    include_frontmatter: bool = False,
) -> str:
    """Return authored Markdown plus its generated component API section.

    Args:
        page: Discovered documentation page.
        include_frontmatter: Read the original source, including YAML metadata,
            instead of using the parsed page body.

    Returns:
        Agent-readable Markdown matching the rendered page's API content.
    """
    content = page.source_path.read_text(encoding="utf-8") if include_frontmatter else page.content
    body = append_component_api_markdown(content, page.metadata).lstrip()
    return f"{_markdown_directive()}\n\n{body}"


def build_llms_txt(config: DocsSiteConfig) -> str:
    """Build the comprehensive agent-readable index of public XY pages."""
    lines = [
        "# XY Documentation",
        "",
        (
            "> XY is a high-performance plotting library for Python and Reflex. "
            "Use this index to find agent-readable Markdown docs, or see "
            f"[llms-full.txt]({_public_url(LLMS_FULL_TXT_PATH)}) for the "
            "complete docs in one file."
        ),
        "",
        "## Docs",
        "",
    ]

    sections: dict[str, list[DocsPage]] = defaultdict(list)
    for page in discover_docs(config):
        sections[_section_for_page(page)].append(page)

    ordered_sections = [
        *[section for section in _SECTION_ORDER if section in sections],
        *sorted(section for section in sections if section not in _SECTION_ORDER),
    ]
    for section in ordered_sections:
        lines.extend((f"### {section}", ""))
        for page in sections[section]:
            description = f": {page.description}" if page.description else ""
            lines.append(f"- [{page.title}]({_page_markdown_url(page)}){description}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_llms_full_txt(config: DocsSiteConfig) -> str:
    """Combine all public XY pages into one agent-readable Markdown file."""
    lines = [
        "# XY Documentation",
        f"Source: {PUBLIC_DOCS_URL}/",
        "",
        (
            "This file stitches together the full XY documentation as Markdown "
            "for AI agents and LLM indexing."
        ),
        "",
        (
            "For a navigable index with links to individual docs pages, see "
            f"[llms.txt]({_public_url(LLMS_TXT_PATH)})."
        ),
        "",
    ]
    for page in discover_docs(config):
        lines.extend(
            (
                f"## {page.title}",
                "",
                f"Source: {_page_markdown_url(page)}",
                "",
                _page_body(
                    _strip_markdown_directive(
                        page_markdown_with_api_reference(page),
                    )
                ),
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


@dataclasses.dataclass(frozen=True, slots=True)
class XYDocsAgentFilesPlugin(Plugin):
    """Publish concise and complete agent-readable XY documentation."""

    docs: DocsSiteConfig

    def get_static_assets(self, **context: Any) -> tuple[tuple[Path, str], ...]:
        """Emit ``llms.txt`` and ``llms-full.txt`` under the frontend path."""
        root = Path(Dirs.PUBLIC)
        if frontend_path := get_config().frontend_path:
            root /= frontend_path.lstrip("/")
        return (
            (root / "llms.txt", build_llms_txt(self.docs)),
            (root / "llms-full.txt", build_llms_full_txt(self.docs)),
        )


__all__ = [
    "XYDocsAgentFilesPlugin",
    "build_llms_full_txt",
    "build_llms_txt",
    "markdown_asset_path",
    "page_markdown_with_api_reference",
]
