from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
ASSET_DIR = APP_ROOT / "assets" / "charts"

# Prefer the checkout source when running the example from this repository.
sys.path.insert(0, str(REPO_ROOT / "python"))

from fastcharts import Figure  # noqa: E402


def write_chart(fig: Figure, name: str) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSET_DIR / name
    fig.to_html(str(path))
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
    rng = np.random.default_rng(11)
    n = 60_000
    x = rng.normal(0, 1.0, n)
    y = 0.55 * x + rng.normal(0, 0.55, n)
    color = np.hypot(x, y)
    size = np.clip(np.abs(rng.normal(6, 2.5, n)), 2, 16)
    return Figure(
        title="60k colored scatter",
        x_label="feature A",
        y_label="feature B",
        width=980,
        height=430,
    ).scatter(x, y, color=color, size=size, colormap="viridis", opacity=0.72)


def density_scatter() -> Figure:
    rng = np.random.default_rng(23)
    n = 250_000
    groups = rng.integers(0, 4, n)
    centers = np.array([[-1.4, -0.9], [-0.2, 0.8], [1.0, -0.2], [1.8, 1.1]])
    noise = rng.normal(0, 0.33, (n, 2))
    pts = centers[groups] + noise
    return Figure(
        title="250k density scatter",
        x_label="x",
        y_label="y",
        width=980,
        height=430,
    ).scatter(pts[:, 0], pts[:, 1], opacity=0.9)


def main() -> None:
    write_chart(line_walk(), "line_walk.html")
    write_chart(colored_scatter(), "colored_scatter.html")
    write_chart(density_scatter(), "density_scatter.html")


if __name__ == "__main__":
    main()
