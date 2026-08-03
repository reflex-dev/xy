"""Production integration coverage for the document-scoped shared WebGL host.

These probes exercise ``ChartView`` and the JavaScript bundled by ``to_html``:
every chart is a real standalone view built from the same small payload, with a
visible Canvas2D presentation surface backed by one detached WebGL2 host.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import xy
from conftest import RENDER_CALLS, run_browser_probe
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
          (view, index) => view._contextLossCount === lossCounts[index] + 1,
        ),
        "shared context loss fan-out",
      );
      extension.restoreContext();
      await waitUntil(
        () => views.every(
          (view, index) =>
            view._contextRestoreCount === restoreCounts[index] + 1 &&
            view.canvas.dataset.xyCtx === "live",
        ),
        "shared context restoration fan-out",
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
          (view, index) => view._contextLossCount === lossCounts[index] + 2,
        ),
        "replacement context loss fan-out",
      );
      await waitUntil(
        () =>
          host.canvas !== replacedCanvas &&
          host.gl !== replacedGl &&
          views.every(
            (view, index) =>
              view._contextRestoreCount === restoreCounts[index] + 2 &&
              view.canvas.dataset.xyCtx === "live",
          ),
        "shared context replacement fan-out",
      );

      for (const view of views) {
        view._drawNow();
        view._raf = null;
      }
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

      document.body.setAttribute("data-xy-shared-loss-probe", JSON.stringify({
        webgl2Acquisitions,
        uniqueWebgl2Contexts: webgl2Contexts.size,
        lostEvents,
        restoredEvents,
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
        snapshotCount: document.querySelectorAll(
          "canvas[data-xy-ctx-snapshot]",
        ).length,
      }));
    } catch (error) {
      document.body.setAttribute(
        "data-xy-shared-loss-probe-error",
        String((error && error.stack) || error),
      );
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

    assert result["webgl2Acquisitions"] == 2, result
    assert result["uniqueWebgl2Contexts"] == 2, result
    assert result["lostEvents"] == [2, 2, 2, 2], result
    assert result["restoredEvents"] == [2, 2, 2, 2], result
    assert result["lossDeltas"] == [2, 2, 2, 2], result
    assert result["restoreDeltas"] == [2, 2, 2, 2], result
    assert result["liveCount"] == 4, result
    assert result["sameHostAfterRestore"] is True, result
    assert result["replacementUsed"] is True, result
    assert result["hostLive"] is True, result
    assert all(result["nonzeroAfterRestore"]), result
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
    ):
        assert marker in chartview, f"ChartView shared-host integration marker missing: {marker}"
    destroy = chartview.split("  destroy() {", 1)[1]
    assert "host.release(this);" in destroy
    assert "loseExt.loseContext();" in destroy
    assert destroy.index("if (this._glHost)") < destroy.index("loseExt.loseContext();")
