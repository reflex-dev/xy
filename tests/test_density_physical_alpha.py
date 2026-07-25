"""Mean-color density textures composite like the points they aggregate
(LOD doc §2 rule 1).

A channel-bearing cell uploads at alpha `1 − (1 − ā)^count` — the physical
compositing of k overplotted points of mean straight alpha ā — with NO
window normalization: a one-point cell reads exactly like one point, dense
cells saturate exactly like overplotted marks, and lightness cannot swing
between windows or across the texture↔points boundary (the previous
per-window log-count tone curve did both; field capture on the 100M
drilldown). Count-only grids keep the log ramp — count is their only
structure — and mean-color drills swap at native opacity with no intensity
handoff (`density_val`/`lod_blend` ignored on such traces).

This drives the real client in headless Chromium, intercepting the texture
upload to read the exact bytes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'

_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    view._raf = null;
    view._sampleRebinDisabled = true;
    const g = view.gpuTraces.find((t) => t.tier === "density");
    const v0 = view.view0;

    // A mean-color reply: 4 cells with counts [0, 1, 3, 50], all wearing the
    // same mean color at full channel alpha — the drawn per-point alpha is
    // the trace's style opacity (0.72), folded INSIDE the exponent.
    const gw = 4, gh = 1;
    const counts = new Float32Array([0, 1, 3, 50]);
    const abar = 0.72; // style opacity from the chart below
    const rgba = new Uint8Array(gw * 4);
    for (let i = 0; i < gw; i++) {
      rgba[i * 4] = 200; rgba[i * 4 + 1] = 60; rgba[i * 4 + 2] = 30;
      rgba[i * 4 + 3] = 255;
    }
    let uploaded = null;
    const gl = view.gl;
    const realTexImage = gl.texImage2D.bind(gl);
    gl.texImage2D = function (...args) {
      const data = args[args.length - 1];
      if (data && data.length === gw * gh * 4) uploaded = new Uint8Array(data);
      return realTexImage(...args);
    };
    view._onKernelMsg({
      type: "density_update", seq: view.seq, trace: g.trace.id,
      traces: [{
        id: g.trace.id, mode: "density", visible: 5000000,
        density: {
          buf: 0, w: gw, h: gh, max: 50,
          x_range: [v0.x0, v0.x1], y_range: [v0.y0, v0.y1],
          rgba: 1, color_agg: "mean",
        },
      }],
    }, [counts.buffer, rgba.buffer]);
    gl.texImage2D = realTexImage;

    const a = uploaded ? [uploaded[3], uploaded[7], uploaded[11], uploaded[15]] : null;
    const expect = (k) => Math.round(255 * (1 - Math.pow(1 - abar, k)));
    // Physical law, no window-max dependence: empty stays 0, k=1 IS the
    // drawn per-point alpha, k=3 composites up, k=50 saturates past the
    // style opacity exactly like overplotted marks.
    const law = a && a[0] === 0 &&
      Math.abs(a[1] - expect(1)) <= 1 &&
      Math.abs(a[2] - expect(3)) <= 1 &&
      a[3] >= 254;
    // No exposure easing on mean-color grids: nothing schedules re-uploads.
    const noNormAnim = g._densityNormAnim === null || g._densityNormAnim === undefined;

    // A drill landing on this mean-color surface carries density_val and a
    // blend weight — both must be ignored: marks enter at native opacity.
    const N = 50;
    const xs = new Float32Array(N), ys = new Float32Array(N), dv = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      xs[i] = v0.x0 + (v0.x1 - v0.x0) * ((i * 0.618) % 1);
      ys[i] = v0.y0 + (v0.y1 - v0.y0) * ((i * 0.314) % 1);
      dv[i] = 0.9;
    }
    view._applyDrill(g, {
      id: g.trace.id, mode: "points", visible: N, reduction: "none", drill_seq: 1,
      x: { buf: 0, offset: 0, scale: 1, len: N },
      y: { buf: 1, offset: 0, scale: 1, len: N },
      x_range: [v0.x0, v0.x1], y_range: [v0.y0, v0.y1],
      density_val: { buf: 2 }, lod_blend: 0.85,
    }, [xs.buffer, ys.buffer, dv.buffer]);
    const noHandoff = g.drill && g.drill.lodBlend === 0 && !g.drill.dBuf;

    document.body.setAttribute("data-xy-alpha-probe", JSON.stringify({
      hasDensity: !!g, gotUpload: !!uploaded, alphas: a, law, noNormAnim, noHandoff,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-alpha-probe-error",
      String((err && err.stack) || err),
    );
  }
"""


def _density_html() -> str:
    rng = np.random.default_rng(0)
    n = 60_000
    x = rng.normal(0.0, 1.0, n)
    y = rng.normal(0.0, 1.0, n)
    c = np.hypot(x, y)
    chart = xy.scatter_chart(
        xy.scatter(x, y, color=c, colormap="viridis", opacity=0.72, density=True),
        xy.x_axis(),
        xy.y_axis(),
        width=480,
        height=360,
    )
    html = chart.to_html()
    assert _RENDER_CALL in html
    return html


def test_mean_color_texture_uses_physical_alpha(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "density_physical_alpha.html",
        "data-xy-alpha-probe",
        label="mean-color physical-alpha probe",
    )

    assert result["hasDensity"] is True
    assert result["gotUpload"] is True
    # alpha(k) = 1-(1-0.72)^k, independent of the window max: 0, 184, 250, 255.
    assert result["law"] is True, result["alphas"]
    assert result["noNormAnim"] is True
    assert result["noHandoff"] is True
