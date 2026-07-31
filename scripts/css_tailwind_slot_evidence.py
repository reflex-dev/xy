"""Generate matched browser evidence for the granular CSS/Tailwind slot audit."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import xy
from xy import export

SLOT_CLASSES = {
    "annotation_layer": "tw-annotation-layer",
    "colorbar_extension": "tw-colorbar-extension",
    "colorbar_line": "tw-colorbar-line",
    "colorbar_minor_tick": "tw-colorbar-minor-tick",
    "modebar_drag_handle": "tw-modebar-drag-handle",
    "modebar_control_group": "tw-modebar-control-group",
    "modebar_separator": "tw-modebar-separator",
    "modebar_icon": "tw-modebar-icon",
    "modebar_zoom_value": "tw-modebar-zoom-value",
    "modebar_indicator": "tw-modebar-indicator",
    "modebar_selection_icon": "tw-modebar-selection-icon",
    "modebar_menu": "tw-modebar-menu",
    "modebar_menu_separator": "tw-modebar-menu-separator",
    "modebar_menu_icon": "tw-modebar-menu-icon",
    "modebar_menu_label": "tw-modebar-menu-label",
    "modebar_history_controls": "tw-modebar-history-controls",
    "axis_band": "tw-axis-band",
    "axis_line": "tw-axis-line",
    "tick_mark": "tw-tick-mark",
}

UTILITY_CSS = """
@layer base, components, utilities;
@layer utilities {
  .tw-annotation-layer { opacity: .72; filter: saturate(1.35); }
  .tw-colorbar-extension { fill: #f97316; stroke: #fed7aa; stroke-width: 2px; }
  .tw-colorbar-line { border-color: #22d3ee; }
  .tw-colorbar-minor-tick { border-color: #a78bfa; }
  .tw-modebar-drag-handle {
    background: #db2777;
    color: #fff;
    border: 2px solid #f9a8d4;
    border-radius: 9999px;
    box-shadow: 0 0 0 4px rgb(219 39 119 / 22%);
  }
  .tw-modebar-control-group {
    gap: 5px;
    padding: 2px;
    border: 1px solid rgb(56 189 248 / 35%);
    border-radius: 8px;
  }
  .tw-modebar-separator { width: 2px; background: #38bdf8; }
  .tw-modebar-icon { color: #facc15; }
  .tw-modebar-zoom-value { color: #f8fafc; font-weight: 800; }
  .tw-modebar-indicator { color: #38bdf8; }
  .tw-modebar-selection-icon { color: #f472b6; }
  .tw-modebar-menu {
    width: 176px;
    background: #172554;
    color: #e0f2fe;
    border: 2px solid #38bdf8;
    border-radius: 14px;
    padding: 7px;
    box-shadow: 0 16px 40px rgb(8 47 73 / 45%);
  }
  .tw-modebar-menu-separator { background: #38bdf8; margin-block: 6px; }
  .tw-modebar-menu-icon { color: #f472b6; }
  .tw-modebar-menu-label { color: #e0f2fe; font-weight: 700; letter-spacing: .01em; }
  .tw-modebar-history-controls {
    padding: 3px;
    border-radius: 8px;
    background: rgb(14 116 144 / 30%);
  }
  .tw-axis-band { cursor: crosshair; }
  .tw-axis-line { background: #fb7185; }
  .tw-tick-mark { background: #4ade80; }
}
html, body {
  margin: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background:
    radial-gradient(circle at 15% 15%, rgb(30 64 175 / 24%), transparent 34%),
    #07111f;
}
body { display: grid; place-items: center; }
.evidence {
  border: 1px solid rgb(148 163 184 / 24%);
  border-radius: 22px;
  box-shadow: 0 28px 70px rgb(0 0 0 / 45%);
}
"""


def audit_chart(label: str) -> xy.Chart:
    """One chart containing every visible surface needed by the comparison."""
    x = list(range(9))
    y = [2.0, 3.4, 2.8, 5.1, 4.7, 6.3, 5.8, 7.4, 8.2]
    confidence = [0.08, 0.18, 0.31, 0.44, 0.57, 0.68, 0.76, 0.9, 1.0]
    return xy.chart(
        xy.line(
            x,
            y,
            name="Signal",
            style={"stroke": "#60a5fa", "stroke-width": 2.5},
        ),
        xy.scatter(
            x,
            y,
            name="Confidence",
            color=confidence,
            colormap="plasma",
            size=9,
            style={"stroke": "#f8fafc", "stroke-width": 1.2},
        ),
        xy.colorbar(title="Confidence", ticks=[0.08, 0.5, 1.0]),
        xy.legend(title="Series", loc="upper right"),
        xy.x_axis(
            label="Release",
            style={
                "axis_color": "#64748b",
                "tick_color": "#64748b",
                "tick_length": 7,
                "tick_width": 1.5,
            },
        ),
        xy.y_axis(
            label="Score",
            style={
                "axis_color": "#64748b",
                "tick_color": "#64748b",
                "tick_length": 7,
                "tick_width": 1.5,
            },
        ),
        xy.vline(5, text="ship", color="#fb7185", width=3),
        xy.callout(
            7,
            7.4,
            "target",
            dx=-50,
            dy=-34,
            color="#facc15",
            style={
                "background": "#172554",
                "border": "1px solid #60a5fa",
                "border_radius": 6,
                "padding": "3px 7px",
                "label_color": "#f8fafc",
            },
        ),
        title=f"CSS & Tailwind surface audit — {label}",
        # The fixture owns a dark chart surface, so opt into XY's documented
        # scheme-aware modebar palette instead of leaving the light fallback.
        class_name="evidence dark",
        class_names=SLOT_CLASSES,
        width=900,
        height=560,
        padding=(64, 118, 68, 82),
        style={
            "background": "#0b1728",
            "color": "#dbeafe",
            "--chart-bg": "#0b1728",
            "--chart-grid": "#233653",
            "--chart-axis": "#64748b",
            "--chart-text": "#dbeafe",
        },
        styles={
            "title": {"font_size": 19, "font_weight": 750},
            "legend": {
                "background": "#101e33e8",
                "border": "1px solid #334155",
                "border_radius": 9,
            },
        },
    )


def _replace_bundle(document: str, bundle: Path | None) -> str:
    if bundle is None:
        return document
    current = export._javascript_for_inline_script(export._bundled_js("standalone"))
    replacement = export._javascript_for_inline_script(bundle.read_text(encoding="utf-8"))
    if current not in document:
        raise RuntimeError("could not locate the current standalone bundle in evidence HTML")
    return document.replace(current, replacement, 1)


def _instrument(document: str) -> str:
    render_call = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    if render_call not in document:
        raise RuntimeError("standalone render call changed; update the evidence script")
    instrumented = """
spec.colorbar = {
  ...spec.colorbar,
  line_only: true,
  extend: "both",
  minor_ticks: true,
  lines: [{value: 0.5, color: "#94a3b8", width: 2, dash: "dashed"}],
};
const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
view._drawNow();
view._raf = null;
const bar = view.root.querySelector('[data-xy-slot="modebar"]');
bar.style.opacity = "1";
bar.style.pointerEvents = "auto";
bar.classList.add("xy-dragging");
const zoomTrigger = bar.querySelector("[data-xy-modebar-menu-trigger]");
if (zoomTrigger) zoomTrigger.click();
"""
    return document.replace(render_call, instrumented, 1)


def _screenshot(html_path: Path, png_path: Path) -> None:
    chromium = export.find_chromium()
    if chromium is None:
        raise RuntimeError("Chromium is required to capture CSS/Tailwind audit evidence")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            chromium,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--allow-file-access-from-files",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--hide-scrollbars",
            "--window-size=940,600",
            "--virtual-time-budget=3000",
            f"--screenshot={png_path.resolve()}",
            html_path.resolve().as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Chromium exited {result.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label", choices=("before", "after"))
    parser.add_argument("html", type=Path)
    parser.add_argument("png", type=Path)
    parser.add_argument(
        "--bundle",
        type=Path,
        help="Optional standalone bundle to substitute (used for the before capture).",
    )
    args = parser.parse_args()

    args.html.parent.mkdir(parents=True, exist_ok=True)
    document = audit_chart(args.label).to_html(custom_css=UTILITY_CSS)
    document = _replace_bundle(document, args.bundle)
    document = _instrument(document)
    export._atomic_write_text(args.html, document)
    _screenshot(args.html, args.png)


if __name__ == "__main__":
    main()
