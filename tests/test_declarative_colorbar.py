"""Declarative continuous-color marks drive built-in colorbar chrome."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium


def test_heatmap_colorbar_uses_compiled_scale_and_public_chrome_options() -> None:
    chart = xy.heatmap_chart(
        xy.heatmap(
            [[-2.0, 0.0], [2.0, 4.0]],
            name="temperature",
            colormap="coolwarm",
            domain=(-3.0, 5.0),
        ),
        xy.colorbar(
            title="Temperature (°C)",
            orientation="horizontal",
            ticks=[-3, 0, 5],
            class_name="scale",
            style={"border-radius": 6},
        ),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["colorbar"] == {
        "domain": [-3.0, 5.0],
        "colormap": "coolwarm",
        "label": "Temperature (°C)",
        "orientation": "horizontal",
        "ticks": [-3.0, 0.0, 5.0],
    }
    assert spec["dom"]["class_names"]["colorbar"] == "scale"
    assert spec["dom"]["styles"]["colorbar"] == {"border-radius": 6}


def test_heatmap_colorbar_autoscales_and_uses_the_mark_name() -> None:
    chart = xy.chart(
        xy.heatmap([[0.25, 0.75], [1.25, 1.75]], name="intensity", colormap="purples"),
        xy.colorbar(),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["colorbar"] == {
        "domain": [0.25, 1.75],
        "colormap": "purples",
        "label": "intensity",
        "orientation": "vertical",
    }


def test_continuous_scatter_colorbar_uses_color_column_not_trace_name() -> None:
    data = {
        "x": [0.0, 1.0, 2.0],
        "y": [2.0, 3.0, 5.0],
        "temperature": [12.0, 18.0, 31.0],
    }
    chart = xy.scatter_chart(
        xy.scatter(
            x="x",
            y="y",
            color="temperature",
            data=data,
            name="stations",
            colormap="plasma",
            color_domain=(10.0, 35.0),
        ),
        xy.colorbar(),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["colorbar"] == {
        "domain": [10.0, 35.0],
        "colormap": "plasma",
        "label": "temperature",
        "orientation": "vertical",
    }


@pytest.mark.parametrize(
    "color",
    ["#2563eb", ["low", "medium", "high"]],
)
def test_noncontinuous_scatter_does_not_invent_a_colorbar(color) -> None:
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0, 2.0], [2.0, 3.0, 5.0], color=color),
        xy.colorbar(),
    )

    spec, _ = chart.figure().build_payload()

    assert "colorbar" not in spec


def test_density_scatter_does_not_label_the_dropped_per_row_color_channel() -> None:
    chart = xy.scatter_chart(
        xy.scatter(
            [0.0, 1.0, 2.0],
            [2.0, 3.0, 5.0],
            color=[10.0, 20.0, 30.0],
            density=True,
            colormap="plasma",
        ),
        xy.colorbar(),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["traces"][0]["tier"] == "density"
    assert spec["traces"][0]["density"]["channels_dropped"] is True
    assert "colorbar" not in spec


def test_hexbin_and_contour_colorbars_use_compiled_domains() -> None:
    x = np.array([-0.9, -0.8, -0.7, 0.1, 0.2, 0.3, 0.4])
    y = np.array([-0.8, -0.7, -0.6, 0.1, 0.2, 0.3, 0.4])
    hex_chart = xy.hexbin_chart(
        xy.hexbin(x, y, gridsize=4, mincnt=1, colormap="magma"),
        xy.colorbar(),
    )
    hex_fig = hex_chart.figure()
    hex_spec, _ = hex_fig.build_payload()
    hex_channel = hex_fig.traces[0].color_ch

    assert hex_spec["colorbar"] == {
        "domain": list(hex_channel.domain),
        "colormap": "magma",
        "label": "count",
        "orientation": "vertical",
    }

    field = np.array(
        [
            [-2.0, -1.0, 0.0],
            [-1.0, 0.0, 1.0],
            [0.0, 1.0, 2.0],
        ]
    )
    contour_chart = xy.contour_chart(
        xy.contour(
            field,
            levels=[-1.5, -0.5, 0.5, 1.5],
            filled=True,
            name="elevation",
            colormap="spectral",
        ),
        xy.colorbar(),
    )
    contour_spec, _ = contour_chart.figure().build_payload()

    assert contour_spec["colorbar"] == {
        "domain": [-1.5, 1.5],
        "colormap": "spectral",
        "label": "elevation",
        "levels": 3,
        "orientation": "vertical",
    }


def test_colorbar_uses_last_continuous_mark_and_show_false_removes_it() -> None:
    chart = xy.chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], name="field", colormap="viridis"),
        xy.scatter(
            [0.0, 1.0],
            [0.0, 1.0],
            color=[100.0, 200.0],
            name="quality",
            colormap="plasma",
        ),
        xy.colorbar(),
    )
    hidden = xy.chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], colormap="viridis"),
        xy.colorbar(show=False),
    )

    spec, _ = chart.figure().build_payload()
    hidden_spec, _ = hidden.figure().build_payload()

    assert spec["colorbar"] == {
        "domain": [100.0, 200.0],
        "colormap": "plasma",
        "label": "quality",
        "orientation": "vertical",
    }
    assert "colorbar" not in hidden_spec


def test_colorbar_rejects_invalid_public_options() -> None:
    with pytest.raises(ValueError, match="colorbar orientation"):
        xy.colorbar(orientation="diagonal")
    with pytest.raises(ValueError, match="colorbar orientation"):
        xy.colorbar(orientation=["vertical"])
    with pytest.raises(ValueError, match="colorbar ticks"):
        xy.colorbar(ticks="0, 1")
    with pytest.raises(ValueError, match="finite"):
        xy.colorbar(ticks=[0.0, np.inf])


@pytest.mark.parametrize(
    ("node", "message"),
    [
        (xy.Colorbar(show="yes"), "colorbar show"),
        (xy.Colorbar(title=42), "colorbar title"),
        (xy.Colorbar(orientation="diagonal"), "colorbar orientation"),
        (xy.Colorbar(ticks=[0.0, np.inf]), "colorbar tick"),
        (xy.Colorbar(class_name=42), "colorbar class_name"),
        (xy.Colorbar(style="color: red"), "colorbar style"),
    ],
)
def test_direct_colorbar_instance_cannot_bypass_factory_validation(node, message) -> None:
    chart = xy.heatmap_chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], colormap="viridis"),
        node,
    )

    with pytest.raises(ValueError, match=message):
        chart.figure()


def test_colorbar_uses_semantic_positional_fields_and_custom_render() -> None:
    renderer = object()
    node = xy.Colorbar(
        True,
        "Temperature",
        "horizontal",
        [0.0, 1.0],
        "scale-class",
        {"color": "red"},
        renderer,
    )

    assert node.title == "Temperature"
    assert node.orientation == "horizontal"
    assert node.ticks == [0.0, 1.0]
    assert node.class_name == "scale-class"
    assert node.style == {"color": "red"}
    assert node.render is renderer

    custom = xy.heatmap_chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], colormap="viridis"),
        node,
    )
    custom_spec, _ = custom.figure().build_payload()
    assert "colorbar" not in custom_spec


def test_declarative_colorbar_reaches_svg_export() -> None:
    svg = xy.heatmap_chart(
        xy.heatmap([[0.0, 0.5], [1.0, 1.5]], name="Intensity", colormap="purples"),
        xy.colorbar(title="Intensity & confidence", ticks=[0.0, 1.5]),
        width=520,
        height=320,
    ).to_svg()

    assert '<linearGradient id="xy-colorbar-' in svg
    assert "Intensity &amp; confidence" in svg
    assert ">0<" in svg
    assert ">1.5<" in svg


def test_svg_explicit_colorbar_ticks_preserve_authored_precision() -> None:
    svg = xy.heatmap_chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], colormap="viridis"),
        xy.colorbar(ticks=[0.123, 2.987]),
        width=520,
        height=320,
    ).to_svg()

    assert ">0.123<" in svg
    assert ">2.987<" in svg


def _browser_colorbar_probe(chromium: str, document: str, page: Path) -> dict:
    render_call = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    assert render_call in document
    probe = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    try {
      const bar = document.querySelector('[data-xy-slot="colorbar_bar"]');
      const title = document.querySelector('[data-xy-slot="colorbar_title"]');
      const ticks = [...document.querySelectorAll('[data-xy-slot="colorbar_tick"]')];
      document.body.setAttribute('data-xy-colorbar-probe', JSON.stringify({
        exists: !!bar,
        title: title && title.textContent,
        tooltip: view._colorbar && view._colorbar.title,
        gradient: bar && getComputedStyle(bar).backgroundImage,
        tickLabels: ticks.map((tick) => tick.textContent),
      }));
    } catch (err) {
      document.body.setAttribute(
        'data-xy-colorbar-probe-error',
        String((err && err.stack) || err)
      );
    }
  }));
"""
    return run_browser_probe(
        chromium,
        document.replace(render_call, probe),
        page,
        "data-xy-colorbar-probe",
        label="colorbar chrome probe",
    )


def test_declarative_colorbar_reaches_browser_chrome(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    chart = xy.heatmap_chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], name="Intensity", colormap="purples"),
        xy.colorbar(ticks=[0.123, 2.987]),
        width=480,
        height=300,
    )

    result = _browser_colorbar_probe(chromium, chart.to_html(), tmp_path / "colorbar.html")

    assert result["exists"] is True
    assert result["title"] == "Intensity"
    assert result["tooltip"] == "Intensity: 0 \u2013 3"
    assert "linear-gradient" in result["gradient"]
    assert result["tickLabels"] == ["0.123", "2.987"]
