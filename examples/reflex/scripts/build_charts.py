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

from reflex_fastcharts_app.live_drilldown import (  # noqa: E402
    billion_drilldown_html,
    colored_scatter_data,
    colored_scatter_figure,
    live_drilldown_html,
)

import fastcharts as fc  # noqa: E402
from fastcharts import Figure  # noqa: E402


def write_chart(fig: Figure | fc.Chart, name: str) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSET_DIR / name
    fig.to_html(str(path))
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


def line_walk() -> Figure:
    rng = np.random.default_rng(7)
    n = 120_000
    x = np.arange(n, dtype=np.float64)
    trend = np.sin(np.linspace(0, 24, n)) * 18
    y = np.cumsum(rng.normal(0, 0.35, n)) + trend
    return Figure(
        title="120k sample random walk",
        x_label="sample",
        y_label="value",
        width=980,
        height=430,
    ).line(x, y, name="walk", color="#3267c8", width=1.4)


def business_overview_demo() -> Figure:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    values = np.array(
        [
            [42.0, 45.0, 48.0, 51.0, 55.0, 59.0],
            [35.0, 38.0, 42.0, 40.0, 46.0, 50.0],
        ]
    )
    return Figure(
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
        opacity=0.86,
    )


def retention_cohort_demo() -> Figure:
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
    return Figure(
        title="Small retention cohort",
        x_label="week",
        y_label="signup cohort",
        width="100%",
        height=430,
    ).heatmap(retention, x=weeks, y=cohorts, name="retention", colormap="viridis", opacity=0.94)


def area_demo() -> Figure:
    rng = np.random.default_rng(13)
    n = 80_000
    x = np.arange(n, dtype=np.float64)
    seasonal = 35 + np.sin(np.linspace(0, 28, n)) * 8
    y = seasonal + np.cumsum(rng.normal(0, 0.025, n))
    base = np.full(n, 25.0)
    return Figure(
        title="80k filled area",
        x_label="sample",
        y_label="active users",
        width="100%",
        height=430,
    ).area(x, y, base=base, name="active users", color="#0891b2", opacity=0.34, line_width=1.1)


def colored_scatter() -> Figure:
    return colored_scatter_figure(
        STATIC_COLORED_SCATTER_POINTS,
        title=f"{STATIC_COLORED_SCATTER_POINTS // 1_000_000}M colored scatter",
        width="100%",
        height=430,
    )


def density_scatter() -> Figure:
    rng = np.random.default_rng(23)
    n = 10_000_000
    centers = np.array([[-1.4, -0.9], [-0.2, 0.8], [1.0, -0.2], [1.8, 1.1]])
    groups = rng.integers(0, len(centers), n, dtype=np.int8)
    x = centers[groups, 0].astype(np.float64, copy=True)
    y = centers[groups, 1].astype(np.float64, copy=True)
    x += rng.normal(0, 0.33, n)
    y += rng.normal(0, 0.33, n)
    return Figure(
        title="10M density scatter",
        x_label="x",
        y_label="y",
        width="100%",
        height=430,
    ).scatter(x, y, opacity=0.9)


def histogram_demo() -> Figure:
    rng = np.random.default_rng(41)
    n = 500_000
    values = np.concatenate(
        [
            rng.normal(-1.2, 0.55, n // 2),
            rng.normal(1.4, 0.8, n // 2),
        ]
    )
    return Figure(
        title="500k sample histogram",
        x_label="value",
        y_label="count",
        width="100%",
        height=430,
    ).hist(values, bins=160, name="distribution", color="#3b82f6", opacity=0.82)


def bar_column_demo() -> Figure:
    categories = ["Search", "Ads", "Email", "Direct", "Partner", "Social"]
    values = np.array(
        [
            [118.0, 94.0, 72.0, 66.0, 43.0, 31.0],
            [88.0, 76.0, 55.0, 48.0, 29.0, 22.0],
            [42.0, 39.0, 26.0, 31.0, 19.0, 14.0],
        ]
    )
    return Figure(
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
        opacity=0.86,
    )


def stacked_bar_demo() -> Figure:
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    values = np.array(
        [
            [42.0, 48.0, 54.0, 61.0],
            [28.0, 34.0, 37.0, 42.0],
            [16.0, 19.0, 24.0, 29.0],
        ]
    )
    return Figure(
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
        opacity=0.88,
    )


def horizontal_bar_demo() -> Figure:
    regions = ["NA", "EU", "APAC", "LATAM", "MEA"]
    values = np.array([142.0, 128.0, 116.0, 74.0, 52.0])
    return Figure(
        title="Horizontal category bars",
        x_label="revenue",
        y_label="region",
        width="100%",
        height=430,
    ).bar(
        regions,
        values,
        orientation="horizontal",
        name="revenue",
        color="#9333ea",
        opacity=0.86,
    )


def heatmap_demo() -> Figure:
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
    return Figure(
        title="Weekly activity heatmap",
        x_label="day",
        y_label="hour",
        width="100%",
        height=430,
    ).heatmap(z, x=cols, y=rows, name="activity", colormap="turbo", opacity=0.94)


def composed_layers_demo() -> fc.Chart:
    monthly = {
        "month": np.array(["Jan", "Feb", "Mar", "Apr", "May", "Jun"]),
        "bookings": np.array([42.0, 45.0, 48.0, 52.0, 58.0, 63.0]),
        "target": np.array([44.0, 46.0, 50.0, 54.0, 57.0, 61.0]),
        "forecast": np.array([40.0, 43.0, 46.0, 50.0, 55.0, 60.0]),
        "sample": np.array([41.0, 47.0, 46.5, 53.5, 56.0, 64.0]),
    }
    return fc.chart(
        fc.bar(
            x="month", y="bookings", data=monthly, name="bookings", color="#f59e0b", opacity=0.34
        ),
        fc.area(
            x="month",
            y="forecast",
            data=monthly,
            base=36.0,
            name="forecast band",
            color="#14b8a6",
            opacity=0.18,
        ),
        fc.scatter(
            x="month",
            y="sample",
            data=monthly,
            name="samples",
            color="#2563eb",
            size=8.0,
            opacity=0.86,
        ),
        fc.line(x="month", y="target", data=monthly, name="target", color="#dc2626", width=2.0),
        fc.x_band("Mar", "May", text="launch window", color="#7c3aed", opacity=0.12),
        fc.vline("Apr", text="release", color="#7c3aed", width=1.8),
        fc.marker(
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
        fc.x_axis(label="month"),
        fc.y_axis(label="pipeline"),
        fc.tooltip(
            fields=["month", "bookings", "forecast", "sample", "target"],
            title="{month}",
            format={
                "bookings": ".1f",
                "forecast": ".1f",
                "sample": ".1f",
                "target": ".1f",
            },
        ),
        fc.legend(),
        title="Composed layered chart",
        width="100%",
        height=430,
    )


def annotated_heatmap_demo() -> fc.Chart:
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
    return fc.chart(
        fc.heatmap(
            z="risk_score",
            x="day",
            y="risk_tier",
            data=data,
            name="risk score",
            colormap="turbo",
            domain=(0.0, 1.0),
            opacity=0.90,
        ),
        fc.threshold_zone(
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
        fc.threshold(
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
        fc.marker(
            "Thu",
            "Critical",
            text="max load",
            color="#0f172a",
            size=9.0,
            symbol="diamond",
            dx=8.0,
            dy=-12.0,
            style={
                "background": "rgba(15, 23, 42, 0.88)",
                "label_color": "#ffffff",
                "border_radius": 6,
                "padding": "3px 7px",
                "box_shadow": "0 10px 24px rgba(15, 23, 42, 0.18)",
            },
        ),
        fc.label(
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
        fc.label(
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
        fc.arrow("Tue", "Medium", "Wed", "High", text="escalation", color="#7c3aed"),
        fc.callout(
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
        fc.theme(
            plot_background="#f8fafc",
            grid_color="rgba(100, 116, 139, 0.16)",
            axis_color="#cbd5e1",
            text_color="#334155",
        ),
        fc.x_axis(
            label="day",
            style={"tick_color": "#334155", "label_color": "#0f172a", "label_size": 12},
        ),
        fc.y_axis(
            label="risk tier",
            style={"tick_color": "#334155", "label_color": "#0f172a", "label_size": 12},
        ),
        fc.legend(legend_component, show=False),
        fc.tooltip(
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


def axes_scales_demo() -> fc.Chart:
    x = np.logspace(0.0, 6.0, 240)
    lx = np.log10(x)
    rank = 96.0 - lx * 11.5 + np.sin(lx * 3.0) * 3.0
    conversion = 0.08 + lx * 0.035 + np.cos(lx * 2.1) * 0.012
    sampled = np.linspace(0, len(x) - 1, 34, dtype=np.int64)
    return fc.chart(
        fc.line(x=x, y=rank, name="quality rank", color="#2563eb", width=2.0),
        fc.scatter(x=x[sampled], y=rank[sampled], name="sampled checks", color="#0f766e", size=7.0),
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
            domain=(1.0, 1_000_000.0),
            format=",.0f",
            tick_count=9,
            tick_label_strategy="auto",
            tick_label_min_gap=18,
            style={"grid_color": "rgba(37,99,235,.14)", "tick_color": "#1d4ed8"},
        ),
        fc.y_axis(
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
            domain=(0.0, 0.35),
            format=".0%",
            tick_count=4,
            tick_label_strategy="hide",
            style={"axis_color": "#dc2626", "tick_color": "#991b1b", "label_color": "#991b1b"},
        ),
        fc.tooltip(fields=["x", "y"], format={"x": ",.0f", "y": ".2f"}),
        fc.legend(),
        title="Log scale, reversed axis, fixed domains, dual y-axis",
        width="100%",
        height=430,
    )


def interaction_basics_demo() -> fc.Chart:
    x = np.linspace(0.0, 12.0, 180)
    actual = np.sin(x) + x * 0.08
    trend = x * 0.08
    return fc.chart(
        fc.scatter(x=x[::6], y=actual[::6], name="samples", color="#2563eb", size=8.0),
        fc.line(x=x, y=trend, name="trend", color="#dc2626", width=2.0),
        fc.interaction_config(
            hover=True,
            click=True,
            select=True,
            brush=True,
            crosshair=True,
            view_change=True,
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
        title="Crosshair, click, brush select, linked x-axis",
        width="100%",
        height=430,
    )


def custom_chrome_demo() -> fc.Chart:
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
    return fc.chart(
        fc.scatter(
            x="activation",
            y="retention",
            color="segment",
            size=18.0,
            data=data,
            name="accounts",
            opacity=0.88,
        ),
        fc.legend(legend_component, show=False),
        fc.tooltip(
            tooltip_component,
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


def custom_chrome_html() -> str:
    html = custom_chrome_demo().to_html()
    render_call = (
        'fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);'
    )
    replacement = (
        "window.__fastchartsCustomChromeView = "
        'fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);'
    )
    if render_call not in html:
        raise RuntimeError("fastcharts standalone render call changed")
    bridge = """
<script>
(() => {
  const attach = () => {
    const view = window.__fastchartsCustomChromeView;
    if (!view || view.__customChromeBridge || !view.canvas) return false;
    view.__customChromeBridge = true;
    const send = (type, row, clientX, clientY) => {
      const rect = view.canvas.getBoundingClientRect();
      const x = Number(clientX) - rect.left;
      const y = Number(clientY) - rect.top;
      if (type === "hover" && (!Number.isFinite(x) || !Number.isFinite(y))) return;
      window.parent.postMessage({
        source: "fastcharts-custom-chrome",
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
    render_call = (
        'fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);'
    )
    replacement = (
        "window.__fastchartsAnnotatedHeatmapView = "
        'fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);'
    )
    if render_call not in html:
        raise RuntimeError("fastcharts standalone render call changed")
    bridge = """
<script>
(() => {
  const attach = () => {
    const view = window.__fastchartsAnnotatedHeatmapView;
    if (!view || view.__annotatedHeatmapBridge || !view.canvas) return false;
    view.__annotatedHeatmapBridge = true;
    const send = (type, row, clientX, clientY) => {
      const rect = view.canvas.getBoundingClientRect();
      const x = Number(clientX) - rect.left;
      const y = Number(clientY) - rect.top;
      if (type === "hover" && (!Number.isFinite(x) || !Number.isFinite(y))) return;
      window.parent.postMessage({
        source: "fastcharts-annotated-heatmap",
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


def write_html_asset(name: str, html: str) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSET_DIR / name
    path.write_text(html, encoding="utf-8")
    print(f"wrote {path.relative_to(APP_ROOT)}")


def finance_ohlcv() -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray
]:
    rng = np.random.default_rng(166)
    n = 150
    x = np.busday_offset("2026-01-02", np.arange(n)).astype("datetime64[ms]")
    trend = np.linspace(0, 24, n)
    wave = np.sin(np.linspace(0, 9, n)) * 8
    close = 282 + trend + wave + np.cumsum(rng.normal(0, 1.4, n))
    open_ = np.r_[close[0] - rng.normal(0, 1.2), close[:-1]] + rng.normal(0, 1.1, n)
    high = np.maximum(open_, close) + rng.uniform(1.2, 4.8, n)
    low = np.minimum(open_, close) - rng.uniform(1.0, 4.2, n)
    volume = rng.lognormal(mean=17.3, sigma=0.25, size=n)
    volume[-1] = max(volume[-1], volume.mean() * 1.8)
    return x, open_, high, low, close, volume


def candlestick_demo() -> fc.FinanceChart:
    x, open_, high, low, close, volume = finance_ohlcv()
    last_x = x[-1]
    end_x = np.busday_offset(last_x.astype("datetime64[D]"), 18).astype("datetime64[ms]")
    entry = float(close[-18])
    return fc.finance_chart(
        fc.candlestick(
            x=x,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            id="price",
            name="AAPL",
            up_color="#22ab94",
            down_color="#f23645",
            width_frac=0.82,
            opacity=0.98,
        ),
        fc.x_axis(type_="time"),
        fc.y_axis(side="right", scale="linear"),
        fc.volume_bars(
            source="price",
            style={
                "up_color": "#22ab94",
                "down_color": "#f23645",
                "grid_color": "#c8d0dc",
                "label_color": "#5f6b7a",
            },
        ),
        fc.bollinger_bands(
            source="price",
            window=20,
            id="BB 20",
            style={
                "color": "#6d5dfc",
                "band_color": "#7b61ff",
                "opacity": 0.62,
                "band_opacity": 0.34,
            },
        ),
        fc.moving_average(
            source="price", window=20, method="sma", id="MA 20", style={"color": "#2962ff"}
        ),
        fc.moving_average(
            source="price", window=50, method="ema", id="EMA 50", style={"color": "#ff9800"}
        ),
        fc.vwap(source="price", bands=(1.0,), id="VWAP", style={"color": "#089981"}),
        fc.short_position(
            source="price",
            entry=(last_x, entry),
            stop=entry * 1.06,
            target=entry * 0.92,
            end=end_x,
            id="Short setup",
            style={"target_color": "#22ab94", "stop_color": "#f23645", "line_color": "#111827"},
        ),
        fc.finance_tools(active="crosshair", snap="ohlc", editable=True),
        title="Finance layer editor",
        width="100%",
        height="100%",
    )


EDITOR_JS = r"""
function createFinanceLayerEditor(view) {
  const palette = document.getElementById("editor-palette");
  const frame = document.getElementById("editor-chart-frame");
  const layerList = document.getElementById("editor-layer-list");
  const status = document.getElementById("editor-status");
  const clearButton = document.getElementById("editor-clear");
  const customIds = new Set();
  let activeTool = null;
  let pointerDrag = null;
  let counter = 1;

  const originalAvwapDraw = fastcharts.LAYER_KINDS.anchored_vwap.draw;
  fastcharts.LAYER_KINDS.anchored_vwap.draw = (chart, ctx, layer) => {
    originalAvwapDraw(chart, ctx, layer);
    if (layer.props && layer.props.series) {
      drawLineSeries(chart, ctx, layer.props.series, layer.style && layer.style.color || "#f59e0b", 1.6);
    }
  };
  fastcharts.LAYER_KINDS.editor_line = {
    draw: (chart, ctx, layer) => drawLineSeries(chart, ctx, layer.props.series, layer.style.color, layer.style.width || 1.5)
  };
  fastcharts.LAYER_KINDS.editor_bollinger = {
    draw: (chart, ctx, layer) => {
      const s = layer.props.series;
      if (!s) return;
      drawLineSeries(chart, ctx, { x: s.x, y: s.upper }, layer.style.band_color || "#7b61ff", 1);
      drawLineSeries(chart, ctx, { x: s.x, y: s.lower }, layer.style.band_color || "#7b61ff", 1);
      drawLineSeries(chart, ctx, { x: s.x, y: s.middle }, layer.style.color || "#6d5dfc", 1.3);
    }
  };

  function candleGpu() {
    return view.gpuTraces.find((g) => g.candle && g.candle.cpu);
  }

  function candleCpu() {
    const g = candleGpu();
    return g ? g.candle.cpu : null;
  }

  function volumeBars() {
    const layer = view.layers.find((item) => item.kind === "volume_bars" && item.props && item.props.bars);
    return layer && layer.props.bars;
  }

  function dataAt(clientX, clientY) {
    const rect = view.root.getBoundingClientRect();
    const sx = clientX - rect.left;
    const sy = clientY - rect.top;
    const p = view.plot;
    const fx = Math.max(0, Math.min(1, (sx - p.x) / p.w));
    const fy = Math.max(0, Math.min(1, (sy - p.y) / p.h));
    return {
      x: view.view.x0 + fx * (view.view.x1 - view.view.x0),
      y: view.view.y1 - fy * (view.view.y1 - view.view.y0),
    };
  }

  function nearestIndex(x) {
    const cpu = candleCpu();
    if (!cpu || !cpu.x.length) return -1;
    let lo = 0;
    let hi = cpu.x.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (cpu.x[mid] < x) lo = mid + 1;
      else hi = mid;
    }
    if (lo > 0 && Math.abs(cpu.x[lo - 1] - x) <= Math.abs(cpu.x[lo] - x)) lo -= 1;
    return lo;
  }

  function dx() {
    const cpu = candleCpu();
    return cpu && Number.isFinite(cpu.dxMed) ? cpu.dxMed : (view.view.x1 - view.view.x0) / 80;
  }

  function nextId(prefix) {
    const id = `edit-${prefix}-${counter}`;
    counter += 1;
    return id;
  }

  function addLayer(layer) {
    view.layers = [...view.layers, layer];
    customIds.add(layer.id);
    renderLayerList();
    view.draw();
    status.textContent = `${labelFor(layer.kind)} added`;
  }

  function removeLayer(id) {
    view.layers = view.layers.filter((layer) => layer.id !== id);
    customIds.delete(id);
    renderLayerList();
    view.draw();
    status.textContent = "Layer removed";
  }

  function labelFor(kind) {
    return {
      position: "Position",
      anchored_vwap: "Anchored VWAP",
      fixed_range_volume_profile: "Fixed profile",
      anchored_volume_profile: "Anchored profile",
      position_forecast: "Forecast",
      sector: "Sector",
      bars_pattern: "Bars pattern",
      ghost_feed: "Ghost feed",
      editor_line: "Moving average",
      editor_bollinger: "Bollinger bands",
      volume_bars: "Volume",
      moving_average: "Moving average",
      bollinger_bands: "Bollinger bands",
      vwap: "VWAP",
    }[kind] || kind;
  }

  function renderLayerList() {
    layerList.replaceChildren();
    const visible = view.layers.filter((layer) => layer.kind !== "volume_bars" || !customIds.has(layer.id));
    for (const layer of visible) {
      const row = document.createElement("div");
      row.className = "editor-layer-row";
      const name = document.createElement("span");
      name.textContent = layer.id || labelFor(layer.kind);
      row.append(name);
      if (layer.id && customIds.has(layer.id)) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Remove";
        button.addEventListener("click", () => removeLayer(layer.id));
        row.append(button);
      }
      layerList.append(row);
    }
  }

  function drawLineSeries(chart, ctx, series, color, width) {
    if (!series || !Array.isArray(series.x) || !Array.isArray(series.y)) return;
    ctx.save();
    ctx.strokeStyle = color || "#2962ff";
    ctx.lineWidth = width || 1.5;
    ctx.beginPath();
    let started = false;
    const n = Math.min(series.x.length, series.y.length);
    for (let i = 0; i < n; i++) {
      const x = Number(series.x[i]);
      const y = Number(series.y[i]);
      if (!Number.isFinite(x) || !Number.isFinite(y)) {
        started = false;
        continue;
      }
      const sx = chart._dataToScreenX(x);
      const sy = chart._dataToScreenY(y);
      if (started) ctx.lineTo(sx, sy);
      else {
        ctx.moveTo(sx, sy);
        started = true;
      }
    }
    ctx.stroke();
    ctx.restore();
  }

  function movingAverageSeries(windowSize) {
    const cpu = candleCpu();
    if (!cpu) return { x: [], y: [] };
    const x = Array.from(cpu.x);
    const y = new Array(cpu.c.length).fill(null);
    let acc = 0;
    for (let i = 0; i < cpu.c.length; i++) {
      acc += cpu.c[i];
      if (i >= windowSize) acc -= cpu.c[i - windowSize];
      if (i >= windowSize - 1) y[i] = acc / windowSize;
    }
    return { x, y };
  }

  function bollingerSeries(windowSize, deviations) {
    const cpu = candleCpu();
    if (!cpu) return { x: [], middle: [], upper: [], lower: [] };
    const x = Array.from(cpu.x);
    const middle = new Array(cpu.c.length).fill(null);
    const upper = new Array(cpu.c.length).fill(null);
    const lower = new Array(cpu.c.length).fill(null);
    for (let i = windowSize - 1; i < cpu.c.length; i++) {
      let sum = 0;
      for (let j = i - windowSize + 1; j <= i; j++) sum += cpu.c[j];
      const avg = sum / windowSize;
      let variance = 0;
      for (let j = i - windowSize + 1; j <= i; j++) variance += (cpu.c[j] - avg) ** 2;
      const std = Math.sqrt(variance / windowSize);
      middle[i] = avg;
      upper[i] = avg + deviations * std;
      lower[i] = avg - deviations * std;
    }
    return { x, middle, upper, lower };
  }

  function anchoredVwapSeries(anchorX) {
    const cpu = candleCpu();
    const bars = volumeBars();
    const start = nearestIndex(anchorX);
    if (!cpu || !bars || start < 0) return { x: [], y: [] };
    const x = [];
    const y = [];
    let pv = 0;
    let volSum = 0;
    for (let i = start; i < cpu.x.length; i++) {
      const vol = Number(bars.volume[i] || 0);
      const typical = (cpu.h[i] + cpu.l[i] + cpu.c[i]) / 3;
      if (Number.isFinite(vol) && vol > 0) {
        pv += typical * vol;
        volSum += vol;
      }
      x.push(cpu.x[i]);
      y.push(volSum > 0 ? pv / volSum : null);
    }
    return { x, y };
  }

  function volumeProfile(startX, endX, rows) {
    const cpu = candleCpu();
    const bars = volumeBars();
    if (!cpu || !bars) return null;
    const loX = Math.min(startX, endX);
    const hiX = Math.max(startX, endX);
    const idxs = [];
    let lowEdge = Infinity;
    let highEdge = -Infinity;
    for (let i = 0; i < cpu.x.length; i++) {
      if (cpu.x[i] < loX || cpu.x[i] > hiX) continue;
      idxs.push(i);
      lowEdge = Math.min(lowEdge, cpu.l[i]);
      highEdge = Math.max(highEdge, cpu.h[i]);
    }
    if (!idxs.length || !Number.isFinite(lowEdge) || !Number.isFinite(highEdge)) return null;
    if (lowEdge === highEdge) {
      lowEdge -= 1;
      highEdge += 1;
    }
    const rowCount = Math.max(8, rows || 56);
    const step = (highEdge - lowEdge) / rowCount;
    const total = new Array(rowCount).fill(0);
    const up = new Array(rowCount).fill(0);
    const down = new Array(rowCount).fill(0);
    for (const i of idxs) {
      const barLow = Math.min(cpu.l[i], cpu.h[i]);
      const barHigh = Math.max(cpu.l[i], cpu.h[i]);
      const span = Math.max(barHigh - barLow, 1e-9);
      const vol = Number(bars.volume[i] || 0);
      const first = Math.max(0, Math.min(rowCount - 1, Math.floor((barLow - lowEdge) / step)));
      const last = Math.max(0, Math.min(rowCount - 1, Math.floor((barHigh - lowEdge) / step)));
      for (let r = first; r <= last; r++) {
        const rowLow = lowEdge + r * step;
        const rowHigh = rowLow + step;
        const overlap = Math.max(0, Math.min(barHigh, rowHigh) - Math.max(barLow, rowLow));
        if (overlap <= 0) continue;
        const share = vol * overlap / span;
        total[r] += share;
        if (cpu.c[i] >= cpu.o[i]) up[r] += share;
        else down[r] += share;
      }
    }
    const maxTotal = Math.max(...total, 0);
    const pocIndex = total.indexOf(maxTotal);
    return {
      price_low: total.map((_, i) => lowEdge + i * step),
      price_high: total.map((_, i) => lowEdge + (i + 1) * step),
      price_mid: total.map((_, i) => lowEdge + (i + 0.5) * step),
      total,
      up,
      down,
      delta: total.map((_, i) => up[i] - down[i]),
      value_area: total.map((v) => v >= maxTotal * 0.34),
      poc_index: pocIndex,
      max_total: maxTotal,
      rows: rowCount,
    };
  }

  function ghostFeed(anchor, bars) {
    const cpu = candleCpu();
    const start = nearestIndex(anchor.x);
    if (!cpu || start < 0) return null;
    const out = { x: [], open: [], high: [], low: [], close: [] };
    let lastClose = anchor.y;
    const step = dx();
    for (let i = 0; i < bars; i++) {
      const drift = 0.42 * i + Math.sin(i * 0.75) * 1.4;
      const open = lastClose;
      const close = anchor.y + drift + (i % 3 - 1) * 0.9;
      const high = Math.max(open, close) + 2.2 + (i % 4) * 0.35;
      const low = Math.min(open, close) - 1.8 - (i % 5) * 0.25;
      out.x.push(anchor.x + step * (i + 1));
      out.open.push(open);
      out.high.push(high);
      out.low.push(low);
      out.close.push(close);
      lastClose = close;
    }
    return out;
  }

  function makeLayer(tool, point) {
    const span = dx();
    const id = nextId(tool.replace(/_/g, "-"));
    const candle = candleCpu();
    const idx = nearestIndex(point.x);
    const snapX = idx >= 0 && candle ? candle.x[idx] : point.x;
    const snapY = idx >= 0 && candle ? candle.c[idx] : point.y;
    const anchor = { x: snapX, y: point.y };
    if (tool === "long_position") {
      const entry = Math.max(point.y, 1);
      return {
        role: "drawing",
        kind: "position",
        id,
        source: "price",
        side: "long",
        anchors: { entry: { x: snapX, y: entry }, stop: { y: entry * 0.96 }, target: { y: entry * 1.08 }, end: { x: snapX + span * 28 } },
        metrics: { risk_reward: 2 },
        style: { target_color: "#22ab94", stop_color: "#f23645", line_color: "#111827" },
      };
    }
    if (tool === "short_position") {
      const entry = Math.max(point.y, 1);
      return {
        role: "drawing",
        kind: "position",
        id,
        source: "price",
        side: "short",
        anchors: { entry: { x: snapX, y: entry }, stop: { y: entry * 1.06 }, target: { y: entry * 0.92 }, end: { x: snapX + span * 28 } },
        metrics: { risk_reward: 1.33 },
        style: { target_color: "#22ab94", stop_color: "#f23645", line_color: "#111827" },
      };
    }
    if (tool === "anchored_vwap") {
      return {
        role: "study",
        kind: "anchored_vwap",
        id,
        source: "price",
        anchors: { anchor },
        props: { price: "hlc3", bands: [], series: anchoredVwapSeries(snapX) },
        style: { color: "#f59e0b", width: 1.5 },
      };
    }
    if (tool === "anchored_volume_profile") {
      const profile = volumeProfile(snapX, view.view.x1, 56);
      return {
        role: "study",
        kind: "anchored_volume_profile",
        id,
        source: "price",
        anchors: { anchor },
        props: { rows: 56, volume: "up_down", value_area: 0.7, profile },
        style: { color: "#667085", up_color: "#22ab94", down_color: "#f23645", poc_color: "#f59e0b" },
      };
    }
    if (tool === "fixed_range_volume_profile") {
      const start = snapX - span * 24;
      const end = snapX + span * 24;
      const profile = volumeProfile(start, end, 56);
      return {
        role: "study",
        kind: "fixed_range_volume_profile",
        id,
        source: "price",
        anchors: { start: { x: start, y: point.y }, end: { x: end, y: point.y } },
        props: { rows: 56, volume: "up_down", value_area: 0.7, profile },
        style: { color: "#667085", up_color: "#22ab94", down_color: "#f23645", poc_color: "#f59e0b" },
      };
    }
    if (tool === "position_forecast") {
      return {
        role: "drawing",
        kind: "position_forecast",
        id,
        source: "price",
        anchors: { start: { x: snapX, y: snapY }, target: { x: snapX + span * 22, y: point.y } },
        style: { color: "#2563eb" },
      };
    }
    if (tool === "sector") {
      return {
        role: "drawing",
        kind: "sector",
        id,
        source: "price",
        anchors: { origin: { x: snapX, y: snapY }, horizon: { x: snapX + span * 28 }, target: { x: snapX + span * 28, y: point.y } },
        style: { color: "#7c3aed" },
      };
    }
    if (tool === "bars_pattern") {
      const start = Math.max(0, idx - 28);
      const end = Math.max(start + 4, idx - 4);
      const pattern = candle ? {
        x: Array.from(candle.x.slice(start, end)).map((x, i) => snapX + span * (i + 1)),
        open: Array.from(candle.o.slice(start, end)),
        high: Array.from(candle.h.slice(start, end)),
        low: Array.from(candle.l.slice(start, end)),
        close: Array.from(candle.c.slice(start, end)),
      } : null;
      return {
        role: "drawing",
        kind: "bars_pattern",
        id,
        source: "price",
        anchors: { start: { bar: start }, end: { bar: end }, destination: { x: snapX, y: point.y } },
        props: { mode: "candlestick", pattern },
        style: { color: "#667085", opacity: 0.74 },
      };
    }
    if (tool === "ghost_feed") {
      return {
        role: "drawing",
        kind: "ghost_feed",
        id,
        source: "price",
        anchors: { anchor: { x: snapX, y: point.y } },
        props: { bars: 24, direction: "up", feed: ghostFeed({ x: snapX, y: point.y }, 24) },
        style: { color: "#475467", opacity: 0.44 },
      };
    }
    if (tool === "moving_average") {
      return {
        role: "study",
        kind: "editor_line",
        id,
        source: "price",
        props: { series: movingAverageSeries(20) },
        style: { color: "#2563eb", width: 1.4 },
      };
    }
    if (tool === "bollinger_bands") {
      return {
        role: "study",
        kind: "editor_bollinger",
        id,
        source: "price",
        props: { series: bollingerSeries(20, 2) },
        style: { color: "#6d5dfc", band_color: "#7b61ff" },
      };
    }
    return null;
  }

  function addTool(tool, point) {
    const layer = makeLayer(tool, point);
    if (!layer) {
      status.textContent = "No layer added";
      return;
    }
    addLayer(layer);
  }

  palette.addEventListener("dragstart", (event) => {
    const tool = event.target.closest("[data-tool]")?.dataset.tool;
    if (!tool) return;
    event.dataTransfer.setData("text/plain", tool);
    event.dataTransfer.effectAllowed = "copy";
  });

  palette.addEventListener("click", (event) => {
    if (pointerDrag && pointerDrag.suppressClick) {
      pointerDrag = null;
      return;
    }
    const item = event.target.closest("[data-tool]");
    if (!item) return;
    activeTool = item.dataset.tool;
    for (const el of palette.querySelectorAll("[data-tool]")) el.classList.toggle("active", el === item);
    status.textContent = item.textContent;
  });

  palette.addEventListener("pointerdown", (event) => {
    const item = event.target.closest("[data-tool]");
    if (!item || event.button !== 0) return;
    event.preventDefault();
    const ghost = item.cloneNode(true);
    ghost.className = "editor-drag-ghost";
    document.body.append(ghost);
    pointerDrag = {
      tool: item.dataset.tool,
      ghost,
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
      suppressClick: false,
    };
    moveGhost(event.clientX, event.clientY);
    item.setPointerCapture?.(event.pointerId);
  });

  document.addEventListener("pointermove", (event) => {
    if (!pointerDrag) return;
    const dist = Math.hypot(event.clientX - pointerDrag.startX, event.clientY - pointerDrag.startY);
    pointerDrag.moved = pointerDrag.moved || dist > 4;
    if (pointerDrag.moved) {
      event.preventDefault();
      frame.classList.add("drag-over");
      moveGhost(event.clientX, event.clientY);
    }
  });

  document.addEventListener("pointerup", (event) => {
    if (!pointerDrag) return;
    const drag = pointerDrag;
    frame.classList.remove("drag-over");
    drag.ghost.remove();
    const target = document.elementFromPoint(event.clientX, event.clientY);
    const overChart = target && frame.contains(target);
    if (drag.moved && overChart) {
      drag.suppressClick = true;
      addTool(drag.tool, dataAt(event.clientX, event.clientY));
    }
    pointerDrag = drag.suppressClick ? drag : null;
  });

  function moveGhost(x, y) {
    if (!pointerDrag || !pointerDrag.ghost) return;
    pointerDrag.ghost.style.transform = `translate(${x + 10}px, ${y + 10}px)`;
  }

  frame.addEventListener("dragover", (event) => {
    event.preventDefault();
    frame.classList.add("drag-over");
  });

  frame.addEventListener("dragleave", () => frame.classList.remove("drag-over"));

  frame.addEventListener("drop", (event) => {
    event.preventDefault();
    frame.classList.remove("drag-over");
    const tool = event.dataTransfer.getData("text/plain");
    if (!tool) return;
    addTool(tool, dataAt(event.clientX, event.clientY));
  });

  view.canvas.addEventListener("click", (event) => {
    if (!activeTool) return;
    addTool(activeTool, dataAt(event.clientX, event.clientY));
  });

  clearButton.addEventListener("click", () => {
    view.layers = view.layers.filter((layer) => !customIds.has(layer.id));
    customIds.clear();
    renderLayerList();
    view.draw();
    status.textContent = "Cleared";
  });

  renderLayerList();
  return { addTool, removeLayer };
}
"""


EDITOR_STYLE = r"""
html,body{margin:0;width:100%;height:100%;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,sans-serif;background:#eef2f7;color:#101828;}
button{font:inherit;}
.editor-shell{height:100vh;min-height:700px;display:grid;grid-template-columns:280px minmax(0,1fr);gap:14px;padding:14px;box-sizing:border-box;}
.editor-sidebar{background:#ffffff;border:1px solid #d7dee8;border-radius:8px;display:flex;flex-direction:column;min-height:0;overflow:hidden;}
.editor-sidebar-header{padding:14px 14px 10px;border-bottom:1px solid #e4e9f0;}
.editor-sidebar-header h2{margin:0;font-size:16px;line-height:1.2;}
.editor-status{margin-top:8px;min-height:18px;color:#667085;font-size:12px;}
.editor-palette{padding:12px;display:grid;grid-template-columns:1fr;gap:8px;border-bottom:1px solid #e4e9f0;}
.editor-tool{height:34px;border:1px solid #cfd8e3;background:#f8fafc;color:#101828;border-radius:6px;display:flex;align-items:center;justify-content:space-between;padding:0 10px;cursor:grab;font-weight:600;font-size:13px;}
.editor-tool:after{content:"+";color:#2563eb;font-weight:800;}
.editor-tool.active,.editor-tool:focus{border-color:#2563eb;background:#eff6ff;outline:none;}
.editor-drag-ghost{position:fixed;left:0;top:0;z-index:9999;width:210px;height:34px;pointer-events:none;border:1px solid #2563eb;background:#eff6ff;color:#101828;border-radius:6px;display:flex;align-items:center;justify-content:space-between;padding:0 10px;box-shadow:0 8px 22px rgba(16,24,40,.18);font-weight:700;font-size:13px;}
.editor-drag-ghost:after{content:"+";color:#2563eb;font-weight:800;}
.editor-layer-panel{padding:12px;min-height:0;overflow:auto;}
.editor-layer-panel h3{margin:0 0 10px;font-size:13px;color:#344054;}
.editor-layer-list{display:grid;gap:7px;}
.editor-layer-row{min-height:30px;display:flex;align-items:center;justify-content:space-between;gap:8px;border:1px solid #e4e9f0;background:#fbfcfe;border-radius:6px;padding:5px 7px;font-size:12px;}
.editor-layer-row span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.editor-layer-row button,.editor-clear{border:1px solid #d0d5dd;background:#fff;border-radius:5px;color:#344054;padding:3px 7px;font-size:12px;cursor:pointer;}
.editor-clear{margin-top:10px;width:100%;height:30px;}
.editor-workspace{min-width:0;display:flex;flex-direction:column;}
.editor-chart-frame{position:relative;flex:1;min-height:670px;border:1px solid #d7dee8;border-radius:8px;background:#fff;overflow:hidden;}
.editor-chart-frame.drag-over{outline:2px solid #2563eb;outline-offset:-4px;}
#chart{width:100%;height:100%;}
@media (max-width:900px){
  .editor-shell{grid-template-columns:1fr;height:auto;min-height:100vh;}
  .editor-palette{grid-template-columns:repeat(2,minmax(0,1fr));}
  .editor-chart-frame{min-height:620px;}
}
"""


EDITOR_BODY = r"""
<div class="editor-shell">
  <aside class="editor-sidebar">
    <div class="editor-sidebar-header">
      <h2>Finance Elements</h2>
      <div id="editor-status" class="editor-status">Ready</div>
    </div>
    <div id="editor-palette" class="editor-palette">
      <button class="editor-tool" type="button" draggable="true" data-tool="long_position">Long position</button>
      <button class="editor-tool" type="button" draggable="true" data-tool="short_position">Short position</button>
      <button class="editor-tool" type="button" draggable="true" data-tool="anchored_vwap">Anchored VWAP</button>
      <button class="editor-tool" type="button" draggable="true" data-tool="anchored_volume_profile">Anchored profile</button>
      <button class="editor-tool" type="button" draggable="true" data-tool="fixed_range_volume_profile">Fixed profile</button>
      <button class="editor-tool" type="button" draggable="true" data-tool="position_forecast">Forecast</button>
      <button class="editor-tool" type="button" draggable="true" data-tool="sector">Sector</button>
      <button class="editor-tool" type="button" draggable="true" data-tool="bars_pattern">Bars pattern</button>
      <button class="editor-tool" type="button" draggable="true" data-tool="ghost_feed">Ghost feed</button>
      <button class="editor-tool" type="button" draggable="true" data-tool="moving_average">MA 20</button>
      <button class="editor-tool" type="button" draggable="true" data-tool="bollinger_bands">Bollinger</button>
    </div>
    <div class="editor-layer-panel">
      <h3>Layers</h3>
      <div id="editor-layer-list" class="editor-layer-list"></div>
      <button id="editor-clear" class="editor-clear" type="button">Clear added</button>
    </div>
  </aside>
  <main class="editor-workspace">
    <div id="editor-chart-frame" class="editor-chart-frame">
      <div id="chart"></div>
    </div>
  </main>
</div>
"""


def candlestick_editor_html() -> str:
    html = candlestick_demo().to_html()
    html = html.replace(
        "html,body{margin:0;width:100%;min-height:100%;font-family:system-ui,sans-serif;background:#fff;}\n"
        "#chart{width:100%;}",
        EDITOR_STYLE.strip(),
    )
    html = html.replace('<div id="chart"></div>', EDITOR_BODY.strip())
    html = html.replace(
        "<script>\n  const spec = ",
        f"<script>{EDITOR_JS}</script>\n<script>\n  const spec = ",
    )
    html = html.replace(
        'fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'const view = fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);\n'
        "  window.fastchartsFinanceEditor = createFinanceLayerEditor(view);",
    )
    return html


def main() -> None:
    live_html = live_drilldown_html()
    write_live_drilldown_chart("live_drilldown_100m.html", live_html)
    write_live_drilldown_chart("live_drilldown_10m.html", live_html)
    write_custom_chrome_chart()
    write_chart(business_overview_demo(), "business_overview.html")
    write_chart(retention_cohort_demo(), "retention_cohort.html")
    write_live_drilldown_chart("live_drilldown_1b.html", billion_drilldown_html())
    write_chart(candlestick_demo(), "candlestick.html")
    write_html_asset("candlestick_editor.html", candlestick_editor_html())
    write_chart(line_walk(), "line_walk.html")
    write_chart(area_demo(), "area.html")
    write_chart(colored_scatter(), "colored_scatter.html")
    write_plotly_chart("plotly_colored_scatter.html")
    write_chart(density_scatter(), "density_scatter.html")
    write_chart(histogram_demo(), "histogram.html")
    write_chart(bar_column_demo(), "bar_column.html")
    write_chart(stacked_bar_demo(), "stacked_bar.html")
    write_chart(horizontal_bar_demo(), "horizontal_bar.html")
    write_chart(heatmap_demo(), "heatmap.html")
    write_chart(composed_layers_demo(), "composed_layers.html")
    write_annotated_heatmap_chart()
    write_chart(axes_scales_demo(), "axes_scales.html")
    write_chart(interaction_basics_demo(), "interaction_basics.html")


if __name__ == "__main__":
    main()
