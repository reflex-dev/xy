"""Production integration coverage for the document-scoped shared WebGL host.

These probes exercise ``ChartView`` and the JavaScript bundled by ``to_html``:
every chart is a real standalone view built from the same small payload, with a
visible Canvas2D presentation surface backed by one detached WebGL2 host.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest

import xy
from conftest import RENDER_CALLS, probe_document, run_browser_probe
from xy.export import find_chromium

ROOT = Path(__file__).resolve().parents[1]


def _chart_html(probe: str) -> str:
    chart = xy.scatter_chart(
        xy.scatter(
            [0.0, 0.5, 1.0],
            [0.0, 0.5, 1.0],
            size=10,
        ),
        width=62,
        height=82,
        padding=(4, 4, 4, 4),
    )
    document = chart.to_html()
    render_call = next((call for call in RENDER_CALLS if call in document), None)
    assert render_call is not None, "to_html render call shape changed; update RENDER_CALLS"
    return document.replace(render_call, probe, 1)


_FIFTY_VIEW_PROBE = r"""
  (() => {
    const originalGetContext = HTMLCanvasElement.prototype.getContext;
    let webgl2Acquisitions = 0;
    const webgl2Contexts = new Set();
    HTMLCanvasElement.prototype.getContext = function (kind, ...args) {
      const context = originalGetContext.call(this, kind, ...args);
      if (kind === "webgl2") {
        webgl2Acquisitions += 1;
        if (context) webgl2Contexts.add(context);
      }
      return context;
    };

    try {
      document.documentElement.style.cssText = "margin:0;width:640px;height:480px";
      document.body.style.cssText = "margin:0;width:640px;height:480px;overflow:hidden";
      const grid = document.getElementById("chart");
      grid.replaceChildren();
      grid.style.cssText = [
        "display:grid",
        "grid-template-columns:repeat(10,62px)",
        "grid-template-rows:repeat(5,82px)",
        "gap:2px",
        "width:638px",
        "height:418px",
      ].join(";");

      const views = [];
      for (let index = 0; index < 50; index++) {
        const holder = document.createElement("div");
        holder.dataset.xySharedProbe = String(index);
        holder.style.cssText = "width:62px;height:82px;overflow:hidden";
        grid.appendChild(holder);
        const view = xy.renderStandalone(holder, spec, buf);
        view._drawNow();
        view._raf = null;
        views.push(view);
      }

      const surface = (view) => {
        const context = view._present2d;
        if (!context || context.canvas !== view.canvas) {
          throw new Error("ChartView has no visible Canvas2D presentation surface");
        }
        if (view.canvas.getContext("2d") !== context) {
          throw new Error("visible chart canvas is not owned by _present2d");
        }
        const bounds = context.canvas.getBoundingClientRect();
        const pixels = context.getImageData(
          0,
          0,
          context.canvas.width,
          context.canvas.height,
        ).data;
        let nonzero = 0;
        let hash = 0x811c9dc5;
        for (let offset = 0; offset < pixels.length; offset++) {
          if (pixels[offset]) nonzero += 1;
          hash = Math.imul(hash ^ pixels[offset], 0x01000193) >>> 0;
        }
        return {
          nonzero,
          hash,
          connected: context.canvas.isConnected,
          inViewport:
            bounds.width > 0 &&
            bounds.height > 0 &&
            bounds.left >= 0 &&
            bounds.top >= 0 &&
            bounds.right <= window.innerWidth &&
            bounds.bottom <= window.innerHeight,
        };
      };
      const exercise = (view) => {
        view._drawNow();
        view._raf = null;
        const frame = surface(view);
        const hit = view._pickAt(view.plot.w / 2, view.plot.h / 2);
        return {
          frame,
          hit: hit ? [hit.trace, hit.index] : null,
        };
      };

      const hosts = new Set(views.map((view) => view._glHost));
      const surfaces = views.map(surface);
      const xBuffersBeforeAppend = views.map((view) => view.gpuTraces[0].xBuf);
      const a1 = exercise(views[0]);
      // Deliberately leave hostile context-global state behind. The next
      // virtual client must not inherit any of it.
      const poisonGl = views[0]._glHost.gl;
      const poisonTexture = poisonGl.createTexture();
      poisonGl.disable(poisonGl.BLEND);
      poisonGl.enable(poisonGl.DEPTH_TEST);
      poisonGl.enable(poisonGl.CULL_FACE);
      poisonGl.colorMask(false, false, false, false);
      poisonGl.frontFace(poisonGl.CW);
      poisonGl.viewport(1, 1, 1, 1);
      poisonGl.enable(poisonGl.SCISSOR_TEST);
      poisonGl.scissor(0, 0, 0, 0);
      poisonGl.blendEquation(poisonGl.FUNC_REVERSE_SUBTRACT);
      poisonGl.blendFunc(poisonGl.ZERO, poisonGl.ZERO);
      poisonGl.activeTexture(poisonGl.TEXTURE1);
      poisonGl.bindTexture(poisonGl.TEXTURE_2D, poisonTexture);
      const b = exercise(views[1]);
      poisonGl.colorMask(false, false, false, false);
      poisonGl.scissor(0, 0, 0, 0);
      poisonGl.activeTexture(poisonGl.TEXTURE1);
      poisonGl.bindTexture(poisonGl.TEXTURE_2D, poisonTexture);
      const a2 = exercise(views[0]);
      poisonGl.deleteTexture(poisonTexture);

      // Stream one canonical point into every client. Packed append messages
      // carry the complete fresh payload as buffers[0]; every view must update
      // its own GPU store even though all 50 share one context.
      const appendSpec = JSON.parse(JSON.stringify(spec));
      const appendTrace = appendSpec.traces[0];
      const xMeta = appendSpec.columns[appendTrace.x];
      const yMeta = appendSpec.columns[appendTrace.y];
      const oldX = new Float32Array(buf, xMeta.byte_offset, xMeta.len);
      const oldY = new Float32Array(buf, yMeta.byte_offset, yMeta.len);
      const appendBuffer = new ArrayBuffer((oldX.length + oldY.length + 2) * 4);
      const appendX = new Float32Array(appendBuffer, 0, oldX.length + 1);
      const appendY = new Float32Array(
        appendBuffer,
        appendX.byteLength,
        oldY.length + 1,
      );
      const encode = (value, meta) =>
        (value - Number(meta.offset || 0)) * Math.abs(Number(meta.scale || 1));
      appendX.set(oldX);
      appendY.set(oldY);
      appendX[oldX.length] = encode(0.25, xMeta);
      appendY[oldY.length] = encode(0.9, yMeta);
      xMeta.byte_offset = 0;
      xMeta.len = appendX.length;
      yMeta.byte_offset = appendX.byteLength;
      yMeta.len = appendY.length;
      appendTrace.n_points = appendX.length;
      if (appendTrace.n_marks !== undefined) appendTrace.n_marks = appendX.length;

      for (const view of views) {
        view._applyAppend({ spec: appendSpec, affected: [appendTrace.id] }, [appendBuffer]);
        view._drawNow();
        view._raf = null;
      }
      const streamFrames = views.map(surface);
      const streamHits = views.map((view) => {
        const [x0, x1] = view._axisRange("x");
        const [y0, y1] = view._axisRange("y");
        const hit = view._pickAt(
          ((0.25 - x0) / (x1 - x0)) * view.plot.w,
          ((y1 - 0.9) / (y1 - y0)) * view.plot.h,
        );
        return hit ? [hit.trace, hit.index] : null;
      });
      for (const view of [...views].reverse()) {
        view._drawNow();
        view._raf = null;
      }
      const reverseStreamFrames = views.map(surface);
      const streamBuffers = views.map((view) => view.gpuTraces[0].xBuf);

      const missingHostsBeforeDestroy = views.filter((view) => !view._glHost).length;
      const canvas2dCountBeforeDestroy = views.filter(
        (view) => view._present2d && view._present2d.canvas === view.canvas,
      ).length;
      const liveBeforeDestroy = views.filter(
        (view) => view.canvas.dataset.xyCtx === "live",
      ).length;
      const snapshotsBeforeDestroy = document.querySelectorAll(
        "canvas[data-xy-ctx-snapshot]",
      ).length;

      const sharedHost = views[1]._glHost;
      const skippedPickView = views[2];
      const hostPick = sharedHost.pick;
      let skippedPick;
      try {
        sharedHost.pick = () => null;
        skippedPickView._pickDirty = true;
        const hit = skippedPickView._pickAt(
          skippedPickView.plot.w / 2,
          skippedPickView.plot.h / 2,
        );
        skippedPick = hit ? [hit.trace, hit.index] : null;
      } finally {
        sharedHost.pick = hostPick;
      }
      skippedPickView._pickDirty = true;
      const resumedPickHit = skippedPickView._pickAt(
        skippedPickView.plot.w / 2,
        skippedPickView.plot.h / 2,
      );
      const resumedPick = resumedPickHit
        ? [resumedPickHit.trace, resumedPickHit.index]
        : null;
      const victimProgram = views[0].pointProg;
      const survivorProgram = views[1].pointProg;
      views[0].destroy();
      const survivor = exercise(views[1]);
      const snapshotsAfterDestroy = document.querySelectorAll(
        "canvas[data-xy-ctx-snapshot]",
      ).length;

      document.body.setAttribute("data-xy-shared-host-probe", JSON.stringify({
        chartCount: views.length,
        webgl2Acquisitions,
        uniqueWebgl2Contexts: webgl2Contexts.size,
        hostCount: hosts.size,
        missingHostsBeforeDestroy,
        liveBeforeDestroy,
        canvas2dCountBeforeDestroy,
        connectedSurfaceCount: surfaces.filter((item) => item.connected).length,
        viewportSurfaceCount: surfaces.filter((item) => item.inViewport).length,
        nonzeroSurfaceCount: surfaces.filter((item) => item.nonzero > 0).length,
        minNonzeroChannels: Math.min(...surfaces.map((item) => item.nonzero)),
        snapshotsBeforeDestroy,
        snapshotsAfterDestroy,
        a1,
        b,
        a2,
        skippedPick,
        resumedPick,
        streamCounts: views.map((view) => view.gpuTraces[0]?.n ?? null),
        streamBuffersRetained: streamBuffers.every(
          (buffer, index) => buffer === xBuffersBeforeAppend[index],
        ),
        distinctStreamBufferCount: new Set(streamBuffers).size,
        changedStreamFrameCount: streamFrames.filter(
          (frame, index) => frame.hash !== surfaces[index].hash,
        ).length,
        stableReverseStreamFrameCount: reverseStreamFrames.filter(
          (frame, index) => frame.hash === streamFrames[index].hash,
        ).length,
        streamHitCount: streamHits.filter(
          (hit) => hit && hit[0] === appendTrace.id && hit[1] === 3,
        ).length,
        victimDestroyed: views[0]._destroyed === true,
        programsDistinct: victimProgram !== survivorProgram,
        victimProgramDeleted: !sharedHost.gl.isProgram(victimProgram),
        survivorProgramLive: sharedHost.gl.isProgram(survivorProgram),
        survivorUsesSameHost: views[1]._glHost === sharedHost,
        survivorLive: views[1].canvas.dataset.xyCtx === "live",
        survivorNonzero: survivor.frame.nonzero,
        survivorHit: survivor.hit,
        hostContextStillLive:
          !!views[1]._glHost && !views[1]._glHost.gl.isContextLost(),
      }));
    } catch (error) {
      document.body.setAttribute(
        "data-xy-shared-host-probe-error",
        String((error && error.stack) || error),
      );
    }
  })();
"""


def _sixty_view_shader_cache_probe() -> str:
    figures = [
        xy.chart(xy.line(x=[0, 1, 2], y=[0, 1, 0]), width=62, height=82).figure(),
        xy.chart(xy.scatter(x=[0, 1, 2], y=[0, 1, 0]), width=62, height=82).figure(),
        xy.chart(xy.hist([0, 1, 1, 2], bins=3), width=62, height=82).figure(),
        xy.chart(
            xy.bar(
                ["a", "b"],
                [[1, 2], [2, 1]],
                mode="grouped",
                series=["A", "B"],
            ),
            width=62,
            height=82,
        ).figure(),
        xy.chart(xy.heatmap([[0, 1], [2, 3]], colormap="turbo"), width=62, height=82).figure(),
    ]
    payloads = []
    for figure in figures:
        spec, blob = figure.build_payload()
        payloads.append(
            {
                "spec": spec,
                "buffer": base64.b64encode(blob).decode("ascii"),
            }
        )

    probe = r"""
  (() => {
    const payloads = __XY_MIXED_PAYLOADS__;
    const glPrototype = WebGL2RenderingContext.prototype;
    const originalCreateShader = glPrototype.createShader;
    const originalShaderSource = glPrototype.shaderSource;
    const originalCompileShader = glPrototype.compileShader;
    const originalDeleteShader = glPrototype.deleteShader;
    const originalCreateProgram = glPrototype.createProgram;
    const originalLinkProgram = glPrototype.linkProgram;
    const shaderTypes = new WeakMap();
    const shaderSources = new WeakMap();
    const compiledSources = new Set();
    let compileShaderCalls = 0;
    let deleteShaderCalls = 0;
    let createProgramCalls = 0;
    let linkProgramCalls = 0;

    glPrototype.createShader = function (type) {
      const shader = originalCreateShader.call(this, type);
      if (shader) shaderTypes.set(shader, type);
      return shader;
    };
    glPrototype.shaderSource = function (shader, source) {
      shaderSources.set(shader, String(source));
      return originalShaderSource.call(this, shader, source);
    };
    glPrototype.compileShader = function (shader) {
      compileShaderCalls += 1;
      compiledSources.add(
        `${shaderTypes.get(shader)}\u0000${shaderSources.get(shader)}`,
      );
      return originalCompileShader.call(this, shader);
    };
    glPrototype.deleteShader = function (shader) {
      deleteShaderCalls += 1;
      return originalDeleteShader.call(this, shader);
    };
    glPrototype.createProgram = function () {
      createProgramCalls += 1;
      return originalCreateProgram.call(this);
    };
    glPrototype.linkProgram = function (program) {
      linkProgramCalls += 1;
      return originalLinkProgram.call(this, program);
    };

    try {
      const grid = document.getElementById("chart");
      grid.replaceChildren();
      grid.style.cssText = [
        "display:grid",
        "grid-template-columns:repeat(10,62px)",
        "gap:2px",
      ].join(";");
      const views = [];
      for (let index = 0; index < 60; index++) {
        const payload = payloads[index % payloads.length];
        const bytes = Uint8Array.from(
          atob(payload.buffer),
          (character) => character.charCodeAt(0),
        );
        const holder = document.createElement("div");
        holder.style.cssText = "width:62px;height:82px;overflow:hidden";
        grid.appendChild(holder);
        const view = xy.renderStandalone(holder, payload.spec, bytes.buffer);
        view._drawNow();
        view._raf = null;
        views.push(view);
      }

      const load = {
        compileShaderCalls,
        uniqueShaderSources: compiledSources.size,
        createProgramCalls,
        linkProgramCalls,
      };
      const pickProbeViews = views.filter((view) => view._pickable);
      for (const view of pickProbeViews) {
        view._pickDirty = true;
        view._pickAt(view.plot.w / 2, view.plot.h / 2);
      }
      const postPick = {
        compileShaderCalls,
        uniqueShaderSources: compiledSources.size,
        createProgramCalls,
        linkProgramCalls,
      };
      for (const view of views) {
        view._drawNow();
        view._raf = null;
      }
      const afterRedraw = {
        compileShaderCalls,
        uniqueShaderSources: compiledSources.size,
        createProgramCalls,
        linkProgramCalls,
      };
      const programs = views.flatMap(
        (view) => Array.from(view._progCache.values()),
      );
      const hostCount = new Set(views.map((view) => view._glHost)).size;
      const contextCount = new Set(views.map((view) => view.gl)).size;
      const host = views[0]._glHost;
      const failedCompileStart = compileShaderCalls;
      const failedDeleteStart = deleteShaderCalls;
      let failedCompileErrors = 0;
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          host.getOrCreateShader(
            host.gl.FRAGMENT_SHADER,
            "#version 300 es\nthis is deliberately invalid",
          );
        } catch (_error) {
          failedCompileErrors += 1;
        }
      }
      const failedShaderCompileCalls = compileShaderCalls - failedCompileStart;
      const failedShaderDeletes = deleteShaderCalls - failedDeleteStart;
      const disposalDeleteStart = deleteShaderCalls;
      for (const view of views) view.destroy();
      const cachedShaderDisposalDeletes = deleteShaderCalls - disposalDeleteStart;
      document.body.setAttribute("data-xy-shader-cache-probe", JSON.stringify({
        chartCount: views.length,
        hostCount,
        contextCount,
        load,
        pickProbeCount: pickProbeViews.length,
        postPick,
        afterRedraw,
        clientProgramCount: programs.length,
        distinctClientProgramCount: new Set(programs).size,
        failedCompileErrors,
        failedShaderCompileCalls,
        failedShaderDeletes,
        cachedShaderDisposalDeletes,
      }));
    } catch (error) {
      document.body.setAttribute(
        "data-xy-shader-cache-probe-error",
        String((error && error.stack) || error),
      );
    } finally {
      glPrototype.createShader = originalCreateShader;
      glPrototype.shaderSource = originalShaderSource;
      glPrototype.compileShader = originalCompileShader;
      glPrototype.deleteShader = originalDeleteShader;
      glPrototype.createProgram = originalCreateProgram;
      glPrototype.linkProgram = originalLinkProgram;
    }
  })();
"""
    return probe.replace(
        "__XY_MIXED_PAYLOADS__",
        json.dumps(payloads, separators=(",", ":")),
    )


_CONTEXT_LOSS_PROBE = r"""
  (async () => {
    const originalGetContext = HTMLCanvasElement.prototype.getContext;
    let webgl2Acquisitions = 0;
    const webgl2Contexts = new Set();
    HTMLCanvasElement.prototype.getContext = function (kind, ...args) {
      const context = originalGetContext.call(this, kind, ...args);
      if (kind === "webgl2") {
        webgl2Acquisitions += 1;
        if (context) webgl2Contexts.add(context);
      }
      return context;
    };
    const glPrototype = WebGL2RenderingContext.prototype;
    const originalCreateShader = glPrototype.createShader;
    const originalShaderSource = glPrototype.shaderSource;
    const originalCompileShader = glPrototype.compileShader;
    const shaderTypes = new WeakMap();
    const shaderSources = new WeakMap();
    const shaderContextIds = new WeakMap();
    const compiledShaderKeys = [];
    let nextShaderContextId = 1;
    glPrototype.createShader = function (type) {
      const shader = originalCreateShader.call(this, type);
      if (shader) shaderTypes.set(shader, type);
      return shader;
    };
    glPrototype.shaderSource = function (shader, source) {
      shaderSources.set(shader, String(source));
      return originalShaderSource.call(this, shader, source);
    };
    glPrototype.compileShader = function (shader) {
      let contextId = shaderContextIds.get(this);
      if (contextId === undefined) {
        contextId = nextShaderContextId++;
        shaderContextIds.set(this, contextId);
      }
      const registry = globalThis[
        Symbol.for("reflex-dev.xy.shared-webgl-host.v1")
      ];
      const currentHost = registry instanceof WeakMap
        ? registry.get(document)
        : null;
      const generation = currentHost && currentHost.gl === this
        ? currentHost.generation
        : 0;
      compiledShaderKeys.push(
        `${contextId}\u0000${generation}\u0000${shaderTypes.get(shader)}` +
        `\u0000${shaderSources.get(shader)}`,
      );
      return originalCompileShader.call(this, shader);
    };

    try {
      document.body.style.cssText = "margin:0;overflow:hidden";
      const grid = document.getElementById("chart");
      grid.replaceChildren();
      grid.style.cssText = "display:grid;grid-template-columns:repeat(4,62px);gap:2px";
      const views = [];
      for (let index = 0; index < 4; index++) {
        const holder = document.createElement("div");
        grid.appendChild(holder);
        const view = xy.renderStandalone(holder, spec, buf);
        view._drawNow();
        view._raf = null;
        views.push(view);
      }

      const zoomed = views[0];
      zoomed._setView(
        { ranges: { x: [0.2, 0.8], y: [0.2, 0.8] } },
        { animate: false, request: false, source: "programmatic" },
      );
      zoomed._drawNow();
      zoomed._raf = null;
      const beforeRange = {
        x: [...zoomed._axisRange("x")],
        y: [...zoomed._axisRange("y")],
      };

      const lostEvents = Array(views.length).fill(0);
      const restoredEvents = Array(views.length).fill(0);
      views.forEach((view, index) => {
        view.canvas.addEventListener("webglcontextlost", () => lostEvents[index]++);
        view.canvas.addEventListener(
          "webglcontextrestored",
          () => restoredEvents[index]++,
        );
      });
      const lossCounts = views.map((view) => view._contextLossCount);
      const restoreCounts = views.map((view) => view._contextRestoreCount);
      const host = views[0]._glHost;
      if (!host || !views.every((view) => view._glHost === host)) {
        throw new Error("context-loss probe did not acquire one shared host");
      }
      const initialShaderCompiles = [...compiledShaderKeys];
      const extension = host.gl.getExtension("WEBGL_lose_context");
      if (!extension) throw new Error("WEBGL_lose_context extension unavailable");

      const waitUntil = async (predicate, label) => {
        const deadline = performance.now() + 5000;
        while (!predicate()) {
          if (performance.now() >= deadline) throw new Error(`timed out waiting for ${label}`);
          await new Promise((resolve) => setTimeout(resolve, 20));
        }
      };

      extension.loseContext();
      await waitUntil(
        () => views.every(
          (view, index) => view._contextLossCount >= lossCounts[index] + 1,
        ),
        "shared context loss fan-out",
      );
      extension.restoreContext();
      await waitUntil(
        () => views.every(
          (view, index) =>
            view._contextRestoreCount >= restoreCounts[index] + 1 &&
            view.canvas.dataset.xyCtx === "live",
        ),
        "shared context restoration fan-out",
      );
      const webgl2AcquisitionsAfterFirstRestore = webgl2Acquisitions;
      const uniqueWebgl2ContextsAfterFirstRestore = webgl2Contexts.size;
      const phaseOneLossCounts = views.map((view) => view._contextLossCount);
      const phaseOneRestoreCounts = views.map((view) => view._contextRestoreCount);
      const phaseOneLossDeltas = phaseOneLossCounts.map(
        (count, index) => count - lossCounts[index],
      );
      const phaseOneRestoreDeltas = phaseOneRestoreCounts.map(
        (count, index) => count - restoreCounts[index],
      );
      const phaseOneShaderCompiles = compiledShaderKeys.slice(
        initialShaderCompiles.length,
      );

      // A real eviction may never restore the original canvas. Leave a second
      // forced loss unrestored: GLHost's watchdog must replace the detached
      // surface/context and rebuild every existing client on the replacement.
      const replacedCanvas = host.canvas;
      const replacedGl = host.gl;
      const replacementExtension = host.gl.getExtension("WEBGL_lose_context");
      if (!replacementExtension) throw new Error("replacement loss extension unavailable");
      replacementExtension.loseContext();
      await waitUntil(
        () => views.every(
          (view, index) => view._contextLossCount >= phaseOneLossCounts[index] + 1,
        ),
        "replacement context loss fan-out",
      );
      await waitUntil(
        () =>
          host.canvas !== replacedCanvas &&
          host.gl !== replacedGl &&
          views.every(
            (view, index) =>
              view._contextRestoreCount >= phaseOneRestoreCounts[index] + 1 &&
              view.canvas.dataset.xyCtx === "live",
          ),
        "shared context replacement fan-out",
      );

      for (const view of views) {
        view._drawNow();
        view._raf = null;
      }
      const phaseTwoShaderCompiles = compiledShaderKeys.slice(
        initialShaderCompiles.length + phaseOneShaderCompiles.length,
      );
      const afterRange = {
        x: [...zoomed._axisRange("x")],
        y: [...zoomed._axisRange("y")],
      };
      const nonzeroAfterRestore = views.map((view) => {
        const context = view._present2d;
        const pixels = context.getImageData(
          0,
          0,
          context.canvas.width,
          context.canvas.height,
        ).data;
        return pixels.some((channel) => channel !== 0);
      });

      // Exercise client-only retry scheduling without waiting in real time.
      // A replaced host leaves `view.gl` pointing at the old lost context until
      // `_initGl` runs, so eligibility must come from the healthy host context.
      const retryView = views[1];
      const originalSetTimeout = window.setTimeout;
      const originalClientGl = retryView.gl;
      const originalClientRestored = retryView._onGlHostContextRestored;
      const queuedRetries = [];
      let nextRetryId = 1;
      let retryAttempts = 0;
      let retryProbe;
      try {
        window.setTimeout = (callback, delay = 0) => {
          queuedRetries.push({ callback, delay });
          return nextRetryId++;
        };
        retryView.gl = { isContextLost: () => true };
        retryView._glLost = true;
        retryView._ctxVisible = true;
        retryView._glHostRecoveryTimer = null;
        retryView._glHostRecoveryDelay = 0;
        retryView._onGlHostContextRestored = () => { retryAttempts += 1; };

        const retryDelays = [];
        let oneTimerPerAttempt = true;
        for (let attempt = 0; attempt < 7; attempt++) {
          retryView._scheduleGlHostClientRecovery();
          retryView._scheduleGlHostClientRecovery();
          oneTimerPerAttempt &&= queuedRetries.length === 1;
          const task = queuedRetries.shift();
          retryDelays.push(task.delay);
          task.callback();
        }

        retryView._ctxVisible = false;
        retryView._scheduleGlHostClientRecovery();
        const offscreenDeferred = queuedRetries.length === 0;
        retryView._ctxVisible = true;
        retryView._recoverContext();
        const visibilityWakeQueued = queuedRetries.length === 1;
        queuedRetries.shift().callback();

        retryProbe = {
          retryDelays,
          oneTimerPerAttempt,
          offscreenDeferred,
          visibilityWakeQueued,
          staleClientRetried: retryAttempts === 8,
        };
      } finally {
        window.setTimeout = originalSetTimeout;
        retryView.gl = originalClientGl;
        retryView._onGlHostContextRestored = originalClientRestored;
        retryView._glLost = false;
        retryView._ctxVisible = true;
        retryView._glHostRecoveryTimer = null;
        retryView._glHostRecoveryDelay = 0;
      }

      document.body.setAttribute("data-xy-shared-loss-probe", JSON.stringify({
        webgl2Acquisitions,
        uniqueWebgl2Contexts: webgl2Contexts.size,
        webgl2AcquisitionsAfterFirstRestore,
        uniqueWebgl2ContextsAfterFirstRestore,
        lostEvents,
        restoredEvents,
        phaseOneLossDeltas,
        phaseOneRestoreDeltas,
        phaseTwoLossDeltas: views.map(
          (view, index) => view._contextLossCount - phaseOneLossCounts[index],
        ),
        phaseTwoRestoreDeltas: views.map(
          (view, index) => view._contextRestoreCount - phaseOneRestoreCounts[index],
        ),
        lossDeltas: views.map(
          (view, index) => view._contextLossCount - lossCounts[index],
        ),
        restoreDeltas: views.map(
          (view, index) => view._contextRestoreCount - restoreCounts[index],
        ),
        liveCount: views.filter((view) => view.canvas.dataset.xyCtx === "live").length,
        sameHostAfterRestore: views.every((view) => view._glHost === host),
        replacementUsed: host.canvas !== replacedCanvas && host.gl !== replacedGl,
        hostLive: !host.gl.isContextLost(),
        beforeRange,
        afterRange,
        nonzeroAfterRestore,
        shaderCompiles: {
          initialCalls: initialShaderCompiles.length,
          initialUniqueGenerationSources: new Set(initialShaderCompiles).size,
          phaseOneCalls: phaseOneShaderCompiles.length,
          phaseOneUniqueGenerationSources: new Set(phaseOneShaderCompiles).size,
          phaseTwoCalls: phaseTwoShaderCompiles.length,
          phaseTwoUniqueGenerationSources: new Set(phaseTwoShaderCompiles).size,
        },
        retryProbe,
        snapshotCount: document.querySelectorAll(
          "canvas[data-xy-ctx-snapshot]",
        ).length,
      }));
    } catch (error) {
      document.body.setAttribute(
        "data-xy-shared-loss-probe-error",
        String((error && error.stack) || error),
      );
    } finally {
      glPrototype.createShader = originalCreateShader;
      glPrototype.shaderSource = originalShaderSource;
      glPrototype.compileShader = originalCompileShader;
    }
  })();
"""


def test_fifty_chartviews_share_one_real_webgl_context(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        _chart_html(_FIFTY_VIEW_PROBE),
        tmp_path / "shared_glhost_50.html",
        "data-xy-shared-host-probe",
        label="50-view shared WebGL host probe",
    )

    assert result["chartCount"] == 50, result
    assert result["webgl2Acquisitions"] == 1, result
    assert result["uniqueWebgl2Contexts"] == 1, result
    assert result["hostCount"] == 1, result
    assert result["missingHostsBeforeDestroy"] == 0, result
    assert result["liveBeforeDestroy"] == 50, result
    assert result["canvas2dCountBeforeDestroy"] == 50, result
    assert result["connectedSurfaceCount"] == 50, result
    assert result["viewportSurfaceCount"] == 50, result
    assert result["nonzeroSurfaceCount"] == 50, result
    assert result["minNonzeroChannels"] > 0, result
    assert result["snapshotsBeforeDestroy"] == 0, result
    assert result["snapshotsAfterDestroy"] == 0, result

    # Rendering and picking another virtual client cannot perturb the first.
    assert result["a1"]["frame"]["hash"] == result["a2"]["frame"]["hash"], result
    assert result["a1"]["hit"] == [0, 1], result
    assert result["b"]["hit"] == [0, 1], result
    assert result["a2"]["hit"] == [0, 1], result
    assert result["skippedPick"] is None, result
    assert result["resumedPick"] == [0, 1], result

    # Every client receives the stream while its buffer/program ownership stays
    # isolated from every other client sharing the context.
    assert result["streamCounts"] == [None, *([4] * 49)], result
    assert result["streamBuffersRetained"] is True, result
    assert result["distinctStreamBufferCount"] == 50, result
    assert result["changedStreamFrameCount"] == 50, result
    assert result["stableReverseStreamFrameCount"] == 50, result
    assert result["streamHitCount"] == 50, result

    # A client release is not a host release while another client survives.
    assert result["victimDestroyed"] is True, result
    assert result["programsDistinct"] is True, result
    assert result["victimProgramDeleted"] is True, result
    assert result["survivorProgramLive"] is True, result
    assert result["survivorUsesSameHost"] is True, result
    assert result["survivorLive"] is True, result
    assert result["survivorNonzero"] > 0, result
    assert result["survivorHit"] == [0, 1], result
    assert result["hostContextStillLive"] is True, result


def test_sixty_chartviews_compile_each_shader_source_once(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        _chart_html(_sixty_view_shader_cache_probe()),
        tmp_path / "shared_glhost_shader_cache_60.html",
        "data-xy-shader-cache-probe",
        label="60-view shared shader-cache probe",
    )

    assert result["chartCount"] == 60, result
    assert result["hostCount"] == 1, result
    assert result["contextCount"] == 1, result
    # Farhan's exact mixed dashboard shape: twelve repetitions of line,
    # scatter, histogram, grouped bar, and heatmap. Load compiles nine unique
    # stage/source pairs; the first pick in each scatter adds two more.
    assert result["load"] == {
        "compileShaderCalls": 9,
        "uniqueShaderSources": 9,
        "createProgramCalls": 60,
        "linkProgramCalls": 60,
    }, result
    assert result["pickProbeCount"] == 12, result
    assert result["postPick"] == {
        "compileShaderCalls": 11,
        "uniqueShaderSources": 11,
        "createProgramCalls": 72,
        "linkProgramCalls": 72,
    }, result
    assert result["afterRedraw"] == result["postPick"], result
    assert result["clientProgramCount"] == 72, result
    assert result["distinctClientProgramCount"] == 72, result
    # Failed shaders are deleted and retried rather than published; final-host
    # disposal then deletes every healthy cached shader exactly once.
    assert result["failedCompileErrors"] == 2, result
    assert result["failedShaderCompileCalls"] == 2, result
    assert result["failedShaderDeletes"] == 2, result
    assert result["cachedShaderDisposalDeletes"] == 11, result


def test_shared_host_loss_restores_every_client_and_zoom(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        _chart_html(_CONTEXT_LOSS_PROBE),
        tmp_path / "shared_glhost_loss.html",
        "data-xy-shared-loss-probe",
        label="shared WebGL host context-loss probe",
    )

    # The 250 ms watchdog may legitimately win a slow first restore under
    # software GL. The second, deliberately unrestored loss must still acquire
    # a newer surface/context than whichever path completed the first phase.
    assert result["webgl2AcquisitionsAfterFirstRestore"] >= 1, result
    assert result["uniqueWebgl2ContextsAfterFirstRestore"] >= 1, result
    assert result["webgl2Acquisitions"] > result["webgl2AcquisitionsAfterFirstRestore"], result
    assert result["uniqueWebgl2Contexts"] > result["uniqueWebgl2ContextsAfterFirstRestore"], result
    for phase in ("phaseOne", "phaseTwo"):
        losses = result[f"{phase}LossDeltas"]
        restores = result[f"{phase}RestoreDeltas"]
        assert len(set(losses)) == 1 and losses[0] >= 1, result
        assert restores == losses, result
    assert result["lossDeltas"] == result["restoreDeltas"], result
    assert result["lostEvents"] == result["lossDeltas"], result
    assert all(
        events >= restores
        for events, restores in zip(result["restoredEvents"], result["restoreDeltas"], strict=True)
    ), result
    assert result["liveCount"] == 4, result
    assert result["sameHostAfterRestore"] is True, result
    assert result["replacementUsed"] is True, result
    assert result["hostLive"] is True, result
    assert all(result["nonzeroAfterRestore"]), result
    # Context loss invalidates cached shader objects. Each healthy generation
    # must refill the cache exactly once per source before client-owned
    # programs relink against that generation's objects.
    for phase in ("initial", "phaseOne", "phaseTwo"):
        calls = result["shaderCompiles"][f"{phase}Calls"]
        unique = result["shaderCompiles"][f"{phase}UniqueGenerationSources"]
        assert calls == unique and calls >= 2, result
    assert result["retryProbe"] == {
        "retryDelays": [50, 100, 200, 400, 800, 1000, 1000],
        "oneTimerPerAttempt": True,
        "offscreenDeferred": True,
        "visibilityWakeQueued": True,
        "staleClientRetried": True,
    }, result
    assert result["snapshotCount"] == 0, result
    assert result["afterRange"]["x"] == pytest.approx(result["beforeRange"]["x"])
    assert result["afterRange"]["y"] == pytest.approx(result["beforeRange"]["y"])


def test_shared_glhost_source_contract() -> None:
    host = (ROOT / "js/src/42_glhost.ts").read_text(encoding="utf-8")
    chartview = (ROOT / "js/src/50_chartview.ts").read_text(encoding="utf-8")

    # Document identity owns the singleton, and releasing the final registered
    # client removes it so a later chart cannot receive a disposed host.
    for marker in (
        'Symbol.for("reflex-dev.xy.shared-webgl-host.v1")',
        "const HOSTS = sharedHostRegistry();",
        "let host = HOSTS.get(doc);",
        "HOSTS.set(doc, host);",
        "HOSTS.delete(doc);",
        "this._clients.add(client);",
        "this._clients.delete(client)",
        "if (this._clients.size === 0) this._dispose();",
        "preserveDrawingBuffer: true",
        "this._replaceLostSurface();",
    ):
        assert marker in host, f"shared-host singleton/lifecycle marker missing: {marker}"

    # Both color and pick passes reset the broad mutable WebGL state surface
    # before client code executes. Presentation copies only the rendered rect.
    color_reset = host.index("this._resetPass(null, w, h, true);")
    color_draw = host.index("drawFn(this.gl);", color_reset)
    pick_reset = host.index("this._resetPass(framebuffer, w, h, false);")
    pick_draw = host.index("drawFn(this.gl);", pick_reset)
    assert color_reset < color_draw
    assert pick_reset < pick_draw
    for marker in (
        "gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);",
        "gl.viewport(0, 0, width, height);",
        "gl.scissor(0, 0, width, height);",
        "gl.bindSampler(unit, null);",
        "gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);",
        "gl.bindVertexArray(null);",
        "gl.useProgram(null);",
        'target2d.globalCompositeOperation = "copy";',
        "target2d.drawImage(this.canvas",
    ):
        assert marker in host, f"shared-host state/presentation marker missing: {marker}"

    # ChartView must acquire a visible 2D surface, route both pass kinds through
    # the host, and release rather than lose the shared context on destroy.
    for marker in (
        "const host = acquireGLHost(document, this);",
        'const present = this.canvas.getContext("2d", { alpha: true });',
        "this._glHost = host;",
        "this._present2d = present;",
        "this._glHost.render(",
        "this._glHost.pick(",
        "this._scheduleGlHostClientRecovery();",
        "this._glHostRecoveryDelay = Math.min(1000, delay * 2);",
        'document.visibilityState !== "visible"',
        "if (!this._renderPick()) return null;",
    ):
        assert marker in chartview, f"ChartView shared-host integration marker missing: {marker}"
    destroy = chartview.split("  destroy() {", 1)[1]
    assert "host.release(this);" in destroy
    assert "loseExt.loseContext();" in destroy
    assert destroy.index("if (this._glHost)") < destroy.index("loseExt.loseContext();")


def test_shared_glhost_texture_unit_reset_contract() -> None:
    """`_resetPass` unbinds exactly ``XY_TEXTURE_UNITS`` texture units.

    The host constant is a reviewed state contract: a renderer change that
    starts activating a third unit must bump it in the same commit, or one
    chart's binding leaks into the next client's pass. Computed
    ``TEXTURE0 + n`` forms would evade this grep — use literals in client
    modules (the host's own reset loop is the one sanctioned computed use).
    """
    host = (ROOT / "js/src/42_glhost.ts").read_text(encoding="utf-8")
    assert "const XY_TEXTURE_UNITS = 2;" in host, "shared-host texture-unit constant missing"
    used: set[int] = set()
    for path in sorted((ROOT / "js/src").glob("*.ts")):
        if path.name == "42_glhost.ts":
            continue
        for match in re.finditer(
            r"activeTexture\(\s*[A-Za-z_$][\w$]*\.TEXTURE(\d+)\s*\)",
            path.read_text(encoding="utf-8"),
        ):
            used.add(int(match.group(1)))
    assert used == {0, 1}, (
        f"renderer modules activate texture units {sorted(used)} but the shared "
        "GLHost resets XY_TEXTURE_UNITS = 2 between clients; change both together"
    )


# ---------------------------------------------------------------------------
# Mixed-size presentation: the grow-only host buffer vs per-chart copies
# ---------------------------------------------------------------------------

_MIXED_SIZE_PROBE = r"""
  (async () => {
    const payloads = __XY_MIXED_SIZE_PAYLOADS__;
    try {
      document.body.style.cssText = "margin:0;overflow:hidden";
      const grid = document.getElementById("chart");
      grid.replaceChildren();
      grid.style.cssText = "position:relative";
      // Zoom every view into an off-center window around the middle data
      // point: the one visible marker parks in the top-right quadrant, so a
      // presentation flip or offset error moves the lit centroid even when a
      // hash comparison has no baseline to disagree with. The window zooms in
      // — programmatic zoom-out is span-clamped and would silently reshape
      // this geometry (the ranges are asserted to catch that).
      const skew = { x: [0.28, 0.55], y: [0.28, 0.55] };
      const views = [];
      const dimsOf = (view) => [
        view.canvas.width,
        view.canvas.height,
        parseFloat(view.canvas.style.width),
        parseFloat(view.canvas.style.height),
      ];
      // Async ResizeObserver delivery can re-measure a chart after creation
      // (headless font metrics and viewport pressure vary by environment). A
      // baseline hashed before that settles would legitimately differ from
      // every redraw, so wait for stable canvas dimensions first — and the
      // report re-checks them so a late relayout fails loudly, not as a hash
      // mystery.
      const settleDims = async (view, label) => {
        const deadline = performance.now() + 5000;
        let last = "";
        let stable = 0;
        while (stable < 3) {
          if (performance.now() >= deadline) {
            throw new Error(`timed out settling dimensions of ${label}`);
          }
          const dims = JSON.stringify(dimsOf(view));
          stable = dims === last ? stable + 1 : 0;
          last = dims;
          await new Promise((resolve) => setTimeout(resolve, 20));
        }
      };
      const build = async (payload, label) => {
        const bytes = Uint8Array.from(
          atob(payload.buffer),
          (character) => character.charCodeAt(0),
        );
        const holder = document.createElement("div");
        holder.style.cssText =
          "position:absolute;top:0;left:0;overflow:hidden;" +
          `width:${payload.css[0]}px;height:${payload.css[1]}px`;
        grid.appendChild(holder);
        const view = xy.renderStandalone(holder, payload.spec, bytes.buffer);
        await settleDims(view, label);
        view._setView(
          { ranges: skew },
          { animate: false, request: false, source: "programmatic" },
        );
        view._drawNow();
        view._raf = null;
        views.push(view);
        return view;
      };
      const surface = (view) => {
        const context = view._present2d;
        if (!context || context.canvas !== view.canvas) {
          throw new Error("ChartView has no Canvas2D presentation surface");
        }
        const w = context.canvas.width;
        const h = context.canvas.height;
        const pixels = context.getImageData(0, 0, w, h).data;
        let hash = 0x811c9dc5;
        let lit = 0;
        let sumX = 0;
        let sumY = 0;
        for (let offset = 0; offset < pixels.length; offset++) {
          hash = Math.imul(hash ^ pixels[offset], 0x01000193) >>> 0;
          if (offset % 4 === 3 && pixels[offset]) {
            const pixel = (offset - 3) / 4;
            lit += 1;
            sumX += pixel % w;
            sumY += Math.floor(pixel / w);
          }
        }
        return {
          hash,
          lit,
          centroidX: lit ? sumX / lit / w : -1,
          centroidY: lit ? sumY / lit / h : -1,
        };
      };
      const redraw = (view) => {
        view._drawNow();
        view._raf = null;
      };
      const pickMiddle = (view) => {
        const [x0, x1] = view._axisRange("x");
        const [y0, y1] = view._axisRange("y");
        // Direct `_drawNow` driving bypasses the draw() bookkeeping that
        // invalidates the pick snapshot on view changes.
        view._pickDirty = true;
        const hit = view._pickAt(
          ((0.5 - x0) / (x1 - x0)) * view.plot.w,
          ((y1 - 0.5) / (y1 - y0)) * view.plot.h,
        );
        return hit ? [hit.trace, hit.index] : null;
      };

      // Smallest chart first: the host buffer starts exactly chart-sized, so
      // this baseline records the sourceY == 0 presentation every later
      // assertion must reproduce byte-for-byte.
      const small = await build(payloads[0], "small chart");
      const host = small._glHost;
      if (!host) throw new Error("mixed-size probe did not acquire a shared host");
      const baselineSmall = surface(small);
      const capacityBaseline = [host.canvas.width, host.canvas.height];

      // A wider chart grows capacity in X. The small chart's presented pixels
      // must not change merely because the shared buffer rendered someone
      // else's frame after its copy completed.
      const wide = await build(payloads[1], "wide chart");
      const baselineWide = surface(wide);
      const smallAfterWideDrew = surface(small);

      // The tallest chart grows capacity in Y: every earlier chart now
      // presents from the bottom-left corner of a buffer taller than itself.
      const tall = await build(payloads[2], "tall chart");
      const baselineTall = surface(tall);
      const capacityGrown = [host.canvas.width, host.canvas.height];
      const dimsAtBaseline = views.map(dimsOf);

      const forwardRedraw = views.map((view) => {
        redraw(view);
        return surface(view);
      });
      const reverseRedraw = [...views].reverse().map((view) => {
        redraw(view);
        return surface(view);
      });
      reverseRedraw.reverse();

      document.body.setAttribute("data-xy-mixed-size-probe", JSON.stringify({
        devicePixelRatio: window.devicePixelRatio,
        viewDprs: views.map((view) => view.dpr),
        viewRanges: views.map((view) => [
          view._axisRange("x"),
          view._axisRange("y"),
        ]),
        hostShared: views.every((view) => view._glHost === host),
        canvasDims: views.map(dimsOf),
        dimsAtBaseline,
        capacityBaseline,
        capacityGrown,
        smallPresentationOffset: [
          host.canvas.width - views[0].canvas.width,
          host.canvas.height - views[0].canvas.height,
        ],
        baselines: [baselineSmall, baselineWide, baselineTall],
        smallAfterWideDrew,
        forwardRedraw,
        reverseRedraw,
        picks: views.map(pickMiddle),
      }));
    } catch (error) {
      document.body.setAttribute(
        "data-xy-mixed-size-probe-error",
        String((error && error.stack) || error),
      );
    }
  })();
"""


def _mixed_size_probe() -> str:
    payloads = []
    # Every chart fits a 320x240 CSS viewport — the window under
    # --force-device-scale-factor=2 — with margin, so no environment's layout
    # pass can shrink a chart away from its requested size mid-probe.
    for width, height in ((62, 82), (150, 90), (70, 170)):
        figure = xy.scatter_chart(
            xy.scatter([0.0, 0.5, 1.0], [0.0, 0.5, 1.0], size=10),
            width=width,
            height=height,
            padding=(4, 4, 4, 4),
        ).figure()
        spec, blob = figure.build_payload()
        payloads.append(
            {
                "spec": spec,
                "buffer": base64.b64encode(blob).decode("ascii"),
                "css": [width, height],
            }
        )
    return _MIXED_SIZE_PROBE.replace(
        "__XY_MIXED_SIZE_PAYLOADS__",
        json.dumps(payloads, separators=(",", ":")),
    )


def _assert_mixed_size_presentation(result: dict, expected_dpr: float) -> None:
    assert result["devicePixelRatio"] == expected_dpr, result
    assert result["viewDprs"] == [expected_dpr] * 3, result
    # The zoomed-in window survives view normalization verbatim; a clamp change
    # here would silently reshape the geometry every assertion below assumes.
    for ranges in result["viewRanges"]:
        assert ranges[0] == pytest.approx([0.28, 0.55]), result
        assert ranges[1] == pytest.approx([0.28, 0.55]), result
    assert result["hostShared"] is True, result
    dims = result["canvasDims"]
    # No relayout may slip in between the hashed baselines and the redraw
    # comparisons — a late resize would make every hash mismatch below a
    # red herring.
    assert dims == result["dimsAtBaseline"], result
    # The plot canvas floors fractional CSS sizes into device pixels; the
    # invariant under a forced device scale factor is the ratio, not the
    # rounding mode.
    for device_w, device_h, css_w, css_h in dims:
        assert abs(device_w - css_w * expected_dpr) <= 1, result
        assert abs(device_h - css_h * expected_dpr) <= 1, result
    # Grow-only capacity: exactly the first client's size at baseline, exactly
    # the elementwise maximum after every chart drew once.
    assert result["capacityBaseline"] == [dims[0][0], dims[0][1]], result
    assert result["capacityGrown"] == [
        max(dim[0] for dim in dims),
        max(dim[1] for dim in dims),
    ], result
    # The anti-vacuity guard: after growth the small chart's copy really does
    # start above the buffer bottom in image coordinates and left of its right
    # edge — the offsets a sourceX/sourceY regression would corrupt.
    offset_x, offset_y = result["smallPresentationOffset"]
    assert offset_x > 0 and offset_y > 0, result
    baselines = result["baselines"]
    assert result["smallAfterWideDrew"]["hash"] == baselines[0]["hash"], result
    for index in range(3):
        assert result["forwardRedraw"][index]["hash"] == baselines[index]["hash"], result
        assert result["reverseRedraw"][index]["hash"] == baselines[index]["hash"], result
    for frame in (*baselines, *result["forwardRedraw"], *result["reverseRedraw"]):
        assert frame["lit"] > 0, result
        assert frame["centroidX"] > 0.55, result
        assert frame["centroidY"] < 0.45, result
    assert result["picks"] == [[0, 1]] * 3, result


def test_mixed_size_charts_present_identically_after_capacity_growth(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        _chart_html(_mixed_size_probe()),
        tmp_path / "shared_glhost_mixed_size.html",
        "data-xy-mixed-size-probe",
        label="mixed-size shared-host presentation probe",
    )
    _assert_mixed_size_presentation(result, expected_dpr=1)


def test_mixed_size_presentation_at_device_pixel_ratio_two(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        _chart_html(_mixed_size_probe()),
        tmp_path / "shared_glhost_mixed_size_dpr2.html",
        "data-xy-mixed-size-probe",
        label="device-pixel-ratio-2 shared-host presentation probe",
        extra_args=("--force-device-scale-factor=2",),
    )
    _assert_mixed_size_presentation(result, expected_dpr=2)


# ---------------------------------------------------------------------------
# Governed fallback: XY_SHARED_WEBGL = false keeps the native path working
# ---------------------------------------------------------------------------

_GOVERNED_FALLBACK_PROBE = r"""
  (async () => {
    const originalGetContext = HTMLCanvasElement.prototype.getContext;
    let webgl2Acquisitions = 0;
    const webgl2Contexts = new Set();
    HTMLCanvasElement.prototype.getContext = function (kind, ...args) {
      const context = originalGetContext.call(this, kind, ...args);
      if (kind === "webgl2") {
        webgl2Acquisitions += 1;
        if (context) webgl2Contexts.add(context);
      }
      return context;
    };
    const sharedOverride = window.XY_SHARED_WEBGL;
    const budgetOverride = window.XY_CONTEXT_BUDGET;
    try {
      window.XY_SHARED_WEBGL = false;
      window.XY_CONTEXT_BUDGET = 2;
      document.body.style.cssText = "margin:0;overflow:hidden";
      const grid = document.getElementById("chart");
      grid.replaceChildren();
      grid.style.cssText = "display:grid;grid-template-columns:repeat(4,62px);gap:2px";
      // Deadlines are virtual-time (the page runs under a raised
      // --virtual-time-budget): generous bounds cost nothing when the cascade
      // settles early, and a genuine hang still reports which label stalled.
      const waitUntil = async (predicate, label) => {
        const deadline = performance.now() + 20000;
        while (!predicate()) {
          if (performance.now() >= deadline) throw new Error(`timed out waiting for ${label}`);
          await new Promise((resolve) => setTimeout(resolve, 20));
        }
      };
      const views = [];
      const build = () => {
        const holder = document.createElement("div");
        holder.style.cssText = "width:62px;height:82px;overflow:hidden";
        grid.appendChild(holder);
        const view = xy.renderStandalone(holder, spec, buf);
        view._drawNow();
        view._raf = null;
        views.push(view);
        return view;
      };
      build();
      build();
      // Zoom the least-recently-visible view before budget pressure releases
      // it: a governed release must bring back exactly this view (#156).
      const zoomed = views[0];
      zoomed._setView(
        { ranges: { x: [0.2, 0.8], y: [0.2, 0.8] } },
        { animate: false, request: false, source: "programmatic" },
      );
      zoomed._drawNow();
      zoomed._raf = null;
      const beforeRange = {
        x: [...zoomed._axisRange("x")],
        y: [...zoomed._axisRange("y")],
      };
      // Two more views exceed the budget of 2. The governor — not the browser
      // — chooses victims: it releases the least-recently-visible views behind
      // snapshot stand-ins, the released-but-visible views revive through the
      // request path, and that rotation settles at exactly budget-many live
      // contexts with every view having cycled through one governed release.
      build();
      build();
      const lossSum = () =>
        views.reduce((total, view) => total + view._contextLossCount, 0);
      const liveViews = () => views.filter((view) => !view._glLost);
      // The rotation cascade's length is timing-dependent (each visible
      // released view revives through the request path, releasing another),
      // so settle on the invariant state: budget-many live views, every view
      // cycled at least once, and loss telemetry quiet across polls.
      const settleOn = async (label, extra) => {
        let stableSum = -1;
        let stablePolls = 0;
        await waitUntil(() => {
          const sum = lossSum();
          stablePolls = sum === stableSum ? stablePolls + 1 : 0;
          stableSum = sum;
          return (
            stablePolls >= 3 &&
            liveViews().length === 2 &&
            views.every((view) => view._contextLossCount >= 1) &&
            views.every((view) => !view._ctxLostPending) &&
            extra()
          );
        }, label);
      };
      await settleOn("governed budget equilibrium", () => true);
      const afterCreation = {
        webgl2Acquisitions,
        uniqueWebgl2Contexts: webgl2Contexts.size,
        stamps: views.map((view) => view.canvas.dataset.xyCtx),
        lost: views.map((view) => view._glLost),
        lossCounts: views.map((view) => view._contextLossCount),
        restoreCounts: views.map((view) => view._contextRestoreCount),
        governorRegistered: views.map((view) => view._governorRegistered === true),
        hostless: views.map((view) => view._glHost === null),
        glHostMarkers: views.map((view) => view.canvas.dataset.xyGlHost ?? null),
        nativeCanvas: views.map(
          (view) => !!view.gl && view.gl.canvas === view.canvas,
        ),
        snapshots: document.querySelectorAll("canvas[data-xy-ctx-snapshot]").length,
      };
      const registry = globalThis[
        Symbol.for("reflex-dev.xy.shared-webgl-host.v1")
      ];
      const registryHostExists =
        registry instanceof WeakMap && registry.get(document) !== undefined;
      const litCount = (view) => {
        view._drawNow();
        view._raf = null;
        const gl = view.gl;
        const w = view.canvas.width;
        const h = view.canvas.height;
        const px = new Uint8Array(w * h * 4);
        gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
        let lit = 0;
        for (let index = 0; index < px.length; index++) if (px[index]) lit += 1;
        return lit;
      };
      const liveLit = liveViews().map((view) => litCount(view));

      // Requesting a released view (the pointer-entry path) must rotate a live
      // view out instead of exceeding the budget.
      const equilibriumSum = lossSum();
      const revived = views.find((view) => view._glLost);
      const revivedIndex = views.indexOf(revived);
      revived._recoverContext();
      await settleOn(
        "budget rotation after revival",
        () => !revived._glLost && lossSum() > equilibriumSum,
      );
      const afterRevival = {
        revivedIndex,
        revivedStamp: revived.canvas.dataset.xyCtx,
        stamps: views.map((view) => view.canvas.dataset.xyCtx),
        lossCounts: views.map((view) => view._contextLossCount),
        restoreCounts: views.map((view) => view._contextRestoreCount),
        lost: views.map((view) => view._glLost),
        liveCount: liveViews().length,
        snapshots: document.querySelectorAll("canvas[data-xy-ctx-snapshot]").length,
        revivedLit: litCount(revived),
        afterRange: {
          x: [...zoomed._axisRange("x")],
          y: [...zoomed._axisRange("y")],
        },
        zoomedRestoreCount: zoomed._contextRestoreCount,
      };
      document.body.setAttribute("data-xy-governed-fallback-probe", JSON.stringify({
        afterCreation,
        registryHostExists,
        liveLit,
        beforeRange,
        afterRevival,
      }));
    } catch (error) {
      document.body.setAttribute(
        "data-xy-governed-fallback-probe-error",
        String((error && error.stack) || error),
      );
    } finally {
      HTMLCanvasElement.prototype.getContext = originalGetContext;
      if (sharedOverride === undefined) delete window.XY_SHARED_WEBGL;
      else window.XY_SHARED_WEBGL = sharedOverride;
      if (budgetOverride === undefined) delete window.XY_CONTEXT_BUDGET;
      else window.XY_CONTEXT_BUDGET = budgetOverride;
    }
  })();
"""


def test_disabled_shared_host_keeps_governed_native_contexts_working(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        _chart_html(_GOVERNED_FALLBACK_PROBE),
        tmp_path / "shared_glhost_governed_fallback.html",
        "data-xy-governed-fallback-probe",
        label="governed-fallback budget probe",
        # The probe's 20 s waitUntil deadlines are virtual-time; the budget
        # must exceed their worst-case sum or a genuine stall dumps the page
        # without the diagnostic timeout label. Idle budget is skipped
        # instantly, so the happy path pays nothing for the headroom.
        extra_args=("--virtual-time-budget=60000",),
    )

    def assert_governed_equilibrium(state: dict) -> None:
        # Budget 2 with four visible charts settles by rotation: the governor
        # releases least-recently-visible views, visible released views revive
        # through the request path, and each revival releases another view.
        # The cascade's exact path is timing-dependent; its invariants are
        # not: exactly budget-many live contexts, every view has cycled
        # through at least one governed release, every completed loss was
        # restored, one snapshot stand-in per released view, and no stamp
        # ever reads "lost" — the browser-eviction marker (§28 keeps the
        # governed/evicted difference legible).
        assert sorted(state["stamps"]) == ["live", "live", "released", "released"], result
        assert state["lost"] == [stamp == "released" for stamp in state["stamps"]], result
        assert all(count >= 1 for count in state["lossCounts"]), result
        for losses, restores, lost in zip(
            state["lossCounts"], state["restoreCounts"], state["lost"], strict=True
        ):
            assert restores == losses - (1 if lost else 0), result
        assert state["snapshots"] == 2, result

    creation = result["afterCreation"]
    # Opting out really is per-chart native WebGL: one context per canvas, no
    # shared host anywhere, and every view registered with the governor.
    assert creation["webgl2Acquisitions"] >= 4, result
    assert creation["uniqueWebgl2Contexts"] == 4, result
    assert creation["hostless"] == [True] * 4, result
    assert creation["governorRegistered"] == [True] * 4, result
    assert creation["glHostMarkers"] == [None] * 4, result
    assert creation["nativeCanvas"] == [True] * 4, result
    assert result["registryHostExists"] is False, result
    assert_governed_equilibrium(creation)
    assert len(result["liveLit"]) == 2, result
    assert all(lit > 0 for lit in result["liveLit"]), result

    revival = result["afterRevival"]
    # Requesting a released view rotates a live one out at budget and renders
    # a real frame; the zoomed view keeps its settled ranges through its own
    # governed release/restore round trip (#156).
    assert_governed_equilibrium(revival)
    assert revival["stamps"][revival["revivedIndex"]] == "live", result
    assert revival["revivedStamp"] == "live", result
    assert revival["liveCount"] == 2, result
    assert sum(revival["lossCounts"]) > sum(creation["lossCounts"]), result
    assert revival["revivedLit"] > 0, result
    assert revival["zoomedRestoreCount"] >= 1, result
    assert result["beforeRange"]["x"] == pytest.approx([0.2, 0.8]), result
    assert revival["afterRange"]["x"] == pytest.approx(result["beforeRange"]["x"]), result
    assert revival["afterRange"]["y"] == pytest.approx(result["beforeRange"]["y"]), result


# ---------------------------------------------------------------------------
# Child-frame gate: governed by default, XY_SHARED_WEBGL = true opts in
# ---------------------------------------------------------------------------

_FRAME_GATE_PROBE = r"""
  (async () => {
    const innerDefault = __XY_INNER_DEFAULT__;
    const innerOptIn = __XY_INNER_OPT_IN__;
    const HOST_KEY = Symbol.for("reflex-dev.xy.shared-webgl-host.v1");
    try {
      document.body.style.cssText = "margin:0;overflow:hidden";
      const grid = document.getElementById("chart");
      grid.replaceChildren();
      const holder = document.createElement("div");
      holder.style.cssText = "width:62px;height:82px;overflow:hidden";
      grid.appendChild(holder);
      const parentView = xy.renderStandalone(holder, spec, buf);
      parentView._drawNow();
      parentView._raf = null;

      // srcdoc frames are same-origin with this page, so the probe can reach
      // each frame's captured view and per-realm host registry directly.
      const makeFrame = (html) => {
        const frame = document.createElement("iframe");
        frame.style.cssText = "width:300px;height:160px;border:0;display:block";
        document.body.appendChild(frame);
        frame.srcdoc = html;
        return frame;
      };
      const defaultFrame = makeFrame(innerDefault);
      const optInFrame = makeFrame(innerOptIn);
      // Virtual-time deadline under a raised --virtual-time-budget: generous
      // because two full chart documents boot inside child frames; an early
      // finish skips the remainder instantly.
      const waitUntil = async (predicate, label) => {
        const deadline = performance.now() + 20000;
        while (!predicate()) {
          if (performance.now() >= deadline) throw new Error(`timed out waiting for ${label}`);
          await new Promise((resolve) => setTimeout(resolve, 20));
        }
      };
      const frameView = (frame) => {
        try {
          return (frame.contentWindow && frame.contentWindow.__fcProbeView) || null;
        } catch (_error) {
          return null;
        }
      };
      await waitUntil(() => frameView(defaultFrame), "default child-frame chart");
      await waitUntil(() => frameView(optInFrame), "opted-in child-frame chart");

      const nonblank = (view) => {
        view._drawNow();
        view._raf = null;
        const w = view.canvas.width;
        const h = view.canvas.height;
        if (view._present2d) {
          return view._present2d.getImageData(0, 0, w, h).data.some(
            (channel) => channel !== 0,
          );
        }
        const gl = view.gl;
        const px = new Uint8Array(w * h * 4);
        gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
        return px.some((channel) => channel !== 0);
      };
      const registryHost = (frame) => {
        const registry = frame.contentWindow[HOST_KEY];
        return registry instanceof frame.contentWindow.WeakMap
          ? registry.get(frame.contentDocument) ?? null
          : null;
      };

      const defaultView = frameView(defaultFrame);
      const optInView = frameView(optInFrame);
      const parentHost = parentView._glHost;
      const optInHost = registryHost(optInFrame);
      document.body.setAttribute("data-xy-frame-gate-probe", JSON.stringify({
        parentHostMode:
          !!parentHost && parentView.canvas.dataset.xyGlHost === "shared",
        defaultFrame: {
          topLevel:
            defaultFrame.contentWindow.top === defaultFrame.contentWindow,
          hostNull: defaultView._glHost === null,
          governorRegistered: defaultView._governorRegistered === true,
          nativeCanvas:
            !!defaultView.gl && defaultView.gl.canvas === defaultView.canvas,
          presents2d: !!defaultView._present2d,
          glHostMarker: defaultView.canvas.dataset.xyGlHost ?? null,
          registryHostExists: registryHost(defaultFrame) !== null,
          nonblank: nonblank(defaultView),
        },
        optInFrame: {
          hostAcquired: optInView._glHost !== null,
          sameHostInRegistry:
            optInHost !== null && optInView._glHost === optInHost,
          distinctFromParentHost: optInHost !== parentHost,
          glHostMarker: optInView.canvas.dataset.xyGlHost ?? null,
          presents2d:
            !!optInView._present2d &&
            optInView._present2d.canvas === optInView.canvas,
          nonblank: nonblank(optInView),
        },
      }));
    } catch (error) {
      document.body.setAttribute(
        "data-xy-frame-gate-probe-error",
        String((error && error.stack) || error),
      );
    }
  })();
"""


def _frame_gate_probe() -> str:
    chart = xy.scatter_chart(
        xy.scatter([0.0, 0.5, 1.0], [0.0, 0.5, 1.0], size=10),
        width=62,
        height=82,
        padding=(4, 4, 4, 4),
    )
    inner = probe_document(chart, "")
    opted_in = inner.replace("<head>", "<head><script>window.XY_SHARED_WEBGL = true;</script>", 1)
    assert opted_in != inner, "to_html head shape changed; update the frame-gate probe"

    def embed(document: str) -> str:
        # The inner documents ride inside the outer page's <script> block as
        # string literals; escaping `<` keeps their own script tags from
        # terminating it.
        return json.dumps(document).replace("<", "\\u003c")

    return _FRAME_GATE_PROBE.replace("__XY_INNER_DEFAULT__", embed(inner)).replace(
        "__XY_INNER_OPT_IN__", embed(opted_in)
    )


def test_child_frames_default_to_governed_path_and_opt_into_shared_host(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    result = run_browser_probe(
        chromium,
        _chart_html(_frame_gate_probe()),
        tmp_path / "shared_glhost_frame_gate.html",
        "data-xy-frame-gate-probe",
        label="child-frame shared-host gate probe",
        # Virtual-time headroom over the probe's 20 s waitUntil deadlines (two
        # embedded chart documents boot in child frames); idle budget is
        # skipped instantly.
        extra_args=("--virtual-time-budget=60000",),
    )

    assert result["parentHostMode"] is True, result
    frame = result["defaultFrame"]
    # A child frame keeps the proven governed native path by default: no host
    # in its realm registry, its visible canvas holds the WebGL context, and
    # it renders.
    assert frame["topLevel"] is False, result
    assert frame["hostNull"] is True, result
    assert frame["governorRegistered"] is True, result
    assert frame["nativeCanvas"] is True, result
    assert frame["presents2d"] is False, result
    assert frame["glHostMarker"] is None, result
    assert frame["registryHostExists"] is False, result
    assert frame["nonblank"] is True, result
    opted_in = result["optInFrame"]
    # XY_SHARED_WEBGL = true opts the frame into its own document-scoped host
    # — a distinct host from the parent document's, presenting through Canvas2D.
    assert opted_in["hostAcquired"] is True, result
    assert opted_in["sameHostInRegistry"] is True, result
    assert opted_in["distinctFromParentHost"] is True, result
    assert opted_in["glHostMarker"] == "shared", result
    assert opted_in["presents2d"] is True, result
    assert opted_in["nonblank"] is True, result
