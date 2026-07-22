import assert from "node:assert/strict";
import test from "node:test";

import {
  __testing,
  ChartView,
  MARK_KINDS,
  markOf,
} from "../../python/xy/static/index.js";
import { fakeStyleElement, makeView, standaloneNamespace } from "./helpers.mjs";

test("ticks and formatters preserve f64, category, log, and UTC semantics", () => {
  assert.equal(__testing.niceStep(2.1), 2.5);
  assert.deepEqual(__testing.linearTicks(9, -1, 4), {
    ticks: [0, 2.5, 5, 7.5],
    step: 2.5,
  });
  assert.deepEqual(__testing.linearTicks(Number.NaN, 1), { ticks: [], step: 1 });
  assert.deepEqual(__testing.logTicks(0.1, 100, 4).ticks, [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100]);
  assert.deepEqual(__testing.logTicks(-1, 10), { ticks: [], step: 1 });
  assert.deepEqual(__testing.categoryTicks(-2, 4, ["a", "b", "c", "d", "e"], 3), {
    ticks: [0, 2, 4],
    step: 2,
  });

  const instant = Date.UTC(2024, 2, 10, 7, 8, 9);
  assert.equal(__testing.fmtTimeSpec(instant, "%Y-%m-%d %H:%M:%S"), "2024-03-10 07:08:09");
  assert.equal(__testing.fmtTime(instant, 60_000), "07:08");
  assert.equal(__testing.fmtNumberSpec(0.125, ".1%"), "12.5%");
  assert.equal(__testing.fmtNumberSpec(1234.5, ",.1f"), "1,234.5");
  assert.throws(
    () => __testing.fmtNumberSpec(1, ".999f"),
    /unsupported numeric format/,
  );
  assert.equal(__testing.fmtGeneral(999999.5), "1e+06");
  assert.equal(__testing.fmtAxis({ kind: "category", categories: ["zero", "one"] }, 1, 1), "one");
  assert.equal(__testing.fmtAxis({ scale: "log", format: ".0f" }, 0.01, 0.01), "0.01");
  assert.equal(__testing.fmtValue(1e-8), "1.000e-8");
});

test("transforms map linear, reversed, and log axes without f32 round trips", () => {
  const view = makeView({
    axes: {
      x: { range: [0, 10] },
      y: { range: [100, 0] },
      y2: { range: [1, 1000], scale: "log" },
    },
  });

  assert.deepEqual(view._map({ offset: 1000, scale: 2 }, 1000, 1010), [0.1, -1]);
  assert.deepEqual(view._map({}, 0, 10, "x"), [0.2, -1]);
  assert.deepEqual(view._map({}, 1, 1000, "y2"), [2 / 3, -1]);
  assert.ok(Math.abs(view._mapConst(100, 1, 1000, "y2") - 1 / 3) < 1e-12);
  assert.deepEqual(view._map({}, 0, 0, "x"), [0, -2]);
  assert.equal(view._axisCoord({ scale: "log" }, 0), Number.NaN);
  assert.equal(view._dataPx("x", 5), 110);
  assert.equal(view._dataPx("y", 75), 95);
  assert.equal(view._dataPx("y2", 10), 86.66666666666667);
  assert.equal(view._edgePadForValue(0, 0, 10, 200), -0.02);
  assert.equal(view._edgePadForValue(10, 0, 10, 200), 0.02);
});

test("axis bounds and zoom limits clamp while preserving reversal and anchors", () => {
  const view = makeView({
    axes: {
      x: { range: [0, 10], bounds: [-5, 15] },
      y: { range: [100, 1], bounds: [1000, 0.1], scale: "log" },
    },
    interaction: { zoom_limits: { x: [0.5, 4], y: [1, 2] } },
  });

  assert.deepEqual(view._clampAxisRange("x", -20, 0), [-5, 15]);
  assert.deepEqual(view._clampAxisRange("x", 8, 9, 0), [8, 10.5]);
  assert.deepEqual(view._clampAxisRange("y", 10, 1, 0.5), [10, 1]);
  assert.deepEqual(view._clampAxisRange("y", 10_000, 0.01, 0.5), [100, 1]);
  assert.deepEqual(view._clampAxisRange("x", Number.NaN, 1), [0, 10]);
});

test("theme colors and authored styles normalize through one strict path", () => {
  assert.deepEqual(__testing.hexColor("#0f08"), [0, 1, 0, 136 / 255]);
  assert.deepEqual(__testing.hexColor("336699"), [0.2, 0.4, 0.6, 1]);
  assert.equal(__testing.hexColor("#12"), null);
  assert.equal(__testing.cssColor([0.2, 0.4, 0.6, 0.5]), "rgba(51,102,153,0.5)");
  assert.deepEqual(__testing.parseColor(null, 42, [1, 0, 0, 1]), [1, 0, 0, 1]);
  assert.equal(__testing.safeCssPaint(null, "#336699"), "rgba(51,102,153,1)");

  const view = Object.create(ChartView.prototype);
  const element = fakeStyleElement();
  view._applyStyle(element, {
    font_size: 12,
    lineHeight: 1.25,
    "--chart-alpha": 0.6,
    opacity: Number.NaN,
    ignored: { nested: true },
  });
  assert.deepEqual(Object.fromEntries(element.values), {
    "font-size": "12px",
    "line-height": "1.25",
    "--chart-alpha": "0.6",
  });
  assert.equal(view._stylePropertyName("borderTopWidth"), "border-top-width");
  assert.equal(view._stylePropertyValue("width", Infinity), null);

  view.spec = { dom: { styles: { legend: { max_height: 50 } } } };
  assert.equal(view._slotStyleValue("legend", "max-height"), 50);
  assert.equal(view._slotStyleValue("legend", "width"), null);
});

test("theme tokens resolve once with currentColor fallbacks", () => {
  const previousDocument = globalThis.document;
  const previousGetComputedStyle = globalThis.getComputedStyle;
  const tokens = {
    "--chart-bg": "rgb(255, 255, 255)",
    "--chart-grid": "rgb(255, 0, 0)",
    "--chart-axis": "",
    "--chart-text": "rgb(0, 128, 0)",
  };
  const colors = {
    currentColor: "rgb(51, 102, 153)",
    "rgb(255, 255, 255)": "rgb(255, 255, 255)",
    "rgb(255, 0, 0)": "rgb(255, 0, 0)",
    "rgb(0, 128, 0)": "rgb(0, 128, 0)",
  };
  const root = {
    appendChild() {},
    removeChild() {},
  };
  try {
    globalThis.document = {
      createElement() {
        return { style: {} };
      },
    };
    globalThis.getComputedStyle = (element) => element === root
      ? { getPropertyValue: (name) => tokens[name] || "" }
      : { color: colors[element.style.color] || "" };

    const theme = __testing.readTheme(root);

    assert.deepEqual(theme.bg, [1, 1, 1, 1]);
    assert.deepEqual(theme.grid, [1, 0, 0, 1]);
    assert.deepEqual(theme.axis, [0.2, 0.4, 0.6, 0.55]);
    assert.deepEqual(theme.label, [0, 128 / 255, 0, 1]);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousGetComputedStyle === undefined) delete globalThis.getComputedStyle;
    else globalThis.getComputedStyle = previousGetComputedStyle;
  }
});

test("mark registry is complete and dispatches unknown kinds to scatter", () => {
  assert.equal(Object.isFrozen(__testing), true);
  const expected = [
    "area", "bar", "box", "box_median", "box_whisker", "column", "contour",
    "error_band", "errorbar", "heatmap", "hexbin", "histogram", "line", "scatter",
    "segments", "stem", "triangle_mesh", "violin",
  ];
  assert.deepEqual(Object.keys(MARK_KINDS).sort(), expected);
  for (const kind of expected) {
    assert.equal(typeof MARK_KINDS[kind].build, "function", `${kind} build`);
    assert.equal(typeof MARK_KINDS[kind].draw, "function", `${kind} draw`);
    assert.equal(markOf(kind), MARK_KINDS[kind]);
  }
  assert.equal(markOf("malformed-kind"), MARK_KINDS.scatter);
  assert.equal(MARK_KINDS.scatter.pointPick, true);
  assert.equal(MARK_KINDS.scatter.retainCpu, true);
});

test("standalone namespace excludes the ESM-only semantic seam", () => {
  const standalone = standaloneNamespace();
  assert.equal("__testing" in standalone, false);
  assert.equal(typeof standalone.renderStandalone, "function");
  assert.equal(standalone.MARK_KINDS.scatter.pointPick, true);
});

test("LOD chooses the tightest covering grid and preserves the broad fallback", () => {
  const broad = { tex: {}, xRange: [0, 100], yRange: [0, 100] };
  const tight = { tex: {}, xRange: [20, 40], yRange: [20, 40] };
  const unrelated = { tex: {}, xRange: [200, 220], yRange: [200, 220] };
  const view = {
    _viewInsideRange(xRange, yRange) {
      return xRange[0] <= 25 && xRange[1] >= 35 && yRange[0] <= 25 && yRange[1] >= 35;
    },
  };
  const g = { density: broad, densityCache: [unrelated, broad, tight] };

  assert.equal(__testing.lodDensityForView(view, g), tight);
  view._viewInsideRange = () => false;
  assert.equal(__testing.lodDensityForView(view, g), broad);
  assert.equal(__testing.lodDensityForView(view, { density: broad, densityCache: [] }), broad);
});

test("LOD direct-drill hysteresis rejects stale, dying, and over-budget holds", () => {
  assert.equal(__testing.LOD_DIRECT_POINT_BUDGET, 200_000);
  let now = 1_000;
  const view = {
    seq: 3,
    _now: () => now,
  };
  const drill = {
    win: { x0: 0, x1: 10, y0: 0, y1: 10 },
    visible: 100_000,
  };
  const g = {
    _lodPendingView: { x0: 0, x1: 15, y0: 0, y1: 10 },
    _lodPendingSeq: 3,
    _lodPendingAt: 900,
  };
  assert.equal(__testing.lodHoldPendingDrill(view, g, drill), true);
  g._lodPendingView.x1 = 30;
  assert.equal(__testing.lodHoldPendingDrill(view, g, drill), false);
  g._lodPendingView.x1 = 15;
  g._lodPendingSeq = 2;
  assert.equal(__testing.lodHoldPendingDrill(view, g, drill), false);
  g._lodPendingSeq = 3;
  g._drillDying = true;
  assert.equal(__testing.lodHoldPendingDrill(view, g, drill), false);
  g._drillDying = false;
  now = 2_500;
  assert.equal(__testing.lodHoldPendingDrill(view, g, drill), false);
});

test("ChartView state copies named axes and emits only real bounded changes", () => {
  const view = makeView({
    axes: {
      x: { range: [0, 10], bounds: [0, 10] },
      y: { range: [0, 20], bounds: [0, 20] },
      y2: { range: [100, 200], bounds: [100, 200] },
    },
  });
  const draws = [];
  const requests = [];
  const events = [];
  view.draw = () => draws.push(view._copyView(view.view));
  view._scheduleViewRequest = () => requests.push(view._copyView(view.view));
  view._emitViewChange = (source, options) => events.push({ source, options });
  view._cancelViewAnimation = () => {};
  view._prefersReducedMotion = () => true;

  const source = view._copyView(view.view);
  source.ranges.y2[0] = 999;
  assert.equal(view.view.ranges.y2[0], 100);

  const changed = view._setView({ ranges: { x: [2, 6], y2: [125, 175] } }, {
    source: "unit",
  });
  assert.deepEqual(changed, ["x", "y2"]);
  assert.deepEqual(view.view.ranges.x, [2, 6]);
  assert.deepEqual(view.view.ranges.y, [0, 20]);
  assert.deepEqual(view.view.ranges.y2, [125, 175]);
  assert.equal(draws.length, 1);
  assert.equal(requests.length, 1);
  assert.deepEqual(events, [{ source: "unit", options: {
    axes: ["x", "y2"], phase: "end", interactionId: undefined, broadcast: undefined,
  } }]);

  assert.deepEqual(view._setView(view.view, { source: "noop" }), []);
  assert.equal(draws.length, 1);
});
