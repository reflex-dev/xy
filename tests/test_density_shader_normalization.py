"""Density exposure stays CPU-cache-free and upload-free while it animates.

The wire provides log-u8 source texels and the cache keeps only R8 textures. A shader-side normalization
factor must preserve the old rendering order: normalize/round/clamp each of
the four source texels first, then bilinearly interpolate them.  Scaling one
already-interpolated value is observably different around rounding and
saturation boundaries.

The browser probe exercises the real committed standalone bundle.  It checks
pixel-exact parity against a CPU-prequantized reference texture, drives 61
normalization frames while spying on ``texImage2D``, applies a transient worker
result, restores the pinned home grid without an upload, and audits cache bytes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

ROOT = Path(__file__).resolve().parents[1]
_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'

_PROBE = r"""
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    const gl = view.gl;
    const g = view.gpuTraces.find((trace) => trace.tier === "density");
    const density = g.density;
    // Isolate the aggregate surface; the retained point sample is unrelated to
    // normalization and could hide a one-pixel density mismatch beneath it.
    g.sampleOverlay = null;
    g.drill = null;
    g.prevDensity = null;
    g._densitySwitchPrev = null;
    g._densitySwitchFadeStart = null;
    g._shownDensity = density;
    g._densityNormAnim = null;

    const pixels = () => {
      const out = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
      gl.finish();
      gl.readPixels(
        0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight,
        gl.RGBA, gl.UNSIGNED_BYTE, out,
      );
      return out;
    };
    const hash = (data) => {
      let value = 2166136261 >>> 0;
      for (let i = 0; i < data.length; i++) {
        value ^= data[i];
        value = Math.imul(value, 16777619) >>> 0;
      }
      return value;
    };
    const mismatchCount = (left, right) => {
      let mismatches = 0;
      for (let i = 0; i < left.length; i++) mismatches += left[i] !== right[i];
      return mismatches;
    };

    // Independent WebGL check: the shader's manual four-texel blend at
    // scale=1 must quantize to the same RGBA8 pixels as native LINEAR texture
    // sampling. This validates the half-texel coordinate/edge-clamp math, not
    // merely the normalization formula.
    const compile = (type, source) => {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        throw new Error(gl.getShaderInfoLog(shader));
      }
      return shader;
    };
    const link = (fragment) => {
      const vertex = compile(gl.VERTEX_SHADER, `#version 300 es
        layout(location=0) in vec2 a_corner;
        out vec2 v_uv;
        void main(){ v_uv=a_corner; gl_Position=vec4(a_corner*2.0-1.0,0.0,1.0); }`);
      const pixel = compile(gl.FRAGMENT_SHADER, fragment);
      const program = gl.createProgram();
      gl.attachShader(program, vertex);
      gl.attachShader(program, pixel);
      gl.linkProgram(program);
      gl.deleteShader(vertex);
      gl.deleteShader(pixel);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(program));
      }
      return program;
    };
    const linearProgram = link(`#version 300 es
      precision highp float;
      uniform sampler2D u_grid;
      in vec2 v_uv; out vec4 outColor;
      void main(){ float t=texture(u_grid,v_uv).r; outColor=vec4(t,t,t,1.0); }`);
    const manualProgram = link(`#version 300 es
      precision highp float;
      uniform sampler2D u_grid;
      in vec2 v_uv; out vec4 outColor;
      float value(ivec2 p){
        float q=floor(texelFetch(u_grid,p,0).r*255.0+0.5);
        return q/255.0;
      }
      float sampleGrid(vec2 uv){
        ivec2 size=textureSize(u_grid,0), last=size-ivec2(1);
        vec2 position=uv*vec2(size)-0.5, amount=fract(position);
        ivec2 lo=ivec2(floor(position)), hi=lo+ivec2(1);
        ivec2 p00=clamp(lo,ivec2(0),last);
        ivec2 p10=clamp(ivec2(hi.x,lo.y),ivec2(0),last);
        ivec2 p01=clamp(ivec2(lo.x,hi.y),ivec2(0),last);
        ivec2 p11=clamp(hi,ivec2(0),last);
        return mix(mix(value(p00),value(p10),amount.x),
                   mix(value(p01),value(p11),amount.x),amount.y);
      }
      void main(){ float t=sampleGrid(v_uv); outColor=vec4(t,t,t,1.0); }`);
    const sampleTexture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, sampleTexture);
    const sampleBytes = new Uint8Array([
      0, 1, 17, 63, 129, 233, 255,
      7, 31, 92, 151, 201, 14, 87,
      255, 180, 111, 55, 22, 3, 0,
      4, 47, 99, 144, 188, 222, 250,
      13, 77, 123, 169, 211, 245, 6,
    ]);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, 7, 5, 0, gl.RED, gl.UNSIGNED_BYTE, sampleBytes);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const outputTexture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, outputTexture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 59, 43, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    const framebuffer = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
    gl.framebufferTexture2D(
      gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, outputTexture, 0,
    );
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
      throw new Error("density sampling parity framebuffer incomplete");
    }
    const sampleWith = (program) => {
      gl.viewport(0, 0, 59, 43);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(program);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, sampleTexture);
      gl.uniform1i(gl.getUniformLocation(program, "u_grid"), 0);
      gl.bindVertexArray(view.quadVao);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      const out = new Uint8Array(59 * 43 * 4);
      gl.readPixels(0, 0, 59, 43, gl.RGBA, gl.UNSIGNED_BYTE, out);
      return out;
    };
    const nativeLinearPixels = sampleWith(linearProgram);
    const manualLinearPixels = sampleWith(manualProgram);
    const linearParityMismatches = mismatchCount(nativeLinearPixels, manualLinearPixels);
    let linearMaxDelta = 0;
    for (let i = 0; i < nativeLinearPixels.length; i++) {
      linearMaxDelta = Math.max(
        linearMaxDelta, Math.abs(nativeLinearPixels[i] - manualLinearPixels[i]),
      );
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.deleteFramebuffer(framebuffer);
    gl.deleteTexture(outputTexture);
    gl.deleteTexture(sampleTexture);
    gl.deleteProgram(linearProgram);
    gl.deleteProgram(manualProgram);

    // First paint's canonical payload already owns the wire bytes. Density
    // cache entries intentionally retain no second CPU-side source.
    const sourceBytes = view._columnView(
      view._payload, view.spec.columns[g.trace.density.buf],
    ).slice();
    const sourceMax = density.max;
    // Pick an exactly representable 0.75 scale.  q * 0.75 deliberately lands
    // on .5 for many source bytes, covering Math.round/floor(x + .5) parity.
    const referenceNorm = Math.expm1(Math.log1p(sourceMax) / 0.75);
    const scale = Math.log1p(sourceMax) / Math.log1p(referenceNorm);
    const shaderScale = Math.fround(scale); // uniform1f precision
    const requantized = new Uint8Array(sourceBytes.length);
    for (let i = 0; i < sourceBytes.length; i++) {
      const q = sourceBytes[i];
      requantized[i] = q === 0
        ? 0
        : Math.max(1, Math.min(255, Math.round(q * shaderScale)));
    }

    // New path: source bytes stay untouched; a scalar drives per-texel shader
    // requantization followed by manual bilinear interpolation.
    density.normMax = referenceNorm;
    g.densityNormMax = referenceNorm;
    view._drawNow();
    const shaderPixels = pixels();

    // Reference path: upload the bytes the former CPU path would have created,
    // then render at scale=1.  Both paths pass through the exact same LUT,
    // blending, clipping, and chart geometry; equality is full-frame parity.
    const sourceTexture = density.tex;
    const referenceTexture = view._uploadDensityGrid(
      requantized, density.w, density.h,
    );
    density.tex = referenceTexture;
    density.max = referenceNorm;
    density.normMax = referenceNorm;
    view._drawNow();
    const referencePixels = pixels();
    const parityMismatches = mismatchCount(shaderPixels, referencePixels);
    gl.deleteTexture(referenceTexture);
    density.tex = sourceTexture;
    density.max = sourceMax;

    // Count all texture allocations after this point. Normalization animation
    // should produce 61 rendered frames and exactly zero texImage2D calls.
    const realTexImage2D = gl.texImage2D.bind(gl);
    let texImageCalls = 0;
    gl.texImage2D = (...args) => {
      texImageCalls += 1;
      return realTexImage2D(...args);
    };
    const realNow = view._now;
    const realDraw = view.draw;
    let clock = 0;
    view._now = () => clock;
    view.draw = () => {};
    const startNorm = Math.expm1(Math.log1p(sourceMax) / 0.5);
    density.normMax = startNorm;
    g.densityNormMax = startNorm;
    g._densityNormAnim = {
      start: startNorm,
      target: sourceMax,
      startedAt: 0,
      duration: 420,
    };
    const animationStarted = performance.now();
    let firstHash = 0;
    let lastHash = 0;
    for (let frame = 0; frame <= 60; frame++) {
      clock = 420 * frame / 60;
      view._drawNow();
      const frameHash = hash(pixels());
      if (frame === 0) firstHash = frameHash;
      if (frame === 60) lastHash = frameHash;
    }
    const animationMs = performance.now() - animationStarted;
    const animationTexUploads = texImageCalls;
    const animationCompleted = g._densityNormAnim === null
      && density.normMax === sourceMax;

    // Simulate the compact result emitted by 46_worker.ts. Applying it uploads
    // the transient u8 source once and retains no CPU grid in the window cache.
    texImageCalls = 0;
    const workerBytes = new Uint8Array([
      0, 1, 9, 32,
      2, 18, 64, 127,
      3, 28, 96, 180,
      4, 40, 160, 255,
    ]);
    const realUploadDensityGrid = view._uploadDensityGrid;
    let workerUploadBytes = null;
    view._uploadDensityGrid = (bytes, w, h) => {
      workerUploadBytes = bytes.slice();
      return realUploadDensityGrid.call(view, bytes, w, h);
    };
    view._onRebinResult({
      type: "grid",
      seq: view.seq,
      trace: g.trace.id,
      w: 4,
      h: 4,
      max: 37,
      enc: "log-u8",
      x0: view.view0.x0,
      x1: view.view0.x1,
      y0: view.view0.y0,
      y1: view.view0.y1,
      grid: workerBytes.buffer,
    });
    view._uploadDensityGrid = realUploadDensityGrid;
    const workerDensity = g.density;
    const workerTexUploads = texImageCalls;
    const compactWorker = workerUploadBytes instanceof Uint8Array
      && workerUploadBytes.byteLength === 16
      && !("encoded" in workerDensity) && !("grid" in workerDensity);

    // The overview is pinned by `_homeDensity`; a pan/home restore reuses its
    // original texture instead of re-uploading a clone.
    g._homeDensity = density;
    texImageCalls = 0;
    view._requestSampleRebin(g, view.view0, view.seq);
    const homeReused = g.density === density && density.tex === sourceTexture;
    const homeRestoreTexUploads = texImageCalls;

    const computedCacheBytes = g.densityCache.reduce(
      (total, item) => total
        + (item.encoded?.byteLength || 0) + (item.grid?.byteLength || 0), 0,
    );
    const compactCache = g.densityCache.every(
      (item) => !("encoded" in item) && !("grid" in item),
    );

    view._now = realNow;
    view.draw = realDraw;
    gl.texImage2D = realTexImage2D;
    document.body.setAttribute("data-density-norm-probe", JSON.stringify({
      hasDensity: !!g,
      sourceCompact: sourceBytes instanceof Uint8Array
        && !("encoded" in density) && !("grid" in density),
      linearParityMismatches,
      linearMaxDelta,
      parityMismatches,
      animationFrames: 61,
      animationMs,
      animationTexUploads,
      animationChangedPixels: firstHash !== lastHash,
      animationCompleted,
      workerTexUploads,
      compactWorker,
      homeReused,
      homeRestoreTexUploads,
      cacheEntries: g.densityCache.length,
      cacheBytes: g.densityCacheBytes,
      computedCacheBytes,
      compactCache,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-density-norm-probe-error",
      String((err && err.stack) || err),
    );
  }
"""

_CONTEXT_PROBE = r"""
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  (async () => {
    try {
      view._sampleRebinDisabled = true;
      let densityTrace = view.gpuTraces.find((trace) => trace.tier === "density");
      densityTrace.sampleOverlay = null;
      densityTrace._densityNormAnim = null;
      densityTrace.density.normMax = densityTrace.density.max;
      view._drawNow();
      const pixelHash = () => {
        const gl = view.gl;
        const data = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
        gl.finish();
        gl.readPixels(
          0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight,
          gl.RGBA, gl.UNSIGNED_BYTE, data,
        );
        let hash = 2166136261 >>> 0;
        for (let i = 0; i < data.length; i++) {
          hash ^= data[i];
          hash = Math.imul(hash, 16777619) >>> 0;
        }
        return hash;
      };
      const before = pixelHash();
      const ext = view.gl.getExtension("WEBGL_lose_context");
      if (!ext) throw new Error("WEBGL_lose_context unavailable");
      const event = (name) => new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error(`timeout waiting for ${name}`)), 2500);
        view.root.addEventListener(name, () => {
          clearTimeout(timeout);
          resolve();
        }, { once: true });
      });
      // Exercise the browser-eviction recovery arm: a real lost context cannot
      // be restored, so ChartView swaps the canvas and rebuilds from `_payload`.
      // Suppress its eager timer and invoke the same recovery method explicitly
      // after the loss event has completely unwound.
      view._ctxVisible = false;
      const lost = event("xy:context_lost");
      ext.loseContext();
      await lost;
      // Cross a task boundary so recovery never runs inside loss dispatch.
      await new Promise((resolve) => setTimeout(resolve, 0));
      view._recoverContext();
      if (view._glLost) throw new Error("fresh-canvas context rebuild failed");
      densityTrace = view.gpuTraces.find((trace) => trace.tier === "density");
      densityTrace.sampleOverlay = null;
      densityTrace._densityNormAnim = null;
      densityTrace.density.normMax = densityTrace.density.max;
      view._drawNow();
      const after = pixelHash();
      document.body.setAttribute("data-density-context-probe", JSON.stringify({
        restored: view._glLost === false && view.canvas.dataset.xyCtx === "live",
        lossCount: view._contextLossCount,
        recoveryCount: view._ctxRecoveries,
        pixelIdentical: before === after,
        compact: !("encoded" in densityTrace.density)
          && !("grid" in densityTrace.density),
        cacheBytes: densityTrace.densityCacheBytes,
        expectedBytes: 0,
      }));
    } catch (err) {
      document.body.setAttribute(
        "data-density-context-probe-error",
        String((err && err.stack) || err),
      );
    }
  })();
"""


def _density_html() -> str:
    rng = np.random.default_rng(166)
    n = 90_000
    x = np.r_[rng.normal(-1.1, 0.42, n // 2), rng.normal(1.2, 0.7, n // 2)]
    y = np.r_[rng.normal(0.8, 0.55, n // 2), rng.normal(-0.7, 0.35, n // 2)]
    chart = xy.scatter_chart(
        xy.scatter(x, y, density=True),
        xy.x_axis(),
        xy.y_axis(),
        width=360,
        height=280,
    )
    html = chart.to_html()
    assert _RENDER_CALL in html
    return html


def test_density_normalization_shader_contract_is_source_local() -> None:
    lod = (ROOT / "js/src/45_lod.ts").read_text(encoding="utf-8")
    shader = (ROOT / "js/src/40_gl.ts").read_text(encoding="utf-8")
    worker = (ROOT / "js/src/46_worker.ts").read_text(encoding="utf-8")
    kernel = (ROOT / "js/src/54_kernel.ts").read_text(encoding="utf-8")

    assert "lodDecodeLogU8" not in lod
    assert "lodCopyEncodedGrid" not in lod
    assert "Math.expm1" not in lod
    step = lod[lod.index("function lodStepNorm") : lod.index("// -- density-source cache")]
    assert "lodWriteGridTexture" not in step
    assert "d.normMax = norm" in step
    assert "texelFetch(u_grid" in shader
    assert "floor(encoded * u_normScale + 0.5)" in shader
    assert "float sampleDensity(vec2 uv)" in shader
    assert "u_normScale == 1.0 ? texture(u_grid, uv).r : sampleDensity(uv)" in shader
    assert 'enc: "log-u8"' in worker
    assert "grid: encoded.buffer" in worker
    assert "this._applySampleRebinGrid(g, g._homeDensity, false);" in kernel


def test_density_normalization_is_pixel_exact_and_upload_free(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        _density_html().replace(_RENDER_CALL, _PROBE),
        tmp_path / "density_shader_norm.html",
        "data-density-norm-probe",
        label="density shader normalization probe",
    )

    assert result["hasDensity"] is True
    assert result["sourceCompact"] is True
    assert result["linearParityMismatches"] == 0, result
    assert result["linearMaxDelta"] == 0, result
    assert result["parityMismatches"] == 0, result
    assert result["animationFrames"] == 61
    assert result["animationTexUploads"] == 0, result
    assert result["animationChangedPixels"] is True
    assert result["animationCompleted"] is True
    assert result["workerTexUploads"] == 1
    assert result["compactWorker"] is True
    assert result["homeReused"] is True
    assert result["homeRestoreTexUploads"] == 0
    assert result["cacheEntries"] <= 8
    assert result["compactCache"] is True
    assert result["cacheBytes"] == result["computedCacheBytes"]
    assert result["cacheBytes"] == 0
    assert result["animationMs"] > 0


def test_density_compact_source_survives_context_rebuild(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        _density_html().replace(_RENDER_CALL, _CONTEXT_PROBE),
        tmp_path / "density_context_restore.html",
        "data-density-context-probe",
        label="density compact context-restore probe",
    )

    assert result["restored"] is True
    assert result["lossCount"] == 1
    assert result["recoveryCount"] == 1
    assert result["pixelIdentical"] is True
    assert result["compact"] is True
    assert result["cacheBytes"] == result["expectedBytes"]
