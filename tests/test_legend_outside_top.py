"""`xy.legend(loc="outside top")`: a legend band above the plot that never covers data.

Every in-plot location, `best` included, covers marks when no corner is empty
(stacked areas, many series, bars that reach the axis maximum). The outside-top
band takes its own room instead: the plot shrinks, the legend lays its entries
out in as many columns as fit, and wraps the rest into rows.

The browser probe skips (never fails) when no Chromium is available, matching
the repo's other browser probes; `XY_REQUIRE_BROWSER=1` turns that into a
failure.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from conftest import run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy import _raster, _svg, _validate  # noqa: E402
from xy.export import find_chromium  # noqa: E402

REGIONS = ["North", "South", "East", "West", "Central", "Online", "Wholesale", "Partners"]


def _lines(names, *, loc="outside top", width=520, height=300, title="Chart", **legend):
    months = np.arange(12)
    marks = [xy.line(months, 30 + 5 * i + (2 + i) * months, name=n) for i, n in enumerate(names)]
    return xy.line_chart(
        *marks, xy.legend(loc=loc, **legend), title=title, width=width, height=height
    )


def _work_orders(loc="outside top"):
    """The reported builder chart: stacked horizontal bars that reach the axis max."""
    stores = ["Bismarck", "Fargo", "Grand Forks", "Jamestown", "Minot", "West Fargo"]
    return xy.chart(
        xy.bar(
            stores,
            np.full((len(stores), 4), 5.0),
            series=["Waiting Parts", "In Progress", "Waiting Approval", "Complete"],
            mode="stacked",
            orientation="horizontal",
        ),
        xy.legend(loc=loc),
        title="Work orders by store",
        width=900,
        height=360,
    )


def _chromium() -> str:
    """Chromium for the browser probes: skip without one, fail under XY_REQUIRE_BROWSER."""
    chromium = find_chromium()
    if not chromium:
        if os.environ.get("XY_REQUIRE_BROWSER"):
            pytest.fail("XY_REQUIRE_BROWSER is set but no Chromium installation was found")
        pytest.skip("no chromium available for the outside-top legend probes")
    return chromium


def _layout(chart):
    spec, _blob = chart.figure().build_payload()
    _w, _h, _compact, plot = _svg.layout(spec)
    return spec, plot


# --- vocabulary -----------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    [
        "outside top",
        "Outside Top",
        "outside-top",
        "outside_top",
        "outside upper",
        "outside upper center",
        "outside center upper",
        "outside top center",
    ],
)
def test_outside_top_spellings_canonicalize(spelling: str) -> None:
    assert _validate.legend_loc(spelling, "legend loc") == "outside top"
    assert xy.legend(loc=spelling).loc == "outside top"


@pytest.mark.parametrize(
    "spelling", ["outside", "outside bottom", "outside right", "outside lower"]
)
def test_other_outside_locations_are_refused(spelling: str) -> None:
    with pytest.raises(ValueError, match="not a legend location"):
        xy.legend(loc=spelling)


def test_refusal_lists_outside_top() -> None:
    with pytest.raises(ValueError, match="'outside top'"):
        xy.legend(loc="northeast")


# --- static layout ----------------------------------------------------------------


def test_band_is_reserved_between_title_and_plot() -> None:
    _spec, inside = _layout(_lines(["Revenue", "Gross profit"], loc="upper right"))
    spec, plot = _layout(_lines(["Revenue", "Gross profit"]))
    room = plot["legend_band_h"] + _svg._OUTSIDE_LEGEND_GAP
    assert plot["y"] == pytest.approx(inside["y"] + room)
    assert plot["h"] == pytest.approx(inside["h"] - room)
    # The band starts where the title band ends, and the title is lifted over it.
    assert plot["legend_band_y"] == pytest.approx(inside["y"])
    assert plot["y"] - plot["top_axis_room"] == pytest.approx(plot["legend_band_y"])
    # The legend box is drawn in the band, entirely above the plot.
    box = _svg._legend_layout(
        _svg.legend_items(spec["traces"]), plot, _svg.legend_options_with_slot(spec, spec["legend"])
    )
    assert box["y"] == pytest.approx(plot["legend_band_y"])
    assert box["y"] + box["box_h"] <= plot["y"] - _svg._OUTSIDE_LEGEND_GAP + 1e-6
    assert box["visible_count"] == 2
    assert box["names"] == ["Revenue", "Gross profit"]


def test_entries_wrap_into_rows_without_ellipsizing() -> None:
    spec, wide = _layout(_lines(REGIONS, width=900))
    _spec, narrow = _layout(_lines(REGIONS, width=420))
    assert wide["legend_band_ncols"] == len(REGIONS)
    assert 1 < narrow["legend_band_ncols"] < len(REGIONS)
    # More rows cost more band height, never hidden entries.
    assert narrow["legend_band_h"] > wide["legend_band_h"]
    narrow_spec, _ = _layout(_lines(REGIONS, width=420))
    box = _svg._legend_layout(
        _svg.legend_items(narrow_spec["traces"]),
        narrow,
        _svg.legend_options_with_slot(narrow_spec, narrow_spec["legend"]),
    )
    assert box["visible_count"] == len(REGIONS)
    assert box["names"] == REGIONS


def test_one_column_when_a_label_is_wide() -> None:
    names = ["Monthly recurring revenue (USD)", "Customer acquisition cost (USD)"]
    _spec, plot = _layout(_lines(names, width=320, height=220))
    assert plot["legend_band_ncols"] == 1


def test_band_never_covers_the_reported_stacked_bar_chart() -> None:
    _spec, plot = _layout(_work_orders())
    assert plot["legend_band_ncols"] == 4
    assert plot["legend_band_y"] + plot["legend_band_h"] < plot["y"]


@pytest.mark.parametrize(
    "chart",
    [
        pytest.param(lambda: _lines(["a", "b"], loc="upper right"), id="in-plot"),
        pytest.param(lambda: _lines(["a", "b"], loc="best"), id="best"),
        pytest.param(lambda: _lines(["a", "b"], anchor=(0.5, 1.2)), id="anchored"),
        pytest.param(
            lambda: xy.line_chart(
                xy.line([0, 1], [0, 1], name="a"), xy.legend(show=False, loc="outside top")
            ),
            id="hidden",
        ),
        pytest.param(
            lambda: xy.line_chart(xy.line([0, 1], [0, 1]), xy.legend(loc="outside top")),
            id="no-entries",
        ),
    ],
)
def test_no_band_when_nothing_should_claim_one(chart) -> None:
    _spec, plot = _layout(chart())
    assert "legend_band_w" not in plot


def test_polar_keeps_its_gutter() -> None:
    chart = xy.polar_chart(
        xy.line([0, 90, 180], [1, 2, 1], name="a"),
        xy.line([0, 90, 180], [2, 1, 2], name="b"),
        xy.legend(loc="outside top"),
    )
    _spec, plot = _layout(chart)
    assert "legend_band_w" not in plot
    assert "legend_box_w" in plot


def test_clip_rect_includes_the_band() -> None:
    _spec, plot = _layout(_lines(["Revenue", "Gross profit"]))
    _x, y, _w, h = _svg.legend_clip_rect(plot)
    assert y == pytest.approx(plot["legend_band_y"])
    assert y + h == pytest.approx(plot["y"] + plot["h"])


def test_svg_and_png_exports_draw_the_band_legend(tmp_path: Path) -> None:
    chart = _work_orders()
    svg = chart.to_svg()
    for name in ("Waiting Parts", "In Progress", "Waiting Approval", "Complete"):
        assert f">{name}</text>" in svg
    png = tmp_path / "band.png"
    chart.to_png(str(png))
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# --- live browser -------------------------------------------------------------------

_RENDER_CALLS = (
    'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
    'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
)

_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const read = () => {
      const legend = document.querySelector('[data-xy-legend-band="top"]');
      if (!legend) throw new Error("outside-top legend never rendered");
      const root = view.root.getBoundingClientRect();
      const box = legend.getBoundingClientRect();
      const canvas = view.canvas.getBoundingClientRect();
      const title = document.querySelector('[data-xy-slot="title"]');
      const titleBox = title ? title.getBoundingClientRect() : null;
      const labels = [...legend.querySelectorAll('[data-xy-slot="legend_label"]')];
      const rowTops = new Set(labels.map((label) => Math.round(label.getBoundingClientRect().top)));
      return {
        columns: Number(legend.dataset.xyLegendColumns),
        rows: rowTops.size,
        // A label that wraps under its own swatch makes its row taller than one line.
        wrappedLabels: labels.filter((label) => label.getBoundingClientRect().height > 20).length,
        legendBottomToCanvasTop: canvas.top - box.bottom,
        titleBottomToLegendTop: titleBox ? box.top - titleBox.bottom : null,
        withinRoot: box.left >= root.left - 1 && box.right <= root.right + 1 && box.top >= root.top - 1,
        scrolls: legend.scrollHeight > legend.clientHeight + 1,
      };
    };
    const initial = read();
    const host = view.root.parentElement;
    host.style.width = "420px";
    view.root.style.width = "420px";
    view.fluid = true;
    view._resize(420, view.size.h);
    view._drawNow();
    view._raf = null;
    const narrow = read();
    document.body.setAttribute("data-xy-outside-top", JSON.stringify({ initial, narrow }));
  } catch (err) {
    document.body.setAttribute("data-xy-outside-top-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_band_never_overlaps_the_plot_and_rewraps_on_resize() -> None:
    chromium = _chromium()
    chart = _lines(REGIONS, width=900, height=360)
    _spec, plot = _layout(chart)
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
    document = document.replace("</body>", _PROBE + "\n</body>", 1)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            chromium,
            document,
            Path(td) / "outside_top.html",
            "data-xy-outside-top",
            label="outside-top legend probe",
        )
    initial, narrow = payload["initial"], payload["narrow"]
    # Same column count as the static export: one row of eight at 900 px.
    assert initial["columns"] == plot["legend_band_ncols"] == len(REGIONS), payload
    assert initial["rows"] == 1, payload
    # Narrowing re-wraps into more rows rather than ellipsizing or scrolling.
    assert 1 < narrow["columns"] < len(REGIONS), payload
    assert narrow["rows"] > 1, payload
    for state in (initial, narrow):
        assert state["legendBottomToCanvasTop"] >= 0, payload
        assert state["titleBottomToLegendTop"] >= 0, payload
        assert state["withinRoot"], payload
        assert not state["scrolls"], payload
        assert state["wrappedLabels"] == 0, payload


# --- `best` falls back to the band when every in-plot position covers data ----------


def _legend(chart):
    spec, _blob = chart.figure().build_payload()
    return spec, spec["legend"]


def test_best_moves_outside_when_no_corner_is_empty() -> None:
    spec, legend = _legend(_work_orders(loc="best"))
    assert legend["loc"] == "outside top"
    # A band legend is exact: `auto_loc` only ever ships with an in-plot `loc`,
    # so the live best pass never drags it back over the bars.
    assert "auto_loc" not in legend
    _w, _h, _compact, plot = _svg.layout(spec)
    assert plot["legend_band_ncols"] == 4
    assert plot["legend_band_y"] + plot["legend_band_h"] < plot["y"]


def test_best_stays_inside_when_a_corner_is_empty() -> None:
    _spec, legend = _legend(_lines(["Revenue", "Gross profit"], loc="best"))
    assert legend["loc"] == "upper left"
    assert legend["auto_loc"] == "best"
    assert legend["auto_outside"] == "top"


def test_best_outside_fallback_reaches_svg_and_png(tmp_path: Path) -> None:
    chart = _work_orders(loc="best")
    spec, _legend_spec = _legend(chart)
    _w, _h, _compact, plot = _svg.layout(spec)
    svg = chart.to_svg()
    assert ">Waiting Parts</text>" in svg
    # Every legend label is drawn in the band, above the band-shrunk plot.
    for name in ("Waiting Parts", "In Progress", "Waiting Approval", "Complete"):
        match = re.search(rf'<text x="[0-9.]+" y="([0-9.]+)"[^>]*>{name}</text>', svg)
        assert match, name
        assert float(match.group(1)) < plot["y"], (name, match.group(1), plot["y"])
    png = tmp_path / "best.png"
    chart.to_png(str(png))
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize(
    "chart",
    [
        pytest.param(lambda: _work_orders(loc="upper right"), id="concrete-loc"),
        pytest.param(
            lambda: xy.chart(
                xy.bar(["a", "b"], [[1.0, 1.0], [1.0, 1.0]], series=["s", "t"], mode="stacked"),
                xy.legend(loc="best", anchor=(0.5, 0.5)),
            ),
            id="anchored",
        ),
        pytest.param(
            lambda: xy.polar_chart(
                xy.line([0, 90, 180, 270, 360], [1, 1, 1, 1, 1], name="a"),
                xy.line([0, 90, 180, 270, 360], [0.5, 0.5, 0.5, 0.5, 0.5], name="b"),
                xy.legend(loc="best"),
            ),
            id="polar",
        ),
    ],
)
def test_best_never_moves_authored_or_polar_legends_outside(chart) -> None:
    _spec, legend = _legend(chart())
    assert legend["loc"] != "outside top"


def test_pyplot_best_keeps_matplotlib_in_plot_semantics() -> None:
    from xy import pyplot as plt

    figure = plt.figure()
    axes = figure.add_subplot(1, 1, 1)
    stores = np.arange(6)
    left = np.zeros(6)
    for name in ["Waiting Parts", "In Progress", "Waiting Approval", "Complete"]:
        axes.barh(stores, np.full(6, 5.0), left=left, label=name)
        left = left + 5.0
    axes.legend(loc="best")
    spec, _blob = axes._build_chart(640, 480).figure().build_payload()
    plt.close(figure)
    assert spec["legend"]["loc"] != "outside top"
    assert "auto_outside" not in spec["legend"]


def test_browser_best_fallback_uses_the_band() -> None:
    chromium = _chromium()
    chart = _work_orders(loc="best")
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
    document = document.replace("</body>", _PROBE + "\n</body>", 1)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            chromium,
            document,
            Path(td) / "best_outside.html",
            "data-xy-outside-top",
            label="best-to-outside legend probe",
        )
    for state in (payload["initial"], payload["narrow"]):
        assert state["legendBottomToCanvasTop"] >= 0, payload
        assert state["wrappedLabels"] == 0, payload
    assert payload["initial"]["columns"] == 4, payload


# --- review findings (PR 544) -------------------------------------------------------------

LONG_NAMES = [f"Customer segment number {i} revenue (USD)" for i in range(8)]


def _band_box(spec, plot):
    return _svg._legend_layout(
        _svg.legend_items(spec["traces"]), plot, _svg.legend_options_with_slot(spec, spec["legend"])
    )


def test_band_height_is_capped_so_a_tall_legend_cannot_push_the_plot_off_canvas() -> None:
    spec, plot = _layout(_lines(LONG_NAMES, width=320, height=200))
    cap = _svg._OUTSIDE_LEGEND_MAX_FRACTION * 200
    assert plot["legend_band_h"] <= cap + 1e-6
    assert plot["y"] + plot["h"] <= 200
    box = _band_box(spec, plot)
    # Static files cannot scroll: rows past the cap are dropped, never drawn over the plot.
    assert 0 < box["visible_count"] < len(LONG_NAMES)
    assert box["y"] + box["box_h"] <= plot["y"]


def test_band_cap_still_keeps_one_row() -> None:
    # 20 px rows on a 96 px card: the 30 % cap (28.8 px) is under one row, and
    # the row still shows because the height budget has room for it.
    months = np.arange(12)
    chart = xy.line_chart(
        xy.line(months, months, name="Revenue"),
        xy.line(months, months + 1, name="Gross profit"),
        xy.legend(loc="outside top", style={"font-size": "20px"}),
        width=320,
        height=96,
        padding=[0, 0, 0, 0],
    )
    _spec, plot = _layout(chart)
    assert plot["legend_band_h"] > plot["legend_band_cap"], plot
    assert plot["legend_band_h"] <= plot["legend_band_budget"], plot
    assert plot["y"] + plot["h"] <= 96 + 1e-6, plot


def _hole_chart(width: int, height: int):
    """Dense points everywhere except a small empty upper-left square."""
    grid = np.linspace(0.0, 1.0, 60)
    xs, ys = np.meshgrid(grid, grid)
    keep = ~((xs < 0.22) & (ys > 0.78))
    return xy.scatter_chart(
        xy.scatter(xs[keep], ys[keep], name="points", size=3),
        xy.scatter(xs[keep][:5], ys[keep][:5], name="more", size=3),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
        width=width,
        height=height,
    )


def test_export_at_another_size_reconsiders_a_best_band() -> None:
    # The hole is too small for the legend on a 320x200 card but not at 1400x900.
    assert _legend(_hole_chart(320, 200))[1]["loc"] == "outside top"
    assert _legend(_hole_chart(1400, 900))[1]["loc"] == "upper left"
    figure = _hole_chart(320, 200).figure()
    spec, _blob, _columns = _raster._export_payload(figure, 1400, 900, None)
    assert spec["legend"]["loc"] == "upper left"


def test_export_keeps_the_band_column_count_for_short_labels() -> None:
    spec, plot = _layout(_lines(["A", "B", "C", "D"], width=300, height=220))
    assert plot["legend_band_ncols"] == 4
    assert _band_box(spec, plot)["ncols"] == 4


_STATIC_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const legend = document.querySelector('[data-xy-legend-band="top"]');
    if (!legend) throw new Error("outside-top legend never rendered");
    const root = view.root.getBoundingClientRect();
    const box = legend.getBoundingClientRect();
    const canvas = view.canvas.getBoundingClientRect();
    document.body.setAttribute("data-xy-band-static", JSON.stringify({
      columns: Number(legend.dataset.xyLegendColumns),
      legendHeight: box.height,
      legendBottomToCanvasTop: canvas.top - box.bottom,
      canvasBottomToRootBottom: root.bottom - canvas.bottom,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-band-static-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def _static_probe(chart, name: str) -> dict:
    chromium = _chromium()
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
    document = document.replace("</body>", _STATIC_PROBE + "\n</body>", 1)
    with tempfile.TemporaryDirectory() as td:
        return run_browser_probe(
            chromium, document, Path(td) / f"{name}.html", "data-xy-band-static", label=name
        )


def test_browser_band_height_is_capped() -> None:
    payload = _static_probe(_lines(LONG_NAMES, width=320, height=200), "band_cap")
    assert payload["legendHeight"] <= _svg._OUTSIDE_LEGEND_MAX_FRACTION * 200 + 1, payload
    assert payload["legendBottomToCanvasTop"] >= 0, payload
    assert payload["canvasBottomToRootBottom"] >= 0, payload


def test_browser_columns_include_slot_padding() -> None:
    # At 534 px the default padding fits five columns and a 2em slot padding four.
    months = np.arange(12)
    chart = xy.line_chart(
        *[xy.line(months, months + i, name=n) for i, n in enumerate(REGIONS)],
        xy.legend(loc="outside top"),
        styles={"legend": {"padding": "2em"}},
        width=534,
        height=320,
    )
    _spec, plot = _layout(chart)
    assert plot["legend_band_ncols"] == 4
    payload = _static_probe(chart, "band_slot_padding")
    assert payload["columns"] == plot["legend_band_ncols"], payload


_DETACHED_PROBE = """
<script>
(async () => {
  try {
    const host = document.createElement("div");
    const view = xy.renderStandalone(host, spec, window.__fcBuf);
    const estimated = view._legendBand ? view._legendBand.h : null;
    // Record the canvas size the shared GL host is asked to present.
    const presented = [];
    if (view._glHost) {
      const render = view._glHost.render.bind(view._glHost);
      view._glHost.render = (owner, present, w, h, frame) => {
        presented.push([w, h]);
        return render(owner, present, w, h, frame);
      };
    }
    document.body.appendChild(host);
    view._drawNow();
    view._raf = null;
    const legend = host.querySelector('[data-xy-legend-band="top"]');
    if (!legend) throw new Error("outside-top legend never rendered");
    const box = legend.getBoundingClientRect();
    const canvas = view.canvas.getBoundingClientRect();
    document.body.setAttribute("data-xy-band-detached", JSON.stringify({
      estimated,
      reserved: view._legendBand ? view._legendBand.h : null,
      measured: legend.offsetHeight,
      natural: legend.scrollHeight,
      presented,
      canvas: [view.canvas.width, view.canvas.height],
      legendBottomToCanvasTop: canvas.top - box.bottom,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-band-detached-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_detached_chart_remeasures_the_band_when_it_connects() -> None:
    # Built before its node is in the document, the band can only use the
    # formula estimate; the first connected frame must lay out again from the
    # measured box, or the taller live legend overlaps the plot.
    chromium = _chromium()
    document = _lines(REGIONS, width=520, height=320).to_html()
    render_call = next((call for call in _RENDER_CALLS if call in document), None)
    assert render_call is not None, "to_html render call shape changed; update the probe swap"
    # Keep a copy of the payload for the detached view, and skip the page's own chart.
    document = document.replace(render_call, "window.__fcBuf = buf.slice(0);", 1)
    document = document.replace("</body>", _DETACHED_PROBE + "\n</body>", 1)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            chromium,
            document,
            Path(td) / "band_detached.html",
            "data-xy-band-detached",
            label="detached outside-top legend probe",
        )
    # The detached estimate also capped the box, so the stale reservation shows
    # as a clipped, scrolling legend rather than an overlap.
    assert payload["natural"] <= payload["measured"] + 1, payload
    assert payload["reserved"] == pytest.approx(payload["measured"], abs=1), payload
    assert payload["legendBottomToCanvasTop"] >= 0, payload
    # The first connected frame lays out again; the shared host must present
    # at the size the frame drew, not the detached size.
    assert payload["presented"], payload
    assert payload["presented"][-1] == payload["canvas"], payload


@pytest.mark.parametrize("key", ["font_size", "font-size", "fontSize"])
def test_static_legend_honors_every_font_size_spelling(key: str) -> None:
    # The browser applies all three; the exporters read only `fontSize`, so a
    # snake_case or kebab-case slot font sized the band (and drew the labels)
    # at the 11 px default while the browser used 20 px.
    months = np.arange(12)
    chart = xy.line_chart(
        *[xy.line(months, months + i, name=n) for i, n in enumerate(REGIONS)],
        xy.legend(loc="outside top"),
        styles={"legend": {key: "20px"}},
        width=520,
        height=320,
    )
    spec, plot = _layout(chart)
    assert _band_box(spec, plot)["font_size"] == 20.0
    reference_spec, reference = _layout(
        xy.line_chart(
            *[xy.line(months, months + i, name=n) for i, n in enumerate(REGIONS)],
            xy.legend(loc="outside top"),
            styles={"legend": {"fontSize": "20px"}},
            width=520,
            height=320,
        )
    )
    assert plot["legend_band_ncols"] == reference["legend_band_ncols"]


def test_band_cap_keeps_one_row_with_a_tall_swatch() -> None:
    # Rows are counted with `line_h`, which a tall `handleheight` swatch raises
    # above `text_h + row_gap`; the one-row floor must use the same pitch.
    named = [{"name": f"Series {i}"} for i in range(6)]
    plot = {
        "x": 0.0,
        "y": 0.0,
        "w": 120.0,
        "h": 300.0,
        "legend_band_x": 0.0,
        "legend_band_y": 0.0,
        "legend_band_w": 120.0,
        "legend_band_h": 0.0,
        "legend_band_ncols": 1,
        "legend_band_cap": 1.0,
    }
    box = _svg._legend_layout(named, plot, {"loc": "outside top", "handleheight": 3.0})
    assert box["visible_count"] == 1


# --- streamed placement changes (PR 544 review) -------------------------------------

_APPEND_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    if (!view) throw new Error("no probe view captured");
    view._drawNow();
    view._raf = null;
    const before = { band: !!view._legendBand, plotY: view.plot.y };
    const buffers = window.__xyAppendBuffers.map((b64) => {
      const bin = atob(b64);
      const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
      return out.buffer;
    });
    view._applyAppend(window.__xyAppendMsg, buffers);
    view._drawNow();
    view._raf = null;
    const legend = view.root.querySelector('[data-xy-legend-band="top"]');
    const canvas = view.canvas.getBoundingClientRect();
    document.body.setAttribute("data-xy-append-band", JSON.stringify({
      before,
      loc: view.spec.legend && view.spec.legend.loc,
      band: !!view._legendBand,
      mounted: !!legend,
      legends: view.root.querySelectorAll("[data-xy-legend-loc]").length,
      plotY: view.plot.y,
      plotH: view.plot.h,
      legendBottomToCanvasTop: legend ? canvas.top - legend.getBoundingClientRect().bottom : null,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-append-band-error", String((err && err.stack) || err));
  }
})();
</script>
"""


_PLOT_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    view._raf = null;
    document.body.setAttribute("data-xy-plot-rect", JSON.stringify({
      band: !!view._legendBand, y: view.plot.y, h: view.plot.h,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-plot-rect-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def _streamed_points():
    return xy.scatter_chart(
        xy.scatter([0.5], [0.5], name="Points"),
        xy.x_axis(domain=(0, 1)),
        xy.y_axis(domain=(0, 1)),
        xy.legend(loc="best"),
        width=600,
        height=300,
    )


def test_append_that_resolves_outside_top_mounts_the_band() -> None:
    # An append re-resolves loc="best"; when the new data covers every inside
    # slot the payload says "outside top", and the mounted chart must move its
    # legend into the band exactly as a fresh render of the same data does.
    import base64
    import json

    from conftest import probe_document
    from xy.interaction import append_data

    chromium = _chromium()
    fig = _streamed_points().figure()
    document = probe_document(fig, _APPEND_PROBE)
    grid = np.linspace(0.0, 1.0, 30)
    gx, gy = np.meshgrid(grid, grid)
    msg, buffers = append_data(fig, fig.traces[0].id, gx.ravel(), gy.ravel())
    assert msg["spec"]["legend"]["loc"] == "outside top"
    payload_js = (
        "<script>window.__xyAppendMsg = "
        + json.dumps(msg)
        + "; window.__xyAppendBuffers = "
        + json.dumps([base64.b64encode(bytes(b)).decode() for b in buffers])
        + ";</script>"
    )
    document = document.replace("<script", payload_js + "<script", 1)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            chromium,
            document,
            Path(td) / "append_band.html",
            "data-xy-append-band",
            label="streamed outside-top legend probe",
        )
        # The same data rendered fresh (the figure now holds the appended rows).
        fresh = run_browser_probe(
            chromium,
            probe_document(fig, _PLOT_PROBE),
            Path(td) / "fresh_band.html",
            "data-xy-plot-rect",
            label="fresh outside-top legend probe",
        )
    assert payload["before"]["band"] is False, payload
    assert payload["loc"] == "outside top", payload
    assert payload["band"] and payload["mounted"], payload
    assert payload["legends"] == 1, payload  # the old in-plot box is gone
    assert payload["legendBottomToCanvasTop"] >= 0, payload
    assert fresh["band"], fresh
    assert payload["plotY"] == pytest.approx(fresh["y"], abs=1), (payload, fresh)
    assert payload["plotH"] == pytest.approx(fresh["h"], abs=1), (payload, fresh)


# --- band budget on short charts (PR 544 review) ----------------------------------

_SHORT_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    view._raf = null;
    const root = view.root.getBoundingClientRect();
    const canvas = view.canvas.getBoundingClientRect();
    document.body.setAttribute("data-xy-short-band", JSON.stringify({
      loc: view.spec.legend && view.spec.legend.loc,
      band: view._legendBand ? view._legendBand.h : 0,
      canvasBottomToRootBottom: root.bottom - canvas.bottom,
      plot: [view.plot.y, view.plot.h],
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-short-band-error", String((err && err.stack) || err));
  }
})();
</script>
"""


@pytest.mark.parametrize("loc", ["best", "outside top"])
def test_static_band_never_pushes_the_plot_off_a_short_chart(loc: str) -> None:
    chart = _lines(REGIONS, width=320, height=100, loc=loc)
    _spec, plot = _layout(chart)
    assert plot["y"] + plot["h"] <= 100 + 1e-6, plot


def test_best_does_not_fall_back_to_a_band_that_cannot_hold_a_row() -> None:
    spec, _plot = _layout(_lines(REGIONS, width=320, height=100, loc="best"))
    assert spec["legend"]["loc"] != "outside top", spec["legend"]


@pytest.mark.parametrize("loc", ["best", "outside top"])
def test_browser_band_never_pushes_the_plot_off_a_short_chart(loc: str) -> None:
    from conftest import probe_document

    chart = _lines(REGIONS, width=320, height=100, loc=loc)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            _chromium(),
            probe_document(chart, _SHORT_PROBE),
            Path(td) / "short_band.html",
            "data-xy-short-band",
            label="short-chart outside-top legend probe",
        )
    assert payload["canvasBottomToRootBottom"] >= -0.5, payload


_LOST_APPEND_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    view._raf = null;
    const sizes = () => [view.canvas.width, view.canvas.height, view.chrome.width, view.chrome.height];
    const before = sizes();
    const buffers = window.__xyAppendBuffers.map((b64) => {
      const bin = atob(b64);
      const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
      return out.buffer;
    });
    // A lost context keeps its last frame on screen: the append must not
    // resize (and so clear) the canvases until the context can draw again.
    view._glLost = true;
    view._applyAppend(window.__xyAppendMsg, buffers);
    const whileLost = { sizes: sizes(), band: !!view._legendBand };
    view._glLost = false;
    view._drawNow();
    view._raf = null;
    document.body.setAttribute("data-xy-lost-append", JSON.stringify({
      before, whileLost, band: !!view._legendBand,
      mounted: !!view.root.querySelector('[data-xy-legend-band="top"]'),
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-lost-append-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_append_while_context_lost_defers_the_band_until_it_can_draw() -> None:
    import base64
    import json

    from conftest import probe_document
    from xy.interaction import append_data

    fig = _streamed_points().figure()
    document = probe_document(fig, _LOST_APPEND_PROBE)
    grid = np.linspace(0.0, 1.0, 30)
    gx, gy = np.meshgrid(grid, grid)
    msg, buffers = append_data(fig, fig.traces[0].id, gx.ravel(), gy.ravel())
    payload_js = (
        "<script>window.__xyAppendMsg = "
        + json.dumps(msg)
        + "; window.__xyAppendBuffers = "
        + json.dumps([base64.b64encode(bytes(b)).decode() for b in buffers])
        + ";</script>"
    )
    document = document.replace("<script", payload_js + "<script", 1)
    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            _chromium(),
            document,
            Path(td) / "lost_append.html",
            "data-xy-lost-append",
            label="lost-context append probe",
        )
    assert payload["whileLost"]["sizes"] == payload["before"], payload
    assert payload["whileLost"]["band"] is False, payload
    assert payload["band"] and payload["mounted"], payload


def _rotating_bars(width: int = 260, height: int = 180, n: int = 4, label: str = "Store"):
    """A y title narrows the plot on the measured pass, so the x labels rotate
    and the bottom axis grows after the band was first sized."""
    stores = [f"{label} {i} branch" for i in range(n)]
    return xy.chart(
        *[
            xy.bar(stores, np.arange(n) * 1000.0 + i * 1e5, name=name)
            for i, name in enumerate(REGIONS)
        ],
        xy.y_axis(label="Revenue in thousands of dollars"),
        xy.legend(loc="outside top"),
        title="Chart",
        width=width,
        height=height,
    )


def test_static_band_rebudgets_after_the_measured_axis_pass() -> None:
    _spec, plot = _layout(_rotating_bars())
    assert plot["legend_band_h"] > 0, plot
    assert plot["h"] >= 40 - 1e-6, plot
    assert plot["y"] + plot["h"] + plot["bottom_axis_room"] <= 180 + 0.5, plot


_AXIS_FIT_PROBE = """
<script>
(async () => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    view._raf = null;
    document.body.setAttribute("data-xy-axis-fit", JSON.stringify({
      band: view._legendBand ? view._legendBand.h : 0,
      plot: [view.plot.y, view.plot.h],
      bottomAxisRoom: view._bottomAxisRoom,
      height: view.size.h,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-axis-fit-error", String((err && err.stack) || err));
  }
})();
</script>
"""


def test_browser_band_rebudgets_after_the_measured_axis_pass() -> None:
    from conftest import probe_document

    with tempfile.TemporaryDirectory() as td:
        payload = run_browser_probe(
            _chromium(),
            # Eight long names rotate in the browser once the plot narrows.
            probe_document(
                _rotating_bars(320, 220, n=8, label="Distribution centre"), _AXIS_FIT_PROBE
            ),
            Path(td) / "axis_fit.html",
            "data-xy-axis-fit",
            label="measured-axis band budget probe",
        )
    y, h = payload["plot"]
    assert payload["band"] > 0, payload
    assert h >= 40 - 1e-6, payload
    assert y + h + payload["bottomAxisRoom"] <= payload["height"] + 0.5, payload
