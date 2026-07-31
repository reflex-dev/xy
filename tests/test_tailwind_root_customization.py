"""Browser and wrapper regressions for Tailwind DOM-slot customizability."""

from __future__ import annotations

from pathlib import Path

import pytest

import xy
from conftest import run_browser_probe
from xy.export import find_chromium

ROOT = Path(__file__).resolve().parents[1]
_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'

_TAILWIND_LAYERS = """
@layer base, components, utilities;
@layer utilities {
  .xy-tailwind-root-font {
    font-family: "Courier New", monospace;
    font-size: 23px;
    font-weight: 700;
    line-height: 29px;
  }
}
"""

_SLOT_TAILWIND_LAYERS = """
@layer base, components, utilities;
@layer utilities {
  .xy-tailwind-swatch {
    display: inline-flex;
    width: 31px;
    height: 19px;
    border-radius: 9px;
    background: rgb(219, 39, 119);
  }
  .fill-violet-500 { fill: rgb(139, 92, 246); }
  .stroke-cyan-400 { stroke: rgb(34, 211, 238); }
  .xy-tailwind-legend-state {
    opacity: .91;
    filter: sepia(1);
  }
  .xy-tailwind-tooltip {
    background: rgb(124, 58, 237);
    border: 3px solid rgb(253, 224, 71);
    padding: 13px;
    box-shadow: 0 6px 0 rgb(34, 197, 94);
  }
  .xy-tailwind-axis-title {
    color: rgb(220, 38, 38);
    font-size: 25px;
    font-weight: 800;
  }
}
"""

_FONT_PROBE = """
  const host = document.getElementById("chart");
  let view = xy.renderStandalone(host, spec, buf);
  try {
    const utility = getComputedStyle(view.root);
    const utilityFont = {
      family: utility.fontFamily,
      size: utility.fontSize,
      weight: utility.fontWeight,
      lineHeight: utility.lineHeight,
      inlineFont: view.root.style.font,
    };

    view.destroy();
    host.replaceChildren();
    const explicitSpec = {
      ...spec,
      dom: {
        ...(spec.dom || {}),
        style: {
          ...((spec.dom && spec.dom.style) || {}),
          font_family: "Georgia, serif",
          font_size: 17,
          font_weight: 500,
          line_height: 1.4,
        },
      },
    };
    view = xy.renderStandalone(host, explicitSpec, buf);
    const explicit = getComputedStyle(view.root);
    document.body.setAttribute("data-xy-root-font-probe", JSON.stringify({
      utility: utilityFont,
      explicit: {
        family: explicit.fontFamily,
        size: explicit.fontSize,
        weight: explicit.fontWeight,
        lineHeight: explicit.lineHeight,
      },
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-root-font-probe-error",
      String((err && err.stack) || err),
    );
  }
"""


def test_tailwind_root_font_utilities_and_explicit_styles_follow_the_cascade(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0]),
        class_name="xy-tailwind-root-font",
        width=420,
        height=280,
    )
    document = chart.to_html(custom_css=_TAILWIND_LAYERS)
    assert _RENDER_CALL in document
    document = document.replace(_RENDER_CALL, _FONT_PROBE, 1)

    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "tailwind_root_font.html",
        "data-xy-root-font-probe",
        label="Tailwind root font cascade probe",
    )

    utility = result["utility"]
    assert "Courier New" in utility["family"]
    assert utility["size"] == "23px"
    assert utility["weight"] == "700"
    assert utility["lineHeight"] == "29px"
    assert utility["inlineFont"] == ""

    explicit = result["explicit"]
    assert "Georgia" in explicit["family"]
    assert explicit["size"] == "17px"
    assert explicit["weight"] == "500"
    assert float(explicit["lineHeight"].removesuffix("px")) == pytest.approx(23.8, abs=0.1)


def test_live_wrapper_rebuilds_constructor_owned_chrome_only_when_needed() -> None:
    jsx = (ROOT / "python" / "reflex_xy" / "assets" / "XYChart.jsx").read_text(encoding="utf-8")

    assert "const mountedChromeSpec = (spec) => ({" in jsx
    for field in (
        "dom:",
        "title:",
        "padding:",
        "show_legend:",
        "legend:",
        "extra_legends:",
        "legend_traces:",
        "colorbar:",
        "has_density_badges:",
        "show_modebar:",
        "export:",
        "interaction:",
        "axes:",
    ):
        assert field in jsx
    # Trace buffers/columns and axis ranges stay outside the mounted-chrome
    # signature, so ordinary data-only publishes retain the updatePayload path.
    assert "legend_traces: (spec?.traces || []).map(legendTraceSpec)" in jsx
    assert "const axisLayoutSpec = (spec) =>" in jsx
    layout_at = jsx.index("const axisLayoutSpec = (spec) =>")
    chrome_at = jsx.index("const mountedChromeSpec = (spec) =>")
    assert layout_at < chrome_at, "axisLayoutSpec must precede mountedChromeSpec"
    assert "range:" not in jsx[layout_at:chrome_at]
    assert "const chromeChanged = Boolean(view && !sameMountedChromeSpec(view.spec, spec));" in jsx
    assert "if (!chromeChanged && view?.updatePayload?.(spec, nextBuffers)) {" in jsx
    assert jsx.index("const chromeChanged = Boolean(") < jsx.index(
        "if (!chromeChanged && view?.updatePayload?."
    )


def test_live_wrapper_silently_hydrates_durable_selection_and_all_axis_ranges() -> None:
    jsx = (ROOT / "python" / "reflex_xy" / "assets" / "XYChart.jsx").read_text(encoding="utf-8")

    assert "const durableState = view?.root?.xy?.state?.() || null;" in jsx
    assert "const viewChanged = changedFromHome(" in jsx
    assert "previousView?.ranges ? { ranges: previousView.ranges } : null" in jsx
    assert "view?.view0," in jsx
    assert "const selectionMaskRequest = pendingPushReplacesSelection(nextPayloadVersion)" in jsx
    assert "? null\n        : selectionRequest(selectionToRestore);" in jsx
    assert 'source: "republish",' in jsx
    assert "dispatch: false," in jsx
    assert "broadcast: false," in jsx
    assert jsx.count("hydrateSelectionForRepublish(selectionToRestore);") == 2
    assert jsx.count("restoreSelectionMask(selectionMaskRequest);") == 2
    assert "if (isRestore) clientMessage = { ...message, suppress_event: true };" in jsx
    assert "dispatchToView(clientMessage, data.buffers || [])" in jsx
    # Geometry is hydrated before the one direct mask re-request.
    assert jsx.index("view._applyStatePatch?.(") < jsx.rindex(
        "restoreSelectionMask(selectionMaskRequest);"
    )


def test_legend_swatch_utilities_win_but_interaction_state_remains_owned(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.chart(
        xy.bar(["Q1", "Q2"], [3.0, 5.0], name="Actual", color="#2563eb"),
        xy.scatter([0.0, 1.0], [2.0, 4.0], name="Plan", color=[0.1, 0.9]),
        xy.line([0.0, 1.0], [1.0, 4.5], name="Forecast", color="#16a34a"),
        xy.legend(),
        class_names={
            "legend_swatch": "xy-tailwind-swatch fill-violet-500 stroke-cyan-400",
            "legend_item": "xy-tailwind-legend-state",
        },
        width=460,
        height=300,
    )
    document = chart.to_html(custom_css=_SLOT_TAILWIND_LAYERS)
    assert _RENDER_CALL in document
    document = document.replace(
        _RENDER_CALL,
        """
  const host = document.getElementById("chart");
  let view = xy.renderStandalone(host, spec, buf);
  try {
    view._drawNow();
    view._raf = null;
    let swatches = [
      ...view.root.querySelectorAll('span[data-xy-slot="legend_swatch"]')
    ];
    let rows = [...view.root.querySelectorAll('[data-xy-slot="legend_item"]')];
    const swatch = swatches[0];
    const symbol = swatches[1].querySelector("path");
    const line = swatches[2].querySelector("line");
    const swatchStyle = getComputedStyle(swatch);
    const symbolStyle = getComputedStyle(symbol);
    const lineStyle = getComputedStyle(line);
    const utility = {
      display: swatchStyle.display,
      width: swatchStyle.width,
      height: swatchStyle.height,
      radius: swatchStyle.borderRadius,
      background: swatchStyle.backgroundColor,
      privatePaint: swatch.style.getPropertyValue("--xy-legend-swatch-paint"),
      inlineBackground: swatch.style.background,
      inlineWidth: swatch.style.width,
      inlineHeight: swatch.style.height,
      inlineDisplay: swatch.style.display,
      symbolFill: symbolStyle.fill,
      symbolStroke: symbolStyle.stroke,
      lineStroke: lineStyle.stroke,
      symbolFillAttribute: symbol.getAttribute("fill"),
      symbolStrokeAttribute: symbol.getAttribute("stroke"),
      lineStrokeAttribute: line.getAttribute("stroke"),
      symbolPrivateFill: swatches[1].style.getPropertyValue(
        "--xy-legend-swatch-fill"
      ),
      symbolPrivateStroke: swatches[1].style.getPropertyValue(
        "--xy-legend-swatch-stroke"
      ),
      linePrivateStroke: swatches[2].style.getPropertyValue(
        "--xy-legend-swatch-stroke"
      ),
    };

    const restStyle = getComputedStyle(rows[1]);
    const rest = {
      opacity: restStyle.opacity,
      filter: restStyle.filter,
      inlineOpacity: rows[1].style.opacity,
      inlineFilter: rows[1].style.filter,
    };
    rows[0].dispatchEvent(new PointerEvent("pointerenter"));
    const hoverStyle = getComputedStyle(rows[1]);
    const hover = {
      opacity: hoverStyle.opacity,
      inlineOpacity: rows[1].style.opacity,
    };
    rows[0].dispatchEvent(new PointerEvent("pointerleave"));
    rows[0].click();
    const offStyle = getComputedStyle(rows[0]);
    const off = {
      opacity: offStyle.opacity,
      filter: offStyle.filter,
      inlineOpacity: rows[0].style.opacity,
      inlineFilter: rows[0].style.filter,
      state: rows[0].hasAttribute("data-xy-legend-off"),
    };

    view.destroy();
    host.replaceChildren();
    const explicitSpec = {
      ...spec,
      dom: {
        ...(spec.dom || {}),
        styles: {
          ...((spec.dom && spec.dom.styles) || {}),
          legend_swatch: {
            background: "#16a34a",
            width: 17,
            height: 13,
            display: "block",
          },
        },
      },
    };
    view = xy.renderStandalone(host, explicitSpec, buf);
    view._drawNow();
    swatches = [
      ...view.root.querySelectorAll('span[data-xy-slot="legend_swatch"]')
    ];
    rows = [...view.root.querySelectorAll('[data-xy-slot="legend_item"]')];
    const explicitStyle = getComputedStyle(swatches[0]);
    document.body.setAttribute("data-xy-slot-cascade-probe", JSON.stringify({
      utility,
      rest,
      hover,
      off,
      explicit: {
        display: explicitStyle.display,
        width: explicitStyle.width,
        height: explicitStyle.height,
        background: explicitStyle.backgroundColor,
      },
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-slot-cascade-probe-error",
      String((err && err.stack) || err),
    );
  }
""",
        1,
    )

    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "tailwind_legend_swatch.html",
        "data-xy-slot-cascade-probe",
        label="Tailwind legend swatch cascade probe",
    )

    utility = result["utility"]
    assert utility["display"] == "inline-flex"
    assert utility["width"] == "31px"
    assert utility["height"] == "19px"
    assert utility["radius"] == "9px"
    assert utility["background"] == "rgb(219, 39, 119)"
    assert utility["privatePaint"]
    assert utility["inlineBackground"] == ""
    assert utility["inlineWidth"] == ""
    assert utility["inlineHeight"] == ""
    assert utility["inlineDisplay"] == ""
    assert utility["symbolFill"] == "rgb(139, 92, 246)"
    assert utility["symbolStroke"] == "rgb(34, 211, 238)"
    assert utility["lineStroke"] == "rgb(34, 211, 238)"
    assert utility["symbolFillAttribute"] is None
    assert utility["symbolStrokeAttribute"] is None
    assert utility["lineStrokeAttribute"] is None
    assert utility["symbolPrivateFill"].startswith("url(")
    assert utility["symbolPrivateStroke"].startswith("url(")
    assert utility["linePrivateStroke"]

    # Ordinary utilities own the at-rest appearance. Hover/off are semantic
    # renderer states and intentionally take priority through inline values.
    assert result["rest"] == {
        "opacity": "0.91",
        "filter": "sepia(1)",
        "inlineOpacity": "",
        "inlineFilter": "",
    }
    assert result["hover"] == {"opacity": "0.4", "inlineOpacity": "0.4"}
    assert result["off"] == {
        "opacity": "0.35",
        "filter": "grayscale(1)",
        "inlineOpacity": "0.35",
        "inlineFilter": "grayscale(1)",
        "state": True,
    }

    assert result["explicit"] == {
        "display": "block",
        "width": "17px",
        "height": "13px",
        "background": "rgb(22, 163, 74)",
    }


def test_custom_tooltip_state_does_not_override_utilities_or_explicit_styles(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0], [1.0, 2.0]),
        xy.tooltip(),
        class_names={"tooltip": "xy-tailwind-tooltip"},
        width=420,
        height=280,
    )
    document = chart.to_html(custom_css=_SLOT_TAILWIND_LAYERS)
    assert _RENDER_CALL in document
    document = document.replace(
        _RENDER_CALL,
        """
  const host = document.getElementById("chart");
  let view = xy.renderStandalone(host, spec, buf);
  try {
    const child = document.createElement("div");
    child.textContent = "Custom tooltip";
    view.setCustomTooltip(child);
    view.tooltip.classList.remove("xy-tailwind-tooltip");
    const classless = {
      boxShadow: getComputedStyle(view.tooltip).boxShadow,
    };
    view.tooltip.classList.add("xy-tailwind-tooltip");
    const utilityStyle = getComputedStyle(view.tooltip);
    const utility = {
      background: utilityStyle.backgroundColor,
      border: utilityStyle.border,
      padding: utilityStyle.padding,
      boxShadow: utilityStyle.boxShadow,
      state: view.tooltip.hasAttribute("data-xy-custom-tooltip"),
      inlineBackground: view.tooltip.style.background,
      inlineBorder: view.tooltip.style.border,
      inlinePadding: view.tooltip.style.padding,
      inlineBoxShadow: view.tooltip.style.boxShadow,
    };

    view.destroy();
    host.replaceChildren();
    const explicitSpec = {
      ...spec,
      dom: {
        ...(spec.dom || {}),
        styles: {
          ...((spec.dom && spec.dom.styles) || {}),
          tooltip: {
            background: "#0f766e",
            border: "4px dotted #fbbf24",
            padding: 7,
            box_shadow: "0 7px 0 #f43f5e",
          },
        },
      },
    };
    view = xy.renderStandalone(host, explicitSpec, buf);
    const explicitChild = document.createElement("div");
    explicitChild.textContent = "Explicit custom tooltip";
    view.setCustomTooltip(explicitChild);
    const explicitStyle = getComputedStyle(view.tooltip);
    document.body.setAttribute("data-xy-tooltip-cascade-probe", JSON.stringify({
      classless,
      utility,
      explicit: {
        background: explicitStyle.backgroundColor,
        border: explicitStyle.border,
        padding: explicitStyle.padding,
        boxShadow: explicitStyle.boxShadow,
        state: view.tooltip.hasAttribute("data-xy-custom-tooltip"),
      },
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-tooltip-cascade-probe-error",
      String((err && err.stack) || err),
    );
  }
""",
        1,
    )

    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "tailwind_custom_tooltip.html",
        "data-xy-tooltip-cascade-probe",
        label="Tailwind custom tooltip cascade probe",
    )

    assert result["classless"] == {"boxShadow": "none"}
    assert result["utility"] == {
        "background": "rgb(124, 58, 237)",
        "border": "3px solid rgb(253, 224, 71)",
        "padding": "13px",
        "boxShadow": "rgb(34, 197, 94) 0px 6px 0px 0px",
        "state": True,
        "inlineBackground": "",
        "inlineBorder": "",
        "inlinePadding": "",
        "inlineBoxShadow": "",
    }
    assert result["explicit"] == {
        "background": "rgb(15, 118, 110)",
        "border": "4px dotted rgb(251, 191, 36)",
        "padding": "7px",
        "boxShadow": "rgb(244, 63, 94) 0px 7px 0px 0px",
        "state": True,
    }


def test_axis_title_weight_utility_wins_default_while_typed_style_stays_inline(
    tmp_path: Path,
) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")

    chart = xy.line_chart(
        xy.line([0.0, 1.0], [1.0, 2.0]),
        xy.x_axis(
            label="Time",
            style={"label_color": "#0f766e", "label_size": 17},
        ),
        class_names={"axis_title": "xy-tailwind-axis-title"},
        width=440,
        height=300,
    )
    document = chart.to_html(custom_css=_SLOT_TAILWIND_LAYERS)
    assert _RENDER_CALL in document
    document = document.replace(
        _RENDER_CALL,
        """
  const host = document.getElementById("chart");
  let view = xy.renderStandalone(host, spec, buf);
  try {
    view._drawNow();
    view._raf = null;
    let title = view.root.querySelector(
      '[data-xy-slot="axis_title"][data-xy-axis="x"]'
    );
    const utilityStyle = getComputedStyle(title);
    const utility = {
      weight: utilityStyle.fontWeight,
      size: utilityStyle.fontSize,
      color: utilityStyle.color,
      inlineWeight: title.style.fontWeight,
      inlineSize: title.style.fontSize,
      inlineColor: title.style.color,
    };

    view.destroy();
    host.replaceChildren();
    const explicitSpec = {
      ...spec,
      dom: {
        ...(spec.dom || {}),
        styles: {
          ...((spec.dom && spec.dom.styles) || {}),
          axis_title: {
            font_weight: 650,
            font_size: 19,
            color: "#1d4ed8",
          },
        },
      },
    };
    view = xy.renderStandalone(host, explicitSpec, buf);
    view._drawNow();
    title = view.root.querySelector(
      '[data-xy-slot="axis_title"][data-xy-axis="x"]'
    );
    const explicitStyle = getComputedStyle(title);
    document.body.setAttribute("data-xy-axis-title-cascade-probe", JSON.stringify({
      utility,
      explicit: {
        weight: explicitStyle.fontWeight,
        size: explicitStyle.fontSize,
        color: explicitStyle.color,
      },
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-axis-title-cascade-probe-error",
      String((err && err.stack) || err),
    );
  }
""",
        1,
    )

    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "tailwind_axis_title.html",
        "data-xy-axis-title-cascade-probe",
        label="Tailwind axis title cascade probe",
    )

    # The utility owns the former fallback weight. Typed axis size/color stay
    # inline because they are explicit cross-renderer author intent.
    assert result["utility"] == {
        "weight": "800",
        "size": "17px",
        "color": "rgb(15, 118, 110)",
        "inlineWeight": "",
        "inlineSize": "17px",
        "inlineColor": "rgb(15, 118, 110)",
    }
    assert result["explicit"] == {
        "weight": "650",
        "size": "19px",
        "color": "rgb(29, 78, 216)",
    }
