"""P1 audit fixes: ticklabel_format export, span autoscale/legend, unusable
locators, and datetime coordinates outside plot/scatter/bar.

Reference numbers marked *mpl 3.11* were recorded against matplotlib 3.11.1;
the cross-check tests re-derive them when matplotlib is importable.
"""

from __future__ import annotations

import datetime as dt
import io
import re

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._artists import Line2D
from xy.pyplot._ticker import FuncFormatter, ScalarFormatter


def _ms(stamp: str) -> float:
    return float(np.datetime64(stamp, "ms").astype(np.int64))


def _export_all(fig) -> dict[str, bytes]:
    out = {}
    for fmt in ("png", "svg", "html"):
        buffer = io.BytesIO()
        fig.savefig(buffer, format=fmt)
        out[fmt] = buffer.getvalue()
    assert out["png"][:4] == b"\x89PNG"
    return out


def _built(ax):
    return ax._build_chart(640, 480).figure()


@pytest.fixture(autouse=True)
def _close_all():
    yield
    plt.close("all")


# ---------------------------------------------------------------------------
# A. ticklabel_format must translate into a label policy, never a crash
# ---------------------------------------------------------------------------


def test_ticklabel_format_plain_exports_fixed_labels():
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [1e6, 1e6 + 1, 1e6 + 2])
    ax.ticklabel_format(style="plain", useOffset=False)
    exports = _export_all(fig)
    labels = _built(ax).axis_options["y"]["tick_labels"]
    # mpl 3.11 with useOffset=False: full fixed values with the shared
    # 2-decimal precision of the 0.25 tick step (the shim lists in-view ticks
    # only; matplotlib's tick list also carries the out-of-view 999999.75).
    assert labels[:3] == ["1000000.00", "1000000.25", "1000000.50"]
    assert all("e" not in label for label in labels)
    assert b"1000000.00" in exports["svg"]


def test_ticklabel_format_plain_default_offset_is_written_in_full():
    # Matplotlib would factor "+1e6" into an offset text; the shim has no
    # offset-text slot, so the labels carry the full value (documented noop).
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [1e6, 2e6, 3e6])
    ax.ticklabel_format(style="plain")
    labels = _built(ax).axis_options["y"]["tick_labels"]
    assert labels[:3] == ["1000000", "1250000", "1500000"]  # mpl 3.11, in-view ticks
    _export_all(fig)


def test_ticklabel_format_sci_writes_shared_exponent_on_each_label():
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [1e6, 2e6, 3e6])
    ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
    labels = _built(ax).axis_options["y"]["tick_labels"]
    # mpl 3.11 mantissas 1.00, 1.25, ... with the "1e6" exponent as offset text.
    assert labels[:3] == ["1.00e6", "1.25e6", "1.50e6"]
    # axis="y" leaves the x axis on the engine's own labels.
    assert _built(ax).axis_options["x"].get("tick_labels") is None
    _export_all(fig)


def test_ticklabel_format_sci_within_scilimits_stays_plain():
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [1e6, 2e6, 3e6])
    ax.ticklabel_format(style="sci", scilimits=(-5, 7))  # 1e6 is inside
    labels = _built(ax).axis_options["y"]["tick_labels"]
    assert labels[:2] == ["1000000", "1250000"]


def test_ticklabel_format_math_text_uses_unicode_power():
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [1e6, 2e6, 3e6])
    ax.ticklabel_format(style="sci", scilimits=(0, 0), useMathText=True)
    labels = _built(ax).axis_options["y"]["tick_labels"]
    assert labels[0] == "1.00×10⁶"  # noqa: RUF001 - intentional multiplication sign
    _export_all(fig)


def test_ticklabel_format_configures_the_scalar_formatter_like_matplotlib():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2])
    ax.ticklabel_format(axis="x", style="sci", scilimits=(-2, 3), useOffset=False)
    formatter = ax.xaxis.get_major_formatter()
    assert isinstance(formatter, ScalarFormatter)
    assert formatter.get_useOffset() is False
    assert ax.yaxis.get_major_formatter() is not formatter
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, p: "x"))
    with pytest.raises(AttributeError):  # mpl: only works with the ScalarFormatter
        ax.ticklabel_format(axis="x", style="plain")


def test_ticklabel_format_cross_check_against_matplotlib():
    mpl = pytest.importorskip("matplotlib")
    mpl.use("Agg")
    import matplotlib.pyplot as mplt

    ref_fig, ref_ax = mplt.subplots()
    ref_ax.plot([0, 1, 2], [1e6, 1e6 + 1, 1e6 + 2])
    ref_ax.ticklabel_format(style="plain", useOffset=False)
    ref_fig.canvas.draw()
    reference = [t.get_text().replace("\N{MINUS SIGN}", "-") for t in ref_ax.get_yticklabels()]
    mplt.close(ref_fig)

    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [1e6, 1e6 + 1, 1e6 + 2])
    ax.ticklabel_format(style="plain", useOffset=False)
    labels = _built(ax).axis_options["y"]["tick_labels"]
    assert set(labels) <= set(reference)
    assert len(labels) >= 5


# ---------------------------------------------------------------------------
# B. spans and rules: autoscale on their own axis, label= reaches the legend
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("draw", "xlim", "ylim"),
    [
        # mpl 3.11 reference limits for a [0, 2] x [0, 4] line plus the artist.
        (lambda ax: (ax.axvspan(-5, -4), ax.axhline(10)), (-5.35, 2.35), (-0.5, 10.5)),
        (lambda ax: ax.axhline(10), (-0.1, 2.1), (-0.5, 10.5)),
        (lambda ax: ax.axvline(10), (-0.5, 10.5), (-0.2, 4.2)),
        (lambda ax: ax.axhspan(6, 8), (-0.1, 2.1), (-0.4, 8.4)),
        (lambda ax: ax.axvspan(3, 4), (-0.2, 4.2), (-0.2, 4.2)),
        # Fractional bounds never touch the perpendicular axis.
        (lambda ax: ax.axhline(10, xmin=0.2, xmax=0.8), (-0.1, 2.1), (-0.5, 10.5)),
        (lambda ax: ax.axvspan(3, 4, ymin=0.2, ymax=0.8), (-0.2, 4.2), (-0.2, 4.2)),
        (lambda ax: ax.axhline(-1), (-0.1, 2.1), (-1.25, 4.25)),
    ],
)
def test_spans_and_rules_autoscale_on_their_own_axis(draw, xlim, ylim):
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [0, 2, 4])
    draw(ax)
    assert ax.get_xlim() == pytest.approx(xlim)
    assert ax.get_ylim() == pytest.approx(ylim)
    _export_all(fig)


def test_non_finite_rule_does_not_autoscale():
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [0, 2, 4])
    ax.axhline(np.nan)  # mpl 3.11: dataLim ignores the NaN position
    assert ax.get_xlim() == pytest.approx((-0.1, 2.1))
    assert ax.get_ylim() == pytest.approx((-0.2, 4.2))


def test_spans_autoscale_cross_check_against_matplotlib():
    mpl = pytest.importorskip("matplotlib")
    mpl.use("Agg")
    import matplotlib.pyplot as mplt

    def scenario(ax):
        ax.plot([0, 1, 2], [0, 2, 4])
        ax.axvspan(-5, -4)
        ax.axhline(10)
        ax.axhspan(-3, -2, xmin=0.1, xmax=0.4)
        ax.axvline(7, ymin=0.5)

    ref_fig, ref_ax = mplt.subplots()
    scenario(ref_ax)
    expected = (tuple(map(float, ref_ax.get_xlim())), tuple(map(float, ref_ax.get_ylim())))
    mplt.close(ref_fig)
    fig, ax = plt.subplots()
    scenario(ax)
    assert ax.get_xlim() == pytest.approx(expected[0])
    assert ax.get_ylim() == pytest.approx(expected[1])


def test_span_only_axes_autoscale_like_matplotlib_dataless_axis():
    fig, ax = plt.subplots()
    ax.axvspan(3, 4)
    assert ax.get_xlim() == pytest.approx((2.95, 4.05))  # mpl 3.11
    assert ax.get_ylim() == (0.0, 1.0)


def test_span_autoscale_reaches_the_exported_chart():
    fig, ax = plt.subplots(figsize=(7.2, 4.0), dpi=100)
    ax.plot([0, 1, 2], [0, 1, 4], label="data")
    ax.axvspan(-5, -4, color="#d0342c", alpha=0.3, label="outage window")
    ax.axhline(10, color="#16a34a", linestyle="--", label="target")
    ax.legend(loc="upper left")
    assert ax.get_xlim() == pytest.approx((-5.35, 2.35))
    assert ax.get_ylim() == pytest.approx((-0.5, 10.5))
    # The built axes carry the dataLim-based limits as their exact domain
    # (matplotlib's margins are already inside them, so no `margin` rides along).
    options = _built(ax).axis_options
    assert options["x"]["domain"] == pytest.approx((-5.35, 2.35))
    assert options["y"]["domain"] == pytest.approx((-0.5, 10.5))
    assert options["x"].get("margin") is None and options["y"].get("margin") is None
    svg = _export_all(fig)["svg"]
    x_ticks = [float(t) for t in re.findall(rb'text-anchor="middle">(-?[\d.]+)<', svg)]
    y_ticks = [float(t) for t in re.findall(rb'text-anchor="end">(-?[\d.]+)<', svg)]
    assert min(x_ticks) <= -5 and max(x_ticks) >= 2  # the span sits inside the view
    assert min(y_ticks) <= 0 and max(y_ticks) >= 10  # and so does the rule
    # A span-free plot keeps the engine's own margin-based autoscale.
    plain_fig, plain_ax = plt.subplots()
    plain_ax.plot([0, 1, 2], [0, 1, 4])
    plain = _built(plain_ax).axis_options
    assert plain["x"].get("domain") is None and plain["x"]["margin"] == pytest.approx(0.05)


def test_twin_axis_span_autoscale_reaches_the_exported_chart():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    twin = ax.twinx()
    twin.plot([0, 1], [0, 1])
    twin.axhline(5)
    assert twin.get_ylim() == pytest.approx((-0.25, 5.25))
    assert _built(ax).axis_options["y2"]["domain"] == pytest.approx((-0.25, 5.25))
    assert _built(ax).axis_options["y"].get("domain") is None  # host y is untouched
    _export_all(fig)


def test_span_labels_reach_legend_with_matching_swatches():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="b")
    rule = ax.axhline(0.5, label="h", color="red", linestyle="--")
    ax.axvspan(0.2, 0.4, label="s")
    ax.axvline(0.3, label="v")
    ax.axhspan(0.6, 0.7, label="hs", color="green", alpha=0.5)
    handles, labels = ax.get_legend_handles_labels()
    assert labels == ["b", "h", "s", "v", "hs"]  # mpl 3.11 order
    assert isinstance(handles[1], Line2D) and isinstance(handles[3], Line2D)
    assert rule.get_label() == "h"
    # The label is a legend entry, never text drawn beside the rule.
    assert "text" not in rule._entry["kwargs"]
    ax.legend()
    items = _built(ax).legend_options["items"]
    assert [item["name"] for item in items] == ["b", "h", "s", "v", "hs"]
    assert [item["kind"] for item in items] == ["line", "line", "area", "line", "area"]
    assert items[1]["style"]["color"] == "red" and items[1]["style"].get("dash")
    assert items[4]["style"] == {"color": "green", "opacity": 0.5}
    # Unlabeled defaults are spelled out so the swatch matches the drawn band.
    assert items[2]["style"] == {"color": "#64748b", "opacity": 0.14}
    exports = _export_all(fig)
    assert b"hs" in exports["svg"]


def test_span_set_label_after_creation_and_underscore_labels():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="b")
    rule = ax.axhline(0.5)
    ax.axvspan(0.2, 0.4, label="_hidden")
    rule.set_label("late")
    assert ax.get_legend_handles_labels()[1] == ["b", "late"]
    ax.legend()
    assert [item["name"] for item in _built(ax).legend_options["items"]] == ["b", "late"]
    _export_all(fig)


def test_unlabeled_spans_leave_the_engine_legend_alone():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="b")
    ax.axhline(0.5)
    ax.legend()
    assert "items" not in _built(ax).legend_options


# ---------------------------------------------------------------------------
# C. locators without a usable tick_values() must not break the build
# ---------------------------------------------------------------------------


class _AbstractLocator:
    """Mimics matplotlib's Locator base: tick_values() is abstract."""

    axis = None

    def tick_values(self, vmin, vmax):
        raise NotImplementedError("Derived must override")


class _CallableLocator(_AbstractLocator):
    def __init__(self):
        self.axis = object()

    def __call__(self):
        return [0.25, 0.5, 0.75]


def test_unusable_minor_locator_keeps_native_date_ticks():
    fig, ax = plt.subplots()
    dates = np.arange("2012-01-01", "2012-05-01", dtype="datetime64[D]")
    ax.plot(dates, np.linspace(0.0, 1.0, len(dates)))
    ax.xaxis.set_minor_locator(_AbstractLocator())
    ax.xaxis.set_major_locator(_AbstractLocator())
    options = _built(ax).axis_options["x"]
    assert options.get("tick_values") is None  # engine's own date ticks
    assert options.get("minor_tick_values") is None
    exports = _export_all(fig)
    assert b"Feb" in exports["svg"] or b"2012-02" in exports["svg"]


def test_locator_with_axis_falls_back_to_calling_it():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.xaxis.set_major_locator(_CallableLocator())
    assert _built(ax).axis_options["x"]["tick_values"] == [0.25, 0.5, 0.75]


def test_pandas_period_tickers_are_noops_on_both_tiers():
    pd = pytest.importorskip("pandas")
    index = pd.date_range("2012-01-01", periods=120, freq="D")
    fig, ax = plt.subplots()
    pd.Series(np.linspace(4000.0, 5000.0, 120), index=index).plot(ax=ax)
    assert type(ax.xaxis.get_minor_locator()).__module__.startswith("xy.")
    options = _built(ax).axis_options["x"]
    assert options.get("tick_values") is None  # engine's own date ticks
    _export_all(fig)


# ---------------------------------------------------------------------------
# D. datetime coordinates in limits, ticks and fills
# ---------------------------------------------------------------------------

_DATES = [dt.datetime(2024, 1, 1) + dt.timedelta(days=i) for i in range(3)]


def _datetime_likes(stamp: str):
    day = dt.date.fromisoformat(stamp)
    values = [
        dt.datetime(day.year, day.month, day.day),
        day,
        np.datetime64(stamp),
    ]
    pd = pytest.importorskip("pandas")
    values.append(pd.Timestamp(stamp))
    return values


@pytest.mark.parametrize("index", range(4))
def test_set_xlim_accepts_every_datetime_like_plot_accepts(index):
    left = _datetime_likes("2023-12-31")[index]
    right = _datetime_likes("2024-01-05")[index]
    fig, ax = plt.subplots()
    ax.plot(_DATES, [1, 2, 3])
    before = ax.get_xlim()
    ax.set_xlim(left, right)
    assert ax.get_xlim() == (_ms("2023-12-31"), _ms("2024-01-05"))
    # Same unit plot() reports: ms since epoch, with the automatic margin.
    assert before == pytest.approx((_ms("2023-12-31T21:36"), _ms("2024-01-03T02:24")))
    ax.set_xlim((left, None))
    assert ax.get_xlim() == (_ms("2023-12-31"), _ms("2024-01-05"))
    _export_all(fig)


def test_set_ylim_and_xlim_wrapper_accept_datetimes():
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], _DATES)
    ax.set_ylim(dt.datetime(2023, 12, 31), dt.datetime(2024, 1, 5))
    assert ax.get_ylim() == (_ms("2023-12-31"), _ms("2024-01-05"))
    plt.figure(fig.number)
    plt.ylim(dt.datetime(2024, 1, 1), np.datetime64("2024-01-04"))
    assert ax.get_ylim() == (_ms("2024-01-01"), _ms("2024-01-04"))
    with pytest.raises(TypeError):
        ax.set_xlim(object(), 1.0)


def test_set_xticks_accepts_datetime_likes():
    pd = pytest.importorskip("pandas")
    fig, ax = plt.subplots()
    ax.plot(_DATES, [1, 2, 3])
    ax.set_xticks(
        [dt.datetime(2024, 1, 1), np.datetime64("2024-01-03"), pd.Timestamp("2024-01-02")]
    )
    assert ax.get_xticks() == pytest.approx(
        [_ms("2024-01-01"), _ms("2024-01-03"), _ms("2024-01-02")]
    )
    ax.set_yticks([1, 2])
    fig2, ax2 = plt.subplots()
    ax2.plot([1, 2, 3], _DATES)
    ax2.set_yticks(np.asarray(["2024-01-01", "2024-01-02"], dtype="datetime64[ns]"))
    assert ax2.get_yticks() == pytest.approx([_ms("2024-01-01"), _ms("2024-01-02")])
    _export_all(fig)
    _export_all(fig2)


def test_fill_between_accepts_datetimes_and_keeps_the_time_axis():
    fig, ax = plt.subplots()
    ax.plot(_DATES, [1, 2, 3])
    plotted = ax.get_xlim()
    ax.fill_between(_DATES, [1, 2, 3], [0, 0, 0], alpha=0.3)
    assert ax.get_xlim() == plotted
    # Without any plot() call the fill alone must still make a date axis.
    fig2, ax2 = plt.subplots()
    ax2.fill_between(np.asarray(_DATES, dtype="datetime64[ns]"), [1, 2, 3])
    assert ax2._axis_holds_datetimes("x")
    assert ax2.get_xlim() == pytest.approx(plotted)
    # The fill-only chart gets the same time-axis labels as the plot() chart.
    ticks = re.compile(rb'text-anchor="middle">([^<]*)<')
    assert ticks.findall(_export_all(fig2)["svg"]) == ticks.findall(_export_all(fig)["svg"])


def test_fill_between_datetime_where_and_interpolate():
    fig, ax = plt.subplots()
    x = np.asarray(_DATES + [dt.datetime(2024, 1, 4)], dtype="datetime64[ns]")
    y = np.asarray([0.0, 2.0, -1.0, 3.0])
    ax.fill_between(x, y, 0.0, where=y > 0, interpolate=True)
    entries = [entry for entry in ax._entries if entry["kind"] == "area"]
    assert entries and all(np.issubdtype(np.asarray(e["x"]).dtype, np.datetime64) for e in entries)
    assert ax._axis_holds_datetimes("x")
    _export_all(fig)


def test_fill_betweenx_accepts_datetime_y():
    fig, ax = plt.subplots()
    ax.fill_betweenx(_DATES, [1, 2, 3], [0, 0, 0])
    assert ax._axis_holds_datetimes("y")
    assert ax.get_ylim() == pytest.approx((_ms("2023-12-31T21:36"), _ms("2024-01-03T02:24")))
    reference_fig, reference_ax = plt.subplots()
    reference_ax.plot([1, 2, 3], _DATES)
    ticks = re.compile(rb'text-anchor="end">([^<]*)<')
    assert ticks.findall(_export_all(fig)["svg"]) == ticks.findall(
        _export_all(reference_fig)["svg"]
    )
