"""Shared benchmark theme contract."""

from __future__ import annotations

from benchmarks.plot_ux import build

from xy._benchmark_theme import (
    BENCHMARK_CSS_VARIABLES,
    BENCHMARK_DARK_THEME,
    BENCHMARK_LIGHT_THEME,
    benchmark_chart_class,
    benchmark_live_theme,
)

_THEME_STYLE_KEYS = {
    "background": "background",
    "plot_background": "--chart-bg",
    "grid_color": "--chart-grid",
    "axis_color": "--chart-axis",
    "text_color": "--chart-text",
}


def test_static_benchmark_export_uses_shared_theme() -> None:
    rows = {("xy", 10_000): {"status": "ok", "visible_complete_ms": 71}}
    for color_scheme, expected_theme in (
        ("light", BENCHMARK_LIGHT_THEME),
        ("dark", BENCHMARK_DARK_THEME),
    ):
        spec, _ = (
            build(rows, [10_000], ["xy"], "time", color_scheme=color_scheme)
            .figure()
            .build_payload()
        )
        style = spec["dom"]["style"]
        assert {
            token: style[style_key] for token, style_key in _THEME_STYLE_KEYS.items()
        } == expected_theme


def test_live_benchmark_theme_derives_both_color_schemes() -> None:
    assert benchmark_live_theme() == {
        token: f"var({css_variable}, {BENCHMARK_LIGHT_THEME[token]})"
        for token, css_variable in BENCHMARK_CSS_VARIABLES.items()
    }

    classes = set(benchmark_chart_class().split())
    assert "w-full" in classes
    for token, css_variable in BENCHMARK_CSS_VARIABLES.items():
        assert f"[{css_variable}:{BENCHMARK_LIGHT_THEME[token]}]" in classes
        assert f"dark:[{css_variable}:{BENCHMARK_DARK_THEME[token]}]" in classes
