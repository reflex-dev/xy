"""Legend rows and annotation labels the browser drew and the exporters did not."""

from __future__ import annotations

import numpy as np

import xy
from xy import _svg
from xy.config import DEFAULT_PALETTE

BRAND = ["#ff5c00", "#111827", "#00b3a4", "#8b5cf6"]


# ---------------------------------------------------------------------------
# Static-export parity for legends and annotation labels
# ---------------------------------------------------------------------------


def categorical_scatter() -> xy.Chart:
    codes = np.array(["alpha", "beta", "gamma"] * 40)
    rng = np.random.default_rng(3)
    return xy.scatter_chart(
        xy.scatter(rng.normal(size=120), rng.normal(size=120), color=codes, size=7),
        xy.legend(),
    )


def test_categorical_legend_rows_reach_static_exports() -> None:
    """The browser drew one row per category; the exporters drew no legend."""
    svg = categorical_scatter().to_svg()
    assert all(category in svg for category in ("alpha", "beta", "gamma"))


def test_categorical_legend_swatches_wear_the_category_colors() -> None:
    entries = _svg.legend_entries(categorical_scatter().figure().build_payload()[0])
    assert [entry["name"] for entry in entries] == ["alpha", "beta", "gamma"]
    assert [entry["style"]["color"] for entry in entries] == DEFAULT_PALETTE[:3]


def test_categorical_legend_follows_the_theme_palette() -> None:
    codes = np.array(["a", "b"] * 20)
    chart = xy.scatter_chart(
        xy.scatter(np.arange(40.0), np.arange(40.0), color=codes),
        xy.legend(),
        xy.theme(palette=BRAND),
    )
    entries = _svg.legend_entries(chart.figure().build_payload()[0])
    assert [entry["style"]["color"] for entry in entries] == BRAND[:2]


def test_named_series_legends_are_unchanged() -> None:
    chart = xy.line_chart(
        xy.line([1, 2], [1, 2], name="north"), xy.line([1, 2], [2, 1], name="south"), xy.legend()
    )
    entries = _svg.legend_entries(chart.figure().build_payload()[0])
    assert [entry["name"] for entry in entries] == ["north", "south"]


def test_unnamed_traces_still_get_no_legend_row() -> None:
    chart = xy.line_chart(xy.line([1, 2], [1, 2]), xy.legend())
    assert _svg.legend_entries(chart.figure().build_payload()[0]) == []


def annotated_chart() -> xy.Chart:
    return xy.line_chart(
        xy.line([1, 2, 3, 4], [1, 2, 3, 4]),
        xy.hline(2.5, text="target", color="#dc2626"),
        xy.vline(3.0, text="launch"),
        xy.y_band(1.2, 1.8, text="tolerance"),
        xy.text(2.0, 1.5, "inline note"),
    )


def test_rule_and_band_labels_reach_the_svg() -> None:
    svg = annotated_chart().to_svg()
    assert all(label in svg for label in ("target", "launch", "tolerance", "inline note"))


def test_rule_and_band_labels_reach_the_native_png(tmp_path) -> None:
    labelled = tmp_path / "labelled.png"
    bare = tmp_path / "bare.png"
    annotated_chart().to_png(str(labelled), width=520, height=320)
    xy.line_chart(
        xy.line([1, 2, 3, 4], [1, 2, 3, 4]),
        xy.hline(2.5, color="#dc2626"),
        xy.vline(3.0),
        xy.y_band(1.2, 1.8),
    ).to_png(str(bare), width=520, height=320)
    assert labelled.read_bytes() != bare.read_bytes()


def test_rule_labels_anchor_where_the_client_puts_them() -> None:
    plot = {"x": 100.0, "y": 50.0, "w": 400.0, "h": 300.0}
    identity = float

    x_rule = _svg._rule_label_anchor({"axis": "x", "value": 7.0}, "rule", identity, identity, plot)
    assert x_rule == (7.0, 56.0, "start", "top")

    y_rule = _svg._rule_label_anchor({"axis": "y", "value": 7.0}, "rule", identity, identity, plot)
    assert y_rule == (494.0, 7.0, "end", "")

    x_band = _svg._rule_label_anchor(
        {"axis": "x", "start": 2.0, "end": 4.0}, "band", identity, identity, plot
    )
    assert x_band == (3.0, 56.0, "middle", "top")


def test_a_rule_label_at_a_non_finite_pixel_is_skipped_not_emitted() -> None:
    """A scale can map a rule off the finite plane; the label must be dropped
    rather than emitted as `x="nan"`, which is an invalid SVG document."""
    plot = {"x": 100.0, "y": 50.0, "w": 400.0, "h": 300.0}
    annotations = [{"kind": "rule", "axis": "y", "value": 1.0, "text": "ghost", "style": {}}]
    marks, labels = _svg._annotation_svg(
        annotations, float, lambda _v: float("inf"), plot, 600.0, 400.0
    )
    assert labels == []
    assert not any("nan" in mark or "inf" in mark.lower() for mark in labels)
