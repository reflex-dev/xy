"""Apples-to-apples static-PNG raster: xy native Rust rasterizer vs Matplotlib Agg.

The WebGL export path pays a browser tax (HTML parse + upload) that Matplotlib
never does, so ``xy-webgl 15 s vs matplotlib 5.6 s`` at 100M compares different
pipelines. THIS benchmark removes the browser from both sides: xy's built-in
Rust rasterizer (``to_png(engine="native")``) against Matplotlib's Agg backend —
both go numpy array → CPU rasterize → PNG bytes, in one process, no browser.

Fairness controls:
- Data generation is shared and EXCLUDED from every timing.
- Identical canvas: 900x420 px (Matplotlib figsize 9x4.2 @ DPI 100; xy scale=1).
- Matched marker: ~1 px, opacity 0.15 (the raw-points-study marker).
- xy runs in DIRECT mode (``density=False``): all N points hit the rasterizer,
  no density/LOD substitution — validated by asserting the scatter trace stays
  direct with a column length of exactly N.
- Three raster arms measured: xy-native, mpl-scatter (PathCollection, what
  ``bench_vs.py`` uses), mpl-plot (``plot(',')`` pixel marker — Matplotlib's
  fastest raw path). Reporting all three avoids cherry-picking Matplotlib.
- Each (engine, size) runs in its own subprocess, so an OOM/segfault at one
  size is reported as a failure instead of killing the whole sweep.

Usage:
  uv run python benchmarks/bench_native_vs_agg.py --sizes 1e6,5e6,10e6,25e6,100e6
  uv run python benchmarks/bench_native_vs_agg.py --one xy-native 25000000
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

W, H, DPI, SEED = 900, 420, 100, 11
MARKER_PX = 1.0
OPACITY = 0.15
ENGINES = ("xy-native", "mpl-scatter", "mpl-plot")


def _painted_fraction(png: bytes) -> float:
    """Fraction of non-white pixels in a PNG (via Matplotlib's reader).

    A PNG byte-size proxy is unusable here: at high N with a translucent marker
    the whole canvas saturates to a near-solid color, which compresses TINY —
    the opposite of blank. Decoding and counting painted (non-white) pixels is
    correct in both the sparse and the saturated regime: a real scatter (sparse
    dots or a solid block) scores high; only a genuinely empty canvas scores ~0.
    Reused for both arms so validation is identical."""
    import matplotlib.image as mpimg
    import numpy as np

    arr = mpimg.imread(io.BytesIO(png))  # HxWx(3|4) float in [0,1]
    rgb = arr[..., :3]
    non_white = np.any(rgb < 0.99, axis=-1)
    if arr.shape[-1] == 4:  # transparent pixels are not "painted"
        non_white &= arr[..., 3] > 0.01
    return float(non_white.mean())


_MIN_PAINTED_FRAC = 0.01


def _gen(n: int):
    import numpy as np

    rng = np.random.default_rng(SEED)
    return rng.uniform(0.0, 1.0, n), rng.uniform(0.0, 1.0, n)


def run_xy_native(n: int) -> dict[str, object]:
    import warnings

    import xy
    from xy import _raster

    x, y = _gen(n)

    t0 = time.perf_counter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # density=False opt-out (§28)
        fig = xy.scatter_chart(
            xy.scatter(x=x, y=y, size=MARKER_PX, opacity=OPACITY, density=False),
            width=W,
            height=H,
        ).figure()
        spec, blob = fig.build_payload(px_width=W)
    build_ms = (time.perf_counter() - t0) * 1000

    # Raw-mode validation: the scatter trace must still be direct with N rows.
    scat = next(t for t in spec["traces"] if t["kind"] == "scatter")
    if scat.get("tier") == "density":
        return {"status": "failed(fell-to-density)"}
    rows = spec["columns"][scat["x"]]["len"]
    if rows != n:
        return {"status": f"failed(rows {rows} != {n})"}

    t0 = time.perf_counter()
    png = _raster.render_raster(spec, blob, 1.0)
    if not isinstance(png, bytes):
        from xy import _png

        png = _png.encode(png)
    raster_ms = (time.perf_counter() - t0) * 1000

    painted = _painted_fraction(png)
    return {
        "status": "ok" if painted >= _MIN_PAINTED_FRAC else "failed(blank)",
        "build_ms": round(build_ms, 1),
        "raster_ms": round(raster_ms, 1),
        "total_ms": round(build_ms + raster_ms, 1),
        "png_bytes": len(png),
        "painted_pct": round(painted * 100, 1),
        "rows": rows,
    }


def _run_mpl(n: int, mode: str) -> dict[str, object]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x, y = _gen(n)

    t0 = time.perf_counter()
    fig, ax = plt.subplots(figsize=(W / DPI, H / DPI), dpi=DPI)
    ax.set_axis_off()
    if mode == "scatter":
        ax.scatter(x, y, s=MARKER_PX, c="red", alpha=OPACITY, linewidths=0)
    else:  # plot with the pixel marker ','
        ax.plot(x, y, ",", color="red", alpha=OPACITY, linestyle="none")
    build_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    render_ms = (time.perf_counter() - t0) * 1000

    png = buf.getvalue()
    painted = _painted_fraction(png)
    return {
        "status": "ok" if painted >= _MIN_PAINTED_FRAC else "failed(blank)",
        "build_ms": round(build_ms, 1),
        "raster_ms": round(render_ms, 1),
        "total_ms": round(build_ms + render_ms, 1),
        "png_bytes": len(png),
        "painted_pct": round(painted * 100, 1),
        "rows": n,
    }


def run_one(engine: str, n: int) -> dict[str, object]:
    if engine == "xy-native":
        return run_xy_native(n)
    if engine == "mpl-scatter":
        return _run_mpl(n, "scatter")
    if engine == "mpl-plot":
        return _run_mpl(n, "plot")
    raise SystemExit(f"unknown engine {engine!r}")


def _cell(engine: str, n: int, timeout_s: float) -> dict[str, object]:
    """One (engine, size) in a fresh subprocess for memory/crash isolation."""
    try:
        out = subprocess.run(
            [sys.executable, __file__, "--one", engine, str(n)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"status": f"failed(timeout>{timeout_s:.0f}s)"}
    if out.returncode != 0:
        tail = (out.stderr or out.stdout).strip().splitlines()[-1:] or ["(no output)"]
        # A bare MemoryError / OOM-kill shows up as a nonzero exit here.
        return {"status": f"failed(exit {out.returncode}: {tail[0][:120]})"}
    for line in reversed(out.stdout.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    return {"status": "failed(no result line)"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--sizes", default="1e6,5e6,10e6,25e6,50e6,100e6")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--one", nargs=2, metavar=("ENGINE", "N"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.one:  # subprocess worker path
        print(json.dumps(run_one(args.one[0], int(args.one[1]))))
        return 0

    sizes = [int(float(s)) for s in args.sizes.split(",") if s.strip()]
    print(f"# canvas={W}x{H} marker~{MARKER_PX}px alpha={OPACITY} seed={SEED} (data gen excluded)")
    if not args.json:
        print(
            f"{'N':>12} {'engine':>12} {'ok':>3} {'build':>9} {'raster':>9} "
            f"{'total':>9} {'paint%':>7}  note"
        )
    for n in sizes:
        for engine in ENGINES:
            row = _cell(engine, n, args.timeout)
            if args.json:
                print(json.dumps({"n": n, "engine": engine, **row}))
                continue
            ok = row.get("status") == "ok"
            if "total_ms" in row:  # cell completed (may still fail validation)
                note = "" if ok else row.get("status", "")
                print(
                    f"{n:>12,} {engine:>12} {'y' if ok else 'N':>3} "
                    f"{row['build_ms']:>9.1f} {row['raster_ms']:>9.1f} "
                    f"{row['total_ms']:>9.1f} {row.get('painted_pct', 0):>7.1f}  {note}"
                )
            else:  # crash/OOM/timeout — no timings
                print(
                    f"{n:>12,} {engine:>12} {'N':>3} {'—':>9} {'—':>9} {'—':>9} {'—':>7}  {row.get('status')}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
