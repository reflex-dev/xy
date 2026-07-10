"""fastcharts scatter benchmark — stdlib only, no numpy, no PyPI.

Produces the fastcharts arm of the vs-Plotly/matplotlib comparison with real
executed numbers even in a locked-down environment, measuring exactly what the
cross-library harness (benchmarks/bench_vs.py) measures for the other libraries:

  data_prep_ms  — kernel-side "prepare to render": encode x,y to relative f32
                  (direct tier) or bin to a density grid (Tier 2, above the
                  threshold), via the native C ABI
  wire_bytes    — bytes crossing to the GPU/browser. Direct = 8·N; density =
                  w·h·4, CONSTANT — the screen-bounded payload that stays flat
                  while Plotly/matplotlib grow ∝ N
  render_ms     — (optional, --render) real render-to-pixels in headless
                  Chromium: ChartView construct + draw + readback, timed with
                  performance.now() inside the page

The point of comparison is the crossover: fastcharts' payload and render cost
go flat under density aggregation where CPU raster/vector libraries scale with N.

Usage:
  python benchmarks/bench_scatter_native.py [--sizes 1e4,1e5,1e6,1e7] [--render]
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "python" / "fastcharts" / "static"
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))

from abi_smoke import load  # noqa: E402
from categories import BENCHMARK_CATEGORIES, categories_for  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402

# Mirror the Python defaults (fastcharts._figure).
DENSITY_THRESHOLD = 200_000
GRID_W, GRID_H = 512, 384
RENDER_W, RENDER_H = 900, 420
SCATTER_NATIVE_CATEGORY_IDS = (
    "medium_direct_scatter",
    "huge_scatter_overview",
    "payload_export_size",
)


def _ptr(a: array, ct):
    return ctypes.cast(a.buffer_info()[0], ctypes.POINTER(ct))


def gen(n: int) -> tuple[array, array]:
    # A correlated cloud, deterministic (no numpy / no Math.random in scripts).
    x = array("d", bytes(8 * n))
    y = array("d", bytes(8 * n))
    # Cheap LCG for spread; deterministic across runs.
    s = 2463534242
    for i in range(n):
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        u = (s & 0xFFFFFF) / 0xFFFFFF - 0.5
        xi = math.sin(i * 1e-4) + u
        x[i] = xi
        y[i] = 0.5 * xi + ((i * 2654435761 & 0xFFFF) / 0xFFFF - 0.5)
    return x, y


def bench_prep(lib, n: int, x: array, y: array) -> dict:
    D, F = ctypes.c_double, ctypes.c_float
    density = n > DENSITY_THRESHOLD
    category_ids = (
        ("huge_scatter_overview", "payload_export_size")
        if density
        else ("medium_direct_scatter", "payload_export_size")
    )
    reps = 3 if n <= 2_000_000 else 1
    best = float("inf")
    if density:
        grid = array("f", bytes(4 * GRID_W * GRID_H))
        for _ in range(reps):
            t0 = time.perf_counter()
            lib.fc_bin_2d(
                _ptr(x, D), _ptr(y, D), n, -2.0, 2.0, -2.0, 2.0, GRID_W, GRID_H, _ptr(grid, F)
            )
            best = min(best, time.perf_counter() - t0)
        wire = GRID_W * GRID_H * 4
        tier = "density"
    else:
        ex = array("f", bytes(4 * n))
        ey = array("f", bytes(4 * n))
        for _ in range(reps):
            t0 = time.perf_counter()
            lib.fc_encode_f32(_ptr(x, D), n, 0.0, 1.0, _ptr(ex, F))
            lib.fc_encode_f32(_ptr(y, D), n, 0.0, 1.0, _ptr(ey, F))
            best = min(best, time.perf_counter() - t0)
        wire = 8 * n
        tier = "direct"
    return {
        "n": n,
        "tier": tier,
        "benchmark_categories": [category["id"] for category in categories_for(category_ids)],
        "data_prep_ms": best * 1e3,
        "wire_bytes": wire,
        "wire_bytes_per_point": wire / n,
        "pts_per_s": n / best if best else None,
    }


def bench_production(n: int, x: array, y: array) -> dict:
    """Time the real Figure -> spec/blob path and assert its reduction contract."""
    import numpy as np

    import fastcharts as fc

    reps = 3 if n <= 2_000_000 else 1
    best = float("inf")
    result = None
    for _ in range(reps):
        t0 = time.perf_counter()
        fig = fc.scatter_chart(fc.scatter(x=x, y=y), width=RENDER_W, height=RENDER_H).figure()
        spec, blob = fig.build_payload()
        best = min(best, time.perf_counter() - t0)
        result = (spec, blob)
    assert result is not None
    spec, blob = result
    trace = spec["traces"][0]
    tier = trace["tier"]
    sample_points = 0
    if tier == "density":
        density = trace["density"]
        column = spec["columns"][density["buf"]]
        grid = np.frombuffer(
            blob,
            dtype=np.float32,
            count=column["len"],
            offset=column["byte_offset"],
        )
        actual = int(round(float(grid.sum())))
        expected = int(trace["visible"])
        if actual != expected:
            raise AssertionError(f"density count oracle failed: {actual} != {expected}")
        sample = density.get("sample") or {}
        sample_points = int(sample.get("n", 0))
    elif trace.get("n_marks") != n:
        raise AssertionError(f"direct row-count oracle failed: {trace.get('n_marks')} != {n}")

    spec_bytes = len(json.dumps(spec, separators=(",", ":"), default=str).encode("utf-8"))
    wire = spec_bytes + len(blob)
    category_ids = (
        ("huge_scatter_overview", "payload_export_size")
        if tier == "density"
        else ("medium_direct_scatter", "payload_export_size")
    )
    return {
        "n": n,
        "tier": tier,
        "benchmark_categories": [category["id"] for category in categories_for(category_ids)],
        "data_prep_ms": best * 1e3,
        "wire_bytes": wire,
        "wire_bytes_per_point": wire / n,
        "blob_bytes": len(blob),
        "spec_bytes": spec_bytes,
        "sample_points": sample_points,
        "pts_per_s": n / best if best else None,
        "oracle_status": "pass",
        "measurement_scope": "production-figure-payload",
    }


def find_chromium() -> str:
    for c in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/opt/pw-browsers/chromium",
        "chromium",
        "chromium-browser",
        "google-chrome",
    ):
        if Path(c).is_file() or shutil.which(c):
            return c
    return ""


def bench_render(n: int, x: array, y: array) -> dict:
    """Real render-to-pixels time in headless Chromium (page-timed)."""
    chromium = find_chromium()
    if not chromium:
        return {"render_ms": None, "note": "no chromium"}
    standalone = (STATIC / "standalone.js").read_text(encoding="utf-8")

    # Build a payload in the wire shape. Direct: encode; density: bin here in
    # Python (small grid) to mirror the kernel output.
    cols, blob = [], bytearray()

    def ship_scalar(vals):
        cols.append({"byte_offset": len(blob), "len": len(vals)})
        blob.extend(array("f", vals).tobytes())
        return len(cols) - 1

    if n > DENSITY_THRESHOLD:
        grid = [0.0] * (GRID_W * GRID_H)
        sx = GRID_W / 4.0
        sy = GRID_H / 4.0
        for i in range(n):
            cx = int((x[i] + 2.0) * sx)
            cy = int((y[i] + 2.0) * sy)
            if 0 <= cx < GRID_W and 0 <= cy < GRID_H:
                grid[cy * GRID_W + cx] += 1.0
        gmax = max(grid)
        trace = {
            "id": 0,
            "kind": "scatter",
            "name": "pts",
            "tier": "density",
            "n_points": n,
            "style": {"opacity": 1.0},
            "density": {
                "buf": ship_scalar(grid),
                "w": GRID_W,
                "h": GRID_H,
                "max": gmax,
                "colormap": "viridis",
                "x_range": [-2.0, 2.0],
                "y_range": [-2.0, 2.0],
                "channels_dropped": False,
            },
        }
    else:
        ex = [float(v) for v in x]
        ey = [float(v) for v in y]
        trace = {
            "id": 0,
            "kind": "scatter",
            "name": "pts",
            "tier": "direct",
            "n_points": n,
            "style": {"opacity": 0.7},
            "x": ship_scalar(ex),
            "y": ship_scalar(ey),
        }
        # direct columns need offset/scale meta
        cols[trace["x"]].update({"offset": 0.0, "scale": 1.0, "kind": "float"})
        cols[trace["y"]].update({"offset": 0.0, "scale": 1.0, "kind": "float"})

    spec = {
        "protocol": 2,
        "width": RENDER_W,
        "height": RENDER_H,
        "title": None,
        "x_axis": {"kind": "linear", "label": "x", "range": [-2.0, 2.0]},
        "y_axis": {"kind": "linear", "label": "y", "range": [-2.0, 2.0]},
        "traces": [trace],
        "columns": cols,
        "backend": "none",
        "show_legend": True,
    }

    page = f"""<!doctype html><html><head><meta charset=utf-8><title>pending</title></head>
<body><div id=chart></div><script>{standalone}</script><script>
const spec={json.dumps(spec)};
const bytes=Uint8Array.from(atob("{base64.b64encode(bytes(blob)).decode()}"),c=>c.charCodeAt(0));
try{{
  const t0=performance.now();
  const v=fastcharts.renderStandalone(document.getElementById("chart"),spec,bytes.buffer);
  v._drawNow();
  const gl=v.gl; const px=new Uint8Array(4); gl.readPixels(0,0,1,1,gl.RGBA,gl.UNSIGNED_BYTE,px);
  const t1=performance.now();
  document.title=`FC_OK render_ms=${{(t1-t0).toFixed(2)}}`;
}}catch(e){{document.title="FC_ERROR "+e.message}}
</script></body></html>"""

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "r.html"
        p.write_text(page, encoding="utf-8")
        out = subprocess.run(
            [
                chromium,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--virtual-time-budget=8000",
                "--dump-dom",
                p.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    m = re.search(r"render_ms=([\d.]+)", out.stdout)
    if not m:
        err = re.search(r"<title>([^<]*)</title>", out.stdout)
        return {"render_ms": None, "note": err.group(1) if err else "no title"}
    return {"render_ms": float(m.group(1))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1e4,1e5,1e6,1e7")
    ap.add_argument("--render", action="store_true", help="also time render-to-pixels in Chromium")
    ap.add_argument(
        "--production",
        action="store_true",
        help="time the installed fastcharts Figure payload path instead of the C-ABI kernel shape",
    )
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    if args.production and args.render:
        ap.error("--production and --render are separate scopes; run them as separate reports")
    sizes = [int(float(s)) for s in args.sizes.split(",")]
    lib = load()

    rows = []
    scope = "production Figure payload" if args.production else "native kernel shape"
    print(f"fastcharts scatter — {scope}, SwiftShader render. threshold={DENSITY_THRESHOLD:,}")
    hdr = "| N | tier | data prep | wire bytes | B/pt"
    sep = "|---|---|---|---|---"
    if args.render:
        hdr += " | render (chromium)"
        sep += "|---"
    print(hdr + " |")
    print(sep + " |")
    for n in sizes:
        x, y = gen(n)
        r = bench_production(n, x, y) if args.production else bench_prep(lib, n, x, y)
        if args.render:
            r.update(bench_render(n, x, y))
        rows.append(r)
        line = (
            f"| {r['n']:,} | {r['tier']} | {r['data_prep_ms']:.1f} ms "
            f"| {_fmt(r['wire_bytes'])} | {r['wire_bytes_per_point']:.3f}"
        )
        if args.render:
            rm = r.get("render_ms")
            line += f" | {rm:.1f} ms" if rm else f" | {r.get('note', '—')}"
        print(line + " |")
        del x, y
    if args.json:
        chromium = find_chromium() if args.render else None
        report = {
            "schema_version": SCHEMA_VERSION,
            "measurement_scope": (
                "production-figure-payload" if args.production else "native-kernel-shape"
            ),
            "environment": collect_environment_metadata(
                chromium=chromium or None,
                fastcharts_backend="native",
            ),
            "benchmark_categories": list(BENCHMARK_CATEGORIES),
            "tracked_categories": categories_for(SCATTER_NATIVE_CATEGORY_IDS),
            "rows": rows,
        }
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")


def _fmt(b: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


if __name__ == "__main__":
    main()
