"""Fast source-level validation for Markdown-rendered documentation IDs.

The post-build route validator checks complete HTML, including shared layout,
raw HTML/SVG, and redirects.
"""

from collections import Counter
from collections.abc import Iterator, Sequence
from typing import Any

from reflex_site_shared.docs.content import discover_docs
from xy_docs.config import DOCS_CONFIG
from xy_docs.markdown import render_xy_markdown_page


def _static_string(value: Any) -> str | None:
    """Return a Python string from a literal Reflex value."""
    if isinstance(value, str):
        return value
    literal = getattr(value, "_var_value", None)
    return literal if isinstance(literal, str) else None


def _walk_component_tree(component: object) -> Iterator[object]:
    """Yield a rendered Reflex component tree in document order."""
    yield component
    for child in getattr(component, "children", ()):
        yield from _walk_component_tree(child)


def duplicate_ids(components: Sequence[object]) -> tuple[str, ...]:
    """Return duplicate static IDs from a rendered component sequence."""
    static_ids = tuple(
        component_id
        for component in components
        if (component_id := _static_string(getattr(component, "id", None)))
    )
    return tuple(component_id for component_id, count in Counter(static_ids).items() if count > 1)


def validate_public_page_ids() -> None:
    """Raise when Markdown-rendered page content has duplicate static IDs."""
    failures: dict[str, tuple[str, ...]] = {}
    for page in discover_docs(DOCS_CONFIG):
        components = tuple(_walk_component_tree(render_xy_markdown_page(page)))
        duplicates = duplicate_ids(components)
        if duplicates:
            failures[page.route] = duplicates
    if failures:
        raise RuntimeError(f"duplicate static IDs: {failures}")


def main() -> None:
    """Validate literal IDs produced from all Markdown-backed pages."""
    validate_public_page_ids()


if __name__ == "__main__":
    main()
