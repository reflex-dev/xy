from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
ASSET_DIR = APP_ROOT / "assets" / "charts"
PLOTLY_SAMPLE_POINTS = 100_000
STATIC_COLORED_SCATTER_POINTS = 10_000_000

# Prefer the checkout source when running the example from this repository.
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(REPO_ROOT / "python"))

from reflex_xy_app.live_drilldown import (  # noqa: E402
    colored_scatter_chart,
    colored_scatter_data,
    live_drilldown_html,
)

import xy  # noqa: E402


def write_chart(chart: xy.Chart, name: str) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSET_DIR / name
    chart.to_html(str(path))
    print(f"wrote {path.relative_to(APP_ROOT)}")


def write_live_drilldown_chart(name: str, html: str | None = None) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSET_DIR / name
    path.write_text(html or live_drilldown_html(), encoding="utf-8")
    print(f"wrote {path.relative_to(APP_ROOT)}")


def write_plotly_chart(name: str) -> None:
    import plotly.graph_objects as go

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    x, y, color, size = colored_scatter_data(PLOTLY_SAMPLE_POINTS)
    path = ASSET_DIR / name
    fig = go.Figure(
        go.Scattergl(
            x=x.astype(np.float32),
            y=y.astype(np.float32),
            mode="markers",
            marker={
                "color": color.astype(np.float32),
                "colorscale": "Viridis",
                "showscale": True,
                "size": size.astype(np.float32),
                "opacity": 0.72,
            },
        )
    )
    fig.update_layout(
        title=f"Plotly Scattergl ({PLOTLY_SAMPLE_POINTS // 1_000}k sample)",
        xaxis_title="feature A",
        yaxis_title="feature B",
        template="plotly_white",
        autosize=True,
        height=430,
        margin={"l": 58, "r": 22, "t": 62, "b": 54},
    )
    fig.write_html(
        str(path),
        config={"displaylogo": False, "responsive": True, "scrollZoom": True},
        full_html=True,
        include_plotlyjs=True,
    )
    print(f"wrote {path.relative_to(APP_ROOT)}")


def line_walk() -> xy.Chart:
    rng = np.random.default_rng(7)
    n = 120_000
    x = np.arange(n, dtype=np.float64)
    trend = np.sin(np.linspace(0, 24, n)) * 18
    y = np.cumsum(rng.normal(0, 0.35, n)) + trend
    return xy.line_chart(
        xy.line(x, y, name="walk", color="#3267c8", width=1.4),
        xy.x_axis(label="sample"),
        xy.y_axis(label="value"),
        title="120k sample random walk",
        width=980,
        height=430,
    )


def business_overview_demo() -> xy.Chart:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    values = np.array(
        [
            [42.0, 45.0, 48.0, 51.0, 55.0, 59.0],
            [35.0, 38.0, 42.0, 40.0, 46.0, 50.0],
        ]
    )
    return xy.column_chart(
        xy.column(
            months,
            values,
            mode="grouped",
            series=["Revenue", "Pipeline"],
            colors=["#2563eb", "#16a34a"],
            opacity=0.86,
        ),
        xy.x_axis(label="month"),
        xy.y_axis(label="USD thousands"),
        title="Small business overview",
        width="100%",
        height=430,
    )


def retention_cohort_demo() -> xy.Chart:
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
        ],
        dtype=np.float64,
    )
    return xy.heatmap_chart(
        xy.heatmap(
            retention, x=weeks, y=cohorts, name="retention", colormap="viridis", opacity=0.94
        ),
        xy.x_axis(label="week"),
        xy.y_axis(label="signup cohort"),
        title="Small retention cohort",
        width="100%",
        height=430,
    )


def area_demo() -> xy.Chart:
    rng = np.random.default_rng(13)
    n = 80_000
    x = np.arange(n, dtype=np.float64)
    seasonal = 35 + np.sin(np.linspace(0, 28, n)) * 8
    y = seasonal + np.cumsum(rng.normal(0, 0.025, n))
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


def colored_scatter() -> xy.Chart:
    return colored_scatter_chart(
        STATIC_COLORED_SCATTER_POINTS,
        title=f"{STATIC_COLORED_SCATTER_POINTS // 1_000_000}M colored scatter",
        width="100%",
        height=430,
    )


def density_scatter() -> xy.Chart:
    rng = np.random.default_rng(23)
    n = 10_000_000
    centers = np.array([[-1.4, -0.9], [-0.2, 0.8], [1.0, -0.2], [1.8, 1.1]])
    groups = rng.integers(0, len(centers), n, dtype=np.int8)
    x = centers[groups, 0].astype(np.float64, copy=True)
    y = centers[groups, 1].astype(np.float64, copy=True)
    x += rng.normal(0, 0.33, n)
    y += rng.normal(0, 0.33, n)
    return xy.scatter_chart(
        xy.scatter(x, y, opacity=0.9),
        xy.x_axis(label="x"),
        xy.y_axis(label="y"),
        title="10M density scatter",
        width="100%",
        height=430,
    )


def histogram_demo() -> xy.Chart:
    rng = np.random.default_rng(41)
    n = 500_000
    values = np.concatenate(
        [
            rng.normal(-1.2, 0.55, n // 2),
            rng.normal(1.4, 0.8, n // 2),
        ]
    )
    return xy.histogram_chart(
        xy.hist(values, bins=160, name="distribution", color="#3b82f6", opacity=0.82),
        xy.x_axis(label="value"),
        xy.y_axis(label="count"),
        title="500k sample histogram",
        width="100%",
        height=430,
    )


def histogram_x_zoom_demo() -> xy.Chart:
    rng = np.random.default_rng(73)
    values = rng.lognormal(mean=4.25, sigma=0.48, size=250_000)
    return xy.histogram_chart(
        xy.hist(values, bins=140, name="requests", color="#7c3aed", opacity=0.86),
        xy.interaction_config(zoom_axes=("x",)),
        xy.x_axis(label="request latency (ms)"),
        xy.y_axis(label="requests"),
        xy.theme(plot_background="#fafafa", grid_color="rgba(100, 116, 139, 0.16)"),
        title="Latency histogram with x-only zoom",
        width="100%",
        height=430,
    )


def bar_column_demo() -> xy.Chart:
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
            opacity=0.86,
        ),
        xy.x_axis(label="channel"),
        xy.y_axis(label="conversions"),
        title="Grouped category bars",
        width="100%",
        height=430,
    )


def stacked_bar_demo() -> xy.Chart:
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    values = np.array(
        [
            [42.0, 48.0, 54.0, 61.0],
            [28.0, 34.0, 37.0, 42.0],
            [16.0, 19.0, 24.0, 29.0],
        ]
    )
    return xy.column_chart(
        xy.column(
            quarters,
            values,
            mode="stacked",
            series=["Core", "Expansion", "Services"],
            colors=["#0f766e", "#7c3aed", "#dc2626"],
            opacity=0.88,
        ),
        xy.x_axis(label="quarter"),
        xy.y_axis(label="revenue"),
        title="Stacked revenue bars",
        width="100%",
        height=430,
    )


def horizontal_bar_demo() -> xy.Chart:
    regions = ["NA", "EU", "APAC", "LATAM", "MEA"]
    values = np.array([142.0, 128.0, 116.0, 74.0, 52.0])
    return xy.bar_chart(
        xy.bar(
            regions,
            values,
            orientation="horizontal",
            name="revenue",
            color="#9333ea",
            opacity=0.86,
        ),
        xy.x_axis(label="revenue"),
        xy.y_axis(label="region"),
        title="Horizontal category bars",
        width="100%",
        height=430,
    )


def normalized_bar_demo() -> xy.Chart:
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
            opacity=0.9,
        ),
        xy.x_axis(label="acquisition channel"),
        xy.y_axis(
            label="customer mix",
            domain=(0, 1),
            tick_values=[0, 0.25, 0.5, 0.75, 1],
            tick_labels=["0%", "25%", "50%", "75%", "100%"],
        ),
        xy.theme(plot_background="#f8fafc", grid_color="rgba(100, 116, 139, 0.18)"),
        title="100% stacked customer mix",
        width="100%",
        height=430,
    )


def diverging_bar_demo() -> xy.Chart:
    products = ["Core", "Cloud", "Data", "Mobile", "Support", "Labs"]
    changes = [0.34, 0.21, 0.12, -0.08, -0.17, 0.27]
    colors = ["#0f766e" if value >= 0 else "#e11d48" for value in changes]
    labels = [f"{value:+.0%}" for value in changes]

    return xy.bar_chart(
        *[
            xy.bar(
                [product],
                [value],
                name=product,
                color=color,
                width=0.68,
                opacity=0.92,
                corner_radius=(6, 6),
            )
            for product, value, color in zip(products, changes, colors, strict=True)
        ],
        *[
            xy.text(
                product,
                value,
                label,
                dx=0,
                dy=-10 if value >= 0 else 18,
                anchor="middle",
                color="#0f172a",
                style={"font_size": "13px", "font_weight": "700"},
            )
            for product, value, label in zip(products, changes, labels, strict=True)
        ],
        xy.hline(0, color="#64748b", width=1.4),
        xy.x_axis(label="product"),
        xy.y_axis(
            label="year-over-year change",
            domain=(-0.3, 0.45),
            tick_values=[-0.25, 0, 0.25],
            tick_labels=["-25%", "0%", "+25%"],
        ),
        xy.legend(show=False),
        xy.theme(plot_background="#ffffff", grid_color="rgba(100, 116, 139, 0.16)"),
        title="Diverging product growth",
        width="100%",
        height=430,
    )


def rounded_goal_bar_demo() -> xy.Chart:
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
                opacity=0.96,
            )
            for team, value, fill in zip(teams, completion, fills, strict=True)
        ],
        *[
            xy.text(
                value,
                team,
                f"{value:.0f}%",
                dx=10,
                dy=4,
                anchor="start",
                color="#0f172a",
                style={"font_size": "13px", "font_weight": "800"},
            )
            for team, value in zip(teams, completion, strict=True)
        ],
        xy.vline(80, text="goal", color="#475569", width=1.5),
        xy.x_axis(
            label="quarterly goal completion",
            domain=(0, 110),
            tick_values=[0, 25, 50, 75, 100],
            tick_labels=["0%", "25%", "50%", "75%", "100%"],
        ),
        xy.y_axis(label=None),
        xy.legend(show=False),
        xy.theme(plot_background="#f8fafc", grid_color="rgba(148, 163, 184, 0.20)"),
        title="Team goal progress",
        width="100%",
        height=430,
    )


def heatmap_demo() -> xy.Chart:
    rng = np.random.default_rng(97)
    cols = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = ["00", "04", "08", "12", "16", "20"]
    base = np.array(
        [
            [0.20, 0.18, 0.22, 0.26, 0.32, 0.44, 0.40],
            [0.28, 0.30, 0.35, 0.38, 0.42, 0.50, 0.46],
            [0.58, 0.63, 0.67, 0.70, 0.74, 0.62, 0.55],
            [0.72, 0.76, 0.80, 0.84, 0.88, 0.70, 0.64],
            [0.66, 0.69, 0.73, 0.78, 0.82, 0.76, 0.68],
            [0.38, 0.40, 0.44, 0.48, 0.55, 0.58, 0.50],
        ],
        dtype=np.float64,
    )
    z = base + rng.normal(0, 0.025, base.shape)
    return xy.heatmap_chart(
        xy.heatmap(z, x=cols, y=rows, name="activity", colormap="turbo", opacity=0.94),
        xy.x_axis(label="day"),
        xy.y_axis(label="hour"),
        title="Weekly activity heatmap",
        width="100%",
        height=430,
    )


def composed_layers_demo() -> xy.Chart:
    monthly = {
        "month": np.array(["Jan", "Feb", "Mar", "Apr", "May", "Jun"]),
        "bookings": np.array([42.0, 45.0, 48.0, 52.0, 58.0, 63.0]),
        "target": np.array([44.0, 46.0, 50.0, 54.0, 57.0, 61.0]),
        "forecast": np.array([40.0, 43.0, 46.0, 50.0, 55.0, 60.0]),
        "sample": np.array([41.0, 47.0, 46.5, 53.5, 56.0, 64.0]),
    }
    return xy.chart(
        xy.bar(
            x="month", y="bookings", data=monthly, name="bookings", color="#f59e0b", opacity=0.34
        ),
        xy.area(
            x="month",
            y="forecast",
            data=monthly,
            base=36.0,
            name="forecast band",
            color="#14b8a6",
            opacity=0.18,
        ),
        xy.scatter(
            x="month",
            y="sample",
            data=monthly,
            name="samples",
            color="#2563eb",
            size=8.0,
            opacity=0.86,
        ),
        xy.line(x="month", y="target", data=monthly, name="target", color="#dc2626", width=2.0),
        xy.x_band("Mar", "May", text="launch window", color="#7c3aed", opacity=0.12),
        xy.vline("Apr", text="release", color="#7c3aed", width=1.8),
        xy.marker(
            "Jun",
            64.0,
            text="sample peak",
            color="#2563eb",
            size=10.0,
            symbol="diamond",
            dx=-12.0,
            dy=-22.0,
            anchor="end",
        ),
        xy.x_axis(label="month"),
        xy.y_axis(label="pipeline"),
        xy.tooltip(
            fields=["month", "bookings", "forecast", "sample", "target"],
            title="{month}",
            format={
                "bookings": ".1f",
                "forecast": ".1f",
                "sample": ".1f",
                "target": ".1f",
            },
        ),
        xy.legend(),
        title="Composed layered chart",
        width="100%",
        height=430,
    )


def annotated_heatmap_demo() -> xy.Chart:
    rows = ["Low", "Medium", "High", "Critical"]
    cols = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    risk = np.array(
        [
            [0.18, 0.24, 0.22, 0.30, 0.28, 0.19],
            [0.36, 0.42, 0.46, 0.52, 0.49, 0.33],
            [0.62, 0.68, 0.72, 0.78, 0.74, 0.58],
            [0.82, 0.86, 0.90, 0.96, 0.91, 0.76],
        ],
        dtype=np.float64,
    )
    data = {"day": cols, "risk_tier": rows, "risk_score": risk}
    # Opaque placeholders stand in for real Reflex components in the app.
    legend_component = object()
    tooltip_component = object()
    return xy.chart(
        xy.heatmap(
            z="risk_score",
            x="day",
            y="risk_tier",
            data=data,
            name="risk score",
            colormap="turbo",
            domain=(0.0, 1.0),
            opacity=0.90,
        ),
        xy.threshold_zone(
            "Wed",
            "Fri",
            axis="x",
            text="launch window",
            color="#2563eb",
            opacity=0.10,
            style={
                "color": "#1d4ed8",
                "background": "rgba(219, 234, 254, 0.92)",
                "border": "1px solid rgba(37, 99, 235, 0.22)",
                "border_radius": 6,
                "padding": "3px 6px",
                "font_weight": 700,
            },
        ),
        xy.threshold(
            "High",
            axis="y",
            text="alert threshold",
            color="#e11d48",
            width=1.8,
            style={
                "color": "#be123c",
                "background": "rgba(255, 241, 242, 0.96)",
                "border": "1px solid rgba(225, 29, 72, 0.22)",
                "border_radius": 6,
                "padding": "3px 6px",
                "font_weight": 700,
            },
        ),
        xy.marker(
            "Thu",
            "Critical",
            text="max load",
            color="#0f172a",
            size=9.0,
            symbol="diamond",
            dx=10.0,
            dy=20.0,
            style={
                "background": "rgba(15, 23, 42, 0.88)",
                "label_color": "#ffffff",
                "border_radius": 6,
                "padding": "3px 7px",
                "box_shadow": "0 10px 24px rgba(15, 23, 42, 0.18)",
            },
        ),
        xy.label(
            "Wed",
            "High",
            "72%",
            dx=0.0,
            dy=-6.0,
            color="#0f172a",
            anchor="middle",
            style={
                "font_weight": 800,
                "font_size": 11,
                "text_shadow": "0 1px 2px rgba(255, 255, 255, 0.70)",
            },
        ),
        xy.label(
            "Thu",
            "Critical",
            "96%",
            dx=0.0,
            dy=-6.0,
            color="#ffffff",
            anchor="middle",
            style={
                "font_weight": 800,
                "font_size": 11,
                "text_shadow": "0 1px 2px rgba(15, 23, 42, 0.55)",
            },
        ),
        xy.arrow("Tue", "Medium", "Wed", "High", text="escalation", color="#7c3aed"),
        xy.callout(
            "Fri",
            "Critical",
            "ops review",
            dx=-78.0,
            dy=-30.0,
            color="#0f172a",
            style={
                "background": "rgba(255, 255, 255, 0.94)",
                "border": "1px solid rgba(15, 23, 42, 0.16)",
                "border_radius": 6,
                "padding": "3px 7px",
            },
        ),
        xy.theme(
            plot_background="#f8fafc",
            grid_color="rgba(100, 116, 139, 0.16)",
            axis_color="#cbd5e1",
            text_color="#334155",
        ),
        xy.x_axis(
            label="day",
            style={"tick_color": "#334155", "label_color": "#0f172a", "label_size": 12},
        ),
        xy.y_axis(
            label="risk tier",
            style={"tick_color": "#334155", "label_color": "#0f172a", "label_size": 12},
        ),
        xy.legend(legend_component, show=False),
        xy.tooltip(
            tooltip_component,
            show=False,
            fields=["day", "risk_tier", "risk_score"],
            title="{risk_tier} / {day}",
            format={"risk_score": ".0%"},
        ),
        title="Annotated risk heatmap",
        width="100%",
        height=430,
    )


def axes_scales_demo() -> xy.Chart:
    x = np.logspace(0.0, 6.0, 240)
    lx = np.log10(x)
    rank = 96.0 - lx * 11.5 + np.sin(lx * 3.0) * 3.0
    conversion = 0.08 + lx * 0.035 + np.cos(lx * 2.1) * 0.012
    sampled = np.linspace(0, len(x) - 1, 34, dtype=np.int64)
    return xy.chart(
        xy.line(x=x, y=rank, name="quality rank", color="#2563eb", width=2.0),
        xy.scatter(x=x[sampled], y=rank[sampled], name="sampled checks", color="#0f766e", size=7.0),
        xy.line(
            x=x,
            y=conversion,
            y_axis="y2",
            name="conversion",
            color="#dc2626",
            width=1.8,
        ),
        xy.x_axis(
            label="request volume",
            label_position="inside_end",
            label_offset=8,
            type_="log",
            domain=(1.0, 1_000_000.0),
            format=",.0f",
            tick_count=9,
            tick_label_strategy="auto",
            tick_label_min_gap=18,
            style={"grid_color": "rgba(37,99,235,.14)", "tick_color": "#1d4ed8"},
        ),
        xy.y_axis(
            label="rank (reversed)",
            label_position="inside_start",
            label_offset=10,
            label_angle=-90,
            domain=(0.0, 100.0),
            reverse=True,
            format=".0f",
            tick_count=5,
            tick_label_strategy="hide",
            style={"axis_color": "#2563eb", "label_color": "#1e40af"},
        ),
        xy.y_axis(
            id="y2",
            label="conversion",
            label_position={
                "right": 16,
                "top": 18,
                "transform": "none",
                "textAlign": "right",
            },
            side="right",
            domain=(0.0, 0.35),
            format=".0%",
            tick_count=4,
            tick_label_strategy="hide",
            style={"axis_color": "#dc2626", "tick_color": "#991b1b", "label_color": "#991b1b"},
        ),
        xy.tooltip(fields=["x", "y"], format={"x": ",.0f", "y": ".2f"}),
        xy.legend(),
        title="Log scale, reversed axis, fixed domains, dual y-axis",
        width="100%",
        height=430,
    )


def interaction_basics_demo() -> xy.Chart:
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
            view_change=True,
            zoom_axes=("x",),
            link_group="demo-linked-x",
            link_axes=("x",),
        ),
        xy.theme(plot_background="white", grid_color="rgba(37,99,235,.12)"),
        xy.tooltip(fields=["x", "y"], format={"x": ".2f", "y": ".2f"}),
        xy.legend(),
        xy.x_axis(label="time", tick_count=13),
        xy.y_axis(label="value"),
        title="X-only zoom, crosshair, click, and brush select",
        width="100%",
        height=430,
    )


def custom_chrome_demo() -> xy.Chart:
    data = {
        "activation": [0.72, 0.81, 0.58, 0.93, 0.66, 0.88, 0.49, 0.77],
        "retention": [0.61, 0.74, 0.52, 0.86, 0.57, 0.81, 0.46, 0.69],
        "segment": [
            "Enterprise",
            "Enterprise",
            "Growth",
            "Enterprise",
            "Self serve",
            "Growth",
            "Self serve",
            "Growth",
        ],
    }
    # Opaque placeholders exercise the same core API shape that real Reflex
    # components use. They are intentionally not serialized into the HTML.
    legend_component = object()
    tooltip_component = object()
    return xy.chart(
        xy.scatter(
            x="activation",
            y="retention",
            color="segment",
            size=18.0,
            data=data,
            name="accounts",
            opacity=0.88,
        ),
        xy.legend(legend_component, show=False),
        xy.tooltip(
            tooltip_component,
            show=False,
            fields=["activation", "retention", "segment"],
            title="{segment}",
            format={"activation": ".2f", "retention": ".2f"},
        ),
        xy.x_axis(label="activation"),
        xy.y_axis(label="retention"),
        title="Custom Reflex legend + tooltip",
        width="100%",
        height=430,
    )


def custom_chrome_html() -> str:
    html = custom_chrome_demo().to_html()
    render_call = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    replacement = (
        "window.__xyCustomChromeView = "
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    )
    if render_call not in html:
        raise RuntimeError("xy standalone render call changed")
    bridge = """
<script>
(() => {
  const attach = () => {
    const view = window.__xyCustomChromeView;
    if (!view || view.__customChromeBridge || !view.canvas) return false;
    view.__customChromeBridge = true;
    const send = (type, row, clientX, clientY) => {
      const rect = view.canvas.getBoundingClientRect();
      const x = Number(clientX) - rect.left;
      const y = Number(clientY) - rect.top;
      if (type === "hover" && (!Number.isFinite(x) || !Number.isFinite(y))) return;
      window.parent.postMessage({
        source: "xy-custom-chrome",
        chart: "custom-chrome",
        type,
        row,
        x,
        y,
      }, window.location.origin);
    };
    view.canvas.addEventListener("pointermove", (event) => {
      if (view._transitionActive && view._transitionActive()) {
        send("leave", null, event.clientX, event.clientY);
        return;
      }
      const rect = view.canvas.getBoundingClientRect();
      const cssX = event.clientX - rect.left;
      const cssY = event.clientY - rect.top;
      const hit = (
        (view._pickAt && view._pickAt(cssX, cssY)) ||
        (view._hoverAt && view._hoverAt(cssX, cssY))
      );
      if (!hit || !view._localRow) {
        send("leave", null, event.clientX, event.clientY);
        return;
      }
      send("hover", view._localRow(hit), event.clientX, event.clientY);
    });
    view.canvas.addEventListener("pointerleave", () => send("leave", null, 0, 0));
    return true;
  };
  if (attach()) return;
  requestAnimationFrame(attach);
  window.setTimeout(attach, 80);
  window.setTimeout(attach, 300);
})();
</script>
"""
    return html.replace(render_call, replacement).replace("</body>", f"{bridge}\n</body>")


def write_custom_chrome_chart(name: str = "custom_chrome.html") -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSET_DIR / name
    path.write_text(custom_chrome_html(), encoding="utf-8")
    print(f"wrote {path.relative_to(APP_ROOT)}")


def annotated_heatmap_html() -> str:
    html = annotated_heatmap_demo().to_html()
    render_call = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    replacement = (
        "window.__xyAnnotatedHeatmapView = "
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    )
    if render_call not in html:
        raise RuntimeError("xy standalone render call changed")
    bridge = """
<script>
(() => {
  const attach = () => {
    const view = window.__xyAnnotatedHeatmapView;
    if (!view || view.__annotatedHeatmapBridge || !view.canvas) return false;
    view.__annotatedHeatmapBridge = true;
    const send = (type, row, clientX, clientY) => {
      const rect = view.canvas.getBoundingClientRect();
      const x = Number(clientX) - rect.left;
      const y = Number(clientY) - rect.top;
      if (type === "hover" && (!Number.isFinite(x) || !Number.isFinite(y))) return;
      window.parent.postMessage({
        source: "xy-annotated-heatmap",
        chart: "annotated-heatmap",
        type,
        row,
        x,
        y,
      }, window.location.origin);
    };
    view.canvas.addEventListener("pointermove", (event) => {
      const rect = view.canvas.getBoundingClientRect();
      const cssX = event.clientX - rect.left;
      const cssY = event.clientY - rect.top;
      const hit = view._hoverAt && view._hoverAt(cssX, cssY);
      if (!hit || !view._localRow) {
        send("leave", null, event.clientX, event.clientY);
        return;
      }
      send("hover", view._localRow(hit), event.clientX, event.clientY);
    });
    view.canvas.addEventListener("pointerleave", () => send("leave", null, 0, 0));
    return true;
  };
  if (attach()) return;
  requestAnimationFrame(attach);
  window.setTimeout(attach, 80);
  window.setTimeout(attach, 300);
})();
</script>
"""
    return html.replace(render_call, replacement).replace("</body>", f"{bridge}\n</body>")


def write_annotated_heatmap_chart(name: str = "annotated_heatmap.html") -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSET_DIR / name
    path.write_text(annotated_heatmap_html(), encoding="utf-8")
    print(f"wrote {path.relative_to(APP_ROOT)}")


def main() -> None:
    live_html = live_drilldown_html()
    write_live_drilldown_chart("live_drilldown_100m.html", live_html)
    write_live_drilldown_chart("live_drilldown_10m.html", live_html)
    write_custom_chrome_chart()
    write_chart(business_overview_demo(), "business_overview.html")
    write_chart(retention_cohort_demo(), "retention_cohort.html")
    write_chart(line_walk(), "line_walk.html")
    write_chart(area_demo(), "area.html")
    write_chart(colored_scatter(), "colored_scatter.html")
    write_plotly_chart("plotly_colored_scatter.html")
    write_chart(density_scatter(), "density_scatter.html")
    write_chart(histogram_demo(), "histogram.html")
    write_chart(histogram_x_zoom_demo(), "histogram_x_zoom.html")
    write_chart(bar_column_demo(), "bar_column.html")
    write_chart(stacked_bar_demo(), "stacked_bar.html")
    write_chart(horizontal_bar_demo(), "horizontal_bar.html")
    write_chart(normalized_bar_demo(), "normalized_bar.html")
    write_chart(diverging_bar_demo(), "diverging_bar.html")
    write_chart(rounded_goal_bar_demo(), "rounded_goal_bar.html")
    write_chart(heatmap_demo(), "heatmap.html")
    write_chart(composed_layers_demo(), "composed_layers.html")
    write_annotated_heatmap_chart()
    write_chart(axes_scales_demo(), "axes_scales.html")
    write_chart(interaction_basics_demo(), "interaction_basics.html")


if __name__ == "__main__":
    main()
