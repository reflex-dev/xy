"""Chart lifecycle smoke for the example gallery.

Runs the FastAPI example and, for every gallery chart plus the drilldown, loads
its route in headless Chromium and runs narrow/wide resize, a visibility flip,
and a WebGL context loss+restore, asserting the view keeps painting lit pixels
and keeps its runtime DOM slots. A final pass loads the index and checks the
embedded iframes paint.

The probe is injected over CDP with `Page.addScriptToEvaluateOnNewDocument` so
it installs before the chart client assigns `window.xy`.

Usage: python scripts/reflex_lifecycle_smoke.py [/path/to/chrome]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "fastapi"))

import charts  # noqa: E402  (examples/fastapi/charts.py)

from _app_smoke import ChromiumSession, Probe, find_chromium, serve_fastapi_app
from xy.dom import CHART_DOM_SLOTS  # noqa: E402

GALLERY_IDS: tuple[str, ...] = tuple(info.id for info in charts.GALLERY)
DRILLDOWN_PATH = "/drilldown"

LIFECYCLE_PHASES = (
    "initial",
    "narrow-resize",
    "wide-resize",
    "visibility-change",
    "context-restore",
    "restore",
)

REQUIRED_RUNTIME_DOM_SLOTS = (
    "root",
    "chrome",
    "canvas",
    "labels",
)

# Few points so the drilldown demo boots quickly.
SMOKE_POINTS = 200_000
MIN_LIT = 8

_WRAP_TEMPLATE = r"""
(() => {
  const views = [];
  const publicDomSlots = new Set(__XY_PUBLIC_DOM_SLOTS__);
  const requiredRuntimeDomSlots = __XY_REQUIRED_RUNTIME_DOM_SLOTS__;
  const phaseNames = __XY_PHASES__;
  window.__xyLifecycleViews = views;

  function wrap(xy) {
    if (!xy || xy.__lifecycleWrapped) return xy;
    xy.__lifecycleWrapped = true;
    const origRS = xy.renderStandalone;
    if (typeof origRS === "function") {
      xy.renderStandalone = function (...args) {
        const view = origRS.apply(this, args);
        views.push(view);
        return view;
      };
    }
    const OriginalChartView = xy.ChartView;
    if (typeof OriginalChartView === "function") {
      xy.ChartView = class LifecycleChartView extends OriginalChartView {
        constructor(...args) {
          super(...args);
          views.push(this);
        }
      };
    }
    return xy;
  }

  // Intercept the bundle's `window.xy = {...}` so the wrap installs before any
  // chart is constructed.
  let _xy;
  Object.defineProperty(window, "xy", {
    configurable: true,
    get: () => _xy,
    set: (value) => { _xy = wrap(value); },
  });

  const tick = () => new Promise((r) => setTimeout(r, 0));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function waitFor(pred, timeout = 3000) {
    const deadline = performance.now() + timeout;
    while (performance.now() < deadline) {
      if (pred()) return true;
      await sleep(25);
    }
    return pred();
  }

  function litPixels(view) {
    if (!view || !view.gl || !view.canvas) return { lit: 0, total: 0 };
    view._syncContainerSize?.();
    view._drawNow?.();
    const gl = view.gl;
    const w = gl.drawingBufferWidth;
    const h = gl.drawingBufferHeight;
    if (!w || !h) return { lit: 0, total: 0 };
    const sampleW = Math.max(1, Math.min(w, 512));
    const sampleH = Math.max(1, Math.min(h, 256));
    const sampleX = Math.max(0, Math.floor((w - sampleW) / 2));
    const sampleY = Math.max(0, Math.floor((h - sampleH) / 2));
    const pixels = new Uint8Array(sampleW * sampleH * 4);
    gl.readPixels(sampleX, sampleY, sampleW, sampleH, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let lit = 0;
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 8) lit++;
    return { lit, total: sampleW * sampleH };
  }
  window.__xyLit = () => views.map((v) => litPixels(v).lit);

  function domSlotReport(view) {
    const counts = {};
    const unexpected = new Set();
    const missing = [];
    const root = view && view.root;
    if (!root) return { counts, missing: requiredRuntimeDomSlots.slice(), unexpected: ["(missing-root)"] };
    const nodes = [root, ...root.querySelectorAll("[data-xy-slot]")];
    for (const node of nodes) {
      const slot = node && node.dataset ? node.dataset.xySlot : "";
      if (!slot) continue;
      counts[slot] = (counts[slot] || 0) + 1;
      if (!publicDomSlots.has(slot)) unexpected.add(slot);
    }
    for (const slot of requiredRuntimeDomSlots) if (!counts[slot]) missing.push(slot);
    return { counts, missing, unexpected: [...unexpected] };
  }

  async function forceContextRestore(view) {
    if (!view || !view.gl || !view.canvas) throw new Error("no live view for context restore");
    const loseExt = view.gl.getExtension("WEBGL_lose_context");
    if (!loseExt) throw new Error("WEBGL_lose_context extension unavailable");
    const lostCanvas = view.canvas;
    let lostSeen = false;
    let restoredSeen = false;
    lostCanvas.addEventListener("webglcontextlost", () => { lostSeen = true; }, { once: true });
    lostCanvas.addEventListener("webglcontextrestored", () => { restoredSeen = true; }, { once: true });
    loseExt.loseContext();
    const rebuilt = () =>
      view.canvas !== lostCanvas && view._glLost === false && view.gl &&
      !view.gl.isContextLost() && !view._destroyed;
    const lostOk = await waitFor(() => lostSeen && (view._glLost === true || rebuilt()), 1500);
    if (!lostOk) throw new Error("webglcontextlost never entered a recovery path");
    if (!rebuilt()) {
      loseExt.restoreContext();
      const ok = await waitFor(
        () => restoredSeen && view._glLost === false && view.gl && !view._destroyed, 3500);
      if (!ok) throw new Error("webglcontextrestored did not rebuild the view");
    }
    await tick(); await tick();
    view._syncContainerSize?.();
    view._drawNow?.();
  }

  window.__xyLifecycleCheck = async function () {
    await tick(); await tick();
    const results = [];
    for (const view of views) {
      const oldWidth = view.root?.style.width || "";
      const phases = [];
      const capture = (name) => {
        const px = litPixels(view);
        phases.push({ name, lit: px.lit, total: px.total });
      };
      capture("initial");
      if (view.root) { view.root.style.width = "420px"; view._syncContainerSize?.(); window.dispatchEvent(new Event("resize")); await tick(); }
      capture("narrow-resize");
      if (view.root) { view.root.style.width = "960px"; view._syncContainerSize?.(); window.dispatchEvent(new Event("resize")); await tick(); }
      capture("wide-resize");
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new Event("focus"));
      await tick();
      capture("visibility-change");
      await forceContextRestore(view);
      capture("context-restore");
      if (view.root) view.root.style.width = oldWidth;
      view._syncContainerSize?.();
      window.dispatchEvent(new Event("resize"));
      await tick();
      capture("restore");
      results.push({
        title: view.spec?.title || "",
        phase_names: phases.map((p) => p.name),
        phases,
        min_lit: Math.min(...phases.map((p) => p.lit)),
        label_count: view.labels?.children?.length || 0,
        dom_slots: domSlotReport(view),
        destroyed: !!view._destroyed,
      });
    }
    return { view_count: views.length, phase_names: phaseNames, results };
  };
})();
"""

WRAP_SCRIPT = (
    _WRAP_TEMPLATE.replace("__XY_PUBLIC_DOM_SLOTS__", json.dumps(list(CHART_DOM_SLOTS)))
    .replace("__XY_REQUIRED_RUNTIME_DOM_SLOTS__", json.dumps(list(REQUIRED_RUNTIME_DOM_SLOTS)))
    .replace("__XY_PHASES__", json.dumps(list(LIFECYCLE_PHASES)))
)


def _check_report(report: dict, label: str) -> int:
    """Validate one page's lifecycle report; raise SystemExit on any failure.

    Returns the minimum lit-pixel count seen across the page's views.
    """
    if not isinstance(report, dict) or not report.get("view_count"):
        raise SystemExit(f"{label}: no chart views mounted ({report!r})")
    if report.get("phase_names") != list(LIFECYCLE_PHASES):
        raise SystemExit(f"{label}: lifecycle phases incomplete: {report.get('phase_names')}")
    mins = []
    for result in report["results"]:
        if result.get("destroyed"):
            raise SystemExit(f"{label}: a view was destroyed mid-lifecycle: {result}")
        if result.get("phase_names") != list(LIFECYCLE_PHASES):
            raise SystemExit(f"{label}: view phases incomplete: {result.get('phase_names')}")
        if int(result.get("min_lit") or 0) <= MIN_LIT:
            raise SystemExit(
                f"{label}: view went blank (min_lit={result.get('min_lit')}): {result.get('title')!r}"
            )
        slots = result.get("dom_slots") or {}
        if slots.get("missing"):
            raise SystemExit(f"{label}: missing runtime DOM slots {slots['missing']}")
        if slots.get("unexpected"):
            raise SystemExit(f"{label}: unexpected DOM slots {slots['unexpected']}")
        mins.append(int(result["min_lit"]))
    return min(mins)


def _run_lifecycle(session: ChromiumSession, url: str, label: str) -> int:
    probe = Probe(session, url, init_script=WRAP_SCRIPT)
    try:
        probe.wait_for(
            "window.__xyLifecycleViews && window.__xyLifecycleViews.length > 0",
            timeout_s=60.0,
            label=f"{label}: chart view mounted",
        )
        report = probe.eval("window.__xyLifecycleCheck()", timeout_s=90.0)
        return _check_report(report, label)
    finally:
        probe.close()


def _check_index_iframes(session: ChromiumSession, base_url: str) -> int:
    """Load the index and confirm its embedded iframes paint lit pixels."""
    probe = Probe(session, base_url, init_script=WRAP_SCRIPT)
    try:
        expected = len(GALLERY_IDS) + 1  # gallery charts + drilldown
        probe.wait_for(
            f"document.querySelectorAll('iframe').length >= {expected}",
            timeout_s=30.0,
            label="index iframes present",
        )
        # Scroll through so lazy iframes load, then let them paint.
        probe.eval(
            "(async () => { for (let y = 0; y <= document.body.scrollHeight; y += 500)"
            " { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); }"
            " window.scrollTo(0, 0); })()",
            timeout_s=60.0,
        )
        lit = probe.wait_for(
            "(() => { const f = Array.from(document.querySelectorAll('iframe'))"
            ".map(f => { try { return f.contentWindow.__xyLit ? Math.max(0, ...f.contentWindow.__xyLit()) : 0; }"
            " catch (e) { return 0; } }); const ready = f.filter(v => v > 8).length;"
            " return ready >= 3 ? ready : 0; })()",
            timeout_s=60.0,
            label="index iframes painted",
        )
        return int(lit)
    finally:
        probe.close()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    chromium = find_chromium(args[0] if args else None)
    with (
        serve_fastapi_app(points=SMOKE_POINTS) as base_url,
        ChromiumSession(chromium, gl="software", sandbox=False) as session,
    ):
        mins = []
        for chart_id in GALLERY_IDS:
            m = _run_lifecycle(session, f"{base_url}/chart/{chart_id}", f"chart/{chart_id}")
            mins.append(m)
            print(f"  chart/{chart_id}: survived lifecycle (min lit {m})")
        drill_min = _run_lifecycle(session, f"{base_url}{DRILLDOWN_PATH}", "drilldown")
        mins.append(drill_min)
        print(f"  drilldown: survived lifecycle (min lit {drill_min})")
        ready = _check_index_iframes(session, base_url)
        print(f"  index: {ready} iframes painted")
    print(
        f"lifecycle smoke OK: {len(GALLERY_IDS)} charts + drilldown x "
        f"{len(LIFECYCLE_PHASES)} phases, min lit pixels {min(mins)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
