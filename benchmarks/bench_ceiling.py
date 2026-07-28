#!/usr/bin/env python3
"""Interactive ceiling and peak-memory sweep across scatter libraries.

Answers two questions on one size ladder: how many source rows each library
can still *interact* with, and what peak resident memory that costs.

Every arm receives the complete row set — no arm is handed pre-thinned input.
What each library then does with those rows is recorded, not assumed:

  xy                 default behavior; a density grid above 200k rows
                     (config.SCATTER_DENSITY_THRESHOLD) plus an 8,192-row
                     retained sample.  Every row is counted into the grid.
  xy-exact           the same figure with density=False, so xy draws one
                     marker per row and its exact-marker ceiling is on the
                     same chart as its default one.
  plotly             plotly.express default render mode (scattergl above
                     1,000 rows); one marker per row.
  matplotlib         WebAgg interactive backend, server-side Agg; one marker
                     per row.
  datashader         Canvas.points aggregation to a screen-sized grid.  Every
                     row is counted, but the output is a static raster: there
                     is no client-side interaction without a live holoviews
                     or bokeh server, which is a different deployment
                     contract and is recorded as such.
  plotly-resampler   not applicable to unordered scatter — FigureResampler
                     asserts monotonically increasing x regardless of the
                     aggregator chosen.  Recorded as an explicit row so the
                     omission is visible rather than silent.

A cell counts as interactive only if it renders nonblank pixels *and* then
survives a scripted zoom/pan sequence.  A first frame that freezes on the
next gesture is not an interactive chart.

Two memory pools are kept apart on purpose: Plotly dies in the browser and
Matplotlib/WebAgg dies in Python, and one summed number would hide which.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psutil  # noqa: E402

import _launch_interactive as interactive  # noqa: E402
import _launch_webagg as webagg  # noqa: E402
from environment import collect_environment_metadata  # noqa: E402

WIDTH = interactive.WIDTH
HEIGHT = interactive.HEIGHT
ROOT = interactive.ROOT
ARTIFACTS = Path(tempfile.gettempdir()) / "xy-ceiling-artifacts"

# 10 anchors the fixed-overhead floor; 10k keeps every published launch
# baseline row comparable; the rest is the requested ladder.
DEFAULT_SIZES = [
    10,
    10_000,
    100_000,
    500_000,
    1_000_000,
    2_500_000,
    5_000_000,
    10_000_000,
    25_000_000,
    50_000_000,
    100_000_000,
]

# contract: what the user can actually do with the output.
#   interactive-webgl   client-side pan/zoom in the browser, no server
#   interactive-server  pan/zoom requires a live Python process
#   static-image        a raster; no interaction without extra infrastructure
ARMS: dict[str, dict[str, Any]] = {
    "xy": {"library": "xy", "contract": "interactive-webgl", "browser": "xy"},
    "xy-exact": {"library": "xy", "contract": "interactive-webgl", "browser": "xy"},
    "plotly": {"library": "plotly", "contract": "interactive-webgl", "browser": "plotly"},
    "matplotlib": {"library": "matplotlib", "contract": "interactive-server", "browser": None},
    "datashader": {"library": "datashader", "contract": "static-image", "browser": None},
    "plotly-resampler": {
        "library": "plotly_resampler",
        "contract": "interactive-server",
        "browser": None,
    },
}

GESTURE_STEPS = 24


class NotApplicable(RuntimeError):
    """The arm cannot express this workload at all."""


def gesture_js(steps: int) -> str:
    """Zoom in, pan across, zoom back out — one step per animation frame.

    Frame intervals are measured between successive animation frames rather
    than around the call, so asynchronous work (xy's standalone re-bin worker,
    Plotly's relayout promise) lands inside the number a user would feel.
    """
    return f"""
function gestureFactor(i) {{ return i < {steps} / 2 ? 0.88 : 1 / 0.88; }}
function gesturePan(i) {{ return ((i % 6) - 2.5) * 0.02; }}
const GESTURE_STEPS = {steps};
async function runGestures(applyStep) {{
  const frames = [];
  let blank = 0;
  let last = performance.now();
  for (let i = 0; i < GESTURE_STEPS; i++) {{
    await new Promise(r => requestAnimationFrame(r));
    const lit = await applyStep(i);
    const now = performance.now();
    frames.push(now - last);
    last = now;
    if (lit === 0) blank++;
  }}
  frames.sort((a, b) => a - b);
  const at = q => frames[Math.min(frames.length - 1, Math.floor(q * frames.length))];
  return {{
    gesture_steps: frames.length,
    gesture_median_ms: at(0.5),
    gesture_p95_ms: at(0.95),
    gesture_max_ms: frames[frames.length - 1],
    gesture_blank_frames: blank,
  }};
}}
"""


def visible_js() -> str:
    """The clock stops when every point is on screen, not at the first paint.

    Plotly's scattergl draws large scatters progressively across frames, so
    the frame that makes the page "ready" can hold a fraction of the markers.
    The honest completion signal is pixel quiescence: hash the full drawing
    buffer every animation frame and stop the clock at the *last observed
    change*, once the canvas has stayed byte-identical for STABLE_FRAMES
    consecutive frames.  A canvas still mutating after VISIBLE_DEADLINE_MS
    never finished rendering and is reported as such, not credited.
    """
    return r"""
const STABLE_FRAMES = 10;
const VISIBLE_DEADLINE_MS = 30000;
function frameHash(gl) {
  const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
  const px = new Uint8Array(w * h * 4);
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
  let hash = 5381 >>> 0, lit = 0;
  for (let i = 0; i < px.length; i += 4) {
    const v = (px[i] << 16) ^ (px[i + 1] << 8) ^ px[i + 2];
    if (v || px[i + 3]) lit++;
    hash = (((hash * 33) >>> 0) ^ v) >>> 0;
  }
  return {hash: hash, lit: lit};
}
async function waitVisibleComplete(sample) {
  let last = sample();
  let lastChange = performance.now();
  let stable = 0;
  const deadline = performance.now() + VISIBLE_DEADLINE_MS;
  while (performance.now() < deadline) {
    await new Promise(r => requestAnimationFrame(r));
    const cur = sample();
    if (cur.hash !== last.hash || cur.lit !== last.lit) {
      lastChange = performance.now();
      stable = 0;
    } else if (cur.lit > 0 && ++stable >= STABLE_FRAMES) {
      return {visible_complete_ms: lastChange, render_stable: true, lit_pixels: cur.lit};
    }
    last = cur;
  }
  return {visible_complete_ms: lastChange, render_stable: false, lit_pixels: last.lit};
}
"""


def xy_probe_html(fig: Any, steps: int) -> str:
    """xy standalone HTML with a first-render probe and a gesture sweep."""
    html = fig.to_html()
    needle = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    replacement = (
        'window.__benchView=xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    )
    if needle not in html:
        raise RuntimeError("xy standalone bootstrap changed")
    html = html.replace(needle, replacement, 1)
    probe = (
        "<script>"
        + interactive.gl_helpers()
        + visible_js()
        + gesture_js(steps)
        + r"""
(async()=>{try{
  await raf2();
  const view=window.__benchView;
  view._drawNow(); view.gl.finish();
  const first_frame_ms=performance.now();
  const first_nonblank=nonblank(view.gl);
  // Redraw before each readback: readPixels outside the producing task sees a
  // cleared buffer when preserveDrawingBuffer is off, and the redraw is what
  // folds any late-arriving async data into the hash.
  const complete=await waitVisibleComplete(()=>{
    view._drawNow(); view.gl.finish();
    return frameHash(view.gl);
  });
  const home={...view.view};
  const stats=await runGestures(async (i)=>{
    view._zoomAt(gestureFactor(i), 0.5+gesturePan(i), 0.5, false);
    view._drawNow(); view.gl.finish();
    return nonblank(view.gl);
  });
  view._setView(home,{animate:false,request:false});
  await raf2();
  view._drawNow(); view.gl.finish();
  const final_nonblank=nonblank(view.gl);
  document.title='XY_BENCH '+JSON.stringify(Object.assign({
    first_frame_ms:first_frame_ms, renderer:renderer(view.gl),
    nonblank_pixels:first_nonblank, final_nonblank_pixels:final_nonblank,
    js_heap_bytes:performance.memory?performance.memory.usedJSHeapSize:null
  }, complete, stats));
}catch(e){document.title='BENCH_ERROR '+String(e&&e.stack||e).slice(0,500);}})();
</script>"""
    )
    return html.replace("</body>", probe + "</body>", 1)


def plotly_probe_html(fig: Any, steps: int) -> str:
    """Plotly HTML with the same first-render probe and gesture sweep."""
    post = (
        interactive.gl_helpers()
        + visible_js()
        + gesture_js(steps)
        + r"""
(async()=>{try{
  const gd=document.getElementById('{plot_id}');
  await raf2();
  let gls=contexts(gd); for(const gl of gls) gl.finish();
  const first_frame_ms=performance.now();
  // Plotly Express only switches to WebGL above ~1000 rows; below that it
  // draws SVG markers and there is no canvas to read pixels back from, so
  // fall back to counting the marker nodes it actually put in the DOM.
  const lit=()=>{const c=contexts(gd); for(const g of c) g.finish();
                 if(c.length) return c.reduce((n,g)=>n+nonblank(g),0);
                 return gd.querySelectorAll('.scatterlayer .point').length;};
  const first_nonblank=lit();
  // Contexts are re-queried per frame: scattergl draws progressively and can
  // bring canvases up after the ready promise resolves.
  const complete=await waitVisibleComplete(()=>{
    const c=contexts(gd);
    if(!c.length){
      const nodes=gd.querySelectorAll('.scatterlayer .point').length;
      return {hash:nodes>>>0, lit:nodes};
    }
    let hash=5381>>>0, litSum=0;
    for(const g of c){ g.finish(); const s=frameHash(g); hash=(hash^s.hash)>>>0; litSum+=s.lit; }
    return {hash:hash, lit:litSum};
  });
  const fl=gd._fullLayout;
  const hx=[fl.xaxis.range[0],fl.xaxis.range[1]];
  const hy=[fl.yaxis.range[0],fl.yaxis.range[1]];
  const cx=(hx[0]+hx[1])/2, cy=(hy[0]+hy[1])/2;
  let hw=(hx[1]-hx[0])/2, hh=(hy[1]-hy[0])/2;
  const stats=await runGestures(async (i)=>{
    const f=gestureFactor(i); hw*=f; hh*=f;
    const sx=cx+(hx[1]-hx[0])*gesturePan(i);
    await Plotly.relayout(gd,{'xaxis.range':[sx-hw,sx+hw],'yaxis.range':[cy-hh,cy+hh]});
    return lit();
  });
  await Plotly.relayout(gd,{'xaxis.range':hx,'yaxis.range':hy});
  await raf2();
  const final_nonblank=lit();
  gls=contexts(gd);
  document.title='PLOTLY_BENCH '+JSON.stringify(Object.assign({
    first_frame_ms:first_frame_ms, renderer:renderer(gls[0]),
    nonblank_pixels:first_nonblank, final_nonblank_pixels:final_nonblank,
    js_heap_bytes:performance.memory?performance.memory.usedJSHeapSize:null
  }, complete, stats));
}catch(e){document.title='BENCH_ERROR '+String(e&&e.stack||e).slice(0,500);}})();
"""
    )
    return fig.to_html(include_plotlyjs=True, full_html=True, post_script=post)


def xy_oracle(fig: Any, n: int) -> dict[str, Any]:
    """Prove what xy's payload actually represents (benchmarks/README §Interpretation)."""
    import numpy as np

    spec, blob = fig.build_payload()
    trace = spec["traces"][0]
    tier = trace["tier"]
    if tier != "density":
        marks = trace.get("n_marks")
        if marks != n:
            raise AssertionError(f"xy direct-row oracle failed: {marks} != {n}")
        return {"mode": "direct", "oracle": "raw-row-count", "points_rendered": n}
    density = trace["density"]
    column = spec["columns"][density["buf"]]
    if int(trace["visible"]) != n:
        raise AssertionError(f"xy visible-count oracle failed: {trace['visible']} != {n}")
    dtype = np.uint8 if density.get("enc") == "log-u8" else np.float32
    grid = np.frombuffer(blob, dtype=dtype, count=column["len"], offset=column["byte_offset"])
    if density.get("enc") == "log-u8":
        if not np.any(grid) or int(grid.max()) != 255:
            raise AssertionError("xy quantized density oracle lost occupancy or maximum")
        oracle = "visible-count+quantized-density"
    else:
        total = int(round(float(grid.sum())))
        if total != n:
            raise AssertionError(f"xy count-conservation oracle failed: {total} != {n}")
        oracle = "count-conservation"
    return {
        "mode": "density",
        "oracle": oracle,
        "points_rendered": int(density["w"]) * int(density["h"]),
        "aggregate_dims": [int(density["w"]), int(density["h"])],
    }


def child_run(arm: str, n: int, artifact: Path | None) -> dict[str, Any]:
    """One arm at one size, in its own interpreter."""
    x, y = interactive.make_data(n)
    source_bytes = int(x.nbytes + y.nbytes)
    detail: dict[str, Any] = {}
    t0 = time.perf_counter()

    if arm in ("xy", "xy-exact"):
        from xy import scatter, scatter_chart

        exact = arm == "xy-exact"
        mark = scatter(x=x, y=y, density=False) if exact else scatter(x=x, y=y)
        fig = scatter_chart(mark, width=WIDTH, height=HEIGHT).figure()
        detail = xy_oracle(fig, n)
        if exact and detail["mode"] != "direct":
            raise AssertionError("xy-exact arm still aggregated")
        html = xy_probe_html(fig, GESTURE_STEPS)
        if artifact is None:
            raise ValueError("xy requires an artifact path")
        artifact.write_text(html, encoding="utf-8")
        detail["output_bytes"] = artifact.stat().st_size
    elif arm == "plotly":
        import plotly.express as px

        fig = px.scatter(x=x, y=y, width=WIDTH, height=HEIGHT)
        detail = {
            "mode": str(fig.data[0].type),
            "oracle": "raw-row-count",
            "points_rendered": n,
        }
        html = plotly_probe_html(fig, GESTURE_STEPS)
        if artifact is None:
            raise ValueError("Plotly requires an artifact path")
        artifact.write_text(html, encoding="utf-8")
        detail["output_bytes"] = artifact.stat().st_size
    elif arm == "datashader":
        import datashader as ds
        import datashader.transfer_functions as tf
        import pandas as pd

        frame = pd.DataFrame({"x": x, "y": y})
        canvas = ds.Canvas(plot_width=WIDTH, plot_height=HEIGHT)
        agg = canvas.points(frame, "x", "y")
        image = tf.shade(agg)
        total = int(agg.values.sum())
        if total != n:
            raise AssertionError(f"datashader count-conservation oracle failed: {total} != {n}")
        pil = image.to_pil()
        if pil.size != (WIDTH, HEIGHT):
            raise AssertionError(f"datashader raster size {pil.size}")
        detail = {
            "mode": "density",
            "oracle": "count-conservation",
            "points_rendered": WIDTH * HEIGHT,
            "aggregate_dims": [WIDTH, HEIGHT],
            "output_bytes": None,
        }
    elif arm == "plotly-resampler":
        # Documented refusal, measured rather than assumed: FigureResampler
        # asserts monotonically increasing x for every aggregator it ships.
        import plotly.graph_objects as go
        from plotly_resampler import FigureResampler

        try:
            fig = FigureResampler(go.Figure(), default_n_shown_samples=2000)
            fig.add_trace(go.Scattergl(mode="markers"), hf_x=x, hf_y=y)
        except AssertionError as exc:
            raise NotApplicable(str(exc)[:300]) from exc
        detail = {"mode": "resampled", "points_rendered": len(fig.data[0].x)}
    else:
        raise ValueError(arm)

    elapsed_ms = (time.perf_counter() - t0) * 1e3
    return {
        "status": "ok",
        "arm": arm,
        "n": n,
        "source_bytes": source_bytes,
        "python_build_ms": elapsed_ms,
        # The child's own high-water mark: exact, and immune to the 50 ms
        # sampling gap that the parent poller cannot close.  ru_maxrss is
        # bytes on macOS and KiB everywhere else, so normalize at the source
        # rather than shipping a field whose unit depends on the platform.
        "python_maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        **detail,
    }


def run_isolated(
    arm: str, n: int, *, timeout_s: float, memory_limit_bytes: int, artifact: Path | None
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        result_path = Path(td) / "result.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--child",
            "--arm",
            arm,
            "--n",
            str(n),
            "--child-out",
            str(result_path),
        ]
        if artifact is not None:
            command += ["--artifact", str(artifact)]
        popen = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        proc = psutil.Process(popen.pid)
        start = time.monotonic()
        peak = 0
        terminal = None
        while popen.poll() is None:
            rss = interactive.tree_rss(proc)
            peak = max(peak, rss)
            if rss > memory_limit_bytes:
                terminal = "memory_limit"
                interactive.terminate_tree(proc)
                break
            if time.monotonic() - start > timeout_s:
                terminal = "timeout"
                interactive.terminate_tree(proc)
                break
            time.sleep(0.05)
        stdout, stderr = popen.communicate()
        wall_ms = (time.monotonic() - start) * 1e3
        if terminal:
            return {
                "status": terminal,
                "arm": arm,
                "n": n,
                "wall_ms": wall_ms,
                "python_peak_rss_bytes": peak,
                "stderr_tail": stderr[-1000:],
            }
        if result_path.exists():
            row = json.loads(result_path.read_text())
            row["python_peak_rss_bytes"] = max(peak, int(row.get("python_maxrss_bytes", 0)))
            row["wall_ms"] = wall_ms
            return row
        status = (
            "not_applicable" if "NotApplicable" in stderr else f"failed(exit={popen.returncode})"
        )
        return {
            "status": status,
            "arm": arm,
            "n": n,
            "wall_ms": wall_ms,
            "python_peak_rss_bytes": peak,
            "stdout_tail": stdout[-500:],
            "stderr_tail": stderr[-2000:],
        }


def sweep(
    sizes: list[int],
    arms: list[str],
    *,
    timeout_s: float,
    memory_gib: float,
    software: bool,
    repetitions: int,
    keep_artifacts: bool = False,
) -> list[dict[str, Any]]:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    limit = int(memory_gib * 2**30)
    rows: list[dict[str, Any]] = []
    # Once an arm has failed, larger sizes are recorded as not attempted
    # instead of burning repetitions on a known corpse.
    ceiling_hit: dict[str, dict[str, Any]] = {}
    for n in sizes:
        for arm in arms:
            spec = ARMS[arm]
            if arm in ceiling_hit:
                rows.append(
                    {
                        "arm": arm,
                        "n": n,
                        "status": "not_attempted",
                        "reason": f"failed at n={ceiling_hit[arm]['n']} "
                        f"({ceiling_hit[arm]['status']})",
                        "contract": spec["contract"],
                    }
                )
                continue
            attempts: list[dict[str, Any]] = []
            for _ in range(repetitions):
                artifact = ARTIFACTS / f"{arm}-{n}.html" if spec["browser"] is not None else None
                if artifact is not None and artifact.exists():
                    artifact.unlink()
                if arm == "matplotlib":
                    row = webagg.benchmark_one(
                        n,
                        timeout_s=timeout_s,
                        memory_limit_bytes=limit,
                        software=software,
                    )
                    row.setdefault("arm", arm)
                    row.setdefault("n", n)
                    row["mode"] = "webagg-exact"
                    row["points_rendered"] = n
                    row["oracle"] = "raw-row-count"
                    if "end_to_end_ttfr_ms" in row:
                        row["ttfr_ms"] = row["end_to_end_ttfr_ms"]
                    # WebAgg interaction is a server round trip that pushes a
                    # fresh raster, not a client-side gesture; this harness
                    # does not drive it, so the arm's ceiling is judged on
                    # first render alone.  Stated, not silently equated.
                    row["gesture_measured"] = False
                else:
                    row = run_isolated(
                        arm,
                        n,
                        timeout_s=timeout_s,
                        memory_limit_bytes=limit,
                        artifact=artifact,
                    )
                    if row["status"] == "ok" and artifact is not None:
                        probe = interactive.browser_once(
                            artifact,
                            timeout_s=timeout_s,
                            memory_limit_bytes=limit,
                            software=software,
                        )
                        row["browser_probe"] = probe
                        row["browser_peak_rss_bytes"] = probe.get("browser_peak_rss_bytes")
                        row["gesture_measured"] = True
                        if probe.get("status") == "ok":
                            # The clock stops at visible-complete: the moment
                            # the canvas last changed before going pixel-stable,
                            # i.e. when every point was actually on screen.
                            # first_frame_ms is kept as a diagnostic; for
                            # progressive renderers the two differ widely.
                            row["ttfr_ms"] = float(row["python_build_ms"]) + float(
                                probe["visible_complete_ms"]
                            )
                            for key in (
                                "first_frame_ms",
                                "visible_complete_ms",
                                "render_stable",
                                "lit_pixels",
                                "gesture_median_ms",
                                "gesture_p95_ms",
                                "gesture_max_ms",
                                "gesture_blank_frames",
                                "gesture_steps",
                                "nonblank_pixels",
                                "final_nonblank_pixels",
                                "js_heap_bytes",
                                "renderer",
                            ):
                                if key in probe:
                                    row[key] = probe[key]
                            # Interactive means it drew everything, survived
                            # the whole gesture sequence, and still draws
                            # afterwards.  Intermediate gesture frames may
                            # legitimately be empty — a deep zoom can land on
                            # blank space, and at n=10 it usually does — so
                            # only the completed render and the restored home
                            # frame are required to be lit.
                            if not row.get("nonblank_pixels") and not row.get("lit_pixels"):
                                row["status"] = "blank_first_frame"
                            elif not row.get("render_stable"):
                                # Still mutating after the deadline: the
                                # render never finished putting points up.
                                row["status"] = "render_unstable"
                            elif row.get("gesture_steps") != GESTURE_STEPS:
                                row["status"] = "gesture_incomplete"
                            elif not row.get("final_nonblank_pixels"):
                                row["status"] = "blank_after_gestures"
                        else:
                            row["status"] = "browser_" + str(probe.get("status"))
                    elif row["status"] == "ok":
                        # No browser in this contract: the recorded time is a
                        # build time, not a time-to-first-interactive-frame.
                        row["build_only_ms"] = row.get("python_build_ms")
                        row["gesture_measured"] = False
                row["contract"] = spec["contract"]
                # Release the artifact as soon as its probe is done.  A single
                # 100M exact-marker page is 1.07 GB and a full ladder leaves
                # 3.2 GB behind, which does not fit a CI runner's disk.
                if artifact is not None and not keep_artifacts:
                    row["output_bytes"] = row.get("output_bytes") or (
                        artifact.stat().st_size if artifact.exists() else None
                    )
                    artifact.unlink(missing_ok=True)
                attempts.append(row)
                if row.get("status") != "ok":
                    break
            best = attempts[-1]
            ok = [a for a in attempts if a.get("status") == "ok"]
            summary = dict(ok[0] if ok else best)
            summary["attempts"] = len(attempts)
            summary["all_statuses"] = [a.get("status") for a in attempts]
            if ok:
                summary["python_peak_rss_bytes"] = max(
                    int(a.get("python_peak_rss_bytes") or 0) for a in ok
                )
                browser_peaks = [
                    int(a["browser_peak_rss_bytes"]) for a in ok if a.get("browser_peak_rss_bytes")
                ]
                if browser_peaks:
                    summary["browser_peak_rss_bytes"] = max(browser_peaks)
            else:
                # not_applicable is a property of the arm, not a size ceiling.
                if best.get("status") != "not_applicable":
                    ceiling_hit[arm] = {"n": n, "status": best.get("status")}
            rows.append(summary)
            print(
                json.dumps(
                    {
                        "arm": arm,
                        "n": n,
                        "status": summary.get("status"),
                        "mode": summary.get("mode"),
                        "python_peak_gib": round(
                            int(summary.get("python_peak_rss_bytes") or 0) / 2**30, 3
                        ),
                        "browser_peak_gib": round(
                            int(summary.get("browser_peak_rss_bytes") or 0) / 2**30, 3
                        ),
                        "ttfr_ms": summary.get("ttfr_ms"),
                        "gesture_p95_ms": summary.get("gesture_p95_ms"),
                    }
                ),
                flush=True,
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--arm", choices=tuple(ARMS))
    parser.add_argument("--n", type=int)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--child-out", type=Path)
    parser.add_argument("--sizes", default=",".join(str(n) for n in DEFAULT_SIZES))
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--memory-gib", type=float, default=36)
    parser.add_argument("--software", action="store_true")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="retain each cell's HTML page (a 100M exact-marker page is ~1 GB)",
    )
    parser.add_argument("--chrome", default=os.environ.get("CHROME", interactive.CHROME))
    parser.add_argument("--out", type=Path, required=False)
    args = parser.parse_args()

    if args.child:
        if args.arm is None or args.n is None or args.child_out is None:
            parser.error("child mode requires --arm, --n, and --child-out")
        try:
            result = child_run(args.arm, args.n, args.artifact)
        except NotApplicable as exc:
            sys.stderr.write(f"NotApplicable: {exc}\n")
            raise SystemExit(3) from exc
        args.child_out.write_text(json.dumps(result), encoding="utf-8")
        return

    if args.out is None:
        parser.error("--out is required")
    interactive.CHROME = args.chrome
    webagg.CHROME = args.chrome
    sizes = [int(v) for v in args.sizes.split(",")]
    arms = [v.strip() for v in args.arms.split(",") if v.strip()]
    unknown = sorted(set(arms) - set(ARMS))
    if unknown:
        parser.error(f"unknown arms: {', '.join(unknown)}")
    rows = sweep(
        sizes,
        arms,
        timeout_s=args.timeout,
        memory_gib=args.memory_gib,
        software=args.software,
        repetitions=args.repetitions,
        keep_artifacts=args.keep_artifacts,
    )
    report = {
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "method": {
            "question": "largest row count each library still renders interactively, "
            "and the peak resident memory that costs",
            "sizes": sizes,
            "arms": {a: ARMS[a] for a in arms},
            "source": "seeded correlated Gaussian float32 x/y (8 bytes per source row)",
            "input_thinning": "none; every arm receives all N rows",
            "viewport_css_px": [WIDTH, HEIGHT],
            "interactive_definition": (
                "render reaches pixel quiescence (canvas hash unchanged for 10 "
                f"consecutive frames) within 30 s, then {GESTURE_STEPS} scripted "
                "zoom/pan steps that all complete, then a nonblank frame again "
                "at the restored home view"
            ),
            "ttfr_definition": (
                "python build + visible_complete_ms: the last canvas change "
                "before pixel quiescence, i.e. when all points were actually on "
                "screen — not the first painted frame (first_frame_ms records "
                "that separately; scattergl renders large scatters progressively "
                "so the two differ). The WebAgg arm rasterizes all N server-side "
                "and pushes one complete frame, so its first nonblank frame is "
                "already all-points-visible by construction."
            ),
            "gesture_coverage": (
                "measured for the interactive-webgl arms only; the WebAgg arm's "
                "interaction is a server round trip this harness does not drive, "
                "so its ceiling reflects first render alone (gesture_measured=false)"
            ),
            "browser_baseline_note": (
                "a headless Chrome with an empty profile already resides ~1 GiB, so "
                "browser peaks must be read against the n=10 row of the same arm"
            ),
            "memory_pools": "python process tree and browser process tree reported separately",
            "python_peak_source": "max(50 ms tree poll, child getrusage RUSAGE_SELF high-water)",
            "browser_peak_source": "50 ms tree poll (brief spikes may be missed)",
            "repetitions": args.repetitions,
            "timeout_s_per_phase": args.timeout,
            "memory_limit_gib_per_process_tree": args.memory_gib,
            "browser_renderer_requested": "swiftshader-software"
            if args.software
            else "metal-default",
            "data_generation_excluded_from_build_ms": True,
            "early_abort": "sizes above a failure are recorded as not_attempted",
        },
        "environment": collect_environment_metadata(chromium=args.chrome),
        "results": rows,
    }
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
