"""Shared visual tokens for static and interactive benchmark charts.

This is an internal module for the repository's benchmark tooling and docs app,
not part of the public ``xy`` API.
"""

from __future__ import annotations

BENCHMARK_LIGHT_THEME = {
    "background": "#ffffff",
    "plot_background": "#fcfcfd",
    "grid_color": "#e8e8ec",
    "axis_color": "#d9d9e0",
    "text_color": "#60646c",
}
BENCHMARK_DARK_THEME = {
    "background": "#09090b",
    "plot_background": "#111113",
    "grid_color": "#27272a",
    "axis_color": "#3f3f46",
    "text_color": "#d4d4d8",
}
BENCHMARK_CSS_VARIABLES = {
    "background": "--benchmark-bg",
    "plot_background": "--benchmark-plot",
    "grid_color": "--benchmark-grid",
    "axis_color": "--benchmark-axis",
    "text_color": "--benchmark-text",
}


def benchmark_live_theme() -> dict[str, str]:
    """Return theme values backed by the docs app's light/dark CSS variables."""
    return {
        token: f"var({css_variable}, {BENCHMARK_LIGHT_THEME[token]})"
        for token, css_variable in BENCHMARK_CSS_VARIABLES.items()
    }


def benchmark_chart_class() -> str:
    """Return the docs class that assigns both color schemes to the CSS variables."""
    light = (
        f"[{css_variable}:{BENCHMARK_LIGHT_THEME[token]}]"
        for token, css_variable in BENCHMARK_CSS_VARIABLES.items()
    )
    dark = (
        f"dark:[{css_variable}:{BENCHMARK_DARK_THEME[token]}]"
        for token, css_variable in BENCHMARK_CSS_VARIABLES.items()
    )
    return " ".join(("w-full", *light, *dark))
