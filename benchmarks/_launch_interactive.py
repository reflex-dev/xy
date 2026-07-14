#!/usr/bin/env python3
"""Default-behavior scatter sweep: xy, Plotly Express, and Matplotlib.

Each library receives the same float32 source arrays through its normal public
scatter API.  xy is allowed to use its automatic LOD behavior; Plotly Express
is allowed to choose its default render mode; Matplotlib uses its default Agg
scatter path.  Large cases run in isolated processes with hard time/RSS caps.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import io
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psutil
import websocket

WIDTH = 900
HEIGHT = 420
DPI = 100
SEED = 20260713
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = Path(tempfile.gettempdir()) / "xy-launch-scatter-artifacts"
DEFAULT_SIZES = [10_000, 100_000, 1_000_000, 10_000_000, 100_000_000, 1_000_000_000]


def make_data(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Two-array-only correlated float32 workload (8 bytes/source row)."""
    rng = np.random.default_rng(SEED)
    x = rng.standard_normal(n, dtype=np.float32)
    y = rng.standard_normal(n, dtype=np.float32)
    # y = 0.5*x + 0.6*noise, entirely in-place to keep the 1B source at 8 GB.
    y *= np.float32(1.2)
    y += x
    y *= np.float32(0.5)
    return x, y


def gl_helpers() -> str:
    return r"""
function raf2() {
  return new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}
function glFor(canvas) {
  return canvas && (canvas.getContext('webgl2') || canvas.getContext('webgl') ||
                    canvas.getContext('experimental-webgl'));
}
function contexts(root) {
  const out = [];
  for (const canvas of root.querySelectorAll('canvas')) {
    const gl = glFor(canvas);
    if (gl && !out.includes(gl)) out.push(gl);
  }
  return out;
}
function renderer(gl) {
  if (!gl) return null;
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
}
function nonblank(gl) {
  if (!gl) return 0;
  const w = Math.max(1, Math.min(128, gl.drawingBufferWidth));
  const h = Math.max(1, Math.min(128, gl.drawingBufferHeight));
  const pixels = new Uint8Array(w * h * 4);
  gl.readPixels(Math.max(0, (gl.drawingBufferWidth-w)>>1),
                Math.max(0, (gl.drawingBufferHeight-h)>>1),
                w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  let count = 0;
  for (let i=0; i<pixels.length; i+=4)
    if (pixels[i] || pixels[i+1] || pixels[i+2] || pixels[i+3]) count++;
  return count;
}
"""


def xy_probe_html(fig: Any) -> str:
    html = fig.to_html()
    needle = 'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);'
    replacement = (
        "window.__benchView=xy.renderStandalone("
        'document.getElementById("chart"), spec, bytes.buffer);'
    )
    if needle not in html:
        raise RuntimeError("xy standalone bootstrap changed")
    html = html.replace(needle, replacement, 1)
    probe = (
        "<script>"
        + gl_helpers()
        + r"""
(async()=>{try{
  await raf2();
  const view=window.__benchView;
  view._drawNow(); view.gl.finish();
  document.title='XY_BENCH '+JSON.stringify({
    ready_ms:performance.now(), renderer:renderer(view.gl),
    nonblank_pixels:nonblank(view.gl),
    js_heap_bytes:performance.memory?performance.memory.usedJSHeapSize:null
  });
}catch(e){document.title='BENCH_ERROR '+String(e&&e.stack||e).slice(0,500);}})();
</script>"""
    )
    return html.replace("</body>", probe + "</body>", 1)


def plotly_probe_html(fig: Any) -> str:
    post = (
        gl_helpers()
        + r"""
(async()=>{try{
  const gd=document.getElementById('{plot_id}');
  await raf2();
  const gls=contexts(gd); for(const gl of gls) gl.finish();
  document.title='PLOTLY_BENCH '+JSON.stringify({
    ready_ms:performance.now(), renderer:renderer(gls[0]),
    nonblank_pixels:gls.reduce((n,gl)=>n+nonblank(gl),0),
    js_heap_bytes:performance.memory?performance.memory.usedJSHeapSize:null
  });
}catch(e){document.title='BENCH_ERROR '+String(e&&e.stack||e).slice(0,500);}})();
"""
    )
    # No render_mode or performance config: this is Plotly Express's default.
    return fig.to_html(include_plotlyjs=True, full_html=True, post_script=post)


def child_run(library: str, n: int, artifact: Path | None) -> dict[str, Any]:
    # Imports are intentionally outside TTFR: the metric starts with source
    # arrays ready, matching the existing exact-render benchmark and normal
    # repeated plotting work. Their resident memory remains included.
    if library == "xy":
        from xy import scatter, scatter_chart
    elif library == "plotly":
        import plotly.express as px
    elif library == "matplotlib":
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from PIL import Image
    else:
        raise ValueError(library)

    process = psutil.Process()
    x, y = make_data(n)
    source_rss = process.memory_info().rss
    source_bytes = int(x.nbytes + y.nbytes)
    t0 = time.perf_counter()

    if library == "xy":
        fig = scatter_chart(scatter(x=x, y=y), width=WIDTH, height=HEIGHT).figure()
        html = xy_probe_html(fig)
        mode = "density" if fig.traces[0].use_density() else "direct"
        if artifact is None:
            raise ValueError("xy requires an artifact path")
        with artifact.open("w", encoding="utf-8") as handle:
            handle.write(html)
        output_bytes = artifact.stat().st_size
        nonblank = None
    elif library == "plotly":
        # render_mode is intentionally omitted: px.scatter defaults to "auto".
        fig = px.scatter(x=x, y=y, width=WIDTH, height=HEIGHT)
        mode = str(fig.data[0].type)
        html = plotly_probe_html(fig)
        if artifact is None:
            raise ValueError("Plotly requires an artifact path")
        with artifact.open("w", encoding="utf-8") as handle:
            handle.write(html)
        output_bytes = artifact.stat().st_size
        nonblank = None
    elif library == "matplotlib":
        fig, ax = plt.subplots(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
        ax.scatter(x, y)
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        plt.close(fig)
        output_bytes = buffer.getbuffer().nbytes
        buffer.seek(0)
        image = np.asarray(Image.open(buffer).convert("RGB"))
        nonblank = int(np.count_nonzero(np.any(image != image[0, 0], axis=2)))
        if nonblank == 0:
            raise AssertionError("Matplotlib produced a blank raster")
        mode = "static-agg"
    elapsed_ms = (time.perf_counter() - t0) * 1e3
    return {
        "status": "ok",
        "library": library,
        "n": n,
        "source_bytes": source_bytes,
        "source_rss_bytes": source_rss,
        "python_render_ms": elapsed_ms,
        "output_bytes": output_bytes,
        "mode": mode,
        "nonblank_pixels": nonblank,
    }


def tree_rss(process: psutil.Process) -> int:
    total = 0
    for proc in [process, *process.children(recursive=True)]:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            total += proc.memory_info().rss
    return total


def terminate_tree(process: psutil.Process) -> None:
    descendants = process.children(recursive=True)
    for proc in reversed(descendants):
        with contextlib.suppress(psutil.NoSuchProcess):
            proc.kill()
    with contextlib.suppress(psutil.NoSuchProcess):
        process.kill()


def run_isolated(
    library: str,
    n: int,
    *,
    timeout_s: float,
    memory_limit_bytes: int,
    artifact: Path | None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        result_path = Path(td) / "result.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--child",
            "--library",
            library,
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
        terminal_status = None
        while popen.poll() is None:
            rss = tree_rss(proc)
            peak = max(peak, rss)
            if rss > memory_limit_bytes:
                terminal_status = "memory_limit"
                terminate_tree(proc)
                break
            if time.monotonic() - start > timeout_s:
                terminal_status = "timeout"
                terminate_tree(proc)
                break
            time.sleep(0.05)
        stdout, stderr = popen.communicate()
        if terminal_status:
            return {
                "status": terminal_status,
                "library": library,
                "n": n,
                "wall_ms": (time.monotonic() - start) * 1e3,
                "python_peak_rss_bytes": peak,
                "stderr_tail": stderr[-1000:],
            }
        if popen.returncode != 0 or not result_path.exists():
            return {
                "status": f"failed(exit={popen.returncode})",
                "library": library,
                "n": n,
                "wall_ms": (time.monotonic() - start) * 1e3,
                "python_peak_rss_bytes": peak,
                "stdout_tail": stdout[-1000:],
                "stderr_tail": stderr[-2000:],
            }
        result = json.loads(result_path.read_text())
        result["python_peak_rss_bytes"] = peak
        result["wall_ms"] = (time.monotonic() - start) * 1e3
        return result


def wait_devtools(profile: Path, popen: subprocess.Popen[str]) -> int:
    active = profile / "DevToolsActivePort"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if active.exists():
            lines = active.read_text().splitlines()
            if lines:
                return int(lines[0])
        if popen.poll() is not None:
            raise RuntimeError("Chrome exited before DevTools became available")
        time.sleep(0.02)
    raise TimeoutError("Chrome DevTools startup timeout")


def browser_once(
    artifact: Path,
    *,
    timeout_s: float,
    memory_limit_bytes: int,
    software: bool = False,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        profile = Path(td) / "profile"
        command = [
            CHROME,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--enable-precise-memory-info",
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            "--force-device-scale-factor=1",
            "--window-size=1100,600",
            f"--user-data-dir={profile}",
            artifact.resolve().as_uri(),
        ]
        if software:
            command[1:1] = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        else:
            command[1:1] = ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"]
        popen = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
        )
        proc = psutil.Process(popen.pid)
        start = time.monotonic()
        peak = 0
        ws = None
        try:
            port = wait_devtools(profile, popen)
            target = None
            while time.monotonic() - start < timeout_s:
                peak = max(peak, tree_rss(proc))
                if peak > memory_limit_bytes:
                    raise MemoryError("browser memory limit")
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    targets = json.load(r)
                target = next((item for item in targets if item.get("type") == "page"), None)
                if target:
                    break
                time.sleep(0.02)
            if not target:
                raise TimeoutError("Chrome page target timeout")
            ws = websocket.create_connection(
                target["webSocketDebuggerUrl"], timeout=min(30, timeout_s)
            )
            call_id = 0
            title = ""
            while time.monotonic() - start < timeout_s:
                rss = tree_rss(proc)
                peak = max(peak, rss)
                if rss > memory_limit_bytes:
                    raise MemoryError("browser memory limit")
                call_id += 1
                ws.send(
                    json.dumps(
                        {
                            "id": call_id,
                            "method": "Runtime.evaluate",
                            "params": {"expression": "document.title", "returnByValue": True},
                        }
                    )
                )
                while True:
                    message = json.loads(ws.recv())
                    if message.get("id") == call_id:
                        break
                title = message.get("result", {}).get("result", {}).get("value", "")
                if title.startswith(("XY_BENCH ", "PLOTLY_BENCH ")):
                    result = json.loads(title.split(" ", 1)[1])
                    result.update(
                        {
                            "status": "ok",
                            "browser_peak_rss_bytes": peak,
                            "browser_wall_ms": (time.monotonic() - start) * 1e3,
                        }
                    )
                    return result
                if title.startswith("BENCH_ERROR "):
                    raise RuntimeError(title)
                time.sleep(0.02)
            raise TimeoutError(f"browser timeout; last title={title!r}")
        except MemoryError as exc:
            return {"status": "memory_limit", "browser_peak_rss_bytes": peak, "error": str(exc)}
        except TimeoutError as exc:
            return {"status": "timeout", "browser_peak_rss_bytes": peak, "error": str(exc)}
        except Exception as exc:
            return {
                "status": f"failed({type(exc).__name__})",
                "browser_peak_rss_bytes": peak,
                "error": str(exc)[:1000],
            }
        finally:
            if ws is not None:
                ws.close()
            terminate_tree(proc)
            try:
                popen.wait(timeout=5)
            except subprocess.TimeoutExpired:
                popen.kill()


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def run_sweep(
    sizes: list[int],
    *,
    timeout_s: float,
    memory_gib: float,
    browser_reps: int,
    libraries: list[str],
    software: bool,
) -> dict[str, Any]:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    limit = int(memory_gib * 2**30)
    results: list[dict[str, Any]] = []
    for n in sizes:
        for library in libraries:
            artifact = ARTIFACTS / f"{library}-{n}.html" if library != "matplotlib" else None
            if artifact and artifact.exists():
                artifact.unlink()
            row = run_isolated(
                library,
                n,
                timeout_s=timeout_s,
                memory_limit_bytes=limit,
                artifact=artifact,
            )
            if row["status"] == "ok" and artifact is not None:
                probes = [
                    browser_once(
                        artifact,
                        timeout_s=timeout_s,
                        memory_limit_bytes=limit,
                        software=software,
                    )
                    for _ in range(browser_reps)
                ]
                ok = [probe for probe in probes if probe.get("status") == "ok"]
                row["browser_probes"] = probes
                if ok:
                    row["browser_ready_ms"] = median([float(p["ready_ms"]) for p in ok])
                    row["browser_peak_rss_bytes"] = max(
                        int(p["browser_peak_rss_bytes"]) for p in ok
                    )
                    row["end_to_end_ttfr_ms"] = row["python_render_ms"] + row["browser_ready_ms"]
                    row["browser_renderer"] = sorted({str(p.get("renderer")) for p in ok})
                    row["browser_nonblank_min"] = min(int(p["nonblank_pixels"]) for p in ok)
                else:
                    row["status"] = "browser_" + probes[-1]["status"]
                    row["browser_peak_rss_bytes"] = max(
                        int(p.get("browser_peak_rss_bytes", 0)) for p in probes
                    )
            elif row["status"] == "ok":
                row["end_to_end_ttfr_ms"] = row["python_render_ms"]
            results.append(row)
            print(
                json.dumps(
                    {
                        "library": library,
                        "n": n,
                        "status": row["status"],
                        "ttfr_ms": row.get("end_to_end_ttfr_ms"),
                        "python_peak_gib": row.get("python_peak_rss_bytes", 0) / 2**30,
                        "browser_peak_gib": row.get("browser_peak_rss_bytes", 0) / 2**30,
                        "mode": row.get("mode"),
                    }
                ),
                flush=True,
            )
    return {
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "method": {
            "description": "default public scatter behavior; no external sampling or aggregation",
            "sizes": sizes,
            "source": "seeded correlated Gaussian float32 x/y",
            "source_bytes_per_row": 8,
            "viewport_css_px": [WIDTH, HEIGHT],
            "timeout_s_per_phase": timeout_s,
            "memory_limit_gib_per_process_tree": memory_gib,
            "browser_repetitions": browser_reps,
            "browser_renderer_requested": "swiftshader-software" if software else "metal-default",
            "libraries": libraries,
            "data_generation_excluded_from_ttfr": True,
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "xy": importlib.metadata.version("xy"),
            "xy_commit": subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
            ).strip(),
            "plotly": importlib.metadata.version("plotly"),
            "matplotlib": importlib.metadata.version("matplotlib"),
            "pandas": importlib.metadata.version("pandas"),
            "cpu_count": os.cpu_count(),
            "chrome": subprocess.check_output([CHROME, "--version"], text=True).strip(),
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--library", choices=("xy", "plotly", "matplotlib"))
    parser.add_argument("--n", type=int)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--child-out", type=Path)
    parser.add_argument("--sizes", default=",".join(str(n) for n in DEFAULT_SIZES))
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--memory-gib", type=float, default=36)
    parser.add_argument("--browser-reps", type=int, default=1)
    parser.add_argument("--libraries", default="xy,plotly,matplotlib")
    parser.add_argument("--software", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "launch-scatter-results.json")
    args = parser.parse_args()
    if args.child:
        if args.library is None or args.n is None or args.child_out is None:
            parser.error("child mode requires --library, --n, and --child-out")
        result = child_run(args.library, args.n, args.artifact)
        args.child_out.write_text(json.dumps(result), encoding="utf-8")
        return
    sizes = [int(value) for value in args.sizes.split(",")]
    libraries = [value.strip() for value in args.libraries.split(",") if value.strip()]
    unknown = sorted(set(libraries) - {"xy", "plotly", "matplotlib"})
    if unknown:
        parser.error(f"unknown libraries: {', '.join(unknown)}")
    result = run_sweep(
        sizes,
        timeout_s=args.timeout,
        memory_gib=args.memory_gib,
        browser_reps=args.browser_reps,
        libraries=libraries,
        software=args.software,
    )
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
