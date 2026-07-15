"""Markdown loading and table-of-contents helpers."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .navigation import DOCS_ROOT, DocPage

HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
MARKDOWN_LINK_RE = re.compile(r"(\[[^]]+\]\()([^)#]+\.md)(#[^)]+)?(\))")


@dataclass(frozen=True, slots=True)
class Heading:
    """A rendered document heading."""

    level: int
    title: str
    slug: str


def plain_text(value: str) -> str:
    """Remove common inline Markdown syntax from a heading."""
    value = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"[*_~`]", "", value)
    return html.unescape(value).strip()


def slugify(value: str) -> str:
    """Create a stable GitHub-style heading slug."""
    value = unicodedata.normalize("NFKD", plain_text(value)).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def route_for_markdown(target: Path) -> str | None:
    """Convert an in-repository Markdown target to its documentation route."""
    try:
        relative = target.resolve().relative_to(DOCS_ROOT.resolve())
    except ValueError:
        return None
    if relative.stem == "index":
        return "/"
    route = relative.with_suffix("").as_posix().replace("_", "-")
    return f"/{route}/"


def rewrite_links(source: str, source_path: Path) -> str:
    """Rewrite relative Markdown links to app routes."""

    def replace(match: re.Match[str]) -> str:
        target = (source_path.parent / match.group(2)).resolve()
        route = route_for_markdown(target)
        if route is None:
            return match.group(0)
        fragment = match.group(3) or ""
        return f"{match.group(1)}{route}{fragment}{match.group(4)}"

    return MARKDOWN_LINK_RE.sub(replace, source)


def prepare_markdown(page: DocPage) -> tuple[str, tuple[Heading, ...]]:
    """Load a page, rewrite links, and add stable heading anchors."""
    source = rewrite_links(page.path.read_text(encoding="utf-8"), page.path)
    output: list[str] = []
    headings: list[Heading] = []
    slug_counts: dict[str, int] = {}
    in_fence = False

    for line in source.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            output.append(line)
            continue

        match = None if in_fence else HEADING_RE.match(line)
        if match is None:
            output.append(line)
            continue

        level = len(match.group(1))
        title = plain_text(match.group(2))
        base_slug = slugify(title) or "section"
        count = slug_counts.get(base_slug, 0)
        slug_counts[base_slug] = count + 1
        slug = base_slug if count == 0 else f"{base_slug}-{count}"
        headings.append(Heading(level=level, title=title, slug=slug))
        output.append(f'<h{level} id="{slug}">{html.escape(title)}</h{level}>')

    return "\n".join(output), tuple(headings)
