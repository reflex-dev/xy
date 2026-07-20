"""Browser regressions for responsive legend and tooltip chrome.

The automatic legend bounds are low-priority, zero-specificity stylesheet defaults so an
explicit component style survives resize. Narrow-chart probes additionally
exercise long legend rows, edge tooltips, and the compact-layout origin; these
failures only manifest after the browser computes real geometry.

Skips (never fails) when no Chromium is available or the headless GL context
can't come up, matching the repo's other browser probes.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from conftest import run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy.export import find_chromium  # noqa: E402

# Capture the standalone render call's return value so the probe can drive the
# view directly (the same swap the visual-regression smoke uses).
_RENDER_CALLS = (
    'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
    'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
)

# Async probe: wait for the legend, record its computed max-height, force a
# responsive height change (so _resize runs its legend-cap branch), then record
# the max-height again. Result lands on a body attribute for `--dump-dom`.
_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    // Bare rAF may not tick under --virtual-time-budget --dump-dom. Drain the
    // initial scheduled draw synchronously so DOM chrome exists deterministically.
    view._drawNow();
    view._raf = null;
    let legend = null;
    for (let i = 0; i < 200; i++) {
      legend = document.querySelector('[data-xy-slot="legend"]');
      if (legend) break;
      await sleep(25);
    }
    if (!legend) throw new Error("legend never rendered");
    const initial = getComputedStyle(legend).maxHeight;
    // Force a responsive height change so _resize takes the legend-cap branch.
    view.fluid = true;
    view.fluidH = true;
    view._resize(view.size.w, view.size.h + 260);
    view._drawNow();
    view._raf = null;
    legend = document.querySelector('[data-xy-slot="legend"]') || legend;
    const afterResize = getComputedStyle(legend).maxHeight;
    document.body.setAttribute(
      "data-xy-legend-maxheight",
      JSON.stringify({ initial, afterResize })
    );
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-maxheight-error",
      String((err && err.stack) || err)
    );
  }
})();
</script>
"""

_OVERFLOW_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const utilityStyle = document.createElement("style");
    utilityStyle.textContent = `
      @layer base, utilities;
      @layer utilities {
        .xy-probe-tooltip {
          background: rgb(1 2 3);
          color: rgb(250 251 252);
          padding: 9px 11px;
          border-radius: 13px;
        }
      }
    `;
    document.head.appendChild(utilityStyle);
    const host = view.root.parentElement;
    host.style.width = "320px";
    host.style.height = "360px";
    view.root.style.width = "320px";
    view.root.style.height = "360px";
    view.fluid = true;
    view.fluidH = true;
    view._resize(320, 360);
    view._drawNow();
    view._raf = null;

    // A docs page can exceed the WebGL context budget. Exercise the same trace
    // builder used during recovery and verify it retains the non-positional
    // CPU channel views that rich tooltips need after the rebuild.
    const sourceScatter = view.gpuTraces.find((g) => g.trace.id === 8);
    const rebuiltScatter = {
      trace: sourceScatter.trace,
      xAxis: sourceScatter.xAxis,
      yAxis: sourceScatter.yAxis,
    };
    view._buildScatterMark(rebuiltScatter, sourceScatter.trace, view._payload);
    const colorCpuRetained = !!rebuiltScatter._cpu?.color;
    const sizeCpuRetained = !!rebuiltScatter._cpu?.size;

    const legend = document.querySelector('[data-xy-slot="legend"]');
    if (!legend) throw new Error("legend never rendered");
    view.canvas.focus();
    view.canvas.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true }));
    for (let i = 0; i < 100 && view.tooltip.style.display !== "block"; i++) {
      await sleep(20);
    }
    const tooltip = document.querySelector('[data-xy-slot="tooltip"]');
    if (!tooltip || tooltip.style.display !== "block") {
      throw new Error("keyboard tooltip never rendered");
    }

    const rootRect = view.root.getBoundingClientRect();
    const legendRect = legend.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const tooltipStyle = getComputedStyle(tooltip);
    const inside = (rect) =>
      rect.left >= rootRect.left - 1 && rect.right <= rootRect.right + 1 &&
      rect.top >= rootRect.top - 1 && rect.bottom <= rootRect.bottom + 1;
    document.body.setAttribute("data-xy-chrome-overflow", JSON.stringify({
      rootWidth: rootRect.width,
      legendWithinRoot: inside(legendRect),
      legendCenterError: Math.abs(
        (legendRect.left + legendRect.right) / 2 -
        (rootRect.left + view.plot.x + view.plot.w / 2)
      ),
      legendHasOverflow: legend.scrollWidth > legend.clientWidth || legend.scrollHeight > legend.clientHeight,
      legendMaxWidth: getComputedStyle(legend).maxWidth,
      canvasLeftError: Math.abs(
        view.canvas.getBoundingClientRect().left - (rootRect.left + view.plot.x)
      ),
      canvasTopError: Math.abs(
        view.canvas.getBoundingClientRect().top - (rootRect.top + view.plot.y)
      ),
      colorCpuRetained,
      sizeCpuRetained,
      tooltipWithinRoot: inside(tooltipRect),
      tooltipWidth: tooltipRect.width,
      tooltipText: tooltip.textContent,
      tooltipBackground: tooltipStyle.backgroundColor,
      tooltipColor: tooltipStyle.color,
      tooltipPadding: tooltipStyle.padding,
      tooltipRadius: tooltipStyle.borderRadius,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-chrome-overflow-error",
      String((err && err.stack) || err)
    );
  }
})();
</script>
"""

_AXIS_CATEGORY_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const hasBothAxes = (nodes) =>
      nodes.some((node) => node.dataset.xyAxis === "x") &&
      nodes.some((node) => node.dataset.xyAxis === "x2");
    let ticks = [];
    for (let i = 0; i < 200; i++) {
      ticks = [...document.querySelectorAll('[data-xy-label-kind="tick"]')];
      if (hasBothAxes(ticks)) break;
      await sleep(25);
    }
    ticks = [...document.querySelectorAll('[data-xy-label-kind="tick"]')];
    if (!hasBothAxes(ticks)) throw new Error("axis ticks never rendered");
    const read = (axisId) => {
      const axis = view.axes[axisId];
      if (!axis) throw new Error(`missing ${axisId} axis`);
      return {
        kind: axis.kind,
        categories: Array.from(axis.categories || []),
        labels: ticks
          .filter((node) => node.dataset.xyAxis === axisId)
          .map((node) => node.textContent),
      };
    };
    document.body.setAttribute(
      "data-xy-axis-categories",
      JSON.stringify({ x: read("x"), x2: read("x2") })
    );
  } catch (err) {
    document.body.setAttribute(
      "data-xy-axis-categories-error",
      String((err && err.stack) || err)
    );
  }
})();
</script>
"""

_ANNOTATION_ALIGNMENT_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    let labels = [];
    for (let i = 0; i < 200; i++) {
      labels = [...document.querySelectorAll('[data-xy-slot="annotation_label"]')];
      if (labels.length >= 2) break;
      await sleep(25);
    }
    labels = [...document.querySelectorAll('[data-xy-slot="annotation_label"]')];
    const findLabel = (text) => labels.find((label) => label.textContent === text);
    const band = findLabel("band-center");
    const arrow = findLabel("arrow-center");
    if (!band || !arrow) throw new Error("annotation labels never rendered");
    const root = view.root.getBoundingClientRect();
    const center = (element) => {
      const rect = element.getBoundingClientRect();
      return [(rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2];
    };
    const [bandCenterX] = center(band);
    const bandExpected = root.left + (view._dataPxX(2) + view._dataPxX(4)) / 2;
    // The arrow label is centered on the shaft midpoint, then lifted along
    // the shaft's upward normal until the box clears the line (plus a small
    // margin). Measure its offset from the midpoint in the shaft's own
    // frame: the tangential component must stay ~0 (still centered along
    // the shaft) and the normal component must be at least the box's
    // projection onto the normal (clear of the line, on the upper side).
    const ax0 = view._dataPxX(0);
    const ay0 = view._dataPxY(0);
    const ax1 = view._dataPxX(2);
    const ay1 = view._dataPxY(2);
    const shaftLen = Math.hypot(ax1 - ax0, ay1 - ay0);
    const tangent = [(ax1 - ax0) / shaftLen, (ay1 - ay0) / shaftLen];
    let normal = [-tangent[1], tangent[0]];
    if (normal[1] > 0) normal = [-normal[0], -normal[1]];
    const arrowRect = arrow.getBoundingClientRect();
    const offX = (arrowRect.left + arrowRect.right) / 2 - root.left - (ax0 + ax1) / 2;
    const offY = (arrowRect.top + arrowRect.bottom) / 2 - root.top - (ay0 + ay1) / 2;
    document.body.setAttribute(
      "data-xy-annotation-alignment",
      JSON.stringify({
        bandCenterError: Math.abs(bandCenterX - bandExpected),
        arrowTangentialError: Math.abs(offX * tangent[0] + offY * tangent[1]),
        arrowNormalOffset: offX * normal[0] + offY * normal[1],
        arrowRequiredClearance:
          (arrowRect.width / 2) * Math.abs(normal[0]) +
          (arrowRect.height / 2) * Math.abs(normal[1]),
        bandTransform: band.style.transform,
        arrowTransform: arrow.style.transform,
      })
    );
  } catch (err) {
    document.body.setAttribute(
      "data-xy-annotation-alignment-error",
      String((err && err.stack) || err)
    );
  }
})();
</script>
"""


def _probe_maxheight(chromium: str, document: str, page: Path) -> dict:
    """Render + probe the legend max-height across a responsive resize."""
    return run_browser_probe(
        chromium, document, page, "data-xy-legend-maxheight", label="legend resize probe"
    )


def _probe_overflow(chromium: str, document: str, page: Path) -> dict:
    """Render the narrow chrome stress case and read its DOM bounds."""
    return run_browser_probe(
        chromium, document, page, "data-xy-chrome-overflow", label="chrome overflow probe"
    )


def _probe_axis_categories(chromium: str, document: str, page: Path) -> dict:
    """Render mixed primary/named scales and read their normalized state + labels."""
    return run_browser_probe(
        chromium, document, page, "data-xy-axis-categories", label="axis category probe"
    )


def _probe_annotation_alignment(chromium: str, document: str, page: Path) -> dict:
    """Render annotation labels and compare their DOM centers with geometry."""
    return run_browser_probe(
        chromium,
        document,
        page,
        "data-xy-annotation-alignment",
        label="annotation alignment probe",
    )


def test_snake_case_legend_max_height_survives_resize() -> None:
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the resize regression probe")

    fig = xy.chart(
        xy.line(x=[0, 1, 2, 3], y=[0, 1, 0, 1], name="alpha"),
        xy.line(x=[0, 1, 2, 3], y=[1, 0, 1, 0], name="beta"),
        xy.legend(),
        # snake_case is the documented Python API form; it must reach the client
        # AND be honored by the responsive-cap guard on resize.
        styles={"legend": {"max_height": 50}},
        width=480,
        height=320,
    )

    document = fig.to_html()
    render_call = next((call for call in _RENDER_CALLS if call in document), None)
    assert render_call is not None, "to_html render call shape changed; update the probe swap"
    capture_call = render_call.replace(
        "xy.renderStandalone(", "window.__fcProbeView = xy.renderStandalone(", 1
    )
    document = document.replace(render_call, capture_call, 1)
    document = document.replace("</body>", _PROBE + "\n</body>", 1)

    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "legend_resize.html"
        payload = _probe_maxheight(chromium, document, page)

    # Before the fix, the auto-cap overwrote the explicit 50px with the (grown)
    # plot height on resize. It must stay pinned at the author's value.
    assert payload["initial"] == "50px", f"explicit max_height not applied at build: {payload}"
    assert payload["afterResize"] == "50px", (
        f"resize clobbered the explicit snake_case max_height: {payload}"
    )


def test_long_legend_and_edge_tooltip_stay_inside_narrow_chart() -> None:
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the chrome overflow probe")

    colors = (
        "#2563eb",
        "#7c3aed",
        "#db2777",
        "#ea580c",
        "#0f766e",
        "#0891b2",
        "#4f46e5",
        "#be123c",
    )
    children = [
        xy.line(
            [0, 1, 2],
            [2 + index * 0.35, 4 + index * 0.2, 1.5 + index * 0.25],
            name=f"Service {index + 1}: reconciliation and settlement pipeline",
            color=color,
        )
        for index, color in enumerate(colors)
    ]
    data = {
        "sample": [0, 1, 2],
        "latency_ms": [8.0, 5.0, 1.0],
        "service_tier": [
            "edge",
            "core",
            "critical-payments-reconciliation-with-extra-long-label",
        ],
        "requests_per_minute": [1_200, 4_800, 12_400],
    }
    children.append(
        xy.scatter(
            x="sample",
            y="latency_ms",
            color="service_tier",
            size="requests_per_minute",
            data=data,
            name="Interactive incident samples with resident tooltip fields",
        )
    )
    chart = xy.chart(
        *children,
        xy.legend(loc="upper center", ncols=2, title="Long operational series"),
        xy.tooltip(
            fields=["sample", "latency_ms", "service_tier", "requests_per_minute"],
            title="{service_tier}",
            format={"latency_ms": ".1f", "requests_per_minute": ",.0f"},
        ),
        xy.interaction_config(
            hover=True,
            click=True,
            crosshair=True,
            select=True,
            brush=True,
            view_change=True,
        ),
        class_names={"tooltip": "xy-probe-tooltip"},
        width="100%",
        height=360,
    )

    document = chart.to_html()
    render_call = next((call for call in _RENDER_CALLS if call in document), None)
    assert render_call is not None
    document = document.replace(
        render_call,
        render_call.replace(
            "xy.renderStandalone(", "window.__fcProbeView = xy.renderStandalone(", 1
        ),
        1,
    )
    document = document.replace("</body>", _OVERFLOW_PROBE + "\n</body>", 1)

    with tempfile.TemporaryDirectory() as td:
        payload = _probe_overflow(chromium, document, Path(td) / "chrome_overflow.html")

    assert payload["rootWidth"] == pytest.approx(320, abs=1), payload
    assert payload["legendWithinRoot"] is True, payload
    assert payload["legendCenterError"] <= 1, payload
    assert payload["legendHasOverflow"] is True, payload
    assert payload["legendMaxWidth"].endswith("px"), payload
    assert payload["canvasLeftError"] <= 1, payload
    assert payload["canvasTopError"] <= 1, payload
    assert payload["colorCpuRetained"] is True, payload
    assert payload["sizeCpuRetained"] is True, payload
    assert payload["tooltipWithinRoot"] is True, payload
    assert payload["tooltipWidth"] <= 312, payload
    assert "critical-payments-reconciliation" in payload["tooltipText"], payload
    assert payload["tooltipBackground"] == "rgb(1, 2, 3)", payload
    assert payload["tooltipColor"] == "rgb(250, 251, 252)", payload
    assert payload["tooltipPadding"] == "9px 11px", payload
    assert payload["tooltipRadius"] == "13px", payload


def test_midpoint_annotation_labels_are_visually_centered() -> None:
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the annotation alignment probe")

    chart = xy.chart(
        xy.line([0, 1, 2, 3, 4], [0, 1, 2, 3, 4]),
        xy.x_band(2, 4, text="band-center"),
        xy.arrow(0, 0, 2, 2, text="arrow-center"),
        xy.x_axis(domain=(-0.5, 4.5)),
        xy.y_axis(domain=(-0.5, 4.5)),
        width=520,
        height=320,
    )

    document = chart.to_html()
    render_call = next((call for call in _RENDER_CALLS if call in document), None)
    assert render_call is not None
    document = document.replace(
        render_call,
        render_call.replace(
            "xy.renderStandalone(", "window.__fcProbeView = xy.renderStandalone(", 1
        ),
        1,
    )
    document = document.replace("</body>", _ANNOTATION_ALIGNMENT_PROBE + "\n</body>", 1)

    with tempfile.TemporaryDirectory() as td:
        payload = _probe_annotation_alignment(
            chromium,
            document,
            Path(td) / "annotation_alignment.html",
        )

    assert payload["bandCenterError"] <= 1, payload
    # Centered along the shaft, offset only along its upward normal — far
    # enough that the box clears the line instead of being struck through.
    assert payload["arrowTangentialError"] <= 1, payload
    assert payload["arrowNormalOffset"] >= payload["arrowRequiredClearance"], payload
    assert "-50%" in payload["bandTransform"], payload
    assert "-50%" in payload["arrowTransform"], payload


@pytest.mark.parametrize(
    "primary_is_category",
    [True, False],
    ids=["primary-category-named-linear", "primary-linear-named-category"],
)
def test_browser_named_axis_category_state_and_tick_chrome_are_independent(
    primary_is_category: bool,
) -> None:
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the named-axis category probe")

    if primary_is_category:
        chart = xy.chart(
            xy.line(["Alpha", "Beta", "Gamma"], [1.0, 2.0, 3.0]),
            xy.line([100.0, 200.0, 300.0], [3.0, 2.0, 1.0], x_axis="x2"),
            xy.x_axis(tick_label_strategy="rotate"),
            xy.x_axis(
                id="x2",
                side="top",
                type_="linear",
                tick_values=(100.0, 200.0, 300.0),
                tick_labels=("N100", "N200", "N300"),
                tick_label_strategy="rotate",
            ),
            width=560,
            height=300,
        )
        expected = {
            "x": {
                "kind": "category",
                "categories": ["Alpha", "Beta", "Gamma"],
                "labels": ["Alpha", "Beta", "Gamma"],
            },
            "x2": {"kind": "linear", "categories": [], "labels": ["N100", "N200", "N300"]},
        }
    else:
        chart = xy.chart(
            xy.line([10.0, 20.0, 30.0], [1.0, 2.0, 3.0]),
            xy.line(["Red", "Green", "Blue"], [3.0, 2.0, 1.0], x_axis="x2"),
            xy.x_axis(
                type_="linear",
                tick_values=(10.0, 20.0, 30.0),
                tick_labels=("P10", "P20", "P30"),
                tick_label_strategy="rotate",
            ),
            xy.x_axis(id="x2", side="top", tick_label_strategy="rotate"),
            width=560,
            height=300,
        )
        expected = {
            "x": {"kind": "linear", "categories": [], "labels": ["P10", "P20", "P30"]},
            "x2": {
                "kind": "category",
                "categories": ["Red", "Green", "Blue"],
                "labels": ["Red", "Green", "Blue"],
            },
        }

    document = chart.to_html()
    render_call = next((call for call in _RENDER_CALLS if call in document), None)
    assert render_call is not None
    document = document.replace(
        render_call,
        render_call.replace(
            "xy.renderStandalone(", "window.__fcProbeView = xy.renderStandalone(", 1
        ),
        1,
    )
    document = document.replace("</body>", _AXIS_CATEGORY_PROBE + "\n</body>", 1)

    with tempfile.TemporaryDirectory() as td:
        payload = _probe_axis_categories(chromium, document, Path(td) / "axis_categories.html")

    assert payload == expected
