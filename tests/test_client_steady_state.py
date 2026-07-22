"""Real-browser guards for client steady-state caches and hover lookup cost."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'


def _run(tmp_path: Path, chart: xy.Chart, probe: str, attribute: str) -> dict:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    document = chart.to_html().replace(_RENDER_CALL, probe)
    assert document != chart.to_html()
    return run_browser_probe(
        chromium,
        document,
        tmp_path / f"{attribute}.html",
        attribute,
        label=attribute,
    )


_COLOR_CACHE_PROBE = r"""
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    if (view._raf) { cancelAnimationFrame(view._raf); view._raf = null; }
    const realAppend = view.root.appendChild.bind(view.root);
    let probes = 0;
    view.root.appendChild = function (node) {
      if (node && node.tagName === "SPAN" && node.style.display === "none") probes++;
      return realAppend(node);
    };
    const fallback = [0, 0, 0, 1];

    view._colorCache.clear();
    const first = view._parseColor("rgba(12,34,56,.5)", fallback);
    const second = view._parseColor("rgba(12,34,56,.5)", fallback);
    const oneProbeForRepeatedExpression = probes === 1 && first === second;

    view.root.style.setProperty("--xy-probe-color", "rgb(8, 16, 24)");
    view._colorCache.clear();
    probes = 0;
    const before = view._parseColor("var(--xy-probe-color)", fallback);
    view.root.style.setProperty("--xy-probe-color", "rgb(80, 96, 112)");
    const cached = view._parseColor("var(--xy-probe-color)", fallback);
    const cachedUntilRefresh = before === cached && probes === 1;
    const epoch = view._themeEpoch;
    view.refreshTheme();
    if (view._raf) { cancelAnimationFrame(view._raf); view._raf = null; }
    probes = 0;
    const refreshed = view._parseColor("var(--xy-probe-color)", fallback);
    const after = view._parseColor("var(--xy-probe-color)", fallback);
    const invalidatedOnThemeRefresh = view._themeEpoch === epoch + 1 &&
      probes === 1 && refreshed === after &&
      Math.round(refreshed[0] * 255) === 80 &&
      Math.round(refreshed[1] * 255) === 96 &&
      Math.round(refreshed[2] * 255) === 112;

    document.body.setAttribute("data-xy-color-cache", JSON.stringify({
      oneProbeForRepeatedExpression,
      cachedUntilRefresh,
      invalidatedOnThemeRefresh,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-color-cache-error", String((err && err.stack) || err));
  }
"""


def test_color_resolution_is_cached_per_view_until_theme_refresh(tmp_path: Path) -> None:
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0], [0.0, 1.0], color="rgba(12,34,56,.5)"),
        width=420,
        height=300,
    )
    result = _run(tmp_path, chart, _COLOR_CACHE_PROBE, "data-xy-color-cache")
    assert result == {key: True for key in result}


_HOVER_PROBE = r"""
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    if (view._raf) { cancelAnimationFrame(view._raf); view._raf = null; }
    const line = view.gpuTraces.find((g) => g.trace.kind === "line");
    const scatter = view.gpuTraces.find((g) => g.trace.kind === "scatter");
    if (!line || !scatter) throw new Error("probe traces missing");

    const xMeta = line._cpu.xMeta;
    const decode = (i) => line._cpu.x[i] / (xMeta.scale || 1) + xMeta.offset;
    const target = decode(Math.floor(line._cpu.x.length * 0.61)) + 0.17;
    let axisCalls = 0;
    const realAxisCoord = view._axisCoord.bind(view);
    view._axisCoord = function (...args) { axisCalls++; return realAxisCoord(...args); };
    const binaryIndex = view._nearestCpuIndex(line, target);
    const binaryAxisCalls = axisCalls;
    let expected = 0;
    for (let i = 1; i < line._cpu.x.length; i++) {
      if (Math.abs(decode(i) - target) < Math.abs(decode(expected) - target)) expected = i;
    }
    const binaryCorrect = binaryIndex === expected;
    const binaryWasLogarithmic = binaryAxisCalls < 32;

    line._transitionPrevXValues = new Float32Array(line._cpu.x);
    line._transitionPositionProgress = 0.5;
    axisCalls = 0;
    const transitionIndex = view._nearestCpuIndex(line, target);
    const transitionUsesSafeLinearFallback = transitionIndex === expected &&
      axisCalls >= Math.min(line._cpu.x.length, line.n);
    line._transitionPrevXValues = null;
    line._transitionPositionProgress = null;
    view._axisCoord = realAxisCoord;

    const kinds = [];
    const realNearest = view._nearestCpuIndex.bind(view);
    view._nearestCpuIndex = function (g, x) {
      kinds.push(g.trace.kind);
      return realNearest(g, x);
    };
    // Populate per-trace pick ranges before simulating a working GPU miss.
    view._pickAt(-5, -5);
    view._hoverAt(view.plot.w * 0.5, view.plot.h * 0.8, true);
    const gpuMissSkipsPointCpuScan = !kinds.includes("scatter") && kinds.includes("line");
    kinds.length = 0;
    view._hoverAt(view.plot.w * 0.5, view.plot.h * 0.8, false);
    const noGpuPassKeepsScatterFallback = kinds.includes("scatter");
    kinds.length = 0;
    view._glLost = true;
    view._hoverAt(view.plot.w * 0.5, view.plot.h * 0.8, true);
    const lostContextKeepsScatterFallback = kinds.includes("scatter");
    view._glLost = false;
    view._nearestCpuIndex = realNearest;

    let picks = 0, fallbacks = 0;
    const realPick = view._pickAt;
    const realHoverAt = view._hoverAt;
    view._pickAt = () => { picks++; return null; };
    view._hoverAt = () => { fallbacks++; return null; };
    view._lastHoverPixel = null;
    const rect = view.canvas.getBoundingClientRect();
    const event = (dx) => ({clientX: rect.left + 70 + dx, clientY: rect.top + 80});
    view._hover(event(0));
    const afterFirst = [picks, fallbacks];
    view._hover(event(0.1 / view.dpr));
    const sameDevicePixelReusesMiss = picks === afterFirst[0] && fallbacks === afterFirst[1];
    view._hover(event(2 / view.dpr));
    const nextDevicePixelRepicks = picks === afterFirst[0] + 1 &&
      fallbacks === afterFirst[1] + 1;
    view._pickAt = realPick;
    view._hoverAt = realHoverAt;

    document.body.setAttribute("data-xy-hover-cache", JSON.stringify({
      binaryCorrect,
      binaryWasLogarithmic,
      transitionUsesSafeLinearFallback,
      gpuMissSkipsPointCpuScan,
      noGpuPassKeepsScatterFallback,
      lostContextKeepsScatterFallback,
      sameDevicePixelReusesMiss,
      nextDevicePixelRepicks,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-hover-cache-error", String((err && err.stack) || err));
  }
"""


def test_hover_uses_gpu_miss_guard_binary_line_search_and_pixel_cache(tmp_path: Path) -> None:
    n = 8192
    x = np.arange(n, dtype=np.float64)
    chart = xy.chart(
        xy.scatter(x, np.full(n, 50.0), density=False),
        xy.line(x, np.sin(x * 0.002), width=1.5),
        xy.x_axis(),
        xy.y_axis(),
        width=520,
        height=340,
        hover=True,
    )
    result = _run(tmp_path, chart, _HOVER_PROBE, "data-xy-hover-cache")
    assert result == {key: True for key in result}


_DRAW_CACHE_PROBE = r"""
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    if (view._raf) { cancelAnimationFrame(view._raf); view._raf = null; }
    const line = view.gpuTraces.find((g) => g.trace.kind === "line");
    const segments = view.gpuTraces.find((g) => g.trace.kind === "segments");
    if (!line || !segments) throw new Error("dashed traces missing");
    // Segment dashes are generated internally by contours. Set the equivalent
    // renderer state directly so this focused client probe covers that cache
    // without depending on a public segments-style spelling.
    segments.trace.style.dash = [5, 2];
    view._drawNow();
    if (view._raf) { cancelAnimationFrame(view._raf); view._raf = null; }
    const gl = view.gl;
    const realBufferData = gl.bufferData.bind(gl);
    let uploads = 0;
    gl.bufferData = function (...args) { uploads++; return realBufferData(...args); };

    const firstLabel = view.labels.firstChild;
    view._drawNow();
    const steadyDashUploads = uploads;
    const steadyLabelsKeepIdentity = !!firstLabel && view.labels.firstChild === firstLabel;

    const ranges = Object.fromEntries(view._axisIds().map((id) => [id, [...view._axisRange(id)]]));
    const xRange = ranges.x;
    const span = xRange[1] - xRange[0];
    ranges.x = [xRange[0] + span * 0.08, xRange[1] - span * 0.08];
    view.view = view._copyView({ranges});
    uploads = 0;
    view._drawNow();
    const changedViewReuploadsDashGeometry = uploads >= 3;
    const changedViewRebuildsLabels = view.labels.firstChild !== firstLabel;

    uploads = 0;
    view._drawNow();
    const warmedViewHasNoDashUploads = uploads === 0;
    line._dashX = new Float32Array(line._dashX);
    uploads = 0;
    view._drawNow();
    const changedGeometryInvalidatesDash = uploads >= 1;

    let now = 1000;
    view._now = () => now;
    view._lastLabelDraw = now;
    const beforeThrottle = view.labels.firstChild;
    const moving = Object.fromEntries(view._axisIds().map((id) => [id, [...view._axisRange(id)]]));
    moving.x = [moving.x[0] + span * 0.01, moving.x[1] + span * 0.01];
    view.view = view._copyView({ranges: moving});
    view._viewMutationActive = true;
    now += 10;
    view._drawNow();
    const activeGestureThrottlesLabels = view.labels.firstChild === beforeThrottle;
    now += 80;
    view._drawNow();
    const cadenceEventuallyRefreshesLabels = view.labels.firstChild !== beforeThrottle;
    const beforeSettle = view.labels.firstChild;
    moving.x = [moving.x[0] + span * 0.01, moving.x[1] + span * 0.01];
    view.view = view._copyView({ranges: moving});
    view._viewMutationActive = false;
    now += 1;
    view._drawNow();
    const settledViewRefreshesImmediately = view.labels.firstChild !== beforeSettle;

    const dashBuffers = [line._lenBuf, segments._segmentDashOffsetBuf,
      segments._segmentDashDirBuf].filter(Boolean);
    const deleted = new Set();
    const realDeleteBuffer = gl.deleteBuffer.bind(gl);
    gl.deleteBuffer = function (buffer) {
      if (dashBuffers.includes(buffer)) deleted.add(buffer);
      return realDeleteBuffer(buffer);
    };
    gl.bufferData = realBufferData;
    view.destroy();
    const destroyDeletesDashBuffers = dashBuffers.length === 3 &&
      dashBuffers.every((buffer) => deleted.has(buffer));

    document.body.setAttribute("data-xy-draw-cache", JSON.stringify({
      steadyDashUploadsAreZero: steadyDashUploads === 0,
      steadyLabelsKeepIdentity,
      changedViewReuploadsDashGeometry,
      changedViewRebuildsLabels,
      warmedViewHasNoDashUploads,
      changedGeometryInvalidatesDash,
      activeGestureThrottlesLabels,
      cadenceEventuallyRefreshesLabels,
      settledViewRefreshesImmediately,
      destroyDeletesDashBuffers,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-draw-cache-error", String((err && err.stack) || err));
  }
"""


def test_dash_and_label_caches_invalidate_and_release_resources(tmp_path: Path) -> None:
    x = np.linspace(0.0, 100.0, 4096)
    chart = xy.chart(
        xy.line(x, np.sin(x), dash=(6.0, 3.0)),
        xy.segments(
            [10.0, 30.0, 50.0],
            [-1.0, -0.5, 0.0],
            [20.0, 40.0, 60.0],
            [0.0, 0.5, 1.0],
        ),
        xy.x_axis(label="x"),
        xy.y_axis(label="y"),
        width=520,
        height=340,
    )
    result = _run(tmp_path, chart, _DRAW_CACHE_PROBE, "data-xy-draw-cache")
    assert result == {key: True for key in result}
