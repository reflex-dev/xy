"""Validate the generated XY documentation sitemap."""

from pathlib import Path
from xml.etree import ElementTree

from reflex_site_shared.docs import discover_docs
from xy_docs.config import DOCS_CONFIG
from xy_docs.constants import PUBLIC_DOCS_URL

APP_ROOT = Path(__file__).resolve().parents[1]
SITEMAP_NAMESPACE = {"sitemap": "https://www.sitemaps.org/schemas/sitemap/0.9"}


def expected_locations() -> list[str]:
    """Return the canonical locations for every public Markdown page.

    Returns:
        Canonical sitemap locations in documentation discovery order.
    """
    pages = discover_docs(DOCS_CONFIG)
    return [f"{PUBLIC_DOCS_URL}{page.route}" for page in pages]


def sitemap_locations(path: Path) -> list[str]:
    """Read locations from a generated sitemap.

    Args:
        path: Generated sitemap path.

    Returns:
        Sitemap location values in document order.
    """
    root = ElementTree.parse(path).getroot()
    return [
        location.text or ""
        for location in root.findall("sitemap:url/sitemap:loc", SITEMAP_NAMESPACE)
    ]


def main() -> None:
    """Validate both source and production sitemap copies."""
    sitemap_paths = (
        APP_ROOT / ".web" / "public" / "sitemap.xml",
        APP_ROOT / ".web" / "build" / "client" / "docs" / "xy" / "sitemap.xml",
    )
    expected = expected_locations()
    for sitemap_path in sitemap_paths:
        actual = sitemap_locations(sitemap_path)
        if actual != expected:
            msg = f"Invalid sitemap {sitemap_path}:\nexpected {expected!r}\nactual   {actual!r}"
            raise RuntimeError(msg)
        if len(actual) != len(set(actual)):
            msg = f"Duplicate sitemap locations in {sitemap_path}"
            raise RuntimeError(msg)


if __name__ == "__main__":
    main()
