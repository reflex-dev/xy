"""Log axes inside one decade show linear-style ticks, not none.

`logTicks` / `_log_ticks` only emitted 1/2/5 x 10^e, so a log axis whose view
sat inside a single decade (any zoom past ~3x) drew no ticks, labels or grid at
all. Renderer-architecture spec §6.1 (Log) now says: when fewer than two decade
ticks fall in range, fall back to `linearTicks` over the span, labelled by the
same `fmtAxis` rules. The exporters share the rule so SVG/PNG/PDF agree with
the browser for the same range.

Three layers: the TS generator via node, the Python generator, and a parity
assertion between them; then a browser probe against the live renderer and
the SVG exporter on the same window. Browser probes skip (never fail)
without Chromium, like the repo's others.
"""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from conftest import probe_document, run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy._svg import _fmt_axis, _fmt_log, _log_ticks  # noqa: E402
from xy.export import find_chromium  # noqa: E402

TICKS_TS = ROOT / "js" / "src" / "30_ticks.ts"
LOG_AXIS = {"scale": "log"}

# Wide ranges (two or more decade ticks in view): the decade ladder, its
# thinned label tier and step 1 — captured from the pre-fix generator, so
# this pins the "byte-identical" promise for the behaviour that was right.
WIDE = {
    (1e-3, 1e3): (
        [
            0.001,
            0.002,
            0.005,
            0.01,
            0.02,
            0.05,
            0.1,
            0.2,
            0.5,
            1,
            2,
            5,
            10,
            20,
            50,
            100,
            200,
            500,
            1000,
        ],
        [0.001, 0.1, 10, 1000],
    ),
    (1, 1e4): (
        [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000],
        [1, 10, 100, 1000, 10000],
    ),
    (0.5, 50): ([0.5, 1, 2, 5, 10, 20, 50], [1, 10]),
    (1, 10): ([1, 2, 5, 10], [1, 10]),
}

# Within-decade ranges: `linearTicks(lo, hi, 6)` positions, every tick
# labelled, step = the nice linear step so `fmtLinear` shares one decimal
# count across the axis (§6.2).
NARROW = {
    (0.3, 0.35): (
        [0.30, 0.31, 0.32, 0.33, 0.34, 0.35],
        0.01,
        ["0.30", "0.31", "0.32", "0.33", "0.34", "0.35"],
    ),
    (2, 3): ([2.0, 2.2, 2.4, 2.6, 2.8, 3.0], 0.2, ["2.0", "2.2", "2.4", "2.6", "2.8", "3.0"]),
    (100, 110): ([100, 102, 104, 106, 108, 110], 2, ["100", "102", "104", "106", "108", "110"]),
    (1e6, 1.5e6): (
        [1.0e6, 1.1e6, 1.2e6, 1.3e6, 1.4e6, 1.5e6],
        1e5,
        ["1.0e6", "1.1e6", "1.2e6", "1.3e6", "1.4e6", "1.5e6"],
    ),
}


def _node_log_ticks(cases: list[tuple[float, float]]) -> list[dict]:
    """Run the TS generator (node imports .ts by file URL) on `cases`."""
    script = f"""
const m = await import({json.dumps(TICKS_TS.as_uri())});
const out = [];
for (const [lo, hi] of {json.dumps(cases)}) {{
  const r = m.logTicks(lo, hi);
  out.push({{
    ticks: r.ticks, labels: r.labels, step: r.step,
    text: r.ticks.map((v) => m.fmtAxis({json.dumps(LOG_AXIS)}, v, r.step)),
    logText: r.ticks.map((v) => m.fmtLog(v)),
  }});
}}
console.log(JSON.stringify(out));
"""
    completed = subprocess.run(
        ["node", "--no-warnings", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(completed.stdout)


def _py_log_ticks(lo: float, hi: float) -> dict:
    ticks, labels, step = _log_ticks(lo, hi)
    return {
        "ticks": ticks,
        "labels": labels,
        "step": step,
        "text": [_fmt_axis(LOG_AXIS, v, step) for v in ticks],
        "logText": [_fmt_log(v) for v in ticks],
    }


def test_ts_wide_ranges_keep_the_decade_ladder() -> None:
    results = _node_log_ticks(list(WIDE))
    for (lo, hi), got in zip(WIDE, results, strict=True):
        ticks, labels = WIDE[(lo, hi)]
        assert got["ticks"] == ticks, (lo, hi, got)
        assert got["labels"] == labels, (lo, hi, got)
        assert got["step"] == 1, (lo, hi, got)


def test_ts_within_decade_falls_back_to_linear_ticks() -> None:
    results = _node_log_ticks(list(NARROW))
    for (lo, hi), got in zip(NARROW, results, strict=True):
        ticks, step, text = NARROW[(lo, hi)]
        assert got["ticks"] == pytest.approx(ticks, rel=1e-9), (lo, hi, got)
        assert got["labels"] == got["ticks"], (lo, hi, got)  # every tick labelled
        assert got["step"] == pytest.approx(step), (lo, hi, got)
        assert got["text"] == text, (lo, hi, got)
        # Distinct labels: the colorbar formats log ticks by magnitude, which
        # collapsed 2.2/2.4/2.6 to "2 2 3" until fmtLog kept significant digits.
        assert len(set(got["logText"])) == len(got["ticks"]), (lo, hi, got)


def test_py_wide_ranges_keep_the_decade_ladder() -> None:
    for (lo, hi), (ticks, labels) in WIDE.items():
        got = _py_log_ticks(lo, hi)
        assert got["ticks"] == pytest.approx(ticks, rel=1e-12), (lo, hi, got)
        assert got["labels"] == pytest.approx(labels, rel=1e-12), (lo, hi, got)
        assert got["step"] == 1.0


def test_py_within_decade_falls_back_to_linear_ticks() -> None:
    for (lo, hi), (ticks, step, text) in NARROW.items():
        got = _py_log_ticks(lo, hi)
        assert got["ticks"] == pytest.approx(ticks, rel=1e-9), (lo, hi, got)
        assert got["labels"] == got["ticks"], (lo, hi, got)
        assert got["step"] == pytest.approx(step), (lo, hi, got)
        assert got["text"] == text, (lo, hi, got)
        assert len(set(got["logText"])) == len(got["ticks"]), (lo, hi, got)


def test_ts_and_py_generators_agree() -> None:
    """Same positions, same step, same label text on both sides — the static
    exports must tick the axis exactly where the browser does."""
    cases = [*WIDE, *NARROW, (0.2, 0.7), (2, 30), (0.5, 5), (3.0, 3.0), *SUBNORMAL]
    js_results = _node_log_ticks(cases)
    for (lo, hi), js in zip(cases, js_results, strict=True):
        py = _py_log_ticks(lo, hi)
        assert py["ticks"] == pytest.approx(js["ticks"], rel=1e-9, abs=0), (lo, hi, js, py)
        assert py["labels"] == pytest.approx(js["labels"], rel=1e-9, abs=0), (lo, hi, js, py)
        assert py["step"] == pytest.approx(js["step"], rel=1e-9), (lo, hi, js, py)
        assert py["text"] == js["text"], (lo, hi, js, py)
        assert py["logText"] == js["logText"], (lo, hi, js, py)
        assert 1 <= len(js["ticks"]) <= 200


# Positive subnormal windows: `(b - a) / target` underflows inside the linear
# fallback (a 1-ulp span / 6 is 0), so it yields nothing; the window's own
# endpoints stand in as the ticks. Both are formatted exponentially.
SUBNORMAL = [(1e-323, 1.5e-323), (5e-324, 1e-323), (2.5e-323, 4e-323)]


def test_subnormal_window_ticks_its_endpoints() -> None:
    js_results = _node_log_ticks(SUBNORMAL)
    for (lo, hi), js in zip(SUBNORMAL, js_results, strict=True):
        py = _py_log_ticks(lo, hi)
        for got in (js, py):
            assert got["ticks"] == [lo, hi], (lo, hi, got)
            assert got["labels"] == [lo, hi], (lo, hi, got)
            assert got["step"] == hi - lo > 0, (lo, hi, got)
            assert len(set(got["text"])) == 2, (lo, hi, got)  # two distinct labels
        assert py["text"] == js["text"], (lo, hi, js, py)


def test_within_decade_always_shows_a_readable_tick_count() -> None:
    """Every within-decade window a zoom can land on gets 3..8 ticks at the
    default target — the failure mode was zero."""
    for lo, hi in [(0.3, 0.35), (2, 3), (100, 110), (1e6, 1.5e6), (7.1, 7.2), (0.011, 0.019)]:
        ticks, _labels, _step = _log_ticks(lo, hi)
        assert 3 <= len(ticks) <= 8, (lo, hi, ticks)
        assert all(lo * (1 - 1e-9) <= v <= hi * (1 + 1e-9) for v in ticks), (lo, hi, ticks)


def _svg_x_tick_texts(svg: str, lo: float, hi: float) -> list[str]:
    root = ET.fromstring(svg)
    out = []
    for node in root.iter():
        if not node.tag.endswith("text"):
            continue
        text = "".join(node.itertext())
        try:
            value = float(text)
        except ValueError:
            continue
        if lo * (1 - 1e-9) <= value <= hi * (1 + 1e-9):
            out.append(text)
    return out


_LOG_ZOOM_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const texts = () => [...view.root.querySelectorAll(
      '[data-xy-label-kind="tick"][data-xy-axis="x"]'
    )].map((el) => el.textContent);
    const wide = texts();
    view._setView({ x0: 0.3, x1: 0.35 }, { request: false });
    view._drawNow();
    const narrow = texts();
    document.body.setAttribute("data-xy-log-zoom", JSON.stringify({ wide, narrow }));
  } catch (err) {
    document.body.setAttribute("data-xy-log-zoom-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_log_axis_zoomed_inside_a_decade_keeps_ticks(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    xs = [0.001 * 10 ** (i / 4) for i in range(25)]
    chart = xy.line_chart(
        xy.line(x=xs, y=[float(i) for i in range(25)]),
        xy.x_axis(type_="log", domain=(1e-3, 1e3)),
        width=480,
        height=320,
    )
    result = run_browser_probe(
        chromium,
        probe_document(chart, _LOG_ZOOM_PROBE),
        tmp_path / "log_zoom.html",
        "data-xy-log-zoom",
        label="log axis zoomed inside a decade",
    )
    # The unzoomed axis labels decades; the zoomed one must still label, and
    # every label must be a distinct value inside the window in order.
    assert "0.001" in result["wide"] and "1000" in result["wide"], result
    narrow = result["narrow"]
    assert 3 <= len(narrow) <= 8, result
    values = [float(t) for t in narrow]
    assert values == sorted(values) and len(set(values)) == len(values), result
    assert all(0.3 <= v <= 0.35 for v in values), result
    # Browser and exporter label the same window identically at the same tick
    # density: the live labels are exactly one of the Python generator's
    # outputs over the densities an axis of this size can ask for.
    py_options = {
        tuple(_fmt_axis(LOG_AXIS, v, step) for v in ticks)
        for ticks, _labels, step in (_log_ticks(0.3, 0.35, target) for target in range(3, 9))
    }
    assert tuple(narrow) in py_options, (narrow, py_options)

    # The SVG export of the same window ticks it the same way (raster shares
    # `axis_ticks`, so PNG/PDF follow).
    svg = xy.line_chart(
        xy.line(x=xs, y=[float(i) for i in range(25)]),
        xy.x_axis(type_="log", domain=(0.3, 0.35)),
        width=480,
        height=320,
    ).to_svg()
    svg_labels = _svg_x_tick_texts(svg, 0.3, 0.35)
    assert 3 <= len(svg_labels) <= 8, svg_labels
    assert tuple(svg_labels) in py_options, (svg_labels, py_options)
