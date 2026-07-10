"""Static SVG export (_svg.py): well-formed output for every chart kind, the
screen-bounded size guarantee, styling fidelity markers, and sync guards
against the JS client tables it mirrors."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

import xy as fc
from xy._figure import Figure
from xy._svg import COLORMAP_STOPS

ROOT = Path(__file__).resolve().parents[1]


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def test_every_chart_kind_exports_wellformed_svg() -> None:
    rng = np.random.default_rng(0)
    x = np.linspace(0.0, 10.0, 50)

    figs = []
    figs.append(Figure().line(x, np.sin(x), dash="dashed", curve="smooth"))
    figs.append(
        Figure().area(x, np.abs(np.sin(x)), fill="linear-gradient(currentColor, transparent)")
    )
    figs.append(
        Figure().scatter(
            x, np.cos(x), symbol="triangle", stroke="#111", color=np.sin(x), size=np.abs(np.cos(x))
        )
    )
    figs.append(Figure().scatter(x, np.cos(x), color=np.array(["a", "b"] * 25)))
    figs.append(Figure().bar(["a", "b", "c"], [1.0, 3.0, 2.0], corner_radius=(4, 0)))
    figs.append(Figure().bar(["a", "b"], [1.0, 2.0], orientation="horizontal"))
    figs.append(Figure().histogram(rng.normal(size=500), corner_radius=2))
    figs.append(Figure().heatmap(rng.random((8, 6))))
    figs.append(Figure().scatter(rng.normal(size=200_000), rng.normal(size=200_000), density=True))
    t = np.datetime64("2024-01-01") + np.arange(50).astype("timedelta64[h]")
    figs.append(Figure().line(t, np.sin(x)))
    log_fig = Figure().scatter(x + 1, 10.0 ** np.linspace(0, 4, 50))
    log_fig.set_axis("y", type_="log")
    figs.append(log_fig)

    for fig in figs:
        svg = fig.to_svg()
        root = _parse(svg)
        assert root.tag.endswith("svg")
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg


def test_svg_stays_screen_bounded_for_large_lines() -> None:
    n = 2_000_000
    y = np.cumsum(np.random.default_rng(1).normal(size=n))
    fig = Figure(width=950, height=420, title="big")
    fig.line(np.arange(n, dtype=np.float64), y, name="walk")
    svg = fig.to_svg()
    # M4 keeps ≤4 points per pixel column: 2M source points must not leak into
    # the file. Generous ceiling: ~4*950 points at ~15 bytes each + chrome.
    assert len(svg) < 300_000, f"SVG not screen-bounded: {len(svg)} bytes"
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["n_points"] == n  # source size recorded (§28)


def test_svg_styling_fidelity_markers() -> None:
    x = np.linspace(0.0, 5.0, 12)
    fig = Figure(title="styled")
    fig.area(
        x,
        np.abs(np.sin(x)) + 0.1,
        curve="smooth",
        dash="dotted",
        fill="linear-gradient(currentColor, transparent)",
        name="a",
    )
    fig.bar(
        ["a", "b"],
        [1.0, 2.0],
        corner_radius=(6, 0),
        stroke="#123456",
        stroke_width=2,
        fill="linear-gradient(to top, #1e40af, #93c5fd)",
    )
    fig.scatter([1.0], [0.5], symbol="cross", stroke="#ff0000")
    svg = fig.to_svg()
    assert "linearGradient" in svg  # gradient fills -> defs
    assert "stroke-dasharray" in svg  # dashes -> native SVG dashes
    assert " C " in svg  # smooth curve -> cubic Béziers, not polyline
    assert re.search(r'<path d="M [^"]*A [^"]*A ', svg)  # rounded corners -> arc path
    assert 'stroke="#123456"' in svg  # bar border
    assert 'stroke="#ff0000"' in svg  # point border
    assert "<title" not in svg  # no stray elements; title is <text>
    assert ">styled<" in svg


def test_svg_axes_chrome_and_hiding() -> None:
    fig = Figure(title="t", x_label="xx", y_label="yy")
    fig.line([0.0, 1.0], [0.0, 1.0], name="n")
    svg = fig.to_svg()
    for text in (">t<", ">xx<", ">yy<", ">n<"):
        assert text in svg

    spark = Figure(padding=0)
    spark.line([0.0, 1.0], [0.0, 1.0])
    for ax in ("x", "y"):
        spark.set_axis(ax, tick_label_strategy="none")
    sparse = spark.to_svg()
    assert 'text-anchor="end"' not in sparse  # no y tick labels
    assert 'text-anchor="middle">' not in sparse  # no x tick labels / titles


def test_svg_write_and_dimension_override(tmp_path: Path) -> None:
    fig = Figure(width="100%", height="100%")
    fig.line([0.0, 1.0], [0.0, 1.0])
    out = tmp_path / "chart.svg"
    svg = fig.to_svg(out, width=640, height=360)
    assert out.read_text(encoding="utf-8") == svg
    root = _parse(svg)
    assert root.get("width") == "640"
    assert root.get("height") == "360"


def test_composition_chart_to_svg_parity() -> None:
    chart = fc.line_chart(
        fc.line(x=[0.0, 1.0], y=[1.0, 2.0], name="s"),
        fc.x_axis(label="time"),
        title="comp",
    )
    svg = chart.to_svg(width=500, height=300)
    _parse(svg)
    assert ">comp<" in svg
    assert ">time<" in svg


def test_density_and_heatmap_embed_png_rasters() -> None:
    rng = np.random.default_rng(2)
    fig = Figure()
    fig.scatter(rng.normal(size=200_000), rng.normal(size=200_000), density=True)
    svg = fig.to_svg()
    assert "data:image/png;base64," in svg  # density grid -> embedded raster
    assert svg.count("<image") == 1

    fig2 = Figure().heatmap(rng.random((16, 12)))
    svg2 = fig2.to_svg()
    assert "data:image/png;base64," in svg2


def test_colormap_stops_stay_in_sync_with_js_client() -> None:
    """The Python tables are ports of 10_colormaps.js — every stop must appear
    verbatim in the JS source, and the map names must match."""
    js = (ROOT / "js" / "src" / "10_colormaps.js").read_text(encoding="utf-8")
    body = js.split("COLORMAP_STOPS = {", 1)[1].split("};", 1)[0]
    js_names = set(re.findall(r"^\s*(\w+): \[", body, re.MULTILINE))
    assert js_names == set(COLORMAP_STOPS), "colormap names diverged from 10_colormaps.js"
    for name, stops in COLORMAP_STOPS.items():
        for r, g, b in stops:
            assert f"[{r}, {g}, {b}]" in body, (
                f"{name} stop ({r},{g},{b}) missing in 10_colormaps.js"
            )
