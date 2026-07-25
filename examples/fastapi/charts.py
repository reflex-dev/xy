"""Chart builders for the FastAPI example.

Each builder is a plain ``() -> xy.Chart`` function. The app renders them with
``chart.to_html()`` and shows each builder's :func:`inspect.getsource` output
in a code panel; the browser smokes import the same builders. ``GALLERY`` lists
the builders with their display copy, and ``BY_ID`` indexes them by id.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

import xy


def line_walk() -> xy.Chart:
    rng = np.random.default_rng(7)
    n = 120_000
    x = np.arange(n, dtype=np.float64)
    y = np.cumsum(rng.normal(0, 0.35, n)) + np.sin(np.linspace(0, 24, n)) * 18
    return xy.line_chart(
        xy.line(x, y, name="walk", color="#3267c8", width=1.4),
        xy.x_axis(label="sample"),
        xy.y_axis(label="value"),
        title="120k sample random walk",
        width="100%",
        height=430,
    )


def area() -> xy.Chart:
    rng = np.random.default_rng(13)
    n = 80_000
    x = np.arange(n, dtype=np.float64)
    y = 35 + np.sin(np.linspace(0, 28, n)) * 8 + np.cumsum(rng.normal(0, 0.025, n))
    base = np.full(n, 25.0)
    return xy.area_chart(
        xy.area(
            x, y, base=base, name="active users", color="#0891b2", opacity=0.34, line_width=1.1
        ),
        xy.x_axis(label="sample"),
        xy.y_axis(label="active users"),
        title="80k filled area",
        width="100%",
        height=430,
    )


def density_scatter() -> xy.Chart:
    rng = np.random.default_rng(23)
    n = 10_000_000
    centers = np.array([[-1.4, -0.9], [-0.2, 0.8], [1.0, -0.2], [1.8, 1.1]])
    groups = rng.integers(0, len(centers), n, dtype=np.int8)
    x = centers[groups, 0] + rng.normal(0, 0.33, n)
    y = centers[groups, 1] + rng.normal(0, 0.33, n)
    return xy.scatter_chart(
        xy.scatter(x, y, opacity=0.9),
        xy.x_axis(label="x"),
        xy.y_axis(label="y"),
        title="10M density scatter",
        width="100%",
        height=430,
    )


def histogram() -> xy.Chart:
    rng = np.random.default_rng(41)
    values = np.concatenate([rng.normal(-1.2, 0.55, 250_000), rng.normal(1.4, 0.8, 250_000)])
    return xy.histogram_chart(
        xy.hist(values, bins=160, name="distribution", color="#3b82f6"),
        xy.x_axis(label="value"),
        xy.y_axis(label="count"),
        title="500k sample histogram",
        width="100%",
        height=430,
    )


def histogram_x_zoom() -> xy.Chart:
    rng = np.random.default_rng(73)
    values = rng.lognormal(mean=4.25, sigma=0.48, size=250_000)
    return xy.histogram_chart(
        xy.hist(values, bins=140, name="requests", color="#7c3aed"),
        xy.interaction_config(zoom_axes=("x",)),
        xy.x_axis(label="request latency (ms)", domain=(0.0, 250.0)),
        xy.y_axis(label="requests"),
        title="Latency histogram with x-only zoom",
        width="100%",
        height=430,
    )


def box_zoom_drag() -> xy.Chart:
    rng = np.random.default_rng(107)
    values = np.concatenate([rng.normal(38, 7, 140_000), rng.normal(72, 12, 110_000)])
    return xy.histogram_chart(
        xy.hist(values, bins=120, name="duration", color="#0891b2"),
        xy.interaction_config(default_drag_action="zoom", zoom_axes=("x",)),
        xy.x_axis(label="duration (ms)"),
        xy.y_axis(label="requests"),
        title="Drag over the histogram to zoom x",
        width="100%",
        height=430,
    )


def grouped_bars() -> xy.Chart:
    categories = ["Search", "Ads", "Email", "Direct", "Partner", "Social"]
    values = np.array(
        [
            [118.0, 94.0, 72.0, 66.0, 43.0, 31.0],
            [88.0, 76.0, 55.0, 48.0, 29.0, 22.0],
            [42.0, 39.0, 26.0, 31.0, 19.0, 14.0],
        ]
    )
    return xy.bar_chart(
        xy.bar(
            categories,
            values,
            mode="grouped",
            series=["Desktop", "Mobile", "Tablet"],
            colors=["#2563eb", "#16a34a", "#f59e0b"],
        ),
        xy.x_axis(label="channel"),
        xy.y_axis(label="conversions"),
        title="Grouped category bars",
        width="100%",
        height=430,
    )


def stacked_bars() -> xy.Chart:
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    values = np.array(
        [[42.0, 48.0, 54.0, 61.0], [28.0, 34.0, 37.0, 42.0], [16.0, 19.0, 24.0, 29.0]]
    )
    return xy.column_chart(
        xy.column(
            quarters,
            values,
            mode="stacked",
            series=["Core", "Expansion", "Services"],
            colors=["#0f766e", "#7c3aed", "#dc2626"],
        ),
        xy.x_axis(label="quarter"),
        xy.y_axis(label="revenue"),
        title="Stacked revenue bars",
        width="100%",
        height=430,
    )


def horizontal_bars() -> xy.Chart:
    regions = ["NA", "EU", "APAC", "LATAM", "MEA"]
    values = np.array([142.0, 128.0, 116.0, 74.0, 52.0])
    return xy.bar_chart(
        xy.bar(regions, values, orientation="horizontal", name="revenue", color="#9333ea"),
        xy.x_axis(label="revenue"),
        xy.y_axis(label="region"),
        title="Horizontal category bars",
        width="100%",
        height=430,
    )


def normalized_bars() -> xy.Chart:
    channels = ["Organic", "Paid", "Partner", "Lifecycle", "Events"]
    values = np.array(
        [
            [52.0, 34.0, 22.0, 44.0, 28.0],
            [31.0, 48.0, 56.0, 33.0, 45.0],
            [17.0, 18.0, 22.0, 23.0, 27.0],
        ]
    )
    return xy.bar_chart(
        xy.bar(
            channels,
            values,
            mode="normalized",
            series=["New", "Returning", "Reactivated"],
            colors=["#2563eb", "#14b8a6", "#f59e0b"],
        ),
        xy.x_axis(label="acquisition channel"),
        xy.y_axis(
            label="customer mix",
            domain=(0, 1),
            tick_values=[0, 0.25, 0.5, 0.75, 1],
            tick_labels=["0%", "25%", "50%", "75%", "100%"],
        ),
        title="100% stacked customer mix",
        width="100%",
        height=430,
    )


def diverging_bars() -> xy.Chart:
    products = ["Core", "Cloud", "Data", "Mobile", "Support", "Labs"]
    changes = [0.34, 0.21, 0.12, -0.08, -0.17, 0.27]
    return xy.bar_chart(
        *[
            xy.bar(
                [product],
                [value],
                name=product,
                color="#0f766e" if value >= 0 else "#e11d48",
                width=0.68,
                corner_radius=(6, 6),
            )
            for product, value in zip(products, changes, strict=True)
        ],
        *[
            xy.text(
                product,
                value,
                f"{value:+.0%}",
                dx=0,
                dy=-10 if value >= 0 else 18,
                anchor="middle",
            )
            for product, value in zip(products, changes, strict=True)
        ],
        xy.hline(0, color="#64748b", width=1.4),
        xy.x_axis(label="product"),
        xy.y_axis(label="year-over-year change", domain=(-0.3, 0.45)),
        xy.legend(show=False),
        title="Diverging product growth",
        width="100%",
        height=430,
    )


def rounded_goal_bars() -> xy.Chart:
    teams = ["Platform", "Growth", "Data", "Success", "Security"]
    completion = [92.0, 84.0, 78.0, 71.0, 63.0]
    fills = [
        {"gradient": "linear-gradient(to right, #2563eb, #60a5fa)", "space": "plot"},
        {"gradient": "linear-gradient(to right, #7c3aed, #a78bfa)", "space": "plot"},
        {"gradient": "linear-gradient(to right, #0891b2, #22d3ee)", "space": "plot"},
        {"gradient": "linear-gradient(to right, #0f766e, #34d399)", "space": "plot"},
        {"gradient": "linear-gradient(to right, #c2410c, #fb923c)", "space": "plot"},
    ]
    return xy.bar_chart(
        *[
            xy.bar(
                [team],
                [value],
                orientation="horizontal",
                name=team,
                fill=fill,
                width=0.62,
                corner_radius=10,
                stroke="rgba(15, 23, 42, 0.12)",
                stroke_width=1,
            )
            for team, value, fill in zip(teams, completion, fills, strict=True)
        ],
        *[
            xy.text(value, team, f"{value:.0f}%", dx=10, dy=4, anchor="start")
            for team, value in zip(teams, completion, strict=True)
        ],
        xy.vline(80, text="goal", color="#475569", width=1.5),
        xy.x_axis(label="quarterly goal completion", domain=(0, 110)),
        xy.y_axis(label=None),
        xy.legend(show=False),
        title="Team goal progress",
        width="100%",
        height=430,
    )


def heatmap() -> xy.Chart:
    cols = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = ["00", "04", "08", "12", "16", "20"]
    z = np.array(
        [
            [0.20, 0.18, 0.22, 0.26, 0.32, 0.44, 0.40],
            [0.28, 0.30, 0.35, 0.38, 0.42, 0.50, 0.46],
            [0.58, 0.63, 0.67, 0.70, 0.74, 0.62, 0.55],
            [0.72, 0.76, 0.80, 0.84, 0.88, 0.70, 0.64],
            [0.66, 0.69, 0.73, 0.78, 0.82, 0.76, 0.68],
            [0.38, 0.40, 0.44, 0.48, 0.55, 0.58, 0.50],
        ]
    )
    return xy.heatmap_chart(
        xy.heatmap(z, x=cols, y=rows, name="activity", colormap="turbo"),
        xy.x_axis(label="day"),
        xy.y_axis(label="hour"),
        title="Weekly activity heatmap",
        width="100%",
        height=430,
    )


def composed_layers() -> xy.Chart:
    data = {
        "month": np.array(["Jan", "Feb", "Mar", "Apr", "May", "Jun"]),
        "bookings": np.array([42.0, 45.0, 48.0, 52.0, 58.0, 63.0]),
        "target": np.array([44.0, 46.0, 50.0, 54.0, 57.0, 61.0]),
        "forecast": np.array([40.0, 43.0, 46.0, 50.0, 55.0, 60.0]),
        "sample": np.array([41.0, 47.0, 46.5, 53.5, 56.0, 64.0]),
    }
    return xy.chart(
        xy.bar(x="month", y="bookings", data=data, name="bookings", color="#f59e0b", opacity=0.34),
        xy.area(
            x="month",
            y="forecast",
            data=data,
            base=36.0,
            name="forecast band",
            color="#14b8a6",
            opacity=0.18,
        ),
        xy.scatter(x="month", y="sample", data=data, name="samples", color="#2563eb", size=8.0),
        xy.line(x="month", y="target", data=data, name="target", color="#dc2626", width=2.0),
        xy.x_band("Mar", "May", text="launch window", color="#7c3aed", opacity=0.12),
        xy.vline("Apr", text="release", color="#7c3aed", width=1.8),
        xy.marker("Jun", 64.0, text="sample peak", color="#2563eb", size=10.0, symbol="diamond"),
        xy.x_axis(label="month"),
        xy.y_axis(label="pipeline"),
        xy.tooltip(
            fields=["month", "bookings", "forecast", "sample", "target"],
            title="{month}",
            format={"bookings": ".1f", "forecast": ".1f", "sample": ".1f", "target": ".1f"},
        ),
        xy.legend(),
        title="Composed layered chart",
        width="100%",
        height=430,
    )


def annotated_heatmap() -> xy.Chart:
    rows = ["Low", "Medium", "High", "Critical"]
    cols = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    risk = np.array(
        [
            [0.18, 0.24, 0.22, 0.30, 0.28, 0.19],
            [0.36, 0.42, 0.46, 0.52, 0.49, 0.33],
            [0.62, 0.68, 0.72, 0.78, 0.74, 0.58],
            [0.82, 0.86, 0.90, 0.96, 0.91, 0.76],
        ]
    )
    data = {"day": cols, "risk_tier": rows, "risk_score": risk}
    return xy.chart(
        xy.heatmap(
            z="risk_score",
            x="day",
            y="risk_tier",
            data=data,
            name="risk score",
            colormap="turbo",
            domain=(0.0, 1.0),
        ),
        xy.threshold_zone(
            "Wed", "Fri", axis="x", text="launch window", color="#2563eb", opacity=0.10
        ),
        xy.threshold("High", axis="y", text="alert threshold", color="#e11d48", width=1.8),
        xy.marker(
            "Thu",
            "Critical",
            text="max load",
            color="#0f172a",
            size=9.0,
            symbol="diamond",
            dx=10.0,
            dy=20.0,
        ),
        xy.label("Wed", "High", "72%", dx=0.0, dy=-6.0, color="#0f172a", anchor="middle"),
        xy.label("Thu", "Critical", "96%", dx=0.0, dy=-6.0, color="#ffffff", anchor="middle"),
        xy.arrow("Tue", "Medium", "Wed", "High", text="escalation", color="#7c3aed"),
        xy.callout("Fri", "Critical", "ops review", dx=-78.0, dy=-30.0, color="#0f172a"),
        xy.x_axis(label="day"),
        xy.y_axis(label="risk tier"),
        xy.tooltip(
            fields=["day", "risk_tier", "risk_score"],
            title="{risk_tier} / {day}",
            format={"risk_score": ".0%"},
        ),
        xy.legend(),
        title="Annotated risk heatmap",
        width="100%",
        height=430,
    )


def axes_scales() -> xy.Chart:
    x = np.logspace(0.0, 6.0, 240)
    lx = np.log10(x)
    rank = 96.0 - lx * 11.5 + np.sin(lx * 3.0) * 3.0
    conversion = 0.08 + lx * 0.035 + np.cos(lx * 2.1) * 0.012
    sampled = np.linspace(0, len(x) - 1, 34, dtype=np.int64)
    return xy.chart(
        xy.line(x=x, y=rank, name="quality rank", color="#2563eb", width=2.0),
        xy.scatter(x=x[sampled], y=rank[sampled], name="sampled checks", color="#0f766e", size=7.0),
        xy.line(x=x, y=conversion, y_axis="y2", name="conversion", color="#dc2626", width=1.8),
        xy.x_axis(label="request volume", type_="log", domain=(1.0, 1_000_000.0), format=",.0f"),
        xy.y_axis(label="rank (reversed)", domain=(0.0, 100.0), reverse=True, format=".0f"),
        xy.y_axis(id="y2", label="conversion", side="right", domain=(0.0, 0.35), format=".0%"),
        xy.legend(),
        xy.interaction_config(
            pan_axes=("x", "y2"),
            zoom_axes=("x", "y2"),
            zoom_limits={"x": (1.0, 64.0), "y2": (0.5, 32.0)},
            reset_axes=("x", "y2"),
        ),
        title="Log scale, reversed axis, fixed domains, dual y-axis",
        width="100%",
        height=430,
    )


def interaction_basics() -> xy.Chart:
    x = np.linspace(0.0, 12.0, 180)
    actual = np.sin(x) + x * 0.08
    trend = x * 0.08
    return xy.chart(
        xy.scatter(x=x[::6], y=actual[::6], name="samples", color="#2563eb", size=8.0),
        xy.line(x=x, y=trend, name="trend", color="#dc2626", width=2.0),
        xy.interaction_config(
            hover=True,
            click=True,
            select=True,
            brush=True,
            crosshair=True,
            zoom_axes=("x",),
        ),
        xy.tooltip(fields=["x", "y"], format={"x": ".2f", "y": ".2f"}),
        xy.legend(),
        xy.x_axis(label="time", tick_count=13),
        xy.y_axis(label="value"),
        title="X-only zoom, crosshair, click, and brush select",
        width="100%",
        height=430,
    )


def business_overview() -> xy.Chart:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    values = np.array([[42.0, 45.0, 48.0, 51.0, 55.0, 59.0], [35.0, 38.0, 42.0, 40.0, 46.0, 50.0]])
    return xy.column_chart(
        xy.column(
            months,
            values,
            mode="grouped",
            series=["Revenue", "Pipeline"],
            colors=["#2563eb", "#16a34a"],
        ),
        xy.x_axis(label="month"),
        xy.y_axis(label="USD thousands"),
        title="Small business overview",
        width="100%",
        height=430,
    )


def retention_cohort() -> xy.Chart:
    cohorts = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    weeks = ["W0", "W1", "W2", "W3", "W4", "W5"]
    retention = np.array(
        [
            [1.00, 0.72, 0.61, 0.54, 0.48, 0.43],
            [1.00, 0.75, 0.64, 0.57, 0.51, 0.46],
            [1.00, 0.70, 0.59, 0.52, 0.47, 0.42],
            [1.00, 0.78, 0.66, 0.60, 0.55, 0.50],
            [1.00, 0.74, 0.63, 0.58, 0.53, 0.49],
            [1.00, 0.77, 0.68, 0.62, 0.57, 0.52],
        ]
    )
    return xy.heatmap_chart(
        xy.heatmap(retention, x=weeks, y=cohorts, name="retention", colormap="viridis"),
        xy.x_axis(label="week"),
        xy.y_axis(label="signup cohort"),
        title="Small retention cohort",
        width="100%",
        height=430,
    )


@dataclass(frozen=True)
class ChartInfo:
    """One gallery entry: a stable id, display copy, and its builder."""

    id: str
    title: str
    subtitle: str
    builder: Callable[[], xy.Chart]


GALLERY: tuple[ChartInfo, ...] = (
    ChartInfo(
        "business-overview",
        "Business overview",
        "Small grouped revenue and pipeline columns.",
        business_overview,
    ),
    ChartInfo(
        "retention-cohort",
        "Retention cohort",
        "Small product-analytics cohort heatmap.",
        retention_cohort,
    ),
    ChartInfo(
        "grouped-bars",
        "Grouped bars",
        "Multiple category series sharing the rectangle primitive.",
        grouped_bars,
    ),
    ChartInfo(
        "stacked-bars",
        "Stacked bars",
        "Positive series stacked from a shared baseline.",
        stacked_bars,
    ),
    ChartInfo(
        "horizontal-bars",
        "Horizontal bars",
        "Category labels on y with value bars along x.",
        horizontal_bars,
    ),
    ChartInfo(
        "normalized-bars",
        "100% stacked bars",
        "Per-channel customer mix normalized to 100%.",
        normalized_bars,
    ),
    ChartInfo(
        "diverging-bars",
        "Diverging growth bars",
        "Positive/negative change with direct value labels.",
        diverging_bars,
    ),
    ChartInfo(
        "rounded-goal-bars",
        "Rounded goal bars",
        "Gradient fills, rounded corners, and a target rule.",
        rounded_goal_bars,
    ),
    ChartInfo(
        "line-walk",
        "Decimated line",
        "120k sorted samples shipped as a screen-bounded line.",
        line_walk,
    ),
    ChartInfo(
        "area", "Filled area", "80k samples filled against a baseline with a line overlay.", area
    ),
    ChartInfo(
        "histogram",
        "Histogram",
        "500k values binned into the shared rectangle renderer.",
        histogram,
    ),
    ChartInfo(
        "histogram-x-zoom",
        "Histogram — x-only zoom",
        "Wheel/box zoom change latency range; y stays fixed.",
        histogram_x_zoom,
    ),
    ChartInfo(
        "box-zoom-drag",
        "Box-zoom drag mode",
        "Plain drag zooms x; double-click resets.",
        box_zoom_drag,
    ),
    ChartInfo("heatmap", "Heatmap", "Matrix values as colored cells on categorical axes.", heatmap),
    ChartInfo(
        "composed-layers",
        "Composed layers",
        "Bars, area, scatter, line, and annotations on one axis.",
        composed_layers,
    ),
    ChartInfo(
        "annotated-heatmap",
        "Annotated heatmap",
        "Risk heatmap with thresholds, markers, arrows, callouts.",
        annotated_heatmap,
    ),
    ChartInfo(
        "axes-scales",
        "Axes and scales",
        "Log x, reversed y, fixed domains, and a dual y-axis.",
        axes_scales,
    ),
    ChartInfo(
        "interaction-basics",
        "Interaction basics",
        "X-only zoom plus crosshair, click, and brush select.",
        interaction_basics,
    ),
    ChartInfo(
        "density-scatter",
        "Density scatter",
        "10M points aggregated into a responsive density surface.",
        density_scatter,
    ),
)

BY_ID: dict[str, ChartInfo] = {info.id: info for info in GALLERY}
