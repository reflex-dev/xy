from __future__ import annotations

import reflex as rx

from .live_drilldown import LIVE_DRILLDOWN_ROUTE, drilldown_endpoint

LIVE_DRILLDOWN_CHART = {
    "id": "live-drilldown",
    "title": "Live 100M Drilldown Scatter",
    "subtitle": "100M source points with Reflex-backed adaptive LOD.",
    "src": "/charts/live_drilldown_100m.html",
    "stat": "100M live",
}

COMPARISON_CHARTS = [
    {
        "id": "fastcharts-scatter",
        "title": "fastcharts Colored Scatter",
        "subtitle": "10M source points with color and size, exported through the density tier.",
        "src": "/charts/colored_scatter.html",
        "stat": "10M source",
    },
    {
        "id": "plotly-scatter",
        "title": "Plotly Scattergl",
        "subtitle": "100k sampled points from the same distribution, rendered as WebGL markers.",
        "src": "/charts/plotly_colored_scatter.html",
        "stat": "100k sample",
    },
]

BUSINESS_CHART = {
    "id": "business-overview",
    "title": "Business Overview",
    "subtitle": "Small grouped revenue and pipeline columns for ordinary dashboard data.",
    "src": "/charts/business_overview.html",
    "stat": "small data",
}

RETENTION_CHART = {
    "id": "retention-cohort",
    "title": "Retention Cohort",
    "subtitle": "Small product analytics heatmap with cohort rows and weekly retention columns.",
    "src": "/charts/retention_cohort.html",
    "stat": "small data",
}

LINE_CHART = {
    "id": "line",
    "title": "Decimated Line",
    "subtitle": "120k sorted samples, shipped as a screen-bounded line payload.",
    "src": "/charts/line_walk.html",
    "stat": "120k points",
}

AREA_CHART = {
    "id": "area",
    "title": "Filled Area",
    "subtitle": "80k samples filled against a baseline with a line overlay.",
    "src": "/charts/area.html",
    "stat": "80k points",
}

DENSITY_CHART = {
    "id": "density-scatter",
    "title": "Density Scatter",
    "subtitle": "10M raw points aggregated into a responsive density texture.",
    "src": "/charts/density_scatter.html",
    "stat": "10M points",
}

HISTOGRAM_CHART = {
    "id": "histogram",
    "title": "Histogram",
    "subtitle": "500k values binned into a shared rectangle-renderer chart.",
    "src": "/charts/histogram.html",
    "stat": "500k values",
}

BAR_CHART = {
    "id": "grouped-bars",
    "title": "Grouped Bars",
    "subtitle": "Multiple category series sharing the rectangle primitive.",
    "src": "/charts/bar_column.html",
    "stat": "grouped",
}

STACKED_BAR_CHART = {
    "id": "stacked-bars",
    "title": "Stacked Bars",
    "subtitle": "Positive series stacked from a shared baseline.",
    "src": "/charts/stacked_bar.html",
    "stat": "stacked",
}

HORIZONTAL_BAR_CHART = {
    "id": "horizontal-bars",
    "title": "Horizontal Bars",
    "subtitle": "Category labels on the y-axis with value bars extending along x.",
    "src": "/charts/horizontal_bar.html",
    "stat": "horizontal",
}

HEATMAP_CHART = {
    "id": "heatmap",
    "title": "Heatmap",
    "subtitle": "Matrix values rendered as colored cells on categorical axes.",
    "src": "/charts/heatmap.html",
    "stat": "grid",
}

BUSINESS_CHARTS = [
    BUSINESS_CHART,
    RETENTION_CHART,
]

CORE_CHARTS = [
    LINE_CHART,
    AREA_CHART,
    HISTOGRAM_CHART,
    BAR_CHART,
    STACKED_BAR_CHART,
    HORIZONTAL_BAR_CHART,
    HEATMAP_CHART,
]

LARGE_DATA_CHARTS = [
    DENSITY_CHART,
    *COMPARISON_CHARTS,
    LIVE_DRILLDOWN_CHART,
]

CHART_NAV = [
    *BUSINESS_CHARTS,
    *CORE_CHARTS,
    *LARGE_DATA_CHARTS,
]


def metric(label: str, value: str) -> rx.Component:
    return rx.box(
        rx.text(label, size="2", color="gray"),
        rx.heading(value, size="5", margin_top="0.25rem"),
        padding="1rem",
        border="1px solid #dde3ea",
        border_radius="8px",
        background="#ffffff",
        min_height="86px",
    )


def chart_panel(chart: dict[str, str], *, fluid: bool = False) -> rx.Component:
    return rx.box(
        rx.box(
            rx.hstack(
                rx.box(
                    rx.heading(chart["title"], size="5"),
                    rx.text(chart["subtitle"], size="2", color="gray", margin_top="0.25rem"),
                ),
                rx.badge(chart["stat"], variant="soft", color_scheme="blue"),
                justify="between",
                align="start",
                width="100%",
                gap="1rem",
            ),
            padding="1rem",
        ),
        rx.box(
            rx.el.iframe(
                src=chart["src"],
                title=chart["title"],
                loading="eager" if fluid else "lazy",
                style={
                    "border": "0",
                    "width": "100%" if fluid else "1040px",
                    "height": "430px",
                    "display": "block",
                    "background": "#ffffff",
                },
            ),
            border_top="1px solid #dde3ea",
            overflow_x="auto",
            overflow_y="hidden",
            background="#ffffff",
            width="100%",
        ),
        border="1px solid #dde3ea",
        border_radius="8px",
        background="#fbfcfe",
        overflow="hidden",
        width="100%",
        id=chart["id"],
    )


def chart_selector() -> rx.Component:
    return rx.flex(
        *[
            rx.link(
                chart["title"],
                href=f"#{chart['id']}",
                padding="0.45rem 0.65rem",
                border="1px solid #ccd6e2",
                border_radius="8px",
                background="#ffffff",
                color="#1d2939",
                text_decoration="none",
                font_size="0.875rem",
                font_weight="500",
            )
            for chart in CHART_NAV
        ],
        align="center",
        gap="0.5rem",
        wrap="wrap",
        width="100%",
    )


def chart_section(
    title: str,
    charts: list[dict[str, str]],
    *,
    columns: dict[str, str] | None = None,
) -> rx.Component:
    return rx.vstack(
        rx.heading(title, size="6"),
        rx.grid(
            *[chart_panel(chart, fluid=True) for chart in charts],
            columns=columns or {"initial": "1", "lg": "2"},
            gap="1rem",
            width="100%",
        ),
        spacing="3",
        width="100%",
        align="stretch",
    )


def index() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.box(
                    rx.heading("fastcharts Reflex dashboard", size="8"),
                    rx.text(
                        "Interactive WebGL charts embedded in a Reflex Python app.",
                        size="3",
                        color="gray",
                        margin_top="0.35rem",
                    ),
                ),
                rx.badge("example app", size="2", variant="soft", color_scheme="green"),
                justify="between",
                align="start",
                width="100%",
                gap="1rem",
            ),
            rx.grid(
                metric("Renderer", "WebGL2"),
                metric("Transport", "binary f32"),
                metric("Business demos", str(len(BUSINESS_CHARTS))),
                metric("Largest demo", "100M points"),
                columns={"initial": "1", "sm": "2", "lg": "4"},
                gap="1rem",
                width="100%",
            ),
            chart_selector(),
            chart_section("Business charts", BUSINESS_CHARTS),
            chart_section("Core 2D gallery", CORE_CHARTS),
            chart_section("Large-data demos", LARGE_DATA_CHARTS, columns={"initial": "1"}),
            spacing="5",
            width="100%",
            max_width="1280px",
        ),
        min_height="100vh",
        padding="2rem",
        background="#f3f6fa",
        color="#101828",
        font_family="Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
    )


app = rx.App()
app.add_page(index, route="/", title="fastcharts Reflex dashboard")
if app._api is not None:
    app._api.add_route(LIVE_DRILLDOWN_ROUTE, drilldown_endpoint, methods=["POST"])
