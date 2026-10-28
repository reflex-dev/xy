"""Opt-in redundancy suppression uses resolved legend entries, not trace count."""

from pathlib import Path

import pytest

import xy
from conftest import probe_document, run_browser_probe
from xy.export import find_chromium


def _marks(case: str):
    """Create deterministic series and encoding cases for visibility checks."""
    if case == "unnamed":
        return [xy.line([0, 1], [1, 2])]
    if case == "single":
        return [xy.line([0, 1], [1, 2], name="SeriesA")]
    if case == "mixed":
        return [xy.line([0, 1], [1, 2], name="SeriesA"), xy.line([0, 1], [2, 1])]
    if case == "multiple":
        return [
            xy.line([0, 1], [1, 2], name="SeriesA"),
            xy.line([0, 1], [2, 1], name="SeriesB"),
        ]
    if case == "categorical":
        return [xy.scatter([0, 1], [1, 2], color=["GroupA", "GroupB"])]
    if case == "single-category":
        return [xy.scatter([0, 1], [1, 2], color=["GroupA", "GroupA"])]
    if case == "continuous":
        return [xy.scatter([0, 1], [1, 2], color=[0.1, 0.9], name="Intensity")]
    if case == "size-encoding":
        return [xy.scatter([0, 1], [1, 2], size=[4, 8], name="Magnitude")]
    raise AssertionError(case)


@pytest.mark.parametrize(
    "case,visible",
    [
        ("unnamed", False),
        ("single", False),
        ("mixed", False),
        ("multiple", True),
        ("categorical", True),
        ("single-category", True),
        ("continuous", True),
        ("size-encoding", True),
    ],
)
def test_auto_legend_visibility_and_exports_match_explicit_policy(case: str, visible: bool) -> None:
    """The browser and both native exporters consume the same resolved boolean."""
    auto = xy.chart(*_marks(case), xy.legend(show="auto"), width=480, height=300)
    explicit = xy.chart(*_marks(case), xy.legend(show=visible), width=480, height=300)
    spec, _ = auto.figure().build_payload()
    assert spec["show_legend"] is visible
    assert auto.to_svg() == explicit.to_svg()
    assert auto.to_image(format="png", scale=1) == explicit.to_image(format="png", scale=1)


@pytest.mark.parametrize("show", [True, False])
def test_explicit_legend_visibility_keeps_its_existing_meaning(show: bool) -> None:
    """Authored booleans retain the existing single-series behavior."""
    chart = xy.chart(*_marks("single"), xy.legend(show=show))
    spec, _ = chart.figure().build_payload()
    assert spec["show_legend"] is show
    assert (">SeriesA</text>" in chart.to_svg()) is show


def test_default_legend_keeps_named_single_series() -> None:
    """Adding automatic visibility must not change the default."""
    chart = xy.chart(*_marks("single"))
    spec, _ = chart.figure().build_payload()
    assert spec["show_legend"] is True
    assert ">SeriesA</text>" in chart.to_svg()


def test_auto_legend_policy_rechecks_resolved_entries_after_figure_changes() -> None:
    """A new named series re-enables an automatic legend on the next payload."""
    chart = xy.chart(*_marks("single"), xy.legend(show="auto"))
    figure = chart.figure()
    assert figure.build_payload()[0]["show_legend"] is False
    figure.line([0, 1], [2, 1], name="SeriesB")
    assert figure.build_payload()[0]["show_legend"] is True


def test_auto_legend_retains_toggle_and_highlight_options() -> None:
    """Visibility policy leaves authored interaction options intact."""
    chart = xy.chart(*_marks("multiple"), xy.legend(show="auto", toggle=False, highlight=False))
    spec, _ = chart.figure().build_payload()
    assert spec["show_legend"] is True
    assert spec["legend"]["toggle"] is False
    assert spec["legend"]["highlight"] is False
    assert "show" not in spec["legend"]


@pytest.mark.parametrize("case,entries", [("single", 0), ("multiple", 2), ("categorical", 2)])
def test_auto_legend_browser_visibility_survives_resizing(
    case: str,
    entries: int,
    tmp_path: Path,
) -> None:
    """The actual client retains the resolved entry count across compact layout."""
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no Chromium available for automatic legend visibility")
    chart = xy.chart(*_marks(case), xy.legend(show="auto"), width=720, height=320)
    probe = r"""
<script>
(() => {
  try {
    const view = window.__fcProbeView;
    view.fluid = true;
    view.fluidH = true;
    const results = [];
    for (const width of [720, 380, 720]) {
      view.root.style.width = width + "px";
      view._resize(width, 320);
      if (view._raf) cancelAnimationFrame(view._raf);
      view._raf = null;
      view._drawNow();
      results.push(view.root.querySelectorAll('[data-xy-slot="legend_item"]').length);
    }
    document.body.setAttribute("data-xy-auto-legend", JSON.stringify({ results }));
  } catch (err) {
    document.body.setAttribute("data-xy-auto-legend-error", String(err.stack || err));
  }
})();
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "auto_legend.html",
        "data-xy-auto-legend",
        label="automatic legend visibility",
    )
    assert result["results"] == [entries] * 3
