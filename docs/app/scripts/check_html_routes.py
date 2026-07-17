"""Validate human-facing documentation routes."""

import re
from pathlib import Path

from reflex_site_shared.docs import discover_docs

from xy_docs.config import DOCS_CONFIG

APP_ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = APP_ROOT / ".web" / "build" / "client"
BUILD_ROOT = CLIENT_ROOT / "docs" / "xy"
ROUTES_ROOT = APP_ROOT / ".web" / "app" / "routes"
LIVE_PREVIEW_MARKERS = ("python demo exec", "python demo-only exec")
LIVE_PREVIEW_ROUTES = {"/overview/gallery/"}
XY_PAYLOAD_PATTERN = re.compile(r'["\'](?P<url>/docs/xy/xy/[a-f0-9]+\.xyf)["\']')
XY_PAYLOAD_MAGIC = b"XYBF"


def route_html_paths(route: str) -> tuple[Path, ...]:
    """Return supported prerender output paths for a route.

    Args:
        route: Public documentation route.

    Returns:
        Flat and directory-index HTML candidates.
    """
    route_path = route.strip("/")
    if not route_path:
        return (BUILD_ROOT / "index.html",)
    return (
        BUILD_ROOT / f"{route_path}.html",
        BUILD_ROOT / route_path / "index.html",
    )


def route_module_path(route: str) -> Path:
    """Return the generated React route module for a docs route.

    Args:
        route: Public documentation route.

    Returns:
        Generated route module path.
    """
    parts = route.strip("/").split("/") if route.strip("/") else []
    filename = (
        ".".join(f"[{part}]" for part in parts) + "._index.jsx"
        if parts
        else "_index.jsx"
    )
    return ROUTES_ROOT / filename


def validate_live_preview(page_route: str, module_path: Path) -> None:
    """Validate a compiled live preview and each payload it references.

    Args:
        page_route: Public route used in validation errors.
        module_path: Generated React route module to inspect.

    Raises:
        RuntimeError: If the route omits XYChart or references an invalid payload.
    """
    source = module_path.read_text(encoding="utf-8")
    if "XYChart" not in source:
        msg = f"Live-preview route does not compile XYChart: {page_route}"
        raise RuntimeError(msg)

    payload_urls = set(XY_PAYLOAD_PATTERN.findall(source))
    if not payload_urls:
        msg = f"Live-preview route has no static XY payload: {page_route}"
        raise RuntimeError(msg)

    for payload_url in payload_urls:
        payload_path = CLIENT_ROOT / payload_url.lstrip("/")
        if not payload_path.is_file():
            msg = f"Missing XY payload for {page_route}: {payload_path}"
            raise RuntimeError(msg)
        if not payload_path.read_bytes().startswith(XY_PAYLOAD_MAGIC):
            msg = f"Invalid XY payload for {page_route}: {payload_path}"
            raise RuntimeError(msg)


def main() -> None:
    """Check every generated docs route."""
    fallback = BUILD_ROOT / "__spa-fallback.html"
    if not fallback.is_file():
        msg = f"Missing SPA fallback: {fallback}"
        raise RuntimeError(msg)

    pages = discover_docs(DOCS_CONFIG)
    for page in pages:
        module_path = route_module_path(page.route)
        if not module_path.is_file():
            msg = f"Missing compiled documentation route: {module_path}"
            raise RuntimeError(msg)
        if page.route in LIVE_PREVIEW_ROUTES or any(
            marker in page.content for marker in LIVE_PREVIEW_MARKERS
        ):
            validate_live_preview(page.route, module_path)
        html_paths = route_html_paths(page.route)
        route_depth = len(Path(page.route.strip("/")).parts)
        if route_depth > 1:
            # Deeper optional segments use the SPA fallback. The route module
            # above proves the Python page was compiled into it.
            continue
        if not any(path.is_file() for path in html_paths):
            msg = f"Missing prerendered documentation route: {html_paths!r}"
            raise RuntimeError(msg)


if __name__ == "__main__":
    main()
