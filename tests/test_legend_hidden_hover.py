"""Legend-hidden category points do not hover (interaction spec §10).

"A hidden series is out of *every* pipeline" — but the CPU hover fallback
(`_nearestCpuIndex`, reached when the GPU pick pass misses) scanned the
unfiltered retained columns for rows `0..g.n` and never consulted the hidden
set. Two defects from one cap: a hidden point still answered hover and showed
its tooltip, and — because `g.n` is the *drawn* count after a category filter
— every visible row shipped at an index >= n became unreachable.

The layout below puts the hidden point's visible neighbour at shipped index 9
of 10 rows (n drops to 7 after hiding the 3-row category), so the fix must both
skip the hidden row and scan past the filtered count to pick it.

Browser probes skip (never fail) without Chromium, like the repo's others.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from conftest import probe_document, run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy.export import find_chromium  # noqa: E402

# (x, y, category) in shipped order. Categories code alphabetically:
# alpha=0, beta=1, gamma=2. Row 3 is the hidden beta point whose only
# neighbour within hover reach is the visible alpha row 9 (0.2 data units =
# ~8 css px on a 520px-wide chart); row 6 is a hidden beta point with no
# visible neighbour within reach at all.
ROWS = [
    (0.5, 9.0, "gamma"),
    (1.0, 1.0, "alpha"),
    (6.5, 7.5, "beta"),
    (5.0, 5.0, "beta"),
    (2.0, 2.0, "alpha"),
    (9.5, 9.0, "gamma"),
    (8.0, 2.0, "beta"),
    (3.0, 3.0, "alpha"),
    (4.0, 0.5, "gamma"),
    (5.2, 5.0, "alpha"),
]
HIDDEN_WITH_NEIGHBOUR = 3
VISIBLE_NEIGHBOUR = 9
HIDDEN_ISOLATED = 6
PLAIN_VISIBLE = 7


def _chart() -> xy.Chart:
    x = np.array([r[0] for r in ROWS])
    y = np.array([r[1] for r in ROWS])
    cats = np.array([r[2] for r in ROWS])
    return xy.scatter_chart(
        xy.scatter(x, y, color=cats),
        xy.x_axis(domain=(0.0, 10.0)),
        xy.y_axis(domain=(0.0, 10.0)),
        xy.legend(),
        width=520,
        height=340,
    )


_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    // Under --dump-dom no frame is ever painted, so a draw scheduled through
    // rAF would never run; a timer stands in for it.
    window.requestAnimationFrame = (cb) => setTimeout(cb, 16);
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
    const g = view.gpuTraces[0];
    const rect = view.canvas.getBoundingClientRect();
    const cssAt = (x, y) => {
      const [lx, ly] = view._projectDataPoint("x", "y", x, y);
      return [lx - view.plot.x, ly - view.plot.y];
    };
    // Drive the full pointer path (pick pass, then CPU fallback) and report
    // what the view settled on; `_hoverAt` alone isolates the fallback.
    const hoverAt = (x, y) => {
      const [cssX, cssY] = cssAt(x, y);
      const fallback = view._hoverAt(cssX, cssY);
      view._hover({ clientX: rect.left + cssX, clientY: rect.top + cssY });
      const target = view._hoverTarget;
      return {
        fallback: fallback ? { index: fallback.index, dist: fallback.dist } : null,
        target: target ? target.index : null,
        tooltip: view.tooltip.style.display === "none" ? null : view.tooltip.textContent,
      };
    };
    const fullN = g.n;
    const before = {
      neighbour: hoverAt(5.0, 5.0),
      isolated: hoverAt(8.0, 2.0),
    };

    click(byName("beta"));
    const hiddenN = g.n;
    const hasVisMap = !!g._visMap;
    const a11yCount = view._a11yGroupCount(g);
    const hidden = {
      neighbour: hoverAt(5.0, 5.0),
      isolated: hoverAt(8.0, 2.0),
      plain: hoverAt(3.0, 3.0),
    };

    click(byName("beta"));
    const restoredN = g.n;
    const restored = { neighbour: hoverAt(5.0, 5.0) };

    document.body.setAttribute(
      "data-xy-hidden-hover",
      JSON.stringify({
        fullN, hiddenN, hasVisMap, a11yCount, restoredN, before, hidden, restored,
        categories: view.spec.traces[0].color.categories,
        legendToggles: sent.filter((m) => m.type === "legend_toggle").length,
      })
    );
  } catch (err) {
    document.body.setAttribute(
      "data-xy-hidden-hover-error",
      String((err && err.stack) || err)
    );
  }
})();
</script>
"""


def test_hidden_category_points_do_not_hover(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    result = run_browser_probe(
        chromium,
        probe_document(_chart(), _PROBE),
        tmp_path / "legend_hidden_hover.html",
        "data-xy-hidden-hover",
        label="legend-hidden hover",
    )
    assert result["categories"] == ["alpha", "beta", "gamma"], result
    assert result["fullN"] == len(ROWS) and result["hiddenN"] == len(ROWS) - 3, result
    assert result["hasVisMap"] is True, result
    assert result["legendToggles"] == 2, result

    # Unfiltered: both beta points hover as themselves.
    before = result["before"]
    assert before["neighbour"]["target"] == HIDDEN_WITH_NEIGHBOUR, result
    assert before["neighbour"]["tooltip"] and "beta" in before["neighbour"]["tooltip"], result
    assert before["isolated"]["target"] == HIDDEN_ISOLATED, result

    hidden = result["hidden"]
    # The pointer on a hidden point must not land on it: the CPU fallback
    # picks the nearest VISIBLE row — shipped index 9, beyond the filtered
    # n of 7 — and the tooltip names that row's category, not "beta".
    assert hidden["neighbour"]["fallback"] is not None, result
    assert hidden["neighbour"]["fallback"]["index"] == VISIBLE_NEIGHBOUR, result
    assert hidden["neighbour"]["fallback"]["dist"] > 0, result
    assert hidden["neighbour"]["target"] == VISIBLE_NEIGHBOUR, result
    assert hidden["neighbour"]["tooltip"] and "alpha" in hidden["neighbour"]["tooltip"], result
    assert "beta" not in hidden["neighbour"]["tooltip"], result
    # A hidden point with nothing visible nearby is simply not there.
    assert hidden["isolated"]["fallback"] is None, result
    assert hidden["isolated"]["target"] is None, result
    assert hidden["isolated"]["tooltip"] is None, result
    # Unrelated visible rows keep hovering as before.
    assert hidden["plain"]["target"] == PLAIN_VISIBLE, result
    assert hidden["plain"]["tooltip"] and "alpha" in hidden["plain"]["tooltip"], result
    # Keyboard traversal keeps hidden rows (§10 accessibility exception) —
    # the pointer fix must not shrink the a11y walk.
    assert result["a11yCount"] == len(ROWS), result

    # Untoggling restores the hidden point to hover.
    assert result["restoredN"] == len(ROWS), result
    assert result["restored"]["neighbour"]["target"] == HIDDEN_WITH_NEIGHBOUR, result
    assert "beta" in result["restored"]["neighbour"]["tooltip"], result


# --------------------------------------------------------------------------
# Scope tripwires for the two paths the CPU hover fallback deliberately does
# NOT guard. Both hold because a categorical color channel is unreachable
# there; if either fact changes, the hover fallback needs the guard and these
# fail pointing at it (js/src/50_chartview.ts `_cpuScanLimit` / `_barHover`,
# interaction spec §10).
# --------------------------------------------------------------------------


def test_bar_marks_cannot_carry_a_categorical_color_channel() -> None:
    """So a bar trace never has category legend rows to toggle.

    `_filterScatterRows` is gated on `colorMode === 2`; the client builds
    category legend rows only for `color.mode === "categorical"`. No
    bar-emitting mark produces one — bar colors resolve to per-series
    constants or direct RGBA — so a bar's legend rows are whole-trace rows,
    which `_hoverAt` already skips via `_legendHidden`. Hence no hidden-row
    test inside `_barHover`.
    """
    from xy._figure import Figure

    builders = {
        "bar": lambda f: f.bar(["A", "B", "C"], [3.0, 5.0, 2.0]),
        "barh": lambda f: f.bar(["A", "B"], [3.0, 5.0], orientation="horizontal"),
        "grouped": lambda f: f.bar(["A", "B"], [[1.0, 2.0], [3.0, 4.0]], series=["a", "b"]),
        "stacked": lambda f: f.bar(
            ["A", "B"], [[1.0, 2.0], [3.0, 4.0]], series=["a", "b"], mode="stacked"
        ),
        "per_series_css": lambda f: f.bar(["A", "B"], [3.0, 5.0], color=["red"]),
        # Numeric RGB(A) per item -> direct_rgba, the other per-row bar paint.
        "direct_paints": lambda f: f.bar(
            ["A", "B"], [3.0, 5.0], color=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        ),
    }
    for label, build in builders.items():
        fig = Figure()
        build(fig)
        for trace in fig.build_payload()[0]["traces"]:
            if "bar" not in trace:
                continue
            mode = (trace.get("color") or {}).get("mode")
            assert mode != "categorical", (label, trace.get("color"))


def test_append_rejects_categorical_color_so_a_live_filter_cannot_go_stale() -> None:
    """So `_visInv` can never be outrun by rows appended under a live filter.

    `_filterScatterRows` (and the `_visInv` the hover scan is bounded by) runs
    only on a categorical color channel; `append_data` rejects exactly those.
    A trace is appendable or category-filterable, never both. Lifting that
    restriction means re-filtering on append — see `_cpuScanLimit`.
    """
    from xy._figure import Figure

    fig = Figure()
    fig.scatter(np.arange(4.0), np.arange(4.0), color=np.array(["a", "b", "a", "b"]))
    fig.build_payload()
    assert fig.traces[0].color_ch.mode == "categorical"
    for kwargs in ({}, {"color": ["a"]}):
        with pytest.raises(ValueError, match="categorical color channels"):
            fig.append(0, [4.0], [4.0], **kwargs)


_BAR_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    window.requestAnimationFrame = (cb) => setTimeout(cb, 16);
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    view.comm = { send: () => {} };
    let rows = [];
    for (let i = 0; i < 200; i++) {
      rows = [...document.querySelectorAll('[data-xy-slot="legend_item"]')];
      if (rows.length >= 3) break;
      await sleep(25);
    }
    if (rows.length < 3) throw new Error(`expected 3 legend rows, got ${rows.length}`);
    const byName = (name) => rows.find((row) => row.textContent === name);
    // Hover the middle of bar `i` of trace `ti`, read from its own retained
    // columns so the probe does not have to model grouped-bar offsets.
    const hoverBar = (ti, i) => {
      const g = view.gpuTraces[ti];
      const cpu = g._cpu;
      const dx = view._decodeValue(cpu.x, cpu.xMeta, i);
      const dy = view._decodeValue(cpu.y, cpu.yMeta, i);
      const [lx, ly] = view._projectDataPoint("x", "y", dx, dy / 2);
      const hit = view._hoverAt(lx - view.plot.x, ly - view.plot.y);
      return hit ? { trace: hit.trace, index: hit.index } : null;
    };
    const middleBefore = hoverBar(1, 1);
    const lastBefore = hoverBar(2, 1);
    // Legend rows for a grouped bar chart are WHOLE-TRACE rows (no category
    // rows exist: bars carry no categorical color channel).
    const catRows = rows.filter((row) => row.dataset.xyLegendCategory !== undefined);
    byName("s2").dispatchEvent(new MouseEvent("click"));
    view._drawNow();
    const middleAfter = hoverBar(1, 1);
    const lastAfter = hoverBar(2, 1);
    const hiddenFlag = !!view.gpuTraces[1]._legendHidden;
    // Bars are not a point-pick mark, so they never enter the GPU pick pass
    // (`pickCount` is never even assigned): `_hoverAt` is the whole hover
    // path for a bar, which is why the hidden-series guard has to live there.
    const g1 = view.gpuTraces[1];
    const cpu1 = g1._cpu;
    const [hx, hy] = view._projectDataPoint(
      "x", "y",
      view._decodeValue(cpu1.x, cpu1.xMeta, 1),
      view._decodeValue(cpu1.y, cpu1.yMeta, 1) / 2,
    );
    const pickAtHidden = view._pickAt(hx - view.plot.x, hy - view.plot.y);
    const pickCountRaw = g1.pickCount ?? null;

    document.body.setAttribute(
      "data-xy-bar-hidden",
      JSON.stringify({
        middleBefore, lastBefore, middleAfter, lastAfter,
        hiddenFlag, pickCountRaw, catRowCount: catRows.length,
        pickAtHidden: pickAtHidden ? pickAtHidden.trace : null,
        legendNames: rows.map((row) => row.textContent),
      })
    );
  } catch (err) {
    document.body.setAttribute(
      "data-xy-bar-hidden-error", String((err && err.stack) || err)
    );
  }
})();
</script>
"""


def test_hidden_bar_series_does_not_hover(tmp_path: Path) -> None:
    """The bar guarantee that does exist: a whole-trace legend hide takes the
    series out of draw, pick and hover, and leaves its neighbours alone."""
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    chart = xy.bar_chart(
        xy.bar(
            x=["A", "B", "C"],
            y=[[3.0, 5.0, 2.0], [4.0, 1.0, 6.0], [2.0, 3.0, 5.0]],
            series=["s1", "s2", "s3"],
        ),
        xy.legend(),
        width=520,
        height=340,
    )
    result = run_browser_probe(
        chromium,
        probe_document(chart, _BAR_PROBE),
        tmp_path / "bar_hidden_hover.html",
        "data-xy-bar-hidden",
        label="hidden bar series hover",
    )
    assert result["legendNames"] == ["s1", "s2", "s3"], result
    assert result["catRowCount"] == 0, result  # whole-trace rows, not category rows
    assert result["middleBefore"] == {"trace": 1, "index": 1}, result
    assert result["lastBefore"] == {"trace": 2, "index": 1}, result
    # Hidden series: out of draw/pick and out of hover. Bars never join the
    # GPU pick pass (no `pointPick`), so `_hoverAt` is the entire hover path.
    assert result["hiddenFlag"] is True, result
    assert result["pickAtHidden"] is None, result
    assert not result["pickCountRaw"], result
    assert result["middleAfter"] != {"trace": 1, "index": 1}, result
    assert result["middleAfter"] is None or result["middleAfter"]["trace"] != 1, result
    # Its neighbour is untouched.
    assert result["lastAfter"] == {"trace": 2, "index": 1}, result
