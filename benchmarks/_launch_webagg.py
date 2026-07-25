#!/usr/bin/env python3
"""Guarded first-render benchmark for Matplotlib's built-in WebAgg backend."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import socket
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
DEFAULT_SIZES = [10_000, 100_000, 1_000_000, 10_000_000, 100_000_000, 1_000_000_000]


def make_data(n: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(SEED)
    x = rng.standard_normal(n, dtype=np.float32)
    y = rng.standard_normal(n, dtype=np.float32)
    y *= np.float32(1.2)
    y += x
    y *= np.float32(0.5)
    return x, y


def server_child(n: int, port: int, ready_path: Path) -> None:
    import matplotlib

    matplotlib.use("WebAgg")
    matplotlib.rcParams["webagg.address"] = "127.0.0.1"
    matplotlib.rcParams["webagg.port"] = port
    matplotlib.rcParams["webagg.port_retries"] = 1
    matplotlib.rcParams["webagg.open_in_browser"] = False
    import matplotlib.pyplot as plt

    process = psutil.Process()
    x, y = make_data(n)
    source_rss = process.memory_info().rss
    t0 = time.perf_counter()
    fig, ax = plt.subplots(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
    collection = ax.scatter(x, y)
    build_ms = (time.perf_counter() - t0) * 1e3
    if len(collection.get_offsets()) != n:
        raise AssertionError("WebAgg PathCollection row-count oracle failed")
    ready_path.write_text(
        json.dumps(
            {
                "n": n,
                "source_bytes": int(x.nbytes + y.nbytes),
                "source_rss_bytes": source_rss,
                "build_ms": build_ms,
                "mode": "interactive-webagg",
                "offset_count": int(len(collection.get_offsets())),
            }
        ),
        encoding="utf-8",
    )
    plt.show()


def tree_rss(process: psutil.Process) -> int:
    total = 0
    for proc in [process, *process.children(recursive=True)]:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            total += proc.memory_info().rss
    return total


def terminate_tree(process: psutil.Process) -> None:
    try:
        children = process.children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    for child in reversed(children):
        with contextlib.suppress(psutil.NoSuchProcess):
            child.kill()
    with contextlib.suppress(psutil.NoSuchProcess):
        process.kill()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_http(port: int, process: subprocess.Popen[str], deadline: float) -> None:
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("WebAgg server exited before accepting requests")
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.05)
    raise TimeoutError("WebAgg HTTP startup timeout")


def wait_devtools(profile: Path, process: subprocess.Popen[str], deadline: float) -> int:
    active = profile / "DevToolsActivePort"
    while time.monotonic() < deadline:
        if active.exists():
            lines = active.read_text().splitlines()
            if lines:
                return int(lines[0])
        if process.poll() is not None:
            raise RuntimeError("Chrome exited before DevTools startup")
        time.sleep(0.02)
    raise TimeoutError("Chrome DevTools startup timeout")


CANVAS_PROBE = r"""
(()=>{
  const candidates=[...document.querySelectorAll('canvas')]
    .filter(c=>c.width>=400&&c.height>=200)
    .sort((a,b)=>b.width*b.height-a.width*a.height);
  if(!candidates.length) return null;
  const c=candidates[0], ctx=c.getContext('2d');
  if(!ctx) return null;
  const d=ctx.getImageData(0,0,c.width,c.height).data;
  const r0=d[0], g0=d[1], b0=d[2], a0=d[3];
  const stride=Math.max(4,Math.floor((c.width*c.height)/4096)*4);
  let different=0;
  for(let i=0;i<d.length;i+=stride) {
    if(Math.abs(d[i]-r0)+Math.abs(d[i+1]-g0)+Math.abs(d[i+2]-b0)+Math.abs(d[i+3]-a0)>24)
      different++;
  }
  if(different<20) return null;
  return {ready_ms:performance.now(),nonblank_samples:different,
          canvas_width:c.width,canvas_height:c.height,
          js_heap_bytes:performance.memory?performance.memory.usedJSHeapSize:null};
})()
"""


def benchmark_one(
    n: int, *, timeout_s: float, memory_limit_bytes: int, software: bool = False
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        ready_path = td_path / "ready.json"
        port = free_port()
        server_cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--server-child",
            "--n",
            str(n),
            "--port",
            str(port),
            "--ready-path",
            str(ready_path),
        ]
        server = subprocess.Popen(
            server_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        server_proc = psutil.Process(server.pid)
        start = time.monotonic()
        deadline = start + timeout_s
        python_peak = 0
        chrome = None
        chrome_proc = None
        ws = None
        browser_peak = 0
        try:
            while not ready_path.exists():
                rss = tree_rss(server_proc)
                python_peak = max(python_peak, rss)
                if rss > memory_limit_bytes:
                    return {
                        "status": "memory_limit",
                        "n": n,
                        "python_peak_rss_bytes": python_peak,
                        "phase": "figure-build",
                    }
                if server.poll() is not None:
                    stdout, stderr = server.communicate()
                    return {
                        "status": f"failed(exit={server.returncode})",
                        "n": n,
                        "python_peak_rss_bytes": python_peak,
                        "stdout_tail": stdout[-1000:],
                        "stderr_tail": stderr[-2000:],
                    }
                if time.monotonic() > deadline:
                    return {
                        "status": "timeout",
                        "n": n,
                        "python_peak_rss_bytes": python_peak,
                        "phase": "figure-build",
                    }
                time.sleep(0.05)

            metadata = json.loads(ready_path.read_text())
            wait_http(port, server, deadline)
            profile = td_path / "chrome-profile"
            chrome_cmd = [
                CHROME,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
                "--enable-precise-memory-info",
                "--remote-debugging-port=0",
                "--remote-allow-origins=*",
                "--force-device-scale-factor=1",
                "--window-size=1100,650",
                f"--user-data-dir={profile}",
                f"http://127.0.0.1:{port}/",
            ]
            if software:
                chrome_cmd[1:1] = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
            browser_start = time.monotonic()
            chrome = subprocess.Popen(
                chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
            )
            chrome_proc = psutil.Process(chrome.pid)
            devtools_port = wait_devtools(profile, chrome, deadline)
            target = None
            while time.monotonic() < deadline:
                python_peak = max(python_peak, tree_rss(server_proc))
                browser_peak = max(browser_peak, tree_rss(chrome_proc))
                if python_peak > memory_limit_bytes or browser_peak > memory_limit_bytes:
                    return {
                        **metadata,
                        "status": "memory_limit",
                        "n": n,
                        "python_peak_rss_bytes": python_peak,
                        "browser_peak_rss_bytes": browser_peak,
                        "phase": "interactive-render",
                    }
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{devtools_port}/json/list", timeout=2
                ) as response:
                    targets = json.load(response)
                target = next((item for item in targets if item.get("type") == "page"), None)
                if target:
                    break
                time.sleep(0.02)
            if not target:
                raise TimeoutError("Chrome page target timeout")
            ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=3)
            call_id = 0
            while time.monotonic() < deadline:
                python_rss = tree_rss(server_proc)
                browser_rss = tree_rss(chrome_proc)
                python_peak = max(python_peak, python_rss)
                browser_peak = max(browser_peak, browser_rss)
                if python_rss > memory_limit_bytes or browser_rss > memory_limit_bytes:
                    return {
                        **metadata,
                        "status": "memory_limit",
                        "python_peak_rss_bytes": python_peak,
                        "browser_peak_rss_bytes": browser_peak,
                        "phase": "interactive-render",
                    }
                call_id += 1
                ws.send(
                    json.dumps(
                        {
                            "id": call_id,
                            "method": "Runtime.evaluate",
                            "params": {"expression": CANVAS_PROBE, "returnByValue": True},
                        }
                    )
                )
                while True:
                    message = json.loads(ws.recv())
                    if message.get("id") == call_id:
                        break
                value = message.get("result", {}).get("result", {}).get("value")
                if value:
                    browser_ready_ms = float(value["ready_ms"])
                    return {
                        **metadata,
                        **value,
                        "status": "ok",
                        "library": "matplotlib-webagg",
                        "python_peak_rss_bytes": python_peak,
                        "browser_peak_rss_bytes": browser_peak,
                        "browser_wall_ms": (time.monotonic() - browser_start) * 1e3,
                        "end_to_end_ttfr_ms": float(metadata["build_ms"]) + browser_ready_ms,
                    }
                time.sleep(0.02)
            return {
                **metadata,
                "status": "timeout",
                "python_peak_rss_bytes": python_peak,
                "browser_peak_rss_bytes": browser_peak,
                "phase": "interactive-render",
            }
        finally:
            if ws is not None:
                ws.close()
            if chrome_proc is not None:
                terminate_tree(chrome_proc)
            if chrome is not None:
                try:
                    chrome.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    chrome.kill()
            terminate_tree(server_proc)
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()


def run(sizes: list[int], *, timeout_s: float, memory_gib: float) -> dict[str, Any]:
    limit = int(memory_gib * 2**30)
    results = []
    for n in sizes:
        row = benchmark_one(n, timeout_s=timeout_s, memory_limit_bytes=limit)
        results.append(row)
        print(
            json.dumps(
                {
                    "n": n,
                    "status": row["status"],
                    "ttfr_ms": row.get("end_to_end_ttfr_ms"),
                    "python_peak_gib": row.get("python_peak_rss_bytes", 0) / 2**30,
                    "browser_peak_gib": row.get("browser_peak_rss_bytes", 0) / 2**30,
                    "offset_count": row.get("offset_count"),
                }
            ),
            flush=True,
        )
    return {
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "method": {
            "backend": "Matplotlib WebAgg",
            "sizes": sizes,
            "timeout_s_total_per_case": timeout_s,
            "memory_limit_gib_per_process_tree": memory_gib,
            "source": "same seeded correlated Gaussian float32 x/y",
            "source_bytes_per_row": 8,
            "data_generation_and_imports_excluded_from_ttfr": True,
            "ttfr": "figure build + browser navigation + Python Agg draw + WebSocket delivery + nonblank canvas",
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "matplotlib": subprocess.check_output(
                [sys.executable, "-c", "import matplotlib; print(matplotlib.__version__)"],
                text=True,
            ).strip(),
            "tornado": subprocess.check_output(
                [sys.executable, "-c", "import tornado; print(tornado.version)"], text=True
            ).strip(),
            "chrome": subprocess.check_output([CHROME, "--version"], text=True).strip(),
            "cpu_count": os.cpu_count(),
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-child", action="store_true")
    parser.add_argument("--n", type=int)
    parser.add_argument("--port", type=int)
    parser.add_argument("--ready-path", type=Path)
    parser.add_argument("--sizes", default=",".join(str(n) for n in DEFAULT_SIZES))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--memory-gib", type=float, default=36)
    parser.add_argument("--out", type=Path, default=ROOT / "matplotlib-webagg-results.json")
    args = parser.parse_args()
    if args.server_child:
        if args.n is None or args.port is None or args.ready_path is None:
            parser.error("server child requires --n, --port, and --ready-path")
        server_child(args.n, args.port, args.ready_path)
        return
    sizes = [int(value) for value in args.sizes.split(",")]
    result = run(sizes, timeout_s=args.timeout, memory_gib=args.memory_gib)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
