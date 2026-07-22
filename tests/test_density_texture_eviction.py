"""Density-cache eviction must never free a texture still referenced by the trace.

The tiered density renderer keeps a small LRU of grid textures per trace and
deletes the texture of any entry it evicts. Eviction pins the live references
(active grid, previous grid, crossfade source) — but `_shownDensity`, the grid
the tier last drew and the *next* crossfade source, was missing from that set.
Its texture could be freed while still referenced; the following crossfade then
bound the deleted handle ("bindTexture: attempt to use a deleted object"),
aborting the density draw and stranding drilled points over a stale surface.

This drives the real client in headless Chromium: it fills the cache past its
cap with large-area grids while `_shownDensity` points at a small-area grid
(the natural eviction target), then checks that grid's texture survived and that
drawing it raises no GL error.
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
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow(); view._raf = null;
    const gl = view.gl;
    const g = view.gpuTraces.find((t) => t.tier === "density");
    const GL_INVALID_OPERATION = 0x0502;

    const mkTex = () => {
      const t = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, 2, 2, 0, gl.RED, gl.UNSIGNED_BYTE,
        new Uint8Array([1, 2, 3, 4]));
      return t;
    };
    // Distinct grids that differ only in covered area (drives LRU's area rule).
    const mkDensity = (side) => ({
      w: 2, h: 2, max: 1, normMax: 1,
      tex: mkTex(), lut: g.density.lut, colormap: "viridis",
      xRange: [0, side], yRange: [0, side],
    });

    // A small-area grid becomes what the tier "last drew": in the cache, live
    // via _shownDensity, but not the active/previous/crossfade grid.
    const shown = mkDensity(0.02);
    view._applySampleRebinGrid(g, shown, true);
    g._shownDensity = shown;

    // Fill well past the cap (8) with much larger grids so `shown` is the LRU
    // eviction target on area. Without the pin its texture gets freed here.
    for (let i = 0; i < 12; i++) view._applySampleRebinGrid(g, mkDensity(100 + i), true);

    const shownTexAlive = gl.isTexture(shown.tex);
    const inCache = (g.densityCache || []).includes(shown);
    const computedCacheBytes = (g.densityCache || []).reduce(
      (total, density) => total
        + (density.encoded?.byteLength || 0) + (density.grid?.byteLength || 0), 0,
    );
    const compactCache = (g.densityCache || []).every(
      (density) => !("encoded" in density) && !("grid" in density),
    );

    // Drawing the retained (crossfade-source) grid must not raise a GL error.
    while (gl.getError() !== gl.NO_ERROR) { /* drain */ }
    view._drawDensity(g, shown);
    const drawError = gl.getError();

    document.body.setAttribute("data-tex-probe", JSON.stringify({
      hasDensity: !!g,
      shownTexAlive,
      inCache,
      cacheEntries: g.densityCache.length,
      cacheBytes: g.densityCacheBytes,
      computedCacheBytes,
      compactCache,
      drawError,
      invalidOp: drawError === GL_INVALID_OPERATION,
    }));
  } catch (err) {
    document.body.setAttribute("data-tex-probe-error", String((err && err.stack) || err));
  }
"""


def _density_html() -> str:
    rng = np.random.default_rng(0)
    n = 40_000
    x = rng.normal(0.0, 1.0, n)
    y = rng.normal(0.0, 1.0, n)
    chart = xy.scatter_chart(
        xy.scatter(x, y, density=True),
        xy.x_axis(),
        xy.y_axis(),
        width=480,
        height=360,
    )
    html = chart.to_html()
    assert _RENDER_CALL in html
    return html


def test_density_cache_eviction_keeps_shown_texture(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    document = _density_html().replace(_RENDER_CALL, _PROBE)
    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "tex_evict.html",
        "data-tex-probe",
        label="density texture eviction probe",
    )

    assert result["hasDensity"] is True
    # The pin keeps `_shownDensity` in the cache and its texture alive through
    # eviction; the pre-fix bug freed it (isTexture false) and left it evicted.
    assert result["inCache"] is True
    assert result["shownTexAlive"] is True
    assert result["cacheEntries"] <= 8
    assert result["compactCache"] is True
    assert result["cacheBytes"] == result["computedCacheBytes"]
    assert result["cacheBytes"] == 0
    # Drawing the retained grid raises no "deleted object" error.
    assert result["invalidOp"] is False, result
    assert result["drawError"] == 0, result
