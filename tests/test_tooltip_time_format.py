"""Tooltip value formatting (`xy.tooltip(format=...)`, interaction spec §7.4).

`format=` is one grammar for every tooltip value: a strftime pattern on a
time-kinded value, the numeric spec otherwise. A datetime column reaches the
row under its channel alias (``"time"`` -> ``"x"``), so the format has to be
resolvable from either the column name or the channel, and a time value with no
authored format still resolves one — the axis's own ``format=``, else the
pattern its visible span reads best in — instead of falling through to a raw
ISO stamp.

Browser probes drive the real client; they skip (never fail) without Chromium,
like the repo's others.
"""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import probe_document, run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy.export import find_chromium  # noqa: E402

START = dt.datetime(2026, 9, 17, 10, 0)
TIMES = [START + dt.timedelta(minutes=5 * i) for i in range(20)]
YES = [0.10 + 0.04 * i for i in range(20)]
NO = [0.90 - 0.04 * i for i in range(20)]
DATA = {"time": TIMES, "yes": YES, "no": NO}
# The point every probe hovers: index 1, five minutes past the start.
HOVER_INDEX = 1


def _market_chart(**tooltip):
    """A two-series time-axis chart in the shape the report came from: a
    datetime column bound to x on both traces, two probability columns on y."""
    return xy.line_chart(
        xy.step("time", "yes", data=DATA, where="post", name="Yes", color="#8884d8"),
        xy.step("time", "no", data=DATA, where="post", name="No", color="#82ca9d"),
        xy.tooltip(**tooltip),
        xy.interaction_config(hover=True),
        width=640,
        height=360,
    )


def test_tooltip_format_ships_for_table_backed_fields() -> None:
    """The wire carries the authored format under the author's own column
    names, plus the per-trace `sources` map the client resolves them through."""
    chart = _market_chart(
        fields=["time", "yes"],
        format={"time": "%b %d, %Y, %H:%M", "yes": ".0%"},
        labels={"time": "", "yes": "Yes"},
    )
    tooltip = chart.figure().build_payload()[0]["tooltip"]
    assert tooltip["format"] == {"time": "%b %d, %Y, %H:%M", "yes": ".0%"}
    # "time" is bound to x on both traces, "yes" to y on the first one only:
    # that per-trace split is what keeps two series' formats apart.
    assert tooltip["sources"]["time"] == [
        {"trace": 0, "channel": "x"},
        {"trace": 1, "channel": "x"},
    ]
    assert tooltip["sources"]["yes"] == [{"trace": 0, "channel": "y"}]
    assert tooltip["aliases"]["time"] == "x"


# Shared probe boilerplate: capture the view, wait for its CPU columns, and
# expose `withSpec(patch)` — hover one data point under a tooltip spec and
# report the rendered text. `sources`/`aliases` are preserved from the built
# spec, because the column-name lookup resolves through them. Each probe below
# splices its own cases in at CASES and runs only those, so a test never pays
# for a browser launch it does not assert on.
_PROBE_PRELUDE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    view.comm = { send: () => {} };
    for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
    const rect = view.canvas.getBoundingClientRect();
    const g = view.gpuTraces[0];
    const base = JSON.parse(JSON.stringify(view.spec.tooltip || {}));
    const axisFormat = view.axes.x.format;
    const cpu = g._cpu;
    const at = (i) => view._decodeValue(cpu.x, cpu.xMeta || g.xMeta, i);
    const tip = view.tooltip;

    const text = () => ({
      title: tip.querySelector('[data-xy-slot="tooltip_title"]')?.textContent ?? null,
      rows: [...tip.querySelectorAll('[data-xy-slot="tooltip_row"]')].map((r) => r.textContent),
    });
    // Hover the vertex itself: nearest mode only picks near a point, and this
    // probe is about the text, not the hit test. Re-hovering the same point is
    // a no-op for the real client (`_hover` returns on an unchanged hit id), so
    // each spec starts from no hover at all.
    const hoverPoint = (index, yValue) => {
      view._hoverId = -1;
      view._hideTooltip();
      const [px, py] = view._projectDataPoint(g.xAxis, g.yAxis, at(index), yValue);
      view._hover({ clientX: rect.left + px - view.plot.x, clientY: rect.top + py - view.plot.y });
      return text();
    };
    const withSpec = (patch, yValue) => {
      view.spec.tooltip = { ...base, ...patch };
      return hoverPoint(INDEX, yValue === undefined ? YES1 : yValue);
    };

    const out = {};
CASES
    document.body.setAttribute(ATTRIBUTE, JSON.stringify(out));
  } catch (err) {
    document.body.setAttribute(ATTRIBUTE + "-error", String((err && err.stack) || err));
  }
})();
</script>
"""

_FORMAT_CASES = """
    // No format at all: the span-aware default, not an ISO stamp.
    out.bare = withSpec({ format: {} });
    // The authored strftime pattern, keyed by the column name...
    out.byColumn = withSpec({ format: { time: "%b %d, %Y, %H:%M" } });
    // ...and by the channel the column is bound to.
    out.byChannel = withSpec({ format: { x: "%Y/%m/%d %H:%M" } });
    // A numeric spec on a time value still means "as a number" — `%` alone is
    // the number grammar's percent suffix, not a strftime token.
    out.numericOnTime = withSpec({ format: { time: ",.0f" } });
    // The reported repro: a custom field list with labels.
    out.fields = withSpec({
      fields: ["time", "yes"],
      format: { time: "%b %d, %Y, %H:%M", yes: ".0%" },
      labels: { time: "", yes: "Yes" },
    });
    // A listed field with no format of its own: the column reaches the row
    // under its OWN name (`_applySharedTooltipFields`), so the channel behind
    // it is the only route to an axis and its span.
    out.fieldsBare = withSpec({ fields: ["time", "yes"], format: {} });
    // `format=` alone, with no fields and no title, reaches the default rows.
    out.formatOnly = withSpec({ format: { time: "%H:%M", yes: ".1%" } });
    // With nothing authored on the tooltip, the axis's own format wins.
    view.axes.x.format = "%H:%M";
    out.axisFormat = withSpec({ format: {} });
    view.axes.x.format = axisFormat;
"""

_SPAN_CASES = """
    // The default follows the visible span: zoom the x range and re-hover.
    const span = (ms) => {
      const centre = at(INDEX);
      view.view.ranges.x = [centre - ms / 2, centre + ms / 2];
      return withSpec({ format: {} });
    };
    out.spanMonths = span(120 * 864e5);
    out.spanMinutes = span(90 * 6e4);
    out.spanSeconds = span(20 * 1e3);
    out.spanSubSecond = span(400);
"""


def _market_probe(cases: str, attribute: str) -> str:
    """The shared prelude with `cases` spliced in, bound to `attribute`."""
    return (
        _PROBE_PRELUDE.replace("CASES", cases)
        .replace("ATTRIBUTE", f'"{attribute}"')
        .replace("INDEX", str(HOVER_INDEX))
        .replace("YES1", repr(YES[HOVER_INDEX]))
    )


def _run_format_probe(chart, attribute: str, probe: str, label: str) -> dict:
    """Render `chart` with `probe` spliced in and return the JSON the probe
    wrote to `attribute`, skipping only when no browser can be spawned."""
    chromium = find_chromium()
    if not chromium:
        pytest.skip(f"no chromium available for the {label} probe")
    document = probe_document(chart, probe)
    with tempfile.TemporaryDirectory() as td:
        return run_browser_probe(
            chromium, document, Path(td) / "tooltip.html", attribute, label=label
        )


def test_browser_time_values_take_the_strftime_path() -> None:
    """Every way a format can be authored reaches a time value, and every way
    it cannot leaves the value alone: the column name, the channel key, a
    listed field, `format=` by itself, the axis's own pattern — and a numeric
    spec on a time value still means "as a number"."""
    probe = _market_probe(_FORMAT_CASES, "data-xy-tipfmt")
    payload = _run_format_probe(_market_chart(), "data-xy-tipfmt", probe, "tooltip format")

    # A 95-minute window ticks in minutes, so the tooltip reads to the minute.
    assert payload["bare"]["rows"] == ["xSep 17, 10:05", "y0.14"], payload["bare"]
    assert payload["byColumn"]["rows"][0] == "xSep 17, 2026, 10:05", payload["byColumn"]
    assert payload["byChannel"]["rows"][0] == "x2026/09/17 10:05", payload["byChannel"]
    # Epoch milliseconds, grouped — the value, not a date.
    assert payload["numericOnTime"]["rows"][0].startswith("x1,7"), payload["numericOnTime"]
    assert ":" not in payload["numericOnTime"]["rows"][0], payload["numericOnTime"]
    # The reported repro, now formatted: label "" collapses to the value alone.
    assert payload["fields"]["rows"] == ["Sep 17, 2026, 10:05", "Yes14%"], payload["fields"]
    # A listed time field with no format still resolves one.
    assert payload["fieldsBare"]["rows"] == ["timeSep 17, 10:05", "yes0.14"], payload["fieldsBare"]
    # `format=` with no `fields=` reaches the default rows.
    assert payload["formatOnly"]["rows"] == ["x10:05", "y14.0%"], payload["formatOnly"]
    # An axis `format=` is the tooltip's default, so both read alike.
    assert payload["axisFormat"]["rows"][0] == "x10:05", payload["axisFormat"]


def test_browser_time_tooltip_default_follows_the_visible_span() -> None:
    """With nothing authored, a time value reads at the granularity the window
    in view calls for, sharpening as the span narrows."""
    probe = _market_probe(_SPAN_CASES, "data-xy-tipspan")
    payload = _run_format_probe(_market_chart(), "data-xy-tipspan", probe, "tooltip span")

    # Each tier is one granularity finer than the axis labels the same span
    # produces: a months-wide window hovers to the day, a minutes-wide one to
    # the minute (spec §7.4).
    assert payload["spanMonths"]["rows"][0] == "xSep 17, 2026", payload["spanMonths"]
    assert payload["spanMinutes"]["rows"][0] == "xSep 17, 10:05", payload["spanMinutes"]
    assert payload["spanSeconds"]["rows"][0] == "x10:05:00", payload["spanSeconds"]
    # Below a second there is no strftime token for milliseconds, so the ISO
    # stamp — which carries them — stays the honest answer.
    assert payload["spanSubSecond"]["rows"][0].endswith("Z"), payload["spanSubSecond"]


_BAND_FORMAT_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    view.comm = { send: () => {} };
    for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
    const rect = view.canvas.getBoundingClientRect();
    const g = view.gpuTraces[0];
    const base = JSON.parse(JSON.stringify(view.spec.tooltip || {}));
    const cpu = g._cpu;
    const at = (i) => view._decodeValue(cpu.x, cpu.xMeta || g.xMeta, i);
    const tip = view.tooltip;
    const text = () => ({
      title: tip.querySelector('[data-xy-slot="tooltip_title"]')?.textContent ?? null,
      rows: [...tip.querySelectorAll('[data-xy-slot="tooltip_row"]')].map((r) => r.textContent),
    });
    // A band is picked by the x coordinate alone: hover high above every point.
    const hoverBand = (patch) => {
      view.spec.tooltip = { ...base, mode: "x", ...patch };
      // As above: a band re-entered from inside itself keeps its rendered
      // content, so drop the band before each spec.
      view._hoverId = -1;
      view._hideTooltip();
      const [px] = view._projectDataPoint(g.xAxis, g.yAxis, at(INDEX), 0);
      view._hover({ clientX: rect.left + px - view.plot.x, clientY: rect.top + 4 });
      return text();
    };

    const out = {};
    out.bare = hoverBand({ format: {} });
    out.timeByColumn = hoverBand({ format: { time: "%b %d, %Y, %H:%M" } });
    // Two series bind different columns to y; their formats must not blur.
    out.perTrace = hoverBand({ format: { time: "%H:%M", yes: ".0%", no: ".3f" } });
    document.body.setAttribute("data-xy-bandfmt", JSON.stringify(out));
  } catch (err) {
    document.body.setAttribute("data-xy-bandfmt-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_band_title_formats_its_time_coordinate() -> None:
    """A band title is a value like any other: it takes the span default, an
    authored format keyed by the time column — which it only ever sees as the
    channel "x" — and leaves each series' own numeric format intact."""
    probe = _BAND_FORMAT_PROBE.replace("INDEX", str(HOVER_INDEX))
    payload = _run_format_probe(
        _market_chart(mode="x"), "data-xy-bandfmt", probe, "band tooltip format"
    )

    # The band title is the x coordinate, so it takes the same grammar as any
    # other time value — including a format keyed by the column name, which the
    # title only ever sees as the channel "x".
    assert payload["bare"]["title"] == "Sep 17, 10:05", payload["bare"]
    assert payload["timeByColumn"]["title"] == "Sep 17, 2026, 10:05", payload["timeByColumn"]

    per_trace = payload["perTrace"]
    assert per_trace["title"] == "10:05", per_trace
    assert per_trace["rows"] == ["Yes14%", "No0.860"], per_trace


_CHANNEL_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    view.comm = { send: () => {} };
    for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
    const rect = view.canvas.getBoundingClientRect();
    const g = view.gpuTraces[0];
    const base = JSON.parse(JSON.stringify(view.spec.tooltip || {}));
    const cpu = g._cpu;
    const tip = view.tooltip;
    const rows = () =>
      [...tip.querySelectorAll('[data-xy-slot="tooltip_row"]')].map((r) => r.textContent);
    const withSpec = (patch) => {
      view.spec.tooltip = { ...base, ...patch };
      view._hoverId = -1;
      view._hideTooltip();
      const x = view._decodeValue(cpu.x, cpu.xMeta || g.xMeta, INDEX);
      const y = view._decodeValue(cpu.y, cpu.yMeta || g.yMeta, INDEX);
      const [px, py] = view._projectDataPoint(g.xAxis, g.yAxis, x, y);
      view._hover({ clientX: rect.left + px - view.plot.x, clientY: rect.top + py - view.plot.y });
      return rows();
    };

    const out = {};
    // The short channel names `labels=` documents, used as format keys.
    out.shortNames = withSpec({ format: { color: ".1f", size: ".3f" } });
    // The authored column names for the same two channels.
    out.columnNames = withSpec({ format: { revenue: ",.0f", growth: ".1%" } });
    document.body.setAttribute("data-xy-chanfmt", JSON.stringify(out));
  } catch (err) {
    document.body.setAttribute("data-xy-chanfmt-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_format_keys_follow_the_labels_vocabulary() -> None:
    """`format=` takes the same keys `labels=` does: the short channel name or
    the author's own column, resolved against the hovered trace."""
    data = {
        "month": [1.0, 2.0, 3.0, 4.0],
        "revenue": [42000.0, 47000.0, 45000.0, 53000.0],
        "growth": [0.04, 0.12, 0.01, 0.18],
    }
    chart = xy.scatter_chart(
        xy.scatter(x="month", y="revenue", color="revenue", size="growth", data=data),
        xy.tooltip(),
        xy.interaction_config(hover=True),
        width=640,
        height=360,
    )
    probe = _CHANNEL_PROBE.replace("INDEX", "1")
    payload = _run_format_probe(chart, "data-xy-chanfmt", probe, "channel format keys")

    # Rows are x, y, colour, size; the colour and size rows take the format.
    assert payload["shortNames"][2:] == ["color47000.0", "size0.120"], payload["shortNames"]
    assert payload["columnNames"][2:] == ["color47,000", "size12.0%"], payload["columnNames"]


_PER_TRACE_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    view.comm = { send: () => {} };
    for (let i = 0; i < 200 && !(view.gpuTraces[0]._cpu && view.gpuTraces[1]._cpu); i++) {
      await sleep(25);
    }
    const rect = view.canvas.getBoundingClientRect();
    const tip = view.tooltip;
    const hoverTrace = (k) => {
      const g = view.gpuTraces[k];
      const cpu = g._cpu;
      const x = view._decodeValue(cpu.x, cpu.xMeta || g.xMeta, INDEX);
      const y = view._decodeValue(cpu.y, cpu.yMeta || g.yMeta, INDEX);
      view._hoverId = -1;
      view._hideTooltip();
      const [px, py] = view._projectDataPoint(g.xAxis, g.yAxis, x, y);
      view._hover({ clientX: rect.left + px - view.plot.x, clientY: rect.top + py - view.plot.y });
      return [...tip.querySelectorAll('[data-xy-slot="tooltip_row"]')].map((r) => r.textContent);
    };
    document.body.setAttribute("data-xy-pertrace", JSON.stringify({
      across: hoverTrace(0),
      down: hoverTrace(1),
      // The figure-level alias keeps only the first binding; the fix reads the
      // per-trace `sources` entry instead.
      alias: view.spec.tooltip.aliases.t,
      sources: view.spec.tooltip.sources.t,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-pertrace-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_channel_resolves_per_trace_not_per_figure() -> None:
    """One column bound to x on one trace and y on another formats by the
    channel the HOVERED trace binds it to. `aliases` keeps only the first
    binding, so resolving through it formatted the second trace as if it were
    the first — the wrong format, and with it the wrong axis and span."""
    data = {
        "t": TIMES[:6],
        "v": [float(i) for i in range(6)],
        "w": [2.0 * i for i in range(6)],
    }
    chart = xy.line_chart(
        xy.line(x="t", y="v", data=data, name="across"),
        xy.line(x="w", y="t", data=data, name="down"),
        xy.tooltip(fields=["t"], format={"x": "%H:%M", "y": "%b %d, %Y"}),
        xy.interaction_config(hover=True),
        width=640,
        height=360,
    )
    probe = _PER_TRACE_PROBE.replace("INDEX", str(HOVER_INDEX))
    payload = _run_format_probe(chart, "data-xy-pertrace", probe, "per-trace channel")

    assert payload["alias"] == "x", payload
    assert payload["sources"] == [
        {"trace": 0, "channel": "x"},
        {"trace": 1, "channel": "y"},
    ], payload
    # Same column, same tooltip, two traces: x on one, y on the other.
    assert payload["across"] == ["t10:05"], payload["across"]
    assert payload["down"] == ["tSep 17, 2026"], payload["down"]


_POLAR_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    view.comm = { send: () => {} };
    for (let i = 0; i < 200 && !view.gpuTraces[0]._cpu; i++) await sleep(25);
    const rect = view.canvas.getBoundingClientRect();
    const g = view.gpuTraces[0];
    const cpu = g._cpu;
    const base = JSON.parse(JSON.stringify(view.spec.tooltip || {}));
    const tip = view.tooltip;
    // Index 0 sits exactly on the authored 0-radian spoke.
    const withSpec = (patch) => {
      view.spec.tooltip = { ...base, ...patch };
      view._hoverId = -1;
      view._hideTooltip();
      const x = view._decodeValue(cpu.x, cpu.xMeta || g.xMeta, 0);
      const y = view._decodeValue(cpu.y, cpu.yMeta || g.yMeta, 0);
      const [px, py] = view._projectDataPoint(g.xAxis, g.yAxis, x, y);
      view._hover({ clientX: rect.left + px - view.plot.x, clientY: rect.top + py - view.plot.y });
      return [...tip.querySelectorAll('[data-xy-slot="tooltip_row"]')].map((r) => r.textContent);
    };
    document.body.setAttribute("data-xy-polarfmt", JSON.stringify({
      // The angle row is opt-in: naming it keeps the authored spoke label.
      labelled: withSpec({ labels: { x: "Direction" }, format: {} }),
      // An explicit format is an instruction about this channel and wins.
      formatted: withSpec({ labels: { x: "Direction" }, format: { x: ".3f" } }),
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-polarfmt-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_polar_angle_keeps_its_spoke_label_until_a_format_says_otherwise() -> None:
    """An authored `format=` reaches the polar angle row, which used to drop it.
    The spoke label stays the default, though: it is the reason the row is
    readable, and a format was never what asked for radians."""
    import math

    import numpy as np

    theta = np.linspace(0.0, 2.0 * math.pi, 24)
    chart = xy.polar_chart(
        xy.line(theta, 1.0 + 0.5 * np.sin(5.0 * theta), color="#2563eb", width=2.0),
        xy.theta_axis(tick_values=[0.0, math.pi], tick_labels=["north", "south"]),
        xy.tooltip(),
        xy.interaction_config(hover=True),
        width=520,
        height=520,
    )
    probe = _POLAR_PROBE
    payload = _run_format_probe(chart, "data-xy-polarfmt", probe, "polar angle format")

    assert payload["labelled"][0] == "Directionnorth", payload["labelled"]
    # Now a number rather than the label. The hovered angle arrives f32-decoded
    # (§4/§16), so zero can come back as a tiny negative — the point is the
    # grammar it is rendered in, not the last bit.
    angle = payload["formatted"][0]
    assert angle.startswith("Direction"), angle
    assert abs(float(angle.removeprefix("Direction"))) < 1e-3, angle
