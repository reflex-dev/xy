"""Tests for the standalone XY documentation application."""

import hashlib
import importlib.util
import inspect
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
import reflex_xy
from reflex_base.components.memo import MemoComponent
from reflex_docgen.markdown import (
    Block,
    BoldSpan,
    CodeBlock,
    DirectiveBlock,
    HeadingBlock,
    ImageSpan,
    ItalicSpan,
    LinkSpan,
    ListBlock,
    QuoteBlock,
    Span,
    StrikethroughSpan,
    TableBlock,
    TextBlock,
    parse_document,
)
from reflex_site_shared.docs import render_markdown
from reflex_site_shared.docs.content import discover_docs
from rxconfig import config
from xy_docs.api_reference import (
    AXES_AND_ANNOTATIONS,
    CHART_FACTORY_GROUPS,
    CHROME_AND_BEHAVIOR,
    MARKS,
    axes_and_annotations_api,
    chart_containers_api,
    chart_factories_api,
    chrome_and_behavior_api,
    marks_api,
)
from xy_docs.breadcrumb import xy_docs_breadcrumb
from xy_docs.config import DOCS_CONFIG, DOCS_NAVIGATION, DOCS_SECTIONS
from xy_docs.footer import xy_docs_footer
from xy_docs.gallery import (
    _gallery_chart,
    _iter_gallery_items,
    _responsive_gallery_svg,
    chart_gallery_grid,
)
from xy_docs.markdown import XyDocsMarkdownTransformer, render_xy_markdown_page
from xy_docs.navbar import xy_docs_navbar
from xy_docs.sidebar import (
    SIDEBAR_SECTION_GROUPS,
    xy_docs_sidebar,
    xy_docs_sidebar_comp,
)

import xy
from xy._validate import _POINT_SYMBOLS
from xy.components import _MARK_APPLIERS

SITEMAP_NAMESPACE = {"sitemap": "https://www.sitemaps.org/schemas/sitemap/0.9"}
DOCS_APP_ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = DOCS_APP_ROOT.parent
EXPORTED_SITEMAP = DOCS_APP_ROOT / ".web" / "public" / "sitemap.xml"
EXPORTED_CLIENT_ASSETS = DOCS_APP_ROOT / ".web" / "build" / "client" / "docs" / "xy" / "assets"
CHECK_HTML_ROUTES_PATH = DOCS_APP_ROOT / "scripts" / "check_html_routes.py"
CHECK_HTML_ROUTES_SPEC = importlib.util.spec_from_file_location(
    "xy_docs_check_html_routes",
    CHECK_HTML_ROUTES_PATH,
)
if CHECK_HTML_ROUTES_SPEC is None or CHECK_HTML_ROUTES_SPEC.loader is None:
    msg = f"Unable to load route validator: {CHECK_HTML_ROUTES_PATH}"
    raise RuntimeError(msg)
check_html_routes = importlib.util.module_from_spec(CHECK_HTML_ROUTES_SPEC)
CHECK_HTML_ROUTES_SPEC.loader.exec_module(check_html_routes)


def _walk_spans(spans: tuple[Span, ...]) -> Iterator[LinkSpan]:
    """Yield links recursively from a Markdown span tree.

    Args:
        spans: Markdown spans to traverse.

    Yields:
        Every discovered link span.
    """
    for span in spans:
        if isinstance(span, LinkSpan):
            yield span
            yield from _walk_spans(span.children)
        elif isinstance(span, (BoldSpan, ItalicSpan, StrikethroughSpan, ImageSpan)):
            yield from _walk_spans(span.children)


def _walk_blocks(blocks: tuple[Block, ...]) -> Iterator[LinkSpan]:
    """Yield links recursively from Markdown blocks, excluding code fences.

    Args:
        blocks: Markdown blocks to traverse.

    Yields:
        Every discovered documentation link.
    """
    for block in blocks:
        if isinstance(block, (HeadingBlock, TextBlock)):
            yield from _walk_spans(block.children)
        elif isinstance(block, ListBlock):
            for item in block.items:
                yield from _walk_blocks(item.children)
        elif isinstance(block, (QuoteBlock, DirectiveBlock)):
            yield from _walk_blocks(block.children)
        elif isinstance(block, TableBlock):
            for row in (block.header, *block.rows):
                for cell in row.cells:
                    yield from _walk_spans(cell.children)


def _normalize_xy_docs_path(url: str) -> str | None:
    """Return an app-relative route for a canonical XY docs URL.

    Args:
        url: Absolute or path-only documentation URL.

    Returns:
        Normalized app route, or ``None`` when the frontend path does not match.
    """
    path = urlparse(url).path.rstrip("/") or "/"
    if path == "/docs/xy":
        return "/"
    if path.startswith("/docs/xy/"):
        return path.removeprefix("/docs/xy")
    return None


def _sitemap_routes(sitemap_path: Path) -> set[str]:
    """Read normalized XY routes from an exported sitemap.

    Args:
        sitemap_path: Generated sitemap file.

    Returns:
        Routes published beneath ``/docs/xy``.
    """
    root = ET.parse(sitemap_path).getroot()
    return {
        route
        for location in root.findall("sitemap:url/sitemap:loc", SITEMAP_NAMESPACE)
        if location.text is not None
        if (route := _normalize_xy_docs_path(location.text.strip())) is not None
    }


def _markdown_files(root: Path) -> Iterator[Path]:
    """Yield source Markdown files outside generated and vendor directories.

    Args:
        root: Documentation tree to scan.

    Yields:
        Markdown source paths in deterministic order.
    """
    skipped = {".git", ".venv", ".web", "build", "dist", "node_modules", "__pycache__"}
    for path in sorted(root.rglob("*.md")):
        if not skipped.intersection(path.relative_to(root).parts):
            yield path


def _link_line(source: str, target: str, cursor: int) -> tuple[int, int]:
    """Locate a Markdown link target after the previous match.

    Args:
        source: Original Markdown source.
        target: Parsed link target.
        cursor: Offset after the previous match.

    Returns:
        The one-based line number and next search offset, or zero and the
        unchanged offset when the target cannot be located.
    """
    needle = "](" + target
    position = source.find(needle, cursor)
    if position == -1:
        position = source.find("]: " + target, cursor)
    if position == -1:
        return 0, cursor
    return source.count("\n", 0, position) + 1, position + len(needle)


def test_public_markdown_routes_match_the_docs_navigation() -> None:
    """Discover the exact eight-section, two-level public information architecture."""
    assert tuple(title for title, _route, _icon, _leaves in DOCS_SECTIONS) == (
        "Overview",
        "Core Concepts",
        "Styling",
        "Chart Gallery",
        "Components",
        "Integrations",
        "Guides",
        "Reference",
    )
    section_routes = tuple(
        dict.fromkeys(
            route
            for _title, landing_route, _icon, leaves in DOCS_SECTIONS
            for route in (
                landing_route,
                *(leaf_route for _leaf_title, leaf_route in leaves),
            )
        )
    )
    assert section_routes == DOCS_NAVIGATION
    assert (
        max(len(tuple(part for part in route.split("/") if part)) for route in section_routes) <= 2
    )

    pages = discover_docs(DOCS_CONFIG)

    assert tuple(page.route for page in pages) == DOCS_NAVIGATION
    assert all(page.description for page in pages)


def test_docs_app_configures_the_reflex_xy_adapter() -> None:
    """Compile live documentation examples through the shipped Reflex adapter."""
    assert config.telemetry_enabled is False
    assert any(isinstance(plugin, reflex_xy.XYPlugin) for plugin in config.plugins)


def test_tailwind_styling_docs_match_the_reflex_plugin_contract() -> None:
    """Keep the Reflex scan-path guidance aligned with the configured plugin."""
    content = (DOCS_ROOT / "styling/chrome-slots.md").read_text(encoding="utf-8")

    assert any(plugin.__class__.__name__ == "TailwindV4Plugin" for plugin in config.plugins)
    assert "the adapter mirrors its chart, slot, mark, and annotation class strings" in content
    assert "without adding the original Python or\nMarkdown file" in content
    assert "Live token/Var charts are different" in content
    assert "normal Reflex component (or safelist it" in content


@pytest.mark.xfail(
    not EXPORTED_CLIENT_ASSETS.is_dir(),
    reason="Build the XY docs frontend before validating compiled Tailwind CSS.",
    run=False,
)
def test_static_xy_tailwind_manifest_reaches_compiled_css() -> None:
    """Prove an XYBF-only class survives the complete Tailwind build.

    The sentinel is assembled from fragments in ``xy_docs.gallery``, so
    Tailwind cannot find its complete arbitrary-property token in Python
    source. The compiled route must receive it through ``tailwindClassTokens``
    and the final stylesheet must contain the corresponding declaration.
    """
    javascript = "\n".join(
        path.read_text(encoding="utf-8") for path in EXPORTED_CLIENT_ASSETS.glob("*.js")
    )
    stylesheets = "\n".join(
        path.read_text(encoding="utf-8") for path in EXPORTED_CLIENT_ASSETS.glob("*.css")
    )

    sentinel = "[--xy-tailwind-bridge:compiled]"
    assert "tailwindClassTokens" in javascript
    assert sentinel in javascript
    assert "--xy-tailwind-bridge:compiled" in stylesheets


def test_styling_troubleshooting_covers_common_host_and_export_failures() -> None:
    """Keep the public styling entry point useful when visual CSS fails."""
    content = (DOCS_ROOT / "styling/index.md").read_text(encoding="utf-8")

    for requirement in (
        "## Styling troubleshooting",
        "Tailwind classes are present but have no effect",
        "A custom font silently falls back",
        "Marks are WebGL/canvas geometry",
        "to_html(custom_css=...)",
        "engine=Engine.chromium",
        "overflow-hidden",
        'height="100%"',
        "normal cascade",
    ):
        assert requirement in content


def test_component_styling_matrix_covers_public_chrome_boundaries() -> None:
    """Keep the styling guide explicit about built-in and custom components."""
    content = (DOCS_ROOT / "styling/component-variations.md").read_text(encoding="utf-8")
    expected = {
        "legend_item",
        "legend_swatch",
        "tooltip(fields=..., title=..., format=...)",
        "x_axis(...)",
        "y_axis(...)",
        "vline(x)",
        "hline(y)",
        "crosshair_x",
        "crosshair_y",
        "selection",
        "legend(render=...)",
        "tooltip(render=...)",
        "colorbar(render=...)",
    }

    missing = {value for value in expected if value not in content}
    assert not missing
    assert 'id="x2"' in content
    assert 'side="top"' in content
    assert "button_class_name=" in content
    assert "button_style=" in content
    assert "does not render components passed through" in content
    assert "Standalone exports cannot include framework-owned components either." in content


def test_styling_docs_cover_every_public_dom_slot() -> None:
    """Make a new stable browser slot fail docs CI until it is documented."""
    chrome = (DOCS_ROOT / "styling/chrome-slots.md").read_text(encoding="utf-8")
    variations = (DOCS_ROOT / "styling/component-variations.md").read_text(encoding="utf-8")

    assert all(f"`{slot}`" in chrome for slot in xy.CHART_DOM_SLOTS)
    for slot in ("root", "title", "chrome", "canvas", "labels", "badge", "badge_item"):
        assert f"`{slot}`" in variations


def test_styling_docs_cover_every_rendered_mark_family() -> None:
    """Tie the mark-style matrix to the actual declarative mark registry."""
    content = (DOCS_ROOT / "styling/mark-styles.md").read_text(encoding="utf-8").lower()

    missing = {
        kind
        for kind in _MARK_APPLIERS
        if kind not in content and kind.replace("_", " ") not in content
    }
    assert not missing


def test_styling_gallery_exercises_every_rendered_mark_family() -> None:
    """Keep the visual styling atlas complete as XY gains mark families."""
    content = (DOCS_ROOT / "styling/gallery.md").read_text(encoding="utf-8").lower()

    missing = {
        kind
        for kind in _MARK_APPLIERS
        if f"`{kind}`" not in content and f"`{kind.replace('_', ' ')}`" not in content
    }
    assert not missing

    required_surfaces = {
        "responsive",
        "prefers-color-scheme",
        "custom legend",
        "custom tooltip",
        "reduction badge",
        "facet_chart",
        "categorical",
        "time axis",
        "to_html(custom_css=",
        "xy.interaction_config(",
        "hover=true",
        "click=true",
        "select=true",
        "brush=true",
        "crosshair=true",
        "view_change=true",
        'loc="upper center"',
        "critical-payments-reconciliation-with-extra-long-label",
    }
    assert all(surface in content for surface in required_surfaces)
    assert len(_POINT_SYMBOLS) == 17
    assert all(f'"{symbol}"' in content for symbol in _POINT_SYMBOLS)
    assert 'mode="grouped"' in content
    assert 'mode="normalized"' in content
    assert 'mode="stacked"' in content
    assert 'orientation="vertical"' in content
    assert 'orientation="horizontal"' in content
    assert "colorbar_bar" in content
    assert "colorbar_tick" in content
    assert "colorbar_title" in content


def test_markdown_heading_links_are_route_local_after_client_navigation() -> None:
    """Do not let a previously visited docs route leak into heading self-links."""
    pages = {page.route: page for page in discover_docs(DOCS_CONFIG)}

    for route in ("/overview/gallery/", "/styling/gallery/"):
        rendered = str(render_xy_markdown_page(pages[route]))
        assert 'to:"#' in rendered
        assert "router_rx_state_" not in rendered


def test_colorbar_docs_match_the_declarative_and_custom_boundaries() -> None:
    """Keep inferred built-ins distinct from opaque framework replacements."""
    content = (DOCS_ROOT / "components/colorbars.md").read_text(encoding="utf-8")

    for option in (
        "title=",
        "orientation=",
        "ticks=",
        "colorbar(show=False)",
    ):
        assert option in content
    for slot in ("colorbar", "colorbar_bar", "colorbar_tick", "colorbar_title"):
        assert f"`{slot}`" in content
    assert "The last compatible continuous mark wins" in content
    assert "does not currently mount custom chrome" in content


def test_custom_font_docs_cover_browser_and_static_export_boundaries() -> None:
    """Keep font loading advice honest across browser and native outputs."""
    content = (DOCS_ROOT / "styling/themes-and-tokens.md").read_text(encoding="utf-8")

    for requirement in (
        "## Custom fonts and export limitations",
        "@font-face",
        'style={"font_family":',
        "Engine.chromium",
        "Toolbar PNG",
        "Toolbar SVG",
        "Native PNG",
        "Python `to_svg()`",
        "baked bitmap font",
    ):
        assert requirement in content


def test_theme_component_demo_uses_site_color_mode_tokens() -> None:
    """Keep the introductory theme demo neutral and responsive to site mode."""
    content = (DOCS_ROOT / "styling/themes-and-tokens.md").read_text(encoding="utf-8")
    demo = content.split("~~~python demo exec", 1)[1].split("~~~", 1)[0]

    for token in (
        "var(--secondary-2)",
        "var(--secondary-a5)",
        "var(--secondary-a8)",
        "var(--secondary-11)",
        "var(--primary-9)",
    ):
        assert token in demo
    assert "--demo-bg" not in demo


def test_accessible_monochrome_recipe_uses_neutral_site_tokens() -> None:
    """Keep the monochrome recipe neutral in both site color modes."""
    content = (DOCS_ROOT / "styling/recipes.md").read_text(encoding="utf-8")
    section = content.split("## Accessible monochrome comparison", 1)[1].split("## ", 1)[0]

    for token in (
        "var(--secondary-2)",
        "var(--secondary-a5)",
        "var(--secondary-a8)",
        "var(--secondary-10)",
        "var(--secondary-11)",
        "var(--secondary-12)",
    ):
        assert token in section
    assert "--mono-bg" not in section


def test_generated_mark_api_does_not_claim_canvas_marks_are_dom_nodes() -> None:
    """Keep generated class_name descriptions aligned with canvas rendering."""
    for factory in MARKS:
        if "class_name" not in inspect.signature(factory).parameters:
            continue
        docstring = inspect.getdoc(factory) or ""
        assert "DOM class name applied to the mark" not in docstring
        assert "Adapter-only trace metadata" in docstring


def test_styling_docs_cover_every_annotation_factory_and_alias() -> None:
    """Keep every public annotation primitive visible in the styling guide."""
    content = (DOCS_ROOT / "styling/component-variations.md").read_text(encoding="utf-8")
    factories = (
        "vline",
        "hline",
        "x_band",
        "y_band",
        "text",
        "label",
        "marker",
        "arrow",
        "threshold",
        "threshold_zone",
        "callout",
    )

    assert all(f"`{factory}" in content for factory in factories)


def test_what_is_xy_shows_density_hero_without_inline_code() -> None:
    """Keep the signature example visible without exposing its long source."""
    content = (DOCS_ROOT / "index.md").read_text(encoding="utf-8")
    demo_source = (DOCS_APP_ROOT / "xy_docs/demos/instrument_sans_density.py").read_text(
        encoding="utf-8"
    )
    font = DOCS_APP_ROOT / "xy_docs/assets/InstrumentSans-wdth-wght.ttf"
    license_file = DOCS_APP_ROOT / "xy_docs/assets/OFL.txt"

    hero = content.index("~~~python demo-only exec")
    introduction = content.index("XY is an experimental Python charting library")
    styling = content.index("**Styling uses familiar web vocabulary.**")
    early_alpha = content.index("### Early alpha")

    assert introduction < styling < hero < early_alpha
    assert "demo exec toggle" not in content
    assert "from xy_docs.demos.instrument_sans_density import xy_density_hero" in content
    assert "View the complete Python source" in content
    assert "N_POINTS = 40_000" in demo_source
    assert "N_INLIERS = round(N_POINTS * 0.97)" in demo_source
    assert "InstrumentSans-wdth-wght.ttf" in demo_source
    assert 'width="100%"' in demo_source
    assert 'height="min(74vw, 560px)"' in demo_source
    assert hashlib.sha256(font.read_bytes()).hexdigest() == (
        "b24f1812584816958afcf22e22d08e44318c5e51651e25d2438efdde389b33b1"
    )
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_file.read_text(encoding="utf-8")


def test_density_hero_toolbar_follows_reflex_color_mode() -> None:
    """Theme the hero toolbar from the host site's adaptive Radix tokens."""
    from xy_docs.demos.instrument_sans_density import xy_density_hero

    rendered = str(xy_density_hero())
    expected_tokens = {
        "--chart-modebar-bg": "var(--secondary-2)",
        "--chart-modebar-active": "var(--primary-a4)",
        "--chart-text": "var(--secondary-11)",
        "--chart-focus": "var(--primary-9)",
    }

    for name, value in expected_tokens.items():
        assert f'["{name}"] : "{value}"' in rendered


def test_public_docs_use_the_xy_namespace_without_the_legacy_alias() -> None:
    """Keep examples, generated references, and docs tests on the public name."""
    legacy_alias = "".join(("f", "c"))
    forbidden = (
        f"import xy as {legacy_alias}",
        f"{legacy_alias}.",
        f"data-{legacy_alias}-",
        f".{legacy_alias}-",
        f'namespace="{legacy_alias}"',
    )
    sources = {page.source_path for page in discover_docs(DOCS_CONFIG)}
    sources.update((DOCS_APP_ROOT / "xy_docs").rglob("*.py"))
    sources.update((DOCS_APP_ROOT / "tests").rglob("*.py"))

    violations = [
        f"{path.relative_to(DOCS_ROOT)}:{line_number}: {line.strip()}"
        for path in sorted(sources)
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            1,
        )
        if any(token in line for token in forbidden)
    ]

    assert not violations, "\n".join(violations)


def test_live_preview_markdown_builds_real_xy_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Compile every live preview through docgen and the static XY adapter."""
    app_payload_dir = DOCS_APP_ROOT / "assets" / "xy"
    app_payloads_before = {path: path.read_bytes() for path in app_payload_dir.glob("*.xyf")}
    monkeypatch.chdir(tmp_path)
    pages = [
        page
        for page in discover_docs(DOCS_CONFIG)
        if any(marker in page.content for marker in check_html_routes.LIVE_PREVIEW_MARKERS)
    ]

    assert pages
    referenced_payloads: set[str] = set()
    for page in pages:
        rendered = str(
            render_markdown(
                page.content,
                virtual_filepath=page.relative_path.as_posix(),
                filename=page.source_path.as_posix(),
            )
        )
        assert "XYChart" in rendered, page.relative_path
        assert "Interactive preview coming soon" not in page.content
        page_payloads = set(re.findall(r'src:"(?:/docs/xy)?/xy/([^"]+\.xyf)"', rendered))
        assert page_payloads, page.relative_path
        referenced_payloads.update(page_payloads)

    generated_payloads = {path.name for path in (tmp_path / "assets" / "xy").glob("*.xyf")}
    assert generated_payloads == referenced_payloads
    assert {
        path: path.read_bytes() for path in app_payload_dir.glob("*.xyf")
    } == app_payloads_before


def test_complete_styling_examples_render_live_previews() -> None:
    """Do not show component-producing styling examples as source code only."""
    violations: list[str] = []
    for path in sorted((DOCS_ROOT / "styling").glob("*.md")):
        content = path.read_text(encoding="utf-8")
        for fence, body in re.findall(r"~~~(python[^\n]*)\n(.*?)\n~~~", content, re.DOTALL):
            if re.search(r"^def\s+\w+\(", body, re.MULTILINE) and "demo exec" not in fence:
                violations.append(f"{path.relative_to(DOCS_ROOT)}: {fence}")

    assert not violations, "\n".join(violations)


def test_single_chart_styling_demos_keep_only_the_parent_preview_card() -> None:
    """Keep Live Demo chrome while avoiding a second chart-owned surface."""
    gallery = (DOCS_ROOT / "styling/gallery.md").read_text(encoding="utf-8")
    blocks = re.findall(r"~~~(python[^\n]*)\n(.*?)\n~~~", gallery, re.DOTALL)
    long_legend = next(
        body for _fence, body in blocks if "long_legend_edge_tooltip_preview" in body
    )
    facets = next(body for _fence, body in blocks if "styled_facet_preview" in body)

    chrome_slots = (DOCS_ROOT / "styling/chrome-slots.md").read_text(encoding="utf-8")
    chrome_blocks = re.findall(r"~~~(python[^\n]*)\n(.*?)\n~~~", chrome_slots, re.DOTALL)
    tailwind_chrome = next(
        body for _fence, body in chrome_blocks if "tailwind_chrome_preview" in body
    )

    assert "rounded-2xl border border-slate-200 bg-white" not in long_legend
    assert "overflow-hidden rounded-xl border border-slate-200" not in facets
    assert "rounded-xl border border-slate-200 bg-white" not in tailwind_chrome

    content = """~~~python demo exec
import reflex as rx

def one_chart_preview():
    return rx.box("chart", width="100%")
~~~"""
    rendered = str(
        XyDocsMarkdownTransformer(
            virtual_filepath="docs/styling/test.md",
            filename="docs/styling/test.md",
        ).transform(parse_document(content))
    )
    parent_card = (
        'className:"flex flex-col p-6 rounded-xl overflow-x-auto border '
        'border-secondary-4 bg-secondary-2 items-center justify-center w-full"'
    )
    assert rendered.count(parent_card) == 1


def test_styling_demos_pair_light_surfaces_with_readable_text() -> None:
    """Prevent light demo panels from inheriting low-contrast dark-mode text."""
    violations: list[str] = []
    for path in sorted((DOCS_ROOT / "styling").glob("*.md")):
        content = path.read_text(encoding="utf-8")
        for _fence, body in re.findall(
            r"~~~(python demo exec[^\n]*)\n(.*?)\n~~~",
            content,
            re.DOTALL,
        ):
            if "bg-white" in body and "dark:bg" not in body:
                violations.append(f"{path.relative_to(DOCS_ROOT)}: unpaired bg-white")
            if re.search(r'(?:plot_background|"background")\s*[:=]\s*"#f', body):
                violations.append(f"{path.relative_to(DOCS_ROOT)}: fixed light background")
            if '"background": "rgb(255 255 255' in body and '"color":' not in body:
                violations.append(f"{path.relative_to(DOCS_ROOT)}: light component without color")

    assert not violations, "\n".join(violations)

    gallery = (DOCS_ROOT / "styling/gallery.md").read_text(encoding="utf-8")
    assert '"background": "var(--chart-bg)"' in gallery
    assert '"colorbar_tick": {"color": "var(--chart-text)"}' in gallery


@pytest.mark.parametrize(
    ("relative_path", "demo_name"),
    (
        ("overview/first-chart.md", "first_chart_demo"),
        ("core-concepts/index.md", "composition_model_demo"),
    ),
)
def test_beginner_examples_use_docdemos(
    relative_path: str,
    demo_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep beginner code and its live result together in a DocDemo."""
    source_path = DOCS_ROOT / relative_path
    content = source_path.read_text(encoding="utf-8")
    live_blocks = [
        block
        for block in parse_document(content).blocks
        if isinstance(block, CodeBlock)
        and block.language == "python"
        and {"demo", "exec"} <= set(block.flags)
    ]

    assert len(live_blocks) == 1
    assert "demo-only" not in live_blocks[0].flags
    assert demo_name in live_blocks[0].content
    assert "reflex_xy.chart" in live_blocks[0].content

    export_calls: list[tuple[tuple, dict]] = []

    def forbid_export(*args, **kwargs) -> None:
        export_calls.append((args, kwargs))
        msg = "DocDemo executed chart.to_html()"
        raise AssertionError(msg)

    if relative_path == "overview/first-chart.md":
        assert 'if __name__ == "__main__":' in live_blocks[0].content
        assert 'chart.to_html("scatter.html")' in live_blocks[0].content
        monkeypatch.setattr(xy.Chart, "to_html", forbid_export)

    monkeypatch.chdir(tmp_path)
    rendered = str(
        render_markdown(
            content,
            virtual_filepath=f"tests/docdemo/{relative_path}",
            filename=source_path.as_posix(),
        )
    )

    shell = 'className:"py-4 gap-4 flex flex-col w-full"'
    preview = 'className:"flex flex-col p-6 rounded-xl overflow-x-auto border border-secondary-4 bg-secondary-2 items-center justify-center w-full"'
    assert rendered.count(shell) == 1
    assert rendered.count(preview) == 1
    assert rendered.count("XYChart") == 1
    assert rendered.index(shell) < rendered.index(preview)
    assert demo_name in rendered
    assert export_calls == []
    assert not (tmp_path / "scatter.html").exists()


def test_installation_uses_uv_first_package_manager_tabs() -> None:
    """Present install commands as tabs with uv selected by default."""
    source_path = DOCS_ROOT / "overview" / "installation.md"
    rendered = str(
        render_markdown(
            source_path.read_text(encoding="utf-8"),
            virtual_filepath="overview/installation.md",
            filename=source_path.as_posix(),
        )
    )

    assert 'defaultValue:"tab1"' in rendered
    assert rendered.count('className:"pill-tab"') == 2
    assert rendered.index('value:"tab1"},"uv"') < rendered.index('value:"tab2"},"pip"')
    assert 'code:"uv add xy"' in rendered
    assert 'code:"python -m pip install xy"' in rendered


def test_chart_gallery_grid_renders_every_type_with_bounded_live_previews(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Show every chart type without exceeding the live WebGL context budget."""
    app_payload_dir = DOCS_APP_ROOT / "assets" / "xy"
    app_payloads_before = {path: path.read_bytes() for path in app_payload_dir.glob("*.xyf")}
    monkeypatch.chdir(tmp_path)

    rendered = str(chart_gallery_grid())
    chart_section = next(
        leaves for title, _landing_route, _icon, leaves in DOCS_SECTIONS if title == "Chart Gallery"
    )
    assert len(chart_section) == 9
    assert rendered.count("XYChart") == 9
    assert rendered.count(" chart guide") == 28
    assert rendered.count("dangerouslySetInnerHTML") == 19
    assert rendered.count('id:"xy-chart-gallery"') == 1
    assert rendered.count("main:has(#xy-chart-gallery) > div:has(#toc-navigation)") == 1
    assert rendered.count("main:has(#xy-chart-gallery) > div:has(article #xy-chart-gallery)") == 1
    assert rendered.count("display: none") == 1
    assert rendered.count("max-width: 88rem") == 1
    assert rendered.count("2xl:grid-cols-3") == 9
    assert rendered.count("h-[220px]") == 47
    assert rendered.count('["height"] : "220px"') == 9
    for chart_type in (
        "Line",
        "Area",
        "Step",
        "Stairs",
        "Scatter",
        "Bar",
        "Column",
        "Histogram",
        "ECDF",
        "Box",
        "Violin",
        "Hexbin",
        "Heatmap",
        "Contour",
        "Error Band",
        "Error Bar",
        "Stem",
        "Segments",
        "Threshold",
        "Triangle Mesh",
        "Horizontal Line",
        "Vertical Line",
        "Bands",
        "Callout",
        "Arrow",
        "Label",
        "Text",
        "Threshold Zone",
        "Facet Chart",
        "Layered Marks",
    ):
        assert chart_type in rendered
    for _title, route in chart_section:
        assert f'to:"{route}"' in rendered
        assert f'to:"/docs/xy{route}"' not in rendered

    payloads = list((tmp_path / "assets" / "xy").glob("*.xyf"))
    assert len(payloads) == 9
    assert all(path.read_bytes().startswith(b"XYBF") for path in payloads)
    assert {
        path: path.read_bytes() for path in app_payload_dir.glob("*.xyf")
    } == app_payloads_before


def test_chart_gallery_combines_only_the_requested_related_tiles() -> None:
    """Merge Step/Stairs and Bar/Column without collapsing other chart types."""
    titles = {title for title, _description, _route, _chart_factory, _live in _iter_gallery_items()}

    assert len(titles) == 28
    assert {"Step + Stairs", "Bar + Column"} <= titles
    assert {"Step", "Stairs", "Bar", "Column"}.isdisjoint(titles)
    assert {
        "Box",
        "Violin",
        "Hexbin",
        "Heatmap",
        "Contour",
        "Error Band",
        "Error Bar",
        "Facet Chart",
        "Layered Marks",
    } <= titles


def test_chart_gallery_hides_the_modebar_from_every_preview() -> None:
    """Keep compact gallery tiles focused on the chart itself."""
    for _title, _description, _route, chart_factory, _live in _iter_gallery_items():
        chart = _gallery_chart(chart_factory)
        modebars = [child for child in chart.children if type(child).__name__ == "Modebar"]
        assert len(modebars) == 1
        assert modebars[0].show is False


def test_chart_gallery_uses_only_purple_and_gray() -> None:
    """Keep every rendered gallery preview inside one restrained palette."""
    svg_paint = re.compile(r"#[0-9a-fA-F]{6}|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,[^)]*)?\)")

    def _paint_rgb(paint: str) -> tuple[int, int, int]:
        if paint.startswith("#"):
            red, green, blue = bytes.fromhex(paint[1:])
            return red, green, blue
        red, green, blue = map(int, re.findall(r"\d+", paint)[:3])
        return red, green, blue

    def _is_purple_or_gray(rgb: tuple[int, int, int]) -> bool:
        red, green, blue = rgb
        is_gray = max(rgb) - min(rgb) <= 18
        is_purple = blue > red and blue > green and red + 8 >= green
        return is_gray or is_purple

    charts = {
        title: chart_factory()
        for title, _description, _route, chart_factory, _live in _iter_gallery_items()
    }
    assert all(
        any(type(child).__name__ == "Theme" for child in chart.children)
        for chart in charts.values()
    )

    violations = {
        title: sorted(
            paint
            for paint in svg_paint.findall(chart.to_svg())
            if not _is_purple_or_gray(_paint_rgb(paint))
        )
        for title, chart in charts.items()
    }

    assert not {title: paints for title, paints in violations.items() if paints}


def test_density_grid_heatmap_uses_only_purple_truecolor() -> None:
    """Keep the live density preview on one cohesive purple ramp."""
    heatmap_factory = next(
        chart_factory
        for title, _description, _route, chart_factory, _live in _iter_gallery_items()
        if title == "Heatmap"
    )
    heatmap = heatmap_factory()
    mark = next(child for child in heatmap.children if child.kind == "heatmap")
    colors = {tuple(color) for row in mark.props["z"] for color in row}

    assert (255, 255, 255) not in colors
    assert colors == {
        (237, 233, 254),
        (196, 181, 253),
        (167, 139, 250),
        (110, 86, 207),
        (101, 80, 185),
    }
    assert all(blue > red and blue > green for red, green, blue in colors)


def test_density_grid_hexbin_replaces_white_bins_with_light_purple() -> None:
    """Keep every occupied Hexbin visible as a shade of purple."""
    hexbin_factory = next(
        chart_factory
        for title, _description, _route, chart_factory, _live in _iter_gallery_items()
        if title == "Hexbin"
    )
    hexbin = hexbin_factory()
    raw_svg = hexbin.to_svg()
    responsive_svg = _responsive_gallery_svg(hexbin)

    assert "rgb(252,251,253)" in raw_svg
    assert "rgb(252,251,253)" not in responsive_svg
    assert "var(--primary-7)" in responsive_svg
    assert "rgb(63,0,125)" in responsive_svg


def test_chart_gallery_previews_follow_the_site_color_mode() -> None:
    """Keep live and static gallery chrome readable in light and dark modes."""
    charts = [
        chart_factory()
        for _title, _description, _route, chart_factory, _live in _iter_gallery_items()
    ]
    expected_theme = {
        "--chart-modebar-bg": "var(--secondary-2)",
        "--chart-modebar-active": "var(--primary-a4)",
        "--chart-focus": "var(--primary-9)",
        "--chart-bg": "transparent",
        "--chart-grid": "var(--secondary-a5)",
        "--chart-axis": "var(--secondary-a8)",
        "--chart-text": "var(--secondary-11)",
        "--chart-crosshair": "var(--primary-a9)",
        "--chart-selection": "var(--primary-9)",
        "--chart-selection-fill": "var(--primary-a3)",
    }

    for chart in charts:
        theme = next(child for child in chart.children if type(child).__name__ == "Theme")
        assert theme.style == expected_theme

        svg = _responsive_gallery_svg(chart)
        assert "rgba(32,32,32,0.14)" not in svg
        assert "rgba(32,32,32,0.55)" not in svg
        assert "rgba(32,32,32,0.85)" not in svg
        assert "var(--secondary-a5)" in svg
        assert "var(--secondary-a8)" in svg
        assert "var(--secondary-11)" in svg


def test_live_preview_route_validator_requires_real_xy_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Accept a compiled XYChart only when its referenced payload is valid."""
    client_root = tmp_path / "client"
    module_path = tmp_path / "route.jsx"
    payload_path = client_root / "docs" / "xy" / "xy" / "abc123.xyf"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(b"XYBF\x01\x00payload")
    module_path.write_text(
        'jsx(XYChart,{src:"/docs/xy/xy/abc123.xyf"})',
        encoding="utf-8",
    )
    monkeypatch.setattr(check_html_routes, "CLIENT_ROOT", client_root)

    check_html_routes.validate_live_preview("/charts/scatter/", module_path)


@pytest.mark.parametrize(
    ("module_source", "payload", "error"),
    (
        ('src:"/docs/xy/xy/abc123.xyf"', b"XYBFpayload", "does not compile XYChart"),
        ("jsx(XYChart,{})", None, "has no static XY payload"),
        (
            'jsx(XYChart,{src:"/docs/xy/xy/abc123.xyf"})',
            None,
            "Missing XY payload",
        ),
        (
            'jsx(XYChart,{src:"/docs/xy/xy/abc123.xyf"})',
            b"not-an-xy-payload",
            "Invalid XY payload",
        ),
    ),
)
def test_live_preview_route_validator_rejects_incomplete_builds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module_source: str,
    payload: bytes | None,
    error: str,
) -> None:
    """Reject routes missing the component, reference, file, or XY payload header."""
    client_root = tmp_path / "client"
    module_path = tmp_path / "route.jsx"
    module_path.write_text(module_source, encoding="utf-8")
    if payload is not None:
        payload_path = client_root / "docs" / "xy" / "xy" / "abc123.xyf"
        payload_path.parent.mkdir(parents=True)
        payload_path.write_bytes(payload)
    monkeypatch.setattr(check_html_routes, "CLIENT_ROOT", client_root)

    with pytest.raises(RuntimeError, match=error):
        check_html_routes.validate_live_preview("/charts/scatter/", module_path)


@pytest.mark.xfail(
    not EXPORTED_SITEMAP.is_file(),
    reason="Build the XY docs frontend before validating Markdown links.",
    run=False,
)
def test_xy_markdown_docs_links_match_exported_sitemap() -> None:
    """Validate every XY docs link in every Markdown source against the sitemap."""
    valid_routes = _sitemap_routes(EXPORTED_SITEMAP)
    errors: list[str] = []

    for path in _markdown_files(DOCS_ROOT):
        source = path.read_text(encoding="utf-8")
        try:
            document = parse_document(source)
        except Exception as error:
            errors.append(f"{path}: failed to parse Markdown ({error})")
            continue

        cursor = 0
        for link in _walk_blocks(document.blocks):
            target_path = urlparse(link.target).path
            if not (target_path == "/docs/xy" or target_path.startswith("/docs/xy/")):
                continue
            line, cursor = _link_line(source, link.target, cursor)
            location = f"{path}:{line}" if line else str(path)
            route = _normalize_xy_docs_path(link.target)
            if route is None:
                errors.append(f"{location}: wrong docs prefix: {link.target}")
                continue
            if "_" in route:
                errors.append(f"{location}: underscore in route: {link.target}")
            if route not in valid_routes:
                errors.append(f"{location}: missing route: {link.target}")

    assert not errors, "\n".join(errors)


def test_xy_sitemap_path_normalization_requires_the_exact_frontend_path() -> None:
    """Normalize canonical locations without accepting sibling docs sites."""
    assert _normalize_xy_docs_path("https://reflex.dev/docs/xy/") == "/"
    assert (
        _normalize_xy_docs_path("https://reflex.dev/docs/xy/charts/scatter/?source=test#example")
        == "/charts/scatter"
    )
    assert _normalize_xy_docs_path("https://reflex.dev/docs/charts/") is None


def test_xy_link_walker_resolves_references_and_ignores_code_fences() -> None:
    """Match rendered Markdown semantics instead of scanning source text."""
    document = parse_document(
        "See [charts][charts].\n\n"
        "[charts]: /docs/xy/charts/\n\n"
        "```markdown\n[not a link](/docs/xy/missing/)\n```\n"
    )

    assert [link.target for link in _walk_blocks(document.blocks)] == ["/docs/xy/charts/"]


def test_xy_sidebar_reuses_memoized_official_navigation_rows() -> None:
    """Render quick tabs plus three labeled groups of direct accordions."""
    component = xy_docs_sidebar_comp(url="/core-concepts/axes-and-scales/")
    assert isinstance(component, MemoComponent)

    instance = str(xy_docs_sidebar("/core-concepts/axes-and-scales/"))
    rendered = str(xy_docs_sidebar_comp._definition.component)

    assert "/core-concepts/axes-and-scales/" in instance
    assert re.findall(
        r'jsx\(RadixThemesText,\{as:"p",className:"m-0 text-sm font-\[525\]"\},"([^"]+)"\)',
        rendered,
    ) == [title for title, _route, _icon, _leaves in DOCS_SECTIONS]
    expected_leaf_count = sum(
        len(leaves) + int(not any(route == landing_route for _title, route in leaves))
        for _title, landing_route, _icon, leaves in DOCS_SECTIONS
    )
    assert rendered.count('jsx("details"') == len(DOCS_SECTIONS)
    assert rendered.count('jsx("summary"') == len(DOCS_SECTIONS)
    assert rendered.count("group/details") == len(DOCS_SECTIONS)
    assert rendered.count("guideMarginClass") == expected_leaf_count
    assert (
        tuple(
            section
            for _group_title, _group_route, sections in SIDEBAR_SECTION_GROUPS
            for section in sections
        )
        == DOCS_SECTIONS
    )
    for group_title in ("Learning", "Examples", "Other"):
        assert group_title in rendered
    for category, route in (
        ("Learn", "/"),
        ("Build", "/charts/"),
        ("API Reference", "/api-reference/"),
    ):
        assert f'aria-label":"Navigate to {category}"' in rendered
        assert f'to:"{route}"' in rendered
    assert 'aria-label":"Navigate to Charts"' not in rendered
    assert 'aria-label":"Navigate to Components"' not in rendered
    assert "Axes and Scales" in rendered
    assert ">XY<" not in rendered


def test_xy_mobile_navbar_uses_the_official_drawer_button() -> None:
    """Match the official navbar while retaining its mobile drawer trigger."""
    component = xy_docs_navbar()
    assert isinstance(component, MemoComponent)

    rendered = str(xy_docs_navbar._definition.component)

    assert 'href:"/"' in rendered
    assert '"aria-label":"Reflex XY"' in rendered
    assert "M29 16H32V10H39V7H32V4H39V1H29V16" in rendered
    assert 'href:"/docs/"' in rendered
    assert 'href:"/docs/ai/overview/best-practices/"' in rendered
    assert 'href:"/docs/getting-started/introduction/"' in rendered
    assert 'href:"/docs/hosting/deploy-quick-start/"' in rendered
    assert 'href:"/docs/xy/"' in rendered
    assert 'variant:"ghost"},"XY"' in rendered
    assert "Open sidebar" in rendered
    assert "Menu01Icon" in rendered
    assert "Cancel01Icon" in rendered
    assert "Mobile documentation navigation" not in rendered
    assert "<details" not in rendered
    assert "<summary" not in rendered


def test_xy_breadcrumb_opens_the_official_docs_sidebar_drawer() -> None:
    """Reuse the complete memoized sidebar in the mobile page-header drawer."""
    page = next(page for page in discover_docs(DOCS_CONFIG) if page.route == "/charts/scatter/")

    rendered = str(xy_docs_breadcrumb(page, xy_docs_sidebar(page.route)))

    assert "Drawer.Root" in rendered
    assert "Drawer.Trigger" in rendered
    assert "Charts" in rendered
    assert "Scatter" in rendered
    assert "/charts/" in rendered
    assert "/charts/scatter/" in rendered
    assert "ArrowDown01Icon" in rendered


def test_xy_breadcrumb_shortens_the_modebar_page_label() -> None:
    """Keep the longest component route from overflowing the mobile header."""
    page = next(
        page
        for page in discover_docs(DOCS_CONFIG)
        if page.route == "/components/modebars-and-interaction-controls/"
    )

    rendered = str(xy_docs_breadcrumb(page, xy_docs_sidebar(page.route)))

    assert "Modebars & Controls" in rendered
    assert "Modebars And Interaction Controls" not in rendered


def test_xy_footer_reuses_official_footer_with_source_aware_links() -> None:
    """Keep the complete official footer while targeting the XY repository."""
    page = next(page for page in discover_docs(DOCS_CONFIG) if page.route == "/charts/")

    rendered = str(xy_docs_footer(page))

    assert "https://github.com/reflex-dev/xy/issues/new" in rendered
    assert "Issue with reflex.dev/docs/xy/charts/" in rendered
    assert "Path: /docs/xy/charts/" in rendered
    assert "https://github.com/reflex-dev/xy/blob/main/docs/charts/index.md" in rendered


def test_component_api_uses_generated_shared_tables() -> None:
    """Render every public factory group through the shared API table."""
    groups = (
        (MARKS, marks_api),
        (AXES_AND_ANNOTATIONS, axes_and_annotations_api),
        (CHROME_AND_BEHAVIOR, chrome_and_behavior_api),
    )

    for functions, render in groups:
        rendered = str(render())
        for function in functions:
            assert f"xy.{function.__name__}" in rendered
        assert "Props" in rendered
        assert "Description" in rendered

    containers = str(chart_containers_api())
    assert "Shared chart props" in containers
    assert "title" in containers
    assert "link_group" in containers
    assert "kind" not in containers

    factories = str(chart_factories_api())
    for group_name, group_factories in CHART_FACTORY_GROUPS:
        assert group_name in factories
        for factory in group_factories:
            assert f"xy.{factory.__name__}" in factories
    assert "Props" in factories
    assert "Description" in factories


def test_documented_factories_describe_every_parameter() -> None:
    """Keep generated API descriptions sourced from complete docstrings."""
    factories = (
        *MARKS,
        *AXES_AND_ANNOTATIONS,
        *CHROME_AND_BEHAVIOR,
        xy.facet_chart,
    )

    for factory in factories:
        docstring = inspect.getdoc(factory) or ""
        assert "Args:" in docstring, factory.__name__
        for parameter in inspect.signature(factory).parameters.values():
            assert f"{parameter.name}:" in docstring, (
                factory.__name__,
                parameter.name,
            )
