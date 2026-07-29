"""Focused browser/client regressions for polar interaction and clipping."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

import xy
from conftest import probe_document, run_browser_probe
from xy.export import find_chromium

ROOT = Path(__file__).resolve().parents[1]


def test_polar_client_routes_coupled_coordinates_and_disables_pan() -> None:
    chartview = (ROOT / "js/src/50_chartview.ts").read_text()
    annotations = (ROOT / "js/src/51_annotations.ts").read_text()
    tooltip = (ROOT / "js/src/52_tooltip.ts").read_text()
    interaction = (ROOT / "js/src/53_interaction.ts").read_text()

    assert '&& this._axisPolicy("pan_axes").length > 0;' in chartview
    assert 'const panAxes = this._axisPolicy("pan_axes");' in interaction
    assert "&& canPan && panAxes.length > 0" in interaction
    assert interaction.count('&& this._axisPolicy("pan_axes").length > 0;') >= 1

    assert "this._projectDataPoint(a.xAxis, a.yAxis, a.x, a.y)" in tooltip
    assert "this._projectDataPoint(g.xAxis, g.yAxis, x, y, polarGeom)" in annotations
    assert "[targetX, targetY] = project(ann.x1, ann.y1);" in annotations
    assert "[px, py] = project(ann.x, ann.y);" in annotations


def test_every_polar_gl_mark_fragment_path_uses_annular_sector_clip() -> None:
    source = (ROOT / "js/src/40_gl.ts").read_text()
    for name in (
        "POINT_FS",
        "POINT_SIMPLE_FS",
        "PICK_FS",
        "LINE_FS",
        "SEGMENT_FS",
        "AREA_FS",
        "RECT_FS",
    ):
        block = source.split(f"export const {name} =", 1)[1].split("`;", 1)[0]
        assert "${POLAR_FRAGMENT_CLIP_GLSL}" in block, name
        assert "xyClipPolarFragment();" in block, name

    annotations = (ROOT / "js/src/51_annotations.ts").read_text()
    assert "function xyClipPolarCanvas(ctx, geom)" in annotations
    assert "if (polarGeom) xyClipPolarCanvas(ctx, polarGeom);" in annotations


def test_polar_fill_shaders_order_reversed_radial_clamp_bounds() -> None:
    source = (ROOT / "js/src/40_gl.ts").read_text()
    for name in ("AREA_VS", "RECT_VS", "BAR_VS"):
        block = source.split(f"export const {name} =", 1)[1].split("`;", 1)[0]
        assert "float rmin = min(u_rrange.x, u_rrange.y);" in block, name
        assert "float rmax = max(u_rrange.x, u_rrange.y);" in block, name
        assert not re.search(
            r"clamp\([^;]*u_rrange\.x,\s*u_rrange\.y",
            block,
        ), name


def test_reversed_polar_radial_axis_keeps_bar_and_area_visible(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.polar_chart(
        xy.bar(
            [0.0],
            [8.0],
            base=2.0,
            width=0.6,
            color="#ff0000",
            opacity=1.0,
            animation=False,
        ),
        xy.area(
            [math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0],
            [8.0, 6.0, 8.0],
            base=2.0,
            color="#0000ff",
            opacity=1.0,
            line_width=0.0,
            animation=False,
        ),
        xy.r_axis(domain=(1.0, 10.0), reverse=True),
        width=420,
        height=420,
    )
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    view.gl.finish();
    const gl = view.gl;
    const pixels = new Uint8Array(
      gl.drawingBufferWidth * gl.drawingBufferHeight * 4
    );
    gl.readPixels(
      0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight,
      gl.RGBA, gl.UNSIGNED_BYTE, pixels,
    );
    let red = 0;
    let blue = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i] > 200 && pixels[i + 1] < 60
          && pixels[i + 2] < 60 && pixels[i + 3] > 200) red++;
      if (pixels[i] < 60 && pixels[i + 1] < 60
          && pixels[i + 2] > 200 && pixels[i + 3] > 200) blue++;
    }
    const geom = view._polarGeometry();
    document.body.setAttribute("data-xy-polar-reversed-r", JSON.stringify({
      red,
      blue,
      range: [geom.rLoRaw, geom.rHiRaw],
      barPoint: view._polarProject(0, 8, geom),
      areaPoint: view._polarProject(Math.PI, 6, geom),
      glError: gl.getError(),
    }));
  } catch (error) {
    document.body.setAttribute(
      "data-xy-polar-reversed-r-error",
      String((error && error.stack) || error),
    );
  }
}, 250);
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_reversed_r.html",
        "data-xy-polar-reversed-r",
        label="polar reversed radial probe",
    )

    assert result["glError"] == 0
    assert result["range"] == pytest.approx([10.0, 1.0])
    assert all(math.isfinite(value) for value in result["barPoint"])
    assert all(math.isfinite(value) for value in result["areaPoint"])
    assert result["red"] > 100
    assert result["blue"] > 100


def test_polar_keyboard_traversal_does_not_hover_culled_point(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.polar_chart(
        # Source order is deliberate: the first point lies outside the sector,
        # while the second is visible and should receive the next key traversal.
        xy.scatter([math.pi, math.pi / 4.0], [0.5, 0.5], size=12.0),
        xy.theta_axis(sector=(0.0, math.pi / 2.0)),
        xy.r_axis(domain=(0.0, 1.0)),
        xy.interaction_config(hover=True),
        width=420,
        height=320,
    )
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    let hoverEvents = 0;
    view.root.addEventListener("xy:hover", () => hoverEvents++);
    const key = () => view.canvas.dispatchEvent(new KeyboardEvent("keydown", {
      key: "ArrowRight", bubbles: true, cancelable: true,
    }));
    key();
    const afterCulled = {
      index: view._a11yPointIndex,
      hoverId: view._hoverId,
      target: view._hoverTarget,
      display: view.tooltip.style.display,
      left: view.tooltip.style.left,
      top: view.tooltip.style.top,
      hoverEvents,
    };
    key();
    const afterVisible = {
      index: view._a11yPointIndex,
      targetIndex: view._hoverTarget ? view._hoverTarget.index : null,
      display: view.tooltip.style.display,
      left: view.tooltip.style.left,
      top: view.tooltip.style.top,
      hoverEvents,
    };
    document.body.setAttribute("data-xy-polar-keyboard-cull", JSON.stringify({
      afterCulled,
      afterVisible,
    }));
  } catch (error) {
    document.body.setAttribute(
      "data-xy-polar-keyboard-cull-error",
      String((error && error.stack) || error),
    );
  }
}, 250);
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_keyboard_cull.html",
        "data-xy-polar-keyboard-cull",
        label="polar keyboard cull probe",
    )

    culled = result["afterCulled"]
    assert culled["index"] == 0
    assert culled["hoverId"] == -1
    assert culled["target"] is None
    assert culled["display"] != "block"
    assert "NaN" not in culled["left"]
    assert "NaN" not in culled["top"]
    assert culled["hoverEvents"] == 0

    visible = result["afterVisible"]
    assert visible["index"] == 1
    assert visible["targetIndex"] == 1
    assert visible["display"] == "block"
    assert visible["left"].endswith("px") and "NaN" not in visible["left"]
    assert visible["top"].endswith("px") and "NaN" not in visible["top"]
    assert visible["hoverEvents"] == 1


def test_polar_gl_chords_are_clipped_to_hole_and_sector(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.polar_chart(
        # This diameter crosses the hole.
        xy.line([0.0, math.pi], [1.0, 1.0], color="#ff0000", width=14),
        # This boundary-to-boundary chord crosses the excluded 270°..360°
        # wedge of the partial sector.
        xy.line(
            [0.0, 1.5 * math.pi],
            [1.0, 1.0],
            color="#0000ff",
            width=14,
        ),
        xy.scatter(
            [1.0],
            [0.7],
            color="#ff0000",
            size=32,
            opacity=1.0,
            density=False,
            _marker_glyph="●",
        ),
        xy.text(1.0, 0.7, "joint", dx=0, dy=0),
        xy.theta_axis(sector=(0.0, 1.5 * math.pi)),
        xy.r_axis(domain=(0.0, 1.0), hole=0.35),
        width=420,
        height=420,
    )
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    view.gl.finish();
    const geom = view._polarGeometry();
    const read = (chartX, chartY) => {
      const rgba = new Uint8Array(4);
      const x = Math.max(0, Math.min(
        view.canvas.width - 1,
        Math.round((chartX - view.plot.x) * view.dpr),
      ));
      const y = Math.max(0, Math.min(
        view.canvas.height - 1,
        Math.round((view.plot.y + view.plot.h - chartY) * view.dpr),
      ));
      view.gl.readPixels(x, y, 1, 1, view.gl.RGBA, view.gl.UNSIGNED_BYTE, rgba);
      return Array.from(rgba);
    };
    const east = view._polarProject(0, 1, geom);
    const south = view._polarProject(1.5 * Math.PI, 1, geom);
    const missingWedgeMidpoint = [
      (east[0] + south[0]) / 2,
      (east[1] + south[1]) / 2,
    ];
    const projected = view._projectDataPoint("x", "y", 1, 0.7, geom);
    view._tooltipAnchor = {xAxis: "x", yAxis: "y", x: 1, y: 0.7};
    const tooltipAnchor = view._tooltipAnchorPx();
    const annotation = Array.from(view.labels.children)
      .find((node) => node.textContent === "joint");
    const overlay = view.overlay.getContext("2d");
    const scanRed = (chartX, chartY) => {
      const radius = Math.round(14 * view.dpr);
      const x = Math.max(0, Math.round(chartX * view.dpr) - radius);
      const y = Math.max(0, Math.round(chartY * view.dpr) - radius);
      const width = Math.min(view.overlay.width - x, radius * 2 + 1);
      const height = Math.min(view.overlay.height - y, radius * 2 + 1);
      const pixels = overlay.getImageData(x, y, width, height).data;
      let count = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] > 180 && pixels[i + 1] < 100
            && pixels[i + 2] < 100 && pixels[i + 3] > 30) count++;
      }
      return count;
    };
    const initialDragMode = view.dragMode;
    const panButton = !!view.root.querySelector('[data-xy-modebar-action="pan"]');
    const beforeZoom = [...view._axisRange("y")];
    view._zoomAt(0.5, 0.5, 0.5, false, 0);
    const afterZoom = [...view._axisRange("y")];
    const canvasRect = view.canvas.getBoundingClientRect();
    const clientX = canvasRect.left + canvasRect.width / 2;
    const clientY = canvasRect.top + canvasRect.height / 2;
    view.canvas.dispatchEvent(new PointerEvent("pointerdown", {
      bubbles: true, pointerId: 71, pointerType: "mouse", buttons: 1,
      clientX, clientY,
    }));
    view.canvas.dispatchEvent(new PointerEvent("pointermove", {
      bubbles: true, pointerId: 71, pointerType: "mouse", buttons: 1,
      clientX, clientY: clientY + 35,
    }));
    view.canvas.dispatchEvent(new PointerEvent("pointerup", {
      bubbles: true, pointerId: 71, pointerType: "mouse", buttons: 0,
      clientX, clientY: clientY + 35,
    }));
    const afterDrag = [...view._axisRange("y")];
    const result = {
      glError: view.gl.getError(),
      hole: read(geom.cx, geom.cy),
      missingSector: read(...missingWedgeMidpoint),
      visibleChord: read(geom.cx - geom.radius * 0.7, geom.cy),
      projected,
      tooltipAnchor,
      annotationAnchor: annotation
        ? [parseFloat(annotation.style.left), parseFloat(annotation.style.top)]
        : null,
      authoredMarkerRedPixels: scanRed(...projected),
      initialDragMode,
      panButton,
      beforeZoom,
      afterZoom,
      afterDrag,
    };
    document.body.setAttribute("data-xy-polar-clip-probe", JSON.stringify(result));
  } catch (error) {
    document.body.setAttribute(
      "data-xy-polar-clip-probe-error",
      String((error && error.stack) || error),
    );
  }
}, 250);
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_fragment_clip.html",
        "data-xy-polar-clip-probe",
        label="polar fragment clip probe",
    )

    assert result["glError"] == 0
    assert result["hole"][3] == 0
    assert result["missingSector"][3] == 0
    assert result["visibleChord"][3] > 0
    assert result["tooltipAnchor"]["lx"] == pytest.approx(result["projected"][0])
    assert result["tooltipAnchor"]["ly"] == pytest.approx(result["projected"][1])
    assert result["annotationAnchor"] == pytest.approx(result["projected"])
    assert result["authoredMarkerRedPixels"] > 5
    assert result["initialDragMode"] != "pan"
    assert result["panButton"] is False
    assert result["afterZoom"] != pytest.approx(result["beforeZoom"])
    assert result["afterDrag"] == pytest.approx(result["afterZoom"])
