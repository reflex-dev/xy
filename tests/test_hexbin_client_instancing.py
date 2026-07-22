"""Real-browser guardrails for the compact instanced hexbin renderer.

The wire already contains one center and one scalar per occupied cell.  These
probes make that same O(cells) shape observable at the GPU boundary and cover
the context-loss rebuild that must recreate the dedicated program and buffers.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'

_PROBE = r"""
  (async () => {
    const proto = WebGL2RenderingContext.prototype;
    const originalDraw = proto.drawArraysInstanced;
    const draws = [];
    proto.drawArraysInstanced = function(mode, first, count, instances) {
      draws.push({mode, first, count, instances});
      return originalDraw.call(this, mode, first, count, instances);
    };
    try {
      const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
      if (view._raf) cancelAnimationFrame(view._raf);
      view._raf = null;
      view._drawNow();
      view.gl.finish();
      proto.drawArraysInstanced = originalDraw;

      const trace = spec.traces.find((item) => item.kind === "hexbin");
      const g = view.gpuTraces.find((item) => item.trace.kind === "hexbin");
      if (!trace || !g) throw new Error("missing hexbin trace");

      const bufferBytes = (gl, buffer) => {
        const prior = gl.getParameter(gl.ARRAY_BUFFER_BINDING);
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        const size = gl.getBufferParameter(gl.ARRAY_BUFFER, gl.BUFFER_SIZE);
        gl.bindBuffer(gl.ARRAY_BUFFER, prior);
        return size;
      };
      const residentBytes = (gl, record) =>
        [record.xBuf, record.yBuf, record.cBuf].reduce(
          (total, buffer) => total + (buffer ? bufferBytes(gl, buffer) : 0), 0);
      const pixels = (recordView) => {
        recordView._drawNow();
        const gl = recordView.gl;
        gl.finish();
        const values = new Uint8Array(recordView.canvas.width * recordView.canvas.height * 4);
        gl.readPixels(0, 0, recordView.canvas.width, recordView.canvas.height,
          gl.RGBA, gl.UNSIGNED_BYTE, values);
        let hash = 2166136261, lit = 0;
        for (let i = 0; i < values.length; i += 4) {
          if (values[i] || values[i + 1] || values[i + 2] || values[i + 3]) lit++;
          hash ^= values[i]; hash = Math.imul(hash, 16777619);
          hash ^= values[i + 1]; hash = Math.imul(hash, 16777619);
          hash ^= values[i + 2]; hash = Math.imul(hash, 16777619);
          hash ^= values[i + 3]; hash = Math.imul(hash, 16777619);
        }
        return {hash: hash >>> 0, lit};
      };
      const gl = view.gl;
      const expectedBytes = g.n * 3 * Float32Array.BYTES_PER_ELEMENT;
      const beforeBytes = residentBytes(gl, g);
      view._zoomAt(0.72, 0.4, 0.6, false, 0);
      const beforePixels = pixels(view);
      const oldBuffers = [g.xBuf, g.yBuf, g.cBuf];
      const oldProgram = view._progCache.get("hexbin");
      const fanDraw = draws.find((draw) =>
        draw.mode === gl.TRIANGLES && draw.first === 0 &&
        draw.count === 18 && draw.instances === g.n);
      const legacyNames = ["x0Buf", "x1Buf", "x2Buf", "y0Buf", "y1Buf", "y2Buf"];
      const legacyFanAbsent = legacyNames.every((name) => !g[name]);
      const compatibilityUnchanged = !view._pickable && !view.pickFbo &&
        view._hoverAt(view.plot.w / 2, view.plot.h / 2) === null;

      // Context restoration calls _initGl(_payload) after the driver invalidates
      // every old handle.  Exercise that same retained-payload rebuild seam
      // deterministically: --dump-dom Chromium does not dispatch the optional
      // WEBGL_lose_context event, while explicit teardown also lets us prove
      // the prior handles were retired instead of leaked.
      view._destroyGlResources();
      const oldBuffersDeleted = oldBuffers.every((buffer) => !gl.isBuffer(buffer));
      // Program deletion is deferred while it is current; DELETE_STATUS proves
      // teardown requested retirement even if isProgram() remains true until
      // the restored draw binds its replacement.
      const oldProgramDeleteRequested = oldProgram &&
        gl.getProgramParameter(oldProgram, gl.DELETE_STATUS);
      view._initGl(view._payload);
      const restored = view.gpuTraces.find((item) => item.trace.kind === "hexbin");
      const afterPixels = pixels(view);
      const afterBytes = residentBytes(view.gl, restored);
      const recreated = [restored.xBuf, restored.yBuf, restored.cBuf].every(
        (buffer, index) => buffer && buffer !== oldBuffers[index] && view.gl.isBuffer(buffer));
      const glError = view.gl.getError();

      document.body.setAttribute("data-xy-hexbin-instancing", JSON.stringify({
        cellCount: g.n,
        traceCellCount: trace.n_marks,
        beforeBytes,
        afterBytes,
        expectedBytes,
        fanDraw: !!fanDraw,
        legacyFanAbsent,
        compatibilityUnchanged,
        nonblank: beforePixels.lit > 0,
        restoredNonblank: afterPixels.lit > 0,
        exactRestore: beforePixels.hash === afterPixels.hash && beforePixels.lit === afterPixels.lit,
        recreated,
        oldBuffersDeleted,
        oldProgramDeleteRequested,
        programRecreated: view._progCache.has("hexbin") &&
          view._progCache.get("hexbin") !== oldProgram,
        glError,
      }));
    } catch (err) {
      proto.drawArraysInstanced = originalDraw;
      document.body.setAttribute(
        "data-xy-hexbin-instancing-error", String((err && err.stack) || err));
    }
  })();
"""


def _hexbin_html(axis_mode: str) -> str:
    # An occupied regular field gives the memory assertion enough cells to
    # catch accidental fan expansion while keeping the pixel hash deterministic.
    log_axes = axis_mode == "log-reversed"
    values = (
        np.linspace(0.25, 4.25, 45, dtype=np.float64)
        if log_axes
        else np.linspace(-2.0, 2.0, 45, dtype=np.float64)
    )
    x, y = np.meshgrid(values, values)
    extent = ((0.2, 4.3), (0.2, 4.3)) if log_axes else ((-2.1, 2.1), (-2.1, 2.1))
    chart = xy.hexbin_chart(
        xy.hexbin(
            x.ravel(),
            y.ravel(),
            gridsize=(44, 44),
            range=extent,
            mincnt=1,
            opacity=0.72,
            colormap="magma",
        ),
        xy.x_axis(type_="log" if log_axes else None, reverse=log_axes),
        xy.y_axis(type_="log" if log_axes else None),
        width=480,
        height=360,
    )
    document = chart.to_html()
    assert _RENDER_CALL in document
    return document


@pytest.mark.parametrize("axis_mode", ["linear", "log-reversed"])
def test_hexbin_uses_three_floats_per_cell_and_survives_gpu_resource_rebuild(
    tmp_path: Path, axis_mode: str
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    result = run_browser_probe(
        chromium,
        _hexbin_html(axis_mode).replace(_RENDER_CALL, _PROBE),
        tmp_path / f"hexbin_instancing_{axis_mode}.html",
        "data-xy-hexbin-instancing",
        label="instanced hexbin lifecycle probe",
    )

    assert result["cellCount"] == result["traceCellCount"]
    assert result["cellCount"] > 1000
    assert result["beforeBytes"] == result["expectedBytes"]
    assert result["afterBytes"] == result["expectedBytes"]
    assert result["glError"] == 0
    checks = (
        "fanDraw",
        "legacyFanAbsent",
        "compatibilityUnchanged",
        "nonblank",
        "restoredNonblank",
        "exactRestore",
        "recreated",
        "oldBuffersDeleted",
        "oldProgramDeleteRequested",
        "programRecreated",
    )
    assert [key for key in checks if result[key] is not True] == [], result
