"""Native zero-inclusive long-tail axis contracts."""

from __future__ import annotations

import numpy as np
import pytest

import xy
from xy import _svg
from xy._figure import Figure


def test_symlog_component_emits_original_domain_and_constant() -> None:
    chart = xy.chart(
        xy.scatter(x=[0.0, 1.0, 1_000_000.0], y=[-10.0, 0.0, 10.0]),
        xy.x_axis(type_="symlog", constant=1_000.0),
    )
    spec, _ = chart.figure().build_payload()

    assert spec["x_axis"]["scale"] == "symlog"
    assert spec["x_axis"]["constant"] == 1_000.0
    assert spec["x_axis"]["range"][0] <= 0.0
    assert spec["x_axis"]["range"][1] > 1_000_000.0


def test_symlog_accepts_zero_and_negative_explicit_domain() -> None:
    fig = Figure().scatter([-100.0, 0.0, 100.0], [0.0, 1.0, 2.0])
    fig.set_axis("x", type_="symlog", constant=10.0, domain=(-100.0, 100.0))
    spec, _ = fig.build_payload()
    assert spec["x_axis"]["range"] == [-100.0, 100.0]


@pytest.mark.parametrize("constant", [0, -1, float("inf")])
def test_symlog_rejects_invalid_constant(constant: float) -> None:
    with pytest.raises(ValueError, match="constant"):
        xy.x_axis(type_="symlog", constant=constant)


def test_constant_is_rejected_for_other_scales() -> None:
    with pytest.raises(ValueError, match="only valid"):
        xy.y_axis(type_="linear", constant=1)


def test_static_symlog_scale_is_symmetric_and_zero_preserving() -> None:
    scale = _svg._Scale(
        {"kind": "linear", "scale": "symlog", "constant": 10.0, "range": [-1_000, 1_000]},
        0,
        200,
    )
    pixels = scale(np.array([-1_000.0, 0.0, 1_000.0]))
    assert pixels == pytest.approx([0.0, 100.0, 200.0])
    assert not scale.affine


def _decoded_column(spec: dict, blob: bytes, col_index: int) -> np.ndarray:
    meta = spec["columns"][col_index]
    raw = np.frombuffer(blob, dtype=np.float32, count=meta["len"], offset=meta["byte_offset"])
    return raw.astype(np.float64) / (meta.get("scale") or 1.0) + meta.get("offset", 0.0)


def test_symlog_geometry_encodes_with_zero_offset() -> None:
    # With x=[0, 1, 1e12] a midpoint offset (~5e11) makes 0 and 1 encode to
    # the same f32 word, but symlog exists to keep them a visible distance
    # apart. Log-family axes pin the encode offset to 0.0 (§4) so the f32
    # error stays *relative* — bounded on screen at every magnitude.
    fig = Figure().scatter([0.0, 1.0, 1e12], [0.0, 1.0, 2.0])
    fig.set_axis("x", type_="symlog", constant=1.0)
    spec, blob = fig.build_payload()
    x_meta = spec["columns"][spec["traces"][0]["x"]]
    assert x_meta["offset"] == 0.0
    decoded = _decoded_column(spec, blob, spec["traces"][0]["x"])
    assert decoded[0] == 0.0
    assert decoded[1] == 1.0


def test_log_geometry_also_pins_zero_offset() -> None:
    fig = Figure().scatter([1e-3, 1.0, 1e12], [0.0, 1.0, 2.0])
    fig.set_axis("x", type_="log")
    spec, _ = fig.build_payload()
    x_meta = spec["columns"][spec["traces"][0]["x"]]
    assert x_meta["offset"] == 0.0


def _occupied_grid_columns(spec: dict, blob: bytes, density: dict) -> np.ndarray:
    meta = spec["columns"][density["buf"]]
    grid = np.frombuffer(blob, dtype=np.uint8, count=meta["len"], offset=meta["byte_offset"])
    return np.flatnonzero(grid.reshape(density["h"], density["w"]).sum(axis=0))


def test_symlog_density_grid_bins_in_scale_coordinates() -> None:
    # Clusters at x=1 and x=1000 are ~30% of the axis apart under symlog
    # (constant=1, domain to 1e9) but land in the same raw-space grid cell.
    # Density grids bin in scale coordinates (§28), so they must occupy
    # clearly separated grid columns.
    n = 400
    x = np.concatenate([np.full(n, 1.0), np.full(n, 1000.0), [1e9]])
    y = np.linspace(0.0, 1.0, len(x))
    fig = Figure().scatter(x, y)
    fig.traces[0].force_density = True
    fig.set_axis("x", type_="symlog", constant=1.0)
    spec, blob = fig.build_payload()
    density = spec["traces"][0]["density"]
    occupied = _occupied_grid_columns(spec, blob, density)

    lo, hi = density["x_range"]
    coord = lambda v: np.sign(v) * np.log1p(np.abs(v))  # noqa: E731
    span = coord(hi) - coord(lo)
    expected_1 = int((coord(1.0) - coord(lo)) / span * density["w"])
    expected_1000 = int((coord(1000.0) - coord(lo)) / span * density["w"])
    assert expected_1000 - expected_1 > 50  # far apart on screen…
    assert any(abs(c - expected_1) <= 1 for c in occupied)
    assert any(abs(c - expected_1000) <= 1 for c in occupied)


def test_symlog_density_view_rebins_in_scale_coordinates() -> None:
    n = 400
    x = np.concatenate([np.full(n, 1.0), np.full(n, 1000.0), [1e9]])
    y = np.linspace(0.0, 1.0, len(x))
    # The drill budget is the per-trace tunable (density_threshold), so no
    # module-constant monkeypatching is needed to keep this view aggregated.
    fig = Figure().scatter(x, y, density_threshold=50)
    fig.traces[0].force_density = True
    fig.set_axis("x", type_="symlog", constant=1.0)
    fig.build_payload()

    update, buffers = fig.density_view(fig.traces[0].id, -1.0, 1e9, -0.1, 1.1, 512, 256)
    trace = update["traces"][0]
    assert trace["mode"] == "density"
    density = trace["density"]
    grid = np.frombuffer(buffers[density["buf"]], dtype=np.uint8).reshape(
        density["h"], density["w"]
    )
    occupied = np.flatnonzero(grid.sum(axis=0))
    lo, hi = density["x_range"]
    coord = lambda v: np.sign(v) * np.log1p(np.abs(v))  # noqa: E731
    span = coord(hi) - coord(lo)
    expected_1 = int((coord(1.0) - coord(lo)) / span * density["w"])
    expected_1000 = int((coord(1000.0) - coord(lo)) / span * density["w"])
    assert expected_1000 - expected_1 > 4  # separated even on a shrunken grid
    assert any(abs(c - expected_1) <= 1 for c in occupied)
    assert any(abs(c - expected_1000) <= 1 for c in occupied)


def test_static_symlog_heatmap_resamples_internal_cells() -> None:
    # A 2-cell data-uniform heatmap on a 0..1000 symlog axis: the cell
    # boundary (x=500) sits ~90% of the way across the axis, so most warped
    # output cells must sample source cell 0. Affine axes never warp.
    scale = _svg._Scale(
        {"kind": "linear", "scale": "symlog", "constant": 1.0, "range": [0, 1000]}, 0, 200
    )
    idx = _svg.warp_axis_indices(scale, 0.0, 1000.0, 2)
    assert idx is not None
    boundary = int(np.searchsorted(idx, 1))
    assert boundary / len(idx) > 0.85
    linear = _svg._Scale({"kind": "linear", "range": [0, 1000]}, 0, 200)
    assert _svg.warp_axis_indices(linear, 0.0, 1000.0, 2) is None


def test_svg_symlog_heatmap_embeds_warped_image() -> None:
    import base64
    import re
    import struct

    fig = Figure().heatmap([[0.0, 1.0], [0.5, 0.75]])
    fig.set_axis("x", type_="symlog", constant=1.0)
    svg = fig.to_svg()
    match = re.search(r'href="data:image/png;base64,([^"]+)"', svg)
    assert match is not None
    png = base64.b64decode(match.group(1))
    width = struct.unpack(">I", png[16:20])[0]
    assert width > 2  # resampled beyond the 2 source columns


def test_symlog_wire_protocol_is_bumped_in_lockstep() -> None:
    # scale="symlog" changes renderer semantics; a cached pre-symlog client
    # must refuse the spec loudly instead of rendering it as linear.
    from pathlib import Path

    from xy.config import PROTOCOL_VERSION

    assert PROTOCOL_VERSION >= 5
    header = Path(__file__).resolve().parents[1] / "js" / "src" / "00_header.ts"
    assert f"PROTOCOL = {PROTOCOL_VERSION};" in header.read_text()


def test_static_symlog_ticks_include_zero_in_original_units() -> None:
    ticks, labels, _ = _svg.axis_ticks(
        {"kind": "linear", "scale": "symlog", "constant": 100.0, "range": [0, 1_000_000]},
        600,
        True,
    )
    assert ticks == labels
    assert 0.0 in ticks
    assert max(ticks) <= 1_000_000


def test_client_number_format_accepts_literal_affixes(tmp_path) -> None:
    # Issue #83's proposed API formats a symlog money axis with "$,.0f"; the
    # numeric grammar carries literal prefix/suffix text through to labels.
    import pytest

    from conftest import run_browser_probe
    from xy.export import find_chromium

    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    chart = xy.scatter_chart(
        xy.scatter(x=[0.0, 1.0], y=[0.0, 200.0]),
        xy.y_axis(domain=(0, 200), format="$.0f"),
        width=480,
        height=360,
    )
    html = chart.to_html()
    render_call = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    assert render_call in html
    probe = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    const axis = view._axis("y");
    document.body.setAttribute("data-xy-format-affix", JSON.stringify({
      label: view._axisTickText(axis, 100, 50),
    }));
  } catch (error) {
    document.body.setAttribute(
      "data-xy-format-affix-error", String((error && error.stack) || error));
  }
"""
    result = run_browser_probe(
        chromium,
        html.replace(render_call, probe),
        tmp_path / "format_affix.html",
        "data-xy-format-affix",
        label="format affix probe",
    )
    assert result["label"] == "$100"
