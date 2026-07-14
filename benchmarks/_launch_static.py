#!/usr/bin/env python3
"""Guarded same-resolution static PNG scatter benchmark."""

from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psutil

WIDTH = 900
HEIGHT = 420
DPI = 100
SEED = 20260713
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SIZES = [10_000, 100_000, 1_000_000, 10_000_000, 1_000_000_000]


def make_data(n: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(SEED)
    x = rng.standard_normal(n, dtype=np.float32)
    y = rng.standard_normal(n, dtype=np.float32)
    y *= np.float32(1.2)
    y += x
    y *= np.float32(0.5)
    return x, y


def nonblank_png(png: bytes) -> int:
    from PIL import Image

    image = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))
    if image.shape[:2] != (HEIGHT, WIDTH):
        raise AssertionError(f"unexpected PNG dimensions {image.shape[:2]}")
    count = int(np.count_nonzero(np.any(image != image[0, 0], axis=2)))
    if count == 0:
        raise AssertionError("blank PNG")
    return count


def child_run(library: str, n: int) -> dict[str, Any]:
    # Imports are excluded from chart-to-PNG time but included in RSS.
    if library == "xy":
        from xy import scatter, scatter_chart
    elif library == "plotly":
        import plotly.express as px
    elif library == "matplotlib":
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    else:
        raise ValueError(library)

    x, y = make_data(n)
    source_rss = psutil.Process().memory_info().rss
    t0 = time.perf_counter()
    if library == "xy":
        fig = scatter_chart(scatter(x=x, y=y), width=WIDTH, height=HEIGHT).figure()
        png = fig.to_png(width=WIDTH, height=HEIGHT, scale=1, engine="native")
        mode = "density" if fig.traces[0].use_density() else "direct"
    elif library == "plotly":
        # render_mode remains px.scatter's default "auto".
        fig = px.scatter(x=x, y=y, width=WIDTH, height=HEIGHT)
        mode = str(fig.data[0].type)
        png = fig.to_image(format="png", width=WIDTH, height=HEIGHT, scale=1)
    else:
        fig, ax = plt.subplots(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
        collection = ax.scatter(x, y)
        if len(collection.get_offsets()) != n:
            raise AssertionError("Matplotlib PathCollection row-count oracle failed")
        output = io.BytesIO()
        fig.savefig(output, format="png", dpi=DPI)
        plt.close(fig)
        png = output.getvalue()
        mode = "static-agg"
    elapsed_ms = (time.perf_counter() - t0) * 1e3
    nonblank = nonblank_png(png)
    return {
        "status": "ok",
        "library": library,
        "n": n,
        "mode": mode,
        "source_bytes": int(x.nbytes + y.nbytes),
        "source_rss_bytes": source_rss,
        "render_ms": elapsed_ms,
        "png_bytes": len(png),
        "nonblank_pixels": nonblank,
        "width": WIDTH,
        "height": HEIGHT,
    }


def tree_rss(process: psutil.Process) -> int:
    total = 0
    try:
        processes = [process, *process.children(recursive=True)]
    except psutil.NoSuchProcess:
        return 0
    for proc in processes:
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


def run_isolated(
    library: str,
    n: int,
    *,
    timeout_s: float,
    memory_limit_bytes: int,
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
                "peak_rss_bytes": peak,
                "wall_ms": (time.monotonic() - start) * 1e3,
                "stderr_tail": stderr[-1000:],
            }
        if popen.returncode != 0 or not result_path.exists():
            return {
                "status": f"failed(exit={popen.returncode})",
                "library": library,
                "n": n,
                "peak_rss_bytes": peak,
                "wall_ms": (time.monotonic() - start) * 1e3,
                "stdout_tail": stdout[-1000:],
                "stderr_tail": stderr[-2000:],
            }
        result = json.loads(result_path.read_text())
        result["peak_rss_bytes"] = peak
        result["wall_ms"] = (time.monotonic() - start) * 1e3
        return result


def run(sizes: list[int], *, timeout_s: float, memory_gib: float) -> dict[str, Any]:
    limit = int(memory_gib * 2**30)
    results = []
    for n in sizes:
        for library in ("xy", "plotly", "matplotlib"):
            row = run_isolated(library, n, timeout_s=timeout_s, memory_limit_bytes=limit)
            results.append(row)
            print(
                json.dumps(
                    {
                        "library": library,
                        "n": n,
                        "status": row["status"],
                        "render_ms": row.get("render_ms"),
                        "peak_gib": row.get("peak_rss_bytes", 0) / 2**30,
                        "mode": row.get("mode"),
                    }
                ),
                flush=True,
            )
    return {
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "method": {
            "target": "validated 900x420 PNG",
            "sizes": sizes,
            "timeout_s_per_case": timeout_s,
            "memory_limit_gib_per_process_tree": memory_gib,
            "source": "same seeded correlated Gaussian float32 x/y",
            "source_bytes_per_row": 8,
            "data_generation_and_imports_excluded_from_render_time": True,
            "xy_path": "native PNG",
            "plotly_path": "Kaleido/Chrome PNG",
            "matplotlib_path": "Agg PNG",
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "xy": importlib.metadata.version("xy"),
            "plotly": importlib.metadata.version("plotly"),
            "kaleido": importlib.metadata.version("kaleido"),
            "matplotlib": importlib.metadata.version("matplotlib"),
            "chrome": subprocess.check_output(
                [CHROME, "--version"],
                text=True,
            ).strip(),
            "cpu_count": os.cpu_count(),
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--library", choices=("xy", "plotly", "matplotlib"))
    parser.add_argument("--n", type=int)
    parser.add_argument("--child-out", type=Path)
    parser.add_argument("--sizes", default=",".join(str(n) for n in DEFAULT_SIZES))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--memory-gib", type=float, default=36)
    parser.add_argument("--out", type=Path, default=ROOT / "launch-static-scatter-results.json")
    args = parser.parse_args()
    if args.child:
        if args.library is None or args.n is None or args.child_out is None:
            parser.error("child mode requires --library, --n, and --child-out")
        result = child_run(args.library, args.n)
        args.child_out.write_text(json.dumps(result), encoding="utf-8")
        return
    sizes = [int(value) for value in args.sizes.split(",")]
    result = run(sizes, timeout_s=args.timeout, memory_gib=args.memory_gib)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
