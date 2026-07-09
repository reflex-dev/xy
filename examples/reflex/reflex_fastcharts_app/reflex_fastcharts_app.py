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

CUSTOM_CHROME_CHART = {
    "id": "custom-chrome",
    "title": "Custom Reflex Chrome",
    "subtitle": "Built-in FastCharts legend and tooltip are disabled; Reflex renders both.",
    "src": "/charts/custom_chrome.html",
    "stat": "custom UI",
}

CUSTOM_CHROME_SEGMENTS = [
    {"label": "Enterprise", "color": "#4c78a8"},
    {"label": "Growth", "color": "#f58518"},
    {"label": "Self serve", "color": "#54a24b"},
]

ANNOTATED_HEATMAP_MARKERS = [
    {
        "label": "Launch window",
        "detail": "Wed through Fri launch period.",
        "color": "#2563eb",
        "background": "#dbeafe",
    },
    {
        "label": "Alert threshold",
        "detail": "High and Critical are operational alert tiers.",
        "color": "#e11d48",
        "background": "#ffe4e6",
    },
    {
        "label": "Ops review",
        "detail": "Critical Friday review.",
        "color": "#0f172a",
        "background": "#e2e8f0",
    },
]

CORE_API_STATUS = [
    {
        "title": "Composable layers",
        "status": "done",
        "color": "green",
        "shipped": "fc.chart(...) overlays scatter, line, bars, area, heatmap, tooltip, and legend.",
        "next": "More mixed-axis examples and richer z-order controls.",
    },
    {
        "title": "Annotations",
        "status": "done",
        "color": "green",
        "shipped": "Rules, bands, text labels, arrows, callouts, and shaded threshold zones.",
        "next": "Named event-marker presets and draggable annotation editing.",
    },
    {
        "title": "Axes and scales",
        "status": "done",
        "color": "green",
        "shipped": "Linear, time, categorical, log, reversed axes, fixed domains, dual y-axes, and tick formatters.",
        "next": "More date presets, axis-linked charts, and multi-axis interaction policies.",
    },
    {
        "title": "Interaction",
        "status": "partial",
        "color": "amber",
        "shipped": "Hover, wheel zoom, pan, box zoom, box select, and component event hooks.",
        "next": "Click selection, lasso, crosshair, linked charts, and synchronized brushing.",
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

COMPOSED_LAYERS_CHART = {
    "id": "composed-layers",
    "title": "Composed Layers",
    "subtitle": "Bars, area, scatter, line, and annotations sharing one categorical axis.",
    "src": "/charts/composed_layers.html",
    "stat": "overlay",
}

ANNOTATED_HEATMAP_CHART = {
    "id": "annotated-heatmap",
    "title": "Annotated Heatmap",
    "subtitle": "Risk heatmap with a guide, hover readout, and event annotations.",
    "src": "/charts/annotated_heatmap.html",
    "stat": "risk guide",
}

AXES_SCALES_CHART = {
    "id": "axes-scales",
    "title": "Axes And Scales",
    "subtitle": "Log x-scale, reversed fixed y-domain, formatted ticks, and right-side y2 overlay.",
    "src": "/charts/axes_scales.html",
    "stat": "axes",
}

INTERACTION_CHART = {
    "id": "interaction-basics",
    "title": "Interaction Basics",
    "subtitle": "Crosshair, click events, brush selection, and linked-view configuration.",
    "src": "/charts/interaction_basics.html",
    "stat": "events",
}

LIVE_BILLION_DRILLDOWN_CHART = {
    "id": "live-billion-drilldown",
    "title": "Live 1B Drilldown Scatter",
    "subtitle": "1B synthetic source points with Reflex-backed adaptive LOD.",
    "src": "/charts/live_drilldown_1b.html",
    "stat": "1B live",
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

CANDLESTICK_CHART = {
    "id": "candlestick",
    "title": "Finance Layer Editor",
    "subtitle": "AAPL-style OHLC candles with draggable finance drawings and studies.",
    "src": "/charts/candlestick_editor.html",
    "stat": "editor",
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

FINANCE_CHARTS = [
    CANDLESTICK_CHART,
]

BUSINESS_CHARTS = [
    CUSTOM_CHROME_CHART,
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
    COMPOSED_LAYERS_CHART,
    ANNOTATED_HEATMAP_CHART,
    AXES_SCALES_CHART,
    INTERACTION_CHART,
]

LARGE_DATA_CHARTS = [
    DENSITY_CHART,
    *COMPARISON_CHARTS,
    LIVE_DRILLDOWN_CHART,
    LIVE_BILLION_DRILLDOWN_CHART,
]

CHART_NAV = [
    *BUSINESS_CHARTS,
    *CORE_CHARTS,
    *FINANCE_CHARTS,
    *LARGE_DATA_CHARTS,
]

CHART_CODE_SNIPPETS = {
    "live-billion-drilldown": """
# 1B synthetic source points; the Reflex backend answers adaptive LOD
# drill requests, so the browser only ever holds a screen-bounded payload.
from reflex_fastcharts_app.live_drilldown import billion_drilldown_html

Path("assets/charts/live_drilldown_1b.html").write_text(billion_drilldown_html())
""",
    "candlestick": """
from fastcharts import Figure

# Fluent form; the composition form is fc.candlestick_chart(fc.candlestick(...))
fig = Figure(title="Finance layer editor", y_side="right")
fig.candlestick(
    dates, o, h, l, c,
    up_color="#26a69a", down_color="#ef5350",
)
""",
    "custom-chrome": """
import fastcharts as fc
import reflex as rx

def my_legend():
    return rx.box(
        rx.text("Segment"),
        rx.hstack(rx.box(background="#4c78a8"), rx.text("Enterprise")),
        rx.hstack(rx.box(background="#f58518"), rx.text("Growth")),
        rx.hstack(rx.box(background="#54a24b"), rx.text("Self serve")),
    )

def my_tooltip():
    return rx.box(
        rx.text(id="tooltip-title"),
        rx.text(id="tooltip-activation"),
        rx.text(id="tooltip-retention"),
        background="linear-gradient(135deg, #2563eb, #7c3aed)",
        color="#ffffff",
    )

data = {
    "activation": [0.72, 0.81, 0.58, 0.93],
    "retention": [0.61, 0.74, 0.52, 0.86],
    "segment": ["Enterprise", "Enterprise", "Growth", "Enterprise"],
}

chart = fc.chart(
    fc.scatter(
        x="activation",
        y="retention",
        color="segment",
        size=18,
        data=data,
        name="accounts",
    ),
    # show=False disables the built-in FastCharts chrome. The Reflex
    # components still belong to the chart and can be mounted by the panel.
    fc.legend(my_legend(), show=False),
    fc.tooltip(
        my_tooltip(),
        show=False,
        fields=["activation", "retention", "segment"],
        title="{segment}",
        format={"activation": ".2f", "retention": ".2f"},
    ),
    fc.x_axis(label="activation"),
    fc.y_axis(label="retention"),
    title="Custom Reflex legend + tooltip",
    width="100%",
    height=430,
)

# This example app embeds prebuilt chart.to_html() assets. The iframe bridge
# owns that export detail; custom Reflex chrome stays keyed by slot name.
def fastcharts_html_chart(chart, src):
    chrome = chart.reflex_components()
    return rx.box(
        rx.el.iframe(src=src, width="100%"),
        chrome["legend"],
        chrome["tooltip"],
        position="relative",
    )

def chart_panel():
    return fastcharts_html_chart(chart, "/charts/custom_chrome.html")
""".strip(),
    "business-overview": """
from fastcharts import Figure
import numpy as np

months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
values = np.array([
    [42, 45, 48, 51, 55, 59],
    [35, 38, 42, 40, 46, 50],
])

fig = Figure(
    title="Small business overview",
    x_label="month",
    y_label="USD thousands",
    width="100%",
    height=430,
).column(
    months,
    values,
    mode="grouped",
    series=["Revenue", "Pipeline"],
    colors=["#2563eb", "#16a34a"],
)

fig.to_html("assets/charts/business_overview.html")
""".strip(),
    "retention-cohort": """
from fastcharts import Figure
import numpy as np

cohorts = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
weeks = ["W0", "W1", "W2", "W3", "W4", "W5"]
retention = np.array([
    [1.00, 0.72, 0.61, 0.54, 0.48, 0.43],
    [1.00, 0.75, 0.64, 0.57, 0.51, 0.46],
    [1.00, 0.70, 0.59, 0.52, 0.47, 0.42],
    [1.00, 0.78, 0.66, 0.60, 0.55, 0.50],
    [1.00, 0.74, 0.63, 0.58, 0.53, 0.49],
    [1.00, 0.77, 0.68, 0.62, 0.57, 0.52],
])

fig = Figure(
    title="Small retention cohort",
    x_label="week",
    y_label="signup cohort",
    width="100%",
    height=430,
).heatmap(retention, x=weeks, y=cohorts, name="retention", colormap="viridis")
""".strip(),
    "line": """
from fastcharts import Figure
import numpy as np

rng = np.random.default_rng(7)
n = 120_000
x = np.arange(n)
y = np.cumsum(rng.normal(0, 0.35, n)) + np.sin(np.linspace(0, 24, n)) * 18

fig = Figure(
    title="120k sample random walk",
    x_label="sample",
    y_label="value",
    width="100%",
    height=430,
).line(x, y, name="walk", color="#3267c8", width=1.4)
""".strip(),
    "area": """
from fastcharts import Figure
import numpy as np

rng = np.random.default_rng(13)
n = 80_000
x = np.arange(n)
y = 35 + np.sin(np.linspace(0, 28, n)) * 8 + np.cumsum(rng.normal(0, 0.025, n))
base = np.full(n, 25.0)

fig = Figure(
    title="80k filled area",
    x_label="sample",
    y_label="active users",
    width="100%",
    height=430,
).area(x, y, base=base, name="active users", color="#0891b2")
""".strip(),
    "histogram": """
from fastcharts import Figure
import numpy as np

rng = np.random.default_rng(41)
values = np.concatenate([
    rng.normal(-1.2, 0.55, 250_000),
    rng.normal(1.4, 0.8, 250_000),
])

fig = Figure(
    title="500k sample histogram",
    x_label="value",
    y_label="count",
    width="100%",
    height=430,
).hist(values, bins=160, name="distribution", color="#3b82f6")
""".strip(),
    "grouped-bars": """
from fastcharts import Figure
import numpy as np

categories = ["Search", "Ads", "Email", "Direct", "Partner", "Social"]
values = np.array([
    [118, 94, 72, 66, 43, 31],
    [88, 76, 55, 48, 29, 22],
    [42, 39, 26, 31, 19, 14],
])

fig = Figure(
    title="Grouped category bars",
    x_label="channel",
    y_label="conversions",
    width="100%",
    height=430,
).bar(
    categories,
    values,
    mode="grouped",
    series=["Desktop", "Mobile", "Tablet"],
    colors=["#2563eb", "#16a34a", "#f59e0b"],
)
""".strip(),
    "stacked-bars": """
from fastcharts import Figure
import numpy as np

quarters = ["Q1", "Q2", "Q3", "Q4"]
values = np.array([
    [42, 48, 54, 61],
    [28, 34, 37, 42],
    [16, 19, 24, 29],
])

fig = Figure(
    title="Stacked revenue bars",
    x_label="quarter",
    y_label="revenue",
    width="100%",
    height=430,
).column(
    quarters,
    values,
    mode="stacked",
    series=["Core", "Expansion", "Services"],
    colors=["#0f766e", "#7c3aed", "#dc2626"],
)
""".strip(),
    "horizontal-bars": """
from fastcharts import Figure
import numpy as np

regions = ["NA", "EU", "APAC", "LATAM", "MEA"]
values = np.array([142, 128, 116, 74, 52])

fig = Figure(
    title="Horizontal category bars",
    x_label="revenue",
    y_label="region",
    width="100%",
    height=430,
).bar(regions, values, orientation="horizontal", name="revenue", color="#9333ea")
""".strip(),
    "heatmap": """
from fastcharts import Figure
import numpy as np

cols = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
rows = ["00", "04", "08", "12", "16", "20"]
z = np.array([
    [0.20, 0.18, 0.22, 0.26, 0.32, 0.44, 0.40],
    [0.28, 0.30, 0.35, 0.38, 0.42, 0.50, 0.46],
    [0.58, 0.63, 0.67, 0.70, 0.74, 0.62, 0.55],
    [0.72, 0.76, 0.80, 0.84, 0.88, 0.70, 0.64],
    [0.66, 0.69, 0.73, 0.78, 0.82, 0.76, 0.68],
    [0.38, 0.40, 0.44, 0.48, 0.55, 0.58, 0.50],
])

fig = Figure(
    title="Weekly activity heatmap",
    x_label="day",
    y_label="hour",
    width="100%",
    height=430,
).heatmap(z, x=cols, y=rows, name="activity", colormap="turbo")
""".strip(),
    "composed-layers": """
import fastcharts as fc
import numpy as np

data = {
    "month": np.array(["Jan", "Feb", "Mar", "Apr", "May", "Jun"]),
    "bookings": np.array([42, 45, 48, 52, 58, 63]),
    "target": np.array([44, 46, 50, 54, 57, 61]),
    "forecast": np.array([40, 43, 46, 50, 55, 60]),
    "sample": np.array([41, 47, 46.5, 53.5, 56, 64]),
}

chart = fc.chart(
    fc.bar(x="month", y="bookings", data=data, name="bookings", color="#f59e0b", opacity=0.34),
    fc.area(x="month", y="forecast", data=data, base=36, name="forecast band", color="#14b8a6"),
    fc.scatter(x="month", y="sample", data=data, name="samples", color="#2563eb", size=8),
    fc.line(x="month", y="target", data=data, name="target", color="#dc2626", width=2),
    fc.x_band("Mar", "May", text="launch window", color="#7c3aed", opacity=0.12),
    fc.vline("Apr", text="release", color="#7c3aed", width=1.8),
    fc.marker("Jun", 64, text="sample peak", color="#2563eb", size=10, symbol="diamond"),
    fc.x_axis(label="month"),
    fc.y_axis(label="pipeline"),
    fc.tooltip(
        fields=["month", "bookings", "forecast", "sample", "target"],
        title="{month}",
        format={"bookings": ".1f", "forecast": ".1f", "sample": ".1f", "target": ".1f"},
    ),
    fc.legend(),
    title="Composed layered chart",
    width="100%",
    height=430,
)
""".strip(),
    "annotated-heatmap": """
import fastcharts as fc
import numpy as np
import reflex as rx

def risk_legend():
    return rx.box(
        rx.text("Risk guide"),
        rx.box(
            height="0.55rem",
            border_radius="999px",
            background="linear-gradient(90deg, #2563eb, #22c55e, #facc15, #ef4444)",
        ),
        rx.hstack(rx.text("0%"), rx.text("100%"), justify="between"),
    )

def risk_tooltip():
    return rx.box(
        rx.text(id="heatmap-tooltip-title"),
        rx.text(id="heatmap-tooltip-score"),
        class_name="rounded-md bg-slate-950 text-white shadow-xl",
    )

rows = ["Low", "Medium", "High", "Critical"]
cols = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
risk = np.array([
    [0.18, 0.24, 0.22, 0.30, 0.28, 0.19],
    [0.36, 0.42, 0.46, 0.52, 0.49, 0.33],
    [0.62, 0.68, 0.72, 0.78, 0.74, 0.58],
    [0.82, 0.86, 0.90, 0.96, 0.91, 0.76],
])
data = {"day": cols, "risk_tier": rows, "risk_score": risk}

chart = fc.chart(
    fc.heatmap(
        z="risk_score",
        x="day",
        y="risk_tier",
        data=data,
        name="risk score",
        colormap="turbo",
        domain=(0, 1),
    ),
    fc.threshold_zone("Wed", "Fri", axis="x", text="launch window", color="#2563eb", opacity=0.10),
    fc.threshold("High", axis="y", text="alert threshold", color="#e11d48", width=1.8),
    fc.marker("Thu", "Critical", text="max load", dx=8, dy=-12, color="#0f172a", symbol="diamond"),
    fc.label("Wed", "High", "72%", dx=0, dy=-6, color="#0f172a", anchor="middle"),
    fc.label("Thu", "Critical", "96%", dx=0, dy=-6, color="#ffffff", anchor="middle"),
    fc.arrow("Tue", "Medium", "Wed", "High", text="escalation", color="#7c3aed"),
    fc.callout("Fri", "Critical", "ops review", dx=-78, dy=-30, color="#0f172a"),
    fc.theme(plot_background="#f8fafc", grid_color="rgba(100, 116, 139, 0.16)"),
    fc.x_axis(label="day"),
    fc.y_axis(label="risk tier"),
    fc.legend(risk_legend(), show=False),
    fc.tooltip(
        risk_tooltip(),
        show=False,
        fields=["day", "risk_tier", "risk_score"],
        title="{risk_tier} / {day}",
        format={"risk_score": ".0%"},
    ),
    title="Annotated risk heatmap",
    width="100%",
    height=430,
)

def chart_panel():
    chrome = chart.reflex_components()
    return rx.box(
        rx.el.iframe(src="/charts/annotated_heatmap.html", width="100%"),
        chrome["legend"],
        chrome["tooltip"],
        position="relative",
    )
""".strip(),
    "axes-scales": """
import fastcharts as fc
import numpy as np

x = np.logspace(0, 6, 240)
lx = np.log10(x)
rank = 96 - lx * 11.5 + np.sin(lx * 3) * 3
conversion = 0.08 + lx * 0.035 + np.cos(lx * 2.1) * 0.012
sampled = np.linspace(0, len(x) - 1, 34, dtype=np.int64)

chart = fc.chart(
    fc.line(x=x, y=rank, name="quality rank", color="#2563eb", width=2),
    fc.scatter(x=x[sampled], y=rank[sampled], name="sampled checks", color="#0f766e", size=7),
    fc.line(
        x=x,
        y=conversion,
        y_axis="y2",
        name="conversion",
        color="#dc2626",
        width=1.8,
    ),
    fc.x_axis(
        label="request volume",
        label_position="inside_end",
        label_offset=8,
        type_="log",
        domain=(1, 1_000_000),
        format=",.0f",
        style={"grid_color": "rgba(37,99,235,.14)", "tick_color": "#1d4ed8"},
    ),
    fc.y_axis(
        label="rank (reversed)",
        label_position="inside_start",
        label_offset=10,
        label_angle=-90,
        domain=(0, 100),
        reverse=True,
        format=".0f",
        style={"axis_color": "#2563eb", "label_color": "#1e40af"},
    ),
    fc.y_axis(
        id="y2",
        label="conversion",
        label_position={
            "right": 16,
            "top": 18,
            "transform": "none",
            "textAlign": "right",
        },
        side="right",
        domain=(0, 0.35),
        format=".0%",
        style={"axis_color": "#dc2626", "tick_color": "#991b1b", "label_color": "#991b1b"},
    ),
    fc.legend(),
    title="Log scale, reversed axis, fixed domains, dual y-axis",
    width="100%",
    height=430,
)
""".strip(),
    "interaction-basics": """
import fastcharts as fc
import numpy as np

x = np.linspace(0, 12, 180)
actual = np.sin(x) + x * 0.08
trend = x * 0.08

def handle_brush(brush):
    print("brushed range", brush)

chart = fc.chart(
    fc.scatter(x=x[::6], y=actual[::6], name="samples", color="#2563eb", size=8),
    fc.line(x=x, y=trend, name="trend", color="#dc2626", width=2),
    fc.interaction_config(
        hover=True,
        click=True,
        select=True,
        brush=True,
        crosshair=True,
        link_group="demo-linked-x",
        link_axes=("x",),
    ),
    fc.mark_style(
        hover={"color": "#0f172a", "size": 18, "opacity": 0.9},
        selected={"opacity": 1},
        unselected={"opacity": 0.18},
    ),
    fc.theme(plot_background="white", grid_color="rgba(37,99,235,.12)"),
    fc.tooltip(fields=["x", "y"], format={"x": ".2f", "y": ".2f"}),
    fc.legend(),
    fc.x_axis(label="time", tick_count=13),
    fc.y_axis(label="value"),
    on_brush=handle_brush,
    title="Crosshair, click, brush select, linked x-axis",
    width="100%",
    height=430,
)
""".strip(),
    "density-scatter": """
from fastcharts import Figure
import numpy as np

rng = np.random.default_rng(23)
n = 10_000_000
centers = np.array([[-1.4, -0.9], [-0.2, 0.8], [1.0, -0.2], [1.8, 1.1]])
groups = rng.integers(0, len(centers), n, dtype=np.int8)
x = centers[groups, 0] + rng.normal(0, 0.33, n)
y = centers[groups, 1] + rng.normal(0, 0.33, n)

fig = Figure(
    title="10M density scatter",
    x_label="x",
    y_label="y",
    width="100%",
    height=430,
).scatter(x, y, opacity=0.9)
""".strip(),
    "fastcharts-scatter": """
from reflex_fastcharts_app.live_drilldown import colored_scatter_figure

fig = colored_scatter_figure(
    10_000_000,
    title="10M colored scatter",
    width="100%",
    height=430,
)
fig.to_html("assets/charts/colored_scatter.html")
""".strip(),
    "plotly-scatter": """
import plotly.graph_objects as go
from reflex_fastcharts_app.live_drilldown import colored_scatter_data

x, y, color, size = colored_scatter_data(100_000)
fig = go.Figure(
    go.Scattergl(
        x=x,
        y=y,
        mode="markers",
        marker={
            "color": color,
            "colorscale": "Viridis",
            "showscale": True,
            "size": size,
            "opacity": 0.72,
        },
    )
)
fig.write_html("assets/charts/plotly_colored_scatter.html", include_plotlyjs=True)
""".strip(),
    "live-drilldown": """
from pathlib import Path

import reflex as rx
from reflex_fastcharts_app.live_drilldown import LIVE_DRILLDOWN_ROUTE, drilldown_endpoint
from reflex_fastcharts_app.live_drilldown import live_drilldown_html

app = rx.App()
app.add_page(index, route="/")
if app._api is not None:
    app._api.add_route(LIVE_DRILLDOWN_ROUTE, drilldown_endpoint, methods=["POST"])

Path("assets/charts/live_drilldown_100m.html").write_text(
    live_drilldown_html(),
    encoding="utf-8",
)
""".strip(),
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


def api_status_card(item: dict[str, str]) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.heading(item["title"], size="4"),
            rx.badge(item["status"], variant="soft", color_scheme=item["color"]),
            justify="between",
            align="start",
            width="100%",
            gap="0.75rem",
        ),
        rx.text(item["shipped"], size="2", color="#344054", margin_top="0.75rem"),
        rx.box(
            rx.text("Next", size="1", color="#667085", font_weight="700"),
            rx.text(item["next"], size="2", color="#1d2939", margin_top="0.25rem"),
            margin_top="0.9rem",
            padding_top="0.75rem",
            border_top="1px solid #e4e7ec",
        ),
        padding="1rem",
        border="1px solid #dde3ea",
        border_radius="8px",
        background="#ffffff",
        min_height="184px",
    )


def core_api_status() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.box(
                rx.heading("Core API status", size="6"),
                rx.text(
                    "Current implementation state for the charting foundation.",
                    size="2",
                    color="gray",
                    margin_top="0.25rem",
                ),
            ),
            rx.badge("foundation", variant="soft", color_scheme="blue"),
            justify="between",
            align="start",
            width="100%",
            gap="1rem",
        ),
        rx.grid(
            *[api_status_card(item) for item in CORE_API_STATUS],
            columns={"initial": "1", "md": "2", "xl": "4"},
            gap="1rem",
            width="100%",
            margin_top="1rem",
        ),
        id="core-api-status",
        padding="1rem",
        border="1px solid #dde3ea",
        border_radius="8px",
        background="#fbfcfe",
        width="100%",
    )


def chart_code_drawer(chart: dict[str, str]) -> rx.Component:
    return rx.el.details(
        rx.el.summary(
            "Code",
            cursor="pointer",
            color="#1d2939",
            font_size="0.875rem",
            font_weight="700",
            padding="0.85rem 1rem",
            list_style="none",
        ),
        rx.el.pre(
            rx.el.code(
                CHART_CODE_SNIPPETS[chart["id"]],
                style={
                    "fontFamily": (
                        "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "
                        "'Liberation Mono', 'Courier New', monospace"
                    ),
                    "whiteSpace": "pre",
                },
            ),
            margin="0",
            padding="1rem",
            background="#111827",
            color="#e5e7eb",
            font_size="0.78rem",
            line_height="1.55",
            overflow_x="auto",
            border_top="1px solid rgba(148, 163, 184, 0.22)",
        ),
        border_top="1px solid #dde3ea",
        background="#ffffff",
        width="100%",
    )


def chart_panel(
    chart: dict[str, str],
    *,
    fluid: bool = False,
    loading: str = "lazy",
) -> rx.Component:
    iframe_height = "720px" if chart["id"] == "candlestick" else "430px"
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
                id=f"{chart['id']}-frame",
                src=chart["src"],
                title=chart["title"],
                loading=loading,
                style={
                    "border": "0",
                    "width": "100%" if fluid else "1040px",
                    "height": iframe_height,
                    "display": "block",
                    "background": "#ffffff",
                },
            ),
            border_top="1px solid #dde3ea",
            overflow_x="auto",
            overflow_y="hidden",
            background="#ffffff",
            width="100%",
            id=f"{chart['id']}-frame-wrap",
        ),
        chart_code_drawer(chart),
        border="1px solid #dde3ea",
        border_radius="8px",
        background="#fbfcfe",
        overflow="hidden",
        width="100%",
        id=chart["id"],
    )


def custom_legend_item(label: str, color: str) -> rx.Component:
    return rx.hstack(
        rx.box(
            width="0.7rem",
            height="0.7rem",
            border_radius="999px",
            background=color,
            flex_shrink="0",
        ),
        rx.text(label, size="1", color="#101828", line_height="1"),
        align="center",
        gap="0.45rem",
        min_width="0",
    )


def custom_legend() -> rx.Component:
    return rx.box(
        rx.text(
            "Segment",
            size="1",
            color="#667085",
            font_weight="700",
            text_transform="uppercase",
            letter_spacing="0",
        ),
        rx.vstack(
            *[
                custom_legend_item(segment["label"], segment["color"])
                for segment in CUSTOM_CHROME_SEGMENTS
            ],
            spacing="1",
            align="stretch",
            margin_top="0.45rem",
        ),
        position="absolute",
        top="0.75rem",
        right="0.75rem",
        z_index="3",
        id="custom-chrome-legend",
        class_name="custom-chrome-legend",
        padding="0.65rem 0.75rem",
        border="1px solid rgba(148, 163, 184, 0.35)",
        border_radius="8px",
        background="rgba(255, 255, 255, 0.88)",
        box_shadow="0 12px 28px rgba(15, 23, 42, 0.10)",
        backdrop_filter="blur(8px)",
        pointer_events="none",
    )


def custom_tooltip() -> rx.Component:
    return rx.box(
        rx.text(
            "segment",
            id="custom-chrome-tooltip-title",
            color="#ffffff",
            font_weight="700",
            font_size="0.84rem",
            line_height="1.15",
        ),
        rx.vstack(
            rx.hstack(
                rx.text("activation", color="rgba(255, 255, 255, 0.74)", font_size="0.76rem"),
                rx.text(
                    "0.00",
                    id="custom-chrome-tooltip-activation",
                    color="#ffffff",
                    font_size="0.76rem",
                    font_weight="700",
                ),
                justify="between",
                width="100%",
            ),
            rx.hstack(
                rx.text("retention", color="rgba(255, 255, 255, 0.74)", font_size="0.76rem"),
                rx.text(
                    "0.00",
                    id="custom-chrome-tooltip-retention",
                    color="#ffffff",
                    font_size="0.76rem",
                    font_weight="700",
                ),
                justify="between",
                width="100%",
            ),
            spacing="1",
            margin_top="0.5rem",
            width="100%",
        ),
        id="custom-chrome-tooltip",
        class_name="custom-chrome-tooltip",
        position="absolute",
        top="0",
        left="0",
        z_index="4",
        min_width="148px",
        padding="0.72rem 0.82rem",
        border="1px solid rgba(255, 255, 255, 0.24)",
        border_radius="8px",
        background="linear-gradient(135deg, rgba(37, 99, 235, 0.96), rgba(124, 58, 237, 0.94))",
        box_shadow="0 20px 42px rgba(30, 41, 59, 0.24)",
        opacity="0",
        pointer_events="none",
        transform="translate(12px, 12px)",
        transition="opacity 80ms ease",
    )


def annotated_heatmap_marker(marker: dict[str, str]) -> rx.Component:
    return rx.hstack(
        rx.box(
            width="0.72rem",
            height="0.72rem",
            border_radius="999px",
            background=marker["color"],
            box_shadow=f"0 0 0 4px {marker['background']}",
            flex_shrink="0",
        ),
        rx.box(
            rx.text(marker["label"], size="2", color="#0f172a", font_weight="700"),
            rx.text(marker["detail"], size="1", color="#64748b", margin_top="0.18rem"),
            min_width="0",
        ),
        align="start",
        gap="0.7rem",
        width="100%",
    )


def annotated_heatmap_legend() -> rx.Component:
    return rx.box(
        rx.text("Risk guide", size="2", color="#0f172a", font_weight="800"),
        rx.box(
            height="0.62rem",
            border_radius="999px",
            background="linear-gradient(90deg, #2563eb 0%, #22c55e 36%, #facc15 68%, #ef4444 100%)",
            box_shadow="inset 0 0 0 1px rgba(15, 23, 42, 0.12)",
            margin_top="0.7rem",
        ),
        rx.hstack(
            rx.text("0%", size="1", color="#64748b", font_weight="700"),
            rx.text("100%", size="1", color="#64748b", font_weight="700"),
            justify="between",
            width="100%",
            margin_top="0.35rem",
        ),
        rx.vstack(
            *[annotated_heatmap_marker(marker) for marker in ANNOTATED_HEATMAP_MARKERS],
            spacing="4",
            align="stretch",
            margin_top="1.2rem",
            width="100%",
        ),
        rx.box(
            rx.text("Current cell", size="1", color="#64748b", font_weight="800"),
            rx.hstack(
                rx.text(
                    "--",
                    id="annotated-heatmap-active-cell",
                    size="3",
                    color="#0f172a",
                    font_weight="800",
                ),
                rx.badge(
                    "--",
                    id="annotated-heatmap-active-score",
                    variant="soft",
                    color_scheme="gray",
                ),
                justify="between",
                align="center",
                width="100%",
                margin_top="0.5rem",
            ),
            padding_top="1rem",
            margin_top="1rem",
            border_top="1px solid #e2e8f0",
        ),
        id="annotated-heatmap-legend",
        class_name="annotated-heatmap-legend",
        flex="0 0 285px",
        padding="1rem",
        border_left="1px solid #dde3ea",
        background="linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
    )


def annotated_heatmap_tooltip() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text(
                "risk",
                id="annotated-heatmap-tooltip-title",
                color="#ffffff",
                font_weight="800",
                font_size="0.82rem",
                line_height="1.15",
            ),
            rx.text(
                "--",
                id="annotated-heatmap-tooltip-score",
                color="#bae6fd",
                font_weight="800",
                font_size="0.82rem",
            ),
            justify="between",
            align="center",
            width="100%",
            gap="0.75rem",
        ),
        rx.box(
            rx.box(
                id="annotated-heatmap-tooltip-bar",
                height="100%",
                width="0%",
                border_radius="999px",
                background="linear-gradient(90deg, #38bdf8, #facc15, #fb7185)",
            ),
            height="0.38rem",
            border_radius="999px",
            background="rgba(255, 255, 255, 0.18)",
            margin_top="0.65rem",
            overflow="hidden",
        ),
        id="annotated-heatmap-tooltip",
        class_name="annotated-heatmap-tooltip",
        position="absolute",
        top="0",
        left="0",
        z_index="4",
        min_width="190px",
        padding="0.72rem 0.82rem",
        border="1px solid rgba(255, 255, 255, 0.20)",
        border_radius="8px",
        background="linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.94))",
        box_shadow="0 20px 42px rgba(15, 23, 42, 0.28)",
        opacity="0",
        pointer_events="none",
        transform="translate(12px, 12px)",
        transition="opacity 80ms ease",
    )


def annotated_heatmap_bridge() -> rx.Component:
    return rx.script(
        """
(() => {
  if (window.__fastchartsAnnotatedHeatmapPanelBridge) return;
  window.__fastchartsAnnotatedHeatmapPanelBridge = true;

  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const tiers = ["Low", "Medium", "High", "Critical"];
  const label = (value, labels) => {
    if (typeof value === "string" && value.trim() !== "") return value;
    const index = Math.round(Number(value));
    return labels[index] || "--";
  };
  const score = (row) => Number(row && (row.risk_score ?? row.color_value));
  const pct = (value) => Number.isFinite(value) ? `${Math.round(value * 100)}%` : "--";
  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data || {};
    if (data.source !== "fastcharts-annotated-heatmap" || data.chart !== "annotated-heatmap") {
      return;
    }

    const tooltip = document.getElementById("annotated-heatmap-tooltip");
    const frame = document.getElementById("annotated-heatmap-frame");
    const wrap = document.getElementById("annotated-heatmap-frame-wrap");
    if (!tooltip || !frame || !wrap) return;

    if (data.type !== "hover" || !data.row) {
      tooltip.style.opacity = "0";
      setText("annotated-heatmap-active-cell", "--");
      setText("annotated-heatmap-active-score", "--");
      return;
    }

    const row = data.row;
    const day = label(row.day ?? row.x, days);
    const tier = label(row.risk_tier ?? row.y, tiers);
    const value = score(row);
    const textScore = pct(value);
    setText("annotated-heatmap-tooltip-title", `${tier} / ${day}`);
    setText("annotated-heatmap-tooltip-score", textScore);
    setText("annotated-heatmap-active-cell", `${tier} / ${day}`);
    setText("annotated-heatmap-active-score", textScore);

    const bar = document.getElementById("annotated-heatmap-tooltip-bar");
    if (bar) bar.style.width = `${Math.max(0, Math.min(100, Math.round(value * 100)))}%`;

    const frameRect = frame.getBoundingClientRect();
    const wrapRect = wrap.getBoundingClientRect();
    const leftFromFrame = Number(data.x) + frameRect.left - wrapRect.left + 16;
    const topFromFrame = Number(data.y) + frameRect.top - wrapRect.top + 16;
    const maxLeft = Math.max(12, wrap.clientWidth - tooltip.offsetWidth - 12);
    const maxTop = Math.max(12, wrap.clientHeight - tooltip.offsetHeight - 12);
    const left = Math.min(Math.max(12, leftFromFrame), maxLeft);
    const top = Math.min(Math.max(12, topFromFrame), maxTop);
    tooltip.style.transform = `translate(${left}px, ${top}px)`;
    tooltip.style.opacity = "1";
  });
})();
"""
    )


def custom_chrome_bridge() -> rx.Component:
    return rx.script(
        """
(() => {
  if (window.__fastchartsCustomChromePanelBridge) return;
  window.__fastchartsCustomChromePanelBridge = true;

  const formatValue = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(2) : "--";
  };
  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data || {};
    if (data.source !== "fastcharts-custom-chrome" || data.chart !== "custom-chrome") {
      return;
    }

    const tooltip = document.getElementById("custom-chrome-tooltip");
    const frame = document.getElementById("custom-chrome-frame");
    const wrap = document.getElementById("custom-chrome-frame-wrap");
    if (!tooltip || !frame || !wrap) return;

    if (data.type !== "hover" || !data.row) {
      tooltip.style.opacity = "0";
      return;
    }

    const row = data.row;
    setText("custom-chrome-tooltip-title", row.color_category || "point");
    setText("custom-chrome-tooltip-activation", formatValue(row.x));
    setText("custom-chrome-tooltip-retention", formatValue(row.y));

    const frameRect = frame.getBoundingClientRect();
    const wrapRect = wrap.getBoundingClientRect();
    const leftFromFrame = Number(data.x) + frameRect.left - wrapRect.left + 16;
    const topFromFrame = Number(data.y) + frameRect.top - wrapRect.top + 16;
    const maxLeft = Math.max(12, wrap.clientWidth - tooltip.offsetWidth - 12);
    const maxTop = Math.max(12, wrap.clientHeight - tooltip.offsetHeight - 12);
    const left = Math.min(Math.max(12, leftFromFrame), maxLeft);
    const top = Math.min(Math.max(12, topFromFrame), maxTop);
    tooltip.style.transform = `translate(${left}px, ${top}px)`;
    tooltip.style.opacity = "1";
  });
})();
"""
    )


def hash_scroll_bridge() -> rx.Component:
    return rx.script(
        """
(() => {
  if (window.__fastchartsHashScroller) return;
  window.__fastchartsHashScroller = true;

  const targetForHash = () => {
    const hash = window.location.hash;
    if (!hash || hash.length < 2) return null;
    const raw = hash.slice(1);
    try {
      return document.getElementById(decodeURIComponent(raw));
    } catch (_) {
      return document.getElementById(raw);
    }
  };

  const scrollToHash = () => {
    const target = targetForHash();
    if (target) target.scrollIntoView({ block: "start", inline: "nearest" });
  };

  const schedule = () => {
    requestAnimationFrame(scrollToHash);
    window.setTimeout(scrollToHash, 80);
    window.setTimeout(scrollToHash, 300);
  };

  window.addEventListener("hashchange", schedule);
  window.addEventListener("load", schedule);
  schedule();
})();
"""
    )


def custom_chrome_panel(chart: dict[str, str]) -> rx.Component:
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
            rx.box(
                rx.el.iframe(
                    id="custom-chrome-frame",
                    src=chart["src"],
                    title=chart["title"],
                    loading="eager",
                    style={
                        "border": "0",
                        "width": "100%",
                        "height": "430px",
                        "display": "block",
                        "background": "#ffffff",
                    },
                ),
                custom_legend(),
                custom_tooltip(),
                id="custom-chrome-frame-wrap",
                position="relative",
                min_height="430px",
                background="#ffffff",
                width="100%",
            ),
            border_top="1px solid #dde3ea",
            overflow="hidden",
            background="#ffffff",
            width="100%",
        ),
        custom_chrome_bridge(),
        chart_code_drawer(chart),
        border="1px solid #dde3ea",
        border_radius="8px",
        background="#fbfcfe",
        overflow="hidden",
        width="100%",
        id=chart["id"],
    )


def annotated_heatmap_panel(chart: dict[str, str]) -> rx.Component:
    return rx.box(
        rx.box(
            rx.hstack(
                rx.box(
                    rx.heading(chart["title"], size="5"),
                    rx.text(chart["subtitle"], size="2", color="gray", margin_top="0.25rem"),
                ),
                rx.badge(chart["stat"], variant="soft", color_scheme="purple"),
                justify="between",
                align="start",
                width="100%",
                gap="1rem",
            ),
            padding="1rem",
        ),
        rx.flex(
            rx.box(
                rx.el.iframe(
                    id="annotated-heatmap-frame",
                    src=chart["src"],
                    title=chart["title"],
                    loading="lazy",
                    style={
                        "border": "0",
                        "width": "100%",
                        "height": "430px",
                        "display": "block",
                        "background": "#ffffff",
                    },
                ),
                annotated_heatmap_tooltip(),
                id="annotated-heatmap-frame-wrap",
                position="relative",
                min_height="430px",
                background="#ffffff",
                flex="1 1 660px",
                min_width="0",
            ),
            annotated_heatmap_legend(),
            align="stretch",
            wrap="wrap",
            width="100%",
            border_top="1px solid #dde3ea",
            background="#ffffff",
            overflow="hidden",
        ),
        annotated_heatmap_bridge(),
        chart_code_drawer(chart),
        border="1px solid #dde3ea",
        border_radius="8px",
        background="#fbfcfe",
        overflow="hidden",
        width="100%",
        id=chart["id"],
    )


def chart_card(chart: dict[str, str], *, fluid: bool = False) -> rx.Component:
    if chart["id"] == CUSTOM_CHROME_CHART["id"]:
        return custom_chrome_panel(chart)
    if chart["id"] == ANNOTATED_HEATMAP_CHART["id"]:
        return annotated_heatmap_panel(chart)
    loading = "eager" if chart["id"] in {"business-overview", "retention-cohort"} else "lazy"
    return chart_panel(chart, fluid=fluid, loading=loading)


def chart_selector() -> rx.Component:
    return rx.flex(
        rx.link(
            "Core API status",
            href="#core-api-status",
            padding="0.45rem 0.65rem",
            border="1px solid #ccd6e2",
            border_radius="8px",
            background="#ffffff",
            color="#1d2939",
            text_decoration="none",
            font_size="0.875rem",
            font_weight="500",
        ),
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
            *[chart_card(chart, fluid=True) for chart in charts],
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
                metric("Largest demo", "1B points"),
                columns={"initial": "1", "sm": "2", "lg": "4"},
                gap="1rem",
                width="100%",
            ),
            chart_selector(),
            hash_scroll_bridge(),
            core_api_status(),
            chart_section("Business charts", BUSINESS_CHARTS),
            chart_section("Core 2D gallery", CORE_CHARTS),
            chart_section("Finance charts", FINANCE_CHARTS, columns={"initial": "1"}),
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
