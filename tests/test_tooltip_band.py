"""Shared-axis tooltip (`xy.tooltip(mode="x")`, interaction spec §7.3).

Recharts' axis tooltip and Plotly's `hovermode="x unified"`: the pointer's
position along the band axis alone selects the data, the perpendicular
position is ignored, every series' point at that coordinate is listed with a
cursor line and an active dot, and the band boundary is halfway between
adjacent points. Browser probes drive the real client; they skip (never
fail) without Chromium, like the repo's others.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from conftest import probe_document, run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy.export import find_chromium  # noqa: E402

PAGES = ["Page A", "Page B", "Page C", "Page D", "Page E", "Page F", "Page G"]
PV = [2400.0, 1398.0, 9800.0, 3908.0, 4800.0, 3800.0, 4300.0]
UV = [4000.0, 3000.0, 2000.0, 2780.0, 1890.0, 2390.0, 3490.0]


def test_tooltip_mode_option() -> None:
    """`mode` rides the wire only when it is not the default, like the other
    opt-in chrome switches, so existing specs stay byte-identical."""
    chart = xy.line_chart(xy.line(PAGES, PV, name="pv"), xy.tooltip(mode="x"))
    assert chart.figure().build_payload()[0]["tooltip"]["mode"] == "x"
    chart = xy.line_chart(xy.line(PAGES, PV, name="pv"), xy.tooltip(mode="y"))
    assert chart.figure().build_payload()[0]["tooltip"]["mode"] == "y"
    default = xy.line_chart(xy.line(PAGES, PV, name="pv"), xy.tooltip())
    assert "mode" not in default.figure().build_payload()[0].get("tooltip", {})
    with pytest.raises(ValueError, match="tooltip mode must be one of"):
        xy.tooltip(mode="unified")
    with pytest.raises(ValueError, match="tooltip mode must be one of"):
        xy.tooltip(mode=None)  # type: ignore[arg-type]
    # Public dataclass: the new field appends after the released order.
    assert xy.Tooltip(True, None, None, {}, None, {}, None, {}).mode == "nearest"
    # A direct dataclass edit is re-validated at build.
    node = xy.tooltip()
    node.mode = "diagonal"
    with pytest.raises(ValueError, match="tooltip mode must be one of"):
        xy.line_chart(xy.line(PAGES, PV, name="pv"), node).figure()


def test_tooltip_cursor_is_a_public_dom_slot() -> None:
    assert "tooltip_cursor" in xy.CHART_DOM_SLOTS


_BAND_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const sent = [];
    view.comm = { send: (m) => sent.push(m) };
    const hovers = [];
    document.addEventListener("xy:hover", (e) => hovers.push(e.detail));
    for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
    const rect = view.canvas.getBoundingClientRect();
    const g = view.gpuTraces[0];
    // Category positions are label indices: Page B is 1, Page C is 2.
    const [bx] = view._projectDataPoint(g.xAxis, g.yAxis, 1, 0);
    const [cx] = view._projectDataPoint(g.xAxis, g.yAxis, 2, 0);
    const bCss = bx - view.plot.x;
    const midCss = (bx + cx) / 2 - view.plot.x;
    const hover = (x, y) => view._hover({ clientX: rect.left + x, clientY: rect.top + y });
    const tip = view.tooltip;
    const cursor = () => view.root.querySelector('[data-xy-slot="tooltip_cursor"]');
    const state = () => ({
      shown: tip.style.display === "block",
      title: tip.querySelector('[data-xy-slot="tooltip_title"]')?.textContent ?? null,
      rows: [...tip.querySelectorAll('[data-xy-slot="tooltip_row"]')].map((r) => r.textContent),
      labelColors: [...tip.querySelectorAll('[data-xy-slot="tooltip_label"]')].map((l) => l.style.color),
      targets: (view._hoverTargets || []).length,
      cursorShown: !!cursor() && cursor().style.display === "block",
      cursorLeft: cursor() ? parseFloat(cursor().style.left) : null,
      cursorHeight: cursor() ? parseFloat(cursor().style.height) : null,
      tipLeft: parseFloat(tip.style.left),
    });

    // Active dots are measured on the presented 2D canvas, not with
    // readPixels on the shared GL context: count series-coloured pixels in a
    // window around each series' Page B point before and after the hover.
    const dpr = view.dpr;
    const snap = () => {
      const c = document.createElement("canvas");
      c.width = view.canvas.width; c.height = view.canvas.height;
      const ctx = c.getContext("2d"); ctx.drawImage(view.canvas, 0, 0); return ctx;
    };
    const near = (ctx, x, y, rgb) => {
      const d = ctx.getImageData(Math.round(x - 14), Math.round(y - 14), 28, 28).data;
      let n = 0;
      for (let i = 0; i < d.length; i += 4) {
        if (d[i + 3] > 0 && Math.abs(d[i] - rgb[0]) < 40 && Math.abs(d[i + 1] - rgb[1]) < 40 && Math.abs(d[i + 2] - rgb[2]) < 40) n++;
      }
      return n;
    };
    const [, pvY] = view._projectDataPoint(g.xAxis, g.yAxis, 1, 1398);
    const [, uvY] = view._projectDataPoint(g.xAxis, g.yAxis, 1, 3000);
    const dotPx = (bx - view.plot.x) * dpr, pvPx = (pvY - view.plot.y) * dpr, uvPx = (uvY - view.plot.y) * dpr;
    view._drawNow();
    const base = snap();
    const dotsBefore = [near(base, dotPx, pvPx, [136, 132, 216]), near(base, dotPx, uvPx, [130, 202, 157])];

    // Far above every point, horizontally aligned with Page B: the whole
    // plot height is the hit target.
    hover(bCss, 4);
    view._drawNow();
    const lit = snap();
    const dotsAfter = [near(lit, dotPx, pvPx, [136, 132, 216]), near(lit, dotPx, uvPx, [130, 202, 157])];
    const aboveB = { ...state(), anchorLeft: bx, plotH: view.plot.h, dotsBefore, dotsAfter };
    const picksAfterB = sent.filter((m) => m.type === "pick").map((m) => [m.trace, m.index]);
    // Same band, lower and slightly right: content stays, tooltip follows.
    hover(bCss + 3, view.plot.h - 4);
    const sameBand = state();
    const picksAfterSame = sent.filter((m) => m.type === "pick").length;
    // Two pixels past the midpoint toward Page C: the band switches.
    hover(midCss + 2, 4);
    const pastMid = state();
    // Two pixels before the midpoint: back to Page B.
    hover(midCss - 2, view.plot.h / 2);
    const beforeMid = state();
    // Outside the plot: everything hides.
    hover(-20, 4);
    const outside = state();
    // Legend-hide uv: the band lists only pv.
    const legendRows = [...document.querySelectorAll('[data-xy-slot="legend_item"]')];
    legendRows.find((r) => r.textContent === "uv").dispatchEvent(new MouseEvent("click"));
    hover(bCss, 4);
    const uvHidden = state();
    document.body.setAttribute("data-xy-bandtip", JSON.stringify({
      aboveB, sameBand, pastMid, beforeMid, outside, uvHidden,
      picksAfterB, picksAfterSame,
      hoverPoints: hovers.map((h) => [(h.points || []).length, h.trace, h.index, h.row && h.row.x]),
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-bandtip-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def _recharts_chart(**tooltip):
    return xy.line_chart(
        xy.line(PAGES, PV, name="pv", color="#8884d8", width=2),
        xy.line(PAGES, UV, name="uv", color="#82ca9d", width=2),
        xy.tooltip(**tooltip),
        xy.legend(),
        # DOM hover events are opt-in (interaction spec §2); the probe asserts
        # their payload.
        xy.interaction_config(hover=True),
        width=640,
        height=360,
    )


def test_browser_x_band_selects_by_horizontal_position_only() -> None:
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the band tooltip probe")
    document = probe_document(_recharts_chart(mode="x"), _BAND_PROBE)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            chromium, document, Path(td) / "band.html", "data-xy-bandtip", label="x band"
        )

    s = payload["aboveB"]
    assert s["shown"] is True and s["title"] == "Page B", s
    assert s["rows"] == ["pv1398", "uv3000"], s  # label + value text nodes
    assert s["targets"] == 2, s
    # Series names carry their series colour as the swatch.
    assert s["labelColors"] == ["rgb(136, 132, 216)", "rgb(130, 202, 157)"], s
    # The cursor spans the plot at Page B's projected x.
    assert s["cursorShown"] is True, s
    assert abs(s["cursorLeft"] - s["anchorLeft"]) <= 0.5, s
    assert abs(s["cursorHeight"] - s["plotH"]) <= 0.5, s
    # Every series in the band gets an active dot in its own colour: the
    # series-coloured pixel count around each Page B point grows well past
    # what the 2 px line alone contributes.
    for before, after in zip(s["dotsBefore"], s["dotsAfter"], strict=True):
        # Threshold sized for a DPR-1 headless run (a 9 px dot over a 2 px line).
        assert after > before + 30, (s["dotsBefore"], s["dotsAfter"])
    # One exact pick per series in the band.
    assert sorted(payload["picksAfterB"]) == [[0, 1], [1, 1]], payload["picksAfterB"]

    # Moving inside the same band re-places the tooltip and sends nothing new.
    t = payload["sameBand"]
    assert t["title"] == "Page B" and t["rows"] == s["rows"], t
    assert t["tipLeft"] != s["tipLeft"], (t["tipLeft"], s["tipLeft"])
    assert payload["picksAfterSame"] == 2, payload["picksAfterSame"]

    # The boundary is halfway between adjacent points.
    assert payload["pastMid"]["title"] == "Page C", payload["pastMid"]
    assert payload["pastMid"]["rows"] == ["pv9800", "uv2000"], payload["pastMid"]
    assert payload["beforeMid"]["title"] == "Page B", payload["beforeMid"]

    o = payload["outside"]
    assert o["shown"] is False and o["cursorShown"] is False and o["targets"] == 0, o

    h = payload["uvHidden"]
    assert h["rows"] == ["pv1398"] and h["targets"] == 1, h

    # xy:hover carries every series in the band; the first is primary.
    assert payload["hoverPoints"][0] == [2, 0, 1, "Page B"], payload["hoverPoints"]
    assert payload["hoverPoints"][-1] == [1, 0, 1, "Page B"], payload["hoverPoints"]


_NEAREST_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    view._raf = null;
    view.comm = { send: () => {} };
    for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
    const rect = view.canvas.getBoundingClientRect();
    const g = view.gpuTraces[0];
    const [bx] = view._projectDataPoint(g.xAxis, g.yAxis, 1, 0);
    view._hover({ clientX: rect.left + bx - view.plot.x, clientY: rect.top + 4 });
    document.body.setAttribute("data-xy-nearest", JSON.stringify({
      shown: view.tooltip.style.display === "block",
      cursor: !!view.root.querySelector('[data-xy-slot="tooltip_cursor"]'),
      targets: (view._hoverTargets || []).length,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-nearest-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_default_mode_still_needs_the_pointer_near_a_point() -> None:
    """The default is unchanged: far above the points there is no tooltip and
    no cursor element is ever created."""
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the nearest tooltip probe")
    document = probe_document(_recharts_chart(), _NEAREST_PROBE)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            chromium, document, Path(td) / "nearest.html", "data-xy-nearest", label="nearest"
        )
    assert payload == {"shown": False, "cursor": False, "targets": 0}, payload


_Y_BAND_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    view._raf = null;
    view.comm = { send: () => {} };
    for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
    const rect = view.canvas.getBoundingClientRect();
    const g = view.gpuTraces[0];
    // y = 20 is the second point of both series; hover far to its right.
    const [, py] = view._projectDataPoint(g.xAxis, g.yAxis, 0, 20);
    view._hover({ clientX: rect.left + view.plot.w - 4, clientY: rect.top + py - view.plot.y });
    const tip = view.tooltip;
    const cursor = view.root.querySelector('[data-xy-slot="tooltip_cursor"]');
    document.body.setAttribute("data-xy-yband", JSON.stringify({
      title: tip.querySelector('[data-xy-slot="tooltip_title"]')?.textContent ?? null,
      rows: [...tip.querySelectorAll('[data-xy-slot="tooltip_row"]')].map((r) => r.textContent),
      cursorWidth: cursor ? parseFloat(cursor.style.width) : null,
      cursorTop: cursor ? parseFloat(cursor.style.top) : null,
      anchorTop: py, plotW: view.plot.w,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-yband-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_y_band_selects_by_vertical_position_only() -> None:
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the y band probe")
    ys = [10.0, 20.0, 30.0]
    chart = xy.scatter_chart(
        xy.scatter([1.0, 2.0, 3.0], ys, name="left", size=8),
        xy.scatter([4.0, 5.0, 6.0], ys, name="right", size=8),
        xy.tooltip(mode="y"),
        width=640,
        height=360,
    )
    document = probe_document(chart, _Y_BAND_PROBE)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            chromium, document, Path(td) / "yband.html", "data-xy-yband", label="y band"
        )
    assert payload["title"] == "20", payload
    assert payload["rows"] == ["left2", "right5"], payload
    assert abs(payload["cursorWidth"] - payload["plotW"]) <= 0.5, payload
    assert abs(payload["cursorTop"] - payload["anchorTop"]) <= 0.5, payload


def test_band_mode_leaves_static_exports_alone() -> None:
    """Tooltips are live-only; the option must not change a byte of the SVG."""
    plain = _recharts_chart().to_svg()
    banded = _recharts_chart(mode="x").to_svg()
    assert plain == banded
    assert np.array_equal(
        np.frombuffer(_recharts_chart().to_png(), dtype=np.uint8),
        np.frombuffer(_recharts_chart(mode="x").to_png(), dtype=np.uint8),
    )


_HOVER_DOT_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    view._raf = null;
    view.comm = { send: () => {} };
    for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
    const rect = view.canvas.getBoundingClientRect();
    const g = view.gpuTraces[0];
    const dpr = view.dpr;
    const [px, py] = view._projectDataPoint(g.xAxis, g.yAxis, 1, 4);
    const cx = (px - view.plot.x) * dpr, cy = (py - view.plot.y) * dpr;
    const snap = () => {
      const c = document.createElement("canvas");
      c.width = view.canvas.width; c.height = view.canvas.height;
      const ctx = c.getContext("2d"); ctx.drawImage(view.canvas, 0, 0); return ctx;
    };
    // The hover highlight paint is dark (rgba(15,23,42,.92)); the marks are not.
    const dark = (ctx) => {
      const d = ctx.getImageData(Math.round(cx - 14), Math.round(cy - 14), 28, 28).data;
      let n = 0;
      for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 0 && d[i] < 70 && d[i + 1] < 70 && d[i + 2] < 90) n++;
      return n;
    };
    view._drawNow();
    const before = dark(snap());
    view._hover({ clientX: rect.left + px - view.plot.x, clientY: rect.top + py - view.plot.y });
    view._drawNow();
    const after = dark(snap());
    document.body.setAttribute("data-xy-hoverdot", JSON.stringify({
      before, after, target: view._hoverTarget ? [view._hoverTarget.trace, view._hoverTarget.index] : null,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-hoverdot-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_nearest_hover_highlight_is_visible() -> None:
    """The hover highlight dot had silently stopped rendering: the full point
    program multiplies fill alpha by the per-item `a_style.x` factor, the
    regular scatter draw now runs through the simpler program that never sets
    that constant attribute, and `_drawHoverPoint` inherited its default of 0.
    The dark highlight paint must actually land on the canvas."""
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the hover dot probe")
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0, 2.0, 3.0], [1.0, 4.0, 2.0, 3.0], name="a", color="#8884d8", size=7),
        xy.scatter([0.0, 1.0, 2.0, 3.0], [3.0, 1.0, 4.0, 2.0], name="b", color="#82ca9d", size=7),
        xy.tooltip(),
        width=640,
        height=360,
    )
    document = probe_document(chart, _HOVER_DOT_PROBE)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            chromium, document, Path(td) / "dot.html", "data-xy-hoverdot", label="hover dot"
        )
    assert payload["target"] == [0, 1], payload
    assert payload["before"] < 10, payload
    assert payload["after"] > payload["before"] + 60, payload


# --- Edge cases (§7.3): the probes below share one helper prelude; each
# reports through `data-xy-bandedge` and drives `view._hover` like the ones
# above.

_EDGE_HELPERS = """
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const view = window.__fcProbeView;
  if (!view) throw new Error("no probe view captured");
  view._drawNow(); view._raf = null;
  const sent = []; view.comm = { send: (m) => sent.push(m) };
  const hovers = []; document.addEventListener("xy:hover", (e) => hovers.push(e.detail));
  for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
  const rect = view.canvas.getBoundingClientRect();
  const g0 = view.gpuTraces[0];
  const proj = (x, y, g = g0) => {
    const [px, py] = view._projectDataPoint(g.xAxis, g.yAxis, x, y);
    return [px - view.plot.x, py - view.plot.y];
  };
  const hover = (x, y) => view._hover({ clientX: rect.left + x, clientY: rect.top + y });
  const tip = view.tooltip;
  const cursor = () => view.root.querySelector('[data-xy-slot="tooltip_cursor"]');
  const state = () => ({
    shown: tip.style.display === "block",
    title: tip.querySelector('[data-xy-slot="tooltip_title"]')?.textContent ?? null,
    rows: [...tip.querySelectorAll('[data-xy-slot="tooltip_row"]')].map((r) => r.textContent),
    targets: (view._hoverTargets || []).length,
    cursorShown: !!cursor() && cursor().style.display === "block",
    cursorLeft: cursor() ? parseFloat(cursor().style.left) : null,
    cursorTop: cursor() ? parseFloat(cursor().style.top) : null,
  });
  const done = (obj) => document.body.setAttribute("data-xy-bandedge", JSON.stringify(obj));
"""


def _edge_probe(body: str) -> str:
    return (
        "<script>(async () => { try {"
        + _EDGE_HELPERS
        + body
        + """
  } catch (err) { document.body.setAttribute("data-xy-bandedge-error", String((err && err.stack) || err)); }
})();</script>"""
    )


def _run_edge(chart, body: str, label: str) -> dict:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("headless chromium not found")
    document = probe_document(chart, _edge_probe(body))
    with tempfile.TemporaryDirectory() as td:
        return run_browser_probe(
            chromium, document, Path(td) / "edge.html", "data-xy-bandedge", label=label
        )


_CATS = ["A", "B", "C", "D", "E"]
_PV5 = [4.0, 3.0, 5.0, 2.0, 6.0]
_UV5 = [2.0, 5.0, 1.0, 4.0, 3.0]


def test_browser_grouped_bars_form_one_band_per_category() -> None:
    """Recharts' classic case: a grouped BarChart lists every series of the
    category the pointer is over, from any x inside the group, with one cursor
    on the category centre and the category label as the title."""
    chart = xy.bar_chart(
        xy.bar(_CATS, [_PV5, _UV5], series=["pv", "uv"]),
        xy.tooltip(mode="x"),
        xy.interaction_config(hover=True),
        width=640,
        height=360,
    )
    payload = _run_edge(
        chart,
        """
  const [bx] = proj(1, 0);
  const slots = view.gpuTraces.map((g) => g._cpu.x[1] / (g._cpu.xMeta.scale || 1) + g._cpu.xMeta.offset);
  hover(bx, 8); const centre = state();
  hover(bx - 25, 8); const leftSlot = state();
  hover(bx + 25, 8); const rightSlot = state();
  const [cx] = proj(2, 0);
  hover((bx + cx) / 2 + 2, 8); const pastGap = state();
  done({ slots, centre, leftSlot, rightSlot, pastGap, bx, plotX: view.plot.x, hovers: hovers.length,
         picks: sent.filter((m) => m.type === "pick").length });
""",
        "grouped bars band",
    )
    slots = payload["slots"]
    assert slots[0] < 1.0 < slots[1], slots  # the two slots straddle the category
    for key in ("centre", "leftSlot", "rightSlot"):
        s = payload[key]
        assert s["shown"] is True and s["title"] == "B", (key, s)
        assert s["rows"] == ["pv3", "uv5"], (key, s)
        assert s["cursorShown"] is True, (key, s)
        # One cursor on the category centre (root coordinates), whichever slot
        # the pointer is over.
        assert abs(s["cursorLeft"] - (payload["bx"] + payload["plotX"])) < 1.0, (key, s, payload)
    assert payload["pastGap"]["title"] == "C", payload["pastGap"]
    # Three pointer positions in one band: one hover event, one pick per series.
    assert payload["hovers"] == 2 and payload["picks"] == 4, payload


def test_browser_horizontal_bars_band_along_y() -> None:
    chart = xy.bar_chart(
        xy.bar(_CATS, [_PV5, _UV5], series=["pv", "uv"], orientation="horizontal"),
        xy.tooltip(mode="y"),
        xy.interaction_config(hover=True),
        width=640,
        height=360,
    )
    payload = _run_edge(
        chart,
        """
  const [, by] = proj(0, 1); hover(view.plot.w - 8, by); done({ atB: state(), plotY: view.plot.y, by });
""",
        "horizontal bars band",
    )
    s = payload["atB"]
    assert s["shown"] is True and s["title"] == "B" and s["rows"] == ["pv3", "uv5"], s
    assert s["cursorShown"] is True, s
    assert abs(s["cursorTop"] - (payload["by"] + payload["plotY"])) < 1.0, (s, payload)


def test_browser_band_respects_each_series_own_x_grid() -> None:
    """A series with no point at the band coordinate is omitted, not guessed:
    two series on interleaved grids alternate bands at the midpoints."""
    chart = xy.line_chart(
        xy.line([0, 1, 2, 3, 4, 5, 6], [1, 2, 3, 2, 1, 2, 3], name="whole"),
        xy.line([0.5, 1.5, 2.5, 3.5, 4.5, 5.5], [3, 2, 1, 2, 3, 2], name="half"),
        xy.tooltip(mode="x"),
        width=640,
        height=360,
    )
    payload = _run_edge(
        chart,
        """
  const [x2] = proj(2, 0), [x25] = proj(2.5, 0);
  hover(x2 + 1, 8); const at2 = state();
  hover((x2 + x25) / 2 - 0.6, 8); const beforeMid = state();
  hover((x2 + x25) / 2 + 0.6, 8); const pastMid = state();
  done({ at2, beforeMid, pastMid });
""",
        "interleaved grids",
    )
    assert payload["at2"]["rows"] == ["whole3"] and payload["at2"]["title"] == "2", payload
    assert payload["beforeMid"]["rows"] == ["whole3"], payload
    assert payload["pastMid"]["rows"] == ["half1"] and payload["pastMid"]["title"] == "2.5", payload


def test_browser_band_boundary_is_the_axis_midpoint_on_log_scales() -> None:
    chart = xy.line_chart(
        xy.line([1, 10, 100, 1000], [1, 2, 3, 4], name="s"),
        xy.x_axis(type_="log"),
        xy.tooltip(mode="x"),
        width=640,
        height=360,
    )
    payload = _run_edge(
        chart,
        """
  const [logMid] = proj(Math.sqrt(1000), 0), [linMid] = proj(55, 0);
  hover(logMid - 2, 8); const under = state();
  hover(logMid + 2, 8); const over = state();
  hover(linMid, 8); const linear = state();
  done({ under, over, linear });
""",
        "log band boundary",
    )
    assert payload["under"]["title"] == "10", payload
    assert payload["over"]["title"] == "100", payload
    # The linear midpoint (55) is well past the log midpoint: still 100.
    assert payload["linear"]["title"] == "100", payload


def test_browser_hidden_band_tooltip_keeps_the_hover_contract() -> None:
    chart = xy.line_chart(
        xy.line([0, 1, 2], [1, 2, 3], name="a"),
        xy.tooltip(show=False, mode="x"),
        xy.interaction_config(hover=True),
        width=640,
        height=360,
    )
    payload = _run_edge(
        chart,
        """
  const [x1] = proj(1, 0); hover(x1, 8);
  done({ s: state(), hovers: hovers.map((h) => [(h.points || []).length, h.row && h.row.x]),
         picks: sent.filter((m) => m.type === "pick").length });
""",
        "show=False band",
    )
    s = payload["s"]
    assert s["shown"] is False and s["cursorShown"] is False, s
    assert s["targets"] == 1, s  # active dot state stays, like nearest mode
    assert payload["hovers"] == [[1, 1]] and payload["picks"] == 1, payload


def test_browser_band_survives_context_loss_and_destroy() -> None:
    """The band-dot scratch VAO belongs to one GL context: a restore must not
    bind the dead handle (which made the recovery frame fail its error check
    and stranded the chart), and destroy must delete it."""
    chart = xy.line_chart(
        xy.line([0, 1, 2, 3], [1, 2, 3, 4], name="a"),
        xy.line([0, 1, 2, 3], [4, 3, 2, 1], name="b"),
        xy.tooltip(mode="x"),
        width=640,
        height=360,
    )
    payload = _run_edge(
        chart,
        """
  const [x1] = proj(1, 0); hover(x1, 8); view._drawNow();
  const vao = view._bandDotVao;
  const host = view._glHost;
  const ext = (host ? host.gl : view.gl).getExtension("WEBGL_lose_context");
  if (!ext) throw new Error("WEBGL_lose_context unavailable");
  const waitUntil = async (pred, label) => {
    const deadline = performance.now() + 5000;
    while (!pred()) { if (performance.now() > deadline) throw new Error("timeout " + label); await sleep(20); }
  };
  const lc = view._contextLossCount, rc = view._contextRestoreCount;
  ext.loseContext(); await waitUntil(() => view._contextLossCount >= lc + 1, "loss");
  ext.restoreContext();
  await waitUntil(() => view._contextRestoreCount >= rc + 1 && view.canvas.dataset.xyCtx === "live", "restore");
  const restored = { vaoReplaced: !!view._bandDotVao && view._bandDotVao !== vao, targets: (view._hoverTargets || []).length };
  hover(x1 + 1, 8); view._drawNow();
  const after = { ...state(), glError: view.gl.getError() };
  view.destroy();
  done({ hadVao: !!vao, restored, after, vaoAfterDestroy: view._bandDotVao });
""",
        "band context loss",
    )
    assert payload["hadVao"] is True, payload
    assert payload["restored"]["vaoReplaced"] is True, payload
    assert payload["after"]["shown"] is True and payload["after"]["glError"] == 0, payload
    assert payload["after"]["rows"] == ["a2", "b3"], payload
    assert payload["vaoAfterDestroy"] is None, payload


def test_browser_three_grouped_series_snap_to_the_chain_not_the_pointer() -> None:
    """From the gap after a category the pointer is nearer the *previous*
    category's slot of the far series than to this category's; bar series
    snap to the band chain, so all three slots read as one band."""
    chart = xy.bar_chart(
        xy.bar(_CATS, [_PV5, _UV5, [1.0, 2.0, 3.0, 4.0, 5.0]], series=["pv", "uv", "amt"]),
        xy.tooltip(mode="x"),
        width=640,
        height=360,
    )
    payload = _run_edge(
        chart,
        """
  const [bx] = proj(1, 0), [cx] = proj(2, 0);
  hover(bx - 22, 8); const leftSlotB = state();
  hover((bx + cx) / 2 + 2, 8); const gapIntoC = state();
  hover((bx + cx) / 2 - 2, 8); const gapIntoB = state();
  done({ leftSlotB, gapIntoC, gapIntoB, bx, cx, plotX: view.plot.x });
""",
        "three grouped series",
    )
    assert payload["leftSlotB"]["rows"] == ["pv3", "uv5", "amt2"], payload["leftSlotB"]
    assert payload["gapIntoC"]["title"] == "C", payload["gapIntoC"]
    assert payload["gapIntoC"]["rows"] == ["pv5", "uv1", "amt3"], payload["gapIntoC"]
    assert payload["gapIntoB"]["title"] == "B", payload["gapIntoB"]
    assert payload["gapIntoB"]["rows"] == ["pv3", "uv5", "amt2"], payload["gapIntoB"]
    assert abs(payload["gapIntoC"]["cursorLeft"] - (payload["cx"] + payload["plotX"])) < 1.0, (
        payload
    )
