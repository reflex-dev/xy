"""xy scatter benchmark — stdlib only, no numpy, no PyPI.

Produces the xy arm of the vs-Plotly/matplotlib comparison with real
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

The point of comparison is the crossover: xy' payload and render cost
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
import statistics
import string
import subprocess
import sys
import tempfile
import time
from array import array
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "python" / "xy" / "static"
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))

from _protocol import PROTOCOL_VERSION  # noqa: E402
from abi_smoke import load  # noqa: E402
from categories import BENCHMARK_CATEGORIES, categories_for  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402

# Mirror the Python defaults (xy._figure).
DENSITY_THRESHOLD = 200_000
GRID_W, GRID_H = 512, 384
RENDER_W, RENDER_H = 900, 420
SCATTER_NATIVE_CATEGORY_IDS = (
    "medium_direct_scatter",
    "huge_scatter_overview",
    "payload_export_size",
)
_PRODUCTION_WARMED = False


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


def gen_numpy_large(n: int) -> tuple[Any, Any]:
    """Fast opt-in fixture for 100M–1B production stress runs.

    The default harness stays stdlib-only. This mode deliberately requires
    NumPy because spending minutes in a Python scalar fixture would obscure
    the production payload measurement; fixture generation remains outside
    the timed region either way.
    """
    import numpy as np

    rng = np.random.default_rng(2026)
    x = np.empty(n, dtype=np.float64)
    y = np.empty(n, dtype=np.float64)
    rng.standard_normal(out=x)
    rng.standard_normal(out=y)
    y *= 0.55
    y += 0.65 * x
    return x, y


def gen_numpy_categories(n: int, groups: int) -> Any:
    """Compact one-codepoint Unicode labels for categorical ceiling probes."""
    import numpy as np

    alphabet = string.ascii_letters + string.digits
    if groups < 2 or groups > len(alphabet):
        raise ValueError(f"categorical groups must be between 2 and {len(alphabet)}")
    codes = np.arange(n, dtype=np.uint8)
    codes %= groups
    return np.asarray(list(alphabet[:groups]))[codes]


def _warm_production_path(xy: Any, np: Any) -> None:
    """Exclude lazy module import/bytecode work from large-row timing."""
    global _PRODUCTION_WARMED
    if _PRODUCTION_WARMED:
        return
    tiny = np.array([0.0, 1.0, 2.0, 3.0])
    fig = xy.scatter_chart(xy.scatter(x=tiny, y=tiny), width=64, height=48).figure()
    fig.build_payload()
    _PRODUCTION_WARMED = True


def bench_prep(lib, n: int, x: array, y: array) -> dict:
    D, F = ctypes.c_double, ctypes.c_float
    density = n > DENSITY_THRESHOLD
    category_ids = (
        ("huge_scatter_overview", "payload_export_size")
        if density
        else ("medium_direct_scatter", "payload_export_size")
    )
    # Reusing the already-generated source columns makes repeats cheap and
    # exposes scheduler noise on the highly parallel 10M–100M path. Keep the
    # high-memory >100M ceiling probes single-shot so their residency contract
    # remains straightforward.
    reps = 3 if n <= 100_000_000 else 1
    best = float("inf")
    if density:
        grid = array("f", bytes(4 * GRID_W * GRID_H))
        for _ in range(reps):
            t0 = time.perf_counter()
            lib.xy_bin_2d(
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
            lib.xy_encode_f32(_ptr(x, D), n, 0.0, 1.0, _ptr(ex, F))
            lib.xy_encode_f32(_ptr(y, D), n, 0.0, 1.0, _ptr(ey, F))
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


def bench_production(
    n: int,
    x: Any,
    y: Any,
    *,
    color: Any | None = None,
    native_png: bool = False,
) -> dict:
    """Time the real Figure -> spec/blob path and assert its reduction contract."""
    import numpy as np

    import xy

    _warm_production_path(xy, np)

    # Source generation is outside this region, so repeat through 100M to
    # suppress parallel-scheduler noise without multiplying ceiling-run RAM.
    reps = 3 if n <= 100_000_000 else 1
    best = float("inf")
    result = None
    for _ in range(reps):
        t0 = time.perf_counter()
        fig = xy.scatter_chart(
            xy.scatter(x=x, y=y, color=color),
            width=RENDER_W,
            height=RENDER_H,
        ).figure()
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
        if density.get("enc") == "log-u8":
            grid = np.frombuffer(
                blob,
                dtype=np.uint8,
                count=column["len"],
                offset=column["byte_offset"],
            )
            if int(trace["visible"]) > 0 and (not np.any(grid) or int(grid.max()) != 255):
                raise AssertionError("quantized density grid lost occupancy or maximum")
        else:
            grid = np.frombuffer(
                blob,
                dtype=np.float32,
                count=column["len"],
                offset=column["byte_offset"],
            )
            actual = int(round(float(grid.sum())))
            if actual != int(trace["visible"]):
                raise AssertionError(f"density count oracle failed: {actual} != {trace['visible']}")
        # The production benchmark data is finite and the initial autorange
        # contains it all, so exact conservation remains independently known
        # even though the display texture is intentionally quantized.
        if int(trace["visible"]) != n:
            raise AssertionError(f"density visible-count oracle failed: {trace['visible']} != {n}")
        sample = density.get("sample") or {}
        sample_points = int(sample.get("n", 0))
        if color is not None and (sample.get("color") or {}).get("mode") != "categorical":
            raise AssertionError("categorical density sample lost its color channel")
    elif trace.get("n_marks") != n:
        raise AssertionError(f"direct row-count oracle failed: {trace.get('n_marks')} != {n}")

    spec_bytes = len(json.dumps(spec, separators=(",", ":"), default=str).encode("utf-8"))
    wire = spec_bytes + len(blob)
    category_ids = (
        ("huge_scatter_overview", "payload_export_size")
        if tier == "density"
        else ("medium_direct_scatter", "payload_export_size")
    )
    row = {
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
        "categorical_groups": 0 if color is None else len(np.unique(color[: min(n, 4096)])),
    }
    if native_png:
        from xy import _raster

        samples = []
        png = b""
        for _ in range(11):
            t0 = time.perf_counter()
            rendered = _raster.render_raster(spec, blob, 1.0, fast_png=True)
            samples.append((time.perf_counter() - t0) * 1e3)
            png = rendered if isinstance(rendered, bytes) else b""
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise AssertionError("native density render did not produce a PNG")
        row["native_png_ms"] = statistics.median(samples)
        row["source_to_native_png_ms"] = row["data_prep_ms"] + row["native_png_ms"]
        row["native_png_bytes"] = len(png)
    return row


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
        "protocol": PROTOCOL_VERSION,
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
  const v=xy.renderStandalone(document.getElementById("chart"),spec,bytes.buffer);
  v._drawNow();
  const gl=v.gl; const px=new Uint8Array(4); gl.readPixels(0,0,1,1,gl.RGBA,gl.UNSIGNED_BYTE,px);
  const t1=performance.now();
  document.title=`XY_OK render_ms=${{(t1-t0).toFixed(2)}}`;
}}catch(e){{document.title="XY_ERROR "+e.message}}
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
        help="time the installed xy Figure payload path instead of the C-ABI kernel shape",
    )
    ap.add_argument(
        "--large-numpy-generator",
        action="store_true",
        help="use a fast NumPy fixture for opt-in 100M-1B production stress runs",
    )
    ap.add_argument(
        "--categorical-groups",
        type=int,
        default=0,
        help="add compact Unicode categories to a production ceiling run (2-62 groups)",
    )
    ap.add_argument(
        "--native-png",
        action="store_true",
        help="also time payload-to-PNG rendering through the native rasterizer",
    )
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    if args.production and args.render:
        ap.error("--production and --render are separate scopes; run them as separate reports")
    if args.large_numpy_generator and not args.production:
        ap.error("--large-numpy-generator requires --production")
    if args.categorical_groups and not args.production:
        ap.error("--categorical-groups requires --production")
    if args.categorical_groups and not 2 <= args.categorical_groups <= 62:
        ap.error("--categorical-groups must be between 2 and 62")
    if args.native_png and not args.production:
        ap.error("--native-png requires --production")
    sizes = [int(float(s)) for s in args.sizes.split(",")]
    lib = load()

    rows = []
    scope = "production Figure payload" if args.production else "native kernel shape"
    if args.categorical_groups:
        scope += f" with {args.categorical_groups} categories"
    print(f"xy scatter — {scope}, SwiftShader render. threshold={DENSITY_THRESHOLD:,}")
    hdr = "| N | tier | data prep | wire bytes | B/pt"
    sep = "|---|---|---|---|---"
    if args.render:
        hdr += " | render (chromium)"
        sep += "|---"
    if args.native_png:
        hdr += " | native PNG"
        sep += "|---"
    print(hdr + " |")
    print(sep + " |")
    for n in sizes:
        x, y = gen_numpy_large(n) if args.large_numpy_generator else gen(n)
        color = (
            gen_numpy_categories(n, args.categorical_groups) if args.categorical_groups else None
        )
        r = (
            bench_production(n, x, y, color=color, native_png=args.native_png)
            if args.production
            else bench_prep(lib, n, x, y)
        )
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
        if args.native_png:
            line += f" | {r['native_png_ms']:.1f} ms"
        print(line + " |")
        del x, y, color
    if args.json:
        chromium = find_chromium() if args.render else None
        report = {
            "schema_version": SCHEMA_VERSION,
            "measurement_scope": (
                "production-figure-payload" if args.production else "native-kernel-shape"
            ),
            "data_generator": "numpy-large" if args.large_numpy_generator else "stdlib-array",
            "categorical_groups": args.categorical_groups,
            "environment": collect_environment_metadata(
                chromium=chromium or None,
                xy_backend="native",
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
