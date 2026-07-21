"""Tests for the standalone XY documentation application."""

import hashlib
import importlib.util
import inspect
import re
import tomllib
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
from xy_docs.breadcrumb import _breadcrumb_parts, xy_docs_breadcrumb
from xy_docs.config import DOCS_CONFIG, DOCS_NAVIGATION, DOCS_REDIRECTS, DOCS_SECTIONS
from xy_docs.constants import PUBLIC_DOCS_URL, PUBLIC_XY_VERSION, SOCIAL_IMAGE_URL
from xy_docs.footer import xy_docs_footer
from xy_docs.gallery import (
    _GALLERY_GROUPS,
    _gallery_preview_svg,
    chart_gallery_grid,
)
from xy_docs.markdown import XyDocsMarkdownTransformer, render_xy_markdown_page
from xy_docs.navbar import XY_GITHUB_STARS, XY_REPOSITORY_URL, xy_docs_navbar
from xy_docs.sidebar import (
    SIDEBAR_SECTION_GROUPS,
    xy_docs_sidebar,
    xy_docs_sidebar_comp,
)
from xy_docs.xy_docs import _DOCS_ROUTES, app

import xy
from xy.components import _MARK_APPLIERS

SITEMAP_NAMESPACE = {"sitemap": "https://www.sitemaps.org/schemas/sitemap/0.9"}
DOCS_APP_ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = DOCS_APP_ROOT.parent
EXPORTED_SITEMAP = DOCS_APP_ROOT / ".web" / "public" / "sitemap.xml"
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
    """Discover the exact nine-section, two-level public information architecture."""
    assert tuple(title for title, _route, _icon, _leaves in DOCS_SECTIONS) == (
        "Overview",
        "Core Concepts",
        "Styling",
        "Chart Gallery",
        "Components",
        "Integrations",
        "Guides",
        "Advanced",
        "Reference",
    )
    assert (
        next(
            landing_route
            for title, landing_route, _icon, _leaves in DOCS_SECTIONS
            if title == "Chart Gallery"
        )
        == "/overview/gallery/"
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
    assert set(section_routes) == set(DOCS_NAVIGATION)
    assert DOCS_NAVIGATION[:4] == (
        "/",
        "/overview/installation/",
        "/overview/first-chart/",
        "/guides/dataframes-and-real-data/",
    )
    assert DOCS_NAVIGATION[-1] == "/overview/benchmarks/"
    assert "/overview/gallery/" in DOCS_NAVIGATION
    assert "/charts/" not in DOCS_NAVIGATION
    core_concept_leaves = next(
        leaves for title, _route, _icon, leaves in DOCS_SECTIONS if title == "Core Concepts"
    )
    assert ("Animations", "/core-concepts/animations/") in core_concept_leaves
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
    assert "literal class strings in Tailwind's default scan" in content
    assert "original Python or Markdown file" in content
    assert "charts produced from a token or `Var`" in content
    assert "safelist it in the host app" in content


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


def test_styling_gallery_covers_retained_advanced_surfaces() -> None:
    """Keep the focused gallery explicit about its retained advanced surfaces."""
    content = (DOCS_ROOT / "styling/gallery.md").read_text(encoding="utf-8").lower()

    required_marks = {
        "area",
        "ecdf",
        "heatmap",
        "contour",
        "hexbin",
        "error_band",
        "errorbar",
        "segments",
        "stem",
        "triangle_mesh",
    }
    assert all(f"`{mark}`" in content for mark in required_marks)

    required_surfaces = {
        "custom legend",
        "styled cursor tooltip",
        "reduction badge",
        "facet_chart",
        "to_html(custom_css=",
        "xy.tooltip(",
    }
    assert all(surface in content for surface in required_surfaces)
    assert "colorbar_bar" in content
    assert "colorbar_tick" in content
    assert "colorbar_title" in content


def test_chart_examples_are_wide_copyable_demos_without_a_toc() -> None:
    """Keep the dedicated examples page spacious and copy-ready."""
    page = next(page for page in discover_docs(DOCS_CONFIG) if page.route == "/styling/examples/")
    document = parse_document(page.content)
    demos = [
        block
        for block in document.blocks
        if isinstance(block, CodeBlock)
        and {"demo", "exec", "toggle", "preview-code"} <= set(block.flags)
    ]

    assert len(demos) >= 4
    assert all(block.content.count("def ") == 1 for block in demos)
    assert all("reflex_xy.chart" in block.content for block in demos)
    assert all('"grid_opacity": 0' in block.content for block in demos)
    assert all('"axis_color": "#00000000"' in block.content for block in demos)
    assert all("xy.vline(" not in block.content for block in demos)
    assert sum("xy.area(" in block.content for block in demos) >= 2
    assert sum("xy.bar(" in block.content or "xy.column(" in block.content for block in demos) >= 4

    stacked_demo = next(block for block in demos if "def stacked_product_mix" in block.content)
    assert stacked_demo.content.count("xy.column(") == 3
    assert stacked_demo.content.count("corner_radius=(6, 0)") == 1
    assert "base=growth_base" in stacked_demo.content
    assert "base=enterprise_base" in stacked_demo.content

    rendered_page = str(render_xy_markdown_page(page))
    demo_count = len(demos)
    assert rendered_page.count("XYChart") == demo_count + 6
    assert rendered_page.count('value:"preview"') == demo_count * 2
    assert rendered_page.count('value:"code"') == demo_count * 2
    assert rendered_page.count("xy-example-tab cursor-pointer") == demo_count * 2
    assert rendered_page.count("xy-example-tab-list inline-flex") == demo_count
    assert "xy-chart-examples" in rendered_page
    assert "max-width: 88rem" in rendered_page
    assert "div:has(#toc-navigation)" in rendered_page
    assert "display: none" in rendered_page
    assert rendered_page.count('id:"responsive-combo-chart"') == 1
    assert rendered_page.count('id:"responsive-combo-chart-demo"') == 1
    assert "var(--chart-" not in page.content
    assert "currentColor" not in page.content
    assert '"transparent"' not in page.content


def test_animation_replay_demos_reuse_example_chrome_and_controls() -> None:
    """Keep animation demos visually aligned with the polished examples."""
    page = next(
        page for page in discover_docs(DOCS_CONFIG) if page.route == "/core-concepts/animations/"
    )
    content = page.content

    assert content.count("ui.button(") == 8
    assert content.count('ui.icon("PlayIcon"') == 5
    assert content.count('variant="outline"') == 8
    assert content.count("flex w-full justify-end px-4 pt-4 sm:px-5 sm:pt-5") == 3
    assert "rx.button(" not in content
    assert 'aria_label="Play mark override animation"' in content
    assert 'aria_label="Play lifecycle animation"' in content
    assert "2 exits · 2 enters · 3 retained" in content
    assert '"sales": [54, 16, 46, 22, 60]' in content
    assert "random.uniform(-0.75, 0.75)" in content
    assert "StreamingAnimationDemo.append_points(1)" in content
    assert "StreamingAnimationDemo.append_points(5)" in content
    assert "StreamingAnimationDemo.append_points(12)" in content
    assert "linear-gradient(#8e51ff4d 5%, #8e51ff00 95%)" in content
    assert '"axis_color": "#00000000"' in content

    rendered = str(render_xy_markdown_page(page))
    assert rendered.count("border border-secondary-a4 bg-secondary-1") >= 8
    assert rendered.count("Play animation") >= 5


def test_palette_playground_drives_a_reactive_chart_grid() -> None:
    """Keep the preset palettes wired to the state-backed XY figures."""
    from xy_docs.playground import PLAYGROUND_PALETTES, ChartPlaygroundState, chart_playground

    rendered_page = str(chart_playground())

    assert rendered_page.count("XYChart") == 6
    assert 'type:"color"' not in rendered_page
    assert rendered_page.count("apply_palette") == len(PLAYGROUND_PALETTES) == 5
    assert "xy-palette-playground" in rendered_page
    assert "grid grid-cols-1 gap-5 xl:grid-cols-2" in rendered_page
    for label, palette in PLAYGROUND_PALETTES:
        assert label in rendered_page
        assert len(palette) == 3
        assert all(re.fullmatch(r"#[0-9a-f]{6}", color) for color in palette)
    assert {
        "momentum",
        "comparison",
        "product_mix",
        "funnel",
        "traffic_share",
        "channel_mix",
    } <= set(ChartPlaygroundState.computed_vars)
    assert "div:has(#toc-navigation)" in rendered_page
    assert "display: none" in rendered_page


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
    """Keep the introductory theme demo neutral, vivid, and mode-responsive."""
    content = (DOCS_ROOT / "styling/themes-and-tokens.md").read_text(encoding="utf-8")
    demo = content.split("~~~python demo exec", 1)[1].split("~~~", 1)[0]

    for token in (
        "--demo-surface:#ffffff",
        "dark:[--demo-surface:#000000]",
        "--demo-grid:#e5e7eb",
        'color="#f43f5e"',
        'fill="linear-gradient(#f43f5e4d 5%, #f43f5e00 95%)"',
        "xy.legend(show=False)",
        '"grid_opacity": 0',
    ):
        assert token in demo


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


def test_what_is_xy_restores_the_sdf_hero_and_ends_with_a_short_pitch() -> None:
    """Keep the original visual opening and the merged Why XY section."""
    content = (DOCS_ROOT / "index.md").read_text(encoding="utf-8")

    heading = content.index("# What is `xy`?")
    styling = content.index("**Completely customizable.**")
    hero = content.index("~~~python demo-only exec")
    early_alpha = content.index("**Early alpha.**")
    start_here = content.index("## Start here")
    why_xy = content.index("## Why XY")
    why_copy = content[why_xy:]

    assert heading < styling < hero < early_alpha < start_here < why_xy
    assert content.rfind("\n## ") + 1 == why_xy
    assert "from xy_docs.demos.xy_sdf_plots import xy_sdf_plot_grid" in content
    assert "All four interactive charts" in content
    assert "View the customizable Python source" in content
    assert "/docs/xy/overview/first-chart/" in content
    assert "/docs/xy/overview/why-xy/" not in content
    assert not (DOCS_ROOT / "overview/why-xy.md").exists()
    assert len(why_copy.split()) < 230
    assert "10-million-point launch benchmark" in why_copy
    assert "Compare by workflow, not by slogan" not in why_copy


def test_core_concepts_keep_essential_binding_content_visible() -> None:
    """Render core semantics as normal content and avoid teaching default no-ops."""
    data = (DOCS_ROOT / "core-concepts/data.md").read_text(encoding="utf-8")
    configuration = (DOCS_ROOT / "core-concepts/configuration.md").read_text(encoding="utf-8")
    overview = (DOCS_ROOT / "index.md").read_text(encoding="utf-8")

    assert "## Color strings" in data
    assert "### Color strings" not in data
    assert "~~~md alert info\n## Color strings" not in data
    assert "density=None" not in configuration
    assert "~~~md alert warning\n**Early alpha.**" in overview
    assert "### Early alpha" not in overview


def test_sdf_demo_assets_remain_reproducible_for_deeper_examples() -> None:
    """Keep the cached SDF demo and its licensed font reproducible."""
    demo_source = (DOCS_APP_ROOT / "xy_docs/demos/xy_sdf_plots.py").read_text(encoding="utf-8")
    font = DOCS_APP_ROOT / "xy_docs/assets/InstrumentSans-wdth-wght.ttf"
    license_file = DOCS_APP_ROOT / "xy_docs/assets/OFL.txt"

    assert "sample_points: int = 50_000" in demo_source
    assert "density_points: int = 1_000_000" in demo_source
    assert "density_display_points: int = 250_000" in demo_source
    assert "@lru_cache(maxsize=4)" in demo_source
    assert (
        'class_name="grid w-full grid-cols-1 gap-0 overflow-hidden md:grid-cols-2"' in demo_source
    )
    assert "InstrumentSans-wdth-wght.ttf" in demo_source
    assert 'width="100%"' in demo_source
    assert 'height="auto"' in demo_source
    assert hashlib.sha256(font.read_bytes()).hexdigest() == (
        "b24f1812584816958afcf22e22d08e44318c5e51651e25d2438efdde389b33b1"
    )
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_file.read_text(encoding="utf-8")


def test_sdf_plot_grid_is_cached_and_uses_reflex_toolbar_tokens() -> None:
    """Build once while keeping every chart toolbar tied to Reflex tokens."""
    from dataclasses import replace

    from xy_docs.demos.xy_sdf_plots import (
        DEFAULT_CONFIG,
        build_sdf_plots,
        xy_sdf_plot_grid,
    )

    config = replace(
        DEFAULT_CONFIG,
        font_size=180,
        x_height_bins=12,
        sample_points=1_000,
        density_points=2_000,
        density_display_points=1_500,
        bin_min_count=2,
        heatmap_stride=4,
        contour_cells_per_bin=4,
    )
    first = build_sdf_plots(config)
    assert build_sdf_plots(config) is first
    assert first.reading_order == (
        first.bins_scatter,
        first.heatmap,
        first.contours,
        first.million_scatter,
    )
    density_mark = first.million_scatter.children[0]
    assert density_mark.kind == "scatter"
    assert len(density_mark.x) == config.density_display_points
    assert density_mark.props["density"] is False
    sizes = density_mark.props["size"]
    assert density_mark.props["size_range"] == (float(sizes.min()), float(sizes.max()))
    assert sizes.min() >= config.density_size_offset
    assert sizes.max() <= config.density_size_offset + config.density_size_scale

    rendered = str(xy_sdf_plot_grid(config))
    expected_tokens = {
        "--chart-modebar-bg": "var(--secondary-2)",
        "--chart-modebar-active": "var(--primary-a4)",
        "--chart-text": "var(--secondary-11)",
        "--chart-focus": "var(--primary-9)",
    }

    for name, value in expected_tokens.items():
        assert rendered.count(f'["{name}"] : "{value}"') == 4
    assert 'id:"xy-sdf-plot-grid"' in rendered
    assert "gap-0" in rendered


def test_sdf_heatmap_outside_support_uses_page_background() -> None:
    """Use the page surface outside support without changing the PDF ramp."""
    from xy_docs.demos import xy_sdf_plots as demo

    colors = demo._heatmap_colors(
        demo.np.array([[0.0, 1e-12, 1.0]]),
        demo.DEFAULT_CONFIG,
        demo.DEFAULT_PALETTE,
    )
    background = demo.DEFAULT_PALETTE.dark_background.removeprefix("#")
    expected = [int(background[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    assert demo.DEFAULT_PALETTE.dark_background == "#090A0B"
    assert colors[0, 0, :3] == pytest.approx(expected)
    assert colors[0, 1, :3] != pytest.approx(expected)
    assert colors[0, 2, :3] != pytest.approx(expected)
    assert demo.np.allclose(colors[..., 3], 1)


def test_sdf_distance_transform_is_exact_without_scipy() -> None:
    """Keep the signed-distance model exact without a heavyweight dependency."""
    from xy_docs.demos import xy_sdf_plots as demo

    mask = demo.np.array(
        [
            [True, True, True, True, True],
            [True, False, True, False, True],
            [True, True, True, True, True],
            [True, True, False, True, True],
        ]
    )
    zero_cells = demo.np.argwhere(~mask)
    expected = demo.np.empty(mask.shape, dtype=float)
    for cell in demo.np.ndindex(mask.shape):
        expected[cell] = demo.np.sqrt(demo.np.min(demo.np.sum((zero_cells - cell) ** 2, axis=1)))

    assert demo.np.allclose(demo._distance_transform_edt(mask), expected)

    manifest = tomllib.loads((DOCS_APP_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any(
        dependency.lower().startswith("scipy") for dependency in manifest["project"]["dependencies"]
    )


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


def test_every_core_concepts_python_example_renders_a_live_chart() -> None:
    """Keep Core Concepts examples visual instead of leaving code-only snippets."""
    violations: list[str] = []
    example_count = 0
    for path in sorted((DOCS_ROOT / "core-concepts").glob("*.md")):
        content = path.read_text(encoding="utf-8")
        for fence, body in re.findall(r"~~~(python[^\n]*)\n(.*?)\n~~~", content, re.DOTALL):
            example_count += 1
            if "demo exec" not in fence or "reflex_xy.chart" not in body:
                violations.append(f"{path.relative_to(DOCS_ROOT)}: {fence}")

    assert example_count == 23
    assert not violations, "\n".join(violations)


def test_single_chart_styling_demos_keep_only_the_parent_preview_card() -> None:
    """Keep one neutral preview surface without a nested chart-owned card."""
    gallery = (DOCS_ROOT / "styling/gallery.md").read_text(encoding="utf-8")
    blocks = re.findall(r"~~~(python[^\n]*)\n(.*?)\n~~~", gallery, re.DOTALL)
    trend = next(body for _fence, body in blocks if "trend_mark_atlas_preview" in body)
    facets = next(body for _fence, body in blocks if "styled_facet_preview" in body)

    chrome_slots = (DOCS_ROOT / "styling/chrome-slots.md").read_text(encoding="utf-8")
    chrome_blocks = re.findall(r"~~~(python[^\n]*)\n(.*?)\n~~~", chrome_slots, re.DOTALL)
    tailwind_chrome = next(
        body for _fence, body in chrome_blocks if "tailwind_chrome_preview" in body
    )

    assert "rounded-2xl border border-slate-200 bg-white" not in trend
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
    assert rendered.count("border-secondary-4") == 1
    assert rendered.count("bg-white") == 1
    assert rendered.count("dark:bg-black") == 1
    assert "bg-secondary-2" not in rendered


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
    ("relative_path", "demo_name", "expected_live_blocks"),
    (
        ("overview/first-chart.md", "first_chart_demo", 1),
        ("core-concepts/index.md", "composition_model_demo", 2),
    ),
)
def test_beginner_examples_use_docdemos(
    relative_path: str,
    demo_name: str,
    expected_live_blocks: int,
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

    assert len(live_blocks) == expected_live_blocks
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
    assert rendered.count(shell) == expected_live_blocks
    assert rendered.count(preview) == expected_live_blocks
    assert rendered.count("XYChart") == expected_live_blocks
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


def test_installation_distinguishes_supported_targets_from_pypi_artifacts() -> None:
    """Do not present missing release wheels as missing platform support."""
    content = (DOCS_ROOT / "overview" / "installation.md").read_text(encoding="utf-8")
    windows_row = next(line for line in content.splitlines() if line.startswith("| Windows |"))
    wasm_row = next(line for line in content.splitlines() if line.startswith("| WebAssembly |"))

    assert all(value in windows_row for value in ("`x86_64`", "`x86`", "`arm64`"))
    assert "| Supported | Not included |" in windows_row
    assert "Pyodide 0.29.4" in wasm_row
    assert "`wasm32` | Supported | Not accepted by PyPI |" in wasm_row
    assert "Windows is supported by XY's native core and release pipeline." in content
    assert "0.0.1 PyPI upload does not include Windows wheels" in content
    assert "runtime-verified Pyodide wheel" in content
    assert "`pyodide_2025_0_wasm32` platform" in content


def test_chart_gallery_grid_renders_every_type_as_inline_svg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Show every chart type as an editable preview without WebGL payloads."""
    app_payload_dir = DOCS_APP_ROOT / "assets" / "xy"
    app_payloads_before = {path: path.read_bytes() for path in app_payload_dir.glob("*.xyf")}
    monkeypatch.chdir(tmp_path)

    rendered = str(chart_gallery_grid())
    chart_section = next(
        leaves for title, _landing_route, _icon, leaves in DOCS_SECTIONS if title == "Chart Gallery"
    )
    assert len(chart_section) == 8
    assert "XYChart" not in rendered
    assert rendered.count("dangerouslySetInnerHTML") == 28
    assert rendered.count('id:"xy-chart-gallery"') == 1
    assert rendered.count("main:has(#xy-chart-gallery) > div:has(#toc-navigation)") == 1
    assert rendered.count("main:has(#xy-chart-gallery) > div:has(article #xy-chart-gallery)") == 1
    assert rendered.count("display: none") == 1
    assert rendered.count("max-width: 88rem") == 1
    assert rendered.count("2xl:grid-cols-3") == 8
    assert rendered.count("aspect-[320/232]") == 28
    assert rendered.count("shadow-large") == 28
    assert rendered.count("transition-bg") == 28
    assert "--gallery-preview-surface: #fff" in rendered
    assert "--gallery-preview-fill: #efeaff" in rendered
    assert "--gallery-preview-soft: #dccfff" in rendered
    assert "--gallery-preview-bar: #dccfff" in rendered
    assert "--gallery-preview-stroke: #a790f0" in rendered
    assert "--gallery-preview-strong: #8067d7" in rendered
    assert "--gallery-preview-muted" not in rendered
    assert "object-contain" not in rendered
    assert "object-center" not in rendered
    assert "xy-tailwind-bridge" not in rendered
    assert rendered.count("size:14") == 28
    assert "size:6" not in rendered
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
    for group in _GALLERY_GROUPS:
        if group.route is not None:
            assert f'to:"{group.route}"' in rendered
            assert f'"aria-label":"Open the {group.title} chart family guide"' in rendered
        for item in group.items:
            route = item.route or group.route
            assert route is not None
            assert f'to:"{route}' in rendered
            assert f'"aria-label":"Open the {item.title} guide"' in rendered
    assert '"aria-label":"Open the Bar, Column, and Scatter chart family guide"' not in rendered
    assert 'to:"/components/annotations/"' in rendered
    assert 'to:"/charts/annotations/"' not in rendered

    assert not list((tmp_path / "assets" / "xy").glob("*.xyf"))
    assert {
        path: path.read_bytes() for path in app_payload_dir.glob("*.xyf")
    } == app_payloads_before


def test_chart_gallery_inline_svgs_share_the_component_preview_style() -> None:
    """Keep all code-native previews on the Reflex 320 by 232 tile system."""
    previews = {
        item.title: _gallery_preview_svg(item.title)
        for group in _GALLERY_GROUPS
        for item in group.items
    }

    assert len(previews) == 28
    for svg in previews.values():
        assert 'viewBox="0 0 320 232"' in svg
        assert '<rect x="52" y="62" width="216" height="108" rx="12"' in svg
        assert "var(--gallery-preview-surface)" in svg
        assert "<style>" not in svg
        assert 'class="preview-' in svg
        assert "effect2_dropShadow" in svg

    rendered = str(chart_gallery_grid())
    assert rendered.count("#xy-chart-gallery .preview-fill { fill:") == 1
    assert rendered.count("#xy-chart-gallery .preview-line {") == 1

    assert "M109 142.5C81.5 142.5 67.5 83 42 83V172H284.5V100H276" in previews["Area"]
    assert "M42 83C67.5 83 81.5 142.5 109 142.5C136.5 142.5 140.5 103 160 103" in previews["Area"]
    assert previews["Scatter"].count("<circle ") == 14
    for scatter_tone in (
        "preview-scatter-low",
        "preview-scatter-mid",
        "preview-scatter-high",
    ):
        assert scatter_tone in previews["Scatter"]
        assert rendered.count(f"#xy-chart-gallery .{scatter_tone} {{") == 1


def test_chart_gallery_cards_link_to_family_pages_with_live_demo_anchors() -> None:
    """Anchor only chart types with dedicated live sections."""
    pages = {page.route: page for page in discover_docs(DOCS_CONFIG)}
    rendered = str(chart_gallery_grid())
    anchored_items: list[tuple[str, str]] = []

    for group in _GALLERY_GROUPS:
        if group.route is not None:
            assert "#" not in group.route
            assert group.route in pages

        for item in group.items:
            route = item.route or group.route
            assert route is not None
            assert "#" not in route
            assert route in pages
            destination = f"{route}#{item.fragment}" if item.fragment else route
            assert f'to:"{destination}"' in rendered
            if item.fragment:
                anchored_items.append((item.title, destination))

    assert anchored_items == [
        ("Step + Stairs", "/charts/line-and-area/#step-and-stairs"),
        ("ECDF", "/charts/distributions/#ecdf"),
        ("Box", "/charts/distributions/#box"),
        ("Violin", "/charts/distributions/#violin"),
        ("Hexbin", "/charts/density-and-grids/#hexbin"),
        ("Contour", "/charts/density-and-grids/#contour"),
        ("Segments", "/charts/specialized/#segments"),
        ("Triangle Mesh", "/charts/specialized/#triangle-mesh"),
        ("Threshold", "/components/annotations/#threshold"),
        ("Horizontal Line", "/components/annotations/#horizontal-line"),
        ("Bands", "/components/annotations/#bands"),
        ("Arrow", "/components/annotations/#arrow"),
        ("Label", "/components/annotations/#label"),
        ("Text", "/components/annotations/#text"),
        ("Facet Chart", "/charts/facets-and-layers/#facet-chart"),
    ]

    line_and_area = pages["/charts/line-and-area/"]
    assert "### Step and Stairs" in line_and_area.content
    assert "def step_and_stairs_demo():" in line_and_area.content
    assert "xy.step(" in line_and_area.content
    assert "xy.stairs(" in line_and_area.content
    assert 'id:"step-and-stairs"' in str(render_xy_markdown_page(line_and_area))

    distributions = pages["/charts/distributions/"]
    assert "### ECDF" in distributions.content
    assert "def ecdf_demo():" in distributions.content
    assert "xy.ecdf(" in distributions.content
    assert "def box_demo():" in distributions.content
    assert "xy.box(" in distributions.content
    assert "def violin_demo():" in distributions.content
    assert "xy.violin(" in distributions.content
    rendered_distributions = str(render_xy_markdown_page(distributions))
    for fragment in ("ecdf", "box", "violin"):
        assert f'id:"{fragment}"' in rendered_distributions

    dedicated_pages = {
        "/charts/density-and-grids/": {
            "hexbin": ("def hexbin_demo():", "xy.hexbin("),
            "contour": ("def contour_demo():", "xy.contour("),
        },
        "/charts/specialized/": {
            "segments": ("def segments_demo():", "xy.segments("),
            "triangle-mesh": ("def triangle_mesh_demo():", "xy.triangle_mesh("),
        },
        "/components/annotations/": {
            "threshold": ("def threshold_demo():", "xy.threshold("),
            "horizontal-line": ("def horizontal_line_demo():", "xy.hline("),
            "bands": ("def bands_demo():", "xy.x_band("),
            "arrow": ("def arrow_demo():", "xy.arrow("),
            "label": ("def label_demo():", "xy.label("),
            "text": ("def text_demo():", "xy.text("),
        },
        "/charts/facets-and-layers/": {
            "facet-chart": ("def facet_chart_demo():", "xy.facet_chart("),
        },
    }
    for route, examples in dedicated_pages.items():
        page = pages[route]
        rendered_page = str(render_xy_markdown_page(page))
        for fragment, requirements in examples.items():
            assert f'id:"{fragment}"' in rendered_page
            assert all(requirement in page.content for requirement in requirements)


def test_chart_gallery_combines_only_the_requested_related_tiles() -> None:
    """Keep requested combined tiles and section ordering explicit."""
    titles = {item.title for group in _GALLERY_GROUPS for item in group.items}
    section_titles = [group.title for group in _GALLERY_GROUPS]

    assert len(titles) == 28
    assert section_titles[:3] == [
        "Line and Area",
        "Distributions",
        "Bar, Column, and Scatter",
    ]
    combined_group = _GALLERY_GROUPS[2]
    assert combined_group.route is None
    assert [(item.title, item.route) for item in combined_group.items] == [
        ("Bar + Column", "/charts/bar-and-column/"),
        ("Scatter", "/charts/scatter/"),
    ]
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


def test_annotations_have_one_canonical_guide_and_a_legacy_redirect() -> None:
    """Keep annotation guidance consolidated without breaking the old chart URL."""
    pages = discover_docs(DOCS_CONFIG)
    annotation_pages = [page for page in pages if page.title == "Annotations"]
    chart_section = next(
        leaves for title, _landing_route, _icon, leaves in DOCS_SECTIONS if title == "Chart Gallery"
    )

    assert [page.route for page in annotation_pages] == ["/components/annotations/"]
    assert ("Annotations", "/charts/annotations/") not in chart_section
    assert DOCS_REDIRECTS["/charts/annotations/"] == "/components/annotations/"

    redirect = app._unevaluated_pages["charts/annotations"]
    rendered_meta = "\n".join(str(component) for component in redirect.meta)
    assert redirect.context == {"sitemap": None}
    assert "https://reflex.dev/docs/xy/components/annotations/" in rendered_meta
    assert "0; url=/docs/xy/components/annotations/" in rendered_meta
    assert "Open the combined Annotations guide" in str(redirect.component())


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


def test_inline_svg_gallery_validator_requires_every_styled_preview(tmp_path: Path) -> None:
    """Accept only the complete code-native gallery in the production route."""
    module_path = tmp_path / "route.jsx"
    preview = 'viewBox=\\"0 0 320 232\\"'
    module_path.write_text(
        preview * 28 + "gallery-preview-surface aspect-[320/232] shadow-large",
        encoding="utf-8",
    )

    check_html_routes.validate_inline_svg_gallery("/overview/gallery/", module_path)

    module_path.write_text(
        preview * 27 + "gallery-preview-surface aspect-[320/232] shadow-large",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="27 previews, expected 28"):
        check_html_routes.validate_inline_svg_gallery("/overview/gallery/", module_path)


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
    """Render quick tabs plus labeled groups of accordions and direct links."""
    component = xy_docs_sidebar_comp(url="/core-concepts/axes-and-scales/")
    assert isinstance(component, MemoComponent)

    instance = str(xy_docs_sidebar("/core-concepts/axes-and-scales/"))
    rendered = str(xy_docs_sidebar_comp._definition.component)
    grouped_sections = tuple(
        section
        for _group_title, _group_route, sections in SIDEBAR_SECTION_GROUPS
        for section in sections
    )

    assert "/core-concepts/axes-and-scales/" in instance
    assert re.findall(
        r'jsx\(RadixThemesText,\{as:"p",className:"m-0 text-sm font-\[525\]"\},"([^"]+)"\)',
        rendered,
    ) == [
        row_title
        for title, landing_route, _icon, leaves in grouped_sections
        for row_title in (
            (*(leaf_title for leaf_title, _leaf_route in leaves),)
            if title == "Integrations"
            and not any(leaf_route == landing_route for _leaf_title, leaf_route in leaves)
            else (
                (leaf_title for leaf_title, _leaf_route in leaves)
                if title == "Integrations"
                else (title,)
            )
        )
    ]
    expected_leaf_count = sum(
        len(leaves) + int(not any(route == landing_route for _title, route in leaves))
        for title, landing_route, _icon, leaves in DOCS_SECTIONS
        if title != "Integrations"
    )
    accordion_count = len(DOCS_SECTIONS) - 1
    assert rendered.count('jsx("details"') == accordion_count
    assert rendered.count('jsx("summary"') == accordion_count
    assert rendered.count("group/details") == accordion_count
    assert rendered.count("guideMarginClass") == expected_leaf_count
    assert sorted(section[0] for section in grouped_sections) == sorted(
        section[0] for section in DOCS_SECTIONS
    )
    learning_sections = SIDEBAR_SECTION_GROUPS[0][2]
    other_sections = SIDEBAR_SECTION_GROUPS[2][2]
    assert [section[0] for section in learning_sections] == [
        "Overview",
        "Core Concepts",
        "Styling",
        "Advanced",
    ]
    assert "Advanced" not in {section[0] for section in other_sections}
    for group_title in ("Learning", "Examples", "Other"):
        assert group_title in rendered
    for category, route in (
        ("Learn", "/"),
        ("Build", "/overview/gallery/"),
        ("API Reference", "/api-reference/"),
    ):
        assert f'aria-label":"Navigate to {category}"' in rendered
        assert f'to:"{route}"' in rendered
    assert 'aria-label":"Navigate to Charts"' not in rendered
    assert 'aria-label":"Navigate to Components"' not in rendered
    assert "Axes and Scales" in rendered
    for route in (
        "/integrations/reflex/",
        "/integrations/notebooks/",
        "/integrations/matplotlib/",
    ):
        assert f'to:"{route}"' in rendered
    for icon in (
        "LucideAtom",
        "LucideNotebookTabs",
        "LucideChartNoAxesCombined",
    ):
        assert icon in rendered
    assert "LucidePlug" not in rendered
    assert rendered.count('"aria-current":((') == 3
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
    assert XY_REPOSITORY_URL in rendered
    assert f"View XY on GitHub - {XY_GITHUB_STARS} stars" in rendered
    assert 'target:"_blank"' in rendered
    assert 'rel:"noopener noreferrer"' in rendered
    assert "XY's initial launch is here" in rendered
    assert "Get started" in rendered
    assert "Reserve your spot" not in rendered
    assert "https://luma.com/a1ty77bt" not in rendered
    assert "Reflex Agent Toolkit is launching" not in rendered


def test_xy_breadcrumb_opens_the_official_docs_sidebar_drawer() -> None:
    """Reuse the complete memoized sidebar in the mobile page-header drawer."""
    page = next(page for page in discover_docs(DOCS_CONFIG) if page.route == "/charts/scatter/")

    rendered = str(xy_docs_breadcrumb(page, xy_docs_sidebar(page.route)))

    assert "Drawer.Root" in rendered
    assert "Drawer.Trigger" in rendered
    assert "Chart Gallery" in rendered
    assert "Scatter" in rendered
    assert "/overview/gallery/" in rendered
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


@pytest.mark.parametrize(
    ("route", "expected"),
    (
        ("/core-concepts/", (("Composition Model", "/core-concepts/"),)),
        (
            "/core-concepts/data/",
            (
                ("Core Concepts", "/core-concepts/"),
                ("Data and Columns", "/core-concepts/data/"),
            ),
        ),
        (
            "/core-concepts/axes-and-scales/",
            (
                ("Core Concepts", "/core-concepts/"),
                ("Axes and Scales", "/core-concepts/axes-and-scales/"),
            ),
        ),
        (
            "/core-concepts/interactions/",
            (
                ("Core Concepts", "/core-concepts/"),
                ("Interactions and Selections", "/core-concepts/interactions/"),
            ),
        ),
        (
            "/core-concepts/large-data-and-performance/",
            (
                ("Core Concepts", "/core-concepts/"),
                (
                    "Large Data and Performance",
                    "/core-concepts/large-data-and-performance/",
                ),
            ),
        ),
        (
            "/core-concepts/configuration/",
            (
                ("Core Concepts", "/core-concepts/"),
                ("Configuration", "/core-concepts/configuration/"),
            ),
        ),
    ),
)
def test_core_concept_breadcrumbs_use_page_titles(
    route: str,
    expected: tuple[tuple[str, str], ...],
) -> None:
    """Use frontmatter titles instead of lossy slug title-casing."""
    page = next(page for page in discover_docs(DOCS_CONFIG) if page.route == route)

    assert _breadcrumb_parts(page) == expected


def test_xy_footer_is_project_specific_and_keeps_source_aware_links() -> None:
    """Target XY support and source pages without parent-product dead ends."""
    page = next(page for page in discover_docs(DOCS_CONFIG) if page.route == "/overview/gallery/")

    rendered = str(xy_docs_footer(page))

    assert "https://github.com/reflex-dev/xy/issues/new" in rendered
    assert "Issue%20with%20reflex.dev/docs/xy/overview/gallery/" in rendered
    assert "Path%3A%20/docs/xy/overview/gallery/%0A%0A" in rendered
    assert "https://github.com/reflex-dev/xy/blob/main/docs/overview/gallery.md" in rendered
    assert 'to:"/guides/getting-help/"' in rendered
    assert 'to:"/guides/deployment-recipes/"' in rendered
    assert 'to:"/docs/xy/' not in rendered
    assert "SECURITY.md" in rendered
    assert "Book a Demo" not in rendered
    assert "reflex.dev/docs/getting-started" not in rendered


def test_every_docs_route_has_canonical_and_social_metadata() -> None:
    """Publish branded canonical and social metadata for every route."""
    assert len(_DOCS_ROUTES) + len(DOCS_REDIRECTS) == len(app._unevaluated_pages)
    assert PUBLIC_XY_VERSION == "0.0.1"
    assert (
        (DOCS_APP_ROOT / "assets/xy-social-card.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    )

    for route in _DOCS_ROUTES:
        route_key = route.path.strip("/") or "index"
        page = app._unevaluated_pages[route_key]
        canonical = f"{PUBLIC_DOCS_URL}{route.path}"
        rendered_meta = "\n".join(str(component) for component in page.meta)

        assert page.context == {"sitemap": {"loc": canonical}}
        assert page.image == SOCIAL_IMAGE_URL
        assert f'href:"{canonical}",rel:"canonical"' in rendered_meta
        assert 'property:"og:title"' in rendered_meta
        assert f'content:"{canonical}",property:"og:url"' in rendered_meta
        assert 'content:"summary_large_image",name:"twitter:card"' in rendered_meta
        assert f'content:"{SOCIAL_IMAGE_URL}",name:"twitter:image"' in rendered_meta


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
