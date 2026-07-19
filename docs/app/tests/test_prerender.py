"""Production prerender coverage for every Markdown-backed documentation route."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from reflex_site_shared.docs import discover_docs
from xy_docs.config import DOCS_CONFIG, DOCS_REDIRECTS
from xy_docs.prerender import (
    _CONFIG_PREFIX,
    XyDocsMarkdownPlugin,
    _merge_frontend_path_collisions,
    _with_all_docs_prerendered,
)


def _config_from_module(source: str) -> dict[str, object]:
    """Decode the generated JavaScript module used by React Router."""
    return json.loads(source.strip().removeprefix(_CONFIG_PREFIX).removesuffix(";"))


def test_production_prerender_config_lists_every_docs_route() -> None:
    """Generate real HTML for nested pages instead of relying on a 404 fallback."""
    source = 'export default {"basename":"/docs/xy/","ssr":false,"prerender":true,"build":"build"};'

    config = _config_from_module(_with_all_docs_prerendered(source))

    assert config["basename"] == "/docs/xy/"
    assert config["prerender"] == [
        *[page.route for page in discover_docs(DOCS_CONFIG)],
        *DOCS_REDIRECTS,
    ]
    assert "/core-concepts/data/" in config["prerender"]
    assert "/core-concepts/large-data-and-performance/" in config["prerender"]
    assert "/charts/annotations/" in config["prerender"]


def test_development_router_config_is_unchanged() -> None:
    """Do not enable production prerendering in the development server."""
    source = 'export default {"basename":"/docs/xy/","ssr":false};'

    assert _with_all_docs_prerendered(source) == source


def test_post_build_merges_public_assets_without_replacing_component_routes(
    tmp_path,
    monkeypatch,
) -> None:
    """Keep the final frontend-path relocation from overwriting /components docs."""
    monkeypatch.setattr(
        "xy_docs.prerender.get_config",
        lambda: SimpleNamespace(frontend_path="/docs/xy"),
    )
    plugin = XyDocsMarkdownPlugin(docs=DOCS_CONFIG)
    source = tmp_path / "components" / "GradientButton.tsx"
    destination = tmp_path / "docs" / "xy" / "components" / "index.html"
    source.parent.mkdir()
    destination.parent.mkdir(parents=True)
    source.write_text("export const GradientButton = () => null;", encoding="utf-8")
    destination.write_text("<title>Components</title>", encoding="utf-8")

    plugin.post_build(static_dir=tmp_path)

    assert not source.parent.exists()
    assert destination.read_text(encoding="utf-8") == "<title>Components</title>"
    assert (destination.parent / "GradientButton.tsx").read_text(
        encoding="utf-8"
    ) == "export const GradientButton = () => null;"


def test_post_build_leaves_noncolliding_assets_for_reflex_relocation(tmp_path) -> None:
    """Only pre-merge a top-level directory when its prefixed destination exists."""
    source = tmp_path / "icons" / "search.svg"
    source.parent.mkdir()
    source.write_text("<svg/>", encoding="utf-8")
    (tmp_path / "docs" / "xy").mkdir(parents=True)

    _merge_frontend_path_collisions(tmp_path, "/docs/xy")

    assert source.read_text(encoding="utf-8") == "<svg/>"


def test_post_build_rejects_public_asset_file_collisions_before_mutation(
    tmp_path,
) -> None:
    """Fail closed rather than overwrite a prerendered route artifact."""
    source = tmp_path / "components" / "index.html"
    destination = tmp_path / "docs" / "xy" / "components" / "index.html"
    source.parent.mkdir()
    destination.parent.mkdir(parents=True)
    source.write_text("public asset", encoding="utf-8")
    destination.write_text("prerendered route", encoding="utf-8")

    with pytest.raises(RuntimeError, match="conflicts with prerendered documentation"):
        _merge_frontend_path_collisions(tmp_path, "/docs/xy")

    assert source.read_text(encoding="utf-8") == "public asset"
    assert destination.read_text(encoding="utf-8") == "prerendered route"


def test_post_build_collision_merge_is_idempotent(tmp_path) -> None:
    """Allow repeated hooks after the top-level collision has already been merged."""
    source = tmp_path / "components" / "GradientButton.tsx"
    destination = tmp_path / "docs" / "xy" / "components" / "index.html"
    source.parent.mkdir()
    destination.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    destination.write_text("route", encoding="utf-8")

    _merge_frontend_path_collisions(tmp_path, "/docs/xy")
    _merge_frontend_path_collisions(tmp_path, "/docs/xy")

    assert destination.read_text(encoding="utf-8") == "route"
    assert (destination.parent / "GradientButton.tsx").read_text(encoding="utf-8") == "source"
