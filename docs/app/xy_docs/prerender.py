"""Prerender every public XY documentation route in production builds."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from reflex.constants import Dirs
from reflex_base.config import get_config
from reflex_site_shared.docs import DocsSiteConfig, discover_docs
from reflex_site_shared.plugins import DocsMarkdownPlugin

from xy_docs.config import DOCS_CONFIG, DOCS_REDIRECTS
from xy_docs.plugins import markdown_asset_path, page_markdown_with_api_reference

_CONFIG_PREFIX = "export default "
_CONFIG_PATH = "react-router.config.js"


def _merge_frontend_path_collisions(
    static_dir: Path,
    frontend_path: str,
) -> None:
    """Merge public assets before Reflex's destructive frontend-path move."""
    normalized_path = frontend_path.strip("/")
    if not normalized_path:
        return

    prefix = Path(normalized_path)
    prefix_root = static_dir / prefix
    collisions: list[tuple[Path, Path]] = []
    for source in static_dir.iterdir():
        if not source.is_dir() or source.name == prefix.parts[0]:
            continue
        destination = prefix_root / source.name
        if destination.is_dir():
            collisions.append((source, destination))

    for source, destination in collisions:
        for source_path in source.rglob("*"):
            destination_path = destination / source_path.relative_to(source)
            if not destination_path.exists():
                continue
            if source_path.is_dir() and destination_path.is_dir():
                continue
            msg = (
                "Public asset relocation conflicts with prerendered documentation: "
                f"{source_path} -> {destination_path}"
            )
            raise RuntimeError(msg)

    for source, destination in collisions:
        shutil.copytree(source, destination, dirs_exist_ok=True)
        shutil.rmtree(source)


def _with_all_docs_prerendered(
    source: str,
    docs: DocsSiteConfig = DOCS_CONFIG,
) -> str:
    """Replace React Router's shallow auto-discovery with explicit docs routes."""
    stripped = source.strip()
    if not stripped.startswith(_CONFIG_PREFIX) or not stripped.endswith(";"):
        msg = "Unexpected React Router config format"
        raise ValueError(msg)

    config = json.loads(stripped.removeprefix(_CONFIG_PREFIX).removesuffix(";"))
    if config.get("prerender") is not True:
        return source

    config["prerender"] = [
        *[page.route for page in discover_docs(docs)],
        *DOCS_REDIRECTS,
    ]
    return f"{_CONFIG_PREFIX}{json.dumps(config)};"


class XyDocsMarkdownPlugin(DocsMarkdownPlugin):
    """Publish Markdown without replacing the routes prerendered beside it."""

    def get_static_assets(self, **context: Any) -> tuple[tuple[Path, str], ...]:
        """Publish source Markdown with the same generated API as the HTML page."""
        del context
        root = Path(Dirs.PUBLIC)
        if frontend_path := get_config().frontend_path:
            root /= frontend_path.lstrip("/")

        assets: list[tuple[Path, str]] = []
        for page in discover_docs(self.docs):
            content = page_markdown_with_api_reference(
                page,
                include_frontmatter=True,
            )
            route = page.route.strip("/")
            assets.extend(
                (
                    (root / markdown_asset_path(page), content),
                    (root / route / ".md", content),
                )
            )
        return tuple(assets)

    def pre_compile(self, **context: Any) -> None:
        """Register the generated-config rewrite for production compilation."""
        context["add_modify_task"](
            _CONFIG_PATH,
            lambda source: _with_all_docs_prerendered(source, self.docs),
        )

    def post_build(self, **context: Any) -> None:
        """Prevent generated component source from replacing docs route HTML."""
        _merge_frontend_path_collisions(
            Path(context["static_dir"]),
            get_config().frontend_path,
        )


__all__ = ["XyDocsMarkdownPlugin"]
