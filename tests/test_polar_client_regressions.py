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


def test_polar_wheel_zoom_is_alive_and_keeps_r_lo_fixed(tmp_path: Path) -> None:
    """Real wheel events must zoom the radial axis with r_lo pinned (§8).

    Two regressions in one probe. First, the wheel gate `dragMode === "none"`
    conflated the user's modebar opt-out with the RESOLVED default — polar
    disables pan/box/select, so its default drag tool is `none`, and the gate
    made radial wheel zoom (polar's only navigation) dead on arrival. Second,
    the assertion is on the §8 contract itself — r_lo fixed, r_hi scaled —
    not just `after != before`.

    Zoom is opted into explicitly because polar now defaults it OFF (§8); this
    probe is about the shape of the gesture once it IS enabled, and
    `test_polar_zoom_is_off_by_default_and_releases_page_scroll` covers the
    default.
    """
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    theta = [i * 2.0 * math.pi / 40.0 for i in range(40)]
    r = [1.0 + 0.4 * math.sin(3.0 * t) for t in theta]
    chart = xy.polar_chart(
        xy.line(theta, r, animation=False),
        xy.interaction_config(zoom=True),
        width=420,
        height=420,
    )
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    const before = view._axisRange("y").slice();
    const canvas = view.canvas;
    const rect = canvas.getBoundingClientRect();
    const cx = rect.left + rect.width * 0.62;
    const cy = rect.top + rect.height * 0.42;

    // Wheel deltas apply a frame later; make frames deterministic instead of
    // waiting out a wall-clock delay. The headless probe runs under
    // --virtual-time-budget, which fast-forwards timers but still needs real
    // frames for rAF, so a timed wait can resolve BEFORE the zoom commits.
    view._raf = null;
    const realRaf = window.requestAnimationFrame;
    let frames = [];
    window.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    const flush = () => {
      for (let round = 0; round < 4 && frames.length; round++) {
        const queued = frames;
        frames = [];
        for (const fn of queued) fn();
      }
    };

    for (let i = 0; i < 5; i++) {
      canvas.dispatchEvent(new WheelEvent("wheel", {
        deltaY: -120, clientX: cx, clientY: cy, bubbles: true, cancelable: true,
      }));
    }
    flush();
    const after = view._axisRange("y").slice();
    window.requestAnimationFrame = realRaf;
    document.body.setAttribute("data-xy-polar-wheel", JSON.stringify({ before, after }));
  } catch (error) {
    document.body.setAttribute("data-xy-polar-wheel-error", String(error));
  }
}, 220);
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_wheel.html",
        "data-xy-polar-wheel",
        label="polar wheel zoom",
    )
    before, after = result["before"], result["after"]
    assert before[0] == 0.0
    assert after[0] == 0.0, f"radial zoom moved r_lo: {after}"
    assert after[1] < before[1] * 0.9, f"wheel did not zoom: {before} -> {after}"


def test_polar_zoom_is_off_by_default_and_releases_page_scroll(tmp_path: Path) -> None:
    """A default polar chart must ignore the wheel end to end (§8).

    The Python default (`zoom=False` on the wire) only pays off if the client
    honours it all the way down, so this asserts the three consequences a user
    actually meets: the radial range does not move, the wheel event is left
    UNCANCELLED so the page keeps scrolling under the cursor, and the modebar
    grows no zoom menu — history alone used to build a "100%" trigger over two
    permanently dead Back/Next items.
    """
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    theta = [i * 2.0 * math.pi / 40.0 for i in range(40)]
    r = [1.0 + 0.4 * math.sin(3.0 * t) for t in theta]
    chart = xy.polar_chart(xy.line(theta, r, animation=False), width=420, height=420)
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    const before = view._axisRange("y").slice();
    const canvas = view.canvas;
    const rect = canvas.getBoundingClientRect();
    const cx = rect.left + rect.width * 0.62;
    const cy = rect.top + rect.height * 0.42;

    view._raf = null;
    const realRaf = window.requestAnimationFrame;
    let frames = [];
    window.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    const flush = () => {
      for (let round = 0; round < 4 && frames.length; round++) {
        const queued = frames;
        frames = [];
        for (const fn of queued) fn();
      }
    };

    let cancelled = false;
    for (let i = 0; i < 5; i++) {
      const event = new WheelEvent("wheel", {
        deltaY: -120, clientX: cx, clientY: cy, bubbles: true, cancelable: true,
      });
      canvas.dispatchEvent(event);
      if (event.defaultPrevented) cancelled = true;
    }
    flush();
    const after = view._axisRange("y").slice();
    window.requestAnimationFrame = realRaf;
    document.body.setAttribute("data-xy-polar-nozoom", JSON.stringify({
      before,
      after,
      cancelled,
      zoomMenu: !!view.root.querySelector('[data-xy-modebar-menu-trigger]'),
      zoomIn: !!view.root.querySelector('[data-xy-modebar-menu-item="zoomin"]'),
      historyBack: !!view.root.querySelector('[data-xy-modebar-history="back"]'),
      modebar: !!view.root.querySelector('[data-xy-slot="modebar"]'),
    }));
  } catch (error) {
    document.body.setAttribute("data-xy-polar-nozoom-error", String(error));
  }
}, 220);
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_no_zoom.html",
        "data-xy-polar-nozoom",
        label="polar default zoom off",
    )
    assert result["after"] == pytest.approx(result["before"]), (
        f"wheel moved the radial range with zoom off: {result['before']} -> {result['after']}"
    )
    assert result["cancelled"] is False, "wheel was cancelled, swallowing page scroll"
    # The modebar itself still renders (export lives there); only the zoom
    # controls are gone.
    assert result["modebar"] is True
    assert result["zoomIn"] is False
    assert result["historyBack"] is False
    assert result["zoomMenu"] is False


@pytest.mark.parametrize(
    ("label", "build"),
    [
        # Zoom off but reset authored: the menu is needed, the readout is not.
        (
            "polar",
            lambda: xy.polar_chart(
                xy.line([0.0, 1.0, 2.0], [1.0, 2.0, 1.5], animation=False),
                xy.interaction_config(reset_axes=("y",)),
                width=420,
                height=420,
            ),
        ),
        # Same wart off the polar path: pan/select keep the menu alive while the
        # percentage can never move.
        (
            "cartesian",
            lambda: xy.line_chart(
                xy.line([0.0, 1.0, 2.0], [1.0, 2.0, 1.5], animation=False),
                xy.interaction_config(zoom=False),
                width=420,
                height=300,
            ),
        ),
    ],
)
def test_a_zoom_disabled_modebar_shows_no_zoom_percentage(label, build, tmp_path: Path) -> None:
    """The "100%" trigger is a zoom READOUT and must not outlive zoom.

    The menu legitimately survives `zoom=False` — reset (via an authored
    `reset_axes`) and view history both live in it — but its trigger rendered a
    permanent "100%" that advertises a control the chart does not have and that
    no gesture can move. It falls back to the menu icon, and the accessible name
    drops from "Zoom controls" to "View controls".
    """
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    probe = """
<script>
setTimeout(() => {
  try {
    const v = window.__fcProbeView;
    v._drawNow();
    const trigger = v.root.querySelector('[data-xy-modebar-menu-trigger]');
    document.body.setAttribute("data-xy-nopct", JSON.stringify({
      zoomFlag: v._interactionFlag("zoom", true),
      trigger: !!trigger,
      percent: trigger ? !!trigger.querySelector('[data-xy-modebar-zoom-percent]') : null,
      icon: trigger ? !!trigger.querySelector('[data-xy-slot="modebar_icon"] svg') : null,
      triggerLabel: trigger ? trigger.getAttribute("aria-label") : null,
      menuLabel: (v.root.querySelector('[data-xy-modebar-menu]') || {
        getAttribute: () => null,
      }).getAttribute("aria-label"),
      resetItem: !!v.root.querySelector('[data-xy-modebar-menu-item="reset"]'),
      zoomIn: !!v.root.querySelector('[data-xy-modebar-menu-item="zoomin"]'),
      labelRef: !!v._zoomMenuLabel,
    }));
  } catch (error) {
    document.body.setAttribute("data-xy-nopct-error", String(error));
  }
}, 220);
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(build(), probe),
        tmp_path / f"no_percent_{label}.html",
        "data-xy-nopct",
        label=f"{label} zoom-off modebar",
    )
    assert result["zoomFlag"] is False
    # The menu is still there and still useful...
    assert result["trigger"] is True
    assert result["resetItem"] is True
    # ...but carries no zoom readout and offers no zoom action.
    assert result["percent"] is False, "zoom percentage rendered on a chart that cannot zoom"
    assert result["icon"] is True, "trigger lost its icon fallback"
    assert result["zoomIn"] is False
    assert result["triggerLabel"] == "View controls"
    assert result["menuLabel"] == "View controls"
    # No label element means `_updateZoomMenuLabel` has nothing to overwrite the
    # accessible name with on the next view change.
    assert result["labelRef"] is False


def test_wind_rose_keeps_radial_zoom_without_restoring_box_zoom(tmp_path: Path) -> None:
    """The wind-rose exception grants RADIAL zoom, not the rectangle gestures.

    `zoom` is the generic capability, so enabling it on the one polar chart that
    wants zoom raises the question of whether `box_zoom` (which defaults to true)
    comes back with it. It does not: the client forces `box_zoom`, `select`,
    `brush`, and `crosshair` off under `coords="polar"` regardless of the flags
    (§8), so a default rose gets the wheel, the Zoom In/Out buttons, and reset —
    and no Box Zoom item, no Pan button, and a resolved drag tool of `none`.
    """
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    bearings = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0] * 4
    speeds = [1.0, 4.0, 9.0, 3.0, 6.0, 2.0, 7.0, 5.0] * 4
    chart = xy.wind_rose(bearings, speeds, width=420, height=420)
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    document.body.setAttribute("data-xy-rose-zoom", JSON.stringify({
      zoomFlag: view._interactionFlag("zoom", true),
      boxZoomFlag: view._interactionFlag("box_zoom", true),
      dragMode: view.dragMode,
      zoomAxes: view._axisPolicy("zoom_axes"),
      resetAxes: view._resetAxisPolicy(),
      zoomIn: !!view.root.querySelector('[data-xy-modebar-menu-item="zoomin"]'),
      resetItem: !!view.root.querySelector('[data-xy-modebar-menu-item="reset"]'),
      boxZoomItem: !!view.root.querySelector('[data-xy-modebar-menu-item="zoom"]'),
      panButton: !!view.root.querySelector('[data-xy-modebar-action="pan"]'),
      selectTrigger: !!view.root.querySelector('[data-xy-modebar-select-trigger]'),
    }));
  } catch (error) {
    document.body.setAttribute("data-xy-rose-zoom-error", String(error));
  }
}, 220);
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "wind_rose_zoom.html",
        "data-xy-rose-zoom",
        label="wind rose zoom scope",
    )
    # Granted: radial zoom on the r axis only, plus its reset.
    assert result["zoomFlag"] is True
    assert result["zoomAxes"] == ["y"]
    assert result["resetAxes"] == ["y"]
    assert result["zoomIn"] is True
    assert result["resetItem"] is True
    # Withheld: every rectangle-shaped gesture, and any drag tool at all.
    assert result["boxZoomFlag"] is False
    assert result["boxZoomItem"] is False
    assert result["panButton"] is False
    assert result["selectTrigger"] is False
    assert result["dragMode"] != "zoom"


def test_polar_bar_hover_wraps_across_the_seam(tmp_path: Path) -> None:
    """A wedge straddling theta = 0/turn (a wind-rose "N" sector) must be
    hoverable on BOTH sides of the seam. `_barHover` compared |dataX - centre|
    in unwrapped data space, so dataX = 355 missed a 30-degree bar centred on
    0 (|355 - 0| = 355), which drew correctly and was silently un-hoverable
    on its wrap side — the exact miss spec §3.2 calls out."""
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.polar_chart(
        xy.bar([0.0, 90.0, 180.0], [3.0, 2.0, 1.0], width=30.0, animation=False),
        xy.theta_axis(unit="degrees", zero="N", direction="clockwise"),
        width=420,
        height=420,
    )
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    const g = view.gpuTraces.find((t) => t.trace.bar);
    document.body.setAttribute("data-xy-polar-seam-hover", JSON.stringify({
      direct: !!view._barHover(g, 10.0, 1.5),
      wrapped: !!view._barHover(g, 355.0, 1.5),
      outside: !!view._barHover(g, 40.0, 1.5),
    }));
  } catch (error) {
    document.body.setAttribute("data-xy-polar-seam-hover-error", String(error));
  }
}, 220);
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_seam_hover.html",
        "data-xy-polar-seam-hover",
        label="polar seam hover",
    )
    assert result == {"direct": True, "wrapped": True, "outside": False}


def test_polar_tooltip_content_speaks_polar(tmp_path: Path) -> None:
    """Tooltip *content* on polar charts — the review's coverage gap.

    The default readout shows VALUES, not angles: the angle is where layout put
    the mark and the cursor is already on it, so a numeric theta row is omitted
    and only the series name plus the radial value appear. An authored spoke
    label is a name rather than an angle and still shows (covered below), and
    naming the row via `labels={"x": ...}` opts it back in.
    """
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    theta = [i * 2.0 * math.pi / 24.0 for i in range(24)]
    r = [1.0 + 0.4 * math.sin(3.0 * t) for t in theta]
    chart = xy.polar_chart(xy.line(theta, r, name="gain", animation=False), width=420, height=400)
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    const g = view.gpuTraces[0];
    // Row for the vertex at theta = pi/2 (index 6 of 24), via the same
    // pipeline a pointer hover uses.
    const hit = { g, index: 6, trace: g.trace.id, synthetic: true };
    const row = view._localRow(hit);
    const items = view._tooltipItems(row);
    document.body.setAttribute("data-xy-polar-tooltip", JSON.stringify(items));
  } catch (error) {
    document.body.setAttribute("data-xy-polar-tooltip-error", String(error));
  }
}, 220);
</script>
"""
    items = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_tooltip_line.html",
        "data-xy-polar-tooltip",
        label="polar tooltip content",
    )
    assert items[0] == {"kind": "title", "value": "gain"}
    assert not any(i.get("label") == "θ" for i in items), (
        f"a numeric angle is layout, not data, and must not show by default: {items}"
    )
    assert any(i.get("label") == "r" for i in items), items


def test_polar_tooltip_angle_row_is_opt_in(tmp_path: Path) -> None:
    """Naming the row brings the angle back, formatted through the axis's own
    text function — so a radians chart reads "π/2", not "1.5708"."""
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    theta = [i * 2.0 * math.pi / 24.0 for i in range(24)]
    r = [1.0 + 0.4 * math.sin(3.0 * t) for t in theta]
    chart = xy.polar_chart(
        xy.line(theta, r, name="gain", animation=False),
        xy.tooltip(labels={"x": "bearing"}),
        width=420,
        height=400,
    )
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    const g = view.gpuTraces[0];
    const row = view._localRow({ g, index: 6, trace: g.trace.id, synthetic: true });
    document.body.setAttribute("data-xy-opt-in", JSON.stringify(view._tooltipItems(row)));
  } catch (error) {
    document.body.setAttribute("data-xy-opt-in-error", String(error));
  }
}, 220);
</script>
"""
    items = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_tooltip_optin.html",
        "data-xy-opt-in",
        label="polar tooltip opt-in angle",
    )
    angle = next(i for i in items if i.get("label") == "bearing")
    assert angle["value"] == "π/2", items


def test_polar_tooltip_degrees_and_radar_labels(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.radar_chart(
        ["speed", "power", "range", "agility"],
        xy.area([0.9, 0.7, 0.5, 0.8], name="Model A"),
        width=420,
        height=400,
    )
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    const g = view.gpuTraces[0];
    // Vertex 1 sits on the "power" spoke (pi/2 of a 4-category radar).
    const row = view._localRow({ g, index: 1, trace: g.trace.id, synthetic: true });
    const items = view._tooltipItems(row);
    document.body.setAttribute("data-xy-radar-tooltip", JSON.stringify(items));
  } catch (error) {
    document.body.setAttribute("data-xy-radar-tooltip-error", String(error));
  }
}, 220);
</script>
"""
    items = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_tooltip_radar.html",
        "data-xy-radar-tooltip",
        label="radar tooltip content",
    )
    assert items[0] == {"kind": "title", "value": "Model A"}
    theta_item = next(i for i in items if i.get("label") == "θ")
    assert theta_item["value"] == "power", items


def test_client_keeps_explicit_theta_ticks_across_the_seam(tmp_path: Path) -> None:
    """The client mirror of the seam-crossing tick window (_svg.py
    `_tick_window_filter`). `_axisTicks` trimmed authored angular ticks with a
    linear `v >= a && v <= b`, so a sector spanning 0/turn silently dropped
    every spoke on the far side of the seam while marks at those same angles
    still drew — the renderers must agree on what a sector contains."""
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.polar_chart(
        xy.line([310.0, 350.0, 30.0, 50.0], [1.0, 2.0, 3.0, 2.0]),
        xy.theta_axis(
            unit="degrees",
            sector=(300.0, 420.0),
            tick_values=[300.0, 330.0, 0.0, 30.0, 60.0],
        ),
        width=420,
        height=420,
    )
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    const seam = view._axisTicks("x", 6).ticks.slice();
    // A non-seam sector must still reject what lies outside it, and a
    // Cartesian axis must not wrap at all.
    const axis = view._axis("x");
    const realSector = axis.sector;
    axis.sector = [0, 180];
    axis.tick_values = [0, 45, 90, 200, -10];
    const bounded = view._axisTicks("x", 6).ticks.slice();
    axis.sector = realSector;
    const radial = view._axisTicks("y", 6).ticks.slice();
    document.body.setAttribute(
      "data-xy-seam-ticks", JSON.stringify({ seam, bounded, radialCount: radial.length }));
  } catch (error) {
    document.body.setAttribute("data-xy-seam-ticks-error", String(error));
  }
}, 220);
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_seam_ticks.html",
        "data-xy-seam-ticks",
        label="polar seam ticks",
    )
    assert result["seam"] == [300.0, 330.0, 0.0, 30.0, 60.0]
    assert result["bounded"] == [0.0, 45.0, 90.0]
    assert result["radialCount"] > 0


def test_polar_rect_hover_span_matches_the_drawn_wedge(tmp_path: Path) -> None:
    """`_rectHover`'s polar containment measured a *directional* span,
    `mod(x1 - x0, turn)`, while anchoring the offset at `min(x0, x1)`. Both
    renderers draw the band as the direct unwrapped interval between the edges
    (GLSL `abs(a1 - a0)`; `_PolarProjection.wedge_angles` `min..max`), so edge
    order carries no meaning — and the mismatch made a descending pair
    (350, 300) report a 310-wide wedge covering 300..610 instead of 300..350,
    and a 350/10 pair hoverable only outside itself."""
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.polar_chart(
        xy.bar([30.0], [1.0], width=10.0),
        xy.theta_axis(unit="degrees"),
        width=420,
        height=420,
    )
    probe = """
<script>
setTimeout(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    const meta = { scale: 1, offset: 0 };
    const wedge = (x0, x1) => ({
      trace: { id: 42 }, n: 1,
      _cpuRect: {
        x0: [x0], x1: [x1], y0: [0], y1: [1],
        x0Meta: meta, x1Meta: meta, y0Meta: meta, y1Meta: meta,
      },
    });
    const hits = (x0, x1, theta) => !!view._rectHover(wedge(x0, x1), theta, 0.5);
    document.body.setAttribute("data-xy-rect-span", JSON.stringify({
      // Descending pair: the wedge is 300..350 either way round.
      descIn: hits(350, 300, 320), descOut: hits(350, 300, 20),
      // Ascending control.
      ascIn: hits(300, 350, 320), ascOut: hits(300, 350, 20),
      // Wide wedge (>180 deg) must stay reachable at its middle.
      wideIn: hits(0, 270, 200), wideOut: hits(0, 270, 300),
      // Seam-crossing bar: edges are emitted unwrapped (-15..15).
      seamIn: hits(-15, 15, 355), seamAlsoIn: hits(-15, 15, 5),
      seamOut: hits(-15, 15, 180),
    }));
  } catch (error) {
    document.body.setAttribute("data-xy-rect-span-error", String(error));
  }
}, 220);
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "polar_rect_span.html",
        "data-xy-rect-span",
        label="polar rect hover span",
    )
    assert result["descIn"] and not result["descOut"], result
    assert result["ascIn"] and not result["ascOut"], result
    assert result["wideIn"] and not result["wideOut"], result
    assert result["seamIn"] and result["seamAlsoIn"] and not result["seamOut"], result
