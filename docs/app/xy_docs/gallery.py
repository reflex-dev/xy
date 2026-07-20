"""Visual chart-type gallery for the XY documentation landing pages."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import reflex as rx
import reflex_xy

import xy

ChartSource = xy.Chart | xy.FacetChart
ChartFactory = Callable[[], ChartSource]
GalleryItem = tuple[str, str, ChartFactory, bool]
GalleryGroup = tuple[str, str, tuple[GalleryItem, ...]]

_WIDTH = 420
_HEIGHT = 220
_PADDING = (20, 16, 28, 36)
_PURPLE = "#6E56CF"
_PURPLE_DARK = "#6550B9"
_PURPLE_LIGHT = "#C4B5FD"
_GRAY_DARK = "#1C2024"
_GRAY_MID = "#8B8D98"
_GRAY_LIGHT = "#CDCED6"
# Keep this token split so compiled CSS proves it came from the generated manifest,
# rather than Tailwind's Python source scan.
_TAILWIND_BRIDGE_SENTINEL = "[--xy-tailwind-" + "bridge:compiled]"
_STATIC_SVG_PAINT_TOKENS = {
    "rgba(32,32,32,0.14)": "var(--secondary-a5)",
    "rgba(32,32,32,0.55)": "var(--secondary-a8)",
    "rgba(32,32,32,0.85)": "var(--secondary-11)",
    _PURPLE: "var(--primary-9)",
    _PURPLE_DARK: "var(--primary-10)",
    _PURPLE_LIGHT: "var(--primary-7)",
    _GRAY_DARK: "var(--secondary-11)",
    _GRAY_MID: "var(--secondary-10)",
    _GRAY_LIGHT: "var(--secondary-8)",
}
_GALLERY_LAYOUT_CSS = """
main:has(#xy-chart-gallery) > div:has(#toc-navigation) {
  display: none;
}
main:has(#xy-chart-gallery) > div:has(article #xy-chart-gallery) {
  max-width: 88rem;
}
"""


def _gallery_theme() -> xy.Theme:
    return xy.theme(
        style={
            "--chart-modebar-bg": "var(--secondary-2)",
            "--chart-modebar-active": "var(--primary-a4)",
            "--chart-focus": "var(--primary-9)",
        },
        plot_background="transparent",
        grid_color="var(--secondary-a5)",
        axis_color="var(--secondary-a8)",
        text_color="var(--secondary-11)",
        crosshair_color="var(--primary-a9)",
        selection_color="var(--primary-9)",
        selection_fill="var(--primary-a3)",
    )


def _line() -> xy.Chart:
    return xy.line_chart(
        xy.line(
            [0, 1, 2, 3, 4, 5],
            [2, 4, 3.4, 6.2, 5.6, 8],
            color=_PURPLE_DARK,
            width=2.4,
            curve="smooth",
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
        class_name=_TAILWIND_BRIDGE_SENTINEL,
    )


def _area() -> xy.Chart:
    return xy.area_chart(
        xy.area(
            [0, 1, 2, 3, 4, 5],
            [2, 4, 3, 6, 5, 8],
            color=_PURPLE,
            opacity=0.24,
            line_color=_PURPLE_DARK,
            line_width=2.2,
            curve="smooth",
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _step() -> xy.Chart:
    return xy.step_chart(
        xy.step(
            [0, 1, 2, 3, 4, 5],
            [1, 3, 2, 5, 4, 7],
            color=_PURPLE,
            width=2.2,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _stairs() -> xy.Chart:
    return xy.stairs_chart(
        xy.stairs(
            [1, 3, 2, 5, 4, 7],
            edges=[0, 1, 2, 3, 4, 5, 6],
            color=_PURPLE,
            width=2.2,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _scatter() -> xy.Chart:
    return xy.scatter_chart(
        xy.scatter(
            [-2.0, -1.4, -0.8, -0.2, 0.3, 0.8, 1.3, 1.9],
            [-1.0, -0.2, -0.7, 0.4, 0.1, 1.1, 0.7, 1.6],
            color=[0, 1, 2, 3, 4, 5, 6, 7],
            size=[6, 9, 7, 11, 8, 13, 9, 12],
            opacity=0.9,
            colormap="purples",
            color_domain=(-2, 7),
            stroke=_PURPLE_DARK,
            stroke_width=0.8,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _bar() -> xy.Chart:
    return xy.bar_chart(
        xy.bar(
            ["Design", "Build", "Ship"],
            [6, 9, 4],
            orientation="horizontal",
            color=_PURPLE,
            corner_radius=3,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=(18, 14, 26, 52),
    )


def _column() -> xy.Chart:
    return xy.column_chart(
        xy.column(
            ["Q1", "Q2", "Q3", "Q4"],
            [4, 6, 5, 8],
            color=_PURPLE,
            corner_radius=(3, 0),
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _histogram() -> xy.Chart:
    values = [8, 12, 13, 14, 15, 15, 16, 18, 19, 21, 22, 23, 26, 29, 34]
    return xy.histogram_chart(
        xy.histogram(
            values,
            bins=7,
            color=_PURPLE,
            opacity=0.88,
            corner_radius=2,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _ecdf() -> xy.Chart:
    values = [8, 12, 13, 14, 15, 15, 16, 18, 19, 21, 22, 23, 26, 29, 34]
    return xy.ecdf_chart(
        xy.ecdf(values, color=_PURPLE_DARK, width=2.2),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _box() -> xy.Chart:
    return xy.box_chart(
        xy.box([3, 4, 5, 5, 6, 7, 7, 8, 9, 12], color=_PURPLE),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _violin() -> xy.Chart:
    return xy.violin_chart(
        xy.violin(
            [2, 3, 3, 4, 4, 4.5, 5, 5, 5.5, 6, 6, 7, 8, 9],
            color=_PURPLE_LIGHT,
            opacity=0.7,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _hexbin() -> xy.Chart:
    x = [
        -1.8,
        -1.5,
        -1.3,
        -1.1,
        -0.9,
        -0.7,
        -0.5,
        -0.3,
        -0.1,
        0.1,
        0.3,
        0.5,
        0.7,
        0.9,
        1.1,
        1.3,
        1.5,
        1.8,
    ]
    y = [
        -0.9,
        -0.5,
        -0.7,
        -0.2,
        -0.4,
        0.1,
        -0.1,
        0.4,
        0.2,
        0.7,
        0.4,
        0.9,
        0.6,
        1.2,
        0.8,
        1.4,
        1.1,
        1.6,
    ]
    return xy.hexbin_chart(
        xy.hexbin(
            x,
            y,
            gridsize=8,
            mincnt=1,
            colormap="purples",
            opacity=0.92,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _heatmap() -> xy.Chart:
    purple_pale = tuple(bytes.fromhex("EDE9FE"))
    purple_light = tuple(bytes.fromhex(_PURPLE_LIGHT[1:]))
    purple_mid = tuple(bytes.fromhex("A78BFA"))
    purple = tuple(bytes.fromhex(_PURPLE[1:]))
    purple_dark = tuple(bytes.fromhex(_PURPLE_DARK[1:]))
    return xy.heatmap_chart(
        xy.heatmap(
            [
                [purple_pale, purple_light, purple_mid, purple_light],
                [purple_light, purple, purple_dark, purple],
                [purple_pale, purple_light, purple_mid, purple_light],
            ],
            opacity=1.0,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=(14, 14, 22, 28),
    )


def _contour() -> xy.Chart:
    return xy.contour_chart(
        xy.contour(
            [
                [0.0, 0.2, 0.4, 0.1],
                [0.2, 0.8, 1.1, 0.5],
                [0.1, 0.6, 0.9, 0.4],
                [0.0, 0.2, 0.3, 0.1],
            ],
            levels=6,
            colormap="purples",
            color=_PURPLE,
            width=1.5,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=(14, 14, 22, 28),
    )


def _error_band() -> xy.Chart:
    x = [0, 1, 2, 3, 4, 5]
    estimate = [3, 4, 4.5, 6, 6.5, 8]
    return xy.error_band_chart(
        xy.error_band(
            x,
            [value - 0.8 for value in estimate],
            [value + 0.8 for value in estimate],
            color=_PURPLE_LIGHT,
            opacity=0.38,
        ),
        xy.line(x, estimate, color=_PURPLE_DARK, width=2.2, curve="smooth"),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _errorbar() -> xy.Chart:
    return xy.errorbar_chart(
        xy.errorbar(
            [0, 1, 2, 3, 4],
            [3, 4.5, 4, 6, 7],
            yerr=[0.4, 0.7, 0.5, 0.8, 0.6],
            color=_PURPLE,
            cap_size=5,
            width=2.2,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _stem() -> xy.Chart:
    return xy.stem_chart(
        xy.stem(
            [0, 1, 2, 3, 4, 5],
            [1, 3, 2, 4, 3, 5],
            color=_PURPLE,
            width=2.2,
            marker_size=6,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _segments() -> xy.Chart:
    starts = [0.4, 0.8, 0.5, 1.1, 0.7]
    ends = [2.0, 2.7, 3.2, 3.6, 4.1]
    rows = [1, 2, 3, 4, 5]
    return xy.segments_chart(
        xy.segments(
            starts,
            rows,
            ends,
            rows,
            color=[0.15, 0.35, 0.55, 0.75, 1.0],
            colormap="purples",
            domain=(-0.2, 1.0),
            width=4.5,
            opacity=0.92,
        ),
        xy.scatter(
            starts,
            rows,
            color=_GRAY_LIGHT,
            size=5,
            colormap="purples",
            stroke=_GRAY_MID,
            stroke_width=0.9,
        ),
        xy.scatter(
            ends,
            rows,
            color=_PURPLE_DARK,
            size=6,
            colormap="purples",
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _threshold() -> xy.Chart:
    return xy.line_chart(
        xy.line(
            [0, 1, 2, 3, 4, 5],
            [2, 3, 4, 5, 6, 7],
            color=_GRAY_MID,
            width=2,
        ),
        xy.threshold(5.3, text="target", color=_PURPLE),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _triangle_mesh() -> xy.Chart:
    return xy.triangle_mesh_chart(
        xy.triangle_mesh(
            [0, 1, 1],
            [0, 0, 1],
            [1, 2, 2],
            [0, 0, 1],
            [0.5, 1.5, 1.5],
            [1.2, 1.3, 2.1],
            color=[0.2, 0.65, 1.0],
            colormap="purples",
            domain=(-0.25, 1.0),
            stroke=_GRAY_LIGHT,
            stroke_width=1,
        ),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


def _annotation_base(*annotations: xy.Annotation) -> xy.Chart:
    return xy.line_chart(
        xy.line(
            [0, 1, 2, 3, 4, 5],
            [2, 3, 4, 6, 5.5, 8],
            color=_GRAY_MID,
            width=2,
            curve="smooth",
        ),
        *annotations,
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=(20, 22, 28, 38),
    )


def _hline() -> xy.Chart:
    return _annotation_base(xy.hline(5, text="target", color=_PURPLE))


def _vline() -> xy.Chart:
    return _annotation_base(xy.vline(3, text="launch", color=_PURPLE))


def _bands() -> xy.Chart:
    return _annotation_base(
        xy.x_band(1.3, 2.5, color=_PURPLE, opacity=0.13),
        xy.y_band(6.2, 8.2, color=_GRAY_MID, opacity=0.1),
    )


def _callout() -> xy.Chart:
    return _annotation_base(xy.callout(3, 6, "Peak", dx=26, dy=-22, color=_GRAY_DARK))


def _arrow() -> xy.Chart:
    return _annotation_base(xy.arrow(1.3, 3.2, 3, 6, text="change", color=_PURPLE))


def _label() -> xy.Chart:
    return _annotation_base(xy.label(3, 6, "Launch", color=_GRAY_DARK))


def _text() -> xy.Chart:
    return _annotation_base(xy.text(4, 5.5, "Forecast", color=_PURPLE))


def _threshold_zone() -> xy.Chart:
    return _annotation_base(xy.threshold_zone(6, 9, text="healthy", color=_PURPLE, opacity=0.13))


def _facet_chart() -> xy.FacetChart:
    data = {
        "x": [0, 1, 2, 3, 0, 1, 2, 3],
        "y": [1, 3, 2, 4, 4, 2, 3, 1],
        "region": ["West", "West", "West", "West", "East", "East", "East", "East"],
    }
    return xy.facet_chart(
        xy.line(x="x", y="y", color=_PURPLE, width=2),
        _gallery_theme(),
        by="region",
        data=data,
        cols=2,
        share_x=True,
        share_y=True,
        gap=12,
        width=_WIDTH,
        height=200,
        padding=(18, 12, 24, 30),
    )


def _layered_marks() -> xy.Chart:
    return xy.chart(
        xy.bar(["A", "B", "C", "D"], [4, 7, 5, 8], color=_PURPLE_LIGHT),
        xy.scatter(
            ["A", "B", "C", "D"],
            [4.5, 6.4, 5.7, 7.6],
            color=_GRAY_DARK,
            size=7,
            colormap="purples",
        ),
        xy.hline(6, color=_PURPLE),
        _gallery_theme(),
        width=_WIDTH,
        height=_HEIGHT,
        padding=_PADDING,
    )


_GALLERY_GROUPS: tuple[GalleryGroup, ...] = (
    (
        "Line and Area",
        "/charts/line-and-area/",
        (
            ("Line", "Continuous trends and ordered series.", _line, True),
            ("Area", "Magnitude over an ordered domain.", _area, False),
            (
                "Step + Stairs",
                "Piecewise-constant values at observations or explicit bin edges.",
                _step,
                False,
            ),
        ),
    ),
    (
        "Scatter",
        "/charts/scatter/",
        (("Scatter", "Relationships with size and color channels.", _scatter, True),),
    ),
    (
        "Bar and Column",
        "/charts/bar-and-column/",
        (
            (
                "Bar + Column",
                "Horizontal and vertical category comparisons.",
                _column,
                True,
            ),
        ),
    ),
    (
        "Distributions",
        "/charts/distributions/",
        (
            ("Histogram", "Binned frequency or density.", _histogram, True),
            ("ECDF", "Cumulative probability without fixed bins.", _ecdf, False),
            ("Box", "Quartiles, spread, and outliers.", _box, False),
            ("Violin", "Distribution shape and density.", _violin, False),
        ),
    ),
    (
        "Density and Grids",
        "/charts/density-and-grids/",
        (
            ("Hexbin", "Aggregate dense points into hexagonal bins.", _hexbin, False),
            ("Heatmap", "Encode a matrix with color.", _heatmap, True),
            ("Contour", "Trace levels across a scalar field.", _contour, False),
        ),
    ),
    (
        "Uncertainty",
        "/charts/uncertainty/",
        (
            ("Error Band", "Show an interval around an estimate.", _error_band, True),
            ("Error Bar", "Show per-observation uncertainty.", _errorbar, False),
        ),
    ),
    (
        "Specialized",
        "/charts/specialized/",
        (
            ("Stem", "Discrete values anchored to a baseline.", _stem, True),
            ("Segments", "Independent data-aligned line segments.", _segments, False),
            (
                "Triangle Mesh",
                "Irregular triangulated surfaces.",
                _triangle_mesh,
                False,
            ),
        ),
    ),
    (
        "Annotations",
        "/components/annotations/",
        (
            ("Threshold", "A labeled reference boundary.", _threshold, False),
            ("Horizontal Line", "A y-aligned rule across the plot.", _hline, False),
            ("Vertical Line", "An x-aligned event marker.", _vline, False),
            ("Bands", "Highlight x and y intervals.", _bands, False),
            ("Callout", "Connect explanatory text to a point.", _callout, False),
            ("Arrow", "Point from one coordinate to another.", _arrow, False),
            ("Label", "Attach a concise label to a coordinate.", _label, False),
            ("Text", "Place free text inside the plot.", _text, False),
            (
                "Threshold Zone",
                "Shade an acceptable or risky range.",
                _threshold_zone,
                True,
            ),
        ),
    ),
    (
        "Facets and Layers",
        "/charts/facets-and-layers/",
        (
            (
                "Facet Chart",
                "Repeat one composition across groups.",
                _facet_chart,
                False,
            ),
            (
                "Layered Marks",
                "Combine marks in one coordinate system.",
                _layered_marks,
                True,
            ),
        ),
    ),
)


def _iter_gallery_items() -> Iterator[tuple[str, str, str, ChartFactory, bool]]:
    for _group_title, route, items in _GALLERY_GROUPS:
        for title, description, chart_factory, live in items:
            yield title, description, route, chart_factory, live


def _responsive_gallery_svg(chart: ChartSource) -> str:
    """Replace static-renderer fallback paints with site color-mode tokens."""
    svg = chart.to_svg()
    if any(getattr(child, "kind", None) == "hexbin" for child in chart.children):
        # The first ``purples`` stop is nearly white. Keep low-count hexagons
        # visible by promoting that Hexbin-only stop to the light site purple.
        svg = svg.replace("rgb(252,251,253)", _PURPLE_LIGHT)
    for paint, token in _STATIC_SVG_PAINT_TOKENS.items():
        svg = svg.replace(paint, token)
    return svg


def _gallery_chart(chart_factory: ChartFactory) -> ChartSource:
    """Build a preview chart without the full-page interaction toolbar."""
    chart = chart_factory()
    chart.children = (*chart.children, xy.modebar(show=False))
    return chart


def _gallery_preview(chart_factory: ChartFactory, *, live: bool) -> rx.Component:
    chart = _gallery_chart(chart_factory)
    if live:
        return reflex_xy.chart(chart, width="100%", height="220px")

    # SVG keeps context use bounded while one tile in each family remains live.
    return rx.html(
        _responsive_gallery_svg(chart),
        class_name="h-[220px] w-full [&>svg]:h-full [&>svg]:w-full",
    )


def _gallery_card(
    title: str,
    description: str,
    route: str,
    chart_factory: ChartFactory,
    *,
    live: bool,
) -> rx.Component:
    """Render one linked chart-type preview card."""
    return rx.link(
        rx.box(
            rx.box(
                _gallery_preview(chart_factory, live=live),
                class_name=(
                    "h-[220px] w-full overflow-hidden bg-white text-secondary-11 dark:bg-black"
                ),
            ),
            rx.box(
                rx.box(
                    rx.el.h3(title, class_name="font-base text-secondary-12"),
                    rx.icon(
                        "arrow-up-right",
                        size=15,
                        class_name=("text-secondary-8 transition group-hover:text-primary-10"),
                    ),
                    class_name="flex items-center justify-between gap-3",
                ),
                rx.el.p(description, class_name="font-small text-secondary-10"),
                class_name=(
                    "flex min-h-[5.5rem] flex-col gap-1.5 border-t "
                    "border-secondary-5 bg-secondary-2 px-5 py-4"
                ),
            ),
            class_name=(
                "group overflow-hidden rounded-2xl border border-secondary-5 "
                "bg-secondary-2 shadow-sm transition duration-200 "
                "hover:-translate-y-1 hover:border-primary-7 "
                "hover:shadow-[0_18px_42px_-28px_rgba(110,86,207,0.65)]"
            ),
        ),
        href=route,
        underline="none",
        class_name="block !text-inherit",
        aria_label=f"Open the {title} chart guide",
    )


def chart_gallery_grid() -> rx.Component:
    """Render every public chart type, grouped like the Chart Gallery."""
    return rx.fragment(
        rx.el.style(_GALLERY_LAYOUT_CSS),
        rx.el.div(
            *(
                rx.el.section(
                    rx.link(
                        rx.el.h2(
                            group_title,
                            class_name="font-large text-secondary-12",
                        ),
                        href=route,
                        underline="none",
                        class_name="!text-inherit hover:!text-primary-10",
                        aria_label=f"Open the {group_title} chart family guide",
                    ),
                    rx.el.div(
                        *(
                            _gallery_card(
                                title,
                                description,
                                route,
                                chart_factory,
                                live=live,
                            )
                            for title, description, chart_factory, live in items
                        ),
                        class_name=("grid w-full grid-cols-1 gap-6 md:grid-cols-2 2xl:grid-cols-3"),
                    ),
                    class_name="flex w-full flex-col gap-4",
                )
                for group_title, route, items in _GALLERY_GROUPS
            ),
            id="xy-chart-gallery",
            class_name="my-8 flex w-full flex-col gap-14",
        ),
    )


__all__ = ["chart_gallery_grid"]
