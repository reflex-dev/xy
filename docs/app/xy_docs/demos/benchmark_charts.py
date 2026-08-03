"""Live XY chart for the public interactive-UX benchmark documentation."""

from __future__ import annotations

import reflex as rx

import reflex_xy
import xy

XY_COLOR = "#6E56CF"
XY_EXACT_COLOR = "#A594E8"
MATPLOTLIB_COLOR = "#8B8D98"
PLOTLY_COLOR = "#B9BBC6"
FAILURE_COLOR = "#D64545"
SERIES = (
    ("XY", XY_COLOR),
    ("XY · density off", XY_EXACT_COLOR),  # noqa: RUF001
    ("Matplotlib", MATPLOTLIB_COLOR),
    ("Plotly", PLOTLY_COLOR),
)

_CHART_CLASS = (
    "w-full [--benchmark-bg:#ffffff] [--benchmark-plot:#fcfcfd] "
    "[--benchmark-grid:#e8e8ec] [--benchmark-axis:#d9d9e0] "
    "[--benchmark-text:#60646c] dark:[--benchmark-bg:#09090b] "
    "dark:[--benchmark-plot:#111113] dark:[--benchmark-grid:#27272a] "
    "dark:[--benchmark-axis:#3f3f46] dark:[--benchmark-text:#d4d4d8]"
)
_CARD_CLASS = (
    "w-full overflow-hidden rounded-xl border border-secondary-4 bg-white "
    "shadow-[0_12px_32px_#1c20240f] dark:bg-black"
)


def _theme() -> xy.Theme:
    """Return the neutral benchmark theme shared by the docs site."""
    return xy.theme(
        background="var(--benchmark-bg, #ffffff)",
        plot_background="var(--benchmark-plot, #fcfcfd)",
        grid_color="var(--benchmark-grid, #e8e8ec)",
        axis_color="var(--benchmark-axis, #d9d9e0)",
        text_color="var(--benchmark-text, #60646c)",
    )


def _legend() -> rx.Component:
    """Render the benchmark series legend."""
    return rx.el.div(
        *(
            rx.el.div(
                rx.el.span(
                    class_name="size-2.5 shrink-0 rounded-full",
                    style={"background": color},
                    aria_hidden="true",
                ),
                rx.el.span(label),
                class_name=(
                    "inline-flex items-center gap-1 whitespace-nowrap text-[0.65625rem] "
                    "font-semibold text-secondary-11"
                ),
            )
            for label, color in SERIES
        ),
        class_name="flex flex-wrap items-center gap-x-3 gap-y-2",
        aria_label="Benchmark series legend",
    )


_SIZES = [
    10_000,
    100_000,
    500_000,
    1_000_000,
    2_500_000,
    5_000_000,
    10_000_000,
    25_000_000,
    50_000_000,
    100_000_000,
]
_XY_VALUES = [0.071, 0.072, 0.075, 0.084, 0.083, 0.089, 0.083, 0.077, 0.076, 0.081]
_XY_EXACT_VALUES = [
    0.085,
    0.074,
    0.087,
    0.098,
    0.111,
    0.144,
    0.206,
    0.424,
    0.645,
    1.343,
]
_MATPLOTLIB_VALUES = [0.086, 0.115, 0.224, 0.357, 0.758, 1.424, 2.804, 6.838, 13.385]
_PLOTLY_VALUES = [0.341, 0.373, 0.477, 0.614, 1.033, 1.785, 3.367, 9.794]


def _series(values: list[float], name: str, color: str, width: float) -> tuple[xy.Mark, xy.Mark]:
    """Return a line and a dot for every measured benchmark cell."""
    sizes = _SIZES[: len(values)]
    return (
        xy.line(sizes, values, name=name, color=color, width=width),
        xy.scatter(x=sizes, y=values, color=color, size=6.5),
    )


_RENDER_TIME_CHART = xy.line_chart(
    *_series(_XY_VALUES, "XY", XY_COLOR, 3),
    *_series(_XY_EXACT_VALUES, "XY · density off", XY_EXACT_COLOR, 2.5),  # noqa: RUF001
    *_series(_MATPLOTLIB_VALUES, "Matplotlib WebAgg", MATPLOTLIB_COLOR, 2),
    *_series(_PLOTLY_VALUES, "Plotly scattergl", PLOTLY_COLOR, 2),
    xy.line(
        [_SIZES[7], _SIZES[8]],
        [_PLOTLY_VALUES[-1], _PLOTLY_VALUES[-1]],
        color=FAILURE_COLOR,
        width=1.5,
        dash="dashed",
        opacity=0.6,
    ),
    xy.marker(
        _SIZES[8],
        _PLOTLY_VALUES[-1],
        size=10,
        symbol="cross",
        color=FAILURE_COLOR,
    ),
    xy.text(
        _SIZES[8],
        _PLOTLY_VALUES[-1],
        "fails at 50M",
        dx=12,
        dy=4,
        anchor="start",
        color=FAILURE_COLOR,
    ),
    xy.line(
        [_SIZES[8], _SIZES[9]],
        [_MATPLOTLIB_VALUES[-1], _MATPLOTLIB_VALUES[-1]],
        color=FAILURE_COLOR,
        width=1.5,
        dash="dashed",
        opacity=0.6,
    ),
    xy.marker(
        _SIZES[9],
        _MATPLOTLIB_VALUES[-1],
        size=10,
        symbol="cross",
        color=FAILURE_COLOR,
    ),
    xy.text(
        70_710_678,
        _MATPLOTLIB_VALUES[-1],
        "fails at 100M",
        dy=18,
        anchor="middle",
        color=FAILURE_COLOR,
    ),
    xy.tooltip(format={"y": ".3f s"}),
    xy.legend(show=False),
    xy.modebar(show=False),
    xy.interaction_config(navigation=False),
    xy.x_axis(
        label="Points plotted",
        type_="log",
        domain=(8_000, 125_000_000),
        tick_values=[10_000, 100_000, 1_000_000, 10_000_000, 100_000_000],
        tick_labels=["10k", "100k", "1M", "10M", "100M"],
        style={"grid_width": 1, "grid_opacity": 1},
    ),
    xy.y_axis(
        label="Time until every point is on screen",
        domain=(0, 14.6),
        tick_values=[0, 2, 4, 6, 8, 10, 12, 14],
        tick_labels=["0", "2", "4", "6", "8", "10", "12", "14 s"],
        style={"grid_width": 1, "grid_opacity": 1},
    ),
    _theme(),
    width="100%",
    height=500,
    padding=(24, 30, 58, 92),
    class_name=_CHART_CLASS,
)


def interactive_ux_demo() -> rx.Component:
    """Render the published 10k-to-100M interactive UX comparison."""
    return rx.el.section(
        rx.el.div(
            rx.el.div(
                rx.el.h2(
                    "Live interactive render time",
                    class_name="text-xl font-semibold tracking-[-0.02em] text-secondary-12",
                ),
                rx.el.p(
                    "Correct and stable canvas · Apple M5 Pro · lower is better",  # noqa: RUF001
                    class_name="mt-1 text-sm font-medium text-secondary-10",
                ),
                class_name="min-w-0",
            ),
            _legend(),
            class_name="flex flex-col gap-4 px-5 pt-5 sm:px-6 sm:pt-7",
        ),
        rx.el.div(
            reflex_xy.chart(_RENDER_TIME_CHART, height="500px"),
            class_name="px-2 pb-2 sm:px-4 sm:pb-4",
        ),
        class_name=_CARD_CLASS,
        aria_label="Interactive render-time benchmark from 10,000 to 100 million points",
    )


__all__ = ["interactive_ux_demo"]
