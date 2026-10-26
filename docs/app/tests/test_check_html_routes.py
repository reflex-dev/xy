"""Focused tests for the post-build HTML route validator."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def test_duplicate_id_validator_covers_html_svg_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Accept unique IDs but reject an HTML/SVG collision with route context."""
    reflex_site_shared = ModuleType("reflex_site_shared")
    reflex_docs = ModuleType("reflex_site_shared.docs")
    reflex_docs.discover_docs = lambda _config: []
    xy_docs = ModuleType("xy_docs")
    xy_config = ModuleType("xy_docs.config")
    xy_config.DOCS_CONFIG = None
    xy_config.DOCS_REDIRECTS = {}
    monkeypatch.setitem(sys.modules, "reflex_site_shared", reflex_site_shared)
    monkeypatch.setitem(sys.modules, "reflex_site_shared.docs", reflex_docs)
    monkeypatch.setitem(sys.modules, "xy_docs", xy_docs)
    monkeypatch.setitem(sys.modules, "xy_docs.config", xy_config)

    validator_path = Path(__file__).resolve().parents[1] / "scripts" / "check_html_routes.py"
    spec = importlib.util.spec_from_file_location("focused_check_html_routes", validator_path)
    assert spec is not None and spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)

    unique_source = '<main id="content"><svg id="chart"/><div id=""></div></main>'
    assert validator.duplicate_html_ids(unique_source) == ()

    duplicate_source = '<main id="content"><svg><g id="shared"/></svg><section id="shared"/></main>'
    html_path = tmp_path / "charts" / "scatter.html"
    assert validator.duplicate_html_ids(duplicate_source) == ("shared",)

    with pytest.raises(
        RuntimeError,
        match=r"duplicate element IDs \('shared',\).*?/charts/scatter/.*scatter\.html",
    ):
        validator.validate_unique_html_ids(
            "/charts/scatter/",
            html_path,
            duplicate_source,
        )
