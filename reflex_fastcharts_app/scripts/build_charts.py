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
    LIVE_SCATTER_POINTS,
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


def main() -> None:
    live_html = live_drilldown_html()
    write_live_drilldown_chart("live_drilldown_100m.html", live_html)
    write_live_drilldown_chart("live_drilldown_10m.html", live_html)
    write_chart(line_walk(), "line_walk.html")
    write_chart(colored_scatter(), "colored_scatter.html")
    write_plotly_chart("plotly_colored_scatter.html")
    write_chart(density_scatter(), "density_scatter.html")


if __name__ == "__main__":
    main()
