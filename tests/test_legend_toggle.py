"""Legend click-to-toggle: kernel state, masked re-aggregation, client hide.

Kernel side (§34 predicate; interaction spec §10): the `legend_toggle`
message records hidden traces/categories on the Trace; `density_view`
re-bins under the mask (bypassing the unfiltered pyramid, tagging the
binning label and the reply's `filter` state), drills ship only visible
rows with canonical `shipped_sel`, selections exclude hidden rows, and
`decimate_view` skips hidden traces.

Client side: clicking a legend row hides the series — direct-tier
categorical traces re-filter their vertex buffers locally from retained
CPU columns (`_visMap` translates picks back to shipped rows), whole
traces skip draw+pick, and the kernel is notified either way.

Browser probes skip (never fail) without Chromium, like the repo's others.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from conftest import run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy import channel  # noqa: E402
from xy._figure import Figure  # noqa: E402
from xy.export import find_chromium  # noqa: E402

_RENDER_CALLS = (
    'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
    'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
)


def _density_fig(n: int = 400_000) -> tuple[Figure, np.ndarray]:
    rng = np.random.default_rng(7)
    x = rng.normal(size=n)
    y = rng.normal(size=n)
    cats = np.array(["A", "B", "C"])[rng.integers(0, 3, n)]
    fig = Figure()
    fig.scatter(x, y, color=cats, density=True)
    fig.build_payload()
    return fig, (x, y)


def test_legend_toggle_masks_density_rebin() -> None:
    fig, (x, y) = _density_fig()
    t = fig.traces[0]
    win = (x >= -3) & (x <= 3) & (y >= -3) & (y <= 3)

    base = fig.density_view(0, -3, 3, -3, 3, 512, 384)[0]["traces"][0]
    assert base["visible"] == int(win.sum())
    assert "filter" not in base and "-masked" not in base["binning"]

    reply = channel.handle_message(
        fig, {"type": "legend_toggle", "trace": 0, "category": 1, "hidden": True}
    )
    assert reply is None  # fire-and-forget state sync
    assert t.hidden_categories == {1}

    entry = fig.density_view(0, -3, 3, -3, 3, 512, 384)[0]["traces"][0]
    expect = int((win & (t.color_ch.codes != 1)).sum())
    assert entry["binning"].endswith("-masked")
    assert entry["visible"] == expect
    assert entry["filter"] == {"hidden_categories": [1]}

    # Untoggle restores the unmasked (pyramid-capable) path with no residue.
    channel.handle_message(
        fig, {"type": "legend_toggle", "trace": 0, "category": 1, "hidden": False}
    )
    entry = fig.density_view(0, -3, 3, -3, 3, 512, 384)[0]["traces"][0]
    assert "-masked" not in entry["binning"]
    assert entry["visible"] == int(win.sum())
    assert "filter" not in entry


def test_legend_toggle_drill_ships_only_visible_rows() -> None:
    fig, _ = _density_fig()
    t = fig.traces[0]
    channel.handle_message(
        fig, {"type": "legend_toggle", "trace": 0, "category": 1, "hidden": True}
    )
    entry = fig.density_view(0, -0.02, 0.02, -0.02, 0.02, 512, 384)[0]["traces"][0]
    assert entry["mode"] == "points"
    assert entry["filter"] == {"hidden_categories": [1]}
    # shipped_sel is canonical: the shipped subset must contain no hidden rows,
    # so pick/selection translation stays exact.
    assert len(t.shipped_sel) == entry["visible"]
    assert not np.any(t.color_ch.codes[t.shipped_sel] == 1)


def test_legend_toggle_selection_and_hidden_trace() -> None:
    fig, _ = _density_fig()
    t = fig.traces[0]
    channel.handle_message(
        fig, {"type": "legend_toggle", "trace": 0, "category": 1, "hidden": True}
    )
    sel = fig.select_range(-10, 10, -10, 10)
    assert not np.any(t.color_ch.codes[sel[0]] == 1)
    assert len(sel[0]) == int((t.color_ch.codes != 1).sum())

    channel.handle_message(fig, {"type": "legend_toggle", "trace": 0, "hidden": True})
    assert fig.density_view(0, -3, 3, -3, 3, 512, 384)[0]["traces"] == []
    assert fig.select_range(-10, 10, -10, 10) == {}


def test_legend_toggle_skips_hidden_line_decimation() -> None:
    n = 300_000
    x = np.linspace(0, 1000, n)
    y = np.sin(x / 7.0)
    fig = Figure()
    fig.line(x, y)
    fig.build_payload()
    assert fig.decimate_view(100.0, 200.0, 800)[0]["traces"]
    fig.legend_toggle(0, True)
    assert fig.decimate_view(100.0, 200.0, 800)[0]["traces"] == []


def test_legend_toggle_validation_never_mutates() -> None:
    fig, _ = _density_fig()
    t = fig.traces[0]
    # Out-of-range category, non-bool hidden, and a non-categorical trace all
    # return None (malformed-client contract) and leave state untouched.
    assert (
        channel.handle_message(
            fig, {"type": "legend_toggle", "trace": 0, "category": 99, "hidden": True}
        )
        is None
    )
    assert (
        channel.handle_message(fig, {"type": "legend_toggle", "trace": 0, "hidden": "yes"}) is None
    )
    assert t.hidden_categories == set() and t.hidden is False

    plain = Figure()
    plain.scatter(np.arange(10.0), np.arange(10.0))
    with pytest.raises(ValueError):
        plain.legend_toggle(0, True, category=0)


def test_legend_toggle_option() -> None:
    data = {"x": np.arange(8.0), "y": np.arange(8.0)}
    disabled = xy.scatter_chart(xy.scatter("x", "y", data=data), xy.legend(toggle=False))
    assert disabled.figure().legend_options["toggle"] is False
    default = xy.scatter_chart(xy.scatter("x", "y", data=data), xy.legend())
    assert "toggle" not in default.figure().legend_options
    with pytest.raises(ValueError):
        xy.legend(toggle="yes")


_TOGGLE_PROBE = """
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
    let rows = [];
    for (let i = 0; i < 200; i++) {
      rows = [...document.querySelectorAll('[data-xy-slot="legend_item"]')];
      if (rows.length >= 3) break;
      await sleep(25);
    }
    if (rows.length < 3) throw new Error(`expected 3 legend rows, got ${rows.length}`);
    const byName = (name) => rows.find((row) => row.textContent === name);
    const click = (row) => row.dispatchEvent(new MouseEvent("click"));
    const cat = view.gpuTraces[1];
    const fullN = cat.n;

    // Category toggle: filtered buffers, pick map, kernel notified.
    click(byName("A"));
    const afterHideN = cat.n;
    const hasVisMap = !!cat._visMap;
    let mappedClean = true;
    for (let j = 0; j < cat.n; j++) {
      if (cat._cpu.color[cat._visMap[j]] === 0) mappedClean = false;
    }
    const rowOff = byName("A").dataset.xyLegendOff !== undefined;

    // Hovering a toggled-off row must not emphasize anything.
    byName("A").dispatchEvent(new PointerEvent("pointerenter"));
    const offHoverDims = view.gpuTraces.map((g) => g._legendDim ?? null);
    byName("A").dispatchEvent(new PointerEvent("pointerleave"));

    // Untoggle restores the full buffers.
    click(byName("A"));
    const restoredN = cat.n;
    const visMapCleared = !cat._visMap;

    // Whole-trace toggle: draw+pick skip flag and kernel notification.
    click(byName("alpha"));
    const alphaHidden = !!view.gpuTraces[0]._legendHidden;
    view._renderPick();
    const alphaUnpickable = view.gpuTraces[0].pickCount === 0;
    click(byName("alpha"));
    const alphaRestored = !view.gpuTraces[0]._legendHidden;

    document.body.setAttribute(
      "data-xy-legend-toggle",
      JSON.stringify({
        fullN, afterHideN, hasVisMap, mappedClean, rowOff, offHoverDims,
        restoredN, visMapCleared, alphaHidden, alphaUnpickable, alphaRestored,
        sent,
      })
    );
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-toggle-error",
      String((err && err.stack) || err)
    );
  }
})();
</script>
"""


def test_browser_legend_click_toggles_series() -> None:
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the legend toggle probe")

    codes = np.array(["A", "A", "A", "A", "A", "B", "B", "B"])
    data = {"x": np.arange(8.0), "y": np.arange(8.0)}
    chart = xy.scatter_chart(
        xy.scatter("x", "y", data=data, name="alpha"),
        xy.scatter("x", "y", data=data, color=codes),
        xy.legend(),
        width=520,
        height=340,
    )

    document = chart.to_html()
    render_call = next((call for call in _RENDER_CALLS if call in document), None)
    assert render_call is not None, "to_html render call shape changed; update the probe swap"
    document = document.replace(
        render_call,
        render_call.replace(
            "xy.renderStandalone(", "window.__fcProbeView = xy.renderStandalone(", 1
        ),
        1,
    )
    document = document.replace("</body>", _TOGGLE_PROBE + "\n</body>", 1)

    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "legend_toggle.html"
        payload = run_browser_probe(
            chromium, document, page, "data-xy-legend-toggle", label="legend toggle"
        )

    assert payload["fullN"] == 8 and payload["afterHideN"] == 3, payload
    assert payload["hasVisMap"] is True and payload["mappedClean"] is True, payload
    assert payload["rowOff"] is True, payload
    # Off rows are inert for hover emphasis.
    assert payload["offHoverDims"] == [None, None], payload
    assert payload["restoredN"] == 8 and payload["visMapCleared"] is True, payload
    assert payload["alphaHidden"] is True and payload["alphaUnpickable"] is True, payload
    assert payload["alphaRestored"] is True, payload
    # Kernel stays in sync: every click shipped a legend_toggle message.
    kinds = [
        (m.get("type"), m.get("trace"), m.get("category"), m.get("hidden")) for m in payload["sent"]
    ]
    assert kinds == [
        ("legend_toggle", 1, 0, True),
        ("legend_toggle", 1, 0, False),
        ("legend_toggle", 0, None, True),
        ("legend_toggle", 0, None, False),
    ], payload["sent"]
