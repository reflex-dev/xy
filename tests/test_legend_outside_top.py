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

import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from conftest import run_browser_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import xy  # noqa: E402
from xy import _svg, _validate  # noqa: E402
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
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no chromium available for the outside-top legend probe")
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
