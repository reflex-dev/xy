"""Reflex example chart lifecycle smoke for headless Chromium.

The Reflex demo embeds committed chart HTML assets in iframes. This smoke wraps
xy constructors inside each committed chart asset, then verifies every
target chart survives the lifecycle that has historically caused blank panels:
fresh browser loads, hash/scroll churn, visibility/resize events, responsive
width changes, iframe shell churn, remounts, and WebGL redraw/readback.

Usage: python scripts/reflex_lifecycle_smoke.py /path/to/chrome
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from xy.dom import CHART_DOM_SLOTS  # noqa: E402

CHART_DIR = ROOT / "examples" / "reflex" / "assets" / "charts"
CHROMIUM_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)

CHART_ASSETS = (
    "custom_chrome.html",
    "business_overview.html",
    "retention_cohort.html",
    "composed_layers.html",
    "axes_scales.html",
    "annotated_heatmap.html",
    "line_walk.html",
    "area.html",
    "bar_column.html",
    "histogram.html",
    "histogram_x_zoom.html",
    "heatmap.html",
    "colored_scatter.html",
    "density_scatter.html",
    "live_drilldown_10m.html",
    "live_drilldown_100m.html",
    "stacked_bar.html",
    "horizontal_bar.html",
    "normalized_bar.html",
    "diverging_bar.html",
    "rounded_goal_bar.html",
    "interaction_basics.html",
)

LIVE_CHART_ASSETS = (
    "live_drilldown_10m.html",
    "live_drilldown_100m.html",
)

CRITICAL_ASSETS = (
    "custom_chrome.html",
    "business_overview.html",
    "retention_cohort.html",
    "live_drilldown_10m.html",
    "live_drilldown_100m.html",
)

SHELL_ASSET_GROUPS = (
    tuple(asset for asset in CHART_ASSETS if asset not in LIVE_CHART_ASSETS),
    LIVE_CHART_ASSETS,
)

LIFECYCLE_PHASES = (
    "initial",
    "hash-navigation",
    "narrow-resize",
    "wide-resize",
    "scroll-bottom",
    "fast-scroll",
    "visibility-change",
    "context-restore",
    "restore",
)

SHELL_PHASES = (
    "iframe-initial",
    "iframe-remount",
    "iframe-reload",
    "iframe-hidden-reveal",
)

REQUIRED_RUNTIME_DOM_SLOTS = (
    "root",
    "chrome",
    "canvas",
    "labels",
    "tooltip",
)

BUNDLE_END = "window.xy = { render, renderStandalone, decodeFrame, ChartView, MARK_KINDS, markOf };\n})();\n</script>"

WRAP_SCRIPT_TEMPLATE = r"""
<script>
(() => {
  const views = [];
  const publicDomSlots = new Set(__XY_PUBLIC_DOM_SLOTS__);
  const requiredRuntimeDomSlots = __XY_REQUIRED_RUNTIME_DOM_SLOTS__;
  window.__xyLifecycleViews = views;

  function tick() {
    return new Promise((resolve) => setTimeout(resolve, 0));
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitFor(predicate, timeout = 2500) {
    const deadline = performance.now() + timeout;
    while (performance.now() < deadline) {
      if (predicate()) return true;
      await sleep(25);
    }
    return predicate();
  }

  function installLifecycleWrap() {
    const xy = window.xy;
    if (!xy || xy.__lifecycleWrapped) return false;
    xy.__lifecycleWrapped = true;

    const originalRenderStandalone = xy.renderStandalone;
    if (typeof originalRenderStandalone === "function") {
      xy.renderStandalone = function (...args) {
        const view = originalRenderStandalone.apply(this, args);
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
    return true;
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
    for (let i = 3; i < pixels.length; i += 4) {
      if (pixels[i] > 8) lit++;
    }
    return { lit, total: sampleW * sampleH };
  }

  function domSlotReport(view) {
    const counts = {};
    const unexpected = new Set();
    const missing = [];
    const root = view && view.root;
    if (!root) {
      return {
        counts,
        missing: requiredRuntimeDomSlots.slice(),
        unexpected: ["(missing-root)"],
      };
    }
    const nodes = [root, ...root.querySelectorAll("[data-xy-slot]")];
    for (const node of nodes) {
      const slot = node && node.dataset ? node.dataset.xySlot : "";
      if (!slot) continue;
      counts[slot] = (counts[slot] || 0) + 1;
      if (!publicDomSlots.has(slot)) unexpected.add(slot);
    }
    for (const slot of requiredRuntimeDomSlots) {
      if (!counts[slot]) missing.push(slot);
    }
    if (view.spec && view.spec.title && !counts.title) missing.push("title");
    return { counts, missing, unexpected: [...unexpected] };
  }

  async function forceContextRestore(view) {
    if (!view || !view.gl || !view.canvas) {
      throw new Error("cannot force WebGL context restore without a live view");
    }
    const loseExt = view.gl.getExtension("WEBGL_lose_context");
    if (!loseExt) {
      throw new Error("WEBGL_lose_context extension unavailable");
    }
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
    if (!lostOk) {
      throw new Error("webglcontextlost did not enter a loss or replacement recovery path");
    }
    if (!rebuilt()) {
      loseExt.restoreContext();
      const restoredOk = await waitFor(
        () => restoredSeen && view._glLost === false && view.gl && !view._destroyed,
        3500,
      );
      if (!restoredOk) {
        throw new Error("webglcontextrestored did not rebuild the view");
      }
    }
    await tick();
    await tick();
    view._syncContainerSize?.();
    view._drawNow?.();
  }

  window.__xyLifecycleCheck = async function () {
    await tick();
    await tick();
    const lifecyclePhases = [
      "initial",
      "hash-navigation",
      "narrow-resize",
      "wide-resize",
      "scroll-bottom",
      "fast-scroll",
      "visibility-change",
      "context-restore",
      "restore",
    ];
    const results = [];
    for (const view of views) {
      const oldWidth = view.root?.style.width || "";
      const oldScroll = { x: window.scrollX || 0, y: window.scrollY || 0 };
      const phases = [];
      const capture = (name) => {
        const pixels = litPixels(view);
        phases.push({
          name,
          lit: pixels.lit,
          total: pixels.total,
          canvas_width: view.canvas?.width || 0,
          canvas_height: view.canvas?.height || 0,
        });
      };
      capture("initial");
      location.hash = `lifecycle-${Date.now()}`;
      window.dispatchEvent(new HashChangeEvent("hashchange"));
      await tick();
      capture("hash-navigation");
      if (view.root) {
        view.root.style.width = "420px";
        view._syncContainerSize?.();
        window.dispatchEvent(new Event("resize"));
        await tick();
      }
      capture("narrow-resize");
      if (view.root) {
        view.root.style.width = "960px";
        view._syncContainerSize?.();
        window.dispatchEvent(new Event("resize"));
        await tick();
      }
      capture("wide-resize");
      window.scrollTo(0, document.body.scrollHeight);
      window.dispatchEvent(new Event("scroll"));
      await tick();
      capture("scroll-bottom");
      for (let i = 0; i < 12; i++) {
        window.scrollTo(0, i % 2 ? 0 : document.body.scrollHeight);
        window.dispatchEvent(new Event("scroll"));
        await tick();
      }
      capture("fast-scroll");
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new Event("focus"));
      await tick();
      capture("visibility-change");
      await forceContextRestore(view);
      capture("context-restore");
      if (view.root) view.root.style.width = oldWidth;
      window.scrollTo(oldScroll.x, oldScroll.y);
      view._syncContainerSize?.();
      window.dispatchEvent(new Event("resize"));
      await tick();
      capture("restore");
      const minLit = Math.min(...phases.map((phase) => phase.lit));
      const domSlots = domSlotReport(view);
      results.push({
        title: view.spec?.title || "",
        trace_count: view.spec?.traces?.length || 0,
        canvas_width: view.canvas?.width || 0,
        canvas_height: view.canvas?.height || 0,
        phase_names: phases.map((phase) => phase.name),
        phases,
        min_lit: minLit,
        label_count: view.labels?.children?.length || 0,
        dom_slots: domSlots,
        destroyed: !!view._destroyed,
      });
    }
    return { view_count: views.length, phase_names: lifecyclePhases, results };
  };

  async function runChildProbe() {
    try {
      for (let i = 0; i < 120 && views.length === 0; i++) await tick();
      location.hash = "lifecycle-smoke";
      window.scrollTo(0, document.body.scrollHeight);
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new Event("resize"));
      await tick();
      window.scrollTo(0, 0);
      const report = await window.__xyLifecycleCheck();
      const blank = report.results.find((r) =>
        r.destroyed || r.min_lit <= 8 ||
        r.phase_names.join("|") !== report.phase_names.join("|")
      );
      const badSlots = report.results.find((r) =>
        (r.dom_slots?.missing || []).length ||
        (r.dom_slots?.unexpected || []).length
      );
      if (!report.view_count || blank || badSlots) {
        throw new Error(JSON.stringify({ report, blank, badSlots }).slice(0, 900));
      }
      const missingSlots = report.results.flatMap((r) => r.dom_slots?.missing || []);
      const unexpectedSlots = report.results.flatMap((r) => r.dom_slots?.unexpected || []);
      const payload = {
        status: "ok",
        view_count: report.view_count,
        phase_names: report.phase_names,
        phase_count: report.phase_names.length,
        min_lit: Math.min(...report.results.map((r) => r.min_lit)),
        labels: report.results.reduce((sum, r) => sum + r.label_count, 0),
        slot_count: report.results.reduce(
          (sum, r) =>
            sum + Object.values(r.dom_slots?.counts || {}).reduce((a, b) => a + b, 0),
          0,
        ),
        missing_slots: missingSlots,
        unexpected_slots: unexpectedSlots,
      };
      document.body.setAttribute("data-xy-child-lifecycle", JSON.stringify(payload));
      window.parent?.postMessage({
        source: "xy-lifecycle-smoke",
        asset: decodeURIComponent(location.pathname.split("/").pop() || ""),
        phase: new URLSearchParams(location.search).get("phase") || "standalone",
        payload,
      }, "*");
    } catch (err) {
      const payload = (err && err.stack ? err.stack : String(err)).slice(0, 1200);
      document.body.setAttribute("data-xy-child-lifecycle-error", payload);
      window.parent?.postMessage({
        source: "xy-lifecycle-smoke",
        asset: decodeURIComponent(location.pathname.split("/").pop() || ""),
        phase: new URLSearchParams(location.search).get("phase") || "standalone",
        error: payload,
      }, "*");
    }
  }

  if (!installLifecycleWrap()) {
    window.__xyLifecycleInstallFailed = true;
  }
  const deferProbe = new URLSearchParams(location.search).get("defer_probe") === "1";
  let probeStarted = false;
  function startProbeOnce() {
    if (probeStarted) return;
    probeStarted = true;
    setTimeout(runChildProbe, 0);
  }
  window.addEventListener("message", (event) => {
    const data = event.data || {};
    if (
      data.source === "xy-lifecycle-parent" &&
      data.command === "run-probe"
    ) {
      startProbeOnce();
    }
  });
  if (!deferProbe) startProbeOnce();
})();
</script>
"""

WRAP_SCRIPT = WRAP_SCRIPT_TEMPLATE.replace(
    "__XY_PUBLIC_DOM_SLOTS__",
    json.dumps(list(CHART_DOM_SLOTS)),
).replace(
    "__XY_REQUIRED_RUNTIME_DOM_SLOTS__",
    json.dumps(list(REQUIRED_RUNTIME_DOM_SLOTS)),
)


def find_chromium(explicit: str | None = None) -> str:
    candidates = ([explicit] if explicit else []) + list(CHROMIUM_CANDIDATES)
    for candidate in candidates:
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return candidate
    raise SystemExit("no chromium binary found; pass one as argv[1]")


def _inject_child_probe(source: str, asset: str) -> str:
    if "window.xy = {" not in source:
        raise ValueError(f"{asset}: not a xy standalone asset")
    if BUNDLE_END not in source:
        raise ValueError(f"{asset}: cannot find standalone bundle boundary")
    return source.replace(BUNDLE_END, BUNDLE_END + WRAP_SCRIPT, 1)


def _write_child_assets(tmp: Path) -> list[Path]:
    paths = []
    for asset in CHART_ASSETS:
        source_path = CHART_DIR / asset
        source = source_path.read_text(encoding="utf-8")
        out = tmp / asset
        out.write_text(_inject_child_probe(source, asset), encoding="utf-8")
        paths.append(out)
    return paths


def _write_shell_page(
    tmp: Path,
    children: list[Path],
    critical_assets: tuple[str, ...] = CRITICAL_ASSETS,
) -> Path:
    assets = [child.name for child in children]
    critical_target_ids = [
        asset.removesuffix(".html").replace("_", "-") for asset in critical_assets
    ]
    page = tmp / "iframe_lifecycle_shell.html"
    page.write_text(
        f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>xy iframe lifecycle shell</title>
  <style>
    body {{ margin: 0; font-family: sans-serif; background: #f8fafc; }}
    #viewport {{
      display: grid;
      grid-template-columns: repeat(2, minmax(360px, 1fr));
      gap: 16px;
      padding: 24px;
      min-height: 2400px;
    }}
    section {{ min-height: 360px; background: white; border: 1px solid #dbe3ef; }}
    iframe {{ display: block; width: 100%; height: 340px; border: 0; }}
    .narrow iframe {{ width: 62%; }}
    #viewport.hidden-boot section {{
      width: 0;
      min-height: 0;
      height: 0;
      border: 0;
      overflow: hidden;
      visibility: hidden;
    }}
    #viewport.hidden-boot iframe {{ width: 0; height: 0; }}
  </style>
</head>
<body>
  <div id="viewport"></div>
  <script>
    const assets = {json.dumps(assets)};
    const criticalAssets = new Set({json.dumps(list(critical_assets))});
    const criticalTargetIds = {json.dumps(critical_target_ids)};
    const viewport = document.getElementById("viewport");
    const reports = [];
    let activePhase = "";
    let keepAliveTick = 0;
    const keepAlive = setInterval(() => {{
      document.body.setAttribute("data-xy-shell-tick", String(++keepAliveTick));
    }}, 250);

    function nextFrame() {{
      return new Promise((resolve) => setTimeout(resolve, 16));
    }}

    function sleep(ms) {{
      return new Promise((resolve) => setTimeout(resolve, ms));
    }}

    function mount(phase, options = {{}}) {{
      viewport.textContent = "";
      viewport.classList.toggle("hidden-boot", !!options.hiddenBoot);
      activePhase = phase;
      const deferProbe = options.hiddenBoot || options.deferProbe;
      for (const [index, asset] of assets.entries()) {{
        const section = document.createElement("section");
        section.id = asset.replace(/\\.html$/, "").replace(/_/g, "-");
        const iframe = document.createElement("iframe");
        iframe.loading = "eager";
        iframe.setAttribute("data-asset", asset);
        iframe.src =
          `${{asset}}?phase=${{encodeURIComponent(phase)}}` +
          `&slot=${{index}}&defer_probe=${{deferProbe ? "1" : "0"}}#${{section.id}}`;
        section.appendChild(iframe);
        viewport.appendChild(section);
      }}
    }}

    async function revealHiddenBoot(phase) {{
      viewport.classList.remove("hidden-boot");
      window.dispatchEvent(new Event("resize"));
      await nextFrame();
      await sleep(80);
      for (const iframe of viewport.querySelectorAll("iframe")) {{
        iframe.contentWindow?.postMessage({{
          source: "xy-lifecycle-parent",
          command: "run-probe",
          phase,
        }}, "*");
      }}
      window.dispatchEvent(new Event("resize"));
      document.dispatchEvent(new Event("visibilitychange"));
      await nextFrame();
    }}

    async function reloadIframes(phase) {{
      for (const iframe of viewport.querySelectorAll("iframe")) {{
        const url = new URL(iframe.src, location.href);
        url.searchParams.set("phase", phase);
        url.searchParams.set("defer_probe", "0");
        url.searchParams.set("reload", "1");
        url.hash = iframe.parentElement?.id || "";
        iframe.src = url.toString();
      }}
      window.dispatchEvent(new Event("resize"));
      document.dispatchEvent(new Event("visibilitychange"));
      await nextFrame();
      await sleep(80);
    }}

    async function churnShell(phase) {{
      for (let i = 0; i < 10; i++) {{
        location.hash = `${{phase}}-${{i}}`;
        document.body.classList.toggle("narrow", i % 2 === 0);
        window.dispatchEvent(new Event("resize"));
        document.dispatchEvent(new Event("visibilitychange"));
        window.scrollTo(0, i % 2 ? 0 : document.body.scrollHeight);
        await nextFrame();
        await sleep(20);
      }}
      for (const id of criticalTargetIds) {{
        location.hash = id;
        document.getElementById(id)?.scrollIntoView({{ block: "start", inline: "nearest" }});
        window.dispatchEvent(new HashChangeEvent("hashchange"));
        window.dispatchEvent(new Event("resize"));
        await nextFrame();
        await sleep(20);
      }}
      document.body.classList.remove("narrow");
      window.dispatchEvent(new Event("resize"));
      window.scrollTo(0, 0);
    }}

    function waitForPhase(phase) {{
      const seen = new Map();
      return new Promise((resolve, reject) => {{
        let ticks = 0;
        const timer = setTimeout(() => {{
          clearInterval(poll);
          const missing = assets.filter((asset) => !seen.has(asset));
          reject(new Error(
            `${{phase}} timed out after ${{seen.size}}/${{assets.length}} reports; missing=${{missing.join(",")}}`
          ));
        }}, 45000);
        const poll = setInterval(() => {{
          ticks++;
          document.body.setAttribute("data-xy-shell-poll", `${{phase}}:${{ticks}}:${{seen.size}}`);
          for (const iframe of viewport.querySelectorAll("iframe")) {{
            const asset = iframe.getAttribute("data-asset");
            if (!asset || seen.has(asset)) continue;
            let body;
            try {{
              body = iframe.contentDocument && iframe.contentDocument.body;
            }} catch (err) {{
              clearTimeout(timer);
              clearInterval(poll);
              reject(new Error(`${{phase}}/${{asset}} inaccessible iframe: ${{err && err.message || err}}`));
              return;
            }}
            if (!body) continue;
            const error = body.getAttribute("data-xy-child-lifecycle-error");
            if (error) {{
              clearTimeout(timer);
              clearInterval(poll);
              reject(new Error(`${{phase}}/${{asset}}: ${{error}}`));
              return;
            }}
            const raw = body.getAttribute("data-xy-child-lifecycle");
            if (!raw) continue;
            let payload;
            try {{
              payload = JSON.parse(raw);
            }} catch (err) {{
              clearTimeout(timer);
              clearInterval(poll);
              reject(new Error(`${{phase}}/${{asset}} bad payload: ${{raw.slice(0, 240)}}`));
              return;
            }}
            seen.set(asset, payload);
          }}
          if (seen.size === assets.length) {{
            clearTimeout(timer);
            clearInterval(poll);
            resolve([...seen.entries()].map(([asset, payload]) => ({{ asset, payload }})));
          }}
        }}, 100);
      }});
    }}

    async function run() {{
      try {{
        const shellPhases = [
          {{ name: "iframe-initial", hiddenBoot: false }},
          {{ name: "iframe-remount", hiddenBoot: false }},
          {{ name: "iframe-reload", hiddenBoot: false, reloadInPlace: true }},
          {{ name: "iframe-hidden-reveal", hiddenBoot: true }},
        ];
        for (const phase of shellPhases) {{
          const waiting = waitForPhase(phase.name);
          mount(phase.name, {{
            hiddenBoot: phase.hiddenBoot,
            deferProbe: phase.reloadInPlace,
          }});
          await churnShell(phase.name);
          if (phase.reloadInPlace) await reloadIframes(phase.name);
          if (phase.hiddenBoot) await revealHiddenBoot(phase.name);
          const phaseReports = await waiting;
          reports.push({{ phase: phase.name, reports: phaseReports }});
          viewport.textContent = "";
          viewport.classList.remove("hidden-boot");
          await nextFrame();
          await sleep(80);
        }}
        const flat = reports.flatMap((phase) => phase.reports.map((r) => r.payload));
        const criticalReports = reports.flatMap((phase) =>
          phase.reports
            .filter((r) => criticalAssets.has(r.asset))
            .map((r) => `${{phase.phase}}:${{r.asset}}`)
        );
        const expectedCriticalReports = criticalAssets.size * reports.length;
        if (criticalReports.length !== expectedCriticalReports) {{
          throw new Error(
            `critical lifecycle coverage incomplete: ` +
            `${{criticalReports.length}}/${{expectedCriticalReports}} ` +
            `reports=${{criticalReports.join(",")}}`
          );
        }}
        const minLit = Math.min(...flat.map((payload) => Number(payload.min_lit || 0)));
        const labels = flat.reduce((sum, payload) => sum + Number(payload.labels || 0), 0);
        const slotCount = flat.reduce((sum, payload) => sum + Number(payload.slot_count || 0), 0);
        if (!(minLit > 8)) throw new Error(`blank shell probe min_lit=${{minLit}}`);
        if (!(slotCount > 0)) throw new Error("shell DOM slot probe found no public slots");
        document.body.setAttribute("data-xy-shell-lifecycle", JSON.stringify({{
          status: "ok",
          phases: reports.length,
          phase_names: reports.map((phase) => phase.phase),
          assets: assets.length,
          reports: flat.length,
          min_lit: minLit,
          labels,
          slot_count: slotCount,
          critical_assets: [...criticalAssets],
          critical_reports: criticalReports.length,
          critical_report_names: criticalReports,
          active_phase: activePhase,
        }}));
        clearInterval(keepAlive);
      }} catch (err) {{
        document.body.setAttribute(
          "data-xy-shell-lifecycle-error",
          String(err && err.stack ? err.stack : err).slice(0, 1200),
        );
        clearInterval(keepAlive);
      }}
    }}

    run();
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return page


def _run_page(chromium: str, page: Path) -> str:
    completed = subprocess.run(
        [
            chromium,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--allow-file-access-from-files",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--hide-scrollbars",
            "--window-size=1280,900",
            "--virtual-time-budget=60000",
            "--dump-dom",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip().splitlines()
        raise SystemExit(f"chromium failed with {completed.returncode}: {stderr[-3:]}")
    return completed.stdout


def _html_attr_json(dom: str, attr: str) -> dict[str, object] | None:
    match = re.search(rf"<body\b[^>]*{re.escape(attr)}=\"([^\"]*)\"", dom)
    if not match:
        return None
    return json.loads(html.unescape(match.group(1)))


def _child_result(dom: str, asset: str) -> dict[str, object]:
    error = re.search(r"<body\b[^>]*data-xy-child-lifecycle-error=\"([^\"]*)\"", dom)
    if error:
        raise SystemExit(f"{asset}: {html.unescape(error.group(1))}")
    payload = _html_attr_json(dom, "data-xy-child-lifecycle")
    if payload is None:
        title_match = re.search(r"<title>(.*?)</title>", dom, flags=re.IGNORECASE | re.S)
        title = html.unescape(title_match.group(1).strip()) if title_match else "(no title)"
        raise SystemExit(f"{asset}: lifecycle probe did not finish (title={title!r})")
    if payload.get("status") != "ok":
        raise SystemExit(f"{asset}: lifecycle smoke failed: {payload}")
    if payload.get("phase_names") != list(LIFECYCLE_PHASES):
        raise SystemExit(f"{asset}: lifecycle phases incomplete: {payload}")
    if payload.get("phase_count") != len(LIFECYCLE_PHASES):
        raise SystemExit(f"{asset}: lifecycle phase count mismatch: {payload}")
    if int(payload.get("slot_count") or 0) <= 0:
        raise SystemExit(f"{asset}: lifecycle DOM slot probe found no public slots: {payload}")
    if payload.get("missing_slots"):
        raise SystemExit(f"{asset}: lifecycle DOM slot probe found missing slots: {payload}")
    if payload.get("unexpected_slots"):
        raise SystemExit(f"{asset}: lifecycle DOM slot probe found unexpected slots: {payload}")
    return payload


def _shell_result(
    dom: str,
    asset_count: int,
    critical_assets: tuple[str, ...] = CRITICAL_ASSETS,
) -> dict[str, object]:
    error = re.search(r"<body\b[^>]*data-xy-shell-lifecycle-error=\"([^\"]*)\"", dom)
    if error:
        raise SystemExit(f"iframe shell: {html.unescape(error.group(1))}")
    payload = _html_attr_json(dom, "data-xy-shell-lifecycle")
    if payload is None:
        raise SystemExit("iframe shell: lifecycle probe did not finish")
    if payload.get("status") != "ok":
        raise SystemExit(f"iframe shell lifecycle smoke failed: {payload}")
    if payload.get("assets") != asset_count or payload.get("phases") != len(SHELL_PHASES):
        raise SystemExit(f"iframe shell lifecycle smoke incomplete: {payload}")
    if payload.get("phase_names") != list(SHELL_PHASES):
        raise SystemExit(f"iframe shell lifecycle phases incomplete: {payload}")
    expected_reports = asset_count * len(SHELL_PHASES)
    if payload.get("reports") != expected_reports:
        raise SystemExit(f"iframe shell asset reports incomplete: {payload}")
    if sorted(payload.get("critical_assets", [])) != sorted(critical_assets):
        raise SystemExit(f"iframe shell critical asset coverage mismatch: {payload}")
    expected_critical_reports = len(critical_assets) * int(payload["phases"])
    if payload.get("critical_reports") != expected_critical_reports:
        raise SystemExit(f"iframe shell critical asset reports incomplete: {payload}")
    expected_critical_report_names = sorted(
        f"{phase}:{asset}" for phase in SHELL_PHASES for asset in critical_assets
    )
    if sorted(payload.get("critical_report_names", [])) != expected_critical_report_names:
        raise SystemExit(f"iframe shell critical asset phase coverage incomplete: {payload}")
    if int(payload.get("slot_count") or 0) <= 0:
        raise SystemExit(f"iframe shell DOM slot probe found no public slots: {payload}")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    chromium = find_chromium(args[0] if args else None)
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        children = _write_child_assets(tmp)
        children_by_name = {child.name: child for child in children}
        for pass_index in range(2):
            pass_min: int | None = None
            for child in children:
                payload = _child_result(_run_page(chromium, child), child.name)
                results.append(payload)
                lit = int(payload["min_lit"])
                pass_min = lit if pass_min is None else min(pass_min, lit)
            print(f"probe pass {pass_index + 1}: {len(children)} charts, min lit pixels {pass_min}")
        shell_payloads: list[dict[str, object]] = []
        for group_index, group in enumerate(SHELL_ASSET_GROUPS, start=1):
            group_children = [children_by_name[asset] for asset in group]
            critical_assets = tuple(asset for asset in CRITICAL_ASSETS if asset in group)
            shell = _write_shell_page(tmp, group_children, critical_assets)
            shell_payload = _shell_result(
                _run_page(chromium, shell), len(group_children), critical_assets
            )
            shell_payloads.append(shell_payload)
            print(
                f"iframe shell {group_index}: "
                f"{shell_payload['assets']} charts x {shell_payload['phases']} "
                "mounts/reloads/reveals, "
                f"min lit pixels {shell_payload['min_lit']}"
            )

    print(
        "reflex lifecycle smoke OK: "
        f"{len(CHART_ASSETS)} charts x 2 loads, "
        f"{len(shell_payloads)} iframe remount/reload/hidden-reveal shells, "
        f"min lit pixels {min(result['min_lit'] for result in results)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
