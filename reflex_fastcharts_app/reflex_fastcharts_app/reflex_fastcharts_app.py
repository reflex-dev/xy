from __future__ import annotations

import reflex as rx

from .live_drilldown import LIVE_DRILLDOWN_ROUTE, drilldown_endpoint

LIVE_DRILLDOWN_CHART = {
    "title": "Live 100M Drilldown Scatter",
    "subtitle": "100M source points with Reflex-backed adaptive LOD.",
    "src": "/charts/live_drilldown_100m.html",
    "stat": "100M live",
}

COMPARISON_CHARTS = [
    {
        "title": "fastcharts Colored Scatter",
        "subtitle": "10M source points with color and size, exported through the density tier.",
        "src": "/charts/colored_scatter.html",
        "stat": "10M source",
    },
    {
        "title": "Plotly Scattergl",
        "subtitle": "100k sampled points from the same distribution, rendered as WebGL markers.",
        "src": "/charts/plotly_colored_scatter.html",
        "stat": "100k sample",
    },
]

LINE_CHART = {
    "title": "Decimated Line",
    "subtitle": "120k sorted samples, shipped as a screen-bounded line payload.",
    "src": "/charts/line_walk.html",
    "stat": "120k points",
}

DENSITY_CHART = {
    "title": "Density Scatter",
    "subtitle": "10M raw points aggregated into a responsive density texture.",
    "src": "/charts/density_scatter.html",
    "stat": "10M points",
}


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
            margin_top="1rem",
            border="1px solid #dde3ea",
            border_radius="8px",
            overflow_x="auto",
            overflow_y="hidden",
            background="#ffffff",
            width="100%",
        ),
        padding="1rem",
        border="1px solid #dde3ea",
        border_radius="8px",
        background="#fbfcfe",
        width="100%",
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
                metric("Largest demo", "100M points"),
                columns={"initial": "1", "sm": "3"},
                gap="1rem",
                width="100%",
            ),
            chart_panel(LIVE_DRILLDOWN_CHART, fluid=True),
            rx.grid(
                *[chart_panel(chart, fluid=True) for chart in COMPARISON_CHARTS],
                columns={"initial": "1", "lg": "2"},
                gap="1rem",
                width="100%",
            ),
            chart_panel(LINE_CHART),
            chart_panel(DENSITY_CHART, fluid=True),
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
