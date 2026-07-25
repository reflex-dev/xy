"""Validate route-level Markdown files in the XY production export."""

from pathlib import Path

from reflex_site_shared.docs import discover_docs
from xy_docs.config import DOCS_CONFIG
from xy_docs.plugins import page_markdown_with_api_reference

APP_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = APP_ROOT / ".web" / "build" / "client" / "docs" / "xy"


def markdown_paths(route: str, *, is_index: bool) -> tuple[Path, Path]:
    """Return direct and trailing-slash Markdown paths for a docs route.

    Args:
        route: Public documentation route.
        is_index: Whether the source file is an index page.

    Returns:
        Paths relative to the documentation build root.
    """
    route_path = Path(route.strip("/"))
    direct_path = route_path / "index.md" if is_index else Path(f"{route.strip('/')}.md")
    trailing_path = route_path / ".md" if route_path.parts else Path(".md")
    return direct_path, trailing_path


def main() -> None:
    """Check every Markdown URL against its authored and generated content."""
    pages = discover_docs(DOCS_CONFIG)
    for page in pages:
        expected = page_markdown_with_api_reference(
            page,
            include_frontmatter=True,
        ).encode()
        paths = markdown_paths(
            page.route,
            is_index=page.relative_path.stem.lower() == "index",
        )
        for relative_path in paths:
            output_path = BUILD_ROOT / relative_path
            if not output_path.is_file():
                msg = f"Missing Markdown asset: {output_path}"
                raise RuntimeError(msg)
            if output_path.read_bytes() != expected:
                msg = f"Markdown asset differs from generated content: {output_path}"
                raise RuntimeError(msg)


if __name__ == "__main__":
    main()
