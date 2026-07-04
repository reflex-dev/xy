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
    colored_scatter_data,
    colored_scatter_figure,
    live_drilldown_html,
)

from fastcharts import Figure  # noqa: E402


def write_chart(fig: Figure, name: str) -> None:
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


def main() -> None:
    live_html = live_drilldown_html()
    write_live_drilldown_chart("live_drilldown_100m.html", live_html)
    write_live_drilldown_chart("live_drilldown_10m.html", live_html)
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


if __name__ == "__main__":
    main()
