#!/usr/bin/env python3
"""Visual-health smoke for the example gallery.

Runs the FastAPI example and, for each chart route plus the drilldown,
screenshots it in headless Chromium and asserts the render is not blank, flat,
or collapsed, and that axis tick labels do not overlap.

This is deliberately not an image-identity regression oracle. Reviewed visual
identity lives in ``scripts/visual_baseline.py``; this gate retains the broader
gallery health, occupancy, and tick-overlap coverage.

Usage: python scripts/visual_health_smoke.py [/path/to/chrome]
"""

from __future__ import annotations

import base64
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "fastapi"))

import charts  # noqa: E402  (examples/fastapi/charts.py)

from _app_smoke import ChromiumSession, Probe, find_chromium, serve_fastapi_app  # noqa: E402

GALLERY_IDS: tuple[str, ...] = tuple(info.id for info in charts.GALLERY)
DRILLDOWN_PATH = "/drilldown"

# A fixed viewport makes screenshot dimensions deterministic across runners.
# Charts declare height=430; the viewport gives it room plus a little margin.
VIEW_W, VIEW_H = 900, 470
PLOT_BOX = (0.09, 0.15, 0.94, 0.83)
SMOKE_POINTS = 200_000


@dataclass(frozen=True)
class PngStats:
    width: int
    height: int
    non_white: int
    colored: int
    unique_colors: int


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
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
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
        if i % (4 * 3) == 0:
            unique.add((r, g, b))
    return PngStats(width, height, non_white, colored, len(unique))


def _region_non_white(rgba: bytes, width: int, height: int, box) -> int:
    x0, y0, x1, y1 = box
    left, top = int(width * x0), int(height * y0)
    right, bottom = int(width * x1), int(height * y1)
    count = 0
    for y in range(top, bottom):
        row = y * width * 4
        for x in range(left, right):
            i = row + x * 4
            r, g, b, a = rgba[i : i + 4]
            if a > 8 and (r < 245 or g < 245 or b < 245):
                count += 1
    return count


def _active_plot_cells(rgba: bytes, width: int, height: int, box) -> int:
    """How many of a 4x3 grid over the plot region carry content (anti-collapse)."""
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
            if _region_non_white(rgba, width, height, cell) > 60:
                active += 1
    return active


def _assert_visual(name: str, data: bytes) -> PngStats:
    stats = _png_stats(data)
    if (stats.width, stats.height) != (VIEW_W, VIEW_H):
        raise SystemExit(f"{name}: unexpected PNG dims {stats.width}x{stats.height}")
    total = stats.width * stats.height
    if stats.non_white < max(600, int(total * 0.004)):
        raise SystemExit(f"{name}: screenshot is too blank ({stats.non_white} non-white px)")
    if stats.colored < max(180, int(total * 0.0008)):
        raise SystemExit(f"{name}: screenshot has too little colored data ({stats.colored} px)")
    if stats.unique_colors < 16:
        raise SystemExit(f"{name}: screenshot is visually flat ({stats.unique_colors} colors)")
    _, _, rgba = _png_rgba(data)
    if _region_non_white(rgba, stats.width, stats.height, PLOT_BOX) < 1000:
        raise SystemExit(f"{name}: plot region is nearly empty")
    active = _active_plot_cells(rgba, stats.width, stats.height, PLOT_BOX)
    if active < 4:
        raise SystemExit(f"{name}: chart collapsed in plot region ({active}/12 active cells)")
    return stats


# Overlap detection over rendered tick-label DOM nodes; runs in the page and
# returns its result by value (no view handle needed — the labels are DOM).
_OVERLAP_EXPR = r"""
(() => {
  const nodes = Array.from(document.querySelectorAll("[data-xy-label-kind='tick']"));
  const labels = nodes.map((el) => {
    const r = el.getBoundingClientRect();
    return { key: (el.dataset.xyAxis || "") + ":" + (el.dataset.xyAxisSide || ""),
             text: el.textContent || "",
             left: r.left, right: r.right, top: r.top, bottom: r.bottom,
             w: r.width, h: r.height };
  }).filter((r) => r.w > 0 && r.h > 0);
  const groups = new Map();
  for (const l of labels) { if (!groups.has(l.key)) groups.set(l.key, []); groups.get(l.key).push(l); }
  const slack = 1.5;
  const hit = (a, b) => a.left < b.right - slack && b.left < a.right - slack &&
                        a.top < b.bottom - slack && b.top < a.bottom - slack;
  const overlaps = [];
  for (const items of groups.values())
    for (let i = 0; i < items.length; i++)
      for (let j = i + 1; j < items.length; j++)
        if (hit(items[i], items[j])) overlaps.push([items[i].text, items[j].text]);
  return { label_count: labels.length, overlaps: overlaps.slice(0, 8) };
})()
"""


def _screenshot_route(session: ChromiumSession, url: str, name: str) -> tuple[bytes, dict]:
    probe = Probe(session, url, emulate=(VIEW_W, VIEW_H, 1.0))
    try:
        probe.wait_for(
            "!!document.querySelector('canvas') && !!document.querySelector(\"[data-xy-slot='canvas']\")",
            timeout_s=60.0,
            label=f"{name}: canvas mounted",
        )
        # settle a couple of animation frames so the first paint has landed
        probe.eval("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        shot = probe._call(
            "Page.captureScreenshot",
            {
                "format": "png",
                "clip": {"x": 0, "y": 0, "width": VIEW_W, "height": VIEW_H, "scale": 1},
            },
        )
        png = base64.b64decode(shot["data"])
        overlaps = probe.eval(_OVERLAP_EXPR)
        return png, overlaps
    finally:
        probe.close()


def main() -> int:
    chromium = find_chromium(sys.argv[1] if len(sys.argv) > 1 else None)
    with (
        serve_fastapi_app(points=SMOKE_POINTS) as base_url,
        ChromiumSession(chromium, gl="software", sandbox=False) as session,
    ):
        for chart_id in GALLERY_IDS:
            png, overlaps = _screenshot_route(session, f"{base_url}/chart/{chart_id}", chart_id)
            stats = _assert_visual(chart_id, png)
            if overlaps.get("overlaps"):
                raise SystemExit(f"{chart_id}: tick label overlaps {overlaps['overlaps']}")
            print(
                f"  {chart_id}: {stats.width}x{stats.height} "
                f"non-white={stats.non_white} colored={stats.colored} "
                f"colors={stats.unique_colors} ticks={overlaps.get('label_count')}"
            )
        png, _ = _screenshot_route(session, f"{base_url}{DRILLDOWN_PATH}", "drilldown")
        _assert_visual("drilldown", png)
        print("  drilldown: rendered")
    print(f"visual health smoke OK: {len(GALLERY_IDS)} charts + drilldown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
