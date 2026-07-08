#!/usr/bin/env python3
"""Screenshot-level visual smoke for representative fastcharts charts.

This complements the low-level WebGL readback smoke by exercising the public
Python API plus Chromium screenshot path across the core chart families. It is
not a pixel-perfect golden suite yet; it catches the class of failures we keep
seeing in the example app: blank canvases, missing render lifecycle redraws, and
charts that collapse to a flat screenshot.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import fastcharts as fc  # noqa: E402
from fastcharts.export import find_chromium  # noqa: E402

CHART_ASSET_DIR = ROOT / "reflex_fastcharts_app" / "assets" / "charts"
W, H, SCALE = 720, 440, 1.0
EXPECTED_W = int(W * SCALE)
EXPECTED_H = int(H * SCALE)
ASSET_W, ASSET_H = 900, 520


@dataclass(frozen=True)
class PngStats:
    width: int
    height: int
    non_white: int
    colored: int
    unique_colors: int


@dataclass(frozen=True)
class RegionStats:
    non_white: int
    colored: int
    dark: int


def _png_rgba(data: bytes) -> tuple[int, int, bytes]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("screenshot output is not a PNG")
    pos = 8
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        chunk_type = data[pos + 4 : pos + 8]
        start = pos + 8
        chunk = data[start : start + length]
        pos = start + length + 4
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
        elif chunk_type == b"IDAT":
            idat += chunk
        elif chunk_type == b"IEND":
            break
    if width is None or height is None or bit_depth != 8 or interlace != 0:
        raise ValueError("unsupported PNG geometry")
    channels = {0: 1, 2: 3, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError(f"unsupported PNG color type {color_type}")
    raw = zlib.decompress(bytes(idat))
    row_len = width * channels
    bpp = channels
    rows = bytearray(width * height * 4)
    prev = bytearray(row_len)
    raw_pos = 0
    out_pos = 0
    for _ in range(height):
        filt = raw[raw_pos]
        raw_pos += 1
        row = bytearray(raw[raw_pos : raw_pos + row_len])
        raw_pos += row_len
        for i, value in enumerate(row):
            left = row[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            if filt == 1:
                row[i] = (value + left) & 0xFF
            elif filt == 2:
                row[i] = (value + up) & 0xFF
            elif filt == 3:
                row[i] = (value + ((left + up) >> 1)) & 0xFF
            elif filt == 4:
                p = left + up - up_left
                pa = abs(p - left)
                pb = abs(p - up)
                pc = abs(p - up_left)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
                row[i] = (value + predictor) & 0xFF
            elif filt != 0:
                raise ValueError(f"unsupported PNG filter {filt}")
        if channels == 4:
            rows[out_pos : out_pos + width * 4] = row
        else:
            for x in range(width):
                if channels == 1:
                    r = g = b = row[x]
                else:
                    r, g, b = row[x * 3 : x * 3 + 3]
                base = out_pos + x * 4
                rows[base : base + 4] = bytes((r, g, b, 255))
        prev = row
        out_pos += width * 4
    return width, height, bytes(rows)


def _png_stats(data: bytes) -> PngStats:
    width, height, rgba = _png_rgba(data)
    sample = 3
    unique: set[tuple[int, int, int]] = set()
    non_white = 0
    colored = 0
    for i in range(0, len(rgba), 4):
        r, g, b, a = rgba[i : i + 4]
        if a <= 8:
            continue
        if r < 245 or g < 245 or b < 245:
            non_white += 1
        if max(r, g, b) - min(r, g, b) > 24:
            colored += 1
        if i % (4 * sample) == 0:
            unique.add((r, g, b))
    return PngStats(width, height, non_white, colored, len(unique))


def _region_stats(
    rgba: bytes,
    width: int,
    height: int,
    box: tuple[float, float, float, float],
) -> RegionStats:
    x0, y0, x1, y1 = box
    left = max(0, min(width, int(width * x0)))
    top = max(0, min(height, int(height * y0)))
    right = max(left, min(width, int(width * x1)))
    bottom = max(top, min(height, int(height * y1)))
    non_white = 0
    colored = 0
    dark = 0
    for y in range(top, bottom):
        row = y * width * 4
        for x in range(left, right):
            i = row + x * 4
            r, g, b, a = rgba[i : i + 4]
            if a <= 8:
                continue
            if r < 245 or g < 245 or b < 245:
                non_white += 1
            if max(r, g, b) - min(r, g, b) > 24:
                colored += 1
            if r < 180 or g < 180 or b < 180:
                dark += 1
    return RegionStats(non_white=non_white, colored=colored, dark=dark)


def _active_plot_cells(
    rgba: bytes,
    width: int,
    height: int,
    box: tuple[float, float, float, float],
) -> int:
    x0, y0, x1, y1 = box
    active = 0
    cols, rows = 4, 3
    for row in range(rows):
        for col in range(cols):
            cell = (
                x0 + (x1 - x0) * col / cols,
                y0 + (y1 - y0) * row / rows,
                x0 + (x1 - x0) * (col + 1) / cols,
                y0 + (y1 - y0) * (row + 1) / rows,
            )
            if _region_stats(rgba, width, height, cell).non_white > 80:
                active += 1
    return active


def _assert_layout_regions(
    name: str,
    data: bytes,
    *,
    expected: tuple[int, int],
    asset: bool = False,
) -> None:
    width, height, rgba = _png_rgba(data)
    if (width, height) != expected:
        raise SystemExit(
            f"{name}: unexpected PNG dims {width}x{height}, want {expected[0]}x{expected[1]}"
        )
    # App assets are 430px-tall chart documents inside a 520px screenshot.
    # Their axis band sits above the bottom of the browser viewport.
    if asset:
        title_box = (0.18, 0.0, 0.82, 0.14)
        plot_box = (0.09, 0.12, 0.94, 0.72)
        x_axis_box = (0.08, 0.68, 0.94, 0.84)
    else:
        title_box = (0.18, 0.0, 0.82, 0.16)
        plot_box = (0.09, 0.15, 0.94, 0.83)
        # Chromium screenshot geometry can place the bottom tick labels a bit
        # above the final 18% of the viewport. Sample a broader lower band so
        # the gate catches missing x-axis chrome instead of runner-specific
        # subpixel layout.
        x_axis_box = (0.08, 0.70, 0.94, 0.99)
    y_axis_box = (0.0, 0.15, 0.16, 0.83)
    regions = {
        "title": _region_stats(rgba, width, height, title_box),
        "plot": _region_stats(rgba, width, height, plot_box),
        "x-axis": _region_stats(rgba, width, height, x_axis_box),
        "y-axis": _region_stats(rgba, width, height, y_axis_box),
    }
    minimums = {
        "title": (500, 200),
        "plot": (1_200, 0),
        "x-axis": (700, 250),
        "y-axis": (500, 200),
    }
    for label, stats in regions.items():
        min_non_white, min_dark = minimums[label]
        if stats.non_white < min_non_white:
            raise SystemExit(
                f"{name}: {label} region is too empty "
                f"({stats.non_white} non-white px, want >= {min_non_white})"
            )
        if min_dark and stats.dark < min_dark:
            raise SystemExit(
                f"{name}: {label} region lost dark text/chrome "
                f"({stats.dark} dark px, want >= {min_dark})"
            )
    if regions["plot"].colored < 100:
        raise SystemExit(
            f"{name}: plot region has too little colored chart data "
            f"({regions['plot'].colored} colored px)"
        )
    active_cells = _active_plot_cells(rgba, width, height, plot_box)
    if active_cells < 8:
        raise SystemExit(f"{name}: chart collapsed in plot region ({active_cells}/12 active cells)")


def _assert_visual(
    name: str,
    data: bytes,
    *,
    expected: tuple[int, int] = (EXPECTED_W, EXPECTED_H),
    asset: bool = False,
) -> PngStats:
    stats = _png_stats(data)
    if (stats.width, stats.height) != expected:
        raise SystemExit(
            f"{name}: unexpected PNG dims {stats.width}x{stats.height}, "
            f"want {expected[0]}x{expected[1]}"
        )
    total = stats.width * stats.height
    min_non_white = max(600, int(total * 0.004))
    min_colored = max(180, int(total * 0.0008))
    if stats.non_white < min_non_white:
        raise SystemExit(f"{name}: screenshot is too blank ({stats.non_white} non-white px)")
    if stats.colored < min_colored:
        raise SystemExit(f"{name}: screenshot has too little colored data ({stats.colored} px)")
    if stats.unique_colors < 24:
        raise SystemExit(f"{name}: screenshot is visually flat ({stats.unique_colors} colors)")
    _assert_layout_regions(name, data, expected=expected, asset=asset)
    return stats


def _screenshot_page(chromium: str, page: Path, *, width: int, height: int) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "screenshot.png"
        proc = subprocess.run(
            [
                chromium,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--allow-file-access-from-files",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--hide-scrollbars",
                f"--window-size={width},{height}",
                "--virtual-time-budget=7000",
                f"--screenshot={out}",
                page.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or "")[-500:]
            raise SystemExit(f"screenshot chromium failed for {page.name}: {tail}")
        if not out.is_file():
            raise SystemExit(f"screenshot chromium did not write {out}")
        return out.read_bytes()


LABEL_OVERLAP_SCRIPT = r"""
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    if (view && typeof view._syncContainerSize === "function") view._syncContainerSize();
    if (view && typeof view._drawNow === "function") view._drawNow();
    let tickNodes = [];
    for (let i = 0; i < 80; i++) {
      tickNodes = Array.from(document.querySelectorAll("[data-fc-label-kind='tick']"));
      if (tickNodes.length) break;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    const labels = tickNodes.map((el) => {
      const r = el.getBoundingClientRect();
      return {
        axis: el.dataset.fcAxis || "",
        side: el.dataset.fcAxisSide || "",
        text: el.textContent || "",
        left: r.left,
        right: r.right,
        top: r.top,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      };
    }).filter((r) => r.width > 0 && r.height > 0);
    const groups = new Map();
    for (const label of labels) {
      const key = `${label.axis}:${label.side}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(label);
    }
    const overlaps = [];
    const slack = 1.5;
    function intersects(a, b) {
      return a.left < b.right - slack && b.left < a.right - slack &&
        a.top < b.bottom - slack && b.top < a.bottom - slack;
    }
    for (const [group, items] of groups) {
      for (let i = 0; i < items.length; i++) {
        for (let j = i + 1; j < items.length; j++) {
          if (intersects(items[i], items[j])) {
            overlaps.push({group, a: items[i].text, b: items[j].text});
          }
        }
      }
    }
    document.body.setAttribute("data-fc-label-overlap", JSON.stringify({
      label_count: labels.length,
      overlap_count: overlaps.length,
      overlaps: overlaps.slice(0, 8),
    }));
  } catch (err) {
    document.body.setAttribute("data-fc-label-overlap-error", String(err && err.stack || err));
  }
})();
</script>
"""


def _dump_dom(chromium: str, page: Path) -> str:
    proc = subprocess.run(
        [
            chromium,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--allow-file-access-from-files",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--hide-scrollbars",
            "--window-size=900,520",
            "--virtual-time-budget=7000",
            "--dump-dom",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-500:]
        raise SystemExit(f"label-overlap probe chromium failed for {page.name}: {tail}")
    return proc.stdout


def _assert_no_tick_label_overlaps_from_document(
    name: str,
    document: str,
    chromium: str,
) -> None:
    standalone_render_call = (
        'fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);'
    )
    standalone_capture_call = (
        "window.__fcProbeView = fastcharts.renderStandalone("
        'document.getElementById("chart"), spec, bytes.buffer);'
    )
    live_render_call = "const view = new fastcharts.ChartView("
    live_capture_call = "const view = window.__fcProbeView = new fastcharts.ChartView("
    if standalone_render_call in document:
        document = document.replace(standalone_render_call, standalone_capture_call, 1)
    elif live_render_call in document:
        document = document.replace(live_render_call, live_capture_call, 1)
    else:
        raise SystemExit(f"{name}: unsupported chart render call for label-overlap probe")
    if "</body>" not in document:
        raise SystemExit(f"{name}: standalone HTML has no body close tag")
    document = document.replace("</body>", LABEL_OVERLAP_SCRIPT + "\n</body>", 1)
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / f"{name}.html"
        page.write_text(document, encoding="utf-8")
        dom = _dump_dom(chromium, page)

    error = re.search(r'data-fc-label-overlap-error="([^"]*)"', dom)
    if error:
        raise SystemExit(f"{name}: label overlap probe failed: {html_lib.unescape(error.group(1))}")
    match = re.search(r'data-fc-label-overlap="([^"]*)"', dom)
    if not match:
        raise SystemExit(f"{name}: label overlap probe did not finish")
    payload = json.loads(html_lib.unescape(match.group(1)))
    if payload["label_count"] <= 0:
        raise SystemExit(f"{name}: label overlap probe found no rendered tick labels")
    if payload["overlap_count"]:
        raise SystemExit(f"{name}: tick label overlaps detected: {payload['overlaps']}")


def _assert_no_tick_label_overlaps(name: str, chart: fc.Chart, chromium: str) -> None:
    _assert_no_tick_label_overlaps_from_document(name, chart.to_html(), chromium)


def _scatter_chart() -> fc.Chart:
    rng = np.random.default_rng(10)
    n = 8_000
    x = rng.normal(size=n)
    y = 0.55 * x + rng.normal(scale=0.55, size=n)
    segment = np.where(x > 0.7, "growth", np.where(x < -0.7, "risk", "core"))
    return fc.chart(
        fc.scatter(x=x, y=y, color=segment, size=5, name="accounts", opacity=0.72),
        fc.x_axis(label="activation"),
        fc.y_axis(label="retention"),
        fc.legend(),
        fc.tooltip(fields=["activation", "retention", "segment"], title="{segment}"),
        title="visual smoke scatter",
        width=W,
        height=H,
    )


def _line_area_chart() -> fc.Chart:
    x = np.linspace(0.0, 36.0, 900)
    y = 54.0 + 0.8 * x + 5.5 * np.sin(x / 2.7)
    trend = 54.0 + 0.8 * x
    return fc.chart(
        fc.area(x=x, y=y - 7.0, color="#93c5fd", opacity=0.28, name="range"),
        fc.line(x=x, y=y, color="#2563eb", width=2.0, name="actual"),
        fc.line(x=x, y=trend, color="#f97316", width=1.8, name="trend"),
        fc.threshold(72.0, text="target", color="#16a34a"),
        fc.x_axis(label="week"),
        fc.y_axis(label="score"),
        fc.legend(),
        title="visual smoke line and area",
        width=W,
        height=H,
    )


def _bar_chart() -> fc.Chart:
    categories = ["Search", "Ads", "Email", "Direct", "Partner", "Social"]
    values = np.array(
        [
            [118, 88, 42],
            [94, 76, 39],
            [72, 55, 26],
            [66, 48, 31],
            [43, 29, 19],
            [31, 22, 14],
        ],
        dtype=float,
    )
    return fc.chart(
        fc.bar(
            x=categories,
            y=values,
            series=["Desktop", "Mobile", "Tablet"],
            colors=["#2563eb", "#16a34a", "#f59e0b"],
            name="conversions",
            mode="grouped",
        ),
        fc.x_axis(label="channel"),
        fc.y_axis(label="conversions"),
        fc.legend(),
        title="visual smoke grouped bars",
        width=W,
        height=H,
    )


def _histogram_chart() -> fc.Chart:
    rng = np.random.default_rng(11)
    values = np.concatenate(
        [
            rng.normal(-1.15, 0.48, 45_000),
            rng.normal(1.35, 0.62, 35_000),
        ]
    )
    return fc.chart(
        fc.histogram(values, bins=180, color="#3b82f6", name="distribution"),
        fc.x_axis(label="value"),
        fc.y_axis(label="count"),
        fc.legend(),
        title="visual smoke histogram",
        width=W,
        height=H,
    )


def _heatmap_chart() -> fc.Chart:
    x = np.linspace(-2.8, 2.8, 70)
    y = np.linspace(-2.2, 2.2, 54)
    xx, yy = np.meshgrid(x, y)
    z = np.exp(-((xx - 0.9) ** 2 + (yy + 0.25) ** 2)) + 0.7 * np.exp(
        -((xx + 1.1) ** 2 + (yy - 0.6) ** 2) / 0.55
    )
    return fc.chart(
        fc.heatmap(z, x=x, y=y, colormap="viridis", name="load"),
        fc.text(-1.05, 0.6, "cluster A", color="#111827"),
        fc.marker(0.9, -0.25, text="peak", color="#f97316"),
        fc.x_axis(label="dimension A"),
        fc.y_axis(label="dimension B"),
        fc.legend(),
        title="visual smoke heatmap",
        width=W,
        height=H,
    )


def _composed_axes_chart() -> fc.Chart:
    x = np.arange(1, 13, dtype=float)
    revenue = np.array([18, 21, 24, 31, 37, 44, 48, 53, 58, 62, 66, 72], dtype=float)
    latency = np.array([220, 190, 168, 144, 128, 116, 104, 96, 90, 84, 79, 73], dtype=float)
    return fc.chart(
        fc.bar(x=x, y=revenue, color="#60a5fa", name="revenue", y_axis="y"),
        fc.line(x=x, y=latency, color="#dc2626", width=2.2, name="latency", y_axis="y2"),
        fc.x_axis(label="month", tick_count=6),
        fc.y_axis(label="revenue", domain=(0, 90), format=".0f"),
        fc.y_axis(
            id="y2",
            label="latency",
            side="right",
            reverse=True,
            domain=(60, 240),
            format=".0f",
        ),
        fc.x_band(5, 7, text="launch", color="#f59e0b", opacity=0.12),
        fc.legend(style={"background": "rgba(255,255,255,0.82)", "borderRadius": "8px"}),
        title="visual smoke composed axes",
        width=W,
        height=H,
    )


def _axes_scales_stress_chart() -> fc.Chart:
    x = np.logspace(0.0, 12.0, 360)
    rank = 210.0 - np.log10(x) * 13.5 + 3.0 * np.sin(np.log10(x) * 1.7)
    conversion = 0.006 + np.log10(x) * 0.0042
    return fc.chart(
        fc.line(x=x, y=rank, color="#2563eb", width=2.0, name="rank"),
        fc.line(
            x=x,
            y=conversion,
            color="#dc2626",
            width=2.0,
            name="conversion",
            y_axis="y2",
        ),
        fc.x_axis(
            label="request volume",
            type_="log",
            domain=(1.0, 1_000_000_000_000.0),
            format=",.0f",
            tick_count=26,
            tick_label_min_gap=14,
        ),
        fc.y_axis(
            label="rank (reversed)",
            domain=(0.0, 220.0),
            reverse=True,
            format=",.0f",
            label_position={"left": 22, "top": "52%"},
        ),
        fc.y_axis(
            id="y2",
            label="conversion",
            side="right",
            domain=(0.0, 0.06),
            format=".0%",
            label_position={"right": 18, "top": "16%"},
            style={"axis_color": "#dc2626", "tick_color": "#dc2626"},
        ),
        fc.legend(style={"background": "rgba(255,255,255,0.84)", "borderRadius": "8px"}),
        title="visual smoke axes and scales stress",
        width=W,
        height=H,
    )


def _custom_chrome_chart() -> fc.Chart:
    rng = np.random.default_rng(12)
    x = rng.normal(size=4_000)
    y = 0.35 * x + rng.normal(scale=0.5, size=x.size)
    return fc.chart(
        fc.scatter(x=x, y=y, color=np.where(y > 0.25, "expansion", "base"), size=6),
        fc.x_axis(label="activation"),
        fc.y_axis(label="retention"),
        fc.legend(
            object(),
            show=False,
            style={"padding": "10px", "background": "linear-gradient(135deg,#111827,#2563eb)"},
        ),
        fc.tooltip(
            object(),
            show=False,
            fields=["activation", "retention"],
            style={"background": "linear-gradient(135deg,#111827,#7c3aed)"},
        ),
        title="visual smoke custom chrome hooks",
        width=W,
        height=H,
    )


def _adaptive_density_chart() -> fc.Chart:
    rng = np.random.default_rng(13)
    n = 260_000
    x = rng.normal(size=n)
    y = 0.45 * x + rng.normal(scale=0.7, size=n)
    return fc.chart(
        fc.scatter(x=x, y=y, colormap="viridis", name="density", density=True),
        fc.x_axis(label="feature A"),
        fc.y_axis(label="feature B"),
        fc.legend(),
        title="visual smoke adaptive density overview",
        width=W,
        height=H,
    )


CASES: tuple[tuple[str, Callable[[], fc.Chart]], ...] = (
    ("scatter", _scatter_chart),
    ("line_area", _line_area_chart),
    ("grouped_bar", _bar_chart),
    ("histogram", _histogram_chart),
    ("heatmap_annotations", _heatmap_chart),
    ("composed_dual_axis", _composed_axes_chart),
    ("axes_scales_stress", _axes_scales_stress_chart),
    ("custom_chrome", _custom_chrome_chart),
    ("adaptive_density", _adaptive_density_chart),
)

ASSET_CASES: tuple[str, ...] = (
    "custom_chrome.html",
    "business_overview.html",
    "retention_cohort.html",
    "line_walk.html",
    "area.html",
    "histogram.html",
    "bar_column.html",
    "stacked_bar.html",
    "horizontal_bar.html",
    "heatmap.html",
    "composed_layers.html",
    "annotated_heatmap.html",
    "axes_scales.html",
    "interaction_basics.html",
    "density_scatter.html",
    "colored_scatter.html",
    "live_drilldown_10m.html",
    "live_drilldown_100m.html",
)


def main() -> None:
    chromium = sys.argv[1] if len(sys.argv) > 1 else find_chromium()
    if chromium is None:
        print("visual regression smoke SKIPPED (no chromium)")
        return
    for name, factory in CASES:
        chart = factory()
        png = chart.to_png(width=W, height=H, scale=SCALE, chromium=chromium)
        stats = _assert_visual(name, png)
        _assert_no_tick_label_overlaps(name, chart, chromium)
        print(
            f"{name}: {stats.width}x{stats.height}, "
            f"non-white={stats.non_white}, colored={stats.colored}, "
            f"colors={stats.unique_colors}"
        )
    for asset in ASSET_CASES:
        page = CHART_ASSET_DIR / asset
        name = f"asset_{page.stem}"
        if not page.is_file():
            raise SystemExit(f"{name}: missing chart asset {page}")
        document = page.read_text(encoding="utf-8")
        png = _screenshot_page(chromium, page, width=ASSET_W, height=ASSET_H)
        stats = _assert_visual(name, png, expected=(ASSET_W, ASSET_H), asset=True)
        _assert_no_tick_label_overlaps_from_document(name, document, chromium)
        print(
            f"{name}: {stats.width}x{stats.height}, "
            f"non-white={stats.non_white}, colored={stats.colored}, "
            f"colors={stats.unique_colors}"
        )
    print(f"visual regression smoke OK: {len(CASES)} charts, {len(ASSET_CASES)} assets")


if __name__ == "__main__":
    main()
