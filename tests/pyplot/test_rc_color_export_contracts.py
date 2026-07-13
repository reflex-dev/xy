from __future__ import annotations

import io
import struct

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _reset_pyplot_state():
    plt.close("all")
    plt.style.use("default")
    yield
    plt.close("all")
    plt.style.use("default")


def test_nested_rc_context_restores_each_level_and_rcdefaults() -> None:
    original = plt.rcParams["lines.linewidth"]
    with plt.rc_context({"lines.linewidth": 2.0}):
        assert plt.rcParams["lines.linewidth"] == 2.0
        with plt.rc_context({"lines.linewidth": 7.0}):
            assert plt.rcParams["lines.linewidth"] == 7.0
        assert plt.rcParams["lines.linewidth"] == 2.0
    assert plt.rcParams["lines.linewidth"] == original
    plt.rcParams["lines.linewidth"] = 9.0
    plt.rcdefaults()
    assert plt.rcParams["lines.linewidth"] == 1.5


def test_style_use_supports_bounded_dicts_and_ordered_lists() -> None:
    plt.style.use({"lines.linewidth": 3.0})
    assert plt.rcParams["lines.linewidth"] == 3.0
    plt.style.use(["default", {"lines.linewidth": 4.0}])
    assert plt.rcParams["lines.linewidth"] == 4.0
    with pytest.raises(NotImplementedError, match=r"unknown\.style\.key"):
        plt.style.use({"unknown.style.key": 1})
    with pytest.raises(NotImplementedError, match="rcParams dict"):
        plt.style.use("ggplot")


def test_figure_facecolor_rcparam_affects_new_figures() -> None:
    with plt.rc_context({"figure.facecolor": "#123456"}):
        assert plt.figure().get_facecolor() == "#123456"


def test_colormap_extremes_alpha_and_reversal_are_preserved() -> None:
    cmap = plt.colormaps["viridis"].with_extremes(
        bad=("red", 0.25), under="#00ff00", over=("blue", 0.75)
    )
    rgba = cmap(np.array([np.nan, -1.0, 0.5, 2.0]))
    np.testing.assert_allclose(rgba[0], [1.0, 0.0, 0.0, 0.25])
    np.testing.assert_allclose(rgba[1], [0.0, 1.0, 0.0, 1.0])
    np.testing.assert_allclose(rgba[3], [0.0, 0.0, 1.0, 0.75])
    forward = plt.colormaps["viridis"](np.array([0.0, 1.0]))
    reverse = plt.colormaps["viridis_r"](np.array([1.0, 0.0]))
    np.testing.assert_allclose(forward, reverse)


def test_savefig_file_objects_require_format_and_reject_discarded_options() -> None:
    fig, ax = plt.subplots(figsize=(4, 3), dpi=80)
    ax.plot([0, 1], [0, 1])
    with pytest.raises(ValueError, match="requires format"):
        fig.savefig(io.BytesIO())
    output = io.BytesIO()
    fig.savefig(output, format="png")
    assert output.getvalue().startswith(b"\x89PNG\r\n\x1a\n")
    for option in ({"transparent": True}, {"metadata": {"Author": "xy"}}, {"bbox_inches": "tight"}):
        with pytest.raises(NotImplementedError, match="savefig"):
            fig.savefig(io.BytesIO(), format="png", **option)
    for unsupported_format in ("jpeg", "webp", "pdf"):
        with pytest.raises(NotImplementedError, match=unsupported_format):
            fig.savefig(io.BytesIO(), format=unsupported_format)


def test_savefig_dpi_changes_output_dimensions_without_mutating_figure() -> None:
    fig, ax = plt.subplots(figsize=(4, 3), dpi=80)
    ax.plot([0, 1], [0, 1])

    def dimensions(dpi: int) -> tuple[int, int]:
        output = io.BytesIO()
        fig.savefig(output, format="png", dpi=dpi)
        return struct.unpack(">II", output.getvalue()[16:24])

    low = dimensions(60)
    high = dimensions(120)
    assert high[0] == 2 * low[0]
    assert high[1] == 2 * low[1]
    assert fig.get_dpi() == 80
