"""Validate semantic heading order on every public documentation route."""

from collections.abc import Iterator, Sequence
from itertools import pairwise
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


def _heading_level(component: object) -> int | None:
    """Return the semantic heading level of a rendered Reflex component."""
    tag = _static_string(getattr(component, "tag", None))
    if tag == "Heading":
        tag = _static_string(getattr(component, "as_", None))
    if tag is not None and len(tag) == 2 and tag[0].lower() == "h":
        level = int(tag[1]) if tag[1].isdigit() else 0
        return level if 1 <= level <= 6 else None
    return None


def heading_outline_errors(components: Sequence[object]) -> tuple[str, ...]:
    """Return missing-H1 and adjacent heading-level errors."""
    levels = tuple(
        level for component in components if (level := _heading_level(component)) is not None
    )
    if not levels:
        return ("missing H1 (page has no headings)",)

    errors = []
    if levels[0] != 1:
        errors.append(f"first heading is H{levels[0]}, expected H1")
    errors.extend(
        f"heading level jumps from H{current} to H{following}"
        for current, following in pairwise(levels)
        if following > current + 1
    )
    return tuple(errors)


def validate_public_page_headings() -> None:
    """Raise when a public page omits H1 or skips a semantic heading level."""
    failures: dict[str, tuple[str, ...]] = {}
    for page in discover_docs(DOCS_CONFIG):
        components = tuple(_walk_component_tree(render_xy_markdown_page(page)))
        errors = heading_outline_errors(components)
        if errors:
            failures[page.route] = errors
    if failures:
        raise RuntimeError(f"heading outline errors: {failures}")


def main() -> None:
    """Validate heading order on all public documentation pages."""
    validate_public_page_headings()


if __name__ == "__main__":
    main()
