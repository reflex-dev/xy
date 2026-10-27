"""Real-Figure smoke coverage for the phase 6/7 polar feature set.

Six user-facing compositions travel through the normal Python payload
builder, the shipped standalone client in headless Chromium, and both native
static exporters:

* polar heatmap with contour isolines;
* a partial sector with a hole and angular/radial error bars;
* categorical theta with a logarithmic radius and polygonal grid;
* a symlog radius with a data-space origin below the visible range;
* bars, line, and scatter composed over one logarithmic annulus;
* a descending radial bar over a log-r data-space-origin annulus.

Pass ``--artifacts DIR`` to retain each live HTML page plus browser, SVG, and
PNG renders for visual inspection.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

import xy
from xy.export import _bundled_js, _javascript_for_inline_script

CHROMIUM_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
)


@dataclass(frozen=True)
class Case:
    name: str
    chart: xy.Chart
    marks: frozenset[str]
    min_live_pixels: int
    grid_shape: str
    sector: tuple[float, float] | None = None
    hole: float = 0.0
    origin: float | None = None
    log_radius: bool = False
    symlog_radius: bool = False
    inner_fraction: float | None = None
    labels: tuple[str, ...] = ()
    probe: tuple[float, float] = (0.0, 1.0)
    probe_kind: str = "line"
    gl_colors: tuple[tuple[str, int], ...] = ()
    chrome_colors: tuple[tuple[str, int], ...] = ()
    static_colors: tuple[tuple[str, int], ...] = ()


def _cases() -> list[Case]:
    theta = np.linspace(0.0, 360.0, 24, endpoint=False)
    radius = np.geomspace(1.0, 100.0, 8)
    theta_rad = np.deg2rad(theta)
    surface = np.array(
        [
            [math.sin(3.0 * angle) + math.cos(1.7 * math.log(r)) for angle in theta_rad]
            for r in radius
        ]
    )
    heatmap_contour = xy.polar_chart(
        xy.heatmap(surface, x=theta, y=radius, name="surface"),
        xy.contour(
            surface,
            x=theta,
            y=radius,
            levels=6,
            color="#ff00ff",
            width=2.0,
            name="isolines",
        ),
        xy.theta_axis(unit="degrees"),
        xy.r_axis(type_="log", domain=(1.0, 100.0)),
        width=520,
        height=520,
        title="Polar heatmap + contour",
    )

    error_theta = [-90.0, -45.0, 0.0, 45.0, 90.0]
    error_radius = [2.0, 3.0, 2.5, 4.0, 3.2]
    sector_hole_errors = xy.polar_chart(
        xy.errorbar(
            error_theta,
            error_radius,
            yerr=[0.3, 0.5, 0.4, 0.6, 0.3],
            xerr=[8.0, 6.0, 10.0, 7.0, 8.0],
            color="#dc2626",
            width=3.0,
            cap_size=10.0,
            name="uncertainty",
        ),
        xy.scatter(error_theta, error_radius, color="#111827", size=8.0),
        xy.theta_axis(
            unit="degrees",
            sector=(-110.0, 110.0),
            zero="N",
            direction="clockwise",
        ),
        xy.r_axis(domain=(0.0, 5.0), hole=0.35),
        width=640,
        height=420,
        title="Sector + hole + polar error bars",
    )

    categories = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    values = [1.0, 5.0, 25.0, 120.0, 600.0, 180.0, 40.0, 7.0]
    categorical_log_polygon = xy.polar_chart(
        xy.line(
            categories + [categories[0]],
            values + [values[0]],
            color="#2563eb",
            width=3.0,
            name="range",
        ),
        xy.scatter(categories, values, color="#f59e0b", size=9.0),
        xy.theta_axis(
            grid_shape="linear",
            zero="N",
            direction="clockwise",
            style={"grid_color": "#10b981"},
        ),
        xy.r_axis(
            type_="log",
            domain=(1.0, 1000.0),
            style={"grid_color": "#10b981"},
        ),
        width=520,
        height=520,
        title="Categorical theta + log r + polygon grid",
    )

    symlog_origin = xy.polar_chart(
        # The opposite outer points deliberately create a diameter chord. The
        # annular clip must retain only its two visible end segments instead of
        # painting through the data-space-origin hole.
        xy.line(
            [0.0, 180.0],
            [100.0, 100.0],
            color="#7c3aed",
            width=5.0,
            name="clipped diameter",
        ),
        xy.scatter([45.0], [0.0], color="#0f766e", size=12.0, name="symlog zero"),
        xy.theta_axis(unit="degrees"),
        xy.r_axis(
            type_="symlog",
            constant=1.0,
            domain=(-10.0, 100.0),
            origin=-100.0,
            tick_values=[-10.0, 0.0, 10.0, 100.0],
        ),
        width=520,
        height=520,
        title="Symlog r + data-space radial origin",
    )

    composed_wedges = xy.polar_chart(
        xy.bar(
            [0.0, 90.0, 180.0, 270.0],
            [100.0, 35.0, 70.0, 20.0],
            base=1.0,
            width=70.0,
            color="#0284c7",
            opacity=1.0,
            animation=False,
            name="range",
        ),
        xy.line(
            [0.0, 90.0, 180.0, 270.0, 360.0],
            [100.0, 35.0, 70.0, 20.0, 100.0],
            color="#f97316",
            width=2.0,
            name="outline",
        ),
        xy.scatter(
            [0.0, 90.0, 180.0, 270.0],
            [100.0, 35.0, 70.0, 20.0],
            color="#111827",
            size=7.0,
        ),
        xy.theta_axis(unit="degrees", zero="N", direction="clockwise"),
        xy.r_axis(type_="log", domain=(1.0, 100.0), hole=0.28),
        width=520,
        height=520,
        title="Composed polar bars + line + scatter",
    )

    origin_descending_wedge = xy.polar_chart(
        # Descending endpoint order exercises the other annular-strip
        # orientation. On this log axis the visible minimum sits at exactly
        # one third of the disc because r_origin=1 is one decade below it.
        xy.bar(
            [0.0],
            [-990.0],
            base=1000.0,
            width=90.0,
            color="#a855f7",
            opacity=1.0,
            animation=False,
            name="descending annular bar",
        ),
        xy.theta_axis(unit="degrees"),
        xy.r_axis(type_="log", domain=(10.0, 1000.0), origin=1.0),
        width=520,
        height=520,
        title="Descending bar + log-r origin",
    )

    return [
        Case(
            "heatmap_contour",
            heatmap_contour,
            frozenset({"heatmap", "contour"}),
            10_000,
            "circular",
            log_radius=True,
            probe=(90.0, 10.0),
            probe_kind="heatmap",
            gl_colors=(("#ff00ff", 30),),
            static_colors=(("#ff00ff", 30),),
        ),
        Case(
            "sector_hole_errorbars",
            sector_hole_errors,
            frozenset({"errorbar", "scatter"}),
            100,
            "circular",
            sector=(-110.0, 110.0),
            hole=0.35,
            probe=(0.0, 2.5),
            probe_kind="errorbar",
            gl_colors=(("#dc2626", 30),),
            static_colors=(("#dc2626", 30),),
        ),
        Case(
            "categorical_log_polygon",
            categorical_log_polygon,
            frozenset({"line", "scatter"}),
            100,
            "linear",
            log_radius=True,
            labels=("N", "NE", "E", "SE", "S", "SW", "W", "NW"),
            probe=(2.0, 25.0),
            probe_kind="line",
            chrome_colors=(("#10b981", 100),),
            static_colors=(("#10b981", 100),),
        ),
        Case(
            "symlog_origin",
            symlog_origin,
            frozenset({"line", "scatter"}),
            20,
            "circular",
            origin=-100.0,
            symlog_radius=True,
            probe=(45.0, 0.0),
            probe_kind="scatter",
            gl_colors=(("#7c3aed", 10), ("#0f766e", 10)),
            static_colors=(("#7c3aed", 10), ("#0f766e", 10)),
        ),
        Case(
            "composed_wedges",
            composed_wedges,
            frozenset({"bar", "line", "scatter"}),
            1_000,
            "circular",
            hole=0.28,
            log_radius=True,
            probe=(0.0, 10.0),
            probe_kind="bar",
            gl_colors=(("#0284c7", 500), ("#f97316", 20)),
            static_colors=(("#0284c7", 500), ("#f97316", 20)),
        ),
        Case(
            "origin_descending_wedge",
            origin_descending_wedge,
            frozenset({"bar"}),
            1_000,
            "circular",
            origin=1.0,
            log_radius=True,
            inner_fraction=1.0 / 3.0,
            probe=(0.0, 100.0),
            probe_kind="bar",
            gl_colors=(("#a855f7", 500),),
            static_colors=(("#a855f7", 500),),
        ),
    ]


def _find_chromium(authored: str | None) -> str:
    if authored:
        return authored
    for candidate in CHROMIUM_CANDIDATES:
        if Path(candidate).is_file() or shutil.which(candidate):
            return candidate
    raise SystemExit("no Chromium binary found; pass one as the first argument")


def _rgb_targets(targets: tuple[tuple[str, int], ...]) -> list[dict[str, Any]]:
    encoded: list[dict[str, Any]] = []
    for color, minimum in targets:
        value = color.removeprefix("#")
        if len(value) != 6:
            raise AssertionError(f"smoke target must be a six-digit hex color, got {color!r}")
        encoded.append(
            {
                "name": color.lower(),
                "rgb": [int(value[offset : offset + 2], 16) for offset in (0, 2, 4)],
                "min": minimum,
            }
        )
    return encoded


def _page(
    spec: dict[str, Any],
    blob: bytes,
    probe: tuple[float, float],
    gl_colors: tuple[tuple[str, int], ...],
    chrome_colors: tuple[tuple[str, int], ...],
) -> str:
    client = _javascript_for_inline_script(_bundled_js("standalone"))
    blob64 = base64.b64encode(blob).decode("ascii")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>pending</title>
<style>html,body{{margin:0;background:#fff}}#chart{{width:100%}}</style></head>
<body><div id="chart"></div>
<script>{client}</script>
<script>
const spec = {json.dumps(spec)};
const probe = {json.dumps(probe)};
const glTargets = {json.dumps(_rgb_targets(gl_colors))};
const chromeTargets = {json.dumps(_rgb_targets(chrome_colors))};
const bytes = Uint8Array.from(atob("{blob64}"), c => c.charCodeAt(0));
try {{
  const view = xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);
  setTimeout(() => {{
    try {{
      view._drawNow();
      const gl = view.gl;
      const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
      const px = new Uint8Array(w * h * 4);
      gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
      let lit = 0, minX = w, minY = h, maxX = -1, maxY = -1;
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {{
        if (px[(y * w + x) * 4 + 3] <= 8) continue;
        lit++;
        minX = Math.min(minX, x); minY = Math.min(minY, y);
        maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
      }}
      const countTargets = (pixels, targets) => Object.fromEntries(
        targets.map(target => {{
          let count = 0;
          for (let i = 0; i < pixels.length; i += 4) {{
            if (pixels[i + 3] <= 8) continue;
            if (
              Math.abs(pixels[i] - target.rgb[0]) <= 24 &&
              Math.abs(pixels[i + 1] - target.rgb[1]) <= 24 &&
              Math.abs(pixels[i + 2] - target.rgb[2]) <= 24
            ) count++;
          }}
          return [target.name, count];
        }})
      );
      const chrome = view.chrome.getContext("2d").getImageData(
        0, 0, view.chrome.width, view.chrome.height
      ).data;
      const glColorCounts = countTargets(px, glTargets);
      const chromeColorCounts = countTargets(chrome, chromeTargets);
      const geom = view._polarGeometry();
      const innerFraction = view._polarRadius(
        geom, geom.rLo, {{coord: true}}
      ) / geom.radius;
      const localX = geom.cx - view.plot.x;
      const localY = geom.cy - view.plot.y;
      const sampleX = Math.max(0, Math.min(w - 1, Math.round(localX * view.dpr)));
      const sampleY = Math.max(0, Math.min(h - 1, Math.round((view.plot.h - localY) * view.dpr)));
      const centerAlpha = px[(sampleY * w + sampleX) * 4 + 3];
      const inverseCenter = view._dataFromCanvas(localX, localY).map(
        value => Number.isFinite(value) ? value : null
      );
      const projectedProbe = view._polarProject(probe[0], probe[1], geom);
      const probeX = projectedProbe[0] - view.plot.x;
      const probeY = projectedProbe[1] - view.plot.y;
      const inverseProbe = view._dataFromCanvas(probeX, probeY).map(
        value => Number.isFinite(value) ? value : null
      );
      const probeHit = view._hoverAt(probeX, probeY);
      const labels = Array.from(document.querySelectorAll(".xy div"))
        .map(node => (node.textContent || "").trim()).filter(Boolean);
      const result = {{
        lit, total: w * h, bounds: [minX, minY, maxX, maxY],
        centerAlpha, inverseCenter, labels,
        projectedProbe, inverseProbe,
        probeHitKind: probeHit ? probeHit.g.trace.kind : null,
        glColorCounts, chromeColorCounts,
        radius: geom.radius, hole: geom.hole, innerFraction,
        sector: [geom.sectorStart, geom.sectorEnd],
        fullSector: geom.fullSector, gridShape: geom.gridShape,
        gpuTraces: view.gpuTraces.map(g => ({{
          kind: g.trace.kind, n: g.n, width: g.width,
          value0Mode: g.value0Mode, value0Const: g.value0Const,
          pos: g._cpuBar ? Array.from(g._cpuBar.pos) : null,
          value1: g._cpuBar ? Array.from(g._cpuBar.value1) : null,
        }})),
        glError: gl.getError(),
      }};
      document.title = "XY_OK " + JSON.stringify(result);
    }} catch (error) {{
      document.title = "XY_ERROR " + (error.stack || error.message);
    }}
  }}, 250);
}} catch (error) {{
  document.title = "XY_ERROR " + (error.stack || error.message);
}}
</script></body></html>"""


def _validate_spec(case: Case, spec: dict[str, Any]) -> None:
    kinds = {trace["kind"] for trace in spec["traces"]}
    missing = case.marks - kinds
    if missing:
        raise AssertionError(f"{case.name}: payload lost trace kinds {sorted(missing)}")
    x_axis = spec["x_axis"]
    y_axis = spec["y_axis"]
    if x_axis["grid_shape"] != case.grid_shape:
        raise AssertionError(f"{case.name}: grid shape did not reach the wire")
    if case.sector is not None and tuple(x_axis["sector"]) != case.sector:
        raise AssertionError(f"{case.name}: sector did not reach the wire")
    if not math.isclose(float(y_axis["hole"]), case.hole):
        raise AssertionError(f"{case.name}: hole did not reach the wire")
    if case.log_radius and y_axis.get("scale") != "log":
        raise AssertionError(f"{case.name}: logarithmic radial scale did not reach the wire")
    if case.symlog_radius and y_axis.get("scale") != "symlog":
        raise AssertionError(f"{case.name}: symlog radial scale did not reach the wire")
    if case.origin is None:
        if "r_origin" in y_axis:
            raise AssertionError(f"{case.name}: payload invented a radial origin")
    elif not math.isclose(float(y_axis.get("r_origin", math.nan)), case.origin):
        raise AssertionError(f"{case.name}: radial origin did not reach the wire")
    if case.labels and x_axis.get("kind") != "category":
        raise AssertionError(f"{case.name}: categorical theta was not encoded as categories")


def _validate_live(case: Case, metrics: dict[str, Any]) -> None:
    if metrics["lit"] < case.min_live_pixels:
        raise AssertionError(
            f"{case.name}: only {metrics['lit']} live WebGL pixels "
            f"(expected at least {case.min_live_pixels}); "
            f"gpu={metrics.get('gpuTraces')}, glError={metrics.get('glError')}"
        )
    if metrics["bounds"][2] < metrics["bounds"][0] or metrics["bounds"][3] < metrics["bounds"][1]:
        raise AssertionError(f"{case.name}: live WebGL output has no finite pixel bounds")
    if metrics["gridShape"] != case.grid_shape:
        raise AssertionError(f"{case.name}: client geometry lost grid_shape")
    if case.origin is None:
        if not math.isclose(float(metrics["hole"]), case.hole, abs_tol=1e-9):
            raise AssertionError(f"{case.name}: client geometry lost the authored hole")
        if not math.isclose(float(metrics["innerFraction"]), case.hole, abs_tol=1e-9):
            raise AssertionError(f"{case.name}: client visible inner radius lost the authored hole")
    elif not 0.0 < float(metrics["innerFraction"]) < 1.0:
        raise AssertionError(f"{case.name}: radial origin did not create a live annulus")
    if case.inner_fraction is not None and not math.isclose(
        float(metrics["innerFraction"]), case.inner_fraction, rel_tol=1e-9, abs_tol=1e-9
    ):
        raise AssertionError(
            f"{case.name}: live inner radius is {metrics['innerFraction']}, "
            f"expected {case.inner_fraction}"
        )
    if case.sector is not None:
        if metrics["fullSector"]:
            raise AssertionError(f"{case.name}: partial sector was treated as a full turn")
        if not np.allclose(metrics["sector"], case.sector):
            raise AssertionError(f"{case.name}: client geometry lost the authored sector")
    if (case.hole or case.origin is not None) and (
        metrics["centerAlpha"] != 0 or metrics["inverseCenter"] != [None, None]
    ):
        raise AssertionError(f"{case.name}: the live hole is painted or hit-testable")
    if not np.all(np.isfinite(metrics["projectedProbe"])):
        raise AssertionError(f"{case.name}: live forward projection returned a non-finite point")
    if not np.allclose(metrics["inverseProbe"], case.probe, rtol=1e-6, atol=1e-6):
        raise AssertionError(
            f"{case.name}: live projection inverse returned {metrics['inverseProbe']}, "
            f"expected {case.probe}"
        )
    if metrics["probeHitKind"] != case.probe_kind:
        raise AssertionError(
            f"{case.name}: live hover hit {metrics['probeHitKind']!r}, expected {case.probe_kind!r}"
        )
    live_labels = set(metrics["labels"])
    for label in case.labels:
        if label not in live_labels:
            raise AssertionError(f"{case.name}: live categorical label {label!r} is missing")
    for color, minimum in case.gl_colors:
        count = int(metrics["glColorCounts"].get(color, 0))
        if count < minimum:
            raise AssertionError(
                f"{case.name}: live WebGL has only {count} {color} pixels "
                f"(expected at least {minimum})"
            )
    for color, minimum in case.chrome_colors:
        count = int(metrics["chromeColorCounts"].get(color, 0))
        if count < minimum:
            raise AssertionError(
                f"{case.name}: live chrome has only {count} {color} pixels "
                f"(expected at least {minimum})"
            )


def _run_live(
    case: Case,
    chromium: str,
    page: Path,
    screenshot: Path | None,
) -> dict[str, Any]:
    command = [
        chromium,
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--virtual-time-budget=5000",
        "--dump-dom",
    ]
    if screenshot is not None:
        command.extend(
            [
                f"--window-size={int(case.chart.width)},{int(case.chart.height)}",
                f"--screenshot={screenshot}",
            ]
        )
    command.append(page.as_uri())
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    match = re.search(r"<title>([^<]*)</title>", result.stdout)
    title = html.unescape(match.group(1)) if match else "(no title in DOM dump)"
    if not title.startswith("XY_OK "):
        print(result.stderr[-2000:])
        raise AssertionError(f"{case.name}: live render failed: {title[:500]}")
    metrics = json.loads(title.removeprefix("XY_OK "))
    _validate_live(case, metrics)
    return metrics


def _validate_static(case: Case, figure: Any, output_dir: Path) -> tuple[int, int, float]:
    svg = figure.to_image(format="svg")
    ET.fromstring(svg)
    if re.search(rb"(?<![A-Za-z])(nan|inf)(?![A-Za-z])", svg, re.IGNORECASE):
        raise AssertionError(f"{case.name}: SVG contains a non-finite coordinate")
    if case.name == "heatmap_contour" and b"<image" not in svg:
        raise AssertionError(f"{case.name}: SVG lost the inverse-rasterized heatmap")

    png = figure.to_image(format="png", engine=xy.Engine.default, scale=1)
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError(f"{case.name}: native export is not a PNG")
    image = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))
    ink = np.any(image < 245, axis=2)
    ink_fraction = float(ink.mean())
    if not 0.001 < ink_fraction < 0.95:
        raise AssertionError(f"{case.name}: suspicious native PNG ink fraction {ink_fraction:.4f}")
    for color, minimum in case.static_colors:
        target = np.asarray(_rgb_targets(((color, minimum),))[0]["rgb"], dtype=np.int16)
        distance = np.abs(image.astype(np.int16) - target[None, None, :])
        count = int(np.all(distance <= 24, axis=2).sum())
        if count < minimum:
            raise AssertionError(
                f"{case.name}: native PNG has only {count} {color} pixels "
                f"(expected at least {minimum})"
            )

    (output_dir / f"{case.name}.svg").write_bytes(svg)
    (output_dir / f"{case.name}.png").write_bytes(png)
    return len(svg), len(png), ink_fraction


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chromium", nargs="?", help="Chromium/Chrome executable")
    parser.add_argument(
        "--artifacts",
        type=Path,
        help="retain HTML plus browser, SVG, and PNG renders in this directory",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_names",
        help="run only this named case (repeatable; defaults to all cases)",
    )
    args = parser.parse_args()
    chromium = _find_chromium(args.chromium)
    cases = _cases()
    if args.case_names:
        selected = set(args.case_names)
        available = {case.name for case in cases}
        unknown = selected - available
        if unknown:
            parser.error(
                f"unknown --case value(s): {', '.join(sorted(unknown))}; "
                f"choose from {', '.join(sorted(available))}"
            )
        cases = [case for case in cases if case.name in selected]

    temporary = None
    if args.artifacts is None:
        temporary = tempfile.TemporaryDirectory()
        output_dir = Path(temporary.name)
    else:
        output_dir = args.artifacts.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

    try:
        for case in cases:
            figure = case.chart.figure()
            spec, blob = figure.build_payload()
            _validate_spec(case, spec)
            page = output_dir / f"{case.name}.html"
            page.write_text(
                _page(spec, blob, case.probe, case.gl_colors, case.chrome_colors),
                encoding="utf-8",
            )
            screenshot = (
                output_dir / f"{case.name}.browser.png" if args.artifacts is not None else None
            )
            metrics = _run_live(case, chromium, page, screenshot)
            svg_bytes, png_bytes, ink_fraction = _validate_static(case, figure, output_dir)
            print(
                f"{case.name}: live={metrics['lit']} px, "
                f"SVG={svg_bytes} B, PNG={png_bytes} B, "
                f"native ink={ink_fraction:.2%}"
            )
    finally:
        if temporary is not None:
            temporary.cleanup()
    print("polar phase 6/7 live examples: browser, SVG, and PNG all OK")


if __name__ == "__main__":
    main()
