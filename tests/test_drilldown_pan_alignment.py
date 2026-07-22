"""FastAPI drilldown: a pan past the data must not offset the density surface.

The drilldown export re-bins its density overview *in the browser* on pan/zoom
(``localDensityUpdate`` in ``examples/fastapi/live_drilldown.py``) from a
fixed-extent integral image. A requested window can reach past the data domain;
the source-bin lookups clamp there, so the grid covers only the on-domain part
of the window. If the update still reports the *requested* window as the grid's
data range, the fixed-extent texture is stretched across the wider window and
the density slides off the point cloud (drilled points and the retained §28
sample draw at true data coordinates). This drives the real client in headless
Chromium, pans well past the +x/+y data edge, and checks the reported density
range stays within the data domain and its mass stays aligned with the data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from conftest import run_browser_probe
from xy.export import find_chromium

FASTAPI_DIR = Path(__file__).resolve().parents[1] / "examples" / "fastapi"

_ANCHOR = "window.xyLiveDrilldown = view;"

_PROBE = r"""
window.xyLiveDrilldown = view;
(async () => {
  try {
    view._drawNow(); view._raf = null;
    const g = view.gpuTraces.find((t) => t.tier === "density");
    const ov = spec.traces.find((t) => t.kind === "scatter" && t.density).density;
    const domX = ov.x_range, domY = ov.y_range;
    const v0 = view.view0 || view.view;
    const homeRange = { x: g.density.xRange.slice(), y: g.density.yRange.slice() };
    // Density cache entries are intentionally GPU-only. Capture the transient
    // local-rebin upload in the probe so alignment can still inspect its mass
    // without making production retain a second CPU grid.
    const uploaded = new WeakMap();
    const realUploadDensityGrid = view._uploadDensityGrid;
    view._uploadDensityGrid = (bytes, w, h) => {
      const texture = realUploadDensityGrid.call(view, bytes, w, h);
      uploaded.set(texture, bytes.slice());
      return texture;
    };

    // Density mass centroid in DATA coordinates, using the reported grid range.
    const centroid = (d) => {
      const { w, h, xRange, yRange } = d;
      const grid = uploaded.get(d.tex);
      if (!grid) throw new Error("panned density upload was not observed");
      let sx = 0, sy = 0, sw = 0;
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const v = grid[y * w + x] || 0; if (v <= 0) continue;
        sx += (xRange[0] + (x + 0.5) / w * (xRange[1] - xRange[0])) * v;
        sy += (yRange[0] + (y + 0.5) / h * (yRange[1] - yRange[0])) * v;
        sw += v;
      }
      return sw > 0 ? { x: sx / sw, y: sy / sw } : null;
    };

    // Pan well past the +x / +y data edge (span unchanged), so the requested
    // window reaches beyond the domain and the source bins clamp.
    const sx = v0.x1 - v0.x0, sy = v0.y1 - v0.y0;
    const panned = { x0: v0.x0 + sx * 0.4, x1: v0.x1 + sx * 0.4,
                     y0: v0.y0 + sy * 0.4, y1: v0.y1 + sy * 0.4 };
    view.view = view._viewFrom(panned);
    view._scheduleViewRequest(view.view, { delay: 0, seq: ++view.seq });
    await new Promise((r) => setTimeout(r, 60));
    view._drawNow(); view._raf = null;

    const c = centroid(g.density);
    view._uploadDensityGrid = realUploadDensityGrid;
    document.body.setAttribute("data-drill-pan", JSON.stringify({
      hasDensity: !!g,
      domX, domY,
      reqHiX: panned.x1, reqHiY: panned.y1,
      homeRange,
      pannedRange: { x: g.density.xRange.slice(), y: g.density.yRange.slice() },
      centroid: c,
    }));
  } catch (err) {
    document.body.setAttribute("data-drill-pan-error", String((err && err.stack) || err));
  }
})();
"""


def _drilldown_html() -> str:
    # Enough points that a panned window still clears the browser-local re-bin
    # budget (DIRECT_POINT_BUDGET * 4 = 800k visible); below it the pan falls to
    # the server round-trip, which is unavailable under file:// and untested here.
    os.environ["XY_LIVE_POINTS"] = "2000000"
    sys.path.insert(0, str(FASTAPI_DIR))
    import importlib

    import live_drilldown

    importlib.reload(live_drilldown)
    html = live_drilldown.live_drilldown_html()
    assert _ANCHOR in html
    return html


def test_drilldown_pan_past_data_keeps_density_aligned(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    # examples/fastapi/live_drilldown.py imports starlette at module load (the
    # callback endpoint), but it is not a core test dependency. Skip cleanly
    # where the fastapi example extra is not installed — same convention as
    # tests/test_example_apps.py's importorskip for the fastapi app test.
    pytest.importorskip("starlette")

    document = _drilldown_html().replace(_ANCHOR, _PROBE, 1)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "drilldown_pan.html",
        "data-drill-pan",
        label="drilldown pan alignment probe",
    )

    assert result["hasDensity"] is True
    dom_x = result["domX"]
    dom_y = result["domY"]
    px = result["pannedRange"]["x"]
    py = result["pannedRange"]["y"]

    # The browser-local re-bin must have run (range changed from home), proving
    # this exercised localDensityUpdate rather than silently no-op'ing.
    assert px != result["homeRange"]["x"], "local density re-bin did not run on pan"

    # The reported grid range must stay within the data domain: the overview
    # integral only holds data inside the domain, so a range reaching past it
    # (toward the requested window edge) is exactly the stretch bug.
    span_x = dom_x[1] - dom_x[0]
    span_y = dom_y[1] - dom_y[0]
    eps_x = span_x * 1e-6
    eps_y = span_y * 1e-6
    assert px[1] <= dom_x[1] + eps_x, (px, dom_x)
    assert py[1] <= dom_y[1] + eps_y, (py, dom_y)
    # And it was genuinely clamped to the domain, not left at the request.
    assert px[1] < result["reqHiX"] - eps_x, (px, result["reqHiX"])
    assert py[1] < result["reqHiY"] - eps_y, (py, result["reqHiY"])

    # The density mass stays aligned with the data (centered near the origin,
    # not dragged toward the requested-but-empty window edge). The pre-fix
    # stretch put the centroid past ~1.1 in x; the data centroid here is ~0.2.
    c = result["centroid"]
    assert c is not None
    assert -1.0 < c["x"] < 1.0, c
    assert -1.0 < c["y"] < 1.0, c
