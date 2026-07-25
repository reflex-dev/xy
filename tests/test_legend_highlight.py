"""Legend entry labels and hover-highlight emphasis.

Python side: a continuous color encoding built from a column name carries that
name onto the wire (`color.label`); `xy.legend(highlight=...)` gates the hover
behavior. There is no generic fallback label — a trace with neither a name nor
a label renders no legend row (matching the static exporters).

Browser side: hovering a legend row dims every other series on the marks
canvas (`_legendDim`), swaps a categorical trace's palette LUT so sibling
categories fade, dims the other legend rows, and restores everything on leave.
Identical unnamed continuous encodings collapse into one row whose hover
emphasizes all backing traces.

Skips (never fails) when no Chromium is available or the headless GL context
can't come up, matching the repo's other browser probes.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from conftest import density_category_chart, probe_document, run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy.export import find_chromium  # noqa: E402


def _data() -> dict[str, np.ndarray]:
    return {
        "x": np.arange(8.0),
        "y": np.arange(8.0),
        "temperature": np.linspace(0.0, 1.0, 8),
    }


def test_continuous_column_name_becomes_channel_label() -> None:
    chart = xy.scatter_chart(xy.scatter("x", "y", data=_data(), color="temperature"))
    trace = chart.figure().traces[0]
    assert trace.color_ch is not None
    assert trace.color_ch.label == "temperature"
    assert trace.color_ch.spec()["label"] == "temperature"


def test_continuous_array_color_ships_no_label() -> None:
    data = _data()
    chart = xy.scatter_chart(xy.scatter("x", "y", data=data, color=data["temperature"]))
    trace = chart.figure().traces[0]
    assert trace.color_ch is not None
    assert trace.color_ch.label is None
    assert "label" not in trace.color_ch.spec()


def test_named_trace_keeps_both_name_and_channel_label() -> None:
    chart = xy.scatter_chart(xy.scatter("x", "y", data=_data(), color="temperature", name="obs"))
    trace = chart.figure().traces[0]
    assert trace.name == "obs"
    assert trace.color_ch.label == "temperature"


def test_legend_highlight_option() -> None:
    data = _data()
    disabled = xy.scatter_chart(xy.scatter("x", "y", data=data), xy.legend(highlight=False))
    assert disabled.figure().legend_options["highlight"] is False
    # Default-on rides implicitly: existing specs stay byte-identical.
    default = xy.scatter_chart(xy.scatter("x", "y", data=data), xy.legend())
    assert "highlight" not in default.figure().legend_options
    with pytest.raises(ValueError):
        xy.legend(highlight="yes")


_HIGHLIGHT_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    let rows = [];
    for (let i = 0; i < 200; i++) {
      rows = [...document.querySelectorAll('[data-xy-slot="legend_item"]')];
      if (rows.length >= 4) break;
      await sleep(25);
    }
    if (rows.length < 4) throw new Error(`expected 4 legend rows, got ${rows.length}`);
    const rowNames = rows.map((row) => row.textContent);
    const byName = (name) => rows.find((row) => row.textContent === name);

    const gradientRow = byName("temperature");
    const gradientSwatchSvg = !!gradientRow.querySelector("svg linearGradient");
    const gradientSymbolFill = gradientRow.querySelector("svg path")?.getAttribute("fill") || "";

    const dims = () => view.gpuTraces.map((g) => g._legendDim ?? null);
    const hover = (row) => row.dispatchEvent(new PointerEvent("pointerenter"));
    const leave = (row) => row.dispatchEvent(new PointerEvent("pointerleave"));

    const alphaRow = byName("alpha");
    hover(alphaRow);
    const hoverAlphaDims = dims();
    const rowOpacities = rows.map((row) => row.style.opacity);
    leave(alphaRow);

    hover(gradientRow);
    const hoverTemperatureDims = dims();
    leave(gradientRow);

    const catRow = byName("A");
    const catTrace = view.gpuTraces[3];
    const lutBefore = catTrace.lut;
    hover(catRow);
    const hoverCategoryDims = dims();
    const lutSwapped = catTrace._legendPrevLut !== undefined && catTrace.lut !== lutBefore;
    leave(catRow);
    const lutRestored = catTrace.lut === lutBefore && catTrace._legendPrevLut === undefined;
    const afterLeaveDims = dims();

    document.body.setAttribute(
      "data-xy-legend-highlight",
      JSON.stringify({
        rowNames,
        gradientSwatchSvg,
        gradientSymbolFill,
        hoverAlphaDims,
        rowOpacities,
        hoverTemperatureDims,
        hoverCategoryDims,
        lutSwapped,
        lutRestored,
        afterLeaveDims,
      })
    );
  } catch (err) {
    document.body.setAttribute(
      "data-xy-legend-highlight-error",
      String((err && err.stack) || err)
    );
  }
})();
</script>
"""


def test_browser_legend_hover_dims_other_series() -> None:
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the legend highlight probe")

    data = _data()
    chart = xy.scatter_chart(
        # Trace 0: named, constant color — plain marker row.
        xy.scatter("x", "y", data=data, name="alpha"),
        # Traces 1+2: identical unnamed continuous encodings — must collapse
        # into ONE "temperature" row that emphasizes both traces on hover.
        xy.scatter("x", "y", data=data, color="temperature"),
        xy.scatter("x", "y", data=data, color="temperature"),
        # Trace 3: categorical — one row per category, LUT-dim on hover.
        xy.scatter(
            "x",
            "y",
            data=data,
            color=np.array(["A", "B", "A", "B", "A", "B", "A", "B"]),
        ),
        # Trace 4: unnamed continuous from a raw array — no name, no label,
        # so it must contribute NO legend row (no generic fallback), while
        # still dimming like any other series when a row is hovered.
        xy.scatter("x", "y", data=data, color=data["temperature"] * 2.0),
        xy.legend(),
        width=520,
        height=340,
    )

    document = probe_document(chart, _HIGHLIGHT_PROBE)

    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "legend_highlight.html"
        payload = run_browser_probe(
            chromium,
            document,
            page,
            "data-xy-legend-highlight",
            label="legend highlight",
        )

    # The unnamed labeled traces surface their column name once; the raw-array
    # trace (no name, no label) gets NO row; categories keep one row each.
    assert payload["rowNames"] == ["alpha", "temperature", "A", "B"], payload
    # The continuous swatch keeps the scatter's marker identity: a symbol
    # path filled with the colormap ramp, not a bare gradient chip.
    assert payload["gradientSwatchSvg"] is True, payload
    assert payload["gradientSymbolFill"].startswith("url(#"), payload

    dim = 0.2
    # The row-less trace 4 still dims with everything else on any hover.
    assert payload["hoverAlphaDims"] == [1, dim, dim, dim, dim], payload
    # The hovered row keeps full opacity; the other rows fade.
    assert payload["rowOpacities"][0] == "", payload
    assert all(opacity == "0.4" for opacity in payload["rowOpacities"][1:]), payload
    # The deduped gradient row backs BOTH continuous traces.
    assert payload["hoverTemperatureDims"] == [dim, 1, 1, dim, dim], payload
    # A category row emphasizes its trace and swaps in the dimmed palette LUT.
    assert payload["hoverCategoryDims"] == [dim, dim, dim, 1, dim], payload
    assert payload["lutSwapped"] is True, payload
    assert payload["lutRestored"] is True, payload
    assert payload["afterLeaveDims"] == [None, None, None, None, None], payload


_DENSITY_HOVER_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    let rows = [];
    for (let i = 0; i < 200; i++) {
      rows = [...document.querySelectorAll('[data-xy-slot="legend_item"]')];
      if (rows.length >= 3) break;
      await sleep(25);
    }
    if (rows.length < 3) throw new Error(`expected 3 category rows, got ${rows.length}`);
    const byName = (name) => rows.find((row) => row.textContent === name);
    const g = view.gpuTraces[0];
    const overlay = g.sampleOverlay;
    if (!overlay) throw new Error("density trace retained no sample overlay");
    const overlayLutBefore = overlay.lut;
    const texBefore = g.density.tex;

    byName("B").dispatchEvent(new PointerEvent("pointerenter"));
    const overlaySwapped =
      overlay._legendPrevLut !== undefined && overlay.lut !== overlayLutBefore;
    // The emphasis lives IN the plane: each cell classified by nearest
    // palette color, sibling-category cells blended toward the background
    // (the LUT-dim rule at cell granularity, §28-recorded approximation) —
    // the hovered category's cells keep their full color, so no uniform
    // recede dims the trace.
    const texSwapped = g.density.tex !== texBefore;
    const surfaceDim = g._legendDim ?? null;
    const overlayDim = overlay._legendDim ?? null;

    byName("B").dispatchEvent(new PointerEvent("pointerleave"));
    const overlayRestored =
      overlay.lut === overlayLutBefore && overlay._legendPrevLut === undefined;
    const texRestored = g.density.tex === texBefore;

    document.body.setAttribute(
      "data-xy-density-hover",
      JSON.stringify({
        overlaySwapped, texSwapped, surfaceDim, overlayDim,
        overlayRestored, texRestored,
      })
    );
  } catch (err) {
    document.body.setAttribute(
      "data-xy-density-hover-error",
      String((err && err.stack) || err)
    );
  }
})();
</script>
"""


def test_browser_density_category_hover_dims_overlay() -> None:
    """Hovering a category row on a density-tier trace must emphasize the
    category through the retained sample overlay's palette LUT — the
    aggregated plane cannot dim sibling categories (§28, recorded), but the
    overlay is a real per-point scatter and can, exactly."""
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the density hover probe")

    chart, _cat, _x, _y = density_category_chart()
    document = probe_document(chart, _DENSITY_HOVER_PROBE)

    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "density_hover.html"
        payload = run_browser_probe(
            chromium,
            document,
            page,
            "data-xy-density-hover",
            label="density hover",
        )

    # The overlay's palette LUT swaps to the dimmed variant on hover...
    assert payload["overlaySwapped"] is True, payload
    # ...and the plane swaps to a per-cell dimmed texture: sibling cells
    # fade toward the background, the hovered category's cells stay vivid —
    # so neither the trace nor the overlay needs a uniform dim.
    assert payload["texSwapped"] is True, payload
    # The hovered trace draws at full opacity — no uniform recede.
    assert payload["surfaceDim"] == 1, payload
    assert payload["overlayDim"] is None, payload
    # Leave restores LUT and texture with no residue.
    assert payload["overlayRestored"] is True, payload
    assert payload["texRestored"] is True, payload


_DARK_BACKDROP_PROBE = """
<script>
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    for (let i = 0; i < 200 && !view.gpuTraces?.[0]?.density?.rgba; i++) await sleep(25);
    const g = view.gpuTraces[0];
    const d = g.density;
    if (!d || !d.rgba) throw new Error("no mean-color plane");
    const palette = g.trace.color.palette;
    // Dim with category B hovered. Sibling cells blend toward the backdrop,
    // and on this DARK page that can only make them darker — a cell that got
    // BRIGHTER is the reported bug (blending toward a white fallback turns
    // siblings into pastels). Asserted over the whole plane rather than one
    // sampled cell, so the probe needs no copy of the classifier.
    const dimmed = view._densityRgbaDimmed(d.rgba, palette, 1);
    // Negative control: the same dim against the white fallback the bug used.
    // It MUST brighten cells — otherwise the assertion below proves nothing.
    const white = view._densityRgbaDimmed(d.rgba, palette, 1, [1, 1, 1, 1]);
    let brightened = 0, darkened = 0, occupied = 0, whiteBrightened = 0;
    for (let i = 0; i < d.rgba.length; i += 4) {
      if (!d.rgba[i + 3]) continue;
      occupied++;
      const before = d.rgba[i] + d.rgba[i + 1] + d.rgba[i + 2];
      const after = dimmed[i] + dimmed[i + 1] + dimmed[i + 2];
      if (after > before) brightened++;
      else if (after < before) darkened++;
      if (white[i] + white[i + 1] + white[i + 2] > before) whiteBrightened++;
    }
    document.body.setAttribute(
      "data-xy-dark-dim",
      JSON.stringify({ occupied, brightened, darkened, whiteBrightened })
    );
  } catch (err) {
    document.body.setAttribute("data-xy-dark-dim-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_density_hover_dims_toward_dark_backdrop() -> None:
    """A chart with no background of its own sits transparent over the page,
    so the hover dim must blend sibling cells toward the page's actual
    backdrop — on a dark page, dimming makes cells DARKER. Blending toward
    a white fallback instead reads as sibling categories brightening into
    pastels (the reported bug)."""
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the dark backdrop probe")

    chart, _cat, _x, _y = density_category_chart()
    document = probe_document(
        chart, _DARK_BACKDROP_PROBE, head="<style>body{background:#0d1117}</style>"
    )

    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "dark_backdrop.html"
        payload = run_browser_probe(
            chromium, document, page, "data-xy-dark-dim", label="dark backdrop dim"
        )

    assert payload["occupied"] > 0, payload
    # Not one sibling cell brightened, and the dim actually did something.
    assert payload["brightened"] == 0, payload
    assert payload["darkened"] > 0, payload
    # ...and the assertion has teeth: the old white fallback DOES brighten.
    assert payload["whiteBrightened"] > 0, payload
