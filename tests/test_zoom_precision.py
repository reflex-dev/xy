"""Browser regression for anisotropic box-zoom followed by zoom-out."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy.export import find_chromium  # noqa: E402

_RENDER_CALLS = (
    'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
    'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
)

_PROBE = """
<script>
(() => {
  try {
    const view = window.__xyZoomProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const home = { ...view.view0 };

    // Reproduce #87: narrow X much faster than Y with three box zooms.
    for (let i = 0; i < 3; i++) {
      const current = view.view;
      const xSpan = current.x1 - current.x0;
      const ySpan = current.y1 - current.y0;
      view._zoomToBox(
        [current.x0 + xSpan * 0.4, current.y0 + ySpan * 0.1],
        [current.x0 + xSpan * 0.6, current.y0 + ySpan * 0.9],
        false
      );
    }
    for (let i = 0; i < 4; i++) view._zoomBy(2, false);

    const current = view.view;
    const xZoom = Math.abs((home.x1 - home.x0) / (current.x1 - current.x0));
    const yZoom = Math.abs((home.y1 - home.y0) / (current.y1 - current.y0));
    document.body.setAttribute("data-xy-zoom-precision", JSON.stringify({
      home,
      current,
      xZoom,
      yZoom,
      finite: Object.values(current).every(Number.isFinite),
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-zoom-precision-error",
      String((err && err.stack) || err)
    );
  }
})();
</script>
"""


def test_zoom_out_does_not_expand_less_zoomed_axis_past_home(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("no chromium available for the zoom precision probe")

    chart = xy.scatter_chart(
        xy.scatter(
            x=[-2.0, -1.0, 0.0, 1.0, 2.0],
            y=[-1.0, 0.5, 0.0, -0.5, 1.0],
        ),
        width=640,
        height=420,
    )
    document = chart.to_html()
    render_call = next((call for call in _RENDER_CALLS if call in document), None)
    assert render_call is not None
    document = document.replace(
        render_call,
        render_call.replace(
            "xy.renderStandalone(", "window.__xyZoomProbeView = xy.renderStandalone(", 1
        ),
        1,
    )
    document = document.replace("</body>", _PROBE + "\n</body>", 1)

    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "zoom_precision.html",
        "data-xy-zoom-precision",
        label="zoom precision probe",
    )

    assert result["finite"] is True, result
    assert result["xZoom"] == pytest.approx(7.8125), result
    assert result["yZoom"] == pytest.approx(1.0), result
    assert result["current"]["y0"] == pytest.approx(result["home"]["y0"]), result
    assert result["current"]["y1"] == pytest.approx(result["home"]["y1"]), result
