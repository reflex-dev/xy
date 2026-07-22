"""Browser contract for allocation-stable line/area tier refinement."""

from __future__ import annotations

from pathlib import Path

import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'

_PROBE = """
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  const gl = view.gl;
  const realData = gl.bufferData.bind(gl);
  const realSub = gl.bufferSubData.bind(gl);
  let dataCalls = 0;
  let subCalls = 0;
  gl.bufferData = (...args) => { dataCalls++; return realData(...args); };
  gl.bufferSubData = (...args) => { subCalls++; return realSub(...args); };
  try {
    view._drawNow();
    const g = view.gpuTraces[0];
    const originalBuffers = [g.xBuf, g.yBuf, g.baseBuf];
    const update = (x, y, base) => view._onKernelMsg({
      type: "tier_update",
      seq: view.seq,
      traces: [{
        id: g.trace.id,
        x: { buf: 0, len: x.length, offset: 10, scale: 2 },
        y: { buf: 1, len: y.length, offset: 20, scale: 3 },
        base: { buf: 2, len: base.length, offset: 30, scale: 4 },
      }],
    }, [x.buffer, y.buffer, base.buffer]);
    const read = (buffer, n) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      const out = new Float32Array(n);
      gl.getBufferSubData(gl.ARRAY_BUFFER, 0, out);
      return [...out];
    };

    const x4 = new Float32Array([1, 2, 3, 4]);
    const y4 = new Float32Array([5, 6, 7, 8]);
    const b4 = new Float32Array([9, 10, 11, 12]);
    update(x4, y4, b4);
    const sameSizeUsedSubData = subCalls === 3 && dataCalls === 0;
    const sameSizeBytesExact = JSON.stringify(read(g.xBuf, 4)) === JSON.stringify([...x4])
      && JSON.stringify(read(g.yBuf, 4)) === JSON.stringify([...y4])
      && JSON.stringify(read(g.baseBuf, 4)) === JSON.stringify([...b4]);

    dataCalls = 0; subCalls = 0;
    const x5 = new Float32Array([2, 4, 6, 8, 10]);
    const y5 = new Float32Array([1, 3, 5, 7, 9]);
    const b5 = new Float32Array([-1, -2, -3, -4, -5]);
    update(x5, y5, b5);
    const changedSizeReallocated = dataCalls === 3 && subCalls === 0;
    const changedSizeBytesExact = JSON.stringify(read(g.xBuf, 5)) === JSON.stringify([...x5])
      && JSON.stringify(read(g.yBuf, 5)) === JSON.stringify([...y5])
      && JSON.stringify(read(g.baseBuf, 5)) === JSON.stringify([...b5]);

    dataCalls = 0; subCalls = 0;
    update(x5, y5, b5);
    const resizedStorageThenReused = subCalls === 3 && dataCalls === 0;
    const identitiesStable = originalBuffers[0] === g.xBuf
      && originalBuffers[1] === g.yBuf && originalBuffers[2] === g.baseBuf;
    const trackedSizesExact = [g.xBuf, g.yBuf, g.baseBuf].every((b) => b._fcBytes === 20);

    document.body.setAttribute("data-xy-tier-buffer-probe", JSON.stringify({
      sameSizeUsedSubData, sameSizeBytesExact, changedSizeReallocated,
      changedSizeBytesExact, resizedStorageThenReused, identitiesStable,
      trackedSizesExact,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-tier-buffer-probe-error", String((err && err.stack) || err));
  } finally {
    gl.bufferData = realData;
    gl.bufferSubData = realSub;
  }
"""


def test_tier_updates_reuse_only_exactly_sized_gpu_storage(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    chart = xy.chart(
        xy.area([0.0, 1.0, 2.0, 3.0], [1.0, 3.0, 2.0, 4.0], base=[0.0] * 4),
        width=480,
        height=320,
    )
    document = chart.to_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "tier-buffer-reuse.html",
        "data-xy-tier-buffer-probe",
        label="tier buffer-reuse probe",
    )
    assert result == {key: True for key in result}
