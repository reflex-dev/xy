"""Browser regressions for reported responsive chart chrome issues."""

from __future__ import annotations

from pathlib import Path

import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium


def _probe(chart: xy.Chart, script: str, tmp_path: Path, name: str) -> dict:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    document = chart.to_html()
    render_call = document.rfind("xy.renderStandalone(")
    assert render_call >= 0
    document = document[:render_call] + "window.__xyIssueView = " + document[render_call:]
    document = document.replace("</body>", f"<script>{script}</script>\n</body>", 1)
    return run_browser_probe(
        chromium,
        document,
        tmp_path / f"{name}.html",
        "data-xy-issue-probe",
        label=name,
    )


_PRELUDE = """
(async () => {
  try {
    const view = window.__xyIssueView;
    if (!view) throw new Error("chart view was not captured");
    view._drawNow();
    view._raf = null;
"""

_POSTLUDE = """
  } catch (error) {
    document.body.setAttribute(
      "data-xy-issue-probe-error", String((error && error.stack) || error)
    );
  }
})();
"""


def test_density_badges_follow_dark_theme(tmp_path: Path) -> None:
    chart = xy.line_chart(xy.line([0, 1], [0, 1]), width=320, height=220)
    script = (
        _PRELUDE
        + """
    view.root.classList.add("dark");
    const badge = document.createElement("div");
    view._applySlot(badge, "badge_item");
    badge.textContent = "sampled 10 of 100";
    view.root.appendChild(badge);
    const style = getComputedStyle(badge);
    document.body.setAttribute("data-xy-issue-probe", JSON.stringify({
      color: style.color,
      background: style.backgroundColor,
    }));
"""
        + _POSTLUDE
    )
    result = _probe(chart, script, tmp_path, "dark density badge")

    assert result["color"] == "rgb(248, 250, 252)", result
    assert result["background"] == "rgba(30, 35, 44, 0.88)", result


def test_modebar_active_button_uses_dark_active_color(tmp_path: Path) -> None:
    chart = xy.line_chart(xy.line([0, 1], [0, 1]), width=500, height=320)
    script = (
        _PRELUDE
        + """
    view.root.classList.add("dark");
    const bar = view.root.querySelector('[data-xy-slot="modebar"]');
    const active = view.root.querySelector(
      'button[data-xy-slot="modebar_button"].xy-active'
    );
    const darkActiveBackground = getComputedStyle(active).backgroundColor;
    const darkBarBackground = getComputedStyle(bar).backgroundColor;
    active.focus();
    const darkFocusShadow = getComputedStyle(active).boxShadow;
    view.root.style.setProperty("--chart-modebar-active", "#ff00ff");
    view.root.style.setProperty("--chart-modebar-focus", "#00ff00");
    const customActiveBackground = getComputedStyle(active).backgroundColor;
    const customFocusShadow = getComputedStyle(active).boxShadow;
    document.body.setAttribute("data-xy-issue-probe", JSON.stringify({
      darkActiveBackground,
      darkBarBackground,
      darkFocusShadow,
      customActiveBackground,
      customFocusShadow,
    }));
"""
        + _POSTLUDE
    )
    result = _probe(chart, script, tmp_path, "dark active modebar button")

    assert result["darkActiveBackground"] == "rgb(18, 20, 23)", result
    assert result["darkBarBackground"] == "rgb(27, 29, 32)", result
    assert "rgb(226, 229, 233)" in result["darkFocusShadow"], result
    assert result["customActiveBackground"] == "rgb(255, 0, 255)", result
    assert "rgb(0, 255, 0)" in result["customFocusShadow"], result


def test_narrow_annotation_labels_stay_inside_and_do_not_collide(tmp_path: Path) -> None:
    chart = xy.line_chart(
        xy.line([0, 25, 50, 75, 100], [0.1, 0.3, 0.55, 0.8, 1.0]),
        xy.vline(76, text="Release freeze"),
        xy.vline(94, text="Customer migration"),
        xy.callout(98, 0.93, "Primary endpoint", dx=42, dy=-32),
        xy.x_axis(domain=(0, 100)),
        xy.y_axis(domain=(0, 1)),
        width=260,
        height=320,
        padding=(50, 18, 48, 44),
    )
    script = (
        _PRELUDE
        + """
    const labels = [...view.root.querySelectorAll('[data-xy-slot="annotation_label"]')];
    const root = view.root.getBoundingClientRect();
    const rects = labels.map((label) => {
      const rect = label.getBoundingClientRect();
      return { text: label.textContent, left: rect.left, right: rect.right,
               top: rect.top, bottom: rect.bottom };
    });
    const inside = rects.every((rect) =>
      rect.left >= root.left - 1 && rect.right <= root.right + 1 &&
      rect.top >= root.top - 1 && rect.bottom <= root.bottom + 1
    );
    const overlaps = [];
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i], b = rects[j];
        if (a.left < b.right - 1 && a.right > b.left + 1 &&
            a.top < b.bottom - 1 && a.bottom > b.top + 1) {
          overlaps.push([a.text, b.text]);
        }
      }
    }
    const firstPositions = rects.map((rect) => [rect.left, rect.top]);
    const realGetBoundingClientRect = Element.prototype.getBoundingClientRect;
    let annotationLayoutReads = 0;
    Element.prototype.getBoundingClientRect = function () {
      if (this.dataset && this.dataset.xySlot === "annotation_label") {
        annotationLayoutReads += 1;
      }
      return realGetBoundingClientRect.call(this);
    };
    view._drawNow();
    view._raf = null;
    Element.prototype.getBoundingClientRect = realGetBoundingClientRect;
    const secondPositions = [...view.root.querySelectorAll('[data-xy-slot="annotation_label"]')]
      .map((label) => {
        const rect = label.getBoundingClientRect();
        return [rect.left, rect.top];
      });
    const callout = [...view.root.querySelectorAll('[data-xy-slot="annotation_label"]')]
      .find((label) => label.textContent === "Primary endpoint");
    const calloutSpec = view.spec.annotations.findIndex((ann) => ann.kind === "callout");
    const resolved = view._resolvedAnnotationAnchors.get(calloutSpec);
    const calloutLeft = parseFloat(callout.style.left);
    const calloutTop = parseFloat(callout.style.top);

    // Advance a view-animation frame inside the 80 ms DOM-label throttle
    // window. The visible label stays at its previous absolute position, so
    // the canvas pointer must begin at that same cached anchor rather than at
    // the new data position plus a stale relative offset.
    const realDataPxX = view._dataPxX.bind(view);
    const realDataPxY = view._dataPxY.bind(view);
    const realDrawArrowLine = view._drawArrowLine.bind(view);
    let animatedPointer = null;
    view._dataPxX = (value) => realDataPxX(value) + 14;
    view._dataPxY = (value) => realDataPxY(value) - 9;
    view._drawArrowLine = (_ctx, x0, y0, x1, y1) => {
      animatedPointer = { x0, y0, x1, y1 };
    };
    view._viewAnim = {};
    view._lastLabelDraw = view._now();
    view._drawChrome();
    view._dataPxX = realDataPxX;
    view._dataPxY = realDataPxY;
    view._drawArrowLine = realDrawArrowLine;
    view._viewAnim = null;
    document.body.setAttribute("data-xy-issue-probe", JSON.stringify({
      labels: rects.map((rect) => rect.text), inside, overlaps,
      stable: JSON.stringify(firstPositions) === JSON.stringify(secondPositions),
      pointerAttached:
        Math.abs(resolved.x - calloutLeft) < 0.01 &&
        Math.abs(resolved.y - calloutTop) < 0.01,
      animatedPointerAttached:
        animatedPointer !== null &&
        Math.abs(animatedPointer.x0 - calloutLeft) < 0.01 &&
        Math.abs(animatedPointer.y0 - calloutTop) < 0.01,
      annotationLayoutReads,
    }));
"""
        + _POSTLUDE
    )
    result = _probe(chart, script, tmp_path, "narrow annotation labels")

    assert result["labels"] == ["Release freeze", "Customer migration", "Primary endpoint"]
    assert result["inside"] is True, result
    assert result["overlaps"] == [], result
    assert result["stable"] is True, result
    assert result["pointerAttached"] is True, result
    assert result["animatedPointerAttached"] is True, result
    assert result["annotationLayoutReads"] <= len(result["labels"]) * 2, result


def test_narrow_categorical_tick_labels_are_ellipsized_inside_chart(tmp_path: Path) -> None:
    categories = [
        "Enterprise customer with an exceptionally long account name",
        "Another customer category whose identity must remain available",
        "Short category",
    ]
    chart = xy.scatter_chart(
        xy.scatter([1, 2, 3], categories),
        xy.x_axis(),
        xy.y_axis(reverse=True),
        width=260,
        height=360,
        padding=(56, 24, 56, 228),
    )
    script = (
        _PRELUDE
        + """
    const labels = [...view.root.querySelectorAll(
      '[data-xy-label-kind="tick"][data-xy-axis="y"]'
    )];
    const root = view.root.getBoundingClientRect();
    const rects = labels.map((label) => label.getBoundingClientRect());
    document.body.setAttribute("data-xy-issue-probe", JSON.stringify({
      count: labels.length,
      inside: rects.every((rect) => rect.left >= root.left - 1 && rect.right <= root.right + 1),
      titles: labels.map((label) => label.getAttribute("title")),
      overflow: labels.map((label) => getComputedStyle(label).textOverflow),
      plotWidth: view.plot.w,
      documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));
"""
        + _POSTLUDE
    )
    result = _probe(chart, script, tmp_path, "narrow categorical tick labels")

    assert result["count"] == len(categories), result
    assert result["inside"] is True, result
    assert result["titles"] == categories, result
    assert result["overflow"] == ["ellipsis"] * len(categories), result
    assert result["plotWidth"] > 0, result
    assert result["documentOverflow"] is False, result


def test_categorical_tick_bounds_follow_anchor_rotation_and_extra_axis_side(
    tmp_path: Path,
) -> None:
    primary = [
        "Primary category with a long identity alpha",
        "Primary category with a long identity beta",
    ]
    secondary = [
        "Secondary category with a long identity alpha",
        "Secondary category with a long identity beta",
    ]
    chart = xy.chart(
        xy.scatter([1, 2], primary),
        xy.scatter([2, 3], secondary, y_axis="y2"),
        xy.x_axis(),
        xy.y_axis(tick_label_anchor="start", tick_label_angle=35),
        # An unset extra-y side defaults to right in the chrome placement path.
        xy.y_axis(id="y2", tick_label_anchor="center", tick_label_angle=-35),
        width=320,
        height=300,
        padding=(48, 96, 48, 96),
    )
    script = (
        _PRELUDE
        + """
    // Python normalizes an omitted extra-y side to "right". Remove it here to
    // exercise the client/update-spec state that previously disagreed: chrome
    // still defaults this axis to right via `side !== "left"`.
    view.axes.y2.side = undefined;
    view._drawNow();
    view._raf = null;
    const labels = [...view.root.querySelectorAll(
      '[data-xy-label-kind="tick"][data-xy-axis^="y"]'
    )];
    const root = view.root.getBoundingClientRect();
    const plotRight = root.left + view.plot.x + view.plot.w;
    const rows = labels.map((label) => {
      const rect = label.getBoundingClientRect();
      return {
        axis: label.dataset.xyAxis,
        side: label.dataset.xyAxisSide,
        left: rect.left,
        right: rect.right,
        inside: rect.left >= root.left - 1 && rect.right <= root.right + 1,
        pinnedRight: root.left + parseFloat(label.style.left) >= plotRight - 1,
      };
    });
    document.body.setAttribute("data-xy-issue-probe", JSON.stringify({ rows }));
"""
        + _POSTLUDE
    )
    result = _probe(chart, script, tmp_path, "categorical transformed placement")

    assert result["rows"], result
    assert all(row["inside"] for row in result["rows"]), result
    extra = [row for row in result["rows"] if row["axis"] == "y2"]
    assert extra, result
    assert all(row["side"] == "" for row in extra), result
    assert all(row["pinnedRight"] for row in extra), result
